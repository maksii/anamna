from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

from ..config import ID_NAMESPACE_PREFIX, Settings, resolve_source_path
from ..db import connect, utc_now
from ..derived import DERIVED_EGFR_METHOD, refresh_derived_observations
from ..health import CONCEPT_UNIT_ALIASES, sync_clinical_findings
from ..i18n import (
    activate_locale,
    format_date_localized,
    format_number_localized,
    reset_locale,
    t,
    t_plural,
    translate_review_reason,
)
from ..immunizations import is_visit_vaccination, parse_immunizations, parse_visit_vaccinations, store_document_doses
from ..reference import _vendor_side, canonical_unit
from .classifier import (
    DISCHARGE_027_TITLE, KNOWN_CLINICAL_TYPES, RESULT_TYPES, UNKNOWN_VENDOR, Classification, classify_document,
    misread_order,
)
from .concepts import (
    CONCEPT_DEFINITIONS,
    NON_ANALYTE_LABELS,
    blood_count_unit,
    clean_label,
    concept_for_alias,
    foreign_categories,
    refine_definition,
    specimen_family,
    stable_concept_id,
)
from .extract import extract_document, file_sha256
from .parsers import (
    PARSED_CLINICAL_TYPES,
    PARSER_VERSION,
    ParsedObservation,
    COMPANION_SUMMARY,
    ParseIssue,
    has_result_header,
    parse_document,
    reference_limits,
    refused_reference,
    scale_interpretation,
    time_of_day_bands,
)
from .positions import store_positions
from .text import collapse_space, combined_page_text, normalized_key, search_key


logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}


class RereadRefused(ValueError):
    """A re-read that would have damaged the record, stopped before it did.

    `detail_key` is the catalogue key the processing queue shows, so the person
    is told why nothing changed rather than "something went wrong".
    """

    def __init__(self, detail_key: str, message: str) -> None:
        super().__init__(message)
        self.detail_key = detail_key


# --- review reasons ----------------------------------------------------------
#
# A review task stores what it asks as catalogue parts, `{"key", "params"}`,
# so it can be said in the reader's language with the right plural form; see
# migration 037.  `reason` keeps an English sentence for readers that predate
# the key.  For the reasons that existed before the key, that sentence is the
# exact one they always wrote, which is also what lets
# `backfill_review_reason_keys` read old rows back apart.

#: Catalogue keys of the review reasons more than one path writes or reads.
REVIEW_VACCINATIONS_N = "review.vaccinations_n"
REVIEW_VERIFY_N = "review.verify_n"
REVIEW_RESCANNED_N = "review.rescanned_n"
REVIEW_FINDINGS = "review.findings"
REVIEW_REREAD_CHANGED_N = "review.reread_changed_n"
REVIEW_REREAD_ORPHANED_N = "review.reread_orphaned_n"
REVIEW_COMPANION_SUMMARY = "review.companion_summary"
#: The catalogue's dash for a missing value.
EM_DASH_KEY = "em.dash"

#: Catalogue key → the English sentence it used to be stored as.
LEGACY_REASONS: dict[str, str] = {
    "review.duplicate": "Confirm this exact duplicate should remain linked to the original document.",
    REVIEW_VACCINATIONS_N: (
        "Check {count} vaccination(s) read from this card against the page, "
        "particularly dates, dose numbers and lot numbers."
    ),
    REVIEW_VERIFY_N: "Verify {count} extracted observation(s) against page evidence before marking trusted.",
    "review.result_not_present": "The order is present but the export contains no result value.",
    "review.image_evidence": "Review image/visual evidence; OCR is not accepted as a clinical fact automatically.",
    "review.narrative": (
        "Review the narrative or visual report; no structured scalar observation was inferred automatically."
    ),
    "review.no_values_found": (
        "Extraction found no values on a report of a kind the parser does read; "
        "check the pages for results it missed."
    ),
    REVIEW_COMPANION_SUMMARY: (
        "An illustrated summary of results the lab issues with a report; its values are read from that report."
    ),
    REVIEW_RESCANNED_N: (
        "Re-read with parser {version}: verify {count} observation(s) the earlier parse did not produce."
    ),
    "review.vanished_n": (
        "{count} observation(s) the earlier parse produced are not in this one, "
        "so check the page to see whether they are really absent."
    ),
    REVIEW_FINDINGS: "Review the narrative or visual findings against page evidence before marking trusted.",
    "review.unfiled_n": (
        "{count} checked observation(s) could not be re-filed: the page they were "
        "read from is no longer in this document, so check where they belong."
    ),
}


def reason_part(key: str, **params: object) -> dict[str, object]:
    return {"key": key, "params": params}


#: `ParseIssue.kind` → the review reason that names it.
ISSUE_REASONS = {
    "unparsed_known_analyte": "review.parse_unread_n",
    "unknown_antibiotic": "review.parse_antibiotic_n",
}


def issue_parts(issues) -> list[dict[str, object]]:
    """One reason part per kind of line the parser recognised and could not read.

    Each lists the lines, so the task says which result to look for on which
    page rather than that something was missed.  Repeats of one printed line
    (native text and its OCR) are listed once.
    """
    grouped: dict[str, list[dict[str, object]]] = {}
    seen: set[tuple[object, ...]] = set()
    for issue in issues or []:
        key = ISSUE_REASONS.get(issue.kind, "review.parse_unread_n")
        marker = (key, issue.page_number, collapse_space(issue.raw_name).casefold())
        if marker in seen:
            continue
        seen.add(marker)
        grouped.setdefault(key, []).append(
            {
                "kind": "issue",
                "label": collapse_space(issue.raw_name),
                "page": issue.page_number,
                "evidence": collapse_space(issue.evidence_text)[:160],
            }
        )
    return [reason_part(key, count=len(items), items=items) for key, items in grouped.items()]


def _reading_text(reading: dict[str, object] | None) -> str:
    """One stored reading, «<0,5 ммоль/л», in the active locale."""
    if not reading:
        return t(EM_DASH_KEY)
    number = reading.get("numeric")
    if number is not None:
        decimals = len(repr(float(number)).partition(".")[2].rstrip("0"))
        printed = str(reading.get("printed") or "")
        if printed and re.fullmatch(r"-?\d+(?:[.,]\d+)?", printed):
            decimals = max(decimals, len(re.split(r"[.,]", printed + ".")[1]))
        text = f"{reading.get('comparator') or ''}{format_number_localized(float(number), min(decimals, 6))}"
    else:
        text = str(reading.get("text") or t(EM_DASH_KEY))
    unit = str(reading.get("unit") or "").strip()
    return f"{text} {unit}" if unit else text


def _render_item(item: dict[str, object]) -> str:
    kind = str(item.get("kind") or "")
    common = {"label": item.get("label") or "", "page": item.get("page") or ""}
    if kind == "changed":
        return t("review.item_changed", old=_reading_text(item.get("old")), new=_reading_text(item.get("new")), **common)
    if kind == "orphaned":
        return t("review.item_orphaned", value=_reading_text(item.get("old")), **common)
    if kind == "issue":
        return t("review.item_issue", evidence=item.get("evidence") or "", **common)
    if kind == "reference":
        return t(
            "review.item_reference",
            old=item.get("old") or t(EM_DASH_KEY),
            new=item.get("new") or t(EM_DASH_KEY),
            **common,
        )
    return str(item.get("label") or "")


def _render_parts(parts: list[dict[str, object]]) -> str:
    rendered = []
    for part in parts:
        key = str(part.get("key") or "")
        params = dict(part.get("params") or {})
        if "items" in params:
            params["items"] = "; ".join(_render_item(item) for item in params["items"] or [])
        for name in ("old_date", "new_date"):
            if name in params:
                params[name] = format_date_localized(params[name])
        if "count" in params:
            count = int(params.pop("count"))
            rendered.append(t_plural(key, count, **params))
        else:
            rendered.append(t(key, **params))
    return " ".join(text for text in rendered if text)


def _reason_parts(row) -> list[dict[str, object]]:
    keys = row.keys() if hasattr(row, "keys") else ()
    payload = row["reason_params_json"] if "reason_params_json" in keys else None
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    if "parts" not in data:
        # A single-part task written as `reason_key` + flat params (labsync's
        # missing-rows task keys its lookups on the flat `order`/`names`).
        key = row["reason_key"] if "reason_key" in keys else None
        return [{"key": key, "params": data}] if key else []
    parts = data.get("parts") or []
    return [part for part in parts if isinstance(part, dict) and part.get("key")]


def review_reason_text(row, locale: str, *, exclude: tuple[str, ...] = ()) -> str:
    """What a review task asks, in `locale`.

    `row` is a `review_tasks` row (sqlite3.Row or dict).  Tasks written with
    catalogue parts render from the catalogue, plural forms included; a row the
    start-up backfill could not read back renders its stored sentence, through
    the old phrase-by-phrase translation, which is the best that row has.
    `exclude` leaves out parts a page shows elsewhere (the re-read proposals).
    """
    token = activate_locale(locale)
    try:
        parts = _reason_parts(row)
        if parts:
            return _render_parts([part for part in parts if part["key"] not in exclude])
        return translate_review_reason(str(row["reason"] or ""))
    finally:
        reset_locale(token)


def _legacy_reason(parts: list[dict[str, object]]) -> str:
    sentences = []
    for part in parts:
        template = LEGACY_REASONS.get(str(part["key"]))
        if template:
            sentences.append(template.format(**dict(part["params"])))
        else:
            token = activate_locale("en")
            try:
                sentences.append(_render_parts([part]))
            finally:
                reset_locale(token)
    return " ".join(sentences)


def open_review_task(
    connection: sqlite3.Connection, owner_user_id: str, document_id: str, parts: list[dict[str, object]]
) -> str:
    task_id = str(uuid.uuid4())
    connection.execute(
        """INSERT INTO review_tasks(
               id, owner_user_id, entity_type, entity_id, reason, reason_key, reason_params_json, created_at
           ) VALUES (?, ?, 'document', ?, ?, ?, ?, ?)""",
        (
            task_id,
            owner_user_id,
            document_id,
            _legacy_reason(parts),
            str(parts[0]["key"]),
            json.dumps({"parts": parts}, ensure_ascii=False),
            utc_now(),
        ),
    )
    return task_id


# --- keeping an open task true ----------------------------------------------
#
# A task is written once, by an import or a re-read, and the record moves on
# under it: values get verified one by one, through the lab cross-check, from
# the row, or a re-read proposal is applied.  «Verify 57 extracted
# observations» under «57 of 57 checked» is the result.  `recount_review_tasks`
# re-derives every countable part from the record, drops what is spent, and
# resolves a task with nothing left to ask -- one helper, called by every path
# that changes a row's state, and on start for the tasks already stored.

#: Parts that only ever reported a refresh from the print; never a question.
REFRESH_ONLY_KEYS = ("review.reread_reference_n", "review.reread_dates_n")
#: Parts whose items each name one checked row awaiting a person's answer.
PROPOSAL_KEYS = (REVIEW_REREAD_CHANGED_N, REVIEW_REREAD_ORPHANED_N)


def _pending_rows(connection: sqlite3.Connection, document_id: str) -> int:
    """Rows of the document still waiting for a person: extracted or corrected."""
    return int(
        connection.execute(
            """SELECT COUNT(*) FROM observations
                WHERE document_id=? AND verification_status IN ('extracted', 'corrected')
                  AND substr(extraction_method, 1, 8) <> 'derived_'""",
            (document_id,),
        ).fetchone()[0]
    )


def _same_stored_reading(row, reading: dict[str, object] | None) -> bool:
    if not reading:
        return False
    if (row["value_numeric"] is None) != (reading.get("numeric") is None):
        return False
    if str(row["comparator"] or "") != str(reading.get("comparator") or ""):
        return False
    if row["value_numeric"] is None:
        return normalized_key(str(row["value_text"] or "")) == normalized_key(str(reading.get("text") or ""))
    return math.isclose(float(row["value_numeric"]), float(reading["numeric"]), rel_tol=1e-9, abs_tol=1e-9)


#: An id-less proposal (written before items carried ids) that fits several
#: rows: a page of Garmin readings has a dozen «Blood pressure category:
#: Нормальний».  Never guessed at -- applying to the wrong reading would
#: rewrite a value nobody asked about.
AMBIGUOUS = object()


def _item_row(connection: sqlite3.Connection, document_id: str, item: dict[str, object]):
    """The checked row a proposal names: by id, or (older tasks) by page, label
    and value when exactly one row fits; `AMBIGUOUS` when several do."""
    if item.get("id"):
        return connection.execute(
            "SELECT * FROM observations WHERE id=? AND document_id=?", (item["id"], document_id)
        ).fetchone()
    fits = [
        row
        for row in connection.execute(
            """SELECT * FROM observations WHERE document_id=? AND page_number=? AND raw_name=?
                 AND verification_status='verified'""",
            (document_id, item.get("page"), item.get("label")),
        )
        if _same_stored_reading(row, item.get("old"))  # type: ignore[arg-type]
    ]
    if len(fits) > 1:
        return AMBIGUOUS
    return fits[0] if fits else None


def _item_id(connection: sqlite3.Connection, document_id: str, item: dict[str, object]) -> str | None:
    row = _item_row(connection, document_id, item)
    return None if row is None or row is AMBIGUOUS else str(row["id"])


def _recounted_parts(connection: sqlite3.Connection, document_id: str, parts: list[dict[str, object]]):
    pending = _pending_rows(connection, document_id)
    doses = int(
        connection.execute(
            "SELECT COUNT(*) FROM immunizations WHERE document_id=? AND verification_status='extracted'",
            (document_id,),
        ).fetchone()[0]
    )
    findings = connection.execute(
        "SELECT 1 FROM clinical_findings WHERE document_id=? AND verification_status='extracted' LIMIT 1",
        (document_id,),
    ).fetchone()
    kept = [_recounted_part(connection, document_id, part, pending, doses, findings) for part in parts]
    return [part for part in kept if part is not None]


def _capped_count(params: dict[str, object], limit: int) -> int:
    params["count"] = min(int(params.get("count") or 0), limit)
    return params["count"]


def _recounted_part(
    connection: sqlite3.Connection, document_id: str, part: dict[str, object], pending: int, doses: int, findings
) -> dict[str, object] | None:
    """One part re-derived from the record; None when it has nothing left to ask."""
    key = str(part.get("key") or "")
    params = dict(part.get("params") or {})
    if key in REFRESH_ONLY_KEYS:
        return None
    if key in (REVIEW_VERIFY_N, REVIEW_RESCANNED_N):
        if not _capped_count(params, pending):
            return None
    elif key == REVIEW_VACCINATIONS_N:
        if not _capped_count(params, doses):
            return None
    elif key == REVIEW_FINDINGS and not findings:
        return None
    elif key in PROPOSAL_KEYS:
        items = _open_proposal_items(connection, document_id, params.get("items") or [])
        if not items:
            return None
        params["items"], params["count"] = items, len(items)
    return {"key": key, "params": params}


def _open_proposal_items(connection: sqlite3.Connection, document_id: str, items) -> list[dict[str, object]]:
    kept = []
    for item in items:
        row = _item_row(connection, document_id, item)
        if row is AMBIGUOUS:
            # Kept as written; a re-read replaces it with one that
            # names its row.
            kept.append(item)
            continue
        # Answered: applied (corrected), set aside (rejected), or
        # changed by hand some other way.  Only a row still standing
        # as checked is still a question.
        if row is None or row["verification_status"] != "verified":
            continue
        # A calculated row (eGFR) was never parser output; an earlier
        # re-read that listed it as "no longer found" was wrong to.
        if is_derived(row["extraction_method"]):
            continue
        kept.append({**item, "id": row["id"]})
    return kept


def _store_task_parts(
    connection: sqlite3.Connection, task, parts: list[dict[str, object]], actor_user_id: str | None, why: str
) -> bool:
    """Write a task's new parts; resolve it, audited, when none are left."""
    if parts == _reason_parts(task):
        return False
    actor = actor_user_id or task["owner_user_id"]
    if not parts:
        connection.execute(
            """UPDATE review_tasks SET state='resolved', resolution='completed', resolved_at=?,
                   reason_params_json=? WHERE id=?""",
            (utc_now(), json.dumps({"parts": []}), task["id"]),
        )
        connection.execute(
            """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id,
                   details_json, created_at)
               VALUES (?, ?, 'review_task_resolved', 'review_task', ?, ?, ?)""",
            (
                task["owner_user_id"], actor, task["id"],
                json.dumps({"document_id": task["entity_id"], "why": why}, ensure_ascii=False),
                utc_now(),
            ),
        )
        return True
    connection.execute(
        "UPDATE review_tasks SET reason=?, reason_key=?, reason_params_json=? WHERE id=?",
        (_legacy_reason(parts), str(parts[0]["key"]), json.dumps({"parts": parts}, ensure_ascii=False), task["id"]),
    )
    return True


def recount_review_tasks(
    connection: sqlite3.Connection, owner_user_id: str, document_id: str, actor_user_id: str | None = None
) -> int:
    """Bring the document's open tasks up to date with its rows. Idempotent."""
    changed = 0
    for task in connection.execute(
        """SELECT * FROM review_tasks WHERE owner_user_id=? AND entity_type='document' AND entity_id=?
             AND state='open'""",
        (owner_user_id, document_id),
    ).fetchall():
        parts = _reason_parts(task)
        if not parts:
            continue
        if _store_task_parts(
            connection, task, _recounted_parts(connection, document_id, parts), actor_user_id, "recount"
        ):
            changed += 1
    return changed


def repair_review_tasks(connection: sqlite3.Connection) -> int:
    """Start-up repair: every open document task recounted (and refresh-only parts dropped)."""
    changed = 0
    for row in connection.execute(
        "SELECT DISTINCT owner_user_id, entity_id FROM review_tasks WHERE entity_type='document' AND state='open'"
    ).fetchall():
        changed += recount_review_tasks(connection, row["owner_user_id"], row["entity_id"])
    return changed


def reread_proposals(connection: sqlite3.Connection, owner_user_id: str, document_id: str) -> dict[str, object]:
    """What the open tasks ask about checked rows, ready to show and to act on."""
    found: dict[str, object] = {"changed": [], "orphaned": []}
    for task in connection.execute(
        """SELECT * FROM review_tasks WHERE owner_user_id=? AND entity_type='document' AND entity_id=?
             AND state='open' ORDER BY created_at""",
        (owner_user_id, document_id),
    ).fetchall():
        for part in _reason_parts(task):
            if part["key"] in PROPOSAL_KEYS:
                bucket = "changed" if part["key"] == REVIEW_REREAD_CHANGED_N else "orphaned"
                found[bucket].extend(  # type: ignore[union-attr]
                    _proposal_views(connection, document_id, part, bucket)
                )
    return found


def _proposal_views(
    connection: sqlite3.Connection, document_id: str, part: dict[str, object], bucket: str
) -> list[dict[str, object]]:
    views = []
    for item in dict(part.get("params") or {}).get("items") or []:
        row = _item_row(connection, document_id, item)
        if (
            row is None or row is AMBIGUOUS
            or row["verification_status"] != "verified" or is_derived(row["extraction_method"])
        ):
            continue
        views.append(
            {
                "id": row["id"],
                "label": item.get("label"),
                "page": item.get("page"),
                "old_text": _reading_text(item.get("old")),
                "new_text": _reading_text(item.get("new")) if bucket == "changed" else "",
                "new": item.get("new"),
            }
        )
    return views


def _audit_observation(connection, owner_user_id, actor_user_id, action, observation_id, details) -> None:
    connection.execute(
        """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id,
               details_json, created_at) VALUES (?, ?, ?, 'observation', ?, ?, ?)""",
        (owner_user_id, actor_user_id, action, observation_id, json.dumps(details, ensure_ascii=False), utc_now()),
    )


def apply_reread_proposals(
    connection: sqlite3.Connection,
    owner_user_id: str,
    document_id: str,
    observation_ids: list[str] | None,
    actor_user_id: str,
    token_kind: str | None = None,
) -> list[str]:
    """Set checked rows to the value the page now reads (all, or `observation_ids`).

    The row takes the re-read's value, comparator, unit and printed precision
    and becomes `corrected`: a person accepted it, and the next re-read pairs
    with it rather than asking again.  The previous reading is in the audit.
    """
    from ..reference import canonical_unit  # noqa: F401  (unit stored as printed)

    applied: list[str] = []
    for proposal in reread_proposals(connection, owner_user_id, document_id)["changed"]:  # type: ignore[union-attr]
        if observation_ids is not None and proposal["id"] not in observation_ids:
            continue
        applied.append(
            _apply_reread_proposal(connection, owner_user_id, document_id, proposal, actor_user_id, token_kind)
        )
    if applied:
        recount_review_tasks(connection, owner_user_id, document_id, actor_user_id)
    return applied


def _apply_reread_proposal(
    connection: sqlite3.Connection,
    owner_user_id: str,
    document_id: str,
    proposal: dict[str, object],
    actor_user_id: str,
    token_kind: str | None,
) -> str:
    row = connection.execute("SELECT * FROM observations WHERE id=?", (proposal["id"],)).fetchone()
    preferred = connection.execute("SELECT preferred_unit FROM concepts WHERE id=?", (row["concept_id"],)).fetchone()
    preferred_unit = preferred["preferred_unit"] if preferred else None
    new = dict(proposal.get("new") or {})
    numeric = new.get("numeric")
    unit = new.get("unit") or row["unit_raw"]
    provisional = ParsedObservation(
        raw_name=row["raw_name"],
        value_numeric=numeric,
        value_text=None if numeric is not None else new.get("text"),
        comparator=new.get("comparator"),
        unit_raw=unit,
        reference_text=row["vendor_reference_text"],
        reference_low=row["vendor_reference_low"],
        reference_high=row["vendor_reference_high"],
        page_number=row["page_number"],
        evidence_text=row["evidence_text"],
        confidence=row["confidence"],
        reference_low_inclusive=bool(row["vendor_reference_low_inclusive"] if row["vendor_reference_low_inclusive"] is not None else 1),
        reference_high_inclusive=bool(row["vendor_reference_high_inclusive"] if row["vendor_reference_high_inclusive"] is not None else 1),
    )
    reading = (
        row["vendor_interpretation"]
        if row["vendor_interpretation_source"] == "lab_record"
        else interpretation(provisional, row["concept_id"])
    )
    connection.execute(
        """UPDATE observations SET value_type=?, value_numeric=?, value_text=?, comparator=?,
               unit_raw=?, unit_canonical=?, value_printed=?, vendor_interpretation=?,
               verification_status='corrected'
           WHERE id=? AND owner_user_id=?""",
        (
            "numeric" if numeric is not None else "text",
            numeric,
            provisional.value_text,
            provisional.comparator,
            unit,
            # Folded exactly as an inserted row is (`insert_observation`):
            # the raw spelling as the canonical unit would start a second
            # trend series and skip every rule written in the folded unit.
            stored_unit(unit, preferred_unit, row["concept_id"]) if numeric is not None else row["unit_canonical"],
            new.get("printed"),
            reading,
            row["id"],
            owner_user_id,
        ),
    )
    _audit_observation(
        connection, owner_user_id, actor_user_id, "observation_reread_applied", row["id"],
        {
            "document_id": document_id,
            "token_kind": token_kind,
            "previous": {
                "value_numeric": row["value_numeric"], "value_text": row["value_text"],
                "comparator": row["comparator"], "unit_raw": row["unit_raw"],
                "value_printed": row["value_printed"], "verification_status": row["verification_status"],
            },
            "applied": new,
        },
    )
    return str(row["id"])


def settle_reread_orphan(
    connection: sqlite3.Connection,
    owner_user_id: str,
    document_id: str,
    observation_id: str,
    keep: bool,
    actor_user_id: str,
    token_kind: str | None = None,
) -> bool:
    """Answer "the re-read no longer finds this checked value": set aside, or keep."""
    proposal = next(
        (item for item in reread_proposals(connection, owner_user_id, document_id)["orphaned"]  # type: ignore[union-attr]
         if item["id"] == observation_id),
        None,
    )
    if proposal is None:
        return False
    if not keep:
        # The same state the row's own "Set aside" sets; the row's Restore undoes it.
        connection.execute(
            "UPDATE observations SET verification_status='rejected' WHERE id=? AND owner_user_id=?",
            (observation_id, owner_user_id),
        )
    _audit_observation(
        connection, owner_user_id, actor_user_id,
        "observation_reread_kept" if keep else "observation_reject", observation_id,
        {"document_id": document_id, "token_kind": token_kind, "previous_state": "verified",
         "reason": "reread_not_found"},
    )
    if keep:
        # Kept rows stay verified, so the recount would keep asking; the
        # answer is taken off the task here.
        for task in connection.execute(
            """SELECT * FROM review_tasks WHERE owner_user_id=? AND entity_type='document' AND entity_id=?
                 AND state='open'""",
            (owner_user_id, document_id),
        ).fetchall():
            parts = _parts_without_orphan(connection, document_id, task, observation_id)
            _store_task_parts(connection, task, parts, actor_user_id, "reread_kept")
    recount_review_tasks(connection, owner_user_id, document_id, actor_user_id)
    return True


def _parts_without_orphan(
    connection: sqlite3.Connection, document_id: str, task, observation_id: str
) -> list[dict[str, object]]:
    parts = []
    for part in _reason_parts(task):
        if part["key"] == REVIEW_REREAD_ORPHANED_N:
            params = dict(part["params"])
            params["items"] = [
                item for item in params.get("items") or []
                if _item_id(connection, document_id, item) != observation_id
            ]
            params["count"] = len(params["items"])
            if not params["items"]:
                continue
            part = {"key": part["key"], "params": params}
        parts.append(part)
    return parts


def _legacy_patterns() -> list[tuple[str, re.Pattern[str]]]:
    patterns = []
    for key, template in LEGACY_REASONS.items():
        expression = re.escape(template)
        expression = expression.replace(re.escape("{count}"), r"(?P<count>\d+)")
        expression = expression.replace(re.escape("{version}"), r"(?P<version>\S+?)")
        # Some writers left the final full stop off.
        expression = expression.removesuffix(re.escape(".")) + r"\.?"
        patterns.append((key, re.compile(expression)))
    return patterns


def parse_legacy_reason(reason: str | None) -> list[dict[str, object]] | None:
    """Read a stored English reason back into catalogue parts, or None."""
    text = collapse_space(reason or "")
    if not text:
        return None
    parts: list[dict[str, object]] = []
    position = 0
    patterns = _legacy_patterns()
    while position < len(text):
        key, match = _first_legacy_match(patterns, text, position)
        if match is None:
            return None
        parts.append(_legacy_part(key, match))
        position = match.end()
        while position < len(text) and text[position] == " ":
            position += 1
    return parts or None


def _first_legacy_match(
    patterns: list[tuple[str, re.Pattern[str]]], text: str, position: int
) -> tuple[str, re.Match[str] | None]:
    for key, pattern in patterns:
        match = pattern.match(text, position)
        if match:
            return key, match
    return "", None


def _legacy_part(key: str, match: re.Match[str]) -> dict[str, object]:
    params: dict[str, object] = {}
    if match.groupdict().get("count") is not None:
        params["count"] = int(match.group("count"))
    if match.groupdict().get("version") is not None:
        params["version"] = match.group("version")
    return reason_part(key, **params)


def backfill_review_reason_keys(connection: sqlite3.Connection) -> int:
    """Give tasks written before migration 037 their catalogue parts.

    Runs on start.  A row whose sentence is not one this file ever wrote gets
    an empty part list, so it is looked at once and renders its stored text.
    """
    rows = connection.execute(
        "SELECT id, reason FROM review_tasks WHERE reason_params_json IS NULL"
    ).fetchall()
    for row in rows:
        parts = parse_legacy_reason(row["reason"])
        connection.execute(
            "UPDATE review_tasks SET reason_key=?, reason_params_json=? WHERE id=?",
            (
                str(parts[0]["key"]) if parts else None,
                json.dumps({"parts": parts or []}, ensure_ascii=False),
                row["id"],
            ),
        )
    return len(rows)

def stable_id(kind: str, value: str) -> str:
    namespace = f"{ID_NAMESPACE_PREFIX}/{kind}"
    return str(uuid.uuid5(uuid.uuid5(uuid.NAMESPACE_URL, namespace), value))


def seed_concepts(connection: sqlite3.Connection) -> None:
    now = utc_now()
    seeded: list[tuple[str, str]] = []
    for definition in CONCEPT_DEFINITIONS:
        concept_id = stable_concept_id(str(definition["name"]))
        connection.execute(
            """INSERT INTO concepts(id, canonical_name, category, value_type, preferred_unit, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET canonical_name=excluded.canonical_name,
                   category=excluded.category, value_type=excluded.value_type,
                   preferred_unit=excluded.preferred_unit""",
            (
                concept_id,
                definition["name"],
                definition["category"],
                definition.get("value_type", "numeric"),
                definition["unit"],
                now,
            ),
        )
        for alias in definition["aliases"]:
            normalized = normalized_key(str(alias))
            seeded.append((concept_id, normalized))
            connection.execute(
                """INSERT OR IGNORE INTO concept_aliases(concept_id, vendor_id, alias, normalized_alias)
                   VALUES (?, NULL, ?, ?)""",
                (concept_id, alias, normalized),
            )
    # An alias with no vendor belongs to this file and to nothing else, so one
    # the file no longer lists is deleted rather than left behind.  Renaming a
    # concept mints a new id -- `stable_concept_id` slugs the English name --
    # and without this the old id kept its aliases: «резус-фактор» went on
    # resolving to a "Rh factor" concept that no definition described any more,
    # ready to file the next Rh result under a concept nothing else points at.
    connection.execute("CREATE TEMP TABLE IF NOT EXISTS _seeded_alias(concept_id TEXT, alias TEXT)")
    connection.execute("DELETE FROM _seeded_alias")
    connection.executemany("INSERT INTO _seeded_alias(concept_id, alias) VALUES (?, ?)", seeded)
    connection.execute(
        """DELETE FROM concept_aliases
           WHERE vendor_id IS NULL
             AND NOT EXISTS (
                 SELECT 1 FROM _seeded_alias s
                 WHERE s.concept_id = concept_aliases.concept_id
                   AND s.alias = concept_aliases.normalized_alias
             )"""
    )
    # A specimen header a parser once took for a label must not stay
    # learned: it would file the next line of any vendor under it.
    connection.execute(
        f"DELETE FROM concept_aliases WHERE normalized_alias IN ({','.join('?' * len(NON_ANALYTE_LABELS))})",
        tuple(NON_ANALYTE_LABELS),
    )
    seed_reference_rules(connection)


def seed_reference_rules(connection: sqlite3.Connection) -> None:
    """Load the curated reference library.

    Curated clinical guidance lives in ``data/reference_library.json`` and
    nowhere else; this wrapper keeps the historical call site while the loader
    owns the content.
    """
    from ..reference import seed_reference_library

    seed_reference_library(connection)


def checked_order(
    connection: sqlite3.Connection, patient_id: object, order: str | None, day: str | None, document_id: str | None = None
) -> str | None:
    """The order number to store: none when OCR read a known order one digit off.

    A photo of a results sheet printed the same day as an order already on
    file, whose number differs from it in one digit, is that order misread
    (an 8 read as a 6): storing it would invent an order nobody placed.
    """
    if not (order and day):
        return order
    known = {
        row[0]
        for row in connection.execute(
            """SELECT order_identifier FROM documents
                WHERE patient_id=? AND id IS NOT ? AND order_identifier IS NOT NULL
                  AND (report_date=? OR substr(collected_at, 1, 10)=?)""",
            (str(patient_id), document_id, day, day),
        )
    }
    return None if misread_order(order, known) else order


def ensure_vendor(connection: sqlite3.Connection, name: str, website: str | None) -> str:
    vendor_id = stable_id("vendor", name)
    connection.execute(
        """INSERT INTO vendors(id, canonical_name, website, created_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(canonical_name) DO UPDATE SET website=COALESCE(excluded.website, vendors.website)""",
        (vendor_id, name, website, utc_now()),
    )
    return vendor_id


def _row_family(specimen: str | None, unit_raw: str | None, context: str | None) -> str | None:
    titled = specimen_family(context)
    return (
        specimen_family(specimen)
        or ("hematology" if blood_count_unit(unit_raw) else None)
        or (titled if titled in {"stool", "smear"} else None)
    )


def _learned_alias_row(
    connection: sqlite3.Connection, normalized: str, vendor_id: str, value_type: str, excluded: list[str]
):
    alias_row = connection.execute(
        f"""SELECT c.id, c.preferred_unit, c.category FROM concept_aliases a
           JOIN concepts c ON c.id = a.concept_id
           WHERE a.normalized_alias = ? AND (a.vendor_id = ? OR a.vendor_id IS NULL)
             AND (c.value_type = ? OR c.value_type = 'mixed')
             AND c.category NOT IN ({",".join("?" * len(excluded)) or "''"})
           ORDER BY a.vendor_id IS NULL ASC LIMIT 1""",
        (normalized, vendor_id, value_type, *excluded),
    ).fetchone()
    if alias_row is None or alias_row["id"] not in _DEFINED_CONCEPT_IDS:
        # An auto concept is one per label across vendors, as its unique name
        # already makes it: a label that differs only in a key-folded
        # character («пов'язані» / «пов"язані») is the same one too, and the
        # vendor-scoped alias each spelling taught must not keep two series.
        alias_row = _first_auto_concept(connection, normalized, value_type, excluded) or alias_row
    return alias_row


def _reuse_alias_concept(connection: sqlite3.Connection, alias_row, inferred_category: str) -> tuple[str, str | None]:
    # Reused through its learned alias, an auto concept's category is
    # read again too: the 39 serum amino acids kept «urinalysis» here
    # after the inference stopped giving it (start-up repair runs this).
    category = _auto_category(alias_row["id"], alias_row["category"], inferred_category)
    if category != alias_row["category"]:
        connection.execute("UPDATE concepts SET category=? WHERE id=?", (category, alias_row["id"]))
    return alias_row["id"], alias_row["preferred_unit"]


def ensure_concept(
    connection: sqlite3.Connection,
    raw_name: str,
    vendor_id: str,
    value_type: str = "numeric",
    unit_raw: str | None = None,
    clinical_type: str | None = None,
    context: str | None = None,
    value_text: str | None = None,
    reference_text: str | None = None,
    specimen: str | None = None,
) -> tuple[str, str | None]:
    """``context`` is the report title, when the caller has one.

    A urinalysis names its specimen in the title («Загальний аналіз сечі»),
    not in every row: a bare «Лейкоцити» carries no сеч- token of its own, so
    without the title the double-seeded aliases resolve by definition order
    and a numeric urine count files under the blood concept.

    ``unit_raw``, ``value_text``, ``reference_text`` and ``clinical_type`` let
    ``refine_definition`` file a label that is the same word across methods
    (strip vs microscopy, ECG vs cuff, CRP vs hs-CRP) by what the row says.

    ``specimen`` is the row's stored material (``observation_specimen``).
    It, then a blood-count unit, then a title naming only stool or only a
    smear, settle which specimen the row was measured in -- and that binds
    (``concept_for_alias``): «Лейкоцити (WBC) 6.84 10^9 клітин/л» in an order
    titled as a urinalysis is the white cell count, and a smear's «Слиз» is
    not urine mucus.  A urinalysis or blood title stays a preference only:
    such orders routinely carry the other specimen's rows too.
    """
    raw_name = clean_label(raw_name)
    normalized = normalized_key(raw_name)
    family = _row_family(specimen, unit_raw, context)
    inferred_category = _inferred_category(normalized, clinical_type, context, family)
    search_category = None if inferred_category == "unmapped" else inferred_category
    # Canonical definitions are resolved before learned vendor aliases because
    # the same printed label can mean different things in different specimen
    # contexts (for example blood glucose versus urine glucose).
    by_label = concept_for_alias(
        raw_name,
        value_type,
        category=search_category,
        specimen=family,
    )
    definition = refine_definition(
        by_label, unit=unit_raw, value_text=value_text, reference=reference_text,
        clinical_type=clinical_type,
    )
    if definition:
        # Learned only when the label decided: a coprogram's «Форма» or
        # «Кристали» is stool because of its section, and learned as a bare
        # alias it would file the next unsectioned «Кристали» as stool too.
        label_decided = family is None or by_label is concept_for_alias(
            raw_name, value_type, category=search_category
        )
        return _store_defined_concept(
            connection, definition, by_label if label_decided else None, vendor_id, raw_name, normalized
        )
    # A learned alias obeys the same specimen: Synevo's urinalysis taught
    # «лейкоцити» -> urine leukocytes, and a smear's «Лейкоцити» must not
    # inherit it.
    excluded = sorted(foreign_categories(raw_name, family))
    raw_name = _specimen_qualified(raw_name, family, specimen)
    normalized = normalized_key(raw_name)
    alias_row = _learned_alias_row(connection, normalized, vendor_id, value_type, excluded)
    if alias_row:
        return _reuse_alias_concept(connection, alias_row, inferred_category)
    concept_id, preferred_unit = _store_unmapped_concept(
        connection, raw_name, normalized, value_type, inferred_category, unit_raw
    )
    if normalized not in NON_ANALYTE_LABELS:
        connection.execute(
            """INSERT OR IGNORE INTO concept_aliases(concept_id, vendor_id, alias, normalized_alias)
               VALUES (?, ?, ?, ?)""",
            (concept_id, vendor_id, collapse_space(raw_name), normalized),
        )
    return concept_id, preferred_unit


def _first_auto_concept(connection: sqlite3.Connection, normalized: str, value_type: str, excluded: list[str]):
    """The earliest auto concept any vendor's alias with this key names."""
    for row in connection.execute(
        f"""SELECT DISTINCT c.id, c.preferred_unit, c.category, c.created_at FROM concept_aliases a
           JOIN concepts c ON c.id = a.concept_id
           WHERE a.normalized_alias = ? AND (c.value_type = ? OR c.value_type = 'mixed')
             AND c.category NOT IN ({",".join("?" * len(excluded)) or "''"})
           ORDER BY c.created_at, c.id""",
        (normalized, value_type, *excluded),
    ):
        if row["id"] not in _DEFINED_CONCEPT_IDS:
            return row
    return None


def _specimen_qualified(raw_name: str, family: str | None, specimen: str | None) -> str:
    """The name an auto concept is kept under: the printed label, plus the
    material when the label alone would merge two different measurements.

    Concept names are unique, so a urine culture's «Lactobacillus spp.» (per
    mL) and a stool culture's (per g) were one series, a smear's «Епітелій»
    took the urinalysis concept of that name, and the vaginal and cervical
    readings of one smear were one series.  Stool rows take «(кал)», which is
    also the name Esculab's coprogram concepts already carry; smear rows take
    their sampling site («VAGINA»).  Urine and blood keep the bare label.
    """
    if family == "stool" and specimen_family(raw_name) != "stool":
        return f"{raw_name} (кал)"
    site = collapse_space(specimen or "")
    if family == "smear" and site and f"({site})".casefold() not in raw_name.casefold():
        return f"{raw_name} ({site})"
    return raw_name


def _inferred_category(
    normalized: str, clinical_type: str | None, context: str | None, family: str | None = None
) -> str:
    if clinical_type in {"allergy", "microbiology"}:
        return clinical_type
    # The established specimen outranks the tokens: a smear's «Епітелій» and a
    # coprogram's «Йодофільні бактерії» carry «епітел»/«бактері» and were filed
    # as urinalysis.  A smear is read for its flora, cells and infection agents.
    if family == "stool":
        return "stool"
    if family == "smear":
        return "microbiology"
    if family == "urinalysis" or _URINE_WORD.search(normalized) or any(
        token in normalized for token in ("епітел", "циліндр", "бактері", "кристал")
    ):
        return "urinalysis"
    # The report's title is the weakest evidence and yields to the row's own
    # material: an order titled «Амінокислоти (... в сироватці) · Сечовина»
    # filed 39 serum amino acids as urinalysis, «сеч» being the first letters
    # of «Сечовина» (urea).  Words, not substrings, and only when the row
    # names no specimen of its own.
    if family is None and context and _URINE_WORD.search(normalized_key(context)):
        return "urinalysis"
    return "unmapped"


#: Urine, as a word: «сеча», «сечі», «сечовий осад», "urine" -- not «сечовина»
#: (urea) or «сечова кислота» (uric acid), which are blood chemistry.
_URINE_STEM = r"\bсеч"
_URINE_ENDING = r"(?:а|і|у|ею|ов(?!ин|а\s+кислот|ої\s+кислот)\w*)?"
_URINE_WORD = re.compile(rf"{_URINE_STEM}{_URINE_ENDING}\b|\burine", re.I)


def _store_defined_concept(
    connection: sqlite3.Connection, definition, by_label, vendor_id: str, raw_name: str, normalized: str
) -> tuple[str, str | None]:
    concept_id = stable_concept_id(str(definition["name"]))
    preferred_unit = definition["unit"] if definition["unit"] is not None else None
    connection.execute(
        """INSERT INTO concepts(
               id, canonical_name, category, value_type, preferred_unit, created_at
           ) VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET canonical_name=excluded.canonical_name,
               category=excluded.category, value_type=excluded.value_type,
               preferred_unit=excluded.preferred_unit""",
        (
            concept_id,
            definition["name"],
            definition["category"],
            definition.get("value_type", "numeric"),
            preferred_unit,
            utc_now(),
        ),
    )
    # An upsert, not INSERT OR IGNORE: a learned alias row filed under the
    # wrong concept before the definition existed could never be healed --
    # «Лейкоцити в мкл (WBC)» kept pointing at the blood count long after
    # the urine definition was written, waiting to re-file urine counts as
    # blood ones if the definitions ever regressed.  A corrected catalogue
    # gets to correct the learned table.  Not learned when the row rather
    # than the label decided (a refinement): «Лейкоцити» is the strip on
    # one row and the microscopy on the next, and an alias says neither.
    # Nor without a vendor: a vendor-less alias row is the seeded catalogue
    # (``seed_concepts`` owns and prunes those), not something learned.
    if definition is by_label and vendor_id is not None:
        connection.execute(
            """INSERT INTO concept_aliases(concept_id, vendor_id, alias, normalized_alias)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(vendor_id, normalized_alias) DO UPDATE SET concept_id=excluded.concept_id""",
            (concept_id, vendor_id, collapse_space(raw_name), normalized),
        )
    return concept_id, preferred_unit


#: The catalogue's concepts, whose category no row's inference may change.
_DEFINED_CONCEPT_IDS = frozenset(stable_concept_id(str(definition["name"])) for definition in CONCEPT_DEFINITIONS)


def _store_unmapped_concept(
    connection: sqlite3.Connection, raw_name: str, normalized: str, value_type: str, category: str,
    unit_raw: str | None,
) -> tuple[str, str | None]:
    concept_id = stable_id("unmapped-concept", f"{normalized}:{value_type}:{category}")
    preferred_unit = unit_raw
    connection.execute(
        """INSERT OR IGNORE INTO concepts(id, canonical_name, category, value_type, preferred_unit, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (concept_id, collapse_space(raw_name), category, value_type, preferred_unit, utc_now()),
    )
    same = connection.execute("SELECT category FROM concepts WHERE id=?", (concept_id,)).fetchone()
    if same:
        # The id is the inferred category's own, so a row found here was
        # stored before under a wrong one (39 serum amino acids kept
        # «urinalysis» from a title's «Сечовина» through every re-read).
        resolved_category = _auto_category(concept_id, same["category"], category)
        if resolved_category != same["category"]:
            connection.execute("UPDATE concepts SET category=? WHERE id=?", (resolved_category, concept_id))
        return concept_id, preferred_unit
    existing = connection.execute(
        "SELECT id, category, value_type, preferred_unit FROM concepts WHERE canonical_name=? COLLATE NOCASE",
        (collapse_space(raw_name),),
    ).fetchone()
    if existing:
        concept_id = existing["id"]
        preferred_unit = existing["preferred_unit"] or preferred_unit
        resolved_type = existing["value_type"] if existing["value_type"] == value_type else "mixed"
        resolved_category = _auto_category(existing["id"], existing["category"], category)
        connection.execute(
            "UPDATE concepts SET category=?, value_type=?, preferred_unit=COALESCE(preferred_unit, ?) WHERE id=?",
            (resolved_category, resolved_type, preferred_unit, concept_id),
        )
    return concept_id, preferred_unit


def _auto_category(concept_id: str, stored: str, inferred: str) -> str:
    """An auto concept's category is an inference, and a better one replaces
    it; «unmapped» replaces only a «urinalysis» (the one category a stray
    substring of a title once gave).  A defined concept's is the catalogue's.
    ponytail: the last row read wins for a label two specimens share under one
    name; `_specimen_qualified` keeps the known ones apart."""
    if concept_id in _DEFINED_CONCEPT_IDS:
        return stored
    return inferred if inferred != "unmapped" or stored == "urinalysis" else stored


#: Concepts whose report prints a three-tier index scale rather than an
#: interval.  Keyed on the concept, not the printed name: the ANA special case
#: matched the English label the parser used to invent, so storing the printed
#: Ukrainian label (DOCB-11) would have silently turned it off.
ANA_CONCEPT_ID = "antinuclear-antibodies"
MUMPS_IGG_CONCEPT_ID = "mumps-virus-igg"


def _text_interpretation(observation: ParsedObservation) -> str | None:
    if observation.value_text and observation.reference_text:
        if normalized_key(observation.value_text) in normalized_key(observation.reference_text):
            return "within_vendor_range"
    return None


def _has_ana_index_scale(normalized_reference: str) -> bool:
    return (
        any(word in normalized_reference for word in ("negative", "негатив"))
        and any(word in normalized_reference for word in ("equivocal", "сумнів", "погранич"))
        and any(word in normalized_reference for word in ("positive", "позитив"))
    )


def _ana_index(value: float) -> str:
    if value < 1.0:
        return "within_vendor_range"
    if value <= 1.2:
        return "borderline"
    return "positive"


def _mumps_igg_positive(
    observation: ParsedObservation, concept_id: str | None, normalized_name: str, normalized_reference: str
) -> bool:
    return bool(
        (
            concept_id == MUMPS_IGG_CONCEPT_ID
            or "вірус паротиту антитіла igg" in normalized_name
            or "mumps virus igg" in normalized_name
        )
        and "негатив" in normalized_reference
        and observation.reference_high is not None
        and observation.value_numeric > observation.reference_high
    )


def interpretation(observation: ParsedObservation, concept_id: str | None = None) -> str | None:
    value = observation.value_numeric
    if value is None:
        return _text_interpretation(observation)
    normalized_name = normalized_key(observation.raw_name)
    normalized_reference = normalized_key(observation.reference_text or "")
    # ANA is reported as a categorical index, not a conventional numeric
    # reference interval.  Treating the first two thresholds as a low/high
    # range incorrectly labels a negative result (<1.0) as "low".
    if concept_id == ANA_CONCEPT_ID and _has_ana_index_scale(normalized_reference):
        return _ana_index(value)
    if _mumps_igg_positive(observation, concept_id, normalized_name, normalized_reference):
        return "positive"
    # A named negative / equivocal / positive scale reads the value itself, as
    # `parsers.finalise` does at ingest; without it the start-up repair, which
    # comes through here, turned an HBsAg in the grey zone from "borderline"
    # into "high".
    scaled = scale_interpretation(value, observation.reference_text)
    if scaled is not None:
        return scaled
    low, high = observation.reference_low, observation.reference_high
    # A censored result («<0.5», «>60») is a limit, not a value: it is placed
    # against the printed range only where its side is certain, the rule the
    # engine applies in reference._vendor_side. None means the range says nothing.
    if observation.comparator in _CENSORED_SIGN:
        return _vendor_side(value, low, high, comparator=_CENSORED_SIGN[observation.comparator])
    if low is None and high is None:
        return _time_of_day_interpretation(value, observation.reference_text)
    return _printed_range_side(value, observation)


def _printed_range_side(value: float, observation: ParsedObservation) -> str:
    low, high = observation.reference_low, observation.reference_high
    # A strict bound excludes the value equal to it: CA-125 35.0 against «< 35»
    # is not inside the laboratory's range, and was published as though it were.
    if low is not None and (value < low or (value == low and not observation.reference_low_inclusive)):
        return "low"
    if high is not None and (value > high or (value == high and not observation.reference_high_inclusive)):
        return "high"
    return "within_vendor_range"


#: The printed censoring signs, mapped to the ASCII comparators `_vendor_side` takes.
_CENSORED_SIGN = {"<": "<", "≤": "<=", ">": ">", "≥": ">="}


def _time_of_day_interpretation(value: float, reference: str | None) -> str | None:
    """A value against a reference printed per time of day (cortisol).

    Which band applies depends on when the sample was drawn, and nothing here
    records that reliably; but a value inside every band, or beyond all of
    them, reads the same whichever applies.  In between, no reading is the
    honest answer.
    """
    bands = time_of_day_bands(reference)
    if not bands:
        return None
    if all(low <= value <= high for low, high in bands):
        return "within_vendor_range"
    if all(value > high for _, high in bands):
        return "high"
    if all(value < low for low, _ in bands):
        return "low"
    return None


def stored_unit(
    unit_raw: str | None, preferred_unit: str | None, concept_id: str | None = None
) -> str | None:
    """The unit the stored ``value_numeric`` is actually in.

    ``unit_canonical`` used to be set to the concept's preferred unit whatever
    the report printed, which makes it a claim about the value that nothing
    ever made true.  Synevo prints MCHC in g/dL; the row was stored as "36" and
    labelled "g/L", and 36 g/L is a tenth of the real measurement -- so the
    application reported *below range* on a reading that is above it, twice, on
    a haematology index whose whole purpose is to flag hypochromia.

    The value itself is never rewritten.  The database keeps what the report
    printed, and conversion happens on the way out, in
    ``_deduped_observation_rows`` -- because this function runs from
    ``repair_observation_semantics`` on every application start, and a repair
    that edits the number it reads would multiply the same MCHC by ten again on
    every restart.  Storing the measurement and stating its unit honestly is
    idempotent by construction.

    Two printed units are restated, both because the number beside them is
    already in the other one: a unit that folds to nothing (specific gravity
    «г/мл» -- the figure is the dimensionless relative density) and a
    per-concept relabel from ``CONCEPT_UNIT_ALIASES`` (plateletcrit printed
    «х 10*9/л» over a value in %).  Left as printed, either gives the analyte a
    second unit and splits its series.
    """
    if not unit_raw:
        return preferred_unit
    folded = canonical_unit(unit_raw)
    if not folded:
        return preferred_unit
    if concept_id and (concept_id, folded) in CONCEPT_UNIT_ALIASES:
        return preferred_unit or CONCEPT_UNIT_ALIASES[(concept_id, folded)]
    return unit_raw


_STRICT_UPPER_RE = re.compile(r"<(?!=)\s*-?\d")
_STRICT_LOWER_RE = re.compile(r">(?!=)\s*-?\d")
#: Whether the reference is a two-sided range («1 - 5», «0,5 до 2»).  Only
#: `search` succeeding matters, and any number before the dash ends in a
#: digit, so the number reduces to that last digit: the same strings match.
_RANGE_RE = re.compile(r"\d\s*(?:до|[-–—])\s*-?\d", re.I)


def reference_inclusivity(
    reference: str | None, low: float | None, high: float | None
) -> tuple[int, int]:
    """Whether each stored bound belongs to the interval: «< 0.2» does not.

    Every row used to be stored 1/1, so a yeast count of 0.2 against a
    laboratory's «< 0.2» was published inside the range.  Only a one-sided
    bound written with a strict sign is exclusive; «до 5», «≤ 5» and «1 - 5»
    include their ends, as laboratories mean them.
    """
    text = reference or ""
    if _RANGE_RE.search(text):
        return 1, 1
    low_inclusive = 0 if low is not None and _STRICT_LOWER_RE.search(text) else 1
    high_inclusive = 0 if high is not None and _STRICT_UPPER_RE.search(text) else 1
    return low_inclusive, high_inclusive


def parsed_inclusivity(parsed: ParsedObservation) -> tuple[int, int]:
    """The parser's own answer when it gives one (F1), else the printed sign."""
    derived = reference_inclusivity(parsed.reference_text, parsed.reference_low, parsed.reference_high)
    low = getattr(parsed, "reference_low_inclusive", None)
    high = getattr(parsed, "reference_high_inclusive", None)
    return (
        derived[0] if low is None else int(bool(low)),
        derived[1] if high is None else int(bool(high)),
    )


def _bounds(reference: str | None) -> tuple[float | None, float | None, int | None, int | None]:
    """The bounds and their inclusivity, as `reference_limits` reads them.

    The inclusivity comes from the band the bound was read from: «> 200 ... 100 -
    200 ...» has a strict lower bound of 200, which a regex over the whole text
    took for inclusive because a dash range appears elsewhere in it.
    """
    limits = reference_limits(reference)
    if limits.low is None and limits.high is None:
        return (None, None, *reference_inclusivity(reference, None, None))
    return limits.low, limits.high, int(limits.low_inclusive), int(limits.high_inclusive)


def observation_date(parsed: ParsedObservation, page_class: Classification, *, human_date: bool = False) -> str | None:
    """When a row was measured: its own timestamp, the draw, then the report.

    The collection date outranks the report date because that is when the
    sample was taken -- an ALEX² panel drawn on the 28th and printed on the 31st
    was charted on the 31st.  A date a person set outranks both inferences.
    """
    if parsed.observed_at:
        return parsed.observed_at
    if not human_date and page_class.collected_at:
        return page_class.collected_at[:10]
    return page_class.report_date


def parsed_interpretation(parsed: ParsedObservation, concept_id: str | None) -> str | None:
    """The laboratory's reading where the parser could state it (a dipstick
    tier, a class legend, a named band), else the one the bounds give."""
    return getattr(parsed, "vendor_interpretation", None) or interpretation(parsed, concept_id)


def observation_specimen(parsed: ParsedObservation, fallback: str | None = None) -> str | None:
    """The material stored with a row: its own, its section's, the page's.

    A Synevo coprogram prints its material once, as the section heading
    («Копрограма», «Аналіз калу на кишкові паразити»), and every row under it
    is a bare «Форма», «pH», «Слиз».  Stored on the row, the heading's
    specimen is what lets ``repair_observation_semantics`` keep those rows on
    the stool concepts on every later start; the section itself is not stored.
    """
    own = getattr(parsed, "specimen", None)
    if own:
        return own
    # A blood section of a page that also holds a urinalysis is blood, not
    # the page's material (the page names none then, `extract_specimen`).
    family = specimen_family(getattr(parsed, "section", None))
    return {"stool": "кал", "urinalysis": "сеча", "hematology": None}.get(family, fallback) if family else fallback


def resolve_parsed_concept(
    connection: sqlite3.Connection, parsed: ParsedObservation, report_id: str | None, vendor_id: str,
    specimen: str | None = None,
) -> tuple[str, str | None]:
    """The concept a parsed row files under, in its report's context.
    ``specimen`` is the page's material, the fallback ``observation_specimen``
    stores."""
    report_type_row = connection.execute(
        "SELECT clinical_type, title FROM reports WHERE id=?", (report_id,)
    ).fetchone()
    return ensure_concept(
        connection,
        parsed.raw_name,
        vendor_id,
        value_type="numeric" if parsed.value_numeric is not None else "text",
        unit_raw=parsed.unit_raw,
        clinical_type=report_type_row["clinical_type"] if report_type_row else None,
        context=report_type_row["title"] if report_type_row else None,
        value_text=parsed.value_text,
        reference_text=parsed.reference_text,
        specimen=observation_specimen(parsed, specimen),
    )


def insert_observation(
    connection: sqlite3.Connection,
    *,
    owner_user_id: str,
    patient_id: str,
    document_id: str,
    report_id: str,
    vendor_id: str,
    observed_at: str | None,
    parsed: ParsedObservation,
    resolved: tuple[str, str | None] | None = None,
    specimen: str | None = None,
) -> str:
    value_type = "numeric" if parsed.value_numeric is not None else "text"
    concept_id, preferred_unit = resolved or resolve_parsed_concept(
        connection, parsed, report_id, vendor_id, specimen
    )
    unit_canonical = stored_unit(parsed.unit_raw, preferred_unit, concept_id)
    low_inclusive, high_inclusive = parsed_inclusivity(parsed)
    observation_id = str(uuid.uuid4())
    connection.execute(
        """INSERT INTO observations(
               id, owner_user_id, patient_id, document_id, report_id, page_number, concept_id,
               raw_name, value_type, value_numeric, value_text, comparator, unit_raw,
               unit_canonical, observed_at, specimen, vendor_reference_text, vendor_reference_low,
               vendor_reference_high, vendor_reference_low_inclusive,
               vendor_reference_high_inclusive, vendor_interpretation,
               verification_status, extraction_method, confidence, evidence_text,
               parser_version, created_at, value_printed, note
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                     'extracted', ?, ?, ?, ?, ?, ?, ?)""",
        (
            observation_id,
            owner_user_id,
            patient_id,
            document_id,
            report_id,
            parsed.page_number,
            concept_id,
            parsed.raw_name,
            value_type,
            parsed.value_numeric,
            parsed.value_text,
            parsed.comparator,
            parsed.unit_raw,
            unit_canonical,
            observed_at,
            observation_specimen(parsed, specimen),
            parsed.reference_text,
            parsed.reference_low,
            parsed.reference_high,
            low_inclusive,
            high_inclusive,
            parsed_interpretation(parsed, concept_id),
            parsed.extraction_method,
            parsed.confidence,
            parsed.evidence_text,
            PARSER_VERSION,
            utc_now(),
            getattr(parsed, "value_printed", None),
            getattr(parsed, "note", None),
        ),
    )
    return observation_id


def _store_positions_quietly(connection: sqlite3.Connection, document_id: str, path: Path) -> None:
    """Where each value sits on its page, for the review list's order.

    Layout only, never clinical content: a failure here must not cost the
    upload, and the document page locates anything left unplaced when it is
    next opened.
    """
    try:
        store_positions(connection, document_id, path)
    except Exception:
        logger.warning("positions: could not locate values of %s", document_id, exc_info=True)


#: Rows whose identity a person chose, rather than a parser: a correction that
#: renamed the metric, or a value typed in by hand.  Re-deriving their concept
#: from the printed label is exactly the decision the person overrode.
HUMAN_AUTHORED = ("human_corrected", "human_entered")


def is_derived(extraction_method: object) -> bool:
    """A row calculated from other rows (eGFR), never read off a page."""
    method = str(extraction_method or "")
    return method == DERIVED_EGFR_METHOD or method.startswith("derived_")


def _repaired_bounds(row) -> tuple[float | None, float | None, int | None, int | None]:
    low, high, low_inclusive, high_inclusive = _bounds(row["vendor_reference_text"])
    # This pass re-reads the printed text with the *generic* bounds parser.
    # Several rows were produced by a parser written for one report layout,
    # which knows things the generic one cannot see -- the vitamin D rows
    # carry 30-50 ng/mL from a reference printed in prose.  Re-deriving
    # nothing from that prose and storing the nothing deleted the interval.
    # A repair may sharpen a bound; it may never erase one -- unless the text
    # is known to be no interval at all (a per-time-of-day or purely
    # interpretive scale), where the stored bound is the error being repaired.
    if low is None and high is None and not refused_reference(row["vendor_reference_text"]):
        low, high = row["vendor_reference_low"], row["vendor_reference_high"]
        low_inclusive, high_inclusive = reference_inclusivity(row["vendor_reference_text"], low, high)
        # The bound came from a parser that read the band («≥18 років: <7»);
        # its inclusivity did too.  Re-derived from the whole block, any «2-20»
        # elsewhere in it made the adult «<7» inclusive again.
        if row["vendor_reference_low_inclusive"] is not None:
            low_inclusive = int(row["vendor_reference_low_inclusive"])
        if row["vendor_reference_high_inclusive"] is not None:
            high_inclusive = int(row["vendor_reference_high_inclusive"])
    return low, high, low_inclusive, high_inclusive


def _audit_semantic_moves(
    connection: sqlite3.Connection, row, concept_id: str, unit_canonical: str | None, now: str
) -> None:
    moves = []
    if concept_id != row["concept_id"]:
        moves.append(("observation_concept_remapped", {"from": row["concept_id"], "to": concept_id}))
    # A unit filled in where none was stored is not a fold of anything.
    if row["unit_canonical"] is not None and unit_canonical != row["unit_canonical"]:
        moves.append(("observation_unit_folded", {"from": row["unit_canonical"], "to": unit_canonical}))
    for action, change in moves:
        connection.execute(
            """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type,
                                        entity_id, details_json, created_at)
               VALUES (?, NULL, ?, 'observation', ?, ?, ?)""",
            (
                row["owner_user_id"], action, row["id"],
                json.dumps(
                    {
                        **change,
                        "raw_name": row["raw_name"],
                        "unit_raw": row["unit_raw"],
                        "value_numeric": row["value_numeric"],
                        "value_text": row["value_text"],
                        "verification_status": row["verification_status"],
                    },
                    ensure_ascii=False,
                ),
                now,
            ),
        )


def repair_observation_semantics(connection: sqlite3.Connection) -> int:
    """Re-resolve stored observations with the current specimen-aware catalog.

    Evidence rows are preserved.  Only their canonical concept, safe vendor
    bounds, canonical unit, and interpretation are refreshed.

    Rows a person authored are left alone.  This runs on every application
    start, so re-resolving them re-derived the concept from the printed label
    and silently undid the remap: someone who moved a value to the right metric
    saw it move back on the next restart, with the correction still recorded in
    the audit trail.  A better catalogue may improve the parser's guesses; it
    does not get to overrule a person's.

    Verified rows are re-filed too, and stay verified: a person confirmed the
    number on the page, and moving it from "Lymphocytes" to "Lymphocytes
    (manual differential)" changes which series it belongs to, never the
    number.  Each concept or unit move is written to the audit trail
    (``observation_concept_remapped`` / ``observation_unit_folded``) with the
    before and after, so a re-filed verified value can be traced.  Idempotent:
    a second run finds nothing to move and writes nothing.

    Ends by refreshing derived values (eGFR), whose inputs this may have moved.
    """
    seed_concepts(connection)
    changed = 0
    rows = connection.execute(
        f"""SELECT o.*, COALESCE(r.vendor_id, d.vendor_id) resolved_vendor_id,
                         COALESCE(r.clinical_type, d.clinical_type) resolved_clinical_type,
                         COALESCE(r.title, d.title) resolved_title
           FROM observations o
           JOIN documents d ON d.id=o.document_id
           LEFT JOIN reports r ON r.id=o.report_id
           WHERE o.extraction_method NOT IN ({",".join("?" * (len(HUMAN_AUTHORED) + 1))})""",
        (*HUMAN_AUTHORED, DERIVED_EGFR_METHOD),
    ).fetchall()
    now = utc_now()
    for row in rows:
        concept_id, preferred_unit = ensure_concept(
            connection,
            row["raw_name"],
            row["resolved_vendor_id"],
            value_type=row["value_type"],
            unit_raw=row["unit_raw"],
            clinical_type=row["resolved_clinical_type"],
            context=row["resolved_title"],
            value_text=row["value_text"],
            reference_text=row["vendor_reference_text"],
            specimen=row["specimen"],
        )
        low, high, low_inclusive, high_inclusive = _repaired_bounds(row)
        provisional = ParsedObservation(
            raw_name=row["raw_name"],
            value_numeric=row["value_numeric"],
            value_text=row["value_text"],
            comparator=row["comparator"],
            unit_raw=row["unit_raw"],
            reference_text=row["vendor_reference_text"],
            reference_low=low,
            reference_high=high,
            page_number=row["page_number"],
            evidence_text=row["evidence_text"],
            confidence=row["confidence"],
            extraction_method=row["extraction_method"],
            reference_low_inclusive=bool(1 if low_inclusive is None else low_inclusive),
            reference_high_inclusive=bool(1 if high_inclusive is None else high_inclusive),
        )
        refreshed = interpretation(provisional, concept_id)
        if row["vendor_interpretation_source"] == "lab_record":
            refreshed = row["vendor_interpretation"]  # the lab's own flag outranks the printed range (labsync)
        unit_canonical = stored_unit(row["unit_raw"], preferred_unit, concept_id)
        _audit_semantic_moves(connection, row, concept_id, unit_canonical, now)
        if (
            concept_id != row["concept_id"]
            or unit_canonical != row["unit_canonical"]
            or low != row["vendor_reference_low"]
            or high != row["vendor_reference_high"]
            or low_inclusive != row["vendor_reference_low_inclusive"]
            or high_inclusive != row["vendor_reference_high_inclusive"]
            or refreshed != row["vendor_interpretation"]
        ):
            # `parser_version` is deliberately not touched.  It records which
            # parser read the printed page, and this pass re-reads nothing from
            # the page - it re-resolves a stored row against today's catalogue.
            # Stamping it here ran on every application start, so the column
            # said "last touched" for every row in the database and there was no
            # way left to ask which documents an older parser had read.
            connection.execute(
                """UPDATE observations SET concept_id=?, unit_canonical=?,
                       vendor_reference_low=?, vendor_reference_high=?,
                       vendor_reference_low_inclusive=?, vendor_reference_high_inclusive=?,
                       vendor_interpretation=?
                   WHERE id=?""",
                (concept_id, unit_canonical, low, high, low_inclusive, high_inclusive, refreshed, row["id"]),
            )
            changed += 1
    _follow_remaining_units(connection)
    # Stored review reasons are repaired on the same start-up pass: a task
    # written before migration 037 gets its catalogue parts read back from
    # its English sentence, so it renders in the reader's language.
    backfill_review_reason_keys(connection)
    repair_review_tasks(connection)
    refresh_derived_observations(connection)
    return changed


def _follow_remaining_units(connection: sqlite3.Connection) -> int:
    """An auto concept's preferred unit is the one its rows print.  Split by
    specimen, the stool «Lactobacillus spp.» moved to its «(кал)» concept and
    left the urine reading (КУО/мл) alone on a concept that still preferred the
    stool unit (КУО/г).  Where no row prints the preferred unit any more, the
    unit most of the remaining rows print replaces it.  A defined concept's
    unit is the catalogue's."""
    units: dict[str, Counter[str]] = {}
    preferred: dict[str, str] = {}
    for row in connection.execute(
        """SELECT c.id, c.preferred_unit, o.unit_raw FROM concepts c JOIN observations o ON o.concept_id=c.id
            WHERE c.preferred_unit IS NOT NULL AND TRIM(COALESCE(o.unit_raw, '')) <> ''"""
    ):
        if row["id"] in _DEFINED_CONCEPT_IDS:
            continue
        units.setdefault(row["id"], Counter())[str(row["unit_raw"]).strip()] += 1
        preferred[row["id"]] = str(row["preferred_unit"])
    changed = 0
    for concept_id, printed in units.items():
        if canonical_unit(preferred[concept_id]) in {canonical_unit(unit) for unit in printed}:
            continue
        connection.execute("UPDATE concepts SET preferred_unit=? WHERE id=?",
                           (printed.most_common(1)[0][0], concept_id))
        changed += 1
    return changed


def _known_neighbour(results: list[Classification], index: int) -> Classification | None:
    if index > 0 and results[index - 1].vendor != UNKNOWN_VENDOR:
        return results[index - 1]
    if index + 1 < len(results) and results[index + 1].vendor != UNKNOWN_VENDOR:
        return results[index + 1]
    return None


def _inherit_neighbour_vendors(results: list[Classification]) -> None:
    """In place, left to right: a page that names no vendor takes a neighbour's."""
    for index, item in enumerate(results):
        if item.vendor != UNKNOWN_VENDOR:
            continue
        inherited = _known_neighbour(results, index)
        if inherited:
            # `replace`, so every field the page read for itself -- collection
            # and issue moments, specimen, report number -- survives.
            results[index] = replace(
                item,
                vendor=inherited.vendor,
                website=inherited.website,
                clinical_type=item.clinical_type if item.clinical_type != "clinical_report" else inherited.clinical_type,
                report_date=item.report_date or inherited.report_date,
                order_identifier=item.order_identifier or inherited.order_identifier,
                collected_at=item.collected_at or inherited.collected_at,
                confidence=min(item.confidence, inherited.confidence, 0.85),
            )


def _continue_previous_reports(results: list[Classification]) -> None:
    """In place.  A continuation page names no kind of its own: page 2 of an
    abdominal ultrasound is kidneys, bladder and the conclusion, with no word
    that says "ultrasound", so it read as a generic clinical report and its
    bladder-wall measurement was never parsed.  Same vendor, no other date: it
    is the previous page's report."""
    for index in range(1, len(results)):
        item, previous = results[index], results[index - 1]
        if (
            item.clinical_type == "clinical_report"
            and previous.clinical_type != "clinical_report"
            and item.vendor == previous.vendor
            and (not item.report_date or not previous.report_date or item.report_date == previous.report_date)
        ):
            results[index] = replace(
                item,
                clinical_type=previous.clinical_type,
                order_identifier=item.order_identifier or previous.order_identifier,
            )


def _shared_report_dates(results: list[Classification]) -> list[Classification]:
    known_vendors = {item.vendor for item in results if item.vendor != UNKNOWN_VENDOR}
    known_types = {
        item.clinical_type for item in results if item.clinical_type != "clinical_report"
    }
    known_dates = {item.report_date for item in results if item.report_date}
    if not len(known_vendors) == len(known_types) == len(known_dates) == 1:
        return results
    report_date = next(iter(known_dates))
    # The draw moment is printed once, in the header, and the second page
    # of the same report was drawn at the same moment.
    known_collected = {item.collected_at for item in results if item.collected_at}
    collected_at = next(iter(known_collected)) if len(known_collected) == 1 else None
    return [
        replace(
            item,
            report_date=item.report_date or report_date,
            collected_at=item.collected_at or collected_at,
        )
        for item in results
    ]


def page_classifications(
    filename: str,
    mime_type: str,
    pages: list[dict[str, object]],
    metadata: dict[str, str],
) -> list[Classification]:
    results = [classify_document(filename, mime_type, [page], metadata) for page in pages]
    if len(results) > 1 and any(item.title == DISCHARGE_027_TITLE for item in results):
        # A discharge summary (form 027/о) is one report however many pages
        # it runs to: its heading is on page 1 and the stay's end date may be
        # on page 2, and a page read alone became an undated "consultation".
        whole = classify_document(filename, mime_type, pages, metadata)
        return [whole] * len(results)
    _inherit_neighbour_vendors(results)
    _continue_previous_reports(results)
    if _one_report(results) and len({item.vendor for item in results if item.vendor != UNKNOWN_VENDOR}) > 1:
        results = _one_report_pages(results, classify_document(filename, mime_type, pages, metadata))
    return _shared_report_dates(results)


#: The header fields one printed report repeats on every page.
_REPORT_HEADER = ("order_identifier", "report_date", "collected_at", "issued_at")


def _header_value(results: list[Classification], field: str) -> tuple[bool, str | None]:
    """Whether the pages agree on one header field, and the fullest value
    printed («2025-11-28» agrees with «2025-11-28T15:30»).  A page that prints
    none agrees with any."""
    values = sorted({str(getattr(item, field)) for item in results if getattr(item, field)}, key=len)
    agree = all(values[-1].startswith(value) for value in values)
    return agree, values[-1] if values else None


def _one_report(results: list[Classification]) -> bool:
    """Result pages of one order: no page prints another order number, date,
    draw or result moment, and some page prints the order or the draw.  A
    Synevo print for a partner clinic carries the clinic's logo on some pages
    and the laboratory's table on others; read page by page that was two
    vendors, a «compound bundle», and the pages under the logo lost their rows
    to a parser that does not know the clinic (eight HPV genotypes)."""
    if len(results) < 2 or not {
        item.clinical_type for item in results if item.clinical_type != "clinical_report"
    } <= RESULT_TYPES:
        return False
    # A page that is no result page and prints no header of its own (an
    # undated consultation scanned behind the results) is not shown to be
    # part of the order.
    keyed = ("order_identifier", "collected_at", "issued_at")
    if any(item.clinical_type not in RESULT_TYPES and not any(getattr(item, field) for field in keyed)
           for item in results):
        return False
    found = {field: _header_value(results, field) for field in _REPORT_HEADER}
    return all(agree for agree, _value in found.values()) and any(found[field][1] for field in keyed)


def _one_report_pages(results: list[Classification], whole: Classification) -> list[Classification]:
    """Every page of one report under the vendor the whole file reads as (the
    laboratory, whose rule outranks the clinic's logo), with the header any
    page printed."""
    vendors = {item.vendor for item in results}
    vendor, website = (whole.vendor, whole.website) if whole.vendor in vendors else (results[0].vendor, results[0].website)
    header = {field: _header_value(results, field)[1] for field in _REPORT_HEADER}
    return [
        replace(item, vendor=vendor, website=website,
                **{field: getattr(item, field) or value for field, value in header.items()})
        for item in results
    ]


def create_reports(
    connection: sqlite3.Connection,
    *,
    owner_user_id: str,
    patient_id: str,
    document_id: str,
    page_classes: list[Classification],
) -> tuple[dict[int, str], dict[str, str]]:
    page_to_report: dict[int, str] = {}
    report_to_vendor: dict[str, str] = {}
    start = 1
    while start <= len(page_classes):
        first = page_classes[start - 1]
        end = start
        while end < len(page_classes):
            candidate = page_classes[end]
            same_identity = (
                candidate.vendor == first.vendor
                and candidate.clinical_type == first.clinical_type
                and candidate.report_date == first.report_date
                and candidate.order_identifier == first.order_identifier
            )
            if not same_identity:
                break
            end += 1
        report_id = str(uuid.uuid4())
        vendor_id = ensure_vendor(connection, first.vendor, first.website)
        connection.execute(
            """INSERT INTO reports(
                   id, owner_user_id, patient_id, document_id, vendor_id, title, clinical_type,
                   report_date, start_page, end_page, order_identifier, status, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report_id,
                owner_user_id,
                patient_id,
                document_id,
                vendor_id,
                first.title,
                first.clinical_type,
                first.report_date,
                start,
                end,
                first.order_identifier,
                first.status,
                utc_now(),
            ),
        )
        for page_number in range(start, end + 1):
            page_to_report[page_number] = report_id
        report_to_vendor[report_id] = vendor_id
        start = end + 1
    return page_to_report, report_to_vendor


def document_content_hash(pages: list[dict[str, object]]) -> str:
    payload = "\n\f\n".join(
        collapse_space(combined_page_text(page)) for page in pages
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Analysis:
    """What one file looks like to the current extractor and classifier.

    Pulled out of `ingest_file` so a rescan reads the same file through exactly
    the same steps - a re-parse that diverged from first import would produce a
    record nobody could reason about.
    """

    pages: list[dict[str, object]]
    mime_type: str
    page_count: int
    content_hash: str
    classification: Classification
    per_page: list[Classification]


def analyse_document(path: Path, run_ocr: bool = True) -> Analysis:
    extracted = extract_document(path, run_ocr=run_ocr)
    pages = list(extracted["pages"])
    classification, per_page = classify_pages(
        path.name, str(extracted["mime_type"]), pages, dict(extracted["metadata"])
    )
    return Analysis(
        pages=pages,
        mime_type=str(extracted["mime_type"]),
        page_count=int(extracted["page_count"]),
        content_hash=document_content_hash(pages),
        classification=classification,
        per_page=per_page,
    )


def classify_pages(
    filename: str, mime_type: str, pages: list[dict[str, object]], metadata: dict[str, str]
) -> tuple[Classification, list[Classification]]:
    """The document's classification and each page's, from page text alone.

    Shared by first import, re-read and the stale check, which runs it over the
    stored page text to find documents the classifier now reads differently.
    """
    classification = classify_document(filename, mime_type, pages, metadata)
    per_page = page_classifications(filename, mime_type, pages, metadata)
    page_vendors = {item.vendor for item in per_page if item.vendor != UNKNOWN_VENDOR}
    page_dates = {item.report_date for item in per_page if item.report_date}
    page_types = {item.clinical_type for item in per_page if item.clinical_type != "clinical_report"}
    # One laboratory order whose pages are a culture and a urinalysis is one
    # report of that order, not a bundle of unrelated ones: it kept no date
    # and no order number of its own.
    # So is a print whose pages share one order or draw header: a page that
    # prints no order number is not another report for that alone.
    one_order = _one_report(per_page)
    is_compound = len(pages) > 1 and not one_order and (
        len(page_vendors) > 1 or len(page_dates) > 1 or len(page_types) > 1
    )
    if not is_compound and one_order and len(page_types) > 1:
        classification = replace(classification, clinical_type="laboratory")
    if is_compound:
        classification = Classification(
            vendor="Multiple vendors" if len(page_vendors) > 1 else classification.vendor,
            website=None if len(page_vendors) > 1 else classification.website,
            clinical_type="compound_bundle",
            title="Compound medical document bundle",
            report_date=None,
            order_identifier=None,
            status="final",
            extraction_strategy="page_segmented_" + classification.extraction_strategy,
            confidence=0.95,
            notes="Physical PDF contains multiple logical report sections; dates and vendors are stored per report.",
        )
    return classification, per_page


def store_doses(
    connection,
    classification: Classification,
    pages: list[dict[str, object]],
    owner_user_id: str,
    patient_id: str,
    document_id: str,
    per_page: list[Classification] | None = None,
) -> int:
    """Read a vaccination card's doses into `immunizations`, if that is what it is.

    Separate from `parse_pages` because a dose is not an observation and does
    not go where observations go — see migration 023.  Shared by first import
    and by re-read so that improving the card parser reaches the cards already
    on file, and idempotent so that re-reading one does not double it.
    """
    parse = parse_immunizations
    if classification.clinical_type != "immunization_record":
        # A vaccination card can be one section of a combined records PDF.
        # The bundle's own classification does not describe every sheet.
        card_pages = [
            page for page, page_class in zip(pages, per_page, strict=True)
            if page_class.clinical_type == "immunization_record"
        ] if per_page else []
        if card_pages:
            pages = card_pages
        elif is_visit_vaccination("\n".join(str(page.get("native_text") or "") for page in pages)):
            # A visit note whose «Вакцинації» section records the injections
            # given at that visit.
            parse = parse_visit_vaccinations
        else:
            return 0
    return store_document_doses(
        connection,
        owner_user_id,
        patient_id,
        document_id,
        parse(pages),
        classification.extraction_strategy,
    )


def _report_runs(per_page: list[Classification]) -> list[list[int]]:
    """Indexes of consecutive pages that form one logical report.

    The same identity `create_reports` groups by, so a report the record files
    as one is also read as one.
    """
    runs: list[list[int]] = []
    for index, page_class in enumerate(per_page):
        if runs:
            first = per_page[runs[-1][0]]
            if (
                page_class.vendor == first.vendor
                and page_class.clinical_type == first.clinical_type
                and page_class.report_date == first.report_date
                and page_class.order_identifier == first.order_identifier
            ):
                runs[-1].append(index)
                continue
        runs.append([index])
    return runs


def age_at(date_of_birth: str | None, on: str | None) -> int | None:
    """Whole years between a birth date and a report date (today when undated)."""
    try:
        born = datetime.fromisoformat(str(date_of_birth)[:10]).date()
        day = datetime.fromisoformat(str(on)[:10]).date() if on else datetime.now().date()
    except (TypeError, ValueError):
        return None
    return day.year - born.year - ((day.month, day.day) < (born.month, born.day))


def patient_demographics(connection: sqlite3.Connection, patient_id: str) -> tuple[str | None, str | None]:
    row = connection.execute(
        "SELECT date_of_birth, sex_at_birth FROM patients WHERE id=?", (patient_id,)
    ).fetchone()
    return (row["date_of_birth"], row["sex_at_birth"]) if row else (None, None)


_PRINTED_DMY = r"(?<!\d)\d{1,2}[./-]\d{1,2}[./-]\d{4}(?!\d)"
_PRINTED_ISO = r"(?<!\d)\d{4}-\d{1,2}-\d{1,2}(?!\d)"
#: «Дата народження: 17.03.1988», «Дата нар. 17/03/1988».
_BIRTH_LABEL_UK = re.compile(r"дата\s+нар(?:одження|\.)?\s*:?\s*(?P<date>" + _PRINTED_DMY + ")", re.I)
#: «Date of birth: 1988-03-17», «DOB 17.03.1988».
_BIRTH_LABEL_EN = re.compile(
    r"\b(?:date\s+of\s+birth|dob)\s*:?\s*(?P<date>" + _PRINTED_DMY + "|" + _PRINTED_ISO + ")", re.I
)
#: «17.03.1988 р.н.» (the date before the suffix is the birth date) and «р.н. 17.03.1988».
#: Both shapes are one pattern so a date that the first shape took is never
#: claimed again by the second: «01.01.1990 р.н. 02.03.2025» prints one birth date.
_BORN_SUFFIX = re.compile(
    r"(?P<before>" + _PRINTED_DMY + r")\s*р\.\s?н\.?|(?<!\w)р\.\s?н\.?\s*:?\s*(?P<after>" + _PRINTED_DMY + ")",
    re.I,
)


def _printed_date(raw: str) -> str | None:
    """The ISO form of a printed date, or None when no such day exists."""
    if match := re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", raw):
        day, month, year = (int(part) for part in match.groups())
    elif match := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw):
        year, month, day = (int(part) for part in match.groups())
    else:
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def printed_birth_dates(text: str) -> set[str]:
    """The dates of birth a document prints, as ISO dates.

    Only a date a label or the «р.н.» suffix names counts.  The collection,
    issue or vaccination dates on a report say nothing about whose report it is.
    """
    raw = [match.group("date") for pattern in (_BIRTH_LABEL_UK, _BIRTH_LABEL_EN) for match in pattern.finditer(text)]
    raw.extend(match.group("before") or match.group("after") for match in _BORN_SUFFIX.finditer(text))
    return {iso for iso in (_printed_date(item) for item in raw) if iso}


def _birth_date_mismatch(date_of_birth: str | None, text: str) -> bool:
    """Whether a document prints a date of birth, and not the patient's own."""
    known = _printed_date(str(date_of_birth or "")[:10])
    printed = printed_birth_dates(text)
    return bool(known and printed and known not in printed)


def _report_date_implausible(report_date: str | None, date_of_birth: str | None) -> bool:
    """A report dated before its patient was born, or after tomorrow (UTC).

    Such a date is a misread, not a fact about the results; the document is then
    filed undated, as one with no date is.  An unreadable date is left alone.
    """
    try:
        dated = date.fromisoformat(str(report_date or "")[:10])
    except ValueError:
        return False
    born = _printed_date(str(date_of_birth or "")[:10])
    if born and dated < date.fromisoformat(born):
        return True
    return dated > datetime.now(timezone.utc).date() + timedelta(days=1)


def _plausible_analysis(analysis: Analysis, date_of_birth: str | None) -> Analysis:
    """`analysis` with each implausible report date cleared, for the document and
    for its pages (an observation's date is read from its page's report date)."""

    def clear(item: Classification) -> Classification:
        return replace(item, report_date=None) if _report_date_implausible(item.report_date, date_of_birth) else item

    return cast(
        Analysis,
        replace(analysis, classification=clear(analysis.classification), per_page=[clear(page) for page in analysis.per_page]),
    )


def parse_pages(
    classification: Classification,
    per_page: list[Classification],
    pages: list[dict[str, object]],
    *,
    issues: list[ParseIssue] | None = None,
    date_of_birth: str | None = None,
    sex: str | None = None,
) -> list[tuple[ParsedObservation, Classification]]:
    """Every observation the current parsers find, with the page that framed it.

    The consecutive pages of one logical report are parsed together, so a
    reference block that runs over a page break is read whole.  The patient's
    age at the report date and sex let a block printed for several populations
    give this patient's bounds.  Lines the parser recognised and could not
    read are appended to `issues`.
    """
    found: list[tuple[ParsedObservation, Classification]] = []
    if classification.clinical_type == "blood_pressure":
        for parsed in parse_document(
            classification.vendor, "blood_pressure", pages, issues=issues,
            age_years=age_at(date_of_birth, classification.report_date), sex=sex,
        ):
            found.append((parsed, per_page[parsed.page_number - 1]))
        return found
    # The pages of one order are one report, read as one: a SILAB print's
    # first page holds every result but, its table header and footer lost to
    # OCR, classifies as a clinical report on its own, and the next page may
    # print no order number.  Split into runs by page identity, the results
    # page went to a reader that knows no laboratory, and the reader's state
    # (section, smear site) did not cross the page break.
    one_order = _one_report(per_page)
    runs = [list(range(len(per_page)))] if one_order else _report_runs(per_page)
    for run in runs:
        head = classification if one_order else per_page[run[0]]
        rows = parse_document(
            head.vendor, head.clinical_type, [pages[index] for index in run], issues=issues,
            age_years=age_at(date_of_birth, head.report_date), sex=sex,
        )
        for index in run:
            page = pages[index]
            on_page = _under_headings(
                [parsed for parsed in rows if parsed.page_number == page["page_number"]], page, per_page[index].title)
            # A page that prints forty results and yields three leaves no trace
            # anywhere: no error, no review task, just a document that reads as
            # though the laboratory ran fewer tests.  One line per page is
            # enough to find that afterwards, and whether the page carried a
            # result header separates "nothing here to read" from "read badly".
            logger.info(
                "parse: page %s type=%s vendor=%s result_header=%s rows=%d",
                page["page_number"],
                per_page[index].clinical_type,
                per_page[index].vendor,
                has_result_header(combined_page_text(page)),
                len(on_page),
            )
            page_class = replace(per_page[index], clinical_type=head.clinical_type) if one_order else per_page[index]
            found.extend((parsed, page_class) for parsed in on_page)
    return found


def _under_headings(rows: list[ParsedObservation], page: dict[str, object], title: str) -> list[ParsedObservation]:
    """Each row with the heading it is printed under, where the page's title
    joins several («Аналіз крові розгорнутий (ЗАК) · Аналіз сечі загальний»):
    the heading's specimen is the row's (`observation_specimen`).  A row the
    parser already sectioned, or one whose line is not found, is left alone."""
    headings = [heading for heading in title.split(" · ") if heading != "..."]
    if len(headings) < 2 or not rows:
        return rows
    lines = [normalized_key(line) for line in combined_page_text(page).splitlines()]
    marks = sorted(
        (index, heading) for heading in headings
        for index in [next((number for number, line in enumerate(lines)
                            if line and normalized_key(heading)[:40] in line), None)]
        if index is not None)
    if not marks:
        return rows
    placed: list[ParsedObservation] = []
    start = 0
    for row in rows:
        evidence = normalized_key(row.evidence_text or "")
        # In page order first; a pass that reads its rows later (words
        # after numbers) looks again from the top.
        at = next((number for number in [*range(start, len(lines)), *range(start)]
                   if len(lines[number]) >= 6 and evidence.startswith(lines[number])), None)
        heading = None if at is None else next((name for mark, name in reversed(marks) if mark <= at), None)
        if heading and not row.section:
            row = replace(row, section=heading)
        start = at if at is not None else start
        placed.append(row)
    return placed


def _nothing_read_reason(classification: Classification) -> dict[str, object]:
    """Why a document that yielded no rows still needs a look."""
    if classification.status == "result_not_present":
        return reason_part("review.result_not_present")
    if classification.extraction_strategy in {"ocr_required", "ocr_image_metadata", "visual_or_vector_review"}:
        return reason_part("review.image_evidence")
    if classification.clinical_type not in PARSED_CLINICAL_TYPES:
        return reason_part("review.narrative")
    # The same sentence used to cover both an ultrasound, which has
    # no numbers to extract, and a laboratory report the parser read
    # and got nothing from.  The first is the expected shape of that
    # document; the second is a parser that missed a whole panel,
    # and a reader who cannot tell them apart cannot act on either.
    return reason_part("review.no_values_found")


def _ingest_review_reasons(
    classification: Classification,
    observations: list[ParsedObservation],
    doses: int,
    duplicate_id: str | None,
    issues: list[ParseIssue],
    undated: bool = False,
    person_mismatch: bool = False,
) -> list[dict[str, object]]:
    review_reasons = []
    companion = any(issue.kind == COMPANION_SUMMARY for issue in issues)
    issues = [issue for issue in issues if issue.kind != COMPANION_SUMMARY]
    if duplicate_id:
        review_reasons.append(reason_part("review.duplicate"))
    # The report prints another person's date of birth: it may be a family
    # member's, filed under this patient.  Stored all the same; someone decides.
    if person_mismatch:
        review_reasons.append(reason_part("review.person_mismatch"))
    # Without a report date its results sort by upload date, which can put a
    # 2019 panel in front of a 2024 one; a person has to say when it was taken.
    if undated and not classification.report_date:
        review_reasons.append(reason_part("review.no_date"))
    if doses:
        # A card's doses are read out of a photograph of handwriting and
        # tender-length product names, so every field of every row is
        # OCR until somebody says otherwise -- and a wrong lot number or
        # a wrong date on a vaccination is not a rounding error.
        review_reasons.append(reason_part(REVIEW_VACCINATIONS_N, count=doses))
    if observations:
        review_reasons.append(reason_part(REVIEW_VERIFY_N, count=len(observations)))
    elif not (doses or duplicate_id):
        review_reasons.append(reason_part(REVIEW_COMPANION_SUMMARY) if companion
                              else _nothing_read_reason(classification))
    review_reasons.extend(issue_parts(issues))
    return review_reasons


def ingest_file(
    settings: Settings,
    owner_user_id: str,
    patient_id: str,
    path: Path,
    run_ocr: bool = True,
) -> dict[str, object]:
    digest = file_sha256(path)
    with connect(settings) as connection:
        existing = connection.execute(
            "SELECT id FROM documents WHERE owner_user_id = ? AND sha256 = ? AND original_filename = ?",
            (owner_user_id, digest, path.name),
        ).fetchone()
        if existing:
            return {"filename": path.name, "document_id": existing["id"], "action": "unchanged"}

    analysis = analyse_document(path, run_ocr=run_ocr)
    pages = analysis.pages
    classification = analysis.classification
    content_hash = analysis.content_hash
    per_page = analysis.per_page
    extracted = {"mime_type": analysis.mime_type, "page_count": analysis.page_count}
    document_id = str(uuid.uuid4())
    with connect(settings) as connection:
        # The write lock is taken up front and waited for, as in reingest_document:
        # a plain BEGIN defers it to the first write after long work, and the
        # default five-second wait then fails an import behind a running re-read.
        connection.execute("PRAGMA busy_timeout = 60000")
        connection.execute("BEGIN IMMEDIATE")
        try:
            seed_concepts(connection)
            date_of_birth, sex = patient_demographics(connection, patient_id)
            # Before anything is stored: a report date the calendar rules out is
            # filed undated, and the document keeps every other field.
            analysis = _plausible_analysis(analysis, date_of_birth)
            classification, per_page = analysis.classification, analysis.per_page
            document_text = " ".join(combined_page_text(page) for page in pages)
            vendor_id = ensure_vendor(connection, classification.vendor, classification.website)
            # The kept document, never another copy: the earliest file with
            # these bytes may itself have been marked a copy since.
            duplicate = connection.execute(
                """SELECT COALESCE(duplicate_of_document_id, id) id FROM documents
                    WHERE owner_user_id = ? AND sha256 = ? ORDER BY imported_at LIMIT 1""",
                (owner_user_id, digest),
            ).fetchone()
            duplicate_id = duplicate["id"] if duplicate else None
            connection.execute(
                """INSERT INTO documents(
                    id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                    mime_type, byte_size, sha256, content_sha256, page_count, title, clinical_type,
                    extraction_strategy, classification_confidence, order_identifier, report_date,
                    imported_at, status, duplicate_of_document_id, notes,
                    collected_at, issued_at, report_number
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    document_id,
                    owner_user_id,
                    patient_id,
                    vendor_id,
                    path.name,
                    str(path.resolve()),
                    extracted["mime_type"],
                    path.stat().st_size,
                    digest,
                    content_hash,
                    extracted["page_count"],
                    classification.title,
                    classification.clinical_type,
                    classification.extraction_strategy,
                    classification.confidence,
                    checked_order(connection, patient_id, classification.order_identifier, classification.report_date),
                    classification.report_date,
                    utc_now(),
                    classification.status,
                    duplicate_id,
                    classification.notes,
                    classification.collected_at,
                    classification.issued_at,
                    classification.report_number,
                ),
            )
            for page in pages:
                connection.execute(
                    """INSERT INTO document_pages(
                           document_id, page_number, native_text, ocr_text, native_text_sha256,
                           extraction_method, native_char_count, image_count, review_status
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'not_reviewed')""",
                    (
                        document_id,
                        page["page_number"],
                        page.get("native_text"),
                        page.get("ocr_text"),
                        page.get("native_text_sha256"),
                        page["extraction_method"],
                        page["native_char_count"],
                        page["image_count"],
                    ),
                )
            page_to_report, report_to_vendor = create_reports(
                connection,
                owner_user_id=owner_user_id,
                patient_id=patient_id,
                document_id=document_id,
                page_classes=per_page,
            )
            observations: list[ParsedObservation] = []
            issues: list[ParseIssue] = []
            doses = 0
            undated = False
            if not duplicate_id:
                doses = store_doses(
                    connection, classification, pages, owner_user_id, patient_id, document_id, per_page
                )
                parsed_with_context = parse_pages(
                    classification, per_page, pages, issues=issues, date_of_birth=date_of_birth, sex=sex
                )
                observations = [item[0] for item in parsed_with_context]
                for parsed, page_class in parsed_with_context:
                    report_id = page_to_report[parsed.page_number]
                    observed_at = observation_date(parsed, page_class)
                    undated = undated or observed_at is None
                    insert_observation(
                        connection,
                        owner_user_id=owner_user_id,
                        patient_id=patient_id,
                        document_id=document_id,
                        report_id=report_id,
                        vendor_id=report_to_vendor[report_id],
                        observed_at=observed_at,
                        parsed=parsed,
                        specimen=page_class.specimen,
                    )
                _store_positions_quietly(connection, document_id, path)
            record_document_relations(connection, owner_user_id, document_id)
            # Narrative reports must reach their health areas on upload, not
            # only after a later application restart or explicit re-read.
            sync_clinical_findings(connection)
            review_reasons = _ingest_review_reasons(
                classification, observations, doses, duplicate_id, issues, undated=undated,
                person_mismatch=_birth_date_mismatch(date_of_birth, document_text),
            )
            if review_reasons:
                open_review_task(connection, owner_user_id, document_id, review_reasons)
            search_content = " ".join(
                [
                    path.name,
                    classification.title,
                    classification.vendor,
                    classification.clinical_type,
                    " ".join(combined_page_text(page) for page in pages),
                    " ".join(observation.raw_name for observation in observations),
                ]
            )
            index_search(connection, document_id, owner_user_id, search_content)
            connection.execute(
                """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at)
                   VALUES (?, ?, 'ingest', 'document', ?, ?, ?)""",
                (
                    owner_user_id,
                    owner_user_id,
                    document_id,
                    json.dumps(
                        {
                            "filename": path.name,
                            "classification": asdict(classification),
                            "observations": len(observations),
                            "duplicate_of": duplicate_id,
                        },
                        ensure_ascii=False,
                    ),
                    utc_now(),
                ),
            )
            refresh_derived_observations(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "filename": path.name,
        "document_id": document_id,
        "action": "duplicate" if duplicate_id else "ingested",
        "vendor": classification.vendor,
        "clinical_type": classification.clinical_type,
        "status": classification.status,
        "report_date": classification.report_date,
        "observations": len(observations),
        # Counted separately, but reported to the queue as content read: a
        # vaccination card yields no observations at all, and calling that
        # "nothing structured could be read from it" told the person their card
        # had failed on the one screen that was showing them thirteen doses.
        "immunizations": doses,
    }


#: A value somebody has ruled on.  A rescan may add to these and may re-file
#: them, but it never overwrites the judgement or the number a person entered.
HUMAN_RULED = ("verified", "corrected", "rejected")


def _apply_human_classification(analysis: Analysis, document) -> Analysis:
    """Put a person's answer about what this document is back on top of a re-read.

    `documents.classified_by = 'human'` means somebody used the control on the
    document page to say what the classifier could not work out.  Everything the
    parser does follows from the kind of report, so this is not a label: it is
    the difference between a file whose results can be read and one whose
    results are stranded in the page text.  Left to itself the re-read would
    reach the same wrong answer it reached the first time, and the correction
    would appear to work and be gone by the next page load.

    Vendor, kind and date are the three the control sets; everything else --
    page count, strategy, title, order identifier -- is still whatever today's
    read of the file says, because those are observations about the file rather
    than decisions about it.
    """
    keys = document.keys()
    date_by_person = "report_date_set_by" in keys and str(document["report_date_set_by"] or "") == "human"
    if str(document["classified_by"] or "") != "human":
        if not (date_by_person and document["report_date"]):
            return analysis
        # A date the owner typed (the metadata form, an adopted suggestion) is
        # a ruling about the document even when its kind is not: three
        # ultrasound reports lost theirs to a classifier that read no date.
        # Pages that read a date of their own in a multi-report bundle keep it.
        single = analysis.classification.clinical_type != "compound_bundle"
        return cast(Analysis, replace(
            analysis,
            classification=replace(analysis.classification, report_date=document["report_date"]),
            per_page=[
                replace(page, report_date=document["report_date"])
                if single or not page.report_date else page
                for page in analysis.per_page
            ],
        ))
    kind = str(document["clinical_type"] or "")
    if kind not in KNOWN_CLINICAL_TYPES:
        # A kind no parser or page knows -- «Лабораторний звіт», written by an
        # AI suggestion in the reader's language and stored as a person's
        # ruling -- cannot be applied: forcing it made `parse_document` return
        # nothing, and the re-read deleted 53 results.  The classifier's own
        # answer stands for the kind; vendor and date are still the person's.
        logger.warning("rescan: %s carries unknown kind %r; using the classifier's", document["id"], kind)
        kind = analysis.classification.clinical_type
    fields = {
        "vendor": str(document["vendor_name"] or analysis.classification.vendor),
        "clinical_type": kind or analysis.classification.clinical_type,
        "report_date": document["report_date"] or analysis.classification.report_date,
        "confidence": 1.0,
    }
    return cast(Analysis, replace(
        analysis,
        classification=replace(analysis.classification, **fields),
        per_page=[replace(page, **fields) for page in analysis.per_page],
    ))


def _date_is_human(document) -> bool:
    keys = document.keys()
    return bool(document["report_date"]) and (
        str(document["classified_by"] or "") == "human"
        or ("report_date_set_by" in keys and str(document["report_date_set_by"] or "") == "human")
    )


def backfill_search_keys(connection) -> int:
    """Give already-indexed documents the folded key the search now matches on.

    Runs on start beside the other repairs.  Cheap after the first pass -- the
    WHERE clause matches nothing once every row has one -- and it means the
    migration does not have to encode the folding rule in SQL, where it would
    be a second copy free to drift from `search_key`.
    """
    rows = connection.execute(
        "SELECT document_id, content FROM search_index WHERE content_folded IS NULL"
    ).fetchall()
    for row in rows:
        connection.execute(
            "UPDATE search_index SET content_folded=? WHERE document_id=?",
            (search_key(str(row["content"] or "")), row["document_id"]),
        )
    if rows:
        connection.commit()
        logger.info("search: folded key written for %d document(s)", len(rows))
    return len(rows)


def index_search(connection, document_id: str, owner_user_id: str, content: str) -> None:
    """Store a document's searchable text, and the key the search matches on.

    Both writers went through their own INSERT before this existed, and the
    folded column has to be written by every one of them or a document silently
    stops being findable by the half of its spellings that need folding.
    """
    text = collapse_space(content)
    connection.execute(
        """INSERT INTO search_index(document_id, owner_user_id, content, content_folded)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(document_id) DO UPDATE SET
               content=excluded.content, content_folded=excluded.content_folded""",
        (document_id, owner_user_id, text, search_key(text)),
    )


_COVER_STATUSES = ("supporting_record", "result_not_present")


def _result_fingerprint(row) -> tuple[object, ...]:
    """One result by content: concept, value, unit and day -- never by id or file."""
    return (
        row["concept_id"],
        None if row["value_numeric"] is None else round(float(row["value_numeric"]), 6),
        normalized_key(str(row["value_text"] or "")) if row["value_numeric"] is None else "",
        canonical_unit(row["unit_canonical"]) if row["value_numeric"] is not None else "",
        str(row["observed_at"] or "")[:10],
    )


#: A line naming a file on the machine that printed the PDF.  A re-export of
#: one report differs from the first export by exactly this footer
#: (`C:\Users\…\AppData\Local\Temp\…pdf`), so it is not part of the report.
_LOCAL_PATH_LINE = re.compile(r"\b[a-z]:[\\/]|\\\\[^\\\s]+\\|file:/|(?:^|\s)/(?:users|home|tmp|var|private)/", re.I)
_NOT_LETTER_OR_DIGIT = re.compile(r"[\W_]+")
#: Below this two "identical" texts are two blank scans, not one report.
_MIN_TEXT_KEY = 40


#: What a print adds to a page that is not the report: a browser's header
#: stamp ("07.08.26, 10:33", two-digit year, at the start of a line), page
#: counters ("Сторінка 1 із 3", "Стор. 2 з 2", "Page 1 of 3"), a report's own
#: print date ("Дата друку: …") and the URL of the page printed.  Three portal
#: prints of one urinalysis differed in nothing else (sandbox, 2026-11-07).
#: `\w` in the counter because a portal prints "Сторінĸа" with a kra (U+0138).
_PRINT_NOISE = re.compile(
    r"^\s*\d{1,2}[./]\d{1,2}[./]\d{2}(?:\d{2})?,\s*\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]\.?m\.?)?"
    r"|\b(?:сторін\w*|стор\.?|page|стр\.?|страница)\s*\d+\s*(?:(?:із|з|of|из|/)\s*\d+)?"
    r"|дата\s+друку\s*:?\s*[\d./]+"
    r"|\b(?:https?|blob|about):\S*",
    re.I,
)
#: An order number or barcode: 7 to 13 digits standing alone.  Shorter runs
#: are licence and street numbers.
_ORDER_NUMBER = re.compile(r"(?<!\w)\d{7,13}(?!\w)")
#: A Ukrainian phone number written without separators: a clinic's letterhead.
_PHONE_NUMBER = re.compile(r"380\d{9}|0[3-9]\d{8}")
#: A number this long is specific enough to tie two files on its own.
_LONG_ORDER_NUMBER = 8
#: An order, collection or result time to the minute: "06.04.2026 15:15",
#: "11/08/2021 14:18".  Letterheads print dates, never times.
_STAMP = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./]((?:19|20)\d{2})[\s,|]{1,4}(\d{1,2}):(\d{2})(?!\d)")
#: A scroll seam: one line long enough not to repeat by chance, looked for
#: among the last lines of one screenshot and the first of the next.
_MIN_SEAM_LINE = 25
_SEAM_LINES = 8
#: Lines that are never a seam: the clinic's letterhead (address, phones,
#: e-mail) and the person's header (name, date of birth, the visit's date).
#: Two separate papers of one visit print them alike at the top of each, and
#: a short paper's last lines are its first.
_NOT_A_SEAM = re.compile(
    r"www\.|https?://|@\w|\.com\b|\+?\s*38\s*\(?0\d|\bтел\b|тел\.|\bвул\.|\bпросп|\bбуд\.|\bтзов\b|\bтов\b|ліцензі|єдрпоу"
    r"|ел\.?\s*пошта|e-?mail|прізвище|\bпіб\b|пацієнт\w*\s*[:：]"
    r"|дата\s+(?:народження|звернення|візиту|прийому|обстеження|консультації)",
    re.I,
)


@dataclass(frozen=True)
class _PageText:
    """What one document's stored page text says, print noise removed."""

    key: str  # every word, sorted: the same-text test
    words: frozenset[str]  # distinct words of four letters or more, no digits
    figures: frozenset[str]  # distinct tokens with a digit: sizes, values, dates
    numbers: frozenset[str]
    stamps: frozenset[str]  # ISO date and minute
    lines: frozenset[str]  # every long line
    head: tuple[str, ...]  # the first and the last long lines, for scroll seams
    tail: tuple[str, ...]


def _page_texts(connection, document_ids: list[str]) -> dict[str, _PageText]:
    """Document id → its page text, native and OCR, case-folded, local file
    paths and print noise left out.

    The key is the words sorted, because a re-export of one report moves whole
    blocks: Expert Hospital's soft-tissue ultrasound came back with its footer
    above the doctor's line, which no in-order comparison survives (sandbox,
    2026-11-06)."""
    lines: dict[str, list[str]] = {}
    for start in range(0, len(document_ids), 500):
        chunk = document_ids[start:start + 500]
        for row in connection.execute(
            f"""SELECT document_id, native_text, ocr_text FROM document_pages
                 WHERE document_id IN ({",".join("?" * len(chunk))}) ORDER BY document_id, page_number""",
            chunk,
        ):
            lines.setdefault(str(row["document_id"]), []).extend(
                _PRINT_NOISE.sub(" ", line)
                for line in combined_page_text(dict(row)).splitlines()
                if not _LOCAL_PATH_LINE.search(line)
            )
    found: dict[str, _PageText] = {}
    for document_id, raw in lines.items():
        text = "\n".join(raw)
        folded = [" ".join(_NOT_LETTER_OR_DIGIT.sub(" ", line.casefold()).split()) for line in raw]
        words = [word for line in folded for word in line.split()]
        long_lines = [line for line in folded if len(line) >= _MIN_SEAM_LINE]
        seam_lines = [
            line for line, printed in zip(folded, raw)
            if len(line) >= _MIN_SEAM_LINE and not _NOT_A_SEAM.search(printed)
        ]
        found[document_id] = _PageText(
            key=" ".join(sorted(words)),
            words=frozenset(word for word in words if len(word) >= 4 and not any(c.isdigit() for c in word)),
            figures=frozenset(word for word in words if len(word) >= 2 and any(c.isdigit() for c in word)),
            numbers=frozenset(
                number for number in _ORDER_NUMBER.findall(text) if not _PHONE_NUMBER.fullmatch(number)
            ),
            stamps=frozenset(
                f"{year}-{int(month):02d}-{int(day):02d}T{int(hour):02d}:{minute}"
                for day, month, year, hour, minute in _STAMP.findall(text)
                if int(hour) < 24 and int(minute) < 60 and 1 <= int(month) <= 12 and 1 <= int(day) <= 31
            ),
            lines=frozenset(long_lines),
            head=tuple(seam_lines[:_SEAM_LINES]),
            tail=tuple(seam_lines[-_SEAM_LINES:]),
        )
    return found


def _text_key(page_text: _PageText | None) -> str:
    """The same-text key, or '' when there is too little text to compare."""
    if page_text is None or len(page_text.key.replace(" ", "")) < _MIN_TEXT_KEY:
        return ""
    return page_text.key


def _result_fingerprints(connection, document_id: str) -> set[tuple[object, ...]]:
    return {
        _result_fingerprint(row)
        for row in connection.execute(
            """SELECT concept_id, value_numeric, value_text, unit_canonical, observed_at
                 FROM observations WHERE document_id=? AND verification_status <> 'rejected'""",
            (document_id,),
        )
    }


def _newer_first(document, document_id: str, other) -> tuple[str, str]:
    """Newer → older, so the relation reads "this one repeats that one"."""
    mine = (str(document["imported_at"] or ""), document_id)
    theirs = (str(other["imported_at"] or ""), str(other["id"]))
    return (document_id, str(other["id"])) if mine >= theirs else (str(other["id"]), document_id)


def _report_number_relation(document, document_id: str, other) -> tuple[str, str, str] | None:
    if not (document["report_number"] and other["report_number"] == document["report_number"]):
        return None
    # One report number, one study: the same report.  Issued on the
    # same day it is a duplicate; on another day, a reprint (pathology
    # № 40217/24 arrived under two orders, issued ten days apart).
    same_issue = (document["report_date"] or "") == (other["report_date"] or "")
    same_study = bool(document["collected_at"]) and document["collected_at"] == other["collected_at"]
    if not (same_issue or same_study):
        return None
    return (*_newer_first(document, document_id, other), "duplicate" if same_issue else "reprint")


def _attachment_relation(document, document_id: str, other) -> tuple[str, str, str] | None:
    if not (document["order_identifier"] and other["order_identifier"] == document["order_identifier"]):
        return None
    mine_cover = document["status"] in _COVER_STATUSES
    their_cover = other["status"] in _COVER_STATUSES
    if mine_cover == their_cover:
        return None
    export, cover = (str(other["id"]), document_id) if mine_cover else (document_id, str(other["id"]))
    return (export, cover, "attachment_of")


def _same_print(document, other) -> bool:
    """One print of one order: the same order and result times to the minute,
    and no order number that says otherwise (a half-size scan may have lost it)."""
    stamps = all(
        document[field] and "T" in str(document[field]) and document[field] == other[field]
        for field in ("collected_at", "issued_at")
    )
    orders = {str(row["order_identifier"]) for row in (document, other) if row["order_identifier"]}
    return stamps and len(orders) <= 1


def _shared_values_agree(mine: set, theirs: set) -> bool:
    """Every result both hold reads the same in both."""
    concepts = {key[0] for key in mine} & {key[0] for key in theirs}
    return bool(concepts) and {key for key in mine if key[0] in concepts} == {
        key for key in theirs if key[0] in concepts}


def _result_relation(document, document_id: str, other, mine: set, theirs: set) -> tuple[str, str, str]:
    other_id = str(other["id"])
    # A copy that lost rows to OCR is still the same report, not a part of it.
    if mine == theirs or (_same_print(document, other) and _shared_values_agree(mine, theirs)):
        return (*_newer_first(document, document_id, other), "duplicate")
    if mine > theirs:
        return (document_id, other_id, "contains")
    if theirs > mine:
        return (other_id, document_id, "contains")
    return (*_newer_first(document, document_id, other), "overlaps")


def _shared_result_relations(
    connection, owner_user_id: str, document, document_id: str, by_id: dict, relations: dict
) -> None:
    mine = _result_fingerprints(connection, document_id)
    dates = sorted({key[4] for key in mine if key[4]})
    if not (mine and dates):
        return
    sharing = connection.execute(
        f"""SELECT DISTINCT o.document_id FROM observations o JOIN documents d ON d.id=o.document_id
             WHERE o.owner_user_id=? AND d.patient_id=? AND o.document_id<>?
               AND d.duplicate_of_document_id IS NULL
               AND substr(o.observed_at, 1, 10) IN ({",".join("?" * len(dates))})""",
        (owner_user_id, document["patient_id"], document_id, *dates),
    ).fetchall()
    for row in sharing:
        other_id = str(row["document_id"])
        if other_id not in by_id:
            continue
        theirs = _result_fingerprints(connection, other_id)
        common = mine & theirs
        if not common:
            continue
        key = _result_relation(document, document_id, by_id[other_id], mine, theirs)
        relations.setdefault(key, (0.9, f"auto:shared_results:{len(common)}"))


#: Relation notes written from page text alone.
SAME_TEXT_NOTE = "auto:same_text"
CONTENT_HASH_NOTE = "auto:content_hash"
SAME_ORDER_NOTE = "auto:same_order"
PARTS_NOTE = "auto:parts"
PAGE_TEXT_NOTE = "auto:page_text"
#: Share of the smaller file's words found in the larger at which two prints
#: of one order are one report rather than a report and its supplement.
_SAME_REPORT_WORDS = 0.6
#: A photo of a report with no order number on it is matched by its words and
#: its figures (sizes, values, dates): nearly all of both must be in one
#: report, and clearly fewer in any other.  Measured on 124 phone photos of
#: one record (2026-11-07): one clinic's template reports share 85 % of their
#: words with each other and differ in their figures, and the next best
#: report trailed a true copy by at least 0.2.
_PAGE_WORDS = 0.85
_PAGE_FIGURES = 0.7
_PAGE_MARGIN = 0.2
_PAGE_MIN_WORDS = 30
_PAGE_MIN_FIGURES = 5


def _person_pairs(connection, document_ids: list[str]) -> set[frozenset[str]]:
    """Pairs a person answered about: nothing automatic is suggested for them."""
    pairs: set[frozenset[str]] = set()
    for start in range(0, len(document_ids), 500):
        chunk = document_ids[start:start + 500]
        for row in connection.execute(
            f"""SELECT source_document_id, target_document_id FROM document_relations
                 WHERE notes LIKE 'person:%' AND source_document_id IN ({",".join("?" * len(chunk))})""",
            chunk,
        ):
            pairs.add(frozenset((str(row[0]), str(row[1]))))
    return pairs


def _first_uploads(connection, document_ids: list[str]) -> dict[str, tuple[str, int]]:
    """Document id → (batch, place in the queue) of the upload that brought it
    in; a re-read is not an upload.  The queue's row order, not its clock: an
    album's files are enqueued within one second."""
    found: dict[str, tuple[str, int]] = {}
    for start in range(0, len(document_ids), 500):
        chunk = document_ids[start:start + 500]
        for row in connection.execute(
            f"""SELECT document_id, batch_id, MIN(rowid) place FROM upload_jobs
                 WHERE kind<>'rescan' AND document_id IN ({",".join("?" * len(chunk))}) GROUP BY document_id""",
            chunk,
        ):
            found[str(row["document_id"])] = (str(row["batch_id"]), int(row["place"]))
    return found


class _TextEvidence:
    """One patient's active documents read side by side: which two hold one
    report, by their page text, its order numbers and its order times."""

    def __init__(self, connection, rows) -> None:
        self.connection = connection
        self.rows = {str(row["id"]): row for row in rows}
        self.texts = _page_texts(connection, list(self.rows))
        self.anchored: dict[str, set[str]] = {}
        self.numbers: dict[str, set[str]] = {}
        for document_id, row in self.rows.items():
            text = self.texts.get(document_id)
            stored = {str(row[name] or "")[:10] for name in ("report_date", "collected_at", "issued_at")} - {""}
            self.anchored[document_id] = stored | {stamp[:10] for stamp in (text.stamps if text else ())}
            numbers = set(text.numbers) if text else set()
            order = re.sub(r"\D", "", str(row["order_identifier"] or ""))
            if order:
                numbers.add(order)
            self.numbers[document_id] = numbers
        # A number printed on files of different days is the letterhead's
        # (a trademark certificate, a company code), not an order's.
        holders: dict[str, list[str]] = {}
        for document_id, numbers in self.numbers.items():
            for number in numbers:
                holders.setdefault(number, []).append(document_id)
        self.letterhead = {
            number for number, ids in holders.items()
            if any(self._conflict(a, b) for index, a in enumerate(ids) for b in ids[index + 1:])
        }
        self._counts: dict[str, int] = {}

    def _conflict(self, a: str, b: str) -> bool:
        """Both files name the days they are about, and no day is shared."""
        return bool(self.anchored[a] and self.anchored[b] and not self.anchored[a] & self.anchored[b])

    def _specific(self, document_id: str) -> set[str]:
        return self.numbers[document_id] - self.letterhead

    def _stamps(self, document_id: str) -> frozenset[str]:
        text = self.texts.get(document_id)
        return text.stamps if text else frozenset()

    def same_order(self, a: str, b: str) -> bool:
        """Two files print one order: its number with a second sign (its day,
        its time), or its order and result times.  A short number alone is
        never enough; a long one is, unless the files are about other days."""
        stamps = self._stamps(a) & self._stamps(b)
        mine, theirs = self._specific(a), self._specific(b)
        numbers = mine & theirs
        if not (stamps or numbers) or self._conflict(a, b):
            return False
        if len(stamps) >= 2 or (stamps and numbers):
            return True
        if stamps:
            # One shared minute, and each names an order the other does not.
            return not (mine and theirs)
        return any(len(number) >= _LONG_ORDER_NUMBER for number in numbers) or bool(
            self.anchored[a] & self.anchored[b]
        )

    def candidate_pairs(self, focus: str | None):
        """Pairs that share an order number or an order time; with `focus`, only its own."""
        index: dict[str, set[str]] = {}
        for document_id in self.rows:
            for token in (self._specific(document_id) | set(self._stamps(document_id))):
                index.setdefault(token, set()).add(document_id)
        seen: set[frozenset[str]] = set()
        # ponytail: every pair under one token; a token on hundreds of files
        # (a letterhead number with no dates to expose it) costs its square.
        for ids in index.values():
            ordered = sorted(ids)
            for position, a in enumerate(ordered):
                for b in ordered[position + 1:]:
                    pair = frozenset((a, b))
                    if pair not in seen and (focus is None or focus in pair):
                        seen.add(pair)
                        yield a, b

    def is_image(self, document_id: str) -> bool:
        return str(self.rows[document_id]["mime_type"] or "").startswith("image/")

    def observation_count(self, document_id: str) -> int:
        if document_id not in self._counts:
            self._counts[document_id] = self.connection.execute(
                "SELECT COUNT(*) FROM observations WHERE document_id=? AND verification_status <> 'rejected'",
                (document_id,),
            ).fetchone()[0]
        return self._counts[document_id]

    def order_relation(self, a: str, b: str) -> tuple[str, str, str] | None:
        """How two files of one order relate: one report twice, a page of the
        other (a photo or screenshot), or a supplement printed beside it."""
        row_a, row_b = self.rows[a], self.rows[b]
        image_a, image_b = self.is_image(a), self.is_image(b)
        if image_a != image_b:
            return (b, a, "contains") if image_a else (a, b, "contains")
        if image_a:
            # Two photos of one order are its pages (see `parts`); the same
            # page photographed twice is found by `page_copies`.
            return None
        words_a = self.texts[a].words if a in self.texts else frozenset()
        words_b = self.texts[b].words if b in self.texts else frozenset()
        small, large = sorted((words_a, words_b), key=len)
        if not small:
            return None
        held = len(small & large) / len(small)
        if held >= _SAME_REPORT_WORDS and len(small) * 2 >= len(large):
            return (*_newer_first(row_a, a, row_b), "duplicate")
        if held >= _SAME_REPORT_WORDS:
            larger, smaller = (a, b) if small is words_b else (b, a)
            return (larger, smaller, "contains")
        # Mostly other words, same order: the illustrated companion or the
        # cytology passport printed beside the report.  The report is the one
        # with more results; between equals, the earlier import.
        main = max((a, b), key=lambda item: (self.observation_count(item), _newer_first(row_a, a, row_b)[1] == item))
        return (b if main == a else a, main, "attachment_of")

    def page_copies(self, focus: str | None):
        """(report, photo, relationship) for photos matched by page text alone.

        A photo of a consultation or an ultrasound protocol prints no order
        number, so it is compared word for word with every other file.  A
        photo held almost whole by one report is a picture of that report
        (`contains`); two photos holding each other almost whole are one page
        photographed twice (`duplicate`)."""
        candidates = [item for item in self.rows if item in self.texts]
        # ponytail: each photo against every file, O(photos x files) set
        # intersections; an inverted word index if records reach thousands.
        only = focus if focus is not None and self.is_image(focus) else None
        for photo in candidates:
            if not self._photo_eligible(photo, only):
                continue
            scores = self._photo_scores(photo, candidates)
            report = self._photo_contained_in(photo, scores, focus)
            if report is not None:
                yield report, photo, "contains"
            yield from self._photo_twins(photo, scores, only, focus)

    def _photo_eligible(self, photo: str, only: str | None) -> bool:
        if not self.is_image(photo) or (only and photo != only):
            return False
        mine = self.texts[photo]
        return len(mine.words) >= _PAGE_MIN_WORDS and len(mine.figures) >= _PAGE_MIN_FIGURES

    def _photo_scores(self, photo: str, candidates: list[str]) -> list[tuple[float, float, str]]:
        mine = self.texts[photo]
        return sorted(
            (
                len(mine.words & self.texts[other].words) / len(mine.words),
                len(mine.figures & self.texts[other].figures) / len(mine.figures),
                other,
            )
            for other in candidates if other != photo
        )

    def _photo_contained_in(self, photo: str, scores: list[tuple[float, float, str]], focus: str | None) -> str | None:
        reports = [item for item in scores if not self.is_image(item[2])]
        if not reports:
            return None
        words, figures, report = reports[-1]
        # The next best, not counting a second file of the same report
        # (an unmarked re-export would otherwise hide every photo of it).
        runner_up = max(
            (item[0] for item in reports[:-1] if not self._same_page(report, item[2])), default=0.0
        )
        if (
            words >= _PAGE_WORDS and figures >= _PAGE_FIGURES and words - runner_up >= _PAGE_MARGIN
            and not self._conflict(photo, report) and (focus is None or focus in (photo, report))
        ):
            return report
        return None

    def _photo_twins(self, photo: str, scores: list[tuple[float, float, str]], only: str | None, focus: str | None):
        for _, _, other in scores:
            if not self.is_image(other) or (not only and other < photo) or (
                focus is not None and focus not in (photo, other)
            ):
                continue
            if self._same_page(photo, other) and not self._conflict(photo, other):
                yield (*_newer_first(self.rows[photo], photo, self.rows[other]), "duplicate")

    def _same_page(self, a: str, b: str) -> bool:
        """Nearly every word and figure of each is in the other."""
        mine, theirs = self.texts[a], self.texts[b]
        common_words, common_figures = len(mine.words & theirs.words), len(mine.figures & theirs.figures)
        return (
            common_words >= 0.9 * max(len(mine.words), len(theirs.words), 1)
            and common_figures >= 0.8 * max(len(mine.figures), len(theirs.figures), 1)
        )

    def _upload_chains(self) -> list[list[str]]:
        """The images of each upload batch that holds two or more, in queue order."""
        uploads = _first_uploads(self.connection, [item for item in self.rows if self.is_image(item)])
        batches: dict[str, list[tuple[int, str]]] = {}
        for document_id, (batch, place) in uploads.items():
            batches.setdefault(batch, []).append((place, document_id))
        chains: list[list[str]] = []
        for members in batches.values():
            if len(members) < 2:
                continue
            members.sort()
            chains.append([document_id for _, document_id in members])
        return chains

    def parts(self, focus: str | None):
        """(later part, first part) for screenshots of one report uploaded together.

        A phone screenshots a long report page by page; each image arrives as
        a document of its own.  Consecutive images of one upload batch are one
        report when they print the same order (number, times), or when a line
        near the end of one is near the start of the next and no other file
        of the record prints it: the seam where one scroll position overlaps
        the next.  A letterhead repeats at the top of every page, never at
        the bottom of one and the top of the next.  The chain is kept to the
        first image."""
        for ordered in self._upload_chains():
            yield from self._chain_parts(ordered, focus)

    def _chain_parts(self, ordered: list[str], focus: str | None):
        head: dict[str, str] = {}
        for position, current in enumerate(ordered):
            for previous in reversed(ordered[max(0, position - 2):position]):
                if self._one_report(previous, current):
                    head[current] = head.get(previous, previous)
                    if focus is None or focus in (current, head[current]):
                        yield current, head[current]
                    break

    def _one_report(self, a: str, b: str) -> bool:
        if self.same_order(a, b):
            return True
        stamps_a, stamps_b = self._stamps(a), self._stamps(b)
        mine, theirs = self._specific(a), self._specific(b)
        if self._conflict(a, b) or (stamps_a and stamps_b and not stamps_a & stamps_b) or (
            mine and theirs and not mine & theirs
        ):
            return False
        if a not in self.texts or b not in self.texts:
            return False
        seam = set(self.texts[a].tail) & set(self.texts[b].head)
        return any(
            not any(line in text.lines for other, text in self.texts.items() if other not in (a, b)) for line in seam
        )


def _text_groups(evidence, ids: list[str]) -> dict[tuple[str, str], list[str]]:
    groups: dict[tuple[str, str], list[str]] = {}
    for document_id in ids:
        key = _text_key(evidence.texts.get(document_id))
        if key:
            groups.setdefault(("text", key), []).append(document_id)
            content_hash = str(evidence.rows[document_id]["content_sha256"] or "")
            if content_hash:
                groups.setdefault(("hash", content_hash), []).append(document_id)
    return groups


def _duplicate_proposals(evidence):
    """Documents whose page text or content hash is the same, one proposal per pair."""
    groups = _text_groups(evidence, list(evidence.rows))
    for (kind, _), members in sorted(groups.items()):
        for position, a in enumerate(members):
            for b in members[position + 1:]:
                yield (
                    (*_newer_first(evidence.rows[a], a, evidence.rows[b]), "duplicate"), 0.9,
                    SAME_TEXT_NOTE if kind == "text" else CONTENT_HASH_NOTE, True,
                )


def _order_proposals(evidence, focus: str | None):
    """Pairs of documents that print the same order, with the relation the evidence gives."""
    for a, b in evidence.candidate_pairs(focus):
        if evidence.same_order(a, b):
            key = evidence.order_relation(a, b)
            if key:
                yield key, 0.8 if key[2] == "duplicate" else 0.7, SAME_ORDER_NOTE, False


def _evidence_proposals(evidence, focus: str | None):
    """What the page text suggests, as (key, confidence, note, beside_results), in the order it is weighed."""
    yield from _duplicate_proposals(evidence)
    yield from _order_proposals(evidence, focus)
    for key in evidence.page_copies(focus):
        yield key, 0.7, PAGE_TEXT_NOTE, False
    for part, first in evidence.parts(focus):
        yield (part, first, "part_of"), 0.7, PARTS_NOTE, False


def _text_evidence_relations(
    connection, rows, relations: dict[tuple[str, str, str], tuple[float, str]], focus: str | None = None
) -> None:
    """Add to `relations` what the page text of one patient's active documents
    says: the same text, the same content hash, one order printed twice, a
    photo of a page, screenshots of one report in parts.  A pair a person
    answered about, or one already related, is left out."""
    evidence = _TextEvidence(connection, rows)
    ids = list(evidence.rows)
    taken = {frozenset((source, target)) for source, target, _ in relations}
    ruled = _person_pairs(connection, ids)

    def add(key: tuple[str, str, str], confidence: float, note: str, *, beside_results: bool = False) -> None:
        pair = frozenset(key[:2])
        if pair in ruled or (focus and focus not in pair) or (pair in taken and not beside_results):
            return
        taken.add(pair)
        relations.setdefault(key, (confidence, note))

    for key, confidence, note, beside_results in _evidence_proposals(evidence, focus):
        add(key, confidence, note, beside_results=beside_results)


_RELATION_COLUMNS = """id, patient_id, order_identifier, report_number, report_date, collected_at, issued_at,
    status, imported_at, mime_type, content_sha256"""


def record_document_relations(connection, owner_user_id: str, document_id: str) -> int:
    """Say how this document relates to the others in the record.

    Three cases arrived as separate, unlinked files: one pathology report
    exported under two orders, an ALEX² cover whose results are in a second
    PDF, and three Expert orders from one draw that print the same results.
    Each reads as new information when it is not, so each is recorded:
    `duplicate` (same printed report number and issue date, or the same
    results), `reprint` (same report number and study date, issued again),
    `contains` / `overlaps` (results in common), `attachment_of` (the export a
    cover points to, by order number).  The page text adds what files with no
    results to compare still say (`_text_evidence_relations`): the same words,
    the same order printed on a scan, a photo of one page, a supplement
    printed beside the report, screenshots of one report uploaded together
    (`part_of`).  Only this function's own rows (`notes` 'auto:…') are
    replaced; relations a person recorded stay, and a pair a person answered
    about gets no new suggestion.
    """
    connection.execute(
        """DELETE FROM document_relations
            WHERE (source_document_id=? OR target_document_id=?) AND notes LIKE 'auto:%'""",
        (document_id, document_id),
    )
    document = connection.execute(
        f"""SELECT {_RELATION_COLUMNS}, duplicate_of_document_id
             FROM documents WHERE id=? AND owner_user_id=?""",
        (document_id, owner_user_id),
    ).fetchone()
    if document is None or document["duplicate_of_document_id"]:
        return 0
    others = connection.execute(
        f"""SELECT {_RELATION_COLUMNS} FROM documents
            WHERE owner_user_id=? AND patient_id=? AND id<>? AND duplicate_of_document_id IS NULL""",
        (owner_user_id, document["patient_id"], document_id),
    ).fetchall()

    relations: dict[tuple[str, str, str], tuple[float, str]] = {}
    for other in others:
        key = _report_number_relation(document, document_id, other)
        if key:
            relations[key] = (1.0, "auto:report_number")
        key = _attachment_relation(document, document_id, other)
        if key:
            relations[key] = (1.0, "auto:order_identifier")
    by_id = {str(other["id"]): other for other in others}
    _shared_result_relations(connection, owner_user_id, document, document_id, by_id, relations)
    _text_evidence_relations(connection, [document, *others], relations, focus=document_id)
    for (source, target, relationship), (confidence, notes) in relations.items():
        connection.execute(
            """INSERT INTO document_relations(source_document_id, target_document_id, relationship, confidence, notes)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(source_document_id, target_document_id, relationship) DO UPDATE SET
                   confidence=excluded.confidence, notes=excluded.notes
               WHERE document_relations.notes LIKE 'auto:%'""",
            (source, target, relationship, confidence, notes),
        )
    return len(relations)


def _stored_relations(connection, ids: list[str]) -> dict[tuple[str, str, str], tuple[float, str]]:
    relations: dict[tuple[str, str, str], tuple[float, str]] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        for row in connection.execute(
            f"""SELECT source_document_id, target_document_id, relationship, confidence, notes
                  FROM document_relations WHERE source_document_id IN ({",".join("?" * len(chunk))})""",
            chunk,
        ):
            relations[(str(row[0]), str(row[1]), str(row[2]))] = (float(row[3]), str(row[4] or ""))
    return relations


def _insert_missing_relations(
    connection, relations: dict[tuple[str, str, str], tuple[float, str]], held: set[tuple[str, str, str]]
) -> int:
    added = 0
    for (source, target, relationship), (confidence, notes) in relations.items():
        if (source, target, relationship) not in held:
            added += connection.execute(
                """INSERT OR IGNORE INTO document_relations(
                       source_document_id, target_document_id, relationship, confidence, notes)
                   VALUES (?, ?, ?, ?, ?)""",
                (source, target, relationship, confidence, notes),
            ).rowcount
    return added


def repair_text_duplicates(connection) -> int:
    """Start-up repair: what page text says about documents already held.

    Relations are otherwise recorded only on import and re-read, so files
    imported before a check existed would never be linked: same-text
    duplicates, equal content hashes, one order printed twice, a photo of a
    page, a supplement, screenshots of one report.  One read of the stored
    page text per patient; idempotent, and a relation already present -- a
    person's above all -- is left as it is.  Copies of copies are pointed at
    the document kept first (`flatten_duplicate_chains`).
    """
    flattened = flatten_duplicate_chains(connection)
    documents = connection.execute(
        f"""SELECT owner_user_id, {_RELATION_COLUMNS} FROM documents
             WHERE duplicate_of_document_id IS NULL ORDER BY owner_user_id, patient_id"""
    ).fetchall()
    patients: dict[tuple[str, str], list] = {}
    for row in documents:
        patients.setdefault((str(row["owner_user_id"]), str(row["patient_id"])), []).append(row)
    added = 0
    for rows in patients.values():
        if len(rows) < 2:
            continue
        ids = [str(row["id"]) for row in rows]
        relations = _stored_relations(connection, ids)
        held = set(relations)
        _text_evidence_relations(connection, rows, relations)
        added += _insert_missing_relations(connection, relations, held)
    if added or flattened:
        connection.commit()
        logger.info("relations: %d pair(s) recorded from page text, %d copy chain(s) shortened", added, flattened)
    return added


def flatten_duplicate_chains(connection) -> int:
    """Point every copy at the document kept, never at another copy.

    Copies are kept one level deep, but a byte-identical upload of a file that
    was later marked a copy pointed at that copy: two copies of one Synevo
    report pointed at each other's original rather than at the document the
    lab order is linked to (sandbox, 2026-11-07).  Repeated until no copy
    points at a copy; a loop (which no write path makes) is left alone."""
    changed = 0
    for _ in range(10):
        step = connection.execute(
            """UPDATE documents SET duplicate_of_document_id=(
                   SELECT parent.duplicate_of_document_id FROM documents parent
                    WHERE parent.id=documents.duplicate_of_document_id)
                WHERE duplicate_of_document_id IN (
                   SELECT id FROM documents WHERE duplicate_of_document_id IS NOT NULL)
                  AND id<>(SELECT parent.duplicate_of_document_id FROM documents parent
                            WHERE parent.id=documents.duplicate_of_document_id)"""
        ).rowcount
        changed += step
        if not step:
            break
    return changed


# --- a person's answer to "these two are one report" -------------------------
#
# The relation above is a suggestion.  Marking a copy makes it what an exact
# byte duplicate is from import: `duplicate_of_document_id` set and no
# measurements of its own, so every value is counted once, from the document
# kept.  A person's answer is written to `document_relations` with notes
# 'person:…', which the automatic refresh never replaces.

#: The relation note that says "a person looked: these are different reports".
NOT_DUPLICATE_NOTE = "person:not_duplicate"


class DuplicateRefused(ValueError):
    """Marking or unmarking refused before anything changed; `key` is the catalogue message."""

    def __init__(self, key: str, **details: object) -> None:
        super().__init__(key)
        self.key = key
        self.details = details


def _record_person_relation(connection, first_id: str, second_id: str, note: str) -> None:
    """Upsert the pair's 'duplicate' row, newer → older as detection writes it."""
    order = {
        str(row["id"]): (str(row["imported_at"] or ""), str(row["id"]))
        for row in connection.execute(
            "SELECT id, imported_at FROM documents WHERE id IN (?, ?)", (first_id, second_id)
        )
    }
    source, target = (first_id, second_id) if order[first_id] >= order[second_id] else (second_id, first_id)
    connection.execute(
        """INSERT INTO document_relations(source_document_id, target_document_id, relationship, confidence, notes)
           VALUES (?, ?, 'duplicate', 1.0, ?)
           ON CONFLICT(source_document_id, target_document_id, relationship) DO UPDATE SET
               confidence=1.0, notes=excluded.notes""",
        (source, target, note),
    )


def _audit_document(connection, owner_user_id, actor_user_id, action, document_id, details) -> None:
    connection.execute(
        """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id,
               details_json, created_at) VALUES (?, ?, ?, 'document', ?, ?, ?)""",
        (owner_user_id, actor_user_id, action, document_id, json.dumps(details, ensure_ascii=False), utc_now()),
    )


def _is_ruled(row) -> bool:
    """A row a person spoke for: checked, corrected, set aside, typed or annotated."""
    if is_derived(row["extraction_method"]):
        return False  # calculated from other rows; follows them, nobody ruled on it
    return (
        row["verification_status"] in ("verified", "corrected", "rejected")
        or (row["entry_source"] or "document") != "document"
        or bool(str(row["note"] or "").strip())
    )


def _duplicate_pair(connection: sqlite3.Connection, owner_user_id: str, copy_id: str, primary_id: str) -> str:
    """The id of the document the copy duplicates, or a refusal."""
    found = {
        str(row["id"]): row
        for row in connection.execute(
            "SELECT id, patient_id, duplicate_of_document_id FROM documents WHERE owner_user_id=? AND id IN (?, ?)",
            (owner_user_id, copy_id, primary_id),
        )
    }
    if copy_id not in found or primary_id not in found:
        raise LookupError(copy_id if copy_id not in found else primary_id)
    copy = found[copy_id]
    if copy["duplicate_of_document_id"]:
        raise DuplicateRefused("dup.error_already")
    # Duplicates are kept one level deep: naming a copy means its original.
    primary_id = str(found[primary_id]["duplicate_of_document_id"] or primary_id)
    if primary_id == copy_id:
        raise DuplicateRefused("dup.error_self")
    primary = connection.execute(
        "SELECT id, patient_id FROM documents WHERE id=? AND owner_user_id=? AND duplicate_of_document_id IS NULL",
        (primary_id, owner_user_id),
    ).fetchone()
    if primary is None:
        raise DuplicateRefused("dup.error_self")
    if primary["patient_id"] != copy["patient_id"]:
        raise DuplicateRefused("dup.error_patient")
    if connection.execute(
        "SELECT 1 FROM upload_jobs WHERE document_id=? AND kind='rescan' AND state='running' LIMIT 1", (copy_id,)
    ).fetchone():
        raise DuplicateRefused("dup.error_busy")
    return primary_id


def _copy_rows_held_by_primary(connection: sqlite3.Connection, copy_id: str, primary_id: str):
    """The copy's observations and doses, refused when one a person ruled on
    is not also held, by content, by the kept document."""
    observation_sql = """SELECT id, raw_name, concept_id, value_numeric, value_text, unit_canonical, observed_at,
                                verification_status, entry_source, extraction_method, note
                           FROM observations WHERE document_id=?"""
    kept_rows = connection.execute(observation_sql, (primary_id,)).fetchall()
    held_any = {_result_fingerprint(row) for row in kept_rows}
    held = {_result_fingerprint(row) for row in kept_rows if row["verification_status"] != "rejected"}
    copy_rows = connection.execute(observation_sql, (copy_id,)).fetchall()
    unheld = [
        row for row in copy_rows
        if _is_ruled(row)
        and _result_fingerprint(row) not in (held_any if row["verification_status"] == "rejected" else held)
    ]
    # A test the kept document does not hold at all is lost with the copy's
    # rows: a Synevo lab record was set aside as a copy of its PDF, whose
    # parse had dropped the only result, and the record held it nowhere
    # (sandbox, 2026-11-07).  By test, not value: two prints of one report
    # that read a date or an interpretation differently are still one report;
    # a test is held when the kept document has its concept or its printed
    # name (an unmapped name gets a concept per vendor).
    kept_tests = {
        test
        for row in kept_rows if row["verification_status"] != "rejected"
        for test in (row["concept_id"], normalized_key(str(row["raw_name"] or "")))
    }
    missing = [
        row for row in copy_rows
        if row["verification_status"] != "rejected" and not is_derived(row["extraction_method"])
        and row["concept_id"] not in kept_tests and normalized_key(str(row["raw_name"] or "")) not in kept_tests
    ]
    if missing and not unheld:
        raise DuplicateRefused(
            "dup.error_missing",
            count=len(missing),
            observation_ids=[row["id"] for row in missing],
            dose_ids=[],
            labels=[str(row["raw_name"]) for row in missing],
        )
    dose_sql = """SELECT id, vaccine_code, product_name, occurrence_date, verification_status, entry_source
                    FROM immunizations WHERE document_id=?"""
    held_doses = {
        (row["vaccine_code"], str(row["occurrence_date"] or "")[:10])
        for row in connection.execute(dose_sql, (primary_id,))
    }
    copy_doses = connection.execute(dose_sql, (copy_id,)).fetchall()
    unheld_doses = [
        row for row in copy_doses
        if (row["verification_status"] != "extracted" or (row["entry_source"] or "document") != "document")
        and (row["vaccine_code"], str(row["occurrence_date"] or "")[:10]) not in held_doses
    ]
    if unheld or unheld_doses:
        raise DuplicateRefused(
            "dup.error_ruled",
            count=len(unheld) + len(unheld_doses),
            observation_ids=[row["id"] for row in unheld],
            dose_ids=[row["id"] for row in unheld_doses],
            labels=[str(row["raw_name"]) for row in unheld] + [str(row["product_name"] or row["vaccine_code"]) for row in unheld_doses],
        )
    return copy_rows, copy_doses


def _resolve_copy_tasks(
    connection: sqlite3.Connection, owner_user_id: str, copy_id: str, actor_user_id: str
) -> list[str]:
    resolved = [
        str(row["id"])
        for row in connection.execute(
            """SELECT id FROM review_tasks WHERE owner_user_id=? AND entity_type='document' AND entity_id=?
                 AND state='open'""",
            (owner_user_id, copy_id),
        )
    ]
    for task_id in resolved:
        connection.execute(
            """UPDATE review_tasks SET state='resolved', resolution='duplicate', assigned_user_id=?, resolved_at=?
                WHERE id=?""",
            (actor_user_id, utc_now(), task_id),
        )
        connection.execute(
            """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id,
                   details_json, created_at)
               VALUES (?, ?, 'review_task_resolved', 'review_task', ?, ?, ?)""",
            (owner_user_id, actor_user_id, task_id,
             json.dumps({"document_id": copy_id, "why": "duplicate"}), utc_now()),
        )
    return resolved


def mark_document_duplicate(
    connection: sqlite3.Connection,
    owner_user_id: str,
    copy_id: str,
    primary_id: str,
    actor_user_id: str,
    token_kind: str | None = None,
) -> dict[str, object]:
    """Make `copy_id` a duplicate of `primary_id`; the caller commits.

    Refused, with nothing changed, when the copy holds a value a person ruled
    on that the kept document does not hold by content (concept, value, unit,
    day): removing the copy's rows would otherwise throw that ruling away.
    """
    primary_id = _duplicate_pair(connection, owner_user_id, copy_id, primary_id)
    copy_rows, copy_doses = _copy_rows_held_by_primary(connection, copy_id, primary_id)

    removed = [str(row["id"]) for row in copy_rows]
    removed_doses = [str(row["id"]) for row in copy_doses]
    # observation_tags cascade and parser_issue_reports keep the report with
    # its observation set to NULL (both by foreign key).
    connection.execute("DELETE FROM observations WHERE document_id=?", (copy_id,))
    connection.execute("DELETE FROM immunizations WHERE document_id=?", (copy_id,))
    connection.execute(
        "UPDATE documents SET duplicate_of_document_id=? WHERE owner_user_id=? AND id=?",
        (primary_id, owner_user_id, copy_id),
    )
    # The copy's own exact duplicates follow it to the original.
    connection.execute(
        "UPDATE documents SET duplicate_of_document_id=? WHERE owner_user_id=? AND duplicate_of_document_id=?",
        (primary_id, owner_user_id, copy_id),
    )
    resolved = _resolve_copy_tasks(connection, owner_user_id, copy_id, actor_user_id)
    _record_person_relation(connection, copy_id, primary_id, "person:duplicate")
    details: dict[str, object] = {
        "primary_document_id": primary_id,
        "removed_observation_ids": removed,
        "removed_observation_count": len(removed),
        "removed_dose_ids": removed_doses,
        "resolved_review_task_ids": resolved,
    }
    if token_kind:
        details["token_kind"] = token_kind
    _audit_document(connection, owner_user_id, actor_user_id, "document_marked_duplicate", copy_id, details)
    refresh_derived_observations(connection)
    sync_clinical_findings(connection)
    return details


def unmark_document_duplicate(
    connection: sqlite3.Connection,
    owner_user_id: str,
    copy_id: str,
    actor_user_id: str,
    token_kind: str | None = None,
) -> str:
    """Make a marked copy a document of its own again; the caller commits and queues its re-read.

    A byte-identical copy is refused: it is the same file, and as a document of
    its own it would count every value twice.
    """
    row = connection.execute(
        """SELECT d.duplicate_of_document_id, d.sha256, p.sha256 primary_sha256
             FROM documents d LEFT JOIN documents p ON p.id=d.duplicate_of_document_id
            WHERE d.id=? AND d.owner_user_id=?""",
        (copy_id, owner_user_id),
    ).fetchone()
    if row is None:
        raise LookupError(copy_id)
    if not row["duplicate_of_document_id"]:
        raise DuplicateRefused("dup.error_not_duplicate")
    if row["sha256"] == row["primary_sha256"]:
        raise DuplicateRefused("dup.error_same_bytes")
    primary_id = str(row["duplicate_of_document_id"])
    connection.execute(
        "UPDATE documents SET duplicate_of_document_id=NULL WHERE id=? AND owner_user_id=?",
        (copy_id, owner_user_id),
    )
    _record_person_relation(connection, copy_id, primary_id, NOT_DUPLICATE_NOTE)
    details: dict[str, object] = {"primary_document_id": primary_id}
    if token_kind:
        details["token_kind"] = token_kind
    _audit_document(connection, owner_user_id, actor_user_id, "document_unmarked_duplicate", copy_id, details)
    return primary_id


def keep_both_documents(
    connection: sqlite3.Connection,
    owner_user_id: str,
    document_id: str,
    other_id: str,
    actor_user_id: str,
    token_kind: str | None = None,
) -> None:
    """A person's "these are different reports": the suggestion stops being made."""
    owned = connection.execute(
        "SELECT COUNT(*) FROM documents WHERE owner_user_id=? AND id IN (?, ?)",
        (owner_user_id, document_id, other_id),
    ).fetchone()[0]
    if document_id == other_id or owned != 2:
        raise LookupError(other_id)
    _record_person_relation(connection, document_id, other_id, NOT_DUPLICATE_NOTE)
    # Every automatic link between the two goes: a "part of", a "photo of a
    # page", a "supplement" is the same question answered.
    connection.execute(
        """DELETE FROM document_relations WHERE notes LIKE 'auto:%'
              AND ((source_document_id=? AND target_document_id=?) OR (source_document_id=? AND target_document_id=?))""",
        (document_id, other_id, other_id, document_id),
    )
    details: dict[str, object] = {"other_document_id": other_id}
    if token_kind:
        details["token_kind"] = token_kind
    _audit_document(connection, owner_user_id, actor_user_id, "document_kept_separate", document_id, details)


#: Stored classification answers already compared, by (document, page text).
_DRIFT_CACHE: dict[tuple[str, str], tuple[object, ...]] = {}


def classification_drift_ids(connection, owner_user_id: str) -> list[str]:
    """Documents the classifier now reads differently from what is stored.

    A re-read is the only thing that rewrites a document's title, kind, date,
    order number and collection/issue moments, and the stale check only ever
    looked at observation parser versions -- so a photo of a consultation dated
    by its upload day, whose classifier now reads the printed date, was never
    offered a re-read: it has no observations to be stale.  Fields a person set
    (`title_set_by`, `classified_by`, `report_date_set_by`) are not compared,
    since a re-read keeps them anyway.  Classified from stored page text, once
    per page-text hash per process.
    """
    rows = connection.execute(
        """SELECT id, original_filename, mime_type, content_sha256, title, title_set_by, clinical_type,
                  classified_by, report_date, report_date_set_by, order_identifier, collected_at, issued_at,
                  patient_id
             FROM documents WHERE owner_user_id=?
              -- A lab's own record of an order (labsync) was never classified
              -- from text: there is no reading for the classifier to redo.
              AND extraction_strategy <> 'lab_api'""",
        (owner_user_id,),
    ).fetchall()
    drifted = []
    for row in rows:
        expected = _expected_classification(connection, row)
        if expected is not None and not expected[4] and row["collected_at"]:
            # The page prints no collection time; the lab's own order does.
            expected = (*expected[:4], lab_order_collected_at(connection, str(row["id"])), *expected[5:])
        if expected is not None and expected[3]:
            order = checked_order(connection, row["patient_id"], str(expected[3]), expected[2], str(row["id"]))
            expected = (*expected[:3], order, *expected[4:])
        if expected is not None and _has_drifted(row, expected):
            drifted.append(str(row["id"]))
    return drifted


def _expected_classification(connection, row) -> tuple[object, ...] | None:
    """What the classifier reads today from the stored pages; None without pages."""
    # Only a hash of the page text can key the cache: without one, the same
    # id could stand for different text (another database, a test).
    key = (str(row["id"]), str(row["content_sha256"])) if row["content_sha256"] else None
    expected = _DRIFT_CACHE.get(key) if key else None
    if expected is not None:
        return expected
    pages = [
        dict(page)
        for page in connection.execute(
            """SELECT page_number, native_text, ocr_text, native_char_count, image_count, extraction_method
                 FROM document_pages WHERE document_id=? ORDER BY page_number""",
            (row["id"],),
        )
    ]
    if not pages:
        return None
    classification, _ = classify_pages(
        str(row["original_filename"] or ""), str(row["mime_type"] or ""), pages, {}
    )
    expected = (
        classification.title,
        classification.clinical_type,
        classification.report_date,
        classification.order_identifier,
        classification.collected_at,
        classification.issued_at,
    )
    if key:
        _DRIFT_CACHE[key] = expected
    return expected


def lab_order_collected_at(connection, document_id: str) -> str | None:
    """When the lab's own order of this document says the sample was taken
    («2024-11-15 11:42» as ``2024-11-15T11:42``), for a report that prints only
    its examination day: an Esculab POLYCHECK page, an Expert Hospital blood
    count.  Never later than the report's own day."""
    row = connection.execute(
        """SELECT o.ordered_at, d.report_date FROM lab_orders o JOIN documents d ON d.id=o.document_id
            WHERE o.document_id=? AND o.ordered_at IS NOT NULL ORDER BY o.ordered_at LIMIT 1""",
        (document_id,),
    ).fetchone()
    if row is None:
        return None
    moment = str(row["ordered_at"]).strip().replace(" ", "T")[:16]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?", moment):
        return None
    if row["report_date"] and moment[:10] > str(row["report_date"])[:10]:
        return None
    return moment


def _has_drifted(row, expected: tuple[object, ...]) -> bool:
    title, kind, report_date, order, collected, issued = expected
    human_kind = str(row["classified_by"] or "") == "human"
    human_date = human_kind or str(row["report_date_set_by"] or "") == "human"
    return bool(
        (str(row["title_set_by"] or "") != "human" and title != row["title"])
        or (not human_kind and kind != row["clinical_type"])
        or (not human_date and report_date != row["report_date"])
        or order != row["order_identifier"]
        or collected != row["collected_at"]
        or issued != row["issued_at"]
    )


def _content_concepts(connection, document_id: str) -> dict[tuple[object, ...], str | None]:
    """The concept each fingerprint of :func:`_content_counts` is filed under."""
    return {
        _fingerprint(row): row["concept_id"]
        for row in connection.execute(
            """SELECT page_number, raw_name, value_numeric, value_text, unit_canonical,
                      comparator, observed_at, concept_id
                 FROM observations WHERE document_id=? AND verification_status='extracted'
                  AND extraction_method <> ?""",
            (document_id, DERIVED_EGFR_METHOD),
        )
    }


def _fingerprint(row) -> tuple[object, ...]:
    return (
        int(row["page_number"] or 0),
        normalized_key(str(row["raw_name"] or "")),
        row["value_numeric"],
        collapse_space(str(row["value_text"] or "")),
        row["unit_canonical"] if row["value_numeric"] is not None else None,
        row["comparator"],
        row["observed_at"],
    )


def _renamed_count(
    gone: Counter[tuple[object, ...]], new: Counter[tuple[object, ...]],
    before: dict[tuple[object, ...], str | None], after: dict[tuple[object, ...], str | None],
) -> int:
    """Rows only the printed label changed on: same page, concept and value.
    «Колір (кал)» read again as «Колір» is neither a vanished value nor a new
    one, and 28 of them told a person to go looking for 28 lost results."""
    def by_concept(counter: Counter, concepts: dict) -> Counter:
        out: Counter[tuple[object, ...]] = Counter()
        for key, count in counter.items():
            concept = concepts.get(key)
            out[(key[0], concept, *key[2:]) if concept else key] += count
        return out
    return sum((by_concept(gone, before) & by_concept(new, after)).values())


def _content_counts(connection, document_id: str) -> Counter[tuple[object, ...]]:
    """What a document's unverified rows *say*, as a multiset.

    Ids are regenerated by every re-read and report groupings are rebuilt, so
    nothing structural survives to compare against.  This is the same test the
    archive cleanup uses to decide whether a snapshot holds anything the live
    record lacks: page, printed label, value, unit.  A `Counter` rather than a
    set, so a panel that genuinely prints the same measurement twice is not
    quietly counted once.
    """
    return Counter(
        _fingerprint(row)
        for row in connection.execute(
            """SELECT page_number, raw_name, value_numeric, value_text, unit_canonical,
                      comparator, observed_at
                 FROM observations WHERE document_id=? AND verification_status='extracted'
                  AND extraction_method <> ?""",
            (document_id, DERIVED_EGFR_METHOD),
        )
    )


# --- pairing a re-read with the rows a person already ruled on ---------------
#
# A re-read produces a fresh set of rows; some of them describe measurements a
# person already verified.  Matching on (page, printed label) -- the only rule
# there was -- broke every time the parser learnt to read a label better: the
# truncated «Скупчення лейкоцитів (WBC» and the full «… (WBC Clumps)» are one
# measurement, and the re-read inserted the second beside the first, verified
# duplicate and unverified twin, on every document whose labels improved.
#
# The rule now is the measurement, not the spelling.  Two rows are the same
# reading when they sit on the same page, say the same value with the same
# comparator, in the same unit, at the same moment -- and either name the same
# concept or carry labels one of which is the other cut short, wrapped or
# suffixed with «, <unit>».  A row the re-read reads *differently* is never
# applied over a person's check: it is listed in a review task instead.

#: A trailing «, <unit>» some layouts print as part of the label
#: («Питома вага, г/мл»).  Only unit-shaped tails: «Нейтрофіли, сегментоядерні»
#: is two analytes apart, not one with a unit.
#: Either tail holds no comma, so only the last comma can start one; the
#: first «/» or «%» splits the free-form tail without ambiguity.  The two
#: shapes are two patterns: a free-form tail with «/» or «%», and a bare unit.
_UNIT_SLASH_TAIL_RE = re.compile(r",[^,/%]*[/%][^,]*$")
_UNIT_WORD_TAIL_RE = re.compile(r",\s*(?:од\.?|мм|сек|с|мг|г|кл|клітин)\s*$", re.I)


def _strip_unit_tail(label: str) -> str:
    """The label without its «, <unit>» tail: the earlier of the two shapes'
    matches is cut, the free-form one when both start at the same comma, as
    one alternation of the two would."""
    tails = [found for found in (_UNIT_SLASH_TAIL_RE.search(label), _UNIT_WORD_TAIL_RE.search(label)) if found]
    if not tails:
        return label
    first = min(tails, key=lambda found: found.start())
    return label[: first.start()] + label[first.end() :]


def _label_key(raw_name: str | None) -> str:
    return normalized_key(_strip_unit_tail(collapse_space(str(raw_name or ""))))


def _labels_similar(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    if not longer.startswith(shorter):
        return False
    # A label cut at a word boundary, or one long enough that a mid-word cut
    # cannot be a different analyte.
    return longer[len(shorter)] == " " or len(shorter.split()) >= 3


def _labels_contain(left: str, right: str) -> bool:
    """One label inside the other at word boundaries, the shorter at least two
    words: an allergen code the old parse kept alone («Ani s 1») inside the
    full printed name the new one joins from its wrapped lines («Anisakis
    simplex Ani s 1 Kunitz Serin Protease Inhibitor»).  Only ever asked of two
    rows that already say the same reading."""
    if _labels_similar(left, right):
        return True
    shorter, longer = sorted((left, right), key=len)
    return len(shorter.split()) >= 2 and f" {shorter} " in f" {longer} "


def _moment(observed_at: object) -> str | None:
    text = str(observed_at or "")
    return text if "T" in text else None


def _same_moment(left: object, right: object) -> bool:
    a, b = _moment(left), _moment(right)
    return a is None or b is None or a == b


def _units_compatible(old: dict[str, object], new: dict[str, object]) -> bool:
    """Whether two numeric rows are in the same unit.

    A unit the re-read no longer prints is not a different unit: the checked
    one stands.  A unit it now prints where the checked row had none is new
    information about the reading, so it has to be shown to a person.
    """
    from ..reference import canonical_unit

    old_raw, new_raw = str(old.get("unit_raw") or ""), str(new.get("unit_raw") or "")
    if not new_raw:
        return True
    if not old_raw:
        return canonical_unit(str(old.get("unit_canonical") or "")) == canonical_unit(new_raw)
    return canonical_unit(old_raw) == canonical_unit(new_raw)


def _same_reading(old: dict[str, object], new: dict[str, object]) -> bool:
    old_number, new_number = old.get("value_numeric"), new.get("value_numeric")
    if (old_number is None) != (new_number is None):
        return False
    if str(old.get("comparator") or "") != str(new.get("comparator") or ""):
        return False
    if old_number is None:
        # A unit beside a qualitative answer («не виявлено», мг/дл) names the
        # dipstick's scale, not the reading, so it does not decide sameness.
        return normalized_key(str(old.get("value_text") or "")) == normalized_key(str(new.get("value_text") or ""))
    if not math.isclose(float(old_number), float(new_number), rel_tol=1e-9, abs_tol=1e-9):
        return False
    return _units_compatible(old, new)


def _reading(row: dict[str, object]) -> dict[str, object]:
    return {
        "numeric": row.get("value_numeric"),
        "text": row.get("value_text"),
        "comparator": row.get("comparator"),
        "unit": row.get("unit_raw") or (row.get("unit_canonical") if row.get("value_numeric") is not None else None),
        "printed": row.get("value_printed"),
    }


def _concept_twin(a: dict[str, object], b: dict[str, object]) -> bool:
    return (
        int(a["page_number"] or 0) == int(b["page_number"] or 0)
        and a.get("concept_id") == b.get("concept_id")
        and _same_reading(a, b)
    )


def _concept_fits(old: dict[str, object], new: dict[str, object]) -> bool:
    """Whether a loose pair may stand: the same concept, or a checked row filed
    under an auto concept.  A checked row under a catalogue analyte is not
    re-labelled as another catalogue analyte that shares its value and line:
    a verified «Білірубін» 5.1 is not «Білірубін прямий» 5.1."""
    previous = str(old.get("concept_id") or "")
    if previous and previous not in _DEFINED_CONCEPT_IDS:
        return True
    return bool(previous) and previous == str(new.get("concept_id") or "")


class _Pairing:
    """One pairing in progress: which rows each side has already given."""

    def __init__(self, preserved: list[dict[str, object]], fresh: list[dict[str, object]]) -> None:
        self.preserved = preserved
        self.fresh = fresh
        self.labels_old = [_label_key(row["raw_name"]) for row in preserved]
        self.labels_new = [_label_key(row["raw_name"]) for row in fresh]
        self.taken_old: set[int] = set()
        self.same: dict[int, int] = {}
        self.changed: dict[int, int] = {}

    def _free_new(self, index: int) -> bool:
        return index not in self.same and index not in self.changed

    def run(self, condition, into: dict[int, int]) -> None:
        for new_index, new in enumerate(self.fresh):
            if not self._free_new(new_index):
                continue
            old_index = self._first_old(condition, new_index, new)
            if old_index is not None:
                into[new_index] = old_index
                self.taken_old.add(old_index)

    def _first_old(self, condition, new_index: int, new: dict[str, object]) -> int | None:
        for old_index, old in enumerate(self.preserved):
            if old_index in self.taken_old:
                continue
            if int(old["page_number"] or 0) != int(new["page_number"] or 0):
                continue
            if not _same_moment(old.get("observed_at"), new.get("observed_at")):
                continue
            if condition(old_index, old, new_index, new):
                return old_index
        return None

    def same_label(self, oi, o, ni, n) -> bool:
        return self.labels_old[oi] == self.labels_new[ni] and _same_reading(o, n)

    def contained_label(self, oi, o, ni, n) -> bool:
        return _labels_contain(self.labels_old[oi], self.labels_new[ni]) and _same_reading(o, n) and _concept_fits(o, n)

    @staticmethod
    def same_line(oi, o, ni, n) -> bool:
        line = collapse_space(str(o.get("evidence_text") or ""))
        return (
            bool(line) and line == collapse_space(str(n.get("evidence_text") or ""))
            and _same_reading(o, n) and _concept_fits(o, n)
        )

    @staticmethod
    def corrected_line(oi, o, ni, n) -> bool:
        """The printed line a person corrected, read again.  The name and value
        were changed by the person, so no reading matches; the line does."""
        if str(o.get("verification_status")) != "corrected":
            return False
        line = str(o.get("evidence_text") or "").strip()
        return bool(line) and line == str(n.get("evidence_text") or "").strip()

    def _only_pair(self, oi, o, ni, n, alike) -> bool:
        """Whether `o` and `n` are the only free rows on either side that are `alike`."""
        olds = [i for i, row in enumerate(self.preserved) if i not in self.taken_old and alike(row, n)]
        news = [i for i, row in enumerate(self.fresh) if self._free_new(i) and alike(o, row)]
        return olds == [oi] and news == [ni]

    def unique_concept(self, oi, o, ni, n) -> bool:
        if not (o.get("concept_id") and o.get("concept_id") == n.get("concept_id") and _same_reading(o, n)):
            return False
        return self._only_pair(oi, o, ni, n, _concept_twin)

    def lone_number(self, oi, o, ni, n) -> bool:
        if o.get("value_numeric") is None or not _same_reading(o, n) or not _concept_fits(o, n):
            return False
        page = int(o["page_number"] or 0)

        def alike(a, b) -> bool:
            return int(a["page_number"] or 0) == page and _same_reading(a, b)

        return self._only_pair(oi, o, ni, n, alike)

    def differs(self, oi, o, ni, n) -> bool:
        if self.labels_old[oi] == self.labels_new[ni]:
            return True
        if str(o.get("verification_status")) not in ("verified", "corrected"):
            return False
        return bool(o.get("concept_id")) and o.get("concept_id") == n.get("concept_id") and _labels_similar(
            self.labels_old[oi], self.labels_new[ni]
        )


def pair_rereading(
    preserved: list[dict[str, object]], fresh: list[dict[str, object]]
) -> tuple[dict[int, int], dict[int, int]]:
    """Match freshly parsed rows to the rows a person ruled on.

    Both sides are dicts carrying `page_number`, `concept_id`, `raw_name`,
    `value_numeric`, `value_text`, `comparator`, `unit_raw`, `unit_canonical`,
    `observed_at`; preserved rows also `verification_status`.  Returns
    ``(same, changed)``: fresh index → preserved index, for rows that are the
    same reading, and for rows that are the same measurement read differently
    (a `rejected` row only under its exact label).  Every row pairs
    at most once.  The passes run strictest first, so the exact twin of a row
    is never stolen by a looser match to its neighbour.
    """
    pairing = _Pairing(preserved, fresh)
    # 1. Same label, same reading.
    pairing.run(pairing.same_label, pairing.same)
    # 2. Same reading under a label that grew or shrank.
    pairing.run(pairing.contained_label, pairing.same)
    # 2b. Same reading printed on the same line: the label the parser gives a
    #     row changed (St Paraskeva rows went from invented English names to
    #     the printed «Нейтрофіли (GRAN)-%»), the line it read did not.
    pairing.run(pairing.same_line, pairing.same)
    # 3. Same concept and reading under labels that share nothing -- a
    #    homoglyph spelling, a renamed row -- but only when unambiguous: the
    #    only such row on either side, or two equal urine counts with
    #    different names would trade labels.
    pairing.run(pairing.unique_concept, pairing.same)
    # 3b. A number that occurs once on the page on both sides, whatever either
    #     side calls it: «Total 25-hydroxyvitamin D» 32.122, the name the old
    #     parser invented, and «Вітамін D загальний» 32.122, the printed one.
    #     Numbers only -- «не виявлено» is printed on every other line.
    pairing.run(pairing.lone_number, pairing.same)
    # 4. The same measurement, read differently.  A row a person set aside
    #    stays set aside under its own label whatever the parser now reads
    #    there; it is not resurrected as a fresh row beside the rejection.
    pairing.run(pairing.differs, pairing.changed)
    # 5. A row a person corrected (name and value changed) whose printed line
    #    the re-read still reads: that fresh row is the line already corrected,
    #    so it is neither inserted beside the correction nor applied to it.
    pairing.run(pairing.corrected_line, pairing.same)
    return pairing.same, pairing.changed


def _keep_checked_concept(connection: sqlite3.Connection, old: dict[str, object], new: dict[str, object]) -> str:
    """The concept a refreshed checked row files under.

    The new label's own concept, unless the catalogue does not know that label
    while the checked row sat under a concept it does: «ШОЕ (SER)» is the line a
    person verified as erythrocyte sedimentation rate, and refiling it under an
    unmapped concept named after the label would drop it out of its trend.  The
    pairing is evidence that the label means the checked concept, so the label
    is learned for it (vendor-scoped, like any learned alias) -- which also
    files the next import of the same line correctly.  A catalogue definition
    still outranks a learned alias, so a later, better definition wins.
    """
    parsed: ParsedObservation = new["parsed"]  # type: ignore[assignment]
    concept_id = str(new["resolved"][0])  # type: ignore[index]
    previous = str(old.get("concept_id") or "")
    if not previous or previous == concept_id:
        return concept_id
    value_type = "numeric" if parsed.value_numeric is not None else "text"
    if concept_for_alias(parsed.raw_name, value_type) is not None:
        return concept_id
    # Only a catalogue concept is worth keeping over the new label's own: an
    # auto concept is a label too, and an inferred category does not make it
    # known.  Kept, a verified «16 генотип» held its bare concept and the
    # renamed «ПЛР. ВПЛ ВКР, 16 генотип» was learned onto it, so the clinic's
    # print never joined the lab record's series.
    if previous not in _DEFINED_CONCEPT_IDS:
        return concept_id
    vendor_id = connection.execute(
        "SELECT vendor_id FROM reports WHERE id=?", (new["report_id"],)
    ).fetchone()
    connection.execute(
        "UPDATE concept_aliases SET concept_id=? WHERE concept_id=? AND normalized_alias=? AND vendor_id IS ?",
        (previous, concept_id, normalized_key(parsed.raw_name), vendor_id["vendor_id"] if vendor_id else None),
    )
    return previous


def _refreshed_reference(
    old: dict[str, object], parsed: ParsedObservation, concept_id: str
) -> tuple[tuple[object, ...], object, dict[str, object] | None]:
    """(reference columns, verdict, the reference change to record or None)."""
    has_reference = bool(collapse_space(parsed.reference_text or "")) or (
        parsed.reference_low is not None or parsed.reference_high is not None
    )
    if not has_reference:
        reference = (
            old["vendor_reference_text"], old["vendor_reference_low"], old["vendor_reference_high"],
            old["vendor_reference_low_inclusive"], old["vendor_reference_high_inclusive"],
        )
        return reference, old["vendor_interpretation"], None
    reference = (parsed.reference_text, parsed.reference_low, parsed.reference_high, *parsed_inclusivity(parsed))
    verdict = parsed_interpretation(parsed, str(concept_id))
    item = None
    if collapse_space(str(old["vendor_reference_text"] or "")) != collapse_space(parsed.reference_text or ""):
        item = {
            "kind": "reference",
            "label": parsed.raw_name,
            "page": parsed.page_number,
            "old": collapse_space(str(old["vendor_reference_text"] or "")),
            "new": collapse_space(parsed.reference_text or ""),
        }
    return reference, verdict, item


def _refresh_checked_row(
    connection: sqlite3.Connection, old: dict[str, object], new: dict[str, object]
) -> tuple[dict[str, object], dict[str, object] | None]:
    parsed: ParsedObservation = new["parsed"]  # type: ignore[assignment]
    concept_id = _keep_checked_concept(connection, old, new)
    reference, verdict, reference_item = _refreshed_reference(old, parsed, concept_id)
    if old.get("vendor_interpretation_source") == "lab_record":
        # The laboratory's own structured flag (labsync) outranks any
        # reading of the printed range.
        verdict = old["vendor_interpretation"]
    # A row stamped with a time of day (a cuff reading) was paired on that
    # moment and keeps it; a dated row moves to the date the page gives.
    observed_at = old["observed_at"]
    if new["observed_at"] and not _moment(old["observed_at"]):
        observed_at = new["observed_at"]
    connection.execute(
        """UPDATE observations SET raw_name=?, evidence_text=?, concept_id=?, unit_raw=?, unit_canonical=?,
               vendor_reference_text=?, vendor_reference_low=?, vendor_reference_high=?,
               vendor_reference_low_inclusive=?, vendor_reference_high_inclusive=?,
               vendor_interpretation=?, value_printed=COALESCE(?, value_printed),
               specimen=COALESCE(?, specimen), note=COALESCE(?, note), observed_at=?, parser_version=?
           WHERE id=?""",
        (
            parsed.raw_name,
            parsed.evidence_text,
            concept_id,
            parsed.unit_raw or old["unit_raw"],
            new["unit_canonical"] if parsed.unit_raw else old["unit_canonical"],
            *reference,
            verdict,
            new.get("value_printed"),
            observation_specimen(parsed, new["page_class"].specimen),  # type: ignore[union-attr]
            getattr(parsed, "note", None),
            observed_at,
            PARSER_VERSION,
            old["id"],
        ),
    )
    entry: dict[str, object] = {"id": old["id"]}
    if str(old["observed_at"] or "")[:10] != str(observed_at or "")[:10]:
        entry["old_date"] = str(old["observed_at"] or "")[:10]
        entry["new_date"] = str(observed_at or "")[:10]
    return entry, reference_item


def _changed_readings(
    preserved: list[dict[str, object]], fresh: list[dict[str, object]], changed: dict[int, int]
) -> list[dict[str, object]]:
    changed_items: list[dict[str, object]] = []
    for new_index, old_index in changed.items():
        old, new = preserved[old_index], fresh[new_index]
        # A corrected value is a person's answer to exactly this question; the
        # parser disagreeing with it again is not news.
        if old["verification_status"] != "verified":
            continue
        changed_items.append(
            {
                "kind": "changed",
                "id": old["id"],
                "label": old["raw_name"],
                "page": old["page_number"],
                "old": _reading(old),
                "new": _reading(new),
            }
        )
    return changed_items


def _apply_pairs(
    connection: sqlite3.Connection,
    preserved: list[dict[str, object]],
    fresh: list[dict[str, object]],
    same: dict[int, int],
    changed: dict[int, int],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    """Bring checked rows up to today's reading of everything but the value.

    A verified row the re-read reads the same takes the new label, evidence,
    reference text, bounds and inclusivity, concept, specimen and printed
    precision, and the collection date -- it stays verified, because the
    number, unit and comparator a person checked are exactly what the page
    still says.  A reference the re-read cannot find is kept rather than
    erased.  Rows a person typed or corrected, and rejected rows, are not
    touched.  Returns what changed: refreshed rows (with any date move),
    rows read differently (applied to nothing), and reference changes.
    """
    refreshed: list[dict[str, object]] = []
    reference_items: list[dict[str, object]] = []
    for new_index, old_index in same.items():
        old, new = preserved[old_index], fresh[new_index]
        if old["verification_status"] != "verified" or str(old["extraction_method"] or "") in HUMAN_AUTHORED:
            continue
        entry, reference_item = _refresh_checked_row(connection, old, new)
        if reference_item:
            reference_items.append(reference_item)
        refreshed.append(entry)
    return refreshed, _changed_readings(preserved, fresh, changed), reference_items


_DOCUMENT_WITH_VENDOR_SQL = """SELECT d.*, v.canonical_name vendor_name FROM documents d
               LEFT JOIN vendors v ON v.id=d.vendor_id
               WHERE d.id=? AND d.owner_user_id=?"""


def _reread_source(settings: Settings, owner_user_id: str, document_id: str) -> Path:
    """The stored file to re-read, refused when there is none or it changed."""
    with connect(settings) as connection:
        document = connection.execute(_DOCUMENT_WITH_VENDOR_SQL, (document_id, owner_user_id)).fetchone()
    if document is None:
        raise LookupError(document_id)
    if document["extraction_strategy"] == "lab_api":
        # The lab's own record of an order with no PDF (labsync): its values
        # were never read from a file, and its next sync is what refreshes them.
        raise RereadRefused("intake.failed_reread_lab_record", f"{document_id}: a lab record has no file to re-read")
    path = resolve_source_path(settings, str(document["source_path"] or ""))
    if not path.is_file():
        raise FileNotFoundError(document["source_path"])
    # A rescan re-reads *the same bytes*: that is the whole reason it may keep
    # the document's id, its links and its SHA-256.  If the file at this path is
    # no longer the file that was imported, re-reading it files somebody else's
    # content under this document's identity while `documents.sha256` goes on
    # asserting the old bytes - and that hash is what duplicate detection
    # trusts, so the record would be wrong in two directions at once.
    if file_sha256(path) != str(document["sha256"] or ""):
        raise ValueError(f"{document_id}: {path.name} is no longer the file that was imported")
    return path


def _refuse_lost_ocr(connection: sqlite3.Connection, document_id: str, analysis: Analysis) -> None:
    new_pages = {int(page["page_number"]): page for page in analysis.pages}
    for old_page in connection.execute(
        "SELECT page_number, ocr_text FROM document_pages WHERE document_id=?",
        (document_id,),
    ):
        current_page = new_pages.get(int(old_page["page_number"]))
        if (
            current_page is not None
            and str(old_page["ocr_text"] or "").strip()
            and not str(current_page.get("ocr_text") or "").strip()
        ):
            # OCR unavailable/timed out is not evidence that the same
            # source no longer contains the previously read results.
            # Fail before replacing any rows or stored page evidence.
            raise RereadRefused(
                "intake.failed_reread_ocr",
                f"{document_id}: OCR returned no previously readable page evidence",
            )


def _reread_parse(connection: sqlite3.Connection, document, analysis: Analysis) -> tuple[list, list[ParseIssue]]:
    # First import deliberately leaves exact duplicates without their
    # own measurements. A re-read must keep that contract, otherwise
    # the same source suddenly adds a second set of historical values.
    parsed_with_context = []
    issues: list[ParseIssue] = []
    if not document["duplicate_of_document_id"]:
        date_of_birth, sex = patient_demographics(connection, str(document["patient_id"]))
        parsed_with_context = parse_pages(
            analysis.classification, analysis.per_page, analysis.pages,
            issues=issues, date_of_birth=date_of_birth, sex=sex,
        )
    return parsed_with_context, issues


def _refuse_emptying(
    connection: sqlite3.Connection, document, classification: Classification, parsed_with_context: list,
    document_id: str, issues: list[ParseIssue] | None = None,
) -> None:
    stored_rows = connection.execute(
        "SELECT COUNT(*) FROM observations WHERE document_id=? AND COALESCE(entry_source, 'document')='document'",
        (document_id,),
    ).fetchone()[0]
    chose_unparsed_kind = (
        str(document["classified_by"] or "") == "human"
        and classification.clinical_type in KNOWN_CLINICAL_TYPES
        and classification.clinical_type not in PARSED_CLINICAL_TYPES
    )
    if (
        stored_rows
        and not parsed_with_context
        and not document["duplicate_of_document_id"]
        and not chose_unparsed_kind
        # The parser recognised a companion summary of another report, whose
        # values that report holds: an empty reading here is the answer, not
        # a broken one, and the old rows are its interleaved columns.
        and not any(issue.kind == COMPANION_SUMMARY for issue in issues or [])
    ):
        # The same guard as OCR's, for the parser: a document that held
        # results and now reads as holding none has not lost them --
        # the reading broke (a kind nobody parses, a layout the parser
        # stopped recognising).  Deleting its unchecked rows on that
        # evidence is how a laboratory report lost 53 results.  Only a
        # person filing it as a kind with nothing to parse (an
        # ultrasound mistaken for a lab report) may empty it.
        raise RereadRefused(
            "intake.failed_reread_empty",
            f"{document_id}: re-read found no values where {stored_rows} were stored",
        )


def _update_reread_document(
    connection: sqlite3.Connection, document, analysis: Analysis, document_id: str, date_by_person: bool
) -> None:
    classification = analysis.classification
    seed_concepts(connection)
    vendor_id = ensure_vendor(connection, classification.vendor, classification.website)
    connection.execute(
        """UPDATE documents SET vendor_id=?, mime_type=?, content_sha256=?, page_count=?,
               title=?, clinical_type=?, extraction_strategy=?, classification_confidence=?,
               order_identifier=?, report_date=?, status=?, notes=?,
               collected_at=?, issued_at=?, report_number=? WHERE id=?""",
        (
            vendor_id,
            analysis.mime_type,
            analysis.content_hash,
            analysis.page_count,
            # A title a person chose is a ruling like a human
            # classification, not an observation about the file: the
            # re-read must not replace it with the classifier's guess.
            document["title"] if str(document["title_set_by"] or "") == "human"
            else classification.title,
            classification.clinical_type,
            classification.extraction_strategy,
            classification.confidence,
            checked_order(
                connection, document["patient_id"], classification.order_identifier, classification.report_date,
                document_id,
            ),
            # `_apply_human_classification` already put a person's
            # date on `classification`; this keeps it even when the
            # classifier read none.
            document["report_date"] if date_by_person else classification.report_date,
            classification.status,
            classification.notes,
            classification.collected_at or lab_order_collected_at(connection, document_id),
            classification.issued_at,
            classification.report_number,
            document_id,
        ),
    )


def _replace_pages(connection: sqlite3.Connection, document_id: str, analysis: Analysis) -> None:
    # A page that was signed off stays signed off; the reviewer looked
    # at the same image and a better parse does not unlook it.
    page_states = {
        int(row["page_number"]): str(row["review_status"])
        for row in connection.execute(
            "SELECT page_number, review_status FROM document_pages WHERE document_id=?",
            (document_id,),
        )
    }
    connection.execute("DELETE FROM document_pages WHERE document_id=?", (document_id,))
    for page in analysis.pages:
        connection.execute(
            """INSERT INTO document_pages(
                   document_id, page_number, native_text, ocr_text, native_text_sha256,
                   extraction_method, native_char_count, image_count, review_status
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                document_id,
                page["page_number"],
                page.get("native_text"),
                page.get("ocr_text"),
                page.get("native_text_sha256"),
                page["extraction_method"],
                page["native_char_count"],
                page["image_count"],
                page_states.get(int(page["page_number"]), "not_reviewed"),
            ),
        )


def _refile_ruled_rows(
    connection: sqlite3.Connection, document_id: str, preserved: list[dict[str, object]], page_to_report: dict
) -> set[str]:
    """Move checked rows and findings into the new reports; the ids left unfiled."""
    # A preserved value follows its page into the new grouping.  When
    # that page is not in the new parse at all - the file now reads as
    # three pages where it used to read as five - there is no honest
    # answer, and the old one was to file it under whichever report came
    # first: a checked measurement sitting under a heading that never
    # printed it, with its own `page_number` still naming a page the
    # document no longer has.  It is detached instead, and counted, so a
    # person is told rather than shown a confident wrong grouping.
    # (Detached rather than left as it was: `observations.report_id`
    # has no ON DELETE clause, so a row still pointing at the report
    # deleted below would abort the whole rescan on a foreign key.)
    unfiled_ids: set[str] = set()
    for row in preserved:
        report_id = page_to_report.get(int(row["page_number"] or 0))
        if report_id is None:
            unfiled_ids.add(str(row["id"]))
        connection.execute(
            "UPDATE observations SET report_id=? WHERE id=?", (report_id, row["id"])
        )
    # Findings a person checked have the same protection as checked
    # scalar results. Reassign them before deleting their old reports,
    # whose foreign key would otherwise cascade away the judgement.
    for finding in connection.execute(
        f"""SELECT id, page_number FROM clinical_findings WHERE document_id=?
            AND verification_status IN ({','.join('?' * len(HUMAN_RULED))})""",
        (document_id, *HUMAN_RULED),
    ).fetchall():
        connection.execute(
            "UPDATE clinical_findings SET report_id=? WHERE id=?",
            (page_to_report.get(int(finding["page_number"])), finding["id"]),
        )
    return unfiled_ids


def _fresh_rows(
    connection: sqlite3.Connection, parsed_with_context: list, page_to_report: dict, report_to_vendor: dict,
    date_by_person: bool,
) -> list[dict[str, object]]:
    fresh = []
    for parsed, page_class in parsed_with_context:
        report_id = page_to_report[parsed.page_number]
        concept_id, preferred_unit = resolve_parsed_concept(
            connection, parsed, report_id, report_to_vendor[report_id], page_class.specimen
        )
        fresh.append(
            {
                "parsed": parsed,
                "page_class": page_class,
                "report_id": report_id,
                "resolved": (concept_id, preferred_unit),
                "page_number": parsed.page_number,
                "concept_id": concept_id,
                "raw_name": parsed.raw_name,
                "value_numeric": parsed.value_numeric,
                "value_text": parsed.value_text,
                "comparator": parsed.comparator,
                "unit_raw": parsed.unit_raw,
                "unit_canonical": stored_unit(parsed.unit_raw, preferred_unit),
                "observed_at": observation_date(parsed, page_class, human_date=date_by_person),
                "value_printed": getattr(parsed, "value_printed", None),
                "evidence_text": parsed.evidence_text,
            }
        )
    return fresh


def _insert_unpaired(
    connection: sqlite3.Connection, owner_user_id: str, patient_id: str, document_id: str,
    fresh: list[dict[str, object]], paired_new: set[int], report_to_vendor: dict,
) -> int:
    added = 0
    for index, item in enumerate(fresh):
        if index in paired_new:
            continue
        insert_observation(
            connection,
            owner_user_id=owner_user_id,
            patient_id=patient_id,
            document_id=document_id,
            report_id=item["report_id"],
            vendor_id=report_to_vendor[item["report_id"]],
            observed_at=item["observed_at"],
            parsed=item["parsed"],
            resolved=item["resolved"],
            specimen=item["page_class"].specimen,
        )
        added += 1
    return added


def _orphaned_items(
    connection: sqlite3.Connection, owner_user_id: str, preserved: list[dict[str, object]],
    paired_old: set[int], unfiled_ids: set[str],
) -> list[dict[str, object]]:
    # A person who answered "keep" to "the re-read no longer finds
    # this" has answered it; the next re-read does not ask again.
    kept_ids = {
        str(row["entity_id"])
        for row in connection.execute(
            """SELECT entity_id FROM audit_events
                WHERE entity_type='observation' AND action='observation_reread_kept'
                  AND owner_user_id=?""",
            (owner_user_id,),
        )
    }
    return [
        {
            "kind": "orphaned",
            "id": row["id"],
            "label": row["raw_name"],
            "page": row["page_number"],
            "old": _reading(row),
        }
        for index, row in enumerate(preserved)
        if index not in paired_old
        and row["verification_status"] == "verified"
        and str(row["extraction_method"] or "") not in HUMAN_AUTHORED
        and row["id"] not in unfiled_ids
        and row["id"] not in kept_ids
    ]


def _paired_values(fresh: list[dict[str, object]], paired_new: set[int]) -> Counter[tuple[object, ...]]:
    return Counter(
        (
            int(item["page_number"] or 0),
            normalized_key(str(item["raw_name"] or "")),
            item["value_numeric"],
            collapse_space(str(item["value_text"] or "")),
            item["unit_canonical"] if item["value_numeric"] is not None else None,
            item["comparator"],
            item["observed_at"],
        )
        for index, item in enumerate(fresh)
        if index in paired_new
    )


def _reread_value_reasons(
    appeared: int, vanished: int, unchecked: int,
    changed_items: list[dict[str, object]], orphaned_items: list[dict[str, object]],
) -> list[dict[str, object]]:
    reasons = []
    if appeared:
        reasons.append(reason_part(REVIEW_RESCANNED_N, count=appeared, version=PARSER_VERSION))
    if vanished:
        reasons.append(reason_part("review.vanished_n", count=vanished))
    # A re-read with no news still has to say something true about a
    # document whose values nobody has checked, or the document falls
    # off the queue.  Saying it here rather than leaving the previous
    # task in place is what keeps a *stale* rescan sentence -- written
    # about rows this pass has just replaced -- from outliving the parse
    # it described.  Documents with nothing to verify (an ultrasound,
    # a consultation) produce no reason and keep whatever task they
    # have, which is the one asking a person to read the narrative.
    if not reasons and unchecked:
        reasons.append(reason_part(REVIEW_VERIFY_N, count=unchecked))
    # What the re-read found about values a person already checked.
    # Each is listed by name and value, so the task says which row to
    # open rather than that "something changed".
    if changed_items:
        reasons.append(reason_part(REVIEW_REREAD_CHANGED_N, count=len(changed_items), items=changed_items))
    if orphaned_items:
        reasons.append(reason_part(REVIEW_REREAD_ORPHANED_N, count=len(orphaned_items), items=orphaned_items))
    return reasons


def _audit_reread_refresh(
    connection: sqlite3.Connection, owner_user_id: str, document_id: str,
    reference_items: list[dict[str, object]], date_moves: Counter,
) -> None:
    # A checked value whose number, unit and comparator are what the
    # page still says, and only its reference, evidence or date was
    # re-read from the print, asks nobody anything: it is recorded,
    # not queued.  (The ALEX² panel alone put 291 such lines in a task.)
    if not (reference_items or date_moves):
        return
    connection.execute(
        """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id,
               details_json, created_at)
           VALUES (?, ?, 'observation_reread_refreshed', 'document', ?, ?, ?)""",
        (
            owner_user_id, owner_user_id, document_id,
            json.dumps(
                {
                    "parser_version": PARSER_VERSION,
                    "references": reference_items,
                    "dates": [
                        {"old": old_date, "new": new_date, "count": count}
                        for (old_date, new_date), count in sorted(date_moves.items(), key=str)
                    ],
                },
                ensure_ascii=False,
            ),
            utc_now(),
        ),
    )


def _reread_record_reasons(
    connection: sqlite3.Connection, document_id: str, unfiled: int, issues: list[ParseIssue],
    person_mismatch: bool = False,
) -> list[dict[str, object]]:
    reasons = []
    # Same wording and meaning as `_ingest_review_reasons`: a printed date of
    # birth that is someone else's may be a family member's report.
    if person_mismatch:
        reasons.append(reason_part("review.person_mismatch"))
    unchecked_doses = connection.execute(
        "SELECT COUNT(*) FROM immunizations WHERE document_id=? AND verification_status='extracted'",
        (document_id,),
    ).fetchone()[0]
    if unchecked_doses:
        reasons.append(reason_part(REVIEW_VACCINATIONS_N, count=unchecked_doses))
    unchecked_findings = connection.execute(
        "SELECT 1 FROM clinical_findings WHERE document_id=? AND verification_status='extracted' LIMIT 1",
        (document_id,),
    ).fetchone()
    if unchecked_findings:
        reasons.append(reason_part(REVIEW_FINDINGS))
    if unfiled:
        reasons.append(reason_part("review.unfiled_n", count=unfiled))
    reasons.extend(issue_parts(issues))
    return reasons


def _replace_open_tasks(
    connection: sqlite3.Connection, owner_user_id: str, document_id: str, reasons: list[dict[str, object]]
) -> None:
    if not reasons:
        return
    # The reasons already open on this document were written about
    # the rows this rescan has just replaced, so leaving them there
    # is how one document ends up carrying six review tasks that
    # each describe a different vanished parse.  They are superseded
    # rather than verified: nobody looked at anything.  Only closed
    # when there is a replacement to put in their place, so a
    # document with unchecked values is never left with no task at
    # all.
    connection.execute(
        """UPDATE review_tasks SET state='resolved', resolution='superseded', resolved_at=?
           WHERE owner_user_id=? AND entity_type='document' AND entity_id=?
             AND state='open'""",
        (utc_now(), owner_user_id, document_id),
    )
    open_review_task(connection, owner_user_id, document_id, reasons)


def reingest_document(
    settings: Settings,
    owner_user_id: str,
    document_id: str,
    run_ocr: bool = True,
) -> dict[str, object]:
    """Re-read a stored document with today's extractor, classifier and parser.

    This exists for the case where the software improved after the file was
    imported: a parser that now understands a layout, a classifier that now
    recognises a vendor, a concept that now has a canonical name.  Nothing
    about the file changed, so its identity does not - same document id, same
    bytes, same SHA-256, same position in every link that already points at it.

    What a person decided outranks what the parser decides.  Observations that
    were verified, corrected or set aside are never deleted and their value,
    unit and comparator are never rewritten; only rows still sitting at
    `extracted`, which nobody has looked at, are replaced by the current parse.
    Rows a person added or corrected from an AI suggestion are `extracted` too,
    but are kept like the checked rows.
    A freshly parsed row that is the same reading as a preserved one
    (`pair_rereading`) is not inserted; a verified twin takes the new label,
    evidence and reference (`_apply_pairs`).  A row read *differently*, and a
    verified row the parse no longer produces, are listed in a review task by
    name and value -- never applied, never silently kept as if confirmed.

    A re-read that would empty a document of results it had is refused
    (`RereadRefused`), the same way an OCR outage is.

    Page groupings and the document's own classification are refreshed, and the
    preserved observations follow their page into the new report - otherwise a
    document that now splits into two reports would keep half its values filed
    under a report that no longer describes them.
    """
    path = _reread_source(settings, owner_user_id, document_id)

    analysis = analyse_document(path, run_ocr=run_ocr)
    if not analysis.pages:
        # Every page grouping, every report and every page row is rebuilt from
        # this list.  An empty one committed the demolition and none of the
        # rebuilding: preserved observations filed under no report, no pages, no
        # reports, and a document that reads as blank rather than as unreadable.
        # A file that cannot be read is a failure, exactly like a missing one.
        raise ValueError(f"{document_id}: re-reading {path.name} produced no pages")
    # A classification a person made outranks the classifier's, the same way a
    # verified observation outranks a re-parse of it.  It has to be applied to
    # the *page* classifications too, not just the document's: `parse_pages`
    # dispatches per page, so a report named "laboratory" whose pages still read
    # as `consultation` would extract exactly as much as it did before, which is
    # nothing.  That is the whole point of naming it, and it is what makes the
    # naming survive the re-read the naming itself queues.
    with connect(settings) as connection:
        # A re-read runs in the background with nobody waiting on it, so it
        # waits out another writer rather than failing on the default five
        # seconds -- a rescan-stale batch on the sandbox lost a job that way.
        connection.execute("PRAGMA busy_timeout = 60000")
        connection.execute("BEGIN IMMEDIATE")
        try:
            # OCR can take minutes. A person may rename or classify the file
            # while it runs; fetch their latest decisions under the write lock
            # rather than restoring the stale snapshot taken before OCR.
            document = connection.execute(_DOCUMENT_WITH_VENDOR_SQL, (document_id, owner_user_id)).fetchone()
            if document is None:
                raise LookupError(document_id)
            analysis = _apply_human_classification(analysis, document)
            patient_id = str(document["patient_id"])
            date_of_birth, _sex = patient_demographics(connection, patient_id)
            if not _date_is_human(document):
                # The same rule as a first import; a date a person set stands.
                analysis = _plausible_analysis(analysis, date_of_birth)
            # The same check as a first import (ingest_file): a printed date of
            # birth that is not the patient's is queued on every re-read too, or
            # the first re-read that finds something else supersedes it silently.
            person_mismatch = _birth_date_mismatch(
                date_of_birth, " ".join(combined_page_text(page) for page in analysis.pages),
            )
            classification = analysis.classification
            _refuse_lost_ocr(connection, document_id, analysis)
            # Parse before touching anything: the parse depends on the file and
            # the classification only, and its result decides whether this
            # re-read may go ahead at all.
            parsed_with_context, issues = _reread_parse(connection, document, analysis)
            _refuse_emptying(connection, document, classification, parsed_with_context, document_id, issues)
            date_by_person = _date_is_human(document)
            _update_reread_document(connection, document, analysis, document_id, date_by_person)
            # A row a person added or corrected from an AI suggestion is stored
            # `extracted` (unverified), but nobody has merely looked at it: the
            # parser never finds an entry again, so deleting it would silently
            # undo the person's work.  It is kept, and pairs with the parse as
            # a checked row does (so a corrected value's original is not
            # re-inserted beside it); it is never refreshed or reported.
            preserved = [
                dict(row)
                for row in connection.execute(
                    f"""SELECT * FROM observations
                        WHERE document_id=? AND (verification_status IN
                              ({",".join("?" * len(HUMAN_RULED))})
                              OR COALESCE(extraction_method, '') LIKE 'ai_suggested%')
                        ORDER BY page_number, rowid""",
                    (document_id, *HUMAN_RULED),
                )
            ]
            # Every re-read replaces every unverified row, so counting the rows
            # it inserted counts the whole document -- and the review task then
            # asks a person to check 27 values none of which changed.  Re-reading
            # 61 files that way produced 61 tasks and 1307 values to verify, with
            # nothing at all different in any of them.  What is worth telling
            # somebody is the *difference*, so the rows about to be deleted are
            # fingerprinted by what they say -- page, printed label, value, unit
            # -- and compared against what this parse produces.
            previous_values = _content_counts(connection, document_id)
            previous_concepts = _content_concepts(connection, document_id)
            discarded = connection.execute(
                """DELETE FROM observations WHERE document_id=? AND verification_status='extracted'
                   AND COALESCE(extraction_method, '') NOT LIKE 'ai_suggested%'""",
                (document_id,),
            ).rowcount
            _replace_pages(connection, document_id, analysis)

            stale_reports = [
                str(row["id"])
                for row in connection.execute(
                    "SELECT id FROM reports WHERE document_id=?", (document_id,)
                )
            ]
            page_to_report, report_to_vendor = create_reports(
                connection,
                owner_user_id=owner_user_id,
                patient_id=patient_id,
                document_id=document_id,
                page_classes=analysis.per_page,
            )
            unfiled_ids = _refile_ruled_rows(connection, document_id, preserved, page_to_report)
            unfiled = len(unfiled_ids)
            if stale_reports:
                connection.execute(
                    f"DELETE FROM reports WHERE id IN ({','.join('?' * len(stale_reports))})",
                    stale_reports,
                )
            # `clinical_findings.report_id` cascades from `reports`, so the
            # delete above just took every narrative finding on this document
            # with it - an ultrasound or a consultation would have disappeared
            # from its health area until the next application start, which is
            # the only other place these are rebuilt.  Rebuilding them here, and
            # after the delete rather than before, is what makes a rescan of a
            # narrative report survive its own transaction.
            sync_clinical_findings(connection)

            doses = 0
            if not document["duplicate_of_document_id"]:
                doses = store_doses(
                    connection, classification, analysis.pages, owner_user_id, patient_id, document_id,
                    analysis.per_page,
                )
            fresh = _fresh_rows(connection, parsed_with_context, page_to_report, report_to_vendor, date_by_person)
            # Only what a parser could have produced takes part: a calculated
            # eGFR is derived from other rows, not read off the page, so the
            # parse can neither pair with it nor "lose" it.  Rows a person
            # typed or corrected still pair -- so the parser's own misreading
            # of them is not inserted beside them -- but are never refreshed,
            # flagged or reported missing (`_apply_pairs`, below).
            preserved = [row for row in preserved if not is_derived(row["extraction_method"])]
            same, changed = pair_rereading(preserved, fresh)
            refreshed, changed_items, reference_items = _apply_pairs(
                connection, preserved, fresh, same, changed
            )
            date_moves = Counter(
                (item["old_date"], item["new_date"]) for item in refreshed if item.get("old_date")
            )
            paired_new = set(same) | set(changed)
            added = _insert_unpaired(
                connection, owner_user_id, patient_id, document_id, fresh, paired_new, report_to_vendor
            )
            skipped = len(same) + len(changed)
            # A row a person verified that this parse does not produce at all.
            # Kept, because the check outranks the parser -- but never kept in
            # silence: «Приносний матеріал, сеча» was a verified analyte that
            # was really the specimen line, and it would have sat beside the
            # correctly read glucose pad for good.
            paired_old = set(same.values()) | set(changed.values())
            orphaned_items = _orphaned_items(connection, owner_user_id, preserved, paired_old, unfiled_ids)
            _store_positions_quietly(connection, document_id, path)
            record_document_relations(connection, owner_user_id, document_id)

            # Read back rather than fingerprinting `parsed`: `insert_observation`
            # rescales and canonicalises on the way in (urine relative density
            # off the x1000 scale, units folded), so comparing the parser's own
            # numbers against stored ones would report every such row as new.
            current_values = _content_counts(connection, document_id)
            appeared = sum((current_values - previous_values).values())
            # The direction nothing reported before, and the one that matters
            # most: a value the old parser found and this one does not. Silent
            # until now -- the row was deleted, the replacement never arrived,
            # and the document simply had less in it than the week before.
            # A row this parse read and paired with a checked row was produced
            # -- it simply was not inserted twice -- so it has not vanished.
            paired_values = _paired_values(fresh, paired_new)
            gone = previous_values - current_values - paired_values
            renamed = _renamed_count(gone, current_values - previous_values, previous_concepts,
                                     _content_concepts(connection, document_id))
            vanished = sum(gone.values()) - renamed
            appeared -= renamed

            search_content = " ".join(
                [
                    str(document["original_filename"] or ""),
                    classification.title,
                    classification.vendor,
                    classification.clinical_type,
                    " ".join(combined_page_text(page) for page in analysis.pages),
                    " ".join(item[0].raw_name for item in parsed_with_context),
                ]
            )
            index_search(connection, document_id, owner_user_id, search_content)
            # A companion summary holds nothing of its own: its old rows were
            # interleaved columns, so "vanished" would send a person looking
            # for values that the report it summarises already holds.
            companion = not parsed_with_context and any(issue.kind == COMPANION_SUMMARY for issue in issues)
            issues = [issue for issue in issues if issue.kind != COMPANION_SUMMARY]
            reasons = [reason_part(REVIEW_COMPANION_SUMMARY)] if companion else _reread_value_reasons(
                appeared, vanished, sum(current_values.values()), changed_items, orphaned_items
            )
            _audit_reread_refresh(connection, owner_user_id, document_id, reference_items, date_moves)
            reasons.extend(_reread_record_reasons(connection, document_id, unfiled, issues, person_mismatch))
            _replace_open_tasks(connection, owner_user_id, document_id, reasons)
            connection.execute(
                """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at)
                   VALUES (?, ?, 'rescan', 'document', ?, ?, ?)""",
                (
                    owner_user_id,
                    owner_user_id,
                    document_id,
                    json.dumps(
                        {
                            "parser_version": PARSER_VERSION,
                            "classification": asdict(classification),
                            "observations_added": added,
                            "observations_appeared": appeared,
                            "observations_vanished": vanished,
                            "observations_replaced": discarded,
                            "observations_preserved": len(preserved),
                            "observations_skipped_as_reviewed": skipped,
                            "observations_left_unfiled": unfiled,
                            "checked_refreshed": len(refreshed),
                            "checked_read_differently": changed_items,
                            "checked_not_found": orphaned_items,
                            "checked_reference_changed": len(reference_items),
                            "checked_dates_moved": sum(date_moves.values()),
                        },
                        ensure_ascii=False,
                    ),
                    utc_now(),
                ),
            )
            refresh_derived_observations(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "document_id": document_id,
        "action": "rescanned",
        "filename": str(document["original_filename"] or path.name),
        "vendor": classification.vendor,
        "clinical_type": classification.clinical_type,
        "observations": added,
        "immunizations": doses,
        "appeared": appeared,
        "vanished": vanished,
        "replaced": discarded,
        "preserved": len(preserved),
        "unfiled": unfiled,
        "refreshed": len(refreshed),
        "read_differently": len(changed_items),
        "not_found": len(orphaned_items),
        "parser_version": PARSER_VERSION,
    }


def ingest_directory(
    settings: Settings,
    owner_user_id: str,
    patient_id: str,
    source_dir: Path | None = None,
    run_ocr: bool = True,
) -> list[dict[str, object]]:
    directory = source_dir or settings.source_dir
    results = []
    for path in sorted(directory.rglob("*"), key=lambda item: str(item.relative_to(directory)).casefold()):
        if path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES:
            try:
                results.append(ingest_file(settings, owner_user_id, patient_id, path, run_ocr=run_ocr))
            except Exception as error:
                # One corrupt scan used to end the scan at that file: everything
                # alphabetically after it was never read, and the only sign was
                # a traceback where the summary should have been.  A bad file
                # stops itself, exactly as it does in the upload queue.  The
                # exception's own text is not recorded - it carries absolute
                # paths and sometimes the patient's filenames.
                logger.error("ingest: a %s file could not be read (%s)", path.suffix.lower() or "file", type(error).__name__)
                logger.debug("ingest: traceback", exc_info=True)
                results.append(
                    {"filename": path.name, "action": "failed", "error": type(error).__name__}
                )
    return results


def audit_inventory(settings: Settings, owner_user_id: str) -> dict[str, object]:
    with connect(settings) as connection:
        documents = [
            dict(row)
            for row in connection.execute(
                """SELECT d.id, d.original_filename, d.title, d.clinical_type, d.extraction_strategy,
                          d.classification_confidence, d.report_date, d.status, d.sha256,
                          d.duplicate_of_document_id, v.canonical_name AS vendor,
                          COUNT(o.id) AS observation_count
                   FROM documents d JOIN vendors v ON v.id=d.vendor_id
                   LEFT JOIN observations o ON o.document_id=d.id
                   WHERE d.owner_user_id=?
                   GROUP BY d.id ORDER BY d.report_date, d.original_filename""",
                (owner_user_id,),
            )
        ]
        counts = dict(
            connection.execute(
                """SELECT
                     (SELECT COUNT(*) FROM documents WHERE owner_user_id=?) AS documents,
                     (SELECT COUNT(*) FROM documents WHERE owner_user_id=? AND duplicate_of_document_id IS NOT NULL) AS duplicates,
                     (SELECT COUNT(*) FROM observations WHERE owner_user_id=?) AS observations,
                     (SELECT COUNT(*) FROM review_tasks WHERE owner_user_id=? AND state='open') AS open_reviews""",
                (owner_user_id, owner_user_id, owner_user_id, owner_user_id),
            ).fetchone()
        )
    return {"generated_at": utc_now(), "counts": counts, "documents": documents}
