"""Synevo's catalogue crawl and cart, against a fake Synevo at ``common._http``.

Every reply here is synthetic, shaped like the ones observed on 2026-11-08.
Pacing sleeps are recorded, never slept.
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import pytest

from anamna import labsync
from anamna.db import connect, migrate
from anamna.labsync import common, synevo_shop
from anamna.labsync.common import LabSyncError, name_key
from anamna.security import create_user

from test_web_panels import PASSWORD, settings_for

CITY = "611b76e53254b616974143c3"
COOKIE = "synthetic-session-" + "b" * 40
BUILD = "testBuild123"

CBC = {"id": "a" * 24, "code": "4018", "name": "Загальний аналіз крові", "price": 300, "active": True}
TSH = {"id": "b" * 24, "code": "1004", "name": "Тиреотропний гормон (ТТГ)", "price": 350, "active": True}
URINE = {"id": "c" * 24, "code": "4071", "name": "Аналіз сечі загальний", "price": 270, "active": True}
PANEL = {"id": "d" * 24, "code": "4198", "name": "Пакет №525", "price": 2070, "active": True}
GONE = {"id": "e" * 24, "code": "9999", "name": "Знято з продажу", "price": 100, "active": False}

DETAILS = {
    CBC["id"]: {"Name": CBC["name"], "BasePrice": 300, "Active": True, "BioMaterialName": ["Венозна кров"],
                "Components": [{"Name": "Аналіз крові: ШОЕ"}, {"Name": "Аналіз крові розгорнутий (ЗАК)"}]},
    TSH["id"]: {"Name": TSH["name"], "BasePrice": 350, "Active": True, "BioMaterialName": ["Венозна кров"],
                "Components": []},
    URINE["id"]: {"Name": URINE["name"], "BasePrice": 270, "Active": True, "BioMaterialName": ["Сеча"],
                  "Components": []},
    PANEL["id"]: {"Name": PANEL["name"], "BasePrice": 2070, "Active": True, "BioMaterialName": ["Венозна кров", "Сеча"],
                  "Components": [{"Name": "Тиреотропний гормон (ТТГ)"}, {"Name": "Аналіз сечі загальний"},
                                 {"Name": "Звіт з описом лабораторних показників"}]},
    synevo_shop.BLOOD_DRAW["service_id"]: {"Name": "Взяття крові одноразовими системами", "BasePrice": 90,
                                           "Active": False, "IsIntake": True, "BioMaterialName": [], "Components": []},
}

#: Two categories; the blood one has three pages and repeats a service the
#: urine one also lists.
LISTINGS = {
    ("substance", "blood"): [[CBC, TSH], [PANEL], [GONE]],
    ("substance", "urine"): [[URINE, PANEL]],
}
RUBRICS = [{"code": "substance", "subrubrics": [{"code": "blood"}, {"code": "urine"}]}]

OFFER_LIST = {"res": "ok", "data": {"pagesCount": 1, "items": [
    {"_id": "f" * 24, "url": "november4198", "endDate": 4102444800000, "statusLabel": {"statusFlag": 0},
     "nameRegional": [{"Language": "uk", "Value": "2026. Листопад. Пропозиція місяця: Захисти свій організм!"}]},
    {"_id": "1" * 24, "url": "bez_mezh", "endDate": 4102444800000, "statusLabel": {"statusFlag": 0},
     "nameRegional": [{"Language": "uk", "Value": "Герой БЕЗ МЕЖ"}]},
    {"_id": "2" * 24, "url": "october10004", "endDate": 1, "statusLabel": {"statusFlag": 1},
     "nameRegional": [{"Language": "uk", "Value": "Жовтень. Пропозиція місяця"}]},
]}}
OFFER_PAGE = {"pageProps": {"discountInfoData": {
    "_id": "f" * 24, "availableCities": [{"_id": CITY}], "unavailableCities": [],
    "servicesDetails": {"appliesFor": "Include", "services": [
        {"code": "4198", "basePrice": 2070, "price": 1449, "discountType": "percentage", "discountValue": 30}]},
}}}


class FakeSynevo:
    """Routes like the real site; records every request; can fail on cue."""

    def __init__(self):
        self.requests: list[tuple[str, str, dict | None]] = []
        self.fail: dict[str, list[int]] = {}   # path prefix -> statuses to answer first
        self.cart = {"_id": "6" * 24, "Items": [], "Intakes": [], "ServicesSum": 0, "IntakesSum": 0,
                     "DiscountsSum": 0, "TotalSum": 0, "Location": {"_id": "611b76e43254b616974142d0"}}
        self.add_replies: dict[str, dict] = {}
        self.cookie_seen: list[str] = []

    def __call__(self, method, url, *, headers, body=None, timeout=20, limit=0):
        parsed = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        payload = json.loads(body) if body else None
        self.requests.append((method, parsed.path, query or payload))
        self.cookie_seen.append(headers.get("Cookie", ""))
        for prefix, statuses in self.fail.items():
            if parsed.path.startswith(prefix) and statuses:
                status = statuses.pop(0)
                if status == 0:
                    raise LabSyncError("labsync.error_unreachable")
                return status, [], b""
        reply = self.route(method, parsed.path, query, payload)
        if isinstance(reply, bytes):
            return 200, [], reply
        return 200, [], json.dumps(reply, ensure_ascii=False).encode("utf-8")

    def route(self, method, path, query, payload):
        if path == "/":
            return b'<script id="__NEXT_DATA__">{"buildId":"' + BUILD.encode() + b'"}</script>'
        if path == "/api/locations":
            return [{"id": CITY, "name": "Львів", "slug": "lviv"}, {"id": "bad id", "name": "x"}]
        if path == f"/_next/data/{BUILD}/uk/rubricator/top-tests.json":
            return {"pageProps": {"rubrics": RUBRICS}}
        if path == "/api/rubricator/services":
            pages = LISTINGS[(query["rubric"], query["category"])]
            page = int(query["page"])
            return {"res": "ok", "services": pages[page - 1], "options": {"totalPages": len(pages), "limit": "10"}}
        if path == "/api/rubricator/service-details":
            data = DETAILS.get(query["serviceId"])
            return {"res": "ok", "data": {**data, "id": query["serviceId"]}} if data else {"res": "error"}
        if path == "/api/discount/get-list":
            return OFFER_LIST
        if path == f"/_next/data/{BUILD}/uk/info/discounts/november4198.json":
            return OFFER_PAGE
        if path == "/api/cart/get-cart":
            return self.cart
        if path == "/api/cart/set-location":
            self.cart["Location"] = {"_id": payload["locationId"]}
            return self.cart
        if path == "/api/cart/add-item":
            code = str(payload["code"])
            if code in self.add_replies:
                return self.add_replies[code]
            self.cart["Items"].append({"Service": {"Code": code}, "Price": 1})
            self.cart["TotalSum"] += 1
            return self.cart
        raise AssertionError(f"unexpected request {method} {path}")


@pytest.fixture
def fake(monkeypatch):
    server = FakeSynevo()
    sleeps: list[float] = []
    clock = [1000.0]

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(common, "_http", server)
    monkeypatch.setattr(synevo_shop, "_sleep", sleep)
    monkeypatch.setattr(synevo_shop, "_clock", lambda: clock[0])
    monkeypatch.setattr(synevo_shop, "_last_request", [float("-inf")])
    server.sleeps = sleeps
    return server


@pytest.fixture
def settings(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    return settings


def paths(server, path):
    return [request for request in server.requests if request[1] == path]


# --- catalogue -----------------------------------------------------------------------


def test_crawl_walks_every_page_dedups_and_reads_panel_members(settings, fake):
    assert synevo_shop.catalog(settings, CITY) is None
    assert synevo_shop.catalog_status(settings, CITY)["state"] == "missing"

    items = synevo_shop.refresh_catalog(settings, CITY)

    by_code = {item["code"]: item for item in items}
    assert sorted(by_code) == ["1004", "4018", "4071", "4198"]  # the inactive one is not for sale
    # Three blood pages and one urine page, each fetched exactly once in
    # Ukrainian and once more in English for the names.
    listing = paths(fake, "/api/rubricator/services")
    for lang in ("uk", "en"):
        assert sorted((q["category"], q["page"]) for _, _, q in listing if q["lang"] == lang) == [
            ("blood", "1"), ("blood", "2"), ("blood", "3"), ("urine", "1")]
    assert all(q["city"] == CITY for _, _, q in listing)
    # The panel sits in both categories and is read once.
    details = [q["serviceId"] for _, _, q in paths(fake, "/api/rubricator/service-details")]
    assert details.count(PANEL["id"]) == 1

    panel = by_code["4198"]
    # Members sold on their own take that test's code; others keep a name key.
    assert [p["id"] for p in panel["parameters"]] == ["1004", "4071", "name:" + name_key("Звіт з описом лабораторних показників")]
    assert by_code["1004"]["parameters"] == [{"id": "1004", "name": "Тиреотропний гормон (ТТГ)"}]
    assert len(by_code["4018"]["parameters"]) == 2
    assert panel["url"] == "https://www.synevo.ua/tests/4198"
    assert panel["order"]["code"] == "4198" and panel["order"]["service_id"] == PANEL["id"]
    assert panel["sex"] is None and panel["synonyms"] == []

    # One blood draw, shared by every venous-blood item; urine needs none.
    draw = {"id": "synevo:intake:6001", "name": "Взяття крові одноразовими системами", "price": 90.0}
    assert by_code["4018"]["fees"] == [draw] and by_code["1004"]["fees"] == [draw] and panel["fees"] == [draw]
    assert by_code["4071"]["fees"] == []

    # Only the running monthly offer discounts; the veterans' one does not.
    assert panel["price"] == 2070 and panel["final_price"] == 1449
    assert panel["order"]["promo"]["id"] == "f" * 24 and panel["order"]["promo"]["percent"] == 30
    assert by_code["4018"]["final_price"] == by_code["4018"]["price"] == 300
    assert not paths(fake, f"/_next/data/{BUILD}/uk/info/discounts/bez_mezh.json")

    assert synevo_shop.catalog(settings, CITY) == items
    status = synevo_shop.catalog_status(settings, CITY)
    assert status["state"] == "ready" and status["fetched_at"]
    assert status["progress"]["stage"] == "done" and status["progress"]["packages"] == 2
    with connect(settings) as connection:
        keys = {row[0] for row in connection.execute("SELECT cache_key FROM lab_catalog_cache WHERE provider='synevo'")}
    assert "catalog.partial" not in keys


def test_pacing_spaces_requests_without_touching_the_network(settings, fake):
    synevo_shop.refresh_catalog(settings, CITY)
    # Every request after the first waited for the one-second budget.
    assert len(fake.sleeps) == len(fake.requests) - 1
    assert all(abs(seconds - synevo_shop.DELAY) < 1e-9 for seconds in fake.sleeps)


def test_an_interrupted_crawl_resumes_where_it_stopped(settings, fake, monkeypatch):
    monkeypatch.setattr(synevo_shop, "CHECKPOINT_EVERY", 1)
    # The network goes away on the second details call, for longer than the retries.
    original = fake.route
    calls = {"details": 0}

    def flaky(method, path, query, payload):
        if path == "/api/rubricator/service-details":
            calls["details"] += 1
            if calls["details"] >= 2:
                raise LabSyncError("labsync.error_unreachable")
        return original(method, path, query, payload)

    monkeypatch.setattr(fake, "route", flaky)
    with pytest.raises(LabSyncError):
        synevo_shop.refresh_catalog(settings, CITY)
    assert synevo_shop.catalog(settings, CITY) is None
    # Backoff doubled between the retries.
    backoffs = [s for s in fake.sleeps if s >= synevo_shop.BACKOFF]
    assert backoffs == [synevo_shop.BACKOFF * 2 ** n for n in range(synevo_shop.RETRIES)]
    status = synevo_shop.catalog_status(settings, CITY)
    assert status["progress"]["stage"] == "details"

    done_before = len(fake.requests)
    monkeypatch.setattr(fake, "route", original)
    items = synevo_shop.refresh_catalog(settings, CITY)
    resumed = fake.requests[done_before:]
    # No listing page and no already-read service was fetched again.  (The
    # home page is read once more, for the offers the first run never reached.)
    listing_paths = ("/api/rubricator/services", f"/_next/data/{BUILD}/uk/rubricator/top-tests.json")
    # The English pass comes after the details, so it is new work, not a repeat.
    assert not [r for r in resumed if r[1] in listing_paths and r[2].get("lang") != "en"]
    read_again = [q["serviceId"] for _, path, q in resumed if path == "/api/rubricator/service-details"]
    assert CBC["id"] not in read_again
    assert len(items) == 4


def test_429_and_5xx_back_off_then_succeed(settings, fake):
    fake.fail["/api/rubricator/services"] = [429, 503]
    items = synevo_shop.refresh_catalog(settings, CITY)
    assert len(items) == 4
    assert synevo_shop.BACKOFF in fake.sleeps and synevo_shop.BACKOFF * 2 in fake.sleeps


def test_a_client_error_is_not_retried(settings, fake):
    fake.fail["/api/rubricator/services"] = [404]
    with pytest.raises(LabSyncError) as raised:
        synevo_shop.refresh_catalog(settings, CITY)
    assert raised.value.status == 404
    assert len(paths(fake, "/api/rubricator/services")) == 1


def test_offers_failing_leaves_list_prices(settings, fake):
    fake.fail["/api/discount/get-list"] = [404]
    items = synevo_shop.refresh_catalog(settings, CITY)
    assert all(item["final_price"] == item["price"] for item in items)
    assert all("promo" not in item["order"] for item in items)


def test_ensure_fresh_starts_one_background_crawl_and_skips_a_fresh_catalogue(settings, fake):
    synevo_shop.ensure_fresh(settings, CITY)
    thread = synevo_shop._threads[CITY]
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert len(synevo_shop.catalog(settings, CITY)) == 4
    before = len(fake.requests)
    synevo_shop.ensure_fresh(settings, CITY)
    assert synevo_shop._threads[CITY] is thread and len(fake.requests) == before


def test_regions_are_cached_and_a_bad_city_id_is_refused(settings, fake):
    assert synevo_shop.regions(settings) == [{"id": CITY, "name": "Львів"}]
    assert synevo_shop.regions(settings) == [{"id": CITY, "name": "Львів"}]
    assert len(paths(fake, "/api/locations")) == 1
    assert synevo_shop.catalog(settings, "../../api/cart/clear-cart") is None
    assert synevo_shop.catalog_status(settings, "x")["state"] == "missing"
    synevo_shop.ensure_fresh(settings, "f" * 24)  # well-formed, but not a Synevo city
    assert "f" * 24 not in synevo_shop._threads
    with pytest.raises(ValueError):
        synevo_shop.refresh_catalog(settings, "../../api/cart/clear-cart")


# --- after a plan ---------------------------------------------------------------------


def test_refresh_prices_reads_only_the_chosen_items(settings, fake):
    items = synevo_shop.refresh_catalog(settings, CITY)
    chosen = [item for item in items if item["code"] in ("4018", "4198")]
    DETAILS[CBC["id"]]["BasePrice"] = 320
    DETAILS[synevo_shop.BLOOD_DRAW["service_id"]]["BasePrice"] = 95
    try:
        before = len(fake.requests)
        fresh = synevo_shop.refresh_prices(settings, CITY, chosen)
    finally:
        DETAILS[CBC["id"]]["BasePrice"] = 300
        DETAILS[synevo_shop.BLOOD_DRAW["service_id"]]["BasePrice"] = 90
    read = [q["serviceId"] for _, path, q in fake.requests[before:] if path == "/api/rubricator/service-details"]
    assert sorted(read) == sorted([CBC["id"], PANEL["id"], synevo_shop.BLOOD_DRAW["service_id"]])
    cbc, panel = fresh
    assert cbc["price"] == cbc["final_price"] == 320 and cbc["checked"] and cbc["available"]
    assert cbc["fees"][0]["price"] == 95
    assert panel["final_price"] == 1449 and panel["order"]["promo"]["percent"] == 30
    assert chosen[0]["price"] == 300  # the caller's items are not changed in place


def test_refresh_prices_marks_withdrawn_and_unreadable_items(settings, fake):
    items = synevo_shop.refresh_catalog(settings, CITY)
    urine = next(item for item in items if item["code"] == "4071")
    DETAILS[URINE["id"]]["Active"] = False
    try:
        assert synevo_shop.refresh_prices(settings, CITY, [urine])[0]["available"] is False
    finally:
        DETAILS[URINE["id"]]["Active"] = True
    fake.fail["/api/rubricator/service-details"] = [0] * (synevo_shop.RETRIES + 1)
    unread = synevo_shop.refresh_prices(settings, CITY, [urine])[0]
    assert unread["checked"] is False and unread["price"] == 270


# --- cart -----------------------------------------------------------------------------


def connected_user(settings) -> str:
    user_id = create_user(settings, "shop@example.test", "Shop", PASSWORD)
    labsync.save_provider_settings(settings, "synevo", enabled=True, url="http://127.0.0.1:9")
    labsync.save_credentials(settings, user_id, "synevo", {"token": COOKIE})
    return user_id


def test_add_to_cart_sends_what_synevo_pages_send(settings, fake):
    items = synevo_shop.refresh_catalog(settings, CITY)
    user_id = connected_user(settings)
    chosen = [item for item in items if item["code"] in ("4018", "4198")]
    fake.requests.clear()
    fake.cookie_seen.clear()

    result = synevo_shop.add_to_cart(settings, user_id, chosen, region=CITY)

    assert [entry["code"] for entry in result["added"]] == ["4018", "4198"] and result["failed"] == []
    assert result["cart_url"] == "http://127.0.0.1:9/ordering"
    assert result["cart"]["total"] == 2
    calls = [(method, path) for method, path, _ in fake.requests]
    assert calls == [("GET", "/api/cart/get-cart"), ("POST", "/api/cart/set-location"),
                     ("POST", "/api/cart/add-item"), ("POST", "/api/cart/add-item")]
    assert fake.requests[1][2] == {"locationId": CITY, "cartId": "6" * 24}
    plain, offered = (body for _, path, body in fake.requests if path == "/api/cart/add-item")
    assert plain == {"code": 4018, "cartId": "6" * 24, "confirm": False, "src": "sc", "info": "/tests/4018",
                     "promoId": None, "isPackage": False}
    assert offered == {"code": 4198, "cartId": "6" * 24, "confirm": False, "src": "akcii",
                       "info": "/info/discounts/november4198", "promoId": "f" * 24, "isPackage": False}
    assert all(cookie == f"next-auth.session-token={COOKIE}" for cookie in fake.cookie_seen)


def test_add_to_cart_reports_each_refusal_and_keeps_going(settings, fake):
    items = synevo_shop.refresh_catalog(settings, CITY)
    user_id = connected_user(settings)
    fake.add_replies = {
        "4018": {"error": 1001, "messages": [{"parent": {"Code": "4198"}}]},
        "1004": {"res": "error", "status": 4013},
        "4071": {"res": "ok", "Items": []},  # answered, but the cart does not hold it
    }
    result = synevo_shop.add_to_cart(settings, user_id, items)
    assert {entry["code"]: entry["reason"] for entry in result["failed"]} == {
        "4018": "synevo_cart.in_package", "1004": "synevo_cart.promo", "4071": "synevo_cart.not_added"}
    assert [entry["code"] for entry in result["added"]] == ["4198"]
    assert not paths(fake, "/api/cart/set-location")


def test_add_to_cart_needs_a_connection_and_stops_on_a_dead_cookie(settings, fake):
    user_id = create_user(settings, "none@example.test", "None", PASSWORD)
    with pytest.raises(LabSyncError) as raised:
        synevo_shop.add_to_cart(settings, user_id, [])
    assert raised.value.key == "labsync.error_off"
    labsync.save_provider_settings(settings, "synevo", enabled=True, url="http://127.0.0.1:9")
    with pytest.raises(LabSyncError) as raised:
        synevo_shop.add_to_cart(settings, user_id, [])
    assert raised.value.key == "labsync.error_no_credentials"

    user_id = connected_user(settings)
    fake.fail["/api/cart/add-item"] = [401]
    with pytest.raises(LabSyncError) as raised:
        synevo_shop.add_to_cart(settings, user_id, [{"id": "4018", "code": "4018", "order": {"code": "4018"}}])
    assert raised.value.key == "labsync.error_auth"


def test_add_to_cart_keeps_the_rolled_cookie(settings, fake, monkeypatch):
    user_id = connected_user(settings)
    rolled = "rolled-session-" + "c" * 40
    original = fake.__call__

    def rolling(method, url, **kwargs):
        status, _, body = original(method, url, **kwargs)
        return status, [f"__Secure-next-auth.session-token={rolled}; Path=/; HttpOnly"], body

    monkeypatch.setattr(common, "_http", rolling)
    synevo_shop.add_to_cart(settings, user_id, [])
    assert labsync.account(settings, user_id, "synevo")["secret"] == rolled


def test_details_keep_turnaround_material_and_plain_preparation(monkeypatch):
    reply = {"res": "ok", "data": {"Name": "ТТГ", "BasePrice": 350, "Active": True, "readyAfter": "1",
                                   "BioMaterialName": ["Венозна кров"], "PrepRuleDescr": "Підготовка до аналізу крові",
                                   "PrepRuleText": "<p>Натщесерце,&nbsp;8-12&nbsp;год</p>", "Remarks": ""}}
    monkeypatch.setattr(synevo_shop, "_get", lambda *a, **k: reply)
    found = synevo_shop._details("5f7b080bf5456f5172169209", "611b76e53254b616974143c3")
    assert found["days"] == 1 and found["bio"] == ["Венозна кров"]
    assert found["prep"] == "Натщесерце, 8-12 год" and found["prep_title"] == "Підготовка до аналізу крові"


def test_only_a_package_named_for_one_sex_is_restricted():
    two = [{"id": "a"}, {"id": "b"}]
    assert synevo_shop._sex("Пакет №45 (Здоров'я жінки + звіт)", two) == "F"
    assert synevo_shop._sex("Пакет №39 (Для чоловіків віком 40+)", two) == "M"
    assert synevo_shop._sex("Пакет №24 (Пренатальний скринінг I триместра)", two) == "F"
    # Shelved "for women" on the site, but a thyroid panel is for anyone.
    assert synevo_shop._sex("Пакет №3.5 (Тиреоїдний: ТТГ, АТПО, Т3 вільний, Т4 вільний)", two) is None
    # A single test is never restricted by its name alone.
    assert synevo_shop._sex("Антимюллерів гормон у жінок", two[:1]) is None
