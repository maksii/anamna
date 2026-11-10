"""Strings added or corrected in the audit pass exist in both locales.

Covers the vaccination, correlation, special-test, plan, AI admin, upload,
dashboard, auth, profile, OpenWearables and labsync catalog entries.
"""

import re

import pytest

from anamna.locales.messages import MESSAGES

AUDITED_KEYS = [
    # Replaced text.
    "vax.note_covid_booster",
    "corr.explain_what",
    "special.gen-hemochromatosis_what",
    "plan.prep_rule_antibiotics",
    "plan.prep_rule_antibiotics_plain",
    "plan.prep_rule_biotin",
    # Added keys.
    "vax.gap_discuss_dated",
    "vax.gap_discuss",
    "vax.agreement_agreed_ua_us",
    "vax.agreement_agreed_ua_us_help",
    "special.once_note_lifetime",
    "special.done_once_lifetime",
    "corr.suggested_note",
    "chat.error_in_progress",
    "auth.error_cross_site",
    "profile.error_password_throttled",
    "profile.error_share_unknown",
    "openwearables.error_taken",
    "openwearables.error_not_yours",
    "openwearables.none_for_you",
    "aiadmin.data_collection_label",
    "aiadmin.data_collection_help",
    "labsync.copy_failed",
    "upload.status_stalled",
    "dashboard.welcome_heading",
    "dashboard.welcome_lead",
    "dashboard.welcome_upload",
    "dashboard.welcome_upload_hint",
    "dashboard.welcome_connect",
    "dashboard.welcome_connect_hint",
    "dashboard.welcome_connect_admin",
    "dashboard.welcome_profile",
    "dashboard.welcome_profile_hint",
]

PLACEHOLDER = re.compile(r"\{(\w+)\}")


@pytest.mark.parametrize("key", AUDITED_KEYS)
def test_key_exists_with_both_locales(key):
    entry = MESSAGES[key]
    for lang in ("en", "uk"):
        assert isinstance(entry[lang], str), (key, lang)
        assert entry[lang].strip(), (key, lang)


@pytest.mark.parametrize("key", AUDITED_KEYS)
def test_placeholders_match_across_locales(key):
    en = set(PLACEHOLDER.findall(MESSAGES[key]["en"]))
    uk = set(PLACEHOLDER.findall(MESSAGES[key]["uk"]))
    assert en == uk, (key, en, uk)


def test_covid_booster_uk_cites_order_595():
    assert "595" in MESSAGES["vax.note_covid_booster"]["uk"]


def test_antibiotics_rule_en_tells_patient_to_ask_doctor():
    assert "ask your doctor" in MESSAGES["plan.prep_rule_antibiotics"]["en"]
