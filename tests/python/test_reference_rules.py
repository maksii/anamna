"""Invariants the curated reference library must satisfy, whatever its size.

Counting rows here would only guarantee that nobody adds guidance; these
assertions guarantee that whatever is loaded is citable, internally consistent
and safe to compare a patient value against.
"""

from pathlib import Path

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.ingest.pipeline import seed_concepts


NO_UNIVERSAL_TARGET = "no_universal_target"


def _seeded(tmp_path: Path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    connection = connect(settings)
    seed_concepts(connection)
    return connection


def test_every_reference_set_is_versioned_and_citable(tmp_path: Path):
    with _seeded(tmp_path) as connection:
        sets = connection.execute(
            "SELECT id, name, publisher, version, source_url, reviewed_at FROM reference_sets"
        ).fetchall()

    assert sets, "the curated library seeded no reference sets"
    for row in sets:
        assert row["version"], f"{row['id']} has no version"
        assert row["publisher"], f"{row['id']} has no publisher"
        assert row["source_url"].startswith("https://"), f"{row['id']} has no https source"
        assert row["reviewed_at"], f"{row['id']} was never reviewed"


def test_every_rule_is_anchored_bounded_and_united(tmp_path: Path):
    with _seeded(tmp_path) as connection:
        rules = connection.execute(
            """SELECT r.id, r.concept_id, r.unit, r.lower_bound, r.upper_bound,
                      r.interpretation, r.reference_set_id, r.context_json,
                      s.id AS resolved_set, c.id AS resolved_concept,
                      (c.id IS NOT NULL AND c.preferred_unit IS NULL) AS dimensionless
               FROM curated_reference_rules r
               LEFT JOIN reference_sets s ON s.id = r.reference_set_id
               LEFT JOIN concepts c ON c.id = r.concept_id"""
        ).fetchall()

    assert rules, "the curated library seeded no rules"
    for rule in rules:
        assert rule["resolved_set"], f"{rule['id']} cites a reference set that does not exist"
        # A rule may describe a device metric key, which is not a concept.
        if rule["lower_bound"] is not None and rule["upper_bound"] is not None:
            assert rule["lower_bound"] <= rule["upper_bound"], f"{rule['id']} has lower > upper"
        bounded = rule["lower_bound"] is not None or rule["upper_bound"] is not None
        marker = rule["interpretation"] == NO_UNIVERSAL_TARGET
        if bounded and not marker and not rule["dimensionless"]:
            assert rule["unit"], f"{rule['id']} compares numbers without naming a unit"


def test_urinalysis_rules_key_to_definition_concepts_not_learned_uuids(tmp_path: Path):
    """Curated urinalysis rules must sit on the stable definition concepts.

    Keyed to per-database learned-concept uuids they judged nothing: the real
    observations land on the definition ids, and the uuids differ between
    databases anyway.
    """
    learned = (
        "754c0e02-dd8c-5188-b3b2-55c3c26f995c",  # urine bilirubin duplicate
        "5750a7ae-1836-55a1-80eb-2464505740bd",  # RTEC duplicate
        "ffab1d8b-951c-522c-b5a3-d75e4c18ede9",  # waxy casts duplicate
        "fde89ebb-4b28-5f6d-8534-b934cf705a02",  # leukocyte casts duplicate
        "1b6e427c-9551-55f3-a5c3-a23c9b2572ec",  # erythrocyte casts duplicate
    )
    with _seeded(tmp_path) as connection:
        placeholders = ",".join("?" for _ in learned)
        orphaned = connection.execute(
            f"SELECT concept_id FROM curated_reference_rules WHERE concept_id IN ({placeholders})",
            learned,
        ).fetchall()
        assert not orphaned, [row["concept_id"] for row in orphaned]
        for concept_id in (
            "urine-bilirubin",
            "renal-epithelial-cells-in-urine",
            "waxy-casts-in-urine",
            "urine-leukocyte-casts",
            "urine-erythrocyte-casts",
        ):
            count = connection.execute(
                "SELECT COUNT(*) FROM curated_reference_rules WHERE concept_id=?",
                (concept_id,),
            ).fetchone()[0]
            assert count > 0, f"{concept_id} lost its curated rules"


def test_oura_scores_have_guidance_and_no_invented_bands(tmp_path: Path):
    """Manufacturer-defined scores explain themselves in both languages and
    carry no numeric bands -- no body publishes a target for them."""
    keys = (
        "activity_score", "breathing_disturbance_index", "moderate_activity",
        "readiness_score", "recovery_high_time", "sleep_efficiency",
        "sleep_score", "stress_high_time", "temperature_deviation",
        "vigorous_activity",
    )
    with _seeded(tmp_path) as connection:
        for key in keys:
            row = connection.execute(
                """SELECT g.short_description, g.why_it_matters,
                          g.short_description_uk, g.why_it_matters_uk,
                          s.source_url
                   FROM concept_guidance g
                   LEFT JOIN reference_sets s ON s.id = g.source_id
                   WHERE g.concept_id=?""",
                (key,),
            ).fetchone()
            assert row, f"{key} has no guidance row"
            for field in ("short_description", "why_it_matters",
                          "short_description_uk", "why_it_matters_uk"):
                assert row[field], f"{key} missing {field}"
            assert row["source_url"] and row["source_url"].startswith("https://"), key
            rules = connection.execute(
                "SELECT COUNT(*) FROM curated_reference_rules WHERE concept_id=?",
                (key,),
            ).fetchone()[0]
            assert rules == 0, f"{key} grew {rules} bands nobody published"


def test_calcium_ionized_bands_and_backfilled_rationales_are_translated(tmp_path: Path):
    with _seeded(tmp_path) as connection:
        untranslated = connection.execute(
            """SELECT label FROM curated_reference_rules
               WHERE concept_id='calcium-ionized'
                 AND (label_uk IS NULL OR TRIM(label_uk)='')"""
        ).fetchall()
        assert not untranslated, [row["label"] for row in untranslated]
        missing = connection.execute(
            """SELECT concept_id FROM concept_guidance
               WHERE retest_rationale IS NOT NULL AND TRIM(retest_rationale) <> ''
                 AND (retest_rationale_uk IS NULL OR TRIM(retest_rationale_uk)='')"""
        ).fetchall()
        assert not missing, [row["concept_id"] for row in missing]


def test_reseeding_is_idempotent(tmp_path: Path):
    with _seeded(tmp_path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM curated_reference_rules").fetchone()[0]
        seed_concepts(connection)
        after = connection.execute("SELECT COUNT(*) FROM curated_reference_rules").fetchone()[0]
        guidance = connection.execute(
            "SELECT COUNT(*) FROM concept_guidance WHERE panel_id IS NOT NULL"
        ).fetchone()[0]
    assert before == after
    assert guidance > 0
