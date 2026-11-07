from copy import deepcopy

import pytest

from anamna.devices.workout_reconcile import reconcile_workouts


def record(identifier, start="2026-09-08T10:00:00Z", end="2026-09-08T11:00:00Z", *,
           vendor="Apple Health", source="Apple Watch", kind="Walking", **extra):
    return {"id": identifier, "owner_user_id": "owner", "source_vendor": vendor, "source_name": source,
            "workout_type": kind, "started_at": start, "ended_at": end, "duration_minutes": 60,
            "energy_kcal": 200, "distance_km": 4, **extra}


def test_offset_equivalent_and_offset_autodetected_copies_are_one_original_value():
    rows = [record("watch", "2026-09-08T13:00:00+03:00", "2026-09-08T14:00:00+03:00"),
            record("ring", "2026-09-08T10:02:00Z", "2026-09-08T11:01:00Z", vendor="Oura", source="Oura", kind="walking", energy_kcal=230),
            record("bridge", vendor="OpenWearables", source="OpenWearables · Apple Health")]
    before = deepcopy(rows)
    result = reconcile_workouts(rows)
    assert len(result) == 1
    chosen = result[0]
    assert chosen["source_vendor"] != "OpenWearables"
    assert chosen["energy_kcal"] in (200, 230)
    assert chosen["record_count"] == chosen["source_count"] == 3
    assert {chosen["id"], *(row["id"] for row in chosen["alternates"])} == {"watch", "ring", "bridge"}
    assert rows == before
    assert reconcile_workouts(reversed(rows)) == result


def test_two_nonoverlapping_workouts_in_the_same_minute_remain_separate():
    rows = [record("a", end="2026-09-08T10:00:15Z"),
            record("b", "2026-09-08T10:00:30Z", "2026-09-08T10:00:50Z", vendor="Oura", source="Oura")]
    assert len(reconcile_workouts(rows)) == 2


def test_different_activity_types_and_contained_segments_do_not_merge():
    assert len(reconcile_workouts([record("a"), record("b", kind="Cycling", vendor="Oura", source="Oura")])) == 2
    assert len(reconcile_workouts([record("a"), record("b", end="2026-09-08T10:20:00Z", vendor="Oura", source="Oura")])) == 2


def test_bridge_record_cannot_transitively_combine_distinct_sessions():
    result = reconcile_workouts([
        record("a"),
        record("b", "2026-09-08T10:02:00Z", "2026-09-08T11:02:00Z", vendor="Oura", source="Oura"),
        record("c", "2026-09-08T10:04:00Z", "2026-09-08T11:04:00Z", vendor="OpenWearables", source="bridge"),
    ])
    assert len(result) == 2
    assert sum(item["record_count"] for item in result) == 3


def test_same_source_reimports_remain_inspectable_without_merging_different_sessions():
    result = reconcile_workouts([record("a"), record("b"), record("c", "2026-09-08T10:01:00Z", "2026-09-08T11:01:00Z")])
    assert len(result) == 2
    repeated = next(item for item in result if item["record_count"] == 2)
    assert repeated["source_count"] == 1
    assert len(repeated["alternates"]) == 1
    assert repeated["reconciliation"]["reason_codes"] == ["same_source_exact_interval"]


def test_strength_aliases_match_and_missing_end_can_use_recorded_duration():
    result = reconcile_workouts([record("a", kind="Traditional Strength Training", end=None),
                                 record("b", kind="strength_training", vendor="OpenWearables", source="bridge")])
    assert len(result) == 1
    assert result[0]["record_count"] == 2


@pytest.mark.parametrize("start,end", [
    ("2026-09-08T10:00:00", "2026-09-08T11:00:00"),
    ("bad", "bad"), ("2026-09-08", "2026-09-08"),
    ("2026-09-08T10:00:00Z", "2026-09-08T09:00:00Z"),
])
def test_unknown_clock_invalid_date_or_reversed_interval_never_invent_a_duplicate(start, end):
    assert len(reconcile_workouts([record("a"), record("b", start, end, vendor="Oura", source="Oura")])) == 2


def test_owner_boundaries_are_preserved_even_if_caller_supplies_mixed_rows():
    assert len(reconcile_workouts([record("a"), record("b", owner_user_id="other")])) == 2
