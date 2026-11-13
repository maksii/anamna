"""One quantity, two paths: a document's reading and a device's daily value.

`panels.MEASUREMENT_TWINS` is the only place a concept and a device metric are
paired.  These tests hold every page and export to it: a same-measurement twin
is one series on one page with every row labelled by source, a home-monitoring
PDF never repeats a device day, a clinic visit is never dropped, and a related
measurement is linked with a reason instead of merged.
"""

from __future__ import annotations

from markupsafe import escape
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from anamna.config import Settings, resource_path
from anamna.correlation import TRIVIAL_PAIRS
from anamna.db import connect, migrate, utc_now
from anamna.devices.apple_health import ECG_HEART_RATE
from anamna.devices.catalog import HEALTHKIT_METRICS
from anamna.i18n import activate_locale, reset_locale, t
from anamna.ingest.pipeline import ensure_vendor, seed_concepts
from anamna.locales.messages import MESSAGES
from anamna.panels import MEASUREMENT_TWINS, SAME_DEVICE_KEYS, TWIN_OF_DEVICE, device_twins
from anamna.reference import canonical_unit
from anamna.security import create_session, create_user
from anamna.web import app as web
from anamna.web.app import create_app


PASSWORD = "a-long-local-password"


def _build(tmp_path: Path) -> tuple[Settings, str, TestClient]:
    sources = tmp_path / "sources"
    sources.mkdir(exist_ok=True)
    settings = Settings(
        database_path=tmp_path / "health.sqlite3", source_dir=sources,
        secret_key="linked-test-secret", session_days=1,
    )
    migrate(settings)
    user_id = create_user(settings, "linked@example.test", "Linked", PASSWORD)
    with connect(settings) as connection:
        seed_concepts(connection)
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Test Patient', '1990-03-14', 'male', ?)""",
            (f"patient-{user_id}", user_id, utc_now()),
        )
        connection.execute(
            """INSERT INTO device_imports(id, owner_user_id, patient_id, vendor_id, adapter_key,
                   source_path, source_fingerprint, source_bytes, imported_at)
               VALUES ('imp-1', ?, ?, ?, 'garmin', 'export.zip', 'fp-1', 10, ?)""",
            (user_id, f"patient-{user_id}", ensure_vendor(connection, "Garmin", None), utc_now()),
        )
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "en")
    web.invalidate_catalog()
    return settings, user_id, client


def _document(settings: Settings, user_id: str, document_id: str, vendor: str, clinical_type: str, day: str) -> None:
    with connect(settings) as connection:
        source = settings.source_dir / f"{document_id}.pdf"
        source.write_text(document_id, encoding="utf-8")
        connection.execute(
            """INSERT INTO documents(
                   id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type,
                   extraction_strategy, classification_confidence, report_date, imported_at, status
               ) VALUES (?, ?, ?, ?, ?, ?, 'application/pdf', 10, ?, 1, ?, ?, 'native_text', 1, ?, ?, 'final')""",
            (
                document_id, user_id, f"patient-{user_id}", ensure_vendor(connection, vendor, None),
                f"{document_id}.pdf", str(source), f"sha-{document_id}", f"{day}__{document_id}",
                clinical_type, day, utc_now(),
            ),
        )


def _observation(settings, user_id, obs_id, document_id, concept_id, value, unit, observed_at) -> None:
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO observations(
                   id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
                   value_type, value_numeric, unit_raw, observed_at, verification_status,
                   extraction_method, confidence, evidence_text, parser_version, created_at)
               VALUES (?, ?, ?, ?, 1, ?, ?, 'numeric', ?, ?, ?, 'extracted', 'test', 0.9, 'evidence', 'test', ?)""",
            (obs_id, user_id, f"patient-{user_id}", document_id, concept_id, concept_id, value, unit, observed_at, utc_now()),
        )
    web.invalidate_catalog()


def _device_day(settings, user_id, key, day, value, unit, *, vendor="Garmin", name="Garmin Index Scale") -> None:
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO device_metric_days(id, owner_user_id, patient_id, import_id,
                   source_name, source_vendor, metric_key, metric_name, category, day,
                   aggregation, unit, value, sample_count, created_at)
               VALUES (?, ?, ?, 'imp-1', ?, ?, ?, ?, 'device_body', ?, 'latest', ?, ?, 1, ?)""",
            (
                f"dmd-{key}-{day}-{vendor}", user_id, f"patient-{user_id}", name, vendor, key,
                key.replace("_", " ").capitalize(), day, unit, value, utc_now(),
            ),
        )
    web.invalidate_catalog()


def _device_units() -> dict[str, str]:
    units = {definition.key: definition.unit for definition in HEALTHKIT_METRICS.values()}
    units[ECG_HEART_RATE.key] = ECG_HEART_RATE.unit
    # Written inline by devices/structured.py (Garmin's blood-pressure log).
    units.setdefault("blood_pressure_pulse", "bpm")
    return units


def test_same_twins_fold_to_one_unit(tmp_path: Path):
    """A twin whose device unit folded differently would split its one series
    into two and every curated rule written in the concept's unit would skip it."""
    settings, _, _ = _build(tmp_path)
    units = _device_units()
    with connect(settings) as connection:
        preferred = dict(connection.execute("SELECT id, preferred_unit FROM concepts"))
    for key in SAME_DEVICE_KEYS:
        concept_id = TWIN_OF_DEVICE[key][0]
        assert canonical_unit(units[key]) == canonical_unit(preferred[concept_id]), key
    # The method twin is the same quantity in the same unit, too.
    assert canonical_unit(units["blood_oxygen"]) == canonical_unit(preferred["oxygen-saturation-spo2"])


def test_same_twins_are_judged_by_one_library_entry(tmp_path: Path):
    """The device copy of each entry had drifted (body_weight cited no Ukrainian
    source); one entry now serves both ids, every source kept."""
    library = json.loads(resource_path("reference_library.json").read_text(encoding="utf-8"))
    entries = {item["concept_id"]: item for item in library["analytes"]}
    assert not SAME_DEVICE_KEYS & set(entries)
    assert "moz-nastanova-00167" in entries["body-weight"]["source_ids"]
    assert "apple-mobility-metrics-whitepaper-2022" in entries["body-height"]["source_ids"]
    settings, _, _ = _build(tmp_path)
    with connect(settings) as connection:
        def rules(concept_id: str) -> list[tuple]:
            return sorted(
                tuple(row) for row in connection.execute(
                    """SELECT label, lower_bound, upper_bound, unit, interpretation, sex, reference_set_id
                       FROM curated_reference_rules WHERE concept_id=?""",
                    (concept_id,),
                )
            )

        for key in SAME_DEVICE_KEYS:
            concept_id = TWIN_OF_DEVICE[key][0]
            assert rules(key) == rules(concept_id), key
        assert rules("systolic_blood_pressure"), "the device id is still judged"


def test_merged_page_shows_both_sources_with_labels(tmp_path: Path):
    settings, user_id, client = _build(tmp_path)
    _document(settings, user_id, "visit-1", "Veselka", "consultation", "2025-03-01")
    _observation(settings, user_id, "obs-w1", "visit-1", "body-weight", 108.0, "kg", "2025-03-01")
    for day, value in (("2025-02-28", 108.4), ("2025-03-01", 108.2), ("2025-03-02", 107.9)):
        _device_day(settings, user_id, "body_weight", day, value, "kg")
    page = client.get("/metrics/body-weight").text
    history = page.split('id="reading-history"', 1)[1].split("</section>", 1)[0]
    # Every row says where it came from, in text.
    assert history.count('data-source="device"') >= 3
    assert history.count('class="an-source-tag" data-source="clinic"') == 1
    assert "Medical document" in history and "Device" in history
    # The visit on a day the scale also weighed is kept beside it.
    assert history.count("<tr") == 1 + 4
    # The chart names its markers, and draws clinic readings differently.
    assert 'class="an-chart-legend"' in page and "Square: a reading from a medical document" in page
    points = json.loads(page.split('id="chart-data">', 1)[1].split("</script>", 1)[0])
    assert {point["source"] for point in points} == {"clinic", "device"}
    assert all(point["document_url"].startswith("/devices/metrics/") for point in points if point["source"] == "device")
    # One card on the landing page, carrying both paths; no device card beside it.
    landing = client.get("/results").text
    assert 'href="/metrics/body-weight"' in landing
    assert 'href="/devices/metrics/body_weight"' not in landing
    with connect(settings) as connection:
        card = web._by_id(web._metric_catalog(connection, user_id))["body-weight"]
    assert card["sources_text"] == t("twin.sources_both")
    assert card["count"] == 4


def test_page_renders_from_device_days_alone(tmp_path: Path):
    settings, user_id, client = _build(tmp_path)
    _device_day(settings, user_id, "body_weight", "2025-03-02", 107.9, "kg")
    response = client.get("/metrics/body-weight")
    assert response.status_code == 200
    assert "107.9" in response.text
    # A concept with neither is still a 404, not an empty page.
    assert client.get("/metrics/body-height").status_code == 404


def test_devices_overview_shows_a_twin_on_its_concept_card(tmp_path: Path):
    """Weight and blood pressure are core device metrics and same-measurement
    twins, so the device catalog has no card of their own; the overview reads
    the concept's card instead of failing on an unjudged row."""
    settings, user_id, client = _build(tmp_path)
    _device_day(settings, user_id, "body_weight", "2025-03-02", 107.9, "kg")
    _device_day(settings, user_id, "steps", "2025-03-02", 8000, "count", vendor="Oura", name="Oura")
    response = client.get("/devices")
    assert response.status_code == 200
    assert 'href="/metrics/body-weight"' in response.text
    assert "107.9" in response.text


def test_home_pdf_duplicate_is_shown_once_and_clinic_reading_is_kept(tmp_path: Path):
    """The Garmin 4-week report printed the cuff's readings; matched on day and
    maker, never on value (the PDF rounds differently).  A clinic pulse taken
    the same morning is a different reading and stays."""
    settings, user_id, client = _build(tmp_path)
    _document(settings, user_id, "garmin-pdf", "Garmin Connect", "blood_pressure", "2025-08-01")
    _document(settings, user_id, "visit-1", "Veselka", "consultation", "2025-08-01")
    _observation(settings, user_id, "obs-sys-dup", "garmin-pdf", "systolic-blood-pressure", 122.0, "mmHg", "2025-08-01T07:10:00")
    _observation(settings, user_id, "obs-sys-only", "garmin-pdf", "systolic-blood-pressure", 125.0, "mmHg", "2025-07-20T07:10:00")
    _observation(settings, user_id, "obs-pulse-dup", "garmin-pdf", "pulse-rate", 70.0, "bpm", "2025-08-01T07:10:00")
    _observation(settings, user_id, "obs-pulse-visit", "visit-1", "pulse-rate", 76.0, "уд/хв", "2025-08-01")
    # Relayed through Apple Health: still Garmin's reading.
    _device_day(settings, user_id, "systolic_blood_pressure", "2025-08-01", 119.0, "mmHg",
                vendor="OpenWearables", name="OpenWearables · apple · Connect · iPhone18,1")
    _device_day(settings, user_id, "blood_pressure_pulse", "2025-08-01", 68.0, "bpm",
                name="Garmin Connect blood pressure")
    with connect(settings) as connection:
        systolic = web._linked_observation_rows(connection, user_id, "systolic-blood-pressure")
        pulse = web._linked_observation_rows(connection, user_id, "pulse-rate")
    assert [row["id"] for row in systolic if not row.get("is_device")] == ["obs-sys-only"]
    assert [row["value_numeric"] for row in systolic if row.get("is_device")] == [119.0]
    assert {row["id"] for row in pulse if not row.get("is_device")} == {"obs-pulse-visit"}
    assert len([row for row in pulse if row.get("is_device")]) == 1
    page = client.get("/metrics/pulse-rate").text
    history = page.split('id="reading-history"', 1)[1].split("</section>", 1)[0]
    assert history.count("<tr") == 1 + 2


def test_twins_link_both_ways_and_related_ones_say_why(tmp_path: Path):
    settings, user_id, client = _build(tmp_path)
    _document(settings, user_id, "visit-1", "Veselka", "consultation", "2025-08-01")
    _observation(settings, user_id, "obs-pulse", "visit-1", "pulse-rate", 76.0, "уд/хв", "2025-08-01")
    _device_day(settings, user_id, "body_weight", "2025-08-01", 108.0, "kg")
    _device_day(settings, user_id, "resting_heart_rate", "2025-08-01", 55.0, "bpm", vendor="Apple Health", name="Apple Watch")
    weight = client.get("/metrics/body-weight").text
    assert 'href="/devices/metrics/body_weight"' in weight
    device = client.get("/devices/metrics/body_weight").text
    assert 'href="/metrics/body-weight"' in device and 'href="/panels/body"' in device
    assert t("twin.compare_page") in device
    pulse = client.get("/metrics/pulse-rate").text
    assert 'href="/devices/metrics/resting_heart_rate"' in pulse
    assert str(escape(t("twin.why_resting_heart_rate"))) in pulse
    resting = client.get("/devices/metrics/resting_heart_rate").text
    assert 'href="/metrics/pulse-rate"' in resting
    # Related is never merged: the watch's 55 is not a pulse-rate reading.
    with connect(settings) as connection:
        assert all(not row.get("is_device") for row in web._linked_observation_rows(connection, user_id, "pulse-rate"))


def test_panel_lists_a_twin_once_and_counts_it_once(tmp_path: Path):
    settings, user_id, _ = _build(tmp_path)
    _document(settings, user_id, "garmin-pdf", "Garmin Connect", "blood_pressure", "2024-07-07")
    _observation(settings, user_id, "obs-sys", "garmin-pdf", "systolic-blood-pressure", 122.0, "mmHg", "2024-07-07T07:00:00")
    _device_day(settings, user_id, "systolic_blood_pressure", "2025-02-13", 119.0, "mmHg", name="Garmin Connect blood pressure")
    with connect(settings) as connection:
        panels = {panel["id"]: panel for panel in web._panel_cards(connection, user_id)}
    members = [member["id"] for member in panels["blood_pressure"]["members"]]
    assert members.count("systolic-blood-pressure") == 1
    assert not [member for member in members if str(member).startswith("device:")]
    systolic = next(m for m in panels["blood_pressure"]["members"] if m["id"] == "systolic-blood-pressure")
    assert systolic["value_text"] == "119" and systolic["latest_date"] == "2025-02-13"
    assert panels["blood_pressure"]["present_count"] + len(panels["blood_pressure"]["missing_members"]) == panels["blood_pressure"]["member_count"]


def test_exports_list_a_twin_once(tmp_path: Path):
    settings, user_id, client = _build(tmp_path)
    _device_day(settings, user_id, "body_weight", "2025-03-02", 107.9, "kg")
    with connect(settings) as connection:
        options = {str(card["id"]) for card in web._export_options(connection, user_id)}
        payload = web._health_export_payload(connection, user_id, ["body-weight"], "auto")
    assert "body-weight" in options and "device:body_weight" not in options
    assert payload["metrics"][0]["point_count"] == 1
    prompt = client.get("/api/ai-export").text
    devices = prompt.split(t("ai.devices_heading"), 1)[1] if t("ai.devices_heading") in prompt else ""
    assert "Body weight" in prompt.split(t("ai.devices_heading"), 1)[0]
    assert "Body weight" not in devices


def test_correlation_trivial_pairs_come_from_the_map():
    for concept_id, twins in MEASUREMENT_TWINS.items():
        for key, relation in twins:
            pair = frozenset((concept_id, f"device:{key}"))
            assert (pair in TRIVIAL_PAIRS) == (relation in {"same", "method"}), (concept_id, key)


def test_device_page_correlation_reads_the_concept(tmp_path: Path):
    assert web._twin_concept_id("device:body_weight") == "body-weight"
    assert web._twin_concept_id("device:resting_heart_rate") == "device:resting_heart_rate"
    assert web._twin_concept_id("pulse-rate") == "pulse-rate"


def test_twin_strings_exist_in_both_locales(tmp_path: Path):
    keys = [key for key in MESSAGES if key.startswith("twin.")]
    assert keys
    for key in keys:
        assert MESSAGES[key].get("en") and MESSAGES[key].get("uk"), key
    for twins in MEASUREMENT_TWINS.values():
        for key, relation in twins:
            assert f"twin.why_{key}" in MESSAGES
            assert f"twin.relation_{relation}" in MESSAGES
    # No AI-styled characters in the new copy.
    for key in keys:
        for text in MESSAGES[key].values():
            assert not re.search("[—→“”]", text), key
    settings, user_id, client = _build(tmp_path)
    _document(settings, user_id, "visit-1", "Veselka", "consultation", "2025-03-01")
    _observation(settings, user_id, "obs-w1", "visit-1", "body-weight", 108.0, "kg", "2025-03-01")
    _device_day(settings, user_id, "body_weight", "2025-03-02", 107.9, "kg")
    client.cookies.set("anamna_lang", "uk")
    page = client.get("/metrics/body-weight").text
    token = activate_locale("uk")
    try:
        for key in ("twin.source_clinic", "twin.source_device", "twin.legend_clinic", "twin.history_note"):
            assert t(key) in page, key
    finally:
        reset_locale(token)
    assert "Medical document" not in page


def test_device_twins_reads_the_map():
    assert device_twins("pulse-rate", "same") == ("blood_pressure_pulse",)
    assert device_twins("pulse-rate", "related") == ("resting_heart_rate", "daily_heart_rate")
    assert device_twins("glucose", "same") == ()


def test_stale_pdf_reading_is_not_an_attention_item(tmp_path: Path):
    """A systolic 142 parsed out of a 2025 Garmin PDF headed the attention list
    while the same cuff had streamed 119 since.  One card, judged on its newest
    reading, whichever path it came by."""
    settings, user_id, _ = _build(tmp_path)
    _document(settings, user_id, "garmin-pdf", "Garmin Connect", "blood_pressure", "2025-02-13")
    _observation(settings, user_id, "obs-sys", "garmin-pdf", "systolic-blood-pressure", 142.0, "mmHg", "2025-02-13T07:00:00")
    _device_day(settings, user_id, "systolic_blood_pressure", "2026-08-30", 119.0, "mmHg", name="Garmin Connect blood pressure")
    with connect(settings) as connection:
        catalog = web._metric_catalog(connection, user_id)
    systolic = web._by_id(catalog)["systolic-blood-pressure"]
    assert systolic["verdict"]["interpretation"] == "normal"
    assert not [card for card in web._attention_cards(catalog) if "systolic" in str(card["id"])]
