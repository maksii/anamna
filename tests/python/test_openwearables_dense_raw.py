"""Dense raw history must exceed a page budget without losing a sample."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json
import time

import pytest
from jinja2 import Environment, FileSystemLoader

from anamna import openwearables as ow
from anamna import openwearables_webhooks as hooks
from anamna.db import connect
from anamna.i18n import activate_locale, reset_locale, t
from test_openwearables_webhooks import linked_record


def sample(stamp="2018-05-24T10:00:00Z", value=1, identifier="old"):
    return {"id": identifier, "timestamp": stamp, "type": "basal_energy", "unit": "kcal", "value": value,
            "source": {"provider": "apple", "source": "Fixture", "device": "Watch"}, "original_detail": {"retained": True}}


def snapshot(settings):
    with connect(settings) as db:
        return {
            "raw": [tuple(row) for row in db.execute("SELECT day,series_type,sample_count,samples FROM openwearables_raw_days ORDER BY day,series_type")],
            "days": [tuple(row) for row in db.execute("SELECT id,source_name,metric_key,day,value,sample_count FROM device_metric_days ORDER BY id")],
        }


def track_spools(monkeypatch, tmp_path):
    original = hooks.tempfile.TemporaryDirectory
    paths = []
    def temporary(*args, **kwargs):
        directory = original(*args, dir=tmp_path, **kwargs)
        paths.append(Path(directory.name))
        return directory
    monkeypatch.setattr(hooks.tempfile, "TemporaryDirectory", temporary)
    return paths


def seed(settings, owner, monkeypatch):
    monkeypatch.setattr(ow, "_api", lambda *args: {"data": [sample()], "pagination": {"has_more": False}})
    hooks.sync_raw_timeseries(settings, owner, "2018-05-24", "2018-05-30")


def test_dense_week_splits_only_over_budget_and_deduplicates_corrected_fractional_boundary(linked_record, monkeypatch, tmp_path):
    settings, owner = linked_record
    seed(settings, owner, monkeypatch)
    before = snapshot(settings)
    spools = track_spools(monkeypatch, tmp_path)
    monkeypatch.setattr(ow, "_MAX_PAGES", 3)
    monkeypatch.setattr(ow, "_PAGE_LIMIT", 100)
    origin = datetime(2018, 5, 24, tzinfo=UTC)
    cut = datetime(2018, 5, 27, 11, 59, 59, 999999, tzinfo=UTC)
    rows = [sample((origin + timedelta(days=day, minutes=index)).isoformat(), identifier=f"{day}-{index}")
            for day in range(7) for index in range(90)]
    for delta in (-1, 0, 1):
        rows.append(sample((cut + timedelta(microseconds=delta)).isoformat(), identifier=f"cut-{delta}"))
    # An unknown series stays available with its full original provenance.
    rows[0]["type"] = "future_vendor_series"
    calls = []
    def api(_settings, path, params):
        assert snapshot(settings) == before  # No partly fetched window is visible.
        lower = datetime.fromisoformat(params["start_time"].replace("Z", "+00:00"))
        upper = datetime.fromisoformat(params["end_time"].replace("Z", "+00:00"))
        selected = [dict(row) for row in rows if lower <= datetime.fromisoformat(row["timestamp"]) <= upper]
        for row in selected:
            if row["id"] == "cut-0" and lower == cut:
                row["value"] = 9  # A later overlap copy corrects the same identity.
        selected.sort(key=lambda row: (row["timestamp"], row["id"]))
        offset = int(params.get("cursor", 0))
        batch = selected[offset:offset + int(params["limit"])]
        more = offset + len(batch) < len(selected)
        calls.append((lower, upper))
        return {"data": batch, "pagination": {"has_more": more, "next_cursor": str(offset + len(batch)) if more else None}}
    monkeypatch.setattr(ow, "_api", api)
    assert hooks.sync_raw_timeseries(settings, owner, "2018-05-24", "2018-05-30") == len(rows)
    assert len(set(calls)) > 1 and len(calls) < 30
    expected = {hooks._sample_key(row): dict(row, value=9) if row["id"] == "cut-0" else row for row in rows}
    with connect(settings) as db:
        identity = ow.account_identity(settings, owner)
        actual = {hooks._sample_key(row): row for row in hooks.archive.iter_samples(db, owner, identity[1], identity[0], "2018-05-24", "2018-05-30")}
        assert actual == expected
        total = db.execute("SELECT sum(value) FROM device_metric_days WHERE metric_key='resting_energy'").fetchone()[0]
        assert total == sum(row["value"] for row in expected.values() if row["type"] == "basal_energy")
    assert spools and not any(path.exists() for path in spools)


@pytest.mark.parametrize("failure", ["http", "cursor", "malformed"])
def test_raw_operational_failures_do_not_trigger_time_splitting(linked_record, monkeypatch, tmp_path, failure):
    settings, owner = linked_record
    seed(settings, owner, monkeypatch)
    before = snapshot(settings)
    spools = track_spools(monkeypatch, tmp_path)
    calls = []
    def api(_settings, path, params):
        calls.append((params["start_time"], params["end_time"]))
        if failure == "http":
            raise ow.OpenWearablesError("unavailable", status=503)
        if failure == "malformed":
            return {"data": "invalid", "pagination": {"has_more": False}}
        return {"data": [], "pagination": {"has_more": True, "next_cursor": "stuck"}}
    monkeypatch.setattr(ow, "_api", api)
    with pytest.raises(ow.OpenWearablesError):
        hooks.sync_raw_timeseries(settings, owner, "2018-05-24", "2018-05-30")
    assert len(set(calls)) == 1 and len(calls) <= 2
    assert snapshot(settings) == before
    assert spools and not any(path.exists() for path in spools)


def test_over_budget_single_timestamp_fails_without_recursing_or_discarding_previous(linked_record, monkeypatch, tmp_path):
    settings, owner = linked_record
    seed(settings, owner, monkeypatch)
    before = snapshot(settings)
    spools = track_spools(monkeypatch, tmp_path)
    monkeypatch.setattr(ow, "_MAX_PAGES", 2)
    monkeypatch.setattr(ow, "_PAGE_LIMIT", 2)
    calls = []
    def api(_settings, path, params):
        offset = int(params.get("cursor", 0))
        calls.append(params)
        return {"data": [sample(identifier=str(offset + index)) for index in range(2)],
                "pagination": {"has_more": True, "next_cursor": str(offset + 2)}}
    monkeypatch.setattr(ow, "_api", api)
    with pytest.raises(ow.OpenWearablesError, match="timestamp boundary"):
        hooks.sync_raw_timeseries(settings, owner, "2018-05-24", "2018-05-30")
    assert len(calls) == 2 and snapshot(settings) == before
    assert spools and not any(path.exists() for path in spools)


def test_failure_after_first_staged_partition_rolls_back_whole_raw_window(linked_record, monkeypatch, tmp_path):
    settings, owner = linked_record
    seed(settings, owner, monkeypatch)
    before = snapshot(settings)
    spools = track_spools(monkeypatch, tmp_path)
    def fetch(_settings, path, params, *args, **kwargs):
        if params["end_time"] == "2018-05-30T23:59:59.999999Z":
            if params["start_time"] == "2018-05-24T00:00:00Z":
                raise ow.OpenWearablesPageLimitError("budget")
            raise ow.OpenWearablesError("right partition unavailable", status=503)
        return [sample(value=8)]
    monkeypatch.setattr(ow, "_exhaustive_rows", fetch)
    with pytest.raises(ow.OpenWearablesError, match="right partition"):
        hooks.sync_raw_timeseries(settings, owner, "2018-05-24", "2018-05-30")
    assert snapshot(settings) == before
    assert spools and not any(path.exists() for path in spools)


def test_failure_during_daily_commit_rolls_back_raw_and_daily_replacement(linked_record, monkeypatch, tmp_path):
    settings, owner = linked_record
    seed(settings, owner, monkeypatch)
    before = snapshot(settings)
    spools = track_spools(monkeypatch, tmp_path)
    monkeypatch.setattr(ow, "_api", lambda *args: {"data": [sample(value=8)], "pagination": {"has_more": False}})
    original = ow._write_days
    def failed_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("simulated failed commit")
    monkeypatch.setattr(ow, "_write_days", failed_write)
    with pytest.raises(RuntimeError, match="failed commit"):
        hooks.sync_raw_timeseries(settings, owner, "2018-05-24", "2018-05-30")
    assert snapshot(settings) == before
    assert spools and not any(path.exists() for path in spools)


@pytest.mark.parametrize("invalidate", ["lease", "link"])
def test_staged_raw_rechecks_binding_and_lease_before_commit(linked_record, monkeypatch, tmp_path, invalidate):
    settings, owner = linked_record
    seed(settings, owner, monkeypatch)
    before = snapshot(settings)
    spools = track_spools(monkeypatch, tmp_path)
    job = hooks.enqueue_sync(settings, [owner], start="2018-05-24", end="2018-05-30")[0]
    identity = ow.account_identity(settings, owner)
    with connect(settings) as db:
        db.execute("UPDATE openwearables_sync_jobs SET status='running',lease_token='first',lease_until=? WHERE id=?", (time.time()+180, job))
    def intervals(*args):
        yield [sample(value=8)]
        if invalidate == "link":
            ow.link_account(settings, owner, identity[0], "fixture@example.test")
        else:
            with connect(settings) as db:
                db.execute("UPDATE openwearables_sync_jobs SET lease_token='other-worker' WHERE id=?", (job,))
    monkeypatch.setattr(hooks, "_raw_intervals", intervals)
    with pytest.raises(ow.OpenWearablesError):
        hooks.sync_raw_timeseries(settings, owner, "2018-05-24", "2018-05-30", (*identity, job, "first"))
    assert snapshot(settings) == before
    assert spools and not any(path.exists() for path in spools)


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_profile_retry_uses_localized_dataset_label_admin_retains_code(linked_record, locale):
    settings, owner = linked_record
    job = hooks.enqueue_sync(settings, [owner])[0]
    with connect(settings) as db:
        db.execute("UPDATE openwearables_sync_jobs SET status='retry',last_error='raw_timeseries' WHERE id=?", (job,))
    token = activate_locale(locale)
    try:
        environment = Environment(loader=FileSystemLoader(Path(ow.__file__).parent / "web" / "templates"), autoescape=True)
        environment.filters.update(datefmt=str, countfmt=str)
        environment.globals['t'] = t
        template = environment.get_template('_openwearables_status.html')
        context = hooks.operational_status(settings, owner)
        assert context['jobs'][0]['error_labels'] == [t('ow_hooks.raw_dataset')]
        profile = template.render(ow_hooks=context, active='profile')
        assert 'raw_timeseries' not in profile
        assert t('ow_hooks.raw_samples') in profile
        assert '<small>' + t('ow_hooks.raw_dataset') + '</small>' in profile
        assert '\u00a0-\u2060\u00a0' in profile  # the window renders, unbreakable, with a plain hyphen
        assert '\u2013' not in profile
        assert '\u00e2\u20ac' not in profile and '\ufffd' not in profile
        assert 'raw_timeseries' in template.render(ow_hooks=context, active='admin_openwearables')
    finally:
        reset_locale(token)
