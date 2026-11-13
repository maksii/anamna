"""A failed order goes back to the plan as it stood: the tile it was sent from
says what happened, the person's choices stay in the form, and a lab whose
sign-in has expired offers the links to order by hand instead of a form that
cannot work.  The lab is faked; nothing reaches Esculab."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from starlette.datastructures import QueryParams

from anamna.db import connect
from anamna.labsync import esculab_shop
from anamna.labsync.common import LabSyncError
from anamna.web import testplan_routes

from test_audit_share_enforcement import PLAN, order_data, shop  # noqa: F401 -- shop is a fixture
from test_plan_doctor import app_for, owner_client  # noqa: F401 -- app_for is a fixture
from test_plan_page_edit import CATALOGUE
from test_testplan import record  # noqa: F401 -- record is a fixture
from test_web_profile import csrf_for


def test_plan_query_keeps_the_plan_and_drops_the_outcome():
    params = QueryParams("touched=1&need=a&add=b&preset=p&plan=1&notice=x&failed=esculab&opoint=7"
                         "&odate=2030-01-01&opay=point&q=fe&oq=t")
    assert testplan_routes.plan_query(params) == "touched=1&need=a&add=b&preset=p&plan=1"


def test_a_failed_order_goes_back_to_its_tile_with_the_choices_made():
    location = testplan_routes._back("touched=1&plan=1", "order_failed", "esculab",
                                     {"opoint": "7", "odate": "", "opay": "point"}).headers["location"]
    assert location.startswith("/plan-tests?touched=1&plan=1&")
    assert parse_qs(urlsplit(location).query) == {
        "touched": ["1"], "plan": ["1"], "notice": ["order_failed"], "failed": ["esculab"],
        "opoint": ["7"], "opay": ["point"]}
    assert location.endswith("#plan-fail-esculab")
    assert testplan_routes._back("touched=1&plan=1", "cart_failed").headers["location"].endswith("#plan-result")


def test_a_refused_esculab_order_keeps_the_selection_and_the_form(shop, monkeypatch):  # noqa: F811
    settings, owner, app, calls = shop

    def refused(client, person, point, items, *, online, day=None):
        raise LabSyncError("labsync.error_order_refused")

    monkeypatch.setattr(esculab_shop, "create_order", refused)
    client = owner_client(app, settings, owner)
    data = order_data(csrf_for(settings, client), nonce="refused-1")
    data.update({"plan_query": "touched=1&plan=1&add=ferritin&need=tsh", "payment": "point"})
    failed = client.post("/plan-tests/order/esculab", data=data, follow_redirects=False)

    assert failed.status_code == 303 and calls["orders"] == []
    location = failed.headers["location"]
    query = parse_qs(urlsplit(location).query)
    assert query["failed"] == ["esculab"] and query["notice"] == ["order_failed"]
    assert query["add"] == ["ferritin"] and query["need"] == ["tsh"] and query["plan"] == ["1"]
    assert query["opoint"] == ["193"] and query["odate"] == ["2030-01-02"] and query["opay"] == ["point"]
    assert location.endswith("#plan-fail-esculab")


def test_the_failed_tile_says_what_happened_and_still_lists_its_items(shop, monkeypatch):  # noqa: F811
    settings, owner, app, _calls = shop
    monkeypatch.setattr(testplan_routes, "_lab_items", lambda *args: [
        {**dict(item), "url": f"{esculab_shop.SITE}/test-{item['id']}"} for item in CATALOGUE])
    client = owner_client(app, settings, owner)

    page = client.get(f"{PLAN}&notice=order_failed&failed=esculab").text
    assert 'id="plan-fail-esculab"' in page
    assert page.count("an-plan-fail") == 1
    # The top-of-page alert is not printed a second time for the same outcome.
    assert page.count("Esculab did not accept the order") == 1
    assert 'class="an-plan-item" data-item=' in page
    assert '<details class="an-plan-tile" open>' in page
    self_block = page.split('class="an-plan-self"', 1)[1].split("</details>", 1)[0]
    assert 'target="_blank"' in self_block and f"{esculab_shop.SITE}/test-" in self_block


def test_an_unknown_notice_is_ignored(shop):  # noqa: F811
    settings, owner, app, _calls = shop
    client = owner_client(app, settings, owner)
    plain = client.get(PLAN).text
    bogus = client.get(f"{PLAN}&notice=bogus").text
    # The nav's language and theme links carry the query along, so only the alerts are compared.
    assert bogus.count('role="alert"') == plain.count('role="alert"')


def test_an_expired_esculab_sign_in_offers_the_links_not_a_form(shop):  # noqa: F811
    settings, owner, app, calls = shop
    with connect(settings) as db:
        db.execute("UPDATE lab_accounts SET secret_expires_at='2020-01-01T00:00:00+00:00' "
                   "WHERE user_id=? AND provider='esculab'", (owner,))
    client = owner_client(app, settings, owner)
    page = client.get(PLAN).text
    assert "/profile?tab=connections&amp;lab=esculab#lab-esculab" in page
    assert 'action="/plan-tests/order/esculab"' not in page
    assert '<details class="an-plan-self" open>' in page
    assert calls["clients"] == []  # the expired sign-in is not even tried
