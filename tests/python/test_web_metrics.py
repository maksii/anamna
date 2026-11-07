"""The metric and devices pages explain themselves: why a judgement was
withheld, whose interval each guidance band is, and which Oura datasets or
permissions never arrived."""

from pathlib import Path

from fastapi.testclient import TestClient

from anamna.db import connect, migrate, utc_now
from anamna.reference import evaluate
from anamna.security import create_user
from anamna.web.app import (
    _blocked_notice,
    _oura_sync_context,
    _rule_applicability,
    create_app,
)

from test_web_profile import login
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for


def seed_sexed_concept(settings, user_id: str, patient_id: str, document_id: str) -> str:
    """One numeric observation of a concept whose only curated rules are
    sexed — the shape that produces curated_blocked='sex_unknown'."""
    concept_id = "test-hemoglobin"
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO concepts(id, canonical_name, category, value_type, preferred_unit, created_at)
               VALUES (?, 'Testoglobin', 'hematology', 'numeric', 'g/L', ?)""",
            (concept_id, utc_now()),
        )
        connection.execute(
            """INSERT INTO reference_sets(id, name, publisher, source_url, reviewed_at)
               VALUES ('set-test', 'Test intervals', 'Test Body', 'https://example.test', ?)""",
            (utc_now(),),
        )
        for rule_id, sex, low, high in (
            ("rule-f", "female", 120.0, 153.0),
            ("rule-m", "male", 134.0, 170.0),
        ):
            connection.execute(
                """INSERT INTO curated_reference_rules(
                       id, reference_set_id, concept_id, label, unit, lower_bound,
                       upper_bound, lower_inclusive, upper_inclusive, interpretation,
                       priority, sex, age_min_years, age_max_years
                   ) VALUES (?, 'set-test', ?, 'Within the reference interval', 'g/L',
                             ?, ?, 1, 1, 'normal', 10, ?, 18.0, 40.0)""",
                (rule_id, concept_id, low, high, sex),
            )
        connection.execute(
            """INSERT INTO observations(
                   id, owner_user_id, patient_id, document_id, page_number, concept_id,
                   raw_name, value_type, value_numeric, unit_raw, unit_canonical,
                   observed_at, verification_status, extraction_method, confidence,
                   evidence_text, parser_version, created_at
               ) VALUES ('obs-hb', ?, ?, ?, 1, ?, 'Testoglobin', 'numeric', 140.0,
                         'g/L', 'g/L', '2026-01-05', 'extracted', 'test', 0.9,
                         'Testoglobin 140 g/L', 'test', ?)""",
            (user_id, patient_id, document_id, concept_id, utc_now()),
        )
    return concept_id


def test_blocked_notice_maps_each_explainable_reason():
    for reason, links_to_profile in (
        ("sex_unknown", True),
        ("age_unknown", True),
        ("requires_clinical_context", False),
        ("sex_not_covered", False),
    ):
        notice = _blocked_notice({"curated_blocked": reason})
        assert notice is not None
        assert notice["reason"] == reason
        assert notice["text"]
        assert (notice["profile_url"] == "/profile?tab=personal") is links_to_profile
    # A withheld verdict can also carry the reason only as unjudged_reason.
    assert _blocked_notice({"unjudged_reason": "sex_unknown"})["reason"] == "sex_unknown"
    # Reasons with no sentence keep the generic empty state.
    assert _blocked_notice({"unjudged_reason": "no_rule"}) is None
    assert _blocked_notice({"curated_blocked": None}) is None
    assert _blocked_notice(None) is None


def test_rule_applicability_mirrors_the_matcher():
    sexed = {"sex": "male", "age_min_years": 18.0, "age_max_years": 40.0}
    assert _rule_applicability(sexed, 34, "male")["applies_to_you"] is True
    assert _rule_applicability(sexed, 34, "female")["applies_to_you"] is False
    # Unknown sex never matches a sexed rule — same as evaluate().
    assert _rule_applicability(sexed, 34, None)["applies_to_you"] is False
    assert _rule_applicability(sexed, 34, "unknown")["applies_to_you"] is False
    # The upper age bound excludes, exactly as reference.py's >= comparison.
    assert _rule_applicability(sexed, 40, "male")["applies_to_you"] is False
    assert _rule_applicability(sexed, None, "male")["applies_to_you"] is False
    # The chip names both constraints; an unconstrained rule needs no chip.
    assert _rule_applicability(sexed, 34, "male")["applicability"]
    unisex = {"sex": None, "age_min_years": None, "age_max_years": None}
    assert _rule_applicability(unisex, None, None) == {
        "applicability": None,
        "applies_to_you": True,
    }


def test_metric_page_carries_the_sex_unknown_block(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, alpha, "Alpha Patient")  # sex_at_birth NULL
    document = seed_document(settings, alpha, patient, "Blood counts", "cbc.txt")
    concept_id = seed_sexed_concept(settings, alpha, patient, document)
    with connect(settings) as connection:
        verdict = evaluate(
            connection, concept_id=concept_id, value_numeric=140.0, unit="g/L",
            age_years=None, sex=None,
        )
    assert verdict["curated_blocked"] == "sex_unknown"
    notice = _blocked_notice(verdict)
    assert notice and notice["profile_url"] == "/profile?tab=personal"
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        assert client.get(f"/metrics/{concept_id}").status_code == 200


def seed_oura_connection(settings, user_id: str, patient_id: str, scopes: str, metadata: str):
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO vendors(id, canonical_name, created_at) VALUES ('vendor-oura', 'Oura', ?)",
            (utc_now(),),
        )
        connection.execute(
            """INSERT INTO provider_connections(user_id, provider, scopes, connected_at, updated_at)
               VALUES (?, 'oura', ?, ?, ?)""",
            (user_id, scopes, utc_now(), utc_now()),
        )
        connection.execute(
            """INSERT INTO device_imports(
                   id, owner_user_id, patient_id, vendor_id, adapter_key, source_path,
                   source_fingerprint, source_bytes, metadata_json, imported_at
               ) VALUES ('import-oura', ?, ?, 'vendor-oura', 'oura_api', 'oura://api',
                         'api', 0, ?, ?)""",
            (user_id, patient_id, metadata, utc_now()),
        )


def test_devices_page_discloses_sync_failures_and_withheld_scopes(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, alpha, "Alpha Patient")
    # Everything granted except the two heart_health-era scopes; two datasets
    # failed on the last sync — the exact state DEV-1 found on the live record.
    seed_oura_connection(
        settings, alpha, patient,
        scopes="extapi:daily extapi:heartrate extapi:workout extapi:session "
               "extapi:spo2 extapi:tag extapi:personal",
        metadata='{"failed_datatypes": {"daily_cardiovascular_age": "403 Forbidden", '
                 '"workouts": "timed out"}}',
    )
    notice = _oura_sync_context(settings, alpha)
    assert notice is not None
    assert notice["reconnect_url"] == "/integrations/oura/connect"
    failures = {item["datatype"]: item for item in notice["failures"]}
    assert failures["daily_cardiovascular_age"]["error"] == "403 Forbidden"
    # Named by the metrics the dataset feeds, not by the API identifier.
    assert failures["daily_cardiovascular_age"]["label"] == "Cardiovascular age, Pulse wave velocity"
    assert failures["workouts"]["label"]
    assert notice["missing_scopes"] == ["Heart health", "Ring configuration"]
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        assert client.get("/devices").status_code == 200


def test_no_connection_means_no_notice(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    seed_patient(settings, alpha, "Alpha Patient")
    assert _oura_sync_context(settings, alpha) is None
