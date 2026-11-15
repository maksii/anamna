"""Adversarial catalog/planner regressions using synthetic observations only."""

import pytest

from anamna import testplan, testplan_aliases, testplan_special
from anamna.ingest.concepts import concept_for_alias, refine_definition, specimen_family
from anamna.panels import panel_for_concept


def offering(parameter_id, name, *, context=None):
    return {"id": parameter_id, "code": parameter_id, "name": context or name,
            "parameters": [{"id": parameter_id, "name": name}], "price": 10,
            "final_price": 10, "fees": [], "synonyms": []}


@pytest.mark.parametrize("label", ["Сечовина", "Сечова кислота", "сечовина (urea)"])
def test_urea_and_uric_acid_do_not_establish_a_urine_specimen(label):
    assert specimen_family(label) is None


@pytest.mark.parametrize("label", ["сеча", "у сечі", "сечу", "urine"])
def test_urine_specimen_still_resolves(label):
    assert specimen_family(label) == "urinalysis"


@pytest.mark.parametrize("label", [
    "Кортизол (cortisol) у слині", "Cortisol (cortisol) saliva",
    "Креатинін (creatinine) у добовій сечі", "Creatinine (creatinine) urine",
    "Glucose (glucose) CSF", "Glucose (glucose) cerebrospinal fluid",
])
def test_bracketed_code_cannot_drop_a_qualifier_after_the_code(label):
    assert concept_for_alias(label) is None


@pytest.mark.parametrize("name", [
    "Neutrophils", "Lymphocytes", "Monocytes", "Eosinophils", "Basophils",
    "Immature granulocytes", "Granulocytes", "Mixed white cells",
])
def test_explicit_differential_unit_selects_absolute_or_percentage(name):
    definition = concept_for_alias(name)
    assert refine_definition(definition, unit="10^9/L")["name"] == f"{name}, absolute"
    absolute = concept_for_alias(f"{name}, absolute")
    assert refine_definition(absolute, unit="% Atypical")["name"] == f"{name}, absolute"
    assert refine_definition(absolute, unit="%")["name"] == name
    assert refine_definition(definition, unit="%")["name"] == name


def test_manual_differential_is_never_reclassified_as_automated_by_unit():
    manual = concept_for_alias("Lymphocytes (manual differential)")
    assert refine_definition(manual, unit="10^9/L") is manual


@pytest.mark.parametrize("family", ["saliva", "CSF", "urine"])
def test_planner_does_not_reuse_blood_aliases_for_another_specimen(family):
    aliases = {"cortisol": [("Synthetic lab", "cortisol")]}
    assert testplan.resolve("Cortisol", family, "Synthetic lab", aliases,
                            {"cortisol": "cortisol", "urine:cortisol": "cortisol"}) is None
    item = offering("unknown", "Cortisol", context=family)
    rows = testplan.keyed([item], "synthetic", "Synthetic lab", aliases,
                         {"id:unknown": "cortisol"}, {})
    assert rows[0]["keys"] == ["synthetic:unknown"]


@pytest.mark.parametrize("name", ["Creatinine", "Albumin", "Blood glucose", "Insulin", "Hemoglobin",
                                 "White blood cell count", "Total cholesterol", "Thyroid stimulating hormone"])
def test_established_blood_quantities_also_obey_explicit_specimens(name):
    assert concept_for_alias(name, specimen="hematology")
    for family in ("urinalysis", "stool", "saliva", "csf"):
        assert concept_for_alias(name, specimen=family) is None
        resolved = testplan.resolve(name, family if family != "urinalysis" else "urine", "Synthetic", {})
        # An explicit blood label still wins over a mixed order's title.
        if specimen_family(name) == "hematology":
            assert resolved
        else:
            assert resolved is None


def test_organ_measurement_does_not_get_a_blood_specimen_from_its_category():
    assert "specimen_family" not in concept_for_alias("Kidney length")
    assert "specimen_family" not in concept_for_alias("Thyroid volume")


def test_equal_value_alone_cannot_teach_an_unrelated_lab_parameter():
    by_value = {5.0: ["hemoglobin"]}
    assert testplan._row_concept("Unrecognised analyte", "5", {}, by_value) is None
    assert testplan._row_concept("Cortisol", "5", {}, by_value) is None
    # A recognized synonym plus the value is positive identity evidence.
    assert testplan._row_concept("Hb", "5", {}, by_value) == "hemoglobin"
    assert testplan._row_concept("Cortisol", "5", {"cortisol": "cortisol"}, {}, "saliva") is None


def test_conflicting_report_mappings_are_not_decided_by_database_row_order():
    learned, conflicts = {}, set()
    row = {"test": "Synthetic analyte", "idtest": "synthetic", "result": "5"}
    for concept in ("albumin", "albumin-fraction", "albumin"):
        testplan._learn_row(learned, row, "esculab", {"synthetic analyte": concept}, {}, conflicts)
    assert "synthetic analyte" not in learned
    assert "id:synthetic" not in learned


def test_ana_method_titre_and_pattern_are_separate_requirements():
    assert testplan_aliases.curated("esculab", "1917") == ("antinuclear-antibodies",)
    assert testplan_aliases.curated("esculab", "1918") == ("x:ana-ift",)
    assert testplan_aliases.curated("esculab", "1919") == ("x:ana-ift-pattern",)
    items = [offering("1919", "ANA pattern")]
    keyed = testplan.keyed(items, "esculab", "Esculab", {}, {}, {})
    assert testplan.optimise(keyed, {"x:ana-ift"})["missing"] == ["x:ana-ift"]


def test_celiac_preset_uses_the_seeded_total_iga_requirement():
    entry = next(e for e in testplan_special.ENTRIES if e.id == "celiac-serology")
    assert "total-immunoglobulin-a" in entry.keys
    assert "x:immunoglobulin-a" not in entry.keys


def test_calculated_globulin_is_a_mass_concentration_distinct_from_fractions():
    definition = concept_for_alias("Globulin, calculated")
    assert definition["unit"] == "g/L"
    assert definition["name"] != concept_for_alias("Gamma globulins")["name"]
    assert panel_for_concept("globulin-calculated").id == "liver"
    assert concept_for_alias("calculated globulin", specimen="urinalysis") is None
