"""Textless images remain visible evidence, without manufactured clinical facts."""
from __future__ import annotations

import pytest

from anamna import diagnosis_candidates
from anamna.db import connect, migrate
from anamna.health import IMAGE_SOURCE_REVIEW, present_finding, sync_clinical_findings
from anamna.i18n import activate_locale, reset_locale
from anamna.security import create_user
from anamna.web.app import _document_findings
from test_validate_source_extraction import validator
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for


@pytest.fixture
def ledger(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    owner = create_user(settings, "image-review@example.test", "Synthetic", PASSWORD)
    patient = seed_patient(settings, owner, "Synthetic")
    return settings, owner, patient


def _image(settings, owner, patient, filename="unknown-image.txt", date=None):
    document = seed_document(settings, owner, patient, "Unidentified image", filename)
    with connect(settings) as db:
        db.execute("UPDATE documents SET clinical_type='diagnostic_image',report_date=? WHERE id=?", (date, document))
        db.execute("INSERT INTO document_pages(document_id,page_number,native_text,extraction_method,review_status) "
                   "VALUES (?,1,'','none','not_reviewed')", (document,))
    return document


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_textless_unidentified_image_is_visible_without_an_invented_conclusion(ledger, locale):
    settings, owner, patient = ledger
    document = _image(settings, owner, patient)
    token = activate_locale(locale)
    try:
        with connect(settings) as db:
            sync_clinical_findings(db)
            rows = list(db.execute("SELECT * FROM clinical_findings WHERE document_id=?", (document,)))
            assert len(rows) == 1
            row = dict(rows[0])
            assert row["health_area"] == "imaging"
            assert row["title"] == "Medical images"
            assert row["summary_en"] == IMAGE_SOURCE_REVIEW
            assert row["summary_uk"] == row["original_text"] == row["recommendations"] == row["attention_reasons"] == ""
            assert row["finding_date"] is None
            assert row["status"] == "information"
            assert row["confidence"] == 0
            assert row["verification_status"] == "extracted"
            shown = present_finding(row)["summary_text"]
            assert ("source review" in shown) if locale == "en" else ("перевірки джерела" in shown)
            assert _document_findings(db, owner, document)[0]["text"] == shown
            record = {}
            validator.check_findings(record, db, db.execute("SELECT * FROM documents WHERE id=?", (document,)).fetchone(),
                                     rows, list(db.execute("SELECT * FROM document_pages WHERE document_id=?", (document,))), [1])
            assert not record.get("issues")
            before = [tuple(r) for r in db.execute("SELECT * FROM clinical_findings")]
            sync_clinical_findings(db)
            assert before == [tuple(r) for r in db.execute("SELECT * FROM clinical_findings")]
    finally:
        reset_locale(token)


def test_two_unknown_studies_with_same_date_are_not_deduplicated(ledger):
    settings, owner, patient = ledger
    documents = {_image(settings, owner, patient, filename, "2025-01-01") for filename in ("a.txt", "b.txt")}
    with connect(settings) as db:
        sync_clinical_findings(db)
        assert {r[0] for r in db.execute("SELECT document_id FROM clinical_findings")} == documents


def test_source_review_notice_is_not_a_diagnosis_but_a_persons_conclusion_is(ledger):
    settings, owner, patient = ledger
    document = _image(settings, owner, patient)
    with connect(settings) as db:
        sync_clinical_findings(db)
        assert diagnosis_candidates.collect(db, owner) == 0
        assert db.execute("SELECT count(*) FROM diagnosis_candidates").fetchone()[0] == 0
        db.execute("UPDATE clinical_findings SET summary_en='Hypertension.',verification_status='corrected' WHERE document_id=?", (document,))
        assert diagnosis_candidates.collect(db, owner) == 1
        assert db.execute("SELECT name FROM diagnosis_candidates").fetchone()[0] == "Hypertension"
        sync_clinical_findings(db)
        assert db.execute("SELECT summary_en FROM clinical_findings").fetchone()[0] == "Hypertension."


def test_newly_extracted_conclusion_replaces_machine_source_review_notice(ledger):
    settings, owner, patient = ledger
    document = _image(settings, owner, patient)
    with connect(settings) as db:
        sync_clinical_findings(db)
        db.execute("UPDATE documents SET title='Chest imaging' WHERE id=?", (document,))
        db.execute("UPDATE document_pages SET native_text='Chest imaging\nConclusion: No focal lung abnormality.' WHERE document_id=?", (document,))
        sync_clinical_findings(db)
        rows = list(db.execute("SELECT * FROM clinical_findings WHERE document_id=?", (document,)))
        assert len(rows) == 1
        assert rows[0]["health_area"] == "lungs"
        assert rows[0]["summary_en"] == "No focal lung abnormality."


@pytest.mark.parametrize("ruling", ["verified", "corrected", "rejected"])
def test_unknown_organ_fallback_never_sits_beside_a_persons_different_area_ruling(ledger, ruling):
    settings, owner, patient = ledger
    document = _image(settings, owner, patient)
    with connect(settings) as db:
        sync_clinical_findings(db)
        db.execute("UPDATE clinical_findings SET health_area='ent',title='ENT CT image set',"
                   "summary_en='Reviewed image evidence.',verification_status=? WHERE document_id=?", (ruling, document))
        before = [tuple(row) for row in db.execute("SELECT * FROM clinical_findings")]
        sync_clinical_findings(db)
        assert before == [tuple(row) for row in db.execute("SELECT * FROM clinical_findings")]
