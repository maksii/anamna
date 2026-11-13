"""Medicine reference text from the Ukrainian pharmacy site tabletki.ua.

A person records a medicine. This module finds its page on the site and keeps
the official instruction for medical use in the ``drug_references`` cache.

Search goes to the open search endpoint of the site's application API. The
instruction is read from the public page of the medicine: that is the default
and needs nothing. With a token that tabletki.ua issued (``ANAMNA_TABLETKI_TOKEN``
or the admin page) an administrator can choose the product-card endpoint of the
same API instead. It gives the instruction in parts and the product's facts: the
active substance, the form, the dosage, who may take it. The card is addressed
by a product code, so an entry linked to a trade name alone is read from the page.

The module identifies itself with the project's User-Agent on searches and page fetches. The card endpoint is called with the header set tabletki.ua expects from a client of that API. It caches searches for 15 minutes and instructions for 90 days. It sends at most 30 requests a minute and never retries. It stops calling for as long as the site asks through HTTP 429 or 503 (with Retry-After), and for 15 minutes after an HTTP 403.

Only the public reference text crosses the wire: the search text and the page
name, never anything from the person's record.
"""

from __future__ import annotations

import email.utils
import html
import http.client
import json
import math
import os
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
MODE_SETTING = "drug_lookup_mode"  # "page" (default) or "api"
TOKEN_SETTING = "drug_lookup_token"  # app API token for the "api" mode
TOKEN_ENV = "ANAMNA_TABLETKI_TOKEN"  # the token tabletki.ua issued; a value saved on the admin page wins
MODE_PAGE = "page"
MODE_API = "api"
_API_CARD = API + "ProductCard/card"
_API_APP_VERSION = "4.1.694"
_API_PLATFORM = "Android"
_API_DEFAULT_TOKEN = ""
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
_ATC_BARE = re.compile(r"[A-Z]\d{2}[A-Z]{2}\d{2}")
_SHOWN_FOR = re.compile(r"Інструкція вказана для «([^»]+)»")
#: One section of the page.  A medicine's instruction marks them ``instr-desktop_N`` / ``instr_cont_N``;
#: a dietary supplement's description marks them ``descr-…`` instead.  Read with the medicine form
#: alone, a supplement page with a full description parsed to no section at all and the entry was
#: researched as if the product were unknown.
_SECTION = re.compile(
    r'<h2 id="(?P<kind>instr|descr)-desktop_(?P<n>\d+)"[^>]*>(?P<title>.*?)</h2>'
    r'\s*<div id="(?P=kind)_cont_(?P=n)"[^>]*>(?P<body>.*?)</div>\s*</section>',
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
#: The characteristics kept from a product card, by the label the site prints.
_FACT_KEYS = {
    "Діючі речовини": "substance", "Діюча речовина": "substance", "МНН": "inn",
    "Форма випуску": "form", "Дозування": "dosage", "Кількість в упаковці": "pack",
    "Умови продажу": "sale", "Фармгрупа": "group", "АТХ-група": "atc",
    "Реєстрація": "registration", "Виробник": "maker",
}
_WARNING_STATES = {1: "allowed", 2: "caution", 0: "forbidden", -1: "free"}

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


def _setting(connection: sqlite3.Connection, key: str) -> str | None:
    """The stored value of one application setting, or None when it was never saved."""
    row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def enabled(connection: sqlite3.Connection) -> bool:
    return _setting(connection, SETTING) != "0"


def mode(connection: sqlite3.Connection) -> str:
    value = _setting(connection, MODE_SETTING)
    return value if value in (MODE_PAGE, MODE_API) else MODE_PAGE


def token(connection: sqlite3.Connection) -> str:
    """The API token: the one saved on the admin page, else the one in the server's environment."""
    stored = _setting(connection, TOKEN_SETTING)
    return (stored if stored else "") or os.environ.get(TOKEN_ENV, "").strip()


def token_source(connection: sqlite3.Connection) -> str:
    """Where the token comes from: "settings", "environment" or ""."""
    if _setting(connection, TOKEN_SETTING):
        return "settings"
    return "environment" if os.environ.get(TOKEN_ENV, "").strip() else ""


def fetch_options(connection: sqlite3.Connection) -> dict:
    """The keyword arguments for cached_instruction, as the administrator set them."""
    api_token = token(connection) if mode(connection) == MODE_API else ""
    return {"use_api": bool(api_token), "api_token": api_token}


def _upsert(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, utc_now()),
    )


def set_enabled(connection: sqlite3.Connection, on: bool) -> None:
    """Upserts the switch; the caller commits."""
    _upsert(connection, SETTING, "1" if on else "0")


def set_mode(connection: sqlite3.Connection, value: str) -> None:
    _upsert(connection, MODE_SETTING, value if value in (MODE_PAGE, MODE_API) else MODE_PAGE)


def set_token(connection: sqlite3.Connection, value: str) -> None:
    _upsert(connection, TOKEN_SETTING, value.strip())


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


def _unit_word(folded: str) -> str:
    unit, earliest = "", None
    for stems, word in _UNIT_STEMS:
        for stem in stems:
            at = folded.find(stem)
            if at != -1 and (earliest is None or at < earliest):
                unit, earliest = word, at
    return unit


def _dose_strength(head: str, unit: str) -> str:
    for found in _STRENGTH.finditer(head):
        text = found.group(0)
        if "/" not in text:
            first = _STRENGTH_UNIT.search(text).group(0)
            if first == "мл" or (first == "г" and unit == "application"):
                continue
        return re.sub(r"\s+", " ", text).strip()
    return ""


def parse_product(name: str) -> tuple[str, str]:
    """The dosage form and the strength of a product name, read from its text.

    The unit is the form word that appears first; the strength is the first
    dose that is not a bottle volume or a tube weight.
    """
    head = name.split("№", 1)[0]
    unit = _unit_word(head.casefold())
    return unit, _dose_strength(head, unit)


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


def _suggest_entries(payload: dict) -> list:
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
    return entries


def _suggest_usable(entries: list) -> tuple[list, dict[str, list[tuple[str, str]]]]:
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
    return usable, products


def _parse_suggest(reply: str) -> list[dict]:
    try:
        payload = json.loads(reply)
    except ValueError as exc:
        raise DrugRefError("suggest reply is not JSON") from exc
    if not isinstance(payload, dict):
        raise DrugRefError("suggest reply is not an object")
    usable, products = _suggest_usable(_suggest_entries(payload))
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


#: A tag or a comment. A bare "<" in running text («кліренс креатиніну < 10 мл/хв») is not one:
#: a tag starts with a letter, or with a slash and a letter, right after the "<".
_TAG = re.compile(r"<!--.*?-->|</?[A-Za-z][^<>]*>", re.S)
#: One table row, so the line breaks inside its cells can become spaces.
_ROW = re.compile(r"(?is)<tr\b.*?</tr>")
_BREAK_IN_ROW = re.compile(r"(?i)<\s*(?:br|/p|/li|/div|/h\d)\s*/?>")


def _text(fragment: str) -> str:
    fragment = _ROW.sub(lambda row: _BREAK_IN_ROW.sub(" ", row.group(0)), fragment)
    fragment = re.sub(r"(?i)<\s*(br|/p|/li|/tr|/h\d)\s*/?>", "\n", fragment)
    fragment = re.sub(r"(?i)</t[dh]>", " | ", fragment)
    plain = html.unescape(_TAG.sub("", fragment))
    plain = re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n", plain))
    return re.sub(r"(?: ?\| ?)+(?=\n|$)", "", plain).strip()


def instruction_page(reference_name: str, code: str = "") -> dict:
    """Fetch instruction by scraping the public HTML page."""
    url = page_url(reference_name, code)
    page = _open(url)
    sections = []
    for match in _SECTION.finditer(page):
        title, text = _text(match.group("title")), _text(match.group("body"))
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
        "details": {},
    }


def _api_headers(api_token: str = "") -> dict:
    """The headers the app's DefaultHeadersInterceptor sends on every request."""
    return {
        "Accept": "application/json",
        "User-Agent": "okhttp/4.12.0",
        "Lang": "uk",
        "deviceOS": _API_PLATFORM,
        "deviceOSversion": "14",
        "appVersion": _API_APP_VERSION,
        "Platform": _API_PLATFORM,
        "AppApiToken": api_token or _API_DEFAULT_TOKEN,
        "Sleep": "false",
        "adid": "00000000-0000-0000-0000-000000000000",
    }


def _same_page(a, b: str) -> bool:
    return urllib.parse.unquote(str(a or "")).casefold() == urllib.parse.unquote(b).casefold()


def instruction_api(reference_name: str, code: str = "", *, api_token: str = "") -> dict:
    """The instruction and the product facts from the product card of the site's API.

    Needs the token tabletki.ua issued and a product code: the card is addressed
    by the product, and the reply is refused unless it names that product and page.
    """
    url = _readable(page_url(reference_name, code))          # also refuses an unusable name
    if not _DIGITS.fullmatch(code):
        raise DrugRefError("the card needs a product code")
    if not api_token:
        raise DrugRefError("the card needs a token")
    query = urllib.parse.urlencode({"name": reference_name, "id": code, "withContentPlus": "false"})
    reply = _open(_API_CARD + "?" + query, headers=_api_headers(api_token))
    try:
        payload = json.loads(reply)
    except ValueError as exc:
        raise DrugRefError("card reply is not JSON") from exc
    if not isinstance(payload, dict):
        raise DrugRefError("card reply is not an object")
    if str(payload.get("goodsIntCode") or "") != code or not _same_page(payload.get("tradenameLink"), reference_name):
        raise DrugRefError("the card is for another product")
    return {
        "url": url,
        "sections": _parse_instruction_parts(payload.get("instructionByParts")),
        "atc": _parse_atc_from_card(payload),
        "shown_for": _text(str(payload.get("goodsName") or payload.get("tradeName") or "")),
        "details": _card_details(payload),
    }


def _fact_values(item: dict) -> list[str]:
    """The distinct texts of one characteristic's values, in the order the card gives them."""
    values: list[str] = []
    for value in item.get("values") or []:
        text = _text(str(value.get("name") or ""))[:300] if isinstance(value, dict) else ""
        if text and text not in values:
            values.append(text)
    return values


def _card_facts(payload: dict) -> list[list]:
    facts: list[list] = []
    seen: set[str] = set()
    for item in payload.get("characteristics") or []:
        key = _FACT_KEYS.get(str(item.get("name") or "").strip()) if isinstance(item, dict) else None
        if key is None or key in seen:
            continue
        values = _fact_values(item)
        if values:
            seen.add(key)
            facts.append([key, values[:10]])
    return facts


def _card_warnings(payload: dict) -> list[list]:
    warnings: list[list] = []
    block = payload.get("goodsWarning")
    for item in (block.get("items") if isinstance(block, dict) else None) or []:
        if not isinstance(item, dict):
            continue
        state = _WARNING_STATES.get(item.get("allowed")) if isinstance(item.get("allowed"), int) else None
        subject = _text(str(item.get("subject") or ""))[:120]
        if state and subject:
            warnings.append([subject, state, _text(str(item.get("remark") or ""))[:200]])
    return warnings[:20]


def _card_details(payload: dict) -> dict:
    """What the card says about the product besides the instruction: facts by key, and who may take it."""
    return {"via": "api", "facts": _card_facts(payload), "warnings": _card_warnings(payload)}


def _parse_instruction_parts(parts) -> list[list[str]]:
    if not isinstance(parts, list):
        return []
    items = [part for part in parts if isinstance(part, dict)]
    if items and all(isinstance(part.get("order"), int) for part in items):
        items.sort(key=lambda part: part["order"])
    sections: list[list[str]] = []
    for part in items:
        title = _text(str(part.get("title") or ""))
        body = _text(str(part.get("html") or ""))
        if body:
            sections.append([title, body])
    return sections


def _atc_from_dfp(payload: dict) -> list[str]:
    atc: list[str] = []
    # dfp.ATCFull is the cleanest source: ["M01AE01"]
    dfp = payload.get("dfp")
    if isinstance(dfp, dict):
        raw = dfp.get("ATCFull")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and _ATC_BARE.fullmatch(item) and item not in atc:
                    atc.append(item)
    return atc


def _atc_from_characteristics(payload: dict) -> list[str]:
    atc: list[str] = []
    # Fallback: characteristics where name contains "АТХ"
    for char in payload.get("characteristics") or []:
        if not isinstance(char, dict) or "АТХ" not in (char.get("name") or ""):
            continue
        for val in char.get("values") or []:
            if (isinstance(val, dict) and isinstance(val.get("code"), str)
                    and _ATC_BARE.fullmatch(val["code"]) and val["code"] not in atc):
                atc.append(val["code"])
    return atc


def _parse_atc_from_card(payload: dict) -> list[str]:
    return _atc_from_dfp(payload) or _atc_from_characteristics(payload)


def instruction(reference_name: str, code: str = "", *, api_token: str = "", use_api: bool = False) -> dict:
    """The instruction: from the product card when the API is chosen and can answer for this entry, else from the page."""
    if use_api and api_token and _DIGITS.fullmatch(code):
        try:
            return instruction_api(reference_name, code, api_token=api_token)
        except DrugRefError:
            # No card, or a card about another product: the public page is the reference.
            fetched = instruction_page(reference_name, code)
            fetched["details"] = {"via": "page"}   # tried the card; do not try again until the copy is old
            return fetched
    return instruction_page(reference_name, code)


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
        "fetched_at": row[3],
        "details": json.loads(row[4]) if row[4] else {},
    }


def stored_instruction(connection: sqlite3.Connection, reference_name: str, code: str = "") -> dict | None:
    """The stored copy, whatever its age. Asks nothing of the site. None when there is none or the name is unusable."""
    try:
        url = _readable(page_url(reference_name, code))
        row = connection.execute(
            "SELECT shown_for, atc_codes, sections_json, fetched_at, details_json FROM drug_references "
            "WHERE source = ? AND url = ?",
            (SOURCE, url),
        ).fetchone()
        return _from_cache(url, row) if row is not None else None
    except (DrugRefError, sqlite3.Error, ValueError):
        return None


def _stored_copy_is_current(row: tuple | None, card_wanted: bool) -> bool:
    """Whether a stored copy can be used without a request: fresh, and not a page copy while the card is wanted."""
    return row is not None and _fresh(row[3]) and not (card_wanted and not row[4])


def _fetch_copy(reference_name: str, code: str, use_api: bool, api_token: str) -> dict | None:
    """The instruction fetched now, or None when the site cannot give one."""
    try:
        return instruction(reference_name, code, use_api=use_api, api_token=api_token)
    except DrugRefError:
        return None


def _store_copy(connection: sqlite3.Connection, fetched: dict) -> dict:
    stored_at = utc_now()
    connection.execute(
        "INSERT OR REPLACE INTO drug_references "
        "(source, url, shown_for, atc_codes, sections_json, fetched_at, details_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            SOURCE,
            fetched["url"],
            fetched["shown_for"],
            ",".join(fetched["atc"]),
            json.dumps(fetched["sections"], ensure_ascii=False),
            stored_at,
            json.dumps(fetched["details"], ensure_ascii=False) if fetched["details"] else "",
        ),
    )
    return {**fetched, "fetched_at": stored_at}


def cached_instruction(
    connection: sqlite3.Connection, reference_name: str, code: str = "",
    *, use_api: bool = False, api_token: str = "",
) -> dict | None:
    """The instruction from the cache, or fetched and stored (the caller commits).

    Never raises. When the page cannot be fetched or parses to no sections, an
    older cached copy is returned if there is one: an instruction from last
    season is better evidence than none. Without any copy the answer is None.
    """
    try:
        url = _readable(page_url(reference_name, code))
        row = connection.execute(
            "SELECT shown_for, atc_codes, sections_json, fetched_at, details_json FROM drug_references "
            "WHERE source = ? AND url = ?",
            (SOURCE, url),
        ).fetchone()
        # A copy read from the page before the card was switched on is read once more through the card.
        card_wanted = bool(use_api and api_token and _DIGITS.fullmatch(code))
        if _stored_copy_is_current(row, card_wanted):
            return _from_cache(url, row)
        fetched = _fetch_copy(reference_name, code, use_api, api_token)
        if fetched is None or not fetched["sections"]:
            return _from_cache(url, row) if row is not None else None
        return _store_copy(connection, fetched)
    except (DrugRefError, sqlite3.Error, ValueError):
        return None
