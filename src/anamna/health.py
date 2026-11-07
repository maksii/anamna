from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import date
from functools import lru_cache

from .config import ID_NAMESPACE_PREFIX
from .db import utc_now
from .i18n import get_locale, t, translate_phrase
from .ingest.classifier import PATIENT_LABEL_RE, VISIT_SECTION_RES
from .ingest.parsers import (
    DEMOGRAPHIC_REFERENCE_RE,
    NON_NORMAL_BAND_RE,
    SPLIT_DECIMAL_RE,
    demographic_reference,
    reference_bounds,
    reference_limits,
)
from .ingest.text import collapse_space, normalized_key, search_key
from .locales.concepts_en import CONCEPT_NAMES_EN
from .locales.concepts_uk import CONCEPT_NAMES_UK
from .locales.phrases import PHRASES
from .panels import DISPLAY_SUPPRESSED, PANEL_BY_ID  # noqa: F401  (re-exported for the web layer)


HEALTH_AREAS: list[dict[str, object]] = [
    {"id": "blood", "name": "Blood health", "short": "Blood", "categories": {"hematology", "coagulation", "iron"}, "description": "Blood counts, clotting and iron stores"},
    {"id": "heart", "name": "Heart & circulation", "short": "Heart", "categories": {"lipids", "cardiovascular", "vital_signs"}, "description": "Blood pressure, cholesterol, heart imaging and blood flow"},
    {"id": "metabolism", "name": "Glucose & metabolism", "short": "Metabolism", "categories": {"metabolic"}, "description": "Glucose control, proteins and metabolic markers"},
    {"id": "liver", "name": "Liver & pancreas", "short": "Liver", "categories": {"liver", "pancreas"}, "description": "Liver enzymes, bilirubin and pancreatic markers"},
    {"id": "kidneys", "name": "Kidneys & urinary", "short": "Kidneys", "categories": {"renal", "urinalysis"}, "description": "Kidney function and urine testing"},
    {"id": "thyroid", "name": "Thyroid & hormones", "short": "Hormones", "categories": {"thyroid", "hormones"}, "description": "Thyroid and endocrine measurements"},
    {"id": "nutrition", "name": "Vitamins & minerals", "short": "Nutrition", "categories": {"vitamins", "electrolytes"}, "description": "Vitamins, minerals and electrolytes"},
    {"id": "immunity", "name": "Immunity & inflammation", "short": "Immunity", "categories": {"immunology", "immunogenetics", "inflammation", "autoimmune"}, "description": "Inflammatory and immune-system markers"},
    {"id": "spine", "name": "Bones & spine", "short": "Bones & spine", "categories": set(), "description": "Cervical, thoracic and lumbar imaging with related bone markers"},
    {"id": "joints", "name": "Joints & soft tissue", "short": "Joints", "categories": set(), "description": "Joint, tendon and soft-tissue imaging with related inflammation and urate results"},
    {"id": "lungs", "name": "Lungs & chest", "short": "Lungs", "categories": set(), "description": "Chest imaging and respiratory evidence"},
    {"id": "digestive", "name": "Stomach & intestines", "short": "Stomach", "categories": {"stool"}, "description": "Stomach and intestinal pathology, procedures and related testing"},
    {"id": "allergy", "name": "Allergy", "short": "Allergy", "categories": {"allergy"}, "description": "Allergen-specific and total IgE testing"},
    {"id": "infection", "name": "Infection & microbiology", "short": "Infection", "categories": {"infection", "microbiology"}, "description": "Cultures, organisms and infection markers"},
    {"id": "ent", "name": "ENT & sinuses", "short": "ENT", "categories": set(), "description": "Ear, nose, throat and sinus imaging"},
    {"id": "skin", "name": "Skin", "short": "Skin", "categories": set(), "description": "Dermatology consultations and skin findings"},
    {"id": "brain", "name": "Brain & nervous system", "short": "Brain", "categories": set(), "description": "Brain recordings such as the EEG (electroencephalogram, a recording of the brain's electrical activity), and visits for headaches and other nervous-system complaints"},
    {"id": "body", "name": "Body composition", "short": "Body", "categories": {"device_body", "body"}, "description": "Weight, body mass index, body fat and lean mass"},
    {"id": "activity", "name": "Activity & fitness", "short": "Activity", "categories": {"device_activity", "device_fitness"}, "description": "Movement, exercise, energy and cardio fitness"},
    {"id": "mobility", "name": "Mobility & gait", "short": "Mobility", "categories": {"device_mobility"}, "description": "Walking speed, step length, steadiness and asymmetry"},
    {"id": "sleep", "name": "Sleep & recovery", "short": "Sleep", "categories": {"device_sleep", "device_recovery"}, "description": "Sleep stages, heart-rate recovery, oxygen and breathing"},
    {"id": "environment", "name": "Hearing & environment", "short": "Environment", "categories": {"device_environment"}, "description": "Sound exposure and time in daylight"},
]

AREA_BY_ID = {str(area["id"]): area for area in HEALTH_AREAS}
CATEGORY_TO_AREA = {
    str(category): str(area["id"])
    for area in HEALTH_AREAS
    for category in area["categories"]
}

# A laboratory result can be relevant to more than one body-system view. The
# first area remains its canonical home; the additional links only colocate
# source evidence and never imply a diagnosis or causal relationship.
#
# The mapping is derived from panel membership rather than hand-listed per
# concept, so the joint and spine views grow as the panels do instead of
# depending on someone remembering to extend a literal.
PANEL_RELATED_AREAS: dict[str, set[str]] = {
    "inflammation": {"joints"},
}

# Concept-level links where the panel as a whole would be too coarse.  The
# whole autoimmune and minerals panels used to reach "Bones & spine", which
# listed liver-specific autoantibodies, sodium and potassium as spine results
# (CLIN-34).  Each autoantibody now goes where it is read: systemic and
# myositis antibodies beside joints and soft tissue, liver antibodies beside
# the liver, HLA-B27 and the inflammation markers beside the spine.
CONCEPT_RELATED_AREAS: dict[str, set[str]] = {
    "25-hydroxyvitamin D": {"spine"},
    "Alkaline phosphatase": {"spine"},
    "Calcium, total": {"spine"},
    "Calcium, ionized": {"spine"},
    "HLA-B27": {"joints", "spine"},
    "C-reactive protein": {"spine"},
    "Erythrocyte sedimentation rate": {"spine"},
    **{name: {"joints"} for name in (
        "Antinuclear antibodies", "Double-stranded DNA antibodies", "Ro/SS-A 52 antibodies",
        "La/SS-B antibodies", "CENP-B antibodies", "Scl-70 antibodies", "Jo-1 antibodies",
        "PM/Scl-100 antibodies", "SRP54 antibodies", "Ku antibodies", "Sm antibodies",
        "U1-snRNP antibodies",
    )},
    **{name: {"liver"} for name in (
        "AMA-M2 antibodies", "LC1 antibodies", "LKM1 antibodies", "Sp100 antibodies", "gp210 antibodies",
    )},
    "Uric acid": {"joints"},
    "Homocysteine": {"heart"},
    # Spot readings from a visit note, read on the lungs view beside the chest
    # imaging as the device's overnight breathing and oxygen metrics are.
    "Oxygen saturation (SpO2)": {"lungs"},
    "Resting respiratory rate": {"lungs"},
    # Parathyroid hormone is an endocrine result that is read beside calcium
    # and vitamin D, so it also belongs in the nutrition view.
    "Parathyroid hormone": {"nutrition"},
    # H. pylori is now categorised as an infection; the digestive view is
    # where a person looks for it.
    "H. pylori stool antigen": {"digestive"},
    # A respiratory infection: the lungs view is where a person looks for it.
    "SARS-CoV-2 antigen": {"lungs"},
}

# Device metrics whose sensor category (device_recovery, shown under Sleep)
# does not reach the body-system view they also inform.
DEVICE_RELATED_AREAS: dict[str, set[str]] = {
    "blood_oxygen": {"lungs"},
    "respiratory_rate": {"lungs"},
    "breathing_disturbances": {"lungs"},
    "breathing_disturbance_index": {"lungs"},
    # Rate, rhythm and pressure reach the record through a wrist or a cuff, so
    # their sensor category files them under sleep or fitness.  That is where
    # they were measured, not what they are about: every one of them is read on
    # the heart view too, which would otherwise show cholesterol and nothing
    # about the beat itself.
    "daily_heart_rate": {"heart"},
    "resting_heart_rate": {"heart"},
    "walking_heart_rate": {"heart"},
    "heart_rate_variability": {"heart"},
    "heart_rate_recovery": {"heart"},
    "vo2_max": {"heart"},
}


def _related_concept_areas() -> dict[str, set[str]]:
    related: dict[str, set[str]] = {}
    for panel_id, areas in PANEL_RELATED_AREAS.items():
        for name in PANEL_BY_ID[panel_id].member_names:
            related.setdefault(name, set()).update(areas)
    for name, areas in CONCEPT_RELATED_AREAS.items():
        related.setdefault(name, set()).update(areas)
    return related


RELATED_CONCEPT_AREAS: dict[str, set[str]] = _related_concept_areas()

CATEGORY_LABELS = {
    "hematology": "Blood count",
    "coagulation": "Clotting",
    "iron": "Iron",
    "lipids": "Cholesterol & lipids",
    "cardiovascular": "Blood pressure & circulation",
    "metabolic": "Glucose control",
    "chemistry": "Blood chemistry",
    "liver": "Liver",
    "pancreas": "Pancreas",
    "tumour_markers": "Tumour markers",
    "renal": "Kidney function",
    "urinalysis": "Urinalysis",
    "thyroid": "Thyroid",
    "hormones": "Hormones",
    "vitamins": "Vitamins",
    "electrolytes": "Minerals & electrolytes",
    "immunology": "Immunology",
    "immunogenetics": "Immunogenetics",
    "autoimmune": "Autoantibodies",
    "inflammation": "Inflammation",
    "stool": "Stool analysis",
    "allergy": "Allergy",
    "infection": "Infection",
    "microbiology": "Microbiology",
    "vital_signs": "Vital signs",
    "body": "Body measurements",
    "device_body": "Body composition",
    "device_activity": "Daily activity",
    "device_fitness": "Fitness",
    "device_mobility": "Mobility",
    "device_sleep": "Sleep",
    "device_recovery": "Recovery & vitals",
    "device_environment": "Environment & hearing",
    "unmapped": "Other extracted result",
}

# English spellings that several translation tables share.
_NOT_DETECTED = "Not detected"
_NOT_DETECTED_TEXT = "not detected"
_HIGH_RISK = "high risk"
_UMOL_L = "µmol/L"
_MIU_L = "mIU/L"
_CELLS_UL = "cells/µL"
_GENOME_EQ_ML = "genome equivalents/mL"
_GIGA_PER_L = "10^9/L"
_TERA_PER_L = "10^12/L"
_EGFR_UNIT = "mL/min/1.73m²"
_BREATHS_PER_MIN = "breaths/min"

VALUE_TRANSLATIONS = {
    "не виявлено": _NOT_DETECTED,
    "не виявлений": _NOT_DETECTED,
    "не виявлена": _NOT_DETECTED,
    "не виявлені": _NOT_DETECTED,
    "негативний": "Negative",
    "негативна": "Negative",
    "позитивний": "Positive",
    "позитивна": "Positive",
    "чутливий": "Susceptible",
    "помірночутливий": "Intermediate susceptibility",
    "резистентний": "Resistant",
    "норма": "Normal",
    "нормальний": "Normal",
    "нормальна": "Normal",
    "високий нормальний": "High-normal",
    "ступінь 1": "Grade 1",
    "ступінь 2": "Grade 2",
    # Every rhythm a Kardia 6L can determine, per AliveCor's own product
    # documentation.  Stored as the device prints them, in English, so it is
    # the reverse direction that carries them -- and without an entry here a
    # Ukrainian reader is shown the finding of their ECG in English.
    "нормальний синусовий ритм": "Normal Sinus Rhythm",
    "фібриляція передсердь": "Atrial Fibrillation",
    "брадикардія": "Bradycardia",
    "тахікардія": "Tachycardia",
    "синусовий ритм із шлуночковими екстрасистолами (шес)":
        "Sinus Rhythm with Premature Ventricular Contractions (PVCs)",
    "синусовий ритм із надшлуночковою ектопією (нше)":
        "Sinus Rhythm with Supraventricular Ectopy (SVE)",
    "синусовий ритм із широким комплексом qrs": "Sinus Rhythm with Wide QRS",
    "не класифіковано": "Unclassified",
    "непридатний для зчитування": "Unreadable",
    # The coprogram, whose results are words rather than numbers.  Two pages
    # of them were unreadable by the parser until now, so none of these had
    # ever needed an English form.
    "коричневий": "Brown",
    "неоформлений": "Unformed",
    "мазеподібний": "Mushy",
    # Keyed without the comma: lookups go through `normalized_key`, which
    # turns punctuation into spaces, so a key carrying one never matches.
    "каловий нерізкий": "Faecal, mild",
    "невелика к-сть.": "Small amount",
    "поодиноко": "Occasional",
    "поодиноко в п/з": "Occasional per HPF",
    "прозора": "Clear",
    "каламутна": "Cloudy",
    "жовтий": "Yellow",
    "бурштиновий": "Amber",
    "сліди": "Trace",
}

UNIT_TRANSLATIONS = {
    "ммоль/л": "mmol/L",
    "мкмоль/л": _UMOL_L,
    "нг/мл": "ng/mL",
    "пг/мл": "pg/mL",
    "мг/дл": "mg/dL",
    "г/л": "g/L",
    "мг/л": "mg/L",
    "мкг/л": "µg/L",
    "ммо/л": _MIU_L,
    "мо/мл": "IU/mL",
    "мо/л": "IU/L",
    "мекв/л": "mEq/L",
    "од/л": "U/L",
    "пмоль/л": "pmol/L",
    "нмоль/л": "nmol/L",
    "кл/мкл": _CELLS_UL,
    "цл/мкл": "casts/µL",
    "гє/мл": _GENOME_EQ_ML,
    # The same unit with the Е/Є homoglyph pair: EskuLab prints «ГЄ/мл» on the
    # Ureaplasma rows and «Mycoplasma genitalium (ПЛР)... ГЕ/мл» two lines down.
    "ге/мл": _GENOME_EQ_ML,
    "куо/г": "CFU/g",
    # Urine microscopy: cells per high-power field, «в полі зору».
    "в п/з": "per HPF",
    "секунди": "s",
    "сек": "s",
    "мм/год": "mm/h",
    "х 10*9/л": _GIGA_PER_L,
    "х 10*12/л": _TERA_PER_L,
    "10*9/л": _GIGA_PER_L,
    "10*12/л": _TERA_PER_L,
    "г/дл": "g/dL",
    # The Cyrillic spellings of ng/dL, µU/mL and U/mL, exactly: free T4,
    # insulin and the CA 15-3 / CA 125 markers on Synevo panels.  Micro-units
    # are deliberately not folded onto mIU/L here: the two are equal only for
    # assays calibrated to an international standard (insulin is one), so
    # that equivalence belongs to a per-concept alias, not to every analyte.
    "нг/дл": "ng/dL",
    "мкод/мл": "µU/mL",
    "од/мл": "U/mL",
    # Millilitres: in UNIT_PATTERN and therefore parsed, but absent here, so a
    # delivered urine volume printed «мл» canonicalised to «мл» while its
    # concept declared "mL" -- the same quantity failing to compare with itself.
    "мл": "mL",
    "×10⁹/л": _GIGA_PER_L,
    "×10¹²/л": _TERA_PER_L,

    "фл": "fL",
    # Bare «од» is "units" -- arbitrary units on an assay that has none of its
    # own.  Not folded onto "ratio": seromucoid units are not a coefficient,
    # and rendering them as one states a relationship that was never measured.
    # «од/л» (U/L) is a separate key and is unaffected.
    "од": "units",
    "індекс": "index",
    "коефіцієнт": "ratio",
    "мм рт. ст.": "mmHg",
    "уд/хв": "bpm",
    "мс": "ms",
    "км/год": "km/h",
    "км": "km",
    # Bare metres: the six-minute-walk distance arrives from Apple Health as
    # "m", which rendered untranslated beside «км» and «см» on the Ukrainian
    # mobility page. Same quantity in both spellings, so folding is safe.
    "м": "m",
    "см": "cm",
    # Echo and ultrasound measurements (LV mass index, intima-media thickness,
    # carotid velocity, bile duct, bladder wall) and the eGFR the labs print.
    # Unfolded, the curated bands written in the Latin form skip every value.
    "мм": "mm",
    "г/м²": "g/m²",
    "см/с": "cm/s",
    "мл/хв/1,73 м²": _EGFR_UNIT,
    "кг": "kg",
    # Grams: left ventricular mass on an echo report.
    "г": "g",
    "кг/м²": "kg/m²",
    "мл/кг/хв": "mL/kg/min",
    "дба": "dBA",
    "год": "hours",
    "кроків": "steps",
    "вдихів/хв": _BREATHS_PER_MIN,
    "поверхів": "flights",
    "ккал": "kcal",
    "хв": "min",
    "кількість": "count",
    # Device metrics from the Oura API: proprietary 0-100 scores, the
    # breathing-disturbance index (events per hour of sleep), pulse-wave
    # velocity and the vendor's "cardiovascular age".
    "балів": "score",
    "на годину": "per hour",
    "м/с": "m/s",
    "років": "years",
}


_VALUE_REVERSE = {english.casefold(): ukrainian for ukrainian, english in VALUE_TRANSLATIONS.items()}
_UNIT_REVERSE = {english.casefold(): ukrainian for ukrainian, english in UNIT_TRANSLATIONS.items()}
# The lookup keys above are lowercased, which a few Ukrainian units cannot
# survive: «мМО/л» is milli-International Units per litre, and «ммо/л» reads as
# millimoles to anyone scanning the column.  Displayed spelling is set here.
_UNIT_REVERSE["miu/l"] = "мМО/л"
# Same reason: «МО» is an abbreviation of «міжнародні одиниці» and is printed
# in capitals, which the casefolded lookup key cannot carry.
_UNIT_REVERSE["iu/l"] = "МО/л"
# «мкОд/мл» as the laboratory prints it, not «мкод/мл».  Keyed as casefold()
# leaves "µU/mL" (µ becomes U+03BC).
_UNIT_REVERSE["μu/ml"] = "мкОд/мл"
# Device units: decibels keep their capital B («дБА», not «дба»); a bare count
# reads as pieces («326 шт.», not «326 кількість»); Apple's physical-effort
# unit had no Ukrainian form at all.
_UNIT_REVERSE["dba"] = "дБА"
_UNIT_REVERSE["count"] = "шт."
_UNIT_REVERSE["met-like effort"] = "MET-еквівалент"
# And the same again for the rhythm determinations.  A laboratory value reads
# «негативний» in lower case because that is how the report prints it, but a
# rhythm is the report's conclusion and is printed as a sentence.  Taken from
# the phrase catalogue rather than spelled a second time here, so the two can
# never drift into two different Ukrainian renderings of one finding.
for _determination in (
    "Normal Sinus Rhythm", "Atrial Fibrillation", "Bradycardia", "Tachycardia",
    "Sinus Rhythm with Premature Ventricular Contractions (PVCs)",
    "Sinus Rhythm with Supraventricular Ectopy (SVE)",
    "Sinus Rhythm with Wide QRS", "Unclassified", "Unreadable",
):
    _VALUE_REVERSE[normalized_key(_determination)] = PHRASES[_determination]

#: Alternative spellings that mean exactly the same quantity as a canonical
#: form above.  An unfolded synonym is not a cosmetic problem: it gives the
#: analyte a second unit, which splits its trend into two unrelated series and
#: makes every curated rule written in the canonical unit skip the value in
#: silence -- the reading is stored, and the page looks like it was never taken.
#: Synevo prints all six of these; the app already held the other spelling.
UNIT_SYNONYMS = {
    "мкмо/мл": _MIU_L,  # µIU/mL and mIU/L are the same quantity, exactly 1:1
    "ммо/мл": "IU/L",   # «мМО/мл», mIU/mL: 10^-3 IU per 10^-3 L is exactly IU/L (Synevo beta-hCG)
    "f/л": "fL",         # one lab's spelling; «фл» above is what Ukrainian shows
    "пг": "pg",
    "мм/год.": "mm/h",   # the trailing full stop is the lab's, not a new unit
    "coi": "index",      # cut-off index: dimensionless, as «індекс» already is
    # A caret exponent with the "/л" lost to a neighbouring text object. Folded
    # so a leukocyte count printed «10^9» is the same measurement as one
    # printed «х 10*9/л»; unfolded it would give the analyte a second unit and
    # split its trend into two series that never meet.
    "10^9": _GIGA_PER_L,
    "10^12": _TERA_PER_L,
    # Latin-script spellings of the same three quantities «мкМО/мл», «кл/мкл»
    # and «тис/мкл» name.  µIU/mL is exactly mIU/L (10^-6 IU per 10^-3 L), and
    # a thousand cells per microlitre is exactly 10^9 per litre.  Written out
    # so a TSH printed "µIU/mL" and one printed «мкМО/мл» land in one series
    # rather than two half-length ones the curated band judges neither of.
    "μiu/ml": _MIU_L,  # U+03BC: str.casefold() rewrites µ (U+00B5) to it
    "uiu/ml": _MIU_L,       # exports that cannot emit a micro sign at all
    "клітин/мкл": _CELLS_UL,
    "тис/мкл": _GIGA_PER_L,
    "мкг/мл": "mg/L",        # 1 µg/mL is 1 mg/L exactly
    "mm/hr": "mm/h",
    # Spellings of the echo/ultrasound and eGFR units above as reports print
    # them.  A cubic centimetre is exactly a millilitre (thyroid volume);
    # «сm3» starts with a Cyrillic «с».
    "г/м2": "g/m²",
    "см3": "mL",
    "cm3": "mL",
    "сm3": "mL",
    # Expert Hospital's duplex prints peak systolic velocity «см/сек»: the
    # same centimetres per second the library's carotid bands are written in.
    "см/сек": "cm/s",
    "мл/хв/1,73м2": _EGFR_UNIT,
    "мл/хв/1,73 м2": _EGFR_UNIT,
    "мл/хв/1,73м²": _EGFR_UNIT,
    "мл/хв/1.73м2": _EGFR_UNIT,
    # Display-only folds: canonical_unit() already rewrites µ to u on both
    # sides, so these compare correctly without help.  Without them the
    # Ukrainian page prints «мкмоль/л» for one creatinine and "umol/L" for the
    # next, which reads as two different measurements.
    "umol/l": _UMOL_L,
    "ug/l": "µg/L",
    "cells/ul": _CELLS_UL,
    # Synevo dipstick: erythrocytes and leukocytes per microlitre are cells
    # per microlitre.  Keyed as casefold() leaves them (µ becomes U+03BC).
    "ery/μl": _CELLS_UL,
    "leu/μl": _CELLS_UL,
    # EskuLab writes the denominator the Synevo panels lost to a neighbouring
    # text object, and spells the numerator out for the absolute differential.
    # A count of 10^9 *cells* per litre is a count of 10^9 per litre, so all
    # three are one measurement; unfolded, «10^9/л» would give the leukocyte
    # count a second unit and split its trend away from the «10^9» readings
    # already in the record.
    "10^9/л": _GIGA_PER_L,
    "10^12/л": _TERA_PER_L,
    "10^9клітин/л": _GIGA_PER_L,
    "10^9 клітин/л": _GIGA_PER_L,
    # Synevo prints the red count's unit as «10^12» over «клітин/л»; read
    # whole, it must fold where «10^12» does or the RBC trend splits in two.
    "10^12клітин/л": _TERA_PER_L,
    "10^12 клітин/л": _TERA_PER_L,
    # Coagulation times print the bare Cyrillic letter where other reports
    # print «сек»; both are seconds. Cyrillic «с» casefolds to itself, so this
    # cannot collide with a Latin "c".
    "с": "s",
    # The trailing full stop is the lab's, not a new unit -- as for «мм/год.»
    # above. Left unfolded, «Од.» and «Од» are two units for one quantity.
    "од.": "units",
    # Expert Hospital labels urine specific gravity «Питома вага, г/мл 1,035».
    # The figure is the relative density every other laboratory here prints
    # without a unit (EskuLab 1.032, St. Paraskeva 1.005), and the reference
    # library files the analyte unitless; folded to "" so the three stay one
    # series instead of the Expert reading starting a second, g/mL one.
    "г/мл": "",
    # The same units with a plain digit for the exponent, a Latin "m" in a
    # Cyrillic word («сm3» on the thyroid report), a dot for the comma, or a
    # space before m².  One spelling each -- the library's (mL, mL/min/1.73m²)
    # -- so a stored value and its band meet in the same unit.
    "cm³": "mL",
    "мл/хв/1.73 м²": _EGFR_UNIT,
    "ml/min/1.73m2": _EGFR_UNIT,
    "ml/min/1.73 m2": _EGFR_UNIT,
    "ml/min/1.73 m²": _EGFR_UNIT,
    # Vital signs and ECG intervals as Veselka's visit notes print them
    # («Температура: 36,6 ° C»; «36,6 ˚С мм.рт.ст 62 уд/в» with a ring above
    # U+02DA and a Cyrillic «С»; «АТ: права рука 120/80 мм.рт.ст.»; «140 мсек»).
    # Each is exactly the unit it folds to; unfolded, the ring-above form even
    # NFKC-decomposes into a combining mark that matches nothing.
    "° c": "°C",
    "˚с": "°C",
    "уд/в": "bpm",
    "мм.рт.ст.": "mmHg",
    "мм.рт.ст": "mmHg",
    "мсек": "ms",
    # Colonies per millilitre: a urine culture's count, where a stool culture
    # counts per gram («КУО/г», CFU/g above).  Not the same quantity, so not
    # folded together; this only gives the per-millilitre spelling its name.
    "куо/мл": "CFU/mL",
    # EskuLab's partner coprogram heads its unit column «кількість в п/з»: a
    # count per field of view, the same unit as «в п/з».
    "кількість в п/з": "per HPF",
}

#: Same number, different label -- registered per concept and never globally.
#:
#: Two situations produce these.  A dimensionless quantity gets a different
#: name from each laboratory: Synevo prints the atherogenic ratio as «Од» and
#: the mumps antibody indices as "AI" and "R", where Expert Hospital prints
#: «коефіцієнт» and the library stores "index".  And a laboratory simply
#: mislabels its own column: Expert Hospital heads plateletcrit «х 10*9/л» and
#: INR «%», then prints values (0.22-0.36 against a 0.1-0.5 interval, 0.87
#: against 0.77-1.24) that are unambiguously the percentage and the ratio.
#:
#: Scoping each to one concept is what makes this safe.  Folding «Од» into
#: «коефіцієнт» globally would be wrong -- «Од» is "units" on an antibody
#: titre, a real quantity -- but for the atherogenic ratio specifically the two
#: spellings are the same dimensionless number.  Keys are ``canonical_unit``
#: forms.  Urobilinogen is deliberately absent: µmol/L and mg/dL are a molar
#: conversion (×16.9, in ``reference.UNIT_CONVERSIONS``), not a relabel.
CONCEPT_UNIT_ALIASES: dict[tuple[str, str], str] = {
    ("atherogenic-coefficient", "units"): "ratio",
    ("inr", "%"): "ratio",
    ("plateletcrit", "10^9/l"): "%",
    ("mumps-virus-igg", "ai"): "index",
    ("mumps-virus-igm", "r"): "index",
    # A visit note prints breathing rate «18 /хв» inline and «16 хв» under its
    # «ЧД» column: per minute, and minutes, by the letter.  Under the
    # respiratory-rate concept both are breaths per minute; anywhere else «хв»
    # stays minutes, which is why this is scoped here and not a synonym.
    ("resting-respiratory-rate", "/хв"): _BREATHS_PER_MIN,
    ("resting-respiratory-rate", "min"): _BREATHS_PER_MIN,
    # Insulin «мкОд/мл» (µU/mL) and «мкМО/мл» (µIU/mL, folded to mIU/L): by
    # prefix arithmetic 1 µU/mL = 1 mU/L, and on an insulin immunoassay the
    # "unit" is the international unit of the WHO insulin reference
    # preparation the method is calibrated to, so the two labels carry the
    # same number.  Not folded globally: elsewhere "U" is an enzyme or an
    # arbitrary assay unit and is no international unit at all.
    ("insulin", "uu/ml"): "miu/l",
}

# Merged only after the reverse map is built, deliberately.  Folding has to
# happen on the way in, but the Ukrainian rendering of "mIU/L" must stay
# «ммо/л» rather than whichever synonym was added last.
UNIT_TRANSLATIONS.update(UNIT_SYNONYMS)


def localized_health_areas() -> list[dict[str, object]]:
    areas = []
    for area in HEALTH_AREAS:
        areas.append(
            {
                **area,
                "name": translate_phrase(str(area["name"])),
                "short": translate_phrase(str(area["short"])),
                "description": translate_phrase(str(area["description"])),
            }
        )
    return areas


def metric_area_ids(canonical_name: str, category: str, metric_key: str | None = None) -> list[str]:
    """Return a stable primary area followed by clinically related views."""
    primary = CATEGORY_TO_AREA.get(category)
    areas: list[str] = [primary] if primary else []
    related = set(RELATED_CONCEPT_AREAS.get(canonical_name, set()))
    if metric_key:
        related |= DEVICE_RELATED_AREAS.get(metric_key, set())
    for area_id in sorted(related):
        if area_id not in areas:
            areas.append(area_id)
    return areas


def concept_display_name(name: str | None) -> str:
    if not name:
        return ""
    if get_locale() == "uk":
        return CONCEPT_NAMES_UK.get(name, name)
    # Allergen concepts are stored under the Ukrainian name printed on the
    # source report; everything else is already canonically English.
    return CONCEPT_NAMES_EN.get(name, name)


# Underscore-stripping alone produces "radiology mri" and "radiology xray" in
# the English UI. These enums are user-facing on the documents filter and every
# document card, so they need real labels rather than a mechanical transform.
ENUM_LABELS_EN = {
    "radiology_mri": "MRI",
    "radiology_xray": "X-ray",
    "diagnostic_image": "Diagnostic images",
    "electrocardiogram": "ECG",
    "blood_pressure": "Blood pressure",
    "compound_bundle": "Document bundle",
    "native_text": "Native PDF text",
    "native_text_plus_embedded_image_ocr": "Native text plus image OCR",
    "native_text_plus_visual_attachments": "Native text plus attachments",
    "ocr_image_metadata": "OCR and image metadata",
    "lab_api": "Lab’s online record (no PDF)",
    "needs_correction": "Needs correction",
    "human_corrected": "Corrected by a person",
    "not_reviewed": "Not reviewed",
    # Curated-rule context vocabulary (rule.context on metric pages). These are
    # read by patients, so each value must answer "what is this?", not name a
    # storage enum.
    "kind": "Type of guidance",
    "decision_threshold": "Decision threshold: a published action cut-off, not a population interval",
    "reference_interval": "Reference interval: the range expected in a healthy population",
    "treatment_target": "Treatment target: the goal for someone under treatment",
    "requires": "Applies only when",
    "infection_or_inflammation": "Infection or inflammation is present",
    "illness": "An acute illness is present",
}


def enum_label(value: str | None) -> str:
    if not value:
        return ""
    if get_locale() == "uk":
        translated = translate_phrase(value)
        if translated != value:
            return translated
        english = ENUM_LABELS_EN.get(value, value.replace("_", " "))
        return translate_phrase(english, fallback=english)
    return ENUM_LABELS_EN.get(value, value.replace("_", " ").capitalize())


def category_label(category: str | None) -> str:
    english = CATEGORY_LABELS.get(category or "", (category or "Other").replace("_", " ").title())
    return translate_phrase(english)


#: `10^9/L` -> `10⁹/L`. Presentation only: canonical_unit() (reference.py)
#: keeps folding the caret form, so this must never run on a unit before it
#: reaches evaluate()/convert_value() - NFKC would collapse the superscript
#: back to a bare digit and silently stop curated rules from matching.
_SUPERSCRIPT_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_CARET_EXPONENT_RE = re.compile(r"\^(\d+)")


def _superscript_exponents(text: str) -> str:
    return _CARET_EXPONENT_RE.sub(lambda m: m.group(1).translate(_SUPERSCRIPT_DIGITS), text)


def display_unit(unit: str | None) -> str:
    if not unit:
        return ""
    key = unit.casefold().strip()
    if get_locale() == "uk":
        if key in UNIT_SYNONYMS:
            # An alternative spelling resolves to the canonical Ukrainian one.
            # Left as printed, a single analyte shows «фл» on one reading and
            # «F/л» on the next, which reads as two different measurements.
            result = _UNIT_REVERSE.get(UNIT_SYNONYMS[key].casefold(), unit)
        elif key in UNIT_TRANSLATIONS:
            result = unit
        else:
            result = _UNIT_REVERSE.get(key, unit)
    else:
        result = UNIT_TRANSLATIONS.get(key, unit)
    return _superscript_exponents(result)


_BLOOD_GROUP_RE = re.compile(r"^(0|O|О|AB|АВ|AВ|АB|A|А|B|В)\s*\(\s*(IV|ІV|I{1,3}|І{1,3})\s*\)$", re.IGNORECASE)


def _blood_group(text: str) -> str | None:
    """One spelling of an ABO group, whatever script the report printed it in.

    EskuLab prints «А (II)» with Latin numerals, Expert Hospital «А(ІІ)» with
    Cyrillic І -- the same group, rendered as two different values side by
    side.  Numerals are Roman (Latin) in both languages; the letters are
    Cyrillic in Ukrainian («0», «А», «В», «АВ») and Latin in English.
    """
    match = _BLOOD_GROUP_RE.match(text)
    if not match:
        return None
    latin = match.group(1).upper().translate(str.maketrans("АВО0", "ABOO"))
    numeral = match.group(2).upper().replace("І", "I")
    letters = latin.translate(str.maketrans("ABO", "АВ0")) if get_locale() == "uk" else latin
    return f"{letters} ({numeral})"


def display_value(value: str | None) -> str:
    if value is None:
        return t("em.dash")
    clean = collapse_space(value)
    group = _blood_group(clean)
    if group:
        return group
    key = normalized_key(clean)
    if get_locale() == "uk":
        if key in VALUE_TRANSLATIONS:
            return clean
        return _VALUE_REVERSE.get(key, clean)
    translated = VALUE_TRANSLATIONS.get(key)
    if translated:
        return translated
    # Microscopy results are a count plus a Ukrainian qualifier ("1-2 в п/з"),
    # so a whole-string lookup can never cover them. Reuse the reference
    # fragment table rather than maintaining a second one.
    return translate_reference_fragments(clean)


_SEX_TOKENS = {
    # «(ч)» and «(ж)» are EskuLab's short forms, printed beside the long ones in
    # the same block: «Дорослі жінки: 35-104» sits opposite «Дорослі (ч):
    # 40-129».  Without them the men's alkaline phosphatase band was
    # indistinguishable from the women's, and a block naming both sexes read as
    # naming neither.  Only the parenthesised forms are accepted -- a bare «ч»
    # is a letter in half the words on the page.
    # «чол.» is the abbreviation EskuLab's liver panel prints beside «жін.».
    "male": re.compile(r"чолов|\bчол\b|\(\s*ч\s*\)|\bmale\b|\bmen\b", re.I),
    "female": re.compile(r"жін|\(\s*ж\s*\)|\bfemale\b|\bwomen\b|вагіт|pregnan|триместр", re.I),
}
_CHILD_RE = re.compile(r"новонарод|дитин|діт|немовл|newborn|child|infant|p(a)?ediatric", re.I)
_ADULT_RE = re.compile(r"дорослі|дорослих|\badults?\b", re.I)
#: Ages, in every unit and spelling these reports write them in, and how many
#: years one of those units is.
#:
#: «р» abbreviated to a single letter is EskuLab's house style for the blood
#: count and the ESR («Чоловіки 17 - 50р», «1-12р.», «Діти до 17р»), and until
#: it was read as a year the two men's ESR bands both applied to a 34-year-old
#: at once -- the 17-50 limit of 15 mm/h and the over-50 limit of 20, with
#: nothing to choose between them.  «старші 50р» is the same statement as «від
#: 50 років».
#:
#: The days and months are the first year, which these blocks split several ways
#: («Діти 0-5 днів», «5 днів - 6 місяців», «6-12 місяців», «2тиж.-1міс.»).  With
#: no unit spelled, a window matched nothing and the band fell through to the
#: generic «Діти» rule -- every patient under eighteen -- so a seven-year-old's
#: AST was judged against the newborn <97 U/L with «6-12 років: <47.0» printed
#: in the same block, and a two-year-old's ALT against <49.0 rather than <33.0.
#:
#: Order matters: «рок…» is tried before the single-letter «р», «тижн…» before
#: «тиж.».
_AGE_UNITS: tuple[tuple[str, float], ...] = (
    (r"рок\w*|рік|year\w*|р\b|р[.:]", 1.0),
    (r"місяц\w*|міс\b|міс[.:]|month\w*", 1 / 12),
    (r"тижн\w*|тиж\b|тиж[.:]|week\w*", 7 / 365.25),
    (r"дн(?:ів|я|і)|день|day\w*", 1 / 365.25),
)
#: Years only.  `_POPULATION_RE` uses this rather than the full set on purpose:
#: it decides what counts as a *label* naming a population, and every band that
#: is written in days or months already names one another way -- «Діти», «5 днів
#: - 6 місяців» -- so widening it there would only start claiming fragments.
_YEAR_UNIT = f"(?:{_AGE_UNITS[0][0]})"
_AGE_UNIT = "(?:" + "|".join(pattern for pattern, _ in _AGE_UNITS) + ")"
_AGE_UNIT_SCALES = tuple(
    (re.compile(rf"^(?:{pattern})", re.I), years) for pattern, years in _AGE_UNITS
)
#: Both ends carry a unit when the band crosses one: «5 днів - 6 місяців»,
#: «Діти 15 днів-1 рік», «2тиж.-1міс.».  The opening unit is optional because
#: the commoner form states it once, at the end: «6-12 років».
_AGE_WINDOW_RE = re.compile(
    rf"\(?\s*(?P<low>\d{{1,3}})\s*(?P<low_unit>{_AGE_UNIT})?\s*[-–—]\s*"
    rf"(?P<high>\d{{1,3}})\s*(?P<high_unit>{_AGE_UNIT})",
    re.I,
)
_AGE_FROM_RE = re.compile(
    rf"(?:від|from|>|≥|старш\w*)\s*(?P<age>\d{{1,3}})\s*(?P<unit>{_AGE_UNIT})", re.I
)
_AGE_TO_RE = re.compile(rf"(?:до|under|<|≤)\s*(?P<age>\d{{1,3}})\s*(?P<unit>{_AGE_UNIT})", re.I)
_HAS_NUMBER_RE = re.compile(r"\d")


def _unit_years(unit: str | None) -> float:
    """How many years the printed unit is worth."""
    for pattern, years in _AGE_UNIT_SCALES:
        if unit and pattern.match(unit.strip()):
            return years
    return 1.0


def _window_years(match: re.Match[str]) -> tuple[float, float]:
    """An age window's two ends, both in years."""
    high_unit = match.group("high_unit")
    low = int(match.group("low")) * _unit_years(match.group("low_unit") or high_unit)
    return low, int(match.group("high")) * _unit_years(high_unit)


def _bound_years(match: re.Match[str]) -> float:
    """A one-sided age bound, in years."""
    return int(match.group("age")) * _unit_years(match.group("unit"))


def _unresolvable(age_years: int, *bounds: float) -> bool:
    """Does one of these boundaries fall inside the patient's own year?

    The only age this module is given is a whole number of years, and the first
    year is where these blocks do all their splitting: a patient recorded as 0
    is anything from a day old to eleven months.  Reading the units without
    saying so would have handed «Діти до 5 днів: <185.0» to every one of them --
    five times the limit the same block prints for the 6-12-month row.  Where a
    whole year cannot settle which side of a boundary the patient is on, no band
    is the honest answer.  Year bands are unaffected: their boundaries are whole
    numbers and never land strictly inside anybody's year.
    """
    return any(age_years < bound < age_years + 1 for bound in bounds)


#: One labelled band out of a block written for every population at once.  The
#: label is whatever precedes the colon since the previous band ended; the
#: interval is the first number or number pair after it.
#: The unit, where the lab printed one, is written hard against the last digit --
#: «Чоловіки 17 - 50р: < 15мм/год» -- and dropping it published the ESR band as
#: a bare "< 15" with nothing saying millimetres per hour.  Only an attached
#: letter run counts, so the space before the next band's «Чоловіки» keeps that
#: label out; the run may cross a solidus, because the same block also prints
#: «<20мм/ год» with the extractor's space inside the unit.
#: The upper bound may be written as a word, «жін.: до 33», «Дорослі: до 21»:
#: read only as a comparator, the liver panel's adult rows had no interval and
#: ALT, AST and bilirubin went unjudged for every adult.  The colon may carry a
#: stray point, «Жінки старші 50р. :. <30мм/год».
_BAND_RE = re.compile(
    r"(?P<label>[^:]*):[\s.]*"
    r"(?P<interval>(?:до\s*|[<>≤≥]\s*)?-?\d+(?:[.,]\d+)?(?:\s*[-–—]\s*-?\d+(?:[.,]\d+)?)?)"
    r"(?P<unit>[^\W\d_]+(?:\s*/\s*[^\W\d_]+)*)?"
)

#: A band named after a condition, a risk tier or a treatment target is not the
#: healthy interval, however cleanly it parses and however well its label fits
#: the patient.  «Гестаційний діабет: 5.1 - 6.9» stands in the same list as
#: «Дорослі: 4.11 - 5.89», names neither age nor sex, and nothing else in this
#: module would refuse it -- so a man's fasting glucose would have been judged
#: against the diagnostic threshold for gestational diabetes.
#: Pregnancy is in here rather than among the sexes.  `_SEX_TOKENS` reads
#: «Вагітні» as female so that a pregnancy-qualified reference is never shown to
#: a man, which is right for a whole reference and wrong for one band of many:
#: it handed «Вагітні: < 5.1» to every woman as her fasting glucose range, with
#: «Дорослі: 4.11 - 5.89» printed two bands away.  Nothing here records whether
#: a patient is pregnant, so the band belongs to nobody.
_CONDITION_BAND_RE = re.compile(
    r"діабет|дефіцит|недостатн|інтоксикац|ризик|терапевтичн|цільов|подагр|"
    r"лікуванн|отруєнн|вагіт|гестаційн|триместр|"
    r"diabet|deficien|toxic|risk|target|therap|treatment|gout|pregnan|trimester",
    re.I,
)

#: The first days of life, whose intervals are unlike every other age group's --
#: a newborn's total bilirubin threshold is 137 µmol/L against 21 for everyone
#: past one month.  `_CHILD_RE` covers it, but "a child" spans eighteen years
#: and a seven-year-old was being given the newborn band on the strength of it.
_NEWBORN_RE = re.compile(r"новонарод|newborn|neonat", re.I)

#: An age wearing an interval's clothes.  «Діти (ч): 0-14 днів: 83-248» offers
#: `0-14` to the first thing that reads it, and a heading that carries no
#: interval of its own will take the next band's numbers otherwise.  What
#: settles it is what follows: a unit of time straight after the numbers is
#: theirs, but a *new* number before that unit is the next band's label
#: beginning -- «Діти 0-5 днів: <49.0 5 днів - 6 місяців: <56.0» has a real
#: interval followed by a real age, and dropping it took the only paediatric
#: band ALT had.
#: The single-letter «р.» is an age too: «Жінки: 18-25 р.: 0.96-13.34» (AMH)
#: offered «18-25» as the women's interval, once per age row.
_TIME_UNIT = r"(?:днів|день|дня|тижн|тиж\b|міс\b|місяц|рок|рік|роки|р\b|год\.)"
#: A comparator opens the next band's label only after a blank: «38-153
#: ≥18 років: 42-156» is a 2-17-year band followed by the adults' label, and
#: reading «≥18 років» as the tail of an age took the amino acids' 2-17 band
#: away and left the adult one unpaired -- none of 39 amino acids got a range.
#: A dash still continues the age («0 - <1 року»), and so does a comparator
#: written hard against the number.
_AGE_NOT_INTERVAL_RE = re.compile(
    rf"^(?:\s*{_TIME_UNIT}|\s*[-–—]+\s*[<>≤≥]?\s*\d{{1,3}}\s*{_TIME_UNIT}|[<>≤≥]+\s*\d{{1,3}}\s*{_TIME_UNIT})",
    re.I,
)

#: Every way a band names the population it belongs to.  Wider than
#: `DEMOGRAPHIC_REFERENCE_RE`, which deliberately omits «дорослі» -- an adult
#: interval standing alone is not a qualified one, and gating `reference_bounds`
#: on it would throw away most of the record.  Inside a list of bands the word
#: is doing the opposite job: it is what distinguishes «Дорослі: <21» from the
#: three newborn thresholds printed above it.
_POPULATION_RE = re.compile(
    "|".join(
        (
            DEMOGRAPHIC_REFERENCE_RE.pattern,
            _ADULT_RE.pattern,
            r"\(\s*[чж]\s*\)",
            r"\d{1,3}\s*[-–—]\s*\d{1,3}\s*" + _YEAR_UNIT,
            # «≥18 років» names its population by the bound: started at the
            # word, the qualifier kept only «років» and lost the age.
            r"[<>≤≥]\s*\d{1,3}\s*" + _YEAR_UNIT,
            # The same bound in words, «старше 12 років: <25», «до 40 р.: <60,5»:
            # without it the qualifier began at «років», lost its number, and
            # named nobody, so gliadin IgG and HE4 had no band for an adult.
            r"(?:від|до|старш\w*)\s*\d{1,3}\s*" + _YEAR_UNIT,
        )
    ),
    re.I,
)


#: Guards a pattern that opens with a blank run against being retried at every
#: position inside that run, which is quadratic on a long one.  A match may
#: start only where the previous character is not blank or the current one is
#: not -- which are exactly the places the unguarded pattern can find its
#: leftmost match: anywhere further into a run, the run's own start matched
#: first, and a scan resuming after a previous match never lands mid-run,
#: because each guarded pattern ends on a greedy blank run or a non-blank.
_RUN_START = r"(?:(?<!\s)|(?!\s))"

#: «мм / год» printed as «мм/год»: the blanks either side of a slash.
_SLASH_SPACING_RE = re.compile(_RUN_START + r"\s*/\s*")


def reference_applies(
    reference: str | None, age_years: int | None = None, sex: str | None = None
) -> bool:
    """Does a demographically-qualified printed range describe this patient?

    Conservative: an interval whose population cannot be confirmed to include
    the patient is treated as not applying.  Showing a child's range to an
    adult as "your range" is a clinical-safety defect, not a formatting one.
    """
    if not demographic_reference(reference):
        return True
    return _population_applies(reference or "", age_years, sex)


def _population_applies(
    reference: str, age_years: int | None = None, sex: str | None = None
) -> bool:
    """The same question, for text already known to name a population.

    Split out because `applicable_band` has established that much before it
    asks, and the short-circuit above would answer True for «Дорослі (ч)» --
    which matches nothing in `DEMOGRAPHIC_REFERENCE_RE` and would have offered a
    woman the men's alkaline phosphatase band.
    """
    text = collapse_space(reference).replace(",", ".")
    if _NEWBORN_RE.search(text) and (age_years is None or age_years >= 1):
        return False
    if _names_other_sex(text, sex):
        return False
    if age_years is None:
        return False
    if _CHILD_RE.search(text) and age_years >= 18:
        return False
    named_age = _named_age_applies(text, age_years)
    if named_age is not None:
        return named_age
    if _ADULT_RE.search(text):
        return age_years >= 18
    if _CHILD_RE.search(text):
        return age_years < 18
    # Sex-qualified only, and the sex matched -- which makes it the adult row.
    # These reports print the children by age and the grown-ups by sex, so a
    # bare «Чоловіки» carries no age because none was needed: everybody it
    # describes is over eighteen.  Given to a boy it is simply another
    # population's interval -- «Чоловіки: 202.3-416.5» went to a seven-year-old
    # whose uric acid runs about a third lower.  The refusal belongs here rather
    # than in `applicable_band`, because `applicable_reference_bounds` reaches
    # the same row a second way, through `_sex_clause`, and fixing only the band
    # selector left that path handing the same number to the same child.
    return age_years >= 18 and any(
        pattern.search(text) for pattern in _SEX_TOKENS.values()
    )


def _names_other_sex(text: str, sex: str | None) -> bool:
    """The reference is written for a sex, and not for this patient's."""
    patient_sex = (sex or "").strip().casefold() or None
    printed_sexes = {
        token_sex for token_sex, pattern in _SEX_TOKENS.items() if pattern.search(text)
    }
    # A reference naming both sexes is a two-row table, not a restriction:
    # "жінки < 28.0 чоловіки < 11.2" applies to this patient as long as he is
    # one of them, and _sex_clause() below picks his half.  Refusing it because
    # the other sex is also mentioned discarded the only limit he had.
    return bool(printed_sexes) and patient_sex not in printed_sexes


def _outside_window(window: re.Match[str], age_years: int) -> bool:
    low, high = _window_years(window)
    return not (low <= age_years <= high) or _unresolvable(age_years, low, high)


def _named_age_applies(text: str, age_years: int) -> bool | None:
    """Whether the age window or age bound a reference names includes the
    patient; ``None`` when it names none."""
    window = _AGE_WINDOW_RE.search(text)
    if window and _outside_window(window, age_years):
        return False
    lower = _AGE_FROM_RE.search(text)
    if lower:
        bound = _bound_years(lower)
        if age_years < bound or _unresolvable(age_years, bound):
            return False
    upper = _AGE_TO_RE.search(text)
    if upper:
        bound = _bound_years(upper)
        if age_years >= bound or _unresolvable(age_years, bound):
            return False
    if window or lower or upper:
        return True
    return None


def _sex_clause(text: str, sex: str | None) -> str | None:
    """The half of a per-sex reference that belongs to this patient.

    Returns ``None`` when the reference is not a per-sex table, so the caller
    goes on treating it as one interval.  A patient of unknown sex gets nothing
    rather than the first clause printed -- a coin toss between two intervals
    is worse than no interval at all.
    """
    marks = sorted(
        (match.start(), token_sex)
        for token_sex, pattern in _SEX_TOKENS.items()
        for match in pattern.finditer(text)
    )
    if len({token_sex for _, token_sex in marks}) < 2 or not sex:
        return None
    for index, (start, token_sex) in enumerate(marks):
        if token_sex != sex:
            continue
        end = marks[index + 1][0] if index + 1 < len(marks) else len(text)
        clause = text[start:end]
        # «Чоловіки/Жінки: 28-100» names both sexes to say the interval is the
        # same for each -- it is one range, not a table with a row apiece.
        # Split at the second name it yields «Чоловіки/», and the only numbers
        # on the line are orphaned in the other half: amylase 63.8 U/L was
        # shown with no interval while 28-100 was printed beside it.  A clause
        # carrying no number is not this patient's clause; the reference is not
        # a per-sex table and the caller should read it whole.
        return clause if _HAS_NUMBER_RE.search(clause) else None
    return None


def _band_specificity(label: str, sex: str | None) -> tuple[int, int]:
    """How closely a band's label describes one person rather than a population.

    Named sex outranks a named age window, which outranks the bare word
    "adults", because that is the order in which the reports themselves narrow:
    a block carrying both «Дорослі жінки» and «Дорослі (ч)» means the sex is the
    discriminator and "adult" is common ground.  The second element breaks ties
    towards the longer label, which is the more qualified one.
    """
    score = 0
    if sex and _SEX_TOKENS[sex].search(label):
        score += 4
    # An open lower age bound short of adulthood is no narrower than "adults":
    # «старші 1 року: 60,0-80,0» is the children's tail of total protein's
    # block, and outranking «Дорослі 66,0-87,0» it gave every adult the
    # paediatric interval.
    lower = _AGE_FROM_RE.search(label)
    if _AGE_WINDOW_RE.search(label) or _AGE_TO_RE.search(label) or (lower and _bound_years(lower) >= 18):
        score += 2
    if _ADULT_RE.search(label):
        score += 1
    return score, len(label)


#: «Дорослі 66,0-87,0 1 день - 4 тижні: 46,0-68,0»: the adults' row printed with
#: no colon, so its interval read as the start of the next band's label.  A
#: colon is put back only before an interval, never before an age window
#: («Дорослі 20-65 років: ...»).
_UNCOLONED_ADULT_RE = re.compile(
    r"(?:дорослі|дорослих|\badults?\b)"
    rf"(?=\s+\d++(?:[.,]\d++)?\s*[-–—]\s*\d++(?:[.,]\d++)?(?![\d.,])(?!\s*{_AGE_UNIT}))",
    re.I,
)


#: A population heading with its age bands under it, «Жінки: 31-35 р.: 0.07-7.35»
#: (AMH), «Діти: <1 року: 3.0 - 5.4».  The heading's own colon made the age
#: window read as the interval and the band's label begin at «р.», so no woman
#: had an AMH band.  The colon before an age qualifier that ends in a colon of
#: its own is dropped, and the heading becomes part of the label.
_NESTED_AGE_LABEL_RE = re.compile(
    rf":(?=\s*(?:[<>≤≥]\s*)?\d{{1,3}}(?:\s*[-–—]\s*\d{{1,3}})?\s*{_AGE_UNIT}\s*:)", re.I
)


def _reading(value: float, interval: str) -> str | None:
    """Which side of one printed interval a value falls on; ``None`` when it has no bounds."""
    limits = reference_limits(interval)
    if limits.low is None and limits.high is None:
        return None
    if limits.high is not None and (value > limits.high or (value == limits.high and not limits.high_inclusive)):
        return "high"
    if limits.low is not None and (value < limits.low or (value == limits.low and not limits.low_inclusive)):
        return "low"
    return "within"


def applicable_band(
    reference: str | None,
    age_years: int | None = None,
    sex: str | None = None,
    value: float | None = None,
) -> str | None:
    """The one band of a multi-population reference block that describes this patient.

    EskuLab prints a whole paediatric table beside the adult one -- ten bands for
    γ-GT, thirteen for alkaline phosphatase -- and the two men's rows sit inside
    it rather than above it.  Judged as a single string the block is
    unmistakably about children, so `reference_applies` refused all of it and a
    34-year-old man was told his γ-GT, ALT, AST, creatinine, calcium and ESR had
    no reference range that applied to him.  Every one of those was printed on
    the page he was looking at.

    So the block is taken apart instead.  Each «label: interval» pair is
    weighed on its own, the ones describing somebody else are dropped, and the
    most specific survivor is returned as ``"label: interval"``.  Returns
    ``None`` for a block that is not a list of labelled bands, and for one whose
    every band belongs to another population -- refusing remains the answer when
    nothing fits, and it must not become a guess.

    ``value``, when the caller has one, settles a tie between equally specific
    bands that every one of them reads the same way: a 50-year-old woman's ESR
    of 6 is inside both «Жінки 17-50р: <20» and «Жінки старші 50р: <30», and
    refusing there left a normal result unjudged.  Where they disagree it is
    still refused.
    """
    if not reference:
        return None
    text = _NESTED_AGE_LABEL_RE.sub("", _UNCOLONED_ADULT_RE.sub(r"\g<0>:", collapse_space(reference)))
    bands = [
        (
            collapse_space(found.group("label")),
            collapse_space(found.group("interval"))
            + _SLASH_SPACING_RE.sub("/", found.group("unit") or ""),
        )
        for found in _BAND_RE.finditer(text)
        if not _AGE_NOT_INTERVAL_RE.match(text[found.end("interval") :])
    ]
    if len(bands) < 2:
        return None
    ranked: list[tuple[tuple[int, int], str, str]] = []
    for label, interval in bands:
        # A label is only a qualifier if it names a population.  Unlabelled
        # numbers and stray fragments of the row above are neither, and a block
        # of them is not the shape this function exists to read.
        start = _POPULATION_RE.search(label)
        if start is None:
            continue
        # The label also carries whatever trailed the previous band -- the units
        # of its interval, most often, since «<10мм/год» leaves «мм/год» behind.
        # The qualifier is what remains from the first population word on.
        qualifier = label[start.start():]
        if _CONDITION_BAND_RE.search(qualifier) or NON_NORMAL_BAND_RE.search(qualifier):
            continue
        if not _population_applies(qualifier, age_years, sex):
            continue
        # A bare «Чоловіки» is the adult men's row and reaches no child;
        # `_population_applies` has already refused it, above, for every path
        # into this module rather than only for this one.
        ranked.append((_band_specificity(qualifier, sex), qualifier, interval))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    # Two bands equally entitled to the same patient are not a choice to make on
    # his behalf: an unresolved reference is recoverable and a wrong one is not.
    # Unless every one of them reads this value the same way.  One label with
    # several intervals is a misread block, never a tie («Жінки: 18-25 р.:
    # 0.96-13.34 Жінки: 26-30 р.: ...» offering its age windows), and agreement
    # between misreadings proves nothing.
    tied = [(item[1], item[2]) for item in ranked if item[0][0] == ranked[0][0][0]]
    intervals = {interval for _, interval in tied}
    if len(intervals) > 1 and (
        value is None
        or len({label for label, _ in tied}) < len(tied)
        or None in (readings := {_reading(value, interval) for interval in intervals})
        or len(readings) > 1
    ):
        return None
    _, qualifier, interval = ranked[0]
    return f"{qualifier}: {interval}"


#: A risk index printed as one cut-off with a reading on either side of it,
#: ROMA's «≥7.4% - високий ризик ... <7.4% - низький ризик».  Not a tier of a
#: graded scale, which stays refused: there are two readings, the low-risk one
#: is the expected result, and the cut-off is exactly where the laboratory's
#: own reading changes.  Refused with the graded scales, a premenopausal ROMA
#: of 10.2 % was shown unjudged under a threshold the report prints.
_LOW_RISK_CUTOFF_RE = re.compile(r"<\s*(\d+(?:[.,]\d+)?)\s*%?\s*[-–—:]?\s*низьк\w*\s+ризик", re.I)
_HIGH_RISK_CUTOFF_RE = re.compile(r"(?:≥|>)\s*(\d+(?:[.,]\d+)?)\s*%?\s*[-–—:]?\s*висок\w*\s+ризик", re.I)


def _risk_cutoff(text: str) -> float | None:
    """The cut-off of a two-reading risk index, as the low-risk side's exclusive upper bound."""
    low_risk = _LOW_RISK_CUTOFF_RE.findall(text)
    high_risk = _HIGH_RISK_CUTOFF_RE.findall(text)
    if len(low_risk) != 1 or len(high_risk) != 1 or low_risk[0].replace(",", ".") != high_risk[0].replace(",", "."):
        return None
    return float(low_risk[0].replace(",", "."))


def applicable_reference_bounds(
    reference: str | None,
    age_years: int | None = None,
    sex: str | None = None,
    value: float | None = None,
) -> tuple[float | None, float | None]:
    """Numeric bounds from a printed reference, only when they fit the patient.

    ``reference_bounds`` discards every demographically-qualified interval,
    which throws away applicable adult ranges along with the paediatric ones.
    Here the qualifier is parsed instead: an adult range is used for an adult,
    a child's range is still refused, and an unparseable qualifier is refused
    rather than guessed at.
    """
    if not reference:
        return None, None
    clean = collapse_space(reference)
    # A block listing several populations is read band by band before anything
    # else is tried: the tests below judge the block as one string, and one
    # string that mentions children is refused whole.  Ahead of the
    # demographic test too, because a block can list bands without naming a
    # population `demographic_reference` recognises -- vitamin D's «Ризик
    # дефіциту: < 10.0 Дорослі: 30.0-50.0 Інтоксикація: >150.0» names only
    # adults, and reading it whole left the first number pair to chance.
    band = applicable_band(clean, age_years, sex, value)
    if band is not None:
        return reference_bounds(band.rsplit(":", 1)[-1])
    if not demographic_reference(clean):
        return reference_bounds(clean)
    if not reference_applies(clean, age_years, sex):
        return None, None
    clause = _sex_clause(clean, (sex or "").strip().casefold() or None)
    if clause is not None:
        # The clause has to describe this patient in its own right.  Judged
        # whole, a block carrying paediatric rows passes `reference_applies` for
        # a child -- the age window it finds is one of theirs -- and the clause
        # picked out of it is «Жінки: <35.0», the grown women's row, which is
        # how a seventeen-year-old was given an adult ALT limit.
        if not _population_applies(clause, age_years, sex):
            return None, None
        clean = collapse_space(clause)
    # `applicable_band` refuses a risk tier and returns None -- and this path
    # then re-admitted it, because the line below throws the tier's own label
    # away before `reference_bounds` ever sees it.  HDL prints «Чоловіки: ризик
    # відсутній: >1.45 Чоловіки: помірний ризик: 0.90-1.45», and 1.45 was
    # published as this man's lower bound: a moderate-risk boundary read as the
    # floor of a healthy range, which put his acceptable 1.11 mmol/L below range
    # and downgraded the curated verdict to a lab-versus-guideline conflict.
    cutoff = _risk_cutoff(clean)
    if cutoff is not None:
        return None, cutoff
    if _CONDITION_BAND_RE.search(clean) or NON_NORMAL_BAND_RE.search(clean):
        return None, None
    # The interval is what follows the qualifier: "Дорослі (20-65 років):
    # 3.89 - 26.8".  Taking the first number pair would grab the age window.
    return _fragment_bounds(clean.rsplit(":", 1)[-1] if ":" in clean else clean)


def _fragment_bounds(fragment: str) -> tuple[float | None, float | None]:
    """Bounds of the interval part of a reference already judged to apply."""
    if demographic_reference(fragment):
        # No colon separates the qualifier from its interval -- EskuLab prints
        # "чоловіки < 10" -- so the interval was confirmed to describe this
        # patient on the line above and then thrown away regardless, leaving a
        # urinary erythrocyte count with no bar to be measured against.
        #
        # Only the sex-qualified case is recovered, by dropping the qualifying
        # words.  Anything carrying an age window stays refused: stripping
        # words out of "Чоловіки 20-65 років 3.89 - 26.8" leaves "20-65 3.89 -
        # 26.8", whose first number pair is the age range, not the interval.
        if (
            _AGE_WINDOW_RE.search(fragment)
            or _AGE_FROM_RE.search(fragment)
            or _AGE_TO_RE.search(fragment)
            or _CHILD_RE.search(fragment)
            or _ADULT_RE.search(fragment)
        ):
            return None, None
        remainder = " ".join(
            word for word in fragment.split() if not DEMOGRAPHIC_REFERENCE_RE.search(word)
        )
        return reference_bounds(remainder) if _HAS_NUMBER_RE.search(remainder) else (None, None)
    return reference_bounds(fragment)


_REF_NUMBER = r"(-?\d+(?:[.,]\d+)?)"
_REF_BETWEEN_RE = re.compile(rf"(?:від\s*)?{_REF_NUMBER}\s*(?:до|[-–—])\s*{_REF_NUMBER}", re.I)
_REF_UP_TO_RE = re.compile(rf"(?:до|<|≤)\s*{_REF_NUMBER}", re.I)
_REF_FROM_RE = re.compile(rf"(?:від|>|≥)\s*{_REF_NUMBER}", re.I)
#: «Новонароджені діти (3 день життя): 1,5 - 2,5», read as a prefix and then
#: its interval: one pattern for both exceeded the regex complexity budget.
#: The prefix ends in a greedy blank run and the interval opens with a digit
#: or a minus, so splitting there matches exactly what the single pattern did.
_REF_NEWBORN_RE = re.compile(r"Новонароджені\s+діти\s*\((\d+)\s+день\s+життя\)\s*:\s*", re.I)
_REF_RANGE_RE = re.compile(rf"{_REF_NUMBER}\s*[-–—]\s*{_REF_NUMBER}")


def _single_interval_text(clean: str) -> str | None:
    """A bare single-interval reference in the display form; ``None`` for any other."""
    between = _REF_BETWEEN_RE.fullmatch(clean)
    if between:
        return f"{between.group(1).replace(',', '.')}-{between.group(2).replace(',', '.')}"
    upper = _REF_UP_TO_RE.fullmatch(clean)
    if upper:
        return f"≤ {upper.group(1).replace(',', '.')}"
    lower = _REF_FROM_RE.fullmatch(clean)
    if lower:
        return f"≥ {lower.group(1).replace(',', '.')}"
    newborn = _REF_NEWBORN_RE.match(clean)
    interval = _REF_RANGE_RE.fullmatch(clean, newborn.end()) if newborn else None
    if interval:
        return t(
            "ref.newborns",
            day=newborn.group(1),
            low=interval.group(1).replace(",", "."),
            high=interval.group(2).replace(",", "."),
        )
    return None


def display_reference(
    reference: str | None,
    age_years: int | None = None,
    sex: str | None = None,
    value: float | None = None,
) -> str:
    if not reference:
        return t("ref.not_supplied")
    # «7. 0 - 7.5» as the text layer gave it is 7.0, which is what the verdict used.
    printed = SPLIT_DECIMAL_RE.sub(r"\1.\2", collapse_space(reference))
    clean, refusal = _reference_for_reader(printed, age_years, sex, value)
    if refusal is not None:
        return refusal
    return _localized_reference(clean)


def _reference_for_reader(
    clean: str, age_years: int | None, sex: str | None, value: float | None = None
) -> tuple[str, str | None]:
    """The reference text to show this reader, or the message shown instead."""
    # The band that describes this reader, labelled, so «8.0-61.0» arrives as
    # "men: 8.0-61.0" and not as a bare pair of numbers whose population they
    # have to take on trust.
    band = applicable_band(clean, age_years, sex, value)
    if band is not None:
        return band, None
    if not demographic_reference(clean):
        return clean, None
    fragment = clean.rsplit(":", 1)[-1] if ":" in clean else clean
    if not _HAS_NUMBER_RE.search(fragment):
        # A bare population label such as "Дорослі (від 18 років):" - the
        # extractor truncated before the numbers.  There is no range here.
        return clean, t("ref.not_supplied")
    if not reference_applies(clean, age_years, sex):
        return clean, t("ref.not_applicable")
    return clean, None


def _localized_reference(clean: str) -> str:
    key = normalized_key(clean)
    if get_locale() == "uk":
        if key in VALUE_TRANSLATIONS:
            return clean
        interval = _single_interval_text(clean)
        return clean if interval is None else interval
    translated_value = VALUE_TRANSLATIONS.get(key)
    if translated_value:
        return translated_value
    interval = _single_interval_text(clean)
    if interval is not None:
        return interval
    # Separators are localized too.  The single-interval forms above already
    # convert the Ukrainian decimal comma; a labelled band skips all of them,
    # so «adults 18-60 years: 2,15-2,5» was reaching the English page verbatim.
    # Only a comma standing between two digits is a decimal point -- the ones
    # separating words are the lab's own punctuation and stay as printed.
    return re.sub(r"(?<=\d),(?=\d)", ".", translate_reference_fragments(clean))


# Laboratory reference texts are free-form: a number, then the lab's own prose.
# The whole-string patterns above only catch the bare numeric forms, so anything
# compound ("<2.59 - оптимальний рівень") reached the English UI in Ukrainian.
# Translating fragment by fragment covers the long tail without pretending we
# can parse arbitrary lab prose. Longest keys first so a short key cannot eat a
# longer phrase it is contained in.
REFERENCE_FRAGMENTS_EN: dict[str, str] = {
    "підвищений ризик розвитку гіпербілірубінемії": "increased risk of hyperbilirubinaemia",
    # A PCR report states no interval, only the load at which colonisation
    # starts to matter.  Untranslated it left Cyrillic in the string, and
    # `reference_display` answers Cyrillic-in-English by printing "Not
    # supplied" -- so the only quantitative statement the report made about
    # Ureaplasma read, in English, as though the laboratory had made none.
    # «ГЄ» is genome equivalents; spelled out rather than transliterated to
    # "GE/mL", which would be one more abbreviation for the reader to look up.
    "клінічно значуща кількість": "clinically significant quantity",
    "гє/мл": _GENOME_EQ_ML,
    "ге/мл": _GENOME_EQ_ML,
    "від світло-жовтого до жовтого кольору": "pale yellow to yellow",
    "не виявлені, поодинокі в препараті": "not detected, occasional in specimen",
    "поодинокі в препараті": "occasional in specimen",
    "поодинокий в препараті": "occasional in specimen",
    "солом`яно-жовтий": "straw yellow",
    "солом'яно-жовтий": "straw yellow",
    "новонароджені діти": "newborns",
    "від білірубіну загального": "of total bilirubin",
    "для груп низького ризику": "for low-risk groups",
    "при цукровому діабеті": "in diabetes",
    "низький рівень ризику": "low risk",
    "негативний результат": "negative result",
    "позитивний результат": "positive result",
    "світло-жовтий / солом`яний": "pale yellow / straw",
    "світло-жовтий / солом'яний": "pale yellow / straw",
    "при лікуванні антикоагулянтами непрямої дії": "on oral anticoagulant therapy",
    "згідно з американською асоціацією діабету": "per the American Diabetes Association",
    "близький до оптимального рівня": "near optimal level",
    "помірно підвищений рівень ризику": "moderately raised risk",
    "дуже високий пороговий рівень": "very high threshold",
    "вище оптимального рівня": "above optimal level",
    "високий пороговий рівень": "high threshold",
    "верхній пороговий рівень": "upper threshold",
    "високий рівень ризику": _HIGH_RISK,
    "для груп пацієнтів": "for patient groups",
    "дуже високого ризику": "very high risk",
    "цільовий рівень": "target level",
    "помірного ризику": "moderate risk",
    "низького ризику": "low risk",
    "високого ризику": _HIGH_RISK,
    "рівень ризику": "risk level",
    "оптимальний рівень": "optimal level",
    "відсутність ризику": "no elevated risk",
    "ризик відсутній": "no elevated risk",
    "здорове населення": "healthy population",
    "помірний ризик": "moderate risk",
    "високий ризик": _HIGH_RISK,
    "від загального": "of total",
    # All four genders of the participle, because the dipstick legend agrees
    # with the analyte it belongs to: «не виявлений білок», «не виявлена
    # глюкоза», «не виявлені кетони».  The masculine form was missing, so urine
    # protein and bilirubin printed their reference in Ukrainian on the English
    # page while glucose and ketones beside them printed it in English.
    "не виявлені": _NOT_DETECTED_TEXT,
    "не виявлено": _NOT_DETECTED_TEXT,
    "не виявлена": _NOT_DETECTED_TEXT,
    "не виявлений": _NOT_DETECTED_TEXT,
    "в нормі": "within range",
    "поодиноко": "occasional",
    "невелика к-сть.": "small amount",
    "невелика к-сть": "small amount",
    # What a coprogram states as its expected result.  «неоформлений» contains
    # «оформлений», and they are opposites -- the fragment regex sorts by
    # length so the longer one wins, which is the whole reason it does that.
    "специфічний, без особливостей": "characteristic, unremarkable",
    "незначна або помірна к-сть.": "slight or moderate amount",
    "не виявлено чи поодинокі": "not detected or occasional",
    "напівм'який": "semi-soft",
    "неоформлений": "unformed",
    "оформлений": "formed",
    "коричневий": "brown",
    "передіабет": "prediabetes",
    "предіабет": "prediabetes",
    "дорослі": "adults",
    "чоловіки": "men",
    "жінки": "women",
    # The liver panel's abbreviated sexes, «жін.: до 33 чол.: до 41».
    "жін.": "women",
    "чол.": "men",
    # ROMA's two readings and the populations they are printed for.  «РЯ» is
    # «рак яєчників», ovarian cancer, spelled out rather than abbreviated.
    "жінки репродуктивного віку": "women of reproductive age",
    "жінки в постменопаузі": "postmenopausal women",
    "високий ризик виявлення епітеліального ря": "high risk of epithelial ovarian cancer",
    "низький ризик виявлення епітеліального ря": "low risk of epithelial ovarian cancer",
    "високий ризик виявлення ря": "high risk of ovarian cancer",
    "низький ризик виявлення ря": "low risk of ovarian cancer",
    "низький ризик": "low risk",
    # The coprogram's pH scale, every band named.
    "в нормі нейтральна або слаболужна": "normal, neutral or slightly alkaline",
    "різко кисла": "strongly acidic",
    "кисла": "acidic",
    "різко лужна": "strongly alkaline",
    "лужна": "alkaline",
    # A colony count's norm: «не більше 1.0 x 10^4 КУО», «Не менше 1.0*10^6 КУО/г».
    "не більше": "no more than",
    "не менше": "at least",
    "куо/г": "CFU/g",
    "куо/мл": "CFU/mL",
    "куо": "CFU",
    # «Чоловіки старші 50р» is one of the two men's ESR rows, and the band
    # selector surfaces whichever of them the reader falls in.
    "старші": "over",
    "старше": "over",
    # The singular is EskuLab's own row heading on the absolute eosinophil
    # count: «Чоловік: 0,04-0,54 Жінки: 0,04-0,36».  Missing from here, the
    # band the selector surfaced kept its Cyrillic, `reference_display` answers
    # Cyrillic-under-English with "not supplied", and the English reader was
    # told no range had been printed for a number the app was at that moment
    # judging against 0.04-0.54.  Rendered as the plural: it is the same row of
    # the same table, and "man" beside "women" reads as a different population.
    "чоловік": "men",
    "жінка": "women",
    "діти": "children",
    "індекс": "index",
    "в п/з": "per HPF",
    # Every age unit these paediatric tables are written in.  The band selector
    # surfaces the lab's own label now, so «6-12 місяців: <82.0» and «До 2тиж.:
    # 134-198» reached the English page half-translated.
    "місяців": "months",
    "місяці": "months",
    "місяця": "month",
    "місяць": "month",
    "тижнів": "weeks",
    "тижні": "weeks",
    "тижня": "week",
    "тиж.": "wk",
    "тиж": "wk",
    "днів": "days",
    "дня": "day",
    "дні": "days",
    "день": "day",
    "років": "years",
    "роки": "years",
    "року": "years",
    "рік": "year",
    # EskuLab abbreviates the year to one letter in the blood count and the ESR
    # -- «Чоловіки 17 - 50р», «1-12р.» -- and the band selector surfaces those
    # labels now, so the English page was reading "men 17 - 50р".  The fragment
    # boundaries only match it standing alone, never inside a word.
    "р.": "y",
    # ...  except that «р» standing alone is also the first letter of «р.н.»,
    # "року народження", so a date of birth was reaching the English page as
    # «07.03.1985 y.н.».  A year abbreviation is never followed by another word;
    # this one always is, which is the whole difference (see `_FRAGMENT_SUFFIX`).
    "р": "y",
    "міс.": "mo",
    "міс": "mo",
    # EskuLab's short forms for the sexes, printed beside the long ones in the
    # same block: «Дорослі жінки: 35-104» opposite «Дорослі (ч): 40-129».
    "(ч)": "(m)",
    "(ж)": "(f)",
    "день життя": "day of life",
    "світло-жовтий": "pale yellow",
    "поодинокий": "occasional",
    "поодинокі": "occasional",
    # Blood groups are deliberately absent: "А(ІІ)" is Latin "A(II)" spelled in
    # Cyrillic homoglyphs, and web.app folds those generically. Enumerating the
    # four ABO groups here would be a second, narrower source of truth.
    "негативний": "negative",
    "позитивний": "positive",
    "негативно": "negative",
    "позитивно": "positive",
    "сумнівний": "equivocal",
    "норма": "normal",
    "до": "up to",
    "від": "from",
    # The band now carries the unit the laboratory printed beside it, so the
    # unit needs an English spelling here too: «Чоловіки 17 - 50р: < 15мм/год»
    # reached the English page as "men 17 - 50y: < 15мм/год".
    "мм/год": "mm/h",
    "од/л": "U/L",
    "г/л": "g/L",
    "мкмоль/л": _UMOL_L,
    "ммоль/л": "mmol/L",
}

#: One key needs more than the shared word boundaries.  «р» is the year, and it
#: is also the first letter of «р.н.» -- «07.03.1985 р.н.», "року народження" --
#: which the shared trailing boundary lets through, because what follows the «р»
#: is a full stop and not a letter.  A year abbreviation is never followed by
#: another word, with or without its dot; the birth-year one always is.  This
#: was the only false positive in the 1,034 distinct strings the record holds,
#: and the guard is written to keep it that way rather than to widen.
_FRAGMENT_SUFFIX = {"р": r"(?!\.?[^\W\d_])"}

_FRAGMENT_RE = re.compile(
    # Anchored to word edges, or a short key eats the middle of a longer word:
    # «до» means "up to" on its own and is three letters inside «здорове»,
    # which the English page was rendering as "зup toрове".  The lookarounds
    # reject a match that starts or ends mid-word without requiring the key
    # itself to begin and end with a letter -- several do not.
    r"(?<![^\W\d_])(?:"
    + "|".join(
        re.escape(key) + _FRAGMENT_SUFFIX.get(key, "")
        for key in sorted(REFERENCE_FRAGMENTS_EN, key=len, reverse=True)
    )
    + r")(?![^\W\d_])",
    re.IGNORECASE,
)


def translate_reference_fragments(text: str) -> str:
    """Translate known Ukrainian fragments inside an otherwise numeric reference."""
    return _FRAGMENT_RE.sub(
        lambda match: REFERENCE_FRAGMENTS_EN[match.group(0).casefold()], text
    )


def status_label(status: str | None) -> str:
    english = {
        "within_vendor_range": "Within original range",
        "borderline": "Equivocal in original report",
        "positive": "Positive in original report",
        "high": "Above original range",
        "low": "Below original range",
        "stable": "No concern noted",
        "attention": "Review finding",
        "information": "Information",
        "verified": "Verified",
        "corrected": "Corrected",
        "extracted": "Needs verification",
        # Extraction debris a reviewer set aside.  The row is kept so the
        # decision is auditable and reversible; it is simply no longer counted
        # as a measurement anywhere else in the record.
        "rejected": "Set aside",
    }.get(status or "", "No comparison")
    return translate_phrase(english)


def age_on(date_of_birth: str | None, on_date: str | None = None) -> int | None:
    if not date_of_birth:
        return None
    try:
        born = date.fromisoformat(date_of_birth[:10])
        current = date.fromisoformat(on_date[:10]) if on_date else date.today()
    except ValueError:
        return None
    return current.year - born.year - ((current.month, current.day) < (born.month, born.day))


# --- narrative findings -------------------------------------------------------
#
# An ultrasound, MRI, biopsy or consultation is filed under a body area as one
# finding per report: the report's own labelled conclusion, the study it came
# from, and whether that conclusion names something abnormal.  Everything is
# the source's wording - nothing is summarised or translated by machine - and
# the row stays `extracted` until a person checks it.
#
# What used to go wrong, each fixed below: the first page's letterhead (clinic
# address, phones, the patient's name and date of birth) stored as the
# "conclusion"; a keyword anywhere in the page choosing the area («Сакроілеїт»
# filed a neurology consult under the intestines, a lumbar MRI's «шийного»
# filed it under ENT); every row `information`, a serrated adenoma included;
# Ukrainian text stored as `summary_en`; a re-issued report shown twice.

NARRATIVE_TYPES = {
    "consultation", "diagnostic_image", "pathology", "radiology_mri",
    "radiology_xray", "ultrasound", "electrocardiogram", "clinical_report",
}

#: The study a report is, read from its own header (title, filename and the
#: text above the conclusion).  First match wins, so specific studies come
#: before the generic ones.  (key, English title, areas, clinical types or
#: None for any narrative type, header pattern).
_STUDIES: tuple[tuple[str, str, tuple[str, ...], frozenset[str] | None, re.Pattern[str]], ...] = tuple(
    (key, title, areas, frozenset(types) if types else None, re.compile(pattern, re.I))
    for key, title, areas, types, pattern in (
        ("consult_neurology", "Neurology consultation", ("spine",), {"consultation"}, r"невролог|невропатолог|neurolog"),
        ("consult_orthopaedic", "Orthopedic consultation", ("joints",), {"consultation"}, r"ортопед|травматолог|orthop"),
        ("consult_vaccination", "Family doctor consultation", ("immunity",), {"consultation"}, r"вакцин|бустрікс|boostrix|vaccin"),
        # A specialist's note quotes the scans it reviewed («УЗД ОЧП …»,
        # «дуплекс сонних артерій»): the specialty decides, before any study.
        ("consult_cardiology", "Cardiology consultation", ("heart",), {"consultation"}, r"кардіолог|cardiolog"),
        ("consult_dermatology", "Dermatology consultation", ("skin",), {"consultation"}, r"дерматолог|dermatolog"),
        ("consult_allergy", "Allergy consultation", ("allergy",), {"consultation"}, r"алерголог|allergolog|allergist"),
        ("consult_gastro", "Gastroenterology consultation", ("digestive",), {"consultation"}, r"гастроентеролог|gastroenterolog"),
        ("consult_endocrine", "Endocrinology consultation", ("thyroid",), {"consultation"}, r"ендокринолог|endocrinolog"),
        # A general physician's note has no organ of its own: its diagnosis
        # (or, with none entered, its complaints) decides.
        ("consult_gp", "General practitioner consultation", (), {"consultation"}, r"терапевт|therapist|internist"),
        ("breath_test", "Breath test for small-intestinal bacterial overgrowth", ("digestive",), None,
         r"дихальн\w*\s+(?:\w{1,3}\s+)?тест|дата\s+проведення\s+тесту|gastrolyzer|breath\s+test"),
        ("echo", "Echocardiogram", ("heart",), None, r"дослідження\s+серця|узд\s+серця|ехокардіо|echocardiog"),
        ("carotid_duplex", "Carotid and vertebral artery ultrasound", ("heart",), None, r"сонних|carotid|вертебральних\s+артері"),
        ("thyroid_us", "Thyroid ultrasound", ("thyroid",), None, r"щитоподібн|щитовидн|thyroid"),
        ("gi_us", "Gastrointestinal tract ultrasound", ("digestive",), {"ultrasound"}, r"шлунково\s*-?\s*кишков"),
        ("egd", "Upper GI endoscopy (EGD)", ("digestive",), None, r"гастродуоденоскоп|панендоскоп"),
        ("abdominal_us", "Abdominal ultrasound", ("liver", "kidneys"), None, r"черевної\s+порожнини|abdominal"),
        ("soft_tissue_us", "Soft-tissue ultrasound", ("joints",), None, r"м['’]яких\s+тканин|soft[- ]tissue"),
        ("salivary_us", "Salivary-gland and cervical-node ultrasound", ("ent",), None, r"слинн|salivary"),
        ("intestinal_biopsy", "Intestinal biopsy (histology)", ("digestive",), {"pathology"}, r"кишк|intestin|colon|поліпектом"),
        ("ecg", "ECG recording", ("heart",), None, r"kardia|\bekg\b|\becg\b|\bекг\b|електрокардіо"),
        ("eeg", "Electroencephalogram (EEG)", ("brain",), None, r"\beeg\b|\bеег\b|електроенцефало|electroencephalo"),
        ("chest_xray", "Chest radiograph", ("lungs",), None, r"\bогк\b|органів\s+грудної|грудної\s+клітки|chest"),
        ("spine_tl_mri", "Thoracic and lumbar spine MRI", ("spine",), {"radiology_mri"}, r"грудного\s+та\s+поперекового|thoracic-and-lumbar"),
        ("spine_c_mri", "Cervical spine MRI", ("spine",), {"radiology_mri"}, r"шийного\s+відділу\s+хребта|cervical[- ]spine"),
        ("spine_t_mri", "Thoracic spine MRI", ("spine",), {"radiology_mri"}, r"грудного\s+відділу\s+хребта|thoracic[- ]spine"),
        ("spine_l_mri", "Lumbar spine MRI", ("spine",), {"radiology_mri"}, r"поперекового\s+відділу\s+хребта|lumbar[- ]spine"),
        ("spine_l_xray", "Lumbar spine radiograph", ("spine",), {"radiology_xray"}, r"поперек\w*\s+(?:\([^)]*\)\s+)?відділ|lumbar"),
        ("spine_xray", "Spine radiograph", ("spine",), {"radiology_xray"}, r"хребт|spine"),
        ("knee_mri", "Knee MRI", ("joints",), {"radiology_mri"}, r"колінного|knee"),
        ("elbow_mri", "Elbow MRI", ("joints",), {"radiology_mri"}, r"ліктьового|elbow"),
        ("ent_ct", "ENT CT image set", ("ent",), None, r"\bent\b|\bлор\b|пазух|sinus"),
    )
)

#: A report whose study is not recognised is still filed, by the organ its
#: title or conclusion names (word starts only: «Сакроілеїт» is not «ілеїт»).
_ORGAN_AREAS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (area, re.compile(pattern, re.I))
    for area, pattern in (
        ("heart", r"\bсерц|\bcardi|\bheart"),
        ("liver", r"\bпечін|\bliver|\bгепат|\bпідшлунков|\bpancrea"),
        ("kidneys", r"\bнир[кц]|\bkidney|\brenal|\bсечов"),
        ("digestive", r"\bкиш|\bintestin|\bшлун[ок]|\bstomach|\bілеїт|\bколіт"),
        ("spine", r"\bхреб|\bspin|\blumbar|\bcervical spine"),
        # A lipoma is a soft-tissue lump wherever it sits («ліпоми лівої
        # верхньої кінцівки»); «кінцівк» itself is in every consultation's
        # «набряків нижніх кінцівок немає».
        ("joints", r"\bсуглоб|\bjoint|\bколін|\bknee|\bлікт|\belbow|\bліпом|\blipom"),
        ("thyroid", r"\bщитопод|\bщитовид|\bthyroid"),
        ("lungs", r"\bлеген|\blung|\bchest|\bгрудної кліт"),
        ("ent", r"\bпазух|\bsinus|\bслинн|\bлор\b|\bсіалоаден|\bsialaden"),
        # By the specialty that wrote it: «шкіра» alone is a line of every
        # general examination («Шкіра: чиста»).
        ("skin", r"\bдерматол|\bdermatol"),
        # «головного мозку», never the «спинного мозку» of a spine scan; a
        # headache («Головний біль», «біль голови») is the nervous system's.
        ("brain", r"\bголовн\w*\s+(?:мозк|біл|бол)|\b(?:біл|бол)\w*\s+голов|\bbrain\b|\bенцефал|\bеег\b|\beeg\b|\bheadache"),
        ("metabolism", r"\bгіпоглік|\bгіперглік|\bцукров\w*\s+діабет|\bhypoglyc|\bhyperglyc|\bdiabet"),
    )
)
#: An ICD-10 code's chapter names the body system a diagnosis is about
#: (WHO ICD-10, 2019 edition): «K52.9» the digestive system, «L20-L30» the
#: skin.  Only chapters with an area of their own; a code in Cyrillic
#: letters («К52.9») is the same code.
_ICD_CODE_RE = re.compile(r"(?<![\w.])([A-ZКМЕІ])(\d{2})(?:\.\d{1,2})?(?![\w])")
_ICD_LETTERS = str.maketrans("КМЕІ", "KMEI")
_ICD_CHAPTERS: tuple[tuple[str, int, int, str], ...] = (
    ("E", 0, 7, "thyroid"), ("E", 10, 16, "metabolism"), ("G", 0, 99, "brain"), ("I", 0, 99, "heart"),
    ("J", 0, 99, "lungs"), ("K", 70, 87, "liver"), ("K", 0, 99, "digestive"), ("L", 0, 99, "skin"),
    ("M", 40, 54, "spine"), ("M", 0, 25, "joints"), ("N", 0, 39, "kidneys"),
)


def _diagnosis_areas(summary: str) -> tuple[str, ...]:
    """The areas a written diagnosis names, by organ word and by ICD-10 code."""
    areas = [area for area, pattern in _ORGAN_AREAS if pattern.search(summary)]
    for letter, number in _ICD_CODE_RE.findall(summary):
        letter = letter.translate(_ICD_LETTERS)
        area = next((area for chapter, low, high, area in _ICD_CHAPTERS
                     if chapter == letter and low <= int(number) <= high), None)
        if area and area not in areas:
            areas.append(area)
    return tuple(areas)
#: A visit that gave a vaccine («Необхідність імунізації», «Вакцинації»):
#: filed under immunity alone -- «Гепатиту А+В» names the vaccine, not the liver.
_VACCINATION_VISIT = re.compile(r"необхідн\w*\s+імунізац|\bвакцинаці[їя]\b|\bvaccination\b", re.I)

_GENERIC_TITLES = {
    "consultation": "Clinical consultation", "diagnostic_image": "Medical images",
    "pathology": "Pathology report", "radiology_mri": "MRI report",
    "radiology_xray": "Radiology report", "ultrasound": "Ultrasound report",
    "electrocardiogram": "ECG report", "clinical_report": "Clinical report",
}

# The labels a report puts in front of its own conclusion, strongest first.
# Within the first group the LAST label wins: a chest X-ray opens with
# «Висновок:» over its description and closes with «Висновок:» over the
# radiologist's verdict.
_CONCLUSION_LABELS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:гістологічн\w*\s+)?(?:висновок|buchobok|заключення)(?:\s+лікаря)?\s*[:：]|(?:impression|conclusion)\s*[:：]", re.I),
    re.compile(r"(?:уз|узд|мр)[- ]?ознаки\s*[:：]", re.I),
    # Form 028/о prints its field label in a column beside the value, so text
    # extraction reads «Діагноз основний: G44.2 …», «Діагноз» / «основний: …»
    # or «основний: K52.9 …» / «Діагноз синдром …» / «супутній: L20-L30 …».
    # «основний:» and «супутній:» are kept in the text (zero width): they say
    # which diagnosis is which.
    re.compile(
        r"(?:попередн|заключн|остаточн|клінічн)\w*\s+діагноз\s*[:：]|^\s*діагноз\s*[:：]"
        r"|^\s*діагноз\s*$|^\s*діагноз\s+(?=основний\s*[:：])|^(?=\s*основний\s*[:：])"
        # Expert's later template: «по МКХ-10 (Основний): -. Опис: <diagnosis>».
        r"|\bпо\s+мкх-?10\s*\(\s*основний\s*\)\s*[:：]",
        re.I | re.M,
    ),
    re.compile(r"kardia\s+advanced\s+determination\s*[:：]", re.I),
    re.compile(r"^\s*огляд\s*(?:[:：]\s*)?$", re.I | re.M),
    # Expert's X-ray: the radiologist's reading under «Результат:».
    re.compile(r"^\s*результат\s*[:：]\s*$", re.I | re.M),
)
#: Which clinical types each label above is read in; a label not listed is read in any.
_CONCLUSION_LABEL_TYPES = {4: {None, "consultation"}, 5: {None, "radiology_xray", "radiology_mri"}}

_CONCLUSION_END = re.compile(
    r"\n\s*(?:рекомендовано|рекомендації|рекомендую)\b|\bрекомендовано\s*[:：]"
    r"|\bрекомендовано\s+(?:обстеження|лікування)|\bдо\s+(?:відома|уваги)"
    r"|\bдата\s+(?:дослідження|обстеження|візиту)|\bдата\s*[:：]|\bплан\s+обстеження|\bпідпис"
    r"|\bрезультати\s+(?:ультразвукового\s+)?досліджен|\bлікар(?:[-‐]\w+)?\s*[:_]|\bлікар[-‐]патолог"
    r"|\bмедична\s+сестра|\bзображень\s*[:：]|\bед\s*[-–]\s*\d|\bnotes\b|\*\s*kardia|\bназва\s+послуги"
    r"|\bсторінка\s+\d|\bлабораторні\s+дослідження|\bпризначене\s+лікування|\bконсультації\s+спеціалістів"
    r"|\bінші\s+дослідження|\bвисновок\s+(?:\w+\s+)?не\s+(?:є|являєть)|\bскарги\b"
    # Form 028/о: the field under the diagnosis.
    r"|\bдані\s+лабораторних\s+та\b"
    # An eHealth diagnostic report's sign-off.
    r"|\bрезультати\s+інтерпретовано|\bдата\s+та\s+час\s+формування"
    # Expert's breath test: «Коментар: рекомендовано консультація …» is advice.
    r"|\bкоментар\s*[:：]\s*(?=рекоменд)"
    # An eHealth visit note: the diagnosis is followed by the vaccines given
    # («Вакцинації», «Назва вакцини …») and the plan («Призначення»), which
    # are the record of the visit, not its conclusion.
    r"|\n\s*вакцинації\s*\n|\bназва\s+вакцини|\n\s*призначення\s*\n|\bрекомендована\s+вакцинація",
    re.I,
)

_RECOMMENDATION_LABEL = re.compile(
    r"\bрекомендовано(?:\s+(?:обстеження|лікування))?\s*[:：]|^\s*(?:рекомендовано|рекомендації)\b(?:\s+і\s+лікування\b)?"
    r"|\bплан\s+обстеження\s*[:：]|\bкоментар\s*[:：]\s*(?=рекоменд)"
    r"|\bпризначене\s+лікування(?:\s+та\s+рекомендації)?\s*[:：]|^\s*призначення\s*$"
    # Zero-width: the label says what the schedule under it is, so it stays.
    r"|^(?=\s*рекомендована\s+вакцинація\b)",
    re.I | re.M,
)
#: The end of a dose's protocol table in an eHealth visit note (the rows
#: `immunizations._visit_block` keeps).  The doctor's advice («Після
#: вакцинації …», fever dosing, «Рекомендована вакцинація: …») follows the
#: last one with no label of its own, above «Призначення».
_VISIT_PROTOCOL_TABLE = re.compile(r"^№ дози.*(?:\n(?:доз\b|[1-9]\s|Здоров).*)*", re.M)
_RECOMMENDATION_END = re.compile(
    r"\bдо\s+(?:відома|уваги)|\bпідпис|\bдата\s+(?:дослідження|обстеження)|\bдата\s*[:：]"
    r"|\bлікар(?:[-‐]\w+)?\s*[:_]|\bлікар\s+пояснив|\bсторінка\s+\d|\bзалиште\s+відгук"
    r"|\bвхід\s+в\s+особистий|\bпацієнт\s*[:：]|\bмедикаментозне\s+лікування|\bмедична\s+сестра"
    r"|\bінші\s+дослідження|\bрезультати\s+(?:ультразвукового\s+)?досліджен|\bзображень\s*[:：]"
    # Form 028/о: the services the clinic books, then the next visit.
    r"|\bрекомендовані\s+послуги|\bдата\s+наступної\s+консультації"
    # Expert's X-ray: the effective dose, the radiologist and the disclaimer.
    r"|\bед\s*[-–=]\s*\d|п\.?\s?і\.?\s?б\.?\s+лікаря|\bне\s+є\s+остаточним",
    re.I,
)

#: Lines that identify the clinic or the person rather than describe the
#: study.  They never reach a stored finding: the patient's name and date of
#: birth were being shown as the clinical conclusion of an abdominal scan.
_LETTERHEAD_LINE = re.compile(
    r"www\.|https?://|@\w|\.com\.ua|\+\s*38\s*\(?0\d|поліклініка\s+№|№\s*\d+\s+від\s+\d|\bтел\b|тел\.|\(0\d{2}\)|\bм\.\s*львів|\bвул\.|\bпросп|проспект\s+\w+"
    r"|\bтзов\b|\bтов\b|\bліцензія|\bєдрпоу|юр\.\s*адреса|контакт|прізвище|\bпіб\b|п\.і\.[бп]"
    r"|\bпацієнт\w*\s*[:：]|\bpatient\s*[:：]|prepared\s+for|дата\s+народження|date\s+of\s+birth|№\s*(?:пацієнта|медичної)|амбулаторна\s+карта"
    r"|історія\s*(?:№|хвороби)|\bвік\s*[:：]|скерува|ким\s+скерований|\bпідпис|\bлікар\b|\bдиректор|допоможіть\s+лікарні"
    r"|напишіть\s+свої|з\s+повагою|особистий\s+кабінет|до\s+відома|до\s+уваги|не\s+є\s+(?:остаточним|клінічним)?\s*діагноз"
    r"|потребу\w*\s+консультації|своїм\s+власним|лікар\s+пояснив|я\s+розумію|підтверджую|^\s*я,\s|сторінка\s+\d"
    r"|залиште\s+відгук|наведіть\s+камеру|\^|\[embedded\s+image|обстеження\s+проведено\s+на|апарат|медична\s+сестра"
    r"|отримано|дата\s+завантаження|пристрій\s*[:：]|частина\s+тіла|^\s*id\s*[:：]|^\s*стать\s*[:：]|^\s*тип\s*[:：]"
    r"|вкажіть\s+основний\s+діагноз|copyright|©|alivecor|confidential|medical\s+system|японія|toshiba|siemens|simens|magnetom|лаборант|_{4,}|^\s*\d+\s+(?:of|з)\s+\d+\s*$|ехеалth|ehealth|описание",
    re.I,
)

#: Abnormal conclusion vocabulary, by the explanation that answers it.  A
#: term only counts when its clause does not negate it («Ознак кісти Бейкера
#: не виявлено» is a normal result).  Plain «протрузія» and «остеохондроз»
#: are deliberately absent: age-related disc changes are reported on most
#: adult spines and are not, alone, a reason to act (moz-1326-2026).
_ATTENTION_TERMS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (family, re.compile(pattern, re.I))
    for family, pattern in (
        ("colorectal_polyp", r"аденом(?!іоз)|поліп(?!ектом)|зубчаст|adenoma|\bpolyp"),
        ("fatty_liver", r"стеатоз|гепатоз|гепатомегал|ліпоматоз|дифузн\w*\s+змін\w*\s+(?:паренхіми\s+)?(?:печінки|підшлунков)|steatosis|hepatomegaly"),
        ("cholestasis", r"холестаз|сладж|cholestasis|sludge"),
        ("thyroid_nodule", r"(?:вузл|вузол)(?![^.;]*(?:шморл|міом))|nodule"),
        ("spine_disc", r"\bкил[аиі]|гриж|екструз|секвестр|конфлікт|спондиліт|сакроіле|спондилоартрит|сколіоз|торакалг|люмб\w*алг|радикулопат|hernia|extrusion"),
        ("lv_mass", r"гіпертрофі|(?:підвищ|збільш)\w*\s+індекс\w*\s+маси\s+міокарда|hypertroph"),
        ("lipoma", r"ліпом(?!атоз)|lipoma"),
        ("lymph_inflammation", r"лімфаденопат|лімфаденіт|запальн\w*\s+змін|сіалоаден|lymphadenopathy"),
        ("joint_tendon", r"тендинопат|тендиніт|лігаментопат|синовіт|хондромаляц|кіст\w*\s+бейкера|розтяг|фасциїт|(?<!спондило)артрит|бурсит|tendinopathy|synovitis|fasciitis|arthritis"),
    )
)
#: Two patterns rather than one alternation, to stay inside the regex
#: complexity budget; only whether any of them is found is ever asked.
_NEGATED_CLAUSES = (
    re.compile(r"не\s+(?:виявлен|визнача|візуаліз|спостеріга)|\bнемає\b|відсутн|\bбез\s+(?:ознак|видимих)", re.I),
    re.compile(r"\bno\s+(?:evidence|sign)|\bnot\s+(?:seen|detected)", re.I),
)
_NEGATED_WORD = re.compile(r"(?:\bне|\bбез|\bno|\bnot)\s+$", re.I)

#: The cited sources behind each explanation (ids in data/reference_library.json).
FINDING_EXPLANATION_SOURCES: dict[str, tuple[str, ...]] = {
    "colorectal_polyp": ("us-mstf-polypectomy-2020", "esge-polypectomy-2020", "moz-512-2025-rok"),
    "fatty_liver": ("aasld-masld-2023", "easl-easd-easo-masld-2024", "moz-826-2014-nash", "fatty-pancreas-consensus-2026"),
    "cholestasis": ("acg-liver-2017", "easl-gallstones-2016", "easl-cholestasis-2009", "moz-nastanova-00213"),
    "thyroid_nodule": ("acr-tirads-2017", "eu-tirads-2017", "nice-ng145"),
    "spine_disc": ("acp-low-back-pain-2017", "acr-axspa-2019", "nice-ng59", "moz-1326-2026", "moz-1582-2025"),
    "lv_mass": ("ase-eacvi-chamber-2015", "moz-1581-2024"),
    "lipoma": ("medlineplus-lipoma", "medlineplus-skin-lumps", "nhs-lipoma"),
    "lymph_inflammation": ("medlineplus-swollen-lymph-nodes", "medlineplus-salivary-gland-infections", "nhs-swollen-glands"),
    "joint_tendon": (
        "medlineplus-tendinitis", "medlineplus-baker-cyst", "medlineplus-plantar-fasciitis", "medlineplus-arthritis",
        "nhs-tendonitis", "nhs-bakers-cyst", "nhs-plantar-fasciitis", "nhs-arthritis",
    ),
}

_DATE_LABELLED = (
    re.compile(r"дата\s+(?:дослідження|обстеження|візиту|консультації)\s*[:.]?[^\d]{0,60}?(\d{1,2})\s*[./,]\s*(\d{1,2})\s*[./,]\s*(\d{4})", re.I | re.S),
    re.compile(r"(?<!\w)(?:дослідження|обстеження)\s*[:：][^\d]{0,60}?(\d{1,2})\s*[./,]\s*(\d{1,2})\s*[./,]\s*(\d{4})", re.I | re.S),
    re.compile(r"\bдата\s*[:：.]\s*(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})", re.I),
)


#: Glyphs the eHealth PDF generator prints for plain ones: ornate parentheses
#: «﴾гіпертонічна﴿» and the U+2010 hyphen in «МКХ‐10».  A soft hyphen is a
#: line-break hint that survived extraction.
_PRINTED_PUNCTUATION = str.maketrans({"\xad": "-", "‐": "-", "﴾": "(", "﴿": ")"})


def _page_text(row: sqlite3.Row) -> str:
    """The page as one text: the native layer, plus OCR unless OCR only reads
    the pictures on a page whose words are already native (an ultrasound
    screenshot's overlay is not part of the report)."""
    native = (row["native_text"] or "").translate(_PRINTED_PUNCTUATION)
    ocr = (row["ocr_text"] or "").translate(_PRINTED_PUNCTUATION)
    if len(re.sub(r"\s", "", native)) >= 400 or not ocr.strip():
        return native.strip()
    if normalized_key(ocr) in normalized_key(native):
        return native.strip()
    return f"{native}\n{ocr}".strip()


def _extract_date(text: str, fallback: str | None) -> str | None:
    """The date the study was done, as the report prints it; else `fallback`.

    A re-issued report carries the issue date as its document date, and a
    phone photo carries the day it was taken, so the printed study date wins.
    Layout can push the value a line or two past its label («Дата
    дослідження: <doctor's name> Лікар: 01.02.2025»); a date of birth never
    qualifies.
    """
    for pattern in _DATE_LABELLED:
        for match in pattern.finditer(text):
            day, month, year = (int(part) for part in match.groups())
            try:
                return date(year, month, day).isoformat()
            except ValueError:
                continue
    return fallback


def _is_noise_line(line: str) -> bool:
    # A labelled field («Опис: ВПЛ») is the form talking, not stamp debris,
    # however short its value.
    if re.match(r"[^\W\d_]{3,}\s*[:：]\s*\S", line):
        return False
    words = re.findall(r"[^\W\d_]{4,}", line)
    return not re.search(r"[.;:!?)]\s*$", line) and len(words) < 2


#: A line that ends on «або» («Нурофен 400 мг … або» / «Парацетамол …») has
#: not finished its sentence, whatever the next line opens with.
_OPEN_CONJUNCTION = re.compile(r"(?<![^\W\d_])(?:або|чи|та|і|й|or|and)$", re.I)


#: A clinic's social handle or web address printed in the margin
#: («@lviv_medical_center») is not part of what the doctor wrote.
_HANDLE_RE = re.compile(r"(?<![\w.])@[A-Za-z_][\w.]*|https?://\S+|\bwww\.\S+")


def _clean_block(text: str) -> str:
    lines = [line.strip(" \t") for line in _HANDLE_RE.sub("", text).splitlines()]
    lines = [line for line in lines if line.strip()]
    # Stamp and signature debris trails a scanned conclusion («coe ЄЖЕНОЮ», «Ry»).
    while lines and _is_noise_line(lines[-1]):
        lines.pop()
    # A diagnosis list is one diagnosis per line («Сакроілеїт?» / «Паротит?»);
    # joined with bare spaces the question mark of one reads as belonging to
    # all.  A line that ends without punctuation before one that opens with a
    # capital or an ICD code is a new item, not a wrapped sentence; so is a
    # line that is an abbreviation alone or with its bracket («Грипу» / «ВПЛ»,
    # «ВПЛ (6, 11, …)»).  An abbreviation with words after it is a wrap
    # («КВР помірний» / «СН 0», OCR's «тонкої» / «КИШКИ ЗІ …»).
    joined = [
        line + ("; " if index + 1 < len(lines) and not re.search(r"[.,;:!?(\-]$", line)
                and not _OPEN_CONJUNCTION.search(line)
                and re.match(r"[A-ZА-ЯІЇЄҐ](?:[a-zа-яіїєґ'’\d]|[A-ZА-ЯІЇЄҐ]+\s*(?:\(|$))", lines[index + 1]) else " ")
        for index, line in enumerate(lines)
    ]
    return collapse_space("".join(joined)).strip(" .-–—:;,") + ("." if lines and lines[-1].rstrip().endswith(".") else "")


def _conclusion_span(text: str, clinical_type: str | None = None) -> tuple[int, int, int] | None:
    """(label start, conclusion start, conclusion end) of the report's own conclusion."""
    for index, pattern in enumerate(_CONCLUSION_LABELS):
        if clinical_type not in _CONCLUSION_LABEL_TYPES.get(index, {clinical_type}):
            continue
        matches = list(pattern.finditer(text))
        for match in (reversed(matches) if index == 0 else matches):
            if clinical_type == "consultation" and index == 0 and _quoted_in_history(text, match.start()):
                continue
            start = match.end()
            end_match = _CONCLUSION_END.search(text, start)
            end = end_match.start() if end_match else len(text)
            if len(_conclusion_text(text[start:end])) >= 4:
                return match.start(), start, min(end, start + 3000)
    return None


def _quoted_in_history(text: str, position: int) -> bool:
    """Whether `position` sits in a visit note's complaints or history, where
    a «Висновок:» is a quoted study («Дихальний тест від …: Висновок: …»)."""
    sections = [
        (found.start(), name) for name, pattern in VISIT_SECTION_RES.items()
        for found in pattern.finditer(text, 0, position)
    ]
    return bool(sections) and max(sections)[1] in {"complaints", "history"}


#: What form 028/о leaves inside a diagnosis: its own field label read into
#: the value («Діагноз синдром …»), and the software's placeholder where no
#: diagnosis was entered («Вкажіть основний діагноз у програмі !»), which is
#: not a diagnosis.
_FORM_DIAGNOSIS_NOISE = re.compile(r"^\s*діагноз(?!\s*[:：])\s*|^.*вкажіть\s+основний\s+діагноз.*$", re.I | re.M)
_MAIN_DIAGNOSIS_LABEL = re.compile(r"^\s*основний\s*[:：]\s*", re.I | re.M)
_CODED_DIAGNOSIS_LINE = re.compile(r"(?:(?:[Оо]сновний|[Сс]упутній)\s*[:：]\s*)?[A-ZКМЕІ]\d{2}(?:\.\d{1,2})?(?:-[A-Z]\d{2})?\s")


def _conclusion_text(block: str) -> str:
    """A conclusion block as stored: cleaned, form noise out, a repeated line said once."""
    # «-. Опис:»: no code was chosen, the description follows.
    block = _FORM_DIAGNOSIS_NOISE.sub("", re.sub(r"^\s*-\s*\.?\s*Опис\s*[:：]\s*", "", block, flags=re.I))
    if not re.search(r"супутн\w*\s*[:：]", block, re.I):
        # «основний:» alone names nothing the reader needs.
        block = _MAIN_DIAGNOSIS_LABEL.sub("", block)
    lines = list(dict.fromkeys(line.strip() for line in block.splitlines() if line.strip()))
    # A line opening with an ICD-10 code is one coded diagnosis; the line
    # after it is the next one, whatever its case («K52.9 … неуточнений» /
    # «синдром надмірного бактерійного росту.»).
    lines = [
        f"{line};" if index + 1 < len(lines) and _CODED_DIAGNOSIS_LINE.match(line)
        and not re.search(r"[.,;:!?(\-]$", line) and not _OPEN_CONJUNCTION.search(line) else line
        for index, line in enumerate(lines)
    ]
    return _clean_block("\n".join(lines))


def _extract_clinical_assessment(text: str, clinical_type: str | None = None) -> str | None:
    """The report's own conclusion, verbatim, from its labelled block only."""
    span = _conclusion_span(text.replace("\xad", "-"), clinical_type)
    return _conclusion_text(text.replace("\xad", "-")[span[1]:span[2]]) if span else None


#: A contact phone, «Тел.: 0501234567» or a bare «+380501234567».
_PHONE = r"(?:тел\.?\s*(?:[:：]\s*)?)?\+?\b(?:38)?0\d{9}\b"
_PHONE_RE = re.compile(_PHONE, re.I)
#: The same phone with the separator that listed it.
_LISTED_PHONE_RE = re.compile(_RUN_START + r"[;,]?\s*" + _PHONE, re.I)
_QUANTITY_COLUMN_RE = re.compile(_RUN_START + r"\s+\d+\s*$")
_BLANK_REVISIT_RE = re.compile(
    _RUN_START + r"[;,.]?\s*Повторний\s+візит\s*(?:[:：]\s*)?(?:[;.]\s*)?$", re.I
)


def _extract_recommendations(text: str, after: int = 0) -> str:
    match = _RECOMMENDATION_LABEL.search(text, after)
    tables = [table.end() for table in _VISIT_PROTOCOL_TABLE.finditer(text, after, match.start() if match else len(text))]
    if not match and not tables:
        return ""
    start = tables[-1] if tables else match.end()
    end_match = _RECOMMENDATION_END.search(text, start)
    block = text[start: end_match.start() if end_match else len(text)]
    lines = []
    services = False  # inside an order sheet's «Назва послуги К-сть» table
    for line in block.splitlines():
        # A contact phone is not advice; strip it before the quantity column
        # rule below eats the number and leaves a bare «Тел.».
        line = _PHONE_RE.sub("", line.strip())
        # The quantity column exists only on the rows under that header;
        # elsewhere a trailing number is the advice («Нурофен 400 мг - 1»,
        # «3 Гардасил 9»).
        services = bool(re.match(r"назва\s+послуги", line, re.I)) or (services and bool(_QUANTITY_COLUMN_RE.search(line)))
        if services:
            line = _QUANTITY_COLUMN_RE.sub("", line.strip())
        if not line or re.match(
            r"назва\s+послуги|консультації\s+спеціалістів\s+та\s+реабілітація"
            r"|спосіб\s+тривалість|назва\s+препарату\s*$|прийому\s+застосування|призначення\s*$",
            line, re.I,
        ):
            continue
        lines.append(line)
    # One referral per line on an order sheet; keep them apart when joined.
    joined = [
        line + (";" if index + 1 < len(lines) and lines[index + 1][:1].isupper()
                and not re.search(r"[.,;:]$", line) and not _OPEN_CONJUNCTION.search(line) else "")
        for index, line in enumerate(lines)
    ]
    text = _clean_block("\n".join(joined))
    # A contact phone is not advice, and a «Повторний візит» the doctor left
    # blank says nothing.
    text = _LISTED_PHONE_RE.sub("", text)
    text = _BLANK_REVISIT_RE.sub("", text).strip(" ;,")
    if len(text) > 1500:
        # Cut at a word, never mid-name («Аркоксія (еторіко»).
        text = text[:1500].rsplit(" ", 1)[0] + " ..."
    return text


#: Two patterns rather than one alternation, to stay inside the regex
#: complexity budget; only whether any of them is found is ever asked.
_IDENTITY_LINES = (
    re.compile(r"прізвище|\bпіб\b|п\.і\.[бп]|\bпацієнт\w*\s*[:：]", re.I),
    re.compile(r"\bpatient\s*[:：]|prepared\s+for|дата\s+народження|date\s+of\s+birth", re.I),
)


def _strip_letterhead(text: str, identity: tuple[str, ...] = ()) -> str:
    """The report without the clinic's letterhead or the person's identity.

    The letterhead always sits above the line naming the patient, so the head
    of the report is cut through the last identity line near the top; what
    remains is filtered line by line, and a line naming the patient (in
    Cyrillic or transliterated) or giving their date of birth is dropped too.
    """
    lines = [raw.strip() for raw in text.splitlines() if raw.strip()]
    head = [
        index for index, line in enumerate(lines[:25])
        if any(pattern.search(line) for pattern in _IDENTITY_LINES)
    ]
    if head:
        lines = lines[head[-1] + 1:]
    lines = [_without_letterhead(line) for line in lines]
    return "\n".join(
        line for line in lines
        if re.search(r"[^\W\d_]", line)
        and not any(token in search_key(line) or token in line for token in identity)
    )


#: The right-hand column of an eHealth visit note's dose rows.  Its left
#: column names the vaccinating doctor («Лікар, який виконав вакцинацію …»,
#: «… (Лікар-педіатр)»), which is a signature line; the quantity and site
#: printed beside it are the record of the dose.
_DOSE_COLUMN_RE = re.compile(r"(?:Кількість введеної вакцини|Одиниці вимірювання|Місце введення|Шлях введення)\b.*")


def _without_letterhead(line: str) -> str:
    """The line, its dose column when only the column beside it is letterhead, or ''."""
    if not _LETTERHEAD_LINE.search(line):
        return line
    column = _DOSE_COLUMN_RE.search(line)
    return column.group(0) if column and not _LETTERHEAD_LINE.search(column.group(0)) else ""


def _identity_tokens(connection: sqlite3.Connection, patient_id: str) -> tuple[str, ...]:
    """Name parts (as search keys) and date-of-birth spellings of one patient."""
    row = connection.execute(
        "SELECT display_name, date_of_birth FROM patients WHERE id=?", (patient_id,)
    ).fetchone()
    if not row:
        return ()
    tokens = [search_key(part) for part in re.findall(r"[^\W\d_]{4,}", str(row[0] or ""))]
    if row[1]:
        try:
            born = date.fromisoformat(str(row[1])[:10])
            tokens += [born.strftime("%d.%m.%Y"), born.isoformat(), born.strftime("%m/%d/%Y"), born.strftime("%Y%m%d")]
        except ValueError:
            pass
    return tuple(tokens)


def _language(text: str) -> str:
    cyrillic = len(re.findall(r"[а-яіїєґ]", text, re.I))
    latin = len(re.findall(r"[a-z]", text, re.I))
    return "uk" if cyrillic >= latin else "en"


def finding_attention(summary: str | None) -> list[str]:
    """The explanation families an abnormal conclusion names, in order."""
    families: list[str] = []
    for clause in re.split(r"[.;\n]|\s[-–—]\s", summary or ""):
        if not clause.strip() or any(pattern.search(clause) for pattern in _NEGATED_CLAUSES):
            continue
        for family, pattern in _ATTENTION_TERMS:
            for match in pattern.finditer(clause):
                if not _NEGATED_WORD.search(clause[: match.start()]) and family not in families:
                    families.append(family)
    return families


def _ocr_quality(text: str) -> float:
    """Share of words that read as one script in one case: OCR of a stamped
    scan produces «кишкИи», «TlocnigxyBanun»."""
    words = re.findall(r"[^\W\d_]{3,}", text)
    if not words:
        return 0.0
    bad = sum(
        1 for word in words
        if (re.search(r"[a-z]", word, re.I) and re.search(r"[а-яіїєґ]", word, re.I))
        or re.search(r"[a-zа-яіїєґ][A-ZА-ЯІЇЄҐ]", word)
    )
    return 1 - bad / len(words)


def _study_for(header: str, clinical_type: str) -> tuple[str, str, tuple[str, ...]] | None:
    for key, title, areas, types, pattern in _STUDIES:
        if (types is None or clinical_type in types) and pattern.search(header):
            return key, title, areas
    return None


#: «...; Клінічний діагноз: ...» -- where a working diagnosis is restated.
_CLINICAL_DIAGNOSIS_RE = re.compile(_RUN_START + r"[;.]?\s*клінічний\s+діагноз\s*[:：]\s*", re.I)


def _report_findings(connection: sqlite3.Connection) -> list[dict[str, object]]:
    """One candidate finding per narrative report, before de-duplication."""
    rows = connection.execute(
        """SELECT d.id document_id, d.owner_user_id, d.patient_id, d.original_filename,
                  d.title document_title, d.imported_at,
                  d.clinical_type document_type, d.report_date document_date,
                  p.page_number, p.native_text, p.ocr_text,
                  r.id report_id, r.clinical_type report_type, r.report_date report_date,
                  COALESCE(r.vendor_id, d.vendor_id) resolved_vendor_id
           FROM documents d
           JOIN document_pages p ON p.document_id=d.id
           LEFT JOIN reports r ON r.document_id=d.id
             AND p.page_number BETWEEN r.start_page AND r.end_page
           WHERE d.duplicate_of_document_id IS NULL
           ORDER BY d.id, p.page_number, r.start_page"""
    ).fetchall()
    candidates = []
    identities: dict[str, tuple[str, ...]] = {}
    for pages in _pages_by_report(rows).values():
        candidate = _report_candidate(connection, pages, identities)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _pages_by_report(rows: list[sqlite3.Row]) -> dict[tuple[str, str | None], list[sqlite3.Row]]:
    """Each page once, under the first report whose page range holds it."""
    reports: dict[tuple[str, str | None], list[sqlite3.Row]] = {}
    seen_pages: set[tuple[str, int]] = set()
    for row in rows:
        page_key = (row["document_id"], row["page_number"])
        if page_key in seen_pages:
            continue
        seen_pages.add(page_key)
        reports.setdefault((row["document_id"], row["report_id"]), []).append(row)
    return reports


#: A visit note whose doctor entered no diagnosis (form 028/о's placeholder
#: stands in its place) is still a visit: what the person came with is what
#: it records.  Kept with its label, so it never reads as a diagnosis.
_COMPLAINTS_LABEL = re.compile(r"^[ \t]*скарги\b", re.I | re.M)
_COMPLAINTS_END = re.compile(r"^[ \t]*(?:анамнез|об['’]єктивн|діагноз|дані\s+лабораторних|рекоменд)", re.I | re.M)


def _complaints_span(text: str) -> tuple[int, int, int] | None:
    label = _COMPLAINTS_LABEL.search(text)
    if not label:
        return None
    end = _COMPLAINTS_END.search(text, label.end())
    end_at = end.start() if end else min(len(text), label.end() + 600)
    return (label.start(), label.start(), end_at) if len(_clean_block(text[label.end():end_at])) >= 4 else None


def _report_summary(text: str, span: tuple[int, int, int] | None) -> str:
    """The report's conclusion, cleaned, with a restated diagnosis said once."""
    summary = _conclusion_text(text[span[1]:span[2]]) if span else ""
    # eHealth marks its required fields with «*»; it is form furniture.
    summary = re.sub(r"\*(?=[\s;,.]|$)", "", summary)
    # A working diagnosis confirmed word for word as the clinical one is
    # one diagnosis, not two.
    parts = _CLINICAL_DIAGNOSIS_RE.split(summary)
    if len(parts) == 2 and normalized_key(parts[0]) == normalized_key(parts[1]):
        summary = parts[1]
    return summary


_EMPTY_FIELD_RE = re.compile(r"^[^\n:]{2,40}[:：][ \t]*$", re.M)


def _report_filing(
    first: sqlite3.Row, clinical_type: str, text: str, span: tuple[int, int, int] | None, summary: str
) -> tuple[str, str, tuple[str, ...]]:
    """(study key, title, health areas) a report is filed under.

    A consultation is the specialty its heading names, filed by what its
    diagnosis names; never by the history it quotes («вірусний гепатит
    заперечує», «УЗД ЩЗ: …», «серцебиття» among the complaints), so its
    header is only the text above the patient line.
    """
    names = f"{first['document_title'] or ''} {first['original_filename'] or ''}"
    if clinical_type == "consultation":
        patient = PATIENT_LABEL_RE.search(text)
        body = text[: patient.start()] if patient else ""
    else:
        # An exam template's empty field («Щитовидна залоза:») names an organ
        # nobody described; it never files the report.
        body = _EMPTY_FIELD_RE.sub("", text[: span[0]] if span else text[:2000])
    study = _study_for(f"{names} {body}", clinical_type)
    diagnosed = _diagnosis_areas(summary)
    # «Гепатиту А+В» in a vaccination visit names the vaccine, not the liver.
    vaccination = clinical_type == "consultation" and _VACCINATION_VISIT.search(f"{summary} {text}")
    if study:
        key, title, areas = study
        if key.startswith("consult_") and key != "consult_vaccination" and diagnosed and not vaccination:
            return key, title, diagnosed
        if areas:
            return study
    if vaccination:
        return "consult_vaccination", "Family doctor consultation", ("immunity",)
    if study:
        return study
    filing = f"{names} {summary or text[:2000]}"
    areas = tuple(dict.fromkeys((*(area for area, pattern in _ORGAN_AREAS if pattern.search(filing)), *diagnosed)))
    return f"generic:{clinical_type}", _GENERIC_TITLES.get(clinical_type, "Clinical report"), areas


def _named_sides(first: sqlite3.Row) -> frozenset[str]:
    """The body sides the document's title or file name names."""
    named = f"{first['document_title'] or ''} {first['original_filename'] or ''}".replace("-", " ").replace("_", " ")
    return frozenset(
        side for side, pattern in (("left", r"\bлів\w*|\bleft\b"), ("right", r"\bправ\w*|\bright\b"))
        if re.search(pattern, named, re.I)
    )


def _conclusion_page(pages: list[sqlite3.Row], texts: list[str], span: tuple[int, int, int] | None) -> int:
    """The page the conclusion's label is printed on."""
    page_number = pages[0]["page_number"]
    if not span:
        return page_number
    offsets, position = [], 0
    for page, page_text in zip(pages, texts):
        offsets.append((position, page["page_number"]))
        position += len(page_text) + 1
    return max((number for offset, number in offsets if offset <= span[0]), default=page_number)


def _report_body_end(text: str, span: tuple[int, int, int] | None) -> int:
    """Where the stored report text ends."""
    if not span:
        return len(text)
    rec = _RECOMMENDATION_LABEL.search(text, span[2])
    if not rec:
        return span[2]
    rec_end = _RECOMMENDATION_END.search(text, rec.end())
    return _sentence_start(text, rec_end.start()) if rec_end else len(text)


def _sentence_start(text: str, index: int) -> int:
    """Where the sentence holding `index` starts: an end marker found inside a
    line («Своїм підписом підтверджую:») must not leave its first words behind."""
    line_start = text.rfind("\n", 0, index) + 1
    ends = [found.end() for found in re.finditer(r"[.;:!?]\s", text[line_start:index])]
    return line_start + (ends[-1] if ends else 0)


def _summary_fields(summary: str, original: str) -> dict[str, object]:
    """Language, status and legibility of one conclusion."""
    language = _language(summary) if summary else "uk"
    attention = finding_attention(summary)
    return {
        "summary_en": summary if language == "en" else "",
        "summary_uk": summary if language == "uk" else "",
        "status": "attention" if attention else "information",
        "attention_reasons": ",".join(attention),
        "confidence": round(0.6 + 0.4 * _ocr_quality(summary), 2) if summary else 0.5,
        "quality": _ocr_quality(summary or original),
    }


def _report_candidate(
    connection: sqlite3.Connection, pages: list[sqlite3.Row], identities: dict[str, tuple[str, ...]]
) -> dict[str, object] | None:
    """The candidate finding of one report's pages, or None for a report that
    is not narrative or names no health area."""
    first = pages[0]
    clinical_type = first["report_type"] or first["document_type"]
    if clinical_type not in NARRATIVE_TYPES:
        return None
    texts = [_page_text(page) for page in pages]
    text = "\n".join(texts)
    span = _conclusion_span(text, clinical_type)
    if span is None and clinical_type == "consultation":
        span = _complaints_span(text)
    summary = _report_summary(text, span)
    recommendations = _extract_recommendations(text, span[2]) if span else ""
    study_key, title, areas = _report_filing(first, clinical_type, text, span, summary)
    # Only an image set is filed without a written conclusion (its finding
    # points at the pictures); any other report with nothing read stays a
    # review task, not an empty finding filed by a word on its page.
    if not areas or (not summary and clinical_type != "diagnostic_image"):
        return None
    sides = _named_sides(first)
    if study_key in {"knee_mri", "elbow_mri"} and len(sides) == 1:
        title = f"{next(iter(sides)).capitalize()} {title[0].lower()}{title[1:]}"
    page_number = _conclusion_page(pages, texts, span)
    # The full report without its letterhead, cut after the conclusion and
    # recommendations so signatures, disclaimers and stamps stay out.
    body_end = _report_body_end(text, span)
    if first["patient_id"] not in identities:
        identities[first["patient_id"]] = _identity_tokens(connection, first["patient_id"])
    original = _strip_letterhead(text[:body_end], identities[first["patient_id"]]) if summary else ""
    fields = _summary_fields(summary, original)
    return {
        "document_id": first["document_id"], "owner_user_id": first["owner_user_id"],
        "patient_id": first["patient_id"], "report_id": first["report_id"],
        "page_number": page_number, "areas": areas, "title": title, "study": study_key,
        "summary_en": fields["summary_en"],
        "summary_uk": fields["summary_uk"],
        "summary": summary, "recommendations": recommendations,
        "original_text": original[:6000],
        "finding_date": _extract_date(text, first["report_date"] or first["document_date"]),
        "vendor_id": first["resolved_vendor_id"],
        "status": fields["status"],
        "attention_reasons": fields["attention_reasons"],
        "confidence": fields["confidence"],
        "quality": fields["quality"],
        "imported_at": first["imported_at"] or "",
        "sides": sides,
    }


def _deduplicate_findings(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    """One finding per study actually performed.

    A clinic re-issuing a report (the 12 Nov biopsy came back on 22 Nov with
    better OCR) or a person uploading the same scan again produces a second
    document with the same study, date and conclusion.  The most legible copy
    is kept; an image set with no written conclusion yields to the same day's
    written report of that study.
    """
    from difflib import SequenceMatcher

    # A trailing page split into its own report («Сайт лікарні», the DICOM
    # footer of an MRI) has no conclusion of its own; the report it belongs to does.
    written_documents = {item["document_id"] for item in candidates if item["summary"]}
    candidates = [item for item in candidates if item["summary"] or item["document_id"] not in written_documents]
    groups: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for item in candidates:
        groups.setdefault((item["owner_user_id"], item["patient_id"], item["study"], item["finding_date"]), []).append(item)
    kept: list[dict[str, object]] = []
    for items in groups.values():
        pool = [item for item in items if item["summary"]] or items
        pool = sorted(pool, key=lambda item: (-float(item["quality"]), str(item["imported_at"]), str(item["document_id"])))
        chosen: list[dict[str, object]] = []
        for item in pool:
            key = normalized_key(str(item["summary"]))
            # Left and right knees scanned on one day read almost alike and
            # are two studies; only the side named in the title tells them apart.
            if any(
                not (item["sides"] and other["sides"] and item["sides"] != other["sides"])
                and (
                    key == normalized_key(str(other["summary"]))
                    or SequenceMatcher(None, key, normalized_key(str(other["summary"])), autojunk=False).ratio() >= 0.85
                )
                for other in chosen
            ):
                continue
            chosen.append(item)
        kept.extend(chosen)
    return kept


#: Sentence ends, line breaks and spaced dashes.  The dash branch opens with a
#: blank run, so it is guarded like `_RUN_START` -- except that a split
#: resuming right after a matched line break may start a dash there.  Each
#: blank run's first blank is written out, so a split enters a run only by
#: consuming one, and the rest of the run is taken whole: nothing a branch
#: needs after it is a blank.
_AREA_CLAUSE_SPLIT_RE = re.compile(r"(?<=[.;])\s\s*+|\n|(?:(?<!\s)|(?<=\n))\s\s*+[-–]\s*")


def _area_finding(item: dict[str, object], area: str) -> dict[str, object]:
    """One area's share of a report filed under several.

    An abdominal scan is filed under liver and kidneys alike, and used to carry
    one status for both: «ознаки жирового гепатозу» put the kidneys of a normal
    kidney study under attention, with the liver's reason.  Each area now keeps
    the sentences of the conclusion that name its organ, and is judged on
    those alone; an area the conclusion does not mention is not under
    attention, and shows the whole conclusion for context.
    """
    areas, summary = item["areas"], str(item["summary"] or "")
    pattern = dict(_ORGAN_AREAS).get(area)
    if len(areas) < 2 or not summary or pattern is None:
        return item
    patterns = [dict(_ORGAN_AREAS).get(other) for other in areas]
    # A sentence naming none of the study's organs («Холестазу в помірній
    # кількості») belongs to the study's first area, the organ it is about.
    own = [
        clause.strip() for clause in _AREA_CLAUSE_SPLIT_RE.split(summary)
        if clause.strip() and (pattern.search(clause) or (
            area == areas[0] and not any(other and other.search(clause) for other in patterns)))
    ]
    reasons = finding_attention(" ".join(own))
    text = " ".join(own) or summary
    return {
        **item,
        "summary_en": text if item["summary_en"] else "",
        "summary_uk": text if item["summary_uk"] else "",
        "status": "attention" if reasons else "information",
        "attention_reasons": ",".join(reasons),
    }


def sync_clinical_findings(connection: sqlite3.Connection) -> int:
    """Rebuild the machine-read narrative findings.  Idempotent.

    Runs on every application start, on upload and on rescan.  A finding a
    person verified, corrected or rejected is never touched, and no machine
    row is added beside it for the same document and area.
    """
    inserted = 0
    # These rows were an older page-level fallback and can contradict the
    # actual conclusion page. They are deterministic machine output, not a
    # user-authored correction.
    connection.execute(
        "DELETE FROM clinical_findings WHERE title='Narrative report'"
        " AND verification_status NOT IN ('verified', 'corrected', 'rejected')"
    )
    ruled = {tuple(row) for row in connection.execute(
        "SELECT document_id, health_area FROM clinical_findings"
        " WHERE verification_status IN ('verified', 'corrected', 'rejected')"
    )}
    current_ids: set[str] = set()
    for report in _deduplicate_findings(_report_findings(connection)):
        for area in report["areas"]:
            if (report["document_id"], area) in ruled:
                continue
            item = _area_finding(report, area)
            finding_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{ID_NAMESPACE_PREFIX}:finding:{item['document_id']}:{item['page_number']}:{area}:{item['title']}",
            ))
            before = connection.total_changes
            connection.execute(
                """INSERT INTO clinical_findings(
                       id, owner_user_id, patient_id, document_id, report_id, page_number,
                       health_area, title, summary_en, summary_uk, recommendations, attention_reasons,
                       original_text, finding_date, vendor_id, status, confidence, verification_status, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'extracted', ?)
                   ON CONFLICT(document_id, page_number, health_area, title) DO UPDATE SET
                       summary_en=excluded.summary_en, summary_uk=excluded.summary_uk,
                       recommendations=excluded.recommendations, attention_reasons=excluded.attention_reasons,
                       original_text=excluded.original_text, finding_date=excluded.finding_date,
                       vendor_id=excluded.vendor_id, status=excluded.status,
                       confidence=excluded.confidence, report_id=excluded.report_id
                   WHERE clinical_findings.verification_status NOT IN ('verified', 'corrected', 'rejected')""",
                (
                    finding_id, item["owner_user_id"], item["patient_id"], item["document_id"],
                    item["report_id"], item["page_number"], area, item["title"],
                    item["summary_en"], item["summary_uk"], item["recommendations"], item["attention_reasons"],
                    item["original_text"], item["finding_date"], item["vendor_id"], item["status"],
                    item["confidence"], utc_now(),
                ),
            )
            inserted += connection.total_changes - before
            existing = connection.execute(
                "SELECT id FROM clinical_findings WHERE document_id=? AND page_number=? AND health_area=? AND title=?",
                (item["document_id"], item["page_number"], area, item["title"]),
            ).fetchone()
            current_ids.add(existing[0] if existing else finding_id)
    # Remove obsolete machine-derived rows when evidence or classification
    # changes. A human ruling remains attached to its original evidence.
    stale = [row[0] for row in connection.execute(
        "SELECT id FROM clinical_findings WHERE verification_status NOT IN ('verified', 'corrected', 'rejected')"
    ) if row[0] not in current_ids]
    connection.executemany("DELETE FROM clinical_findings WHERE id=?", [(item,) for item in stale])
    return inserted


@lru_cache(maxsize=1)
def _library_sources() -> dict[str, dict[str, object]]:
    from .reference import LIBRARY_PATH

    library = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    return {str(source["id"]): source for source in library.get("sources", [])}


def present_finding(row: dict[str, object]) -> dict[str, object]:
    """Locale-aware display fields for one stored finding.

    The summary is shown in the reader's language only when the source wrote
    it in that language (or a catalogued phrase translates it); otherwise the
    source's wording is shown and labelled as the original, never passed off
    as a translation.
    """
    english, ukrainian = str(row.get("summary_en") or ""), str(row.get("summary_uk") or "")
    text, original_language = _summary_for_locale(get_locale(), english, ukrainian)
    sources = _library_sources()
    explanations = [
        _finding_explanation(family, sources)
        for family in [item for item in str(row.get("attention_reasons") or "").split(",") if item]
    ]
    return {
        "summary_text": text,
        "summary_original_language": original_language,
        "explanations": explanations,
    }


def _summary_for_locale(locale: str, english: str, ukrainian: str) -> tuple[str, str | None]:
    """(summary text, the language it was written in when that is not the reader's)."""
    if locale != "uk":
        return english or ukrainian, ("uk" if not english and ukrainian else None)
    if ukrainian:
        return ukrainian, None
    if english and english in PHRASES:
        return PHRASES[english], None
    return english, ("en" if english else None)


def _finding_explanation(family: str, sources: dict[str, dict[str, object]]) -> dict[str, object]:
    cited = [sources[key] for key in FINDING_EXPLANATION_SOURCES.get(family, ()) if key in sources]
    return {
        "key": family,
        "text": t(f"finding.explain.{family}"),
        "sources": [
            {"publisher": translate_phrase(str(source.get("publisher") or "")), "name": source.get("name"),
             "url": source.get("url"), "region": source.get("region")}
            for source in cited
        ],
    }


def rule_context(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
