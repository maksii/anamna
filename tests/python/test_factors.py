"""Medicines and other factors: input rules, the record, the people who may touch it,
the chart periods, the medicine-implied facts, AI suggestions and the assistant's text.

Each test asserts one rule of the feature.  The database is a temporary one; the
baseline fixtures are created through the same helpers the lifecycle tests use.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from anamna import factors
from anamna.db import connect, migrate
from anamna.ingest.pipeline import seed_concepts
from anamna.security import create_user
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for

TODAY = date(2025, 6, 1)

SUGGESTION = {
    "created_at": "2025-06-01T00:00:00+00:00",
    "model": "test-model",
    "language": "en",
    "source": {"name": "Reference", "url": "https://example.test/reference", "shown_for": "Warfarin"},
    "fields": {
        "purpose": {"text": "AI purpose text", "quote": "purpose quote"},
        "usual_dose": {"text": "2.5 mg daily", "quote": "dose quote"},
        "monitoring": {"text": "Check INR", "quote": "monitoring quote"},
    },
    "effects": [
        {"concept_id": "ldl-cholesterol", "label": "LDL cholesterol", "direction": "lowers", "note": "dose", "quote": "quote-ldl"},
        {"concept_id": None, "label": "Platelets", "direction": "raises", "note": "", "quote": "quote-plt"},
    ],
}


def base(**fields) -> dict:
    return {"kind": "medicine", "name": "Warfarin", "status": "current", **fields}


def cleaned(**fields):
    return factors.clean(base(**fields), today=TODAY)


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
        "reference_name", "reference_code",
    }


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


def test_a_broken_stored_suggestion_reads_as_none(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    db.connection.execute("UPDATE factors SET suggestion_json='{not json' WHERE id=?", (factor_id,))
    assert fetch(db, factor_id)["suggestion"] is None


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


def test_another_user_cannot_apply_a_suggestion_to_a_factor(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    factors.store_suggestion(db.connection, db.alpha, factor_id, SUGGESTION)
    assert factors.apply_suggestion(db.connection, db.beta, factor_id, "all", today=TODAY) is False
    assert fetch(db, factor_id)["effects"] == []


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


# --- AI suggestions -----------------------------------------------------------

def suggested_factor(db) -> str:
    factor_id = add(db, db.alpha, db.alpha_patient, purpose="Person wrote this", started_on="2025-01-01")
    factors.store_suggestion(db.connection, db.alpha, factor_id, SUGGESTION)
    return factor_id


def test_pending_lists_the_fields_and_effects_still_to_take(db):
    factor_id = suggested_factor(db)
    pending = factors.pending(fetch(db, factor_id))
    assert [field["name"] for field in pending["fields"]] == ["purpose", "usual_dose", "monitoring"]
    assert [effect["index"] for effect in pending["effects"]] == [0, 1]


def test_pending_leaves_out_an_effect_the_factor_already_has(db):
    factor_id = suggested_factor(db)
    factors.add_effect(db.connection, db.alpha, factor_id, concept_id="ldl-cholesterol", label="", direction="lowers")
    assert [effect["index"] for effect in factors.pending(fetch(db, factor_id))["effects"]] == [1]


def test_pending_of_no_suggestion_is_empty():
    assert factors.pending({"suggestion": None}) == {"fields": [], "effects": [], "empty": True}


def test_all_fills_only_the_empty_fields_and_marks_them_ai(db):
    factor_id = suggested_factor(db)
    assert factors.apply_suggestion(db.connection, db.alpha, factor_id, "all", today=TODAY) is True
    row = fetch(db, factor_id)
    assert (row["purpose"], row["usual_dose"]) == ("Person wrote this", "2.5 mg daily")


def test_all_records_the_filled_fields_as_ai_text(db):
    factor_id = suggested_factor(db)
    factors.apply_suggestion(db.connection, db.alpha, factor_id, "all", today=TODAY)
    assert fetch(db, factor_id)["ai_fields"] == ("usual_dose", "monitoring")


def test_all_adds_every_pending_effect_as_ai_with_its_quote(db):
    factor_id = suggested_factor(db)
    factors.apply_suggestion(db.connection, db.alpha, factor_id, "all", today=TODAY)
    effects = fetch(db, factor_id)["effects"]
    # Effects written in the same second order by id, so compare as a set.
    assert sorted((effect["origin"], effect["evidence"]) for effect in effects) == [("ai", "quote-ldl"), ("ai", "quote-plt")]


def test_naming_a_field_overwrites_the_person_text_and_marks_it(db):
    factor_id = suggested_factor(db)
    assert factors.apply_suggestion(db.connection, db.alpha, factor_id, "purpose", today=TODAY) is True
    row = fetch(db, factor_id)
    assert (row["purpose"], row["ai_fields"]) == ("AI purpose text", ("purpose",))


def test_naming_an_effect_adds_only_that_effect(db):
    factor_id = suggested_factor(db)
    assert factors.apply_suggestion(db.connection, db.alpha, factor_id, "effect:1", today=TODAY) is True
    effects = fetch(db, factor_id)["effects"]
    assert [(effect["label"], effect["origin"]) for effect in effects] == [("Platelets", "ai")]


def test_an_effect_index_out_of_range_is_refused(db):
    factor_id = suggested_factor(db)
    assert factors.apply_suggestion(db.connection, db.alpha, factor_id, "effect:9", today=TODAY) is False


def test_dismiss_clears_the_suggestion(db):
    factor_id = suggested_factor(db)
    assert factors.apply_suggestion(db.connection, db.alpha, factor_id, "dismiss", today=TODAY) is True
    assert fetch(db, factor_id)["suggestion"] is None


def test_an_unknown_action_is_refused(db):
    factor_id = suggested_factor(db)
    assert factors.apply_suggestion(db.connection, db.alpha, factor_id, "nonsense", today=TODAY) is False


def test_an_action_without_a_suggestion_is_refused(db):
    factor_id = add(db, db.alpha, db.alpha_patient)
    assert factors.apply_suggestion(db.connection, db.alpha, factor_id, "all", today=TODAY) is False


def test_editing_an_ai_field_removes_its_ai_mark(db):
    factor_id = suggested_factor(db)
    factors.apply_suggestion(db.connection, db.alpha, factor_id, "all", today=TODAY)
    values, _ = cleaned(
        purpose="Person wrote this", usual_dose="5 mg", monitoring="Check INR",
        started_on="2025-01-01",
    )
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
        f"- Warfarin [medicine; warfarin; ATC B01AA03] 1 mg; 5 mg, evening; since 2025-01-01; for AF; "
        f"effects: lowers LDL cholesterol m:{factor_id}"
    )


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
