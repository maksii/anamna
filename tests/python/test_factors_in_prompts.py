"""Medicines and other factors reach the two AI hand-offs: the copy-for-AI export and the change summary.

Each assertion guards a way the model could be wrong about this person: a
medicine that is taken but not listed, a dose printed without its dates, a
medicine stopped years ago blamed for this week's result, a sentence naming a
medicine dropped by the grounding check, or an invented number let through
because a medicine happens to carry a number in its name.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from anamna import ai, factors
from anamna.db import connect
from anamna.web import changes

from test_ai_export import _prompt
from test_web_changes import build_changes_fixture, reply
from test_web_panels import build


def _add(settings, user_id: str, *, effect: str | None = None, **form) -> str:
    """A factor saved the way the Medicines form saves it: cleaned, then created."""
    values, error = factors.clean({key: str(value) for key, value in form.items()}, today=date.today())
    assert error is None, error
    with connect(settings) as connection:
        factor_id = factors.create(connection, user_id, f"patient-{user_id}", values)
        if effect:
            factors.add_effect(
                connection, user_id, factor_id, concept_id=None, label=effect, direction="raises"
            )
    return factor_id


def _days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _line_after(text: str, prefix: str) -> tuple[str, str]:
    """The line starting with ``prefix`` and the one under it."""
    lines = text.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    return lines[index], lines[index + 1]


def test_a_current_medicine_is_listed_with_its_dosing_dates_and_effect_in_english(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    started = _days_ago(120)
    _add(
        settings, user_id, kind="medicine", name="Діокор 80", substance="perindopril", strength="80 mg",
        dose="1 tablet", schedule="once daily", started_on=started, reason="blood pressure",
        effect="ferritin",
    )
    text = _prompt(client, locale="en")
    assert "## Medicines and other entries I recorded" in text
    line, effect = _line_after(text, "- Діокор 80")
    assert line == (
        f"- Діокор 80 80 mg [Medicine, Current]: perindopril; 1 tablet, once daily; "
        f"from {started}; blood pressure"
    )
    assert effect == "  - raises ferritin"
    # The gaps section no longer claims that medicines are absent.
    assert text.index("## Medicines and other entries I recorded") < text.index("What this record does NOT contain")


def test_a_current_medicine_is_listed_with_its_dosing_dates_and_effect_in_ukrainian(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    started = _days_ago(120)
    _add(
        settings, user_id, kind="medicine", name="Діокор 80", substance="perindopril", strength="80 mg",
        dose="1 tablet", schedule="once daily", started_on=started, reason="тиск",
        effect="ferritin",
    )
    text = _prompt(client, locale="uk")
    assert "## Мої записи про ліки та інше" in text
    line, effect = _line_after(text, "- Діокор 80")
    assert line == (
        f"- Діокор 80 80 mg [Ліки, Триває]: perindopril; 1 tablet, once daily; "
        f"з {started}; тиск"
    )
    assert effect == "  - підвищує ferritin"


def test_a_finished_supplement_shows_its_range_and_that_the_dates_are_approximate(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _add(
        settings, user_id, kind="supplement", name="Вітамін D3", started_on="2025-01-10",
        ended_on="2025-03-01", dates_approximate="1", status="past", effect="calcium",
    )
    en = _prompt(client, locale="en")
    assert "- Вітамін D3 [Supplement or vitamin, Finished]: 2025-01-10 to 2025-03-01 (the dates are approximate)" in en
    uk = _prompt(client, locale="uk")
    assert "- Вітамін D3 [Добавка або вітамін, Завершено]: 2025-01-10 – 2025-03-01 (дати приблизні)" in uk


def test_an_empty_record_says_none_is_recorded(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    text = _prompt(client, locale="en")
    assert "None recorded. Ask me what I take." in text


def test_weight_and_height_travel_when_they_are_set(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE patients SET weight_kg=?, height_cm=? WHERE owner_user_id=?", (82.5, 180, user_id)
        )
    en = _prompt(client, locale="en")
    assert "- Weight: 82.5 kg" in en
    assert "- Height: 180 cm" in en
    uk = _prompt(client, locale="uk")
    assert "- Вага: 82.5 кг" in uk
    assert "- Зріст: 180 см" in uk


def test_weight_and_height_are_left_out_when_unset(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    text = _prompt(client, locale="en")
    assert "- Weight:" not in text
    assert "- Height:" not in text


def test_the_change_summary_carries_current_factors_and_leaves_out_one_stopped_three_years_ago(tmp_path: Path):
    settings, user_id, _client, _ = build_changes_fixture(tmp_path)
    _add(
        settings, user_id, kind="medicine", name="Діокор 80", substance="perindopril", strength="80 mg",
        started_on=_days_ago(120), effect="ferritin",
    )
    long_ago_end = date.today() - timedelta(days=3 * 365)
    _add(
        settings, user_id, kind="medicine", name="Old antibiotic",
        started_on=(long_ago_end - timedelta(days=30)).isoformat(), ended_on=long_ago_end.isoformat(),
    )
    with connect(settings) as connection:
        view = changes.build_changes(connection, user_id)
        items = changes.factors_payload(connection, user_id, today=date.today())

    assert view["ai_payload"], "the fixture must produce a summary to attach factors to"
    assert view["ai_factors"] == items
    names = [item["name"] for item in items]
    assert "Діокор 80" in names
    assert "Old antibiotic" not in names
    current = items[0]
    assert current["status"] == "current"
    assert current["since"] == _days_ago(120)[:7]
    assert current["until"] is None
    assert current["can_change"] == [{"test": "ferritin", "direction": "raises"}]

    messages = changes.messages_for(view["ai_payload"], "en", items)
    user = json.loads(messages[1]["content"])
    assert set(user) == {"results", "factors"}
    assert user["factors"] == items
    assert "`factors` lists the medicines" in messages[0]["content"]


def _summary_of(settings, user_id: str, medicine: str, monkeypatch, *, pass_factors: bool):
    """Summarise the fixture's report with one medicine on record and a model reply naming it."""
    _add(
        settings, user_id, kind="medicine", name=medicine, substance="perindopril",
        started_on=_days_ago(120), effect="ferritin",
    )
    with connect(settings) as connection:
        view = changes.build_changes(connection, user_id)
    model = json.dumps({
        "state": (
            f"{medicine} може підвищувати цей показник. "
            "Zeta marker is now 7.0 mmol/L, above range. "
            "Показник сягає 42 одиниць."
        ),
        "findings": [],
        "improved": [],
    })
    fake = reply(model)
    monkeypatch.setattr(ai, "complete", fake)
    content, _model = changes.summarise(
        settings, view["ai_payload"], "uk", view["ai_factors"] if pass_factors else ()
    )
    return content, fake


def test_a_sentence_naming_a_medicine_with_a_number_survives_and_an_invented_number_does_not(
    tmp_path: Path, monkeypatch
):
    settings, user_id, _client, _ = build_changes_fixture(tmp_path)
    content, fake = _summary_of(settings, user_id, "Діокор 80", monkeypatch, pass_factors=True)

    # The medicine reached the model beside the results ...
    sent = json.loads(fake.calls[0]["messages"][1]["content"])
    assert [item["name"] for item in sent["factors"]] == ["Діокор 80"]
    # ... the sentence naming it kept its "80", and the invented 42 was dropped.
    assert content["state"] == (
        "Діокор 80 може підвищувати цей показник. Zeta marker is now 7.0 mmol/L, above range."
    )


def test_a_medicine_number_is_grounded_only_because_the_medicine_is_in_the_payload(
    tmp_path: Path, monkeypatch
):
    # 137 is not a measurement anywhere in this fixture (80 is, so it would prove nothing).
    settings, user_id, _client, _ = build_changes_fixture(tmp_path)
    content, _fake = _summary_of(settings, user_id, "Діокор 137", monkeypatch, pass_factors=True)
    assert content["state"].startswith("Діокор 137 може підвищувати цей показник.")

    (tmp_path / "again").mkdir()
    settings, user_id, _client, _ = build_changes_fixture(tmp_path / "again")
    content, _fake = _summary_of(settings, user_id, "Діокор 137", monkeypatch, pass_factors=False)
    assert "Діокор 137" not in content["state"]
    assert content["state"] == "Zeta marker is now 7.0 mmol/L, above range."
