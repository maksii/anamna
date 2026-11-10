"""Pins the reference-band corrections from the 2026-11 band audit.

Each test names the numbered change it guards. Bounds are asserted in the
bracket notation the audit used: ``[a,b)`` is lower inclusive, upper exclusive,
``(a,b]`` is the reverse, and ``None`` means no bound.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "data" / "reference_library.json"


@pytest.fixture(scope="module")
def library_text() -> str:
    return LIBRARY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def library(library_text: str) -> dict:
    return json.loads(library_text)


@pytest.fixture(scope="module")
def analytes(library: dict) -> dict:
    return {analyte["concept_id"]: analyte for analyte in library["analytes"]}


def bands_of(analytes: dict, concept_id: str) -> list[dict]:
    return analytes[concept_id]["bands"]


def interval(band: dict) -> str:
    lower = "None" if band["lower"] is None else str(band["lower"])
    upper = "None" if band["upper"] is None else str(band["upper"])
    left = "[" if band["lower_inclusive"] else "("
    right = "]" if band["upper_inclusive"] else ")"
    return f"{left}{lower},{upper}{right}"


def test_round_trip_is_byte_identical(library: dict, library_text: str) -> None:
    rebuilt = json.dumps(library, ensure_ascii=False, indent=2) + "\n"
    assert rebuilt == library_text
    assert "\r\n" not in library_text


def test_every_band_label_has_a_ukrainian_label(analytes: dict) -> None:
    missing = []
    for concept_id, analyte in analytes.items():
        labels = (analyte.get("uk") or {}).get("band_labels")
        if not labels:
            continue
        for band in analyte.get("bands", []):
            if band["label"] not in labels:
                missing.append((concept_id, band["label"]))
    assert missing == []


# 1. 25-hydroxyvitamin-d: Endocrine Society 2011 cut-offs no longer judge a result.
def test_vitd_endocrine_society_bands_removed(analytes: dict) -> None:
    analyte = analytes["25-hydroxyvitamin-d"]
    assert all(b["source_id"] != "endocrine-society-vitd-2011" for b in analyte["bands"])
    assert "endocrine-society-vitd-2011" in analyte["source_ids"]
    assert "2024 guideline withdrew them" in analyte["divergence_note"]
    assert not any("Endocrine Society 2011" in label for label in analyte["uk"]["band_labels"])
    assert len(analyte["bands"]) == 4


# 2. hs-CRP: cardiovascular risk tiers.
def test_hscrp_bands(analytes: dict) -> None:
    bands = bands_of(analytes, "high-sensitivity-c-reactive-protein")
    assert interval(bands[1]) == "[1.0,3.0]"
    assert interval(bands[2]) == "(3.0,10.0]"
    assert interval(bands[3]) == "(10.0,None)"
    assert bands[2]["lower_inclusive"] is False


# 3. HDL: low, not-low and the US classification boundary at 1.03.
def test_hdl_bands(analytes: dict) -> None:
    bands = bands_of(analytes, "hdl-cholesterol")
    assert interval(bands[0]) == "[None,1.0]"
    assert interval(bands[1]) == "(1.0,None)"
    assert bands[2]["label"] == "Low (US classification)"
    assert interval(bands[2]) == "[None,1.03)"
    assert interval(bands[3]) == "[1.03,1.55)"


# 4. Ionised calcium: contiguous bands.
def test_ionised_calcium_bands(analytes: dict) -> None:
    bands = bands_of(analytes, "calcium-ionized")
    assert interval(bands[1]) == "[1.15,1.3]"
    assert interval(bands[2]) == "(1.3,2.0]"
    assert interval(bands[3]) == "(2.0,None]"


# 5. Ferritin: sex-specific WHO thresholds, borderline band for women, illness band.
def test_ferritin_bands(analytes: dict) -> None:
    bands = bands_of(analytes, "ferritin")
    assert interval(bands[3]) == "[30.0,200.0]" and bands[3]["sex"] == "male"
    assert interval(bands[4]) == "(200.0,None]" and bands[4]["sex"] == "male"
    assert interval(bands[5]) == "[30.0,150.0]" and bands[5]["sex"] == "female"
    assert interval(bands[6]) == "(150.0,200.0]"
    assert bands[6]["sex"] == "female"
    assert bands[6]["interpretation"] == "borderline_high"
    assert bands[6]["label"] == (
        "Above the WHO threshold for menstruating women, not above the one for non-menstruating women"
    )
    assert bands[7]["sex"] == "female" and bands[7]["interpretation"] == "high"
    assert interval(bands[7]) == "(200.0,None]"
    assert bands[7]["label"] == "Possible risk of iron overload (women)"
    assert bands[7]["source_id"] == bands[4]["source_id"]
    assert interval(bands[8]) == "(500.0,None]"
    assert bands[8]["requires"] == ["illness"]
    uk = analytes["ferritin"]["uk"]["band_labels"]
    assert uk["Possible risk of iron overload (women)"] == "Можливий ризик перевантаження залізом (жінки)"
    assert "Possible risk of iron overload (women. WHO menstruating-women threshold, applied to all female profiles)" not in uk


# 6. ApoA1: desirable value boundary.
def test_apoa1_bands(analytes: dict) -> None:
    bands = bands_of(analytes, "apolipoprotein-a1")
    assert interval(bands[0]) == "[None,1.25]"
    assert interval(bands[1]) == "(1.25,None)"


# 7. Absolute eosinophils: borderline recheck and the high band.
def test_eosinophil_bands(analytes: dict) -> None:
    analyte = analytes["eosinophils-absolute"]
    bands = analyte["bands"]
    assert interval(bands[3]) == "[1.5,5.0]"
    assert bands[3]["interpretation"] == "high"
    assert interval(bands[4]) == "(5.0,None]"
    assert analyte["retest_condition"] == {"applies_when": "borderline"}


# 8. LDL: ncep-atp3 US classification boundaries; the band after them is untouched.
def test_ldl_ncep_bands(analytes: dict) -> None:
    bands = bands_of(analytes, "ldl-cholesterol")
    assert interval(bands[14]) == "[None,2.59)"
    assert interval(bands[15]) == "[2.59,3.36)"
    assert interval(bands[16]) == "[3.36,4.14)"
    assert interval(bands[17]) == "[4.14,4.91)"
    assert interval(bands[18]) == "[4.91,None)"
    assert interval(bands[19]) == "[4.9,None)"


# 9. Fibrinogen.
def test_fibrinogen_bands(analytes: dict) -> None:
    bands = bands_of(analytes, "fibrinogen")
    assert interval(bands[1]) == "[1.5,4.0]"
    assert interval(bands[2]) == "(4.0,None)"


# 10. Haematocrit: female bands exclude pregnancy.
def test_hematocrit_bands(analytes: dict) -> None:
    bands = bands_of(analytes, "hematocrit")
    assert interval(bands[1]) == "[39.5,50.0]"
    assert interval(bands[2]) == "(50.0,None)"
    assert interval(bands[4]) == "[34.8,45.9]"
    assert interval(bands[5]) == "(45.9,None)"
    for index in (3, 4, 5):
        assert bands[index]["sex"] == "female"
        assert bands[index]["excludes"] == ["pregnant"]


# 11. Haemoglobin: Nordic reference interval bounds; female bands exclude pregnancy.
def test_hemoglobin_bands(analytes: dict) -> None:
    bands = bands_of(analytes, "hemoglobin")
    assert interval(bands[4]) == "[134,170]"
    assert interval(bands[5]) == "(170,None)"
    assert interval(bands[10]) == "[120,153]"
    assert interval(bands[11]) == "(153,None)"
    for index in range(6, 12):
        assert bands[index]["sex"] == "female"
        assert bands[index]["excludes"] == ["pregnant"]


# 12. Blood pressure: closed upper bounds, crisis bands start exclusive.
def test_blood_pressure_bands(analytes: dict) -> None:
    dbp = bands_of(analytes, "diastolic-blood-pressure")
    assert interval(dbp[2]) == "[90,120]"
    assert interval(dbp[3]) == "(120,None]"
    sbp = bands_of(analytes, "systolic-blood-pressure")
    assert interval(sbp[3]) == "[140,180]"
    assert interval(sbp[4]) == "(180,None]"


# 13. Exercise minutes: weekly amount as a daily equivalent.
def test_exercise_bands(analytes: dict) -> None:
    bands = bands_of(analytes, "exercise_minutes")
    assert interval(bands[0]) == "[None,21.43)"
    assert interval(bands[1]) == "[21.43,42.86)"
    assert interval(bands[2]) == "[42.86,None]"


# 14. Total cholesterol and triglycerides (ncep-atp3 bands only).
def test_total_cholesterol_and_triglyceride_bands(analytes: dict) -> None:
    tc = bands_of(analytes, "total-cholesterol")
    assert interval(tc[3]) == "[None,5.17)"
    assert interval(tc[4]) == "[5.17,6.21)"
    assert interval(tc[5]) == "[6.21,None)"
    tg = bands_of(analytes, "triglycerides")
    assert interval(tg[1]) == "[1.69,2.26)"
    assert interval(tg[2]) == "[2.26,5.65)"
    assert interval(tg[3]) == "[5.65,11.3)"
    assert interval(tg[0]) == "[None,1.7)"
    assert interval(tg[4]) == "[11.3,None)"


# 15. Platelets: sex-neutral transfusion and ITP bands; female copies removed.
def test_platelet_bands(analytes: dict) -> None:
    bands = bands_of(analytes, "platelet-count")
    assert [b["sex"] for b in bands[:3]] == [None, None, None]
    assert sum(1 for b in bands if b["sex"] is None) == 3
    assert len(bands) == 9
    assert [b["sex"] for b in bands[3:6]] == ["male", "male", "male"]
    assert [b["sex"] for b in bands[6:9]] == ["female", "female", "female"]
    assert interval(bands[6]) == "[100,165)"


# 16. Walking speed: gait cut-off applies from age 65.
def test_walking_speed_bands(analytes: dict) -> None:
    analyte = analytes["walking_speed"]
    bands = analyte["bands"]
    assert [b["age_min"] for b in bands] == [65, 65]
    assert bands[1]["label"] == "Above the slow-gait cut-off"
    assert analyte["uk"]["band_labels"]["Above the slow-gait cut-off"] == "Вище порогу повільної ходи"
    assert "At or above the slow-gait cut-off" not in analyte["uk"]["band_labels"]


# 17. TSH: two complete age groups (18-80 and 80 and over), pregnancy excluded, borderline recheck.
def test_tsh_bands(analytes: dict) -> None:
    analyte = analytes["thyroid-stimulating-hormone"]
    bands = analyte["bands"]
    younger = [b for b in bands if b["age_max"] == 80]
    older = [b for b in bands if b["age_min"] == 80]
    assert len(younger) == 4
    assert len(older) == 4
    # Each group runs from no lower bound to no upper bound, with no gap between bands.
    for group, normal_upper in ((younger, 4.0), (older, 7.0)):
        spans = [(b["lower"], b["upper"]) for b in group]
        assert spans == [(None, 0.4), (0.4, normal_upper), (normal_upper, 10.0), (10.0, None)]
        assert [b["interpretation"] for b in group] == ["low", "normal", "borderline_high", "high"]
    for band in bands:
        assert analyte["uk"]["band_labels"][band["label"]]
        assert "pregnant" in band["excludes"]
    assert analyte["retest_condition"] == {"applies_when": "borderline"}


# 18. Red-cell folate: the two female bands apply only when planning pregnancy.
def test_red_cell_folate_requires_planning_pregnancy(analytes: dict) -> None:
    bands = bands_of(analytes, "red-cell-folate-concentration")
    assert bands[3]["requires"] == ["planning_pregnancy"]
    assert bands[4]["requires"] == ["planning_pregnancy"]
    assert "requires" not in bands[0]


# 19. Renal epithelial cells: source moved to EFLM, no retest interval.
def test_renal_epithelial_cells_source_and_retest(analytes: dict) -> None:
    analyte = analytes["renal-epithelial-cells-in-urine"]
    band = analyte["bands"][1]
    assert band["source_id"] == "eflm-urinalysis-2023"
    assert band["corroborated_by"] == ["aafp-urinalysis"]
    assert analyte["retest_interval_months"] is None
    assert "retest_condition" not in analyte
    assert analyte["retest_rationale"] is None
    assert "retest_rationale" not in analyte["uk"]


# 20. Pulse rate: labels say what the band means in plain words.
def test_pulse_rate_labels(analytes: dict) -> None:
    analyte = analytes["pulse-rate"]
    assert analyte["bands"][1]["label"] == "Below 60 bpm (can be normal in fit people)"
    assert analyte["bands"][2]["label"] == "Above 100 bpm at rest"
    assert analyte["uk"]["band_labels"]["Below 60 bpm (can be normal in fit people)"] == (
        "Нижче 60 уд./хв (у тренованих людей може бути нормою)"
    )
    assert analyte["uk"]["band_labels"]["Above 100 bpm at rest"] == "Понад 100 уд./хв у спокої"


# 21. Allergen-specific IgE: class cut-offs do not depend on age.
def test_allergen_specific_ige_has_no_age_floor(analytes: dict) -> None:
    assert all(b["age_min"] is None for b in bands_of(analytes, "_allergen_specific_ige"))


# 22. Folate serum and stool blood: no retest interval recorded.
@pytest.mark.parametrize("concept_id", ["folate-serum", "stool-blood"])
def test_retest_interval_cleared(analytes: dict, concept_id: str) -> None:
    analyte = analytes[concept_id]
    assert analyte["retest_interval_months"] is None
    assert "retest_condition" not in analyte
    assert analyte["retest_rationale"] is None
    assert "retest_rationale" not in analyte["uk"]


# 23. HbA1c: recheck only at the borderline; pregnancy excluded from every band.
def test_hba1c_retest_and_pregnancy(analytes: dict) -> None:
    analyte = analytes["hemoglobin-a1c"]
    assert analyte["retest_condition"] == {"applies_when": "borderline"}
    for band in analyte["bands"]:
        assert band["excludes"] == ["pregnant"]


# 24. Blood glucose: fasting bands, random-sample diabetes band, pregnancy and non-fasting exclusions.
def test_blood_glucose_bands(analytes: dict) -> None:
    analyte = analytes["blood-glucose"]
    bands = analyte["bands"]
    assert len(bands) == 10
    random_bands = [b for b in bands if b.get("requires") == ["not_fasting_sample"]]
    assert len(random_bands) == 1
    random_band = random_bands[0]
    assert random_band["lower"] == 11.1
    assert interval(random_band) == "[11.1,None)"
    assert random_band["interpretation"] == "high"
    assert random_band["sex"] is None
    assert random_band["age_min"] == 18
    assert random_band["source_id"] == "ada-soc-2026"
    assert random_band["corroborated_by"] == ["niddk-diabetes-tests", "who-idf-2006", "moz-nakaz-1300-2024"]
    assert random_band["excludes"] == ["pregnant"]
    assert random_band["label"] in analyte["uk"]["band_labels"]
    assert set(random_band) == set(bands[0]) | {"requires", "excludes"}
    for band in bands:
        if band is random_band:
            continue
        assert "not_fasting_sample" in band["excludes"]
        assert "pregnant" in band["excludes"]
    normal_bands = [b for b in bands if b["interpretation"] == "normal"]
    assert len(normal_bands) == 3
    for band in normal_bands:
        assert band["lower"] == 3.9
        assert band["lower_inclusive"] is True
        assert "70 mg/dL" in band["note"]
        assert "70 мг/дл" in band["notes_uk"]
    assert analyte["retest_condition"] == {"applies_when": "borderline"}
