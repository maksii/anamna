"""Beyond the cheapest plan: what a plan gives for its money, which analytes
it pays for twice, and the plans worth showing next to the cheapest.

A *plan* is an *irredundant cover*: a set of items that covers every
coverable required key, where every item is there for a required key no
other item in the plan covers.  Remove any item and something the person
asked for goes missing.  So a single test bought next to a panel that
already measures it is never a plan, and neither is a panel added only for
its extras: alternatives are other ways to cover the same needs, not extras
bolted on.

**Value** (:func:`measured`, :func:`annotate`): each distinct result a plan
reports beyond the required keys counts 1, and 1 more when the record
already holds that result (it extends a history the person has).  A result
is one analyte the lab reports:

- heading and note rows («Примітки», «Фізико-хімічні властивості») are not
  results (``parameter_keys`` already maps them to nothing);
- a whole examination reported as one text block (``testplan.WHOLE_TESTS``,
  the coprogram) is one result, not every concept of its category;
- a genetic test is one result, however many genes it lists;
- a key the record derives from another (creatinine's eGFR,
  ``testplan_aliases.IMPLIED``) is not a second result.

**Duplicates**: a result reported by more than one item in a plan.  Their
money is already in the plan's cost, so duplicates break ties only: among
plans of equal cost and equal value, fewer duplicates wins.  A dearer plan
with fewer duplicates and the same value is simply worse (more money for
the same distinct results) and is never shown.  Each plan item says how
many results it repeats and which needs only it covers (:func:`annotate`),
so the page can say why an overlapping item is there.

**Alternatives** (:func:`alternatives`): plans on the cost/value Pareto
frontier within ``max_extra_pct`` of the cheapest, each strictly more value
than every cheaper one.  **Most complete** (:func:`most_complete`,
:func:`complete_options`): the frontier's highest-value plan, then cheaper
frontier plans stepping down to the cheapest.

**How plans are found**: exactly, as a mixed-integer program solved by
HiGHS (:class:`_Model`), one objective at a time, each later one holding the
earlier at its optimum: the cheapest plan is the lowest cost, then the most
value at that cost, then the fewest duplicates (extra copies of a result);
the most complete is the most value net of duplicates (each extra copy of
a result counts against the results a plan adds, so a package earns its
place only by bringing more new results than it repeats), then the lowest
cost, then the fewest duplicates.  No price cap: the cheaper plans below it
are its options.  Frontier plans are the most valuable plan under a cost cap,
made as cheap as its value allows.  ``exact`` is False only when a solve
hit :data:`TIME_LIMIT` and its best plan so far was used.
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor

import highspy
import numpy as np

from . import testplan, testplan_aliases
from .ingest.text import normalized_key

#: A runaway guard, not a quality setting: every solve runs to a proven
#: optimum, and only a program that has not finished after this many seconds
#: returns its best plan so far (``exact`` False, and the page says so).  A
#: 79-need check-up at one lab proves the cheapest plan in 0.3 s, its options
#: in 1-2 s and the most complete plan with its options in 0.5-1.5 s.
TIME_LIMIT = 120.0
#: How much dearer than the cheapest an alternative may be, by default.
MAX_EXTRA_PCT = 0.25
_EPS = 0.005  # half a kopiyka: prices are kopiyka-exact, sums are floats
_HEURISTICS = ("mip_heuristic_run_feasibility_jump", "mip_heuristic_run_rins", "mip_heuristic_run_rens",
               "mip_heuristic_run_root_reduced_cost")

#: Keys the record calculates from another key, never measured on their own.
_DERIVED = frozenset(key for keys in testplan_aliases.IMPLIED.values() for key in keys)


def _ref(item: dict) -> str:
    return f"{item.get('lab')}:{item['id']}"


def measured(item: dict) -> dict[str, frozenset[str]]:
    """The results an item reports: ``result -> the requirement keys it
    stands for``.  A result is a requirement key, except a whole examination
    (``"whole:<its name>"``, ``"whole:копрограма"``) and a genetic test
    (``"genetic:<lab>:<id>"``), each one result standing for many keys.
    Headings, notes and derived keys are not results."""
    if testplan.item_kind(item) == "genetic":
        return {f"genetic:{_ref(item)}": frozenset(item["keys"])}
    per_parameter = item.get("parameter_keys")
    if per_parameter is None:  # an item not keyed by testplan.keyed (tests, hand-made)
        return {key: frozenset((key,)) for key in item["keys"] if key not in _DERIVED}
    out: dict[str, frozenset[str]] = {}
    for parameter, keys in zip(item["parameters"], per_parameter):
        if not keys:
            continue
        name = normalized_key(parameter["name"])
        if name in testplan.WHOLE_TESTS:
            out.setdefault(f"whole:{name}", frozenset(keys))
            continue
        for key in keys:
            if key not in _DERIVED:
                out.setdefault(key, frozenset((key,)))
    return out


def duplicates(plan_items: list[dict]) -> dict[str, list[dict]]:
    """Every result reported by more than one item: ``result -> [items]``.
    All results count, not only the required ones."""
    by_result: dict[str, list[dict]] = {}
    for item in plan_items:
        for result in measured(item):
            by_result.setdefault(result, []).append(item)
    return {result: found for result, found in by_result.items() if len(found) > 1}


def duplicate_cost(plan_items: list[dict]) -> float:
    """Money spent on results measured twice: each item's price shared
    evenly over the results it reports, and every copy of a duplicated
    result counted but one -- a forced item's copy when there is one (the
    person chose that item; what was planned around it repeats it), else
    the cheapest."""
    per_result = {id(item): float(item["final_price"]) / max(1, len(measured(item))) for item in plan_items}
    waste = 0.0
    for found in duplicates(plan_items).values():
        keep = min(found, key=lambda item: (not item.get("forced"), per_result[id(item)]))
        waste += sum(per_result[id(item)] for item in found if item is not keep)
    return round(waste, 2)


def _extra(results: dict[str, frozenset[str]], required: set[str], tracked) -> tuple[set[str], set[str]]:
    """(results beyond the required keys, those of them the record holds)."""
    extra = {result for result, keys in results.items() if not keys & required}
    return extra, {result for result in extra if results[result] & tracked}


def annotate(plan: dict, required: set[str], tracked=frozenset(), cheapest: dict | None = None) -> dict:
    """``plan`` (the shape :func:`testplan.optimise` returns) with ``value``,
    ``extra_keys``, ``tracked_extra``, ``duplicates`` (``result -> ["<lab>:<id>"]``),
    ``duplicate_cost``, and relative to ``cheapest`` (itself when None)
    ``delta_cost``, ``more_results`` and ``more_tracked``.  ``required`` is
    what the person asked for, not what an included panel adds to it.

    Each item gets ``repeats`` (how many of its results another item in the
    plan also reports; a forced item, which the person chose, is compared
    with the other forced items only, so the repeats land on what was
    planned around it), ``repeated`` (those results) and ``justified_by``
    (the required keys no other item in the plan covers: why it is there).
    Changes and returns ``plan``."""
    required = set(required)
    per_item = [measured(item) for item in plan["items"]]
    results: dict[str, frozenset[str]] = {}
    for found in per_item:
        for result, keys in found.items():
            results.setdefault(result, keys)
    for index, item in enumerate(plan["items"]):
        others = [n for n in range(len(plan["items"])) if n != index
                  and (not item.get("forced") or plan["items"][n].get("forced"))]
        repeated = per_item[index].keys() & set().union(*(per_item[n].keys() for n in others))
        elsewhere = set().union(*(set(other["keys"]) for n, other in enumerate(plan["items"]) if n != index))
        item.update(repeats=len(repeated), repeated=sorted(repeated),
                    justified_by=sorted(set(item["keys"]) & required - elsewhere))
    extra, mine = _extra(results, required, set(tracked))
    plan.update(value=len(extra) + len(mine), extra_keys=sorted(extra), tracked_extra=sorted(mine),
                duplicates={result: [_ref(item) for item in found]
                            for result, found in sorted(duplicates(plan["items"]).items())},
                duplicate_cost=duplicate_cost(plan["items"]))
    base = cheapest or plan
    plan.update(delta_cost=round(plan["cost"] - base["cost"], 2),
                more_results=len(extra) - len(base["extra_keys"]),
                more_tracked=len(mine) - len(base["tracked_extra"]))
    return plan


def fixed(items: list[dict], required: set[str], tracked=frozenset()) -> dict:
    """A plan of exactly ``items``, in the order given (the person's own
    edit of one), in :func:`testplan.optimise`'s shape and annotated: each
    draw fee once, ``missing`` what none of them covers."""
    fees: dict[str, dict] = {}
    for item in items:
        for fee in item["fees"]:
            fees.setdefault(fee["id"], fee)
    items_cost = sum(float(item["final_price"]) for item in items)
    fee_total = sum(float(fee["price"]) for fee in fees.values())
    have = {key for item in items for key in item["keys"]}
    plan = {"items": [dict(item) for item in items], "fees": list(fees.values()), "items_cost": round(items_cost, 2),
            "fees_cost": round(fee_total, 2), "cost": round(items_cost + fee_total, 2),
            "list_cost": round(sum(float(item["price"]) for item in items) + fee_total, 2),
            "covered": sorted(set(required) & have), "missing": sorted(set(required) - have), "exact": True}
    return annotate(plan, required, tracked)


def _shape(forced: list[dict], chosen: list[dict], required: set[str], covered, missing, exact: bool) -> dict:
    """``chosen`` plus ``forced`` in :func:`testplan.optimise`'s plan shape."""
    fees: dict[str, dict] = {}
    for item in [*forced, *chosen]:
        for fee in item["fees"]:
            fees.setdefault(fee["id"], fee)
    picked = [{**item, "forced": True} for item in forced] + sorted(
        ({**item, "forced": False} for item in chosen), key=lambda item: -len(set(item["keys"]) & required))
    items_cost = sum(float(item["final_price"]) for item in picked)
    fee_total = sum(float(fee["price"]) for fee in fees.values())
    return {"items": picked, "fees": list(fees.values()), "items_cost": round(items_cost, 2),
            "fees_cost": round(fee_total, 2), "cost": round(items_cost + fee_total, 2),
            "list_cost": round(sum(float(item["price"]) for item in picked) + fee_total, 2),
            "covered": list(covered), "missing": list(missing), "exact": exact}




# --- the solver ---------------------------------------------------------------------


def _dominance(cands: list[tuple], net: bool = False) -> list[tuple]:
    """``cands`` (``(item, cover, results, price, fees)``) without the
    dominated ones, safely: another item with the same cover reports every
    result this one does and adds no fee this one does not, and is either
    cheaper or the same results at the same price.  Swapping it in keeps a
    cover irredundant, costs less (or the same with no more fees) and is
    worth no less, so no objective here ever wants the dominated one.
    Counting duplicates against value (``net``), more results can be worse
    (they may repeat what the plan has), so only the same results dominate."""
    by_cover: dict[frozenset, list[int]] = {}
    for index, cand in enumerate(cands):
        by_cover.setdefault(cand[1], []).append(index)

    def dominates(other: int, index: int) -> bool:
        _, _, o_results, o_price, o_fees = cands[other]
        _, _, results, price, fees = cands[index]
        wider = o_results.keys() == results.keys() if net else o_results.keys() >= results.keys()
        if other == index or not (wider and o_fees.keys() <= fees.keys()):
            return False
        if o_price < price - _EPS:
            return True
        same = o_results.keys() == results.keys() and abs(o_price - price) <= _EPS
        return same and (len(o_fees) < len(fees) or other < index)

    return [cand for index, cand in enumerate(cands) if not any(dominates(o, index) for o in by_cover[cand[1]])]


def _forced_facts(forced: list[dict]) -> tuple[dict, float, set]:
    forced_fees = {fee["id"]: float(fee["price"]) for item in forced for fee in item["fees"]}
    forced_cost = sum(float(item["final_price"]) for item in forced) + sum(forced_fees.values())
    forced_results = {result for item in forced for result in measured(item)}
    return forced_fees, forced_cost, forced_results


def _fee_prices(cands: list[tuple], forced_fees: dict) -> dict:
    return {fee: price for cand in cands for fee, price in cand[4].items() if fee not in forced_fees}


def _fitting_start(start: tuple | None, cap: float) -> tuple | None:
    return start if start is not None and start[0] <= cap + _EPS else None


def _stages(first: str) -> tuple[str, ...]:
    return ("cost", "value", "dups") if first == "cost" else ("value", "cost", "dups")


def _open_candidates(pool: list[dict], forced_ids: set, open_keys: set, net: bool) -> list[tuple]:
    cands = []
    for item in pool:
        cover = frozenset(item["keys"]) & open_keys
        if cover and (item.get("lab"), item["id"]) not in forced_ids:
            cands.append((item, cover, measured(item), float(item["final_price"]),
                          {fee["id"]: float(fee["price"]) for fee in item["fees"]}))
    return _dominance(cands, net)


def _result_weights(cands: list[tuple], forced_results: set, required: set[str], tracked: set) -> dict[str, int]:
    result_keys: dict[str, frozenset[str]] = {}
    for cand in cands:
        for result, found in cand[2].items():
            if result not in forced_results:
                result_keys.setdefault(result, found)
    # Value: 1 for a result beyond the needs, 2 when the record holds it.
    return {result: 1 + bool(found & tracked) for result, found in result_keys.items() if not found & required}


def _index_sets(cands: list[tuple], results: list[frozenset]) -> tuple[list[tuple], dict[tuple, list[str]]]:
    coverers: dict[str, list[int]] = {}
    reporting: dict[str, list[int]] = {}
    for i, cand in enumerate(cands):
        for key in cand[1]:
            coverers.setdefault(key, []).append(i)
        for result in results[i]:
            reporting.setdefault(result, []).append(i)
    key_sets = list(dict.fromkeys(tuple(found) for found in coverers.values()))
    result_sets: dict[tuple, list[str]] = {}
    for result, found in reporting.items():
        result_sets.setdefault(tuple(found), []).append(result)
    return key_sets, result_sets


def _columns(n: int, fee_price: dict, key_sets: list, result_sets: dict) -> tuple:
    y_col = {fee: n + index for index, fee in enumerate(sorted(fee_price))}
    t_col = [n + len(y_col) + index for index in range(len(key_sets))]
    u_col = {(i, c): n + len(y_col) + len(key_sets) + index
             for index, (c, i) in enumerate((c, i) for c, found in enumerate(key_sets) for i in found)}
    w_col = [n + len(y_col) + len(key_sets) + len(u_col) + index for index in range(len(result_sets))]
    size = n + len(y_col) + len(key_sets) + len(u_col) + len(w_col)
    return y_col, t_col, u_col, w_col, size


def _key_rows(key_sets: list, t_col: list, u_col: dict, inf: float) -> list:
    rows = []
    for c, found in enumerate(key_sets):
        rows.append((1.0, inf, dict.fromkeys(found, 1.0)))
        rows.append((0.0, 0.0, {t_col[c]: 1.0, **{u_col[i, c]: -1.0 for i in found}}))
        rows.extend((-inf, 1.0, {i: 1.0, u_col[i, c]: -1.0, t_col[c]: 1.0}) for i in found)
    return rows


def _item_rows(n: int, fees: list[dict], u_col: dict, y_col: dict, w_col: list, result_sets: dict, inf: float) -> list:
    owns: list[dict[int, float]] = [{} for _ in range(n)]
    for (i, _), column in u_col.items():
        owns[i][column] = -1.0
    rows = []
    for i in range(n):
        rows.append((-inf, 0.0, {i: 1.0, **owns[i]}))
        rows.extend((-inf, 0.0, {i: 1.0, y_col[fee]: -1.0}) for fee in fees[i])
    for column, found in zip(w_col, result_sets):
        rows.append((-inf, 0.0, {column: 1.0, **dict.fromkeys(found, -1.0)}))
    return rows


def _matrix(rows: list) -> tuple:
    starts, index, values = [], [], []
    for _, _, entries in rows:
        starts.append(len(index))
        index.extend(entries)
        values.extend(entries.values())
    return (len(rows), np.array([row[0] for row in rows]), np.array([row[1] for row in rows]),
            len(index), np.array(starts, dtype=np.int32), np.array(index, dtype=np.int32),
            np.array(values, dtype=np.float64))


class _Model:
    """Every irredundant cover of ``required`` from ``pool`` (``forced``
    bought already) as one HiGHS mixed-integer program, solved again for each
    objective and bound :meth:`best` asks for.

    Keys covered by the same items are one key ``k`` here, and results
    reported by the same items one result ``r``.  Columns: ``x_i`` item
    ``i`` is bought (binary); ``y_f`` fee ``f`` is paid; ``u_ik`` ``i`` is
    the only bought item covering ``k``, ``t_k`` the sum of them; ``w_r``
    ``r`` is reported.  Rows: every key covered (``sum x_i >= 1``); ``x_j -
    u_jk + t_k <= 1`` (an item owning ``k`` rules out every other bought
    item covering it); ``x_i <= sum_k u_ik`` (every bought item owns a key:
    the plan is irredundant); ``y_f >= x_i`` for each fee of an item; ``w_r
    <= sum x_i`` over the items reporting ``r``; then a cost row and a value
    row whose bounds hold the earlier objectives at their optimum.  The
    forced items' results and fees are constants, outside the program."""

    def __init__(self, pool: list[dict], required: set[str], forced: list[dict], tracked, deadline: float,
                 net: bool = False):
        self.forced, self.required, self.tracked, self.deadline = forced, required, set(tracked), deadline
        # "Most value" counts each duplicate against the value (most_complete).
        self.net = net
        forced_ids = {(item.get("lab"), item["id"]) for item in forced}
        open_keys = required - {key for item in forced for key in item["keys"]}
        self.covered = sorted(required & {key for item in [*forced, *pool] for key in item["keys"]})
        self.missing = sorted(required - set(self.covered))
        forced_fees, self.forced_cost, forced_results = _forced_facts(forced)
        cands = _open_candidates(pool, forced_ids, open_keys, net)
        self.items = [cand[0] for cand in cands]
        self.n = n = len(cands)
        fee_price = _fee_prices(cands, forced_fees)
        self.weight = _result_weights(cands, forced_results, required, self.tracked)
        self.results = [frozenset(cand[2].keys() - forced_results) for cand in cands]
        self.reports = [len(cand[2]) for cand in cands]
        self.prices = [cand[3] for cand in cands]
        self.fees = [{fee: fee_price[fee] for fee in cand[4] if fee in fee_price} for cand in cands]
        # Keys covered by the same items are one key to the program, and
        # results reported by the same items one result: the same plans
        # from a far smaller program.
        key_sets, result_sets = _index_sets(cands, self.results)
        y_col, t_col, u_col, w_col, self.size = _columns(n, fee_price, key_sets, result_sets)
        self.y_col, self.t_col, self.u_col, self.key_sets = y_col, t_col, u_col, key_sets
        self.w_col = dict(zip(w_col, result_sets))
        objective = self._objectives(fee_price, y_col, w_col, result_sets)
        self.objective = objective
        inf = highspy.kHighsInf
        rows = _key_rows(key_sets, t_col, u_col, inf) + _item_rows(n, self.fees, u_col, y_col, w_col, result_sets, inf)
        self.cost_row, self.value_row = len(rows), len(rows) + 1
        rows.append((-inf, inf, {c: v for c, v in enumerate(objective["cost"]) if v}))
        rows.append((-inf, inf, {c: -v for c, v in enumerate(objective["value"]) if v}))
        self.matrix = _matrix(rows)
        self.everything = np.arange(self.size, dtype=np.int32)

    def _objectives(self, fee_price: dict, y_col: dict, w_col: list, result_sets: dict) -> dict:
        n, cols = self.n, self.size
        cost = np.zeros(cols)
        cost[:n] = self.prices
        for fee, column in y_col.items():
            cost[column] = fee_price[fee]
        value = np.zeros(cols)  # negated: minimised, it is the most value
        dups = np.zeros(cols)  # extra copies: every report less the distinct results
        dups[:n] = self.reports
        for column, results in zip(w_col, result_sets.values()):
            value[column] = -sum(self.weight.get(result, 0) for result in results)
            dups[column] = -len(results)
        if self.net:
            value = value + dups
        return {"cost": cost, "value": value, "dups": dups}

    def _highs(self) -> highspy.Highs:
        """A fresh solver holding the program: one per solve sequence, so
        sequences run side by side in threads (HiGHS releases the GIL)."""
        highs = highspy.Highs()
        highs.silent()
        highs.setOptionValue("mip_rel_gap", 0.0)
        # Measured on the real catalogues: this heuristic costs more time
        # than it saves (and with a plan to start from, all do: see best).
        highs.setOptionValue("mip_heuristic_run_feasibility_jump", False)
        highs.addVars(self.size, np.zeros(self.size), np.ones(self.size))
        highs.changeColsIntegrality(self.n, self.everything[:self.n], np.ones(self.n, dtype=np.uint8))
        highs.addRows(*self.matrix)
        return highs

    def _start(self, chosen: tuple[int, ...]) -> np.ndarray:
        """Every column's value for the plan ``chosen``: a MIP start."""
        values = np.zeros(self.size)
        values[list(chosen)] = 1.0
        bought = set(chosen)
        for fee, column in self.y_col.items():
            values[column] = any(fee in self.fees[i] for i in chosen)
        for c, found in enumerate(self.key_sets):
            mine = [i for i in found if i in bought]
            if len(mine) == 1:  # the one item covering these keys owns them
                values[self.t_col[c]] = values[self.u_col[mine[0], c]] = 1.0
        for column, reporting in self.w_col.items():
            values[column] = any(i in bought for i in reporting)
        return values

    def measure(self, chosen: tuple[int, ...], exact: bool = True) -> tuple:
        """``(cost, value, duplicates, chosen, exact)``: the cost with the
        forced items', the value and duplicates beyond theirs (what the
        program counts), and whether every solve that found it finished."""
        fees = {fee: price for i in chosen for fee, price in self.fees[i].items()}
        reported = set().union(*(self.results[i] for i in chosen))
        return (round(self.forced_cost + sum(self.prices[i] for i in chosen) + sum(fees.values()), 2),
                sum(self.weight.get(result, 0) for result in reported),
                sum(self.reports[i] for i in chosen) - len(reported), chosen, exact)

    def best(self, first: str = "cost", cap: float = math.inf, *, start: tuple | None = None,
             deadline: float | None = None) -> tuple | None:
        """The best plan costing at most ``cap``, as :meth:`measure` gives it:
        the lowest cost, then the most value, then the fewest duplicates
        (``first`` "cost"), or the most value, then the lowest cost, then the
        fewest duplicates ("value").  One solve per objective, each holding
        the one before at its optimum and starting from it; the first starts
        from ``start`` (a plan :meth:`best` returned) when it fits ``cap``.
        None when no plan fits ``cap`` or the time (``deadline``, else the
        model's) ran out before one turned up."""
        if not self.n:
            return self.measure(()) if self.forced_cost <= cap + _EPS else None
        highs, inf = self._highs(), highspy.kHighsInf
        highs.changeRowBounds(self.cost_row, -inf, cap - self.forced_cost + _EPS if cap < math.inf else inf)
        found = _fitting_start(start, cap)
        exact = True
        for stage in _stages(first):
            self._prepare_stage(highs, stage, first, found, deadline)
            highs.run()
            status = highs.getModelStatus()
            if self._unsolved(highs, status):
                return None if stage == first else found
            if status == highspy.HighsModelStatus.kTimeLimit:
                exact = False
            found = self._solution(highs, exact)
            self._tighten(highs, stage, found, inf)
        return found

    def _solution(self, highs, exact: bool) -> tuple:
        return self.measure(tuple(i for i in range(self.n) if highs.getSolution().col_value[i] > 0.5), exact)

    def _prepare_stage(self, highs, stage: str, first: str, found: tuple | None, deadline: float | None) -> None:
        highs.changeColsCost(self.size, self.everything, self.objective[stage])
        highs.setOptionValue("time_limit", max(min(deadline or math.inf, self.deadline) - time.monotonic(), 0.01))
        if found is not None:
            highs.setSolution(self.size, self.everything, self._start(found[3]))
            if stage != first:  # holding the optimum already: the search only proves it
                for heuristic in _HEURISTICS:
                    highs.setOptionValue(heuristic, False)
                highs.setOptionValue("mip_heuristic_effort", 0.0)

    def _unsolved(self, highs, status) -> bool:
        """No plan the solver can show: it neither finished nor ran out of time, or it has no feasible solution."""
        return (status not in (highspy.HighsModelStatus.kOptimal, highspy.HighsModelStatus.kTimeLimit)
                or highs.getInfo().primal_solution_status != highspy.SolutionStatus.kSolutionStatusFeasible)

    def _tighten(self, highs, stage: str, found: tuple, inf: float) -> None:
        if stage == "cost":
            highs.changeRowBounds(self.cost_row, -inf, found[0] - self.forced_cost + _EPS)
        elif stage == "value":
            highs.changeRowBounds(self.value_row, found[1] - (found[2] if self.net else 0) - 0.5, inf)

    def richest(self, caps: list[float], start: tuple | None = None) -> list[tuple | None]:
        """:meth:`best` most valuable first under each of ``caps``, side by side."""
        if len(caps) <= 1:
            return [self.best("value", cap, start=start) for cap in caps]
        with ThreadPoolExecutor(len(caps)) as pool:
            return list(pool.map(lambda cap: self.best("value", cap, start=start), caps))

    def plan(self, found: tuple, cheapest: dict | None = None) -> dict:
        """``found`` in :func:`_shape`'s plan shape, annotated."""
        plan = _shape(self.forced, [self.items[i] for i in found[3]], self.required, self.covered, self.missing,
                      found[4])
        return annotate(plan, self.required, self.tracked, cheapest)


def _model(items, required, forced, labs, tracked, net: bool = False) -> _Model:
    pool = [item for item in items if labs is None or item.get("lab") in labs]
    forced = list({(item.get("lab"), item["id"]): item for item in forced
                   if labs is None or item.get("lab") in labs}.values())
    return _Model(pool, set(required), forced, tracked, time.monotonic() + TIME_LIMIT, net)


def _cheapest(model: _Model) -> tuple[tuple | None, dict]:
    """The cheapest plan, measured and annotated.  Should the time run out
    before the solver holds any cover, :func:`testplan.optimise` stands in
    (``exact`` False)."""
    low = model.best("cost")
    if low is None:
        fallback = testplan.optimise(model.items, model.required, forced=model.forced)
        return None, annotate({**fallback, "exact": False}, model.required, model.tracked)
    return low, model.plan(low)


def _frontier(model: _Model, low: tuple, found: list, count: int) -> list[tuple]:
    """The most valuable plan of ``found`` (each the most valuable plan
    under some cap; ties to the cheaper) and up to ``count`` frontier plans
    between ``low`` and it, cheapest first and the top last; empty when
    nothing is worth more than ``low``.  Below ``count`` plans in between,
    the most valuable plan just cheaper than each known one is added, until
    no gap holds another.  Each is the cheapest plan of its value, so on the
    frontier."""
    found = [plan for plan in found if plan is not None and plan[1] > low[1]]
    if not found:
        return []
    top = max(found, key=lambda plan: (plan[1], -plan[0]))
    line = {top[1]: top}
    probed = set()  # plans whose next cheaper frontier plan is known
    while True:
        for plan in found:
            if plan is not None and low[1] < plan[1] < top[1]:
                line.setdefault(plan[1], plan)
        todo = sorted(plan for plan in line.values() if plan[1] not in probed)[:max(count + 1 - len(line), 0)]
        if not todo:
            break
        probed.update(plan[1] for plan in todo)
        found = model.richest([plan[0] - 0.01 for plan in todo], low)
    out, best = [], low[1]
    for plan in sorted(line.values()):  # strictly more value for more money
        if plan[1] > best:
            out.append(plan)
            best = plan[1]
    return [*out[:-1][:count], out[-1]]


def alternatives(items: list[dict], required: set[str], *, forced: list[dict] = (), labs: set[str] | None = None,
                 tracked=frozenset(), max_extra_pct: float = MAX_EXTRA_PCT, limit: int = 3) -> list[dict]:
    """``[cheapest, *alternatives]``.  The cheapest plan first (with the
    most value, then the fewest duplicates, at its cost); then up to
    ``limit`` frontier plans costing at most ``max_extra_pct`` more, each
    worth strictly more than every cheaper plan (so none is dominated): the
    most valuable one within the bound and the most valuable under caps
    spaced evenly up to the bound, shown cheapest first.  ``labs`` keeps
    items (and forced items) of those labs only; ``tracked`` is the concepts
    the record holds (:func:`testplan.lab_concepts`).  Every plan is
    annotated (:func:`annotate`) against the cheapest: "for +``delta_cost``
    UAH, ``more_results`` more results (``more_tracked`` you already
    track)"."""
    model = _model(items, required, forced, labs, tracked)
    low, cheapest = _cheapest(model)
    if low is None or limit <= 0:
        return [cheapest]
    bound = cheapest["cost"] * (1 + max(0.0, max_extra_pct))
    found = model.richest([bound, *(low[0] + (bound - low[0]) * step / limit for step in range(1, limit))], low)
    return [cheapest, *(model.plan(plan, cheapest) for plan in _frontier(model, low, found, limit - 1))]


def most_complete(items: list[dict], required: set[str], *, budget: float | None = None,
                  labs: set[str] | None = None, forced: list[dict] = (), tracked=frozenset()) -> dict | None:
    """The "quality first" plan: of the irredundant covers of ``required``
    at ``labs`` costing at most ``budget`` (any cost when None), the one of
    highest value; ties go to the lower cost, then fewer duplicates.  None
    when no cover fits the budget.  Value is net of duplicates (see the
    module docstring).  Annotated against the cheapest cover."""
    model = _model(items, required, forced, labs, tracked, net=True)
    low, cheapest = _cheapest(model)
    if budget is not None and cheapest["cost"] > float(budget) + _EPS:
        return None
    top = low and model.best("value", math.inf if budget is None else float(budget), start=low)
    if not top or top[1] <= low[1]:
        return cheapest
    return model.plan(top, cheapest)


def complete_options(items: list[dict], required: set[str], *, forced: list[dict] = (),
                     labs: set[str] | None = None, tracked=frozenset(), limit: int = 3) -> list[dict]:
    """The "most complete" choices, best first: the most complete plan
    (:func:`most_complete` with no budget), then up to ``limit`` cheaper
    frontier plans stepping down (the most valuable under caps spaced evenly
    between it and the cheapest), then the cheapest; each worth strictly
    more than every cheaper one, all annotated against the cheapest.  Just
    ``[cheapest]`` when nothing is worth more than it.  The most complete
    plan gets two thirds of the time left, the plans below it the rest."""
    model = _model(items, required, forced, labs, tracked, net=True)
    low, cheapest = _cheapest(model)
    if low is None:
        return [cheapest]
    now = time.monotonic()
    top = model.best("value", start=low, deadline=now + (model.deadline - now) * 2 / 3)
    if top is None or top[1] <= low[1]:
        return [cheapest]
    found = model.richest([low[0] + (top[0] - low[0]) * step / (limit + 1) for step in range(1, limit + 1)], low)
    line = _frontier(model, low, [top, *found], limit)
    return [*(model.plan(plan, cheapest) for plan in reversed(line)), cheapest]
