"""Uploading the next export must not duplicate the last one.

A vendor export is cumulative.  Apple Health's February archive contains every
day January's did, so the interesting case is not the same file twice -- the
fingerprint already caught that -- but the *superset*, which is what a person
who exports monthly actually uploads.  Before
`migrations/012_device_rows_are_owner_scoped.sql` every overlapping day,
workout and ECG arrived a second time, and the record grew with the square of
how diligently it was kept.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.devices.importer import import_device_export
from anamna.devices.queries import device_overview
from anamna.ingest import intake
from anamna.security import create_user


JANUARY = """ <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Owner Watch" unit="count" startDate="2026-01-02 10:00:00 +0200" endDate="2026-01-02 10:01:00 +0200" value="1200"/>
 <Record type="HKQuantityTypeIdentifierRestingHeartRate" sourceName="Owner Watch" unit="count/min" startDate="2026-01-02 06:00:00 +0200" endDate="2026-01-02 06:00:00 +0200" value="54"/>
 <Record type="HKCategoryTypeIdentifierIrregularHeartRhythmEvent" sourceName="Owner Watch" startDate="2026-01-02 08:00:00 +0200" endDate="2026-01-02 08:00:00 +0200" value="1"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeWalking" sourceName="Owner Watch" startDate="2026-01-02 12:00:00 +0200" endDate="2026-01-02 12:30:00 +0200" duration="30" durationUnit="min"/>
"""
FEBRUARY_EXTRA = """ <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Owner Watch" unit="count" startDate="2026-02-03 10:00:00 +0200" endDate="2026-02-03 10:01:00 +0200" value="3400"/>
"""
#: The same January day, re-exported after the watch finished syncing it.
JANUARY_CORRECTED = JANUARY.replace('value="1200"', 'value="1850"')

HEADER = (
    '<?xml version="1.0"?>\n<HealthData>\n'
    ' <Me HKCharacteristicTypeIdentifierDateOfBirth="1990-03-14"'
    ' HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexMale"/>\n'
)


def export_at(root: Path, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "export.xml").write_text(HEADER + body + "</HealthData>\n", encoding="utf-8")
    return root


@pytest.fixture
def record(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "health.sqlite3",
        source_dir=tmp_path / "sources",
        secret_key="device-reimport-secret",
    )
    settings.source_dir.mkdir(parents=True, exist_ok=True)
    migrate(settings)
    user_id = create_user(settings, "devices@example.test", "Devices", "a-long-local-password")
    patient_id = f"patient-{user_id}"
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Test Patient', '1990-03-14', 'male', ?)""",
            (patient_id, user_id, utc_now()),
        )
        connection.commit()

    def importer(body: str, name: str) -> dict[str, object]:
        return import_device_export(
            settings,
            owner_user_id=user_id,
            patient_id=patient_id,
            vendor_key="apple_health",
            source=export_at(tmp_path / name, body),
        )

    return settings, user_id, importer


def counts(settings: Settings, user_id: str) -> dict[str, int]:
    with connect(settings) as connection:
        return dict(
            connection.execute(
                """SELECT
                     (SELECT COUNT(*) FROM device_metric_days WHERE owner_user_id=?) days,
                     (SELECT COUNT(*) FROM device_workouts WHERE owner_user_id=?) workouts,
                     (SELECT COUNT(*) FROM device_events WHERE owner_user_id=?) events,
                     (SELECT COUNT(*) FROM device_imports WHERE owner_user_id=?) imports""",
                (user_id,) * 4,
            ).fetchone()
        )


def test_the_same_export_twice_changes_nothing(record):
    settings, user_id, importer = record
    first = importer(JANUARY, "january")
    before = counts(settings, user_id)
    second = importer(JANUARY, "january-again")

    assert second["import_id"] == first["import_id"]
    assert counts(settings, user_id) == before


def test_next_months_export_adds_only_what_is_new(record):
    settings, user_id, importer = record
    importer(JANUARY, "january")
    importer(JANUARY + FEBRUARY_EXTRA, "february")

    after = counts(settings, user_id)
    # Two days of steps, one resting heart rate; one walk; one rhythm notice.
    assert after["days"] == 3
    assert after["workouts"] == 1
    assert after["events"] == 1
    # Both export files are still recorded: they are provenance, not duplicates.
    assert after["imports"] == 2


def test_a_day_re_exported_takes_the_newer_reading(record):
    settings, user_id, importer = record
    importer(JANUARY, "january")
    importer(JANUARY_CORRECTED + FEBRUARY_EXTRA, "february")

    with connect(settings) as connection:
        rows = connection.execute(
            """SELECT value FROM device_metric_days
               WHERE owner_user_id=? AND metric_key='steps' AND day='2026-01-02'""",
            (user_id,),
        ).fetchall()
    assert [row["value"] for row in rows] == [1850]


def test_the_devices_page_counts_each_measurement_once(record):
    settings, user_id, importer = record
    importer(JANUARY, "january")
    importer(JANUARY + FEBRUARY_EXTRA, "february")

    with connect(settings) as connection:
        overview = device_overview(connection, user_id)
    assert overview["counts"]["daily_rows"] == 3
    assert overview["counts"]["workouts"] == 1
    assert overview["counts"]["events"] == 1
    assert len(overview["workouts"]) == 1
    assert len(overview["events"]) == 1
    steps = next(card for card in overview["core_metrics"] if card["id"] == "device:steps")
    assert steps["evidence_count"] == 2  # one sample on each of the two days

    # The summary names the export a person uploaded last, not the first one.
    apple = next(item for item in overview["vendors"] if item["key"] == "apple_health")
    assert apple["latest_date"] == "2026-02-03"


def test_a_row_the_adapter_no_longer_produces_is_removed(record):
    """Re-reading one export with changed logic must not leave the old rows.

    A metric key the catalogue has dropped or renamed stands in for "the
    adapter used to write this and no longer does": it still carries this
    import's id, but this pass did not rewrite it.
    """
    settings, user_id, importer = record
    first = importer(JANUARY, "january")
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO device_metric_days(
                   id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                   metric_key, metric_name, category, day, aggregation, unit, value,
                   sample_count, created_at
               ) SELECT 'retired-row', owner_user_id, patient_id, import_id, source_name,
                        source_vendor, 'retired_metric', 'Retired metric', category, day,
                        aggregation, unit, value, sample_count, '2020-01-01T00:00:00+00:00'
                  FROM device_metric_days WHERE import_id=? LIMIT 1""",
            (first["import_id"],),
        )
        connection.commit()

    importer(JANUARY, "january")  # same bytes, same import id, current mapping
    with connect(settings) as connection:
        keys = sorted(
            str(row["metric_key"])
            for row in connection.execute(
                "SELECT metric_key FROM device_metric_days WHERE owner_user_id=?", (user_id,)
            )
        )
    assert keys == ["resting_heart_rate", "steps"]


# --- the whole way in, through the upload form ------------------------------


def test_uploading_next_months_archive_does_not_duplicate_the_record(tmp_path: Path, monkeypatch):
    """The scenario a person actually performs, end to end.

    Export from Apple Health, upload the zip, export again next month, upload
    that one too.  The second archive repeats every day the first one held,
    which is what a cumulative export is; what must not happen is a second copy
    of each of those days appearing beside the first.

    This drives the real `/upload` endpoint, so it covers the parts the unit
    tests above skip: the archive being recognised as an Apple Health export
    from its own layout, expanded into its own directory, and handed to the
    adapter as a separate queued job.
    """
    from fastapi.testclient import TestClient

    from anamna.security import create_session
    from anamna.web import app as web
    from anamna.web.app import create_app

    monkeypatch.setattr(intake, "start_worker", lambda settings: None)
    settings = Settings(
        database_path=tmp_path / "health.sqlite3",
        source_dir=tmp_path / "sources",
        secret_key="upload-reimport-secret",
    )
    settings.source_dir.mkdir(parents=True, exist_ok=True)
    migrate(settings)
    user_id = create_user(settings, "upload@example.test", "Upload", "a-long-local-password")
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Test Patient', '1990-03-14', 'male', ?)""",
            (f"patient-{user_id}", user_id, utc_now()),
        )
        connection.commit()
    token, csrf = create_session(settings, user_id)
    client = TestClient(create_app(settings))
    client.cookies.set("anamna_session", token)

    def archive_of(body: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            # Apple zips the export one directory down, which is the layout
            # detection has to see through.
            bundle.writestr("apple_health_export/export.xml", HEADER + body + "</HealthData>\n")
        return buffer.getvalue()

    def upload(body: str, name: str) -> None:
        response = client.post(
            "/upload",
            files={"files": (name, archive_of(body), "application/zip")},
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert response.status_code == 303, response.status_code
        intake.drain_now(settings)

    upload(JANUARY, "export-january.zip")
    after_first = counts(settings, user_id)
    upload(JANUARY + FEBRUARY_EXTRA, "export-february.zip")
    after_second = counts(settings, user_id)

    assert after_first == {"days": 2, "workouts": 1, "events": 1, "imports": 1}
    # One new day, and nothing else moved. Before the natural key was
    # owner-scoped this read days=5, workouts=2, events=2.
    assert after_second == {"days": 3, "workouts": 1, "events": 1, "imports": 2}

    with connect(settings) as connection:
        states = [
            (str(row["kind"]), str(row["state"]), str(row["detail_key"]))
            for row in connection.execute(
                "SELECT kind, state, detail_key FROM upload_jobs ORDER BY created_at, rowid"
            )
        ]
    # Both archives were recognised as device exports rather than treated as
    # bundles of documents, and both ran to completion.
    assert [item[0] for item in states] == ["archive", "device_export", "archive", "device_export"]
    assert {item[1] for item in states} == {"done"}
