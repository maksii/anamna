"""The results page: one list of everything the record holds, from three former pages.

/results replaces /metrics (the search and the result list), /panels (the test
groups, now one way to group the list) and /changes (the latest result episode
and how each test moved).  Its quick filters count what they open; a search
box finds a result, a test group, a document or a medicine by name.

Nothing here judges a value.  The verdicts and the comparisons come from the
same helpers the metric and panel pages use, so the three cannot disagree.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from ..db import connect
from ..i18n import get_locale, t
from .changes import (
    AI_ERRORS,
    BUCKETS,
    EPISODE_GAP_DAYS,
    GROUPS,
    SHOWS,
    SORTS,
    _can_ask,
    arrange,
    attach_notes,
    build_changes,
    load_summary,
    view_options,
    view_query,
)


def _attention_ids(web, catalog: list[dict]) -> set[str]:
    """The ids of the results that need attention now."""
    return {str(card["id"]) for card in web._attention_cards(catalog)}


def mark(entries: list[dict], *, everything: bool, catalog: list[dict], panels: list[dict], web) -> None:
    """Stamp each entry with what the page shows about it: historical, attention, due and,
    for an entry that needs attention, how far outside its interval it sits (`outside_by_text`).

    On the whole record `attention` is the metric's own attention state; on a
    selected period it is the change itself (new, still or borderline).
    """
    by_id = {str(card["id"]): card for card in catalog}
    attention_ids = _attention_ids(web, catalog)
    due_ids = {str(panel["id"]) for panel in web._due_panels(panels)}
    for entry in entries:
        card = by_id.get(entry["concept_id"]) or {}
        entry["historical"] = bool(everything and card.get("historical"))
        entry["attention"] = (
            (entry["concept_id"] in attention_ids) if everything
            else entry["bucket"] in ("new", "still", "borderline")
        )
        entry["due"] = entry.get("panel_id") in due_ids
        entry["outside_by_text"] = web._outside_by_text(entry) if entry["attention"] else None


def _whole_record_entries(connection, owner_id: str, web) -> list[dict]:
    """Every result of the whole record, marked the way the everything scope marks them."""
    data = build_changes(connection, owner_id, everything=True)
    if data is None or data["report"] is None:
        return []
    report = data["report"]
    entries = [*report["open"], *(entry for _, found in report["collapsed"] for entry in found)]
    catalog = web._complete_days(connection, owner_id, web._metric_catalog(connection, owner_id))
    panels = web._panel_cards(connection, owner_id, member_limit=6)
    mark(entries, everything=True, catalog=catalog, panels=panels, web=web)
    return entries


def search_view(connection, owner_id: str, q: str, offset: int = 0) -> dict:
    """What a search shows.  Laboratory results come back as the same rows the list prints,
    so a result reads the same whether it was found by browsing or by typing."""
    from . import app as web  # the search helpers live there; imported late to avoid a cycle

    view = web._metrics_view(connection, owner_id, q, offset)
    group = next((found for found in view["groups"] if found["key"] == "metrics"), None)
    if group and (group["rows"] or group["more_rows"]):
        entries = {str(entry["concept_id"]): entry for entry in _whole_record_entries(connection, owner_id, web)}
        replaced = False

        def swap(rows: list) -> list:
            nonlocal replaced
            out = []
            for card in rows:
                entry = entries.get(str(card["id"]))
                replaced = replaced or entry is not None
                out.append(entry if entry is not None else card)
            return out

        group["rows"] = swap(group["rows"])
        if isinstance(group["more_rows"], list):
            group["more_rows"] = swap(group["more_rows"])
        if replaced:
            group["kind"] = "results"
    return view


def chips(counts: dict, *, total: int, changed: int, unverified: int, current: str) -> list[dict]:
    """The quick filters above the list.  A filter that would open nothing is left out, except "all" and the one on screen.

    `unverified` is the number the "Not yet checked" filter lists (the caller counts it by that filter's rule), so the chip and the list agree.
    """
    filters = (
        ("all", t("results.chip_all"), total, "/results", "neutral"),
        ("attention", t("results.chip_attention"), counts["attention"], "/results?show=attention", "attention"),
        ("changed", t("results.chip_changed"), changed, "/results?episode=latest&show=changed", "neutral"),
        ("unverified", t("results.chip_unverified"), unverified, "/results?show=unverified", "due"),
        ("due", t("results.chip_due"), counts["due"], "/results?show=due&group=panel", "due"),
    )
    return [
        {"key": key, "label": label, "count": count, "href": href, "current": key == current, "tone": tone}
        for key, label, count, href, tone in filters
        if count or key in ("all", current)
    ]


def register_results_routes(
    app, settings, *, templates, template_context, require_user, record_user, viewing_row,
):
    @app.get("/results", response_class=HTMLResponse)
    def results_page(
        request: Request,
        q: str = "",
        document: str = "",
        episode: str = "",
        date_from: Annotated[str, Query(alias="from")] = "",
        date_to: Annotated[str, Query(alias="to")] = "",
        sort: str = "",
        show: str = "",
        group: str = "",
        reverse: str = "",
        area: str = "",
        offset: int = 0,
    ):
        """The results list: a search when `q` is typed, otherwise the record or one selection of it."""
        from . import app as web  # the page helpers live there; imported late to avoid a cycle

        user = require_user(request)
        owner = record_user(request, user)
        locale = get_locale()
        q = q.strip()
        if episode == "all":
            episode = ""
        area = area if area in web.AREA_BY_ID else ""
        everything = not (document or episode or date_from or date_to)
        options = view_options(sort, show, group, reverse, everything=everything, area=area)
        with connect(settings) as connection:
            catalog = web._complete_days(connection, owner["id"], web._metric_catalog(connection, owner["id"]))
            counts = web._status_counts(connection, owner["id"])
            latest = build_changes(connection, owner["id"])
            view = data = summary = arranged = page = None
            panels: list[dict] = []
            findings: list[dict] = []
            devices: list[dict] = []
            if q:
                view = search_view(connection, owner["id"], q, offset)
            else:
                data = build_changes(
                    connection, owner["id"], document_id=document or None, episode=episode,
                    date_from=date_from, date_to=date_to, everything=everything,
                )
                if data is None:
                    raise HTTPException(404)
                summary = (
                    load_summary(connection, owner["id"], locale, data["scope"], data["fingerprint"])
                    if data["scope"] else None
                )
                panels = web._panel_cards(connection, owner["id"], member_limit=6)
                if everything and options["show"] == "attention" and not options["area"]:
                    findings = [
                        web._finding_result(row)
                        for row in web._attention_findings(web._finding_catalog(connection, owner["id"]))
                    ]
                if data["report"] is not None:
                    mark(
                        [*data["report"]["open"], *(entry for _, found in data["report"]["collapsed"] for entry in found)],
                        everything=everything, catalog=catalog, panels=panels, web=web,
                    )
                    arranged = arrange(
                        data["report"], options,
                        areas=[(str(a["id"]), str(a["name"])) for a in web.localized_health_areas()],
                    )
                if arranged and everything and options["group"] == "none" and arranged["sections"]:
                    section = arranged["sections"][0]
                    total = len(section["entries"])
                    base = "/results?" + urlencode([
                        *([("area", area)] if area else []),
                        ("group", "none"),
                        *[(name, value) for name, value in (("sort", options["sort"]), ("show", options["show"]))
                          if value not in ("status", "all")],
                        *([("reverse", "1")] if options["reverse"] else []),
                    ])
                    page = web._pagination(total, offset, web.PAGE_SIZE, base)
                    section["entries"] = section["entries"][page["offset"]: page["offset"] + web.PAGE_SIZE]
                    if total <= web.PAGE_SIZE:
                        page = None
                if everything:
                    devices = [card for card in catalog if card["is_device"]]
                    if area:
                        devices = [card for card in devices if area in card["area_ids"]]
                    if options["show"] == "attention":
                        attention_ids = _attention_ids(web, catalog)
                        devices = [card for card in devices if str(card["id"]) in attention_ids]
                    elif options["show"] != "all":
                        devices = []
        if q:
            current = ""
        elif data["selection"]["kind"] == "latest" and options["show"] == "changed":
            current = "changed"
        elif everything and not area and options["show"] in ("all", "attention", "unverified", "due"):
            current = options["show"]
        else:
            current = ""
        latest_report = latest["report"] if latest else None
        changed = latest_report["counts"]["new"] + latest_report["counts"]["resolved"] if latest_report else 0
        record_total = sum(1 for card in catalog if not card["is_device"])
        unverified = sum(
            1 for card in catalog
            if not card["is_device"] and str(card.get("verification_status") or "extracted") not in ("verified", "corrected")
        )
        selection_pairs = [
            (name, request.query_params[name])
            for name in ("document", "episode", "from", "to")
            if request.query_params.get(name) and request.query_params[name] != "all"
        ]
        error = request.query_params.get("ai_error")
        return templates.TemplateResponse(
            request,
            "results.html",
            template_context(
                request,
                active="results",
                q=q,
                chips=chips(counts, total=record_total, changed=changed, unverified=unverified, current=current),
                view=view,
                data=data,
                arranged=arranged,
                view_query=view_query(options),
                selection_pairs=selection_pairs,
                reset_url="/results" + (("?" + urlencode(selection_pairs)) if selection_pairs else ""),
                view_sorts=SORTS,
                view_shows=SHOWS,
                view_groups=GROUPS,
                buckets=BUCKETS,
                episode_gap_days=EPISODE_GAP_DAYS,
                area=(
                    {"id": area, "name": web.translate_phrase(str(web.AREA_BY_ID[area]["name"])), "url": f"/areas/{area}"}
                    if area else None
                ),
                findings=findings,
                devices=devices,
                page=page,
                summary=summary,
                summary_findings=attach_notes(data, summary) if data else [],
                ai_can_ask=_can_ask(settings, request, user, data, viewing_row) if data else False,
                ai_error=error if error in AI_ERRORS else None,
                document_filter=document,
            ),
        )
