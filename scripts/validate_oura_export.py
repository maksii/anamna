"""Validate an Oura Takeout without writing any patient data to the database."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from anamna.config import ROOT
from anamna.devices.oura_export import OuraAdapter
from anamna.ingest.intake import detect_archive_adapter, detect_directory_adapter, expand_archive


EXPECTED_METRICS = {
    "dailyactivity.csv": {
        "active_energy", "activity_score", "moderate_activity", "resting_energy", "steps",
        "vigorous_activity",
    },
    "dailycardiovascularage.csv": {"cardiovascular_age", "pulse_wave_velocity"},
    "dailyreadiness.csv": {"readiness_score", "temperature_deviation"},
    "dailysleep.csv": {"sleep_score"},
    "dailyspo2.csv": {"blood_oxygen", "breathing_disturbance_index"},
    "dailystress.csv": {"recovery_high_time", "stress_high_time"},
    "heartrate.csv": {"daily_heart_rate"},
    "importedheartrate.csv": {"daily_heart_rate"},
    "importedstepcount.csv": {"steps"},
    "sleepmodel.csv": {
        "heart_rate_variability", "lowest_sleeping_heart_rate", "respiratory_rate", "sleep_awake",
        "sleep_core", "sleep_deep", "sleep_duration", "sleep_efficiency", "sleep_rem",
        "time_in_bed",
    },
    "vo2max.csv": {"vo2_max"},
}


def _validate(source: Path, detected: tuple[str | None, str]) -> dict[str, object]:
    parsed = OuraAdapter().parse(source)
    metadata = parsed.metadata
    file_rows = metadata.get("file_rows", {})
    keys = {item.definition.key for item in parsed.aggregates}
    errors: list[str] = []
    if detected[0] != "oura":
        errors.append(f"archive detection returned {detected[0]!r}, not 'oura'")
    unsupported = metadata.get("unsupported_populated_files", [])
    if unsupported:
        errors.append(f"unsupported populated App Data tables: {unsupported}")
    unexpected = metadata.get("unexpected_normalized_columns", {})
    if unexpected:
        errors.append(f"new columns in normalized tables: {unexpected}")
    if parsed.raw_record_count != sum(int(value) for value in file_rows.values()):
        errors.append("raw record count does not reconcile with per-file counts")
    for filename, expected in EXPECTED_METRICS.items():
        if int(file_rows.get(filename, 0)):
            missing = sorted(expected - keys)
            if missing:
                errors.append(f"{filename}: missing normalized metric(s) {missing}")
    if int(file_rows.get("workout.csv", 0)) and not parsed.workouts:
        errors.append("workout.csv is populated but produced no workouts")
    if int(file_rows.get("enhancedtag.csv", 0)) and not parsed.events:
        errors.append("enhancedtag.csv is populated but produced no events")

    populated = {name for name, count in file_rows.items() if int(count)}
    accounted = set(metadata.get("normalized_populated_files", [])) | set(
        metadata.get("retained_populated_files", [])
    ) | set(unsupported)
    if populated != accounted:
        errors.append(f"populated-file coverage does not reconcile: {sorted(populated ^ accounted)}")

    return {
        "detected_adapter": detected[0],
        "export_format": metadata.get("export_format"),
        "range": [parsed.export_started_at, parsed.export_ended_at],
        "app_data_files": metadata.get("app_data_files"),
        "app_data_rows": metadata.get("app_data_rows"),
        "daily_metric_rows": len(parsed.aggregates),
        "metric_keys": sorted(keys),
        "workouts": len(parsed.workouts),
        "events": len(parsed.events),
        "normalized_populated_files": metadata.get("normalized_populated_files", []),
        "retained_populated_files": metadata.get("retained_populated_files", []),
        "unsupported_populated_files": unsupported,
        "unexpected_normalized_columns": unexpected,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oura", type=Path, required=True, help="Oura data.zip or its extracted directory")
    parser.add_argument(
        "--json-output", type=Path, default=ROOT / "work" / "oura-export-validation.json",
    )
    args = parser.parse_args()
    supplied = args.oura.resolve()

    if supplied.is_file():
        detected = detect_archive_adapter(supplied)
        with tempfile.TemporaryDirectory(prefix="anamna-oura-") as temp:
            root = Path(temp)
            expand_archive(supplied, root)
            payload = _validate(root / detected[1] if detected[1] else root, detected)
    else:
        detected = detect_directory_adapter(supplied)
        payload = _validate(supplied / detected[1] if detected[1] else supplied, detected)

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
