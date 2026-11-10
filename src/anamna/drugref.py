"""Medicine reference text from the Ukrainian pharmacy site tabletki.ua.

A person records a medicine; this module finds its page on the site (search
suggestions, then the official instruction for medical use shown there) and
keeps the instruction sections in the ``drug_references`` cache.  Only the
public reference text crosses the wire: the search text and the page name,
never anything from the person's record.
"""

from __future__ import annotations

import html
import http.client
import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

from .config import USER_AGENT
from .db import utc_now

SOURCE = "tabletki"
BASE = "https://tabletki.ua"
SETTING = "drug_lookup_enabled"  # app_settings key; absent or "1" means on, "0" means off
TIMEOUT = 10
MAX_BYTES = 3_000_000
CACHE_DAYS = 90

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


class DrugRefError(Exception):
    """The reference site could not be used; the message names no URL and no search text."""


class _RedirectWithinSite(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith(BASE + "/"):
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


def _open(url: str, data: bytes | None = None) -> str:
    if not url.startswith(BASE + "/"):
        raise DrugRefError("URL outside the reference site refused")
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "uk"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    request = urllib.request.Request(url, data=data, headers=headers)
    opener = urllib.request.build_opener(_RedirectWithinSite)
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            body = response.read(MAX_BYTES + 1)
    except DrugRefError:
        raise
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as exc:
        raise DrugRefError(type(exc).__name__) from None
    if len(body) > MAX_BYTES:
        raise DrugRefError("reply too large")
    return body.decode("utf-8", errors="replace")


def suggest(text: str) -> list[dict]:
    text = text.strip()
    if len(text) < 3:
        return []
    body = urllib.parse.urlencode({"searchText": text}).encode("utf-8")
    reply = _open(BASE + "/ajax/search/suggest", body)
    try:
        items = json.loads(reply)
    except ValueError as exc:
        raise DrugRefError("suggest reply is not JSON") from exc
    if not isinstance(items, list):
        raise DrugRefError("suggest reply is not a list")
    found: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            raise DrugRefError("suggest item is not an object")
        if item.get("type") != 1 or item.get("screenViewType") not in _SUGGEST_KINDS:
            continue
        reference_name = item.get("urlName")
        name = item.get("name")
        if not isinstance(reference_name, str) or not reference_name or not isinstance(name, str):
            continue
        kind = _SUGGEST_KINDS[item["screenViewType"]]
        found.append({
            "kind": kind,
            "code": str(item.get("code") or ""),
            "name": name,
            "reference_name": reference_name,
            "maker": str(item.get("description") or "") if kind == "product" else "",
        })
        if len(found) == _SUGGEST_LIMIT:
            break
    return found


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


def cached_instruction(connection: sqlite3.Connection, reference_name: str, code: str = "") -> dict | None:
    """The instruction from the cache, or fetched and stored (the caller commits).

    Never raises: a failed fetch or a page without sections gives None and stores nothing.
    """
    try:
        url = _readable(page_url(reference_name, code))
        row = connection.execute(
            "SELECT shown_for, atc_codes, sections_json, fetched_at FROM drug_references "
            "WHERE source = ? AND url = ?",
            (SOURCE, url),
        ).fetchone()
        if row is not None and _fresh(row[3]):
            return {
                "url": url,
                "sections": json.loads(row[2]),
                "atc": [code_ for code_ in row[1].split(",") if code_],
                "shown_for": row[0],
            }
        fetched = instruction(reference_name, code)
        if not fetched["sections"]:
            return None
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
