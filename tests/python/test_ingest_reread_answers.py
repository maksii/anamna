"""After a re-read: what it may ask, how the asking stays true, and the answers.

Pins the post-deploy findings of 2026-11-06 on the sandbox:
1. calculated eGFR rows were reported as "no longer found";
2. 291 reference refreshes on one ALEX² panel became questions;
3. «Verify 57 extracted observations» outlived the verification;
4. 52 value changes had no way to be applied but one hand correction each.
"""

from __future__ import annotations

import json
from pathlib import Path

from anamna.db import connect
from anamna.ingest import pipeline
from anamna.security import create_access_token

from test_ingest_reread_pairing import (  # noqa: F401  (fixture)
    TWO_PAGES,
    empty_document,
    open_task,
    parsed,
    parts_of,
    rows,
    stored,
)
from test_rescan import build, classification, page, rescanner  # noqa: F401  (fixture)


def csrf(settings, user_id: str) -> str:
    with connect(settings) as connection:
        return connection.execute("SELECT csrf_token FROM sessions WHERE user_id=?", (user_id,)).fetchone()[0]


def audit(settings, action: str) -> list[dict]:
    with connect(settings) as connection:
        return [
            {**dict(row), "details": json.loads(row["details_json"] or "{}")}
            for row in connection.execute("SELECT * FROM audit_events WHERE action=? ORDER BY id", (action,))
        ]


def task_with(settings, user_id: str, parts: list[dict]) -> str:
    with connect(settings) as connection:
        connection.execute("UPDATE review_tasks SET state='resolved' WHERE entity_id='doc-1'")
        task_id = pipeline.open_review_task(connection, user_id, "doc-1", parts)
        connection.commit()
    return task_id


def task_state(settings, task_id: str) -> dict:
    with connect(settings) as connection:
        return dict(connection.execute("SELECT * FROM review_tasks WHERE id=?", (task_id,)).fetchone())


def test_a_calculated_egfr_is_never_reported_as_no_longer_found(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    stored(settings, user_id, "Креатинін", 80.0, unit="мкмоль/л")
    stored(settings, user_id, "eGFR (CKD-EPI 2021)", 110.0, unit="mL/min/1.73m²")
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET extraction_method='derived_ckd_epi_2021' WHERE raw_name LIKE 'eGFR%'"
        )
        connection.commit()
    rescanner([parsed("Креатинін", 80.0, unit="мкмоль/л")], pages=TWO_PAGES)
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        open_tasks = connection.execute(
            "SELECT reason_params_json FROM review_tasks WHERE entity_id='doc-1' AND state='open'"
        ).fetchall()
    assert all("reread_orphaned" not in str(row[0]) for row in open_tasks)


def test_a_reference_refresh_is_audited_not_asked(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    stored(settings, user_id, "Бактерії в мкл (BACT)", 130.1, unit="кл/мкл", reference="жінки < 100.0")
    rescanner(
        [parsed("Бактерії в мкл (BACT)", 130.1, unit="кл/мкл", reference="жінки < 100.0 чоловіки < 26.4")],
        pages=TWO_PAGES,
    )
    pipeline.reingest_document(settings, user_id, "doc-1")
    (row,) = rows(settings)
    assert row["vendor_reference_text"] == "жінки < 100.0 чоловіки < 26.4"
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM review_tasks WHERE entity_id='doc-1' AND state='open' "
            "AND reason_params_json LIKE '%reread_reference%'"
        ).fetchone()[0] == 0
    (event,) = audit(settings, "observation_reread_refreshed")
    assert event["details"]["references"][0]["old"] == "жінки < 100.0"


def test_the_repair_drops_refresh_parts_and_resolves_an_emptied_task(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE document_id='doc-1'")
        connection.commit()
    only_refresh = task_with(settings, user_id, [
        pipeline.reason_part("review.reread_reference_n", count=1, items=[{"kind": "reference", "label": "A",
                                                                            "page": 1, "old": "x", "new": "y"}]),
        pipeline.reason_part("review.reread_dates_n", count=2, old_date="2025-08-31", new_date="2025-08-28"),
    ])
    with connect(settings) as connection:
        assert pipeline.repair_review_tasks(connection) == 1
        assert pipeline.repair_review_tasks(connection) == 0
        connection.commit()
    resolved = task_state(settings, only_refresh)
    assert (resolved["state"], resolved["resolution"]) == ("resolved", "completed")
    assert audit(settings, "review_task_resolved")


def test_verifying_values_recounts_the_open_task_on_every_path(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    task_id = task_with(settings, user_id, [pipeline.reason_part("review.verify_n", count=8)])
    token = csrf(settings, user_id)
    # The row-swap JSON path.
    response = client.post("/observations/obs-0/state", data={"action": "verify", "csrf_token": token},
                           headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert parts_of(task_state(settings, task_id))["review.verify_n"]["count"] == 7
    # The plain form path.
    client.post("/observations/obs-1/state", data={"action": "verify", "csrf_token": token}, follow_redirects=False)
    assert parts_of(task_state(settings, task_id))["review.verify_n"]["count"] == 6
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE id <> 'obs-7'")
        connection.commit()
    client.post("/observations/obs-7/state", data={"action": "verify", "csrf_token": token}, follow_redirects=False)
    done = task_state(settings, task_id)
    assert done["state"] == "resolved"
    assert any(event["entity_id"] == task_id for event in audit(settings, "review_task_resolved"))


def _proposal_task(settings, user_id: str) -> str:
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE document_id='doc-1'")
        rows_ = {row["raw_name"]: dict(row) for row in connection.execute(
            "SELECT * FROM observations WHERE document_id='doc-1'")}
        connection.commit()
    ldl, hdl, other = rows_["LDL cholesterol"], rows_["HDL cholesterol"], rows_["Creatinine"]
    return task_with(settings, user_id, [
        pipeline.reason_part("review.reread_changed_n", count=2, items=[
            {"kind": "changed", "id": ldl["id"], "label": ldl["raw_name"], "page": ldl["page_number"],
             "old": pipeline._reading(ldl),
             "new": {"numeric": 0.15, "text": None, "comparator": "<", "unit": "mmol/L", "printed": "0.15"}},
            # An older task without ids: found by page, label and value.
            {"kind": "changed", "label": hdl["raw_name"], "page": hdl["page_number"],
             "old": pipeline._reading(hdl),
             "new": {"numeric": 1.6, "text": None, "comparator": None, "unit": hdl["unit_raw"], "printed": "1.60"}},
        ]),
        pipeline.reason_part("review.reread_orphaned_n", count=1, items=[
            {"kind": "orphaned", "id": other["id"], "label": other["raw_name"], "page": other["page_number"],
             "old": pipeline._reading(other)},
        ]),
    ])


def test_applying_one_proposal_in_place_and_the_rest_at_once(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    task_id = _proposal_task(settings, user_id)
    page_html = client.get("/documents/doc-1").text
    assert "Apply the value the page now reads" in page_html and "Apply all 2" in page_html
    queue = client.get("/documents?review_state=open").text
    assert "re-read proposals to answer" in queue or "re-read proposal to answer" in queue

    token = csrf(settings, user_id)
    ldl_id = next(row["id"] for row in rows(settings) if row["raw_name"] == "LDL cholesterol")
    response = client.post("/documents/doc-1/reread-proposals",
                           data={"action": "apply", "observation_id": ldl_id, "csrf_token": token},
                           headers={"Accept": "application/json"})
    payload = response.json()
    assert payload["ok"] and ldl_id in payload["rows"] and "Apply the value" in payload["panel"]
    ldl = next(row for row in rows(settings) if row["id"] == ldl_id)
    assert (ldl["value_numeric"], ldl["comparator"], ldl["value_printed"], ldl["verification_status"]) == (
        0.15, "<", "0.15", "corrected")
    # The applied unit is folded like an inserted row's, never stored raw as canonical.
    from anamna.ingest.pipeline import stored_unit

    with connect(settings) as connection:
        preferred = connection.execute("SELECT preferred_unit FROM concepts WHERE id=?", (ldl["concept_id"],)).fetchone()[0]
    assert ldl["unit_canonical"] == stored_unit(ldl["unit_raw"], preferred, ldl["concept_id"])
    (event,) = audit(settings, "observation_reread_applied")
    assert event["details"]["previous"]["value_numeric"] == 4.42 and "token_kind" in event["details"]

    client.post("/documents/doc-1/reread-proposals", data={"action": "apply_all", "csrf_token": token},
                follow_redirects=False)
    hdl = next(row for row in rows(settings) if row["raw_name"] == "HDL cholesterol")
    assert (hdl["value_numeric"], hdl["verification_status"]) == (1.6, "corrected")
    assert "review.reread_changed_n" not in parts_of(task_state(settings, task_id))


def test_a_value_no_longer_found_can_be_set_aside_or_kept_and_the_task_resolves(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    task_id = _proposal_task(settings, user_id)
    token = csrf(settings, user_id)
    creatinine = next(row["id"] for row in rows(settings) if row["raw_name"] == "Creatinine")
    client.post("/documents/doc-1/reread-proposals", data={"action": "apply_all", "csrf_token": token},
                follow_redirects=False)
    client.post("/documents/doc-1/reread-proposals",
                data={"action": "set_aside", "observation_id": creatinine, "csrf_token": token},
                follow_redirects=False)
    assert next(row for row in rows(settings) if row["id"] == creatinine)["verification_status"] == "rejected"
    assert task_state(settings, task_id)["state"] == "resolved"
    # Reversible through the row's own Restore.
    client.post(f"/observations/{creatinine}/state", data={"action": "restore", "csrf_token": token},
                follow_redirects=False)
    assert next(row for row in rows(settings) if row["id"] == creatinine)["verification_status"] == "extracted"


def test_keep_answers_the_question_for_good(tmp_path: Path, rescanner):
    settings, user_id, client = build(tmp_path)
    task_id = _proposal_task(settings, user_id)
    creatinine = next(row["id"] for row in rows(settings) if row["raw_name"] == "Creatinine")
    _, secret = create_access_token(settings, user_id, "agent", "Orchestrator")
    response = client.post("/documents/doc-1/reread-proposals",
                           data={"action": "keep", "observation_id": creatinine},
                           headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"})
    assert response.status_code == 200, response.text
    assert "review.reread_orphaned_n" not in parts_of(task_state(settings, task_id))
    (event,) = audit(settings, "observation_reread_kept")
    assert event["details"]["token_kind"] == "agent"


def test_the_repair_takes_a_calculated_egfr_off_an_old_task(tmp_path: Path):
    """Sandbox tasks written before the fix name the eGFR row by label, not id."""
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET verification_status='verified', extraction_method='derived_ckd_epi_2021' "
            "WHERE id='obs-0'"
        )
        egfr = dict(connection.execute("SELECT * FROM observations WHERE id='obs-0'").fetchone())
        connection.commit()
    task_id = task_with(settings, user_id, [
        pipeline.reason_part("review.reread_orphaned_n", count=1, items=[
            {"kind": "orphaned", "label": egfr["raw_name"], "page": egfr["page_number"],
             "old": pipeline._reading(egfr)},
        ]),
    ])
    with connect(settings) as connection:
        pipeline.repair_review_tasks(connection)
        connection.commit()
    assert task_state(settings, task_id)["state"] == "resolved"


def test_the_review_line_does_not_repeat_the_proposals_panel(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _proposal_task(settings, user_id)
    page_html = client.get("/documents/doc-1").text
    line = page_html.split("data-review-line>", 1)[1].split("</p>", 1)[0]
    assert "reads" not in line and "no longer finds" not in line


def test_an_old_proposal_that_fits_several_readings_is_never_guessed(tmp_path: Path):
    """A Garmin page prints «Нормальний» on a dozen readings; an id-less item
    from before items carried ids cannot say which one it meant."""
    settings, user_id, client = build(tmp_path)
    empty_document(settings)
    for moment in ("2024-07-07T15:05:00", "2024-07-07T22:37:00"):
        stored(settings, user_id, "Blood pressure category", text="Нормальний", observed_at=moment)
    task_id = task_with(settings, user_id, [
        pipeline.reason_part("review.reread_changed_n", count=1, items=[
            {"kind": "changed", "label": "Blood pressure category", "page": 1,
             "old": {"numeric": None, "text": "Нормальний", "comparator": None, "unit": None},
             "new": {"numeric": None, "text": "Високий нормальний", "comparator": None, "unit": None}},
        ]),
    ])
    response = client.post("/documents/doc-1/reread-proposals",
                           data={"action": "apply_all", "csrf_token": csrf(settings, user_id)},
                           follow_redirects=False)
    assert response.status_code == 404
    assert {row["value_text"] for row in rows(settings)} == {"Нормальний"}
    with connect(settings) as connection:
        pipeline.repair_review_tasks(connection)
        connection.commit()
    # Kept as written until a re-read replaces it with one that names its row.
    assert parts_of(task_state(settings, task_id))["review.reread_changed_n"]["count"] == 1


def test_the_answer_route_refuses_without_the_session_token(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _proposal_task(settings, user_id)
    assert client.post("/documents/doc-1/reread-proposals",
                       data={"action": "apply_all", "csrf_token": "wrong"}).status_code == 403
