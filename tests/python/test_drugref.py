"""Medicine reference lookup from tabletki.ua.

Every network call is replaced: an autouse fixture makes building an opener
fail, and each test that needs a reply fakes ``drugref._open`` itself.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anamna import drugref
from anamna.db import connect, migrate
from anamna.drugref import BASE, DrugRefError

from test_web_panels import settings_for


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the test reached the network")

    monkeypatch.setattr(urllib.request, "build_opener", refuse)


SUGGEST_REPLY = json.dumps(
    [
        {"type": 0, "name": "Торгові назви"},
        {"type": 1, "code": "12197", "name": "Діокор", "urlName": "Диокор",
         "screenViewType": "TNCATV", "description": "11 товарів"},
        {"type": 1, "code": "8311", "name": "Діокор соло 80 таблетки, в/плів. обол. по 80 мг №30 (10х3)",
         "urlName": "Диокор-соло-80", "screenViewType": "PCV", "description": "Acino Pharma AG"},
        {"type": 4, "name": "Нічого не знайдено"},
    ],
    ensure_ascii=False,
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


def test_suggest_keeps_trade_names_and_products_and_ignores_headings_and_empty_results(monkeypatch):
    sent = []

    def fake_open(url, data=None):
        sent.append((url, data))
        return SUGGEST_REPLY

    monkeypatch.setattr(drugref, "_open", fake_open)
    assert drugref.suggest("  діокор ") == [
        {"kind": "trade_name", "code": "12197", "name": "Діокор",
         "reference_name": "Диокор", "maker": ""},
        {"kind": "product", "code": "8311",
         "name": "Діокор соло 80 таблетки, в/плів. обол. по 80 мг №30 (10х3)",
         "reference_name": "Диокор-соло-80", "maker": "Acino Pharma AG"},
    ]
    assert sent == [(
        BASE + "/ajax/search/suggest",
        urllib.parse.urlencode({"searchText": "діокор"}).encode("utf-8"),
    )]


def test_suggest_returns_at_most_twelve(monkeypatch):
    items = [
        {"type": 1, "code": str(number), "name": f"Назва {number}", "urlName": f"Назва-{number}",
         "screenViewType": "PCV", "description": "Виробник"}
        for number in range(15)
    ]
    monkeypatch.setattr(drugref, "_open", lambda url, data=None: json.dumps(items, ensure_ascii=False))
    assert len(drugref.suggest("назва")) == 12


def test_suggest_under_three_characters_makes_no_request(monkeypatch):
    def refuse(url, data=None):
        raise AssertionError("a short query reached the site")

    monkeypatch.setattr(drugref, "_open", refuse)
    assert drugref.suggest("ді") == []
    assert drugref.suggest("  я ") == []


def test_suggest_refuses_a_reply_that_is_not_a_list(monkeypatch):
    monkeypatch.setattr(drugref, "_open", lambda url, data=None: "<html>maintenance</html>")
    with pytest.raises(DrugRefError):
        drugref.suggest("діокор")


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


def test_open_refuses_a_url_on_another_host():
    with pytest.raises(DrugRefError):
        drugref._open("https://example.com/uk/x/")
    with pytest.raises(DrugRefError):
        drugref._open("https://tabletki.ua.evil.example/")


def test_a_redirect_to_another_host_is_refused():
    handler = drugref._RedirectWithinSite()
    request = urllib.request.Request(BASE + "/uk/x/")
    with pytest.raises(DrugRefError):
        handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example/")


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
