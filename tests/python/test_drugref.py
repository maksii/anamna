"""Medicine reference lookup from tabletki.ua.

Every network call is replaced. An autouse fixture makes building an opener
fail. Tests that need a reply install the ``site`` fake, which stands in for
the opener, or fake ``drugref._open`` when they only exercise parsing.
"""

from __future__ import annotations

import email.message
import email.utils
import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anamna import drugref
from anamna.config import USER_AGENT
from anamna.db import connect, migrate
from anamna.drugref import API, BASE, DrugRefError, DrugRefPaused

from test_web_panels import settings_for


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the test reached the network")

    monkeypatch.setattr(urllib.request, "build_opener", refuse)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(drugref, "_now", fake)
    drugref.reset_state()
    yield fake
    drugref.reset_state()


def entry(view, code, url, name, description=""):
    return {"screenViewType": view, "code": code, "url": url, "name": name, "description": description}


def reply(*items):
    payload = {"group": [{"name": "Результати", "searchItems": list(items)}]}
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


SUGGEST_REPLY = reply(
    entry("TNCATV", "12197", "Диокор-соло-80", "Діокор", "11 товарів"),
    entry("PCV", "8311", "Диокор-соло-80",
          "Діокор соло 80 таблетки, в/плів. обол. по 80 мг №30 (10х3)", "Acino Pharma AG"),
)

PAGE = (
    '<html><script>var page={"ATCFull":["C09DA03","C09CA03","C09DA03"]};</script>'
    '<p>Інструкція вказана для «Валсартан-Тева 160 мг»</p>'
    '<section><h2 id="instr-desktop_0" data-index="instr_cont_0" data-mobile-id="instr_0" style="x">Склад</h2>'
    ' <div id="instr_cont_0" class="product-instructions-text" style="y">'
    ' <p><i>діючі речовини:</i> валсартан, гідрохлоротіазид;</p><p>допоміжні речовини:&nbsp;лактоза.</p>'
    ' </div> </section>'
    '<section><h2 id="instr-desktop_1" data-index="instr_cont_1" data-mobile-id="instr_1" style="x">Дозування</h2>'
    ' <div id="instr_cont_1" class="product-instructions-text" style="y">'
    ' <table><tr><td>Доза</td><td>80 мг</td></tr></table>Приймати<br>щодня.'
    ' </div> </section>'
    '</html>'
)


class Reply:
    def __init__(self, body):
        self.body = body

    def read(self, size):
        return self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Site:
    """Stands in for the opener. Scripted outcomes are used first, then the default reply."""

    def __init__(self):
        self.outcomes = []
        self.default = SUGGEST_REPLY
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        outcome = self.outcomes.pop(0) if self.outcomes else self.default
        if isinstance(outcome, BaseException):
            raise outcome
        return Reply(outcome)


@pytest.fixture
def site(monkeypatch):
    fake = Site()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: fake)
    return fake


def http_error(code, retry_after=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(BASE + "/uk/x/", code, "refused", headers, None)


def test_suggest_parses_trade_names_and_products_into_the_seven_keys(site):
    found = drugref.suggest("  діокор ")
    assert found == [
        {"kind": "trade_name", "code": "12197", "name": "Діокор", "reference_name": "Диокор-соло-80",
         "maker": "", "unit": "tablet", "strength": "80 мг"},
        {"kind": "product", "code": "8311",
         "name": "Діокор соло 80 таблетки, в/плів. обол. по 80 мг №30 (10х3)",
         "reference_name": "Диокор-соло-80", "maker": "Acino Pharma AG",
         "unit": "tablet", "strength": "80 мг"},
    ]
    (request,) = site.requests
    assert request.full_url == API + "Search/searchHintsV2"
    assert request.data == json.dumps({"term": "діокор"}).encode("utf-8")
    assert request.get_header("Lang") == "uk"
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("Content-type") == "application/json; charset=UTF-8"
    assert request.get_header("User-agent") == USER_AGENT


def test_a_trade_name_keeps_the_unit_and_strength_its_products_agree_on(site):
    site.default = reply(
        entry("TNCATV", "1", "Коа", "Коа"),
        entry("PCV", "2", "Коа", "Коа таблетки по 10 мг №30", "Виробник А"),
        entry("PCV", "3", "Коа", "Коа таблетки по 10 мг №60", "Виробник Б"),
    )
    found = drugref.suggest("коа")[0]
    assert (found["unit"], found["strength"]) == ("tablet", "10 мг")


def test_a_trade_name_keeps_only_the_unit_when_its_products_differ_in_strength(site):
    site.default = reply(
        entry("TNCATV", "1", "Коа", "Коа"),
        entry("PCV", "2", "Коа", "Коа таблетки по 10 мг №30"),
        entry("PCV", "3", "Коа", "Коа таблетки по 20 мг №30"),
    )
    assert drugref.suggest("коа")[0] == {
        "kind": "trade_name", "code": "1", "name": "Коа", "reference_name": "Коа",
        "maker": "", "unit": "tablet", "strength": "",
    }


def test_a_trade_name_with_products_of_two_forms_gets_no_unit(site):
    site.default = reply(
        entry("TNCATV", "1", "Коа", "Коа"),
        entry("PCV", "2", "Коа", "Коа таблетки по 10 мг №30"),
        entry("PCV", "3", "Коа", "Коа капсули по 10 мг №30"),
    )
    found = drugref.suggest("коа")[0]
    assert (found["unit"], found["strength"]) == ("", "")


def test_a_trade_name_without_a_product_has_no_unit_or_strength(site):
    site.default = reply(entry("TNCATV", "1", "Коа", "Коа"))
    found = drugref.suggest("коа")[0]
    assert (found["unit"], found["strength"]) == ("", "")


def test_a_trade_name_takes_its_values_from_a_product_past_the_limit(site):
    site.default = reply(
        entry("TNCATV", "1", "Коа", "Коа"),
        *[entry("PCV", str(number), f"Інше-{number}", f"Назва {number} таблетки по 5 мг №10")
          for number in range(13)],
        entry("PCV", "99", "Коа", "Коа таблетки по 10 мг №30", "Виробник"),
    )
    found = drugref.suggest("коа")
    assert len(found) == 12
    assert (found[0]["unit"], found[0]["strength"]) == ("tablet", "10 мг")


def test_suggest_returns_at_most_twelve(site):
    site.default = reply(
        *[entry("PCV", str(number), f"Назва-{number}", f"Назва {number} таблетки по 5 мг №10", "Виробник")
          for number in range(15)]
    )
    assert len(drugref.suggest("назва")) == 12


def test_items_that_are_not_usable_are_skipped(site):
    site.default = reply(
        "not a dict",
        {"screenViewType": ["PCV"], "url": "a", "name": "Список"},
        entry("OTHER", "1", "b", "Інше"),
        {"screenViewType": "PCV", "code": "2", "name": "Без адреси"},
        {"screenViewType": "PCV", "code": "3", "url": "c", "name": 5},
        entry("PCV", "4", "", "Порожня адреса"),
        entry("PCV", "5", "d", "Таблетки по 5 мг №10", "Виробник"),
    )
    assert drugref.suggest("таблетки") == [{
        "kind": "product", "code": "5", "name": "Таблетки по 5 мг №10", "reference_name": "d",
        "maker": "Виробник", "unit": "tablet", "strength": "5 мг",
    }]


@pytest.mark.parametrize("payload", [{}, {"group": None}, {"group": [{"name": "x", "searchItems": None}]}])
def test_an_empty_reply_gives_no_suggestions(site, payload):
    site.default = json.dumps(payload).encode("utf-8")
    assert drugref.suggest("діокор") == []


@pytest.mark.parametrize(
    "payload",
    [
        "<html>maintenance</html>",
        json.dumps([{"type": 1}]),
        json.dumps({"group": "x"}),
        json.dumps({"group": ["x"]}),
        json.dumps({"group": [{"searchItems": "x"}]}),
    ],
)
def test_suggest_refuses_a_reply_of_another_shape(site, payload):
    site.default = payload.encode("utf-8")
    with pytest.raises(DrugRefError):
        drugref.suggest("діокор")


def test_suggest_under_three_characters_makes_no_request(monkeypatch):
    def refuse(url, data=None, headers=None):
        raise AssertionError("a short query reached the site")

    monkeypatch.setattr(drugref, "_open", refuse)
    assert drugref.suggest("ді") == []
    assert drugref.suggest("  я ") == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Діокор соло 160 таблетки, в/плів. обол. по 160 мг №30 (10х3)", ("tablet", "160 мг")),
        ("Вітамін D3 краплі оральні 15000 МО/мл по 10 мл у флак.", ("drop", "15000 МО/мл")),
        ("Анальгін розчин д/ін. 500 мг/мл по 2 мл в амп. №10", ("ml", "500 мг/мл")),
        ("Ко-Діован таблетки, в/плів. обол. по 160 мг/12,5 мг №14", ("tablet", "160 мг/12,5 мг")),
        ("Левоміколь мазь по 40 г у тубі", ("application", "")),
        ("Нурофен сироп по 100 мл у флак.", ("ml", "")),
        ("Щось невідоме", ("", "")),
    ],
)
def test_parse_product_reads_the_form_and_the_strength(name, expected):
    assert drugref.parse_product(name) == expected


def test_localize_strength_uses_international_units_outside_ukrainian():
    assert drugref.localize_strength("160 мг/12,5 мг", "en") == "160 mg/12.5 mg"
    assert drugref.localize_strength("15000 МО/мл", "en") == "15000 IU/ml"
    assert drugref.localize_strength("500 мкг", "en") == "500 mcg"
    assert drugref.localize_strength("40 г", "en") == "40 g"
    assert drugref.localize_strength("160 мг/12,5 мг", "uk") == "160 мг/12,5 мг"


def test_a_repeated_search_is_served_from_the_cache(site, clock):
    first = drugref.suggest("Діокор")
    assert drugref.suggest("  діокор   ") == first
    assert len(site.requests) == 1

    first[0]["name"] = "changed"
    assert drugref.suggest("діокор")[0]["name"] == "Діокор"

    clock.advance(drugref.SUGGEST_CACHE_SECONDS + 1)
    drugref.suggest("діокор")
    assert len(site.requests) == 2


def test_the_cache_drops_its_oldest_entry_when_full(site, monkeypatch):
    monkeypatch.setattr(drugref, "SUGGEST_CACHE_SIZE", 2)
    for text in ("перший", "другий", "третій"):
        drugref.suggest(text)
    assert len(site.requests) == 3
    drugref.suggest("третій")
    assert len(site.requests) == 3
    drugref.suggest("перший")
    assert len(site.requests) == 4


def test_a_429_with_retry_after_pauses_every_request(site, clock):
    site.outcomes.append(http_error(429, "300"))
    with pytest.raises(DrugRefPaused) as paused:
        drugref.suggest("діокор")
    assert paused.value.seconds == 300
    assert drugref.paused_seconds() == 300

    with pytest.raises(DrugRefPaused):
        drugref.suggest("ібупрофен")
    assert len(site.requests) == 1

    clock.advance(301)
    assert drugref.suggest("ібупрофен")
    assert len(site.requests) == 2


@pytest.mark.parametrize(
    ("failure", "seconds"),
    [
        (http_error(429), 120),
        (http_error(429, "5"), 30),
        (http_error(429, "99999"), 3600),
        (http_error(503), 120),
        (http_error(403), 900),
    ],
)
def test_the_pause_length_follows_the_status_and_the_header(site, failure, seconds):
    site.outcomes.append(failure)
    with pytest.raises(DrugRefPaused) as paused:
        drugref.suggest("діокор")
    assert paused.value.seconds == seconds
    assert drugref.paused_seconds() == seconds


def test_a_retry_after_date_is_read_as_the_time_until_it(site):
    later = datetime.now(UTC) + timedelta(seconds=400)
    site.outcomes.append(http_error(429, email.utils.format_datetime(later, usegmt=True)))
    with pytest.raises(DrugRefPaused) as paused:
        drugref.suggest("діокор")
    assert 390 <= paused.value.seconds <= 400


def test_the_thirty_first_request_in_a_minute_waits_without_sending(site, clock):
    for number in range(drugref.REQUEST_BUDGET):
        drugref._open(BASE + f"/uk/Назва-{number}/")
    with pytest.raises(DrugRefPaused) as paused:
        drugref._open(BASE + "/uk/Остання/")
    assert paused.value.seconds == drugref.BUDGET_SECONDS
    assert len(site.requests) == drugref.REQUEST_BUDGET

    clock.advance(drugref.BUDGET_SECONDS + 1)
    drugref._open(BASE + "/uk/Остання/")
    assert len(site.requests) == drugref.REQUEST_BUDGET + 1


def test_open_refuses_other_hosts_and_accepts_both_allowed_prefixes(site):
    for url in ("https://evil.example/", "https://app.tabletki.ua/other/", "https://tabletki.ua.evil.example/"):
        with pytest.raises(DrugRefError):
            drugref._open(url)
    assert drugref._open(BASE + "/uk/x/")
    assert drugref._open(API + "Search/searchHintsV2", b"{}", headers={"Lang": "uk"})
    assert len(site.requests) == 2


def test_open_refuses_another_host():
    with pytest.raises(DrugRefError):
        drugref._open("https://example.com/uk/x/")
    with pytest.raises(DrugRefError):
        drugref._open("https://tabletki.ua.evil.example/")


def test_a_redirect_to_another_host_is_refused_and_one_to_the_api_is_followed():
    handler = drugref._RedirectWithinSite()
    request = urllib.request.Request(BASE + "/uk/x/")
    with pytest.raises(DrugRefError):
        handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example/")
    assert handler.redirect_request(request, None, 302, "Found", {}, API + "Search/x") is not None


def test_instruction_parses_sections_atc_codes_and_the_shown_for_sentence(monkeypatch):
    fetched = []

    def fake_open(url, data=None):
        fetched.append(url)
        return PAGE

    monkeypatch.setattr(drugref, "_open", fake_open)
    result = drugref.instruction("Валсартан-Тева")
    assert fetched == [drugref.page_url("Валсартан-Тева")]
    assert result["url"] == BASE + "/uk/Валсартан-Тева/"
    assert result["atc"] == ["C09DA03", "C09CA03"]
    assert result["shown_for"] == "Валсартан-Тева 160 мг"
    assert [title for title, _ in result["sections"]] == ["Склад", "Дозування"]
    assert result["sections"][0][1] == (
        "діючі речовини: валсартан, гідрохлоротіазид;\nдопоміжні речовини: лактоза."
    )
    dosing = result["sections"][1][1]
    assert "Доза | 80 мг" in dosing
    assert "Приймати\nщодня." in dosing


def test_instruction_of_a_page_without_sections_is_empty_not_an_error(monkeypatch):
    monkeypatch.setattr(drugref, "_open", lambda url, data=None: "<html>no instruction here</html>")
    result = drugref.instruction("Невідомий")
    assert result["sections"] == []
    assert result["atc"] == []
    assert result["shown_for"] == ""


def test_page_url_quotes_cyrillic_and_appends_a_numeric_code():
    url = drugref.page_url("Диокор-соло-80", "8311")
    assert url == BASE + "/uk/" + urllib.parse.quote("Диокор-соло-80", safe="") + "/8311/"
    assert "%D0%94" in url


def test_page_url_drops_a_code_that_is_not_all_digits():
    assert drugref.page_url("Диокор", "abc") == BASE + "/uk/" + urllib.parse.quote("Диокор", safe="") + "/"


@pytest.mark.parametrize("name", ["a/b", "..", "x?y", "a#b", "100%", "a\\b", "a..b", ""])
def test_page_url_refuses_names_that_could_change_the_path(name):
    with pytest.raises(DrugRefError):
        drugref.page_url(name)


@pytest.mark.parametrize(
    "failure",
    [urllib.error.URLError("Діокор"), TimeoutError("slow"), http.client.IncompleteRead(b"")],
)
def test_a_network_failure_names_only_its_class(monkeypatch, failure):
    class Opener:
        def open(self, request, timeout=None):
            raise failure

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: Opener())
    with pytest.raises(DrugRefError) as refused:
        drugref._open(BASE + "/uk/Діокор/")
    assert str(refused.value) == type(failure).__name__
    assert "Діокор" not in str(refused.value)


def test_a_reply_over_the_size_limit_is_refused(monkeypatch):
    class Response:
        def read(self, size):
            return b"a" * min(size, 25)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Opener:
        def open(self, request, timeout=None):
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: Opener())
    monkeypatch.setattr(drugref, "MAX_BYTES", 10)
    with pytest.raises(DrugRefError):
        drugref._open(BASE + "/uk/x/")


def test_the_lookup_is_on_by_default_and_follows_the_switch(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    with connect(settings) as connection:
        assert drugref.enabled(connection)
        drugref.set_enabled(connection, False)
        assert not drugref.enabled(connection)
        drugref.set_enabled(connection, True)
        assert drugref.enabled(connection)
        drugref.set_enabled(connection, False)
        rows = connection.execute("SELECT COUNT(*) FROM app_settings WHERE key = ?", (drugref.SETTING,)).fetchone()
        assert rows[0] == 1


def test_cached_instruction_stores_serves_from_the_cache_and_refetches_when_old(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    fetches = []

    def fake_open(url, data=None):
        fetches.append(url)
        return PAGE

    monkeypatch.setattr(drugref, "_open", fake_open)
    with connect(settings) as connection:
        first = drugref.cached_instruction(connection, "Валсартан-Тева")
        assert first is not None and first["sections"][0][0] == "Склад"
        assert len(fetches) == 1
        assert drugref.cached_instruction(connection, "Валсартан-Тева") == first
        assert len(fetches) == 1

        old = (datetime.now(UTC) - timedelta(days=drugref.CACHE_DAYS + 1)).isoformat()
        connection.execute("UPDATE drug_references SET fetched_at = ?", (old,))
        assert drugref.cached_instruction(connection, "Валсартан-Тева") == first
        assert len(fetches) == 2
        fetched_at = connection.execute("SELECT fetched_at FROM drug_references").fetchone()[0]
        assert fetched_at != old


def test_a_failed_fetch_or_an_empty_page_returns_none_and_stores_nothing(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)

    def down(url, data=None):
        raise DrugRefError("URLError")

    with connect(settings) as connection:
        monkeypatch.setattr(drugref, "_open", down)
        assert drugref.cached_instruction(connection, "Аміодарон") is None
        monkeypatch.setattr(drugref, "_open", lambda url, data=None: "<html>no sections</html>")
        assert drugref.cached_instruction(connection, "Аміодарон") is None
        assert connection.execute("SELECT COUNT(*) FROM drug_references").fetchone()[0] == 0


def test_cached_instruction_is_none_while_the_site_is_paused(tmp_path: Path, site):
    settings = settings_for(tmp_path)
    migrate(settings)
    site.outcomes.append(http_error(429, "300"))
    with connect(settings) as connection:
        assert drugref.cached_instruction(connection, "Валсартан-Тева") is None
        assert drugref.cached_instruction(connection, "Валсартан-Тева") is None
    assert len(site.requests) == 1


def cache_then_age(connection, monkeypatch, days=200):
    """Caches the test page, then ages the row past the cache limit. Returns the cached copy and the old date."""
    monkeypatch.setattr(drugref, "_open", lambda url, data=None: PAGE)
    cached = drugref.cached_instruction(connection, "Валсартан-Тева")
    old = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    connection.execute("UPDATE drug_references SET fetched_at = ?", (old,))
    return cached, old


def fetched_at_of(connection):
    return connection.execute("SELECT fetched_at FROM drug_references").fetchone()[0]


def test_stale_cache_is_used_when_the_fetch_fails(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    with connect(settings) as connection:
        cached, old = cache_then_age(connection, monkeypatch)

        def down(url, data=None):
            raise DrugRefError("URLError")

        monkeypatch.setattr(drugref, "_open", down)
        result = drugref.cached_instruction(connection, "Валсартан-Тева")
        assert result == cached
        assert result["sections"][0][0] == "Склад"
        assert result["atc"] == ["C09DA03", "C09CA03"]
        assert result["shown_for"] == cached["shown_for"]
        assert fetched_at_of(connection) == old


def test_stale_cache_is_used_while_lookups_are_paused(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    with connect(settings) as connection:
        cached, old = cache_then_age(connection, monkeypatch)

        def paused(url, data=None):
            raise DrugRefPaused(60)

        monkeypatch.setattr(drugref, "_open", paused)
        assert drugref.cached_instruction(connection, "Валсартан-Тева") == cached
        assert fetched_at_of(connection) == old


def test_stale_cache_is_used_when_the_page_has_no_sections(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    with connect(settings) as connection:
        cached, old = cache_then_age(connection, monkeypatch)
        monkeypatch.setattr(drugref, "_open", lambda url, data=None: "<html>no sections</html>")
        assert drugref.cached_instruction(connection, "Валсартан-Тева") == cached
        assert fetched_at_of(connection) == old


def test_stale_cache_is_replaced_by_a_good_fetch(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    with connect(settings) as connection:
        _, old = cache_then_age(connection, monkeypatch)
        page = PAGE.replace("Склад", "Склад оновлено")
        monkeypatch.setattr(drugref, "_open", lambda url, data=None: page)
        result = drugref.cached_instruction(connection, "Валсартан-Тева")
        assert result["sections"][0][0] == "Склад оновлено"
        sections_json = connection.execute("SELECT sections_json FROM drug_references").fetchone()[0]
        assert "Склад оновлено" in sections_json
        assert fetched_at_of(connection) != old


def test_no_cache_and_failed_fetch_gives_none(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)

    def down(url, data=None):
        raise DrugRefError("URLError")

    monkeypatch.setattr(drugref, "_open", down)
    with connect(settings) as connection:
        assert drugref.cached_instruction(connection, "Валсартан-Тева") is None
        assert connection.execute("SELECT COUNT(*) FROM drug_references").fetchone()[0] == 0


def test_broken_stale_row_gives_none_when_the_fetch_fails(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    with connect(settings) as connection:
        cache_then_age(connection, monkeypatch)
        connection.execute("UPDATE drug_references SET sections_json = ?", ("not json",))

        def down(url, data=None):
            raise DrugRefError("URLError")

        monkeypatch.setattr(drugref, "_open", down)
        assert drugref.cached_instruction(connection, "Валсартан-Тева") is None
        monkeypatch.setattr(drugref, "_open", lambda url, data=None: PAGE)
        assert drugref.cached_instruction(connection, "Валсартан-Тева")["sections"][0][0] == "Склад"
