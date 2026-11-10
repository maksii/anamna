"""Audit of the vaccination rules: what each product covers, what the adult
schedule says is owed, what the calendar covers for everyone, and whether every
disease the page can show has a Ukrainian sentence beside its English one.

The facts asserted here come from Ukraine's vaccination calendar (МОЗ order 595)
and from the adult schedules `immunizations.SCHEDULE` cites.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from anamna.immunizations import (
    DISEASES,
    SCHEDULE,
    VACCINE_CODES,
    calendar_diseases_without_a_dose,
    find_gaps,
    identify_vaccine,
)
from anamna.locales.phrases import PHRASES


def _gaps(doses: list[dict[str, object]], today: date) -> dict[str, object]:
    return {gap.key: gap for gap in find_gaps(doses, today)}


# --- adult schedule: items whose authorities differ ---------------------------

def test_a_covid_dose_three_years_old_is_a_point_to_discuss_not_a_due_date():
    today = date(2026, 11, 10)
    gap = _gaps([{"occurrence_date": "2023-03-01", "diseases": "covid19"}], today)["covid_booster"]
    assert gap.kind == "discuss"
    assert gap.due_date is None
    assert gap.urgency == "unknown"


def test_a_recent_covid_dose_leaves_nothing_to_raise():
    today = date(2026, 11, 10)
    recent = (today - timedelta(days=30)).isoformat()
    assert "covid_booster" not in _gaps([{"occurrence_date": recent, "diseases": "covid19"}], today)


def test_no_covid_dose_on_file_is_a_point_to_discuss_without_a_date():
    gap = _gaps([], date(2026, 11, 10))["covid_booster"]
    assert gap.kind == "discuss"
    assert gap.due_date is None


def test_an_influenza_dose_from_two_seasons_ago_is_a_point_to_discuss_not_overdue():
    today = date(2026, 11, 10)
    gap = _gaps([{"occurrence_date": "2024-11-05", "diseases": "influenza"}], today)["influenza_season"]
    assert gap.kind == "discuss"
    assert gap.due_date is None
    assert gap.urgency != "overdue"


def test_an_influenza_dose_in_the_current_season_leaves_nothing_to_raise():
    doses = [{"occurrence_date": "2026-10-01", "diseases": "influenza"}]
    assert "influenza_season" not in _gaps(doses, date(2026, 11, 10))


def test_between_influenza_seasons_there_is_nothing_to_raise():
    assert "influenza_season" not in _gaps([], date(2026, 7, 1))


def test_a_differs_item_never_gets_a_due_date_or_overdue_urgency():
    differing = {item.key for item in SCHEDULE if item.agreement == "differs"}
    assert differing == {"influenza_season", "covid_booster"}
    histories = [
        [],
        [{"occurrence_date": "2024-11-05", "diseases": "influenza,covid19"}],
        [{"occurrence_date": "2025-06-01", "diseases": "covid19"}],
    ]
    for offset in range(0, 900, 37):
        today = date(2025, 1, 1) + timedelta(days=offset)
        for doses in histories:
            for gap in find_gaps(doses, today):
                if gap.agreement == "differs":
                    assert gap.kind == "discuss", gap
                    assert gap.due_date is None, gap
                    assert gap.urgency != "overdue", gap


# --- adult schedule: agreed items ---------------------------------------------

def test_a_tetanus_booster_twelve_years_old_is_overdue_and_agreed_by_ua_and_us():
    today = date(2026, 11, 10)
    old = (today - timedelta(days=12 * 365)).isoformat()
    gap = _gaps([{"occurrence_date": old, "diseases": "diphtheria,tetanus"}], today)["td_booster"]
    assert gap.kind == "due"
    assert gap.urgency == "overdue"
    assert gap.agreement == "agreed_ua_us"


# --- unfinished courses --------------------------------------------------------

def test_an_unfinished_course_claims_no_timing():
    doses = [{"occurrence_date": "2026-01-08", "diseases": "hpv", "dose_number": 2, "doses_in_series": 3}]
    gap = _gaps(doses, date(2026, 11, 10))["series:hpv"]
    assert gap.kind == "series"
    assert gap.urgency == "unknown"


# --- vaccine code map ----------------------------------------------------------

def test_pcv10_is_credited_with_pneumococcus_only():
    assert VACCINE_CODES["PCV10"] == ("pneumococcus",)


def test_a_meningococcal_c_conjugate_is_not_credited_with_acwy():
    assert VACCINE_CODES["MenC_conj"] == ("meningococcus_c",)
    assert "meningococcus_acwy" not in VACCINE_CODES["MenC_conj"]


def test_men_acwy_135_keeps_its_four_serogroups():
    assert VACCINE_CODES["Men_ACWY_135"] == ("meningococcus_acwy",)


@pytest.mark.parametrize("phrase", ["менінгокової інфекції серогрупи", "менінгококів серогрупи"])
def test_a_serogroup_wording_credits_acwy_only_when_all_four_serogroups_are_named(phrase):
    assert identify_vaccine(f"вакцина для профілактики {phrase} A, C, W-135 та Y")[1] == ("meningococcus_acwy",)
    assert "meningococcus_acwy" not in identify_vaccine(f"вакцина для профілактики {phrase} A та C")[1]


def test_every_disease_key_in_the_code_map_exists():
    unknown = sorted(
        (code, key)
        for code, keys in VACCINE_CODES.items()
        for key in keys
        if key not in DISEASES
    )
    assert unknown == []


# --- the national calendar -----------------------------------------------------

def test_hpv_is_not_a_calendar_vaccine_for_everyone():
    assert DISEASES["hpv"].ua_calendar is False
    assert "hpv" not in calendar_diseases_without_a_dose([])


# --- translations --------------------------------------------------------------

def test_every_disease_name_and_explanation_has_a_ukrainian_sentence():
    missing = [
        text
        for disease in DISEASES.values()
        for text in (disease.name, disease.explanation)
        if text not in PHRASES
    ]
    assert missing == []
