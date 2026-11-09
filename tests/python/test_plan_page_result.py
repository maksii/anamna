"""/plan-tests result: one compact tile per lab, the fuller options say what
they buy and which results those are."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from anamna import labsync, testplan
from anamna.labsync import esculab_shop
from anamna.security import create_session
from anamna.web import testplan_routes
from anamna.web.app import create_app

from test_testplan import card, item, record  # noqa: F401 -- record is a fixture


def test_option_view_names_the_results_an_option_adds():
    cheapest = {"cost": 180.0, "extra_keys": ["a", "gone"], "tracked_extra": [], "items": [item(1, ["x", "a", "gone"], 100)]}
    sub = item(7, ["x", "esculab:9"], 150, params=[{"id": "x", "name": "x"}, {"id": "9", "name": "кількість"}])
    sub["name"] = "Загальний аналіз сечі"
    option = {"cost": 260.0, "extra_keys": ["a", "b", "c", "esculab:9", "whole:копрограма"], "tracked_extra": ["c"],
              "items": [sub]}
    names = {"a": "Alpha", "b": "Beta", "c": "Gamma", "gone": "Delta", "esculab:9": "кількість"}
    view = testplan_routes._option_view(1, option, cheapest, names, chosen=0)
    assert view["delta"] == 80.0 and not view["chosen"]
    # What the record already holds first, each marked; then the page's
    # alphabetical order (Ukrainian before Latin).
    assert [row["name"] for row in view["gained"]] == ["Gamma", "кількість", "Копрограма", "Beta"]
    assert [row["tracked"] for row in view["gained"]] == [True, False, False, False]
    assert view["tracked_count"] == 1
    # A lab's own sub-row is named with the test it belongs to.
    assert [row["source"] for row in view["gained"]] == ["", "Загальний аналіз сечі", "", ""]
    assert view["lost"] == ["Delta"]


@pytest.fixture
def plan_client(record, monkeypatch):  # noqa: F811
    settings, user_id = record
    labsync.save_provider_settings(settings, "esculab", enabled=True, url="http://127.0.0.1:9")
    for key in [k for k in testplan_routes.SHOPS if k != "esculab"]:
        monkeypatch.delitem(testplan_routes.SHOPS, key)
    # The single test covers the list; the panel brings two more results for 40 UAH more.
    catalogue = [item(1, ["ferritin"], 100), item(2, ["ferritin", "transferrin", "iron"], 140)]
    monkeypatch.setattr(testplan_routes, "_lab_items", lambda *args: catalogue)
    monkeypatch.setattr(esculab_shop, "regions", lambda settings, base_url=None: [{"id": "3201", "name": "Львів"}])
    monkeypatch.setattr(esculab_shop, "details", lambda settings, ids, base_url=None: {})
    monkeypatch.setattr("anamna.web.app._metric_catalog", lambda connection, owner: [
        {**card("ferritin", category="iron"), "name": "Ferritin"}])
    monkeypatch.setattr(testplan, "lab_concepts", lambda connection, owner: {"ferritin", "iron"})
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "en")
    return client


def test_a_plan_is_a_tile_whose_options_say_what_they_buy(plan_client):
    page = plan_client.get("/plan-tests?touched=1&need=ferritin&plan=1").text
    assert 'id="plan-esculab"' in page and 'class="an-plan-tile"' in page and "an-plan-how" not in page
    # The summary carries what a person compares; one lab, so it opens.
    assert "180 UAH" in page and "Covers 1 of 1" in page and "1 item" in page and "1 fuller option" in page
    assert '<details class="an-plan-tile" open>' in page
    assert "+40 UAH</strong>: 2 more results, 1 of them measured before" in page
    assert "Which results" in page and "measured before</span>" in page
    assert "alt_esculab=2#plan-esculab" in page

    switched = plan_client.get("/plan-tests?touched=1&need=ferritin&plan=1&alt_esculab=2").text
    assert "Fuller option shown, +40 UAH" in switched and "Cheapest plan" in switched and "Shown now" in switched

    plan_client.cookies.set("anamna_lang", "uk")
    uk = plan_client.get("/plan-tests?touched=1&need=ferritin&plan=1").text
    assert "Охоплює 1 з 1" in uk and "Є 1 повніший варіант" in uk
    assert "ще 2 показники, з них 1 ви вже здавали" in uk and "Які саме показники" in uk


def test_a_split_between_labs_is_a_tile_that_names_its_cost(record, monkeypatch):  # noqa: F811
    from anamna.labsync import synevo_shop

    settings, user_id = record
    for key in ("esculab", "synevo"):
        labsync.save_provider_settings(settings, key, enabled=True, url="http://127.0.0.1:9")
    monkeypatch.setitem(testplan_routes.SHOPS, "synevo", synevo_shop)
    labs = {"esculab": [item(1, ["ferritin"], 100), item(2, ["iron"], 400)],
            "synevo": [item(3, ["ferritin"], 400, lab="synevo"), item(4, ["iron"], 100, lab="synevo")]}
    monkeypatch.setattr(testplan_routes, "_lab_items", lambda settings, connection, owner, key, region: labs[key])
    for module in (esculab_shop, synevo_shop):
        monkeypatch.setattr(module, "regions", lambda settings, base_url=None: [{"id": "1", "name": "Львів"}])
    monkeypatch.setattr(esculab_shop, "details", lambda settings, ids, base_url=None: {})
    monkeypatch.setattr("anamna.web.app._metric_catalog", lambda connection, owner: [])
    monkeypatch.setattr(testplan, "lab_concepts", lambda connection, owner: set())
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "en")
    page = client.get("/plan-tests?touched=1&need=ferritin&need=iron&plan=1").text
    # 100 + 100 + two draws beats 580 at either lab: the split comes first, closed like the rest.
    assert page.index('id="plan-mixed"') < page.index('id="plan-esculab"') < page.index('id="plan-synevo"')
    assert page.count('<details class="an-plan-tile">') == 3
    assert "220 UAH cheaper than a single lab, but you visit two labs and pay for sample collection twice." in page
    assert "Order each part from that lab&#39;s own plan on this page." in page
