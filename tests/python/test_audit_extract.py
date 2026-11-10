from __future__ import annotations

import logging
import threading

import pdfplumber
import pytest
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from anamna.ingest import extract


class _Page:
    def __init__(self, width: float, height: float) -> None:
        self._size = (width, height)

    def get_size(self) -> tuple[float, float]:
        return self._size


def test_render_scale_never_exceeds_the_pixel_cap():
    oversized = _Page(14400.0, 14400.0)
    assert extract._render_scale(oversized, 3.5) * 14400 <= extract.MAX_RENDER_EDGE_PX

    a4 = _Page(595.0, 842.0)
    assert extract._render_scale(a4, 3.5) == 3.5


def test_tiff_with_too_many_frames_is_refused(tmp_path, monkeypatch):
    frames = [Image.new("L", (20, 20), value) for value in (0, 128, 255)]
    target = tmp_path / "three-frames.tif"
    frames[0].save(target, save_all=True, append_images=frames[1:])
    monkeypatch.setattr(extract, "MAX_OCR_PAGES", 2)

    with pytest.raises(ValueError, match="3 frames"):
        extract.extract_document(target, run_ocr=False)


def test_pdf_pages_past_the_cap_skip_ocr(tmp_path, monkeypatch, caplog):
    source = tmp_path / "three-pages.pdf"
    canvas = Canvas(str(source), pagesize=(300, 400))
    for line in ("first page", "second page", "third page"):
        canvas.drawString(40, 200, line)
        canvas.showPage()
    canvas.save()

    recorded: list[bool] = []

    def recorder(path, index, page, run_ocr):
        recorded.append(run_ocr)
        return {"page_number": index}

    monkeypatch.setattr(extract, "MAX_OCR_PAGES", 1)
    monkeypatch.setattr(extract, "_pdf_page", recorder)
    with caplog.at_level(logging.WARNING, logger=extract.__name__):
        extract.extract_document(source, run_ocr=True)

    assert recorded == [True, False, False]
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "3" in warnings[0].getMessage()
    assert "three-pages" not in warnings[0].getMessage()


def test_pdf_reader_is_reused_for_the_same_file(tmp_path):
    source = tmp_path / "one-page.pdf"
    canvas = Canvas(str(source), pagesize=(300, 400))
    canvas.drawString(40, 200, "one page")
    canvas.save()

    first = extract._pdf_reader(str(source), source.stat().st_mtime_ns)
    second = extract._pdf_reader(str(source), source.stat().st_mtime_ns)
    assert first is second


def test_pdfium_lock_is_reentrant_and_exported():
    lock = extract.PDFIUM_LOCK
    assert lock.acquire(blocking=False)
    assert lock.acquire(blocking=False)
    lock.release()
    lock.release()


def _lock_probing_first_output(lock_free: list[bool]):
    """Stand-in for the Tesseract runner: records whether PDFIUM_LOCK is free, then prints nothing."""

    def first_output(commands):
        probed: dict[str, bool] = {}

        def probe():
            probed["free"] = extract.PDFIUM_LOCK.acquire(timeout=2)
            if probed["free"]:
                extract.PDFIUM_LOCK.release()

        worker = threading.Thread(target=probe)
        worker.start()
        worker.join()
        lock_free.append(probed["free"])
        return ""

    return first_output


def test_ocr_never_runs_while_the_pdfium_lock_is_held(tmp_path, monkeypatch):
    source = tmp_path / "scan.pdf"
    canvas = Canvas(str(source), pagesize=(300, 400))
    canvas.drawString(40, 200, "page text")
    canvas.save()

    lock_free: list[bool] = []
    monkeypatch.setattr(extract, "_first_output", _lock_probing_first_output(lock_free))

    assert extract.ocr_pdf_page(source, 0) == ""
    assert lock_free
    assert all(lock_free)


def test_embedded_image_ocr_never_runs_while_the_pdfium_lock_is_held(tmp_path, monkeypatch):
    picture = Image.new("RGB", (200, 120), "white")
    source = tmp_path / "embedded.pdf"
    canvas = Canvas(str(source), pagesize=(300, 400))
    canvas.drawImage(ImageReader(picture), 40, 150, width=220, height=132)
    canvas.save()

    with pdfplumber.open(source) as pdf:
        regions = extract.significant_image_regions(pdf.pages[0])
    assert regions

    lock_free: list[bool] = []
    monkeypatch.setattr(extract, "_first_output", _lock_probing_first_output(lock_free))

    assert extract.ocr_pdf_image_regions(source, 0, regions) == ""
    assert lock_free
    assert all(lock_free)
