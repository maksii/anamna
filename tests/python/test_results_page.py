"""/results: the one page that replaced /metrics, /panels and /changes.

Each test seeds only what it needs on top of the miniature record that
``test_web_panels.build`` makes (LDL and HDL on 2025-02-13, the vitamin D pair
on 2025-08-28, and so on) and asserts one thing about the page.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from markupsafe import escape

from anamna.db import connect, utc_now
from anamna.i18n import activate_locale, reset_locale, t
from anamna.ingest.pipeline import ensure_concept, ensure_vendor
from anamna.panels import PANEL_BY_ID
from anamna.web import app as web
from anamna.web import results as results_module

from test_web_panels import build

LDL = "ldl-cholesterol"
HDL = "hdl-cholesterol"


def _msg(key: str, locale: str = "en", **values) -> str:
    token = activate_locale(locale)
    try:
        return t(key, **values)
    finally:
        reset_locale(token)


def _list_region(page: str) -> str:
    """The results region of the page: the list, its period picker and its view form.

    The header echoes the request address into its language and theme forms,
    so two addresses that show the same list differ there and nowhere else.
    """
    return page.split('<div id="search-results">', 1)[1].split("<script", 1)[0]


def _rows(page: str) -> list[str]:
    """Each result row, from the end of its opening tag to its closing tag."""
    return [chunk.split("</li>", 1)[0] for chunk in page.split('<li class="an-res"')[1:]]


def _row(page: str, concept_id: str) -> str:
    return next(row for row in _rows(page) if f'href="/metrics/{concept_id}"' in row)


def _section(page: str, key: str) -> str:
    """The body of one disclosure of the list, from its opening tag to its close."""
    return page.split(f'data-section="{key}"', 1)[1].split("</details>", 1)[0]


def add_document(settings, user_id: str, document_id: str, report_date: str) -> None:
    source = settings.source_dir / f"{document_id}.pdf"
    source.write_text("report", encoding="utf-8")
    with connect(settings) as connection:
        vendor_id = ensure_vendor(connection, "Test Lab", None)
        connection.execute(
            """INSERT INTO documents(
                   id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type,
                   extraction_strategy, classification_confidence, report_date, imported_at, status
               ) VALUES (?, ?, ?, ?, ?, ?, 'application/pdf', 10, ?, 1, ?, 'laboratory',
                         'native_text', 1, ?, ?, 'final')""",
            (
                document_id, user_id, f"patient-{user_id}", vendor_id, f"{document_id}.pdf",
                str(source), f"sha-{document_id}", f"Follow-up {document_id}", report_date, utc_now(),
            ),
        )


def add_results(settings, user_id: str, document_id: str, rows: list[tuple]) -> None:
    """Each row is (name, value, unit, observed, low, high), all read on one document."""
    with connect(settings) as connection:
        vendor_id = ensure_vendor(connection, "Test Lab", None)
        for name, value, unit, observed, low, high in rows:
            concept_id, _ = ensure_concept(connection, name, vendor_id)
            connection.execute(
                """INSERT INTO observations(
                       id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
                       value_type, value_numeric, unit_raw, observed_at,
                       vendor_reference_text, vendor_reference_low, vendor_reference_high,
                       verification_status, extraction_method, confidence, evidence_text,
                       parser_version, created_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?, 'numeric', ?, ?, ?, ?, ?, ?, 'extracted', 'test', 0.9,
                           ?, 'test', ?)""",
                (
                    f"seed-{document_id}-{concept_id}", user_id, f"patient-{user_id}", document_id,
                    concept_id, name, value, unit, observed,
                    f"{low} - {high}" if low is not None else None, low, high,
                    f"{name} evidence", utc_now(),
                ),
            )


def test_the_page_has_one_navigation_entry_and_no_retired_links(tmp_path: Path):
    _, _, client = build(tmp_path)
    page = client.get("/results").text
    assert page.count(f"<h1>{_msg('results.heading')}</h1>") == 1
    primary = page.split('<nav class="nav-links"', 1)[1].split("</nav>", 1)[0]
    links = re.findall(r'<a [^>]*href="/results"[^>]*>', primary)
    assert len(links) == 1
    assert 'aria-current="page"' in links[0]
    for retired in ('href="/metrics"', 'href="/panels"', 'href="/changes"'):
        assert retired not in page, retired
    assert not re.search(r'href="/(metrics|panels|changes)\?', page)


def test_a_result_measured_twice_is_one_row_with_its_previous_value(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_document(settings, user_id, "doc-2", "2025-09-01")
    add_results(settings, user_id, "doc-2", [("LDL cholesterol", 2.5, "mmol/L", "2025-09-01", 0.0, 3.0)])
    page = client.get("/results").text
    ldl_rows = [row for row in _rows(page) if f'href="/metrics/{LDL}"' in row]
    assert len(ldl_rows) == 1
    assert 'class="an-res__name" href="/metrics/ldl-cholesterol"' in ldl_rows[0]
    assert "<strong>2.5</strong>" in ldl_rows[0]
    assert _msg("changes.was_on", value="4.42 mmol/L", date="13 Feb 2025") in ldl_rows[0]


def test_the_attention_filter_lists_an_outside_result_and_not_an_inside_one(tmp_path: Path):
    _, _, client = build(tmp_path)
    page = client.get("/results?show=attention").text
    assert 'data-attention="true"' in _row(page, LDL)
    assert f'href="/metrics/{HDL}"' not in page
    assert re.search(r'data-chip="attention"[^>]*aria-current="page"', page)


def test_an_attention_row_names_how_far_outside_its_interval_and_an_inside_row_does_not(tmp_path: Path):
    _, _, client = build(tmp_path)
    row = _row(client.get("/results?show=attention").text, LDL)
    assert "outside the interval" in row
    assert _msg("insights.outside_by", amount="1.42 mmol/L") in row
    assert "outside the interval" not in _row(client.get("/results").text, HDL)


def test_the_unverified_filter_links_to_the_documents_awaiting_review(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_document(settings, user_id, "doc-2", "2025-09-01")
    add_results(settings, user_id, "doc-2", [("LDL cholesterol", 2.5, "mmol/L", "2025-09-01", 0.0, 3.0)])
    link = 'href="/documents?review_state=open"'
    assert link in _list_region(client.get("/results?show=unverified").text)
    assert link not in _list_region(client.get("/results").text)


def test_the_not_yet_checked_chip_counts_what_its_filter_lists(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    # The fixture's observations all start as extracted; verify them so only the rows added below are unchecked.
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE owner_user_id=?", (user_id,))
    add_document(settings, user_id, "doc-2", "2025-09-01")
    add_results(settings, user_id, "doc-2", [
        ("Seeded marker checked", 1.0, "mmol/L", "2025-09-01", None, None),
        ("Seeded marker first", 2.0, "mmol/L", "2025-09-01", None, None),
        ("Seeded marker second", 3.0, "mmol/L", "2025-09-01", None, None),
    ])
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET verification_status='verified' WHERE owner_user_id=? AND raw_name='Seeded marker checked'",
            (user_id,),
        )
        concept = {
            name: connection.execute(
                "SELECT concept_id FROM observations WHERE owner_user_id=? AND raw_name=?", (user_id, name),
            ).fetchone()[0]
            for name in ("Seeded marker checked", "Seeded marker first", "Seeded marker second")
        }
    web.invalidate_catalog(user_id)

    page = client.get("/results").text
    assert re.search(r'data-chip="unverified"[^>]*>[^<]*<span>2</span>', page)
    listed = _list_region(client.get("/results?show=unverified").text)
    assert len(_rows(listed)) == 2
    assert f'href="/metrics/{concept["Seeded marker first"]}"' in listed
    assert f'href="/metrics/{concept["Seeded marker second"]}"' in listed
    assert f'href="/metrics/{concept["Seeded marker checked"]}"' not in listed


def test_the_whole_record_links_to_the_allergy_and_genetics_overviews(tmp_path: Path):
    _, _, client = build(tmp_path)
    page = client.get("/results").text
    assert 'aria-labelledby="results-overviews"' in page
    section = page.split('aria-labelledby="results-overviews"', 1)[1].split("</section>", 1)[0]
    assert 'href="/allergy"' in section
    assert 'href="/genetics"' in section
    for url in ("/results?show=attention", "/results?area=heart"):
        assert 'aria-labelledby="results-overviews"' not in client.get(url).text, url


def test_a_result_sits_under_its_test_group_or_its_body_system(tmp_path: Path):
    _, _, client = build(tmp_path)
    by_group = client.get("/results?group=panel").text
    assert f'href="/metrics/{LDL}"' in _section(by_group, "panel-lipids")
    assert 'data-section="area-heart"' not in by_group
    by_area = client.get("/results").text
    assert f'href="/metrics/{LDL}"' in _section(by_area, "area-heart")
    assert 'data-section="panel-lipids"' not in by_area


def test_a_body_system_shows_five_rows_and_links_to_the_rest(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    # Five more heart results from the lipid panel, so the body system holds
    # seven: LDL and HDL from the fixture plus these.
    names = PANEL_BY_ID["lipids"].member_names
    extra = [
        (name, 1.0, "mmol/L", "2025-02-13", None, None)
        for name, concept_id in zip(names, PANEL_BY_ID["lipids"].members)
        if concept_id not in (LDL, HDL)
    ][:5]
    add_results(settings, user_id, "doc-1", extra)

    page = client.get("/results").text
    section = _section(page, "area-heart")
    assert len(_rows(section)) == 5
    assert 'href="/results?area=heart"' in section

    only = client.get("/results?area=heart").text
    assert len(_rows(only)) == 7
    token = activate_locale("en")
    try:
        area_name = web.translate_phrase(str(web.AREA_BY_ID["heart"]["name"]))
    finally:
        reset_locale(token)
    assert str(escape(_msg("results.area_only", area=area_name))) in only


def test_the_flat_list_is_paged_forty_at_a_time(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_results(
        settings, user_id, "doc-1",
        [(f"Seeded marker {index:02d}", 1.0 + index, "mmol/L", "2025-02-13", None, None) for index in range(45)],
    )
    first = client.get("/results?group=none").text
    assert len(_rows(first)) == 40
    next_link = re.search(r'href="([^"]*offset=40)"', first)
    assert next_link, "the first page offers no next page"
    second = client.get(html.unescape(next_link.group(1))).text
    # Seven results from the fixture and the forty-five seeded above.
    assert len(_rows(second)) == 7 + 45 - 40


def test_episode_latest_is_the_newest_test_date_only(tmp_path: Path):
    _, _, client = build(tmp_path)
    page = client.get("/results?episode=latest").text
    rows = _rows(page)
    assert len(rows) == 1
    assert 'href="/metrics/25-hydroxyvitamin-d"' in rows[0]
    assert 'class="an-change-counts"' in page
    assert _list_region(client.get("/results?episode=all").text) == _list_region(client.get("/results").text)


def test_sort_by_name_orders_the_rows_and_reverse_flips_them(tmp_path: Path):
    _, _, client = build(tmp_path)

    def names(url: str) -> list[str]:
        return [html.unescape(name) for name in re.findall(r'<a class="an-res__name" href="[^"]*">([^<]+)</a>', client.get(url).text)]

    ascending = names("/results?sort=name&group=none")
    assert len(ascending) == 7
    assert ascending == sorted(ascending, key=str.casefold)
    assert names("/results?sort=name&group=none&reverse=1") == ascending[::-1]
    # Under the default grouping each body system's own rows are in name order.
    grouped = client.get("/results?sort=name").text
    for section in re.findall(r'<details class="an-area-section an-res-section".*?</details>', grouped, re.S):
        section_names = re.findall(r'<a class="an-res__name" href="[^"]*">([^<]+)</a>', section)
        assert section_names == sorted(section_names, key=str.casefold)


def test_a_search_shows_its_heading_and_the_matching_row_and_no_sections(tmp_path: Path):
    _, _, client = build(tmp_path)
    page = client.get("/results?q=cholesterol").text
    assert 'id="result-title"' in page
    assert str(escape(_msg("metrics.matches_for", query="cholesterol"))) in page
    assert f'href="/metrics/{LDL}"' in _row(page, LDL)
    assert f'href="/metrics/{HDL}"' in " ".join(_rows(page))
    assert "data-section=" not in page


def test_retired_addresses_redirect_to_their_filter(tmp_path: Path):
    _, _, client = build(tmp_path)
    cases = {
        "/panels": "/results?group=panel",
        "/metrics?status=due": "/results?show=due&group=panel",
        "/changes?document=abc": "/results?document=abc",
    }
    for old, new in cases.items():
        response = client.get(old, follow_redirects=False)
        assert response.status_code == 301, old
        assert response.headers["location"] == new, old


def test_unknown_filter_values_fall_back_to_the_defaults(tmp_path: Path):
    _, _, client = build(tmp_path)
    default = client.get("/results")
    odd = client.get("/results?area=nope&sort=nope&show=nope&group=nope")
    assert odd.status_code == 200
    assert _list_region(odd.text) == _list_region(default.text)


def test_the_page_speaks_ukrainian_without_raw_keys(tmp_path: Path):
    _, _, client = build(tmp_path)
    client.cookies.set("anamna_lang", "uk")
    for url in ("/results", "/results?group=panel", "/results?q=cholesterol", "/results?show=attention"):
        response = client.get(url)
        assert response.status_code == 200, url
        # Scripts are not page text: the list's script names its own JS keys.
        body = re.sub(r"<script.*?</script>", "", response.text, flags=re.S)
        assert _msg("results.heading", "uk") in body, url
        assert not re.search(r"results\.[a-z_]+", body), url


def test_mark_stamps_attention_historical_and_due_on_the_whole_record(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    web.invalidate_catalog()
    with connect(settings) as connection:
        catalog = web._complete_days(connection, user_id, web._metric_catalog(connection, user_id))
    catalog = [{**card, "historical": True} if card["id"] == HDL else card for card in catalog]
    panels = [
        {"id": "lipids", "present_count": 2, "staleness": {"state": "overdue", "days_ago": 400}},
        {"id": "kidney", "present_count": 1, "staleness": {"state": "fresh", "days_ago": 1}},
    ]
    entries = [
        {"concept_id": LDL, "bucket": "new", "panel_id": "lipids"},
        {"concept_id": HDL, "bucket": "first", "panel_id": "lipids"},
        {"concept_id": "creatinine", "bucket": "first", "panel_id": "kidney"},
    ]
    results_module.mark(entries, everything=True, catalog=catalog, panels=panels, web=web)
    assert [entry["attention"] for entry in entries] == [True, False, False]
    assert [entry["historical"] for entry in entries] == [False, True, False]
    assert [entry["due"] for entry in entries] == [True, True, False]


def test_mark_on_a_test_date_takes_attention_from_the_change_and_no_history(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    web.invalidate_catalog()
    with connect(settings) as connection:
        catalog = web._complete_days(connection, user_id, web._metric_catalog(connection, user_id))
    catalog = [{**card, "historical": True} if card["id"] == HDL else card for card in catalog]
    panels = [{"id": "lipids", "present_count": 2, "staleness": {"state": "overdue", "days_ago": 400}}]
    entries = [
        {"concept_id": LDL, "bucket": "new", "panel_id": "lipids"},
        {"concept_id": HDL, "bucket": "stable", "panel_id": "lipids"},
        {"concept_id": "hemoglobin", "bucket": "borderline", "panel_id": "cbc"},
    ]
    results_module.mark(entries, everything=False, catalog=catalog, panels=panels, web=web)
    assert [entry["attention"] for entry in entries] == [True, False, True]
    assert [entry["historical"] for entry in entries] == [False, False, False]
    assert [entry["due"] for entry in entries] == [True, True, False]


def test_mark_names_the_distance_only_for_an_attention_result(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    web.invalidate_catalog()
    with connect(settings) as connection:
        catalog = web._complete_days(connection, user_id, web._metric_catalog(connection, user_id))
    panels = [{"id": "lipids", "present_count": 2, "staleness": {"state": "fresh", "days_ago": 1}}]
    entries = [
        {"concept_id": LDL, "bucket": "new", "panel_id": "lipids", "value_numeric": 4.42,
         "unit": "mmol/L", "verdict": {"target_high": 3.0}},
        {"concept_id": HDL, "bucket": "stable", "panel_id": "lipids", "value_numeric": 0.5,
         "unit": "mmol/L", "verdict": {"target_low": 1.0, "target_high": 2.2}},
    ]
    results_module.mark(entries, everything=False, catalog=catalog, panels=panels, web=web)
    assert [entry["attention"] for entry in entries] == [True, False]
    assert entries[0]["outside_by_text"] == "1.42 mmol/L"
    assert entries[1]["outside_by_text"] is None


def test_chips_leave_out_an_empty_filter_but_keep_all_and_the_one_on_screen():
    token = activate_locale("en")
    try:
        counts = {"attention": 0, "due": 0}
        plain = results_module.chips(counts, total=10, changed=0, unverified=3, current="")
        assert [chip["key"] for chip in plain] == ["all", "unverified"]
        assert plain[0]["count"] == 10 and plain[0]["current"] is False
        assert plain[1]["href"] == "/results?show=unverified" and plain[1]["tone"] == "due"
        assert plain[1]["count"] == 3

        on_screen = results_module.chips(counts, total=10, changed=0, unverified=3, current="attention")
        assert [chip["key"] for chip in on_screen] == ["all", "attention", "unverified"]
        assert next(chip for chip in on_screen if chip["key"] == "attention")["current"] is True
    finally:
        reset_locale(token)
