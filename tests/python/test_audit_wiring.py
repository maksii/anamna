import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

import anamna.labsync as labsync
from anamna import immunizations
from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.i18n import t
from anamna.web import app as app_module
from anamna.web.app import create_app


def settings_for(tmp_path: Path) -> Settings:
    sources = tmp_path / "sources"
    sources.mkdir()
    return Settings(
        database_path=tmp_path / "health.sqlite3",
        source_dir=sources,
        secret_key="test-secret",
        session_days=1,
    )


def test_healthz_answers_get_and_head(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    with TestClient(create_app(settings)) as client:
        get = client.get("/healthz")
        head = client.head("/healthz")
    assert get.status_code == 200
    assert get.text == "ok"
    assert head.status_code == 200
    assert head.content == b""


def test_comparator_of_reads_the_printed_comparator_or_none():
    assert app_module._comparator_of({"comparator": "<"}) == "<"
    assert app_module._comparator_of({}) is None
    assert app_module._comparator_of({"comparator": None}) is None
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        with_column = connection.execute("SELECT '>' AS comparator").fetchone()
        without_column = connection.execute("SELECT 1 AS value").fetchone()
        assert app_module._comparator_of(with_column) == ">"
        assert app_module._comparator_of(without_column) is None
    finally:
        connection.close()


def test_a_censored_reading_reaches_the_engine_as_censored(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    calls: list[dict[str, object]] = []

    def recording_evaluate(connection, **kwargs):
        calls.append(kwargs)
        return {"interpretation": "unjudged", "authority": "none"}

    monkeypatch.setattr(app_module, "evaluate", recording_evaluate)
    monkeypatch.setattr(app_module, "_clinical_context", lambda connection, owner: {})
    row = {
        "preferred_unit": "ng/mL",
        "unit_raw": "ng/mL",
        "value_numeric": 1.0,
        "value_text": None,
        "vendor_reference_low": None,
        "vendor_reference_high": None,
        "vendor_interpretation": None,
        "vendor_reference_text": None,
        "owner_user_id": "owner-1",
        "comparator": "<",
    }
    with connect(settings) as connection:
        app_module._reading_verdict(connection, "c1", row, 34, "male")
        app_module._reading_verdict(connection, "c1", {**row, "comparator": None}, 34, "male")
        del row["comparator"]
        app_module._reading_verdict(connection, "c1", row, 34, "male")
    assert calls[0]["comparator"] == "<"
    assert calls[0]["concept_id"] == "c1"
    assert calls[1]["comparator"] is None
    assert calls[2]["comparator"] is None


def _covid_gap(last_date: str | None) -> immunizations.Gap:
    return immunizations.Gap(
        key="covid_booster",
        kind="discuss",
        diseases=("covid19",),
        last_date=last_date,
        agreement="differs",
        urgency="unknown",
    )


def test_a_discuss_gap_with_a_past_dose_names_that_date_and_no_due_date():
    dated = app_module.format_date("2023-10-01")
    row = app_module._gap_row(_covid_gap("2023-10-01"), [])
    assert row["sentence"] == t("vax.gap_discuss_dated", date=dated)
    assert dated in row["sentence"]
    assert row["sentence"] != t("vax.gap_never")


def test_a_discuss_gap_without_a_dose_says_it_is_for_the_doctor():
    row = app_module._gap_row(_covid_gap(None), [])
    assert row["sentence"] == t("vax.gap_discuss")


def test_create_app_refreshes_the_catalog_when_a_lab_sync_changes_a_record(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_app(settings)
    assert app_module.invalidate_catalog in labsync._record_changed
