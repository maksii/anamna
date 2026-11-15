"""An import's names and methods must reach the catalogue's existing panels."""

from pathlib import Path

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.ingest.concepts import (
    CONCEPT_DEFINITIONS,
    concept_for_alias,
    refine_definition,
    stable_concept_id,
    specimen_family,
)
from anamna.ingest.pipeline import ensure_concept, ensure_vendor, seed_concepts
from anamna.ingest.text import normalized_key
from anamna.health import concept_display_name, metric_area_ids
from anamna.i18n import activate_locale, reset_locale
from anamna.panels import PANEL_BY_ID, TWIN_OF_DEVICE, panel_for_concept
from anamna.reference import canonical_unit


def test_each_canonical_concept_has_one_definition():
    names = [definition["name"] for definition in CONCEPT_DEFINITIONS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("definition", CONCEPT_DEFINITIONS, ids=lambda item: item["name"])
def test_canonical_names_are_import_aliases(definition):
    assert concept_for_alias(
        str(definition["name"]),
        str(definition.get("value_type", "numeric")),
        category=str(definition["category"]),
    ) is definition


@pytest.mark.parametrize(
    "alias, name",
    [
        ("Hb", "Hemoglobin"),
        ("RDW-CV", "Red cell distribution width, CV"),
        ("RDW-SD", "Red cell distribution width, SD"),
        ("MID%", "Mixed white cells"),
        ("MID#", "Mixed white cells, absolute"),
        ("P-LCR", "Platelet large cell ratio"),
    ],
)
def test_bare_cbc_codes_reach_the_blood_count(alias, name):
    definition = concept_for_alias(alias, "numeric")
    assert definition and definition["name"] == name
    assert panel_for_concept(stable_concept_id(name)).id == "cbc"


def test_canonical_aliases_do_not_drop_method_or_specimen_discriminators(tmp_path: Path):
    settings = Settings(tmp_path / "test.sqlite3", tmp_path / "sources", "audit-secret")
    migrate(settings)
    with connect(settings) as connection:
        seed_concepts(connection)
        seeded_aliases = {
            (row[0], row[1])
            for row in connection.execute(
                "SELECT concept_id, normalized_alias FROM concept_aliases WHERE vendor_id IS NULL"
            )
        }
        for definition in CONCEPT_DEFINITIONS:
            assert (
                stable_concept_id(str(definition["name"])), normalized_key(str(definition["name"]))
            ) in seeded_aliases
        vendor = ensure_vendor(connection, "Synthetic laboratory", None)
        for name, expected in (
            ("Neutrophils", "neutrophils"),
            ("Neutrophils (manual differential)", "neutrophils-manual-differential"),
            ("Mean corpuscular volume", "mean-corpuscular-volume"),
            ("Urine leukocytes (dipstick)", "urine-leukocyte-esterase"),
            ("Urine leukocytes per high-power field", "urine-leukocytes-per-high-power-field"),
        ):
            assert ensure_concept(connection, name, vendor)[0] == expected
        assert refine_definition(
            concept_for_alias("Pulse rate"), clinical_type="electrocardiogram"
        )["name"] == "ECG heart rate"
        assert refine_definition(
            concept_for_alias("C-reactive protein"), reference="<1 low risk; 1–3 average risk"
        )["name"] == "High-sensitivity C-reactive protein"
        assert concept_for_alias("Stool pH", specimen="stool")["name"] == "Stool pH"
        assert concept_for_alias("Urine pH", specimen="urinalysis")["name"] == "Urine pH"


def test_temperature_and_fitness_age_are_reachable_on_their_panels():
    assert TWIN_OF_DEVICE["body_temperature"] == ("body-temperature", "same")
    assert panel_for_concept("body-temperature").id == "vitals"
    assert "fitness_age" in PANEL_BY_ID["cardio_fitness"].device_members


def test_albumin_globulin_ratio_declares_its_dimensionless_unit():
    definition = concept_for_alias("Albumin to globulin ratio")
    assert definition["unit"] == "ratio"
    assert panel_for_concept(stable_concept_id(definition["name"])).id == "liver"


def test_atherogenic_ratios_require_the_named_quantity():
    assert concept_for_alias("atherogenic coefficient")["name"] == "Atherogenic coefficient"
    assert concept_for_alias("atherogenic index") is None
    assert concept_for_alias("atherogenic index of plasma") is None


@pytest.mark.parametrize("prefix", ["Ig G до Хелікобактер пілорі", "Антитіла IgG", "Дихальний тест"])
def test_h_pylori_parenthetical_name_cannot_drop_the_known_test_method(prefix):
    assert concept_for_alias(f"{prefix} (Helicobacter pylori)") is None


@pytest.mark.parametrize(
    "label,unit,expected",
    [
        ("Ретикулоцити", "10^6/мкл", "Reticulocytes, absolute"),
        ("Reticulocytes", "10^9/L", "Reticulocytes, absolute"),
        ("Ретикулоцити", "%", "Reticulocytes"),
        ("Ретикулоцити %", "%", "Reticulocytes"),
        ("Фракція незрілих ретикулоцитів", "%", "Immature reticulocyte fraction"),
        ("Антимюллерів гормон Advanced (АМГ, AMH Advanced)", "ng/mL", "Anti-Mullerian hormone"),
        ("Індекс HOMA", None, "HOMA index (reported, model unspecified)"),
        ("Індекс ROMA пременопауза", "%", "ROMA, premenopausal"),
        ("Індекс ROMA постменопауза", "%", "ROMA, postmenopausal"),
        ("Helicobacter pylori", None, "H. pylori test, method unspecified"),
        ("Базовий рівень водню (H2)", "ppm", "Breath hydrogen"),
    ],
)
def test_missing_reported_quantities_keep_their_method_and_fraction(label, unit, expected):
    definition = refine_definition(concept_for_alias(label), unit=unit)
    assert definition["name"] == expected


def test_new_panels_and_locales_reach_their_measurements():
    amino = [d for d in CONCEPT_DEFINITIONS if str(d["name"]).endswith(", serum or plasma")]
    assert len(amino) == 39
    assert {stable_concept_id(d["name"]) for d in amino} == set(PANEL_BY_ID["amino_acids"].members)
    for panel_id, area in (("celiac", "digestive"), ("folate_genetics", "metabolism"),
                           ("ovarian_risk", "reproductive")):
        for name in PANEL_BY_ID[panel_id].member_names:
            definition = next(d for d in CONCEPT_DEFINITIONS if d["name"] == name)
            assert area in metric_area_ids(name, definition["category"])
    for definition in CONCEPT_DEFINITIONS[-73:]:
        assert (panel_for_concept(stable_concept_id(definition["name"]), definition["category"])
                or definition["name"] == "Blood count comment")
        token = activate_locale("uk")
        try:
            assert concept_display_name(definition["name"]) != definition["name"]
        finally:
            reset_locale(token)


@pytest.mark.parametrize("label", ["Alanine", "Аланін", "Cortisol", "Pancreatic amylase"])
def test_blood_aliases_do_not_claim_other_specimens(label):
    assert concept_for_alias(label, specimen="hematology")
    assert concept_for_alias(label, specimen="urinalysis") is None
    assert concept_for_alias(label, specimen="stool") is None
    assert concept_for_alias(label, specimen="saliva") is None
    assert concept_for_alias(label, specimen="csf") is None


@pytest.mark.parametrize("label,family", [("сеча", "urinalysis"), ("слина", "saliva"),
                                          ("ліквор", "csf"), ("CSF", "csf")])
def test_blood_cortisol_does_not_claim_explicit_other_material(label, family):
    assert specimen_family(label) == family
    assert concept_for_alias("Cortisol", specimen=family) is None


def test_a_bare_serum_bound_name_obeys_a_urine_category():
    assert concept_for_alias("Taurine", category="urinalysis") is None
    assert concept_for_alias("Taurine", specimen="hematology")["name"] == "Taurine, serum or plasma"
    # A label naming its blood specimen is stronger than a mixed-order title.
    assert concept_for_alias("Serum cortisol", category="urinalysis")["name"] == "Cortisol"


def test_learned_blood_alias_cannot_relabel_a_urine_sample(tmp_path):
    settings = Settings(tmp_path / "test.sqlite3", tmp_path / "sources", "audit-secret")
    migrate(settings)
    with connect(settings) as connection:
        seed_concepts(connection)
        vendor = ensure_vendor(connection, "Synthetic laboratory", None)
        blood, _ = ensure_concept(connection, "Alanine", vendor, specimen="serum", unit_raw="µmol/L")
        urine, _ = ensure_concept(connection, "Alanine", vendor, specimen="urine", unit_raw="µmol/L")
        assert blood == "alanine-serum-or-plasma"
        assert urine != blood


@pytest.mark.parametrize(
    "printed,expected",
    [("10^6/мкл", "10^12/l"), ("мМО/мл", "iu/l"), ("мкМО/мл", "miu/l"),
     ("нгФЕОд/мл", "ng/mlfeu"), ("мкг/дл", "ug/dl"), ("Titer", "titer")],
)
def test_reporting_units_keep_prefixes_and_d_dimer_calibration(printed, expected):
    assert canonical_unit(printed) == expected
