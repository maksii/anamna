"""The other results of a test group sit in the hero, one press from the top."""
from __future__ import annotations

from test_web_panels import build


def test_read_together_is_in_the_hero_above_the_chart(tmp_path):
    # build() seeds LDL and HDL; LDL's lipid panel has the rest as siblings.
    _, _, client = build(tmp_path)
    page = client.get("/metrics/ldl-cholesterol")
    assert page.status_code == 200
    text = page.text
    assert 'id="read-together"' in text
    assert text.index('id="read-together"') < text.index('id="reading-trend"')
    # Inside the hero section, not after it.
    hero_start = text.index('<section class="metric-detail-hero')
    hero_end = text.index("</section>", hero_start)
    assert hero_start < text.index('id="read-together"') < hero_end
    # The old folded container is gone.
    assert 'class="panel an-fold an-siblings"' not in text
    # At least one sibling link sits between the disclosure and the chart.
    together = text[text.index('id="read-together"'):text.index('id="reading-trend"')]
    assert 'href="/metrics/' in together
