"""Items the person pins into a plan, and telling sets from single results."""

from __future__ import annotations

from anamna import testplan


def item(item_id, keys, price, *, fees=(("draw", 80.0),), lab="esculab", groups=(), params=None):
    return {"id": str(item_id), "name": f"Item {item_id}", "price": float(price), "final_price": float(price),
            "fees": [{"id": f"{lab}:{fee}", "name": fee, "price": cost} for fee, cost in fees],
            "parameters": params if params is not None else [{"id": k, "name": k} for k in keys],
            "keys": list(keys), "lab": lab, "groups": list(groups)}


def test_a_pinned_item_is_bought_and_the_rest_is_planned_around_it():
    genetic = item("dna", ["x:fh-genes"], 36170, groups=["Генетичні дослідження"])
    singles = [item(1, ["ldl"], 171), item(2, ["hdl"], 180), item(3, ["ldl", "hdl", "tc"], 600)]
    plan = testplan.optimise(singles, {"ldl", "hdl"}, forced=[genetic])
    assert [(i["id"], i["forced"]) for i in plan["items"]] == [("dna", True), ("1", False), ("2", False)]
    # One blood draw for the whole visit, however many items need it.
    assert plan["cost"] == 36170 + 171 + 180 + 80 and plan["fees_cost"] == 80


def test_what_a_pinned_panel_reports_is_not_bought_twice():
    panel = item("p", ["ldl", "hdl", "tc"], 600)
    plan = testplan.optimise([item(1, ["ldl"], 10), item(2, ["glucose"], 50), panel], {"ldl", "glucose"},
                             forced=[panel])
    assert [i["id"] for i in plan["items"]] == ["p", "2"] and plan["missing"] == []


def test_returned_items_are_copies():
    shared = item(1, ["ldl"], 10)
    testplan.optimise([shared], {"ldl"})["items"][0]["covers_names"] = ["changed"]
    assert "covers_names" not in shared and "forced" not in shared


def test_pins_are_per_lab():
    esculab, synevo = item("296", ["a"], 100), item("296", ["b"], 100, lab="synevo", fees=())
    plan = testplan.optimise([esculab, synevo], {"a", "b"}, forced=[esculab])
    assert sorted((i["lab"], i["forced"]) for i in plan["items"]) == [("esculab", True), ("synevo", False)]


def test_kinds_follow_the_labs_own_shelves():
    assert testplan.item_kind(item(1, ["ldl"], 1)) == "single"
    assert testplan.item_kind(item(2, ["a", "b"], 1)) == "set"
    # One "parameter", but a gene panel: never offered as a cholesterol value.
    assert testplan.item_kind(item(3, ["esculab:9"], 1, groups=["Генетичні дослідження", "Генетика"])) == "genetic"
    assert testplan.item_kind(item(4, ["x"], 1, lab="synevo", groups=["what-to-check/genetic-tests"])) == "genetic"
    assert testplan.item_kind(item(5, ["x"], 1, lab="synevo", groups=["check-up/mens"])) == "set"
    assert testplan.item_kind(item(6, ["x"], 1, groups=["Пакетні пропозиції"])) == "set"


def test_a_ceiling_prunes_and_says_whether_it_was_beaten():
    items = [item(1, ["a"], 100), item(2, ["b"], 100), item(3, ["a", "b"], 150)]
    beaten = testplan.optimise(items, {"a", "b"}, ceiling=300)
    assert beaten["cost"] == 230 and beaten["beats_ceiling"]
    # Nothing under 200 exists: a real cover still comes back, flagged.
    unbeaten = testplan.optimise(items, {"a", "b"}, ceiling=200)
    assert unbeaten["cost"] == 230 and not unbeaten["beats_ceiling"] and unbeaten["covered"] == ["a", "b"]
    assert testplan.optimise(items, {"a", "b"})["beats_ceiling"]


def test_a_bundle_named_as_one_is_a_set_even_with_one_result_row():
    assert testplan.item_kind(item(7, ["esculab:1"], 1, params=[{"id": "1", "name": "Панель"}]) | {"name": "Панель целіакії"}) == "set"
    assert testplan.item_kind(item(8, ["x"], 1) | {"name": "Пакет №56. Білкові фракції"}) == "set"
    # «Комплексна …» is a word of its own, not a bundle name.
    assert testplan.item_kind(item(9, ["x"], 1) | {"name": "Комплексна оцінка заліза"}) == "single"


def test_synevo_shelves_are_named_and_esculab_keeps_its_first_shelf():
    from anamna.web.testplan_routes import _shelves

    labs = {"synevo": [item("s1", ["a", "b"], 1, lab="synevo", groups=["check-up/mens", "panel/zzz"])],
            "esculab": [item("e1", ["a", "b"], 1, groups=["Пакетні пропозиції", "Пакет №1"])]}
    rows = _shelves(labs, {"check-up/mens": "Чекап · Чоловічий"})
    assert [(r["value"], r["name"], r["count"]) for r in rows] == [
        ("esculab:Пакетні пропозиції", "Пакетні пропозиції", 1), ("synevo:check-up/mens", "Чекап · Чоловічий", 1)]


def test_children_packages_are_recognised_by_name_not_shelf():
    from anamna.testplan import for_children

    assert for_children({"name": "Програма «Дитячий Check-UP»"})
    assert for_children({"name": "Пакет №155 (Здоров'я дитини)"})
    assert for_children({"name": "Пакет №351 (Перевір свою дитину! + звіт з описом лабораторних показників)"})
    # Synevo's children's check-up shelf also holds tests adults take.
    assert not for_children({"name": "ALEX3-тест (молекулярний аналіз на 300 алергенів, антитіла IgE)",
                             "groups": ["check-up/childrens", "panel/allergological-panel"]})
    # A paternity test names a child but is taken by adults too.
    assert not for_children({"name": "ДНК-тест на встановлення батьківства (батько/мати + дитина)"})
    # Synevo shelves plain ferritin "for children" as well.
    assert not for_children({"name": "Феритин", "groups": ["for-whom/tests-for-children"]})
