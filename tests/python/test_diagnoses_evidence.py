"""The evidence row of a possible diagnosis: the value in the reader's locale, and only for the same reading."""

from __future__ import annotations

from pathlib import Path

import pytest

from anamna.db import connect, migrate
from anamna.i18n import activate_locale, reset_locale, translate_phrase
from anamna.web import diagnoses_routes

from test_web_security import settings_for


@pytest.fixture
def connection(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    with connect(settings) as conn:
        yield conn


@pytest.fixture
def uk():
    token = activate_locale("uk")
    yield
    reset_locale(token)


def _page(connection, cards: dict[str, dict]) -> diagnoses_routes._Page:
    return diagnoses_routes._Page(connection, "owner", "uk", lambda *args, **kwargs: None, {}, cards)


def _item(**overrides) -> dict:
    item = {
        "metric": "Ferritin",
        "metric_id": "ferritin",
        "value": "2.5",
        "unit": "ng/mL",
        "date": "2026-03-04",
        "band": "High",
        "url": "/metrics/ferritin",
        "source_name": "Source",
        "source_url": "https://example.test/source",
    }
    item.update(overrides)
    return item


def _card(latest_date: str | None) -> dict:
    return {
        "id": "ferritin",
        "name": "Феритин",
        "value_text": "2,5",
        "unit": "нг/мл",
        "latest_date": latest_date,
    }


def test_same_reading_takes_the_localized_value_and_unit(connection, uk):
    page = _page(connection, {"ferritin": _card("2026-03-04T10:00:00")})

    view = diagnoses_routes._evidence_view(page, _item())

    assert view["metric"] == "Феритин"
    assert view["value_text"] == "2,5"
    assert view["unit"] == "нг/мл"
    assert view["url"] == "/metrics/ferritin"
    assert view["source_name"] == "Source"


def test_older_evidence_keeps_the_stored_value_and_unit(connection, uk):
    page = _page(connection, {"ferritin": _card("2026-05-01")})

    view = diagnoses_routes._evidence_view(page, _item())

    assert view["metric"] == "Феритин"
    assert view["value_text"] == "2.5"
    assert view["unit"] == "ng/mL"


def test_no_card_keeps_the_stored_value_and_translated_name(connection, uk):
    view = diagnoses_routes._evidence_view(
        _page(connection, {}), _item(metric="Clinical consultation", metric_id="", value="2.5", unit="ng/mL"),
    )

    assert view["metric"] == translate_phrase("Clinical consultation") == "Консультація лікаря"
    assert view["value_text"] == "2.5"
    assert view["unit"] == "ng/mL"


def test_undated_evidence_never_takes_a_card_value(connection, uk):
    page = _page(connection, {"ferritin": _card(None)})

    view = diagnoses_routes._evidence_view(page, _item(date=None))

    assert view["value_text"] == "2.5"
    assert view["unit"] == "ng/mL"
