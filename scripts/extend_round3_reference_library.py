"""Reproduce public definitions and applicability corrections from audit three."""
from __future__ import annotations

import json
from pathlib import Path


OW_TYPES = "https://github.com/the-momentum/open-wearables/blob/main/backend/app/schemas/enums/series_types.py"
PREGNANCY_SOURCE = "https://www.nice.org.uk/guidance/ng3/chapter/Recommendations"
MEASUREMENTS_SOURCE = "https://www.niddk.nih.gov/research-funding/research-programs/kidney-clinical-research-epidemiology/laboratory/factors-affecting-egfr-accuracy/clinical-measurements"


def extend(library: dict) -> None:
    sources = library["sources"]
    def source(key, publisher, name, url, region, official):
        existing = next((item for item in sources if item["url"] == url), None)
        if existing:
            return existing["id"]
        sources.append({"id": key, "publisher": publisher, "name": name, "url": url,
                        "identifier": key, "region": region, "official": official,
                        "reviewed_at": "2026-11-15"})
        return key

    weather_source = source("openwearables-series-types-2026", "OpenWearables",
                            "Canonical series types and source aliases", OW_TYPES, "INT", False)
    pregnancy_source = source("nice-ng3-egfr-pregnancy", "NICE", "NG3, recommendation 1.3.30",
                              PREGNANCY_SOURCE, "EU", True)
    measurement_source = source("niddk-egfr-clinical-measurements", "NIDDK",
                                "Clinical measurements affecting eGFR accuracy", MEASUREMENTS_SOURCE, "US", True)
    by_id = {item["concept_id"]: item for item in library["analytes"]}
    for key, name, uk_name, unit, description, uk_description in (
        ("weather_temperature", "Weather temperature", "Температура за даними погоди", "°C",
         "Weather-context temperature supplied by the provider. This is an environmental quantity, not body or skin temperature.",
         "Температура в погодному контексті, надана джерелом. Це показник середовища, а не температура тіла чи шкіри."),
        ("weather_humidity", "Weather relative humidity", "Відносна вологість за даними погоди", "%",
         "Relative humidity supplied in the provider's weather context. This is not a body-water measurement.",
         "Відносна вологість у погодному контексті джерела. Це не вимірювання води в організмі."),
    ):
        item = {"concept_id": key, "canonical_name": name, "unit": unit, "panel": "weather",
                "kind": "no_universal_target", "bands": [], "source_id": weather_source,
                "source_ids": [weather_source], "regions_covered": ["INT"], "agreement": "single_source",
                "short_description": description,
                "why_it_matters": "Keep the source and collection context with this value. No clinical reference interval or routine retest schedule is assigned.",
                "no_universal_target_reason": "A provider weather field is environmental context, not a clinical target.",
                "retest_interval_months": None, "retest_rationale": None,
                "uk": {"name": uk_name, "short_description": uk_description,
                       "why_it_matters": "Зберігайте разом зі значенням його джерело й контекст збору. Клінічний референтний інтервал і плановий термін повторної перевірки не призначаються.",
                       "no_universal_target_reason": "Погодне поле джерела є контекстом середовища, а не клінічною ціллю.",
                       "band_labels": {}}}
        if key in by_id:
            by_id[key].update(item)
        else:
            library["analytes"].append(item)
    egfr = by_id["estimated-glomerular-filtration-rate-ckd-epi-2021"]
    egfr["source_ids"] = list(dict.fromkeys([*egfr.get("source_ids", []), pregnancy_source, measurement_source]))
    egfr["regions_covered"] = sorted(set(egfr.get("regions_covered", [])) | {"EU", "US"})
    for container, note in (
        (egfr, "eGFR equations are not valid during pregnancy. Anamna suppresses reconstruction for a recorded pregnancy window and retains reported values without staging them. CKD-EPI also assumes appropriately standardized creatinine; assay calibration and stable renal function are not established merely by checking a source value. Review the source method and clinical limitations."),
        (egfr.setdefault("uk", {}), "Рівняння рШКФ не є валідними під час вагітності. Anamna не виконує реконструкцію в межах записаного періоду вагітності й зберігає повідомлені значення без визначення стадії. CKD-EPI також передбачає належно стандартизований креатинін; перевірка значення за джерелом сама по собі не підтверджує калібрування аналізу чи стабільність функції нирок. Перевірте метод джерела та клінічні обмеження."),
    ):
        previous = str(container.get("jurisdiction_note") or "")
        if note not in previous:
            container["jurisdiction_note"] = (previous + " " + note).strip()
    reported_id = "estimated-glomerular-filtration-rate-reported"
    reported = {
        "concept_id": reported_id, "canonical_name": "Estimated glomerular filtration rate, reported",
        "unit": "mL/min/1.73m²", "panel": "kidney", "kind": "no_universal_target", "bands": [],
        "source_id": measurement_source, "source_ids": list(egfr["source_ids"]),
        "regions_covered": list(egfr["regions_covered"]), "agreement": "no_universal_target",
        "short_description": "An estimate of kidney filtration reported by a laboratory. This shared catalog identity does not establish the equation, its year or its filtration marker; any method printed in the original name remains part of the source evidence.",
        "why_it_matters": "Retain the reported method, biomarker, body-surface-area indexing and laboratory interpretation. A CKD-EPI, MDRD or cystatin-C label must not be silently renamed as the creatinine-only CKD-EPI 2021 equation used by Anamna.",
        "no_universal_target_reason": "The equation and assay are not established by a generic eGFR label. This shared identity receives no CKD-EPI 2021-specific interval or routine retest schedule.",
        "jurisdiction_note": "Different estimating equations have different validation and limitations. During a pregnancy recorded in the profile, reported eGFR is retained as source evidence without clinical staging; eGFR equations are not valid for use in pregnancy.",
        "retest_interval_months": None, "retest_rationale": None,
        "uk": {
            "name": "Розрахункова швидкість клубочкової фільтрації, повідомлена",
            "short_description": "Оцінка фільтраційної функції нирок, повідомлена лабораторією. Ця спільна каталожна назва не встановлює рівняння, його рік або маркер фільтрації; метод, зазначений в оригінальній назві, залишається частиною вихідних даних.",
            "why_it_matters": "Зберігайте повідомлені метод, біомаркер, індексацію до площі поверхні тіла та інтерпретацію лабораторії. Позначення CKD-EPI, MDRD або цистатину C не можна непомітно перейменовувати на рівняння CKD-EPI 2021 лише за креатиніном, яке використовує Anamna.",
            "no_universal_target_reason": "Загальне позначення рШКФ не встановлює рівняння та метод аналізу. Цій спільній назві не призначають інтервалу CKD-EPI 2021 або планового терміну повторної перевірки.",
            "jurisdiction_note": "Різні рівняння оцінювання мають різну валідацію та обмеження. Під час вагітності, зазначеної в профілі, повідомлену рШКФ зберігають як дані джерела без визначення клінічної стадії; рівняння рШКФ не є валідними для використання під час вагітності.",
            "band_labels": {},
        },
    }
    if reported_id in by_id:
        by_id[reported_id].update(reported)
    else:
        library["analytes"].append(reported)
    iron = by_id.get("serum-iron")
    if iron:
        iron["why_it_matters"] = "Serum iron varies with timing and context. Read it with the blood count and ferritin; transferrin saturation or iron-binding capacity, when available, provide separate information and cannot be inferred from ferritin alone."
        iron.setdefault("uk", {})["why_it_matters"] = "Сироваткове залізо залежить від часу забору та контексту. Оцінюйте його разом із загальним аналізом крові та феритином; насичення трансферину або залізозв’язувальна здатність, якщо вони наявні, дають окрему інформацію й не можуть бути виведені лише з феритину."
    sources.sort(key=lambda item: item["id"])


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "data/reference_library.json"
    library = json.loads(path.read_text(encoding="utf-8"))
    extend(library)
    path.write_text(json.dumps(library, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
