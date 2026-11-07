"""Readings that are not this person's: "not my reading", "not my device".

A bathroom scale shared by two people writes both people's weigh-ins into the
Apple Health of the phone it is paired with; OpenWearables then serves every
one of them as the phone owner's.  A watch handed down from one person to the
next keeps its model, so a device model alone never identifies whose a
reading is: a rule always names the writing app *and* the device.

A rule covers one reading (an instant: every series written at it, e.g. the
weight, BMI and body fat of one weigh-in), a window (values derived from a
wrong reading, such as energy a watch computed from someone else's weight), or
a whole origin.  The raw archive keeps everything, so a rule is reversible;
every aggregation entry point consults the rules as samples are added
(``Aggregate.add`` through ``EXCLUDING``), so a re-sync or re-import of the
same data stays excluded.  Read paths are never filtered: there are too many
of them, and a filter forgotten on one would show the reading again.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from statistics import median

from ..db import connect, transaction, utc_now
from .models import EXCLUDING
from .timezone import _instant, local_bounds_utc, user_timezone, user_timezone_for

logger = logging.getLogger("anamna.exclusions")

SCOPES = ("reading", "window", "origin")
OPENWEARABLES = "openwearables"
#: Series names for the two non-daily tables a rule can also cover.
WORKOUTS = "workouts"
EVENTS = "events"
#: File adapters: a rule they own names the export's own source name.
FILE_ADAPTERS = ("apple_health", "oura", "garmin", "kardia")
#: Direct provider APIs; their rows carry the same source names as the
#: provider's own file export ("Oura", "Garmin Index Scale").
API_ADAPTERS = ("oura_api", "garmin_api", "garmin_personal_api")
#: Every writer other than OpenWearables: a rule for one of these names the
#: stored source name, and the device is part of that name or not given.
ADAPTERS = FILE_ADAPTERS + API_ADAPTERS
#: Writers that store one origin under one name, so a rule made from any of
#: them reaches all of them.  OpenWearables' Apple source is HealthKit's
#: sourceName, the name an Apple Health export carries.
_GROUPS = (
    frozenset({"apple_health", "apple"}),
    frozenset({"oura", "oura_api"}),
    frozenset({"garmin", "garmin_api", "garmin_personal_api"}),
    frozenset({"kardia"}),
)


def _group(provider: str) -> frozenset[str]:
    return next((group for group in _GROUPS if provider in group), frozenset({provider}))
#: Rules spanning at most this many days are recalculated inside the request.
INLINE_DAYS = 31
#: A body reading this far from the person's own median is suggested for a
#: check.  ponytail: a fixed relative band; per-metric spread when it misfires.
SUGGEST_RATIO = 0.3
SUGGEST_MIN_DAYS = 5
SUGGEST_KEYS = frozenset({
    "body_weight", "body_mass_index", "body_fat_percentage", "lean_body_mass", "waist_circumference",
})
_SERIES_KEY = re.compile(r"[a-z0-9_]{1,64}")
_DATATYPES = ("activity", "sleep", "recovery", "scores", "body_series")
_MIDNIGHT = "T00:00:00"


class ExclusionError(ValueError):
    """A request that cannot become a rule; ``code`` names a message key."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def clean(value: object) -> str:
    return str(value or "").replace(" ", " ").strip()


def ow_label(provider: str, source: str, device: str) -> str:
    """The source name OpenWearables rows of this origin are stored under."""
    from ..openwearables import _source_label

    return _source_label({"source": {"provider": provider, "source": source, "device": device}})


def label_for(row, context: str) -> str | None:
    """The stored ``source_name`` this rule reaches in ``context`` (the
    OpenWearables sync, one file adapter or one provider API), or None."""
    provider = row["origin_provider"]
    if context == OPENWEARABLES:
        return None if provider in ADAPTERS else ow_label(provider, row["origin_source"], row["origin_device"])
    return row["origin_source"] if context in _group(provider) else None


def _when(text: object) -> tuple[datetime | None, date | None]:
    """An instant, or a bare day for a value the server dated itself."""
    text = str(text or "")
    moment = _instant(text)
    if moment is not None:
        return moment, None
    try:
        return None, date.fromisoformat(text[:10])
    except ValueError:
        return None, None


@dataclass(frozen=True)
class Rule:
    scope: str
    lower: datetime | None
    upper: datetime | None
    series: frozenset[str] | None

    def covers(self, key: str, moment: datetime | None, day: date | None, until: datetime | None,
               day_zone=UTC) -> bool:
        if self.series is not None and key not in self.series:
            return False
        if self.scope == "origin":
            return True
        if moment is None:
            # A daily total dated by its writer: a window that overlaps the
            # day removes the total whole; one reading never does.
            if self.scope != "window" or day is None:
                return False
            start = datetime.combine(day, time.min, day_zone)
            after = datetime.combine(day + timedelta(days=1), time.min, day_zone)
            return self.lower < after and self.upper >= start
        if self.scope == "reading":
            return moment == self.lower
        return self.lower <= (until or moment) and moment <= self.upper


class Matcher:
    """Active rules indexed by the stored source name they reach.

    ``day_zone`` is the zone a bare day is a calendar day in: OpenWearables
    summaries are dated in UTC by the server, every other writer dates a day
    in the person's own zone.
    """

    def __init__(self, rules: dict[str, list[Rule]], day_zone=UTC):
        self._rules = rules
        self._day_zone = day_zone

    def excludes(self, source_name: str, key: str, observed: object, until: object = None) -> bool:
        rules = self._rules.get(source_name)
        if not rules:
            return False
        moment, day = _when(observed)
        end = _when(until)[0] if until else None
        return any(rule.covers(key, moment, day, end, self._day_zone) for rule in rules)


def _rule(row) -> Rule:
    series = json.loads(row["series"]) if row["series"] else None
    return Rule(
        scope=row["scope"],
        lower=datetime.fromisoformat(row["from_utc"]) if row["from_utc"] else None,
        upper=datetime.fromisoformat(row["until_utc"]) if row["until_utc"] else None,
        series=frozenset(series) if series else None,
    )


def matcher(db, owner_user_id: str, context: str = OPENWEARABLES) -> Matcher | None:
    """The person's active rules for one aggregation context; None when none
    apply, so the hot path stays a single ContextVar read."""
    rules: dict[str, list[Rule]] = {}
    for row in db.execute(
        "SELECT * FROM device_exclusions WHERE owner_user_id=? AND revoked_at IS NULL", (owner_user_id,)
    ):
        label = label_for(row, context)
        if label:
            rules.setdefault(label, []).append(_rule(row))
    if not rules:
        return None
    return Matcher(rules, UTC if context == OPENWEARABLES else user_timezone(db, owner_user_id))


def version(db, owner_user_id: str) -> tuple:
    """Changes whenever a rule is made or undone: rows are only ever added,
    and an undo moves one from active to revoked."""
    return tuple(db.execute(
        "SELECT COUNT(*), COALESCE(SUM(revoked_at IS NULL), 0) FROM device_exclusions WHERE owner_user_id=?",
        (owner_user_id,)).fetchone())


class RulesChanged(RuntimeError):
    """A rule was made or undone while a long import was being parsed."""


@contextmanager
def using(rules: Matcher | None):
    token = EXCLUDING.set(rules)
    try:
        yield rules
    finally:
        EXCLUDING.reset(token)


@contextmanager
def applying(db, owner_user_id: str, context: str = OPENWEARABLES):
    """Aggregate inside this block without the person's excluded readings."""
    with using(matcher(db, owner_user_id, context)) as rules:
        yield rules


# --- creating and undoing rules ------------------------------------------------


def utc_text(moment: datetime) -> str:
    """One spelling for stored instants, so they also compare as text."""
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def parse_instant(text: str, tz) -> datetime:
    """An ISO instant; one without an offset (a ``datetime-local`` field) is
    the person's own wall-clock time."""
    try:
        moment = datetime.fromisoformat(clean(text).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExclusionError("exclusions.err_time") from exc
    return (moment.replace(tzinfo=tz) if moment.tzinfo is None else moment).astimezone(UTC)


def _origin_known(db, owner_user_id: str, provider: str, source: str, device: str) -> bool:
    """The origin wrote something into this person's own record."""
    if provider in ADAPTERS:
        group = sorted(_group(provider) & set(ADAPTERS))
        sql = """SELECT 1 FROM {table} r JOIN device_imports i ON i.id=r.import_id
                 WHERE r.owner_user_id=? AND r.source_name=? AND i.adapter_key IN (%s) LIMIT 1""" % ",".join("?" * len(group))
        params = (owner_user_id, source, *group)
    else:
        sql = "SELECT 1 FROM {table} WHERE owner_user_id=? AND source_name=? LIMIT 1"
        params = (owner_user_id, ow_label(provider, source, device))
    return any(db.execute(sql.format(table=table), params).fetchone()
               for table in ("device_metric_days", "device_workouts", "device_events"))


def connected_people(db, owner_user_id: str) -> list:
    """Accounts sharing a record with this person, in either direction: the
    people a reading can be said to belong to."""
    return db.execute(
        """SELECT DISTINCT u.id, u.display_name, u.email FROM users u
           JOIN users me ON me.id=?
           WHERE u.id<>me.id AND u.disabled_at IS NULL AND (
               EXISTS (SELECT 1 FROM record_shares s WHERE s.owner_user_id=me.id AND s.grantee_email=u.email)
               OR EXISTS (SELECT 1 FROM record_shares s WHERE s.owner_user_id=u.id AND s.grantee_email=me.email))
           ORDER BY u.display_name""",
        (owner_user_id,),
    ).fetchall()


def _series(db, owner_user_id: str, series: list[str]) -> str | None:
    from ..openwearables import DEFS

    keys = sorted({clean(key) for key in series if clean(key)})
    if not keys:
        return None
    known = {row[0] for row in db.execute(
        "SELECT DISTINCT metric_key FROM device_metric_days WHERE owner_user_id=?", (owner_user_id,))}
    if any(not _SERIES_KEY.fullmatch(key) or key not in known | set(DEFS) | {WORKOUTS, EVENTS} for key in keys):
        raise ExclusionError("exclusions.err_series")
    return json.dumps(keys)


def _audit(db, owner_user_id: str, actor_user_id: str, action: str, exclusion_id: str, details: dict) -> None:
    db.execute(
        """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at)
           VALUES (?, ?, ?, 'device_exclusion', ?, ?, ?)""",
        (owner_user_id, actor_user_id, action, exclusion_id, json.dumps(details, ensure_ascii=False), utc_now()),
    )


def _bounds(scope: str, from_text: str, until_text: str, tz) -> tuple[str | None, str | None]:
    if scope == "origin":
        return None, None
    if not clean(from_text) or (scope == "window" and not clean(until_text)):
        raise ExclusionError("exclusions.err_time")
    lower = parse_instant(from_text, tz)
    if scope == "reading":
        return utc_text(lower), None
    upper = parse_instant(until_text, tz)
    if upper < lower:
        raise ExclusionError("exclusions.err_order")
    return utc_text(lower), utc_text(upper)


def create(settings, owner_user_id: str, actor_user_id: str, *, provider: str, source: str, device: str = "",
           scope: str, from_text: str = "", until_text: str = "", series: list[str] | None = None,
           belongs_to: str = "", reason: str = "") -> str:
    """Store a rule for the person's own record and audit it; the same active
    rule asked for twice is the one rule."""
    provider, source, device, belongs_to = clean(provider), clean(source), clean(device), clean(belongs_to)
    if scope not in SCOPES:
        raise ExclusionError("exclusions.err_scope")
    if not provider or not source or max(len(provider), len(source), len(device)) > 200:
        raise ExclusionError("exclusions.err_origin")
    if len(reason) > 500:
        raise ExclusionError("exclusions.err_reason")
    tz = user_timezone_for(settings, owner_user_id)
    lower, upper = _bounds(scope, from_text, until_text, tz)
    with transaction(settings, immediate=True) as db:
        if not _origin_known(db, owner_user_id, provider, source, device):
            raise ExclusionError("exclusions.err_origin")
        stored_series = _series(db, owner_user_id, series or [])
        if belongs_to and belongs_to not in {row["id"] for row in connected_people(db, owner_user_id)}:
            raise ExclusionError("exclusions.err_person")
        same = db.execute(
            """SELECT id FROM device_exclusions WHERE owner_user_id=? AND revoked_at IS NULL
               AND origin_provider=? AND origin_source=? AND origin_device=? AND scope=?
               AND from_utc IS ? AND until_utc IS ? AND series IS ?""",
            (owner_user_id, provider, source, device, scope, lower, upper, stored_series),
        ).fetchone()
        if same:
            return str(same["id"])
        patient = db.execute(
            "SELECT id FROM patients WHERE owner_user_id=? ORDER BY created_at LIMIT 1", (owner_user_id,)
        ).fetchone()
        exclusion_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO device_exclusions(id, owner_user_id, patient_id, origin_provider, origin_source,
                   origin_device, scope, from_utc, until_utc, series, belongs_to_user_id, reason,
                   created_by_user_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (exclusion_id, owner_user_id, patient["id"] if patient else None, provider, source, device, scope,
             lower, upper, stored_series, belongs_to or None, clean(reason), actor_user_id, utc_now()),
        )
        _audit(db, owner_user_id, actor_user_id, "device_exclusion_created", exclusion_id, {
            "scope": scope, "origin": [provider, source, device], "from_utc": lower, "until_utc": upper,
            "series": json.loads(stored_series) if stored_series else None, "belongs_to_user_id": belongs_to or None,
        })
    return exclusion_id


def undo(settings, owner_user_id: str, actor_user_id: str, exclusion_id: str) -> bool:
    with transaction(settings, immediate=True) as db:
        changed = db.execute(
            """UPDATE device_exclusions SET revoked_at=?, revoked_by_user_id=?, applied_at=NULL
               WHERE id=? AND owner_user_id=? AND revoked_at IS NULL""",
            (utc_now(), actor_user_id, exclusion_id, owner_user_id),
        ).rowcount
        if changed:
            _audit(db, owner_user_id, actor_user_id, "device_exclusion_undone", exclusion_id, {})
    return bool(changed)


def listed(db, owner_user_id: str) -> list:
    """Active rules, and undone ones whose values are still being restored."""
    return db.execute(
        """SELECT e.*, u.display_name AS belongs_to_name FROM device_exclusions e
           LEFT JOIN users u ON u.id=e.belongs_to_user_id
           WHERE e.owner_user_id=? AND (e.revoked_at IS NULL OR e.applied_at IS NULL)
           ORDER BY e.created_at DESC""",
        (owner_user_id,),
    ).fetchall()


def affecting(db, owner_user_id: str, metric_key: str) -> int:
    """Active rules that can change this metric's values."""
    return sum(1 for row in db.execute(
        "SELECT series FROM device_exclusions WHERE owner_user_id=? AND revoked_at IS NULL", (owner_user_id,))
        if not row["series"] or metric_key in json.loads(row["series"]))


# --- recalculating the stored days -------------------------------------------


def _day(moment: str, shift: int) -> str:
    return (datetime.fromisoformat(moment).date() + timedelta(days=shift)).isoformat()


def span(row) -> tuple[str, str]:
    """UTC days a rule touches, widened a day each side: a local day can start
    the UTC day before and end the UTC day after."""
    from ..openwearables import EPOCH_DAY

    if row["scope"] == "origin":
        return EPOCH_DAY, (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    return _day(row["from_utc"], -1), _day(row["until_utc"] or row["from_utc"], 1)


def _span_days(row) -> int:
    first, last = span(row)
    return (date.fromisoformat(last) - date.fromisoformat(first)).days + 1


def _chunks(first: str, last: str, size: int):
    start, final = date.fromisoformat(first), date.fromisoformat(last)
    while start <= final:
        end = min(start + timedelta(days=size - 1), final)
        yield start.isoformat(), end.isoformat()
        start = end + timedelta(days=1)


def _account(db, owner_user_id: str):
    """(envelope id, remote user, server) of the person's OpenWearables archive."""
    from ..openwearables import ADAPTER_KEY

    row = db.execute("SELECT id, metadata_json FROM device_imports WHERE owner_user_id=? AND adapter_key=?",
                     (owner_user_id, ADAPTER_KEY)).fetchone()
    if row is None:
        return None
    state = json.loads(row["metadata_json"] or "{}")
    remote, server = str(state.get("remote_user_id") or ""), str(state.get("remote_server_url") or "")
    if remote and not server:
        # Links made before the server was recorded in the state: the archive
        # names it, and a relink to another account purges that archive.
        servers = {found[0] for table in ("openwearables_raw_records", "openwearables_raw_days")
                   for found in db.execute(f"SELECT DISTINCT server_url FROM {table} WHERE owner_user_id=? AND remote_user_id=?",
                                           (owner_user_id, remote))}
        server = servers.pop() if len(servers) == 1 else ""
    return (str(row["id"]), remote, server) if remote and server else None


def _archived(db, owner_user_id: str, account, datatype: str, first: str, last: str) -> list[dict]:
    return [json.loads(payload) for (payload,) in db.execute(
        """SELECT payload_json FROM openwearables_raw_records WHERE owner_user_id=? AND server_url=?
           AND remote_user_id=? AND datatype=? AND day BETWEEN ? AND ?""",
        (owner_user_id, account[2], account[1], datatype, first, last))]


def _archive_span(db, owner_user_id: str, account) -> tuple[str, str] | None:
    from .. import openwearables_archive as archive

    days = [day for day in archive.sample_day_span(db, owner_user_id, account[2], account[1]) if day]
    days += [day for day in db.execute(
        "SELECT MIN(day), MAX(day) FROM openwearables_raw_records WHERE owner_user_id=? AND server_url=? AND remote_user_id=?",
        (owner_user_id, account[2], account[1])).fetchone() if day]
    return (min(days), max(days)) if days else None


def _rebuild_chunk(settings, db, owner_user_id: str, account, start: str, end: str, tz) -> None:
    from .. import openwearables as ow
    from .reaggregate import _with_resting_samples

    import_id, remote, server = account
    expected = (remote, server)
    before, after = _day(start + _MIDNIGHT, -1), _day(end + _MIDNIGHT, 1)
    for datatype in _DATATYPES:
        rows = _archived(db, owner_user_id, account, datatype, before, after)
        if not rows:
            continue  # never delete days the archive cannot rebuild
        if datatype == "recovery":
            rows = _with_resting_samples(ow, db, rows, owner_user_id, server, remote, start, end, tz)
        bucket: dict = {}
        with applying(db, owner_user_id):
            ow._MAPPERS[datatype](rows, bucket, tz)
        ow._write_days(settings, owner_user_id, import_id, ow._in_window(bucket.values(), start, end),
                       ow.DATATYPE_KEYS[datatype], start, end, expected, db_connection=db, verify_account=False)
    # After the summaries, as in a sync: the activity summary also writes the
    # raw-owned daily totals, and the raw recompute replaces them.
    ow.recompute_raw_days(settings, db, owner_user_id, import_id, expected, start, end, tz, verify_account=False)
    rules = matcher(db, owner_user_id)
    workouts = _archived(db, owner_user_id, account, "workouts", start, end)
    if workouts:
        ow._write_workouts(settings, owner_user_id, import_id, ow.workouts_from_rows(workouts, rules), start, end,
                           expected, db_connection=db, verify_account=False)
    cycles = _archived(db, owner_user_id, account, "cycles", start, end)
    if cycles:
        ow._write_events(settings, owner_user_id, import_id, ow.cycles_from_rows(cycles, rules), start, end,
                         expected, db_connection=db, verify_account=False)


def rebuild_openwearables(settings, owner_user_id: str, first: str, last: str) -> int:
    """Rebuild UTC days ``first..last`` of the OpenWearables rows from the
    local archive alone, under the current rules; returns chunks written."""
    with connect(settings) as db:
        account = _account(db, owner_user_id)
        bounds = _archive_span(db, owner_user_id, account) if account else None
    if not bounds:
        return 0
    first = max(first, _day(bounds[0] + _MIDNIGHT, -1))
    last = min(last, _day(bounds[1] + _MIDNIGHT, 1))
    tz = user_timezone_for(settings, owner_user_id)
    chunks = 0
    for start, end in _chunks(first, last, INLINE_DAYS):
        with transaction(settings, immediate=True) as db:
            _rebuild_chunk(settings, db, owner_user_id, account, start, end, tz)
        chunks += 1
    return chunks


def _adapters_reached(db, owner_user_id: str, rows) -> set[str]:
    """File exports and provider APIs holding rows that a pending rule reaches."""
    adapters = {row[0] for row in db.execute(
        """SELECT DISTINCT i.adapter_key FROM device_imports i WHERE i.owner_user_id=? AND (
               EXISTS (SELECT 1 FROM device_metric_days d WHERE d.import_id=i.id)
               OR EXISTS (SELECT 1 FROM device_workouts w WHERE w.import_id=i.id)
               OR EXISTS (SELECT 1 FROM device_events e WHERE e.import_id=i.id))""", (owner_user_id,))}
    return {adapter for adapter in adapters & set(ADAPTERS) if any(label_for(row, adapter) for row in rows)}


#: Writers that must ask their provider again to rebuild: no local archive.
_REFETCHED = frozenset({"oura_api", "garmin_personal_api"})


def _rebuild_provider(settings, owner_user_id: str, adapter: str, first: str, last: str) -> None:
    """Rewrite one provider API's days ``first..last`` under the current rules:
    Garmin's pushed summaries from their local mirror, the others by the
    provider's own windowed sync."""
    if adapter == "garmin_api":
        from .. import garmin

        garmin.rebuild_window(settings, owner_user_id, first, last)
    elif adapter == "oura_api":
        from .. import oura

        oura.resync_window(settings, owner_user_id, first, last)
    elif adapter == "garmin_personal_api":
        from .. import garmin_personal

        garmin_personal.resync_window(settings, owner_user_id, first, last)


def _pending(db, owner_user_id: str) -> list:
    return db.execute("SELECT * FROM device_exclusions WHERE owner_user_id=? AND applied_at IS NULL",
                      (owner_user_id,)).fetchall()


def _merged_spans(rows) -> list[list[str]]:
    """The rules' day spans, overlapping ones joined."""
    merged: list[list[str]] = []
    for first, last in sorted(span(row) for row in rows):
        if merged and first <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], last)
        else:
            merged.append([first, last])
    return merged


def _rebuild_providers(settings, owner_user_id: str, adapters: set[str], first: str, last: str) -> None:
    for adapter in sorted(adapters & set(API_ADAPTERS)):
        try:
            _rebuild_provider(settings, owner_user_id, adapter, first, last)
        except Exception:  # noqa: BLE001 - its next sync applies the rules in its own write
            logger.warning("exclusions: %s could not be asked again", adapter, exc_info=True)


def _reimport_files(settings, owner_user_id: str) -> None:
    from .reaggregate import reimport_files

    for result in reimport_files(settings, owner_user_id):
        if result["status"] == "skipped_source_missing":
            logger.warning("exclusions: export %s has no kept copy to re-read", result["import_id"])


def run_pending(settings, owner_user_id: str) -> int:
    """Recalculate every day a pending rule (new or undone) touches; returns
    the number of rules settled.

    Every writer reads the rules inside the transaction that replaces its
    window, so a sync racing this rebuild cannot write an excluded reading
    back: whichever commits second sees the rule."""
    with connect(settings) as db:
        rows = _pending(db, owner_user_id)
        adapters = _adapters_reached(db, owner_user_id, rows) if rows else set()
    if not rows:
        return 0
    for first, last in _merged_spans(rows):
        rebuild_openwearables(settings, owner_user_id, first, last)
        _rebuild_providers(settings, owner_user_id, adapters, first, last)
    if adapters & set(FILE_ADAPTERS):
        _reimport_files(settings, owner_user_id)
    with transaction(settings, immediate=True) as db:
        settled = 0
        for row in rows:
            # A rule undone (or re-applied) while this ran stays pending.
            settled += db.execute(
                "UPDATE device_exclusions SET applied_at=? WHERE id=? AND applied_at IS NULL AND revoked_at IS ?",
                (utc_now(), row["id"], row["revoked_at"]),
            ).rowcount
    return settled


def _spawn(name: str, target, *args) -> None:
    from ..openwearables import _spawn as spawn

    spawn(name, target, *args)


def settle(settings, owner_user_id: str) -> str:
    """Apply pending rules now when they are small, else in the background.

    Returns ``idle`` (nothing pending), ``applied`` or ``queued``.
    """
    with connect(settings) as db:
        rows = _pending(db, owner_user_id)
        adapters = _adapters_reached(db, owner_user_id, rows) if rows else set()
    if not rows:
        return "idle"
    # A file is re-read whole and a provider is asked over the network: both
    # leave the request; the local archives are rebuilt in it.
    slow = adapters & (set(FILE_ADAPTERS) | _REFETCHED)
    if not slow and all(_span_days(row) <= INLINE_DAYS for row in rows):
        run_pending(settings, owner_user_id)
        return "applied"
    _spawn(f"exclusions-{owner_user_id}", run_pending, settings, owner_user_id)
    return "queued"


# --- what the person reviews -----------------------------------------------------


def origin_from_label(label: str) -> tuple[str, str, str] | None:
    """(provider, source app, device) of an OpenWearables source name; None
    when it does not name an app."""
    parts = label.split(" · ")
    if len(parts) < 3 or parts[0] != "OpenWearables":
        return None
    origin = (parts[1], parts[2], " · ".join(parts[3:]))
    return origin if ow_label(*origin) == label else None


def _mapped(datatype: str, row: dict, tz) -> dict[str, float]:
    """{metric key: value} one archived row contributes, without any rules."""
    from .. import openwearables as ow

    bucket: dict = {}
    with using(None):
        if datatype == "samples":
            if str(row.get("type") or "") in ow.BODY_SERIES:
                ow._map_body_series([row], bucket, tz)
            else:
                ow.map_raw_metrics([row], bucket, tz)
        else:
            ow._MAPPERS[datatype]([row], bucket, tz)
    return {key: item.value for (key, _day, _source), item in bucket.items() if item.sample_count}


def _reading_rows(db, owner_user_id: str, account, lower: datetime, upper: datetime):
    """(datatype, instant text, payload) of archived timestamped rows in
    [lower, upper)."""
    from .. import openwearables_archive as archive

    first, last = lower.date().isoformat(), upper.date().isoformat()
    for row in archive.iter_samples(db, owner_user_id, account[2], account[1], first, last):
        yield "samples", str(row.get("timestamp") or ""), row
    for datatype, field in (("body_series", "timestamp"), ("sleep", "start_time"), ("scores", "recorded_at")):
        for row in _archived(db, owner_user_id, account, datatype, _day(utc_text(lower), -1), last):
            yield datatype, str(row.get(field) or ""), row


def readings(db, owner_user_id: str, source_name: str, metric_key: str, day: str, tz) -> dict[str, object]:
    """The single readings behind one stored day of one source.

    ``items``: one entry per instant at which ``metric_key`` was written, with
    every series written at that same instant.  ``origin`` is the writer.
    Day-dated summaries (activity, recovery) and file exports keep no single
    readings here, so they come back with no items.
    """
    from ..openwearables import _source_label

    file_row = db.execute(
        """SELECT i.adapter_key FROM device_metric_days d JOIN device_imports i ON i.id=d.import_id
           WHERE d.owner_user_id=? AND d.source_name=? AND d.metric_key=? AND d.day=? AND i.adapter_key IN ({})
           LIMIT 1""".format(",".join("?" for _ in ADAPTERS)),
        (owner_user_id, source_name, metric_key, day, *ADAPTERS),
    ).fetchone() or db.execute(
        """SELECT i.adapter_key FROM device_metric_days d JOIN device_imports i ON i.id=d.import_id
           WHERE d.owner_user_id=? AND d.source_name=? AND i.adapter_key IN ({})
           LIMIT 1""".format(",".join("?" for _ in ADAPTERS)),
        (owner_user_id, source_name, *ADAPTERS),
    ).fetchone()
    if file_row:
        # File exports and provider APIs keep no single readings to list; the
        # day's value and a period are what can be excluded.
        return {"origin": (file_row[0], source_name, ""), "items": [], "kind": "file"}
    account = _account(db, owner_user_id)
    origin = origin_from_label(source_name)
    if account is None or origin is None:
        return {"origin": origin, "items": [], "kind": "openwearables"}
    low, high = local_bounds_utc(day, day, tz)
    lower, upper = datetime.fromisoformat(low), datetime.fromisoformat(high)
    instants: dict[datetime, dict[str, float]] = {}
    for datatype, stamp, row in _reading_rows(db, owner_user_id, account, lower, upper):
        moment = _instant(stamp)
        if moment is None or not lower <= moment < upper or _source_label(row) != source_name:
            continue
        instants.setdefault(moment, {}).update(_mapped(datatype, row, tz))
    rules = matcher(db, owner_user_id)
    items = [
        {"instant": utc_text(moment), "moment": moment, "series": series, "value": series[metric_key],
         "excluded": bool(rules and rules.excludes(source_name, metric_key, utc_text(moment)))}
        for moment, series in sorted(instants.items()) if metric_key in series
    ]
    return {"origin": origin, "items": items, "kind": "openwearables"}


def usual(values: list[float]) -> float | None:
    """The person's own median, when there is enough history to have one."""
    values = [value for value in values if value]
    return median(values) if len(values) >= SUGGEST_MIN_DAYS else None


def far_from_usual(metric_key: str, value: float | None, typical: float | None) -> bool:
    """Worth a check: a body reading far from the person's own median.  A
    suggestion only; nothing is ever excluded without the person saying so."""
    return (metric_key in SUGGEST_KEYS and value is not None and typical is not None
            and abs(float(value) - typical) > SUGGEST_RATIO * abs(typical))


if __name__ == "__main__":
    # The predicate's own check: a reading, a window over a day total, an origin.
    weigh_in = datetime(2026, 4, 27, 11, 18, 48, tzinfo=UTC)
    rules = Matcher({"scale": [Rule("reading", weigh_in, None, None)],
                     "watch": [Rule("window", weigh_in, weigh_in + timedelta(days=6), frozenset({"total_energy"}))]})
    assert rules.excludes("scale", "body_weight", "2026-04-27T11:18:48Z")
    assert rules.excludes("scale", "body_mass_index", "2026-04-27 14:18:48 +0300")
    assert not rules.excludes("scale", "body_weight", "2026-04-27T11:18:49Z")
    assert not rules.excludes("scale", "body_weight", "2026-04-27")
    assert rules.excludes("watch", "total_energy", "2026-04-27") and rules.excludes("watch", "total_energy", "2026-05-03")
    assert not rules.excludes("watch", "total_energy", "2026-04-26") and not rules.excludes("watch", "steps", "2026-04-28")
    assert not rules.excludes("other", "body_weight", "2026-04-27T11:18:48Z")
    print("ok")
