"""Memoised reads, the explorer's opening chart, upload placement and cleanup.

Each test pins one fix in `web/app.py`: the device history is built once per
change of the owner's device data, a memoised card is rebuilt when the calendar
day changes, a finished upload never overwrites a name another upload holds,
the explorer's opening chart asks for the bar it draws at, and a deleted
document's rendered pages go with its bytes.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.ingest.pipeline import ensure_vendor
from anamna.security import create_user
from anamna.web import app as web

PASSWORD = "a-long-local-password"
REAL_DATE = date


def settings_for(tmp_path: Path) -> Settings:
    sources = tmp_path / "sources"
    sources.mkdir(exist_ok=True)
    return Settings(
        database_path=tmp_path / "health.sqlite3",
        source_dir=sources,
        secret_key="audit-perf-secret",
        session_days=1,
    )


def owner_of(tmp_path: Path) -> tuple[Settings, str]:
    settings = settings_for(tmp_path)
    migrate(settings)
    return settings, create_user(settings, "perf@example.test", "Perf", PASSWORD)


def add_device_day(settings: Settings, user_id: str) -> None:
    """One daily device row for the owner, with the parents its foreign keys need."""
    patient_id = f"patient-{user_id}"
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Perf Patient', '1990-03-14', 'male', ?)""",
            (patient_id, user_id, utc_now()),
        )
        vendor_id = ensure_vendor(connection, "Perf Watch", None)
        connection.execute(
            """INSERT INTO device_imports(id, owner_user_id, patient_id, vendor_id, adapter_key,
                   source_path, source_fingerprint, source_bytes, imported_at)
               VALUES ('import-1', ?, ?, ?, 'test', 'export.csv', 'fingerprint-1', 10, ?)""",
            (user_id, patient_id, vendor_id, utc_now()),
        )
        connection.execute(
            """INSERT INTO device_metric_days(id, owner_user_id, patient_id, import_id, source_name,
                   source_vendor, metric_key, metric_name, category, day, aggregation, unit, value,
                   sample_count, created_at)
               VALUES ('day-1', ?, ?, 'import-1', 'Watch', 'Perf Watch', 'steps', 'Steps', 'activity',
                   '2026-01-05', 'sum', 'count', 1234.0, 1, ?)""",
            (user_id, patient_id, utc_now()),
        )


def test_device_history_is_built_once_until_the_owner_device_data_changes(tmp_path, monkeypatch):
    settings, user_id = owner_of(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        web, "device_history_summary", lambda connection, owner: calls.append(owner) or [{"metric_key": "steps"}]
    )
    with connect(settings) as connection:
        assert web.device_history(connection, user_id) == [{"metric_key": "steps"}]
        web.device_history(connection, user_id)
        assert len(calls) == 1
    add_device_day(settings, user_id)
    with connect(settings) as connection:
        web.device_history(connection, user_id)
        assert len(calls) == 2
        web.invalidate_catalog(user_id)
        web.device_history(connection, user_id)
        assert len(calls) == 3


def test_memoised_cards_are_rebuilt_when_the_calendar_day_changes(tmp_path, monkeypatch):
    settings, user_id = owner_of(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(web, "device_history_summary", lambda connection, owner: calls.append(owner) or [])

    class Tomorrow(REAL_DATE):
        @classmethod
        def today(cls):
            return REAL_DATE.fromordinal(REAL_DATE.today().toordinal() + 1)

    with connect(settings) as connection:
        web.device_history(connection, user_id)
        web.device_history(connection, user_id)
        assert len(calls) == 1
        monkeypatch.setattr(web, "date", Tomorrow)
        web.device_history(connection, user_id)
        assert len(calls) == 2


def test_place_exclusively_never_overwrites_a_name_another_upload_holds(tmp_path):
    existing = tmp_path / "scan.pdf"
    existing.write_bytes(b"another upload")
    free = tmp_path / "scan-1.pdf"
    partial = tmp_path / "partial"
    partial.write_bytes(b"new arrival")
    picks = iter([existing, free])

    placed = web._place_exclusively(partial, lambda: next(picks))

    assert placed == free
    assert existing.read_bytes() == b"another upload"
    assert free.read_bytes() == b"new arrival"
    assert not partial.exists()


def test_weakest_opening_asks_for_the_explorer_bar_without_the_significance_gate(monkeypatch):
    captured: dict[str, object] = {}

    def fake_suggest(primary_id, primary_series, candidates, align, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(web, "suggest", fake_suggest)

    assert web._correlation_weakest_opening("lab-primary", {"all": []}, [("same", {}, "all")]) is None
    assert captured["require_significance"] is False


def test_deleting_the_last_copy_removes_its_rendered_pages(tmp_path):
    settings = settings_for(tmp_path)
    sha256 = "ab" * 32
    source = settings.source_dir / "uploads" / "2026-01" / "scan.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"document bytes")
    cache = settings.database_path.parent / "source-page-cache" / sha256[:24]
    cache.mkdir(parents=True)
    (cache / "page-1.png").write_bytes(b"rendered page")
    unrelated = settings.database_path.parent / "source-page-cache" / ("cd" * 12)
    unrelated.mkdir(parents=True)
    (unrelated / "page-1.png").write_bytes(b"other document")

    removed = web._remove_unused_source(settings, {"source_path": str(source), "sha256": sha256})

    assert removed is True
    assert not source.exists()
    assert not cache.exists()
    assert unrelated.exists()
