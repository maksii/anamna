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


def test_text_keeps_a_bare_less_than_and_greater_than():
    fragment = (
        "<p>кліренсом креатиніну &lt; 10 мл/хв</p>"
        "<p>кліренсом креатиніну < 10 мл/хв та діаліз. Для пацієнтів > 10 мл/хв корекція не потрібна.</p>"
    )
    text = drugref._text(fragment)
    assert "< 10 мл/хв та діаліз" in text
    assert "> 10 мл/хв корекція" in text
    assert "<p>" not in text


def test_text_still_removes_real_tags_attributes_and_comments():
    assert drugref._text('<p class="x">a <b>b</b><!-- note --> c<br/>d</p>') == "a b c\nd"


def test_a_table_row_becomes_one_line_with_its_cells_separated_by_bars():
    row = (
        "<table><tr><td><p>Haemophilus influenzae</p></td><td><p>≤1</p></td>"
        "<td><p>-</p></td><td><p>&gt; 1</p></td></tr></table>"
    )
    assert drugref._text(row) == "Haemophilus influenzae | ≤1 | - | > 1"
    assert drugref._text(row.replace("&gt;", ">")) == "Haemophilus influenzae | ≤1 | - | > 1"


def test_two_rows_give_two_lines_and_a_header_row_of_th_cells_works_the_same():
    table = (
        "<table><tr><th>Antibiotic</th><th>MIC</th></tr>"
        "<tr><td>Ampicillin</td><td>≤1</td></tr></table>"
    )
    assert drugref._text(table) == "Antibiotic | MIC\nAmpicillin | ≤1"


def test_two_paragraphs_or_a_line_break_in_one_cell_stay_on_the_rows_line():
    table = "<table><tr><td><p>first</p><p>second</p></td><td>x<br>y</td></tr></table>"
    assert drugref._text(table) == "first second | x y"


def test_an_empty_last_cell_leaves_no_dangling_bar_and_a_bar_mid_line_stays():
    assert drugref._text("<table><tr><td>Ampicillin</td><td></td></tr></table>") == "Ampicillin"
    assert drugref._text("<table><tr><td>a | b</td><td>c</td></tr></table>") == "a | b | c"


def test_text_outside_tables_comes_out_as_before():
    assert drugref._text("<p>a</p><p>b <b>c</b></p>") == "a\nb c"
    assert drugref._text("<p>x<br>y</p>") == "x\ny"
    assert (
        drugref._text("<p>Before.</p><table><tr><td>a</td><td>b</td></tr></table><p>After.</p>")
        == "Before.\na | b\nAfter."
    )


def test_a_bare_less_than_in_an_instruction_section_survives_the_page_parse(monkeypatch):
    page = (
        '<html><section><h2 id="instr-desktop_0" data-index="instr_cont_0">Особливості</h2>'
        ' <div id="instr_cont_0" class="product-instructions-text">'
        ' <p>Пацієнтам із кліренсом креатиніну < 10 мл/хв та пацієнтам, яким проводять діаліз, '
        "тому валсартан слід застосовувати з обережністю. Для пацієнтів із кліренсом креатиніну "
        "> 10 мл/хв корекція дози не потрібна.</p>"
        " </div> </section></html>"
    )
    monkeypatch.setattr(drugref, "_open", lambda url, data=None: page)
    result = drugref.instruction_page("Валсартан-Тева")
    text = result["sections"][0][1]
    assert "кліренсом креатиніну < 10 мл/хв та пацієнтам" in text
    assert "кліренсом креатиніну > 10 мл/хв корекція дози" in text


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
        assert without_time(drugref.cached_instruction(connection, "Валсартан-Тева")) == without_time(first)
        assert len(fetches) == 2
        fetched_at = connection.execute("SELECT fetched_at FROM drug_references").fetchone()[0]
        assert fetched_at != old


def test_migration_67_marks_copies_stored_before_it_as_old(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    monkeypatch.setattr(drugref, "_open", lambda url, data=None: PAGE)
    with connect(settings) as connection:
        assert drugref.cached_instruction(connection, "Валсартан-Тева") is not None
        # Back to the schema before migration 67: no details column, no version row.
        connection.execute("DELETE FROM schema_migrations WHERE version = 67")
        connection.execute("ALTER TABLE drug_references DROP COLUMN details_json")
        connection.commit()
    migrate(settings)
    with connect(settings) as connection:
        fetched_at = connection.execute("SELECT fetched_at FROM drug_references").fetchone()[0]
    assert fetched_at == "2000-01-01T00:00:00+00:00"


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


def without_time(found):
    """The instruction without the date it was stored: two reads of one copy differ only there."""
    return {key: value for key, value in found.items() if key != "fetched_at"}


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
        assert without_time(result) == without_time(cached)
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
        assert without_time(drugref.cached_instruction(connection, "Валсартан-Тева")) == without_time(cached)
        assert fetched_at_of(connection) == old


def test_stale_cache_is_used_when_the_page_has_no_sections(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    with connect(settings) as connection:
        cached, old = cache_then_age(connection, monkeypatch)
        monkeypatch.setattr(drugref, "_open", lambda url, data=None: "<html>no sections</html>")
        assert without_time(drugref.cached_instruction(connection, "Валсартан-Тева")) == without_time(cached)
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


CARD_ID = "13634"
CARD_NAME = "Диокор-соло-160"
CARD = {
    "goodsIntCode": CARD_ID,
    "tradenameLink": CARD_NAME,
    "tradeName": "Діокор соло 160",
    "goodsName": "Діокор соло 160 таблетки, в/плів. обол. по 160 мг №30 (10х3)",
    "instructionByParts": [{"id": "1", "title": "Склад", "anchor": "Склад", "order": 1,
                            "html": "<p><i>діюча речовина:</i> валсартан;</p>"}],
    "dfp": {"ATCFull": ["C09CA03"]},
    "characteristics": [
        {"name": "Діючі речовини", "values": [{"name": "валсартан", "code": None}]},
        {"name": "Форма випуску", "values": [{"name": "таблетки, в/плів. обол.", "code": None}]},
        {"name": "Дозування", "values": [{"name": "валсартан: 160 мг", "code": None}]},
        {"name": "Кількість в упаковці", "values": [{"name": "30 шт", "code": None}]},
        {"name": "Умови продажу", "values": [{"name": "за рецептом", "code": None}]},
        {"name": "Фармгрупа", "values": [{"name": "Прості препарати антагоністів ангіотензину ІІ.", "code": "571"}]},
        {"name": "АТХ-група", "values": [{"name": "C09CA03 Валсартан", "code": "C09CA03"}]},
        {"name": "МНН", "values": [{"name": "Valsartan", "code": "715"}]},
        {"name": "Реєстрація", "values": [{"name": "UA/11341/01/01 от 30/10/2020", "code": None}]},
        {"name": "Виробник", "values": [{"name": "ТОВ «Фарма Старт», Україна.", "code": ""}]},
        {"name": "Форма випуску", "values": [{"name": "таблетки", "code": None}]},
        {"name": "Діюча речовина", "values": [{"name": "валсартан", "code": None}]},
    ],
    "goodsWarning": {"title": "Особливості застосування", "items": [
        {"allowed": 1, "remark": "дозволено", "subject": "Дорослі"},
        {"allowed": 2, "remark": "з обережністю", "subject": "Діабетики"},
        {"allowed": 0, "remark": "заборонено", "subject": "Вагітні"},
        {"allowed": -1, "remark": "Немає обмежень", "subject": "Приймати"},
    ]},
}


def card_reply(**changes):
    return json.dumps({**CARD, **changes}, ensure_ascii=False)


def fake_site(monkeypatch, card=None, page=PAGE):
    """Fakes _open: the card endpoint answers ``card`` (a body, or an exception to raise), other addresses ``page``.

    Returns the list of (url, headers) the calls were made with.
    """
    calls = []
    card = card_reply() if card is None else card

    def fake_open(url, data=None, headers=None):
        calls.append((url, headers))
        if url.startswith(API):
            if isinstance(card, BaseException):
                raise card
            return card
        return page

    monkeypatch.setattr(drugref, "_open", fake_open)
    return calls


def test_the_card_request_carries_the_token_and_the_product_code(monkeypatch):
    calls = fake_site(monkeypatch)
    drugref.instruction_api(CARD_NAME, CARD_ID, api_token="секрет")
    ((url, headers),) = calls
    assert headers["AppApiToken"] == "секрет"
    assert "id=13634" in url
    assert "withContentPlus=false" in url


def test_the_card_is_not_asked_without_a_product_code_or_a_token(monkeypatch):
    def refuse(url, data=None, headers=None):
        raise AssertionError("the card was requested")

    monkeypatch.setattr(drugref, "_open", refuse)
    with pytest.raises(DrugRefError):
        drugref.instruction_api(CARD_NAME, "", api_token="секрет")
    with pytest.raises(DrugRefError):
        drugref.instruction_api(CARD_NAME, CARD_ID, api_token="")


def test_a_card_about_another_product_or_another_page_is_refused(monkeypatch):
    fake_site(monkeypatch, card=card_reply(goodsIntCode="99999"))
    with pytest.raises(DrugRefError):
        drugref.instruction_api(CARD_NAME, CARD_ID, api_token="t")
    fake_site(monkeypatch, card=card_reply(tradenameLink="Інший-препарат"))
    with pytest.raises(DrugRefError):
        drugref.instruction_api(CARD_NAME, CARD_ID, api_token="t")


def test_a_good_card_gives_the_instruction_the_atc_codes_and_the_product_facts(monkeypatch):
    fake_site(monkeypatch)
    result = drugref.instruction_api(CARD_NAME, CARD_ID, api_token="t")
    assert result["url"] == BASE + "/uk/" + CARD_NAME + "/13634/"
    assert result["sections"] == [["Склад", "діюча речовина: валсартан;"]]
    assert result["atc"] == ["C09CA03"]
    assert result["shown_for"] == CARD["goodsName"]
    details = result["details"]
    assert details["via"] == "api"
    assert [key for key, _ in details["facts"]] == [
        "substance", "form", "dosage", "pack", "sale", "group", "atc", "inn", "registration", "maker",
    ]
    assert dict(details["facts"])["form"] == ["таблетки, в/плів. обол."]
    assert details["warnings"] == [
        ["Дорослі", "allowed", "дозволено"],
        ["Діабетики", "caution", "з обережністю"],
        ["Вагітні", "forbidden", "заборонено"],
        ["Приймати", "free", "Немає обмежень"],
    ]


def test_the_page_is_read_when_the_card_fails_and_a_trade_name_never_asks_the_card(monkeypatch):
    calls = fake_site(monkeypatch, card=DrugRefError("URLError"))
    result = drugref.instruction("Валсартан-Тева", CARD_ID, api_token="t", use_api=True)
    assert result["sections"][0][0] == "Склад"
    assert result["details"] == {"via": "page"}
    assert [url.startswith(API) for url, _ in calls] == [True, False]

    calls = fake_site(monkeypatch)
    result = drugref.instruction("Валсартан-Тева", "", api_token="t", use_api=True)
    assert [url.startswith(API) for url, _ in calls] == [False]
    assert result["details"] == {}


def test_the_cache_keeps_the_card_details_and_serves_them_without_a_request(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    fake_site(monkeypatch)
    with connect(settings) as connection:
        fetched = drugref.cached_instruction(connection, CARD_NAME, CARD_ID, use_api=True, api_token="t")
        assert fetched["details"]["via"] == "api"
        fetched_at, details_json = connection.execute(
            "SELECT fetched_at, details_json FROM drug_references").fetchone()
        assert fetched_at == fetched["fetched_at"]
        assert json.loads(details_json)["via"] == "api"

        def refuse(url, data=None, headers=None):
            raise AssertionError("the site was asked again")

        monkeypatch.setattr(drugref, "_open", refuse)
        assert drugref.stored_instruction(connection, CARD_NAME, CARD_ID) == fetched
        assert drugref.stored_instruction(connection, "Невідомий", CARD_ID) is None


def test_a_fresh_page_copy_is_read_once_more_through_the_card_and_no_further(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    calls = fake_site(monkeypatch)
    with connect(settings) as connection:
        def details_json():
            return connection.execute("SELECT details_json FROM drug_references").fetchone()[0]

        drugref.cached_instruction(connection, CARD_NAME, CARD_ID)
        assert details_json() == ""
        assert [url.startswith(API) for url, _ in calls] == [False]

        drugref.cached_instruction(connection, CARD_NAME, CARD_ID, use_api=True, api_token="t")
        assert [url.startswith(API) for url, _ in calls] == [False, True]
        assert json.loads(details_json())["via"] == "api"

        drugref.cached_instruction(connection, CARD_NAME, CARD_ID, use_api=True, api_token="t")
        assert len(calls) == 2

        connection.execute("UPDATE drug_references SET details_json = ?", ('{"via": "page"}',))
        drugref.cached_instruction(connection, CARD_NAME, CARD_ID, use_api=True, api_token="t")
        assert len(calls) == 2

        connection.execute("UPDATE drug_references SET details_json = ''")
        drugref.cached_instruction(connection, CARD_NAME, CARD_ID)
        assert len(calls) == 2


def test_the_token_is_the_saved_one_else_the_environment_one(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    monkeypatch.delenv(drugref.TOKEN_ENV, raising=False)
    with connect(settings) as connection:
        assert drugref.token(connection) == ""
        assert drugref.token_source(connection) == ""

        monkeypatch.setenv(drugref.TOKEN_ENV, "env-token")
        assert drugref.token(connection) == "env-token"
        assert drugref.token_source(connection) == "environment"

        drugref.set_token(connection, "saved-token")
        assert drugref.token(connection) == "saved-token"
        assert drugref.token_source(connection) == "settings"


def test_the_api_mode_without_a_token_falls_back_to_the_page(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    monkeypatch.delenv(drugref.TOKEN_ENV, raising=False)
    with connect(settings) as connection:
        drugref.set_mode(connection, drugref.MODE_API)
        assert drugref.fetch_options(connection) == {"use_api": False, "api_token": ""}
        drugref.set_token(connection, "saved-token")
        assert drugref.fetch_options(connection) == {"use_api": True, "api_token": "saved-token"}
