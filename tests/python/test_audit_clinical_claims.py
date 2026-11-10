"""Claims the pages make without being asked, each checked against the rule
that keeps it honest: a correlation put forward as a suggestion, a planner
test marked as needing only one sample, and the warfarin dosing panel.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from anamna import genetics, testplan_special
from anamna.correlation import _critical_r, _independent_pairs, align_pairs, correlate, suggest

GENETIC = ("Генетичні дослідження",)


def days(count: int) -> list[str]:
    start = date(2026, 1, 1)
    return [(start + timedelta(days=index)).isoformat() for index in range(count)]


def series_of(values: list[float]) -> list[tuple[str, float]]:
    return list(zip(days(len(values)), values))


def pairs_on(day_numbers: list[int]) -> list[tuple[str, float, float]]:
    """Pairs on the given day offsets from 2026-01-01; the values do not matter here."""
    start = date(2026, 1, 1)
    return [((start + timedelta(days=number)).isoformat(), 1.0, 1.0) for number in day_numbers]


def item(name: str, **extra) -> dict:
    return {"id": name, "name": name, "groups": list(GENETIC), **extra}


# --- how much chance can explain ---------------------------------------------


def test_the_chance_level_falls_with_more_days_and_rises_with_companions_tried():
    assert _critical_r(8, 1) > 0.7
    assert 0.15 < _critical_r(100, 1) < 0.25
    assert _critical_r(100, 20) > _critical_r(100, 1)
    assert _critical_r(3, 1) == 1.0


# --- suggestions ---------------------------------------------------------------


def test_a_short_series_is_not_suggested_even_when_perfectly_correlated():
    """Seven pairs is under the minimum of eight, whatever their correlation."""
    ramp = [float(n) for n in range(7)]
    found = suggest("test:primary", series_of(ramp), {"test:companion": series_of(ramp)}, "same_day")
    assert found == []


def test_ten_daily_pairs_that_are_perfectly_correlated_are_suggested():
    """|r| = 1 clears the chance level for ten days against one companion."""
    ramp = [float(n) for n in range(10)]
    found = suggest("test:primary", series_of(ramp), {"test:companion": series_of(ramp)}, "same_day")
    assert [item["id"] for item in found] == ["test:companion"]
    assert math.isclose(float(found[0]["r"]), 1.0, abs_tol=1e-12)
    assert found[0]["effective_n"] == 10
    assert found[0]["comparisons"] == 1


def test_a_long_perfectly_correlated_series_is_suggested_with_its_bar_reported():
    ramp = [float(n) for n in range(60)]
    found = suggest("test:primary", series_of(ramp), {"test:companion": series_of(ramp)}, "same_day")
    assert [item["id"] for item in found] == ["test:companion"]
    assert math.isclose(float(found[0]["r"]), 1.0, abs_tol=1e-12)
    assert found[0]["comparisons"] == 1
    assert found[0]["effective_n"] == 60


def test_a_shuffled_companion_over_sixty_days_is_not_suggested():
    ramp = [float(n) for n in range(60)]
    shuffled = ramp[:]
    random.Random(7).shuffle(shuffled)
    found = suggest("test:primary", series_of(ramp), {"test:companion": series_of(shuffled)}, "same_day")
    assert found == []


def test_a_trailing_seven_day_mean_counts_its_independent_days_not_its_pairs():
    """Sixty days averaged over seven leave 58 pairs, one per anchor from the
    third day on. Anchors a week apart share no days, so the independent count
    is 9 (days 2, 9, ..., 58). The rising pair then has to clear the chance
    level for nine days, and it does."""
    ramp = [float(n) for n in range(60)]
    pairs = align_pairs(series_of(ramp), series_of(ramp), "avg7")
    assert len(pairs) == 58
    assert _independent_pairs(pairs, 7) == 9
    summary = correlate(pairs)
    assert abs(float(summary["r"])) >= _critical_r(9, 1)
    found = suggest("test:primary", series_of(ramp), {"test:companion": series_of(ramp)}, "avg7")
    assert [item["id"] for item in found] == ["test:companion"]
    assert found[0]["effective_n"] == 9
    assert found[0]["comparisons"] == 1


def test_eight_monthly_anchors_under_a_thirty_day_mean_are_eight_independent_pairs():
    """Eight draws two months apart, each averaged over its own month of a
    steadily rising daily series. No window reaches another anchor, so all
    eight count, and the monotonic relation clears the chance level for eight."""
    companion = series_of([float(n) for n in range(481)])
    anchors = [(day, float(index + 1)) for index, day in enumerate(days(481)[60::60])]
    assert len(anchors) == 8
    found = suggest("test:primary", anchors, {"test:companion": companion}, "avg30")
    assert [item["id"] for item in found] == ["test:companion"]
    assert found[0]["effective_n"] == 8
    assert found[0]["n"] == 8
    assert math.isclose(float(found[0]["r"]), 1.0, abs_tol=1e-12)


def test_the_explorer_view_shows_a_weak_pair_that_the_gate_refuses():
    """Ranks 1..10 against each other's blocks reversed: sum(d²) = 114, so
    rho = 1 - 6·114/990 = 51/165 = 0.309. Real, above the 0.15 floor, and
    below the chance level for ten days, so only the ungated call shows it."""
    ramp = [float(n) for n in range(10)]
    weak = [7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 9.0, 8.0, 10.0]
    candidates = {"test:companion": series_of(weak)}
    shown = suggest(
        "test:primary", series_of(ramp), candidates, "same_day", require_significance=False
    )
    assert [item["id"] for item in shown] == ["test:companion"]
    assert math.isclose(float(shown[0]["r"]), 51 / 165, abs_tol=1e-12)
    assert suggest("test:primary", series_of(ramp), candidates, "same_day") == []


# --- independent days ----------------------------------------------------------------


def test_independent_pairs_of_a_daily_series_count_one_per_window():
    daily = pairs_on(list(range(60)))
    assert _independent_pairs(daily, 7) == 9  # days 0, 7, ..., 56
    assert _independent_pairs(daily, 1) == 60


def test_independent_pairs_of_sparse_anchors_count_only_those_a_window_apart():
    # 0 counts; 10 and 20 share its window; 35, 70, 100 and 130 each sit at
    # least thirty days from the one before; 131 shares 130's window.
    assert _independent_pairs(pairs_on([0, 10, 20, 35, 70, 100, 130, 131]), 30) == 5
    assert _independent_pairs(pairs_on([0, 60, 120, 180, 240, 300, 360, 420]), 30) == 8


def test_independent_pairs_with_no_window_is_every_pair_and_none_is_zero():
    assert _independent_pairs(pairs_on([0, 1, 2, 3, 4]), 1) == 5
    assert _independent_pairs([], 30) == 0


# --- once is enough ----------------------------------------------------------------


def test_lipoprotein_a_is_a_blood_level_a_doctor_may_repeat():
    entry = testplan_special.BY_ID["lipoprotein-a"]
    assert entry.once is True
    assert entry.once_kind == "lifetime_level"


def test_every_genetic_entry_is_dna_that_never_changes():
    genes = [entry for entry in testplan_special.ENTRIES if entry.id.startswith("gen-")]
    assert genes
    assert all(entry.once_kind == "dna" for entry in genes)


# --- the warfarin dosing panel ----------------------------------------------------


def test_warfarin_dosing_needs_both_genes_in_either_order():
    assert "sp:gen-warfarin" not in testplan_special.matches(item("Генетика варфарину: VKORC1"))
    assert "sp:gen-warfarin" in testplan_special.matches(item("Чутливість до варфарину (CYP2C9, VKORC1)"))
    assert "sp:gen-warfarin" in testplan_special.matches(item("Чутливість до варфарину (VKORC1, CYP2C9)"))


def test_a_vkorc1_variant_listed_in_a_description_is_not_the_dosing_panel():
    vkorc1_only = item("Генетика варфарину: VKORC1",
                       description="rs9923231 (VKORC1 -1639G>A), rs8050894, rs7294")
    assert "sp:gen-warfarin" not in testplan_special.matches(vkorc1_only)


# --- inherited or acquired ----------------------------------------------------------


def test_an_inherited_gene_result_with_a_known_test_needs_one_sample():
    assert genetics._once_only("gen-lactose", "Лактазна недостатність, ген LCT") is True
    assert genetics._once_only(None, "Лактазна недостатність, ген LCT") is False


def test_an_acquired_tumour_mutation_is_followed_over_time_even_when_it_reads_as_a_gene():
    name = "Мутація JAK2 V617F"
    assert genetics.kind("x", "unmapped", name) == "gene"
    assert genetics._once_only("gen-thrombophilia", name) is False
