"""Reproduce the sourced device definitions added by the connection audit.

Only reference metadata is changed; this script never reads patient records.
Run before ``seed_reference_library.py`` to apply it to an existing library.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


REVIEWED_AT = "2026-11-15"
APPLE_BASE = "https://developer.apple.com/documentation/healthkit/"
# Pinned to the commit that was read, so the cited lines cannot move.
OW_COMMIT = "7ca121dd4e483ec2f397f141a326e2bc81a960bd"
OW_BASE = "https://github.com/the-momentum/open-wearables/blob/" + OW_COMMIT + "/backend/app/"


def _source(key: str, publisher: str, name: str, url: str, identifier: str) -> dict:
    return {
        "id": key, "region": "INT", "publisher": publisher, "name": name,
        "url": url, "identifier": identifier, "reviewed_at": REVIEWED_AT,
        "official": False, "kind": "manufacturer_documentation",
        "access_note": "Manufacturer or upstream implementation documentation, reviewed for the quantity's definition; not clinical guidance or a reference interval.",
    }


SOURCES = [
    _source("apple-healthkit-body-temperature", "Apple Inc.", "HealthKit: bodyTemperature",
            APPLE_BASE + "hkquantitytypeidentifier/bodytemperature", "HKQuantityTypeIdentifierBodyTemperature"),
    *[
        _source("apple-healthkit-" + suffix, "Apple Inc.", "HealthKit: " + symbol,
                APPLE_BASE + "hkquantitytypeidentifier/" + symbol.lower(), "HKQuantityTypeIdentifier" + symbol[0].upper() + symbol[1:])
        for suffix, symbol in (
            ("environmental-sound-reduction", "environmentalSoundReduction"),
            ("stair-ascent-speed", "stairAscentSpeed"),
            ("stair-descent-speed", "stairDescentSpeed"),
            ("swimming-distance", "distanceSwimming"),
        )
    ],
    _source("apple-healthkit-stand-hour", "Apple Inc.", "HealthKit: Apple stand hour categories",
            APPLE_BASE + "hkcategoryvalueapplestandhour", "HKCategoryValueAppleStandHour"),
    _source("oura-lowest-resting-heart-rate", "Oura Health Oy", "Readiness Contributors: Resting Heart Rate",
            "https://support.ouraring.com/hc/en-us/articles/360057791533-Readiness-Contributors", "Oura Member Care article 360057791533"),
    _source("openwearables-score-schema-2026", "Open Wearables / Momentum", "Health score categories and provider-specific numeric values",
            OW_BASE + "schemas/model_crud/activities/health_score.py", "HealthScoreBase.value and .category (HealthScoreCategory); commit " + OW_COMMIT[:12]),
    _source("openwearables-sleep-interruptions-2026", "Open Wearables / Momentum", "Daily sleep summary: significant awakenings",
            OW_BASE + "services/summaries_service.py", "_interruptions_count; SleepSummary.interruptions_count; commit " + OW_COMMIT[:12]),
    _source("openwearables-recovery-summary-2026", "Open Wearables / Momentum", "Daily recovery summary: source-reported recovery score",
            OW_BASE + "services/summaries_service.py", "SummariesService.get_recovery_summaries; recovery_score; commit " + OW_COMMIT[:12]),
]


# id, name, Ukrainian name, unit, panel, source id, English definition, Ukrainian definition
DEFINITIONS = (
    ("environmental_sound_reduction", "Environmental sound reduction", "Зниження навколишнього шуму", "dBA", "hearing", "apple-healthkit-environmental-sound-reduction",
     "The reduction in environmental sound intensity measured while wearing supported headphones. It describes a change in sound level, not the remaining sound exposure at the ear.",
     "Зниження інтенсивності навколишнього звуку під час носіння підтримуваних навушників. Це зміна рівня звуку, а не залишковий вплив звуку на вухо."),
    ("stair_ascent_speed", "Stair ascent speed", "Швидкість підйому сходами", "m/s", "mobility", "apple-healthkit-stair-ascent-speed",
     "The watch's measured speed while walking up a flight of stairs. Uphill and downhill stair speeds are separate measurements.",
     "Швидкість підйому сходами, виміряна годинником. Швидкості підйому та спуску є окремими показниками."),
    ("stair_descent_speed", "Stair descent speed", "Швидкість спуску сходами", "m/s", "mobility", "apple-healthkit-stair-descent-speed",
     "The watch's measured speed while walking down a flight of stairs. It is kept separate from stair ascent speed.",
     "Швидкість спуску сходами, виміряна годинником. Її зберігають окремо від швидкості підйому."),
    ("swimming_distance", "Swimming distance", "Відстань плавання", "m", "activity", "apple-healthkit-swimming-distance",
     "The distance recorded while swimming, accumulated over the day. Distance alone does not describe the intensity or duration of the activity.",
     "Відстань, зареєстрована під час плавання та підсумована за день. Сама відстань не визначає інтенсивності чи тривалості навантаження."),
    ("stand_hours", "Stand hours", "Години з рухом стоячи", "hours", "activity", "apple-healthkit-stand-hour",
     "The number of hours containing a stand-and-move event recorded by Apple Health. A counted hour does not mean an entire hour spent standing.",
     "Кількість годин, у яких Apple Health зареєстрував вставання та рух. Зарахована година не означає цілу годину перебування стоячи."),
    ("lowest_sleeping_heart_rate", "Lowest sleeping heart rate", "Найнижчий пульс під час сну", "bpm", "cardio_fitness", "oura-lowest-resting-heart-rate",
     "The lowest heart rate reported during sleep. Oura compares the nightly minimum with the person's own longer-term pattern; this is separate from the average sleeping or daytime resting heart rate.",
     "Найнижчий пульс, зареєстрований під час сну. Oura порівнює нічний мінімум з особистою тривалою динамікою; це окремий показник від середнього пульсу уві сні чи пульсу спокою вдень."),
    ("sleep_interruptions", "Sleep interruptions", "Переривання сну", "count", "sleep", "openwearables-sleep-interruptions-2026",
     "The upstream sleep summary's count of significant awakenings in the main sleep sessions. Its detection depends on the available sleep-stage timeline and upstream implementation.",
     "Кількість значущих пробуджень в основних періодах сну за зведенням джерела. Виявлення залежить від наявної послідовності стадій сну та реалізації системи-джерела."),
)

SCORES = (
    ("body_battery_score", "Body Battery score", "Оцінка Body Battery"),
    ("health_recovery_score", "Health recovery score", "Оцінка відновлення у зведенні здоров’я"),
    ("recovery_score", "Recovery score", "Оцінка відновлення"),
    ("resilience_score", "Resilience score", "Оцінка стійкості"),
    ("strain_score", "Strain score", "Оцінка навантаження"),
    ("stress_score", "Stress score", "Оцінка стресу"),
)


def additions() -> list[dict]:
    rows = list(DEFINITIONS)
    for key, name, uk_name in SCORES:
        source = "openwearables-recovery-summary-2026" if key == "recovery_score" else "openwearables-score-schema-2026"
        rows.append((key, name, uk_name, "score", "recovery", source,
                     "A source-reported " + name.lower() + ". The method and numeric scale depend on the provider and score category; the imported number is preserved without converting it into another provider's score.",
                     "Оцінка, повідомлена джерелом: «" + uk_name + "». Методика й числова шкала залежать від постачальника та категорії оцінки; імпортоване число зберігається без перетворення на оцінку іншого постачальника."))
    return [
        {
            "concept_id": key, "canonical_name": name, "unit": unit,
            "kind": "no_universal_target", "bands": [], "panel": panel,
            "source_id": source, "source_ids": [source], "regions_covered": ["INT"],
            "agreement": "single_source", "short_description": description,
            "why_it_matters": "Read this alongside its source, measurement method and your own history. No clinical reference interval is assigned to this device-specific summary.",
            "retest_interval_months": None, "retest_rationale": None,
            "uk": {
                "name": uk_name, "short_description": uk_description,
                "why_it_matters": "Розглядайте цей показник разом із джерелом, способом вимірювання та власною динамікою. Для цього зведення пристрою не встановлено клінічного референтного інтервалу.",
                "band_labels": {},
            },
        }
        for key, name, uk_name, unit, panel, source, description, uk_description in rows
    ]


def extend(library: dict) -> dict[str, int]:
    """Add missing entries, preserving every existing reference and band."""
    sources = {source["id"] for source in library["sources"]}
    analytes = {entry["concept_id"]: entry for entry in library["analytes"]}
    source_added = analyte_added = 0
    for source in SOURCES:
        if source["id"] not in sources:
            library["sources"].append(source)
            source_added += 1
    for entry in additions():
        if entry["concept_id"] not in analytes:
            library["analytes"].append(entry)
            analyte_added += 1
    # Body temperature is a SAME twin; the clinical entry remains the authority.
    body = analytes.get("body-temperature")
    if body is not None:
        body.setdefault("source_ids", [])
        if "apple-healthkit-body-temperature" not in body["source_ids"]:
            body["source_ids"].append("apple-healthkit-body-temperature")
        if "INT" not in body.setdefault("regions_covered", []):
            body["regions_covered"].append("INT")
    return {"sources_added": source_added, "analytes_added": analyte_added}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=Path("data/reference_library.json"))
    args = parser.parse_args()
    library = json.loads(args.library.read_text(encoding="utf-8"))
    counts = extend(library)
    args.library.write_text(json.dumps(library, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
