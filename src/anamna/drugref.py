"""Medicine reference text from the Ukrainian pharmacy site tabletki.ua.

A person records a medicine. This module finds its page on the site and keeps
the official instruction for medical use in the ``drug_references`` cache.

Search goes to the open search endpoint of the site's application API. The
instruction is read from the public page of the medicine. The product-card
endpoint of that same API answers 403 without the application's own token, and
this module does not send that token.

The module identifies itself with the project's User-Agent. It caches searches
for 15 minutes and instructions for 90 days. It sends at most 30 requests a
minute and never retries. It stops calling for as long as the site asks through
HTTP 429 or 503 (with Retry-After), and for 15 minutes after an HTTP 403.

Only the public reference text crosses the wire: the search text and the page
name, never anything from the person's record.
"""

from __future__ import annotations

import email.utils
import html
import http.client
import json
import math
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict, deque
from datetime import UTC, datetime, timedelta

from .config import USER_AGENT
from .db import utc_now

SOURCE = "tabletki"
BASE = "https://tabletki.ua"
API = "https://app.tabletki.ua/api/app/v1/"
_ALLOWED = (BASE + "/", API)
SETTING = "drug_lookup_enabled"  # app_settings key; absent or "1" means on, "0" means off
TIMEOUT = 10
MAX_BYTES = 3_000_000
CACHE_DAYS = 90
SUGGEST_CACHE_SECONDS = 900
SUGGEST_CACHE_SIZE = 256
REQUEST_BUDGET = 30
BUDGET_SECONDS = 60
DEFAULT_PAUSE_SECONDS = 120
MIN_PAUSE_SECONDS = 30
MAX_PAUSE_SECONDS = 3600
FORBIDDEN_PAUSE_SECONDS = 900

_SUGGEST_KINDS = {"TNCATV": "trade_name", "PCV": "product"}
_SUGGEST_LIMIT = 12
_BAD_REFERENCE_CHARS = ("/", "\\", "?", "#", "%")
_DIGITS = re.compile(r"[0-9]+")
_ATC_BLOCK = re.compile(r'"ATCFull":\[([^\]]*)\]')
_ATC_CODE = re.compile(r'"([A-Z]\d{2}[A-Z]{2}\d{2})"')
_SHOWN_FOR = re.compile(r"Інструкція вказана для «([^»]+)»")
_SECTION = re.compile(
    r'<h2 id="instr-desktop_(\d+)"[^>]*>(.*?)</h2>\s*<div id="instr_cont_\1"[^>]*>(.*?)</div>\s*</section>',
    re.S,
)
_UNIT_STEMS = (
    (("таблет", "драже"), "tablet"),
    (("капсул",), "capsule"),
    (("крапл",), "drop"),
    (("сироп", "суспенз", "розчин", "емульс", "настойк", "настоянк", "еліксир", "мікстур"), "ml"),
    (("спрей", "аерозоль", "інгаляц"), "puff"),
    (("порошок", "гранул"), "sachet"),
    (("супозитор", "песар", "свічк"), "suppository"),
    (("мазь", "крем", "гель", "лінімент", "паста"), "application"),
    (("пластир",), "patch"),
)
_STRENGTH = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:мкг|мг|г|мл|МО|ОД|%)"
    r"(?:\s*/\s*(?:\d+(?:[.,]\d+)?\s*)?(?:мкг|мг|г|мл|МО|ОД|доза|доз))*"
    r"(?![A-Za-zА-Яа-яІіЇїЄєҐґ])"
)
_STRENGTH_UNIT = re.compile(r"мкг|мг|г|мл|МО|ОД|%")
_CYRILLIC = "А-Яа-яІіЇїЄєҐґ"
_INTERNATIONAL_UNITS = (
    ("мкг", "mcg"),
    ("мг", "mg"),
    ("мл", "ml"),
    ("МО", "IU"),
    ("ОД", "U"),
    ("доза", "dose"),
    ("доз", "dose"),
)

_lock = threading.Lock()
_now = time.monotonic
_SUGGEST_CACHE: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
_sent: deque[float] = deque()
_paused_until = 0.0


class DrugRefError(Exception):
    """The reference site could not be used; the message names no URL and no search text."""


class DrugRefPaused(DrugRefError):
    """The reference site asked for a pause, or this process has spent its request budget."""

    def __init__(self, seconds: int):
        super().__init__("the reference site asked for a pause")
        self.seconds = int(seconds)


class _RedirectWithinSite(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith(_ALLOWED):
            raise DrugRefError("redirect outside the reference site refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def enabled(connection: sqlite3.Connection) -> bool:
    row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (SETTING,)).fetchone()
    return row is None or row[0] != "0"


def set_enabled(connection: sqlite3.Connection, on: bool) -> None:
    """Upserts the switch; the caller commits."""
    connection.execute(
        "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (SETTING, "1" if on else "0", utc_now()),
    )


def reset_state() -> None:
    """Clears the suggest cache, the request budget and any pause. Tests call it before each case."""
    global _paused_until
    with _lock:
        _SUGGEST_CACHE.clear()
        _sent.clear()
        _paused_until = 0.0


def paused_seconds() -> int:
    """Whole seconds left of a pause asked for by the site; 0 when there is none."""
    with _lock:
        remaining = _paused_until - _now()
    return math.ceil(remaining) if remaining > 0 else 0


def _seconds_until(moment: float, now: float) -> int:
    return max(1, math.ceil(moment - now))


def _admit() -> None:
    """Counts one request about to be sent, or raises DrugRefPaused without sending."""
    with _lock:
        now = _now()
        if now < _paused_until:
            raise DrugRefPaused(_seconds_until(_paused_until, now))
        while _sent and now - _sent[0] >= BUDGET_SECONDS:
            _sent.popleft()
        if len(_sent) >= REQUEST_BUDGET:
            raise DrugRefPaused(_seconds_until(_sent[0] + BUDGET_SECONDS, now))
        _sent.append(now)


def _pause(wait: int) -> None:
    global _paused_until
    with _lock:
        _paused_until = _now() + wait
    raise DrugRefPaused(wait)


def _retry_after(headers) -> int:
    """The wait the server asked for, clamped. The default when the header is missing or unreadable."""
    value = headers.get("Retry-After") if headers is not None else None
    if value is None:
        return DEFAULT_PAUSE_SECONDS
    value = value.strip()
    if _DIGITS.fullmatch(value):
        seconds = int(value)
    else:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return DEFAULT_PAUSE_SECONDS
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = math.ceil((when - datetime.now(UTC)).total_seconds())
    return min(MAX_PAUSE_SECONDS, max(MIN_PAUSE_SECONDS, seconds))


def _open(url: str, data: bytes | None = None, headers: dict | None = None) -> str:
    if not url.startswith(_ALLOWED):
        raise DrugRefError("URL outside the reference site refused")
    _admit()
    sent = {"User-Agent": USER_AGENT, "Accept-Language": "uk"}
    if data is not None:
        sent["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    sent.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=sent)
    opener = urllib.request.build_opener(_RedirectWithinSite)
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            body = response.read(MAX_BYTES + 1)
    except DrugRefError:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code in (429, 503):
            _pause(_retry_after(exc.headers))
        if exc.code == 403:
            _pause(FORBIDDEN_PAUSE_SECONDS)
        raise DrugRefError(type(exc).__name__) from None
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as exc:
        raise DrugRefError(type(exc).__name__) from None
    if len(body) > MAX_BYTES:
        raise DrugRefError("reply too large")
    return body.decode("utf-8", errors="replace")


def parse_product(name: str) -> tuple[str, str]:
    """The dosage form and the strength of a product name, read from its text.

    The unit is the form word that appears first; the strength is the first
    dose that is not a bottle volume or a tube weight.
    """
    head = name.split("№", 1)[0]
    folded = head.casefold()
    unit, earliest = "", None
    for stems, word in _UNIT_STEMS:
        for stem in stems:
            at = folded.find(stem)
            if at != -1 and (earliest is None or at < earliest):
                unit, earliest = word, at
    strength = ""
    for found in _STRENGTH.finditer(head):
        text = found.group(0)
        if "/" not in text:
            first = _STRENGTH_UNIT.search(text).group(0)
            if first == "мл" or (first == "г" and unit == "application"):
                continue
        strength = re.sub(r"\s+", " ", text).strip()
        break
    return unit, strength


def localize_strength(text: str, locale: str) -> str:
    """Ukrainian dose units spelt the international way for other locales."""
    if locale == "uk":
        return text
    for ukrainian, international in _INTERNATIONAL_UNITS:
        text = text.replace(ukrainian, international)
    text = re.sub(rf"(?<![{_CYRILLIC}])г(?![{_CYRILLIC}])", "g", text)
    return re.sub(r"(?<=\d),(?=\d)", ".", text)


def _shared_values(values: list[tuple[str, str]]) -> tuple[str, str]:
    """A trade name's unit and strength from its products: both when they agree, else the unit if it agrees."""
    if not values:
        return ("", "")
    if len(set(values)) == 1:
        return values[0]
    units = {unit for unit, _ in values}
    return (units.pop() if len(units) == 1 else "", "")


def _parse_suggest(reply: str) -> list[dict]:
    try:
        payload = json.loads(reply)
    except ValueError as exc:
        raise DrugRefError("suggest reply is not JSON") from exc
    if not isinstance(payload, dict):
        raise DrugRefError("suggest reply is not an object")
    groups = payload.get("group")
    if groups is None:
        groups = []
    if not isinstance(groups, list):
        raise DrugRefError("suggest groups are not a list")
    entries: list = []
    for group in groups:
        if not isinstance(group, dict):
            raise DrugRefError("suggest group is not an object")
        items = group.get("searchItems")
        if items is None:
            continue
        if not isinstance(items, list):
            raise DrugRefError("suggest search items are not a list")
        entries.extend(items)
    usable = []
    products: dict[str, list[tuple[str, str]]] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        view = item.get("screenViewType")
        kind = _SUGGEST_KINDS.get(view) if isinstance(view, str) else None
        url, name = item.get("url"), item.get("name")
        if kind is None or not isinstance(url, str) or not url or not isinstance(name, str):
            continue
        values = parse_product(name) if kind == "product" else None
        if values is not None:
            products.setdefault(url, []).append(values)
        usable.append((kind, item, url, name, values))
    found: list[dict] = []
    for kind, item, url, name, values in usable:
        if kind == "product":
            unit, strength = values
            maker = str(item.get("description") or "")
        else:
            unit, strength = _shared_values(products.get(url, []))
            maker = ""
        found.append({
            "kind": kind,
            "code": str(item.get("code") or ""),
            "name": name,
            "reference_name": url,
            "maker": maker,
            "unit": unit,
            "strength": strength,
        })
        if len(found) == _SUGGEST_LIMIT:
            break
    return found


def suggest(text: str) -> list[dict]:
    text = text.strip()
    if len(text) < 3:
        return []
    key = " ".join(text.split()).casefold()
    with _lock:
        hit = _SUGGEST_CACHE.get(key)
        if hit is not None:
            if _now() - hit[0] < SUGGEST_CACHE_SECONDS:
                return [dict(item) for item in hit[1]]
            del _SUGGEST_CACHE[key]
    body = json.dumps({"term": text}).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Lang": "uk",
        "Content-Type": "application/json; charset=UTF-8",
    }
    found = _parse_suggest(_open(API + "Search/searchHintsV2", body, headers=headers))
    with _lock:
        _SUGGEST_CACHE[key] = (_now(), found)
        while len(_SUGGEST_CACHE) > SUGGEST_CACHE_SIZE:
            _SUGGEST_CACHE.popitem(last=False)
    return [dict(item) for item in found]


def page_url(reference_name: str, code: str = "") -> str:
    """The page to fetch: percent-encoded, so Cyrillic names travel as UTF-8."""
    if not reference_name or any(ch in reference_name for ch in _BAD_REFERENCE_CHARS) or ".." in reference_name:
        raise DrugRefError("unusable reference name")
    url = BASE + "/uk/" + urllib.parse.quote(reference_name, safe="") + "/"
    if _DIGITS.fullmatch(code):
        url += code + "/"
    return url


def _readable(url: str) -> str:
    return urllib.parse.unquote(url)


def _text(fragment: str) -> str:
    fragment = re.sub(r"(?i)<\s*(br|/p|/li|/tr|/h\d)\s*/?>", "\n", fragment)
    fragment = re.sub(r"(?i)</t[dh]>", " | ", fragment)
    plain = html.unescape(re.sub(r"<[^>]+>", "", fragment))
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n", plain)).strip()


def instruction(reference_name: str, code: str = "") -> dict:
    url = page_url(reference_name, code)
    page = _open(url)
    sections = []
    for match in _SECTION.finditer(page):
        title, text = _text(match.group(2)), _text(match.group(3))
        if text:
            sections.append([title, text])
    atc: list[str] = []
    block = _ATC_BLOCK.search(page)
    if block:
        for found in _ATC_CODE.findall(block.group(1)):
            if found not in atc:
                atc.append(found)
    shown = _SHOWN_FOR.search(page)
    return {
        "url": _readable(url),
        "sections": sections,
        "atc": atc,
        "shown_for": shown.group(1) if shown else "",
    }


def _fresh(fetched_at: str) -> bool:
    try:
        when = datetime.fromisoformat(fetched_at)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return datetime.now(UTC) - when < timedelta(days=CACHE_DAYS)


def _from_cache(url: str, row: tuple) -> dict:
    return {
        "url": url,
        "sections": json.loads(row[2]),
        "atc": [code_ for code_ in row[1].split(",") if code_],
        "shown_for": row[0],
    }


def cached_instruction(connection: sqlite3.Connection, reference_name: str, code: str = "") -> dict | None:
    """The instruction from the cache, or fetched and stored (the caller commits).

    Never raises. When the page cannot be fetched or parses to no sections, an
    older cached copy is returned if there is one: an instruction from last
    season is better evidence than none. Without any copy the answer is None.
    """
    try:
        url = _readable(page_url(reference_name, code))
        row = connection.execute(
            "SELECT shown_for, atc_codes, sections_json, fetched_at FROM drug_references "
            "WHERE source = ? AND url = ?",
            (SOURCE, url),
        ).fetchone()
        if row is not None and _fresh(row[3]):
            return _from_cache(url, row)
        try:
            fetched = instruction(reference_name, code)
        except DrugRefError:
            fetched = None
        if fetched is None or not fetched["sections"]:
            return _from_cache(url, row) if row is not None else None
        connection.execute(
            "INSERT OR REPLACE INTO drug_references "
            "(source, url, shown_for, atc_codes, sections_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                SOURCE,
                fetched["url"],
                fetched["shown_for"],
                ",".join(fetched["atc"]),
                json.dumps(fetched["sections"], ensure_ascii=False),
                utc_now(),
            ),
        )
        return fetched
    except (DrugRefError, sqlite3.Error, ValueError):
        return None
