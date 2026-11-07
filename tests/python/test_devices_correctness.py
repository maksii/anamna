"""Device data correctness (audit batch F8, 2026-11-06).

Each test names the finding it guards: OPS-01 implausible values, OPS-02
bridge vs direct, OPS-03 local day, OPS-06 partial sources, OPS-07 partial
today, OPS-09 never-filled metrics, OPS-12 provenance, OPS-24 staleness,
PERF-02 memo, PERF-03 page weight.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from anamna import openwearables as ow
from anamna import openwearables_webhooks as hooks
from anamna.db import connect, migrate, utc_now
from anamna.devices.apple_health import AppleHealthAdapter
from anamna.devices.queries import device_metric_catalog, device_metric_values, device_overview, is_partial_day
from anamna.devices.reaggregate import compare, reaggregate_openwearables
from anamna.devices.reconcile import human_source_label, select_daily, select_metrics, source_key, valid_row
from anamna.devices.timezone import local_bounds_utc, local_day, today
from anamna.devices.units import plausible_value
from anamna.security import create_user
from anamna.web import app as web_app
from anamna.web.app import create_app
from test_openwearables_webhooks import linked_record  # noqa: F401 - fixture
from test_web_profile import login
from test_web_security import PASSWORD, seed_patient, settings_for

KYIV = ZoneInfo("Europe/Kyiv")


def reading(source, vendor, key, value, day="2026-08-07", aggregation="sum", unit="steps"):
    return {"source_name": source, "source_vendor": vendor, "metric_key": key, "value": value, "day": day,
            "sample_count": 1, "metric_name": key, "category": "device_activity", "aggregation": aggregation, "unit": unit}


# --- OPS-02: a bridge copy never outranks the direct copy of its own origin --

def test_direct_export_outranks_its_own_bridge_copy():
    direct = reading("Owner", "Apple Health", "walking_speed", 4.4, aggregation="average", unit="km/h")
    bridge = reading("OpenWearables · apple · Owner · iPhone14,2", "OpenWearables", "walking_speed", 4.5,
                     aggregation="average", unit="km/h")
    assert select_daily([bridge, direct])[0]["source_name"] == "Owner"
    assert select_daily([direct, bridge])[0]["source_name"] == "Owner"
    # Where the direct export does not reach, the bridge still fills the day.
    assert select_daily([dict(bridge, day="2026-08-08")])[0]["source_name"] == bridge["source_name"]


def test_a_bridged_watch_still_outranks_a_direct_phone():
    phone = reading("Owner", "Apple Health", "steps", 9000)
    watch = reading("OpenWearables · apple · Ivan’s Apple Watch · Watch7,5", "OpenWearables", "steps", 8800)
    direct_watch = reading("Ivan’s Apple Watch", "Apple Health", "steps", 8790)
    assert select_daily([phone, watch])[0]["source_name"] == watch["source_name"]
    assert select_daily([phone, watch, direct_watch])[0]["source_name"] == "Ivan’s Apple Watch"


def test_a_bridged_night_never_outranks_the_direct_night_of_its_origin():
    sleep = lambda *args: dict(reading(*args, unit="hours"), category="device_sleep")  # noqa: E731
    rows = [sleep("Owner", "Apple Health", "time_in_bed", 8.11),
            sleep("OpenWearables · apple · Owner · iPhone14,2", "OpenWearables", "time_in_bed", 8.73),
            sleep("OpenWearables · apple · Owner · iPhone14,2", "OpenWearables", "sleep_duration", 8.73)]
    chosen = select_metrics({"time_in_bed": rows[:2], "sleep_duration": rows[2:]}, {})
    assert chosen["time_in_bed"][0]["source_name"] == "Owner"


def test_human_source_labels_name_each_source_once():
    assert human_source_label("OpenWearables", "OpenWearables · apple · Oura · iPhone18,1") == "Oura · OpenWearables"
    assert human_source_label("Oura", "Oura") == "Oura"
    assert human_source_label("Apple Health", "Watch7,5") == "Apple Health · Apple Watch"
    assert human_source_label("Oura import", "apple_watch") == "Oura import · Apple Watch"
    assert human_source_label("OpenWearables", "OpenWearables · internal") == "OpenWearables"


# --- OPS-06: a zero or partly worn source never hides a real day ------------

def test_zero_or_low_coverage_total_never_hides_another_sources_day():
    watch = reading("Ivan’s Apple Watch", "Apple Health", "steps", 0)
    phone = reading("Owner", "Apple Health", "steps", 7133)
    assert select_daily([watch, phone])[0]["value"] == 7133
    # Even an explicit preference yields to a source that covered the day...
    assert select_daily([watch, phone], source_key(watch))[0]["value"] == 7133
    # ...and the totals are chosen between, never summed.
    assert [row["value"] for row in select_daily([dict(watch, value=2000), phone])] == [7133]
    # A comparable reading keeps the device priority.
    assert select_daily([dict(watch, value=6000), phone])[0]["source_name"] == "Ivan’s Apple Watch"
    # Alone, even a zero is the reading of that day.
    assert select_daily([watch])[0]["value"] == 0


def test_a_sleep_fragment_never_hides_the_night_another_source_recorded():
    fragment = dict(reading("Oura", "Oura", "time_in_bed", 0.2, unit="hours"), category="device_sleep")
    night = dict(reading("Clock", "Apple Health", "time_in_bed", 5.9, unit="hours"), category="device_sleep")
    assert select_metrics({"time_in_bed": [fragment, night]}, {})["time_in_bed"][0]["value"] == 5.9


# --- OPS-01: implausible body values -----------------------------------------

def test_plausibility_matches_the_patient_checks_and_rescues_metres():
    assert plausible_value("waist_circumference", 0.99) == pytest.approx(99.0)
    assert plausible_value("waist_circumference", 99.0) == 99.0
    assert plausible_value("waist_circumference", 450) is None
    assert plausible_value("body_height", 1.85) == pytest.approx(185.0)
    assert plausible_value("body_weight", 0.5) is None
    assert plausible_value("steps", 0) == 0
    assert not valid_row(reading("x", "OpenWearables", "waist_circumference", 0.99, unit="cm"))
    assert valid_row(reading("x", "Apple Health", "waist_circumference", 99.0, unit="cm"))


def test_bridge_waist_in_metres_is_stored_as_centimetres(linked_record):  # noqa: F811
    settings, owner = linked_record
    bucket: dict = {}
    ow._map_body_series([{"type": "waist_circumference", "timestamp": "2018-09-05T20:25:00Z", "value": 0.99,
                          "unit": "cm", "source": {"provider": "apple", "source": "Health", "device": "iPhone10,6"}}], bucket)
    ow._write_days(settings, owner, ow.ensure_envelope(settings, owner), list(bucket.values()),
                   ("waist_circumference",), "2018-09-05", "2018-09-05", ow.account_identity(settings, owner))
    with connect(settings) as db:
        values = [row["value"] for row in db.execute("SELECT value FROM device_metric_days WHERE metric_key='waist_circumference'")]
    assert values == [pytest.approx(99.0)]


@pytest.fixture
def ledger(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    owner = create_user(settings, "owner@example.com", "owner", PASSWORD)
    patient = seed_patient(settings, owner, "Local fixture")
    with connect(settings) as db:
        db.execute("INSERT INTO vendors(id,canonical_name,created_at) VALUES ('fixture','Fixture',?)", (utc_now(),))
        for import_id, adapter in (("fixture", "apple_health"), ("old", "apple_health")):
            db.execute("""INSERT INTO device_imports(id,owner_user_id,patient_id,vendor_id,adapter_key,source_path,
                          source_fingerprint,source_bytes,imported_at) VALUES (?,?,?,'fixture',?,?,?,1,?)""",
                       (import_id, owner, patient, adapter, import_id, import_id, utc_now()))
    return settings, owner, patient


def insert(settings, owner, patient, row, import_id="fixture"):
    with connect(settings) as db:
        db.execute("""INSERT INTO device_metric_days(id,owner_user_id,patient_id,import_id,source_name,source_vendor,
                      metric_key,metric_name,category,day,aggregation,unit,value,value_min,value_max,sample_count,created_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (f"{row['source_name']}:{row['metric_key']}:{row['day']}", owner, patient, import_id, row["source_name"],
                    row["source_vendor"], row["metric_key"], row["metric_name"], row["category"], row["day"],
                    row["aggregation"], row["unit"], row["value"], row["value"], row["value"], 1, utc_now()))


def test_an_implausible_waist_is_never_shown_judged_or_put_in_the_profile(ledger):
    settings, owner, patient = ledger
    insert(settings, owner, patient, reading("OpenWearables · apple · Health · iPhone10,6", "OpenWearables",
                                             "waist_circumference", 0.99, "2018-09-05", "latest", "cm"))
    with connect(settings) as db:
        assert device_metric_values(db, owner, "waist_circumference") == []
        assert "device:waist_circumference" not in {card["id"] for card in device_metric_catalog(db, owner)}
        assert web_app._measured_body(db, owner) == {}
    with TestClient(create_app(settings)) as client:
        login(client, "owner@example.com")
        assert client.get("/devices/metrics/waist_circumference").status_code == 404
    insert(settings, owner, patient, reading("Health", "Apple Health", "waist_circumference", 99.0, "2018-09-05", "latest", "cm"))
    with connect(settings) as db:
        assert web_app._measured_body(db, owner)["waist_cm"]["value"] == 99.0


# --- OPS-03: one local-day boundary ------------------------------------------

def test_local_day_is_the_persons_calendar_day_in_summer_and_winter():
    assert local_day("2026-07-01T21:30:00Z", KYIV) == "2026-07-02"   # UTC+3
    assert local_day("2026-01-01T21:30:00Z", KYIV) == "2026-01-01"   # UTC+2
    assert local_day("2026-01-01T22:30:00Z", KYIV) == "2026-01-02"
    assert local_day("2026-03-29 00:30:00 +0000", KYIV) == "2026-03-29"
    assert local_day("2026-08-07", KYIV) == "2026-08-07"
    assert local_bounds_utc("2026-07-01", "2026-07-01", KYIV) == (
        "2026-06-30T21:00:00.000000+00:00", "2026-07-01T21:00:00.000000+00:00")


def test_raw_steps_are_cut_at_local_midnight_not_utc():
    source = {"provider": "apple", "source": "Ivan’s Apple Watch", "device": "Watch7,5"}
    bucket: dict = {}
    ow.map_raw_metrics([
        {"type": "steps", "timestamp": "2026-10-05T22:30:00Z", "value": 60, "unit": "count", "source": source},
        {"type": "steps", "timestamp": "2026-10-06T10:00:00Z", "value": 3877, "unit": "count", "source": source},
    ], bucket, KYIV)
    totals = {day: item.value for (key, day, _), item in bucket.items() if key == "steps"}
    assert totals == {"2026-10-06": 3937}


def test_raw_recompute_reads_the_first_local_days_early_hours_from_storage(linked_record, monkeypatch):  # noqa: F811
    settings, owner = linked_record
    source = {"provider": "apple", "source": "Watch", "device": "Watch7,5"}

    def sample(stamp, value, key):
        return {"id": key, "type": "steps", "timestamp": stamp, "value": value, "unit": "count", "source": source}

    # The previous window carried 23:30 Kyiv on 10-05 and 00:30 Kyiv on 10-06.
    monkeypatch.setattr(ow, "_api", lambda *args: {"data": [sample("2026-10-05T20:30:00Z", 5, "a"),
                                                            sample("2026-10-05T21:30:00Z", 7, "b")],
                                                   "pagination": {"has_more": False}})
    hooks.sync_raw_timeseries(settings, owner, "2026-10-05", "2026-10-05")
    monkeypatch.setattr(ow, "_api", lambda *args: {"data": [sample("2026-10-06T09:00:00Z", 100, "c")],
                                                   "pagination": {"has_more": False}})
    hooks.sync_raw_timeseries(settings, owner, "2026-10-06", "2026-10-06")
    with connect(settings) as db:
        days = dict(db.execute("SELECT day, value FROM device_metric_days WHERE metric_key='steps' ORDER BY day"))
    assert days == {"2026-10-05": 5, "2026-10-06": 107}


def test_a_summary_day_without_raw_samples_is_kept_not_lost(linked_record):  # noqa: F811
    settings, owner = linked_record
    remote, server, _generation = ow.account_identity(settings, owner)
    source = {"provider": "apple", "source": "Watch", "device": "Watch3,4"}
    with connect(settings) as db:
        db.execute("INSERT INTO openwearables_raw_records VALUES (?,?,?,?,?,?,?,?)",
                   (owner, server, remote, "activity", "a1", "2019-09-20",
                    json.dumps({"date": "2019-09-20", "steps": 4321, "source": source}), utc_now()))
        db.execute("INSERT INTO openwearables_raw_samples VALUES (?,?,?,?,?,?,?,?)",
                   (owner, server, remote, "e1", "2019-09-21T09:00:00.000000+00:00", "energy",
                    json.dumps({"type": "energy", "timestamp": "2019-09-21T09:00:00Z", "value": 450, "unit": "kcal",
                                "source": source}), utc_now()))
    envelope, identity = ow.ensure_envelope(settings, owner), ow.account_identity(settings, owner)
    with connect(settings) as db:
        ow.recompute_raw_days(settings, db, owner, envelope, identity, "2019-09-20", "2019-09-21")
    with connect(settings) as db:
        rows = {(r[0], r[1]): r[2] for r in db.execute("SELECT metric_key, day, value FROM device_metric_days")}
    # The pre-2020 "energy" series is active energy; the summary-only day stays.
    assert rows == {("steps", "2019-09-20"): 4321, ("active_energy", "2019-09-21"): 450}


def test_apple_export_days_follow_the_persons_zone(tmp_path):
    export = tmp_path / "export.xml"
    record = ('<Record type="HKQuantityTypeIdentifierStepCount" sourceName="Watch" unit="count" '
              'startDate="{start}" endDate="{start}" value="{value}"/>')
    export.write_text("<HealthData>\n" + "\n".join([
        record.format(start="2026-07-01 23:30:00 +0000", value=10),   # 02:30 Kyiv on 07-02
        record.format(start="2026-07-01 12:00:00 +0300", value=20),
    ]) + "\n</HealthData>\n", encoding="utf-8")
    parsed = AppleHealthAdapter().parse(export, tz=KYIV)
    steps = {item.day: item.value for item in parsed.aggregates if item.definition.key == "steps"}
    assert steps == {"2026-07-01": 20, "2026-07-02": 10}


def test_reaggregation_is_idempotent_and_reports_moved_days(linked_record, monkeypatch):  # noqa: F811
    settings, owner = linked_record
    source = {"provider": "apple", "source": "Watch", "device": "Watch7,5"}
    samples = [{"id": f"s{index}", "type": "steps", "timestamp": stamp, "value": value, "unit": "count", "source": source}
               for index, (stamp, value) in enumerate([("2026-10-05T22:30:00Z", 60), ("2026-10-06T10:00:00Z", 3877)])]
    monkeypatch.setattr(ow, "_api", lambda *args: {"data": samples, "pagination": {"has_more": False}})
    hooks.sync_raw_timeseries(settings, owner, "2026-10-05", "2026-10-06")
    # Simulate the old UTC cut still stored.
    with connect(settings) as db:
        db.execute("UPDATE device_metric_days SET value=3877 WHERE metric_key='steps' AND day='2026-10-06'")
        db.execute("""INSERT INTO device_metric_days(id,owner_user_id,patient_id,import_id,source_name,source_vendor,metric_key,
                      metric_name,category,day,aggregation,unit,value,sample_count,created_at)
                      SELECT 'utc',owner_user_id,patient_id,import_id,source_name,source_vendor,metric_key,metric_name,category,
                             '2026-10-05',aggregation,unit,60,1,created_at FROM device_metric_days WHERE metric_key='steps'""")
    before = {row[0]: row[1] for row in connect(settings).execute("SELECT day, value FROM device_metric_days WHERE metric_key='steps'")}
    reaggregate_openwearables(settings, owner, pause=0)
    after = {row[0]: row[1] for row in connect(settings).execute("SELECT day, value FROM device_metric_days WHERE metric_key='steps'")}
    assert before == {"2026-10-05": 60, "2026-10-06": 3877}
    assert after == {"2026-10-06": 3937}
    assert sum(before.values()) == sum(after.values())
    report = compare({("steps", "w"): before}, {("steps", "w"): after}, {"steps": "sum"})
    assert report[0]["changed_days"] == 2 and report[0]["sum_before"] == report[0]["sum_after"]
    reaggregate_openwearables(settings, owner, pause=0)
    again = {row[0]: row[1] for row in connect(settings).execute("SELECT day, value FROM device_metric_days WHERE metric_key='steps'")}
    assert again == after


# --- OPS-07, OPS-09, OPS-12, OPS-24 on the pages -----------------------------

def test_partial_today_never_headlines_and_never_fills_a_metric_never_filled(ledger):
    settings, owner, patient = ledger
    now = today(KYIV)
    yesterday = (date.fromisoformat(now) - timedelta(days=1)).isoformat()
    for day, value in ((yesterday, 6245), (now, 12)):
        insert(settings, owner, patient, reading("Ivan’s Apple Watch", "Apple Health", "steps", value, day))
    for day in (yesterday, now):
        insert(settings, owner, patient, dict(reading("OpenWearables · apple · Watch · Watch7,5", "OpenWearables",
                                                      "sleep_naps", 0, day, unit="count"), category="device_sleep"))
    assert is_partial_day("steps", now, KYIV) and not is_partial_day("steps", yesterday, KYIV)
    assert not is_partial_day("resting_heart_rate", now, KYIV) and not is_partial_day("sleep_duration", now, KYIV)
    with connect(settings) as db:
        cards = {card["id"]: card for card in device_metric_catalog(db, owner)}
    assert cards["device:steps"]["latest_numeric"] == 6245 and cards["device:steps"]["latest_date"] == yesterday
    assert "device:sleep_naps" not in cards
    with TestClient(create_app(settings)) as client:
        login(client, "owner@example.com")
        client.cookies.set("anamna_lang", "en")
        page = client.get("/devices/metrics/steps").text
        assert "6,245" in page and "12 steps so far today" in page
        payload = json.loads(page.split('id="device-chart-data">', 1)[1].split("</script>", 1)[0]) if 'id="device-chart-data"' in page else None
        assert payload is None or now not in payload["combined"]["d"]


def test_device_cards_carry_no_verify_chip_and_go_stale_after_a_week(ledger):
    settings, owner, patient = ledger
    # A daily metric that stopped: ten days in a row, the last 20 days ago.
    for back in range(20, 30):
        day = (date.today() - timedelta(days=back)).isoformat()
        insert(settings, owner, patient, reading("Ivan’s Apple Watch", "Apple Health", "exercise_minutes", 22, day, unit="min"))
    with connect(settings) as db:
        card = next(card for card in web_app._build_device_catalog(db, owner) if card["id"] == "device:exercise_minutes")
    # A quiet device is a fact, not a schedule falling due: no overdue badge,
    # plain text beside the date instead (owner, 2026-11-06).
    assert card["staleness"]["state"] != "overdue" and "20" in card["staleness"]["quiet_text"]
    assert "20" in card["date_text"]
    with TestClient(create_app(settings)) as client:
        login(client, "owner@example.com")
        for locale, text in (("en", "No new readings for 20 days"), ("uk", "Нових вимірювань немає вже 20 днів")):
            client.cookies.delete("anamna_lang")
            client.cookies.set("anamna_lang", locale)
            page = client.get("/devices").text
            assert "an-state-slot--verify" not in page.split("device-metric-grid", 1)[1].split("</section>", 1)[0]
            # The device card carries the chip; /metrics lists compact result
            # rows since F6a, without cadence chips.
            assert text in page


def test_devices_header_is_compact_and_says_its_date_as_a_date(ledger):
    """The header printed the last tracked day in the serif stat-numeral style,
    broken over three lines («06 / лист. / 2026»), above a lead sentence of
    storage jargon. Now: no title block at all (the navigation names the
    page), a small stat row with the date as a <time> in running text and the
    two counts as labelled links, and the device cards straight after it;
    vendor and provenance tiles fold."""
    settings, owner, patient = ledger
    insert(settings, owner, patient, reading("Owner", "Apple Health", "steps", 100, "2026-08-01"))
    with TestClient(create_app(settings)) as client:
        login(client, "owner@example.com")
        for locale, day, workouts, events in (
            ("en", "01 Aug 2026", "0 workouts", "0 ECGs and heart alerts"),
            ("uk", "01 серп. 2026", "0 тренувань", "0 ЕКГ і серцевих сповіщень"),
        ):
            client.cookies.delete("anamna_lang")
            client.cookies.set("anamna_lang", locale)
            page = client.get("/devices").text
            head = page.split('<section class="an-device-head"', 1)[1].split("</section>", 1)[0]
            assert "an-totals" not in head and "<dd>" not in head
            assert "aggregate" not in head and "агрегат" not in head
            assert f'<time datetime="2026-08-01">{day}</time>' in head
            assert f'<a href="#device-workouts">{workouts}</a>' in head
            assert f'<a href="#device-events">{events}</a>' in head
            # Cards come first; the vendor tiles and the provenance fold.
            assert page.index("device-metric-grid") < page.index('id="device-sources"')
            assert '<details class="panel an-page-disclosure" id="device-sources">' in page
            assert '<details class="panel an-page-disclosure" id="device-provenance">' in page
            assert 'id="device-workouts"' in page and 'id="device-events"' in page


def test_provenance_marks_superseded_exports_and_counts_rows_in_use(ledger):
    settings, owner, patient = ledger
    insert(settings, owner, patient, reading("Owner", "Apple Health", "steps", 100, "2026-08-01"))
    with connect(settings) as db:
        overview = device_overview(db, owner)
    imports = {item["id"]: item for item in overview["imports"]}
    assert imports["old"]["superseded"] and not imports["fixture"]["superseded"]
    assert imports["fixture"]["rows_owned"] == 1 and overview["active_import_count"] == 1
    apple = next(vendor for vendor in overview["vendors"] if vendor["key"] == "apple_health")
    assert apple["record_count"] == 1 and apple["latest_date"] == "2026-08-01"


# --- PERF-02 / PERF-03 ---------------------------------------------------------

def test_detail_page_inlines_one_columnar_series_and_loads_sources_on_demand(ledger):
    settings, owner, patient = ledger
    start = date(2016, 1, 1)
    with connect(settings) as db:
        for offset in range(3000):
            day = (start + timedelta(days=offset)).isoformat()
            for name, vendor, value in (("Ivan’s Apple Watch", "Apple Health", 8000.123456 + offset),
                                        ("OpenWearables · apple · Owner · iPhone14,2", "OpenWearables", 7000.987654)):
                db.execute("""INSERT INTO device_metric_days(id,owner_user_id,patient_id,import_id,source_name,source_vendor,
                              metric_key,metric_name,category,day,aggregation,unit,value,value_min,value_max,sample_count,created_at)
                              VALUES (?,?,?,'fixture',?,?,'steps','Daily steps','device_activity',?,'sum','steps',?,1,9,40,?)""",
                           (f"{name}{day}", owner, patient, name, vendor, day, value, utc_now()))
    with TestClient(create_app(settings)) as client:
        login(client, "owner@example.com")
        client.cookies.set("anamna_lang", "uk")
        page = client.get("/devices/metrics/steps")
        assert page.status_code == 200 and len(page.content) < 200_000
        payload = json.loads(page.text.split('id="device-chart-data">', 1)[1].split("</script>", 1)[0])
        # The year the chart opens on is inline; "All" fetches the rest.
        assert len(payload["combined"]["d"]) == 367 and set(payload["combined"]) == {"d", "v", "s", "n", "lo", "hi"}
        assert payload["complete"] is False
        assert payload["combined"]["v"][0] == round(8000.123456 + 2633, 1)
        everything = client.get(payload["full_url"]).json()
        assert len(everything["points"]["d"]) == 3000 and everything["points"]["v"][0] == 8000.1
        source = payload["sources"][-1]
        series = client.get(source["url"]).json()
        assert len(series["points"]["d"]) == 3000 and series["labels"] == ["Owner · OpenWearables"]
        assert client.get("/api/devices/metrics/steps/source/unknown").status_code == 404


def test_device_write_rebuilds_only_the_device_half_and_only_for_its_owner(ledger, monkeypatch):
    settings, owner, patient = ledger
    other = create_user(settings, "partner@example.com", "Olena", PASSWORD)
    insert(settings, owner, patient, reading("Owner", "Apple Health", "steps", 100, "2026-08-01"))
    built: list[str] = []
    lab, device = web_app._build_lab_catalog, web_app._build_device_catalog
    monkeypatch.setattr(web_app, "_build_lab_catalog", lambda c, o: built.append(f"lab:{o}") or lab(c, o))
    monkeypatch.setattr(web_app, "_build_device_catalog", lambda c, o: built.append(f"device:{o}") or device(c, o))
    web_app.invalidate_catalog()
    with connect(settings) as db:
        web_app._catalog(db, owner)
        web_app._catalog(db, other)
    built.clear()
    insert(settings, owner, patient, reading("Owner", "Apple Health", "steps", 200, "2026-08-02"))
    with connect(settings) as db:
        web_app._catalog(db, owner)
        web_app._catalog(db, other)
    assert built == [f"device:{owner}"]
    web_app.invalidate_catalog(other)
    built.clear()
    with connect(settings) as db:
        web_app._catalog(db, owner)
        web_app._catalog(db, other)
    assert built == [f"lab:{other}", f"device:{other}"]


def test_a_night_longer_than_sixteen_hours_is_never_selected():
    from anamna.devices.reconcile import valid_row
    from anamna.devices.units import is_plausible

    assert not valid_row({"metric_key": "sleep_duration", "value": 21.0})  # a manual 21 h entry, 2019-08-09
    assert not valid_row({"metric_key": "time_in_bed", "value": 16.5})
    assert valid_row({"metric_key": "sleep_duration", "value": 6.55})
    assert valid_row({"metric_key": "sleep_duration", "value": 16.0})
    assert is_plausible("sleep_awake", 0.0)


def test_a_quiet_device_metric_never_marks_a_panel_overdue(ledger):
    """Owner, 2026-11-06: the Sleep panel read «Нових даних немає 91 день» while
    its rows were from today.  The badge means "a cited schedule says this is
    due"; a device that stopped sending one metric is not that."""
    settings, owner, patient = ledger
    today = date.today().isoformat()
    quiet = (date.today() - timedelta(days=91)).isoformat()
    insert(settings, owner, patient, reading("Oura", "Oura", "sleep_duration", 5.7, today, "sum", "hours"))
    insert(settings, owner, patient, reading("Watch", "Apple Health", "sleeping_wrist_temperature", 0.1, quiet, "average", "°C"))
    with connect(settings) as db:
        cards = {card["id"]: card for card in web_app._build_device_catalog(db, owner)}
    assert cards["device:sleeping_wrist_temperature"]["staleness"]["state"] != "overdue"
    with TestClient(create_app(settings)) as client:
        login(client, "owner@example.com")
        page = client.get("/panels/sleep").text
        # No cadence slot at all, or one that is not overdue.
        cadence = page.split("an-state-slot--cadence", 1)[1].split("</span>", 1)[0] if "an-state-slot--cadence" in page else ""
        assert 'data-state="overdue"' not in cadence and "No new readings" not in cadence
        assert 'data-state="overdue"' not in page.split("<main", 1)[1].split("an-panel-members", 1)[0]


def test_on_demand_device_metric_never_says_it_went_quiet():
    """An ECG taken now and then has no expected next day: "no new data for
    91 days" beside it reads as a missed test (owner, 2026-11-06).  Only a
    metric that normally arrives most days says so once a week has passed."""
    today_ = date(2026, 11, 6)
    daily = [str(today_ - timedelta(days=95 + n)) for n in range(30)]
    sparse = [str(today_ - timedelta(days=95 + 20 * n)) for n in range(8)]
    assert web_app._arrives_daily(daily)
    assert not web_app._arrives_daily(sparse)
    assert not web_app._arrives_daily(daily[:3]), "too little history to call it daily"
    latest = daily[0]
    assert web_app._device_staleness(latest, {}, daily=True).get("quiet_text")
    assert not web_app._device_staleness(latest, {}, daily=False).get("quiet_text")
