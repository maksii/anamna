"""Synthetic source files exercise ingestion without touching the personal ledger."""

from __future__ import annotations

from dataclasses import replace
import io
from pathlib import Path
import zipfile

import pytest
from PIL import Image

from anamna.config import Settings
from anamna.db import connect, migrate, transaction, utc_now
from anamna.ingest import extract, intake, pipeline
from anamna.ingest.classifier import extract_date
from anamna.ingest.text import parse_decimal
from anamna.security import create_user

from test_rescan import classification, observation, page


@pytest.fixture
def ledger(tmp_path: Path, monkeypatch):
    settings = Settings(tmp_path / "ledger.sqlite3", tmp_path / "sources", "test-secret")
    settings.source_dir.mkdir()
    migrate(settings)
    owner = create_user(settings, "owner@example.com", "owner", "synthetic-local-password")
    patient = f"patient-{owner}"
    with transaction(settings) as connection:
        connection.execute(
            "INSERT INTO patients(id, owner_user_id, display_name, created_at) VALUES (?, ?, ?, ?)",
            (patient, owner, "Synthetic patient", utc_now()),
        )
    klass = classification()
    monkeypatch.setattr(
        pipeline, "analyse_document",
        lambda path, run_ocr=True: pipeline.Analysis(
            [page(1)], "application/pdf", 1, "text-hash", klass, [klass]
        ),
    )
    monkeypatch.setattr(
        pipeline, "parse_pages",
        lambda *_, **__: [(observation("LDL cholesterol", 4.42), klass)],
    )
    monkeypatch.setattr(intake.paperless, "push_document", lambda *_: None)
    yield settings, owner, patient


def uploaded_source(settings, name="report.pdf"):
    path = settings.source_dir / "uploads" / "2026-09" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic document source")
    return path


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-Infinity", "1e999", "<Infinity"])
def test_nonfinite_numbers_are_not_measurements(value):
    assert parse_decimal(value) is None


def test_finite_exponents_and_localized_decimals_remain_accepted():
    assert parse_decimal("1e3") == 1000.0
    assert parse_decimal("<1 234,5") == 1234.5


def test_retry_after_ingest_commit_preserves_the_only_source_copy(ledger):
    settings, owner, patient = ledger
    source = uploaded_source(settings)
    first = pipeline.ingest_file(settings, owner, patient, source)
    intake.enqueue(
        settings, owner_user_id=owner, patient_id=patient, batch_id="retry",
        kind="document", filename=source.name, source_path=source, start=False,
    )
    intake.drain_now(settings)
    assert source.read_bytes() == b"synthetic document source"
    with connect(settings) as connection:
        job = connection.execute("SELECT * FROM upload_jobs").fetchone()
        assert job["document_id"] == first["document_id"]
        assert job["detail_key"] == "intake.done_unchanged"


def test_unreferenced_reupload_is_still_discarded(ledger):
    settings, owner, patient = ledger
    original = uploaded_source(settings)
    pipeline.ingest_file(settings, owner, patient, original)
    copy = original.parent / "second" / original.name
    copy.parent.mkdir()
    copy.write_bytes(original.read_bytes())
    intake._discard_upload_copy(settings, copy)
    assert original.is_file()
    assert not copy.exists()


def test_rescanning_a_duplicate_does_not_create_a_second_result_set(ledger):
    settings, owner, patient = ledger
    source = uploaded_source(settings)
    original = pipeline.ingest_file(settings, owner, patient, source)
    duplicate_path = uploaded_source(settings, "duplicate.pdf")
    duplicate = pipeline.ingest_file(settings, owner, patient, duplicate_path)
    assert duplicate["action"] == "duplicate"
    result = pipeline.reingest_document(settings, owner, str(duplicate["document_id"]))
    assert result["observations"] == 0
    with connect(settings) as connection:
        rows = connection.execute("SELECT document_id FROM observations").fetchall()
        assert [row[0] for row in rows] == [original["document_id"]]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("changed", [{"comparator": "<"}, {"observed_at": "2025-02-14"}])
def test_changed_comparator_or_measurement_date_is_reported_for_review(ledger, monkeypatch, changed):
    settings, owner, patient = ledger
    imported = pipeline.ingest_file(settings, owner, patient, uploaded_source(settings))
    revised = replace(observation("LDL cholesterol", 4.42), **changed)
    monkeypatch.setattr(pipeline, "parse_pages", lambda *_, **__: [(revised, classification())])
    result = pipeline.reingest_document(settings, owner, str(imported["document_id"]))
    assert result["appeared"] == result["vanished"] == 1


def test_tiff_pages_are_ocrd_separately_with_their_original_page_numbers(tmp_path, monkeypatch):
    source = tmp_path / "two-pages.tiff"
    first = Image.new("RGB", (40, 50), "red")
    second = Image.new("RGB", (40, 50), "blue")
    first.save(source, save_all=True, append_images=[second])

    def read_frame(path, psm):
        with Image.open(path) as image:
            return "first page" if image.convert("RGB").getpixel((0, 0)) == (255, 0, 0) else "second page"

    monkeypatch.setattr(extract, "ocr_layout_rows", read_frame)
    extracted = extract.extract_document(source)
    assert extracted["page_count"] == 2
    assert [(p["page_number"], p["ocr_text"]) for p in extracted["pages"]] == [
        (1, "first page"), (2, "second page")
    ]
    without_ocr = extract.extract_document(source, run_ocr=False)
    assert without_ocr["page_count"] == 2
    assert all(p["ocr_text"] == "" for p in without_ocr["pages"])


def test_image_orientation_is_applied_before_ocr(tmp_path, monkeypatch):
    source = tmp_path / "phone.jpg"
    image = Image.new("RGB", (40, 60), "white")
    exif = image.getexif()
    exif[274] = 6
    image.save(source, exif=exif)

    def read_frame(path, psm):
        with Image.open(path) as normalized:
            assert normalized.size == (60, 40)
            assert normalized.getexif().get(274, 1) == 1
        return "upright medical record"

    monkeypatch.setattr(extract, "ocr_layout_rows", read_frame)
    assert extract.extract_document(source)["pages"][0]["ocr_text"] == "upright medical record"


def test_scanned_page_with_a_logo_uses_whole_page_ocr(tmp_path, monkeypatch):
    from reportlab.pdfgen.canvas import Canvas

    source = tmp_path / "scan-with-logo.pdf"
    scan = tmp_path / "scan.png"
    logo = tmp_path / "logo.png"
    Image.new("RGB", (300, 400), "white").save(scan)
    Image.new("RGB", (100, 50), "red").save(logo)
    canvas = Canvas(str(source), pagesize=(300, 400))
    canvas.drawImage(str(scan), 0, 0, width=300, height=400)
    canvas.drawImage(str(logo), 0, 350, width=200, height=50)
    canvas.save()
    monkeypatch.setattr(extract, "ocr_pdf_image_regions", lambda *_: "clinic logo")
    monkeypatch.setattr(extract, "ocr_pdf_page", lambda *_: "the whole medical report")
    result = extract.extract_document(source)["pages"][0]
    assert result["ocr_text"] == "the whole medical report"
    assert result["extraction_method"] == "page_image_ocr"


def test_directory_detection_only_reads_the_promised_prefix(tmp_path, monkeypatch):
    source = tmp_path / "readiness.json"
    source.write_bytes(b'{"readiness_score": 80}')

    def forbid_whole_file_read(*_):
        pytest.fail("adapter detection must not load a multi-gigabyte export into memory")

    monkeypatch.setattr(Path, "read_bytes", forbid_whole_file_read)
    assert intake.detect_directory_adapter(tmp_path) == ("oura", "")


def test_human_edits_during_ocr_are_preserved_by_the_rescan(ledger, monkeypatch):
    settings, owner, patient = ledger
    imported = pipeline.ingest_file(settings, owner, patient, uploaded_source(settings))
    document_id = str(imported["document_id"])
    previous_analysis = pipeline.analyse_document

    def analyze_while_person_edits(path, run_ocr=True):
        with transaction(settings) as connection:
            connection.execute(
                """UPDATE documents SET title='Chosen during OCR', title_set_by='human',
                       clinical_type='consultation', classified_by='human' WHERE id=?""",
                (document_id,),
            )
        return previous_analysis(path, run_ocr=run_ocr)

    monkeypatch.setattr(pipeline, "analyse_document", analyze_while_person_edits)
    pipeline.reingest_document(settings, owner, document_id)
    with connect(settings) as connection:
        document = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        assert document["title"] == "Chosen during OCR"
        assert document["clinical_type"] == "consultation"


def test_compound_bundle_extracts_and_reviews_both_labs_and_vaccinations(ledger, monkeypatch):
    from test_immunizations import CARD_PAGE

    settings, owner, patient = ledger
    bundle = classification(clinical_type="compound_bundle")
    lab = classification()
    card = classification(clinical_type="immunization_record")
    pages = [page(1), {**page(2), **CARD_PAGE, "page_number": 2}]
    monkeypatch.setattr(
        pipeline, "analyse_document",
        lambda path, run_ocr=True: pipeline.Analysis(
            pages, "application/pdf", 2, "bundle-hash", bundle, [lab, card]
        ),
    )
    imported = pipeline.ingest_file(settings, owner, patient, uploaded_source(settings))
    assert imported["observations"] == 1
    assert imported["immunizations"] == 3
    for _ in range(2):
        pipeline.reingest_document(settings, owner, str(imported["document_id"]))
        with connect(settings) as connection:
            doses = connection.execute("SELECT * FROM immunizations").fetchall()
            assert len(doses) == 3
            assert all(row["page_number"] == 2 and row["verification_status"] == "extracted" for row in doses)
            reasons = " ".join(row[0] for row in connection.execute("SELECT reason FROM review_tasks WHERE state='open'"))
            assert "vaccination(s)" in reasons
            assert "observation(s)" in reasons


@pytest.mark.parametrize("run_ocr", [True, False])
def test_an_empty_ocr_reread_cannot_erase_existing_evidence(ledger, run_ocr):
    settings, owner, patient = ledger
    imported = pipeline.ingest_file(settings, owner, patient, uploaded_source(settings))
    document_id = str(imported["document_id"])
    with transaction(settings) as connection:
        connection.execute(
            "UPDATE document_pages SET ocr_text='previously readable medical results', image_count=1 WHERE document_id=?",
            (document_id,),
        )
        before = dict(connection.execute("SELECT * FROM observations").fetchone())
    with pytest.raises(ValueError, match="OCR"):
        pipeline.reingest_document(settings, owner, document_id, run_ocr=run_ocr)
    with connect(settings) as connection:
        assert dict(connection.execute("SELECT * FROM observations").fetchone()) == before
        assert connection.execute("SELECT ocr_text FROM document_pages").fetchone()[0] == "previously readable medical results"


def zip_bytes(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


@pytest.mark.parametrize("limit", ["MAX_ARCHIVE_ENTRIES", "MAX_ARCHIVE_EXPANDED_BYTES"])
def test_nested_archives_share_one_expansion_limit(tmp_path, monkeypatch, limit):
    inner = zip_bytes([("one.pdf", b"1" * 100), ("two.pdf", b"2" * 100)])
    source = tmp_path / "nested.zip"
    source.write_bytes(zip_bytes([("first.zip", inner), ("second.zip", inner)]))
    monkeypatch.setattr(intake, limit, 3 if limit.endswith("ENTRIES") else len(inner) * 2 + 100)
    with pytest.raises(ValueError):
        intake.expand_archive(source, tmp_path / "expanded")


def test_failed_archive_expansion_keeps_source_but_removes_partial_outputs(ledger, monkeypatch):
    settings, owner, patient = ledger
    inner = zip_bytes([("one.pdf", b"1"), ("two.pdf", b"2")])
    source = uploaded_source(settings, "nested.zip")
    source.write_bytes(zip_bytes([("first.zip", inner), ("second.zip", inner)]))
    monkeypatch.setattr(intake, "MAX_ARCHIVE_ENTRIES", 3)
    job_id = intake.enqueue(
        settings, owner_user_id=owner, patient_id=patient, batch_id="archive-limit",
        kind="archive", filename=source.name, source_path=source, start=False,
    )
    intake.drain_now(settings)
    assert source.is_file()
    assert list(source.parent.iterdir()) == [source]
    with connect(settings) as connection:
        job = connection.execute("SELECT * FROM upload_jobs WHERE id=?", (job_id,)).fetchone()
        assert (job["state"], job["detail_key"]) == ("failed", "intake.failed_too_big")


def test_visit_date_printed_on_a_photo_outranks_the_photo_filename():
    assert extract_date("Дата візиту: 23/02/2025", "photo_2026-08-07_20-31-12.jpg") == "2025-02-23"


@pytest.mark.parametrize("text,filename", [
    ("Дата візиту: 31/02/2025", "report.jpg"),
    ("", "report_2025-02-31.pdf"),
    ("", "report_2025_13_01.pdf"),
    ("Дата: 31.04.2025", "report.pdf"),
])
def test_impossible_calendar_dates_are_not_stored(text, filename):
    assert extract_date(text, filename) is None


def test_narrative_upload_is_visible_immediately_and_reread_reopens_review(ledger, monkeypatch):
    settings, owner, patient = ledger
    klass = classification(clinical_type="diagnostic_image", title="Chest imaging")
    monkeypatch.setattr(
        pipeline, "analyse_document",
        lambda path, run_ocr=True: pipeline.Analysis(
            [page(1, "chest radiograph images")], "application/pdf", 1, "chest", klass, [klass]
        ),
    )
    monkeypatch.setattr(pipeline, "parse_pages", lambda *_, **__: [])
    imported = pipeline.ingest_file(settings, owner, patient, uploaded_source(settings))
    with transaction(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM clinical_findings").fetchone()[0] == 1
        connection.execute("UPDATE review_tasks SET state='resolved', resolution='verified'")
    pipeline.reingest_document(settings, owner, str(imported["document_id"]))
    with connect(settings) as connection:
        reason = connection.execute("SELECT reason FROM review_tasks WHERE state='open'").fetchone()
        assert reason is not None
        assert "Review the narrative or visual findings" in reason[0]


def test_verified_narrative_finding_survives_report_rebuilding(ledger, monkeypatch):
    settings, owner, patient = ledger
    klass = classification(clinical_type="diagnostic_image", title="Chest imaging")
    monkeypatch.setattr(
        pipeline, "analyse_document",
        lambda path, run_ocr=True: pipeline.Analysis(
            [page(1, "chest radiograph images")], "application/pdf", 1, "chest", klass, [klass]
        ),
    )
    monkeypatch.setattr(pipeline, "parse_pages", lambda *_, **__: [])
    imported = pipeline.ingest_file(settings, owner, patient, uploaded_source(settings))
    with transaction(settings) as connection:
        pipeline.sync_clinical_findings(connection)
        connection.execute("UPDATE clinical_findings SET verification_status='verified'")
        previous = dict(connection.execute("SELECT * FROM clinical_findings").fetchone())
    pipeline.reingest_document(settings, owner, str(imported["document_id"]))
    with connect(settings) as connection:
        current = dict(connection.execute("SELECT * FROM clinical_findings").fetchone())
        assert current["verification_status"] == "verified"
        assert current["id"] == previous["id"]
        assert current["created_at"] == previous["created_at"]
        assert connection.execute("SELECT id FROM reports WHERE id=?", (current["report_id"],)).fetchone()


def test_whole_page_ocr_does_not_mistake_the_only_logo_for_the_whole_page(tmp_path, monkeypatch):
    from reportlab.pdfgen.canvas import Canvas

    source = tmp_path / "vector-report.pdf"
    logo = tmp_path / "logo.png"
    Image.new("RGB", (120, 40), "red").save(logo)
    canvas = Canvas(str(source), pagesize=(300, 400))
    canvas.drawImage(str(logo), 10, 350, width=120, height=40)
    canvas.drawString(20, 100, "Clinical conclusion")
    canvas.save()

    def read_rendered_page(path, psm):
        with Image.open(path) as image:
            assert image.width / image.height == pytest.approx(300 / 400)
        return "Clinical conclusion"

    monkeypatch.setattr(extract, "ocr_layout_rows", read_rendered_page)
    assert extract.ocr_pdf_page(source, 0) == "Clinical conclusion"


@pytest.mark.parametrize("nested", [False, True])
def test_archive_collisions_are_reported_without_silently_losing_a_report(ledger, nested):
    settings, owner, patient = ledger
    source = uploaded_source(settings, "ambiguous.zip")
    if nested:
        entries = [("reports/report.pdf", b"first report"), ("reports.zip", zip_bytes([("report.pdf", b"second report")]))]
        payload = zip_bytes(entries)
    else:
        with pytest.warns(UserWarning, match="Duplicate name"):
            payload = zip_bytes([("report.pdf", b"first report"), ("report.pdf", b"second report")])
    source.write_bytes(payload)
    intake.enqueue(
        settings, owner_user_id=owner, patient_id=patient, batch_id="collision",
        kind="archive", filename=source.name, source_path=source, start=False,
    )
    intake.drain_now(settings)
    assert source.read_bytes() == payload
    assert list(source.parent.iterdir()) == [source]
    with connect(settings) as connection:
        job = connection.execute("SELECT * FROM upload_jobs").fetchone()
        assert (job["state"], job["detail_key"]) == ("failed", "intake.failed_unreadable")
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
