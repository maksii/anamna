"""The ECG page, device notifications and workout labels read in both locales.

Audit 2026-11-06: on the Ukrainian locale the ECG page showed "Sinus Rhythm",
"78 bpm" and "25mm/s, 10mm/mV" in English, RR / SDNN / RMSSD went unexplained,
and workout types arrived as `walking` beside `Walking`.
"""

from __future__ import annotations

import math
import sqlite3

import pytest
from fastapi.testclient import TestClient

from anamna.config import Settings
from anamna.db import migrate
from anamna.devices import ecg
from anamna.devices.apple_health import DEVICE_EVENTS
from anamna.devices.workout_reconcile import reconcile_workouts, workout_label
from anamna.health import display_unit
from anamna.i18n import activate_locale, reset_locale, t, translate_phrase
from anamna.security import create_session, create_user
from anamna.web.app import create_app

APPLE_HEADER = """Name,Test
Recorded Date,2024-01-04 13:38:52 +0300
Classification,Sinus Rhythm
Symptoms,Fluttering
Device,"Watch7,5"
Sample Rate,512 hertz


Lead,Lead I
Unit,µV

"""


class locale:
    def __init__(self, code):
        self.code = code

    def __enter__(self):
        self.token = activate_locale(self.code)

    def __exit__(self, *exc):
        reset_locale(self.token)


def _beats_csv(path, seconds=10, rate=512, rr=0.8):
    samples = [0.0] * (seconds * rate)
    for beat in range(int((seconds - 1) / rr)):
        centre = (0.4 + beat * rr) * rate
        for index in range(int(centre) - 20, int(centre) + 21):
            if 0 <= index < len(samples):
                samples[index] += 1000 * math.exp(-0.5 * ((index - centre) / 6) ** 2)
    path.write_text(APPLE_HEADER + "\n".join(f"{v:.3f}" for v in samples) + "\n", encoding="utf-8")


@pytest.fixture()
def ecg_client(tmp_path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "ecg-i18n-secret")
    (tmp_path / "sources").mkdir()
    migrate(settings)
    user_id = create_user(settings, "ecg-i18n@test.local", "ECG User", "password12345")
    source = tmp_path / "sources" / "ecg.csv"
    _beats_csv(source)
    db = sqlite3.connect(tmp_path / "health.sqlite3")  # foreign keys off by default
    db.execute(
        """INSERT INTO device_events(id, owner_user_id, patient_id, import_id, source_name, source_vendor,
               event_type, started_at, value_text, value_numeric, unit, source_file, created_at)
           VALUES ('ecg1', ?, 'p', 'i', 'Apple Watch', 'Apple Health', 'Electrocardiogram',
                   '2024-01-04T13:38:52', 'Sinus Rhythm', 78, 'bpm', ?, '2024-01-04')""",
        (user_id, str(source)),
    )
    db.commit()
    db.close()
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    return client


def _page(client, code):
    client.cookies.set("anamna_lang", code)
    response = client.get("/devices/ecg/ecg1")
    assert response.status_code == 200
    return response.text


def test_ecg_page_is_ukrainian_in_uk(ecg_client):
    page = _page(ecg_client, "uk")
    assert "Синусовий ритм" in page
    assert "<strong>Sinus Rhythm</strong>" not in page
    assert "25 мм/с, 10 мм/мВ" in page
    assert "mm/s" not in page
    assert "78 уд/хв" in page and " bpm" not in page
    assert " мс" in page and " ms<" not in page
    assert "0-7,5 с" in page or "0-10 с" in page  # comma decimal, Ukrainian unit
    assert " s<" not in page


def test_ecg_page_stays_english_in_en(ecg_client):
    page = _page(ecg_client, "en")
    assert "<strong>Sinus Rhythm</strong>" in page
    assert "25mm/s, 10mm/mV" in page
    assert "78 bpm" in page


@pytest.mark.parametrize("code", ["en", "uk"])
def test_ecg_page_explains_rr_sdnn_rmssd_with_source(ecg_client, code):
    page = _page(ecg_client, code)
    with locale(code):
        for key in ("rr_full", "rr_help", "sdnn_full", "sdnn_help", "rmssd_full", "rmssd_help"):
            assert t(f"ecg.{key}") in page.replace("&#39;", "'")
    assert "10.1161/01.CIR.93.5.1043" in page
    assert "Circulation 1996;93:1043-1065" in page


def test_explanations_differ_between_locales():
    for key in ("rr_full", "rr_help", "sdnn_full", "sdnn_help", "rmssd_full", "rmssd_help", "hrv_source", "scale_text"):
        with locale("en"):
            en = t(f"ecg.{key}")
        with locale("uk"):
            uk = t(f"ecg.{key}")
        assert en != f"ecg.{key}" and uk != en, key


def test_scale_and_row_label_follow_the_locale():
    recording = ecg.Recording(
        recorded_at="x", device="d", vendor="Kardia", classification="Normal Sinus Rhythm",
        sample_rate=500.0, leads={"I": [0.0] * 3750}, mm_per_second=25.0, mm_per_mv=10.0,
    )
    with locale("en"):
        assert recording.scale_text == "25mm/s, 10mm/mV"
        assert ecg.strip_rows(recording)[0]["label"] == "0-7.5 s"
    with locale("uk"):
        assert recording.scale_text == "25 мм/с, 10 мм/мВ"
        assert ecg.strip_rows(recording)[0]["label"] == "0-7,5 с"


def test_units_have_ukrainian_display_forms():
    with locale("uk"):
        assert display_unit("bpm") == "уд/хв"
        assert display_unit("ms") == "мс"


@pytest.mark.parametrize(
    "text",
    [
        "Sinus Rhythm", "Normal Sinus Rhythm", "Atrial Fibrillation", "Possible Atrial Fibrillation",
        "Inconclusive", "Inconclusive Low Heart Rate", "Inconclusive High Heart Rate",
        "Inconclusive Poor Reading", "Heart Rate Over 150", "Heart Rate Under 50", "Unrecognized",
        "Unclassified", "Bradycardia", "Tachycardia",
    ],
)
def test_every_ecg_classification_has_a_ukrainian_phrase(text):
    with locale("uk"):
        assert translate_phrase(text) != text


def test_every_device_notification_has_a_ukrainian_phrase():
    with locale("uk"):
        for label in (*DEVICE_EVENTS.values(), "MET-like effort"):
            assert translate_phrase(label) != label, label


def _row(identifier, kind, start="2026-09-08T10:00:00Z", vendor="Apple Health"):
    return {
        "id": identifier, "owner_user_id": "o", "source_vendor": vendor, "source_name": vendor,
        "workout_type": kind, "started_at": start, "ended_at": "2026-09-08T11:00:00Z",
        "duration_minutes": 60,
    }


def test_workout_case_variants_are_one_session_with_one_label():
    rows = [_row("a", "Walking"), _row("b", "walking", vendor="Oura")]
    result = reconcile_workouts(rows)
    assert len(result) == 1
    assert result[0]["workout_type"] == "Walking"
    assert result[0]["record_count"] == 2


@pytest.mark.parametrize(
    "raw, label",
    [
        ("walking", "Walking"), ("strength_training", "Strength Training"),
        ("Traditional Strength Training", "Traditional Strength Training"),
        ("HKWorkoutActivityTypeMindAndBody", "Mind and Body"), ("Mind And Body", "Mind and Body"),
        ("cardio_training", "Cardio Training"), ("generic", "Workout"), ("other", "Other"),
        ("High Intensity Interval Training", "High Intensity Interval Training"),
        ("kite_surfing", "Kite Surfing"), ("", "Workout"),
    ],
)
def test_workout_label_is_one_title_case_phrase(raw, label):
    assert workout_label(raw) == label


def test_workout_labels_are_translated_and_stored_value_untouched():
    row = _row("a", "strength_training")
    result = reconcile_workouts([row])[0]
    assert row["workout_type"] == "strength_training"
    with locale("uk"):
        assert translate_phrase(result["workout_type"]) == "Силове тренування"
        for raw in ("running", "Cycling", "Swimming", "Hiking", "Yoga", "elliptical", "rowing",
                    "Stair Climbing", "Dance", "Cooldown", "Core Training", "cardio_training",
                    "High Intensity Interval Training", "Functional Strength Training", "Other"):
            label = workout_label(raw)
            assert translate_phrase(label) != label, label
