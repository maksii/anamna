"""/plan-tests answers in place: presets add a whole reason to come in one
press, the two searches re-render through /plan-tests/live without a reload
(and never build a plan), and the page offers untick-all and reset.
Synthetic record; the lab catalogue is stubbed (one Esculab ferritin test)."""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from anamna import labsync, testplan, testplan_aliases, testplan_value
from anamna.db import connect
from anamna.labsync import esculab_shop
from anamna.locales.messages import MESSAGES
from anamna.security import create_session
from anamna.web import testplan_routes
from anamna.web.app import create_app

from test_testplan import GOOD, record  # noqa: F401 -- `record` is a fixture


@pytest.fixture
def page(record, monkeypatch):  # noqa: F811
    settings, user_id = record
    labsync.save_provider_settings(settings, "esculab", enabled=True, url="http://127.0.0.1:9")
    for key in [k for k in testplan_routes.SHOPS if k != "esculab"]:
        monkeypatch.delitem(testplan_routes.SHOPS, key)
    monkeypatch.setattr(esculab_shop, "catalog", lambda settings, region, base_url=None: [esculab_shop.item(GOOD)])
    monkeypatch.setattr(esculab_shop, "regions", lambda settings, base_url=None: [{"id": "3201", "name": "Львів"}])
    monkeypatch.setattr("anamna.web.app._metric_catalog", lambda connection, owner: [])
    monkeypatch.setattr(testplan, "lab_concepts", lambda connection, owner: set())
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "uk")
    return client


def test_a_preset_adds_what_a_lab_sells_to_the_one_list(page):
    html = page.get("/plan-tests?touched=1&preset=iron").text
    row = re.search(r'<li[^>]*data-key="ferritin"[^>]*>.*?</li>', html, re.S).group(0)
    assert 'data-why="added"' in row and 'name="need" value="ferritin" checked' in row
    # No notice: the tile and the list say what changed.
    assert 'role="status">Додано' not in html and "Набір додається" not in html
    # Pressed again with ferritin already ticked: still one row.
    again = page.get("/plan-tests?touched=1&need=ferritin&preset=iron").text
    assert again.count('data-key="ferritin"') == 1
    # Only presets with something the city's labs sell are offered.
    assert 'value="iron"' in html and 'value="checkup"' in html and 'value="sugar"' not in html
    assert "Готові набори" in html and "Зняти всі" in html and re.search(r'<a class="button secondary" href="/plan-tests">Скинути</a>', html)


def test_live_search_renders_both_blocks_and_never_builds_a_plan(page, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the live search built a plan")

    monkeypatch.setattr(testplan_value, "alternatives", refuse)
    reply = page.get("/plan-tests/live", params={"touched": "1", "q": "ферит", "sq": "", "plan": "1"})
    assert reply.status_code == 200 and set(reply.json()) == {"found", "sets", "match"}
    found = reply.json()["found"]
    assert 'name="add" value="ferritin"' in found and "data-fold" in found and "data-fold-more" in found
    assert 'data-status="1 збіг"' in found
    assert "sets_prompt" not in reply.json()["sets"] and "data-status" not in reply.json()["sets"]


def test_ticking_needs_no_add_button(page):
    html = page.get("/plan-tests?touched=1&q=ферит").text
    assert "Додати позначені" not in html and "Add ticked" not in html
    # The search button stays for a page without script; the script removes it.
    # Routine checks: one search box, no packages browser.
    assert len(re.findall(r" data-js-hide>", html)) == 1 and len(re.findall(r" data-live-field[\s>]", html)) == 1
    assert '<div data-live="found">' in html and '<div data-live="sets">' not in html
    # Special tests: the same box, plus the packages' kind, price ceiling and
    # sort (one lab here: no lab filter, no sections).
    special = page.get("/plan-tests?special=1&touched=1&q=ферит").text
    assert len(re.findall(r" data-js-hide>", special)) == 2 and len(re.findall(r" data-live-field[\s>]", special)) == 4
    assert '<div data-live="found">' in special and '<div data-live="sets">' in special


def test_preset_keys_are_real(record):  # noqa: F811
    settings, _ = record
    with connect(settings) as connection:
        concepts = {row[0] for row in connection.execute("SELECT id FROM concepts")}
    for sex in ("M", "F", None):
        for name, keys in testplan_routes.presets_for(sex).items():
            for key in keys:
                assert key in concepts or key in testplan_aliases.SAME, (name, key)
            assert MESSAGES[f"plan.preset_{name}"]["uk"] and MESSAGES[f"plan.preset_{name}_hint"]["en"], name
    # The full check-up holds every set offered (the person's own hormone set)
    # and the labs' check-up extras; never the other sex's set.
    men, women = testplan_routes.presets_for("M"), testplan_routes.presets_for("F")
    for offered in (men, women):
        assert all(set(keys) <= set(offered["checkup"]) for keys in offered.values())
    assert "x:psa-total" in men["checkup"] and "x:psa-total" not in women["checkup"]
    assert "cancer-antigen-125-ca-125" in women["checkup"] and "women" not in men and "men" not in women
    assert set(testplan_routes.CHECKUP_EXTRA) <= set(men["checkup"])
    for key in ("plan.add_submit", "plan.sets_include_submit", "plan.preset_lipids"):
        assert key not in MESSAGES, key


def _ferritin(days_ago: int) -> dict:
    day = (date.today() - timedelta(days=days_ago)).isoformat()
    return {"id": "ferritin", "name": "Феритин", "category": "iron", "is_device": False, "unit": "нг/мл",
            "value_text": "202", "date_text": day, "latest_date": day, "url": "/metrics/ferritin",
            "series": [{"date": "2025-01-01", "value": 150.0}, {"date": day, "value": 202.0}],
            "verdict": {"interpretation": "high", "label": "Вище норми", "high": 150.0, "low": 30.0},
            "staleness": {"state": "fresh", "label": "Свіжий"}}


@pytest.fixture
def measured(page, monkeypatch):
    def use(days_ago):
        monkeypatch.setattr("anamna.web.app._metric_catalog", lambda connection, owner: [_ferritin(days_ago)])
        monkeypatch.setattr(testplan, "lab_concepts", lambda connection, owner: {"ferritin"})
        return page
    return use


def test_a_result_measured_days_ago_is_left_unticked(measured):
    page = measured(4)
    html = page.get("/plan-tests").text
    # Out of range, so suggested, but measured four days ago: listed, not ticked.
    row = re.search(r"<li[^>]*data-recent[^>]*>.*?</li>", html, re.S).group(0)
    assert "data-skipped" in row and 'value="ferritin" >' in row and "здано 4 дні тому" in row
    assert re.search(r'role="switch" name="recent" value="1" checked data-recent-switch', html)
    assert "Не позначає 1 показник зі списку, зданий за останні 14 днів." in html
    # The switch off (a touched form without it) and the row is the person's to tick.
    off = page.get("/plan-tests?touched=1&need=ferritin").text
    assert re.search(r'name="recent" value="1"\s+data-recent-switch', off)
    # A preset skips it too.
    preset = page.get("/plan-tests?touched=1&recent=1&preset=iron").text
    assert 'value="ferritin" checked' not in preset
    # Two weeks and a day: suggested and ticked as before.
    old = measured(15).get("/plan-tests").text
    assert 'value="ferritin" checked' in old and "data-recent" not in old.split("data-recent-switch")[0].split("<form")[1]


def test_added_rows_show_the_latest_value_badge_and_trend(measured):
    page = measured(40)
    html = page.get("/plan-tests?touched=1&preset=vitamins").text
    body = re.search(r'<li[^>]*data-key="ferritin"[^>]*>.*?</li>', html, re.S).group(0)
    assert 'class="an-status-chip" data-interpretation="high"' in body and "Вище норми" in body
    assert 'class="an-sparkline"' in html and "Динаміка: Феритин" in html
    assert "an-sparkline" in body
    # Searched while on the list: the list shows it, the search adds nothing twice.
    reply = page.get("/plan-tests/live", params={"touched": "1", "need": "ferritin", "q": "ферит"}).json()
    assert reply["match"] == ["ferritin"] and 'value="ferritin"' not in reply["found"]


def test_presets_toggle_on_and_off(page):
    on = page.get("/plan-tests?touched=1&preset=iron").text
    button = re.search(r'<button type="submit" class="an-plan-preset" name="(\w+)" value="iron"\s+aria-pressed="(\w+)"', on)
    assert button.groups() == ("drop", "true") and "Обрано: усі 1" in on
    assert re.search(r'data-presets-on>(\d+)<', on).group(1) == "3"  # iron, vitamins and the check-up all hold ferritin alone
    off = page.get("/plan-tests?touched=1&need=ferritin&drop=iron").text
    assert 'value="ferritin" checked' not in off
    button = re.search(r'name="(\w+)" value="iron"\s+aria-pressed="(\w+)"', off)
    assert button.groups() == ("preset", "false")
