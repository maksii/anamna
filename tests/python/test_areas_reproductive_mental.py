"""Gynaecological and psychiatric diagnoses file under their own areas."""
from anamna.health import HEALTH_AREAS, _diagnosis_areas, _study_for
from anamna.i18n import translate_phrase, activate_locale, reset_locale


def test_gynaecological_diagnoses_file_under_reproductive_health():
    assert _diagnosis_areas("Аденоміоз. Вузлова міома матки") == ("reproductive",)
    assert _diagnosis_areas("Ендометріоїдна кіста лівого яєчника N80.1") == ("reproductive",)
    assert _diagnosis_areas("D27 Доброякісне новоутворення") == ("reproductive",)
    assert "kidneys" in _diagnosis_areas("N20.0 камінь нирки")


def test_psychiatric_diagnosis_files_under_mental_health():
    assert _diagnosis_areas("Попередній діагноз: F90.2 розлад змішаного типу") == ("mental",)
    assert _study_for("Консультація лікаря-психіатра", "consultation")[2] == ("mental",)


def test_mental_health_area_is_named_in_both_languages():
    area = next(item for item in HEALTH_AREAS if item["id"] == "mental")
    token = activate_locale("uk")
    try:
        assert translate_phrase(area["name"]) == "Психічне здоров’я"
        assert translate_phrase(area["description"]) != area["description"]
    finally:
        reset_locale(token)
