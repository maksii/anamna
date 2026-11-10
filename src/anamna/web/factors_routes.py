"""The Medicines pages: the record of medicines and other factors, one entry and
its page, its form, the lookup of medicine names, and the AI reference card.
Wired by create_app.

Reads go through ``record_user``, so a share viewer and a guest see the owner's
entries read-only.  Every write is bound to the signed-in account and refused to
a guest or to a share viewer.  The lookup and the AI research leave the machine,
so they run in the threadpool.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from urllib.parse import urlencode

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .. import ai, drugref, factor_research, factors
from ..db import connect, utc_now
from ..health import concept_display_name
from ..i18n import format_date_localized, get_locale, t
from ..locales.concepts_en import CONCEPT_NAMES_EN
from ..locales.concepts_uk import CONCEPT_NAMES_UK
from ..locales.messages_factors import MESSAGES_FACTORS
from . import factors_view

_AI_REASONS = frozenset(("disabled", "budget", "provider_error", "truncated", "in_progress"))
_ATC = re.compile(r"[A-Z][0-9]{2}(?:[A-Z]{1,2}(?:[0-9]{2})?)?")
_DOCUMENT_LIMIT = 200
_FACT_ILLNESS = frozenset(("illness", "infection_or_inflammation"))
_BLANK = {
    "name": "", "substance": "", "atc_code": "", "strength": "", "dose": "", "schedule": "",
    "started_on": "", "ended_on": "", "dates_approximate": 0, "reason": "", "prescriber": "",
    "document_id": "", "notes": "", "purpose": "", "usual_dose": "", "interactions": "",
    "monitoring": "", "cautions": "", "reference_name": "", "reference_code": "", "reference_url": "",
    "ai_fields": (),
}


def _writable(user, owner) -> bool:
    """The signed-in account is looking at its own record, and is not a guest."""
    return user.get("token_kind") != "guest" and owner["id"] == user["id"]


def _notice(key: str) -> str | None:
    """The translated text for a ``saved`` or ``error`` query value, or None for
    anything that is not one of ours (a query value is never echoed)."""
    message = f"med.{key}"
    return t(message) if message in MESSAGES_FACTORS else None


def _saved(value: str) -> str | None:
    return _notice(f"{value}_notice") if value else None


def _error(value: str) -> str | None:
    return _notice(f"error_{value}") if value else None


def _kind(value: str) -> str:
    return value if value in factors.KINDS else "medicine"


def _ai_error(exc: ai.AIUnavailable) -> str:
    return f"ai_{exc.reason if exc.reason in _AI_REASONS else 'provider_error'}"


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _kinds() -> list[tuple[str, str]]:
    return [(kind, t(f"med.kind.{kind}")) for kind in factors.KINDS]


def _concept_names(connection) -> dict[str, str]:
    return {row["id"]: row["canonical_name"] for row in connection.execute("SELECT id, canonical_name FROM concepts")}


def _metric_ids(connection, owner_id: str) -> frozenset[str]:
    return frozenset(
        row[0] for row in connection.execute(
            "SELECT DISTINCT concept_id FROM observations WHERE owner_user_id=? AND concept_id IS NOT NULL",
            (owner_id,),
        )
    )


def _concept_for_label(connection, label: str) -> str | None:
    """The concept whose localized or English name equals ``label``, ignoring case."""
    wanted = " ".join(label.split()).casefold()
    if not wanted:
        return None
    for row in connection.execute("SELECT id, canonical_name FROM concepts ORDER BY id"):
        canonical = row["canonical_name"]
        names = (canonical, CONCEPT_NAMES_EN.get(canonical, canonical), CONCEPT_NAMES_UK.get(canonical, canonical))
        if any(" ".join(name.split()).casefold() == wanted for name in names):
            return row["id"]
    return None


def _documents(connection, owner_id: str, document_row, document_id: str | None = None) -> list[dict]:
    """The owner's documents newest first as {id, label}; one of them when ``document_id`` is given."""
    where = "AND d.id = ?" if document_id else ""
    params: tuple = (owner_id, document_id) if document_id else (owner_id,)
    rows = connection.execute(
        f"""SELECT d.id, d.title, d.clinical_type, d.report_date, d.imported_at,
                   d.original_filename, v.canonical_name vendor
            FROM documents d LEFT JOIN vendors v ON v.id = d.vendor_id
            WHERE d.owner_user_id = ? AND d.duplicate_of_document_id IS NULL {where}
            ORDER BY COALESCE(d.report_date, substr(d.imported_at, 1, 10)) DESC, d.rowid DESC
            LIMIT {_DOCUMENT_LIMIT}""",
        params,
    ).fetchall()
    out = []
    for row in rows:
        item = document_row(row)
        label = " · ".join(part for part in (item["date_text"], item["title_text"]) if part)
        out.append({"id": row["id"], "label": label})
    return out


def _fact_notes(row: dict) -> list[str]:
    notes: list[str] = []
    seen: set[str] = set()
    needs_dates = not row["started_on"] or (row["effective_status"] == "past" and not row["ended_on"])
    for fact in row["facts"]:
        key = "illness" if fact in _FACT_ILLNESS else fact
        if key in seen:
            continue
        seen.add(key)
        text = t(f"med.fact.{key}")
        notes.append(f"{text} {t('med.fact.needs_dates')}" if needs_dates else text)
    return notes


def _research(settings, connection, user_id: str, factor_id: str, locale: str, today: date) -> bool:
    """Ask the AI about one entry and store the answer.  Returns whether any
    suggestion is now waiting for the person.  Raises ``ai.AIUnavailable``;
    nothing is stored then.  Blocking: call it from the threadpool."""
    row = factors.get(connection, user_id, factor_id, today=today)
    suggestion = factor_research.research(settings, connection, row, locale=locale)
    factors.store_suggestion(connection, user_id, factor_id, suggestion)
    codes = suggestion.get("atc_codes") or []
    if codes and not row["atc_code"] and _ATC.fullmatch(codes[0]):
        # The code comes from the reference page, never from the model's text.
        connection.execute(
            "UPDATE factors SET atc_code = ?, updated_at = ? WHERE id = ? AND owner_user_id = ? AND atc_code = ''",
            (codes[0], utc_now(), factor_id, user_id),
        )
    connection.commit()
    fresh = factors.get(connection, user_id, factor_id, today=today)
    return not factors.pending(fresh)["empty"]


def register_routes(app, settings, *, templates, template_context, require_user, record_user, require_csrf,
                    audit, document_row) -> None:
    """``audit`` is ``partial(_audit, settings)``; ``document_row`` renders a documents row as the record search does."""

    def form_response(request: Request, connection, owner_id: str, *, is_new: bool, factor: dict,
                      action: str, back_url: str, back_label: str):
        return templates.TemplateResponse(request, "medicine_form.html", template_context(
            request, active="medicines", is_new=is_new, factor=factor, kinds=_kinds(),
            statuses=factors.STATUSES, documents=_documents(connection, owner_id, document_row),
            lookup_on=drugref.enabled(connection), ai_ready=ai.ai_active(settings, factor_research.FEATURE),
            action=action, back_url=back_url, back_label=back_label,
            error=_error(request.query_params.get("error", "")),
        ))

    def owned_factor(connection, user_id: str, factor_id: str, today: date) -> dict:
        row = factors.get(connection, user_id, factor_id, today=today)
        if row is None:
            raise HTTPException(404)
        return row

    @app.get("/medicines", response_class=HTMLResponse)
    def medicines_page(request: Request, kind: str = "", saved: str = "", error: str = ""):
        user = require_user(request)
        owner = record_user(request, user)
        today = date.today()
        locale = get_locale()
        with connect(settings) as connection:
            rows = factors.listing(connection, owner["id"], today=today)
            metric_ids = _metric_ids(connection, owner["id"])
            names = _concept_names(connection)
        axis = factors_view.scale(rows, today, locale)
        counts = Counter(row["kind"] for row in rows)
        # A filter that matches nothing is ignored rather than showing an empty page.
        chosen = kind if kind in factors.KINDS and counts[kind] else ""
        shown = [row for row in rows if not chosen or row["kind"] == chosen]
        cards = [
            factors_view.card(row, locale=locale, today=today, scale=axis, metric_ids=metric_ids,
                              concept_names=names)
            for row in shown
        ]
        groups = []
        for key in ("current", "prescribed", "past"):
            entries = [item for item in cards if item["status"] == key]
            if entries:
                groups.append({"key": key, "label": t(f"med.group.{key}"), "entries": entries})
        filters = [{"label": t("med.filter_all"), "url": "/medicines", "count": len(rows), "active": not chosen}]
        for key in factors.KINDS:
            if counts[key]:
                filters.append({
                    "label": t(f"med.kinds.{key}"), "url": f"/medicines?kind={key}",
                    "count": counts[key], "active": chosen == key,
                })
        return templates.TemplateResponse(request, "medicines.html", template_context(
            request, active="medicines", groups=groups, filters=filters, scale=axis, kinds=_kinds(),
            saved=_saved(saved), error=_error(error),
        ))

    @app.get("/medicines/new", response_class=HTMLResponse)
    def new_page(request: Request, kind: str = ""):
        user = require_user(request)
        owner = record_user(request, user)
        if not _writable(user, owner):
            return _redirect("/medicines")
        factor = {**_BLANK, "kind": _kind(kind), "status": "current"}
        with connect(settings) as connection:
            return form_response(request, connection, user["id"], is_new=True, factor=factor,
                                 action="/medicines", back_url="/medicines", back_label=t("med.title"))

    def create(request: Request, user, form) -> RedirectResponse:
        today = date.today()
        values, problem = factors.clean(form, today=today)
        if problem:
            return _redirect(f"/medicines/new?{urlencode({'kind': _kind(str(form.get('kind') or '')), 'error': problem})}")
        with connect(settings) as connection:
            patient = connection.execute(
                "SELECT id FROM patients WHERE owner_user_id = ? ORDER BY created_at LIMIT 1", (user["id"],),
            ).fetchone()
            if patient is None:
                return _redirect("/medicines")
            factor_id = factors.create(connection, user["id"], patient["id"], values)
            audit(user["id"], user["id"], "factor.create", "factor", factor_id, {"kind": values["kind"]},
                  connection=connection)
            connection.commit()
            target = f"/medicines/{factor_id}"
            if form.get("research") != "1":
                return _redirect(f"{target}?saved=created")
            try:
                waiting = _research(settings, connection, user["id"], factor_id, get_locale(), today)
            except ai.AIUnavailable as exc:
                return _redirect(f"{target}?saved=created&error={_ai_error(exc)}")
        if waiting:
            return _redirect(f"{target}?saved=researched#suggestions")
        return _redirect(f"{target}?saved=researched_empty")

    @app.post("/medicines")
    async def create_page(request: Request):
        user = require_user(request)
        form = await request.form()
        owner = await run_in_threadpool(record_user, request, user)
        if not _writable(user, owner):
            raise HTTPException(403)
        require_csrf(user, str(form.get("csrf_token") or ""))
        return await run_in_threadpool(create, request, user, form)

    @app.get("/medicines/lookup")
    def lookup(request: Request, q: str = ""):
        user = require_user(request)
        owner = record_user(request, user)
        if not _writable(user, owner):
            raise HTTPException(403)
        with connect(settings) as connection:
            if not drugref.enabled(connection):
                return JSONResponse({"items": [], "error": "off"})
        try:
            items = drugref.suggest(q[:200])
        except drugref.DrugRefError:
            return JSONResponse({"items": [], "error": "unavailable"})
        return JSONResponse({"items": items})

    @app.get("/medicines/{factor_id}", response_class=HTMLResponse)
    def detail_page(request: Request, factor_id: str, saved: str = "", error: str = ""):
        user = require_user(request)
        owner = record_user(request, user)
        today = date.today()
        locale = get_locale()
        with connect(settings) as connection:
            row = owned_factor(connection, owner["id"], factor_id, today)
            metric_ids = _metric_ids(connection, owner["id"])
            names = _concept_names(connection)
            document_id = row["document_id"]
            documents = _documents(connection, owner["id"], document_row, document_id) if document_id else []
            effect_options = sorted({
                concept_display_name(names[concept]) for concept in metric_ids if concept in names
            })
        entry = factors_view.card(row, locale=locale, today=today, metric_ids=metric_ids, concept_names=names)
        entry["document"] = documents[0] if documents else None
        entry["fact_notes"] = _fact_notes(row)
        pending = None
        suggestion = row["suggestion"]
        if suggestion:
            state = factors.pending(row)
            source = suggestion.get("source") or None
            created = suggestion.get("created_at")
            pending = {
                "fields": [{**field, "label": t(f"med.field.{field['name']}")} for field in state["fields"]],
                "effects": [factors_view.effect_view(effect, locale, metric_ids, names) for effect in state["effects"]],
                "empty": state["empty"],
                "source": source,
                "created_text": format_date_localized(created) if created else "",
            }
        return templates.TemplateResponse(request, "medicine_detail.html", template_context(
            request, active="medicines", factor=entry, pending=pending, pending_at=row["suggestion_at"],
            effect_options=effect_options, ai_ready=ai.ai_active(settings, factor_research.FEATURE),
            saved=_saved(saved), error=_error(error),
        ))

    @app.get("/medicines/{factor_id}/edit", response_class=HTMLResponse)
    def edit_page(request: Request, factor_id: str):
        user = require_user(request)
        owner = record_user(request, user)
        if not _writable(user, owner):
            return _redirect(f"/medicines/{factor_id}")
        with connect(settings) as connection:
            row = owned_factor(connection, user["id"], factor_id, date.today())
            return form_response(request, connection, user["id"], is_new=False, factor=row,
                                 action=f"/medicines/{factor_id}", back_url=f"/medicines/{factor_id}",
                                 back_label=row["name"])

    def act(request: Request, user, factor_id: str, form) -> RedirectResponse:
        today = date.today()
        locale = get_locale()
        base = f"/medicines/{factor_id}"
        action = str(form.get("action") or "")
        with connect(settings) as connection:
            owned_factor(connection, user["id"], factor_id, today)
            if action == "save":
                values, problem = factors.clean(form, today=today)
                if problem:
                    return _redirect(f"{base}/edit?{urlencode({'error': problem})}")
                factors.update(connection, user["id"], factor_id, values)
                audit(user["id"], user["id"], "factor.update", "factor", factor_id, {"kind": values["kind"]},
                      connection=connection)
                connection.commit()
                return _redirect(f"{base}?saved=saved")
            if action == "stop":
                factors.stop(connection, user["id"], factor_id, today)
                connection.commit()
                return _redirect(f"{base}?saved=stopped")
            if action == "remove":
                factors.delete(connection, user["id"], factor_id)
                audit(user["id"], user["id"], "factor.delete", "factor", factor_id, {}, connection=connection)
                connection.commit()
                return _redirect("/medicines?saved=removed")
            if action == "research":
                try:
                    waiting = _research(settings, connection, user["id"], factor_id, locale, today)
                except ai.AIUnavailable as exc:
                    return _redirect(f"{base}?error={_ai_error(exc)}")
                if waiting:
                    return _redirect(f"{base}?saved=researched#suggestions")
                return _redirect(f"{base}?saved=researched_empty")
            if action == "apply":
                what = str(form.get("what") or "")
                factors.apply_suggestion(connection, user["id"], factor_id, what, today=today)
                connection.commit()
                if what == "dismiss":
                    return _redirect(f"{base}?saved=dismissed")
                state = factors.pending(factors.get(connection, user["id"], factor_id, today=today))
                return _redirect(f"{base}?saved=applied" + ("" if state["empty"] else "#suggestions"))
            if action == "effect_add":
                label = " ".join(str(form.get("label") or "").split())[:200]
                concept = _concept_for_label(connection, label)
                added = factors.add_effect(
                    connection, user["id"], factor_id, concept_id=concept, label=label,
                    direction=str(form.get("direction") or ""), note=str(form.get("note") or ""),
                )
                connection.commit()
                return _redirect(f"{base}?error=effect" if added is None else f"{base}?saved=effect_added")
            if action == "effect_remove":
                factors.remove_effect(connection, user["id"], str(form.get("effect_id") or ""))
                connection.commit()
                return _redirect(f"{base}?saved=effect_removed")
        raise HTTPException(400)

    @app.post("/medicines/{factor_id}")
    async def factor_action(request: Request, factor_id: str):
        user = require_user(request)
        form = await request.form()
        owner = await run_in_threadpool(record_user, request, user)
        if not _writable(user, owner):
            raise HTTPException(403)
        require_csrf(user, str(form.get("csrf_token") or ""))
        return await run_in_threadpool(act, request, user, factor_id, form)
