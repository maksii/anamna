"""What a test plan gives for its money (:mod:`anamna.testplan_value`):
results beyond the needs, duplicates, the cost/value frontier, the "quality
first" plans, all solved exactly.  Every catalogue is synthetic except the
last test, which reads the cached real price lists when this machine has
them."""

from __future__ import annotations

import itertools
import random
import sqlite3
import time
from pathlib import Path

import pytest

from anamna import testplan
from anamna import testplan_value as tv


def item(item_id, keys, price, *, fees=(("draw", 80.0),), lab="esculab", params=None, groups=None):
    out = {"id": str(item_id), "code": "", "name": f"Item {item_id}", "url": None, "price": float(price),
           "final_price": float(price),
           "fees": [{"id": f"{lab}:{fee}", "name": fee, "price": cost} for fee, cost in fees],
           "parameters": params or [{"id": k, "name": k} for k in keys], "synonyms": [], "sex": None,
           "order": {}, "keys": list(keys), "lab": lab}
    if groups:
        out["groups"] = groups
    return out


def ids(plan):
    return sorted(i["id"] for i in plan["items"])


# --- what counts as a result ----------------------------------------------------


def test_headings_whole_examinations_genetic_and_derived_keys_are_one_result_or_none():
    stool = ["stool-ph", "stool-fat", "stool-starch", "stool-muscle-fibres"]
    coprogram = item(1, ["stool-ph", "stool-fat", "stool-starch", "stool-muscle-fibres", "x:note-free"], 300,
                     params=[{"id": "p1", "name": "Копрограма"}, {"id": "p2", "name": "Примітки"},
                             {"id": "p3", "name": "Колір"}])
    coprogram["parameter_keys"] = [stool, [], ["x:note-free"]]
    assert tv.measured(coprogram) == {"whole:копрограма": frozenset(stool),
                                      "x:note-free": frozenset({"x:note-free"})}
    genes = item(2, ["a", "b", "c"], 900, groups=["Генетичні дослідження"])
    assert list(tv.measured(genes)) == ["genetic:esculab:2"]
    creatinine = item(3, ["creatinine", "estimated-glomerular-filtration-rate-ckd-epi-2021"], 100)
    assert list(tv.measured(creatinine)) == ["creatinine"]

    # The coprogram is one extra result, and none when a stool key is needed.
    plan = tv.annotate(testplan.optimise([coprogram], {"x:note-free"}), {"x:note-free"})
    assert plan["extra_keys"] == ["whole:копрограма"] and plan["value"] == 1
    plan = tv.annotate(testplan.optimise([coprogram], {"stool-ph"}), {"stool-ph"})
    assert plan["extra_keys"] == ["x:note-free"]


def test_a_result_already_in_the_record_counts_twice():
    plan = tv.annotate(testplan.optimise([item(1, ["a", "e1", "e2"], 100)], {"a"}), {"a"}, tracked={"e2"})
    assert plan["extra_keys"] == ["e1", "e2"] and plan["tracked_extra"] == ["e2"] and plan["value"] == 3


# --- duplicates -------------------------------------------------------------------


def test_duplicates_are_found_and_priced():
    lipids = item(1, ["chol", "hdl"], 200)
    biochem = item(2, ["chol", "glucose", "alt", "ast"], 400)
    found = tv.duplicates([lipids, biochem])
    assert list(found) == ["chol"] and [i["id"] for i in found["chol"]] == ["1", "2"]
    # 200/2 = 100 a result against 400/4 = 100: one copy is the waste.
    assert tv.duplicate_cost([lipids, biochem]) == 100.0
    plan = tv.annotate(testplan.optimise([lipids, biochem], {"hdl", "glucose"}), {"hdl", "glucose"})
    assert plan["duplicates"] == {"chol": ["esculab:1", "esculab:2"]} and plan["duplicate_cost"] == 100.0


def test_each_item_says_what_it_repeats_and_which_needs_justify_it():
    # The person includes a package; a CBC-like item is planned around it for
    # «c», repeating two of the package's results.
    package = item(9, ["a", "b", "x1", "x2", "x3"], 1000)
    items = [package, item(1, ["c", "x1", "x2", "y"], 300), item(2, ["d"], 100)]
    plan = tv.alternatives(items, {"a", "b", "c", "d"}, forced=[package])[0]
    facts = {i["id"]: (i["repeats"], i["repeated"], i["justified_by"]) for i in plan["items"]}
    assert facts == {"9": (0, [], ["a", "b"]), "1": (2, ["x1", "x2"], ["c"]), "2": (0, [], ["d"])}
    # The repeats are charged to the planned item (300 over 4 results), not
    # to the package the person chose.
    assert plan["duplicate_cost"] == 150.0 and sorted(plan["duplicates"]) == ["x1", "x2"]


def test_never_a_single_next_to_a_panel_that_measures_it():
    # The single «a» brings five extras cheaply, so a plan that merely adds
    # value would buy it next to the panel.  It is never a plan: «a» is the
    # panel's already.
    items = [item(1, ["a", "b", "c"], 200), item(2, ["a", "e1", "e2", "e3", "e4", "e5"], 30),
             item(3, ["b"], 90), item(4, ["c"], 90)]
    plans = tv.alternatives(items, {"a", "b", "c"}, max_extra_pct=5, limit=10)
    best = tv.most_complete(items, {"a", "b", "c"})
    for plan in [*plans, best]:
        chosen = [set(i["keys"]) & {"a", "b", "c"} for i in plan["items"]]
        for index, cover in enumerate(chosen):
            assert cover - set().union(*(c for n, c in enumerate(chosen) if n != index)), ids(plan)
    assert ids(best) == ["2", "3", "4"] and best["value"] == 5


def test_the_cheapest_plan_is_not_the_greedy_one():
    # Greedy, best price per key first, takes the panel (75 a key) and then
    # needs «e» and «f» alone: 300 + 100 + 100.  Two halves cover all six
    # for 480.
    items = [item(1, ["a", "b", "c", "d"], 300), item(2, ["a", "b", "e"], 240), item(3, ["c", "d", "f"], 240),
             item(4, ["e"], 100), item(5, ["f"], 100)]
    plan = tv.alternatives(items, {"a", "b", "c", "d", "e", "f"}, limit=0)[0]
    assert ids(plan) == ["2", "3"] and plan["cost"] == 560.0 and plan["exact"]


def test_fewest_duplicates_break_ties_in_every_mode():
    # Every pair costs 200 + 80 and reports x, y and z beyond the needs;
    # {1, 2} reports each once, the others repeat «y», «z» or both.
    items = [item(1, ["a", "x", "y"], 100), item(2, ["b", "z"], 100), item(3, ["a", "x", "y", "z"], 100),
             item(4, ["b", "z", "y"], 100)]
    for plan in [tv.alternatives(items, {"a", "b"})[0], tv.most_complete(items, {"a", "b"}),
                 *tv.complete_options(items, {"a", "b"})]:
        assert ids(plan) == ["1", "2"] and plan["duplicates"] == {} and plan["value"] == 3
    # Duplicates count extra copies: «y» three times is two, as much as «y»
    # and «z» twice each.
    assert sum(len(found) - 1 for found in tv.duplicates([item(5, ["y"], 1), *items[2:]]).values()) == 3


def test_equal_cost_and_value_prefers_fewer_duplicates():
    # Two covers at 300 + 80, both reporting «x» besides the needs: {1, 2}
    # pays for it twice, {3, 4} once.  Mixing them costs more or misses «b».
    items = [item(1, ["a", "b", "x"], 200), item(2, ["c", "x"], 100), item(3, ["a", "x"], 150),
             item(4, ["b", "c"], 150)]
    cheapest = tv.alternatives(items, {"a", "b", "c"})[0]
    assert ids(cheapest) == ["3", "4"] and cheapest["duplicates"] == {} and cheapest["cost"] == 380.0
    assert cheapest["value"] == 1


# --- alternatives ---------------------------------------------------------------------


def test_an_alternative_appears_exactly_when_it_adds_value_within_the_bound():
    singles = [item(1, ["a"], 100), item(2, ["b"], 100)]  # 280 with the draw
    within = singles + [item(3, ["a", "b", "e1", "e2", "e3", "e4", "e5"], 230)]  # 310: +10.7 %
    plans = tv.alternatives(within, {"a", "b"}, tracked={"e1"})
    assert [ids(p) for p in plans] == [["1", "2"], ["3"]]
    alt = plans[1]
    assert alt["delta_cost"] == 30.0 and alt["more_results"] == 5 and alt["more_tracked"] == 1 and alt["value"] == 6
    assert set(alt) >= {"items", "fees", "items_cost", "fees_cost", "cost", "list_cost", "covered", "missing",
                        "exact", "value", "extra_keys", "tracked_extra", "duplicates", "duplicate_cost", "delta_cost"}
    assert alt["items"][0] is not within[2] and alt["items"][0]["forced"] is False

    assert len(tv.alternatives(within, {"a", "b"}, max_extra_pct=0.10)) == 1  # 10.7 % is over
    too_dear = singles + [item(3, ["a", "b", "e1", "e2", "e3", "e4", "e5"], 300)]  # 380: +35.7 %
    assert len(tv.alternatives(too_dear, {"a", "b"})) == 1
    no_more = singles + [item(3, ["a", "b"], 230)]  # dearer, nothing more
    assert len(tv.alternatives(no_more, {"a", "b"})) == 1


def test_dominated_alternatives_are_dropped_and_the_limit_keeps_the_best():
    items = [item(1, ["a"], 100), item(2, ["b"], 100),
             item(3, ["a", "b", "e1", "e2", "e3"], 240),        # 320, 3 more
             item(4, ["a", "b", "e1", "e2"], 250),              # 330, 2 more: dominated by 3
             item(5, ["a", "b", "e1", "e2", "e3", "e4"], 260),  # 340, 4 more
             item(6, ["a", "b", *[f"e{n}" for n in range(1, 11)]], 270)]  # 350, 10 more
    plans = tv.alternatives(items, {"a", "b"})
    assert [ids(p) for p in plans] == [["1", "2"], ["3"], ["5"], ["6"]]
    assert [p["delta_cost"] for p in plans] == [0.0, 40.0, 60.0, 70.0]


def test_a_short_list_keeps_the_most_valuable_and_the_best_rate():
    items = [item(1, ["a"], 100), item(2, ["b"], 100),
             item(3, ["a", "b", "e1", "e2", "e3"], 210),        # 290: 3 for +10 (0.3/UAH)
             item(5, ["a", "b", "e1", "e2", "e3", "e4"], 260),  # 340: 4 for +60
             item(6, ["a", "b", *[f"e{n}" for n in range(1, 11)]], 270)]  # 350: 10 for +70
    assert [ids(p) for p in tv.alternatives(items, {"a", "b"}, limit=2)] == [["1", "2"], ["3"], ["6"]]


def test_a_preferred_lab_plans_with_its_items_only():
    items = [item(1, ["a", "b"], 100, lab="synevo"), item(2, ["a"], 100), item(3, ["b"], 100),
             item(4, ["a", "b", "e1"], 230)]
    assert [p["items"][0]["lab"] for p in tv.alternatives(items, {"a", "b"})] == ["synevo"]
    plans = tv.alternatives(items, {"a", "b"}, labs={"esculab"})
    assert [ids(p) for p in plans] == [["2", "3"], ["4"]]
    assert all(i["lab"] == "esculab" for p in plans for i in p["items"])
    assert tv.most_complete(items, {"a", "b"}, labs={"synevo"})["cost"] == 180.0


def test_forced_items_stay_and_the_rest_is_planned_around_them():
    panel = item(9, ["a", "z"], 500)
    items = [panel, item(1, ["a"], 50), item(2, ["b"], 60), item(3, ["b", "e1", "e2"], 70)]
    plans = tv.alternatives(items, {"a", "b"}, forced=[panel])
    assert [ids(p) for p in plans] == [["2", "9"], ["3", "9"]]
    assert plans[0]["items"][0]["forced"] and plans[0]["cost"] == 640.0 and plans[1]["delta_cost"] == 10.0


# --- most complete ----------------------------------------------------------------------


def test_most_complete_maximises_results_under_the_budget():
    items = [item(1, ["a"], 100), item(2, ["b"], 100),
             item(3, ["a", "b", "e1", "e2", "e3"], 240),               # 320
             item(4, ["a", "b", *[f"e{n}" for n in range(1, 9)]], 900),  # 980
             item(5, ["a", "b", *[f"e{n}" for n in range(1, 9)]], 950)]  # same results, dearer
    assert ids(tv.most_complete(items, {"a", "b"})) == ["4"]
    assert tv.most_complete(items, {"a", "b"})["delta_cost"] == 700.0
    assert ids(tv.most_complete(items, {"a", "b"}, budget=500)) == ["3"]
    assert ids(tv.most_complete(items, {"a", "b"}, budget=290)) == ["1", "2"]
    assert tv.most_complete(items, {"a", "b"}, budget=200) is None


def test_complete_options_step_down_from_the_most_complete_to_the_cheapest():
    items = [item(1, ["a"], 100), item(2, ["b"], 100),
             item(3, ["a", "b", "e1", "e2", "e3"], 240),               # 320, 3 more
             item(4, ["a", "b", *[f"e{n}" for n in range(1, 9)]], 900),  # 980, 8 more
             item(6, ["a", "b", "e1", "e2", "e3", "e4"], 600)]          # 680, 4 more
    options = tv.complete_options(items, {"a", "b"})
    assert [ids(p) for p in options] == [["4"], ["6"], ["3"], ["1", "2"]]
    assert [p["delta_cost"] for p in options] == [700.0, 400.0, 40.0, 0.0]
    assert all(p["exact"] for p in options)
    # One step: the best under the midpoint, 630.
    assert [ids(p) for p in tv.complete_options(items, {"a", "b"}, limit=1)] == [["4"], ["3"], ["1", "2"]]
    # Nothing worth more than the cheapest: the cheapest alone.
    assert [ids(p) for p in tv.complete_options(items[:2], {"a", "b"})] == [["1", "2"]]


# --- exactness against brute force ------------------------------------------------------


def _random_catalogue(rng, lab="esculab"):
    keys = [f"k{n}" for n in range(rng.randint(2, 5))]
    extras = [f"e{n}" for n in range(6)]
    fees = [("draw", 80.0), ("urine", 30.0)]
    items = [item(n, rng.sample(keys, rng.randint(1, len(keys))) + rng.sample(extras, rng.randint(0, 4)),
                  rng.choice([40, 60, 60, 90, 120, 150, 200]), fees=rng.sample(fees, rng.randint(0, 2)), lab=lab)
             for n in range(rng.randint(1, 8))]
    required = set(rng.sample(keys, rng.randint(1, len(keys))))
    tracked = set(rng.sample(keys + extras, 3))
    forced = rng.sample(items, 1) if items and rng.random() < 0.25 else []
    return items, required, tracked, forced


def _brute(items, required, tracked, forced, budget):
    """(cost, value, duplicates, ids) of every irredundant cover within budget."""
    forced_ids = {i["id"] for i in forced}
    open_keys = required - {k for i in forced for k in i["keys"]}
    pool = [i for i in items if i["id"] not in forced_ids and set(i["keys"]) & open_keys]
    coverable = open_keys & {k for i in pool for k in i["keys"]}
    out = []
    for size in range(len(pool) + 1):
        for combo in itertools.combinations(pool, size):
            covers = [set(i["keys"]) & coverable for i in combo]
            if set().union(*covers) != coverable:
                continue
            if any(not c - set().union(*(o for n, o in enumerate(covers) if n != index))
                   for index, c in enumerate(covers)):
                continue
            plan = tv.annotate(tv._shape(forced, list(combo), required, [], [], True), required, tracked)
            if plan["cost"] <= budget + 1e-6:
                out.append((plan["cost"], plan["value"], _copies(plan), ids(plan)))
    return out


def _copies(plan):
    """The duplicates the solver minimises: extra copies of a result."""
    return sum(len(found) - 1 for found in plan["duplicates"].values())


def _pareto(plans):
    best = {}
    for cost, value, dups, _ in plans:
        if (cost, value) not in best or dups < best[(cost, value)]:
            best[(cost, value)] = dups
    return sorted((c, v, d) for (c, v), d in best.items()
                  if not any(c2 <= c and v2 >= v and (c2, v2) != (c, v) for c2, v2 in best))


def test_most_complete_ranks_by_value_net_of_duplicates():
    # Items 1+2 cost 130 and report 8 results, two of them twice; items 0+2
    # cost 290 and report 7, none twice.  Net of copies the dearer plan is
    # worth more (7 against 6), so it is the most complete plan.  Ranked by
    # results alone, the cheapest one hid it.
    items = [item(0, ["k0", "e4"], 90, fees=(("draw", 80.0), ("urine", 30.0))),
             item(1, ["k0", "e1", "e3", "e4", "e0"], 40, fees=()),
             item(2, ["k1", "k2", "e0", "e5", "e1"], 90, fees=())]
    required, tracked = {"k0", "k1"}, {"e0", "e5", "k0"}
    best = tv.most_complete(items, required, tracked=tracked)
    assert ids(best) == ["0", "2"] and _copies(best) == 0
    options = tv.complete_options(items, required, tracked=tracked)
    assert [ids(plan) for plan in options] == [["0", "2"], ["1", "2"]]


def test_every_mode_equals_brute_force():
    rng = random.Random(11)
    for _ in range(150):
        items, required, tracked, forced = _random_catalogue(rng)
        base = testplan.optimise(items, required, forced=forced)
        budget = base["cost"] * 1.6
        plans = _brute(items, required, tracked, forced, budget)
        everything = _brute(items, required, tracked, forced, float("inf"))
        shown = tv.alternatives(items, required, forced=forced, tracked=tracked, max_extra_pct=0.6, limit=10)
        assert all(plan["exact"] for plan in shown)
        assert [(p["cost"], p["value"], _copies(p)) for p in shown] == _pareto(plans)
        assert shown[0]["cost"] == base["cost"]
        # Most complete: the most value net of duplicates (each extra copy
        # counts against it), then the lowest cost, then the fewest copies;
        # the options below step down to the cheapest, dearer always worth more.
        def net(plan):
            return (plan[1] - plan[2], -plan[0], -plan[2])

        options = tv.complete_options(items, required, forced=forced, tracked=tracked, limit=10)
        top = max(everything, key=net)
        got = [(p["cost"], p["value"], _copies(p)) for p in options]
        assert all(plan["exact"] for plan in options) and got[-1][0] == base["cost"]
        assert len(options) == 1 or net((*got[0], None)) == net(top)
        assert all(dear[0] > cheap[0] and dear[1] - dear[2] > cheap[1] - cheap[2] for dear, cheap in zip(got, got[1:]))
        # Each option is the best plan at its price: no plan costing no more is
        # worth more, or as much for less, or as much for as much with fewer copies.
        assert all(net(plan) == net(max((q for q in everything if q[0] <= plan[0] + 0.005), key=net))
                   for plan in got)

        for limit_budget in (None, budget):
            got = tv.most_complete(items, required, forced=forced, tracked=tracked, budget=limit_budget)
            pool = plans if limit_budget else everything
            want = max(pool, key=net)
            cheap = min(pool, key=lambda p: (p[0], p[2] - p[1], p[2]))
            if want[1] - want[2] <= cheap[1] - cheap[2]:
                continue  # nothing worth more than the cheapest: the cheapest stands
            assert net((got["cost"], got["value"], _copies(got))) == net(want)


# --- the real catalogues ---------------------------------------------------------------

LIVE = Path(__file__).resolve().parents[2] / "data" / "anamna.sqlite3"
CHECKUP = {
    "hemoglobin", "white-blood-cell-count", "red-blood-cell-count", "platelet-count", "hematocrit",
    "mean-corpuscular-volume", "mean-corpuscular-hemoglobin", "mean-corpuscular-hemoglobin-concentration",
    "neutrophils", "lymphocytes", "monocytes", "eosinophils", "basophils", "erythrocyte-sedimentation-rate",
    "blood-glucose", "hemoglobin-a1c", "total-cholesterol", "ldl-cholesterol", "hdl-cholesterol", "triglycerides",
    "alanine-aminotransferase", "aspartate-aminotransferase", "creatinine", "urea", "thyroid-stimulating-hormone",
    "ferritin", "25-hydroxyvitamin-d", "urine-specific-gravity", "urine-ph", "urine-protein", "urine-glucose",
    "urine-ketones", "urine-leukocytes", "urine-erythrocytes", "urine-nitrite", "urine-bilirubin",
    "urine-urobilinogen",
}


def _real_catalogues():
    """Both cached price lists keyed as the page keys them, read-only; None
    on a machine without the record or the catalogues."""
    import json

    from anamna.labsync import esculab_shop, synevo_shop

    if not LIVE.exists():
        return None
    connection = sqlite3.connect(f"file:{LIVE.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        owner = connection.execute("SELECT id FROM users ORDER BY created_at LIMIT 1").fetchone()
        rows = {row["provider"]: json.loads(row["payload_json"]) for row in connection.execute(
            "SELECT provider, payload_json FROM lab_catalog_cache WHERE cache_key='catalog' AND region IN (?, ?)",
            (esculab_shop.DEFAULT_REGION, synevo_shop.DEFAULT_REGION))}
        if owner is None or set(rows) != {"esculab", "synevo"}:
            return None
        aliases, categories = testplan.alias_index(connection), testplan.category_index(connection)
        labs = {lab: testplan.keyed(rows[lab], lab, vendor, aliases,
                                    testplan.learned_names(connection, owner["id"], lab), categories)
                for lab, vendor in (("esculab", "Esculab"), ("synevo", "Synevo"))}
        return labs, testplan.lab_concepts(connection, owner["id"])
    except sqlite3.Error:
        return None
    finally:
        connection.close()


def test_alternatives_on_the_real_catalogues_are_exact_and_quick():
    found = _real_catalogues()
    if found is None:
        pytest.skip("no cached lab catalogues on this machine")
    labs, tracked = found
    for lab, items in labs.items():
        started = time.perf_counter()
        plans = tv.alternatives(items, CHECKUP, labs={lab}, tracked=tracked)
        elapsed = time.perf_counter() - started
        assert elapsed < 5, (lab, elapsed)
        assert all(p["exact"] for p in plans) and plans[0]["cost"] <= testplan.optimise(items, CHECKUP)["cost"]
        assert all(p["value"] > plans[0]["value"] and 0 < p["delta_cost"] <= plans[0]["cost"] * 0.25 + 0.01
                   for p in plans[1:])


def test_a_set_plus_single_tests_beats_a_second_overlapping_set_unless_that_set_is_cheaper():
    """The owner's rule: singles, sets and their mixes are all compared; a
    second set that repeats results is bought only when it is the cheaper
    way, and fuller plans are options with their price, never the default."""
    needs = {"a", "b", "c", "d", "e", "f", "g"}
    big = item("big", ["a", "b", "c", "d", "e"], 500)  # covers almost everything
    singles = [item("f", ["f"], 100), item("g", ["g"], 100)]
    overlap = item("overlap", ["d", "e", "f", "g", "x1", "x2", "x3"], 300)  # repeats d and e
    plans = tv.alternatives([big, *singles, overlap], needs, limit=3)
    assert ids(plans[0]) == ["big", "f", "g"] and plans[0]["cost"] == 780 and not plans[0]["duplicates"]
    # The overlapping set adds three results for 100 more: shown as an option, not chosen.
    assert [ids(p) for p in plans[1:]] == [["big", "overlap"]] and plans[1]["more_results"] == 3
    # Cheaper than the two singles: then the repeats are worth it, and it is the plan.
    cheap = {**overlap, "price": 150.0, "final_price": 150.0}
    assert ids(tv.alternatives([big, *singles, cheap], needs, limit=0)[0]) == ["big", "overlap"]
    # Most complete takes the set only because it adds more than it repeats (3 new, 2 repeated).
    assert ids(tv.most_complete([big, *singles, overlap], needs)) == ["big", "overlap"]
    repeats_more = {**overlap, "keys": ["d", "e", "f", "g", "x1"], "parameters": [{"id": k, "name": k} for k in "defg"] + [{"id": "x1", "name": "x1"}]}
    assert ids(tv.most_complete([big, *singles, repeats_more], needs)) == ["big", "f", "g"]
