"""Medicines on the test-group pages: the entries that list an effect on a result
of a group show on ``/panels/<id>``, the group cards on ``/panels`` count them,
and a prescribed entry (not yet started) marks nothing.

The fixture is the one ``test_web_panels.build`` makes: LDL and HDL read on
2025-02-13, both in the ``lipids`` group.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from anamna import factors
from anamna.db import connect
from anamna.web import app as web
from test_web_panels import build

PANEL_ID = "lipids"
LDL = "ldl-cholesterol"


def add_entry(settings, user_id, patient_id, *, name, status="current", started="2025-01-10", ended="", effects=()):
    """One entry saved through ``factors.create``, with the given effects."""
    form = {"kind": "medicine", "name": name, "status": status, "started_on": started, "ended_on": ended}
    values, error = factors.clean(form, today=date.today())
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


def test_an_entry_that_moves_a_result_shows_on_its_group_and_card(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    patient_id = f"patient-{user_id}"
    factor_id = add_entry(settings, user_id, patient_id, name="Test medicine", effects=[(LDL, "raises")])

    detail = client.get(f"/panels/{PANEL_ID}")
    assert detail.status_code == 200
    assert "an-panel-medicines" in detail.text
    assert f'href="/medicines/{factor_id}"' in detail.text
    assert 'class="an-effect an-influence"' in detail.text
    assert "an-panel-member-row__influences" in detail.text

    cards = client.get("/panels")
    assert cards.status_code == 200
    assert "an-panel-card__medicines" in cards.text


def test_without_entries_neither_page_marks_anything(tmp_path: Path):
    _, _, client = build(tmp_path)

    detail = client.get(f"/panels/{PANEL_ID}")
    assert detail.status_code == 200
    assert "an-panel-medicines" not in detail.text
    assert "an-panel-member-row__influences" not in detail.text

    cards = client.get("/panels")
    assert cards.status_code == 200
    assert "an-panel-card__medicines" not in cards.text


def test_a_prescribed_entry_that_has_not_started_marks_nothing(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    patient_id = f"patient-{user_id}"
    add_entry(
        settings, user_id, patient_id, name="Planned medicine", status="prescribed",
        started="2026-06-01", effects=[(LDL, "lowers")],
    )

    detail = client.get(f"/panels/{PANEL_ID}")
    assert detail.status_code == 200
    assert "an-panel-medicines" not in detail.text
    assert "an-panel-member-row__influences" not in detail.text

    cards = client.get("/panels")
    assert "an-panel-card__medicines" not in cards.text


def test_the_shared_cards_are_not_mutated_by_the_group_page(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    patient_id = f"patient-{user_id}"
    add_entry(settings, user_id, patient_id, name="Test medicine", effects=[(LDL, "raises")])

    assert client.get(f"/panels/{PANEL_ID}").status_code == 200
    with connect(settings) as connection:
        cards = {card["id"]: card for card in web._metric_catalog(connection, user_id)}
    assert LDL in cards
    assert "influences" not in cards[LDL]
    assert "medicines_count" not in cards[LDL]
