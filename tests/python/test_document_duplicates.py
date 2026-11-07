"""One report held as two files: found, shown, and counted once.

A re-export of the same PDF arrives as different bytes -- a temp-file path in
the footer, other line wraps, other letter case -- so the import does not see
an exact duplicate.  Both copies then carried their own values and both sat in
the review queue asking for the same values to be checked twice.  These tests
pin the answer: the record says the two are one report, a person keeps one,
and the copy matches the exact-duplicate contract (no values of its own)
without throwing away anything a person ruled on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna.db import connect
from anamna.ingest import intake, pipeline
from anamna.security import create_access_token
from anamna.web.app import create_app

from test_rescan import build, csrf_for

REPORT = """Ультразвукове дослідження м'яких тканин
Висновок: ехографічних ознак патологічних утворень не виявлено.
Лікар: Іваненко І.І.
"""


@pytest.fixture(autouse=True)
def no_worker(monkeypatch):
    monkeypatch.setattr(intake, "start_worker", lambda settings: None)


def add_copy(settings, doc_id: str = "copy", *, with_values: bool = True, imported_at: str = "2030-01-01T00:00:00+00:00"):
    """A second file of doc-1: other bytes, its own values and its own open task."""
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO documents(id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
                   classification_confidence, report_date, imported_at, status)
               SELECT ?, owner_user_id, patient_id, vendor_id, ?, source_path, mime_type, 1, ?, 1, title,
                      clinical_type, extraction_strategy, 1, report_date, ?, 'final'
                 FROM documents WHERE id='doc-1'""",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", imported_at),
        )
        if with_values:
            connection.execute(
                """INSERT INTO observations(id, owner_user_id, patient_id, document_id, page_number, concept_id,
                       raw_name, value_type, value_numeric, value_text, unit_raw, unit_canonical, observed_at,
                       verification_status, extraction_method, confidence, evidence_text, parser_version, created_at)
                   SELECT id || '-' || ?, owner_user_id, patient_id, ?, page_number, concept_id, raw_name,
                          value_type, value_numeric, value_text, unit_raw, unit_canonical, observed_at,
                          'extracted', extraction_method, confidence, evidence_text, parser_version, created_at
                     FROM observations WHERE document_id='doc-1'""",
                (doc_id, doc_id),
            )
        connection.execute(
            """INSERT INTO review_tasks(id, owner_user_id, entity_type, entity_id, reason, state, created_at)
               SELECT ?, owner_user_id, 'document', ?, 'Verify values', 'open', ? FROM documents WHERE id='doc-1'""",
            (f"task-{doc_id}", doc_id, imported_at),
        )
        connection.commit()


def set_pages(settings, doc_id: str, text: str) -> None:
    with connect(settings) as connection:
        connection.execute("DELETE FROM document_pages WHERE document_id=?", (doc_id,))
        connection.execute(
            """INSERT INTO document_pages(document_id, page_number, native_text, extraction_method, native_char_count)
               VALUES (?, 1, ?, 'native_pdf_text', ?)""",
            (doc_id, text, len(text)),
        )
        connection.commit()


def scalar(settings, sql: str, *params):
    with connect(settings) as connection:
        return connection.execute(sql, params).fetchone()[0]


def mark(client, settings, user_id, copy="copy", primary="doc-1", **headers):
    return client.post(
        f"/documents/{copy}/duplicate",
        data={"action": "mark", "primary_id": primary, "csrf_token": csrf_for(settings, user_id)},
        headers=headers,
        follow_redirects=False,
    )


def test_marking_a_copy_counts_its_values_once_and_unmarking_brings_them_back(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_copy(settings)
    with connect(settings) as connection:
        # A value checked on the copy that the kept document also holds is
        # not lost by removing the copy's rows.
        connection.execute("UPDATE observations SET verification_status='verified' WHERE id='obs-0-copy'")
        connection.commit()
    assert scalar(settings, "SELECT COUNT(*) FROM observations WHERE document_id='copy'") == 8

    response = mark(client, settings, user_id)
    assert response.status_code == 303
    assert response.headers["location"] == "/documents/copy#duplicates"
    assert scalar(settings, "SELECT duplicate_of_document_id FROM documents WHERE id='copy'") == "doc-1"
    assert scalar(settings, "SELECT COUNT(*) FROM observations WHERE document_id='copy'") == 0
    assert scalar(settings, "SELECT COUNT(*) FROM observations WHERE document_id='doc-1'") == 8
    # Its review task is answered, audited like any other resolution.
    assert scalar(settings, "SELECT state || ':' || resolution FROM review_tasks WHERE id='task-copy'") == "resolved:duplicate"
    assert scalar(
        settings,
        "SELECT COUNT(*) FROM audit_events WHERE action='review_task_resolved' AND entity_id='task-copy'",
    ) == 1
    details = json.loads(scalar(
        settings, "SELECT details_json FROM audit_events WHERE action='document_marked_duplicate' AND entity_id='copy'"
    ))
    assert details["removed_observation_count"] == 8
    assert details["primary_document_id"] == "doc-1"
    assert "token_kind" not in details  # a password session: the person's own hand
    with connect(settings) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    # The copy no longer waits in the review queue.
    queue = client.get("/documents?review_state=open").text
    assert "/documents/copy" not in queue

    response = client.post(
        "/documents/copy/duplicate",
        data={"action": "unmark", "csrf_token": csrf_for(settings, user_id)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "rescan=queued" in response.headers["location"]
    assert scalar(settings, "SELECT duplicate_of_document_id FROM documents WHERE id='copy'") is None
    assert scalar(
        settings, "SELECT COUNT(*) FROM upload_jobs WHERE document_id='copy' AND kind='rescan' AND state='queued'"
    ) == 1
    assert scalar(settings, "SELECT COUNT(*) FROM audit_events WHERE action='document_unmarked_duplicate'") == 1
    # "Not a duplicate" is remembered, so the suggestion does not come back.
    assert scalar(settings, "SELECT notes FROM document_relations WHERE relationship='duplicate'") == "person:not_duplicate"


def test_a_value_a_person_ruled_on_that_the_kept_document_lacks_refuses_the_mark(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_copy(settings)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET verification_status='corrected', value_numeric=99 WHERE id='obs-1-copy'"
        )
        connection.commit()
    response = mark(client, settings, user_id)
    assert response.status_code == 303
    assert response.headers["location"] == "/documents/copy?dup_error=ruled#duplicates"
    # Nothing changed.
    assert scalar(settings, "SELECT duplicate_of_document_id FROM documents WHERE id='copy'") is None
    assert scalar(settings, "SELECT COUNT(*) FROM observations WHERE document_id='copy'") == 8
    assert scalar(settings, "SELECT state FROM review_tasks WHERE id='task-copy'") == "open"
    page = client.get(response.headers["location"]).text
    assert "Nothing was changed: this copy holds values a person checked" in page

    refused = client.post(
        "/documents/copy/duplicate",
        data={"action": "mark", "primary_id": "doc-1", "csrf_token": csrf_for(settings, user_id)},
        headers={"Accept": "application/json"},
    )
    assert refused.status_code == 409
    assert refused.json()["error"] == "ruled"
    assert refused.json()["observation_ids"] == ["obs-1-copy"]


def test_marking_refuses_itself_a_chain_and_a_missing_csrf(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_copy(settings)
    assert mark(client, settings, user_id, copy="doc-1", primary="doc-1").headers["location"].endswith(
        "dup_error=self#duplicates"
    )
    assert mark(client, settings, user_id).status_code == 303
    # Naming the copy as the original means its original; doc-1 cannot become
    # a copy of its own copy.
    assert mark(client, settings, user_id, copy="doc-1", primary="copy").headers["location"].endswith(
        "dup_error=self#duplicates"
    )
    assert client.post(
        "/documents/doc-1/duplicate", data={"action": "mark", "primary_id": "copy"}, follow_redirects=False
    ).status_code == 403
    assert mark(client, settings, user_id, copy="nope").status_code == 404


def test_only_the_owner_or_its_agent_may_mark(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    add_copy(settings)
    _, guest = create_access_token(settings, user_id, "guest", "doctor", expires_at="2999-01-01T00:00:00+00:00")
    _, api = create_access_token(settings, user_id, "api", "integration")
    _, agent = create_access_token(settings, user_id, "agent", "deploy check")
    with TestClient(create_app(settings)) as anonymous:
        for secret in (guest, api):
            refused = anonymous.post(
                "/documents/copy/duplicate", data={"action": "mark", "primary_id": "doc-1"},
                headers={"Authorization": f"Bearer {secret}"}, follow_redirects=False,
            )
            assert refused.status_code == 403
        assert scalar(settings, "SELECT duplicate_of_document_id FROM documents WHERE id='copy'") is None
        done = anonymous.post(
            "/documents/copy/duplicate", data={"action": "mark", "primary_id": "doc-1"},
            headers={"Authorization": f"Bearer {agent}", "Accept": "application/json"},
        )
        assert done.status_code == 200 and done.json()["ok"]
    details = json.loads(scalar(settings, "SELECT details_json FROM audit_events WHERE action='document_marked_duplicate'"))
    assert details["token_kind"] == "agent"


def test_same_text_is_a_duplicate_despite_case_wraps_and_a_temp_file_footer(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    add_copy(settings, "first", with_values=False, imported_at="2025-01-01T00:00:00+00:00")
    add_copy(settings, "again", with_values=False, imported_at="2025-02-01T00:00:00+00:00")
    add_copy(settings, "other", with_values=False, imported_at="2025-03-01T00:00:00+00:00")
    add_copy(settings, "blank", with_values=False, imported_at="2025-04-01T00:00:00+00:00")
    add_copy(settings, "blank2", with_values=False, imported_at="2025-05-01T00:00:00+00:00")
    set_pages(settings, "first", REPORT + "C:\\Users\\maks\\AppData\\Local\\Temp\\tmp81a2.pdf\n")
    rewrapped = REPORT.upper().replace("ПАТОЛОГІЧНИХ ", "ПАТОЛОГІЧНИХ\n").replace(":", " :")
    set_pages(settings, "again", rewrapped + "file:///C:/Users/maks/AppData/Local/Temp/tmp99ff.pdf  1/1\n")
    set_pages(settings, "other", REPORT.replace("не виявлено", "виявлено кісту 4 мм"))
    set_pages(settings, "blank", "1/1")
    set_pages(settings, "blank2", "1/1")
    with connect(settings) as connection:
        pipeline.record_document_relations(connection, user_id, "again")
        connection.commit()
        found = connection.execute(
            "SELECT source_document_id, target_document_id, relationship, notes FROM document_relations"
        ).fetchall()
    assert [tuple(row) for row in found] == [("again", "first", "duplicate", "auto:same_text")]

    # Documents already held are linked on start, without a re-read; idempotent.
    with connect(settings) as connection:
        connection.execute("DELETE FROM document_relations")
        connection.commit()
        assert pipeline.repair_text_duplicates(connection) == 1
        assert pipeline.repair_text_duplicates(connection) == 0
        # A person's "different reports" survives both the repair and a re-read.
        connection.execute("UPDATE document_relations SET notes='person:not_duplicate'")
        pipeline.record_document_relations(connection, user_id, "again")
        pipeline.repair_text_duplicates(connection)
        assert connection.execute("SELECT notes FROM document_relations").fetchall()[0][0] == "person:not_duplicate"


def test_a_re_export_that_moved_whole_blocks_is_still_the_same_report(tmp_path: Path):
    """Expert Hospital's soft-tissue ultrasound came back with its footer above
    the doctor's line: same words, another order (sandbox, 2026-11-06)."""
    settings, user_id, _ = build(tmp_path)
    add_copy(settings, "first", with_values=False, imported_at="2025-01-01T00:00:00+00:00")
    add_copy(settings, "moved", with_values=False, imported_at="2025-02-01T00:00:00+00:00")
    set_pages(settings, "first", REPORT)
    set_pages(settings, "moved", "\n".join(reversed(REPORT.splitlines())))
    with connect(settings) as connection:
        pipeline.record_document_relations(connection, user_id, "moved")
        connection.commit()
        found = [tuple(row) for row in connection.execute(
            "SELECT source_document_id, target_document_id, relationship FROM document_relations")]
    assert found == [("moved", "first", "duplicate")]


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_both_notices_and_the_card_hint_render_in_both_languages(tmp_path: Path, locale: str):
    settings, user_id, client = build(tmp_path)
    client.cookies.set("anamna_lang", locale)
    add_copy(settings)
    with connect(settings) as connection:
        pipeline.record_document_relations(connection, user_id, "copy")
        connection.commit()
    assert scalar(settings, "SELECT notes FROM document_relations") == "auto:shared_results:8"
    words = {
        "en": ("Same report as", "Keep that one: mark this copy as a duplicate", "Keep this one: mark that one as a duplicate",
               "Both hold the same 8 results", "This is a copy of", "Not a duplicate", "A copy of this report is also held:"),
        "uk": ("Той самий документ, що й", "Залишити той, а цей позначити копією", "Залишити цей, а той позначити копією",
               "В обох ті самі 8 результатів", "Це копія документа", "Це не дублікат", "Є також копія цього документа:"),
    }[locale]
    page = client.get("/documents/copy").text
    for text in words[:4]:
        assert text in page, text
    # The copy is the newer import, so keeping the other one is the suggestion.
    assert page.index(words[1]) < page.index(words[2])
    queue = client.get("/documents?review_state=open").text
    assert words[0] in queue

    assert mark(client, settings, user_id).status_code == 303
    page = client.get("/documents/copy").text
    assert words[4] in page and words[5] in page
    assert words[0] not in page
    assert words[6] in client.get("/documents/doc-1").text
