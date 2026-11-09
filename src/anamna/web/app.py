from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from collections import Counter, OrderedDict
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime, timedelta
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache, partial
from pathlib import Path, PurePath
from typing import Annotated, Callable
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import anyio
import uvicorn
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from ..ai import (
    DEFAULT_MODELS as AI_DEFAULT_MODELS,
    EFFORTS as AI_EFFORTS,
    FALLBACK_MODELS as AI_FALLBACK_MODELS,
    PAID_PROVIDERS as AI_PAID_PROVIDERS,
    PROVIDER_HOSTS as AI_PROVIDER_HOSTS,
    PROVIDER_NAMES as AI_PROVIDER_NAMES,
    TASKS as AI_TASKS,
    AIUnavailable,
    ai_active,
    complete as ai_complete,
    document_hints,
    cached_models as cached_ai_models,
    list_models as list_ai_models,
    parse_admin_form as parse_ai_admin_form,
    provider_host as ai_provider_host,
    review_limits as ai_review_limits,
    ai_settings,
    save_ai_settings,
    usage_summary,
)
from .. import garmin, garmin_personal, integrations, openwearables, oura, paperless
from .. import openwearables_webhooks as ow_hooks
from ..telegram import TelegramService
from .telegram_routes import register_telegram_routes
from .changes import register_changes_routes, verdict_state
from .labsync_routes import register_routes as register_labsync_routes
from .testplan_routes import register_routes as register_testplan_routes
from .allergy_routes import register_routes as register_allergy_routes
from .genetics_routes import register_routes as register_genetics_routes
from .chat_routes import register_routes as register_chat_routes
from .openwearables_routes import register_routes as register_openwearables_routes
from ..config import Settings, env, get_settings, resolve_source_path, load_integration_environment, configure_logging, _request_memo
from ..correlation import (
    ALIGNMENTS as CORRELATION_ALIGNMENTS,
    MIN_PAIRS_EXPLORER,
    WINDOW_DAYS as CORRELATION_WINDOW_DAYS,
    align_pairs,
    averaged_side,
    correlate,
    regression,
    rolling_mean_series,
    sample_evenly,
    suggest,
)
from ..db import connect, migrate, utc_now
from ..devices.catalog import DEVICE_CATEGORY_LABELS, HEALTHKIT_METRICS, SLEEP_METRICS, canonical_source_vendor
from ..devices.ecg import measure as measure_ecg, read_cached as read_ecg, strip_rows
from ..devices.structured import GarminAdapter, OuraAdapter
from ..devices import exclusions as device_exclusions
from ..devices.reconcile import (
    SLEEP_FAMILY, bridge_origin, human_source_label, preference_group, source_key, source_kind, valid_row,
)
from ..devices.timezone import timezone_choices, user_timezone, valid_timezone
from ..devices.units import PLAUSIBLE_RANGES
from .experience import build_overview, build_area_experience
from . import search as record_search
from .. import immunizations as immunization_records
from ..devices import queries as device_queries
from ..locales.concepts_en import CONCEPT_NAMES_EN
from ..locales.concepts_uk import CONCEPT_NAMES_UK
from ..locales.phrases import PHRASES
from ..devices.queries import (
    SLEEP_STAGE_KEYS,
    area_tracker,
    device_history_summary,
    device_metric_comparison,
    device_metric_catalog,
    device_metric_values,
    device_overview,
    is_partial_day,
)
from ..health import (
    AREA_BY_ID,
    CATEGORY_TO_AREA,
    HEALTH_AREAS,
    age_on,
    category_label,
    concept_display_name,
    display_reference,
    display_unit,
    applicable_band,
    applicable_reference_bounds,
    display_value,
    enum_label,
    finding_attention,
    _diagnosis_areas,
    localized_health_areas,
    metric_area_ids,
    present_finding,
    reference_applies,
    rule_context,
    status_label,
    sync_clinical_findings,
)
from ..i18n import (
    LOCALE_COOKIE,
    VISITOR_LOCALE,
    activate_locale,
    format_date_localized,
    format_number_localized,
    get_locale,
    js_strings,
    localize_mapping,
    normalize_locale,
    reset_locale,
    set_locale,
    t,
    t_plural,
    translate_phrase,
)
from ..immunizations import (
    DISEASES,
    VACCINE_CODES,
    calendar_diseases_without_a_dose,
    diseases_for,
    doses_for,
    visit_notes,
    find_gaps,
    fold as immunization_fold,
    product_for,
    refresh_card_review,
    schedule_sources,
)
from ..locales.messages import MESSAGES
from .health_export import AGGREGATION_KEYS, prepare_metric, render_pdf
from ..ingest.intake import (
    ARCHIVE_SUFFIXES,
    INTAKE_SUFFIXES,
    batch_progress,
    clear_finished,
    enqueue,
    reclaim_abandoned_jobs,
    record_duplicate,
    record_rejected,
    start_worker,
)
from ..ingest.pipeline import (
    ensure_concept,
    ensure_vendor,
    file_sha256,
    backfill_search_keys,
    ingest_file,
    interpretation,
    repair_observation_semantics,
    apply_reread_proposals,
    NOT_DUPLICATE_NOTE,
    PAGE_TEXT_NOTE,
    SAME_ORDER_NOTE,
    DuplicateRefused,
    _audit_document,
    _duplicate_pair,
    _record_person_relation,
    keep_both_documents,
    mark_document_duplicate,
    recount_review_tasks,
    repair_text_duplicates,
    unmark_document_duplicate,
    reread_proposals,
    review_reason_text,
    settle_reread_orphan,
    seed_reference_rules,
)
from ..derived import refresh_derived_observations
from ..ingest.classifier import repair_order_identifiers
from ..ingest.parsers import PARSER_VERSION, ParsedObservation, reference_bounds
from ..ingest.positions import backfill_positions, page_box, position_key
from ..ingest.text import collapse_space, normalized_key, parse_decimal, search_key
from ..panels import (
    ATTENTION_INTERPRETATIONS,
    BORDERLINE_INTERPRETATIONS,
    DISPLAY_SUPPRESSED,
    HOME_MONITORING_TYPES,
    MEASUREMENT_TWINS,
    PANEL_BY_ID,
    PANELS,
    SAME_DEVICE_KEYS,
    TWIN_OF_DEVICE,
    device_twins,
    panel_for_concept,
    panel_members,
    panel_retest_months,
    roll_up,
)
from ..reference import (
    RULE_CACHE,
    canonical_unit,
    clinical_context,
    convert_value,
    edge_safe_decimals,
    evaluate,
    interpretation_label,
    localised_guidance,
    range_text,
    rule_applies_to_context,
    rule_label,
    rule_note,
    rule_requirement,
    sources_for,
    staleness,
)
from .ai_export import (
    DEFAULT_SECTIONS,
    SECTIONS,
    SECTION_KEYS,
    build_prompt,
    build_subject_prompt,
)
from ..security import (
    DOCTOR_PIN_ACCESS,
    DOCTOR_PIN_CLIENT_LIMIT,
    DOCTOR_PIN_GLOBAL_KEY,
    DOCTOR_PIN_GLOBAL_LIMIT,
    DOCTOR_PIN_REDEEM_WINDOW,
    LOGIN_ATTEMPT_WINDOW,
    MINIMUM_PASSWORD_LENGTH,
    ROLES,
    SETUP_CODE_GLOBAL_KEY,
    SETUP_CODE_GLOBAL_LIMIT,
    TOKEN_KINDS,
    AlreadySetUp,
    access_token_user,
    authenticate,
    clear_attempts,
    create_access_token,
    create_doctor_pin,
    create_session,
    create_user,
    csrf_matches,
    ensure_seeded_token,
    has_users,
    list_access_tokens,
    list_doctor_pins,
    new_setup_code,
    open_registration,
    setup_code_matches,
    list_sessions,
    record_attempt,
    redeem_doctor_pin,
    revoke_access_token,
    revoke_session,
    revoke_other_sessions,
    revoke_session_by_handle,
    session_user,
    set_open_registration,
    set_password,
    throttled,
    touch_access_token,
    update_access_token,
)


#: Paths, media types, stored names and message keys used in more than one place.
_DOCUMENTS_URL = "/documents"
_LOGIN_URL = "/login"
_SETUP_URL = "/setup"
_setup_log = logging.getLogger("anamna.setup")
_LOGIN_THROTTLED_URL = "/login?error=throttled"
_DOCTOR_URL = "/doctor"
_PROFILE_URL = "/profile"
_VACCINATIONS_URL = "/vaccinations"
_UPLOAD_URL = "/upload"
_DEVICES_URL = "/devices"
_STATIC_PREFIX = "/static/"
_INTEGRATION_SYNC_SAVED_URL = "/profile?saved=integration_sync"
_PAPERLESS_URL_ERROR_URL = "/admin/paperless?error=paperless.error_url"
_RESCAN_QUEUED_QUERY = "?rescan=queued"
_PDF_MEDIA_TYPE = "application/pdf"
_JSON_MEDIA_TYPE = "application/json"
_DEVICE_METRIC_PREFIX = "device:"
_UNKNOWN_PROVIDER = "Unknown provider"
_UNKNOWN_VENDOR = "Unknown vendor"
_OWNED_DOCUMENT_SQL = "SELECT 1 FROM documents WHERE id=? AND owner_user_id=?"
_EM_DASH_KEY = "em.dash"
_VERIFIED_STATE = "verified"
_DATE_UNKNOWN_KEY = "date.unknown"
_UNKNOWN_PROVIDER_KEY = "unknown.provider"
_DOCTOR_MINUTES_KEY = "doctor.minutes"
_SOURCE_UNAVAILABLE_KEY = "source.unavailable"
_DOC_DATE_INVALID_KEY = "doc.date_invalid"
_UPLOAD_ERROR_CSRF = "upload.error_csrf"
_UPLOAD_ERROR_NO_SOURCE = "upload.error_no_source"
_ADMIN_ERROR_INVALID = "admin.error_invalid"
_ADMIN_ERROR_PASSWORD = "admin.error_password"
_ADMIN_ERROR_UNKNOWN = "admin.error_unknown"
_REGISTER_ERROR_INVALID = "register.error_invalid"
_REGISTER_ERROR_PASSWORD = "register.error_password"
_DEVICE_MEASUREMENT_KEY = "device.measurement"
_PROFILE_ERROR_DOB = "profile.error_dob"
_PROFILE_ERROR_CHOICE = "profile.error_choice"
_TOKEN_ERROR_EXPIRY = "token.error_expiry"
_INTAKE_FAILED_UNREADABLE = "intake.failed_unreadable"
_INTAKE_FAILED_UNSUPPORTED = "intake.failed_unsupported"

THEME_COOKIE = "anamna_theme"
VIEW_COOKIE = "anamna_record"
#: Pages that show results, and so carry the "Ask an AI" button.
AI_EXPORT_PAGES = frozenset(
    {"dashboard", "panels", "metrics", "devices", "documents"}
)
REVIEW_STATES = ("open", "resolved", "needs_correction")
#: Refusals of /documents/{id}/duplicate, each `dup.error_<code>` in the catalogue.
DUPLICATE_ERRORS = ("already", "self", "patient", "busy", "ruled", "missing", "not_duplicate", "same_bytes")
BLOOD_TYPES = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")

#: The values the patients CHECK constraint accepts; "" from the form is NULL.
#: Editable here because sexed reference rules apply only on exact match — an
#: account that cannot state its sex silently loses every sexed judgement.
SEX_AT_BIRTH = ("female", "male", "intersex", "unknown")

#: Body measurements the profile keeps, each with the unit it is stored in, the
#: device metric that supersedes it, and the range the column will accept.  A
#: measurement a wearable or a smart scale already records is shown from that
#: evidence and the manual copy is not stored, exactly as a lab-determined
#: blood group displaces a typed one — two numbers for one quantity drift, and
#: the one a clinician reads should be the one something measured.
BODY_MEASUREMENTS = (
    ("height_cm", "body_height", "cm", 30.0, 280.0),
    ("weight_kg", "body_weight", "kg", 1.0, 700.0),
    ("waist_cm", "waist_circumference", "cm", 20.0, 300.0),
    ("chest_cm", None, "cm", 20.0, 300.0),
    ("hip_cm", None, "cm", 20.0, 300.0),
)

#: Lifestyle context, as published vocabularies rather than free text, so each
#: value can be translated, compared and read by a rule.  Sources are cited to
#: the reader in `profile.<field>_hint`.
PROFILE_CHOICES = {
    "activity_level": ("sedentary", "light", "moderate", "active", "athlete"),
    # LDL / non-HDL / ApoB goals are defined per category (reference.clinical_context).
    "cv_risk_category": ("low", "moderate", "high", "very_high"),
    "skin_type": ("I", "II", "III", "IV", "V", "VI"),
    "smoking_status": ("never", "former", "current"),
    "alcohol_use": ("none", "occasional", "moderate", "frequent"),
}

#: Everything a guest link may reach.  Enforced as an allowlist of prefixes
#: rather than a list of pages to forbid: a route added next month is refused
#: by default, which is the direction an access check should fail in.
GUEST_ALLOWED_PREFIXES = (
    "/insights", "/changes", "/panels", "/metrics", _DEVICES_URL, _DOCUMENTS_URL,
    "/privacy", "/terms",
    "/api/panels", "/api/metrics", "/api/documents", "/api/ai-export", "/static",
    # The correlation explorer is rendered on the metric pages a guest already
    # reads; without its data endpoint every control on it answers 403.
    "/api/correlation",
    # A device page's per-source chart series loads from here on demand.
    "/api/devices/metrics",
    # A doctor holding a link may well have their own account here.  Without
    # these the sign-in page answers 403 to the one visitor most likely to want
    # it, which is a dead end reached by clicking nothing unusual.
    _LOGIN_URL, "/register",
    # And a doctor may hold invitations from two patients.  Refusing the second
    # link because the first one is still open would make the fix "sign out,
    # then click the link again", which nobody is going to guess.
    "/t/",
    # A doctor plans the patient's next tests and saves the selection for them
    # (POST /plan-tests/suggest below); ordering stays the patient's.  The
    # planner links the allergy and DNA pages, and the menu vaccinations.
    "/plan-tests", "/allergy", "/genetics", _VACCINATIONS_URL,
)
#: The POSTs a guest may still make.  None of them touch the record: they end
#: the visit, change how it is displayed, or sign the visitor in as themselves,
#: and refusing them would leave a guest unable to read the page in their own
#: language or to stop being a guest.
GUEST_ALLOWED_POSTS = ("/logout", "/theme", "/locale", _LOGIN_URL, "/register", _DOCTOR_URL,
                       # The one write a guest makes: a doctor's test selection,
                       # kept apart for the patient to accept, never the record.
                       "/plan-tests/suggest")
#: Pages a guest may open by exact path.  /doctor is here rather than among the
#: prefixes so that a later "/doctor-…" route is not let in by accident; a
#: doctor already reading one patient's record enters the next patient's code.
GUEST_ALLOWED_PAGES = ("/", _DOCTOR_URL)


def _measured_body(connection, owner_user_id: str) -> dict[str, dict[str, object]]:
    """The newest device-measured value for each linked body measurement.

    Routed through ``device_metric_values`` rather than a fresh query so a day
    with readings from a phone and a scale resolves to the same source the
    device pages already prefer — otherwise the profile and the metric page
    would quote different weights for the same morning.
    """
    measured: dict[str, dict[str, object]] = {}
    for field, metric_key, _unit, _low, _high in BODY_MEASUREMENTS:
        if metric_key is None:
            continue
        # Only a value inside the column's own CHECK range may stand in for a
        # typed measurement: a 0.99 cm "waist" from a mislabelled bridge row
        # once locked the field (UX-32).  Selection already drops those; this
        # keeps the profile safe on its own.
        rows = [row for row in device_metric_values(connection, owner_user_id, metric_key)
                if _low < float(row["value"]) < _high]
        if not rows:
            continue
        latest = rows[0]
        unit = display_unit(latest["unit"]) if latest["unit"] else None
        measured[field] = {
            "value": latest["value"],
            "text": format_measurement(latest["value"], unit),
            "day": latest["day"],
            "date_text": format_date(str(latest["day"])),
            "metric_key": metric_key,
            "source": human_source_label(str(latest["source_vendor"]), str(latest["source_name"])),
        }
    return measured

#: Lab wording -> canonical ABO group.  Ukrainian reports write the group with
#: Cyrillic letters and roman numerals ("А(ІІ)", "0(I)"), so the text is
#: latinised first and the longest numeral is matched before its prefixes.
_CYRILLIC_TO_LATIN = str.maketrans({"А": "A", "В": "B", "О": "O", "І": "I"})
_ABO_PATTERNS = (
    ("IV", "AB"), ("AB", "AB"), ("III", "B"), ("II", "A"), ("I", "O"),
    ("B", "B"), ("A", "A"), ("O", "O"), ("0", "O"),
)


def abo_from_text(value: str | None) -> str | None:
    if not value:
        return None
    text = value.upper().translate(_CYRILLIC_TO_LATIN)
    for pattern, group in _ABO_PATTERNS:
        if pattern in text:
            return group
    return None


def rh_from_text(value: str | None) -> str | None:
    if not value:
        return None
    text = value.casefold()
    if "поз" in text or "positive" in text or "+" in text:
        return "+"
    if "нег" in text or "negative" in text or "-" in text or "−" in text:
        return "-"
    return None


def _lab_blood_type(connection, owner_user_id: str) -> dict[str, str] | None:
    """The latest lab-determined blood group, so the profile mirrors evidence
    instead of keeping a second, unconnected manual copy."""

    def latest(concept_id: str):
        return connection.execute(
            """SELECT value_text, observed_at, document_id FROM observations
               WHERE owner_user_id=? AND concept_id=? AND value_text IS NOT NULL
                 AND verification_status <> 'rejected'
               ORDER BY observed_at DESC LIMIT 1""",
            (owner_user_id, concept_id),
        ).fetchone()

    group = latest("blood-group")
    abo = abo_from_text(group["value_text"]) if group else None
    if abo is None:
        return None
    rh_row = latest("rhesus-factor")
    rh = rh_from_text(rh_row["value_text"]) if rh_row else None
    return {
        "value": abo + (rh or ""),
        "observed_at": group["observed_at"],
        "date_text": format_date(group["observed_at"]),
        "document_id": group["document_id"],
    }

WEB_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=WEB_DIR / "templates")

#: Rows rendered per page.  Every count shown beside a paged list is the real
#: total ("40 of 295"), never the size of the slice.
PAGE_SIZE = 40
DOCUMENT_PAGE_SIZE = 20
#: Two weeks of per-source rows per page, the window the trackers show; with
#: four or five sources a day, more made the history table the page's bulk.
DEVICE_ROW_PAGE_SIZE = 14

#: Days of the selected series a device page carries inline: the year its
#: chart opens on.  "All" fetches the rest; ten years of steps inline was
#: 2.7 MB of HTML for a chart that shows thirty days first (PERF-03).
DEVICE_INLINE_DAYS = 366

# Source-defined measurements that need a semantic caveat even before a
# curator adds a clinical guidance row. These notes describe the provider
# contract only; they deliberately do not invent reference intervals.
PROVIDER_SCORE_KEYS = frozenset({
    "recovery_score", "stress_score", "resilience_score", "body_battery_score",
    "strain_score", "health_recovery_score",
})
#: A daily-aggregate series longer than this is bucketed before it reaches the
#: browser: 3,399 individual circles are a solid blob, not a chart.
CHART_MAX_POINTS = 240
#: The type-ahead returns a slice; the response also carries the true totals so
#: the interface can say how many results it is not showing.
SEARCH_PAGE_SIZE = 12
#: Uploads are written to disk before parsing, so the body is capped first.
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
#: An archive is held to a different limit because a vendor export legitimately
#: is one: a full Apple Health export is a couple of gigabytes and refusing it
#: would mean the whole device-import feature is unreachable from a browser.
#: The bytes are streamed to disk a megabyte at a time either way.
MAX_ARCHIVE_UPLOAD_BYTES = 6 * 1024**3
#: Cloudflare fronts the public host and answers any single request body over
#: about 100 MB with its own 413 before this process sees it.  The upload page
#: keeps every request under that ceiling: a submission whose files together
#: exceed the threshold is sent as slices of this size to /upload/chunk, and
#: the assembled file joins the ordinary intake path.
UPLOAD_CHUNK_BYTES = 32 * 1024 * 1024
UPLOAD_CHUNK_THRESHOLD = 64 * 1024 * 1024
#: `upload_error` arrives in a URL, so only a key the handler itself can emit is
#: ever resolved back onto the page.
UPLOAD_ERRORS = frozenset(
    {
        "upload.error_missing",
        "upload.error_name",
        "upload.error_type",
        "upload.error_too_large",
        "upload.error_failed",
        _UPLOAD_ERROR_CSRF,
        _UPLOAD_ERROR_NO_SOURCE,
        "upload.error_busy",
    }
)
#: How many past uploads the upload page lists.
UPLOAD_RECENT = 6
#: How many queue rows the processing area carries at once.
UPLOAD_QUEUE_LIMIT = 60
#: Device exports the upload form offers by name.  Auto-detection reads an
#: archive's own layout, but a reader who knows what they exported should not
#: have to hope: naming the vendor skips detection entirely.
DEVICE_ADAPTERS = ("apple_health", "garmin", "oura", "kardia")


def upload_limit_for(name: str) -> int:
    return (
        MAX_ARCHIVE_UPLOAD_BYTES
        if Path(name).suffix.casefold() in ARCHIVE_SUFFIXES
        else MAX_UPLOAD_BYTES
    )


# --- request-scoped memoisation --------------------------------------------
#
# The catalog is a full window-function scan over every observation plus a
# 58k-row device aggregate scan plus one evaluate() per concept.  Several
# sections of one page need it; recomputing it per section is where the
# dashboard's render time went.  The cache dict is installed by the locale
# middleware, so it lives exactly as long as one request.
_request_cache: ContextVar[dict[str, object] | None] = ContextVar(
    "anamna_request_cache", default=None
)


def _cached[T](key: tuple[object, ...], build: Callable[[], T]) -> T:
    cache = _request_cache.get()
    if cache is None:
        return build()
    if key not in cache:
        cache[key] = build()
    return cache[key]


#: Process-level memo for the expensive reads, keyed by a cheap fingerprint of
#: the data they summarise (one index probe each against seconds to rebuild).
#: Lab and device halves are fingerprinted and cached apart, so an Oura webhook
#: rebuilds device cards and leaves the lab catalog warm, and the reverse
#: (PERF-02).  Least-recently-used per key, invalidated per owner: one person's
#: upload never evicts another person's pages.  Every mutating route calls
#: `invalidate_catalog`; the fingerprint catches a change made by another
#: process such as a CLI ingest or a sync worker.
_MEMO: "OrderedDict[tuple[str, str, str], tuple[tuple, object]]" = OrderedDict()
_MEMO_SIZE = 32
_MEMO_LOCK = threading.Lock()

#: Which half of the record each memoised read summarises.
_MEMO_SCOPE = {"lab_catalog": "lab", "device_catalog": "device", "devices": "device"}


def invalidate_catalog(owner_user_id: str | None = None) -> None:
    """Forget memoised summaries: one owner's, or everyone's when unnamed.

    Checking one value changes one person's record; emptying every account's
    memo for it made the next dashboard anyone opened a two-second rebuild.
    """
    with _MEMO_LOCK:
        if owner_user_id is None:
            _MEMO.clear()
            _CORRELATION_MEMO.clear()
            return
        for memo in (_MEMO, _CORRELATION_MEMO):
            for key in [key for key in memo if key[0] == owner_user_id]:
                del memo[key]


_FINGERPRINT_SQL = {
    "lab": """SELECT (SELECT COUNT(*) FROM observations WHERE owner_user_id=?),
                     (SELECT MAX(created_at) FROM observations WHERE owner_user_id=?)""",
    # created_at advances on every device write (upserts restamp it), so a
    # re-cut that keeps the row count and the newest day still registers.
    "device": """SELECT (SELECT COUNT(*) FROM device_metric_days WHERE owner_user_id=?),
                        (SELECT MAX(created_at) FROM device_metric_days WHERE owner_user_id=?),
                        (SELECT COUNT(*) || ' ' || MAX(imported_at) FROM device_imports WHERE owner_user_id=?),
                        (SELECT MAX(updated_at) FROM device_source_preferences WHERE owner_user_id=?),
                        (SELECT COUNT(*) || ' ' || coalesce(MAX(created_at), '') || ' ' || coalesce(MAX(revoked_at), '')
                                || ' ' || coalesce(MAX(applied_at), '') || ' ' || SUM(applied_at IS NULL)
                           FROM device_exclusions WHERE owner_user_id=?)""",
}


def _fingerprint(connection, owner_user_id: str, scope: str = "all") -> tuple:
    """`all` (the default, for reads that mix both halves) is both prints."""
    if scope == "all":
        return (_fingerprint(connection, owner_user_id, "lab"), _fingerprint(connection, owner_user_id, "device"))
    sql = _FINGERPRINT_SQL[scope]
    return _cached(
        ("fingerprint", scope, owner_user_id),
        lambda: tuple(connection.execute(sql, (owner_user_id,) * sql.count("?")).fetchone()),
    )


def _memoised[T](connection, owner_user_id: str, name: str, build: Callable[[], T]) -> T:
    def resolve() -> T:
        # Cards carry localised names and labels, so the locale is part of the key.
        key = (owner_user_id, get_locale(), name)
        fingerprint = _fingerprint(connection, owner_user_id, _MEMO_SCOPE.get(name, "all"))
        with _MEMO_LOCK:
            entry = _MEMO.get(key)
            if entry is not None and entry[0] == fingerprint:
                _MEMO.move_to_end(key)
                return entry[1]
        value = build()
        with _MEMO_LOCK:
            _MEMO[key] = (fingerprint, value)
            _MEMO.move_to_end(key)
            while len(_MEMO) > _MEMO_SIZE:
                _MEMO.popitem(last=False)
        return value

    return _cached((name, owner_user_id), resolve)


# --- formatting -------------------------------------------------------------
#
# Every number a template prints arrives already formatted.  Jinja does no
# arithmetic, no rounding and no unit logic: `0.853957 km` and `95.9524 %` are
# what happens when the decision is left to the last moment.


def _canonical_units(mapping: dict[str, int]) -> dict[str, int]:
    return {canonical_unit(unit): decimals for unit, decimals in mapping.items()}


#: Display precision that suits the unit rather than the float.  Steps are
#: whole numbers; a distance in km is worth two decimals; a percentage is worth
#: one.  Anything not listed falls back to magnitude-based significant figures.
UNIT_DECIMALS = _canonical_units(
    {
        "steps": 0, "flights": 0, "kcal": 0, "min": 0, "count": 0, "records": 0,
        "bpm": 0, "ms": 0, "breaths/min": 0, "mmHg": 0, "m": 0, "mL": 0,
        "Hz": 0, "score": 0, "years": 0,
        "%": 1, "dBA": 1, "hours": 1, "kg": 1, "kg/m²": 1, "cm": 1, "s": 1,
        "mL/kg/min": 1, "°C": 1, "mm/h": 1, "MET-like effort": 1,
        "per hour": 1, "m/s": 1,
        "km": 2, "km/h": 2,
    }
)


def _decimals_for(value: float, unit: str | None) -> int:
    fixed = UNIT_DECIMALS.get(canonical_unit(unit))
    if fixed is not None:
        return fixed
    magnitude = abs(value)
    if magnitude >= 1000:
        return 0
    if magnitude >= 100:
        return 1
    if magnitude >= 1:
        return 2
    if magnitude >= 0.01:
        return 3
    return 4


def stored_decimals(value: float | None, limit: int = 4) -> int:
    """How many decimals the stored number actually carries.

    `UNIT_DECIMALS` sets the precision a unit is normally *worth* reading to,
    which is right for a device average and wrong for a number transcribed off
    a printed page: it pins `%` at one decimal, so an HbA1c the laboratory
    printed as 5.24 % was shown as 5,2 % -- a digit the report has and the
    screen does not, against thresholds (5.7 %, 6.5 %) written to two.  A value
    that came from a page is displayed at its own precision or better, never
    less.  Capped, because a corrected or converted value can carry float
    noise that is not precision.
    """
    if value is None:
        return 0
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return 0
    text = repr(number)
    if "e" in text or "E" in text:
        return limit
    return min(len(text.partition(".")[2].rstrip("0")), limit)


def format_quantity(value: float | None, unit: str | None = None, *, minimum_decimals: int = 0) -> str:
    """A reading, at the precision its unit deserves and its locale expects."""
    if value is None:
        return t(_EM_DASH_KEY)
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return t(_EM_DASH_KEY)
    return format_number_localized(number, max(_decimals_for(number, unit), minimum_decimals))


def _edge_safe(value: float | None, unit: str | None, verdict: dict | None) -> int:
    """Decimals that keep a displayed reading on its side of every band edge."""
    if value is None:
        return 0
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return 0
    return edge_safe_decimals(number, _decimals_for(number, unit), verdict, unit)


def format_measured(value: float | None, unit: str | None = None) -> str:
    """A quantity read off a source document, at the precision it was printed.

    Device aggregates keep going through `format_quantity`: an average step
    count to four decimals is noise, not fidelity.
    """
    return format_quantity(value, unit, minimum_decimals=stored_decimals(value))


def format_count(value: float | None) -> str:
    """A whole number in body copy: `5,591,981 source records`."""
    if value is None:
        return t(_EM_DASH_KEY)
    return format_number_localized(round(float(value)), 0)


def format_measurement(value: float | None, unit: str | None) -> str:
    text = format_quantity(value, unit)
    return f"{text} {unit}".strip() if unit else text


#: What a laboratory prints in front of a number when the assay could not
#: resolve the result any further.
COMPARATORS = "<>≤≥"


def _validated_date(value: str, error_key: str, *, required: bool = False) -> str | None:
    """Validate the whole submitted calendar date before it enters the ledger."""
    clean = value.strip()
    if not clean and not required:
        return None
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", clean):
            raise ValueError("Expected ISO calendar date")
        date.fromisoformat(clean)
    except ValueError:
        raise HTTPException(400, t(error_key)) from None
    return clean


def split_comparator(typed: str) -> tuple[str | None, str]:
    """A reviewer's typed reading, separated into its sign and its number.

    The correction form offers one field for the reading, because one field is
    how the report prints it.  Reading the sign back out here means someone who
    opened the form to fix a unit round-trips ``<0.01`` untouched, and someone
    who means to drop a misread sign deletes one character.
    """
    # `text and`, because "" is a substring of every string and an empty field
    # would otherwise be read as a comparator with nothing after it.
    text = typed.strip()
    if text and text[0] in COMPARATORS:
        return text[0], text[1:].strip()
    return None, text


def _printed_places(row: dict[str, object] | sqlite3.Row, keys) -> int:
    """Decimals the laboratory printed: the stored token wins, the evidence line is the fallback."""
    printed = str(row["value_printed"] or "") if "value_printed" in keys else ""
    if re.fullmatch(r"-?\d+(?:[.,]\d+)?", printed) and math.isclose(
        float(printed.replace(",", ".")), float(row["value_numeric"]), rel_tol=1e-9, abs_tol=1e-12
    ):
        return min(len(re.split(r"[.,]", printed + ".")[1]), 6)
    return printed_decimals(row["value_numeric"], row["evidence_text"] if "evidence_text" in keys else None)


def _reading_number(row: dict[str, object] | sqlite3.Row, keys, unit: str | None) -> str:
    """The numeric part of a reading, without its comparator."""
    if "is_device" in keys and row["is_device"]:
        # A device day is a mean of samples: its float carries arithmetic,
        # not precision (`67.3333 bpm`), so it reads to the unit's precision.
        return format_quantity(row["value_numeric"], unit)
    if "converted_from" in keys and row["converted_from"]:
        # Restated in another unit: the printed digits describe a different
        # number, and a converted float's own digits are arithmetic, not
        # precision ("2.071 mg/dL" from a printed 35 µmol/L).
        return format_quantity(row["value_numeric"], unit)
    # «1,80» is stored as 1.8; keep the zero the laboratory wrote.  The
    # stored printed token wins; older rows fall back to the evidence line.
    printed_places = _printed_places(row, keys)
    if printed_places:
        return format_number_localized(row["value_numeric"], printed_places, keep_trailing_zeros=True)
    return format_quantity(row["value_numeric"], unit, minimum_decimals=stored_decimals(row["value_numeric"]))


def format_reading(row: dict[str, object] | sqlite3.Row, unit: str | None) -> str:
    """One observation as the report printed it, comparator and all.

    ``<0.01`` is a different clinical fact from ``0.01``: the first says the
    assay could not see the analyte down to its own floor, the second says it
    measured it there.  Printing the number alone shows a reader a measurement
    that was never made, and puts it beside a reference interval as though it
    had been -- which is exactly the certification the review page exists to
    ask for.  Every page that shows a value goes through here so no new one has
    to remember.
    """
    if row["value_numeric"] is None:
        return latinize_code(display_value(row["value_text"]))
    keys = row.keys()
    number = _reading_number(row, keys, unit)
    comparator = row["comparator"] if "comparator" in keys else None
    return f"{comparator}{number}" if comparator else number


_PRINTED_NUMBER_RE = re.compile(r"(?<![\d.,])\d+(?:[.,]\d+)?(?!\d)")


def printed_decimals(value: float | None, evidence: str | None) -> int:
    """How many decimals the report printed this value with.

    A float cannot remember trailing zeros: «1,80» is stored as 1.8 and was
    shown as 1,8 -- a digit of the laboratory's precision lost on the way to
    the screen.  The evidence line is the printed row, so the first number on
    it equal to the value says how it was written.  No match, no claim.
    """
    if value is None or not evidence:
        return 0
    for token in _PRINTED_NUMBER_RE.findall(evidence):
        if abs(float(token.replace(",", ".")) - float(value)) < 1e-9:
            return min(len(re.split(r"[.,]", token, maxsplit=1)[1]) if re.search(r"[.,]", token) else 0, 4)
    return 0


def _byte_size_text(value: object) -> str:
    """A file size a person reads, localised.

    Uploads run from a 40 kB photo to a 2 GB vendor export, so the unit is
    chosen per file rather than fixing one and printing 0.00004 GB.
    """
    try:
        size = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    for unit, step, decimals in (("gigabytes", 1024**3, 1), ("megabytes", 1024**2, 1), ("kilobytes", 1024, 0)):
        if size >= step:
            return t(f"upload.{unit}", count=format_number_localized(size / step, decimals))
    return t("upload.bytes", count=format_number_localized(size, 0))


def format_date(value: str | None, fallback: str | None = None) -> str:
    return format_date_localized(value, _DATE_UNKNOWN_KEY)


def format_number(value: float | None) -> str:
    return format_number_localized(value)


def format_compact_number(value: float | None) -> str:
    return format_number_localized(value)


#: Cyrillic letters whose glyph is identical to a Latin one.  Blood group
#: "А(ІІ)" is Latin "A(II)" written in Cyrillic; folding it is a spelling fix,
#: not a translation, and only ever applied when the whole token folds.
#: Unrelated to `search_key`, which transliterates by sound instead.
_HOMOGLYPHS = str.maketrans(
    {
        "А": "A", "В": "B", "Е": "E", "І": "I", "Ї": "I", "К": "K", "М": "M",
        "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
        "а": "a", "е": "e", "і": "i", "о": "o", "р": "p", "с": "c", "у": "y",
        "х": "x",
    }
)
_CYRILLIC_RE = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
_CODE_LIKE_RE = re.compile(r"^[A-Za-z0-9()+\-/., ]+$")


def latinize_code(text: str) -> str:
    """Fold a Cyrillic-spelled code such as `А(ІІ)` to `A(II)` in English mode."""
    if get_locale() == "uk" or not text or not _CYRILLIC_RE.search(text):
        return text
    folded = text.translate(_HOMOGLYPHS)
    if _CYRILLIC_RE.search(folded) or not _CODE_LIKE_RE.fullmatch(folded):
        return text
    if not any(character in folded for character in "()+-/0123456789"):
        return text
    return folded


_DECIMAL_POINT_RE = re.compile(r"(?<=\d)\.(?=\d)")
_LEADING_BOUND_RE = re.compile(r"^\s*((?:[<>≤≥]\s*)?-?\d+(?:[.,]\d+)?)")
#: The second number of a printed range, read where `_LEADING_BOUND_RE` stopped.
_RANGE_TAIL_RE = re.compile(r"\s*[-–—]\s*-?\d+(?:[.,]\d+)?")


def reference_display(
    reference: str | None, age: int | None, sex: str | None, value: float | None = None
) -> str:
    """The laboratory's printed interval, in the reader's language.

    Some printed intervals carry a source-language annotation - `<3.0 - для
    груп низького ризику`.  In English mode the numbers stay and the untranslated
    commentary goes, rather than the whole thing arriving as Cyrillic.
    """
    text = display_reference(reference, age, sex, value)
    if get_locale() == "uk":
        # The value beside it reads «2,5»; the interval must not read «0.5–5.0».
        return _DECIMAL_POINT_RE.sub(",", text)
    if not _CYRILLIC_RE.search(text):
        return text
    match = _LEADING_BOUND_RE.match(text)
    if not match:
        return t("ref.not_supplied")
    bound = match.group(1)
    if tail := _RANGE_TAIL_RE.match(text, match.end()):
        bound += tail.group(0)
    return display_reference(bound.replace(",", "."), age, sex)


def _vendor_bounds(row, age: int | None, sex: str | None):
    """The printed interval, but only when it describes this patient.

    The parser stores no bounds for a demographically-qualified range, which
    discards the adult interval along with the paediatric one.  Recovering it
    is what lets the engine notice that the laboratory and the curated source
    disagree - the folate the lab called low and a curated interval calls
    normal must never render as a calm green "within range".
    """
    low, high = row["vendor_reference_low"], row["vendor_reference_high"]
    reading = row["vendor_interpretation"]
    if low is None and high is None:
        low, high = applicable_reference_bounds(row["vendor_reference_text"], age, sex, row["value_numeric"])
        bare = re.fullmatch(r"\s*(-?\d+(?:[.,]\d+)?)\s*", str(row["vendor_reference_text"] or ""))
        if low is None and high is None and bare and row["value_numeric"] is not None:
            # A reference printed as a bare number ("0.0" beside atypical
            # lymphocytes) is the value the laboratory expects -- an upper
            # limit of that number -- not "no reference" / "No comparison".
            high = float(bare.group(1).replace(",", "."))
    elif not reference_applies(row["vendor_reference_text"], age, sex) and (
        (low, high) != applicable_reference_bounds(row["vendor_reference_text"], age, sex, row["value_numeric"])
    ):
        # A block printed for several populations fails as a whole («Діти …
        # Чоловіки: 4.0 - 5.0 Жінки …»); the parser now stores this patient's
        # band from it.  Those bounds stand when they are exactly the band this
        # patient's age and sex pick out -- otherwise an RBC of 5.06 against the
        # laboratory's male 4.0-5.0 would lose its "above range" and read green.
        return None, None, None
    if low is None and high is None:
        return None, None, reading
    return low, high, reading


def _render_pdf_page(cache_dir: Path, source: Path, cache_key: str, page_number: int) -> Path:
    """Render one PDF page for the first-class web viewer and cache it locally.

    The cache lives beside the database, so a container that persists /data
    keeps rendered pages across restarts instead of re-rendering every PDF.
    """
    import pypdfium2 as pdfium

    target = cache_dir / cache_key[:24] / f"page-{page_number}.png"
    if target.is_file() and target.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(source)
    try:
        if page_number < 1 or page_number > len(document):
            raise IndexError(page_number)
        page = document[page_number - 1]
        try:
            image = page.render(scale=2.0).to_pil().convert("RGB")
            temporary = target.with_name(f".{target.stem}-{uuid.uuid4().hex}.png")
            image.save(temporary, format="PNG", optimize=True)
            temporary.replace(target)
        finally:
            page.close()
    finally:
        document.close()
    return target


def _render_image_page(cache_dir: Path, source: Path, cache_key: str, page_number: int) -> Path:
    """Serve each image frame upright in a format every supported browser reads."""
    from PIL import Image, ImageOps

    target = cache_dir / cache_key[:24] / f"image-page-{page_number}.png"
    if target.is_file() and target.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}-{uuid.uuid4().hex}.png")
    try:
        with Image.open(source) as original:
            original.seek(page_number - 1)
            with ImageOps.exif_transpose(original) as upright:
                upright.convert("RGB").save(temporary, format="PNG")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


templates.env.filters["datefmt"] = format_date
templates.env.filters["numfmt"] = format_number
templates.env.filters["compactnum"] = format_compact_number
templates.env.filters["qtyfmt"] = format_quantity
templates.env.filters["countfmt"] = format_count
templates.env.filters["unitfmt"] = display_unit
templates.env.filters["valuefmt"] = display_value
templates.env.filters["reffmt"] = display_reference
templates.env.filters["statusfmt"] = status_label
templates.env.filters["categoryfmt"] = category_label
templates.env.filters["conceptfmt"] = concept_display_name
templates.env.filters["enumfmt"] = enum_label
templates.env.filters["phrase"] = translate_phrase
def asset(path: str) -> str:
    """`/static/<path>` with the file's modification time attached.

    The stylesheet is cached by URL — Cloudflare holds `/static/app.css` for
    four hours in front of this server, and the deploy does not purge it. An
    unversioned URL therefore serves the *previous* release's CSS to new markup
    for hours after shipping, which looks like a broken control rather than a
    stale file: the AI hand-off button rendered as an unstyled browser button
    because `.ai-fab` existed only in the stylesheet nobody was being served.
    The stat runs per render, so editing a file in development busts it too.
    """
    try:
        stamp = int((WEB_DIR / "static" / path).stat().st_mtime)
    except OSError:
        return f"/static/{path}"
    return f"/static/{path}?v={stamp}"


def _static_cache_control(request: Request) -> str:
    """Cache-Control for a `/static/*` response.

    A URL whose `?v=` is the file's current mtime — exactly what `asset()`
    emits — names one immutable byte sequence: the next edit changes the URL,
    so browsers and Cloudflare may keep it for a year without revalidating.
    Anything else (no version, a stale one, a missing file) gets five minutes,
    so an old or hand-typed URL never pins outdated bytes.
    """
    short = "public, max-age=300, no-transform"
    static_root = (WEB_DIR / "static").resolve()
    target = (static_root / request.url.path.removeprefix(_STATIC_PREFIX)).resolve()
    if not target.is_relative_to(static_root):
        return short
    try:
        stamp = str(int(target.stat().st_mtime))
    except OSError:
        return short
    if request.query_params.get("v") == stamp:
        return "public, max-age=31536000, immutable, no-transform"
    return short


templates.env.globals["asset"] = asset
templates.env.globals["t"] = t
templates.env.globals["_"] = t
templates.env.globals["t_plural"] = t_plural
templates.env.globals["first_on_page"] = lambda key: _first_on_page(key)


DOCUMENT_TYPE_TITLES = {
    "laboratory": "Laboratory report",
    "radiology_mri": "MRI report",
    "radiology_xray": "X-ray report",
    "ultrasound": "Ultrasound report",
    "pathology": "Pathology report",
    "diagnostic_image": "Diagnostic imaging record",
    "compound_bundle": "Medical document bundle",
    "consultation": "Consultation report",
    "allergy": "Allergy report",
    "microbiology": "Microbiology report",
    # These four are emitted by the classifier and were missing here, which the
    # `<select>` on the document page turns into a wrong answer rather than a
    # missing one: with no option matching the document's own kind, the browser
    # selects the first, so an ECG recording read "Allergy report".  Saving that
    # form -- the obvious thing to do when the field looks wrong -- reclassified
    # the ECG as an allergy panel and re-read it, and the ECG parser never runs
    # on an allergy report.  This dict is also the allowlist the POST validates
    # against, so there was no way to set the right answer back either.
    "electrocardiogram": "ECG recording",
    "blood_pressure": "Blood pressure record",
    "administrative": "Administrative document",
    "clinical_report": "Clinical report",
    "immunization_record": "Vaccination card",
    # A screening scale someone filled in (ASRS, NICHQ Vanderbilt).
    "questionnaire": "Questionnaire",
}

#: A stored title that is really the ingest filename.  Showing it as the
#: document's name and again as its filename says the same thing twice and
#: says nothing either time.
_FILE_SUFFIX_RE = re.compile(r"\.(?:pdf|png|jpe?g|tiff?)$", re.I)


def _looks_like_filename(title: str) -> bool:
    """A double underscore (the ingest prefix "2025-01-02__" has one too) or a file suffix."""
    return "__" in title or bool(_FILE_SUFFIX_RE.search(title))


def display_document_title(
    title: str | None,
    clinical_type: str | None = None,
    vendor: str | None = None,
    *,
    subjects: list[str] | tuple[str, ...] = (),
    date: str | None = None,
    filename: str | None = None,
) -> str:
    """The document's name in the reader's language.

    A printed title is kept when the reader can read it.  Otherwise -- a
    filename, nothing at all, a Ukrainian heading on an English page -- the
    name is built from what the document is about: `<kind> — <tests> —
    <date>`.  "Laboratory report · Expert Hospital" was 27 identical rows in
    the English list, and the vendor is printed beside the title anyway.
    ``vendor`` is accepted for old callers and deliberately not used.
    """
    raw_title = title or ""
    translated = translate_phrase(raw_title)
    # "vact" and "photo_2026-08-07_20-31-04" are what the file was called on
    # disk, not what it is.
    is_filename = _looks_like_filename(raw_title) or (
        bool(filename) and raw_title.casefold() == PurePath(str(filename)).stem.casefold()
    )
    if raw_title and not is_filename:
        readable = (
            translated != raw_title or bool(_CYRILLIC_RE.search(raw_title))
            if get_locale() == "uk"
            else not _CYRILLIC_RE.search(raw_title)
        )
        if readable:
            return translated
    type_label = translate_phrase(DOCUMENT_TYPE_TITLES.get(clinical_type or "", "Medical report"))
    parts = [type_label]
    named = list(subjects)
    if named:
        shown = named[:3]
        more = len(named) - len(shown)
        parts.append(", ".join(shown) + (f" {t_plural('doc.title_more', more)}" if more else ""))
    if date:
        parts.append(format_date(date))
    return " - ".join(parts)


templates.env.globals["document_title"] = display_document_title


#: What a document's results are, for its generated title: every concept it
#: holds, in the order printed, with the category that places it in a panel.
_TITLE_TESTS_SQL = """(SELECT GROUP_CONCAT(tc.id || char(9) || COALESCE(tc.category, '') || char(9) || tc.canonical_name, char(10))
      FROM (SELECT c.id, c.category, c.canonical_name
              FROM observations tob JOIN concepts c ON c.id=tob.concept_id
             WHERE tob.document_id=d.id AND tob.verification_status <> 'rejected'
             GROUP BY c.id ORDER BY MIN(tob.page_number), MIN(tob.rowid)) tc) title_tests,
   (SELECT GROUP_CONCAT(DISTINCT tf.health_area) FROM clinical_findings tf
     WHERE tf.document_id=d.id AND tf.verification_status <> 'rejected') title_areas"""


def _title_subjects(tests: str | None, areas: str | None, clinical_type: str = "") -> list[str]:
    """What a document is about, named for its title.

    One or two results are named themselves; more are named by the panel they
    belong to, because "Hemoglobin, Hematocrit, Red blood cells + 24 more" is a
    worse name for a blood count than "Complete blood count".  A narrative
    report with no values is named by the body area its conclusion is about.
    """
    rows = [line.split("\t", 2) for line in (tests or "").split("\n") if line.count("\t") == 2]
    names: list[str] = []
    for concept_id, category, canonical in rows:
        panel = panel_for_concept(concept_id, category) if len(rows) > 2 else None
        if panel is not None and panel.id == clinical_type and panel.name.casefold() in (
            DOCUMENT_TYPE_TITLES.get(clinical_type, "").casefold()
        ):
            continue  # "Blood pressure record — Blood pressure" says one thing twice
        name = translate_phrase(panel.name) if panel else concept_display_name(canonical)
        if name not in names:
            names.append(name)
    if names or rows:
        return names
    return [
        translate_phrase(str(AREA_BY_ID[area]["short"]))
        for area in (areas or "").split(",")
        if area in AREA_BY_ID
    ][:2]


def _source_title_key(item: dict[str, object], raw_title: str, title: str, filename: str) -> str | None:
    # The stored title is shown under the generated one only when it is worth
    # reading and is honestly labelled: a heading printed on the report, or a
    # name the reader gave it themselves.  A filename is not "the original
    # report title", and neither is an English name this application wrote.
    if not (
        raw_title and raw_title != title and not _looks_like_filename(raw_title)
        and raw_title.casefold() != PurePath(filename).stem.casefold()
    ):
        return None
    if item.get("title_set_by") == "human":
        return "doc.title_yours"
    if _CYRILLIC_RE.search(raw_title):
        return "doc.original_title"
    return None


def _vendor_label(vendor) -> str:
    if vendor in {None, _UNKNOWN_PROVIDER, _UNKNOWN_VENDOR}:
        return t(_UNKNOWN_PROVIDER_KEY)
    return translate_phrase(str(vendor))


def _generated_title(item: dict[str, object], raw_title: str) -> str:
    clinical_type = str(item.get("clinical_type") or "")
    return display_document_title(
        raw_title,
        clinical_type,
        subjects=_title_subjects(  # type: ignore[arg-type]
            item.get("title_tests"), item.get("title_areas"), clinical_type
        ),
        date=str(item.get("report_date") or "") or None,
        filename=str(item.get("original_filename") or "") or None,
    )


def _document_row(row) -> dict[str, object]:
    """One document as the templates render it: one title, one subtitle."""
    item = dict(row)
    vendor = item.get("vendor")
    item["vendor_value"] = str(vendor or "")
    vendor_label = _vendor_label(vendor)
    raw_title = str(item.get("title") or "")
    title = _generated_title(item, raw_title)
    filename = str(item.get("original_filename") or "")
    item["vendor"] = vendor_label
    item["title_text"] = title
    item["type_label"] = translate_phrase(
        DOCUMENT_TYPE_TITLES.get(str(item.get("clinical_type") or ""), "Medical report")
    )
    item["source_title_key"] = _source_title_key(item, raw_title, title, filename)
    # Never print the filename twice: it is a subtitle only when it adds
    # something the title does not already say.
    item["filename_text"] = filename if filename and filename not in title else None
    item["date_text"] = format_date(
        str(item.get("report_date") or item.get("imported_at") or "") or None
    )
    item["url"] = f"/documents/{item['id']}"
    return item


def _displayable_metric(name: str) -> bool:
    """Reject extraction debris, not language.

    Hiding Cyrillic labels was a mapping bug wearing a filter's clothes; an
    unmapped source label is now shown under its own group instead.
    """
    folded = name.casefold().strip(" .,:;()")
    parsing_fragments = {
        "від", "крові", "нормальний або", "нирковий", "буропігментовані",
        "восковидні", "гіалінові", "епітеліальні", "зернисті",
    }
    return folded not in parsing_fragments and len(folded) >= 2


def _deduped_observation_rows(
    connection, owner_user_id: str, concept_id: str | None = None
) -> list[dict[str, object]]:
    concept_filter = "AND o.concept_id=?" if concept_id else ""
    params: list[object] = [owner_user_id]
    if concept_id:
        params.append(concept_id)
    rows = connection.execute(
        f"""WITH evidence AS (
                 SELECT o.*, c.canonical_name, c.category, c.preferred_unit,
                        d.title document_title, d.original_filename, d.duplicate_of_document_id,
                        d.order_identifier document_order, d.clinical_type document_clinical_type,
                        COALESCE(rv.canonical_name, dv.canonical_name, 'Unknown provider') vendor,
                        COALESCE(r.vendor_id, d.vendor_id) resolved_vendor_id,
                        r.title report_title,
                        ROW_NUMBER() OVER (
                            PARTITION BY o.concept_id,
                              COALESCE(o.observed_at, 'undated:' || o.document_id),
                              CASE WHEN o.value_numeric IS NOT NULL THEN printf('%.12g', o.value_numeric) ELSE o.value_text END,
                              COALESCE(r.vendor_id, d.vendor_id, '')
                            ORDER BY (d.duplicate_of_document_id IS NULL) DESC,
                                     o.confidence DESC, o.created_at
                        ) evidence_rank,
                        COUNT(*) OVER (
                            PARTITION BY o.concept_id,
                              COALESCE(o.observed_at, 'undated:' || o.document_id),
                              CASE WHEN o.value_numeric IS NOT NULL THEN printf('%.12g', o.value_numeric) ELSE o.value_text END,
                              COALESCE(r.vendor_id, d.vendor_id, '')
                        ) evidence_count
                 FROM observations o
                 JOIN concepts c ON c.id=o.concept_id
                 JOIN documents d ON d.id=o.document_id
                 LEFT JOIN reports r ON r.id=o.report_id
                 LEFT JOIN vendors rv ON rv.id=r.vendor_id
                 LEFT JOIN vendors dv ON dv.id=d.vendor_id
                 -- A row a reviewer set aside stays in the database for audit
                 -- and can be restored, but it is not a measurement: it must
                 -- not reach a chart, a panel or a verdict.
                 WHERE o.owner_user_id=? AND o.verification_status <> 'rejected' {concept_filter}
             )
             SELECT * FROM evidence WHERE evidence_rank=1
             ORDER BY COALESCE(observed_at, created_at) DESC, canonical_name""",
        params,
    ).fetchall()
    return [_in_preferred_unit(dict(row)) for row in rows]


#: Concepts with a device twin that is the same measurement (`MEASUREMENT_TWINS`).
SAME_TWIN_CONCEPTS = tuple(concept_id for concept_id in MEASUREMENT_TWINS if device_twins(concept_id, "same"))
#: Fields `_deduped_observation_rows` joins in beside the observation's own.
_JOINED_ROW_FIELDS = (
    "canonical_name", "category", "preferred_unit", "document_title", "original_filename",
    "duplicate_of_document_id", "document_order", "document_clinical_type", "vendor",
    "resolved_vendor_id", "report_title", "evidence_rank", "evidence_count",
)


def _device_maker(row) -> str:
    """Who made a device reading, the transport stripped: a Garmin cuff's day
    relayed through Apple Health is still Garmin's."""
    if source_kind(row) == "bridge":
        return bridge_origin(str(row["source_name"]))[1].casefold()
    return canonical_source_vendor(str(row["source_vendor"])).casefold()


def _device_reading_row(concept, row: dict[str, object], columns: list[str]) -> dict[str, object]:
    """One device day in the shape of a deduped observation row, so the card,
    the chart, the history table and the exports read it through the same
    code as a printed result.  It has no document; it links to its sources."""
    reading: dict[str, object] = dict.fromkeys((*columns, *_JOINED_ROW_FIELDS))
    reading.update(
        {
            "id": f"device:{row['metric_key']}:{row['day']}",
            "owner_user_id": row["owner_user_id"],
            "concept_id": concept["id"],
            "canonical_name": concept["canonical_name"],
            "category": concept["category"],
            "preferred_unit": concept["preferred_unit"],
            "observed_at": str(row["day"])[:10],
            "value_numeric": float(row["value"]),
            "unit_raw": row["unit"],
            "verification_status": "device_measurement",
            "confidence": 1.0,
            "created_at": row.get("updated_at") or row.get("created_at"),
            "vendor": human_source_label(str(row["source_vendor"]), str(row["source_name"])),
            "evidence_rank": 1,
            "evidence_count": 1,
            "is_device": True,
            "metric_key": row["metric_key"],
            "device_url": f"/devices/metrics/{row['metric_key']}",
        }
    )
    return reading


def _linked_observation_rows(
    connection, owner_user_id: str, concept_id: str | None = None
) -> list[dict[str, object]]:
    """`_deduped_observation_rows` with each same-measurement device twin folded in.

    A scale's weight and a clinic's weight are one quantity, so they are one
    series: every day the device side selects (the preferred source per day,
    exactly as /devices/metrics chooses it) joins the document readings.  A
    home-monitoring PDF (a cuff's 4-week report) printed the readings the cuff
    also streams, and was listing 43 days twice; its observation is dropped
    when a device row from the same maker exists for that day.  Matched on day
    and maker, never on value: the PDF rounds differently.  A clinic visit is
    never dropped, whatever a device recorded the same morning.
    """
    rows = _deduped_observation_rows(connection, owner_user_id, concept_id)
    linked = [item for item in SAME_TWIN_CONCEPTS if concept_id in (None, item)]
    if not linked:
        return rows
    placeholders = ",".join("?" for _ in linked)
    concepts = {
        str(row["id"]): row
        for row in connection.execute(
            f"SELECT id, canonical_name, category, preferred_unit FROM concepts WHERE id IN ({placeholders})",
            linked,
        )
    }
    columns = [str(row[1]) for row in connection.execute("PRAGMA table_info(observations)")]
    device_rows: list[dict[str, object]] = []
    recorded: set[tuple[str, str, str]] = set()
    for linked_id, concept in concepts.items():
        for key in device_twins(linked_id, "same"):
            recorded.update(
                (linked_id, str(row["day"])[:10], _device_maker(row))
                for row in connection.execute(
                    "SELECT day, source_vendor, source_name FROM device_metric_days WHERE owner_user_id=? AND metric_key=?",
                    (owner_user_id, key),
                )
            )
            device_rows.extend(
                _in_preferred_unit(_device_reading_row(concept, row, columns))
                for row in device_metric_values(connection, owner_user_id, key)
                if valid_row(row)
            )
    if not device_rows:
        return rows
    kept = [
        row for row in rows
        if not (
            row.get("document_clinical_type") in HOME_MONITORING_TYPES
            and (
                str(row["concept_id"]),
                str(row.get("observed_at") or "")[:10],
                canonical_source_vendor(str(row.get("vendor") or "")).casefold(),
            ) in recorded
        )
    ]
    # Newest first, as the document rows already are; a stable sort keeps a
    # day's document and device rows in the order they arrived.
    return sorted(
        [*kept, *device_rows],
        key=lambda row: str(row.get("observed_at") or row.get("created_at") or ""),
        reverse=True,
    )


def _in_preferred_unit(row: dict[str, object]) -> dict[str, object]:
    """Restate one reading in the unit its concept is tracked in.

    The database stores what the report printed, which is the only thing it can
    honestly store -- but a trend has one axis.  Synevo prints MCHC in g/dL and
    Expert Hospital in g/L, so the same person's series read 36, 339, 343, 340,
    36, 342: two readings a tenth of their true size, and a verdict of *below
    range* on a value that is above it.

    Only a conversion registered for this concept is applied.  A unit with no
    registered conversion keeps its printed value and its printed unit, so
    ``evaluate`` sees the disagreement and declines to judge rather than
    comparing a number against an interval written in something else.
    """
    value, printed = row.get("value_numeric"), row.get("unit_raw")
    preferred = row.get("preferred_unit")
    if value is None or not printed or not preferred:
        return row
    if canonical_unit(str(printed)) == canonical_unit(str(preferred)):
        return row
    converted = convert_value(float(value), str(printed), str(preferred), str(row["concept_id"]))
    if converted is None:
        # Honest disagreement: keep the reading as printed and let the verdict
        # layer refuse it.  preferred_unit is cleared so nothing downstream
        # re-labels this number with a unit it is not in.
        return {**row, "preferred_unit": printed}
    # The interval the laboratory printed is in the laboratory's unit, so it
    # has to travel with the value.  Left behind, the MCHC row read "360 g/L,
    # original provider range 32.0-36.0" -- the converted result beside the
    # unconverted bar it is measured against.
    bounds = {
        field: (
            None
            if row.get(field) is None
            else convert_value(float(row[field]), str(printed), str(preferred), str(row["concept_id"]))
        )
        for field in ("vendor_reference_low", "vendor_reference_high")
    }
    return {
        **row,
        **bounds,
        "value_numeric": converted,
        "unit_raw": preferred,
        # So the display layer knows the printed text no longer describes the
        # number beside it and can restate the interval in the same unit.
        "converted_from": printed,
    }


def _row_reference_display(row, age: int | None, sex: str | None, unit: str | None) -> str:
    """The provider's interval, in whatever unit its value is being shown in."""
    if row.get("converted_from"):
        restated = range_text(row["vendor_reference_low"], row["vendor_reference_high"], unit)
        if restated and restated != t(_EM_DASH_KEY):
            return restated
        if row.get("vendor_reference_text"):
            # Could not be restated: say which unit the printed numbers are in.
            return f"{reference_display(row['vendor_reference_text'], age, sex, row.get('value_numeric'))} ({display_unit(str(row['converted_from']))})"
    return reference_display(row["vendor_reference_text"], age, sex, row.get("value_numeric"))


def _same_day_key(row: dict[str, object]) -> str:
    # A device day and a clinic reading on the same date are two readings,
    # not two printings of one: the visit is never folded into the scale.
    return ("device:" if row.get("is_device") else "") + str(
        row.get("observed_at") or f"undated:{row.get('document_id')}"
    )


def _printing_rank(row: dict[str, object]) -> tuple[float, str]:
    return float(row.get("confidence") or 0), str(row.get("created_at") or "")


def _printed_value(row: dict[str, object]) -> object:
    return row.get("value_numeric") if row.get("value_numeric") is not None else row.get("value_text")


def _one_per_day(values: list[dict[str, object]]) -> list[dict[str, object]]:
    """Collapse repeat printings of the same draw to one result per day.

    A laboratory report that prints vitamin D on page 1 and again on page 5
    with a different rounding is one measurement, not a two-day trend.  The
    higher-confidence row represents the day and carries the count of the
    variants, so the interface can disclose the disagreement instead of
    plotting it.
    """
    chosen: dict[str, dict[str, object]] = {}
    for row in values:
        key = _same_day_key(row)
        current = chosen.get(key)
        if current is None:
            row["same_day_count"] = 1
            row["same_day_values"] = []
            chosen[key] = row
            continue
        loser, winner = (current, row) if _printing_rank(row) > _printing_rank(current) else (row, current)
        winner["same_day_count"] = int(current.get("same_day_count") or 1) + 1
        winner["same_day_values"] = list(current.get("same_day_values") or []) + [_printed_value(loser)]
        chosen[key] = winner
    return sorted(
        chosen.values(),
        key=lambda row: str(row.get("observed_at") or row.get("created_at") or ""),
        reverse=True,
    )


def _date_key(value: object) -> int:
    text = re.sub(r"\D", "", str(value or ""))[:8]
    return int(text) if text else 0


def _attention_rank(card: dict[str, object]) -> int:
    """How loudly a result asks to be looked at.  Derived from the verdict.

    0 critical · 1 outside the governing interval · 2 the two cited authorities
    disagree · 3 borderline · 4 nothing to say.  Nothing here is a hand-picked
    concept id: the ranking is whatever the evaluation engine returned.
    """
    verdict = card.get("verdict") or {}
    reading = str(verdict.get("interpretation") or "unjudged")
    if reading in {"critical_low", "critical_high"}:
        return 0
    if reading in ATTENTION_INTERPRETATIONS:
        return 1
    if verdict.get("conflicts_with_vendor"):
        return 2
    if reading in BORDERLINE_INTERPRETATIONS:
        return 3
    return 4


def _catalog_rank(card: dict[str, object]) -> tuple[int, int, int, int]:
    """Default ordering: a person opening "Find results" wants their results.

    Laboratory analytes come before device aggregates - otherwise the first
    forty cards are step counts and the cholesterol the page was opened for is
    unreachable.  Within each group: what needs attention, then what is recent.
    """
    return (
        1 if card["is_device"] else 0,
        _attention_rank(card),
        -_date_key(card["latest_date"]),
        -int(card["count"]),
    )


def _patient_row(connection, owner_user_id: str):
    return _cached(
        ("patient", owner_user_id),
        lambda: connection.execute(
            "SELECT * FROM patients WHERE owner_user_id=? ORDER BY created_at LIMIT 1",
            (owner_user_id,),
        ).fetchone(),
    )


def _measure_again(settings, connection, owner_user_id: str, concept_id: str, sex: str | None) -> dict | None:
    """Where a laboratory result can be measured again and for how much, per
    switched-on lab: its cheapest single test, and the cheapest panel that
    includes it when that costs less or no single test exists.  From the labs'
    stored price lists only (:func:`testplan_routes.stored_lab_items`); a lab
    whose list is being read is left out rather than reported as not selling
    it.  None for a result no laboratory reported or no lab sells."""
    from urllib.parse import urlencode

    from .. import labsync, testplan
    from . import testplan_routes

    if concept_id not in testplan.lab_concepts(connection, owner_user_id):
        return None
    letter = {"male": "M", "female": "F"}.get(str(sex or ""))

    def cost(item):
        return item["final_price"] + sum(fee["price"] for fee in item["fees"])

    offers = []
    for key in testplan_routes.SHOPS:
        if not labsync.active(settings, key):
            continue
        items, fetched = testplan_routes.stored_lab_items(settings, connection, owner_user_id, key)
        sold = [item for item in items or () if concept_id in item["keys"]
                and not (letter and item.get("sex") and item["sex"] != letter)]
        if not sold:
            continue
        single = min((item for item in sold if len(item["keys"]) == 1), key=cost, default=None)
        panel = min((item for item in sold if len(item["keys"]) > 1), key=cost, default=None)
        if single and panel and cost(panel) >= cost(single):
            panel = None
        city = next((region["name"] for row in connection.execute(
            "SELECT payload_json FROM lab_catalog_cache WHERE provider=? AND cache_key='regions'", (key,))
            for region in json.loads(row[0]) if str(region.get("id")) == testplan_routes.SHOPS[key].DEFAULT_REGION), "")
        offers.append({"lab": testplan_routes.VENDORS[key], "city": city, "fetched_at": fetched,
                       "options": [dict(item, kind=kind, fees_cost=cost(item) - item["final_price"])
                                   for kind, item in (("single", single), ("panel", panel)) if item]})
    if not offers:
        return None
    return {"offers": offers,
            "plan_url": "/plan-tests?" + urlencode({"touched": 1, "need": concept_id, "plan": 1})}


def _demographics(connection, owner_user_id: str) -> tuple[int | None, str | None]:
    row = _patient_row(connection, owner_user_id)
    if row is None:
        return None, None
    return age_on(row["date_of_birth"]), row["sex_at_birth"]


def _clinical_context(connection, owner_user_id: str | None) -> dict[str, object]:
    """The record's cardiovascular risk category, once per request."""
    return _cached(
        ("clinical_context", owner_user_id),
        lambda: clinical_context(connection, owner_user_id),
    )


def _first_on_page(key: str) -> bool:
    """True the first time a template asks about ``key`` in this request: an
    explanation that applies to every value on a page is printed once."""
    cache = _request_cache.get()
    if cache is None:
        return True
    seen = cache.setdefault("first_on_page", set())
    if key in seen:
        return False
    seen.add(key)
    return True


#: The block reasons a page can explain in a sentence; anything else (e.g. a
#: unit mismatch) keeps the generic empty state.
BLOCKED_NOTICE_KEYS = {
    "sex_unknown": "verdict.blocked_sex_unknown",
    "age_unknown": "verdict.blocked_age_unknown",
    "requires_clinical_context": "verdict.blocked_clinical_context",
    "requires_cv_risk_category": "verdict.blocked_cv_risk_category",
    "sex_not_covered": "verdict.blocked_sex_not_covered",
}


def _blocked_notice(verdict: dict | None) -> dict[str, object] | None:
    """Why curated judgement was withheld — or diluted to a unisex fallback —
    as a sentence the page can print, with a pointer to the profile when the
    fix is one field away. evaluate() keeps ``curated_blocked`` even when a
    weaker band still judged, so the notice covers both cases."""
    verdict = verdict or {}
    reason = str(verdict.get("curated_blocked") or verdict.get("unjudged_reason") or "")
    key = BLOCKED_NOTICE_KEYS.get(reason)
    if key is None:
        return None
    return {
        "reason": reason,
        "text": t(key),
        "profile_url": (
            "/profile?tab=personal"
            if reason in ("sex_unknown", "age_unknown", "requires_cv_risk_category")
            else None
        ),
    }


def _age_chip_text(age_min: float | None, age_max: float | None) -> str | None:
    low = format_number_localized(age_min) if age_min is not None else None
    high = format_number_localized(age_max) if age_max is not None else None
    if low is not None and high is not None:
        return t("rule.age_range", low=low, high=high)
    if low is not None:
        return t("rule.age_from", years=low)
    if high is not None:
        return t("rule.age_under", years=high)
    return None


def rule_text(rule, field: str) -> str | None:
    """A curated rule's ``label`` or ``notes`` in the reader's language.

    Ukrainian prefers the ``<field>_uk`` column (``label_uk`` since migration
    008; ``notes_uk`` once the library carries it) and then a catalogued
    phrase.  An English sentence nobody has translated is withheld from a
    Ukrainian page rather than printed in English beside Ukrainian bands --
    the band, its interval and its source still show; only the note waits for
    its translation.
    """
    raw = str(rule[field] or "").strip()
    if not raw:
        return None
    if get_locale() != "uk":
        return raw
    column = f"{field}_uk"
    localized = rule[column] if column in rule.keys() else None
    if localized and str(localized).strip():
        return str(localized).strip()
    translated = translate_phrase(raw)
    return translated if translated != raw else None


def _rule_applies(rule_sex: str | None, patient_sex: str | None, age_min, age_max, age: int | None) -> bool:
    if rule_sex and rule_sex != patient_sex:
        return False
    if age_min is None and age_max is None:
        return True
    if age is None:
        return False
    if age_min is not None and age < age_min:
        return False
    return age_max is None or age < age_max


def _rule_applicability(rule, age: int | None, sex: str | None) -> dict[str, object]:
    """Who a curated band is written for, and whether that is this patient.

    Mirrors evaluate()'s matching exactly — same casefold, unknown-as-None sex,
    and the same ``>=`` exclusion on the upper age bound — so the chip never
    contradicts the verdict beside it.
    """
    rule_sex = (str(rule["sex"] or "")).strip().casefold() or None
    age_min, age_max = rule["age_min_years"], rule["age_max_years"]
    patient_sex = (sex or "").strip().casefold() or None
    if patient_sex == "unknown":
        patient_sex = None
    parts = [t(f"sex.{rule_sex}")] if rule_sex else []
    age_text = _age_chip_text(age_min, age_max)
    if age_text:
        parts.append(age_text)
    applies = _rule_applies(rule_sex, patient_sex, age_min, age_max, age)
    return {"applicability": " · ".join(parts) or None, "applies_to_you": applies}


def _oura_datatype_label(data_type: str) -> str:
    """A failed Oura dataset, named by the metrics it feeds — the names the
    rest of the record already uses — rather than by an API identifier."""
    if data_type == "workouts":
        return t("devices.datatype_workouts")
    if data_type == "heartrate":
        return translate_phrase("Daily heart rate")
    names = [oura.DEFS[key].name for key in oura.DATATYPE_KEYS.get(data_type, ()) if key in oura.DEFS]
    return ", ".join(translate_phrase(name) for name in names) or data_type


#: capitalize() mangles initialisms — "spo2" must not surface as "Spo2".
_OURA_SCOPE_NAMES = {"spo2": "SpO₂"}


def _oura_sync_context(settings: Settings, user_id: str) -> dict[str, object] | None:
    """What the devices page must disclose about an Oura connection: datasets
    whose last sync failed, and requested scopes the person declined."""
    row = integrations.connection_row(settings, user_id, "oura")
    if row is None:
        return None
    failures = oura.sync_state(settings, user_id).get("failed_datatypes") or {}
    missing = integrations.missing_scopes(integrations.PROVIDERS["oura"], str(row["scopes"] or ""))
    return {
        "failures": [
            {"datatype": data_type, "label": _oura_datatype_label(data_type), "error": str(error)}
            for data_type, error in sorted(failures.items())
        ],
        "missing_scopes": [
            translate_phrase(_OURA_SCOPE_NAMES.get(scope, scope.replace("_", " ").capitalize()))
            for scope in missing
        ],
        # A link, never a form: the CSP form-action directive would block the
        # cross-origin redirect (see test_connect_is_a_navigation_because_
        # form_action_would_block_it).
        "reconnect_url": "/integrations/oura/connect",
    }


def _openwearables_sync_context(settings: Settings, user_id: str) -> dict[str, object] | None:
    """What the devices page must disclose about a linked OpenWearables server:
    datasets whose last sync failed, and when data last moved.

    Delivery and retrieval are separate stages. A recent notification alone
    must never be presented as a completed import.
    """
    if openwearables.linked(settings, user_id) is None:
        return None
    state = openwearables.sync_state(settings, user_id)
    failed = state.get("failed_datatypes") or {}
    # The labels come back in `sorted(failed)` order — the datatypes are named
    # by the measurements they carry, the errors are the server's own words.
    labels = openwearables.failed_datatype_labels(settings, user_id)
    return {
        "failures": [
            {"label": label, "error": str(failed[datatype])}
            for label, datatype in zip(labels, sorted(failed), strict=False)
        ],
        "last_sync_at": str(state.get("last_sync_at") or ""),
    }


def _visible_vendors(settings: Settings, vendors) -> list[dict[str, object]]:
    """The vendor strip, minus an OpenWearables card nobody can use.

    ``device_overview`` always names the vendor, because rows a since-disabled
    link wrote must keep saying where they came from.  Before anyone linked it,
    though, it is a server this instance does not have, and an integration the
    operator never configured is not a "Ready for export" card — it is no card.
    """
    on = openwearables.configured(settings)
    return [
        dict(vendor)
        for vendor in vendors
        if vendor["key"] != "openwearables"
        or on
        or vendor["record_count"]
        or vendor["import_id"]
    ]


def _guidance_index(connection) -> dict[str, dict[str, object]]:
    return _cached(
        ("guidance", get_locale()),
        lambda: {
            str(row["concept_id"]): localised_guidance(dict(row))
            for row in connection.execute("SELECT * FROM concept_guidance")
        },
    )


def _trend(
    current: float | None,
    previous: float | None,
    unit: str | None,
    previous_date: str | None,
) -> dict[str, object] | None:
    if current is None or previous is None:
        return None
    delta = float(current) - float(previous)
    # A delta is read against the previous value, so it keeps a decimal even
    # where the reading itself is whole: "0.9 bpm", never "1 bpm" for 0.904594.
    text = format_quantity(abs(delta), unit, minimum_decimals=1 if abs(delta) < 10 else 0)
    meaningful = bool(re.search(r"[1-9]", text))
    direction = "flat"
    if meaningful:
        direction = "up" if delta > 0 else "down"
    return {
        "direction": direction,
        "delta_text": f"{text} {unit}".strip() if unit else text,
        "since_text": t("panel.delta_since", date=format_date(previous_date)),
        "meaningful": meaningful,
    }


def _panel_reference(panel_id: str | None) -> tuple[str | None, str | None]:
    if not panel_id:
        return None, None
    panel = PANEL_BY_ID.get(panel_id)
    return (panel.id, translate_phrase(panel.name)) if panel else (None, None)


_DEVICE_PANEL_BY_METRIC: dict[str, str] = {
    key: panel.id for panel in PANELS for key in panel.device_members
}

#: English display name for every device metric key a panel can name, drawn
#: from the importers' own definitions so an absent member is announced under
#: the same name its data would arrive with.
_DEVICE_METRIC_NAMES: dict[str, str] = {
    definition.key: definition.name
    for definition in {**HEALTHKIT_METRICS, **SLEEP_METRICS}.values()
}
_DEVICE_METRIC_NAMES.update(
    {key: name for key, name, _category, _unit, _scale in
     (*OuraAdapter.fields.values(), *GarminAdapter.fields.values())}
)
_DEVICE_METRIC_NAMES.update({d.key: d.name for d in oura.DEFS.values()})
_DEVICE_METRIC_NAMES.update({d.key: d.name for d in openwearables.DEFS.values()})
_DEVICE_METRIC_NAMES.update({d.key: d.name for d in garmin.DEFS.values()})
# Defined inline in their parsers rather than in an importable dict; the
# spellings match devices/structured.py, apple_health.py and kardia.py.
_DEVICE_METRIC_NAMES.update({
    "systolic_blood_pressure": "Systolic blood pressure",
    "diastolic_blood_pressure": "Diastolic blood pressure",
    "blood_pressure_pulse": "Pulse during blood-pressure reading",
    "ecg_heart_rate": "ECG heart rate",
    "body_height": "Body height",
    "body_water_percentage": "Body water",
    "bone_mass": "Bone mass",
    "muscle_mass": "Muscle mass",
})


def _device_member_name(metric_key: str) -> str:
    return translate_phrase(
        _DEVICE_METRIC_NAMES.get(metric_key) or metric_key.replace("_", " ").capitalize()
    )
# A device key that is the same measurement as a concept is read in the
# concept's panel, and in that one only.
_DEVICE_PANEL_BY_METRIC.update(
    {
        key: panel.id
        for key, (concept_id, relation) in TWIN_OF_DEVICE.items()
        if relation == "same" and (panel := panel_for_concept(concept_id)) is not None
    }
)


def _reading_verdict(
    connection, concept_id: str, row: dict[str, object], age: int | None, sex: str | None
) -> tuple[str | None, dict[str, object]]:
    """One reading's unit and verdict -- the single path every lab page judges by.

    `_lab_card` judges the latest day through here and /changes judges every
    day it compares, so the two can never disagree about the same number.
    """
    unit_source = (
        (row["preferred_unit"] or row["unit_raw"])
        if row["value_numeric"] is not None
        else row["unit_raw"]
    )

    # A printed interval that describes newborns or women is not this
    # patient's interval and must never become the bar he is measured against;
    # an adult one that the parser refused is recovered here.
    vendor_low, vendor_high, vendor_interpretation = _vendor_bounds(row, age, sex)

    # canonical_unit() folds locale spelling (`кл/мкл` and `cells/µL`
    # canonicalise identically) so evaluate() is given unit_source, ahead of
    # display_unit()'s cosmetic superscript rewrite (`10^9/L` -> `10⁹/L`):
    # NFKC-folding a Unicode superscript collapses the exponent marker
    # entirely and would silently stop the 10^9/L and 10^12/L curated rules
    # from matching.
    verdict = evaluate(
        connection,
        concept_id=concept_id,
        value_numeric=row["value_numeric"],
        value_text=row["value_text"],
        unit=unit_source,
        age_years=age,
        sex=sex,
        vendor_low=vendor_low,
        vendor_high=vendor_high,
        vendor_interpretation=vendor_interpretation,
        clinical_context=_clinical_context(connection, row.get("owner_user_id")),
    )
    return unit_source, verdict


def _lab_card(
    connection,
    concept_id: str,
    values: list[dict[str, object]],
    aliases: dict[str, list[str]],
    age: int | None,
    sex: str | None,
    guidance_index: dict[str, dict[str, object]],
) -> dict[str, object]:
    daily = _one_per_day(values)
    latest = daily[0]
    name = str(latest["canonical_name"])
    category = str(latest["category"])
    display_name = concept_display_name(name)
    area_ids = metric_area_ids(name, category)
    primary_area_id = area_ids[0] if area_ids else "other"
    area_definition = AREA_BY_ID.get(primary_area_id, {})

    unit_source, verdict = _reading_verdict(connection, concept_id, latest, age, sex)
    unit = display_unit(unit_source)

    numeric_days = [row for row in daily if row["value_numeric"] is not None]
    trend = None
    if len(numeric_days) >= 2:
        trend = _trend(
            float(numeric_days[0]["value_numeric"]),
            float(numeric_days[1]["value_numeric"]),
            unit,
            str(numeric_days[1]["observed_at"] or ""),
        )

    entry = guidance_index.get(concept_id) or {}
    freshness = staleness(
        latest["observed_at"],
        entry.get("retest_interval_months"),
        rationale=entry.get("retest_rationale"),
        condition=entry.get("retest_condition_json"),
        interpretation=str(verdict["interpretation"]),
        age_years=age,
    )

    panel = panel_for_concept(concept_id, category)
    vendor = latest["vendor"]
    vendor = (
        t(_UNKNOWN_PROVIDER_KEY)
        if vendor in {_UNKNOWN_PROVIDER, _UNKNOWN_VENDOR}
        else translate_phrase(str(vendor))
    )
    value_text = format_reading(latest, unit)
    # Both languages' names whatever the reader's locale, so "birch" finds the
    # allergen on the Ukrainian page and «кроки» finds steps on the English one.
    # The area a result belongs to is deliberately absent: matching it made
    # every analyte in "Heart" an answer to "heart rate".
    searchable = record_search.terms(
        [
            name, display_name, CONCEPT_NAMES_EN.get(name), CONCEPT_NAMES_UK.get(name),
            *aliases.get(concept_id, []),
            *[str(item.get("raw_name") or "") for item in values],
        ],
        [panel.name, PHRASES.get(panel.name)] if panel else [],
    )

    return {
        "id": concept_id,
        "url": f"/metrics/{concept_id}",
        "name": display_name,
        "unit": unit,
        "value_text": value_text,
        "value_numeric": latest["value_numeric"],
        "category": category,
        "category_label": category_label(category),
        "area_id": primary_area_id,
        "primary_area_id": primary_area_id,
        "area_ids": area_ids,
        "area_name": translate_phrase(str(area_definition.get("name", "Other results"))),
        "panel_id": panel.id if panel else None,
        "panel_name": translate_phrase(panel.name) if panel else None,
        "latest_date": latest["observed_at"],
        "date_text": format_date(latest["observed_at"]),
        "vendor": vendor,
        "count": len(daily),
        "evidence_count": sum(int(item["evidence_count"]) for item in values),
        "is_device": False,
        "is_unmapped": category == "unmapped",
        "verdict": verdict,
        "trend": trend,
        "staleness": freshness,
        "verification_status": str(latest["verification_status"] or "extracted"),
        "verification_label": (
            t(_DEVICE_MEASUREMENT_KEY) if latest.get("is_device") else status_label(latest["verification_status"])
        ),
        # A same-measurement twin reads one series from documents and devices;
        # the card says so, beside the source of the value it shows.
        "sources_text": (
            t("twin.sources_both")
            if len({bool(item.get("is_device")) for item in values}) > 1
            else ""
        ),
        "same_day_count": int(latest.get("same_day_count") or 1),
        # Legacy fields still read by pages that have not been rebuilt yet.
        "latest_numeric": latest["value_numeric"],
        "latest_text": (
            latinize_code(display_value(latest["value_text"]))
            if latest["value_text"] is not None
            else None
        ),
        "status": verdict["interpretation"],
        "status_label": verdict["label"],
        "aliases": aliases.get(concept_id, [])[:4],
        "series": [
            {"date": str(row["observed_at"]), "value": float(row["value_numeric"])}
            for row in reversed(numeric_days)
            if row["observed_at"]
        ],
        "search_terms": searchable,
        "displayable": _displayable_metric(name),
    }


#: A wearable reports daily; a week without a reading means the device stopped
#: reporting (unworn, unpaired, sync broken), not that nothing changed (OPS-24).
DEVICE_STALE_DAYS = 7


def _arrives_daily(days: list[object]) -> bool:
    """True for a metric that normally has a value most days (a watch's step
    count), false for one taken on demand (an ECG, a cuff reading): only the
    first kind says anything by going quiet for a week."""
    seen = sorted({str(day)[:10] for day in days if day})
    if len(seen) < 5:
        return False
    try:
        span = (date.fromisoformat(seen[-1]) - date.fromisoformat(seen[0])).days + 1
    except ValueError:
        return False
    return len(seen) / span >= 0.5


def _device_staleness(
    latest_day: object, entry: dict[str, object], *, interpretation: str | None = None, age_years: float | None = None,
    daily: bool = True,
) -> dict[str, object]:
    """The cadence chip for a device metric: a cited retest interval when one
    exists (and its condition holds), otherwise "no new readings for N days"
    once a week has passed."""
    freshness = staleness(
        latest_day,
        entry.get("retest_interval_months"),
        rationale=entry.get("retest_rationale"),
        condition=entry.get("retest_condition_json"),
        interpretation=interpretation,
        age_years=age_years,
    )
    days = freshness.get("days_ago")
    # On-demand readings (an ECG, a cuff) have no expected next day: months
    # between them is how they are taken, not a device that went quiet.
    if daily and days is not None and int(days) > DEVICE_STALE_DAYS:
        # A device that stopped sending a metric is a fact about the device,
        # not a test falling due: the badge system means "a cited schedule
        # says this is due" and nothing else (owner, 2026-11-06 -- "no one
        # draws blood every 91 days").  The card says it in plain text beside
        # the date instead; the state stays whatever the cadence decided.
        freshness = {
            **freshness,
            "quiet_text": t_plural("device.stale", int(days), value=format_count(days)),
            "quiet_body": t("device.stale_body", date=format_date(str(latest_day)[:10])),
        }
    return freshness


def _quiet_suffix(freshness: dict[str, object]) -> str:
    return f" · {freshness['quiet_text']}" if freshness.get("quiet_text") else ""


def _device_trend(raw: dict[str, object], unit: str) -> dict[str, object] | None:
    legacy_trend = raw.get("trend") or {}
    if not legacy_trend:
        return None
    delta = float(legacy_trend.get("delta") or 0.0)
    current = float(raw["latest_numeric"] or 0.0)
    trend = _trend(current, current - delta, unit, None)
    if trend:
        trend["since_text"] = t("panel.trend_flat") if not trend["meaningful"] else ""
    return trend


def _device_search_terms(raw: dict[str, object], metric_key: str, panel_name) -> list[str]:
    # The catalog names the metric in the reader's language only; the phrase
    # table gives back the other one.  No vendor boilerplate: the words "ECG
    # blood pressure" on every device card made all 57 of them an answer to
    # "blood pressure".
    return record_search.terms(
        [
            raw["name"], _english(str(raw["name"])), PHRASES.get(_english(str(raw["name"]))),
            metric_key.replace("_", " "),
        ],
        [
            raw["category_label"], _english(str(raw["category_label"])), panel_name,
            *[str(item) for item in (raw.get("aliases") or [])],
        ],
    )


def _device_card(
    connection,
    raw: dict[str, object],
    age: int | None,
    sex: str | None,
    guidance_index: dict[str, dict[str, object]],
) -> dict[str, object]:
    metric_key = str(raw["id"]).removeprefix(_DEVICE_METRIC_PREFIX)
    unit = str(raw["unit"] or "")
    verdict = evaluate(
        connection,
        concept_id=metric_key,
        value_numeric=raw["latest_numeric"],
        unit=unit,
        age_years=age,
        sex=sex,
    )
    entry = guidance_index.get(metric_key) or {}
    freshness = _device_staleness(
        raw["latest_date"], entry, interpretation=str(verdict["interpretation"]), age_years=age,
        daily=_arrives_daily([item["date"] for item in raw.get("series") or []]),
    )
    panel_id, panel_name = _panel_reference(_DEVICE_PANEL_BY_METRIC.get(metric_key))
    # Rounding must not carry a value across the edge of the band that judged
    # it: 6.95 h printed as "7 h" beside "below the >=7 h recommendation".
    shown = format_quantity(
        raw["latest_numeric"], unit,
        minimum_decimals=_edge_safe(raw["latest_numeric"], unit, verdict),
    )
    exact = format_measured(raw["latest_numeric"], unit)
    trend = _device_trend(raw, unit)
    return {
        **raw,
        "unit": unit,
        # `format_measured` honours the digits the number *carries*, which is
        # right for a value transcribed off a printed report and wrong here: a
        # device aggregate is a mean over a day's samples, so it carries the
        # full float and was published as `68.457 bpm` and `63.5671 ms` --
        # four decimals of arithmetic residue presented as precision the sensor
        # never had.  `format_quantity` uses UNIT_DECIMALS, which already says
        # what each unit is worth reading to.  The undivided number stays
        # reachable on `value_exact`, so nothing is hidden, only unstated.
        "value_text": shown,
        "value_exact": exact if exact != shown else "",
        "value_numeric": raw["latest_numeric"],
        # A blood-pressure reading from a cuff is not "sleep & recovery"; when a
        # panel claims the metric the panel names it.
        "category_label": panel_name or raw["category_label"],
        "panel_id": panel_id,
        "panel_name": panel_name,
        "date_text": format_date(str(raw["latest_date"])) + _quiet_suffix(freshness),
        "verdict": verdict,
        "trend": trend,
        "staleness": freshness,
        "verification_status": "device_measurement",
        "verification_label": t(_DEVICE_MEASUREMENT_KEY),
        "is_unmapped": False,
        "status": verdict["interpretation"],
        "status_label": verdict["label"],
        "series": raw.get("series") or [],
        # The catalog names the metric in the reader's language only; the
        # phrase table gives back the other one.  No vendor boilerplate: the
        # words "ECG blood pressure" on every device card made all 57 of them
        # an answer to "blood pressure".
        "search_terms": _device_search_terms(raw, metric_key, panel_name),
        "displayable": True,
    }


_PHRASE_SOURCES = {translated: english for english, translated in PHRASES.items()}


def _english(text: str) -> str:
    """The English phrase a translated label came from (itself when English)."""
    return _PHRASE_SOURCES.get(text, text)


def _build_lab_catalog(connection, owner_user_id: str) -> list[dict[str, object]]:
    age, sex = _demographics(connection, owner_user_id)
    guidance_index = _guidance_index(connection)
    aliases: dict[str, list[str]] = {}
    for row in connection.execute(
        """SELECT DISTINCT a.concept_id, a.alias FROM concept_aliases a
           WHERE EXISTS (SELECT 1 FROM observations o WHERE o.concept_id=a.concept_id
                         AND o.owner_user_id=? AND o.verification_status <> 'rejected')""",
        (owner_user_id,),
    ):
        aliases.setdefault(str(row["concept_id"]), []).append(str(row["alias"]))
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in _deduped_observation_rows(connection, owner_user_id):
        # A concept with a same-measurement device twin is built by
        # `_build_linked_catalog`, from both halves of the record.
        if str(row["concept_id"]) not in SAME_TWIN_CONCEPTS:
            grouped.setdefault(str(row["concept_id"]), []).append(row)
    return [
        _lab_card(connection, concept_id, values, aliases, age, sex, guidance_index)
        for concept_id, values in grouped.items()
    ]


def _build_linked_catalog(connection, owner_user_id: str) -> list[dict[str, object]]:
    """One card per same-measurement twin, read from documents and devices.

    Built apart from both halves because it reads both: a scale sync and a
    clinic upload each change it, and neither may rebuild the other half.
    """
    age, sex = _demographics(connection, owner_user_id)
    guidance_index = _guidance_index(connection)
    placeholders = ",".join("?" for _ in SAME_TWIN_CONCEPTS)
    aliases: dict[str, list[str]] = {}
    for row in connection.execute(
        f"SELECT DISTINCT concept_id, alias FROM concept_aliases WHERE concept_id IN ({placeholders})",
        SAME_TWIN_CONCEPTS,
    ):
        aliases.setdefault(str(row["concept_id"]), []).append(str(row["alias"]))
    cards = []
    for concept_id in SAME_TWIN_CONCEPTS:
        values = _linked_observation_rows(connection, owner_user_id, concept_id)
        if values:
            cards.append(_lab_card(connection, concept_id, values, aliases, age, sex, guidance_index))
    return cards


def _build_device_catalog(connection, owner_user_id: str) -> list[dict[str, object]]:
    age, sex = _demographics(connection, owner_user_id)
    guidance_index = _guidance_index(connection)
    return [
        _device_card(connection, raw, age, sex, guidance_index)
        for raw in device_metric_catalog(connection, owner_user_id)
        # Read on its concept's card; listing it here would show it twice.
        if str(raw["id"]).removeprefix(_DEVICE_METRIC_PREFIX) not in SAME_DEVICE_KEYS
    ]


def _build_catalog(connection, owner_user_id: str) -> list[dict[str, object]]:
    return [
        *_build_lab_catalog(connection, owner_user_id),
        *_build_linked_catalog(connection, owner_user_id),
        *_build_device_catalog(connection, owner_user_id),
    ]


def _catalog(connection, owner_user_id: str) -> list[dict[str, object]]:
    # Three memo slots: a device sync rebuilds only the device half and the
    # few linked twins (PERF-02).  The demographics every slot judges by live
    # in the patient row, whose edits invalidate the owner's whole memo.
    lab = _memoised(connection, owner_user_id, "lab_catalog", lambda: _build_lab_catalog(connection, owner_user_id))
    linked = _memoised(connection, owner_user_id, "linked_catalog", lambda: _build_linked_catalog(connection, owner_user_id))
    device = _memoised(connection, owner_user_id, "device_catalog", lambda: _build_device_catalog(connection, owner_user_id))
    return [*lab, *linked, *device]


def _device_overview(connection, owner_user_id: str) -> dict[str, object]:
    """The devices summary, memoised: it rescans all 58k daily rows to build it."""
    return _memoised(
        connection, owner_user_id, "devices", lambda: device_overview(connection, owner_user_id)
    )


def _metric_catalog(
    connection,
    owner_user_id: str,
    *,
    include_devices: bool = True,
    include_suppressed: bool = False,
) -> list[dict[str, object]]:
    """Every measurement this user owns, as `MetricCard`s, ranked for display.

    One shape for every grid on every page: the card carries its own verdict,
    trend, staleness and pre-formatted text, so no template ever has to work
    out what a number means.  Callers slice for pagination; the full list is
    memoised per request.  Searching it is `_record_search`'s job.
    """
    cards = []
    for card in _catalog(connection, owner_user_id):
        if not include_devices and card["is_device"]:
            continue
        if not include_suppressed and card["id"] in DISPLAY_SUPPRESSED:
            # Kept in the record and reachable by name; just not a result in
            # its own right, so it does not crowd the default view.
            continue
        if not card["displayable"]:
            continue
        cards.append(card)
    cards.sort(key=_catalog_rank)
    return cards


def _by_id(cards: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(card["id"]): card for card in cards}


def _representative(cards: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
    """The members worth showing in a card's preview strip.

    Abnormal first, then the most recent, then the most trended - and never the
    same number twice, which is how the heart card came to spend both of its
    slots on `77 bpm`.
    """
    ordered = sorted(
        cards,
        key=lambda card: (_attention_rank(card), -_date_key(card["latest_date"]), -int(card["count"])),
    )
    seen: set[tuple[str, str]] = set()
    picked: list[dict[str, object]] = []
    for card in ordered:
        fingerprint = (str(card["value_text"]), str(card["unit"]))
        if fingerprint in seen and len(ordered) > limit:
            continue
        seen.add(fingerprint)
        picked.append(card)
        if len(picked) >= limit:
            break
    return picked


def _attention_cards(catalog: list[dict[str, object]]) -> list[dict[str, object]]:
    """What deserves attention, ordered by what the verdicts actually say.

    Laboratory results outrank device aggregates at equal severity: a wearable's
    partial day is still measured against a published threshold, but it is not
    what a person came to this page to read.
    """
    flagged = [
        card
        for card in catalog
        # A weekly maximum is a statistic derived from readings that are
        # themselves judged here; listing both says the same thing twice.
        if _attention_rank(card) <= 3 and not str(card["id"]).startswith("weekly-")
    ]
    flagged.sort(
        key=lambda card: (
            _attention_rank(card),
            1 if card["is_device"] else 0,
            -_date_key(card["latest_date"]),
        )
    )
    return flagged


def _finding_summary(row: dict[str, object]) -> str:
    """A finding in the reader's language: its own summary, else the other
    language's, else the first line that was printed."""
    english, ukrainian = str(row.get("summary_en") or "").strip(), str(row.get("summary_uk") or "").strip()
    own, other = (ukrainian, english) if get_locale() == "uk" else (english, ukrainian)
    text = own or other or str(row.get("original_text") or "").strip() or str(row.get("title") or "")
    text = collapse_space(text.splitlines()[0] if text else "")
    return text if len(text) <= 220 else text[:217].rstrip() + "..."


def _attention_findings(findings: list[dict[str, object]]) -> list[dict[str, object]]:
    """Report conclusions marked `attention`, one per document and wording.

    A finding is filed under every area it touches; the reader should see the
    serrated adenoma once, not once per organ the pathology report names.
    """
    seen: set[tuple[object, str]] = set()
    picked: list[dict[str, object]] = []
    for row in findings:
        if row.get("status") != "attention":
            continue
        key = (row.get("document_id"), _finding_summary(row))
        if key not in seen:
            seen.add(key)
            picked.append(row)
    return picked


def _finding_result(row: dict[str, object]) -> dict[str, object]:
    """A finding as one search or priority row."""
    return {
        "title": _finding_summary(row),
        "subtitle": " · ".join(
            str(part) for part in (row.get("title"), row.get("date_text"), row.get("vendor")) if part
        ),
        "url": f"/documents/{row['document_id']}",
        "badge": t("panels.status_attention") if row.get("status") == "attention" else "",
        "note": t("metrics.finding_attention_note") if row.get("status") == "attention" else "",
    }


def _partial_day(connection, owner_user_id: str, metric_key: str, day: object) -> bool:
    """Whether `day` is a day the device is still recording (CONTRACTS §6)."""
    from ..devices.timezone import user_timezone

    zone = user_timezone(connection, owner_user_id)
    return bool(device_queries.is_partial_day(metric_key, str(day or "")[:10], zone))


def _complete_days(connection, owner_user_id: str, catalog: list[dict[str, object]]) -> list[dict[str, object]]:
    """The catalog with every still-recording device day replaced by the last
    complete one.

    At 08:00 today's step count is 0 and today's active energy 0 kcal; judged
    against a daily threshold, both read as "Below" and headed the home page.
    A day that is still being recorded is not a measurement of that day.
    The replacement card is judged again by `evaluate`, never copied.
    """
    demographics: tuple[int | None, str | None] | None = None
    guidance: dict[str, dict[str, object]] = {}
    cards: list[dict[str, object]] = []
    for card in catalog:
        metric_key = str(card["id"]).removeprefix(_DEVICE_METRIC_PREFIX)
        if not card["is_device"] or not _partial_day(connection, owner_user_id, metric_key, card["latest_date"]):
            cards.append(card)
            continue
        today = str(card["latest_date"])[:10]
        earlier = [point for point in card.get("series") or [] if str(point["date"])[:10] < today]
        if not earlier:
            continue
        if demographics is None:
            demographics = _demographics(connection, owner_user_id)
            guidance = _guidance_index(connection)
        last, previous = earlier[-1], (earlier[-2] if len(earlier) > 1 else None)
        raw = {
            **card,
            "latest_numeric": last["value"],
            "latest_date": str(last["date"])[:10],
            "series": earlier,
            "trend": {"delta": float(last["value"]) - float(previous["value"])} if previous else None,
            "count": max(1, int(card.get("count") or 1) - 1),
        }
        cards.append(_device_card(connection, raw, *demographics, guidance))
    return cards


def _outside_by_text(card: dict[str, object]) -> str | None:
    """How far outside the target interval this value sits, formatted.

    ``None`` for a value inside its interval, a text result, or a distance
    that rounds to nothing worth saying.
    """
    verdict = card.get("verdict") or {}
    value = card.get("value_numeric")
    if value is None:
        return None
    low = verdict.get("target_low", verdict.get("low"))
    high = verdict.get("target_high", verdict.get("high"))
    if high is not None and float(value) > float(high):
        delta = float(value) - float(high)
    elif low is not None and float(value) < float(low):
        delta = float(low) - float(value)
    else:
        return None
    unit = str(card.get("unit") or "") or None
    text = format_quantity(delta, unit, minimum_decimals=1 if delta < 10 else 0)
    if not re.search(r"[1-9]", text):
        return None
    return f"{text} {unit}".strip() if unit else text


# --- panels -----------------------------------------------------------------


def _panel_member_names(connection, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    unique = list(dict.fromkeys(ids))
    placeholders = ",".join("?" for _ in unique)
    return {
        str(row["id"]): concept_display_name(str(row["canonical_name"]))
        for row in connection.execute(
            f"SELECT id, canonical_name FROM concepts WHERE id IN ({placeholders})", unique
        )
    }


def _missing_panel_members(keys: list[str], by_id: dict[str, dict[str, object]], names: dict[str, str]) -> list[dict[str, object]]:
    return [
        {
            "id": key,
            "name": (
                _device_member_name(key.removeprefix(_DEVICE_METRIC_PREFIX))
                if key.startswith(_DEVICE_METRIC_PREFIX)
                else names.get(key, key)
            ),
        }
        for key in keys
        if key not in by_id
    ]


def _retest_rationale(connection, keys: list[str], cadence) -> object:
    if cadence is None:
        return None
    guidance_index = _guidance_index(connection)
    for key in keys:
        entry = guidance_index.get(key.removeprefix(_DEVICE_METRIC_PREFIX)) or {}
        if entry.get("retest_interval_months") == cadence:
            return entry.get("retest_rationale")
    return None


def _worst_member_freshness(present: list[dict[str, object]], freshness: dict[str, object]) -> dict[str, object]:
    # Each member is judged against its own cadence, and the worst member state
    # governs the panel: a 3-month TSH must not hide behind a fresher antibody
    # draw.  `days_ago` stays the panel's own latest so sorting is unchanged.
    severity = {"overdue": 0, "due_soon": 1}
    overdue_members = [
        card["staleness"]
        for card in present
        if (card.get("staleness") or {}).get("state") in severity
    ]
    worst = min(
        overdue_members, key=lambda state: severity[str(state["state"])], default=None
    )
    if worst is not None and severity[str(worst["state"])] < severity.get(
        str(freshness["state"]), 9
    ):
        return {**worst, "days_ago": freshness.get("days_ago")}
    return freshness


def _panel_card(
    connection,
    panel,
    by_id: dict[str, dict[str, object]],
    names: dict[str, str],
    *,
    member_limit: int | None = None,
) -> dict[str, object]:
    member_ids = panel_members(connection, panel)
    keys = list(member_ids) + [f"device:{key}" for key in panel.device_members]
    present = [by_id[key] for key in keys if key in by_id]
    missing = _missing_panel_members(keys, by_id, names)
    latest = max((str(card["latest_date"] or "") for card in present), default="")
    cadence = panel_retest_months(connection, panel)
    rationale = _retest_rationale(connection, keys, cadence)
    freshness = staleness(latest or None, cadence, rationale=rationale)
    freshness = _worst_member_freshness(present, freshness)
    summary = roll_up(present, freshness)
    # A member whose two cited authorities disagree is not a clean "normal";
    # panels.roll_up judges on interpretation alone, so the conflict is folded
    # into the *status* here until the domain layer carries it. It is never
    # folded into flagged_count: the two sets overlap - a value can be both
    # above the interval and disputed - and adding them counted it twice, so a
    # two-analyte panel claimed "Outside the interval: 2" beside a member the
    # same card labelled "Within range".
    conflicted = sum(
        1 for card in present if (card["verdict"] or {}).get("conflicts_with_vendor")
    )
    status = str(summary["status"])
    if conflicted and status == "normal":
        status = "borderline"
    area = AREA_BY_ID.get(panel.area_id, {})
    members = _representative(present, member_limit) if member_limit else present
    return {
        "id": panel.id,
        "url": f"/panels/{panel.id}",
        "name": translate_phrase(panel.name),
        "short": translate_phrase(panel.short),
        "description": translate_phrase(panel.description),
        "area_id": panel.area_id,
        "area_name": translate_phrase(str(area.get("name", panel.area_id))),
        "status": status,
        "status_label": t(f"panels.status_{status}"),
        "member_count": len(keys),
        "present_count": len(present),
        "flagged_count": int(summary["flagged_count"]),
        "conflict_count": conflicted,
        "staleness": freshness,
        "members": members,
        "missing_members": missing,
        # Device metrics are not analytes; the card wording switches on this.
        "has_device_members": bool(panel.device_members),
        "renderer": panel.renderer,
    }


def _panel_cards(
    connection, owner_user_id: str, *, member_limit: int | None = None
) -> list[dict[str, object]]:
    catalog = _metric_catalog(connection, owner_user_id)
    by_id = _by_id(catalog)
    every_member = [
        member for panel in PANELS for member in panel_members(connection, panel)
    ]
    names = _panel_member_names(connection, [key for key in every_member if key not in by_id])
    return [
        _panel_card(connection, panel, by_id, names, member_limit=member_limit)
        for panel in PANELS
    ]


_PANEL_STATUS_ORDER = {
    "attention": 0, "borderline": 1, "stale": 2, "normal": 3, "unjudged": 4, "absent": 5,
}
_STALENESS_ORDER = {"overdue": 0, "due_soon": 1, "no_interval": 2, "fresh": 3, "never": 4}


def _panel_sort_key(panel: dict[str, object]) -> tuple[int, int, int]:
    return (
        _PANEL_STATUS_ORDER.get(str(panel["status"]), 9),
        _STALENESS_ORDER.get(str(panel["staleness"]["state"]), 9),
        -int(panel["staleness"].get("days_ago") or 0),
    )


#: How far outside the data a reference bound may lie and still pull the value
#: axis out to it, as a share of the data's own spread.  Further than that the
#: band would squash the series into a few pixels (haemoglobin 146-159 drawn on
#: a 130-170 axis, LDL 2.7-5.5 on 0-6), so it is clipped to the plot instead.
#: The same rule is `AnamnaChart.fitDomain` in chart.js; keep the two in step.
NEAR_BOUND_SHARE = 0.5
AXIS_PAD_SHARE = 0.08


def fit_domain(values: list[float], bounds: list[float | None]) -> tuple[float, float]:
    """The value axis for a series: its own spread plus padding.

    A reference bound widens the axis only when it lies near the data, and a
    never-negative measurement is never given a negative floor.  The axis is
    never forced to zero: a laboratory value sits far from it.
    """
    low, high = min(values), max(values)
    spread = high - low or max(abs(high) * 0.1, 1e-6)
    reach = spread * NEAR_BOUND_SHARE
    for bound in (float(value) for value in bounds if value is not None):
        if low - reach <= bound <= high + reach:
            low, high = min(low, bound), max(high, bound)
    pad = (high - low or spread) * AXIS_PAD_SHARE
    floor = low - pad
    if min(values) >= 0 and floor < 0:
        floor = 0.0
    return floor, high + pad


#: A run of number characters.  Only a run can hold a printed decimal: its
#: first character is never preceded by another digit, point, comma or "№",
#: so "№1.5", "1.2.3" and the "5.3" of "1,5.3" are never read as one.
_NUMERIC_RUN = re.compile(r"[\d.,№]+")


def _localize_printed_decimal(match: re.Match[str]) -> str:
    """The run with a leading "<digits>.<digits>" in the reader's locale, kept
    at its printed precision; anything else in the run is left as printed."""
    run = match.group(0)
    whole, point, rest = run.partition(".")
    places = next((index for index, char in enumerate(rest) if not char.isdecimal()), len(rest))
    tail = rest[places:]
    if not (point and whole.isdecimal() and places) or tail.startswith("."):
        return run
    return format_number_localized(float(f"{whole}.{rest[:places]}"), places) + tail


def localized_reference(text: str | None) -> str | None:
    """A laboratory's printed interval with its numbers in the reader's locale.

    The text is quoted from the report ("Жінки: ризик відсутній: >1.68"), so a
    Ukrainian page printed "1.68" and "0.0" beside "≤ 2,59" from the engine.
    Each decimal goes through `format_number_localized` at its printed
    precision; the words are left as printed.
    """
    if not text or get_locale() != "uk":
        return text
    return _NUMERIC_RUN.sub(_localize_printed_decimal, str(text))


_NUMBER_SEPARATORS = "  ,."
_PRINTED_NUMBER_RUN = re.compile(r"[\d  ,.]+")


def _first_printed_number(text: str) -> str:
    """The first run of number characters that holds a digit, cut after its
    last digit: "12" of "Below 12-20", "1 234,5" of "1 234,5 g/L"."""
    for match in _PRINTED_NUMBER_RUN.finditer(text):
        if any(char.isdecimal() for char in match.group(0)):
            return match.group(0).rstrip(_NUMBER_SEPARATORS)
    return ""


def precise_at_edges(value: float | None, text: str, verdict: dict[str, object] | None) -> str:
    """``text`` with as many extra decimals as it takes not to cross a bound.

    A resting 11.68 printed as "12" beside "Below 12–20", or 6.95 h printed as
    "7 h" beside "Below ≥7", reads as a contradiction.  When rounding lands the
    printed number on the other side of (or exactly on) a bound the value is
    not on, one more decimal is added, up to three.
    """
    if value is None or not verdict or not re.search(r"\d", text or ""):
        return text
    bounds = {
        float(bound)
        for key in ("low", "high", "target_low", "target_high")
        if (bound := verdict.get(key)) is not None
    }
    number = float(value)
    printed_text = _first_printed_number(text)
    if not printed_text:
        return text
    separator = "," if get_locale() == "uk" else "."
    decimals = len(printed_text.rsplit(separator, 1)[1]) if separator in printed_text else 0

    def printed(places: int) -> float:
        return round(number, places)

    def crosses(places: int) -> bool:
        shown = printed(places)
        return any(
            (shown < bound) != (number < bound) or (shown == bound) != (number == bound)
            for bound in bounds
        )

    places = decimals
    while crosses(places) and places < decimals + 3:
        places += 1
    if places == decimals:
        return text
    return text.replace(printed_text, format_number_localized(number, places).rstrip(), 1)


def _sparkline(card: dict[str, object], span: tuple[int, int] | None) -> dict[str, object] | None:
    """One member's series on a shared time axis, in a 100x30 viewBox.

    A single point is not a trend; those return None so the page does not draw
    a 500 px chart with one dot on it.
    """
    series = card.get("series") or []
    if len(series) < 2:
        return None
    values = [float(point["value"]) for point in series]
    verdict = card.get("verdict") or {}
    # Shade the band the reader should be IN, not the severity tier the value
    # matched — same rule the range bar implements (`reference.py:_verdict`).
    # `target_*` already fall back to the matched band when it is the benign one.
    band_low = verdict.get("target_low", verdict.get("low"))
    band_high = verdict.get("target_high", verdict.get("high"))
    low, high = fit_domain(values, [band_low, band_high])
    dates = [_date_key(point["date"]) for point in series]
    start, end = span or (min(dates), max(dates))
    width = max(end - start, 1)

    def place_y(value: float) -> float:
        return round(30.0 * (1.0 - (value - low) / (high - low)), 2)

    points = [
        {"x": round(100.0 * (_date_key(point["date"]) - start) / width, 2), "y": place_y(float(point["value"]))}
        for point in series
    ]
    band = None
    if band_low is not None or band_high is not None:
        # The axis follows the data now, so a far bound lies off the plot:
        # the band is clipped to what is drawn rather than painted outside it.
        start = place_y(float(band_high)) if band_high is not None else 0.0
        end = place_y(float(band_low)) if band_low is not None else 30.0
        start, end = min(max(start, 0.0), 30.0), min(max(end, 0.0), 30.0)
        band = {"start": start, "end": end} if end > start else None
    return {
        "points": points,
        "band": band,
        "path": " ".join(f"{point['x']},{point['y']}" for point in points),
    }


# --- allergy renderer -------------------------------------------------------
#
# Grouping is taxonomic, read from the WHO/IUIS code that every allergen name
# carries ("Bet v 1" is birch, "Der p 2" a house-dust mite) through the
# allergen source table in ``anamna.allergy``, which also serves /allergy.  It
# orders 295 identical-looking rows into families a person can scan; it makes
# no clinical claim.  The old genus-only table put rice (Ory s) among grass
# pollens, hemp (Can s) among animals and tomato (Sola l) among insect venoms.
_PANEL_GROUP = {
    "animals": "animal_dander", "insects": "insect_venom", "latex": "other",
    **{key: "foods" for key in ("legumes", "cereals", "spices", "fruits", "vegetables", "nuts_seeds",
                                "milk", "egg", "fish_seafood", "meat")},
}


def _allergen_family(name: str) -> str:
    """Which allergen family a component name belongs to."""
    from ..allergy import SOURCE_GROUP, parse_name

    group = SOURCE_GROUP.get(str(parse_name(name)["source"] or ""), "other")
    return _PANEL_GROUP.get(group, group)


def _cap_classes(connection) -> list[dict[str, object]]:
    """The CAP/RAST class legend, read from the curated library, never typed."""
    rows = connection.execute(
        """SELECT DISTINCT label, lower_bound, upper_bound, unit
           FROM curated_reference_rules
           WHERE label LIKE 'Class %' ORDER BY COALESCE(lower_bound, -1)"""
    ).fetchall()
    legend = []
    for row in rows:
        match = re.match(r"Class (\d)", str(row["label"]))
        if not match:
            continue
        legend.append(
            {
                "class": int(match.group(1)),
                "lower": row["lower_bound"],
                "upper": row["upper_bound"],
                "range_text": _bounds_text(row["lower_bound"], row["upper_bound"], row["unit"]),
                "label": t(f"allergy.cap_{match.group(1)}"),
            }
        )
    return legend


def _bounds_text(low: object, high: object, unit: object) -> str:
    from ..reference import range_text

    return range_text(
        float(low) if low is not None else None,
        float(high) if high is not None else None,
        display_unit(str(unit)) if unit else None,
    )


def _cap_class(value: float | None, legend: list[dict[str, object]]) -> int | None:
    """Which published class a result falls in, using the seeded bounds."""
    if value is None:
        return None
    for entry in sorted(legend, key=lambda item: -(item["lower"] if item["lower"] is not None else -1)):
        low, high = entry["lower"], entry["upper"]
        if (low is None or value >= float(low)) and (high is None or value < float(high)):
            return int(entry["class"])
    return None


#: Above this many results an area page lists them as one table, not cards:
#: 296 allergen cards were 108,831 px of «<0,1 kUA/L» at phone width.
AREA_TABLE_THRESHOLD = 30
_COMPONENT_CODE_RE = re.compile(r"\b([A-Z][a-z]{1,3}\s+[a-z]{1,3}(?:\s+\d{1,2})?)\b")


def _area_row(card: dict[str, object], area_id: str, legend) -> dict[str, object]:
    from ..allergy import ALEX_SOURCE_ID, alex_legend

    value = float(card["value_numeric"]) if card.get("value_numeric") is not None else None
    code = _COMPONENT_CODE_RE.search(str(card.get("name") or "")) if area_id == "allergy" else None
    # An ALEX result is graded on the ALEX report's own five levels; the
    # ImmunoCAP classes belong to another assay.  The class column renders
    # ``allergy.cap_<key>``, so the ALEX key carries its prefix.
    alex = bool(legend) and (card.get("verdict") or {}).get("source_id") == ALEX_SOURCE_ID
    level = _cap_class(value, alex_legend() if alex else legend) if legend else None
    return {
        "card": card,
        "code": code.group(1) if code else "",
        "cap_class": f"alex_{level}" if alex and level is not None else level,
        "class_rank": level,
        # An allergen measured above the detection limit is shown even
        # below class 1: «Cyn d 1 0,12» was visible only in a panel preview.
        "attention": _attention_rank(card) <= 1 or (
            area_id == "allergy" and value is not None and value > 0
            and not str(card.get("value_text") or "").lstrip().startswith(("<", "≤"))
            and card.get("id") != "total-immunoglobulin-e"
        ),
        "value": value,
    }


def _area_table(connection, area_id: str, metrics: list[dict[str, object]]) -> dict[str, object] | None:
    """The compact table for an area with too many results for cards.

    Results the evaluation engine flags come first (for allergens: sensitised,
    by ImmunoCAP class), then everything by value; the allergen component code
    is shown verbatim as printed.
    """
    if len(metrics) <= AREA_TABLE_THRESHOLD:
        return None
    legend = _cap_classes(connection) if area_id == "allergy" else []
    rows = [_area_row(card, area_id, legend) for card in metrics]
    rows.sort(key=lambda row: (
        not row["attention"], _attention_rank(row["card"]), -(row["class_rank"] if row["class_rank"] is not None else -1),
        -(row["value"] or 0), str(row["card"].get("name") or ""),
    ))
    return {
        "rows": rows,
        "attention": [row for row in rows if row["attention"]],
        "has_class": bool(legend),
        "attention_heading": t("area.table_detected" if area_id == "allergy" else "area.table_attention"),
        "has_code": any(row["code"] for row in rows),
    }


def _attends(card: dict[str, object]) -> bool:
    return str((card["verdict"] or {}).get("interpretation")) in ATTENTION_INTERPRETATIONS


def _highest_text(cards: list[dict[str, object]]) -> str:
    numeric = [(float(card["value_numeric"]), card) for card in cards if card["value_numeric"] is not None]
    highest = max(numeric, key=lambda item: item[0], default=None)
    return format_measurement(highest[0], str(highest[1]["unit"])) if highest else t(_EM_DASH_KEY)


def _is_alex(card: dict[str, object]) -> bool:
    from ..allergy import ALEX_SOURCE_ID

    return (card.get("verdict") or {}).get("source_id") == ALEX_SOURCE_ID


def _allergy_item(card: dict[str, object], legend) -> dict[str, object]:
    from ..allergy import alex_legend

    scale = alex_legend() if _is_alex(card) else legend
    level = _cap_class(float(card["value_numeric"]) if card["value_numeric"] is not None else None, scale)
    return {
        "name": card["name"],
        "value_text": f"{card['value_text']} {card['unit']}".strip(),
        "cap_class": level,
        "class_label": next((entry["label"] for entry in scale if entry["class"] == level), t(_EM_DASH_KEY)),
        "interpretation": str((card["verdict"] or {}).get("interpretation") or "unjudged"),
        "url": card["url"],
    }


def _allergy_group(key: str, members: list[dict[str, object]], legend) -> dict[str, object]:
    members.sort(
        key=lambda card: (_attention_rank(card), -(float(card["value_numeric"] or 0)), str(card["name"]))
    )
    return {
        "key": key,
        "name": t(f"allergy.group_{key}"),
        "tested": len(members),
        "positive": sum(1 for card in members if _attends(card)),
        "highest_text": _highest_text(members),
        "items": [_allergy_item(card, legend) for card in members],
    }


def _allergy_block(connection, rows: list[dict[str, object]]) -> dict[str, object]:
    legend = _cap_classes(connection)
    total_ige = next((card for card in rows if card["id"] == "total-immunoglobulin-e"), None)
    allergens = [card for card in rows if card is not total_ige]
    tested_on = max((str(card["latest_date"] or "") for card in allergens), default="")

    groups: dict[str, list[dict[str, object]]] = {}
    for card in allergens:
        groups.setdefault(_allergen_family(str(card["name"])), []).append(card)
    ordered_groups = [
        _allergy_group(key, groups[key], legend)
        for key in (
            "tree_pollen", "grass_pollen", "weed_pollen", "mites", "animal_dander",
            "moulds", "foods", "insect_venom", "other",
        )
        if groups.get(key)
    ]
    return {
        "tested": len(allergens),
        "positive": sum(1 for card in allergens if _attends(card)),
        "highest_text": _highest_text(allergens),
        "tested_on": format_date(tested_on or None),
        "classes": legend,
        "scales": _allergy_scales(legend, allergens),
        "groups": ordered_groups,
        "total_ige": total_ige,
    }


def _allergy_scales(legend, allergens: list[dict[str, object]]) -> list[dict[str, object]]:
    """The grading scale(s) the results on the page were actually graded on."""
    from ..allergy import ALEX_CUTOFF, alex_legend

    scales = []
    if any(_is_alex(card) for card in allergens):
        scales.append({"heading": t("allergy.page.scale_alex_title"), "classes": alex_legend(),
                       "lead": t("allergy.alex_lead", cutoff=format_measurement(ALEX_CUTOFF, display_unit("kUA/L")))})
    if legend and any(not _is_alex(card) for card in allergens):
        scales.append({"heading": t("allergy.cap_heading"), "classes": legend, "lead": t("allergy.cap_lead")})
    return scales


# --- blood-pressure renderer ------------------------------------------------

#: The concept each reading of a cuff is filed under.  The cuff's own daily
#: values are already on these concepts' cards (`MEASUREMENT_TWINS`).
_BP_ROLES = {
    "systolic": "systolic-blood-pressure",
    "diastolic": "diastolic-blood-pressure",
    "pulse": "pulse-rate",
}
_BP_ROLE_OF = {concept_id: role for role, concept_id in _BP_ROLES.items()}
_BP_WEEKLY_PREFIX = "weekly-"


def _bp_bands(connection) -> list[dict[str, object]]:
    systolic = {
        str(row["label"]): row
        for row in connection.execute(
            """SELECT label, label_uk, lower_bound, upper_bound FROM curated_reference_rules
               WHERE concept_id='systolic-blood-pressure' ORDER BY COALESCE(lower_bound, -1)"""
        )
    }
    diastolic = {
        str(row["label"]): row
        for row in connection.execute(
            "SELECT label, lower_bound, upper_bound FROM curated_reference_rules WHERE concept_id='diastolic-blood-pressure'"
        )
    }
    bands = []
    for label, row in systolic.items():
        pair = diastolic.get(label)
        bands.append(
            {
                # The key is always the English slug: it selects the band colour
                # in app.css, and a Cyrillic label slugifies to nothing.
                "key": re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_"),
                # Same precedence reference.curated_rules() uses: the curated
                # Ukrainian band label first, the phrase catalogue as fallback.
                "label": str(row["label_uk"])
                if get_locale() == "uk" and row["label_uk"]
                else translate_phrase(label),
                "sys_low": row["lower_bound"],
                "sys_high": row["upper_bound"],
                "dia_low": pair["lower_bound"] if pair else None,
                "dia_high": pair["upper_bound"] if pair else None,
            }
        )
    return bands


def _bp_pick(by_id: dict[str, dict[str, object]], role: str) -> dict[str, object] | None:
    # One card, whether the cuff wrote the reading or a report printed it.
    return by_id.get(_BP_ROLES[role])


def _bp_category(systolic, diastolic) -> tuple[str, str, dict[str, object] | None]:
    """Category label, key and governing verdict for a blood-pressure pair."""
    if not (systolic and diastolic):
        return t("bp.no_reading"), "unjudged", None
    # ESH: the overall category is set by whichever number is worse.
    verdict = min((systolic, diastolic), key=_attention_rank)["verdict"] or {}
    return (
        str(verdict.get("band_label") or verdict.get("label") or ""),
        str(verdict.get("interpretation") or "unjudged"),
        verdict,
    )


def _bp_series(connection, owner_user_id: str, card: dict[str, object] | None) -> list[dict[str, object]]:
    if card is None:
        return []
    if card["series"]:
        return [
            {"date": point["date"], "value": point["value"]}
            for point in card["series"][-CHART_MAX_POINTS:]
        ]
    key = str(card["id"]).removeprefix(_DEVICE_METRIC_PREFIX)
    return [
        {"date": str(row["day"]), "value": float(row["value"])}
        for row in reversed(_downsample(device_metric_values(connection, owner_user_id, key)))
    ]


def _bp_value_text(card: dict[str, object] | None) -> str:
    return card["value_text"] if card else t(_EM_DASH_KEY)


def _bp_block(connection, owner_user_id: str, rows: list[dict[str, object]]) -> dict[str, object]:
    by_id = _by_id(rows)
    systolic, diastolic = _bp_pick(by_id, "systolic"), _bp_pick(by_id, "diastolic")
    pulse = _bp_pick(by_id, "pulse")
    reference = systolic or diastolic
    category_label_text, category_key, verdict = _bp_category(systolic, diastolic)
    weekly = _weekly_blood_pressure(rows)
    return {
        # Every text field falls back to an em dash, which is truthy, so the
        # presence of a reading is stated rather than inferred from the copy.
        "has_reading": bool(systolic or diastolic),
        "systolic_text": _bp_value_text(systolic),
        "diastolic_text": _bp_value_text(diastolic),
        "pulse_text": _bp_value_text(pulse),
        "category_label": category_label_text,
        "category_key": category_key,
        # The governing member's full verdict, so the page can show the same
        # multi-authority disclosure lab analytes get (PANEL-N6).
        "category_verdict": verdict or None,
        "measured_on": format_date(str(reference["latest_date"]) if reference else None),
        "bands": _bp_bands(connection),
        "series": {
            "systolic": _bp_series(connection, owner_user_id, systolic),
            "diastolic": _bp_series(connection, owner_user_id, diastolic),
        },
        "weekly": weekly,
    }


def _weekly_blood_pressure(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """The weekly min/max/count artefacts, read as one range instead of five cards."""
    weekly = {}
    for card in rows:
        identifier = str(card["id"])
        if not identifier.startswith(_BP_WEEKLY_PREFIX):
            continue
        week = str(card["latest_date"] or "")
        entry = weekly.setdefault(
            week,
            {"week": format_date(week or None), "sys_min": None, "sys_max": None,
             "dia_min": None, "dia_max": None, "readings": None},
        )
        for suffix, field in (
            ("systolic-blood-pressure-minimum", "sys_min"),
            ("systolic-blood-pressure-maximum", "sys_max"),
            ("diastolic-blood-pressure-minimum", "dia_min"),
            ("diastolic-blood-pressure-maximum", "dia_max"),
            ("blood-pressure-reading-count", "readings"),
        ):
            if identifier.endswith(suffix):
                entry[field] = card["value_text"]
    return sorted(weekly.values(), key=lambda item: str(item["week"]), reverse=True)


# --- electrocardiograms ------------------------------------------------------


def _ecg_rows(connection, owner_user_id: str) -> list[dict[str, object]]:
    """Every electrocardiogram in the record, newest first.

    A Kardia report is also an imported document, so the two are joined on the
    file they share; an Apple Watch recording has no document behind it and the
    join simply finds nothing.
    """
    return [
        dict(row)
        for row in connection.execute(
            """SELECT de.*, d.id document_id FROM device_events de
               LEFT JOIN documents d
                 ON d.owner_user_id=de.owner_user_id AND d.source_path=de.source_file
               WHERE de.owner_user_id=? AND de.event_type='Electrocardiogram'
               ORDER BY de.started_at DESC""",
            (owner_user_id,),
        )
    ]


def _localized_measurement(value: float, unit: str) -> str:
    """A reading with its unit in the reader's language: `78 уд/хв`, `762 мс`."""
    return f"{format_quantity(value, unit)} {display_unit(unit)}"


def _ecg_card(row: dict[str, object]) -> dict[str, object]:
    """One recording as every list of them shows it."""
    started = str(row["started_at"])
    rate = row["value_numeric"]
    return {
        "id": str(row["id"]),
        "url": f"/devices/ecg/{row['id']}",
        "document_id": row.get("document_id"),
        "source_name": str(row["source_name"]),
        "source_vendor": str(row["source_vendor"]),
        "source_label": human_source_label(str(row["source_vendor"]), str(row["source_name"])),
        "started_at": started,
        "date_text": format_date(started[:10]),
        "time_text": started[11:16],
        "classification": translate_phrase(str(row["value_text"] or "")) or t("ecg.unclassified"),
        "rate_text": _localized_measurement(rate, str(row["unit"] or "bpm")) if rate is not None else t(_EM_DASH_KEY),
    }


def _ecg_measurement(measurement: dict[str, object]) -> dict[str, object]:
    """The measured statistics, formatted, with every gap left visible.

    A statistic the recording cannot support is `None` in the measurement and
    stays absent here rather than arriving as a dash that reads like a value.
    """

    def quantity(key: str, unit: str) -> str | None:
        value = measurement.get(key)
        return _localized_measurement(float(value), unit) if value is not None else None

    return {
        "heart_rate": quantity("heart_rate", "bpm"),
        "heart_rate_min": quantity("heart_rate_min", "bpm"),
        "heart_rate_max": quantity("heart_rate_max", "bpm"),
        "rr_mean": quantity("rr_mean_ms", "ms"),
        "sdnn": quantity("sdnn_ms", "ms"),
        "rmssd": quantity("rmssd_ms", "ms"),
        "beats": format_count(measurement.get("beats")),
        "lead": measurement.get("lead"),
        "excluded": int(measurement.get("excluded_intervals") or 0),
        "excluded_text": format_count(measurement.get("excluded_intervals")),
        "intervals_text": format_count(len(measurement.get("rr_intervals") or [])),
    }


# --- charts -----------------------------------------------------------------


def _downsample(rows: list[dict[str, object]], limit: int = CHART_MAX_POINTS) -> list[dict[str, object]]:
    """Bucket a long daily series so the chart is a line, not a blob.

    2,857 daily points drawn as 2,857 circles is an unreadable solid band and
    a 300 kB payload; the bucket mean keeps the shape and the axis honest.
    """
    if len(rows) <= limit:
        return rows
    size = math.ceil(len(rows) / limit)
    bucketed = []
    for index in range(0, len(rows), size):
        chunk = rows[index : index + size]
        values = [float(row["value"]) for row in chunk]
        middle = dict(chunk[len(chunk) // 2])
        middle["value"] = sum(values) / len(values)
        middle["value_min"] = min(float(row["value_min"] or row["value"]) for row in chunk)
        middle["value_max"] = max(float(row["value_max"] or row["value"]) for row in chunk)
        middle["sample_count"] = sum(int(row["sample_count"] or 0) for row in chunk)
        middle["bucket_days"] = len(chunk)
        bucketed.append(middle)
    return bucketed


def _finding_catalog(connection, owner_user_id: str) -> list[dict[str, object]]:
    def build() -> list[dict[str, object]]:
        rows = connection.execute(
            # A finding whose report printed no study date takes the
            # document's date; «Date unknown» beside a dated report was wrong.
            """SELECT f.*, COALESCE(f.finding_date, d.report_date) shown_date,
                             d.title document_title, d.original_filename,
                             COALESCE(v.canonical_name, 'Unknown provider') vendor
               FROM clinical_findings f
               JOIN documents d ON d.id=f.document_id
               LEFT JOIN vendors v ON v.id=f.vendor_id
               WHERE f.owner_user_id=? AND f.verification_status <> 'rejected'
                 AND d.duplicate_of_document_id IS NULL
               ORDER BY COALESCE(f.finding_date, d.report_date, d.imported_at) DESC, f.created_at DESC""",
            (owner_user_id,),
        ).fetchall()
        seen: set[tuple[object, ...]] = set()
        findings: list[dict[str, object]] = []
        for raw in rows:
            row = dict(raw)
            row["finding_date"] = row.pop("shown_date")
            key = (row["document_id"], row["page_number"], row["health_area"], row["title"], row["summary_en"], row["finding_date"])
            if key in seen:
                continue
            seen.add(key)
            vendor = row["vendor"]
            row["vendor"] = (
                t(_UNKNOWN_PROVIDER_KEY)
                if vendor in {_UNKNOWN_PROVIDER, _UNKNOWN_VENDOR}
                else translate_phrase(str(vendor))
            )
            # Before the English column is run through the phrase catalogue:
            # the display text must know which language the source wrote in.
            row.update(present_finding(row))
            row["title"] = translate_phrase(str(row["title"]))
            row["summary_en"] = translate_phrase(str(row["summary_en"]))
            row["date_text"] = format_date(str(row["finding_date"] or "") or None)
            findings.append(row)
        return findings

    return _cached(("findings", owner_user_id), build)


def _chart_band(verdict: dict[str, object]) -> dict[str, object] | None:
    """The interval the trend chart shades: the band the reader should be IN.

    Shading the tier the value matched drew an out-of-range series inside the
    shaded region, reading as reassurance; the target band keeps the chart
    agreeing with the range bar (`reference.py:_verdict`).
    """
    low = verdict.get("target_low", verdict.get("low"))
    high = verdict.get("target_high", verdict.get("high"))
    if low is None and high is None:
        return None
    label = (
        verdict.get("band_label")
        if verdict.get("target_is_matched_band", True)
        else verdict.get("target_range_text")
    )
    return {"low": low, "high": high, "label": label or verdict.get("range_text") or ""}


def _row_display_unit(row: dict[str, object]) -> str | None:
    """The unit one deduped row's number is actually in.

    After `_in_preferred_unit` the ROW's `preferred_unit` is either the unit
    the value was converted into or the printed unit it kept; the concept's
    own `preferred_unit` is only an aspiration and must never relabel a
    number that could not be converted into it.
    """
    source = (
        (row["preferred_unit"] or row["unit_raw"])
        if row["value_numeric"] is not None
        else row["unit_raw"]
    )
    return str(source) if source else None


def _comparison_bounds(row: dict[str, object], age, sex: str | None, unit_source: str | None) -> tuple:
    """The printed interval at sampling age, in the unit the value is shown in."""
    low, high, _ = _vendor_bounds(row, age, sex)
    # General reference parsing accepts a standalone "Adults" interval as
    # unqualified. Historical readings cannot assume the sample was adult;
    # a matched child band in a multi-population block remains usable.
    reference = str(row.get("vendor_reference_text") or "")
    if (age is None or age < 18) and re.search(r"доросл|adult", reference, re.I):
        if applicable_band(reference, age, sex) is None:
            low, high = None, None
    # Stored numeric bounds already travelled with the converted value, but
    # a newly recovered interval is still in the source text's printed unit.
    if row.get("converted_from") and row.get("vendor_reference_low") is None and row.get("vendor_reference_high") is None:
        low, high = (
            convert_value(bound, str(row["converted_from"]), str(unit_source), str(row["concept_id"]))
            if bound is not None else None for bound in (low, high)
        )
    return low, high


def _comparison_status(row: dict[str, object], low, high) -> tuple[object, str]:
    """(status, basis): the laboratory's own flag, else the value set against its interval."""
    reading_status = row["vendor_interpretation"]
    comparison_basis = "stored_flag" if reading_status else "none"
    if not reading_status and row.get("value_numeric") is not None and (low is not None or high is not None):
        value = float(row["value_numeric"])
        if high is not None and value > high:
            reading_status = "high"
        elif low is not None and value < low:
            reading_status = "low"
        else:
            reading_status = "within_vendor_range"
        comparison_basis = "original_range"
    return reading_status, comparison_basis


def _original_comparison(
    row: dict[str, object], *, date_of_birth: str | None = None,
    sex: str | None = None, unit_source: str | None = None,
) -> dict[str, object]:
    """A display-only comparison shared by history and chart, never a stored flag."""
    unit_source = unit_source or _row_display_unit(row)
    unit = display_unit(unit_source)
    # A report is compared at sampling age, never against the latest target band.
    age = age_on(date_of_birth, str(row.get("observed_at") or "unknown"))
    if age is not None and age < 0:
        age = None
    low, high = _comparison_bounds(row, age, sex, unit_source)
    reading_status, comparison_basis = _comparison_status(row, low, high)
    reference_text = range_text(low, high, unit) if low is not None or high is not None else None
    return {
        "status": reading_status or "information",
        "status_label": status_label(reading_status),
        "comparison_basis": comparison_basis,
        "comparison_label": t("chart.comparison_" + comparison_basis) if comparison_basis != "none" else None,
        "reference_low": low,
        "reference_high": high,
        "reference_text": reference_text,
        "reference_label": t("chart.original_interval", interval=reference_text) if reference_text else None,
        "age_at_observation": age,
    }


def _chart_number(row: dict[str, object], unit: str | None) -> str:
    """A point's printed number: as the report printed it, or a device day at its unit's precision."""
    if row.get("is_device"):
        return format_quantity(row["value_numeric"], unit)
    return format_measured(row["value_numeric"], unit)


def _chart_payload(
    values: list[dict[str, object]], preferred_unit: str | None,
    *, date_of_birth: str | None = None, sex: str | None = None, connection=None,
) -> list[dict[str, object]]:
    """One point per day, each coloured by its own verdict.

    With a ``connection`` every point is judged by `_reading_verdict` at the
    age the sample was taken -- the same path as the hero and /changes -- so a
    critically high 8.1 is never drawn grey because its report printed no
    flag (the old colour was the laboratory's flag alone).
    """
    daily = [
        row
        for row in reversed(_one_per_day(values))
        if row["value_numeric"] is not None and row["observed_at"]
    ]
    if not daily:
        return []
    # One axis, one unit: the unit the newest reading is in — the same one the
    # hero value shows.  A reading `_in_preferred_unit` could not convert into
    # it stays off the shared axis rather than being plotted as a number it is
    # not; the history table still lists it in its own unit.
    series_unit = _row_display_unit(daily[-1]) or preferred_unit
    unit = display_unit(series_unit)
    return [
        _chart_point(row, series_unit, unit, date_of_birth=date_of_birth, sex=sex, connection=connection)
        for row in daily
        if canonical_unit(str(_row_display_unit(row) or "")) == canonical_unit(str(series_unit or ""))
    ]


def _chart_point(
    row: dict[str, object], series_unit: str | None, unit: str | None,
    *, date_of_birth: str | None, sex: str | None, connection,
) -> dict[str, object]:
    """One drawn point of `_chart_payload`, judged when there is a ``connection``."""
    comparison = _original_comparison(row, date_of_birth=date_of_birth, sex=sex, unit_source=series_unit)
    judged = {}
    if connection is not None:
        _, verdict = _reading_verdict(
            connection, str(row["concept_id"]), row, comparison["age_at_observation"], sex
        )
        judged = {
            "state": verdict_state(verdict),
            "verdict_label": str(verdict.get("label") or ""),
            "value_text": precise_at_edges(row["value_numeric"], _chart_number(row, unit), verdict),
        }
    return {
        "id": row["id"],
        "date": row["observed_at"],
        "value": row["value_numeric"],
        "value_text": _chart_number(row, unit),
        "unit": unit,
        "vendor": (
            t(_UNKNOWN_PROVIDER_KEY)
            if row["vendor"] in {_UNKNOWN_PROVIDER, _UNKNOWN_VENDOR}
            else translate_phrase(str(row["vendor"]))
        ),
        **{key: value for key, value in comparison.items() if key != "age_at_observation"},
        # A device day has no page of its own; it opens its sources.
        "document_url": row.get("device_url") or f"/documents/{row['document_id']}#observation-{row['id']}",
        "link_label": t("twin.compare_sources") if row.get("is_device") else t("chart.open_evidence"),
        # Which path the reading came by, in words: the marker shape
        # says it too, but never on its own.
        "source": "device" if row.get("is_device") else "clinic",
        "source_text": t("twin.source_device") if row.get("is_device") else t("twin.source_clinic"),
        "line": "main",
        "source_count": row["evidence_count"],
        "same_day_count": int(row.get("same_day_count") or 1),
        **judged,
    }


# --- correlations -----------------------------------------------------------
#
# "Does anything I do move this number?" is the question a single trend line
# cannot answer.  Everything below reduces the record's two series stores --
# daily device aggregates and dated laboratory draws -- to the one shape
# `correlation.py` reads: `(day, value)`, one per day, ascending, in the unit
# the rest of the interface prints.

#: Offered without being asked for, on every detail page that has a series:
#: behaviours and vital signs a person can act on.  Everything else this owner
#: records is still one selection away in the explorer's picker.
CORRELATION_CANDIDATE_KEYS = (
    "steps", "exercise_minutes", "active_energy", "sleep_duration", "time_in_bed",
    "resting_heart_rate", "heart_rate_variability", "daily_heart_rate", "blood_oxygen",
    "respiratory_rate", "body_weight", "sleeping_wrist_temperature",
    "systolic_blood_pressure", "diastolic_blood_pressure", "time_in_daylight",
    "sleep_efficiency", "breathing_disturbance_index", "readiness_score", "stress_high_time",
)

#: Explorer windows, counted back from the primary series' own newest day --
#: never from today, so a record whose sync stopped in March still describes
#: the year that was actually measured.
CORRELATION_RANGES = {"90": 90, "365": 365, "all": None}

#: Two readings is the least a metric can bring to a comparison — one is a dot
#: with nothing to move against.  These floors used to sit at 30/6 back when a
#: chart refused to draw below the coefficient minimum; now that the curves are
#: drawn regardless and only the coefficient is gated (six pairs), a three-draw
#: serum iron against a year of sleep is exactly the comparison the feature
#: exists for, and a floor that hides it hides the point.
CORRELATION_PICKER_DEVICE_DAYS = 2
CORRELATION_PICKER_LAB_DAYS = 2
#: What the primary itself must carry before the section renders at all.  A
#: single-draw allergy panel gets no correlation section, by design.
CORRELATION_MIN_PRIMARY_DEVICE_DAYS = 2
CORRELATION_MIN_PRIMARY_LAB_DAYS = 2
#: How many paired days a companion needs before the page puts it forward
#: unasked. Six is enough to draw and read; a suggestion the reader did not ask
#: for should be standing on more than that.
CORRELATION_MIN_SHARED_DRAWS = 8

#: How many companions one chart carries. Four is where the distinct colour and
#: dash-pattern slots run out, and past that a normalised overlay is a thicket.
CORRELATION_MAX_COMPANIONS = 4


def _device_day_series(connection, owner_user_id: str, metric_key: str) -> dict[str, object] | None:
    """One device metric as a dated series, deduplicated across its sources.

    Always through `device_metric_values`: read straight from
    `device_metric_days`, a day carried by both the Watch and the Oura ring
    appears twice and the same day pairs with itself.
    """
    rows = device_metric_values(connection, owner_user_id, metric_key)
    if not rows:
        return None
    latest = rows[0]
    return {
        "name": translate_phrase(str(latest["metric_name"])),
        "unit": display_unit(str(latest["unit"]) if latest["unit"] else None),
        "series": sorted((str(row["day"]), float(row["value"])) for row in rows),
    }


def _correlation_device_options(connection, owner_user_id: str) -> list[dict[str, object]]:
    """What device metrics exist and how many days each has run."""
    return [
        {
            "key": str(row["metric_key"]),
            "name": translate_phrase(str(row["metric_name"])),
            "category": str(row["category"]),
            "days": int(row["days"]),
        }
        for row in connection.execute(
            """SELECT metric_key, MIN(metric_name) metric_name, MIN(category) category,
                          COUNT(DISTINCT day) days
                   FROM device_metric_days WHERE owner_user_id=? GROUP BY metric_key""",
            (owner_user_id,),
        )
        # Offered once, under its concept, whose series already carries it.
        if str(row["metric_key"]) not in SAME_DEVICE_KEYS
    ]


def _correlation_candidates(
    connection, owner_user_id: str, device_options: list[dict[str, object]]
) -> dict[str, dict[str, object]]:
    """The suggestion candidates' full series, for those this owner records."""
    present = {option["key"] for option in device_options}
    candidates: dict[str, dict[str, object]] = {}
    for key in CORRELATION_CANDIDATE_KEYS:
        if key not in present:
            continue
        resolved = _device_day_series(connection, owner_user_id, key)
        if resolved:
            candidates[f"device:{key}"] = resolved
    return candidates


def _correlation_lab_series(connection, owner_user_id: str) -> dict[str, dict[str, object]]:
    """Every laboratory analyte the record can plot, one value per day."""
    # One deduplicating pass for the whole record rather than one per
    # analyte: the window function in `_deduped_observation_rows` is the
    # expensive part and it costs the same for 1 concept as for 565.
    concepts = {
        str(row["id"]): (str(row["canonical_name"]), row["preferred_unit"])
        for row in connection.execute("SELECT id, canonical_name, preferred_unit FROM concepts")
    }
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in _linked_observation_rows(connection, owner_user_id):
        if row["value_numeric"] is None or not row["observed_at"]:
            continue
        grouped.setdefault(str(row["concept_id"]), []).append(row)
    labs: dict[str, dict[str, object]] = {}
    for concept_id, rows in grouped.items():
        name, unit = concepts.get(concept_id, ("", None))
        if concept_id in DISPLAY_SUPPRESSED or not _displayable_metric(name):
            continue
        by_day: dict[str, float] = {}
        # `_one_per_day` returns newest first and keys on the full
        # timestamp, so `setdefault` on the date part keeps the day's
        # most recent reading when a report printed two.
        for row in _one_per_day(rows):
            by_day.setdefault(str(row["observed_at"])[:10], float(row["value_numeric"]))
        labs[concept_id] = {
            "name": concept_display_name(name),
            "unit": display_unit(unit),
            "series": sorted(by_day.items()),
        }
    return labs


def _correlation_index(connection, owner_user_id: str) -> dict[str, object]:
    """Everything the section needs except the primary series, in one memo slot.

    `_MEMO` holds eight entries and clears the lot when it overflows, so four
    caches here would evict the metric catalog on every page load.  One entry
    carries all three reads: what device metrics exist and how long each has
    run, the suggestion candidates' full series, and every laboratory analyte
    the record can plot.
    """

    def build() -> dict[str, object]:
        device_options = _correlation_device_options(connection, owner_user_id)
        candidates = _correlation_candidates(connection, owner_user_id, device_options)
        labs = _correlation_lab_series(connection, owner_user_id)
        return {"device_options": device_options, "candidates": candidates, "labs": labs}

    return _memoised(connection, owner_user_id, "correlation", build)


def _correlation_metric(connection, owner_user_id: str, metric_id: str) -> dict[str, object] | None:
    """Resolve a catalog id — `device:<key>` or a bare concept id — to a series."""
    index = _correlation_index(connection, owner_user_id)
    if metric_id.startswith(_DEVICE_METRIC_PREFIX):
        found = index["candidates"].get(metric_id)
        return found or _device_day_series(connection, owner_user_id, metric_id.removeprefix(_DEVICE_METRIC_PREFIX))
    return index["labs"].get(metric_id)


def _correlation_window(series: list[tuple[str, float]], range_key: str) -> list[tuple[str, float]]:
    """The last N days of a series, counted from its own newest day.

    Never from today: a record whose sync stopped in March would otherwise
    report "no data in the last 90 days" about a year that was measured.
    """
    window = CORRELATION_RANGES[range_key]
    if not window or not series:
        return list(series)
    cutoff = (date.fromisoformat(series[-1][0]) - timedelta(days=window - 1)).isoformat()
    return [item for item in series if item[0] >= cutoff]


def _drawn_series(
    series: list[tuple[str, float]], window: int | None, period: dict[str, str] | None
) -> tuple[list[dict[str, object]], str | None]:
    """One series ready to plot: smoothed if asked, clipped, thinned.

    The rolling mean is taken over the *whole* series and clipped afterwards.
    Clipping first would leave the left-hand edge of every averaged curve
    computed from the two or three days that happened to survive the clip, so
    a 30-day mean would open each chart with a spike that is an artefact of
    where the window starts.

    Clipping to the primary's own drawn span is what stops a companion with a
    decade of history from stretching the time axis past the readings the page
    is actually about.
    """
    values = rolling_mean_series(series, window) if window else series
    if period:
        values = [item for item in values if period["from"] <= item[0] <= period["to"]]
    drawn = sample_evenly(values)
    note = (
        t_plural(
            "corr.sampled",
            len(values),
            shown=format_count(len(drawn)),
            total=format_count(len(values)),
        )
        if len(drawn) < len(values)
        else None
    )
    return [{"day": day, "value": value} for day, value in drawn], note


def _correlation_companion_block(
    companion_id: str,
    companion: dict[str, object],
    windowed: list[tuple[str, float]],
    align: str,
    smoothed: str | None,
    window: int | None,
    period: dict[str, str] | None,
    single: bool,
) -> dict[str, object]:
    """One companion's curve and, when enough days pair, its coefficient."""
    pairs = align_pairs(windowed, companion["series"], align)
    summary = correlate(pairs)
    thin = len(pairs) < MIN_PAIRS_EXPLORER
    points, note = _drawn_series(
        companion["series"], window if smoothed else None, period
    )
    return {
        "id": companion_id,
        "name": companion["name"],
        "unit": companion["unit"],
        "smoothed": smoothed,
        "series": points,
        "n": summary["n"],
        # Below the floor no coefficient is reported at all, rather
        # than a number the reader would have to know to distrust.
        "r": None if thin else summary["r"],
        "strength": "none" if thin else summary["strength"],
        "direction": "none" if thin else summary["direction"],
        "insufficient": thin,
        # Ukrainian selects between three plural forms, which no flat
        # string table handed to the browser can do — so every counted
        # phrase is resolved here, in the request's own locale.
        "labels": {
            "days": t_plural("corr.days", summary["n"], value=format_count(summary["n"])),
            "sampled": note,
        },
        # The scatter plots one companion against the primary; with
        # several selected there is no single pair of axes to plot on.
        "pairs": (
            [
                {"day": day, "a": first, "b": second}
                for day, first, second in sample_evenly(pairs)
            ]
            if single
            else None
        ),
        "regression": regression(pairs) if single and not thin else None,
    }


def _correlation_payload(
    primary_id: str,
    primary: dict[str, object],
    companions: list[tuple[str, dict[str, object]]],
    align: str,
    range_key: str,
) -> dict[str, object]:
    """The contract `/api/correlation` returns, and the page's opening state.

    Up to four companions travel together, because the question is "does
    anything move with this" and answering it one metric at a time is what
    made the first version feel like a lab report viewer.

    Two things are kept apart here. The *coefficient* is computed from the
    aligned pairs and never from anything drawn, so thinning and smoothing
    cannot flatter it. The *curves* are drawn whenever there is data, even
    when there are too few overlapping days to report a coefficient — seeing
    four iron results laid over a year of sleep is worth something, and
    replacing it with a refusal message was the single loudest complaint about
    the first version.
    """
    windowed = _correlation_window(primary["series"], range_key)
    period = {"from": windowed[0][0], "to": windowed[-1][0]} if windowed else None
    window = CORRELATION_WINDOW_DAYS.get(align)

    # Which side gets averaged is decided per companion, so a page can be the
    # sparse side of one comparison and the dense side of another.  The primary
    # is drawn smoothed when it was averaged for any of them: that curve is
    # what those coefficients were computed against, and it is the shape the
    # reader is being asked to compare.
    # ponytail: one smoothed/raw decision for a primary that is averaged for
    # some companions and anchored for others. Per-companion primary curves
    # would be strictly truer and four overlapping copies of the same metric
    # strictly less readable; revisit if a real record makes the mix common.
    sides = {
        companion_id: averaged_side(windowed, companion["series"], align)
        for companion_id, companion in companions
    }
    primary_averaged = any(side == "primary" for side in sides.values())
    series, sampled = _drawn_series(windowed, window if primary_averaged else None, period)

    single = len(companions) == 1
    blocks = [
        _correlation_companion_block(
            companion_id, companion, windowed, align,
            align if sides[companion_id] == "companion" else None, window, period, single,
        )
        for companion_id, companion in companions
    ]
    return {
        "a": {
            "id": primary_id,
            "name": primary["name"],
            "unit": primary["unit"],
            "smoothed": align if primary_averaged else None,
            "series": series,
            "sampled": sampled,
        },
        "companions": blocks,
        "align": align,
        "range": range_key,
        "period": period,
    }


def _correlation_groups(index: dict[str, object], primary_id: str) -> list[dict[str, object]]:
    """Picker options, grouped the way the devices pages already group them."""
    by_category: dict[str, list[dict[str, str]]] = {}
    for option in index["device_options"]:
        metric_id = f"device:{option['key']}"
        if metric_id == primary_id or option["days"] < CORRELATION_PICKER_DEVICE_DAYS:
            continue
        by_category.setdefault(option["category"], []).append(
            {"id": metric_id, "name": option["name"]}
        )
    groups = [
        {
            "label": translate_phrase(DEVICE_CATEGORY_LABELS.get(category, "Device data")),
            "options": sorted(options, key=lambda option: option["name"]),
        }
        for category, options in by_category.items()
    ]
    groups.sort(key=lambda group: group["label"])
    labs = sorted(
        (
            {"id": concept_id, "name": str(entry["name"])}
            for concept_id, entry in index["labs"].items()
            if concept_id != primary_id and len(entry["series"]) >= CORRELATION_PICKER_LAB_DAYS
        ),
        key=lambda option: option["name"],
    )
    if labs:
        groups.append({"label": t("corr.group_labs"), "options": labs})
    return groups


#: Built sections by (owner, locale, primary), each beside the data fingerprint
#: it was computed from.  Ranking the suggestions costs ~200 ms a page view and
#: answers the same until the record changes.  Its own dict, not `_MEMO`: that
#: one holds eight entries and clears wholesale, so a slot per metric page
#: would evict the catalog on every visit.  ponytail: cleared whole at 128
#: entries; an LRU only if people browse more metrics than that between edits.
_CORRELATION_MEMO: dict[tuple[str, str, str], tuple[tuple, dict[str, object] | None]] = {}


def _twin_concept_id(metric_id: str) -> str:
    """A same-measurement device id read as its concept's id; anything else unchanged."""
    twin = TWIN_OF_DEVICE.get(metric_id.removeprefix(_DEVICE_METRIC_PREFIX))
    if metric_id.startswith(_DEVICE_METRIC_PREFIX) and twin and twin[1] == "same":
        return twin[0]
    return metric_id


def _correlation_context(connection, owner_user_id: str, primary_id: str) -> dict[str, object] | None:
    primary_id = _twin_concept_id(primary_id)
    key = (owner_user_id, get_locale(), primary_id)
    fingerprint = _fingerprint(connection, owner_user_id)
    entry = _CORRELATION_MEMO.get(key)
    if entry is not None and entry[0] == fingerprint:
        return entry[1]
    section = _build_correlation_context(connection, owner_user_id, primary_id)
    if len(_CORRELATION_MEMO) >= 128:
        _CORRELATION_MEMO.clear()
    _CORRELATION_MEMO[key] = (fingerprint, section)
    return section


def _correlation_lab_pools(
    labs: dict[str, dict[str, object]], primary_id: str, is_device: bool, windowed: list[tuple[str, float]]
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    """(analytes sharing draws with a laboratory primary, analytes a wearable primary may meet)."""
    siblings: dict[str, dict[str, object]] = {}
    if is_device:
        lab_pool = {
            concept_id: entry
            for concept_id, entry in labs.items()
            if len(entry["series"]) >= CORRELATION_PICKER_LAB_DAYS
            and not concept_id.startswith("weekly-")
        }
        return siblings, lab_pool
    primary_days = {day for day, _ in windowed}
    for concept_id, entry in labs.items():
        if concept_id == primary_id or concept_id.startswith("weekly-"):
            continue
        shared = sum(1 for day, _ in entry["series"] if day in primary_days)
        if shared >= MIN_PAIRS_EXPLORER:
            siblings[concept_id] = entry
    return siblings, {}


def _correlation_ranked_by_pool(
    primary_id: str, windows: dict[str, list[tuple[str, float]]], pools, **limits
) -> list[list[tuple[dict[str, object], str, str]]]:
    """One strongest-first queue per pool, each carrying align and period.

    Defaults to the bar a *suggestion* has to clear; the opening-chart
    fallback lowers it to the bar the explorer will draw at.
    """
    limits.setdefault("min_pairs", CORRELATION_MIN_SHARED_DRAWS)
    return [
        [
            (found, used, period)
            for found in suggest(
                primary_id,
                windows[period],
                {key: value["series"] for key, value in pool.items()},
                used,
                **limits,
            )
        ]
        for used, pool, period in pools
    ]


def _correlation_strength_order(item: tuple[dict[str, object], str, str]) -> tuple[float, str]:
    return (-abs(float(item[0]["r"])), str(item[0]["id"]))


def _correlation_weakest_opening(
    primary_id: str, windows: dict[str, list[tuple[str, float]]], pools
) -> tuple[dict[str, object], str, str] | None:
    """The strongest pairing the explorer would draw, however weak, or None."""
    ranked = sorted(
        (
            found
            for queue in _correlation_ranked_by_pool(
                primary_id, windows, pools, min_pairs=MIN_PAIRS_EXPLORER, min_abs_r=0.0, top=1
            )
            for found in queue
        ),
        key=_correlation_strength_order,
    )
    return next(iter(ranked), None)


def _correlation_shortlist(
    queues: list[list[tuple[dict[str, object], str, str]]], offered: dict[str, dict[str, object]]
) -> list[tuple[dict[str, object], str, str]]:
    """Up to five suggestions taken round-robin across pools, one per displayed name."""
    seen: set[str] = set()
    shortlist: list[tuple[dict[str, object], str, str]] = []
    while len(shortlist) < 5 and any(queues):
        for queue in queues:
            if not queue or len(shortlist) == 5:
                continue
            found, used, period = queue.pop(0)
            name = str(offered[str(found["id"])]["name"])
            if name in seen:
                continue
            seen.add(name)
            shortlist.append((found, used, period))
    # Mixed by pool, but still read strongest first, because that is what the
    # heading above them promises.
    shortlist.sort(key=_correlation_strength_order)
    return shortlist


def _correlation_suggestion(
    found: dict[str, object], used: str, period: str, companion: dict[str, object], primary_name: object
) -> dict[str, object]:
    """One suggestion card."""
    reading = float(found["r"])
    return {
        **found,
        "name": companion["name"],
        # Carried on the card: clicking it has to select the alignment
        # and the period the number was actually computed under, or the
        # chart it opens disagrees with the card that opened it.
        "align": used,
        "range": period,
        "r_text": format_number_localized(reading, 2),
        "strength_label": t(f"corr.strength_{found['strength']}"),
        "days_text": t_plural(
            "corr.days", int(found["n"]), value=format_count(int(found["n"]))
        ),
        "sentence": t(
            "corr.sentence_same" if reading > 0 else "corr.sentence_opposite",
            a=primary_name,
            b=companion["name"],
            strength=t(f"corr.strength_{found['strength']}"),
        ),
    }


def _build_correlation_context(connection, owner_user_id: str, primary_id: str) -> dict[str, object] | None:
    """The whole section, or `None` when this metric has nothing to relate.

    A page that cannot say anything useful says nothing: no empty panel, no
    picker over a single reading, no "not enough data" where the honest answer
    is that this measurement was taken once.
    """
    primary = _correlation_metric(connection, owner_user_id, primary_id)
    # A concept carrying a scale's or a cuff's daily values is read as the
    # daily series it mostly is.
    is_device = primary_id.startswith(_DEVICE_METRIC_PREFIX) or primary_id in SAME_TWIN_CONCEPTS
    floor = CORRELATION_MIN_PRIMARY_DEVICE_DAYS if is_device else CORRELATION_MIN_PRIMARY_LAB_DAYS
    if primary is None or len(primary["series"]) < floor:
        return None
    index = _correlation_index(connection, owner_user_id)
    groups = _correlation_groups(index, primary_id)
    if not groups:
        return None

    # A wearable records daily, so "same day" is a real comparison. A blood
    # draw is a point in a quarter, and the thing that could have moved it is
    # the week that came before it — not whatever the watch logged that morning.
    align = "same_day" if is_device else "avg7"
    # A daily wearable series opens on the last year rather than on a decade of
    # smear. A sparse one does not: the electrocardiogram has nine readings over
    # five years, one of them inside its own last twelve months, so a 365-day
    # default opened the panel on a window that could not be compared with
    # anything.
    range_key = (
        "365"
        if is_device and len(_correlation_window(primary["series"], "365")) >= MIN_PAIRS_EXPLORER
        else "all"
    )

    candidates = {key: value for key, value in index["candidates"].items() if key != primary_id}
    # Suggestions are measured over the window the explorer opens on, so the
    # day count on a card is the same number the chart under it reports. Read
    # over the whole record instead, a card offering "2,856 days" opened a
    # chart headed "308 days" and neither number explained the other.
    windowed = _correlation_window(primary["series"], range_key)

    # Laboratory companions reach the page by two different questions, so they
    # are asked two different ways.
    #
    # From another analyte: two results from one tube are compared on the day
    # they were drawn. A companion recorded only on those same dates has one
    # day in its own 7-day window, so `avg7` would drop every pair and a CBC
    # would silently relate to nothing in the CBC. The pool is everything
    # sharing enough draws for the *explorer*, not for a suggestion — `suggest`
    # below applies the higher bar to the cards, and pre-filtering at that bar
    # left a six-draw lipid panel with no opening comparison at all when its
    # own HDL and triglycerides came from the same six tubes.
    #
    # From a wearable: "does the month before a blood test show up in it".
    # `avg30` anchors on the analyte's draw dates and averages the device side,
    # which is the whole point of the re-orientation in `align_pairs` — asked
    # the other way round, a blood-pressure page could offer nothing but other
    # blood-pressure readings.
    #
    # A `weekly-` concept is a minimum, maximum or count computed over readings
    # the record already holds separately, so correlating against one measures
    # the arithmetic that produced it — and "weekly blood pressure reading
    # count" is how often a cuff was used, not a measurement of the person at
    # all. `_attention_cards` withholds the same family for the same reason.
    # They stay in the picker, like every other trivial pair: withheld from what
    # the page says on its own, never made unreachable.
    siblings, lab_pool = _correlation_lab_pools(index["labs"], primary_id, is_device, windowed)
    # Each pool is asked over the period that pool can actually answer in. A
    # wearable page opens on the last year, which is right for the wearable
    # metrics beside it and fatal for the laboratory ones: a year of a device
    # series holds two or three blood draws, so "blood pressure against the
    # lipid panel" could never clear the suggestion bar and the page went on
    # offering nothing but other wearable metrics. The laboratory pool is
    # measured over the whole record, and the card carries that period with it.
    pools = (
        (align, candidates, range_key),
        ("same_day", siblings, range_key),
        ("avg30", lab_pool, "all"),
    )
    #: Every series a suggestion can come from, by id, whichever pool found it.
    offered = {**candidates, **siblings, **lab_pool}
    windows = {key: _correlation_window(primary["series"], key) for key in {range_key, "all"}}

    # Taken a pool at a time rather than off one ranked list. With nine paired
    # days a coefficient of 0.6 is easy to reach by chance, so ranking on
    # magnitude alone let five nine-day laboratory pairings push every
    # three-hundred-day wearable one off the resting-heart-rate page entirely.
    # Round-robin keeps both kinds of finding in front of the reader without
    # inventing a significance test to weigh them against each other, and every
    # card prints the day count it stands on.
    #
    # One name, one card, too: two series the reader cannot tell apart by name
    # (a same-measurement twin is already one series, `MEASUREMENT_TWINS`)
    # would print the same heading over two coefficients.
    shortlist = _correlation_shortlist(_correlation_ranked_by_pool(primary_id, windows, pools), offered)

    suggestions = [
        _correlation_suggestion(found, used, period, offered[str(found["id"])], primary["name"])
        for found, used, period in shortlist
    ]
    # Nothing cleared the suggestion bar is not the same as nothing to draw.
    # Without this the picker's first alphabetical option opened the panel, and
    # on ten of the twelve metrics with no suggestion that was a companion with
    # too little overlap: a section whose entire opening state was "not enough
    # data" over a record that had plenty. The weakest honest comparison beats
    # that, and the sentence under the chart still calls it negligible.
    opening = shortlist[0] if shortlist else _correlation_weakest_opening(primary_id, windows, pools)
    initial = None
    if opening is not None:
        found, used, period = opening
        top = str(found["id"])
        initial = _correlation_payload(primary_id, primary, [(top, offered[top])], used, period)
    section = {
        "primary": {"id": primary_id, "name": primary["name"], "unit": primary["unit"]},
        "suggestions": suggestions,
        "groups": groups,
        "defaults": {"align": align, "range": range_key},
        "initial": initial,
    }
    # The chart paints from this on first render rather than after a round
    # trip, so the panel never opens empty and then jumps.  The suggestion
    # cards and the picker are server-rendered markup, so they stay out of it.
    # Serialized by |tojson in the template, never json.dumps + |safe: metric
    # names come from parsed documents, and tojson escapes the "</script>" a
    # hostile analyte name could smuggle into the inline block.
    section["boot"] = {key: section[key] for key in ("primary", "defaults", "initial")}
    return section


def _known_vendors(connection) -> list[str]:
    """Providers already in the record, for the classify form's type-ahead."""
    return [
        str(item["canonical_name"])
        for item in connection.execute(
            "SELECT canonical_name FROM vendors ORDER BY canonical_name"
        )
        if str(item["canonical_name"]) not in {_UNKNOWN_VENDOR, "Multiple vendors"}
    ]


def _document_kinds() -> list[dict[str, str]]:
    """Every kind a document may be named, in the reader's language and order.

    Shared by the document page and the review queue: two copies of this list
    would be one edit away from the two pages offering different answers, and
    the POST validates against the same dict either way.
    """
    return [
        {"key": key, "label": translate_phrase(title)}
        for key, title in sorted(
            DOCUMENT_TYPE_TITLES.items(), key=lambda pair: translate_phrase(pair[1])
        )
    ]


def _observation_unit_source(row: dict[str, object], shown: dict[str, object], numeric: bool):
    if numeric:
        return shown["unit_raw"]
    # A word has no unit: "Not detected mg/dL" is a parser's column
    # header, not a measurement.  "0-1 in HPF" keeps its own.
    text_value = str(row["value_text"] or "")
    return row["unit_raw"] if any(ch.isdigit() for ch in text_value) else None


def _sorted_observation_rows(rows: list) -> list:
    # In the order the document prints them: page, then where on the page
    # (`store_positions`).  Alphabetical within a page put the first row of an
    # Esculab report last, and a list that does not follow the page beside it
    # cannot be checked against it.  A Garmin export reads one week, then its
    # five values: the five share the week's printed line and keep the order
    # they were read in.
    #
    # Position is trusted only on a page where every row was placed.  On an
    # OCR page that placed one row of three, sorting by it put the placed
    # calcium above the unplaced potassium and sodium printed before it; the
    # parse order is the printed order there.
    placed_pages = {
        page
        for page in {int(row["page_number"] or 0) for row in rows}
        if all(
            position_key(row["evidence_bbox_json"])[0] < 1_000
            for row in rows
            if int(row["page_number"] or 0) == page
        )
    }
    return sorted(
        rows,
        key=lambda row: (
            int(row["page_number"] or 0),
            *(
                position_key(row["evidence_bbox_json"])
                if int(row["page_number"] or 0) in placed_pages
                else (0, 0.0)
            ),
            str(row["observed_at"] or ""),
            int(row["insert_order"]),
        ),
    )


def _document_observation_item(
    connection, owner_user_id: str, row: dict[str, object], age, sex, picker_names: dict[str, str]
) -> dict[str, object]:
    """One extracted value, formatted and judged, beside its evidence."""
    # Judged and shown in the unit the concept is tracked in.  Relabelling
    # without converting put Synevo's MCHC 36 g/dL on the page as
    # "36 g/L · below range" -- a tenth of its size -- while the trend page,
    # which converts, said 360.  Printed values stay on `row` for the
    # correction form: a fix is made against what the page says.
    shown = _in_preferred_unit(row)
    numeric = row["value_numeric"] is not None
    unit_source = _observation_unit_source(row, shown, numeric)
    unit = display_unit(unit_source)
    vendor_low, vendor_high, vendor_reading = _vendor_bounds(shown, age, sex)
    if shown.get("converted_from") and shown.get("vendor_reference_low") is None and shown.get("vendor_reference_high") is None:
        # Bounds recovered from the printed text are in the printed unit;
        # set against the converted value they would judge 360 by 36.
        vendor_low = vendor_high = None
    row["name"] = concept_display_name(str(row["canonical_name"]))
    row["picker_name"] = picker_names.get(str(row["concept_id"]), row["name"])
    # A parser that writes the English concept name as the "printed" label
    # invented it; saying "original name: Systolic blood pressure" over a
    # Ukrainian page is a claim about the page that is not true.
    row["show_raw_name"] = (
        str(row["raw_name"] or "").casefold() != str(row["canonical_name"] or "").casefold()
    )
    row["unit_text"] = unit
    row["display_value"] = format_reading(shown, unit)
    row["converted_from"] = shown.get("converted_from")
    # The correction field is seeded with the sign as well as the number, so
    # opening the form to fix something else and saving does not quietly
    # publish `0.01` where the report said `<0.01`.
    row["edit_numeric"] = (
        format_reading(row, row["unit_raw"]) if numeric else ""
    )
    # Named, so «Not supplied» says what was not supplied.
    row["display_reference"] = t(
        "doc.lab_reference", range=_row_reference_display(shown, age, sex, unit)
    )
    row["display_status"] = status_label(row["vendor_interpretation"])
    row["page_text"] = format_count(row["page_number"])
    # Where the source viewer outlines this value's printed row.
    row["page_box"] = page_box(row["evidence_bbox_json"])
    # The date this measurement was taken, as its own field: on a document
    # whose values span more than one, it is the only thing that tells two
    # otherwise identical rows apart.
    row["observed_text"] = format_date(str(row["observed_at"] or "") or None)
    # unit_source, not the display_unit()-rewritten `unit`: see the same
    # guard in _lab_card - evaluate()/canonical_unit() must see the caret
    # form, never the Unicode-superscript presentation form.
    row["verdict"] = evaluate(
        connection,
        concept_id=str(row["concept_id"]),
        value_numeric=shown["value_numeric"],
        value_text=row["value_text"],
        unit=unit_source if numeric else row["unit_raw"],
        age_years=age,
        sex=sex,
        vendor_low=vendor_low,
        vendor_high=vendor_high,
        vendor_interpretation=vendor_reading,
        clinical_context=_clinical_context(connection, owner_user_id),
    )
    row["url"] = f"/metrics/{row['concept_id']}"
    return row


def _document_observations(
    connection, owner_user_id: str, document_id: str, observation_ids: list[str] | None = None
) -> list[dict[str, object]]:
    """The extracted values, formatted and judged, beside their evidence.

    ``observation_ids`` narrows the work to those rows -- one value re-rendered
    after it was checked, or a collapsed group opened on demand -- without a
    second copy of the formatting that would drift from this one.
    """
    age, sex = _demographics(connection, owner_user_id)
    # The mapping control is pre-filled with the name the picker itself offers,
    # so leaving it untouched round-trips to the same concept instead of
    # falling through to a re-resolution of the printed label.
    picker_names = {
        str(row["id"]): name for name, row in _concept_picker(connection).items()
    }
    narrowed = (
        f" AND o.id IN ({','.join('?' * len(observation_ids))})" if observation_ids else ""
    )
    rows = connection.execute(
        f"""SELECT o.*, o.rowid AS insert_order, c.canonical_name, c.category, c.preferred_unit
           FROM observations o JOIN concepts c ON c.id=o.concept_id
           WHERE o.document_id=? AND o.owner_user_id=?{narrowed}""",
        (document_id, owner_user_id, *(observation_ids or [])),
    ).fetchall()
    return [
        _document_observation_item(connection, owner_user_id, dict(raw), age, sex, picker_names)
        for raw in _sorted_observation_rows(rows)
    ]


#: Kinds whose substance is a written conclusion, not a table of values: their
#: page opens on that conclusion rather than on an empty list of numbers.
NARRATIVE_DOCUMENT_TYPES = frozenset(
    {
        "ultrasound", "radiology_mri", "radiology_xray", "pathology", "consultation",
        "diagnostic_image", "clinical_report", "electrocardiogram",
    }
)
_FINDING_STATUS_RANK = {"attention": 0, "stable": 1, "information": 2}


def _finding_texts(row: dict[str, object], uk: bool) -> tuple[str, str, str]:
    """(shown text, summary in the reader's language, summary in the other one)."""
    own = str((row.get("summary_uk") if uk else row.get("summary_en")) or "").strip()
    other = str((row.get("summary_en") if uk else row.get("summary_uk")) or "").strip()
    text = translate_phrase(own or other) or str(row.get("original_text") or "").strip()
    return text, own, other


def _finding_as_printed_key(uk: bool, cyrillic: bool, text: str, summary: str):
    """Shown as printed when the words are not in the reader's language."""
    if not uk and cyrillic:
        return "doc.finding_as_printed_uk"
    if uk and not cyrillic and text == summary and re.search(r"[A-Za-z]{3}", text):
        return "doc.finding_as_printed_en"
    return None


def _merge_finding(merged: dict[tuple[int, str], dict[str, object]], row: dict[str, object], uk: bool) -> None:
    """Fold one stored finding into the card for its (page, text)."""
    text, own, other = _finding_texts(row, uk)
    if not text:
        return
    cyrillic = bool(_CYRILLIC_RE.search(text))
    key = (int(row["page_number"] or 1), text)
    item = merged.setdefault(
        key,
        {
            "page_number": key[0],
            "text": text,
            "as_printed_key": _finding_as_printed_key(uk, cyrillic, text, own or other),
            "original_text": str(row.get("original_text") or "").strip(),
            "status": str(row["status"]),
            "areas": [],
            "date_text": format_date(str(row.get("finding_date") or "") or None),
            "ids": [],
            "recommendations": str(row.get("recommendations") or "").strip(),
            "corrected": False,
        },
    )
    item["ids"].append(str(row["id"]))  # type: ignore[union-attr]
    item["person_added"] = str(row["id"]).startswith(PERSON_FINDING_PREFIX)
    item["corrected"] = item["corrected"] or row.get("verification_status") == "corrected"
    if _FINDING_STATUS_RANK.get(str(row["status"]), 3) < _FINDING_STATUS_RANK.get(str(item["status"]), 3):
        item["status"] = str(row["status"])
    area = AREA_BY_ID.get(str(row["health_area"]))
    if area is not None:
        name = translate_phrase(str(area["name"]))
        if name not in item["areas"]:
            item["areas"].append(name)  # type: ignore[union-attr]


def _document_findings(connection, owner_user_id: str, document_id: str) -> list[dict[str, object]]:
    """The report's conclusions, once each, in the reader's language when one exists.

    `sync_clinical_findings` files one conclusion under every body area it
    touches, so the same sentence arrives once per area; here it is one card
    naming its areas.  A summary in the other language, or only the printed
    wording, is shown as what it is rather than passed off as a translation.
    """
    uk = get_locale() == "uk"
    merged: dict[tuple[int, str], dict[str, object]] = {}
    for raw in connection.execute(
        """SELECT * FROM clinical_findings
            WHERE document_id=? AND owner_user_id=? AND verification_status <> 'rejected'
            ORDER BY page_number, created_at""",
        (document_id, owner_user_id),
    ):
        _merge_finding(merged, dict(raw), uk)
    findings = list(merged.values())
    corrections = _finding_corrections(connection, owner_user_id, [i for item in findings for i in item["ids"]])
    for item in findings:
        item["show_original"] = bool(item["original_text"]) and item["original_text"] != item["text"]
        found = next((corrections[i] for i in item["ids"] if i in corrections), None)
        if item["corrected"] and found:
            item["corrected_text"] = t("doc.finding_corrected_by", name=found["name"], date=format_date(found["date"]))
            item["read_text"] = found["read_text"]
        # A conclusion is a few sentences.  A passage this long is a whole page
        # the extractor could not narrow down; it opens on its first lines and
        # the rest is one press away rather than three screens of letterhead.
        text = str(item["text"])
        item["lead_text"] = (text[:320].rsplit(" ", 1)[0] + " ...") if len(text) > 480 else ""
    findings.sort(key=lambda item: (_FINDING_STATUS_RANK.get(str(item["status"]), 3), item["page_number"]))
    return findings


def _finding_corrections(connection, owner_user_id: str, finding_ids: list[str]) -> dict[str, dict[str, str]]:
    """Finding id -> who corrected its text last, when, and the text the
    software had read before any person's correction (from the audit log)."""
    if not finding_ids:
        return {}
    found: dict[str, dict[str, str]] = {}
    for row in connection.execute(
        f"""SELECT a.entity_id, a.created_at, a.details_json, COALESCE(u.display_name, u.email, '') name
              FROM audit_events a LEFT JOIN users u ON u.id=a.actor_user_id
             WHERE a.owner_user_id=? AND a.entity_type='clinical_finding'
               AND a.action IN ('finding_corrected', 'finding_added')
               AND a.entity_id IN ({",".join("?" * len(finding_ids))})
             ORDER BY a.id DESC""",
        (owner_user_id, *finding_ids),
    ):
        entry = found.setdefault(str(row["entity_id"]), {"name": str(row["name"]), "date": str(row["created_at"])[:10]})
        before = json.loads(row["details_json"] or "{}").get("before") or {}
        if "read_text" not in entry and before.get("verification_status") != "corrected":
            entry["read_text"] = str(before.get("summary_uk") or before.get("summary_en") or "")
            entry["before"] = before  # type: ignore[assignment]
    return found


def _bp_group(
    items: list[dict[str, object]],
) -> tuple[dict[tuple[object, object], dict[str, object]], list[dict[str, object]]]:
    """Cuff observations gathered per (time, page), and everything that is not one."""
    roles = _BP_ROLE_OF
    grouped: dict[tuple[object, object], dict[str, object]] = {}
    rest: list[dict[str, object]] = []
    for item in items:
        role = roles.get(str(item["concept_id"]))
        printed_category = str(item["canonical_name"]) == "Blood pressure category"
        if (role is None and not printed_category) or not item.get("observed_at"):
            rest.append(item)
            continue
        reading = grouped.setdefault(
            (item["observed_at"], item["page_number"]),
            {
                "observed_at": str(item["observed_at"]),
                "page_number": item["page_number"],
                "ids": [],
                "states": set(),
                "systolic": None, "diastolic": None, "pulse": None, "printed_category": "",
            },
        )
        reading["ids"].append(str(item["id"]))  # type: ignore[union-attr]
        reading["states"].add(str(item["verification_status"]))  # type: ignore[union-attr]
        if printed_category:
            reading["printed_category"] = str(item["display_value"])
        else:
            reading[role] = item
    return grouped, rest


def _bp_reading_state(states: set[str]) -> str:
    if "extracted" in states:
        return "extracted"
    if states == {"rejected"}:
        return "rejected"
    return _VERIFIED_STATE


def _bp_reading_view(reading: dict[str, object]) -> dict[str, object]:
    """One grouped reading, judged by the worse of its two pressures."""
    systolic, diastolic = reading["systolic"], reading["diastolic"]
    judged = [card for card in (systolic, diastolic) if card is not None]
    verdict = min(judged, key=_attention_rank)["verdict"] or {}  # type: ignore[index]
    states = reading.pop("states")
    stamp = str(reading["observed_at"])
    return {
        **reading,
        "date_text": format_date(stamp[:10]),
        "time_text": stamp[11:16] if len(stamp) >= 16 else "",
        "pressure_text": t(
            "bp.reading",
            systolic=systolic["display_value"] if systolic else t(_EM_DASH_KEY),  # type: ignore[index]
            diastolic=diastolic["display_value"] if diastolic else t(_EM_DASH_KEY),  # type: ignore[index]
        ),
        "pulse_text": reading["pulse"]["display_value"] if reading["pulse"] else "",  # type: ignore[index]
        "category_key": str(verdict.get("interpretation") or "unjudged"),
        "category_label": str(verdict.get("band_label") or verdict.get("label") or t("verdict.no_range")),
        "state": _bp_reading_state(states),  # type: ignore[arg-type]
    }


def _bp_readings(items: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """A cuff export as one row per reading, and whatever is not a reading.

    The parser stores a reading as three or four observations; shown as cards
    that was 164 cards and 60,000 px for four weeks of measurements, none of
    them saying what time it was taken.  The category is the worse of the two
    pressures' verdicts -- the ESH rule `_bp_block` already applies -- with the
    device's own printed label beside it as evidence, not as the judgement.
    """
    grouped, rest = _bp_group(items)
    readings = []
    for reading in grouped.values():
        if reading["systolic"] is None and reading["diastolic"] is None:
            rest.extend(item for item in items if str(item["id"]) in reading["ids"])
            continue
        readings.append(_bp_reading_view(reading))
    # In the order printed: `items` already follows the page.
    return readings, rest


def _split_negative_allergens(items: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """An allergy panel's results: anything worth reading, then the negatives.

    ALEX² tests 295 allergens; a negative panel printed as 295 full cards was a
    100,000 px page with the one value worth seeing somewhere inside it.  A
    result is folded away only when the reference engine judged it negative
    or normal -- never on a threshold written here.
    """
    negatives = [
        item for item in items
        if item["value_numeric"] is not None
        # Total IgE is the panel's context, not one of its allergens.
        and str(item["canonical_name"]) != "Total immunoglobulin E"
        and str((item.get("verdict") or {}).get("interpretation") or "") in {"negative", "normal", "optimal"}
        and item["verification_status"] != "rejected"
    ]
    folded = {id(item) for item in negatives}
    # Measurable-but-negative first: 0.12 kUA/L under a 0.3 cut-off is still
    # the line somebody scanning for a trace wants at the top.
    negatives.sort(key=lambda item: (item["comparator"] == "<", -float(item["value_numeric"])))
    return [item for item in items if id(item) not in folded], negatives


def _review_reason(task: dict[str, object]) -> str:
    """A review task's reason in the reader's language (CONTRACTS §2)."""
    # The re-read proposals are listed, with their answers, in their own panel
    # on the document page and counted on the queue card; said again here they
    # were the same eighteen lines twice.
    return review_reason_text(
        task, get_locale(), exclude=("review.reread_changed_n", "review.reread_orphaned_n")
    )


def _review_status(task: dict[str, object]) -> dict[str, object]:
    """The review line a document page shows: progress, and what is still asked.

    "0 of 0 checked" on an ultrasound report reads as a failure; it has no
    values, which is said instead.  A reason asking for values to be checked
    is spent once none are waiting -- "Verify 57 extracted observations" under
    "57 of 57 checked" contradicted the line it sat on.
    """
    counted = int(task.get("observation_count") or 0)  # type: ignore[arg-type]
    pending = int(task.get("pending_count") or 0)  # type: ignore[arg-type]
    task["progress_text"] = (
        t("review.progress", checked=format_count(counted - pending), total=format_count(counted))
        if counted
        else t("review.no_values")
    )
    task["reason_text"] = (
        _review_reason(task) if task.get("state") != "resolved" and (pending or not counted) else ""
    )
    rejected = int(task.get("rejected_count") or 0)  # type: ignore[arg-type]
    task["line_text"] = " · ".join(
        part
        for part in (
            str(task["progress_text"]),
            t("review.set_aside_n", count=format_count(rejected)) if rejected else "",
            str(task["reason_text"]),
        )
        if part
    )
    return task


def _document_review_task(connection, owner_user_id: str, document_id: str) -> dict[str, object] | None:
    """The document's latest review task with its counts, ready to show."""
    row = connection.execute(
        """SELECT rt.*,
                  (SELECT COUNT(*) FROM observations o WHERE o.document_id=d.id AND o.verification_status <> 'rejected') observation_count,
                  (SELECT COUNT(*) FROM observations o WHERE o.document_id=d.id AND o.verification_status='extracted') pending_count,
                  (SELECT COUNT(*) FROM observations o WHERE o.document_id=d.id AND o.verification_status='rejected') rejected_count
             FROM documents d JOIN review_tasks rt
               ON rt.owner_user_id=d.owner_user_id AND rt.entity_type='document' AND rt.entity_id=d.id
            WHERE d.id=? AND d.owner_user_id=?
            ORDER BY rt.created_at DESC, rt.rowid DESC LIMIT 1""",
        (document_id, owner_user_id),
    ).fetchone()
    return _review_status(dict(row)) if row else None


def _document_briefs(connection, owner_user_id: str, document_ids: set[str]) -> dict[str, dict[str, object]]:
    """id → a document's display title and date, for naming it in another's notice."""
    if not document_ids:
        return {}
    ids = sorted(document_ids)
    return {
        str(row["id"]): _document_row(row)
        for row in connection.execute(
            f"""SELECT d.id, d.title, d.clinical_type, d.report_date, d.original_filename, d.imported_at,
                       d.duplicate_of_document_id, d.sha256, d.page_count, d.mime_type, v.canonical_name vendor, {_TITLE_TESTS_SQL},
                       EXISTS(SELECT 1 FROM lab_orders lo WHERE lo.document_id=d.id) has_lab_order
                  FROM documents d LEFT JOIN vendors v ON v.id=d.vendor_id
                 WHERE d.owner_user_id=? AND d.id IN ({",".join("?" * len(ids))})""",
            (owner_user_id, *ids),
        )
    }


def _same_report_pairs(
    connection, owner_user_id: str, document_ids: list[str]
) -> dict[str, list[tuple[str, str, bool | None]]]:
    """Active document → [(active other document, relation note, keep the other)]
    for files the record says hold one report.

    Only open questions: a pair a person called different, or where one side
    is already marked a copy, is not listed.  A photo or a part of a report
    found by its order or its page text (`contains`) is offered like a copy,
    the whole report kept; for a plain duplicate the third item is None and
    the page decides which file to keep.
    """
    found: dict[str, list[tuple[str, str, bool | None]]] = {}
    if not document_ids:
        return found
    marks = ",".join("?" * len(document_ids))
    for row in connection.execute(
        f"""SELECT r.source_document_id, r.target_document_id, r.relationship, COALESCE(r.notes, '') notes
              FROM document_relations r
              JOIN documents a ON a.id=r.source_document_id
              JOIN documents b ON b.id=r.target_document_id
             WHERE (r.relationship='duplicate' OR (r.relationship='contains' AND r.notes IN (?, ?)))
               AND COALESCE(r.notes, '')<>?
               AND a.owner_user_id=? AND b.owner_user_id=?
               AND a.duplicate_of_document_id IS NULL AND b.duplicate_of_document_id IS NULL
               AND (r.source_document_id IN ({marks}) OR r.target_document_id IN ({marks}))""",
        (SAME_ORDER_NOTE, PAGE_TEXT_NOTE, NOT_DUPLICATE_NOTE, owner_user_id, owner_user_id,
         *document_ids, *document_ids),
    ):
        source, target, notes = str(row["source_document_id"]), str(row["target_document_id"]), str(row["notes"])
        whole = row["relationship"] == "contains"  # the source holds the whole report
        found.setdefault(source, []).append((target, notes, False if whole else None))
        found.setdefault(target, []).append((source, notes, True if whole else None))
    return found


def _same_report_reason(note: str) -> str:
    """Why the record thinks two files are one report, in the reader's words."""
    if note.startswith("auto:shared_results:"):
        return t_plural("dup.reason_results", int(note.rsplit(":", 1)[1] or 0))
    if note == "auto:report_number":
        return t("dup.reason_report_number")
    if note == "auto:content_hash":
        return t("dup.reason_content_hash")
    if note == SAME_ORDER_NOTE:
        return t("dup.reason_same_order")
    if note == PAGE_TEXT_NOTE:
        return t("dup.reason_page_text")
    return t("dup.reason_text")


#: (relationship, this document is the source) → how the other one is named;
#: a (relationship, is source, note) entry, when there is one, comes first.
_RELATION_TEXT_KEYS = {
    ("contains", True): "dup.rel_contains",
    ("contains", False): "dup.rel_contained_in",
    ("reprint", True): "dup.rel_reprint",
    ("reprint", False): "dup.rel_reprint",
    ("overlaps", True): "dup.rel_overlaps",
    ("overlaps", False): "dup.rel_overlaps",
    ("attachment_of", True): "dup.rel_results_for",
    ("attachment_of", False): "dup.rel_results_in",
    ("attachment_of", True, SAME_ORDER_NOTE): "dup.rel_supplement_of",
    ("attachment_of", False, SAME_ORDER_NOTE): "dup.rel_has_supplement",
    ("part_of", True): "dup.rel_part_of",
    ("part_of", False): "dup.rel_has_part",
}


def _relation_other_id(row, document_id: str) -> str:
    """The document at the far end of a relation row."""
    return str(row["target_document_id"] if row["source_document_id"] == document_id else row["source_document_id"])


def _keep_rank(brief: dict[str, object], document_id: str) -> tuple[int, str, str]:
    """Lower is kept: the file the lab's order is linked to, then the older import."""
    return (0 if brief.get("has_lab_order") else 1, str(brief.get("imported_at") or ""), document_id)


def _same_as_entries(
    pairs: list[tuple[str, str, bool | None]], briefs: dict[str, dict[str, object]], mine: dict[str, object]
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    my_rank = _keep_rank(mine, str(mine["id"]))
    for other_id, note, keep_other in pairs:
        brief = briefs.get(other_id)
        if not brief:
            continue
        if keep_other is not None:
            suggested = "dup.suggested_whole"
        else:
            # The file the lab's order is linked to: its values are checked
            # against the lab's own record.  Else the older import: the one
            # the record has been counting, whose values a person may have
            # checked.
            other_rank = _keep_rank(brief, other_id)
            keep_other = other_rank <= my_rank
            suggested = "dup.suggested_lab_order" if other_rank[0] != my_rank[0] else "dup.suggested"
        entries.append({
            "document": brief, "reason": _same_report_reason(note), "keep_other": keep_other, "suggested": suggested,
        })
    return entries


def _related_entries(related, briefs: dict[str, dict[str, object]], document_id: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for row in related:
        is_source = row["source_document_id"] == document_id
        other_id = _relation_other_id(row, document_id)
        relationship = str(row["relationship"])
        key = _RELATION_TEXT_KEYS.get((relationship, is_source, str(row["notes"] or ""))) or _RELATION_TEXT_KEYS.get(
            (relationship, is_source)
        )
        person = str(row["notes"] or "") == PERSON_PART_NOTE
        if person:
            key = "dup.rel_person_part_of" if is_source else "dup.rel_person_has_part"
        if key and other_id in briefs:
            entries.append({
                "label": t(key), "document": briefs[other_id], "part": relationship == "part_of",
                "person": person, "is_source": is_source,
            })
    # A file a person placed in a report is no longer offered as the next
    # screenshot of some other one.
    if any(item["person"] and item["is_source"] for item in entries):
        entries = [item for item in entries if item["person"] or not (item["part"] and item["is_source"])]
    return entries


def _document_relations_view(connection, owner_user_id: str, document: dict[str, object]) -> dict[str, object]:
    """What the document page says about other files holding the same report."""
    document_id = str(document["id"])
    view: dict[str, object] = {"copy_of": None, "same_bytes": False, "same_as": [], "related": [], "copies": []}
    copies = [
        str(row[0])
        for row in connection.execute(
            "SELECT id FROM documents WHERE owner_user_id=? AND duplicate_of_document_id=? ORDER BY imported_at",
            (owner_user_id, document_id),
        )
    ]
    pairs = [] if document.get("duplicate_of_document_id") else _same_report_pairs(
        connection, owner_user_id, [document_id]
    ).get(document_id, [])
    related = connection.execute(
        """SELECT source_document_id, target_document_id, relationship, notes FROM document_relations
            WHERE relationship<>'duplicate' AND NOT (relationship='contains' AND COALESCE(notes, '') IN (?, ?))
              AND (source_document_id=? OR target_document_id=?)""",
        (SAME_ORDER_NOTE, PAGE_TEXT_NOTE, document_id, document_id),
    ).fetchall()
    primary_id = str(document.get("duplicate_of_document_id") or "")
    others = {other for other, _, _ in pairs} | set(copies) | ({primary_id} if primary_id else set()) | {
        _relation_other_id(row, document_id) for row in related
    }
    briefs = _document_briefs(connection, owner_user_id, others)
    if primary_id and primary_id in briefs:
        view["copy_of"] = briefs[primary_id]
        view["same_bytes"] = briefs[primary_id].get("sha256") == document.get("sha256")
    mine = {**document, "has_lab_order": bool(connection.execute(
        "SELECT 1 FROM lab_orders WHERE document_id=? LIMIT 1", (document_id,)
    ).fetchone())}
    view["same_as"] = _same_as_entries(pairs, briefs, mine)
    view["related"] = _related_entries(related, briefs, document_id)
    # Screenshots of one report: the page explains them and offers to unlink one.
    view["parts"] = [item for item in view["related"] if item["part"]]
    view["person_part_of"] = next(
        (item["document"] for item in view["related"] if item["person"] and item["is_source"]), None
    )
    view["person_parts"] = sorted(
        (item["document"] for item in view["related"] if item["person"] and not item["is_source"]),
        key=lambda brief: (str(brief.get("imported_at") or ""), str(brief.get("original_filename") or "")),
    )
    view["copies"] = [briefs[item] for item in copies if item in briefs]
    return view


#: How many reports the "part of a report" picker offers.
_PART_CANDIDATES = 60


def _part_candidates(connection, owner_user_id: str, document: dict[str, object]) -> list[dict[str, object]]:
    """Reports this file could be a page of: the same patient's other kept
    files, the same report date first, then the nearest uploads -- photos of
    one report are taken and sent together."""
    rows = connection.execute(
        """SELECT d.id FROM documents d
            WHERE d.owner_user_id=? AND d.patient_id=? AND d.id<>? AND d.duplicate_of_document_id IS NULL
              AND NOT EXISTS (SELECT 1 FROM document_relations r WHERE r.source_document_id=d.id
                              AND r.relationship='part_of' AND r.notes=?)
            ORDER BY COALESCE(d.report_date, '')=COALESCE(?, '-') DESC,
                     ABS(julianday(d.imported_at) - julianday(?)), d.id
            LIMIT ?""",
        (owner_user_id, document["patient_id"], document["id"], PERSON_PART_NOTE,
         document.get("report_date"), document.get("imported_at"), _PART_CANDIDATES),
    ).fetchall()
    briefs = _document_briefs(connection, owner_user_id, {str(row[0]) for row in rows})
    return [briefs[str(row[0])] for row in rows if str(row[0]) in briefs]


def _concept_picker(connection) -> dict[str, dict[str, object]]:
    """Metric name as the correction picker offers it -> that concept's row.

    Names are shown in the reader's language, and two different concepts can
    share one Ukrainian name - `глюкоза` is both blood glucose and urine
    glucose, `лейкоцити` is both a blood count and a urine finding.  A name in
    that position carries its canonical spelling too, because a picker where
    one entry can mean two analytes is how a blood result ends up filed as a
    urine one.

    The page and the handler that reads the page's answer are both built from
    this one mapping, so every name the list offers resolves, and a name it
    never offered can never resolve to the wrong concept.
    """
    rows = [
        dict(row)
        for row in connection.execute(
            "SELECT id, canonical_name, preferred_unit FROM concepts ORDER BY canonical_name"
        )
    ]
    shared = Counter(concept_display_name(str(row["canonical_name"])).casefold() for row in rows)
    picker: dict[str, dict[str, object]] = {}
    for row in rows:
        name = concept_display_name(str(row["canonical_name"]))
        if shared[name.casefold()] > 1:
            name = f"{name} ({row['canonical_name']})"
        picker[name] = row
    return picker


def _picked_concept(picker: dict[str, dict[str, object]], name: str) -> dict[str, object] | None:
    """The concept a typed or chosen picker name means, or None.

    The canonical spelling is accepted as well as the offered one: it is unique
    by definition, and someone reading a Ukrainian page may still type the name
    they know from the report.
    """
    folded = name.casefold().strip()
    if not folded:
        return None
    for offered, row in picker.items():
        if offered.casefold() == folded or str(row["canonical_name"]).casefold() == folded:
            return row
    return None


def _pagination(total: int, offset: int, limit: int, base: str) -> dict[str, object]:
    """An honest counter: `40 of 295`, with a way to reach the other 255."""
    offset = max(0, min(offset, max(total - 1, 0)))
    shown = max(0, min(limit, total - offset))
    joiner = "&" if "?" in base else "?"
    return {
        "offset": offset,
        "limit": limit,
        "total": total,
        "shown": shown,
        "first": offset + 1 if shown else 0,
        "last": offset + shown,
        "has_more": offset + limit < total,
        "next_url": f"{base}{joiner}offset={offset + limit}" if offset + limit < total else None,
        "prev_url": f"{base}{joiner}offset={max(0, offset - limit)}" if offset else None,
    }


def _safe_next(value: str | None, fallback: str = "/") -> str:
    r"""A caller-supplied return path, or the fallback — never another site.

    Backslashes are folded before the test because browsers fold them after
    it: Chrome and Firefox read `/\evil.com` as `//evil.com`, which is a
    protocol-relative URL to somebody else's host, so the naive check waves
    through the one shape it exists to stop.
    """
    candidate = (value or "").replace("\\", "/")
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return fallback


#: What a reader can say went wrong with an extracted value.  The keys are the
#: contract: they match the CHECK constraint in migration 017, the
#: `report.cat_*` message keys, and the vocabulary a fixing agent queries
#: `parser_issue_reports` by — change all four together or none.
ISSUE_CATEGORIES = (
    "wrong_value",
    "wrong_unit",
    "wrong_metric",
    "wrong_reference",
    "missing_value",
    "not_a_result",
    "wrong_date_or_page",
    "other",
)


def _document_issue_reports(connection, owner_user_id: str, document_id: str) -> list[dict[str, object]]:
    """Filed parser problems for one document, ready to render.

    Everything shown comes off the snapshot taken when the report was filed,
    not the live observation row: a re-scan may since have deleted or changed
    the row, and the report is about what the parser did *then*.
    """
    items = []
    for row in connection.execute(
        """SELECT * FROM parser_issue_reports WHERE document_id=? AND owner_user_id=?
           ORDER BY status = 'resolved', created_at DESC""",
        (document_id, owner_user_id),
    ):
        context = json.loads(row["context_json"])
        observation = context.get("observation") or None
        target_value = ""
        if observation:
            unit = display_unit(observation.get("unit_raw"))
            target_value = f"{format_reading(observation, unit)} {unit or ''}".strip()
        items.append(
            {
                "id": row["id"],
                "category_label": t("report.cat_" + str(row["category"])),
                "target_name": (observation or {}).get("raw_name") or t("report.target_document"),
                "target_value": target_value,
                "page_number": (observation or {}).get("page_number"),
                "expected_text": row["expected_text"],
                "description": row["description"],
                "resolved": row["status"] == "resolved",
                "status_label": t("report.status_" + str(row["status"])),
                "created_text": format_date(str(row["created_at"] or "")[:10] or None),
            }
        )
    return items


#: Control characters, the path separators, and the glyphs Windows refuses in a
#: filename.  Deliberately a denylist: the allowlist that stood here permitted
#: `[\w \-.()]` and Cyrillic, which reads as generous until a phone hands over
#: «Найменування_міністерства,_іншого_органу_виконавчої.pdf» — a scan of a MOZ
#: form, named after its own first line — and the comma alone got it rejected as
#: "damaged, or its name cannot be used".  Apostrophes, «», №, +, &, ! and [] are
#: all just as ordinary in a document's name.  Nothing downstream needs the name
#: to be narrow: it is a leaf (`PurePath.name`), it is joined to one fixed
#: directory, and the suffix check below still decides what is accepted at all.
_UNSAFE_FILENAME_RE = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')
#: Windows resolves these as devices whatever extension follows, so a file named
#: after one cannot be opened back.
_RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{digit}" for digit in range(1, 10)}
    | {f"lpt{digit}" for digit in range(1, 10)}
)


def _sanitised_upload_name(raw: str | None) -> str | None:
    """Never trust the client's filename.

    Strips any path the browser sent, then requires the remainder to be a plain
    name with a supported suffix: no separators, no dotfiles, nothing a
    filesystem here would refuse.  A directory picker sends `folder/sub/scan.pdf`;
    only the leaf survives, and the archive's own entry names are re-checked
    again when it is expanded.
    """
    if not raw:
        return None
    name = PurePath(raw.replace("\\", "/")).name.strip()
    if not name or len(name) > 120 or name.startswith("."):
        return None
    if _UNSAFE_FILENAME_RE.search(name):
        return None
    if name.partition(".")[0].casefold() in _RESERVED_STEMS:
        return None
    if Path(name).suffix.casefold() not in INTAKE_SUFFIXES:
        return None
    return name


def _upload_target(settings: Settings, name: str) -> Path:
    """A fresh path in this month's arrivals corner, never overwriting.

    Web uploads are raw arrivals, not curated files: they land in their own
    dated corner of the sources tree instead of the curated root.
    """
    upload_dir = settings.source_dir / "uploads" / utc_now()[:7]
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / name
    counter = 1
    while target.exists():
        target = upload_dir / f"{Path(name).stem}-{counter}{Path(name).suffix}"
        counter += 1
    return target


async def _admit_upload(
    settings: Settings, common: dict[str, str], kind: str, name: str, target: Path, written: int
) -> None:
    """Classify a file already on disk, dedupe documents, and queue it.

    Shared by the one-request form path and the sliced path: whichever way the
    bytes arrived, the same rules decide what happens to them.
    """
    suffix = Path(name).suffix.casefold()
    if kind != "auto":
        job_kind, adapter = ("device_export" if suffix not in ARCHIVE_SUFFIXES else "archive"), kind
    elif suffix in ARCHIVE_SUFFIXES:
        job_kind, adapter = "archive", None
    else:
        job_kind, adapter = "document", None

    if job_kind == "document":
        # The pipeline dedupes by SHA-256 anyway, but only after a full
        # extract and by recording a second document that points at the
        # first.  Asking here means a re-upload costs one hash instead
        # of an OCR pass, keeps one copy of the bytes on disk, and can
        # say what happened.
        digest = await run_in_threadpool(file_sha256, target)
        with connect(settings) as connection:
            held = connection.execute(
                """SELECT id FROM documents WHERE owner_user_id=? AND sha256=?
                   ORDER BY imported_at LIMIT 1""",
                (common["owner_user_id"], digest),
            ).fetchone()
        if held:
            target.unlink(missing_ok=True)
            record_duplicate(
                settings, **common, filename=name,
                document_id=str(held["id"]), byte_size=written,
            )
            return

    enqueue(
        settings, **common, kind=job_kind, adapter_key=adapter,
        filename=name, source_path=target, byte_size=written,
    )


def _export_options(connection, owner_user_id: str) -> list[dict[str, object]]:
    """Every recorded metric that can be added to an export."""

    return _metric_catalog(
        connection,
        owner_user_id,
        include_devices=True,
        include_suppressed=True,
    )


def _export_metric_groups(options: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for card in options:
        category = str(card["category_label"])
        groups.setdefault(category, []).append(
            {
                "id": card["id"],
                "name": card["name"],
                "latest_text": f"{card['value_text']} {card['unit']}".strip(),
                "count_text": t_plural("metric.points", int(card["count"])),
            }
        )
    return [{"name": name, "metrics": metrics} for name, metrics in groups.items()]


def _export_prepare_labels() -> dict[str, str]:
    return {
        "aggregated_reference": t("export.aggregated_reference"),
        "average": t("export.average_badge"),
        "unknown_date": t(_DATE_UNKNOWN_KEY),
        **{key: t(f"export.aggregation_{key}") for key in AGGREGATION_KEYS},
    }


def _export_pdf_labels() -> dict[str, str]:
    return {
        "title": t("export.document_title"),
        "subtitle": t("export.document_subtitle"),
        "patient": t("export.patient"),
        "date_of_birth": t("export.date_of_birth"),
        "created": t("export.created"),
        "included": t("export.included"),
        "latest": t("export.latest"),
        "period": t("export.period"),
        "column_date": t("export.th_date"),
        "column_result": t("export.th_result"),
        "column_comparison": t("export.th_comparison"),
        "column_source": t("export.th_source"),
        "unknown_source": t("export.unknown_source"),
        "not_available": t("export.not_available"),
        "page": t("export.page"),
    }


def _export_interval_text(verdict, interval, judged: bool) -> str:
    if not (judged and interval and interval != t(_EM_DASH_KEY)):
        return ""
    return t("export.judged_against", interval=interval,
             authority=str(verdict.get("authority_label") or ""))


def _export_reference_text(verdict, comparison, lab_reference, judged: bool) -> str:
    # A range that does not describe this patient says nothing
    # under a value another authority judged; withheld.
    if not (lab_reference and lab_reference != t(_EM_DASH_KEY)):
        return ""
    if (judged and verdict.get("authority") != "vendor"
            and comparison["reference_text"] is None
            and comparison["comparison_basis"] == "none"):
        return ""
    return t("export.lab_interval", interval=lab_reference)


def _export_observation_row(connection, concept_id: str, row, date_of_birth, sex) -> dict[str, object]:
    unit = display_unit(_row_display_unit(row))
    provider = row.get("vendor")
    provider_text = (
        t(_UNKNOWN_PROVIDER_KEY)
        if provider in {None, _UNKNOWN_PROVIDER, _UNKNOWN_VENDOR}
        else translate_phrase(str(provider))
    )
    # Judged and compared at the age the sample was taken: a 2016
    # result must not be read against today's age, and a paediatric
    # first line of a multi-population interval is not this adult's.
    comparison = _original_comparison(row, date_of_birth=date_of_birth, sex=sex)
    _, verdict = _reading_verdict(
        connection, concept_id, row, comparison["age_at_observation"], sex
    )
    lab_reference = localized_reference(comparison["reference_text"] or _row_reference_display(
        row, comparison["age_at_observation"], sex, unit
    ))
    interval = verdict.get("target_range_text") or verdict.get("range_text")
    judged = verdict.get("interpretation") not in {None, "unjudged", "not_a_measurement"}
    also = [
        format_measured(value, unit) if isinstance(value, (int, float)) else display_value(str(value))
        for value in row.get("same_day_values") or []
    ]
    value_text = format_reading(row, unit)
    return {
        "id": row["id"],
        "date": row["observed_at"],
        "date_text": format_date(row["observed_at"]),
        "value_text": precise_at_edges(row["value_numeric"], value_text, verdict),
        "numeric": row["value_numeric"],
        "unit": unit or "",
        "verdict": str(verdict["label"]) if judged else "",
        "verdict_state": verdict_state(verdict),
        "interval": _export_interval_text(verdict, interval, judged),
        "reference": _export_reference_text(verdict, comparison, lab_reference, judged),
        "also_printed": t("export.also_printed", values=", ".join(also)) if also else "",
        "provider": provider_text,
        # Provider has its own trace column; keeping it out of the
        # fallback document title avoids "Test Lab - report - Test Lab".
        "document_title": (
            t("twin.source_device") if row.get("is_device")
            else display_document_title(str(row.get("document_title") or ""))
        ),
        "status": t(_DEVICE_MEASUREMENT_KEY) if row.get("is_device") else status_label(row["verification_status"]),
        # A device day has no page to open; its sources are compared on the
        # device page, which the export's metric heading already links to.
        "document_url": None if row.get("is_device") else f"/documents/{row['document_id']}#observation-{row['id']}",
    }


def _export_device_rows(connection, owner_user_id: str, metric_key: str) -> list[dict[str, object]]:
    device_rows = []
    for row in device_metric_values(connection, owner_user_id, metric_key):
        unit = display_unit(str(row.get("unit") or "")) or ""
        minimum = row.get("value_min")
        maximum = row.get("value_max")
        samples = int(row.get("sample_count") or 0)
        spread = ""
        if minimum is not None and maximum is not None and (
            float(minimum) != float(maximum) or samples > 1
        ):
            spread = t(
                "export.device_spread",
                minimum=format_number_localized(minimum),
                maximum=format_number_localized(maximum),
                count=samples,
            )
        source_vendor = translate_phrase(str(row.get("source_vendor") or ""))
        source_name = translate_phrase(str(row.get("source_name") or ""))
        device_rows.append(
            {
                "id": row["id"],
                "date": row["day"],
                "date_text": format_date(row["day"]),
                "value_text": format_number_localized(row["value"]),
                "numeric": row["value"],
                "unit": unit,
                "reference": spread,
                "provider": source_vendor or source_name,
                "document_title": source_name if source_name != source_vendor else "",
                "status": "",
                "document_url": None,
            }
        )
    return device_rows


def _export_detail_url(metric_id: str) -> str:
    if metric_id.startswith(_DEVICE_METRIC_PREFIX):
        return f"/devices/metrics/{metric_id.removeprefix(_DEVICE_METRIC_PREFIX)}"
    return f"/metrics/{metric_id}"


def _export_period_text(all_dates: list[str]) -> str:
    if not all_dates:
        return t(_DATE_UNKNOWN_KEY)
    if min(all_dates) == max(all_dates):
        return format_date(min(all_dates))
    return f"{format_date(min(all_dates))} - {format_date(max(all_dates))}"


def _health_export_payload(
    connection,
    owner_user_id: str,
    selected_ids: list[str],
    aggregation: str,
    options: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build the single normalized structure used by HTML and PDF."""

    options = options if options is not None else _export_options(connection, owner_user_id)
    allowed = {str(card["id"]): card for card in options}
    selected = list(dict.fromkeys(metric_id for metric_id in selected_ids if metric_id in allowed))
    _, sex = _demographics(connection, owner_user_id)
    patient = _patient_row(connection, owner_user_id)
    date_of_birth = patient["date_of_birth"] if patient else None
    by_concept: dict[str, list[dict[str, object]]] = {}
    for row in _linked_observation_rows(connection, owner_user_id):
        if str(row["concept_id"]) in selected:
            by_concept.setdefault(str(row["concept_id"]), []).append(row)
    grouped: dict[str, list[dict[str, object]]] = {}
    for concept_id, concept_rows in by_concept.items():
        # One result per day, as the chart draws it: a report that prints the
        # same draw twice is one measurement, and two rows on one date read as
        # twins.  The other printing is disclosed beside the kept one.
        grouped[concept_id] = [
            _export_observation_row(connection, concept_id, row, date_of_birth, sex)
            for row in _one_per_day(concept_rows)
        ]

    for metric_id in selected:
        if metric_id.startswith(_DEVICE_METRIC_PREFIX):
            grouped[metric_id] = _export_device_rows(
                connection, owner_user_id, metric_id.removeprefix(_DEVICE_METRIC_PREFIX)
            )

    labels = _export_prepare_labels()
    metrics = []
    for metric_id in selected:
        card = allowed[metric_id]
        metrics.append(
            prepare_metric(
                {
                    "id": metric_id,
                    "name": card["name"],
                    "category_name": card["category_label"],
                    "detail_url": _export_detail_url(metric_id),
                },
                grouped.get(metric_id, []),
                aggregation,
                datefmt=format_date,
                numfmt=format_number_localized,
                labels=labels,
            )
        )

    all_dates = [
        str(row["date"])
        for metric in metrics
        for row in grouped.get(str(metric["id"]), [])
        if row.get("date")
    ]
    total_values = sum(int(metric["point_count"]) for metric in metrics)
    metric_text = t_plural("export.metrics_count", len(metrics))
    value_text = t_plural("export.values_count", total_values)
    return {
        "patient_name": str(patient["display_name"]) if patient else t("export.unknown_patient"),
        "date_of_birth_text": format_date(patient["date_of_birth"]) if patient and patient["date_of_birth"] else t("export.not_available"),
        "created_text": format_date(date.today().isoformat()),
        "metrics": metrics,
        "selected_ids": selected,
        "selection_text": t("export.selection_summary", metrics=metric_text, values=value_text),
        "period_text": _export_period_text(all_dates),
    }


#: OpenAPI documentation of the HTTP errors each route can raise (its own and
#: those of the helpers and dependencies it calls), so the schema lists them.
_HTTP_400 = {"description": "Bad request"}
_HTTP_401 = {"description": "Not signed in"}
_HTTP_403 = {"description": "Forbidden"}
_HTTP_404 = {"description": "Not found"}
_HTTP_413 = {"description": "Payload too large"}
_HTTP_415 = {"description": "Unsupported media type"}
_HTTP_429 = {"description": "Too many requests"}
_RESPONSES_400_401 = {400: _HTTP_400, 401: _HTTP_401}
_RESPONSES_400_401_403 = {400: _HTTP_400, 401: _HTTP_401, 403: _HTTP_403}
_RESPONSES_400_401_403_404 = {400: _HTTP_400, 401: _HTTP_401, 403: _HTTP_403, 404: _HTTP_404}
_RESPONSES_400_401_404 = {400: _HTTP_400, 401: _HTTP_401, 404: _HTTP_404}
_RESPONSES_400_404_413_429 = {400: _HTTP_400, 404: _HTTP_404, 413: _HTTP_413, 429: _HTTP_429}
_RESPONSES_401 = {401: _HTTP_401}
_RESPONSES_401_403 = {401: _HTTP_401, 403: _HTTP_403}
_RESPONSES_401_403_404 = {401: _HTTP_401, 403: _HTTP_403, 404: _HTTP_404}
_RESPONSES_401_404 = {401: _HTTP_401, 404: _HTTP_404}
_RESPONSES_401_404_415 = {401: _HTTP_401, 404: _HTTP_404, 415: _HTTP_415}
_RESPONSES_403 = {403: _HTTP_403}
_RESPONSES_413_429 = {413: _HTTP_413, 429: _HTTP_429}
_RESPONSES_429 = {429: _HTTP_429}

router = APIRouter()



#: Sent on every response.  The application serves one person's medical
#: record, so the defaults are the restrictive ones: nothing off-origin
#: loads, nothing frames it, and no referrer carries a document id to
#: another site.  `'unsafe-inline'` is present because the templates carry
#: inline theme, i18n and chart bootstrapping that runs during parse —
#: it is the one relaxation, and `default-src 'self'` still stops a
#: successful injection from reaching an external collector.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        # form-action stays strict on purpose. Chrome applies it to every
        # redirect hop a form submission lands on, and a provider's OAuth
        # entry bounces through its own SSO hosts (cloud.ouraring.com →
        # moi.ouraring.com, measured 2026-08-07) — an unwinnable allowlist.
        # That is why the wearable Connect controls are links (GET → 303),
        # never form POSTs: navigations are outside form-action's reach.
        "form-action 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

def _bearer_secret(request: Request) -> str | None:
    """The credential this request presents in a header, if any.

    Two spellings because two kinds of caller reach for different ones: a
    script writes ``Authorization: Bearer``, an HTTP client library and
    most API consoles offer ``X-API-Key``.  Refusing the second would be a
    support question, not a security property.
    """
    header = request.headers.get("authorization") or ""
    if header[:7].casefold() == "bearer ":
        return header[7:].strip()
    return (request.headers.get("x-api-key") or "").strip() or None

def _resolve_user(request: Request):
    """Whoever is making this request — by bearer credential or by cookie.

    The header is tried first and, when present, is the whole answer: a
    caller who sent a token and got it wrong must be refused rather than
    quietly served as whoever the browser happened to be signed in as.
    """
    settings = request.app.state.settings
    secret = _bearer_secret(request)
    if secret:
        row = access_token_user(settings, secret)
        if row is None:
            return None
        stamp = utc_now()
        # Once a minute is enough to tell a live credential from an
        # abandoned one, and it keeps a read-only API call from taking a
        # write lock on every request an integration test makes.
        if (row["token_used_at"] or "")[:16] != stamp[:16]:
            touch_access_token(settings, row["token_id"])
        # No cookie took part, so no site can make a browser replay this:
        # CSRF is a cookie problem, and `bearer` is what says so.
        return dict(row) | {"csrf_token": "", "bearer": True}
    row = session_user(settings, request.cookies.get("anamna_session"))
    return None if row is None else dict(row) | {"bearer": False}

async def token_scope(request: Request, call_next):
    """Resolve the caller once, and hold each credential to its own reach.

    In middleware rather than in a dependency so that it covers the routes
    nobody has written yet: a page added next month is inside the guest
    allowlist's "no" by default, which is the direction this check has to
    fail in.  A password session is unaffected — `token_kind` is NULL for
    one, and every branch below is keyed on it.
    """
    request.state.anamna_user = await run_in_threadpool(_resolve_user, request)
    kind = (request.state.anamna_user or {}).get("token_kind")
    path = request.url.path
    if kind == "api" and not path.startswith("/api/"):
        return JSONResponse({"detail": t("token.error_api_only")}, status_code=403)
    if kind == "guest":
        if request.method in ("GET", "HEAD"):
            permitted = path in GUEST_ALLOWED_PAGES or path.startswith(GUEST_ALLOWED_PREFIXES)
        else:
            permitted = path in GUEST_ALLOWED_POSTS
        if not permitted:
            return JSONResponse({"detail": t("token.error_guest_only")}, status_code=403)
    return await call_next(request)

async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    # Record pages, API payloads and source previews must be fetched under
    # the current authorization. Cached evidence can outlive logout or a
    # revoked invitation, including when switching accounts in one browser.
    # `no-transform` keeps Cloudflare from rewriting the page: without it
    # the edge injects its analytics beacon (which this CSP then blocks,
    # one console error per load) and rewrites e-mail addresses into
    # /cdn-cgi/l/email-protection links, even inside <option>/<template>.
    if request.url.path.startswith(_STATIC_PREFIX):
        response.headers["Cache-Control"] = _static_cache_control(request)
    else:
        response.headers["Cache-Control"] = "private, no-store, no-transform"
    if request.url.scheme == "https":
        # Only over TLS: sent on a plain-http reply it is ignored by every
        # browser, and pins a scheme the deployment may not have yet.
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response

async def locale_middleware(request: Request, call_next):
    locale = normalize_locale(request.query_params.get("lang") or request.cookies.get(LOCALE_COOKIE) or VISITOR_LOCALE)
    token = activate_locale(locale)
    cache_token = _request_cache.set({})
    # Settings readers memoise per request, but only where nothing writes
    # them: a POST that saves a setting and then reads it back must see
    # the new value.
    memo_token = _request_memo.set({} if request.method in ("GET", "HEAD") else None)
    # reference.py reads each concept's curated rules once per request.
    rules_token = RULE_CACHE.set({})
    try:
        response = await call_next(request)
        # Never on a static file: Cloudflare refuses to cache any response
        # that sets a cookie, so every first visit's CSS and scripts went
        # BYPASS to the origin. Assets do not depend on the locale anyway.
        if request.url.path.startswith(_STATIC_PREFIX):
            return response
        # Only a choice is remembered; the default is not, so it can change.
        if request.query_params.get("lang"):
            response.set_cookie(
                LOCALE_COOKIE, locale, max_age=365 * 86400, samesite="lax", httponly=True,
                secure=_secure_cookie(request),
            )
        return response
    finally:
        RULE_CACHE.reset(rules_token)
        _request_memo.reset(memo_token)
        _request_cache.reset(cache_token)
        reset_locale(token)

async def derived_values(request: Request, call_next):
    """Recalculate derived values (eGFR) after anything that may have
    changed their inputs -- a corrected creatinine, a verification, a new
    date of birth.  One hook here rather than one per route, so a route
    added later cannot leave a stale eGFR behind; it writes only when a
    value actually moved."""
    settings = request.app.state.settings
    response = await call_next(request)
    if (
        request.method not in {"GET", "HEAD", "OPTIONS"}
        and response.status_code < 400
        and getattr(request.state, "anamna_user", None)
    ):
        def refresh() -> None:
            with connect(settings) as connection:
                if any(refresh_derived_observations(connection).values()):
                    connection.commit()
                    invalidate_catalog()

        await run_in_threadpool(refresh)
    return response

def current_user(request: Request):
    """Resolved once by `token_scope`, so every route reads the same answer
    and a request costs one lookup rather than one per caller."""
    return getattr(request.state, "anamna_user", None)

def require_user(request: Request):
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user

def csrf_ok(user, token: str) -> bool:
    """Whether this request carries the right cross-site protection.

    A bearer credential is never attached by a browser on its own, so there
    is no cross-site request to forge.  The check guards the cookie session;
    skipping it for a header is not a hole, and *not* skipping it is a
    different bug — the two upload routes compared the token directly rather
    than going through here, which locked the agent credential out of the
    one route that most needs exercising on a deployment: the door.
    """
    return bool(user.get("bearer")) or csrf_matches(user["csrf_token"], token)

def require_csrf(user, token: str) -> None:
    if not csrf_ok(user, token):
        raise HTTPException(403, t("csrf.invalid"))

def require_admin(request: Request):
    """A signed-in administrator, or a refusal.

    401 for a stranger so the exception handler sends them to sign in;
    403 for a signed-in non-administrator, because signing in again will
    not help and a redirect loop is the usual way that is discovered.
    """
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, t("admin.forbidden"))
    return user

def viewing_row(request: Request):
    """The users row of the shared record being viewed, or None for one's own.

    A missing, self-referring, or revoked grant silently falls back to the
    session user's own record, so a stale cookie can never expose anything.
    """
    settings = request.app.state.settings
    user = current_user(request)
    if user is None or user.get("token_kind") == "guest":
        return None

    def resolve():
        target = request.cookies.get(VIEW_COOKIE)
        if not target or target == user["id"]:
            return None
        with connect(settings) as connection:
            return connection.execute(
                """SELECT u.* FROM record_shares s JOIN users u ON u.id = s.owner_user_id
                       WHERE s.owner_user_id = ? AND s.grantee_email = ? AND u.disabled_at IS NULL""",
                (target, user["email"]),
            ).fetchone()

    return _cached(("viewing", user["id"]), resolve)

def record_user(request: Request, user):
    """The account whose record a read-only page renders: a shared owner or oneself.

    Only GET routes route through this; every mutating route keeps the
    session user, so a viewer's writes can never land in the owner's record.
    """
    return viewing_row(request) or user

def template_context(request: Request, **values):
    user = current_user(request)
    locale = get_locale()
    return {
        "request": request,
        "user": user,
        "viewing": viewing_row(request),
        # A guest is not the account holder even though the pages render
        # that account's record, so the chrome has to say whose record this
        # is and drop every control the visitor cannot use.  The end date is
        # named rather than alluded to: a visitor who plans to come back
        # needs to know whether the link will still be there.
        "guest": bool(user) and user.get("token_kind") == "guest",
        "guest_until": format_date(user["token_expires_at"]) if user and user.get("token_expires_at") else None,
        "csrf_token": user["csrf_token"] if user else None,
        "locale": locale,
        "html_lang": "uk" if locale == "uk" else "en",
        # "system" follows the operating system; the explicit values pin it.
        "theme": _theme_choice(request),
        "js_i18n": js_strings(),
        "js_locale": "uk-UA" if locale == "uk" else "en-GB",
        # The hand-off offers the whole record, so it belongs on the pages
        # that show results and nowhere else: on /upload or /profile the
        # button would advertise data the reader is not looking at.
        "ai_export": values.get("active") in AI_EXPORT_PAGES,
        "ai_export_sections": SECTIONS,
        # Everything the door actually takes, archives included. Listing
        # only SUPPORTED_SUFFIXES greyed out the .zip in the iOS Files
        # picker on the same page that told the reader to upload one, which
        # put every vendor export out of reach on the primary platform.
        "upload_accept": ",".join(sorted(INTAKE_SUFFIXES)),
        "upload_size_limit": t("upload.megabytes", count=MAX_UPLOAD_BYTES // (1024 * 1024)),
        # The report-a-problem modal's category list, one source for every
        # page that renders it, matching ISSUE_CATEGORIES exactly.
        "report_categories": [(key, t("report.cat_" + key)) for key in ISSUE_CATEGORIES],
        **values,
    }

THEME_CHOICES = ("system", "light", "dark")

def _theme_choice(request: Request) -> str:
    """The reader's stored preference, or "system" to follow the OS."""
    value = (request.cookies.get(THEME_COOKIE) or "").strip().casefold()
    return value if value in THEME_CHOICES else "system"

@router.post("/theme", responses=_RESPONSES_403)
def switch_theme(
    request: Request,
    theme: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
    csrf_token: Annotated[str, Form()] = "",
):
    """Pin the colour scheme, or hand it back to the operating system.

    Server-side rather than a client toggle so the correct theme is in the
    very first byte of HTML: a JS flip repaints after first paint, which is
    a visible flash of the wrong colours on every navigation.
    """
    destination = _safe_next(next)
    user = current_user(request)
    if user and not csrf_matches(user["csrf_token"], csrf_token):
        raise HTTPException(403, t("csrf.invalid"))
    choice = theme.strip().casefold()
    if choice not in THEME_CHOICES:
        choice = "system"
    response = RedirectResponse(destination, status_code=303)
    if choice == "system":
        response.delete_cookie(THEME_COOKIE)
    else:
        response.set_cookie(
            THEME_COOKIE, choice, max_age=365 * 86400, samesite="lax", httponly=True,
            secure=_secure_cookie(request),
        )
    return response

@router.post("/locale")
def switch_locale(
    request: Request,
    lang: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
    csrf_token: Annotated[str, Form()] = "",
):
    destination = _safe_next(next)
    user = current_user(request)
    response = RedirectResponse(destination, status_code=303)
    if user and not csrf_matches(user["csrf_token"], csrf_token):
        # Reject the change without a scare page: a forged language switch
        # is refused, and the visitor still lands where they were going.
        return response
    locale = set_locale(lang)
    response.set_cookie(
        LOCALE_COOKIE, locale, max_age=365 * 86400, samesite="lax", httponly=True,
        secure=_secure_cookie(request),
    )
    return response

def login_redirect(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": t("auth.required")}, status_code=401)
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)

@router.get(_LOGIN_URL, response_class=HTMLResponse)
def login_page(request: Request, error: str | None = None):
    # A guest is signed in to somebody else's record, not to an account of
    # their own, so bouncing them back to it is the one thing they did not
    # ask for.  They get the form; signing in replaces the guest session.
    settings = request.app.state.settings
    if not has_users(settings):
        return RedirectResponse(_SETUP_URL, status_code=303)
    user = current_user(request)
    if user and user.get("token_kind") != "guest":
        return RedirectResponse("/", status_code=303)
    if error in {"invalid", "Invalid email or password"}:
        error = t("login.error")
    elif error == "throttled":
        error = t("login.error_throttled")
    elif error == "closed":
        error = t("register.closed")
    elif error == "token":
        error = t("token.error_link")
    elif error == "setup_taken":
        error = t("setup.error_taken")
    elif error:
        # Only the codes above: anything else in ?error= would print a
        # stranger's sentence ("call this number…") inside the sign-in alert.
        error = None
    return templates.TemplateResponse(
        request,
        "login.html",
        template_context(request, error=error, registration_open=open_registration(settings)),
    )

def _secure_cookie(request: Request) -> bool:
    """Whether a cookie set in answer to this request may travel only over TLS.

    Follows the scheme the request actually arrived on rather than a
    constant: `secure=True` would make sign-in impossible over plain
    http on localhost, and a hardcoded `False` hands the session
    cookie to anyone on the path once this is served over TLS.
    `ANAMNA_SECURE_COOKIES` overrides the detection for the
    case it cannot see — TLS terminating at a proxy uvicorn does not
    trust, where the request still arrives as plain http.
    """
    configured = request.app.state.settings.secure_cookies
    return configured if configured is not None else request.url.scheme == "https"

def _signed_in(request: Request, destination: str, user_id: str) -> RedirectResponse:
    settings = request.app.state.settings
    token, _ = create_session(settings, user_id, user_agent=request.headers.get("user-agent"))
    with connect(settings) as connection:
        connection.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?", (utc_now(), user_id)
        )
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(
        "anamna_session",
        token,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(request),
        max_age=settings.session_days * 86400,
    )
    return response

def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"

@router.post(_LOGIN_URL)
def login(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
):
    settings = request.app.state.settings
    client = _client_key(request)
    if throttled(client):
        return RedirectResponse(_LOGIN_THROTTLED_URL, status_code=303)
    user = authenticate(settings, email, password)
    if user is None:
        record_attempt(client)
        return RedirectResponse("/login?error=invalid", status_code=303)
    # Only failures count here: somebody who knows their own password must
    # never be locked out of their own record by a noisy neighbour.
    clear_attempts(client)
    return _signed_in(request, _safe_next(next), user["id"])

@router.get("/t/{token}")
def token_sign_in(request: Request, token: str):
    """Turn an invitation link into a session.

    A browser cannot be asked to send an ``Authorization`` header by
    following a link, so a guest link has to arrive in the path and be
    exchanged for a cookie at once — after which the secret is out of the
    address bar, out of the history entry that matters, and (through
    ``Referrer-Policy: no-referrer``) out of anything the next page loads.

    An API key is refused here on purpose: it is scoped to ``/api/`` and
    minting a browsing session from one would quietly widen it.
    """
    # Metered like the sign-in form.  The secret itself is 256 bits and is
    # not going to be guessed, but this is an unauthenticated endpoint that
    # reaches the database on every call, and leaving one of those open is
    # how a handful of connections becomes a saturated box.
    settings = request.app.state.settings
    client = _client_key(request)
    if throttled(client):
        return RedirectResponse(_LOGIN_THROTTLED_URL, status_code=303)
    row = access_token_user(settings, token)
    if row is None or row["token_kind"] == "api":
        record_attempt(client)
        return RedirectResponse("/login?error=token", status_code=303)
    clear_attempts(client)
    touch_access_token(settings, row["token_id"])
    return _guest_session(request, row)

def _guest_session(request: Request, row) -> RedirectResponse:
    """Open a read-only session for a guest row (``id`` is the owner,
    ``token_id`` the credential) and send the visitor to the record."""
    settings = request.app.state.settings
    days = float(settings.session_days)
    if row["token_expires_at"]:
        # The session can never outlive the invitation that opened it.
        remaining = (
            datetime.fromisoformat(row["token_expires_at"]) - datetime.now(UTC)
        ).total_seconds() / 86400
        days = max(1.0 / 1440, min(days, remaining))
    session_token, _ = create_session(settings, row["id"], row["token_id"], days, user_agent=request.headers.get("user-agent"))
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "anamna_session",
        session_token,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(request),
        max_age=int(days * 86400),
    )
    # A visitor arriving on a link must never inherit whatever record the
    # previous occupant of this browser had selected.
    response.delete_cookie(VIEW_COOKIE)
    return response

def _public_base(request: Request) -> str:
    """The address a person would type to reach this server.

    Behind the Cloudflare tunnel the app sees plain http from the tunnel,
    which uvicorn does not trust for forwarded headers, so a link printed
    for someone else to open read «http://health…».  The tunnel says what
    the visitor actually used in X-Forwarded-Proto; it only ever upgrades
    the scheme shown, never where the request goes.
    """
    base = str(request.base_url).rstrip("/")
    parts = urlsplit(base)
    if request.headers.get("x-forwarded-proto", "").lower() == "https" and parts.scheme == "http":
        base = urlunsplit(parts._replace(scheme="https"))
    return base

def _doctor_client_key(request: Request) -> str:
    """Who is knocking on /doctor, for the per-client meter only.

    Behind the Cloudflare tunnel every request arrives from the tunnel's
    own address, so ``request.client`` would put every clinic in one
    bucket.  ``CF-Connecting-IP`` is what Cloudflare says the visitor was.
    It can be forged by anyone reaching the origin directly, which is why
    it only ever chooses a bucket: the global meter below it counts every
    failure no matter what this header says.
    """
    forwarded = (request.headers.get("cf-connecting-ip") or "").strip()[:64]
    return "doctor-pin:" + (forwarded or _client_key(request))

def _doctor_page(request: Request, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "doctor.html",
        template_context(
            request,
            error=error,
            redeem_minutes=t_plural(_DOCTOR_MINUTES_KEY, int(DOCTOR_PIN_REDEEM_WINDOW.total_seconds() // 60)),
            access_hours=t_plural("doctor.hours", int(DOCTOR_PIN_ACCESS.total_seconds() // 3600)),
        ),
        status_code=status_code,
    )

@router.get(_DOCTOR_URL, response_class=HTMLResponse)
def doctor_page(request: Request):
    """Where a clinician types the six digits the patient reads out.

    Public, like the sign-in form, and open to a signed-in guest as well:
    a doctor already reading one patient's record enters the next one's
    code without having to find the sign-out button first.
    """
    return _doctor_page(request)

@router.post(_DOCTOR_URL)
def doctor_redeem(request: Request, pin: Annotated[str, Form()] = ""):
    # No CSRF token, exactly like /login: there is no session yet to bind
    # one to, and the worst a forged post can do is open a read-only view
    # of the forger's own record in the victim's browser.
    settings = request.app.state.settings
    client = _doctor_client_key(request)
    if throttled(client, DOCTOR_PIN_CLIENT_LIMIT) or throttled(DOCTOR_PIN_GLOBAL_KEY, DOCTOR_PIN_GLOBAL_LIMIT):
        return _doctor_page(request, t("doctor.error_throttled", minutes=t_plural(_DOCTOR_MINUTES_KEY, int(LOGIN_ATTEMPT_WINDOW.total_seconds() // 60))), status_code=429)
    row = redeem_doctor_pin(settings, pin)
    if row is None:
        # Wrong, expired, already used, malformed: one answer for all of
        # them, so a guess learns nothing but "no".
        record_attempt(client)
        record_attempt(DOCTOR_PIN_GLOBAL_KEY)
        return _doctor_page(request, t("doctor.error_invalid", minutes=t_plural(_DOCTOR_MINUTES_KEY, int(DOCTOR_PIN_REDEEM_WINDOW.total_seconds() // 60))), status_code=400)
    _audit(settings, row["id"], None, "doctor_pin_redeemed", "access_token", row["token_id"], {})
    return _guest_session(request, row)

REGISTER_ERRORS = frozenset(
    {"register.error_exists", _REGISTER_ERROR_PASSWORD, _REGISTER_ERROR_INVALID}
)

def _new_account(settings, email: str, display_name: str, password: str, role: str = "user",
                 *, date_of_birth: str | None = None, sex_at_birth: str | None = None,
                 first_only: bool = False) -> str:
    """An account and the patient record it exists to hold.

    Shared by self-registration, by an administrator adding someone and by
    first-run setup: an account without a patients row has no record to write
    results into, and the paths had no business creating different things.
    """
    user_id = create_user(settings, email, display_name, password, role, first_only=first_only)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), user_id, display_name.strip(), date_of_birth, sex_at_birth, utc_now()),
        )
    return user_id

def announce_setup_code(app) -> None:
    """Print the first-run code to the server log, once per process.

    A code chosen through ANAMNA_SETUP_CODE is never printed: whoever
    set it already knows it, and the log may be read by more people.
    """
    if app.state.setup_code_announced:
        return
    app.state.setup_code_announced = True
    if app.state.settings.setup_code:
        _setup_log.warning("First-run setup: no accounts yet; the setup code is ANAMNA_SETUP_CODE.")
    else:
        _setup_log.warning("First-run setup code: %s", app.state.setup_code)

def _setup_page(request: Request, error: str | None = None, form=None, status_code: int = 200):
    settings = request.app.state.settings
    return templates.TemplateResponse(
        request,
        "setup.html",
        template_context(
            request,
            error=error,
            form=form or {},
            code_from_env=bool(settings.setup_code),
            sex_options=SEX_AT_BIRTH,
            minimum_password=MINIMUM_PASSWORD_LENGTH,
        ),
        status_code=status_code,
    )

@router.get(_SETUP_URL, response_class=HTMLResponse)
def setup_page(request: Request):
    """The first-run page: only while the database has no accounts at all."""
    if has_users(request.app.state.settings):
        return RedirectResponse(_LOGIN_URL, status_code=303)
    announce_setup_code(request.app)
    return _setup_page(request)

@router.post(_SETUP_URL)
def setup(
    request: Request,
    setup_code: Annotated[str, Form()] = "",
    display_name: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    date_of_birth: Annotated[str, Form()] = "",
    sex_at_birth: Annotated[str, Form()] = "",
):
    """Create the administrator and their own record, given the setup code.

    No CSRF token, like /login: there is no session to bind one to, and a
    forged post would need the code.  The code is never echoed back, put in
    a URL or written to the page; only wrong codes count against the meter.
    """
    settings = request.app.state.settings
    if has_users(settings):
        return RedirectResponse(_LOGIN_URL, status_code=303)
    values = {"display_name": display_name.strip(), "email": email.strip(),
              "date_of_birth": date_of_birth.strip(), "sex_at_birth": sex_at_birth.strip()}
    client = "setup-code:" + _client_key(request)
    if throttled(client) or throttled(SETUP_CODE_GLOBAL_KEY, SETUP_CODE_GLOBAL_LIMIT):
        minutes = t_plural(_DOCTOR_MINUTES_KEY, int(LOGIN_ATTEMPT_WINDOW.total_seconds() // 60))
        return _setup_page(request, t("setup.error_throttled", minutes=minutes), values, 429)
    if not setup_code_matches(request.app.state.setup_code, setup_code):
        record_attempt(client)
        record_attempt(SETUP_CODE_GLOBAL_KEY)
        return _setup_page(request, t("setup.error_code"), values, 400)
    dob, dob_ok = _profile_dob(values["date_of_birth"])
    sex = values["sex_at_birth"] or None
    if not values["email"] or not values["display_name"]:
        error = _REGISTER_ERROR_INVALID
    elif len(password) < MINIMUM_PASSWORD_LENGTH:
        error = _REGISTER_ERROR_PASSWORD
    elif not dob_ok:
        error = _PROFILE_ERROR_DOB
    elif sex is not None and sex not in SEX_AT_BIRTH:
        error = _PROFILE_ERROR_CHOICE
    else:
        error = None
    if error:
        return _setup_page(request, t(error), values, 400)
    try:
        user_id = _new_account(settings, values["email"], values["display_name"], password,
                               date_of_birth=dob, sex_at_birth=sex, first_only=True)
    except AlreadySetUp:
        # Lost the race to a simultaneous submission: one administrator only.
        return RedirectResponse(f"{_LOGIN_URL}?error=setup_taken", status_code=303)
    clear_attempts(client)
    _audit(settings, user_id, user_id, "first_run_setup", "user", user_id, {})
    # The operator-pinned agent credential needs an administrator to belong
    # to; on a fresh volume that is only now possible.
    ensure_seeded_token(settings, settings.agent_token)
    return _signed_in(request, "/", user_id)

@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, error: str | None = None):
    settings = request.app.state.settings
    if not has_users(settings):
        return RedirectResponse(_SETUP_URL, status_code=303)
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    if not open_registration(settings):
        return RedirectResponse("/login?error=closed", status_code=303)
    message = t(error) if error in REGISTER_ERRORS else None
    return templates.TemplateResponse(
        request,
        "register.html",
        template_context(request, error=message),
    )

@router.post("/register")
def register(
    request: Request,
    email: Annotated[str, Form()],
    display_name: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    settings = request.app.state.settings
    def failed(key: str) -> RedirectResponse:
        return RedirectResponse(f"/register?error={key}", status_code=303)

    # Checked again on the POST, not only when the form was rendered: the
    # page may have been open in a tab since before registration closed.
    if not has_users(settings):
        return RedirectResponse(_SETUP_URL, status_code=303)
    if not open_registration(settings):
        return RedirectResponse("/login?error=closed", status_code=303)
    client = _client_key(request)
    if throttled(client):
        return RedirectResponse(_LOGIN_THROTTLED_URL, status_code=303)
    # Every attempt counts, not only the failed ones: an open sign-up form
    # on a public server is abused by succeeding, not by failing.
    record_attempt(client)
    if not email.strip() or not display_name.strip():
        return failed(_REGISTER_ERROR_INVALID)
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        return failed(_REGISTER_ERROR_PASSWORD)
    try:
        user_id = _new_account(settings, email, display_name, password)
    except sqlite3.IntegrityError:
        return failed("register.error_exists")
    return _signed_in(request, "/", user_id)

@router.post("/logout", responses=_RESPONSES_401_403)
def logout(request: Request, csrf_token: Annotated[str, Form()]):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    revoke_session(settings, request.cookies.get("anamna_session"))
    response = RedirectResponse(_LOGIN_URL, status_code=303)
    response.delete_cookie("anamna_session")
    response.delete_cookie(VIEW_COOKIE)
    return response

# --- administration -----------------------------------------------------

def _audit(settings, owner_id, actor_id, action, entity_type, entity_id, details, connection=None):
    """One administrative act, recorded.

    `owner_user_id` is the acting administrator rather than the account
    acted on: the column cascades from users(id), so an event owned by a
    deleted account would be deleted with it — the record of the deletion
    would be the first thing the deletion destroyed.
    """
    statement = (
        """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type,
                                        entity_id, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)"""
    )
    values = (owner_id, actor_id, action, entity_type, entity_id, json.dumps(details), utc_now())
    if connection is not None:
        connection.execute(statement, values)
        return
    with connect(settings) as own:
        own.execute(statement, values)

ADMIN_ERRORS = frozenset(
    {
        _ADMIN_ERROR_INVALID,
        _ADMIN_ERROR_PASSWORD,
        "admin.error_exists",
        _ADMIN_ERROR_UNKNOWN,
        "admin.error_self",
        "admin.error_last_admin",
        "admin.error_password_match",
        "admin.error_password_self",
    }
)
ADMIN_DONE = frozenset(
    {
        "added", "blocked", "unblocked", "promoted", "demoted", "deleted", "password_set",
        "registration_open", "registration_closed",
    }
)

def _admin_count(connection) -> int:
    return connection.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled_at IS NULL"
    ).fetchone()[0]

def _user_stats(connection) -> list[dict[str, object]]:
    """Every account with what it actually holds.

    Scalar subqueries rather than joins: two child tables joined onto one
    parent multiply each other's rows, and the counts would both be wrong
    in a way that looks plausible.
    """
    rows = connection.execute(
        """SELECT u.id, u.email, u.display_name, u.role, u.created_at,
                      u.disabled_at, u.last_login_at,
                      (SELECT COUNT(*) FROM documents d WHERE d.owner_user_id = u.id) AS documents,
                      (SELECT COUNT(*) FROM observations o WHERE o.owner_user_id = u.id) AS observations,
                      (SELECT COALESCE(SUM(d.byte_size), 0) FROM documents d
                        WHERE d.owner_user_id = u.id) AS bytes,
                      (SELECT COUNT(*) FROM review_tasks r
                        WHERE r.owner_user_id = u.id AND r.state = 'open') AS open_reviews,
                      (SELECT COUNT(*) FROM sessions s WHERE s.user_id = u.id
                        AND s.expires_at > ?) AS live_sessions
                 FROM users u
                ORDER BY u.created_at, u.rowid""",
        (datetime.now(UTC).isoformat(),),
    ).fetchall()
    return [
        {
            **dict(row),
            "bytes_text": _byte_size_text(row["bytes"]),
            "created_text": format_date(row["created_at"]),
            "last_login_text": format_date(row["last_login_at"]) if row["last_login_at"] else None,
            "documents_text": format_count(row["documents"]),
            "observations_text": format_count(row["observations"]),
            "open_reviews_text": format_count(row["open_reviews"]),
            "live_sessions_text": format_count(row["live_sessions"]),
        }
        for row in rows
    ]

@router.get("/admin/users", response_class=HTMLResponse, responses=_RESPONSES_401_403)
def admin_users(request: Request, error: str | None = None, done: str | None = None):
    settings = request.app.state.settings
    admin = require_admin(request)
    with connect(settings) as connection:
        people = _user_stats(connection)
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        template_context(
            request,
            active="admin",
            people=people,
            admin_id=admin["id"],
            minimum_password=MINIMUM_PASSWORD_LENGTH,
            registration_open=open_registration(settings),
            # Formatted here, not in the template: the same totals rendered
            # raw sat beside per-person counts that had been through
            # `format_count`, so one Ukrainian page showed both "1309" and
            # "1 309" for the same quantity.
            totals={
                "people": format_count(len(people)),
                "documents": format_count(sum(int(person["documents"]) for person in people)),
                "observations": format_count(
                    sum(int(person["observations"]) for person in people)
                ),
                "bytes_text": _byte_size_text(sum(int(person["bytes"]) for person in people)),
            },
            error=t(error) if error in ADMIN_ERRORS else None,
            done=t(f"admin.done_{done}") if done in ADMIN_DONE else None,
        ),
    )

def _admin_redirect(*, error: str | None = None, done: str | None = None) -> RedirectResponse:
    query = ""
    if error:
        query = f"?error={error}"
    elif done:
        query = f"?done={done}"
    return RedirectResponse(f"/admin/users{query}", status_code=303)

@router.post("/admin/users", responses=_RESPONSES_401_403)
def admin_add_user(
    request: Request,
    email: Annotated[str, Form()],
    display_name: Annotated[str, Form()],
    password: Annotated[str, Form()],
    role: Annotated[str, Form()] = "user",
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    admin = require_admin(request)
    require_csrf(admin, csrf_token)
    if not email.strip() or "@" not in email or not display_name.strip():
        return _admin_redirect(error=_ADMIN_ERROR_INVALID)
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        return _admin_redirect(error=_ADMIN_ERROR_PASSWORD)
    try:
        created = _new_account(settings, email, display_name, password, role)
    except sqlite3.IntegrityError:
        return _admin_redirect(error="admin.error_exists")
    _audit(settings, admin["id"], admin["id"], "admin_user_added", "user", created,
           {"email": email.strip().casefold(), "role": role})
    return _admin_redirect(done="added")

def _delete_orphaned_sources(settings, connection, user_id: str) -> int:
    """Remove the deleted account's files from disk, not only its rows.

    An account deletion that leaves the person's laboratory PDFs in
    `sources/` has not deleted their record, it has only stopped showing
    it.  Only paths that resolve inside the configured sources directory
    are touched, and only when no surviving document still points at them.
    """
    paths = [
        row["source_path"]
        for row in connection.execute(
            "SELECT DISTINCT source_path FROM documents WHERE owner_user_id = ?", (user_id,)
        )
    ]
    removed = 0
    for stored in paths:
        still_used = connection.execute(
            "SELECT 1 FROM documents WHERE source_path = ? AND owner_user_id <> ? LIMIT 1",
            (stored, user_id),
        ).fetchone()
        if still_used:
            continue
        path = resolve_source_path(settings, stored)
        try:
            inside = path.resolve().is_relative_to(settings.source_dir.resolve())
        except OSError:
            continue
        if inside and path.is_file():
            path.unlink()
            removed += 1
    return removed

def _admin_apply_action(settings, connection, admin, target, user_id: str, action: str) -> str:
    """Carry out one validated account action; returns what was done."""
    if action == "block":
        # The session join in `session_user` filters on `disabled_at`,
        # so every live session of this account stops on the next
        # request; the rows are cleared too so nothing lingers.
        connection.execute("UPDATE users SET disabled_at = ? WHERE id = ?", (utc_now(), user_id))
        connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return "blocked"
    if action == "unblock":
        connection.execute("UPDATE users SET disabled_at = NULL WHERE id = ?", (user_id,))
        return "unblocked"
    if action in {"promote", "demote"}:
        connection.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            ("admin" if action == "promote" else "user", user_id),
        )
        return "promoted" if action == "promote" else "demoted"
    removed = _delete_orphaned_sources(settings, connection, user_id)
    # Every child table cascades from users(id); the audit line is
    # written against the acting administrator so it is not
    # deleted along with the account it describes.
    connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
    _audit(settings, admin["id"], admin["id"], "admin_user_deleted", "user", user_id,
           {"email": target["email"], "files_removed": removed},
           connection=connection)
    return "deleted"

@router.post("/admin/users/{user_id}", responses=_RESPONSES_401_403)
def admin_change_user(
    request: Request,
    user_id: str,
    action: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
):
    """Block, unblock, promote, demote or delete one account.

    One route rather than five: they share the guard, the CSRF check, the
    last-administrator rule and the audit line, and five copies of those
    is five places for one of them to go missing.
    """
    settings = request.app.state.settings
    admin = require_admin(request)
    require_csrf(admin, csrf_token)
    if action not in {"block", "unblock", "promote", "demote", "delete"}:
        return _admin_redirect(error=_ADMIN_ERROR_INVALID)
    # Nobody may lock themselves out or empty the administrator role: an
    # instance with no reachable administrator can only be repaired with a
    # SQL client, which is not a recovery path a web UI may rely on.
    if user_id == admin["id"] and action in {"block", "demote", "delete"}:
        return _admin_redirect(error="admin.error_self")

    with connect(settings) as connection:
        target = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            return _admin_redirect(error=_ADMIN_ERROR_UNKNOWN)
        losing_admin = target["role"] == "admin" and action in {"block", "demote", "delete"}
        if losing_admin and _admin_count(connection) <= 1:
            return _admin_redirect(error="admin.error_last_admin")

        done = _admin_apply_action(settings, connection, admin, target, user_id, action)

        if done != "deleted":
            _audit(settings, admin["id"], admin["id"], f"admin_user_{done}", "user", user_id,
                   {"email": target["email"]}, connection=connection)
    return _admin_redirect(done=done)

@router.post("/admin/users/{user_id}/password", responses=_RESPONSES_401_403)
def admin_set_user_password(
    request: Request,
    user_id: str,
    new_password: Annotated[str, Form()] = "",
    confirm_password: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """Give a person who forgot their password a new one.

    Typed twice, held to the same minimum as registration, never echoed
    back, never logged or audited (only that it happened).  Every session
    of that account ends, as a change on /profile ends the others: whoever
    held the old password is out.  Not for the administrator's own
    account -- /profile asks for the current password first, and a
    borrowed admin session must not be enough to take an account over.
    """
    settings = request.app.state.settings
    admin = require_admin(request)
    require_csrf(admin, csrf_token)
    if user_id == admin["id"]:
        return _admin_redirect(error="admin.error_password_self")
    if new_password != confirm_password:
        return _admin_redirect(error="admin.error_password_match")
    if len(new_password) < MINIMUM_PASSWORD_LENGTH:
        return _admin_redirect(error=_ADMIN_ERROR_PASSWORD)
    with connect(settings) as connection:
        target = connection.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        return _admin_redirect(error=_ADMIN_ERROR_UNKNOWN)
    set_password(settings, user_id, new_password, keep_token=None)
    _audit(settings, admin["id"], admin["id"], "user_password_set_by_admin", "user", user_id, {"email": target["email"]})
    return _admin_redirect(done="password_set")

@router.post("/admin/registration", responses=_RESPONSES_401_403)
def admin_set_registration(
    request: Request,
    enabled: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    admin = require_admin(request)
    require_csrf(admin, csrf_token)
    wanted = enabled == "1"
    set_open_registration(settings, wanted)
    _audit(settings, admin["id"], admin["id"], "admin_registration_changed", "app_settings",
           "open_registration", {"open": wanted})
    return _admin_redirect(done="registration_open" if wanted else "registration_closed")

# --- profile and sharing ------------------------------------------------

PROFILE_ERRORS = frozenset(
    {
        "profile.error_name",
        _PROFILE_ERROR_DOB,
        "profile.error_blood",
        "profile.error_measurement",
        _PROFILE_ERROR_CHOICE,
        "profile.error_timezone",
        "profile.error_share_email",
        "profile.error_share_self",
        "profile.error_password_current",
        "profile.error_password_match",
        "profile.error_password_short",
        "token.error_label",
        "token.error_kind",
        _TOKEN_ERROR_EXPIRY,
        "token.error_owner",
        "token.error_unknown",
        "doctor.error_unknown",
        "paperless.error_no_token",
        "paperless.error_upload_off",
        "paperless.error_test",
        "paperless.error_blocked",
        "integrations.error_denied",
        "integrations.error_state",
        "integrations.error_exchange",
        "integrations.error_garmin_key",
        "integrations.error_garmin_key_refused",
        "integrations.error_garmin_unreachable",
        "openwearables.error_user",
        "openwearables.error_unreachable",
        "profile.error_session",
    }
)

#: Confirmation per `saved` value on the Security tab's session list.
SESSION_SAVED = {"session": "profile.session_saved_one", "sessions": "profile.session_saved_others"}

def _session_device(user_agent: str) -> str:
    """"Safari on iPhone" from a User-Agent, enough to recognise one's own
    devices; the raw header is never printed.  Order matters: Edge and
    Opera carry "Chrome", Chrome carries "Safari", iPadOS may claim Mac."""
    ua = user_agent or ""
    if not ua:
        return t("profile.session_unrecorded_device")
    browser = next((name for token, name in (
        ("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("FxiOS", "Firefox"),
        ("CriOS", "Chrome"), ("Chrome/", "Chrome"), ("Safari/", "Safari"),
    ) if token in ua), "")
    platform = next((name for token, name in (
        ("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
        ("Macintosh", "macOS"), ("CrOS", "ChromeOS"), ("Linux", "Linux"),
    ) if token in ua), "")
    if not browser:
        return t("profile.session_unknown_device")
    return t("profile.session_device", browser=browser, platform=platform or t("profile.session_unknown_platform"))

def _session_rows(request: Request, user) -> list[dict[str, object]]:
    settings = request.app.state.settings
    rows = list_sessions(settings, user["id"], request.cookies.get("anamna_session"))
    for row in rows:
        row["device"] = _session_device(row["user_agent"])
        row["created_text"] = format_date(row["created_at"])
        row["expires_text"] = format_date(row["expires_at"])
    return rows

#: Confirmation text per paperless `saved` value, and the list that keeps
#: the generic "Profile saved" from speaking over them.
PAPERLESS_SAVED = {
    "paperless": "paperless.saved_settings",
    "paperless_test": "paperless.saved_test",
    "paperless_sync": "paperless.saved_sync",
}

#: Same shape for wearable providers (Garmin, Oura) and for the
#: OpenWearables server, which is linked from the same tab.
INTEGRATION_SAVED = {
    "integration_connected": "integrations.saved_connected",
    "integration_disconnected": "integrations.saved_disconnected",
    "integration_sync": "integrations.saved_sync",
    "garmin_key_saved": "integrations.saved_garmin_key",
    "garmin_key_removed": "integrations.saved_garmin_key_removed",
    "openwearables_linked": "openwearables.saved_linked",
    "openwearables_replaced": "openwearables.saved_replaced",
    "openwearables_unlinked": "openwearables.saved_unlinked",
    "openwearables_sync": "openwearables.saved_sync",
}

def _oura_panel(settings, user_id: str) -> dict[str, object]:
    """What the profile card says about a connected Oura account: how much
    data has landed, when it last moved, and whether webhooks can reach us."""
    connection = integrations.connection_row(settings, user_id, "oura")
    if connection is None:
        return {}
    state = oura.sync_state(settings, user_id)
    with connect(settings) as db:
        days = db.execute(
            "SELECT COUNT(DISTINCT day), MAX(day) FROM device_metric_days WHERE owner_user_id=? AND source_name='Oura'",
            (user_id,),
        ).fetchone()
    subscriptions = state.get("subscriptions") if isinstance(state.get("subscriptions"), dict) else {}
    ring = state.get("ring") if isinstance(state.get("ring"), dict) else {}
    return {
        "needs_reauthorize": str(connection["status"]) == "reauthorize",
        "sync_days": int(days[0] or 0),
        "sync_latest_day": str(days[1] or ""),
        "sync_last_at": str(state.get("last_sync_at") or ""),
        "backfill_done": bool(state.get("last_backfill_at")),
        "webhooks_active": bool(subscriptions.get("active")),
        "ring": ring,
    }

def _garmin_panel(settings, user_id: str) -> dict[str, object]:
    """The business-tier Garmin card: what has arrived, when Garmin last
    delivered, what the person shared, and how far history came back."""
    connection = integrations.connection_row(settings, user_id, "garmin")
    if connection is None:
        return {}
    state = garmin.sync_state(settings, user_id)
    with connect(settings) as db:
        days = db.execute(
            "SELECT COUNT(DISTINCT d.day), MAX(d.day) FROM device_metric_days d JOIN device_imports i ON i.id=d.import_id WHERE i.owner_user_id=? AND i.adapter_key=?",
            (user_id, garmin.ADAPTER_KEY),
        ).fetchone()
    granted = set(str(connection["scopes"] or "").split())
    backfill = state.get("backfill") if isinstance(state.get("backfill"), dict) else {}
    statuses = {str((entry or {}).get("status") or "") for entry in backfill.values()}
    return {
        "needs_reauthorize": str(connection["status"]) == "reauthorize",
        "sync_days": int(days[0] or 0),
        "sync_latest_day": str(days[1] or ""),
        "last_delivery_at": str(state.get("last_delivery_at") or ""),
        "permissions": [
            {"key": key, "label": t(f"integrations.garmin_permission_{key.lower()}"), "granted": key in granted}
            for key in ("HEALTH_EXPORT", "ACTIVITY_EXPORT", "MCT_EXPORT")
        ],
        "backfill_state": _garmin_backfill_state(state, statuses),
    }

def _garmin_backfill_state(state, statuses) -> str:
    if not state.get("last_backfill_at") or "paused" in statuses:
        return "running"
    return "unavailable" if statuses == {"unavailable"} else "done"

def _openwearables_panel(settings, user) -> dict[str, object] | None:
    """The OpenWearables card, or ``None`` when the operator configured no
    server — an integration nobody can use is not an empty card.

    Unlinked, the card is a list of the accounts that server holds, with
    the one whose address matches this person's preselected.  A server that
    will not answer must still render a page: the card says so and offers
    nothing to submit, rather than taking the whole profile down with it.
    """
    if not openwearables.configured(settings):
        return None
    if openwearables.linked(settings, user["id"]) is None:
        try:
            people = openwearables.remote_users(settings)
        except openwearables.OpenWearablesError as exc:
            openwearables.logger.warning("openwearables: user list unavailable: %s", exc)
            return {"linked": False, "unreachable": True, "people": []}
        mine = str(user["email"]).casefold()
        return {
            "linked": False,
            "unreachable": False,
            "people": [
                {**person, "selected": str(person["email"]).casefold() == mine}
                for person in people
            ],
        }
    state = openwearables.sync_state(settings, user["id"])
    with connect(settings) as db:
        days = db.execute(
            """SELECT COUNT(DISTINCT day), MAX(day) FROM device_metric_days
                    WHERE owner_user_id=? AND source_vendor=?""",
            (user["id"], openwearables.SOURCE_NAME),
        ).fetchone()
    return {
        "linked": True,
        "unreachable": False,
        "remote_email": str(state.get("remote_email") or ""),
        "sync_days": int(days[0] or 0),
        "sync_latest_day": str(days[1] or ""),
        "sync_last_at": str(state.get("last_sync_at") or ""),
        "backfill_done": bool(state.get("last_backfill_at")),
        "failures": openwearables.failed_datatype_labels(settings, user["id"]),
    }

#: The profile's panels. The strip links to these so every panel stays
#: reachable with JavaScript off; the script upgrades the links to instant
#: switching without changing where they point.
PROFILE_TABS = ("personal", "sharing", "tokens", "security", "connections")

def _profile_active_tab(error, saved, new_token, tab: str, new_pin) -> str:
    # Which tab is open on arrival. Decided from the raw keys, before
    # translation, so a redirect lands on the panel that owns the message
    # instead of on a personal-details form with an error about a password
    # scrolled off somewhere below it.
    key = error or ""
    if key.startswith("profile.error_password") or key == "profile.error_session" or saved in ("password", *SESSION_SAVED):
        return "security"
    if key.startswith(("profile.error_share", "doctor.")) or saved == "doctor_revoked" or new_pin is not None:
        return "sharing"
    if key.startswith("token.") or saved in ("revoked", "token") or new_token is not None:
        return "tokens"
    if (
        key.startswith("paperless.")
        or key.startswith("integrations.")
        or key.startswith("openwearables.")
        or saved in PAPERLESS_SAVED
        or saved in INTEGRATION_SAVED
    ):
        return "connections"
    if tab in PROFILE_TABS:
        # The tab strip links here rather than relying on script, so the
        # panels stay reachable with JavaScript off.  A message about a
        # specific panel still wins over the link, above.
        return tab
    return "personal"

def _profile_saved_flag(saved) -> bool:
    # Distinct confirmations, never more than one at once: "Profile
    # saved" over a revoked credential says the wrong thing about
    # the thing that just happened.
    return (
        bool(saved)
        and saved not in ("password", "revoked", "token", "doctor_revoked", *SESSION_SAVED)
        and saved not in PAPERLESS_SAVED
        and saved not in INTEGRATION_SAVED
    )

def _profile_paperless_fields(settings, user_id: str, saved, paperless_on: bool, paperless_account) -> dict[str, object]:
    return {
        "paperless_on": paperless_on,
        "paperless_token_tail": str(paperless_account["token"])[-6:] if paperless_account["token"] else "",
        "paperless_upload": bool(paperless_account["upload_enabled"]),
        "paperless_url": paperless.paperless_settings(settings)["url"] if paperless_on else "",
        "paperless_counts": (
            paperless.link_counts(settings, user_id)
            if paperless_on and paperless_account["token"]
            else None
        ),
        "paperless_saved": t(PAPERLESS_SAVED[saved]) if saved in PAPERLESS_SAVED else None,
    }

def _profile_integration_providers(settings, user_id: str) -> list[dict[str, object]]:
    return [
        {
            "key": spec.key,
            "name": spec.display_name,
            "connected": integrations.connection_row(settings, user_id, spec.key),
            **(_oura_panel(settings, user_id) if spec.key == "oura" else {}),
            **(_garmin_panel(settings, user_id) if spec.key == "garmin" else {}),
        }
        for spec in integrations.configured_providers(settings)
    ]

def _garmin_personal_available(settings, user_id: str) -> bool:
    # A business-tier Garmin connection already delivers everything
    # a personal key could; offering both would write it twice.
    return (
        (garmin_personal.enabled(settings) or integrations.connection_row(settings, user_id, garmin_personal.PROVIDER_KEY) is not None)
        and integrations.connection_row(settings, user_id, "garmin") is None
    )

def _profile_response(request: Request, user, error=None, saved=None, new_token=None, tab="", new_pin=None):
    """Render the profile.

    A separate function because minting a credential has to answer with the
    page itself rather than a redirect: the secret is shown once and never
    stored, so it cannot survive a round trip through a URL — and putting
    it in one would write it into browser history and every proxy log on
    the way.
    """
    settings = request.app.state.settings
    with connect(settings) as connection:
        patient = _patient_row(connection, user["id"])
        lab_blood = _lab_blood_type(connection, user["id"])
        measured = _measured_body(connection, user["id"])
        zone = user_timezone(connection, user["id"])
        timezone_name = str(zone)
        shares = connection.execute(
            "SELECT * FROM record_shares WHERE owner_user_id=? ORDER BY created_at",
            (user["id"],),
        ).fetchall()
        shared_with_me = connection.execute(
            """SELECT s.owner_user_id, u.display_name FROM record_shares s
                   JOIN users u ON u.id = s.owner_user_id
                   WHERE s.grantee_email = ? AND u.disabled_at IS NULL
                   ORDER BY u.display_name""",
            (user["email"],),
        ).fetchall()
    active_tab = _profile_active_tab(error, saved, new_token, tab, new_pin)
    paperless_on = paperless.paperless_active(settings)
    paperless_account = (
        paperless.account(settings, user["id"]) if paperless_on else {"token": "", "upload_enabled": False}
    )
    return templates.TemplateResponse(
        request,
        "profile.html",
        template_context(
            request,
            active="profile",
            active_tab=active_tab,
            patient=patient,
            lab_blood=lab_blood,
            measured=measured,
            body_measurements=BODY_MEASUREMENTS,
            user_timezone_name=timezone_name,
            timezone_options=timezone_choices(),
            profile_choices=PROFILE_CHOICES,
            shares=shares,
            shared_with_me=shared_with_me,
            blood_types=BLOOD_TYPES,
            sex_options=SEX_AT_BIRTH,
            minimum_password=MINIMUM_PASSWORD_LENGTH,
            # PIN accesses have their own list under "Share with a doctor".
            tokens=[_token_row(row) for row in list_access_tokens(settings, user["id"]) if not row["pin_hash"]],
            doctor_pins=[_doctor_pin_row(row, zone) for row in list_doctor_pins(settings, user["id"])],
            new_pin=new_pin,
            doctor_url=_public_base(request) + _DOCTOR_URL,
            doctor_saved=saved == "doctor_revoked",
            redeem_minutes=t_plural(_DOCTOR_MINUTES_KEY, int(DOCTOR_PIN_REDEEM_WINDOW.total_seconds() // 60)),
            access_hours=t_plural("doctor.hours", int(DOCTOR_PIN_ACCESS.total_seconds() // 3600)),
            token_kinds=TOKEN_KINDS,
            new_token=new_token,
            token_base=_public_base(request),
            error=t(error) if error in PROFILE_ERRORS else None,
            saved=_profile_saved_flag(saved),
            password_saved=saved == "password",
            session_saved=t(SESSION_SAVED[saved]) if saved in SESSION_SAVED else None,
            sessions=_session_rows(request, user),
            token_saved=t(f"token.saved_{saved}") if saved in ("revoked", "token") else None,
            **_profile_paperless_fields(settings, user["id"], saved, paperless_on, paperless_account),
            integration_saved=t(INTEGRATION_SAVED[saved]) if saved in INTEGRATION_SAVED else None,
            integrations_providers=_profile_integration_providers(settings, user["id"]),
            openwearables_card=_openwearables_panel(settings, user),
            garmin_personal_card=garmin_personal.panel(settings, user["id"]),
            garmin_personal_available=_garmin_personal_available(settings, user["id"]),
            ow_hooks=ow_hooks.operational_status(settings, user["id"]),
            telegram=request.app.state.telegram.profile(user["id"]),
        ),
    )

@router.get(_PROFILE_URL, response_class=HTMLResponse, responses=_RESPONSES_401)
def profile_page(
    request: Request,
    error: str | None = None,
    saved: str | None = None,
    tab: str = "",
):
    return _profile_response(request, require_user(request), error=error, saved=saved, tab=tab)

# --- access tokens ------------------------------------------------------

def _token_row(row) -> dict[str, object]:
    """One credential as the list shows it: never the secret, always the
    state — because "does this still work?" is the only question a person
    asks of a token they cannot read."""
    expires_at = row["expires_at"]
    expired = bool(expires_at) and expires_at <= datetime.now(UTC).isoformat()
    return {
        "id": row["id"],
        "kind": row["kind"],
        "kind_label": t(f"token.kind_{row['kind']}"),
        "label": row["label"],
        "seeded": bool(row["seeded"]),
        "pin": bool(row["pin_hash"]),
        "hint": row["hint"],
        "owner_email": row["owner_email"],
        "owner_name": row["owner_name"],
        "owner_user_id": row["owner_user_id"],
        "created_text": format_date(row["created_at"]),
        "expires_at": expires_at,
        "expires_text": format_date(expires_at) if expires_at else t("token.never_expires"),
        "expired": expired,
        "last_used_text": format_date(row["last_used_at"]) if row["last_used_at"] else t("token.never_used"),
        # An expiry has to be editable, and <input type="date"> only speaks
        # calendar dates — the stored stamp carries a time it would drop.
        "expires_date": expires_at[:10] if expires_at else "",
    }

def _token_expiry(value: str) -> str | None:
    """A submitted calendar date as the end of that day, or None for never.

    End of day rather than midnight: a doctor told the link works until
    Friday expects it to work on Friday, and an expiry at 00:00 takes the
    whole day away without saying so.
    """
    value = value.strip()
    if not value:
        return None
    moment = datetime.combine(date.fromisoformat(value), datetime.max.time(), tzinfo=UTC)
    return moment.replace(microsecond=0).isoformat()

def _token_target(request: Request, user, owner_user_id: str) -> str:
    """Whose record a credential is being minted against.

    An administrator may name anyone; everybody else gets themselves, and
    an ignored field is safer here than a trusted one — a hand-written form
    post carrying somebody else's id must not become a grant.
    """
    settings = request.app.state.settings
    target = (owner_user_id or "").strip()
    if not target or target == user["id"] or user["role"] != "admin":
        return user["id"]
    with connect(settings) as connection:
        exists = connection.execute("SELECT 1 FROM users WHERE id=?", (target,)).fetchone()
    if exists is None:
        raise HTTPException(404, t("token.error_owner"))
    return target

@router.post("/tokens", response_class=HTMLResponse, responses=_RESPONSES_401_403_404)
def create_token(
    request: Request,
    kind: Annotated[str, Form()],
    label: Annotated[str, Form()] = "",
    expires_on: Annotated[str, Form()] = "",
    owner_user_id: Annotated[str, Form()] = "",
    origin: Annotated[str, Form()] = "profile",
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    admin = user["role"] == "admin"

    def failed(key: str):
        if origin == "admin" and admin:
            return _admin_tokens_response(request, user, error=key)
        return _profile_response(request, user, error=key)

    if kind not in TOKEN_KINDS:
        return failed("token.error_kind")
    if not label.strip():
        return failed("token.error_label")
    try:
        expires_at = _token_expiry(expires_on)
    except ValueError:
        return failed(_TOKEN_ERROR_EXPIRY)
    if expires_at is not None and expires_at <= utc_now():
        return failed(_TOKEN_ERROR_EXPIRY)
    # A link handed to somebody outside the household has to stop working
    # on its own; the two machine credentials are the owner's to keep.
    if kind == "guest" and expires_at is None:
        return failed(_TOKEN_ERROR_EXPIRY)
    target = _token_target(request, user, owner_user_id)
    token_id, secret = create_access_token(
        settings, target, kind, label, expires_at, created_by_user_id=user["id"]
    )
    _audit(settings, user["id"], user["id"], "token_created", "access_token", token_id,
           {"kind": kind, "label": label.strip(), "owner": target, "expires_at": expires_at})
    minted = {"secret": secret, "kind": kind, "label": label.strip(), "id": token_id}
    if origin == "admin" and admin:
        return _admin_tokens_response(request, user, new_token=minted)
    return _profile_response(request, user, new_token=minted)

@router.post("/tokens/{token_id}", responses=_RESPONSES_400_401_403)
def change_token(
    request: Request,
    token_id: str,
    action: Annotated[str, Form()],
    label: Annotated[str, Form()] = "",
    expires_on: Annotated[str, Form()] = "",
    origin: Annotated[str, Form()] = "profile",
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    # An administrator reaches every credential; everybody else is scoped
    # to their own by passing their id into the WHERE clause, so a guessed
    # token id changes nothing.
    admin = user["role"] == "admin"
    scope = None if admin else user["id"]
    # Only an administrator is sent back to the page only they can open;
    # anyone else lands on their profile rather than on a 403 explaining
    # that the page they were bounced to is not for them.
    destination = "/admin/tokens" if origin == "admin" and admin else _PROFILE_URL

    def done(key: str) -> RedirectResponse:
        return RedirectResponse(f"{destination}?saved={key}", status_code=303)

    if action == "revoke":
        if not revoke_access_token(settings, token_id, scope):
            return RedirectResponse(f"{destination}?error=token.error_unknown", status_code=303)
        _audit(settings, user["id"], user["id"], "token_revoked", "access_token", token_id, {})
        return done("revoked")
    if action == "update":
        if not label.strip():
            return RedirectResponse(f"{destination}?error=token.error_label", status_code=303)
        try:
            expires_at = _token_expiry(expires_on)
        except ValueError:
            return RedirectResponse(f"{destination}?error=token.error_expiry", status_code=303)
        if not update_access_token(settings, token_id, label, expires_at, scope):
            return RedirectResponse(f"{destination}?error=token.error_unknown", status_code=303)
        _audit(settings, user["id"], user["id"], "token_updated", "access_token", token_id,
               {"label": label.strip(), "expires_at": expires_at})
        return done("token")
    raise HTTPException(400, t("token.error_unknown"))

def _local_moment(value: str, zone) -> str:
    """A stored UTC stamp as the owner's local date and time."""
    moment = datetime.fromisoformat(value).astimezone(zone)
    return f"{format_date(moment.date().isoformat())}, {moment:%H:%M}"

def _doctor_pin_row(row, zone) -> dict[str, object]:
    return {
        "id": row["id"],
        "redeemed": bool(row["pin_redeemed_at"]),
        "created_text": _local_moment(row["created_at"], zone),
        "redeem_by_text": _local_moment(row["pin_redeem_by"], zone),
        "redeemed_text": _local_moment(row["pin_redeemed_at"], zone) if row["pin_redeemed_at"] else "",
        "expires_text": _local_moment(row["expires_at"], zone),
    }

@router.post("/profile/doctor-pin", response_class=HTMLResponse, responses=_RESPONSES_401_403)
def doctor_pin_create(request: Request, csrf_token: Annotated[str, Form()] = ""):
    """Show a six-digit code for the doctor's office.

    Answered with the page, never a redirect, for the same reason a minted
    token is: only the code's hash is kept, so this is the one moment the
    digits exist, and a URL would write them into history.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    token_id, pin, redeem_by, expires_at = create_doctor_pin(settings, user["id"])
    _audit(settings, user["id"], user["id"], "doctor_pin_created", "access_token", token_id,
           {"redeem_by": redeem_by.isoformat(timespec="seconds"),
            "expires_at": expires_at.isoformat(timespec="seconds")})
    with connect(settings) as connection:
        zone = user_timezone(connection, user["id"])
    new_pin = {
        "digits": pin,
        "redeem_by_text": _local_moment(redeem_by.isoformat(), zone),
        "expires_text": _local_moment(expires_at.isoformat(), zone),
    }
    return _profile_response(request, user, new_pin=new_pin)

@router.post("/profile/doctor-pin/{token_id}/revoke", responses=_RESPONSES_401_403)
def doctor_pin_revoke(request: Request, token_id: str, csrf_token: Annotated[str, Form()] = ""):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    # Scoped to the owner in the WHERE clause; the sessions the code opened
    # go with the row through the foreign key.
    if not revoke_access_token(settings, token_id, user["id"]):
        return RedirectResponse("/profile?error=doctor.error_unknown", status_code=303)
    _audit(settings, user["id"], user["id"], "doctor_pin_revoked", "access_token", token_id, {})
    return RedirectResponse("/profile?saved=doctor_revoked", status_code=303)

def _admin_tokens_response(request: Request, user, error=None, saved=None, new_token=None):
    settings = request.app.state.settings
    with connect(settings) as connection:
        people = connection.execute(
            "SELECT id, email, display_name FROM users ORDER BY display_name COLLATE NOCASE"
        ).fetchall()
    return templates.TemplateResponse(
        request,
        "admin_tokens.html",
        template_context(
            request,
            active="admin_tokens",
            people=people,
            tokens=[_token_row(row) for row in list_access_tokens(settings)],
            token_kinds=TOKEN_KINDS,
            new_token=new_token,
            token_base=_public_base(request),
            admin_id=user["id"],
            error=t(error) if error in PROFILE_ERRORS else None,
            saved=t(f"token.saved_{saved}") if saved in ("revoked", "token") else None,
        ),
    )

@router.get("/admin/tokens", response_class=HTMLResponse, responses=_RESPONSES_401_403)
def admin_tokens(request: Request, error: str | None = None, saved: str | None = None):
    return _admin_tokens_response(request, require_admin(request), error=error, saved=saved)

AI_ADMIN_ERRORS = frozenset({
    "aiassist.error_provider", "aiassist.error_test", "aiassist.error_cap",
    "aiassist.error_model", "aiassist.error_max_tokens", "aiassist.error_test_task",
})
AI_ADMIN_DONE = frozenset({"saved", "test"})

#: Stored provider errors, read as one of a few kinds.  The stored text is
#: whatever the provider or the model sent back -- an English sentence at
#: best, a slice of the model's own reply about a medical document at
#: worst -- so the page names the kind, in the reader's language, and
#: never prints the text.  First match wins; order matters.
AI_ERROR_KINDS = (
    (re.compile(r"^no reply$"), "aiassist.err_no_reply"),
    (re.compile(r"finish_reason=length"), "aiassist.err_truncated"),
    (re.compile(r"finish_reason=(content_filter|refusal)"), "aiassist.err_refused"),
    (re.compile(r"finish_reason="), "aiassist.err_incomplete"),
    (re.compile(r"^(daily|minute)$|daily cap|budget", re.I), "aiassist.err_budget"),
    (re.compile(r"HTTP 40[13]\b|authenticat|permission ?denied|api[ _-]?key", re.I), "aiassist.err_credentials"),
    (re.compile(r"HTTP 429\b|rate.?limit", re.I), "aiassist.err_rate"),
    (re.compile(r"HTTP 404\b|no endpoints|not ?found|model_not_found|unknown provider", re.I), "aiassist.err_model"),
    (re.compile(r"timed? ?out", re.I), "aiassist.err_timeout"),
    (re.compile(r"json|unparseable|malformed|reply field|reply carried|not text", re.I), "aiassist.err_unparseable"),
    (re.compile(r"HTTP 5\d\d\b|connection|urlerror|unreachable|overloaded|server error", re.I), "aiassist.err_unreachable"),
)

def _ai_error_text(stored: str) -> str:
    key = next((key for pattern, key in AI_ERROR_KINDS if pattern.search(stored)), "aiassist.err_other")
    return t(key)

@router.get("/admin/ai", response_class=HTMLResponse, responses=_RESPONSES_401_403)
def admin_ai(
    request: Request,
    error: str | None = None,
    done: str | None = None,
    task: str = "",
    model: str = "",
):
    settings = request.app.state.settings
    require_admin(request)
    config = ai_settings(settings)
    tested_task = task if task in AI_TASKS else ""
    usage = usage_summary(settings)
    for item in usage["recent"]:
        item["error_text"] = _ai_error_text(item["error"]) if item["error"] else ""
    return templates.TemplateResponse(
        request,
        "admin_ai.html",
        template_context(
            request,
            active="admin_ai",
            ai=config,
            ai_on=ai_active(settings),
            # Enough of each key to recognise it, never enough to use it.
            key_tails={
                name: value[-6:] if value else "" for name, value in config["keys"].items()
            },
            providers=AI_PROVIDER_NAMES,
            paid_providers=AI_PAID_PROVIDERS,
            provider_hosts=AI_PROVIDER_HOSTS,
            ai_tasks=AI_TASKS,
            efforts=AI_EFFORTS,
            default_models=AI_DEFAULT_MODELS,
            # Live lists only for providers with a key; free text always
            # works.  Rendered from memory only (None = not fetched yet):
            # two live list calls of up to 8 s each held the whole page,
            # so the page asks /admin/ai/models after it has loaded.
            model_lists={name: cached_ai_models(settings, name) for name in AI_PAID_PROVIDERS},
            # OpenRouter has no model list call here: its router and fallbacks.
            openrouter_models=[AI_DEFAULT_MODELS["openrouter"], *AI_FALLBACK_MODELS],
            usage=usage,
            tested_task=tested_task,
            # The answering model came back in the redirect; it is shown
            # only as text and only when it looks like a model id.
            tested_model=model[:120] if tested_task and re.fullmatch(r"[\w./:@+-]{1,120}", model) else "",
            error=t(error) if error in AI_ADMIN_ERRORS else None,
            done=t(f"aiassist.done_{done}") if done in AI_ADMIN_DONE else None,
        ),
    )

@router.post("/admin/ai", responses=_RESPONSES_401_403)
async def admin_ai_save(request: Request):
    """Reads the form as a mapping: three providers times their key fields
    plus three tasks times five route fields is a signature nobody can
    keep in step with the page by hand."""
    settings = request.app.state.settings
    admin = require_admin(request)
    form = await request.form()
    require_csrf(admin, str(form.get("csrf_token") or ""))
    parsed = parse_ai_admin_form(form)
    if isinstance(parsed, str):
        return RedirectResponse(f"/admin/ai?error={parsed}", status_code=303)
    values, audit = parsed
    save_ai_settings(settings, values)
    # The keys themselves must never reach the audit log; only which changed.
    _audit(settings, admin["id"], admin["id"], "admin_ai_changed", "app_settings", "ai", audit)
    return RedirectResponse("/admin/ai?done=saved", status_code=303)

@router.get("/admin/ai/models", responses=_RESPONSES_401_403_404)
def admin_ai_models(request: Request, provider: str = ""):
    """One provider's model list for the picker, fetched after the page
    has rendered.  Cached for an hour; empty without a key or on failure,
    and the field stays free text either way."""
    settings = request.app.state.settings
    require_admin(request)
    if provider not in AI_PAID_PROVIDERS:
        raise HTTPException(404)
    return JSONResponse({"provider": provider, "models": list_ai_models(settings, provider)})

@router.post("/admin/ai/test", responses=_RESPONSES_401_403)
def admin_ai_test(
    request: Request,
    task: Annotated[str, Form()] = "default",
    csrf_token: Annotated[str, Form()] = "",
):
    """One real round-trip over the chosen task's route, so "configured"
    and "working" stay different claims.  The outcome, including the
    provider's error text, lands in the usage table on the same page, and
    the model that actually answered is named on the page."""
    settings = request.app.state.settings
    admin = require_admin(request)
    require_csrf(admin, csrf_token)
    if task not in AI_TASKS:
        return RedirectResponse("/admin/ai?error=aiassist.error_test_task", status_code=303)
    try:
        result = ai_complete(
            settings,
            # The feature name routes the call: `admin_test` is the default
            # task, the others ride their own task's route.
            "admin_test" if task == "default" else f"admin_test_{task}",
            [{"role": "user", "content": "Reply with exactly: OK"}],
            timeout=60,
        )
    except AIUnavailable:
        return RedirectResponse(
            f"/admin/ai?error=aiassist.error_test&task={task}#ai-usage", status_code=303
        )
    return RedirectResponse(
        f"/admin/ai?done=test&task={task}&model={quote(result.model, safe='')}#ai-tasks",
        status_code=303,
    )

# --- paperless (admin) --------------------------------------------------

PAPERLESS_ADMIN_ERRORS = frozenset(
    {"paperless.error_url", "paperless.error_unreachable", "paperless.error_blocked"}
)
PAPERLESS_ADMIN_DONE = ("saved", "saved_reconsent", "test", "reachable", "sync")

@router.get("/admin/paperless", response_class=HTMLResponse, responses=_RESPONSES_401_403)
def admin_paperless(request: Request, error: str | None = None, done: str | None = None):
    settings = request.app.state.settings
    require_admin(request)
    config = paperless.paperless_settings(settings)
    with connect(settings) as connection:
        connected = connection.execute(
            "SELECT COUNT(*) FROM paperless_accounts WHERE api_token <> ''"
        ).fetchone()[0]
    return templates.TemplateResponse(
        request,
        "admin_paperless.html",
        template_context(
            request,
            active="admin_paperless",
            paperless=config,
            paperless_on=config["enabled"] == "1" and bool(config["url"]),
            paperless_plaintext=paperless.url_is_plaintext_remote(config["url"]),
            connected=connected,
            counts=paperless.instance_counts(settings),
            error=t(error) if error in PAPERLESS_ADMIN_ERRORS else None,
            done=t(f"paperless.done_{done}") if done in PAPERLESS_ADMIN_DONE else None,
        ),
    )

@router.post("/admin/paperless/sync", responses=_RESPONSES_401_403)
def admin_paperless_sync(request: Request, csrf_token: Annotated[str, Form()] = ""):
    """One press when Paperless arrives mid-life: every consenting
    account's back catalog is sent, and every earlier failure retried.
    Consent stays per person — accounts without the checkbox are skipped."""
    settings = request.app.state.settings
    admin = require_admin(request)
    require_csrf(admin, csrf_token)
    if not paperless.paperless_active(settings):
        return RedirectResponse(_PAPERLESS_URL_ERROR_URL, status_code=303)
    paperless.start_sync_all(settings)
    _audit(settings, admin["id"], admin["id"], "admin_paperless_sync", "app_settings", "paperless", {})
    return RedirectResponse("/admin/paperless?done=sync", status_code=303)

@router.post("/admin/paperless", responses=_RESPONSES_401_403)
def admin_paperless_save(
    request: Request,
    enabled: Annotated[str, Form()] = "",
    url: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    admin = require_admin(request)
    require_csrf(admin, csrf_token)
    url = url.strip().rstrip("/")
    if url and not paperless.url_is_acceptable(url):
        return RedirectResponse(_PAPERLESS_URL_ERROR_URL, status_code=303)
    previous = paperless.paperless_settings(settings)["url"]
    # Everyone consented to *this* server.  Pointing the instance at
    # another one must not silently replay their tokens, or ship their
    # back catalogue, to a host they never agreed to.
    forgotten = paperless.forget_all_consent(settings) if url != previous and previous else 0
    paperless.save_paperless_settings(
        settings,
        {"paperless_enabled": "1" if enabled == "1" else "0", "paperless_url": url},
    )
    _audit(settings,
        admin["id"], admin["id"], "admin_paperless_changed", "app_settings", "paperless",
        {"enabled": enabled == "1", "url": url, "consent_cleared": forgotten},
    )
    done = "saved_reconsent" if forgotten else "saved"
    return RedirectResponse(f"/admin/paperless?done={done}", status_code=303)

@router.post("/admin/paperless/test", responses=_RESPONSES_401_403)
def admin_paperless_test(request: Request, csrf_token: Annotated[str, Form()] = ""):
    """One real round trip.  With the admin's own token stored it proves
    the whole path; without one, Paperless still proves it is there by
    demanding one, and the page says which of the two was shown."""
    settings = request.app.state.settings
    admin = require_admin(request)
    require_csrf(admin, csrf_token)
    config = paperless.paperless_settings(settings)
    if not config["url"]:
        return RedirectResponse(_PAPERLESS_URL_ERROR_URL, status_code=303)
    result = paperless.probe(config["url"], str(paperless.account(settings, admin["id"])["token"]))
    if result["authenticated"]:
        return RedirectResponse("/admin/paperless?done=test", status_code=303)
    if result["blocked"]:
        return RedirectResponse("/admin/paperless?error=paperless.error_blocked", status_code=303)
    if result["reachable"]:
        return RedirectResponse("/admin/paperless?done=reachable", status_code=303)
    return RedirectResponse("/admin/paperless?error=paperless.error_unreachable", status_code=303)

# --- OpenWearables (admin) ----------------------------------------------

OPENWEARABLES_ADMIN_ERRORS = frozenset(
    {
        "openwearables.error_url",
        "openwearables.error_unauthorized",
        "openwearables.error_unreachable",
    }
)
OPENWEARABLES_ADMIN_DONE = ("saved", "saved_relink")

@router.get("/admin/openwearables", response_class=HTMLResponse, responses=_RESPONSES_401_403)
def admin_openwearables(
    request: Request, error: str | None = None, done: str | None = None, users: int = 0,
    hook_error: str = "", hook_done: str = "",
):
    settings = request.app.state.settings
    require_admin(request)
    config = openwearables.ow_settings(settings)
    with connect(settings) as db:
        linked = db.execute(
            "SELECT COUNT(*) FROM provider_connections WHERE provider=?",
            (openwearables.PROVIDER,),
        ).fetchone()[0]
    return templates.TemplateResponse(
        request,
        "admin_openwearables.html",
        template_context(
            request,
            active="admin_openwearables",
            openwearables=config,
            openwearables_on=openwearables.configured(settings),
            # The key is never echoed back into the form; the tail is only
            # enough to tell one stored secret from another.
            ow_key_tail=config["api_key"][-6:] if config["api_key"] else "",
            linked=linked,
            ow_hooks=ow_hooks.operational_status(settings),
            error=_openwearables_admin_error(error, hook_error),
            done=_openwearables_admin_done(done, hook_done, users),
        ),
    )

def _openwearables_admin_error(error: str | None, hook_error: str) -> str | None:
    if hook_error:
        return t("ow_hooks.error")
    return t(error) if error in OPENWEARABLES_ADMIN_ERRORS else None

def _openwearables_admin_done(done: str | None, hook_done: str, users: int) -> str | None:
    if hook_done:
        return t("ow_hooks.done")
    if done == "test_ok":
        return t_plural("openwearables.done_test_ok", max(0, users))
    if done in OPENWEARABLES_ADMIN_DONE:
        return t(f"openwearables.done_{done}")
    return None

@router.post("/admin/openwearables", responses=_RESPONSES_401_403)
def admin_openwearables_save(
    request: Request,
    enabled: Annotated[str, Form()] = "",
    url: Annotated[str, Form()] = "",
    api_key: Annotated[str, Form()] = "",
    clear_key: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    admin = require_admin(request)
    require_csrf(admin, csrf_token)
    url = url.strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        return RedirectResponse(
            "/admin/openwearables?error=openwearables.error_url", status_code=303
        )
    previous = openwearables.ow_settings(settings)["url"]
    values = {
        "openwearables_enabled": "1" if enabled == "1" else "0",
        "openwearables_url": url,
    }
    # Blank means "keep the stored key" — the form never echoes the secret,
    # so blank is what an untouched form submits.
    if clear_key == "1":
        values["openwearables_api_key"] = ""
    elif api_key.strip():
        values["openwearables_api_key"] = api_key.strip()
    # Naming a different server unlinks every account: a remote user id is
    # meaningless over there, and resolving it against whoever happens to
    # hold that uuid would attach a stranger's measurements to this record.
    openwearables.save_settings(settings, values)
    _audit(settings,
        admin["id"], admin["id"], "admin_openwearables_changed", "app_settings",
        "openwearables",
        # The key itself must never reach the audit log.
        {
            "enabled": enabled == "1",
            "url": url,
            "key_changed": "openwearables_api_key" in values,
        },
    )
    done = "saved_relink" if previous and url != previous else "saved"
    return RedirectResponse(f"/admin/openwearables?done={done}", status_code=303)

@router.post("/admin/openwearables/test", responses=_RESPONSES_401_403)
def admin_openwearables_test(request: Request, csrf_token: Annotated[str, Form()] = ""):
    """One real authenticated round trip, so "configured" and "working"
    stay different claims.  It runs while the feature is still switched
    off, which is the order an operator actually sets this up in."""
    settings = request.app.state.settings
    admin = require_admin(request)
    require_csrf(admin, csrf_token)
    config = openwearables.ow_settings(settings)
    if not config["url"] or not config["api_key"]:
        return RedirectResponse(
            "/admin/openwearables?error=openwearables.error_url", status_code=303
        )
    result = openwearables.probe(settings)
    if result["ok"]:
        return RedirectResponse(
            f"/admin/openwearables?done=test_ok&users={int(result['user_count'] or 0)}",
            status_code=303,
        )
    if result["status"] == "unauthorized":
        return RedirectResponse(
            "/admin/openwearables?error=openwearables.error_unauthorized", status_code=303
        )
    return RedirectResponse(
        "/admin/openwearables?error=openwearables.error_unreachable", status_code=303
    )

@router.post("/profile/password", responses=_RESPONSES_401_403)
def change_password(
    request: Request,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """Let a person replace a password somebody else chose for them.

    An administrator creating an account has to pick its first password,
    which means the administrator knows it.  Without this the person could
    never take their own record back, and the initial password would stay
    valid for as long as the account did.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    # The current password is re-checked even though the session is valid:
    # otherwise an unattended logged-in browser is enough to take the
    # account over permanently.
    if authenticate(settings, user["email"], current_password) is None:
        return RedirectResponse("/profile?error=profile.error_password_current", status_code=303)
    if new_password != confirm_password:
        return RedirectResponse("/profile?error=profile.error_password_match", status_code=303)
    if len(new_password) < MINIMUM_PASSWORD_LENGTH:
        return RedirectResponse("/profile?error=profile.error_password_short", status_code=303)
    set_password(
        settings,
        user["id"],
        new_password,
        keep_token=request.cookies.get("anamna_session"),
    )
    _audit(settings, user["id"], user["id"], "password_changed", "user", user["id"], {})
    return RedirectResponse("/profile?saved=password", status_code=303)

@router.post("/profile/sessions/revoke", responses=_RESPONSES_401_403)
def revoke_one_session(
    request: Request,
    session: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """Sign one other browser out.  Never the one asking (see
    ``revoke_session_by_handle``): a stale page cannot end the tab in use."""
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    if not revoke_session_by_handle(settings, user["id"], session.strip(), request.cookies.get("anamna_session")):
        return RedirectResponse("/profile?error=profile.error_session#sessions", status_code=303)
    _audit(settings, user["id"], user["id"], "session_revoked", "session", session.strip()[:24], {})
    return RedirectResponse("/profile?saved=session#sessions", status_code=303)

@router.post("/profile/sessions/revoke-others", responses=_RESPONSES_401_403)
def revoke_others(request: Request, csrf_token: Annotated[str, Form()] = ""):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    ended = revoke_other_sessions(settings, user["id"], request.cookies.get("anamna_session"))
    _audit(settings, user["id"], user["id"], "sessions_revoked", "user", user["id"], {"count": ended})
    return RedirectResponse("/profile?saved=sessions#sessions", status_code=303)

@router.post("/profile/paperless", responses=_RESPONSES_401_403_404)
def save_paperless_account(
    request: Request,
    upload_enabled: Annotated[str, Form()] = "",
    api_token: Annotated[str, Form()] = "",
    clear_token: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    if not paperless.paperless_active(settings):
        raise HTTPException(404)
    # A blank token field means "keep the stored one" — the form never
    # echoes the secret back, so blank is what an untouched form submits.
    token = None
    if clear_token == "1":
        token = ""
    elif api_token.strip():
        token = api_token.strip()
    paperless.save_account(
        settings, user["id"], token=token, upload_enabled=upload_enabled == "1"
    )
    _audit(settings,
        user["id"], user["id"], "paperless_account_changed", "paperless_accounts", user["id"],
        # The token itself must never reach the audit log.
        {"upload_enabled": upload_enabled == "1", "token_changed": token is not None},
    )
    return RedirectResponse("/profile?saved=paperless", status_code=303)

@router.post("/profile/paperless/test", responses=_RESPONSES_401_403)
def test_paperless_account(request: Request, csrf_token: Annotated[str, Form()] = ""):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    ready = paperless.connection_for(settings, user["id"])
    if not ready:
        return RedirectResponse("/profile?error=paperless.error_no_token", status_code=303)
    try:
        paperless.test_connection(*ready)
    except paperless.PaperlessError as exc:
        # A tunnel or proxy turning us away is not a token problem, and
        # this is the button the person presses when their upload failed.
        if paperless.blocked_by_proxy(str(exc)):
            return RedirectResponse("/profile?error=paperless.error_blocked", status_code=303)
        return RedirectResponse("/profile?error=paperless.error_test", status_code=303)
    # One authenticated round trip proves the transport works, which means
    # whatever refused the earlier uploads has been dealt with — a wrong
    # token, a server that was down, a proxy rejecting our requests.  The
    # attempt cap exists to stop an automatic loop re-sending a document
    # this server genuinely will not take; it must not outlive its cause,
    # or the fix is invisible and the sync button does nothing.
    paperless.clear_attempts(settings, user["id"])
    return RedirectResponse("/profile?saved=paperless_test", status_code=303)

@router.post("/profile/paperless/sync", responses=_RESPONSES_401_403)
def sync_paperless_documents(request: Request, csrf_token: Annotated[str, Form()] = ""):
    """Send every document not yet in Paperless, in the background; the
    counts on the page say how far it got on the next reload."""
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    if not paperless.connection_for(settings, user["id"]):
        return RedirectResponse("/profile?error=paperless.error_no_token", status_code=303)
    if not paperless.upload_ready(settings, user["id"]):
        return RedirectResponse("/profile?error=paperless.error_upload_off", status_code=303)
    paperless.start_sync(settings, user["id"])
    return RedirectResponse("/profile?saved=paperless_sync", status_code=303)

# --- OpenWearables (profile) --------------------------------------------
# Two layers of consent, like Paperless: the operator names the server and
# holds its key, then each person links their own account on it.

def _openwearables_user(request: Request):
    """A signed-in person, and a configured server.  With the feature off
    these routes do not exist at all — an unusable form that answers an
    error is still a form somebody can find."""
    settings = request.app.state.settings
    user = require_user(request)
    if not openwearables.configured(settings):
        raise HTTPException(404)
    return user

@router.post("/profile/openwearables/link", responses=_RESPONSES_401_403_404)
def openwearables_link(
    request: Request,
    remote_user_id: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    user = _openwearables_user(request)
    require_csrf(user, csrf_token)
    try:
        people = openwearables.remote_users(settings)
    except openwearables.OpenWearablesError as exc:
        openwearables.logger.warning("openwearables: link failed to list accounts: %s", exc)
        return RedirectResponse(
            "/profile?error=openwearables.error_unreachable", status_code=303
        )
    # The submitted id is checked against the server's own list rather than
    # trusted: a hand-written form post must not be able to point this
    # record at an account the person was never shown.
    chosen = next(
        (person for person in people if person["id"] == remote_user_id.strip()), None
    )
    if chosen is None:
        return RedirectResponse("/profile?error=openwearables.error_user", status_code=303)
    replaced = openwearables.link_account(
        settings, user["id"], str(chosen["id"]), str(chosen["email"])
    )
    _audit(settings,
        user["id"], user["id"], "openwearables_linked", "provider_connections",
        openwearables.PROVIDER,
        {"remote_user_id": chosen["id"], "replaced_previous_account": replaced},
    )
    openwearables.start_backfill(settings, user["id"])
    saved = "openwearables_replaced" if replaced else "openwearables_linked"
    return RedirectResponse(f"/profile?saved={saved}", status_code=303)

@router.post("/profile/openwearables/unlink", responses=_RESPONSES_401_403_404)
def openwearables_unlink(request: Request, csrf_token: Annotated[str, Form()] = ""):
    settings = request.app.state.settings
    user = _openwearables_user(request)
    require_csrf(user, csrf_token)
    openwearables.unlink_account(settings, user["id"])
    _audit(settings, user["id"], user["id"], "openwearables_unlinked", "provider_connections",
           openwearables.PROVIDER, {})
    return RedirectResponse("/profile?saved=openwearables_unlinked", status_code=303)

@router.post("/profile/openwearables/sync", responses=_RESPONSES_401_403_404)
def openwearables_sync(request: Request, csrf_token: Annotated[str, Form()] = ""):
    settings = request.app.state.settings
    user = _openwearables_user(request)
    require_csrf(user, csrf_token)
    if openwearables.linked(settings, user["id"]) is None:
        raise HTTPException(404)
    openwearables.start_recent_sync(settings, user["id"])
    return RedirectResponse("/profile?saved=openwearables_sync", status_code=303)

# --- provider integrations (Garmin, Oura) -------------------------------
# URL contract, registration values and provider references:
# docs/provider-integrations.md. The browser-facing routes act on the
# signed-in account, never the record being viewed — linking a wearable is
# a credential operation, like changing a password.

def _integration_provider(settings, key: str, *, must_be_configured: bool = True) -> integrations.Provider:
    spec = integrations.PROVIDERS.get(key)
    if spec is None or (must_be_configured and not integrations.configured(settings, spec)):
        raise HTTPException(404)
    return spec

@router.get("/integrations/{provider}/connect", responses=_RESPONSES_401_404)
def integration_connect(request: Request, provider: str):
    # A GET navigation, not a form POST: the 303 lands on the provider's
    # authorize page, which then hops across its own SSO hosts — a chain
    # Chrome checks against form-action for form submissions but not for
    # navigations (see SECURITY_HEADERS). CSRF protection is not lost:
    # this mints only a state nonce bound to the signed-in account, and
    # nothing is granted until the person consents at the provider and the
    # callback validates that same state against the same account.
    settings = request.app.state.settings
    user = require_user(request)
    spec = _integration_provider(settings, provider)
    authorize_url = integrations.begin_oauth(
        settings,
        user["id"],
        spec,
        integrations.redirect_uri(settings, spec, str(request.base_url)),
    )
    return RedirectResponse(authorize_url, status_code=303)

@router.get("/integrations/{provider}/callback", responses=_RESPONSES_401_404)
def integration_callback(
    request: Request, provider: str, code: str = "", state: str = "", error: str = ""
):
    settings = request.app.state.settings
    user = require_user(request)
    spec = _integration_provider(settings, provider)
    if error:
        # The person pressed "deny" at the provider; nothing was granted.
        return RedirectResponse("/profile?error=integrations.error_denied", status_code=303)
    try:
        integrations.complete_oauth(
            settings,
            user["id"],
            spec,
            code=code,
            state=state,
            redirect=integrations.redirect_uri(settings, spec, str(request.base_url)),
        )
    except integrations.StaleStateError:
        return RedirectResponse("/profile?error=integrations.error_state", status_code=303)
    except integrations.IntegrationError as exc:
        integrations.logger.warning("%s: token exchange failed: %s", provider, exc)
        return RedirectResponse("/profile?error=integrations.error_exchange", status_code=303)
    _audit(settings, user["id"], user["id"], "integration_connected", "provider_connections", spec.key, {})
    if spec.key == "oura":
        # Identify the account, subscribe to webhooks, pull all history —
        # in the background; the profile shows progress on reload.
        oura.start_connect_tasks(settings, user["id"])
    elif spec.key == "garmin":
        # Permissions, anything Garmin pushed meanwhile, then the month of
        # history Garmin replays through the webhook.
        garmin.start_connect_tasks(settings, user["id"])
    return RedirectResponse("/profile?saved=integration_connected", status_code=303)

@router.post("/integrations/{provider}/disconnect", responses=_RESPONSES_401_403_404)
def integration_disconnect(request: Request, provider: str, csrf_token: Annotated[str, Form()] = ""):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    # Not gated on configured(): removing a connection must keep working
    # after the operator clears the client credentials.
    spec = _integration_provider(settings, provider, must_be_configured=False)
    integrations.disconnect(settings, user["id"], spec)
    if spec.key == "garmin":
        # What Garmin delivered goes with the consent that delivered it
        # (Garmin's terms); a Garmin *file export* the person imported is
        # theirs and stays.
        garmin.purge(settings, user["id"])
    _audit(settings, user["id"], user["id"], "integration_disconnected", "provider_connections", spec.key, {})
    return RedirectResponse("/profile?saved=integration_disconnected", status_code=303)

@router.post("/integrations/oura/sync", responses=_RESPONSES_401_403_404)
def integration_oura_sync(request: Request, csrf_token: Annotated[str, Form()] = ""):
    """The recent window, every dataset, in the background — the button a
    person presses when the ring synced but the page has not caught up."""
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    _integration_provider(settings, "oura")
    if integrations.connection_row(settings, user["id"], "oura") is None:
        raise HTTPException(404)
    oura.start_recent_sync(settings, user["id"])
    return RedirectResponse(_INTEGRATION_SYNC_SAVED_URL, status_code=303)

@router.post("/integrations/garmin/sync", responses=_RESPONSES_401_403_404)
def integration_garmin_sync(request: Request, csrf_token: Annotated[str, Form()] = ""):
    """Process anything Garmin delivered and resume a paused history
    request. Garmin forbids ad-hoc pulls, so this cannot fetch on demand."""
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    _integration_provider(settings, "garmin")
    if integrations.connection_row(settings, user["id"], "garmin") is None:
        raise HTTPException(404)
    garmin.start_connect_tasks(settings, user["id"])
    return RedirectResponse(_INTEGRATION_SYNC_SAVED_URL, status_code=303)

# Garmin Personal API: the person's own key, pasted on /profile. Not OAuth
# (no provider redirect at all), so these are ordinary same-origin forms.

@router.post("/integrations/garmin/personal", responses=_RESPONSES_401_403_404)
def garmin_personal_save(
    request: Request,
    api_key: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    if not garmin_personal.enabled(settings):
        raise HTTPException(404)
    key = api_key.strip()
    if not garmin_personal.looks_like_key(key):
        return RedirectResponse("/profile?error=integrations.error_garmin_key", status_code=303)
    try:
        garmin_personal.link_key(settings, user["id"], key)
    except garmin_personal.InvalidKeyError:
        return RedirectResponse("/profile?error=integrations.error_garmin_key_refused", status_code=303)
    except integrations.IntegrationError as exc:
        garmin_personal.logger.warning("garmin personal: key check failed: %s", exc)
        return RedirectResponse("/profile?error=integrations.error_garmin_unreachable", status_code=303)
    _audit(settings, user["id"], user["id"], "integration_connected", "provider_connections", garmin_personal.PROVIDER_KEY, {})
    garmin_personal.start_sync(settings, user["id"])
    return RedirectResponse("/profile?saved=garmin_key_saved", status_code=303)

@router.post("/integrations/garmin/personal/sync", responses=_RESPONSES_401_403_404)
def garmin_personal_sync(request: Request, csrf_token: Annotated[str, Form()] = ""):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    if not garmin_personal.enabled(settings) or integrations.connection_row(settings, user["id"], garmin_personal.PROVIDER_KEY) is None:
        raise HTTPException(404)
    garmin_personal.start_sync(settings, user["id"])
    return RedirectResponse(_INTEGRATION_SYNC_SAVED_URL, status_code=303)

@router.post("/integrations/garmin/personal/remove", responses=_RESPONSES_401_403)
def garmin_personal_remove(request: Request, csrf_token: Annotated[str, Form()] = ""):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    garmin_personal.unlink(settings, user["id"])
    _audit(settings, user["id"], user["id"], "integration_disconnected", "provider_connections", garmin_personal.PROVIDER_KEY, {})
    return RedirectResponse("/profile?saved=garmin_key_removed", status_code=303)

# The webhook routes are unauthenticated by design — the caller is Garmin's
# or Oura's server, not a browser with a session. They must answer 200 in
# seconds (both providers redeliver on anything else), so they only verify,
# store the raw payload, and return; parsing into observations is a later,
# idempotent processing step over provider_events.

def _oversized(request: Request) -> bool:
    try:
        return int(request.headers.get("content-length") or 0) > integrations.MAX_EVENT_BYTES
    except ValueError:
        return True

@router.get("/integrations/oura/webhook", responses=_RESPONSES_429)
def oura_webhook_verify(request: Request, verification_token: str = "", challenge: str = ""):
    """Oura's one-time subscription handshake: echo the challenge back."""
    settings = request.app.state.settings
    client = request.client.host if request.client else ""
    if throttled(client):
        raise HTTPException(429)
    expected = integrations.oura_verification_token(settings)
    if not expected or not csrf_matches(expected, verification_token):
        record_attempt(client)
        # Returned, not raised: the 401 handler redirects browsers to
        # /login, and Oura's verifier needs the status code, not a form.
        return JSONResponse({"detail": "invalid verification token"}, status_code=401)
    return {"challenge": challenge}

@router.post("/integrations/oura/webhook", responses=_RESPONSES_413_429)
async def oura_webhook(request: Request):
    settings = request.app.state.settings
    client = request.client.host if request.client else ""
    if throttled(client):
        raise HTTPException(429)
    if _oversized(request):
        raise HTTPException(413)
    body = await request.body()
    _, client_secret = integrations.client_config(settings, integrations.PROVIDERS["oura"])
    if not integrations.verify_oura_signature(
        client_secret,
        request.headers.get("x-oura-timestamp", ""),
        body,
        request.headers.get("x-oura-signature", ""),
    ):
        record_attempt(client)
        # Returned, not raised — see oura_webhook_verify.
        return JSONResponse({"detail": "invalid signature"}, status_code=401)
    await run_in_threadpool(integrations.record_event, settings, "oura", body)
    # Answer 200 first-class fast; turning the event into rows happens on
    # a background thread over provider_events.
    oura.start_processing(settings)
    return {"status": "ok"}

@router.post("/integrations/garmin/webhook", responses=_RESPONSES_400_404_413_429)
async def garmin_webhook(request: Request):
    # Garmin does not sign its deliveries. Every one carries a
    # `garmin-client-id` header naming our app, so the gate is that header
    # (constant-time) + shape + size + the attempt throttle; the payload's
    # user ids are matched to stored connections at processing time, never
    # trusted here.
    settings = request.app.state.settings
    client = request.client.host if request.client else ""
    if throttled(client):
        raise HTTPException(429)
    client_id, _ = integrations.client_config(settings, integrations.PROVIDERS["garmin"])
    if not client_id:
        raise HTTPException(404)
    if not csrf_matches(client_id, request.headers.get("garmin-client-id", "")):
        record_attempt(client)
        # Returned, not raised — see oura_webhook_verify.
        return JSONResponse({"detail": "unknown client"}, status_code=401)
    if _oversized(request):
        raise HTTPException(413)
    body = await request.body()
    if not integrations.acceptable_event(body):
        record_attempt(client)
        raise HTTPException(400)
    await run_in_threadpool(integrations.record_event, settings, "garmin", body)
    # Answer 200 inside Garmin's 30 s; mapping happens on a thread.
    garmin.start_processing(settings)
    return {"status": "ok"}

def _profile_text(form, name: str) -> str:
    return str(form.get(name) or "").strip()

def _profile_dob(raw: str) -> tuple[str | None, bool]:
    """The ISO date of birth (``None`` when blank) and whether it is plausible."""
    if not raw:
        return None, True
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        return None, False
    if parsed > date.today() or parsed.year < 1900:
        return None, False
    return parsed.isoformat(), True

def _profile_blood_sex(form) -> tuple[str | None, str | None, str | None]:
    """Blood type and sex at birth, plus the error key when one is not allowed."""
    blood = _profile_text(form, "blood_type") or None
    if blood is not None and blood not in BLOOD_TYPES:
        return None, None, "profile.error_blood"
    sex = _profile_text(form, "sex_at_birth") or None
    if sex is not None and sex not in SEX_AT_BIRTH:
        return None, None, _PROFILE_ERROR_CHOICE
    return blood, sex, None

def _profile_measurements(form) -> dict[str, float | None] | None:
    """The typed body measurements, or ``None`` when one is out of range."""
    measurements: dict[str, float | None] = {}
    for column, _metric_key, _unit, low, high in BODY_MEASUREMENTS:
        raw = _profile_text(form, column)
        if not raw:
            measurements[column] = None
            continue
        # `parse_decimal` already folds the Ukrainian comma separator.
        value = parse_decimal(raw)
        if value is None or not (low <= value <= high):
            return None
        measurements[column] = round(value, 2)
    return measurements

def _profile_choices(form) -> dict[str, str | None] | None:
    """The enumerated profile attributes, or ``None`` when one is not allowed."""
    choices: dict[str, str | None] = {}
    for column, allowed in PROFILE_CHOICES.items():
        raw = _profile_text(form, column)
        if raw and raw not in allowed:
            return None
        choices[column] = raw or None
    return choices

def _profile_store(connection, user_id: str, name: str, nickname, dob, sex, blood,
                   measurements: dict[str, float | None], choices: dict[str, str | None],
                   timezone_name: str) -> None:
    # Measured evidence is the single source of truth, exactly as a
    # lab-determined blood group is: while a device has recorded the
    # quantity the typed copy is not stored, so the two never drift
    # and the profile can never contradict the trend beside it.
    if _lab_blood_type(connection, user_id) is not None:
        blood = None
    for column in _measured_body(connection, user_id):
        measurements[column] = None
    connection.execute(
        "UPDATE users SET display_name=?, nickname=? WHERE id=?",
        (name, nickname, user_id),
    )
    if timezone_name:
        connection.execute("UPDATE users SET timezone=? WHERE id=?", (timezone_name, user_id))
    columns = ["display_name", "date_of_birth", "sex_at_birth", "blood_type", *measurements, *choices]
    values = [name, dob, sex, blood, *measurements.values(), *choices.values()]
    patient = _patient_row(connection, user_id)
    if patient is None:
        # CLI-created accounts can predate their patient profile.
        connection.execute(
            f"""INSERT INTO patients(id, owner_user_id, created_at, {', '.join(columns)})
                        VALUES ({', '.join('?' * (len(columns) + 3))})""",
            (str(uuid.uuid4()), user_id, utc_now(), *values),
        )
    else:
        connection.execute(
            f"UPDATE patients SET {'=?, '.join(columns)}=? WHERE id=?",
            (*values, patient["id"]),
        )

@router.post(_PROFILE_URL, responses=_RESPONSES_401_403)
async def update_profile(request: Request):
    """Store the details a lab report never carries.

    Reads the form as a mapping rather than declaring a parameter per
    field: the measurable and enumerated attributes are already described
    once in ``BODY_MEASUREMENTS`` and ``PROFILE_CHOICES``, and a second
    hand-maintained copy in this signature is how the two get out of step.
    """
    settings = request.app.state.settings
    user = require_user(request)
    form = await request.form()
    require_csrf(user, str(form.get("csrf_token") or ""))

    def failed(key: str) -> RedirectResponse:
        return RedirectResponse(f"/profile?error={key}", status_code=303)

    def field(name: str) -> str:
        return _profile_text(form, name)

    name = field("full_name")
    if not name:
        return failed("profile.error_name")
    # Empty means "no nickname": the header falls back to the full name
    # rather than storing a duplicate of it that then never updates.
    nickname = field("nickname") or None
    dob, dob_ok = _profile_dob(field("date_of_birth"))
    if not dob_ok:
        return failed(_PROFILE_ERROR_DOB)
    blood, sex, error_key = _profile_blood_sex(form)
    if error_key:
        return failed(error_key)

    measurements = _profile_measurements(form)
    if measurements is None:
        return failed("profile.error_measurement")

    # The calendar device days are cut on; an unknown name is refused
    # rather than silently falling back, which would re-date nothing.
    timezone_name = field("timezone")
    if timezone_name and not valid_timezone(timezone_name):
        return failed("profile.error_timezone")

    choices = _profile_choices(form)
    if choices is None:
        return failed(_PROFILE_ERROR_CHOICE)

    with connect(settings) as connection:
        _profile_store(connection, user["id"], name, nickname, dob, sex, blood,
                       measurements, choices, timezone_name)
    # Sex, age and the cardiovascular risk category all change verdicts;
    # the memoised catalogue must not keep judging by the old profile.
    invalidate_catalog(user["id"])
    return RedirectResponse("/profile?saved=1", status_code=303)

@router.post("/profile/shares", responses=_RESPONSES_401_403)
def add_share(
    request: Request,
    email: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    grantee = email.strip().casefold()
    if "@" not in grantee or " " in grantee:
        return RedirectResponse("/profile?error=profile.error_share_email", status_code=303)
    if grantee == user["email"]:
        return RedirectResponse("/profile?error=profile.error_share_self", status_code=303)
    with connect(settings) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO record_shares(id, owner_user_id, grantee_email, created_at)
                   VALUES (?, ?, ?, ?)""",
            (str(uuid.uuid4()), user["id"], grantee, utc_now()),
        )
    return RedirectResponse(_PROFILE_URL, status_code=303)

@router.post("/profile/shares/remove", responses=_RESPONSES_401_403)
def remove_share(
    request: Request,
    share_id: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    with connect(settings) as connection:
        connection.execute(
            "DELETE FROM record_shares WHERE id=? AND owner_user_id=?",
            (share_id, user["id"]),
        )
    return RedirectResponse(_PROFILE_URL, status_code=303)

@router.post("/profile/view", responses=_RESPONSES_401_403_404)
def switch_record(
    request: Request,
    owner_user_id: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    response = RedirectResponse("/", status_code=303)
    if owner_user_id in ("self", user["id"]):
        response.delete_cookie(VIEW_COOKIE)
        return response
    with connect(settings) as connection:
        allowed = connection.execute(
            "SELECT 1 FROM record_shares WHERE owner_user_id=? AND grantee_email=?",
            (owner_user_id, user["email"]),
        ).fetchone()
    if allowed is None:
        raise HTTPException(404)
    response.set_cookie(
        VIEW_COOKIE,
        owner_user_id,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(request),
        max_age=settings.session_days * 86400,
    )
    return response

# --- overview -----------------------------------------------------------

def _counts(connection, owner_user_id: str) -> dict[str, object]:
    counts = dict(
        connection.execute(
            """SELECT
                    (SELECT COUNT(*) FROM documents WHERE owner_user_id=?) documents,
                    (SELECT COUNT(*) FROM observations WHERE owner_user_id=? AND verification_status <> 'rejected') observations,
                    (SELECT COUNT(*) FROM (
                         SELECT (SELECT rt.state FROM review_tasks rt
                                   WHERE rt.owner_user_id=d.owner_user_id AND rt.entity_type='document' AND rt.entity_id=d.id
                                   ORDER BY rt.created_at DESC, rt.rowid DESC LIMIT 1) state
                            FROM documents d WHERE d.owner_user_id=?
                     ) current_review WHERE state='open') reviews,
                    (SELECT COUNT(*) FROM observations WHERE owner_user_id=? AND verification_status='extracted') unverified,
                    (SELECT COUNT(DISTINCT document_id) FROM observations WHERE owner_user_id=? AND verification_status='extracted') unverified_documents,
                    (SELECT MAX(observed_at) FROM observations WHERE owner_user_id=? AND verification_status <> 'rejected') latest_result,
                    (SELECT MAX(day) FROM device_metric_days WHERE owner_user_id=?) latest_device""",
            (owner_user_id,) * 7,
        ).fetchone()
    )
    counts["documents_text"] = format_count(counts["documents"])
    counts["observations_text"] = format_count(counts["observations"])
    counts["unverified_text"] = format_count(counts["unverified"])
    counts["latest_result_text"] = format_date(counts["latest_result"])
    counts["latest_device_text"] = format_date(counts["latest_device"])
    return counts

_AREA_STATUS_LABEL_KEYS = {
    "attention": "dashboard.status_attention",
    "borderline": "dashboard.status_borderline",
    "stable": "dashboard.status_stable",
    "no_data": "dashboard.status_empty",
}

def _area_status(has_attention: bool, has_borderline: bool, has_evidence: bool) -> str:
    if has_attention:
        return "attention"
    if has_borderline:
        return "borderline"
    if has_evidence:
        return "stable"
    return "no_data"

def _area_entry(definition, catalog, findings, area_panels) -> dict[str, object]:
    area_id = str(definition["id"])
    area_metrics = [item for item in catalog if area_id in item["area_ids"]]
    area_metrics.sort(
        key=lambda item: (
            _attention_rank(item),
            -_date_key(item["latest_date"]),
            0 if item["primary_area_id"] == area_id else 1,
        )
    )
    area_findings = [item for item in findings if item["health_area"] == area_id]
    attention_findings = [item for item in area_findings if item["status"] == "attention"]
    # An area with an interpretation says so; an area whose only content
    # states there is no interpretation must not claim evidence.
    interpreted = [item for item in area_findings if item["status"] != "information"]
    flagged = [item for item in area_metrics if _attention_rank(item) <= 2]
    borderline = [item for item in area_metrics if _attention_rank(item) == 3]
    latest_dates = [str(item["latest_date"]) for item in area_metrics if item["latest_date"]]
    latest_dates += [str(item["finding_date"]) for item in area_findings if item["finding_date"]]
    status_value = _area_status(
        bool(flagged or attention_findings), bool(borderline), bool(area_metrics or area_findings)
    )
    return {
        **definition,
        "name": translate_phrase(str(definition["name"])),
        "short": translate_phrase(str(definition["short"])),
        "description": translate_phrase(str(definition["description"])),
        "status": status_value,
        "status_label": t(_AREA_STATUS_LABEL_KEYS[status_value]),
        "latest_date": max(latest_dates) if latest_dates else None,
        "latest_date_text": format_date(max(latest_dates) if latest_dates else None),
        "metrics": _representative(area_metrics, 2),
        "finding": area_findings[0] if area_findings else None,
        "finding_count": len(area_findings),
        "attention_finding_count": len(attention_findings),
        "has_interpretation": bool(interpreted),
        "metric_count": len(area_metrics),
        # An area whose only evidence is a report conclusion is
        # counted by the documents behind it, never shown as "0".
        "finding_document_count": len({item["document_id"] for item in area_findings}),
        "flagged_count": len(flagged),
        "evidence_count": len(area_metrics) + len(area_findings),
        "panel_ids": [str(panel["id"]) for panel in area_panels],
        "panels": area_panels,
    }

def _areas(catalog, findings, panels) -> list[dict[str, object]]:
    panels_by_area: dict[str, list[dict[str, object]]] = {}
    for panel in panels:
        panels_by_area.setdefault(str(panel["area_id"]), []).append(panel)
    return [
        _area_entry(definition, catalog, findings, panels_by_area.get(str(definition["id"]), []))
        for definition in HEALTH_AREAS
    ]

def _tiles(attention_count: int, due_count: int, panels, counts) -> list[dict[str, object]]:
    """Each tile is a shortcut to the filtered list it counts."""
    with_data = sum(1 for panel in panels if panel["present_count"])
    unverified = int(counts["unverified"])
    return [
        {
            "key": "attention",
            "label": t("tile.attention") if attention_count else t("tile.attention_zero"),
            "value": format_count(attention_count),
            "href": "/metrics?status=attention",
            "tone": "attention" if attention_count else "good",
        },
        {
            "key": "due",
            "label": t("tile.due") if due_count else t("tile.due_zero"),
            "value": format_count(due_count),
            "href": "/metrics?status=due",
            "tone": "due" if due_count else "good",
        },
        {
            "key": "panels",
            "label": t("tile.panels_covered"),
            "value": f"{format_count(with_data)}/{format_count(len(panels))}",
            "href": "/panels",
            "tone": "neutral",
        },
        {
            # The number of unchecked *results*, as the label says -- this
            # used to print the open review-task count under it.  The note
            # counts exactly what the link opens.
            "key": "unverified",
            "label": t("tile.unverified") if unverified else t("tile.unverified_zero"),
            "value": format_count(unverified),
            "note": (
                t_plural("tile.review_documents", int(counts["reviews"]))
                if counts["reviews"] else ""
            ),
            "href": "/documents?review_state=open",
            "tone": "due" if unverified else "good",
        },
    ]

def _oldest_panels(panels) -> list[dict[str, object]]:
    """Panels with no published retest cadence, longest unrepeated first.

    Most analytes have no screening interval; these are shown by age and
    never described as late.
    """
    oldest = [
        panel for panel in panels
        if panel["present_count"] and panel["staleness"]["state"] == "no_interval"
    ]
    oldest.sort(key=lambda panel: -int(panel["staleness"].get("days_ago") or 0))
    return oldest

def _due_panels(panels) -> list[dict[str, object]]:
    due = [
        panel
        for panel in panels
        if panel["present_count"] and panel["staleness"]["state"] in {"overdue", "due_soon"}
    ]
    due.sort(key=lambda panel: (_STALENESS_ORDER[panel["staleness"]["state"]], -int(panel["staleness"].get("days_ago") or 0)))
    return due

@router.get("/", response_class=HTMLResponse, responses=_RESPONSES_401)
def dashboard(request: Request):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        patient = _patient_row(connection, user["id"])
        counts = _counts(connection, user["id"])
        # Every card on this page is read at the last complete device day:
        # a morning's "0 steps" is not a result.
        catalog = _complete_days(connection, user["id"], _metric_catalog(connection, user["id"]))
        panels = _panel_cards(connection, user["id"], member_limit=6)
        findings = _finding_catalog(connection, user["id"])
        recent_documents = [
            _document_row(row)
            for row in connection.execute(
                """SELECT d.id, d.title, d.original_filename, d.report_date, d.imported_at,
                              d.clinical_type, v.canonical_name vendor, COUNT(o.id) observation_count
                       FROM documents d LEFT JOIN vendors v ON v.id=d.vendor_id
                       LEFT JOIN observations o ON o.document_id=d.id AND o.verification_status <> 'rejected'
                       WHERE d.owner_user_id=? GROUP BY d.id
                       ORDER BY d.imported_at DESC, d.rowid DESC LIMIT 4""",
                (user["id"],),
            )
        ]
        attention = _attention_cards(catalog)
        attention_findings = _attention_findings(findings)
        experience = build_overview(
            _areas(catalog, findings, panels), catalog, counts, attention=attention,
        )
    # What needs attention, first: the abnormal results and report
    # conclusions themselves, not a count of them.
    priorities = [
        {"kind": "metric", "card": {**card, "outside_by_text": _outside_by_text(card)}}
        for card in attention[:4]
    ] + [{"kind": "finding", "row": _finding_result(row)} for row in attention_findings[:2]]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        template_context(
            request,
            patient=patient,
            experience=experience,
            counts=counts,
            patient_age=age_on(patient["date_of_birth"]) if patient else None,
            patient_sex_label=(
                t(f"sex.{str(patient['sex_at_birth'] or 'unknown').casefold()}") if patient else ""
            ),
            priorities=priorities,
            attention_total=len(attention) + len(attention_findings),
            tiles=_tiles(len(attention) + len(attention_findings), len(_due_panels(panels)), panels, counts),
            recent_documents=recent_documents,
            active="dashboard",
        ),
    )

# --- AI hand-off --------------------------------------------------------

def _focus_label(connection, owner_user_id: str, path: str) -> str | None:
    """What the reader had open when they asked for the prompt.

    Purely a hint for the assistant's opening paragraph -- the whole record
    travels either way, because a single analyte read without the rest of
    the panel is how a confident wrong answer gets written.
    """
    parts = [segment for segment in str(path or "").split("/") if segment]
    if parts[:2] == ["devices", "metrics"] and len(parts) == 3:
        parts = ["metrics", _twin_concept_id(f"device:{parts[2]}")]
    if len(parts) != 2:
        return None
    section, key = parts
    if section == "metrics":
        card = _by_id(_metric_catalog(connection, owner_user_id, include_suppressed=True))
        return str(card[key]["name"]) if key in card else None
    if section == "areas":
        area = AREA_BY_ID.get(key)
        return translate_phrase(str(area["name"])) if area else None
    if section == "panels":
        panel = PANEL_BY_ID.get(key)
        return translate_phrase(panel.name) if panel else None
    return None

def _scope_device(connection, owner_user_id: str, metric_key: str) -> dict[str, object] | None:
    concept_id = _twin_concept_id(f"{_DEVICE_METRIC_PREFIX}{metric_key}")
    if not concept_id.startswith(_DEVICE_METRIC_PREFIX):
        # One measurement, one excerpt: the concept's, which carries this
        # device's summary beside the documents.
        return _scope_metric(connection, owner_user_id, concept_id)
    summaries = [
        item
        for item in device_history_summary(connection, owner_user_id)
        if str(item["metric_key"]) == metric_key
    ]
    if not summaries:
        return None
    card = _by_id(_metric_catalog(connection, owner_user_id)).get(f"device:{metric_key}")
    return {
        "kind": "device",
        "label": str(card["name"]) if card else translate_phrase(str(summaries[0]["name"])),
        "cards": [card] if card else [],
        "device_summaries": summaries,
        "detailed": True,
    }

def _scope_metric(connection, owner_user_id: str, key: str) -> dict[str, object] | None:
    by_id = _by_id(_metric_catalog(connection, owner_user_id, include_suppressed=True))
    card = by_id.get(key)
    if card is None or card.get("is_device"):
        return None
    related = []
    panel = PANEL_BY_ID.get(str(card.get("panel_id") or ""))
    if panel is not None:
        related = [
            by_id[member]
            for member in panel_members(connection, panel)
            if member != key and member in by_id
        ]
    twins = set(device_twins(key, "same"))
    return {
        "kind": "metric",
        "label": str(card["name"]),
        "cards": [card],
        "device_summaries": [
            item for item in device_history_summary(connection, owner_user_id)
            if str(item["metric_key"]) in twins
        ] if twins else [],
        "related_cards": related,
        "related_label": card.get("panel_name"),
        "detailed": True,
    }

def _scope_panel(connection, owner_user_id: str, key: str) -> dict[str, object] | None:
    panel = PANEL_BY_ID.get(key)
    if panel is None:
        return None
    by_id = _by_id(_metric_catalog(connection, owner_user_id, include_suppressed=True))
    return {
        "kind": "panel",
        "label": translate_phrase(panel.name),
        "cards": [
            by_id[member]
            for member in panel_members(connection, panel)
            if member in by_id
        ],
    }

def _scope_area(connection, owner_user_id: str, key: str) -> dict[str, object] | None:
    area = AREA_BY_ID.get(key)
    if area is None:
        return None
    return {
        "kind": "area",
        "label": translate_phrase(str(area["name"])),
        "cards": [
            card
            for card in _metric_catalog(connection, owner_user_id)
            if key in card["area_ids"]
        ],
        "findings": [
            item
            for item in _finding_catalog(connection, owner_user_id)
            if str(item["health_area"]) == key
        ],
    }

def _scope_document(connection, owner_user_id: str, key: str) -> dict[str, object] | None:
    row = connection.execute(
        """SELECT d.*, v.canonical_name vendor FROM documents d
                   LEFT JOIN vendors v ON v.id=d.vendor_id
                   WHERE d.id=? AND d.owner_user_id=?""",
        (key, owner_user_id),
    ).fetchone()
    if not row:
        return None
    document = _document_row(row)
    return {
        "kind": "document",
        "label": str(document["title_text"]),
        "document": document,
        # A row the reader set aside as parser debris is not a result.
        # The page still shows it, carrying a "Set aside" chip that
        # says so; the prompt has no such chip, so an exported
        # rejected row reads exactly like a genuine measurement.
        "observations": [
            item
            for item in _document_observations(connection, owner_user_id, key)
            if str(item.get("verification_status") or "") != "rejected"
        ],
        "findings": [
            item
            for item in _finding_catalog(connection, owner_user_id)
            if str(item["document_id"]) == key
        ],
    }

_SCOPE_SECTIONS = {
    "metrics": _scope_metric,
    "panels": _scope_panel,
    "areas": _scope_area,
    "documents": _scope_document,
}

def _scope_subject(connection, owner_user_id: str, path: str) -> dict[str, object] | None:
    """The detail page the reader had open, resolved to the data it shows.

    Feeds `build_subject_prompt`.  ``None`` means the path is a list page
    or resolves to nothing this user owns, and the whole-record prompt is
    the only honest export.
    """
    parts = [segment for segment in str(path or "").split("/") if segment]
    if parts[:2] == ["devices", "metrics"] and len(parts) == 3:
        return _scope_device(connection, owner_user_id, parts[2])
    if len(parts) != 2:
        return None
    section, key = parts
    resolve = _SCOPE_SECTIONS.get(section)
    return resolve(connection, owner_user_id, key) if resolve else None

@router.get("/api/ai-export", response_class=PlainTextResponse, responses=_RESPONSES_401_404)
def ai_export_prompt(
    request: Request, include: str | None = None, path: str = "", scope: str = "record"
):
    """The record as one pasteable prompt.  See `ai_export.py`.

    ``scope=page`` narrows it to what the page at ``path`` shows — the
    subject in full plus the context needed to read it.  A path that is not
    a detail page falls back to the whole record rather than erroring: the
    fallback is a superset of what was asked for, never less.
    """
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    sections = (
        DEFAULT_SECTIONS
        if include is None
        else {item.strip() for item in include.split(",")} & SECTION_KEYS
    )
    with connect(settings) as connection:
        patient = _patient_row(connection, user["id"])
        counts = _counts(connection, user["id"])
        counts["patient_age"] = age_on(patient["date_of_birth"]) if patient else None
        catalog = _metric_catalog(connection, user["id"])
        subject = (
            _scope_subject(connection, user["id"], path) if scope == "page" else None
        )
        if subject is not None:
            text = build_subject_prompt(
                connection,
                user["id"],
                subject=subject,
                include=sections,
                patient=patient,
                counts=counts,
                catalog=catalog,
                attention=_attention_cards(catalog),
                guidance=_guidance_index(connection),
            )
            return PlainTextResponse(text, media_type="text/plain; charset=utf-8")
        documents = [
            _document_row(row)
            for row in connection.execute(
                """SELECT d.id, d.title, d.original_filename, d.report_date, d.imported_at,
                              d.clinical_type, v.canonical_name vendor, COUNT(o.id) observation_count
                       FROM documents d LEFT JOIN vendors v ON v.id=d.vendor_id
                       LEFT JOIN observations o ON o.document_id=d.id
                            AND o.verification_status <> 'rejected'
                       WHERE d.owner_user_id=? GROUP BY d.id
                       ORDER BY d.report_date IS NULL, d.report_date DESC, d.imported_at DESC""",
                (user["id"],),
            )
        ]
        text = build_prompt(
            connection,
            user["id"],
            include=sections,
            focus=_focus_label(connection, user["id"], path),
            patient=patient,
            counts=counts,
            catalog=catalog,
            attention=_attention_cards(catalog),
            findings=_finding_catalog(connection, user["id"]),
            guidance=_guidance_index(connection),
            documents=documents,
        )
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")

# --- panels -------------------------------------------------------------

@router.get("/panels", response_class=HTMLResponse, responses=_RESPONSES_401)
def panels_page(request: Request, sort: str = ""):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        panels = _panel_cards(connection, user["id"], member_limit=6)
    # One order for both views: the attention view is this list, flat; the
    # area view stamps each card with its place in it, so the in-page
    # toggle reorders without asking the server again.
    ranked = sorted(panels, key=_panel_sort_key)
    attention_order = {panel["id"]: index for index, panel in enumerate(ranked)}
    groups = []
    for definition in HEALTH_AREAS:
        area_id = str(definition["id"])
        area_panels = sorted(
            [panel for panel in panels if panel["area_id"] == area_id], key=_panel_sort_key
        )
        if area_panels:
            groups.append(
                {
                    "area_id": area_id,
                    "area_name": translate_phrase(str(definition["name"])),
                    "panels": area_panels,
                    "flagged": sum(1 for panel in area_panels if panel["status"] == "attention"),
                    "overdue": sum(
                        1 for panel in area_panels if panel["staleness"]["state"] == "overdue"
                    ),
                }
            )
    totals = {
        "panels": len(panels),
        "with_data": sum(1 for panel in panels if panel["present_count"]),
        "flagged": sum(1 for panel in panels if panel["status"] == "attention"),
        "overdue": sum(1 for panel in panels if panel["staleness"]["state"] == "overdue"),
    }
    return templates.TemplateResponse(
        request,
        "panels.html",
        template_context(
            request, groups=groups, totals=totals, active="panels",
            sort="attention" if sort == "attention" else "area",
            ranked=ranked, attention_order=attention_order,
        ),
    )

# ------------------------------------------------------------ vaccinations

def _product_sources(product) -> list[dict[str, object]]:
    return [
        {**source, "region_label": t(f"vax.region_{source['region']}")}
        for source in (product.sources if product else ())
    ]

def _dose_trade_maker(row, stored, product) -> tuple[str, str]:
    trade = str(stored.get("trade_name") or "") or (product.trade_name if product else "")
    maker = str(row["manufacturer"] or "") or (product.manufacturer if product else "")
    return trade, maker

def _dose_alternatives(row, product) -> list:
    # "Most likely, since the card names no product" is only true when
    # the source names none: a visit note prints «Gardasil 9» itself.
    if not product or immunization_fold(product.trade_name) in immunization_fold(str(row["evidence_text"] or "")):
        return []
    return list(product.alternatives)

def _dose_product_fields(row, stored, product, trade: str, maker: str) -> dict[str, object]:
    return {
        # What the dose *is*, in the words a person searches for; the
        # printed paragraph is kept, but only as "as printed".
        "trade_name": stored.get("trade_name") or "",
        "trade": trade,
        "maker": maker,
        "maker_short": product.maker_short if product else "",
        "alternatives": _dose_alternatives(row, product),
        "product_key": product.key if product else (row["vaccine_code"] or "other"),
        "product_label": trade or (row["vaccine_code"] or "") or t("vax.unidentified_short"),
        "product_sources": _product_sources(product),
    }

def _dose_search_text(row, product, keys, disease_names, trade, maker, facility, clinician, date_value) -> str:
    # Everything the page's filter box matches, folded once here.
    return " ".join(
        part for part in (
            trade, maker, row["vaccine_code"] or "", row["product_name"] or "",
            row["lot_number"] or "", facility, clinician, date_value,
            format_date(row["occurrence_date"]), *disease_names,
            *(DISEASES[key].name for key in keys),
            *(product.alternatives if product else ()),
        ) if part
    ).casefold()

def _dose_record_fields(row) -> dict[str, object]:
    given, total = row["dose_number"], row["doses_in_series"]
    return {
        "product_name": row["product_name"] or "",
        "manufacturer": row["manufacturer"] or "",
        "kind_label": t(f"vax.kind_{row['event_kind']}"),
        "event_kind": row["event_kind"],
        "dose_number": given,
        "doses_in_series": total,
        "dose_text": t("vax.dose_of", given=given, total=total) if given and total else "",
        "lot_number": row["lot_number"] or "",
        "route_label": t("vax.route_intramuscular") if row["route"] == "intramuscular" else "",
        "note": row["note"] or "",
        "manual": row["entry_source"] == "manual",
        "status": row["verification_status"],
        "status_label": t(f"vax.status_{row['verification_status']}"),
        "document_id": row["document_id"],
        "document_title": display_document_title(
            row["document_title"], "immunization_record"
        ) if row["document_id"] else "",
        "evidence_text": row["evidence_text"] or "",
    }

def _dose_row(row) -> dict[str, object]:
    """One dose, as the page shows it."""
    keys = [key for key in str(row["diseases"] or "").split(",") if key in DISEASES]
    stored = dict(row)
    product = product_for(stored)
    trade, maker = _dose_trade_maker(row, stored, product)
    disease_names = [translate_phrase(DISEASES[key].name) for key in keys]
    date_value = str(row["occurrence_date"] or "")
    quantity = row["dose_quantity"]
    facility = str(stored.get("facility") or "")
    clinician = str(stored.get("clinician") or "")
    return {
        "id": row["id"],
        "date": row["occurrence_date"],
        "date_text": format_date(row["occurrence_date"]),
        "year": date_value[:4],
        **_dose_product_fields(row, stored, product, trade, maker),
        "facility": facility,
        "clinician": clinician,
        "site": str(row["site"] or ""),
        "quantity_text": (
            t("vax.quantity_ml", value=format_number_localized(quantity))
            if quantity is not None else ""
        ),
        "code_meaning": " · ".join(disease_names),
        "search_text": _dose_search_text(
            row, product, keys, disease_names, trade, maker, facility, clinician, date_value
        ),
        "vaccine_code": row["vaccine_code"] or "",
        # The picker entry, not the bare code: a correction form seeded with
        # "DTaP" shows the person a token, and one seeded with the entry
        # shows them what it means and still resolves back to the same code.
        "vaccine_entry": _vaccine_entry_for(str(row["vaccine_code"] or "")),
        "page_number": row["page_number"],
        "diseases": [translate_phrase(DISEASES[key].name) for key in keys],
        "disease_keys": keys,
        **_dose_record_fields(row),
    }

def _gap_row(gap, rows: list[dict[str, object]]) -> dict[str, object]:
    """One outstanding item, with the sentence and the citations it needs."""
    library = schedule_sources()
    if gap.kind == "series":
        sentence = t(
            "vax.gap_series",
            given=gap.dose_number, total=gap.doses_in_series,
            date=format_date(gap.last_date),
        )
    elif gap.last_date and gap.due_date:
        key = "vax.gap_overdue" if gap.urgency == "overdue" else "vax.gap_due"
        sentence = t(key, date=format_date(gap.last_date), due=format_date(gap.due_date))
    elif gap.due_date:
        sentence = t("vax.gap_never_dated", due=format_date(gap.due_date))
    else:
        sentence = t("vax.gap_never")
    note_key = f"vax.note_{gap.key}"
    # A gap that names a vaccine already on file can offer to add the next
    # dose of it, pre-filled from the last one. A gap for something never
    # recorded cannot: nothing here knows which product a doctor will use,
    # and guessing one into a medical record is worse than an empty field.
    covering = sorted(
        (row for row in rows if set(gap.diseases) & set(row["disease_keys"])),
        key=lambda row: str(row["date"] or ""),
        reverse=True,
    )
    return {
        "key": gap.key,
        "prefill": _next_dose_prefill(covering) if covering else None,
        "kind": gap.kind,
        "diseases": [
            translate_phrase(DISEASES[key].name) for key in gap.diseases if key in DISEASES
        ],
        "sentence": sentence,
        "urgency": gap.urgency,
        "urgency_label": t(f"vax.urgency_{gap.urgency}"),
        "agreement": gap.agreement,
        "agreement_label": t(f"vax.agreement_{gap.agreement}"),
        "agreement_help": t(f"vax.agreement_{gap.agreement}_help"),
        "note": t(note_key) if note_key in MESSAGES else "",
        "regions": [t(f"vax.region_{region}") for region in gap.regions_covered],
        "sources": [
            {
                "publisher": library[key]["publisher"],
                "name": library[key]["name"],
                "url": library[key]["url"],
                "region": t(f"vax.region_{library[key]['region']}"),
            }
            for key in gap.source_ids
            if key in library
        ],
    }

#: Separates the code from the diseases in a picker entry.  Spaced, so it
#: cannot occur inside either half.
VACCINE_LABEL_SEPARATOR = " - "

def _vaccine_options() -> list[str]:
    """The vaccine picker's entries: `CODE - Disease · Disease`.

    A `<datalist>` rather than a `<select>`, and the diseases are in the
    entry rather than beside it, because a datalist filters on what the
    person types against the whole string.  Seventy entries in a select is a
    scroll; here, typing "tetanus" narrows it to the seventeen products that
    cover tetanus without anyone needing to know what "TdaPIPV" stands for.
    Built per request: the disease names are localized, and so is the sort.
    """
    options = [
        code + VACCINE_LABEL_SEPARATOR + " · ".join(
            translate_phrase(DISEASES[key].name) for key in keys if key in DISEASES
        )
        for code, keys in VACCINE_CODES.items()
    ]
    return sorted(options, key=str.casefold)

def _vaccine_code_from(entry: str) -> str | None:
    """The code a picker entry names, or None when it names nothing known.

    A datalist is a suggestion, not a constraint: whatever the person typed
    arrives verbatim, which may be a full entry, a bare code, or a product
    name they wrote themselves.  The last is not an error — it is the
    "not in this list" case, and the handler asks for a product name instead.
    """
    typed = entry.strip()
    if not typed:
        return None
    # An entry saved by the browser before the separator changed still parses.
    head = typed.replace(" — ", VACCINE_LABEL_SEPARATOR).split(VACCINE_LABEL_SEPARATOR, 1)[0].strip()
    for candidate in (head, typed):
        if candidate in VACCINE_CODES:
            return candidate
        folded = {code.casefold(): code for code in VACCINE_CODES}
        if candidate.casefold() in folded:
            return folded[candidate.casefold()]
    return None

def _vaccine_entry_for(code: str) -> str:
    """The picker entry that names `code`, for pre-filling the form."""
    if code not in VACCINE_CODES:
        return ""
    return code + VACCINE_LABEL_SEPARATOR + " · ".join(
        translate_phrase(DISEASES[key].name)
        for key in VACCINE_CODES[code]
        if key in DISEASES
    )

def _next_dose_prefill(doses: list[dict[str, object]]) -> dict[str, object]:
    """What the next dose of this vaccine most likely is, from the last one.

    The card states the length of the course itself, so a dose recorded as
    "2 of 3" says plainly that the next one is the third of three — and that
    it is a `Ревакцинація`, because on form 063/о only the first dose of a
    course is a `Вакцинація`.  A course the card shows as finished says the
    opposite: the next dose is a new booster, and its numbering belongs to
    whatever course that booster starts, which this cannot know and does not
    guess.
    """
    latest = doses[0]
    given, total = latest.get("dose_number"), latest.get("doses_in_series")
    prefill = {
        "vaccine_entry": _vaccine_entry_for(str(latest.get("vaccine_code") or "")),
        "product_name": latest.get("product_name") or "",
        "manufacturer": latest.get("manufacturer") or "",
        "trade_name": latest.get("trade") or "",
        "facility": latest.get("facility") or "",
        "dose_number": "",
        "doses_in_series": "",
        "event_kind": "revaccination",
    }
    if given and total and int(given) < int(total):
        prefill["dose_number"] = int(given) + 1
        prefill["doses_in_series"] = int(total)
        prefill["event_kind"] = "vaccination" if int(given) + 1 == 1 else "revaccination"
    return prefill

def _group_products(members: list[dict[str, object]]) -> list[dict[str, object]]:
    """The products in one disease section, newest first, each once."""
    seen: dict[str, dict[str, object]] = {}
    for row in members:
        key = str(row["product_key"])
        if key not in seen:
            seen[key] = {
                "label": row["product_label"],
                "maker": row["maker"],
                "maker_short": row["maker_short"] or row["maker"],
                "code": row["vaccine_code"],
                "code_meaning": row["code_meaning"],
                "alternatives": row["alternatives"],
                "sources": row["product_sources"],
                "count": 0,
            }
        seen[key]["count"] += 1
    return list(seen.values())

@router.get(_VACCINATIONS_URL, responses=_RESPONSES_401)
def vaccinations_page(request: Request, saved: str = "", error: str = "", q: str = ""):
    """Every dose on file, what the schedules say next, and a way to add one."""
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        doses = doses_for(connection, user["id"])
        notes = visit_notes(connection, user["id"], doses)
    rows = [_dose_row(row) for row in doses]
    for row in rows:
        row["visit_notes"] = [
            {**note, "date_text": format_date_localized(note["report_date"]) if note["report_date"] else ""}
            for note in notes.get(str(row["id"]), [])
        ]
    today = date.fromisoformat(utc_now()[:10])
    gaps = [_gap_row(gap, rows) for gap in find_gaps(doses, today)]

    groups = []
    for key, disease in DISEASES.items():
        members = sorted(
            (row for row in rows if key in row["disease_keys"]),
            key=lambda row: str(row["date"] or ""),
            reverse=True,
        )
        if not members:
            continue
        latest = members[0]
        groups.append(
            {
                "key": key,
                "name": translate_phrase(disease.name),
                "explanation": translate_phrase(disease.explanation),
                "doses": members,
                # The summary line, so a closed section still answers the
                # question the page is opened with: what have I had, and
                # when was the last one.
                "count": len(members),
                "products": _group_products(members),
                "latest_text": latest["date_text"],
                "latest_dose_text": latest["dose_text"],
                "unchecked": sum(1 for row in members if row["status"] == "extracted"),
                "prefill": _next_dose_prefill(members),
            }
        )
    groups.sort(key=lambda group: str(group["doses"][0]["date"] or ""), reverse=True)
    missing = [
        {
            "key": key,
            "name": translate_phrase(DISEASES[key].name),
            "explanation": translate_phrase(DISEASES[key].explanation),
        }
        for key in calendar_diseases_without_a_dose(doses)
    ]
    return templates.TemplateResponse(
        request,
        "vaccinations.html",
        template_context(
            request,
            groups=groups,
            gaps=gaps,
            missing=missing,
            unidentified=[row for row in rows if not row["disease_keys"]],
            totals={
                "doses": len(rows),
                "protected": len(groups),
                "outstanding": len(gaps),
                "unchecked": sum(1 for row in rows if row["status"] == "extracted"),
            },
            vaccine_options=_vaccine_options(),
            # The filter's choices come from what is on file, never from
            # the whole dictionary: an option that matches nothing is a
            # dead end.
            filters={
                "q": q.strip()[:120],
                "years": sorted({str(row["year"]) for row in rows if row["year"]}, reverse=True),
                "products": sorted(
                    {(str(row["product_key"]), str(row["product_label"])) for row in rows},
                    key=lambda item: item[1].casefold(),
                ),
                "diseases": [(group["key"], group["name"]) for group in sorted(
                    groups, key=lambda group: str(group["name"]).casefold()
                )],
            },
            today=utc_now()[:10],
            saved=t(f"vax.{saved}_notice") if f"vax.{saved}_notice" in MESSAGES else "",
            error=t(f"vax.error_{error}") if f"vax.error_{error}" in MESSAGES else "",
            active="vaccinations",
        ),
    )

def _dose_form_values(
    occurred_on: str, vaccine_code: str, product_name: str,
    dose_number: str, doses_in_series: str,
) -> tuple[dict[str, object], str]:
    """Validate what the form sent; return the stored shape, or an error key."""
    try:
        occurrence = date.fromisoformat(occurred_on.strip())
    except ValueError:
        return {}, "date"
    if occurrence > date.fromisoformat(utc_now()[:10]):
        return {}, "date"
    typed = vaccine_code.strip()
    code = _vaccine_code_from(typed) or ""
    product = product_name.strip()[:400]
    if typed and not code and not product:
        # A datalist suggests, it does not constrain, so somebody who could
        # not find their vaccine simply typed its name into the box. That is
        # an answer, not an error: keep it as the product name, which is the
        # field it belongs in.
        product = typed[:400]
    if not code and not product:
        # Without one or the other there is no way to say what was given,
        # and a dated row naming no vaccine helps nobody.
        return {}, "vaccine"
    given = int(dose_number) if dose_number.strip().isdigit() else None
    total = int(doses_in_series) if doses_in_series.strip().isdigit() else None
    if given and total and given > total:
        return {}, "series"
    return (
        {
            "occurrence_date": occurrence.isoformat(),
            "vaccine_code": code,
            "diseases": ",".join(diseases_for(code)),
            "product_name": product,
            "dose_number": given,
            "doses_in_series": total,
        },
        "",
    )

@dataclass(frozen=True)
class _DoseFields:
    """The dose itself, as both the add and the edit form post it."""

    occurred_on: str
    vaccine_code: str
    event_kind: str
    product_name: str
    manufacturer: str
    trade_name: str
    facility: str
    clinician: str
    dose_number: str
    doses_in_series: str
    lot_number: str
    note: str


def _dose_fields(
    occurred_on: Annotated[str, Form()] = "",
    vaccine_code: Annotated[str, Form()] = "",
    event_kind: Annotated[str, Form()] = "vaccination",
    product_name: Annotated[str, Form()] = "",
    manufacturer: Annotated[str, Form()] = "",
    trade_name: Annotated[str, Form()] = "",
    facility: Annotated[str, Form()] = "",
    clinician: Annotated[str, Form()] = "",
    dose_number: Annotated[str, Form()] = "",
    doses_in_series: Annotated[str, Form()] = "",
    lot_number: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
) -> _DoseFields:
    """A dependency, so FastAPI reads these as the same form fields it always did."""
    return _DoseFields(
        occurred_on, vaccine_code, event_kind, product_name, manufacturer, trade_name,
        facility, clinician, dose_number, doses_in_series, lot_number, note,
    )

def _dose_details(dose: _DoseFields) -> tuple[str, str, str, str, str]:
    """Manufacturer, trade name, facility, clinician and event kind, as both
    the add and the edit route store them."""
    return (
        dose.manufacturer.strip()[:200], dose.trade_name.strip()[:120],
        dose.facility.strip()[:200], dose.clinician.strip()[:200],
        dose.event_kind if dose.event_kind in {"vaccination", "revaccination"} else "vaccination",
    )


def _dose_source(connection, user_id: str, document_id: str):
    """The linked card (None when unlinked) and the patient the dose is for."""
    source_document = None
    if document_id:
        source_document = connection.execute(
            "SELECT id, patient_id, page_count FROM documents WHERE id=? AND owner_user_id=?",
            (document_id, user_id),
        ).fetchone()
        if source_document is None:
            raise HTTPException(404)
    if source_document:
        patient = connection.execute(
            "SELECT * FROM patients WHERE id=?", (source_document["patient_id"],)
        ).fetchone()
    else:
        patient = _patient_row(connection, user_id)
    if patient is None:
        raise HTTPException(400, t(_UPLOAD_ERROR_NO_SOURCE))
    return source_document, patient


def _dose_placement(source_document, page_number: int) -> tuple[object, object, str]:
    """Document id, page and entry source for the new row."""
    if not source_document:
        return None, None, "manual"
    return (
        source_document["id"],
        max(1, min(int(page_number), int(source_document["page_count"] or 1))),
        "document",
    )


@router.post(_VACCINATIONS_URL, responses=_RESPONSES_400_401_403_404)
def add_vaccination(
    request: Request,
    dose: Annotated[_DoseFields, Depends(_dose_fields)],
    document_id: Annotated[str, Form()] = "",
    page_number: Annotated[int, Form()] = 1,
    evidence_text: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = _VACCINATIONS_URL,
    csrf_token: Annotated[str, Form()] = "",
):
    """Add a human-reviewed dose, optionally linked to its source document.

    The commonest one by far is a childhood dose from a paper booklet: the
    Ukrainian electronic register starts in 2019, so for anybody born before
    then the card they can scan is missing the first twenty years of their
    own vaccination history.  Unlinked doses remain `manual`; a suggestion
    accepted beside a card keeps the document, page and source evidence and
    is marked human-corrected so a re-read cannot silently overwrite it.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    destination = _safe_next(next, _VACCINATIONS_URL)
    joiner = "&" if "?" in destination else "?"
    values, problem = _dose_form_values(
        dose.occurred_on, dose.vaccine_code, dose.product_name, dose.dose_number, dose.doses_in_series
    )
    if problem:
        return RedirectResponse(f"{destination}{joiner}error={problem}", status_code=303)
    with connect(settings) as connection:
        source_document, patient = _dose_source(connection, user["id"], document_id)
        lot = dose.lot_number.strip()[:80]
        if lot and connection.execute(
            """SELECT 1 FROM immunizations
                   WHERE owner_user_id=? AND occurrence_date=? AND lot_number=?""",
            (user["id"], values["occurrence_date"], lot),
        ).fetchone():
            # The same identity `store_document_doses` dedupes on.  Without
            # this the unique index answers with a 500 page.
            return RedirectResponse(f"{destination}{joiner}error=duplicate", status_code=303)
        now = utc_now()
        source_id, source_page, source_kind = _dose_placement(source_document, page_number)
        evidence = collapse_space(evidence_text)[:500]
        connection.execute(
            """INSERT INTO immunizations(
                       id, owner_user_id, patient_id, document_id, page_number,
                       occurrence_date, vaccine_code, diseases,
                       product_name, manufacturer, trade_name, facility, clinician,
                       event_kind, dose_number, doses_in_series,
                       lot_number, note, entry_source, entered_by_user_id, verification_status,
                       evidence_text, confidence, extraction_method, parser_version,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'corrected',
                             ?, 1.0, 'human_entered', 'human', ?, ?)""",
            (
                str(uuid.uuid4()), user["id"], patient["id"],
                source_id, source_page,
                values["occurrence_date"],
                values["vaccine_code"], values["diseases"], values["product_name"],
                *_dose_details(dose),
                values["dose_number"], values["doses_in_series"], lot, dose.note.strip()[:500],
                source_kind, user["id"], evidence, now, now,
            ),
        )
        if source_document is not None:
            refresh_card_review(connection, user["id"], source_document["id"], user["id"])
        connection.commit()
    return RedirectResponse(f"{destination}{joiner}saved=added", status_code=303)

def _answer_dose(connection, user_id: str, row, immunization_id: str, action: str) -> str:
    """Apply `verify` or `remove` and commit; "" for any other action."""
    if action == "verify":
        connection.execute(
            """UPDATE immunizations SET verification_status='verified',
                       entered_by_user_id=?, updated_at=? WHERE id=?""",
            (user_id, utc_now(), immunization_id),
        )
        saved = _VERIFIED_STATE
    elif action == "remove":
        if row["entry_source"] == "manual":
            connection.execute(
                "DELETE FROM immunizations WHERE id=?", (immunization_id,)
            )
        else:
            # Not deleted: re-reading the card would find the same row
            # again and put it straight back.  `rejected` is the answer
            # `store_document_doses` protects and `doses_for` hides.
            connection.execute(
                """UPDATE immunizations SET verification_status='rejected',
                           entered_by_user_id=?, updated_at=? WHERE id=?""",
                (user_id, utc_now(), immunization_id),
            )
        saved = "removed"
    else:
        return ""
    if row["document_id"]:
        refresh_card_review(connection, user_id, row["document_id"], user_id)
    connection.commit()
    return saved


@router.post("/vaccinations/{immunization_id}", responses=_RESPONSES_401_403_404)
def update_vaccination(
    request: Request,
    immunization_id: str,
    dose: Annotated[_DoseFields, Depends(_dose_fields)],
    action: Annotated[str, Form()] = "save",
    next: Annotated[str, Form()] = _VACCINATIONS_URL,
    csrf_token: Annotated[str, Form()] = "",
):
    """Confirm, correct or set aside one dose.

    Three actions on one route because they are three answers to the same
    question — is this row what the card says?  `verify` accepts it,
    `save` replaces it, `remove` says it should not be there.  All three
    move the row out of `extracted`, which is what stops the next re-read
    of the card from overwriting the person's answer.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    destination = _safe_next(next, _VACCINATIONS_URL)
    joiner = "&" if "?" in destination else "?"
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT * FROM immunizations WHERE id=? AND owner_user_id=?",
            (immunization_id, user["id"]),
        ).fetchone()
        if row is None:
            raise HTTPException(404)
        answered = _answer_dose(connection, user["id"], row, immunization_id, action)
        if answered:
            return RedirectResponse(f"{destination}{joiner}saved={answered}", status_code=303)

        values, problem = _dose_form_values(
            dose.occurred_on, dose.vaccine_code, dose.product_name, dose.dose_number, dose.doses_in_series
        )
        if problem:
            return RedirectResponse(f"{destination}{joiner}error={problem}", status_code=303)
        lot = dose.lot_number.strip()[:80]
        if lot and connection.execute(
            """SELECT 1 FROM immunizations WHERE owner_user_id=? AND occurrence_date=?
                   AND lot_number=? AND id<>?""",
            (user["id"], values["occurrence_date"], lot, immunization_id),
        ).fetchone():
            return RedirectResponse(f"{destination}{joiner}error=duplicate", status_code=303)
        connection.execute(
            """UPDATE immunizations SET occurrence_date=?, vaccine_code=?, diseases=?,
                       product_name=?, manufacturer=?, trade_name=?, facility=?, clinician=?,
                       event_kind=?, dose_number=?,
                       doses_in_series=?, lot_number=?, note=?, verification_status='corrected',
                       entered_by_user_id=?, updated_at=? WHERE id=?""",
            (
                values["occurrence_date"], values["vaccine_code"], values["diseases"],
                values["product_name"], *_dose_details(dose),
                values["dose_number"], values["doses_in_series"], lot, dose.note.strip()[:500],
                user["id"], utc_now(), immunization_id,
            ),
        )
        if row["document_id"]:
            refresh_card_review(connection, user["id"], row["document_id"], user["id"])
        connection.commit()
    return RedirectResponse(f"{destination}{joiner}saved=saved", status_code=303)

def _panel_context(connection, owner_user_id: str, panel_id: str) -> dict[str, object]:
    panel = PANEL_BY_ID.get(panel_id)
    if panel is None:
        raise HTTPException(404)
    catalog = _metric_catalog(connection, owner_user_id)
    by_id = _by_id(catalog)
    member_ids = panel_members(connection, panel)
    names = _panel_member_names(
        connection, [key for key in member_ids if key not in by_id]
    )
    card = _panel_card(connection, panel, by_id, names)
    rows = list(card["members"])
    dates = [
        _date_key(point["date"]) for row in rows for point in (row.get("series") or [])
    ]
    span = (min(dates), max(dates)) if dates else None
    sparklines = {}
    for row in rows:
        spark = _sparkline(row, span)
        if spark:
            sparklines[str(row["id"])] = spark
    concept_ids = [str(row["id"]) for row in rows if not row["is_device"]]
    documents = []
    if concept_ids:
        placeholders = ",".join("?" for _ in concept_ids)
        documents = [
            _document_row(row)
            for row in connection.execute(
                f"""SELECT d.id, d.title, d.original_filename, d.report_date, d.imported_at,
                               d.clinical_type, d.page_count, v.canonical_name vendor,
                               COUNT(DISTINCT o.id) observation_count
                        FROM documents d JOIN vendors v ON v.id=d.vendor_id
                        JOIN observations o ON o.document_id=d.id AND o.verification_status <> 'rejected'
                        WHERE d.owner_user_id=? AND o.concept_id IN ({placeholders})
                        GROUP BY d.id
                        ORDER BY COALESCE(d.report_date, d.imported_at) DESC""",
                [owner_user_id, *concept_ids],
            )
        ]
    guidance_index = _guidance_index(connection)
    entries = [guidance_index.get(str(row["id"]).removeprefix(_DEVICE_METRIC_PREFIX)) for row in rows]
    entries = [entry for entry in entries if entry]
    return {
        "panel": card,
        "rows": rows,
        "sparklines": sparklines,
        "documents": documents,
        "sources": sources_for(
            connection,
            [str(row["id"]).removeprefix(_DEVICE_METRIC_PREFIX) for row in rows],
        ),
        "guidance": {
            "short_description": card["description"],
            # A member's why-it-matters is the panel's only when it is the
            # only member; CBC must not present hemoglobin's text as its own.
            "why_it_matters": (
                translate_phrase(str(entries[0]["why_it_matters"]))
                if len(entries) == 1 and entries[0].get("why_it_matters")
                else None
            ),
        },
        "renderer": panel.renderer,
    }

@router.get("/panels/{panel_id}", response_class=HTMLResponse, responses=_RESPONSES_401_404)
def panel_detail(request: Request, panel_id: str):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        context = _panel_context(connection, user["id"], panel_id)
        rows = context["rows"]
        context["allergy"] = (
            _allergy_block(connection, rows) if context["renderer"] == "allergy" else None
        )
        context["blood_pressure"] = (
            _bp_block(connection, user["id"], rows)
            if context["renderer"] == "blood_pressure"
            else None
        )
    return templates.TemplateResponse(
        request,
        "panel_detail.html",
        template_context(
            request,
            **context,
            export_url=f"/panels/{panel_id}/export",
            ai_scope_label=context["panel"]["name"],
            active="panels",
        ),
    )

def _render_health_export(
    request: Request,
    *,
    origin_kind: str,
    origin_id: str,
    metric: list[str] | None,
    aggregation: str,
    custom: int,
):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    aggregation = aggregation if aggregation in AGGREGATION_KEYS else "auto"
    with connect(settings) as connection:
        options = _export_options(connection, user["id"])
        option_by_id = {str(card["id"]): card for card in options}
        if origin_kind == "panel":
            context = _panel_context(connection, user["id"], origin_id)
            defaults = [str(row["id"]) for row in context["rows"]]
            origin_name = str(context["panel"]["name"])
            back_url = f"/panels/{origin_id}"
            export_url = f"/panels/{origin_id}/export"
        elif origin_kind == "metric":
            card = option_by_id.get(origin_id)
            if card is None:
                raise HTTPException(404)
            defaults = [origin_id]
            origin_name = str(card["name"])
            back_url = f"/metrics/{origin_id}"
            export_url = f"/metrics/{origin_id}/export"
        else:
            metric_id = f"device:{origin_id}"
            card = option_by_id.get(metric_id)
            if card is None:
                raise HTTPException(404)
            defaults = [metric_id]
            origin_name = str(card["name"])
            back_url = f"/devices/metrics/{origin_id}"
            export_url = f"/devices/metrics/{origin_id}/export"
        selected = list(metric or []) if custom else defaults
        export = _health_export_payload(
            connection, user["id"], selected, aggregation, options
        )
    return templates.TemplateResponse(
        request,
        "health_export.html",
        template_context(
            request,
            export=export,
            export_url=export_url,
            back_url=back_url,
            origin_name=origin_name,
            metric_groups=_export_metric_groups(options),
            selected_ids=set(export["selected_ids"]),
            aggregation=aggregation,
            aggregation_options=("auto", "exact", "month", "quarter", "year"),
            selection_error=bool(custom and not export["metrics"]),
            active={"panel": "panels", "metric": "metrics", "device": "devices"}[origin_kind],
        ),
    )

@router.get("/panels/{panel_id}/export", response_class=HTMLResponse, responses=_RESPONSES_401_404)
def panel_export(
    request: Request,
    panel_id: str,
    metric: Annotated[list[str] | None, Query()] = None,
    aggregation: str = "auto",
    custom: int = 0,
):
    return _render_health_export(
        request,
        origin_kind="panel",
        origin_id=panel_id,
        metric=metric,
        aggregation=aggregation,
        custom=custom,
    )

@router.get("/metrics/{concept_id}/export", response_class=HTMLResponse, responses=_RESPONSES_401_404)
def metric_export(
    request: Request,
    concept_id: str,
    metric: Annotated[list[str] | None, Query()] = None,
    aggregation: str = "auto",
    custom: int = 0,
):
    return _render_health_export(
        request,
        origin_kind="metric",
        origin_id=concept_id,
        metric=metric,
        aggregation=aggregation,
        custom=custom,
    )

@router.get("/devices/metrics/{metric_key}/export", response_class=HTMLResponse, responses=_RESPONSES_401_404)
def device_metric_export(
    request: Request,
    metric_key: str,
    metric: Annotated[list[str] | None, Query()] = None,
    aggregation: str = "auto",
    custom: int = 0,
):
    return _render_health_export(
        request,
        origin_kind="device",
        origin_id=metric_key,
        metric=metric,
        aggregation=aggregation,
        custom=custom,
    )

@router.get("/exports/health-history.pdf", responses=_RESPONSES_401)
def health_history_pdf(
    request: Request,
    metric: Annotated[list[str] | None, Query()] = None,
    aggregation: str = "auto",
):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    aggregation = aggregation if aggregation in AGGREGATION_KEYS else "auto"
    with connect(settings) as connection:
        export = _health_export_payload(
            connection, user["id"], list(metric or []), aggregation
        )
    if not export["metrics"]:
        return PlainTextResponse(t("export.select_one_body"), status_code=400)
    content = render_pdf(export, _export_pdf_labels())
    filename = f"health-history-{date.today().isoformat()}.pdf"
    return Response(
        content,
        media_type=_PDF_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )

@router.get("/api/panels/{panel_id}", responses=_RESPONSES_401_404)
def panel_json(request: Request, panel_id: str):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        context = _panel_context(connection, user["id"], panel_id)
        rows = context["rows"]
        allergy = (
            _allergy_block(connection, rows) if context["renderer"] == "allergy" else None
        )
        blood_pressure = (
            _bp_block(connection, user["id"], rows)
            if context["renderer"] == "blood_pressure"
            else None
        )

    def public(row: dict[str, object]) -> dict[str, object]:
        # A copy, never a pop: these dicts ARE the memoised catalog cards,
        # and mutating them broke every later search until restart.
        return {key: value for key, value in row.items() if key != "search_terms"}

    return {
        "panel": {
            **context["panel"],
            "members": [public(member) for member in context["panel"]["members"]],
        },
        "rows": [public(row) for row in rows],
        "sparklines": context["sparklines"],
        "documents": context["documents"],
        "sources": context["sources"],
        "guidance": context["guidance"],
        "renderer": context["renderer"],
        "allergy": allergy,
        "blood_pressure": blood_pressure,
    }

# --- insights (retired) -------------------------------------------------

@router.get("/insights")
def insights():
    """Retired: every section it had is a status filter on /metrics now.

    301 so bookmarks and a guest's old link land on the same list.
    """
    return RedirectResponse("/metrics?status=attention", status_code=301)

# --- areas --------------------------------------------------------------

@router.get("/areas/{area_id}", response_class=HTMLResponse, responses=_RESPONSES_401_404)
def health_area_detail(request: Request, area_id: str):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    definition = AREA_BY_ID.get(area_id)
    if not definition:
        raise HTTPException(404)
    with connect(settings) as connection:
        catalog = _metric_catalog(connection, user["id"])
        findings = _finding_catalog(connection, user["id"])
        panels = _panel_cards(connection, user["id"], member_limit=6)
        area = next(item for item in _areas(catalog, findings, panels) if item["id"] == area_id)
        metrics = [item for item in catalog if area_id in item["area_ids"]]
        metrics.sort(
            key=lambda item: (
                _attention_rank(item),
                0 if item["primary_area_id"] == area_id else 1,
                -_date_key(item["latest_date"]),
            )
        )
        area_findings = [item for item in findings if item["health_area"] == area_id]
        # Activity, mobility and sleep are measured by a wearable every
        # day, so they read as a tracker dashboard: daily bars, weekly and
        # monthly averages, a month-on-month comparison, and the sleep
        # stages stacked per night. The metrics the tracker covers leave
        # the flat measurement grid — the same number twice is noise.
        tracker = area_tracker(connection, user["id"], area_id)
        measurement_count = len(metrics)
        experience = build_area_experience(area, metrics, tracker)
        if tracker:
            covered = {f"device:{card['metric_key']}" for card in tracker["cards"]}
            if tracker["sleep"]:
                covered.update(
                    f"device:{key}"
                    for key in (*SLEEP_STAGE_KEYS, "sleep_duration", "time_in_bed")
                )
            metrics = [item for item in metrics if str(item["id"]) not in covered]
        # The heart is the one area whose evidence is mostly not a lab
        # result: a cuff writes the pressure and a wrist writes the beat.
        # Both are read here rather than only inside their own panels.
        blood_pressure = _bp_block(connection, user["id"], catalog) if area_id == "heart" else None
        ecg_recordings = (
            [_ecg_card(row) for row in _ecg_rows(connection, user["id"])]
            if area_id == "heart"
            else []
        )
        big_table = _area_table(connection, area_id, metrics)
        concept_ids = [str(item["id"]) for item in metrics if not item["is_device"]]
        evidence_terms = [
            "EXISTS (SELECT 1 FROM clinical_findings ef WHERE ef.document_id=d.id"
            " AND ef.health_area=? AND ef.verification_status <> 'rejected')"
        ]
        params: list[object] = [user["id"], area_id]
        if concept_ids:
            placeholders = ",".join("?" for _ in concept_ids)
            evidence_terms.append(
                f"EXISTS (SELECT 1 FROM observations eo WHERE eo.document_id=d.id"
                f" AND eo.verification_status <> 'rejected' AND eo.concept_id IN ({placeholders}))"
            )
            params.extend(concept_ids)
        documents = [
            _document_row(row)
            for row in connection.execute(
                f"""SELECT d.id, d.title, d.original_filename, d.report_date, d.imported_at,
                                d.clinical_type, d.page_count, v.canonical_name vendor,
                                COUNT(DISTINCT o.id) observation_count,
                                COUNT(DISTINCT f.id) finding_count
                         FROM documents d JOIN vendors v ON v.id=d.vendor_id
                         LEFT JOIN observations o ON o.document_id=d.id AND o.verification_status <> 'rejected'
                         LEFT JOIN clinical_findings f ON f.document_id=d.id AND f.health_area=?
                           AND f.verification_status <> 'rejected'
                         WHERE d.owner_user_id=? AND d.duplicate_of_document_id IS NULL
                           AND ({' OR '.join(evidence_terms)})
                         GROUP BY d.id
                         ORDER BY COALESCE(d.report_date, d.imported_at) DESC""",
                [area_id, *params],
            )
        ]
    return templates.TemplateResponse(
        request,
        "area_detail.html",
        template_context(
            request,
            area=area,
            experience=experience,
            panels=area["panels"],
            metrics=metrics,
            measurement_count=measurement_count,
            tracker=tracker,
            findings=area_findings,
            big_table=big_table,
            documents=documents,
            blood_pressure=blood_pressure,
            ecg_recordings=ecg_recordings,
            has_attention=area["status"] == "attention",
            ai_scope_label=area["name"],
            active="dashboard",
        ),
    )

# --- documents ----------------------------------------------------------

def _paperless_matches(settings, connection, owner_user_id: str, q: str) -> list[str]:
    """Local ids of this person's documents whose Paperless copy matches
    the query's full text.  Empty on any failure — a Paperless that is
    down must leave search exactly as it was without it."""
    try:
        ready = paperless.connection_for(settings, owner_user_id)
        if not ready:
            return []
        remote_ids = paperless.cached_search_ids(*ready, q)
        if not remote_ids:
            return []
        marks = ",".join("?" * len(remote_ids))
        return [
            str(row["id"])
            for row in connection.execute(
                f"SELECT id FROM documents WHERE owner_user_id=? AND paperless_id IN ({marks})",
                [owner_user_id, *remote_ids],
            )
        ]
    except Exception:
        return []

def _document_text_matcher(settings, connection, owner_user_id: str, q: str,
                           use_paperless: bool) -> tuple[str, list[object]]:
    """The search-text condition and its parameters, for a non-blank ``q``."""
    # COALESCE so a row whose folded copy has not been written yet is
    # still searchable, at the old case-sensitive quality, rather than
    # dropping out of every result.
    matcher = (
        "(COALESCE(s.content_folded, s.content, '') LIKE ? "
        "OR COALESCE(d.original_filename, '') LIKE ? "
        "OR COALESCE(d.title, '') LIKE ?)"
    )
    matcher_params: list[object] = [
        f"%{search_key(q.strip())}%",
        f"%{q.strip()}%",
        f"%{q.strip()}%",
    ]
    # Paperless read the same files with its own OCR, so its full-text
    # index catches wording ours missed.  Only documents this person
    # already owns can come back — the ids are mapped through the
    # stored link, never taken from Paperless on trust.
    linked = _paperless_matches(settings, connection, owner_user_id, q.strip()) if use_paperless else []
    if linked:
        matcher = f"({matcher} OR d.id IN ({','.join('?' * len(linked))}))"
        matcher_params.extend(linked)
    return matcher, matcher_params


def _card_review_need(row: dict[str, object], task: dict[str, object]) -> str:
    """What an unresolved review still asks of one document card."""
    pending = int(row.get("pending_count") or 0)
    if pending:
        review_need = t_plural("documents.values_to_check", pending)
    else:
        review_need = _review_status({**task, "observation_count": row.get("observation_count")})["reason_text"]
    proposed = sum(
        len(dict(part.get("params") or {}).get("items") or [])
        for part in _reason_parts_of(task)
        if part.get("key") in ("review.reread_changed_n", "review.reread_orphaned_n")
    )
    if not proposed:
        return review_need
    # Without this a fully checked file whose re-read reads 18
    # values differently showed nothing at all on its card.
    need = t_plural("reread.queue_n", proposed)
    return f"{review_need} · {need}" if pending else need


def _mark_review_needs(connection, rows: list[dict[str, object]]) -> None:
    # What each file still needs, said on its card: the review queue used to
    # list files under a generic heading with no hint of why each was there.
    task_ids = [str(row["review_task_id"]) for row in rows if row.get("review_task_id")]
    tasks = {
        str(task["id"]): dict(task)
        for task in connection.execute(
            f"SELECT * FROM review_tasks WHERE id IN ({','.join('?' * len(task_ids))})", task_ids
        )
    } if task_ids else {}
    for row in rows:
        task = tasks.get(str(row.get("review_task_id") or ""))
        row["review_state"] = task["state"] if task else None
        row["review_need"] = ""
        if task and task["state"] != "resolved":
            row["review_need"] = _card_review_need(row, task)


def _mark_same_report(connection, owner_user_id: str, rows: list[dict[str, object]]) -> None:
    # Two files of one report each ask to be checked; the card says so, and
    # the document page is where the person keeps one.
    pairs = _same_report_pairs(
        connection, owner_user_id, [str(row["id"]) for row in rows if not row.get("duplicate_of_document_id")]
    )
    briefs = _document_briefs(connection, owner_user_id, {other for found in pairs.values() for other, _, _ in found})
    ids = [str(row["id"]) for row in rows]
    parted = {
        str(item)
        for found in connection.execute(
            f"""SELECT source_document_id, target_document_id FROM document_relations
                 WHERE relationship='part_of' AND (source_document_id IN ({",".join("?" * len(ids))})
                       OR target_document_id IN ({",".join("?" * len(ids))}))""",
            (*ids, *ids),
        )
        for item in found
    } if ids else set()
    for row in rows:
        others = [briefs[other] for other, _, _ in pairs.get(str(row["id"]), []) if other in briefs]
        row["same_report_text"] = t(
            "dup.card_same_as", title=others[0]["title_text"], date=format_date(others[0].get("report_date"))
        ) if others else (t("dup.card_part") if str(row["id"]) in parted else "")


def _document_search(settings, connection, owner_user_id: str, q: str, clinical_type: str,
                     vendor: str, review_state: str, offset: int,
                     use_paperless: bool = True) -> tuple[int, list[dict[str, object]]]:
    """The filtered page of documents, for a page load and for live search.

    One query behind both, so the list the search box paints can never be
    assembled differently from the list a reload produces.

    ``use_paperless`` is False for someone viewing a shared record: their
    search text would otherwise be sent to the patient's Paperless server
    under the patient's token, which is neither theirs to spend nor part
    of what the patient shared.
    """
    conditions = ["d.owner_user_id=?"]
    params: list[object] = [owner_user_id]
    if q.strip():
        matcher, matcher_params = _document_text_matcher(
            settings, connection, owner_user_id, q, use_paperless
        )
        conditions.append(matcher)
        params.extend(matcher_params)
    if clinical_type:
        conditions.append("d.clinical_type=?")
        params.append(clinical_type)
    if vendor:
        conditions.append("v.id=?")
        params.append(vendor)
    if review_state:
        conditions.append(
            "(SELECT rt.state FROM review_tasks rt WHERE rt.owner_user_id=d.owner_user_id "
            "AND rt.entity_type='document' AND rt.entity_id=d.id "
            "ORDER BY rt.created_at DESC, rt.rowid DESC LIMIT 1)=?"
        )
        params.append(review_state)
    where = " AND ".join(conditions)
    total = connection.execute(
        f"""SELECT COUNT(DISTINCT d.id) FROM documents d
                LEFT JOIN vendors v ON v.id=d.vendor_id
                LEFT JOIN search_index s ON s.document_id=d.id WHERE {where}""",
        params,
    ).fetchone()[0]
    rows = [
        _document_row(row)
        for row in connection.execute(
            f"""SELECT d.*, v.canonical_name vendor, COUNT(DISTINCT o.id) observation_count,
                            COUNT(DISTINCT CASE WHEN o.verification_status='extracted' THEN o.id END) pending_count,
                            COUNT(DISTINCT r.id) report_count,
                            GROUP_CONCAT(DISTINCT t.name) tags,
                            (SELECT rt.id FROM review_tasks rt
                              WHERE rt.owner_user_id=d.owner_user_id AND rt.entity_type='document' AND rt.entity_id=d.id
                              ORDER BY rt.created_at DESC, rt.rowid DESC LIMIT 1) review_task_id,
                            {_TITLE_TESTS_SQL}
                     FROM documents d LEFT JOIN vendors v ON v.id=d.vendor_id
                     LEFT JOIN search_index s ON s.document_id=d.id
                     LEFT JOIN reports r ON r.document_id=d.id
                     LEFT JOIN observations o ON o.document_id=d.id AND o.verification_status <> 'rejected'
                     LEFT JOIN document_tags dt ON dt.document_id=d.id
                     LEFT JOIN tags t ON t.id=dt.tag_id
                     WHERE {where} GROUP BY d.id
                     ORDER BY d.imported_at DESC, d.rowid DESC
                     LIMIT ? OFFSET ?""",
            [*params, DOCUMENT_PAGE_SIZE, max(0, offset)],
        )
    ]
    _mark_review_needs(connection, rows)
    _mark_same_report(connection, owner_user_id, rows)
    return int(total), rows

@router.get("/api/documents/search", responses=_RESPONSES_401_404)
def document_search(
    request: Request,
    q: str = "",
    clinical_type: str = "",
    vendor: str = "",
    review_state: str = "",
    offset: int = 0,
):
    """The document list as rendered cards, for search-as-you-type.

    Cards rather than JSON, from the same macro the page load uses: see the
    note in `_document_cards.html` for what rebuilding them in the browser
    cost the metrics page.
    """
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    if review_state and review_state not in REVIEW_STATES:
        raise HTTPException(404)
    offset = max(0, offset)
    with connect(settings) as connection:
        total, rows = _document_search(settings,
            connection, user["id"], q, clinical_type, vendor, review_state, offset,
            use_paperless=viewing_row(request) is None,
        )
        stale = set(_stale_document_ids(connection, user["id"]))
    for row in rows:
        row["is_stale"] = str(row["id"]) in stale
    context = template_context(request)
    base = f"/documents?q={q}&clinical_type={clinical_type}&vendor={vendor}&review_state={review_state}"
    return {
        "documents": templates.get_template("_document_cards.html").render(
            {**context, "documents": rows}
        ),
        "pagination": templates.get_template("_pagination.html").render(
            {**context, "page": _pagination(total, offset, DOCUMENT_PAGE_SIZE, base)}
        ),
        "total": total,
        "total_text": format_count(total),
    }

@router.get(_DOCUMENTS_URL, response_class=HTMLResponse, responses=_RESPONSES_401_404)
def documents(
    request: Request,
    q: str = "",
    clinical_type: str = "",
    vendor: str = "",
    review_state: str = "",
    offset: int = 0,
    rescan: str = "",
    count: int = 0,
    deleted: str = "",
    promoted: str = "",
    delete_error: str = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    if review_state and review_state not in REVIEW_STATES:
        raise HTTPException(404)
    offset = max(0, offset)
    with connect(settings) as connection:
        total, rows = _document_search(settings,
            connection, user["id"], q, clinical_type, vendor, review_state, offset,
            use_paperless=viewing_row(request) is None,
        )
        # Facets are named, not spelled out of the enum: `radiology mri (8)`
        # is a column value, not a label a person recognises.
        types = [
            {
                **dict(row),
                "label": translate_phrase(
                    DOCUMENT_TYPE_TITLES.get(
                        str(row["clinical_type"] or ""), enum_label(str(row["clinical_type"] or ""))
                    )
                ),
            }
            for row in connection.execute(
                "SELECT clinical_type, COUNT(*) count FROM documents WHERE owner_user_id=? GROUP BY clinical_type ORDER BY clinical_type",
                (user["id"],),
            )
        ]
        vendors = [
            {**dict(row), "label": translate_phrase(str(row["canonical_name"]))}
            for row in connection.execute(
                """SELECT v.id, v.canonical_name, COUNT(*) count FROM documents d JOIN vendors v ON v.id=d.vendor_id
                       WHERE d.owner_user_id=? GROUP BY v.id ORDER BY v.canonical_name""",
                (user["id"],),
            )
        ]
        review_counts = {
            str(row["state"]): int(row["count"])
            for row in connection.execute(
                """SELECT state, COUNT(*) count FROM (
                         SELECT d.id,
                                (SELECT rt.state FROM review_tasks rt
                                  WHERE rt.owner_user_id=d.owner_user_id AND rt.entity_type='document' AND rt.entity_id=d.id
                                  ORDER BY rt.created_at DESC, rt.rowid DESC LIMIT 1) state
                           FROM documents d WHERE d.owner_user_id=?
                       ) current_review WHERE state IS NOT NULL GROUP BY state""",
                (user["id"],),
            )
        }
        all_document_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM documents WHERE owner_user_id=?", (user["id"],)
            ).fetchone()[0]
        )
        stale = set(_stale_document_ids(connection, user["id"]))
        # A re-read that failed leaves the file exactly as stale as it was,
        # so the panel would otherwise invite the same fruitless press
        # forever without ever mentioning the last one.
        # Counted per file, by its latest re-read: one that failed and then
        # succeeded is not still failing.
        rescan_failed = int(
            connection.execute(
                """SELECT COUNT(*) FROM (
                         SELECT state, ROW_NUMBER() OVER (
                                  PARTITION BY document_id ORDER BY created_at DESC, rowid DESC) latest
                           FROM upload_jobs
                          WHERE owner_user_id=? AND kind='rescan' AND document_id IS NOT NULL
                       ) WHERE latest=1 AND state='failed'""",
                (user["id"],),
            ).fetchone()[0]
        )
    for row in rows:
        row["is_stale"] = str(row["id"]) in stale
    base = f"/documents?q={q}&clinical_type={clinical_type}&vendor={vendor}&review_state={review_state}"
    return templates.TemplateResponse(
        request,
        "documents.html",
        template_context(
            request, documents=rows, types=types, vendors=vendors, q=q,
            selected_type=clinical_type, selected_vendor=vendor,
            selected_review_state=review_state, review_counts=review_counts,
            all_document_count=all_document_count,
            page=_pagination(int(total), offset, DOCUMENT_PAGE_SIZE, base),
            total_documents=int(total),
            stale_count=len(stale),
            stale_count_text=format_count(len(stale)),
            parser_version=PARSER_VERSION,
            rescan_queued=rescan == "queued",
            rescan_none=rescan == "none",
            rescan_queued_text=t_plural("rescan.bulk_queued", count),
            rescan_failed=rescan_failed,
            rescan_failed_text=t_plural("rescan.failed", rescan_failed),
            stale_line_text=t_plural("rescan.bulk_line", len(stale)),
            # The review state is the queue itself, named in the heading; it
            # does not keep the filter panel open on a phone.
            filters_active=bool(q or clinical_type or vendor),
            document_deleted=deleted == "1",
            document_promoted=promoted == "1",
            document_delete_busy=delete_error == "busy",
            upload_error=request.query_params.get("upload_error"),
            # Explains why a search can match text no local extraction
            # holds; shown only to someone actually connected.
            paperless_search=paperless.connection_for(settings, user["id"]) is not None,
            active="documents",
        ),
    )

def _given_here(connection, user_id: str, document_id: str) -> list[dict[str, str]]:
    """Doses a visit note on this document says were given that day."""
    all_doses = doses_for(connection, user_id)
    notes = visit_notes(connection, user_id, all_doses)
    return [
        {
            "date_text": format_date_localized(dose["occurrence_date"]),
            "name": str(_dose_row(dose)["trade"] or dose.get("vaccine_code") or ""),
            "lot": str(dose.get("lot_number") or ""),
        }
        for dose in all_doses
        if any(note["id"] == document_id for note in notes.get(str(dose["id"]), []))
    ]


def _document_hint_rounds(connection, document_id: str, hint: str):
    """Every AI review round in this locale, and the one to show: the
    requested round when it exists, else the latest."""
    hint_rounds = connection.execute(
        """SELECT id, model, created_at
                 FROM ai_document_hints
                WHERE document_id=? AND locale=?
                ORDER BY created_at DESC, id DESC""",
        (document_id, get_locale()),
    ).fetchall()
    hints_row = None
    if hint.isdecimal():
        hints_row = connection.execute(
            """SELECT id, model, content_json, created_at
                     FROM ai_document_hints
                    WHERE id=? AND document_id=? AND locale=?""",
            (int(hint), document_id, get_locale()),
        ).fetchone()
    if hints_row is None:
        hints_row = connection.execute(
            """SELECT id, model, content_json, created_at
                     FROM ai_document_hints
                    WHERE document_id=? AND locale=?
                    ORDER BY created_at DESC, id DESC LIMIT 1""",
            (document_id, get_locale()),
        ).fetchone()
    return hint_rounds, hints_row


def _fill_missed_value(item: dict, document: dict[str, object]) -> None:
    # Missing-value hints are drafts, not inert prose. Split a numeric
    # suggestion into the field the manual-entry endpoint validates;
    # everything else stays editable as text before it is saved.
    suggested = str(item.get("value") or "").strip()
    comparator, number_text = split_comparator(suggested)
    if number_text and parse_decimal(number_text) is not None:
        item["numeric_input"] = f"{comparator or ''}{number_text}"
        item["text_input"] = ""
    else:
        item["numeric_input"] = ""
        item["text_input"] = suggested
    try:
        item["page_input"] = max(1, min(int(item.get("page") or 1), int(document["page_count"] or 1)))
    except (TypeError, ValueError):
        item["page_input"] = 1
    item["observed_input"] = item.get("observed_at") or document.get("report_date") or ""


def _suspicious_rows(settings, document_id: str, ai_hints: dict) -> dict:
    """The rows the review flagged, as they stand now."""
    suspicious_ids = [
        str(item.get("observation_id") or "") for item in ai_hints.get("suspicious", [])
    ]
    if not suspicious_ids:
        return {}
    with connect(settings) as connection:
        return {
            row["id"]: row
            for row in connection.execute(
                f"""SELECT o.id, o.raw_name, o.value_numeric, o.value_text, o.comparator,
                               o.unit_raw, o.vendor_reference_text, o.verification_status,
                               c.canonical_name
                          FROM observations o LEFT JOIN concepts c ON c.id=o.concept_id
                         WHERE o.document_id=? AND o.id IN ({",".join("?" * len(suspicious_ids))})""",
                (document_id, *suspicious_ids),
            )
        }


def _suspicious_value_inputs(item: dict, row) -> tuple[str, str, str]:
    """The suggested value, and the numeric and text inputs the fix form starts from."""
    suggested_value = str(item.get("suggested_value") or "").strip()
    if suggested_value:
        comparator, number_text = split_comparator(suggested_value)
        numeric_ok = bool(number_text) and parse_decimal(number_text) is not None
        numeric_input = f"{comparator or ''}{number_text}" if numeric_ok else ""
        text_input = "" if numeric_ok else suggested_value
    elif row["value_numeric"] is not None:
        numeric_input = f"{row['comparator'] or ''}{format_number(row['value_numeric'])}"
        text_input = ""
    else:
        numeric_input, text_input = "", row["value_text"] or ""
    return suggested_value, numeric_input, text_input


def _suspicious_fix_form(item: dict, row) -> tuple[dict[str, object], str]:
    """The prefilled correction form, and the suggested value it came from."""
    suggested_value, numeric_input, text_input = _suspicious_value_inputs(item, row)
    suggested_name = str(item.get("suggested_name") or "").strip()
    return {
        "raw_name": suggested_name or row["raw_name"],
        # A renamed row is re-resolved from its new name; an
        # unchanged name keeps the metric it is filed under now.
        "canonical_name": "" if suggested_name and suggested_name != row["raw_name"] else (row["canonical_name"] or ""),
        "numeric_input": numeric_input,
        "text_input": text_input,
        "unit": str(item.get("suggested_unit") or "").strip() or (row["unit_raw"] or ""),
        "reference": str(item.get("suggested_reference") or "").strip() or (row["vendor_reference_text"] or ""),
    }, suggested_value


def _suspicious_fix(item: dict, row) -> dict[str, object] | None:
    fix, suggested_value = _suspicious_fix_form(item, row)
    changed = (
        fix["raw_name"] != row["raw_name"]
        or fix["unit"] != (row["unit_raw"] or "")
        or fix["reference"] != (row["vendor_reference_text"] or "")
        or bool(suggested_value)
    )
    if changed and item.get("issue_type") != "not_measurement":
        return fix
    return None


def _mark_suspicious(item: dict, current_rows: dict) -> None:
    row = current_rows.get(str(item.get("observation_id") or ""))
    item["current_state"] = row["verification_status"] if row else "missing"
    item["fix"] = None
    if row is None or row["verification_status"] == "rejected":
        return
    item["fix"] = _suspicious_fix(item, row)


def _fill_missed_immunization(item: dict, document: dict[str, object]) -> None:
    item["page_input"] = max(
        1, min(int(item.get("page") or 1), int(document["page_count"] or 1))
    )
    item["date"] = item.get("occurred_on") or ""
    item["vaccine_entry"] = item.get("vaccine_code") or ""
    item["note"] = ""


def _document_ai_hints(settings, document_id: str, document: dict[str, object], hints_row):
    """The shown AI review round, with every suggestion turned into a draft form."""
    ai_hints = json.loads(hints_row["content_json"]) if hints_row else None
    if not ai_hints:
        return ai_hints
    # A round stored before the kind was an enum may carry a free-text
    # kind; it is not offered, because the route would refuse it.
    metadata = ai_hints.get("suggested_metadata") or {}
    if metadata.get("clinical_type") not in DOCUMENT_TYPE_TITLES:
        metadata["clinical_type"] = ""
    for item in ai_hints.get("missed_values", []):
        _fill_missed_value(item, document)
    # A suspicious row that carries a correction becomes a prefilled
    # form against the row as it stands now (it may have been fixed or
    # set aside since the review ran).  Empty suggested fields keep the
    # current value, so applying a unit fix cannot blank the number.
    current_rows = _suspicious_rows(settings, document_id, ai_hints)
    for item in ai_hints.get("suspicious", []):
        _mark_suspicious(item, current_rows)
    for item in ai_hints.get("missed_immunizations", []):
        _fill_missed_immunization(item, document)
    return ai_hints


def _document_listing(clinical_type: str, findings, observations):
    """Narrative flag, the observations listed as rows, and the readings
    (blood pressure, negative allergens) shown apart from them."""
    narrative = clinical_type in NARRATIVE_DOCUMENT_TYPES or (bool(findings) and not observations)
    bp_readings: list[dict[str, object]] = []
    negative_allergens: list[dict[str, object]] = []
    listed = observations
    if clinical_type == "blood_pressure":
        bp_readings, listed = _bp_readings(observations)
    elif clinical_type == "allergy":
        listed, negative_allergens = _split_negative_allergens(observations)
    return narrative, listed, bp_readings, negative_allergens


def _document_paperless(request: Request, settings, document_id: str,
                        document: dict[str, object]) -> tuple[str | None, bool]:
    """The link to this document's Paperless copy, and whether one is still pending."""
    # A copy in Paperless is linked lazily, on the page where the link
    # would appear: consumption over there takes as long as its OCR does,
    # and this is the first moment anyone looks.
    # ponytail: one task lookup per view while pending (10 s worst case
    # against a dead server); a background poller if that ever hurts.
    # Someone reading a shared record is shown none of this: that the
    # patient mirrors their documents to an external archive, at which
    # address, under which id, was not part of what they shared.
    owns_record = (
        viewing_row(request) is None
        and (current_user(request) or {}).get("token_kind") != "guest"
    )
    paperless_id = document.get("paperless_id")
    if not paperless_id and document.get("paperless_task_id") and owns_record:
        paperless_id = paperless.resolve_pending(settings, document_id)
    paperless_config = paperless.paperless_settings(settings)
    paperless_link = (
        paperless.document_url(paperless_config["url"], paperless_id)
        if owns_record and paperless_id and paperless_config["enabled"] == "1" and paperless_config["url"]
        else None
    )
    pending = bool(owns_record and not paperless_id and document.get("paperless_task_id"))
    return paperless_link, pending


def _hint_round_meta(round_row) -> dict[str, object]:
    return {
        "id": round_row["id"],
        "model": round_row["model"],
        "created_text": format_date(round_row["created_at"]),
        "created_time": round_row["created_at"][11:16],
    }


def _document_ai_error(request: Request) -> str | None:
    return (
        request.query_params.get("ai_error")
        if request.query_params.get("ai_error") in ("disabled", "budget", "provider_error", "in_progress", "truncated")
        else None
    )


@router.get("/documents/{document_id}", response_class=HTMLResponse, responses=_RESPONSES_401_404)
def document_detail(
    request: Request,
    document_id: str,
    rescan: str = "",
    hint: str = "",
    dup_error: str = "",
    finding_error: str = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        row = connection.execute(
            f"""SELECT d.*, v.canonical_name vendor, {_TITLE_TESTS_SQL} FROM documents d
                   LEFT JOIN vendors v ON v.id=d.vendor_id WHERE d.id=? AND d.owner_user_id=?""",
            (document_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404)
        document = _document_row(row)
        findings = _document_findings(connection, user["id"], document_id)
        reports = connection.execute(
            """SELECT r.*, v.canonical_name vendor FROM reports r LEFT JOIN vendors v ON v.id=r.vendor_id
                   WHERE r.document_id=? ORDER BY r.start_page""",
            (document_id,),
        ).fetchall()
        backfill_positions(
            connection, document_id, resolve_source_path(settings, str(row["source_path"] or ""))
        )
        observations = _document_observations(connection, user["id"], document_id)
        pages = connection.execute(
            "SELECT * FROM document_pages WHERE document_id=? ORDER BY page_number", (document_id,)
        ).fetchall()
        tags = connection.execute(
            """SELECT t.* FROM tags t JOIN document_tags dt ON dt.tag_id=t.id
                   WHERE dt.document_id=? ORDER BY t.name""",
            (document_id,),
        ).fetchall()
        relations = _document_relations_view(connection, user["id"], document)
        part_candidates = [] if document.get("duplicate_of_document_id") else _part_candidates(
            connection, user["id"], document
        )
        concepts = sorted(_concept_picker(connection))
        document["is_stale"] = document_id in set(_stale_document_ids(connection, user["id"]))
        known_vendors = _known_vendors(connection)
        issue_reports = _document_issue_reports(connection, user["id"], document_id)
        review_task = _document_review_task(connection, user["id"], document_id)
        proposals = reread_proposals(connection, user["id"], document_id)
        # A dose is reviewed here, not on /vaccinations: it was read off a
        # photograph by OCR, and "does this match the card?" can only be
        # answered next to the card.
        immunizations = [
            _dose_row(row)
            for row in connection.execute(
                """SELECT i.*, NULL document_title, NULL original_filename
                       FROM immunizations i
                       WHERE i.document_id=? AND i.verification_status <> 'rejected'
                       ORDER BY i.page_number, i.occurrence_date""",
                (document_id,),
            )
        ]
        # A clinic's visit note records the injections given that day; the
        # doses themselves live on the card they were read from (or were
        # typed in), so the note points at them rather than copying them.
        given_here = [] if immunizations else _given_here(connection, user["id"], document_id)
        hint_rounds, hints_row = _document_hint_rounds(connection, document_id, hint)
    ai_hints = _document_ai_hints(settings, document_id, document, hints_row)
    clinical_type = str(document.get("clinical_type") or "")
    narrative, listed, bp_readings, negative_allergens = _document_listing(
        clinical_type, findings, observations
    )
    paperless_link, paperless_pending = _document_paperless(request, settings, document_id, document)
    return templates.TemplateResponse(
        request,
        "document_detail.html",
        template_context(
            request, document=document, reports=reports, observations=observations, given_here=given_here,
            listed_observations=listed, bp_readings=bp_readings,
            negative_allergens=negative_allergens, findings=findings, narrative=narrative,
            pages=pages, tags=tags, relations=relations, concepts=concepts, part_candidates=part_candidates,
            dup_error=f"dup.error_{dup_error}" if dup_error in DUPLICATE_ERRORS else None,
            finding_error=f"doc.finding_error_{finding_error}" if finding_error in FINDING_ERRORS else None,
            # A written conclusion is never about what only a wearable measures.
            health_areas=[area for area in localized_health_areas() if area["id"] not in _DEVICE_ONLY_AREAS],
            rescan_queued=rescan == "queued", parser_version=PARSER_VERSION,
            known_vendors=known_vendors, document_kinds=_document_kinds(),
            issue_reports=issue_reports, ai_scope_label=document["title_text"],
            review_task=review_task,
            proposals=proposals,
            immunizations=immunizations,
            vaccine_options=_vaccine_options(),
            today=utc_now()[:10],
            # The tab appears when hints can be made or already exist; a
            # cached answer stays readable even after AI is switched off,
            # because it is data the reader already has.
            ai_assist=ai_active(settings, "document_review"),
            # The host of the route this page's button uses, not a global.
            ai_provider_host=ai_provider_host(settings, "document_review"),
            ai_hints=ai_hints,
            ai_hints_meta=_hint_round_meta(hints_row) if hints_row else None,
            ai_hint_rounds=[
                {
                    **_hint_round_meta(round_row),
                    "is_latest": index == 0,
                    "is_selected": bool(hints_row and round_row["id"] == hints_row["id"]),
                }
                for index, round_row in enumerate(hint_rounds)
            ],
            ai_error=_document_ai_error(request),
            paperless_link=paperless_link,
            paperless_pending=paperless_pending,
            return_url=f"/documents/{document_id}", active="documents"
        ),
    )

@router.get("/documents/{document_id}/source", responses=_RESPONSES_401_404)
def document_source(request: Request, document_id: str):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT source_path, mime_type, original_filename FROM documents WHERE id=? AND owner_user_id=?",
            (document_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404)
    path = resolve_source_path(settings, row["source_path"])
    if not path.is_file():
        raise HTTPException(404, t(_SOURCE_UNAVAILABLE_KEY))
    return FileResponse(path, media_type=row["mime_type"], filename=row["original_filename"], content_disposition_type="inline")

@router.get("/documents/{document_id}/pages/{page_number}/image", responses=_RESPONSES_401_404_415)
def document_page_image(request: Request, document_id: str, page_number: int):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        row = connection.execute(
            """SELECT source_path, mime_type, page_count, sha256
                   FROM documents WHERE id=? AND owner_user_id=?""",
            (document_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404)
    source = resolve_source_path(settings, row["source_path"])
    if not source.is_file() or page_number < 1 or page_number > int(row["page_count"]):
        raise HTTPException(404, t(_SOURCE_UNAVAILABLE_KEY))
    if str(row["mime_type"]).startswith("image/"):
        try:
            rendered = _render_image_page(
                settings.database_path.parent / "source-page-cache", source, str(row["sha256"]), page_number
            )
        except (OSError, EOFError, ValueError):
            raise HTTPException(404, t(_SOURCE_UNAVAILABLE_KEY)) from None
        return FileResponse(rendered, media_type="image/png")
    if row["mime_type"] != _PDF_MEDIA_TYPE:
        raise HTTPException(415)
    try:
        rendered = _render_pdf_page(
            settings.database_path.parent / "source-page-cache",
            source,
            str(row["sha256"]),
            page_number,
        )
    except (IndexError, ValueError):
        raise HTTPException(404) from None
    return FileResponse(rendered, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})

def _ai_hint_images(settings, row, pages, limits: dict | None = None) -> list[bytes]:
    """Render pages when text extraction is absent or too thin to support
    a narrative conclusion.  A pathology PDF in the real collection had
    a complete result visibly printed on page 1 but only its header in the
    text layer; requiring *all* pages to be textless silently discarded the
    most clinically useful source."""
    extracted_chars = sum(
        len((page["native_text"] or "").strip()) + len((page["ocr_text"] or "").strip())
        for page in pages
    )
    kind = str(row["clinical_type"] or "").casefold()
    narrative_scan = any(word in kind for word in ("patholog", "histolog", "radiolog"))
    limits = limits or {"paid": False, "images": 4}
    # A paid route always gets the rendered pages: checking each extracted
    # value against the printed table is what the review is for.
    if extracted_chars >= 800 and not narrative_scan and not limits["paid"]:
        return []
    source = resolve_source_path(settings, row["source_path"])
    if not source.is_file():
        return []
    images: list[bytes] = []
    try:
        if str(row["mime_type"]).startswith("image/"):
            from io import BytesIO

            from PIL import Image

            with Image.open(source) as opened:
                buffer = BytesIO()
                opened.convert("RGB").save(buffer, format="PNG")
            images.append(buffer.getvalue())
        elif row["mime_type"] == _PDF_MEDIA_TYPE:
            for page_number in range(1, min(int(row["page_count"]), int(limits["images"])) + 1):
                rendered = _render_pdf_page(
                    settings.database_path.parent / "source-page-cache",
                    source,
                    str(row["sha256"]),
                    page_number,
                )
                images.append(rendered.read_bytes())
    except Exception:
        # A hint request must never fail harder than "no images attached".
        return images
    return images

def _ai_hints_answer(request: Request, location: str, payload: dict[str, object],
                     status_code: int = 200):
    """JSON for the page's script, a redirect for a plain form post."""
    if _JSON_MEDIA_TYPE in request.headers.get("accept", ""):
        return JSONResponse(payload, status_code=status_code)
    return RedirectResponse(location, status_code=303)


def _ai_hint_inputs(connection, document_id: str, user_id: str):
    """Pages, observations and doses the review is asked about."""
    pages = connection.execute(
        "SELECT page_number, native_text, ocr_text FROM document_pages WHERE document_id=? ORDER BY page_number",
        (document_id,),
    ).fetchall()
    observations = connection.execute(
        """SELECT id, raw_name, value_numeric, value_text, comparator, unit_raw,
                      vendor_reference_text, page_number
                 FROM observations WHERE document_id=? AND owner_user_id=? ORDER BY page_number""",
        (document_id, user_id),
    ).fetchall()
    immunizations = connection.execute(
        """SELECT id, occurrence_date, vaccine_code, product_name, manufacturer,
                      dose_number, doses_in_series, lot_number, page_number
                 FROM immunizations WHERE document_id=? AND owner_user_id=?
                   AND verification_status <> 'rejected'
                 ORDER BY page_number, occurrence_date""",
        (document_id, user_id),
    ).fetchall()
    return pages, observations, immunizations


def _ai_hint_observation(obs) -> dict[str, object]:
    return {
        "id": obs["id"],
        "raw_name": obs["raw_name"],
        "value": (
            f"{obs['comparator'] or ''}{obs['value_numeric']}"
            if obs["value_numeric"] is not None
            else (obs["value_text"] or "")
        ),
        "unit": obs["unit_raw"] or "",
        "vendor_reference_text": obs["vendor_reference_text"] or "",
        "page_number": obs["page_number"],
    }


@router.post("/documents/{document_id}/ai-hints", responses=_RESPONSES_401_403_404)
def generate_ai_hints(
    request: Request,
    document_id: str,
    csrf_token: Annotated[str, Form()] = "",
    refresh: Annotated[str, Form()] = "",
):
    """Create an append-only review round, reusing the latest until refreshed.

    Synchronous on purpose: the reader pressed the button and is waiting
    for this document, a queue would add machinery to save nobody's time.
    Free pools can take tens of seconds; the button says so.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    locale = get_locale()
    with connect(settings) as connection:
        row = connection.execute(
            """SELECT d.*, v.canonical_name vendor FROM documents d
                   LEFT JOIN vendors v ON v.id=d.vendor_id WHERE d.id=? AND d.owner_user_id=?""",
            (document_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404)
        cached = connection.execute(
            "SELECT document_id FROM ai_document_hints WHERE document_id=? AND locale=?",
            (document_id, locale),
        ).fetchone()
        if cached and refresh != "1":
            location = f"/documents/{document_id}#side-panel-ai"
            return _ai_hints_answer(request, location, {"ok": True, "location": location, "cached": True})
        pages, observations, immunizations = _ai_hint_inputs(connection, document_id, user["id"])
    limits = ai_review_limits(settings)
    try:
        hints = document_hints(
            settings,
            document=dict(row),
            pages=[dict(page) for page in pages],
            observations=[_ai_hint_observation(obs) for obs in observations],
            immunizations=[dict(item) for item in immunizations],
            images=_ai_hint_images(settings, row, pages, limits),
            locale=locale,
        )
    except AIUnavailable as failure:
        reason = (
            failure.reason
            if failure.reason in ("disabled", "budget", "in_progress", "truncated")
            else "provider_error"
        )
        location = f"/documents/{document_id}?ai_error={reason}#side-panel-ai"
        return _ai_hints_answer(
            request, location, {"ok": False, "reason": reason, "location": location}, 503
        )
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO ai_document_hints(document_id, locale, provider, model, content_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
            (document_id, locale, hints.get("provider") or limits["provider"], hints["model"],
             json.dumps(hints, ensure_ascii=False), utc_now()),
        )
    location = f"/documents/{document_id}#side-panel-ai"
    return _ai_hints_answer(request, location, {"ok": True, "location": location})

@router.post("/documents/{document_id}/ai-title", responses=_RESPONSES_400_401_403_404)
def apply_ai_title(
    request: Request,
    document_id: str,
    title: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
):
    """Adopt the suggested title.  A person read it and pressed the button,
    so this is a human edit that a rescan's classifier must not undo —
    which is why it does not touch `classified_by` or anything derived."""
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    cleaned = collapse_space(title)[:240]
    if not cleaned:
        raise HTTPException(400)
    with connect(settings) as connection:
        updated = connection.execute(
            "UPDATE documents SET title=?, title_set_by='human' WHERE id=? AND owner_user_id=?",
            (cleaned, document_id, user["id"]),
        ).rowcount
    if not updated:
        raise HTTPException(404)
    _audit(settings, user["id"], user["id"], "ai_title_applied", "document", document_id, {"title": cleaned})
    return RedirectResponse(f"/documents/{document_id}#side-panel-ai", status_code=303)

def _applied_ai_details(*fields: tuple[bool, str, object]) -> dict[str, object]:
    """The selected fields only, as the audit event records them."""
    return {name: value for selected, name, value in fields if selected}


@router.post("/documents/{document_id}/ai-metadata", responses=_RESPONSES_400_401_403_404)
def apply_ai_metadata(
    request: Request,
    document_id: str,
    clinical_type: Annotated[str, Form()] = "",
    vendor: Annotated[str, Form()] = "",
    report_date: Annotated[str, Form()] = "",
    apply_clinical_type: Annotated[str, Form()] = "",
    apply_vendor: Annotated[str, Form()] = "",
    apply_report_date: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """Apply only the AI detail fields a person explicitly selected.

    The unchecked state is the safe default in the UI and is enforced here
    too: merely rendering or submitting a suggestion cannot replace all of
    the document's details as a group.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    selected_kind = apply_clinical_type == "1"
    selected_vendor = apply_vendor == "1"
    selected_date = apply_report_date == "1"
    if not any((selected_kind, selected_vendor, selected_date)):
        raise HTTPException(400, t("aiassist.select_one"))

    kind = collapse_space(clinical_type)[:100]
    vendor_name = collapse_space(vendor)[:200]
    clean_date = (
        _validated_date(report_date, _DOC_DATE_INVALID_KEY, required=True) if selected_date else None
    )
    # Only a kind the parser has a contract for.  A model answering in the
    # reader's language once stored «Лабораторний звіт» here as a human
    # classification; the next re-read found no parser for it and deleted
    # the document's 53 values.
    if selected_kind and kind not in DOCUMENT_TYPE_TITLES:
        raise HTTPException(400, t("classify.kind_unknown"))
    if selected_vendor and not vendor_name:
        raise HTTPException(400, t("classify.vendor"))

    known_kind = selected_kind
    with connect(settings) as connection:
        row = connection.execute(
            """SELECT id, patient_id, original_filename, clinical_type, vendor_id, report_date
                     FROM documents WHERE id=? AND owner_user_id=?""",
            (document_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404)
        vendor_id = (
            ensure_vendor(connection, vendor_name, None)
            if selected_vendor
            else row["vendor_id"]
        )
        connection.execute(
            """UPDATE documents
                      SET clinical_type=CASE WHEN ? THEN ? ELSE clinical_type END,
                          vendor_id=CASE WHEN ? THEN ? ELSE vendor_id END,
                          report_date=CASE WHEN ? THEN ? ELSE report_date END,
                          report_date_set_by=CASE WHEN ? THEN 'human' ELSE report_date_set_by END,
                          classified_by=CASE WHEN ? THEN 'human' ELSE classified_by END,
                          classification_confidence=CASE WHEN ? THEN 1.0 ELSE classification_confidence END
                    WHERE id=? AND owner_user_id=?""",
            (
                selected_kind, kind, selected_vendor, vendor_id,
                selected_date, clean_date, selected_date, selected_kind, selected_kind,
                document_id, user["id"],
            ),
        )
        applied = _applied_ai_details(
            (selected_kind, "clinical_type", kind),
            (selected_vendor, "vendor", vendor_name),
            (selected_date, "report_date", clean_date),
        )
        connection.execute(
            """INSERT INTO audit_events(
                       owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at
                   ) VALUES (?, ?, 'ai_document_details_applied', 'document', ?, ?, ?)""",
            (
                user["id"], user["id"], document_id,
                json.dumps(applied, ensure_ascii=False), utc_now(),
            ),
        )
        connection.commit()
    invalidate_catalog(user["id"])
    if known_kind and kind != str(row["clinical_type"] or ""):
        enqueue(
            settings,
            owner_user_id=user["id"],
            patient_id=str(row["patient_id"]),
            batch_id=str(uuid.uuid4()),
            kind="rescan",
            filename=str(row["original_filename"] or document_id),
            document_id=document_id,
        )
    return RedirectResponse(f"/documents/{document_id}#side-panel-ai", status_code=303)

#: Areas fed only by devices (sleep, activity, body, mobility, environment).
_DEVICE_ONLY_AREAS = frozenset(
    str(area["id"]) for area in HEALTH_AREAS
    if area["categories"] and all(str(c).startswith("device_") or c == "body" for c in area["categories"])
)

@router.post("/documents/{document_id}/metadata", responses=_RESPONSES_400_401_403_404)
def edit_document_metadata(
    request: Request,
    document_id: str,
    title: Annotated[str, Form()],
    report_date: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """Edit the two document facts a person most often needs to correct.

    This is deliberately separate from classification: changing a title or
    date must not re-run extraction or make the reader wait for a queue.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    clean_title = collapse_space(title)[:240]
    clean_date = _validated_date(report_date, _DOC_DATE_INVALID_KEY)
    if not clean_title:
        raise HTTPException(400, t("doc.title"))
    with connect(settings) as connection:
        updated = connection.execute(
            """UPDATE documents SET title=?, title_set_by='human', report_date=?,
                       report_date_set_by=CASE WHEN ? IS NOT NULL AND ? IS NOT report_date
                                               THEN 'human' ELSE report_date_set_by END
                    WHERE id=? AND owner_user_id=?""",
            (clean_title, clean_date, clean_date, clean_date, document_id, user["id"]),
        ).rowcount
        if not updated:
            raise HTTPException(404)
        connection.execute(
            """UPDATE search_index
                      SET content=content || ' ' || ?,
                          content_folded=COALESCE(content_folded, '') || ' ' || ?
                    WHERE document_id=? AND owner_user_id=?""",
            (clean_title, search_key(clean_title), document_id, user["id"]),
        )
        connection.execute(
            """INSERT INTO audit_events(
                       owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at
                   ) VALUES (?, ?, 'document_metadata_edited', 'document', ?, ?, ?)""",
            (
                user["id"], user["id"], document_id,
                json.dumps({"title": clean_title, "report_date": clean_date}, ensure_ascii=False),
                utc_now(),
            ),
        )
    invalidate_catalog(user["id"])
    return RedirectResponse(f"/documents/{document_id}#side-panel-details", status_code=303)

#: Longest conclusion and recommendation a person may type.
_FINDING_TEXT_MAX = 6000
#: Id prefix of a conclusion a person wrote where the software read none:
#: the only kind `remove` deletes, and the only kind `revert` leaves alone
#: (there is no machine reading to go back to).
PERSON_FINDING_PREFIX = "person-finding-"
#: Why an added conclusion was refused, as the page names it.
FINDING_ERRORS = ("area", "exists", "date")


class _FindingRefused(ValueError):
    """An `add` refused before anything changed; the value is the FINDING_ERRORS code."""


def _finding_fields(text: str, recommended: str) -> dict[str, str]:
    """The stored columns of a person's wording: its language, and a status
    judged from the words themselves, as for the software's own reading."""
    uk = bool(_CYRILLIC_RE.search(text))
    reasons = finding_attention(text)
    return {
        "summary_uk": text if uk else "", "summary_en": "" if uk else text,
        "recommendations": recommended, "status": "attention" if reasons else "information",
        "attention_reasons": ",".join(reasons), "verification_status": "corrected",
    }


def _add_person_finding(
    connection, user_id: str, document_id: str, text: str, recommended: str, finding_date: str, area: str,
) -> list[str]:
    """Write a conclusion the software did not read (photos whose OCR missed
    the diagnosis line); the ids written.  Filed under the chosen area, else
    under every area the diagnosis names (the rule narrative reports are
    filed by, `_diagnosis_areas`), else under the one the document's title names."""
    document = connection.execute(
        "SELECT patient_id, vendor_id, report_date, title, clinical_type FROM documents WHERE id=? AND owner_user_id=?",
        (document_id, user_id),
    ).fetchone()
    if document is None:
        raise LookupError(document_id)
    if finding_date:
        try:
            finding_date = date.fromisoformat(finding_date).isoformat()
        except ValueError:
            raise _FindingRefused("date") from None
    areas = (area,) if area else (_diagnosis_areas(text) or _diagnosis_areas(str(document["title"] or "")))
    if not areas:
        raise _FindingRefused("area")
    title = DOCUMENT_TYPE_TITLES.get(str(document["clinical_type"] or ""), "Clinical report")
    fields = _finding_fields(text, recommended)
    ids = []
    for health_area in areas:
        finding_id = f"{PERSON_FINDING_PREFIX}{uuid.uuid4()}"
        try:
            connection.execute(
                """INSERT INTO clinical_findings(
                       id, owner_user_id, patient_id, document_id, report_id, page_number, health_area, title,
                       summary_en, summary_uk, recommendations, attention_reasons, original_text, finding_date,
                       vendor_id, status, confidence, verification_status, created_at
                   ) VALUES (?, ?, ?, ?, NULL, 1, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, 1, 'corrected', ?)""",
                (finding_id, user_id, document["patient_id"], document_id, health_area, title,
                 fields["summary_en"], fields["summary_uk"], recommended, fields["attention_reasons"],
                 finding_date or document["report_date"], document["vendor_id"], fields["status"], utc_now()),
            )
        except sqlite3.IntegrityError:
            raise _FindingRefused("exists") from None
        ids.append(finding_id)
    return ids


def _audit_finding(connection, user, action: str, finding_id: str, details: dict[str, object]) -> None:
    if user.get("token_kind"):
        details["token_kind"] = user["token_kind"]
    connection.execute(
        """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id,
               details_json, created_at) VALUES (?, ?, ?, 'clinical_finding', ?, ?, ?)""",
        (user["id"], user["id"], action, finding_id, json.dumps(details, ensure_ascii=False), utc_now()),
    )


@router.post("/documents/{document_id}/findings", responses=_RESPONSES_400_401_403_404)
def correct_document_finding(
    request: Request,
    document_id: str,
    finding_id: Annotated[list[str], Form()] = [],  # noqa: B006 - FastAPI copies the default
    action: Annotated[str, Form()] = "correct",
    summary: Annotated[str, Form()] = "",
    recommendations: Annotated[str, Form()] = "",
    finding_date: Annotated[str, Form()] = "",
    health_area: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
):
    """A person's wording of a conclusion, read off the image of the report.

    `correct` stores `summary` (and `recommendations`) on the named findings
    of this document as `corrected`, which neither a re-read nor
    `sync_clinical_findings` ever rewrites; the status is judged again from
    the person's words.  The text before, who and when go to the audit log,
    and the page offers the text the software read.  `revert` puts back what
    the software read and lets the next rebuild refresh it.
    `add` writes a conclusion where the software read none (`finding_date`,
    default the document's date; `health_area`, default the areas the text
    names); `remove` deletes one a person added, and nothing else.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    text, recommended = (value.replace("\r\n", "\n").strip() for value in (summary, recommendations))
    if action not in {"correct", "revert", "add", "remove"} or action in {"correct", "add"} and not text:
        raise HTTPException(400)
    if len(text) > _FINDING_TEXT_MAX or len(recommended) > _FINDING_TEXT_MAX:
        raise HTTPException(400)
    if health_area and health_area not in AREA_BY_ID:
        raise HTTPException(400)
    destination = _safe_next(next, f"/documents/{document_id}")
    with connect(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if action == "add":
            try:
                ids = _add_person_finding(
                    connection, user["id"], document_id, text, recommended, finding_date.strip(), health_area
                )
            except LookupError:
                connection.rollback()
                raise HTTPException(404) from None
            except _FindingRefused as refused:
                connection.rollback()
                code = str(refused)
                if _wants_json(request):
                    return JSONResponse(
                        {"ok": False, "error": code, "detail": t(f"doc.finding_error_{code}")}, status_code=409
                    )
                return RedirectResponse(f"{destination}?finding_error={code}#side-panel-conclusion", status_code=303)
            for added in ids:
                _audit_finding(connection, user, "finding_added", added, {
                    "document_id": document_id, "source": "image", "after": _finding_fields(text, recommended),
                })
            connection.commit()
            invalidate_catalog(user["id"])
            if _wants_json(request):
                return JSONResponse({"ok": True, "action": action, "finding_ids": ids})
            return RedirectResponse(destination + "#side-panel-conclusion", status_code=303)
        rows = connection.execute(
            f"""SELECT * FROM clinical_findings WHERE owner_user_id=? AND document_id=?
                  AND verification_status<>'rejected' AND id IN ({",".join("?" * len(finding_id))})""",
            (user["id"], document_id, *finding_id),
        ).fetchall() if finding_id else []
        if action == "remove":
            rows = [row for row in rows if str(row["id"]).startswith(PERSON_FINDING_PREFIX)]
        if not rows:
            connection.rollback()
            raise HTTPException(404)
        if action == "correct":
            after = _finding_fields(text, recommended)
            # The date the photo prints, when the reading lost it.
            corrected_date = _validated_date(finding_date, _DOC_DATE_INVALID_KEY) if finding_date else None
        elif action == "revert":
            history = _finding_corrections(connection, user["id"], [str(row["id"]) for row in rows])
        columns = ("summary_uk", "summary_en", "recommendations", "status", "attention_reasons", "verification_status")
        for row in rows:
            before = {name: row[name] for name in columns}
            if action == "remove":
                connection.execute("DELETE FROM clinical_findings WHERE id=?", (row["id"],))
                _audit_finding(connection, user, "finding_removed", str(row["id"]), {
                    "document_id": document_id, "health_area": row["health_area"], "before": before,
                })
                continue
            if action == "revert":
                # A person's own conclusion has no reading to go back to; it is removed instead.
                if row["verification_status"] != "corrected" or str(row["id"]).startswith(PERSON_FINDING_PREFIX):
                    continue
                after = {**before, "verification_status": "extracted",
                         **(history.get(str(row["id"]), {}).get("before") or {})}
            connection.execute(
                f"UPDATE clinical_findings SET {', '.join(f'{name}=?' for name in columns)} WHERE id=?",
                (*(after[name] for name in columns), row["id"]),
            )
            if action == "correct" and corrected_date:
                connection.execute("UPDATE clinical_findings SET finding_date=? WHERE id=?", (corrected_date, row["id"]))
            _audit_finding(
                connection, user, "finding_corrected" if action == "correct" else "finding_correction_reverted",
                str(row["id"]), {"document_id": document_id, "source": "image", "before": before, "after": after,
                                 **({"finding_date": corrected_date} if action == "correct" and corrected_date else {})},
            )
        if action in {"revert", "remove"}:
            sync_clinical_findings(connection)  # an extracted row is refreshed from its page now
        connection.commit()
    invalidate_catalog(user["id"])
    if _wants_json(request):
        return JSONResponse({"ok": True, "action": action, "finding_ids": [str(row["id"]) for row in rows]})
    return RedirectResponse(destination + "#side-panel-conclusion", status_code=303)


@router.post("/documents/{document_id}/tags", responses=_RESPONSES_401_403_404)
def add_document_tag(
    request: Request,
    document_id: str,
    name: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    clean = name.strip()[:40]
    if not clean:
        return RedirectResponse(f"/documents/{document_id}", status_code=303)
    with connect(settings) as connection:
        owned = connection.execute(
            _OWNED_DOCUMENT_SQL, (document_id, user["id"])
        ).fetchone()
        if not owned:
            raise HTTPException(404)
        tag_id = str(uuid.uuid5(uuid.UUID(user["id"]), clean.casefold()))
        connection.execute(
            "INSERT OR IGNORE INTO tags(id, owner_user_id, name) VALUES (?, ?, ?)",
            (tag_id, user["id"], clean),
        )
        connection.execute(
            "INSERT OR IGNORE INTO document_tags(document_id, tag_id) VALUES (?, ?)",
            (document_id, tag_id),
        )
        connection.execute(
            """UPDATE search_index
                      SET content=content || ' ' || ?1,
                          content_folded=COALESCE(content_folded, '') || ' ' || ?4
                    WHERE document_id=?2 AND owner_user_id=?3""",
            (clean, document_id, user["id"], search_key(clean)),
        )
    invalidate_catalog(user["id"])
    return RedirectResponse(f"/documents/{document_id}", status_code=303)

def _document_delete_redirect(destination: str, *, promoted: bool = False,
                              error: str = "") -> RedirectResponse:
    separator = "&" if "?" in destination else "?"
    if error:
        query = f"delete_error={error}"
    else:
        query = "deleted=1" + ("&promoted=1" if promoted else "")
    return RedirectResponse(f"{destination}{separator}{query}", status_code=303)

def _promote_duplicate_copy(connection, owner_user_id: str, document, document_id: str, promoted) -> str:
    """Make `promoted` the primary copy in place of `document`; return its re-read job id."""
    promoted_id = str(promoted["id"])
    # The external Paperless row represents these exact bytes,
    # so preserve that link on the surviving primary document.
    connection.execute(
        """UPDATE documents
                  SET duplicate_of_document_id=NULL,
                      paperless_task_id=COALESCE(paperless_task_id, ?),
                      paperless_id=COALESCE(paperless_id, ?),
                      paperless_attempts=MAX(paperless_attempts, ?)
                WHERE id=?""",
        (
            document["paperless_task_id"], document["paperless_id"],
            int(document["paperless_attempts"] or 0), promoted_id,
        ),
    )
    connection.execute(
        """UPDATE documents SET duplicate_of_document_id=?
                 WHERE owner_user_id=? AND duplicate_of_document_id=? AND id<>?""",
        (promoted_id, owner_user_id, document_id, promoted_id),
    )
    connection.execute(
        "UPDATE upload_jobs SET document_id=? WHERE owner_user_id=? AND document_id=?",
        (promoted_id, owner_user_id, document_id),
    )
    promotion_job_id = str(uuid.uuid4())
    connection.execute(
        """INSERT INTO upload_jobs(
                   id, owner_user_id, patient_id, batch_id, kind, filename,
                   byte_size, state, detail_key, document_id, created_at
               ) VALUES (?, ?, ?, ?, 'rescan', ?, ?, 'queued',
                         'intake.step_waiting', ?, ?)""",
        (
            promotion_job_id,
            owner_user_id,
            promoted["patient_id"],
            str(uuid.uuid4()),
            promoted["original_filename"],
            promoted["byte_size"],
            promoted_id,
            utc_now(),
        ),
    )
    return promotion_job_id

def _reassign_document_dependants(connection, owner_user_id: str, document, document_id: str):
    """Repoint duplicates and queue rows away from a document about to be deleted.

    Returns the promoted duplicate (or None) and its re-read job id (or None).
    """
    parent_id = document["duplicate_of_document_id"]
    children = connection.execute(
        """SELECT * FROM documents
                 WHERE owner_user_id=? AND duplicate_of_document_id=?
                 ORDER BY imported_at, rowid""",
        (owner_user_id, document_id),
    ).fetchall()
    if parent_id:
        # This row was itself a duplicate. Any legacy children are
        # still duplicates of the same surviving primary copy.
        connection.execute(
            """UPDATE documents SET duplicate_of_document_id=?
                     WHERE owner_user_id=? AND duplicate_of_document_id=?""",
            (parent_id, owner_user_id, document_id),
        )
        connection.execute(
            "UPDATE upload_jobs SET document_id=? WHERE owner_user_id=? AND document_id=?",
            (parent_id, owner_user_id, document_id),
        )
        return None, None
    if children:
        promoted = children[0]
        return promoted, _promote_duplicate_copy(connection, owner_user_id, document, document_id, promoted)
    # Queue history may outlive the document, but it must not
    # keep offering a link to an id that no longer exists.
    connection.execute(
        "UPDATE upload_jobs SET document_id=NULL WHERE owner_user_id=? AND document_id=?",
        (owner_user_id, document_id),
    )
    return None, None

def _remove_unused_source(settings, document) -> bool:
    """Unlink a deleted document's source file if it lies inside `sources/`."""
    source = resolve_source_path(settings, str(document["source_path"] or ""))
    try:
        inside_sources = source.resolve().is_relative_to(settings.source_dir.resolve())
    except OSError:
        inside_sources = False
    if not (inside_sources and source.is_file()):
        return False
    try:
        source.unlink()
    except OSError:
        return False
    return True

@router.post("/documents/{document_id}/delete", responses=_RESPONSES_401_403_404)
def delete_document(
    request: Request,
    document_id: str,
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = _DOCUMENTS_URL,
):
    """Delete one owned document and its private source bytes.

    Exact duplicates are separate document rows with separate source
    files. Removing one therefore never removes another one's bytes. If
    the row being removed is the primary copy, the oldest surviving exact
    duplicate becomes primary and is queued for a re-read so it acquires
    its own observations instead of depending on the deleted row.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    destination = _safe_next(next, _DOCUMENTS_URL)

    with connect(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            document = connection.execute(
                """SELECT * FROM documents WHERE id=? AND owner_user_id=?""",
                (document_id, user["id"]),
            ).fetchone()
            if document is None:
                raise HTTPException(404)

            # A running rescan has already opened and analysed these bytes.
            # Let it finish rather than deleting the identity underneath
            # its write transaction. A merely queued rescan can be safely
            # cancelled as part of this deletion.
            running = connection.execute(
                """SELECT 1 FROM upload_jobs WHERE owner_user_id=? AND document_id=?
                         AND kind='rescan' AND state='running' LIMIT 1""",
                (user["id"], document_id),
            ).fetchone()
            if running:
                connection.rollback()
                return _document_delete_redirect(destination, error="busy")
            connection.execute(
                """DELETE FROM upload_jobs WHERE owner_user_id=? AND document_id=?
                         AND kind='rescan' AND state='queued'""",
                (user["id"], document_id),
            )

            promoted, promotion_job_id = _reassign_document_dependants(
                connection, user["id"], document, document_id
            )

            connection.execute(
                """DELETE FROM review_tasks
                         WHERE owner_user_id=? AND entity_type='document' AND entity_id=?""",
                (user["id"], document_id),
            )
            source_still_used = connection.execute(
                """SELECT 1 WHERE
                           EXISTS(SELECT 1 FROM documents WHERE id<>?2 AND source_path=?1)
                        OR EXISTS(SELECT 1 FROM device_imports WHERE source_path=?1)
                        OR EXISTS(SELECT 1 FROM device_events WHERE source_file=?1)
                        OR EXISTS(SELECT 1 FROM device_workouts WHERE route_file=?1)""",
                (document["source_path"], document_id),
            ).fetchone()
            connection.execute("DELETE FROM documents WHERE id=?", (document_id,))
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    file_removed = False if source_still_used else _remove_unused_source(settings, document)

    _audit(settings,
        user["id"], user["id"], "document_deleted", "document", document_id,
        {
            "filename": str(document["original_filename"]),
            "sha256": str(document["sha256"]),
            "file_removed": file_removed,
            "promoted_document_id": str(promoted["id"]) if promoted else None,
        },
    )
    if promotion_job_id:
        start_worker(settings)
    invalidate_catalog(user["id"])
    return _document_delete_redirect(destination, promoted=promoted is not None)

# --- upload -------------------------------------------------------------

def _recent_uploads(connection, owner_user_id: str) -> list[dict[str, object]]:
    """The last few files, each with how far its extraction has got."""
    items = []
    for row in connection.execute(
        """SELECT d.id, d.title, d.clinical_type, d.original_filename, d.report_date,
                      d.imported_at, d.duplicate_of_document_id, v.canonical_name vendor,
                      COUNT(o.id) total,
                      COALESCE(SUM(o.verification_status='extracted'), 0) unverified
               FROM documents d LEFT JOIN vendors v ON v.id=d.vendor_id
               LEFT JOIN observations o ON o.document_id=d.id AND o.verification_status <> 'rejected'
               WHERE d.owner_user_id=? GROUP BY d.id
               ORDER BY d.imported_at DESC LIMIT ?""",
        (owner_user_id, UPLOAD_RECENT),
    ):
        item = _document_row(row)
        total, unverified = int(row["total"]), int(row["unverified"] or 0)
        if row["duplicate_of_document_id"]:
            status = t("upload.status_duplicate")
        elif not total:
            status = t("upload.status_none")
        elif unverified:
            status = t(
                "upload.status_unverified",
                unverified=format_count(unverified),
                total=format_count(total),
            )
        else:
            status = t("upload.status_checked", total=format_count(total))
        item["status_text"] = status
        # An upload list is ordered by when it arrived, so it says so; the
        # report date belongs to the document, not to this queue.
        item["date_text"] = format_date(str(row["imported_at"] or "") or None)
        items.append(item)
    return items

#: How a finished job is worded, and whether it produced something to open.
_QUEUE_STATES = {
    "queued": "neutral",
    "running": "busy",
    "done": "ok",
    "skipped": "neutral",
    "failed": "bad",
}
_QUEUE_NOT_FAILURES = frozenset({"intake.failed_device_archive_member"})
_recent_uploads_template = templates.env.from_string(
    '{% from "_document_cards.html" import upload_recent_list with context %}{{ upload_recent_list(recent) }}'
)

def _queue_state(request: Request, owner_user_id: str) -> dict[str, object]:
    """The processing area, as the page renders it and the poll returns it."""
    settings = request.app.state.settings
    with connect(settings) as connection:
        progress = batch_progress(connection, owner_user_id, UPLOAD_QUEUE_LIMIT)
        recent = _recent_uploads(connection, owner_user_id)
    jobs = [_queue_row(job) for job in progress["jobs"]]
    failed = sum(1 for job in jobs if job["failed"])
    return {
        "jobs": jobs,
        "recent": recent,
        "active": progress["active"],
        "done": progress["done"],
        "failed": failed,
        "set_aside": sum(1 for job in jobs if job["state"] == "failed" and not job["failed"]),
        "total": progress["total"],
        "failed_text": t_plural("upload.failed_alert", failed) if failed else "",
    }

def _queue_job_url(job) -> str:
    """Where a finished upload is opened: its document, else the device import."""
    if job["document_id"]:
        return f"/documents/{job['document_id']}"
    return _DEVICES_URL if job["import_id"] else ""

#: The tally a finished job reports, keyed by how it finished.
_QUEUE_DONE_COUNTS = {
    "intake.done_imported": "intake.count_values",
    "intake.done_expanded": "intake.count_files",
    "intake.done_device": "intake.count_days",
    "intake.done_rescanned": "intake.count_new_values",
}

def _queue_summary(state: str, detail: str, count: int) -> str:
    # A job that produced nothing countable says nothing rather than
    # "0 values": a zero here is the absence of a tally, not a measurement.
    key = _QUEUE_DONE_COUNTS.get(detail) if state == "done" else None
    return t_plural(key, count) if count and key else ""

def _queue_row(job) -> dict[str, object]:
    """One queue row as the page and the polling endpoint both render it.

    Both surfaces read this so a row cannot say one thing on load and
    another thing a second later when the first poll lands.
    """
    state = str(job["state"])
    kind = str(job["kind"])
    detail = str(job["detail_key"] or "intake.step_waiting")
    count = int(job["observation_count"] or 0)
    summary = _queue_summary(state, detail, count)
    # A file inside a device export that is not a medical document (Garmin
    # ships avatar PNGs) is left out by design.  Counted as a failure, nine
    # of these read as nine broken uploads.
    set_aside = state == "failed" and detail in _QUEUE_NOT_FAILURES
    return {
        "id": str(job["id"]),
        "kind": kind,
        "kind_text": t(f"intake.kind_{kind}"),
        "filename": str(job["filename"]),
        "state": state,
        "failed": state == "failed" and not set_aside,
        # Nothing left to do or to look at: these fold after the newest few.
        "finished": state in ("done", "skipped") or set_aside,
        "tone": "neutral" if set_aside else _QUEUE_STATES.get(state, "neutral"),
        "state_text": t("intake.state_not_imported") if set_aside else t(f"intake.state_{state}"),
        "detail_text": t(detail),
        "summary_text": summary,
        "size_text": _byte_size_text(job["byte_size"]),
        "url": _queue_job_url(job),
        "title": str(job["document_title"] or "") if "document_title" in job.keys() else "",
    }

@router.get(_UPLOAD_URL, response_class=HTMLResponse, responses=_RESPONSES_401)
def upload_page(
    request: Request,
    upload_error: str | None = None,
    duplicate: str | None = None,
    batch: str | None = None,
    deleted: str = "",
    promoted: str = "",
    delete_error: str = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    # A page that never finished its batch is a page whose worker died with
    # the process. Restarting it here means reopening the tab resumes the
    # queue rather than stranding it.
    start_worker(settings)
    queue = _queue_state(request, user["id"])
    with connect(settings) as connection:
        held = (
            connection.execute(
                """SELECT id, title, clinical_type, original_filename FROM documents
                       WHERE id=? AND owner_user_id=?""",
                (duplicate, user["id"]),
            ).fetchone()
            if duplicate
            else None
        )
    return templates.TemplateResponse(
        request,
        "upload.html",
        template_context(
            request,
            recent=queue["recent"],
            queue=queue["jobs"],
            queue_active=queue["active"],
            queue_done=queue["done"],
            queue_failed=queue["failed"],
            queue_failed_text=queue["failed_text"],
            queue_total=queue["total"],
            adapters=[
                {"key": key, "label": t(f"intake.adapter_{key}")} for key in DEVICE_ADAPTERS
            ],
            error_text=t(upload_error) if upload_error in UPLOAD_ERRORS else None,
            duplicate_url=f"/documents/{held['id']}" if held else None,
            document_deleted=deleted == "1",
            document_promoted=promoted == "1",
            document_delete_busy=delete_error == "busy",
            formats_text=", ".join(sorted(INTAKE_SUFFIXES)),
            archive_limit=t("upload.gigabytes", count=MAX_ARCHIVE_UPLOAD_BYTES // 1024**3),
            chunk_size=UPLOAD_CHUNK_BYTES,
            chunk_threshold=UPLOAD_CHUNK_THRESHOLD,
            active="upload",
        ),
    )

def _unnamed_upload_detail(filename: str) -> str:
    """Why a file whose name the door rule refused was rejected.

    A supported format under an unusable name is a different problem from
    an unsupported format, and saying which is the difference between
    "rename it" and "convert it".
    """
    supported = PurePath(filename).suffix.casefold() in INTAKE_SUFFIXES
    return _INTAKE_FAILED_UNREADABLE if supported else _INTAKE_FAILED_UNSUPPORTED

async def _write_upload(upload: UploadFile, target: Path, limit: int) -> tuple[int, bool]:
    """Stream one upload to `target`; the bytes written and whether it overran `limit`."""
    written = 0
    oversized = False
    try:
        async with await anyio.open_file(target, "wb") as handle:
            while chunk := await upload.read(1 << 20):
                written += len(chunk)
                if written > limit:
                    oversized = True
                    break
                await handle.write(chunk)
    finally:
        await upload.close()
    return written, oversized

async def _receive_upload(settings, common: dict[str, object], kind: str, upload: UploadFile) -> None:
    """Put one file of a submission on disk and in the queue, or queue its rejection."""
    name = _sanitised_upload_name(upload.filename)
    if not name:
        record_rejected(
            settings,
            **common,
            filename=PurePath(upload.filename.replace("\\", "/")).name[:120] or "?",
            detail_key=_unnamed_upload_detail(upload.filename),
        )
        await upload.close()
        return

    limit = upload_limit_for(name)
    target = _upload_target(settings, name)
    written, oversized = await _write_upload(upload, target, limit)
    if oversized or not written:
        target.unlink(missing_ok=True)
        record_rejected(
            settings,
            **common,
            filename=name,
            byte_size=written or None,
            detail_key="intake.failed_too_big" if oversized else "intake.failed_missing",
        )
        return

    await _admit_upload(settings, common, kind, name, target, written)

@router.post(_UPLOAD_URL, responses=_RESPONSES_400_401)
async def upload_document(
    request: Request,
    files: Annotated[list[UploadFile], File()] = [],
    file: Annotated[UploadFile | None, File()] = None,
    kind: Annotated[str, Form()] = "auto",
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = _UPLOAD_URL,
):
    """Take everything the reader selected and put it in the queue.

    Nothing is parsed while the browser waits.  A submission can be forty
    scans or a two-gigabyte vendor export, so the request's whole job is to
    get bytes onto disk safely and hand each one to the intake worker; the
    processing area is where the reader watches it happen.

    One unusable file does not sink the submission.  It is written into the
    queue as a rejected row, next to the ones that worked, because "3 of 40
    were rejected" without saying which three is not something a person can
    act on.
    """
    settings = request.app.state.settings
    user = require_user(request)
    destination = _safe_next(next, _UPLOAD_URL)

    def failed(key: str) -> RedirectResponse:
        joiner = "&" if "?" in destination else "?"
        return RedirectResponse(f"{destination}{joiner}upload_error={key}", status_code=303)

    if not csrf_ok(user, csrf_token):
        return failed(_UPLOAD_ERROR_CSRF)
    arrivals = [item for item in ([*files, file] if file else list(files)) if item is not None]
    arrivals = [item for item in arrivals if item.filename]
    if not arrivals:
        return failed("upload.error_missing")
    if kind != "auto" and kind not in DEVICE_ADAPTERS:
        raise HTTPException(400)

    with connect(settings) as connection:
        patient = _patient_row(connection, user["id"])
    if patient is None:
        return failed(_UPLOAD_ERROR_NO_SOURCE)

    batch_id = str(uuid.uuid4())
    common = {
        "owner_user_id": user["id"],
        "patient_id": patient["id"],
        "batch_id": batch_id,
    }

    for upload in arrivals:
        await _receive_upload(settings, common, kind, upload)

    return RedirectResponse(f"{destination}{'&' if '?' in destination else '?'}batch={batch_id}", status_code=303)

def _upload_partial_path(settings, owner_user_id: str, session: str) -> Path:
    """Where one chunked submission is assembled, after sweeping abandoned ones."""
    partial_dir = settings.source_dir / "uploads" / ".partial"
    partial_dir.mkdir(parents=True, exist_ok=True)
    # A browser that navigated away mid-file leaves its partial behind,
    # and nothing ever resumes one: the page always restarts a file from
    # zero.  A suffix-less name keeps the extraction validator's eyes off
    # what is, by construction, not yet an arrival.
    cutoff = time.time() - 86_400
    for stale in partial_dir.iterdir():
        with suppress(OSError):
            if stale.stat().st_mtime < cutoff:
                stale.unlink()
    return partial_dir / f"{owner_user_id}-{session}"

def _partial_size(partial: Path, offset: int) -> int:
    """Bytes already assembled; a slice at offset 0 starts the file over."""
    have = partial.stat().st_size if partial.exists() else 0
    if offset == 0 and have:
        partial.unlink()
        have = 0
    return have

async def _append_chunk(chunk: UploadFile, partial: Path, have: int, limit: int) -> tuple[int, bool]:
    """Append one slice to the partial; the new size and whether it overran `limit`."""
    written = have
    oversized = False
    try:
        async with await anyio.open_file(partial, "ab") as handle:
            while piece := await chunk.read(1 << 20):
                written += len(piece)
                if written > limit:
                    oversized = True
                    break
                await handle.write(piece)
    finally:
        await chunk.close()
    return written, oversized

async def _finish_chunked_upload(
    settings, common: dict[str, object], kind: str, filename: str,
    display: str, partial: Path, written: int,
) -> JSONResponse:
    """Hand the assembled file to the ordinary intake path, or queue its rejection."""
    name = _sanitised_upload_name(filename)
    if not name or not written:
        # `name` was vetted on the first slice, but nothing obliges a
        # client to send the same filename twice, so the door rule holds
        # here too.
        partial.unlink(missing_ok=True)
        detail_key = _unnamed_upload_detail(filename) if written else "intake.failed_missing"
        record_rejected(
            settings, **common, filename=display, byte_size=written or None,
            detail_key=detail_key,
        )
        return JSONResponse({"status": "rejected"})

    target = _upload_target(settings, name)
    partial.replace(target)
    await _admit_upload(settings, common, kind, name, target, written)
    return JSONResponse({"status": "done"})

@router.post("/upload/chunk", responses=_RESPONSES_400_401)
async def upload_chunk(
    request: Request,
    chunk: Annotated[UploadFile, File()],
    session: Annotated[str, Form()],
    offset: Annotated[int, Form()],
    filename: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
    kind: Annotated[str, Form()] = "auto",
    final: Annotated[str, Form()] = "0",
):
    """One slice of a submission too large for the proxy in front of the site.

    Cloudflare answers any single request body over about 100 MB with its
    own 413 that this process never sees, so the upload page sends a large
    submission in slices.  The only state between slices is the partial
    file itself: a slice is accepted when `offset` equals its current
    size, and on `final` the assembled file enters the ordinary intake
    path — same name rules, same dedupe, same queue as a one-request
    upload.  `session` groups the slices and becomes the batch id the
    page then watches.
    """
    settings = request.app.state.settings
    user = require_user(request)
    if not csrf_ok(user, csrf_token):
        return JSONResponse({"error": _UPLOAD_ERROR_CSRF}, status_code=403)
    try:
        uuid.UUID(session)
    except ValueError:
        raise HTTPException(400)
    if kind != "auto" and kind not in DEVICE_ADAPTERS:
        raise HTTPException(400)
    with connect(settings) as connection:
        patient = _patient_row(connection, user["id"])
    if patient is None:
        return JSONResponse({"error": _UPLOAD_ERROR_NO_SOURCE}, status_code=409)
    common = {
        "owner_user_id": user["id"],
        "patient_id": patient["id"],
        "batch_id": session,
    }

    partial = _upload_partial_path(settings, str(user["id"]), session)

    display = PurePath(filename.replace("\\", "/")).name[:120] or "?"
    have = _partial_size(partial, offset)
    if offset != have:
        # Out of order, repeated, or resuming a partial the sweep took.
        # The size that actually landed answers, so the page can tell.
        await chunk.close()
        return JSONResponse({"size": have}, status_code=409)
    if offset == 0 and _sanitised_upload_name(filename) is None:
        # The same door rule the form path applies, checked before the
        # first byte lands rather than after the last slice of a file
        # that was never going to be accepted.
        await chunk.close()
        record_rejected(
            settings, **common, filename=display,
            detail_key=_unnamed_upload_detail(filename),
        )
        return JSONResponse({"status": "rejected"})

    written, oversized = await _append_chunk(chunk, partial, have, upload_limit_for(filename))
    if oversized:
        partial.unlink(missing_ok=True)
        record_rejected(
            settings, **common, filename=display, byte_size=written,
            detail_key="intake.failed_too_big",
        )
        return JSONResponse({"status": "rejected"})
    if final != "1":
        return JSONResponse({"status": "ok", "size": written})
    return await _finish_chunked_upload(settings, common, kind, filename, display, partial, written)

@router.get("/api/uploads/queue", responses=_RESPONSES_401)
def upload_queue(request: Request):
    """What the processing area polls: the queue, already localised."""
    user = require_user(request)
    queue = _queue_state(request, user["id"])
    recent = queue.pop("recent")
    # The finished list comes with the last poll, rendered by the macro the
    # page uses, so finishing a batch no longer reloads the whole page.
    queue["recent_html"] = _recent_uploads_template.render(
        template_context(request, recent=recent)
    )
    return JSONResponse(queue)

@router.post("/uploads/clear", responses=_RESPONSES_401_403)
def clear_queue(request: Request, csrf_token: Annotated[str, Form()] = ""):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    clear_finished(settings, user["id"])
    return RedirectResponse(_UPLOAD_URL, status_code=303)

@router.post("/documents/{document_id}/classification", responses=_RESPONSES_400_401_403_404)
def reclassify_document(
    request: Request,
    document_id: str,
    clinical_type: Annotated[str, Form()] = "",
    clinical_type_custom: Annotated[str, Form()] = "",
    vendor: Annotated[str, Form()] = "",
    vendor_custom: Annotated[str, Form()] = "",
    report_date: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
):
    """Say what a document actually is, when the classifier got it wrong.

    Everything the parser does follows from the kind of report: it returns
    nothing at all for anything outside laboratory, allergy and
    microbiology.  So a lab report the classifier could not place produced
    no values, and re-reading it ran the same classifier to the same
    conclusion -- the results sat in the stored page text, unreachable, for
    good.  A person naming the kind ends that, and the file is re-read at
    once so the answer takes effect rather than waiting to be asked for
    twice.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    kind = collapse_space(
        clinical_type_custom if clinical_type.strip() == "__custom__" else clinical_type
    )[:100]
    if not kind or kind.startswith("__") or any(ord(character) < 32 for character in kind):
        raise HTTPException(400, t("classify.kind"))
    known_kind = kind in DOCUMENT_TYPE_TITLES
    clean_date = _validated_date(report_date, _DOC_DATE_INVALID_KEY)
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT id, patient_id, original_filename, vendor_id FROM documents WHERE id=? AND owner_user_id=?",
            (document_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404)
        vendor_choice = vendor.strip()
        if vendor_choice == "__custom__":
            vendor_name = collapse_space(vendor_custom)[:200]
            if not vendor_name:
                raise HTTPException(400, t("classify.vendor"))
        elif vendor_choice == "__clear__":
            vendor_name = _UNKNOWN_VENDOR
        else:
            vendor_name = collapse_space(vendor_choice)[:200]
        vendor_id = ensure_vendor(connection, vendor_name, None) if vendor_name else row["vendor_id"]
        connection.execute(
            """UPDATE documents SET clinical_type=?, vendor_id=?,
                       report_date=COALESCE(?, report_date), classified_by='human',
                       report_date_set_by=CASE WHEN ? IS NOT NULL THEN 'human' ELSE report_date_set_by END,
                       classification_confidence=1.0
                   WHERE id=? AND owner_user_id=?""",
            (kind, vendor_id, clean_date, clean_date, document_id, user["id"]),
        )
        connection.execute(
            """INSERT INTO audit_events(
                       owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at
                   ) VALUES (?, ?, 'document_reclassified', 'document', ?, ?, ?)""",
            (
                user["id"], user["id"], document_id,
                json.dumps(
                    {"clinical_type": kind, "vendor": vendor_name, "report_date": clean_date},
                    ensure_ascii=False,
                ),
                utc_now(),
            ),
        )
        connection.commit()
    invalidate_catalog(user["id"])
    # Known kinds select a parser and need a re-read. A custom filing label
    # is useful organization, but has no parser contract and must not erase
    # extracted rows by attempting one.
    if known_kind:
        enqueue(
            settings,
            owner_user_id=user["id"],
            patient_id=str(row["patient_id"]),
            batch_id=str(uuid.uuid4()),
            kind="rescan",
            filename=str(row["original_filename"] or document_id),
            document_id=document_id,
        )
    destination = _safe_next(next, f"/documents/{document_id}")
    return RedirectResponse(
        destination + (_RESCAN_QUEUED_QUERY if known_kind else "#side-panel-details"), status_code=303
    )

def _stale_document_ids(connection, owner_user_id: str) -> list[str]:
    """Documents whose stored values came from an earlier parser.

    The record keeps `observations.parser_version`, so a file that was read
    before the parser learned a unit or a layout can be named rather than
    guessed at.  A file that produced no values at all is deliberately not
    here: nothing was stamped, so there is no evidence it is behind, and
    listing every narrative ultrasound forever would make the count noise.
    Its own page still offers the re-read.

    Only rows a re-read would actually replace count, which is exactly the
    set `reingest_document` deletes: `extracted`.  A value somebody typed in
    carries `parser_version='human'` and one somebody verified keeps
    whichever version read it, because both outrank the parser and are
    preserved untouched -- so counting them marked the document as behind
    for good, and the button offering to fix it could never move the number
    however often it was pressed.

    Also listed: documents the current classifier reads differently from
    what is stored -- title, kind, date, order number, collection and issue
    moments, each only where a person did not set it.  That is the only way
    a document with no values (a consultation photo dated by its upload
    day) is ever offered the re-read that fixes it, and a re-read stores
    exactly that classification, so the document leaves the list after it.
    """
    from ..ingest.pipeline import classification_drift_ids

    by_parser = {
        str(row["id"])
        for row in connection.execute(
            """SELECT DISTINCT d.id FROM documents d
                   JOIN observations o ON o.document_id=d.id
                   WHERE d.owner_user_id=? AND o.verification_status='extracted'
                     AND d.extraction_strategy <> 'lab_api'
                     AND COALESCE(o.parser_version,'') <> ?""",
            (owner_user_id, PARSER_VERSION),
        )
    }
    return sorted(by_parser | set(classification_drift_ids(connection, owner_user_id)))

@router.post("/documents/rescan-stale", responses=_RESPONSES_401_403)
def rescan_stale_documents(
    request: Request,
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
):
    """Re-read every file the parser has moved past, in one action.

    The per-document button answers "this file looks wrong"; this answers
    the question that actually arises, which is "the software improved, so
    which of my files are still on the old reading?".  Answering it one
    file at a time over 85 documents is not an answer.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    with connect(settings) as connection:
        patient = _patient_row(connection, user["id"])
        stale = _stale_document_ids(connection, user["id"])
        filenames = {
            str(row["id"]): str(row["original_filename"] or row["id"])
            for row in connection.execute(
                "SELECT id, original_filename FROM documents WHERE owner_user_id=?",
                (user["id"],),
            )
        }
    if patient is None or not stale:
        return RedirectResponse(_safe_next(next, _DOCUMENTS_URL) + "?rescan=none", status_code=303)
    batch_id = str(uuid.uuid4())
    for document_id in stale:
        enqueue(
            settings,
            owner_user_id=user["id"],
            patient_id=str(patient["id"]),
            batch_id=batch_id,
            kind="rescan",
            filename=filenames.get(document_id, document_id),
            document_id=document_id,
            # One worker start for the batch, not one per file.
            start=document_id == stale[-1],
        )
    return RedirectResponse(
        _safe_next(next, _DOCUMENTS_URL) + f"?rescan=queued&count={len(stale)}", status_code=303
    )

@router.post("/documents/{document_id}/rescan", responses=_RESPONSES_401_403_404)
def rescan_document(
    request: Request,
    document_id: str,
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
):
    """Re-read a stored file with today's extractor, classifier and parser.

    The reason this exists: the software keeps learning.  A document read
    by last month's parser is not re-read by this month's unless somebody
    asks, and re-uploading the same file only produces a duplicate.  What a
    person already verified or corrected survives the re-read; see
    `reingest_document`.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT id, original_filename, patient_id FROM documents WHERE id=? AND owner_user_id=?",
            (document_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404)
    enqueue(
        settings,
        owner_user_id=user["id"],
        patient_id=str(row["patient_id"]),
        batch_id=str(uuid.uuid4()),
        kind="rescan",
        filename=str(row["original_filename"] or document_id),
        document_id=document_id,
    )
    return RedirectResponse(
        _safe_next(next, f"/documents/{document_id}") + _RESCAN_QUEUED_QUERY, status_code=303
    )

def _apply_duplicate_action(
    connection, owner_user_id: str, document_id: str, action: str,
    primary_id: str, other_id: str, token_kind,
) -> dict[str, object]:
    """Run one duplicate answer inside the caller's transaction; the details it reports."""
    if action == "mark":
        return mark_document_duplicate(
            connection, owner_user_id, document_id, primary_id, owner_user_id, token_kind
        )
    if action == "unmark":
        return {"primary_document_id": unmark_document_duplicate(
            connection, owner_user_id, document_id, owner_user_id, token_kind
        )}
    if action == "part":
        return _link_document_part(connection, owner_user_id, document_id, primary_id, token_kind)
    # "Not part of this report" undoes a person's link as well as a suggestion.
    connection.execute(
        """DELETE FROM document_relations WHERE relationship='part_of' AND notes=?
              AND ((source_document_id=? AND target_document_id=?) OR (source_document_id=? AND target_document_id=?))""",
        (PERSON_PART_NOTE, document_id, other_id, other_id, document_id),
    )
    keep_both_documents(connection, owner_user_id, document_id, other_id, owner_user_id, token_kind)
    return {}


#: A person's "this file is a page or part of that report".  Detection's
#: `auto:parts` rows only suggest; this one is never replaced by a re-read or
#: the start-up repair (both touch `auto:` rows only).
PERSON_PART_NOTE = "person:part_of"


def _person_part_target(connection, document_id: str) -> str | None:
    row = connection.execute(
        "SELECT target_document_id FROM document_relations WHERE relationship='part_of' AND notes=? AND source_document_id=?",
        (PERSON_PART_NOTE, document_id),
    ).fetchone()
    return str(row[0]) if row else None


def _person_part_ids(connection, owner_user_id: str, report_id: str) -> list[str]:
    """The files a person linked as parts of this report, in upload order."""
    return [str(row[0]) for row in connection.execute(
        """SELECT d.id FROM document_relations r JOIN documents d ON d.id=r.source_document_id
            WHERE r.relationship='part_of' AND r.notes=? AND r.target_document_id=? AND d.owner_user_id=?
            ORDER BY d.imported_at, d.original_filename""",
        (PERSON_PART_NOTE, report_id, owner_user_id),
    )]


def _link_document_part(connection, owner_user_id: str, part_id: str, report_id: str, token_kind) -> dict[str, object]:
    """Record that `part_id` is a page or part of `report_id`; the caller commits.

    Each file keeps its own pages and values; the report's page shows the
    part's pages, and checking the report checks the part.  Refused like
    marking a copy: another patient, the file itself, a marked copy, a file
    being re-read.  Naming a copy means its original, and naming a part means
    the report it belongs to, so parts are one level deep.
    """
    report_id = _duplicate_pair(connection, owner_user_id, part_id, report_id)
    report_id = _person_part_target(connection, report_id) or report_id
    if report_id == part_id:
        raise DuplicateRefused("dup.error_self")
    # A file re-linked moves; parts of its own follow it to the report.
    connection.execute(
        "DELETE FROM document_relations WHERE relationship='part_of' AND notes=? AND source_document_id=?",
        (PERSON_PART_NOTE, part_id),
    )
    connection.execute(
        """UPDATE OR REPLACE document_relations SET target_document_id=?
            WHERE relationship='part_of' AND notes=? AND target_document_id=?""",
        (report_id, PERSON_PART_NOTE, part_id),
    )
    # Every automatic suggestion about the pair is the same question, now
    # answered; and a part is not a copy, so no "same report" offer returns.
    connection.execute(
        """DELETE FROM document_relations WHERE notes LIKE 'auto:%'
              AND ((source_document_id=? AND target_document_id=?) OR (source_document_id=? AND target_document_id=?))""",
        (part_id, report_id, report_id, part_id),
    )
    _record_person_relation(connection, part_id, report_id, NOT_DUPLICATE_NOTE)
    connection.execute(
        """INSERT INTO document_relations(source_document_id, target_document_id, relationship, confidence, notes)
           VALUES (?, ?, 'part_of', 1.0, ?)""",
        (part_id, report_id, PERSON_PART_NOTE),
    )
    details: dict[str, object] = {"report_document_id": report_id}
    if token_kind:
        details["token_kind"] = token_kind
    _audit_document(connection, owner_user_id, owner_user_id, "document_linked_part", part_id, details)
    return details

def _queue_unmarked_rescan(settings, owner_user_id: str, document_id: str) -> None:
    """Queue the re-read that brings an unmarked duplicate's own values back."""
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT original_filename, patient_id FROM documents WHERE id=?", (document_id,)
        ).fetchone()
    enqueue(
        settings,
        owner_user_id=owner_user_id,
        patient_id=str(row["patient_id"]),
        batch_id=str(uuid.uuid4()),
        kind="rescan",
        filename=str(row["original_filename"] or document_id),
        document_id=document_id,
    )

@router.post("/documents/{document_id}/duplicate", responses=_RESPONSES_400_401_403_404)
def document_duplicate(
    request: Request,
    document_id: str,
    action: Annotated[str, Form()],
    primary_id: Annotated[str, Form()] = "",
    other_id: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
):
    """Say whether this file is a copy of a report already in the record.

    `mark` makes it a duplicate of `primary_id`: its values are counted
    once, from that document, exactly as for a byte-identical upload.
    `unmark` makes it a document of its own again and queues its re-read,
    which brings its values back through the normal pipeline.
    `keep_both` answers a same-report suggestion with "different reports",
    and undoes a `part` link between the two.
    `part` records this file as a page or part of the report `primary_id`.
    Each is audited with the credential kind that made it.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    if action not in {"mark", "unmark", "keep_both", "part"}:
        raise HTTPException(400)
    if action in {"mark", "part"} and not primary_id or action == "keep_both" and not other_id:
        raise HTTPException(400)
    destination = _safe_next(next, f"/documents/{document_id}")
    token_kind = user.get("token_kind")
    with connect(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            details = _apply_duplicate_action(
                connection, user["id"], document_id, action, primary_id, other_id, token_kind
            )
            connection.commit()
        except LookupError:
            connection.rollback()
            raise HTTPException(404) from None
        except DuplicateRefused as refused:
            connection.rollback()
            code = refused.key.removeprefix("dup.error_")
            if _wants_json(request):
                return JSONResponse(
                    {"ok": False, "error": code, "detail": t(refused.key), **refused.details},
                    status_code=409,
                )
            return RedirectResponse(f"{destination}?dup_error={code}#duplicates", status_code=303)
    if action == "unmark":
        _queue_unmarked_rescan(settings, user["id"], document_id)
    invalidate_catalog(user["id"])
    if _wants_json(request):
        return JSONResponse({"ok": True, "action": action, **details})
    suffix = _RESCAN_QUEUED_QUERY if action == "unmark" else ""
    return RedirectResponse(f"{destination}{suffix}#duplicates", status_code=303)

# --- corrections --------------------------------------------------------

def _remap_concept(
    connection,
    canonical_name: str,
    raw_name: str,
    vendor_id: str | None,
    value_type: str,
    unit_raw: str | None,
) -> tuple[str, str | None]:
    """The concept a corrected observation belongs to.

    A reviewer who names an existing metric is making an explicit mapping
    decision and it is honoured exactly for that observation - guessing
    from the printed label is what put the value in the wrong place to
    begin with.  An empty or unknown name falls back to the parser's own
    resolution.

    The printed label is also offered to the alias table so a label the
    parser has never seen is learned, but only where nothing is claiming
    it yet: `concept_aliases` carries no owner column and vendors are
    shared between accounts, so overwriting an existing row would let one
    person's correction silently refile another person's next import.  The
    correction always lands on this observation either way; what it does
    not do is rewrite a rule someone else depends on.
    """
    concept = _picked_concept(_concept_picker(connection), canonical_name[:300])
    if concept is None:
        return ensure_concept(
            connection,
            raw_name,
            vendor_id,
            value_type=value_type,
            unit_raw=unit_raw,
            clinical_type="laboratory",
        )
    connection.execute(
        """INSERT OR IGNORE INTO concept_aliases(concept_id, vendor_id, alias, normalized_alias)
               VALUES (?, ?, ?, ?)""",
        (concept["id"], vendor_id, collapse_space(raw_name), normalized_key(raw_name)),
    )
    return str(concept["id"]), concept["preferred_unit"]

_proposals_template = templates.env.from_string('{% include "_reread_proposals.html" %}')
_rows_template = templates.env.from_string(
    """{% from "_components.html" import observation_row with context %}
{%- set lab_classes = lab_observation_classes(user, document_id) if (lab_observation_classes is defined and not viewing and not guest) else {} -%}
{%- for item in items %}{{ observation_row(item, none if viewing else csrf_token, return_url, 'an-concept-list', '', lab_classes.get(item.id, '')) }}{% endfor %}"""
)

def _wants_json(request: Request) -> bool:
    return _JSON_MEDIA_TYPE in request.headers.get("accept", "")

def _observation_rows_html(request: Request, owner_user_id: str, document_id: str, ids: list[str]) -> str:
    """Rows of the document page rendered alone, by the macro the page uses."""
    settings = request.app.state.settings
    with connect(settings) as connection:
        items = _document_observations(connection, owner_user_id, document_id, ids)
    return _rows_template.render(
        template_context(
            request, items=items, document_id=document_id, return_url=f"/documents/{document_id}"
        )
    )

def _row_swap(request: Request, owner_user_id: str, document_id: str, observation_id: str) -> JSONResponse:
    """What a checked or corrected value needs to update in place.

    Pressing "Verify" on one of 57 values used to reload the whole page and
    land the reader back at the top of it; the row and the review line are
    all that changed.
    """
    settings = request.app.state.settings
    with connect(settings) as connection:
        task = _document_review_task(connection, owner_user_id, document_id)
    return JSONResponse(
        {
            "ok": True,
            "row": _observation_rows_html(request, owner_user_id, document_id, [observation_id]),
            "review_line": task["line_text"] if task else "",
        }
    )

@router.get("/documents/{document_id}/rows", response_class=HTMLResponse, responses=_RESPONSES_401_404)
def document_rows(request: Request, document_id: str, ids: str = ""):
    """Observation rows of one document, for a collapsed group opened on demand."""
    settings = request.app.state.settings
    user = record_user(request, require_user(request))
    wanted = [item for item in ids.split(",") if item][:400]
    with connect(settings) as connection:
        owned = connection.execute(
            _OWNED_DOCUMENT_SQL, (document_id, user["id"])
        ).fetchone()
    if not owned:
        raise HTTPException(404)
    if not wanted:
        return HTMLResponse("")
    return HTMLResponse(_observation_rows_html(request, user["id"], document_id, wanted))

def _typed_observation_value(
    raw_name: str, value_numeric: str, value_text: str,
    vendor_reference_text: str, observed_at: str, evidence_text: str,
) -> tuple:
    """A typed-in value, validated and cleaned as an observation row stores it.

    Returns (name, numeric, text, value_type, comparator, reference, low,
    high, observed, evidence); `text` is None for a numeric value.
    """
    clean_name = raw_name.strip()[:300]
    clean_text = value_text.strip()[:500]
    # `<0.01` is the reading, not a typo to be tidied away.  The field is
    # pre-filled with the sign, so a correction aimed at some other part of
    # the row carries it back unchanged, and deleting the character is how a
    # reviewer says the parser invented it.
    comparator, typed_number = split_comparator(value_numeric)
    numeric = parse_decimal(typed_number) if typed_number else None
    if not clean_name or (numeric is None and not clean_text):
        raise HTTPException(400, t("obs.required"))
    if typed_number and numeric is None:
        raise HTTPException(400, t("obs.numeric_invalid"))
    reference = vendor_reference_text.strip()[:500] or None
    clean_observed = _validated_date(observed_at, "obs.observed_invalid")
    clean_evidence = collapse_space(evidence_text)[:500]
    low, high = reference_bounds(reference)
    if numeric is None:
        return (clean_name, None, clean_text, "text", None,
                reference, low, high, clean_observed, clean_evidence)
    return (clean_name, numeric, None, "numeric", comparator,
            reference, low, high, clean_observed, clean_evidence)

@router.post("/observations/{observation_id}", responses=_RESPONSES_400_401_403_404)
def correct_observation(
    request: Request,
    observation_id: str,
    raw_name: Annotated[str, Form()],
    canonical_name: Annotated[str, Form()] = "",
    value_numeric: Annotated[str, Form()] = "",
    value_text: Annotated[str, Form()] = "",
    unit_raw: Annotated[str, Form()] = "",
    vendor_reference_text: Annotated[str, Form()] = "",
    observed_at: Annotated[str, Form()] = "",
    evidence_text: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
    ai_suggested: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    # A correction a model proposed is applied by a person but not checked
    # by one yet: the row goes back to `extracted` (unverified) so the
    # review queue still asks for it, rather than counting as corrected.
    from_ai = ai_suggested == "1"
    (
        clean_name, numeric, stored_text, value_type, comparator,
        reference, low, high, clean_observed, clean_evidence,
    ) = _typed_observation_value(
        raw_name, value_numeric, value_text, vendor_reference_text, observed_at, evidence_text
    )
    status, method, audit_action = (
        ("extracted", "ai_suggested_correction", "observation_ai_correction_applied")
        if from_ai
        else ("corrected", "human_corrected", "observation_corrected")
    )
    unit = unit_raw.strip()[:80] or None
    with connect(settings) as connection:
        row = connection.execute(
            """SELECT o.*, COALESCE(r.vendor_id, d.vendor_id) vendor_id FROM observations o
                   LEFT JOIN reports r ON r.id=o.report_id
                   LEFT JOIN documents d ON d.id=o.document_id
                   WHERE o.id=? AND o.owner_user_id=?""",
            (observation_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404)
        concept_id, preferred_unit = _remap_concept(
            connection,
            canonical_name,
            clean_name,
            row["vendor_id"],
            value_type,
            unit,
        )
        provisional = ParsedObservation(
            raw_name=clean_name,
            value_numeric=numeric,
            value_text=stored_text,
            comparator=comparator,
            unit_raw=unit,
            reference_text=reference,
            reference_low=low,
            reference_high=high,
            page_number=row["page_number"],
            evidence_text=clean_evidence or row["evidence_text"],
            confidence=1.0,
        )
        connection.execute(
            # Editing a value the reviewer had set aside must not quietly
            # put it back into every chart and panel: tidying the wording
            # of something you rejected is not un-rejecting it, and the row
            # has its own Restore control for when it is.
            """UPDATE observations SET
                       concept_id=?, raw_name=?, value_type=?, value_numeric=?, value_text=?,
                       comparator=?, unit_raw=?, unit_canonical=?, vendor_reference_text=?,
                       vendor_reference_low=?, vendor_reference_high=?, vendor_interpretation=?,
                       observed_at=?, evidence_text=?,
                       verification_status=CASE WHEN verification_status='rejected'
                                                THEN 'rejected' ELSE ? END,
                       extraction_method=?, confidence=?
                   WHERE id=? AND owner_user_id=?""",
            (
                concept_id,
                clean_name,
                value_type,
                numeric,
                stored_text,
                comparator,
                provisional.unit_raw,
                preferred_unit,
                reference,
                low,
                high,
                interpretation(provisional, concept_id),
                clean_observed or row["observed_at"],
                clean_evidence or row["evidence_text"],
                status,
                method,
                row["confidence"] if from_ai else 1.0,
                observation_id,
                user["id"],
            ),
        )
        connection.execute(
            """INSERT INTO audit_events(
                       owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at
                   ) VALUES (?, ?, ?, 'observation', ?, ?, ?)""",
            (
                user["id"], user["id"],
                audit_action,
                observation_id,
                json.dumps(
                    {
                        "previous_raw_name": row["raw_name"],
                        "previous_concept_id": row["concept_id"],
                        # The fields a correction actually changes. Without
                        # them the trail records that a number was corrected
                        # and cannot say what it used to be, which is the
                        # one question anybody asks of it later.
                        "previous_value_numeric": row["value_numeric"],
                        "previous_value_text": row["value_text"],
                        "previous_comparator": row["comparator"],
                        "previous_unit_raw": row["unit_raw"],
                        "previous_vendor_reference_text": row["vendor_reference_text"],
                        "concept_id": concept_id,
                        "document_id": row["document_id"],
                    },
                    ensure_ascii=False,
                ),
                utc_now(),
            ),
        )
        # The task above this row asked for N values; it says N-1 now.
        recount_review_tasks(connection, user["id"], str(row["document_id"]), user["id"])
    invalidate_catalog(user["id"])
    if _wants_json(request):
        return _row_swap(request, user["id"], str(row["document_id"]), observation_id)
    # A correction made in the review queue returns to the review queue.
    # Landing the reviewer on the document page after every fix cost them
    # their place in an 85-file run.
    return RedirectResponse(
        _safe_next(next, f"/documents/{row['document_id']}") + f"#observation-{observation_id}",
        status_code=303,
    )

def _reason_parts_of(task) -> list[dict[str, object]]:
    try:
        return list(json.loads(task.get("reason_params_json") or "{}").get("parts") or [])
    except (TypeError, ValueError, AttributeError):
        return []

def _answer_reread(connection, user, document_id: str, action: str, observation_id: str) -> list[str]:
    """Apply or settle the re-read proposals one answer covers; the observation ids it touched."""
    token_kind = user.get("token_kind")
    if action in {"apply", "apply_all"}:
        return apply_reread_proposals(
            connection, user["id"], document_id,
            None if action == "apply_all" else [observation_id], user["id"], token_kind,
        )
    settled = settle_reread_orphan(
        connection, user["id"], document_id, observation_id, action == "keep", user["id"], token_kind,
    )
    return [observation_id] if settled else []

@router.post("/documents/{document_id}/reread-proposals", responses=_RESPONSES_400_401_403_404)
def answer_reread_proposals(
    request: Request,
    document_id: str,
    action: Annotated[str, Form()],
    observation_id: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
):
    """Apply what the page now reads, or answer "no longer found", in place.

    `apply` sets one checked row to the re-read's value (`apply_all`: every
    one listed), state `corrected`; `set_aside` rejects a row the re-read no
    longer finds (the row's Restore undoes it); `keep` keeps it as checked.
    Each is audited with the credential kind that made it.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    if action not in {"apply", "apply_all", "set_aside", "keep"}:
        raise HTTPException(400)
    if action != "apply_all" and not observation_id:
        raise HTTPException(400)
    with connect(settings) as connection:
        if not connection.execute(
            _OWNED_DOCUMENT_SQL, (document_id, user["id"])
        ).fetchone():
            raise HTTPException(404)
        touched = _answer_reread(connection, user, document_id, action, observation_id)
        if not touched:
            raise HTTPException(404)
        proposals = reread_proposals(connection, user["id"], document_id)
        task = _document_review_task(connection, user["id"], document_id)
    invalidate_catalog(user["id"])
    if _wants_json(request):
        return JSONResponse(
            {
                "ok": True,
                "panel": _proposals_template.render(
                    template_context(request, proposals=proposals, document={"id": document_id},
                                     viewing=False)
                ),
                "rows": {
                    item: _observation_rows_html(request, user["id"], document_id, [item]) for item in touched
                },
                "review_line": task["line_text"] if task else "",
            }
        )
    return RedirectResponse(_safe_next(next, f"/documents/{document_id}") + "#reread-proposals", status_code=303)

@router.post("/observations/{observation_id}/state", responses=_RESPONSES_400_401_403_404)
def set_observation_state(
    request: Request,
    observation_id: str,
    action: Annotated[str, Form()],
    next: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """Accept, set aside, or restore one extracted value.

    Setting aside is not deletion: the row keeps its evidence and its
    provenance and can be restored, it simply stops counting as a
    measurement.  Parser debris is common enough that a reviewer needs a
    way to say so without destroying what the parser saw.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    states = {"verify": _VERIFIED_STATE, "reject": "rejected", "restore": "extracted"}
    if action not in states:
        raise HTTPException(400)
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT document_id, verification_status FROM observations WHERE id=? AND owner_user_id=?",
            (observation_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404)
        connection.execute(
            "UPDATE observations SET verification_status=? WHERE id=? AND owner_user_id=?",
            (states[action], observation_id, user["id"]),
        )
        connection.execute(
            """INSERT INTO audit_events(
                       owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at
                   ) VALUES (?, ?, ?, 'observation', ?, ?, ?)""",
            (
                user["id"], user["id"], f"observation_{action}", observation_id,
                json.dumps(
                    {"previous_state": row["verification_status"], "document_id": row["document_id"]},
                    ensure_ascii=False,
                ),
                utc_now(),
            ),
        )
        # The task above this row asked for N values; it says N-1 now.
        recount_review_tasks(connection, user["id"], str(row["document_id"]), user["id"])
    invalidate_catalog(user["id"])
    if _wants_json(request):
        return _row_swap(request, user["id"], str(row["document_id"]), observation_id)
    return RedirectResponse(
        _safe_next(next, f"/documents/{row['document_id']}") + f"#observation-{observation_id}",
        status_code=303,
    )

@router.post("/documents/{document_id}/observations", responses=_RESPONSES_400_401_403_404)
def add_observation(
    request: Request,
    document_id: str,
    raw_name: Annotated[str, Form()],
    page_number: Annotated[int, Form()] = 1,
    canonical_name: Annotated[str, Form()] = "",
    value_numeric: Annotated[str, Form()] = "",
    value_text: Annotated[str, Form()] = "",
    unit_raw: Annotated[str, Form()] = "",
    vendor_reference_text: Annotated[str, Form()] = "",
    observed_at: Annotated[str, Form()] = "",
    evidence_text: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """Record a value the parser missed entirely.

    Checking an extraction is only half a review: a printed result the
    parser never saw is invisible on every page of this application, and
    certifying the rest of the page as correct would quietly bless that
    gap.  The row is marked as entered by hand, so it is never mistaken
    for something the parser found.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    (
        clean_name, numeric, stored_text, value_type, comparator,
        reference, low, high, clean_observed, clean_evidence,
    ) = _typed_observation_value(
        raw_name, value_numeric, value_text, vendor_reference_text, observed_at, evidence_text
    )
    unit = unit_raw.strip()[:80] or None
    with connect(settings) as connection:
        document = connection.execute(
            "SELECT id, patient_id, vendor_id, page_count, report_date FROM documents WHERE id=? AND owner_user_id=?",
            (document_id, user["id"]),
        ).fetchone()
        if not document:
            raise HTTPException(404)
        page = max(1, min(int(page_number), int(document["page_count"] or 1)))
        report = connection.execute(
            """SELECT id, vendor_id, report_date FROM reports
                   WHERE document_id=? AND ? BETWEEN start_page AND end_page
                   ORDER BY start_page LIMIT 1""",
            (document_id, page),
        ).fetchone()
        report_id, report_vendor_id, report_date = (
            (report["id"], report["vendor_id"], report["report_date"]) if report else (None, None, None)
        )
        vendor_id = report_vendor_id or document["vendor_id"]
        concept_id, preferred_unit = _remap_concept(
            connection,
            canonical_name,
            clean_name,
            vendor_id,
            value_type,
            unit,
        )
        provisional = ParsedObservation(
            raw_name=clean_name,
            value_numeric=numeric,
            value_text=stored_text,
            comparator=comparator,
            unit_raw=unit,
            reference_text=reference,
            reference_low=low,
            reference_high=high,
            page_number=page,
            evidence_text=clean_evidence or t("obs.entered_evidence"),
            confidence=1.0,
        )
        observation_id = str(uuid.uuid4())
        connection.execute(
            """INSERT INTO observations(
                       id, owner_user_id, patient_id, document_id, report_id, page_number,
                       concept_id, raw_name, value_type, value_numeric, value_text, comparator,
                       unit_raw, unit_canonical, observed_at, vendor_reference_text,
                       vendor_reference_low, vendor_reference_high, vendor_interpretation,
                       verification_status, extraction_method, confidence, evidence_text,
                       parser_version, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                             'corrected', 'human_entered', 1.0, ?, 'human', ?)""",
            (
                observation_id, user["id"], document["patient_id"], document_id,
                report_id, page, concept_id, clean_name,
                value_type, numeric,
                stored_text, comparator, unit, preferred_unit,
                clean_observed or report_date or document["report_date"],
                reference, low, high, interpretation(provisional, concept_id),
                provisional.evidence_text, utc_now(),
            ),
        )
        connection.execute(
            """INSERT INTO audit_events(
                       owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at
                   ) VALUES (?, ?, 'observation_entered', 'observation', ?, ?, ?)""",
            (
                user["id"], user["id"], observation_id,
                json.dumps({"document_id": document_id, "concept_id": concept_id}, ensure_ascii=False),
                utc_now(),
            ),
        )
    invalidate_catalog(user["id"])
    return RedirectResponse(
        _safe_next(next, f"/documents/{document_id}") + f"#observation-{observation_id}",
        status_code=303,
    )

@router.post("/documents/{document_id}/issues", responses=_RESPONSES_400_401_403_404)
def report_parser_issue(
    request: Request,
    document_id: str,
    category: Annotated[str, Form()],
    observation_id: Annotated[str, Form()] = "",
    expected_text: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """File a report that the parser misread this document.

    A correction fixes one number; this row exists so the parser defect
    behind it can be found later.  It is written for whoever does that
    fixing, so the whole state of the misread — source file, page,
    evidence line, what was stored — is snapshotted now, before a re-scan
    or a correction erases it.  Migration 017 documents the contract.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    if category not in ISSUE_CATEGORIES:
        raise HTTPException(400)
    expected = collapse_space(expected_text)[:500] or None
    details = description.strip()[:2000] or None
    with connect(settings) as connection:
        document = connection.execute(
            """SELECT d.id, d.title, d.original_filename, d.source_path, d.clinical_type,
                          d.report_date, d.sha256, v.canonical_name vendor
                   FROM documents d LEFT JOIN vendors v ON v.id=d.vendor_id
                   WHERE d.id=? AND d.owner_user_id=?""",
            (document_id, user["id"]),
        ).fetchone()
        if not document:
            raise HTTPException(404)
        observation = None
        clean_observation_id = observation_id.strip() or None
        if clean_observation_id:
            observation = connection.execute(
                """SELECT o.*, c.canonical_name FROM observations o
                       LEFT JOIN concepts c ON c.id=o.concept_id
                       WHERE o.id=? AND o.document_id=? AND o.owner_user_id=?""",
                (clean_observation_id, document_id, user["id"]),
            ).fetchone()
            if not observation:
                raise HTTPException(404)
        context = {
            "parser_version": PARSER_VERSION,
            "document": {
                key: document[key]
                for key in (
                    "id", "title", "original_filename", "source_path",
                    "vendor", "clinical_type", "report_date", "sha256",
                )
            },
            "observation": {
                key: observation[key]
                for key in (
                    "id", "raw_name", "concept_id", "canonical_name",
                    "value_numeric", "value_text", "comparator", "unit_raw",
                    "unit_canonical", "vendor_reference_text", "page_number",
                    "evidence_text", "extraction_method", "parser_version",
                    "verification_status", "observed_at",
                )
            }
            if observation
            else None,
        }
        issue_id = str(uuid.uuid4())
        connection.execute(
            """INSERT INTO parser_issue_reports(
                       id, owner_user_id, document_id, observation_id, category,
                       expected_text, description, context_json, status, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (
                issue_id, user["id"], document_id, clean_observation_id,
                category, expected, details,
                json.dumps(context, ensure_ascii=False), utc_now(),
            ),
        )
        connection.execute(
            """INSERT INTO audit_events(
                       owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at
                   ) VALUES (?, ?, 'issue_reported', 'parser_issue_report', ?, ?, ?)""",
            (
                user["id"], user["id"], issue_id,
                json.dumps(
                    {"document_id": document_id, "observation_id": clean_observation_id, "category": category},
                    ensure_ascii=False,
                ),
                utc_now(),
            ),
        )
    return RedirectResponse(
        _safe_next(next, f"/documents/{document_id}") + "#issue-reports", status_code=303
    )

@router.post("/issues/{issue_id}/state", responses=_RESPONSES_400_401_403_404)
def set_issue_state(
    request: Request,
    issue_id: str,
    action: Annotated[str, Form()],
    next: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    """Close a filed parser problem as fixed, or reopen it.

    Resolving is a statement that the defect is fixed and the document
    re-read — not that the report was seen — so it is reversible.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    states = {"resolve": "resolved", "reopen": "open"}
    if action not in states:
        raise HTTPException(400)
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT document_id, status FROM parser_issue_reports WHERE id=? AND owner_user_id=?",
            (issue_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404)
        connection.execute(
            "UPDATE parser_issue_reports SET status=?, resolved_at=? WHERE id=? AND owner_user_id=?",
            (
                states[action],
                utc_now() if action == "resolve" else None,
                issue_id,
                user["id"],
            ),
        )
        connection.execute(
            """INSERT INTO audit_events(
                       owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at
                   ) VALUES (?, ?, ?, 'parser_issue_report', ?, ?, ?)""",
            (
                user["id"], user["id"],
                "issue_resolved" if action == "resolve" else "issue_reopened", issue_id,
                json.dumps(
                    {"previous_status": row["status"], "document_id": row["document_id"]},
                    ensure_ascii=False,
                ),
                utc_now(),
            ),
        )
    return RedirectResponse(
        _safe_next(next, f"/documents/{row['document_id']}") + "#issue-reports", status_code=303
    )

# --- search -------------------------------------------------------------
#
# /metrics answers three questions on one page, through one renderer
# (`_search_results.html`) shared by the page load and the live search:
# "where is X?" (q), "what needs me?" (status) and "what is in this area?"
# (area).  With none of them it lists every result compactly -- the panel
# cards that used to follow the search box (56 000 px on a phone) are
# /panels' job.

METRIC_STATUSES = ("attention", "due", "oldest", "unverified")
#: How each status chip is coloured; anything else is neutral.
_STATUS_TONES = {"attention": "attention", "due": "due", "unverified": "due"}
_STATUS_TEXT = {
    "attention": ("insights.attention_heading", "insights.attention_lead"),
    "due": ("insights.due_heading", "insights.due_lead"),
    "oldest": ("insights.oldest_heading", "insights.oldest_lead"),
    "unverified": ("metrics.status_unverified", "insights.unverified_lead"),
}
_GROUP_HEADINGS = {
    "metrics": "metrics.group_analytes",
    "device_metrics": "metrics.group_devices",
    "vaccinations": "metrics.group_vaccinations",
    "findings": "metrics.group_findings",
    "documents": "metrics.group_documents",
    "panels": "metrics.group_panels",
    "areas": "metrics.group_areas",
}
_GROUP_KINDS = {
    "metrics": "metric", "device_metrics": "metric", "panels": "panel",
    "vaccinations": "row", "findings": "row", "documents": "row", "areas": "row",
}

def _group(key: str, rows: list, *, kind: str | None = None, page=None, fold: bool = False) -> dict[str, object]:
    """One result group; `page` slices it, `fold` shows a dozen and keeps the
    rest one click away on the same page, so the count on the heading is
    always the count of what can be opened here."""
    shown = rows[page["offset"]: page["offset"] + page["limit"]] if page else rows
    cut = SEARCH_PAGE_SIZE if fold else len(shown)
    return {
        "key": key,
        "kind": kind or _GROUP_KINDS[key],
        "heading": t(_GROUP_HEADINGS[key]),
        "rows": shown[:cut],
        "more_rows": shown[cut:],
        "total": len(rows),
        "page": page,
    }

def _both_languages(text: str | None) -> list[str]:
    english = _english(str(text or ""))
    return [str(text or ""), english, PHRASES.get(english, "")]

def _document_reported_concepts(
    connection, owner_user_id: str, analyte_terms: dict[str, record_search.Terms] | None,
) -> dict[str, list[str]]:
    """Concept ids each document reports, read only when there are analyte
    names to attach to them."""
    reported: dict[str, list[str]] = {}
    if not analyte_terms:
        return reported
    for row in connection.execute(
        """SELECT DISTINCT document_id, concept_id FROM observations
                WHERE owner_user_id=? AND document_id IS NOT NULL AND concept_id IS NOT NULL
                  AND verification_status <> 'rejected'""",
        (owner_user_id,),
    ):
        reported.setdefault(str(row["document_id"]), []).append(str(row["concept_id"]))
    return reported

def _document_locale_terms(row, kind: str, vendor: str, when: str | None) -> tuple[list[str], list[str]]:
    """A document's names and dates as both languages print them."""
    names: list[str] = [str(row["title"] or "")]
    dates: list[str] = []
    for locale in ("en", "uk"):
        token = activate_locale(locale)
        try:
            names += [
                display_document_title(row["title"], kind, vendor),
                translate_phrase(DOCUMENT_TYPE_TITLES.get(kind, "")),
                enum_label(kind) if kind else "",
                translate_phrase(vendor) if vendor else "",
            ]
            dates.append(format_date(when) if when else "")
        finally:
            reset_locale(token)
    return names, dates

def _document_analyte_terms(
    searchable: record_search.Terms, concept_ids, analyte_terms: dict[str, record_search.Terms] | None,
) -> record_search.Terms:
    """The document's own terms plus the names of the results it reports,
    each term once."""
    held = {term for term, _ in searchable}
    for concept_id in concept_ids:
        for term, _ in (analyte_terms or {}).get(concept_id, ()):
            if term not in held:
                held.add(term)
                searchable += ((term, 1),)
    return searchable

def _document_entry(
    row, reported: dict[str, list[str]], analyte_terms: dict[str, record_search.Terms] | None,
) -> tuple[record_search.Terms, dict[str, object]]:
    vendor = str(row["vendor"] or "")
    vendor = "" if vendor in {_UNKNOWN_PROVIDER, _UNKNOWN_VENDOR} else vendor
    kind = str(row["clinical_type"] or "")
    when = str(row["report_date"] or "")[:10] or None
    names, dates = _document_locale_terms(row, kind, vendor, when)
    if when:
        dates += [when, f"{when[8:10]}.{when[5:7]}.{when[:4]}"]
    vendor_label = translate_phrase(vendor) if vendor else t(_UNKNOWN_PROVIDER_KEY)
    searchable = record_search.terms(names, [*dates, str(row["original_filename"] or "")])
    searchable = _document_analyte_terms(searchable, reported.get(str(row["id"]), ()), analyte_terms)
    return (
        searchable,
        {
            "title": display_document_title(row["title"], kind, vendor),
            "subtitle": " · ".join(
                part for part in (
                    format_date(when) if when else "",
                    vendor_label,
                    translate_phrase(DOCUMENT_TYPE_TITLES.get(kind, "")),
                ) if part
            ),
            "url": f"/documents/{row['id']}",
        },
    )

def _document_entries(
    connection, owner_user_id: str, analyte_terms: dict[str, record_search.Terms] | None = None,
) -> list[tuple[record_search.Terms, dict[str, object]]]:
    """Every document by title, kind, provider and date, in both languages,
    and by the results it reports: a lipid panel answers «холестерин» though
    its title says «Ліпідограма».  `analyte_terms` is each metric card's own
    names by concept id; on a document they are context, ranked below its
    title."""
    reported = _document_reported_concepts(connection, owner_user_id, analyte_terms)
    rows = connection.execute(
        """SELECT d.id, d.title, d.clinical_type, d.report_date, d.imported_at,
                      d.original_filename, v.canonical_name vendor
               FROM documents d LEFT JOIN vendors v ON v.id=d.vendor_id
               WHERE d.owner_user_id=? AND d.duplicate_of_document_id IS NULL
               ORDER BY COALESCE(d.report_date, substr(d.imported_at, 1, 10)) DESC, d.rowid DESC""",
        (owner_user_id,),
    ).fetchall()
    return [_document_entry(row, reported, analyte_terms) for row in rows]

def _record_search(connection, owner_user_id: str, q: str, offset: int) -> list[dict[str, object]]:
    """Every kind of thing the record holds, matched by word starts and
    case endings in both languages (`web/search.py` has the rules)."""
    query = record_search.parse(q)
    if not query.phrases:
        return []
    catalog = _metric_catalog(connection, owner_user_id, include_suppressed=True)
    panels = sorted(_panel_cards(connection, owner_user_id, member_limit=6), key=_panel_sort_key)
    findings: dict[tuple[object, str], dict[str, object]] = {}
    for row in _finding_catalog(connection, owner_user_id):
        # One row per conclusion, though it is filed under every area it
        # touches; the attention copy wins so the badge is never lost.
        key = (row["document_id"], _finding_summary(row))
        if key not in findings or row.get("status") == "attention":
            findings[key] = row
    # CONTRACTS §4: the vaccination module owns its own vocabulary --
    # vaccine code, trade name, manufacturer, diseases, in both languages.
    vaccinations = immunization_records.search_entries(connection, owner_user_id, get_locale())
    candidates: dict[str, list[tuple[record_search.Terms, object]]] = {
        "metrics": [(card["search_terms"], card) for card in catalog if not card["is_device"]],
        "device_metrics": [(card["search_terms"], card) for card in catalog if card["is_device"]],
        "panels": [
            (record_search.terms([
                *_both_languages(panel["name"]), *_both_languages(panel["short"]),
            ]), panel)
            for panel in panels
        ],
        "vaccinations": [
            # "vaccination" is search vocabulary, not text: it makes every
            # dose an answer to «щеплення» and "vaccine" via the synonyms.
            (record_search.terms([entry["title"], *entry.get("terms", [])], [entry.get("subtitle"), "vaccination"]), entry)
            for entry in vaccinations
        ],
        "findings": [
            (
                record_search.terms(
                    [row.get("summary_en"), row.get("summary_uk"), row.get("original_text")],
                    [*_both_languages(row.get("title")), row.get("vendor")],
                ),
                _finding_result(row),
            )
            for row in findings.values()
        ],
        "documents": _document_entries(
            connection, owner_user_id,
            {str(card["id"]): card["search_terms"] for card in catalog if not card["is_device"]},
        ),
        "areas": [
            (
                record_search.terms([*_both_languages(area["name"]), *_both_languages(area["short"])]),
                {"title": area["name"], "subtitle": area["description"], "url": f"/areas/{area['id']}"},
            )
            for area in localized_health_areas()
        ],
    }
    ranked = record_search.rank(query, candidates)
    # A fixed order, never "best match first": the same word typed one
    # letter further must not swap the results and the conclusions round.
    groups = []
    for key in (key for key in candidates if ranked[key]):
        rows = [item for _, item in ranked[key]]
        if key == "metrics":
            page = _pagination(len(rows), offset, PAGE_SIZE, f"/metrics?q={quote(q)}")
            groups.append(_group(key, rows, page=page))
        else:
            groups.append(_group(key, rows, fold=True))
    return groups

def _search_texts(q: str, found: bool) -> tuple[str, dict[str, str] | None, tuple[str, str]]:
    """(note, link, empty state) for a search.  Two letters find only whole
    words and one finds nothing, and the page says so rather than showing a
    random handful; otherwise the link points at the search inside report
    text, which this page does not do."""
    if record_search.parse(q).short:
        explain = t_plural("metrics.short_query", record_search.MIN_LETTERS)
        return (explain if found else ""), None, (t("metrics.short_query_title"), explain)
    link = {"url": f"/documents?q={quote(q)}", "label": t("metrics.search_document_text")}
    return "", link, (t("metrics.empty_title"), t("metrics.empty_body"))

def _status_groups(connection, owner_user_id: str, status: str, offset: int = 0) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    """One /insights section, as a filter: (groups, an optional note link)."""
    if status == "attention":
        catalog = _complete_days(connection, owner_user_id, _metric_catalog(connection, owner_user_id))
        # Copies: the cards are the memoised catalog (see panel_json).
        cards = [{**card, "outside_by_text": _outside_by_text(card)} for card in _attention_cards(catalog)]
        findings = [_finding_result(row) for row in _attention_findings(_finding_catalog(connection, owner_user_id))]
        return [
            group for group in (
                _group("metrics", [card for card in cards if not card["is_device"]], kind="attention"),
                _group("findings", findings),
                _group("device_metrics", [card for card in cards if card["is_device"]], kind="attention"),
            ) if group["rows"]
        ], None
    if status in {"due", "oldest"}:
        panels = _panel_cards(connection, owner_user_id, member_limit=6)
        rows = _due_panels(panels) if status == "due" else _oldest_panels(panels)
        link = {"url": _UPLOAD_URL, "label": t("insights.upload_cta")} if status == "due" else None
        return ([_group("panels", rows)] if rows else []), link
    cards = [
        card for card in _metric_catalog(connection, owner_user_id)
        if card["verification_status"] == "extracted"
    ]
    lab = [card for card in cards if not card["is_device"]]
    groups = [
        group for group in (
            _group("metrics", lab, page=_pagination(len(lab), offset, PAGE_SIZE, "/metrics?status=unverified")),
            _group("device_metrics", [card for card in cards if card["is_device"]]),
        ) if group["rows"]
    ]
    return groups, {"url": "/documents?review_state=open", "label": t("insights.open_review")}

def _status_counts(connection, owner_user_id: str) -> dict[str, int]:
    catalog = _complete_days(connection, owner_user_id, _metric_catalog(connection, owner_user_id))
    panels = _panel_cards(connection, owner_user_id, member_limit=6)
    return {
        "attention": len(_attention_cards(catalog)) + len(_attention_findings(_finding_catalog(connection, owner_user_id))),
        "due": len(_due_panels(panels)),
        "oldest": len(_oldest_panels(panels)),
        "unverified": sum(
            1 for card in _metric_catalog(connection, owner_user_id)
            if card["verification_status"] == "extracted"
        ),
    }

def _metrics_view(connection, owner_user_id: str, q: str = "", status: str = "", area: str = "", offset: int = 0) -> dict[str, object]:
    """What /metrics shows for one combination of its three filters."""
    q = q.strip()
    offset = max(0, offset)
    note, link = "", None
    empty = (t("metrics.empty_title"), t("metrics.empty_body"))
    if q:
        groups = _record_search(connection, owner_user_id, q, offset)
        title = t("metrics.matches_for", query=q)
        status = area = ""
        note, link, empty = _search_texts(q, bool(groups))
    elif status in METRIC_STATUSES:
        groups, link = _status_groups(connection, owner_user_id, status, offset)
        heading, lead = _STATUS_TEXT[status]
        title, note = t(heading), t(lead)
        if status == "unverified":
            counts = _counts(connection, owner_user_id)
            if int(counts["unverified"]):
                note = " ".join((
                    t_plural("metrics.unverified_results", int(counts["unverified"])),
                    t_plural("metrics.unverified_in_documents", int(counts["unverified_documents"])),
                    note,
                ))
        empty = (t(f"insights.{status}_empty_title"), t(f"insights.{status}_empty_body"))
        area = ""
    elif area in AREA_BY_ID:
        cards = [card for card in _metric_catalog(connection, owner_user_id) if area in card["area_ids"]]
        lab = [card for card in cards if not card["is_device"]]
        groups = [
            group for group in (
                _group("metrics", lab, page=_pagination(len(lab), offset, PAGE_SIZE, f"/metrics?area={area}")),
                _group("device_metrics", [card for card in cards if card["is_device"]]),
            ) if group["rows"]
        ]
        title = translate_phrase(str(AREA_BY_ID[area]["name"]))
        link = {"url": f"/areas/{area}", "label": t("metrics.open_area", area=title)}
        status = ""
    else:
        status = area = ""
        cards = _metric_catalog(connection, owner_user_id)
        lab = sum(1 for card in cards if not card["is_device"])
        return {
            "q": "", "status": "", "area": "",
            "title": t("metrics.overview_title"), "note": "", "link": None,
            "groups": [],
            "sections": _landing_sections(cards),
            # One count, the whole record: the old landing printed "113
            # shown" beside a group headed "595".
            "count_text": " · ".join(
                text for text in (
                    t_plural("metrics.count_lab", lab) if lab else "",
                    t_plural("metrics.count_device", len(cards) - lab) if len(cards) > lab else "",
                ) if text
            ),
            "empty_title": empty[0], "empty_body": empty[1],
        }
    return {
        "q": q, "status": status, "area": area,
        "title": title, "note": note, "link": link,
        "groups": groups,
        "sections": [],
        # Every match, not the slice on screen; the pager says which slice.
        "count_text": t_plural("metrics.result_count", sum(int(group["total"]) for group in groups)),
        "empty_title": empty[0], "empty_body": empty[1],
    }

def _landing_section(
    device: bool, area_id: str, name: str, rows: list[dict[str, object]], known: set[str]
) -> dict[str, object]:
    return {
        "key": f"{'device' if device else 'lab'}-{area_id}",
        "area_id": area_id if area_id in known else "",
        "title": name,
        "device": device,
        "rows": rows,
        "total": len(rows),
        "flagged": sum(1 for card in rows if _attention_rank(card) <= 3),
    }

def _landing_sections(cards: list[dict[str, object]]) -> list[dict[str, object]]:
    """/metrics with nothing typed: every result, grouped by body system.

    Laboratory sections first, open; device measurements after, in their
    own sections, closed.  Each keeps the catalog order -- what needs
    attention, then what is recent -- so its first rows are the ones worth
    reading.  A card sits in its primary area only, so the section counts
    add up to the count line.
    """
    by_area: dict[tuple[bool, str], list[dict[str, object]]] = {}
    for card in cards:
        by_area.setdefault((bool(card["is_device"]), str(card["primary_area_id"])), []).append(card)
    areas = localized_health_areas()
    known = {str(area["id"]) for area in areas}
    sections = []
    for device in (False, True):
        listed = [(str(area["id"]), str(area["name"])) for area in areas]
        stray = sorted({key for is_device, key in by_area.keys() if is_device == device and key not in known})
        listed += [(key, t("metrics.section_other")) for key in stray]
        for area_id, name in listed:
            rows = by_area.get((device, area_id))
            if not rows:
                continue
            sections.append(_landing_section(device, area_id, name, rows, known))
    return sections

@router.get("/metrics", response_class=HTMLResponse, responses=_RESPONSES_401)
def metrics(request: Request, q: str = "", status: str = "", area: str = "", offset: int = 0):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        view = _metrics_view(connection, user["id"], q, status, area, offset)
        everything = _metric_catalog(connection, user["id"])
        status_counts = _status_counts(connection, user["id"])
    statuses = [
        {
            "key": key,
            "label": t(_STATUS_TEXT[key][0]),
            "count": status_counts[key],
            "tone": _STATUS_TONES.get(key, "neutral"),
        }
        for key in METRIC_STATUSES
        # A chip that would open an empty list is noise; the active one
        # stays so the reader can see what they are looking at.
        if status_counts[key] or view["status"] == key
    ]
    return templates.TemplateResponse(
        request,
        "metrics.html",
        template_context(
            request,
            view=view,
            q=view["q"],
            statuses=statuses,
            total_metrics=len(everything),
            active="metrics",
        ),
    )

@router.get("/api/metrics/search", responses=_RESPONSES_401)
def metric_search(request: Request, q: str = "", status: str = "", area: str = "", offset: int = 0):
    """The /metrics result region, rendered by the template the page uses.

    One renderer, one truth: the type-ahead used to rebuild cards from JSON
    and left slots showing a blank seed card's text, so an out-of-range
    ferritin came back with "Above range" printed over "Your result is
    inside this range".
    """
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        view = _metrics_view(connection, user["id"], q, status, area, offset)
    html = templates.get_template("_search_results.html").render(
        {**template_context(request), "view": view}
    )
    return {
        "html": html,
        "title": view["title"],
        "count_text": view["count_text"],
        "status": view["status"],
        "area": view["area"],
        "totals": {group["key"]: group["total"] for group in view["groups"]},
        "order": [group["key"] for group in view["groups"]],
    }


def _metric_panel_context(
    connection, panel, catalog: dict[str, dict[str, object]], concept_id: str,
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    """The panel card this result belongs to and up to twelve of its
    other members, or (None, []) outside any panel."""
    if panel is None:
        return None, []
    names = _panel_member_names(connection, panel_members(connection, panel))
    panel_card = _panel_card(connection, panel, catalog, names)
    siblings = [
        {
            "id": member["id"],
            "name": member["name"],
            "url": member["url"],
            "verdict_interpretation": str(
                (member["verdict"] or {}).get("interpretation") or "unjudged"
            ),
        }
        for member in panel_card["members"]
        if str(member["id"]) != concept_id
    ][:12]
    return panel_card, siblings

def _metric_history_row(connection, concept_id: str, row, date_of_birth, sex) -> None:
    """One history-table row's display fields and its own verdict, in place."""
    # The deduped ROW's own unit, never the concept's aspiration: an
    # unconvertible 35 µmol/L urobilinogen was relabelled "35 mg/dL".
    row["display_unit"] = display_unit(_row_display_unit(row))
    row["display_value"] = format_reading(row, row["display_unit"])
    # The laboratory's printed range, shown only when it describes this
    # patient - and never rendered in the source language in EN mode.
    comparison = _original_comparison(
        row, date_of_birth=date_of_birth, sex=sex,
    )
    row["display_reference"] = localized_reference(
        comparison["reference_text"] or _row_reference_display(
            row, comparison["age_at_observation"], sex, row["display_unit"],
        )
    )
    row["display_status"] = comparison["status_label"]
    row["display_comparison"] = comparison
    row["date_text"] = format_date(row["observed_at"])
    # Which interval judged this result, at the age it was taken.  When
    # another authority judged it and the laboratory's printed range
    # does not describe this patient, "Not applicable to this age or
    # sex" under a verdict reads as a contradiction, so it is withheld.
    _, row_verdict = _reading_verdict(
        connection, concept_id, row, comparison["age_at_observation"], sex
    )
    row["verdict"] = row_verdict
    row["verdict_state"] = verdict_state(row_verdict)
    row["judged"] = row_verdict.get("interpretation") not in {None, "unjudged", "not_a_measurement"}
    interval = row_verdict.get("target_range_text") or row_verdict.get("range_text")
    row["judged_text"] = (
        t("export.judged_against", interval=interval, authority=str(row_verdict.get("authority_label") or ""))
        if row["judged"] and interval and interval != t(_EM_DASH_KEY) else ""
    )
    row["hide_lab"] = bool(
        # A device day has no printed range to show.
        row.get("is_device")
        or (
            row["judged"]
            and row_verdict.get("authority") != "vendor"
            and comparison["comparison_basis"] == "none"
            and comparison["reference_text"] is None
        )
    )

def _metric_rule(raw_rule, age, sex, page_context) -> dict[str, object]:
    rule = dict(raw_rule)
    # label_uk / verdict.* in the reader's language (F4 helpers); a note
    # or an English document title nobody translated is withheld on a
    # Ukrainian page (rule_text) -- the band, interval and source remain.
    rule["label"] = translate_phrase(rule_label(raw_rule))
    rule["interpretation_key"] = str(raw_rule["interpretation"])
    rule["interpretation"] = interpretation_label(str(raw_rule["interpretation"]))
    rule["notes"] = rule_text(raw_rule, "notes")
    rule["reference_set"] = rule_text(raw_rule, "reference_set")
    rule["publisher"] = translate_phrase(str(rule["publisher"]))
    # Matching keys (assay cut-off, risk category, its requirement) are
    # machinery the applicability chip already states in words.
    rule["context"] = localize_mapping({
        key: value for key, value in rule_context(rule["context_json"]).items()
        if key not in {"vendor_upper", "not_vendor_upper", "cv_risk_category", "requires"}
        or (key == "requires" and "cv_risk_category" not in value)
    })
    rule["range_text"] = _bounds_text(rule["lower_bound"], rule["upper_bound"], rule["unit"])
    # Two bands named "Within the reference interval" with different
    # numbers are unreadable until each says whose numbers they are.
    rule.update(_rule_applicability(raw_rule, age, sex))
    # A risk-category goal applies to you only for your own category;
    # all five LDL tiers used to read "Applies to you".
    requirement = rule_requirement(raw_rule)
    if requirement:
        rule["applicability"] = " · ".join(
            part for part in (rule.get("applicability"), str(requirement["label"])) if part
        )
        rule["applies_to_you"] = bool(rule["applies_to_you"]) and rule_applies_to_context(
            raw_rule, page_context
        )
    return rule

def _metric_chart(connection, values, preferred_unit, date_of_birth, sex) -> list[dict[str, object]]:
    """The chart series, marking each history row the shared axis left out."""
    chart_points = _chart_payload(
        values, preferred_unit,
        date_of_birth=date_of_birth, sex=sex,
        connection=connection,
    )
    chart_unit = chart_points[0]["unit"] if chart_points else None
    for row in values:
        # A reading the shared axis excluded (its unit cannot be converted
        # to the series unit) is disclosed in the history table.
        row["off_axis"] = bool(
            row["value_numeric"] is not None
            and chart_unit
            and row["display_unit"]
            and row["display_unit"] != chart_unit
        )
    return chart_points

def _metric_latest(connection, concept_id: str, values, card) -> tuple[object, object, dict[str, object]]:
    """(latest row, the previous numeric row, the page verdict)."""
    latest = values[0] if values else None
    previous_numeric = next(
        (item for item in values[1:] if item["value_numeric"] is not None), None
    ) if latest and latest["value_numeric"] is not None else None
    verdict = (card or {}).get("verdict") or evaluate(connection, concept_id=concept_id)
    if latest is not None and latest["value_numeric"] is not None:
        latest["display_value"] = precise_at_edges(
            latest["value_numeric"], latest["display_value"], verdict
        )
    return latest, previous_numeric, verdict

def _metric_guidance(entry: dict[str, object]) -> dict[str, object]:
    return {
        "short_description": translate_phrase(str(entry.get("short_description") or "")) or None,
        "why_it_matters": translate_phrase(str(entry.get("why_it_matters") or "")) or None,
        "retest_rationale": translate_phrase(str(entry.get("retest_rationale") or "")) or None,
    }

def _metric_area(category) -> dict[str, object] | None:
    if category not in CATEGORY_TO_AREA:
        return None
    return {
        **AREA_BY_ID[CATEGORY_TO_AREA[category]],
        "name": translate_phrase(str(AREA_BY_ID[CATEGORY_TO_AREA[category]]["name"])),
    }

#: History rows per page: a scale's daily weight is hundreds of rows.
METRIC_HISTORY_PAGE_SIZE = 50


def _twin_days(connection, owner_user_id: str, keys: list[str]) -> dict[str, int]:
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    return {
        str(row["metric_key"]): int(row["days"])
        for row in connection.execute(
            f"""SELECT metric_key, COUNT(DISTINCT day) days FROM device_metric_days
                WHERE owner_user_id=? AND metric_key IN ({placeholders}) GROUP BY metric_key""",
            (owner_user_id, *keys),
        )
    }


def _twin_links(connection, owner_user_id: str, concept_id: str) -> list[dict[str, object]]:
    """The device metrics this concept is linked to, each with why, and only
    those this owner records (a link to an empty device page is a 404)."""
    twins = MEASUREMENT_TWINS.get(concept_id, ())
    days = _twin_days(connection, owner_user_id, [key for key, _ in twins])
    return [
        {
            "key": key,
            "relation": relation,
            "url": f"/devices/metrics/{key}",
            "name": _device_member_name(key),
            "days_text": t_plural("device.days_count", days[key], value=format_count(days[key])),
            "why": t(f"twin.why_{key}"),
        }
        for key, relation in twins
        if key in days
    ]


def _method_series(
    connection, owner_user_id: str, concept, date_of_birth, age, sex
) -> list[dict[str, object]]:
    """Each same-quantity-other-method twin as its own series, judged by its
    own library entry: a fingertip spot check and a wrist sensor's nightly
    average are never one line, and never one verdict."""
    columns = [str(row[1]) for row in connection.execute("PRAGMA table_info(observations)")]
    series = []
    for key in device_twins(str(concept["id"]), "method"):
        raw = [row for row in device_metric_values(connection, owner_user_id, key) if valid_row(row)]
        if not raw:
            continue
        latest = raw[0]
        own = {
            "id": key, "canonical_name": str(latest["metric_name"]),
            "category": concept["category"], "preferred_unit": latest["unit"],
        }
        rows = [_device_reading_row(own, row, columns) for row in raw]
        points = _chart_payload(rows, latest["unit"], date_of_birth=date_of_birth, sex=sex, connection=connection)
        for point in points:
            point["line"] = "method"
            point["source_text"] = t("twin.source_method")
        unit = display_unit(str(latest["unit"]) if latest["unit"] else None)
        verdict = evaluate(
            connection, concept_id=key, value_numeric=latest["value"],
            unit=str(latest["unit"] or ""), age_years=age, sex=sex,
        )
        series.append(
            {
                "key": key,
                "name": _device_member_name(key),
                "url": f"/devices/metrics/{key}",
                "value_text": format_quantity(latest["value"], unit),
                "unit": unit,
                "date": str(latest["day"]),
                "source": human_source_label(str(latest["source_vendor"]), str(latest["source_name"])),
                "verdict": verdict,
                "days_text": t_plural("device.days_count", len(raw), value=format_count(len(raw))),
                "why": t(f"twin.why_{key}"),
                "points": points,
            }
        )
    return series


@router.get("/metrics/{concept_id}", response_class=HTMLResponse, responses=_RESPONSES_401_404)
def metric_detail(request: Request, concept_id: str, offset: int = 0):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        concept = connection.execute("SELECT c.* FROM concepts c WHERE c.id=?", (concept_id,)).fetchone()
        # Documents and same-measurement device days alike: a scale-only
        # weight is still this page, never a 404.
        values = _linked_observation_rows(connection, user["id"], concept_id) if concept else []
        if not values:
            raise HTTPException(404)
        age, sex = _demographics(connection, user["id"])
        measure = _measure_again(settings, connection, user["id"], concept_id, sex)
        page_context = _clinical_context(connection, user["id"])
        patient = _patient_row(connection, user["id"])
        aliases = connection.execute(
            "SELECT alias FROM concept_aliases WHERE concept_id=? ORDER BY alias", (concept_id,)
        ).fetchall()
        rules = connection.execute(
            """SELECT rr.*, rs.name reference_set, rs.publisher, rs.source_url, rs.reviewed_at
                   FROM curated_reference_rules rr JOIN reference_sets rs ON rs.id=rr.reference_set_id
                   WHERE rr.concept_id=? ORDER BY rr.priority DESC""",
            (concept_id,),
        ).fetchall()
        catalog = _by_id(_metric_catalog(connection, user["id"], include_suppressed=True))
        card = catalog.get(concept_id)
        correlation = _correlation_context(connection, user["id"], concept_id)
        entry = _guidance_index(connection).get(concept_id) or {}
        panel = panel_for_concept(concept_id, str(concept["category"]))
        panel_card, siblings = _metric_panel_context(connection, panel, catalog, concept_id)
        date_of_birth = patient["date_of_birth"] if patient else None
        twin_links = _twin_links(connection, user["id"], concept_id)
        method_series = _method_series(connection, user["id"], concept, date_of_birth, age, sex)
    for row in values:
        _metric_history_row(connection, concept_id, row, date_of_birth, sex)
    parsed_rules = [_metric_rule(raw_rule, age, sex, page_context) for raw_rule in rules]
    chart_points = _metric_chart(connection, values, concept["preferred_unit"], date_of_birth, sex)
    chart_unit = canonical_unit(str(chart_points[0]["unit"])) if chart_points else None
    for method in method_series:
        # Drawn beside the main series only on the same axis unit.
        chart_points.extend(
            point for point in method["points"]
            if chart_unit is None or canonical_unit(str(point["unit"])) == chart_unit
        )
    chart_points.sort(key=lambda point: str(point["date"]))
    chart_sources = {str(point["source"]) for point in chart_points if point["line"] == "main"}
    if any(point["line"] == "method" for point in chart_points):
        chart_sources.add("method")
    latest, previous_numeric, verdict = _metric_latest(connection, concept_id, values, card)
    chart_band = _chart_band(verdict)
    history_page = _pagination(len(values), max(0, offset), METRIC_HISTORY_PAGE_SIZE, f"/metrics/{concept_id}")
    history = values[history_page["offset"]: history_page["offset"] + METRIC_HISTORY_PAGE_SIZE]
    return templates.TemplateResponse(
        request,
        "metric_detail.html",
        template_context(
            request, concept=concept, values=values, aliases=aliases, rules=parsed_rules,
            history=history,
            page=history_page,
            # A legend only where the chart mixes paths; a lab-only chart has one.
            chart_legend=[kind for kind in ("clinic", "device", "method") if kind in chart_sources]
            if len(chart_sources) > 1 else [],
            twin_links=twin_links,
            method_series=method_series,
            chart_points=chart_points,
            latest=latest, previous_numeric=previous_numeric,
            card=card,
            verdict=verdict,
            blocked_notice=_blocked_notice(verdict),
            trend=(card or {}).get("trend"),
            staleness=(card or {}).get("staleness")
            or staleness(None, entry.get("retest_interval_months")),
            guidance=_metric_guidance(entry),
            panel=panel_card,
            siblings=siblings,
            measure=measure,
            export_url=f"/metrics/{concept_id}/export",
            chart_band=chart_band,
            correlation=correlation,
            concept_name=concept_display_name(concept["canonical_name"]),
            ai_scope_label=(card["name"] if card else concept_display_name(concept["canonical_name"])),
            area=_metric_area(concept["category"]),
            active="metrics"
        ),
    )

# --- devices ------------------------------------------------------------

def _device_event_url(event) -> str:
    """An ECG opens its own trace; any other event opens its source document, if any."""
    if event["event_type"] == "Electrocardiogram":
        return f"/devices/ecg/{event['id']}"
    return f"/documents/{event['document_id']}" if event["document_id"] else ""

def _core_cards(core: list[dict[str, object]], catalog: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    """The judged catalog card behind each core device metric, once each.

    A same-measurement twin (weight, blood pressure, ECG heart rate) is not a
    device card of its own: it is read on its concept's card, which folds the
    device's readings in.  A metric the catalog does not list is left out
    rather than drawn from the unjudged overview row."""
    cards: dict[str, dict[str, object]] = {}
    for item in core:
        key = str(item["id"]).removeprefix(_DEVICE_METRIC_PREFIX)
        card = catalog.get(TWIN_OF_DEVICE[key][0]) if key in SAME_DEVICE_KEYS else catalog.get(str(item["id"]))
        if card is not None:
            cards.setdefault(str(card["id"]), card)
    return list(cards.values())


@router.get(_DEVICES_URL, response_class=HTMLResponse, responses=_RESPONSES_401)
def devices_page(request: Request):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    # A visit can queue a due check; the lifespan worker also schedules
    # checks independently. A queue failure must not hide existing data.
    try:
        openwearables.maybe_refresh(settings, user["id"])
    except Exception:  # noqa: BLE001
        openwearables.logger.warning("openwearables: refresh check failed", exc_info=True)
    with connect(settings) as connection:
        overview = dict(_device_overview(connection, user["id"]))
        catalog = _by_id(_metric_catalog(connection, user["id"]))
    overview["core_metrics"] = _core_cards(overview["core_metrics"], catalog)
    vendors = _visible_vendors(settings, overview["vendors"])
    overview["vendors"] = vendors
    # An electrocardiogram opens on its own waveform; every other event
    # opens the document it came from, when one exists.
    overview["events"] = [
        dict(event, url=_device_event_url(event))
        for event in overview["events"]
    ]
    connected = [vendor for vendor in vendors if vendor["record_count"]]
    counts = overview["counts"]
    # One source for both numbers: "3 connected of 4 supported" can no
    # longer disagree with itself further down the page.
    overview["summary"] = {
        "supported": len(vendors),
        "connected": len(connected),
        "supported_text": format_count(len(vendors)),
        "connected_text": format_count(len(connected)),
        "records_text": format_count(sum(int(vendor["record_count"] or 0) for vendor in vendors)),
        "daily_rows_text": format_count(counts["daily_rows"]),
        "workouts_text": format_count(counts["workouts"]),
        "events_text": format_count(counts["events"]),
        "latest_day_text": format_date(counts["latest_day"]),
    }
    for vendor in vendors:
        vendor["record_count_text"] = format_count(vendor["record_count"])
        vendor["latest_date_text"] = format_date(vendor["latest_date"])
    return templates.TemplateResponse(
        request,
        "devices.html",
        template_context(
            request,
            overview=overview,
            oura_sync=_oura_sync_context(settings, user["id"]),
            openwearables_sync=_openwearables_sync_context(settings, user["id"]),
            active="devices",
        ),
    )

def _chart_columns(rows, unit: str, labels: list[str], names: dict | None = None) -> dict[str, list]:
    """One series as parallel columns at display precision (PERF-03).

    Point objects repeated the unit, vendor and source on every day — 2.7
    MB for ten years of steps.  Columns carry each fact once; the source is
    an index into `labels`; values keep the decimals the page shows.
    """
    index = {label: position for position, label in enumerate(labels)}
    # The comparison's own labels, so a tooltip names a source exactly
    # as its button and card do.
    named: dict[tuple[str, str], str] = dict(names or {})
    columns: dict[str, list] = {"d": [], "v": [], "s": [], "n": [], "lo": [], "hi": []}

    def rounded(value):
        if value is None:
            return None
        number = float(value)
        return round(number, _decimals_for(number, unit) + 1)

    for item in reversed(rows):
        identity = (str(item["source_vendor"]), str(item["source_name"]))
        label = named.get(identity) or named.setdefault(identity, human_source_label(*identity))
        if label not in index:
            index[label] = len(labels)
            labels.append(label)
        columns["d"].append(str(item["day"]))
        columns["v"].append(rounded(item["value"]))
        columns["s"].append(index[label])
        columns["n"].append(int(item["sample_count"] or 0))
        columns["lo"].append(rounded(item["value_min"]))
        columns["hi"].append(rounded(item["value_max"]))
    return columns

def _device_comparison_or_404(connection, owner_user_id: str, metric_key: str) -> dict[str, object]:
    comparison = device_metric_comparison(connection, owner_user_id, metric_key)
    if not comparison or not any(valid_row(row) for source in comparison["sources"] for row in source["rows"]):
        # No reading a body could have produced: nothing to show or judge.
        raise HTTPException(404)
    return comparison

#: Plain-language guidance for device metrics the guidance library does not
#: describe: (short description key, why-it-matters key).
_DEVICE_GUIDANCE_FALLBACKS = {
    "active_minutes": ("device.guidance_active_minutes", "device.guidance_active_minutes_why"),
    "lowest_sleeping_heart_rate": ("device.guidance_sleep_low_hr", "device.guidance_sleep_low_hr_why"),
}

def _device_latest(comparison: dict[str, object], metric_key: str, tz) -> tuple[list, object, object]:
    """(the series rows, today's unfinished total or None, the latest row)."""
    preferred = comparison["preferred"]
    # Today's running total is a day not finished: it is reported as
    # "so far today", never as the latest reading, the trend's newest
    # point or the chart's last value (UX-11, OPS-07).
    partial = preferred[0] if preferred and is_partial_day(metric_key, preferred[0]["day"], tz) else None
    values = [row for row in preferred if row is not partial] or preferred
    latest = values[0] if values else next(
        row for source in comparison["sources"] for row in source["rows"] if valid_row(row)
    )
    if latest is partial:
        partial = None
    return values, partial, latest

def _format_device_day_rows(day_groups: list[dict[str, object]], unit: str | None) -> None:
    # Only the rows on screen are formatted: 40,000 format calls for a
    # 60-row table were a fifth of the page's render time (PERF-03).
    for day in day_groups:
        for row in day["rows"]:
            row["value_text"] = format_quantity(row["value"], unit)
            row["min_text"] = format_quantity(row["value_min"], unit)
            row["max_text"] = format_quantity(row["value_max"], unit)
            row["samples_text"] = format_count(row["sample_count"])
            row["date_text"] = format_date(str(row["day"]))

def _device_chart_payload(
    comparison: dict[str, object], values: list, partial, unit: str | None, metric_key: str,
) -> tuple[list, dict[str, object]]:
    """(the complete series without today's partial total, the chart JSON payload)."""
    labels: list[str] = []
    series = [row for row in values if row is not partial]
    since = (date.fromisoformat(str(series[0]["day"])[:10]) - timedelta(days=DEVICE_INLINE_DAYS)).isoformat() if series else ""
    inline = [row for row in series if str(row["day"]) >= since]
    chart_payload = {
        "unit": unit,
        "labels": labels,
        # Inline: the last year of the selected series.  The rest of it,
        # and each source's own series, load when first asked for.
        "combined": _chart_columns(inline, unit, labels, {
            (source["vendor"], source["name"]): source["label"] for source in comparison["sources"]}),
        "complete": len(inline) == len(series),
        "full_url": f"/api/devices/metrics/{metric_key}/source/combined",
        "sources": [
            {"id": source["source_key"], "label": source["label"],
             "url": f"/api/devices/metrics/{metric_key}/source/{source['source_key']}"}
            for source in comparison["sources"]
        ],
    }
    return series, chart_payload

def _device_guidance(entry: dict[str, object], metric_key: str) -> dict[str, object]:
    guidance = _metric_guidance(entry)
    if guidance["short_description"]:
        return guidance
    if metric_key in PROVIDER_SCORE_KEYS:
        keys = ("device.guidance_provider_score", "device.guidance_provider_score_why")
    else:
        keys = _DEVICE_GUIDANCE_FALLBACKS.get(metric_key)
    if keys:
        guidance.update(short_description=t(keys[0]), why_it_matters=t(keys[1]))
    return guidance

def _device_twin_link(connection, owner_user_id: str, metric_key: str) -> dict[str, object] | None:
    """Where a device metric's twin concept is read, and the panel it is filed
    in: the other half of the mutual link `_twin_links` makes."""
    concept_id, relation = TWIN_OF_DEVICE.get(metric_key, (None, None))
    panel_id, panel_name = _panel_reference(_DEVICE_PANEL_BY_METRIC.get(metric_key))
    concept = connection.execute(
        "SELECT canonical_name FROM concepts WHERE id=?", (concept_id,)
    ).fetchone() if concept_id else None
    # The concept page exists when it has something to show: a same twin is
    # always on it; a method or related twin only beside clinic readings.
    reachable = concept is not None and (
        relation == "same" or bool(_deduped_observation_rows(connection, owner_user_id, concept_id))
    )
    if not reachable and panel_id is None:
        return None
    return {
        "relation": relation if reachable else None,
        "concept_url": f"/metrics/{concept_id}" if reachable else None,
        "concept_name": concept_display_name(str(concept["canonical_name"])) if reachable else None,
        "why": t(f"twin.why_{metric_key}") if reachable else None,
        "panel_url": f"/panels/{panel_id}" if panel_id else None,
        "panel_name": panel_name,
    }


def _excludable_sources(connection, owner_user_id: str) -> set[str]:
    """Stored source names a "not my reading" rule can reach: OpenWearables
    sources that name their app, and file exports."""
    names = set()
    for name, adapter in connection.execute(
        """SELECT DISTINCT d.source_name, i.adapter_key FROM device_metric_days d
           JOIN device_imports i ON i.id=d.import_id WHERE d.owner_user_id=?""", (owner_user_id,)):
        if adapter in device_exclusions.ADAPTERS or (
                adapter == openwearables.ADAPTER_KEY and device_exclusions.origin_from_label(name)):
            names.add(name)
    return names


def _review_url(metric_key: str, day: str, source_name: str) -> str:
    return "/devices/readings?" + urlencode({"metric": metric_key, "day": day, "source": source_name})


def _exclusion_context(connection, owner_user_id: str, metric_key: str, comparison, unit, own: bool) -> dict:
    """The page's "not my reading" affordances: a review link per row, the
    readings far from the person's usual values, and how many rules apply."""
    names = _excludable_sources(connection, owner_user_id) if own else set()
    labels = {(source["vendor"], source["name"]): source["label"] for source in comparison["sources"]}

    def review_url(row) -> str:
        name = str(row["source_name"])
        return _review_url(metric_key, str(row["day"]), name) if name in names else ""

    rows = [row for source in comparison["sources"] for row in source["rows"]]
    typical = device_exclusions.usual([float(row["value"]) for row in rows if row["value"] is not None])
    suggestions = [
        {"day": str(row["day"]), "value_text": format_measurement(row["value"], unit),
         "source_label": labels.get((row["source_vendor"], row["source_name"]), row["source_name"]),
         "url": review_url(row)}
        for row in sorted(rows, key=lambda item: str(item["day"]), reverse=True)
        if device_exclusions.far_from_usual(metric_key, row["value"], typical) and review_url(row)
    ][:10]
    return {
        "review_url": review_url,
        "suggestions": suggestions,
        "typical_text": format_measurement(typical, unit) if typical is not None else "",
        "active": device_exclusions.affecting(connection, owner_user_id, metric_key),
        "own": own,
    }


@router.get("/devices/metrics/{metric_key}", response_class=HTMLResponse, responses=_RESPONSES_401_404)
def device_metric_detail(request: Request, metric_key: str, offset: int = 0):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    offset = max(0, offset)
    with connect(settings) as connection:
        comparison = _device_comparison_or_404(connection, user["id"], metric_key)
        tz = user_timezone(connection, user["id"])
        values, partial, latest = _device_latest(comparison, metric_key, tz)
        age, sex = _demographics(connection, user["id"])
        entry = _guidance_index(connection).get(metric_key) or {}
        correlation = _correlation_context(connection, user["id"], f"device:{metric_key}")
        twin = _device_twin_link(connection, user["id"], metric_key)
        unit = display_unit(str(latest["unit"]) if latest["unit"] else None)
        verdict = evaluate(
            connection,
            concept_id=metric_key,
            value_numeric=latest["value"],
            unit=str(latest["unit"] or ""),
            age_years=age,
            sex=sex,
        )
        can_manage = viewing_row(request) is None and current_user(request).get("token_kind") != "guest"
        exclusion = _exclusion_context(connection, user["id"], metric_key, comparison, unit, can_manage)
    freshness = _device_staleness(
        latest["day"], entry, interpretation=str(verdict["interpretation"]), age_years=age,
        daily=_arrives_daily([day["day"] for day in comparison["days"][:90]]),
    )
    day_groups = comparison["days"][offset : offset + DEVICE_ROW_PAGE_SIZE]
    _format_device_day_rows(day_groups, unit)
    for day in day_groups:
        for row in day["rows"]:
            row["review_url"] = exclusion["review_url"](row)
    latest = dict(latest)
    latest["value_text"] = format_quantity(latest["value"], unit)
    series, chart_payload = _device_chart_payload(comparison, values, partial, unit, metric_key)
    chart_band = _chart_band(verdict)
    trend = (
        _trend(
            float(latest["value"]),
            float(values[1]["value"]),
            unit,
            str(values[1]["day"]),
        )
        if len(values) > 1
        else None
    )
    base = f"/devices/metrics/{metric_key}"
    guidance = _device_guidance(entry, metric_key)
    total_days = len(comparison["days"])
    return templates.TemplateResponse(
        request,
        "device_metric_detail.html",
        template_context(
            request,
            values=values,
            comparison=comparison,
            can_manage_sources=can_manage,
            exclusion=exclusion,
            day_groups=day_groups,
            latest=latest,
            latest_text=format_measurement(latest["value"], unit),
            latest_source_label=human_source_label(str(latest["source_vendor"]), str(latest["source_name"])),
            partial_text=f"{format_quantity(partial['value'], unit)} {unit}".strip() if partial else "",
            unit=unit,
            verdict=verdict,
            blocked_notice=_blocked_notice(verdict),
            trend=trend,
            staleness=freshness,
            chart_band=chart_band,
            chart_available=len(series) > 1 or any(int(source["day_count"]) > 1 for source in comparison["sources"]),
            correlation=correlation,
            guidance=guidance,
            twin=twin,
            # A three-year daily series opens on the last year, not on "All".
            chart_default_range="1y",
            chart_payload=chart_payload,
            page=_pagination(total_days, offset, DEVICE_ROW_PAGE_SIZE, base),
            total_days=total_days,
            total_days_text=format_count(total_days),
            export_url=f"/devices/metrics/{metric_key}/export",
            ai_scope_label=translate_phrase(str(latest["metric_name"])),
            active="devices",
        ),
    )

@router.get("/api/devices/metrics/{metric_key}/source/{source_id}", responses=_RESPONSES_401_404)
def device_metric_source_series(request: Request, metric_key: str, source_id: str):
    """One source's full daily series, fetched when its chart button is
    first pressed (PERF-03).  Same columns as the page's inline series."""
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        comparison = _device_comparison_or_404(connection, user["id"], metric_key)
    if source_id == "combined":
        # The whole selected series, without today's unfinished total.
        with connect(settings) as connection:
            tz = user_timezone(connection, user["id"])
        rows = [row for row in comparison["preferred"] if not is_partial_day(metric_key, row["day"], tz)]
    else:
        source = next((item for item in comparison["sources"] if item["source_key"] == source_id), None)
        if source is None:
            raise HTTPException(404)
        rows = [row for row in source["rows"] if valid_row(row)]
    if not rows:
        raise HTTPException(404)
    unit = display_unit(str(rows[0]["unit"]) if rows[0]["unit"] else None)
    labels: list[str] = []
    names = {(item["vendor"], item["name"]): item["label"] for item in comparison["sources"]}
    return JSONResponse({"unit": unit, "labels": labels, "points": _chart_columns(rows, unit, labels, names)})

@router.post("/devices/source-preference", responses=_RESPONSES_400_401_403)
def device_source_preference(
    request: Request,
    metric_key: Annotated[str, Form()],
    source_key_value: Annotated[str, Form(alias="source_key")] = "",
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    if user.get("token_kind") == "guest" or viewing_row(request) is not None:
        raise HTTPException(403)
    with connect(settings) as connection:
        keys = sorted(SLEEP_FAMILY) if metric_key in SLEEP_FAMILY else [metric_key]
        rows = connection.execute(
            f"SELECT DISTINCT source_vendor, source_name FROM device_metric_days WHERE owner_user_id=? AND metric_key IN ({','.join('?' for _ in keys)})",
            (user["id"], *keys),
        ).fetchall()
        if not rows or (source_key_value and source_key_value not in {source_key(row) for row in rows}):
            raise HTTPException(400, t("source_policy.invalid"))
        group = preference_group(metric_key)
        if source_key_value:
            connection.execute(
                """INSERT INTO device_source_preferences(owner_user_id, preference_group, source_key, updated_at) VALUES (?,?,?,?)
                       ON CONFLICT(owner_user_id, preference_group) DO UPDATE SET source_key=excluded.source_key, updated_at=excluded.updated_at""",
                (user["id"], group, source_key_value, utc_now()),
            )
        else:
            connection.execute("DELETE FROM device_source_preferences WHERE owner_user_id=? AND preference_group=?", (user["id"], group))
        connection.execute(
            "INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at) VALUES (?,?,?,?,?,?,?)",
            (user["id"], user["id"], "device_source_preference_changed", "device_source_preferences", group,
             json.dumps({"source_key": source_key_value or None}), utc_now()),
        )
    invalidate_catalog(user["id"])
    return RedirectResponse(_safe_next(next, f"/devices/metrics/{metric_key}"), status_code=303)

# --- "not my reading" -----------------------------------------------------------

def _own_record_only(request: Request, user) -> None:
    """A rule changes the record it is made in: the owner's own session or
    credential only, never a guest or the viewer of a shared record."""
    if user.get("token_kind") == "guest" or viewing_row(request) is not None:
        raise HTTPException(403, t("exclusions.err_shared"))

def _metric_names(connection, owner_user_id: str) -> dict[str, tuple[str, str]]:
    names = {key: (definition.name, definition.unit) for key, definition in openwearables.DEFS.items()}
    for key, name, unit in connection.execute(
        "SELECT metric_key, MAX(metric_name), MAX(unit) FROM device_metric_days WHERE owner_user_id=? GROUP BY metric_key",
        (owner_user_id,)):
        names[str(key)] = (str(name), str(unit or ""))
    names[device_exclusions.WORKOUTS] = (t("exclusions.series_workouts"), "")
    names[device_exclusions.EVENTS] = (t("exclusions.series_events"), "")
    return names

def _local_time_text(moment: datetime, tz) -> str:
    local = moment.astimezone(tz)
    return f"{format_date(local.date().isoformat())} {local:%H:%M}"

def _local_input(moment: datetime, tz) -> str:
    return moment.astimezone(tz).strftime("%Y-%m-%dT%H:%M")

def _reading_items(found: dict, metric: str, names: dict, typical) -> list[dict]:
    items = []
    for item in found["items"]:
        unit = display_unit(names.get(metric, ("", ""))[1])
        items.append({
            "instant": item["instant"],
            "value_text": format_measurement(item["value"], unit),
            "far": device_exclusions.far_from_usual(metric, item["value"], typical),
            "excluded": item["excluded"],
            "companions": [
                {"name": translate_phrase(names.get(key, (key, ""))[0]),
                 "value_text": format_measurement(value, display_unit(names.get(key, ("", ""))[1]))}
                for key, value in sorted(item["series"].items())
            ],
            "moment": item["moment"],
        })
    return items

@router.get("/devices/readings", response_class=HTMLResponse, responses=_RESPONSES_401_403_404)
def device_readings(request: Request, metric: str = "", day: str = "", source: str = ""):
    """One stored day of one source, opened into the readings behind it, with
    the ways to say they are not this person's."""
    settings = request.app.state.settings
    user = require_user(request)
    _own_record_only(request, user)
    day = _validated_date(day, "exclusions.err_time", required=True)
    with connect(settings) as connection:
        if source not in _excludable_sources(connection, user["id"]):
            raise HTTPException(404)
        names = _metric_names(connection, user["id"])
        stored = connection.execute(
            "SELECT * FROM device_metric_days WHERE owner_user_id=? AND metric_key=? AND source_name=? AND day=?",
            (user["id"], metric, source, day)).fetchone()
        if metric not in names:
            raise HTTPException(404)
        tz = user_timezone(connection, user["id"])
        found = device_exclusions.readings(connection, user["id"], source, metric, day, tz)
        typical = device_exclusions.usual([float(row[0]) for row in connection.execute(
            "SELECT value FROM device_metric_days WHERE owner_user_id=? AND metric_key=? AND value IS NOT NULL",
            (user["id"], metric))])
        source_keys = [str(row[0]) for row in connection.execute(
            "SELECT DISTINCT metric_key FROM device_metric_days WHERE owner_user_id=? AND source_name=? ORDER BY metric_key",
            (user["id"], source))]
        people = device_exclusions.connected_people(connection, user["id"])
        vendor = str(stored["source_vendor"]) if stored else ""
    if found["origin"] is None:
        raise HTTPException(404)
    unit = display_unit(names[metric][1])
    items = _reading_items(found, metric, names, typical)
    for item in items:
        item["time_text"] = _local_time_text(item.pop("moment"), tz)
    if found["kind"] == "file":
        low, high = device_exclusions.local_bounds_utc(day, day, tz)
        day_bounds = (low, device_exclusions.utc_text(datetime.fromisoformat(high) - timedelta(microseconds=1)))
    else:
        # A summary the server dated itself is a UTC day; its own bounds,
        # so the neighbouring days' totals are left alone.
        day_bounds = (f"{day}T00:00:00+00:00", f"{day}T23:59:59.999999+00:00")
    provider, app_name, device = found["origin"]
    return templates.TemplateResponse(
        request,
        "device_readings.html",
        template_context(
            request,
            metric_key=metric,
            metric_name=translate_phrase(names[metric][0]),
            day=day,
            source=source,
            source_label=human_source_label(vendor or openwearables.SOURCE_NAME, source),
            origin={"provider": provider, "source": app_name, "device": device},
            kind=found["kind"],
            items=items,
            stored_text=format_measurement(stored["value"], unit) if stored else "",
            typical_text=format_measurement(typical, unit) if typical is not None else "",
            day_bounds=day_bounds,
            window_from=f"{day}T00:00",
            window_until=f"{day}T23:59",
            series_options=[{"key": key, "name": translate_phrase(names.get(key, (key, ""))[0])} for key in source_keys],
            people=people,
            back_url=f"/devices/metrics/{metric}",
            here=_review_url(metric, day, source),
            active="devices",
        ),
    )

@router.post("/devices/exclusions", responses=_RESPONSES_400_401_403)
def device_exclusion_create(
    request: Request,
    scope: Annotated[str, Form()],
    origin_provider: Annotated[str, Form()],
    origin_source: Annotated[str, Form()],
    origin_device: Annotated[str, Form()] = "",
    from_utc: Annotated[str, Form()] = "",
    until_utc: Annotated[str, Form()] = "",
    series: Annotated[list[str] | None, Form()] = None,
    belongs_to: Annotated[str, Form()] = "",
    reason: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
):
    """Mark a reading, a period or a source as not this person's.

    ``from_utc``/``until_utc`` take an ISO instant; one without an offset (the
    page's own date-and-time fields) is the person's wall-clock time.
    """
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    _own_record_only(request, user)
    try:
        device_exclusions.create(
            settings, user["id"], user["id"], provider=origin_provider, source=origin_source,
            device=origin_device, scope=scope, from_text=from_utc, until_text=until_utc,
            series=series or [], belongs_to=belongs_to, reason=reason)
    except device_exclusions.ExclusionError as exc:
        raise HTTPException(400, t(exc.code)) from None
    state = device_exclusions.settle(settings, user["id"])
    invalidate_catalog(user["id"])
    query = urlencode({"status": state, "next": _safe_next(next, _DEVICES_URL)})
    return RedirectResponse(f"/devices/exclusions?{query}", status_code=303)

@router.post("/devices/exclusions/{exclusion_id}/undo", responses=_RESPONSES_400_401_403_404)
def device_exclusion_undo(
    request: Request,
    exclusion_id: str,
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    _own_record_only(request, user)
    if not device_exclusions.undo(settings, user["id"], user["id"], exclusion_id):
        raise HTTPException(404)
    state = device_exclusions.settle(settings, user["id"])
    invalidate_catalog(user["id"])
    query = urlencode({"status": "undone" if state != "queued" else "undo_queued", "next": _safe_next(next, _DEVICES_URL)})
    return RedirectResponse(f"/devices/exclusions?{query}", status_code=303)

def _exclusion_row(row, names: dict, tz) -> dict:
    series = json.loads(row["series"]) if row["series"] else []
    when = ""
    if row["scope"] == "reading":
        when = _local_time_text(datetime.fromisoformat(row["from_utc"]), tz)
    elif row["scope"] == "window":
        when = t("exclusions.when_window", start=_local_time_text(datetime.fromisoformat(row["from_utc"]), tz),
                 end=_local_time_text(datetime.fromisoformat(row["until_utc"]), tz))
    if row["revoked_at"]:
        state = "undoing"
    else:
        state = "applied" if row["applied_at"] else "pending"
    return {
        "id": row["id"], "scope": row["scope"], "when": when,
        "app": row["origin_source"], "device": row["origin_device"], "provider": row["origin_provider"],
        "series": [translate_phrase(names.get(key, (key, ""))[0]) for key in series],
        "belongs_to": row["belongs_to_name"] or "", "reason": row["reason"],
        "created_text": format_date(str(row["created_at"])[:10]), "state": state,
    }

@router.get("/devices/exclusions", response_class=HTMLResponse, responses=_RESPONSES_401_403)
def device_exclusions_page(request: Request, status: str = "", next: str = ""):
    settings = request.app.state.settings
    user = require_user(request)
    _own_record_only(request, user)
    with connect(settings) as connection:
        rows = device_exclusions.listed(connection, user["id"])
        names = _metric_names(connection, user["id"])
        tz = user_timezone(connection, user["id"])
    items = [_exclusion_row(row, names, tz) for row in rows]
    if any(item["state"] != "applied" for item in items):
        # A recalculation cut short by a restart resumes on the next visit.
        device_exclusions._spawn(f"exclusions-{user['id']}", device_exclusions.run_pending, settings, user["id"])
    back = _safe_next(next, _DEVICES_URL)
    return templates.TemplateResponse(
        request,
        "device_exclusions.html",
        template_context(
            request,
            items=[item for item in items if item["state"] != "undoing"],
            undoing=[item for item in items if item["state"] == "undoing"],
            status=status if status in ("applied", "queued", "undone", "undo_queued", "idle") else "",
            back_url=back,
            here=request.url.path + ("?" + urlencode({"next": back}) if back != _DEVICES_URL else ""),
            active="devices",
        ),
    )

@router.get("/devices/ecg", response_class=HTMLResponse, responses=_RESPONSES_401)
def ecg_index(request: Request):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        rows = _ecg_rows(connection, user["id"])
    if rows:
        return RedirectResponse(f"/devices/ecg/{rows[0]['id']}", status_code=303)
    return templates.TemplateResponse(
        request,
        "ecg_detail.html",
        template_context(request, recording=None, recordings=[], active="devices"),
    )

def _ecg_trace(source, lead: str):
    """(recording or None, its lead names, the lead shown, its measurement)."""
    # The waveform is read from the file on demand rather than stored: the
    # samples are the source, and re-reading them keeps the page honest if
    # the file is ever replaced.  A file that has moved away, or that never
    # carried a recoverable trace, degrades to the header the import saved.
    recording = read_ecg(source) if source.is_file() else None
    if not recording:
        return recording, [], "", {}
    available = list(recording.leads)
    chosen = lead if lead in available else recording.primary_lead
    return recording, available, chosen, measure_ecg(recording, chosen)

def _ecg_calibration(recording) -> dict[str, str]:
    keys = ("scale", "filter", "symptoms", "sample_rate", "duration", "samples")
    if not recording:
        return dict.fromkeys(keys, "")
    return dict(zip(keys, (
        recording.scale_text,
        recording.filter_text,
        recording.symptoms,
        format_quantity(recording.sample_rate, "Hz"),
        format_quantity(recording.duration_seconds, "s"),
        format_count(recording.sample_count),
    )))

@router.get("/devices/ecg/{event_id}", response_class=HTMLResponse, responses=_RESPONSES_401_404)
def ecg_detail(request: Request, event_id: str, lead: str = ""):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        rows = _ecg_rows(connection, user["id"])
    position = next((index for index, row in enumerate(rows) if str(row["id"]) == event_id), None)
    if position is None:
        raise HTTPException(404)
    row = rows[position]
    source = resolve_source_path(settings, str(row["source_file"] or ""))
    recording, available, chosen, measurement = _ecg_trace(source, lead)
    card = _ecg_card(row)
    card["source_missing"] = not source.is_file()
    card["source_name_text"] = source.name
    return templates.TemplateResponse(
        request,
        "ecg_detail.html",
        template_context(
            request,
            recording=card,
            measurement=_ecg_measurement(measurement) if measurement else None,
            leads=[
                {"name": name, "url": f"/devices/ecg/{event_id}?lead={name}", "active": name == chosen}
                for name in available
            ],
            strip=strip_rows(recording) if recording else [],
            calibration=_ecg_calibration(recording),
            recordings=[_ecg_card(item) for item in rows],
            previous=_ecg_card(rows[position + 1]) if position + 1 < len(rows) else None,
            following=_ecg_card(rows[position - 1]) if position else None,
            position_text=t("ecg.position", index=position + 1, total=len(rows)),
            active="devices",
        ),
    )

@router.get("/api/metrics/{concept_id}", responses=_RESPONSES_401_404)
def metric_json(request: Request, concept_id: str):
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    with connect(settings) as connection:
        concept = connection.execute(
            "SELECT preferred_unit FROM concepts WHERE id=?", (concept_id,)
        ).fetchone()
        if not concept:
            raise HTTPException(404)
        rows = _linked_observation_rows(connection, user["id"], concept_id)
        patient = _patient_row(connection, user["id"])
        return _chart_payload(
            rows, concept["preferred_unit"],
            date_of_birth=patient["date_of_birth"] if patient else None,
            sex=patient["sex_at_birth"] if patient else None,
            connection=connection,
        )

@router.get("/api/correlation", responses=_RESPONSES_400_401_404)
def correlation_json(
    request: Request,
    a: str,
    b: Annotated[list[str], Query(alias="b")],
    align: str = "same_day",
    range_key: Annotated[str, Query(alias="range")] = "all",
):
    """How this owner's measurements move together — one against up to four.

    Owner-scoped like every other read: `a` and every `b` are resolved
    against this account's own series, so an id belonging to somebody else
    is a 404 rather than a leak.  Too little overlap is a 200 carrying
    `insufficient` on that companion, because "four days is not enough to
    put a number on" is an answer the page renders beside a chart it can
    still draw, not an error and not a blank frame.
    """
    settings = request.app.state.settings
    user = require_user(request)
    user = record_user(request, user)
    if align not in CORRELATION_ALIGNMENTS or range_key not in CORRELATION_RANGES:
        raise HTTPException(400, "unsupported alignment or range")
    if not 1 <= len(b) <= CORRELATION_MAX_COMPANIONS:
        raise HTTPException(400, f"between 1 and {CORRELATION_MAX_COMPANIONS} companions")
    if len(set(b)) != len(b):
        # Silently collapsing them would report fewer series than the page
        # asked for, which reads as a metric having gone missing.
        raise HTTPException(400, "companions must be distinct")
    if a in b:
        # A series against itself is r=1.0 by construction — a fabricated
        # "very strong" association in the shape of a real finding.
        raise HTTPException(400, "a companion must differ from the primary")
    with connect(settings) as connection:
        primary = _correlation_metric(connection, user["id"], a)
        if primary is None:
            raise HTTPException(404)
        companions = []
        for companion_id in b:
            companion = _correlation_metric(connection, user["id"], companion_id)
            if companion is None:
                raise HTTPException(404)
            companions.append((companion_id, companion))
        return _correlation_payload(a, primary, companions, align, range_key)

# --- review -------------------------------------------------------------

#: The task states a file-level review action may start from.
_REVIEW_ACTION_FROM_STATES = {
    "reopen": ("resolved", "needs_correction"),
    "verify": ("open",),
    "needs_correction": ("open",),
}

@router.post("/documents/{document_id}/review", responses=_RESPONSES_400_401_403_404)
def resolve_document_review(
    request: Request,
    document_id: str,
    action: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
):
    """Apply a file-level review decision from the document detail page."""
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    allowed_states = _REVIEW_ACTION_FROM_STATES.get(action, ())
    if not allowed_states:
        raise HTTPException(400)
    with connect(settings) as connection:
        task = connection.execute(
            f"""SELECT id FROM review_tasks WHERE owner_user_id=? AND entity_type='document'
                      AND entity_id=? AND state IN ({','.join('?' * len(allowed_states))})
                      ORDER BY created_at DESC LIMIT 1""",
            (user["id"], document_id, *allowed_states),
        ).fetchone()
    if not task:
        raise HTTPException(404)
    return resolve_review(
        request,
        str(task["id"]),
        action,
        csrf_token,
        next or f"/documents/{document_id}",
    )

@router.get("/review", response_class=HTMLResponse, responses=_RESPONSES_401_404)
def review(request: Request, state: str = "open", document: str = ""):
    user = require_user(request)
    # Reached by URL while a shared record is open, this used to show the
    # reader their OWN queue under a banner announcing someone else's
    # record, with every control disabled on data that was actually
    # theirs.  It reads the record the rest of the header claims; the
    # write routes still use the session user, so nothing can be changed.
    user = record_user(request, user)
    if state not in REVIEW_STATES:
        raise HTTPException(404)
    # The former review workspace duplicated the document source, value
    # editors and classification form. Keep old bookmarks useful while the
    # document list and detail page become the only active UI.
    if document:
        return RedirectResponse(f"/documents/{document}", status_code=302)
    return RedirectResponse(f"/documents?review_state={state}", status_code=302)

def _apply_review_action(connection, user_id: str, entity_type: str, entity_id: str, action: str, allowed) -> None:
    """One file's (or entity's) tasks moved, and what the decision means for its rows."""
    resolutions = {"verify": "resolved", "needs_correction": "needs_correction", "reopen": "open"}
    connection.execute(
        f"""UPDATE review_tasks SET state=?, resolution=?, assigned_user_id=?, resolved_at=?
                WHERE owner_user_id=? AND entity_type=? AND entity_id=?
                  AND state IN ({",".join("?" * len(allowed))})""",
        (
            resolutions[action],
            None if action == "reopen" else action,
            user_id,
            None if action == "reopen" else utc_now(),
            user_id,
            entity_type,
            entity_id,
            *allowed,
        ),
    )
    if action == "verify" and entity_type == "document":
        # Only the values nobody has ruled on move: a correction and a
        # set-aside are decisions a bulk verification must not overwrite.
        connection.execute(
            """UPDATE observations SET verification_status='verified'
                   WHERE document_id=? AND owner_user_id=? AND verification_status='extracted'""",
            (entity_id, user_id),
        )
        # A visit note's doses are part of what the file says, so
        # confirming the file confirms them the way it confirms values.
        connection.execute(
            """UPDATE immunizations SET verification_status='verified', entered_by_user_id=?, updated_at=?
                   WHERE document_id=? AND owner_user_id=? AND verification_status='extracted'""",
            (user_id, utc_now(), entity_id, user_id),
        )
        # And its narrative findings: nothing else ever marks one
        # checked, so a confirmed report kept its findings provisional
        # and `sync_clinical_findings` rebuilt them on every start.
        connection.execute(
            """UPDATE clinical_findings SET verification_status='verified'
                   WHERE document_id=? AND owner_user_id=? AND verification_status='extracted'""",
            (entity_id, user_id),
        )
        connection.execute(
            "UPDATE document_pages SET review_status='verified' WHERE document_id=?",
            (entity_id,),
        )
    elif action == "reopen" and entity_type == "document":
        connection.execute(
            """UPDATE observations SET verification_status='extracted'
                   WHERE document_id=? AND owner_user_id=? AND verification_status='verified'""",
            (entity_id, user_id),
        )
        connection.execute(
            """UPDATE clinical_findings SET verification_status='extracted'
                   WHERE document_id=? AND owner_user_id=? AND verification_status='verified'""",
            (entity_id, user_id),
        )
        connection.execute(
            "UPDATE document_pages SET review_status='not_reviewed' WHERE document_id=?",
            (entity_id,),
        )
    connection.execute(
        """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, user_id, f"review_{action}", entity_type, entity_id, "{}", utc_now()),
    )
    if entity_type == "document":
        recount_review_tasks(connection, user_id, entity_id, user_id)

@router.post("/review/{task_id}", responses=_RESPONSES_400_401_403_404)
def resolve_review(
    request: Request,
    task_id: str,
    action: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
):
    settings = request.app.state.settings
    user = require_user(request)
    require_csrf(user, csrf_token)
    resolutions = {"verify": "resolved", "needs_correction": "needs_correction", "reopen": "open"}
    if action not in resolutions:
        raise HTTPException(400)
    # Reopening is the whole point of keeping the resolved and correction
    # queues browsable: a decision made in a hurry has to be reversible
    # from the page that shows it.  Each action names the states it may act
    # on, so an open task cannot be "reopened" into reverting its own work.
    allowed = ("resolved", "needs_correction") if action == "reopen" else ("open",)
    with connect(settings) as connection:
        task = connection.execute(
            f"""SELECT * FROM review_tasks WHERE id=? AND owner_user_id=?
                    AND state IN ({",".join("?" * len(allowed))})""",
            (task_id, user["id"], *allowed),
        ).fetchone()
        if not task:
            raise HTTPException(404)
        # Every task on this file in the same state, not only the one the
        # button named.  The queue shows one entry per file, so finishing it
        # has to finish the file -- otherwise the entry reappears carrying a
        # sibling task the reader was never shown and cannot tell apart.
        # A file a person linked as part of this report is checked with it,
        # when its own task is in the same state (a part flagged for
        # correction is not verified by checking the report).
        entities = [str(task["entity_id"])]
        if task["entity_type"] == "document":
            entities += [
                part for part in _person_part_ids(connection, user["id"], entities[0])
                if connection.execute(
                    f"""SELECT 1 FROM review_tasks WHERE owner_user_id=? AND entity_type='document' AND entity_id=?
                          AND state IN ({",".join("?" * len(allowed))}) LIMIT 1""",
                    (user["id"], part, *allowed),
                ).fetchone()
            ]
        for entity_id in entities:
            _apply_review_action(connection, user["id"], str(task["entity_type"]), entity_id, action, allowed)
    invalidate_catalog(user["id"])
    # Finishing a file lands on the next one, so a queue of 85 is one
    # continuous pass rather than 85 returns to the top of a list.
    return RedirectResponse(_safe_next(next, "/review"), status_code=303)

# Legal pages are public on purpose: API providers verify a privacy-policy
# URL with an anonymous fetch, so neither route may require a session.
# `shell=True` gives the signed-out render the same page width the
# signed-in chrome gets for free.
@router.get("/healthz", include_in_schema=False)
def healthz(request: Request):
    """Liveness for the container healthcheck: the process answers and the
    database opens.  Public and content-free on purpose."""
    settings = request.app.state.settings
    with connect(settings) as connection:
        connection.execute("SELECT 1").fetchone()
    return PlainTextResponse("ok")

@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return templates.TemplateResponse(
        request, "privacy.html", template_context(request, active="privacy", shell=True)
    )

@router.get("/terms", response_class=HTMLResponse)
def terms(request: Request):
    return templates.TemplateResponse(
        request, "terms.html", template_context(request, active="terms", shell=True)
    )



@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = app.state.settings
    telegram_service = app.state.telegram
    # Set to 0 for a deliberate offline inspection. Production starts the
    # durable workers independently of visits to patient pages.
    workers_enabled = env("BACKGROUND_WORKERS", "1") != "0"
    ow_enabled = workers_enabled and env("OPENWEARABLES_WORKER", "1") != "0"
    ow_worker = ow_hooks.start_worker(settings) if ow_enabled else None
    # Garmin Personal API keys have no push: this re-syncs them and retries
    # Garmin business deliveries that failed to process.
    garmin_stop = garmin_personal.start_scheduler(settings) if workers_enabled else None
    # Oura: webhook events are processed on a timer (not only when the next
    # webhook arrives), and every usable account catches up once a day.
    oura_stop, oura_thread = oura.start_scheduler(settings) if workers_enabled else (None, None)
    if workers_enabled:
        telegram_service.start()
    try:
        yield
    finally:
        if garmin_stop:
            garmin_stop.set()
        if oura_stop:
            oura_stop.set()
            await run_in_threadpool(oura_thread.join, 10)
        await run_in_threadpool(telegram_service.stop)
        if ow_worker:
            await run_in_threadpool(ow_hooks.stop_worker, ow_worker)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()
    migrate(settings)
    with connect(settings) as connection:
        # A fresh clone must arrive complete: curated guidance is seeded here,
        # beside the migration, not only when a document is ingested.
        seed_reference_rules(connection)
        repair_observation_semantics(connection)
        repair_order_identifiers(connection)
        sync_clinical_findings(connection)
        backfill_search_keys(connection)
        repair_text_duplicates(connection)
    # An operator-pinned agent credential, re-created if the row is missing so
    # a restored database or a fresh volume does not silently lock automation
    # out.  Absent unless ANAMNA_AGENT_TOKEN is set.
    ensure_seeded_token(settings, settings.agent_token)
    # A job that was mid-read when the process ended is claimed by a worker that
    # no longer exists, and nothing looks at `running` again.  Recreating the
    # container during a rescan left exactly one of those reading forever.
    reclaim_abandoned_jobs(settings)
    telegram_service = TelegramService(settings)

    app = FastAPI(title="Anamna", docs_url=None, redoc_url=None, lifespan=_lifespan)
    app.state.settings = settings
    app.state.telegram = telegram_service
    # ponytail: the generated code lives in this process's memory, so a
    # multi-worker server would hold one code per worker. Store it hashed in
    # app_settings if this is ever run with more than one worker.
    app.state.setup_code = settings.setup_code or new_setup_code()
    app.state.setup_code_announced = False
    if not has_users(settings):
        announce_setup_code(app)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(router)
    app.middleware('http')(token_scope)
    app.middleware('http')(security_headers)
    app.middleware('http')(locale_middleware)
    app.middleware('http')(derived_values)
    app.add_exception_handler(401, login_redirect)

    register_openwearables_routes(app, settings, require_admin, require_csrf)
    register_telegram_routes(
        app, settings, service=telegram_service, require_user=require_user,
        require_admin=require_admin, require_csrf=require_csrf,
        template_context=template_context, templates=templates,
    )
    register_changes_routes(
        app, settings, templates=templates, template_context=template_context,
        require_user=require_user, require_csrf=require_csrf,
        record_user=record_user, viewing_row=viewing_row,
    )
    register_labsync_routes(
        app, settings, templates=templates, template_context=template_context, require_user=require_user,
        require_admin=require_admin, require_csrf=require_csrf, audit=partial(_audit, settings), invalidate=invalidate_catalog,
    )
    register_testplan_routes(
        app, settings, templates=templates, template_context=template_context, require_user=require_user,
        record_user=record_user, require_csrf=require_csrf, audit=partial(_audit, settings),
    )
    register_chat_routes(
        app, settings, templates=templates, template_context=template_context, require_user=require_user,
        record_user=record_user, require_csrf=require_csrf, viewing_row=viewing_row,
    )
    for register in (register_allergy_routes, register_genetics_routes):
        register(app, settings, templates=templates, template_context=template_context,
                 require_user=require_user, record_user=record_user)
    return app


@lru_cache(maxsize=1)
def _default_app() -> FastAPI:
    load_integration_environment()
    return create_app()


async def app(scope, receive, send) -> None:
    """Initialize the default ledger only when the ASGI server starts using it.

    Importing a formatting helper or constructing an isolated test app must
    never migrate the operator's default database or reclaim its active jobs.
    The existing uvicorn entry point remains compatible with deployments.
    """
    await _default_app()(scope, receive, send)


def run() -> None:
    port = int(os.environ.get("PORT") or 8000)
    uvicorn.run("anamna.web.app:app", host="127.0.0.1", port=port, reload=False)
