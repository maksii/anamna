"""Copies the results cannot reveal: prints, scans, photos and screenshots.

A browser print of one report differs from the next only in its header
stamp; a scan of it reads to other words; a phone photo shows one page; a
cytology passport is printed beside it; screenshots of a long page arrive one
per scroll position.  None of these carries results that compare, so each is
recognised from its page text: the words, the order number, the order and
result times.  Every name, number and date here is invented.
"""

from __future__ import annotations

from dataclasses import replace
import html
from pathlib import Path

import pytest

from anamna.db import connect, utc_now
from anamna.ingest import intake, pipeline

from test_document_duplicates import add_copy, csrf_for, mark, scalar
from test_ingestion_integrity import ledger  # noqa: F401  (fixture)
from test_rescan import build


@pytest.fixture(autouse=True)
def no_worker(monkeypatch):
    monkeypatch.setattr(intake, "start_worker", lambda settings: None)


def add_document(settings, doc_id: str, text: str = "", *, ocr: str = "", mime: str = "application/pdf",
                 imported_at: str = "2026-01-01T00:00:00+00:00", **fields) -> None:
    """A document with no values: only its page text, native and OCR."""
    add_copy(settings, doc_id, with_values=False, imported_at=imported_at)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE documents SET mime_type=?, report_date=NULL WHERE id=?", (mime, doc_id)
        )
        for name, value in fields.items():
            connection.execute(f"UPDATE documents SET {name}=? WHERE id=?", (value, doc_id))
        connection.execute(
            """INSERT INTO document_pages(document_id, page_number, native_text, ocr_text, extraction_method,
                   native_char_count) VALUES (?, 1, ?, ?, 'native_pdf_text', ?)""",
            (doc_id, text, ocr, len(text)),
        )
        connection.commit()


def relations(settings) -> set[tuple[str, str, str, str]]:
    with connect(settings) as connection:
        return {tuple(row) for row in connection.execute(
            "SELECT source_document_id, target_document_id, relationship, notes FROM document_relations")}


def relate(settings, user_id: str, *doc_ids: str) -> set[tuple[str, str, str, str]]:
    with connect(settings) as connection:
        for doc_id in doc_ids:
            pipeline.record_document_relations(connection, user_id, doc_id)
        connection.commit()
    return relations(settings)


URINALYSIS = """Медичний центр Тестова клініка
Аналіз сечі загальний
Колір солом'яно-жовтий
Прозорість прозора
Відносна щільність 1,018
Лейкоцити не виявлені
Еритроцити не виявлені
"""


def test_browser_prints_that_differ_only_in_the_print_header_are_one_report(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    for index, (stamp, counter) in enumerate((("07.08.26, 10:33", "Сторінĸа 1 із 2"),
                                              ("07.08.26, 10:32", "Сторінка 1 з 2"),
                                              ("8/7/26, 10:27 AM", "Page 1 of 2"))):
        # The header is native text; the screenshot inside the page is OCR.
        add_document(settings, f"print-{index}", f"{stamp}\n{counter}\nhttps://portal.example.test/r/{index}",
                     ocr=URINALYSIS + f"Дата друку: 0{index + 1}.08.2026\n",
                     imported_at=f"2026-01-0{index + 1}T00:00:00+00:00")
    found = relate(settings, user_id, "print-2")
    assert found == {
        ("print-2", "print-0", "duplicate", "auto:same_text"),
        ("print-2", "print-1", "duplicate", "auto:same_text"),
    }
    # Documents already held are linked on start, all three pairs.
    with connect(settings) as connection:
        connection.execute("DELETE FROM document_relations")
        connection.commit()
        assert pipeline.repair_text_duplicates(connection) == 3
        assert pipeline.repair_text_duplicates(connection) == 0


def test_an_equal_content_hash_is_one_report_but_two_blank_scans_are_not(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    add_document(settings, "render-1", URINALYSIS, content_sha256="hash-a")
    add_document(settings, "render-2", URINALYSIS.replace("Колір", "Ко-\nлір"), content_sha256="hash-a",
                 imported_at="2026-02-01T00:00:00+00:00")
    add_document(settings, "blank-1", "1", content_sha256="hash-empty")
    add_document(settings, "blank-2", "1", content_sha256="hash-empty")
    assert relate(settings, user_id, "render-2", "blank-2") == {
        ("render-2", "render-1", "duplicate", "auto:content_hash"),
    }


SMEAR = """Медичний центр Тестова клініка
Результати досліджень
Дата замовлення: 02.03.2026 09:41
Дата результату: 04.03.2026 16:05
Клієнт: Петренко Олена 4400112233
Аналіз мазка на мікрофлору
Лейкоцити поодинокі в полі зору
Епітелій в помірній кількості
Флора палички в помірній кількості
Висновок Ступінь чистоти друга
"""
# The same sheet scanned at half size: the barcode is lost, words are misread.
SMEAR_SCAN = """Медичний центр Тестова клініка
Результати дослідженб
Дата замовлення: | 02.03.2026 09:41
Дата результату: 04.03.2026 16:05
Клієнт: Петренко Олена
Аналіз мазка на мікрофлору
Лейкоцити поодинокі в полі зору
Епітелій в помірній кількості
Флора палички в помірній
Висновок Ступінь чистоти
"""
PASSPORT = """Цитологічний паспорт
Петренко Олена ШК 4400112233
Дата замовлення: 02.03.2026
Зображення клітин сформовано автоматизованою системою візуалізації
препаратів рідинної цитології, яка позначає ділянки для перегляду
лабораторним експертом і зберігає знімки кожного поля
"""


def test_one_order_scanned_twice_and_its_cytology_passport(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_document(settings, "report", SMEAR, imported_at="2026-03-05T00:00:00+00:00")
    add_document(settings, "scan", ocr=SMEAR_SCAN, imported_at="2026-03-06T00:00:00+00:00")
    add_document(settings, "passport", ocr=PASSPORT, imported_at="2026-03-07T00:00:00+00:00",
                 report_date="2026-03-02")
    assert relate(settings, user_id, "scan", "passport") == {
        ("scan", "report", "duplicate", "auto:same_order"),
        ("passport", "report", "attachment_of", "auto:same_order"),
    }
    page = client.get("/documents/scan").text
    assert "Both print the same order" in page
    assert "Keep that one: mark this copy as a duplicate" in page
    page = client.get("/documents/report").text
    assert "A supplement for this order (cell images, explanations) is in" in page
    assert "Supplement printed for the same order as" in client.get("/documents/passport").text
    client.cookies.set("anamna_lang", "uk")
    assert "В обох надруковано те саме замовлення" in client.get("/documents/scan").text
    assert "Додаток до цього замовлення (зображення клітин, пояснення) є в документі" in client.get(
        "/documents/report").text


LETTERHEAD = "Тестова клініка, свідоцтво на знак 7654321\n"


def test_a_letterhead_number_or_a_short_number_alone_links_nothing(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    # One certificate number on reports of two different days.
    add_document(settings, "spring", LETTERHEAD + "Дата замовлення: 02.03.2026 09:41\nГемоглобін 131")
    add_document(settings, "autumn", LETTERHEAD + "Дата замовлення: 14.10.2026 11:02\nГемоглобін 128")
    # A seven-digit number and nothing else in common.
    add_document(settings, "note-a", "Направлення 1234567 до терапевта")
    add_document(settings, "note-b", "Квитанція 1234567 оплачено")
    assert relate(settings, user_id, "autumn", "note-b") == set()


LAB = """Лабораторія Тест
Замовлення: 55001234 / 12.05.2026 08:15 Дата видачі: 13.05.2026 17:40
Аланінамінотрансфераза 23 Од/л 0 - 33
Аспартатамінотрансфераза 19 Од/л 0 - 32
Білірубін загальний 11,2 мкмоль/л 0 - 21
"""


def test_a_phone_photo_of_one_page_is_offered_as_a_copy_of_the_report(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_document(settings, "lab", LAB)
    add_document(settings, "photo", ocr="Замовлення 55001234 / 12.05.2026 08:15\nАланінамінотрансфераза 23 Од/л",
                 mime="image/jpeg", imported_at="2026-05-20T00:00:00+00:00")
    assert relate(settings, user_id, "photo") == {("lab", "photo", "contains", "auto:same_order")}
    page = client.get("/documents/photo").text
    assert "Suggested: keep the whole report. The other file is a photo, screenshot or part of it." in page
    # The photo holds no values, so marking it a copy loses nothing.
    assert mark(client, settings, user_id, copy="photo", primary="lab").status_code == 303
    assert scalar(settings, "SELECT duplicate_of_document_id FROM documents WHERE id='photo'") == "lab"


CONSULTATION = """Тестова клініка консультативний висновок лікаря гастроентеролога
Скарги на періодичний біль у животі після їжі, здуття, печію ввечері
Анамнез хвороби протягом двох років, погіршення навесні
Об'єктивно стан задовільний, живіт мякий, болючий в епігастрії
Діагноз функціональна диспепсія К30
Рекомендовано дієта, омепразол 20 мг двічі на день 28 днів
Контроль через 6 тижнів, дихальний тест на 14 день після курсу
Дата огляду 06.06.2024 лікар Іваненко
Вага 64 кг зріст 168 см тиск 118/76 пульс 72
"""
OTHER_CONSULTATION = """Тестова клініка консультативний висновок лікаря ендокринолога
Скарги на слабкість зранку, тремтіння через дві години після солодкого
Об'єктивно щитоподібна залоза не збільшена, шкіра звичайної вологості
Діагноз реактивна гіпоглікемія Е16.1
Рекомендовано дробне харчування 5 разів на день, глікемічний профіль
Дата огляду 13.11.2024 лікар Петренко
Вага 63 кг зріст 168 см тиск 110/70 пульс 80
"""


def test_a_photo_of_a_consultation_is_matched_by_its_words_and_figures(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_document(settings, "consult", CONSULTATION)
    add_document(settings, "other", OTHER_CONSULTATION)
    photo = CONSULTATION.replace("мякий", "м'якнй").replace("ввечері", "ввечерi")
    add_document(settings, "photo", ocr=photo, mime="image/jpeg", imported_at="2026-06-07T00:00:00+00:00")
    # The template of a third consultation, figures of another day: no match.
    template = CONSULTATION.replace("06.06.2024", "19.09.2024").replace("64 кг", "61 кг").replace(
        "118/76", "125/80").replace("72", "66").replace("28 днів", "14 днів").replace("6 тижнів", "3 місяці")
    add_document(settings, "template-photo", ocr=template.replace("К30", "К58"), mime="image/jpeg",
                 imported_at="2026-09-20T00:00:00+00:00")
    found = relate(settings, user_id, "photo", "template-photo")
    assert ("consult", "photo", "contains", "auto:page_text") in found
    assert not {row for row in found if "template-photo" in row[:2] and row[3] != "auto:parts"}
    page = client.get("/documents/photo").text
    assert "Nearly every word and number of one file is also in the other." in page
    client.cookies.set("anamna_lang", "uk")
    assert "Майже кожне слово й число одного файлу є і в іншому." in client.get("/documents/photo").text


def _batch(settings, owner: str, patient: str, batch: str, *doc_ids: str) -> None:
    with connect(settings) as connection:
        for index, doc_id in enumerate(doc_ids):
            connection.execute(
                """INSERT INTO upload_jobs(id, owner_user_id, patient_id, batch_id, kind, filename, state,
                       document_id, created_at) VALUES (?, ?, ?, ?, 'document', 'photo.jpg', 'done', ?, ?)""",
                (f"job-{doc_id}", owner, patient, batch, doc_id, f"2026-07-01T10:00:0{index}+00:00"),
            )
        connection.commit()


SCROLL_1 = """Лабораторія Тест
Пацієнт Петренко Олена
Загальний аналіз крові з лейкоцитарною формулою
Гемоглобін 132 г/л референтний інтервал 117 - 155
Еритроцити 4,41 10^12/л референтний інтервал 3,8 - 5,1
"""
SCROLL_2 = """Еритроцити 4,41 10^12/л референтний інтервал 3,8 - 5,1
Гематокрит 39,6 % референтний інтервал 35 - 45
Тромбоцити 251 10^9/л референтний інтервал 150 - 400
"""
SCROLL_3 = """Тромбоцити 251 10^9/л референтний інтервал 150 - 400
Лейкоцити 6,2 10^9/л референтний інтервал 4 - 10
Лікар лаборант Іваненко
"""
OTHER_REPORT = """Лабораторія Тест
Пацієнт Петренко Олена
Глюкоза натще 5,1 ммоль/л референтний інтервал 3,9 - 5,8
"""


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_screenshots_of_one_report_uploaded_together_are_its_parts(tmp_path: Path, locale: str):
    settings, user_id, client = build(tmp_path)
    client.cookies.set("anamna_lang", locale)
    for doc_id, text in (("shot-1", SCROLL_1), ("shot-2", SCROLL_2), ("shot-3", SCROLL_3), ("shot-4", OTHER_REPORT)):
        add_document(settings, doc_id, ocr=text, mime="image/jpeg")
    patient = scalar(settings, "SELECT patient_id FROM documents WHERE id='doc-1'")
    _batch(settings, user_id, patient, "batch-1", "shot-1", "shot-2", "shot-3", "shot-4")
    found = relate(settings, user_id, "shot-1", "shot-2", "shot-3", "shot-4")
    assert found == {
        ("shot-2", "shot-1", "part_of", "auto:parts"),
        ("shot-3", "shot-1", "part_of", "auto:parts"),
    }
    words = {
        "en": ("Next screenshot of this report:", "Screenshot of one report, uploaded with its first part:",
               "Not part of this report", "Screenshot of one report sent in several parts"),
        "uk": ("Наступний знімок екрана цього звіту:", "Знімок екрана одного звіту, надісланий разом із його першою частиною:",
               "Це не частина цього звіту", "Знімок екрана звіту, надісланого кількома частинами"),
    }[locale]
    head = client.get("/documents/shot-1").text
    assert head.count(words[0]) == 2
    part = client.get("/documents/shot-3").text
    assert words[1] in part and words[2] in part
    assert words[3] in client.get("/documents?review_state=open").text
    # "Not part of this report" unlinks it, and a re-read does not link it again.
    response = client.post(
        "/documents/shot-3/duplicate",
        data={"action": "keep_both", "other_id": "shot-1", "csrf_token": csrf_for(settings, user_id)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert {row[:3] for row in relate(settings, user_id, "shot-3")} == {
        ("shot-2", "shot-1", "part_of"), ("shot-3", "shot-1", "duplicate"),
    }


def test_an_uploaded_screenshot_is_related_once_its_job_names_it(ledger, monkeypatch):  # noqa: F811
    settings, owner, patient = ledger
    texts = {"one.jpg": SCROLL_1, "two.jpg": SCROLL_2}

    def analysed(path, run_ocr=True):
        klass = replace(pipeline_classification, title=path.name)
        page = {"page_number": 1, "native_text": "", "ocr_text": texts[path.name], "native_text_sha256": None,
                "extraction_method": "tesseract", "native_char_count": 0, "image_count": 1}
        return pipeline.Analysis([page], "image/jpeg", 1, f"hash-{path.name}", klass, [klass])

    from test_rescan import classification
    pipeline_classification = classification()
    monkeypatch.setattr(pipeline, "analyse_document", analysed)
    monkeypatch.setattr(pipeline, "parse_pages", lambda *_, **__: [])
    for name in texts:
        path = settings.source_dir / "uploads" / "2026-07" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        intake.enqueue(settings, owner_user_id=owner, patient_id=patient, batch_id="album",
                       kind="document", filename=name, source_path=path, start=False)
    intake.drain_now(settings)
    with connect(settings) as connection:
        titles = dict(connection.execute("SELECT id, title FROM documents").fetchall())
        found = [(titles[s], titles[t], r) for s, t, r in connection.execute(
            "SELECT source_document_id, target_document_id, relationship FROM document_relations")]
    assert found == [("two.jpg", "one.jpg", "part_of")]


def test_copies_of_copies_point_at_the_kept_document(ledger):  # noqa: F811
    settings, owner, patient = ledger
    from test_ingestion_integrity import uploaded_source

    kept = pipeline.ingest_file(settings, owner, patient, uploaded_source(settings, "kept.pdf"))["document_id"]
    copy = pipeline.ingest_file(settings, owner, patient, uploaded_source(settings, "copy.pdf"))["document_id"]
    assert scalar(settings, "SELECT duplicate_of_document_id FROM documents WHERE id=?", copy) == kept
    with connect(settings) as connection:
        # A third document is kept, and the first is marked a copy of it.
        connection.execute(
            """INSERT INTO documents(id, owner_user_id, patient_id, original_filename, source_path, mime_type,
                   byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
                   classification_confidence, imported_at, status)
               SELECT 'lab-pdf', owner_user_id, patient_id, 'lab.pdf', source_path, mime_type, 1, 'other-bytes',
                      1, title, clinical_type, extraction_strategy, 1, ?, 'final' FROM documents WHERE id=?""",
            (utc_now(), kept),
        )
        connection.execute("UPDATE documents SET duplicate_of_document_id='lab-pdf' WHERE id=?", (kept,))
        connection.commit()
    # Same bytes again: the new copy names the kept document, never a copy.
    again = pipeline.ingest_file(settings, owner, patient, uploaded_source(settings, "again.pdf"))["document_id"]
    assert scalar(settings, "SELECT duplicate_of_document_id FROM documents WHERE id=?", again) == "lab-pdf"
    # The chain left before the fix is shortened on start.
    with connect(settings) as connection:
        assert pipeline.flatten_duplicate_chains(connection) == 1
        connection.commit()
    assert scalar(settings, "SELECT duplicate_of_document_id FROM documents WHERE id=?", copy) == "lab-pdf"


def test_the_file_linked_to_the_lab_order_is_the_suggested_keep(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_copy(settings)  # newer, the same eight results
    with connect(settings) as connection:
        pipeline.record_document_relations(connection, user_id, "copy")
        connection.execute(
            """INSERT INTO lab_orders(owner_user_id, provider, remote_person_id, order_id, state, document_id,
                   first_seen_at, last_synced_at) VALUES (?, 'esculab', 'p', '55001234', 'linked', 'copy', ?, ?)""",
            (user_id, utc_now(), utc_now()),
        )
        connection.commit()
    page = html.unescape(client.get("/documents/copy").text)
    assert "Suggested: keep the file linked to the lab's order." in page
    assert page.index("Keep this one: mark that one as a duplicate") < page.index(
        "Keep that one: mark this copy as a duplicate")


def test_marking_refuses_when_the_kept_document_lacks_a_test_entirely(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_copy(settings)
    with connect(settings) as connection:
        connection.execute("DELETE FROM observations WHERE id='obs-2'")
        connection.commit()
    response = mark(client, settings, user_id)
    assert response.headers["location"] == "/documents/copy?dup_error=missing#duplicates"
    assert scalar(settings, "SELECT COUNT(*) FROM observations WHERE document_id='copy'") == 8
    assert "this copy holds a test the document you keep does not hold at all" in client.get(
        response.headers["location"]).text
    client.cookies.set("anamna_lang", "uk")
    assert "у цій копії є аналіз, якого зовсім немає" in client.get(response.headers["location"]).text
    # Keeping the copy instead loses nothing.
    assert mark(client, settings, user_id, copy="doc-1", primary="copy").status_code == 303
    assert scalar(settings, "SELECT duplicate_of_document_id FROM documents WHERE id='doc-1'") == "copy"
