"""AI reference card for a factor: quote checking, normalisation and the payload sent to the model.

The provider is stubbed at the registry seam (as in test_ai_assist.py) and the
reference lookup is replaced, so nothing leaves the machine.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from anamna import ai, drugref, factor_research
from anamna.db import connect, migrate

from test_web_panels import settings_for


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the test reached the network")

    monkeypatch.setattr(urllib.request, "build_opener", refuse)


REFERENCE = {
    "url": "https://tabletki.ua/uk/Диокор/8311/",
    "sections": [
        ["Склад", "діючі речовини: валсартан, гідрохлоротіазид;\nдопоміжні речовини: лактоза."],
        ["Фармакологічні властивості",
         "Валсартан є антагоністом рецепторів ангіотензину II. "
         "Гідрохлоротіазид підвищує виведення натрію і калію."],
        ["Спосіб застосування", "Дорослим призначають 80 мг один раз на добу. Максимальна доза 320 мг."],
        ["Термін придатності", "3 роки."],
        ["Упаковка", "По 30 таблеток у блістері."],
        ["Виробник", "Acino Pharma AG, Швейцарія."],
    ],
    "atc": ["C09DA03"],
    "shown_for": "Диокор 80 мг",
}


def card(**overrides) -> str:
    reply = {
        "substance": {"text": "валсартан, гідрохлоротіазид", "quote": "діючі речовини: валсартан, гідрохлоротіазид;"},
        "purpose": {"text": "Таблетки для зниження тиску.", "quote": ""},
        "usual_dose": {"text": "80 мг раз на добу.", "quote": "Дорослим призначають 80 мг один раз на добу."},
        "interactions": {"text": "", "quote": ""},
        "monitoring": {"text": "", "quote": ""},
        "cautions": {"text": "", "quote": ""},
        "effects": [],
    }
    reply.update(overrides)
    return json.dumps(reply, ensure_ascii=False)


def factor_for(**overrides) -> dict:
    factor = {
        "id": "f10", "owner_user_id": "u1", "kind": "medicine", "name": "Діокор", "substance": "валсартан",
        "atc_code": "", "strength": "80 мг", "how_taken": "1 tablet · once a day",
        "reason": "тиск", "reference_name": "Диокор", "reference_code": "8311",
    }
    factor.update(overrides)
    return factor


def make_database(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    return settings


def add_owner(connection, user_id: str, patient_id: str) -> None:
    connection.execute(
        "INSERT INTO users(id, email, display_name, password_salt, password_hash, created_at) "
        "VALUES (?, ?, 'Тест', x'00', x'11', '2026-01-01T00:00:00+00:00')",
        (user_id, f"{user_id}@example.test"),
    )
    connection.execute(
        "INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at) "
        "VALUES (?, ?, 'Пацієнт', '1990-01-02', 'female', '2026-01-01T00:00:00+00:00')",
        (patient_id, user_id),
    )


def stub_model(settings, monkeypatch, reply: str) -> list[dict]:
    ai.save_ai_settings(settings, {"ai_api_key": "sk-or-test"})
    calls: list[dict] = []

    def provider(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        calls.append({"messages": messages, "timeout": timeout, "response_format": response_format})
        return ai.AIResult(content=reply, model="test/model", prompt_tokens=10, completion_tokens=5)

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", provider)
    return calls


def sent_payload(calls: list[dict]) -> dict:
    return json.loads(calls[-1]["messages"][1]["content"])


def use_reference(monkeypatch, reference: dict | None = REFERENCE) -> None:
    monkeypatch.setattr(drugref, "cached_instruction", lambda connection, name, code="", **_kw: reference)


def test_a_quote_found_in_the_instruction_survives_with_other_case_and_spacing(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    stub_model(settings, monkeypatch, card(
        purpose={"text": "Блокує рецептори.",
                 "quote": "  ВАЛСАРТАН є   антагоністом рецепторів ангіотензину II. "},
        usual_dose={"text": "80 мг.", "quote": "Дорослим\xa0призначають 80 мг один раз на добу."},
    ))
    use_reference(monkeypatch)
    with connect(settings) as connection:
        result = factor_research.research(settings, connection, factor_for(), locale="uk")
    assert result["fields"]["purpose"]["quote"] == "ВАЛСАРТАН є   антагоністом рецепторів ангіотензину II."
    assert result["fields"]["usual_dose"]["quote"] == "Дорослим\xa0призначають 80 мг один раз на добу."
    assert result["source"] == {"name": "tabletki.ua", "url": REFERENCE["url"], "shown_for": "Диокор 80 мг"}
    assert result["atc_codes"] == ["C09DA03"]


def test_a_quote_missing_from_the_instruction_or_too_short_becomes_empty(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    stub_model(settings, monkeypatch, card(
        purpose={"text": "Блокує рецептори.", "quote": "Цього тексту немає в інструкції."},
        usual_dose={"text": "80 мг.", "quote": "80 мг"},
    ))
    use_reference(monkeypatch)
    with connect(settings) as connection:
        result = factor_research.research(settings, connection, factor_for(), locale="uk")
    assert result["fields"]["purpose"]["quote"] == ""
    assert result["fields"]["usual_dose"]["quote"] == ""


def test_an_unknown_analyte_keeps_its_label_and_a_known_one_takes_the_catalogue_name(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    known_id, known_name = "c-potassium-test", "Калій (тест)"
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO concepts(id, canonical_name, category, created_at) "
            "VALUES (?, ?, 'chemistry', '2026-01-01T00:00:00+00:00')",
            (known_id, known_name),
        )
    stub_model(settings, monkeypatch, card(effects=[
        {"analyte_id": "not-in-catalogue", "label": "Калій сироватки", "direction": "lowers",
         "note": "Помірно.", "quote": ""},
        {"analyte_id": known_id, "label": "", "direction": "raises", "note": "Так.", "quote": ""},
    ]))
    use_reference(monkeypatch)
    with connect(settings) as connection:
        effects = factor_research.research(settings, connection, factor_for(), locale="uk")["effects"]
    assert effects[0] == {"concept_id": None, "label": "Калій сироватки", "direction": "lowers",
                          "note": "Помірно.", "quote": ""}
    assert effects[1]["concept_id"] == known_id
    assert effects[1]["label"] == known_name


def test_a_bad_direction_becomes_changes_and_repeats_collapse(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    stub_model(settings, monkeypatch, card(effects=[
        {"analyte_id": "", "label": "Сечова кислота", "direction": "spikes", "note": "", "quote": ""},
        {"analyte_id": "", "label": "сечова КИСЛОТА", "direction": "raises", "note": "", "quote": ""},
        {"analyte_id": "", "label": "", "direction": "raises", "note": "", "quote": ""},
    ]))
    use_reference(monkeypatch)
    with connect(settings) as connection:
        effects = factor_research.research(settings, connection, factor_for(), locale="en")["effects"]
    assert effects == [{"concept_id": None, "label": "Сечова кислота", "direction": "changes",
                        "note": "", "quote": ""}]


def test_at_most_twenty_effects_are_kept(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    stub_model(settings, monkeypatch, card(effects=[
        {"analyte_id": "", "label": f"Показник {number}", "direction": "changes", "note": "", "quote": ""}
        for number in range(25)
    ]))
    use_reference(monkeypatch)
    with connect(settings) as connection:
        effects = factor_research.research(settings, connection, factor_for(), locale="uk")["effects"]
    assert len(effects) == 20
    assert effects[-1]["label"] == "Показник 19"


def test_an_empty_text_field_is_left_out_and_long_text_is_cut(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    stub_model(settings, monkeypatch, card(
        monitoring={"text": "   ", "quote": "x"},
        purpose={"text": "а" * 2500, "quote": ""},
    ))
    use_reference(monkeypatch)
    with connect(settings) as connection:
        fields = factor_research.research(settings, connection, factor_for(), locale="uk")["fields"]
    assert "monitoring" not in fields
    assert len(fields["purpose"]["text"]) == 2000


def test_the_substance_loses_its_closing_full_stop_and_other_fields_keep_theirs(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    stub_model(settings, monkeypatch, card(
        substance={"text": "Валсартан і гідрохлоротіазид. ", "quote": ""},
        purpose={"text": "Таблетки для зниження тиску.", "quote": ""},
    ))
    use_reference(monkeypatch, None)
    with connect(settings) as connection:
        fields = factor_research.research(settings, connection, factor_for(), locale="uk")["fields"]
    assert fields["substance"]["text"] == "Валсартан і гідрохлоротіазид"
    assert fields["purpose"]["text"] == "Таблетки для зниження тиску."


def test_without_a_reference_the_source_is_none_and_no_quote_survives(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    stub_model(settings, monkeypatch, card())

    def must_not_fetch(connection, name, code="", **_kw):
        raise AssertionError("a factor without a reference name was looked up")

    monkeypatch.setattr(drugref, "cached_instruction", must_not_fetch)
    with connect(settings) as connection:
        result = factor_research.research(
            settings, connection, factor_for(reference_name="", reference_code=""), locale="uk"
        )
    assert result["source"] is None
    assert result["atc_codes"] == []
    assert result["regimen"] is None
    assert all(field["quote"] == "" for field in result["fields"].values())
    assert result["fields"]["substance"]["text"] == "валсартан, гідрохлоротіазид"


def test_instruction_sections_about_storage_and_makers_are_not_sent_and_long_ones_are_cut(
    tmp_path: Path, monkeypatch
):
    settings = make_database(tmp_path)
    calls = stub_model(settings, monkeypatch, card())
    long_reference = {**REFERENCE, "sections": REFERENCE["sections"] + [["Опис", "б" * 15000]]}
    use_reference(monkeypatch, long_reference)
    with connect(settings) as connection:
        factor_research.research(settings, connection, factor_for(), locale="uk")
    instruction = sent_payload(calls)["instruction"]
    titles = [section["title"] for section in instruction]
    assert titles == ["Склад", "Фармакологічні властивості", "Спосіб застосування", "Опис"]
    described = next(section for section in instruction if section["title"] == "Опис")
    assert described["text"] == "б" * 10000 + " […]"


def test_also_taking_lists_the_owners_other_current_factors_only(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    with connect(settings) as connection:
        add_owner(connection, "u1", "p1")
        add_owner(connection, "u2", "p2")
        connection.executemany(
            "INSERT INTO factors (id, owner_user_id, patient_id, kind, name, substance, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'medicine', ?, ?, ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
            [
                ("f10", "u1", "p1", "Діокор", "валсартан", "current"),
                ("f2", "u1", "p1", "Амлодипін", "амлодипін", "current"),
                ("f3", "u1", "p1", "Старий препарат", "", "past"),
                ("f4", "u2", "p2", "Чужий препарат", "", "current"),
            ],
        )
    calls = stub_model(settings, monkeypatch, card())
    use_reference(monkeypatch, None)
    with connect(settings) as connection:
        factor_research.research(settings, connection, factor_for(reference_name=""), locale="uk")
    assert sent_payload(calls)["also_taking"] == ["Амлодипін (амлодипін)"]


def test_the_model_gets_the_schema_timeout_and_the_language(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    calls = stub_model(settings, monkeypatch, card())
    use_reference(monkeypatch, None)
    with connect(settings) as connection:
        result = factor_research.research(settings, connection, factor_for(), locale="en")
    assert calls[-1]["timeout"] == 120
    assert calls[-1]["response_format"]["json_schema"]["name"] == "medicine_research"
    payload = sent_payload(calls)
    assert payload["language"] == "English"
    assert payload["output_contract"]["additionalProperties"] is False
    assert payload["item"]["substance"] == "валсартан"
    assert payload["item"]["how_taken"] == "1 tablet · once a day"
    assert "dose" not in payload["item"] and "schedule" not in payload["item"]
    regimen_schema = payload["output_contract"]["properties"]["usual_regimen"]
    assert regimen_schema["additionalProperties"] is False
    assert set(regimen_schema["required"]) == {
        "dose_amount", "dose_unit", "repeat", "every", "per_day", "quote"}
    assert "usual_regimen" in payload["output_contract"]["required"]
    assert result["model"] == "test/model"
    assert result["language"] == "en"


def test_ai_switched_off_raises_unavailable_before_any_lookup(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    stub_model(settings, monkeypatch, card())
    ai.save_ai_settings(settings, {"ai_enabled": "0"})

    def must_not_fetch(connection, name, code="", **_kw):
        raise AssertionError("a lookup ran with AI off")

    monkeypatch.setattr(drugref, "cached_instruction", must_not_fetch)
    with connect(settings) as connection:
        with pytest.raises(ai.AIUnavailable) as refused:
            factor_research.research(settings, connection, factor_for(), locale="uk")
    assert refused.value.reason == "disabled"


def test_a_reply_that_is_not_json_raises_unavailable(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    stub_model(settings, monkeypatch, "Вибачте, не можу відповісти.")
    use_reference(monkeypatch, None)
    with connect(settings) as connection:
        with pytest.raises(ai.AIUnavailable) as refused:
            factor_research.research(settings, connection, factor_for(), locale="uk")
    assert refused.value.reason == "provider_error"


def test_a_reply_without_an_effects_list_raises_unavailable(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    stub_model(settings, monkeypatch, json.dumps({"purpose": {"text": "x", "quote": ""}}))
    use_reference(monkeypatch, None)
    with connect(settings) as connection:
        with pytest.raises(ai.AIUnavailable) as refused:
            factor_research.research(settings, connection, factor_for(), locale="uk")
    assert refused.value.reason == "provider_error"


def test_research_commits_the_cached_reference_before_the_model_call_takes_its_lock(tmp_path: Path, monkeypatch):
    """The real ai.complete runs (budget and usage rows included); only the provider adapter is faked.

    The reference page is cached on the caller's connection, and ai.complete then records
    usage on a connection of its own with BEGIN IMMEDIATE.  Without a commit in between,
    that second connection waits out busy_timeout and fails with "database is locked".
    """
    settings = make_database(tmp_path)
    with connect(settings) as connection:
        add_owner(connection, "u1", "p1")
        connection.execute(
            "INSERT INTO factors (id, owner_user_id, patient_id, kind, name, substance, status, created_at, updated_at) "
            "VALUES ('f10', 'u1', 'p1', 'medicine', 'Діокор', 'валсартан', 'current', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
    stub_model(settings, monkeypatch, card())

    def cache_without_commit(connection, name, code="", **_kw):
        connection.execute(
            "INSERT INTO drug_references (source, url, shown_for, atc_codes, sections_json, fetched_at) "
            "VALUES (?, ?, ?, 'C09DA03', ?, '2026-01-01T00:00:00+00:00')",
            (drugref.SOURCE, REFERENCE["url"], REFERENCE["shown_for"],
             json.dumps(REFERENCE["sections"], ensure_ascii=False)),
        )
        return REFERENCE

    monkeypatch.setattr(drugref, "cached_instruction", cache_without_commit)
    with connect(settings) as connection:
        result = factor_research.research(settings, connection, factor_for(), locale="uk")
    assert result["source"]["url"] == REFERENCE["url"]
    assert result["fields"]["purpose"]["text"] == "Таблетки для зниження тиску."
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM drug_references").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM ai_usage WHERE ok = 1").fetchone()[0] == 1


def test_research_reads_the_reference_with_the_administrators_fetch_options(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    stub_model(settings, monkeypatch, card())
    monkeypatch.setattr(drugref, "fetch_options", lambda connection: {"use_api": True, "api_token": "tok-test"})
    seen: list[dict] = []

    def cached(connection, name, code="", **kwargs):
        seen.append({"name": name, "code": code, **kwargs})
        return REFERENCE

    monkeypatch.setattr(drugref, "cached_instruction", cached)
    with connect(settings) as connection:
        factor_research.research(settings, connection, factor_for(), locale="uk")
    assert seen == [{"name": "Диокор", "code": "8311", "use_api": True, "api_token": "tok-test"}]


REGIMEN_QUOTE ="Дорослим призначають 80 мг один раз на добу."
HAYSTACK = factor_research._normal(" ".join(text for _, text in REFERENCE["sections"]))


def regimen_reply(**overrides) -> dict:
    regimen = {"dose_amount": 80, "dose_unit": "mg", "repeat": "daily", "every": 1, "per_day": 1,
               "quote": REGIMEN_QUOTE}
    regimen.update(overrides)
    return {"usual_regimen": regimen}


def test_a_regimen_the_instruction_states_is_offered():
    assert factor_research._regimen(regimen_reply(), HAYSTACK, "medicine") == {
        "dose_amount": 80.0, "dose_unit": "mg", "repeat": "daily", "every": 1, "per_day": 1,
        "quote": REGIMEN_QUOTE,
    }


@pytest.mark.parametrize("reply, haystack, kind", [
    (regimen_reply(quote="Цього тексту немає в інструкції."), HAYSTACK, "medicine"),
    (regimen_reply(), "", "medicine"),
    (regimen_reply(dose_amount=0), HAYSTACK, "medicine"),
    (regimen_reply(dose_amount=1001), HAYSTACK, "medicine"),
    (regimen_reply(dose_amount=True), HAYSTACK, "medicine"),
    (regimen_reply(dose_unit=""), HAYSTACK, "medicine"),
    (regimen_reply(repeat=""), HAYSTACK, "medicine"),
    (regimen_reply(repeat="as_needed"), HAYSTACK, "medicine"),
    (regimen_reply(), HAYSTACK, "diet"),
    ({}, HAYSTACK, "medicine"),
])
def test_a_regimen_that_is_not_stated_or_not_usable_is_not_offered(reply, haystack, kind):
    assert factor_research._regimen(reply, haystack, kind) is None


def test_every_and_per_day_are_clamped_and_a_one_day_interval_becomes_daily():
    regimen = factor_research._regimen
    weekly = regimen(regimen_reply(repeat="weekly", every=500, per_day=30), HAYSTACK, "supplement")
    assert (weekly["every"], weekly["per_day"]) == (99, 24)
    monthly = regimen(regimen_reply(repeat="monthly", every=0, per_day=-3), HAYSTACK, "medicine")
    assert (monthly["every"], monthly["per_day"]) == (1, 1)
    not_ints = regimen(regimen_reply(repeat="weekly", every="2", per_day="x"), HAYSTACK, "medicine")
    assert (not_ints["every"], not_ints["per_day"]) == (1, 1)
    one_day = regimen(regimen_reply(repeat="days", every=1), HAYSTACK, "medicine")
    assert (one_day["repeat"], one_day["every"]) == ("daily", 1)
    every_three = regimen(regimen_reply(repeat="days", every=3), HAYSTACK, "medicine")
    assert (every_three["repeat"], every_three["every"]) == ("days", 3)
    daily = regimen(regimen_reply(repeat="daily", every=5), HAYSTACK, "medicine")
    assert daily["every"] == 1


def test_a_fractional_amount_is_rounded_to_three_places():
    offered = factor_research._regimen(regimen_reply(dose_amount=0.3333333), HAYSTACK, "medicine")
    assert offered["dose_amount"] == 0.333


def test_research_offers_the_regimen_only_when_the_instruction_states_it(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    stub_model(settings, monkeypatch, card(**regimen_reply()))
    use_reference(monkeypatch)
    with connect(settings) as connection:
        result = factor_research.research(settings, connection, factor_for(), locale="uk")
    assert result["regimen"] == {"dose_amount": 80.0, "dose_unit": "mg", "repeat": "daily",
                                 "every": 1, "per_day": 1, "quote": REGIMEN_QUOTE}

    stub_model(settings, monkeypatch, card(**regimen_reply(quote="Немає такого в інструкції.")))
    with connect(settings) as connection:
        assert factor_research.research(settings, connection, factor_for(), locale="uk")["regimen"] is None

    stub_model(settings, monkeypatch, card(**regimen_reply()))
    use_reference(monkeypatch, None)
    with connect(settings) as connection:
        assert factor_research.research(settings, connection, factor_for(), locale="uk")["regimen"] is None


def test_a_draft_without_an_id_or_a_database_row_is_researched(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    with connect(settings) as connection:
        add_owner(connection, "u1", "p1")
        connection.execute(
            "INSERT INTO factors (id, owner_user_id, patient_id, kind, name, substance, status, created_at, updated_at) "
            "VALUES ('f2', 'u1', 'p1', 'medicine', 'Амлодипін', 'амлодипін', 'current', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
    calls = stub_model(settings, monkeypatch, card(**regimen_reply()))
    use_reference(monkeypatch)
    draft = {key: value for key, value in factor_for().items() if key != "id"}
    with connect(settings) as connection:
        result = factor_research.research(settings, connection, draft, locale="uk")
    payload = sent_payload(calls)
    assert payload["also_taking"] == ["Амлодипін (амлодипін)"]
    assert payload["item"]["name"] == "Діокор"
    assert payload["item"]["how_taken"] == "1 tablet · once a day"
    assert result["regimen"]["quote"] == REGIMEN_QUOTE
    assert result["fields"]["usual_dose"]["quote"] == REGIMEN_QUOTE


def test_a_reply_without_a_regimen_still_works_and_offers_none(tmp_path: Path, monkeypatch):
    settings = make_database(tmp_path)
    stub_model(settings, monkeypatch, card())
    use_reference(monkeypatch)
    with connect(settings) as connection:
        result = factor_research.research(settings, connection, factor_for(), locale="uk")
    assert result["regimen"] is None
    assert result["fields"]["usual_dose"]["quote"] == REGIMEN_QUOTE
