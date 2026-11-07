"""/vaccinations as a person reads it (UX-07 / UX-35): which vaccine, by whom,
where, findable — in both languages, with nothing left unexplained."""

from __future__ import annotations

import re
from pathlib import Path

from anamna.db import connect
from anamna.immunizations import parse_immunizations, store_document_doses

from test_immunizations_products import CARD
from test_web_panels import build


def _seed(settings, user_id: str) -> None:
    with connect(settings) as connection:
        store_document_doses(connection, user_id, f"patient-{user_id}", "doc-1",
                             parse_immunizations([CARD]), "scanned_page_ocr")
        connection.commit()


def test_each_section_names_its_products_makers_and_latest_date(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _seed(settings, user_id)
    page = client.get("/vaccinations").text
    summaries = re.findall(r'<summary class="an-vax-group__summary">(.*?)</summary>', page, re.S)
    hepatitis = next(summary for summary in summaries if "Hepatitis A" in summary)
    assert "Twinrix · GSK" in hepatitis
    assert "latest" in hepatitis
    # The registered maker and the facility, in the row; the printed paragraph
    # only under "As printed".
    assert "GlaxoSmithKline Biologicals S.A." in page
    assert "ТзОВ Тестовий Центр" in page
    assert "As printed" in page
    # The code says what it means without a hover.
    assert "HepAHepB</span> - Hepatitis A · Hepatitis B" in page
    # Every product cites where its name comes from.
    assert "drlz.com.ua/lz/tvinryks" in page and "Registration and sources (3)" in page
    assert "Schedule sources (3)" in page
    # A combined vaccine is listed under each disease; its ids must still be unique.
    ids = re.findall(r'<li class="an-vax-dose" id="([^"]+)"', page)
    assert len(ids) == len(set(ids))


def test_the_dose_list_can_be_searched_and_filtered(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _seed(settings, user_id)
    page = client.get("/vaccinations?q=Twinrix").text
    assert 'role="search"' in page
    assert 'id="vax-filter-q" type="search" name="q" value="Twinrix"' in page
    for control in ("vax-filter-year", "vax-filter-product", "vax-filter-disease"):
        assert f'<label for="{control}">' in page, control
    assert '<option value="2026">2026</option>' in page
    assert '<option value="twinrix">Twinrix</option>' in page
    assert 'aria-live="polite"' in page
    row = re.search(r'<li class="an-vax-dose" id="dose-hepatitis_a-[^"]+"[^>]*>', page).group(0)
    assert 'data-year="2026"' in row and 'data-product="twinrix"' in row
    # The search text holds the names in both languages, folded once.
    assert "twinrix" in row and "hepatitis a" in row and "ahabb411xy" in row


def test_the_three_selects_fold_behind_filters_on_a_phone(tmp_path: Path):
    """Search plus three full-width selects was taller than the list it
    filtered: the selects sit in a <details> «Filters» fold that the
    stylesheet keeps open from 720px, where they form one row."""
    settings, user_id, client = build(tmp_path)
    _seed(settings, user_id)
    for locale, toggle in (("en", "Filters"), ("uk", "Фільтри")):
        client.cookies.set("anamna_lang", locale)
        page = client.get("/vaccinations").text
        form = page.split('<form class="an-vax-filter"', 1)[1].split("</form>", 1)[0]
        fold = form.split('<details class="an-vax-filter__more">', 1)[1]
        assert f'<summary class="an-vax-filter__toggle">{toggle}</summary>' in fold
        for control in ("vax-filter-year", "vax-filter-product", "vax-filter-disease"):
            assert f'id="{control}"' in fold, control
        # The search box stays outside the fold, labelled for assistive tech.
        assert 'id="vax-filter-q"' not in fold
        # No title block at all: the page opens on its one compact band.
        assert '<section class="an-vax-head"' in page and "page-head" not in page
    css = (Path(__file__).parents[2] / "src/anamna/web/static/app.css").read_text(encoding="utf-8")
    wide = css[css.index(".an-vax-filter__toggle { display: none; }") - 400:]
    assert "@media (min-width: 720px)" in wide[:400]
    assert ".an-vax-filter__more::details-content { content-visibility: visible;" in wide


def test_both_locales_and_no_stray_english(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _seed(settings, user_id)
    client.cookies.set("anamna_lang", "uk")
    page = client.get("/vaccinations").text
    for expected in ("Як надруковано", "Знайти щеплення", "Усі роки", "Захищає від",
                     "Джерела календарів (3)", "Що означають позначки біля щеплення", "Код вакцини eHealth",
                     "Заклад за документом", "0,5 мл"):
        assert expected in page, expected
    for leaked in ("As printed", "All years", "Schedule sources", "Registration and sources",
                   "Facility on the card", "doses match", "Published by"):
        assert leaked not in page, leaked
    # The client-side count uses all three Ukrainian plural forms.
    assert 'data-few="Знайдено {count} щеплення"' in page
    assert 'data-many="Знайдено {count} щеплень"' in page


def test_a_typed_dose_keeps_its_trade_name_facility_and_clinician(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        csrf = connection.execute(
            "SELECT csrf_token FROM sessions WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (user_id,)
        ).fetchone()[0]
    client.post("/vaccinations", data={
        "csrf_token": csrf, "occurred_on": "2024-05-02", "vaccine_code": "HPV",
        "trade_name": "Gardasil 9", "manufacturer": "MSD", "facility": "Clinic 7",
        "clinician": "Dr Test",
    }, follow_redirects=False)
    with connect(settings) as connection:
        row = dict(connection.execute("SELECT * FROM immunizations").fetchone())
    assert (row["trade_name"], row["facility"], row["clinician"]) == ("Gardasil 9", "Clinic 7", "Dr Test")
    page = client.get("/vaccinations").text
    assert "Gardasil 9" in page and "Clinic 7" in page and "Dr Test" in page
    # Saving the correction form must not wipe them.
    client.post(f"/vaccinations/{row['id']}", data={
        "csrf_token": csrf, "action": "save", "occurred_on": "2024-05-02", "vaccine_code": "HPV",
        "trade_name": "Gardasil 9", "facility": "Clinic 8", "clinician": "Dr Test",
    }, follow_redirects=False)
    with connect(settings) as connection:
        assert connection.execute("SELECT facility FROM immunizations").fetchone()[0] == "Clinic 8"
