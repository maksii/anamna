"""What every lab connection shares: the one HTTP door, and reading lab rows.

Every network call of every provider goes through :func:`_http` — tests
replace that one function.  Response bodies are never logged: they are a
person's lab results, and the request paths carry order and person numbers.
"""

from __future__ import annotations

import html
import json
import logging
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from .. import health  # noqa: F401  -- merges UNIT_SYNONYMS into canonical_unit's table
from ..config import USER_AGENT

logger = logging.getLogger("anamna.labsync")

REQUEST_TIMEOUT = 20
PDF_TIMEOUT = 120
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_PDF_BYTES = 60 * 1024 * 1024
ERROR_REPLY = "labsync.error_reply"


class LabSyncError(Exception):
    """Something the person or operator can act on; ``key`` is a message key."""

    def __init__(self, key: str, status: int | None = None):
        super().__init__(key)
        self.key = key
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would replay ``Authorization`` and
    ``Cookie`` to whatever host the Location names.  A 3xx becomes an error."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_opener = urllib.request.build_opener(_NoRedirect())


def _http(method: str, url: str, *, headers: dict[str, str], body: bytes | None = None,
          timeout: int = REQUEST_TIMEOUT, limit: int = MAX_JSON_BYTES) -> tuple[int, list[str], bytes]:
    """One request: ``(status, set_cookie_headers, body)``.  Network failure
    raises ``labsync.error_unreachable``; an HTTP error status is returned."""
    request = urllib.request.Request(url, data=body, method=method,
                                     headers={"User-Agent": USER_AGENT, **headers})
    try:
        with _opener.open(request, timeout=timeout) as response:
            return response.status, response.headers.get_all("Set-Cookie") or [], response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.headers.get_all("Set-Cookie") if exc.headers else None) or [], b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("labsync: unreachable: %s", type(exc).__name__)
        raise LabSyncError("labsync.error_unreachable") from None


def _encode_body(payload: object | None, form: dict[str, str] | None) -> tuple[bytes | None, str]:
    if form is not None:
        return urllib.parse.urlencode(form).encode("ascii"), "application/x-www-form-urlencoded; charset=UTF-8"
    return (json.dumps(payload).encode("utf-8") if payload is not None else None), "application/json"


def call(method: str, url: str, *, headers: dict[str, str], payload: object | None = None,
         want: str = "json", form: dict[str, str] | None = None) -> tuple[object, list[str]]:
    """JSON (or PDF bytes) back, with the Set-Cookie headers; 401/403 become
    ``labsync.error_auth``, anything else unexpected ``labsync.error_reply``.
    ``form`` sends an urlencoded body instead of JSON (an OAuth token call)."""
    data, kind = _encode_body(payload, form)
    headers = {
        "Accept": "application/pdf" if want == "pdf" else "application/json",
        **({"Content-Type": kind} if data is not None else {}),
        **headers,
    }
    limit = MAX_PDF_BYTES if want == "pdf" else MAX_JSON_BYTES
    status, cookies, body = _http(method, url, headers=headers, body=data,
                                  timeout=PDF_TIMEOUT if want == "pdf" else REQUEST_TIMEOUT, limit=limit)
    if status in (401, 403):
        raise LabSyncError("labsync.error_auth", status)
    if not 200 <= status < 300 or len(body) > limit:
        logger.warning("labsync: %s request answered HTTP %s", method, status)
        raise LabSyncError(ERROR_REPLY, status)
    if want == "pdf":
        if not body.startswith(b"%PDF"):
            raise LabSyncError("labsync.error_pdf")
        return body, cookies
    try:
        return (json.loads(body.decode("utf-8")) if body else None), cookies
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise LabSyncError(ERROR_REPLY) from None


def url_is_acceptable(url: str) -> bool:
    """HTTPS to a bare origin; plain HTTP only to this machine (tests, a fake
    server).  No credentials, path, query or fragment: the person's secret is
    sent to exactly this origin and nowhere else."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    if parsed.path not in ("", "/"):
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def digits(value: object) -> str:
    text = str(value if value is not None else "").strip()
    if not re.fullmatch(r"\d{1,20}", text):
        raise LabSyncError(ERROR_REPLY)
    return text


def sex_of(value: object) -> str:
    text = str(value or "").strip().casefold()
    if text in {"m", "male", "ч", "чоловіча", "man", "1"}:
        return "male"
    if text in {"f", "female", "ж", "жіноча", "woman", "2"}:
        return "female"
    return ""


def iso_day(value: object) -> str:
    text = str(value or "")[:10]
    return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else ""


# --- reading rows ---------------------------------------------------------------


def _array_elements(raw: str) -> list[tuple[str, bool]]:
    """The elements of a Postgres array body, each with whether it was quoted."""
    items: list[tuple[str, bool]] = []
    current: list[str] = []
    quoted = in_quotes = False
    index = 0
    while index < len(raw):
        char = raw[index]
        if in_quotes and char == "\\" and index + 1 < len(raw):
            index += 1
            current.append(raw[index])
        elif in_quotes and char == '"':
            in_quotes = False
        elif not in_quotes and char == '"':
            in_quotes = quoted = True
        elif not in_quotes and char == ",":
            items.append(("".join(current), quoted))
            current, quoted = [], False
        else:
            current.append(char)
        index += 1
    items.append(("".join(current), quoted))
    return items


def parse_norm(text: object) -> list[str]:
    """EskuLab's Postgres array literal of reference lines, each ending in
    ``#%``: ``{"< 3.8 низького ризику#%","Чоловіки: 130-170#%"}``,
    ``{3.1-19.9#%}``, ``{NULL}``.  Quoted and bare elements may be mixed."""
    raw = str(text or "").strip()
    if raw.startswith("{") and raw.endswith("}"):
        raw = raw[1:-1]
    lines = []
    for item, was_quoted in _array_elements(raw):
        if not was_quoted and item.strip().upper() == "NULL":
            continue
        line = item.strip()
        if line.endswith("#%"):
            line = line[:-2]
        line = " ".join(line.split())
        if line:
            lines.append(line)
    return lines


_SUP_RE = re.compile(r"<sup>([^<]*)</sup>", re.I)
_TAG_RE = re.compile(r"<[^>]*>")


def clean_unit(text: object) -> str:
    """``10<sup>9</sup>/л`` → ``10^9/л``; ``-`` and blanks are "no unit"."""
    raw = _SUP_RE.sub(lambda match: "^" + match.group(1).strip(), str(text or ""))
    raw = " ".join(html.unescape(_TAG_RE.sub("", raw)).split())
    return "" if raw in {"-", "—", "–"} else raw


def lab_row(*, test: object, result: object, units: object = "", resulttype: str = "", state: str = "",
            norm: list[str] | None = None, packet: object = "", material: object = "", idtest: object = "") -> dict:
    """The provider-neutral row the cross-check reads."""
    return {
        "idtest": str(idtest or ""),
        "test": " ".join(str(test or "").split())[:300],
        "packet": " ".join(str(packet or "").split())[:300],
        # Long enough for a whole coprogram or antibiogram block, which the
        # cross-check searches to recognise the observations that came from it.
        "result": str(result if result is not None else "").strip()[:100_000],
        "units": clean_unit(units)[:80],
        "resulttype": str(resulttype or "").strip().casefold(),
        "state": str(state or "").strip().casefold(),
        "norm": [line for line in (norm or []) if line][:40],
        "material": " ".join(str(material or "").split())[:120],
    }


# --- names and values -------------------------------------------------------------

#: Cyrillic letters that print identically to Latin ones.  Synevo's «МСН» and
#: «МСНС» are Cyrillic homoglyphs of MCH and MCHC, and EskuLab mixes scripts
#: inside one abbreviation («PСТ»).  Folding both sides through the same map
#: makes them one key; two genuinely different names stay different because
#: every other letter still has to agree.
_HOMOGLYPHS = str.maketrans(
    {"а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o",
     "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "і": "i",
     "’": "'", "ʼ": "'", "`": "'", "ʹ": "'", "–": "-", "—": "-", "−": "-"}
)
_BRACKETS_RE = re.compile(r"\([^()]*\)")
_SECTION_RE = re.compile(r"^[^:()]{3,60}:\s+(?=\S)")


def name_key(name: object) -> str:
    """Casefolded, homoglyph-folded, whitespace removed entirely — so
    «відношення(МНВ/INR)» and «відношення (МНВ/INR)» are one name."""
    text = unicodedata.normalize("NFKC", str(name or "")).casefold().translate(_HOMOGLYPHS)
    return re.sub(r"\s+", "", text).strip(".,:;")


def loose_name_key(name: object) -> str:
    """:func:`name_key` without bracketed groups (specimen, abbreviation) and
    without a leading section label («Аналіз крові: …»).  The cross-check uses
    it only when it is unambiguous on both sides: on its own it would fold
    RDW-SD into RDW-CV, or «Базофіли (абс.)» into the percentage."""
    text = _SECTION_RE.sub("", str(name or ""))
    while _BRACKETS_RE.search(text):
        text = _BRACKETS_RE.sub("", text)
    return name_key(text)


_COMPARATOR_RE = re.compile(r"^\s*(<=|>=|≤|≥|<|>)\s*")
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def comparator(sign: object) -> str | None:
    sign = str(sign or "").strip()
    return {"≤": "<=", "≥": ">="}.get(sign, sign) or None


def parse_result(text: object) -> tuple[str | None, float | None]:
    """``"3.29"`` → (None, 3.29); ``"<0,5"`` → ("<", 0.5); words → (None, None)."""
    raw = str(text or "").strip()
    match = _COMPARATOR_RE.match(raw)
    sign = None
    if match:
        sign = comparator(match.group(1))
        raw = raw[match.end():]
    raw = raw.replace("\xa0", "").replace(" ", "").replace(",", ".")
    if _NUMBER_RE.fullmatch(raw):
        return sign, float(raw)
    return None, None
