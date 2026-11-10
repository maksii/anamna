"""What the assistant reads about the person's body and medicines: the profile's
body line, the factor lines, and the get_medicines tool.

The model is not called.  Tools and the profile run against a temporary record,
and the one tool that could reach the network is run with the network refused.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from anamna import chat, drugref, factors
from anamna.db import connect, utc_now
from anamna.web import app as web
from anamna.web.chat_routes import build_tools, profile_summary

from test_chat import _other_person
from test_web_panels import build

SOURCE_URL = "https://tabletki.ua/uk/Coumadin/12345/"
SECTIONS = [["Показання", "Профілактика тромбозів"], ["Дозування", "2.5 мг щодня"]]


def _add(settings, owner: str, **fields) -> str:
    values, error = factors.clean({"kind": "medicine", "name": "Warfarin", "status": "current", **fields},
                                  today=date.today())
    assert error is None, error
    with connect(settings) as db:
        return factors.create(db, owner, f"patient-{owner}", values)


def _store_instruction(settings, url: str, sections: list[list[str]]) -> None:
    with connect(settings) as db:
        db.execute(
            "INSERT INTO drug_references(source, url, shown_for, atc_codes, sections_json, fetched_at) "
            "VALUES ('tabletki', ?, 'Warfarin', 'B01AA03', ?, ?)",
            (url, json.dumps(sections, ensure_ascii=False), utc_now()),
        )


def _profile(settings, owner: str) -> str:
    web.invalidate_catalog()
    with connect(settings) as db:
        return profile_summary(db, owner)


def _run(settings, owner: str, arguments: dict) -> str:
    with connect(settings) as db:
        return chat.run_tool(build_tools(db, owner), "get_medicines", arguments)


# --- the profile: body and factors -----------------------------------------------


def test_the_body_line_carries_weight_height_and_bmi_from_the_patient_row(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    with connect(settings) as db:
        db.execute(
            "UPDATE patients SET weight_kg=82, height_cm=180, activity_level='moderate', smoking_status='never' "
            "WHERE owner_user_id=?",
            (owner,),
        )
    profile = _profile(settings, owner)
    assert "body: weight 82 kg, height 180 cm, BMI 25.3; activity moderate; smoking never" in profile


def test_a_device_weight_displaces_the_typed_one_with_its_date(tmp_path: Path, monkeypatch):
    settings, owner, _client = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE patients SET weight_kg=82, height_cm=180 WHERE owner_user_id=?", (owner,))
    measured = {"weight_kg": {"value": 80.5, "day": "2026-10-30", "text": "80.5 kg"}}
    monkeypatch.setattr(web, "_measured_body", lambda _connection, _owner: measured)
    profile = _profile(settings, owner)
    assert "body: weight 80.5 kg (2026-10-30), height 180 cm, BMI 24.8" in profile


def test_the_body_line_says_what_is_not_recorded(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    assert ("body: weight and height not recorded (ask when a dose or a risk depends on them)"
            in _profile(settings, owner))


def test_the_body_line_gives_pregnancy_only_while_it_is_near(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    due = date.today() + timedelta(days=100)
    with connect(settings) as db:
        db.execute("UPDATE patients SET pregnancy_due_date=?, planning_pregnancy=1 WHERE owner_user_id=?",
                   (due.isoformat(), owner))
    profile = _profile(settings, owner)
    assert f"pregnant, due {due.isoformat()}" in profile and "planning a pregnancy" in profile


def test_the_profile_lists_a_current_medicine_with_its_dose_and_effect(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    factor_id = _add(settings, owner, substance="warfarin", atc_code="B01AA03", strength="1 mg",
                     dose="5 mg", schedule="evening", started_on="2025-01-01", reason="AF")
    with connect(settings) as db:
        factors.add_effect(db, owner, factor_id, concept_id="ldl-cholesterol", label="", direction="lowers")
    profile = _profile(settings, owner)
    assert "## medicines and other factors (1 current, 0 prescribed but not started, 0 past" in profile
    assert (f"- Warfarin [medicine; warfarin; ATC B01AA03] 1 mg; 5 mg, evening; since 2025-01-01; for AF; "
            f"effects: lowers LDL cholesterol m:{factor_id}") in profile


def test_the_profile_says_none_recorded_for_an_empty_record(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    profile = _profile(settings, owner)
    assert "## medicines and other factors" in profile
    assert "none recorded." in profile


# --- get_medicines ------------------------------------------------------------------


def test_get_medicines_without_arguments_lists_every_entry_including_a_past_one(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    _add(settings, owner, started_on="2025-01-01")
    _add(settings, owner, name="Ibuprofen", status="past", started_on="2024-01-01", ended_on="2024-02-01")
    text = _run(settings, owner, {})
    assert "- Warfarin [" in text and "- Ibuprofen [" in text
    assert "until 2024-02-01" in text


def test_get_medicines_with_an_id_gives_the_entry_and_its_instruction_sections(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    factor_id = _add(settings, owner, reference_name="Coumadin", reference_code="12345", started_on="2025-01-01")
    _store_instruction(settings, SOURCE_URL, SECTIONS)
    text = _run(settings, owner, {"medicine_id": f"m:{factor_id}"})
    assert text.startswith("- Warfarin [")
    assert text.splitlines()[-1] == (
        "instruction sections (official instruction for medical use, tabletki.ua): Показання; Дозування")


def test_get_medicines_with_a_section_returns_its_text(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    factor_id = _add(settings, owner, reference_name="Coumadin", reference_code="12345")
    _store_instruction(settings, SOURCE_URL, SECTIONS)
    assert _run(settings, owner, {"medicine_id": f"m:{factor_id}", "section": "дозув"}) == "Дозування:\n2.5 мг щодня"
    assert _run(settings, owner, {"medicine_id": f"m:{factor_id}", "section": "побічні"}) == (
        "No such section. Sections: Показання; Дозування")


def test_get_medicines_with_a_section_says_when_no_instruction_is_stored(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    factor_id = _add(settings, owner)
    assert _run(settings, owner, {"medicine_id": f"m:{factor_id}", "section": "дозування"}) == (
        "No instruction is stored for this entry.")


def test_get_medicines_makes_no_network_request(tmp_path: Path, monkeypatch):
    settings, owner, _client = build(tmp_path)
    factor_id = _add(settings, owner, reference_name="Coumadin", reference_code="12345")
    _store_instruction(settings, SOURCE_URL, SECTIONS)

    def refuse(*_args, **_kwargs):
        raise AssertionError("the assistant reached the network")

    monkeypatch.setattr(drugref, "_open", refuse)
    with connect(settings) as db:
        # Called directly: run_tool would turn the assertion into a sentence.
        tool = build_tools(db, owner)["get_medicines"]
        assert "tabletki.ua" in tool.run({"medicine_id": f"m:{factor_id}"})
        assert "Дозування:" in tool.run({"medicine_id": f"m:{factor_id}", "section": "дозу"})


def test_another_persons_medicine_id_is_not_found(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    other = _other_person(settings)
    with connect(settings) as db:
        other_factor = factors.create(
            db, other, f"patient-{other}", factors.clean({"kind": "medicine", "name": "Metformin",
                                                          "status": "current"}, today=date.today())[0],
        )
    assert _run(settings, owner, {"medicine_id": f"m:{other_factor}"}) == "No such medicine or factor."
    assert _run(settings, owner, {"medicine_id": other_factor, "section": "дозування"}) == (
        "No such medicine or factor.")
