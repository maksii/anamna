"""Diagnoses on the record: the page, the form, the detail page, possible and found diagnoses.

The record is read through the owner's account, so a share viewer or a guest
sees the owner's diagnoses read-only.  Every write needs the owner's own
signed-in account, a valid CSRF token and a database connection of its own.
A reading of the documents is a job the page polls, as in the Medicines page.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from functools import lru_cache, partial
from typing import Any, NamedTuple

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .. import (
    ai, diagnoses, diagnosis_candidates, diagnosis_matrix, diagnosis_scan, diagnosis_treatment, factor_jobs, factors, icd10,
)
from ..config import resource_path
from ..db import connect
from ..health import AREA_BY_ID, _diagnosis_areas
from ..i18n import MESSAGES, activate_locale, format_date_localized, get_locale, reset_locale, t, t_plural, translate_phrase
from . import diagnoses_job
from .changes import verdict_state
from .factors_routes import _documents, _redirect, _writable

_MAX_KEYS = 200


class _Wiring(NamedTuple):
    """What the Diagnoses routes take from ``create_app``."""

    settings: Any
    templates: Any
    template_context: Callable[..., Any]
    require_user: Callable[..., Any]
    record_user: Callable[..., Any]
    require_csrf: Callable[..., Any]
    audit: Callable[..., Any]
    document_row: Callable[..., Any]
    catalog: Callable[..., Any]
    matrix_cards: Callable[..., Any]


class _Page(NamedTuple):
    """What one request needs to build its views: the owner's connection, locale and metric cards."""

    connection: Any
    owner_id: str
    locale: str
    document_row: Callable[..., Any]
    matrix: dict[str, str]  # English metric name -> card id, from the matching cards
    cards: dict[str, dict]  # card id -> card in the request's locale


def _page(w: _Wiring, connection, owner_id: str) -> _Page:
    matrix = {str(card["name"]): str(card["id"]) for card in w.matrix_cards(connection, owner_id)}
    cards = {str(card["id"]): card for card in w.catalog(connection, owner_id)}
    return _Page(connection, owner_id, get_locale(), w.document_row, matrix, cards)


def _date(value: object) -> str:
    """A stored ISO date as the page prints it; '' when blank."""
    text = str(value or "")[:10]
    return format_date_localized(text) if text else ""


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _message(prefix: str, value: str) -> str | None:
    """The translated notice for a known query value; any other value gives none and is never echoed."""
    key = f"{prefix}.{value}" if value else ""
    return t(key) if key in MESSAGES else None


def _title(block: dict, locale: str) -> str:
    """A catalogue title in the locale; English falls back to the Ukrainian title."""
    if locale == "uk":
        return str(block["uk"])
    return str(block.get("en") or block["uk"])


def _chapter_text(code: str, locale: str) -> str:
    entry = icd10.entry(code) if code else None
    if entry is None or entry["chapter"] is None:
        return ""
    return _title(entry["chapter"], locale)


def _chapter_range(code: str) -> str:
    """The code range of the ICD-10 chapter the code sits in, '' for none."""
    entry = icd10.entry(code) if code else None
    if entry is None or entry["chapter"] is None:
        return ""
    return str(entry["chapter"]["range"])


def _by_chapter(items: list[dict]) -> list[dict]:
    """The diagnoses grouped by ICD-10 chapter, in the classification's order; uncoded ones last."""
    groups: dict[str, dict] = {}
    for item in items:
        key = item["chapter_range"]
        group = groups.setdefault(key, {
            "key": key or "none",
            "title": item["chapter_text"] if key else t("dx.group.uncoded"),
            "items": [],
        })
        group["items"].append(item)
    return [groups[key] for key in sorted(groups, key=lambda key: (key == "", key))]


def _search_text(*parts: object) -> str:
    """What the page's filter matches: the visible words of a diagnosis, folded to lower case."""
    return " ".join(str(part) for part in parts if part).casefold()


def _area(code: str) -> dict | None:
    """The health area the code's ICD chapter belongs to, as the Areas pages name it."""
    areas = _diagnosis_areas(code) if code else ()
    if not areas or areas[0] not in AREA_BY_ID:
        return None
    return {
        "id": areas[0],
        "name": translate_phrase(str(AREA_BY_ID[areas[0]]["name"])),
        "url": f"/areas/{areas[0]}",
    }


def _document_ref(page: _Page, document_id: str | None) -> dict | None:
    """The owner's document as {id, label, url}; None when there is none or it no longer exists."""
    if not document_id:
        return None
    found = _documents(page.connection, page.owner_id, page.document_row, document_id)
    if not found:
        return None
    return {**found[0], "url": f"/documents/{found[0]['id']}"}


def _owned_document(connection, owner_id: str, w: _Wiring, document_id: str | None) -> str | None:
    """The document id when it is one of the owner's documents, else None."""
    if not document_id:
        return None
    return document_id if _documents(connection, owner_id, w.document_row, document_id) else None


def _chip(card: dict) -> dict:
    verdict = card.get("verdict") or {}
    return {
        "name": str(card["name"]),
        "url": card.get("url", ""),
        "value_text": _text(card.get("value_text")),
        "unit": _text(card.get("unit")),
        "date_text": _text(card.get("date_text")),
        "state": verdict_state(verdict),
        "verdict_label": str(verdict.get("label") or ""),
    }


def _medicine_view(page: _Page, item: dict) -> dict:
    """One medicine of a diagnosis as the pages print it, with the reason it is shown."""
    factor = item["factor"]
    status = str(factor["effective_status"])
    basis = item["basis"]
    if basis == "linked":
        basis_text = t("dx.treat.basis_linked")
    else:
        basis_text = t("dx.treat.basis_atc", group=t("dx.atc." + item["group"]), code=item["atc_prefix"])
    return {
        "id": factor["id"],
        "name": str(factor["name"]),
        "substance": _text(factor["substance"]),
        "regimen": factors.regimen_text(factor, page.locale),
        "status": status,
        "status_label": t("med.status." + status),
        "since_text": t("dx.since", date=_date(factor["started_on"])) if factor["started_on"] else "",
        "until_text": t("dx.until", date=_date(factor["ended_on"])) if factor["ended_on"] else "",
        "url": f"/medicines/{factor['id']}",
        "basis": basis,
        "basis_text": basis_text,
    }


def _watch(page: _Page, code: str) -> list[dict]:
    """The metrics the person has a card for that bear on this diagnosis."""
    chips = []
    for metric in diagnosis_matrix.watch_metrics(code):
        card = page.cards.get(page.matrix.get(metric, ""))
        if card is not None:
            chips.append(_chip(card))
    return chips


def _diagnosis_view(page: _Page, row) -> dict:
    code = str(row["code"] or "")
    # ponytail: one factors.listing per diagnosis card; hoist to one listing per request if a record grows to hundreds of diagnoses.
    medicines = diagnosis_treatment.medicines(page.connection, page.owner_id, row, today=date.today())
    name = diagnoses.display_name(row, page.locale)
    written = diagnoses.written_detail(row)
    chapter_text = _chapter_text(code, page.locale)
    return {
        "id": row["id"],
        "url": f"/diagnoses/{row['id']}",
        "code": code,
        "name": name,
        "written": written,
        "day": row["diagnosed_on"] or "",
        "search": _search_text(name, written, code, row["clinician"], chapter_text),
        "status": row["status"],
        "status_label": t(f"dx.status.{row['status']}"),
        "certainty": row["certainty"],
        "certainty_label": t(f"dx.certainty.{row['certainty']}"),
        "since_text": t("dx.since", date=_date(row["diagnosed_on"])) if row["diagnosed_on"] else "",
        "until_text": t("dx.until", date=_date(row["resolved_on"])) if row["resolved_on"] else "",
        "approximate": bool(row["dates_approximate"]),
        "clinician": row["clinician"],
        "notes": row["notes"],
        "origin": row["origin"],
        "origin_label": t(f"dx.origin.{row['origin']}"),
        "document": _document_ref(page, row["document_id"]),
        "chapter_text": chapter_text,
        "chapter_range": _chapter_range(code),
        "area": _area(code),
        "watch": _watch(page, code),
        "medicines": [_medicine_view(page, item) for item in medicines],
    }


def _evidence_view(page: _Page, item: dict) -> dict:
    card = page.cards.get(str(item.get("metric_id") or ""))
    metric = str(card["name"]) if card else translate_phrase(str(item.get("metric") or ""))
    value_text, unit = _text(item.get("value")), _text(item.get("unit"))
    item_date = str(item.get("date") or "")[:10]
    # The localized card carries the value in the reader's locale, but only for the same reading.
    if card and item_date and str(card.get("latest_date") or "")[:10] == item_date:
        value_text, unit = _text(card.get("value_text")), _text(card.get("unit"))
    return {
        "metric": metric,
        "url": _text(item.get("url")),
        "value_text": value_text,
        "unit": unit,
        "date_text": _date(item.get("date")),
        "band": diagnosis_matrix.band_text(
            page.connection, str(item.get("metric") or ""), str(item.get("band") or ""), page.locale,
        ),
        "source_name": _text(item.get("source_name")),
        "source_url": _text(item.get("source_url")),
    }


def _possible_view(page: _Page, row: dict) -> dict:
    return {
        "id": row["id"],
        "code": row["code"],
        "title": icd10.name(row["code"], page.locale),
        "rule_id": row["rule_id"],
        "note": t(f"dx.rule.{row['rule_id']}.note"),
        "doctor_text": t(f"dx.doctor.{row['doctor']}"),
        "evidence": [_evidence_view(page, item) for item in row["evidence"]],
        "first_seen_text": _date(row["first_seen_at"]),
        "confirm_url": f"/diagnoses/new?suspicion={row['id']}",
    }


def _found_when(group: dict) -> str:
    """The last date seen; with several mentions, the first and the last dates."""
    last = _date(group["last_date"])
    if group["mentions"] <= 1:
        return last
    parts = []
    first = _date(group["first_date"])
    if first:
        parts.append(t("dx.found.first_seen", date=first))
    if last:
        parts.append(t("dx.found.last_seen", date=last))
    return ", ".join(parts)


def _found_view(page: _Page, group: dict) -> dict:
    documents = [ref for document in group["documents"] if (ref := _document_ref(page, document["id"]))]
    code, title = group["code"], group["title"]
    titled = bool(code and title)
    written_raw = group["name"] if group["name"] != title else ""
    method = "ai" if "ai" in group["methods"] else "code" if "code" in group["methods"] else "text"
    return {
        "key": group["key"],
        "code": code,
        "name": title if titled else group["name"],
        "written": diagnoses.written_detail({"code": code, "name": written_raw}) if titled else "",
        "certainty": group["certainty"],
        "certainty_label": t(f"dx.certainty.{group['certainty']}"),
        "mentions_text": t_plural("dx.found.mentions", group["mentions"]),
        "when_text": _found_when(group),
        "quote": group["quote"],
        "code_printed": bool(group["code_printed"]),
        "method": method,
        "ai": method == "ai",
        "text": method == "text",
        "documents": documents,
        "existing_url": f"/diagnoses/{group['existing_id']}" if group.get("existing_id") else "",
    }


@lru_cache(maxsize=1)
def _raw_sources() -> list[dict]:
    """The catalogue's sources exactly as the file carries them; read once."""
    data = json.loads(resource_path("icd10.json").read_text(encoding="utf-8"))
    return list(data["sources"])


def _sources(locale: str) -> list[dict]:
    """The catalogue's sources as the page lists them, names and publishers in the reader's locale."""
    return [
        {
            "name": source.get(f"name_{locale}") or source.get("name", ""),
            "publisher": source.get(f"publisher_{locale}") or source.get("publisher", ""),
            "url": source.get("url", ""),
            "region": source.get("region", ""),
        }
        for source in _raw_sources()
    ]


def _record_lists(page: _Page) -> dict[str, list[dict]]:
    lists: dict[str, list[dict]] = {"current": [], "provisional": [], "past": []}
    for row in diagnoses.listing(page.connection, page.owner_id):
        view = _diagnosis_view(page, row)
        if view["status"] != "active":
            lists["past"].append(view)
        elif view["certainty"] == "provisional":
            lists["provisional"].append(view)
        else:
            lists["current"].append(view)
    return lists


def _found_lists(page: _Page) -> tuple[list[dict], list[dict], list[dict]]:
    fresh, existing = [], []
    for group in diagnosis_candidates.groups(page.connection, page.owner_id, locale=page.locale):
        (existing if group["existing_id"] else fresh).append(_found_view(page, group))
    dismissed = [
        _found_view(page, group)
        for group in diagnosis_candidates.dismissed(page.connection, page.owner_id, locale=page.locale)
    ]
    return fresh, existing, dismissed


def _scan_view(connection, owner_id: str, user_id: str, settings) -> dict:
    counts = diagnosis_scan.counts(connection, owner_id)
    return {
        "ai_ready": ai.ai_active(settings, diagnosis_scan.FEATURE),
        "documents": counts["documents"],
        "waiting": counts["waiting"],
        "job": factor_jobs.running(user_id, "dx_scan") or "",
    }


def _diagnoses_page(w: _Wiring, request: Request, saved: str, error: str):
    user = w.require_user(request)
    owner = w.record_user(request, user)
    writable = _writable(user, owner)
    with connect(w.settings) as connection:
        if writable:
            diagnoses_job.refresh_if_changed(w.settings, connection, owner["id"], w.matrix_cards)
        page = _page(w, connection, owner["id"])
        lists = _record_lists(page)
        suspicions = diagnosis_matrix.listing(connection, owner["id"], ("open", "muted"))
        possible = [_possible_view(page, row) for row in suspicions if row["state"] == "open"]
        muted = [_possible_view(page, row) for row in suspicions if row["state"] == "muted"]
        fresh, existing, dismissed = _found_lists(page)
        last = diagnoses_job.last_refreshed(connection, owner["id"])
        scan = _scan_view(connection, owner["id"], user["id"], w.settings)
    summary = {
        "active": len(lists["current"]) + len(lists["provisional"]),
        "possible": len(possible) + len(lists["provisional"]),
        "found": len(fresh),
    }
    return w.templates.TemplateResponse(request, "diagnoses.html", w.template_context(
        request, active="diagnoses", writable=writable, summary=summary,
        current=lists["current"], current_groups=_by_chapter(lists["current"]),
        provisional=lists["provisional"], past=lists["past"],
        possible=possible, muted=muted, found=fresh, found_existing=existing, found_dismissed=dismissed,
        scan=scan, saved=_message("dx.notice", saved), error=_message("dx.error", error),
        checked_text=t("dx.checked", date=_date(last)) if last else "", sources=_sources(get_locale()),
    ))


def _blank_values() -> dict:
    return {
        "code": "", "name": "", "status": "active", "certainty": "confirmed", "diagnosed_on": "",
        "resolved_on": "", "dates_approximate": 0, "clinician": "", "document_id": None, "notes": "",
    }


def _open_suspicion(connection, owner_id: str, suspicion_id: str) -> dict | None:
    """The owner's open possible diagnosis with this id, or None."""
    if not suspicion_id:
        return None
    return next((row for row in diagnosis_matrix.listing(connection, owner_id) if row["id"] == suspicion_id), None)


def _prefill(connection, owner_id: str, code_text: str, suspicion_id: str) -> tuple[dict, str]:
    """The new form's values and the suspicion it confirms ('' when none)."""
    values = _blank_values()
    suspicion = _open_suspicion(connection, owner_id, suspicion_id)
    if suspicion is not None:
        values["code"] = suspicion["code"]
        values["certainty"] = "confirmed"
        return values, suspicion["id"]
    code = icd10.normalize(code_text) if code_text else ""
    if code and icd10.entry(code) is not None:
        values["code"] = code
    return values, ""


def _patient_id(connection, owner_id: str) -> str | None:
    row = connection.execute(
        "SELECT id FROM patients WHERE owner_user_id = ? ORDER BY created_at LIMIT 1", (owner_id,),
    ).fetchone()
    return row["id"] if row is not None else None


def _form_page(w: _Wiring, request: Request, connection, owner_id: str, *, values: dict, is_new: bool,
               diagnosis_id: str, suspicion_id: str, errors: list[str], status_code: int = 200):
    locale = get_locale()
    code = str(values.get("code") or "")
    return w.templates.TemplateResponse(request, "diagnosis_form.html", w.template_context(
        request, active="diagnoses", is_new=is_new,
        action_url="/diagnoses/new" if is_new else f"/diagnoses/{diagnosis_id}/edit",
        cancel_url="/diagnoses" if is_new else f"/diagnoses/{diagnosis_id}",
        values=values, code_title=icd10.name(code, locale) if code else "",
        errors=[t(f"dx.error.{key}") for key in errors],
        documents=_documents(connection, owner_id, w.document_row),
        statuses=[(value, t(f"dx.status.{value}")) for value in diagnoses.STATUSES],
        certainties=[(value, t(f"dx.certainty.{value}")) for value in diagnoses.CERTAINTIES],
        suspicion_id=suspicion_id,
    ), status_code=status_code)


def _new_page(w: _Wiring, request: Request, code: str, suspicion: str):
    user = w.require_user(request)
    owner = w.record_user(request, user)
    if not _writable(user, owner):
        return _redirect("/diagnoses")
    with connect(w.settings) as connection:
        values, suspicion_id = _prefill(connection, owner["id"], code, suspicion)
        return _form_page(w, request, connection, owner["id"], values=values, is_new=True,
                          diagnosis_id="", suspicion_id=suspicion_id, errors=[])


def _edit_page(w: _Wiring, request: Request, diagnosis_id: str):
    user = w.require_user(request)
    owner = w.record_user(request, user)
    if not _writable(user, owner):
        return _redirect("/diagnoses")
    with connect(w.settings) as connection:
        row = diagnoses.get(connection, owner["id"], diagnosis_id)
        if row is None:
            raise HTTPException(404)
        return _form_page(w, request, connection, owner["id"], values=row, is_new=False,
                          diagnosis_id=diagnosis_id, suspicion_id="", errors=[])


def _refresh(w: _Wiring, connection, owner_id: str) -> None:
    """Commit the write, then bring the possible and found diagnoses up to date."""
    connection.commit()
    diagnoses_job.refresh_if_changed(w.settings, connection, owner_id, w.matrix_cards, force=True)


def _create(w: _Wiring, request: Request, user, form):
    owner_id = user["id"]
    values, errors = diagnoses.clean(form, today=date.today())
    with connect(w.settings) as connection:
        values["document_id"] = _owned_document(connection, owner_id, w, values["document_id"])
        suspicion = _open_suspicion(connection, owner_id, str(form.get("suspicion_id") or ""))
        suspicion_id = suspicion["id"] if suspicion else ""
        if errors:
            return _form_page(w, request, connection, owner_id, values=values, is_new=True,
                              diagnosis_id="", suspicion_id=suspicion_id, errors=errors, status_code=400)
        patient_id = _patient_id(connection, owner_id)
        if patient_id is None:
            return _redirect("/diagnoses?error=not_found")
        origin = "suspicion" if suspicion else "person"
        diagnosis_id = diagnoses.create(connection, owner_id, patient_id, values, origin=origin)
        if suspicion:
            diagnosis_matrix.confirm(connection, owner_id, suspicion_id, diagnosis_id)
        w.audit(user["id"], user["id"], "diagnosis.create", "diagnosis", diagnosis_id, {"source": origin},
                connection=connection)
        _refresh(w, connection, owner_id)
    return _redirect("/diagnoses?saved=added")


def _update(w: _Wiring, request: Request, diagnosis_id: str, user, form):
    owner_id = user["id"]
    values, errors = diagnoses.clean(form, today=date.today())
    with connect(w.settings) as connection:
        if diagnoses.get(connection, owner_id, diagnosis_id) is None:
            raise HTTPException(404)
        values["document_id"] = _owned_document(connection, owner_id, w, values["document_id"])
        if errors:
            return _form_page(w, request, connection, owner_id, values=values, is_new=False,
                              diagnosis_id=diagnosis_id, suspicion_id="", errors=errors, status_code=400)
        diagnoses.update(connection, owner_id, diagnosis_id, values)
        w.audit(user["id"], user["id"], "diagnosis.update", "diagnosis", diagnosis_id, {}, connection=connection)
        _refresh(w, connection, owner_id)
    return _redirect(f"/diagnoses/{diagnosis_id}?saved=saved")


def _set_status(w: _Wiring, diagnosis_id: str, user, form):
    owner_id = user["id"]
    status = str(form.get("status") or "")
    if status not in diagnoses.STATUSES:
        raise HTTPException(400)
    with connect(w.settings) as connection:
        if not diagnoses.set_status(connection, owner_id, diagnosis_id, status, today=date.today()):
            raise HTTPException(404)
        w.audit(user["id"], user["id"], "diagnosis.status", "diagnosis", diagnosis_id, {"status": status},
                connection=connection)
        _refresh(w, connection, owner_id)
    return _redirect("/diagnoses?saved=status_changed")


def _delete(w: _Wiring, diagnosis_id: str, user, form):
    owner_id = user["id"]
    with connect(w.settings) as connection:
        if not diagnoses.delete(connection, owner_id, diagnosis_id):
            raise HTTPException(404)
        w.audit(user["id"], user["id"], "diagnosis.delete", "diagnosis", diagnosis_id, {}, connection=connection)
        _refresh(w, connection, owner_id)
    return _redirect("/diagnoses?saved=deleted")


def _medicine_action(w: _Wiring, diagnosis_id: str, user, form):
    """Link a medicine to a diagnosis, or say it is not for this diagnosis."""
    owner_id = user["id"]
    factor_id = str(form.get("factor_id") or "")
    action = str(form.get("action") or "")
    refused = _redirect(f"/diagnoses/{diagnosis_id}?error=medicine#dx-treatment")
    with connect(w.settings) as connection:
        if diagnoses.get(connection, owner_id, diagnosis_id) is None:
            raise HTTPException(404)
        if action not in ("add", "remove"):
            return refused
        linked = action == "add"
        write = diagnosis_treatment.link if linked else diagnosis_treatment.unlink
        if not write(connection, owner_id, diagnosis_id, factor_id):
            return refused
        audit_action = "diagnosis.medicine_link" if linked else "diagnosis.medicine_unlink"
        w.audit(user["id"], user["id"], audit_action, "diagnosis", diagnosis_id, {"factor_id": factor_id},
                connection=connection)
        connection.commit()
    saved = "medicine_linked" if linked else "medicine_unlinked"
    return _redirect(f"/diagnoses/{diagnosis_id}?saved={saved}#dx-treatment")


def _possible_action(w: _Wiring, suspicion_id: str, user, form):
    owner_id = user["id"]
    action = str(form.get("action") or "")
    if action not in ("mute", "restore"):
        raise HTTPException(400)
    with connect(w.settings) as connection:
        if action == "mute":
            if not diagnosis_matrix.mute(connection, owner_id, suspicion_id):
                raise HTTPException(404)
            connection.commit()
            return _redirect("/diagnoses?saved=muted")
        if not diagnosis_matrix.restore(connection, owner_id, suspicion_id):
            raise HTTPException(404)
        _refresh(w, connection, owner_id)
    return _redirect("/diagnoses?saved=restored")


def _check_possible(w: _Wiring, user, form):
    with connect(w.settings) as connection:
        _refresh(w, connection, user["id"])
    return _redirect("/diagnoses?saved=checked")


def _accept_found(w: _Wiring, user, connection, keys: list[str]) -> RedirectResponse:
    owner_id = user["id"]
    patient_id = _patient_id(connection, owner_id)
    if patient_id is None:
        return _redirect("/diagnoses?error=not_found")
    touched = diagnosis_candidates.accept(connection, owner_id, patient_id, keys)
    if not touched:
        return _redirect("/diagnoses?error=found_none")
    for diagnosis_id in touched:
        w.audit(user["id"], user["id"], "diagnosis.create", "diagnosis", diagnosis_id, {"source": "documents"},
                connection=connection)
    _refresh(w, connection, owner_id)
    return _redirect("/diagnoses?saved=found_added")


def _found_action(w: _Wiring, user, form):
    keys = [str(key) for key in form.getlist("key")][:_MAX_KEYS]
    if not keys:
        return _redirect("/diagnoses?error=found_none")
    action = str(form.get("action") or "")
    if action not in ("accept", "dismiss", "restore"):
        raise HTTPException(400)
    with connect(w.settings) as connection:
        if action == "accept":
            return _accept_found(w, user, connection, keys)
        if action == "dismiss":
            diagnosis_candidates.dismiss(connection, user["id"], keys)
            connection.commit()
            return _redirect("/diagnoses?saved=found_dismissed")
        diagnosis_candidates.restore(connection, user["id"], keys)
        connection.commit()
    return _redirect("/diagnoses?saved=found_restored")


def _mention_view(page: _Page, mention: dict) -> dict:
    return {
        "date_text": _date(mention["date"]),
        "quote": mention["quote"],
        "certainty_label": t(f"dx.certainty.{mention['certainty']}"),
        "method_label": t(f"dx.method.{mention['method']}"),
        "document": _document_ref(page, mention["document_id"]),
    }


def _confirmed_suspicion(page: _Page, diagnosis_id: str) -> dict | None:
    """The possible diagnosis this diagnosis was confirmed from, as a PossibleView, or None."""
    row = page.connection.execute(
        "SELECT id FROM diagnosis_suspicions WHERE owner_user_id = ? AND diagnosis_id = ? AND state = 'confirmed'",
        (page.owner_id, diagnosis_id),
    ).fetchone()
    if row is None:
        return None
    found = next(
        (item for item in diagnosis_matrix.listing(page.connection, page.owner_id, ("confirmed",))
         if item["id"] == row["id"]),
        None,
    )
    return _possible_view(page, found) if found is not None else None


def _detail_page(w: _Wiring, request: Request, diagnosis_id: str, saved: str, error: str):
    user = w.require_user(request)
    owner = w.record_user(request, user)
    with connect(w.settings) as connection:
        row = diagnoses.get(connection, owner["id"], diagnosis_id)
        if row is None:
            raise HTTPException(404)
        page = _page(w, connection, owner["id"])
        item = _diagnosis_view(page, row)
        entry = icd10.entry(str(row["code"] or "")) if row["code"] else None
        if entry is not None:
            entry = {**entry, "category_title": icd10.name(entry["category"], page.locale)}
        mentions = [
            _mention_view(page, mention)
            for mention in diagnosis_candidates.mentions(connection, owner["id"], diagnosis_id)
        ]
        suspicion = _confirmed_suspicion(page, diagnosis_id)
        medicine_choices = [
            {"id": factor["id"], "name": factor["name"]}
            for factor in diagnosis_treatment.choices(connection, owner["id"], row, today=date.today())
        ]
    return w.templates.TemplateResponse(request, "diagnosis_detail.html", w.template_context(
        request, active="diagnoses", item=item, entry=entry, mentions=mentions, suspicion=suspicion,
        medicine_choices=medicine_choices, treatment_source_url=diagnosis_treatment.SOURCE_URL,
        writable=_writable(user, owner), saved=_message("dx.notice", saved),
        error=_message("dx.error", error),
    ))


async def _write(w: _Wiring, request: Request, work: Callable[[dict, Any], Any]):
    """A POST: the owner's own account, a valid CSRF token, then ``work(user, form)`` in a thread."""
    user = w.require_user(request)
    form = await request.form()
    owner = await run_in_threadpool(w.record_user, request, user)
    if not _writable(user, owner):
        raise HTTPException(403)
    w.require_csrf(user, str(form.get("csrf_token") or ""))
    return await run_in_threadpool(work, user, form)


def _start_scan(settings, user) -> JSONResponse:
    """Start the reading of the waiting documents as a job; the page polls for its progress."""
    if not ai.ai_active(settings, diagnosis_scan.FEATURE):
        return JSONResponse({"error": "disabled"})
    owner_id = user["id"]
    with connect(settings) as connection:
        waiting = diagnosis_scan.counts(connection, owner_id)["waiting"]
    if not waiting and not factor_jobs.running(owner_id, "dx_scan"):
        return JSONResponse({"error": "lost"})
    locale = get_locale()

    def work(report) -> dict:
        token = activate_locale(locale)
        try:
            return diagnosis_scan.scan(settings, partial(connect, settings), owner_id, locale=locale, report=report)
        finally:
            reset_locale(token)

    return JSONResponse({"job": factor_jobs.start(owner_id, work, kind="dx_scan", with_progress=True)})


def _scan_status(user_id: str, job_id: str) -> JSONResponse:
    job = factor_jobs.get(user_id, job_id)
    if job is None or job["kind"] != "dx_scan":
        return JSONResponse({"state": "failed", "error": "lost", "done": 0, "total": 0, "failed": 0})
    return JSONResponse({
        "state": job["state"], "error": job["error"], "done": job["done"], "total": job["total"],
        "failed": int((job["result"] or {}).get("failed") or 0),
    })


def register_routes(app, settings, *, templates, template_context, require_user, record_user, require_csrf,
                    audit, document_row, catalog, matrix_cards) -> None:
    """``audit`` is ``partial(_audit, settings)``; ``document_row`` renders a documents row as the record search does.

    ``catalog(connection, owner_id)`` gives the metric cards in the request's locale, for display;
    ``matrix_cards(connection, owner_id)`` gives them in English, for matching.
    """
    w = _Wiring(settings, templates, template_context, require_user, record_user, require_csrf, audit,
                document_row, catalog, matrix_cards)

    # Fixed paths come first: a path parameter declared earlier would take "new" or "codes" as an id.
    @app.get("/diagnoses", response_class=HTMLResponse)
    def diagnoses_page(request: Request, saved: str = "", error: str = ""):
        return _diagnoses_page(w, request, saved, error)

    @app.get("/diagnoses/new", response_class=HTMLResponse)
    def new_page(request: Request, code: str = "", suspicion: str = ""):
        return _new_page(w, request, code, suspicion)

    @app.post("/diagnoses/new")
    async def create_page(request: Request):
        return await _write(w, request, partial(_create, w, request))

    @app.get("/diagnoses/codes")
    def codes(request: Request, q: str = ""):
        require_user(request)
        return JSONResponse(icd10.search(q, get_locale(), 20))

    @app.get("/diagnoses/found/scan/{job_id}")
    def found_scan_status(request: Request, job_id: str):
        user = require_user(request)
        owner = record_user(request, user)
        if not _writable(user, owner):
            raise HTTPException(403)
        return _scan_status(user["id"], job_id)

    @app.post("/diagnoses/found/scan")
    async def found_scan_page(request: Request):
        return await _write(w, request, lambda user, form: _start_scan(settings, user))

    @app.post("/diagnoses/found")
    async def found_action_page(request: Request):
        return await _write(w, request, partial(_found_action, w))

    @app.post("/diagnoses/possible/check")
    async def possible_check_page(request: Request):
        return await _write(w, request, partial(_check_possible, w))

    @app.post("/diagnoses/possible/{suspicion_id}")
    async def possible_action_page(request: Request, suspicion_id: str):
        return await _write(w, request, partial(_possible_action, w, suspicion_id))

    @app.get("/diagnoses/{diagnosis_id}", response_class=HTMLResponse)
    def detail_page(request: Request, diagnosis_id: str, saved: str = "", error: str = ""):
        return _detail_page(w, request, diagnosis_id, saved, error)

    @app.get("/diagnoses/{diagnosis_id}/edit", response_class=HTMLResponse)
    def edit_page(request: Request, diagnosis_id: str):
        return _edit_page(w, request, diagnosis_id)

    @app.post("/diagnoses/{diagnosis_id}/edit")
    async def update_page(request: Request, diagnosis_id: str):
        return await _write(w, request, partial(_update, w, request, diagnosis_id))

    @app.post("/diagnoses/{diagnosis_id}/status")
    async def status_page(request: Request, diagnosis_id: str):
        return await _write(w, request, partial(_set_status, w, diagnosis_id))

    @app.post("/diagnoses/{diagnosis_id}/medicines")
    async def medicines_page(request: Request, diagnosis_id: str):
        return await _write(w, request, partial(_medicine_action, w, diagnosis_id))

    @app.post("/diagnoses/{diagnosis_id}/delete")
    async def delete_page(request: Request, diagnosis_id: str):
        return await _write(w, request, partial(_delete, w, diagnosis_id))
