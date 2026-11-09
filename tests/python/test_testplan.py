"""The test planner: matching lab items to the record, the cheapest cover,
Esculab's price and order shapes, and the /plan-tests page.

Every fixture is synthetic; HTTP is stubbed at ``labsync.common._http``.
"""

from __future__ import annotations

import itertools
import json
import random
import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from anamna import labsync, testplan
from anamna.db import connect, migrate, utc_now
from anamna.ingest.pipeline import seed_concepts
from anamna.labsync import common, esculab_shop
from anamna.security import create_session, create_user
from anamna.web import testplan_routes
from anamna.web.app import create_app

from test_web_panels import PASSWORD, settings_for


def item(item_id, keys, price, *, final=None, fees=(("draw", 80.0),), lab="esculab", params=None):
    return {"id": str(item_id), "code": f"C{item_id}", "name": f"Item {item_id}", "url": None, "price": float(price),
            "final_price": float(final if final is not None else price), "discount_pct": 0.0,
            "fees": [{"id": f"{lab}:{fee}", "name": fee, "price": cost} for fee, cost in fees],
            "parameters": params or [{"id": k, "name": k} for k in keys], "synonyms": [], "sex": None,
            "order": {"confId": "1"}, "keys": list(keys), "lab": lab}


# --- the optimiser --------------------------------------------------------------


def test_panel_beats_singles_and_the_fee_is_paid_once():
    items = [item(1, ["a"], 100), item(2, ["b"], 100), item(3, ["c"], 100), item(4, ["a", "b", "c", "x"], 250)]
    plan = testplan.optimise(items, {"a", "b", "c"})
    assert [i["id"] for i in plan["items"]] == ["4"]
    assert plan["cost"] == 330.0 and plan["fees_cost"] == 80.0 and plan["exact"]
    assert testplan.separately(items, {"a", "b", "c"}) == 380.0


def test_discounted_singles_beat_the_panel():
    items = [item(1, ["a"], 100, final=60), item(2, ["b"], 100, final=60), item(4, ["a", "b"], 150)]
    plan = testplan.optimise(items, {"a", "b"})
    assert sorted(i["id"] for i in plan["items"]) == ["1", "2"] and plan["cost"] == 200.0
    assert plan["list_cost"] == 280.0


def test_a_second_fee_changes_the_answer():
    # The urine test has no blood draw; the cheaper blood-only route adds one.
    items = [item(1, ["a"], 100, fees=()), item(2, ["a"], 90, fees=(("draw", 80.0),)), item(3, ["b"], 50)]
    plan = testplan.optimise(items, {"a", "b"})
    assert sorted(i["id"] for i in plan["items"]) == ["2", "3"] and plan["cost"] == 220.0


def test_what_no_item_measures_is_reported_not_dropped():
    plan = testplan.optimise([item(1, ["a"], 10)], {"a", "zzz"})
    assert plan["covered"] == ["a"] and plan["missing"] == ["zzz"]


def test_matches_brute_force_on_random_catalogues():
    rng = random.Random(7)
    for _ in range(60):
        keys = [f"k{n}" for n in range(rng.randint(2, 6))]
        fees = [("draw", 80.0), ("urine", 30.0), ("swab", 50.0)]
        items = [item(n, rng.sample(keys, rng.randint(1, len(keys))), rng.randint(50, 900),
                      fees=rng.sample(fees, rng.randint(0, 2)))
                 for n in range(rng.randint(1, 9))]
        required = set(rng.sample(keys, rng.randint(1, len(keys))))
        coverable = required & {k for i in items for k in i["keys"]}
        best = 0.0 if not coverable else None
        for size in range(1, len(items) + 1 if coverable else 1):
            for combo in itertools.combinations(items, size):
                if coverable <= {k for i in combo for k in i["keys"]}:
                    cost = sum(i["final_price"] for i in combo) + sum(
                        {f["id"]: f["price"] for i in combo for f in i["fees"]}.values())
                    best = cost if best is None else min(best, cost)
        plan = testplan.optimise(items, required)
        assert set(plan["covered"]) == coverable
        assert plan["cost"] == pytest.approx(best)


def test_node_limit_still_returns_a_full_cover():
    items = [item(n, [f"k{n % 7}", f"k{(n * 3) % 7}"], 100 + n) for n in range(40)]
    plan = testplan.optimise(items, {f"k{n}" for n in range(7)}, node_limit=3)
    assert set(plan["covered"]) == {f"k{n}" for n in range(7)} and plan["exact"] is False


# --- needs and ordering ---------------------------------------------------------


def card(cid, category="lipids", state="fresh", reading="normal", device=False):
    return {"id": cid, "name": cid, "category": category, "is_device": device,
            "staleness": {"state": state}, "verdict": {"interpretation": reading}}


def test_needs_are_due_or_flagged_lab_results():
    # An echo index and a blood pressure are flagged too, but no laboratory
    # ever reported them: ordering a lab test cannot re-measure them.
    found = testplan.needs([
        card("ldl", reading="high"), card("tsh", state="overdue"), card("ok"),
        card("steps", device=True, reading="low"), card("bp", category="cardiovascular", state="overdue"),
        card("lvmi", category="cardiovascular", reading="high"), card("birch", category="allergy", reading="high"),
    ], {"ldl", "tsh", "ok", "steps", "birch"})
    assert [(n["key"], n["preselected"]) for n in found] == [("ldl", True), ("tsh", True), ("birch", False)]
    assert found[0]["flagged"] and found[1]["due"]


def test_ukrainian_alphabet_order():
    names = ["Іршава", "Берегове", "м. Бурштин", "Ізюм", "Чернівці", "Яворів", "Ґорґани"]
    assert sorted(names, key=testplan.alphabetical) == ["Берегове", "м. Бурштин", "Ґорґани", "Ізюм", "Іршава",
                                                         "Чернівці", "Яворів"]


# --- Esculab's price list and orders --------------------------------------------


GOOD = {"id": 296, "name": "Феритин  (FER)", "code": "F1003", "price": 455.0, "discount": 10.0, "path": "/ferytyn",
        "opt": ["forman", "forwoman", "public"], "info": {"ua_synonyms": "<p>ferritin, феритин</p>"},
        "configs": [{"id": 7308}], "parameters": [{"id": 326, "name": "Феритин"}, {"id": 326, "name": "Феритин"}],
        "takes": [{"id": 370, "name": "Відбір біоматеріалу", "price": 80.0, "discount": 0.0}], "duritionDay": 1}


def test_price_list_good_becomes_an_item():
    found = esculab_shop.item(GOOD)
    # The discount is whole hryvnias, rounded down: 45.5 -> 45.
    assert found["final_price"] == 410.0 and found["price"] == 455.0
    assert found["parameters"] == [{"id": "326", "name": "Феритин"}]
    assert found["url"] == "https://esculab.com/ferytyn" and found["order"] == {"confId": "7308"}
    assert found["synonyms"] == ["ferritin", "феритин"] and found["sex"] is None
    assert found["fees"] == [{"id": "370", "name": "Відбір біоматеріалу", "price": 80.0}]
    assert esculab_shop.item({**GOOD, "opt": ["forwoman"]})["sex"] == "F"
    # No basket button in the app: not offered.
    assert esculab_shop.item({**GOOD, "opt": ["notsale"]}) is None
    assert esculab_shop.item({**GOOD, "price": 0}) is None


class Client:
    base_url, secret, phone = "http://127.0.0.1:9", "jwt", "380000000001"


def test_order_body_matches_the_app(monkeypatch):
    sent = []

    def fake(method, url, *, headers, body=None, **_):
        sent.append((method, url, headers, json.loads(body) if body else None))
        if url.endswith("/api/customers/referral/create"):
            return 200, [], b'{"referralId": 10400001}'
        return 200, [], b'"https:\\/\\/www.liqpay.ua\\/checkout\\/x"'

    monkeypatch.setattr(common, "_http", fake)
    found = esculab_shop.item(GOOD)
    result = esculab_shop.create_order(Client(), "2184432", "193", [found], online=True, day=date(2030, 1, 2))
    assert result == {"number": "10400001", "payment_url": "https://www.liqpay.ua/checkout/x"}
    method, url, headers, body = sent[0]
    assert headers["Authorization"] == "Bearer jwt" and headers["AccessPhone"] == "380000000001"
    assert body["punktId"] == 193 and body["clientId"] == 2184432 and body["payment"] == "CARD"
    assert body["date"].startswith("2030-01-02")
    assert body["services"] == [
        {"goodId": 296, "confId": 7308, "price": 455.0, "discount": 45.0, "amount": 1, "name": "Феритин (FER)"},
        {"goodId": 370, "confId": 0, "price": 80.0, "discount": 0.0, "amount": 1, "name": "Відбір біоматеріалу"},
    ]
    assert sent[1][1] == esculab_shop.PAYMENT_LINK + "10400001"


def test_an_unreadable_payment_reply_is_no_link(monkeypatch):
    monkeypatch.setattr(common, "_http", lambda *a, **k: (200, [], b"<html>nope</html>"))
    assert esculab_shop.payment_link(Client(), "1") is None


# --- matching to the record ------------------------------------------------------


@pytest.fixture
def record(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "plan@example.test", "Plan", PASSWORD)
    with connect(settings) as connection:
        seed_concepts(connection)
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Test Person', '1990-01-01', 'male', ?)""", (f"patient-{user_id}", user_id, utc_now()))
    return settings, user_id


def test_keys_resolve_names_whole_tests_and_specimen(record):
    settings, _ = record
    with connect(settings) as connection:
        aliases, categories = testplan.alias_index(connection), testplan.category_index(connection)
    items = [
        {**esculab_shop.item(GOOD), "id": "1"},
        {**esculab_shop.item(GOOD), "id": "2", "name": "Копрограма", "parameters": [{"id": "9", "name": "Копрограма "}]},
        {**esculab_shop.item(GOOD), "id": "3", "name": "Загальний аналіз сечі",
         "parameters": [{"id": "1106", "name": "Глюкоза (C-GLU)"}, {"id": "990077", "name": "Невідомий показник"}]},
    ]
    keyed = testplan.keyed(items, "esculab", "Esculab", aliases, {}, categories)
    assert keyed[0]["keys"] == ["ferritin"] and keyed[0]["fees"][0]["id"] == "esculab:370"
    assert set(keyed[1]["keys"]) == set(categories["stool"]) and keyed[1]["keys"]
    assert keyed[2]["keys"] == ["urine-glucose", "esculab:990077"]


# --- the page ------------------------------------------------------------------------


def test_page_lists_needs_and_builds_a_plan(record, monkeypatch):
    settings, user_id = record
    labsync.save_provider_settings(settings, "esculab", enabled=True, url="http://127.0.0.1:9")
    for key in [k for k in testplan_routes.SHOPS if k != "esculab"]:
        monkeypatch.delitem(testplan_routes.SHOPS, key)
    catalogue = [esculab_shop.item(GOOD)]
    monkeypatch.setattr(esculab_shop, "catalog", lambda settings, region, base_url=None: catalogue)
    monkeypatch.setattr(esculab_shop, "regions", lambda settings, base_url=None: [{"id": "3201", "name": "Львів"}])
    shown = {"name": "Ferritin", "value_text": "202", "unit": "ng/mL", "date_text": "28 Aug 2025",
             "verdict": {"interpretation": "high", "label": "High"}, "staleness": {"state": "fresh", "label": "Fresh"}}
    monkeypatch.setattr("anamna.web.app._metric_catalog", lambda connection, owner: [
        {**card("ferritin", category="iron"), **shown, "url": "/metrics/ferritin"},
        {**card("lvmi", category="cardiovascular"), **shown, "name": "LV mass index", "url": "/metrics/lvmi"}])
    monkeypatch.setattr(testplan, "lab_concepts", lambda connection, owner: {"ferritin"})
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "en")

    page = client.get("/plan-tests")
    assert page.status_code == 200 and "Ferritin" in page.text and 'value="ferritin" checked' in page.text
    assert "LV mass index" not in page.text

    planned = client.get("/plan-tests?touched=1&need=ferritin&plan=1")
    assert planned.status_code == 200
    assert "490 UAH" in planned.text  # 410 + one 80 UAH draw
    # Not connected to Esculab: no order form, a way to connect instead.
    assert "/plan-tests/order/esculab" not in planned.text and "#lab-esculab" in planned.text

    # Ferritin is on the list (unticked): the search shows that row and adds
    # nothing twice, on the page and in the live reply alike.
    found = client.get("/plan-tests?touched=1&q=ferr")
    assert """data-match='["ferritin"]'""" in found.text
    assert 'name="add" value="ferritin"' not in found.text and "Феритин (FER)" not in found.text
    reply = client.get("/plan-tests/live", params={"touched": "1", "q": "ferr"}).json()
    assert reply["match"] == ["ferritin"]
    client.cookies.set("anamna_lang", "uk")
    assert "490 грн" in client.get("/plan-tests?touched=1&need=ferritin&plan=1").text


# --- what the labs say about each test ----------------------------------------------

RICH = {**GOOD, "nameRu": "Ферритин (FER)", "durationMin": 0, "note": "<p>Відбір з понеділка по п&#39;ятницю</p>",
        "configs": [{"id": 7308, "materials": [{"id": 1, "name": "сироватка крові"}]}, {"id": 1, "materials": []}],
        "info": {"ua_synonyms": "<p>ferritin, феритин</p>",
                 "ua_synonyms_site": "<p>Сироватковий феритин (<span>Serum</span> <span>ferritin</span>); Білок депо заліза</p>"}}


def test_a_good_carries_turnaround_sample_prep_and_search_names():
    found = esculab_shop.item(RICH)
    assert found["days"] == 1 and found["minutes"] is None
    assert found["material"] == ["сироватка крові"]
    # The price list has the point restriction; the rules come from details.
    assert found["prep"] == "Відбір з понеділка по п'ятницю"
    assert "Сироватковий феритин (Serum ferritin)" in found["aka"] and "Ферритин (FER)" in found["aka"]
    # Search-only names stay out of synonyms, which concept matching reads.
    assert found["synonyms"] == ["ferritin", "феритин"]
    express = esculab_shop.item({**RICH, "duritionDay": 0, "durationMin": 15})
    assert express["days"] is None and express["minutes"] == 15
    rules = "<p>Кров відбирається натщесерце (через 8-12 год після прийому їжі).</p>" + "<p>Пийте воду. </p>" * 400
    assert len(esculab_shop.prep({"ua_rules": rules})) <= esculab_shop.PREP_LIMIT
    assert esculab_shop.prep({"ua_rules": rules}).startswith("Кров відбирається натщесерце")


def test_preparation_rules_are_read_once_and_cached(record, monkeypatch):
    settings, _ = record
    calls = []

    def fake(method, url, *, headers, body=None, **_):
        calls.append(url)
        return 200, [], json.dumps({"goodId": 296, "info": {
            "ua_rules": "<p>Кров відбирається натщесерце (через 8-12 год після прийому їжі).</p>"}}).encode()

    monkeypatch.setattr(common, "_http", fake)
    first = esculab_shop.details(settings, ["296", "x"], "http://lab.test")
    # The preparation rules, and what the good's page says it contains (none here).
    assert first == {"296": {"prep": "Кров відбирається натщесерце (через 8-12 год після прийому їжі).",
                             "text": "", "genes": []}}
    assert calls == ["http://lab.test/api/site/price/details/get?goodId=296"]
    assert esculab_shop.details(settings, ["296"], "http://lab.test") == first and len(calls) == 1


def test_prices_are_re_read_from_the_price_list(monkeypatch):
    # The details reply has no price at all, so the list is the only source.
    cheaper = {**GOOD, "discount": 50.0}
    monkeypatch.setattr(common, "_http", lambda *a, **k: (200, [], json.dumps([{"goods": [cheaper]}]).encode()))
    fresh = esculab_shop.refresh_prices("3201", [esculab_shop.item(GOOD), {**esculab_shop.item(GOOD), "id": "9"}])
    assert fresh[0]["final_price"] == 228.0 and fresh[0]["checked"] is True
    assert fresh[1]["checked"] is False and fresh[1]["final_price"] == 410.0


def keyed_item(item_id, keys, price, name, *, groups=(), params=None, **extra):
    return {**item(item_id, keys, price, params=params), "name": name, "groups": list(groups), **extra}


SHELF = [
    keyed_item(1, ["ferritin"], 410, "Феритин (FER)", synonyms=["ferritin"], days=1, material=["сироватка крові"]),
    keyed_item(2, ["mch"], 50, "Середній вміст гемоглобіну (МСН)"),
    keyed_item(3, ["total-cholesterol"], 120, "Холестерин загальний (CHOL)"),
    keyed_item(4, ["total-cholesterol", "ldl", "hdl"], 300, "Пакет №6. Ліпідограма"),
    keyed_item(5, ["esculab:dna"], 9000, "Сімейна гіперхолестеринемія, 4 гени",
               groups=["Генетичні дослідження", "Генетика"], params=[{"id": "dna", "name": "Гени LDLR, APOB"}]),
]
CONCEPTS = {"ferritin": "Ferritin", "mch": "MCH", "total-cholesterol": "Total cholesterol"}


def test_analyte_search_lists_single_results_in_either_language():
    names = {"ferritin": "Ferritin", "mch": "MCH", "total-cholesterol": "Total cholesterol"}

    def labels(text):
        rows, _ = testplan_routes._search(text, [], {"esculab": SHELF}, names, set(), set(), CONCEPTS)
        return [row["label"] for row in rows]

    assert labels("ferritin") == ["Ferritin"] and labels("феритин") == ["Ferritin"]
    assert labels("FER") == ["Ferritin"]
    # A Latin abbreviation printed in Cyrillic lookalikes, and typed either way.
    assert labels("MCH") == ["MCH"] and labels("мсн") == ["MCH"]
    # Neither the genetic panel nor the lipid profile is a cholesterol value.
    assert labels("холестерин") == ["Total cholesterol"] and labels("cholesterol") == ["Total cholesterol"]
    rows, fuzzy = testplan_routes._search("ферритинн", [], {"esculab": SHELF}, names, set(), set(), CONCEPTS)
    assert [row["label"] for row in rows] == ["Ferritin"] and fuzzy
    assert rows[0]["offers"].startswith("Esculab 410")


def test_panels_and_genetic_tests_are_browsed_apart():
    found, _ = testplan_routes._sets("холестерин", "", {"esculab": SHELF}, {}, set(), CONCEPTS)
    # The package measures cholesterol; the gene panel only names it inside a
    # longer word, which is enough here and never in the analyte box.
    assert [(row["name"], row["kind"]) for row in found] == [
        ("Пакет №6. Ліпідограма", "set"), ("Сімейна гіперхолестеринемія, 4 гени", "genetic")]
    shelf, _ = testplan_routes._sets("", "esculab:Генетичні дослідження", {"esculab": SHELF}, {}, {"esculab:5"}, CONCEPTS)
    assert [(row["value"], row["included"]) for row in shelf] == [("esculab:5", True)]
    assert testplan_routes._shelves({"esculab": SHELF}, {}) == [
        {"lab": "esculab", "vendor": "Esculab", "name": "Генетичні дослідження", "count": 1,
         "value": "esculab:Генетичні дослідження"}]


def test_an_included_panel_is_pinned_and_the_rest_planned_around_it(record, monkeypatch):
    settings, user_id = record
    labsync.save_provider_settings(settings, "esculab", enabled=True, url="http://127.0.0.1:9")
    for key in [k for k in testplan_routes.SHOPS if k != "esculab"]:
        monkeypatch.delitem(testplan_routes.SHOPS, key)
    panel = {**esculab_shop.item({**RICH, "id": 71, "name": "Пакет №6. Ліпідограма", "code": "F2005", "price": 300.0,
                                  "discount": 0.0, "parameters": [{"id": 1, "name": "Холестерин загальний"},
                                                                  {"id": 2, "name": "Тригліцериди"}]}),
             "groups": ["Пакетні пропозиції", "Пакети"]}
    genetic = {**esculab_shop.item({**RICH, "id": 900, "name": "Сімейна гіперхолестеринемія, 4 гени", "code": "G1",
                                    "price": 9000.0, "discount": 0.0, "parameters": [{"id": 77, "name": "LDLR"}]}),
               "groups": ["Генетичні дослідження", "Генетика"]}
    catalogue = [esculab_shop.item(RICH), panel, genetic]
    monkeypatch.setattr(esculab_shop, "catalog", lambda settings, region, base_url=None: catalogue)
    monkeypatch.setattr(esculab_shop, "regions", lambda settings, base_url=None: [{"id": "3201", "name": "Львів"}])
    monkeypatch.setattr(esculab_shop, "details", lambda settings, ids, base_url=None: {
        i: {"prep": "Кров відбирається натщесерце (через 8-12 год після прийому їжі)."} for i in ids})
    monkeypatch.setattr("anamna.web.app._metric_catalog", lambda connection, owner: [])
    monkeypatch.setattr(testplan, "lab_concepts", lambda connection, owner: set())
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "en")

    # The analyte box offers ferritin, never the gene panel or the package.
    found = client.get("/plan-tests?touched=1&q=cholesterol").text
    assert "Сімейна гіперхолестеринемія" not in found and "Ліпідограма" not in found
    # Packages and genetic tests are found in special mode, by the same box.
    browsed = client.get("/plan-tests?special=1&touched=1&q=cholesterol").text
    assert 'name="include" value="esculab:71"' in browsed and "Lab packages and named tests" in browsed
    browsed = client.get("/plan-tests?special=1&touched=1&q=холестерин").text
    assert 'name="include" value="esculab:900"' in browsed and "Genetic test" in browsed

    planned = client.get("/plan-tests?touched=1&need=ferritin&include=esculab:900&plan=1").text
    assert "Added by you" in planned and 'name="include" value="esculab:900" checked' in planned
    # 9000 + ferritin 410 + one 80 UAH draw shared by both.
    assert "9,490 UAH" in planned
    assert "Ready in about 1 day" in planned and "blood serum" in planned
    # The lab's sentence becomes one curated line, and the summary its gist.
    assert "Fasting: last meal 8-12 h before the test." in planned and "Fasting 8-12 h" in planned
    assert "Кров відбирається натщесерце" not in planned

    client.cookies.set("anamna_lang", "uk")
    uk = client.get("/plan-tests?touched=1&need=ferritin&include=esculab:900&plan=1").text
    assert "Ви додали" in uk and "Як підготуватися" in uk and "Термін виконання: 1 день" in uk
    assert "Натщесерце: останній прийом їжі за 8-12 год до аналізу." in uk
    assert 'name="include" value="esculab:900" checked' in uk and "сироватка крові" in uk


# --- long lists: pages and filters ------------------------------------------------------


def test_pages_clamp_and_count():
    rows = list(range(45))
    first = testplan_routes._page(rows, None)
    assert first["rows"] == rows[:20] and (first["start"], first["end"], first["pages"]) == (1, 20, 3)
    last = testplan_routes._page(rows, "3")
    assert last["rows"] == rows[40:] and (last["start"], last["end"], last["page"]) == (41, 45, 3)
    assert testplan_routes._page(rows, "99")["page"] == 3 and testplan_routes._page(rows, "0")["page"] == 1
    assert testplan_routes._page(rows, "two")["page"] == 1
    empty = testplan_routes._page([], "2")
    assert (empty["page"], empty["pages"], empty["start"], empty["end"]) == (1, 1, 0, 0)
    assert testplan_routes._amount("1 500,5") == 1500.5 and testplan_routes._amount("-3") is None
    assert testplan_routes._amount("abc") is None


@pytest.fixture
def shelf_page(record, monkeypatch):
    """45 gene tests and two packages at Esculab, signed in, English."""
    settings, user_id = record
    labsync.save_provider_settings(settings, "esculab", enabled=True, url="http://127.0.0.1:9")
    for key in [k for k in testplan_routes.SHOPS if k != "esculab"]:
        monkeypatch.delitem(testplan_routes.SHOPS, key)
    genes = [{**esculab_shop.item({**RICH, "id": 1000 + n, "name": f"Ген {n:02d}", "code": f"G{n}",
                                   "price": 1000.0 + n * 10, "discount": 0.0, "parameters": [{"id": 5000 + n, "name": f"Ген {n:02d}"}]}),
              "groups": ["Генетичні дослідження", "Генетика"]} for n in range(45)]
    packages = [{**esculab_shop.item({**RICH, "id": 2000 + n, "name": f"Пакет {n}. Ліпідограма", "code": f"P{n}",
                                      "price": price, "discount": 0.0,
                                      "parameters": [{"id": 1, "name": "Холестерин загальний"}, {"id": 2, "name": "Тригліцериди"}]}),
                 "groups": ["Пакетні пропозиції", "Пакети"]} for n, price in ((1, 900.0), (2, 300.0))]
    catalogue = [esculab_shop.item(RICH), *genes, *packages]
    monkeypatch.setattr(esculab_shop, "catalog", lambda settings, region, base_url=None: catalogue)
    monkeypatch.setattr(esculab_shop, "regions", lambda settings, base_url=None: [{"id": "3201", "name": "Львів"}])
    monkeypatch.setattr("anamna.web.app._metric_catalog", lambda connection, owner: [])
    monkeypatch.setattr(testplan, "lab_concepts", lambda connection, owner: set())
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "en")
    return client


GENETIC = "sg=esculab%3A%D0%93%D0%B5%D0%BD%D0%B5%D1%82%D0%B8%D1%87%D0%BD%D1%96+%D0%B4%D0%BE%D1%81%D0%BB%D1%96%D0%B4%D0%B6%D0%B5%D0%BD%D0%BD%D1%8F"


def test_a_section_is_paged_and_the_links_keep_the_plan(shelf_page):
    page = shelf_page.get(f"/plan-tests?special=1&touched=1&need=ferritin&include=esculab:2001&city_esculab=3201&{GENETIC}").text
    assert "1-20 of 45" in page and "45 matches" in page and page.count('name="include" value="esculab:10') == 20
    assert 'rel="prev"' not in page
    nxt = page.split('rel="next" href="')[1].split('"')[0].replace("&amp;", "&")
    assert "sp=2" in nxt and "need=ferritin" in nxt and "include=esculab%3A2001" in nxt and "city_esculab=3201" in nxt
    assert nxt.endswith("#plan-sets-found")
    last = shelf_page.get(f"/plan-tests?special=1&touched=1&{GENETIC}&sp=3").text
    assert "41-45 of 45" in last and 'rel="next"' not in last and 'rel="prev"' in last
    # Past the end: the last page, not an empty one.
    assert "41-45 of 45" in shelf_page.get(f"/plan-tests?special=1&touched=1&{GENETIC}&sp=99").text
    # Nothing typed and no section: never the whole catalogue.
    bare = shelf_page.get("/plan-tests?special=1&touched=1&skind=genetic").text
    assert 'name="include" value="esculab:1000"' not in bare


def test_the_sets_filters_narrow_and_order(shelf_page):
    def found(query):
        page = shelf_page.get("/plan-tests?special=1&touched=1&" + query).text
        return re.findall(r'name="include" value="(esculab:\d+)"', page)

    assert found("q=Ліпідограма") == ["esculab:2001", "esculab:2002"]
    assert found("q=Ліпідограма&ssort=price") == ["esculab:2002", "esculab:2001"]
    assert found("q=Ліпідограма&smax=500") == ["esculab:2002"]
    assert found(f"{GENETIC}&skind=set") == []
    assert found(f"{GENETIC}&skind=genetic&smax=1015") == ["esculab:1000", "esculab:1001"]
    assert found("q=Ліпідограма&slab=esculab") == ["esculab:2001", "esculab:2002"]
    assert found("q=Ліпідограма&slab=nowhere") == ["esculab:2001", "esculab:2002"]
    shelf_page.cookies.set("anamna_lang", "uk")
    uk = shelf_page.get(f"/plan-tests?special=1&touched=1&{GENETIC}&sp=2").text
    assert "21-40 із 45" in uk and "45 збігів" in uk and "Наступні" in uk and "Попередні" in uk


def test_analyte_results_are_paged():
    rows = [{"id": f"c{n}", "name": f"Ferritin {n}", "is_device": False, "aliases": []} for n in range(25)]
    found, _ = testplan_routes._search("ferritin", rows, {}, {}, set(), {row["id"] for row in rows})
    assert len(found) == 25
    second = testplan_routes._page(found, "2")
    assert [row["label"] for row in second["rows"]] == [f"Ferritin {n}" for n in range(20, 25)]


def test_a_labs_english_name_finds_and_labels_its_test():
    from anamna.i18n import get_locale, set_locale

    amh = keyed_item(9, ["synevo:1050"], 820, "Антимюллерів гормон (АМГ, MIS)", lab="synevo",
                     name_en="Anti-Müllerian hormone (AMH, MIS)")
    tsh_lookalike = keyed_item(10, ["synevo:2"], 300, "Антитіла до тканинної трансглютамінази (tTG)")
    labs = {"synevo": [amh, tsh_lookalike]}
    names = {"synevo:1050": "Anti-Müllerian hormone (AMH, MIS)", "synevo:2": "tTG"}
    for query in ("anti-mullerian", "Anti-Müllerian hormone", "АМГ", "AMH"):
        rows, _ = testplan_routes._search(query, [], labs, names, set(), set())
        assert [row["keys"] for row in rows] == [["synevo:1050"]], query
    # «tTG» is not «ТТГ» (TSH) however the search key folds g and h.
    assert testplan_routes._search("TSH", [], labs, names, set(), set())[0] == []
    before = get_locale()
    try:
        set_locale("en")
        assert testplan_routes._label(amh) == {"label": "Anti-Müllerian hormone (AMH, MIS)", "label_lang": "en"}
        set_locale("uk")
        assert testplan_routes._label(amh)["label"] == "Антимюллерів гормон (АМГ, MIS)"
    finally:
        set_locale(before)
