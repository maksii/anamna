"""'Measure this again' on a result's page: where a laboratory result can be
re-measured and for how much, from the stored price lists.

Every fixture is synthetic; the Esculab price list is stubbed at
``esculab_shop.catalog`` as test_testplan.py does, and nothing reaches a lab.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import labsync, testplan
from anamna.db import connect
from anamna.labsync import esculab_shop
from anamna.security import create_access_token
from anamna.web.app import create_app

from test_web_panels import build


def good(good_id, name, price, parameters, discount=0.0):
    return {"id": good_id, "name": name, "code": f"F{good_id}", "price": price, "discount": discount,
            "path": f"/test-{good_id}", "opt": ["forman", "forwoman", "public"], "info": {},
            "configs": [{"id": 7000 + good_id}], "parameters": [{"id": 900 + n, "name": p} for n, p in enumerate(parameters)],
            "takes": [{"id": 370, "name": "Відбір біоматеріалу", "price": 80.0, "discount": 0.0}]}


CATALOGUE = [
    good(1, "ЛПНЩ", 200.0, ["LDL cholesterol"]),
    # Cheaper than the single test, so it is shown beside it.
    good(2, "Ліпідограма", 220.0, ["LDL cholesterol", "HDL cholesterol"], discount=50.0),
    # Dearer than the single test: not worth showing.
    good(3, "Великий профіль", 900.0, ["LDL cholesterol", "Creatinine"]),
]


@pytest.fixture
def page(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    labsync.save_provider_settings(settings, "esculab", enabled=True, url="http://127.0.0.1:9")
    items = [esculab_shop.item(entry) for entry in CATALOGUE]
    monkeypatch.setattr(esculab_shop, "catalog", lambda settings, region, base_url=None: items)
    return settings, user_id, client


def read_now(monkeypatch):
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    monkeypatch.setattr(testplan, "fetched_at", lambda settings, provider, region, key="catalog": stamp)


def test_shown_for_a_sold_lab_result_with_single_test_panel_and_planner_link(page, monkeypatch):
    settings, user_id, client = page
    read_now(monkeypatch)
    text = client.get("/metrics/ldl-cholesterol").text
    assert 'id="measure-again"' in text and "Where to test and what it costs" in text
    assert "ЛПНЩ" in text and "200 UAH" in text
    # 220 at 50 % off is 110, under the single test; the 900 profile is not shown.
    assert "Ліпідограма" in text and "Cheaper as part of a panel" in text and "110 UAH" in text
    assert "Великий профіль" not in text
    assert "plus 80 UAH for sample collection, once per visit" in text
    assert "https://esculab.com/test-1" in text
    assert 'href="/plan-tests?touched=1&amp;need=ldl-cholesterol&amp;plan=1"' in text
    client.cookies.set("anamna_lang", "uk")
    text = client.get("/metrics/ldl-cholesterol").text
    assert "Де здати і скільки це коштує" in text and "200 грн" in text and "Спланувати цей аналіз" in text
    # The link it gives plans exactly this analyte: the discounted panel and
    # one draw, 110 + 80.
    client.cookies.set("anamna_lang", "en")
    planned = client.get("/plan-tests?touched=1&need=ldl-cholesterol&plan=1").text
    assert "Ліпідограма" in planned and "190 UAH" in planned


def test_hidden_for_a_result_no_laboratory_reported(page, monkeypatch):
    settings, _, client = page
    read_now(monkeypatch)
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET clinical_type='ultrasound'")
    assert 'id="measure-again"' not in client.get("/metrics/ldl-cholesterol").text


def test_hidden_for_a_lab_result_no_lab_sells(page, monkeypatch):
    _, _, client = page
    read_now(monkeypatch)
    assert 'id="measure-again"' not in client.get("/metrics/folate-serum").text


def test_hidden_while_the_catalogue_was_never_read(page):
    # No stored copy: the page says nothing rather than "not sold", and does
    # not wait for the price list (it is read in the background).
    _, _, client = page
    assert 'id="measure-again"' not in client.get("/metrics/ldl-cholesterol").text


def test_a_guest_sees_prices_and_plans_but_never_orders(page, monkeypatch):
    settings, user_id, _ = page
    read_now(monkeypatch)
    _, secret = create_access_token(settings, user_id, "guest", "Doctor", expires_at="2100-01-01T00:00:00+00:00")
    with TestClient(create_app(settings)) as guest:
        guest.cookies.set("anamna_lang", "en")
        guest.get(f"/t/{secret}")
        text = guest.get("/metrics/ldl-cholesterol").text
        assert 'id="measure-again"' in text and "ЛПНЩ" in text
        # A doctor plans the test and saves it for the patient; ordering is refused.
        assert "/plan-tests?" in text
        assert guest.get("/plan-tests").status_code == 200
        assert guest.post("/plan-tests/order/esculab").status_code == 403
        assert guest.post("/plan-tests/cart/synevo").status_code == 403
