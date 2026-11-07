"""Index pages open on content, not on a title block.

The navigation already names the page, so the home page, /panels,
/vaccinations and /devices dropped their eyebrows, visible titles and lead
paragraphs. Each still has exactly one h1 for screen readers, and every
sentence that carried meaning is still reachable — folded, not deleted.
"""
from __future__ import annotations

import re
from pathlib import Path

from anamna.db import connect
from anamna.i18n import activate_locale, reset_locale, t
from anamna.web import app as web

from test_web_panels import build
from test_web_search import _seed_finding
from test_web_vaccinations import _seed as _seed_vaccinations

LOCALES = ("en", "uk")


def _msg(key: str, locale: str, **values) -> str:
    token = activate_locale(locale)
    try:
        return t(key, **values)
    finally:
        reset_locale(token)


def _visible(page: str) -> str:
    """The markup a sighted reader sees on arrival: no folded <details>
    bodies, no visually-hidden elements, no scripts."""
    page = re.sub(r"<script.*?</script>", "", page, flags=re.S)
    page = re.sub(r"(<details[^>]*>\s*<summary[^>]*>.*?</summary>).*?</details>", r"\1", page, flags=re.S)
    return re.sub(r'<(\w+)[^>]*class="[^"]*visually-hidden[^"]*"[^>]*>.*?</\1>', "", page, flags=re.S)


def _h1s(page: str) -> list[str]:
    return re.findall(r"<h1\b[^>]*>", page)


def _get(client, path: str, locale: str) -> str:
    client.cookies.set("anamna_lang", locale)
    response = client.get(path)
    assert response.status_code == 200, path
    return response.text


def test_home_opens_on_the_attention_list(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _seed_finding(settings, user_id)
    web.invalidate_catalog()
    for locale in LOCALES:
        page = _get(client, "/", locale)
        assert len(_h1s(page)) == 1, locale
        seen = _visible(page)
        # The heading is there for screen readers only; the caption folded.
        assert 'id="home-priorities-heading" class="visually-hidden"' in page
        assert _msg("dashboard.priority_heading", locale) not in seen
        assert _msg("dashboard.priority_note", locale) not in seen
        foot = page.split('class="an-home-priorities__foot"', 1)[1].split("</section>", 1)[0]
        assert _msg("dashboard.priority_note_summary", locale) in foot
        assert _msg("dashboard.priority_note", locale) in foot
        # The footer is the last row of the list box itself.
        priorities = page.split('class="dashboard-section an-home-priorities"', 1)[1].split("</section>", 1)[0]
        assert priorities.index("an-result-list") < priorities.index("an-home-priorities__foot")
        # The status tiles are links; no caption has to say so.
        assert 'class="an-stat-tile" href="' in page
        assert "Select a count to open" not in page and "Натисніть на число" not in page


def test_home_area_cards_open_from_their_header(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    web.invalidate_catalog()
    for locale in LOCALES:
        page = _get(client, "/", locale)
        seen = _visible(page)
        assert _msg("experience.overview", locale) not in seen
        assert _msg("experience.directory", locale) not in re.sub(r'aria-label="[^"]*"', "", seen)
        assert 'id="px-overview-heading" class="visually-hidden"' in page
        assert 'id="px-directory-heading" class="visually-hidden"' in page
        assert "px-record-count" not in page
        cards = re.findall(r'<article class="px-focus-card".*?</article>', page, re.S)
        assert cards, "the home page shows at least one area card"
        for card in cards:
            header = card.split("</header>", 1)[0]
            area = re.search(r'data-area="([^"]+)"', card).group(1)
            assert f'<a class="px-focus-open" href="/areas/{area}">{_msg("experience.open_short", locale)}' in header
            assert "<footer" not in card


def test_panels_open_on_counts_and_sort_in_one_row(tmp_path: Path):
    _, _, client = build(tmp_path)
    for locale in LOCALES:
        page = _get(client, "/panels", locale)
        assert _h1s(page) == ['<h1 id="panels-heading" class="visually-hidden">'], locale
        seen = _visible(page)
        assert _msg("panels.heading", locale) not in seen.split("an-index-disclosures")[0]
        assert "Results by test group" not in page and "Результати за групами аналізів" not in page
        head = page.split('<section class="an-panels-head"', 1)[1].split("</section>", 1)[0]
        for key in ("panels.totals_flagged", "panels.totals_overdue", "panels.sort_area", "panels.sort_attention"):
            assert _msg(key, locale) in head, key
        assert 'class="an-panels-head__count"' in head
        assert page.index("an-panels-head") < page.index("an-index-disclosures")


def test_vaccinations_open_on_the_add_button(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _seed_vaccinations(settings, user_id)
    for locale in LOCALES:
        page = _get(client, "/vaccinations", locale)
        assert _h1s(page) == ['<h1 id="vax-heading" class="visually-hidden">'], locale
        head = page.split('<section class="an-vax-head"', 1)[1].split("</section>", 1)[0]
        # The button takes the title's place: first thing in the band.
        assert head.index('data-vax-add') < head.index("an-totals")
        # «Worth asking about» is a jump to the gap analysis, not a tile.
        jump = re.search(r'<a class="an-vax-head__gaps" href="#vax-gaps">([^<]+)</a>', head)
        assert jump and jump.group(1).startswith(_msg("vax.gaps_jump", locale, count="").strip())
        assert 'id="vax-gaps"' in page
        tiles = re.findall(r"<dt>([^<]+)</dt><dd>(\d+)</dd>", head)
        assert all(int(value) for _, value in tiles), "a count of nothing is not a tile"
        assert _msg("vax.totals_doses", locale) in dict(tiles)
        seen = _visible(page)
        # The lead and the doses caption are gone from view; the grouping rule
        # is in the legend, and the gap analysis carries no disclaimer.
        assert '<h2 id="vax-doses" class="visually-hidden">' in page
        assert _msg("vax.doses_lead", locale) not in seen
        legend = page.split('<details class="an-vax-legend">', 1)[1].split("</details>", 1)[0]
        assert _msg("vax.doses_lead", locale) in legend
        gaps = page.split('id="vax-gaps"', 1)[1].split("</section>", 1)[0]
        assert _msg("vax.gaps_disclaimer", locale) not in gaps


def test_vaccinations_drop_a_zero_tile(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    _seed_vaccinations(settings, user_id)

    with connect(settings) as connection:
        connection.execute("UPDATE immunizations SET verification_status = 'verified' WHERE owner_user_id = ?", (user_id,))
    page = _get(client, "/vaccinations", "en")
    head = page.split('<section class="an-vax-head"', 1)[1].split("</section>", 1)[0]
    assert _msg("vax.totals_unchecked", "en") not in head


def test_devices_open_on_the_stat_band_and_cards(tmp_path: Path):
    _, _, client = build(tmp_path)
    for locale in LOCALES:
        page = _get(client, "/devices", locale)
        assert _h1s(page) == ['<h1 id="devices-heading" class="visually-hidden">'], locale
        seen = _visible(page)
        assert "Wearables &amp; connected health" not in page and "Носимі пристрої" not in page
        assert _msg("devices.lead_plain", locale) not in seen
        assert _msg("devices.latest_health", locale) not in seen
        # The band holds the stats and the area shortcuts, then the cards.
        band = page.split('<section class="an-device-head"', 1)[1].split("</section>", 1)[0]
        assert 'class="an-device-stats"' in band and 'class="px-area-nav"' in band
        # «Find all device metrics» sits at the foot of the grid, not above it.
        latest = page.split('class="dashboard-section an-device-latest"', 1)[1].split("</section>", 1)[0]
        assert latest.index("device-metric-grid") < latest.index('href="/metrics?q=device"')
        # The folded source explanation stays; the lead paragraph is gone.
        assert _msg("devices.lead_plain", locale) not in latest
        assert _msg("experience.source_policy_body", locale) in latest
