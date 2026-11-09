"""/plan-tests/cart/synevo: the planned items go to the person's Synevo cart,
in the planned city; the page shows what was taken, why anything was not,
and the total with the blood draw counted once.  Synevo is stubbed."""

from __future__ import annotations

from fastapi.testclient import TestClient

from anamna import labsync
from anamna.db import connect, migrate, utc_now
from anamna.labsync import synevo_shop
from anamna.security import create_session, create_user
from anamna.web.app import create_app

from test_web_panels import PASSWORD, settings_for

DRAW = {"id": "synevo:intake:6001", "name": "Взяття крові", "price": 90.0}


def synevo_item(code, price):
    return {"id": code, "code": code, "name": f"Test {code}", "url": None, "price": price, "final_price": price,
            "discount_pct": 0.0, "fees": [DRAW], "parameters": [{"id": code, "name": f"Test {code}"}],
            "synonyms": [], "sex": None, "order": {"code": code}}


def test_cart_takes_the_plan_in_its_city(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "cart@example.test", "Cart", PASSWORD)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Test Person', '1990-01-01', 'male', ?)""", (f"p-{user_id}", user_id, utc_now()))
    labsync.save_provider_settings(settings, "synevo", enabled=True, url="http://127.0.0.1:9")
    items = [synevo_item("1004", 350.0), synevo_item("1085", 300.0)]
    monkeypatch.setattr(synevo_shop, "catalog", lambda settings, region: items)
    calls = []

    def add(settings, user, chosen, *, region=None):
        calls.append((user, [item["code"] for item in chosen], region))
        return {"added": [{"id": "1004"}], "failed": [{"id": "1085", "name": "Test 1085", "reason": "synevo_cart.in_package"}],
                "cart_url": "https://www.synevo.ua/ordering"}

    monkeypatch.setattr(synevo_shop, "add_to_cart", add)
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "en")
    with connect(settings) as connection:
        csrf = connection.execute("SELECT csrf_token FROM sessions WHERE user_id=?", (user_id,)).fetchone()[0]

    reply = client.post("/plan-tests/cart/synevo", data={
        "csrf_token": csrf, "region": synevo_shop.DEFAULT_REGION, "plan_query": "touched=1&plan=1",
        "item": ["1004", "1085"]})
    assert reply.status_code == 200
    assert calls == [(user_id, ["1004", "1085"], synevo_shop.DEFAULT_REGION)]
    # Only what Synevo took is listed and summed, the draw once: 350 + 90.
    assert "Total: 440 UAH" in reply.text
    assert "already part of a panel in your cart" in reply.text
    assert "https://www.synevo.ua/ordering" in reply.text


def test_cart_refuses_without_csrf(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "cart2@example.test", "Cart", PASSWORD)
    labsync.save_provider_settings(settings, "synevo", enabled=True, url="http://127.0.0.1:9")
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    assert client.post("/plan-tests/cart/synevo", data={"csrf_token": "wrong", "item": ["1004"]}).status_code == 403
