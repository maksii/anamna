"""Values listed in the order the document prints them, and placed on the page.

The review page shows a document's values beside its pages.  They used to be
ordered alphabetically within a page, so the first row of an Esculab report
was the last card under it, and a list that does not follow the page cannot
be checked against it.  `positions.py` finds each value's printed row once and
stores it; the document page sorts by it and the source viewer outlines it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from anamna.db import connect
from anamna.ingest import pipeline
from anamna.ingest.positions import (
    LOCATOR_VERSION,
    locate_page,
    page_box,
    position_key,
    store_positions,
)

from test_rescan import build as _rescan_record
from test_rescan import observation as rescan_observation
from test_rescan import page as rescan_page
from test_rescan import rescanner  # noqa: F401 - the fixture, by name
from test_web_panels import build as _built_record

PAGE = (0.0, 0.0, 600.0, 800.0)


def words(*lines: tuple[float, list[tuple[float, str]]]) -> list[dict]:
    """pdfplumber-shaped words: (top, [(x0, text), ...]) per printed line."""
    found = []
    for top, items in lines:
        for x0, text in items:
            found.append({"x0": x0, "x1": x0 + 6 * len(text), "top": top, "bottom": top + 9, "text": text})
    return found


def row(name: str, evidence: str | None = None) -> dict:
    return {"raw_name": name, "evidence_text": evidence or name}


def tops(positions: list[dict]) -> list[float]:
    return [round(item["box"][1] * PAGE[3]) for item in positions]


def test_rows_are_placed_where_the_page_prints_them():
    page = words(
        (100, [(30, "1."), (40, "Холестерин"), (110, "не-ЛПВЩ"), (250, "3.29"), (320, "ммоль/л")]),
        (140, [(40, "Коефіцієнт"), (110, "атерогенності"), (250, "2.59")]),
        (180, [(40, "β-ліпопротеїди"), (250, "39")]),
    )
    # Inserted alphabetically, the way the list used to show them.
    rows = [
        row("β-ліпопротеїди", "β-ліпопротеїди 39"),
        row("Коефіцієнт атерогенності", "Коефіцієнт атерогенності 2.59"),
        row("Холестерин не-ЛПВЩ", "Холестерин не-ЛПВЩ 3.29 ммоль/л"),
    ]
    positions = locate_page(rows, page, PAGE, "")
    assert tops(positions) == [180, 140, 100]
    assert all(item["v"] == LOCATOR_VERSION for item in positions)
    # The row is framed from where the name starts, not from the row number.
    assert positions[2]["box"][0] == round(40 / 600, 4)
    ordered = sorted(zip(rows, positions), key=lambda pair: position_key(json.dumps(pair[1])))
    assert [item["raw_name"] for item, _ in ordered] == [
        "Холестерин не-ЛПВЩ", "Коефіцієнт атерогенності", "β-ліпопротеїди",
    ]


def test_a_label_printed_twice_gives_each_row_its_own_printing():
    page = words(
        (100, [(40, "Колір"), (250, "жовтий")]),
        (300, [(40, "Колір"), (250, "коричневий")]),
    )
    positions = locate_page([row("Колір"), row("Колір")], page, PAGE, "")
    assert tops(positions) == [100, 300]


def test_a_longer_label_claims_its_row_before_a_shorter_one_can():
    page = words(
        (100, [(40, "Білірубін"), (110, "загальний"), (250, "12.0")]),
        (140, [(40, "Білірубін"), (250, "8.2")]),
    )
    positions = locate_page(
        [row("Білірубін", "Білірубін 8.2"), row("Білірубін загальний", "Білірубін загальний 12.0")],
        page, PAGE, "",
    )
    assert tops(positions) == [140, 100]


def test_a_wrapped_label_is_followed_onto_the_next_line_and_no_further():
    page = words(
        # Esculab: the abbreviation wraps under the name, past the value.
        (100, [(40, "Аспартатамінотрансфераза"), (250, "27.8"), (320, "Од/л")]),
        (111, [(40, "(АСТ)"), (380, "Чоловіки:")]),
        # Synevo: one first line, told apart only by the tail under it.  The
        # Latin and Cyrillic spellings of a look-alike must meet as well.
        (200, [(40, "Ширина"), (100, "розподілення"), (250, "36.6"), (320, "фл")]),
        (211, [(40, "(RDW-SD)")]),
        (230, [(40, "Ширина"), (100, "розподілення"), (250, "12.1"), (320, "%")]),
        (241, [(40, "(RDW-CV)")]),
    )
    positions = locate_page(
        [
            row("Ширина розподілення (RDW-CV)"),
            row("Ширина розподілення (RDW-SD)"),
            row("Аспартатамінотрансфераза (ACT)"),
        ],
        page, PAGE, "",
    )
    assert tops(positions) == [230, 200, 100]
    # The frame spans both lines of the wrapped name.
    assert positions[2]["box"][3] == round(120 / 800, 4)


def test_the_row_that_carries_the_value_beats_a_header_naming_the_test():
    page = words(
        (60, [(40, "Замовлення:"), (120, "Глюкоза,"), (190, "Ліпаза")]),
        (200, [(40, "Глюкоза"), (250, "5,65"), (320, "ммоль/л")]),
        (230, [(40, "Ліпаза"), (250, "36,53")]),
    )
    positions = locate_page(
        [row("Глюкоза", "Глюкоза 5,65 ммоль/л"), row("Ліпаза", "Ліпаза 36,53")], page, PAGE, "",
    )
    assert tops(positions) == [200, 230]


def test_a_grouped_row_is_found_by_its_member_under_the_group():
    page = words(
        (100, [(30, "Крохмаль"), (420, "не"), (440, "виявлено")]),
        (104, [(190, "внутрішньоклітинний")]),
        (120, [(190, "позаклітинний"), (420, "не"), (440, "виявлено")]),
    )
    positions = locate_page(
        [row("Крохмаль позаклітинний (кал)", "Крохмаль позаклітинний (кал) не виявлено")], page, PAGE, "",
    )
    assert tops(positions) == [120]


def test_a_label_the_parser_named_itself_is_placed_on_its_evidence_line():
    page = words(
        (100, [(40, "08:13"), (90, "120"), (120, "Сис."), (150, "/"), (160, "80"), (190, "Діас."), (230, "70"), (260, "bpm")]),
        (130, [(40, "07:10"), (90, "118"), (120, "Сис."), (150, "/"), (160, "79"), (190, "Діас."), (230, "66"), (260, "bpm")]),
    )
    first = "08:13 120 Сис. / 80 Діас. 70 bpm"
    second = "07:10 118 Сис. / 79 Діас. 66 bpm"
    positions = locate_page(
        [
            row("Systolic blood pressure", first), row("Pulse rate", first),
            row("Systolic blood pressure", second),
        ],
        page, PAGE, "",
    )
    # Several values read out of one printed line all belong on that line.
    assert tops(positions) == [100, 100, 130]


def test_without_a_text_layer_the_page_text_gives_an_approximate_line():
    text = "Header\nTriglycerides 1.23\nCholesterol 4.56\nFooter"
    positions = locate_page(
        [row("Cholesterol"), row("Triglycerides"), row("Never printed")], None, None, text,
    )
    assert positions[0] == {"v": LOCATOR_VERSION, "y": round(2.5 / 4, 4)}
    assert positions[1] == {"v": LOCATOR_VERSION, "y": round(1.5 / 4, 4)}
    # Looked for and not found: recorded, so nobody looks again, and sorted last.
    assert positions[2] == {"v": LOCATOR_VERSION}
    assert position_key(json.dumps(positions[2])) > position_key(json.dumps(positions[0]))
    # Only an exact box is ever drawn.
    assert page_box(json.dumps(positions[0])) is None
    assert page_box(None) is None
    assert page_box("not json") is None


def minimal_pdf(lines: list[tuple[int, str]]) -> bytes:
    """A one-page PDF with Helvetica text at the given baselines (y from bottom)."""
    stream = "\n".join(f"BT /F1 12 Tf 50 {y} Td ({text}) Tj ET" for y, text in lines).encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 600 800]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    body, offsets = b"%PDF-1.4\n", []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % number + content + b"\nendobj\n"
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return body


def scratch_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """CREATE TABLE observations(id TEXT PRIMARY KEY, document_id TEXT, page_number INTEGER,
               raw_name TEXT, evidence_text TEXT, extraction_method TEXT, evidence_bbox_json TEXT);
           CREATE TABLE document_pages(document_id TEXT, page_number INTEGER, native_text TEXT, ocr_text TEXT);"""
    )
    return connection


def test_store_positions_reads_the_pdf_text_layer(tmp_path: Path):
    source = tmp_path / "report.pdf"
    source.write_bytes(minimal_pdf([(700, "Glucose 5.1 mmol/L"), (650, "ALT 30 U/L")]))
    connection = scratch_database()
    connection.executemany(
        "INSERT INTO observations VALUES (?, 'doc', 1, ?, ?, 'native_pdf_text_parser', NULL)",
        [("a", "ALT", "ALT 30 U/L"), ("b", "Glucose", "Glucose 5.1 mmol/L")],
    )
    connection.execute("INSERT INTO document_pages VALUES ('doc', 1, 'Glucose 5.1 mmol/L\nALT 30 U/L', NULL)")
    assert store_positions(connection, "doc", source) == 2
    stored = dict(connection.execute("SELECT id, evidence_bbox_json FROM observations"))
    glucose, alt = page_box(stored["b"]), page_box(stored["a"])
    assert glucose and alt, stored
    # Fractions of the page, top-down: 800pt high, baseline 700 is ~1/8 down.
    assert 0.09 < glucose[1] < 0.13 and glucose[1] < alt[1]
    assert abs(glucose[0] - 50 / 600) < 0.01

    # A file that will not open still gets the page text's line order.
    source.write_bytes(b"not a pdf")
    connection.execute("UPDATE observations SET evidence_bbox_json=NULL")
    store_positions(connection, "doc", source)
    stored = dict(connection.execute("SELECT id, evidence_bbox_json FROM observations"))
    assert json.loads(stored["b"])["y"] < json.loads(stored["a"])["y"]


def test_the_document_page_places_old_rows_once_and_lists_them_in_print_order(tmp_path: Path):
    settings, user_id, client = _built_record(tmp_path)
    with connect(settings) as connection:
        # Rows imported before positions existed, on one page, out of order.
        connection.execute("UPDATE observations SET page_number=1, evidence_bbox_json=NULL WHERE document_id='doc-1'")
        names = [row[0] for row in connection.execute(
            "SELECT raw_name FROM observations WHERE document_id='doc-1' ORDER BY raw_name DESC"
        )]
        # The page prints them in reverse alphabetical order.
        connection.execute(
            "INSERT OR REPLACE INTO document_pages(document_id, page_number, native_text, extraction_method,"
            " native_char_count, image_count, review_status) VALUES ('doc-1', 1, ?, 'native_pdf_text', 1, 0, 'not_reviewed')",
            ("\n".join(f"{name} evidence" for name in names),),
        )
        connection.commit()
    body = client.get("/documents/doc-1").text
    with connect(settings) as connection:
        stored = [row[0] for row in connection.execute(
            "SELECT evidence_bbox_json FROM observations WHERE document_id='doc-1'"
        )]
    assert stored and all(json.loads(item)["v"] == LOCATOR_VERSION for item in stored)
    # Located by the evidence line: the parser-written English label is no
    # longer claimed as the printed one, so it is not on the row.
    order = sorted(names, key=lambda name: body.index(f"<q>{name} evidence</q>"))
    assert order == names
    # The cards carry their page for the viewer to follow; the explanatory
    # paragraph above the list was removed in the help-text cleanup.
    assert 'data-obs-page="1"' in body
    assert "the original page follows" not in body


def test_a_reread_stores_where_each_value_sits(tmp_path: Path, rescanner):
    """Import and re-read place values as they write them, not on first view."""
    settings, user_id, _ = _rescan_record(tmp_path)
    # The fixture's file is not a PDF, so this is the page-text fallback --
    # the same path a photographed report takes.
    rescanner(
        [rescan_observation("Glucose", 5.1), rescan_observation("ALT", 30.0)],
        pages=[rescan_page(1, "ALT 30\nGlucose 5.1")],
    )
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        stored = dict(connection.execute(
            "SELECT raw_name, evidence_bbox_json FROM observations WHERE document_id='doc-1'"
        ))
    assert json.loads(stored["ALT"])["y"] < json.loads(stored["Glucose"])["y"]


def test_a_card_with_an_exact_box_hands_it_to_the_viewer(tmp_path: Path):
    settings, _, client = _built_record(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET evidence_bbox_json=? WHERE document_id='doc-1'",
            (json.dumps({"v": LOCATOR_VERSION, "box": [0.1, 0.2, 0.9, 0.25]}),),
        )
        connection.commit()
    body = client.get("/documents/doc-1").text
    assert 'data-box="0.1,0.2,0.9,0.25"' in body
