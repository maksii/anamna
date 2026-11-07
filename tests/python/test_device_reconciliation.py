from __future__ import annotations

import copy
import itertools
import json

import pytest
from fastapi.testclient import TestClient

from anamna.db import connect, migrate, utc_now
from anamna.devices.queries import area_tracker, device_history_summary, device_metric_catalog, device_metric_comparison, device_metric_values
from anamna.devices.reconcile import select_daily, select_metrics, source_key
from anamna.security import create_user
from anamna.web.app import create_app
from test_web_security import PASSWORD, seed_patient, settings_for
from test_web_profile import login, csrf_for


def reading(source, vendor, key, value, day="2026-08-07", samples=1):
    return {"source_name": source, "source_vendor": vendor, "metric_key": key, "value": value,
            "day": day, "sample_count": samples, "metric_name": key, "category": "device_sleep" if key.startswith("sleep_") or key == "time_in_bed" else "device_activity",
            "aggregation": "sum", "unit": "hours" if key.startswith("sleep_") or key == "time_in_bed" else "steps"}


def test_competing_daily_totals_are_selected_never_added_or_averaged():
    rows = [reading("Apple Watch", "Apple Health", "steps", 1000), reading("Oura", "Oura", "steps", 1400), reading("OpenWearables · apple · Watch", "OpenWearables", "steps", 1000)]
    before = copy.deepcopy(rows)
    for permutation in itertools.permutations(rows):
        selected = select_daily(list(permutation))
        assert [r["value"] for r in selected] == [1000]
    assert rows == before
    assert select_daily(rows, source_key(rows[1]))[0]["value"] == 1400


@pytest.mark.parametrize(("vendor", "name", "label"), [
    ("Oura", "Oura", "Oura"),
    ("OpenWearables", "OpenWearables · apple · Oura · iPhone18,1", "Oura · OpenWearables"),
    ("OpenWearables", "openwearables · apple · Watch", "Watch · OpenWearables"),
    ("Apple Health", "Apple Watch", "Apple Health · Apple Watch"),
])
def test_comparison_labels_do_not_repeat_vendor_prefix_or_change_provenance(ledger, vendor, name, label):
    settings, owner, _ = ledger
    with connect(settings) as db:
        db.execute("UPDATE device_metric_days SET source_vendor=?, source_name=? WHERE metric_key='sleep_rem'", (vendor, name))
        comparison = device_metric_comparison(db, owner, "sleep_rem")
    source = comparison["sources"][0]
    assert source["label"] == label
    assert source["vendor"] == vendor
    assert source["name"] == name
    assert source["rows"][0]["source_vendor"] == vendor
    assert source["rows"][0]["source_name"] == name


def test_sleep_stages_do_not_fill_gaps_from_a_different_device():
    grouped = {
        "sleep_duration": [reading("Oura", "Oura", "sleep_duration", 7), reading("Apple Watch", "Apple Health", "sleep_duration", 8)],
        "sleep_deep": [reading("Oura", "Oura", "sleep_deep", 1), reading("Apple Watch", "Apple Health", "sleep_deep", 2)],
        "sleep_rem": [reading("Apple Watch", "Apple Health", "sleep_rem", 3)],
    }
    selected = select_metrics(grouped, {})
    assert selected["sleep_duration"][0]["value"] == 7
    assert selected["sleep_deep"][0]["value"] == 1
    assert selected["sleep_rem"] == []
    preferred = select_metrics(grouped, {"sleep": source_key(grouped["sleep_duration"][1])})
    assert preferred["sleep_duration"][0]["value"] == 8
    assert preferred["sleep_deep"][0]["value"] == 2
    assert preferred["sleep_rem"][0]["value"] == 3


def test_named_bridge_retains_physical_provider_priority_and_direct_copy_wins():
    rows = [reading("Apple Watch", "Apple Health", "sleep_duration", 8), reading("OpenWearables · oura · Oura Ring", "OpenWearables", "sleep_duration", 7)]
    assert select_metrics({"sleep_duration": rows}, {})["sleep_duration"][0]["value"] == 7
    rows.append(reading("Oura", "Oura", "sleep_duration", 7.2))
    assert select_metrics({"sleep_duration": rows}, {})["sleep_duration"][0]["value"] == 7.2


def test_preference_falls_back_only_on_days_without_that_source():
    watch = reading("Apple Watch", "Apple Health", "steps", 1000)
    oura = reading("Oura", "Oura", "steps", 1400)
    older = reading("Apple Watch", "Apple Health", "steps", 900, "2026-08-06")
    assert [r["value"] for r in select_daily([watch, oura, older], source_key(oura))] == [1400, 900]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), None, "invalid"])
def test_nonfinite_alternative_cannot_poison_selected_history(bad):
    assert select_daily([reading("Apple Watch", "Apple Health", "steps", bad), reading("Oura", "Oura", "steps", 3)])[0]["value"] == 3


@pytest.fixture
def ledger(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    owner = create_user(settings, "owner@example.com", "owner", PASSWORD)
    patient = seed_patient(settings, owner, "Local fixture")
    rows = [
        reading("Oura", "Oura", "sleep_duration", 7), reading("Apple Watch", "Apple Health", "sleep_duration", 8),
        reading("Oura", "Oura", "sleep_deep", 1), reading("Apple Watch", "Apple Health", "sleep_deep", 2),
        reading("Apple Watch", "Apple Health", "sleep_rem", 3), reading("Apple Watch", "Apple Health", "sleep_duration", 6, "2026-08-06"),
    ]
    with connect(settings) as db:
        db.execute("INSERT INTO vendors(id,canonical_name,created_at) VALUES ('fixture','Fixture',?)", (utc_now(),))
        db.execute("""INSERT INTO device_imports(id,owner_user_id,patient_id,vendor_id,adapter_key,source_path,source_fingerprint,source_bytes,imported_at)
                      VALUES ('fixture',?,?,'fixture','apple_health','fixture','fixture',1,?)""", (owner, patient, utc_now()))
        for index, row in enumerate(rows):
            db.execute("""INSERT INTO device_metric_days(id,owner_user_id,patient_id,import_id,source_name,source_vendor,metric_key,metric_name,category,day,aggregation,unit,value,sample_count,created_at)
                          VALUES (?,?,?,'fixture',?,?,?,?,?,?,?,?,?,?,?)""",
                       (str(index), owner, patient, row['source_name'], row['source_vendor'], row['metric_key'], row['metric_name'], row['category'], row['day'], row['aggregation'], row['unit'], row['value'], row['sample_count'], utc_now()))
    return settings, owner, rows


def test_all_aggregate_views_use_same_sleep_source_and_retain_alternatives(ledger):
    settings, owner, rows = ledger
    with connect(settings) as db:
        before = [tuple(row) for row in db.execute("SELECT * FROM device_metric_days ORDER BY id")]
        selected = device_metric_values(db, owner, "sleep_duration")
        assert selected[0]["value"] == 7
        assert device_metric_values(db, owner, "sleep_rem") == []
        comparison = device_metric_comparison(db, owner, "sleep_rem")
        assert comparison["stored_row_count"] == 1 and comparison["has_selected_values"] is False
        cards = {c['id']: c for c in device_metric_catalog(db, owner)}
        assert cards['device:sleep_duration']['latest_numeric'] == 7
        assert 'device:sleep_rem' not in cards
        history = {c['metric_key']: c for c in device_history_summary(db, owner)}
        assert history['sleep_duration']['latest_value'] == 7
        night = area_tracker(db, owner, 'sleep')['sleep']['nights'][-1]
        assert night['asleep'] == 7 and night['source'] == 'Oura' and night['source_count'] == 2
        assert night['alternates'][0]['asleep'] == 8
        assert next(s for s in night['stages'] if s['key'] == 'sleep_rem')['value'] is None
        assert before == [tuple(row) for row in db.execute("SELECT * FROM device_metric_days ORDER BY id")]


def test_owner_preference_persists_and_clears_without_changing_evidence(ledger):
    settings, owner, rows = ledger
    with TestClient(create_app(settings)) as client:
        login(client, 'owner@example.com')
        csrf = csrf_for(settings, client)
        response = client.post('/devices/source-preference', data={"metric_key":"sleep_duration","source_key":source_key(rows[1]),"csrf_token":csrf}, follow_redirects=False)
        assert response.status_code == 303
        with connect(settings) as db:
            assert device_metric_values(db, owner, 'sleep_duration')[0]['value'] == 8
            assert device_metric_values(db, owner, 'sleep_rem')[0]['value'] == 3
            assert db.execute('SELECT COUNT(*) FROM device_metric_days').fetchone()[0] == len(rows)
        assert client.get('/devices/metrics/sleep_rem').status_code == 200
        assert client.post('/devices/source-preference',data={"metric_key":"sleep_duration","source_key":"","csrf_token":csrf}).status_code == 200
        assert client.get('/devices/metrics/sleep_rem').status_code == 200
    with connect(settings) as db:
        assert not db.execute('SELECT * FROM device_source_preferences').fetchall()
        assert device_metric_values(db, owner, 'sleep_duration')[0]['value'] == 7
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='device_source_preference_changed'").fetchone()[0] == 2


def test_source_preference_rejects_csrf_invalid_source_and_other_owners(ledger):
    settings, owner, rows = ledger
    create_user(settings, 'partner@example.com', 'Olena', PASSWORD)
    with TestClient(create_app(settings)) as client:
        login(client, 'owner@example.com')
        assert client.post('/devices/source-preference',data={"metric_key":"sleep_duration","source_key":source_key(rows[1])}).status_code == 403
        assert client.post('/devices/source-preference',data={"metric_key":"sleep_duration","source_key":"unknown","csrf_token":csrf_for(settings,client)}).status_code == 400
        login(client, 'partner@example.com')
        assert client.post('/devices/source-preference',data={"metric_key":"sleep_duration","source_key":source_key(rows[1]),"csrf_token":csrf_for(settings,client)}).status_code == 400
    with connect(settings) as db:
        assert not db.execute('SELECT * FROM device_source_preferences').fetchall()
