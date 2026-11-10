"""Per-share access level: "read" (the record only) or "full" (today's behaviour).

The level is stored on the share, set by the owner in the sharing panel, and
carried by the viewing row so the chrome can say which one the viewer has.
Enforcement in the chat and test-ordering routes is tested elsewhere.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import markupsafe
import pytest
from fastapi.testclient import TestClient

from anamna.db import connect, migrate
from anamna.locales.messages import MESSAGES
from anamna.security import create_user
from anamna.web.app import create_app

from test_web_profile import csrf_for, login
from test_web_security import PASSWORD, settings_for

OWNER_EMAIL = "alpha@example.test"
GRANTEES = ("beta@example.test", "gamma@example.test", "delta@example.test")
#: The owner's sharing panel lists each share's select first, then the add form's.
OPTION = re.compile(r'<option value="(read|full)"\s*(selected)?\s*>')


def two_users(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, OWNER_EMAIL, "Alpha", PASSWORD)
    for email in GRANTEES:
        create_user(settings, email, email.split("@")[0].capitalize(), PASSWORD)
    return settings, alpha


def user_id(settings, email: str) -> str:
    with connect(settings) as connection:
        return connection.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]


def stored(settings, owner_id: str) -> dict[str, str]:
    with connect(settings) as connection:
        rows = connection.execute(
            "SELECT grantee_email, access FROM record_shares WHERE owner_user_id=?", (owner_id,)
        ).fetchall()
    return {email: access for email, access in rows}


def share_id(settings, owner_id: str, email: str) -> str:
    with connect(settings) as connection:
        return connection.execute(
            "SELECT id FROM record_shares WHERE owner_user_id=? AND grantee_email=?", (owner_id, email)
        ).fetchone()[0]


def add(client: TestClient, csrf: str, email: str, **fields):
    data = {"email": email, "csrf_token": csrf, **fields}
    return client.post("/profile/shares", data=data, follow_redirects=False)


def test_migration_gives_existing_shares_full_and_refuses_other_levels(tmp_path: Path):
    settings, alpha = two_users(tmp_path)
    beta = user_id(settings, GRANTEES[0])
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO record_shares(id, owner_user_id, grantee_email, grantee_user_id, created_at)
                   VALUES ('legacy-share', ?, ?, ?, '2026-01-01T00:00:00+00:00')""",
            (alpha, GRANTEES[0], beta),
        )
        access = connection.execute("SELECT access FROM record_shares WHERE id='legacy-share'").fetchone()[0]
    assert access == "full"

    with pytest.raises(sqlite3.IntegrityError):
        with connect(settings) as connection:
            connection.execute(
                """INSERT INTO record_shares(id, owner_user_id, grantee_email, grantee_user_id, created_at, access)
                       VALUES ('bad-share', ?, ?, ?, '2026-01-01T00:00:00+00:00', 'other')""",
                (alpha, GRANTEES[1], beta),
            )


def test_a_new_share_is_read_only_unless_the_owner_asks_for_full(tmp_path: Path):
    settings, alpha = two_users(tmp_path)
    with TestClient(create_app(settings)) as owner:
        login(owner, OWNER_EMAIL)
        csrf = csrf_for(settings, owner)
        add(owner, csrf, GRANTEES[0])
        add(owner, csrf, GRANTEES[1], access="full")
        add(owner, csrf, GRANTEES[2], access="nonsense")
    assert stored(settings, alpha) == {
        GRANTEES[0]: "read",
        GRANTEES[1]: "full",
        GRANTEES[2]: "read",
    }


def test_re_sharing_with_another_level_changes_the_row_instead_of_adding_one(tmp_path: Path):
    settings, alpha = two_users(tmp_path)
    with TestClient(create_app(settings)) as owner:
        login(owner, OWNER_EMAIL)
        csrf = csrf_for(settings, owner)
        add(owner, csrf, GRANTEES[0])
        before = share_id(settings, alpha, GRANTEES[0])
        add(owner, csrf, GRANTEES[0].upper(), access="full")
        assert stored(settings, alpha) == {GRANTEES[0]: "full"}
        assert share_id(settings, alpha, GRANTEES[0]) == before
        add(owner, csrf, GRANTEES[0], access="read")
        assert stored(settings, alpha) == {GRANTEES[0]: "read"}
        with connect(settings) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM record_shares WHERE owner_user_id=?", (alpha,)
            ).fetchone()[0]
    assert count == 1


def test_the_owner_changes_a_share_level_and_nobody_else_can(tmp_path: Path):
    settings, alpha = two_users(tmp_path)
    with TestClient(create_app(settings)) as owner:
        login(owner, OWNER_EMAIL)
        csrf = csrf_for(settings, owner)
        add(owner, csrf, GRANTEES[0])
        beta_share = share_id(settings, alpha, GRANTEES[0])

        changed = owner.post(
            "/profile/shares/level",
            data={"share_id": beta_share, "access": "full", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert changed.status_code == 303
        assert changed.headers["location"] == "/profile?saved=share_level"
        assert stored(settings, alpha) == {GRANTEES[0]: "full"}
        confirmation = owner.get("/profile?saved=share_level").text
        assert MESSAGES["profile.share_level_saved"]["en"] in confirmation

        assert owner.post(
            "/profile/shares/level",
            data={"share_id": beta_share, "access": "other", "csrf_token": csrf},
            follow_redirects=False,
        ).status_code == 400
        assert owner.post(
            "/profile/shares/level",
            data={"share_id": beta_share, "access": "read"},
            follow_redirects=False,
        ).status_code == 403
        assert stored(settings, alpha) == {GRANTEES[0]: "full"}

    with TestClient(create_app(settings)) as stranger:
        login(stranger, GRANTEES[1])
        stranger_csrf = csrf_for(settings, stranger)
        stranger.post(
            "/profile/shares/level",
            data={"share_id": beta_share, "access": "read", "csrf_token": stranger_csrf},
            follow_redirects=False,
        )
    assert stored(settings, alpha) == {GRANTEES[0]: "full"}


def test_the_owner_sees_each_share_with_its_level_selected(tmp_path: Path):
    settings, alpha = two_users(tmp_path)
    with TestClient(create_app(settings)) as owner:
        login(owner, OWNER_EMAIL)
        csrf = csrf_for(settings, owner)
        add(owner, csrf, GRANTEES[0], access="full")
        page = owner.get("/profile").text
    assert '<select name="access"' in page
    # The share's own select comes first, then the add form's select (read by default).
    options = OPTION.findall(page)
    assert options[:2] == [("read", ""), ("full", "selected")]
    assert options[2:4] == [("read", "selected"), ("full", "")]


def test_the_viewer_sees_the_banner_for_the_level_the_owner_granted(tmp_path: Path):
    settings, alpha = two_users(tmp_path)
    read_banner = markupsafe.escape(MESSAGES["viewing.banner"]["en"].format(name="Alpha"))
    full_banner = markupsafe.escape(MESSAGES["viewing.banner_full"]["en"].format(name="Alpha"))

    with TestClient(create_app(settings)) as owner:
        login(owner, OWNER_EMAIL)
        csrf = csrf_for(settings, owner)
        add(owner, csrf, GRANTEES[0])

    with TestClient(create_app(settings)) as viewer:
        login(viewer, GRANTEES[0])
        viewer_csrf = csrf_for(settings, viewer)
        viewer.post("/profile/view", data={"owner_user_id": alpha, "csrf_token": viewer_csrf})
        page = viewer.get("/").text
        assert str(read_banner) in page
        assert str(full_banner) not in page

    with TestClient(create_app(settings)) as owner:
        login(owner, OWNER_EMAIL)
        csrf = csrf_for(settings, owner)
        add(owner, csrf, GRANTEES[0], access="full")

    with TestClient(create_app(settings)) as viewer:
        login(viewer, GRANTEES[0])
        viewer_csrf = csrf_for(settings, viewer)
        viewer.post("/profile/view", data={"owner_user_id": alpha, "csrf_token": viewer_csrf})
        page = viewer.get("/").text
        assert str(full_banner) in page
        assert str(read_banner) not in page
        profile = viewer.get("/profile").text
        assert f"Alpha ({MESSAGES['profile.share_level_full']['en']})" in profile
