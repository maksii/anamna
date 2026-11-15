"""What a reader and the assistant are shown about a calculated result."""
from __future__ import annotations

import re

import pytest

from anamna.calculation_info import CALCULATION_URLS
from anamna.i18n import activate_locale, reset_locale, translate_phrase
from anamna.locales.messages import MESSAGES
from anamna.web import ai_export, chat_routes
from anamna.web.app import templates

UUID = "3f2b8c1e-9d4a-5e6f-8a7b-0c1d2e3f4a5b"
LAB_EVIDENCE = (
    "MCH (pg) = Hb (g/L) / RBC (10^12/L)\n"
    f'{UUID}: 150 g/L; {{"document_id": "{UUID}", "unit_raw": "г/л"}}; Гемоглобін 150 г/л'
)
EGFR_EVIDENCE = f"CKD-EPI 2021: Scr=0.9 mg/dL; age=34; sex=male; input_id={UUID}; unit_raw='мкмоль/л'; Креатинін 80"


@pytest.fixture(params=["en", "uk"])
def lang(request):
    token = activate_locale(request.param)
    yield request.param
    reset_locale(token)


def _macro(template: str, name: str):
    return getattr(templates.env.get_template(template).module, name)


def test_every_calculation_method_explains_itself_in_both_languages():
    for method in CALCULATION_URLS:
        entry = MESSAGES.get("doc." + method)
        assert entry and entry.get("en") and entry.get("uk"), method


def test_the_assistant_never_reads_a_raw_message_key(lang):
    for method in CALCULATION_URLS:
        assert "doc." not in ai_export._calculation_text({"extraction_method": method}).split("http")[0], method


@pytest.mark.parametrize(("method", "evidence", "formula"), [
    ("derived_mch", LAB_EVIDENCE, "MCH (pg) = Hb (g/L) / RBC (10^12/L)"),
    ("derived_ckd_epi_2021", EGFR_EVIDENCE, "CKD-EPI 2021: Scr=0.9 mg/dL"),
])
def test_calculated_row_quotes_the_formula_and_no_machine_record(lang, method, evidence, formula):
    html = str(_macro("_components.html", "observation_row")({
        "id": "row", "concept_id": "c", "canonical_name": "Hemoglobin", "raw_name": "Hemoglobin",
        "verification_status": "extracted", "extraction_method": method, "evidence_text": evidence,
        "page_number": 1, "display_value": "30", "unit_text": "pg", "value_numeric": 30,
    }))
    quote = re.search(r"<q>(.*?)</q>", html, re.S).group(1)
    assert quote == formula
    assert MESSAGES["doc." + method][lang] in html
    visible = html.split("<details", 1)[0]
    assert UUID not in visible and "{" not in visible and "input_id" not in visible


def test_a_printed_row_still_quotes_its_whole_source_line(lang):
    html = str(_macro("_components.html", "observation_row")({
        "id": "row", "concept_id": "c", "canonical_name": "Hemoglobin", "raw_name": "Hemoglobin",
        "verification_status": "extracted", "extraction_method": "text", "evidence_text": "Hb 150 g/L; ref 130-170",
        "page_number": 1, "display_value": "150", "unit_text": "g/L", "value_numeric": 150,
    }))
    assert "<q>Hb 150 g/L; ref 130-170</q>" in html


@pytest.mark.parametrize(("item", "auto", "key"), [
    ({"extraction_method": "derived_mch", "verification_status": "extracted"}, False, "calc.provisional"),
    ({"extraction_method": "derived_bmi"}, True, "calc.provisional_auto"),
    ({"extraction_method": "derived_bmi", "is_device": True}, False, "calc.provisional_auto"),
    ({"extraction_method": "derived_profile_bmi", "is_profile": True}, False, "calc.provisional_auto"),
])
def test_only_a_result_that_can_be_confirmed_asks_to_be_checked(lang, item, auto, key):
    html = str(_macro("_components.html", "calculation_details")(item, auto=auto))
    for candidate in ("calc.provisional", "calc.provisional_auto"):
        assert (MESSAGES[candidate][lang] in html) == (candidate == key)


def test_device_day_says_calculated_and_from_what_without_repeating_the_formula(lang):
    day = {"day": "2026-02-03", "value": 20.0, "extraction_method": "derived_bmi", "calculation_inputs": [
        {"input_kind": "device_weight", "input_value": 80, "input_unit": "kg", "input_day": "2026-02-03"}]}
    text = ai_export._device_day(day)
    assert MESSAGES["calc.status"][lang] in text and MESSAGES["calc.input_device_weight"][lang] in text
    assert "http" not in text and MESSAGES["doc.derived_bmi"][lang] not in text
    assert ("80 кг" if lang == "uk" else "80 kg") in text
    assert ai_export._device_day({"day": "2026-02-03", "value": 20.0}) == "2026-02-03 20"


def test_adjacent_calculated_history_rows_both_say_so(lang):
    item = {"observed_at": "2026-02-03", "display_value": "30", "display_unit": "pg",
            "extraction_method": "derived_mch", "vendor": "Lab", "document_id": "d"}
    sources = type("NoSources", (), {"ref": staticmethod(lambda *_: "")})()
    context = chat_routes._history_context(item, sources)
    first = chat_routes._history_text(item, context, dict.fromkeys(context))
    second = chat_routes._history_text(item, context, context)
    assert context["calculation"] and context["calculation"] in first and context["calculation"] in second
    assert context["source"] in first and context["source"] not in second


@pytest.mark.parametrize("guidance", [
    {"no_universal_target_reason": "Depends on the assay."},
    {"jurisdiction_note": "EU and US differ."},
    {"sources": [{"url": "https://example.org/s", "publisher": "WHO", "name": "Guide"}]},
])
def test_guidance_with_only_a_reason_a_note_or_sources_is_shown(lang, guidance):
    html = str(_macro("_experience.html", "metric_about")(guidance, None))
    assert "<details" in html and MESSAGES["metric.what_it_measures"][lang] in html
    assert str(next(iter(guidance.values()))) in html or "https://example.org/s" in html


def test_metric_about_stays_silent_without_guidance():
    assert "<details" not in str(_macro("_experience.html", "metric_about")({}, None))


def test_counts_are_not_welded_to_an_english_noun():
    for key in ("ai.calculated_days", "panel.context_coverage"):
        assert not MESSAGES[key]["en"].startswith("{"), key


def test_device_body_temperature_has_a_ukrainian_name():
    token = activate_locale("uk")
    try:
        assert translate_phrase("Body temperature") == "Температура тіла"
    finally:
        reset_locale(token)
