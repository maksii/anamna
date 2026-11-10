"""Routes injected into the existing app authentication and template boundary."""
from __future__ import annotations

import hmac
import json
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from ..i18n import t
from ..telegram_transport import TelegramError


def _require_webhook_secret(service, actual: str) -> None:
    """Authenticate before reading the body."""
    cfg = service.config()
    expected = service.webhook_secret()
    if not cfg["enabled"] or cfg["mode"] != "webhook" or not expected or not hmac.compare_digest(actual.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(403)


async def _read_bounded_body(request: Request) -> bytearray:
    """Bound streamed/chunked requests too."""
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 262144:
            raise HTTPException(413)
    return body


def register_telegram_routes(app, _settings, *, service, require_user, require_admin, require_csrf, template_context, templates):
    def render(request, *, error=None, done=None):
        return templates.TemplateResponse(request, "admin_telegram.html", template_context(request, active="admin_telegram", telegram=service.config(), error=error, done=done))

    @app.get("/admin/telegram")
    async def telegram_admin(request: Request):
        require_admin(request)
        return render(request)

    @app.post("/admin/telegram")
    async def telegram_configure(request: Request):
        admin = require_admin(request)
        form = await request.form()
        require_csrf(admin, str(form.get("csrf_token", "")))
        try:
            await run_in_threadpool(service.configure, enabled=form.get("action") == "activate", mode=str(form.get("mode", "polling")), public_url=str(form.get("public_url", "")), actor=admin["id"])
        except TelegramError as error:
            return render(request, error=t(error.key))
        return render(request, done=t("telegram.saved"))

    @app.post("/profile/telegram/link")
    async def telegram_link(request: Request):
        user = require_user(request)
        form = await request.form()
        require_csrf(user, str(form.get("csrf_token", "")))
        if form.get("consent") != "1":
            raise HTTPException(400, t("telegram.consent"))
        try:
            link = service.create_link(user["id"])
        except TelegramError as error:
            raise HTTPException(400, t(error.key)) from None
        response = templates.TemplateResponse(request, "telegram_link.html", template_context(request, active="profile", telegram_link=link))
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.post("/profile/telegram/unlink")
    async def telegram_unlink(request: Request):
        user = require_user(request)
        form = await request.form()
        require_csrf(user, str(form.get("csrf_token", "")))
        service.unlink(user["id"])
        return RedirectResponse("/profile?tab=connections#telegram", status_code=303)

    @app.post("/api/telegram/webhook")
    async def telegram_webhook(request: Request):
        # Authenticate before reading the body; bound streamed/chunked requests too.
        actual = request.headers.get("x-telegram-bot-api-secret-token", "")
        _require_webhook_secret(service, actual)
        body = await _read_bounded_body(request)
        try:
            update = json.loads(body)
            if not isinstance(update, dict):
                raise ValueError()
            await run_in_threadpool(service.receive, update, webhook_secret=actual)
        except (ValueError, TypeError, TelegramError):
            raise HTTPException(400) from None
        return JSONResponse({"ok": True})
