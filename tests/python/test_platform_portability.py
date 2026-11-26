"""What changes between Linux, macOS and Windows, held to one behaviour.

Each of these worked on the machine it was written on and failed quietly on
another: a ZIP whose members differ only in case lost one report on macOS, a
server started from the Dock had no OCR, and every Cyrillic word of a PDF the
application printed on a Mac came out as boxes.
"""

from __future__ import annotations

import io
import os
import sys
import unicodedata
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfReader

from anamna.ingest import extract, intake
from anamna.web import health_export


def _zip(path: Path, entries: list[tuple[str, bytes]]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return path


def _one_file(directory: Path, first: str, second: str) -> bool:
    """Whether this filesystem stores `first` and `second` as the same file."""
    directory.mkdir()
    (directory / first).write_bytes(b"probe")
    return (directory / second).exists()


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("reports/report.pdf", "Reports/Report.pdf"),
        # «й» composed (NFC, what Linux and Windows write) and decomposed (NFD,
        # what an archive made on an older Mac carries): one file on APFS.
        (unicodedata.normalize("NFC", "аналіз-й.pdf"), unicodedata.normalize("NFD", "аналіз-й.pdf")),
    ],
    ids=["case", "unicode-normalization"],
)
def test_members_that_land_in_one_file_are_refused_on_every_filesystem(tmp_path: Path, first, second):
    archive = _zip(tmp_path / "bundle.zip", [(first, b"first report"), (second, b"second report")])
    folds = _one_file(tmp_path / "probe", Path(first).name, Path(second).name)
    target = tmp_path / "out"
    if folds:
        # The second write would replace the first report's bytes in place.
        with pytest.raises(intake._ArchiveCollisionError):
            intake.expand_archive(archive, target)
    else:
        produced = intake.expand_archive(archive, target)
        assert sorted(path.read_bytes() for path in produced) == [b"first report", b"second report"]


def test_tesseract_is_found_where_a_package_manager_puts_it(monkeypatch, tmp_path: Path):
    """A server started by launchd has no Homebrew on its PATH."""
    installed = tmp_path / "bin" / "tesseract"
    installed.parent.mkdir()
    installed.write_text("#!/bin/sh\n")
    installed.chmod(0o755)
    monkeypatch.setattr(extract.shutil, "which", lambda name: None)
    monkeypatch.setattr(extract, "TESSERACT_FALLBACKS", ("/nonexistent/tesseract", str(installed)))
    extract.tesseract_command.cache_clear()
    try:
        assert extract.tesseract_command() == str(installed)
        assert extract.tesseract_commands(Path("page.png"), "stdout")[0] == [str(installed), "page.png", "stdout"]
    finally:
        extract.tesseract_command.cache_clear()


def test_tesseract_on_path_wins_and_a_missing_one_stays_the_bare_name(monkeypatch):
    monkeypatch.setattr(extract, "TESSERACT_FALLBACKS", ())
    extract.tesseract_command.cache_clear()
    try:
        monkeypatch.setattr(extract.shutil, "which", lambda name: "/somewhere/tesseract")
        assert extract.tesseract_command() == "/somewhere/tesseract"
        extract.tesseract_command.cache_clear()
        monkeypatch.setattr(extract.shutil, "which", lambda name: None)
        assert extract.tesseract_command() == "tesseract"
    finally:
        extract.tesseract_command.cache_clear()


def test_wsl_is_tried_only_on_windows(monkeypatch):
    monkeypatch.setattr(extract, "ON_WINDOWS", False)
    assert [command[0] for command in extract.tesseract_commands(Path("page.png"), "stdout")] == [
        extract.tesseract_command()
    ]
    assert extract.tesseract_commands(None, "--list-langs") == [[extract.tesseract_command(), "--list-langs"]]
    monkeypatch.setattr(extract, "ON_WINDOWS", True)
    monkeypatch.setattr(extract, "wsl_path", lambda path: "/mnt/c/page.png")
    assert extract.tesseract_commands(Path("page.png"), "stdout")[1] == [
        extract.WSL_EXE, "tesseract", "/mnt/c/page.png", "stdout"
    ]


@pytest.mark.skipif(sys.platform != "darwin", reason="the fonts every Mac ships")
def test_a_mac_prints_cyrillic_with_a_font_that_has_it():
    regular, bold = health_export._font_paths()
    assert regular is not None and bold is not None, "no Cyrillic font found: exports fall back to Helvetica"
    assert str(regular).startswith(("/System/Library/Fonts/", "/Library/Fonts/"))


def test_an_exported_pdf_keeps_its_cyrillic_text():
    """Helvetica has no Cyrillic: a PDF set in it reads back as «nnnn»."""
    if health_export._font_paths() == (None, None):
        pytest.skip("no TrueType font with Cyrillic on this machine")
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas

    regular, _ = health_export._register_export_fonts()
    output = io.BytesIO()
    canvas = Canvas(output, pagesize=A4)
    canvas.setFont(regular, 12)
    canvas.drawString(72, 720, "Гемоглобін 135 г/л")
    canvas.save()
    text = PdfReader(io.BytesIO(output.getvalue())).pages[0].extract_text()
    assert "Гемоглобін" in text


def _without_file_ids(monkeypatch) -> None:
    """Make every stat report inode 0, as some network shares and FUSE mounts do."""
    real_stat = Path.stat

    def stat(self, *args, **kwargs):
        status = real_stat(self, *args, **kwargs)
        fields = list(status[:10])
        fields[1] = fields[2] = 0  # st_ino, st_dev
        return os.stat_result(fields)

    monkeypatch.setattr(Path, "stat", stat)


def test_a_filesystem_without_file_ids_still_imports_distinct_members(tmp_path: Path, monkeypatch):
    """Inode 0 for every file must not read as every member landing in one file."""
    archive = _zip(tmp_path / "bundle.zip", [("a/first.pdf", b"first report"), ("b/second.pdf", b"second report")])
    _without_file_ids(monkeypatch)
    produced = intake.expand_archive(archive, tmp_path / "out")
    assert sorted(path.read_bytes() for path in produced) == [b"first report", b"second report"]


def test_a_filesystem_without_file_ids_still_refuses_a_case_collision(tmp_path: Path, monkeypatch):
    archive = _zip(tmp_path / "bundle.zip", [("reports/report.pdf", b"first"), ("Reports/Report.pdf", b"second")])
    _without_file_ids(monkeypatch)
    with pytest.raises(intake._ArchiveCollisionError):
        intake.expand_archive(archive, tmp_path / "out")


def test_posix_install_paths_are_not_tried_on_windows(monkeypatch):
    monkeypatch.setattr(extract, "ON_WINDOWS", True)
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")
    fallbacks = extract._tesseract_fallbacks()
    assert fallbacks and all(path.endswith("tesseract.exe") for path in fallbacks)
    assert not any(path.startswith("/") for path in fallbacks)
    assert any("Program Files" in path for path in fallbacks)
    monkeypatch.setattr(extract, "ON_WINDOWS", False)
    assert extract._tesseract_fallbacks()[0] == "/opt/homebrew/bin/tesseract"
