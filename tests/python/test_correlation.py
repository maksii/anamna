"""Correlations: the alignment rules, the coefficient, and the endpoint.

Almost all of this needs no database. `anamna.correlation` is pure — a
series is a list of `(day, value)` — which is deliberate: the parts that can
silently produce a confident wrong number are the trailing-window join and the
choice of *ranked* correlation, and both are checkable against arithmetic done
by hand.

The three facts these tests exist to protect:

* an averaging alignment anchors on the series with FEWER recorded days and
  averages the other one. Anchoring on the primary instead is what made the
  first version useless: asked for the 30-day mean of a lipid panel around each
  of 150 blood-pressure days, every window held one draw or none, and a page
  that should have read "cholesterol against the month of blood pressure before
  it" read "fewer than six days carry both measurements";
* the three-recorded-days minimum is a rule about the *mean*, so it constrains
  the averaged side and never the single anchor reading;
* the coefficient is Spearman, not Pearson. The fixture below is monotonic but
  not linear, so the two methods give different answers and only the ranked one
  gives the answer written here.
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from anamna.correlation import (
    MIN_PAIRS_EXPLORER,
    TRIVIAL_PAIRS,
    align_pairs,
    averaged_side,
    correlate,
    regression,
    rolling_mean_series,
    sample_evenly,
    strength,
    suggest,
)
from anamna.db import connect, migrate, utc_now
from anamna.ingest.pipeline import ensure_concept, ensure_vendor
from anamna.security import create_user
from anamna.web.app import create_app

from test_web_security import PASSWORD, seed_patient, settings_for
from test_web_profile import login
from test_web_tracker import seed_days


def days(start: int, count: int) -> list[str]:
    return [f"2026-01-{day:02d}" for day in range(start, start + count)]


def series(values: list[float], start: int = 1) -> list[tuple[str, float]]:
    return list(zip(days(start, len(values)), values))


# --- alignment ---------------------------------------------------------------


def test_same_day_is_an_inner_join():
    primary = [("2026-01-01", 1.0), ("2026-01-02", 2.0), ("2026-01-03", 3.0)]
    companion = [("2026-01-02", 20.0), ("2026-01-03", 30.0), ("2026-01-09", 90.0)]
    assert align_pairs(primary, companion, "same_day") == [
        ("2026-01-02", 2.0, 20.0),
        ("2026-01-03", 3.0, 30.0),
    ]


def test_prev_day_reads_the_companion_from_the_day_before():
    """Last night's sleep against this morning's resting heart rate."""
    primary = [("2026-01-02", 2.0), ("2026-01-03", 3.0)]
    companion = [("2026-01-01", 10.0), ("2026-01-02", 20.0)]
    assert align_pairs(primary, companion, "prev_day") == [
        ("2026-01-02", 2.0, 10.0),
        ("2026-01-03", 3.0, 20.0),
    ]
    # The same input under same_day matches only where the dates coincide, so
    # the two alignments cannot be quietly returning the same thing.
    assert align_pairs(primary, companion, "same_day") == [("2026-01-02", 2.0, 20.0)]
    # Neither day-join averages anything.
    assert averaged_side(primary, companion, "same_day") is None
    assert averaged_side(primary, companion, "prev_day") is None


def test_the_sparser_series_anchors_and_the_denser_one_is_averaged():
    sparse = [("2026-01-10", 5.0)]
    dense = series([float(value) for value in range(1, 11)])
    assert averaged_side(sparse, dense, "avg7") == "companion"
    assert averaged_side(dense, sparse, "avg7") == "primary"
    # A tie keeps the page's own readings as the fixed points.
    assert averaged_side(dense, dense, "avg7") == "companion"


def test_avg7_window_is_the_seven_days_ending_on_the_anchor():
    primary = [("2026-01-10", 100.0)]
    companion = [
        ("2026-01-03", 1000.0),  # d-7: outside the window
        ("2026-01-04", 1.0),  # d-6: the first day inside it
        ("2026-01-05", 2.0),
        ("2026-01-10", 3.0),  # the anchor's own day counts
    ]
    assert align_pairs(primary, companion, "avg7") == [("2026-01-10", 100.0, 2.0)]


def test_anchoring_flips_when_the_companion_is_the_sparser_side():
    """The lipid-panel case: one blood draw against a month of daily readings.

    Under the old rule this returned nothing at all — each of the ten dense
    days had at most one companion reading in its window, so the three-day
    minimum dropped every pair. Now the single draw anchors, the dense series
    is averaged around it, and the answer is one honest pair.
    """
    dense = series([float(value) for value in range(1, 11)])  # 2026-01-01..10
    sparse = [("2026-01-10", 42.0)]
    pairs = align_pairs(dense, sparse, "avg7")
    # Averaged over 2026-01-04..10, which is values 4..10.
    assert pairs == [("2026-01-10", 7.0, 42.0)]
    # Whichever side was averaged, the tuple is always
    # (day, primary_value, companion_value) — the caller plots in terms of the
    # page it is on and never has to ask which way round the arguments came.
    assert align_pairs(sparse, dense, "avg7") == [("2026-01-10", 42.0, 7.0)]


def test_the_three_day_minimum_constrains_the_averaged_side_only():
    anchor = [("2026-01-10", 100.0)]
    two_days = [("2026-01-09", 4.0), ("2026-01-10", 6.0)]
    # Two recorded days is not an average, so the pair is dropped.
    assert align_pairs(anchor, two_days, "avg7") == []
    # A third day inside the window is enough...
    assert align_pairs(anchor, [("2026-01-08", 2.0), *two_days], "avg7") == [
        ("2026-01-10", 100.0, 4.0)
    ]
    # ...and the single anchor reading is never held to that rule, whichever
    # side of the call it arrived on.
    dense = series([float(value) for value in range(1, 11)])
    assert len(align_pairs(dense, anchor, "avg7")) == 1
    assert len(align_pairs(anchor, dense, "avg7")) == 1


def test_avg30_window_is_thirty_days_ending_on_the_anchor():
    primary = [("2026-02-01", 5.0)]
    companion = [
        ("2026-01-02", 999.0),  # d-30: outside
        ("2026-01-03", 3.0),  # d-29: the first day inside
        ("2026-01-20", 6.0),
        ("2026-02-01", 9.0),
    ]
    assert align_pairs(primary, companion, "avg30") == [("2026-02-01", 5.0, 6.0)]


def test_an_unknown_alignment_is_refused_rather_than_guessed():
    try:
        align_pairs([("2026-01-01", 1.0)], [("2026-01-01", 1.0)], "weekly")
    except ValueError:
        return
    raise AssertionError("an unknown alignment must not silently fall back")


def test_rolling_mean_series_has_no_minimum_because_it_is_only_a_curve():
    source = [
        ("2026-01-01", 2.0),
        ("2026-01-02", 4.0),
        ("2026-01-05", 12.0),
        ("2026-01-20", 100.0),
    ]
    assert rolling_mean_series(source, 7) == [
        ("2026-01-01", 2.0),  # itself alone
        ("2026-01-02", 3.0),  # (2+4)/2
        ("2026-01-05", 6.0),  # (2+4+12)/3
        ("2026-01-20", 100.0),  # nothing else within seven days
    ]
    # One output point per input day, so a drawn curve never develops a hole
    # the reader has no explanation for.
    assert len(rolling_mean_series(source, 30)) == len(source)


# --- the coefficient ---------------------------------------------------------


def test_correlation_is_ranked_not_linear():
    """A monotonic but curved relationship, where the two methods disagree.

    Spearman by hand: ranks are 1..6 against 2,1,4,3,6,5, so d is ±1 six times
    and sum(d²) = 6.  rho = 1 - 6·6 / (6·(36-1)) = 1 - 36/210 = 0.828571…
    Pearson on the same numbers is 0.913, so a test that passed on 0.9-ish
    would not tell the two apart — this one does.
    """
    pairs = [
        (day, float(index + 1), value)
        for index, (day, value) in enumerate(
            zip(days(1, 6), [10.0, 8.0, 30.0, 25.0, 60.0, 55.0])
        )
    ]
    summary = correlate(pairs)
    assert summary["n"] == 6
    assert math.isclose(float(summary["r"]), 1 - 36 / 210, abs_tol=1e-12)
    assert summary["strength"] == "strong"
    assert summary["direction"] == "positive"


def test_a_curve_that_only_ranking_can_see():
    """y = x²: perfectly monotonic, so Spearman is exactly 1 and Pearson is not."""
    pairs = [(day, float(n), float(n * n)) for day, n in zip(days(1, 5), range(1, 6))]
    assert correlate(pairs)["r"] == 1.0


def test_degenerate_input_has_no_coefficient_rather_than_a_zero():
    """`None` says "not measured"; 0.0 would claim "measured, no association"."""
    single = [("2026-01-01", 1.0, 2.0)]
    assert correlate([])["r"] is None
    assert correlate(single)["r"] is None
    flat = [(day, 5.0, float(index)) for index, day in enumerate(days(1, 6))]
    assert correlate(flat)["r"] is None
    assert correlate(flat)["n"] == 6, "the pair count is still true"
    assert regression(single) is None
    assert regression([]) is None


def test_regression_puts_the_companion_on_x_and_the_primary_on_y():
    # primary = 3·companion + 1, so the line the scatter draws is slope 3.
    pairs = [(day, 3.0 * n + 1.0, float(n)) for day, n in zip(days(1, 5), range(1, 6))]
    line = regression(pairs)
    assert math.isclose(line["slope"], 3.0, abs_tol=1e-9)
    assert math.isclose(line["intercept"], 1.0, abs_tol=1e-9)


def test_strength_bands_match_schober_at_every_edge():
    assert strength(0.0) == "negligible"
    assert strength(0.09) == "negligible"
    assert strength(0.10) == "weak"
    assert strength(0.39) == "weak"
    assert strength(0.40) == "moderate"
    assert strength(0.69) == "moderate"
    assert strength(0.70) == "strong"
    assert strength(0.89) == "strong"
    assert strength(0.90) == "very_strong"
    assert strength(1.0) == "very_strong"
    # The bands describe magnitude; an inverse association is judged the same.
    assert strength(-0.75) == "strong"
    assert strength(None) == "none"


# --- sampling ----------------------------------------------------------------


def test_sample_evenly_leaves_a_short_list_alone():
    points = series([float(index) for index in range(9)])
    assert sample_evenly(points, 400) is points


def test_sample_evenly_thins_and_keeps_both_ends():
    items = [(f"day-{index}", float(index), float(index)) for index in range(1000)]
    drawn = sample_evenly(items, 400)
    assert len(drawn) == 400
    assert drawn[0] is items[0]
    assert drawn[-1] is items[-1]
    # Evenly spaced, so the drawn cloud has the same spread as the full one --
    # bucket means would pull it towards the middle and read as a tighter,
    # stronger relationship than the data supports.
    steps = {round(drawn[index + 1][1] - drawn[index][1]) for index in range(399)}
    assert steps <= {2, 3}


# --- suggestions -------------------------------------------------------------


def test_suggest_skips_itself_and_the_pairs_that_are_arithmetic():
    assert frozenset(("device:steps", "device:walking_running_distance")) in TRIVIAL_PAIRS
    rising = series([float(n) for n in range(1, 11)])
    candidates = {
        "device:steps": rising,
        "device:walking_running_distance": rising,
        "device:resting_heart_rate": series([float(10 - n) for n in range(10)]),
    }
    found = suggest("device:steps", rising, candidates, "same_day")
    assert [item["id"] for item in found] == ["device:resting_heart_rate"]
    assert found[0]["r"] == -1.0
    assert found[0]["direction"] == "negative"
    # One comparison left after the trivial pair is skipped; ten independent days.
    assert found[0]["comparisons"] == 1 and found[0]["effective_n"] == 10


def test_suggest_applies_its_thresholds_and_ranks_by_magnitude():
    rising = series([float(n) for n in range(1, 11)])
    candidates = {
        # rho = -1: the strongest thing here, so it leads.
        "device:resting_heart_rate": series([float(10 - n) for n in range(10)]),
        # A permutation with sum(d²) = 150, so rho = 1 - 900/990 = 0.0909:
        # real, and below the 0.15 floor a suggestion has to clear.
        "device:blood_oxygen": series([3.0, 7.0, 1.0, 9.0, 6.0, 10.0, 2.0, 8.0, 4.0, 5.0]),
        # Strong, but only five days overlap -- too few to put forward.
        "device:body_weight": series([1.0, 2.0, 3.0, 4.0, 5.0]),
        # rho = 0.9394, second by magnitude.
        "device:sleep_duration": series([2.0, 1.0, 4.0, 3.0, 6.0, 5.0, 8.0, 7.0, 10.0, 9.0]),
    }
    assert math.isclose(
        float(correlate(align_pairs(rising, candidates["device:blood_oxygen"], "same_day"))["r"]),
        1 - 900 / 990,
        abs_tol=1e-12,
    )
    found = suggest("device:heart_rate_variability", rising, candidates, "same_day")
    assert [item["id"] for item in found] == [
        "device:resting_heart_rate",
        "device:sleep_duration",
    ]
    assert all(item["n"] == 10 for item in found)
    # Four comparisons (body weight included, though its five days are too few
    # to put forward). Sleep's rho of 0.9394 clears the chance level for ten
    # days across four companions, which is about 0.75.
    assert all(item["comparisons"] == 4 and item["effective_n"] == 10 for item in found)


# --- the endpoint ------------------------------------------------------------


def seed_lab(settings, user_id, patient_id, name, unit, readings):
    """A laboratory analyte with dated numeric results, as ingest would file it."""
    with connect(settings) as connection:
        vendor_id = ensure_vendor(connection, "Test Lab", None)
        connection.execute(
            """INSERT OR IGNORE INTO documents(
                   id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type,
                   extraction_strategy, classification_confidence, imported_at, status
               ) VALUES ('doc-lab', ?, ?, ?, 'lab.txt', 'lab.txt', 'text/plain', 1, 'lab', 1,
                         'Lab report', 'laboratory', 'native_text', 1, ?, 'final')""",
            (user_id, patient_id, vendor_id, utc_now()),
        )
        concept_id, _ = ensure_concept(connection, name, vendor_id, "numeric", unit)
        for index, (day, value) in enumerate(readings):
            connection.execute(
                """INSERT INTO observations(
                       id, owner_user_id, patient_id, document_id, page_number, concept_id,
                       raw_name, value_type, value_numeric, unit_raw, observed_at,
                       verification_status, extraction_method, confidence, evidence_text,
                       parser_version, created_at)
                   VALUES (?, ?, ?, 'doc-lab', 1, ?, ?, 'numeric', ?, ?, ?,
                           'extracted', 'test', 0.9, ?, 'test', ?)""",
                (
                    f"obs-{concept_id}-{index}", user_id, patient_id, concept_id, name,
                    value, unit, day, f"{name} {value} {unit}", utc_now(),
                ),
            )
    return concept_id


def build(tmp_path: Path):
    """A record with a dense wearable, a sparse analyte, and one barely there."""
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "corr@example.test", "Corr", PASSWORD)
    patient_id = seed_patient(settings, user_id, "Corr Patient")
    span = [f"2026-01-{day:02d}" for day in range(1, 31)]
    seed_days(
        settings, user_id, patient_id, "steps", "Daily steps", "device_activity", "steps", "sum",
        [(day, 4000.0 + index * 200) for index, day in enumerate(span)],
    )
    # Falls as steps rise, and not on a straight line.
    seed_days(
        settings, user_id, patient_id, "resting_heart_rate", "Resting heart rate",
        "device_recovery", "bpm", "average",
        [(day, 70.0 - (index ** 1.4) / 10) for index, day in enumerate(span)],
    )
    # Three days only: never enough for a coefficient, but drawable — the
    # serum-iron case in miniature, and the page must offer it.
    seed_days(
        settings, user_id, patient_id, "vo2_max", "Cardio fitness (VO₂ max)", "device_fitness",
        "mL/kg/min", "average", [(day, 42.0 + index) for index, day in enumerate(span[:3])],
    )
    # One day only: a dot with nothing to move against, below every floor.
    seed_days(
        settings, user_id, patient_id, "body_height", "Height", "device_body",
        "cm", "latest", [(span[0], 184.0)],
    )
    # Eight draws inside the wearable's span plus one from the year before, so
    # clipping has something to clip.
    ferritin = seed_lab(
        settings, user_id, patient_id, "Ferritin", "ng/mL",
        [("2025-06-01", 20.0)] + [(span[index * 3 + 3], 30.0 + index * 5) for index in range(8)],
    )
    # Four draws: drawable, but never enough for a coefficient.
    iron = seed_lab(
        settings, user_id, patient_id, "Iron", "µmol/L",
        [(span[index * 7 + 2], 12.0 + index) for index in range(4)],
    )
    return settings, ferritin, iron


def payload_for(client, **params):
    response = client.get("/api/correlation", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_endpoint_returns_the_documented_shape(tmp_path: Path):
    settings, _, _ = build(tmp_path)
    with TestClient(create_app(settings)) as client:
        login(client, "corr@example.test")
        payload = payload_for(
            client, a="device:steps", b="device:resting_heart_rate",
            align="same_day", range="all",
        )

    assert payload["align"] == "same_day"
    assert payload["range"] == "all"
    assert payload["period"] == {"from": "2026-01-01", "to": "2026-01-30"}
    assert payload["a"]["id"] == "device:steps"
    assert payload["a"]["name"] == "Daily steps"
    assert payload["a"]["smoothed"] is None, "a day join averages nothing"
    assert payload["a"]["series"][0] == {"day": "2026-01-01", "value": 4000.0}
    assert len(payload["a"]["series"]) == 30

    assert len(payload["companions"]) == 1
    companion = payload["companions"][0]
    assert companion["id"] == "device:resting_heart_rate"
    assert companion["unit"] == "bpm"
    assert companion["smoothed"] is None
    assert len(companion["series"]) == 30
    assert companion["n"] == 30
    # Steps rise every day and the heart rate falls every day, so the ranks are
    # exactly reversed however curved the fall is.
    assert companion["r"] == -1.0
    assert companion["strength"] == "very_strong"
    assert companion["direction"] == "negative"
    assert companion["insufficient"] is False
    assert companion["regression"]["slope"] < 0
    assert len(companion["pairs"]) == 30
    assert companion["pairs"][0] == {"day": "2026-01-01", "a": 4000.0, "b": 70.0}
    # Ukrainian has three plural forms, so the counted phrase is resolved on the
    # server and travels with the data rather than through the JS string table.
    assert companion["labels"]["days"] == "30 days"
    assert companion["labels"]["sampled"] is None


def test_endpoint_carries_up_to_four_companions_and_drops_the_scatter(tmp_path: Path):
    settings, ferritin, _ = build(tmp_path)
    with TestClient(create_app(settings)) as client:
        login(client, "corr@example.test")
        payload = payload_for(
            client, a="device:steps",
            b=["device:resting_heart_rate", "device:vo2_max", ferritin],
            align="same_day", range="all",
        )
    assert [companion["id"] for companion in payload["companions"]] == [
        "device:resting_heart_rate", "device:vo2_max", ferritin,
    ]
    # A scatter needs one pair of axes, so with several companions there is
    # nothing to plot one against and the fields say so rather than guessing.
    assert all(companion["pairs"] is None for companion in payload["companions"])
    assert all(companion["regression"] is None for companion in payload["companions"])
    # Every companion still carries a drawable series.
    assert all(companion["series"] for companion in payload["companions"])


def test_endpoint_refuses_what_it_cannot_answer(tmp_path: Path):
    settings, _, _ = build(tmp_path)
    with TestClient(create_app(settings)) as client:
        login(client, "corr@example.test")
        base = {"a": "device:steps", "b": "device:resting_heart_rate"}
        assert client.get("/api/correlation", params={**base, "align": "weekly"}).status_code == 400
        assert client.get("/api/correlation", params={**base, "range": "2y"}).status_code == 400
        # Five companions is past the point where four colours and four dash
        # patterns can keep them apart.
        assert client.get("/api/correlation", params={
            "a": "device:steps",
            "b": ["device:resting_heart_rate", "device:vo2_max", "device:steps",
                  "device:blood_oxygen", "device:sleep_duration"],
        }).status_code == 400
        # Collapsing a duplicate would return fewer series than the page asked
        # for, which reads as a metric having gone missing.
        assert client.get("/api/correlation", params={
            "a": "device:steps", "b": ["device:vo2_max", "device:vo2_max"],
        }).status_code == 400
        assert client.get("/api/correlation", params={
            "a": "device:steps", "b": ["device:vo2_max", "device:nothing-here"],
        }).status_code == 404
        # A series against itself is r=1.0 by construction — a fabricated
        # "very strong" association in the shape of a real finding.
        assert client.get("/api/correlation", params={
            "a": "device:steps", "b": ["device:steps", "device:vo2_max"],
        }).status_code == 400


def test_guest_links_may_read_the_correlation_api():
    """The explorer renders on guest-visible metric pages; without this prefix
    every control on it answers 403 with a misleading connection error."""
    from anamna.web.app import GUEST_ALLOWED_PREFIXES

    assert "/api/correlation" in GUEST_ALLOWED_PREFIXES


def test_a_hostile_metric_name_cannot_break_out_of_the_boot_payload(tmp_path: Path):
    """Metric names come from parsed documents; the boot payload is serialized
    with |tojson precisely so a name carrying '</script>' stays inert."""
    settings, _, _ = build(tmp_path)
    with connect(settings) as db:
        user_id = db.execute("SELECT id FROM users").fetchone()[0]
        patient_id = db.execute("SELECT id FROM patients").fetchone()[0]
    hostile = "</script><script>alert(9)</script>"
    seed_days(
        settings, user_id, patient_id, "hostile_metric", hostile, "device_activity",
        "steps", "sum", [(f"2026-01-{day:02d}", float(day)) for day in range(1, 12)],
    )
    with TestClient(create_app(settings)) as client:
        login(client, "corr@example.test")
        page = client.get("/devices/metrics/hostile_metric").text
    assert 'id="corr-data"' in page  # the panel rendered
    assert hostile not in page  # nowhere raw — escaped in markup and payload alike


def test_a_companion_it_cannot_measure_is_still_drawn(tmp_path: Path):
    """Four iron results over a month of steps: no coefficient, but a chart.

    Suppressing the whole chart on `insufficient` was the loudest complaint
    about the first version — seeing four results laid over the wearable is
    worth something even when no number can honestly be put on it.
    """
    settings, _, iron = build(tmp_path)
    with TestClient(create_app(settings)) as client:
        login(client, "corr@example.test")
        payload = payload_for(client, a="device:steps", b=iron, align="avg30", range="all")
    companion = payload["companions"][0]
    assert companion["n"] <= 4 < MIN_PAIRS_EXPLORER
    assert companion["insufficient"] is True
    # No coefficient is reported at all, rather than one the reader would have
    # to know to distrust.
    assert companion["r"] is None and companion["strength"] == "none"
    assert companion["regression"] is None
    # Both sides are present and drawable, which is the entire point.
    assert len(companion["series"]) == 4
    assert len(payload["a"]["series"]) == 30
    # Iron is the sparser side, so it anchors and the wearable is averaged --
    # which is what makes the pairing possible at all.
    assert payload["a"]["smoothed"] == "avg30"
    assert companion["smoothed"] is None


def test_companion_series_is_clipped_to_the_primary_span(tmp_path: Path):
    """A decade of history must not stretch the axis past the drawn period."""
    settings, ferritin, _ = build(tmp_path)
    with TestClient(create_app(settings)) as client:
        login(client, "corr@example.test")
        payload = payload_for(client, a="device:steps", b=ferritin, align="avg30", range="all")
    period = payload["period"]
    drawn = [point["day"] for point in payload["companions"][0]["series"]]
    assert drawn, "the analyte still has readings inside the span"
    assert all(period["from"] <= day <= period["to"] for day in drawn)
    assert "2025-06-01" not in drawn


def test_endpoint_trims_the_range_from_the_series_own_newest_day(tmp_path: Path):
    """Counted back from the last recorded day, never from today."""
    settings, _, _ = build(tmp_path)
    with TestClient(create_app(settings)) as client:
        login(client, "corr@example.test")
        payload = payload_for(
            client, a="device:steps", b="device:resting_heart_rate", range="90",
        )
    # The record ends in January 2026; ninety days back from *today* would find
    # nothing at all, and this window still holds every one of its thirty days.
    assert payload["companions"][0]["n"] == 30


def test_a_device_page_suggests_laboratory_analytes_too(tmp_path: Path):
    """The complaint that started the revision: a wearable page offering only
    other wearable metrics, when the question was whether the month before a
    blood test shows up in it."""
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "lab@example.test", "Lab", PASSWORD)
    patient_id = seed_patient(settings, user_id, "Lab Patient")
    # A year of steps climbing every day, so every trailing month climbs too.
    span = [(date(2026, 1, 1) + timedelta(days=index)).isoformat() for index in range(240)]
    seed_days(
        settings, user_id, patient_id, "steps", "Daily steps", "device_activity", "steps", "sum",
        [(day, 4000.0 + index * 20.0) for index, day in enumerate(span)],
    )
    # Eight draws a month apart: each one is an independent day for the gate,
    # and the analyte rises with them, so the rank correlation is exact.
    ferritin = seed_lab(
        settings, user_id, patient_id, "Ferritin", "ng/mL",
        [(span[3 + 30 * index], 30.0 + index * 5) for index in range(8)],
    )
    with TestClient(create_app(settings)) as client:
        login(client, "lab@example.test")
        page = client.get("/devices/metrics/steps").text
    card = re.search(
        rf'data-corr-pick="{ferritin}"\s+data-corr-align="(\w+)" data-corr-period="(\w+)"', page
    )
    assert card, "a laboratory analyte must be suggestible from a device page"
    # Averaged, because the wearable is the denser side, and over the whole
    # record, because a year of a device series holds two or three blood draws.
    assert card.groups() == ("avg30", "all")


def test_the_detail_page_carries_the_section_and_opens_on_a_suggestion(tmp_path: Path):
    settings, _, _ = build(tmp_path)
    with TestClient(create_app(settings)) as client:
        login(client, "corr@example.test")
        page = client.get("/devices/metrics/steps").text
    assert 'class="panel an-corr' in page
    assert "How this relates to your other measurements" in page
    # The picker is a filterable checkbox list, not a dropdown of eighty items.
    assert 'id="corr-filter"' in page and 'type="checkbox"' in page
    # Rendered from the server's own payload, so the panel never opens blank.
    assert '"companions":' in page and '"series":' in page
    # The strength wording is cited on the page itself, not only in the code.
    assert "10.1213/ANE.0000000000002864" in page
    # Three recorded days is drawable against a dense companion — that is the
    # serum-iron scenario this feature exists for — so the section renders.
    # One recorded day is a dot with nothing to move against, so it does not.
    with TestClient(create_app(settings)) as client:
        login(client, "corr@example.test")
        assert 'class="panel an-corr' in client.get("/devices/metrics/vo2_max").text
        assert 'class="panel an-corr' not in client.get("/devices/metrics/body_height").text
