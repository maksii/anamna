"""Per-sample facts: whether a blood sample was taken fasting, and whether a result
was taken during a pregnancy the profile records.

Each test asserts one rule the verdict depends on: a person's answer about the
sample is stored and read back as the fact the bands name; a result inside the
40 weeks before a recorded due date is judged as a pregnancy result; a result
that refuses judgement says so on the page; and only the owner of a record may
change its answer.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import markupsafe
import pytest
from fastapi.testclient import TestClient

from anamna import integrations
from anamna.db import connect, migrate
from anamna.health import rule_context
from anamna.ingest.concepts import concept_for_alias
from anamna.ingest.pipeline import ensure_concept
from anamna.locales.messages import MESSAGES
from anamna.security import create_access_token, create_user
from anamna.web import app as web
from anamna.web.app import create_app

from test_web_panels import PASSWORD, build, settings_for
from test_web_profile import csrf_for, login

TODAY = datetime.now(UTC).date()


def message(key: str) -> str:
    return str(markupsafe.escape(MESSAGES[key]["en"]))


def count(settings, sql: str, *args) -> int:
    with connect(settings) as connection:
        return connection.execute(sql, args).fetchone()[0]


def concept(settings, name: str) -> str:
    with connect(settings) as connection:
        concept_id, _ = ensure_concept(connection, name, None)
    return concept_id


def add_observation(
    settings, user_id: str, concept_id: str, value: float, observed: str, observation_id: str,
    *, raw_name: str = "Glucose", unit: str = "mmol/L", sample_condition: str | None = None,
) -> None:
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO observations(
                   id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
                   value_type, value_numeric, unit_raw, observed_at, verification_status,
                   extraction_method, confidence, evidence_text, parser_version, created_at,
                   sample_condition)
               VALUES (?, ?, ?, 'doc-1', 1, ?, ?, 'numeric', ?, ?, ?, 'extracted', 'test', 0.9,
                       'fixture', 'test', '2026-01-01T00:00:00+00:00', ?)""",
            (observation_id, user_id, f"patient-{user_id}", concept_id, raw_name, value, unit,
             observed, sample_condition),
        )
    web.invalidate_catalog()


def verdict_of(settings, user_id: str, concept_id: str, observation_id: str) -> dict:
    with connect(settings) as connection:
        rows = web._deduped_observation_rows(connection, user_id, concept_id)
        row = next(item for item in rows if item["id"] == observation_id)
        return web._reading_verdict(connection, concept_id, row, 40, "male")[1]


def mark(client: TestClient, settings, observation_id: str, condition: str, **overrides):
    data = {"condition": condition, "csrf_token": csrf_for(settings, client), **overrides}
    return client.post(f"/observations/{observation_id}/sample-condition", data=data, follow_redirects=False)


def set_due(settings, user_id: str, due: str | None) -> None:
    with connect(settings) as connection:
        connection.execute("UPDATE patients SET pregnancy_due_date=? WHERE owner_user_id=?", (due, user_id))
    web.invalidate_catalog()


def stored_due(settings, user_id: str) -> str | None:
    with connect(settings) as connection:
        return connection.execute(
            "SELECT pregnancy_due_date FROM patients WHERE owner_user_id=?", (user_id,)
        ).fetchone()[0]


def profile_form(csrf: str, sex: str, due: str | None = None) -> dict[str, str]:
    data = {
        "full_name": "Test Patient", "date_of_birth": "1990-03-14", "sex_at_birth": sex,
        "csrf_token": csrf,
    }
    if due is not None:
        data["pregnancy_due_date"] = due
    return data


# --- the facts ---------------------------------------------------------------


def test_a_plain_result_carries_no_sample_facts(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        assert web._sample_facts(connection, {"owner_user_id": user_id, "observed_at": "2026-01-10"}) == {}
        assert web._sample_facts(connection, {
            "owner_user_id": user_id, "observed_at": "2026-01-10", "sample_condition": None,
        }) == {}
        assert web._sample_facts(connection, {
            "owner_user_id": user_id, "observed_at": "2026-01-10", "sample_condition": "fasting",
        }) == {}


def test_a_result_marked_not_fasting_carries_that_fact(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        facts = web._sample_facts(connection, {
            "owner_user_id": user_id, "observed_at": "2026-01-10", "sample_condition": "not_fasting",
        })
    assert facts == {"not_fasting_sample": True}


@pytest.mark.parametrize(
    ("days_before_due", "pregnant"),
    [(100, True), (0, True), (280, True), (281, False), (-1, False)],
)
def test_a_result_is_pregnant_only_within_the_forty_weeks_before_the_due_date(
    tmp_path: Path, days_before_due: int, pregnant: bool
):
    settings, user_id, _ = build(tmp_path)
    due = TODAY + timedelta(days=60)
    set_due(settings, user_id, due.isoformat())
    observed = (due - timedelta(days=days_before_due)).isoformat()
    with connect(settings) as connection:
        facts = web._sample_facts(connection, {"owner_user_id": user_id, "observed_at": observed})
    assert facts == ({"pregnant": True} if pregnant else {})


def test_no_due_date_or_an_unreadable_one_means_no_pregnancy(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    row = {"owner_user_id": user_id, "observed_at": TODAY.isoformat()}
    with connect(settings) as connection:
        assert web._sample_facts(connection, row) == {}
    set_due(settings, user_id, "soon")
    with connect(settings) as connection:
        assert web._sample_facts(connection, row) == {}


def test_a_row_without_the_sample_column_means_not_stated(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        bare = connection.execute("SELECT 'x' AS other").fetchone()
    assert web._fasting_state(bare) is None
    assert web._sample_facts(connection, bare) == {}


# --- the printed name and the person's answer -------------------------------


def test_the_printed_name_says_fasting_until_the_person_answers(tmp_path: Path):
    settings, _, _ = build(tmp_path)
    assert web._fasting_state({"raw_name": "Глюкоза натще", "sample_condition": None}) == "fasting"
    assert web._fasting_state({"raw_name": "Glucose, fasting", "sample_condition": None}) == "fasting"
    assert web._fasting_state({"raw_name": "Глюкоза натще", "sample_condition": "not_fasting"}) == "not_fasting"
    assert web._fasting_state({"raw_name": "Глюкоза натще", "sample_condition": "fasting"}) == "fasting"
    assert web._fasting_state({"raw_name": "Глюкоза", "sample_condition": None}) is None
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT 'Глюкоза натще' AS raw_name, 'not_fasting' AS sample_condition"
        ).fetchone()
    assert web._fasting_state(row) == "not_fasting"


# --- the glucose verdicts ----------------------------------------------------


def test_marking_a_glucose_sample_not_fasting_withdraws_the_fasting_judgement(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    glucose = concept(settings, "Blood glucose")
    add_observation(settings, user_id, glucose, 6.0, "2026-08-04", "glu-6")

    before = verdict_of(settings, user_id, glucose, "glu-6")
    assert before["authority"] == "curated"
    assert before["interpretation"] == "borderline_high"

    response = mark(client, settings, "glu-6", "not_fasting")
    assert response.status_code == 303
    assert response.headers["location"] == f"/metrics/{glucose}?saved=sample_condition"

    after = verdict_of(settings, user_id, glucose, "glu-6")
    assert after["curated_blocked"] == "excluded_not_fasting_sample"
    assert after["authority"] != "curated" or after["interpretation"] != "borderline"

    page = client.get(f"/metrics/{glucose}?saved=sample_condition").text
    assert message("verdict.blocked_not_fasting") in page
    assert message("glucose.saved") in page

    cleared = mark(client, settings, "glu-6", "")
    assert cleared.status_code == 303
    restored = verdict_of(settings, user_id, glucose, "glu-6")
    assert restored == before


def test_a_high_glucose_marked_not_fasting_is_judged_by_the_random_sample_band(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    glucose = concept(settings, "Blood glucose")
    add_observation(settings, user_id, glucose, 12.0, "2026-08-04", "glu-12")
    mark(client, settings, "glu-12", "not_fasting")
    verdict = verdict_of(settings, user_id, glucose, "glu-12")
    assert verdict["interpretation"] == "high"
    assert "random" in str(verdict["band_label"]).casefold()
    # The fasting bands still say why they were set aside; the page explains it.
    assert verdict["curated_blocked"] == "excluded_not_fasting_sample"


# --- the pregnancy verdicts --------------------------------------------------


def test_a_tsh_taken_during_a_recorded_pregnancy_is_not_judged_by_the_adult_bands(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    tsh = concept(settings, "Thyroid stimulating hormone")
    add_observation(settings, user_id, tsh, 2.0, TODAY.isoformat(), "tsh-1", raw_name="TSH", unit="mIU/L")
    assert verdict_of(settings, user_id, tsh, "tsh-1").get("curated_blocked") is None

    set_due(settings, user_id, (TODAY + timedelta(days=60)).isoformat())
    assert verdict_of(settings, user_id, tsh, "tsh-1")["curated_blocked"] == "excluded_pregnant"
    assert message("verdict.blocked_pregnancy") in client.get(f"/metrics/{tsh}").text


def test_a_glucose_taken_during_a_recorded_pregnancy_says_so(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    glucose = concept(settings, "Blood glucose")
    add_observation(settings, user_id, glucose, 5.0, TODAY.isoformat(), "glu-p")
    set_due(settings, user_id, (TODAY + timedelta(days=60)).isoformat())
    assert verdict_of(settings, user_id, glucose, "glu-p")["curated_blocked"] == "excluded_pregnant"
    assert message("verdict.blocked_pregnancy") in client.get(f"/metrics/{glucose}").text


def test_a_result_from_two_years_earlier_is_judged_as_before(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    tsh = concept(settings, "Thyroid stimulating hormone")
    two_years_ago = (TODAY - timedelta(days=730)).isoformat()
    add_observation(settings, user_id, tsh, 2.0, two_years_ago, "tsh-old", raw_name="TSH", unit="mIU/L")
    before = verdict_of(settings, user_id, tsh, "tsh-old")
    set_due(settings, user_id, (TODAY + timedelta(days=60)).isoformat())
    assert verdict_of(settings, user_id, tsh, "tsh-old") == before


def test_the_profile_records_a_due_date_and_clears_it_on_request(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, client)
    due = (TODAY + timedelta(days=60)).isoformat()

    saved = client.post("/profile", data=profile_form(csrf, "female", due), follow_redirects=False)
    assert saved.headers["location"] == "/profile?saved=1"
    assert stored_due(settings, user_id) == due
    page = client.get("/profile").text
    assert 'name="pregnancy_due_date"' in page and f'value="{due}"' in page

    client.post("/profile", data=profile_form(csrf, "female", ""), follow_redirects=False)
    assert stored_due(settings, user_id) is None

    client.post("/profile", data=profile_form(csrf, "female", due), follow_redirects=False)
    two_years = (TODAY + timedelta(days=730)).isoformat()
    client.post("/profile", data=profile_form(csrf, "female", two_years), follow_redirects=False)
    assert stored_due(settings, user_id) == due
    client.post("/profile", data=profile_form(csrf, "female", "not-a-date"), follow_redirects=False)
    assert stored_due(settings, user_id) == due


def test_a_male_profile_has_no_due_date_field(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    set_due(settings, user_id, (TODAY + timedelta(days=60)).isoformat())
    page = client.get("/profile").text
    assert 'name="pregnancy_due_date"' not in page


def test_saving_a_male_profile_clears_a_stored_due_date(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, client)
    due = (TODAY + timedelta(days=60)).isoformat()
    client.post("/profile", data=profile_form(csrf, "female", due), follow_redirects=False)
    assert stored_due(settings, user_id) == due

    saved = client.post("/profile", data=profile_form(csrf, "male", due), follow_redirects=False)
    assert saved.headers["location"] == "/profile?saved=1"
    assert stored_due(settings, user_id) is None


# --- the question on the metric page -----------------------------------------


def test_the_glucose_page_asks_about_fasting_and_other_analytes_do_not(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    glucose = concept(settings, "Blood glucose")
    add_observation(settings, user_id, glucose, 5.1, "2026-08-04", "glu-ask")
    page = client.get(f"/metrics/{glucose}").text
    assert message("glucose.assumed_fasting") in page
    assert message("glucose.question") in page
    assert 'action="/observations/glu-ask/sample-condition"' in page
    assert 'name="condition"' in page

    hemoglobin = client.get(f"/metrics/{concept(settings, 'Hemoglobin')}").text
    assert message("glucose.assumed_fasting") not in hemoglobin
    assert message("glucose.question") not in hemoglobin
    assert "/sample-condition" not in hemoglobin


def test_a_shared_record_shows_the_answer_but_offers_no_form(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    glucose = concept(settings, "Blood glucose")
    add_observation(settings, user_id, glucose, 5.1, "2026-08-04", "glu-view", sample_condition="fasting")
    viewer_id = create_user(settings, "viewer@example.test", "Viewer", PASSWORD)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO record_shares(id, owner_user_id, grantee_email, grantee_user_id, created_at, access)
                   VALUES ('share-view', ?, 'viewer@example.test', ?, '2026-01-01T00:00:00+00:00', 'read')""",
            (user_id, viewer_id),
        )
    with TestClient(create_app(settings)) as viewer:
        login(viewer, "viewer@example.test")
        viewer.post("/profile/view", data={"owner_user_id": user_id, "csrf_token": csrf_for(settings, viewer)})
        page = viewer.get(f"/metrics/{glucose}").text
    assert message("glucose.confirmed_fasting") in page
    assert "/sample-condition" not in page


def test_a_metric_rule_with_an_excludes_gate_shows_no_chip_for_it(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    glucose = concept(settings, "Blood glucose")
    with connect(settings) as connection:
        rules = connection.execute(
            """SELECT rr.*, rs.name reference_set, rs.publisher, rs.source_url, rs.reviewed_at
                   FROM curated_reference_rules rr JOIN reference_sets rs ON rs.id=rr.reference_set_id
                   WHERE rr.concept_id=?""",
            (glucose,),
        ).fetchall()
    gated = [rule for rule in rules if "excludes" in rule_context(rule["context_json"])]
    assert gated
    rendered = web._metric_rule(gated[0], 40, "male", {})
    assert "excludes" not in rendered["context"]


def _rule_view(settings, context: dict, page_context: dict | None = None) -> dict:
    """A glucose band's rule view, with its gate replaced by ``context``."""
    with connect(settings) as connection:
        row = connection.execute(
            """SELECT rr.*, rs.name reference_set, rs.publisher, rs.source_url, rs.reviewed_at
                   FROM curated_reference_rules rr JOIN reference_sets rs ON rs.id=rr.reference_set_id
                   WHERE rr.concept_id=? LIMIT 1""",
            (concept(settings, "Blood glucose"),),
        ).fetchone()
    return web._metric_rule(dict(row, context_json=json.dumps(context)), 40, "male", page_context or {})


def test_a_rule_that_needs_only_a_silent_fact_shows_no_requirement_chip(tmp_path: Path):
    settings, _, _ = build(tmp_path)
    rendered = _rule_view(settings, {"requires": ["not_fasting_sample"]})
    assert "requires" not in rendered["context"]
    assert "not_fasting_sample" not in repr(rendered["context"])
    assert "not_fasting_sample" not in str(rendered.get("applicability") or "")
    assert MESSAGES["cv_risk.goal_requires"]["en"] not in str(rendered.get("applicability") or "")


def test_a_rule_that_needs_a_risk_category_keeps_its_goal_chip_and_hides_the_key(tmp_path: Path):
    settings, _, _ = build(tmp_path)
    rendered = _rule_view(settings, {"requires": ["cv_risk_category"], "cv_risk_category": "high"})
    assert "requires" not in rendered["context"]
    assert "cv_risk_category" not in rendered["context"]
    assert rendered["applicability"].endswith(MESSAGES["cv_risk.goal_for_high"]["en"])


# --- writing an answer -------------------------------------------------------


def test_only_the_owner_may_answer_about_a_sample(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    glucose = concept(settings, "Blood glucose")
    add_observation(settings, user_id, glucose, 5.1, "2026-08-04", "glu-own")

    create_user(settings, "stranger@example.test", "Stranger", PASSWORD)
    with TestClient(create_app(settings)) as stranger:
        login(stranger, "stranger@example.test")
        refused = mark(stranger, settings, "glu-own", "not_fasting")
    assert refused.status_code == 404

    viewer_id = create_user(settings, "reader@example.test", "Reader", PASSWORD)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO record_shares(id, owner_user_id, grantee_email, grantee_user_id, created_at, access)
                   VALUES ('share-full', ?, 'reader@example.test', ?, '2026-01-01T00:00:00+00:00', 'full')""",
            (user_id, viewer_id),
        )
    with TestClient(create_app(settings)) as reader:
        login(reader, "reader@example.test")
        reader.post("/profile/view", data={"owner_user_id": user_id, "csrf_token": csrf_for(settings, reader)})
        refused = mark(reader, settings, "glu-own", "not_fasting")
    assert refused.status_code == 404

    expires = (datetime.now(UTC) + timedelta(days=14)).replace(microsecond=0).isoformat()
    _, secret = create_access_token(settings, user_id, kind="guest", label="visitor", expires_at=expires)
    with TestClient(create_app(settings)) as guest:
        guest.get(f"/t/{secret}", follow_redirects=False)
        # The guest sees the record without the question ...
        assert "/sample-condition" not in guest.get(f"/metrics/{glucose}").text
        # ... and a forged post is refused even with a valid token.
        refused = mark(guest, settings, "glu-own", "not_fasting")
    assert refused.status_code == 403

    assert count(settings, "SELECT COUNT(*) FROM observations WHERE id='glu-own' AND sample_condition IS NULL") == 1


def test_a_post_needs_the_csrf_token_and_a_known_answer(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    glucose = concept(settings, "Blood glucose")
    add_observation(settings, user_id, glucose, 5.1, "2026-08-04", "glu-csrf")
    no_token = client.post(
        "/observations/glu-csrf/sample-condition", data={"condition": "not_fasting"}, follow_redirects=False,
    )
    assert no_token.status_code == 403
    unknown = mark(client, settings, "glu-csrf", "maybe")
    assert unknown.status_code == 400
    assert count(settings, "SELECT COUNT(*) FROM observations WHERE id='glu-csrf' AND sample_condition IS NULL") == 1


# --- the glucose aliases -----------------------------------------------------


@pytest.mark.parametrize(
    "alias",
    [
        "глюкоза натще", "глюкоза (натще)", "глюкоза крові", "глюкоза крові натще",
        "глюкоза плазми", "глюкоза плазми натще", "глюкоза венозної крові",
        "fasting glucose", "glucose, fasting", "fasting plasma glucose",
    ],
)
def test_fasting_glucose_spellings_resolve_to_blood_glucose(alias: str):
    definition = concept_for_alias(alias, "numeric")
    assert definition is not None
    assert definition["name"] == "Blood glucose"


@pytest.mark.parametrize("alias", ["Глюкоза через 2 години", "Глюкоза постпрандіальна", "Глюкозотолерантний тест"])
def test_other_glucose_samples_still_resolve_to_nothing(alias: str):
    assert concept_for_alias(alias, "numeric") is None


# --- account deletion --------------------------------------------------------


def test_account_deletion_survives_a_provider_that_cannot_be_reached(
    tmp_path: Path, monkeypatch, caplog
):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)

    def unreachable(*args, **kwargs):
        raise RuntimeError("provider unreachable")

    monkeypatch.setattr(integrations, "disconnect", unreachable)
    caplog.set_level(logging.WARNING, logger="anamna.account")
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        response = client.post(
            "/profile/delete-account",
            data={"password": PASSWORD, "email": "alpha@example.test", "csrf_token": csrf_for(settings, client)},
            follow_redirects=False,
        )
    assert response.headers["location"] == "/login?notice=account_deleted"
    assert count(settings, "SELECT COUNT(*) FROM users WHERE id=?", alpha) == 0
    assert "account deletion: disconnecting garmin failed (RuntimeError)" in caplog.text


def test_the_heart_page_says_a_category_describes_one_reading(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    # The category chip and its note exist only where a pressure was read.
    add_observation(
        settings, user_id, concept(settings, "Systolic blood pressure"), 128.0,
        TODAY.isoformat(), "bp-sys", raw_name="Systolic", unit="mm Hg",
    )
    add_observation(
        settings, user_id, concept(settings, "Diastolic blood pressure"), 82.0,
        TODAY.isoformat(), "bp-dia", raw_name="Diastolic", unit="mm Hg",
    )
    page = client.get("/areas/heart")
    assert page.status_code == 200
    assert f'<p class="muted">{message("bp.single_reading_note")}</p>' in page.text
