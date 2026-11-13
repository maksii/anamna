"""Diagnoses read from documents: the text parsers, the candidates, grouping, accepting and dismissing.

The database is a temporary one; no AI is called.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from anamna import diagnoses, diagnosis_candidates
from anamna.db import connect, migrate
from anamna.security import create_user
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for

TWO_CODED = (
    "I11.9 - Гіпертензивна (гіпертонічна) хвороба серця без (застійної) серцевої недостатності "
    "Гіпертонічна хвороба Іст, 1ст, КВР помірний СН 0; E78.2 - Змішана гіперліпідемія;"
)
SKIN = (
    "L82 - Себорейний кератоз , кератома лівої вушної раковини; B07 - Вірусні бородавки; "
    "D23.5 - Інші доброякісні новоутворення шкіри тулуба , папіломи"
)
ABSCESS = "L02.0 - Абсцес, фурункул та карбункул шкіри обличчя правої брови; Клінічний діагноз"
HEADACHE = "G44.2 Головний біль, пов'язаний з перенапруженням"
COMPLAINT = "Скарги: A44 вакцинація Бустрікс. Огляд: Загальний стан - задовільний."
ICPC_ONLY = "A44 вакцинація Бустрікс"
ICPC_COMPLIANCE = (
    "Підтримання здоров'я / профілактика; Код ICPC2 МКХ-10 Z27.9 - Необхідність імунізації проти "
    "неуточнених комбінацій інфекційних хвороб; Опис: Гепатиту А+В"
)
RANGE = "L20-L30 Дерматит та екзема"
NO_CODE = "Правобічний сіалоаденіт; Реактивна підщелепна лімфаденопатія; Епідемічний паротит?"
PROVISIONAL = "K29.5 - Хронічний гастрит?"
CODED_LINE = "Дата консультації: 21.07.2018\nКод МКХ Х: K11.2\nКлінічний діагноз:\nПравобічний сіалоаденіт"


def test_a_summary_with_two_coded_diagnoses_gives_both():
    items = diagnosis_candidates.parse_summary(TWO_CODED)
    assert [(item["code"], item["certainty"]) for item in items] == [("I11.9", "confirmed"), ("E78.2", "confirmed")]
    assert items[1]["name"] == "Змішана гіперліпідемія"


def test_skin_diagnoses_with_a_dash_and_a_comma_are_all_kept():
    assert [item["code"] for item in diagnosis_candidates.parse_summary(SKIN)] == ["L82", "B07", "D23.5"]


def test_a_code_with_a_label_after_it_gives_one_item():
    assert [item["code"] for item in diagnosis_candidates.parse_summary(ABSCESS)] == ["L02.0"]


def test_a_code_with_no_dash_before_the_name_is_read():
    assert [item["code"] for item in diagnosis_candidates.parse_summary(HEADACHE)] == ["G44.2"]


def test_a_summary_that_starts_with_complaints_gives_nothing():
    assert diagnosis_candidates.parse_summary(COMPLAINT) == []


def test_an_icpc_code_whose_name_shares_no_stem_with_its_title_is_not_a_diagnosis():
    assert diagnosis_candidates.parse_summary(ICPC_ONLY) == []


def test_a_reason_for_encounter_code_is_not_a_condition():
    assert diagnosis_candidates.parse_summary(ICPC_COMPLIANCE) == []


def test_a_range_of_codes_is_skipped():
    assert diagnosis_candidates.parse_summary(RANGE) == []


def test_a_summary_without_codes_gives_nothing_for_the_code_reader():
    assert diagnosis_candidates.parse_summary(NO_CODE) == []


def test_a_question_mark_makes_the_diagnosis_provisional():
    [item] = diagnosis_candidates.parse_summary(PROVISIONAL)
    assert item["code"] == "K29.5"
    assert item["certainty"] == "provisional"
    assert item["quote"] == PROVISIONAL


def test_a_name_is_cut_to_200_characters_and_a_quote_to_400():
    long_name = "Гіпертензивна хвороба " * 30
    [item] = diagnosis_candidates.parse_summary(f"I11 - {long_name}")
    assert len(item["name"]) == 200
    assert len(item["quote"]) <= 400


def test_a_cyrillic_look_alike_code_is_folded_to_latin():
    [item] = diagnosis_candidates.parse_summary("К11.2 - Сіалоаденіт")
    assert item["code"] == "K11.2"


def test_a_coded_line_gives_the_code_with_no_name_and_the_line_as_quote():
    [item] = diagnosis_candidates.parse_coded_line(CODED_LINE)
    assert item == {"code": "K11.2", "name": "", "certainty": "confirmed", "quote": "Код МКХ Х: K11.2"}


def test_coded_lines_take_several_codes_separated_by_commas_and_skip_icpc_and_non_conditions():
    text = "МКХ-10: E78.2, I10\nКод ICPC2 МКХ: K11.2\nМКХ: Z27.9\nМКХ-10: L20-L30"
    assert [item["code"] for item in diagnosis_candidates.parse_coded_line(text)] == ["E78.2", "I10"]


def test_codes_printed_in_a_text_are_the_normalized_codes_it_names():
    assert diagnosis_candidates.codes_in("Код МКХ-10: К11,2 та E78.2; L20-L30") == {"K11.2", "E78.2", "L20", "L30"}


# --- the database --------------------------------------------------------------------

CONSULTATIONS = {
    "jan": ("consult-jan.txt", "2025-01-10"),
    "mar": ("consult-mar.txt", "2025-03-05"),
    "may": ("consult-may.txt", "2025-05-20"),
    "dup": ("consult-dup.txt", "2025-06-01"),
    "lab": ("lab.txt", "2025-06-02"),
}


@pytest.fixture
def db(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    alpha_patient = seed_patient(settings, alpha, "Alpha")
    beta_patient = seed_patient(settings, beta, "Beta")
    docs = {key: seed_document(settings, alpha, alpha_patient, key, filename) for key, (filename, _day) in CONSULTATIONS.items()}
    connection = connect(settings)
    for key, (_filename, day) in CONSULTATIONS.items():
        clinical = "laboratory" if key == "lab" else "consultation"
        connection.execute(
            "UPDATE documents SET clinical_type = ?, report_date = ? WHERE id = ?", (clinical, day, docs[key])
        )
    connection.execute("UPDATE documents SET duplicate_of_document_id = ? WHERE id = ?", (docs["jan"], docs["dup"]))
    connection.commit()
    yield SimpleNamespace(
        connection=connection, alpha=alpha, beta=beta, alpha_patient=alpha_patient,
        beta_patient=beta_patient, docs=docs,
    )
    connection.close()


def finding(db, document_id: str, summary: str, *, area: str = "cardiology", text: str = "") -> None:
    db.connection.execute(
        """INSERT INTO clinical_findings(id, owner_user_id, patient_id, document_id, page_number,
               health_area, title, summary_en, summary_uk, original_text, status, created_at)
           VALUES (?, ?, ?, ?, 1, ?, ?, '', ?, ?, 'information', '2025-06-01T00:00:00+00:00')""",
        (str(uuid.uuid4()), db.alpha, db.alpha_patient, document_id, area, area, summary, text),
    )
    db.connection.commit()


def collect(db, owner=None) -> int:
    count = diagnosis_candidates.collect(db.connection, owner or db.alpha)
    db.connection.commit()
    return count


def offered(db, owner=None) -> dict:
    found = diagnosis_candidates.groups(db.connection, owner or db.alpha, locale="en")
    return {group["key"]: group for group in found}


def add_diagnosis(db, code: str, name: str = "") -> str:
    return diagnoses.create(
        db.connection, db.alpha, db.alpha_patient,
        {
            "code": code, "name": name, "status": "active", "certainty": "confirmed",
            "diagnosed_on": None, "resolved_on": None, "dates_approximate": 1,
            "clinician": "", "document_id": None, "notes": "",
        },
        origin="person",
    )


def test_collect_inserts_each_diagnosis_once_and_a_second_run_inserts_nothing(db):
    finding(db, db.docs["jan"], TWO_CODED, area="cardiology")
    finding(db, db.docs["jan"], TWO_CODED, area="lipids")
    assert collect(db) == 2
    assert collect(db) == 0


def test_a_duplicate_document_and_a_laboratory_report_are_not_read(db):
    finding(db, db.docs["dup"], TWO_CODED)
    finding(db, db.docs["lab"], TWO_CODED)
    assert collect(db) == 0


def test_the_same_code_in_two_documents_is_one_group_with_its_dates(db):
    finding(db, db.docs["jan"], "E78.2 - Змішана гіперліпідемія;")
    finding(db, db.docs["may"], "E78.2 - Змішана гіперліпідемія;")
    collect(db)

    [group] = diagnosis_candidates.groups(db.connection, db.alpha, locale="en")

    assert group["key"] == "E78.2"
    assert group["code"] == "E78.2"
    assert group["title"] == "Mixed hyperlipidaemia"
    assert group["name"] == "Змішана гіперліпідемія"
    assert group["mentions"] == 2
    assert group["first_date"] == "2025-01-10"
    assert group["last_date"] == "2025-05-20"
    assert group["certainty"] == "confirmed"
    assert group["code_printed"] is True
    assert group["methods"] == ["code"]
    assert group["existing_id"] is None
    assert group["documents"] == [
        {"id": db.docs["may"], "date": "2025-05-20"},
        {"id": db.docs["jan"], "date": "2025-01-10"},
    ]


def test_existing_id_is_the_owners_diagnosis_with_the_same_code(db):
    dx_id = add_diagnosis(db, "E78.2")
    finding(db, db.docs["jan"], "E78.2 - Змішана гіперліпідемія;")
    collect(db)
    assert offered(db)["E78.2"]["existing_id"] == dx_id


def test_accept_creates_one_diagnosis_from_the_document(db):
    finding(db, db.docs["jan"], "E78.2 - Змішана гіперліпідемія;")
    finding(db, db.docs["may"], "E78.2 - Змішана гіперліпідемія;")
    collect(db)

    touched = diagnosis_candidates.accept(db.connection, db.alpha, db.alpha_patient, ["E78.2"])

    assert len(touched) == 1
    row = db.connection.execute(
        "SELECT code, name, origin, status, certainty, diagnosed_on, dates_approximate, document_id, resolved_on "
        "FROM diagnoses WHERE owner_user_id = ?",
        (db.alpha,),
    ).fetchall()
    assert [tuple(item) for item in row] == [
        ("E78.2", "Змішана гіперліпідемія", "document", "active", "confirmed", "2025-01-10", 1, db.docs["may"], None),
    ]
    states = db.connection.execute(
        "SELECT DISTINCT state, diagnosis_id FROM diagnosis_candidates WHERE owner_user_id = ?", (db.alpha,)
    ).fetchall()
    assert [tuple(item) for item in states] == [("accepted", touched[0])]
    assert offered(db) == {}


def test_accept_of_a_group_with_an_existing_diagnosis_links_and_creates_nothing(db):
    dx_id = add_diagnosis(db, "E78.2")
    finding(db, db.docs["jan"], "E78.2 - Змішана гіперліпідемія;")
    collect(db)

    touched = diagnosis_candidates.accept(db.connection, db.alpha, db.alpha_patient, ["E78.2"])

    assert touched == [dx_id]
    assert db.connection.execute("SELECT COUNT(*) FROM diagnoses WHERE owner_user_id = ?", (db.alpha,)).fetchone()[0] == 1
    linked = db.connection.execute("SELECT state, diagnosis_id FROM diagnosis_candidates").fetchone()
    assert tuple(linked) == ("accepted", dx_id)


def test_a_bare_code_is_accepted_with_an_empty_name(db):
    finding(db, db.docs["jan"], "", text="Код МКХ Х: K11.2")
    collect(db)
    [group] = diagnosis_candidates.groups(db.connection, db.alpha, locale="en")
    assert group["name"] == "Sialoadenitis"

    diagnosis_candidates.accept(db.connection, db.alpha, db.alpha_patient, ["K11.2"])

    row = db.connection.execute("SELECT code, name FROM diagnoses WHERE owner_user_id = ?", (db.alpha,)).fetchone()
    assert tuple(row) == ("K11.2", "")


def test_dismiss_hides_the_group_and_a_later_mention_arrives_dismissed_until_restored(db):
    finding(db, db.docs["jan"], "E78.2 - Змішана гіперліпідемія;")
    collect(db)

    assert diagnosis_candidates.dismiss(db.connection, db.alpha, ["E78.2"]) == 1
    db.connection.commit()
    assert offered(db) == {}
    assert [group["key"] for group in diagnosis_candidates.dismissed(db.connection, db.alpha, locale="en")] == ["E78.2"]

    finding(db, db.docs["mar"], "E78.2 - Змішана гіперліпідемія;")
    assert collect(db) == 1
    state = db.connection.execute(
        "SELECT state FROM diagnosis_candidates WHERE document_id = ?", (db.docs["mar"],)
    ).fetchone()[0]
    assert state == "dismissed"
    assert offered(db) == {}
    [dismissed] = diagnosis_candidates.dismissed(db.connection, db.alpha, locale="en")
    assert dismissed["mentions"] == 2

    assert diagnosis_candidates.restore(db.connection, db.alpha, ["E78.2"]) == 1
    db.connection.commit()
    assert offered(db)["E78.2"]["mentions"] == 2
    assert diagnosis_candidates.dismissed(db.connection, db.alpha, locale="en") == []


def test_mentions_of_an_accepted_diagnosis_are_listed_oldest_first(db):
    finding(db, db.docs["may"], "E78.2 - Змішана гіперліпідемія;")
    finding(db, db.docs["jan"], "E78.2 - Змішана гіперліпідемія;")
    collect(db)
    dx_id = diagnosis_candidates.accept(db.connection, db.alpha, db.alpha_patient, ["E78.2"])[0]

    found = diagnosis_candidates.mentions(db.connection, db.alpha, dx_id)

    assert [(item["document_id"], item["date"], item["method"]) for item in found] == [
        (db.docs["jan"], "2025-01-10", "code"),
        (db.docs["may"], "2025-05-20", "code"),
    ]


def test_another_owner_sees_and_accepts_nothing(db):
    finding(db, db.docs["jan"], "E78.2 - Змішана гіперліпідемія;")
    collect(db)

    assert offered(db, db.beta) == {}
    assert diagnosis_candidates.accept(db.connection, db.beta, db.beta_patient, ["E78.2"]) == []
    assert diagnosis_candidates.dismiss(db.connection, db.beta, ["E78.2"]) == 0
    assert offered(db)["E78.2"]["mentions"] == 1
