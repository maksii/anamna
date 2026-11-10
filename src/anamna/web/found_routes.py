"""Found in your documents: the Medicines page that lists what the documents say.

The page shows what the document reader found, one line for each medicine,
procedure or illness, with the passage it was read from.  Reading the
documents is a job: the page starts it, and the browser polls the job until it
ends, so a long reading does not hold a request.  Nothing becomes an entry
until the person ticks it and adds it.  A dismissed item is not offered again.
"""

from __future__ import annotations

from datetime import date
from functools import partial

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .. import ai, factor_candidates, factor_jobs, factor_scan, factors
from ..db import connect
from ..i18n import activate_locale, format_date_localized, get_locale, reset_locale, t, t_plural
from .factors_routes import _documents, _redirect, _writable

_SAVED = {"found_added": "med.found_added_notice", "found_dismissed": "med.found_dismissed_notice"}
_ERRORS = {
    "found_none": "med.error_found_none",
    "found_stopped": "med.error_found_stopped",
    "found_failed": "med.error_found_failed",
    "found_unread": "med.error_found_unread",
}
_MAX_KEYS = 200


def _notice(value: str, table: dict[str, str]) -> str | None:
    """The translated text for a known query value; any other value gives no notice."""
    key = table.get(value)
    return t(key) if key else None


def _date_text(day: str, exact: bool) -> str:
    """A date as the page prints it.  A date the document gave only by its year shows the year, marked approximate."""
    if not exact:
        return f"≈ {day[:4]}"
    return format_date_localized(day)


def _when(group: dict) -> str:
    """When the group was seen: the last date, or with several mentions the count and the first and last dates."""
    last = _date_text(group["last_date"], group["last_exact"]) if group["last_date"] else ""
    if group["mentions"] <= 1:
        return last
    parts = [t_plural("med.found.mentions", group["mentions"])]
    if group["first_date"]:
        parts.append(t("med.found.first_seen", date=_date_text(group["first_date"], group["first_exact"])))
    if last:
        parts.append(t("med.found.last_seen", date=last))
    return ", ".join(parts)


def _view(connection, owner_id: str, document_row, group: dict, seen: dict[str, dict | None]) -> dict:
    """One group as the found page reads it.  A document that no longer exists is left out.

    ``seen`` holds each document already read for this request, so a document several groups cite is read once.
    """
    documents = []
    for document in group["documents"]:
        if document["id"] not in seen:
            found = _documents(connection, owner_id, document_row, document["id"])
            seen[document["id"]] = found[0] if found else None
        if seen[document["id"]] is not None:
            documents.append(seen[document["id"]])
    return {
        "key": group["key"], "name": group["name"], "strength": group["strength"], "how": group["how"],
        "reason": group["reason"], "quote": group["quote"], "suggested_status": group["suggested_status"],
        "kind_label": t(f"med.kind.{group['kind']}"), "is_point": group["kind"] in factors.POINT_KINDS,
        "when_text": _when(group), "documents": documents,
    }


def register_routes(app, settings, *, templates, template_context, require_user, record_user, require_csrf,
                    audit, document_row) -> None:
    """``audit`` is ``partial(_audit, settings)``; ``document_row`` renders a documents row as the record search does."""

    @app.get("/medicines/found", response_class=HTMLResponse)
    def found_page(request: Request, saved: str = "", error: str = ""):
        user = require_user(request)
        owner = record_user(request, user)
        if not _writable(user, owner):
            return _redirect("/medicines")
        today = date.today()
        locale = get_locale()
        views: dict[bool, list[dict]] = {False: [], True: []}
        seen: dict[str, dict | None] = {}
        with connect(settings) as connection:
            counts = factor_scan.counts(connection, user["id"])
            for group in factor_candidates.groups(connection, user["id"], today=today, locale=locale):
                views[group["existing"]].append(_view(connection, user["id"], document_row, group, seen))
        return templates.TemplateResponse(request, "medicines_found.html", template_context(
            request, active="medicines", counts=counts,
            ai_ready=ai.ai_active(settings, factor_scan.FEATURE),
            job=factor_jobs.running(user["id"], "scan") or "",
            statuses=factors.STATUSES, fresh=views[False], existing=views[True],
            saved=_notice(saved, _SAVED), error=_notice(error, _ERRORS),
        ))

    def start_scan(user) -> JSONResponse:
        """Start the reading of the waiting documents as a job; the page polls for its progress."""
        if not ai.ai_active(settings, factor_scan.FEATURE):
            return JSONResponse({"error": "disabled"})
        owner_id = user["id"]
        with connect(settings) as connection:
            waiting = factor_scan.counts(connection, owner_id)["waiting"]
        if not waiting and not factor_jobs.running(owner_id, "scan"):
            return JSONResponse({"error": "lost"})
        locale = get_locale()

        def work(report) -> dict:
            token = activate_locale(locale)
            try:
                return factor_scan.scan(
                    settings, partial(connect, settings), owner_id, locale=locale, report=report,
                )
            finally:
                reset_locale(token)

        return JSONResponse({"job": factor_jobs.start(owner_id, work, kind="scan", with_progress=True)})

    @app.post("/medicines/found/scan")
    async def found_scan_page(request: Request):
        user = require_user(request)
        form = await request.form()
        owner = await run_in_threadpool(record_user, request, user)
        if not _writable(user, owner):
            raise HTTPException(403)
        require_csrf(user, str(form.get("csrf_token") or ""))
        return await run_in_threadpool(start_scan, user)

    @app.get("/medicines/found/scan/{job_id}")
    def found_scan_status(request: Request, job_id: str):
        user = require_user(request)
        owner = record_user(request, user)
        if not _writable(user, owner):
            raise HTTPException(403)
        job = factor_jobs.get(user["id"], job_id)
        if job is None or job["kind"] != "scan":
            return JSONResponse({"state": "failed", "error": "lost", "done": 0, "total": 0, "failed": 0})
        return JSONResponse({
            "state": job["state"], "error": job["error"], "done": job["done"], "total": job["total"],
            "failed": int((job["result"] or {}).get("failed") or 0),
        })

    def found_action(user, form) -> RedirectResponse:
        keys = [str(key) for key in form.getlist("key")][:_MAX_KEYS]
        if not keys:
            return _redirect("/medicines/found?error=found_none")
        action = str(form.get("action") or "")
        with connect(settings) as connection:
            if action == "accept":
                patient = connection.execute(
                    "SELECT id FROM patients WHERE owner_user_id = ? ORDER BY created_at LIMIT 1", (user["id"],),
                ).fetchone()
                if patient is None:
                    return _redirect("/medicines")
                statuses = {key: str(form.get(f"status:{key}") or "") for key in keys}
                created, failed = factor_candidates.accept(
                    connection, user["id"], patient["id"], keys, statuses, today=date.today(),
                )
                for factor_id in created:
                    audit(user["id"], user["id"], "factor.create", "factor", factor_id, {"source": "documents"},
                          connection=connection)
                connection.commit()
                if not created:
                    error = "found_failed" if failed else "found_none"
                    return _redirect(f"/medicines/found?error={error}")
                if failed:
                    return _redirect("/medicines/found?saved=found_added&error=found_failed")
                return _redirect("/medicines/found?saved=found_added")
            if action == "dismiss":
                factor_candidates.dismiss(connection, user["id"], keys)
                connection.commit()
                return _redirect("/medicines/found?saved=found_dismissed")
        raise HTTPException(400)

    @app.post("/medicines/found")
    async def found_action_page(request: Request):
        user = require_user(request)
        form = await request.form()
        owner = await run_in_threadpool(record_user, request, user)
        if not _writable(user, owner):
            raise HTTPException(403)
        require_csrf(user, str(form.get("csrf_token") or ""))
        return await run_in_threadpool(found_action, user, form)
