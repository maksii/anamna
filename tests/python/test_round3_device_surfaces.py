"""Synthetic patient identity, sample-age and opaque-field surface proofs."""
from __future__ import annotations

import json
from html import unescape

from anamna.db import connect, utc_now
from anamna.devices.importer import import_device_export
from anamna.devices.queries import device_metric_catalog
from anamna.devices.reconcile import source_key
from anamna.i18n import activate_locale, reset_locale, t
from anamna.web import app as web

from test_linked_metrics import _build, _device_day
from test_reference import _rule


def _other_patient(db, owner, source):
    db.execute("INSERT OR IGNORE INTO patients(id,owner_user_id,display_name,created_at) VALUES ('other-patient',?,'Synthetic other patient',?)", (owner, utc_now()))
    db.execute("UPDATE device_metric_days SET patient_id='other-patient' WHERE source_name=?", (source,))


def _age_rules(db, key, *, child_low=0, child_high=10, adult_low=20, adult_high=30):
    db.execute("DELETE FROM curated_reference_rules WHERE concept_id=?", (key,))
    db.execute("INSERT OR IGNORE INTO reference_sets(id,name,publisher,source_url,reviewed_at,official) VALUES ('synthetic-age-source','Synthetic test rules','Synthetic fixture','https://example.invalid/age-test','2025-01-01',0)")
    for name, low, high, age_min, age_max in (("child", child_low, child_high, 0, 18), ("adult", adult_low, adult_high, 18, None)):
        _rule(db, key, id=f"synthetic-{key}-{name}", reference_set_id="synthetic-age-source",
              label=f"Synthetic {name} band", unit="%" if key == "blood_oxygen" else "score",
              lower_bound=low, upper_bound=high, age_min_years=age_min, age_max_years=age_max,
              priority=9000)


def test_bp_export_correlation_and_twin_counts_exclude_other_patient_evidence(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _device_day(settings, owner, "systolic_blood_pressure", "2025-01-01", 120, "mmHg")
    _device_day(settings, owner, "systolic_blood_pressure", "2025-01-01", 180, "mmHg", vendor="Apple Health", name="Synthetic other")
    _device_day(settings, owner, "sleep_duration", "2025-01-02", 8, "hours", vendor="Apple Health", name="Synthetic other")
    with connect(settings) as db:
        _other_patient(db, owner, "Synthetic other")
        second = dict(db.execute("SELECT * FROM device_metric_days WHERE metric_key='systolic_blood_pressure' AND patient_id='other-patient'").fetchone())
        db.execute("INSERT INTO device_source_preferences(owner_user_id,preference_group,source_key,updated_at) VALUES (?,?,?,?)", (owner, "systolic_blood_pressure", source_key(second), utc_now()))
        assert web._bp_series(db, owner, {"id": "device:systolic_blood_pressure", "series": []}) == [{"date": "2025-01-01", "value": 120}]
        assert [row["numeric"] for row in web._export_device_rows(db, owner, "systolic_blood_pressure")] == [120]
        assert not any(item["key"] == "sleep_duration" for item in web._correlation_device_options(db, owner))
        assert web._twin_days(db, owner, ["systolic_blood_pressure", "sleep_duration"]) == {"systolic_blood_pressure": 1}


def test_device_card_and_detail_judge_age_on_the_recorded_day(tmp_path):
    settings, owner, client = _build(tmp_path)
    _device_day(settings, owner, "synthetic_age_metric", "2000-01-01", 5, "score")
    with connect(settings) as db:
        db.execute("UPDATE patients SET date_of_birth='1990-01-01' WHERE owner_user_id=?", (owner,))
        _age_rules(db, "synthetic_age_metric")
        [raw] = device_metric_catalog(db, owner, patient_id="patient-" + owner)
        card = web._device_card(db, raw, 36, "male", {})
        assert card["verdict"]["band_label"] == "Synthetic child band"
    web.invalidate_catalog()
    page = client.get('/devices/metrics/synthetic_age_metric')
    assert page.status_code == 200
    assert page.context["verdict"]["band_label"] == "Synthetic child band"


def test_twin_and_correlation_counts_track_selectable_days_and_same_second_repair(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _device_day(settings, owner, "blood_oxygen", "2025-01-01", float("inf"), "%")
    _device_day(settings, owner, "blood_oxygen", "2025-01-02", 97, "%")
    _device_day(settings, owner, "body_weight", "2025-01-01", -1, "kg")
    with connect(settings) as db:
        options = {item["key"]: item for item in web._correlation_device_options(db, owner)}
        assert options["blood_oxygen"]["days"] == 1
        assert "body_weight" not in options
        assert web._twin_days(db, owner, ["blood_oxygen", "body_weight"]) == {"blood_oxygen": 1}
        db.execute("UPDATE device_metric_days SET value=96 WHERE metric_key='blood_oxygen' AND day='2025-01-01'")
        assert web._twin_days(db, owner, ["blood_oxygen"]) == {"blood_oxygen": 2}
        assert {item["key"]: item["days"] for item in web._correlation_device_options(db, owner)}["blood_oxygen"] == 2


def test_alternate_method_series_keeps_primary_identity_and_sample_age(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _device_day(settings, owner, "blood_oxygen", "2000-01-01", 97, "%")
    _device_day(settings, owner, "blood_oxygen", "2000-01-01", 50, "%", vendor="Apple Health", name="Synthetic other")
    with connect(settings) as db:
        _other_patient(db, owner, "Synthetic other")
        db.execute("UPDATE patients SET date_of_birth='1990-01-01' WHERE id=?", ("patient-" + owner,))
        _age_rules(db, "blood_oxygen", child_low=90, child_high=100, adult_low=30, adult_high=40)
        concept = db.execute("SELECT * FROM concepts WHERE id='oxygen-saturation-spo2'").fetchone()
        [series] = web._method_series(db, owner, concept, "1990-01-01", 36, "male")
        assert series["value_text"].startswith("97")
        assert series["verdict"]["band_label"] == "Synthetic child band"
        assert {point["value"] for point in series["points"]} == {97}


def test_opaque_garmin_impedance_is_explained_bilingually_without_invented_units(tmp_path):
    settings, owner, client = _build(tmp_path)
    source = settings.source_dir / "synthetic_userBioMetrics.json"
    source.write_text(json.dumps([
        {"metaData": {"calendarDate": f"2025-01-0{index + 1}T12:00:00"},
         "weight": {"sourceType": "INDEX_SCALE", "weight": 80000, "rawImpedance": value}}
        for index, value in enumerate((0, 500))
    ]), encoding="utf-8")
    import_device_export(settings, owner_user_id=owner, patient_id="patient-" + owner, vendor_key="garmin", source=source)
    for lang in ("en", "uk"):
        client.cookies.set("anamna_lang", lang)
        page = client.get('/devices')
        assert page.status_code == 200
        token = activate_locale(lang)
        try:
            assert t("devices.raw_impedance_heading") in page.text
            assert t("devices.raw_impedance_explanation") in unescape(page.text)
        finally:
            reset_locale(token)
        assert 'weight.rawImpedance' in page.text
        assert '500 Ω' not in page.text and '500 ohm' not in page.text
