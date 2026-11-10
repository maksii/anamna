"""Audit logging: no file name reaches the intake log, an upstream error body
stays out of the exception message that callers log, and the archive's reclaim
refuses to run without an explicit ``--yes``.

HTTP is faked at each module's ``_opener``, as in test_audit_integrations.
"""

from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from anamna import integrations, openwearables, paperless

INTAKE = Path(__file__).resolve().parents[2] / "src" / "anamna" / "ingest" / "intake.py"


class _Refuses:
    """Every request is answered with an HTTP error carrying ``text`` as its body."""

    def __init__(self, code: int, text: bytes):
        self._error = urllib.error.HTTPError("https://upstream.test/", code, "reason", {}, io.BytesIO(text))

    def open(self, request, timeout=None):
        raise self._error


BODY = b'{"detail": "Ivanov Petro scan 2024.pdf"}'


def test_intake_log_lines_never_name_a_file():
    offending = []
    for number, line in enumerate(INTAKE.read_text(encoding="utf-8").splitlines(), 1):
        if "logger." not in line:
            continue
        if ".filename" in line or ".name)" in line or "path)" in line:
            offending.append((number, line.strip()))
    assert offending == []


def test_integrations_error_message_is_the_status_alone(monkeypatch, caplog):
    monkeypatch.setattr(integrations, "_opener", _Refuses(500, BODY))
    with caplog.at_level(logging.DEBUG, logger="anamna.integrations"):
        with pytest.raises(integrations.IntegrationError) as caught:
            integrations._request("https://oura.test/v2/usercollection/sleep")
    assert str(caught.value) == "HTTP 500"
    assert caught.value.status == 500
    assert "Ivanov" not in str(caught.value)
    assert "Ivanov" in caplog.text  # the body is still available at DEBUG


def test_paperless_error_message_is_the_status_alone(monkeypatch, caplog):
    monkeypatch.setattr(paperless, "_opener", _Refuses(500, BODY))
    with caplog.at_level(logging.DEBUG, logger="anamna.paperless"):
        with pytest.raises(paperless.PaperlessError) as caught:
            paperless._request("http://paperless.test", "tok", "/api/documents/")
    assert str(caught.value) == "HTTP 500"
    assert caught.value.status == 500
    assert caught.value.body == BODY.decode("utf-8")
    assert "Ivanov" in caplog.text


def test_openwearables_error_message_is_the_status_alone(monkeypatch, caplog):
    monkeypatch.setattr(openwearables, "_opener", _Refuses(500, BODY))
    with caplog.at_level(logging.DEBUG, logger="anamna.openwearables"):
        with pytest.raises(openwearables.OpenWearablesError) as caught:
            openwearables._request("https://openwearables.test/api/v1/users")
    assert str(caught.value) == "HTTP 500"
    assert caught.value.status == 500
    assert "Ivanov" not in str(caught.value)
    assert "Ivanov" in caplog.text  # the body is still available at DEBUG


def test_paperless_test_button_keeps_the_body_it_classifies_by(monkeypatch):
    # web/app.py decides "blocked by a proxy" from the text of this message, so
    # the test-connection path keeps the old "HTTP NNN: body" form.
    monkeypatch.setattr(paperless, "_opener", _Refuses(403, b"<!DOCTYPE html><html>error code: 1010</html>"))
    with pytest.raises(paperless.PaperlessError) as caught:
        paperless.test_connection("http://paperless.test", "tok")
    assert str(caught.value).startswith("HTTP 403: <!DOCTYPE html>")
    assert paperless.blocked_by_proxy(str(caught.value))


def test_reclaim_refuses_to_run_without_yes(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, "-m", "anamna.openwearables_archive", "reclaim"],
        env={**os.environ, "ANAMNA_DB": str(tmp_path / "x.sqlite3")},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 2
    assert "--yes" in result.stderr
    assert "backup" in result.stderr
