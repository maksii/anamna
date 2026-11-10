"""Found in your documents: the page, the scan job and the accept and dismiss routes.

The reading of the documents is replaced at its seam, and the AI switch is
set by hand, so nothing here reaches a model.
"""

from __future__ import annotations

import threading
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from anamna import ai, factor_jobs, factor_scan, security
from anamna.db import connect, migrate, utc_now
from anamna.i18n import format_date_localized
from anamna.security import create_access_token, create_user
from anamna.web.app import create_app

from test_web_profile import csrf_for, login
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for

@pytest.fixture(autouse=True)
def fresh_state():
    security._attempts.clear()
    factor_jobs.reset()
    yield
    security._attempts.clear()
    factor_jobs.reset()


@dataclass
class World:
    settings: object
    alpha: str
    bravo: str
    document: str


@pytest.fixture
def world(tmp_path) -> World:
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    bravo = create_user(settings, "bravo@example.test", "Bravo", PASSWORD)
    patient = seed_patient(settings, alpha, "Alpha Patient")
    seed_patient(settings, bravo, "Bravo Patient")
    document = seed_document(settings, alpha, patient, "Alpha consultation", "alpha-consult.txt")
    with connect(settings) as connection:
        connection.execute(
            "UPDATE documents SET clinical_type = 'consultation', report_date = ? WHERE id = ?",
            (date.today().isoformat(), document),
        )
        connection.commit()
    return World(settings, alpha, bravo, document)


@pytest.fixture
def clients(world):
    """Opens clients that stay signed in for the length of the test."""
    with ExitStack() as stack:
        def open_as(email: str) -> TestClient:
            client = stack.enter_context(TestClient(create_app(world.settings)))
            login(client, email)
            return client

        yield open_as


def csrf(world: World, client: TestClient) -> str:
    return csrf_for(world.settings, client)


def entry_fields(**overrides) -> dict:
    data = {
        "kind": "medicine", "name": "Lisinopril", "strength": "10 мг", "dose": "1 таблетка",
        "schedule": "щоранку", "status": "current", "started_on": "2025-01-10", "ended_on": "",
        "reason": "Тиск", "prescriber": "Лікар", "notes": "Переношу добре",
        "substance": "lisinopril", "atc_code": "C09AA03",
        "reference_name": "Lisinopril", "reference_code": "8311",
    }
    data.update(overrides)
    return data


def add_candidate(world: World, name: str, *, kind: str = "medicine", quote: str | None = None,
                  timing: str = "now", event_date: str | None = None, date_exact: int = 0) -> None:
    """A mention the reader found in the owner's consultation, not yet offered or decided."""
    with connect(world.settings) as connection:
        connection.execute(
            """INSERT INTO factor_candidates(
                   id, owner_user_id, document_id, kind, name, name_key, quote, state, created_at,
                   timing, event_date, date_exact)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)""",
            (f"cand-{kind}-{name.lower()}", world.alpha, world.document, kind, name, name.lower(),
             quote or f"Take {name} daily", utc_now(), timing, event_date, date_exact),
        )
        connection.commit()


def candidate_states(world: World) -> dict[str, str]:
    with connect(world.settings) as connection:
        return {
            row["name_key"]: row["state"]
            for row in connection.execute("SELECT name_key, state FROM factor_candidates")
        }


def factor_named(world: World, name: str):
    with connect(world.settings) as connection:
        return connection.execute("SELECT * FROM factors WHERE name = ?", (name,)).fetchone()


def scan_started(world: World, owner, *, extra_fields: dict | None = None):
    return owner.post("/medicines/found/scan", data={"csrf_token": csrf(world, owner), **(extra_fields or {})})


def test_the_page_lists_a_new_candidate_and_keeps_the_existing_one_unticked(world, clients):
    alpha = clients("alpha@example.test")
    create = alpha.post("/medicines", data={**entry_fields(), "csrf_token": csrf(world, alpha)},
                        follow_redirects=False)
    assert create.status_code == 303
    add_candidate(world, "Amlodipine", quote="Amlodipine 5 mg daily")
    add_candidate(world, "Lisinopril", quote="Lisinopril 10 mg each morning")

    response = alpha.get("/medicines/found")
    assert response.status_code == 200
    page = response.text
    assert "Amlodipine" in page
    assert "Amlodipine 5 mg daily" in page
    assert '<span class="pill">Medicine</span>' in page
    assert 'name="status:medicine:amlodipine"' in page
    assert 'href="/documents/doc-alpha-consult.txt"' in page
    assert 'value="medicine:amlodipine" checked' in page

    existing = page.split('class="an-found-existing"', 1)[1]
    assert "Lisinopril" in existing
    assert 'value="medicine:lisinopril"' in existing
    assert 'value="medicine:lisinopril" checked' not in page


def test_a_date_given_only_by_its_year_shows_as_an_approximate_year(world, clients):
    alpha = clients("alpha@example.test")
    add_candidate(world, "Appendectomy", kind="procedure", quote="Appendectomy in 2019", timing="past",
                  event_date="2019-01-01", date_exact=0)
    add_candidate(world, "Tonsillectomy", kind="procedure", quote="Tonsillectomy on 2 Feb 2019", timing="past",
                  event_date="2019-02-02", date_exact=1)

    page = alpha.get("/medicines/found").text

    assert "≈ 2019" in page
    assert "01 Jan 2019" not in page
    # Control: a date the document gave in full still prints as a full date.
    assert format_date_localized("2019-02-02") in page


def test_the_page_shows_the_unread_count_and_the_button_only_when_ai_is_on(world, clients, monkeypatch):
    alpha = clients("alpha@example.test")

    monkeypatch.setattr(ai, "ai_active", lambda settings, feature: True)
    on = alpha.get("/medicines/found").text
    assert "1 of 1 documents" in on
    assert "data-found-start" in on
    assert "Read my documents" in on
    assert "AI assistant is not set up" not in on

    monkeypatch.setattr(ai, "ai_active", lambda settings, feature: False)
    off = alpha.get("/medicines/found").text
    assert "The AI assistant is not set up on this server" in off
    assert "data-found-start" not in off
    assert "Read my documents" not in off


def test_a_guest_and_a_share_viewer_are_turned_away(world, clients):
    alpha = clients("alpha@example.test")
    alpha.post("/profile/shares", data={"email": "bravo@example.test", "csrf_token": csrf(world, alpha)})
    bravo = clients("bravo@example.test")
    bravo.post("/profile/view", data={"owner_user_id": world.alpha, "csrf_token": csrf(world, bravo)})

    expires = (datetime.now(UTC) + timedelta(days=14)).replace(microsecond=0).isoformat()
    _, secret = create_access_token(world.settings, world.alpha, kind="guest", label="doctor", expires_at=expires)
    with TestClient(create_app(world.settings)) as guest:
        assert guest.get(f"/t/{secret}", follow_redirects=False).status_code in (302, 303)
        for viewer in (guest, bravo):
            page = viewer.get("/medicines/found", follow_redirects=False)
            assert page.status_code in (302, 303)
            assert page.headers["location"] == "/medicines"
            assert viewer.post("/medicines/found/scan", data={"csrf_token": "x"}).status_code == 403
            assert viewer.get("/medicines/found/scan/some-job").status_code == 403
            assert viewer.post("/medicines/found", data={"csrf_token": "x", "action": "dismiss",
                                                         "key": "medicine:x"}).status_code == 403


def test_the_scan_is_a_job_that_reports_its_progress(world, clients, monkeypatch):
    alpha = clients("alpha@example.test")
    monkeypatch.setattr(ai, "ai_active", lambda settings, feature: False)
    assert scan_started(world, alpha).json() == {"error": "disabled"}

    monkeypatch.setattr(ai, "ai_active", lambda settings, feature: True)
    with connect(world.settings) as connection:
        connection.execute(
            "INSERT INTO factor_scans(document_id, owner_user_id, scanned_at, model, found) VALUES (?, ?, ?, 'test', 0)",
            (world.document, world.alpha, utc_now()),
        )
        connection.commit()
    assert scan_started(world, alpha).json() == {"error": "lost"}
    with connect(world.settings) as connection:
        connection.execute("DELETE FROM factor_scans WHERE document_id = ?", (world.document,))
        connection.commit()

    release = threading.Event()
    reported = threading.Event()

    def blocked(settings, connect_, owner_id, *, locale, report=None):
        report(1, 3)
        reported.set()
        release.wait(10)
        return {"stored": 0}

    monkeypatch.setattr(factor_scan, "scan", blocked)
    job = scan_started(world, alpha).json()["job"]
    assert reported.wait(10)
    status = alpha.get(f"/medicines/found/scan/{job}").json()
    assert status == {"state": "running", "error": "", "done": 1, "total": 3}
    assert scan_started(world, alpha).json()["job"] == job

    release.set()
    factor_jobs.join(job)
    assert alpha.get(f"/medicines/found/scan/{job}").json()["state"] == "done"


def test_a_scan_status_is_lost_for_an_unknown_foreign_or_research_job(world, clients):
    alpha = clients("alpha@example.test")
    bravo = clients("bravo@example.test")
    lost = {"state": "failed", "error": "lost", "done": 0, "total": 0}

    assert alpha.get("/medicines/found/scan/no-such-job").json() == lost

    scan = factor_jobs.start(world.alpha, lambda report: {"stored": 0}, kind="scan", with_progress=True)
    factor_jobs.join(scan)
    assert bravo.get(f"/medicines/found/scan/{scan}").json() == lost
    assert alpha.get(f"/medicines/found/scan/{scan}").json()["state"] == "done"

    research = factor_jobs.start(world.alpha, lambda: {"ok": True})
    factor_jobs.join(research)
    assert alpha.get(f"/medicines/found/scan/{research}").json() == lost


def test_accepting_the_ticked_keys_creates_entries_and_leaves_the_rest(world, clients):
    alpha = clients("alpha@example.test")
    add_candidate(world, "Amlodipine")
    add_candidate(world, "Losartan")
    add_candidate(world, "Metformin")

    response = alpha.post("/medicines/found", data={
        "csrf_token": csrf(world, alpha), "action": "accept",
        "key": ["medicine:amlodipine", "medicine:losartan"],
        "status:medicine:losartan": "past",
    }, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/medicines/found?saved=found_added"
    assert "Added to your list." in alpha.get(response.headers["location"]).text

    listing = alpha.get("/medicines").text
    assert "Amlodipine" in listing and "Losartan" in listing
    assert "Metformin" not in listing
    assert factor_named(world, "Losartan")["status"] == "past"
    assert factor_named(world, "Amlodipine")["status"] == "current"

    assert candidate_states(world) == {"amlodipine": "accepted", "losartan": "accepted", "metformin": "new"}
    with connect(world.settings) as connection:
        audited = connection.execute(
            "SELECT entity_id, details_json FROM audit_events WHERE action = 'factor.create' ORDER BY id"
        ).fetchall()
    assert sorted(row["entity_id"] for row in audited) == sorted(
        row["id"] for row in (factor_named(world, "Amlodipine"), factor_named(world, "Losartan"))
    )
    assert all('"source": "documents"' in row["details_json"] for row in audited)
    assert "Metformin" in alpha.get("/medicines/found").text


def test_dismissing_removes_the_ticked_items_from_the_page(world, clients):
    alpha = clients("alpha@example.test")
    add_candidate(world, "Metformin")
    add_candidate(world, "Losartan")

    response = alpha.post("/medicines/found", data={
        "csrf_token": csrf(world, alpha), "action": "dismiss", "key": ["medicine:metformin"],
    }, follow_redirects=False)
    assert response.headers["location"] == "/medicines/found?saved=found_dismissed"

    page = alpha.get(response.headers["location"]).text
    assert "Dismissed. These will not be offered again." in page
    assert "Metformin" not in alpha.get("/medicines/found").text
    assert "Losartan" in alpha.get("/medicines/found").text
    assert candidate_states(world) == {"metformin": "dismissed", "losartan": "new"}


def test_no_keys_a_missing_csrf_token_and_an_unknown_action_are_refused(world, clients):
    alpha = clients("alpha@example.test")
    add_candidate(world, "Amlodipine")

    none = alpha.post("/medicines/found", data={"csrf_token": csrf(world, alpha), "action": "accept"},
                      follow_redirects=False)
    assert none.headers["location"] == "/medicines/found?error=found_none"
    assert "Tick at least one item first." in alpha.get(none.headers["location"]).text

    assert alpha.post("/medicines/found", data={
        "csrf_token": "x", "action": "accept", "key": ["medicine:amlodipine"],
    }).status_code == 403

    assert alpha.post("/medicines/found", data={
        "csrf_token": csrf(world, alpha), "action": "explode", "key": ["medicine:amlodipine"],
    }).status_code == 400
    assert candidate_states(world) == {"amlodipine": "new"}
