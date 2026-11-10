"""Optional Paperless-ngx integration (https://docs.paperless-ngx.com/api/).

The application must behave identically with this switched off: every caller
treats :class:`PaperlessError` — and an unconfigured setup — as "no Paperless
today" and renders the page it would have rendered anyway.  Paperless never
becomes a source of clinical facts; it holds a *copy* of a document this
application already owns, and what comes back (full-text search matches, a
link to the copy) is navigation, not data.

Two layers of consent, mirroring the AI assist pattern:

* the operator enables the feature and names the server in ``app_settings``
  (managed from /admin/paperless);
* each person stores their own Paperless API token and separately opts in to
  having new uploads forwarded.  Documents sent with a person's token belong
  to that person's Paperless account — Paperless enforces the ownership, this
  application never mixes tokens.

Verified against Paperless-ngx 3.0.5 (API version 10) on 2026-08-06:
``POST /api/documents/post_document/`` answers a quoted task UUID; the
consumption task's document id arrives in ``result_data.document_id`` (older
servers used ``related_document``, both are read); full-text search is
``GET /api/documents/?query=…``; authentication is ``Authorization: Token …``.
"""

from __future__ import annotations

import functools
import ipaddress
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .config import USER_AGENT, Settings, log_run, per_request, resolve_source_path
from .db import connect, transaction, utc_now

logger = logging.getLogger("anamna.paperless")

REQUEST_TIMEOUT = 15
UPLOAD_TIMEOUT = 120  # a scanned bundle is tens of megabytes on a home LAN

#: Largest response body read into memory.  Every answer these calls expect is
#: JSON of a few kilobytes to a few megabytes; anything larger is not one.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024

#: Give up re-sending a document after this many refusals; see migration 020.
MAX_UPLOAD_ATTEMPTS = 3

# Documents currently being uploaded, so two sync passes cannot send the same
# bytes twice.  Process-local by design: a restart forgets them, which is the
# correct answer for an upload that never finished.
_inflight: set[tuple[str, str]] = set()
_inflight_lock = threading.Lock()


class PaperlessError(Exception):
    """The server is unreachable, refused the request, or answered nonsense.

    ``status`` is the HTTP code when Paperless answered at all.  When not given
    it is read from an ``HTTP NNN:`` message prefix, the form :func:`_request`
    builds, so a message carrying the code also carries it as an attribute.
    """

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        if status is None:
            match = re.match(r"HTTP (\d{3})\b", message)
            status = int(match.group(1)) if match else None
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects.

    ``urllib`` copies every header except content-length/type onto the
    redirected request, so a 302 would hand ``Authorization: Token <secret>``
    to whatever host the Location names.  Paperless never redirects its own
    API, so a 3xx here is a misconfigured URL or an attack; returning None
    turns it into an :class:`urllib.error.HTTPError`, which the caller
    already renders as "that server did not answer like Paperless".
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_opener = urllib.request.build_opener(_NoRedirect())


# --- configuration -----------------------------------------------------------

SETTING_KEYS = ("paperless_enabled", "paperless_url")


@per_request
def paperless_settings(settings: Settings) -> dict[str, str]:
    with connect(settings) as connection:
        stored = dict(
            connection.execute(
                "SELECT key, value FROM app_settings WHERE key IN (?, ?)", SETTING_KEYS
            ).fetchall()
        )
    # The env var seeds an unconfigured instance; once the admin has saved the
    # field it wins even when empty, or clearing the address would silently
    # reinstate the old server and keep sending documents to it.
    url = stored["paperless_url"] if "paperless_url" in stored else os.getenv("PAPERLESS_URL", "")
    return {
        "enabled": stored.get("paperless_enabled", "1"),
        "url": url.strip().rstrip("/"),
    }


def url_is_acceptable(url: str) -> bool:
    """Whether this is a usable Paperless address at all."""
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def url_is_plaintext_remote(url: str) -> bool:
    """``http://`` to somewhere that is not this machine or the local network.

    Not refused — a self-hosted Paperless is often reached by a LAN hostname
    this cannot recognise, and locking the operator out of their own server
    would be the worse failure.  It is said plainly on the page instead,
    because over the public internet plaintext exposes every uploaded report
    and every user's token to anyone on the path.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or not parsed.hostname:
        return False
    host = parsed.hostname
    # A single-label name ("nas") or a reserved local suffix is LAN by
    # construction; a dotted public name is the case worth warning about.
    if "." not in host or host.partition(".")[2] in {
        "local", "lan", "home", "internal", "home.arpa", "localhost", "test",
    }:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (address.is_private or address.is_loopback)


def forget_all_consent(settings: Settings) -> int:
    """Drop every stored token and upload opt-in; returns how many were held.

    Consent was given for a *named* server — the profile page says so — so
    changing the address has to ask again rather than silently pointing
    everyone's documents and credentials at a new host.
    """
    with connect(settings) as connection:
        held = connection.execute(
            "SELECT COUNT(*) FROM paperless_accounts WHERE api_token <> '' OR upload_enabled = 1"
        ).fetchone()[0]
        connection.execute(
            "UPDATE paperless_accounts SET api_token='', upload_enabled=0, updated_at=?", (utc_now(),)
        )
        # Task and document IDs are local to the old server. Reusing them on
        # another server could link a report to an unrelated remote document.
        connection.execute(
            "UPDATE documents SET paperless_id=NULL, paperless_task_id=NULL, paperless_attempts=0"
        )
    return int(held)


def save_paperless_settings(settings: Settings, values: dict[str, str]) -> None:
    with connect(settings) as connection:
        for key, value in values.items():
            connection.execute(
                """INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                (key, value, utc_now()),
            )


def paperless_active(settings: Settings) -> bool:
    config = paperless_settings(settings)
    return config["enabled"] == "1" and bool(config["url"])


def account(settings: Settings, user_id: str) -> dict[str, object]:
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT api_token, upload_enabled FROM paperless_accounts WHERE user_id=?",
            (user_id,),
        ).fetchone()
    return {
        "token": row["api_token"] if row else "",
        "upload_enabled": bool(row and row["upload_enabled"]),
    }


def save_account(
    settings: Settings, user_id: str, *, token: str | None = None, upload_enabled: bool | None = None
) -> None:
    """Upsert a person's connection.  ``None`` keeps the stored value — the
    form never echoes the token back, so blank is what an untouched form
    submits."""
    current = account(settings, user_id)
    stored_token = current["token"] if token is None else token
    stored_upload = current["upload_enabled"] if upload_enabled is None else upload_enabled
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO paperless_accounts(user_id, api_token, upload_enabled, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET api_token = excluded.api_token,
                   upload_enabled = excluded.upload_enabled, updated_at = excluded.updated_at""",
            (user_id, stored_token, 1 if stored_upload else 0, utc_now()),
        )


def connection_for(settings: Settings, user_id: str) -> tuple[str, str] | None:
    """``(url, token)`` when the feature is on and this person is connected —
    what search enrichment and link resolution need."""
    config = paperless_settings(settings)
    if config["enabled"] != "1" or not config["url"]:
        return None
    token = str(account(settings, user_id)["token"])
    return (config["url"], token) if token else None


def upload_ready(settings: Settings, user_id: str) -> tuple[str, str] | None:
    """Like :func:`connection_for`, but only when the person has also opted in
    to sending uploads — connecting to read is not consenting to write."""
    config = paperless_settings(settings)
    if config["enabled"] != "1" or not config["url"]:
        return None
    person = account(settings, user_id)
    if not person["token"] or not person["upload_enabled"]:
        return None
    return (config["url"], str(person["token"]))


# --- HTTP --------------------------------------------------------------------


def _request(
    url: str,
    token: str,
    path: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    timeout: int = REQUEST_TIMEOUT,
):
    """One request, parsed JSON back (``None`` for an empty body); every
    failure becomes :class:`PaperlessError` so callers degrade uniformly."""
    request = urllib.request.Request(
        url.rstrip("/") + path,
        data=data,
        method=method,
        headers={
            **({"Authorization": f"Token {token}"} if token else {}),
            "Accept": "application/json",
            # Cloudflare refuses urllib's default signature; see USER_AGENT.
            "User-Agent": USER_AGENT,
            **(headers or {}),
        },
    )
    try:
        with _opener.open(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise PaperlessError("paperless: response too large")
    except urllib.error.HTTPError as exc:
        detail = exc.read(MAX_RESPONSE_BYTES).decode("utf-8", "replace")[:300]
        raise PaperlessError(f"HTTP {exc.code}: {detail}", status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PaperlessError(str(exc)) from exc
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PaperlessError(f"unparseable reply: {body[:200]!r}") from exc


def test_connection(url: str, token: str) -> int:
    """How many documents this token can see; raises :class:`PaperlessError`.
    One authenticated round trip, so "configured" and "working" stay
    different claims."""
    payload = _request(url, token, "/api/documents/?page_size=1")
    if not isinstance(payload, dict) or "count" not in payload:
        raise PaperlessError("that server does not answer like Paperless")
    return int(payload["count"] or 0)


#: A 403 that never reached Paperless.  Cloudflare, and proxies like it,
#: answer with their own numbered error page rather than the JSON `detail`
#: Paperless returns — telling them apart is the difference between "store
#: your token" and "something in front of that server is turning us away",
#: which is a different job for a different person.
_PROXY_BLOCK_RE = re.compile(r"error[ _]code|cloudflare|<!doctype|<html", re.I)


def blocked_by_proxy(detail: str) -> bool:
    return bool(_PROXY_BLOCK_RE.search(detail)) and '"detail"' not in detail


def probe(url: str, token: str) -> dict[str, object]:
    """What the admin test button reports.  Without a token a Paperless server
    still proves it is there by demanding one (401) — that is reachability,
    not an error."""
    answer = {"reachable": False, "authenticated": False, "documents": None, "blocked": False}
    try:
        return {**answer, "reachable": True, "authenticated": True,
                "documents": test_connection(url, token)}
    except PaperlessError as exc:
        detail = str(exc)
        if blocked_by_proxy(detail):
            # Reached *something*, but not Paperless.  Saying "it asks for a
            # token" here sends the operator to look for a credential problem
            # that does not exist.
            return {**answer, "blocked": True}
        if "HTTP 401" in detail or "HTTP 403" in detail:
            return {**answer, "reachable": True}
        return answer


def upload_file(url: str, token: str, path: Path, *, title: str = "", created: str = "") -> str:
    """Hand one file to Paperless; returns the consumption task's UUID."""
    boundary = uuid.uuid4().hex
    fields = [("title", title), ("created", created)]
    body = b""
    for name, value in fields:
        if value:
            body += (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
            ).encode("utf-8")
    filename = path.name.replace('"', "")
    body += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    body += path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")
    payload = _request(
        url,
        token,
        "/api/documents/post_document/",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout=UPLOAD_TIMEOUT,
    )
    if not isinstance(payload, str) or not payload:
        raise PaperlessError(f"expected a task id, got {str(payload)[:200]!r}")
    return payload


def task_state(url: str, token: str, task_id: str) -> dict[str, object]:
    """``{"status", "document_id"}`` for one consumption task.  Status is
    lower-cased ("pending"/"started"/"success"/"failure"); the document id is
    present only on success."""
    payload = _request(
        url, token, "/api/tasks/?task_id=" + urllib.parse.quote(task_id), timeout=10
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    if not results:
        return {"status": "unknown", "document_id": None}
    row = results[0]
    document_id = row.get("related_document")
    result_data = row.get("result_data")
    if not document_id and isinstance(result_data, dict):
        document_id = result_data.get("document_id")
    try:
        document_id = int(document_id) if document_id else None
    except (TypeError, ValueError):
        document_id = None
    return {"status": str(row.get("status") or "").lower(), "document_id": document_id}


def search_ids(url: str, token: str, query: str, among: tuple[int, ...]) -> list[int]:
    """Which of ``among`` (Paperless ids this person's documents link to)
    match the query's full text.

    Filtered over there rather than here: the archive holds far more than
    this record (1849 documents against 301 on 2026-11-09), so a plain
    "top 50" let unrelated papers crowd out linked matches — 7 of 23 for
    "гемоглобін".  Paperless applies ``id__in`` before ranking.
    """
    if not among:
        return []
    # ponytail: the ids ride in the URL, ~6 bytes each; past a few thousand
    # linked documents this nears proxy URL limits and wants chunking.
    payload = _request(
        url,
        token,
        f"/api/documents/?query={urllib.parse.quote(query)}&page_size={len(among)}&fields=id"
        f"&id__in={','.join(map(str, among))}",
        timeout=8,
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    return [int(row["id"]) for row in results or [] if row.get("id")]


def document_url(url: str, paperless_id: int) -> str:
    return f"{url.rstrip('/')}/documents/{paperless_id}/details"


# ponytail: one flat dict per process, 60 s TTL, cleared when it grows past
# 200 entries — enough to keep search-as-you-type from re-asking Paperless on
# every keystroke, and to stop poking a server that just failed.
_SEARCH_TTL = 60
_search_cache: dict[tuple[str, str, str, tuple[int, ...]], tuple[float, list[int]]] = {}

# When the server fails, remember the *server* rather than the query.  Search
# runs on every keystroke, so a host that black-holes packets (rather than
# refusing them) would otherwise cost a full timeout per prefix typed, and
# these are sync endpoints holding a threadpool thread while they wait.
_DOWN_TTL = 60
_down_until: dict[str, float] = {}


def reset_caches() -> None:
    """Forget both module-level caches (tests; a settings change)."""
    _search_cache.clear()
    _down_until.clear()


def cached_search_ids(url: str, token: str, query: str, among: tuple[int, ...]) -> list[int]:
    key = (url, token, query, among)
    now = time.monotonic()
    hit = _search_cache.get(key)
    if hit and now - hit[0] < _SEARCH_TTL:
        return hit[1]
    if now < _down_until.get(url, 0.0):
        return []
    try:
        ids = search_ids(url, token, query, among)
    except PaperlessError as exc:
        logger.warning("paperless: search failed: %s", exc)
        _down_until[url] = now + _DOWN_TTL
        return []
    _down_until.pop(url, None)
    if len(_search_cache) > 200:
        _search_cache.clear()
    _search_cache[key] = (now, ids)
    return ids


# --- documents kept here, mirrored there -------------------------------------


def push_document(settings: Settings, document_id: str) -> bool:
    """Send one stored document to its owner's Paperless account.

    Never raises: intake calls this after every successful ingest, and a
    Paperless that is down must not fail the upload that just worked.  Exact
    duplicates (``duplicate_of_document_id`` set) are skipped — the original
    row carries the link, and Paperless would refuse the same bytes anyway.
    """
    claim = (str(settings.database_path.resolve()), document_id)
    # Claim before reading. A caller holding a stale preflight row must not
    # send again after another upload has already finished and released it.
    with _inflight_lock:
        if claim in _inflight:
            return False
        _inflight.add(claim)
    try:
        return _push_document(settings, document_id)
    except Exception:  # noqa: BLE001 - the contract above is the whole point
        # Reading the file, the upload and both writes can fail in ways that
        # are not PaperlessError (a locked database, an antivirus holding the
        # just-written file).  Letting one escape reaches run_job's blanket
        # handler, which marks an ingest that already succeeded as failed and
        # zeroes its observation count.  Mirroring is never worth that.
        logger.warning("paperless: upload of document %s failed", document_id, exc_info=True)
        return False
    finally:
        with _inflight_lock:
            _inflight.discard(claim)


def _refused_by_paperless(exc: Exception) -> bool:
    """A 4xx that Paperless answered with, other than 408 (timeout) and 429
    (rate limit): the server judged the request, and will judge it the same way."""
    return (
        isinstance(exc, PaperlessError)
        and exc.status is not None
        and 400 <= exc.status <= 499
        and exc.status not in (408, 429)
    )


def _push_document(settings: Settings, document_id: str) -> bool:
    with connect(settings) as connection:
        row = connection.execute(
            """SELECT owner_user_id, source_path, title, report_date, duplicate_of_document_id,
                      paperless_task_id, paperless_id, paperless_attempts
                 FROM documents WHERE id=?""",
            (document_id,),
        ).fetchone()
    if not row or row["paperless_id"] or row["paperless_task_id"] or row["duplicate_of_document_id"]:
        return False
    # A rejection Paperless will repeat — a duplicate checksum, a PDF its OCR
    # cannot read — is not worth re-uploading on every sync forever.  The
    # profile says how many were refused, so giving up stays visible.
    if int(row["paperless_attempts"] or 0) >= MAX_UPLOAD_ATTEMPTS:
        return False
    ready = upload_ready(settings, str(row["owner_user_id"]))
    if not ready:
        return False
    # The stored path is absolute on the machine that ingested it; a container
    # serving the copied database has to find the same file under its own
    # sources directory, exactly as the viewer and a rescan do.
    path = resolve_source_path(settings, str(row["source_path"] or ""))
    if not path.is_file():
        logger.warning("paperless: document %s has no readable source file", document_id)
        return False
    try:
        task_id = upload_file(
            *ready, path, title=str(row["title"] or path.stem), created=str(row["report_date"] or "")
        )
        with transaction(settings, immediate=True) as connection:
            if connection_for(settings, str(row["owner_user_id"])) != ready:
                return False
            # Acceptance only queues OCR; it is not a successful consumption.
            # Preserve previous refusals until the task actually succeeds.
            connection.execute(
                "UPDATE documents SET paperless_task_id=? WHERE id=?",
                (task_id, document_id),
            )
    except Exception as exc:  # noqa: BLE001 - a copy service degrades, never raises
        # Only Paperless turning the document down counts towards the cap.  An
        # outage, a timeout or a 5xx says nothing about this document, and
        # counting it would stop mirroring for good after three scheduler passes.
        if _refused_by_paperless(exc):
            with connect(settings) as connection:
                connection.execute(
                    "UPDATE documents SET paperless_attempts=paperless_attempts+1 WHERE id=?",
                    (document_id,),
                )
        logger.warning("paperless: upload of document %s failed: %s", document_id, exc)
        return False
    return True


def resolve_pending(settings: Settings, document_id: str) -> int | None:
    """Turn a stored task id into the Paperless document id, once consumption
    (OCR included) has finished over there.

    Returns the Paperless id when linked, ``None`` while pending or on any
    failure.  A failed task clears the task id so a later sync may try again;
    an unreachable server changes nothing.
    """
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT owner_user_id, paperless_task_id, paperless_id FROM documents WHERE id=?",
            (document_id,),
        ).fetchone()
    if not row:
        return None
    if row["paperless_id"]:
        return int(row["paperless_id"])
    if not row["paperless_task_id"]:
        return None
    ready = connection_for(settings, str(row["owner_user_id"]))
    if not ready:
        return None
    try:
        state = task_state(*ready, str(row["paperless_task_id"]))
    except PaperlessError:
        return None
    if state["status"] == "success" and state["document_id"]:
        with transaction(settings, immediate=True) as connection:
            if connection_for(settings, str(row["owner_user_id"])) != ready:
                return None
            updated = connection.execute(
                "UPDATE documents SET paperless_id=?, paperless_task_id=NULL, paperless_attempts=0 WHERE id=? AND paperless_task_id=?",
                (state["document_id"], document_id, row["paperless_task_id"]),
            )
        return int(state["document_id"]) if updated.rowcount else None
    if state["status"] == "failure":
        with connect(settings) as connection:
            connection.execute(
                "UPDATE documents SET paperless_task_id=NULL, paperless_attempts=paperless_attempts+1 WHERE id=? AND paperless_task_id=?",
                (document_id, row["paperless_task_id"]),
            )
    return None


def link_counts(settings: Settings, user_id: str) -> dict[str, int]:
    """What the profile shows: of this person's documents, how many have a
    Paperless copy, how many are on their way, how many were never sent."""
    with connect(settings) as connection:
        row = connection.execute(
            """SELECT COUNT(*) total,
                      COALESCE(SUM(paperless_id IS NOT NULL), 0) linked,
                      COALESCE(SUM(paperless_id IS NULL AND paperless_task_id IS NOT NULL), 0) pending,
                      COALESCE(SUM(paperless_id IS NULL AND paperless_task_id IS NULL
                                   AND paperless_attempts >= ?), 0) refused
                 FROM documents WHERE owner_user_id=? AND duplicate_of_document_id IS NULL""",
            (MAX_UPLOAD_ATTEMPTS, user_id),
        ).fetchone()
    counts = dict(row)
    # "Refused" is carved out of "unsent" rather than added to it: the page
    # would otherwise keep offering to send documents Paperless has already
    # turned down three times.
    counts["unsent"] = counts["total"] - counts["linked"] - counts["pending"] - counts["refused"]
    return counts


def clear_attempts(settings: Settings, user_id: str) -> int:
    """Forget this person's refusal counts; returns how many were carrying one.

    Called when a connection test succeeds, because that proves the cause of
    the earlier refusals is gone.  See `MAX_UPLOAD_ATTEMPTS`.
    """
    with connect(settings) as connection:
        cursor = connection.execute(
            "UPDATE documents SET paperless_attempts=0 WHERE owner_user_id=? AND paperless_attempts>0",
            (user_id,),
        )
        return int(cursor.rowcount)


def sync_documents(settings: Settings, user_id: str, *, attempted_only: bool = False) -> dict[str, int]:
    """Bring every document this person owns into Paperless: resolve uploads
    still pending, retry the ones whose consumption failed, push the ones
    never sent.  One pass repairs everything repairable — a wrong token fixed
    after the fact, a server that was down, a rejected file — so "press sync
    once" is the whole recovery story.  Sequential on purpose: a home server
    digesting one OCR at a time is the polite pace.

    ``attempted_only`` limits the pass to documents already handed over at
    least once (a task id, or a recorded refusal): what the scheduler runs.
    Sending a document that predates the person's consent stays a button
    press, because "send new uploads" is what they agreed to."""
    pushed = resolved = 0
    with connect(settings) as connection:
        rows = connection.execute(
            f"""SELECT id, paperless_task_id FROM documents
               WHERE owner_user_id=? AND paperless_id IS NULL AND duplicate_of_document_id IS NULL
               {"AND (paperless_task_id IS NOT NULL OR paperless_attempts > 0)" if attempted_only else ""}
               ORDER BY imported_at""",
            (user_id,),
        ).fetchall()
    for row in rows:
        document_id = str(row["id"])
        if row["paperless_task_id"]:
            if resolve_pending(settings, document_id):
                resolved += 1
                continue
            with connect(settings) as connection:
                still = connection.execute(
                    "SELECT paperless_task_id FROM documents WHERE id=?", (document_id,)
                ).fetchone()
            if still and still["paperless_task_id"]:
                continue  # genuinely still being consumed over there
            # The task failed and resolve_pending cleared it — fall through
            # and send the file again now, not on some second press.
        if push_document(settings, document_id):
            pushed += 1
    return {"pushed": pushed, "resolved": resolved}


def sync_all_users(settings: Settings, *, attempted_only: bool = False) -> dict[str, int]:
    """The same sync for every person who stored a token *and* consented to
    sending — what the admin presses when Paperless arrives mid-life and the
    record predates it.  Consent is per person and is honoured here exactly as
    it is on upload: an account without the checkbox is not touched."""
    totals = {"users": 0, "pushed": 0, "resolved": 0}
    with connect(settings) as connection:
        user_ids = [
            row[0]
            for row in connection.execute(
                "SELECT user_id FROM paperless_accounts WHERE api_token <> '' AND upload_enabled = 1"
            )
        ]
    for user_id in user_ids:
        if not upload_ready(settings, str(user_id)):
            continue  # the operator may have switched the feature off mid-run
        outcome = sync_documents(settings, str(user_id), attempted_only=attempted_only)
        totals["users"] += 1
        totals["pushed"] += outcome["pushed"]
        totals["resolved"] += outcome["resolved"]
    return totals


def start_sync(settings: Settings, user_id: str) -> None:
    """The sync as a fire-and-forget background thread, so the profile POST
    answers immediately; progress is visible in the counts on reload."""
    threading.Thread(
        target=_logged, args=("paperless sync", sync_documents, settings, user_id),
        name="anamna-paperless-sync", daemon=True,
    ).start()


def start_sync_all(settings: Settings) -> None:
    """:func:`sync_all_users` in the background, for the admin button."""
    threading.Thread(
        target=_logged, args=("paperless sync-all", sync_all_users, settings),
        name="anamna-paperless-sync-all", daemon=True,
    ).start()


#: How often the scheduler links finished uploads.  Paperless OCR takes
#: seconds to minutes per file, so five minutes keeps a link close behind it.
SCHEDULE_SECONDS = 300


def start_scheduler(settings: Settings) -> threading.Event:
    """Link uploads Paperless has finished reading, and retry ones it refused
    or never received, for every consenting account; stop with ``.set()``.

    An upload only stores a task id: the document id exists once OCR is done
    over there.  Before this loop that id was fetched only when someone opened
    the document's page or pressed sync, so every automatic import (lab
    syncs) stayed "on the way" indefinitely: 243 on the sandbox on
    2026-11-09, every one already consumed successfully by Paperless."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(SCHEDULE_SECONDS):
            try:
                active = paperless_active(settings)
            except Exception:  # noqa: BLE001 — a locked database must not end the loop
                logger.warning("paperless scheduler: cannot read settings", exc_info=True)
                continue
            if active:
                _logged("paperless-scheduler", functools.partial(sync_all_users, attempted_only=True), settings)

    threading.Thread(target=loop, name="anamna-paperless-scheduler", daemon=True).start()
    return stop


def _logged(loop: str, target, *args) -> None:
    started = time.monotonic()
    try:
        log_run(logger, loop, started, target(*args))
    except Exception as exc:  # noqa: BLE001 — a background thread has no caller to tell
        log_run(logger, loop, started, error=exc)


def instance_counts(settings: Settings) -> dict[str, int]:
    """What the admin page shows: across every consenting account, how many
    documents have a Paperless copy, how many are on their way, how many wait."""
    with connect(settings) as connection:
        row = connection.execute(
            """SELECT COUNT(*) total,
                      COALESCE(SUM(d.paperless_id IS NOT NULL), 0) linked,
                      COALESCE(SUM(d.paperless_id IS NULL AND d.paperless_task_id IS NOT NULL), 0) pending,
                      COALESCE(SUM(d.paperless_id IS NULL AND d.paperless_task_id IS NULL
                                   AND d.paperless_attempts >= ?), 0) refused
                 FROM documents d
                 JOIN paperless_accounts a ON a.user_id = d.owner_user_id
                WHERE a.api_token <> '' AND a.upload_enabled = 1
                  AND d.duplicate_of_document_id IS NULL""",
            (MAX_UPLOAD_ATTEMPTS,),
        ).fetchone()
    counts = dict(row)
    # Same carve-out as link_counts, so the admin page and the profile do not
    # report different numbers for the same documents.
    counts["unsent"] = counts["total"] - counts["linked"] - counts["pending"] - counts["refused"]
    return counts
