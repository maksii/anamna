"""The diagnoses refresh job: when it runs, what it stores, and the background pass.

The metric cards are hand-built, as in the matrix tests, so no reference library is needed.
"""

from __future__ import annotations

import threading
import time
from datetime import date

import pytest

from anamna import diagnosis_candidates, diagnoses
from anamna.db import connect, migrate
from anamna.security import create_user
from anamna.web import diagnoses_job

from test_web_security import PASSWORD, seed_patient, settings_for

LDL_HIGH = "Above the European laboratory flagging cut-point"
TG_HIGH = "High"


def _card(name: str, label: str) -> dict:
    return {
        "name": name,
        "id": name.casefold().replace(" ", "-"),
        "url": f"/metrics/{name.casefold().replace(' ', '-')}",
        "value_text": "5.5",
        "unit": "mmol/L",
        "latest_date": date.today().isoformat(),
        "verdict": {
            "band_label": label,
            "source_id": "s",
            "source_name": "S",
            "source_url": "u",
            "authority_positions": [],
        },
    }


def _lipid_cards(connection, owner_id: str) -> list[dict]:
    return [_card("LDL cholesterol", LDL_HIGH), _card("Triglycerides", TG_HIGH)]


def _no_cards(connection, owner_id: str) -> list[dict]:
    return []


@pytest.fixture
def world(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, alpha, "Alpha Patient")
    return settings, alpha, patient


def _run(settings, owner_id: str, cards, *, force: bool = False) -> bool:
    with connect(settings) as connection:
        return diagnoses_job.refresh_if_changed(settings, connection, owner_id, cards, force=force)


def _suspicion_states(settings, owner_id: str) -> dict[str, str]:
    with connect(settings) as connection:
        return {
            row["rule_id"]: row["state"]
            for row in connection.execute(
                "SELECT rule_id, state FROM diagnosis_suspicions WHERE owner_user_id = ?", (owner_id,),
            )
        }


def _add_diagnosis(settings, owner_id: str, patient_id: str, code: str = "E78.2") -> None:
    values = {
        "code": code, "name": "", "status": "active", "certainty": "confirmed", "diagnosed_on": None,
        "resolved_on": None, "dates_approximate": 0, "clinician": "", "document_id": None, "notes": "",
    }
    with connect(settings) as connection:
        diagnoses.create(connection, owner_id, patient_id, values)
        connection.commit()


def test_the_first_refresh_runs_and_opens_a_possible_diagnosis(world):
    settings, alpha, _ = world
    assert _run(settings, alpha, _lipid_cards) is True
    assert _suspicion_states(settings, alpha) == {"lipid_mixed": "open"}


def test_an_unchanged_record_is_not_refreshed_again(world):
    settings, alpha, _ = world
    _run(settings, alpha, _lipid_cards)
    assert _run(settings, alpha, _lipid_cards) is False


def test_a_new_diagnosis_changes_the_fingerprint_and_triggers_a_refresh(world):
    settings, alpha, patient = world
    _run(settings, alpha, _lipid_cards)
    before = _run(settings, alpha, _lipid_cards)
    assert before is False

    _add_diagnosis(settings, alpha, patient)

    assert _run(settings, alpha, _lipid_cards) is True


def test_a_change_of_the_reading_rules_makes_the_record_be_read_again(world, monkeypatch):
    settings, alpha, _ = world
    _run(settings, alpha, _lipid_cards)
    assert _run(settings, alpha, _lipid_cards) is False
    monkeypatch.setattr(diagnosis_candidates, "READER_VERSION", diagnosis_candidates.READER_VERSION + 1)
    assert _run(settings, alpha, _lipid_cards) is True


def test_the_fingerprint_holds_the_reader_version(world, monkeypatch):
    settings, alpha, _ = world
    with connect(settings) as connection:
        before = diagnoses_job.fingerprint(connection, alpha)
        monkeypatch.setattr(diagnosis_candidates, "READER_VERSION", diagnosis_candidates.READER_VERSION + 1)
        after = diagnoses_job.fingerprint(connection, alpha)
    assert before != after


def test_force_runs_even_when_nothing_changed(world):
    settings, alpha, _ = world
    _run(settings, alpha, _lipid_cards)
    assert _run(settings, alpha, _no_cards, force=True) is True
    # The forced run used the cards it was given: nothing matches, so the open possible diagnosis clears.
    assert _suspicion_states(settings, alpha) == {"lipid_mixed": "cleared"}


def test_last_refreshed_is_set_after_a_run(world):
    settings, alpha, _ = world
    with connect(settings) as connection:
        assert diagnoses_job.last_refreshed(connection, alpha) is None
    _run(settings, alpha, _lipid_cards)
    with connect(settings) as connection:
        assert diagnoses_job.last_refreshed(connection, alpha)


def test_the_scheduler_runs_a_pass_and_stops_when_asked(world):
    settings, alpha, _ = world
    stop = diagnoses_job.start_scheduler(settings, _lipid_cards, interval=0.01)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with connect(settings) as connection:
            if diagnoses_job.last_refreshed(connection, alpha):
                break
        time.sleep(0.01)
    stop.set()
    for thread in threading.enumerate():
        if thread.name == "diagnoses-refresh":
            thread.join(10)
            assert not thread.is_alive()
    assert _suspicion_states(settings, alpha) == {"lipid_mixed": "open"}
