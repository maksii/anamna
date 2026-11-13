"""Panel, dashboard and card-shape contract for the web layer.

The fixture builds a miniature record - one abnormal lipid, one normal lipid,
one paediatric-only reference, one same-day duplicate - because every defect
these tests guard against was a wrong *shape*, not a wrong query.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from anamna.config import Settings
from anamna.i18n import activate_locale, reset_locale, t
from anamna.db import connect, migrate, utc_now
from anamna.ingest.pipeline import ensure_concept, ensure_vendor, seed_concepts
from anamna.panels import PANEL_BY_ID
from anamna.security import create_session, create_user
from anamna.web import app as web
from anamna.web.app import create_app


PASSWORD = "a-long-local-password"


def settings_for(tmp_path: Path) -> Settings:
    sources = tmp_path / "sources"
    sources.mkdir(exist_ok=True)
    return Settings(
        database_path=tmp_path / "health.sqlite3",
        source_dir=sources,
        secret_key="panel-test-secret",
        session_days=1,
    )


OBSERVATIONS = [
    # name, numeric, text, unit, date, vendor range text, vendor low/high, vendor reading
    ("LDL cholesterol", 4.42, None, "mmol/L", "2025-02-13", "0 - 3.0", 0.0, 3.0, "high"),
    ("HDL cholesterol", 1.42, None, "mmol/L", "2025-02-13", "1.0 - 2.2", 1.0, 2.2, "within_vendor_range"),
    ("Creatinine", 88.0, None, "µmol/L", "2025-02-13", "62 - 106", 62.0, 106.0, "within_vendor_range"),
    ("Hemoglobin", 150.0, None, "g/L", "2025-02-13", "Діти: <1 року: 100.0-140.0", None, None, None),
    ("Folate, serum", 3.06, None, "ng/mL", "2025-02-13", "Дорослі (20-65 років): 3.89 - 26.8", None, None, None),
    # Same draw printed twice on different pages with different rounding.
    ("25-hydroxyvitamin D", 27.4, None, "ng/mL", "2025-08-28", None, None, None, None),
    ("25-hydroxyvitamin D", 30.2, None, "ng/mL", "2025-08-28", None, None, None, None),
    ("Blood group", None, "А(ІІ)", None, "2025-02-13", None, None, None, None),
]


def build(tmp_path: Path) -> tuple[Settings, str, TestClient]:
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "panels@example.test", "Panels", PASSWORD)
    patient_id = f"patient-{user_id}"
    with connect(settings) as connection:
        seed_concepts(connection)
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Test Patient', '1990-03-14', 'male', ?)""",
            (patient_id, user_id, utc_now()),
        )
        vendor_id = ensure_vendor(connection, "Test Lab", None)
        source = settings.source_dir / "report.pdf"
        source.write_text("report", encoding="utf-8")
        connection.execute(
            """INSERT INTO documents(
                   id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type,
                   extraction_strategy, classification_confidence, report_date, imported_at, status
               ) VALUES ('doc-1', ?, ?, ?, 'report.pdf', ?, 'application/pdf', 10, 'sha-1', 5,
                         '2025-02-13__test-lab__laboratory__result-1', 'laboratory', 'native_text', 1,
                         '2025-02-13', ?, 'final')""",
            (user_id, patient_id, vendor_id, str(source), utc_now()),
        )
        connection.execute(
            "INSERT INTO search_index(document_id, owner_user_id, content) VALUES ('doc-1', ?, 'lipids')",
            (user_id,),
        )
        connection.execute(
            """INSERT INTO review_tasks(id, owner_user_id, entity_type, entity_id, reason, state, created_at)
               VALUES ('task-1', ?, 'document', 'doc-1',
                       'Verify 8 extracted observation(s) against page evidence before marking trusted',
                       'open', ?)""",
            (user_id, utc_now()),
        )
        for index, (name, numeric, text, unit, observed, reference, low, high, reading) in enumerate(
            OBSERVATIONS
        ):
            concept_id, _ = ensure_concept(connection, name, vendor_id)
            connection.execute(
                """INSERT INTO observations(
                       id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
                       value_type, value_numeric, value_text, unit_raw, observed_at,
                       vendor_reference_text, vendor_reference_low, vendor_reference_high,
                       vendor_interpretation, verification_status, extraction_method, confidence,
                       evidence_text, parser_version, created_at)
                   VALUES (?, ?, ?, 'doc-1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'extracted', 'test',
                           ?, ?, 'test', ?)""",
                (
                    f"obs-{index}", user_id, patient_id, index + 1, concept_id, name,
                    "numeric" if numeric is not None else "text", numeric, text, unit, observed,
                    reference, low, high, reading, 0.9 - index * 0.01, f"{name} evidence", utc_now(),
                ),
            )
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "en")
    return settings, user_id, client


def catalog_for(settings: Settings, user_id: str):
    web.invalidate_catalog()
    with connect(settings) as connection:
        return {card["id"]: card for card in web._metric_catalog(connection, user_id)}


def test_metric_card_carries_everything_a_template_needs(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    cards = catalog_for(settings, user_id)
    ldl = cards["ldl-cholesterol"]
    for field in (
        "id", "url", "name", "unit", "value_text", "value_numeric", "category_label",
        "area_id", "area_name", "panel_id", "panel_name", "latest_date", "date_text",
        "vendor", "count", "evidence_count", "is_device", "verdict", "trend",
        "staleness", "verification_status", "verification_label",
    ):
        assert field in ldl, field
    # Pre-formatted, never a raw float or an ISO date.
    assert ldl["value_text"] == "4.42"
    assert ldl["date_text"] == "13 Feb 2025"
    assert ldl["panel_id"] == "lipids"
    assert ldl["verdict"]["interpretation"] == "high"
    assert ldl["staleness"]["state"] in {"fresh", "due_soon", "overdue", "no_interval"}


def test_attention_is_derived_from_verdicts_not_a_hard_coded_list(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    cards = catalog_for(settings, user_id)
    attention = web._attention_cards(list(cards.values()))
    names = [card["id"] for card in attention]
    assert "ldl-cholesterol" in names
    assert "hdl-cholesterol" not in names
    assert "creatinine" not in names
    # Folate 3.06 ng/mL must reach the attention list on its own merits. It
    # once did so only as a lab-versus-library conflict; now WHO's "possible
    # deficiency" band says the same thing the laboratory did, so it is simply
    # an abnormal result.
    folate = cards["folate-serum"]
    assert folate["verdict"]["interpretation"] not in {"normal", "optimal", "negative"}
    assert "folate-serum" in names
    # Two bodies call 3.06 "possible deficiency" and "below functional
    # adequacy"; the most severe containing band leads (reference._band_rank),
    # so folate ranks as an out-of-interval result alongside LDL, never after
    # a borderline one.
    assert web._attention_rank(cards["ldl-cholesterol"]) <= web._attention_rank(folate) <= 1


def test_paediatric_reference_never_becomes_the_adult_patients_range(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    hemoglobin = catalog_for(settings, user_id)["hemoglobin"]
    verdict = hemoglobin["verdict"]
    assert verdict["authority"] != "vendor" or (verdict["low"], verdict["high"]) != (100.0, 140.0)


def test_same_day_duplicates_are_one_result_not_a_two_point_trend(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    vitamin_d = catalog_for(settings, user_id)["25-hydroxyvitamin-d"]
    assert vitamin_d["count"] == 1
    assert vitamin_d["same_day_count"] == 2
    assert len(vitamin_d["series"]) == 1
    assert vitamin_d["trend"] is None


def test_cyrillic_spelled_code_is_folded_in_english(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    # One spelling for every lab's «А(ІІ)» / «А (II)» (DOCC-38).
    assert catalog_for(settings, user_id)["blood-group"]["value_text"] == "A (II)"


def test_panel_card_reports_presence_and_gaps(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    web.invalidate_catalog()
    with connect(settings) as connection:
        panels = {panel["id"]: panel for panel in web._panel_cards(connection, user_id)}
    lipids = panels["lipids"]
    # The fixture supplies exactly these two; everything else the panel names
    # is a gap the card has to report.  Both expectations are derived from the
    # panel definition rather than typed out: the panel gains members whenever
    # the reference library learns to judge more of what a lipid report prints,
    # and a literal count here turns each such addition into a false failure
    # about presence reporting, which is what this test is actually for.
    supplied = {"ldl-cholesterol", "hdl-cholesterol"}
    assert lipids["present_count"] == len(supplied)
    assert lipids["member_count"] == len(PANEL_BY_ID["lipids"].members)
    assert lipids["status"] == "attention"
    assert {item["id"] for item in lipids["missing_members"]} == (
        set(PANEL_BY_ID["lipids"].members) - supplied
    )
    assert panels["thyroid"]["status"] == "absent"
    assert panels["thyroid"]["present_count"] == 0


def test_out_of_range_and_conflicted_are_two_counts_not_one(tmp_path: Path):
    """A member can be above the interval *and* disputed; that is one member.

    Adding the conflict tally into flagged_count made a two-analyte panel
    report "Outside the interval: 2" directly beneath a member the same card
    labelled "Within range".
    """
    settings, _, _ = build(tmp_path)

    def member(interpretation: str, conflict: bool) -> dict[str, object]:
        return {
            "latest_date": "2025-02-13",
            "verdict": {"interpretation": interpretation, "conflicts_with_vendor": conflict},
        }

    with connect(settings) as connection:
        card = web._panel_card(
            connection,
            PANEL_BY_ID["lipids"],
            {"ldl-cholesterol": member("high", True), "hdl-cholesterol": member("normal", False)},
            {},
        )
        # Conflict alone still demotes an otherwise clean panel - only the
        # counts changed, not the status.
        quiet = web._panel_card(
            connection,
            PANEL_BY_ID["lipids"],
            {"ldl-cholesterol": member("normal", True), "hdl-cholesterol": member("normal", False)},
            {},
        )
    assert card["flagged_count"] == 1
    assert card["conflict_count"] == 1
    assert card["status"] == "attention"
    assert (quiet["flagged_count"], quiet["conflict_count"]) == (0, 1)
    assert quiet["status"] == "borderline"


def test_panel_and_area_routes_404_on_unknown_ids(tmp_path: Path):
    _, _, client = build(tmp_path)
    assert client.get("/panels/not-a-panel").status_code == 404
    assert client.get("/api/panels/not-a-panel").status_code == 404
    assert client.get("/areas/not-an-area").status_code == 404
    assert client.get("/metrics/not-a-concept").status_code == 404
    assert client.get("/devices/metrics/not-a-metric").status_code == 404


def test_every_route_requires_a_session(tmp_path: Path):
    settings, _, _ = build(tmp_path)
    anonymous = TestClient(create_app(settings))
    # /insights is a permanent redirect to /results now, which is guarded below.
    assert anonymous.get("/insights", follow_redirects=False).headers["location"] == "/results?show=attention"
    # The retired list addresses answer with a redirect first; the redirect
    # target is what has to be guarded, so the target is what is listed.
    for route in ("/", "/results", "/results?group=panel", "/panels/lipids", "/documents", "/review"):
        response = anonymous.get(route, follow_redirects=False)
        assert response.status_code == 303, route
        assert response.headers["location"].startswith("/login")
    assert anonymous.get("/api/panels/lipids").status_code == 401
    assert anonymous.get("/api/metrics/search").status_code == 401


def test_panel_json_matches_the_page(tmp_path: Path):
    _, _, client = build(tmp_path)
    payload = client.get("/api/panels/lipids").json()
    assert payload["panel"]["id"] == "lipids"
    assert payload["renderer"] == "standard"
    assert [row["id"] for row in payload["rows"]] == ["ldl-cholesterol", "hdl-cholesterol"]


def test_live_search_returns_the_cards_the_page_renders(tmp_path: Path):
    """The type-ahead may not restate a verdict in its own words.

    Live search used to rebuild these cards in JavaScript from JSON. It filled
    the slots someone had remembered and left the rest showing the blank seed
    card's text, so an out-of-range ferritin came back with the chip "Above
    range" printed over the sentence "Your result is inside this range", a
    legend reading "Shaded band = 28 Aug 2025", and a chip trailing a bare
    " · " where the conflict suffix belonged. The search told the reader an
    out-of-range result was normal.

    One renderer serves both branches now, so the guard is byte equality with
    the page - any slot a second renderer forgot would show up as a diff -
    plus the three specific lies that bug told.
    """
    _, _, client = build(tmp_path)
    # The pages come back in the request's locale (English); pin the contextvar
    # so `t()` here cannot be left speaking Ukrainian by an earlier test.
    token = activate_locale("en")
    try:
        # The type-ahead's result region is, byte for byte, the region the page
        # load renders -- for a query, a status filter and the default list.
        # The type-ahead answers a typed search only: with the box empty the
        # page keeps the list it drew, and the status filters are page
        # addresses, not search parameters.
        for query in ("q=cholesterol",):
            page = client.get(f"/results?{query}").text
            payload = client.get(f"/api/metrics/search?{query}").json()
            assert payload["html"].strip(), query
            assert payload["html"] in page, f"the live region differs from the page for {query}"
        rows = client.get("/api/metrics/search?q=LDL").json()["html"]
        ldl_row = next(
            chunk.split("</li>", 1)[0]
            for chunk in rows.split('<li class="an-res"')[1:]
            if 'href="/metrics/ldl-cholesterol"' in chunk
        )
        assert 'data-interpretation="high"' in ldl_row
        assert t("verdict.you_are_within") not in ldl_row

        # The full metric card (range bar, chip) lives on the area pages now.
        page = client.get("/areas/heart").text
        cards = re.findall(r'<article class="result-card an-metric-card".*?</article>', page, re.S)
        assert cards, "the area page rendered no metric cards"
        assert 'data-section="panel-' in client.get("/results?group=panel").text, (
            "the test-group view rendered no sections"
        )

        high = next((c for c in cards if 'data-out-of-range="high"' in c), None)
        assert high, "fixture no longer produces an out-of-range card to guard"

        # a) The sentence agrees with the chip rather than with the seed card.
        #    Cards no longer print the sentence — it lives in the bar's
        #    accessible name (and, spelled out, in the detail page's collapsed
        #    verdict details) — so the accessible name is what must agree.
        reading = re.search(r'class="an-range-bar"[^>]*?aria-label="(.*?)"', high, re.S)
        above_key = "verdict.target_above" if 'data-distinct-target="true"' in high else "verdict.you_are_above"
        assert reading and reading.group(1).startswith(t(above_key))
        assert t("verdict.you_are_within") not in high

        # b) The interval named in the accessible name is the shaded band, not
        #    the sample date.
        date_text = re.search(r'result-meta">\s*<span>(.*?)</span>', high, re.S)
        band_key = "verdict.target_interval" if 'data-distinct-target="true"' in high else "verdict.band_aria"
        assert t(band_key, range="").strip() in reading.group(1)
        assert date_text and date_text.group(1).strip()
        assert date_text.group(1).strip() not in reading.group(1)

        # c) The chip completes its conflict suffix or omits the separator.
        #    Only the card ROOT's data-conflict means a vendor conflict the
        #    chip must name — the collapsed details inside the card also
        #    carries the attribute for an authorities-only disagreement, which
        #    its own summary line names instead.
        for card in cards:
            verdict = re.search(
                r'an-state-slot--verdict.*?an-state-slot__text">(.*?)</span>',
                card,
                re.S,
            )
            assert verdict, "metric card missing verdict slot"
            chip = verdict.group(1).strip()
            assert not chip.endswith("·"), f"dangling separator in verdict {chip!r}"
            if 'data-conflict="true"' in card.split(">", 1)[0]:
                assert t("verdict.conflict") in chip, f"conflict not named in verdict {chip!r}"
    finally:
        reset_locale(token)


def test_range_bar_accessible_name_never_contradicts_the_verdict(tmp_path: Path):
    """A screen reader must hear the verdict the card prints.

    The bar's aria-label opened with a fixed "Position inside the reference
    interval" and appended the real verdict at the end, so an out-of-range
    result announced itself as inside the interval - the visible bug's fix had
    left the accessible name still saying it.
    """
    _, _, client = build(tmp_path)
    token = activate_locale("en")
    try:
        page = client.get("/areas/heart").text
        seen = 0
        for card in re.findall(r'<article class="result-card an-metric-card".*?</article>', page, re.S):
            label = re.search(r'class="an-range-bar"[^>]*?aria-label="(.*?)"', card, re.S)
            if not label:
                continue
            seen += 1
            prefix = "verdict.target_" if 'data-distinct-target="true"' in card else "verdict.you_are_"
            spoken, expected = label.group(1), (
                t(prefix + "above")
                if 'data-out-of-range="high"' in card
                else t(prefix + "below")
                if 'data-out-of-range="low"' in card
                else t(prefix + "within")
            )
            assert spoken.startswith(expected), f"aria-label {spoken!r} contradicts the card"
        assert seen, "no card carried a range bar to check"
    finally:
        reset_locale(token)


def test_locale_form_is_csrf_protected(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        csrf = connection.execute(
            "SELECT csrf_token FROM sessions WHERE user_id=?", (user_id,)
        ).fetchone()[0]
    forged = client.post("/locale", data={"lang": "uk", "next": "/"}, follow_redirects=False)
    assert forged.status_code == 303
    assert "anamna_lang" not in forged.cookies
    accepted = client.post(
        "/locale", data={"lang": "uk", "next": "/", "csrf_token": csrf}, follow_redirects=False
    )
    assert accepted.cookies["anamna_lang"] == "uk"


# One measurement reaching a panel by two paths (a parsed Garmin PDF and the
# cuff's daily values) is one card now, built from both by the twin map, not
# two cards with the older one hidden by display name: see
# test_linked_metrics.py::test_panel_lists_a_twin_once_and_counts_it_once.


def test_panel_json_does_not_mutate_the_catalog_memo(tmp_path: Path):
    """GET /api/panels/{id} used to pop search_text off the memoised cards,
    500ing every later search until restart."""
    _, _, client = build(tmp_path)
    payload = client.get("/api/panels/lipids").json()
    for row in payload["rows"]:
        assert "search_text" not in row
    for member in payload["panel"]["members"]:
        assert "search_text" not in member
    assert client.get("/results?q=cholesterol").status_code == 200
    assert client.get("/api/metrics/search?q=cholesterol").status_code == 200


def test_panel_json_carries_the_blocks_the_page_renders(tmp_path: Path):
    _, _, client = build(tmp_path)
    payload = client.get("/api/panels/lipids").json()
    assert isinstance(payload["documents"], list)
    assert payload["documents"], "the lipid observations came from doc-1"
    assert payload["allergy"] is None
    assert payload["blood_pressure"] is None
    bp = client.get("/api/panels/blood_pressure").json()
    assert bp["renderer"] == "blood_pressure"
    assert bp["blood_pressure"]["has_reading"] is False


def test_chart_band_shades_the_target_not_the_matched_tier():
    verdict = {
        "low": 4.9,
        "high": None,
        "band_label": "Severe hypercholesterolaemia",
        "range_text": "≥ 4.9 mmol/L",
        "target_low": None,
        "target_high": 1.4,
        "target_range_text": "< 1.4 mmol/L",
        "target_is_matched_band": False,
    }
    band = web._chart_band(verdict)
    assert (band["low"], band["high"]) == (None, 1.4)
    assert band["label"] == "< 1.4 mmol/L"
    # A verdict without target fields (a hand-built or legacy one) still bands.
    assert web._chart_band({"low": 1.0, "high": 2.0, "band_label": "Normal"}) == {
        "low": 1.0,
        "high": 2.0,
        "label": "Normal",
    }
    assert web._chart_band({"low": None, "high": None}) is None


def test_sparkline_shades_the_target_band_not_the_matched_tier():
    card = {
        "series": [{"date": "2025-01-01", "value": 5.0}, {"date": "2025-02-01", "value": 5.5}],
        "verdict": {"low": 4.9, "high": None, "target_low": 1.0, "target_high": 1.4},
    }
    spark = web._sparkline(card, None)
    # The target 1.0-1.4 lies far below a 5.0-5.5 series: the axis follows the
    # readings, so the band is off the plot and not drawn, and the series uses
    # the height instead of being squashed into its top sixth.
    assert spark["band"] is None
    ys = [point["y"] for point in spark["points"]]
    assert max(ys) - min(ys) > 20
    near = web._sparkline({**card, "verdict": {"low": 4.9, "high": None, "target_low": 4.9, "target_high": 5.2}}, None)
    # A near band is drawn, clipped to the plot.
    assert near["band"] and 0.0 <= near["band"]["start"] < near["band"]["end"] <= 30.0


def test_an_overdue_member_cannot_hide_behind_a_fresher_sibling(tmp_path: Path):
    settings, _, _ = build(tmp_path)

    def member(latest: str, state: str) -> dict[str, object]:
        return {
            "latest_date": latest,
            "verdict": {"interpretation": "normal"},
            "staleness": {"state": state, "days_ago": 400, "label": ""},
        }

    with connect(settings) as connection:
        card = web._panel_card(
            connection,
            PANEL_BY_ID["lipids"],
            {
                "ldl-cholesterol": member("2020-01-01", "overdue"),
                "hdl-cholesterol": member(date.today().isoformat(), "fresh"),
            },
            {},
        )
    assert card["staleness"]["state"] == "overdue"
    # days_ago stays the panel's own latest date, so sorting is unchanged.
    assert card["staleness"]["days_ago"] == 0


def test_missing_device_members_are_named_like_missing_analytes(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    token = activate_locale("en")
    try:
        web.invalidate_catalog()
        with connect(settings) as connection:
            panels = {panel["id"]: panel for panel in web._panel_cards(connection, user_id)}
        recovery = panels["recovery"]
        missing = {item["id"]: item["name"] for item in recovery["missing_members"]}
        assert "device:readiness_score" in missing
        assert missing["device:readiness_score"] == "Readiness score"
        assert missing["device:stress_level"] == "Average stress level"
        # Coverage arithmetic: what is absent plus what is present is the count
        # the card claims, for device panels exactly as for lab panels.
        assert len(missing) + recovery["present_count"] == recovery["member_count"]
    finally:
        reset_locale(token)


def seed_device_days(settings: Settings, user_id: str, metrics: list[tuple[str, str]]) -> None:
    with connect(settings) as connection:
        patient_id = connection.execute(
            "SELECT id FROM patients WHERE owner_user_id=?", (user_id,)
        ).fetchone()[0]
        vendor_id = ensure_vendor(connection, "Apple", None)
        connection.execute(
            """INSERT INTO device_imports(id, owner_user_id, patient_id, vendor_id, adapter_key,
                   source_path, source_fingerprint, source_bytes, imported_at)
               VALUES ('imp-1', ?, ?, ?, 'apple_health', 'export.zip', 'fp-1', 10, ?)""",
            (user_id, patient_id, vendor_id, utc_now()),
        )
        for index, (key, name) in enumerate(metrics):
            connection.execute(
                """INSERT INTO device_metric_days(id, owner_user_id, patient_id, import_id,
                       source_name, source_vendor, metric_key, metric_name, category, day,
                       aggregation, unit, value, sample_count, created_at)
                   VALUES (?, ?, ?, 'imp-1', 'Apple Watch', 'Apple', ?, ?, 'device_activity',
                           '2025-08-01', 'average', 'count', 1.0, 1, ?)""",
                (f"dmd-{index}", user_id, patient_id, key, name, utc_now()),
            )
    web.invalidate_catalog()


def test_device_metric_group_is_never_truncated(tmp_path: Path):
    """40 of 57 device metrics with no pagination left 17 reachable only by
    guessing their names; the device group renders whole."""
    settings, user_id, client = build(tmp_path)
    seed_device_days(
        settings,
        user_id,
        [(f"test_metric_{index:02d}", f"Test metric {index:02d}") for index in range(45)],
    )
    page = client.get("/results").text
    links = {match for match in re.findall(r'href="(/devices/metrics/[^"]+)"', page)}
    assert len(links) >= 45


def test_outside_by_text_names_the_distance_to_the_target_bound():
    token = activate_locale("en")
    try:
        outside = web._outside_by_text(
            {
                "value_numeric": 5.54,
                "unit": "mmol/L",
                "verdict": {"low": 4.9, "high": None, "target_low": None, "target_high": 1.4},
            }
        )
        assert outside is not None
        assert re.fullmatch(r"4[.,]14? mmol/L", outside)
        # Inside the interval, or textual, there is nothing to say.
        assert web._outside_by_text(
            {"value_numeric": 1.2, "unit": "mmol/L", "verdict": {"target_low": 1.0, "target_high": 1.4}}
        ) is None
        assert web._outside_by_text({"value_numeric": None, "verdict": {}}) is None
    finally:
        reset_locale(token)


def test_attention_filter_names_how_far_outside_the_interval(tmp_path: Path):
    _, _, client = build(tmp_path)
    token = activate_locale("en")
    try:
        page = client.get("/results?show=attention").text
        # LDL 4.42 with no cardiovascular risk category on record is judged by
        # the population cut-point (EAS/EFLM < 3.0 -- CLIN-01: risk-tier goals
        # never judge without a category), so it sits 1.42 mmol/L outside and
        # the row says so in words.
        assert t("insights.outside_by", amount="1.42 mmol/L") in page
    finally:
        reset_locale(token)


def test_an_unconvertible_reading_keeps_its_printed_unit(tmp_path: Path):
    """The concept prefers mg/dL; a µmol/L reading with no registered
    conversion must never be re-labelled `mg/dL`, on the page or the axis."""
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        vendor_id = ensure_vendor(connection, "Test Lab", None)
        concept_id, _ = ensure_concept(connection, "Urobilinogen", vendor_id)
        connection.execute(
            "UPDATE concepts SET preferred_unit='mg/dL' WHERE id=?", (concept_id,)
        )
        patient_id = connection.execute(
            "SELECT id FROM patients WHERE owner_user_id=?", (user_id,)
        ).fetchone()[0]
        for obs_id, value, unit, day in (
            ("obs-uro-1", 0.5, "mg/dL", "2022-08-24"),
            ("obs-uro-2", 35.0, "мкмоль/л", "2025-09-16"),
        ):
            connection.execute(
                """INSERT INTO observations(
                       id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
                       value_type, value_numeric, unit_raw, observed_at, verification_status,
                       extraction_method, confidence, evidence_text, parser_version, created_at)
                   VALUES (?, ?, ?, 'doc-1', 1, ?, 'Urobilinogen', 'numeric', ?, ?, ?,
                           'extracted', 'test', 0.9, 'Urobilinogen evidence', 'test', ?)""",
                (obs_id, user_id, patient_id, concept_id, value, unit, day, utc_now()),
            )
    web.invalidate_catalog()
    points = client.get(f"/api/metrics/{concept_id}").json()
    # One axis, one unit: the newest reading's own unit carries the series and
    # the unconvertible sibling stays off it instead of being re-labelled.
    assert [point["value"] for point in points] == [35.0]
    assert "mg" not in points[0]["unit"]
    page = client.get(f"/metrics/{concept_id}").text
    assert "35 <small>mg/dL</small>" not in page
    assert re.search(r"0[.,]5 <small>mg/dL</small>", page)


def test_long_pages_fold_reference_blocks_and_drop_labels_that_repeat(tmp_path: Path):
    """The phone sweep measured /panels/cbc at 23,400px and a 53-value lab
    document at 28,700px. Secondary blocks fold; a label that only repeats the
    heading above it is not printed; the primary action is a verb."""
    settings, user_id, client = build(tmp_path)
    panel_name = client.get("/api/panels/lipids").json()["panel"]["name"]
    page = client.get("/panels/lipids").text
    assert '<details class="panel an-page-disclosure an-panel-sources">' in page
    assert '<details class="panel an-page-disclosure an-panel-guidance">' in page
    rows = page.split('class="an-panel-member-rows"', 1)[1].split("</section>", 1)[0]
    assert rows.count("an-panel-member-row__name") == 2
    # The panel's own name under each of its rows, on its own page, said nothing.
    assert f"<small>{panel_name}</small>" not in rows
    # A document row prints the source label only when it differs from the name.
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET raw_name='ЛПНЩ (LDL)' WHERE id='obs-0'")
    document = client.get("/documents/doc-1").text
    assert document.count("Original source label") == 1
    assert "ЛПНЩ (LDL)" in document
    for locale, verb in (("en", "Add files"), ("uk", "Додати файли")):
        client.cookies.set("anamna_lang", locale)
        assert f'<a class="primary" href="/upload">{verb}</a>' in client.get("/documents").text
    client.cookies.set("anamna_lang", "en")
