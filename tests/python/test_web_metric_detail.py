"""Metric detail page: the chart leads, scaled to the data, each point judged."""
from __future__ import annotations

import pytest

from anamna.web import app as web


def test_value_axis_follows_the_readings_and_only_a_near_band():
    # Haemoglobin 146-159 under a 130-170 band: both bounds are far, so the
    # axis is the data plus padding, not the band.
    low, high = web.fit_domain([146, 152, 159], [130, 170])
    assert 140 < low < 146 and 159 < high < 165
    # A bound within half the spread of the data still widens the axis.
    low, high = web.fit_domain([4.1, 5.9], [3.4, None])
    assert low < 3.4
    # Never forced to zero, never negative for a never-negative value.
    low, _ = web.fit_domain([2.7, 5.5], [0.0, 3.0])
    assert low > 2.0
    assert web.fit_domain([0.1, 0.2], [])[0] >= 0
    # A flat series still gets a drawable axis.
    low, high = web.fit_domain([5.0, 5.0], [])
    assert low < 5.0 < high


def test_rounding_never_crosses_the_bound_it_is_printed_beside():
    with_band = {"low": 12.0, "high": 20.0}
    assert web.precise_at_edges(11.68, "12", with_band) == "11.7"
    assert web.precise_at_edges(6.95, "7", {"target_low": 7.0}) == "6.95"
    # Nothing crossed: the printed precision stands.
    assert web.precise_at_edges(14.2, "14", with_band) == "14"
    assert web.precise_at_edges(None, "Negative", with_band) == "Negative"
    assert web.precise_at_edges(12.0, "12", with_band) == "12"


class Rule(dict):
    def keys(self):  # sqlite3.Row-like
        return super().keys()


def test_rule_text_never_prints_english_on_a_ukrainian_page(monkeypatch):
    rule = Rule(label="Severe anaemia (WHO)", label_uk="Тяжка анемія (ВООЗ)",
                notes="The strip where WHO and NORIP disagree.", reference_set="WHO thresholds")
    monkeypatch.setattr(web, "get_locale", lambda: "en")
    assert web.rule_text(rule, "label") == "Severe anaemia (WHO)"
    assert web.rule_text(rule, "notes") == "The strip where WHO and NORIP disagree."
    monkeypatch.setattr(web, "get_locale", lambda: "uk")
    assert web.rule_text(rule, "label") == "Тяжка анемія (ВООЗ)"
    # Untranslated English is withheld, not shown.
    assert web.rule_text(rule, "notes") is None
    assert web.rule_text(rule, "reference_set") is None
    rule["notes_uk"] = "Смуга, де ВООЗ і NORIP розходяться."
    assert web.rule_text(rule, "notes") == "Смуга, де ВООЗ і NORIP розходяться."


def _metric_fixture(tmp_path):
    from anamna.db import connect, utc_now
    from anamna.ingest.pipeline import ensure_concept
    from test_web_panels import build

    settings, user_id, client = build(tmp_path)
    reference = "Діти 6-12 років: 24-54 Дорослі: 20-40"
    with connect(settings) as db:
        concept, _ = ensure_concept(db, "Lymphocytes", None)
        single, _ = ensure_concept(db, "Zeta single marker", None)
        rows = [
            ("lymph-0", concept, "2026-08-04", 43),
            ("lymph-1", concept, "2002-08-04", 43),
            ("single-0", single, "2026-08-04", 3.1),
        ]
        for row_id, concept_id, day, value in rows:
            db.execute("""INSERT INTO observations(
                id,owner_user_id,patient_id,document_id,page_number,concept_id,raw_name,
                value_type,value_numeric,unit_raw,observed_at,vendor_reference_text,
                verification_status,extraction_method,confidence,evidence_text,parser_version,created_at)
                VALUES (?,?,?,'doc-1',1,?,'Lymphocytes','numeric',?,'%',?,?,'extracted','test',0.9,'fixture','test',?)""",
                (row_id, user_id, f"patient-{user_id}", concept_id, value, day, reference, utc_now()))
    web.invalidate_catalog()
    return client, concept, single


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_chart_leads_points_are_judged_and_the_rest_is_folded(tmp_path, locale):
    client, concept, single = _metric_fixture(tmp_path)
    client.cookies.set("anamna_lang", locale)
    page = client.get(f"/metrics/{concept}")
    assert page.status_code == 200
    points = page.context["chart_points"]
    # Judged by evaluate() at the age each sample was taken: 43 % at ten
    # years old is inside the child band, at 34 it is above the adult one.
    assert [p["state"] for p in points] == ["in", "out"]
    assert all(p["verdict_label"] for p in points)
    text = page.text
    # The chart comes straight after the hero, then every result; guidance
    # follows, folded. "What this measures" lives in the hero itself.
    assert text.index('id="reading-trend"') < text.index('id="reading-history"') < text.index('id="reading-guidance"')
    assert '<details class="panel an-fold official-guidance">' in text
    hero = text[text.index('<section class="metric-detail-hero'):]
    assert 'class="an-verdict-details an-metric-about"' in hero[:hero.index("</section>")]
    assert 'class="px-detail-nav"' not in text and "guidance-badge" not in text
    assert "metric-context-panel" not in text and 'class="chart-help"' not in text
    assert "Source aliases remain attached" not in text and "Псевдоніми джерела" not in text
    # The "vs <date>" caption is printed once, not again in the chip's hidden text.
    since = page.context["trend"]["since_text"] if page.context["trend"] else ""
    if since:
        assert text.count(since) == 1
    one = client.get(f"/metrics/{single}").text
    assert ("One measurement so far" if locale == "en" else "Поки що одне вимірювання") in one


def test_hero_reads_top_to_bottom_with_details_at_full_width(tmp_path):
    # The owner's complaint: name stranded at the foot of an empty left column,
    # details squeezed into a 340 px right column. The name now leads, the value
    # sits in the same head row, and the bar and details follow as siblings of
    # that row -- never nested in a narrow column wrapper.
    client, concept, _ = _metric_fixture(tmp_path)
    text = client.get(f"/metrics/{concept}").text
    hero = text[text.index('<section class="metric-detail-hero an-metric-hero"'):]
    hero = hero[:hero.index("</section>")]
    assert hero.index("<h1>") < hero.index('class="an-metric-hero__value"')
    head = hero[hero.index('class="an-metric-hero__head"'):hero.index('class="an-metric-hero__reading"')]
    # The head closes before the reading block opens: the slice starts after the
    # head's own "<div" and ends on the reading's, so opens and closes balance.
    assert head.count("<div") == head.count("</div>")
    assert "an-range-bar" not in head and "an-verdict-details" not in head
    reading = hero[hero.index('class="an-metric-hero__reading"'):]
    assert "an-range-bar" in reading and '<details class="an-verdict-details"' in reading
    assert "latest-reading" not in hero


def test_printed_reference_numbers_follow_the_locale(monkeypatch):
    printed = "Жінки: ризик відсутній: >1.68 Пакет №4.12 0.0"
    monkeypatch.setattr(web, "get_locale", lambda: "en")
    assert web.localized_reference(printed) == printed
    from anamna import i18n

    monkeypatch.setattr(web, "get_locale", lambda: "uk")
    token = i18n._locale.set("uk")  # format_number_localized reads the request locale
    try:
        shown = web.localized_reference(printed)
    finally:
        i18n._locale.reset(token)
    assert ">1,68" in shown and "№4.12" in shown and "1.68" not in shown


def test_a_range_that_does_not_describe_the_patient_is_withheld_under_a_verdict(tmp_path):
    from anamna.db import connect, utc_now
    from test_web_panels import build

    settings, user_id, client = build(tmp_path)
    with connect(settings) as db:
        db.execute("""INSERT INTO observations(
            id,owner_user_id,patient_id,document_id,page_number,concept_id,raw_name,
            value_type,value_numeric,unit_raw,observed_at,vendor_reference_text,
            verification_status,extraction_method,confidence,evidence_text,parser_version,created_at)
            VALUES ('hb-1',?,?,'doc-1',1,'hemoglobin','Гемоглобін','numeric',156,'g/L','2016-07-19',
                    'Жінки: 120-140','extracted','test',0.9,'fixture','test',?)""",
            (user_id, f"patient-{user_id}", utc_now()))
    web.invalidate_catalog()
    page = client.get("/metrics/hemoglobin")
    assert page.status_code == 200
    row = next(item for item in page.context["values"] if item["id"] == "hb-1")
    # A woman's range under a male patient's value that the curated interval
    # judged: the verdict names its interval and the lab line is withheld.
    assert row["judged"] and row["verdict"]["authority"] == "curated"
    assert row["hide_lab"] and row["judged_text"]
    table = page.text.split('id="reading-history"', 1)[1].split("</table>", 1)[0]
    assert "Not applicable to this age or sex" not in table


def test_correlation_suggestions_are_memoised_until_the_record_changes(tmp_path, monkeypatch):
    client, concept, _ = _metric_fixture(tmp_path)
    calls = []
    real = web._build_correlation_context
    monkeypatch.setattr(web, "_build_correlation_context", lambda *a: calls.append(a) or real(*a))
    client.get(f"/metrics/{concept}")
    client.get(f"/metrics/{concept}")
    assert len(calls) == 1
    web.invalidate_catalog()
    client.get(f"/metrics/{concept}")
    assert len(calls) == 2
