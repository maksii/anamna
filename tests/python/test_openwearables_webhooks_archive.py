"""The compact raw archive, its background conversion and the status pages
that must never count raw samples on render (PERF-01, PERF-11, UX-26, OPS-23)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from anamna import openwearables as ow
from anamna import openwearables_archive as archive
from anamna import openwearables_webhooks as hooks
from anamna.db import connect, migrate, transaction
from anamna.i18n import t
from anamna.security import create_session, create_user
from anamna.web.app import create_app
from test_openwearables import BASE, OTHER_REMOTE, REMOTE
from test_openwearables_webhooks import linked_record, payload, signed  # noqa: F401 — fixture

LEGACY_COLUMNS = "(owner_user_id,server_url,remote_user_id,sample_key,timestamp,series_type,payload_json,received_at)"


def legacy_rows(owner, remote=REMOTE, days=("2026-07-30", "2026-07-31", "2026-08-01"), per_day=40):
    """Rows exactly as the pre-040 write path stored them."""
    rows = []
    for day in days:
        for index in range(per_day):
            kind = ("heart_rate", "steps", "future_series")[index % 3]
            value = {"heart_rate": 60 + index, "steps": index * 1.5, "future_series": "n/a"}[kind]
            unit = {"heart_rate": "bpm", "steps": "count", "future_series": "x"}[kind]
            sample = {"timestamp": f"{day}T{index % 24:02d}:{index:02d}:00Z", "type": kind, "unit": unit, "value": value,
                      "source": {"device": "Годинник", "provider": "apple"}, "original_detail": {"kept": index}}
            rows.append((owner, BASE, remote, hooks._sample_key(sample), hooks._utc_stamp(sample["timestamp"]), kind,
                         json.dumps(sample, ensure_ascii=False, sort_keys=True), f"2026-09-0{1 + index % 3}T00:00:00+00:00"))
    return rows


def seed_legacy(settings, rows):
    with connect(settings) as db:
        # As migration 040 does for every account that existed before it.
        db.execute("INSERT OR IGNORE INTO openwearables_raw_totals(owner_user_id) SELECT id FROM users")
        db.executemany(f"INSERT INTO openwearables_raw_samples{LEGACY_COLUMNS} VALUES (?,?,?,?,?,?,?,?)", rows)


def convert_all(settings):
    steps, cursor = 0, archive.convert_step(settings, budget=0)
    while cursor:
        steps += 1
        assert steps < 1000
        cursor = archive.convert_step(settings, budget=0, cursor=cursor)
    return steps


def test_migration_creates_structures_only_and_leaves_old_rows_alone(tmp_path):
    """Startup must not wait on 7 M rows: 040 never touches them."""
    from test_web_panels import settings_for
    settings = settings_for(tmp_path)
    migrate(settings)
    owner = create_user(settings, "owner@example.com", "owner", "local-fixture-password")
    with connect(settings) as db:
        db.execute("DELETE FROM schema_migrations WHERE version=40")
        for name in ("openwearables_raw_days", "openwearables_raw_conversion", "openwearables_raw_totals"):
            db.execute(f"DROP TABLE {name}")
        db.executemany(f"INSERT INTO openwearables_raw_samples{LEGACY_COLUMNS} VALUES (?,?,?,?,?,?,?,?)", legacy_rows(owner))
    migrate(settings)
    with connect(settings) as db:
        assert db.execute("SELECT count(*) FROM openwearables_raw_samples").fetchone()[0] == 120
        assert db.execute("SELECT count(*) FROM openwearables_raw_days").fetchone()[0] == 0
        assert [tuple(r) for r in db.execute("SELECT owner_user_id,legacy_base FROM openwearables_raw_totals")] == [(owner, None)]


def test_next_day_lookup_and_old_day_reads_stay_on_the_index(linked_record):
    settings, owner = linked_record
    with connect(settings) as db:
        plan = " ".join(str(r[3]) for r in db.execute(f"""EXPLAIN QUERY PLAN SELECT owner_user_id FROM {archive.LEGACY}
            WHERE (owner_user_id,server_url,remote_user_id,timestamp) >= (?,?,?,?)
            ORDER BY owner_user_id,server_url,remote_user_id,timestamp LIMIT 1""", ("a", "b", "c", "d")))
        assert "ow_samples_window" in plan and ">" in plan
        plan = " ".join(str(r[3]) for r in db.execute("EXPLAIN QUERY PLAN " + f"""SELECT 1 FROM {archive.LEGACY}
            WHERE owner_user_id=? AND server_url=? AND remote_user_id=? AND timestamp >= ? AND timestamp < ?""",
            ("a", "b", "c", "d", "e")))
        assert "ow_samples_window" in plan and "timestamp>" in plan


def test_conversion_is_content_identical_resumable_and_reclaimed_after_verification(linked_record):
    settings, owner = linked_record
    other = create_user(settings, "partner@example.com", "Olena", "local-fixture-password")
    rows = legacy_rows(owner) + legacy_rows(other, OTHER_REMOTE, days=("2026-08-01",))
    seed_legacy(settings, rows)
    with connect(settings) as db:
        before = archive.day_fingerprints(db)
        reader_before = list(archive.iter_samples(db, owner, BASE, REMOTE, "2026-07-01", "2026-08-31"))
        assert archive.totals(db) == {"samples": None, "compacting": True}  # not counted yet
    # One account-day per step at budget 0: a restart between any two is valid.
    assert archive.convert_step(settings, budget=0)
    with connect(settings) as db:
        assert archive.totals(db) == {"samples": len(rows), "compacting": True}
        assert db.execute("SELECT count(*) FROM openwearables_raw_conversion").fetchone()[0] == 1
        # The reader sees both formats, in the same order, mid-conversion.
        assert list(archive.iter_samples(db, owner, BASE, REMOTE, "2026-07-01", "2026-08-31")) == reader_before
        assert archive.day_fingerprints(db) == before
    with pytest.raises(SystemExit, match="not copied"):
        archive.reclaim(settings)  # never drops while anything is uncopied
    # A restart without the cursor finds the next uncopied day from the ledger.
    convert_all(settings)
    with connect(settings) as db:
        assert db.execute("SELECT count(*) FROM openwearables_raw_samples").fetchone()[0] == len(rows)  # copied, not deleted
        assert archive.status(db)["conversion_complete"]
        assert archive.day_fingerprints(db) == before  # per-day counts and value sums
        assert archive.verify(db) == {"days": 4, "samples": len(rows), "matching": 4, "replaced": 0, "mismatched": []}
        assert archive.totals(db) == {"samples": len(rows), "compacting": False}
    result = archive.reclaim(settings)
    assert result["file_bytes_after"] <= result["file_bytes_before"]
    with connect(settings) as db:
        assert not archive.legacy_present(db)
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='ow_samples_window'").fetchone()
        assert archive.day_fingerprints(db) == before
        assert list(archive.iter_samples(db, owner, BASE, REMOTE, "2026-07-01", "2026-08-31")) == reader_before
        assert archive.totals(db) == {"samples": len(rows), "compacting": False}
        assert archive.totals(db, other) == {"samples": 40, "compacting": False}
        assert db.execute("SELECT sum(length(samples)) FROM openwearables_raw_days").fetchone()[0] < \
            sum(len(r[6]) for r in rows) / 2  # compact
    assert not archive.convert_step(settings)  # idempotent once done
    assert hooks.operational_status(settings)["raw_sample_count"] == len(rows)


def test_a_day_that_does_not_read_back_is_rolled_back_untouched(linked_record, monkeypatch):
    settings, owner = linked_record
    seed_legacy(settings, legacy_rows(owner))
    real = archive._encode
    monkeypatch.setattr(archive, "_encode", lambda rows: real(list(rows)[:-1]))
    with pytest.raises(archive.ArchiveMismatch):
        archive.convert_step(settings, budget=0)
    with connect(settings) as db:
        assert db.execute("SELECT count(*) FROM openwearables_raw_samples").fetchone()[0] == 120
        assert db.execute("SELECT count(*) FROM openwearables_raw_days").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM openwearables_raw_conversion").fetchone()[0] == 0


def test_background_thread_finishes_and_survives_a_busy_database(linked_record, monkeypatch):
    settings, owner = linked_record
    seed_legacy(settings, legacy_rows(owner))
    calls = {"n": 0}
    real = archive.convert_step

    def flaky(settings, budget=archive.STEP_SECONDS, cursor=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return real(settings, budget=0, cursor=cursor)

    monkeypatch.setattr(archive, "convert_step", flaky)
    stop = threading.Event()
    waits = []
    monkeypatch.setattr(stop, "wait", lambda seconds: waits.append(seconds))
    archive.run_conversion(settings, stop)
    assert waits[0] == 5  # a missed turn, not a dead thread
    with connect(settings) as db:
        assert archive.status(db)["conversion_complete"]
        assert archive.totals(db, owner) == {"samples": 120, "compacting": False}


def test_fresh_install_drops_the_empty_old_table_at_once(linked_record):
    settings, owner = linked_record
    assert archive.convert_step(settings) is None
    with connect(settings) as db:
        assert not archive.legacy_present(db)


def test_write_paths_supersede_old_days_during_conversion(linked_record, monkeypatch):
    settings, owner = linked_record
    seed_legacy(settings, legacy_rows(owner))
    with connect(settings) as db:
        before = {s["timestamp"]: s for s in archive.iter_samples(db, owner, BASE, REMOTE, "2026-07-30", "2026-07-30")}
    # A webhook delivery for 1 Aug copies that day first, then merges.
    body = payload()
    hooks.receive(settings, "receiver", body, signed(body))
    with connect(settings) as db:
        assert len(list(archive.iter_samples(db, owner, BASE, REMOTE, "2026-08-01", "2026-08-01"))) == 41
    # A sync of 31 Jul replaces that day; its 40 old rows are superseded.
    fetched = [{"timestamp": "2026-07-31T10:00:00Z", "type": "heart_rate", "value": 70, "unit": "bpm"}]
    monkeypatch.setattr(ow, "_api", lambda *args: {"data": fetched, "pagination": {"has_more": False}})
    hooks.sync_raw_timeseries(settings, owner, "2026-07-31", "2026-07-31")
    with connect(settings) as db:
        assert list(archive.iter_samples(db, owner, BASE, REMOTE, "2026-07-31", "2026-07-31")) == fetched
    convert_all(settings)
    with connect(settings) as db:
        after = {s["timestamp"]: s for s in archive.iter_samples(db, owner, BASE, REMOTE, "2026-07-30", "2026-07-30")}
        assert after == before
        assert list(archive.iter_samples(db, owner, BASE, REMOTE, "2026-07-31", "2026-07-31")) == fetched
        assert archive.verify(db) | {"samples": 0} == {"days": 3, "samples": 0, "matching": 1, "replaced": 2, "mismatched": []}
        assert archive.totals(db, owner) == {"samples": 40 + 41 + 1, "compacting": False}
    archive.reclaim(settings)
    with connect(settings) as db:
        assert archive.totals(db, owner) == {"samples": 40 + 41 + 1, "compacting": False}
        assert list(archive.iter_samples(db, owner, BASE, REMOTE, "2026-07-31", "2026-07-31")) == fetched


def test_relink_and_account_deletion_erase_archive_and_counters(linked_record):
    settings, owner = linked_record
    seed_legacy(settings, legacy_rows(owner))
    archive.convert_step(settings, budget=0)  # one day archived, two still old
    ow.link_account(settings, owner, OTHER_REMOTE, "other@example.test")
    with connect(settings) as db:
        for table in ("openwearables_raw_samples", "openwearables_raw_days", "openwearables_raw_conversion"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    convert_all(settings)  # the emptied table goes; relinking afterwards still works
    ow.link_account(settings, owner, REMOTE, "owner@example.com")
    with connect(settings) as db:
        assert not archive.legacy_present(db)
        assert archive.totals(db, owner) == {"samples": 0, "compacting": False}
        db.execute("DELETE FROM users WHERE id=?", (owner,))
        assert db.execute("SELECT count(*) FROM openwearables_raw_totals").fetchone()[0] == 0
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_status_renders_never_read_the_raw_archive(linked_record):
    """PERF-01: 600 ms of every /profile was `count(*)` over 7.4 M rows."""
    settings, owner = linked_record
    seed_legacy(settings, legacy_rows(owner))
    convert_all(settings)
    archive.reclaim(settings)
    seen = []
    real = sqlite3.connect

    def traced(*args, **kwargs):
        connection = real(*args, **kwargs)
        connection.set_trace_callback(seen.append)
        return connection

    import anamna.db as db_module
    original = db_module.sqlite3.connect
    db_module.sqlite3.connect = traced
    try:
        status = hooks.operational_status(settings, owner)
        hooks.operational_status(settings)
    finally:
        db_module.sqlite3.connect = original
    assert status["raw_sample_count"] == 120
    touched = [sql for sql in seen if "sqlite_master" not in sql
               and ("openwearables_raw_days" in sql or "openwearables_raw_samples" in sql)]
    assert touched == []


def test_scheduled_catchup_is_three_days_and_monthly_history_is_incremental(linked_record):
    settings, owner = linked_record
    from datetime import UTC, datetime, timedelta
    today = datetime.now(UTC).date()
    assert hooks.schedule_due(settings, now=1000) == 1
    with connect(settings) as db:
        jobs = {r["reason"]: r for r in db.execute("SELECT * FROM openwearables_sync_jobs")}
        assert jobs["backfill"]["start_day"] == ow.EPOCH_DAY  # a new link gets full history
        assert (jobs["scheduled"]["start_day"], jobs["scheduled"]["end_day"]) == (
            (today - timedelta(days=3)).isoformat(), today.isoformat())
        db.execute("UPDATE openwearables_sync_jobs SET status='complete', end_day='2026-10-20'")
    hooks.schedule_due(settings, now=1000 + 31 * 86400)
    with connect(settings) as db:
        history = db.execute("SELECT start_day FROM openwearables_sync_jobs WHERE reason='backfill' AND status='queued'").fetchone()
    assert history[0] == "2026-10-13"  # previous end minus the overlap, not 2015


def admin_client(settings, user_id, locale="en"):
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", locale)
    return client


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_admin_shows_ten_runs_with_times_and_loads_the_rest_on_request(linked_record, locale):
    settings, owner = linked_record
    with transaction(settings, immediate=True) as db:
        for index in range(14):
            db.execute("""INSERT INTO openwearables_sync_jobs(id,owner_user_id,server_url,remote_user_id,link_generation,
                reason,start_day,end_day,next_day,status,counts_json,created_at,updated_at)
                VALUES (?,?,?,?,'', 'scheduled','2026-10-06','2026-11-05','2026-11-06','complete',?,?,?)""",
                (f"job{index:02d}", owner, BASE, REMOTE, json.dumps({"activity": 3, "raw_timeseries": 1200 + index}),
                 f"2026-11-0{1 + index // 4}T{2 + index % 4 * 6:02d}:46:19+00:00", f"2026-11-0{1 + index // 4}T{3 + index % 4 * 6:02d}:21:45+00:00"))
    client = admin_client(settings, owner, locale)
    from anamna.i18n import activate_locale, reset_locale
    token = activate_locale(locale)
    try:
        page = client.get("/admin/openwearables").text
        assert page.count(t("ow_hooks.reason_scheduled")) == 10
        assert "21:21\u00a0UTC" in page and "08:46\u00a0UTC" in page  # time of day: pairs are distinguishable
        assert "\u00a0-\u2060\u00a0" in page  # the period never wraps
        assert t("ow_hooks.show_all", count="14") in page
        rest = client.get("/admin/openwearables/jobs?offset=10")
        assert rest.status_code == 200 and rest.text.count("<tr>") == 4
        assert t("ow_hooks.fetched_samples") in rest.text
        member = create_user(settings, "member@example.test", "Member", "local-fixture-password")
        assert admin_client(settings, member).get("/admin/openwearables/jobs").status_code == 403
    finally:
        reset_locale(token)


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_profile_status_shows_last_check_and_never_admin_instructions(linked_record, locale):
    settings, owner = linked_record
    hooks.schedule_due(settings, now=time.time())
    with connect(settings) as db:
        db.execute("UPDATE openwearables_sync_jobs SET status='complete', updated_at='2026-11-05T22:21:45+00:00'")
    from anamna.i18n import activate_locale, reset_locale
    token = activate_locale(locale)
    try:
        page = admin_client(settings, owner, locale).get("/profile?tab=connections").text
        assert t("ow_hooks.last_check") in page and "22:21\u00a0UTC" in page
        assert t("ow_hooks.next_check") in page
        for admin_only in ("ow_hooks.empty", "ow_hooks.lead", "ow_hooks.subscriptions", "ow_hooks.receipts"):
            assert t(admin_only) not in page
        devices = admin_client(settings, owner, locale).get("/devices").text
        assert "webhook" not in devices.lower() and "вебхук" not in devices.lower()
    finally:
        reset_locale(token)


def test_local_day_rebuild_reads_the_compact_archive_not_only_the_old_table(linked_record):
    """F8's local-day rebuild and re-aggregation read raw samples; after F11's
    compaction those live in the archive, so they must go through its reader."""
    settings, owner = linked_record
    seed_legacy(settings, legacy_rows(owner))
    convert_all(settings)
    with connect(settings) as db:
        # Old table emptied of nothing yet, but every day is claimed: only the
        # archive's reader still sees the samples.
        via_reader = list(ow._stored_samples(db, owner, BASE, REMOTE, "2026-07-31T00:00:00", "2026-08-01T00:00:00"))
        span = archive.sample_day_span(db, owner, BASE, REMOTE)
    assert via_reader and all("2026-07-31T00:00:00" <= row["timestamp"] < "2026-08-01T00:00:00" for row in via_reader)
    assert len(via_reader) == 40
    assert span == ("2026-07-30", "2026-08-01")
    steps = list(ow._stored_samples(db_for(settings), owner, BASE, REMOTE, "2026-07-30T00:00:00", "2026-08-02T00:00:00",
                                     "steps"))
    assert steps and {row["type"] for row in steps} == {"steps"}


def db_for(settings):
    return connect(settings).__enter__()
