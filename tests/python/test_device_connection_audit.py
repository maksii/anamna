"""Synthetic evidence for device quantities reaching their clinical panels."""
from __future__ import annotations

import pytest
import json
import runpy
from pathlib import Path

from anamna.devices.apple_health import AppleHealthAdapter
from anamna import garmin, garmin_personal, openwearables, oura
from anamna.config import resource_path
from anamna.devices.apple_health import ECG_HEART_RATE, STAND_HOURS
from anamna.devices.catalog import HEALTHKIT_METRICS, SLEEP_METRICS
from anamna.devices.oura_export import FIELDS
from anamna.panels import SAME_DEVICE_KEYS, TWIN_OF_DEVICE, panel_for_concept


def test_body_temperature_import_converts_units_and_keeps_latest(tmp_path):
    source = tmp_path / "export.xml"
    source.write_text(
        '<HealthData>\n'
        '<Record type="HKQuantityTypeIdentifierBodyTemperature" sourceName="Thermometer" '
        'unit="degF" startDate="2026-08-01 08:00:00 +0300" '
        'endDate="2026-08-01 08:00:00 +0300" value="98.6"/>\n'
        '<Record type="HKQuantityTypeIdentifierBodyTemperature" sourceName="Thermometer" '
        'unit="degC" startDate="2026-08-01 19:00:00 +0300" '
        'endDate="2026-08-01 19:00:00 +0300" value="37.5"/>\n'
        '</HealthData>',
        encoding="utf-8",
    )
    parsed = AppleHealthAdapter().parse(source)
    reading, = parsed.aggregates
    assert reading.definition.key == "body_temperature"
    assert reading.definition.unit == "°C"
    assert reading.value == pytest.approx(37.5)
    assert reading.value_min == pytest.approx(37)
    assert reading.sample_count == 2
    assert parsed.metadata["unknown_type_counts"] == {}


def test_thermometer_readings_link_to_vitals_without_merging_wrist_temperature():
    assert TWIN_OF_DEVICE["body_temperature"] == ("body-temperature", "same")
    assert panel_for_concept("body-temperature").id == "vitals"
    assert TWIN_OF_DEVICE["sleeping_wrist_temperature"] == ("body-temperature", "related")
    assert HEALTHKIT_METRICS["HKQuantityTypeIdentifierAppleSleepingWristTemperature"].key != "body_temperature"


def test_reference_extension_is_sourced_bilingual_and_preserves_existing_entries():
    extension = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "extend_device_reference_library.py"))
    existing = {"concept_id": "body-temperature", "bands": [{"label": "Existing clinical band"}], "source_ids": ["clinical-source"]}
    library = {"sources": [], "analytes": [existing]}
    assert extension["extend"](library) == {"sources_added": 10, "analytes_added": 13}
    assert extension["extend"](library) == {"sources_added": 0, "analytes_added": 0}
    assert existing["bands"] == [{"label": "Existing clinical band"}]
    assert existing["source_ids"] == ["clinical-source", "apple-healthkit-body-temperature"]
    sources = {item["id"]: item for item in library["sources"]}
    for entry in library["analytes"][1:]:
        assert entry["kind"] == "no_universal_target"
        assert entry["bands"] == []
        assert entry["short_description"] and entry["why_it_matters"]
        assert entry["uk"]["name"] and entry["uk"]["short_description"] and entry["uk"]["why_it_matters"]
        for source_id in entry["source_ids"]:
            assert sources[source_id]["url"].startswith("https://")
            assert sources[source_id]["official"] is False
            assert sources[source_id]["identifier"]


def test_every_imported_device_metric_has_sourced_reference_content():
    library = json.loads(resource_path("reference_library.json").read_text(encoding="utf-8"))
    analytes = {entry["concept_id"]: entry for entry in library["analytes"]}
    sources = {source["id"] for source in library["sources"]}
    known = {definition.key for definition in HEALTHKIT_METRICS.values()}
    known.update(definition.key for definition in SLEEP_METRICS.values())
    known.update({ECG_HEART_RATE.key, STAND_HOURS.key})
    known.update(definition[0] for definition in FIELDS.values())
    known.update(garmin.DEFS)
    known.update(openwearables.DEFS)
    known.update(oura.DEFS)
    known.update(key for keys in garmin_personal.DATASET_KEYS.values() for key in keys)
    for key in sorted(known):
        reference_key = TWIN_OF_DEVICE[key][0] if key in SAME_DEVICE_KEYS else key
        assert reference_key in analytes, key
        entry = analytes[reference_key]
        assert entry.get("source_ids") and set(entry["source_ids"]) <= sources, key
        assert entry.get("short_description") and entry.get("why_it_matters"), key
        assert entry.get("uk", {}).get("short_description") and entry["uk"].get("why_it_matters"), key
