"""Independent synthetic writer, exclusion and cache lifecycle regressions."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from anamna import garmin
from anamna.db import connect, utc_now
from anamna.devices import exclusions
from anamna.devices.catalog import metric
from anamna.devices.calculations import refresh_device_calculations
from anamna.devices.importer import import_device_export
from anamna.devices.models import Aggregate
from anamna.devices.queries import area_tracker, device_history_summary, device_metric_catalog, device_metric_comparison, device_metric_values
from anamna.devices.reconcile import source_key
from anamna.devices.reaggregate import reimport_files
from anamna.devices.structured import FIT_SCALE_SOURCE
from anamna.web import app as web

from test_garmin import configure, connect_business, deliver, daily
from test_linked_metrics import _build, _device_day
from test_web_profile import csrf_for
from test_round3_raw_devices import _fit_weight_archive


def _export(settings, owner, *, name="apple", value=80):
    folder = settings.source_dir / name
    folder.mkdir(exist_ok=True)
    source = folder / "export.xml"
    source.write_text(
        '<HealthData>\n<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Synthetic scale" '
        f'unit="kg" value="{value}" startDate="2025-01-01 08:00:00 +0000" '
        'endDate="2025-01-01 08:00:00 +0000"/>\n</HealthData>', encoding="utf-8",
    )
    result = import_device_export(settings, owner_user_id=owner, patient_id="patient-" + owner,
                                  vendor_key="apple_health", source=source)
    return source, result["import_id"]


def _weight(db, owner):
    return [row["value"] for row in device_metric_values(db, owner, "body_weight")]


@pytest.mark.parametrize("old_path_exists", [False, True])
def test_reimport_resolves_retained_export_under_configured_sources(tmp_path, old_path_exists):
    settings, owner, _ = _build(tmp_path)
    source, import_id = _export(settings, owner)
    previous = tmp_path / "previous-host" / "sources" / "apple" / "export.xml"
    if old_path_exists:
        previous.parent.mkdir(parents=True)
        previous.write_text(source.read_text(encoding="utf-8").replace('value="80"', 'value="777"'), encoding="utf-8")
    with connect(settings) as db:
        db.execute("UPDATE device_imports SET source_path=? WHERE id=?", (str(previous), import_id))
    result = next(item for item in reimport_files(settings, owner) if item["import_id"] == import_id)
    assert result["status"] == "reimported"
    with connect(settings) as db:
        assert _weight(db, owner) == [80]
        assert db.execute("SELECT source_path FROM device_imports WHERE id=?", (import_id,)).fetchone()[0] == str(source)


def test_fully_excluded_file_import_restores_on_undo_without_reviving_superseded_file(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _, old_import = _export(settings, owner, name="older", value=80)
    _, new_import = _export(settings, owner, name="newer", value=90)
    rule = exclusions.create(settings, owner, owner, provider="apple_health", source="Synthetic scale", scope="origin")
    exclusions.run_pending(settings, owner)
    with connect(settings) as db:
        assert _weight(db, owner) == []
        assert not db.execute("SELECT 1 FROM device_metric_days WHERE import_id=?", (new_import,)).fetchone()
    assert exclusions.undo(settings, owner, owner, rule)
    exclusions.run_pending(settings, owner)
    with connect(settings) as db:
        assert _weight(db, owner) == [90]
        assert not db.execute("SELECT 1 FROM device_metric_days WHERE import_id=?", (old_import,)).fetchone()
        assert not json.loads(db.execute("SELECT metadata_json FROM device_imports WHERE id=?", (new_import,)).fetchone()[0]).get("rebuild_after_exclusion")


def test_fully_excluded_mirrored_provider_restores_on_undo(tmp_path):
    settings, owner, _ = _build(tmp_path)
    configure(settings)
    connect_business(settings, owner)
    deliver(settings, {"dailies": [daily("2025-01-01", "synthetic-day", steps=123)]})
    garmin.process_pending(settings)
    rule = exclusions.create(settings, owner, owner, provider="garmin_api", source="Garmin", scope="origin")
    exclusions.run_pending(settings, owner)
    with connect(settings) as db:
        assert not device_metric_values(db, owner, "steps")
    exclusions.undo(settings, owner, owner, rule)
    exclusions.run_pending(settings, owner)
    with connect(settings) as db:
        assert [row["value"] for row in device_metric_values(db, owner, "steps")] == [123]


def test_explicit_zero_values_survive_the_real_writer_and_metric_catalog(tmp_path):
    settings, owner, _ = _build(tmp_path)
    with connect(settings) as db:
        for key, unit, aggregation in (("steps", "steps", "sum"), ("temperature_deviation", "°C", "average")):
            item = Aggregate(metric(key, key, "device_activity", unit, aggregation), "2025-01-01", "Synthetic device", "Garmin")
            item.add(0, "2025-01-01T08:00:00Z")
            garmin.replace_metric_days(db, owner, "imp-1", [key], [item.day], [item])
        cards = {card["id"]: card for card in device_metric_catalog(db, owner)}
        assert cards["device:steps"]["latest_numeric"] == 0
        assert cards["device:temperature_deviation"]["latest_numeric"] == 0
        summary = {item["metric_key"]: item for item in device_history_summary(db, owner)}
        assert summary["steps"]["day_count"] == 1
        assert summary["temperature_deviation"]["latest_value"] == 0


def test_same_second_provider_replacement_changes_the_device_fingerprint(tmp_path, monkeypatch):
    settings, owner, _ = _build(tmp_path)
    monkeypatch.setattr(garmin, "utc_now", lambda: "2025-02-01T12:00:00+00:00")
    def replace(value):
        item = Aggregate(metric("steps", "Steps", "device_activity", "steps", "sum"), "2025-01-01", "Synthetic watch", "Garmin")
        item.add(value, "2025-01-01T08:00:00Z")
        with connect(settings) as db:
            garmin.replace_metric_days(db, owner, "imp-1", ["steps"], [item.day], [item])
            return web._fingerprint(db, owner, "device")
    before = replace(100)
    after = replace(200)
    assert before != after


def test_missing_export_does_not_report_an_unapplied_exclusion_as_settled(tmp_path):
    settings, owner, _ = _build(tmp_path)
    source, _ = _export(settings, owner)
    rule = exclusions.create(settings, owner, owner, provider="apple_health", source="Synthetic scale", scope="origin")
    source.unlink()  # This synthetic arrival belongs only to this test.
    assert exclusions.run_pending(settings, owner) == 0
    with connect(settings) as db:
        assert db.execute("SELECT applied_at FROM device_exclusions WHERE id=?", (rule,)).fetchone()[0] is None


@pytest.mark.parametrize("key,unit,primary,other,area", [
    ("steps", "steps", 100, 200, "activity"),
    ("sleep_duration", "hours", 6, 8, "sleep"),
])
def test_patient_filter_precedes_catalog_comparison_history_and_tracker_selection(tmp_path, key, unit, primary, other, area):
    settings, owner, _ = _build(tmp_path)
    _device_day(settings, owner, key, "2025-01-01", primary, unit)
    _device_day(settings, owner, key, "2025-01-01", other, unit, vendor="Apple Health", name="Synthetic second device")
    with connect(settings) as db:
        db.execute("UPDATE device_metric_days SET category=?", ("device_activity" if key == "steps" else "device_sleep",))
        db.execute("INSERT INTO patients(id,owner_user_id,display_name,created_at) VALUES ('other-patient',?,'Synthetic other patient',?)", (owner, utc_now()))
        db.execute("UPDATE device_metric_days SET patient_id='other-patient' WHERE source_name='Synthetic second device'")
        second = dict(db.execute("SELECT * FROM device_metric_days WHERE patient_id='other-patient'").fetchone())
        db.execute("INSERT INTO device_source_preferences(owner_user_id,preference_group,source_key,updated_at) VALUES (?,?,?,?)", (owner, "sleep" if key == "sleep_duration" else key, source_key(second), utc_now()))
        for patient, expected in (("patient-" + owner, primary), ("other-patient", other)):
            comparison = device_metric_comparison(db, owner, key, patient_id=patient)
            assert comparison["stored_row_count"] == 1 and comparison["preferred"][0]["value"] == expected
            [card] = device_metric_catalog(db, owner, patient_id=patient)
            assert card["latest_numeric"] == expected and card["source_count"] == 1
            [summary] = device_history_summary(db, owner, patient_id=patient)
            assert summary["latest_value"] == expected and summary["months"][0]["mean"] == expected
            tracker = area_tracker(db, owner, area, patient_id=patient)
            assert tracker is not None
            if key == "steps":
                assert tracker["cards"][0]["latest_value"] == expected
            else:
                assert tracker["sleep"]["asleep_avg30"] == expected
        # Account-level tooling keeps all identities unless a patient is requested.
        assert device_metric_comparison(db, owner, key)["stored_row_count"] == 2


def test_device_revision_cascades_when_an_owner_with_device_evidence_is_removed(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _export(settings, owner)
    exclusions.create(settings, owner, owner, provider="apple_health", source="Synthetic scale", scope="origin")
    with connect(settings) as db:
        assert db.execute("SELECT revision FROM device_metric_revisions WHERE owner_user_id=?", (owner,)).fetchone()[0] > 0
        db.execute("DELETE FROM users WHERE id=?", (owner,))
        assert not db.execute("SELECT 1 FROM device_metric_revisions WHERE owner_user_id=?", (owner,)).fetchone()
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_failed_provider_rebuild_remains_pending_for_retry(tmp_path, monkeypatch):
    settings, owner, _ = _build(tmp_path)
    configure(settings)
    connect_business(settings, owner)
    deliver(settings, {"dailies": [daily("2025-01-01", "synthetic-day", steps=123)]})
    garmin.process_pending(settings)
    rule = exclusions.create(settings, owner, owner, provider="garmin_api", source="Garmin", scope="origin")
    def unavailable(*args):
        raise TimeoutError("Synthetic provider unavailable")
    monkeypatch.setattr(exclusions, "_rebuild_provider", unavailable)
    assert exclusions.run_pending(settings, owner) == 0
    with connect(settings) as db:
        assert db.execute("SELECT applied_at FROM device_exclusions WHERE id=?", (rule,)).fetchone()[0] is None


@pytest.mark.parametrize("key,unit,category", [("steps", "steps", "device_activity"), ("sleep_duration", "hours", "device_sleep")])
def test_saved_preferred_source_keeps_its_explicit_zero_and_clearing_restores_automatic_selection(tmp_path, key, unit, category):
    settings, owner, client = _build(tmp_path)
    rows = []
    for name, value in (("Synthetic preferred", 0), ("Synthetic alternative", 8)):
        item = Aggregate(metric(key, key, category, unit, "sum"), "2025-01-01", name, "Garmin")
        item.add(value, "2025-01-01T08:00:00Z")
        rows.append(item)
    with connect(settings) as db:
        garmin.replace_metric_days(db, owner, "imp-1", [key], ["2025-01-01"], rows)
        assert device_metric_values(db, owner, key)[0]["value"] == 8
        preferred = dict(db.execute("SELECT * FROM device_metric_days WHERE source_name='Synthetic preferred'").fetchone())
        evidence = [tuple(row) for row in db.execute("SELECT * FROM device_metric_days ORDER BY id")]
    csrf = csrf_for(settings, client)
    response = client.post('/devices/source-preference', data={"metric_key": key, "source_key": source_key(preferred), "csrf_token": csrf}, follow_redirects=False)
    assert response.status_code == 303
    with connect(settings) as db:
        assert device_metric_values(db, owner, key)[0]["value"] == 0
        assert device_metric_comparison(db, owner, key)["preferred"][0]["value"] == 0
        assert [tuple(row) for row in db.execute("SELECT * FROM device_metric_days ORDER BY id")] == evidence
    response = client.post('/devices/source-preference', data={"metric_key": key, "source_key": "", "csrf_token": csrf}, follow_redirects=False)
    assert response.status_code == 303
    with connect(settings) as db:
        assert device_metric_values(db, owner, key)[0]["value"] == 8


@pytest.mark.parametrize("scope", ["origin", "reading", "window"])
@pytest.mark.parametrize("series", [None, ["body_weight"], ["body_mass_index"]])
def test_new_fit_channel_cannot_recreate_excluded_scale_weight_or_bmi(tmp_path, scope, series):
    settings, owner, _ = _build(tmp_path)
    _device_day(settings, owner, "body_weight", "2025-01-01", 80, "kg")
    with connect(settings) as db:
        db.execute("UPDATE patients SET height_cm=200 WHERE owner_user_id=?", (owner,))
    rule = exclusions.create(settings, owner, owner, provider="garmin", source="Garmin Index Scale",
                             scope=scope, series=series, from_text="2025-01-01T12:00:00+00:00",
                             until_text="2025-01-01T13:00:00+00:00")
    with connect(settings) as db:
        db.execute("DELETE FROM device_metric_days WHERE source_name='Garmin Index Scale'")
    source = settings.source_dir / "synthetic-fit"
    source.mkdir()
    _fit_weight_archive(source, [{"timestamp": datetime(2025, 1, 1, 12, tzinfo=UTC), "weight": 80, "percent_fat": 20}])
    def reimport():
        import_device_export(settings, owner_user_id=owner, patient_id="patient-" + owner,
                             vendor_key="garmin", source=source)
        with connect(settings) as db:
            refresh_device_calculations(db)
            return {row["metric_key"]: row["value"] for row in db.execute("SELECT metric_key,value FROM device_metric_days")}
    values = reimport()
    assert "body_mass_index" not in values
    assert ("body_weight" in values) == (series == ["body_mass_index"])
    assert ("body_fat_percentage" in values) == (series is not None)
    assert exclusions.undo(settings, owner, owner, rule)
    restored = reimport()
    assert restored == {"body_weight": 80, "body_fat_percentage": 20, "body_mass_index": 20}


def test_fit_specific_exclusion_does_not_reach_canonical_scale_source(tmp_path):
    rule = exclusions.Rule("origin", None, None, None)
    canonical = exclusions.Matcher({"Garmin Index Scale": [rule]})
    assert canonical.excludes(FIT_SCALE_SOURCE, "body_weight", "2025-01-01T12:00:00Z")
    fit_only = exclusions.Matcher({FIT_SCALE_SOURCE: [rule]})
    assert fit_only.excludes(FIT_SCALE_SOURCE, "body_weight", "2025-01-01T12:00:00Z")
    assert not fit_only.excludes("Garmin Index Scale", "body_weight", "2025-01-01T12:00:00Z")
    settings, owner, _ = _build(tmp_path)
    _device_day(settings, owner, "body_weight", "2025-01-01", 80, "kg")
    _device_day(settings, owner, "body_weight", "2025-01-02", 80, "kg", name=FIT_SCALE_SOURCE)
    exclusions.create(settings, owner, owner, provider="garmin", source=FIT_SCALE_SOURCE,
                      scope="origin", series=["body_mass_index"])
    with connect(settings) as db:
        db.execute("UPDATE patients SET height_cm=200 WHERE owner_user_id=?", (owner,))
        refresh_device_calculations(db)
        assert [row["day"] for row in db.execute("SELECT day FROM device_metric_days WHERE metric_key='body_mass_index'")] == ["2025-01-01"]
