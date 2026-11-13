"""Record-wide search, the /results filters and the home priorities.

Built on the miniature record in `test_web_panels.build`: one abnormal LDL, a
normal HDL and creatinine, a hemoglobin, one document from "Test Lab".  Every
test here guards a defect the 2026-11-06 sandbox audit measured (UX-01..03,
UX-11, CLIN-20..27).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from anamna import immunizations
from anamna.db import connect, utc_now
from anamna.web import app as web
from anamna.web import search

from test_web_panels import build


def _api(client, **params) -> dict:
    web.invalidate_catalog()
    return client.get("/api/metrics/search", params=params).json()


def _seed_finding(settings, user_id: str, *, status: str = "attention") -> None:
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO clinical_findings(
                   id, owner_user_id, patient_id, document_id, page_number, health_area, title,
                   summary_en, original_text, finding_date, status, created_at)
               VALUES ('finding-1', ?, ?, 'doc-1', 1, 'digestive', 'Pathology report', '',
                       'Фрагменти зубчастої аденоми, хронічний неактивний ілеїт', '2025-11-12', ?, ?)""",
            (user_id, f"patient-{user_id}", status, utc_now()),
        )


def _seed_steps(settings, user_id: str, values: dict[str, float]) -> None:
    with connect(settings) as connection:
        vendor_id = connection.execute("SELECT id FROM vendors LIMIT 1").fetchone()["id"]
        connection.execute(
            """INSERT INTO device_imports(
                   id, owner_user_id, patient_id, vendor_id, adapter_key, source_path,
                   source_fingerprint, source_bytes, raw_record_count, status, metadata_json, imported_at)
               VALUES ('imp-1', ?, ?, ?, 'apple_health', 'export.zip', 'sha-d', 10, 2, 'complete', '{}', ?)""",
            (user_id, f"patient-{user_id}", vendor_id, utc_now()),
        )
        for index, (day, value) in enumerate(values.items()):
            connection.execute(
                """INSERT INTO device_metric_days(
                       id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                       metric_key, metric_name, category, day, aggregation, unit,
                       value, sample_count, created_at)
                   VALUES (?, ?, ?, 'imp-1', 'Watch', 'Apple Health', 'steps', 'Daily steps',
                           'device_activity', ?, 'sum', 'steps', ?, 30, ?)""",
                (f"dm-{index}", user_id, f"patient-{user_id}", day, value, utc_now()),
            )


# --- matching -----------------------------------------------------------------


def test_matching_is_whole_word_bilingual_and_synonym_aware():
    def hit(query: str, *names: str):
        return search.score(search.parse(query), search.terms(names))

    assert hit("ALT", "Health score") is None, "«heALTh» is not ALT"
    assert hit("AST", "Activated partial thromboplastin time") is None
    assert hit("BMI", "Submitted material") is None
    assert hit("кір", "Осокір") is None
    assert hit("сон", "Цефтріаксон") is None
    assert hit("ЕКГ", "Перехідний епітелій") is None
    assert hit("АЛТ", "ALT") == search.EXACT, "script folds"
    assert hit("ЛПНП", "LDL cholesterol") == search.EXACT, "abbreviation table"
    assert hit("цукор", "Blood glucose") == search.EXACT
    assert hit("HRV", "Heart rate variability (SDNN)") == search.WHOLE_WORD
    assert hit("SpO2", "Blood oxygen saturation") == search.WHOLE_WORD
    assert hit("Lp(a)", "Lipoprotein(a)") == search.EXACT
    assert hit("аденома", "Фрагменти зубчастої аденоми") == search.PREFIX, "case ending"


def test_short_query_drops_word_starts_once_a_real_match_exists():
    ranked = search.rank(search.parse("Hb"), {
        "metrics": [(search.terms(["Hbs antigen"]), "hbs"), (search.terms(["Hemoglobin", "Hb"]), "hb")],
    })
    assert [item for _, item in ranked["metrics"]] == ["hb"]


def test_typing_a_word_never_loses_what_its_start_found():
    """Each longer prefix of «холестерин» used to find a different, smaller
    set: a case-ending hit («холестаз») hid every word start, and the English
    names came only with the finished word."""
    names = {
        "metrics": [
            (search.terms(["Total cholesterol", "Холестерин загальний"]), "total"),
            (search.terms(["LDL cholesterol"]), "ldl"),
            (search.terms(["Common bile duct diameter", "Холедох"]), "duct"),
        ],
        "findings": [(search.terms(["Ознаки холестазу"]), "cholestasis")],
    }
    found = {}
    for typed in ("холе", "холес", "холест", "холесте", "холестер", "холестери", "холестерин"):
        ranked = search.rank(search.parse(typed), names)
        found[typed] = {item for hits in ranked.values() for _, item in hits}
        assert {"total", "ldl"} <= found[typed], (typed, found[typed])
    assert found["холестерин"] == {"total", "ldl"}, "the finished word keeps only real matches"


# --- properties over a realistic bilingual record ---------------------------------
#
# Names as a Ukrainian lab, the concept catalog and an ultrasound report print
# them: Ukrainian and English, abbreviations on only some rows, inflected words
# inside report text, Synevo's Cyrillic «МСН».  The sandbox showed «лімфоцити»
# 5 results, «лімфо» 1, «лім» 0 and «л» a scattered handful; these tests encode
# the properties that rule all of that out, not the numbers.

RECORD = {
    "metrics": [
        (search.terms(["Лімфоцити", "Lymphocytes", "LYM%"]), "lym-pct"),
        (search.terms(["Лімфоцити, абсолютна кількість (LYM#)", "Lymphocytes, absolute"]), "lym-abs"),
        (search.terms(["Атипові лімфоцити", "Atypical lymphocytes"]), "lym-atypical"),
        (search.terms(["Реактивні лімфоцити"]), "lym-reactive"),
        (search.terms(["Білок загальний", "Total protein"]), "protein"),
        (search.terms(["Білок у сечі", "Urine protein"]), "urine-protein"),
        (search.terms(["С-реактивний білок", "C-reactive protein", "СРБ"]), "crp"),
        (search.terms(["Білірубін загальний", "Total bilirubin"]), "bilirubin"),
        (search.terms(["Холестерин загальний", "Total cholesterol"]), "cholesterol"),
        (search.terms(["Холестерин ЛПНЩ", "LDL cholesterol"]), "ldl"),
        (search.terms(["Гемоглобін", "Hemoglobin", "Hb"]), "hb"),
        (search.terms(["Середній вміст гемоглобіну в еритроциті (МСН)"]), "mch"),
        (search.terms(["Помідор Sola l", "Tomato"]), "tomato"),
        (search.terms(["Ліпаза", "Lipase"]), "lipase"),
    ],
    "findings": [
        (search.terms(["Збільшені лімфовузли шиї", "Реактивна лімфаденопатія"]), "nodes"),
        (search.terms(["Сліди білка в сечі"]), "trace-protein"),
        (search.terms(["Підвищений рівень холестерину"]), "high-cholesterol"),
        (search.terms(["Кількість лімфоцитів у межах норми"]), "lym-text"),
        (search.terms(["Комп’ютерна томографія органів грудної клітки"]), "ct"),
    ],
    "documents": [
        (search.terms(["Загальний аналіз крові"], ["Лімфоцити", "Гемоглобін"]), "cbc"),
        (search.terms(["Ліпідограма"], ["Холестерин загальний", "LDL cholesterol"]), "lipids"),
    ],
}


def _found(query: str) -> set[str]:
    ranked = search.rank(search.parse(query), RECORD)
    return {item for hits in ranked.values() for _, item in hits}


LYMPHOCYTE_RESULTS = {"lym-pct", "lym-abs", "lym-atypical", "lym-reactive"}


def test_a_beginning_finds_at_least_what_the_whole_word_finds():
    for word in ("лімфоцити", "лімфоцитів", "білок", "білка", "холестерину", "гемоглобін",
                 "lymphocytes", "cholesterol", "загальний білок"):
        for size in range(search.MIN_LETTERS, len(word)):
            shorter, longer = word[:size], word[:size + 1]
            if search.parse(shorter).short:
                continue
            missing = _found(longer) - _found(shorter)
            assert not missing, (shorter, longer, missing)


def test_ukrainian_case_endings_find_the_same_results():
    for form in ("лімфоцити", "лімфоцитів", "лімфоцитах", "лімфоцитами", "лімфоцит"):
        assert LYMPHOCYTE_RESULTS <= _found(form), form
    for form in ("білок", "білка", "білки", "білком"):
        assert {"protein", "urine-protein", "crp", "trace-protein"} <= _found(form), form
    assert "bilirubin" not in _found("білка"), "a case ending is not a word start"
    for form in ("холестерин", "холестерину", "холестерином"):
        assert {"cholesterol", "ldl", "high-cholesterol", "lipids"} <= _found(form), form
    assert {"protein"} == _found("загальний білок") & {"protein", "urine-protein", "crp"}
    # An inflected word names its synonyms as the dictionary form does.
    english_only = {"m": [(search.terms(["LYM#"]), "lym"), (search.terms(["Total cholesterol"]), "chol")]}
    for typed, item in (("лімфоцитів", "lym"), ("лімфоцитах", "lym"), ("холестерину", "chol")):
        assert [hit for _, hit in search.rank(search.parse(typed), english_only)["m"]] == [item], typed


def test_abbreviations_and_english_names_reach_every_matching_result():
    for query in ("LYM", "lymphocytes", "Lymphocyte", "лімфоцити"):
        assert LYMPHOCYTE_RESULTS <= _found(query), query
    assert "cbc" in _found("LYM"), "a document by the results it reports"
    assert {"ldl", "lipids"} <= _found("ЛПНЩ")


def test_lookalike_letters_and_apostrophes_never_decide_a_match():
    assert LYMPHOCYTE_RESULTS <= _found("лiмфоцити"), "Latin i typed inside a Cyrillic word"
    assert LYMPHOCYTE_RESULTS <= _found("ЛIМФОЦИТИ")
    assert "mch" in _found("MCH"), "Synevo's Cyrillic «МСН» is the Latin abbreviation"
    assert "mch" in _found("МСН")
    for spelling in ("комп'ютерна", "компʼютерна", "компютерна"):
        assert "ct" in _found(spelling), spelling


def test_short_queries_find_whole_words_only_and_say_so():
    assert search.parse("л").short and search.parse("лі").short and search.parse("Hb").short
    assert not search.parse("лім").short and not search.parse("щит").short
    assert search.parse("щ").short, "letters are counted as typed, not as transliterated"
    assert _found("л") == set(), "one letter finds nothing, though «Sola l» has it as a word"
    assert _found("лі") == set(), "two letters are no word start"
    assert _found("Hb") == {"hb", "cbc"}, "and the blood count reporting it"
    assert LYMPHOCYTE_RESULTS | {"nodes", "lym-text"} <= _found("лім")


def test_a_whole_word_elsewhere_never_hides_word_starts():
    """«лімфо» is a whole word in one biopsy report; it used to drop every
    lymphocyte result from the page."""
    groups = {
        "metrics": [(search.terms(["Лімфоцити"]), "lymphocytes")],
        "findings": [(search.terms(["Вогнищева лімфо плазмоцитарна інфільтрація"]), "biopsy")],
    }
    ranked = search.rank(search.parse("лімфо"), groups)
    assert ranked == {"metrics": [(search.PARTIAL, "lymphocytes")], "findings": [(search.WHOLE_WORD, "biopsy")]}
    mixed = search.rank(search.parse("білок"), {"m": [
        (search.terms(["Білковий обмін"]), "fractions"), (search.terms(["Сліди білка"]), "trace"),
        (search.terms(["Білок загальний"]), "protein"),
    ]})["m"]
    assert [item for _, item in mixed] == ["protein", "trace", "fractions"], "whole word, case ending, word start"


# --- the endpoint ---------------------------------------------------------------


def test_search_reaches_names_in_both_languages_whatever_the_ui_locale(tmp_path: Path):
    _, _, client = build(tmp_path)
    for locale in ("en", "uk"):
        client.cookies.set("anamna_lang", locale)
        for query in ("LDL", "ЛПНЩ", "ЛПНП", "ldl cholesterol"):
            payload = _api(client, q=query)
            assert payload["order"][0] == "metrics", (locale, query)
            assert 'href="/metrics/ldl-cholesterol"' in payload["html"], (locale, query)
            assert "/metrics/hdl-cholesterol" not in payload["html"], (locale, query)
        payload = _api(client, q="haemoglobin")
        assert "/metrics/hemoglobin" in payload["html"]


def test_search_finds_documents_by_provider_kind_and_date(tmp_path: Path):
    _, _, client = build(tmp_path)
    for query in ("Test Lab", "13.02.2025", "2025-02-13", "laboratory"):
        payload = _api(client, q=query)
        assert payload["totals"].get("documents") == 1, query
        assert 'href="/documents/doc-1"' in payload["html"], query


def test_search_finds_report_conclusions_in_either_language(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _seed_finding(settings, user_id)
    for query in ("аденома", "adenoma"):
        payload = _api(client, q=query)
        assert payload["totals"].get("findings") == 1, query
        assert "зубчастої аденоми" in payload["html"]


def test_search_renders_the_vaccination_group(tmp_path: Path, monkeypatch):
    _, _, client = build(tmp_path)

    def entries(connection, owner_user_id, locale):
        return [{"kind": "vaccination", "title": "Boostrix", "subtitle": "2024-03-01",
                 "url": "/vaccinations#dose-1", "terms": ["DTaP", "GlaxoSmithKline", "tetanus", "правець"]}]

    monkeypatch.setattr(immunizations, "search_entries", entries, raising=False)
    for query in ("правець", "tetanus", "Boostrix", "Бустрікс", "щеплення"):
        payload = _api(client, q=query)
        assert payload["order"][0] == "vaccinations", query
        assert 'href="/vaccinations#dose-1"' in payload["html"], query


# --- /insights retired into the /results filters ----------------------------------


def test_filters_replace_the_insights_page(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _seed_finding(settings, user_id)
    attention = client.get("/results?show=attention").text
    assert "/metrics/ldl-cholesterol" in attention
    assert "/metrics/hdl-cholesterol" not in attention
    assert "зубчастої аденоми" in attention, "an attention finding is a priority (CLIN-27)"
    unverified = client.get("/results?show=unverified").text
    assert 'data-chip="unverified" data-tone="due" aria-current="page"' in unverified
    assert "an-change__unverified" in unverified, "every row names that it still awaits checking"
    page = client.get("/results").text
    assert "autofocus" not in page, "UX-25"
    assert "/insights" not in client.get("/").text


def test_landing_groups_the_record_by_body_system_with_one_honest_count(tmp_path: Path):
    """The no-query /results was a 7,400 px flat list: 40 paged lab rows, then
    every device row saying "No comparison available", under "113 shown"
    beside a group headed "595"."""
    settings, user_id, client = build(tmp_path)
    _seed_steps(settings, user_id, {"2026-01-01": 7000, "2026-01-02": 8000})
    html = client.get("/results").text
    web.invalidate_catalog()
    with connect(settings) as connection:
        cards = web._metric_catalog(connection, user_id)
    lab = sum(1 for card in cards if not card["is_device"])
    # The "All results" chip counts laboratory results; device measurements sit apart.
    assert re.search(rf'data-chip="all"[^>]*>All results <span>{lab}</span>', html), lab
    # Section counts add up to the card count: each card sits in one section.
    sections = re.findall(r'data-section="([^"]+)"', html)
    totals = [int(n) for n in re.findall(r'<small>(\d+) results?', html)]
    assert len(sections) == len(totals) and sum(totals) == len(cards)
    # The section with the abnormal LDL opens, attention first; devices stay closed.
    heart = html.split('data-section="area-heart"')[1].split("</details>")[0]
    assert heart.startswith(" open") and heart.index("ldl-cholesterol") < heart.index("hdl-cholesterol")
    device = re.search(r'<details[^>]*data-section="devices"[^>]*>', html).group(0)
    assert " open" not in device, "device measurements are one closed disclosure"
    # No verdict text where there is nothing to compare; the bar is named in words.
    assert "No comparison available" not in html
    assert "What the marks and labels mean" in html and "Sources disagree" in html
    assert 'class="metric-chip-row metric-chip-row--areas"' not in html


# A stale PDF reading of a measurement the cuff has since re-measured is no
# longer a separate card to be hidden by display name; the twin is one card
# judged on its newest reading. See
# test_linked_metrics.py::test_stale_pdf_reading_is_not_an_attention_item.


# --- home ---------------------------------------------------------------------


def test_home_never_headlines_a_day_still_being_recorded(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    _seed_steps(settings, user_id, {(today - timedelta(days=2)).isoformat(): 7000, yesterday: 8326, today.isoformat(): 0})
    monkeypatch.setattr(
        web.device_queries, "is_partial_day",
        lambda metric_key, day, tz: day == today.isoformat(), raising=False,
    )
    web.invalidate_catalog()
    with connect(settings) as connection:
        cards = web._complete_days(connection, user_id, web._metric_catalog(connection, user_id))
    steps = next(card for card in cards if card["id"] == "device:steps")
    assert steps["latest_date"] == yesterday and steps["value_numeric"] == 8326
    assert all(point["date"] < today.isoformat() for point in steps["series"])


def test_home_leads_with_priorities_and_points_tiles_at_filters(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _seed_finding(settings, user_id)
    web.invalidate_catalog()
    page = client.get("/").text
    assert page.index("home-priorities-heading") < page.index("home-status-heading")
    assert "/metrics/ldl-cholesterol" in page.split("home-status-heading")[0]
    assert "зубчастої аденоми" in page, "the attention finding is on the home page"
    assert 'href="/results?show=attention"' in page and 'href="/results?show=due&amp;group=panel"' in page
    assert "home-destinations-heading" not in page, "the nav-copy tiles are gone (UX-02)"
    # The unverified tile counts results (eight extracted rows), not review tasks (one).
    tile = page.split('href="/documents?review_state=open" data-tone="due"')[1].split("</a>")[0]
    assert ">8<" in tile.replace(" ", "")


def test_area_with_only_a_conclusion_counts_its_document(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _seed_finding(settings, user_id, status="information")
    web.invalidate_catalog()
    page = client.get("/").text
    digestive = page.split('href="/areas/digestive"')[1].split("</a>")[0]
    assert "1 document" in digestive


# --- test groups ----------------------------------------------------------------


def test_test_groups_list_the_attention_sections_first(tmp_path: Path):
    """Grouped by test group, a group holding an attention result opens and
    leads; the groups with nothing to attend to follow it."""
    _, _, client = build(tmp_path)
    web.invalidate_catalog()
    page = client.get("/results?group=panel").text
    assert 'data-section="panel-lipids" open' in page, "the abnormal LDL opens its group"
    attention = [page.index(f'data-section="panel-{key}"') for key in ("vitamins", "lipids")]
    quiet = [page.index(f'data-section="panel-{key}"') for key in ("kidney", "cbc")]
    assert max(attention) < min(quiet), "attention leads"


REDIRECTS = [
    ("/metrics", "/results"),
    ("/metrics?q=alt", "/results?q=alt"),
    ("/metrics?status=attention", "/results?show=attention"),
    ("/metrics?status=unverified", "/results?show=unverified"),
    ("/metrics?status=due", "/results?show=due&group=panel"),
    ("/metrics?status=oldest", "/results?group=panel&sort=date&reverse=1"),
    ("/metrics?area=heart", "/results?area=heart"),
    ("/panels", "/results?group=panel"),
    ("/changes", "/results?episode=latest"),
    ("/insights", "/results?show=attention"),
]


@pytest.mark.parametrize(("path", "location"), REDIRECTS)
def test_retired_list_pages_answer_301_to_results(tmp_path: Path, path: str, location: str):
    _, _, client = build(tmp_path)
    moved = client.get(path, follow_redirects=False)
    assert moved.status_code == 301
    assert moved.headers["location"] == location


def test_a_search_lists_a_laboratory_result_as_a_result_row(tmp_path: Path):
    _, _, client = build(tmp_path)
    page = client.get("/results", params={"q": "LDL cholesterol"}).text
    assert '<li class="an-res" data-bucket="new" data-attention="true">' in page
    assert '<a class="an-res__name" href="/metrics/ldl-cholesterol">LDL cholesterol</a>' in page


def test_a_document_is_found_by_the_results_it_reports(tmp_path: Path):
    """The lipid panel's title says nothing about cholesterol; its rows do."""
    _, _, client = build(tmp_path)
    for query in ("холестерин", "LDL", "cholesterol"):
        payload = _api(client, q=query)
        assert payload["totals"].get("documents") == 1, query
        assert 'href="/documents/doc-1"' in payload["html"], query


def test_the_result_groups_keep_one_order_as_the_word_grows(tmp_path: Path):
    """Results first, then conclusions, then documents, whichever matched
    best: «холесте» and «холестерин» must not swap the sections round."""
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO clinical_findings(
                   id, owner_user_id, patient_id, document_id, page_number, health_area, title,
                   summary_en, original_text, finding_date, status, created_at)
               VALUES ('finding-chol', ?, ?, 'doc-1', 1, 'digestive', 'Ultrasound', '',
                       'Ознаки холестерозу жовчного міхура', '2025-11-12', 'attention', ?)""",
            (user_id, f"patient-{user_id}", utc_now()),
        )
        connection.commit()
    orders = {typed: _api(client, q=typed)["order"] for typed in ("холесте", "холестер", "холестерин")}
    for typed, order in orders.items():
        assert order[0] == "metrics", (typed, order)
        present = [key for key in ("metrics", "findings", "documents") if key in order]
        assert present == sorted(present, key=["metrics", "findings", "documents"].index), (typed, order)


GROUP_ORDER = ["metrics", "device_metrics", "panels", "vaccinations", "findings", "documents", "areas"]


def _seed_findings(settings, user_id: str, count: int) -> None:
    with connect(settings) as connection:
        for index in range(count):
            connection.execute(
                """INSERT INTO clinical_findings(
                       id, owner_user_id, patient_id, document_id, page_number, health_area, title,
                       summary_en, original_text, finding_date, status, created_at)
                   VALUES (?, ?, ?, 'doc-1', ?, 'liver', 'Ultrasound', '',
                           ?, '2025-11-12', 'information', ?)""",
                (f"finding-{index}", user_id, f"patient-{user_id}", index + 1,
                 f"Дифузні зміни печінки, ділянка {index}", utc_now()),
            )
        connection.commit()


def test_every_group_keeps_the_fixed_order_and_counts_what_it_lists(tmp_path: Path):
    """A heading's count is what can be opened on this page: the first dozen
    are listed, the rest fold under "Show N more", none is a link to a
    different search that counts differently."""
    settings, user_id, client = build(tmp_path)
    _seed_findings(settings, user_id, 15)
    for typed in ("печ", "печінка", "печінки", "liver", "холестерин", "LDL", "лабораторія"):
        order = _api(client, q=typed)["order"]
        assert order == sorted(order, key=GROUP_ORDER.index), (typed, order)
    payload = _api(client, q="печінки")
    assert payload["totals"]["findings"] == 15
    section = payload["html"].split('data-group="findings"')[1].split("</section>")[0]
    listed, folded = section.split('<details class="an-result-more">')
    assert listed.count(" an-result-row\"") == 12
    assert folded.count(" an-result-row\"") == 3 and "Show 3 more" in folded
    assert 'href="/documents?q=' in payload["html"], "the search inside report text is one link away"


def test_short_queries_explain_themselves_in_both_languages(tmp_path: Path):
    _, _, client = build(tmp_path)
    texts = {
        "en": ("Type a few more letters", "Type at least 3 letters to search by the beginning of a word"),
        "uk": ("Введіть ще кілька літер", "Введіть щонайменше 3 літери, щоб шукати за початком слова"),
    }
    for locale, (title, explanation) in texts.items():
        client.cookies.set("anamna_lang", locale)
        single = _api(client, q="L")
        assert single["order"] == [] and title in single["html"] and explanation in single["html"], locale
        two = _api(client, q="Hb")
        assert "/metrics/hemoglobin" in two["html"] and explanation in two["html"], locale
        full = _api(client, q="hemo")
        assert "/metrics/hemoglobin" in full["html"] and explanation not in full["html"], locale
