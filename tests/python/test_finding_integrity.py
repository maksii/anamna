"""Narrative grouping must not invent diagnoses or overwrite a human ruling."""
import pytest

from anamna.db import connect, migrate, utc_now
from anamna.health import _extract_clinical_assessment, finding_attention, sync_clinical_findings
from anamna.security import create_user
from anamna.web.app import _finding_catalog
from test_web_security import PASSWORD, settings_for, seed_patient, seed_document


def test_keyword_grouping_preserves_negation_and_does_not_invent_other_findings():
    source = "Висновок: Ознак кісти Бейкера не виявлено."
    summary = _extract_clinical_assessment(source)
    assert summary == "Ознак кісти Бейкера не виявлено."
    # A negated term is a normal result, not an attention finding.
    assert finding_attention(summary) == []


@pytest.fixture
def ledger(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    owner = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, owner, "Alpha")
    document = seed_document(settings, owner, patient, "Chest imaging", "chest.txt")
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET clinical_type='diagnostic_image' WHERE id=?", (document,))
        connection.execute(
            "INSERT INTO document_pages(document_id,page_number,native_text,extraction_method,review_status) VALUES (?,1,?,'native','not_reviewed')",
            (document, "Chest images without a written assessment."),
        )
        sync_clinical_findings(connection)
    return settings, owner, document


@pytest.mark.parametrize("state", ["verified", "corrected", "rejected"])
def test_regeneration_preserves_human_findings_and_original_evidence(ledger, state):
    settings, owner, document = ledger
    with connect(settings) as connection:
        connection.execute(
            "UPDATE clinical_findings SET title='Narrative report', summary_en='Reviewed wording', original_text='Reviewed source', verification_status=?",
            (state,),
        )
        before = [tuple(row) for row in connection.execute("SELECT * FROM clinical_findings")]
        connection.execute("UPDATE document_pages SET native_text='Different chest image content' WHERE document_id=?", (document,))
        sync_clinical_findings(connection)
        assert before == [tuple(row) for row in connection.execute("SELECT * FROM clinical_findings")]
        visible = _finding_catalog(connection, owner)
        assert len(visible) == (0 if state == "rejected" else 1)


def test_duplicate_sources_do_not_supply_additional_findings(ledger):
    settings, owner, original = ledger
    with connect(settings) as connection:
        patient = connection.execute("SELECT patient_id FROM documents WHERE id=?", (original,)).fetchone()[0]
    duplicate = seed_document(settings, owner, patient, "Chest imaging duplicate", "copy.txt")
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET clinical_type='diagnostic_image', duplicate_of_document_id=? WHERE id=?", (original, duplicate))
        connection.execute(
            "INSERT INTO document_pages(document_id,page_number,native_text,extraction_method,review_status) VALUES (?,1,'chest images','native','not_reviewed')",
            (duplicate,),
        )
        sync_clinical_findings(connection)
        assert connection.execute("SELECT COUNT(*) FROM clinical_findings").fetchone()[0] == 1


def test_obsolete_machine_findings_are_reconciled_when_source_changes(ledger):
    settings, _, document = ledger
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET title='Other imaging', original_filename='other.txt' WHERE id=?", (document,))
        connection.execute("UPDATE document_pages SET native_text='Kidney imaging' WHERE document_id=?", (document,))
        sync_clinical_findings(connection)
        areas = [row[0] for row in connection.execute("SELECT health_area FROM clinical_findings")]
        assert areas == ["kidneys"]


def test_clinic_consultations_are_filed_by_specialty_and_vaccination_visits_under_immunity(tmp_path):
    """Live Veselka/St. Paraskeva notes, 2026-11-06: a cardiologist quoting the
    carotid scan it reviewed is the cardiology consultation; a dermatology note
    has an area of its own; a vaccination visit naming «Гепатиту А+В» is about
    immunity, not the liver; «Клінічний діагноз:» is the conclusion."""
    settings = settings_for(tmp_path)
    migrate(settings)
    owner = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, owner, "Alpha")
    notes = {
        "cardio": ("Консультація лікаря-кардіолога",
                   "Консультація лікаря-кардіолога\nДуплекс сонних артерій: без стенозів\nДіагноз:\nI11.9 Гіпертензивна хвороба серця"),
        "derma": ("Консультація лікаря-дерматолога",
                  "Консультація лікаря-дерматолога\nКлінічний діагноз:\nL82 Себорейний кератоз\nПризначене лікування: бетадин"),
        "lipoma": ("УЗД прицільно ділянки",
                   "УЗД ПРИЦІЛЬНО\nВ ділянці 'інтересу' візуалізується гіперехогенне утворення 9,4х4,6мм\n"
                   "Висновок: Ультразвукові ознаки ліпоми лівої верхньої кінцівки.\nЛікар: Н."),
        "vaccine": ("Огляд лікаря первинка",
                    "Огляд лікаря первинка\nОб'єктивний стан: шкіра чиста\nДіагноз:\nМКХ-10 Z27.9 Необхідність імунізації\n"
                    "Опис: Гепатиту А+В\nВакцинації\nНазва вакцини HepAHepB"),
    }
    for key, (title, text) in notes.items():
        document = seed_document(settings, owner, patient, title, f"{key}.txt")
        with connect(settings) as connection:
            connection.execute("UPDATE documents SET clinical_type=?, report_date='2026-08-09' WHERE id=?",
                               ("ultrasound" if key == "lipoma" else "consultation", document))
            connection.execute(
                "INSERT INTO document_pages(document_id,page_number,native_text,extraction_method,review_status) "
                "VALUES (?,1,?,'native','not_reviewed')", (document, text))
    with connect(settings) as connection:
        sync_clinical_findings(connection)
        found = {row["document_id"]: (row["title"], row["health_area"])
                 for row in connection.execute("SELECT * FROM clinical_findings")}
    assert _extract_clinical_assessment(notes["derma"][1], "consultation").startswith("L82 Себорейний кератоз")
    assert found["doc-cardio.txt"] == ("Cardiology consultation", "heart")
    assert found["doc-derma.txt"] == ("Dermatology consultation", "skin")
    assert found["doc-vaccine.txt"] == ("Family doctor consultation", "immunity")
    assert found["doc-lipoma.txt"] == ("Ultrasound report", "joints"), "a soft-tissue lump has an area"
