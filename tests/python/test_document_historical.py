"""A document the person marked historical stays in the record and keeps its
verdicts, but its conclusions, the results whose latest reading comes from it,
the panels it feeds and the test plan's "measure again" reasons stop raising
attention.  A newer reading from another document is judged as usual.
"""
from __future__ import annotations

from pathlib import Path

from anamna.db import connect, utc_now
from anamna.panels import ATTENTION_INTERPRETATIONS, roll_up
from anamna.security import create_user
from anamna.testplan import needs
from anamna.web import app as web
from test_web_panels import PASSWORD, build, catalog_for
from test_web_security import seed_document, seed_patient


def _csrf(settings, user_id: str) -> str:
    with connect(settings) as connection:
        return connection.execute(
            "SELECT csrf_token FROM sessions WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()[0]


def _mark(client, settings, user_id: str, document_id: str, historical: str):
    return client.post(
        f"/documents/{document_id}/historical",
        data={"historical": historical, "csrf_token": _csrf(settings, user_id)},
        follow_redirects=False,
    )


def _attention_ids(settings, user_id: str) -> set[str]:
    web.invalidate_catalog(user_id)
    with connect(settings) as connection:
        return {str(card["id"]) for card in web._attention_cards(web._metric_catalog(connection, user_id))}


def _historical_at(settings, document_id: str):
    with connect(settings) as connection:
        return connection.execute("SELECT historical_at FROM documents WHERE id=?", (document_id,)).fetchone()[0]


def _second_report(settings, user_id: str, day: str = "2025-06-01") -> None:
    """A newer LDL reading (4.6) on its own document, copied from the first one."""
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO documents(id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
                   classification_confidence, report_date, imported_at, status)
               SELECT 'doc-2', owner_user_id, patient_id, vendor_id, 'later.pdf', source_path, mime_type,
                      byte_size, 'sha-2', 1, 'later', clinical_type, extraction_strategy,
                      classification_confidence, ?, ?, status
               FROM documents WHERE id='doc-1' AND owner_user_id=?""",
            (day, utc_now(), user_id),
        )
        connection.execute(
            """INSERT INTO observations(id, owner_user_id, patient_id, document_id, page_number, concept_id,
                   raw_name, value_type, value_numeric, unit_raw, observed_at, verification_status,
                   extraction_method, confidence, evidence_text, parser_version, created_at)
               SELECT 'obs-later', owner_user_id, patient_id, 'doc-2', 1, concept_id, raw_name, value_type,
                      4.6, unit_raw, ?, 'extracted', 'test', 0.9, 'later evidence', parser_version, ?
               FROM observations WHERE id='obs-0' AND owner_user_id=?""",
            (day, utc_now(), user_id),
        )
    web.invalidate_catalog(user_id)


def test_marking_and_clearing_are_saved_and_audited(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    response = _mark(client, settings, user_id, "doc-1", "1")
    assert response.status_code == 303
    assert response.headers["location"] == "/documents/doc-1?historical=saved#document-historical"
    assert _historical_at(settings, "doc-1")
    with connect(settings) as connection:
        actions = [row[0] for row in connection.execute(
            "SELECT action FROM audit_events WHERE entity_id='doc-1' AND action LIKE 'document_marked_%' ORDER BY created_at"
        )]
    assert actions == ["document_marked_historical"]

    response = _mark(client, settings, user_id, "doc-1", "0")
    assert response.status_code == 303
    assert response.headers["location"] == "/documents/doc-1?historical=cleared#document-historical"
    assert _historical_at(settings, "doc-1") is None
    with connect(settings) as connection:
        cleared = connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE entity_id='doc-1' AND action='document_marked_current'"
        ).fetchone()[0]
    assert cleared == 1


def test_marking_needs_the_session_token_and_the_owner(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    for data in ({"historical": "1"}, {"historical": "1", "csrf_token": "wrong"}):
        response = client.post("/documents/doc-1/historical", data=data, follow_redirects=False)
        assert response.status_code == 403
    assert _historical_at(settings, "doc-1") is None

    other = create_user(settings, "other@example.test", "Other", PASSWORD)
    seed_document(settings, other, seed_patient(settings, other, "Other"), "Other private result", "other.txt")
    response = _mark(client, settings, user_id, "doc-other.txt", "1")
    assert response.status_code == 404
    with connect(settings) as connection:
        assert connection.execute("SELECT historical_at FROM documents WHERE id='doc-other.txt'").fetchone()[0] is None


def test_a_result_whose_latest_reading_is_historical_stops_raising_attention(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    assert "ldl-cholesterol" in _attention_ids(settings, user_id)
    before = catalog_for(settings, user_id)["ldl-cholesterol"]["verdict"]["interpretation"]
    assert before == "high"

    _mark(client, settings, user_id, "doc-1", "1")
    assert "ldl-cholesterol" not in _attention_ids(settings, user_id)
    card = catalog_for(settings, user_id)["ldl-cholesterol"]
    assert card["historical"] is True
    assert card["verdict"]["interpretation"] == before

    _mark(client, settings, user_id, "doc-1", "0")
    assert "ldl-cholesterol" in _attention_ids(settings, user_id)
    assert catalog_for(settings, user_id)["ldl-cholesterol"]["historical"] is False


def test_a_newer_reading_from_another_document_is_judged_as_usual(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _second_report(settings, user_id)
    _mark(client, settings, user_id, "doc-1", "1")
    card = catalog_for(settings, user_id)["ldl-cholesterol"]
    assert card["historical"] is False
    assert card["latest_date"] == "2025-06-01"
    assert "ldl-cholesterol" in _attention_ids(settings, user_id)


def test_a_conclusion_from_a_historical_document_is_information(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO clinical_findings(id, owner_user_id, patient_id, document_id, page_number,
                   health_area, title, summary_en, original_text, finding_date, status, confidence,
                   verification_status, created_at)
               VALUES ('finding-1', ?, ?, 'doc-1', 1, 'heart', 'Cardiology consultation',
                       'Aortic valve sclerosis', 'Aortic valve sclerosis', '2025-02-13', 'attention', 0.9,
                       'extracted', ?)""",
            (user_id, f"patient-{user_id}", utc_now()),
        )

    def attention_ids() -> list[str]:
        web.invalidate_catalog(user_id)
        with connect(settings) as connection:
            return [str(row["id"]) for row in web._attention_findings(web._finding_catalog(connection, user_id))]

    assert attention_ids() == ["finding-1"]
    _mark(client, settings, user_id, "doc-1", "1")
    assert attention_ids() == []
    with connect(settings) as connection:
        rows = {str(row["id"]): row for row in web._finding_catalog(connection, user_id)}
    assert rows["finding-1"]["historical"] is True
    assert rows["finding-1"]["status"] == "information"


def test_a_historical_member_does_not_flag_its_panel():
    high = {"verdict": {"interpretation": "high"}, "historical": True}
    assert "high" in ATTENTION_INTERPRETATIONS
    assert roll_up([{"verdict": {"interpretation": "high"}}])["status"] == "attention"
    assert roll_up([high])["status"] != "attention"
    assert roll_up([high])["flagged_count"] == 0
    assert roll_up([high, {"verdict": {"interpretation": "borderline_high"}, "historical": True}])["status"] == "unjudged"
    assert roll_up([high, {"verdict": {"interpretation": "normal"}}])["status"] == "normal"


def test_a_historical_result_is_not_a_reason_to_measure_again():
    card = {
        "id": "ldl-cholesterol", "name": "LDL cholesterol", "category": "lipids",
        "verdict": {"interpretation": "high"}, "staleness": {"state": "fresh"}, "is_device": False,
    }
    assert [need["key"] for need in needs([card], {"ldl-cholesterol"})] == ["ldl-cholesterol"]
    assert needs([{**card, "historical": True}], {"ldl-cholesterol"}) == []


def test_document_page_offers_the_control_and_shows_the_mark(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    page = client.get("/documents/doc-1")
    assert page.status_code == 200
    assert 'action="/documents/doc-1/historical"' in page.text
    assert 'id="document-historical"' in page.text
    assert "an-historical-pill" not in page.text

    _mark(client, settings, user_id, "doc-1", "1")
    page = client.get("/documents/doc-1?historical=saved")
    assert page.status_code == 200
    assert "an-historical-pill" in page.text
    assert 'value="0"' in page.text
