"""OpenWearables: a self-hosted aggregation server, read into the record.

The server sits between the person's phone and everything that writes to it —
Apple Health, Oura, Garmin, Zepp Life — and re-serves the result as daily
summaries.  What that buys this application is *continuity*: a file export is
a photograph taken on the day somebody remembered to take it, and the days
after it are simply missing until the next one.  A linked server keeps
arriving.

Rows retain the OpenWearables transport vendor and a source name containing
the upstream provider, writer and device. The source reconciliation layer
uses that provenance and the person's preference to choose among overlapping
measurements. Direct imports and bridge rows remain separately inspectable;
the natural key ``(owner, source_name, metric_key, day)`` keeps them apart.

Two layers of consent, mirroring Paperless: the operator enables the feature
and names the server (``/admin/openwearables``), then each person links their
own remote account.  The API key is instance-wide and admin-held; a person
never sees it.

Writing works exactly as :mod:`anamna.oura` does — the **windowed
recompute**.  Fetch one datatype for one date window, rebuild the daily rows
for the metric keys that datatype owns, upsert them, and delete this
envelope's rows in the window for days the server no longer reports.  A failed
fetch changes nothing, because the delete only runs after the whole window
arrived.

Signed outgoing webhooks and durable scheduled catch-up are implemented in
``openwearables_webhooks``. Endpoint management supports the instance API key
or a separately configured management bearer token, depending on the server.
Manual sync and link backfill use the same account-scoped persistent queue.

Verified against the live API on 2026-08-07.  Authentication is the header
``X-Open-Wearables-API-Key`` (not Bearer); a missing required parameter
answers 400, not 422; and three different pagination styles are in use —
cursor for summaries, events and timeseries, offset for health scores, page
number for the user list.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta, tzinfo

from .config import USER_AGENT, Settings, env, per_request
from .db import connect, transaction, utc_now
from .devices import exclusions
from .devices.catalog import HEALTHKIT_METRICS, SLEEP_METRICS, metric
from .devices.models import Aggregate, DeviceEvent, MetricDefinition, Workout
from .devices.timezone import local_bounds_utc, local_day, user_timezone, user_timezone_for
from .devices.units import convert_quantity, finite_number, plausible_aggregates
from .i18n import t, translate_phrase
from .ingest.pipeline import ensure_vendor, stable_id

logger = logging.getLogger("anamna.openwearables")

SOURCE_NAME = "OpenWearables"
PROVIDER = "openwearables"
ADAPTER_KEY = "openwearables_api"
VENDOR_WEBSITE = "https://openwearables.io/"

#: The event type menstrual cycles are stored under; also their UI label.
EVENT_CYCLE = "Menstrual cycle"

#: Earliest data seen on the live server is 2016-01-01; start a year before it
#: so a longer-lived account backfills whole.
EPOCH_DAY = "2015-01-01"

#: The "Sync now" window. Backfill owns history; this heals recent edits.
RECENT_WINDOW_DAYS = 30

#: Interval between durable, page-independent scheduled catch-up runs.
REFRESH_SECONDS = 12 * 3600

REQUEST_TIMEOUT = 30

#: Largest response body read into memory.  Every answer these calls expect is
#: JSON of a few kilobytes to a few megabytes; anything larger is not one.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024

#: Server-side page maxima, measured: activity takes 400, the other cursor
#: endpoints 100, health-scores 1000 on its own offset pagination.
_SUMMARY_LIMIT = 400
_PAGE_LIMIT = 100
_SCORE_LIMIT = 1000

#: A server that answered the same cursor twice would page forever.
_MAX_PAGES = 500


class OpenWearablesError(Exception):
    """The server is unreachable, refused the request, or answered nonsense.

    ``status`` carries the HTTP code when one was received — callers branch on
    it as an integer, never by substring-matching the message, which embeds up
    to 300 characters of response body that can contain anything.
    """

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class OpenWearablesPageLimitError(OpenWearablesError):
    """A valid cursor chain exceeds one bounded read, rather than failing HTTP."""

    def __init__(self, message: str, *, indivisible_timestamp: bool = False):
        super().__init__(message)
        self.indivisible_timestamp = indivisible_timestamp


# --- HTTP --------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects.

    ``urllib`` copies every header except content-length/type onto the
    redirected request, so a 302 would hand ``X-Open-Wearables-API-Key`` to
    whatever host the Location names.  The API never redirects itself, so a
    3xx here is a misconfigured URL or an attack.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_opener = urllib.request.build_opener(_NoRedirect())


def _request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    timeout: int = REQUEST_TIMEOUT,
    data: dict | None = None,
):
    """One request, parsed JSON back (``None`` for an empty body).  The single
    seam tests stub; every failure becomes :class:`OpenWearablesError`."""
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Accept": "application/json",
            # Cloudflare refuses urllib's default signature; see USER_AGENT.
            "User-Agent": USER_AGENT,
            **(headers or {}),
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
        data=json.dumps(data).encode("utf-8") if data is not None else None,
    )
    try:
        with _opener.open(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise OpenWearablesError("openwearables: response too large")
    except urllib.error.HTTPError as exc:
        detail = exc.read(MAX_RESPONSE_BYTES).decode("utf-8", "replace")[:300]
        raise OpenWearablesError(f"HTTP {exc.code}: {detail}", status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OpenWearablesError(str(exc)) from exc
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OpenWearablesError(f"unparseable reply: {body[:200]!r}") from exc


# --- configuration -----------------------------------------------------------

SETTING_KEYS = ("openwearables_enabled", "openwearables_url", "openwearables_api_key")


@per_request
def ow_settings(settings: Settings) -> dict[str, str]:
    with connect(settings) as connection:
        stored = dict(
            connection.execute(
                "SELECT key, value FROM app_settings WHERE key IN (?, ?, ?)", SETTING_KEYS
            ).fetchall()
        )
    # The env vars seed an unconfigured instance; once the admin has saved a
    # field it wins even when empty, or clearing the address would silently
    # reinstate the old server and keep reading somebody's health data from it.
    url = (
        stored["openwearables_url"] if "openwearables_url" in stored
        else env("OPENWEARABLES_URL", "")
    )
    api_key = (
        stored["openwearables_api_key"] if "openwearables_api_key" in stored
        else env("OPENWEARABLES_API_KEY", "")
    )
    return {
        "enabled": stored.get("openwearables_enabled", "1"),
        "url": url.strip().rstrip("/"),
        "api_key": api_key.strip(),
    }


def configured(settings: Settings) -> bool:
    """Whether the feature is on *and* usable.  Everything user-facing hides
    itself when this is false — an unconfigured integration is not a broken
    page, it is no page."""
    config = ow_settings(settings)
    return config["enabled"] == "1" and bool(config["url"]) and bool(config["api_key"])


def save_settings(settings: Settings, values: dict[str, str]) -> None:
    """Store the admin's fields.

    A remote user id means nothing on a different server, so pointing at one
    unlinks every account rather than leaving links that resolve to whoever
    happens to hold that uuid over there.  Synced rows stay: they are the
    person's measurements, and re-linking resumes them.
    """
    previous = ow_settings(settings)["url"]
    changed_server = "openwearables_url" in values and values["openwearables_url"].strip().rstrip("/") != previous
    with transaction(settings, immediate=True) as connection:
        if changed_server:
            # Preserve the original server identity even for envelopes created
            # before that identity was stored explicitly.
            for row in connection.execute("SELECT id, metadata_json FROM device_imports WHERE adapter_key=?", (ADAPTER_KEY,)).fetchall():
                state = json.loads(row["metadata_json"])
                state.setdefault("remote_server_url", previous)
                connection.execute("UPDATE device_imports SET metadata_json=? WHERE id=?", (json.dumps(state), row["id"]))
        for key, value in values.items():
            connection.execute(
                """INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                (key, value, utc_now()),
            )
        if changed_server:
            if previous:
                # An environment-provided developer token belongs to the old
                # server. A URL edit must not send it to the replacement host.
                connection.execute("""INSERT INTO app_settings(key,value,updated_at)
                    VALUES ('openwearables_webhook_token_server',?,?) ON CONFLICT(key) DO NOTHING""", (previous, utc_now()))
            connection.execute("DELETE FROM provider_connections WHERE provider=?", (PROVIDER,))
            connection.execute("UPDATE openwearables_subscriptions SET enabled=0, status='server_changed', secret='', previous_secret='' WHERE server_url=?", (previous,))
            connection.execute("UPDATE openwearables_sync_jobs SET status='cancelled', updated_at=? WHERE status IN ('queued','running','retry')", (utc_now(),))


# --- authenticated API access ------------------------------------------------


def _api(settings: Settings, path: str, params: dict[str, object] | None = None,
         *, method: str = "GET", data: dict | None = None):
    config = ow_settings(settings)
    if not config["url"] or not config["api_key"]:
        raise OpenWearablesError("openwearables: no server configured")
    url = f"{config['url']}/api/v1{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    options = {"headers": {"X-Open-Wearables-API-Key": config["api_key"]}}
    if method != "GET":
        options["method"] = method
    if data is not None:
        options["data"] = data
    return _request(url, **options)


_UTC_OFFSET = "+00:00"
_STATE_SQL = "SELECT metadata_json FROM device_imports WHERE owner_user_id=? AND adapter_key=?"


def _page_rows(path: str, page: object) -> tuple[list[dict], dict]:
    """Validate one cursor page and return its rows and pagination block."""
    if not isinstance(page, dict):
        raise OpenWearablesError(f"openwearables: {path} answered {type(page).__name__}, not a page")
    batch = page.get("data")
    if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
        raise OpenWearablesError(f"openwearables: {path} answered with an invalid data list")
    pagination = page.get("pagination")
    if not isinstance(pagination, dict) or not isinstance(pagination.get("has_more"), bool):
        raise OpenWearablesError(f"openwearables: {path} answered with invalid pagination")
    return batch, pagination


def _indivisible_timestamp(rows: list[dict]) -> bool:
    """True when every row shares one timestamp, so no window can split them."""
    stamp = rows[0].get("timestamp") if rows else None
    return bool(stamp) and all(row.get("timestamp") == stamp for row in rows)


def _cursor_pages(settings: Settings, path: str, params: dict[str, object], limit: int) -> list[dict]:
    """Summaries, events and timeseries: ``{data, pagination: {next_cursor,
    has_more}}``."""
    rows: list[dict] = []
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(_MAX_PAGES):
        page = _api(settings, path, {**params, "limit": str(limit), **({"cursor": cursor} if cursor else {})})
        batch, pagination = _page_rows(path, page)
        rows.extend(batch)
        cursor = str(pagination.get("next_cursor") or "")
        if not pagination.get("has_more"):
            return rows
        if not cursor or cursor in seen:
            raise OpenWearablesError(f"openwearables: {path} pagination did not advance")
        seen.add(cursor)
    raise OpenWearablesPageLimitError(f"openwearables: {path} exceeded the pagination limit",
        indivisible_timestamp=_indivisible_timestamp(rows))


def _day_shift(day: str, days: int) -> str:
    try:
        return (datetime.fromisoformat(day[:10]) + timedelta(days=days)).date().isoformat()
    except ValueError:
        return ""


def _fresh_rows(batch: list[dict], seen_rows: set[str]) -> list[dict]:
    """Rows not seen before, recording each fingerprint as it is taken."""
    fresh = []
    for row in batch:
        fingerprint = json.dumps(row, sort_keys=True, separators=(",", ":"))
        if fingerprint not in seen_rows:
            seen_rows.add(fingerprint)
            fresh.append(row)
    return fresh


def _exhaustive_rows(settings: Settings, path: str, params: dict[str, object],
                     limit: int, advance, *, max_rows: int | None = None) -> list[dict]:
    """Keep reading past a cursor chain that gives up early.

    The server has answered ``has_more: false`` on a *full* page in the middle
    of the history — measured 2026-08-07: sleep summaries stopped at
    2024-07-21 with two more years of nights still on the server, reachable by
    simply asking again from the next day.  A short page is a genuine end; a
    full one reopens the window at its final day/timestamp and deduplicates
    that overlap. If a full boundary cannot advance, fail before replacing
    stored rows rather than skipping equal timestamps or same-day sources.
    """
    rows: list[dict] = []
    seen_rows: set[str] = set()
    window = dict(params)
    for _ in range(_MAX_PAGES):
        batch = _cursor_pages(settings, path, window, limit)
        fresh = _fresh_rows(batch, seen_rows)
        rows.extend(fresh)
        if max_rows is not None and len(rows) > max_rows:
            raise OpenWearablesPageLimitError(f"openwearables: {path} exceeded the interval row budget",
                indivisible_timestamp=_indivisible_timestamp(rows))
        if not batch or len(batch) % limit:
            return rows
        next_window = advance(batch, window)
        if next_window is None or next_window == window or not fresh:
            raise OpenWearablesError(f"openwearables: {path} full terminal page cannot prove complete boundary")
        window = next_window
    raise OpenWearablesPageLimitError(f"openwearables: {path} exceeded the window pagination limit")


def _advance_dates(batch: list[dict], window: dict[str, object]) -> dict[str, object] | None:
    """Overlap the final day: several sources can share its date."""
    last = max((str(row.get("date") or "")[:10] for row in batch), default="")
    start = _day_shift(last, 0)
    if not start or start <= str(window.get("start_date") or "") or start > str(window.get("end_date") or ""):
        return None
    return {**window, "start_date": start}


def _advance_timestamps(batch: list[dict], window: dict[str, object]) -> dict[str, object] | None:
    """Overlap the final timestamp, preserving fractional and equal-time rows."""
    last = max((str(row.get("timestamp") or "") for row in batch), default="")
    try:
        moment = datetime.fromisoformat(last.replace("Z", _UTC_OFFSET))
    except ValueError:
        return None
    start = moment.astimezone(UTC).isoformat().replace(_UTC_OFFSET, "Z")
    # Compare instants, not strings: "…T23:59:59Z" sorts after
    # "…T23:59:59.999999Z" as text, which failed a full page ending exactly
    # on the window's last whole second.
    bounds = []
    for field in ("start_time", "end_time"):
        try:
            bounds.append(datetime.fromisoformat(str(window.get(field) or "").replace("Z", _UTC_OFFSET)))
        except ValueError:
            return None
    if moment <= bounds[0] or moment > bounds[1]:
        return None
    return {**window, "start_time": start}


def _advance_descending(batch: list[dict], window: dict[str, object]) -> dict[str, object] | None:
    """Overlap the oldest day, including every session on that boundary."""
    first = min((str(row.get("start_time") or "")[:10] for row in batch), default="")
    end = _day_shift(first, 1)
    if not end or end >= str(window.get("end_date") or "") or end < str(window.get("start_date") or ""):
        return None
    return {**window, "end_date": end}


def _offset_pages(settings: Settings, path: str, params: dict[str, object], limit: int) -> list[dict]:
    """Health scores paginate by offset and always answer ``next_cursor``
    null, so the cursor loop above would stop after one page."""
    rows: list[dict] = []
    for page in range(_MAX_PAGES):
        payload = _api(settings, path, {**params, "limit": str(limit), "offset": str(page * limit)})
        if not isinstance(payload, dict):
            raise OpenWearablesError(f"openwearables: {path} answered {type(payload).__name__}, not a page")
        batch = payload.get("data")
        if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
            raise OpenWearablesError(f"openwearables: {path} answered with an invalid data list")
        pagination = payload.get("pagination") or {}
        if not isinstance(pagination, dict):
            raise OpenWearablesError(f"openwearables: {path} answered with invalid pagination")
        rows.extend(batch)
        if not pagination.get("has_more"):
            return rows
        if len(batch) < limit:
            raise OpenWearablesError(f"openwearables: {path} returned a truncated offset page")
    raise OpenWearablesError(f"openwearables: {path} exceeded the pagination limit")


def remote_users(settings: Settings) -> list[dict[str, object]]:
    """Every account the server holds, for a person to pick their own from.

    The single-user ``GET /users/{id}`` leaves ``last_synced_at`` and
    ``has_active_connection`` unset, so this list is the only place they are
    true — which is why the card reads them from here rather than re-fetching
    the one account it cares about.
    """
    users: list[dict[str, object]] = []
    page = 1
    for _ in range(_MAX_PAGES):
        payload = _api(settings, "/users", {"limit": "100", "page": str(page)})
        if not isinstance(payload, dict):
            raise OpenWearablesError("openwearables: /users did not answer a page")
        items = payload.get("items")
        if not isinstance(items, list) or any(not isinstance(item, dict) or not item.get("id") for item in items):
            raise OpenWearablesError("openwearables: /users answered an invalid account list")
        for item in items:
            name = " ".join(
                str(item.get(part) or "") for part in ("first_name", "last_name")
            ).strip()
            users.append(
                {
                    "id": str(item["id"]),
                    "email": str(item.get("email") or ""),
                    "name": name,
                    "last_synced_at": str(item.get("last_synced_at") or ""),
                    "connected": bool(item.get("has_active_connection")),
                }
            )
        if not payload.get("has_next"):
            return users
        page += 1
    raise OpenWearablesError("openwearables: /users exceeded the pagination limit")


def probe(settings: Settings) -> dict[str, object]:
    """What the admin's test button reports.  One authenticated round trip, so
    "configured" and "working" stay different claims."""
    try:
        users = remote_users(settings)
    except OpenWearablesError as exc:
        status = "unauthorized" if exc.status in (401, 403) else "unreachable"
        return {"ok": False, "status": status, "user_count": None}
    return {"ok": True, "status": "ok", "user_count": len(users)}


# --- what each datatype becomes ----------------------------------------------

_BY_KEY = {d.key: d for d in {**HEALTHKIT_METRICS, **SLEEP_METRICS}.values()}


def _definition(key: str, name: str, category: str, unit: str, aggregation: str) -> MetricDefinition:
    """The catalog's definition when the key exists there — one spelling of
    name/unit/aggregation per key across every importer — else a new one."""
    return _BY_KEY.get(key) or metric(key, name, category, unit, aggregation)


DEFS = {
    key: _definition(key, name, category, unit, aggregation)
    for key, name, category, unit, aggregation in (
        # Catalog keys: the literals here are fallbacks the catalog overrides.
        ("steps", "Daily steps", "device_activity", "steps", "sum"),
        ("walking_running_distance", "Walking and running distance", "device_activity", "km", "sum"),
        ("flights_climbed", "Flights climbed", "device_activity", "flights", "sum"),
        ("active_energy", "Active energy", "device_activity", "kcal", "sum"),
        ("active_minutes", "Active minutes", "device_activity", "min", "sum"),
        ("sedentary_minutes", "Sedentary time", "device_activity", "min", "sum"),
        ("light_activity", "Light activity", "device_activity", "min", "sum"),
        ("total_energy", "Total energy expenditure", "device_activity", "kcal", "sum"),
        ("elevation", "Daily elevation", "device_activity", "m", "sum"),
        ("moderate_activity", "Moderate activity", "device_activity", "min", "sum"),
        ("vigorous_activity", "Vigorous activity", "device_activity", "min", "sum"),
        ("daily_heart_rate", "Daily heart rate", "device_recovery", "bpm", "average"),
        ("sleep_duration", "Time asleep", "device_sleep", "hours", "sum"),
        ("time_in_bed", "Time in bed", "device_sleep", "hours", "sum"),
        ("sleep_deep", "Deep sleep", "device_sleep", "hours", "sum"),
        ("sleep_rem", "REM sleep", "device_sleep", "hours", "sum"),
        ("sleep_core", "Core sleep", "device_sleep", "hours", "sum"),
        ("sleep_awake", "Awake during sleep", "device_sleep", "hours", "sum"),
        ("sleeping_heart_rate", "Average sleeping heart rate", "device_sleep", "bpm", "average"),
        ("heart_rate_variability_rmssd", "Heart rate variability (RMSSD)", "device_recovery", "ms", "average"),
        ("sleep_interruptions", "Sleep interruptions", "device_sleep", "count", "sum"),
        ("sleep_naps", "Naps", "device_sleep", "count", "sum"),
        ("sleep_nap_duration", "Nap duration", "device_sleep", "min", "sum"),
        ("heart_rate_variability", "Heart rate variability (SDNN)", "device_recovery", "ms", "average"),
        ("respiratory_rate", "Respiratory rate", "device_recovery", "breaths/min", "average"),
        ("blood_oxygen", "Blood oxygen saturation", "device_recovery", "%", "average"),
        ("resting_heart_rate", "Resting heart rate", "device_recovery", "bpm", "average"),
        ("body_weight", "Body weight", "device_body", "kg", "latest"),
        ("body_mass_index", "Body mass index", "device_body", "kg/m²", "latest"),
        ("body_fat_percentage", "Body fat", "device_body", "%", "latest"),
        ("lean_body_mass", "Lean body mass", "device_body", "kg", "latest"),
        ("waist_circumference", "Waist circumference", "device_body", "cm", "latest"),
        ("vo2_max", "Cardio fitness (VO₂ max)", "device_fitness", "mL/kg/min", "average"),
        # Keys the catalog does not carry; spellings must match the importer
        # that established them — devices/structured.py and oura.py.
        ("body_height", "Body height", "device_body", "cm", "latest"),
        ("sleep_efficiency", "Sleep efficiency", "device_sleep", "%", "latest"),
        ("sleep_score", "Sleep score", "device_sleep", "score", "latest"),
        ("readiness_score", "Readiness score", "device_recovery", "score", "latest"),
        ("activity_score", "Activity score", "device_activity", "score", "latest"),
        # New with this integration: a vendor-proprietary 0-100 composite with
        # no published interval, shown as a score rather than judged.
        ("recovery_score", "Recovery score", "device_recovery", "score", "latest"),
        ("stress_score", "Stress score", "device_recovery", "score", "latest"),
        ("resilience_score", "Resilience score", "device_recovery", "score", "latest"),
        ("body_battery_score", "Body Battery score", "device_recovery", "score", "latest"),
        ("strain_score", "Strain score", "device_recovery", "score", "latest"),
        ("health_recovery_score", "Health recovery score", "device_recovery", "score", "latest"),
    )
}

#: Which metric keys each datatype owns — the delete scope of its recompute.
#: A key owned by two datatypes would have each sync delete the other's days.
DATATYPE_KEYS: dict[str, tuple[str, ...]] = {
    # Steps, distance, floors, active energy and daily heart rate are owned by
    # the raw recompute (DAILY_RAW_METRICS), which cuts them at local midnight.
    # The activity summary still writes them -- the only copy when no raw
    # samples arrive -- but never deletes them, and the raw pass that follows
    # it in every sync job replaces its UTC-cut rows window by window.
    "activity": (
        "active_minutes", "sedentary_minutes", "light_activity", "total_energy", "elevation",
        "moderate_activity", "vigorous_activity",
    ),
    "sleep": (
        "sleep_duration", "time_in_bed", "sleep_efficiency", "sleep_deep", "sleep_rem",
        "sleep_core", "sleep_awake", "heart_rate_variability", "respiratory_rate",
        "blood_oxygen", "sleeping_heart_rate", "heart_rate_variability_rmssd",
        "sleep_interruptions", "sleep_naps", "sleep_nap_duration",
    ),
    "recovery": ("recovery_score", "resting_heart_rate"),
    "scores": (
        "sleep_score", "readiness_score", "activity_score", "stress_score",
        "resilience_score", "body_battery_score", "strain_score", "health_recovery_score",
    ),
    "body_series": (
        "body_weight", "body_height", "body_fat_percentage", "body_mass_index",
        "lean_body_mass", "waist_circumference", "vo2_max",
    ),
}

#: Sparse series used for daily body measurements. The durable worker also
#: archives all raw series independently, including unmapped sample types.
BODY_SERIES = {
    "weight": "body_weight",
    "height": "body_height",
    "body_fat_percentage": "body_fat_percentage",
    "body_mass_index": "body_mass_index",
    "lean_body_mass": "lean_body_mass",
    "waist_circumference": "waist_circumference",
    "vo2_max": "vo2_max",
}

# Exact API series -> established catalog concepts which daily summaries do
# not contain. No new reference interval or scoring interpretation is added.
RAW_METRICS = {
    "blood_pressure_systolic": "systolic_blood_pressure",
    "blood_pressure_diastolic": "diastolic_blood_pressure",
    "walking_heart_rate_average": "walking_heart_rate",
    "heart_rate_recovery_one_minute": "heart_rate_recovery",
    "distance_cycling": "cycling_distance",
    "distance_swimming": "swimming_distance",
    "swimming_stroke_count": "swimming_strokes",
    "basal_energy": "resting_energy",
    "exercise_time": "exercise_minutes",
    "stand_time": "stand_minutes",
    "walking_speed": "walking_speed",
    "walking_step_length": "walking_step_length",
    "walking_double_support_percentage": "walking_double_support",
    "walking_asymmetry_percentage": "walking_asymmetry",
    "walking_steadiness": "walking_steadiness",
    "stair_ascent_speed": "stair_ascent_speed",
    "stair_descent_speed": "stair_descent_speed",
    "six_minute_walk_test_distance": "six_minute_walk",
    "time_in_daylight": "time_in_daylight",
    "environmental_audio_exposure": "environmental_audio",
    "headphone_audio_exposure": "headphone_audio",
    "environmental_sound_reduction": "environmental_sound_reduction",
}
#: Series types a newer server *answers* with for a type requested under its
#: old name. OpenWearables 0.11 renamed walking_heart_rate_average; requests
#: keep the old spelling (0.10 rejects the new one), responses may carry
#: either, and an unmapped row would read as a deleted day.
RAW_METRIC_RENAMES = {"walking_heart_rate": "walking_heart_rate"}
DEFS.update({key: _BY_KEY[key] for key in RAW_METRICS.values()})

# OpenWearables serializes its internal unit enum values, not display labels.
# Keep this compatibility vocabulary at this API boundary, with exact physical
# conversions delegated to the shared converter. Never infer units from values.
_API_UNITS = {
    "percent": "%", "kg_m2": "kg/m²", "m_per_s": "m/s", "meters": "m",
    "brpm": "breaths/min", "seconds": "s", "minutes": "min", "hours": "hours",
    "celsius": "°C", "fahrenheit": "°F", "ml_kg_min": "mL/kg/min",
}


def _api_quantity(row: dict, target: str) -> float | None:
    unit = str(row.get("unit") or "")
    return convert_quantity(_num(row.get("value")), _API_UNITS.get(unit, unit), target)

# The API contract exposes all of these as named health-score categories. They
# remain separate manufacturer-defined concepts: a stress score is not merged
# with Garmin's average stress level, and the health-score recovery category is
# not merged with the recovery summary's own score.
_SCORE_KEYS = {
    "sleep": "sleep_score",
    "readiness": "readiness_score",
    "activity": "activity_score",
    "stress": "stress_score",
    "resilience": "resilience_score",
    "body_battery": "body_battery_score",
    "body battery": "body_battery_score",
    "strain": "strain_score",
    "recovery": "health_recovery_score",
}

_SLEEP_STAGE_FIELDS = (
    ("deep_minutes", "sleep_deep"),
    ("rem_minutes", "sleep_rem"),
    ("light_minutes", "sleep_core"),
    ("awake_minutes", "sleep_awake"),
)


def _num(value: object) -> float | None:
    return finite_number(value)


def _source_label(row: dict | None) -> str:
    source = row.get("source") if isinstance(row, dict) else None
    if not isinstance(source, dict) and isinstance(row, dict):
        source = {"provider": row.get("provider"), "device": row.get("device")}
    if not isinstance(source, dict):
        return SOURCE_NAME
    parts = [str(source.get(field) or "").replace("\u00a0", " ").strip() for field in ("provider", "source", "device")]
    parts = [part for part in parts if part and part.casefold() != SOURCE_NAME.casefold()]
    return " · ".join((SOURCE_NAME, *parts)) if parts else SOURCE_NAME


def _aggregate(
    bucket: dict, key: str, day: str, value: float | None, observed: str = "",
    source_row: dict | None = None,
) -> None:
    # The day-length guard is here rather than only in the mappers: a sample
    # with a null timestamp would otherwise write a day='' row that the
    # BETWEEN-scoped delete never removes and the detail page cannot parse.
    if value is None or len(day) != 10:
        return
    source_name = _source_label(source_row)
    item = bucket.get((key, day, source_name))
    if item is None:
        item = Aggregate(DEFS[key], day, source_name, SOURCE_NAME)
        bucket[(key, day, source_name)] = item
    item.add(value, observed or day)


def _scaled(row: dict, field: str, scale: float = 1.0) -> float | None:
    value = _num(row.get(field))
    return value * scale if value is not None else None


def _map_daily_heart_rate(bucket: dict, day: str, row: dict, heart: dict) -> None:
    _aggregate(bucket, "daily_heart_rate", day, _num(heart.get("avg_bpm")), source_row=row)
    item = bucket.get(("daily_heart_rate", day, _source_label(row)))
    # The server averaged the whole day; its own min and max are the
    # real range, which one averaged sample cannot reconstruct.
    if item is None:
        return
    low, high = _num(heart.get("min_bpm")), _num(heart.get("max_bpm"))
    if low is not None:
        item.value_min = low
    if high is not None:
        item.value_max = high


def _map_activity(rows: list[dict], bucket: dict, tz: tzinfo | None = None) -> None:
    # The summary's `date` is the server's UTC day.  The daily totals it also
    # carries (steps, distance, floors, active energy, heart rate) are rebuilt
    # per local day from the raw samples, which own those keys and run after
    # this mapper; its other fields have no raw series and keep the server day.
    for row in rows:
        day = str(row.get("date") or "")[:10]
        if len(day) != 10:
            continue
        _aggregate(bucket, "steps", day, _num(row.get("steps")), source_row=row)
        _aggregate(bucket, "walking_running_distance", day, _scaled(row, "distance_meters", 1 / 1000), source_row=row)
        _aggregate(bucket, "flights_climbed", day, _num(row.get("floors_climbed")), source_row=row)
        _aggregate(bucket, "active_energy", day, _num(row.get("active_calories_kcal")), source_row=row)
        _aggregate(bucket, "active_minutes", day, _num(row.get("active_minutes")), source_row=row)
        _aggregate(bucket, "sedentary_minutes", day, _num(row.get("sedentary_minutes")), source_row=row)
        _aggregate(bucket, "total_energy", day, _num(row.get("total_calories_kcal")), source_row=row)
        _aggregate(bucket, "elevation", day, _num(row.get("elevation_meters")), source_row=row)
        intensity = row.get("intensity_minutes")
        if isinstance(intensity, dict):
            _aggregate(bucket, "light_activity", day, _num(intensity.get("light")), source_row=row)
            _aggregate(bucket, "moderate_activity", day, _num(intensity.get("moderate")), source_row=row)
            _aggregate(bucket, "vigorous_activity", day, _num(intensity.get("vigorous")), source_row=row)
        heart = row.get("heart_rate")
        if isinstance(heart, dict):
            _map_daily_heart_rate(bucket, day, row, heart)


def _map_sleep(rows: list[dict], bucket: dict, tz: tzinfo | None = None) -> None:
    for row in rows:
        # The server dates a night by its local wake date (a night ending
        # 23:58Z is dated the next day), the convention the Apple and Oura
        # importers use, so the rows line up day for day.
        day = str(row.get("date") or "")[:10]
        if len(day) != 10:
            continue
        observed = str(row.get("start_time") or day)
        _aggregate(bucket, "sleep_duration", day, _scaled(row, "duration_minutes", 1 / 60), observed, row)
        _aggregate(bucket, "time_in_bed", day, _scaled(row, "time_in_bed_minutes", 1 / 60), observed, row)
        _aggregate(bucket, "sleep_efficiency", day, _num(row.get("efficiency_percent")), observed, row)
        _aggregate(bucket, "heart_rate_variability", day, _num(row.get("avg_hrv_sdnn_ms")), observed, row)
        _aggregate(bucket, "heart_rate_variability_rmssd", day, _num(row.get("avg_hrv_rmssd_ms")), observed, row)
        _aggregate(bucket, "respiratory_rate", day, _num(row.get("avg_respiratory_rate")), observed, row)
        _aggregate(bucket, "blood_oxygen", day, _num(row.get("avg_spo2_percent")), observed, row)
        _aggregate(bucket, "sleeping_heart_rate", day, _num(row.get("avg_heart_rate_bpm")), observed, row)
        _aggregate(bucket, "sleep_interruptions", day, _num(row.get("interruptions_count")), observed, row)
        # nap_count / nap_duration_minutes are not mapped: the server reports
        # 0 for every night of every account (1,358 rows, all zero), which is
        # "this source does not detect naps", not "no naps".
        stages = row.get("stages")
        if not isinstance(stages, dict):
            continue
        minutes = {field: _num(stages.get(field)) for field, _key in _SLEEP_STAGE_FIELDS}
        # A phone-only night reports all four stages as 0: that is "this
        # tracker cannot stage sleep", not a night with no deep sleep at all.
        if not any(minutes.values()):
            continue
        for field, key in _SLEEP_STAGE_FIELDS:
            if minutes[field] is not None:
                _aggregate(bucket, key, day, minutes[field] / 60, observed, row)


def _map_recovery(rows: list[dict], bucket: dict, tz: tzinfo | None = None) -> None:
    for row in rows:
        day = str(row.get("date") or "")[:10]
        if len(day) != 10:
            continue
        # A resting-HR row rebuilt from a sample carries the sample's instant,
        # so a "not my reading" rule on that instant can match it.
        observed = str(row.get("timestamp") or "")
        _aggregate(bucket, "recovery_score", day, _num(row.get("recovery_score")), observed, row)
        _aggregate(bucket, "resting_heart_rate", day, _num(row.get("resting_heart_rate_bpm")), observed, row)
        # sleep_duration_seconds, sleep_efficiency_percent, avg_hrv_sdnn_ms and
        # avg_spo2_percent repeat the sleep summary, which owns those keys.


def _map_scores(rows: list[dict], bucket: dict, tz: tzinfo | None = None) -> None:
    for row in rows:
        category = str(row.get("category") or "").casefold().replace("-", "_")
        key = _SCORE_KEYS.get(category)
        recorded = str(row.get("recorded_at") or "")
        if key:
            _aggregate(bucket, key, local_day(recorded, tz), _num(row.get("value")), recorded, row)


def _map_body_series(rows: list[dict], bucket: dict, tz: tzinfo | None = None) -> None:
    for row in rows:
        key = BODY_SERIES.get(str(row.get("type") or ""))
        stamp = str(row.get("timestamp") or "")
        if key:
            # The person's local day; "latest" keys take that day's last sample.
            try:
                value = _api_quantity(row, DEFS[key].unit)
            except ValueError as exc:
                raise OpenWearablesError(str(exc)) from exc
            _aggregate(bucket, key, local_day(stamp, tz), value, stamp, row)


def _raw_key(row: dict) -> str | None:
    kind = str(row.get("type") or "")
    return RAW_METRICS.get(kind) or DAILY_RAW_METRICS.get(kind) or RAW_METRIC_RENAMES.get(kind)


def map_raw_metrics(rows, bucket: dict, tz: tzinfo | None = None) -> set[str]:
    """Normalize known granular metrics into local-day aggregates, one pass.

    A daily total replaces intraday fragments for the same source/day, and
    repeated totals use the newest timestamp instead of being summed.  A
    series in a unit the converter does not know is skipped and returned, so
    one bad series never costs the others their days.
    """
    fragments: dict[tuple[str, str, str], dict] = {}
    totals: dict[tuple[str, str, str], dict] = {}
    failed: set[str] = set()
    for row in rows:
        key = _raw_key(row)
        if not key or key in failed:
            continue
        stamp = str(row.get("timestamp") or "")
        day = local_day(stamp, tz)
        try:
            value = _api_quantity(row, DEFS[key].unit)
        except ValueError:
            failed.add(key)
            continue
        group = (key, day, _source_label(row))
        if row.get("is_daily_total") is True and DEFS[key].aggregation == "sum":
            previous = totals.get(group)
            if previous is None or stamp > previous["stamp"]:
                totals[group] = {"stamp": stamp, "value": value, "row": row}
            continue
        fragments.setdefault(group, {"items": []})["items"].append((value, stamp, row))
    _store_raw_groups(bucket, totals, fragments, failed)
    return failed


def _store_raw_groups(bucket: dict, totals: dict, fragments: dict, failed: set[str]) -> None:
    for group, entry in totals.items():
        if group[0] not in failed:
            _aggregate(bucket, group[0], group[1], entry["value"], entry["stamp"], entry["row"])
    for group, entry in fragments.items():
        if group in totals or group[0] in failed:
            continue
        for value, stamp, row in entry["items"]:
            _aggregate(bucket, group[0], group[1], value, stamp, row)
    for key in failed:
        for group in [group for group in bucket if group[0] == key]:
            del bucket[group]


_MAPPERS = {
    "activity": _map_activity,
    "sleep": _map_sleep,
    "recovery": _map_recovery,
    "scores": _map_scores,
    "body_series": _map_body_series,
}

#: Datatypes whose rows are dated from a timestamp, so the fetch reaches back
#: one day: the first local day's early hours are the previous UTC day.
_TIMESTAMPED = frozenset({"recovery", "scores", "body_series"})

#: Datatype -> summary endpoint and its page size.
_SUMMARY_PATHS = {
    "activity": ("summaries/activity", _SUMMARY_LIMIT),
    "sleep": ("summaries/sleep", _PAGE_LIMIT),
    "recovery": ("summaries/recovery", _PAGE_LIMIT),
}


def _with_resting_samples(settings: Settings, remote: str, start: str, end: str,
                          tz: tzinfo | None, rows: list[dict]) -> list[dict]:
    """Upstream documents that its recovery summary currently only includes
    WHOOP. Pull actual resting-HR samples for other sources."""
    samples = _exhaustive_rows(settings, f"/users/{remote}/timeseries",
        {"start_time": _day_shift(start, -1) + "T00:00:00Z", "end_time": end + "T23:59:59.999999Z", "types": ["resting_heart_rate"]},
        _PAGE_LIMIT, _advance_timestamps)
    samples = [s for s in samples if s.get("type") == "resting_heart_rate"]
    replaced = {(local_day(str(s.get("timestamp") or ""), tz), _source_label(s)) for s in samples}
    rows = [dict(row, resting_heart_rate_bpm=None) if (str(row.get("date") or "")[:10], _source_label(row)) in replaced else row for row in rows]
    for sample in samples:
        try:
            value = _api_quantity(sample, "bpm")
        except ValueError as exc:
            raise OpenWearablesError(str(exc)) from exc
        rows.append({"date": local_day(str(sample.get("timestamp") or ""), tz), "source": sample.get("source"),
                     "timestamp": sample.get("timestamp"), "resting_heart_rate_bpm": value})
    return rows


def _fetch(settings: Settings, remote: str, datatype: str, start: str, end: str,
           tz: tzinfo | None = None) -> list[dict]:
    if datatype in _SUMMARY_PATHS:
        path, limit = _SUMMARY_PATHS[datatype]
        rows = _exhaustive_rows(
            settings, f"/users/{remote}/{path}", {"start_date": start, "end_date": _day_shift(end, 1)},
            limit, _advance_dates,
        )
        rows = [row for row in rows if start <= str(row.get("date") or "")[:10] <= end]
        if datatype == "recovery":
            rows = _with_resting_samples(settings, remote, start, end, tz, rows)
        return rows
    if datatype == "scores":
        # Use matching date-only edges: deployed score handlers reject mixed
        # naive/aware query dates. Next midnight preserves the complete day;
        # the day before carries the first local day's early hours.
        rows = _offset_pages(
            settings, f"/users/{remote}/health-scores",
            {"start_date": _day_shift(start, -1), "end_date": _day_shift(end, 1)}, _SCORE_LIMIT,
        )
        return [row for row in rows if start <= local_day(str(row.get("recorded_at") or ""), tz) <= end]
    return _exhaustive_rows(
        settings, f"/users/{remote}/timeseries",
        {
            "start_time": f"{_day_shift(start, -1)}T00:00:00Z",
            "end_time": f"{end}T23:59:59.999999Z",
            "types": list(BODY_SERIES),
        },
        _PAGE_LIMIT, _advance_timestamps,
    )


def _in_window(aggregates, start: str, end: str) -> list[Aggregate]:
    """Only the local days the window owns: a fetch that reached into the
    neighbouring days for their boundary hours must not write partial copies
    of those days over complete ones."""
    return [item for item in aggregates if start <= item.day <= end]


#: Raw series -> the daily key it is aggregated into, per local day.  The
#: activity summary carries these totals too, cut at UTC midnight; the raw
#: recompute runs after it and replaces them (the `summary == UTC sum of raw`
#: identity was checked for every day of June 2025 on the live account).
DAILY_RAW_METRICS = {
    "steps": "steps",
    "distance_walking_running": "walking_running_distance",
    "flights_climbed": "flights_climbed",
    "active_energy": "active_energy",
    # The server's name for active energy before September 2020: its activity
    # summary equals this series' UTC-day sum on every day both exist.
    "energy": "active_energy",
    "heart_rate": "daily_heart_rate",
}


def raw_metric_keys() -> tuple[str, ...]:
    return tuple(dict.fromkeys([*RAW_METRICS.values(), *DAILY_RAW_METRICS.values()]))


DATATYPE_KEYS["raw_metrics"] = raw_metric_keys()


def _stored_samples(db, user_id: str, server_url: str, remote_user_id: str, lower: str, upper: str,
                    series_type: str | None = None):
    """Archived samples with ``lower <= timestamp < upper`` (UTC instants), read
    through the archive's one reader so compacted days are seen (F11)."""
    from . import openwearables_archive as archive

    for row in archive.iter_samples(db, user_id, server_url, remote_user_id, lower[:10], upper[:10], series_type):
        stamp = str(row.get("timestamp") or "")
        if lower <= stamp < upper:
            yield row


def recompute_raw_days(settings: Settings, db, user_id: str, import_id: str, expected: tuple,
                       start: str, end: str, tz: tzinfo | None = None, *, verify_account: bool = True) -> set[str]:
    """Rebuild local days [start, end] of every raw-owned key from the samples
    stored for the account.  Runs inside the caller's write transaction after
    the window's samples were committed, so the first local day's early hours
    (the previous UTC day, fetched by the previous window) are included.
    Returns the keys whose series carried an unknown unit (left untouched)."""
    tz = tz or user_timezone(db, user_id)
    lower, upper = local_bounds_utc(start, end, tz)
    bucket: dict = {}
    covered: set[tuple[str, str, str]] = set()

    def samples():
        for row in _stored_samples(db, user_id, expected[1], expected[0], lower, upper):
            key = _raw_key(row)
            if key:
                covered.add((key, _source_label(row), str(row.get("timestamp") or "")[:10]))
            yield row

    # Exclusions apply inside the mapper, after `covered` saw the sample: an
    # excluded reading still covers its day, so the summary below cannot
    # bring it back, and the summary's own rows pass the same rules.
    with exclusions.applying(db, user_id):
        failed = map_raw_metrics(samples(), bucket, tz)
        # A summary day the raw store holds no sample for (the server summarised
        # it, the raw history has a hole) keeps the summary's value, on the
        # summary's own date: re-cutting is never a reason to lose a day.
        archived = [json.loads(payload) for (payload,) in db.execute(
            """SELECT payload_json FROM openwearables_raw_records WHERE owner_user_id=? AND server_url=?
               AND remote_user_id=? AND datatype='activity' AND day BETWEEN ? AND ?""",
            (user_id, expected[1], expected[0], start, end))]
        summary: dict = {}
        _map_activity(archived, summary, tz)
    for (key, day, source), item in summary.items():
        if key in DAILY_RAW_METRICS.values() and (key, source, day) not in covered and (key, day, source) not in bucket:
            bucket[(key, day, source)] = item
    _write_days(settings, user_id, import_id, _in_window(bucket.values(), start, end),
                tuple(key for key in raw_metric_keys() if key not in failed),
                start, end, expected, db_connection=db, verify_account=verify_account)
    return failed


# --- persistence -------------------------------------------------------------


def _patient_id(settings: Settings, user_id: str) -> str:
    with connect(settings) as db:
        row = db.execute(
            "SELECT id FROM patients WHERE owner_user_id=? ORDER BY created_at LIMIT 1", (user_id,)
        ).fetchone()
    if row is None:
        raise OpenWearablesError("openwearables: no patient profile to attach device data to")
    return str(row["id"])


def ensure_envelope(settings: Settings, user_id: str) -> str:
    """The one device_imports row every synced row hangs from.

    The file importers fingerprint bytes; an API link has none, so the
    fingerprint is the account itself and the row doubles as the sync-state
    store (metadata_json: the remote account, last sync, failures).
    """
    import_id = stable_id("device-import", f"{user_id}:{ADAPTER_KEY}:api")
    patient_id = _patient_id(settings, user_id)
    with connect(settings) as db:
        vendor_id = ensure_vendor(db, SOURCE_NAME, VENDOR_WEBSITE)
        db.execute(
            """INSERT INTO device_imports(
                   id, owner_user_id, patient_id, vendor_id, adapter_key, source_path,
                   source_fingerprint, source_bytes, raw_record_count, status,
                   metadata_json, imported_at)
               VALUES (?, ?, ?, ?, ?, 'openwearables://api', 'api', 0, 0, 'complete', '{}', ?)
               ON CONFLICT(owner_user_id, adapter_key, source_fingerprint) DO NOTHING""",
            (import_id, user_id, patient_id, vendor_id, ADAPTER_KEY, utc_now()),
        )
    return import_id


def sync_state(settings: Settings, user_id: str) -> dict:
    with connect(settings) as db:
        row = db.execute(
            _STATE_SQL,
            (user_id, ADAPTER_KEY),
        ).fetchone()
    try:
        return json.loads(row["metadata_json"]) if row else {}
    except json.JSONDecodeError:
        return {}


def _update_state(settings: Settings, user_id: str, **values: object) -> None:
    with transaction(settings, immediate=True) as db:
        row = db.execute(_STATE_SQL, (user_id, ADAPTER_KEY)).fetchone()
        state = {**(json.loads(row[0]) if row else {}), **values}
        db.execute(
            """UPDATE device_imports SET metadata_json=?, imported_at=?,
                      raw_record_count=(SELECT COUNT(*) FROM device_metric_days WHERE import_id=device_imports.id)
                WHERE owner_user_id=? AND adapter_key=?""",
            (json.dumps(state, ensure_ascii=False), utc_now(), user_id, ADAPTER_KEY),
        )


def _write_days(settings: Settings, user_id: str, import_id: str,
                aggregates: list[Aggregate], owned_keys: tuple[str, ...],
                start: str, end: str, expected_account: tuple[str, str], *, db_connection=None,
                verify_account: bool = True) -> int:
    """Upsert the recomputed days, then drop this envelope's days in the window
    the server no longer reports.  Runs only after the whole window arrived.

    ``verify_account=False`` is for a rebuild from the local archive alone
    (exclusions): nothing fetched can be another person's, and the archive is
    read inside the same write transaction a relink would purge it in."""
    patient_id = _patient_id(settings, user_id)
    now = utc_now()
    aggregates = plausible_aggregates(aggregates)
    with (nullcontext(db_connection) if db_connection is not None else transaction(settings, immediate=True)) as db:
        if verify_account:
            _check_sync_account(db, settings, user_id, expected_account)
        # Recompute the requested window as one atomic replacement. Source
        # identity is part of the natural key, so deleting only the generic
        # `OpenWearables` name would strand rows after the API starts naming
        # their upstream provider, and retaining a day just because another
        # source still reports it would strand the vanished source too.
        removed = 0
        for key in owned_keys:
            removed += db.execute(
                """DELETE FROM device_metric_days
                   WHERE owner_user_id=? AND import_id=? AND metric_key=?
                     AND day BETWEEN ? AND ?""",
                (user_id, import_id, key, start, end),
            ).rowcount
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
    if removed:
        logger.info("openwearables: removed %d stale day(s) for %s in %s..%s", removed, owned_keys, start, end)
    return len(aggregates)


def _write_workouts(settings: Settings, user_id: str, import_id: str, workouts: list[Workout],
                    start: str, end: str, expected_account: tuple[str, str], *, db_connection=None,
                    verify_account: bool = True) -> int:
    patient_id = _patient_id(settings, user_id)
    now = utc_now()
    with (nullcontext(db_connection) if db_connection is not None else transaction(settings, immediate=True)) as db:
        if verify_account:
            _check_sync_account(db, settings, user_id, expected_account)
        db.execute(
            "DELETE FROM device_workouts WHERE owner_user_id=? AND import_id=? AND substr(started_at, 1, 10) BETWEEN ? AND ?",
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
    return len(workouts)


def _write_events(settings: Settings, user_id: str, import_id: str, events: list[DeviceEvent],
                  start: str, end: str, expected_account: tuple[str, str], *, db_connection=None,
                  verify_account: bool = True) -> int:
    patient_id = _patient_id(settings, user_id)
    now = utc_now()
    with (nullcontext(db_connection) if db_connection is not None else transaction(settings, immediate=True)) as db:
        if verify_account:
            _check_sync_account(db, settings, user_id, expected_account)
        db.execute(
            "DELETE FROM device_events WHERE owner_user_id=? AND import_id=? AND event_type=? AND substr(started_at, 1, 10) BETWEEN ? AND ?",
            (user_id, import_id, EVENT_CYCLE, start, end),
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
                   value_text=excluded.value_text, value_numeric=excluded.value_numeric,
                   unit=excluded.unit, created_at=excluded.created_at""",
            [
                (
                    stable_id("device-event", f"{user_id}:{e.event_type}:{e.started_at}:{e.source_name}"),
                    user_id, patient_id, import_id, e.source_name, e.source_vendor,
                    e.event_type, e.started_at, e.ended_at, e.value_text, e.value_numeric,
                    e.unit, None, now,
                )
                for e in events
            ],
        )
    return len(events)


# --- linking a remote account ------------------------------------------------


def linked(settings: Settings, user_id: str):
    with connect(settings) as db:
        return db.execute(
            "SELECT * FROM provider_connections WHERE user_id=? AND provider=?",
            (user_id, PROVIDER),
        ).fetchone()


def _remote_user_id(settings: Settings, user_id: str) -> str:
    row = linked(settings, user_id)
    remote = str(row["external_user_id"]) if row else ""
    if not remote:
        raise OpenWearablesError("openwearables: no remote account is linked")
    return remote


def _check_sync_account(db, settings: Settings, user_id: str, expected: tuple[str, str]) -> None:
    """Check inside the write transaction: a relink must not race the insert."""
    row = db.execute(
        "SELECT external_user_id FROM provider_connections WHERE user_id=? AND provider=?", (user_id, PROVIDER)
    ).fetchone()
    if row is None or (str(row["external_user_id"]), ow_settings(settings)["url"]) != expected[:2]:
        raise OpenWearablesError("openwearables: linked account changed during sync; retry for the current account")
    if len(expected) > 2:
        state = db.execute(_STATE_SQL, (user_id, ADAPTER_KEY)).fetchone()
        if not state or json.loads(state[0]).get("link_generation", "") != expected[2]:
            raise OpenWearablesError("openwearables: linked account changed during sync")
    if len(expected) > 4:
        lease = db.execute("SELECT status,lease_token,lease_until FROM openwearables_sync_jobs WHERE id=?", (expected[3],)).fetchone()
        if not lease or lease["status"] != "running" or lease["lease_token"] != expected[4] or lease["lease_until"] <= time.time():
            raise OpenWearablesError("openwearables: synchronization lease expired")


def account_identity(settings: Settings, user_id: str) -> tuple[str, str, str]:
    return (_remote_user_id(settings, user_id), ow_settings(settings)["url"], str(sync_state(settings, user_id).get("link_generation", "")))


def linked_elsewhere(settings: Settings, user_id: str, remote_user_id: str) -> bool:
    """Whether another local account already holds this remote account.  Two
    records fed by one person's wearable is the mix-up this integration exists
    to prevent, whoever asks for it."""
    with connect(settings) as db:
        return db.execute(
            "SELECT 1 FROM provider_connections WHERE provider=? AND external_user_id=? AND user_id<>?",
            (PROVIDER, remote_user_id, user_id),
        ).fetchone() is not None


def link_account(settings: Settings, user_id: str, remote_user_id: str, remote_email: str) -> bool:
    """Point this account at one remote account.

    Returns True when that *replaced* a different one, in which case every row
    the previous link wrote has been deleted: they were another person's
    measurements, and merging two people's days into one record is the one
    outcome this integration must never produce.  Rows from file imports and
    from other APIs are untouched — the purge is scoped to this envelope.
    """
    import_id = ensure_envelope(settings, user_id)
    now = utc_now()
    with transaction(settings, immediate=True) as db:
        state = json.loads(db.execute("SELECT metadata_json FROM device_imports WHERE id=?", (import_id,)).fetchone()[0])
        previous = str(state.get("remote_user_id") or "")
        server = ow_settings(settings)["url"]
        replaced = bool(previous) and (previous != remote_user_id or state.get("remote_server_url", server) != server)
        if replaced:
            for table in ("device_metric_days", "device_workouts", "device_events"):
                db.execute(f"DELETE FROM {table} WHERE import_id=?", (import_id,))
            db.execute("DELETE FROM openwearables_raw_records WHERE owner_user_id=?", (user_id,))
            from .openwearables_archive import purge_owner
            purge_owner(db, user_id)
            db.execute("DELETE FROM openwearables_receipt_targets WHERE owner_user_id=?", (user_id,))
        db.execute(
            """INSERT INTO provider_connections(user_id, provider, access_token, refresh_token,
                       token_expires_at, external_user_id, scopes, connected_at, updated_at, status)
               VALUES (?, ?, '', '', NULL, ?, '', ?, ?, 'active')
               ON CONFLICT(user_id, provider) DO UPDATE SET
                   external_user_id=excluded.external_user_id,
                   updated_at=excluded.updated_at, status='active'""",
            (user_id, PROVIDER, remote_user_id, now, now),
        )
        if replaced:
            state.update(last_sync_at="", last_backfill_at="", backfill_counts={}, failed_datatypes={})
        state.update(remote_user_id=remote_user_id, remote_email=remote_email, remote_server_url=server,
                     link_generation=uuid.uuid4().hex)
        db.execute("UPDATE openwearables_sync_jobs SET status='cancelled', updated_at=? WHERE owner_user_id=? AND status IN ('queued','running','retry')", (now, user_id))
        db.execute(
            """UPDATE device_imports SET metadata_json=?, imported_at=?,
                raw_record_count=(SELECT COUNT(*) FROM device_metric_days WHERE import_id=?) WHERE id=?""",
            (json.dumps(state, ensure_ascii=False), now, import_id, import_id),
        )
    return replaced


def unlink_account(settings: Settings, user_id: str) -> None:
    """Stop syncing.  Everything already written stays — it is this person's
    own record. Re-linking creates a new generation and schedules reconciliation
    of the recent window and history without discarding that retained record."""
    with connect(settings) as db:
        db.execute(
            "DELETE FROM provider_connections WHERE user_id=? AND provider=?", (user_id, PROVIDER)
        )
        db.execute("UPDATE openwearables_sync_jobs SET status='cancelled', updated_at=? WHERE owner_user_id=? AND status IN ('queued','running','retry')", (utc_now(), user_id))


# --- sync: the windowed recompute --------------------------------------------


def sync_datatype(settings: Settings, user_id: str, datatype: str, start: str, end: str, expected_account: tuple | None = None) -> int:
    """Fetch one datatype for [start, end] and make the stored days match."""
    expected_account = expected_account or account_identity(settings, user_id)
    remote = expected_account[0]
    tz = user_timezone_for(settings, user_id)
    rows = _fetch(settings, remote, datatype, start, end, tz)
    bucket: dict[tuple[str, str, str], Aggregate] = {}
    from .openwearables_webhooks import archive_records
    archive_records(settings, user_id, datatype, rows, start, end, expected_account)
    import_id = ensure_envelope(settings, user_id)
    with transaction(settings, immediate=True) as db:
        # Mapped inside the transaction that replaces the window: an exclusion
        # saved at any moment of this sync is either seen here or saved after
        # this commit, and then its own rebuild removes the reading.
        with exclusions.applying(db, user_id):
            _MAPPERS[datatype](rows, bucket, tz)
        written = _write_days(
            settings, user_id, import_id, _in_window(bucket.values(), start, end), DATATYPE_KEYS[datatype],
            start, end, expected_account, db_connection=db,
        )
        if datatype == "activity":
            # The daily totals the summary repeats belong to the raw recompute:
            # rebuild them now from stored samples and the archive just refreshed,
            # so a day the server withdrew disappears with this sync, not later.
            recompute_raw_days(settings, db, user_id, import_id, expected_account, start, end, tz)
    return written


def sync_workouts(settings: Settings, user_id: str, start: str, end: str, expected_account: tuple | None = None) -> int:
    """Reconcile the complete fetched window, including removed sessions."""
    expected_account = expected_account or account_identity(settings, user_id)
    remote = expected_account[0]
    import_id = ensure_envelope(settings, user_id)
    rows = _exhaustive_rows(
        settings, f"/users/{remote}/events/workouts",
        {"start_date": start, "end_date": _day_shift(end, 1)}, _PAGE_LIMIT, _advance_descending,
    )
    rows = [row for row in rows if start <= str(row.get("start_time") or "")[:10] <= end]
    from .openwearables_webhooks import archive_records
    archive_records(settings, user_id, "workouts", rows, start, end, expected_account)
    with transaction(settings, immediate=True) as db:
        workouts = workouts_from_rows(rows, exclusions.matcher(db, user_id))
        return _write_workouts(settings, user_id, import_id, workouts, start, end, expected_account, db_connection=db)


def workouts_from_rows(rows: list[dict], rules=None) -> list[Workout]:
    """Archived or fetched workout sessions, less those excluded as not the
    person's (``rules``: an exclusions matcher, or None)."""
    workouts: list[Workout] = []
    for row in rows:
        started = str(row.get("start_time") or "")
        if not started:
            continue
        duration = _num(row.get("duration_seconds"))
        distance = _num(row.get("distance_meters"))
        workout = Workout(
            source_name=_source_label(row), source_vendor=SOURCE_NAME,
            workout_type=str(row.get("type") or "workout"),
            started_at=started, ended_at=str(row.get("end_time") or "") or None,
            duration_minutes=duration / 60 if duration is not None else None,
            energy_kcal=_num(row.get("calories_kcal")),
            distance_km=distance / 1000 if distance is not None else None,
        )
        if rules is None or not rules.excludes(workout.source_name, exclusions.WORKOUTS, started, workout.ended_at):
            workouts.append(workout)
    return workouts


def sync_cycles(settings: Settings, user_id: str, start: str, end: str, expected_account: tuple | None = None) -> int:
    expected_account = expected_account or account_identity(settings, user_id)
    remote = expected_account[0]
    import_id = ensure_envelope(settings, user_id)
    rows = _exhaustive_rows(
        settings, f"/users/{remote}/events/menstrual-cycles",
        {"start_date": start, "end_date": _day_shift(end, 1)}, _PAGE_LIMIT, _advance_descending,
    )
    rows = [row for row in rows if start <= str(row.get("start_time") or "")[:10] <= end]
    from .openwearables_webhooks import archive_records
    archive_records(settings, user_id, "cycles", rows, start, end, expected_account)
    with transaction(settings, immediate=True) as db:
        events = cycles_from_rows(rows, exclusions.matcher(db, user_id))
        return _write_events(settings, user_id, import_id, events, start, end, expected_account, db_connection=db)


def cycles_from_rows(rows: list[dict], rules=None) -> list[DeviceEvent]:
    events: list[DeviceEvent] = []
    for row in rows:
        started = str(row.get("start_time") or "")
        # A predicted cycle is the server's forecast of a period that has not
        # happened; the record holds measurements, not expectations.
        if not started or row.get("is_predicted_cycle"):
            continue
        event = DeviceEvent(
            source_name=_source_label(row), source_vendor=SOURCE_NAME, event_type=EVENT_CYCLE,
            started_at=started, ended_at=str(row.get("end_time") or "") or None,
            value_text=str(row.get("current_phase_type") or "") or None,
            value_numeric=_num(row.get("cycle_length")), unit="days",
        )
        if rules is None or not rules.excludes(event.source_name, exclusions.EVENTS, started, event.ended_at):
            events.append(event)
    return events


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _sync_window(settings: Settings, user_id: str, start: str, end: str, expected: tuple | None = None) -> tuple[dict, dict]:
    """Every datatype for one window, each independent of the others: a server
    that refuses one dataset must not cost the person the other six."""
    counts: dict[str, int] = {}
    failed: dict[str, str] = {}
    expected = expected or account_identity(settings, user_id)
    for datatype in _MAPPERS:
        try:
            counts[datatype] = sync_datatype(settings, user_id, datatype, start, end, expected)
        except OpenWearablesError as exc:
            failed[datatype] = str(exc)[:200]
            logger.warning("openwearables: sync of %s failed: %s", datatype, exc)
    for slot, run in (("workouts", sync_workouts), ("cycles", sync_cycles)):
        try:
            counts[slot] = run(settings, user_id, start, end, expected)
        except OpenWearablesError as exc:
            failed[slot] = str(exc)[:200]
            logger.warning("openwearables: sync of %s failed: %s", slot, exc)
    return counts, failed


def backfill(settings: Settings, user_id: str) -> dict[str, int]:
    """Everything the server holds, from before any of it existed to today."""
    counts, failed = _sync_window(settings, user_id, EPOCH_DAY, _today())
    _update_state(settings, user_id, last_backfill_at=utc_now(), last_sync_at=utc_now(),
                  backfill_counts=counts, failed_datatypes=failed)
    return counts


def sync_recent(settings: Settings, user_id: str) -> dict[str, int]:
    """The manual button and the opportunistic refresh: the recent window."""
    start = (datetime.now(UTC).date() - timedelta(days=RECENT_WINDOW_DAYS)).isoformat()
    counts, failed = _sync_window(settings, user_id, start, _today())
    # Written even when empty: a clean sync clears failures recorded earlier.
    _update_state(settings, user_id, last_sync_at=utc_now(), failed_datatypes=failed)
    return counts


def failed_datatype_labels(settings: Settings, user_id: str) -> list[str]:
    """Datasets whose last sync failed, named by the measurements they carry
    rather than by an API identifier — "Deep sleep" says something to the
    person reading the page; "sleep" says something to the server."""
    failed = sync_state(settings, user_id).get("failed_datatypes") or {}
    return datatype_labels(failed)


def datatype_labels(datatypes) -> list[str]:
    """Localized dataset descriptions; unknown technical codes stay private."""
    labels: list[str] = []
    for datatype in sorted(datatypes):
        if datatype == "workouts":
            labels.append(t("devices.datatype_workouts"))
        elif datatype == "cycles":
            labels.append(translate_phrase(EVENT_CYCLE))
        elif datatype == "raw_timeseries":
            labels.append(t("ow_hooks.raw_dataset"))
        elif datatype == "sync":
            labels.append(t("ow_hooks.jobs"))
        else:
            names = [DEFS[key].name for key in DATATYPE_KEYS.get(datatype, ()) if key in DEFS]
            labels.append(", ".join(translate_phrase(name) for name in names) or t("ow_hooks.jobs"))
    return labels


# --- background entry points -------------------------------------------------

_inflight: set[str] = set()
_inflight_lock = threading.Lock()


def _spawn(name: str, target, *args) -> None:
    with _inflight_lock:
        if name in _inflight:
            return
        _inflight.add(name)

    def run() -> None:
        try:
            target(*args)
        except Exception:  # noqa: BLE001 — a sync must never take the request down
            logger.warning("openwearables: background %s failed", name, exc_info=True)
        finally:
            with _inflight_lock:
                _inflight.discard(name)

    threading.Thread(target=run, name=f"anamna-{name}", daemon=True).start()


def reset_module_state() -> None:
    """Forget in-flight background syncs (tests)."""
    with _inflight_lock:
        _inflight.clear()


def start_backfill(settings: Settings, user_id: str) -> None:
    from .openwearables_webhooks import enqueue_sync
    enqueue_sync(settings, [user_id], backfill=True)


def start_recent_sync(settings: Settings, user_id: str) -> None:
    from .openwearables_webhooks import enqueue_sync
    enqueue_sync(settings, [user_id])


def _age_seconds(stamp: str) -> float:
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(stamp)).total_seconds()
    except ValueError:
        return float("inf")


def maybe_refresh(settings: Settings, user_id: str) -> None:
    """Queue a stale account as an optional supplement to the scheduled worker."""
    if not configured(settings) or linked(settings, user_id) is None:
        return
    if _age_seconds(str(sync_state(settings, user_id).get("last_sync_at") or "")) < REFRESH_SECONDS:
        return
    start_recent_sync(settings, user_id)
