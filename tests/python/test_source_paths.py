"""Recorded source paths carry the prefix of the machine that imported them;
the file is read from this installation's sources directory."""
from dataclasses import replace

from anamna.config import get_settings, resolve_source_path


def test_configured_sources_win_over_a_recorded_path_that_still_exists(tmp_path):
    old, new = tmp_path / "old" / "sources", tmp_path / "new" / "sources"
    for root in (old, new):
        (root / "2025").mkdir(parents=True)
        (root / "2025" / "report.pdf").write_bytes(b"%PDF")
    settings = replace(get_settings(), source_dir=new)
    assert resolve_source_path(settings, str(old / "2025" / "report.pdf")) == new / "2025" / "report.pdf"


def test_container_path_maps_into_the_local_directory(tmp_path):
    (tmp_path / "sources" / "uploads").mkdir(parents=True)
    (tmp_path / "sources" / "uploads" / "a.pdf").write_bytes(b"%PDF")
    settings = replace(get_settings(), source_dir=tmp_path / "sources")
    assert resolve_source_path(settings, "/data/sources/uploads/a.pdf") == tmp_path / "sources" / "uploads" / "a.pdf"


def test_a_path_outside_any_sources_directory_is_kept(tmp_path):
    elsewhere = tmp_path / "export.zip"
    elsewhere.write_bytes(b"PK")
    settings = replace(get_settings(), source_dir=tmp_path / "sources")
    assert resolve_source_path(settings, str(elsewhere)) == elsewhere
