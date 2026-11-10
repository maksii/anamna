"""/chat: discuss the record with the configured AI route (see :mod:`..chat`).

Access scope.  The chat reads exactly the record the request may read:
``record_user`` resolves it once, before the model is asked anything, and
every tool closes over that owner id -- a model can choose a metric or a
document, never an account.  Ids it supplies are always looked up together
with the owner, so another person's document id answers "not in this record".

* The owner chats about their own record.
* A person a record is shared with chats about the owner's record, read-only,
  and the conversation is theirs (``user_id`` is the viewer), so the owner
  never sees what a viewer asked.  Conversations are listed per record, and a
  revoked share hides the ones about that record.
* A guest link reaches no chat.  ``/chat`` is outside the guest allowlist in
  ``token_scope`` (403 by default), and that is the right answer, not an
  omission: a guest link exists to let a doctor *read* the record, while a
  chat stores conversations and spends the owner's paid AI budget on the
  visitor's questions -- two things an invitation to read never granted.
* An ``api`` credential reaches ``/api/*`` only, so no chat either.

Nothing here writes to the record: every tool is a read.
"""

from __future__ import annotations

import asyncio
import contextvars
import html
import json
import queue
import re
import threading
from collections.abc import Callable
from datetime import date

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from markupsafe import Markup
from starlette.concurrency import run_in_threadpool

from .. import chat
from ..ai import AIUnavailable, redact_document_text
from ..db import connect
from ..i18n import activate_locale, format_number_localized, get_locale, reset_locale, t, t_plural
from ..reference import RULE_CACHE
from . import ai_export as fx
from .ai_export import Sources, _code, judged

MAX_LIST = 30
NO_ARGUMENTS = {"type": "object", "properties": {}, "additionalProperties": False}
#: Page text one read_document call returns.  Cyrillic OCR text costs about one
#: token per two characters, so this is ~3k tokens.
DOCUMENT_TEXT_CHARS = 6000
HISTORY_ROWS = 120
#: Non-laboratory document kinds a visit or study produces.
VISIT_KINDS = (
    "consultation", "clinical_report", "radiology_mri", "radiology_xray", "ultrasound",
    "pathology", "diagnostic_image", "electrocardiogram", "microbiology",
)


# --- the record, as tools --------------------------------------------------------
#
# Everything a tool returns is resent on every later round of the same answer,
# so the text is written for tokens, not for eyes.  The grammar is explained
# once, in ``chat.RECORD_FORMAT``:
#
# * English, whatever the page language: the same record costs 13-38% more
#   tokens in Ukrainian (measured 2026-11-09) and the model answers in the
#   page's language either way.
# * One result per line, the verdict as the reference engine's own code.
# * Publishers as stable aliases (S1, S2, ...) with a ``Sources:`` legend for
#   the ones used, instead of a 100-character name on every line.
# * Document ids cut to their first eight characters (``d:fc0dcb5d``); the tools
#   accept the short form back.
# * History rows leave out whatever the row above already said.

DOC_ID_CHARS = 8


def _doc(document_id: object) -> str:
    return f"d:{str(document_id)[:DOC_ID_CHARS]}"


def _ids(url: object) -> str:
    """The id a tool takes back, in the short form ``RECORD_FORMAT`` names."""
    parts = [part for part in str(url or "").split("/") if part]
    if parts[:2] == ["devices", "metrics"] and len(parts) == 3:
        return f" key:{parts[2]}"
    if len(parts) == 2:
        return {"documents": f" {_doc(parts[1])}", "metrics": f" #{parts[1]}",
                "panels": f" panel:{parts[1]}", "areas": f" area:{parts[1]}"}.get(parts[0], "")
    return ""


def _clean_id(value: str) -> str:
    """An id as a model may write it back: ``d:…``, ``#…``, ``panel:…``, bracketed."""
    value = value.strip().strip("[]()").strip()
    for prefix in ("document_id:", "metric_id:", "panel_id:", "area_id:", "metric_key:",
                   "d:", "#", "panel:", "area:", "key:", "device:"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
    return value


def _text(args: dict, key: str, limit: int = 200) -> str:
    return " ".join(str(args.get(key) or "").split())[:limit]


def _int(args: dict, key: str, default: int = 0) -> int:
    try:
        return max(0, int(args.get(key) or default))
    except (TypeError, ValueError):
        return default


def _english(function: Callable[..., str], *args) -> str:
    token = activate_locale("en")
    try:
        return function(*args)
    finally:
        reset_locale(token)


def result_row(card: dict, sources: Sources | None, dated: str = "") -> str:
    """``- LDL cholesterol: 2.7 mmol/L @2026-11-05 high (<1.8 S3; ≠ …) ✓ #ldl-cholesterol``

    ``dated`` is the date every row of the output shares (a document's): a
    row on that date leaves it out.  Without ``sources`` the interval is left
    out too (the profile: the verdict is enough to choose what to read)."""
    verdict = card.get("verdict") or {}
    day = str(card.get("latest_date") or "-")[:10]
    text = (f"- {card['name']}: {fx._value_text(card)}{'' if day == dated else ' @' + day} "
            f"{_code(verdict.get('interpretation'))}{judged(verdict, sources) if sources else ''}")
    if str(card.get("verification_status")) in {"verified", "corrected"}:
        text += " ✓"
    return text + _ids(card.get("url"))


def _negatives(cards: list[dict]) -> tuple[list[dict], str]:
    """Allergen components below the cut-off as one count: an ALEX panel is
    ~300 of them and their names were 7k characters a call.  search_record
    still finds any single one ("birch") with its own line."""
    negative = [card for card in cards if card.get("panel_id") == "allergy"
                and fx._severity(card) == 3 and str((card.get("verdict") or {}).get("interpretation")) == "negative"]
    if len(negative) < fx.ALLERGEN_COLLAPSE_MIN:
        return cards, ""
    days = sorted({str(card.get("latest_date") or "")[:10] for card in negative} - {""})
    span = days[0] if len(days) == 1 else (f"{days[0]}..{days[-1]}" if days else "-")
    kept = [card for card in cards if card not in negative]
    return kept, (f"- {len(negative)} allergen components negative (below the cut-off) @{span}; "
                  "search_record finds one by name")


def _device_line(summary: dict) -> str:
    window = summary["months"] or summary["years"]
    recent = ""
    if window:
        days = sum(int(bucket["days"]) for bucket in window)
        mean = sum(float(bucket["mean"]) * int(bucket["days"]) for bucket in window) / max(days, 1)
        recent = (f"; mean {fx._num(mean, 4)} ({fx._num(min(float(b['min']) for b in window), 4)}-"
                  f"{fx._num(max(float(b['max']) for b in window), 4)}) over the last {days}d")
    return (f"- {summary['name']}: {fx._num(summary['latest_value'])} {summary['unit'] or ''} "
            f"@{summary['latest_day']}{recent}; {summary['day_count']}d since {summary['first_day']} "
            f"key:{summary['metric_key']}").replace("  ", " ")


def _device_detail(summary: dict) -> str:
    def buckets(rows: list[dict]) -> str:
        return "; ".join(
            f"{bucket['period']} {fx._num(bucket['mean'], 4)} ({fx._num(bucket['min'], 4)}-"
            f"{fx._num(bucket['max'], 4)}, {bucket['days']}d)" for bucket in rows
        )

    lines = [
        f"{summary['name']} ({summary['unit'] or 'no unit'}; daily {summary['aggregation']}; "
        f"{summary['day_count']}d since {summary['first_day']}; from {', '.join(map(str, summary['vendors']))})",
        "last 14 days: " + ", ".join(
            f"{str(day['day'])[5:]} {fx._num(day['value'])}" for day in summary["recent_days"][:14]),
    ]
    if summary["months"]:
        lines.append("monthly mean (min-max, days): " + buckets(summary["months"][:12]))
    if summary["years"]:
        lines.append("yearly: " + buckets(summary["years"]))
    return "\n".join(lines)


def build_tools(connection, owner_id: str) -> dict[str, chat.Tool]:
    """The read-only tools, every one bound to ``owner_id``."""
    from . import app as web
    from .. import allergy, genetics, testplan
    from .. import immunizations as vaccines
    from ..health import HEALTH_AREAS
    from ..i18n import translate_phrase

    sources = Sources(connection)

    def catalog() -> list[dict]:
        return web._metric_catalog(connection, owner_id, include_suppressed=True)

    def row(card: dict) -> str:
        return result_row(card, sources)

    def find_document(raw: str) -> str | None:
        key = _clean_id(raw)
        if not key:
            return None
        pattern = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = connection.execute(
            "SELECT id FROM documents WHERE owner_user_id = ? AND id LIKE ? ESCAPE '\\' LIMIT 2",
            (owner_id, pattern),
        ).fetchall()
        return str(rows[0][0]) if len(rows) == 1 else None

    def search_record(args: dict) -> str:
        query = _text(args, "query", 120)
        groups = web._record_search(connection, owner_id, query, 0) if query else []
        if not groups:
            return (f"Nothing matches {query!r}. Try another spelling, the English or Ukrainian name, "
                    "or list_results.")
        out = []
        for group in groups:
            rows = [*group["rows"], *group["more_rows"]]
            out.append(f"## {group['heading']} ({group['total']})")
            for item in rows[:20]:
                if group["key"] in ("metrics", "device_metrics"):
                    out.append(row(item))
                else:
                    out.append(f"- {item.get('title')}; {item.get('subtitle') or ''}".rstrip("; ") + _ids(item.get("url")))
            if group["total"] > 20:
                out.append(f"- +{group['total'] - 20} more; narrow the query")
        return "\n".join(out)

    def get_metric(args: dict) -> str:
        metric_id = _clean_id(_text(args, "metric_id", 120))
        rows = web._linked_observation_rows(connection, owner_id, metric_id) if metric_id else []
        if not rows:
            summaries = [item for item in web.device_history(connection, owner_id)
                         if str(item["metric_key"]) == metric_id]
            if summaries:
                return _device_detail(summaries[0])
            return f"No results for {metric_id!r}. search_record finds the id."
        _age, sex = web._demographics(connection, owner_id)
        patient = web._patient_row(connection, owner_id)
        birth = patient["date_of_birth"] if patient else None
        card = web._by_id(catalog()).get(metric_id)
        out = []
        if card:
            out.append(row(card))
            freshness = card.get("staleness") or {}
            if freshness.get("state") in {"overdue", "due_soon"} or freshness.get("due_on"):
                out.append(f"retest: {freshness.get('state')}" + (f", due {freshness['due_on']}" if freshness.get("due_on") else ""))
            if card.get("panel_id"):
                out.append(f"panel:{card['panel_id']}")
        entry = web._guidance_index(connection).get(metric_id) or {}
        about = " ".join(str(entry.get(key) or "").strip() for key in ("short_description", "why_it_matters")).strip()
        if about:
            out.append(f"about: {about}")
        out.append(f"history, newest first ({len(rows)}):")
        previous = {"judged": None, "lab": None, "source": None}
        for item in rows[:HISTORY_ROWS]:
            web._metric_history_row(connection, metric_id, item, birth, sex)
            verdict = item.get("verdict") or {}
            current = {
                "judged": judged(verdict, sources),
                "lab": "" if item.get("hide_lab") or not item.get("display_reference") else f" lab {item['display_reference']}",
                "source": " device" if item.get("is_device") else f" {item.get('vendor') or '-'} {_doc(item.get('document_id'))}",
            }
            text = (f"{str(item.get('observed_at') or '-')[:10]} {item['display_value']} {item['display_unit']}".rstrip()
                    + f" {_code(verdict.get('interpretation'))}")
            text += "".join(value for key, value in current.items() if value != previous[key])
            if str(item.get("verification_status")) in {"verified", "corrected"}:
                text += " ✓"
            out.append(text)
            previous = current
        if len(rows) > HISTORY_ROWS:
            out.append(f"+{len(rows) - HISTORY_ROWS} older readings")
        return "\n".join(out)

    def list_results(args: dict) -> str:
        area_id = _clean_id(_text(args, "area_id", 40))
        cards = [card for card in catalog() if not card.get("is_device")]
        if not area_id:
            out = ["Body systems (results, outside interval):"]
            for area in HEALTH_AREAS:
                members = [card for card in cards if area["id"] in card["area_ids"]]
                if members:
                    flagged = sum(1 for card in members if fx._severity(card) < 2)
                    out.append(f"- {translate_phrase(str(area['name']))} area:{area['id']} {len(members)}, {flagged}")
            return "\n".join(out)
        members = sorted((card for card in cards if area_id in card["area_ids"]),
                         key=lambda card: (fx._severity(card), str(card["name"])))
        if not members:
            return f"No results in {area_id!r}. list_results without area_id lists the areas."
        members, collapsed = _negatives(members)
        return "\n".join([*map(row, members), *([collapsed] if collapsed else [])])

    def documents_query(where: str = "", params: tuple = ()) -> list[dict]:
        return [web._document_row(item) for item in connection.execute(
            f"""SELECT d.id, d.title, d.original_filename, d.report_date, d.imported_at, d.clinical_type,
                       v.canonical_name vendor,
                       (SELECT COUNT(*) FROM observations o WHERE o.document_id = d.id
                         AND o.verification_status <> 'rejected') observation_count
                  FROM documents d LEFT JOIN vendors v ON v.id = d.vendor_id
                 WHERE d.owner_user_id = ? AND d.duplicate_of_document_id IS NULL {where}
                 ORDER BY d.report_date IS NULL, d.report_date DESC, d.imported_at DESC""",
            (owner_id, *params),
        )]

    def document_line(item: dict) -> str:
        count = int(item.get("observation_count") or 0)
        return (f"- {item.get('report_date') or '-'} {_document_name(item)}; {item.get('vendor')}"
                + (f"; {count} values" if count else "") + f" {_doc(item['id'])}")

    def list_documents(args: dict) -> str:
        query, kind, offset = _text(args, "query", 80).casefold(), _text(args, "kind", 40), _int(args, "offset")
        rows = documents_query()
        if kind:
            rows = [item for item in rows if item.get("clinical_type") == kind]
        if query:
            rows = [item for item in rows if query in " ".join(
                str(item.get(key) or "") for key in ("title_text", "original_filename", "vendor", "type_label")
            ).casefold()]
        page = rows[offset: offset + MAX_LIST]
        out = [f"{len(rows)} documents, newest first" + (f", {offset + 1}-{offset + len(page)}:" if rows else "")]
        out += [document_line(item) for item in page]
        if offset + len(page) < len(rows):
            out.append(f"+more: offset={offset + len(page)}")
        return "\n".join(out)

    def read_document(args: dict) -> str:
        raw, first_page = _text(args, "document_id", 80), _int(args, "page", 0)
        document_id = find_document(raw)
        subject = web._scope_document(connection, owner_id, document_id) if document_id else None
        if subject is None:
            return f"No document {raw!r} in this record. list_documents or search_record finds the id."
        document = subject["document"]
        out = [f"{_document_name(document)}; {document.get('vendor')}; {document.get('report_date') or '-'}; "
               f"{_doc(document_id)}"]
        observations = list(subject.get("observations") or ())
        if observations and not first_page:
            dated = str(document.get("report_date") or "")[:10]
            out.append(f"results ({len(observations)}; dated {dated or 'per row'} unless a row says @):")
            out += [result_row(fx._observation_card(item), sources, dated) for item in observations[:HISTORY_ROWS]]
        findings = list(dict.fromkeys(fx._finding_line(item) for item in subject.get("findings") or ()))
        if findings and not first_page:
            out += ["conclusions:", *findings]
        pages = connection.execute(
            """SELECT page_number, COALESCE(NULLIF(native_text, ''), ocr_text, '') text
                 FROM document_pages WHERE document_id = ? ORDER BY page_number""",
            (document_id,),
        ).fetchall()
        if not first_page and (observations or findings):
            # The results and conclusions are what was read from these pages;
            # the text itself is ~3k tokens a call and is fetched on request.
            if pages:
                out.append(f"text: {len(pages)} pages, not included; page=1 reads it")
            return "\n".join(out)
        first_page = max(1, first_page)
        shown, budget = [], DOCUMENT_TEXT_CHARS
        for page in pages:
            if page["page_number"] < first_page:
                continue
            text = redact_document_text(str(page["text"] or "")).strip()
            if shown and len(text) > budget:
                break
            shown.append((page["page_number"], text[:budget]))
            budget -= len(text)
        out.append(f"text ({len(pages)} pages, identifying lines removed):")
        for number, text in shown:
            out += [f"[p{number}]", text or "(no text)"]
        if shown and shown[-1][0] < len(pages):
            out.append(f"+more: page={shown[-1][0] + 1}")
        elif not pages:
            out.append("(no text was extracted)")
        return "\n".join(out)

    def list_visits(args: dict) -> str:
        offset = _int(args, "offset")
        by_document: dict[str, list[str]] = {}
        for item in web._finding_catalog(connection, owner_id):
            # One conclusion is filed under every body system it touches; the
            # line drops the date and provider the document line already has.
            text = str(item.get("title") or "")
            summary = " ".join(str(item.get("summary_en") or "").split())
            text = f"{text}: {summary}" if summary else text
            lines = by_document.setdefault(str(item["document_id"]), [])
            if text and text not in lines:
                lines.append(text)
        marks = ",".join("?" * len(VISIT_KINDS))
        documents = documents_query(
            f"AND (d.clinical_type IN ({marks}) OR d.id IN (SELECT document_id FROM clinical_findings WHERE owner_user_id = ?))",
            (*VISIT_KINDS, owner_id),
        )
        if not documents:
            return "No visit notes, consultations, imaging or other reports with conclusions."
        page = documents[offset: offset + MAX_LIST // 2]
        out = [f"{len(documents)} visits and reports, newest first, {offset + 1}-{offset + len(page)}; "
               "conclusions indented:"]
        for document in page:
            out.append(document_line(document))
            out += [f"  - {text}" for text in by_document.get(str(document["id"]), [])[:6]]
        if offset + len(page) < len(documents):
            out.append(f"+more: offset={offset + len(page)}")
        return "\n".join(out)

    def get_vaccinations(args: dict) -> str:
        doses = vaccines.doses_for(connection, owner_id)
        if not doses:
            return "No vaccinations recorded. A vaccination card or certificate can be uploaded."
        out = [f"{len(doses)} doses, oldest first:"]
        for dose in doses:
            diseases = ", ".join(vaccines._disease_names([key for key in str(dose.get("diseases") or "").split(",") if key]))
            series = ""
            if dose.get("dose_number"):
                series = f" dose {dose['dose_number']}" + (f"/{dose['doses_in_series']}" if dose.get("doses_in_series") else "")
            # The printed product name is long and in the card's language; the
            # code and the diseases say which vaccine it was.
            name = str(dose.get("vaccine_code") or "") or str(dose.get("product_name") or "")[:60]
            out.append(f"- {dose.get('occurrence_date') or '-'} {name} ({diseases}); {dose.get('manufacturer') or '-'}"
                       f"{series}{'; booster' if dose.get('event_kind') == 'revaccination' else ''}"
                       f"{' ✓' if dose.get('verification_status') in ('verified', 'corrected') else ''}")
        gaps = vaccines.find_gaps(doses, date.today())
        if gaps:
            out.append("outstanding per the national schedule:")
            out += [
                f"- {', '.join(vaccines._disease_names(list(gap.diseases)))}: {gap.kind}, {gap.urgency}"
                + (f", due {gap.due_date}" if gap.due_date else "") + (f", last {gap.last_date}" if gap.last_date else "")
                for gap in gaps
            ]
        return "\n".join(out)

    def get_devices(args: dict) -> str:
        key = _clean_id(_text(args, "metric_key", 80))
        summaries = web.device_history(connection, owner_id)
        if not summaries:
            return "No wearable or home-device data in this record."
        if key:
            match = [item for item in summaries if str(item["metric_key"]) == key]
            if not match:
                return f"No device metric {key!r}. get_devices without metric_key lists them."
            return _device_detail(match[0])
        return "\n".join(["Device metrics (latest @day; mean over the recent window; span):",
                          *map(_device_line, summaries)])

    def get_panel(args: dict) -> str:
        panel_id = _clean_id(_text(args, "panel_id", 60))
        if panel_id:
            subject = web._scope_panel(connection, owner_id, panel_id)
            if subject is None:
                return f"No panel {panel_id!r}. get_panel without panel_id lists them."
            return "\n".join([str(subject["label"]), *map(row, subject["cards"])])
        out = ["Panels (status, tests on file/in panel, flagged):"]
        for panel in web._panel_cards(connection, owner_id, member_limit=6):
            if panel["present_count"]:
                out.append(f"- {panel['name']} panel:{panel['id']} {panel['status']}, "
                           f"{panel['present_count']}/{panel['member_count']}, {panel['flagged_count']}")
        return "\n".join(out)

    def get_allergy(args: dict) -> str:
        age, sex = web._demographics(connection, owner_id)
        view = allergy.overview(
            connection, owner_id,
            judge=lambda item: web._reading_verdict(connection, item["concept_id"], item, age, sex)[1],
            reading=lambda item: web.format_reading(item, item["preferred_unit"] or item["unit_raw"]),
        )
        if not view.get("has_results"):
            return "No allergy tests in this record."
        headline = allergy.headline(view)
        out = [" ".join(str(headline.get(key) or "") for key in ("title", "body", "highest")).strip()]
        cards = [card for card in catalog() if card.get("panel_id") == "allergy"]
        cards.sort(key=lambda card: (fx._severity(card), str(card["name"])))
        cards, collapsed = _negatives(cards)
        out += [*map(row, cards), *([collapsed] if collapsed else [])]
        return "\n".join(out)

    def get_genetics(args: dict) -> str:
        view = genetics.overview(connection, owner_id, catalog(), {})
        out = []
        for heading, cards in (("genetic tests:", [item["card"] for item in view["genes"]]),
                               ("infections by DNA/RNA test (PCR):", view["germs"]),
                               ("antibody tests:", view["antibodies"])):
            if cards:
                out += [heading, *map(row, cards)]
        return "\n".join(out) or "No genetic, PCR or antibody tests in this record."

    def get_test_plan(args: dict) -> str:
        cards = [card for card in catalog() if not card.get("is_device")]
        needs = testplan.needs(cards, testplan.lab_concepts(connection, owner_id))
        if not needs:
            return "Nothing due: no lab result is past its retest interval or outside its interval."
        out = ["To measure again (why: due = retest interval, out = outside interval; optional = "
               "not preselected; prices are on /plan-tests):"]
        for need in needs:
            card = need["card"]
            why = []
            if need["due"]:
                due_on = (card.get("staleness") or {}).get("due_on")
                why.append(f"due {due_on}" if due_on else "due")
            if need["flagged"]:
                why.append("out")
            out.append(f"{row(card)} [{', '.join(why)}{'' if need['preselected'] else ', optional'}]")
        return "\n".join(out)

    def schema(**properties: tuple[str, str]) -> dict:
        return {
            "type": "object",
            "properties": {name: {"type": kind, "description": text} for name, (kind, text) in properties.items()},
            "additionalProperties": False,
        }

    specs: list[tuple[str, str, dict, Callable[[dict], str], Callable[[dict], str]]] = [
        ("search_record", "Find results, panels, documents, conclusions, vaccinations by name (English or "
         "Ukrainian).", schema(query=("string", "words")), search_record, lambda a: _text(a, "query", 60)),
        ("get_metric", "One result's full history.", schema(metric_id=("string", "#id")), get_metric,
         lambda a: ""),
        ("list_results", "No area_id: body systems. With area_id: its current results.",
         schema(area_id=("string", "area:id")), list_results, lambda a: ""),
        ("list_documents", "Documents, newest first.",
         schema(query=("string", "words in title or provider"), kind=("string", "laboratory, consultation, ..."),
                offset=("integer", "next page")), list_documents, lambda a: ""),
        ("read_document", "A document's results and conclusions; with page, its text from that page.",
         schema(document_id=("string", "d:id"), page=("integer", "first page of text")), read_document,
         lambda a: ""),
        ("list_visits", "Visits, consultations, imaging and reports with their conclusions.",
         schema(offset=("integer", "next page")), list_visits, lambda a: ""),
        ("get_vaccinations", "Vaccination doses and what the schedule suggests is outstanding.",
         NO_ARGUMENTS, get_vaccinations, lambda a: ""),
        ("get_devices", "Wearable data. No metric_key: every metric. With it: recent days, monthly, yearly.",
         schema(metric_key=("string", "key:id")), get_devices, lambda a: ""),
        ("get_panel", "No panel_id: test panels. With it: that panel's results.",
         schema(panel_id=("string", "panel:id")), get_panel, lambda a: ""),
        ("get_allergy", "Allergy overview and allergen results.", NO_ARGUMENTS, get_allergy, lambda a: ""),
        ("get_genetics", "Genetic, PCR infection and antibody tests.", NO_ARGUMENTS, get_genetics, lambda a: ""),
        ("get_test_plan", "What the test planner suggests measuring again, and why.", NO_ARGUMENTS,
         get_test_plan, lambda a: ""),
    ]

    def wrapped(run: Callable[[dict], str]) -> Callable[[dict], str]:
        return lambda args: sources.render(_english(run, args))

    return {
        name: chat.Tool(name=name, description=description, parameters=parameters, run=wrapped(run), detail=detail)
        for name, description, parameters, run, detail in specs
    }


def profile_summary(connection, owner_id: str) -> str:
    """What the model knows before it calls anything: who, how much, what is flagged."""
    return _english(_profile_summary, connection, owner_id)


def _profile_summary(connection, owner_id: str) -> str:
    from . import app as web
    from ..health import HEALTH_AREAS, age_on
    from ..i18n import translate_phrase

    patient = web._patient_row(connection, owner_id)
    counts = web._counts(connection, owner_id)
    catalog = web._metric_catalog(connection, owner_id)
    labs = [card for card in catalog if not card.get("is_device")]
    age = age_on(patient["date_of_birth"]) if patient else None
    sex = str(patient["sex_at_birth"] or "unknown") if patient else "unknown"
    vaccinations = connection.execute(
        "SELECT COUNT(*) FROM immunizations WHERE owner_user_id = ? AND verification_status <> 'rejected'", (owner_id,)
    ).fetchone()[0]
    findings = len(web._finding_catalog(connection, owner_id))
    # Name and date of birth stay home: age and sex are what a reading needs.
    out = [
        "# Record",
        f"age {age if age is not None else 'unknown'}, sex at birth {sex}"
        + (f", blood type {patient['blood_type']}" if patient and patient["blood_type"] else ""),
        f"{counts.get('observations', 0)} lab results ({len(labs)} measurements) from {counts.get('documents', 0)} "
        f"documents, latest {str(counts.get('latest_result') or '-')[:10]}; {findings} written conclusions; "
        f"{vaccinations} vaccination doses; {len(catalog) - len(labs)} device metrics, latest day "
        f"{counts.get('latest_device') or '-'}",
        "not in this record unless a document states it: medications, symptoms, diagnoses, family history",
    ]
    # The verdict and the interval it was judged against, nothing more: the
    # history, the guidance and the other readings are one get_metric away.
    attention = web._attention_cards(catalog)
    out.append(f"## needs attention ({len(attention)})")
    out += [result_row(card, None) for card in attention[:fx.MAX_ATTENTION]]
    if len(attention) > fx.MAX_ATTENTION:
        out.append(f"+{len(attention) - fx.MAX_ATTENTION} more: list_results")
    out.append("## body systems (results)")
    out.append("; ".join(
        f"{translate_phrase(str(area['name']))} area:{area['id']} {count}"
        for area in HEALTH_AREAS
        if (count := sum(1 for card in labs if area["id"] in card["area_ids"]))
    ))
    return "\n".join(out)


def _document_name(row: dict) -> str:
    """Kind and title, without the generated title's repeat of kind and date."""
    title, kind = str(row.get("title_text") or ""), str(row.get("type_label") or "")
    return kind if not title or title.startswith(kind) else f"{kind}: {title}"


# --- rendering ---------------------------------------------------------------------

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_ITEM = re.compile(r"^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$")
_HEADING = re.compile(r"^#{1,6}\s+(.*)$")


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = _CODE.sub(r"<code>\1</code>", escaped)
    return _BOLD.sub(r"<strong>\1</strong>", escaped)


def render_markdown(text: str) -> Markup:
    """The small Markdown the prompt allows, as HTML: paragraphs, lists,
    headings shown as bold lines, **bold** and `code`.  Everything is escaped
    first, so a model (or a document it quotes) cannot inject markup."""
    out: list[str] = []
    paragraph: list[str] = []
    list_tag = ""

    def close_paragraph() -> None:
        if paragraph:
            out.append("<p>" + "<br>".join(_inline(item) for item in paragraph) + "</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = ""

    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        item, heading = _ITEM.match(raw), _HEADING.match(raw.strip())
        if not raw.strip():
            close_paragraph()
            close_list()
        elif heading:
            close_paragraph()
            close_list()
            out.append(f"<p><strong>{_inline(heading.group(1))}</strong></p>")
        elif item:
            close_paragraph()
            tag = "ol" if item.group(1) else "ul"
            if tag != list_tag:
                close_list()
                out.append(f"<{tag}>")
                list_tag = tag
            out.append(f"<li>{_inline(item.group(2))}</li>")
        else:
            close_list()
            paragraph.append(raw.strip())
    close_paragraph()
    close_list()
    return Markup("".join(out))


#: What the reader is told each tool did, in their language.
TOOL_LABELS = {
    "search_record": "chat.tool_search", "get_metric": "chat.tool_metric", "list_results": "chat.tool_results",
    "list_documents": "chat.tool_documents", "read_document": "chat.tool_document", "list_visits": "chat.tool_visits",
    "get_vaccinations": "chat.tool_vaccinations", "get_devices": "chat.tool_devices", "get_panel": "chat.tool_panel",
    "get_allergy": "chat.tool_allergy", "get_genetics": "chat.tool_genetics", "get_test_plan": "chat.tool_plan",
}


def tool_label(event: dict) -> str:
    name, detail = str(event.get("name") or ""), str(event.get("detail") or "")
    if name == "search_record" and detail:
        return t("chat.tool_search", query=detail)
    return t(TOOL_LABELS[name] if name in TOOL_LABELS and name != "search_record" else "chat.tool_other")


def error_text(reason: str, *, admin: bool) -> str:
    key = f"chat.error_{reason}" if f"chat.error_{reason}" in _ERROR_KEYS else "chat.error_provider_error"
    message = t(key)
    if reason == "disabled":
        message += " " + t("chat.error_disabled_admin" if admin else "chat.error_disabled_ask")
    return message


_ERROR_KEYS = {"chat.error_disabled", "chat.error_budget", "chat.error_provider_error", "chat.error_truncated",
               "chat.error_in_progress"}


# --- one turn ------------------------------------------------------------------------


def compact_history(settings, stored: dict, message: str, locale: str,
                    emit: Callable[[dict], None]) -> tuple[str, list[dict]]:
    """The summary and the turns to send with ``message``, compacting first
    when the conversation has grown past ``chat.COMPACT_AT_CHARS``.

    A failed summary leaves the stored one as it was; ``chat.history`` then
    drops the oldest turns, so the request stays bounded either way.
    """
    messages = list(stored.get("messages") or [])
    summary, through = str(stored.get("summary") or ""), int(stored.get("summary_through") or 0)
    older = chat.pending_compaction(messages, through)
    if older:
        emit({"type": "status", "label": t("chat.compacting")})
        try:
            summary = chat.summarise(settings, summary, older, locale)
        except AIUnavailable:
            pass
        else:
            through = int(older[-1]["id"])
            chat.save_summary(settings, str(stored["id"]), summary, through)
            emit({"type": "compacted", "after_id": through, "label": t("chat.compacted")})
    live = [item for item in messages if int(item["id"]) > through]
    return summary, chat.history([*live, {"role": "user", "content": message}])


def tokens_text(count: int) -> str:
    """``850`` / ``12.6k`` in the page's number format."""
    if count < 1000:
        return format_number_localized(count, 0)
    return t("chat.tokens_k", value=format_number_localized(round(count / 1000, 1), 1))


def context_view(conversation: dict | None) -> dict:
    """The page's context indicator: what the last answer read, and how full
    the replayed history is before it is summarised."""
    answers = [item for item in (conversation or {}).get("messages", []) if item["role"] == "assistant"]
    context = int(answers[-1].get("context_tokens") or 0) if answers else 0
    percent = chat.memory_percent(conversation)
    return {
        "tokens": context, "percent": percent,
        "text": t("chat.context_short", tokens=tokens_text(context)) if context else "",
        "label": t("chat.context_label", tokens=tokens_text(context), percent=percent),
    }


def _run_turn(settings, *, viewer: dict, owner: dict, conversation_id: str, message: str, locale: str,
              emit: Callable[[dict], None], choice: str = "") -> None:
    """Store the question, answer it, store the answer.  Runs in its own
    thread with its own locale and caches: a streamed body outlives the
    request middleware that set them."""
    activate_locale(locale)
    from .app import _request_cache

    _request_cache.set({})
    RULE_CACHE.set({})
    stored = chat.conversation(settings, conversation_id, viewer["id"], owner["id"]) or {}
    summary, turns = compact_history(settings, stored, message, locale, emit)
    chat.add_message(settings, conversation_id, "user", message)
    connection = connect(settings)
    try:
        system = chat.system_prompt(
            locale=locale, today=date.today().isoformat(),
            profile=profile_summary(connection, owner["id"]), viewer_is_owner=viewer["id"] == owner["id"],
            summary=summary,
        )
        tools = build_tools(connection, owner["id"])
        try:
            answer = chat.respond(
                settings, system=system, turns=turns, tools=tools,
                on_text=lambda text: emit({"type": "text", "text": text}),
                on_tool=lambda event: emit({"type": "tool", "label": tool_label(event)}),
                choice=choice,
            )
        except AIUnavailable as exc:
            text = getattr(exc, "text", "")
            chat.add_message(settings, conversation_id, "assistant", text, tools=getattr(exc, "tools", []),
                             model=getattr(exc, "model", ""), error=exc.reason,
                             tokens=getattr(exc, "tokens", (0, 0, 0)))
            emit({"type": "error", "reason": exc.reason,
                  "message": error_text(exc.reason, admin=viewer.get("role") == "admin"),
                  "html": str(render_markdown(text)) if text else ""})
            return
        chat.add_message(settings, conversation_id, "assistant", answer.text, tools=answer.tools,
                         model=answer.model, tokens=answer.tokens)
        stored = chat.conversation(settings, conversation_id, viewer["id"], owner["id"])
        emit({"type": "done", "html": str(render_markdown(answer.text)), "model": answer.model,
              "context": context_view(stored),
              "tools": [tool_label(event) for event in answer.tools],
              "tools_summary": t_plural("chat.looked_at", len(answer.tools))})
    finally:
        connection.close()


#: People with an answer being written right now.  One turn at a time each:
#: a second POST would interleave two answers in one conversation and spend
#: the installation's shared daily budget twice as fast.
# ponytail: process-local, like the document-review lock; move to a table if
# the server ever runs more than one worker.
_TURNS: set[tuple[str, str]] = set()
_TURNS_LOCK = threading.Lock()


def _share_read_only(user, owner) -> bool:
    """A viewer of someone else's record whom the owner gave read-only access."""
    return owner["id"] != user["id"] and dict(owner).get("share_access") != "full"


def register_routes(app, settings, *, templates, template_context, require_user, record_user, require_csrf,
                    viewing_row) -> None:
    def people(request: Request) -> tuple[dict, dict]:
        user = require_user(request)
        if user.get("token_kind") in ("guest", "api"):
            # token_scope already refuses both; this keeps the rule true if
            # the allowlist ever grows a prefix that happens to cover /chat.
            raise HTTPException(403, t("chat.error_guest"))
        return dict(user), dict(record_user(request, user))

    def page(request: Request, viewer: dict, owner: dict, current: dict | None):
        choices = chat.choices(settings)
        chosen = str((current or {}).get("model_key") or "")
        if chosen not in {item["key"] for item in choices}:
            chosen = choices[0]["key"] if choices else ""
        route = chat.chat_route(settings, chosen)
        items = chat.conversations(settings, viewer["id"], owner["id"])
        messages = []
        for item in (current or {}).get("messages", []):
            messages.append({
                **item,
                "html": render_markdown(item["content"]) if item["role"] == "assistant" else None,
                "tool_labels": [tool_label(event) for event in item["tools"]],
                "error_text": error_text(item["error"], admin=viewer.get("role") == "admin") if item["error"] else "",
            })
        return templates.TemplateResponse(request, "chat.html", template_context(
            request, active="chat", conversations=items, current=current, messages=messages,
            route={key: route[key] for key in ("provider", "model", "host")}, ai_ready=route["active"], is_owner=viewer["id"] == owner["id"],
            share_read_only=_share_read_only(viewer, owner),
            record_name=owner.get("display_name") or "",
            disabled_text=error_text("disabled", admin=viewer.get("role") == "admin"),
            busy_text=error_text("in_progress", admin=False) if request.query_params.get("busy") else "",
            message_limit=chat.MAX_MESSAGE_CHARS, choices=choices, chosen=chosen,
            context=context_view(current),
        ))

    @app.get("/chat", response_class=HTMLResponse)
    def chat_page(request: Request):
        viewer, owner = people(request)
        return page(request, viewer, owner, None)

    @app.get("/chat/{conversation_id}", response_class=HTMLResponse)
    def chat_conversation(request: Request, conversation_id: str):
        viewer, owner = people(request)
        current = chat.conversation(settings, conversation_id, viewer["id"], owner["id"])
        if current is None:
            raise HTTPException(404)
        return page(request, viewer, owner, current)

    @app.post("/chat/send")
    async def chat_send(request: Request):
        viewer, owner = await run_in_threadpool(people, request)
        if _share_read_only(viewer, owner):
            # Before any conversation, message or model call: a read-only share is not asked about.
            raise HTTPException(403, t("chat.error_share_read_only"))
        form = await request.form()
        require_csrf(viewer, str(form.get("csrf_token") or ""))
        message = str(form.get("message") or "").strip()[: chat.MAX_MESSAGE_CHARS]
        if not message:
            return RedirectResponse(f"/chat/{form.get('conversation_id')}" if form.get("conversation_id") else "/chat", 303)
        key = (str(settings.database_path), str(viewer["id"]))
        with _TURNS_LOCK:
            busy = key in _TURNS
            if not busy:
                _TURNS.add(key)
        if busy:
            if "text/event-stream" in request.headers.get("accept", ""):
                async def refused():
                    yield _sse({"type": "error", "reason": "in_progress",
                                "message": error_text("in_progress", admin=False), "html": ""})

                return StreamingResponse(refused(), media_type="text/event-stream",
                                         headers={"X-Accel-Buffering": "no"})
            # The page says why the message was not sent (see busy_text in page()).
            return RedirectResponse((f"/chat/{form.get('conversation_id')}" if form.get("conversation_id") else "/chat") + "?busy=1", 303)
        try:
            conversation_id = str(form.get("conversation_id") or "")
            if not conversation_id:
                conversation_id = await run_in_threadpool(
                    chat.create_conversation, settings, viewer["id"], owner["id"], message)
            known = await run_in_threadpool(chat.conversation, settings, conversation_id, viewer["id"], owner["id"])
            if known is None:
                raise HTTPException(404)
            title = str(known["title"])
            # Only a model the admin offers; anything else answers on the default.
            choice = str(form.get("model") or "")
            if choice not in {item["key"] for item in await run_in_threadpool(chat.choices, settings)}:
                choice = ""
            if choice != str(known.get("model_key") or ""):
                await run_in_threadpool(chat.set_model, settings, conversation_id, choice)
            locale = get_locale()
            events: queue.Queue = queue.Queue()

            def work() -> None:
                try:
                    _run_turn(settings, viewer=viewer, owner=owner, conversation_id=conversation_id,
                              message=message, locale=locale, emit=events.put, choice=choice)
                except Exception:
                    events.put({"type": "error", "reason": "provider_error",
                                "message": error_text("provider_error", admin=False), "html": ""})
                    raise
                finally:
                    # Released before the stream ends, so a retry that follows the
                    # last event is not refused as still in progress.
                    with _TURNS_LOCK:
                        _TURNS.discard(key)
                    events.put(None)

            thread = threading.Thread(target=contextvars.Context().run, args=(work,), daemon=True)
            thread.start()
        except BaseException:
            with _TURNS_LOCK:
                _TURNS.discard(key)
            raise
        if "text/event-stream" not in request.headers.get("accept", ""):
            # Without script the form posts normally: wait for the answer,
            # then show the conversation with it.
            await run_in_threadpool(thread.join)
            return RedirectResponse(f"/chat/{conversation_id}", 303)

        async def stream():
            yield _sse({"type": "conversation", "id": conversation_id, "url": f"/chat/{conversation_id}",
                        "title": title})
            while True:
                event = await asyncio.to_thread(events.get)
                if event is None:
                    return
                yield _sse(event)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no"})

    @app.post("/chat/{conversation_id}/delete")
    async def chat_delete(request: Request, conversation_id: str):
        viewer, _owner = await run_in_threadpool(people, request)
        form = await request.form()
        require_csrf(viewer, str(form.get("csrf_token") or ""))
        await run_in_threadpool(chat.delete_conversation, settings, conversation_id, viewer["id"])
        # Deleting another conversation from the list keeps the open one open.
        # Only an id shape is accepted, so `back` can never point off /chat.
        back = str(form.get("back") or "")
        if back != conversation_id and re.fullmatch(r"[0-9a-f]{32}", back):
            return RedirectResponse(f"/chat/{back}?deleted=1", 303)
        return RedirectResponse("/chat?deleted=1", 303)

    @app.post("/chat/delete-all")
    async def chat_delete_all(request: Request):
        viewer, owner = await run_in_threadpool(people, request)
        form = await request.form()
        require_csrf(viewer, str(form.get("csrf_token") or ""))
        await run_in_threadpool(chat.delete_all, settings, viewer["id"], owner["id"])
        return RedirectResponse("/chat?deleted=all", 303)


def _sse(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
