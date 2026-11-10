"""The documents that fit a medicine entry: name terms, labelled lines, snippets and the search itself.

The database is a temporary one, migrated and seeded through the helpers the other
document tests use.  Each test asserts one rule of the search.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from anamna import factor_documents as fd
from anamna.db import connect, migrate
from anamna.ingest.pipeline import ensure_vendor
from anamna.ingest.text import search_key
from anamna.security import create_user
from test_web_security import PASSWORD, seed_patient, settings_for

DIOKOR = "Діокор соло 160 таблетки, в/плів. обол. по 160 мг №30"


def add_document(
    connection,
    owner: str,
    patient: str,
    doc_id: str,
    *,
    title: str,
    vendor: str,
    pages: list[str],
    report_date: str | None = None,
    imported_at: str = "2025-01-01T08:00:00+00:00",
    duplicate_of: str | None = None,
    clinical_type: str = "consultation",
) -> str:
    """One document with its pages and its search row, the way the pipeline stores them."""
    vendor_id = ensure_vendor(connection, vendor, None)
    connection.execute(
        """INSERT INTO documents(
               id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
               mime_type, byte_size, sha256, page_count, title, clinical_type,
               extraction_strategy, classification_confidence, imported_at, status,
               report_date, duplicate_of_document_id
           ) VALUES (?, ?, ?, ?, ?, ?, 'text/plain', 1, ?, ?, ?, ?, 'native_text', 1, ?, 'final', ?, ?)""",
        (
            doc_id, owner, patient, vendor_id, f"{doc_id}.txt", f"{doc_id}.txt", f"sha-{doc_id}",
            len(pages), title, clinical_type, imported_at, report_date, duplicate_of,
        ),
    )
    for number, text in enumerate(pages, start=1):
        connection.execute(
            """INSERT INTO document_pages(document_id, page_number, native_text, extraction_method, native_char_count)
               VALUES (?, ?, ?, 'native_pdf_text', ?)""",
            (doc_id, number, text, len(text)),
        )
    content = "\n".join(pages)
    connection.execute(
        "INSERT INTO search_index(document_id, owner_user_id, content, content_folded) VALUES (?, ?, ?, ?)",
        (doc_id, owner, content, search_key(content)),
    )
    return doc_id


@pytest.fixture
def db(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    alpha_patient = seed_patient(settings, alpha, "Alpha")
    beta_patient = seed_patient(settings, beta, "Beta")
    connection = connect(settings)
    add = lambda *args, **kwargs: add_document(connection, *args, **kwargs)  # noqa: E731
    ids = SimpleNamespace(
        # Mentions the medicine, dated, with a doctor, a diagnosis and a clinic.
        cardio=add(
            alpha, alpha_patient, "doc-cardio", title="Виписка кардіолога", vendor="Clinic North",
            report_date="2025-02-10",
            pages=[
                "Клінічний центр Північ\n"
                "Лікар: Петренко Олена Іванівна\n"
                "Діагноз: Гіпертонічна хвороба II стадії.\n"
                "Рекомендовано Діокор соло 160 мг щодня."
            ],
        ),
        # Mentions the medicine and is the newest mention.
        note=add(
            alpha, alpha_patient, "doc-note", title="Призначення", vendor="Clinic North",
            report_date="2025-03-01", pages=["Діокор соло 160 мг, за призначенням лікаря"],
        ),
        # Does not mention the medicine, but its title does.
        listing=add(
            alpha, alpha_patient, "doc-list", title="Список Діокор", vendor="Lab Central",
            report_date="2025-06-01", pages=["Пацієнт, рецепт №12"], clinical_type="laboratory",
        ),
        labs=add(
            alpha, alpha_patient, "doc-labs", title="Аналізи крові", vendor="Lab Central",
            report_date="2025-04-01", pages=["Глюкоза 5.1 ммоль/л\nХолестерин 5.0\nТромбоцити 1002"],
            clinical_type="laboratory",
        ),
        ultrasound=add(
            alpha, alpha_patient, "doc-usg", title="УЗД 100% норма", vendor="Clinic North",
            report_date="2025-05-20", pages=["Печінка 100% норма"],
        ),
        underscore=add(
            alpha, alpha_patient, "doc-under", title="Файл_тест", vendor="Lab Central",
            report_date="2025-01-15", pages=["Значення a_b збережено"],
        ),
        wildcard=add(
            alpha, alpha_patient, "doc-wild", title="Файл Ф", vendor="Lab Central",
            report_date="2025-01-20", pages=["Значення axb збережено"],
        ),
        # No report date: dated is False and the date is the import date.
        undated=add(
            alpha, alpha_patient, "doc-old", title="", vendor="Clinic North",
            imported_at="2024-12-15T09:00:00+00:00",
            pages=["Валсартан 80 мг, 1 таблетка на день.\nЛікар: Сидоренко Марія"],
        ),
        duplicate=add(
            alpha, alpha_patient, "doc-copy", title="Виписка кардіолога (копія)", vendor="Clinic North",
            report_date="2025-02-11", pages=["Діокор соло 160 мг"], duplicate_of="doc-cardio",
        ),
        other=add(
            beta, beta_patient, "doc-beta", title="Діокор чужий", vendor="Lab Central",
            report_date="2025-02-12", pages=["Діокор соло 160 мг"],
        ),
    )
    connection.commit()
    yield SimpleNamespace(connection=connection, alpha=alpha, beta=beta, ids=ids)
    connection.close()


def found(rows) -> list[str]:
    return [row["id"] for row in rows]


# name_terms ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("name", "substance", "expected"),
    [
        (DIOKOR, "валсартан", ["Діокор соло", "Діокор", "валсартан"]),
        ("Аспірин кардіо", "", ["Аспірин кардіо", "Аспірин"]),
        ("D3", "", []),
        ("Ibuprofen", "ibuprofen", ["Ibuprofen"]),
        ("", "амлодипін, валсартан", ["амлодипін", "валсартан"]),
    ],
)
def test_name_terms(name, substance, expected):
    assert fd.name_terms(name, substance) == expected


# doctor_in and diagnosis_in -----------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Лікар: Петренко Олена Іванівна", "Петренко Олена Іванівна"),
        ("Лікар-кардіолог: Шевченко О.П.", "Шевченко О.П."),
        ("Лікар пояснив ризики", ""),
        ("лікар: _______", ""),
        ("Doctor: Anna Kovalenko", "Anna Kovalenko"),
        ("Лікар: Петренко Олена Іванівна   Підпис", "Петренко Олена Іванівна"),
        ("Лікар: Шевченко Олена Петрівна.", "Шевченко Олена Петрівна"),
    ],
)
def test_doctor_in(text, expected):
    assert fd.doctor_in(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Діагноз: Гіпертонічна хвороба.", "Гіпертонічна хвороба"),
        ("Заключний діагноз:   Гострий   бронхіт;", "Гострий бронхіт"),
        ("Diagnosis: Asthma", "Asthma"),
        ("Діагноз: ab", ""),
        ("Без діагнозу", ""),
    ],
)
def test_diagnosis_in(text, expected):
    assert fd.diagnosis_in(text) == expected


# snippet -------------------------------------------------------------------

def test_snippet_returns_a_short_matching_line():
    text = "Перший рядок\nДіокор соло 160 мг\nІнший рядок"
    assert fd.snippet(text, ["Діокор соло"]) == "Діокор соло 160 мг"


def test_snippet_cuts_a_long_line_around_the_match():
    line = " ".join(["слово"] * 60) + " Діокор соло " + " ".join(["слово"] * 60)
    result = fd.snippet(line, ["Діокор соло"])
    assert result.startswith(fd._ELLIPSIS) and result.endswith(fd._ELLIPSIS)
    assert "Діокор соло" in result
    assert len(result) <= fd.SNIPPET_CHARS + 2


def test_snippet_is_empty_without_a_match():
    assert fd.snippet("abc", ["xyz"]) == ""


# search: name -------------------------------------------------------------

def test_name_returns_only_mentions_newest_first(db):
    rows = fd.search(db.connection, db.alpha, name=DIOKOR)
    assert found(rows) == [db.ids.note, db.ids.cardio]
    assert all(row["mentions"] for row in rows)
    assert "Діокор соло" in rows[0]["snippet"]


def test_substance_brings_in_its_documents(db):
    rows = fd.search(db.connection, db.alpha, name=DIOKOR, substance="валсартан")
    assert found(rows) == [db.ids.note, db.ids.cardio, db.ids.undated]


def test_name_nothing_mentions_returns_most_recent(db):
    rows = fd.search(db.connection, db.alpha, name="Метформін 500 мг")
    assert found(rows)[:3] == [db.ids.listing, db.ids.ultrasound, db.ids.labs]
    assert not any(row["mentions"] for row in rows)


def test_no_name_and_no_text_returns_most_recent(db):
    rows = fd.search(db.connection, db.alpha, limit=3)
    assert found(rows) == [db.ids.listing, db.ids.ultrasound, db.ids.labs]


# search: text -------------------------------------------------------------

def test_text_matches_content_and_mentions_come_first(db):
    rows = fd.search(db.connection, db.alpha, name=DIOKOR, text="Діокор")
    assert found(rows) == [db.ids.note, db.ids.cardio, db.ids.listing]
    assert [row["mentions"] for row in rows] == [True, True, False]


def test_text_matches_title_case_insensitively(db):
    rows = fd.search(db.connection, db.alpha, text="виписка кардіолога")
    assert found(rows) == [db.ids.cardio]


def test_text_matches_clinic_name(db):
    rows = fd.search(db.connection, db.alpha, text="Clinic North")
    assert found(rows) == [db.ids.ultrasound, db.ids.note, db.ids.cardio, db.ids.undated]


def test_every_word_must_match(db):
    assert found(fd.search(db.connection, db.alpha, text="Діокор Петренко")) == [db.ids.cardio]
    assert fd.search(db.connection, db.alpha, text="Lab North") == []


# search: scope ------------------------------------------------------------

def test_other_users_and_duplicates_never_come_back(db):
    everything = fd.search(db.connection, db.alpha, name=DIOKOR, text="Діокор", limit=50)
    assert db.ids.other not in found(everything)
    assert db.ids.duplicate not in found(everything)
    recent = fd.search(db.connection, db.alpha, limit=50)
    assert db.ids.other not in found(recent) and db.ids.duplicate not in found(recent)


def test_one_hides_other_users_and_duplicates(db):
    assert fd.one(db.connection, db.alpha, db.ids.other, name=DIOKOR) is None
    assert fd.one(db.connection, db.alpha, db.ids.duplicate, name=DIOKOR) is None
    assert fd.one(db.connection, db.beta, db.ids.cardio, name=DIOKOR) is None


# search: text is literal --------------------------------------------------

def test_percent_in_text_is_literal(db):
    assert found(fd.search(db.connection, db.alpha, text="100%")) == [db.ids.ultrasound]


def test_underscore_in_text_is_literal(db):
    assert found(fd.search(db.connection, db.alpha, text="a_b")) == [db.ids.underscore]


# fields -------------------------------------------------------------------

def test_fields_come_from_the_document(db):
    row = fd.one(db.connection, db.alpha, db.ids.cardio, name=DIOKOR)
    assert row == {
        "id": db.ids.cardio,
        "title": "Виписка кардіолога",
        "clinical_type": "consultation",
        "date": "2025-02-10",
        "dated": True,
        "clinic": "Clinic North",
        "doctor": "Петренко Олена Іванівна",
        "diagnosis": "Гіпертонічна хвороба II стадії",
        "mentions": True,
        "snippet": "Рекомендовано Діокор соло 160 мг щодня.",
    }


def test_undated_document_uses_import_date_and_file_name(db):
    row = fd.one(db.connection, db.alpha, db.ids.undated, name=DIOKOR)
    assert row["dated"] is False
    assert row["date"] == "2024-12-15"
    assert row["title"] == "doc-old"
    assert row["doctor"] == "Сидоренко Марія"
    assert row["mentions"] is False
    assert row["snippet"] == ""


# limit --------------------------------------------------------------------

def test_limit_is_respected(db):
    assert found(fd.search(db.connection, db.alpha, name=DIOKOR, limit=1)) == [db.ids.note]
    assert len(fd.search(db.connection, db.alpha, limit=3)) == 3
