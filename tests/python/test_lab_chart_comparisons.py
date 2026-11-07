"""Chart comparisons use the original report at the patient's sampling age."""
from copy import deepcopy

import pytest

from anamna.web.app import _chart_payload, _in_preferred_unit, _original_comparison


def reading(day="2026-08-04", value=43, reference="Дорослі: 20-40", **extra):
    return {
        "id": day, "document_id": "fixture", "concept_id": "lymphocytes",
        "observed_at": day, "value_numeric": value, "unit_raw": "%", "preferred_unit": "%",
        "vendor": "Test Lab", "vendor_reference_text": reference,
        "vendor_reference_low": None, "vendor_reference_high": None,
        "vendor_interpretation": None, "evidence_count": 1, **extra,
    }


def test_chart_recovers_each_original_interval_at_sampling_age():
    reference = "Діти 6-12 років: 24-54 Дорослі: 20-40"
    rows = [reading(reference=reference), reading("2002-08-04", reference=reference)]
    points = _chart_payload(rows, "%", date_of_birth="1990-03-14", sex="male")
    assert [(p["reference_low"], p["reference_high"], p["status"]) for p in points] == [
        (24, 54, "within_vendor_range"), (20, 40, "high"),
    ]
    assert all(p["comparison_basis"] == "original_range" for p in points)
    assert all(row["vendor_reference_text"] == reference for row in rows)
    assert all(row["vendor_interpretation"] is None for row in rows)


@pytest.mark.parametrize(("reference", "birthday", "sex"), [
    ("Дорослі: 20-40", None, "male"),
    ("Дорослі: 20-40", "2020-02-19", "male"),
    ("Жінки: 20-40", "1990-03-14", "male"),
    ("Діти 6-12 років: 24-54", "1990-03-14", "male"),
    (None, "1990-03-14", "male"),
])
def test_unknown_or_inapplicable_reference_stays_uncompared(reference, birthday, sex):
    point = _chart_payload([reading(reference=reference)], "%", date_of_birth=birthday, sex=sex)[0]
    assert point["status"] == "information"
    assert point["comparison_basis"] == "none"
    assert point["reference_label"] is None


def test_explicit_provider_flag_is_retained_even_when_numeric_interval_disagrees():
    row = reading(value=43, vendor_interpretation="within_vendor_range")
    point = _chart_payload([row], "%", date_of_birth="1990-03-14", sex="male")[0]
    assert point["status"] == "within_vendor_range"
    assert point["comparison_basis"] == "stored_flag"
    assert (point["reference_low"], point["reference_high"]) == (20, 40)
    assert _original_comparison(row, date_of_birth="1990-03-14", sex="male")["status"] == point["status"]
    assert point["comparison_label"]


def test_text_only_history_and_undated_age_qualified_results_are_not_inferred():
    for row in (reading(value=None, value_text="not detected"), reading(day=None)):
        comparison = _original_comparison(row, date_of_birth="1990-03-14", sex="male")
        assert comparison["status"] == "information"
        assert comparison["comparison_basis"] == "none"


@pytest.mark.parametrize("numeric_bounds", [False, True])
def test_recovered_and_stored_intervals_travel_with_converted_values(numeric_bounds):
    row = reading(value=37, reference="Дорослі: 32-36", concept_id="mean-corpuscular-hemoglobin-concentration",
                  unit_raw="g/dL", preferred_unit="g/L",
                  vendor_reference_low=32 if numeric_bounds else None,
                  vendor_reference_high=36 if numeric_bounds else None)
    original = deepcopy(row)
    converted = _in_preferred_unit(row)
    point = _chart_payload([converted], "g/L", date_of_birth="1990-03-14", sex="male")[0]
    assert point["value"] == 370
    assert (point["reference_low"], point["reference_high"]) == (320, 360)
    assert point["status"] == "high"
    history = _original_comparison(converted, date_of_birth="1990-03-14", sex="male")
    assert history["reference_text"] == point["reference_text"]
    assert history["status"] == point["status"]
    assert row == original


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_html_and_api_recover_original_flags_with_matching_demographic_context(tmp_path, locale):
    from anamna.db import connect, utc_now
    from anamna.ingest.pipeline import ensure_concept
    from anamna.web import app as web
    from test_web_panels import build

    settings, user_id, client = build(tmp_path)
    reference = "Діти 6-12 років: 24-54 Дорослі: 20-40"
    with connect(settings) as db:
        concept, _ = ensure_concept(db, "Lymphocytes", None)
        for index, day in enumerate(("2026-08-04", "2002-08-04")):
            db.execute("""INSERT INTO observations(
                id,owner_user_id,patient_id,document_id,page_number,concept_id,raw_name,
                value_type,value_numeric,unit_raw,observed_at,vendor_reference_text,
                verification_status,extraction_method,confidence,evidence_text,parser_version,created_at)
                VALUES (?,?,?,'doc-1',1,?,'Lymphocytes','numeric',43,'%',?,?,'extracted','test',0.9,'fixture','test',?)""",
                (f"lymph-{index}", user_id, f"patient-{user_id}", concept, day, reference, utc_now()))
    web.invalidate_catalog()
    client.cookies.set("anamna_lang", locale)
    page = client.get(f"/metrics/{concept}")
    assert page.status_code == 200
    points = page.context["chart_points"]
    assert [p["status"] for p in points] == ["within_vendor_range", "high"]
    assert page.context["verdict"]["interpretation"] == "high"
    assert page.context["verdict"]["authority"] == "vendor"
    assert [p["reference_high"] for p in points] == [54, 40]
    assert client.get(f"/api/metrics/{concept}").json() == points
    history = page.context["values"]
    for item in history:
        point = next(p for p in points if p["id"] == item["id"])
        assert item["display_status"] == point["status_label"]
        assert item["display_reference"] == point["reference_text"]
        assert item["display_comparison"]["status"] == point["status"]
        assert item["vendor_interpretation"] is None
    table = page.text.split('id="reading-history"', 1)[1].split('</table>', 1)[0]
    assert 'class="metric-state high"' in table
    assert ("Compared with the original interval" if locale == "en" else "Порівняно з інтервалом з оригіналу") in table
    # The chart's caption about per-point colouring was removed at the owner's
    # request; each point's own verdict still rides in its tooltip and row.
    assert ("its own verdict" if locale == "en" else "власною оцінкою") not in page.text
    with connect(settings) as db:
        stored = db.execute("SELECT vendor_reference_text,vendor_reference_low,vendor_reference_high,vendor_interpretation FROM observations WHERE id LIKE 'lymph-%'").fetchall()
    assert all(tuple(row) == (reference, None, None, None) for row in stored)
