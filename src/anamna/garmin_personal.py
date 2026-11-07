"""Garmin Connect Personal API: one person's own Garmin data, with their own key.

Garmin's Connect Developer Program has three tiers. Starter and Enterprise
are OAuth + push (`garmin.py`); **Personal** is a key a person creates for
themselves at connect.garmin.com → Settings → Personal API, valid 30 days to
one year, read-only, pull-only, and — per Garmin's terms — for applications
they operate for their own use. That is exactly a self-hosted record, so each
person pastes their *own* key on /profile; nobody holds anyone else's.

The key is exchanged for a 24-hour bearer JWT (`POST …/personal-api-key/token`
with ``Authorization: ApiKey <key>``); there is no refresh token, a new JWT is
minted from the key. A refused exchange (401/403) means the key expired or was
deleted at Garmin: the connection is marked ``reauthorize`` and the profile
asks for a new key.

Writes follow oura.py's **windowed recompute**: fetch one dataset for a date
window, rebuild the days for the metric keys it owns, upsert, and delete this
envelope's rows in the window that the API no longer reports. Backfill is that
from the first day with data; the scheduler and "Sync now" re-run the last
30 days. Field names and units are Garmin's Personal API OpenAPI 1.0.0
(developer.garmin.com/gc-developer-program/personal/swagger-docs), checked
against a live account on 2026-11-05 — which showed the spec wrong in one
place: weight, bone and muscle mass arrive in **grams**, not kilograms.

What the Personal API cannot give, and so is not here: blood pressure (no
endpoint — the file export still carries it), VO₂ max, skin temperature and
any push. Hydration, nutrition, goals and heart-rate zones are settings or
diary entries, not measurements.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
import urllib.parse
from datetime import UTC, date, datetime, timedelta, timezone

from . import garmin, integrations
from .config import Settings, log_run
from .db import connect, transaction, utc_now
from .devices import exclusions
from .devices.models import Aggregate, Workout
from .integrations import IntegrationError, ReauthorizeError

logger = logging.getLogger("anamna.garmin_personal")

PROVIDER_KEY = "garmin_personal"
ADAPTER_KEY = "garmin_personal_api"
BASE = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
KEY_PREFIX = "GCDC_"

#: Garmin Connect launched in 2008; nothing older can exist.
EPOCH_DAY = "2008-01-01"
RECENT_WINDOW_DAYS = 30
#: Re-mint the JWT this long before it lapses (Garmin's own client uses 1 h).
TOKEN_SLACK_SECONDS = 3600
#: How often the scheduler re-syncs a key's recent window.
REFRESH_SECONDS = 6 * 3600
#: Per-request range limits from the OpenAPI descriptions.
CHUNK_DAYS = {"daily": 365, "sleep": 31, "hrv": 366, "weight": 3650}
_ACTIVITY_PAGE = 100
_MAX_PAGES = 200

#: Metric keys each dataset owns — the delete scope of its recompute.
DATASET_KEYS: dict[str, tuple[str, ...]] = {
    "daily": (
        "steps", "flights_climbed", "active_energy", "resting_energy", "resting_heart_rate",
        "moderate_activity", "vigorous_activity", "stress_level", "body_battery_high", "body_battery_low",
    ),
    "sleep": (
        "sleep_duration", "sleep_deep", "sleep_core", "sleep_rem", "sleep_awake", "time_in_bed",
        "sleep_score", "respiratory_rate", "blood_oxygen", "sleeping_heart_rate",
    ),
    "hrv": ("heart_rate_variability_rmssd",),
    "weight": ("body_weight", "body_mass_index", "body_fat_percentage", "body_water_percentage",
               "bone_mass", "muscle_mass"),
}


def enabled(settings: Settings) -> bool:
    """The operator's switch — the same two layers of consent as Paperless and
    OpenWearables: the operator offers the feature, each person opts in."""
    return integrations.integration_settings(settings)["garmin_personal_enabled"].casefold() in ("1", "true", "yes", "on")


class InvalidKeyError(IntegrationError):
    """Garmin refused the key itself — wrong, expired or deleted."""


# --- the key and its bearer token ----------------------------------------------


def looks_like_key(text: str) -> bool:
    """Shape check before any network call. Garmin documents no structure
    beyond the prefix, so nothing else is assumed."""
    return text.startswith(KEY_PREFIX) and 20 <= len(text) <= 1024 and text.isascii() and not any(c.isspace() for c in text)


def _claims(jwt: str) -> dict:
    try:
        part = jwt.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _mint(key: str) -> tuple[str, str | None, dict]:
    """Exchange the key for a bearer JWT: (jwt, expiry iso, claims)."""
    try:
        jwt = integrations._request(f"{BASE}{TOKEN_PATH}", method="POST", raw=True,
                                    headers={"Accept": "*/*", "Authorization": f"ApiKey {key}"})
    except IntegrationError as exc:
        if exc.status in (401, 403):
            raise InvalidKeyError(str(exc), status=exc.status) from exc
        raise
    jwt = (jwt or "").strip()
    claims = _claims(jwt)
    if not jwt or not claims.get("exp"):
        raise IntegrationError("garmin personal: token endpoint answered without a JWT")
    expires = datetime.fromtimestamp(float(claims["exp"]), UTC).replace(microsecond=0).isoformat()
    return jwt, expires, claims


def link_key(settings: Settings, user_id: str, key: str) -> None:
    """Validate the key by using it, then store it. Raises InvalidKeyError
    when Garmin refuses it — nothing is stored then."""
    jwt, expires, claims = _mint(key)
    integrations.save_connection(
        settings, user_id, PROVIDER_KEY,
        access_token=jwt, refresh_token=key, expires_at=expires,
        external_user_id=str(claims.get("garmin_guid") or ""),
        scopes=" ".join(claims.get("scope") or []) if isinstance(claims.get("scope"), list) else str(claims.get("scope") or ""),
    )


def unlink(settings: Settings, user_id: str) -> None:
    """Forget the key. The data it brought stays: it is the person's own record,
    pulled with their own key, and deleting the key at Garmin is theirs to do."""
    with connect(settings) as db:
        db.execute("DELETE FROM provider_connections WHERE user_id=? AND provider=?", (user_id, PROVIDER_KEY))


def _bearer(settings: Settings, user_id: str, *, force: bool = False) -> str:
    row = integrations.require_connection(settings, user_id, PROVIDER_KEY)
    if not force and integrations.expires_in(row) > TOKEN_SLACK_SECONDS:
        return str(row["access_token"])
    with integrations._lock_for(PROVIDER_KEY, user_id):
        row = integrations.require_connection(settings, user_id, PROVIDER_KEY)
        if not force and integrations.expires_in(row) > TOKEN_SLACK_SECONDS:
            return str(row["access_token"])
        try:
            jwt, expires, _ = _mint(str(row["refresh_token"]))
        except InvalidKeyError as exc:
            with connect(settings) as db:
                db.execute("UPDATE provider_connections SET status='reauthorize', updated_at=? WHERE user_id=? AND provider=?",
                           (utc_now(), user_id, PROVIDER_KEY))
            raise ReauthorizeError(str(exc), status=exc.status) from exc
        with connect(settings) as db:
            db.execute(
                "UPDATE provider_connections SET access_token=?, token_expires_at=?, status='active', updated_at=? WHERE user_id=? AND provider=? AND refresh_token=?",
                (jwt, expires, utc_now(), user_id, PROVIDER_KEY, row["refresh_token"]),
            )
        return jwt


def api_get(settings: Settings, user_id: str, path: str, params: dict[str, object] | None = None):
    url = f"{BASE}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    try:
        return integrations._request(url, headers={"Authorization": f"Bearer {_bearer(settings, user_id)}"})
    except IntegrationError as exc:
        if exc.status != 401:
            raise
        # The JWT died early (key deleted, clock skew): mint once and retry.
        return integrations._request(url, headers={"Authorization": f"Bearer {_bearer(settings, user_id, force=True)}"})


# --- mapping ---------------------------------------------------------------------

add, num = garmin.add, garmin.num


def _local_from_ms(local_ms: object, gmt_ms: object) -> str:
    """Garmin's weight rows carry the local wall-clock and GMT as two epoch-ms
    numbers; their difference is the offset."""
    local, gmt = num(local_ms), num(gmt_ms)
    if local is None or gmt is None:
        return ""
    zone = timezone(timedelta(seconds=round((local - gmt) / 1000 / 60) * 60))
    return datetime.fromtimestamp(gmt / 1000, zone).isoformat()


def _local_from_strings(local: object, gmt: object) -> datetime | None:
    """Activities give "YYYY-MM-DD HH:MM:SS" local and GMT strings."""
    try:
        local_dt = datetime.fromisoformat(str(local).replace(" ", "T"))
        gmt_dt = datetime.fromisoformat(str(gmt).replace(" ", "T"))
    except ValueError:
        return None
    offset = round((local_dt - gmt_dt).total_seconds() / 60) * 60
    return local_dt.replace(tzinfo=timezone(timedelta(seconds=offset)))


def map_daily(rows: list[dict], bucket: dict) -> None:
    for row in rows:
        day = str(row.get("calendarDate") or "")[:10]
        # A day with no wellness data is a day the watch was not worn: Garmin
        # still answers with zeros, which are not measurements.
        if not row.get("includesWellnessData"):
            continue
        section = lambda name: row.get(name) if isinstance(row.get(name), dict) else {}  # noqa: E731
        movement, calories, heart = section("movement"), section("calories"), section("heartRate")
        intensity, stress, battery = section("intensityMinutes"), section("stress"), section("bodyBattery")
        add(bucket, "steps", day, num(movement.get("steps")))
        add(bucket, "flights_climbed", day, num(movement.get("floorsAscended")))
        add(bucket, "active_energy", day, num(calories.get("burnedActive")))
        add(bucket, "resting_energy", day, num(calories.get("burnedResting")))
        add(bucket, "resting_heart_rate", day, num(heart.get("restingValue")))
        add(bucket, "moderate_activity", day, num(intensity.get("moderate")))
        add(bucket, "vigorous_activity", day, num(intensity.get("vigorous")))
        level = num(stress.get("avgLevel"))
        if level is not None and level >= 0:  # -1/-2: not enough rest-state data
            add(bucket, "stress_level", day, level)
        high, low = num(battery.get("maxValue")), num(battery.get("minValue"))
        if high is not None and high >= 0:
            add(bucket, "body_battery_high", day, high)
        if low is not None and low >= 0:
            add(bucket, "body_battery_low", day, low)


def map_sleep(rows: list[dict], bucket: dict) -> None:
    for row in rows:
        day = str(row.get("calendarDate") or "")[:10]
        asleep = num(row.get("sleepTimeSeconds"))
        if not asleep:
            continue  # Garmin lists every requested date; most carry no sleep
        observed = str(row.get("sleepStartTimestampLocal") or day)
        for field, key in (("sleepTimeSeconds", "sleep_duration"), ("deepSleepSeconds", "sleep_deep"),
                           ("lightSleepSeconds", "sleep_core"), ("remSleepSeconds", "sleep_rem"),
                           ("awakeSleepSeconds", "sleep_awake")):
            add(bucket, key, day, garmin.converted(row.get(field), "s", key), observed)
        awake = num(row.get("awakeSleepSeconds")) or 0
        add(bucket, "time_in_bed", day, garmin.converted(asleep + awake, "s", "time_in_bed"), observed)
        scores = row.get("sleepScores") if isinstance(row.get("sleepScores"), dict) else {}
        overall = scores.get("overall") if isinstance(scores.get("overall"), dict) else {}
        add(bucket, "sleep_score", day, num(overall.get("value")), observed)
        add(bucket, "respiratory_rate", day, num(row.get("averageRespirationValue")), observed)
        spo2 = num(row.get("averageSpO2Value"))
        if spo2 is not None and 50 <= spo2 <= 100:
            add(bucket, "blood_oxygen", day, spo2, observed)
        add(bucket, "sleeping_heart_rate", day, num(row.get("avgHeartRate")), observed)


def map_hrv(rows: list[dict], bucket: dict) -> None:
    for row in rows:
        add(bucket, "heart_rate_variability_rmssd", str(row.get("calendarDate") or "")[:10], num(row.get("lastNightAvg")))


def map_weight(days: list[dict], bucket: dict) -> None:
    for summary in days:
        for entry in summary.get("allWeightMetrics") or []:
            if not isinstance(entry, dict):
                continue
            day = str(entry.get("calendarDate") or summary.get("summaryDate") or "")[:10]
            # Same source names as the Garmin file importer, so a reading in
            # both the export and the API is one row, not two.
            source = garmin.SCALE_SOURCE_NAME if entry.get("sourceType") == "INDEX_SCALE" else garmin.MANUAL_WEIGHT_SOURCE_NAME
            garmin.body_composition(bucket, day, _local_from_ms(entry.get("date"), entry.get("timestampGMT")), source, (
                ("body_weight", entry.get("weight"), "g"),
                ("body_mass_index", entry.get("bmi"), ""),
                ("body_fat_percentage", entry.get("bodyFat"), ""),
                ("body_water_percentage", entry.get("bodyWater"), ""),
                ("bone_mass", entry.get("boneMass"), "g"),
                ("muscle_mass", entry.get("muscleMass"), "g"),
            ))


def map_activity(row: dict) -> Workout | None:
    kind = row.get("activityType") if isinstance(row.get("activityType"), dict) else {}
    return garmin.workout(
        _local_from_strings(row.get("startTimeLocal"), row.get("startTimeGMT")),
        str(kind.get("typeKey") or ""), num(row.get("duration")), num(row.get("calories")), num(row.get("distance")),
    )


# --- fetching ----------------------------------------------------------------------


def _chunks(start: str, end: str, size: int):
    cursor, final = date.fromisoformat(start), date.fromisoformat(end)
    while cursor <= final:
        stop = min(cursor + timedelta(days=size - 1), final)
        yield cursor.isoformat(), stop.isoformat()
        cursor = stop + timedelta(days=1)


def _dataset_request(dataset: str, a: str, b: str) -> tuple[str, dict | None, str | None]:
    """Path, query and the key holding the list in a wrapped answer (None when
    the answer is the list itself)."""
    if dataset == "daily":
        return "/usersummary-service/v2/dailysummaries", {"startDate": a, "endDate": b}, "data"
    if dataset == "sleep":
        return "/sleep-service/sleep/dailySleepSummariesByDate", {"startDate": a, "endDate": b}, None
    if dataset == "hrv":
        return f"/hrv-service/hrv/daily/{a}/{b}", None, "hrvSummaries"
    return f"/weight-service/weight/range/{a}/{b}", {"includeAll": "true"}, "dailyWeightSummaries"


def fetch(settings: Settings, user_id: str, dataset: str, start: str, end: str) -> list[dict]:
    rows: list[dict] = []
    for a, b in _chunks(start, end, CHUNK_DAYS[dataset]):
        path, query, wrapper = _dataset_request(dataset, a, b)
        batch = api_get(settings, user_id, path, query)
        if wrapper:
            batch = batch.get(wrapper) if isinstance(batch, dict) else None
        if batch is None:
            batch = []
        if not isinstance(batch, list):
            raise IntegrationError(f"garmin personal: {dataset} answered {type(batch).__name__}, not a list")
        rows.extend(item for item in batch if isinstance(item, dict))
    return rows


def fetch_activities(settings: Settings, user_id: str, start: str, end: str) -> list[dict]:
    rows: list[dict] = []
    for page in range(_MAX_PAGES):
        batch = api_get(settings, user_id, "/activitylist-service/activities/search/activities", {
            "start": page * _ACTIVITY_PAGE, "limit": _ACTIVITY_PAGE, "startDate": start, "endDate": end,
            "sortOrder": "asc", "excludeChildren": "true",
        })
        if not isinstance(batch, list):
            raise IntegrationError("garmin personal: activity search answered a non-list")
        rows.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < _ACTIVITY_PAGE:
            return rows
    raise IntegrationError("garmin personal: activity search exceeded the pagination limit")


_MAPPERS = {"daily": map_daily, "sleep": map_sleep, "hrv": map_hrv, "weight": map_weight}


def _days(start: str, end: str) -> list[str]:
    return [a for a, _ in _chunks(start, end, 1)]


def _check_key(db, user_id: str, key: str) -> None:
    row = db.execute("SELECT refresh_token FROM provider_connections WHERE user_id=? AND provider=?",
                     (user_id, PROVIDER_KEY)).fetchone()
    if row is None or str(row[0]) != key:
        raise IntegrationError("garmin personal: the key changed during sync; retry with the current one")


def _current_key(settings: Settings, user_id: str) -> str:
    return str(integrations.require_connection(settings, user_id, PROVIDER_KEY)["refresh_token"])


def sync_dataset(settings: Settings, user_id: str, dataset: str, start: str, end: str) -> int:
    """Fetch one dataset for [start, end] and make the stored days match."""
    key = _current_key(settings, user_id)
    import_id = garmin.ensure_envelope(settings, user_id, ADAPTER_KEY)
    rows = fetch(settings, user_id, dataset, start, end)
    bucket: dict[tuple, Aggregate] = {}
    with transaction(settings, immediate=True) as db:
        _check_key(db, user_id, key)
        # Mapped under the person's "not my reading" rules, read in this
        # write transaction, so a rule saved during the fetch is applied.
        with exclusions.applying(db, user_id, ADAPTER_KEY):
            _MAPPERS[dataset](rows, bucket)
        return garmin.replace_metric_days(db, user_id, import_id, DATASET_KEYS[dataset], _days(start, end),
                                          list(bucket.values()))


def sync_activities(settings: Settings, user_id: str, start: str, end: str) -> int:
    key = _current_key(settings, user_id)
    import_id = garmin.ensure_envelope(settings, user_id, ADAPTER_KEY)
    workouts = [w for w in map(map_activity, fetch_activities(settings, user_id, start, end)) if w]
    with transaction(settings, immediate=True) as db:
        _check_key(db, user_id, key)
        workouts = garmin.kept_workouts(workouts, exclusions.matcher(db, user_id, ADAPTER_KEY))
        return garmin.replace_workouts(db, user_id, import_id, _days(start, end), workouts)


def sync_fitness_age(settings: Settings, user_id: str, as_of: str) -> int:
    """Fitness age is "the latest as of a date": one value, written on the
    day Garmin last recomputed it. No window — older values are history."""
    key = _current_key(settings, user_id)
    import_id = garmin.ensure_envelope(settings, user_id, ADAPTER_KEY)
    payload = api_get(settings, user_id, f"/fitnessage-service/fitnessage/v2/{as_of}")
    if isinstance(payload, list):
        entries = payload
    else:
        entries = [payload] if isinstance(payload, dict) else []
    bucket: dict = {}
    with transaction(settings, immediate=True) as db:
        _check_key(db, user_id, key)
        with exclusions.applying(db, user_id, ADAPTER_KEY):
            for entry in entries:
                if isinstance(entry, dict) and not entry.get("invalidReason"):
                    add(bucket, "fitness_age", str(entry.get("lastUpdated") or as_of)[:10], num(entry.get("fitnessAge")))
        return garmin.replace_metric_days(db, user_id, import_id, ("fitness_age",),
                                          {item.day for item in bucket.values()}, list(bucket.values()))


# --- entry points ---------------------------------------------------------------------


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _first_wellness_day(settings: Settings, user_id: str) -> str | None:
    """Daily summaries in year-long bites from 2008 — cheap, and the first day
    with wellness data bounds the per-31-day sleep backfill, which would
    otherwise be ~220 requests for an account that never wore a watch."""
    for start, end in _chunks(EPOCH_DAY, _today(), CHUNK_DAYS["daily"]):
        rows = fetch(settings, user_id, "daily", start, end)
        days = sorted(str(r.get("calendarDate"))[:10] for r in rows if r.get("includesWellnessData"))
        if days:
            return days[0]
    return None


def _run(steps: list[tuple[str, object]]) -> tuple[dict, dict]:
    counts: dict[str, int] = {}
    failed: dict[str, str] = {}
    for name, step in steps:
        try:
            counts[name] = step()
        except ReauthorizeError:
            raise
        except IntegrationError as exc:
            failed[name] = str(exc)[:200]
            logger.warning("garmin personal: %s failed: %s", name, exc)
    return counts, failed


def backfill(settings: Settings, user_id: str) -> dict[str, int]:
    """Everything the key can see. Datasets are independent: one failing must
    not cost the person the others."""
    garmin.ensure_envelope(settings, user_id, ADAPTER_KEY)
    today = _today()
    first = _first_wellness_day(settings, user_id)
    steps: list[tuple[str, object]] = [
        ("weight", lambda: sync_dataset(settings, user_id, "weight", EPOCH_DAY, today)),
        ("activities", lambda: sync_activities(settings, user_id, EPOCH_DAY, today)),
        ("fitness_age", lambda: sync_fitness_age(settings, user_id, today)),
    ]
    if first:
        steps += [(ds, lambda ds=ds: sync_dataset(settings, user_id, ds, first, today)) for ds in ("daily", "sleep", "hrv")]
    counts, failed = _run(steps)
    garmin.update_state(settings, user_id, ADAPTER_KEY, last_backfill_at=utc_now(), last_sync_at=utc_now(),
                        first_wellness_day=first or "", backfill_counts=counts, failed_datatypes=failed)
    return counts


def sync_recent(settings: Settings, user_id: str) -> dict[str, int]:
    start = (datetime.now(UTC).date() - timedelta(days=RECENT_WINDOW_DAYS)).isoformat()
    today = _today()
    steps: list[tuple[str, object]] = [
        (ds, lambda ds=ds: sync_dataset(settings, user_id, ds, start, today)) for ds in ("daily", "sleep", "hrv", "weight")
    ] + [
        ("activities", lambda: sync_activities(settings, user_id, start, today)),
        ("fitness_age", lambda: sync_fitness_age(settings, user_id, today)),
    ]
    counts, failed = _run(steps)
    garmin.update_state(settings, user_id, ADAPTER_KEY, last_sync_at=utc_now(), failed_datatypes=failed)
    return counts


def resync_window(settings: Settings, user_id: str, start: str, end: str) -> dict[str, int]:
    """Fetch and rewrite [start, end] after the person's "not my reading"
    rules changed.  The key keeps no local copy, so the provider's own
    windowed sync is the rebuild; fitness age is asked again as of each day
    it is stored for, since the API only answers "latest as of"."""
    if integrations.connection_row(settings, user_id, PROVIDER_KEY) is None:
        return {}
    start, end = max(start, EPOCH_DAY), min(end, _today())
    if start > end:
        return {}
    with connect(settings) as db:
        ages = [str(row[0]) for row in db.execute(
            """SELECT DISTINCT d.day FROM device_metric_days d JOIN device_imports i ON i.id=d.import_id
               WHERE d.owner_user_id=? AND i.adapter_key=? AND d.metric_key='fitness_age' AND d.day BETWEEN ? AND ?""",
            (user_id, ADAPTER_KEY, start, end))]
    steps: list[tuple[str, object]] = [
        (ds, lambda ds=ds: sync_dataset(settings, user_id, ds, start, end)) for ds in ("daily", "sleep", "hrv", "weight")
    ] + [("activities", lambda: sync_activities(settings, user_id, start, end))]
    steps += [(f"fitness_age {day}", lambda day=day: sync_fitness_age(settings, user_id, day)) for day in ages]
    counts, _failed = _run(steps)
    return counts


def sync_state(settings: Settings, user_id: str) -> dict:
    return garmin.sync_state(settings, user_id, ADAPTER_KEY)


def _connect_run(settings: Settings, user_id: str) -> None:
    try:
        if sync_state(settings, user_id).get("last_backfill_at"):
            sync_recent(settings, user_id)
        else:
            backfill(settings, user_id)
    except ReauthorizeError:
        logger.warning("garmin personal: the stored key was refused; the profile asks for a new one")


def start_sync(settings: Settings, user_id: str) -> None:
    """After a key is saved (full history, once) and from "Sync now"."""
    garmin.spawn(f"garmin-personal-{user_id}", _connect_run, settings, user_id)


def sync_due(settings: Settings) -> int:
    """The scheduler's pass: every active key whose last sync is stale."""
    if not enabled(settings):
        return 0
    with connect(settings) as db:
        users = [str(r[0]) for r in db.execute(
            "SELECT user_id FROM provider_connections WHERE provider=? AND status='active'", (PROVIDER_KEY,))]
    started = 0
    for user_id in users:
        last = str(sync_state(settings, user_id).get("last_sync_at") or "")
        try:
            stale = not last or (datetime.now(UTC) - datetime.fromisoformat(last)).total_seconds() > REFRESH_SECONDS
        except ValueError:
            stale = True
        if stale:
            _connect_run(settings, user_id)
            started += 1
    return started


# --- the scheduler: Personal keys have no push, and Garmin business deliveries
# --- that failed to process need a retry that does not wait for the next push.

SCHEDULE_SECONDS = 15 * 60


def start_scheduler(settings: Settings) -> threading.Event:
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(SCHEDULE_SECONDS):
            # Each pass is fully guarded and its handler never writes: a
            # handler that touches SQLite during a lock is how earlier loops
            # in this codebase died silently.
            for name, step in (("personal", sync_due), ("deliveries", garmin.process_pending)):
                try:
                    started = time.monotonic()
                    log_run(logger, f"garmin-scheduler {name}", started, step(settings))
                except Exception:  # noqa: BLE001
                    logger.warning("garmin scheduler: %s pass failed", name, exc_info=True)

    threading.Thread(target=loop, name="anamna-garmin-scheduler", daemon=True).start()
    return stop


def panel(settings: Settings, user_id: str) -> dict[str, object] | None:
    """What the profile card says about a stored key, or None without one."""
    row = integrations.connection_row(settings, user_id, PROVIDER_KEY)
    if row is None:
        return None
    state = sync_state(settings, user_id)
    with connect(settings) as db:
        days = db.execute(
            "SELECT COUNT(DISTINCT day), MAX(day) FROM device_metric_days d JOIN device_imports i ON i.id=d.import_id WHERE i.owner_user_id=? AND i.adapter_key=?",
            (user_id, ADAPTER_KEY),
        ).fetchone()
    return {
        "connected_at": str(row["connected_at"]),
        "needs_new_key": str(row["status"]) == "reauthorize",
        "sync_days": int(days[0] or 0),
        "sync_latest_day": str(days[1] or ""),
        "sync_last_at": str(state.get("last_sync_at") or ""),
        "backfill_done": bool(state.get("last_backfill_at")),
        "no_wellness": bool(state.get("last_backfill_at")) and not state.get("first_wellness_day"),
        "failures": sorted((state.get("failed_datatypes") or {}).keys()),
    }
