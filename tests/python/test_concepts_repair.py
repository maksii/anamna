"""The start-up repair re-files stored rows, audits it, and derives eGFR."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anamna.db import connect, utc_now
from anamna.derived import (
    DERIVED_EGFR_METHOD,
    EGFR_CONCEPT_ID,
    ckd_epi_2021,
    refresh_derived_observations,
)
from anamna.ingest.pipeline import repair_observation_semantics

from test_web_panels import build


def _insert(connection, user_id, row_id, raw_name, concept_id, *, value=None, text=None, unit=None,
            canonical=None, status="verified", observed="2025-02-13", report_title=None):
    connection.execute(
        """INSERT INTO observations(
               id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
               value_type, value_numeric, value_text, unit_raw, unit_canonical, observed_at,
               verification_status, extraction_method, confidence, evidence_text, parser_version,
               created_at)
           VALUES (?, ?, ?, 'doc-1', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'native_pdf_text_parser', 0.9,
                   ?, 'test', ?)""",
        (row_id, user_id, f"patient-{user_id}", concept_id, raw_name,
         "numeric" if value is not None else "text", value, text, unit, canonical, observed,
         status, f"{raw_name} {value or text}", utc_now()),
    )


def test_old_rows_move_to_the_new_concepts_keep_their_value_and_verification(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        # As the previous catalogue filed them.
        _insert(connection, user_id, "smear", "Лімфоцити", "lymphocytes", value=36.0, unit="%", canonical="%")
        _insert(connection, user_id, "abs", "Нейтрофіли (абс.)", "granulocytes-absolute", value=3.08,
                unit="10^9", canonical="10^9")
        _insert(connection, user_id, "pct", "Тромбокрит (PCT)", "plateletcrit", value=0.3,
                unit="х 10*9/л", canonical="х 10*9/л")
        # The concept the HCV split left behind; no definition names it any more.
        connection.execute("INSERT OR IGNORE INTO concepts(id, canonical_name, category, value_type, created_at) "
                           "VALUES ('hepatitis-c-antibodies', 'Hepatitis C antibodies', 'infection', 'numeric', ?)",
                           (utc_now(),))
        _insert(connection, user_id, "hcv", "Вірус гепатиту C (HCV), антитіла сумарні",
                "hepatitis-c-antibodies", value=0.12, unit="Індекс", canonical="Індекс")
        mark = connection.execute("SELECT COALESCE(MAX(id), 0) FROM audit_events").fetchone()[0]
        repair_observation_semantics(connection)
        rows = {
            row["id"]: row
            for row in connection.execute(
                "SELECT * FROM observations WHERE id IN ('smear', 'abs', 'pct', 'hcv')"
            )
        }
        audits = connection.execute(
            "SELECT action, entity_id, actor_user_id, details_json FROM audit_events WHERE id > ?", (mark,)
        ).fetchall()
        assert rows["smear"]["concept_id"] == "lymphocytes-manual-differential"
        assert rows["abs"]["concept_id"] == "neutrophils-absolute"
        assert rows["hcv"]["concept_id"] == "hepatitis-c-total-antibodies"
        assert rows["pct"]["unit_canonical"] == "%"
        for row_id, value in (("smear", 36.0), ("abs", 3.08), ("pct", 0.3), ("hcv", 0.12)):
            assert rows[row_id]["value_numeric"] == value
            assert rows[row_id]["verification_status"] == "verified"
        assert rows["pct"]["unit_raw"] == "х 10*9/л"

        moved = {(a["action"], a["entity_id"]): json.loads(a["details_json"]) for a in audits}
        assert moved[("observation_concept_remapped", "smear")]["from"] == "lymphocytes"
        assert moved[("observation_concept_remapped", "smear")]["to"] == "lymphocytes-manual-differential"
        assert moved[("observation_concept_remapped", "smear")]["verification_status"] == "verified"
        folded = moved[("observation_unit_folded", "pct")]
        assert (folded["from"], folded["to"], folded["value_numeric"]) == ("х 10*9/л", "%", 0.3)
        assert all(a["actor_user_id"] is None for a in audits)

        # Idempotent: nothing to move, nothing written.
        mark = connection.execute("SELECT COALESCE(MAX(id), 0) FROM audit_events").fetchone()[0]
        assert repair_observation_semantics(connection) == 0
        assert connection.execute("SELECT COUNT(*) FROM audit_events WHERE id > ?", (mark,)).fetchone()[0] == 0


def test_a_human_correction_is_still_not_re_derived(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        _insert(connection, user_id, "kept", "Лімфоцити", "lymphocytes", value=36.0, unit="%")
        connection.execute("UPDATE observations SET extraction_method='human_corrected' WHERE id='kept'")
        repair_observation_semantics(connection)
        assert connection.execute("SELECT concept_id FROM observations WHERE id='kept'").fetchone()[0] == "lymphocytes"


# --- eGFR -------------------------------------------------------------------


@pytest.mark.parametrize(
    "creatinine_mg_dl, age, sex, expected",
    [
        # Worked from the published equation (Inker et al. 2021): at Scr = κ
        # only the age term and the sex factor remain.
        (0.9, 40, "male", 142 * 0.9938**40),
        (0.7, 40, "female", 142 * 0.9938**40 * 1.012),
        # Above κ the −1.200 exponent applies.
        (1.8, 50, "male", 142 * (1.8 / 0.9) ** -1.200 * 0.9938**50),
        # Below κ the α exponent applies.
        (0.5, 30, "female", 142 * (0.5 / 0.7) ** -0.241 * 0.9938**30 * 1.012),
    ],
)
def test_ckd_epi_2021_matches_the_published_equation(creatinine_mg_dl, age, sex, expected):
    assert ckd_epi_2021(creatinine_mg_dl, age, sex) == pytest.approx(expected)


def test_ckd_epi_2021_reference_points():
    """NKF calculator: male, 60 years, creatinine 1.0 mg/dL -> 86."""
    assert round(ckd_epi_2021(1.0, 60, "male")) == 86


def _egfr(connection):
    return connection.execute(
        "SELECT * FROM observations WHERE extraction_method=?", (DERIVED_EGFR_METHOD,)
    ).fetchall()


def test_egfr_is_derived_from_creatinine_and_follows_its_input(tmp_path: Path):
    """Fixture: creatinine 88 µmol/L on 2025-02-13, male born 1990-03-14 (34)."""
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        # An unchecked creatinine gives nothing: no figure nobody confirmed.
        assert _egfr(connection) == []

        # A verified creatinine makes a verified eGFR -- arithmetic, not extraction.
        connection.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        refresh_derived_observations(connection)
        [row] = _egfr(connection)
        assert row["concept_id"] == EGFR_CONCEPT_ID
        assert row["value_numeric"] == round(ckd_epi_2021(88 / 88.4, 34, "male")) == 102
        assert row["unit_raw"] == "mL/min/1.73m²"
        assert row["document_id"] == "doc-1"
        assert row["observed_at"] == "2025-02-13"
        assert row["evidence_text"] == "Creatinine evidence"  # the printed line it came from
        assert row["verification_status"] == "verified"
        assert refresh_derived_observations(connection) == {"added": 0, "updated": 0, "removed": 0}

        # A corrected value recalculates.
        connection.execute("UPDATE observations SET value_numeric=150 WHERE concept_id='creatinine'")
        refresh_derived_observations(connection)
        assert _egfr(connection)[0]["value_numeric"] == round(ckd_epi_2021(150 / 88.4, 34, "male"))

        # No sex, no equation.
        connection.execute("UPDATE patients SET sex_at_birth='unknown'")
        refresh_derived_observations(connection)
        assert _egfr(connection) == []
        connection.execute("UPDATE patients SET sex_at_birth='male'")

        # A rejected creatinine takes its eGFR with it.
        connection.execute("UPDATE observations SET verification_status='rejected' WHERE concept_id='creatinine'")
        refresh_derived_observations(connection)
        assert _egfr(connection) == []
        connection.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        refresh_derived_observations(connection)
        connection.commit()

    page = client.get(f"/metrics/{EGFR_CONCEPT_ID}")
    assert page.status_code == 200
    assert "eGFR" in page.text or "glomerular" in page.text
    assert "/documents/doc-1" in page.text


def test_a_report_that_prints_its_own_egfr_is_not_given_a_second(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        _insert(connection, user_id, "printed-egfr", "рШКФ (CKD-EPI)", EGFR_CONCEPT_ID, value=101.0,
                unit="мл/хв/1,73м2", status="extracted")
        refresh_derived_observations(connection)
        assert _egfr(connection) == []


def test_no_egfr_for_a_child(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE concept_id='creatinine'")
        connection.execute("UPDATE patients SET date_of_birth='2015-01-01'")
        refresh_derived_observations(connection)
        assert _egfr(connection) == []


def test_a_change_through_the_web_recalculates(tmp_path: Path):
    """The middleware hook: any successful write refreshes derived values."""
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET value_numeric=150, verification_status='verified' WHERE concept_id='creatinine'"
        )
        connection.commit()
    # Any successful authenticated write will do; /locale answers 303.
    assert client.post("/locale", data={"lang": "en", "next": "/"}, follow_redirects=False).status_code == 303
    with connect(settings) as connection:
        assert _egfr(connection)[0]["value_numeric"] == round(ckd_epi_2021(150 / 88.4, 34, "male"))
