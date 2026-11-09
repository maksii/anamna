"""Special tests (testplan_special): markers find the same kind of test at
both labs by name and nothing else, every entry and marker reads in both
languages, the solver answers an entry with the cheapest mix, and the
planner's special mode lists, ticks and plans them."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from anamna import labsync, testplan, testplan_special, testplan_value
from anamna.labsync import esculab_shop
from anamna.locales.messages import MESSAGES
from anamna.security import create_session
from anamna.web import testplan_routes
from anamna.web.app import create_app

from test_testplan import RICH, record  # noqa: F401 -- `record` is a fixture


def item(name, kind_groups=(), parameters=1, **extra):
    return {"id": name, "name": name, "groups": list(kind_groups),
            "parameters": [{"id": f"{name}:{n}", "name": name} for n in range(parameters)], **extra}


# Real names from the Esculab and Synevo price lists (November 2026).
GENETIC = ("Генетичні дослідження",)
MATCHES = {
    "sp:allergy-multiplex": ["Мультикомпонентний алерготест ALEX-3 (визначення рівня загального IgE і специфічних IgE до 300 алергенів)",
                             "ALEX3-тест (молекулярний аналіз на 300 алергенів, антитіла IgE)"],
    "sp:allergy-inhalant": ["Пакет №606 (Алергени. Астма/риніт Дорослий)", "Інгаляційна панель №1 (20 алергенів, Polycheck)"],
    "sp:gen-lactose": ["ПЛР. Генетика. Лактозна непереносимість (13910 T>C, кров)"],
    "sp:gen-f5": ["ПЛР. Тромбофілія. Ген F5-Leiden (1691G>A)",
                  "Спадкові тромбофілічні чинники. Лейденська мутація фактора V зсідання крові (FVL)"],
    "sp:gen-f2": ["ПЛР. Тромбофілія. Ген F2-протромбін (20210 G>A)",
                  "Спадкові тромбофілічні чинники. Мутація фактора II протромбіну G20210A (FII)"],
    # Synevo writes the gene in Cyrillic lookalikes.
    "sp:gen-mthfr": ["ПЛР. Фолатний цикл. МТНFR (677 C>T)"],
    "sp:hiv": ["ВІЛ експрес-тест (якісне визначення) з підтвердженням"],
    "sp:covid": ["Коронавірус (SARS-CoV-2), антиген (назо-орофарингеальний зішкріб). Експрес-тест"],
}
NOT = {
    # «віл» in «вільний» is free T4, not HIV.
    "sp:hiv": ["Тироксин вільний (Т4 віл, FT4)"],
    # Children's panels and a nasal culture are not the adult hay fever panel.
    "sp:allergy-inhalant": ["Пакет ImmunoCAP. Астма/Риніт. Діти (10 алергенів)",
                            "Визначення аеробів, факул.анаеробів з АБЧ з МІС та грибів Candida spp. з АМЧ з МІС (СИНУСИТИ. ГАЙМОРИТИ. РИНІТИ)"],
    "sp:covid": ["Лабораторний індикатор (Neutrophil to lymphocyte ratio, NLR) прогнозу COVID-19"],
    "sp:gen-cftr": ["Генетичні чинники панкреатиту (СFTR, SPINK1)"],
    # A folate panel names MTHFR, but the clotting markers are other genes.
    "sp:gen-f5": ["Фолатний обмін MTHFR"],
}


@pytest.mark.parametrize(("key", "name"), [(k, n) for k, names in MATCHES.items() for n in names])
def test_a_marker_finds_its_test_by_name(key, name):
    kind = GENETIC if key.startswith("sp:gen-") else ()
    assert key in testplan_special.matches(item(name, kind))


@pytest.mark.parametrize(("key", "name"), [(k, n) for k, names in NOT.items() for n in names])
def test_a_marker_leaves_other_tests_alone(key, name):
    kind = GENETIC if key.startswith("sp:gen-") else ()
    assert key not in testplan_special.matches(item(name, kind))


def test_a_marker_is_a_key_to_cover_not_a_result_the_item_reports():
    found = testplan_special.tag([{**item("ПЛР. Генетика. Лактозна непереносимість (13910 T>C, кров)", GENETIC),
                                   "keys": ["synevo:3201"], "parameter_keys": [["synevo:3201"]]}])[0]
    assert found["keys"] == ["synevo:3201", "sp:gen-lactose"] and found["parameter_keys"] == [["synevo:3201"]]


def test_every_entry_and_marker_reads_in_both_languages():
    ids = {entry.id for entry in testplan_special.ENTRIES}
    for entry in testplan_special.ENTRIES:
        for key in (f"special.{entry.id}", f"special.{entry.id}_what"):
            assert set(MESSAGES[key]) == {"en", "uk"} and all(MESSAGES[key].values()), key
        assert entry.topic in testplan_special.TOPICS
    for marker in testplan_special.MARKERS:
        assert f"special.{marker.id}" in MESSAGES, marker.id
    for topic in testplan_special.TOPICS:
        assert {"en", "uk"} <= set(MESSAGES[f"special.topic_{topic}"]) and f"special.topic_{topic}_hint" in MESSAGES
    # Entries own their keys: one entry per id, and markers referenced exist.
    assert len(ids) == len(testplan_special.ENTRIES)
    markers = {marker.key for marker in testplan_special.MARKERS}
    assert {k for e in testplan_special.ENTRIES for k in e.keys if k.startswith("sp:")} <= markers


def test_a_package_counts_for_the_tests_among_its_rows():
    package = {"name": "Пакет №191.2 (ПЛР. Генетика. Тромбофілія високого ризику)", "groups": list(GENETIC),
               "parameters": [{"name": "ПЛР. Тромбофілія. Ген F5-Leiden (1691G>A)"},
                              {"name": "ПЛР. Тромбофілія. Ген F2-протромбін (20210 G>A)"}]}
    assert {"sp:gen-f5", "sp:gen-f2"} <= set(testplan_special.matches(package))
    # A check-up's HIV row counts, whatever kind of item holds it.
    checkup = {"name": "Пакет №241. Інфекційний скринінг", "groups": [],
               "parameters": [{"name": "ВІЛ 1/2, антитіла та антиген p24"}, {"name": "HBsAg"}]}
    assert "sp:hiv" in testplan_special.matches(checkup)


def test_a_described_variant_list_counts_and_a_passing_mention_does_not():
    listed = {**item("Генетична панель «DNA Health» — 47 генів", GENETIC),
              "description": "HFE (гемохроматоз): C282Y та H63D rs1800562 MCM6 (лактоза): -13910 C>T rs4988235 "
                             "HLA (целіакія): DQ2 / DQ8 MTHFR 677 C>T rs1801133"}
    assert {"sp:gen-hemochromatosis", "sp:gen-lactose", "sp:gen-celiac", "sp:gen-mthfr"} \
        <= set(testplan_special.matches(listed))
    passing = {**item("ПЛР. Тромбофілія. Ген F2-протромбін (20210 G>A)", GENETIC),
               "description": "Разом із мутацією Лейдена F5 (1691 G>A) ризик тромбозу зростає."}
    assert "sp:gen-f5" not in testplan_special.matches(passing)


def test_a_gene_counts_only_on_a_panel_for_that_purpose():
    onco = {**item("GenPlan Onco — 252 гени", GENETIC), "genes": ["BRCA1", "BRCA2", "MLH1", "MSH2", "MSH6", "PMS2"],
            "description": "Спадкові форми раку: панель для оцінки ризику."}
    assert {"sp:gen-brca", "sp:gen-lynch"} <= set(testplan_special.matches(onco))
    # BRCA2 on a Fanconi anaemia panel is read for Fanconi anaemia.
    fanconi = {**item("Генетична панель «Анемія Фанконі» – 22 гени", GENETIC), "genes": ["BRCA1", "BRCA2", "FANCA"],
               "description": "Анемія Фанконі - спадкова недостатність кісткового мозку."}
    assert "sp:gen-brca" not in testplan_special.matches(fanconi)


def test_a_carrier_panel_counts_for_the_acmg_tier_it_states():
    tier3 = {**item("GenPlan Baby (Carrier Screening) — 787 генів", GENETIC),
             "description": "охоплюючи 787 генів та відповідає сучасним стандартам (рівень Tier 3 згідно з "
                            "рекомендаціями ACMG 2021 року)"}
    found = set(testplan_special.matches(tier3))
    assert {"sp:gen-tier3", "sp:gen-tier2", "sp:gen-cftr", "sp:gen-sma"} <= found
    # A carrier screen that states no tier answers cystic fibrosis and SMA only.
    plain = set(testplan_special.matches(item("Генетика. NGS. Скринінг CarrierSeq (420 генів)", GENETIC)))
    assert {"sp:gen-cftr", "sp:gen-sma"} <= plain and "sp:gen-tier3" not in plain
    assert "sp:gen-sma" not in testplan_special.matches(
        item("Спінальна м′язова атрофія. Гомозиготне носійство СМА (делеції 7-го та 8-го екзонів)", GENETIC))
    assert "sp:gen-celiac" in testplan_special.matches(item("Генетика. Целіакія", GENETIC))


def test_alex_answers_the_smaller_allergy_panels_too():
    found = testplan_special.matches(item("ALEX3-тест (молекулярний аналіз на 300 алергенів, антитіла IgE)"))
    assert {"sp:allergy-multiplex", "sp:allergy-inhalant", "sp:allergy-food", "x:sige:e1",
            "total-immunoglobulin-e"} <= set(found)
    # The panel does not answer for ALEX.
    assert "sp:allergy-multiplex" not in testplan_special.matches(item("Пакет №606 (Алергени. Астма/риніт Дорослий)"))


def test_two_gene_tests_cost_less_as_the_labs_package():
    def priced(name, price, keys):
        return {"id": name, "lab": "esculab", "name": name, "price": price, "final_price": price, "keys": keys,
                "parameters": [{"id": name, "name": name}], "parameter_keys": [keys], "fees": [],
                "groups": list(GENETIC)}
    items = testplan_special.tag([
        priced("Спадкові тромбофілічні чинники. Лейденська мутація фактора V зсідання крові (FVL)", 1080, ["esculab:1"]),
        priced("Спадкові тромбофілічні чинники. Мутація фактора II протромбіну G20210A (FII)", 1080, ["esculab:2"]),
        priced("Пакет №266. Спадкові тромбофілічні чинники. Лейденська мутація фактора V зсідання крові (FVL), "
               "мутація фактора II протромбіну G20210A (FII)", 1600, ["esculab:3"]),
    ])
    best = testplan_value.alternatives(items, set(testplan_special.BY_ID["gen-thrombophilia"].keys), limit=0)[0]
    assert best["cost"] == 1600 and [i["id"][:11] for i in best["items"]] == ["Пакет №266."]


# --- the page ------------------------------------------------------------------

HLA = {**RICH, "id": 3001, "name": "Виявлення носійства гену HLA B-27", "code": "O1", "price": 1595.0, "discount": 0.0,
       "parameters": [{"id": 9001, "name": "Виявлення носійства гену HLA B-27"}]}
LACTOSE = {**RICH, "id": 3002, "name": "Спадкова непереносимість лактози (кров). Виявлення методом ПЛР ДНК", "code": "O2",
           "price": 670.0, "discount": 0.0, "parameters": [{"id": 9002, "name": "Лактозна непереносимість"}]}


@pytest.fixture
def special_page(record, monkeypatch):  # noqa: F811
    """Esculab sells an HLA-B27 test and a lactose gene test; the record holds
    an HLA-B27 result from August 2025."""
    settings, user_id = record
    labsync.save_provider_settings(settings, "esculab", enabled=True, url="http://127.0.0.1:9")
    for key in [k for k in testplan_routes.SHOPS if k != "esculab"]:
        monkeypatch.delitem(testplan_routes.SHOPS, key)
    goods = [{**esculab_shop.item(good), "groups": list(GENETIC)} for good in (HLA, LACTOSE)]
    monkeypatch.setattr(esculab_shop, "catalog", lambda settings, region, base_url=None: goods)
    monkeypatch.setattr(esculab_shop, "regions", lambda settings, base_url=None: [{"id": "3201", "name": "Львів"}])
    cards = [{"id": "hla-b27", "name": "HLA-B27", "category": "immunogenetics", "is_device": False,
              "latest_date": "2025-08-29", "value_text": "Not detected", "unit": "", "date_text": "29 Aug 2025",
              "url": "/metrics/hla-b27", "staleness": {"state": "fresh"}, "verdict": {"interpretation": "normal"}}]
    monkeypatch.setattr("anamna.web.app._metric_catalog", lambda connection, owner: cards)
    monkeypatch.setattr(testplan, "lab_concepts", lambda connection, owner: {"hla-b27"})
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "en")
    return client


def test_the_switch_turns_the_page_to_special_tests(special_page):
    routine = special_page.get("/plan-tests").text
    assert 'role="switch" name="special"' in routine and "Built from your record" in routine
    # Routine checks no longer carry the packages browser.
    assert 'id="plan-sets"' not in routine and 'name="sx"' not in routine
    html = special_page.get("/plan-tests?special=1").text
    assert re.search(r'name="special" value="1" checked', html) and "Start from a question" in html
    # Like a preset, a topic shows only with something sold here (two gene tests).
    assert 'name="preset" value="genetics"' in html and 'value="allergy"' not in html
    assert "Pick a topic above or search for a test." in html and 'id="plan-sets"' in html
    special_page.cookies.set("anamna_lang", "uk")
    uk = special_page.get("/plan-tests?special=1").text
    assert "Спеціальні аналізи" in uk and "Ваша ДНК" in uk and "Почніть із питання" in uk


def test_a_topic_lists_its_tests_and_a_dna_test_done_stays_unticked(special_page):
    html = special_page.get("/plan-tests?special=1&touched=1&preset=genetics").text
    rows = re.findall(r'<input type="checkbox" name="sx" value="([\w-]+)"[^>]*>', html)
    assert "gen-hla-b27" in rows and "gen-lactose" in rows
    # Like a routine preset, the topic ticks what is sold here; HLA-B27 was
    # done and DNA does not change, so it stays unticked.
    assert re.search(r'name="sx" value="gen-lactose"[^>]* checked', html)
    assert not re.search(r'name="sx" value="gen-hla-b27"[^>]* checked', html)
    assert re.search(r'name="drop" value="genetics"\s+aria-pressed="true" data-preset-keys="gen-lactose"', html)
    assert "Selected: all 1" in html
    assert "Your DNA does not change, so it never needs repeating." in html
    # What no lab here sells cannot be ticked.
    assert re.search(r'name="sx" value="gen-brca"[^>]* disabled', html)
    assert '<input type="hidden" name="topic" value="genetics">' in html


def test_pressing_a_topic_again_takes_its_tests_off_the_list(special_page):
    html = special_page.get("/plan-tests?special=1&touched=1&topic=genetics&sx=gen-lactose&drop=genetics").text
    # As a routine preset takes its results away.
    assert 'name="sx" value="gen-lactose"' not in html and 'name="topic" value="genetics"' not in html
    assert "Pick a topic above or search for a test." in html
    # The topics stay open after a press, as the presets do.
    assert re.search(r'id="plan-presets" data-presets data-open', html)


def test_the_plan_covers_the_picked_tests_with_the_labs_items(special_page):
    html = special_page.get("/plan-tests?special=1&touched=1&topic=genetics&sx=gen-lactose&plan=1").text
    assert "Covers 1 of 1" in html and "Спадкова непереносимість лактози" in html
    assert "covers Lactose intolerance gene (LCT)" in html


def test_the_search_finds_a_test_in_either_language(special_page):
    live = special_page.get("/plan-tests/live?special=1&touched=1&q=лактоза").json()
    assert 'value="gen-lactose"' in live["found"] and "Tests for that" in live["found"]
    # The lab's own item is found below, to include as it is.
    assert 'name="include" value="esculab:3002"' in live["sets"]


ALEX = {**RICH, "id": 3003, "name": "ALEX3-тест (молекулярний аналіз на 300 алергенів, антитіла IgE)", "code": "O3",
        "price": 6100.0, "discount": 0.0, "parameters": [{"id": 9003, "name": "ALEX3"}]}


def test_every_allergen_an_entry_asks_for_has_a_name_in_both_languages():
    asked = {k.removeprefix("x:sige:") for e in testplan_special.ENTRIES for k in e.keys if k.startswith("x:sige:")}
    assert asked <= set(testplan_special.ALLERGENS)
    for code in testplan_special.ALLERGENS:
        names = MESSAGES[f"special.allergen_{code}"]
        assert set(names) == {"en", "uk"} and all(f"({code})" in name for name in names.values()), code


def test_an_allergen_sold_only_inside_alex_is_named_not_shown_as_a_key(special_page, monkeypatch):
    goods = [esculab_shop.item(ALEX)]
    monkeypatch.setattr(esculab_shop, "catalog", lambda settings, region, base_url=None: goods)
    html = special_page.get("/plan-tests?special=1&touched=1&topic=allergy&sx=allergy-ga2len&plan=1").text
    assert "Covers 18 of 18" in html and "Olive tree pollen (t9)" in html
    assert "x:sige:" not in re.sub(r'(value|data-[\w-]+)="[^"]*"', "", html)
