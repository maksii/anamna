"""Medicines and other entries that bear on a result: which entries list an effect
on a concept (``factors.influences``), which of them were under way on the day
of a result or happened since the one before (``factors.influencing``), how the
result page and the test-group panel print them (``factors_view``), and that the
macro renders the marks.  The database is a temporary one, built through the
same helpers the lifecycle tests use.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from anamna import factors
from anamna.db import connect, migrate, utc_now
from anamna.ingest.pipeline import seed_concepts
from anamna.security import create_user
from anamna.web import factors_view
from test_web_security import PASSWORD, settings_for

TODAY = date(2026, 11, 13)


@pytest.fixture
def owned(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "influence@example.test", "Influence", PASSWORD)
    patient_id = f"patient-{user_id}"
    with connect(settings) as connection:
        seed_concepts(connection)
        connection.execute(
            "INSERT INTO patients(id, owner_user_id, display_name, created_at) VALUES (?, ?, ?, ?)",
            (patient_id, user_id, "Test Patient", utc_now()),
        )
        connection.commit()
    return settings, user_id, patient_id


def add_entry(settings, user_id, patient_id, *, name, kind="medicine", status="current", started="", ended="", effects=()):
    """One entry saved through ``factors.create``, with the given status and effects."""
    form = {"kind": kind, "name": name, "status": status, "started_on": started, "ended_on": ended}
    values, error = factors.clean(form, today=TODAY)
    assert error is None, error
    values["status"] = status
    with connect(settings) as connection:
        factor_id = factors.create(connection, user_id, patient_id, values)
        for concept_id, direction in effects:
            factors.add_effect(
                connection, user_id, factor_id, concept_id=concept_id,
                label=concept_id, direction=direction,
            )
        connection.commit()
    return factor_id


def entry(**fields) -> dict:
    """An entry as ``factors.influences`` lists it."""
    return {
        "id": "x", "name": "Entry", "kind": "medicine", "start": "2026-01-01", "end": None,
        "point": False, "approximate": False, "direction": "raises", "note": "", "origin": "person",
        **fields,
    }


# --- factors.influences ------------------------------------------------------


def test_influences_maps_a_concept_to_its_entries_oldest_first(owned):
    settings, user_id, patient_id = owned
    warfarin = add_entry(
        settings, user_id, patient_id, name="Warfarin", started="2026-01-01", ended="2026-02-01",
        effects=[("ldl-cholesterol", "lowers"), ("ldl-cholesterol", "raises")],
    )
    surgery = add_entry(
        settings, user_id, patient_id, name="Surgery", kind="procedure", started="2026-01-10",
        effects=[("ldl-cholesterol", "changes")],
    )
    add_entry(
        settings, user_id, patient_id, name="Prescribed later", status="prescribed", started="2026-03-01",
        effects=[("ldl-cholesterol", "lowers")],
    )
    add_entry(settings, user_id, patient_id, name="Finished undated", status="past", started="", effects=[("ldl-cholesterol", "lowers")])
    with connect(settings) as connection:
        found = factors.influences(connection, user_id, today=TODAY)

    assert [item["name"] for item in found["ldl-cholesterol"]] == ["Warfarin", "Surgery"]
    first, second = found["ldl-cholesterol"]
    assert first["id"] == warfarin and second["id"] == surgery
    assert first["direction"] == "lowers"  # the first effect recorded for the entry and concept
    assert first["start"] == "2026-01-01" and first["end"] == "2026-02-01" and first["point"] is False
    assert first["undated"] is False
    assert second["point"] is True and second["end"] is None
    assert set(found) == {"ldl-cholesterol"}


def test_influences_keeps_an_undated_entry_only_while_it_is_under_way(owned):
    settings, user_id, patient_id = owned
    ongoing = add_entry(
        settings, user_id, patient_id, name="Ongoing undated", status="current", started="",
        effects=[("ldl-cholesterol", "lowers")],
    )
    add_entry(
        settings, user_id, patient_id, name="Finished undated", status="past", started="",
        effects=[("ldl-cholesterol", "lowers")],
    )
    add_entry(
        settings, user_id, patient_id, name="Procedure undated", kind="procedure", status="current", started="",
        effects=[("ldl-cholesterol", "lowers")],
    )
    with connect(settings) as connection:
        found = factors.influences(connection, user_id, today=TODAY)

    [item] = found["ldl-cholesterol"]
    assert item["id"] == ongoing
    assert item["undated"] is True and item["start"] is None
    assert item["name"] == "Ongoing undated"


def test_influences_marks_a_finished_entry_without_end_date_as_a_point(owned):
    settings, user_id, patient_id = owned
    add_entry(
        settings, user_id, patient_id, name="Old course", status="past", started="2025-06-01",
        effects=[("inr", "raises")],
    )
    with connect(settings) as connection:
        [item] = factors.influences(connection, user_id, today=TODAY)["inr"]
    assert item["point"] is True


# --- factors.influencing -----------------------------------------------------


def period(start="2026-01-01", end="2026-02-01", **fields) -> dict:
    return entry(start=start, end=end, **fields)


def test_a_period_is_under_way_on_days_inside_it_only():
    items = [period()]
    assert [item["when"] for item in factors.influencing(items, "2026-01-15")] == ["during"]
    assert factors.influencing(items, "2026-03-01") == []
    assert factors.influencing(items, "2025-12-31") == []
    assert factors.influencing(items, "2026-02-01")[0]["when"] == "during"


def test_an_open_period_is_under_way_from_its_start_onwards():
    items = [entry(start="2026-01-05", end=None)]
    assert factors.influencing(items, "2026-01-04") == []
    assert factors.influencing(items, "2026-01-05")[0]["when"] == "during"
    assert factors.influencing(items, "2026-12-31")[0]["when"] == "during"


def test_a_one_day_entry_bears_on_the_result_after_the_previous_one():
    items = [entry(start="2026-01-10", end=None, point=True)]
    found = factors.influencing(items, "2026-01-20", "2026-01-05")
    assert [item["when"] for item in found] == ["since"]
    assert factors.influencing(items, "2026-01-20", "2026-01-12") == []
    assert factors.influencing(items, "2026-01-20") == []
    assert factors.influencing(items, "2026-01-09", "2026-01-05") == []


def test_an_undated_entry_is_returned_for_any_day_as_undated():
    items = [entry(name="Ongoing undated", start=None, end=None, undated=True)]
    assert [item["when"] for item in factors.influencing(items, "2026-01-15")] == ["undated"]
    assert [item["when"] for item in factors.influencing(items, "2019-06-01", "2019-01-01")] == ["undated"]


def test_no_day_means_nothing_is_claimed():
    assert factors.influencing([period()], None) == []
    assert factors.influencing([period()], "") == []
    assert factors.influencing([entry(start=None, end=None, undated=True)], None) == []


# --- factors_view ------------------------------------------------------------


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_influence_chips_link_the_entry_and_name_direction_and_timing(locale):
    items = factors.influencing([period(id="abc", name="Warfarin", direction="lowers", origin="ai")], "2026-01-15")
    [chip] = factors_view.influence_chips(items, locale=locale)
    assert chip["url"] == "/medicines/abc"
    assert chip["direction"] == "lowers"
    assert chip["when"] == "during"
    assert chip["origin"] == "ai"
    assert chip["name"] == "Warfarin"
    assert chip["direction_label"] and chip["when_label"] and chip["kind_label"]


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_influence_chips_name_an_undated_entry_as_undated(locale):
    items = factors.influencing([entry(id="u", name="Ongoing", start=None, end=None, undated=True)], "2026-01-15")
    [chip] = factors_view.influence_chips(items, locale=locale)
    assert chip["when"] == "undated"
    assert chip["when_label"] and chip["period_text"]


def test_panel_entries_does_not_raise_on_an_undated_entry():
    by_concept = {
        "ldl-cholesterol": [entry(id="u", name="Ongoing", start=None, end=None, undated=True, direction="lowers")],
    }
    rows = [{"id": "ldl-cholesterol", "name": "LDL cholesterol", "url": "/metrics/ldl-cholesterol"}]
    [panel] = factors_view.panel_entries(rows, by_concept, locale="en")
    assert panel["id"] == "u" and panel["url"] == "/medicines/u"
    assert panel["effects"][0]["direction"] == "lowers"


def test_panel_entries_lists_an_entry_once_with_one_effect_per_result():
    by_concept = {
        "ldl-cholesterol": [entry(id="w", name="Warfarin", direction="lowers", start="2026-01-01", end="2026-02-01")],
        "hdl-cholesterol": [entry(id="w", name="Warfarin", direction="raises", start="2026-01-01", end="2026-02-01")],
    }
    rows = [
        {"id": "ldl-cholesterol", "name": "LDL cholesterol", "url": "/metrics/ldl-cholesterol"},
        {"id": "hdl-cholesterol", "name": "HDL cholesterol", "url": "/metrics/hdl-cholesterol"},
    ]
    [panel] = factors_view.panel_entries(rows, by_concept, locale="en")
    assert panel["id"] == "w" and panel["url"] == "/medicines/w"
    assert [effect["label"] for effect in panel["effects"]] == ["LDL cholesterol", "HDL cholesterol"]
    assert [effect["direction"] for effect in panel["effects"]] == ["lowers", "raises"]
    assert [effect["url"] for effect in panel["effects"]] == ["/metrics/ldl-cholesterol", "/metrics/hdl-cholesterol"]


# --- the macro ---------------------------------------------------------------


def macro():
    """The macro as the app loads it, with the app's filters and globals."""
    from anamna.web.app import templates

    return templates.env.get_template("_factors.html").module.influence_chips


def test_the_influence_macro_prints_a_link_with_direction_and_timing():
    chips = factors_view.influence_chips(
        factors.influencing([period(id="abc", name="Warfarin", direction="raises")], "2026-01-15"), locale="en",
    )
    html = str(macro()(chips))
    assert 'href="/medicines/abc"' in html
    assert 'data-direction="raises"' in html
    assert 'data-when="during"' in html
    assert "Warfarin" in html


def test_the_influence_macro_prints_nothing_without_chips():
    assert str(macro()([])).strip() == ""
