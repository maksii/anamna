"""Coverage and integrity of the curated reference library (CLAUDE.md rule 8).

The library is data, so its failure modes are silent: a band that cites a
source id nobody defined, a region claimed that no cited source supports, a
Ukrainian page that falls back to an English note, a concept the parser emits
with no guidance at all.  Each check here pins one of those.
"""

import json
from pathlib import Path

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.ingest.pipeline import seed_concepts
from anamna.reference import LIBRARY_PATH, evaluate

LIBRARY = json.loads(Path(LIBRARY_PATH).read_text(encoding="utf-8"))
SOURCES = {source["id"]: source for source in LIBRARY["sources"]}
ANALYTES = {entry["concept_id"]: entry for entry in LIBRARY["analytes"]}

# Joint European/North American society publications: filed under one region,
# authored by bodies of both.
JOINT_REGIONS = {
    "esc-naspe-hrv-1996": {"EU", "US"},
    "acr-eular-ra-2010": {"EU", "US"},
    "eular-acr-sle-2019": {"EU", "US"},
    "ers-ats-fwt-2014": {"EU", "US"},
}

# Analytes whose band notes another fix batch translates (it adds `notes_uk`
# support and the Ukrainian for its own entries).
NOTES_OWNED_ELSEWHERE = {
    "ldl-cholesterol", "non-hdl-cholesterol", "apolipoprotein-b", "lipoprotein-a",
    "total-cholesterol", "hdl-cholesterol", "c-reactive-protein",
    "high-sensitivity-c-reactive-protein", "stool-ph", "respiratory_rate", "blood_oxygen",
    "sleep_duration", "white-blood-cell-count", "_allergen_specific_ige",
}


def _cited(entry: dict) -> list[str]:
    ids = list(entry.get("source_ids") or [])
    if entry.get("source_id"):
        ids.append(entry["source_id"])
    for band in entry.get("bands") or []:
        if band.get("source_id"):
            ids.append(band["source_id"])
        ids.extend(band.get("corroborated_by") or [])
    return ids


def _regions(entry: dict) -> set[str]:
    regions: set[str] = set()
    for source_id in _cited(entry):
        if SOURCES.get(source_id, {}).get("region"):
            regions.add(SOURCES[source_id]["region"])
        regions |= JOINT_REGIONS.get(source_id, set())
    return regions


@pytest.fixture
def connection(tmp_path: Path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    with connect(settings) as conn:
        seed_concepts(conn)
        yield conn


def test_every_source_carries_region_and_official_flag():
    for source in LIBRARY["sources"]:
        assert source.get("region") in {"US", "EU", "UA", "INT"}, source["id"]
        assert isinstance(source.get("official"), bool), source["id"]
        assert source["url"].startswith("https://"), source["id"]


def test_every_cited_source_exists_and_regions_match_the_citations():
    for concept_id, entry in ANALYTES.items():
        for source_id in _cited(entry):
            assert source_id in SOURCES, (concept_id, source_id)
        if entry.get("regions_covered") is not None:
            assert set(entry["regions_covered"]) == _regions(entry), concept_id


def test_every_band_note_has_ukrainian():
    for concept_id, entry in ANALYTES.items():
        if concept_id in NOTES_OWNED_ELSEWHERE or concept_id.startswith("weekly-"):
            continue
        for band in entry.get("bands") or []:
            if band.get("note"):
                assert band.get("notes_uk"), (concept_id, band["label"])
                # A Ukrainian note that is the English one copied over is no translation.
                assert band["notes_uk"] != band["note"], (concept_id, band["label"])


def test_every_band_label_and_prose_ships_in_ukrainian():
    for concept_id, entry in ANALYTES.items():
        uk = entry.get("uk") or {}
        assert uk.get("short_description") and uk.get("why_it_matters"), concept_id
        for band in entry.get("bands") or []:
            assert band["label"] in (uk.get("band_labels") or {}), (concept_id, band["label"])


# Concepts the parser emits (sandbox audit 2026-11-06 contract §1, CLIN-37, OPS-08)
# that previously had no guidance at all.
REQUIRED_ENTRIES = [
    # new concepts
    "neutrophils-absolute", "segmented-neutrophils", "band-neutrophils",
    "neutrophils-manual-differential", "lymphocytes-manual-differential",
    "monocytes-manual-differential", "eosinophils-manual-differential",
    "basophils-manual-differential", "hepatitis-b-core-antibodies-total-anti-hbc",
    "urine-erythrocytes-dipstick", "urine-leukocytes-dipstick",
    "urine-leukocytes-per-high-power-field", "urine-erythrocytes-per-high-power-field",
    "estimated-glomerular-filtration-rate-ckd-epi-2021", "left-ventricular-mass-index",
    "carotid-intima-media-thickness", "peak-systolic-velocity-common-carotid-artery",
    "liver-craniocaudal-size", "common-bile-duct-diameter", "bladder-wall-thickness",
    "thyroid-volume",
    # urine sediment analyser channels
    "crystals-in-urine", "epithelial-cells-in-urine", "non-hyaline-casts-in-urine",
    "non-squamous-epithelial-cells-in-urine", "total-casts-in-urine",
    # antibiotic susceptibilities
    *(f"{drug}-susceptibility" for drug in (
        "amoxicillin-clavulanate", "amoxicillin", "ampicillin-sulbactam", "ampicillin",
        "azithromycin", "benzylpenicillin", "cefaclor", "cefalexin", "cefazolin",
        "cefotaxime", "cefpodoxime", "ceftriaxone", "cefuroxime", "clarithromycin",
        "clindamycin", "doxycycline", "ertapenem", "erythromycin", "linezolid",
        "minocycline", "moxifloxacin", "piperacillin", "roxithromycin", "tetracycline",
        "tigecycline", "trimethoprim-sulfamethoxazole",
    )),
    # device metrics (OPS-08)
    "cardiovascular_age", "pulse_wave_velocity", "elevation", "light_activity",
    "sedentary_minutes", "sleep_nap_duration", "sleep_naps", "swimming_strokes",
    "total_energy",
]


@pytest.mark.parametrize("concept_id", REQUIRED_ENTRIES)
def test_required_concept_has_sourced_guidance(concept_id):
    entry = ANALYTES.get(concept_id)
    assert entry is not None, concept_id
    assert _cited(entry), concept_id
    assert entry["uk"].get("name"), concept_id


def test_susceptibility_is_never_given_a_universal_number():
    for concept_id, entry in ANALYTES.items():
        if concept_id.endswith("-susceptibility"):
            assert entry["kind"] == "no_universal_target", concept_id
            assert not entry["bands"], concept_id


# CLIN-37: the concepts that cited no Ukrainian source.  Each now either cites
# one or says, in the entry, that none exists and what was searched.
NEEDED_A_UKRAINIAN_ANSWER = [
    "band-neutrophils", "basophils", "eosinophils", "granulocytes", "granulocytes-absolute",
    "immature-granulocytes", "lymphocytes", "lymphocytes-absolute", "mean-platelet-volume",
    "metamyelocytes", "mixed-white-cells", "mixed-white-cells-absolute", "monocytes",
    "myelocytes", "neutrophils", "platelet-distribution-width", "platelet-distribution-width-sd",
    "platelet-large-cell-ratio", "plateletcrit", "promyelocytes",
    "red-cell-distribution-width-cv", "red-cell-distribution-width-sd",
    "quick-prothrombin-index", "whole-blood-folate", "red-cell-folate-calculation-hematocrit",
    "brown-pigmented-casts-in-urine", "epithelial-casts-in-urine", "granular-casts-in-urine",
    "hyaline-casts-in-urine", "squamous-epithelial-cells-in-urine",
    "transitional-epithelial-cells-in-urine", "urine-amorphous-phosphates",
    "urine-amorphous-urates", "urine-atypical-like-cells", "urine-bacteria",
    "urine-bladder-epithelial-cells", "urine-changed-erythrocytes", "urine-erythrocyte-casts",
    "urine-erythrocytes", "urine-erythrocytes-unchanged", "urine-leukocyte-casts",
    "urine-leukocyte-clusters", "urine-leukocyte-esterase", "urine-leukocytes",
    "urine-mucus-elements", "urine-nitrite", "urine-salts", "urine-sperm-cells",
    "urine-yeast-like-cells", "waxy-casts-in-urine",
    "ama-m2-antibodies", "cenp-b-antibodies", "double-stranded-dna-antibodies",
    "gp210-antibodies", "jo-1-antibodies", "ku-antibodies", "la-ss-b-antibodies",
    "lc1-antibodies", "lkm1-antibodies", "myeloperoxidase-antibodies", "pm-scl-100-antibodies",
    "proteinase-3-antibodies", "ro-ss-a-52-antibodies", "scl-70-antibodies", "sm-antibodies",
    "sp100-antibodies", "srp54-antibodies", "u1-snrnp-antibodies", "thyroglobulin-antibodies",
    "thyroid-peroxidase-antibodies", "free-triiodothyronine", "parathyroid-hormone",
    "total-testosterone", "hla-b27",
    "albumin", "total-protein", "direct-bilirubin", "indirect-bilirubin", "alpha-amylase",
    "lipase", "antistreptolysin-o", "chlamydia-trachomatis-pcr", "mycoplasma-genitalium-pcr",
    "mycoplasma-hominis-dna", "neisseria-gonorrhoeae-dna", "trichomonas-vaginalis-dna",
    "ureaplasma-parvum-dna", "ureaplasma-urealyticum-dna", "h-pylori-stool-antigen",
    "homocysteine", "mumps-virus-igg", "mumps-virus-igm", "pulse-rate", "ecg-recording-duration",
    "stool-form", "blood-pressure-category",
]


@pytest.mark.parametrize("concept_id", NEEDED_A_UKRAINIAN_ANSWER)
def test_ukrainian_source_or_explicit_absence(concept_id):
    entry = ANALYTES[concept_id]
    regions = _regions(entry)
    assert regions, concept_id
    if "UA" not in regions:
        note = entry.get("jurisdiction_note") or ""
        assert "No Ukrainian source" in note, concept_id


@pytest.mark.parametrize(
    ("concept_id", "value", "unit", "sex", "expected"),
    [
        # KDIGO 2024 GFR categories: eGFR arrives with decimals.
        ("estimated-glomerular-filtration-rate-ckd-epi-2021", 90.0, "mL/min/1.73m²", "male", "G1"),
        ("estimated-glomerular-filtration-rate-ckd-epi-2021", 89.6, "mL/min/1.73m²", "male", "G2"),
        ("estimated-glomerular-filtration-rate-ckd-epi-2021", 59.99, "mL/min/1.73m²", "female", "G3a"),
        ("estimated-glomerular-filtration-rate-ckd-epi-2021", 14.5, "mL/min/1.73m²", "female", "G5"),
        # ASE/EACVI 2015 LV mass index limits are sex-specific.
        ("left-ventricular-mass-index", 100.0, "g/m²", "male", "Within"),
        ("left-ventricular-mass-index", 100.0, "g/m²", "female", "hypertrophy"),
        ("left-ventricular-mass-index", 115.4, "g/m²", "male", "hypertrophy"),
        ("carotid-intima-media-thickness", 0.95, "mm", "male", "Thickened"),
        ("neutrophils-absolute", 1.55, "10^9/L", "male", "Slightly below"),
        ("lymphocytes-absolute", 3.7, "10^9/L", "female", "Above the Ukrainian limit"),
    ],
)
def test_new_bands_classify_decimal_values(connection, concept_id, value, unit, sex, expected):
    verdict = evaluate(
        connection, concept_id, value_numeric=value, unit=unit, age_years=40, sex=sex
    )
    assert verdict["authority"] == "curated", verdict
    assert expected in (verdict["band_label"] or ""), verdict


@pytest.mark.parametrize(
    ("printed", "library"),
    [
        ("мм", "mm"),
        ("г/м2", "g/m²"),
        ("г", "g"),
        ("см/с", "cm/s"),
        ("см3", "mL"),
        ("сm3", "mL"),  # Cyrillic «с»
        ("мл/хв/1,73м2", "mL/min/1.73m²"),
        ("мл/хв/1,73 м²", "mL/min/1.73m²"),
    ],
)
def test_report_units_fold_onto_the_library_unit(printed, library):
    """An unfolded spelling silently drops every curated verdict for the concept."""
    from anamna.reference import canonical_unit

    assert canonical_unit(printed) == canonical_unit(library)


def test_no_new_holes_between_bands():
    """Every banded partition is contiguous for each demographic it serves.

    Ferritin is the one deliberate exception: its deficiency and overload
    thresholds are independent publications with an unflagged range between.
    """
    def covered(bands, point):
        for band in bands:
            lower, upper = band["lower"], band["upper"]
            if lower is not None and (point < lower or (point == lower and not band.get("lower_inclusive", True))):
                continue
            if upper is not None and (point > upper or (point == upper and not band.get("upper_inclusive", True))):
                continue
            return True
        return False

    for concept_id, entry in ANALYTES.items():
        if concept_id == "ferritin":
            continue
        groups: dict[tuple, list] = {}
        for band in entry.get("bands") or []:
            if band["lower"] is None and band["upper"] is None or band.get("requires"):
                continue
            key = (band.get("sex") or "any", band.get("age_min"), band.get("age_max"),
                   band.get("unit", entry["unit"]))
            groups.setdefault(key, []).append(band)
        for key, bands in groups.items():
            edges = sorted({x for b in bands for x in (b["lower"], b["upper"]) if x is not None})
            probes = set(edges) | {(a + b) / 2 for a, b in zip(edges, edges[1:])}
            holes = [p for p in sorted(probes) if not covered(bands, p)]
            assert not holes, (concept_id, key, holes)


def test_left_ventricular_mass_grams_are_contiguous_and_178_g_is_normal_for_a_man(connection):
    """178 g is the 2025-02-13 echo's «Індекс маси міокарда ЛШ», which the cube
    formula on the same page shows is grams: normal (88-224 g), not the
    hypertrophy a 178 g/m² index would mean."""
    for sex, edges in (("male", (88, 224, 258, 292)), ("female", (67, 162, 186, 210))):
        for value in sorted({*edges, *(e + 0.5 for e in edges), *(e - 0.5 for e in edges)}):
            verdict = evaluate(
                connection, "left-ventricular-mass", value_numeric=value, unit="г", age_years=33, sex=sex
            )
            assert verdict["authority"] == "curated", (sex, value, verdict)
            assert verdict["band_label"], (sex, value)
    verdict = evaluate(
        connection, "left-ventricular-mass", value_numeric=178, unit="г", age_years=33, sex="male"
    )
    assert verdict["interpretation"] == "normal"
    assert verdict["source_id"] == "ase-eacvi-chamber-quantification-2015"
    assert evaluate(
        connection, "left-ventricular-mass", value_numeric=224.5, unit="g", age_years=33, sex="male"
    )["band_label"] == "Mildly increased (ASE/EACVI)"


@pytest.mark.parametrize("value", [115.0, 117.0])
def test_spleen_in_the_moz_zone_shows_both_readings_never_an_alarm(connection, value):
    verdict = evaluate(connection, "spleen-length", value_numeric=value, unit="мм", age_years=33, sex="male")
    assert verdict["interpretation"] == "borderline"
    assert verdict["source_id"] == "moz-nastanova-00904"
    assert verdict["authorities_disagree"] is True
    readings = {item["source_id"]: item["interpretation"] for item in verdict["authority_positions"]}
    assert readings == {"moz-nastanova-00904": "borderline", "efsumb-ecb2-spleen": "normal"}
