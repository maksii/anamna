"""Operational guards: liveness endpoint and the raw-sample
delete window that used to hold the write lock for a full-table walk."""

from pathlib import Path

from fastapi.testclient import TestClient

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.web.app import create_app


def _settings(tmp_path: Path) -> Settings:
    sources = tmp_path / "sources"
    sources.mkdir()
    return Settings(
        database_path=tmp_path / "health.sqlite3",
        source_dir=sources,
        secret_key="test-secret",
        session_days=1,
    )


def test_healthz_is_public_and_touches_the_database(tmp_path: Path):
    client = TestClient(create_app(_settings(tmp_path)))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


def test_raw_sample_window_delete_uses_the_timestamp_index(tmp_path: Path):
    """The window must be a range on the bare column.  `substr(timestamp, ...)`
    hid it from ow_samples_window and turned every refresh into a scan of all
    the user's samples while the write lock was held."""
    settings = _settings(tmp_path)
    migrate(settings)
    source = Path("src/anamna/openwearables_webhooks.py").read_text(encoding="utf-8")
    assert "substr(timestamp" not in source
    with connect(settings) as connection:
        plan = " ".join(
            str(row[3])
            for row in connection.execute(
                """EXPLAIN QUERY PLAN DELETE FROM openwearables_raw_samples
                   WHERE owner_user_id=? AND server_url=? AND remote_user_id=?
                     AND timestamp >= ? AND timestamp < ?""",
                ("u", "s", "r", "2026-09-01", "2026-09-08"),
            )
        )
    assert "ow_samples_window" in plan and "timestamp>" in plan
