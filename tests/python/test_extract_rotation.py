from __future__ import annotations

import subprocess

import pytest
from PIL import Image, ImageDraw, ImageFont

from anamna.ingest import extract


def _osd_available() -> bool:
    try:
        result = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "osd" in result.stdout.split()


needs_osd = pytest.mark.skipif(not _osd_available(), reason="tesseract with osd.traineddata not available")

LINES = ["Hemoglobin and glucose report", "Patient visited the clinic yesterday morning", "Results were within normal range"]


def _page(path):
    image = Image.new("L", (1600, 900), 255)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 56)
    except OSError:
        font = ImageFont.load_default(56)
    for index, line in enumerate(LINES * 2):
        draw.text((60, 60 + index * 130), line, fill=0, font=font)
    return image


def _words(path) -> str:
    # psm 11 (sparse) does no orientation handling of its own, unlike psm 3.
    return subprocess.run(
        ["tesseract", str(path), "stdout", "--psm", "11", "-l", "eng"], capture_output=True, text=True
    ).stdout.lower()


@needs_osd
@pytest.mark.parametrize("turn", [90, 270])
def test_sideways_page_is_rotated_upright(tmp_path, turn):
    target = tmp_path / "page.png"
    _page(target).rotate(turn, expand=True).save(target)
    applied = extract.upright_image_file(target)

    assert applied == turn  # PIL rotates counter-clockwise; the fix is the same angle clockwise
    with Image.open(target) as image:
        assert image.width > image.height
    assert "hemoglobin" in _words(target)


@needs_osd
def test_upright_page_is_left_alone(tmp_path):
    target = tmp_path / "page.png"
    _page(target).save(target)
    before = target.read_bytes()
    assert extract.upright_image_file(target) == 0
    assert target.read_bytes() == before


@pytest.mark.parametrize(
    "output",
    ["", "garbage", "Rotate: 90\nOrientation confidence: 0.5\n", "Rotate: abc\nOrientation confidence: 9\n"],
)
def test_osd_failure_or_low_confidence_leaves_image_unchanged(tmp_path, monkeypatch, output):
    target = tmp_path / "page.png"
    Image.new("L", (40, 20), 255).save(target)
    before = target.read_bytes()
    monkeypatch.setattr(extract, "_first_output", lambda commands: output)
    assert extract.upright_image_file(target) == 0
    assert target.read_bytes() == before


def test_confident_osd_rotates_clockwise(tmp_path, monkeypatch):
    target = tmp_path / "page.png"
    Image.new("L", (40, 20), 255).save(target)
    monkeypatch.setattr(extract, "_first_output", lambda commands: "Rotate: 90\nOrientation confidence: 8.0\n")
    assert extract.upright_image_file(target) == 90
    with Image.open(target) as image:
        assert image.size == (20, 40)
