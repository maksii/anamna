"""/changes: the reader's sort, filter and grouping, and the medicines that bear on each result.

The pure tests build entries by hand; the medicine test reuses the two-report
fixture of ``test_web_changes`` so the verdict engine decides every bucket.
The Changes page itself is a redirect into /results; its own tests live with /results.
"""

from __future__ import annotations

from pathlib import Path

from anamna.db import connect, utc_now
from anamna.web import changes

from test_web_changes import build_changes_fixture, view_for


def entry(name, bucket="stable", *, direction=None, context="Blood count", panel_url=None,
          unverified=False, influences=(), share=None, attention=False, due=False,
          area_id="other", area_name="Other results", panel_id=None, day=""):
    return {
        "name": name,
        "bucket": bucket,
        "direction": direction,
        "context": context,
        "panel_url": panel_url,
        "panel_id": panel_id,
        "area_id": area_id,
        "area_name": area_name,
        "day": day,
        "unverified": unverified,
        "influences": list(influences),
        "attention": attention,
        "due": due,
        "change": None if share is None else {"comparable": True, "share": share},
    }


def report_of(entries):
    """A report shaped like ``_build_report``: entries sorted, open and collapsed split."""
    ordered = sorted(entries, key=changes._sort_key)
    return {
        "open": [e for e in ordered if e["bucket"] in changes.OPEN_BUCKETS],
        "collapsed": [
            (bucket, [e for e in ordered if e["bucket"] == bucket])
            for bucket in changes.BUCKETS
            if bucket not in changes.OPEN_BUCKETS and any(e["bucket"] == bucket for e in ordered)
        ],
    }


def names(arranged):
    return [e["name"] for section in arranged["sections"] for e in section["entries"]]


def flat(report, **options):
    return changes.arrange(report, changes.view_options(**options))


MIXED = [
    entry("beta", "new", direction="worse", attention=True),
    entry("Alpha", "still", direction="better", context="Liver", panel_url="/panels/liver"),
    entry("gamma", "stable", context="Blood count"),
    entry("delta", "resolved", influences=[{"id": "f1"}]),
    entry("Epsilon", "first", unverified=True),
    entry("zeta", "borderline", context="Liver", panel_url="/panels/liver", due=True),
]


def test_default_options_keep_the_pages_own_layout():
    report = report_of(MIXED)
    arranged = flat(report)
    sections = arranged["sections"]
    # One open list (no heading), then one closed fold per quiet bucket, in bucket order.
    assert sections[0]["kind"] == "list" and sections[0]["entries"] == report["open"]
    folds = [section for section in sections if section["kind"] == "fold"]
    assert [section["entries"] for section in folds] == [entries for _, entries in report["collapsed"] if entries]
    assert [section["open"] for section in sections] == [True] + [False] * len(folds)
    assert arranged["shown"] == arranged["total"] == len(MIXED)
    assert arranged["nothing_open"] is False


def test_nothing_open_only_when_no_open_result_and_nothing_filtered():
    quiet = report_of([entry("only stable", "stable")])
    assert flat(quiet)["nothing_open"] is True
    assert flat(quiet, show="attention")["nothing_open"] is False
    assert flat(quiet, group="none")["nothing_open"] is False


def test_name_sort_is_case_insensitive_and_reverse_flips_it():
    report = report_of(MIXED)
    assert names(flat(report, sort="name", group="none")) == sorted(
        [e["name"] for e in MIXED], key=str.casefold
    )
    assert names(flat(report, sort="name", group="none", reverse="1")) == sorted(
        [e["name"] for e in MIXED], key=str.casefold, reverse=True
    )


def test_change_sort_puts_the_biggest_share_first_and_no_comparison_last():
    report = report_of([
        entry("small", share=5.0),
        entry("nothing to compare"),
        entry("large", share=40.0),
        entry("middle", share=12.0),
    ])
    assert names(flat(report, sort="change", group="none")) == ["large", "middle", "small", "nothing to compare"]


def test_filters_keep_what_they_name():
    report = report_of(MIXED)
    assert names(flat(report, show="attention", group="none")) == ["beta"]
    # The old name for the attention filter still works.
    assert names(flat(report, show="outside", group="none")) == ["beta"]
    assert {e["bucket"] for e in flat(report, show="changed", group="none")["sections"][0]["entries"]} == {
        "new", "resolved"
    }
    medicine = flat(report, show="medicine", group="none")
    assert names(medicine) == ["delta"]
    assert medicine["shown"] == 1 and medicine["total"] == len(MIXED)
    assert names(flat(report, show="unverified", group="none")) == ["Epsilon"]
    assert names(flat(report, show="due", group="none")) == ["zeta"]


def test_a_filter_with_no_match_has_no_sections():
    empty = flat(report_of([entry("plain")]), show="medicine")
    assert empty["sections"] == [] and empty["shown"] == 0


def test_group_by_test_group_follows_the_sort_with_headings():
    arranged = flat(report_of(MIXED), group="panel")
    assert [section["kind"] for section in arranged["sections"]] == ["section", "section"]
    # The attention result leads under the default status sort, so its group comes first.
    assert [section["title"] for section in arranged["sections"]] == ["Blood count", "Liver"]
    liver = arranged["sections"][1]
    assert liver["url"] == "/panels/liver" and liver["url_kind"] == "panel"
    assert [e["name"] for e in liver["entries"]] == ["Alpha", "zeta"]
    by_name = flat(report_of(MIXED), group="panel", sort="name")
    assert [section["title"] for section in by_name["sections"]] == ["Liver", "Blood count"]


def test_no_grouping_is_one_list_with_everything_shown():
    arranged = flat(report_of(MIXED), group="none")
    assert [section["kind"] for section in arranged["sections"]] == ["list"]
    assert len(arranged["sections"][0]["entries"]) == len(MIXED)
    assert flat(report_of([]), group="none")["sections"] == []


def test_unknown_choices_fall_back_to_the_page_defaults():
    assert changes.view_options("bogus", "bogus", "bogus", "2") == {
        "sort": "status", "show": "all", "default_group": "status", "group": "status",
        "reverse": False, "everything": False, "area": "",
    }
    assert changes.view_options("name", "medicine", "none", "1") == {
        "sort": "name", "show": "medicine", "default_group": "status", "group": "none",
        "reverse": True, "everything": False, "area": "",
    }


def test_view_query_names_only_what_differs_from_the_default():
    assert changes.view_query(changes.view_options()) == ""
    assert changes.view_query(changes.view_options("name", "", "", "1")) == "sort=name&reverse=1"
    assert changes.view_query(changes.view_options("", "medicine", "none")) == "show=medicine&group=none"
    assert changes.view_query(changes.view_options("", "", "", "1")) == "reverse=1"


def test_changes_page_redirects_to_results_with_the_same_view(tmp_path: Path):
    _, _, client, _ = build_changes_fixture(tmp_path)
    response = client.get("/changes?sort=name", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "/results?episode=latest&sort=name"


def test_changes_page_redirects_a_chosen_episode_unchanged(tmp_path: Path):
    _, _, client, _ = build_changes_fixture(tmp_path)
    response = client.get("/changes?episode=2026-01-05&show=changed", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "/results?episode=2026-01-05&show=changed"


def test_a_medicine_bears_on_its_result(tmp_path: Path):
    settings, user_id, _, ids = build_changes_fixture(tmp_path)
    factor_id = "factor-changes-view"
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO factors(id, owner_user_id, patient_id, kind, name, status, started_on, created_at, updated_at)
               VALUES (?, ?, ?, 'medicine', 'Test medicine', 'current', '2025-01-01', ?, ?)""",
            (factor_id, user_id, f"patient-{user_id}", utc_now(), utc_now()),
        )
        connection.execute(
            """INSERT INTO factor_effects(id, factor_id, owner_user_id, concept_id, label, direction, origin, created_at)
               VALUES (?, ?, ?, ?, 'Zeta marker', 'raises', 'person', ?)""",
            (f"effect-{factor_id}", factor_id, user_id, ids["Zeta marker"], utc_now()),
        )
    entries = {e["name"]: e for e in view_for(settings, user_id)["groups"][0]["open"]}
    assert entries["Zeta marker"]["influences"][0]["url"] == f"/medicines/{factor_id}"
