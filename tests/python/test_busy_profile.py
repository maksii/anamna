"""Profile and admin pages show that a server wait is under way, in both locales."""

from __future__ import annotations

from pathlib import Path

import pytest

from anamna.locales.messages import MESSAGES
from test_labsync import make

KEYS = ("labsync.sending_code", "labsync.verifying_code", "labsync.signing_in", "labsync.status_unreachable")


def test_new_keys_exist_in_both_locales():
    for key in KEYS:
        assert MESSAGES[key].get("en") and MESSAGES[key].get("uk"), key


@pytest.mark.parametrize("lang,sending", [("en", "Sending the code..."), ("uk", "Надсилаємо код...")])
def test_the_sms_sign_in_button_says_what_it_is_doing(tmp_path: Path, lang: str, sending: str):
    _, _, client = make(tmp_path)
    client.cookies.set("anamna_lang", lang)
    page = client.get("/profile").text
    assert f'data-working="{sending}"' in page
