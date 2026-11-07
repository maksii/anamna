"""A scanned page has no text layer, and reading it is not optional.

Every document a person uploads that is not a lab's own PDF export arrives as a
photograph: a consultation note, an MRI report, a paper form.  Those pages
carry one full-bleed image and no native text — and `significant_image_regions`
deliberately ignores anything covering more than 85% of the sheet, because on a
*native-text* report that is the letterhead template.  The two cases are the
same shape and opposite situations, and until now the second one silently
produced nothing: a fourteen-megabyte two-page scan imported in under a second
with zero characters extracted, no error, and a page that read as blank.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from anamna.ingest import extract
from anamna.ingest.classifier import classify_document
from anamna.ingest.extract import extract_document


#: Applied per test, not to the module: the TSV-parsing regression below fakes
#: the tesseract call entirely, and skipping it wherever tesseract is absent
#: would leave the bug it guards unguarded on exactly the machine that runs CI.
needs_tesseract = pytest.mark.skipif(
    not extract.ocr_available(),
    reason="OCR needs tesseract, locally or through WSL",
)

#: Short enough to fit the page at a size the default bitmap font survives.
TEXT = "VACCINATION CARD"


def scanned_pdf(path: Path) -> Path:
    """A PDF whose only content is one full-page picture of some words."""
    page = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(page)
    # Drawn large enough that the default bitmap font survives OCR; the point
    # here is the plumbing, not tesseract's accuracy on small type.
    for index, line in enumerate((TEXT, "FORM 063/O", "BATCH AC37B478AG")):
        draw.text((90, 160 + index * 190), line, fill="black", font_size=96)
    page.save(path, "PDF", resolution=150.0)
    return path


@needs_tesseract
def test_a_full_page_scan_is_read(tmp_path: Path):
    document = extract_document(scanned_pdf(tmp_path / "scan.pdf"))
    page = document["pages"][0]
    assert page["native_char_count"] == 0, "the fixture must have no text layer"
    assert page["ocr_text"].strip(), "a scanned page produced no text at all"
    assert "VACCINATION" in page["ocr_text"].upper()
    # Named for what happened, so the document page does not tell a reader that
    # an embedded table was lifted out of a text layer that never existed.
    assert page["extraction_method"] == "page_image_ocr"
    classification = classify_document("scan.pdf", "application/pdf", document["pages"], {})
    assert classification.extraction_strategy == "scanned_page_ocr"
    # The status that used to be the end of the story for one of these.
    assert classification.status != "attachment_only"


@needs_tesseract
def test_run_ocr_false_still_skips_the_work(tmp_path: Path):
    """The re-read path passes `run_ocr=False`; that must stay free."""
    document = extract_document(scanned_pdf(tmp_path / "scan.pdf"), run_ocr=False)
    page = document["pages"][0]
    assert page["ocr_text"] == ""
    assert page["extraction_method"] == "native_pdf_text"


def test_a_quote_in_the_ocr_does_not_eat_the_following_rows(monkeypatch, tmp_path: Path):
    """Tesseract's TSV is not CSV, and «внутрішньом'я» is why it matters.

    The apostrophe comes back as a double quote often enough to be routine. Read
    with the csv module's default quoting, that opens a quoted field which
    swallows every following line into one — and the rows that vanished
    reappeared as literal TSV printed on the page where a batch number should
    have been.
    """
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    rows = [
        # A word tesseract read with a double quote for the apostrophe.
        '5\t1\t1\t1\t1\t1\t100\t100\t200\t20\t90\tBHYTPIWHbOM"A',
        '5\t1\t1\t1\t2\t1\t100\t200\t120\t20\t95\tAC37B478AG',
        '5\t1\t1\t1\t3\t1\t100\t300\t120\t20\t95\t28.03.2026',
    ]
    monkeypatch.setattr(
        extract.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "R", (), {"returncode": 0, "stdout": "\n".join([header, *rows])}
        )(),
    )
    text = extract.ocr_layout_rows(tmp_path / "unused.png")
    assert "AC37B478AG" in text
    assert "28.03.2026" in text
    assert "\t" not in text, "raw TSV leaked into the reconstructed text"
