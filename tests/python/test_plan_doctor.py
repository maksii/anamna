"""/plan-tests for a doctor (a guest credential): plans, never orders, saves the
selection for the patient, who opens it, reviews it and orders.  A record
shared with another account orders through a lab account that holds its owner."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from anamna import labsync, testplan
from anamna.db import connect, utc_now
from anamna.labsync import esculab_shop
from anamna.security import create_access_token, create_session, create_user
from anamna.web import testplan_routes
from anamna.web.app import create_app

from test_plan_page_edit import CATALOGUE
from test_testplan import PASSWORD, card, record  # noqa: F401 -- record is a fixture


@pytest.fixture
def app_for(record, monkeypatch):  # noqa: F811
    settings, user_id = record
    labsync.save_provider_settings(settings, "esculab", enabled=True, url="http://127.0.0.1:9")
    for key in [k for k in testplan_routes.SHOPS if k != "esculab"]:
        monkeypatch.delitem(testplan_routes.SHOPS, key)
    monkeypatch.setattr(testplan_routes, "_lab_items", lambda *args: [dict(i) for i in CATALOGUE])
    monkeypatch.setattr(esculab_shop, "regions", lambda settings, base_url=None: [{"id": "3201", "name": "Львів"}])
    monkeypatch.setattr(esculab_shop, "details", lambda settings, ids, base_url=None: {})
    monkeypatch.setattr("anamna.web.app._metric_catalog", lambda connection, owner: [
        {**card("ferritin", category="iron", state="overdue"), "name": "Ferritin"}])
    monkeypatch.setattr(testplan, "lab_concepts", lambda connection, owner: {"ferritin"})
    return settings, user_id, create_app(settings)


def owner_client(app, settings, user_id):
    client = TestClient(app)
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "en")
    return client


def doctor_client(app, settings, user_id):
    expires = (datetime.now(UTC) + timedelta(days=14)).isoformat()
    _, secret = create_access_token(settings, user_id, "guest", "Dr Kovalenko", expires_at=expires)
    client = TestClient(app)
    client.cookies.set("anamna_lang", "en")
    assert client.get(f"/t/{secret}", follow_redirects=False).status_code == 303
    return client


def csrf(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def test_a_doctor_plans_saves_for_the_patient_and_never_orders(app_for):
    settings, user_id, app = app_for
    doctor = doctor_client(app, settings, user_id)
    page = doctor.get("/plan-tests?touched=1&need=ferritin&need=tsh&plan=1")
    assert page.status_code == 200
    html = page.text
    assert "You are viewing as the patient&#39;s doctor" in html and "Save for the patient" in html
    assert 'action="/plan-tests/order/esculab"' not in html and "/plan-tests/cart/synevo" not in html
    # The token is in the save form's body, never in the planner's address.
    assert 'id="plan-suggest" action="/plan-tests/suggest" method="post"' in html
    assert "csrf_token" not in html[html.index('data-plan-form'):html.index('</form>', html.index('data-plan-form'))]
    # Ordering is refused by the server, not merely hidden.
    assert doctor.post("/plan-tests/order/esculab", data={"csrf_token": csrf(html)}).status_code == 403
    assert doctor.get("/allergy").status_code == 200 and doctor.get("/vaccinations").status_code == 200

    saved = doctor.post("/plan-tests/suggest", data={
        "csrf_token": csrf(html), "query": "touched=1&need=ferritin&need=tsh&q=x&plan=1&put=esculab:4"},
        follow_redirects=False)
    assert saved.status_code == 303 and "notice=suggestion_saved" in saved.headers["location"]
    with connect(settings) as connection:
        row = connection.execute("SELECT * FROM plan_suggestions WHERE owner_user_id=?", (user_id,)).fetchone()
    assert row["query"] == "touched=1&need=ferritin&need=tsh&put=esculab%3A4"
    assert row["test_count"] == 2 and row["author"] == "Dr Kovalenko" and row["token_id"]
    assert "Saved. The patient will see this selection" in doctor.get(saved.headers["location"]).text

    empty = doctor.post("/plan-tests/suggest", data={"csrf_token": csrf(html), "query": "touched=1"},
                        follow_redirects=False)
    assert "notice=suggestion_empty" in empty.headers["location"]


def test_the_patient_opens_or_dismisses_the_doctors_selection(app_for):
    settings, user_id, app = app_for
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO plan_suggestions(id, owner_user_id, query, test_count, author, created_at)
               VALUES ('s1', ?, 'touched=1&need=ferritin', 1, 'Dr Kovalenko', ?)""", (user_id, utc_now()))
    owner = owner_client(app, settings, user_id)
    html = owner.get("/plan-tests").text
    assert "Your doctor&#39;s selection" in html and "Dr Kovalenko" in html and "1 result" in html
    assert 'href="/plan-tests?touched=1&amp;need=ferritin&amp;plan=1#plan-result"' in html
    # The owner may not save as a doctor.
    assert owner.post("/plan-tests/suggest", data={"csrf_token": csrf(html), "query": "need=x"}).status_code == 403

    owner.cookies.set("anamna_lang", "uk")
    assert "Вибір вашого лікаря" in owner.get("/plan-tests").text
    gone = owner.post("/plan-tests/suggestion/s1/dismiss", data={"csrf_token": csrf(html)}, follow_redirects=False)
    assert gone.status_code == 303
    assert "Вибір вашого лікаря" not in owner.get("/plan-tests").text


def test_a_doctor_cannot_see_the_patients_saved_selections(app_for):
    settings, user_id, app = app_for
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO plan_suggestions(id, owner_user_id, query, test_count, author, created_at)
               VALUES ('s1', ?, 'touched=1&need=ferritin', 1, 'Dr Other', ?)""", (user_id, utc_now()))
    html = doctor_client(app, settings, user_id).get("/plan-tests").text
    assert "Dr Other" not in html and "/dismiss" not in html


def test_suggestion_query_keeps_the_selection_and_drops_searches():
    raw = "touched=1&need=a&q=ferr&sq=x&sp=2&plan=1&notice=x&olab=esculab&oq=t&alt_esculab=2&cut=esculab:1&ex=urine"
    assert testplan_routes.suggestion_query(raw) == "touched=1&need=a&alt_esculab=2&cut=esculab%3A1&ex=urine"


def test_a_shared_record_orders_through_an_account_that_holds_its_owner(record):  # noqa: F811
    settings, owner_id = record
    viewer_id = create_user(settings, "viewer@example.test", "Viewer", PASSWORD)

    def link(account, target, person, consent):
        with connect(settings) as connection:
            connection.execute(
                """INSERT INTO lab_person_links(account_user_id, provider, remote_person_id, remote_person_json,
                       target_user_id, consent, mismatch_confirmed, created_at, updated_at)
                   VALUES (?, 'esculab', ?, '{}', ?, ?, 0, ?, ?)""",
                (account, person, target, consent, utc_now(), utc_now()))

    order = testplan_routes._order_account
    assert order(settings, owner_id, owner_id, "esculab") == (owner_id, None)
    link(owner_id, owner_id, "p-own", "owner")
    assert order(settings, owner_id, owner_id, "esculab") == (owner_id, "p-own")
    # Shared: the owner's own account, unless the viewer's account holds them.
    assert order(settings, viewer_id, owner_id, "esculab") == (owner_id, "p-own")
    link(viewer_id, owner_id, "p-family", "asked")
    assert order(settings, viewer_id, owner_id, "esculab") == (owner_id, "p-own")
    with connect(settings) as connection:
        connection.execute("UPDATE lab_person_links SET consent='accepted' WHERE remote_person_id='p-family'")
    assert order(settings, viewer_id, owner_id, "esculab") == (viewer_id, "p-family")
