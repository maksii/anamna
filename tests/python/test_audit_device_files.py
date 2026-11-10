"""A device export with one bad file must count it and keep importing the rest."""

from __future__ import annotations

import zipfile
from pathlib import Path

from anamna.devices import oura_export, structured

# A 14-byte FIT header that declares zero data bytes: a valid, empty activity file.
EMPTY_FIT = b"\x0e" + b"\x00" * 13


def test_a_csv_with_invalid_utf8_yields_without_raising(tmp_path: Path):
    path = tmp_path / "export.csv"
    path.write_bytes(b"a,b\n1,\xff\xfe\n")

    assert list(structured._rows(path)) == []


def test_a_garmin_calendar_date_with_a_non_integer_part_has_no_date():
    assert structured._garmin_observed_at({"metaData": {"calendarDate": [2026, "x", 3]}}) == ""


def test_a_broken_nested_zip_is_counted_and_the_good_one_still_counts(tmp_path: Path):
    with zipfile.ZipFile(tmp_path / "good.zip", "w") as archive:
        archive.writestr("activity.fit", EMPTY_FIT)
    (tmp_path / "broken.zip").write_bytes(b"PK\x03\x04garbage")

    counts = structured._garmin_fit_counts(tmp_path)

    assert counts["invalid"] == 1
    assert counts["entries"] == 1


def test_a_nested_member_over_the_size_cap_is_skipped_unread(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(structured, "MAX_NESTED_MEMBER_BYTES", 8)
    with zipfile.ZipFile(tmp_path / "big.zip", "w") as archive:
        archive.writestr("activity.fit", EMPTY_FIT)

    assert structured._fit_archive_counts(tmp_path / "big.zip") == {"skipped_large": 1}


def test_an_undecodable_oura_csv_yields_no_rows_and_no_header_without_raising(tmp_path: Path):
    path = tmp_path / "dailysleep.csv"
    path.write_bytes(b"id;score\n1;\xff\xfe\n")

    assert list(oura_export._csv_rows(path)) == []
    assert oura_export._csv_header(path) == set()
