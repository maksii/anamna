"""Medicines that belong to a diagnosis: the ATC groups, the person's own links, and the strings.

Each test asserts one rule.  The database is a temporary one; nothing is shared with other files.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from anamna import diagnoses, diagnosis_treatment as dt, factors, icd10
from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.i18n import MESSAGES
from anamna.locales.messages_diagnosis_treatment import MESSAGES_DIAGNOSIS_TREATMENT
from anamna.security import create_user

TODAY = date(2025, 6, 1)
PASSWORD = "a-long-local-password"
ATC_SHAPE = re.compile(r"^[A-Z][0-9]{2}[A-Z]{0,2}$")
SPEC_KEYS = {
    "dx.treat.heading", "dx.treat.lead", "dx.treat.none", "dx.treat.basis_atc", "dx.treat.basis_linked",
    "dx.treat.remove", "dx.treat.add_label", "dx.treat.add", "dx.treat.open_medicines", "dx.treat.atc_explain",
    "dx.treat.source", "dx.notice.medicine_linked", "dx.notice.medicine_unlinked", "dx.error.medicine",
    "ai.dx_treated_with",
}


def settings_for(tmp_path: Path) -> Settings:
    sources = tmp_path / "sources"
    sources.mkdir()
    return Settings(
        database_path=tmp_path / "health.sqlite3",
        source_dir=sources,
        secret_key="test-secret",
        session_days=1,
    )


def seed_patient(settings: Settings, user_id: str, name: str) -> str:
    patient_id = f"patient-{user_id}"
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO patients(id, owner_user_id, display_name, created_at) VALUES (?, ?, ?, ?)",
            (patient_id, user_id, name, utc_now()),
        )
    return patient_id


@pytest.fixture
def db(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    connection = connect(settings)
    yield SimpleNamespace(
        settings=settings, connection=connection,
        alpha=alpha, beta=beta,
        alpha_patient=seed_patient(settings, alpha, "Alpha"),
        beta_patient=seed_patient(settings, beta, "Beta"),
    )
    connection.close()


def diagnosis(db, owner: str, patient: str, code: str) -> dict:
    values, errors = diagnoses.clean({"code": code, "status": "active", "certainty": "confirmed"}, today=TODAY)
    assert errors == [], errors
    return diagnoses.get(db.connection, owner, diagnoses.create(db.connection, owner, patient, values))


def factor(db, owner: str, patient: str, *, kind: str = "medicine", name: str = "Valsartan",
           atc: str = "C09CA03", ended_on: str | None = None) -> str:
    factor_id = str(uuid.uuid4())
    now = utc_now()
    db.connection.execute(
        "INSERT INTO factors(id, owner_user_id, patient_id, kind, name, atc_code, status, ended_on, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (factor_id, owner, patient, kind, name, atc, "current", ended_on, now, now),
    )
    return factor_id


def medicine_ids(db, owner: str, dx: dict) -> list[str]:
    return [item["factor"]["id"] for item in dt.medicines(db.connection, owner, dx, today=TODAY)]


# --- the catalogue of groups and the strings -------------------------------------------


def test_every_icd_prefix_of_a_group_is_a_catalogue_code():
    missing = [prefix for group in dt.GROUPS for prefix in group.icd if icd10.entry(prefix) is None]
    assert missing == []


def test_every_atc_prefix_has_the_who_shape_and_group_keys_are_unique():
    assert all(ATC_SHAPE.match(prefix) for group in dt.GROUPS for prefix in group.atc)
    keys = [group.key for group in dt.GROUPS]
    assert len(keys) == len(set(keys))


def test_every_group_name_and_every_string_exists_in_both_locales():
    keys = SPEC_KEYS | {f"dx.atc.{group.key}" for group in dt.GROUPS}
    assert set(MESSAGES_DIAGNOSIS_TREATMENT) == keys
    for key in keys:
        assert MESSAGES[key]["en"], key
        assert MESSAGES[key]["uk"], key


# --- the ATC match ---------------------------------------------------------------------


def test_a_valsartan_group_matches_hypertension_with_the_reason_it_matched():
    assert dt.group_for("C09CA03", "I11.9").key == "c09"
    assert dt.group_for("c09ca03", "i11.9").key == "c09"
    assert dt.group_for("C10AA05", "E78.2").key == "c10"


def test_a_group_does_not_match_a_condition_it_is_not_used_for():
    assert dt.group_for("C09CA03", "E78.2") is None
    assert dt.group_for("", "I10") is None
    assert dt.group_for("C09CA03", "") is None


def test_a_medicine_appears_on_its_diagnosis_by_atc_group_with_the_matching_prefix(db):
    alpha_dx = diagnosis(db, db.alpha, db.alpha_patient, "I11.9")
    valsartan = factor(db, db.alpha, db.alpha_patient)
    items = dt.medicines(db.connection, db.alpha, alpha_dx, today=TODAY)
    assert [(item["factor"]["id"], item["basis"], item["group"], item["atc_prefix"]) for item in items] == [
        (valsartan, "atc", "c09", "C09"),
    ]


def test_a_medicine_of_another_group_is_not_on_an_unrelated_diagnosis(db):
    lipid = diagnosis(db, db.alpha, db.alpha_patient, "E78.2")
    factor(db, db.alpha, db.alpha_patient)
    assert dt.medicines(db.connection, db.alpha, lipid, today=TODAY) == []


# --- the person's own links ------------------------------------------------------------


def test_unlinking_hides_an_atc_match_and_offers_the_medicine_as_a_choice(db):
    dx = diagnosis(db, db.alpha, db.alpha_patient, "I11.9")
    valsartan = factor(db, db.alpha, db.alpha_patient)
    assert dt.unlink(db.connection, db.alpha, dx["id"], valsartan) is True
    assert medicine_ids(db, db.alpha, dx) == []
    assert [row["id"] for row in dt.choices(db.connection, db.alpha, dx, today=TODAY)] == [valsartan]


def test_linking_brings_the_medicine_back_as_linked(db):
    dx = diagnosis(db, db.alpha, db.alpha_patient, "I11.9")
    valsartan = factor(db, db.alpha, db.alpha_patient)
    dt.unlink(db.connection, db.alpha, dx["id"], valsartan)
    assert dt.link(db.connection, db.alpha, dx["id"], valsartan) is True
    (item,) = dt.medicines(db.connection, db.alpha, dx, today=TODAY)
    assert (item["basis"], item["group"], item["atc_prefix"]) == ("linked", "c09", "C09")
    assert dt.choices(db.connection, db.alpha, dx, today=TODAY) == []


def test_a_medicine_without_an_atc_code_appears_only_once_linked(db):
    dx = diagnosis(db, db.alpha, db.alpha_patient, "I11.9")
    magnesium = factor(db, db.alpha, db.alpha_patient, kind="supplement", name="Magnesium", atc="")
    assert medicine_ids(db, db.alpha, dx) == []
    assert dt.link(db.connection, db.alpha, dx["id"], magnesium) is True
    (item,) = dt.medicines(db.connection, db.alpha, dx, today=TODAY)
    assert (item["basis"], item["group"], item["atc_prefix"]) == ("linked", "", "")


def test_an_illness_is_never_a_medicine_and_cannot_be_linked(db):
    dx = diagnosis(db, db.alpha, db.alpha_patient, "I11.9")
    illness = factor(db, db.alpha, db.alpha_patient, kind="illness", name="Hypertension", atc="")
    assert dt.link(db.connection, db.alpha, dx["id"], illness) is False
    assert medicine_ids(db, db.alpha, dx) == []
    assert dt.choices(db.connection, db.alpha, dx, today=TODAY) == []


def test_another_persons_diagnosis_or_medicine_cannot_be_linked(db):
    alpha_dx = diagnosis(db, db.alpha, db.alpha_patient, "I11.9")
    beta_dx = diagnosis(db, db.beta, db.beta_patient, "I11.9")
    alpha_factor = factor(db, db.alpha, db.alpha_patient)
    beta_factor = factor(db, db.beta, db.beta_patient)
    assert dt.link(db.connection, db.beta, alpha_dx["id"], beta_factor) is False
    assert dt.link(db.connection, db.alpha, beta_dx["id"], alpha_factor) is False
    assert dt.link(db.connection, db.alpha, alpha_dx["id"], beta_factor) is False
    assert dt.unlink(db.connection, db.alpha, beta_dx["id"], alpha_factor) is False


# --- names and cascades ----------------------------------------------------------------


def test_names_leaves_out_a_medicine_that_has_ended(db):
    dx = diagnosis(db, db.alpha, db.alpha_patient, "I11.9")
    factor(db, db.alpha, db.alpha_patient, name="Valsartan 80 mg")
    factor(db, db.alpha, db.alpha_patient, name="Old valsartan", ended_on="2025-01-01")
    assert dt.names(db.connection, db.alpha, dx, today=TODAY) == ["Valsartan 80 mg"]


def test_deleting_the_diagnosis_or_the_medicine_removes_the_link(db):
    dx = diagnosis(db, db.alpha, db.alpha_patient, "I11.9")
    valsartan = factor(db, db.alpha, db.alpha_patient)
    other = factor(db, db.alpha, db.alpha_patient, name="Other", atc="")
    dt.link(db.connection, db.alpha, dx["id"], valsartan)
    dt.link(db.connection, db.alpha, dx["id"], other)
    factors.delete(db.connection, db.alpha, valsartan)
    remaining = db.connection.execute("SELECT factor_id FROM diagnosis_medicines").fetchall()
    assert [row["factor_id"] for row in remaining] == [other]
    diagnoses.delete(db.connection, db.alpha, dx["id"])
    assert db.connection.execute("SELECT COUNT(*) FROM diagnosis_medicines").fetchone()[0] == 0
    assert db.connection.execute("PRAGMA foreign_key_check").fetchall() == []
