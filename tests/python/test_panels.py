from pathlib import Path

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.devices.catalog import HEALTHKIT_METRICS, SLEEP_METRICS
from anamna.devices.structured import GarminAdapter, OuraAdapter
from anamna.health import HEALTH_AREAS
from anamna.ingest.concepts import stable_concept_id
from anamna.ingest.pipeline import seed_concepts
from anamna.oura import DEFS as OURA_DEFS
from anamna.openwearables import DEFS as OPENWEARABLES_DEFS
from anamna.panels import (
    DISPLAY_SUPPRESSED,
    MEASUREMENT_TWINS,
    PANEL_BY_ID,
    SAME_DEVICE_KEYS,
    TWIN_OF_DEVICE,
    PANELS,
    PANELS_BY_AREA,
    panel_for_concept,
    panel_members,
    panel_retest_months,
    roll_up,
)


def _seeded(tmp_path: Path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    connection = connect(settings)
    seed_concepts(connection)
    return connection


def test_every_named_panel_member_resolves_to_a_seeded_concept(tmp_path: Path):
    with _seeded(tmp_path) as connection:
        seeded = {row["id"] for row in connection.execute("SELECT id FROM concepts")}
    missing = {
        panel.id: [
            name
            for name in panel.member_names
            if stable_concept_id(name) not in seeded
        ]
        for panel in PANELS
    }
    assert {panel: names for panel, names in missing.items() if names} == {}


def test_panel_ids_and_area_grouping_are_consistent():
    assert len(PANEL_BY_ID) == len(PANELS)
    assert sum(len(panels) for panels in PANELS_BY_AREA.values()) == len(PANELS)
    for area_id, panels in PANELS_BY_AREA.items():
        assert all(panel.area_id == area_id for panel in panels)


def test_panel_for_concept_round_trips():
    for panel in PANELS:
        for member in panel.members:
            resolved = panel_for_concept(member)
            assert resolved is not None
            assert member in PANEL_BY_ID[resolved.id].members
    # Dynamic membership is resolved by category, not by name.
    assert panel_for_concept("some-allergen", "allergy").id == "allergy"
    assert panel_for_concept("urine-ph", "urinalysis").id == "urinalysis"
    assert panel_for_concept("nothing-at-all") is None


def test_allergy_panel_lists_total_ige_first_then_the_catalogued_allergens(tmp_path: Path):
    with _seeded(tmp_path) as connection:
        connection.execute(
            "INSERT INTO concepts(id, canonical_name, category, value_type, created_at)"
            " VALUES ('bet-v-1', 'Bet v 1 PR-10', 'allergy', 'numeric', '2026-01-01')"
        )
        members = panel_members(connection, PANEL_BY_ID["allergy"])
    assert members[0] == stable_concept_id("Total immunoglobulin E")
    assert "bet-v-1" in members
    assert len(members) == len(set(members))


def test_roll_up_precedence():
    assert roll_up([])["status"] == "absent"
    assert roll_up(["normal", "normal"])["status"] == "normal"
    assert roll_up(["normal", "borderline_high"])["status"] == "borderline"
    assert roll_up(["normal", "borderline_high", "high"])["status"] == "attention"
    assert roll_up(["unjudged", "unjudged"])["status"] == "unjudged"
    # Precedence is by severity, not by count.
    assert roll_up(["low"] + ["normal"] * 20)["status"] == "attention"


def test_roll_up_reports_attention_and_stale_together():
    overdue = {"state": "overdue"}
    result = roll_up(["high", "normal"], overdue)
    assert result["status"] == "attention"
    assert result["attention"] is True
    assert result["stale"] is True
    assert result["flagged_count"] == 1
    # Nothing judged and overdue reads as stale, which is the actionable state.
    assert roll_up(["unjudged"], overdue)["status"] == "stale"
    assert roll_up(["unjudged"], {"state": "fresh"})["status"] == "unjudged"


def test_roll_up_accepts_metric_cards():
    cards = [{"verdict": {"interpretation": "high"}}, {"verdict": {"interpretation": "normal"}}]
    assert roll_up(cards)["status"] == "attention"


def test_fixed_attributes_do_not_affect_the_roll_up():
    # HLA-B27 sits in the autoimmune panel but is an inherited marker.
    assert roll_up(["normal", "not_a_measurement"])["status"] == "normal"
    assert roll_up(["not_a_measurement"])["status"] == "absent"


def test_suppressed_results_stay_out_of_panels(tmp_path: Path):
    with _seeded(tmp_path) as connection:
        members = panel_members(connection, PANEL_BY_ID["vitamins"])
    assert "red-cell-folate-calculation-hematocrit" not in members
    assert stable_concept_id("Vitamin B12") in members
    # Recording length is device telemetry, not a result.
    assert "ecg-recording-duration" in DISPLAY_SUPPRESSED


def test_panel_sweeps_and_area_categories_exist_in_the_seed(tmp_path: Path):
    """A sweep of a category no concept carries silently hides a whole panel."""
    with _seeded(tmp_path) as connection:
        seeded = {
            row["category"] for row in connection.execute("SELECT DISTINCT category FROM concepts")
        }
    dead_sweeps = {
        (panel.id, category)
        for panel in PANELS
        for category in panel.member_categories
        if category not in seeded
    }
    dead_areas = {
        (area["id"], category)
        for area in HEALTH_AREAS
        for category in area["categories"]
        if not str(category).startswith("device_") and category not in seeded
    }
    assert dead_sweeps == set()
    assert dead_areas == set()


# Concepts deliberately left without a panel home; each needs a reason.
PANEL_LESS_CONCEPTS = (
    # Carried by the /devices/ecg recording picker and linked from the heart
    # area; the blood_pressure renderer would never display it as a member row.
    "heart-rhythm",
    # Echocardiography and ultrasound measurements: read from a narrative
    # imaging report and shown with it on the heart, liver, kidney and thyroid
    # area pages.  A laboratory panel is a set of results drawn on one sample,
    # which a carotid scan and a thyroid volume are not.
    "left-ventricular-mass-index",
    "left-ventricular-mass",
    "carotid-intima-media-thickness",
    "peak-systolic-velocity-common-carotid-artery",
    "liver-craniocaudal-size",
    "common-bile-duct-diameter",
    "bladder-wall-thickness",
    "thyroid-volume",
    # The rest of those protocols' sizes (test_ultrasound_measurements), for
    # the same reason; the lesion's diameters land on the body area page.
    "liver-left-lobe-size", "portal-vein-diameter", "gallbladder-length", "gallbladder-width",
    "pancreatic-head-size", "pancreatic-body-size", "pancreatic-tail-size", "splenic-vein-diameter",
    "kidney-length", "kidney-width", "renal-parenchymal-thickness", "largest-renal-salt-crystal-size",
    "urinary-bladder-volume", "spleen-length", "spleen-thickness", "thyroid-isthmus-thickness",
    "thyroid-lobe-length", "thyroid-ti-rads-category", "right-ventricular-diameter",
    "interventricular-septal-thickness-diastole", "left-ventricular-end-diastolic-diameter",
    "left-ventricular-posterior-wall-thickness-diastole", "left-ventricular-ejection-fraction",
    "ascending-aorta-diameter", "aortic-root-diameter-at-the-sinuses-of-valsalva", "left-atrial-diameter",
    "tricuspid-valve-peak-pressure-gradient", "pulmonary-artery-acceleration-time",
    "peak-systolic-velocity-internal-carotid-artery", "peak-systolic-velocity-external-carotid-artery",
    "peak-systolic-velocity-vertebral-artery", "vertebral-artery-diameter",
    "soft-tissue-lesion-largest-diameter", "soft-tissue-lesion-smaller-diameter",
    # Review 2 (2026-11-07): transcranial and InMed duplex, pelvic and breast
    # ultrasound, the gallbladder emptying test, the EEG's rhythms and breath
    # hydrogen, read from narrative protocols for the same reason and shown on
    # the heart, reproductive, liver, brain and digestive area pages.
    "peak-systolic-velocity-anterior-cerebral-artery", "peak-systolic-velocity-middle-cerebral-artery",
    "peak-systolic-velocity-intracranial-vertebral-artery-v4", "peak-systolic-velocity-basilar-artery",
    "vertebral-artery-resistive-index", "internal-jugular-vein-diameter",
    "uterine-body-length", "uterine-body-anteroposterior-diameter", "uterine-body-width", "endometrial-thickness",
    "cervical-length", "cervical-thickness", "ovary-length", "ovarian-volume", "antral-follicle-count",
    "largest-ovarian-follicle-diameter", "corpus-luteum-diameter", "ovarian-cyst-largest-diameter",
    "ovarian-cyst-smaller-diameter", "ovarian-o-rads-category", "uterine-lesion-largest-diameter",
    "uterine-lesion-smaller-diameter", "breast-bi-rads-category", "breast-lesion-largest-diameter",
    "breast-lesion-smaller-diameter", "largest-breast-cyst-diameter", "breast-skin-thickness",
    "breast-subcutaneous-fat-thickness", "breast-glandular-tissue-thickness",
    "gallbladder-ejection-fraction", "gallbladder-volume",
    "eeg-alpha-rhythm-frequency", "eeg-alpha-rhythm-amplitude", "eeg-beta-rhythm-frequency",
    "eeg-beta-rhythm-amplitude", "eeg-theta-rhythm-frequency", "eeg-theta-rhythm-amplitude",
    "breath-hydrogen",
    # Tumour markers: read against a known cancer or a pelvic mass, not a body
    # system, so no area panel claims them; their metric pages explain that.
    "cancer-antigen-125-ca-125", "cancer-antigen-15-3-ca-15-3", "human-epididymis-protein-4-he4",
    # Review 4: the effective dose an X-ray report prints is an exposure, not a
    # body system's reading; it shows on its metric page and on the report.
    "effective-radiation-dose",
)


def test_every_seeded_concept_is_paneled_suppressed_or_excused(tmp_path: Path):
    with _seeded(tmp_path) as connection:
        rows = connection.execute("SELECT id, category FROM concepts").fetchall()
    unclaimed = sorted(
        row["id"]
        for row in rows
        if panel_for_concept(row["id"], row["category"]) is None
        and row["id"] not in DISPLAY_SUPPRESSED
        and row["id"] not in PANEL_LESS_CONCEPTS
    )
    assert unclaimed == []


# Metric keys built inline by importers rather than through a fields mapping;
# the source-text assertion below catches a rename that would strand a panel.
_INLINE_IMPORTER_KEYS = {
    "devices/structured.py": (
        "systolic_blood_pressure",
        "diastolic_blood_pressure",
        "blood_pressure_pulse",
        "body_height",
        "body_weight",
        "body_mass_index",
        "body_fat_percentage",
        "body_water_percentage",
        "bone_mass",
        "muscle_mass",
    ),
    "devices/kardia.py": ("ecg_heart_rate",),
    "devices/apple_health.py": ("ecg_heart_rate", "stand_hours"),
}

# Writable metric keys deliberately shown on no panel; each needs a reason.
UNPANELED_DEVICE_KEYS = (
    # Legacy Oura file-export mapping of the bare 'score' field; the API
    # integration writes sleep/readiness/activity scores instead.
    "oura_score",
)


def test_panel_device_members_match_what_importers_write():
    package = Path(__file__).resolve().parents[2] / "src" / "anamna"
    writable = {definition.key for definition in HEALTHKIT_METRICS.values()}
    writable |= {definition.key for definition in SLEEP_METRICS.values()}
    writable |= set(OURA_DEFS)
    writable |= set(OPENWEARABLES_DEFS)
    writable |= {spec[0] for spec in OuraAdapter.fields.values()}
    writable |= {spec[0] for spec in GarminAdapter.fields.values()}
    for relative, keys in _INLINE_IMPORTER_KEYS.items():
        source = (package / relative).read_text(encoding="utf-8")
        for key in keys:
            assert f'"{key}"' in source, (relative, key)
            writable.add(key)
    paneled = {key for panel in PANELS for key in panel.device_members}
    # A same-measurement twin is read on its concept's card, so it is paneled
    # through that concept and must not be named by a panel a second time.
    assert paneled & SAME_DEVICE_KEYS == set()
    assert all(panel_for_concept(TWIN_OF_DEVICE[key][0]) for key in SAME_DEVICE_KEYS)
    paneled |= SAME_DEVICE_KEYS
    assert paneled - writable == set()
    assert writable - paneled - set(UNPANELED_DEVICE_KEYS) == set()


def test_retest_cadence_resolves_through_dynamic_sweeps(tmp_path: Path):
    with _seeded(tmp_path) as connection:
        member = panel_members(connection, PANEL_BY_ID["urinalysis"])[0]
        connection.execute(
            """INSERT INTO concept_guidance(concept_id, retest_interval_months) VALUES (?, 1)
               ON CONFLICT(concept_id) DO UPDATE SET retest_interval_months=1""",
            (member,),
        )
        # The urinalysis panel has no named members, so only the category
        # sweep can carry the cadence to the panel.
        assert panel_retest_months(connection, PANEL_BY_ID["urinalysis"]) == 1


def test_measurement_twins_name_real_concepts_and_known_relations():
    """Every concept in the twin map is seeded, every relation is one of the
    three, and no device key is twinned with two concepts."""
    from anamna.ingest.concepts import CONCEPT_DEFINITIONS

    seeded = {stable_concept_id(str(item["name"])) for item in CONCEPT_DEFINITIONS}
    assert set(MEASUREMENT_TWINS) <= seeded
    pairs = [(key, kind) for twins in MEASUREMENT_TWINS.values() for key, kind in twins]
    assert {kind for _, kind in pairs} <= {"same", "method", "related"}
    assert len({key for key, _ in pairs}) == len(pairs)
    # Laboratory glucose has no device twin: a monitor reads interstitial fluid.
    assert not any("glucose" in concept for concept in MEASUREMENT_TWINS)


def test_ecg_heart_rate_is_filed_in_one_panel():
    from anamna.web import app as web

    homes = {panel.id for panel in PANELS if "ecg_heart_rate" in panel.device_members}
    homes.add(web._DEVICE_PANEL_BY_METRIC["ecg_heart_rate"])
    assert homes == {panel_for_concept("ecg-heart-rate").id} == {"blood_pressure"}
