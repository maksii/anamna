"""What a person can say on the document page that the software cannot:
"this file is part N of that report" and "the conclusion reads like this".

Both answer phone photos whose text OCR cannot read reliably: the photo is
kept as image evidence, linked into its report, and its conclusion is written
by a person from the image.  Neither answer may be undone by a re-read, the
start-up repair or `sync_clinical_findings`.  Bearer callers (the agent
credential) skip CSRF, so they must not be refused for omitting the field.
Every name, number and date here is invented.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna.db import connect
from anamna.health import sync_clinical_findings
from anamna.ingest import intake, pipeline
from anamna.security import create_access_token
from anamna.web.app import create_app

from test_document_copies import add_document, relations
from test_document_duplicates import scalar
from test_rescan import build


@pytest.fixture(autouse=True)
def no_worker(monkeypatch):
    monkeypatch.setattr(intake, "start_worker", lambda settings: None)


REPORT_PAGE = """Медичний центр Тестова клініка
Протокол консультації лікаря
Скарги на біль у горлі протягом трьох днів.
"""
PHOTO_PAGE = """В1СНОВОК :: г0стрий фарингіт
Рекомен.. полоскання
"""
ULTRASOUND = """Медичний центр Тестова клініка
ПРОТОКОЛ УЛЬТРАЗВУКОВОГО ДОСЛІДЖЕННЯ органів черевної порожнини
Печінка не збільшена, контури рівні.
ВИСНОВОК: Ехо ознак дифузних змін печ1нки ;; не виявлено.
РЕКОМЕНДОВАНО: консультація терапевта
"""


def _task(settings, doc_id: str, state: str = "open") -> None:
    """Every added document arrives with its open task `task-<id>`; set its state."""
    with connect(settings) as connection:
        connection.execute("UPDATE review_tasks SET state=? WHERE id=?", (state, f"task-{doc_id}"))
        connection.commit()


def _agent(settings, user_id: str) -> dict[str, str]:
    _, secret = create_access_token(settings, user_id, "agent", "test agent")
    return {"Authorization": f"Bearer {secret}", "Accept": "application/json"}


def _states(settings, *doc_ids: str) -> list[str]:
    with connect(settings) as connection:
        return [
            connection.execute("SELECT state FROM review_tasks WHERE entity_id=?", (doc_id,)).fetchone()[0]
            for doc_id in doc_ids
        ]


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_a_person_links_a_photo_as_part_of_a_report_and_can_undo_it(tmp_path: Path, locale: str):
    settings, user_id, client = build(tmp_path)
    client.cookies.set("anamna_lang", locale)
    add_document(settings, "report", REPORT_PAGE, imported_at="2026-02-01T10:00:00+00:00")
    add_document(settings, "photo", ocr=PHOTO_PAGE, mime="image/jpeg", imported_at="2026-02-01T10:00:05+00:00")
    agent = _agent(settings, user_id)
    with TestClient(create_app(settings)) as api:
        done = api.post("/documents/photo/duplicate", data={"action": "part", "primary_id": "report"}, headers=agent)
        assert done.status_code == 200 and done.json()["report_document_id"] == "report"
        # Naming the part itself as a report means the report it belongs to.
        refused = api.post("/documents/report/duplicate", data={"action": "part", "primary_id": "photo"}, headers=agent)
        assert refused.status_code == 409 and refused.json()["error"] == "self"
    held = {row for row in relations(settings) if row[2] == "part_of"}
    assert held == {("photo", "report", "part_of", "person:part_of")}
    audit = json.loads(scalar(settings, "SELECT details_json FROM audit_events WHERE action='document_linked_part'"))
    assert audit == {"report_document_id": "report", "token_kind": "agent"}

    # Neither a re-read nor the start-up repair replaces it.
    with connect(settings) as connection:
        for doc_id in ("report", "photo"):
            pipeline.record_document_relations(connection, user_id, doc_id)
        pipeline.repair_text_duplicates(connection)
        connection.commit()
    assert ("photo", "report", "part_of", "person:part_of") in relations(settings)

    words = {
        "en": ("Page or part of this report, linked by a person:", "Page or part of the report",
               "Not part of this report", "Part of another report"),
        "uk": ("Сторінка або частина цього звіту, приєднана людиною:", "Сторінка або частина звіту",
               "Це не частина цього звіту", "Частина іншого звіту"),
    }[locale]
    head = client.get("/documents/report").text
    assert words[0] in head
    assert 'src="/documents/photo/pages/1/image"' in head  # the part's page, readable from the report
    part = client.get("/documents/photo").text
    assert words[1] in part and words[2] in part and words[3] in part

    # "Not part of this report" undoes the link, and a re-read does not bring it back.
    with TestClient(create_app(settings)) as api:
        undone = api.post("/documents/photo/duplicate", data={"action": "keep_both", "other_id": "report"}, headers=agent)
        assert undone.status_code == 200
    with connect(settings) as connection:
        pipeline.record_document_relations(connection, user_id, "photo")
        connection.commit()
    assert not {row for row in relations(settings) if row[2] == "part_of"}


def test_checking_the_report_checks_the_parts_a_person_linked(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    for doc_id, imported in (("report", "10"), ("photo-2", "11"), ("photo-3", "12"), ("flagged", "13")):
        add_document(settings, doc_id, f"page {doc_id}", imported_at=f"2026-02-01T10:00:{imported}+00:00")
        _task(settings, doc_id, "needs_correction" if doc_id == "flagged" else "open")
    agent = _agent(settings, user_id)
    with TestClient(create_app(settings)) as api:
        for part in ("photo-2", "photo-3", "flagged"):
            assert api.post(
                f"/documents/{part}/duplicate", data={"action": "part", "primary_id": "report"}, headers=agent
            ).status_code == 200
        # A bearer caller sends no csrf_token: the route must not 422 on it.
        verified = api.post("/documents/report/review", data={"action": "verify"}, headers=agent,
                            follow_redirects=False)
        assert verified.status_code == 303
        assert _states(settings, "report", "photo-2", "photo-3", "flagged") == [
            "resolved", "resolved", "resolved", "needs_correction",
        ]
        reopened = api.post("/review/task-report", data={"action": "reopen"}, headers=agent, follow_redirects=False)
        assert reopened.status_code == 303
        assert _states(settings, "report", "photo-2", "photo-3") == ["open", "open", "open"]


def test_bearer_requests_need_no_csrf_field_but_a_cookie_session_still_does(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_document(settings, "report", REPORT_PAGE)
    _task(settings, "report")
    agent = _agent(settings, user_id)
    assert client.post("/documents/report/review", data={"action": "verify"}, follow_redirects=False).status_code == 403
    assert client.post("/documents/report/tags", data={"name": "x"}, follow_redirects=False).status_code == 403
    with TestClient(create_app(settings)) as api:
        for path, data in (
            ("/documents/report/tags", {"name": "photo"}),
            ("/documents/report/metadata", {"title": "Consultation"}),
            ("/documents/report/review", {"action": "verify"}),
            ("/review/task-report", {"action": "reopen"}),
        ):
            response = api.post(path, data=data, headers=agent, follow_redirects=False)
            assert response.status_code in (200, 303), (path, response.status_code, response.text[:200])
    assert _states(settings, "report") == ["open"]


def _ultrasound(settings) -> list[dict[str, object]]:
    add_document(settings, "us-1", ULTRASOUND, clinical_type="ultrasound", report_date="2025-03-01")
    with connect(settings) as connection:
        sync_clinical_findings(connection)
        connection.commit()
        return [dict(row) for row in connection.execute(
            "SELECT * FROM clinical_findings WHERE document_id='us-1' ORDER BY health_area")]


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_a_person_corrects_a_conclusion_and_no_rebuild_overwrites_it(tmp_path: Path, locale: str):
    settings, user_id, client = build(tmp_path)
    client.cookies.set("anamna_lang", locale)
    rows = _ultrasound(settings)
    assert rows and all("печ1нки" in row["summary_uk"] for row in rows)
    read = rows[0]["summary_uk"]
    agent = _agent(settings, user_id)
    fixed = "Ехо ознак дифузних змін печінки не виявлено."
    with TestClient(create_app(settings)) as api:
        response = api.post(
            "/documents/us-1/findings",
            data={"finding_id": [row["id"] for row in rows], "summary": fixed,
                  "recommendations": "консультація терапевта"},
            headers=agent,
        )
        assert response.status_code == 200 and response.json()["ok"]
        # A finding of another document is not reachable through this one.
        assert api.post("/documents/doc-1/findings", data={"finding_id": rows[0]["id"], "summary": "x"},
                        headers=agent).status_code == 404

    with connect(settings) as connection:
        sync_clinical_findings(connection)  # start-up, upload and re-read all run this
        connection.commit()
        stored = [dict(row) for row in connection.execute(
            "SELECT * FROM clinical_findings WHERE document_id='us-1' ORDER BY health_area")]
    assert [row["id"] for row in stored] == [row["id"] for row in rows]
    assert {(row["summary_uk"], row["summary_en"], row["recommendations"], row["verification_status"])
            for row in stored} == {(fixed, "", "консультація терапевта", "corrected")}
    details = json.loads(scalar(settings, "SELECT details_json FROM audit_events WHERE action='finding_corrected' LIMIT 1"))
    assert details["source"] == "image" and details["before"]["summary_uk"] == read
    assert details["token_kind"] == "agent"

    page = client.get("/documents/us-1").text
    words = {
        "en": ("Corrected by a person", "Written from the image of the report by", "Show the text as read"),
        "uk": ("Виправлено людиною", "Текст записано за зображенням звіту:", "Показати прочитаний текст"),
    }[locale]
    assert all(word in page for word in words)
    assert fixed in page and read in page  # shown, and the text as read one press away

    # Undo puts back what the software read, and it is machine output again.
    with TestClient(create_app(settings)) as api:
        undone = api.post("/documents/us-1/findings",
                          data={"finding_id": [row["id"] for row in rows], "action": "revert"}, headers=agent)
        assert undone.status_code == 200
    with connect(settings) as connection:
        back = {(row[0], row[1]) for row in connection.execute(
            "SELECT summary_uk, verification_status FROM clinical_findings WHERE document_id='us-1'")}
    assert back == {(read, "extracted")}


def test_a_person_corrected_finding_survives_a_reread_of_its_document(tmp_path: Path):
    """The re-read deletes and recreates the document's reports, from which
    findings cascade; a corrected one is moved to the new report first."""
    settings, user_id, client = build(tmp_path)
    rows = _ultrasound(settings)
    with connect(settings) as connection:
        connection.execute("UPDATE clinical_findings SET verification_status='corrected', summary_uk='Норма.'"
                           " WHERE document_id='us-1'")
        report = connection.execute(
            "INSERT INTO reports(id, document_id, owner_user_id, patient_id, start_page, end_page, clinical_type, title,"
            " created_at) SELECT 'old-report', id, owner_user_id, patient_id, 1, 1, 'ultrasound', 'x', '2026-01-01'"
            " FROM documents WHERE id='us-1'"
        )
        assert report.rowcount == 1
        connection.execute("UPDATE clinical_findings SET report_id='old-report' WHERE document_id='us-1'")
        connection.commit()
        pipeline._refile_ruled_rows(connection, "us-1", [], {1: None})
        connection.execute("DELETE FROM reports WHERE id='old-report'")
        sync_clinical_findings(connection)
        connection.commit()
        kept = {row[0] for row in connection.execute("SELECT summary_uk FROM clinical_findings WHERE document_id='us-1'")}
    assert len(rows) == 2 and kept == {"Норма."}
