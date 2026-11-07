"""OpenWearables transport and administrator actions, wired by create_app."""
from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .. import openwearables as ow
from .. import openwearables_webhooks as hooks
from ..i18n import t


def _require_users(users: list[str]) -> None:
    if not users:
        raise hooks.WebhookError("select_accounts")


async def _read_limited_body(request: Request) -> bytearray:
    """The request body, refused as soon as it passes the webhook size cap."""
    body = bytearray()
    if int(request.headers.get("content-length", "0")) > hooks.MAX_BODY_BYTES:
        raise hooks.WebhookError("body_too_large", 413)
    async for chunk in request.stream():
        if len(body) + len(chunk) > hooks.MAX_BODY_BYTES:
            raise hooks.WebhookError("body_too_large", 413)
        body.extend(chunk)
    return body


async def _run_action(settings, action: str, form, receiver_id: str, users: list[str]) -> None:
    if action == "save":
        await run_in_threadpool(hooks.save_subscription, settings, str(form.get("public_url") or ""), receiver_id=receiver_id,
            remote_user_id=str(form.get("remote_user_id") or ""),
            filter_types=str(form.get("filter_types") or "").replace(",", " ").split())
    elif action == "delete":
        await run_in_threadpool(hooks.delete_subscription, settings, receiver_id)
    elif action == "test":
        await run_in_threadpool(hooks.test_subscription, settings, receiver_id, str(form.get("event_type") or "workout.created"))
    elif action == "retry":
        _require_users(users)
        await run_in_threadpool(hooks.retry_jobs, settings, user_ids=users)
    elif action == "sync":
        _require_users(users)
        await run_in_threadpool(hooks.enqueue_sync, settings, users, backfill=form.get("backfill") == "1")
    else:
        raise HTTPException(404)


def register_routes(app, settings, require_admin, require_csrf) -> None:
    @app.post("/webhooks/openwearables/{receiver_id}")
    async def receiver(request: Request, receiver_id: str):
        try:
            body = await _read_limited_body(request)
            result = await run_in_threadpool(hooks.receive, settings, receiver_id, bytes(body), request.headers)
            return JSONResponse(result, status_code=202)
        except hooks.WebhookError as exc:
            return JSONResponse({"error": exc.code}, status_code=exc.status)
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        # Database errors deliberately propagate as 5xx: upstream must retry
        # when the durable receipt could not be committed.

    @app.post("/admin/openwearables/webhooks/{action}")
    async def administer(request: Request, action: str):
        admin = await run_in_threadpool(require_admin, request)
        form = await request.form()
        await run_in_threadpool(require_csrf, admin, str(form.get("csrf_token") or ""))
        receiver_id = str(form.get("receiver_id") or "")
        users = [str(value) for value in form.getlist("user_ids") if value]
        try:
            await _run_action(settings, action, form, receiver_id, users)
        except (hooks.WebhookError, ow.OpenWearablesError):
            return RedirectResponse("/admin/openwearables?hook_error=1", status_code=303)
        return RedirectResponse("/admin/openwearables?hook_done=1", status_code=303)

    @app.get("/admin/openwearables/jobs", response_class=HTMLResponse)
    def all_jobs(request: Request, offset: int = 0):
        """The background-check rows past the first page, loaded on request."""
        require_admin(request)
        from .app import templates  # created with the app module that imports this one
        status = hooks.operational_status(settings)
        status["jobs"] = hooks.job_rows(settings, offset=max(0, offset), limit=1000)
        return templates.env.get_template("_openwearables_jobs.html").render(ow_hooks=status, admin=True)

    @app.get("/admin/openwearables/webhooks/{receiver_id}/attempts")
    def attempts(request: Request, receiver_id: str):
        require_admin(request)
        try:
            return hooks.remote_evidence(settings, receiver_id)
        except (hooks.WebhookError, ow.OpenWearablesError) as exc:
            raise HTTPException(502, t("ow_hooks.error")) from exc
