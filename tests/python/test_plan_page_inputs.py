"""The input half of /plan-tests on a phone: the needs list folds behind
"show all N" with a filter by reason, and the plan settings fold into one
summary line.  Synthetic record; the lab catalogue is stubbed."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from anamna import labsync, testplan
from anamna.locales.messages import MESSAGES
from anamna.security import create_session
from anamna.web import testplan_routes
from anamna.web.app import create_app
from anamna.labsync import esculab_shop

from test_testplan import GOOD, card, record  # noqa: F401 -- `record` is a fixture

NEW_KEYS = ("plan.why_label", "plan.why_all", "plan.why_flagged", "plan.why_due", "plan.needs_show_all",
            "plan.needs_show_less", "plan.selected_label", "plan.sum_no_city", "plan.sum_cheapest",
            "plan.sum_complete", "plan.sum_all_labs", "plan.sum_only")


@pytest.fixture
def page(record, monkeypatch):  # noqa: F811
    """Eight results to retest: seven out of range, one only due."""
    settings, user_id = record
    labsync.save_provider_settings(settings, "esculab", enabled=True, url="http://127.0.0.1:9")
    for key in [k for k in testplan_routes.SHOPS if k != "esculab"]:
        monkeypatch.delitem(testplan_routes.SHOPS, key)
    monkeypatch.setattr(esculab_shop, "catalog", lambda settings, region, base_url=None: [esculab_shop.item(GOOD)])
    monkeypatch.setattr(esculab_shop, "regions", lambda settings, base_url=None: [{"id": "3201", "name": "Львів"}])
    shown = {"value_text": "1", "unit": "", "date_text": "1 Jan 2026", "url": "/metrics/x"}
    cards = [{**card(f"c{n}", category="iron", reading="high"), **shown, "name": f"Result {n}",
              "verdict": {"interpretation": "high", "label": "High"}, "staleness": {"state": "fresh", "label": "Fresh"}}
             for n in range(7)]
    cards.append({**card("c7", category="iron", state="overdue"), **shown, "name": "Result 7",
                  "verdict": {"interpretation": "normal", "label": "Normal"},
                  "staleness": {"state": "overdue", "label": "Overdue"}})
    monkeypatch.setattr("anamna.web.app._metric_catalog", lambda connection, owner: cards)
    monkeypatch.setattr(testplan, "lab_concepts", lambda connection, owner: {c["id"] for c in cards})
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    return client


def test_the_needs_list_folds_and_filters_by_reason(page):
    page.cookies.set("anamna_lang", "en")
    html = page.get("/plan-tests").text
    assert html.count('name="need"') == 8 and "data-needs-list" in html
    assert 'data-more="Show all {count}"' in html and "Show all 8" in html
    # The reason filter: all, out of range (7), due (1).
    assert re.search(r'data-why="flagged">Out of range <span class="an-plan-why__n">7<', html)
    assert re.search(r'data-why="due">Due again <span class="an-plan-why__n">1<', html)
    assert len(re.findall(r'<li[^>]* data-why="flagged"', html)) == 7 and len(re.findall(r'<li[^>]* data-why="due"', html)) == 1
    # The lead paragraph and the step labels are gone; the count is live.
    assert "Step 1" not in html and re.search(r"Selected: <span data-selected-count>\d+</span>", html)
    page.cookies.set("anamna_lang", "uk")
    uk = page.get("/plan-tests").text
    assert "Показати всі 8" in uk and "Поза нормою" in uk and "Час повторити" in uk and "Обрано:" in uk


def test_the_settings_fold_into_one_summary_line(page):
    page.cookies.set("anamna_lang", "uk")
    html = page.get("/plan-tests?city=Львів").text
    summary = re.search(r"data-where-sum[^>]*>(.*?)</span>", html, re.S).group(1)
    assert summary == "Львів · спершу найдешевше"
    # A city is set and served, so the controls wait behind the summary.
    assert re.search(r'<section class="panel an-plan-where"[^>]*>\s*<details>', html)
    complete = page.get("/plan-tests?city=Львів&mode=complete&budget=2500").text
    assert re.search(r"data-where-sum[^>]*>Львів · найповніше<", complete) and 'name="budget"' not in complete
    # A city no lab serves opens the settings, with the warning inside.
    missing = page.get("/plan-tests?city=Атлантида").text
    assert re.search(r'<section class="panel an-plan-where"[^>]*>\s*<details open>', missing)
    page.cookies.set("anamna_lang", "en")
    assert "Lviv" not in page.get("/plan-tests?city=Львів").text  # city names stay as the lab spells them
    assert "Львів · cheapest first" in page.get("/plan-tests?city=Львів").text


def test_every_submit_returns_to_its_block(page):
    html = page.get("/plan-tests").text
    for block in ("plan-add", "plan-where"):
        assert re.search(rf'id="{block}"[^>]*data-return', html), block
    special = page.get("/plan-tests?special=1").text
    for block in ("plan-add", "plan-sets", "plan-where"):
        assert re.search(rf'id="{block}"[^>]*data-return', special), block
    # A filter that is set keeps its disclosure open.
    narrowed = page.get("/plan-tests?special=1&touched=1&skind=genetic").text
    assert '<details class="an-plan-narrow" open>' in narrowed


def test_new_keys_exist_in_both_locales():
    for key in NEW_KEYS:
        entry = MESSAGES[key]
        assert entry.get("en") and entry.get("uk"), key
    for key in ("plan.lead", "plan.step1", "plan.step2", "plan.needs_lead", "plan.sets_eyebrow"):
        assert key not in MESSAGES, key
