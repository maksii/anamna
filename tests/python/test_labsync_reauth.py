"""Sign in again in place: a lab connection whose stored sign-in ran out or was
refused keeps its linked people and order history, shows the sign-in form on
its own card, and resumes the sync once a new sign-in works.

Every fixture is synthetic; HTTP goes through the same stand-in as
``test_labsync.py``.
"""

from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path

import pytest

from anamna import labsync
from anamna.db import connect, utc_now
from anamna.labsync import common

from test_labsync import (
    CODE,
    PHONE,
    connect_esculab,
    csrf,
    esculab_routes,
    make,
    router,
    sign_in_esculab,
)


def expire(settings, user_id: str, when: str = "2020-01-01T00:00:00") -> None:
    with connect(settings) as connection:
        connection.execute(
            "UPDATE lab_accounts SET secret_expires_at=? WHERE user_id=? AND provider='esculab'", (when, user_id))


def links_of(settings, user_id: str) -> list[tuple]:
    with connect(settings) as connection:
        return [tuple(row) for row in connection.execute(
            "SELECT * FROM lab_person_links WHERE account_user_id=? ORDER BY remote_person_id", (user_id,))]


def jwt_expiring(exp: int) -> str:
    """A token shaped like the lab's own, whose payload says when it ends."""
    def part(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'HS256'})}.{part({'sub': '1', 'exp': exp})}.c2lnbmF0dXJl"


def test_reauth_reason_names_what_must_be_renewed(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    connect_esculab(settings, user_id, monkeypatch, esculab_routes([], {}))
    assert labsync.reauth_reason(labsync.account(settings, user_id, "esculab")) == ""

    expire(settings, user_id)
    assert labsync.reauth_reason(labsync.account(settings, user_id, "esculab")) == "expired"

    with connect(settings) as connection:
        connection.execute("UPDATE lab_accounts SET secret_expires_at=NULL, auth_rejected_at=? WHERE user_id=?",
                           (utc_now(), user_id))
    assert labsync.reauth_reason(labsync.account(settings, user_id, "esculab")) == "rejected"

    # The lab's own token carries its end: a past one is expired even with no stored date.
    with connect(settings) as connection:
        connection.execute("UPDATE lab_accounts SET secret=?, auth_rejected_at=NULL WHERE user_id=?",
                           (jwt_expiring(1_000_000_000), user_id))
    assert labsync.reauth_reason(labsync.account(settings, user_id, "esculab")) == "expired"

    with connect(settings) as connection:
        connection.execute("UPDATE lab_accounts SET secret='' WHERE user_id=?", (user_id,))
    assert labsync.reauth_reason(labsync.account(settings, user_id, "esculab")) == ""
    assert labsync.reauth_reason(None) == ""


def test_reauth_needed_lists_only_the_labs_that_must_renew(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    connect_esculab(settings, user_id, monkeypatch, esculab_routes([], {}))
    user = {"id": user_id, "token_kind": None}
    assert labsync.reauth_needed(settings, user) == []  # a working sign-in needs nothing

    expire(settings, user_id)
    assert labsync.reauth_needed(settings, user) == [
        {"key": "esculab", "name": labsync.provider("esculab").NAME, "reason": "expired"}]
    assert labsync.reauth_needed(settings, {"id": user_id, "token_kind": "api"}) == []
    assert labsync.reauth_needed(settings, {"id": user_id, "token_kind": "guest"}) == []


def test_a_refused_check_is_remembered_until_a_new_sign_in_works(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    connect_esculab(settings, user_id, monkeypatch, esculab_routes([], {}))
    monkeypatch.setattr(common, "_http", router({("POST", "/api/customers/findPatientSite"): 401}))
    with pytest.raises(common.LabSyncError) as caught:
        labsync.check_account(settings, user_id, "esculab")
    assert caught.value.key == "labsync.error_auth"
    row = labsync.account(settings, user_id, "esculab")
    assert row["auth_rejected_at"] and labsync.reauth_reason(row) == "rejected"

    monkeypatch.setattr(common, "_http", router(esculab_routes([], {})))
    sign_in_esculab(settings, user_id)
    row = labsync.account(settings, user_id, "esculab")
    assert row["auth_rejected_at"] is None and labsync.reauth_reason(row) == ""

    monkeypatch.setattr(common, "_http", router({("POST", "/api/customers/findPatientSite"): 401}))
    with pytest.raises(common.LabSyncError):
        labsync.check_account(settings, user_id, "esculab")
    monkeypatch.setattr(common, "_http", router(esculab_routes([], {})))
    labsync.check_account(settings, user_id, "esculab")  # the lab answers: the refusal is over
    assert labsync.account(settings, user_id, "esculab")["auth_rejected_at"] is None


def test_an_expired_sign_in_shows_the_sign_in_form_on_its_own_card(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path)
    connect_esculab(settings, user_id, monkeypatch, esculab_routes([], {}))
    expire(settings, user_id)
    page = client.get("/profile?tab=connections").text
    card = page[page.index('id="lab-esculab"'):page.index('id="lab-synevo"')]
    reauth = card[card.index('id="lab-reauth-esculab"'):]
    assert 'action="/profile/lab/esculab/credentials"' in reauth and 'name="phone"' in reauth
    assert 'action="/profile/lab/esculab/forget"' in card  # Forget stays, as before
    assert 'action="/profile/lab/esculab/sync"' in card
    assert 'href="#conn-lab-esculab"' in page  # the summary above the sections names it
    assert re.search(r'data-working="[^"]*"\s+disabled', card)  # no sync while the sign-in is out


def test_signing_in_again_keeps_the_links_and_resumes_the_sync(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path)
    connect_esculab(settings, user_id, monkeypatch, esculab_routes([], {}))
    links = links_of(settings, user_id)
    assert links  # the chosen person is linked
    expire(settings, user_id)
    monkeypatch.setattr(common, "_http", router(esculab_routes([], {})))
    started: list[str] = []
    monkeypatch.setattr(labsync, "start_sync", lambda settings_, uid, key: started.append(key))
    token = csrf(settings, user_id)

    asked = client.post("/profile/lab/esculab/credentials", data={"phone": PHONE, "csrf_token": token},
                        follow_redirects=False)
    assert "lab_msg=labsync.password_code_sent" in asked.headers["location"]
    signed = client.post("/profile/lab/esculab/credentials", data={"code": CODE, "csrf_token": token},
                         follow_redirects=False)
    assert "lab_msg=labsync.reauth_done" in signed.headers["location"]
    assert started == ["esculab"]  # the sync picks up where it stopped
    assert links_of(settings, user_id) == links  # people and their links are untouched
    row = labsync.account(settings, user_id, "esculab")
    assert labsync.reauth_reason(row) == "" and row["auth_rejected_at"] is None


def test_the_home_page_says_a_sign_in_ran_out(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path)
    connect_esculab(settings, user_id, monkeypatch, esculab_routes([], {}))
    expire(settings, user_id)
    home = client.get("/").text
    assert "/profile?tab=connections&amp;lab=esculab#lab-esculab" in home


def test_cancelling_a_code_while_signing_in_again_keeps_the_stored_sign_in(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path)
    connect_esculab(settings, user_id, monkeypatch, esculab_routes([], {}))
    expire(settings, user_id)  # the sign-in ran out: the reauth block is what shows the code step
    before = labsync.account(settings, user_id, "esculab")
    links = links_of(settings, user_id)
    assert before["secret"] and before["persons_json"] and links
    labsync._PENDING[(user_id, "esculab")] = {
        "challenge": {"phone_masked": "+380" + "•" * 7 + "01", "code_length": 6, "expires_in": 300},
        "state": {}, "phone": PHONE, "until": time.monotonic() + 300}
    try:
        page = client.get("/profile?tab=connections").text
        assert 'name="code"' in page and 'name="pending_only" value="1"' in page

        cancelled = client.post("/profile/lab/esculab/forget",
                                data={"pending_only": "1", "csrf_token": csrf(settings, user_id)},
                                follow_redirects=False)
        assert "lab_msg=labsync.password_code_cancelled" in cancelled.headers["location"]
        assert labsync.pending_code(user_id, "esculab") is None
        after = labsync.account(settings, user_id, "esculab")
        assert after["secret"] == before["secret"] and after["persons_json"] == before["persons_json"]
        assert links_of(settings, user_id) == links
    finally:
        labsync._PENDING.pop((user_id, "esculab"), None)
