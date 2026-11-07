"""The one local-day boundary every device adapter cuts a day at.

A daily total belongs to the calendar day the person lived, not to UTC: a walk
at 01:30 in Kyiv is "today" to the walker and "yesterday" to UTC, and cutting
at UTC midnight moved two to three hours of every day into its neighbour.  The
person's zone is a user setting (`users.timezone`, migration 041), read with
DST-aware `ZoneInfo` so a summer evening and a winter evening both land right.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

DEFAULT_TIMEZONE = "Europe/Kyiv"


@lru_cache(maxsize=64)
def zone(name: str | None) -> ZoneInfo:
    """`ZoneInfo` for a stored name; an unknown or empty name is the default."""
    try:
        return ZoneInfo(str(name or DEFAULT_TIMEZONE))
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def valid_timezone(name: str) -> bool:
    return name in _names()


@lru_cache(maxsize=1)
def _names() -> frozenset[str]:
    return frozenset(available_timezones())


def timezone_choices() -> list[str]:
    return sorted(_names())


def user_timezone(connection, owner_user_id: str) -> ZoneInfo:
    """The person's zone; the default when the column or the row is absent
    (read-only tooling may open a pre-migration backup)."""
    try:
        row = connection.execute("SELECT timezone FROM users WHERE id=?", (owner_user_id,)).fetchone()
    except Exception:  # noqa: BLE001 - sqlite3.OperationalError on an old schema
        return zone(None)
    return zone(row[0] if row else None)


def user_timezone_for(settings, owner_user_id: str) -> ZoneInfo:
    from ..db import connect

    with connect(settings) as connection:
        return user_timezone(connection, owner_user_id)


def _instant(stamp: str) -> datetime | None:
    text = stamp.strip()
    if len(text) <= 10:
        return None
    # Apple Health writes "2024-01-01 08:00:00 +0200": fold the space before
    # the offset so fromisoformat reads it.
    if len(text) >= 25 and text[19] == " " and text[20] in "+-":
        text = text[:19] + text[20:]
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    # A timestamp with no offset is read as UTC: the APIs that omit it
    # (OpenWearables raw samples, Oura heart rate) document UTC.
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def local_day(stamp: str, tz: tzinfo | None = None) -> str:
    """The calendar day `stamp` falls on in `tz` (default zone when omitted).

    A bare date is already a local day and is returned unchanged; text that is
    not a timestamp falls back to its first ten characters, the convention it
    replaces, so nothing that parsed before stops parsing now.
    """
    text = str(stamp or "")
    moment = _instant(text)
    if moment is None:
        return text[:10]
    return moment.astimezone(tz or zone(None)).date().isoformat()


def local_bounds_utc(start_day: str, end_day: str, tz: tzinfo) -> tuple[str, str]:
    """[first instant of start_day, first instant after end_day) in UTC ISO."""
    first = datetime.combine(date.fromisoformat(start_day), datetime.min.time(), tz)
    after = datetime.combine(date.fromordinal(date.fromisoformat(end_day).toordinal() + 1), datetime.min.time(), tz)
    # Microsecond form: the same shape the raw-sample table stores, so the
    # bounds compare as strings exactly as they compare as instants.
    return (first.astimezone(UTC).isoformat(timespec="microseconds"),
            after.astimezone(UTC).isoformat(timespec="microseconds"))


def today(tz: tzinfo | None = None) -> str:
    return datetime.now(tz or zone(None)).date().isoformat()
