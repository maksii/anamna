"""/changes: every result date set beside the previous result of the same test.

The fixture adds a second report to the panel fixture, with analytes chosen so
each bucket is reached through the real verdict engine (vendor intervals only,
so the expectation does not depend on the curated library).  The AI short
state is exercised with ``anamna.ai.complete`` stubbed; no provider is
ever called.
"""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from anamna import ai, i18n
from anamna.db import connect, utc_now
from anamna.ingest.pipeline import ensure_concept, ensure_vendor
from anamna.security import create_access_token
from anamna.web import changes
from anamna.web.app import create_app

from test_web_panels import build
from test_web_issue_reports import csrf_for

# name, earlier (doc-1, 2025-02-13), later (doc-2, 2025-09-01); value, unit, low, high
SERIES = [
    ("Zeta marker", (3.0, "mmol/L", 1, 5), (7.0, "mmol/L", 1, 5)),      # new problem
    ("Eta marker", (7.0, "mmol/L", 1, 5), (3.0, "mmol/L", 1, 5)),       # resolved
    ("Theta marker", (6.0, "mmol/L", 1, 5), (8.0, "mmol/L", 1, 5)),     # still, worsening
    ("Iota marker", (9.0, "mmol/L", 1, 5), (6.0, "mmol/L", 1, 5)),      # still, improving
    ("Kappa marker", (3.0, "mmol/L", 1, 5), (3.5, "mmol/L", 1, 5)),     # stable, +0.5 (+17%)
    ("Lambda marker", None, (2.0, "mmol/L", 1, 5)),                     # first measurement
    ("Omicron marker", None, (9.0, "mmol/L", 1, 5)),                    # first, but outside: new
    ("Mu marker", None, (4.0, "mmol/L", None, None)),                   # not judged
    ("Nu marker", (3.0, "mmol/L", 1, 5), (60.0, "mg/dL", 20, 100)),     # stable, units differ
]


def _observation(connection, user_id, document_id, index, concept_id, name, reading, observed, status="extracted"):
    value, unit, low, high = reading
    connection.execute(
        """INSERT INTO observations(
               id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
               value_type, value_numeric, unit_raw, observed_at,
               vendor_reference_text, vendor_reference_low, vendor_reference_high,
               verification_status, extraction_method, confidence, evidence_text, parser_version, created_at)
           VALUES (?, ?, ?, ?, 1, ?, ?, 'numeric', ?, ?, ?, ?, ?, ?, ?, 'test', 0.9, ?, 'test', ?)""",
        (
            f"chg-{document_id}-{index}", user_id, f"patient-{user_id}", document_id, concept_id, name,
            value, unit, observed, f"{low} - {high}" if low is not None else None, low, high,
            status, f"{name} evidence", utc_now(),
        ),
    )


def build_changes_fixture(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        vendor_id = ensure_vendor(connection, "Test Lab", None)
        source = settings.source_dir / "report-2.pdf"
        source.write_text("report", encoding="utf-8")
        connection.execute(
            """INSERT INTO documents(
                   id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type,
                   extraction_strategy, classification_confidence, report_date, imported_at, status
               ) VALUES ('doc-2', ?, ?, ?, 'report-2.pdf', ?, 'application/pdf', 10, 'sha-2', 1,
                         'Follow-up panel', 'laboratory', 'native_text', 1, '2025-09-01', ?, 'final')""",
            (user_id, f"patient-{user_id}", vendor_id, str(source), utc_now()),
        )
        ids = {}
        for index, (name, earlier, later) in enumerate(SERIES):
            concept_id, _ = ensure_concept(connection, name, vendor_id)
            ids[name] = concept_id
            if earlier:
                _observation(connection, user_id, "doc-1", 100 + index, concept_id, name, earlier, "2025-02-13")
            _observation(connection, user_id, "doc-2", index, concept_id, name, later, "2025-09-01")
        # A row a reviewer set aside never reaches the page.
        xi, _ = ensure_concept(connection, "Xi marker", vendor_id)
        ids["Xi marker"] = xi
        _observation(connection, user_id, "doc-2", 99, xi, "Xi marker", (50.0, "mmol/L", 1, 5), "2025-09-01", "rejected")
    return settings, user_id, client, ids


def view_for(settings, user_id, **kwargs):
    with connect(settings) as connection:
        return changes.build_changes(connection, user_id, **kwargs)


def by_name(group):
    entries = list(group["open"]) + [e for _, items in group["collapsed"] for e in items]
    return {entry["name"]: entry for entry in entries}


def test_classification_rules_without_a_database():
    out = {"interpretation": "high", "target_low": 1, "target_high": 5}
    inside = {"interpretation": "normal"}
    edge = {"interpretation": "borderline_high"}
    none = {"interpretation": "unjudged"}
    assert changes.classify(out, inside) == "new"
    assert changes.classify(out, none) == "new"
    assert changes.classify(out, None) == "new"
    assert changes.classify(inside, out) == "resolved"
    assert changes.classify(inside, edge) == "resolved"
    assert changes.classify(out, out) == "still"
    assert changes.classify(edge, inside) == "borderline"
    assert changes.classify(inside, inside) == "stable"
    assert changes.classify(inside, None) == "first"
    assert changes.classify(none, out) == "unjudged"
    assert changes.direction(6.0, 8.0, out) == "better"
    assert changes.direction(8.0, 6.0, out) == "worse"
    assert changes.direction(8.0, 8.05, out) == "same"
    # Crossing from below to above is judged by the distance now outside.
    assert changes.direction(5.5, 0.0, out) == "better"
    assert changes.direction(8.0, 6.0, {"interpretation": "high"}) is None


def test_every_bucket_is_reached_through_the_real_verdict(tmp_path: Path):
    settings, user_id, _, _ = build_changes_fixture(tmp_path)
    view = view_for(settings, user_id)
    latest = view["groups"][0]
    # The fixture's 2025-08-28 vitamin D is four days before: one episode.
    assert latest["date"] == "2025-08-28..2025-09-01"
    assert view["report"] is latest and len(view["groups"]) == 1
    entries = by_name(latest)
    assert entries["Zeta marker"]["bucket"] == "new"
    assert entries["Omicron marker"]["bucket"] == "new"
    assert entries["Eta marker"]["bucket"] == "resolved"
    assert (entries["Theta marker"]["bucket"], entries["Theta marker"]["direction"]) == ("still", "worse")
    assert (entries["Iota marker"]["bucket"], entries["Iota marker"]["direction"]) == ("still", "better")
    assert entries["Kappa marker"]["bucket"] == "stable"
    assert entries["Lambda marker"]["bucket"] == "first"
    assert entries["Mu marker"]["bucket"] == "unjudged"
    assert entries["Iota marker"]["label"] == "Still outside · improving"
    # The open list leads with what changed for the worse; stable collapses.
    assert [e["bucket"] for e in latest["open"]][:2] == ["new", "new"]
    assert "Kappa marker" not in {e["name"] for e in latest["open"]}
    assert latest["counts"]["new"] == 2 and latest["counts"]["still"] == 2
    kappa = entries["Kappa marker"]
    assert kappa["change"]["text"] == "+0.5 mmol/L (+17%)"
    assert kappa["previous"]["date_text"] == "13 Feb 2025"
    assert kappa["url"] == f"/metrics/{kappa['concept_id']}"
    assert kappa["source_url"].startswith("/documents/doc-2#observation-chg-doc-2-")
    assert kappa["unverified"] is True


def test_units_that_do_not_fold_together_are_not_compared(tmp_path: Path):
    settings, user_id, client, _ = build_changes_fixture(tmp_path)
    nu = by_name(view_for(settings, user_id)["groups"][0])["Nu marker"]
    assert nu["change"] == {"comparable": False, "text": "Not comparable: different units"}
    assert nu["direction"] is None
    page = client.get("/changes").text
    assert "Not comparable: different units" in page


def test_rejected_rows_are_not_results(tmp_path: Path):
    settings, user_id, client, _ = build_changes_fixture(tmp_path)
    for group in view_for(settings, user_id)["groups"]:
        assert "Xi marker" not in by_name(group)
    assert "Xi marker" not in client.get("/changes").text


def test_document_filter_shows_exactly_what_one_upload_changed(tmp_path: Path):
    settings, user_id, client, _ = build_changes_fixture(tmp_path)
    view = view_for(settings, user_id, document_id="doc-2")
    assert [group["date"] for group in view["groups"]] == ["2025-09-01"]
    assert view["selection"]["kind"] == "document"
    assert view["scope"] == "document:doc-2"
    # Comparisons still reach back across documents.
    assert by_name(view["groups"][0])["Eta marker"]["previous"]["value_text"] == "7"
    earlier = view_for(settings, user_id, document_id="doc-1")
    # doc-1 carries the panel fixture's 2025-02-13 draw and its 2025-08-28 vitamin D: one report.
    assert [group["date"] for group in earlier["groups"]] == ["2025-02-13..2025-08-28"]
    assert all(e["document_id"] == "doc-1" for g in earlier["groups"] for e in by_name(g).values())
    page = client.get("/changes?document=doc-2")
    assert page.status_code == 200
    assert "What this document changed" in page.text
    assert client.get("/changes?document=nope").status_code == 404
    # The document page offers the link.
    assert 'href="/changes?document=doc-2"' in client.get("/documents/doc-2").text


def test_page_is_reachable_and_renders_both_locales(tmp_path: Path):
    _, _, client, _ = build_changes_fixture(tmp_path)
    home = client.get("/").text
    assert 'href="/changes"' in home
    page = client.get("/changes").text
    for text in ("What changed in your results", "New problem", "What these labels mean", "Stable in range"):
        assert text in page
    assert 'id="changes-ai-form"' not in page  # AI not configured: no button, nothing broken
    client.cookies.set("anamna_lang", "uk")
    uk = client.get("/changes").text
    assert "Нове відхилення" in uk and "Що змінилося у ваших результатах" in uk
    assert "+0,5 ммоль/л (+17 %)" in uk
    assert "changes." not in uk.replace("/changes", "").replace("#changes", "").replace("changes-", "")


def reply(text: str):
    def fake_complete(settings, feature, messages, *, max_tokens=3000, timeout=90, response_format=None):
        fake_complete.calls.append({"feature": feature, "messages": messages, "response_format": response_format})
        return ai.AIResult(content=text, model="stub/model", prompt_tokens=1, completion_tokens=1)

    fake_complete.calls = []
    return fake_complete


SUMMARY = json.dumps({
    "state": "Zeta marker is now 7.0 mmol/L, above range. Something rose by 42 units.",
    "findings": [
        {"test": "Theta marker", "level": "moderate", "how_serious": "Theta marker reached 8.0 mmol/L.",
         "what_it_is": "A test of something.", "possible_reasons": ["A recent meal.", "Invented 123.4 value."],
         "usually_next": ["Repeat the test."], "ask": ["Ask about Zeta marker."]},
        {"test": "Not in the data", "level": "urgent", "how_serious": "Made up.", "what_it_is": "",
         "possible_reasons": [], "usually_next": [], "ask": []},
        {"test": "Zeta marker", "level": "catastrophic", "how_serious": "Bad level.", "what_it_is": "",
         "possible_reasons": [], "usually_next": [], "ask": []},
    ],
    "improved": ["Eta marker returned to 3.0 mmol/L."],
})


def test_ai_summary_generates_caches_and_reuses(tmp_path: Path, monkeypatch):
    settings, user_id, client, _ = build_changes_fixture(tmp_path)
    ai.save_ai_settings(settings, {"ai_api_key": "sk-test"})
    stub = reply(SUMMARY)
    monkeypatch.setattr(ai, "complete", stub)
    page = client.get("/changes").text
    assert 'id="changes-ai-form"' in page
    csrf = csrf_for(settings, user_id)
    response = client.post("/changes/ai-summary", data={"csrf_token": csrf}, headers={"Accept": "application/json"})
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "location": "/changes#changes-ai"}
    assert stub.calls[0]["feature"] == "changes_summary"
    assert stub.calls[0]["response_format"]["type"] == "json_schema"
    sent = json.dumps(stub.calls[0]["messages"], ensure_ascii=False)
    assert "Zeta marker" in sent
    assert "Test Patient" not in sent and "1990-03-14" not in sent and user_id not in sent

    page = client.get("/changes").text
    # Badge once text exists; the model id is never printed.
    assert "AI-generated" in page and "stub/model" not in page
    assert "Zeta marker is now 7.0 mmol/L, above range." in page
    # A sentence or item carrying a number the data does not contain is dropped.
    assert "42 units" not in page and "123.4" not in page
    assert "Theta marker reached 8.0 mmol/L." in page
    # Findings name only tests in the data, at a level from the fixed set.
    assert "Made up." not in page and "Bad level." not in page
    assert 'data-level="moderate"' in page and "Questions to ask your doctor" in page
    assert "A recent meal." in page and "What the levels mean" in page
    sent_payload = json.loads(stub.calls[0]["messages"][1]["content"])["results"][0]["changes"]
    zeta = next(change for change in sent_payload if change["test"] == "Zeta marker")
    assert zeta["target_range"] and zeta["beyond_target"]["side"] == "above upper limit"

    again = client.post("/changes/ai-summary", data={"csrf_token": csrf}, headers={"Accept": "application/json"})
    assert again.json()["cached"] is True and len(stub.calls) == 1
    client.post("/changes/ai-summary", data={"csrf_token": csrf, "refresh": "1"}, headers={"Accept": "application/json"})
    assert len(stub.calls) == 2

    # New results make the stored state stale rather than silently current.
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET value_numeric=4.0 WHERE id='chg-doc-2-0'")
    assert "Your results changed after this summary was written" in client.get("/changes").text
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ai_change_summaries").fetchone()[0] == 1


def test_ai_summary_scopes_to_a_document(tmp_path: Path, monkeypatch):
    settings, user_id, client, _ = build_changes_fixture(tmp_path)
    ai.save_ai_settings(settings, {"ai_api_key": "sk-test"})
    monkeypatch.setattr(ai, "complete", reply(SUMMARY))
    response = client.post(
        "/changes/ai-summary", data={"csrf_token": csrf_for(settings, user_id), "document": "doc-2"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/changes?document=doc-2#changes-ai"
    with connect(settings) as connection:
        assert connection.execute("SELECT scope FROM ai_change_summaries").fetchone()[0] == "document:doc-2"


def test_ai_unavailable_degrades_with_a_reason(tmp_path: Path, monkeypatch):
    settings, user_id, client, _ = build_changes_fixture(tmp_path)
    ai.save_ai_settings(settings, {"ai_api_key": "sk-test"})

    def busy(*args, **kwargs):
        raise ai.AIUnavailable("budget", "minute")

    monkeypatch.setattr(ai, "complete", busy)
    csrf = csrf_for(settings, user_id)
    response = client.post("/changes/ai-summary", data={"csrf_token": csrf}, headers={"Accept": "application/json"})
    assert response.status_code == 503 and response.json() == {"ok": False, "reason": "budget"}
    fallback = client.post("/changes/ai-summary", data={"csrf_token": csrf}, follow_redirects=False)
    assert fallback.headers["location"] == "/changes?ai_error=budget#changes-ai"
    page = client.get("/changes?ai_error=budget").text
    assert html.escape(i18n.t("aiassist.error_budget")) in page
    # An unusable reply is a provider error, not a 500.
    monkeypatch.setattr(ai, "complete", reply("not json at all"))
    broken = client.post("/changes/ai-summary", data={"csrf_token": csrf}, headers={"Accept": "application/json"})
    assert broken.json()["reason"] == "provider_error"


def test_ai_summary_requires_csrf(tmp_path: Path, monkeypatch):
    settings, _, client, _ = build_changes_fixture(tmp_path)
    ai.save_ai_settings(settings, {"ai_api_key": "sk-test"})
    stub = reply(SUMMARY)
    monkeypatch.setattr(ai, "complete", stub)
    assert client.post("/changes/ai-summary", data={"csrf_token": "wrong"}).status_code == 403
    assert stub.calls == []


def test_a_guest_reads_the_page_but_cannot_ask_ai(tmp_path: Path, monkeypatch):
    settings, user_id, _, _ = build_changes_fixture(tmp_path)
    ai.save_ai_settings(settings, {"ai_api_key": "sk-test"})
    stub = reply(SUMMARY)
    monkeypatch.setattr(ai, "complete", stub)
    expires = (datetime.now(UTC) + timedelta(days=3)).isoformat(timespec="seconds")
    _, secret = create_access_token(settings, user_id, "guest", "Dr Test", expires_at=expires)
    with TestClient(create_app(settings)) as guest:
        guest.get(f"/t/{secret}")
        page = guest.get("/changes")
        assert page.status_code == 200
        assert 'id="changes-ai-form"' not in page.text
        assert guest.post("/changes/ai-summary", data={"csrf_token": ""}).status_code == 403
    assert stub.calls == []


def test_a_change_row_draws_its_trend_with_values_on_the_points(tmp_path: Path):
    settings, user_id, client, _ = build_changes_fixture(tmp_path)
    entries = by_name(view_for(settings, user_id)["groups"][0])
    kappa = entries["Kappa marker"]["trend"]
    # Oldest first; the newest point is this result.
    assert [point["month"] for point in kappa["points"]] == ["Feb 2025", "Sep 2025"]
    assert [point["current"] for point in kappa["points"]] == [False, True]
    assert all(0 <= point["y"] <= kappa["height"] for point in kappa["points"])
    assert kappa["band"] is not None and "13 Feb 2025" in kappa["label"]
    # One reading is no trend; units that do not fold are never one line.
    assert entries["Lambda marker"]["trend"] is None
    assert entries["Nu marker"]["trend"] is None
    page = client.get("/changes").text
    assert 'class="an-trend"' in page and 'class="an-trend__value"' in page
    uk = client.get("/changes?lang=uk").text
    assert "лют. 2025" in uk and "Динаміка від найстарішого" in uk


def test_ai_summary_is_folded_after_the_changes_with_notes_in_their_rows(tmp_path: Path, monkeypatch):
    settings, user_id, client, _ = build_changes_fixture(tmp_path)
    ai.save_ai_settings(settings, {"ai_api_key": "sk-test"})
    monkeypatch.setattr(ai, "complete", reply(SUMMARY))
    before = client.get("/changes").text
    # Nothing written yet: a closed block with a teaser, and no AI badge.
    assert '<details class="panel an-change-ai" id="changes-ai">' in before
    assert "AI-generated" not in before
    assert before.index('class="an-change-list"') < before.index('id="changes-ai"')
    csrf = csrf_for(settings, user_id)
    client.post("/changes/ai-summary", data={"csrf_token": csrf}, headers={"Accept": "application/json"})
    page = client.get("/changes").text
    block = page.split('id="changes-ai"', 1)[1].split("<script>", 1)[0]
    # The per-test finding sits, folded, in the Theta marker change row.
    theta_row = page.split(">Theta marker</a>", 1)[1].split("</li>", 1)[0]
    assert 'class="an-change-note"' in theta_row and "Theta marker reached 8.0 mmol/L." in theta_row
    assert "Theta marker reached 8.0 mmol/L." not in block
    # Stored in UTC, printed as a localised date the browser restates locally.
    assert "UTC" not in block and "<time datetime=" in block and "data-local" in block


def test_collapsed_buckets_defer_their_charts(tmp_path: Path):
    _, _, client, _ = build_changes_fixture(tmp_path)
    page = client.get("/changes").text
    head, more = page.split('class="an-change-more"', 1)
    # Kappa marker is stable: its chart waits in a <template> until opened.
    lazy = more.split('<template class="an-trend-lazy">', 1)
    assert len(lazy) == 2 and lazy[1].lstrip().startswith('<svg class="an-trend"')
    assert '<svg class="an-trend"' in head and "an-trend-lazy" not in head


def test_sparkline_axis_follows_the_readings_not_a_distant_band():
    from anamna.web import app as web

    class Web:
        fit_domain = staticmethod(web.fit_domain)
        format_measured = staticmethod(lambda value, unit: f"{value:g}")
        format_date = staticmethod(lambda value: str(value))

    history = [
        {"value_numeric": value, "preferred_unit": "g/L", "unit_raw": "g/L", "observed_at": day}
        for value, day in ((151, "2026-08-04"), (146, "2025-11-05"), (152, "2025-08-02"))
    ]
    trend = changes._trend(Web, history, "g/L", "g/L", {"target_low": 130.0, "target_high": 170.0})
    ys = [point["y"] for point in trend["points"]]
    # 146-152 spans most of the plot instead of 3-13 px under a 130-170 axis.
    assert max(ys) - min(ys) > 30
    # Every reading is inside the band, so it shades the whole visible plot.
    assert trend["band"]["height"] >= max(ys) - min(ys)


# --- Result episodes ------------------------------------------------------------


def test_result_dates_group_into_episodes_by_gap_and_order():
    days = {"2025-01-01", "2025-01-08", "2025-01-16", "2025-03-01", "2025-03-03"}
    # Seven days apart is one episode; eight days apart is a new one.
    assert changes.group_episodes(days) == [
        ("2025-01-01", "2025-01-08"), ("2025-01-16", "2025-01-16"), ("2025-03-01", "2025-03-03"),
    ]
    # One laboratory order with results on both sides of a long gap is one episode.
    order = {("lab", "A-1"): {"2025-01-08", "2025-03-01"}}
    assert changes.group_episodes(days, order) == [("2025-01-01", "2025-03-03")]
    assert changes.group_episodes(set()) == []


def test_span_labels_in_both_locales():
    token = i18n.activate_locale("en")
    try:
        assert changes.span_text("2025-08-28", "2025-08-28") == "28 Aug 2025"
        assert changes.span_text("2026-08-03", "2026-08-04") == "03-04 Aug 2026"
        assert changes.span_text("2025-08-28", "2025-09-04") == "28 Aug - 04 Sep 2025"
        assert changes.span_text("2024-12-28", "2025-01-04") == "28 Dec 2024 - 04 Jan 2025"
    finally:
        i18n.reset_locale(token)
    token = i18n.activate_locale("uk")
    try:
        assert changes.span_text("2025-08-28", "2025-09-04") == "28 серп. - 04 вер. 2025"
    finally:
        i18n.reset_locale(token)


def test_default_shows_only_the_latest_episode(tmp_path: Path):
    settings, user_id, client, _ = build_changes_fixture(tmp_path)
    view = view_for(settings, user_id)
    assert [e["value"] for e in view["episodes"]] == ["2025-08-28", "2025-02-13"]
    assert view["episodes"][0]["current"] and view["selection"]["kind"] == "latest"
    assert view["nav"]["earlier"]["url"] == "/changes?episode=2025-02-13" and "newer" not in view["nav"]
    names = set(by_name(view["report"]))
    # Tests measured only in the older episode are not in the latest report.
    older_only = set(by_name(view_for(settings, user_id, episode="2025-02-13")["report"])) - names
    assert older_only, "the fixture's February draw should hold tests the latest episode lacks"
    page = client.get("/changes").text
    assert page.count('class="panel an-change-group"') == 1
    assert '<select id="changes-episode" name="episode">' in page
    assert 'href="/changes?episode=2025-02-13" rel="prev"' in page
    assert "an-change-jump" not in page and "an-change-hero" not in page
    assert all(f">{html.escape(name)}</a>" not in page for name in older_only)


def test_previous_value_is_taken_from_before_the_episode(tmp_path: Path):
    settings, user_id, client, ids = build_changes_fixture(tmp_path)
    with connect(settings) as connection:
        # Kappa also measured on 2025-08-28, inside the latest episode, far out of range.
        _observation(connection, user_id, "doc-1", 300, ids["Kappa marker"], "Kappa marker",
                     (9.0, "mmol/L", 1, 5), "2025-08-28")
    kappa = by_name(view_for(settings, user_id)["report"])["Kappa marker"]
    # Compared with February, not with the other half of the same episode.
    assert kappa["previous"]["date_text"] == "13 Feb 2025" and kappa["bucket"] == "stable"
    assert kappa["value_text"] == "3.5"
    assert kappa["also"] == ["28 Aug 2025: 9 mmol/L"]
    assert "Also measured in this period: 28 Aug 2025: 9 mmol/L" in client.get("/changes").text


def test_custom_range_merges_into_one_report(tmp_path: Path):
    settings, user_id, _, _ = build_changes_fixture(tmp_path)
    view = view_for(settings, user_id, date_from="2025-02-01", date_to="2025-09-30")
    assert view["selection"] == {"kind": "range", "from": "2025-02-01", "to": "2025-09-30",
                                 "label": "01 Feb - 30 Sep 2025"}
    report = view["report"]
    assert report["date"] == "2025-02-13..2025-09-01"
    kappa = by_name(report)["Kappa marker"]
    # Both readings are inside the range: one row, nothing before it to compare.
    assert kappa["previous"] is None and kappa["also"] == ["13 Feb 2025: 3 mmol/L"]
    assert view["scope"] is None and view["ai_payload"] == []
    # Reversed dates are read the right way round.
    swapped = view_for(settings, user_id, date_from="2025-09-30", date_to="2025-02-01")
    assert swapped["selection"]["from"] == "2025-02-01"


def test_selection_round_trips_through_the_query_string(tmp_path: Path):
    _, _, client, _ = build_changes_fixture(tmp_path)
    older = client.get("/changes?episode=2025-02-13").text
    assert '<option value="2025-02-13" data-url="/changes?episode=2025-02-13" selected>' in older
    assert 'href="/changes" rel="next"' in older
    # Any date inside an episode finds it; a nonsense value falls back to the latest.
    assert 'value="2025-08-28" data-url="/changes" selected' in client.get("/changes?episode=2025-09-01").text
    assert 'value="2025-08-28" data-url="/changes" selected' in client.get("/changes?episode=nope").text
    ranged = client.get("/changes?from=2025-02-01&to=2025-09-30").text
    assert 'name="from" value="2025-02-01"' in ranged and 'name="to" value="2025-09-30"' in ranged
    assert '<details class="an-change-range" open>' in ranged
    assert "Chosen dates: 01 Feb - 30 Sep 2025" in ranged
    empty = client.get("/changes?from=2030-01-01&to=2030-02-01")
    assert empty.status_code == 200
    assert "No results in 01 Jan - 01 Feb 2030" in empty.text and 'href="/changes"' in empty.text
    # A one-test period says nothing extra: the count beside the heading does.
    single = client.get("/changes?from=2025-08-28&to=2025-08-28").text
    assert "Only one test was measured in this period." not in single


def test_episode_and_range_pages_render_in_both_locales(tmp_path: Path):
    _, _, client, _ = build_changes_fixture(tmp_path)
    client.cookies.set("anamna_lang", "uk")
    for url in ("/changes", "/changes?episode=2025-02-13", "/changes?from=2025-02-01&to=2025-09-30",
                "/changes?from=2030-01-01&to=2030-02-01"):
        page = client.get(url).text
        visible = page.replace("/changes", "").replace("#changes", "").replace("changes-", "")
        assert "changes." not in visible, url
    uk = client.get("/changes").text
    assert "Результати за" in uk and "Раніше: 13 лют. 2025" in uk and "Свій період одним звітом" in uk
    assert "28 серп. - 01 вер. 2025" in uk


def test_order_number_joins_an_episode_across_a_gap(tmp_path: Path):
    settings, user_id, _, _ = build_changes_fixture(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE documents SET order_identifier='A-1',"
            " vendor_id=(SELECT vendor_id FROM documents WHERE id='doc-2') WHERE id IN ('doc-1', 'doc-2')"
        )
    view = view_for(settings, user_id)
    assert [(e["value"], e["label"]) for e in view["episodes"]] == [("2025-02-13", "13 Feb - 01 Sep 2025")]


def test_home_monitoring_pdfs_never_make_an_episode(tmp_path: Path):
    """A Garmin cuff's 4-week log is device data: near-daily readings would
    chain separate lab visits into one month-long episode."""
    settings, user_id, _, _ = build_changes_fixture(tmp_path)
    before = [e["value"] for e in view_for(settings, user_id)["episodes"]]
    with connect(settings) as connection:
        vendor_id = ensure_vendor(connection, "Garmin Connect", None)
        connection.execute(
            """INSERT INTO documents(
                   id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type,
                   extraction_strategy, classification_confidence, report_date, imported_at, status
               ) VALUES ('doc-bp', ?, ?, ?, 'bp.pdf', 'bp.pdf', 'application/pdf', 10, 'sha-bp', 1,
                         'Blood pressure log', 'blood_pressure', 'native_text', 1, '2025-10-01', ?, 'final')""",
            (user_id, f"patient-{user_id}", vendor_id, utc_now()),
        )
        systolic, _ = ensure_concept(connection, "Systolic blood pressure", vendor_id)
        for day in range(1, 29):
            _observation(connection, user_id, "doc-bp", day, systolic, "Systolic blood pressure",
                         (120.0 + day % 5, "mmHg", 90, 140), f"2025-10-{day:02d}")
    assert [e["value"] for e in view_for(settings, user_id)["episodes"]] == before
    # The upload's own view still answers "what did this file change".
    assert view_for(settings, user_id, document_id="doc-bp")["report"]
