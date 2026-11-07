"""`parser_issue_reports` — the trail a reader leaves for whoever fixes the parser.

A correction fixes one number and then a re-scan may regenerate every
observation id, so a report is only useful if it snapshots the misread at
filing time and outlives the row it was filed against.  These tests pin
exactly that contract: the snapshot carries the source path, page and
evidence line a fixing agent needs, and deleting the observation later must
not take the report with it.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from anamna.db import connect
from anamna.security import create_session, create_user
from anamna.web.app import create_app

from test_web_panels import build


def csrf_for(settings, user_id: str) -> str:
    with connect(settings) as connection:
        return connection.execute(
            "SELECT csrf_token FROM sessions WHERE user_id=?", (user_id,)
        ).fetchone()[0]


def file_report(client, csrf: str, **fields):
    data = {"category": "wrong_unit", "next": "/documents/doc-1", "csrf_token": csrf}
    data.update(fields)
    return client.post("/documents/doc-1/issues", data=data, follow_redirects=False)


def report_rows(settings):
    with connect(settings) as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM parser_issue_reports")]


def test_row_report_snapshots_everything_a_fixing_agent_needs(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    response = file_report(
        client, csrf,
        observation_id="obs-0", category="wrong_value",
        expected_text="4.24", description="Digits transposed",
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/documents/doc-1#issue-reports")

    (row,) = report_rows(settings)
    assert row["document_id"] == "doc-1"
    assert row["observation_id"] == "obs-0"
    assert row["category"] == "wrong_value"
    assert row["expected_text"] == "4.24"
    assert row["status"] == "open"

    context = json.loads(row["context_json"])
    # The document half locates the source file to reproduce against.
    assert context["document"]["source_path"].endswith("report.pdf")
    assert context["document"]["vendor"] == "Test Lab"
    assert context["parser_version"]
    # The observation half is what the parser stored, beside the line it read.
    observation = context["observation"]
    assert observation["raw_name"] == "LDL cholesterol"
    assert observation["value_numeric"] == 4.42
    assert observation["unit_raw"] == "mmol/L"
    assert observation["page_number"] == 1
    assert observation["evidence_text"] == "LDL cholesterol evidence"

    with connect(settings) as connection:
        actions = [
            str(row[0])
            for row in connection.execute(
                "SELECT action FROM audit_events WHERE entity_type='parser_issue_report'"
            )
        ]
    assert actions == ["issue_reported"]


def test_document_level_report_needs_no_observation(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    response = file_report(client, csrf, category="missing_value", description="ESR missing")
    assert response.status_code == 303
    (row,) = report_rows(settings)
    assert row["observation_id"] is None
    assert json.loads(row["context_json"])["observation"] is None


def test_report_outlives_the_observation_it_was_filed_against(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    file_report(client, csrf, observation_id="obs-0", category="wrong_value")
    # A re-scan deletes and recreates observation rows.
    with connect(settings) as connection:
        connection.execute("DELETE FROM observations WHERE id='obs-0'")
    (row,) = report_rows(settings)
    assert row["observation_id"] is None  # SET NULL, not CASCADE
    assert json.loads(row["context_json"])["observation"]["raw_name"] == "LDL cholesterol"


def test_resolve_and_reopen(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    file_report(client, csrf)
    (row,) = report_rows(settings)

    response = client.post(
        f"/issues/{row['id']}/state",
        data={"action": "resolve", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303
    (resolved,) = report_rows(settings)
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"]

    client.post(
        f"/issues/{row['id']}/state",
        data={"action": "reopen", "csrf_token": csrf},
        follow_redirects=False,
    )
    (reopened,) = report_rows(settings)
    assert reopened["status"] == "open"
    assert reopened["resolved_at"] is None


def test_bad_category_and_foreign_observation_are_refused(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    assert file_report(client, csrf, category="typo").status_code == 400
    assert file_report(client, csrf, observation_id="not-mine").status_code == 404
    assert report_rows(settings) == []


def _second_account(settings) -> tuple[TestClient, str]:
    """A signed-in stranger and their CSRF token, for the checks that matter most."""
    other_id = create_user(settings, "stranger@example.test", "Stranger", "1qaz@Wsx000")
    other = TestClient(create_app(settings))
    token, _ = create_session(settings, other_id)
    other.cookies.set("anamna_session", token)
    other.cookies.set("anamna_lang", "en")
    return other, csrf_for(settings, other_id)


def test_a_stranger_cannot_file_against_or_resolve_someone_elses_record(tmp_path: Path):
    """The routes take a bare document id and a bare issue id — the shape that
    is an IDOR whenever the owner predicate is forgotten.  The guards exist;
    nothing pinned them until now."""
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    file_report(client, csrf, observation_id="obs-0", category="wrong_value")
    (row,) = report_rows(settings)

    other, other_csrf = _second_account(settings)
    # Someone else's document is not theirs to file against...
    assert other.post(
        "/documents/doc-1/issues",
        data={"category": "wrong_value", "csrf_token": other_csrf},
        follow_redirects=False,
    ).status_code == 404
    # ...nor is someone else's report theirs to close.
    assert other.post(
        f"/issues/{row['id']}/state",
        data={"action": "resolve", "csrf_token": other_csrf},
        follow_redirects=False,
    ).status_code == 404
    assert report_rows(settings)[0]["status"] == "open"
    assert len(report_rows(settings)) == 1


def test_a_missing_csrf_token_and_an_unknown_action_are_refused(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    # No token at all: the write never happens.
    assert client.post(
        "/documents/doc-1/issues",
        data={"category": "wrong_value"},
        follow_redirects=False,
    ).status_code == 403
    assert report_rows(settings) == []

    file_report(client, csrf, category="wrong_value")
    (row,) = report_rows(settings)
    assert client.post(
        f"/issues/{row['id']}/state",
        data={"action": "delete", "csrf_token": csrf},
        follow_redirects=False,
    ).status_code == 400
    assert report_rows(settings)[0]["status"] == "open"


def test_filing_from_the_review_bench_is_acknowledged_there(tmp_path: Path):
    """The handler redirects to `#issue-reports`.  The review page used to
    render the modal but never the list, so that anchor did not exist: the
    reporter pressed Send, the page came back identical, and the only sane
    conclusion was that the button was broken."""
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    bench = "/review?state=open&document=doc-1"

    response = client.post(
        "/documents/doc-1/issues",
        data={"category": "wrong_unit", "expected_text": "фл", "next": bench, "csrf_token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("#issue-reports")

    body = client.get(bench).text
    assert 'id="issue-reports"' in body, "the anchor the redirect points at does not exist"
    assert "фл" in body


def test_document_page_offers_the_button_and_lists_the_report(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    body = client.get("/documents/doc-1").text
    # Entry points before any report exists: per-row and document-level.
    assert body.count("data-report-issue") >= 2
    assert 'id="an-report-dialog"' in body
    assert 'id="issue-reports"' not in body  # no empty section advertised

    file_report(client, csrf, observation_id="obs-0", category="wrong_unit", expected_text="фл")
    body = client.get("/documents/doc-1").text
    assert 'id="issue-reports"' in body
    assert "LDL cholesterol" in body
    assert "фл" in body
