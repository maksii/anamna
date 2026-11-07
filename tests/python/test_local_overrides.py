"""An installation's own corrections live in data/local_overrides.json beside
the database, never in code: they name one person's files and devices."""
import json

import pytest

from anamna import config
from anamna.devices import catalog
from anamna.ingest.classifier import classify_document


@pytest.fixture
def overrides(tmp_path, monkeypatch):
    def write(content: dict) -> None:
        (tmp_path / config.LOCAL_OVERRIDES_FILE).write_text(json.dumps(content), encoding="utf-8")
        config._read_local_overrides.cache_clear()
        catalog.canonical_source_vendor.cache_clear()

    monkeypatch.setenv("ANAMNA_DB", str(tmp_path / "anamna.sqlite3"))
    yield write
    config._read_local_overrides.cache_clear()
    catalog.canonical_source_vendor.cache_clear()


PAGES = [{"page_number": 1, "text": "Some scanned page"}]


def test_no_file_means_no_overrides(overrides):
    config._read_local_overrides.cache_clear()
    assert config.local_overrides() == {}


def test_classifier_applies_a_matching_override_only(overrides):
    overrides({"classifier": [{"filename_contains": ["2020-01-02__clinic__"], "set": {"notes": "Checked by hand."}}]})
    matched = classify_document("2020-01-02__clinic__scan.pdf", "application/pdf", PAGES)
    other = classify_document("2020-01-03__clinic__scan.pdf", "application/pdf", PAGES)
    assert matched.notes == "Checked by hand."
    assert other.notes != "Checked by hand."


def test_renamed_apple_device_counts_as_apple(overrides):
    overrides({})
    assert catalog.canonical_source_vendor("Kitchen phone") != catalog.canonical_source_vendor("iPhone")
    overrides({"apple_device_names": ["Kitchen phone"]})
    assert catalog.canonical_source_vendor("Kitchen phone") == catalog.canonical_source_vendor("iPhone")


def test_malformed_file_is_an_error_not_silence(tmp_path, overrides):
    (tmp_path / config.LOCAL_OVERRIDES_FILE).write_text("{not json", encoding="utf-8")
    config._read_local_overrides.cache_clear()
    with pytest.raises(ValueError):
        config.local_overrides()
