"""One printed word, several measurements: the method decides the concept.

Each case is a pair of rows from a real report in the record that used to
share one concept -- and therefore one trend, one-per-day deduplication and
one verdict -- although they measure different things.
"""

from __future__ import annotations

import pytest

from anamna.ingest.concepts import (
    CONCEPT_DEFINITIONS,
    clean_label,
    concept_for_alias,
    refine_definition,
    stable_concept_id,
)
from anamna.locales.concepts_uk import CONCEPT_NAMES_UK
from anamna.panels import PANELS


def resolve(label, value_type="numeric", category=None, **row):
    definition = refine_definition(concept_for_alias(label, value_type, category), **row)
    return definition and definition["name"]


@pytest.mark.parametrize(
    "printed, expected",
    [
        # Analyser (5-part) rows: «(на 100 лейкоцитів)», «(абс.)», channel codes.
        ("Нейтрофіли (на 100 лейкоцитів)", "Neutrophils"),
        ("Нейтрофіли (абс.)", "Neutrophils, absolute"),
        ("NEUT#", "Neutrophils, absolute"),
        ("Лімфоцити (на 100 лейкоцитів)", "Lymphocytes"),
        ("Відносне значення лімфоцитів (LYM%)", "Lymphocytes"),
        ("Моноцити (на 100 лейкоцитів)", "Monocytes"),
        ("Еозинофіли (на 100 лейкоцитів)", "Eosinophils"),
        ("Базофіли (на 100 лейкоцитів)", "Basophils"),
        # The three-part granulocyte channel is not the neutrophil count.
        ("Абсолютне значення гранулоцитів (GRA#)", "Granulocytes, absolute"),
        # Smear (manual) rows: bare names, Esculab's (Lymph)/(Mid), and the
        # segmented/band split no analyser prints.
        ("Сегментоядерні нейтрофіли", "Segmented neutrophils"),
        ("Нейтрофіли сегментоядерні", "Segmented neutrophils"),
        ("Сегментоядерні нейтрофіли (NEUT)", "Segmented neutrophils"),
        ("Паличкоядерні нейтрофіли (BAND)", "Band neutrophils"),
        ("Лімфоцити", "Lymphocytes (manual differential)"),
        ("Лімфоцити (Lymph)", "Lymphocytes (manual differential)"),
        ("Моноцити", "Monocytes (manual differential)"),
        ("Моноцити (Mid)", "Monocytes (manual differential)"),
        ("Еозинофіли", "Eosinophils (manual differential)"),
        ("Базофіли", "Basophils (manual differential)"),
    ],
)
def test_analyser_and_smear_differentials_are_separate_series(printed, expected):
    """Synevo 2025-08-28 prints 50.1 % analyser neutrophils above a smear's
    50 % segmented; Esculab 45.0 % lymphocytes above the smear's 43 %."""
    assert resolve(printed) == expected


@pytest.mark.parametrize(
    "printed, unit, value_text, reference, expected",
    [
        # Synevo: one word, two methods; only the unit tells them apart.
        ("Лейкоцити", "Leu/µL", "не виявлені", None, "Urine leukocytes (dipstick)"),
        ("Лейкоцити", "в п/з", "до 5.0", None, "Urine leukocytes per high-power field"),
        ("Еритроцити", "Ery/µL", "не виявлені", None, "Urine erythrocytes (dipstick)"),
        # St. Paraskeva writes the field into the value.
        ("Urine leukocytes", None, "1-2 в п/з", "1 - 6 в п/з", "Urine leukocytes per high-power field"),
        # Esculab automated sediment: counts per microlitre stay on the base concept.
        ("Лейкоцити в мкл (WBC)", "кл/мкл", None, "жінки < 28.0", "Urine leukocytes"),
        ("Еритроцити в мкл (RBC)", "кл/мкл", None, "чоловіки < 10", "Urine erythrocytes"),
        # Labels that name the strip or the field themselves.
        ("Лейкоцити (C-LEU)", "кл/мкл", None, None, "Urine leukocytes (dipstick)"),
        ("Лейкоцити в сечі, кл/мкл", None, "негативний", None, "Urine leukocytes (dipstick)"),
        ("Еритроцити/гемоглобін (C-BLD)", "мг/дл", "не виявлені (-)", None, "Urine erythrocytes (dipstick)"),
        ("Еритроцити (за активністю пероксидази), кл/мкл", None, "негативний", None, "Urine erythrocytes (dipstick)"),
        ("Лейкоцити (WBC), в п/з", None, "0-1", "0-5", "Urine leukocytes per high-power field"),
        # The analyser's unchanged cells are per microlitre, the microscopy's per field.
        ("Незмінені еритроцити (NL RBC)", "кл/мкл", None, None, "Urine erythrocytes, unchanged (per microlitre)"),
        ("Еритроцити не змінені, в п/з", None, "0-0-1", "0-2", "Urine erythrocytes, unchanged"),
    ],
)
def test_urine_strip_microscopy_and_counts_are_separate_series(printed, unit, value_text, reference, expected):
    for value_type in ("numeric", "text"):
        assert resolve(
            printed, value_type, "urinalysis", unit=unit, value_text=value_text, reference=reference
        ) == expected


def test_the_leukocyte_strip_keeps_the_esterase_id():
    assert stable_concept_id("Urine leukocytes (dipstick)") == "urine-leukocyte-esterase"


def test_standard_crp_and_hs_crp_are_separate():
    """A standard CRP of 3.6 mg/L («до 5») was judged on hs-CRP risk tiers."""
    assert resolve("С-реактивний білок", reference="до 5") == "C-reactive protein"
    assert resolve("C-reactive protein", reference="<5") == "C-reactive protein"
    # Latin C, Cyrillic rest -- the homoglyph fold.
    assert resolve("C-реактивний білок") == "C-reactive protein"
    assert resolve("hs-CRP") == "High-sensitivity C-reactive protein"
    assert resolve("С-реактивний білок високочутливий") == "High-sensitivity C-reactive protein"
    assert resolve(
        "С-реактивний білок", reference="<1 низький ризик; 1-3 середній ризик"
    ) == "High-sensitivity C-reactive protein"


def test_an_ecg_rate_is_not_a_cuff_pulse():
    assert resolve("Pulse rate", clinical_type="electrocardiogram") == "ECG heart rate"
    assert resolve("Pulse rate", clinical_type="blood_pressure") == "Pulse rate"


def test_hepatitis_c_total_antibodies_are_one_concept():
    synevo = resolve("Вірус гепатиту C (HCV), антитіла сумарні")
    esculab = resolve("HCV антитіла сумарні")
    assert synevo == esculab == "Hepatitis C total antibodies"


def test_anti_hbc_is_renamed_and_keeps_its_address():
    assert resolve("Вірус гепатиту B (HBV), HBcorAg") == "Hepatitis B core antibodies, total (anti-HBc)"
    assert resolve("anti-HBc") == "Hepatitis B core antibodies, total (anti-HBc)"
    assert stable_concept_id("Hepatitis B core antibodies, total (anti-HBc)") == "hepatitis-b-core-antigen-marker"


@pytest.mark.parametrize(
    "printed, expected",
    [
        ("Кристали сечової кислоти", "Uric acid crystals in urine"),
        ("Кристали оксалату кальцію", "Calcium oxalate crystals in urine"),
        ("Кристали трипельфосфатів", "Triple phosphate crystals in urine"),
        ("Кристали фосфату кальцію", "Calcium phosphate crystals in urine"),
        ("Кристали фосфорнокислого вапна", "Phosphate of lime crystals in urine"),
        ("Кристали карбонату кальцію", "Calcium carbonate crystals in urine"),
        ("Кристали біурата амонію", "Ammonium biurate crystals in urine"),
        ("Кристали білірубіну", "Bilirubin crystals in urine"),
        # OCR read «Іміпенем» glyph by glyph as Latin.
        ("ImineHem", "Imipenem susceptibility"),
    ],
)
def test_text_results_that_minted_ukrainian_only_concepts_now_resolve(printed, expected):
    assert resolve(printed, "text") == expected


@pytest.mark.parametrize(
    "printed, value_type, category, expected",
    [
        # St. Paraskeva's printed labels, as the parser now stores them.  Its
        # analyser is three-part: GRAN and MID are channels, not cell types.
        ("ШОЕ (SER)", "numeric", None, "Erythrocyte sedimentation rate"),
        ("Ширина розподілу еритроцитів (RDW)", "numeric", None, "Red cell distribution width, CV"),
        ("Нейтрофіли (GRAN)-абс.", "numeric", None, "Granulocytes, absolute"),
        ("Нейтрофіли (GRAN)-%", "numeric", None, "Granulocytes"),
        ("Лімфоцити (LYM)-абс.", "numeric", None, "Lymphocytes, absolute"),
        ("Лімфоцити (LYM)-%", "numeric", None, "Lymphocytes"),
        ("Моноцити (MID)-абс.", "numeric", None, "Mixed white cells, absolute"),
        ("Моноцити (MID)-%", "numeric", None, "Mixed white cells"),
        ("Питома густина", "numeric", "urinalysis", "Urine specific gravity"),
        ("pH", "numeric", "urinalysis", "Urine pH"),
        ("Епітелій плоский", "text", "urinalysis", "Squamous epithelial cells in urine"),
        ("Епітелій перехідний", "text", "urinalysis", "Transitional epithelial cells in urine"),
        ("Епітелій нирковий", "text", "urinalysis", "Renal epithelial cells in urine"),
        ("Циліндри буропігментовані", "text", "urinalysis", "Brown-pigmented casts in urine"),
        ("Циліндри восковидні", "text", "urinalysis", "Waxy casts in urine"),
        ("Еритроцити (змінені)", "text", "urinalysis", "Urine changed erythrocytes"),
        ("Вітамін D загальний", "numeric", None, "25-hydroxyvitamin D"),
        ("Швидкий тест для виявлення поверхневого антигену до вірусу гепатиту В (HBsAg)", "text", None,
         "Hepatitis B surface antigen rapid test"),
    ],
)
def test_printed_labels_the_parser_now_keeps_resolve(printed, value_type, category, expected):
    assert resolve(printed, value_type, category) == expected


def test_joined_allergen_names_resolve_to_the_fragment_their_concept_has():
    assert clean_label("Anisakis simplex Ani s 1 Kunitz Serin Protease Inhibitor") == "Ani s 1"
    assert clean_label("Подорожник ланцетолистий Pla l") == "Подорожник ланцетолистий"
    assert clean_label("Пшениця Tri a aA_TI Alpha-Amylase Trypsin-Inhibitor") == "Tri a aA_TI"
    assert clean_label("Bet v 1 PR-10") == "Bet v 1 PR-10"


def test_a_wrapped_multiplier_is_not_part_of_an_organism_name():
    assert clean_label("Staphylococcus aureus 1.0 x") == "Staphylococcus aureus"
    assert clean_label("Streptococcus mitis oralis 1.0 x") == "Streptococcus mitis oralis"
    assert clean_label("Вітамін B12") == "Вітамін B12"


@pytest.mark.parametrize(
    "printed, expected",
    [
        ("Середній вміст гемоглобіну в еритроциті (МСН)", "Mean corpuscular hemoglobin"),
        ("Середній вміст гемоглобіну в еритроциті (MCH)", "Mean corpuscular hemoglobin"),
        ("Вірус гепатиту В (HBV), HBsAg", "Hepatitis B surface antigen"),
        ("Вірус гепатиту B (HBV), HBsAg", "Hepatitis B surface antigen"),
        ("Гематокрит (НСТ)", "Hematocrit"),
    ],
)
def test_latin_and_cyrillic_homoglyphs_resolve_alike(printed, expected):
    assert resolve(printed) == expected


@pytest.mark.parametrize(
    "printed, expected",
    [
        ("Індекс маси міокарда ЛШ", "Left ventricular mass index"),
        ("Маса міокарда ЛШ", "Left ventricular mass"),
        ("ММЛШ", "Left ventricular mass"),
        ("Товщина КІМ", "Carotid intima-media thickness"),
        ("PSV", "Peak systolic velocity, common carotid artery"),
        ("Косий вертикальний (по середньо-ключичній лінії)", "Liver craniocaudal size"),
        ("Холедох", "Common bile duct diameter"),
        ("Товщина стінки сечового міхура", "Bladder wall thickness"),
        ("Сумарний об'єм", "Thyroid volume"),
        ("eGFR", "Estimated glomerular filtration rate (CKD-EPI 2021)"),
        ("рШКФ", "Estimated glomerular filtration rate (CKD-EPI 2021)"),
    ],
)
def test_imaging_and_derived_concepts_resolve(printed, expected):
    assert resolve(printed) == expected


def test_every_definition_has_a_ukrainian_name_and_its_english_name_as_alias_where_new():
    """Search finds a concept by either language's name."""
    missing = [str(d["name"]) for d in CONCEPT_DEFINITIONS if str(d["name"]) not in CONCEPT_NAMES_UK]
    assert not missing
    for name in (
        "Neutrophils, absolute", "Segmented neutrophils", "Neutrophils (manual differential)",
        "Lymphocytes (manual differential)", "Monocytes (manual differential)",
        "Eosinophils (manual differential)", "Basophils (manual differential)",
        "High-sensitivity C-reactive protein", "Urine erythrocytes (dipstick)",
        "Urine leukocytes (dipstick)", "Urine leukocytes per high-power field",
        "Urine erythrocytes per high-power field",
        "Estimated glomerular filtration rate (CKD-EPI 2021)", "Left ventricular mass index",
        "Left ventricular mass", "Carotid intima-media thickness", "Peak systolic velocity, common carotid artery",
        "Liver craniocaudal size", "Common bile duct diameter", "Bladder wall thickness",
        "Thyroid volume", "Hepatitis B core antibodies, total (anti-HBc)", "ECG heart rate",
    ):
        assert resolve(name, None) == name, name


def test_no_two_definitions_share_a_folded_alias_except_by_specimen():
    from anamna.ingest.concepts import _ALIAS_INDEX

    shared = {key: [d["category"] for d in found] for key, found in _ALIAS_INDEX.items() if len(found) > 1}
    for key, categories in shared.items():
        assert len(set(categories)) == len(categories), (key, categories)


def test_new_concepts_sit_in_their_panels():
    members = {panel.id: set(panel.member_names) for panel in PANELS}
    assert {"Neutrophils, absolute", "Segmented neutrophils", "Lymphocytes (manual differential)"} <= members["cbc"]
    assert "Estimated glomerular filtration rate (CKD-EPI 2021)" in members["kidney"]
    assert "High-sensitivity C-reactive protein" in members["inflammation"]
