"""/genetics: the DNA (genetic tests) overview page (:mod:`..genetics`)."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from .. import genetics
from ..db import connect
from . import testplan_routes


def register_routes(app, settings, *, templates, template_context, require_user, record_user) -> None:
    @app.get("/genetics", response_class=HTMLResponse)
    def genetics_page(request: Request):
        from .app import _metric_catalog

        user = require_user(request)
        owner = record_user(request, user)
        with connect(settings) as connection:
            cards = _metric_catalog(connection, owner["id"])
            offers = testplan_routes.special_offers(settings, connection, owner["id"], genetics.ENTRIES)
            view = genetics.overview(connection, owner["id"], cards, offers)
        return templates.TemplateResponse(request, "genetics.html", template_context(
            request, active="genetics", view=view, uah=testplan_routes.uah))
