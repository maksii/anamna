"""Record public equation provenance in the published reference library.

No patient records or reference bands are added or changed. Idempotent.
"""
from __future__ import annotations

import json
from pathlib import Path

from anamna.calculation_info import BMI_SOURCE_URL
from anamna.lab_calculations import INACTIVE_LAB_METHODS, LAB_CALCULATIONS

INCOMPATIBLE_BILIRUBIN_SOURCE = "https://pch-pathlab.com/cms/?q=test-rep-dbil"

SOURCES = {
    INCOMPATIBLE_BILIRUBIN_SOURCE: (
        "north-west-anglia-direct-bilirubin-methods", "EU", "North West Anglia NHS Foundation Trust Pathology Services", "Direct bilirubin: assay compatibility", "Direct bilirubin test directory: calculated indirect bilirubin is not appropriate with this laboratory's methods", True),
    "https://www.sysmex.gr/academy/kentro-gnoseon/technologies/reticulocyte-count-application-ret/": (
        "sysmex-reticulocyte-application", "EU", "Sysmex Europe", "Reticulocyte count application (RET)", "Sysmex RET application documentation", False),
    "https://www.sysmex.de/fileadmin/media/f101/Xtra/Themenblaetter/Sysmex-White-Paper-Retikulozyt.pdf": (
        "sysmex-reticulocyte-whitepaper-2022", "EU", "Sysmex Deutschland", "Retikulozyten: White Paper", "White Paper 2022, page 4: IRF = MFR + HFR", False),
    "https://webpath.med.utah.edu/EXAM/LabMedCurric/LabMed04_01.html": (
        "utah-laboratory-hematology", "US", "University of Utah", "Laboratory Medicine Curriculum: Hematology", "WebPath LabMed04_01", True),
    "https://www.nhs.uk/conditions/high-cholesterol/cholesterol-levels/": (
        "nhs-cholesterol-levels", "EU", "NHS", "High cholesterol: Cholesterol levels", "NHS cholesterol levels publication", True),
    "https://www.sysmex-europe.com/academy/library/glossary/": (
        "sysmex-hematology-glossary", "EU", "Sysmex Europe", "Haematology glossary", "Academy glossary: PCT, 5-part and 6-part differential", False),
    "https://biolincc.nhlbi.nih.gov/media/studies/heirs/Laboratory%20Test%20Descriptions.pdf": (
        "nhlbi-heirs-laboratory-tests", "US", "National Heart, Lung, and Blood Institute", "HEIRS Laboratory Test Descriptions", "HEIRS Laboratory Test Descriptions, page 3", True),
    "https://www.beaumontlaboratory.com/lab-test-directory/detail?URL=albumin-globulin-ratio&itemID=1": (
        "corewell-albumin-globulin-ratio", "US", "Corewell Health Laboratory", "Albumin/Globulin Ratio", "Laboratory Test Directory: Albumin/Globulin Ratio", True),
    BMI_SOURCE_URL: (
        "cdc-bmi-calculation", "US", "Centers for Disease Control and Prevention", "Calculating BMI", "Growth Chart Training: Calculating BMI", True),
    "https://pmc.ncbi.nlm.nih.gov/articles/PMC9812546/": (
        "atherogenic-indices-2022", "INT", "Cureus", "A Descriptive Study of Atherogenic Indices in Patients Admitted to a Tertiary Care Hospital", "Dharmaraj S, Rajaragupathy S, Denishya S. Cureus 2022;14(12):e32231. doi:10.7759/cureus.32231; PMCID: PMC9812546", False),
}


def _calculated_globulin() -> dict:
    """Globulin mass concentration is distinct from an electrophoresis fraction."""
    return {
        "concept_id": "globulin-calculated", "canonical_name": "Globulin, calculated",
        "unit": "g/L", "kind": "no_universal_target", "bands": [], "panel": "liver",
        "source_id": "corewell-albumin-globulin-ratio",
        "source_ids": ["corewell-albumin-globulin-ratio"], "regions_covered": ["US"],
        "agreement": "no_universal_target",
        "short_description": "The serum or plasma globulin mass concentration calculated as total protein minus albumin. This is separate from the percentages of individual protein-electrophoresis fractions.",
        "why_it_matters": "Read with total protein, albumin, the albumin/globulin ratio and the performing laboratory's methods. This calculation does not identify a particular immunoglobulin or replace protein electrophoresis.",
        "no_universal_target_reason": "The performing laboratory's specimen, methods and reference interval apply. A numerical interval from one laboratory is not adopted as a universal target.",
        "retest_interval_months": None, "retest_rationale": None,
        "uk": {
            "name": "Глобуліни, розрахована концентрація",
            "short_description": "Масова концентрація глобулінів у сироватці або плазмі, розрахована як загальний білок мінус альбумін. Це окремий показник від відсотків окремих фракцій електрофорезу білків.",
            "why_it_matters": "Оцінюйте разом із загальним білком, альбуміном, співвідношенням альбумін/глобуліни та методами лабораторії. Розрахунок не визначає окремий імуноглобулін і не замінює електрофорез білків.",
            "no_universal_target_reason": "Застосовуються біоматеріал, методи та референтний інтервал лабораторії. Числовий інтервал окремої лабораторії не приймається як універсальна норма.",
            "band_labels": {},
        },
    }


def _clarify_bmi_age_scope(entry: dict) -> None:
    """Do not attribute the WHO/UA adult bands at age 18 to CDC's 20+ table."""
    age_note = (
        "The adult bands shown from age 18 follow the WHO/Ukraine adult framework. "
        "CDC applies its adult BMI categories from age 20 and uses BMI-for-age percentiles for ages 2 through 19. "
        "Thus adult numerical cut-points agree where the adult populations overlap, but age applicability differs; "
        "an adult-band result at age 18 or 19 is not a CDC BMI-for-age assessment.")
    age_note_uk = (
        "Наведені дорослі інтервали від 18 років відповідають підходу ВООЗ та українській настанові для дорослих. "
        "CDC застосовує дорослі категорії ІМТ від 20 років, а у віці від 2 до 19 років використовує вікові перцентилі ІМТ. "
        "Тому числові пороги збігаються там, де дорослі групи перекриваються, але вікова застосовність відрізняється; "
        "оцінка за дорослими інтервалами у 18 або 19 років не є оцінкою вікового ІМТ за CDC.")
    entry["agreement"] = "conditional"
    entry["divergence_note"] = age_note
    for container, note in ((entry, age_note), (entry.setdefault("uk", {}), age_note_uk)):
        existing = str(container.get("jurisdiction_note") or "")
        if note not in existing:
            container["jurisdiction_note"] = (existing + " " + note).strip()
    for band in entry.get("bands", []):
        if (band.get("age_min") or 0) >= 20:
            continue
        if band.get("source_id") == "cdc-bmi":
            band["source_id"] = "dec-kn-ozhyrinnya-dorosli-2023"
        if "cdc-bmi" in (band.get("corroborated_by") or []):
            band["corroborated_by"].remove("cdc-bmi")
        # A former corroborator can now be the primary source.
        band["corroborated_by"] = [key for key in band.get("corroborated_by", [])
                                   if key != band.get("source_id")]
        for key, note in (("note", age_note), ("notes_uk", age_note_uk)):
            existing = str(band.get(key) or "")
            old_sentence = (
                "WHO, CDC and the Ukrainian guideline «Obesity in adults» (ДЕЦ МОЗ, 2023) use the same adult cut-points. "
                if key == "note" else
                "ВООЗ, CDC і українська клінічна настанова «Ожиріння у дорослих» (ДЕЦ МОЗ, 2023) мають однакові пороги для дорослих. ")
            existing = existing.replace(old_sentence, "")
            if note not in existing:
                existing = (note + " " + existing).strip()
            band[key] = existing


def extend(library: dict) -> dict[str, int]:
    added = 0
    by_url = {item["url"]: item for item in library["sources"]}
    # Correct the former misattribution even on an already extended library.
    research = by_url.get("https://pmc.ncbi.nlm.nih.gov/articles/PMC9812546/")
    if research is not None:
        _, _, publisher, name, identifier, _ = SOURCES[research["url"]]
        research.update(publisher=publisher, name=name, identifier=identifier,
                        official=False, kind="primary_research")
    for url in {item.source_url for item in LAB_CALCULATIONS} | {BMI_SOURCE_URL, INCOMPATIBLE_BILIRUBIN_SOURCE}:
        if url in by_url:
            continue
        source_id, region, publisher, name, identifier, official = SOURCES[url]
        record = dict(id=source_id, region=region, publisher=publisher, name=name,
                      url=url, identifier=identifier, official=official, reviewed_at="2026-11-15")
        if not official:
            record["kind"] = "manufacturer_documentation" if "sysmex" in url else "primary_research"
        library["sources"].append(record)
        by_url[url] = record
        added += 1
    analytes = {item["concept_id"]: item for item in library["analytes"]}
    if "globulin-calculated" not in analytes:
        globulin = _calculated_globulin()
        library["analytes"].append(globulin)
        analytes[globulin["concept_id"]] = globulin
    count = 0
    for calculation in LAB_CALCULATIONS:
        entry = analytes[calculation.concept_id]
        source = by_url[calculation.source_url]
        if source["id"] not in entry["source_ids"]:
            entry["source_ids"].append(source["id"])
        if source["region"] not in entry["regions_covered"]:
            entry["regions_covered"].append(source["region"])
        entry["calculation"] = {
            "method": calculation.method, "formula": calculation.formula,
            "input_concept_ids": [item.concept_id for item in calculation.inputs],
            "source_id": source["id"], "requires_confirmed_inputs": True,
            "output_provisional": True, "automatic_enabled": calculation.method not in INACTIVE_LAB_METHODS,
        }
        count += 1
    indirect = analytes["indirect-bilirubin"]
    caveat_source = by_url[INCOMPATIBLE_BILIRUBIN_SOURCE]
    if caveat_source["id"] not in indirect["source_ids"]:
        indirect["source_ids"].append(caveat_source["id"])
    if "EU" not in indirect["regions_covered"]:
        indirect["regions_covered"].append("EU")
    indirect["calculation"]["requires_compatible_assays"] = True
    indirect["jurisdiction_note"] = (
        "The NHLBI HEIRS protocol calculates indirect bilirubin as total minus direct bilirubin. "
        "North West Anglia NHS Pathology states that its total and direct assay methods do not correlate sufficiently for this calculation. "
        "Compatibility of the performing laboratory's methods must therefore be established; automatic reconstruction is disabled when this evidence is absent.")
    indirect.setdefault("uk", {})["jurisdiction_note"] = (
        "Протокол NHLBI HEIRS розраховує непрямий білірубін як загальний мінус прямий. "
        "Патологічна служба NHS North West Anglia зазначає, що її методи визначення загального та прямого білірубіну недостатньо узгоджені для цього розрахунку. "
        "Тому потрібне підтвердження сумісності методів лабораторії; без цих даних автоматичне відновлення вимкнено.")
    entry = analytes["body-mass-index"]
    _clarify_bmi_age_scope(entry)
    source = by_url[BMI_SOURCE_URL]
    if source["id"] not in entry["source_ids"]:
        entry["source_ids"].append(source["id"])
    entry["device_calculation"] = {
        "method": "derived_bmi", "formula": "BMI = weight (kg) / height (m)^2",
        "input_metric_keys": ["body_weight", "body_height"], "source_id": source["id"],
        "output_provisional": True,
    }
    coefficient = analytes["atherogenic-coefficient"]
    coefficient["short_description"] = coefficient["short_description"].replace(
        ", also called the Castelli index,", ",")
    if "uk" in coefficient:
        coefficient["uk"]["short_description"] = (
            "Коефіцієнт атерогенності — це (загальний холестерин − холестерин ЛПВЩ) / холестерин ЛПВЩ. "
            "Це окремий показник від індексу Кастеллі та логарифмічного атерогенного індексу плазми. "
            "Універсальної цілі для цього співвідношення немає; оцінка ризику спирається на чинні клінічні настанови.")
    library["sources"].sort(key=lambda item: item["id"])
    return {"sources_added": added, "calculations_documented": count}


def main():
    path = Path(__file__).resolve().parents[1] / "data/reference_library.json"
    library = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(extend(library)))
    path.write_text(json.dumps(library, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
