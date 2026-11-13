"""The AI summary's severity and its numbers are held to the data and the engine's verdict.

The model words a change; the reference engine judges it.  A level that
contradicts the verdict is clamped, and a sentence is kept only when every
number in it is a measurement the payload carries, not a date, id or count.
The model is stubbed as in ``test_web_changes``; no provider is ever called.
"""

from __future__ import annotations

import json

import pytest

from anamna import ai, i18n
from anamna.db import connect
from anamna.web import app as web_app
from anamna.web import changes

from test_web_changes import build_changes_fixture, reply
from test_web_issue_reports import csrf_for


@pytest.mark.parametrize(
    ("level", "verdict", "expected"),
    [
        ("urgent", "borderline_high", "moderate"),
        ("marked", "normal", "moderate"),
        ("slight", "critical_high", "marked"),
        ("urgent", "critical_low", "urgent"),
        ("moderate", "high", "moderate"),
        ("slight", "low", "slight"),
        ("weird", "critical_high", "weird"),
        ("urgent", "", "urgent"),
    ],
)
def test_clamped_level_is_held_inside_the_engine_verdict(level, verdict, expected):
    assert changes._clamped_level(level, verdict) == expected


def test_measurement_numbers_take_values_and_bounds_but_not_dates_or_counts():
    payload = [{
        "date": "2026-03-14",
        "counts": {"New": 3},
        "changes": [{
            "test": "Zeta marker",
            "value": "5.4",
            "unit": "mmol/L",
            "target_range": "1 - 5 mmol/L",
            "beyond_target": {"side": "above upper limit", "percent": 8},
            "earlier": [{"month": "Mar 2026", "value": "4.9"}],
            "previous": {"date": "2026-03-01", "value": "4.9", "unit": "mmol/L", "verdict": "Within range"},
            "change": "+0.5 mmol/L (+10%)",
        }],
    }]
    found = changes._measurement_numbers(payload)
    for measured in (5.4, 4.9, 1.0, 5.0, 8.0, 0.5, 10.0):
        assert measured in found
    for not_measured in (14.0, 3.0, 2026.0, 2025.0):
        assert not_measured not in found


def test_summary_level_is_clamped_to_the_engine_verdict_and_stored_and_rendered(tmp_path, monkeypatch):
    settings, user_id, client, ids = build_changes_fixture(tmp_path)
    ai.save_ai_settings(settings, {"ai_api_key": "sk-test"})
    theta = ids["Theta marker"]
    engine = web_app._reading_verdict

    # The fixture's 1-5 band never yields a borderline verdict on its own, so
    # the engine's answer for this one test is replaced with a borderline one.
    def borderline_theta(connection, concept_id, row, age, sex):
        unit_source, verdict = engine(connection, concept_id, row, age, sex)
        if concept_id == theta:
            verdict = {**verdict, "interpretation": "borderline_high", "label": i18n.t("verdict.borderline_high")}
        return unit_source, verdict

    monkeypatch.setattr(web_app, "_reading_verdict", borderline_theta)
    model_reply = json.dumps({
        "state": "Zeta marker is now 7.0 mmol/L, above range.",
        "findings": [{
            "test": "Theta marker", "level": "urgent", "how_serious": "Theta marker reached 8.0 mmol/L.",
            "what_it_is": "A test of something.", "possible_reasons": [], "usually_next": [], "ask": [],
        }],
        "improved": [],
    })
    monkeypatch.setattr(ai, "complete", reply(model_reply))
    client.post(
        "/changes/ai-summary", data={"csrf_token": csrf_for(settings, user_id)},
        headers={"Accept": "application/json"},
    )
    with connect(settings) as connection:
        stored = json.loads(connection.execute("SELECT content_json FROM ai_change_summaries").fetchone()[0])
    (finding,) = stored["findings"]
    assert finding["test"] == "Theta marker" and finding["level"] == "moderate"
    theta_row = client.get("/results?episode=latest").text.split(">Theta marker</a>", 1)[1].split("</li>", 1)[0]
    assert 'data-level="moderate"' in theta_row and 'data-level="urgent"' not in theta_row


def test_a_sentence_quoting_a_number_found_only_in_a_date_is_dropped(tmp_path, monkeypatch):
    settings, user_id, client, _ = build_changes_fixture(tmp_path)
    ai.save_ai_settings(settings, {"ai_api_key": "sk-test"})
    # "13" appears only in the previous result's date ("13 Feb 2025"), never as a measurement.
    model_reply = json.dumps({
        "state": "Zeta marker is now 7.0 mmol/L, above range. Kappa marker was last compared on 13 Feb 2025.",
        "findings": [],
        "improved": [],
    })
    monkeypatch.setattr(ai, "complete", reply(model_reply))
    client.post(
        "/changes/ai-summary", data={"csrf_token": csrf_for(settings, user_id)},
        headers={"Accept": "application/json"},
    )
    with connect(settings) as connection:
        stored = json.loads(connection.execute("SELECT content_json FROM ai_change_summaries").fetchone()[0])
    assert stored["state"] == "Zeta marker is now 7.0 mmol/L, above range."


def test_the_summary_prompt_asks_for_the_combined_picture_and_never_a_dose():
    system = changes.messages_for([], "en")[0]["content"]
    assert "what the combination suggests" in system
    assert "named specifically" in system
    assert "Never a dose" not in system
    assert "No treatments, medicines or doses" not in system


def test_payload_years_come_from_date_fields_only():
    payload = [{
        "date": "2026-03-14",
        "changes": [{
            "value": "2024.5",
            "earlier": [{"month": "2025-11", "value": "4.9"}],
            "previous": {"date": "2026-03-14", "value": "4.9"},
        }],
    }]
    assert changes._payload_years(payload) == {2025.0, 2026.0}


def test_a_sentence_mentioning_only_the_year_of_an_earlier_reading_is_kept(tmp_path, monkeypatch):
    settings, user_id, client, _ = build_changes_fixture(tmp_path)
    ai.save_ai_settings(settings, {"ai_api_key": "sk-test"})
    # "2025" is the year of Kappa's previous reading ("13 Feb 2025"), named in the data as a date.
    model_reply = json.dumps({
        "state": "Zeta marker is now 7.0 mmol/L, above range. Kappa marker was last measured in 2025.",
        "findings": [],
        "improved": [],
    })
    monkeypatch.setattr(ai, "complete", reply(model_reply))
    client.post(
        "/changes/ai-summary", data={"csrf_token": csrf_for(settings, user_id)},
        headers={"Accept": "application/json"},
    )
    with connect(settings) as connection:
        stored = json.loads(connection.execute("SELECT content_json FROM ai_change_summaries").fetchone()[0])
    assert stored["state"] == (
        "Zeta marker is now 7.0 mmol/L, above range. Kappa marker was last measured in 2025."
    )
