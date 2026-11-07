import pytest

from anamna.devices.apple_health import AppleHealthAdapter


def sleep(kind, start, end, source="Apple Watch"):
    return f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="{source}" startDate="{start}" endDate="{end}" value="HKCategoryValueSleepAnalysis{kind}"/>'


def parse(tmp_path, records):
    path = tmp_path / "export.xml"
    content = "<HealthData>\n" + "\n".join(records) + "\n</HealthData>"
    path.write_text(content, encoding="utf-8")
    result = AppleHealthAdapter().parse(path)
    assert path.read_text(encoding="utf-8") == content
    assert result.raw_record_count == len(records)
    assert result.export_ended_at == max(item.day for item in result.aggregates)
    return {(item.source_name, item.definition.key, item.day): item for item in result.aggregates}


def test_connected_stages_before_midnight_share_the_final_local_wake_date(tmp_path):
    values = parse(tmp_path, [
        sleep("AsleepCore", "2026-09-07 23:00:00 +0300", "2026-09-07 23:30:00 +0300"),
        sleep("AsleepDeep", "2026-09-07 23:30:00 +0300", "2026-09-08 01:00:00 +0300"),
        sleep("AsleepREM", "2026-09-08 01:00:00 +0300", "2026-09-08 05:00:00 +0300"),
    ])
    assert {key[2] for key in values} == {"2026-09-08"}
    assert values[("Apple Watch", "sleep_core", "2026-09-08")].value == 0.5
    assert values[("Apple Watch", "sleep_duration", "2026-09-08")].value == 6


def test_in_bed_connects_interrupted_sleep_but_does_not_add_awake_time_to_asleep(tmp_path):
    values = parse(tmp_path, [
        sleep("InBed", "2026-09-07 22:00:00 +0300", "2026-09-08 07:00:00 +0300"),
        sleep("AsleepCore", "2026-09-07 22:00:00 +0300", "2026-09-07 23:00:00 +0300"),
        sleep("AsleepDeep", "2026-09-08 01:00:00 +0300", "2026-09-08 07:00:00 +0300"),
    ])
    assert values[("Apple Watch", "sleep_duration", "2026-09-08")].value == 7
    assert values[("Apple Watch", "time_in_bed", "2026-09-08")].value == 9


def test_separate_naps_and_nights_stay_on_their_own_wake_days(tmp_path):
    values = parse(tmp_path, [
        sleep("Asleep", "2026-09-07 14:00:00 +0300", "2026-09-07 15:00:00 +0300"),
        sleep("Asleep", "2026-09-07 23:00:00 +0300", "2026-09-08 07:00:00 +0300"),
        sleep("Asleep", "2026-09-08 14:00:00 +0300", "2026-09-08 14:30:00 +0300"),
    ])
    assert values[("Apple Watch", "sleep_duration", "2026-09-07")].value == 1
    assert values[("Apple Watch", "sleep_duration", "2026-09-08")].value == 8.5
    assert values[("Apple Watch", "sleep_duration", "2026-09-08")].sample_count == 2


def test_a_different_sources_long_interval_cannot_redate_another_source(tmp_path):
    values = parse(tmp_path, [
        sleep("Asleep", "2026-09-07 21:00:00 +0300", "2026-09-07 22:00:00 +0300"),
        sleep("InBed", "2026-09-07 20:00:00 +0300", "2026-09-08 07:00:00 +0300", "Oura"),
    ])
    assert ("Apple Watch", "sleep_duration", "2026-09-07") in values
    assert ("Apple Watch", "sleep_duration", "2026-09-08") not in values


def test_overlapping_summary_and_stages_union_without_double_counting(tmp_path):
    values = parse(tmp_path, [
        sleep("Asleep", "2026-09-07 23:00:00 +0300", "2026-09-08 07:00:00 +0300"),
        sleep("AsleepCore", "2026-09-07 23:00:00 +0300", "2026-09-08 03:00:00 +0300"),
        sleep("AsleepDeep", "2026-09-08 03:00:00 +0300", "2026-09-08 07:00:00 +0300"),
    ])
    assert values[("Apple Watch", "sleep_duration", "2026-09-08")].value == 8


def test_daytime_shift_work_and_dst_use_local_end_date_and_elapsed_hours(tmp_path):
    values = parse(tmp_path, [
        sleep("AsleepCore", "2026-10-24 23:00:00 +0300", "2026-10-25 03:30:00 +0300"),
        sleep("AsleepDeep", "2026-10-25 03:30:00 +0300", "2026-10-25 07:00:00 +0200"),
        sleep("Asleep", "2026-10-26 08:00:00 +0200", "2026-10-26 16:00:00 +0200"),
    ])
    assert values[("Apple Watch", "sleep_duration", "2026-10-25")].value == pytest.approx(9)
    assert values[("Apple Watch", "sleep_duration", "2026-10-26")].value == 8


def test_absent_intervals_are_not_invented_to_bridge_an_unrecorded_gap(tmp_path):
    values = parse(tmp_path, [
        sleep("AsleepCore", "2026-09-07 22:00:00 +0300", "2026-09-07 23:00:00 +0300"),
        sleep("AsleepDeep", "2026-09-08 01:00:00 +0300", "2026-09-08 07:00:00 +0300"),
    ])
    assert values[("Apple Watch", "sleep_duration", "2026-09-07")].value == 1
    assert values[("Apple Watch", "sleep_duration", "2026-09-08")].value == 6
