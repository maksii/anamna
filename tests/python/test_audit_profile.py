"""Profile, sharing and token rules that the audit found open to the wrong person.

Each test asserts one rule: a share follows the account it was given to, not an
address; an ordinary user links only their own OpenWearables account; a guest
link cannot lose its expiry; the change-password form is metered; the AI data
policy is stored from the page; and the migration that moved shares onto
accounts keeps only what it can attribute.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import ai, openwearables, security
from anamna.db import connect, migrate
from anamna.security import PASSWORD_CHANGE_LIMIT, create_user
from anamna.web.app import _openwearables_panel, create_app

from test_ai_assist import admin_form
from test_web_panels import build
from test_web_profile import csrf_for, login
from test_web_security import PASSWORD, settings_for


MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "055_record_share_grantee.sql"

REMOTE_OWN = {
    "id": "r1",
    "created_at": "2024-01-01T00:00:00Z",
    "first_name": "Alpha",
    "last_name": "Owner",
    "email": "alpha@example.test",
    "external_user_id": "ext-1",
    "last_synced_at": None,
    "last_synced_provider": None,
    "has_active_connection": False,
}
REMOTE_OTHER = {
    **REMOTE_OWN,
    "id": "r2",
    "first_name": "Someone",
    "last_name": "Else",
    "email": "other@example.test",
    "external_user_id": "ext-2",
}


@pytest.fixture
def wrong_password_counter():
    """The change-password counter is process-wide; each test starts and ends clean."""
    security._attempts.clear()
    yield
    security._attempts.clear()


def share(client: TestClient, csrf: str, email: str):
    return client.post(
        "/profile/shares", data={"email": email, "csrf_token": csrf}, follow_redirects=False
    )


def test_a_share_is_refused_for_an_address_with_no_account_and_names_the_account_it_gives_to(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    with TestClient(create_app(settings)) as owner:
        login(owner, "alpha@example.test")
        csrf = csrf_for(settings, owner)
        refused = share(owner, csrf, "carol@example.test")
        assert refused.headers["location"] == "/profile?error=profile.error_share_unknown"
        granted = share(owner, csrf, "Beta@Example.test")
        assert granted.status_code == 303
    with connect(settings) as db:
        rows = db.execute(
            "SELECT grantee_email, grantee_user_id FROM record_shares WHERE owner_user_id=?", (alpha,)
        ).fetchall()
    assert [tuple(row) for row in rows] == [("beta@example.test", beta)]

    with TestClient(create_app(settings)) as viewer:
        login(viewer, "beta@example.test")
        view = viewer.post(
            "/profile/view",
            data={"owner_user_id": alpha, "csrf_token": csrf_for(settings, viewer)},
            follow_redirects=False,
        )
        assert view.status_code == 303


def test_an_address_refused_at_share_time_gains_nothing_when_someone_registers_it(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    create_user(settings, "beta@example.test", "Beta", PASSWORD)
    with TestClient(create_app(settings)) as owner:
        login(owner, "alpha@example.test")
        share(owner, csrf_for(settings, owner), "carol@example.test")
    # The address registers afterwards: the share the owner was refused must not reach it.
    create_user(settings, "carol@example.test", "Carol", PASSWORD)
    with TestClient(create_app(settings)) as carol:
        login(carol, "carol@example.test")
        view = carol.post(
            "/profile/view",
            data={"owner_user_id": alpha, "csrf_token": csrf_for(settings, carol)},
            follow_redirects=False,
        )
        assert view.status_code == 404


def test_deleting_the_grantee_account_takes_its_shares_with_it(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    with TestClient(create_app(settings)) as owner:
        login(owner, "alpha@example.test")
        share(owner, csrf_for(settings, owner), "beta@example.test")
    with connect(settings) as db:
        db.execute("DELETE FROM users WHERE id=?", (beta,))
    with connect(settings) as db:
        remaining = db.execute(
            "SELECT COUNT(*) FROM record_shares WHERE owner_user_id=?", (alpha,)
        ).fetchone()[0]
        assert remaining == 0
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_backfills_matching_grantees_and_drops_the_rest(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    with connect(settings) as db:
        db.execute(
            """INSERT INTO record_shares(id, owner_user_id, grantee_email, grantee_user_id, created_at)
               VALUES ('matched', ?, 'Beta@Example.test', NULL, '2026-01-01T00:00:00+00:00')""",
            (alpha,),
        )
        db.execute(
            """INSERT INTO record_shares(id, owner_user_id, grantee_email, grantee_user_id, created_at)
               VALUES ('unmatched', ?, 'nobody@example.test', NULL, '2026-01-01T00:00:00+00:00')""",
            (alpha,),
        )
    # The migration ran before these rows existed, so its backfill is replayed
    # from the file itself rather than trusted to have run over them.
    script = re.sub(r"--[^\n]*", "", MIGRATION.read_text(encoding="utf-8"))
    statements = [part.strip() for part in script.split(";") if part.strip()]
    backfill = [s for s in statements if s.startswith(("UPDATE", "DELETE"))]
    assert len(backfill) == 2
    with connect(settings) as db:
        for statement in backfill:
            db.execute(statement)
        rows = db.execute("SELECT id, grantee_user_id FROM record_shares ORDER BY id").fetchall()
    assert [tuple(row) for row in rows] == [("matched", beta)]


def test_an_ordinary_user_links_only_the_remote_account_under_their_own_address(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    people = [dict(REMOTE_OWN), dict(REMOTE_OTHER)]
    linked_calls: list[tuple] = []
    backfills: list[str] = []

    def record_link(settings, user_id, remote_user_id, remote_email):
        linked_calls.append((user_id, remote_user_id, remote_email))
        return False

    monkeypatch.setattr(openwearables, "configured", lambda settings: True)
    monkeypatch.setattr(openwearables, "remote_users", lambda settings: people)
    monkeypatch.setattr(openwearables, "link_account", record_link)
    monkeypatch.setattr(openwearables, "start_backfill", lambda settings, user_id: backfills.append(user_id))

    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        csrf = csrf_for(settings, client)
        not_mine = client.post(
            "/profile/openwearables/link",
            data={"csrf_token": csrf, "remote_user_id": "r2"},
            follow_redirects=False,
        )
        assert not_mine.headers["location"] == "/profile?error=openwearables.error_not_yours"
        assert linked_calls == []

        mine = client.post(
            "/profile/openwearables/link",
            data={"csrf_token": csrf, "remote_user_id": "r1"},
            follow_redirects=False,
        )
        assert mine.headers["location"] == "/profile?saved=openwearables_linked"
        assert linked_calls == [(alpha, "r1", "alpha@example.test")]
        assert backfills == [alpha]

        monkeypatch.setattr(openwearables, "linked_elsewhere", lambda settings, user_id, remote_id: True)
        taken = client.post(
            "/profile/openwearables/link",
            data={"csrf_token": csrf, "remote_user_id": "r1"},
            follow_redirects=False,
        )
        assert taken.headers["location"] == "/profile?error=openwearables.error_taken"
        assert len(linked_calls) == 1


def test_the_card_lists_only_the_viewers_own_remote_account(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    root = create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    carol = create_user(settings, "carol@example.test", "Carol", PASSWORD)
    monkeypatch.setattr(openwearables, "configured", lambda settings: True)
    monkeypatch.setattr(
        openwearables, "remote_users", lambda settings: [dict(REMOTE_OWN), dict(REMOTE_OTHER)]
    )

    def as_user(user_id: str, email: str, role: str) -> dict:
        return {"id": user_id, "email": email, "role": role}

    mine = _openwearables_panel(settings, as_user(alpha, "alpha@example.test", "user"))
    assert [person["id"] for person in mine["people"]] == ["r1"]
    assert mine["people"][0]["selected"] is True
    assert mine["none_for_you"] is False

    nobody = _openwearables_panel(settings, as_user(carol, "carol@example.test", "user"))
    assert nobody["people"] == []
    assert nobody["none_for_you"] is True

    everyone = _openwearables_panel(settings, as_user(root, "root@example.test", "admin"))
    assert [person["id"] for person in everyone["people"]] == ["r1", "r2"]
    assert everyone["none_for_you"] is False


def test_a_guest_link_cannot_have_its_expiry_removed(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        csrf = csrf_for(settings, client)
        created = client.post(
            "/tokens",
            data={"kind": "guest", "label": "Doctor", "expires_on": "2099-12-31",
                  "origin": "profile", "csrf_token": csrf},
        )
        assert created.status_code == 200
        with connect(settings) as db:
            token_id, expires_before = db.execute(
                "SELECT id, expires_at FROM access_tokens WHERE owner_user_id=? AND kind='guest'",
                (alpha,),
            ).fetchone()
        assert expires_before

        blank = client.post(
            f"/tokens/{token_id}",
            data={"action": "update", "label": "Doctor", "expires_on": "", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert blank.headers["location"] == "/profile?error=token.error_expiry"
    with connect(settings) as db:
        assert db.execute(
            "SELECT expires_at FROM access_tokens WHERE id=?", (token_id,)
        ).fetchone()[0] == expires_before


@pytest.mark.usefixtures("wrong_password_counter")
def test_the_change_password_form_stops_checking_guesses_at_the_limit(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        csrf = csrf_for(settings, client)
        form = {"csrf_token": csrf, "new_password": "another-long-password",
                "confirm_password": "another-long-password"}
        for _ in range(PASSWORD_CHANGE_LIMIT):
            wrong = client.post(
                "/profile/password",
                data={**form, "current_password": "a-wrong-guess-here"},
                follow_redirects=False,
            )
            assert wrong.headers["location"] == "/profile?error=profile.error_password_current"
        blocked = client.post(
            "/profile/password",
            data={**form, "current_password": PASSWORD},
            follow_redirects=False,
        )
        assert blocked.headers["location"] == "/profile?error=profile.error_password_throttled&wait=15"


def test_the_admin_ai_page_stores_the_data_policy_and_an_unchecked_box_means_deny(tmp_path: Path, monkeypatch):
    for name in ("OPENROUTER_API_KEY", "openrouter", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    settings, _admin_id, client = build(tmp_path)
    csrf = csrf_for(settings, client)

    allowed = client.post("/admin/ai", data=admin_form(csrf, data_collection="allow"), follow_redirects=False)
    assert allowed.status_code == 303
    assert ai.ai_settings(settings)["data_collection"] == "allow"

    unchecked = client.post("/admin/ai", data=admin_form(csrf), follow_redirects=False)
    assert unchecked.status_code == 303
    assert ai.ai_settings(settings)["data_collection"] == "deny"
