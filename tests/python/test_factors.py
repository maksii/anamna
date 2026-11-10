"""Medicines and other factors: input rules, the record, the people who may touch it,
the chart periods, the medicine-implied facts, the dose and schedule, AI-accepted
text and effects, and the assistant's text.

Each test asserts one rule of the feature.  The database is a temporary one; the
baseline fixtures are created through the same helpers the lifecycle tests use.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from anamna import factors
from anamna.db import connect, migrate
from anamna.i18n import MESSAGES, get_locale
from anamna.ingest.pipeline import seed_concepts
from anamna.security import create_user
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for

TODAY = date(2025, 6, 1)

UK_KEYS_READY = "med.unit.tablet_few" in MESSAGES

AI_LDL = {"concept_id": "ldl-cholesterol", "label": "LDL cholesterol", "direction": "lowers", "note": "dose", "quote": "quote-ldl"}
AI_PLATELETS = {"concept_id": None, "label": "Platelets", "direction": "raises", "note": "", "quote": "quote-plt"}


def base(**fields) -> dict:
    return {"kind": "medicine", "name": "Warfarin", "status": "current", **fields}


def cleaned(**fields):
    return factors.clean(base(**fields), today=TODAY)


def saved(**fields) -> dict:
    values, error = cleaned(**fields)
    assert error is None, error
    return values


def schedule(**fields) -> dict:
    return json.loads(saved(**fields)["schedule_json"])


def shaped(**fields) -> dict:
    """A factor as ``factors.get`` shapes it, with the dose and schedule keys empty."""
    row = {"kind": "medicine", "dose_amount": None, "dose_unit": "", "dose": "", "schedule": "", "regimen": None}
    return {**row, **fields}


def plan(**fields) -> dict:
    """A schedule as ``factors.get`` returns it under ``regimen``."""
    return {"repeat": "daily", "every": 1, "weekdays": [], "per_day": 1, "times": [], "clock": [], "meal": "", **fields}


@pytest.fixture
def db(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    alpha_patient = seed_patient(settings, alpha, "Alpha")
    beta_patient = seed_patient(settings, beta, "Beta")
    alpha_document = seed_document(settings, alpha, alpha_patient, "Alpha result", "alpha-lab.txt")
    beta_document = seed_document(settings, beta, beta_patient, "Beta result", "beta-lab.txt")
    connection = connect(settings)
    seed_concepts(connection)
    connection.commit()
    yield SimpleNamespace(
        settings=settings, connection=connection,
        alpha=alpha, beta=beta, alpha_patient=alpha_patient, beta_patient=beta_patient,
        alpha_document=alpha_document, beta_document=beta_document,
    )
    connection.close()


def add(db, owner: str, patient: str, **fields) -> str:
    values, error = factors.clean(base(**fields), today=TODAY)
    assert error is None, error
    return factors.create(db.connection, owner, patient, values)


def fetch(db, factor_id: str, owner: str | None = None) -> dict | None:
    return factors.get(db.connection, owner or db.alpha, factor_id, today=TODAY)


# --- clean: the input rules, one assertion each -------------------------------

def test_clean_rejects_an_unknown_kind():
    assert factors.clean({"kind": "vitamin", "name": "D"}, today=TODAY) == ({}, "kind")


def test_clean_requires_a_name_once_stripped():
    assert factors.clean({"kind": "medicine", "name": "   "}, today=TODAY) == ({}, "name")


def test_clean_limits_the_name_to_200_characters():
    assert factors.clean({"kind": "medicine", "name": "x" * 201}, today=TODAY) == ({}, "name")


def test_clean_rejects_a_malformed_date():
    assert cleaned(started_on="01.02.2025") == ({}, "date_format")


def test_clean_rejects_a_start_after_the_end():
    assert cleaned(started_on="2025-05-02", ended_on="2025-05-01") == ({}, "dates")


def test_a_procedure_dated_tomorrow_is_prescribed():
    values, _ = cleaned(kind="procedure", name="Colonoscopy", started_on="2025-06-02")
    assert values["status"] == "prescribed"


def test_a_procedure_has_no_end_date():
    values, _ = cleaned(kind="procedure", name="Colonoscopy", started_on="2025-03-01", ended_on="2025-03-02")
    assert values["ended_on"] is None


def test_a_past_procedure_is_past():
    values, _ = cleaned(kind="procedure", name="Colonoscopy", started_on="2025-03-01")
    assert values["status"] == "past"


def test_an_ended_medicine_is_past():
    values, _ = cleaned(started_on="2025-01-01", ended_on="2025-02-01")
    assert values["status"] == "past"


def test_an_unknown_status_becomes_current():
    values, _ = cleaned(status="maybe")
    assert values["status"] == "current"


def test_a_future_start_is_prescribed_not_started():
    values, _ = cleaned(started_on="2025-07-01")
    assert values["status"] == "prescribed"


def test_a_prescription_dated_in_the_past_stays_prescribed():
    values, _ = cleaned(status="prescribed", started_on="2025-03-01")
    assert values["status"] == "prescribed"


def test_dates_approximate_is_one_for_on():
    assert cleaned(dates_approximate="on")[0]["dates_approximate"] == 1


def test_dates_approximate_is_zero_for_other_values():
    assert cleaned(dates_approximate="yes")[0]["dates_approximate"] == 0


def test_atc_code_is_upper_cased_with_spaces_removed():
    assert cleaned(atc_code=" b01 aa03 ")[0]["atc_code"] == "B01AA03"


def test_atc_code_that_is_not_a_code_is_dropped():
    assert cleaned(atc_code="B01AA0")[0]["atc_code"] == ""


def test_short_text_is_cut_to_200_characters():
    assert cleaned(substance="a" * 250)[0]["substance"] == "a" * 200


def test_long_text_is_cut_to_4000_characters():
    assert cleaned(notes="n" * 5000)[0]["notes"] == "n" * 4000


def test_missing_form_keys_count_as_empty():
    assert factors.clean({"kind": "medicine", "name": "Warfarin"}, today=TODAY)[0]["reason"] == ""


def test_reference_name_with_a_path_character_is_dropped():
    assert cleaned(reference_name="warfarin/5", reference_code="123")[0]["reference_name"] == ""


def test_reference_name_with_dot_dot_is_dropped():
    assert cleaned(reference_name="a..b")[0]["reference_name"] == ""


def test_reference_code_must_be_digits():
    assert cleaned(reference_name="warfarin-5", reference_code="12a")[0]["reference_code"] == ""


def test_reference_code_is_dropped_without_a_name():
    assert cleaned(reference_code="123")[0]["reference_code"] == ""


def test_clean_returns_exactly_the_documented_keys():
    values, _ = cleaned()
    assert set(values) == {
        "kind", "name", "substance", "atc_code", "strength", "dose", "schedule", "status",
        "started_on", "ended_on", "dates_approximate", "reason", "prescriber", "document_id",
        "notes", "purpose", "usual_dose", "interactions", "monitoring", "cautions",
        "reference_name", "reference_code", "dose_amount", "dose_unit", "schedule_json",
        "ai_fields", "ai_effects",
    }


# --- clean: the dose ----------------------------------------------------------

def test_a_dose_amount_with_a_comma_is_read_as_a_decimal():
    assert saved(dose_amount=" 0,5 ", dose_unit="tablet")["dose_amount"] == 0.5


def test_a_dose_amount_is_rounded_to_three_decimals():
    assert saved(dose_amount="0.12345", dose_unit="mg")["dose_amount"] == 0.123


@pytest.mark.parametrize("amount", ["0", "-1", "100001", "nan", "inf", "abc"])
def test_a_dose_amount_outside_the_range_or_not_a_number_is_dropped(amount):
    values = saved(dose_amount=amount, dose_unit="tablet")
    assert (values["dose_amount"], values["dose_unit"]) == (None, "")


def test_a_dose_amount_is_none_for_a_kind_that_takes_no_dose():
    values = saved(kind="diet", dose_amount="2", dose_unit="g")
    assert (values["dose_amount"], values["dose_unit"]) == (None, "")


def test_a_dose_unit_without_an_amount_is_dropped():
    assert saved(dose_unit="tablet")["dose_unit"] == ""


def test_an_unknown_dose_unit_is_dropped():
    assert saved(dose_amount="1", dose_unit="spoon")["dose_unit"] == ""


def test_a_known_dose_unit_is_kept_with_its_amount():
    assert saved(dose_amount="2", dose_unit="drop")["dose_unit"] == "drop"


# --- clean: the schedule ------------------------------------------------------

@pytest.mark.parametrize("repeat", ["daily", "as_needed", "monthly"])
def test_each_repeat_is_stored(repeat):
    assert schedule(repeat=repeat)["repeat"] == repeat


def test_weekly_is_stored_with_its_weekdays():
    assert schedule(repeat="weekly", weekday=["0", "3"])["weekdays"] == [0, 3]


def test_days_with_every_one_becomes_daily():
    stored = schedule(repeat="days", every="1")
    assert (stored["repeat"], stored["every"]) == ("daily", 1)


def test_days_with_every_three_stays_days():
    stored = schedule(repeat="days", every="3")
    assert (stored["repeat"], stored["every"]) == ("days", 3)


def test_as_needed_always_has_every_one():
    assert schedule(repeat="as_needed", every="5")["every"] == 1


def test_every_is_clamped_to_99_and_defaults_to_one():
    assert schedule(repeat="monthly", every="500")["every"] == 99
    assert schedule(repeat="monthly", every="abc")["every"] == 1


def test_weekdays_are_kept_only_for_a_weekly_repeat():
    assert schedule(repeat="daily", weekday=["0", "3"])["weekdays"] == []


def test_weekdays_are_sorted_distinct_and_within_the_week():
    assert schedule(repeat="weekly", weekday=["3", "0", "3", "7", "x"])["weekdays"] == [0, 3]


def test_per_day_is_raised_to_the_number_of_times_of_day():
    assert schedule(repeat="daily", per_day="1", day_part=["morning", "night"])["per_day"] == 2


def test_per_day_is_raised_to_the_number_of_clock_times():
    assert schedule(repeat="daily", per_day="1", clock=["08:00", "20:00"])["per_day"] == 2


def test_per_day_is_clamped_to_one_through_twenty_four():
    assert schedule(repeat="daily", per_day="0")["per_day"] == 1
    assert schedule(repeat="daily", per_day="30")["per_day"] == 24


def test_times_of_day_keep_the_day_order_and_drop_unknown_and_repeated_ones():
    stored = schedule(repeat="daily", day_part=["night", "nonsense", "morning", "night"])
    assert stored["times"] == ["morning", "night"]


def test_clock_times_must_be_real_times_of_day():
    stored = schedule(repeat="daily", clock=["08:00", "8:00", "24:00", "23:59", "12:60", "08:00"])
    assert stored["clock"] == ["08:00", "23:59"]


def test_clock_times_are_capped_at_twelve():
    stored = schedule(repeat="daily", clock=[f"{hour:02d}:00" for hour in range(15)])
    assert len(stored["clock"]) == 12


def test_a_meal_must_be_one_of_the_known_meals():
    assert schedule(repeat="daily", meal="during")["meal"] == ""
    assert schedule(repeat="daily", meal="after")["meal"] == "after"


def test_an_activity_carries_only_its_repeat():
    stored = schedule(
        kind="activity", repeat="weekly", weekday=["1"], per_day="3",
        day_part=["morning"], clock=["08:00"], meal="after",
    )
    assert stored == {"repeat": "weekly", "every": 1, "weekdays": [1], "per_day": 1, "times": [], "clock": [], "meal": ""}


def test_the_schedule_keys_are_stored_in_the_documented_order():
    stored = saved(repeat="daily", day_part="morning")["schedule_json"]
    assert list(json.loads(stored)) == ["repeat", "every", "weekdays", "per_day", "times", "clock", "meal"]


def test_a_diet_has_no_schedule():
    assert saved(kind="diet", repeat="daily")["schedule_json"] == ""


def test_an_unknown_repeat_gives_no_schedule():
    assert saved(repeat="hourly")["schedule_json"] == ""


# --- clean: AI-accepted fields and effects ------------------------------------

def test_ai_fields_name_the_posted_fields_that_have_text_in_schema_order():
    values = saved(purpose="A", usual_dose="B", monitoring="", ai_fields="monitoring,usual_dose,purpose,bogus")
    assert values["ai_fields"] == ("purpose", "usual_dose")


def test_ai_fields_are_empty_when_nothing_is_posted():
    assert saved(purpose="A")["ai_fields"] == ()


def test_ai_effects_are_empty_when_nothing_is_posted():
    assert saved()["ai_effects"] == []


def test_ai_effects_keep_the_usable_fields_and_cut_them_to_their_limits():
    posted = {
        "concept_id": "  ldl-cholesterol ", "label": "L" * 300, "direction": "lowers",
        "note": "n" * 600, "quote": "q" * 500, "unused": 1,
    }
    effect = saved(ai_effect=[json.dumps(posted)])["ai_effects"][0]
    assert (effect["concept_id"], len(effect["label"]), len(effect["note"]), len(effect["quote"])) == (
        "ldl-cholesterol", 200, 500, 400,
    )


def test_ai_effects_skip_what_is_not_an_object_or_has_no_known_direction():
    posted = [
        "not json", "[1, 2]", json.dumps({"label": "x", "direction": "up"}),
        json.dumps({"label": "Iron", "direction": "raises"}),
    ]
    effects = saved(ai_effect=posted)["ai_effects"]
    assert [(item["label"], item["concept_id"]) for item in effects] == [("Iron", None)]


def test_a_concept_id_that_is_not_text_becomes_none():
    effect = saved(ai_effect=[json.dumps({"concept_id": 5, "label": "Iron", "direction": "raises"})])["ai_effects"][0]
    assert effect["concept_id"] is None


def test_ai_effects_are_capped_at_twenty():
    posted = [json.dumps({"label": f"Effect {index}", "direction": "raises"}) for index in range(25)]
    assert len(saved(ai_effect=posted)["ai_effects"]) == 20


# --- create, get, update, delete ----------------------------------------------

def test_create_round_trips_the_record_and_its_reference_link(db):
    values, _ = cleaned(
        substance="warfarin", atc_code="B01AA03", strength="5 mg", dose="1 tablet", schedule="evening",
        started_on="2025-01-01", reason="atrial fibrillation", prescriber="Dr Example",
        purpose="Blood thinner", reference_name="Coumadin", reference_code="12345",
    )
    factor_id = factors.create(db.connection, db.alpha, db.alpha_patient, values)
    row = fetch(db, factor_id)
    assert (row["strength"], row["schedule"], row["purpose"]) == ("5 mg", "evening", "Blood thinner")
    assert row["reference_url"] == "https://tabletki.ua/uk/Coumadin/12345/"


def test_a_reference_name_alone_gives_a_link_without_a_code(db):
    factor_id = add(db, db.alpha, db.alpha_patient, reference_name="Coumadin")
    assert fetch(db, factor_id)["reference_url"] == "https://tabletki.ua/uk/Coumadin/"


def test_a_reference_source_is_recorded_when_there_is_a_name(db):
    factor_id = add(db, db.alpha, db.alpha_patient, reference_name="Coumadin")
    assert fetch(db, factor_id)["reference_source"] == "tabletki"


def test_the_dose_and_schedule_round_trip_and_read_back_as_a_regimen(db):
    factor_id = add(
        db, db.alpha, db.alpha_patient, dose_amount="1", dose_unit="tablet", repeat="daily",
        per_day="2", day_part=["evening", "morning"], meal="after",
    )
    row = fetch(db, factor_id)
    assert (row["dose_amount"], row["dose_unit"]) == (1.0, "tablet")
    assert row["regimen"] == {
        "repeat": "daily", "every": 1, "weekdays": [], "per_day": 2,
        "times": ["morning", "evening"], "clock": [], "meal": "after",
    }


def test_a_factor_without_a_schedule_has_no_regimen(db):
    assert fetch(db, add(db, db.alpha, db.alpha_patient))["regimen"] is None


def test_the_migration_drops_the_suggestion_columns_and_adds_the_dose_columns(db):
    columns = {row[1] for row in db.connection.execute("PRAGMA table_info(factors)")}
    assert "suggestion_json" not in columns and "suggestion_at" not in columns
    assert {"dose_amount", "dose_unit", "schedule_json"} <= columns


def test_create_stores_accepted_ai_fields_and_effects_as_ai(db):
    values = saved(
        purpose="Blood thinner", usual_dose="2.5 mg", ai_fields="usual_dose",
        ai_effect=[json.dumps(AI_LDL), json.dumps(AI_PLATELETS)],
    )
    factor_id = factors.create(db.connection, db.alpha, db.alpha_patient, values)
    row = fetch(db, factor_id)
    assert row["ai_fields"] == ("usual_dose",)
    # Effects written in the same second order by id, so compare as a set.
    assert sorted((effect["origin"], effect["evidence"]) for effect in row["effects"]) == [
        ("ai", "quote-ldl"), ("ai", "quote-plt"),
    ]


def test_create_keeps_only_one_of_two_ai_effects_with_the_same_label(db):
    posted = [
        json.dumps({"label": "Iron", "direction": "lowers", "quote": "a"}),
        json.dumps({"label": "iron", "direction": "raises", "quote": "b"}),
    ]
    factor_id = factors.create(db.connection, db.alpha, db.alpha_patient, saved(ai_effect=posted))
    assert len(fetch(db, factor_id)["effects"]) == 1


def test_update_keeps_an_unchanged_ai_field_and_drops_an_edited_one(db):
    factor_id = factors.create(
        db.connection, db.alpha, db.alpha_patient,
        saved(purpose="AI purpose", usual_dose="2.5 mg", ai_fields="purpose,usual_dose"),
    )
    factors.update(db.connection, db.alpha, factor_id, saved(purpose="AI purpose", usual_dose="5 mg"))
    assert fetch(db, factor_id)["ai_fields"] == ("purpose",)


def test_update_marks_a_newly_accepted_ai_field_and_keeps_the_others(db):
    factor_id = factors.create(
        db.connection, db.alpha, db.alpha_patient,
        saved(purpose="AI purpose", usual_dose="2.5 mg", ai_fields="purpose,usual_dose"),
    )
    factors.update(db.connection, db.alpha, factor_id, saved(purpose="AI purpose", usual_dose="5 mg"))
    factors.update(
        db.connection, db.alpha, factor_id,
        saved(purpose="AI purpose", usual_dose="5 mg", monitoring="Check INR", ai_fields="monitoring"),
    )
    assert fetch(db, factor_id)["ai_fields"] == ("purpose", "monitoring")


def test_update_adds_an_ai_effect_unless_the_factor_already_has_its_label(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    factors.add_effect(db.connection, db.alpha, factor_id, concept_id=None, label="Iron", direction="lowers")
    factors.update(db.connection, db.alpha, factor_id, saved(ai_effect=[json.dumps({"label": "iron", "direction": "raises"})]))
    effects = fetch(db, factor_id)["effects"]
    assert [(effect["label"], effect["origin"]) for effect in effects] == [("Iron", "person")]


def test_update_adds_an_ai_effect_on_a_new_concept(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    factors.update(db.connection, db.alpha, factor_id, saved(ai_effect=[json.dumps(AI_LDL)]))
    effects = fetch(db, factor_id)["effects"]
    assert [(effect["concept_id"], effect["origin"], effect["evidence"]) for effect in effects] == [
        ("ldl-cholesterol", "ai", "quote-ldl"),
    ]


def test_update_replaces_the_values(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    values, _ = cleaned(name="Warfarin 2")
    assert factors.update(db.connection, db.alpha, factor_id, values) is True
    assert fetch(db, factor_id)["name"] == "Warfarin 2"


def test_delete_removes_the_factor_once(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    assert factors.delete(db.connection, db.alpha, factor_id) is True
    assert fetch(db, factor_id) is None
    assert factors.delete(db.connection, db.alpha, factor_id) is False


def test_a_document_of_another_user_is_stored_as_null(db):
    values, _ = cleaned(document_id=db.beta_document)
    factor_id = factors.create(db.connection, db.alpha, db.alpha_patient, values)
    assert fetch(db, factor_id)["document_id"] is None


def test_a_document_of_the_same_user_is_kept(db):
    values, _ = cleaned(document_id=db.alpha_document)
    factor_id = factors.create(db.connection, db.alpha, db.alpha_patient, values)
    assert fetch(db, factor_id)["document_id"] == db.alpha_document


def test_search_rows_lists_the_factor_with_its_reason(db):
    add(db, db.alpha, db.alpha_patient, reason="atrial fibrillation")
    rows = factors.search_rows(db.connection, db.alpha)
    assert [(row["name"], row["reason"]) for row in rows] == [("Warfarin", "atrial fibrillation")]


def test_stop_ends_a_period_as_past(db):
    factor_id = add(db, db.alpha, db.alpha_patient, started_on="2025-01-01")
    assert factors.stop(db.connection, db.alpha, factor_id, date(2025, 5, 1)) is True
    row = fetch(db, factor_id)
    assert (row["status"], row["ended_on"]) == ("past", "2025-05-01")


def test_stop_before_a_later_start_ends_on_the_start(db):
    factor_id = add(db, db.alpha, db.alpha_patient, started_on="2025-05-10")
    factors.stop(db.connection, db.alpha, factor_id, date(2025, 5, 1))
    assert fetch(db, factor_id)["ended_on"] == "2025-05-10"


def test_stop_refuses_a_procedure(db):
    factor_id = add(db, db.alpha, db.alpha_patient, kind="procedure", started_on="2025-03-03")
    assert factors.stop(db.connection, db.alpha, factor_id, date(2025, 5, 1)) is False


def test_effective_status_turns_past_once_the_end_is_before_today():
    assert factors.effective_status({"status": "current", "ended_on": "2025-05-31"}, TODAY) == "past"


def test_effective_status_keeps_the_stored_status_without_an_end():
    assert factors.effective_status({"status": "current", "ended_on": None}, TODAY) == "current"


# --- people: another account can reach nothing -------------------------------

def test_another_user_cannot_read_change_or_remove_a_factor(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    values, _ = cleaned(name="Renamed")
    assert fetch(db, factor_id, db.beta) is None
    assert factors.update(db.connection, db.beta, factor_id, values) is False
    assert factors.delete(db.connection, db.beta, factor_id) is False
    assert fetch(db, factor_id)["name"] == "Warfarin"


def test_another_user_cannot_stop_or_add_an_effect_to_a_factor(db):
    factor_id = add(db, db.alpha, db.alpha_patient, started_on="2025-01-01")
    assert factors.stop(db.connection, db.beta, factor_id, TODAY) is False
    assert factors.add_effect(db.connection, db.beta, factor_id, concept_id=None, label="x", direction="raises") is None
    assert fetch(db, factor_id)["status"] == "current"


# --- effects ------------------------------------------------------------------

def test_a_second_effect_on_the_same_concept_is_not_inserted(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    first = factors.add_effect(db.connection, db.alpha, factor_id, concept_id="ldl-cholesterol", label="", direction="lowers")
    second = factors.add_effect(db.connection, db.alpha, factor_id, concept_id="ldl-cholesterol", label="other", direction="raises")
    assert second == first


def test_an_effect_on_a_concept_takes_the_concept_name_as_its_label(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    factors.add_effect(db.connection, db.alpha, factor_id, concept_id="ldl-cholesterol", label="", direction="lowers")
    assert fetch(db, factor_id)["effects"][0]["label"] == "LDL cholesterol"


def test_a_label_without_a_known_concept_is_kept_with_no_concept(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    factors.add_effect(db.connection, db.alpha, factor_id, concept_id="no-such-concept", label="Foo", direction="raises")
    assert fetch(db, factor_id)["effects"][0]["concept_id"] is None


def test_the_same_label_without_a_concept_is_not_duplicated(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    first = factors.add_effect(db.connection, db.alpha, factor_id, concept_id=None, label="Iron", direction="lowers")
    second = factors.add_effect(db.connection, db.alpha, factor_id, concept_id=None, label="iron", direction="raises")
    assert second == first


def test_an_effect_needs_a_concept_or_a_label(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    assert factors.add_effect(db.connection, db.alpha, factor_id, concept_id=None, label="", direction="raises") is None


def test_an_effect_needs_a_known_direction(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    assert factors.add_effect(db.connection, db.alpha, factor_id, concept_id=None, label="Iron", direction="up") is None


def test_remove_effect_deletes_it_once(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    effect = factors.add_effect(db.connection, db.alpha, factor_id, concept_id=None, label="Iron", direction="raises")
    assert factors.remove_effect(db.connection, db.alpha, effect) is True
    assert factors.remove_effect(db.connection, db.alpha, effect) is False


def test_deleting_the_user_removes_factors_and_effects(db):
    db.connection.commit()
    gamma = create_user(db.settings, "gamma@example.test", "Gamma", PASSWORD)
    patient = seed_patient(db.settings, gamma, "Gamma")
    factor_id = add(db, gamma, patient, started_on="2025-01-01")
    factors.add_effect(db.connection, gamma, factor_id, concept_id="ldl-cholesterol", label="", direction="lowers")
    db.connection.execute("DELETE FROM users WHERE id=?", (gamma,))
    assert db.connection.execute("SELECT COUNT(*) FROM factors").fetchone()[0] == 0
    assert db.connection.execute("SELECT COUNT(*) FROM factor_effects").fetchone()[0] == 0
    assert db.connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_the_migration_adds_planning_pregnancy_defaulting_to_zero(db):
    value = db.connection.execute(
        "SELECT planning_pregnancy FROM patients WHERE id=?", (db.alpha_patient,)
    ).fetchone()[0]
    assert value == 0


# --- listing ------------------------------------------------------------------

def test_listing_orders_current_then_prescribed_then_past(db):
    add(db, db.alpha, db.alpha_patient, name="Current B", started_on="2025-01-01")
    add(db, db.alpha, db.alpha_patient, name="Current A", started_on="2025-01-01")
    add(db, db.alpha, db.alpha_patient, name="Current undated")
    add(db, db.alpha, db.alpha_patient, name="Prescribed", started_on="2025-07-01")
    add(db, db.alpha, db.alpha_patient, name="Old", status="past", started_on="2024-01-01", ended_on="2024-02-01")
    add(db, db.alpha, db.alpha_patient, name="Later past", status="past", started_on="2024-05-01", ended_on="2024-06-01")
    add(db, db.alpha, db.alpha_patient, name="Past undated", status="past")
    names = [row["name"] for row in factors.listing(db.connection, db.alpha, today=TODAY)]
    assert names == ["Current A", "Current B", "Current undated", "Prescribed", "Later past", "Old", "Past undated"]


def test_listing_attaches_each_factors_effects(db):
    first = add(db, db.alpha, db.alpha_patient, name="First")
    add(db, db.alpha, db.alpha_patient, name="Second")
    factors.add_effect(db.connection, db.alpha, first, concept_id=None, label="Iron", direction="raises")
    by_name = {row["name"]: row for row in factors.listing(db.connection, db.alpha, today=TODAY)}
    assert [effect["label"] for effect in by_name["First"]["effects"]] == ["Iron"]


# --- periods ------------------------------------------------------------------

def test_periods_mark_the_related_effect_and_the_open_ends(db):
    statin = add(db, db.alpha, db.alpha_patient, name="Statin", started_on="2025-01-01")
    factors.add_effect(db.connection, db.alpha, statin, concept_id="ldl-cholesterol", label="", direction="lowers", note="dose", origin="person")
    add(db, db.alpha, db.alpha_patient, name="Biopsy", kind="procedure", started_on="2025-03-03")
    add(db, db.alpha, db.alpha_patient, name="Finished", status="past", started_on="2024-01-01", ended_on="2024-02-01")
    add(db, db.alpha, db.alpha_patient, name="Unknown end", status="past", started_on="2024-05-01")
    add(db, db.alpha, db.alpha_patient, name="Future", started_on="2025-07-01")
    rows = {row["name"]: row for row in factors.periods(db.connection, db.alpha, ["ldl-cholesterol"], today=TODAY)}
    assert set(rows) == {"Statin", "Biopsy", "Finished", "Unknown end"}


def test_periods_give_the_direction_and_note_of_a_related_effect(db):
    statin = add(db, db.alpha, db.alpha_patient, name="Statin", started_on="2025-01-01")
    factors.add_effect(db.connection, db.alpha, statin, concept_id="ldl-cholesterol", label="", direction="lowers", note="dose", origin="person")
    row = {r["name"]: r for r in factors.periods(db.connection, db.alpha, ["ldl-cholesterol"], today=TODAY)}["Statin"]
    assert (row["related"], row["direction"], row["note"], row["origin"]) == (True, "lowers", "dose", "person")


def test_periods_leave_an_ongoing_factor_open_ended(db):
    add(db, db.alpha, db.alpha_patient, name="Statin", started_on="2025-01-01")
    row = factors.periods(db.connection, db.alpha, [], today=TODAY)[0]
    assert (row["end"], row["point"]) == (None, False)


def test_periods_mark_a_procedure_as_a_point(db):
    add(db, db.alpha, db.alpha_patient, name="Biopsy", kind="procedure", started_on="2025-03-03")
    row = factors.periods(db.connection, db.alpha, [], today=TODAY)[0]
    assert (row["point"], row["end"]) == (True, None)


def test_periods_draw_a_past_factor_without_an_end_as_a_point(db):
    add(db, db.alpha, db.alpha_patient, name="Unknown end", status="past", started_on="2024-05-01")
    row = factors.periods(db.connection, db.alpha, [], today=TODAY)[0]
    assert row["point"] is True


def test_periods_leave_out_prescribed_factors(db):
    add(db, db.alpha, db.alpha_patient, name="Future", started_on="2025-07-01")
    assert factors.periods(db.connection, db.alpha, [], today=TODAY) == []


# --- medicine-implied facts ---------------------------------------------------

def test_an_atc_vka_code_implies_vka_therapy():
    assert factors.implied_facts({"kind": "medicine", "atc_code": "B01AA03", "substance": "", "name": "Coumadin"}) == ("vka_therapy",)


def test_a_substance_word_implies_vka_therapy_without_an_atc_code():
    assert factors.implied_facts({"kind": "medicine", "atc_code": "", "substance": "Варфарин", "name": "Варфарин"}) == ("vka_therapy",)


def test_an_atc_urate_code_implies_urate_lowering_therapy():
    assert factors.implied_facts({"kind": "medicine", "atc_code": "M04AA01", "substance": "", "name": "Zyloric"}) == ("urate_lowering_therapy",)


def test_an_illness_implies_the_inflammation_facts():
    assert factors.implied_facts({"kind": "illness", "atc_code": "", "substance": "", "name": "Flu"}) == ("illness", "infection_or_inflammation")


def test_an_unrelated_medicine_implies_nothing():
    assert factors.implied_facts({"kind": "medicine", "atc_code": "A02BC01", "substance": "omeprazole", "name": "Omeprazole"}) == ()


def test_fact_periods_and_facts_on_cover_inside_before_after_and_ongoing(db):
    add(db, db.alpha, db.alpha_patient, name="Warfarin now", atc_code="B01AA03", started_on="2025-01-01")
    add(db, db.alpha, db.alpha_patient, name="Warfarin old", atc_code="B01AA03", status="past", started_on="2024-01-01", ended_on="2024-03-01")
    add(db, db.alpha, db.alpha_patient, name="Warfarin unknown", atc_code="B01AA03", status="past", started_on="2023-01-01")
    add(db, db.alpha, db.alpha_patient, name="Warfarin next", atc_code="B01AA03", started_on="2025-07-01")
    periods = factors.fact_periods(db.connection, db.alpha)
    assert factors.facts_on(periods, "2025-02-01") == {"vka_therapy"}
    assert factors.facts_on(periods, "2024-02-01") == {"vka_therapy"}
    assert factors.facts_on(periods, "2024-04-01") == set()
    assert factors.facts_on(periods, "2023-06-01") == set()
    assert factors.facts_on(periods, "2030-01-01") == {"vka_therapy"}


# --- dose and schedule text ---------------------------------------------------

@pytest.mark.skipif(not UK_KEYS_READY, reason="Ukrainian medicine keys are not in the catalogue yet")
def test_regimen_text_in_ukrainian_uses_the_plural_forms():
    text = factors.regimen_text(shaped(dose_amount=2, dose_unit="tablet", regimen=plan(per_day=3)), "uk")
    assert text == "2 таблетки · 3 рази на день"


@pytest.mark.skipif(not UK_KEYS_READY, reason="Ukrainian medicine keys are not in the catalogue yet")
def test_a_fractional_amount_in_ukrainian_uses_a_comma_and_the_few_form():
    text = factors.regimen_text(shaped(dose_amount=0.5, dose_unit="tablet", regimen=plan()), "uk")
    assert text.startswith("0,5 таблетки")


def test_regimen_text_restores_the_locale_it_was_asked_in():
    before = get_locale()
    factors.regimen_text(shaped(dose_amount=1, dose_unit="tablet"), "uk")
    assert get_locale() == before


def test_regimen_text_for_a_tablet_taken_twice_a_day_with_a_meal():
    row = shaped(dose_amount=1, dose_unit="tablet", regimen=plan(per_day=2, times=["morning", "evening"], meal="after"))
    assert factors.regimen_text(row, "en") == "1 tablet · 2 times a day (morning, evening) · after food"


def test_regimen_text_for_half_a_tablet_once_a_day():
    row = shaped(dose_amount=0.5, dose_unit="tablet", regimen=plan(per_day=1))
    assert factors.regimen_text(row, "en") == "0.5 tablets · once a day"


def test_regimen_text_for_drops_every_week_on_two_days_with_a_clock_time():
    row = shaped(dose_amount=10, dose_unit="drop", regimen=plan(repeat="weekly", weekdays=[0, 3], clock=["08:00"]))
    assert factors.regimen_text(row, "en") == "10 drops · every week on Mon, Thu · 08:00"


def test_regimen_text_for_an_as_needed_dose_with_a_maximum():
    row = shaped(dose_amount=1, dose_unit="tablet", regimen=plan(repeat="as_needed", per_day=3))
    assert factors.regimen_text(row, "en") == "1 tablet · when needed, up to 3 times a day"


def test_regimen_text_for_a_every_three_days_dose_with_two_times_a_day():
    row = shaped(regimen=plan(repeat="days", every=3, per_day=2))
    assert factors.regimen_text(row, "en") == "every 3 days · 2 times a day"


def test_regimen_text_for_an_activity_on_three_weekdays_with_its_note():
    row = shaped(kind="activity", regimen=plan(repeat="weekly", weekdays=[1, 3, 5]), schedule="1 hour")
    assert factors.regimen_text(row, "en") == "every week on Tue, Thu, Sat · 1 hour"


def test_regimen_text_for_an_activity_every_day_has_no_dose_part():
    assert factors.regimen_text(shaped(kind="activity", regimen=plan()), "en") == "every day"


def test_regimen_text_for_free_text_dose_and_schedule():
    assert factors.regimen_text(shaped(dose="one pill", schedule="mornings"), "en") == "one pill · mornings"


def test_regimen_text_for_nothing_is_empty():
    assert factors.regimen_text(shaped(), "en") == ""


# --- AI suggestions: the form owns them now -----------------------------------

def test_another_user_cannot_add_an_ai_effect_through_update(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    factors.update(db.connection, db.beta, factor_id, saved(ai_effect=[json.dumps(AI_LDL)]))
    assert fetch(db, factor_id)["effects"] == []


def test_editing_an_ai_field_removes_its_ai_mark(db):
    factor_id = factors.create(
        db.connection, db.alpha, db.alpha_patient,
        saved(purpose="Person wrote this", usual_dose="2.5 mg", monitoring="Check INR", ai_fields="usual_dose,monitoring"),
    )
    values = saved(purpose="Person wrote this", usual_dose="5 mg", monitoring="Check INR", started_on="2025-01-01")
    factors.update(db.connection, db.alpha, factor_id, values)
    assert fetch(db, factor_id)["ai_fields"] == ("monitoring",)


# --- assistant text ----------------------------------------------------------

def test_chat_lines_for_an_empty_record_are_the_two_fixed_lines(db):
    assert factors.chat_lines(db.connection, db.alpha, today=TODAY) == [
        "## medicines and other factors",
        "none recorded. When it matters, ask what the person takes and does; they can add medicines, "
        "supplements, operations, illnesses, diet and training on the Medicines page.",
    ]


def test_chat_lines_describe_one_medicine_with_its_effect(db):
    factor_id = add(
        db, db.alpha, db.alpha_patient, name="Warfarin", substance="warfarin", atc_code="B01AA03",
        strength="1 mg", dose="5 mg", schedule="evening", started_on="2025-01-01", reason="AF",
    )
    factors.add_effect(db.connection, db.alpha, factor_id, concept_id="ldl-cholesterol", label="", direction="lowers")
    lines = factors.chat_lines(db.connection, db.alpha, today=TODAY)
    assert lines[0] == "## medicines and other factors (1 current, 0 prescribed but not started, 0 past; detail: get_medicines)"
    assert lines[1] == (
        f"- Warfarin [medicine; warfarin; ATC B01AA03] 1 mg; 5 mg · evening; since 2025-01-01; for AF; "
        f"effects: lowers LDL cholesterol m:{factor_id}"
    )


def test_chat_lines_show_the_scheduled_dose_of_a_medicine(db):
    add(
        db, db.alpha, db.alpha_patient, name="Warfarin", dose_amount="5", dose_unit="mg",
        repeat="daily", per_day="2", day_part=["morning", "evening"], started_on="2025-01-01",
    )
    line = factors.chat_lines(db.connection, db.alpha, today=TODAY)[1]
    assert line.startswith("- Warfarin [medicine] ")
    assert "5 mg · 2 times a day (morning, evening)" in line


def test_chat_detail_without_an_id_on_an_empty_record(db):
    assert factors.chat_detail(db.connection, db.alpha, today=TODAY) == "No medicines or other factors are recorded."


def test_chat_detail_with_an_unknown_id(db):
    assert factors.chat_detail(db.connection, db.alpha, today=TODAY, factor_id="m:nope") == "No such medicine or factor."


def test_chat_detail_with_an_id_gives_the_fields_and_an_ai_effect(db):
    factor_id = add(db, db.alpha, db.alpha_patient, name="Warfarin", purpose="Blood thinner", started_on="2025-01-01")
    factors.add_effect(db.connection, db.alpha, factor_id, concept_id=None, label="Iron", direction="lowers", note="n", origin="ai")
    text = factors.chat_detail(db.connection, db.alpha, today=TODAY, factor_id=f"m:{factor_id}")
    assert "  what it is: Blood thinner" in text.splitlines()
    assert "  effect: lowers Iron (n) [from an AI suggestion the person accepted]" in text.splitlines()


def test_chat_detail_header_names_the_end_of_a_past_factor(db):
    factor_id = add(db, db.alpha, db.alpha_patient, status="past", started_on="2024-01-01", ended_on="2024-02-01")
    header = factors.chat_detail(db.connection, db.alpha, today=TODAY, factor_id=factor_id).splitlines()[0]
    assert "until 2024-02-01" in header


def test_chat_detail_without_an_id_lists_every_factor(db):
    add(db, db.alpha, db.alpha_patient, name="Warfarin", started_on="2025-01-01")
    add(db, db.alpha, db.alpha_patient, name="Statin", status="past", started_on="2024-01-01", ended_on="2024-02-01")
    text = factors.chat_detail(db.connection, db.alpha, today=TODAY)
    assert sum(line.startswith("- ") for line in text.splitlines()) == 2


def test_chat_detail_does_not_show_another_users_factor(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    assert factors.chat_detail(db.connection, db.beta, today=TODAY, factor_id=factor_id) == "No such medicine or factor."
