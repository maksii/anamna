from __future__ import annotations

from anamna.i18n import set_locale, t, translate_phrase
from anamna.health import category_label, concept_display_name, status_label
from anamna.locales.messages import MESSAGES


def test_all_message_keys_have_both_locales():
    for key, entry in MESSAGES.items():
        assert "en" in entry and entry["en"], key
        assert "uk" in entry and entry["uk"], key


def test_server_and_chart_payload_share_all_month_spellings():
    from anamna.i18n import activate_locale, reset_locale, format_date_localized, js_strings

    expected = {
        "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "uk": ["січ.", "лют.", "бер.", "квіт.", "трав.", "черв.", "лип.", "серп.", "вер.", "жовт.", "лист.", "груд."],
    }
    for locale, months in expected.items():
        token = activate_locale(locale)
        try:
            assert js_strings()["_formats"]["months_short"] == months
            for month, spelling in enumerate(months, 1):
                assert format_date_localized(f"2026-{month:02d}-08") == f"08 {spelling} 2026"
        finally:
            reset_locale(token)


def test_ui_chrome_switches_locale():
    set_locale("en")
    assert t("nav.overview") == "Home"
    assert t("brand.name") == "Anamna"
    set_locale("uk")
    assert t("nav.overview") == "Головна"
    assert t("brand.name") == "Anamna"
    set_locale("en")


def test_domain_labels_switch_locale():
    set_locale("en")
    assert category_label("lipids") == "Cholesterol & lipids"
    assert status_label("high") == "Above original range"
    assert concept_display_name("Creatinine") == "Creatinine"
    set_locale("uk")
    assert category_label("lipids") == "Холестерин і ліпіди"
    assert status_label("high") == "Вище норми лабораторії"
    assert concept_display_name("Creatinine") == "Креатинін"
    assert translate_phrase("Blood health") == "Кров і кровотворення"
    set_locale("en")


def test_every_curated_interpretation_has_a_verdict_label_in_both_locales(tmp_path):
    """PANEL-05: a curated band whose interpretation has no verdict.* entry
    renders the raw key as the patient's verdict label — 'verdict.borderline'
    stood in for the current uric-acid result in both locales.

    The interpretations are enumerated from a freshly seeded scratch library,
    never from the live database, plus the three values evaluate() emits that
    no curated rule carries.
    """
    from anamna.config import Settings
    from anamna.db import connect, migrate
    from anamna.ingest.pipeline import seed_concepts

    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "i18n-test-secret")
    migrate(settings)
    with connect(settings) as connection:
        seed_concepts(connection)
        interpretations = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT interpretation FROM curated_reference_rules"
            )
            if row[0]
        }

    assert interpretations, "the seeded library carries no curated interpretations"
    interpretations |= {"unjudged", "indeterminate", "not_a_measurement"}
    for interpretation in sorted(interpretations):
        entry = MESSAGES.get(f"verdict.{interpretation}")
        assert entry is not None, f"verdict.{interpretation} is missing from MESSAGES"
        assert entry.get("en"), f"verdict.{interpretation} has no English label"
        assert entry.get("uk"), f"verdict.{interpretation} has no Ukrainian label"


def test_reference_intervals_use_the_locale_decimal_separator():
    """An interval sits beside the reader's own value, so both must agree.

    The value already formatted through ``format_number_localized`` while
    ``range_text`` used a raw float repr, so one Ukrainian line read
    "6,57 ... 3.5-8.8" -- two conventions for the same kind of number.
    """
    from anamna.reference import range_text

    set_locale("en")
    assert range_text(3.5, 8.8, None) == "3.5-8.8"
    assert range_text(1234.5, 5678.9, None) == "1,234.5-5,678.9"

    set_locale("uk")
    assert range_text(3.5, 8.8, None) == "3,5-8,8"
    # Ukrainian groups thousands with U+00A0, not a comma.
    assert range_text(1234.5, 5678.9, None) == "1 234,5-5 678,9"
    # Precision must survive: the magnitude-based default would give "0".
    assert range_text(0.001, None, None) == "≥ 0,001"

    set_locale("en")
