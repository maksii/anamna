"""Which concept a value is filed under: the 2026-11-07 value-by-value review.

Every case is a row shape from a reviewed report (names and ids changed).  The
printed label is the same word across specimens or methods, and the row's
specimen, section or unit is what says which measurement it was.
"""

from __future__ import annotations

from pathlib import Path

import json

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.ingest.concepts import CONCEPT_DEFINITIONS, stable_concept_id
from anamna.ingest.parsers import ParsedObservation
from anamna.ingest.pipeline import (
    ensure_concept,
    ensure_vendor,
    observation_specimen,
    repair_observation_semantics,
    seed_concepts,
)
from anamna.locales.concepts_uk import CONCEPT_NAMES_UK
from anamna.reference import LIBRARY_PATH, convert_value

from test_web_panels import build

URINALYSIS_TITLE = "Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду)"
SMEAR_TITLE = "ПАП-тест методом рідинної цитології. ЦИТОЛОГІЧНИЙ ПАСПОРТ"
CLINIC_TITLE = "Загальна клініка"


@pytest.fixture
def connection(tmp_path: Path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    with connect(settings) as conn:
        seed_concepts(conn)
        yield conn


def filed(connection, raw_name, *, value_type="text", title=None, **row):
    vendor_id = ensure_vendor(connection, "Synevo", None)
    concept_id, _unit = ensure_concept(
        connection, raw_name, vendor_id, value_type=value_type, clinical_type="laboratory", context=title, **row
    )
    return concept_id


def test_a_blood_count_unit_outranks_a_urinalysis_title(connection):
    """«Лейкоцити (WBC): 6.84 10^9 клітин/л» in an order titled as a
    urinalysis was filed as urine leukocytes and missing from the white-cell
    trend."""
    assert filed(connection, "Лейкоцити (WBC)", value_type="numeric", title=URINALYSIS_TITLE,
                 unit_raw="10^9 клітин/л") == "white-blood-cell-count"
    # The same order's urine rows keep their urine concepts.
    assert filed(connection, "Лейкоцити", title=URINALYSIS_TITLE, unit_raw="Leu/µL",
                 value_text="не виявлені") == "urine-leukocyte-esterase"
    assert filed(connection, "Лейкоцити в мкл (WBC)", value_type="numeric", title=URINALYSIS_TITLE,
                 unit_raw="кл/мкл", specimen="сеча") == "urine-leukocytes"


@pytest.mark.parametrize(
    ("raw_name", "value_type", "value_text", "expected"),
    [
        ("pH", "numeric", None, "stool-ph"),
        ("Слиз", "text", "в невеликій кількості", "stool-mucus"),
        ("Форма", "text", "не оформлений", "stool-form"),
        ("Консистенція", "text", "мазеподібна", "stool-consistency"),
        ("Запах", "text", "специфічний каловий", "stool-odour"),
        ("Колір калових мас", "text", "коричневий", "stool-colour"),
        ("М'язові волокна неперетравлені", "text", "не виявлені", "stool-muscle-fibres-unaltered"),
        ("М'язові волокна перетравлені", "text", "не виявлені", "stool-muscle-fibres-altered"),
        ("Нейтральний жир", "text", "не виявлений", "stool-neutral-fat"),
        ("Жирні кислоти", "text", "в невеликій кількості", "stool-fatty-acids"),
        ("Неперетравлена клітковина", "text", "в помірній кількості", "stool-plant-fibre-undigested"),
        ("Перетравлена клітковина", "text", "не виявлена", "stool-plant-fibre-digested"),
        ("Мила", "text", "не виявлені", "stool-soaps"),
        ("Крохмальні зерна позаклітинні", "text", "поодинокі в препараті", "stool-starch-extracellular"),
        ("Крохмальні зерна внутрішньоклітинні", "text", "не виявлені", "stool-starch-intracellular"),
        ("Йодофільні бактерії", "text", "поодинокі в препараті", "stool-iodophilic-flora"),
        ("Лейкоцити (копрограма)", "text", "не виявлені", "stool-leukocytes"),
        ("Еритроцити (копрограма)", "text", "не виявлені", "stool-erythrocytes"),
        ("Епітелій", "text", "не виявлений", "stool-epithelium"),
        ("Найпростіші (цисти лямблій)", "text", "не виявлені", "stool-protozoa"),
        ("Вегетативні форми і цисти найпростіших", "text", "не виявлені", "stool-protozoa"),
        ("Дріжджовий грибок", "text", "виявлений в невеликій кількості", "stool-yeast-like-fungal-elements"),
        ("Яйця гельмінтів", "text", "не виявлені", "stool-helminth-eggs"),
        ("Кристали", "text", "не виявлені", "stool-crystals"),
    ],
)
def test_a_coprogram_section_files_its_rows_under_the_stool_concepts(
    connection, raw_name, value_type, value_text, expected
):
    """The Synevo coprogram prints its material only as the section heading;
    «pH 6.75» and «Слиз» landed on urine pH and urine mucus, and the other rows
    on nameless concepts beside the existing stool ones."""
    for section in ("Копрограма", "Аналіз калу на кишкові паразити (метод"):
        parsed = ParsedObservation(
            raw_name=raw_name, value_numeric=6.75 if value_type == "numeric" else None,
            value_text=value_text, comparator=None, unit_raw=None, reference_text=None,
            reference_low=None, reference_high=None, page_number=1, evidence_text=raw_name,
            confidence=0.93, section=section,
        )
        specimen = observation_specimen(parsed)
        assert specimen == "кал"
        assert filed(connection, raw_name, value_type=value_type, title=CLINIC_TITLE,
                     value_text=value_text, specimen=specimen) == expected


def test_a_section_decided_concept_is_not_learned_as_a_bare_alias(connection):
    """Learned, the coprogram's «Кристали» -> stool would file the next
    unsectioned «Кристали» of the same laboratory as stool too."""
    assert filed(connection, "Кристали", value_text="не виявлені", specimen="кал") == "stool-crystals"
    assert filed(connection, "Кристали", value_text="не виявлені", title=URINALYSIS_TITLE) != "stool-crystals"
    assert filed(connection, "Епітелій", value_text="не виявлений", specimen="кал") == "stool-epithelium"
    assert filed(connection, "Епітелій", value_text="не виявлений", title=URINALYSIS_TITLE) != "stool-epithelium"


def test_a_coprogram_title_is_enough_once_it_names_the_stool(connection):
    assert filed(connection, "pH", value_type="numeric", title="Копрограма") == "stool-ph"


def test_a_section_without_a_specimen_keeps_the_page_fallback():
    parsed = ParsedObservation(
        raw_name="Лейкоцити", value_numeric=None, value_text="1-2", comparator=None, unit_raw=None,
        reference_text=None, reference_low=None, reference_high=None, page_number=1,
        evidence_text="", confidence=0.9, section="sediment",
    )
    assert observation_specimen(parsed, "сеча") == "сеча"
    assert observation_specimen(parsed) is None


def test_potassium_is_not_stool(connection):
    """«кал» is matched as a word start: «Калій» is an electrolyte."""
    assert filed(connection, "Калій", value_type="numeric", title="Калій, натрій", unit_raw="ммоль/л") == "potassium"


@pytest.mark.parametrize("raw_name", ["Лейкоцити", "Еритроцити", "Слиз"])
def test_a_smear_row_is_not_a_urinalysis_row(connection, raw_name):
    """A gynaecological smear prints bare «Лейкоцити», «Еритроцити», «Слиз»;
    they were filed under the urine concepts, and through Synevo's learned
    aliases would be again."""
    urine = filed(connection, raw_name, title=URINALYSIS_TITLE, value_text="не виявлені")
    assert CONCEPTS_BY_ID[urine]["category"] == "urinalysis"
    concept_id = filed(connection, raw_name, title=SMEAR_TITLE, value_text="в тяжах слизу 30-50")
    category = connection.execute("SELECT category FROM concepts WHERE id=?", (concept_id,)).fetchone()[0]
    assert concept_id != urine
    assert category == "microbiology"
    # Once the smear's site heading («ТОЧКА 2: VAGINA») reaches the row as its specimen.
    assert filed(connection, raw_name, specimen="VAGINA", value_text="не виявлені") == concept_id


def test_microscopy_on_the_slide_is_per_field_and_the_analyser_count_is_per_microlitre(connection):
    """Synevo's manual sediment «Еритроцити: не виявлені (не виявлені,
    поодинокі в препараті)» joined the analyser's per-µL series; EskuLab's
    «Незмінені еритроцити (NL RBC) 16.4 кл/мкл» joined the per-field one."""
    assert filed(connection, "Еритроцити", title=URINALYSIS_TITLE, value_text="не виявлені",
                 reference_text="не виявлені, поодинокі в препараті") == "urine-erythrocytes-per-high-power-field"
    assert filed(connection, "Незмінені еритроцити (NL RBC)", value_type="numeric", specimen="сеча",
                 unit_raw="кл/мкл", reference_text="жінки < 15 чоловіки < 10") == (
        "urine-erythrocytes-unchanged-per-microlitre")
    assert filed(connection, "Еритроцити не змінені, в п/з", value_text="0-0-1",
                 reference_text="0-2") == "urine-erythrocytes-unchanged"


@pytest.mark.parametrize(
    ("raw_name", "value_type", "expected"),
    [
        ("Загальний Ig E", "numeric", "total-immunoglobulin-e"),
        ("Хелікобактер пілорі, кал", "text", "h-pylori-stool-antigen"),
        ("Залізо сироваткове", "numeric", "serum-iron"),
        ("Протромбіновий час (ПЧ, РТ, сек.)", "numeric", "prothrombin-time"),
        ("Протромбін за Квіком, %", "numeric", "quick-prothrombin-index"),
    ],
)
def test_other_laboratories_spellings_reach_the_existing_concept(connection, raw_name, value_type, expected):
    assert filed(connection, raw_name, value_type=value_type) == expected
    # The stool test keeps its concept with the stool specimen the row carries.
    assert filed(connection, raw_name, value_type=value_type, specimen="кал") == expected


def test_free_t3_in_pg_per_ml_and_total_ige_in_iu_per_ml_convert():
    """Synevo prints FT3 3.40 пг/мл and total IgE in МО/мл; the library bands
    are pmol/L and kU/L, and with no conversion they skipped the value."""
    assert convert_value(3.40, "пг/мл", "pmol/L", "free-triiodothyronine") == pytest.approx(5.22, abs=0.01)
    assert convert_value(5.22, "pmol/L", "пг/мл", "free-triiodothyronine") == pytest.approx(3.40, abs=0.01)
    assert convert_value(38.9, "МО/мл", "kU/L", "total-immunoglobulin-e") == 38.9


def test_stored_rows_move_on_start(tmp_path: Path):
    """The start-up repair reads the stored unit, specimen and title, so the
    white-cell count, the analyser count, the IgE and a coprogram row whose
    stool specimen was stored move without a re-read."""
    settings, user_id, _client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET title=? WHERE id='doc-1'", (URINALYSIS_TITLE,))
        rows = (
            ("wbc", "Лейкоцити (WBC)", 6.84, "10^9 клітин/л", None, "urine-leukocytes"),
            ("nl", "Незмінені еритроцити (NL RBC)", 16.4, "кл/мкл", "сеча", "urine-erythrocytes-unchanged"),
            ("ige", "Загальний Ig E", 38.9, "МО/мл", None, "urine-leukocytes"),
            ("copro", "pH", 6.75, None, "кал", "urine-ph"),
        )
        for row_id, raw_name, value, unit, specimen, old in rows:
            connection.execute(
                """INSERT INTO observations(id, owner_user_id, patient_id, document_id, page_number, concept_id,
                       raw_name, value_type, value_numeric, unit_raw, specimen, verification_status,
                       extraction_method, confidence, evidence_text, parser_version, created_at)
                   VALUES (?, ?, ?, 'doc-1', 1, ?, ?, 'numeric', ?, ?, ?, 'extracted', 'lab_api', 0.9, ?,
                           'test', ?)""",
                (row_id, user_id, f"patient-{user_id}", old, raw_name, value, unit, specimen, raw_name, utc_now()),
            )
        repair_observation_semantics(connection)
        moved = dict(connection.execute(
            "SELECT id, concept_id FROM observations WHERE id IN ('wbc', 'nl', 'ige', 'copro')"
        ).fetchall())
        assert moved == {
            "wbc": "white-blood-cell-count",
            "nl": "urine-erythrocytes-unchanged-per-microlitre",
            "ige": "total-immunoglobulin-e",
            "copro": "stool-ph",
        }
        # Idempotent: a second start finds nothing to move.
        assert repair_observation_semantics(connection) == 0


def test_the_new_concept_is_named_and_sourced():
    name = "Urine erythrocytes, unchanged (per microlitre)"
    assert name in {str(item["name"]) for item in CONCEPT_DEFINITIONS}
    assert CONCEPT_NAMES_UK[name]
    library = json.loads(Path(LIBRARY_PATH).read_text(encoding="utf-8"))
    entry = next(item for item in library["analytes"] if item["concept_id"] == stable_concept_id(name))
    assert entry["kind"] == "no_universal_target" and entry["source_ids"]
    assert entry["uk"]["name"] and entry["uk"]["short_description"]


CONCEPTS_BY_ID = {stable_concept_id(str(item["name"])): item for item in CONCEPT_DEFINITIONS}
