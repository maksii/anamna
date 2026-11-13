"""Diagnoses read from documents: the text parsers, the candidates, grouping, accepting and dismissing.

The database is a temporary one; no AI is called.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from anamna import diagnoses, diagnosis_candidates, icd10
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


# --- conclusions, word for word -----------------------------------------------------

NORMAL_ECHO = (
    "Лівий шлуночок не розширений, стінки не потовщені. Функція клапанів звичайна. "
    "Рідини в порожнині перикарду не виявлено."
)
LONG_PRESERVED = (
    "Гіпертрофія лівого шлуночка помірного ступеня з частково збереженими скороченнями стінок серця "
    "та ознаками перевантаження тиском"
)


def test_a_conclusion_gives_one_item_per_statement_and_a_question_mark_makes_it_provisional():
    items = diagnosis_candidates.parse_conclusion(
        "Плантарний фасциїт правої стопи. Артрит. Реактивний артрит, гіперурикемія?"
    )
    assert [(item["name"], item["certainty"]) for item in items] == [
        ("Плантарний фасциїт правої стопи", "confirmed"),
        ("Артрит", "confirmed"),
        ("Реактивний артрит, гіперурикемія", "provisional"),
    ]
    assert all(item["code"] == "" for item in items)


def test_a_sentence_end_after_an_abbreviation_or_before_a_bracket_does_not_split_the_statement():
    items = diagnosis_candidates.parse_conclusion(
        "МР-ознаки хондромаляції надколінника І ст. (за Outerbridge). Протрузія диска L5-S1."
    )
    assert [item["name"] for item in items] == [
        "МР-ознаки хондромаляції надколінника І ст. (за Outerbridge)",
        "Протрузія диска L5-S1",
    ]


def test_a_normal_echo_conclusion_gives_nothing():
    assert diagnosis_candidates.parse_conclusion(NORMAL_ECHO) == []


@pytest.mark.parametrize("text", ["Синусовий ритм, вольтаж збережений. ЕКГ в межах норми.", "Normal Sinus Rhythm"])
def test_a_normal_ecg_statement_gives_nothing(text):
    assert diagnosis_candidates.parse_conclusion(text) == []


def test_a_preserved_word_before_a_noun_is_kept_because_the_statement_also_holds_a_finding():
    [item] = diagnosis_candidates.parse_conclusion(LONG_PRESERVED)
    assert item["name"] == LONG_PRESERVED


def test_a_conclusion_that_starts_with_complaints_or_names_icpc_gives_nothing():
    assert diagnosis_candidates.parse_conclusion("Скарги: A44 вакцинація. Огляд: без змін.") == []
    assert diagnosis_candidates.parse_conclusion("Вакцинація; ICPC-2: A44") == []
    assert diagnosis_candidates.parse_conclusion(None) == []


def test_a_coded_piece_is_left_to_the_code_reader_and_a_bare_label_is_dropped():
    assert diagnosis_candidates.parse_conclusion("L02.0 - Абсцес шкіри обличчя; Клінічний діагноз") == []


def test_a_statement_the_same_document_already_codes_is_not_offered_again():
    [item] = diagnosis_candidates.parse_conclusion(
        "Правобічний сіалоаденіт; Реактивна лімфаденопатія", skip_codes={"K11.2"},
    )
    assert item["name"] == "Реактивна лімфаденопатія"


def test_a_list_number_is_not_part_of_the_name_and_an_instruction_is_dropped():
    [item] = diagnosis_candidates.parse_conclusion(
        "1 Морфологія відповідає зубчастій аденомі; 2. Необхідна кореляція з клінічними даними"
    )
    assert item["name"] == "Морфологія відповідає зубчастій аденомі"


def test_a_statement_longer_than_200_characters_is_cut_with_an_ellipsis():
    [item] = diagnosis_candidates.parse_conclusion("Гіпертрофія стінок " * 20)
    assert len(item["name"]) <= 200
    assert item["name"].endswith("…")


def test_the_same_statement_twice_is_offered_once():
    assert [item["name"] for item in diagnosis_candidates.parse_conclusion("Артрит. Артрит.")] == ["Артрит"]


@pytest.mark.parametrize(
    "text",
    [
        "Синуси вільні.",
        "Контури діафрагми чіткі, рівні.",
        "Газовий міхур шлунка розташований типово.",
        "На рентгенограмі ОГК в прямій проекції легеневі поля прозорі.",
        "Корені легень структурні, тяжисті.",
        "Серце - вікові особливості.",
        "Легеневі поля без вогнищево-інфільтративних змін.",
        "Бакпосів калу на дисбактеріоз. Чутливість до антибіотиків ДДМ.",
        "Копрограма від 18.05.2026р: кал неоформлений",
        "Антимікотикограма від 18.05.2026р: виявлено",
    ],
)
def test_a_description_of_a_normal_finding_or_a_study_heading_gives_nothing(text):
    assert diagnosis_candidates.parse_conclusion(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "Легеневий рисунок збагачений за рахунок судинного компоненту, перибронхіальних змін.",
        "Незначні сольові нашарування в нирках без порушення уродинаміки.",
        "Протрузія м/х диска L5-L6.",
        "Хронічний панкреатит.",
        "Гостра анальна тріщина.",
        "Вільна рідина в черевній порожнині.",
        "Типові ознаки гострого апендициту.",
        "Структурні зміни печінки.",
    ],
)
def test_a_finding_that_only_resembles_a_normal_word_is_still_one_item(text):
    [item] = diagnosis_candidates.parse_conclusion(text)
    assert item["name"] == text.rstrip(".")


# The summary of a real cardiology visit ran two diagnoses into one line: E09.9 took the whole
# line as its name and I11.9 was never offered.
RUN_ON = (
    "E09.9 - Проміжна гіперглікемія без ускладнень преддіабет? Клінічний діагноз: I11.9 - Гіпертензивна "
    "(гіпертонічна) хвороба серця без (застійної) серцевої недостатності"
)


def test_a_second_diagnosis_label_inside_a_piece_starts_a_second_diagnosis():
    items = diagnosis_candidates.parse_summary(RUN_ON)
    assert [(item["code"], item["certainty"]) for item in items] == [("E09.9", "provisional"), ("I11.9", "confirmed")]
    assert items[0]["name"] == "Проміжна гіперглікемія без ускладнень преддіабет"


def test_the_coded_lines_of_a_document_are_read_even_when_it_starts_with_complaints():
    text = (
        "Скарги: набряк брови\nПОПЕРЕДНІЙ ДІАГНОЗ:\n"
        "L02.0 - Абсцес, фурункул та карбункул шкіри обличчя правої брови\n"
        "S31 - Часткове медичне обстеження"
    )
    assert diagnosis_candidates.parse_summary(text) == []
    assert [item["code"] for item in diagnosis_candidates.coded_lines(text)] == ["L02.0"]


MRI_TEXT = (
    "Опис:\nТіла хребців неправильної конфігурації.\nВисновок:\n"
    "Дегенеративні зміни хребта у вигляді остеохондрозу, протрузій\nм/х дисків L4-L5.\n"
    "S- подібний сколіоз.\nРекомендовано: консультація невролога\n"
    "До уваги!\nВисновок не є остаточним діагнозом та потребує консультації з лікуючим лікарем."
)


def test_a_conclusion_runs_to_the_recommendation_and_a_wrapped_line_is_joined():
    assert diagnosis_candidates.conclusion_text(MRI_TEXT) == (
        "Дегенеративні зміни хребта у вигляді остеохондрозу, протрузій м/х дисків L4-L5.\nS- подібний сколіоз."
    )


def test_a_conclusion_stops_at_a_labelled_field_and_the_next_heading_starts_another():
    text = (
        "Клінічний діагноз: явища ілеїту\nКлінічні дані:\nНадсилається: шматочки тканини\n"
        "Гістологічний висновок:\nХронічний неактивний ілеїт."
    )
    assert diagnosis_candidates.conclusion_text(text) == "явища ілеїту\nХронічний неактивний ілеїт."


def test_a_text_without_a_conclusion_heading_has_no_conclusion():
    assert diagnosis_candidates.conclusion_text("Скарги: печія\nОгляд: живіт м'який") == ""


def test_a_label_is_not_part_of_the_name_and_an_abbreviation_alone_is_a_diagnosis():
    found = diagnosis_candidates.parse_conclusion("Супутній: Комбінований геморой ІІ ст.\nПопередній діагноз: СПК")
    assert [item["name"] for item in found] == ["Комбінований геморой ІІ ст", "СПК"]


def test_a_code_the_catalogue_does_not_know_is_offered_as_written():
    assert icd10.entry("F90.2") is None
    [item] = diagnosis_candidates.parse_conclusion("Попередній діагноз: F90.2 Розлад з дефіцитом уваги.")
    assert item["name"] == "F90.2 Розлад з дефіцитом уваги"


@pytest.mark.parametrize(
    "text",
    [
        "Призначено німесил на 3 дні, флемоксин 1000 мг двічі на день",
        "лікування Нурофен форте і кларитин 5 днів",
        "щеплення проведено (деталі у записі вакцинації)",
        "Цитологія на атипові клітини (зішкріб, мазок на склі): Тип II",
        "Аналіз у/г мазка на мікрофлору (на склі): Ступінь чистоти III",
        "КВР високий",
        "Патологоанатом рекомендує зіставити результат із клінічними даними",
        "Хворіє близько тижня, раніше не лікувався",
    ],
)
def test_a_prescription_a_vaccination_a_test_or_a_remark_is_not_a_diagnosis(text):
    assert diagnosis_candidates.parse_conclusion(text) == []


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


def test_a_duplicate_document_is_not_read(db):
    finding(db, db.docs["dup"], TWO_CODED)
    assert collect(db) == 0


def test_a_laboratory_report_is_read_like_any_other_document(db):
    finding(db, db.docs["lab"], TWO_CODED)
    assert collect(db) == 2


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


# --- conclusions in the database -----------------------------------------------------

MRI_KEY = "n:протрузія диска l5-s1"


def make_mri(db) -> str:
    """The laboratory document of the fixture as a study report (MRI)."""
    db.connection.execute("UPDATE documents SET clinical_type = 'radiology_mri' WHERE id = ?", (db.docs["lab"],))
    db.connection.commit()
    return db.docs["lab"]


def text_rows(db, document_id: str) -> list[tuple]:
    rows = db.connection.execute(
        "SELECT method, code, code_printed, name, certainty, state FROM diagnosis_candidates "
        "WHERE document_id = ? AND method = 'text' ORDER BY name",
        (document_id,),
    ).fetchall()
    return [tuple(row) for row in rows]


def test_a_conclusion_of_a_study_gives_one_text_candidate_and_collecting_again_does_not_repeat_it(db):
    mri = make_mri(db)
    finding(db, mri, "Протрузія диска L5-S1.")
    collect(db)
    collect(db)
    assert text_rows(db, mri) == [("text", "", 0, "Протрузія диска L5-S1", "confirmed", "new")]
    [group] = diagnosis_candidates.groups(db.connection, db.alpha, locale="en")
    assert group["key"] == MRI_KEY
    assert group["code"] == ""
    assert group["methods"] == ["text"]


def test_an_uncoded_consultation_diagnosis_is_offered_word_for_word(db):
    finding(db, db.docs["jan"], NO_CODE)
    collect(db)
    found = {group["name"]: group["certainty"] for group in diagnosis_candidates.groups(db.connection, db.alpha, locale="en")}
    assert found == {
        "Правобічний сіалоаденіт": "confirmed",
        "Реактивна підщелепна лімфаденопатія": "confirmed",
        "Епідемічний паротит": "provisional",
    }


def test_a_dismissed_text_candidate_stays_dismissed_after_collect(db):
    mri = make_mri(db)
    finding(db, mri, "Протрузія диска L5-S1.")
    collect(db)
    assert diagnosis_candidates.dismiss(db.connection, db.alpha, [MRI_KEY]) == 1
    db.connection.commit()
    collect(db)
    assert offered(db) == {}
    assert [group["key"] for group in diagnosis_candidates.dismissed(db.connection, db.alpha, locale="en")] == [MRI_KEY]
    assert text_rows(db, mri) == [("text", "", 0, "Протрузія диска L5-S1", "confirmed", "dismissed")]


def test_a_document_the_ai_reader_has_read_gets_no_conclusion_candidates(db):
    mri = make_mri(db)
    db.connection.execute(
        "INSERT INTO diagnosis_scans(document_id, owner_user_id, scanned_at, model, found) "
        "VALUES (?, ?, '2026-01-01T00:00:00+00:00', 'test/model', 0)",
        (mri, db.alpha),
    )
    db.connection.commit()
    finding(db, mri, "Протрузія диска L5-S1.")
    collect(db)
    assert text_rows(db, mri) == []


def test_a_finding_with_empty_summaries_and_text_does_not_crash(db):
    finding(db, db.docs["jan"], "", text="")
    assert collect(db) == 0


def native_page(db, document_id: str, text: str) -> None:
    db.connection.execute(
        "INSERT INTO document_pages(document_id, page_number, native_text, extraction_method, native_char_count) "
        "VALUES (?, 1, ?, 'native', ?)",
        (document_id, text, len(text)),
    )
    db.connection.commit()


LIPOMA_TEXT = (
    "Особливості обстеження – підшкірно візуалізується гіперехогенний утвір з чітким рівним контуром,\n" * 5
    + "ЗАКЛЮЧЕННЯ: Ліпоми лівої руки\nРекомендовано : спостереження в динаміці"
)


def test_a_native_document_offers_its_conclusion_and_only_the_summary_statements_it_says(db):
    study = make_mri(db)
    native_page(db, study, LIPOMA_TEXT)
    finding(db, study, "УЗД м'яких тканин: утвір 8,3 x 4,5 мм, розцінений як ліпома. Ліпоми лівої руки.", text=LIPOMA_TEXT)
    collect(db)
    assert [row[3] for row in text_rows(db, study)] == ["Ліпоми лівої руки"]


def test_a_scanned_document_without_native_text_is_still_read_from_its_summary(db):
    study = make_mri(db)
    finding(db, study, "Протрузія диска L5-S1.", text="Протрузiя диска L5-SI (OCR)")
    collect(db)
    assert [row[3] for row in text_rows(db, study)] == ["Протрузія диска L5-S1"]


def test_collect_reads_the_coded_diagnosis_lines_of_the_document_text(db):
    finding(
        db, db.docs["jan"], "Фурункул правої брови.",
        text="Скарги: набряк брови\nПОПЕРЕДНІЙ ДІАГНОЗ:\nL02.0 - Абсцес, фурункул та карбункул шкіри обличчя правої брови",
    )
    collect(db)
    assert offered(db)["L02.0"]["code_printed"] is True
