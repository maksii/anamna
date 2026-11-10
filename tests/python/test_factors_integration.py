"""Medicines and other entries wired into the rest of the record: the clinical
facts a band waits for, planning a pregnancy, the chart periods, record search,
the dashboard tile, the export, the administrator's switch and the account
deletion.  Each test drives the route or the function a user reaches the
behaviour through, on a throwaway database.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from anamna import drugref, factors, reference
from anamna.db import connect, migrate
from anamna.export import write_record_archive
from anamna.i18n import MESSAGES
from anamna.security import create_user
from anamna.web import app as web
from anamna.web import factors_view
from anamna.web.app import create_app

from test_audit_sample_facts import add_observation, profile_form
from test_web_panels import PASSWORD, build, settings_for
from test_web_profile import csrf_for, login
from test_web_security import seed_patient

TODAY = datetime.now(UTC).date()
MICRO = "µ"  # the database spells micro with U+00B5, as the sample rows do


def add_factor(settings, user_id: str, *, started: str = "", ended: str = "", **fields) -> str:
    form = {
        "kind": "medicine", "status": "current", "name": "Warfarin", "atc_code": "B01AA03",
        "started_on": started, "ended_on": ended, **fields,
    }
    values, error = factors.clean(form, today=TODAY)
    assert error is None, error
    with connect(settings) as connection:
        factor_id = factors.create(connection, user_id, f"patient-{user_id}", values)
        connection.commit()
    web.invalidate_catalog()
    return factor_id


def verdict_for(settings, user_id: str, concept_id: str, observation_id: str, sex: str = "male") -> dict:
    with connect(settings) as connection:
        rows = web._deduped_observation_rows(connection, user_id, concept_id)
        row = next(item for item in rows if item["id"] == observation_id)
        return web._reading_verdict(connection, concept_id, row, 40, sex)[1]


def sample_facts_for(settings, user_id: str, observed: str) -> dict:
    with connect(settings) as connection:
        return web._sample_facts(connection, {"owner_user_id": user_id, "observed_at": observed})



# --- clinical facts from medicines and illnesses ------------------------------


def test_an_inr_inside_a_warfarin_period_is_judged_by_the_vka_band(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    add_factor(settings, user_id, started="2026-03-01")
    add_observation(settings, user_id, "inr", 2.5, "2026-04-10", "inr-on", raw_name="INR", unit="ratio")
    verdict = verdict_for(settings, user_id, "inr", "inr-on")
    assert verdict["authority"] == "curated"
    assert verdict["band_label"] == "Vitamin K antagonist therapeutic range"
    assert sample_facts_for(settings, user_id, "2026-04-10") == {"vka_therapy": True}


def test_an_inr_without_the_medicine_or_before_it_started_is_not_judged_by_the_vka_band(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    add_observation(settings, user_id, "inr", 2.5, "2026-04-10", "inr-none", raw_name="INR", unit="ratio")
    before = verdict_for(settings, user_id, "inr", "inr-none")
    assert before["authority"] != "curated"
    assert before["band_label"] != "Vitamin K antagonist therapeutic range"
    add_factor(settings, user_id, started="2026-05-01")
    add_observation(settings, user_id, "inr", 2.4, "2026-04-10", "inr-early", raw_name="INR", unit="ratio")
    early = verdict_for(settings, user_id, "inr", "inr-early")
    assert early["band_label"] != "Vitamin K antagonist therapeutic range"
    assert sample_facts_for(settings, user_id, "2026-04-10") == {}


def test_a_uric_acid_inside_an_allopurinol_period_is_judged_by_a_gout_band(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    add_factor(settings, user_id, name="Allopurinol", atc_code="M04AA01", substance="allopurinol", started="2026-03-01")
    add_observation(settings, user_id, "uric-acid", 300.0, "2026-04-10", "ua-on", raw_name="Urate", unit=f"{MICRO}mol/L")
    inside = verdict_for(settings, user_id, "uric-acid", "ua-on")
    assert inside["authority"] == "curated"
    assert inside["band_label"].startswith("180-360")
    add_observation(settings, user_id, "uric-acid", 300.0, "2025-12-01", "ua-off", raw_name="Urate", unit=f"{MICRO}mol/L")
    outside = verdict_for(settings, user_id, "uric-acid", "ua-off")
    assert outside["authority"] != "curated"


def test_a_ferritin_inside_an_illness_carries_the_inflammation_fact_into_the_verdict(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    add_factor(settings, user_id, kind="illness", name="Pneumonia", atc_code="", started="2026-03-01", ended="2026-03-20")
    facts = sample_facts_for(settings, user_id, "2026-03-10")
    assert facts == {"illness": True, "infection_or_inflammation": True}
    assert sample_facts_for(settings, user_id, "2026-04-10") == {}
    with connect(settings) as connection:
        verdict = reference.evaluate(
            connection, "ferritin", value_numeric=15.0, unit="ng/mL", age_years=40, sex="female",
            clinical_context=facts,
        )
    assert verdict["band_label"] == "Iron deficiency in the presence of infection or inflammation"


# --- planning a pregnancy ------------------------------------------------------


def test_planning_a_pregnancy_saved_on_the_profile_judges_red_cell_folate_by_the_who_band(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_observation(
        settings, user_id, "red-cell-folate-concentration", 250.0, "2026-04-10", "folate-1",
        raw_name="Folate RBC", unit="ng/mL",
    )
    neural = "Below the WHO optimal concentration for prevention of neural tube defects"
    assert verdict_for(settings, user_id, "red-cell-folate-concentration", "folate-1", "female")["band_label"] != neural

    data = profile_form(csrf_for(settings, client), "female")
    response = client.post("/profile", data={**data, "planning_pregnancy": "1"}, follow_redirects=False)
    assert response.status_code == 303
    with connect(settings) as connection:
        assert reference.clinical_context(connection, user_id)["planning_pregnancy"] is True
    assert verdict_for(settings, user_id, "red-cell-folate-concentration", "folate-1", "female")["band_label"] == neural


def test_a_male_profile_cannot_plan_a_pregnancy(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    data = profile_form(csrf_for(settings, client), "male")
    response = client.post("/profile", data={**data, "planning_pregnancy": "1"}, follow_redirects=False)
    assert response.status_code == 303
    with connect(settings) as connection:
        stored = connection.execute(
            "SELECT planning_pregnancy FROM patients WHERE owner_user_id=?", (user_id,)
        ).fetchone()[0]
        assert not reference.clinical_context(connection, user_id).get("planning_pregnancy")
    assert stored == 0


# --- the chart periods ---------------------------------------------------------


def test_a_metric_page_lists_the_entry_that_affects_it_and_folds_the_others(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_observation(settings, user_id, "ferritin", 50.0, "2026-03-01", "fer-1", raw_name="Ferritin", unit="ng/mL")
    add_observation(settings, user_id, "ferritin", 55.0, "2026-04-10", "fer-2", raw_name="Ferritin", unit="ng/mL")
    iron = add_factor(settings, user_id, kind="supplement", name="Iron tablets", atc_code="", started="2026-02-01")
    add_factor(settings, user_id, name="Warfarin", started="2026-02-01")
    with connect(settings) as connection:
        assert factors.add_effect(connection, user_id, iron, concept_id="ferritin", label="Ferritin", direction="raises")
        connection.commit()
    web.invalidate_catalog()

    page = client.get("/metrics/ferritin").text
    assert MESSAGES["med.chart.heading"]["en"] in page
    assert 'id="factor-periods-metric"' in page
    assert 'data-factor-others="metric"' in page
    assert "Iron tablets" in page and "Warfarin" in page


def test_a_metric_page_with_no_entries_shows_none_of_it(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_observation(settings, user_id, "ferritin", 50.0, "2026-03-01", "fer-a", raw_name="Ferritin", unit="ng/mL")
    add_observation(settings, user_id, "ferritin", 55.0, "2026-04-10", "fer-b", raw_name="Ferritin", unit="ng/mL")
    page = client.get("/metrics/ferritin").text
    assert MESSAGES["med.chart.heading"]["en"] not in page
    assert "factor-periods-metric" not in page


def test_the_blood_pressure_block_carries_the_periods_of_its_two_readings(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    antihypertensive = add_factor(settings, user_id, name="Ramipril", atc_code="C09AA05", started="2026-02-01")
    with connect(settings) as connection:
        factors.add_effect(
            connection, user_id, antihypertensive, concept_id="systolic-blood-pressure",
            label="Systolic blood pressure", direction="lowers",
        )
        connection.commit()
        block = web._bp_block(connection, user_id, [])
    related = block["factor_periods"]["related"]
    assert [item["name"] for item in related] == ["Ramipril"]
    assert related[0]["direction"] == "lowers"


def test_a_device_metric_is_paired_with_the_lab_concept_it_measures(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    assert web._device_twin_concepts("resting_heart_rate") == ["pulse-rate"]
    assert web._device_twin_concepts("no_such_device_metric") == []
    entry = add_factor(settings, user_id, name="Metoprolol", atc_code="C07AB02", started="2026-02-01")
    with connect(settings) as connection:
        factors.add_effect(connection, user_id, entry, concept_id="pulse-rate", label="Pulse", direction="lowers")
        connection.commit()
        paired = factors_view.chart_periods(
            connection, user_id, web._device_twin_concepts("resting_heart_rate"), locale="en", today=TODAY,
        )
        unpaired = factors_view.chart_periods(
            connection, user_id, web._device_twin_concepts("no_such_device_metric"), locale="en", today=TODAY,
        )
    assert [item["name"] for item in paired["related"]] == ["Metoprolol"]
    assert unpaired is not None and unpaired["related"] == [] and [item["name"] for item in unpaired["others"]] == ["Metoprolol"]


# --- record search --------------------------------------------------------------


def test_a_medicine_is_found_by_name_and_by_substance_under_its_group(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_factor(settings, user_id, name="Marevan", substance="warfarin", started="2026-02-01")
    with connect(settings) as connection:
        groups = web._record_search(connection, user_id, "warfarin", 0)
        by_name = web._record_search(connection, user_id, "marevan", 0)
    for found in (groups, by_name):
        medicines = next(group for group in found if group["key"] == "medicines")
        assert medicines["rows"][0]["title"] == "Marevan"
        assert medicines["rows"][0]["url"].startswith("/medicines/")
        assert "Medicine" in medicines["rows"][0]["subtitle"] and "Current" in medicines["rows"][0]["subtitle"]
        assert "warfarin" in medicines["rows"][0]["subtitle"]
    client.cookies.set("anamna_lang", "uk")
    page = client.get("/metrics?q=warfarin").text
    assert MESSAGES["metrics.group_medicines"]["uk"] in page and "Marevan" in page
    client.cookies.set("anamna_lang", "en")
    assert MESSAGES["metrics.group_medicines"]["en"] in client.get("/metrics?q=marevan").text


# --- the dashboard tile ----------------------------------------------------------


def test_the_dashboard_tile_counts_current_entries_and_names_them(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_factor(settings, user_id, name="Warfarin", started="2026-02-01")
    add_factor(settings, user_id, name="Vitamin D", kind="supplement", atc_code="", started="2026-02-01")
    page = client.get("/").text
    assert MESSAGES["med.tile.label"]["en"] in page
    assert "Vitamin D, Warfarin" in page


def test_an_empty_record_invites_the_owner_to_add_what_they_take(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    page = client.get("/").text
    assert MESSAGES["med.tile.note_empty"]["en"] in page


def test_a_guest_sees_the_medicine_tile_only_when_there_is_something_in_it(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        assert web._medicine_tile(connection, user_id, owner=False) is None
        assert web._medicine_tile(connection, user_id, owner=True)["note"] == MESSAGES["med.tile.note_empty"]["en"]
    add_factor(settings, user_id, name="Warfarin", started="2026-02-01")
    with connect(settings) as connection:
        tile = web._medicine_tile(connection, user_id, owner=False)
    assert tile["value"] == "1" and tile["href"] == "/medicines" and tile["note"] == "Warfarin"


# --- export --------------------------------------------------------------------------


def test_the_record_export_carries_the_medicines_and_their_effects(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    entry = add_factor(settings, user_id, name="Marevan", started="2026-02-01")
    with connect(settings) as connection:
        factors.add_effect(connection, user_id, entry, concept_id=None, label="INR", direction="raises")
        connection.commit()
    buffer = io.BytesIO()
    counts = write_record_archive(settings, user_id, buffer)
    assert counts["medicines"] == 1 and counts["medicine_effects"] == 1
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive:
        names = archive.namelist()
        assert "medicines.csv" in names and "medicine_effects.csv" in names
        assert b"Marevan" in archive.read("medicines.csv")
        assert b"INR" in archive.read("medicine_effects.csv")


# --- the administrator's switch -----------------------------------------------------


def test_the_administrator_switches_the_medicine_reference_on_and_off(tmp_path: Path):
    settings, admin_id, client = build(tmp_path)
    with connect(settings) as connection:
        assert drugref.enabled(connection) is True
    assert MESSAGES["admin.drug_lookup_label"]["en"] in client.get("/admin/ai").text
    response = client.post(
        "/admin/ai", data={"csrf_token": csrf_for(settings, client)}, follow_redirects=False,
    )
    assert response.status_code == 303
    with connect(settings) as connection:
        assert drugref.enabled(connection) is False
    response = client.post(
        "/admin/ai", data={"csrf_token": csrf_for(settings, client), "drug_lookup": "1"}, follow_redirects=False,
    )
    assert response.status_code == 303
    with connect(settings) as connection:
        assert drugref.enabled(connection) is True


def test_a_member_cannot_switch_the_medicine_reference(tmp_path: Path):
    settings, admin_id, _ = build(tmp_path)
    create_user(settings, "member@example.test", "Member", PASSWORD)
    with TestClient(create_app(settings)) as client:
        login(client, "member@example.test")
        response = client.post(
            "/admin/ai", data={"csrf_token": csrf_for(settings, client)}, follow_redirects=False,
        )
    assert response.status_code == 403
    with connect(settings) as connection:
        assert drugref.enabled(connection) is True


# --- account deletion ------------------------------------------------------------------


def test_deleting_the_account_removes_the_medicine_rows(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    seed_patient(settings, alpha, "Alpha Patient")
    entry = add_factor(settings, alpha, name="Warfarin", started="2026-02-01")
    with connect(settings) as connection:
        factors.add_effect(connection, alpha, entry, concept_id=None, label="INR", direction="raises")
        connection.commit()
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, "alpha@example.test")
        response = client.post(
            "/profile/delete-account",
            data={"password": PASSWORD, "email": "alpha@example.test", "csrf_token": csrf_for(settings, client)},
            follow_redirects=False,
        )
    assert response.headers["location"] == "/login?notice=account_deleted"
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM factors WHERE owner_user_id=?", (alpha,)).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM factor_effects WHERE owner_user_id=?", (alpha,)).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
