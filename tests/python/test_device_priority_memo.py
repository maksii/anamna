"""The per-pass memo and the cached source key must agree with the plain functions."""
import hashlib

from anamna.devices.reconcile import _rank, priority_memo, select_daily, selection_priority, source_key

BRIDGED = "OpenWearables · apple · Kitchen phone · iPhone14,2"


def _row(row_id, metric, vendor, name, value=60.0, aggregation="mean", day="2026-03-01"):
    return {
        "id": row_id, "metric_key": metric, "day": day, "value": value,
        "source_vendor": vendor, "source_name": name, "sample_count": 1, "aggregation": aggregation,
    }


def test_source_key_matches_the_plain_hash():
    for vendor, name in (("Oura", "Oura Ring"), ("openwearables", BRIDGED), (None, "x")):
        row = {"source_vendor": vendor, "source_name": name}
        expected = hashlib.sha256(f"{vendor}\0{name}".encode()).hexdigest()[:24]
        assert source_key(row) == expected


def test_priority_memo_agrees_with_selection_priority():
    rows = [
        _row("a", "steps", "Apple Health", "Apple Health"),
        _row("b", "steps", "Oura", "Oura"),
        _row("c", "resting_heart_rate", "Garmin", "Garmin"),
        _row("d", "resting_heart_rate", "openwearables", BRIDGED),
        _row("e", "resting_heart_rate", "Oura", "Oura"),
        _row("f", "ecg_heart_rate", "Kardia", "Kardia"),
    ]
    priority = priority_memo()
    for _ in range(2):  # the second pass is answered from the memo
        for row in rows:
            assert priority(row) == selection_priority(row)

    day_rows = [
        _row("x1", "resting_heart_rate", "Oura", "Oura", value=58.0),
        _row("x2", "resting_heart_rate", "Garmin", "Garmin", value=61.0),
        _row("x3", "resting_heart_rate", "openwearables", BRIDGED, value=64.0),
    ]
    expected = min(day_rows, key=_rank)["id"]
    assert [row["id"] for row in select_daily(day_rows)] == [expected]
