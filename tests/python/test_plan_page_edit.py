"""/plan-tests: samples the person will not give, and editing a lab's order
(take an item out, put one in from that lab's shelf)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import QueryParams

from anamna import labsync, testplan
from anamna.labsync import esculab_shop
from anamna.security import create_session
from anamna.web import testplan_routes
from anamna.web.app import create_app

from test_testplan import card, item, record  # noqa: F401 -- record is a fixture


def sample(material, *, item_id=1, keys=("ferritin",), price=100):
    return {**item(item_id, list(keys), price), "material": list(material)}


@pytest.mark.parametrize(("material", "groups"), [
    (["сироватка крові"], {"blood"}),
    (["Венозна кров"], {"blood"}),
    (["сеча (добова)"], {"urine"}),
    (["кал"], {"stool"}),
    (["мазок із носоглотки", "цільна кров ЗАК"], {"swab", "blood"}),
    (["букальний зішкріб"], {"swab"}),
    (["слина"], {"saliva"}),
    (["секрет простати"], {"semen"}),
    (["сироватка крові + ліквор"], {"blood", "other"}),
    (["Різні види біопсійного матеріалу в залежності від аналізу"], {"other"}),
    ([], set()),
])
def test_an_item_needs_the_samples_its_material_names(material, groups):
    assert testplan.samples(sample(material)) == groups


def test_sechova_kyslota_is_a_blood_test_not_urine():
    # «Сечова кислота» (uric acid) and «сечовина» (urea) are blood tests.
    assert testplan.samples(sample(["сироватка крові"])) == {"blood"}
    assert not testplan.SAMPLES["urine"].search("сечова кислота")


CATALOGUE = [
    sample(["сироватка крові"], item_id=1, keys=("ferritin",), price=100),
    sample(["сеча"], item_id=2, keys=("urine-ph",), price=50),
    # A package that needs urine too: leaving urine out drops it whole.
    sample(["сироватка крові", "сеча"], item_id=3, keys=("ferritin", "urine-ph"), price=120),
    sample(["сироватка крові"], item_id=4, keys=("tsh",), price=90),
]


@pytest.fixture
def client(record, monkeypatch):  # noqa: F811
    settings, user_id = record
    labsync.save_provider_settings(settings, "esculab", enabled=True, url="http://127.0.0.1:9")
    for key in [k for k in testplan_routes.SHOPS if k != "esculab"]:
        monkeypatch.delitem(testplan_routes.SHOPS, key)
    monkeypatch.setattr(testplan_routes, "_lab_items", lambda *args: [dict(i) for i in CATALOGUE])
    monkeypatch.setattr(esculab_shop, "regions", lambda settings, base_url=None: [{"id": "3201", "name": "Львів"}])
    monkeypatch.setattr(esculab_shop, "details", lambda settings, ids, base_url=None: {})
    monkeypatch.setattr("anamna.web.app._metric_catalog", lambda connection, owner: [
        {**card("ferritin", category="iron", state="overdue"), "name": "Ferritin"},
        {**card("urine-ph", category="urine", state="overdue"), "name": "Urine pH"}])
    monkeypatch.setattr(testplan, "lab_concepts", lambda connection, owner: {"ferritin", "urine-ph"})
    test_client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    test_client.cookies.set("anamna_session", token)
    test_client.cookies.set("anamna_lang", "en")
    return test_client


def test_with_urine_left_out_a_urine_result_is_neither_listed_nor_planned(client):
    both = client.get("/plan-tests?touched=1&need=ferritin&need=urine-ph&plan=1").text
    assert 'value="urine-ph" checked' in both and "Covers 2 of 2" in both

    page = client.get("/plan-tests?touched=1&need=ferritin&need=urine-ph&ex=urine&plan=1").text
    assert 'name="ex" value="urine" data-sum="urine"' in page and 'value="urine"' in page
    assert 'data-key="urine-ph"' not in page and 'data-item="3"' not in page and 'data-item="2"' not in page
    assert 'data-item="1"' in page and "Covers 1 of 1" in page
    assert "1 result left off your list: Urine pH" in page and "leaving out urine" in page
    # Remembered for the next visit, which starts from the record again.
    assert client.cookies.get(testplan_routes.SAMPLES_COOKIE) == "urine"
    again = client.get("/plan-tests").text
    assert 'value="urine" data-sum="urine"\n                 aria-describedby="plan-samples-hint" checked' in again
    assert 'data-key="urine-ph"' not in again

    client.cookies.set("anamna_lang", "uk")
    uk = client.get("/plan-tests?touched=1&need=ferritin&need=urine-ph&ex=urine").text
    assert "Зі списку знято 1 показник:" in uk and "без: сеча" in uk and "Зразки, які ви не здаватимете" in uk


def test_an_order_is_edited_item_by_item_and_the_total_follows(client):
    base = "/plan-tests?touched=1&need=ferritin&plan=1"
    plan = client.get(base).text
    assert 'data-item="1"' in plan and "180 UAH" in plan  # 100 + the 80 UAH draw
    assert "cut=esculab%3A1#plan-esculab" in plan

    cut = client.get(base + "&cut=esculab:1").text
    assert "Changed by you" in cut and "This order does not cover: Ferritin." in cut
    assert "Removed" in cut and "Put back" in cut and "Covers 0 of 1" in cut
    assert 'data-item="1"' not in cut and "Undo my changes" in cut

    edited = client.get(base + "&put=esculab:4").text
    assert 'data-item="4"' in edited and "270 UAH" in edited  # one draw fee for both


def test_edit_url_toggles_one_edit_and_keeps_every_other_choice():
    params = QueryParams("need=a&plan=1&cut=esculab:1&put=synevo:9&olab=esculab&oq=tsh")
    back = testplan_routes.edit_url(params, "esculab", put="esculab:1")
    assert back == "/plan-tests?need=a&plan=1&put=synevo%3A9#plan-esculab"
    added = testplan_routes.edit_url(params, "esculab", put="esculab:4")
    assert "put=esculab%3A4" in added and "cut=esculab%3A1" in added and "oq=" not in added
    removed = testplan_routes.edit_url(QueryParams("put=esculab:4"), "esculab", cut="esculab:4")
    assert removed == "/plan-tests?#plan-esculab"
    reset = testplan_routes.edit_url(params, "esculab", reset=True)
    assert "esculab%3A" not in reset and "put=synevo%3A9" in reset
    option = testplan_routes.edit_url(params, "esculab", alt=2)
    assert "alt_esculab=2" in option and "cut=" not in option


def test_the_order_box_finds_the_labs_tests_and_filters_the_order(client):
    reply = client.get("/plan-tests/order-search?touched=1&need=ferritin&plan=1&olab=esculab&oq=Item 4&have=1").json()
    assert reply["match"] == []
    assert "Item 4" in reply["html"] and "put=esculab%3A4" in reply["html"] and "plan=1" in reply["html"]
    found = client.get("/plan-tests/order-search?touched=1&need=ferritin&olab=esculab&oq=Item 1&have=1").json()
    assert found["match"] == ["1"] and "Item 1" not in found["html"]
    # Without script: the same box as a form, the order filtered on the page.
    page = client.get("/plan-tests?touched=1&need=ferritin&plan=1&olab=esculab&oq=Item 4").text
    assert 'data-item="1" hidden' in page and "Nothing in this order matches." in page
    assert "put=esculab%3A4" in page
