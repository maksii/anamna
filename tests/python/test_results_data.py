"""The results view's data layer: options, filters, sorts, grouping by body system or test group, and the cap.

Pure tests on hand-built entries (``test_changes_view.entry``); no database.
"""

from __future__ import annotations

from anamna.web import changes

from test_changes_view import entry, report_of

AREAS = [("liver", "Liver"), ("blood", "Blood"), ("heart", "Heart")]


def arranged(report, areas=(), **options):
    return changes.arrange(report, changes.view_options(**options), areas=areas)


def names(result):
    return [e["name"] for section in result["sections"] for e in section["entries"]]


def in_area(area_id, count, **extra):
    return [entry(f"{area_id} {i}", "stable", area_id=area_id, area_name=area_id.title(), **extra) for i in range(count)]


def test_view_options_default_to_body_system_only_for_everything():
    assert changes.view_options()["group"] == "status"
    everything = changes.view_options(everything=True)
    assert everything["group"] == "area" and everything["default_group"] == "area"
    assert changes.view_options(everything=True, group="panel")["group"] == "panel"
    assert changes.view_options(show="outside")["show"] == "attention"
    assert changes.view_options(sort="nonsense", show="nonsense", group="nonsense")["sort"] == "status"
    assert changes.view_options(sort="date")["sort"] == "date"
    assert changes.view_options(area="blood")["area"] == "blood"


def test_view_query_leaves_out_the_mode_default_and_the_body_system():
    assert changes.view_query(changes.view_options()) == ""
    assert changes.view_query(changes.view_options(everything=True)) == ""
    assert changes.view_query(changes.view_options(everything=True, area="blood")) == ""
    assert changes.view_query(changes.view_options(everything=True, group="status")) == "group=status"
    assert changes.view_query(changes.view_options(group="area")) == "group=area"
    assert changes.view_query(changes.view_options(group="panel")) == "group=panel"
    assert changes.view_query(
        changes.view_options(everything=True, group="none", sort="date", show="due", reverse="1")
    ) == "sort=date&show=due&group=none&reverse=1"


def test_grouped_by_body_system_follows_the_given_order_and_puts_unknown_last():
    report = report_of([
        entry("heart one", "new", area_id="heart", area_name="Heart", attention=True),
        entry("blood one", "still", area_id="blood", area_name="Blood"),
        entry("blood two", "stable", area_id="blood", area_name="Blood", attention=True),
        entry("mystery", "borderline", area_id="mystery", area_name="Mystery"),
        entry("liver one", "still", area_id="liver", area_name="Liver"),
    ])
    result = arranged(report, AREAS, group="area")
    assert [s["key"] for s in result["sections"]] == ["area-liver", "area-blood", "area-heart", "area-mystery"]
    assert all(s["kind"] == "section" for s in result["sections"])
    blood, heart, mystery = result["sections"][1], result["sections"][2], result["sections"][3]
    assert blood["title"] == "Blood" and blood["url"] == "/areas/blood" and blood["url_kind"] == "area"
    assert blood["total"] == 2 and blood["flagged"] == 1 and blood["open"] is True
    assert heart["url"] == "/areas/heart"
    assert mystery["title"] == "Mystery" and mystery["url"] is None and mystery["total"] == 1
    assert result["shown"] == result["total"] == 5


def test_a_body_system_over_the_cap_shows_five_and_links_to_the_rest():
    report = report_of(in_area("blood", 7) + [entry("liver one", "still", area_id="liver", area_name="Liver")])
    result = arranged(report, AREAS, everything=True, show="all", group="area")
    blood = next(s for s in result["sections"] if s["key"] == "area-blood")
    assert len(blood["entries"]) == 5
    assert blood["total"] == 7
    assert blood["more_url"] == "/results?area=blood"
    assert blood["open"] is False


def test_nothing_is_cut_when_filtered_narrowed_or_not_everything():
    flagged = report_of(in_area("blood", 7, attention=True))
    section = arranged(flagged, AREAS, everything=True, show="attention", group="area")["sections"][0]
    assert len(section["entries"]) == 7 and section["more_url"] is None and section["open"] is True

    mixed = report_of(in_area("blood", 7) + [entry("liver one", "still", area_id="liver", area_name="Liver")])
    narrowed = arranged(mixed, AREAS, everything=True, area="blood")
    assert narrowed["total"] == 7 and narrowed["shown"] == 7
    assert [s["key"] for s in narrowed["sections"]] == ["area-blood"]
    assert len(narrowed["sections"][0]["entries"]) == 7 and narrowed["sections"][0]["more_url"] is None

    plain = arranged(mixed, AREAS, group="area")
    assert len(next(s for s in plain["sections"] if s["key"] == "area-blood")["entries"]) == 7


def test_grouped_by_test_group_caps_at_the_panel_page_and_follows_the_sort():
    liver = [
        entry(f"liver {i}", "stable", context="Liver", panel_url="/panels/liver", panel_id="liver")
        for i in range(6)
    ]
    report = report_of(liver + [
        entry("iron", "new", context="Iron", panel_url="/panels/iron", panel_id="iron", attention=True),
    ])
    result = arranged(report, group="panel", everything=True)
    iron, liver_section = result["sections"]
    assert [s["title"] for s in result["sections"]] == ["Iron", "Liver"]
    assert iron["key"] == "panel-iron" and iron["open"] is True and iron["more_url"] is None
    assert liver_section["key"] == "panel-liver" and liver_section["total"] == 6
    assert len(liver_section["entries"]) == 5 and liver_section["more_url"] == "/panels/liver"
    assert liver_section["url"] == "/panels/liver" and liver_section["url_kind"] == "panel"
    assert liver_section["open"] is False


def test_a_group_with_no_page_of_its_own_links_its_rest_to_the_body_system():
    result = arranged(report_of(in_area("heart", 7)), AREAS, group="panel", everything=True)
    section = result["sections"][0]
    assert len(section["entries"]) == 5 and section["total"] == 7
    assert section["url"] is None
    assert section["more_url"] == "/results?area=heart"


def test_due_and_attention_keep_only_their_flagged_entries():
    report = report_of([
        entry("flagged", "stable", attention=True),
        entry("due", "stable", due=True),
        entry("neither", "new"),
    ])
    assert names(arranged(report, group="none", show="due")) == ["due"]
    assert names(arranged(report, group="none", show="attention")) == ["flagged"]
    assert arranged(report, group="none", show="due")["total"] == 3


def test_date_sort_puts_the_newest_day_first_and_an_undated_result_last():
    report = report_of([
        entry("c-mar", "stable", day="2026-03-01"),
        entry("a-jan", "stable", day="2026-01-05"),
        entry("b-jan", "stable", day="2026-01-05"),
        entry("b-dec", "stable", day="2025-12-31"),
        entry("z-none", "stable", day=""),
    ])
    assert names(arranged(report, group="none", sort="date")) == ["c-mar", "a-jan", "b-jan", "b-dec", "z-none"]
    # Oldest first keeps the undated result last: no date is not "the oldest".
    assert names(arranged(report, group="none", sort="date", reverse="1")) == [
        "b-dec", "b-jan", "a-jan", "c-mar", "z-none"
    ]


def test_latest_positions_takes_the_newest_episode_of_a_test():
    daily = [{"observed_at": "2026-11-05"}, {"observed_at": "2026-11-03"}, {"observed_at": "2026-08-04"}]
    spans = [("2026-11-03", "2026-11-05"), ("2026-08-04", "2026-08-04")]
    assert changes._latest_positions(daily, spans) == [0, 1]


def test_latest_positions_for_an_undated_result():
    assert changes._latest_positions([{"observed_at": None}], [("", "")]) == [0]
