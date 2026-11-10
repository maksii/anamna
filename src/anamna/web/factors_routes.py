"""The Medicines pages: the list, one entry and its page, its form, the lookup of
medicine names, and the AI reference card.  Wired by create_app.

Reads go through ``record_user``, so a share viewer and a guest see the owner's
entries read-only.  Every write is bound to the signed-in account and refused to
a guest or to a share viewer.  The lookup and the AI research leave the machine,
so they run in the threadpool.

The AI research runs as a job that the form polls, so a slow answer does not
hold the request.  Saving an entry never calls the AI.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import date

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .. import ai, drugref, factor_jobs, factor_research, factors
from ..db import connect
from ..health import concept_display_name
from ..i18n import activate_locale, get_locale, reset_locale, t
from ..locales.concepts_en import CONCEPT_NAMES_EN
from ..locales.concepts_uk import CONCEPT_NAMES_UK
from ..locales.messages_factors import MESSAGES_FACTORS
from . import factors_view

_ATC = re.compile(r"[A-Z][0-9]{2}(?:[A-Z]{1,2}(?:[0-9]{2})?)?")
_DOCUMENT_LIMIT = 200
_FACT_ILLNESS = frozenset(("illness", "infection_or_inflammation"))
# Fields that a form posts more than once; every other field has one value.
_MULTI = ("weekday", "day_part", "clock", "ai_effect")
_BLANK = {
    "name": "", "substance": "", "atc_code": "", "strength": "", "dose": "", "schedule": "",
    "started_on": "", "ended_on": "", "dates_approximate": 0, "reason": "", "prescriber": "",
    "document_id": "", "notes": "", "purpose": "", "usual_dose": "", "interactions": "",
    "monitoring": "", "cautions": "", "reference_name": "", "reference_code": "", "reference_url": "",
    "ai_fields": (), "dose_amount": None, "dose_unit": "", "regimen": None,
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


def _draft(form, *, today: date) -> dict:
    """What the person posted, shaped like an entry, for showing the form again
    or for the AI.  Unlike ``factors.clean`` it never refuses: a missing name or a
    bad date is replaced for the cleaning and the posted text is put back."""
    multi = hasattr(form, "getlist")
    posted = {key: (form.getlist(key) if multi and key in _MULTI else form.get(key)) for key in form.keys()}
    name = str(posted.get("name") or "").strip()[: factors.SHORT]
    safe = {**posted, "kind": _kind(str(posted.get("kind") or "")), "name": name or "-"}
    values, problem = factors.clean(safe, today=today)
    if problem in ("date_format", "dates"):
        values, problem = factors.clean({**safe, "started_on": "", "ended_on": ""}, today=today)
    # The kind and the name are valid by now, so clean refuses nothing else.
    values["name"] = name
    values["started_on"] = str(posted.get("started_on") or "").strip()
    values["ended_on"] = str(posted.get("ended_on") or "").strip()
    values["regimen"] = json.loads(values["schedule_json"]) if values["schedule_json"] else None
    values["ai_fields"] = tuple(values.get("ai_fields", ()))
    return {**_BLANK, **values}


def _suggestion_view(suggestion: dict, kind: str, locale: str, metric_ids, names, have: list[dict]) -> dict:
    """What the form shows for one AI answer: the suggested texts with their quotes,
    the effects the entry does not have yet, the code, the source and the regimen."""
    posted_fields = suggestion.get("fields") or {}
    fields = {
        name: {"text": posted_fields[name].get("text", ""), "quote": posted_fields[name].get("quote", "")}
        for name in factors.SUGGESTED_FIELDS if name in posted_fields
    }
    effects = []
    for effect in suggestion.get("effects") or []:
        label = " ".join(str(effect.get("label") or "").split()).casefold()
        concept = effect.get("concept_id") or ""
        if any((concept and item["concept_id"] == concept) or (label and item["label"] == label) for item in have):
            continue
        view = factors_view.effect_view(effect, locale, metric_ids, names)
        effects.append({
            key: view.get(key, "")
            for key in ("concept_id", "label", "direction", "direction_label", "note", "quote")
        })
    atc = next((code for code in suggestion.get("atc_codes") or [] if _ATC.fullmatch(str(code))), "")
    source = suggestion.get("source")
    source_view = {"url": source.get("url", ""), "shown_for": source.get("shown_for", "")} if source else None
    regimen = suggestion.get("regimen")
    regimen_view = None
    if regimen is not None:
        plan = {
            "repeat": regimen["repeat"], "every": regimen["every"], "weekdays": [],
            "per_day": regimen["per_day"], "times": [], "clock": [], "meal": "",
        }
        text = factors.regimen_text({
            "kind": kind, "dose_amount": regimen["dose_amount"], "dose_unit": regimen["dose_unit"],
            "dose": "", "schedule": "", "regimen": plan,
        }, locale)
        regimen_view = {
            **{key: value for key, value in regimen.items() if key != "quote"},
            "quote": regimen.get("quote", ""), "text": text,
        }
    return {"fields": fields, "effects": effects, "atc_code": atc, "source": source_view, "regimen": regimen_view}


def register_routes(app, settings, *, templates, template_context, require_user, record_user, require_csrf,
                    audit, document_row) -> None:
    """``audit`` is ``partial(_audit, settings)``; ``document_row`` renders a documents row as the record search does."""

    def form_response(request: Request, connection, owner_id: str, *, is_new: bool, factor: dict,
                      action: str, back_url: str, back_label: str, autostart: bool = False,
                      error: str | None = None, status_code: int = 200):
        return templates.TemplateResponse(request, "medicine_form.html", template_context(
            request, active="medicines", is_new=is_new, factor=factor, kinds=_kinds(),
            statuses=factors.STATUSES, documents=_documents(connection, owner_id, document_row),
            lookup_on=drugref.enabled(connection), ai_ready=ai.ai_active(settings, factor_research.FEATURE),
            action=action, back_url=back_url, back_label=back_label,
            dose_units=factors.DOSE_UNITS, repeats=factors.REPEATS, day_parts=factors.DAY_PARTS,
            meals=factors.MEALS, autostart=autostart,
            error=error if error is not None else _error(request.query_params.get("error", "")),
        ), status_code=status_code)

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

    def create(request: Request, user, form):
        today = date.today()
        values, problem = factors.clean(form, today=today)
        if problem:
            with connect(settings) as connection:
                return form_response(
                    request, connection, user["id"], is_new=True, factor=_draft(form, today=today),
                    action="/medicines", back_url="/medicines", back_label=t("med.title"),
                    error=_error(problem), status_code=400,
                )
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
        return _redirect(f"/medicines/{factor_id}?saved=created")

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
        locale = get_locale()
        try:
            items = drugref.suggest(q[:200])
        except drugref.DrugRefPaused as exc:
            return JSONResponse({"items": [], "error": "paused", "minutes": max(1, math.ceil(exc.seconds / 60))})
        except drugref.DrugRefError:
            return JSONResponse({"items": [], "error": "unavailable"})
        for item in items:
            item["strength"] = drugref.localize_strength(item.get("strength") or "", locale)
        return JSONResponse({"items": items})

    def start_research(user, form) -> JSONResponse:
        """Start the AI research for the posted draft as a job; the form polls for the answer."""
        if not ai.ai_active(settings, factor_research.FEATURE):
            return JSONResponse({"error": "disabled"})
        today = date.today()
        draft = _draft(form, today=today)
        if not draft["name"]:
            return JSONResponse({"error": "lost"}, status_code=400)
        factor_id = str(form.get("factor_id") or "")
        have: list[dict] = []
        with connect(settings) as connection:
            if factor_id and factors.get(connection, user["id"], factor_id, today=today) is None:
                factor_id = ""  # never research against another person's entry
            if factor_id:
                have = [
                    {"concept_id": row["concept_id"], "label": " ".join(str(row["label"] or "").split()).casefold()}
                    for row in connection.execute(
                        "SELECT concept_id, label FROM factor_effects WHERE factor_id = ? AND owner_user_id = ?",
                        (factor_id, user["id"]),
                    )
                ]
        entry = {**draft, "id": factor_id, "owner_user_id": user["id"], "how_taken": factors.regimen_text(draft, "en")}
        locale = get_locale()
        kind = entry["kind"]

        def work() -> dict:
            token = activate_locale(locale)
            try:
                with connect(settings) as connection:
                    suggestion = factor_research.research(settings, connection, entry, locale=locale)
                    connection.commit()
                    metric_ids = _metric_ids(connection, user["id"])
                    names = _concept_names(connection)
                return _suggestion_view(suggestion, kind, locale, metric_ids, names, have)
            finally:
                reset_locale(token)

        return JSONResponse({"job": factor_jobs.start(user["id"], work)})

    @app.post("/medicines/suggest")
    async def suggest_page(request: Request):
        user = require_user(request)
        form = await request.form()
        owner = await run_in_threadpool(record_user, request, user)
        if not _writable(user, owner):
            raise HTTPException(403)
        require_csrf(user, str(form.get("csrf_token") or ""))
        return await run_in_threadpool(start_research, user, form)

    @app.get("/medicines/suggest/{job_id}")
    def suggest_status(request: Request, job_id: str):
        user = require_user(request)
        owner = record_user(request, user)
        if not _writable(user, owner):
            raise HTTPException(403)
        job = factor_jobs.get(user["id"], job_id)
        if job is None:
            return JSONResponse({"state": "failed", "error": "lost"})
        if job["state"] == "done":
            return JSONResponse({"state": "done", "suggestion": job["result"]})
        if job["state"] == "failed":
            return JSONResponse({"state": "failed", "error": job["error"] or "provider_error"})
        return JSONResponse({"state": "running"})

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
        return templates.TemplateResponse(request, "medicine_detail.html", template_context(
            request, active="medicines", factor=entry,
            effect_options=effect_options, ai_ready=ai.ai_active(settings, factor_research.FEATURE),
            saved=_saved(saved), error=_error(error),
        ))

    @app.get("/medicines/{factor_id}/edit", response_class=HTMLResponse)
    def edit_page(request: Request, factor_id: str, suggest: str = ""):
        user = require_user(request)
        owner = record_user(request, user)
        if not _writable(user, owner):
            return _redirect(f"/medicines/{factor_id}")
        with connect(settings) as connection:
            row = owned_factor(connection, user["id"], factor_id, date.today())
            return form_response(
                request, connection, user["id"], is_new=False, factor=row,
                action=f"/medicines/{factor_id}", back_url=f"/medicines/{factor_id}",
                back_label=row["name"],
                autostart=suggest == "1" and ai.ai_active(settings, factor_research.FEATURE),
            )

    def act(request: Request, user, factor_id: str, form) -> RedirectResponse:
        today = date.today()
        base = f"/medicines/{factor_id}"
        action = str(form.get("action") or "")
        with connect(settings) as connection:
            stored = owned_factor(connection, user["id"], factor_id, today)
            if action == "save":
                values, problem = factors.clean(form, today=today)
                if problem:
                    return form_response(
                        request, connection, user["id"], is_new=False,
                        factor={**_draft(form, today=today), "id": factor_id},
                        action=base, back_url=base, back_label=stored["name"],
                        error=_error(problem), status_code=400,
                    )
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
