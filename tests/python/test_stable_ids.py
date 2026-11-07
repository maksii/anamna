"""Stored row ids are uuid5 values under namespaces named after the project's
former name.  The rename must never reach them: a different namespace re-keys
every vendor, device day and derived value, and a re-import then duplicates
what is already stored instead of replacing it."""
import uuid

from anamna import derived, reference
from anamna.ingest.pipeline import stable_id


def test_stable_ids_keep_their_pre_rename_values():
    assert stable_id("vendor", "Synevo") == "525f3ff0-b01c-5642-8f03-5dd0dac47dd9"
    assert stable_id("device-metric-day", "u:Oura:steps:2026-01-01") == "64d62cab-3976-55b4-882f-b095bc740b0e"
    assert str(derived._NAMESPACE) == "1caabb85-cdd1-5315-a547-62eb7d091845"
    assert str(reference._LIBRARY_NAMESPACE) == "a92eb33a-9556-53b4-801b-560d8b39aa0a"


def test_pinned_values_are_the_original_formula():
    original = uuid.uuid5(uuid.uuid5(uuid.NAMESPACE_URL, "health-ledger/vendor"), "Synevo")
    assert str(original) == "525f3ff0-b01c-5642-8f03-5dd0dac47dd9"
