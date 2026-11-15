"""Review findings on the metric-connections change, each held by a test.

A series keeps its history when a laboratory did not print the specimen, a
home-monitoring PDF does not repeat a device day, a measured height locks the
profile field only when the BMI calculation accepts it, a mislabelled newest
result does not empty a series, the correlation index lists only what it can
plot, a calculated device row exports as a calculation, and the new
migrations run inside one transaction each.
"""

from __future__ import annotations

from pathlib import Path

from markupsafe import escape

from anamna import db
from anamna.db import connect
from anamna.i18n import activate_locale, reset_locale, t
from anamna.web import app as web

from test_linked_metrics import _build, _device_day, _document, _observation


def _set(settings, obs_id: str, **columns) -> None:
    with connect(settings) as connection:
        connection.execute(
            f"UPDATE observations SET {'=?, '.join(columns)}=? WHERE id=?", (*columns.values(), obs_id)
        )
    web.invalidate_catalog()


def _unit(settings, concept_id: str) -> str:
    with connect(settings) as connection:
        return connection.execute("SELECT preferred_unit FROM concepts WHERE id=?", (concept_id,)).fetchone()[0]


def _card(settings, user_id: str, concept_id: str) -> dict:
    with connect(settings) as connection:
        return web._by_id(web._metric_catalog(connection, user_id, include_suppressed=True))[concept_id]


# --- 1: an unstated specimen fits any series ---------------------------------

def _row(row_id: str, specimen=None, note=None) -> dict:
    return {"id": row_id, "patient_id": "p", "specimen": specimen, "sample_condition": None, "note": note}


def test_an_unstated_specimen_joins_the_series_and_a_note_never_splits_it():
    rows = [_row("a", "цільна кров"), _row("b", "Цільна  кров", note="+valsakor"), _row("c"), _row("d", note="Duration: 30s")]
    assert [row["id"] for row in web._latest_context_rows(rows)] == ["a", "b", "c", "d"]


def test_two_stated_specimens_stay_two_series_even_under_an_unstated_newest_row():
    rows = [_row("new"), _row("left-1", "ліва"), _row("right-1", "права"), _row("left-2", "ліва"), _row("old")]
    assert [row["id"] for row in web._latest_context_rows(rows)] == ["new", "left-1", "left-2", "old"]
    assert [row["id"] for row in web._latest_context_rows(rows[2:])] == ["right-1", "old"]


def test_hemoglobin_keeps_its_history_when_only_the_newest_reports_name_the_specimen(tmp_path: Path):
    settings, user_id, client = _build(tmp_path)
    unit = _unit(settings, "hemoglobin")
    days = ["2026-11-05", "2026-08-04", "2025-11-05", "2025-09-16", "2025-08-28"]
    for index, day in enumerate(days):
        _document(settings, user_id, f"cbc-{index}", "Synevo", "laboratory", day)
        _observation(settings, user_id, f"hgb-{index}", f"cbc-{index}", "hemoglobin", 150.0 + index, unit, day)
    for obs_id in ("hgb-0", "hgb-1"):
        _set(settings, obs_id, specimen="цільна кров")
    assert len(_card(settings, user_id, "hemoglobin")["series"]) == 5
    page = client.get("/metrics/hemoglobin").text
    assert page.count('"date"') >= 5 or page.count("&#34;date&#34;") >= 5
    # Nothing was left off the chart, so nothing is said about another context.
    assert "The chart follows" not in page


def test_the_context_note_is_shown_only_when_a_result_was_left_out(tmp_path: Path):
    settings, user_id, client = _build(tmp_path)
    unit = _unit(settings, "hemoglobin")
    for index, (day, specimen) in enumerate((("2026-03-01", "ліва"), ("2026-02-01", "права"), ("2026-01-01", "ліва"))):
        _document(settings, user_id, f"doc-{index}", "Synevo", "laboratory", day)
        _observation(settings, user_id, f"obs-{index}", f"doc-{index}", "hemoglobin", 150.0 + index, unit, day)
        _set(settings, f"obs-{index}", specimen=specimen)
    assert len(_card(settings, user_id, "hemoglobin")["series"]) == 2
    locale = activate_locale("en")
    try:
        page = client.get("/metrics/hemoglobin").text
        assert "The chart follows" in page and str(escape(t("metric.context_history_note"))) in page
    finally:
        reset_locale(locale)


# --- 2: a home-monitoring PDF does not repeat the device day -------------------

def test_a_cuff_report_and_the_cuff_day_are_counted_once(tmp_path: Path):
    settings, user_id, _ = _build(tmp_path)
    _document(settings, user_id, "garmin-pdf", "Garmin Connect", "blood_pressure", "2025-02-13")
    _observation(settings, user_id, "bp-am", "garmin-pdf", "systolic-blood-pressure", 122.0, "mmHg", "2025-02-13T07:10:00")
    _observation(settings, user_id, "bp-pm", "garmin-pdf", "systolic-blood-pressure", 116.0, "mmHg", "2025-02-13T21:40:00")
    _observation(settings, user_id, "bp-alone", "garmin-pdf", "systolic-blood-pressure", 121.0, "mmHg", "2025-02-10T07:10:00")
    _document(settings, user_id, "visit", "Veselka", "consultation", "2025-02-13")
    _observation(settings, user_id, "bp-clinic", "visit", "systolic-blood-pressure", 130.0, "mmHg", "2025-02-13")
    _device_day(settings, user_id, "systolic_blood_pressure", "2025-02-13", 119.0, "mmHg", name="Garmin Connect blood pressure")
    with connect(settings) as connection:
        rows = web._linked_observation_rows(connection, user_id, "systolic-blood-pressure")
    # The day the cuff streamed: its mean once, and the clinic's own reading.
    assert sorted(row["value_numeric"] for row in rows if str(row["observed_at"]).startswith("2025-02-13")) == [119.0, 130.0]
    # A day only the report has is kept.
    assert {row["id"] for row in rows if not row.get("is_device")} == {"bp-alone", "bp-clinic"}


# --- 3: a measured height locks the field only when BMI accepts it -------------

def _height(settings, user_id: str, obs_id: str, value: float, day: str) -> None:
    _document(settings, user_id, f"doc-{obs_id}", "Veselka", "consultation", day)
    _observation(settings, user_id, obs_id, f"doc-{obs_id}", "body-height", value, "cm", day)
    _set(settings, obs_id, verification_status="verified")


def _measured_height(settings, user_id: str):
    with connect(settings) as connection:
        return web._measured_body(connection, user_id).get("height_cm")


def test_a_height_measured_in_childhood_leaves_the_typed_height_and_its_field(tmp_path: Path):
    settings, user_id, client = _build(tmp_path)  # born 1990-03-14
    with connect(settings) as connection:
        connection.execute("UPDATE patients SET height_cm=183, weight_kg=80 WHERE owner_user_id=?", (user_id,))
    _height(settings, user_id, "h-teen", 168.0, "2005-06-01")
    assert _measured_height(settings, user_id) is None
    assert 'name="height_cm"' in client.get("/profile").text
    with connect(settings) as connection:
        web._profile_store(connection, user_id, "Linked", None, "1990-03-14", "male", None,
                           {"height_cm": 183.0, "weight_kg": 80.0}, {}, "")
        patient = connection.execute("SELECT height_cm FROM patients WHERE owner_user_id=?", (user_id,)).fetchone()
        assert patient["height_cm"] == 183.0
        bmi = web._profile_bmi_reading(connection, user_id)
    assert bmi is not None and round(bmi["value_numeric"], 1) == 23.9


def test_an_adult_verified_height_takes_the_field(tmp_path: Path):
    settings, user_id, client = _build(tmp_path)
    _height(settings, user_id, "h-adult", 184.0, "2024-06-01")
    measured = _measured_height(settings, user_id)
    assert measured is not None and measured["value"] == 184.0
    assert 'name="height_cm"' not in client.get("/profile").text


def test_two_verified_heights_that_disagree_on_one_day_do_not_lock_the_field(tmp_path: Path):
    settings, user_id, client = _build(tmp_path)
    _height(settings, user_id, "h-one", 184.0, "2024-06-01")
    _height(settings, user_id, "h-two", 181.0, "2024-06-01")
    assert _measured_height(settings, user_id) is None
    assert 'name="height_cm"' in client.get("/profile").text


# --- 6: the card's series follows the newest number, as the chart does ----------

def test_a_newest_number_in_another_unit_carries_the_series_as_on_the_chart(monkeypatch):
    """Five respiratory rates under a newest one in a unit that cannot be
    converted: the card draws what the detail chart draws, the newest reading
    in its own unit, never an empty series and never a trend across two units."""
    monkeypatch.setattr(web, "_reading_verdict", lambda *args: ("min", {"interpretation": "unjudged", "label": "Unjudged"}))
    good = {
        "concept_id": "resting-respiratory-rate", "canonical_name": "Resting respiratory rate",
        "category": "vitals", "patient_id": "p", "document_id": "d", "created_at": "2026-06-02",
        "confidence": .9, "value_text": None, "unit_raw": "breaths/min", "preferred_unit": "breaths/min",
        "comparator": None, "raw_name": "Respiratory rate", "specimen": None, "sample_condition": None,
        "note": None, "vendor": "Synthetic clinic", "verification_status": "extracted", "evidence_count": 1,
    }
    rows = [{**good, "id": "bad", "observed_at": "2026-06-01", "value_numeric": 16.0,
             "unit_raw": "min", "preferred_unit": "min", "unit_mismatch": True}]
    rows += [{**good, "id": f"rr-{index}", "observed_at": f"2026-0{5 - index}-01", "value_numeric": 14.0 + index}
             for index in range(5)]
    card = web._lab_card(None, "resting-respiratory-rate", rows, {}, None, None, {})
    assert [point["value"] for point in card["series"]] == [16.0]
    assert card["trend"] is None
    # The chart's side of the same rule: test_web_panels.py::test_an_unconvertible_reading_keeps_its_printed_unit.


def test_a_text_newest_result_keeps_the_earlier_numbers(tmp_path: Path):
    settings, user_id, _ = _build(tmp_path)
    unit = _unit(settings, "hemoglobin")
    for index, day in enumerate(("2026-03-01", "2026-02-01", "2026-01-01")):
        _document(settings, user_id, f"doc-{index}", "Synevo", "laboratory", day)
        _observation(settings, user_id, f"obs-{index}", f"doc-{index}", "hemoglobin", 150.0 + index, unit, day)
    _set(settings, "obs-0", value_numeric=None, value_text="negative", value_type="text", unit_raw=None)
    card = _card(settings, user_id, "hemoglobin")
    assert [point["value"] for point in card["series"]] == [152.0, 151.0]
    assert card["trend"] is None  # the newest result is not one of the numbers


# --- 7: the correlation index lists what it can plot ---------------------------

def test_the_correlation_index_skips_text_only_results_and_keeps_unitless_numbers(tmp_path: Path):
    settings, user_id, client = _build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE concepts SET preferred_unit=NULL WHERE id='hemoglobin'")
    for index, day in enumerate(("2026-03-01", "2026-02-01")):
        _document(settings, user_id, f"doc-{index}", "Synevo", "laboratory", day)
        _observation(settings, user_id, f"hgb-{index}", f"doc-{index}", "hemoglobin", 150.0 + index, "g/L", day)
        _observation(settings, user_id, f"txt-{index}", f"doc-{index}", "hematocrit", 1.0, None, day)
        _set(settings, f"txt-{index}", value_numeric=None, value_text="negative", value_type="text")
    with connect(settings) as connection:
        labs = web._correlation_lab_series(connection, user_id)
    assert labs["hemoglobin"]["series"] == [("2026-02-01", 151.0), ("2026-03-01", 150.0)]
    assert "hematocrit" not in labs
    assert all(entry["series"] for entry in labs.values())


# --- 8: a calculated device row exports as a calculation -----------------------

def test_a_calculated_bmi_row_is_not_exported_as_a_device_measurement(tmp_path: Path, monkeypatch):
    settings, user_id, _ = _build(tmp_path)
    base = {"day": "2026-01-01", "value": 24.2, "unit": "kg/m²", "source_vendor": "Garmin", "source_name": "Garmin Index Scale"}
    monkeypatch.setattr(web, "device_metric_values", lambda *args, **kwargs: [
        {**base, "id": "derived-bmi-2026-01-01"}, {**base, "id": "dmd-1", "day": "2025-12-31"},
    ])
    locale = activate_locale("en")
    try:
        with connect(settings) as connection:
            derived, measured = web._export_device_rows(connection, user_id, "body_mass_index")
        assert derived["status"] == t("calc.status")
        assert measured["status"] == t(web._DEVICE_MEASUREMENT_KEY)
        assert derived["status"] != measured["status"]
    finally:
        reset_locale(locale)


# --- 4: a migration is one transaction ---------------------------------------

def test_no_migration_from_071_on_runs_unwrapped():
    """A trigger's BEGIN alone at the start of a line makes `migrate()` run the
    file outside a transaction: killed between the script and its version row,
    it fails with "table already exists" on every later start."""
    recent = [path for path in sorted(db.MIGRATIONS_DIR.glob("*.sql")) if int(path.name.split("_", 1)[0]) >= 71]
    assert len(recent) >= 6
    for path in recent:
        assert not db._SELF_MANAGED.search(path.read_text(encoding="utf-8")), path.name


def test_the_revision_triggers_exist_and_fire(tmp_path: Path):
    settings, user_id, _ = _build(tmp_path)
    with connect(settings) as connection:
        triggers = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert {"observation_revision_insert", "device_metric_days_revision_update",
                "patients_clinical_revision_update", "factors_clinical_revision_insert"} <= triggers
        before = connection.execute(
            "SELECT revision FROM device_metric_revisions WHERE owner_user_id=?", (user_id,)).fetchone()
    _device_day(settings, user_id, "body_weight", "2026-01-01", 80.0, "kg")
    with connect(settings) as connection:
        after = connection.execute(
            "SELECT revision FROM device_metric_revisions WHERE owner_user_id=?", (user_id,)).fetchone()
        assert after[0] == (before[0] if before else 0) + 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
