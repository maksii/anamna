"""Lab connections (EskuLab, Synevo, the mobile-app labs): admin switch, per-person connection,
sync, and the document cross-check's verify button.  Wired by create_app."""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .. import labsync
from ..i18n import format_number_localized
from ..labsync.common import parse_result

SAVED_CHECKED = "labsync.saved_checked"
RECHECK_COUNTS = ("orders", "relinked", "units", "units_undone", "flags", "flags_undone", "tasks")

SAVED_KEYS = frozenset({
    "labsync.saved_credentials", SAVED_CHECKED,
    "labsync.saved_sync", "labsync.saved_forgotten",
    "labsync.password_code_sent", "labsync.password_code_cancelled", "labsync.sms_choose_person",
})


def _lab_value(text: object) -> str:
    """The lab's printed result in this locale's number format; words as-is."""
    sign, number = parse_result(text)
    if number is None:
        return str(text or "")
    printed = str(text).replace(",", ".")
    decimals = len(printed.partition(".")[2].strip()) if "." in printed else 0
    return (sign or "") + format_number_localized(number, decimals)


def _lab_numeric(text: object) -> str:
    """The lab's result as the manual-entry form reads it (``<0.5``), or ''."""
    sign, number = parse_result(text)
    return "" if number is None else (sign or "") + str(text).strip().lstrip("<>=≤≥ ").replace(",", ".")


def _back(key: str, message: str) -> RedirectResponse:
    return RedirectResponse(f"/profile?tab=connections&lab={key}&lab_msg={message}#lab-{key}", status_code=303)


def _inbox_back(message: str) -> RedirectResponse:
    return RedirectResponse(f"/profile?tab=connections&lab=inbox&lab_msg={message}#lab-inbox", status_code=303)


def _register_globals(settings, templates) -> None:
    from .app import _cached  # create_app's module, loaded by now; request-scoped memo

    def once(name: str, user, *args, build):
        """One computation per request: the document page asks for its
        cross-check twice (panel and per-row badges) — PERF-13."""
        return _cached(("labsync", name, (user or {}).get("id"), (user or {}).get("token_kind"), *args), build)

    env = templates.env
    env.globals["lab_profile_cards"] = lambda user: once(
        "cards", user, build=lambda: labsync.profile_cards(settings, user))
    env.globals["lab_document_check"] = lambda user, document_id: once(
        "check", user, document_id, build=lambda: labsync.document_check(settings, user, document_id))
    env.globals["lab_observation_classes"] = lambda user, document_id: (
        env.globals["lab_document_check"](user, document_id) or {}).get("by_observation", {})
    env.globals["lab_message_keys"] = labsync.ERROR_KEYS | SAVED_KEYS | labsync.LINK_KEYS
    env.globals["lab_record"] = lambda document_id: labsync.lab_record(settings, document_id)
    env.globals["lab_inbox"] = lambda user: once("inbox", user, build=lambda: labsync.inbox(settings, user))
    env.globals["lab_inbox_count"] = lambda user: once(
        "inbox_count", user, build=lambda: labsync.inbox_count(settings, user))
    env.globals["lab_pending_code"] = lambda user, key: labsync.pending_code(user["id"], key) if user else None
    env.globals["lab_sign_in"] = lambda key: getattr(labsync.PROVIDERS.get(key), "SIGN_IN", "paste")
    env.filters["labvalue"] = _lab_value
    env.filters["labnumeric"] = _lab_numeric


def _admin_providers(settings) -> list[dict]:
    return [
        {"key": key, "name": module.NAME, "default_url": module.DEFAULT_URL,
         "sign_in": getattr(module, "SIGN_IN", "paste"), "messages": getattr(module, "MESSAGES", key),
         "config": labsync.provider_settings(settings, key), "active": labsync.active(settings, key),
         "counts": labsync.instance_counts(settings, key)}
        for key, module in labsync.PROVIDERS.items()
    ]


def _rechecked_counts(params) -> dict[str, str]:
    return {name: format_number_localized(int(params.get(name) or 0), 0)
            for name in RECHECK_COUNTS if (params.get(name) or "0").isdigit()}


def _admin_done(done: str, rechecked: dict[str, str]) -> str:
    if done in {"saved", "saved_forgot"}:
        return done
    return done if done == "rechecked" and len(rechecked) == len(RECHECK_COUNTS) else ""


def _register_admin_routes(app, settings, *, templates, template_context, require_admin, require_csrf, audit,
                           invalidate) -> None:
    @app.get("/admin/lab-connections", response_class=HTMLResponse)
    def admin_page(request: Request, done: str = "", error: str = "", provider: str = ""):
        require_admin(request)
        rechecked = _rechecked_counts(request.query_params)
        return templates.TemplateResponse(request, "admin_labsync.html", template_context(
            request, active="admin_labsync", providers=_admin_providers(settings), focus=provider,
            rechecked=rechecked, done=_admin_done(done, rechecked),
            error=error if error in labsync.ERROR_KEYS else ""))

    @app.post("/admin/lab-connections/recheck")
    async def admin_recheck(request: Request):
        """Re-run every stored order's post-sync steps — no lab is contacted.
        The repair to run after a deploy that changed them; idempotent."""
        admin = await run_in_threadpool(require_admin, request)
        form = await request.form()
        await run_in_threadpool(require_csrf, admin, str(form.get("csrf_token") or ""))
        summary = await run_in_threadpool(labsync.recheck, settings)
        await run_in_threadpool(audit, admin["id"], admin["id"], "admin_labsync_rechecked", "lab_orders", "all",
                                summary)
        invalidate()
        query = "&".join(f"{name}={int(count)}" for name, count in summary.items())
        return RedirectResponse(f"/admin/lab-connections?done=rechecked&{query}#lab-admin-recheck", status_code=303)

    @app.post("/admin/lab-connections/{key}")
    async def admin_save(request: Request, key: str):
        admin = await run_in_threadpool(require_admin, request)
        form = await request.form()
        await run_in_threadpool(require_csrf, admin, str(form.get("csrf_token") or ""))
        if key not in labsync.PROVIDERS:
            raise HTTPException(404)
        enabled = form.get("enabled") == "1"
        try:
            forgotten = await run_in_threadpool(
                lambda: labsync.save_provider_settings(settings, key, enabled=enabled, url=str(form.get("url") or "")))
        except labsync.LabSyncError as exc:
            return RedirectResponse(f"/admin/lab-connections?provider={key}&error={exc.key}#lab-admin-{key}",
                                    status_code=303)
        await run_in_threadpool(audit, admin["id"], admin["id"], "admin_labsync_changed", "app_settings", key,
                                {"enabled": enabled, "credentials_forgotten": forgotten})
        done = "saved_forgot" if forgotten else "saved"
        return RedirectResponse(f"/admin/lab-connections?provider={key}&done={done}#lab-admin-{key}", status_code=303)


async def _check_signed_in(settings, user, key: str) -> RedirectResponse:
    """Signing in already proved the account; ask who is on it at once."""
    try:
        await run_in_threadpool(labsync.check_account, settings, user["id"], key)
    except labsync.LabSyncError as exc:
        return _back(key, exc.key)
    return _back(key, SAVED_CHECKED)


def _register_credential_routes(app, settings, *, person_form, audit) -> None:
    @app.post("/profile/lab/{key}/credentials")
    async def save_credentials(request: Request, key: str):
        user, form = await person_form(request, key)
        values = {name: str(form.get(name) or "")
                  for name in ("credentials_json", "token", "phone", "password", "code", "patient")}
        try:
            saved = await run_in_threadpool(labsync.save_credentials, settings, user["id"], key, values)
        except labsync.LabSyncError as exc:
            return _back(key, exc.key)
        finally:
            values.clear()  # the password lives no longer than this request
        if saved in ("labsync.password_code_sent", "labsync.sms_choose_person"):
            return _back(key, saved)
        # Never the secret: what changed, not what it is.
        await run_in_threadpool(audit, user["id"], user["id"], "labsync_credentials_saved", "lab_accounts", key, {})
        if labsync.signs_in(key):
            return await _check_signed_in(settings, user, key)
        return _back(key, saved)

    @app.post("/profile/lab/{key}/forget")
    async def forget(request: Request, key: str):
        user, _ = await person_form(request, key)
        row = await run_in_threadpool(labsync.account, settings, user["id"], key)
        await run_in_threadpool(labsync.forget, settings, user["id"], key)
        if not row or not row["secret"]:  # only a texted-code step was waiting
            return _back(key, "labsync.password_code_cancelled")
        await run_in_threadpool(audit, user["id"], user["id"], "labsync_credentials_forgotten", "lab_accounts", key, {})
        return _back(key, "labsync.saved_forgotten")

    @app.post("/profile/lab/{key}/check")
    async def check(request: Request, key: str):
        user, _ = await person_form(request, key)
        return await _check_signed_in(settings, user, key)


async def _audit_link(audit, user, key: str, linked: dict, person_id: str, confirmed: bool) -> None:
    details = {"remote_person_id": person_id, "target_user_id": linked["target"],
               "consent": linked["consent"], "confirmed_mismatch": confirmed}
    await run_in_threadpool(audit, user["id"], user["id"], "labsync_person_linked", "lab_person_links", key, details)
    if linked["target"] != user["id"]:
        # The receiving record's own trail says who links results to it.
        await run_in_threadpool(audit, linked["target"], user["id"], "labsync_person_linked",
                                "lab_person_links", key, details)


async def _sync_after_link(settings, user, key: str, linked: dict) -> str:
    try:
        await run_in_threadpool(labsync.start_sync, settings, user["id"], key)
    except labsync.LabSyncError as exc:
        return "labsync.link_saved_running" if exc.key == "labsync.error_running" else exc.key
    return "labsync.link_saved_self" if linked["target"] == user["id"] else "labsync.link_saved_other"


def _register_link_routes(app, settings, *, person_form, audit) -> None:
    @app.post("/profile/lab/{key}/link")
    async def link(request: Request, key: str):
        """Link one person on the lab account to a record: one's own (synced
        straight away) or a family member's (fetched and held for them)."""
        user, form = await person_form(request, key)
        person_id, target = str(form.get("person_id") or ""), str(form.get("target") or "")
        confirmed = form.get("confirm") == "1"
        try:
            linked = await run_in_threadpool(labsync.link_person, settings, user["id"], key, person_id, target,
                                             confirmed)
        except labsync.LabSyncError as exc:
            return _back(key, exc.key)
        if linked["target"] is None:
            await run_in_threadpool(audit, user["id"], user["id"], "labsync_person_unlinked", "lab_person_links",
                                    key, {"remote_person_id": person_id})
            return _back(key, "labsync.link_removed")
        await _audit_link(audit, user, key, linked, person_id, confirmed)
        return _back(key, await _sync_after_link(settings, user, key, linked))

    @app.post("/profile/lab/{key}/sync")
    async def sync(request: Request, key: str):
        user, _ = await person_form(request, key)
        row = await run_in_threadpool(labsync.account, settings, user["id"], key)
        if not row or not row["secret"]:
            return _back(key, "labsync.error_no_credentials")
        if not await run_in_threadpool(labsync.has_links, settings, user["id"], key):
            return _back(key, "labsync.error_no_patient")
        try:
            await run_in_threadpool(labsync.start_sync, settings, user["id"], key)
        except labsync.LabSyncError as exc:
            return _back(key, exc.key)
        await run_in_threadpool(audit, user["id"], user["id"], "labsync_sync_started", "lab_accounts", key, {})
        return _back(key, "labsync.saved_sync")


def _register_status_route(app, settings, *, templates, template_context, require_user) -> None:
    @app.get("/api/lab-sync/{key}/status")
    def sync_status(request: Request, key: str):
        """Where this person's sync stands, for the card to update itself in
        place while a run is going (PERF-06).  ``html`` is the rendered card;
        the page swaps only its live parts -- the progress line and the
        orders as they arrive, then the summary."""
        user = require_user(request)
        card = labsync.profile_card(settings, user, key)
        if card is None:
            raise HTTPException(404)
        body = {"state": card["sync_state"], "finished_at": card["sync_finished_at"]}
        body["html"] = templates.get_template("_labsync_profile.html").render(template_context(request, card=card))
        return JSONResponse(body, headers={"Cache-Control": "no-store"})


def _register_inbox_routes(app, settings, *, person_form, audit, invalidate) -> None:
    """Results somebody else's lab account fetched for this user."""

    async def inbox_form(request: Request, key: str):
        user, form = await person_form(request, key)
        return user, form, str(form.get("account") or ""), str(form.get("person_id") or "")

    @app.post("/profile/lab-inbox/{key}/decide")
    async def decide(request: Request, key: str):
        user, form, holder, person_id = await inbox_form(request, key)
        accept = form.get("decision") == "accept"
        orders = [str(value) for value in form.getlist("order_ids") if value]
        try:
            count = await run_in_threadpool(labsync.decide_orders, settings, user["id"], key, holder, person_id,
                                            orders, accept)
        except labsync.LabSyncError as exc:
            return _inbox_back(exc.key)
        action = "labsync_results_accepted" if accept else "labsync_results_declined"
        await run_in_threadpool(audit, user["id"], user["id"], action, "lab_orders", key,
                                {"account_user_id": holder, "remote_person_id": person_id, "orders": count})
        invalidate()
        return _inbox_back("labsync.inbox_accepted" if accept else "labsync.inbox_declined")

    @app.post("/profile/lab-inbox/{key}/consent")
    async def consent(request: Request, key: str):
        user, form, holder, person_id = await inbox_form(request, key)
        choice = str(form.get("consent") or "")
        try:
            await run_in_threadpool(labsync.set_consent, settings, user["id"], key, holder, person_id, choice)
        except labsync.LabSyncError as exc:
            return _inbox_back(exc.key)
        await run_in_threadpool(audit, user["id"], user["id"], "labsync_link_consent", "lab_person_links", key,
                                {"account_user_id": holder, "remote_person_id": person_id, "consent": choice})
        invalidate()
        return _inbox_back("labsync.inbox_consent_saved")


def _register_verify_route(app, settings, *, require_user, require_csrf, invalidate) -> None:
    """The document's cross-check."""

    @app.post("/documents/{document_id}/lab-verify")
    async def verify(request: Request, document_id: str):
        user = await run_in_threadpool(require_user, request)
        form = await request.form()
        await run_in_threadpool(require_csrf, user, str(form.get("csrf_token") or ""))
        if not await run_in_threadpool(labsync.active_providers, settings):
            raise HTTPException(404)
        ids = [str(value) for value in form.getlist("observation_ids") if value]
        try:
            count = await run_in_threadpool(labsync.verify_matches, settings, user["id"], document_id, ids,
                                            user.get("token_kind"))
        except LookupError:
            raise HTTPException(404) from None

        def recount() -> None:
            # The document's open task asked for these values; it counts again.
            from ..db import connect
            from ..ingest.pipeline import recount_review_tasks

            with connect(settings) as connection:
                recount_review_tasks(connection, user["id"], document_id, user["id"])

        await run_in_threadpool(recount)
        invalidate()
        return RedirectResponse(f"/documents/{document_id}?lab_verified={count}#lab-crosscheck", status_code=303)


def register_routes(app, settings, *, templates, template_context, require_user, require_admin, require_csrf,
                    audit, invalidate) -> None:
    _register_globals(settings, templates)

    async def person_form(request: Request, key: str):
        """The signed-in person, their form, and the provider — or 404 when the
        operator has not enabled it: an integration that is off does not exist."""
        user = await run_in_threadpool(require_user, request)
        form = await request.form()
        await run_in_threadpool(require_csrf, user, str(form.get("csrf_token") or ""))
        if key not in labsync.PROVIDERS or not await run_in_threadpool(labsync.active, settings, key):
            raise HTTPException(404)
        return user, form

    _register_admin_routes(app, settings, templates=templates, template_context=template_context,
                           require_admin=require_admin, require_csrf=require_csrf, audit=audit,
                           invalidate=invalidate)
    _register_credential_routes(app, settings, person_form=person_form, audit=audit)
    _register_link_routes(app, settings, person_form=person_form, audit=audit)
    _register_status_route(app, settings, templates=templates, template_context=template_context,
                           require_user=require_user)
    _register_inbox_routes(app, settings, person_form=person_form, audit=audit, invalidate=invalidate)
    _register_verify_route(app, settings, require_user=require_user, require_csrf=require_csrf,
                           invalidate=invalidate)
