from __future__ import annotations

import csv
import hashlib
import io
import mimetypes
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import pdfplumber
from PIL import Image, ImageOps
from pypdf import PdfReader
import pypdfium2 as pdfium

from ..config import ROOT
from .text import text_sha256


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").casefold()
    suffix = resolved.as_posix().split(":", 1)[-1]
    return f"/mnt/{drive}{suffix}"


#: Tesseract's page-segmentation mode.  `11` -- sparse text, no assumed order --
#: is right for a cropped table pulled out of an otherwise native-text page.  A
#: whole scanned sheet is the opposite case: it has a layout, and `3` (automatic
#: segmentation) is the mode that reads one.
SPARSE_REGION_PSM = "11"
FULL_PAGE_PSM = "3"
#: A scan is embedded at whatever size the phone produced.  Anything much past
#: this on the long edge costs minutes of OCR for no extra characters.
PAGE_RENDER_LONG_EDGE = 3000
#: An image whose long edge is under half this is enlarged by a whole factor
#: (at most 3) before OCR.
SMALL_IMAGE_EDGE = 2600
#: Below this many native characters a page carries no readable text of its own,
#: and whatever it does carry is in the picture.  The same number the classifier
#: uses to call a document `ocr_required`, so the two cannot disagree about which
#: pages are scans.
SCANNED_PAGE_CHARS = 80
#: The Windows launcher for the WSL install that carries tesseract.
WSL_EXE = "wsl.exe"
#: Tesseract's language argument: Ukrainian reports with English terms.
OCR_LANGUAGES = "ukr+eng"


@lru_cache(maxsize=1)
def ocr_available() -> bool:
    """Whether an OCR command can actually run with both configured languages.

    `wsl.exe` existing on Windows says only that the launcher is installed. A
    disabled WSL service still returns access denied, which previously made the
    end-to-end OCR test run and then fail with an empty page. Probe the exact
    language contract instead of inferring capability from an executable name.
    """
    for command in (["tesseract", "--list-langs"], [WSL_EXE, "tesseract", "--list-langs"]):
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            languages = {line.strip() for line in result.stdout.splitlines()}
            if {"ukr", "eng"} <= languages:
                return True
    return False


def _first_output(commands: list[list[str]]) -> str:
    """Stdout of the first command that runs and prints something, else ""."""
    for command in commands:
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=120, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    return ""


#: Tesseract's orientation confidence is a score, not a percentage: sideways
#: pages of real text score in the tens, while a mis-detection on sparse or
#: noisy text hovers below 2. Below this the page is left as it is.
OSD_MIN_CONFIDENCE = 2.0


def upright_image_file(path: Path) -> int:
    """Rotate a page image in place when tesseract's OSD says it is sideways.

    Phone photos of paper arrive turned 90 or 270 degrees and OCR reads
    nothing from them. Returns the clockwise degrees applied (0 when OSD is
    unavailable, fails, is not confident, or says the page is already upright).
    Never raises: on any doubt the image is left untouched.
    """
    try:
        output = _first_output([
            ["tesseract", str(path), "stdout", "--psm", "0", "-l", "osd"],
            [WSL_EXE, "tesseract", wsl_path(path), "stdout", "--psm", "0", "-l", "osd"],
        ])
        fields = {
            key.strip().lower(): value.strip()
            for key, _, value in (line.partition(":") for line in output.splitlines())
        }
        degrees = int(float(fields["rotate"]))
        confidence = float(fields["orientation confidence"])
        if degrees not in (90, 180, 270) or confidence < OSD_MIN_CONFIDENCE:
            return 0
        with Image.open(path) as image:
            rotated = image.rotate(-degrees, expand=True)  # PIL turns counter-clockwise
        rotated.save(path)
        return degrees
    except (KeyError, ValueError, OSError):
        return 0


def ocr_image(path: Path, psm: str = SPARSE_REGION_PSM) -> str:
    commands = [
        ["tesseract", str(path), "stdout", "-l", OCR_LANGUAGES, "--psm", psm],
        [WSL_EXE, "tesseract", wsl_path(path), "stdout", "-l", OCR_LANGUAGES, "--psm", psm],
    ]
    return _first_output(commands).strip()


def _tsv_words(output: str) -> list[dict[str, object]]:
    words: list[dict[str, object]] = []
    # QUOTE_NONE, and not by preference.  Tesseract's TSV is columns of raw
    # recognised text, and «внутрішньом'я» is routinely read back with a double
    # quote for the apostrophe -- at which point the csv module treats it as an
    # opening quote and eats every following line into one field until it finds
    # a partner.  The rows that vanished came back as literal TSV inside the
    # reconstructed text: `4 1 69 1 8 0 1786 455 105 23 -1` printed on the page
    # where a lot number should have been.
    for row in csv.DictReader(io.StringIO(output), delimiter="\t", quoting=csv.QUOTE_NONE):
        value = (row.get("text") or "").strip()
        if not value:
            continue
        try:
            left, top = int(row["left"]), int(row["top"])
            _, height = int(row["width"]), int(row["height"])
            confidence = float(row.get("conf") or -1)
        except (TypeError, ValueError):
            continue
        if confidence < 0:
            continue
        words.append(
            {"left": left, "center_y": top + height / 2, "height": height, "text": value}
        )
    return words


def _row_groups(words: list[dict[str, object]]) -> list[dict[str, object]]:
    """Words whose vertical centres agree, as rows in reading order of their first word."""
    groups: list[dict[str, object]] = []
    for word in sorted(words, key=lambda item: (float(item["center_y"]), int(item["left"]))):
        selected = None
        for group in reversed(groups[-5:]):
            tolerance = max(6.0, min(float(group["height"]), float(word["height"])) * 0.7)
            if abs(float(group["center_y"]) - float(word["center_y"])) <= tolerance:
                selected = group
                break
        if selected is None:
            groups.append(
                {"center_y": word["center_y"], "height": word["height"], "words": [word]}
            )
        else:
            selected_words = selected["words"]
            selected_words.append(word)
            count = len(selected_words)
            selected["center_y"] = (
                float(selected["center_y"]) * (count - 1) + float(word["center_y"])
            ) / count
            selected["height"] = max(float(selected["height"]), float(word["height"]))
    return groups


def ocr_layout_rows(path: Path, psm: str = SPARSE_REGION_PSM) -> str:
    """OCR an image and reconstruct visual rows from TSV word coordinates."""
    commands = [
        ["tesseract", str(path), "stdout", "-l", OCR_LANGUAGES, "--psm", psm, "tsv"],
        [WSL_EXE, "tesseract", wsl_path(path), "stdout", "-l", OCR_LANGUAGES, "--psm", psm, "tsv"],
    ]
    output = _first_output(commands)
    if not output:
        return ""
    lines = []
    for group in sorted(_row_groups(_tsv_words(output)), key=lambda item: float(item["center_y"])):
        words_in_row = sorted(group["words"], key=lambda item: int(item["left"]))
        line = " ".join(str(item["text"]) for item in words_in_row).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def significant_image_regions(page) -> list[dict[str, object]]:
    page_area = float(page.width * page.height)
    regions = []
    for image in page.images:
        area = max(0.0, float((image["x1"] - image["x0"]) * (image["bottom"] - image["top"])))
        coverage = area / page_area if page_area else 0.0
        # Ignore small logos/QR codes and full-page background templates that
        # already carry a complete native text overlay.
        if 0.04 <= coverage <= 0.85:
            regions.append(
                {
                    "name": str(image.get("name") or ""),
                    "box": (
                        float(image["x0"]), float(image["top"]),
                        float(image["x1"]), float(image["bottom"]),
                    ),
                }
            )
    return regions


def ocr_pdf_image_regions(pdf_path: Path, page_index: int, regions) -> str:
    if not regions:
        return ""
    scratch_root = ROOT / "tmp"
    scratch_root.mkdir(parents=True, exist_ok=True)
    blocks = []
    with (
        tempfile.TemporaryDirectory(prefix="anamna-ocr-", dir=scratch_root) as directory,
        pdfium.PdfDocument(pdf_path) as document,
    ):
        page = document[page_index]
        source_images = {
            Path(item.name).stem: item.image
            for item in PdfReader(pdf_path).pages[page_index].images
        }
        scale = 3.5
        rendered = page.render(scale=scale).to_pil().convert("RGB")
        for index, region in enumerate(regions, start=1):
            x0, top, x1, bottom = region["box"]
            crop_path = Path(directory) / f"region-{index}.png"
            source_image = source_images.get(str(region["name"]))
            if source_image is not None:
                # Prefer the PDF's source pixels. Re-rasterizing a small table
                # can alter punctuation or decimal glyphs before OCR sees them.
                source_image.convert("RGB").save(crop_path)
            else:
                pad = 8
                box = (
                    max(0, int(x0 * scale) - pad), max(0, int(top * scale) - pad),
                    min(rendered.width, int(x1 * scale) + pad),
                    min(rendered.height, int(bottom * scale) + pad),
                )
                rendered.crop(box).save(crop_path)
            text = ocr_layout_rows(crop_path) or ocr_image(crop_path)
            if text:
                blocks.append(f"[Embedded image region {index}]\n{text}")
    return "\n".join(blocks)


def ocr_pdf_page(pdf_path: Path, page_index: int) -> str:
    """OCR a whole page as one image.

    `significant_image_regions` deliberately ignores anything covering more than
    85% of the sheet, because on a native-text report that is the letterhead
    template behind the text.  A scan is exactly the same shape and the opposite
    situation: one full-bleed image, no native text, nothing else to read.  A
    two-page photograph of a MOZ vaccination card imported in under a second
    with zero characters extracted and no error anywhere -- the page simply read
    as though it were blank.  Every kind of document a person uploads (a
    consultation note, an MRI report, a paper form) arrives this way, so the
    fallback is on page emptiness rather than on recognising a document type.
    """
    scratch_root = ROOT / "tmp"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="anamna-ocr-", dir=scratch_root) as directory:
        target = Path(directory) / "page.png"
        # A single image can be a logo beside vector text, and an embedded
        # scan can have rotation/cropping in the PDF. Render the actual visible
        # page instead of assuming its only image is the entire document.
        with pdfium.PdfDocument(pdf_path) as document:
            page = document[page_index]
            scale = min(3.5, max(1.0, PAGE_RENDER_LONG_EDGE / max(page.get_size())))
            bitmap = page.render(scale=scale)
            try:
                bitmap.to_pil().convert("RGB").save(target)
            finally:
                bitmap.close()
        upright_image_file(target)
        return ocr_layout_rows(target, FULL_PAGE_PSM) or ocr_image(target, FULL_PAGE_PSM)


def page_word_positions(page) -> list[tuple[float, float, float, str]]:
    """Every word on the page as (x0, x1, top, text), rounded to a tenth of a point.

    Rounded because nothing downstream needs sub-tenth precision and the raw
    floats make the payload three times the size for no gain.
    """
    return [
        (round(word["x0"], 1), round(word["x1"], 1), round(word["top"], 1), word["text"])
        for word in page.extract_words(x_tolerance=2, y_tolerance=2)
    ]


def _pdf_page(path: Path, index: int, page, run_ocr: bool) -> dict[str, object]:
    native_text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
    native_char_count = len(" ".join(native_text.split()))
    ocr_text = ""
    method = "native_pdf_text"
    # A logo may be the only region selected on a full-page scan.
    # Reading it successfully says nothing about the medical text
    # in the larger background image, so scans always read whole.
    if run_ocr and page.images and native_char_count < SCANNED_PAGE_CHARS:
        ocr_text = ocr_pdf_page(path, index - 1)
        if ocr_text:
            method = "page_image_ocr"
    elif run_ocr:
        ocr_text = ocr_pdf_image_regions(path, index - 1, significant_image_regions(page))
        if ocr_text:
            method = "native_pdf_text+embedded_image_ocr"
    return {
        "page_number": index,
        "native_text": native_text,
        "ocr_text": ocr_text,
        "native_text_sha256": text_sha256(native_text),
        "native_char_count": native_char_count,
        "image_count": len(page.images),
        "extraction_method": method,
        # Where each word sits on the page.  A report printed as
        # a table loses its columns the moment it is flattened
        # to text: EskuLab indents the specimen under the
        # analyte name, so «Приносний матеріал, сеча» arrives
        # looking exactly like a continuation of the name above
        # it, and the reference column -- which wraps over the
        # following lines -- looks exactly like more results.
        # Parsers that guess at this from the text alone get it
        # wrong; one that reads the x position does not.
        #
        # Deliberately not persisted.  `document_pages` stores
        # native_text and ocr_text, `document_content_hash`
        # hashes only those two, and every INSERT names its
        # columns -- so this key travels from extraction to
        # parsing in memory and stops there.
        "words": page_word_positions(page),
    }


def _extract_pdf(path: Path, run_ocr: bool) -> dict[str, object]:
    reader = PdfReader(path)
    metadata = {
        key.lstrip("/"): str(value)
        for key, value in (reader.metadata or {}).items()
        if value is not None
    }
    with pdfplumber.open(path) as pdf:
        pages = [_pdf_page(path, index, page, run_ocr) for index, page in enumerate(pdf.pages, start=1)]
    return {
        "mime_type": "application/pdf",
        "page_count": len(reader.pages),
        "metadata": metadata,
        "pages": pages,
    }


def extract_document(path: Path, run_ocr: bool = True) -> dict[str, object]:
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.casefold() == ".pdf":
        return _extract_pdf(path, run_ocr)
    with Image.open(path) as image:
        image.verify()
    # TIFFs contain multiple sheets; passing the whole file to OCR and storing
    # one page collapses their evidence (and TSV row coordinates) together.
    # Normalize phone EXIF orientation as well: OCR reads raw pixels rather
    # than the upright image the person saw in their photo viewer.
    pages = []
    with Image.open(path) as image, tempfile.TemporaryDirectory(prefix="anamna-image-") as directory:
        for index in range(getattr(image, "n_frames", 1)):
            image.seek(index)
            ocr_text = ""
            if run_ocr:
                target = Path(directory) / f"page-{index + 1}.png"
                with ImageOps.exif_transpose(image) as upright:
                    page = upright.convert("L")
                    # A Telegram photo arrives at about 1280 px: a phone
                    # screenshot of a report then carries 6 px letters, which
                    # tesseract reads as nothing at all.  Enlarging to about
                    # the size of a rendered PDF page brings the text back.
                    scale = min(3, SMALL_IMAGE_EDGE // max(page.size))
                    if scale > 1:
                        page = page.resize((page.width * scale, page.height * scale), Image.LANCZOS)
                    page.save(target)
                upright_image_file(target)
                ocr_text = ocr_layout_rows(target, FULL_PAGE_PSM) or ocr_image(target, FULL_PAGE_PSM)
            pages.append(
                {
                    "page_number": index + 1,
                    "native_text": "",
                    "ocr_text": ocr_text,
                    "native_text_sha256": text_sha256(""),
                    "native_char_count": 0,
                    "image_count": 1,
                    "extraction_method": "tesseract_ukr_eng" if ocr_text else "visual_review_required",
                }
            )
    return {
        "mime_type": mime_type,
        "page_count": len(pages),
        "metadata": {},
        "pages": pages,
    }
