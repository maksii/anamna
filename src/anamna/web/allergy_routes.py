"""The allergy overview page (/allergy): see :mod:`..allergy`."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from .. import allergy
from ..db import connect
from ..health import display_unit


def register_routes(app, settings, *, templates, template_context, require_user, record_user) -> None:
    @app.get("/allergy", response_class=HTMLResponse)
    def allergy_page(request: Request, q: str = ""):
        # app.py imports this module, so its helpers are read at request time:
        # every value is judged by the same path the lab pages use.
        from .app import _demographics, _reading_verdict, format_reading

        user = require_user(request)
        owner = record_user(request, user)
        with connect(settings) as connection:
            age, sex = _demographics(connection, owner["id"])

            def judge(row):
                return _reading_verdict(connection, row["concept_id"], row, age, sex)[1]

            def reading(row):
                return format_reading(row, row["preferred_unit"] or row["unit_raw"])

            view = allergy.overview(connection, owner["id"], judge=judge, reading=reading, query=q)
        return templates.TemplateResponse(request, "allergy.html", template_context(
            request, active="allergy", view=view, headline=allergy.headline(view), query=q.strip()[:80],
            unit_text=display_unit("kUA/L")))
