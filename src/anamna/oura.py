"""Oura: the API-driven side of the wearable integration.

`integrations.py` owns getting connected (OAuth, webhook receipt); this module
owns what a connection is *for* — pulling every dataset the Oura API serves and
landing it in the same device tables the file importers write, so the existing
/devices pages, trends, source-priority resolution and reference evaluation
all apply unchanged.

The one idea everything here hangs on is the **windowed recompute**.  Every
write goes through :func:`sync_range`: fetch all documents of one data type in
a date window, rebuild the daily rows for the metric keys that data type owns,
upsert them, and delete Oura rows in the window for days the API no longer
reports.  Backfill is that with a window from `EPOCH_DAY` to today; a webhook
event is that with a window around the changed document; a deletion is that
with a wide window.  One code path, idempotent by construction, correct for
Oura's many-sleep-periods-per-day shape — and it never deletes a day it did
not just refetch, so a failed pull changes nothing.

Data types deliberately *not* turned into rows (kept raw in provider_events,
which every webhook already archives): daily_resilience and sleep_time are
enums/recommendations rather than measurements, rest_mode_period is a mode
flag, meal has no numeric contract, and `tag` is superseded by enhanced_tag.
ring_configuration is fetched into the sync-state metadata and shown on the
profile card instead of being charted.

Oura refresh tokens are single-use: the rotated pair is stored *before* the
old one is discarded, under a per-user lock.  A refused refresh marks the
connection `reauthorize` — visible on the profile — rather than failing
silently forever.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, tzinfo

from . import integrations
from .config import Settings, log_run
from .db import connect, transaction, utc_now
from .devices import exclusions
from .devices.catalog import HEALTHKIT_METRICS, SLEEP_METRICS, metric
from .devices.models import Aggregate, DeviceEvent, MetricDefinition, Workout
from .devices.oura_export import SLEEP_KEYS, quarantine_sleep
from .devices.timezone import local_bounds_utc, local_day, user_timezone_for
from .devices.timezone import today as local_today
from .devices.units import finite_number, plausible_aggregates
from .ingest.pipeline import ensure_vendor, stable_id
from .integrations import IntegrationError

logger = logging.getLogger("anamna.oura")

PROVIDER = integrations.PROVIDERS["oura"]
API = "https://api.ouraring.com"
SOURCE_NAME = "Oura"
ADAPTER_KEY = "oura_api"

#: Before the first Oura ring shipped there is nothing to fetch.
EPOCH_DAY = "2015-10-01"

#: A webhook delete event names a document we can no longer fetch, so its day
#: is unknowable; recompute this many days back instead. Deletions of older
#: documents than this are corrected by the next manual sync.
# ponytail: 90-day guess; per-document day bookkeeping would be the upgrade.
DELETE_WINDOW_DAYS = 90

#: The manual "Sync now" window. Backfill already owns history; this heals
#: recent edits and the un-webhooked heart-rate series.
RECENT_WINDOW_DAYS = 30

TOKEN_SLACK_SECONDS = integrations.TOKEN_SLACK_SECONDS

#: Re-check webhook subscriptions at most this often per process.
SUBSCRIPTION_CHECK_SECONDS = 24 * 3600

#: Heart-rate samples arrive every few minutes; fetch history in month-sized
#: bites so no single response is unbounded.  Oura refuses a range longer than
#: 30 days ("Timerange ... less than or equal to 30 days", HTTP 400), and a
#: chunk is requested as whole local days -- N days is N x 24 h -- so 30 is the
#: most it can be.
HEARTRATE_CHUNK_DAYS = 30
_MAX_PAGES = 1000


# --- what each data type becomes ---------------------------------------------

_BY_KEY = {d.key: d for d in {**HEALTHKIT_METRICS, **SLEEP_METRICS}.values()}


def _definition(key: str, name: str, category: str, unit: str, aggregation: str) -> MetricDefinition:
    """The catalog's definition when the key exists there — one spelling of
    name/unit/aggregation per key across every importer — else a new one."""
    return _BY_KEY.get(key) or metric(key, name, category, unit, aggregation)


DEFS = {
    key: _definition(key, name, category, unit, aggregation)
    for key, name, category, unit, aggregation in (
        # Shared keys: the catalog entry wins, these literals are fallbacks.
        ("sleep_duration", "Time asleep", "device_sleep", "hours", "sum"),
        ("sleep_deep", "Deep sleep", "device_sleep", "hours", "sum"),
        ("sleep_rem", "REM sleep", "device_sleep", "hours", "sum"),
        ("sleep_core", "Core sleep", "device_sleep", "hours", "sum"),
        ("sleep_awake", "Awake during sleep", "device_sleep", "hours", "sum"),
        ("time_in_bed", "Time in bed", "device_sleep", "hours", "sum"),
        ("lowest_sleeping_heart_rate", "Lowest sleeping heart rate", "device_recovery", "bpm", "latest"),
        # Oura reports rMSSD, not the SDNN quantity exported by HealthKit.
        ("heart_rate_variability_rmssd", "Heart rate variability (RMSSD)", "device_recovery", "ms", "average"),
        ("respiratory_rate", "Respiratory rate", "device_recovery", "breaths/min", "average"),
        ("blood_oxygen", "Blood oxygen saturation", "device_recovery", "%", "average"),
        ("daily_heart_rate", "Daily heart rate", "device_recovery", "bpm", "average"),
        ("steps", "Daily steps", "device_activity", "steps", "sum"),
        ("active_energy", "Active energy", "device_activity", "kcal", "sum"),
        ("resting_energy", "Resting energy", "device_activity", "kcal", "sum"),
        ("moderate_activity", "Moderate activity", "device_activity", "min", "sum"),
        ("vigorous_activity", "Vigorous activity", "device_activity", "min", "sum"),
        ("vo2_max", "Cardio fitness (VO₂ max)", "device_fitness", "mL/kg/min", "average"),
        # Oura-established keys — spellings must match devices/structured.py.
        ("sleep_score", "Sleep score", "device_sleep", "score", "latest"),
        ("readiness_score", "Readiness score", "device_recovery", "score", "latest"),
        ("activity_score", "Activity score", "device_activity", "score", "latest"),
        ("temperature_deviation", "Temperature deviation", "device_recovery", "°C", "latest"),
        # New with the API integration.
        ("sleep_efficiency", "Sleep efficiency", "device_sleep", "%", "latest"),
        ("breathing_disturbance_index", "Breathing disturbance index", "device_recovery", "per hour", "average"),
        ("stress_high_time", "High stress time", "device_recovery", "min", "latest"),
        ("recovery_high_time", "High recovery time", "device_recovery", "min", "latest"),
        ("cardiovascular_age", "Cardiovascular age", "device_recovery", "years", "latest"),
        ("pulse_wave_velocity", "Pulse wave velocity", "device_recovery", "m/s", "latest"),
    )
}

#: Sleep periods that count as sleep. `rest` is lying down awake; `deleted`
#: is Oura's own tombstone.
_SLEEP_TYPES = {"long_sleep", "sleep", "late_nap"}

#: Which metric keys each data type owns — the delete scope of its recompute.
#: A key must be owned by exactly one data type or two syncs would fight.
DATATYPE_KEYS = {
    "sleep": SLEEP_KEYS,
    "daily_sleep": ("sleep_score",),
    "daily_readiness": ("readiness_score", "temperature_deviation"),
    "daily_activity": (
        "steps", "active_energy", "resting_energy", "activity_score",
        "moderate_activity", "vigorous_activity",
    ),
    "daily_spo2": ("blood_oxygen", "breathing_disturbance_index"),
    "daily_stress": ("stress_high_time", "recovery_high_time"),
    "daily_cardiovascular_age": ("cardiovascular_age", "pulse_wave_velocity"),
    "vo2_max": ("vo2_max",),
}

#: Data types whose documents are periods whose `day` is the *wake* date while
#: the endpoint's date filter matches the period's start: a window opening at
#: day D never contains the night that began on the evening of D-1, so every
#: webhook for the newest night synced nothing (sleep stopped after
#: 2026-11-01 although each event was processed).  Fetched from a day earlier.
PERIOD_DATATYPES = {"sleep"}

#: Webhook data types kept as raw archive only (see module docstring).
RETAINED_ONLY = {"daily_resilience", "sleep_time", "rest_mode_period", "ring_configuration", "meal", "tag"}

#: Everything worth a webhook subscription — each with create/update/delete.
SUBSCRIBED_DATATYPES = tuple(sorted(
    set(DATATYPE_KEYS) | {"workout", "session", "enhanced_tag"} | (RETAINED_ONLY - {"tag"})
))

#: Endpoint path per data type; `vo2_max` is spelled `vO2_max` by the API.
_ENDPOINTS = {**{t: t for t in DATATYPE_KEYS}, "vo2_max": "vO2_max", "workout": "workout",
              "session": "session", "enhanced_tag": "enhanced_tag"}


ReauthorizeError = integrations.ReauthorizeError


# --- authenticated API access ------------------------------------------------
# Token rotation and the 401-retry live in integrations (shared with Garmin);
# these names stay because the rest of this module and its tests use them.

_refresh_locks = integrations._refresh_locks
_expires_in = integrations.expires_in


def _connection(settings: Settings, user_id: str):
    return integrations.require_connection(settings, user_id, "oura")


def _refresh(settings: Settings, user_id: str) -> None:
    integrations.refresh_tokens(settings, user_id, PROVIDER)


def api_get(settings: Settings, user_id: str, path: str, params: dict[str, str] | None = None):
    """One authenticated GET, refreshing the token when stale or refused."""
    url = f"{API}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    return integrations.authorized_request(settings, user_id, PROVIDER, url)


def _paged(settings: Settings, user_id: str, path: str, params: dict[str, str]) -> list[dict]:
    documents: list[dict] = []
    token: str | None = None
    seen: set[str] = set()
    for _ in range(_MAX_PAGES):
        page = api_get(settings, user_id, path, {**params, **({"next_token": token} if token else {})})
        if not isinstance(page, dict):
            raise IntegrationError(f"oura: {path} answered {type(page).__name__}, not a document page")
        batch = page.get("data")
        if not isinstance(batch, list) or any(not isinstance(item, dict) for item in batch):
            raise IntegrationError(f"oura: {path} answered with an invalid data list")
        documents.extend(batch)
        token = page.get("next_token")
        if not token:
            return documents
        if not isinstance(token, str) or token in seen:
            raise IntegrationError(f"oura: {path} pagination did not advance")
        seen.add(token)
    raise IntegrationError(f"oura: {path} exceeded the pagination limit")


def resolve_external_user_id(settings: Settings, user_id: str) -> str:
    """Oura's own id for this account — the `user_id` its webhook events carry."""
    previous = _connection(settings, user_id)
    if _expires_in(previous) <= TOKEN_SLACK_SECONDS:
        _refresh(settings, user_id)
        previous = _connection(settings, user_id)
    payload = api_get(settings, user_id, "/v2/usercollection/personal_info")
    external = str(payload.get("id") or "") if isinstance(payload, dict) else ""
    if external:
        with transaction(settings, immediate=True) as db:
            current = db.execute("SELECT access_token FROM provider_connections WHERE user_id=? AND provider='oura'", (user_id,)).fetchone()
            if current is None or current[0] != previous["access_token"]:
                raise IntegrationError("oura: connection changed during account lookup; retry")
            integrations._reconcile_oura_account(db, user_id, external)
            db.execute(
                "UPDATE provider_connections SET external_user_id=?, updated_at=? WHERE user_id=? AND provider='oura'",
                (external, utc_now(), user_id),
            )
    return external


# --- persistence -------------------------------------------------------------


def _patient_id(settings: Settings, user_id: str) -> str:
    with connect(settings) as db:
        row = db.execute(
            "SELECT id FROM patients WHERE owner_user_id=? ORDER BY created_at LIMIT 1", (user_id,)
        ).fetchone()
    if row is None:
        raise IntegrationError("oura: no patient profile to attach device data to")
    return str(row["id"])


def ensure_envelope(settings: Settings, user_id: str) -> str:
    """The one device_imports row all API-synced rows hang from.

    The file importers fingerprint bytes; an API connection has no bytes, so
    the fingerprint is the account itself and the row doubles as the sync-state
    store (metadata_json: last sync, subscriptions, ring).
    """
    import_id = stable_id("device-import", f"{user_id}:oura_api:api")
    patient_id = _patient_id(settings, user_id)
    with connect(settings) as db:
        vendor_id = ensure_vendor(db, "Oura", "https://ouraring.com/")
        db.execute(
            """INSERT INTO device_imports(
                   id, owner_user_id, patient_id, vendor_id, adapter_key, source_path,
                   source_fingerprint, source_bytes, raw_record_count, status,
                   metadata_json, imported_at)
               VALUES (?, ?, ?, ?, 'oura_api', 'oura://api', 'api', 0, 0, 'complete', '{}', ?)
               ON CONFLICT(owner_user_id, adapter_key, source_fingerprint) DO NOTHING""",
            (import_id, user_id, patient_id, vendor_id, utc_now()),
        )
        row = db.execute("SELECT external_user_id FROM provider_connections WHERE user_id=? AND provider='oura'", (user_id,)).fetchone()
        if row:
            integrations._reconcile_oura_account(db, user_id, str(row[0] or ""))
    return import_id


def sync_state(settings: Settings, user_id: str) -> dict:
    with connect(settings) as db:
        row = db.execute(
            "SELECT metadata_json FROM device_imports WHERE owner_user_id=? AND adapter_key='oura_api'",
            (user_id,),
        ).fetchone()
    try:
        return json.loads(row["metadata_json"]) if row else {}
    except json.JSONDecodeError:
        return {}


def _update_state(settings: Settings, user_id: str, **values: object) -> None:
    with transaction(settings, immediate=True) as db:
        row = db.execute("SELECT metadata_json FROM device_imports WHERE owner_user_id=? AND adapter_key='oura_api'", (user_id,)).fetchone()
        state = {**(json.loads(row[0]) if row else {}), **values}
        db.execute(
            """UPDATE device_imports SET metadata_json=?, imported_at=?,
                      raw_record_count=(SELECT COUNT(*) FROM device_metric_days WHERE import_id=device_imports.id)
                WHERE owner_user_id=? AND adapter_key='oura_api'""",
            (json.dumps(state, ensure_ascii=False), utc_now(), user_id),
        )


def _write_days(settings: Settings, user_id: str, import_id: str,
                build: Callable[[], list[Aggregate]], owned_keys: tuple[str, ...],
                start: str, end: str, expected_account: str) -> int:
    """Upsert the recomputed days, then drop Oura days in the window the API no
    longer reports. Runs only after the whole window was fetched successfully.

    ``build`` maps the fetched documents; it runs inside the write transaction
    under the person's "not my reading" rules, so a rule saved during the
    fetch is applied, and one saved after this commit rebuilds the window."""
    patient_id = _patient_id(settings, user_id)
    now = utc_now()
    with transaction(settings, immediate=True) as db:
        _check_sync_account(db, user_id, expected_account)
        with exclusions.applying(db, user_id, ADAPTER_KEY):
            aggregates = build()
        # Withheld values are absent from fresh_days, so a stale stored copy of
        # them is deleted below rather than left standing.
        # Quarantine first: an over-long night withholds every metric of that
        # night (HRV included), and the plain plausibility filter would otherwise
        # drop the sleep total alone and leave the night's other metrics standing.
        kept, quarantined = quarantine_sleep(aggregates)
        aggregates = plausible_aggregates(kept)
        if quarantined:
            logger.warning("oura: withheld implausible sleep days %s", quarantined)
        fresh_days = {(item.definition.key, item.day) for item in aggregates}
        db.executemany(
            """INSERT INTO device_metric_days(
                   id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                   metric_key, metric_name, category, day, aggregation, unit, value,
                   value_min, value_max, value_sum, sample_count, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(owner_user_id, source_name, metric_key, day) DO UPDATE SET
                   patient_id=excluded.patient_id, import_id=excluded.import_id,
                   source_vendor=excluded.source_vendor, metric_name=excluded.metric_name,
                   category=excluded.category, aggregation=excluded.aggregation,
                   unit=excluded.unit, value=excluded.value, value_min=excluded.value_min,
                   value_max=excluded.value_max, value_sum=excluded.value_sum,
                   sample_count=excluded.sample_count, created_at=excluded.created_at""",
            [
                (
                    stable_id("device-metric-day", f"{user_id}:{item.source_name}:{item.definition.key}:{item.day}"),
                    user_id, patient_id, import_id, item.source_name, item.source_vendor,
                    item.definition.key, item.definition.name, item.definition.category, item.day,
                    item.definition.aggregation, item.definition.unit, item.value,
                    item.value_min, item.value_max, item.value_sum, item.sample_count, now,
                )
                for item in aggregates
            ],
        )
        removed = 0
        for key in owned_keys:
            days = [day for metric_key, day in fresh_days if metric_key == key]
            placeholders = ",".join("?" for _ in days)
            # Scoped to rows this envelope owns: a day that came from a *file*
            # export (same source_name "Oura") and is absent from the API —
            # older than API retention, or a previous account — must survive.
            # Overlapping days flip to this import_id on upsert, so the API
            # remains authoritative for everything it actually reports.
            removed += db.execute(
                f"""DELETE FROM device_metric_days
                     WHERE owner_user_id=? AND source_name=? AND metric_key=?
                       AND import_id=? AND day BETWEEN ? AND ?
                       {f"AND day NOT IN ({placeholders})" if days else ""}""",
                (user_id, SOURCE_NAME, key, import_id, start, end, *days),
            ).rowcount
    if removed:
        logger.info("oura: removed %d stale day(s) for %s in %s..%s", removed, owned_keys, start, end)
    return len(aggregates)


# --- mapping one data type's documents into daily rows ------------------------


def _num(value: object) -> float | None:
    return finite_number(value)


def _aggregate(bucket: dict, key: str, day: str, value: float | None, observed: str = "") -> None:
    # The day-length guard here, not only in the mappers: a heart-rate sample
    # with a null timestamp would otherwise write a day='' row that the
    # BETWEEN-scoped delete never removes and the detail page cannot parse.
    if value is None or len(day) != 10:
        return
    definition = DEFS[key]
    item = bucket.get((key, day))
    if item is None:
        item = Aggregate(definition, day, SOURCE_NAME, SOURCE_NAME)
        bucket[(key, day)] = item
    item.add(value, observed or day)


def _scaled(document: dict, field: str, scale: float = 1.0) -> float | None:
    value = _num(document.get(field))
    return value * scale if value is not None else None


_SLEEP_FIELDS = (
    ("total_sleep_duration", "sleep_duration"),
    ("deep_sleep_duration", "sleep_deep"),
    ("rem_sleep_duration", "sleep_rem"),
    ("light_sleep_duration", "sleep_core"),
    ("awake_time", "sleep_awake"),
)


def _sleep_periods_by_day(documents: list[dict]) -> dict[str, list[dict]]:
    by_day: dict[str, list[dict]] = {}
    for document in documents:
        day = str(document.get("day") or "")[:10]
        if len(day) == 10 and str(document.get("type") or "") != "deleted":
            by_day.setdefault(day, []).append(document)
    return by_day


def _map_sleep(documents: list[dict], bucket: dict) -> None:
    for day, periods in _sleep_periods_by_day(documents).items():
        asleep = [p for p in periods if str(p.get("type") or "") in _SLEEP_TYPES]
        for field, key in _SLEEP_FIELDS:
            for period in asleep:
                _aggregate(bucket, key, day, _scaled(period, field, 1 / 3600),
                           str(period.get("bedtime_start") or day))
        for period in periods:
            _aggregate(bucket, "time_in_bed", day, _scaled(period, "time_in_bed", 1 / 3600),
                       str(period.get("bedtime_start") or day))
        _map_sleep_summary(bucket, day, asleep)


def _map_sleep_summary(bucket: dict, day: str, asleep: list[dict]) -> None:
    lows = [value for value in (_num(p.get("lowest_heart_rate")) for p in asleep) if value]
    if lows:
        _aggregate(bucket, "lowest_sleeping_heart_rate", day, min(lows))
    main = max(asleep, key=lambda p: _num(p.get("total_sleep_duration")) or 0.0, default=None)
    if main is not None:
        _aggregate(bucket, "heart_rate_variability_rmssd", day, _num(main.get("average_hrv")))
        _aggregate(bucket, "respiratory_rate", day, _num(main.get("average_breath")))
        _aggregate(bucket, "sleep_efficiency", day, _num(main.get("efficiency")))


def _map_scalar_fields(fields: tuple[tuple[str, str, float], ...]):
    def mapper(documents: list[dict], bucket: dict) -> None:
        for document in documents:
            day = str(document.get("day") or "")[:10]
            if len(day) != 10:
                continue
            for field, key, scale in fields:
                _aggregate(bucket, key, day, _scaled(document, field, scale))
    return mapper


def _map_daily_activity(documents: list[dict], bucket: dict) -> None:
    for document in documents:
        day = str(document.get("day") or "")[:10]
        if len(day) != 10:
            continue
        _aggregate(bucket, "steps", day, _scaled(document, "steps"))
        _aggregate(bucket, "activity_score", day, _scaled(document, "score"))
        _aggregate(bucket, "moderate_activity", day, _scaled(document, "medium_activity_time", 1 / 60))
        _aggregate(bucket, "vigorous_activity", day, _scaled(document, "high_activity_time", 1 / 60))
        active = _num(document.get("active_calories"))
        total = _num(document.get("total_calories"))
        _aggregate(bucket, "active_energy", day, active)
        if active is not None and total is not None and total >= active:
            _aggregate(bucket, "resting_energy", day, total - active)


def _map_daily_spo2(documents: list[dict], bucket: dict) -> None:
    for document in documents:
        day = str(document.get("day") or "")[:10]
        if len(day) != 10:
            continue
        percentage = document.get("spo2_percentage")
        if isinstance(percentage, dict):
            _aggregate(bucket, "blood_oxygen", day, _num(percentage.get("average")))
        _aggregate(bucket, "breathing_disturbance_index", day, _num(document.get("breathing_disturbance_index")))


_MAPPERS = {
    "sleep": _map_sleep,
    "daily_sleep": _map_scalar_fields((("score", "sleep_score", 1),)),
    "daily_readiness": _map_scalar_fields(
        (("score", "readiness_score", 1), ("temperature_deviation", "temperature_deviation", 1))
    ),
    "daily_activity": _map_daily_activity,
    "daily_spo2": _map_daily_spo2,
    "daily_stress": _map_scalar_fields(
        (("stress_high", "stress_high_time", 1 / 60), ("recovery_high", "recovery_high_time", 1 / 60))
    ),
    "daily_cardiovascular_age": _map_scalar_fields(
        (("vascular_age", "cardiovascular_age", 1), ("pulse_wave_velocity", "pulse_wave_velocity", 1))
    ),
    "vo2_max": _map_scalar_fields((("vo2_max", "vo2_max", 1),)),
}


# --- sync: the windowed recompute --------------------------------------------


def _sync_account(settings: Settings, user_id: str) -> str:
    external = str(_connection(settings, user_id)["external_user_id"] or "")
    if not external:
        external = resolve_external_user_id(settings, user_id)
    if not external:
        raise IntegrationError("oura: unable to confirm the connected account")
    return external


def _check_sync_account(db, user_id: str, expected: str) -> None:
    row = db.execute("SELECT external_user_id FROM provider_connections WHERE user_id=? AND provider='oura'", (user_id,)).fetchone()
    if row is None or str(row[0]) != expected:
        raise IntegrationError("oura: connected account changed during sync; retry for the current account")


def _next_day(day: str) -> str:
    """Oura treats end_date as exclusive: a window ending today, asked for
    as-is, never contains today's documents (the 2026-08-07 backfill at 09:42
    Kyiv stopped at 08-06 for every daily key)."""
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def _previous_day(day: str) -> str:
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def sync_range(settings: Settings, user_id: str, data_type: str, start: str, end: str) -> int:
    """Fetch one data type for [start, end] and make the stored days match."""
    mapper = _MAPPERS[data_type]
    import_id = ensure_envelope(settings, user_id)
    expected_account = _sync_account(settings, user_id)
    fetch_start = _previous_day(start) if data_type in PERIOD_DATATYPES and start > EPOCH_DAY else start
    # Kept to [start, end] by Oura's own `day`: the extra day fetched for a
    # period type holds only part of start-1 (its night began on start-2),
    # and writing that would overwrite a complete day with a partial one.
    documents = [
        document for document in _paged(
            settings, user_id, f"/v2/usercollection/{_ENDPOINTS[data_type]}",
            {"start_date": fetch_start, "end_date": _next_day(end)},
        )
        if start <= str(document.get("day") or "")[:10] <= end
    ]
    def build() -> list[Aggregate]:
        bucket: dict[tuple[str, str], Aggregate] = {}
        mapper(documents, bucket)
        return list(bucket.values())

    return _write_days(settings, user_id, import_id, build, DATATYPE_KEYS[data_type], start, end, expected_account)


def sync_heartrate(settings: Settings, user_id: str, start: str, end: str) -> int:
    """The continuous bpm series, aggregated per day. No webhook exists for it,
    so it rides along with every other sync, chunked month by month."""
    import_id = ensure_envelope(settings, user_id)
    expected_account = _sync_account(settings, user_id)
    tz = user_timezone_for(settings, user_id)
    written = 0
    chunk_start = date.fromisoformat(start)
    final = date.fromisoformat(end)
    while chunk_start <= final:
        chunk_end = min(chunk_start + timedelta(days=HEARTRATE_CHUNK_DAYS - 1), final)
        first, last = chunk_start.isoformat(), chunk_end.isoformat()
        # The whole local days, not UTC days: in Kyiv a UTC window starts two
        # to three hours late and every boundary day was written half-empty.
        window_start, window_end = local_bounds_utc(first, last, tz)
        rows = _paged(
            settings, user_id, "/v2/usercollection/heartrate",
            {"start_datetime": _seconds(window_start), "end_datetime": _seconds(window_end)},
        )
        def build(rows=rows, first=first, last=last) -> list[Aggregate]:
            bucket: dict[tuple[str, str], Aggregate] = {}
            for row in rows:
                stamp = str(row.get("timestamp") or "")
                day = local_day(stamp, tz)
                # A sample on the closing instant belongs to the next chunk.
                if first <= day <= last:
                    _aggregate(bucket, "daily_heart_rate", day, _num(row.get("bpm")), stamp)
            return list(bucket.values())

        written += _write_days(settings, user_id, import_id, build, ("daily_heart_rate",), first, last,
                               expected_account)
        chunk_start = chunk_end + timedelta(days=1)
    return written


def _seconds(stamp: str) -> str:
    """An ISO instant without the microseconds, the shape Oura documents."""
    return datetime.fromisoformat(stamp).isoformat(timespec="seconds")


def _document_local_day(document: dict, stamp: str, tz: tzinfo) -> str:
    """Oura's own `day` (its local day, the one the date filter used), else
    the timestamp's day in the person's zone."""
    day = str(document.get("day") or document.get("start_day") or "")[:10]
    return day if len(day) == 10 else local_day(stamp, tz)


def _iso_minutes(start: str, end: str) -> float | None:
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60
    except (TypeError, ValueError):
        return None


def _started_documents(settings: Settings, user_id: str, path: str, window: dict, tz: tzinfo, end: str,
                       start_fields: tuple[str, ...]):
    """Documents of one collection that started on or before `end`, with their start stamp."""
    for document in _paged(settings, user_id, path, window):
        started = ""
        for field in start_fields:
            started = str(document.get(field) or "")
            if started:
                break
        if started and _document_local_day(document, started, tz) <= end:
            yield document, started


def _workout_documents(settings: Settings, user_id: str, window: dict, tz: tzinfo, end: str) -> list[Workout]:
    workouts: list[Workout] = []
    for document, started in _started_documents(settings, user_id, "/v2/usercollection/workout", window, tz, end,
                                                ("start_datetime",)):
        ended = str(document.get("end_datetime") or "") or None
        distance = _num(document.get("distance"))
        workouts.append(Workout(
            source_name=SOURCE_NAME, source_vendor=SOURCE_NAME,
            workout_type=str(document.get("activity") or "workout"),
            started_at=started, ended_at=ended,
            duration_minutes=_iso_minutes(started, ended) if ended else None,
            energy_kcal=_num(document.get("calories")),
            distance_km=distance / 1000 if distance is not None else None,
        ))
    return workouts


def _session_documents(settings: Settings, user_id: str, window: dict, tz: tzinfo, end: str) -> list[Workout]:
    workouts: list[Workout] = []
    for document, started in _started_documents(settings, user_id, "/v2/usercollection/session", window, tz, end,
                                                ("start_datetime",)):
        ended = str(document.get("end_datetime") or "") or None
        workouts.append(Workout(
            source_name=SOURCE_NAME, source_vendor=SOURCE_NAME,
            workout_type=str(document.get("type") or "session"),
            started_at=started, ended_at=ended,
            duration_minutes=_iso_minutes(started, ended) if ended else None,
        ))
    return workouts


def _tag_documents(settings: Settings, user_id: str, window: dict, tz: tzinfo, end: str) -> list[DeviceEvent]:
    events: list[DeviceEvent] = []
    for document, started in _started_documents(settings, user_id, "/v2/usercollection/enhanced_tag", window, tz, end,
                                                ("start_time", "start_day")):
        text = ": ".join(part for part in (
            str(document.get("custom_name") or document.get("tag_type_code") or "tag"),
            str(document.get("comment") or ""),
        ) if part)
        events.append(DeviceEvent(
            source_name=SOURCE_NAME, source_vendor=SOURCE_NAME, event_type="Oura tag",
            started_at=started, ended_at=str(document.get("end_time") or "") or None,
            value_text=text,
        ))
    return events


def sync_workouts(settings: Settings, user_id: str, start: str, end: str) -> int:
    """Atomically reconcile workouts, sessions and tags after fetching all three."""
    patient_id = _patient_id(settings, user_id)
    import_id = ensure_envelope(settings, user_id)
    expected_account = _sync_account(settings, user_id)
    tz = user_timezone_for(settings, user_id)
    # Oura's end_date is exclusive: ask for the day after and keep [start, end].
    window = {"start_date": start, "end_date": _next_day(end)}
    workouts = _workout_documents(settings, user_id, window, tz, end)
    workouts += _session_documents(settings, user_id, window, tz, end)
    events = _tag_documents(settings, user_id, window, tz, end)
    now = utc_now()
    with transaction(settings, immediate=True) as db:
        _check_sync_account(db, user_id, expected_account)
        # The person's rules, read in the transaction that writes the window.
        rules = exclusions.matcher(db, user_id, ADAPTER_KEY)
        if rules is not None:
            workouts = [w for w in workouts if not rules.excludes(w.source_name, exclusions.WORKOUTS, w.started_at, w.ended_at)]
            events = [e for e in events if not rules.excludes(e.source_name, exclusions.EVENTS, e.started_at, e.ended_at)]
        for table in ("device_workouts", "device_events"):
            db.execute(
                f"DELETE FROM {table} WHERE owner_user_id=? AND import_id=? AND substr(started_at, 1, 10) BETWEEN ? AND ?",
                (user_id, import_id, start, end),
            )
        db.executemany(
            """INSERT INTO device_workouts(
                   id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                   workout_type, started_at, ended_at, duration_minutes, energy_kcal,
                   distance_km, route_file, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(owner_user_id, source_name, workout_type, started_at) DO UPDATE SET
                   patient_id=excluded.patient_id, import_id=excluded.import_id,
                   source_vendor=excluded.source_vendor, ended_at=excluded.ended_at,
                   duration_minutes=excluded.duration_minutes, energy_kcal=excluded.energy_kcal,
                   distance_km=excluded.distance_km, created_at=excluded.created_at""",
            [
                (
                    stable_id("device-workout", f"{user_id}:{w.source_name}:{w.workout_type}:{w.started_at}"),
                    user_id, patient_id, import_id, w.source_name, w.source_vendor,
                    w.workout_type, w.started_at, w.ended_at, w.duration_minutes,
                    w.energy_kcal, w.distance_km, None, now,
                )
                for w in workouts
            ],
        )
        db.executemany(
            """INSERT INTO device_events(
                   id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                   event_type, started_at, ended_at, value_text, value_numeric, unit,
                   source_file, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(owner_user_id, event_type, started_at, source_name) DO UPDATE SET
                   patient_id=excluded.patient_id, import_id=excluded.import_id,
                   source_vendor=excluded.source_vendor, ended_at=excluded.ended_at,
                   value_text=excluded.value_text, created_at=excluded.created_at""",
            [
                (
                    stable_id("device-event", f"{user_id}:{e.event_type}:{e.started_at}:{e.source_name}"),
                    user_id, patient_id, import_id, e.source_name, e.source_vendor,
                    e.event_type, e.started_at, e.ended_at, e.value_text, None, None, None, now,
                )
                for e in events
            ],
        )
    return len(workouts) + len(events)


def _fetch_ring(settings: Settings, user_id: str) -> None:
    try:
        documents = _paged(settings, user_id, "/v2/usercollection/ring_configuration", {})
    except IntegrationError as exc:
        logger.warning("oura: ring configuration fetch failed: %s", exc)
        return
    newest = documents[-1] if documents else {}
    _update_state(settings, user_id, ring={
        "hardware_type": str(newest.get("hardware_type") or ""),
        "size": newest.get("size"),
        "firmware_version": str(newest.get("firmware_version") or ""),
        "set_up_at": str(newest.get("set_up_at") or ""),
    } if newest else {})


# --- the three entry points: backfill, webhook processing, manual sync --------


def _today(tz: tzinfo | None = None) -> str:
    """Today in the person's zone. A UTC today ends the window a day short
    between local midnight and UTC midnight, hiding the night just ended."""
    return local_today(tz)


def _days_before(day: str, days: int) -> str:
    return (date.fromisoformat(day) - timedelta(days=days)).isoformat()


def backfill(settings: Settings, user_id: str) -> dict[str, int]:
    """Everything the API holds, from before the first ring shipped to today.
    Per-type independence: one failing dataset must not cost the other nine."""
    ensure_envelope(settings, user_id)
    try:
        resolve_external_user_id(settings, user_id)
    except IntegrationError as exc:
        # Each dataset confirms the account itself before writing; one failed
        # lookup must not abort the whole backfill without a recorded reason.
        logger.warning("oura: account lookup before backfill failed: %s", exc)
    _fetch_ring(settings, user_id)
    counts: dict[str, int] = {}
    # A log line is invisible to the person; failed_datatypes lands in the
    # envelope metadata so /devices can say which datasets never arrived.
    failed: dict[str, str] = {}
    today = _today(user_timezone_for(settings, user_id))
    for data_type in _MAPPERS:
        try:
            counts[data_type] = sync_range(settings, user_id, data_type, EPOCH_DAY, today)
        except IntegrationError as exc:
            failed[data_type] = str(exc)[:200]
            logger.warning("oura: backfill of %s failed: %s", data_type, exc)
    try:
        counts["workouts"] = sync_workouts(settings, user_id, EPOCH_DAY, today)
    except IntegrationError as exc:
        failed["workouts"] = str(exc)[:200]
        logger.warning("oura: backfill of workouts failed: %s", exc)
    try:
        counts["heartrate"] = sync_heartrate(settings, user_id, EPOCH_DAY, today)
    except IntegrationError as exc:
        failed["heartrate"] = str(exc)[:200]
        logger.warning("oura: backfill of heart rate failed: %s", exc)
    _update_state(settings, user_id, last_backfill_at=utc_now(), last_sync_at=utc_now(),
                  last_recent_sync_at=utc_now(), backfill_counts=counts, failed_datatypes=failed)
    return counts


def sync_recent(settings: Settings, user_id: str) -> dict[str, int]:
    """The manual button: the recent window, every dataset, plus subscriptions."""
    today = _today(user_timezone_for(settings, user_id))
    start = _days_before(today, RECENT_WINDOW_DAYS)
    counts: dict[str, int] = {}
    # Written even when empty: a clean sync clears failures recorded earlier.
    failed: dict[str, str] = {}
    for data_type in _MAPPERS:
        try:
            counts[data_type] = sync_range(settings, user_id, data_type, start, today)
        except IntegrationError as exc:
            failed[data_type] = str(exc)[:200]
            logger.warning("oura: sync of %s failed: %s", data_type, exc)
    # Separate guards: heart rate has no webhook, so this button is its only
    # healing path and a workouts failure must not take it down too.
    try:
        counts["workouts"] = sync_workouts(settings, user_id, start, today)
    except IntegrationError as exc:
        failed["workouts"] = str(exc)[:200]
        logger.warning("oura: workout sync failed: %s", exc)
    try:
        counts["heartrate"] = sync_heartrate(settings, user_id, start, today)
    except IntegrationError as exc:
        failed["heartrate"] = str(exc)[:200]
        logger.warning("oura: heart-rate sync failed: %s", exc)
    _fetch_ring(settings, user_id)
    ensure_subscriptions(settings, force=True)
    _update_state(settings, user_id, last_sync_at=utc_now(), last_recent_sync_at=utc_now(),
                  failed_datatypes=failed)
    return counts


def resync_window(settings: Settings, user_id: str, start: str, end: str) -> dict[str, int]:
    """Fetch and rewrite every dataset for [start, end] after the person's
    "not my reading" rules changed.  Oura keeps no local copy of its
    documents, so its own windowed sync is the rebuild; nothing is fetched for
    an account that is no longer connected."""
    if not integrations.connection_row(settings, user_id, "oura"):
        return {}
    start = max(start, EPOCH_DAY)
    end = min(end, _today(user_timezone_for(settings, user_id)))
    if start > end:
        return {}
    counts: dict[str, int] = {}
    steps = [(data_type, lambda data_type=data_type: sync_range(settings, user_id, data_type, start, end))
             for data_type in _MAPPERS]
    steps += [("workouts", lambda: sync_workouts(settings, user_id, start, end)),
              ("heartrate", lambda: sync_heartrate(settings, user_id, start, end))]
    for name, step in steps:
        try:
            counts[name] = step()
        except IntegrationError as exc:
            logger.warning("oura: rebuild of %s after an exclusion failed: %s", name, exc)
    return counts


_WORKOUT_TYPES = ("workout", "session", "enhanced_tag")


def _widen_window(windows: dict[tuple[str, str], str], key: tuple[str, str], day: str) -> None:
    if key not in windows:
        windows[key] = day
    elif not day or not windows[key]:
        windows[key] = ""  # a delete anywhere widens the whole slot
    else:
        windows[key] = min(windows[key], day)


def _plan_events(settings: Settings, rows, connections: dict[str, str]):
    """Fold event rows into (user, slot) -> earliest changed day ('' = wide
    window), which slot each event row belongs to (None = nothing to sync,
    mark it anyway), and the users to ride heart rate along for."""
    windows: dict[tuple[str, str], str] = {}
    row_slots: dict[int, tuple[str, str] | None] = {}
    heartrate_users: set[str] = set()
    for row in rows:
        row_slots[int(row["id"])] = None
        try:
            event = json.loads(str(row["payload"]))
        except json.JSONDecodeError:
            continue
        user_id = connections.get(str(event.get("user_id") or ""))
        data_type = str(event.get("data_type") or "")
        if not user_id or (data_type not in _MAPPERS and data_type not in _WORKOUT_TYPES):
            continue
        heartrate_users.add(user_id)
        slot = "workouts" if data_type in _WORKOUT_TYPES else data_type
        row_slots[int(row["id"])] = (user_id, slot)
        day = ""
        if str(event.get("event_type") or "") in ("create", "update"):
            day = _document_day(settings, user_id, data_type, str(event.get("object_id") or ""))
        _widen_window(windows, (user_id, slot), day)
    return windows, row_slots, heartrate_users


def _sync_windows(settings: Settings, windows: dict[tuple[str, str], str], zones: dict,
                  reauth: set[str]) -> tuple[dict[tuple[str, str], tuple[str, bool]], set[tuple[str, str]]]:
    """Sync each (user, slot) window. Returns the slots that failed, mapped to the
    exception class name and whether it is a provider/network failure (IntegrationError),
    and the slots held back because their account needs
    re-authorization (`reauth` holds those users, and grows as refusals are seen):
    held slots are not called again in this pass and count no attempt."""
    failed: dict[tuple[str, str], tuple[str, bool]] = {}
    held: set[tuple[str, str]] = set()
    for (user_id, slot), earliest in windows.items():
        if user_id in reauth:
            held.add((user_id, slot))
            continue
        today = _today(zones[user_id])
        start = min(earliest or _days_before(today, DELETE_WINDOW_DAYS), today)
        try:
            if slot == "workouts":
                sync_workouts(settings, user_id, start, today)
            else:
                sync_range(settings, user_id, slot, start, today)
        except Exception as exc:  # noqa: BLE001 — one account's failure must not hold up the others
            # Leave this slot's events unprocessed: Oura never redelivers an
            # event we answered 200, so stamping it here would make a transient
            # outage permanent — a deletion at Oura displayed as real forever.
            failed[(user_id, slot)] = (type(exc).__name__, isinstance(exc, IntegrationError))
            if isinstance(exc, ReauthorizeError):
                reauth.add(user_id)
            logger.warning("oura: processing %s for a user failed, will retry: %s", slot, type(exc).__name__)
    return failed, held


def _heartrate_ride_along(settings: Settings, users: set[str], zones: dict) -> None:
    for user_id in users:
        today = _today(zones[user_id])
        try:
            sync_heartrate(settings, user_id, _days_before(today, 3), today)
        except Exception as exc:  # noqa: BLE001 — a heart-rate failure must not hold up the queue
            logger.warning("oura: heart-rate ride-along failed: %s", type(exc).__name__)
        _update_state(settings, user_id, last_sync_at=utc_now())


#: A delivery whose window keeps failing inside this application's own code is set aside after this many tries.
MAX_EVENT_ATTEMPTS = 5
#: A delivery that fails because the provider could not be reached or answered an error is retried for about a day of scheduler passes before it is set aside; one that fails inside this application's own code is set aside after MAX_EVENT_ATTEMPTS, because retrying cannot change the outcome.
MAX_TRANSIENT_ATTEMPTS = 300
def _record_failure(db, row_id: int, error: str, transient: bool) -> None:
    """Count one failed try under the exception class name only. A provider or network
    failure (``transient``) sets the delivery aside at MAX_TRANSIENT_ATTEMPTS, any other
    at MAX_EVENT_ATTEMPTS (processed_at stamped) so it stops being retried."""
    db.execute("UPDATE provider_events SET attempts=attempts+1, last_error=? WHERE id=?", (error, row_id))
    attempts = int(db.execute("SELECT attempts FROM provider_events WHERE id=?", (row_id,)).fetchone()[0])
    limit = MAX_TRANSIENT_ATTEMPTS if transient else MAX_EVENT_ATTEMPTS
    if attempts >= limit:
        db.execute("UPDATE provider_events SET processed_at=? WHERE id=?", (utc_now(), row_id))
        logger.warning("oura: delivery %s set aside after %s attempts: %s", row_id, attempts, error)


def process_pending(settings: Settings) -> int:
    """Turn archived webhook events into synced windows, then mark them done.

    Events name a document id, not a day, so create/update fetches the single
    document to learn which day changed; a delete (or a fetch that 404s) widens
    the window to DELETE_WINDOW_DAYS. Unknown users (disconnected since) and
    retained-only data types are marked processed without a sync. A window that
    fails leaves its events pending, counted against MAX_TRANSIENT_ATTEMPTS when
    the provider or network failed and MAX_EVENT_ATTEMPTS when this application's
    own code did.
    """
    with connect(settings) as db:
        rows = db.execute(
            "SELECT id, payload FROM provider_events WHERE provider='oura' AND processed_at IS NULL AND attempts<? ORDER BY id",
            (MAX_TRANSIENT_ATTEMPTS,),
        ).fetchall()
        connections = {
            str(row["external_user_id"]): str(row["user_id"])
            for row in db.execute(
                "SELECT user_id, external_user_id FROM provider_connections WHERE provider='oura' AND external_user_id<>''"
            )
        }
        reauth = {str(row[0]) for row in db.execute(
            "SELECT user_id FROM provider_connections WHERE provider='oura' AND status='reauthorize'"
        )}
    if not rows:
        return 0
    windows, row_slots, heartrate_users = _plan_events(settings, rows, connections)
    zones = {user_id: user_timezone_for(settings, user_id) for user_id in heartrate_users}
    failed, held = _sync_windows(settings, windows, zones, reauth)
    _heartrate_ride_along(settings, heartrate_users, zones)
    now = utc_now()
    done: list[int] = []
    with connect(settings) as db:
        for row_id, slot in row_slots.items():
            if slot is None:
                done.append(row_id)
            elif slot in failed:
                error, transient = failed[slot]
                _record_failure(db, row_id, error, transient)
            elif slot not in held:
                done.append(row_id)
        db.executemany(
            "UPDATE provider_events SET processed_at=? WHERE id=?",
            [(now, row_id) for row_id in done],
        )
    ensure_subscriptions(settings)
    return len(done)


def _document_day(settings: Settings, user_id: str, data_type: str, object_id: str) -> str:
    if not object_id or data_type not in _ENDPOINTS:
        return ""
    try:
        payload = api_get(settings, user_id, f"/v2/usercollection/{_ENDPOINTS[data_type]}/{object_id}")
    except IntegrationError:
        return ""  # deleted since, or transient — the wide window covers it
    day = str(payload.get("day") or payload.get("start_day") or "")[:10] if isinstance(payload, dict) else ""
    return day if len(day) == 10 else ""


# --- webhook subscriptions ---------------------------------------------------

_last_subscription_check = 0.0


def _reconcile_subscriptions(url: str, headers: dict, callback: str, token: str):
    """Delete strays and duplicates, create what is missing, renew what expires within a week."""
    existing = integrations._request(url, headers=headers)
    if isinstance(existing, dict):
        existing = existing.get("data") or []
    if not isinstance(existing, list):
        raise IntegrationError(f"oura: subscription list answered {type(existing).__name__}")
    keep: dict[tuple[str, str], dict] = {}
    for subscription in existing:
        slot = (str(subscription.get("data_type")), str(subscription.get("event_type")))
        if str(subscription.get("callback_url")) != callback or slot in keep:
            integrations._request(f"{url}/{subscription.get('id')}", headers=headers, method="DELETE")
        else:
            keep[slot] = subscription
    soon = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    created = renewed = 0
    for data_type in SUBSCRIBED_DATATYPES:
        for event_type in ("create", "update", "delete"):
            action = _sync_subscription_slot(url, headers, callback, token, soon,
                                             keep.get((data_type, event_type)), data_type, event_type)
            created += action == "created"
            renewed += action == "renewed"
    return keep, created, renewed


def _sync_subscription_slot(url: str, headers: dict, callback: str, token: str, soon: str,
                            subscription: dict | None, data_type: str, event_type: str) -> str:
    """Create a missing subscription or renew one expiring by `soon`; says which."""
    if subscription is None:
        integrations._request(url, headers=headers, method="POST", json_data={
            "callback_url": callback, "verification_token": token,
            "event_type": event_type, "data_type": data_type,
        })
        return "created"
    if str(subscription.get("expiration_time") or "") <= soon:
        integrations._request(
            f"{url}/renew/{subscription.get('id')}", headers=headers, method="PUT"
        )
        return "renewed"
    return ""


def ensure_subscriptions(settings: Settings, force: bool = False) -> dict[str, object]:
    """Create what is missing, renew what is expiring, for every data type.

    Only meaningful where Oura can reach us: without a configured public URL
    (local development) this reports why and does nothing. Oura verifies the
    callback with a challenge GET at creation time, so the URL must be served
    by *this* application with *this* verification token when it runs.
    """
    global _last_subscription_check
    if not force and time.monotonic() - _last_subscription_check < SUBSCRIPTION_CHECK_SECONDS:
        return {"skipped": "checked recently"}
    base = integrations.integration_settings(settings)["integrations_public_url"]
    client_id, client_secret = integrations.client_config(settings, PROVIDER)
    if not base:
        return _note_subscriptions(settings, {"active": 0, "reason": "no_public_url", "checked_at": utc_now()})
    if not client_id:
        return {"skipped": "unconfigured"}
    _last_subscription_check = time.monotonic()
    callback = f"{base.rstrip('/')}/integrations/oura/webhook"
    token = integrations.ensure_oura_verification_token(settings)
    headers = {"x-client-id": client_id, "x-client-secret": client_secret}
    url = f"{API}/v2/webhook/subscription"
    try:
        keep, created, renewed = _reconcile_subscriptions(url, headers, callback, token)
        status = {"active": len(keep) + created, "created": created, "renewed": renewed,
                  "checked_at": utc_now()}
    except IntegrationError as exc:
        logger.warning("oura: subscription upkeep failed: %s", exc)
        status = {"active": None, "reason": str(exc)[:200], "checked_at": utc_now()}
    return _note_subscriptions(settings, status)


def _note_subscriptions(settings: Settings, status: dict) -> dict:
    with connect(settings) as db:
        users = [str(row["user_id"]) for row in db.execute(
            "SELECT user_id FROM provider_connections WHERE provider='oura'"
        )]
    for user_id in users:
        try:
            _update_state(settings, user_id, subscriptions=status)
        except IntegrationError:
            pass  # no envelope yet — first backfill will create it
    return status


# --- background entry points (the paperless thread pattern) -------------------

_inflight: set[str] = set()
_inflight_lock = threading.Lock()


def _run_once(name: str, target, *args) -> None:
    """Run `target` unless a run under the same name is already in flight.

    The handler only logs: a handler that writes to SQLite during a lock is how
    earlier background loops in this codebase died silently.
    """
    with _inflight_lock:
        if name in _inflight:
            return
        _inflight.add(name)
    try:
        started = time.monotonic()
        # "oura-sync-<user id>" is logged as "oura-sync": no identifiers.
        log_run(logger, "-".join(name.split("-")[:2]), started, target(*args))
    except Exception:  # noqa: BLE001 — a sync must never take its caller down
        logger.warning("oura: background %s failed", name, exc_info=True)
    finally:
        with _inflight_lock:
            _inflight.discard(name)


def _spawn(name: str, target, *args) -> None:
    with _inflight_lock:
        if name in _inflight:
            return
    threading.Thread(target=_run_once, args=(name, target, *args),
                     name=f"anamna-{name}", daemon=True).start()


def start_connect_tasks(settings: Settings, user_id: str) -> None:
    """After the OAuth callback: identify, subscribe, backfill, drain."""
    def run() -> None:
        # Envelope first: it is where subscription state is noted, and on a
        # first-ever connect it does not exist until something creates it.
        ensure_envelope(settings, user_id)
        ensure_subscriptions(settings, force=True)
        backfill(settings, user_id)
        process_pending(settings)
    _spawn(f"oura-connect-{user_id}", run)


def start_processing(settings: Settings) -> None:
    _spawn("oura-process", process_pending, settings)


def start_recent_sync(settings: Settings, user_id: str) -> None:
    _spawn(f"oura-sync-{user_id}", sync_recent, settings, user_id)


# --- the scheduler: webhooks are a hint, not a guarantee ----------------------
# An event archived by the webhook used to be processed only when the *next*
# webhook arrived (the last one of a day sat unprocessed until morning), and a
# window that missed a document was never revisited. The scheduler drains the
# queue on a timer and re-syncs every account's recent window once a day.

SCHEDULE_SECONDS = 5 * 60
DAILY_SYNC_SECONDS = 24 * 3600


def sync_due(settings: Settings) -> int:
    """Run the recent-window sync for every usable account not synced in a day.

    Throttled by `last_recent_sync_at` in the envelope metadata, so a restart
    does not refire every account; stamped before the sync runs, so a sync that
    keeps failing is retried daily rather than every pass.
    """
    with connect(settings) as db:
        users = [str(row[0]) for row in db.execute(
            "SELECT user_id FROM provider_connections WHERE provider='oura' AND status<>'reauthorize'"
        )]
    synced = 0
    for user_id in users:
        last = str(sync_state(settings, user_id).get("last_recent_sync_at") or "")
        try:
            moment = datetime.fromisoformat(last)
            stale = (datetime.now(UTC) - moment.replace(tzinfo=moment.tzinfo or UTC)).total_seconds() >= DAILY_SYNC_SECONDS
        except ValueError:
            stale = True
        if not stale:
            continue
        try:
            # Where the stamp lives; without it every pass would sync again.
            ensure_envelope(settings, user_id)
        except IntegrationError as exc:
            logger.warning("oura scheduler: cannot sync an account yet: %s", exc)
            continue
        _update_state(settings, user_id, last_recent_sync_at=utc_now())
        # Same name as the "Sync now" button: never two syncs of one account.
        _run_once(f"oura-sync-{user_id}", sync_recent, settings, user_id)
        synced += 1
    return synced


def start_scheduler(settings: Settings) -> tuple[threading.Event, threading.Thread]:
    """Start the timer thread. Stop with `event.set()`, then `thread.join()`."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(SCHEDULE_SECONDS):
            for name, step in (("events", lambda: _run_once("oura-process", process_pending, settings)),
                               ("daily sync", lambda: sync_due(settings))):
                if stop.is_set():
                    return
                try:
                    step()
                except Exception:  # noqa: BLE001 — "database is locked" included; log only
                    logger.warning("oura scheduler: %s pass failed", name, exc_info=True)

    thread = threading.Thread(target=loop, name="anamna-oura-scheduler", daemon=True)
    thread.start()
    return stop, thread
