"""Audit fixes in the planner and lab routes: an unknown Esculab region never
reaches the lab, a garbled total answers with a redirect, a doctor link keeps
one pending suggestion per record, the admin counts read only ASCII digits, and
a heading with markup characters renders in the health-history PDF."""

from __future__ import annotations

from anamna.db import connect
from anamna.i18n import format_number_localized
from anamna.labsync import esculab_shop
from anamna.labsync.common import LabSyncError
from anamna.web import health_export, labsync_routes, testplan_routes

from test_plan_doctor import app_for, csrf, doctor_client, owner_client  # noqa: F401 -- app_for is a fixture
from test_testplan import record  # noqa: F401 -- record is a fixture


def test_known_region_accepts_only_the_regions_the_lab_lists(monkeypatch):
    monkeypatch.setattr(esculab_shop, "regions", lambda settings, base_url=None: [{"id": 7, "name": "X"}])
    assert testplan_routes._known_region(None, "esculab", "7") == "7"
    assert testplan_routes._known_region(None, "esculab", "8") is None
    assert testplan_routes._known_region(None, "esculab", "") is None
    assert testplan_routes._known_region(None, "esculab", None) is None


def test_known_region_accepts_nothing_while_the_lab_list_is_unavailable(monkeypatch):
    def unreachable(settings, base_url=None):
        raise LabSyncError("labsync.error_unreachable")

    monkeypatch.setattr(esculab_shop, "regions", unreachable)
    assert testplan_routes._known_region(None, "esculab", "7") is None


def test_expected_total_is_a_finite_number_or_none():
    assert testplan_routes._expected_total({"expected": "12,5"}) == 12.5
    assert testplan_routes._expected_total({}) == 0.0
    assert testplan_routes._expected_total({"expected": "abc"}) is None
    assert testplan_routes._expected_total({"expected": "nan"}) is None


def test_the_cached_list_is_stale_only_when_it_disagrees_with_fresh_prices():
    assert testplan_routes._list_is_stale(150.0, 150.0) is False
    assert testplan_routes._list_is_stale(150.0, 150.004) is False
    assert testplan_routes._list_is_stale(150.0, 162.5) is True


def test_an_unknown_city_in_the_planner_reads_as_no_city(app_for, monkeypatch):  # noqa: F811
    settings, user_id, app = app_for
    seen = []
    monkeypatch.setattr(testplan_routes, "_lab_items", lambda settings, connection, owner, key, region: seen.append(region) or [])
    client = owner_client(app, settings, user_id)
    assert client.get("/plan-tests?city_esculab=999&touched=1").status_code == 200
    assert seen == [esculab_shop.DEFAULT_REGION]


def test_an_esculab_order_with_a_garbled_total_goes_back_to_the_planner(app_for):  # noqa: F811
    settings, user_id, app = app_for
    client = owner_client(app, settings, user_id)
    html = client.get("/plan-tests").text
    reply = client.post("/plan-tests/order/esculab", data={
        "csrf_token": csrf(html), "region": "3201", "expected": "abc", "item": ["1"],
        "plan_query": "touched=1&plan=1", "order_nonce": "garbled-total"}, follow_redirects=False)
    assert reply.status_code == 303 and "notice=items_gone" in reply.headers["location"]


def test_a_doctor_link_holds_one_pending_suggestion_per_record(app_for):  # noqa: F811
    settings, user_id, app = app_for
    doctor = doctor_client(app, settings, user_id)
    html = doctor.get("/plan-tests?touched=1&need=ferritin&plan=1").text
    doctor.post("/plan-tests/suggest", data={"csrf_token": csrf(html), "query": "touched=1&need=ferritin&plan=1"},
                follow_redirects=False)
    newer = "touched=1&need=ferritin&need=tsh&plan=1"
    replaced = doctor.post("/plan-tests/suggest", data={"csrf_token": csrf(html), "query": newer},
                           follow_redirects=False)
    assert replaced.status_code == 303 and "notice=suggestion_saved" in replaced.headers["location"]
    other = doctor_client(app, settings, user_id)
    other_html = other.get("/plan-tests?touched=1&need=ferritin&plan=1").text
    other.post("/plan-tests/suggest", data={"csrf_token": csrf(other_html), "query": "touched=1&need=ferritin&plan=1"},
               follow_redirects=False)
    with connect(settings) as connection:
        rows = connection.execute(
            "SELECT query, token_id FROM plan_suggestions WHERE owner_user_id=?", (user_id,)).fetchall()
    # One row per doctor link: the first link's older suggestion was replaced by the newer one,
    # and the second link holds its own.
    older = testplan_routes.suggestion_query("touched=1&need=ferritin&plan=1")
    assert len(rows) == 2 and len({row["token_id"] for row in rows}) == 2
    assert sorted(row["query"] for row in rows) == sorted([testplan_routes.suggestion_query(newer), older])


def test_recheck_counts_read_only_ascii_digits():
    # "²" is str.isdigit() but int() rejects it: it must be skipped, not raise.
    assert "orders" not in labsync_routes._rechecked_counts({"orders": "²"})
    counts = labsync_routes._rechecked_counts({"orders": "12", "flags": "x"})
    assert counts["orders"] == format_number_localized(12, 0)
    assert "flags" not in counts


def test_a_metric_name_with_markup_characters_builds_its_heading():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import KeepTogether, Paragraph

    style = ParagraphStyle("ExportTest")
    paragraph = lambda value, style=style: health_export._pdf_paragraph(Paragraph, value, style)  # noqa: E731
    labels = {key: key for key in ("latest", "period", "not_available", "column_date", "column_result",
                                   "column_comparison", "column_source", "unknown_source")}
    metric = {"name": "Anti-HBs <10 & more", "latest": {}, "period_text": "2024", "rows": []}
    story = health_export._metric_story(metric, False, paragraph, (style, style, style, style), labels, "Helvetica")
    heading = story[0]
    assert isinstance(heading, KeepTogether)
    assert heading._content[0].text == "Anti-HBs &lt;10 &amp; more"
