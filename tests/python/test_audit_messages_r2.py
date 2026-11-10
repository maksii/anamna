"""Catalogue entries added or corrected in the second messages audit pass.

Every new key exists in both locales with the same placeholders, and the
replaced wording is gone from the catalogue.
"""

import re

import pytest

from anamna.locales.messages import MESSAGES
from anamna.locales.phrases import PHRASES

NEW_KEYS = [
    "profile.share_level",
    "profile.share_level_read",
    "profile.share_level_full",
    "profile.share_level_change",
    "profile.share_level_saved",
    "viewing.banner_full",
    "chat.share_read_only",
    "chat.error_share_read_only",
    "chat.answer_ready",
    "plan.share_read_only",
    "plan.error_share_read_only",
    "plan.error_order_session",
    "plan.error_order_repeat",
    "plan.error_order_uncertain",
    "verdict.blocked_not_fasting",
    "verdict.blocked_pregnancy",
    "glucose.assumed_fasting",
    "glucose.confirmed_fasting",
    "glucose.marked_not_fasting",
    "glucose.question",
    "glucose.answer_fasting",
    "glucose.answer_not_fasting",
    "glucose.answer_unknown",
    "glucose.save",
    "glucose.saved",
    "profile.pregnancy_due_date",
    "profile.pregnancy_due_date_hint",
    "profile.delete_heading",
    "profile.delete_lead",
    "profile.delete_password",
    "profile.delete_confirm_email",
    "profile.delete_button",
    "profile.error_delete_password",
    "profile.error_delete_email",
    "profile.error_delete_last_admin",
    "auth.account_deleted",
    "profile.export_heading",
    "profile.export_lead",
    "profile.export_button",
    "profile.email_heading",
    "profile.email_new",
    "profile.email_button",
    "profile.email_saved",
    "profile.error_email_taken",
    "profile.error_email_invalid",
    "profile.error_email_password",
    "error.title",
    "error.400",
    "error.403",
    "error.404",
    "error.413",
    "error.429",
    "error.other",
    "error.home",
    "lang.en_full",
    "lang.uk_full",
    "table.scroll_region",
    "upload.announce_done",
    "labsync.phone_placeholder",
    "labsync.error_order_forbidden",
    "review.no_date",
    "review.person_mismatch",
    "review.lab_rows_changed",
    "bp.single_reading_note",
    "stale.condition_borderline_only",
]

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _message_texts():
    for entry in MESSAGES.values():
        yield from entry.values()


@pytest.mark.parametrize("key", NEW_KEYS)
def test_new_entry_exists_in_both_locales_with_matching_placeholders(key):
    entry = MESSAGES[key]
    assert entry["en"].strip(), f"{key} has an empty en"
    assert entry["uk"].strip(), f"{key} has an empty uk"
    assert sorted(set(PLACEHOLDER.findall(entry["en"]))) == sorted(set(PLACEHOLDER.findall(entry["uk"])))


def test_assistant_prompts_carry_the_differential_and_the_doctor_bullet():
    assert not any("You are my doctor" in text for text in _message_texts())
    for key in ("ai.task_body", "ai.task_body_scoped"):
        assert "most likely first" in MESSAGES[key]["en"], key
        assert "найімовірнішого" in MESSAGES[key]["uk"], key


def test_assistant_prompts_ask_for_worked_figures_and_drop_the_no_doses_rule():
    for key in ("ai.task_body", "ai.task_body_scoped"):
        english, ukrainian = MESSAGES[key]["en"], MESSAGES[key]["uk"]
        assert "without personal doses" not in english, key
        assert "без персональних доз" not in ukrainian, key
        assert "Work the figures out for me" in english, key
        assert "Розрахуйте цифри саме для мене" in ukrainian, key


def test_guideline_label_names_the_2025_guideline():
    assert not any("ACC/AHA 2017" in text for text in _message_texts())


def test_alcohol_hint_no_longer_uses_the_friday_night_example():
    assert not any("Friday night" in text for text in _message_texts())


def test_cookie_notice_names_the_test_planner_cookie():
    assert "test planner" in MESSAGES["privacy.s4_body"]["en"]


def test_cruciate_ligament_abbreviation_is_explained_in_ukrainian_phrases():
    assert not any("зміни ПХЗ" in uk for uk in PHRASES.values())
