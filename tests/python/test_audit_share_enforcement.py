"""A share's access level, enforced where it matters.

A person a record is shared with reads it under the owner's grant.  Read-only
(``access='read'``) they may not ask the assistant about it, and may not order
or fill a lab cart for its owner; they may save a selection for the owner, as a
doctor does.  A full share keeps today's behaviour.  Also here: an order form is
spent once, and an access token never places an order.  The assistant is
scripted and both labs are faked, so nothing reaches a provider or a laboratory.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from anamna import labsync
from anamna.db import connect, utc_now
from anamna.labsync import esculab_shop
from anamna.labsync.common import LabSyncError
from anamna.security import create_access_token, create_user
from anamna.web.app import create_app

from test_chat import Scripted, _ai_on
from test_plan_doctor import app_for, owner_client  # noqa: F401 -- app_for is a fixture
from test_testplan import record  # noqa: F401 -- record is a fixture
from test_web_panels import PASSWORD, build
from test_web_profile import csrf_for

READER = "reader@example.test"


def viewer(settings, owner_id: str, access: str) -> TestClient:
    """A signed-in account the owner shares the record with, switched to that record."""
    grantee = create_user(settings, READER, "Reader", PASSWORD)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO record_shares(id, owner_user_id, grantee_email, grantee_user_id, created_at, access)
               VALUES (?, ?, ?, ?, ?, ?)""", (f"share-{access}", owner_id, READER, grantee, utc_now(), access))
    client = TestClient(create_app(settings))
    client.cookies.set("anamna_lang", "en")
    # Not followed: the dashboard is not what these tests look at, and the planner's stubbed metric catalogue
    # does not carry every field the dashboard reads.
    signed_in = client.post("/login", data={"email": READER, "password": PASSWORD, "next": "/"}, follow_redirects=False)
    assert signed_in.status_code == 303
    switched = client.post("/profile/view", data={"owner_user_id": owner_id, "csrf_token": csrf_for(settings, client)},
                           follow_redirects=False)
    assert switched.status_code == 303
    return client


# --- the assistant --------------------------------------------------------------------


def test_a_read_only_share_is_never_asked_about_the_record(tmp_path, monkeypatch):
    settings, owner, _owner_client = build(tmp_path)
    _ai_on(settings, monkeypatch, [("Should not be said.", [])])
    reader = viewer(settings, owner, "read")

    page = reader.get("/chat").text
    assert "read-only, so the assistant cannot be asked about it" in page
    assert "data-chat-composer" not in page and "<textarea" not in page
    assert "You are asking about the record" not in page

    refused = reader.post("/chat/send", data={"csrf_token": csrf_for(settings, reader), "message": "My LDL?"},
                          follow_redirects=False)
    assert refused.status_code == 403 and "Read-only access" in refused.text
    assert Scripted.systems == []  # the model was never called
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM chat_conversations").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0


def test_a_full_share_asks_the_assistant_as_before(tmp_path, monkeypatch):
    settings, owner, owner_client_ = build(tmp_path)
    _ai_on(settings, monkeypatch, [("Your answer.", [])])
    reader = viewer(settings, owner, "full")

    page = reader.get("/chat").text
    assert "You are asking about the record" in page and "data-chat-composer" in page
    sent = reader.post("/chat/send", data={"csrf_token": csrf_for(settings, reader), "message": "My LDL?"},
                       follow_redirects=False)
    assert sent.status_code == 303 and len(Scripted.systems) == 1
    assert "data-chat-composer" in owner_client_.get("/chat").text


# --- ordering -------------------------------------------------------------------------


def good(good_id: int, name: str, price: float) -> dict:
    return esculab_shop.item({
        "id": good_id, "name": name, "code": f"F{good_id}", "price": price, "discount": 0.0,
        "path": f"/test-{good_id}", "opt": [], "info": {}, "configs": [{"id": 7000 + good_id}],
        "parameters": [{"id": 900 + good_id, "name": name}],
        "takes": [{"id": 370, "name": "Blood draw", "price": 80.0, "discount": 0.0}],
    })


ITEMS = [good(1, "Ferritin panel", 300.0), good(2, "TSH", 150.0)]
#: The total the page would show: both tests and the one blood draw they share.
EXPECTED = round(sum(item["final_price"] for item in ITEMS) + sum(fee["price"] for fee in esculab_shop.fees(ITEMS)), 2)


def order_data(token: str, nonce: str | None = None) -> dict:
    data = {"csrf_token": token, "region": "3201", "plan_query": "touched=1&plan=1", "expected": str(EXPECTED),
            "item": ["1", "2"], "point": "193", "date": "2030-01-02", "payment": "online"}
    if nonce is not None:
        data["order_nonce"] = nonce
    return data


def cart_data(token: str) -> dict:
    return {"csrf_token": token, "region": "3201", "plan_query": "touched=1&plan=1", "item": ["1", "2"]}


@pytest.fixture
def shop(app_for, monkeypatch):
    """The planner of ``app_for``, with the Esculab account, its person and both lab calls faked.

    ``calls`` records what reached the lab: the account clients built and the orders filed."""
    settings, owner, app = app_for
    calls = {"clients": [], "orders": []}
    monkeypatch.setattr(esculab_shop, "catalog", lambda settings, region, base_url=None: ITEMS)
    monkeypatch.setattr(esculab_shop, "refresh_prices", lambda region, items, base_url=None: items)
    monkeypatch.setattr(esculab_shop, "points", lambda settings, region, base_url=None: [{"id": "193", "address": "Lviv", "hours": ""}])
    monkeypatch.setattr(esculab_shop, "last_point", lambda client, person: "193")

    def client(settings, key, secret, phone, refresh=None):
        calls["clients"].append(key)
        return object()

    def create(client, person, point, items, *, online, day=None):
        calls["orders"].append([item["id"] for item in items])
        return {"number": "5001", "payment_url": None}

    monkeypatch.setattr(labsync, "_client", client)
    monkeypatch.setattr(esculab_shop, "create_order", create)
    labsync.save_provider_settings(settings, "synevo", enabled=True, url="http://127.0.0.1:9")
    now = utc_now()
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO lab_accounts(user_id, provider, secret, refresh_secret, phone, updated_at)
               VALUES (?, 'esculab', 'session-token', '', '380500000000', ?)""", (owner, now))
        connection.execute(
            """INSERT INTO lab_person_links(account_user_id, provider, remote_person_id, remote_person_json,
                   target_user_id, consent, mismatch_confirmed, created_at, updated_at)
               VALUES (?, 'esculab', 'p-own', '{}', ?, 'owner', 0, ?, ?)""", (owner, owner, now, now))
    return settings, owner, app, calls


PLAN = "/plan-tests?touched=1&need=ferritin&plan=1"


def test_a_read_only_share_sees_no_order_and_reaches_no_lab(shop):
    settings, owner, _app, calls = shop
    reader = viewer(settings, owner, "read")

    page = reader.get(PLAN).text
    assert "is read-only, so you cannot order tests for them" in page
    assert 'action="/plan-tests/order/esculab"' not in page and 'action="/plan-tests/cart/synevo"' not in page
    assert 'id="plan-suggest"' in page  # it may still save a selection, as a doctor does
    assert calls["clients"] == []  # the account's client is not even built for the page

    token = csrf_for(settings, reader)
    order = reader.post("/plan-tests/order/esculab", data=order_data(token, nonce="read-1"), follow_redirects=False)
    assert order.status_code == 403 and "Read-only access" in order.text
    cart = reader.post("/plan-tests/cart/synevo", data=cart_data(token), follow_redirects=False)
    assert cart.status_code == 403 and "Read-only access" in cart.text
    assert calls == {"clients": [], "orders": []}


def test_a_read_only_share_saves_a_suggestion_the_owner_sees(shop):
    settings, owner, app, _calls = shop
    reader = viewer(settings, owner, "read")

    saved = reader.post("/plan-tests/suggest", data={"csrf_token": csrf_for(settings, reader),
                                                    "query": "touched=1&need=ferritin&plan=1"},
                        follow_redirects=False)
    assert saved.status_code == 303 and "notice=suggestion_saved" in saved.headers["location"]
    with connect(settings) as db:
        rows = db.execute("SELECT owner_user_id, token_id, author FROM plan_suggestions").fetchall()
    assert [(row["owner_user_id"], row["token_id"], row["author"]) for row in rows] == [(owner, None, "Reader")]
    owner_page = owner_client(app, settings, owner).get("/plan-tests").text
    assert "Reader" in owner_page and "/plan-tests/suggestion/" in owner_page


def test_the_owner_cannot_save_a_suggestion_to_their_own_record(shop):
    settings, owner, app, _calls = shop
    client = owner_client(app, settings, owner)
    refused = client.post("/plan-tests/suggest", data={"csrf_token": csrf_for(settings, client), "query": "need=x"},
                          follow_redirects=False)
    assert refused.status_code == 403


def test_a_full_share_orders_through_the_owners_lab_account(shop):
    settings, owner, _app, calls = shop
    reader = viewer(settings, owner, "full")

    page = reader.get(PLAN).text
    assert 'action="/plan-tests/order/esculab"' in page and "is read-only" not in page
    filed = reader.post("/plan-tests/order/esculab", data=order_data(csrf_for(settings, reader), nonce="full-1"),
                        follow_redirects=False)
    assert filed.status_code == 200 and "5001" in filed.text
    # The page built the account's client to offer the form; the order used it to file.
    assert calls["orders"] == [["1", "2"]] and set(calls["clients"]) == {"esculab"}


def test_an_access_token_never_places_an_order(shop):
    settings, owner, app, calls = shop
    _, secret = create_access_token(settings, owner, "agent", "deployment check")
    with TestClient(app) as agent:
        headers = {"Authorization": f"Bearer {secret}"}
        refused = agent.post("/plan-tests/order/esculab", data=order_data("", nonce="bearer-1"), headers=headers,
                             follow_redirects=False)
        cart = agent.post("/plan-tests/cart/synevo", data=cart_data(""), headers=headers, follow_redirects=False)
    assert refused.status_code == 403 and "signed-in browser session" in refused.text
    assert cart.status_code == 403 and "signed-in browser session" in cart.text
    assert calls == {"clients": [], "orders": []}


def test_an_order_form_is_spent_once_and_a_form_without_one_is_not_sent(shop):
    settings, owner, app, calls = shop
    client = owner_client(app, settings, owner)
    token = csrf_for(settings, client)

    first = client.post("/plan-tests/order/esculab", data=order_data(token, nonce="form-1"), follow_redirects=False)
    assert first.status_code == 200 and calls["orders"] == [["1", "2"]]

    again = client.post("/plan-tests/order/esculab", data=order_data(token, nonce="form-1"), follow_redirects=False)
    assert again.status_code == 303 and "notice=order_repeat" in again.headers["location"]
    assert "This order was already submitted" in client.get(again.headers["location"]).text

    bare = client.post("/plan-tests/order/esculab", data=order_data(token), follow_redirects=False)
    assert bare.status_code == 303 and "notice=order_repeat" in bare.headers["location"]
    assert calls["orders"] == [["1", "2"]]
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM lab_order_nonces WHERE user_id=?", (owner,)).fetchone()[0] == 1


def test_an_unreachable_lab_leaves_the_outcome_uncertain_and_the_form_spent(shop, monkeypatch):
    settings, owner, app, calls = shop

    def unreachable(client, person, point, items, *, online, day=None):
        raise LabSyncError("labsync.error_unreachable")

    monkeypatch.setattr(esculab_shop, "create_order", unreachable)
    client = owner_client(app, settings, owner)
    token = csrf_for(settings, client)
    slow = client.post("/plan-tests/order/esculab", data=order_data(token, nonce="slow-1"), follow_redirects=False)
    assert slow.status_code == 303 and "notice=order_uncertain" in slow.headers["location"]
    assert "did not answer in time" in client.get(slow.headers["location"]).text
    retry = client.post("/plan-tests/order/esculab", data=order_data(token, nonce="slow-1"), follow_redirects=False)
    assert "notice=order_repeat" in retry.headers["location"] and calls["orders"] == []


NONCE = re.compile(r'name="order_nonce" value="([^"]+)"')


def test_the_order_form_carries_its_own_nonce_and_a_new_one_per_page(shop):
    settings, owner, app, calls = shop
    client = owner_client(app, settings, owner)

    first = NONCE.search(client.get(PLAN).text)
    assert first and first.group(1)
    filed = client.post("/plan-tests/order/esculab", data=order_data(csrf_for(settings, client), nonce=first.group(1)),
                        follow_redirects=False)
    assert filed.status_code == 200 and len(calls["orders"]) == 1

    second = NONCE.search(client.get(PLAN).text)
    assert second and second.group(1) != first.group(1)
