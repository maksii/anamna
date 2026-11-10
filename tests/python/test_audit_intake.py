"""Archive intake refuses member names that escape the extraction directory or
name a Windows device, leaves no partial expansion behind, and keeps its worker
alive through a failing iteration.

Synthetic zips are built in tmp_path only.
"""

from __future__ import annotations

import io
import sqlite3
import threading
import zipfile
from pathlib import Path

from anamna.ingest import intake


def test_archive_member_names_cannot_move_the_device_root(tmp_path: Path):
    path = tmp_path / "escape.zip"
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr(zipfile.ZipInfo("../../di_connect/a.json"), b"{}")

    adapter, root = intake.detect_archive_adapter(path)

    assert adapter is None
    assert root == ""
    assert ".." not in root


def test_unsafe_rejects_reserved_device_names():
    for name in ("nul.pdf", "a/COM1.json", "LPT9"):
        assert intake._unsafe(name), name
    for name in ("console.pdf", "a/b.pdf"):
        assert not intake._unsafe(name), name
    assert intake._unsafe("../x")


def test_corrupt_nested_archive_leaves_nothing_behind(tmp_path: Path):
    # The inner archive opens and its first member extracts; the second member's
    # CRC then fails. The partial expansion must not survive that failure.
    inner_buffer = io.BytesIO()
    with zipfile.ZipFile(inner_buffer, "w", zipfile.ZIP_STORED) as inner:
        inner.writestr("a.txt", b"alpha-payload")
        inner.writestr("b.txt", b"bravo-payload")
    inner_bytes = inner_buffer.getvalue().replace(b"bravo-payload", b"bravo-xxxxxxx")
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as bundle:
        bundle.writestr("inner.zip", inner_bytes)

    intake.expand_archive(outer, tmp_path / "out")

    assert not (tmp_path / "out" / "inner").exists()


def test_worker_survives_a_failing_iteration(monkeypatch):
    calls: list[object] = []

    def claim(settings):
        calls.append(settings)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return None

    monkeypatch.setattr(intake, "_claim", claim)
    monkeypatch.setattr(intake, "_pending", lambda settings: False)
    monkeypatch.setattr(intake.time, "sleep", lambda seconds: None)
    monkeypatch.setitem(intake._WORKERS, "k", threading.current_thread())

    intake._drain(None, "k")

    assert len(calls) == 2
    assert "k" not in intake._WORKERS
