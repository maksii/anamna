"""Regression evidence for provider reconciliation and quantity correctness."""
from __future__ import annotations

import pytest

from anamna import integrations, openwearables, oura, paperless
from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.devices import importer as device_importer
from anamna.devices.apple_health import AppleHealthAdapter
from anamna.devices.catalog import metric
from anamna.devices.models import Aggregate
from anamna.security import create_user


@pytest.fixture
def ledger(tmp_path):
    settings = Settings(database_path=tmp_path / "ledger.sqlite3", source_dir=tmp_path / "sources", secret_key="provider-review-fixture")
    migrate(settings)
    user = create_user(settings, "owner@example.com", "owner", "provider-review-password")
    with connect(settings) as db:
        db.execute("INSERT INTO patients(id, owner_user_id, display_name, created_at) VALUES ('patient', ?, 'Patient', ?)", (user, utc_now()))
    return settings, user


def apple_export(tmp_path, rows):
    path = tmp_path / "export.xml"
    path.write_text("<HealthData>\n" + "\n".join(rows) + "\n</HealthData>", encoding="utf-8")
    return path


def quantity(kind, value, unit):
    return f'<Record type="HKQuantityTypeIdentifier{kind}" sourceName="Watch" unit="{unit}" startDate="2026-08-01 10:00:00 +0300" endDate="2026-08-01 10:00:00 +0300" value="{value}"/>'


@pytest.mark.parametrize("kind,value,unit,key,expected", [
    ("BodyMass", 220, "lb", "body_weight", 99.7903214),
    ("Height", 1.8, "m", "body_height", 180),
    ("WalkingStepLength", 30, "in", "walking_step_length", 76.2),
    ("DistanceWalkingRunning", 1, "mi", "walking_running_distance", 1.609344),
    ("DistanceSwimming", 100, "yd", "swimming_distance", 91.44),
    ("WalkingSpeed", 1, "m/s", "walking_speed", 3.6),
    ("ActiveEnergyBurned", 418.4, "kJ", "active_energy", 100),
    ("AppleExerciseTime", 120, "s", "exercise_minutes", 2),
    ("HeartRateVariabilitySDNN", 0.05, "s", "heart_rate_variability", 50),
    ("AppleSleepingWristTemperature", 98.6, "degF", "sleeping_wrist_temperature", 37),
    ("BodyMassIndex", 24, "count", "body_mass_index", 24),
    ("WalkingSpeed", 4, "km/hr", "walking_speed", 4),
])
def test_apple_quantities_convert_exported_units(tmp_path, kind, value, unit, key, expected):
    parsed = AppleHealthAdapter().parse(apple_export(tmp_path, [quantity(kind, value, unit)]))
    item, = parsed.aggregates
    assert item.definition.key == key
    assert item.value == pytest.approx(expected)


def test_apple_workout_converts_duration_energy_and_distance(tmp_path):
    path = apple_export(tmp_path, ['<Workout workoutActivityType="HKWorkoutActivityTypeWalking" sourceName="Watch" startDate="2026-08-01 10:00:00 +0300" duration="1800" durationUnit="s" totalEnergyBurned="418.4" totalEnergyBurnedUnit="kJ" totalDistance="1" totalDistanceUnit="mi"/>'])
    workout, = AppleHealthAdapter().parse(path).workouts
    assert workout.duration_minutes == 30
    assert workout.energy_kcal == pytest.approx(100)
    assert workout.distance_km == pytest.approx(1.609344)


def test_apple_refuses_incompatible_units(tmp_path):
    with pytest.raises(ValueError, match="unit"):
        AppleHealthAdapter().parse(apple_export(tmp_path, [quantity("BodyMass", 80, "furlongs")]))


def test_apple_deduplication_includes_unit(tmp_path):
    parsed = AppleHealthAdapter().parse(apple_export(tmp_path, [quantity("DistanceWalkingRunning", 1, "km"), quantity("DistanceWalkingRunning", 1, "mi")]))
    assert parsed.aggregates[0].sample_count == 2
    assert parsed.aggregates[0].value == pytest.approx(2.609344)


def test_device_import_rejects_foreign_patient(ledger, tmp_path):
    settings, user = ledger
    other = create_user(settings, "partner@example.com", "Olena", "provider-review-password")
    with connect(settings) as db:
        db.execute("INSERT INTO patients(id, owner_user_id, display_name, created_at) VALUES ('other-patient', ?, 'Other', ?)", (other, utc_now()))
    with pytest.raises(ValueError, match="patient"):
        device_importer.import_device_export(settings, owner_user_id=user, patient_id="other-patient", vendor_key="apple_health", source=apple_export(tmp_path, [quantity("BodyMass", 80, "kg")]))
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_imports").fetchone()[0] == 0


def test_same_timestamp_reimport_removes_retired_rows(ledger, tmp_path, monkeypatch):
    settings, user = ledger
    path = apple_export(tmp_path, [quantity("BodyMass", 80, "kg")])
    monkeypatch.setattr(device_importer, "utc_now", lambda: "2026-08-01T10:00:00+00:00")
    first = device_importer.import_device_export(settings, owner_user_id=user, patient_id="patient", vendor_key="apple_health", source=path)
    original = AppleHealthAdapter.parse
    def without_metrics(self, source, tz=None):
        parsed = original(self, source, tz)
        parsed.aggregates = []
        return parsed
    monkeypatch.setattr(AppleHealthAdapter, "parse", without_metrics)
    device_importer.import_device_export(settings, owner_user_id=user, patient_id="patient", vendor_key="apple_health", source=path)
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_metric_days WHERE import_id=?", (first["import_id"],)).fetchone()[0] == 0


def test_repair_reimport_preserves_other_imports_exactly(ledger, tmp_path):
    settings, user = ledger
    workout = '<Workout workoutActivityType="HKWorkoutActivityTypeWalking" sourceName="Watch" startDate="2026-08-01 10:00:00 +0300" duration="30" durationUnit="min"/>'
    event = '<Record type="HKCategoryTypeIdentifierHighHeartRateEvent" sourceName="Watch" startDate="2026-08-01 10:00:00 +0300" value="first"/>'
    first = apple_export(tmp_path, [quantity("BodyMass", 80, "kg"), workout, event])
    device_importer.import_device_export(settings, owner_user_id=user, patient_id="patient", vendor_key="apple_health", source=first)
    second_dir = tmp_path / "newer"
    second_dir.mkdir()
    second = apple_export(second_dir, [quantity("BodyMass", 81, "kg"), workout.replace('duration="30"', 'duration="40"'), event.replace('value="first"', 'value="second"')])
    device_importer.import_device_export(settings, owner_user_id=user, patient_id="patient", vendor_key="apple_health", source=second)
    with connect(settings) as db:
        before = {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table}")] for table in ("device_metric_days", "device_workouts", "device_events")}
    device_importer.import_device_export(settings, owner_user_id=user, patient_id="patient", vendor_key="apple_health", source=first, preserve_other_imports=True)
    with connect(settings) as db:
        for table, rows in before.items():
            assert [tuple(row) for row in db.execute(f"SELECT * FROM {table}")] == rows


def test_reimport_keeps_surviving_legacy_row_ids(ledger, tmp_path):
    settings, user = ledger
    path = apple_export(tmp_path, [quantity("BodyMass", 80, "kg")])
    device_importer.import_device_export(settings, owner_user_id=user, patient_id="patient", vendor_key="apple_health", source=path)
    with connect(settings) as db:
        db.execute("UPDATE device_metric_days SET id='legacy-row-id'")
    device_importer.import_device_export(settings, owner_user_id=user, patient_id="patient", vendor_key="apple_health", source=path, preserve_other_imports=True)
    with connect(settings) as db:
        assert db.execute("SELECT id FROM device_metric_days").fetchone()[0] == "legacy-row-id"


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": {}}, {"data": [None]}])
def test_oura_rejects_malformed_pages(payload, monkeypatch):
    monkeypatch.setattr(oura, "api_get", lambda *a, **kw: payload)
    with pytest.raises(integrations.IntegrationError):
        oura._paged(None, "user", "/test", {})


def test_oura_rejects_repeated_cursor(monkeypatch):
    calls = []
    def repeating(*args, **kwargs):
        calls.append(1)
        assert len(calls) <= 2, "pagination must stop on the repeated cursor"
        return {"data": [], "next_token": "repeat"}
    monkeypatch.setattr(oura, "api_get", repeating)
    with pytest.raises(integrations.IntegrationError):
        oura._paged(None, "user", "/test", {})


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": {}}, {"data": [None]}, {"data": [], "pagination": {"has_more": True}}])
def test_openwearables_rejects_incomplete_pages(payload, monkeypatch):
    monkeypatch.setattr(openwearables, "_api", lambda *a, **kw: payload)
    with pytest.raises(openwearables.OpenWearablesError):
        openwearables._cursor_pages(None, "/test", {}, 10)


@pytest.mark.parametrize("module,parser", [(oura, "_num"), (openwearables, "_num")])
@pytest.mark.parametrize("value", [float("inf"), "NaN", True])
def test_provider_rejects_non_measurements(module, parser, value):
    assert getattr(module, parser)(value) is None


def test_oura_deleted_workouts_and_tags_are_reconciled(ledger, monkeypatch):
    settings, user = ledger
    from test_oura import connect_account
    connect_account(settings, user)
    payloads = {"workout": [{"start_datetime": "2026-08-01T10:00:00Z", "activity": "walk"}], "session": [], "enhanced_tag": [{"start_day": "2026-08-01", "custom_name": "symptom"}]}
    monkeypatch.setattr(oura, "_paged", lambda s, u, path, params: payloads[path.rsplit("/", 1)[-1]])
    oura.sync_workouts(settings, user, "2026-08-01", "2026-08-01")
    payloads.update(workout=[], enhanced_tag=[])
    oura.sync_workouts(settings, user, "2026-08-01", "2026-08-01")
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_workouts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM device_events").fetchone()[0] == 0


def test_openwearables_deleted_workouts_and_cycles_are_reconciled(ledger, monkeypatch):
    settings, user = ledger
    openwearables.link_account(settings, user, "remote", "owner@example.com")
    rows = [{"start_time": "2026-08-01T10:00:00Z", "type": "walk"}]
    monkeypatch.setattr(openwearables, "_exhaustive_rows", lambda *a, **kw: rows)
    openwearables.sync_workouts(settings, user, "2026-08-01", "2026-08-01")
    openwearables.sync_cycles(settings, user, "2026-08-01", "2026-08-01")
    rows.clear()
    openwearables.sync_workouts(settings, user, "2026-08-01", "2026-08-01")
    openwearables.sync_cycles(settings, user, "2026-08-01", "2026-08-01")
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_workouts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM device_events").fetchone()[0] == 0


def test_latest_measurement_compares_instants_across_offsets():
    item = Aggregate(metric("body_weight", "Weight", "device_body", "kg", "latest"), "2026-08-01", "Scale", "Scale")
    item.add(80, "2026-08-01T10:00:00+03:00")
    item.add(81, "2026-08-01T09:00:00Z")
    assert item.value == 81


def test_sleep_stages_do_not_double_count_an_overlapping_unspecified_period(tmp_path):
    def sleep(kind, start, end):
        return f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" startDate="2026-08-01 {start} +0300" endDate="2026-08-01 {end} +0300" value="HKCategoryValueSleepAnalysis{kind}"/>'
    path = apple_export(tmp_path, [sleep("AsleepUnspecified", "00:00:00", "08:00:00"), sleep("AsleepCore", "00:00:00", "06:00:00"), sleep("AsleepDeep", "06:00:00", "08:00:00")])
    rows = {item.definition.key: item.value for item in AppleHealthAdapter().parse(path).aggregates}
    assert rows == {"sleep_duration": 8, "sleep_core": 6, "sleep_deep": 2}


def test_oauth_callback_cannot_consume_another_users_state(ledger):
    settings, user = ledger
    with connect(settings) as db:
        db.execute("INSERT INTO oauth_states(state, user_id, provider, code_verifier, created_at) VALUES ('owned-state', ?, 'oura', '', ?)", (user, utc_now()))
    with pytest.raises(integrations.StaleStateError):
        integrations.complete_oauth(settings, "another-user", integrations.PROVIDERS["oura"], code="code", state="owned-state", redirect="https://ledger.test/callback")
    with connect(settings) as db:
        assert db.execute("SELECT state FROM oauth_states").fetchone() is not None


def test_paperless_async_refusals_exhaust_retry_budget(tmp_path, monkeypatch):
    from test_paperless import build, configure_paperless, connect_user
    settings, user, _ = build(tmp_path)
    configure_paperless(settings)
    connect_user(settings, user)
    sent = []
    def upload(*a, **kw):
        sent.append(1)
        return "task"
    monkeypatch.setattr(paperless, "upload_file", upload)
    monkeypatch.setattr(paperless, "task_state", lambda *a: {"status": "failure", "document_id": None})
    for _ in range(paperless.MAX_UPLOAD_ATTEMPTS + 2):
        paperless.push_document(settings, "doc-1")
        paperless.resolve_pending(settings, "doc-1")
    assert len(sent) == paperless.MAX_UPLOAD_ATTEMPTS
    assert paperless.link_counts(settings, user)["refused"] == 1


def test_paperless_server_change_forgets_server_local_document_ids(tmp_path):
    from test_paperless import build, configure_paperless, connect_user
    settings, user, _ = build(tmp_path)
    configure_paperless(settings)
    connect_user(settings, user)
    with connect(settings) as db:
        db.execute("UPDATE documents SET paperless_id=7, paperless_task_id='old-task' WHERE id='doc-1'")
    paperless.forget_all_consent(settings)
    with connect(settings) as db:
        row = db.execute("SELECT paperless_id, paperless_task_id FROM documents WHERE id='doc-1'").fetchone()
        assert tuple(row) == (None, None)


@pytest.mark.parametrize("datatype", ["activity", "workouts", "cycles"])
def test_openwearables_discards_fetch_from_replaced_account(ledger, monkeypatch, datatype):
    settings, user = ledger
    openwearables.link_account(settings, user, "old-remote", "old@example.test")
    def switched(*a, **kw):
        openwearables.link_account(settings, user, "new-remote", "new@example.test")
        return [{"date": "2026-08-01", "steps": 9000, "start_time": "2026-08-01T10:00:00Z", "type": "walk"}]
    monkeypatch.setattr(openwearables, "_fetch", switched)
    monkeypatch.setattr(openwearables, "_exhaustive_rows", switched)
    with pytest.raises(openwearables.OpenWearablesError):
        if datatype == "activity":
            openwearables.sync_datatype(settings, user, datatype, "2026-08-01", "2026-08-01")
        else:
            getattr(openwearables, "sync_" + datatype)(settings, user, "2026-08-01", "2026-08-01")
    with connect(settings) as db:
        for table in ("device_metric_days", "device_workouts", "device_events"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_openwearables_relink_on_new_server_clears_previous_server_data(ledger, monkeypatch):
    settings, user = ledger
    openwearables.save_settings(settings, {"openwearables_url": "https://old.example.test"})
    openwearables.link_account(settings, user, "remote", "old@example.test")
    monkeypatch.setattr(openwearables, "_fetch", lambda *a: [{"date": "2026-08-01", "steps": 9000}])
    openwearables.sync_datatype(settings, user, "activity", "2026-08-01", "2026-08-01")
    openwearables.save_settings(settings, {"openwearables_url": "https://new.example.test"})
    assert openwearables.link_account(settings, user, "remote", "new@example.test") is True
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_metric_days").fetchone()[0] == 0


def test_paperless_claim_precedes_preflight_reads(tmp_path, monkeypatch):
    from test_paperless import build
    settings, user, _ = build(tmp_path)
    sent, nested = [], []
    def ready(*a):
        if not nested:
            nested.append(True)
            paperless.push_document(settings, "doc-1")
        return ("https://paperless.test", "token")
    monkeypatch.setattr(paperless, "upload_ready", ready)
    monkeypatch.setattr(paperless, "connection_for", ready)
    monkeypatch.setattr(paperless, "upload_file", lambda *a, **kw: sent.append("task") or "task")
    paperless.push_document(settings, "doc-1")
    assert sent == ["task"]


def test_paperless_does_not_store_old_task_after_server_change(tmp_path, monkeypatch):
    from test_paperless import build, configure_paperless, connect_user
    settings, user, _ = build(tmp_path)
    configure_paperless(settings)
    connect_user(settings, user)
    def upload(*a, **kw):
        paperless.forget_all_consent(settings)
        return "old-task"
    monkeypatch.setattr(paperless, "upload_file", upload)
    assert paperless.push_document(settings, "doc-1") is False
    with connect(settings) as db:
        assert db.execute("SELECT paperless_task_id FROM documents WHERE id='doc-1'").fetchone()[0] is None


def test_oura_remote_account_switch_clears_only_its_api_history(ledger, tmp_path, monkeypatch):
    from test_oura import connect_account
    settings, user = ledger
    connect_account(settings, user)
    device_importer.import_device_export(settings, owner_user_id=user, patient_id="patient", vendor_key="apple_health", source=apple_export(tmp_path, [quantity("BodyMass", 80, "kg")]))
    monkeypatch.setattr(oura, "_paged", lambda *a: [{"day": "2026-08-01", "score": 80}])
    oura.sync_range(settings, user, "daily_sleep", "2026-08-01", "2026-08-01")
    for remote in ("", "another-remote"):
        integrations.save_connection(settings, user, "oura", access_token="new", refresh_token="new", expires_at=None, external_user_id=remote, scopes="daily")
    with connect(settings) as db:
        assert [row[0] for row in db.execute("SELECT metric_key FROM device_metric_days")] == ["body_weight"]


def test_oura_fetch_cannot_repopulate_a_replaced_accounts_history(ledger, monkeypatch):
    from test_oura import connect_account
    settings, user = ledger
    connect_account(settings, user)
    def switched(*a):
        integrations.save_connection(settings, user, "oura", access_token="new", refresh_token="new", expires_at=None, external_user_id="another-remote", scopes="daily")
        return [{"day": "2026-08-01", "score": 80}]
    monkeypatch.setattr(oura, "_paged", switched)
    with pytest.raises(integrations.IntegrationError):
        oura.sync_range(settings, user, "daily_sleep", "2026-08-01", "2026-08-01")
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_metric_days").fetchone()[0] == 0


def test_delayed_oura_refresh_cannot_recreate_disconnected_account(ledger, monkeypatch):
    from test_oura import connect_account
    settings, user = ledger
    connect_account(settings, user, expires_in_seconds=-1)
    def refreshed(*a, **kw):
        with connect(settings) as db:
            db.execute("DELETE FROM provider_connections WHERE user_id=?", (user,))
        return {"access_token": "rotated", "refresh_token": "rotated", "expires_in": 3600}
    monkeypatch.setattr(integrations, "_request", refreshed)
    with pytest.raises(integrations.IntegrationError):
        oura._refresh(settings, user)
    assert integrations.connection_row(settings, user, "oura") is None
