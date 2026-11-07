"""Re-reading a document that is already in the record.

The reason this exists at all: the software keeps learning. A file imported in
March was read by March's parser, and nothing re-reads it when April's parser
learns the layout - re-uploading the same file only produces a duplicate.

The reason it is dangerous: a re-read regenerates observations, and some of
those observations are no longer the parser's. A person verified them, corrected
them, or set them aside. Every test here pins one way that judgement could be
silently thrown away by a better parser, which would be a worse outcome than
never re-reading at all.

Parsing itself is covered by `test_parsers.py`; what is stubbed here is the
"old parser" and the "new parser", because the contract under test is which
rows survive the swap.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from pathlib import Path

import pytest

from anamna.db import connect
from anamna.ingest import parsers, pipeline
from anamna.ingest.classifier import Classification
from anamna.ingest.parsers import ParsedObservation
from anamna.ingest.pipeline import file_sha256

from test_web_panels import build as _built_record


def build(tmp_path: Path):
    """The shared fixture, with the document's checksum made true.

    The record fixture writes a placeholder into `documents.sha256`; a rescan
    now refuses to re-read a file whose bytes are not the ones that were
    imported, and a placeholder is indistinguishable from a replaced file.
    """
    settings, user_id, client = _built_record(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE documents SET sha256=? WHERE id='doc-1'",
            (file_sha256(settings.source_dir / "report.pdf"),),
        )
        connection.commit()
    return settings, user_id, client


def csrf_for(settings, user_id: str) -> str:
    with connect(settings) as connection:
        return connection.execute(
            "SELECT csrf_token FROM sessions WHERE user_id=?", (user_id,)
        ).fetchone()[0]


def classification(**overrides) -> Classification:
    base = dict(
        vendor="Test Lab", website=None, clinical_type="laboratory",
        title="Re-read report", report_date="2025-02-13", order_identifier=None,
        status="final", extraction_strategy="native_text", confidence=0.9, notes=None,
    )
    return Classification(**{**base, **overrides})


def page(number: int, text: str = "text") -> dict[str, object]:
    return {
        "page_number": number, "native_text": text, "ocr_text": None,
        "native_text_sha256": f"sha-{number}", "extraction_method": "native_pdf_text",
        "native_char_count": len(text), "image_count": 0,
    }


def observation(name: str, value: float, page_number: int = 1) -> ParsedObservation:
    return ParsedObservation(
        raw_name=name, value_numeric=value, value_text=None, comparator=None,
        unit_raw="mmol/L", reference_text="0 - 3.0", reference_low=0.0, reference_high=3.0,
        page_number=page_number, evidence_text=f"{name} {value}", confidence=0.95,
        extraction_method="native_pdf_text_parser",
    )


def owned_rows(settings) -> list[ParsedObservation]:
    """What the record already holds for doc-1, as a parser would read it."""
    with connect(settings) as connection:
        return [
            ParsedObservation(
                raw_name=row["raw_name"], value_numeric=row["value_numeric"], value_text=row["value_text"],
                comparator=row["comparator"], unit_raw=row["unit_raw"],
                reference_text=row["vendor_reference_text"], reference_low=row["vendor_reference_low"],
                reference_high=row["vendor_reference_high"], page_number=row["page_number"],
                evidence_text=row["evidence_text"], confidence=0.95,
                observed_at=row["observed_at"],
            )
            for row in connection.execute(
                "SELECT * FROM observations WHERE document_id='doc-1' ORDER BY page_number, rowid"
            )
        ]


@pytest.fixture
def rescanner(monkeypatch):
    """Stand in for today's extractor and parser.

    `pages` and `found` are what the *new* read produces; the record already
    holds what the old one did.
    """

    def install(found, pages=None, klass=None, per_page=None):
        page_list = pages or [page(1)]
        resolved = klass or classification()
        monkeypatch.setattr(
            pipeline, "analyse_document",
            lambda path, run_ocr=True: pipeline.Analysis(
                pages=page_list, mime_type="application/pdf", page_count=len(page_list),
                content_hash="content-hash", classification=resolved,
                per_page=per_page or [resolved] * len(page_list),
            ),
        )
        monkeypatch.setattr(
            pipeline, "parse_pages",
            lambda classification_, per_page_, pages_, **_: [
                (item, per_page_[item.page_number - 1]) for item in found
            ],
        )

    return install


def states(settings, user_id: str) -> dict[str, tuple[str, float | None]]:
    with connect(settings) as connection:
        return {
            str(row["raw_name"]): (str(row["verification_status"]), row["value_numeric"])
            for row in connection.execute(
                "SELECT raw_name, verification_status, value_numeric FROM observations WHERE document_id='doc-1'"
            )
        }


def test_a_checked_value_outranks_a_better_parse(tmp_path: Path, rescanner):
    """The whole point. A person looked at this number; the parser did not."""
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET verification_status='verified' WHERE raw_name='LDL cholesterol'"
        )
        connection.execute(
            "UPDATE observations SET verification_status='corrected', value_numeric=1.51 WHERE raw_name='HDL cholesterol'"
        )
        connection.execute(
            "UPDATE observations SET verification_status='rejected' WHERE raw_name='Creatinine'"
        )
        connection.commit()

    # The new parser reads all three again, and differently. Pages match the
    # fixture's: a preserved row is matched by page *and* printed label, so a
    # value that moved page is a different measurement, not the same one.
    rescanner(
        [
            observation("LDL cholesterol", 9.99, page_number=1),
            observation("HDL cholesterol", 9.99, page_number=2),
            observation("Creatinine", 9.99, page_number=3),
            observation("Ferritin", 42.0, page_number=1),
        ],
        pages=[page(number) for number in (1, 2, 3)],
    )
    result = pipeline.reingest_document(settings, user_id, "doc-1")

    after = states(settings, user_id)
    assert after["LDL cholesterol"] == ("verified", 4.42)
    assert after["HDL cholesterol"] == ("corrected", 1.51)
    assert after["Creatinine"] == ("rejected", 88.0)
    # Only the value nobody had ruled on is new, and it arrives provisional.
    assert after["Ferritin"] == ("extracted", 42.0)
    assert result["preserved"] == 3
    assert result["observations"] == 1


def test_a_reread_does_not_duplicate_a_value_a_person_already_owns(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET verification_status='verified' WHERE raw_name='LDL cholesterol'"
        )
        connection.commit()
    rescanner([observation("LDL cholesterol", 4.42)])
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM observations WHERE document_id='doc-1' AND raw_name='LDL cholesterol'"
        ).fetchone()[0] == 1


def test_values_nobody_ruled_on_are_replaced_wholesale(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    rescanner([observation("Ferritin", 42.0)])
    result = pipeline.reingest_document(settings, user_id, "doc-1")
    assert set(states(settings, user_id)) == {"Ferritin"}
    assert result["replaced"] == 8 and result["preserved"] == 0


def test_the_document_keeps_its_identity_and_refreshes_its_reading(tmp_path: Path, rescanner):
    """A re-read is not a re-import: every link that points here still points here."""
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        before = dict(connection.execute("SELECT * FROM documents WHERE id='doc-1'").fetchone())
    rescanner(
        [observation("Ferritin", 42.0)],
        klass=classification(title="Recognised at last", clinical_type="microbiology", vendor="Better Lab"),
    )
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        after = dict(connection.execute("SELECT * FROM documents WHERE id='doc-1'").fetchone())
    for stable in ("id", "sha256", "imported_at", "original_filename", "source_path", "owner_user_id"):
        assert after[stable] == before[stable], stable
    assert after["title"] == "Recognised at last"
    assert after["clinical_type"] == "microbiology"
    assert after["vendor_id"] != before["vendor_id"]


def test_a_title_a_person_chose_survives_the_reread(tmp_path: Path, rescanner):
    """Adopting a suggested title is a ruling like a human classification:
    the classifier's next guess must not quietly replace it."""
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE documents SET title='Lipid panel, spring check-up', title_set_by='human' WHERE id='doc-1'"
        )
        connection.commit()
    rescanner(
        [observation("Ferritin", 42.0)],
        klass=classification(title="2025-02-13__test-lab__laboratory__result-1"),
    )
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT title FROM documents WHERE id='doc-1'"
        ).fetchone()[0] == "Lipid panel, spring check-up"


def test_a_page_that_was_signed_off_stays_signed_off(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO document_pages(document_id, page_number, extraction_method, review_status)
               VALUES ('doc-1', 1, 'native_pdf_text', 'verified'),
                      ('doc-1', 2, 'native_pdf_text', 'not_reviewed')"""
        )
        connection.commit()
    rescanner([observation("Ferritin", 42.0)], pages=[page(1), page(2)])
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        assert dict(
            connection.execute(
                "SELECT page_number, review_status FROM document_pages WHERE document_id='doc-1'"
            ).fetchall()
        ) == {1: "verified", 2: "not_reviewed"}


def test_preserved_values_follow_their_page_into_the_new_report(tmp_path: Path, rescanner):
    """A document that now splits into two reports must not leave half its
    checked values filed under a report that no longer describes them."""
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO reports(id, owner_user_id, patient_id, document_id, vendor_id, title,
                                   clinical_type, report_date, start_page, end_page, status, created_at)
               SELECT 'old-report', owner_user_id, patient_id, id, vendor_id, 'Old grouping',
                      'laboratory', '2025-02-13', 1, 2, 'final', imported_at
               FROM documents WHERE id='doc-1'"""
        )
        connection.execute(
            "UPDATE observations SET report_id='old-report', verification_status='verified' WHERE raw_name='LDL cholesterol'"
        )
        connection.execute("UPDATE observations SET page_number=2 WHERE raw_name='LDL cholesterol'")
        connection.commit()

    first = classification(report_date="2025-02-13")
    second = classification(report_date="2025-09-01", title="Second visit")
    rescanner(
        [observation("Ferritin", 42.0, page_number=1)],
        pages=[page(1), page(2)],
        klass=first,
        per_page=[first, second],
    )
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        reports = {
            str(row["id"]): (row["start_page"], row["end_page"])
            for row in connection.execute("SELECT * FROM reports WHERE document_id='doc-1'")
        }
        moved = connection.execute(
            "SELECT report_id, page_number FROM observations WHERE raw_name='LDL cholesterol'"
        ).fetchone()
    assert "old-report" not in reports
    assert len(reports) == 2
    assert reports[str(moved["report_id"])] == (2, 2)


def test_new_values_open_a_review_task_and_a_quiet_reread_does_not(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified'")
        connection.execute("DELETE FROM review_tasks")
        connection.commit()

    # Every page the fixture's values were read from, because a re-read that
    # loses a page is not a quiet one: it is reported, and that is its own test.
    same_pages = [page(number) for number in range(1, 9)]
    # The new parse reads every checked value again, exactly as checked: no
    # news.  (A checked value it stopped reading *is* news; see
    # test_ingest_reread_pairing.py.)
    owned = owned_rows(settings)
    rescanner(owned, pages=same_pages)
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM review_tasks").fetchone()[0] == 0

    rescanner([*owned, observation("Ferritin", 42.0)], pages=same_pages)
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        task = connection.execute("SELECT * FROM review_tasks").fetchone()
    assert task["entity_id"] == "doc-1" and task["state"] == "open"
    assert "1 observation" in str(task["reason"])


def test_a_reread_that_changes_nothing_asks_nobody_to_check_anything(
    tmp_path: Path, rescanner
):
    """The one that reached the live record.

    Every re-read replaces every unverified row, so counting what it inserted
    counts the whole document.  Re-reading 85 stored files that way produced 61
    review tasks between them, each asking a person to verify every value in a
    file -- 1307 in total, of which exactly zero had changed.  A task nobody
    needs to act on is worse than no task: it is the reason the real ones stop
    being read.
    """
    settings, user_id, _ = build(tmp_path)
    found = [observation("Ferritin", 42.0), observation("LDL cholesterol", 4.42)]

    # The first pass genuinely changes the document, so it says so.  Ferritin
    # is new; the record already held LDL cholesterol at 4.42, and a re-read
    # producing the same reading again is not a discovery -- which is the whole
    # distinction, made here against rows the fixture wrote rather than rows
    # this test did.
    rescanner(found)
    first = pipeline.reingest_document(settings, user_id, "doc-1")
    assert first["observations"] == 2
    assert first["appeared"] == 1 and first["vanished"] == 7

    with connect(settings) as connection:
        connection.execute("DELETE FROM review_tasks")
        connection.commit()

    # The second reads the same file with the same parser and finds the same
    # two values.  Two rows were still written -- `added` is 2 -- and that is
    # precisely the number that must not reach the person.
    rescanner(found)
    second = pipeline.reingest_document(settings, user_id, "doc-1")
    assert second["observations"] == 2
    assert second["appeared"] == 0 and second["vanished"] == 0
    # The document still holds two values nobody has checked, so it must not
    # fall off the queue -- but what it is asked for is a first reading of two
    # values, not a re-reading of a discovery that never happened.
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM review_tasks").fetchone()[0] == 1
    reason = reason_for(settings, "doc-1")
    assert "did not produce" not in reason
    assert reason.startswith("Verify 2 extracted observation(s)")


def test_a_value_the_reread_stopped_producing_is_reported(tmp_path: Path, rescanner):
    """The direction nothing reported, and the one that loses data.

    A parser change that stops recognising a layout deletes the old rows and
    writes no replacement.  Nothing raised a task for it, because a task was
    raised only when rows were *added* -- so the document quietly held one
    fewer result than the week before, and only the printed page could say so.
    """
    settings, user_id, _ = build(tmp_path)
    rescanner([observation("Ferritin", 42.0), observation("LDL cholesterol", 4.42)])
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        connection.execute("DELETE FROM review_tasks")
        connection.commit()

    rescanner([observation("Ferritin", 42.0)])
    result = pipeline.reingest_document(settings, user_id, "doc-1")
    assert result["vanished"] == 1 and result["appeared"] == 0
    assert "are not in this one" in reason_for(settings, "doc-1")

    # A changed *value* is both: the old reading is gone and a new one is here.
    rescanner([observation("Ferritin", 43.5)])
    changed = pipeline.reingest_document(settings, user_id, "doc-1")
    assert changed["appeared"] == 1 and changed["vanished"] == 1


def test_the_audit_trail_records_what_the_reread_changed(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET verification_status='verified' WHERE raw_name='LDL cholesterol'"
        )
        connection.commit()
    rescanner([observation("Ferritin", 42.0)])
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        event = connection.execute(
            "SELECT * FROM audit_events WHERE action='rescan' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    import json

    details = json.loads(str(event["details_json"]))
    assert details["observations_preserved"] == 1
    assert details["observations_replaced"] == 7
    assert details["observations_added"] == 1
    assert details["parser_version"]


def test_a_missing_source_file_fails_loudly_and_changes_nothing(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    (settings.source_dir / "report.pdf").unlink()
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET source_path='/nowhere/report.pdf' WHERE id='doc-1'")
        connection.commit()
    rescanner([observation("Ferritin", 42.0)])
    with pytest.raises(FileNotFoundError):
        pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM observations WHERE document_id='doc-1'"
        ).fetchone()[0] == 8


def test_another_owners_document_cannot_be_rescanned(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with pytest.raises(LookupError):
        pipeline.reingest_document(settings, "somebody-else", "doc-1")


def test_a_replaced_source_file_is_refused_rather_than_read(tmp_path: Path, rescanner):
    """A re-read keeps the document's id, its links and its SHA-256.

    All three are only honest while the file on disk is still the file that was
    imported. Reading different bytes under the old identity leaves the record
    asserting a checksum for content nobody has ever seen - and that checksum is
    what duplicate detection matches on.
    """
    settings, user_id, _ = build(tmp_path)
    (settings.source_dir / "report.pdf").write_text("a different document", encoding="utf-8")
    rescanner([observation("Ferritin", 42.0)])
    with pytest.raises(ValueError):
        pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM observations WHERE document_id='doc-1'"
        ).fetchone()[0] == 8


def test_a_reread_that_finds_no_pages_fails_before_it_deletes_anything(
    tmp_path: Path, monkeypatch
):
    """An unreadable file is a failure, not an empty document.

    Committing this emptied the document: every page row gone, every report
    gone, and every checked observation filed under no report at all - a
    document that reads as though the scan had always been blank.
    """
    settings, user_id, _ = build(tmp_path)
    monkeypatch.setattr(
        pipeline, "analyse_document",
        lambda path, run_ocr=True: pipeline.Analysis(
            pages=[], mime_type="application/pdf", page_count=0, content_hash="empty",
            classification=classification(), per_page=[],
        ),
    )
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO document_pages(document_id, page_number, extraction_method, review_status)
               VALUES ('doc-1', 1, 'native_pdf_text', 'verified')"""
        )
        connection.commit()

    with pytest.raises(ValueError):
        pipeline.reingest_document(settings, user_id, "doc-1")

    with connect(settings) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM observations WHERE document_id='doc-1'"
        ).fetchone()[0] == 8
        assert connection.execute(
            "SELECT COUNT(*) FROM document_pages WHERE document_id='doc-1'"
        ).fetchone()[0] == 1


def test_a_checked_value_whose_page_is_gone_is_declared_not_guessed(tmp_path: Path, rescanner):
    """The new parse is shorter than the old one, so one page has no successor.

    Filing that value under whichever report came first would put a measurement
    a person checked under a heading that never printed it, while its own
    `page_number` still names a page the document no longer has. Nobody would
    ever learn that had happened.
    """
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET verification_status='verified' WHERE raw_name='Creatinine'"
        )
        connection.execute("UPDATE observations SET page_number=3 WHERE raw_name='Creatinine'")
        connection.commit()

    rescanner([observation("Ferritin", 42.0, page_number=1)], pages=[page(1)])
    result = pipeline.reingest_document(settings, user_id, "doc-1")

    assert result["unfiled"] == 1
    with connect(settings) as connection:
        orphan = connection.execute(
            "SELECT report_id, page_number, verification_status FROM observations WHERE raw_name='Creatinine'"
        ).fetchone()
        task = connection.execute(
            "SELECT reason FROM review_tasks WHERE entity_id='doc-1' AND state='open'"
        ).fetchone()
    # The value and the judgement on it are untouched; only the grouping is
    # admitted to be unknown.
    assert (orphan["report_id"], orphan["page_number"]) == (None, 3)
    assert orphan["verification_status"] == "verified"
    assert "1 checked observation(s) could not be re-filed" in str(task["reason"])


def test_a_reread_keeps_the_narrative_findings_it_deletes_on_the_way(tmp_path: Path, rescanner):
    """`clinical_findings.report_id` cascades from `reports`.

    Rescanning drops and rebuilds this document's reports, which took every
    finding on it with them - an ultrasound, an MRI or a consultation vanished
    from its health area until the next application start, which is the only
    other place these are rebuilt.
    """
    settings, user_id, _ = build(tmp_path)
    imaging = classification(clinical_type="diagnostic_image", title="Chest imaging")
    with connect(settings) as connection:
        # An imaging record has no values; the fixture's lab rows would make
        # the empty re-read below a refused one (a document that had values
        # and now reads none), which is its own test.
        connection.execute("DELETE FROM observations WHERE document_id='doc-1'")
        connection.execute("UPDATE documents SET clinical_type='diagnostic_image' WHERE id='doc-1'")
        connection.execute(
            """INSERT INTO document_pages(document_id, page_number, native_text, extraction_method, review_status)
               VALUES ('doc-1', 1, 'chest radiograph images', 'native_pdf_text', 'not_reviewed')"""
        )
        connection.execute(
            """INSERT INTO reports(id, owner_user_id, patient_id, document_id, vendor_id, title,
                                   clinical_type, report_date, start_page, end_page, status, created_at)
               SELECT 'old-report', owner_user_id, patient_id, id, vendor_id, 'Chest imaging',
                      'diagnostic_image', '2025-02-13', 1, 1, 'final', imported_at
               FROM documents WHERE id='doc-1'"""
        )
        from anamna.health import sync_clinical_findings

        sync_clinical_findings(connection)
        connection.commit()
        before = connection.execute(
            "SELECT COUNT(*) FROM clinical_findings WHERE document_id='doc-1'"
        ).fetchone()[0]
    assert before, "the fixture has to produce a finding for this to prove anything"

    rescanner([], pages=[page(1, "chest radiograph images")], klass=imaging, per_page=[imaging])
    pipeline.reingest_document(settings, user_id, "doc-1")

    with connect(settings) as connection:
        after = connection.execute(
            """SELECT f.id, f.report_id, r.id live_report FROM clinical_findings f
               LEFT JOIN reports r ON r.id=f.report_id WHERE f.document_id='doc-1'"""
        ).fetchall()
    assert len(after) == before
    # Re-filed onto the report the rescan built, not left pointing at a
    # report that no longer exists.
    assert all(row["report_id"] and row["live_report"] for row in after)


def test_a_reread_closes_the_review_tasks_it_supersedes(tmp_path: Path, rescanner):
    """Every rescan used to leave its predecessor's task open.

    Six rescans, six open tasks on one document, each describing a set of
    observations that no longer exists - and the person is asked to check all
    six.
    """
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO review_tasks(id, owner_user_id, entity_type, entity_id, reason, state, created_at)
               VALUES ('task-2', ?, 'document', 'doc-1', 'An earlier rescan said something else.',
                       'open', '2025-01-01T00:00:00Z')""",
            (user_id,),
        )
        connection.commit()

    rescanner([observation("Ferritin", 42.0)])
    pipeline.reingest_document(settings, user_id, "doc-1")

    with connect(settings) as connection:
        tasks = connection.execute(
            "SELECT id, state, resolution, resolved_at, reason FROM review_tasks WHERE entity_id='doc-1'"
        ).fetchall()
    open_tasks = [row for row in tasks if row["state"] == "open"]
    superseded = [row for row in tasks if row["state"] == "resolved"]
    assert len(open_tasks) == 1
    assert "1 observation(s)" in str(open_tasks[0]["reason"])
    # Superseded, never verified: nobody looked at anything, so no reviewer is
    # recorded as having decided this.
    assert {row["id"] for row in superseded} == {"task-1", "task-2"}
    assert all(row["resolution"] == "superseded" and row["resolved_at"] for row in superseded)


def test_a_quiet_reread_leaves_the_open_task_it_has_no_replacement_for(tmp_path: Path, rescanner):
    """The document still holds values nobody has checked.

    Closing its last task because a rescan happened to add nothing would take
    the document off the review queue with its values still unverified.
    """
    settings, user_id, _ = build(tmp_path)
    # A re-read that reads none of the eight stored values is refused outright
    # (nothing is deleted, nothing is closed); one that reads them all again
    # unchanged is the quiet case.
    rescanner([])
    with pytest.raises(pipeline.RereadRefused):
        pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE raw_name='LDL cholesterol'")
        connection.commit()
    rescanner(owned_rows(settings), pages=[page(number) for number in range(1, 9)])
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM review_tasks WHERE entity_id='doc-1' AND state='open'"
        ).fetchone()[0] == 1


def test_the_startup_repair_never_undoes_a_persons_remap(tmp_path: Path):
    """`repair_observation_semantics` runs on every application start.

    It re-resolves each observation's concept from the printed label, which is
    the whole point for a parser-derived row and precisely wrong for one a
    person refiled by hand: the remap survived until the next restart and then
    silently reverted, with the correction still sitting in the audit trail.
    """
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            """UPDATE observations SET concept_id='creatinine', verification_status='corrected',
                   extraction_method='human_corrected' WHERE raw_name='LDL cholesterol'"""
        )
        # A row the parser owns, deliberately mis-filed, to prove the repair
        # still does its job on everything else.
        connection.execute(
            "UPDATE observations SET concept_id='creatinine' WHERE raw_name='HDL cholesterol'"
        )
        connection.commit()

    with connect(settings) as connection:
        pipeline.repair_observation_semantics(connection)
        connection.commit()
        after = dict(
            connection.execute(
                "SELECT raw_name, concept_id FROM observations WHERE raw_name IN ('LDL cholesterol','HDL cholesterol')"
            ).fetchall()
        )
    assert after["LDL cholesterol"] == "creatinine"
    assert after["HDL cholesterol"] != "creatinine"


def test_the_startup_repair_does_not_claim_to_have_parsed_anything(tmp_path: Path):
    """`parser_version` says which parser read the printed page.

    The repair re-resolves a stored row against today's catalogue and re-reads
    nothing, so stamping the current version on every row it touched - on every
    application start - turned the column into "last written by anything" and
    left no way to ask which documents an older parser had read.
    """
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET concept_id='creatinine', parser_version='2019.01-1' WHERE raw_name='HDL cholesterol'"
        )
        connection.commit()

    with connect(settings) as connection:
        assert pipeline.repair_observation_semantics(connection)
        connection.commit()
        row = connection.execute(
            "SELECT concept_id, parser_version FROM observations WHERE raw_name='HDL cholesterol'"
        ).fetchone()
    # The repair did its job, and said nothing about who parsed the page.
    assert row["concept_id"] != "creatinine"
    assert row["parser_version"] == "2019.01-1"


# --- the first read, which a re-read has to keep true ------------------------


def ingest(settings, user_id: str, tmp_path: Path, klass: Classification, found=()):
    """One file through `ingest_file`, with the parse under the test's control."""
    source = settings.source_dir / f"{klass.clinical_type}-{len(found)}.pdf"
    source.write_text(klass.title, encoding="utf-8")
    return pipeline.ingest_file(settings, user_id, f"patient-{user_id}", source)


def reason_for(settings, document_id: str) -> str:
    with connect(settings) as connection:
        return str(
            connection.execute(
                "SELECT reason FROM review_tasks WHERE entity_id=?", (document_id,)
            ).fetchone()["reason"]
        )


def test_a_report_with_nothing_to_extract_reads_differently_from_a_failed_extraction(
    tmp_path: Path, rescanner
):
    """One sentence used to cover both, and they call for opposite actions.

    An ultrasound has no numbers in it: that document is complete as it stands.
    A laboratory report with no values is a parser that missed a whole panel,
    and the pages need looking at.
    """
    settings, user_id, _ = build(tmp_path)
    narrative = classification(clinical_type="ultrasound", title="Abdominal ultrasound")
    rescanner([], klass=narrative, per_page=[narrative])
    quiet = ingest(settings, user_id, tmp_path, narrative)
    assert "Review the narrative or visual report" in reason_for(settings, str(quiet["document_id"]))

    laboratory = classification(title="Blood panel")
    rescanner([], klass=laboratory, per_page=[laboratory])
    missed = ingest(settings, user_id, tmp_path, laboratory)
    assert "Extraction found no values" in reason_for(settings, str(missed["document_id"]))


def test_the_parseable_types_are_the_ones_the_parser_dispatches_on():
    """`parse_document` gates on the set the pipeline reads, not a copy of it.

    The distinction the review reason draws -- "this kind of report has no
    numbers" versus "the parser read it and found none" -- is worth nothing if
    the parser can grow a kind the pipeline never hears about. One set, checked
    here against the dispatch it guards.
    """
    assert pipeline.PARSED_CLINICAL_TYPES is parsers.PARSED_CLINICAL_TYPES
    source = inspect.getsource(parsers.parse_document)
    assert "clinical_type not in PARSED_CLINICAL_TYPES" in source
    # The two that dispatch to their own parser sit behind the same gate, so a
    # blood-pressure or ECG report must be in the set or it stops being read.
    dispatched = set(re.findall(r'clinical_type == "([a-z_]+)"', source))
    assert dispatched <= set(parsers.PARSED_CLINICAL_TYPES)
    assert {"laboratory", "blood_pressure", "electrocardiogram"} <= set(
        parsers.PARSED_CLINICAL_TYPES
    )


def test_every_page_leaves_a_line_saying_what_was_read_from_it(tmp_path: Path, caplog):
    """A page printing forty results that yields three is otherwise invisible.

    No error, no review task: the document simply reads as though the
    laboratory ran fewer tests. Whether the page carried a result header is
    what separates "nothing here to read" from "read badly".
    """
    lab = classification()
    printed = page(2, "Показник Результат\nГемоглобін 145 г/л 130 - 160")
    with caplog.at_level(logging.INFO, logger="anamna.ingest.pipeline"):
        pipeline.parse_pages(lab, [lab, lab], [page(1, "a covering letter"), printed])
    lines = [record.getMessage() for record in caplog.records if record.message.startswith("parse:")]
    assert len(lines) == 2
    assert "page 1" in lines[0] and "result_header=False" in lines[0] and "rows=0" in lines[0]
    assert "page 2" in lines[1] and "result_header=True" in lines[1]


def test_one_unreadable_file_does_not_end_the_scan(tmp_path: Path, monkeypatch):
    """`ingest_directory` is the CLI's whole import.

    A single corrupt scan used to raise out of it, so everything alphabetically
    after that file was never read and the only sign of it was a traceback
    where the summary should have been.
    """
    settings, user_id, _ = build(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for name in ("a-broken.pdf", "b-fine.pdf"):
        (corpus / name).write_text(name, encoding="utf-8")
    lab = classification()
    monkeypatch.setattr(pipeline, "parse_pages", lambda *_a, **_k: [])

    def explode_on_the_first(path, run_ocr=True):
        if "broken" in path.name:
            raise RuntimeError("unreadable pdf")
        return pipeline.Analysis(
            pages=[page(1)], mime_type="application/pdf", page_count=1,
            content_hash=path.name, classification=lab, per_page=[lab],
        )

    monkeypatch.setattr(pipeline, "analyse_document", explode_on_the_first)
    results = pipeline.ingest_directory(settings, user_id, f"patient-{user_id}", corpus)

    assert [(item["filename"], item["action"]) for item in results] == [
        ("a-broken.pdf", "failed"),
        ("b-fine.pdf", "ingested"),
    ]
    # The failure is reported without the exception's own text, which carries
    # absolute paths and sometimes the patient's filenames.
    assert results[0]["error"] == "RuntimeError"
    assert json.dumps(results)


# --- the route in front of it -----------------------------------------------


def test_the_button_queues_the_reread_rather_than_blocking_the_page(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    response = client.post(
        "/documents/doc-1/rescan",
        data={"csrf_token": csrf_for(settings, user_id)},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/documents/doc-1?rescan=queued"
    with connect(settings) as connection:
        job = connection.execute("SELECT * FROM upload_jobs WHERE kind='rescan'").fetchone()
    assert (job["document_id"], job["owner_user_id"]) == ("doc-1", user_id)


def test_a_reread_needs_the_session_token_and_the_document_to_be_yours(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    assert client.post("/documents/doc-1/rescan", data={"csrf_token": "wrong"}).status_code == 403
    assert client.post(
        "/documents/doc-does-not-exist/rescan",
        data={"csrf_token": csrf_for(settings, user_id)},
    ).status_code == 404
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM upload_jobs").fetchone()[0] == 0


def patient_of(settings) -> str:
    with connect(settings) as connection:
        return str(connection.execute("SELECT id FROM patients LIMIT 1").fetchone()[0])


def stale_panel(client) -> str:
    """The "files read by an older parser" panel, or "" when it is not shown."""
    body = client.get("/documents").text
    if "an-stale-rescan" not in body:
        return ""
    return body[body.index("an-stale-rescan"):]


def test_a_value_a_person_owns_does_not_hold_the_document_on_an_older_parser(
    tmp_path: Path,
):
    """The count that could not be moved.

    Staleness asks which files a re-read would improve, and it asked it of every
    stored row.  Two kinds of row are never re-parsed: a value somebody typed in
    carries `parser_version='human'`, and one somebody verified keeps whichever
    version read it, because both outrank the parser.  Either one marked its
    document as behind permanently -- the panel offered to fix it, the re-read
    ran, preserved them exactly as it promises to, and the number did not move.
    """
    settings, _, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET parser_version=? WHERE document_id='doc-1'",
            (parsers.PARSER_VERSION,),
        )
        connection.commit()
    assert stale_panel(client) == "", "the fixture has to start current for this to prove anything"

    for status, version in (("verified", "2019.01-1"), ("corrected", "human")):
        with connect(settings) as connection:
            connection.execute(
                "UPDATE observations SET verification_status=?, parser_version=? "
                "WHERE raw_name='LDL cholesterol'",
                (status, version),
            )
            connection.commit()
        assert stale_panel(client) == "", status

    # A row the parser does own is still counted: that is the whole feature.
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET parser_version='2019.01-1' WHERE raw_name='HDL cholesterol'"
        )
        connection.commit()
    assert "Files read by an older parser" in stale_panel(client)


def test_the_queued_reread_links_to_the_page_that_reports_it(tmp_path: Path):
    """"Watch the processing area for progress" named a page nothing linked to.

    Re-reading 62 files said "queued" and then never mentioned itself again.
    Every one of them failed, the processing queue said so in red, and no route
    led there from the button that had filled it.
    """
    settings, user_id, client = build(tmp_path)
    token = csrf_for(settings, user_id)

    bulk = client.post("/documents/rescan-stale", data={"csrf_token": token}).text
    assert 'href="/upload#processing"' in bulk
    assert "Open the processing area" in bulk

    one = client.post("/documents/doc-1/rescan", data={"csrf_token": token}).text
    assert 'href="/upload#processing"' in one


def test_a_reread_that_failed_says_so_beside_the_count_it_did_not_move(tmp_path: Path):
    """Otherwise the panel invites the same fruitless press forever.

    A stored file that is no longer where the record expects it fails every
    re-read, and no amount of pressing changes that -- but the only page saying
    so was the one nothing linked to.
    """
    settings, user_id, client = build(tmp_path)
    assert "re-read(s) failed" not in stale_panel(client)

    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO upload_jobs(id, owner_user_id, patient_id, batch_id, kind, filename,
                                       state, detail_key, document_id, created_at)
               VALUES ('job-x', ?, ?, 'batch-x', 'rescan', 'report.pdf',
                       'failed', 'intake.failed_missing', 'doc-1', '2026-01-01T00:00:00Z')""",
            (user_id, patient_of(settings)),
        )
        connection.commit()

    panel = stale_panel(client)
    assert "The last re-read of 1 file failed" in panel
    assert 'href="/upload#processing"' in panel

    client.cookies.set("anamna_lang", "uk")
    assert "Не вдалося перечитати 1 файл" in stale_panel(client)
    client.cookies.set("anamna_lang", "en")


def test_a_file_the_queue_cannot_find_is_written_down_rather_than_swallowed(
    tmp_path: Path, caplog
):
    """The one failure that logged nothing.

    A server whose database had been placed on its volume without `sources/`
    beside it failed 124 re-reads in a row and wrote not one line about it; the
    only visible effect was a count that never moved.
    """
    from anamna.ingest import intake

    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET source_path='/nowhere/report.pdf' WHERE id='doc-1'")
        connection.commit()
    (settings.source_dir / "report.pdf").unlink()
    intake.enqueue(
        settings, owner_user_id=user_id, patient_id=patient_of(settings), batch_id="batch-x",
        kind="rescan", filename="report.pdf", document_id="doc-1", start=False,
    )
    with caplog.at_level(logging.WARNING, logger="anamna.ingest.intake"):
        intake.drain_now(settings)

    assert any("found no file to read" in record.getMessage() for record in caplog.records)
    with connect(settings) as connection:
        job = connection.execute("SELECT state, detail_key FROM upload_jobs").fetchone()
    assert (job["state"], job["detail_key"]) == ("failed", "intake.failed_missing")


def test_a_job_whose_worker_died_is_returned_to_the_queue(tmp_path: Path):
    """`_claim` only ever looks at `queued`, so `running` is a one-way door.

    Recreating the container mid-rescan left a job claimed by a worker that no
    longer existed: not queued, so nothing picks it up; not finished, so the
    processing area reads "Reading..." for good.
    """
    from anamna.ingest import intake

    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO upload_jobs(id, owner_user_id, patient_id, batch_id, kind, filename,
                                       state, detail_key, document_id, created_at, started_at)
               VALUES ('stranded', ?, ?, 'batch-x', 'rescan', 'report.pdf',
                       'running', 'intake.step_reading', 'doc-1', '2026-01-01T00:00:00Z',
                       '2026-01-01T00:00:01Z')""",
            (user_id, patient_of(settings)),
        )
        connection.commit()

    assert intake.reclaim_abandoned_jobs(settings) == 1
    with connect(settings) as connection:
        job = connection.execute("SELECT * FROM upload_jobs WHERE id='stranded'").fetchone()
    assert (job["state"], job["detail_key"]) == ("queued", "intake.step_waiting")
    assert job["started_at"] is None
    # Nothing left to reclaim, so a restart with a quiet queue changes nothing.
    assert intake.reclaim_abandoned_jobs(settings) == 0


def test_the_document_page_offers_a_reread_in_both_languages(tmp_path: Path):
    settings, _, client = build(tmp_path)
    body = client.get("/documents/doc-1").text
    assert "Re-read with the current parser" in body
    # The button stands alone; the explanatory paragraph under it is gone.
    assert "verified, corrected or set aside are kept exactly as they are" not in body
    assert 'action="/documents/doc-1/rescan"' in body

    client.cookies.set("anamna_lang", "uk")
    ukrainian = client.get("/documents/doc-1").text
    assert "Перечитати поточною версією" in ukrainian
    assert "Re-read with the current parser" not in ukrainian
    client.cookies.set("anamna_lang", "en")


def test_a_reread_waits_out_another_writer(tmp_path: Path, rescanner):
    """A background re-read must not fail because another writer held the
    lock for longer than the interactive five-second timeout."""
    import sqlite3
    import threading
    import time

    settings, user_id, _ = build(tmp_path)
    rescanner([observation("Ferritin", 42.0)])
    held = threading.Event()

    def hold() -> None:
        other = sqlite3.connect(settings.database_path, isolation_level=None)
        other.execute("BEGIN IMMEDIATE")
        held.set()
        time.sleep(6)
        other.execute("COMMIT")
        other.close()

    thread = threading.Thread(target=hold)
    thread.start()
    held.wait()
    try:
        result = pipeline.reingest_document(settings, user_id, "doc-1")
    finally:
        thread.join()
    assert result["replaced"] == 8
