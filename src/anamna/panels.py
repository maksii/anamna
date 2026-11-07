"""Panels: the groups of analytes that are ordered and read together.

A panel is the primary navigational object ("how are my lipids"), the single
analyte is the drill-down.  Panel membership is deliberately independent of
``concepts.category``: erythrocyte sedimentation rate is an inflammation marker
that is nevertheless printed on every complete blood count.

Member ids are derived with :func:`stable_concept_id` from the canonical name
so a rename in ``CONCEPT_DEFINITIONS`` cannot silently orphan a panel row; the
test suite asserts every member resolves to a seeded concept.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .i18n import translate_phrase
from .ingest.concepts import stable_concept_id


ATTENTION_INTERPRETATIONS = frozenset(
    {"low", "high", "critical_low", "critical_high", "positive"}
)
BORDERLINE_INTERPRETATIONS = frozenset(
    {"borderline_low", "borderline_high", "borderline", "indeterminate"}
)
NORMAL_INTERPRETATIONS = frozenset({"normal", "optimal", "negative"})

#: Results kept in the record but excluded from panels and the default catalog.
#: They remain reachable by direct search - extracted data is never deleted.
DISPLAY_SUPPRESSED = frozenset(
    {
        # An intermediate hematocrit used only to compute red-cell folate; it
        # duplicates the CBC hematocrit and is not a result in its own right.
        "red-cell-folate-calculation-hematocrit",
        # Recording length is device telemetry, not a result; the recording
        # itself lives on /devices/ecg and the id stays reachable by search.
        "ecg-recording-duration",
    }
)


#: One quantity reaching the record on two paths: a concept parsed out of a
#: document, and a device's daily metric.  The single map every page, export
#: and correlation reads the pairing from; nothing else may pair them by name.
#:
#: ``same``    one measurement (a scale, a cuff, a Kardia strip exported twice):
#:             read on the concept page as one series, judged by one library
#:             entry, listed once everywhere.
#: ``method``  the same quantity measured another way (a clinic fingertip spot
#:             check against a wrist sensor's daily average): one page, two
#:             series, each judged by its own library entry, never merged.
#: ``related`` a neighbouring measurement that answers a different question
#:             (a clinic pulse against a watch's resting heart rate): each page
#:             links to the other and says why they differ.
#:
#: Lab glucose has no device twin on purpose: a continuous glucose monitor
#: reads interstitial fluid, and must stay apart if one is ever connected.
MEASUREMENT_TWINS: dict[str, tuple[tuple[str, str], ...]] = {
    "body-weight": (("body_weight", "same"),),
    "body-height": (("body_height", "same"),),
    "body-mass-index": (("body_mass_index", "same"),),
    "systolic-blood-pressure": (("systolic_blood_pressure", "same"),),
    "diastolic-blood-pressure": (("diastolic_blood_pressure", "same"),),
    "pulse-rate": (
        ("blood_pressure_pulse", "same"),
        ("resting_heart_rate", "related"),
        ("daily_heart_rate", "related"),
    ),
    "ecg-heart-rate": (("ecg_heart_rate", "same"),),
    "oxygen-saturation-spo2": (("blood_oxygen", "method"),),
    "resting-respiratory-rate": (("respiratory_rate", "related"),),
    "body-temperature": (
        ("sleeping_wrist_temperature", "related"),
        ("temperature_deviation", "related"),
    ),
}

#: device key -> (concept id, relation): the map read from the device side.
TWIN_OF_DEVICE: dict[str, tuple[str, str]] = {
    key: (concept_id, relation)
    for concept_id, twins in MEASUREMENT_TWINS.items()
    for key, relation in twins
}

#: Device keys that are the same measurement as a concept, and so are never
#: listed as a metric of their own.
SAME_DEVICE_KEYS: frozenset[str] = frozenset(
    key for key, (_concept, relation) in TWIN_OF_DEVICE.items() if relation == "same"
)


def device_twins(concept_id: str, relation: str) -> tuple[str, ...]:
    """The device keys linked to a concept by ``relation``, in map order."""
    return tuple(key for key, kind in MEASUREMENT_TWINS.get(concept_id, ()) if kind == relation)


#: Home monitoring exported as a PDF (a cuff's 4-week log, a Kardia ECG): the
#: same readings the device streams, printed.  Such a document's observation is
#: a duplicate of a device day from the same vendor; a clinic visit never is.
HOME_MONITORING_TYPES = frozenset({"blood_pressure", "electrocardiogram"})


@dataclass(frozen=True)
class Panel:
    id: str
    name: str
    short: str
    description: str
    area_id: str
    member_names: tuple[str, ...] = ()
    #: Concepts whose ``category`` puts them in this panel even though they are
    #: not listed by name (295 allergens, 63 urinalysis rows, serology).
    member_categories: tuple[str, ...] = ()
    device_members: tuple[str, ...] = ()
    renderer: str = "standard"
    #: Cadence comes from the curated library, never from a hand-typed number.
    retest_months: int | None = None
    members: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "members", tuple(stable_concept_id(name) for name in self.member_names)
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "short": self.short,
            "description": self.description,
            "area_id": self.area_id,
            "members": list(self.members),
            "member_names": list(self.member_names),
            "member_categories": list(self.member_categories),
            "device_members": list(self.device_members),
            "renderer": self.renderer,
            "retest_months": self.retest_months,
        }


PANELS: list[Panel] = [
    Panel(
        id="cbc",
        name="Complete blood count",
        short="Blood count",
        description="Red cells, white cells and platelets counted on one sample.",
        area_id="blood",
        member_names=(
            "Hemoglobin",
            "Hematocrit",
            "Red blood cell count",
            "Nucleated red blood cell fraction",
            "Mean corpuscular volume",
            "Mean corpuscular hemoglobin",
            "Mean corpuscular hemoglobin concentration",
            "Red cell distribution width, CV",
            "Red cell distribution width, SD",
            "White blood cell count",
            "Neutrophils",
            "Neutrophils, absolute",
            # The manual (smear) differential, kept as its own rows beside the
            # analyser's: same cells, a different method, often the same day.
            "Segmented neutrophils",
            "Band neutrophils",
            "Neutrophils (manual differential)",
            "Immature granulocytes",
            "Immature granulocytes, absolute",
            "Promyelocytes",
            "Myelocytes",
            "Metamyelocytes",
            "Lymphocytes",
            "Lymphocytes, absolute",
            "Lymphocytes (manual differential)",
            "Atypical lymphocytes",
            "Reactive lymphocytes",
            "Monocytes",
            "Monocytes, absolute",
            "Monocytes (manual differential)",
            "Eosinophils",
            "Eosinophils, absolute",
            "Eosinophils (manual differential)",
            "Basophils",
            "Basophils, absolute",
            "Basophils (manual differential)",
            "Granulocytes",
            "Granulocytes, absolute",
            "Mixed white cells",
            "Mixed white cells, absolute",
            "Platelet count",
            "Mean platelet volume",
            "Platelet distribution width",
            "Platelet distribution width, SD",
            "Platelet large cell ratio",
            "Plateletcrit",
            "Erythrocyte sedimentation rate",
            # Facts printed on the same order: roll_up ignores their
            # not_a_measurement verdicts, mirroring HLA-B27 in autoimmune.
            "Blood group",
            "Rhesus factor",
        ),
    ),
    Panel(
        id="lipids",
        name="Lipid profile (lipidogram)",
        short="Lipids",
        description="Cholesterol fractions and triglycerides used in cardiovascular risk assessment.",
        area_id="heart",
        member_names=(
            "Total cholesterol",
            "LDL cholesterol",
            "HDL cholesterol",
            "VLDL cholesterol",
            "Triglycerides",
            "Atherogenic coefficient",
            # The five below were printed on the same lipid panel the patient
            # ordered and belonged to no panel at all, so they appeared only on
            # their own metric pages -- somebody opening "how are my lipids"
            # saw six of eleven results and none of the three that were high.
            # Apolipoprotein B and lipoprotein(a) are the two the cardiology
            # guidelines add precisely because the cholesterol fractions miss
            # risk, which makes "not on the lipid page" the wrong place for
            # them.
            "Apolipoprotein A1",
            "Apolipoprotein B",
            "Lipoprotein(a)",
            "Non-HDL cholesterol",
            "Beta-lipoproteins",
        ),
    ),
    Panel(
        id="glucose",
        name="Glucose & metabolic control",
        short="Glucose",
        description="Fasting glucose and the three-month average carried by glycated hemoglobin.",
        area_id="metabolism",
        member_names=("Blood glucose", "Hemoglobin A1c", "C-peptide"),
    ),
    Panel(
        id="liver",
        name="Liver panel",
        short="Liver",
        description="Liver enzymes, bilirubin fractions and the serum proteins the liver makes.",
        area_id="liver",
        member_names=(
            "Alanine aminotransferase",
            "Aspartate aminotransferase",
            "Gamma-glutamyl transferase",
            "Alkaline phosphatase",
            "Total bilirubin",
            "Direct bilirubin",
            "Indirect bilirubin",
            "Total protein",
            "Albumin",
            "Albumin fraction",
            "Albumin to globulin ratio",
            "Alpha-1 globulins",
            "Alpha-2 globulins",
            "Beta globulins",
            "Gamma globulins",
            "Thymol turbidity test",
        ),
    ),
    Panel(
        id="pancreas",
        name="Pancreas",
        short="Pancreas",
        description="Pancreatic enzymes measured in serum.",
        area_id="liver",
        member_names=("Alpha-amylase", "Lipase"),
    ),
    Panel(
        id="kidney",
        name="Kidney panel",
        short="Kidneys",
        description="Waste products the kidneys clear from blood.",
        area_id="kidneys",
        member_names=(
            "Creatinine",
            "Estimated glomerular filtration rate (CKD-EPI 2021)",
            "Urea",
            "Uric acid",
        ),
    ),
    Panel(
        id="urinalysis",
        name="Urinalysis",
        short="Urine",
        description="Appearance, dipstick chemistry and microscopy of a urine sample.",
        area_id="kidneys",
        member_categories=("urinalysis",),
        renderer="urinalysis",
    ),
    Panel(
        id="thyroid",
        name="Thyroid",
        short="Thyroid",
        description="Thyroid hormones and the antibodies that attack the thyroid gland.",
        area_id="thyroid",
        member_names=(
            "Thyroid stimulating hormone",
            "Free thyroxine",
            "Free triiodothyronine",
            "Thyroid peroxidase antibodies",
            "Thyroglobulin antibodies",
        ),
    ),
    Panel(
        id="hormones",
        name="Other hormones",
        short="Hormones",
        description="Endocrine measurements outside the thyroid panel.",
        area_id="thyroid",
        member_names=("Parathyroid hormone", "Total testosterone"),
    ),
    Panel(
        id="iron",
        name="Iron status",
        short="Iron",
        description="Circulating iron and the protein that stores it.",
        area_id="blood",
        member_names=("Serum iron", "Ferritin"),
    ),
    Panel(
        id="vitamins",
        name="Vitamins",
        short="Vitamins",
        description="Vitamin D, the B-vitamins and the marker that reflects their supply.",
        area_id="nutrition",
        member_names=(
            "25-hydroxyvitamin D",
            "Vitamin B12",
            "Folate, serum",
            "Whole-blood folate",
            "Red-cell folate concentration",
            "Red-cell folate calculation hematocrit",
            "Homocysteine",
        ),
    ),
    Panel(
        id="minerals",
        name="Minerals & electrolytes",
        short="Minerals",
        description="The salts and minerals that keep nerves, muscle and bone working.",
        area_id="nutrition",
        member_names=("Sodium", "Potassium", "Magnesium", "Calcium, total", "Calcium, ionized"),
    ),
    Panel(
        id="inflammation",
        name="Inflammation",
        short="Inflammation",
        description="General markers that rise when there is inflammation somewhere in the body.",
        area_id="immunity",
        member_names=(
            "C-reactive protein",
            "High-sensitivity C-reactive protein",
            "Erythrocyte sedimentation rate",
            "Fibrinogen",
            "Antistreptolysin O",
            "Rheumatoid factor",
            "Seromucoids",
        ),
    ),
    Panel(
        id="coagulation",
        name="Clotting",
        short="Clotting",
        description="How quickly blood forms a clot.",
        area_id="blood",
        member_names=(
            "INR",
            "Prothrombin time",
            "Quick prothrombin index",
            "Activated partial thromboplastin time",
            "Thrombin time",
            "Fibrinogen",
        ),
    ),
    Panel(
        id="autoimmune",
        name="Autoantibody panel",
        short="Autoantibodies",
        description="Antibodies directed at the body's own tissue, plus the HLA-B27 marker.",
        area_id="immunity",
        member_names=(
            "Antinuclear antibodies",
            "Double-stranded DNA antibodies",
            "Ro/SS-A 52 antibodies",
            "La/SS-B antibodies",
            "CENP-B antibodies",
            "Scl-70 antibodies",
            "Jo-1 antibodies",
            "Myeloperoxidase antibodies",
            "Proteinase 3 antibodies",
            "AMA-M2 antibodies",
            "LC1 antibodies",
            "LKM1 antibodies",
            "PM/Scl-100 antibodies",
            "SRP54 antibodies",
            "Sp100 antibodies",
            "gp210 antibodies",
            "Ku antibodies",
            "Sm antibodies",
            "U1-snRNP antibodies",
            "HLA-B27",
        ),
    ),
    Panel(
        id="allergy",
        name="Allergen-specific IgE",
        short="Allergy",
        description="Total IgE and the allergen-specific IgE results from the ImmunoCAP panel.",
        area_id="allergy",
        member_names=("Total immunoglobulin E",),
        member_categories=("allergy",),
        renderer="allergy",
    ),
    Panel(
        id="infection",
        name="Infection serology",
        short="Serology",
        description="Antibody and antigen tests for transmissible infections.",
        area_id="infection",
        member_categories=("infection",),
    ),
    Panel(
        id="microbiology",
        name="Culture & susceptibility",
        short="Cultures",
        description="What grew from a sample and which antibiotics it responded to.",
        area_id="infection",
        member_categories=("microbiology",),
    ),
    Panel(
        id="gastro",
        name="Digestive testing",
        short="Digestive",
        description="Laboratory testing of the stomach and intestines.",
        area_id="digestive",
        member_names=("H. pylori stool antigen",),
    ),
    Panel(
        id="coprogram",
        name="Stool analysis (coprogram)",
        short="Coprogram",
        description="Physical, chemical and microscopic examination of a stool sample.",
        area_id="digestive",
        member_categories=("stool",),
    ),
    Panel(
        id="blood_pressure",
        name="Blood pressure",
        short="Blood pressure",
        description="Systolic and diastolic pressure read together with the pulse.",
        area_id="heart",
        member_names=(
            "Systolic blood pressure",
            "Diastolic blood pressure",
            "Pulse rate",
            "ECG heart rate",
            "Blood pressure category",
            "Weekly systolic blood pressure minimum",
            "Weekly systolic blood pressure maximum",
            "Weekly diastolic blood pressure minimum",
            "Weekly diastolic blood pressure maximum",
            "Weekly blood pressure reading count",
        ),
        # The cuff's and the Kardia's daily values arrive on these concepts'
        # own cards (MEASUREMENT_TWINS), so the panel names no device key.
        renderer="blood_pressure",
    ),
    Panel(
        id="vitals",
        name="Vital signs",
        short="Vitals",
        description="Temperature, breathing rate and oxygen saturation measured at a visit.",
        # Filed beside blood pressure and pulse, the other half of the same
        # «Життєві показники» block of a visit note.
        area_id="heart",
        member_names=("Body temperature", "Oxygen saturation (SpO2)", "Resting respiratory rate"),
    ),
    Panel(
        id="ecg",
        name="ECG intervals",
        short="ECG",
        description="How long each electrical phase of the heartbeat lasts on a 12-lead ECG.",
        area_id="heart",
        member_names=("PR interval", "QRS duration", "QT interval", "QTc (Bazett)", "QTc (Framingham)"),
    ),
    Panel(
        id="body",
        name="Body composition",
        short="Body",
        description="Weight and what it is made of.",
        area_id="body",
        # Weighed and measured at a visit or by a scale: one card each, the
        # scale's days included (MEASUREMENT_TWINS).
        member_names=("Body weight", "Body height", "Body mass index"),
        device_members=(
            "body_fat_percentage",
            "lean_body_mass",
            "waist_circumference",
            "bone_mass",
            "muscle_mass",
            "body_water_percentage",
        ),
    ),
    Panel(
        id="cardio_fitness",
        name="Cardio fitness",
        short="Fitness",
        description="How the heart responds to effort and to rest.",
        # Filed under the heart rather than under activity: every member is a
        # property of the beat, and the activity view keeps the metrics anyway
        # through their own sensor category.
        area_id="heart",
        device_members=(
            "vo2_max",
            "resting_heart_rate",
            "lowest_sleeping_heart_rate",
            "daily_heart_rate",
            "heart_rate_variability",
            "heart_rate_recovery",
            "walking_heart_rate",
            "pulse_wave_velocity",
            "cardiovascular_age",
        ),
    ),
    Panel(
        id="sleep",
        name="Sleep",
        short="Sleep",
        description="Sleep stages and the vital signs recorded overnight.",
        area_id="sleep",
        device_members=(
            "sleep_duration",
            "sleep_deep",
            "sleep_rem",
            "sleep_core",
            "sleep_awake",
            "time_in_bed",
            "sleep_efficiency",
            "sleep_score",
            "respiratory_rate",
            "blood_oxygen",
            "sleeping_wrist_temperature",
            "breathing_disturbances",
            "breathing_disturbance_index",
            "sleeping_heart_rate",
            "heart_rate_variability_rmssd",
            "sleep_interruptions",
            "sleep_naps",
            "sleep_nap_duration",
        ),
    ),
    Panel(
        id="recovery",
        name="Recovery & stress",
        short="Recovery",
        description="How the body recharges: readiness, stress balance and overnight temperature.",
        # Under sleep, like the rest of the device_recovery category: recovery
        # is measured overnight even though it is spent during the day.
        area_id="sleep",
        device_members=(
            "readiness_score",
            "temperature_deviation",
            "stress_high_time",
            "recovery_high_time",
            "stress_level",
            "body_battery_high",
            "body_battery_low",
            "recovery_score",
            "stress_score",
            "resilience_score",
            "body_battery_score",
            "strain_score",
            "health_recovery_score",
        ),
    ),
    Panel(
        id="activity",
        name="Daily activity",
        short="Activity",
        description="Movement, exercise and energy across the day.",
        area_id="activity",
        device_members=(
            "steps",
            "exercise_minutes",
            "active_minutes",
            "sedentary_minutes",
            "light_activity",
            "moderate_activity",
            "vigorous_activity",
            "active_energy",
            "resting_energy",
            "total_energy",
            "elevation",
            "walking_running_distance",
            "flights_climbed",
            "stand_minutes",
            "stand_hours",
            "activity_score",
            "physical_effort",
            "cycling_distance",
            "swimming_distance",
            "swimming_strokes",
        ),
    ),
    Panel(
        id="hearing",
        name="Hearing & environment",
        short="Hearing",
        description="Noise exposure from surroundings and headphones, and daily daylight.",
        area_id="environment",
        device_members=(
            "environmental_audio",
            "headphone_audio",
            "environmental_sound_reduction",
            "time_in_daylight",
        ),
    ),
    Panel(
        id="mobility",
        name="Mobility & gait",
        short="Mobility",
        description="Walking speed, step length, steadiness and asymmetry.",
        area_id="mobility",
        device_members=(
            "walking_speed",
            "walking_step_length",
            "walking_asymmetry",
            "walking_double_support",
            "walking_steadiness",
            "six_minute_walk",
            "stair_ascent_speed",
            "stair_descent_speed",
        ),
    ),
]

PANEL_BY_ID: dict[str, Panel] = {panel.id: panel for panel in PANELS}

PANELS_BY_AREA: dict[str, list[Panel]] = {}
for _panel in PANELS:
    PANELS_BY_AREA.setdefault(_panel.area_id, []).append(_panel)

# First listing wins: a concept named by one panel and swept up by another
# panel's category still reads as a member of the panel that names it.
_PANEL_BY_CONCEPT: dict[str, Panel] = {}
_PANEL_BY_CATEGORY: dict[str, Panel] = {}
for _panel in PANELS:
    for _member in _panel.members:
        _PANEL_BY_CONCEPT.setdefault(_member, _panel)
    for _category in _panel.member_categories:
        _PANEL_BY_CATEGORY.setdefault(_category, _panel)
del _panel


def panel_for_concept(concept_id: str, category: str | None = None) -> Panel | None:
    """Return the panel a concept is read in, or ``None``.

    ``category`` resolves the panels whose membership is dynamic (allergens,
    urinalysis rows, serology), which are far too numerous to list by name.
    """
    panel = _PANEL_BY_CONCEPT.get(concept_id)
    if panel is not None:
        return panel
    return _PANEL_BY_CATEGORY.get(category or "")


def panel_members(connection: sqlite3.Connection, panel: Panel) -> list[str]:
    """Concept ids in clinical reading order, named members first."""
    members = [member for member in panel.members if member not in DISPLAY_SUPPRESSED]
    if not panel.member_categories:
        return members
    seen = set(members)
    placeholders = ",".join("?" for _ in panel.member_categories)
    rows = connection.execute(
        f"SELECT id FROM concepts WHERE category IN ({placeholders}) ORDER BY canonical_name",
        panel.member_categories,
    ).fetchall()
    members.extend(
        row["id"]
        for row in rows
        if row["id"] not in seen and row["id"] not in DISPLAY_SUPPRESSED
    )
    return members


def panel_retest_months(connection: sqlite3.Connection, panel: Panel) -> int | None:
    """Shortest cited retest cadence among the panel's members.

    Returns ``None`` when no member has a published screening interval - that
    is a real answer, not a missing one, and must never be filled with a
    hand-picked cadence.
    """
    if panel.retest_months is not None:
        return panel.retest_months
    # panel_members includes dynamic category sweeps, so all-dynamic panels
    # (urinalysis, coprogram) can resolve a cadence from their swept members.
    keys = panel_members(connection, panel) + list(panel.device_members)
    if not keys:
        return None
    placeholders = ",".join("?" for _ in keys)
    # A conditional cadence ("repeat a raised TSH after 3 months", FIT from 45)
    # is not the panel's schedule. Each member judges its own condition in
    # staleness(), and the worst member state still governs the panel.
    row = connection.execute(
        f"""SELECT MIN(retest_interval_months) FROM concept_guidance
            WHERE concept_id IN ({placeholders}) AND retest_interval_months IS NOT NULL
              AND retest_condition_json IS NULL""",
        keys,
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _interpretation_of(member: object) -> str:
    if isinstance(member, str):
        return member
    if isinstance(member, dict):
        verdict = member.get("verdict") or member
        if isinstance(verdict, dict):
            return str(verdict.get("interpretation") or "unjudged")
    return "unjudged"


def roll_up(members, staleness: dict[str, object] | None = None) -> dict[str, object]:
    """Collapse member verdicts into one panel status.

    ``members`` accepts interpretation strings, ``Verdict`` dicts or
    ``MetricCard`` dicts.  ``attention`` and ``stale`` are reported as separate
    flags because they describe different problems, and ``attention`` takes the
    display slot when both apply.
    """
    # Blood group and HLA-B27 are facts, not results: they can never make a
    # panel look unjudged, and they can never make it look abnormal either.
    interpretations = [
        value
        for value in (_interpretation_of(member) for member in members)
        if value != "not_a_measurement"
    ]
    stale = bool(staleness and staleness.get("state") in {"overdue", "never"})
    flagged = sum(1 for value in interpretations if value in ATTENTION_INTERPRETATIONS)
    if not interpretations:
        return {"status": "absent", "attention": False, "stale": False, "flagged_count": 0}
    if flagged:
        status = "attention"
    elif any(value in BORDERLINE_INTERPRETATIONS for value in interpretations):
        status = "borderline"
    elif any(value in NORMAL_INTERPRETATIONS for value in interpretations):
        status = "normal"
    else:
        status = "stale" if stale else "unjudged"
    return {
        "status": status,
        "attention": status == "attention",
        "stale": stale,
        "flagged_count": flagged,
    }


def localized_panels() -> list[dict[str, object]]:
    return [
        {
            **panel.as_dict(),
            "name": translate_phrase(panel.name),
            "short": translate_phrase(panel.short),
            "description": translate_phrase(panel.description),
        }
        for panel in PANELS
    ]
