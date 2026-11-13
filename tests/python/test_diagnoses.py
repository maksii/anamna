"""Diagnoses on the record: the migration, the input rules, the owner's rows, status and dates,
the order of the list, the names shown for a code, and the active codes.

Each test asserts one rule.  The database is a temporary one, built through the same
helpers the lifecycle tests use; nothing is shared with the other test files.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from anamna import diagnoses, icd10
from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.security import create_user

TODAY = date(2025, 6, 1)
PASSWORD = "a-long-local-password"
TABLES = {
    "diagnoses", "diagnosis_scans", "diagnosis_candidates", "diagnosis_suspicions", "diagnosis_refresh",
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


def cleaned(**fields) -> dict:
    values, errors = diagnoses.clean(fields, today=TODAY)
    assert errors == [], errors
    return values


def add(db, owner: str, patient: str, **fields) -> str:
    return diagnoses.create(db.connection, owner, patient, cleaned(**fields))


def fetch(db, diagnosis_id: str, owner: str | None = None) -> dict | None:
    return diagnoses.get(db.connection, owner or db.alpha, diagnosis_id)


def test_migration_creates_the_five_tables(db):
    names = {
        row["name"] for row in db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert TABLES <= names
    assert db.connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_clean_refuses_a_code_outside_the_catalogue_and_keeps_its_text():
    values, errors = diagnoses.clean({"code": "Ж00", "name": "", "diagnosed_on": ""}, today=TODAY)
    assert errors == ["code_unknown", "name_required"]
    assert values["code"] == "Ж00"


def test_clean_requires_a_name_or_a_known_code():
    _, errors = diagnoses.clean({}, today=TODAY)
    assert errors == ["name_required"]
    _, errors = diagnoses.clean({"name": "Anaemia"}, today=TODAY)
    assert errors == []


def test_clean_accepts_a_code_alone_with_an_empty_name():
    values, errors = diagnoses.clean({"code": "E78.2"}, today=TODAY)
    assert errors == []
    assert values["code"] == "E78.2"
    assert values["name"] == ""


def test_clean_normalises_a_cyrillic_code():
    values, errors = diagnoses.clean({"code": "Е78,2 "}, today=TODAY)  # Cyrillic Е
    assert errors == []
    assert values["code"] == "E78.2"


def test_clean_drops_the_resolved_date_of_an_active_diagnosis():
    values, errors = diagnoses.clean(
        {"name": "Anaemia", "status": "active", "diagnosed_on": "2024-01-10", "resolved_on": "2024-06-01"},
        today=TODAY,
    )
    assert errors == []
    assert values["resolved_on"] is None
    assert values["diagnosed_on"] == "2024-01-10"


def test_clean_reports_each_date_error_once():
    _, errors = diagnoses.clean(
        {"name": "x", "status": "resolved", "diagnosed_on": "2024-13-01", "resolved_on": "2024-02-30"},
        today=TODAY,
    )
    assert errors == ["date_invalid"]


def test_clean_reports_a_future_date_and_a_reversed_pair():
    _, errors = diagnoses.clean({"name": "x", "diagnosed_on": "2030-01-01"}, today=TODAY)
    assert errors == ["date_future"]
    _, errors = diagnoses.clean(
        {"name": "x", "status": "resolved", "diagnosed_on": "2024-05-01", "resolved_on": "2024-01-01"},
        today=TODAY,
    )
    assert errors == ["date_order"]


def test_clean_falls_back_for_an_unknown_status_and_certainty():
    values, _ = diagnoses.clean({"name": "x", "status": "bogus", "certainty": "bogus"}, today=TODAY)
    assert values["status"] == "active"
    assert values["certainty"] == "confirmed"


def test_clean_applies_text_limits_and_flags():
    values, errors = diagnoses.clean(
        {
            "name": "  " + "a" * 300 + "  ", "clinician": "c" * 250, "notes": "n" * 2500,
            "dates_approximate": "on", "document_id": "  ",
        },
        today=TODAY,
    )
    assert errors == []
    assert len(values["name"]) == 200
    assert len(values["clinician"]) == 200
    assert len(values["notes"]) == 2000
    assert values["dates_approximate"] == 1
    assert values["document_id"] is None


def test_create_get_update_and_delete(db):
    diagnosis_id = add(db, db.alpha, db.alpha_patient, code="E78.2", diagnosed_on="2024-01-10")
    row = fetch(db, diagnosis_id)
    assert row["code"] == "E78.2"
    assert row["origin"] == "person"
    assert row["patient_id"] == db.alpha_patient

    changed = cleaned(code="E78.2", name="Mixed lipids", diagnosed_on="2024-02-01", clinician="Dr X")
    assert diagnoses.update(db.connection, db.alpha, diagnosis_id, changed) is True
    row = fetch(db, diagnosis_id)
    assert row["name"] == "Mixed lipids"
    assert row["diagnosed_on"] == "2024-02-01"
    assert row["clinician"] == "Dr X"

    assert diagnoses.delete(db.connection, db.alpha, diagnosis_id) is True
    assert fetch(db, diagnosis_id) is None


def test_another_owner_cannot_read_change_or_delete_the_row(db):
    diagnosis_id = add(db, db.alpha, db.alpha_patient, code="E78.2", name="Mixed lipids")
    assert fetch(db, diagnosis_id, owner=db.beta) is None
    assert diagnoses.update(db.connection, db.beta, diagnosis_id, cleaned(name="Stolen")) is False
    assert diagnoses.set_status(db.connection, db.beta, diagnosis_id, "resolved", today=TODAY) is False
    assert diagnoses.delete(db.connection, db.beta, diagnosis_id) is False
    row = fetch(db, diagnosis_id)
    assert row is not None
    assert row["name"] == "Mixed lipids"
    assert row["status"] == "active"


def add_document(db, document_id: str, owner: str, patient: str) -> None:
    db.connection.execute(
        """INSERT INTO documents(id, owner_user_id, patient_id, original_filename, source_path, mime_type,
               byte_size, sha256, page_count, title, clinical_type, extraction_strategy, imported_at)
           VALUES (?, ?, ?, 'consult.pdf', 'consult.pdf', 'application/pdf', 1, ?, 1, 'Consultation',
               'other', 'native', ?)""",
        (document_id, owner, patient, f"sha-{document_id}", utc_now()),
    )


def add_accepted_candidate(db, candidate_id: str, document_id: str, owner: str, diagnosis_id: str) -> None:
    db.connection.execute(
        """INSERT INTO diagnosis_candidates(id, owner_user_id, document_id, method, code, code_printed, name,
               name_key, certainty, timing, event_date, date_exact, quote, state, diagnosis_id, created_at)
           VALUES (?, ?, ?, 'code', 'E78.2', 1, 'Mixed lipids', 'mixed lipids', 'confirmed', 'now',
               '2025-01-15', 1, 'E78.2 Mixed lipids', 'accepted', ?, ?)""",
        (candidate_id, owner, document_id, diagnosis_id, utc_now()),
    )


def candidate_row(db, candidate_id: str) -> tuple:
    row = db.connection.execute(
        "SELECT state, diagnosis_id FROM diagnosis_candidates WHERE id=?", (candidate_id,)
    ).fetchone()
    return row["state"], row["diagnosis_id"]


def test_deleting_a_diagnosis_sends_its_accepted_candidates_to_the_hidden_suggestions(db):
    add_document(db, "doc-alpha", db.alpha, db.alpha_patient)
    diagnosis_id = add(db, db.alpha, db.alpha_patient, code="E78.2", name="Mixed lipids")
    add_accepted_candidate(db, "cand-alpha", "doc-alpha", db.alpha, diagnosis_id)
    db.connection.commit()

    assert diagnoses.delete(db.connection, db.alpha, diagnosis_id) is True
    assert candidate_row(db, "cand-alpha") == ("dismissed", None)


def test_deleting_another_owners_diagnosis_leaves_their_candidates_alone(db):
    add_document(db, "doc-alpha", db.alpha, db.alpha_patient)
    add_document(db, "doc-beta", db.beta, db.beta_patient)
    alpha_id = add(db, db.alpha, db.alpha_patient, code="E78.2", name="Mixed lipids")
    beta_id = add(db, db.beta, db.beta_patient, code="E78.2", name="Mixed lipids")
    add_accepted_candidate(db, "cand-alpha", "doc-alpha", db.alpha, alpha_id)
    add_accepted_candidate(db, "cand-beta", "doc-beta", db.beta, beta_id)
    db.connection.commit()

    assert diagnoses.delete(db.connection, db.alpha, beta_id) is False
    assert candidate_row(db, "cand-beta") == ("accepted", beta_id)
    assert diagnoses.delete(db.connection, db.beta, alpha_id) is False
    assert candidate_row(db, "cand-alpha") == ("accepted", alpha_id)


def test_set_status_moves_between_the_three_states(db):
    diagnosis_id = add(db, db.alpha, db.alpha_patient, name="Gout", diagnosed_on="2024-01-10")

    assert diagnoses.set_status(db.connection, db.alpha, diagnosis_id, "resolved", today=TODAY) is True
    row = fetch(db, diagnosis_id)
    assert row["status"] == "resolved"
    assert row["resolved_on"] == TODAY.isoformat()

    assert diagnoses.set_status(db.connection, db.alpha, diagnosis_id, "active", today=TODAY) is True
    row = fetch(db, diagnosis_id)
    assert row["status"] == "active"
    assert row["resolved_on"] is None

    assert diagnoses.set_status(db.connection, db.alpha, diagnosis_id, "outdated", today=TODAY) is True
    assert fetch(db, diagnosis_id)["status"] == "outdated"


def test_set_status_keeps_an_end_date_already_set(db):
    diagnosis_id = add(db, db.alpha, db.alpha_patient, name="Gout", diagnosed_on="2024-01-10", resolved_on="2024-03-01", status="resolved")
    diagnoses.set_status(db.connection, db.alpha, diagnosis_id, "outdated", today=TODAY)
    assert fetch(db, diagnosis_id)["resolved_on"] == "2024-03-01"


def test_set_status_never_ends_before_the_diagnosis(db):
    diagnosis_id = add(db, db.alpha, db.alpha_patient, name="Gout", diagnosed_on="2025-05-20")
    diagnoses.set_status(db.connection, db.alpha, diagnosis_id, "resolved", today=date(2025, 5, 1))
    assert fetch(db, diagnosis_id)["resolved_on"] == "2025-05-20"


def test_set_status_refuses_an_unknown_status_and_a_missing_row(db):
    diagnosis_id = add(db, db.alpha, db.alpha_patient, name="Gout")
    assert diagnoses.set_status(db.connection, db.alpha, diagnosis_id, "cured", today=TODAY) is False
    assert diagnoses.set_status(db.connection, db.alpha, "no-such-id", "resolved", today=TODAY) is False


def test_listing_puts_active_first_newest_first_and_undated_last(db):
    add(db, db.alpha, db.alpha_patient, name="Old and over", diagnosed_on="2024-01-01", status="resolved", resolved_on="2024-06-01")
    add(db, db.alpha, db.alpha_patient, name="Older active", diagnosed_on="2020-01-01")
    add(db, db.alpha, db.alpha_patient, name="Undated active")
    add(db, db.alpha, db.alpha_patient, name="Newer active", diagnosed_on="2023-06-01")
    add(db, db.alpha, db.alpha_patient, name="Newest active", diagnosed_on="2024-09-01")

    names = [row["name"] for row in diagnoses.listing(db.connection, db.alpha)]
    assert names == [
        "Newest active", "Newer active", "Older active", "Undated active", "Old and over",
    ]
    assert diagnoses.listing(db.connection, db.beta) == []


def test_display_name_uses_the_catalogue_title_for_a_coded_row_without_a_name():
    row = {"code": "E78.2", "name": ""}
    english = diagnoses.display_name(row, "en")
    ukrainian = diagnoses.display_name(row, "uk")
    assert english == icd10.name("E78.2", "en")
    assert ukrainian == icd10.name("E78.2", "uk")
    assert english != ukrainian
    assert "E78.2" not in (english, ukrainian)


def test_display_name_is_the_catalogue_title_in_the_readers_language_for_a_written_name():
    row = {"code": "E78.2", "name": "Змішана гіперліпідемія, уточнено лікарем"}
    assert diagnoses.display_name(row, "en") == icd10.name("E78.2", "en") == "Mixed hyperlipidaemia"
    assert diagnoses.display_name(row, "uk") == icd10.name("E78.2", "uk") == "Змішана гіперліпідемія"


def test_display_name_is_the_written_name_for_an_uncoded_row_in_both_locales():
    row = {"code": "", "name": "Плантарний фасциїт"}
    assert diagnoses.display_name(row, "en") == "Плантарний фасциїт"
    assert diagnoses.display_name(row, "uk") == "Плантарний фасциїт"


def test_display_name_is_the_written_name_for_a_code_outside_the_catalogue():
    assert icd10.entry("Z99.99") is None
    row = {"code": "Z99.99", "name": "Written only"}
    assert diagnoses.display_name(row, "en") == "Written only"
    assert diagnoses.display_name(row, "uk") == "Written only"


def test_display_name_falls_back_to_the_code_for_an_unknown_code():
    assert diagnoses.display_name({"code": "Ж00", "name": ""}, "en") == "Ж00"
    assert diagnoses.display_name({"code": "", "name": ""}, "en") == ""


def test_written_detail_is_what_the_document_adds_after_the_ukrainian_title():
    title = icd10.name("I11.9", "uk")
    row = {"code": "I11.9", "name": title + " Гіпертонічна хвороба Іст, 1ст"}
    assert diagnoses.written_detail(row) == "Гіпертонічна хвороба Іст, 1ст"


def test_written_detail_drops_a_separator_between_the_title_and_the_addition():
    title = icd10.name("E78.2", "uk")
    assert diagnoses.written_detail({"code": "E78.2", "name": title + ", як записано"}) == "як записано"


def test_written_detail_is_empty_when_the_name_repeats_a_title():
    uk = icd10.name("E78.2", "uk")
    en = icd10.name("E78.2", "en")
    assert diagnoses.written_detail({"code": "E78.2", "name": uk}) == ""
    assert diagnoses.written_detail({"code": "E78.2", "name": en}) == ""
    assert diagnoses.written_detail({"code": "E78.2", "name": en.upper()}) == ""


def test_written_detail_is_empty_without_a_code_or_a_name_or_for_an_unknown_code():
    assert diagnoses.written_detail({"code": "", "name": "Плантарний фасциїт"}) == ""
    assert diagnoses.written_detail({"code": "E78.2", "name": ""}) == ""
    assert diagnoses.written_detail({"code": "Z99.99", "name": "Written only"}) == ""


def test_written_detail_is_the_whole_name_when_it_does_not_start_with_the_title():
    row = {"code": "B07", "name": "бородавки на руці"}
    assert diagnoses.written_detail(row) == "бородавки на руці"


def test_active_codes_leaves_out_resolved_rows_and_blank_codes(db):
    add(db, db.alpha, db.alpha_patient, code="E78.2", certainty="provisional")
    add(db, db.alpha, db.alpha_patient, code="E78.2", name="Second entry")
    add(db, db.alpha, db.alpha_patient, code="E11", status="resolved", resolved_on="2024-01-01", diagnosed_on="2023-01-01")
    add(db, db.alpha, db.alpha_patient, name="Named only")
    assert diagnoses.active_codes(db.connection, db.alpha) == {"E78.2"}
    assert diagnoses.active_codes(db.connection, db.beta) == set()


def test_deleting_the_user_cascades_to_the_diagnoses(db):
    add(db, db.alpha, db.alpha_patient, code="E78.2")
    db.connection.execute("DELETE FROM users WHERE id=?", (db.alpha,))
    db.connection.commit()
    count = db.connection.execute("SELECT COUNT(*) FROM diagnoses WHERE owner_user_id=?", (db.alpha,)).fetchone()[0]
    assert count == 0
    assert db.connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_the_table_refuses_a_row_with_neither_code_nor_name(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO diagnoses (id, owner_user_id, patient_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("row-without-label", db.alpha, db.alpha_patient, utc_now(), utc_now()),
        )
