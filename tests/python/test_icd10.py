"""The bundled ICD-10 catalogue reader (anamna.icd10) over data/icd10.json."""

from __future__ import annotations

import importlib.util
import json
import re

from anamna import icd10
from anamna.config import ROOT


def test_normalize_maps_cyrillic_lookalikes_case_and_separators():
    assert icd10.normalize("К11,2") == "K11.2"
    assert icd10.normalize(" e11.2 ") == "E11.2"
    assert icd10.normalize("e 78") == "E78"
    assert icd10.normalize("E78,2") == "E78.2"


def test_normalize_rejects_what_is_not_a_code():
    assert icd10.normalize("ABC") == ""
    assert icd10.normalize("E7") == ""
    assert icd10.normalize("") == ""


def test_entry_reads_a_three_character_code_with_its_chapter_and_block():
    row = icd10.entry("E78.2")
    assert row is not None
    assert row["code"] == "E78.2"
    assert row["uk"] == "Змішана гіперліпідемія"
    assert row["en"] == "Mixed hyperlipidaemia"
    assert row["en_exact"] is True
    assert row["category"] == "E78"
    assert row["chapter"]["number"] == "IV"
    start, end = row["block"]["range"].split("-")
    assert start <= "E78" <= end


def test_entry_of_an_unknown_code_is_none():
    assert icd10.entry("A99.9") is None
    assert icd10.entry("ABC") is None


def test_entry_of_an_amendment_code_falls_back_to_the_nearest_who_ancestor():
    row = icd10.entry("E11.21")
    assert row is not None
    assert row["en_exact"] is False
    assert row["en"] != ""


def test_name_in_each_locale_and_english_falls_back_to_ukrainian():
    assert icd10.name("E78.2", "uk") == "Змішана гіперліпідемія"
    assert icd10.name("E78.2", "en") == "Mixed hyperlipidaemia"
    # E09 is an Australian (ICD-10-AM) category WHO does not title: its English title comes from
    # AM_ONLY_TITLES, and the leaf below it inherits that title as an ancestor (en_exact 0).
    assert icd10.name("E09", "en") == "Intermediate hyperglycaemia"
    assert icd10.name("E09.9", "en") == "Intermediate hyperglycaemia"
    assert icd10.entry("E09.9")["en_exact"] is False
    assert icd10.entry("B59")["en"] == "Pneumocystosis"
    assert icd10.name("A99.9", "en") == ""


def test_is_condition_excludes_external_causes_u_codes_and_encounter_reasons():
    assert icd10.is_condition("Z25.8") is False
    assert icd10.is_condition("V85.4") is False
    assert icd10.is_condition("W90") is False
    assert icd10.is_condition("U07.1") is False


def test_is_condition_keeps_diagnoses_and_later_z_codes():
    assert icd10.is_condition("Z95.0") is True
    assert icd10.is_condition("E78.2") is True
    assert icd10.is_condition("I10") is True
    assert icd10.is_condition("Z80") is True


def test_search_by_code_prefix_lists_the_category_first_then_its_codes():
    codes = [row["code"] for row in icd10.search("e78", "uk", limit=50)]
    assert codes[0] == "E78"
    assert codes[1:4] == ["E78.0", "E78.1", "E78.2"]
    assert all(code.startswith("E78") for code in codes)


def test_search_by_ukrainian_words():
    codes = [row["code"] for row in icd10.search("гіперліпідемія", "uk", limit=50)]
    assert "E78.2" in codes


def test_search_finds_a_ukrainian_word_with_stray_latin_letters_in_the_query():
    assert "E78" in [row["code"] for row in icd10.search("ліпідемії", "uk")]
    assert "E78" in [row["code"] for row in icd10.search("лiпiдемiї", "uk")]


def test_ukrainian_titles_carry_no_latin_letters_inside_cyrillic_words():
    assert not re.search(r"[A-Za-z]", icd10.entry("E78")["uk"])
    # A word that is entirely Latin is a real word and stays as written.
    assert "Escherichia" in icd10.entry("A04.0")["uk"]


def test_repair_uk_turns_look_alikes_back_inside_cyrillic_words_only():
    spec = importlib.util.spec_from_file_location("build_icd10", ROOT / "scripts/build_icd10.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    assert build.repair_uk("лiпiдемiї") == "ліпідемії"
    assert build.repair_uk("Escherichia") == "Escherichia"
    assert build.repair_uk("IgE") == "IgE"
    assert build.repair_uk("E78") == "E78"


def test_search_by_english_words():
    codes = [row["code"] for row in icd10.search("mixed hyperlipidaemia", "en", limit=50)]
    assert "E78.2" in codes


def test_search_returns_names_in_the_requested_locale():
    row = next(r for r in icd10.search("e78.2", "en") if r["code"] == "E78.2")
    assert row == {"code": "E78.2", "name": "Mixed hyperlipidaemia"}


def test_blank_query_returns_nothing():
    assert icd10.search("", "uk") == []
    assert icd10.search("   ", "en") == []
    assert icd10.search("a", "en") == []


def test_search_honours_the_limit():
    assert len(icd10.search("e11", "uk", limit=3)) == 3
    assert icd10.search("e11", "uk", limit=0) == []


def _catalogue() -> dict:
    return json.loads((ROOT / "data/icd10.json").read_text(encoding="utf-8"))


def test_search_never_offers_encounter_reason_codes():
    # Z25.8 and Z23-type codes carry this word, so the filter is genuinely exercised.
    word = "імунізації"
    in_catalogue = [code for code, (uk, _, _) in _catalogue()["codes"].items() if word in uk.casefold()]
    assert any(code.startswith("Z") and code[1:3] <= "79" for code in in_catalogue)
    results = icd10.search(word, "uk", limit=200)
    assert all(not (row["code"].startswith("Z") and row["code"][1:3] <= "79") for row in results)
    assert all(icd10.is_condition(row["code"]) for row in results)


def test_every_code_is_well_formed_and_has_a_ukrainian_title():
    data = _catalogue()
    pattern = re.compile(r"[A-Z][0-9]{2}(\.[0-9]{1,2})?")
    assert data["codes"]
    for code, (uk, en, exact) in data["codes"].items():
        assert pattern.fullmatch(code), code
        assert uk.strip(), code
        assert exact in (0, 1), code


def test_chapter_of_endocrine_codes_is_spelled_with_two_н():
    assert icd10.entry("E78.2")["chapter"]["uk"].startswith("Ендокринні")


def test_myasthenia_gravis_title_has_gravis_as_its_own_latin_word():
    assert icd10.entry("G70")["uk"].startswith("Міастенія gravis")


def test_stage_iv_roman_numeral_is_written_in_latin_letters():
    assert icd10.entry("L89.3")["uk"].split()[-1] == "IV"


def test_gm2_gangliosidosis_title_has_latin_gm2():
    assert "GM2" in icd10.entry("E75.0")["uk"]


def test_no_ukrainian_title_has_a_word_mixing_cyrillic_and_latin_letters():
    data = _catalogue()
    titles = [row["uk"] for row in [*data["chapters"], *data["blocks"]]]
    titles += [uk for uk, _, _ in data["codes"].values()]
    mixed = {
        word
        for title in titles
        for word in re.findall(r"[^\W\d_]+", title)
        if re.search("[Ѐ-ӿ]", word) and re.search("[A-Za-z]", word)
    }
    assert mixed == set(), sorted(mixed)
