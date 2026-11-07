"""An administrator can give a person who forgot their password a new one:
admin-only, CSRF-checked, typed twice, never echoed, audited, and every session
of that account ends."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from anamna.db import connect, migrate
from anamna.security import authenticate, create_user
from anamna.web.app import create_app

from test_web_profile import csrf_for, login
from test_web_security import PASSWORD, settings_for

NEW = "a-brand-new-password"


def _sessions(settings, user_id):
    with connect(settings) as db:
        return db.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (user_id,)).fetchone()[0]


def test_admin_sets_a_new_password_and_signs_the_person_out(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANAMNA_BACKGROUND_WORKERS", "0")
    settings = settings_for(tmp_path)
    migrate(settings)
    admin = create_user(settings, "root@example.test", "Root", PASSWORD)  # first account: administrator
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    app = create_app(settings)
    with TestClient(app) as root, TestClient(app) as person:
        login(root, "root@example.test")
        login(person, "beta@example.test")
        assert _sessions(settings, beta) == 1
        for locale, label in (("en", "Set a new password"), ("uk", "Задати новий пароль")):
            page = root.get(f"/admin/users?lang={locale}").text
            assert label in page and "admin.set_password" not in page
        csrf = csrf_for(settings, root)
        url = f"/admin/users/{beta}/password"
        # CSRF, matching, length: each refused with nothing changed.
        assert root.post(url, data={"new_password": NEW, "confirm_password": NEW, "csrf_token": "x"}).status_code == 403
        mismatch = root.post(url, data={"new_password": NEW, "confirm_password": NEW + "!", "csrf_token": csrf}, follow_redirects=False)
        assert mismatch.headers["location"].endswith("error=admin.error_password_match")
        short = root.post(url, data={"new_password": "short", "confirm_password": "short", "csrf_token": csrf}, follow_redirects=False)
        assert short.headers["location"].endswith("error=admin.error_password")
        own = root.post(f"/admin/users/{admin}/password", data={"new_password": NEW, "confirm_password": NEW, "csrf_token": csrf}, follow_redirects=False)
        assert own.headers["location"].endswith("error=admin.error_password_self")
        assert authenticate(settings, "beta@example.test", PASSWORD) is not None
        # A non-administrator cannot use it.
        assert person.post(f"/admin/users/{admin}/password", data={"new_password": NEW, "confirm_password": NEW, "csrf_token": csrf_for(settings, person)}).status_code == 403
        done = root.post(url, data={"new_password": NEW, "confirm_password": NEW, "csrf_token": csrf}, follow_redirects=False)
        assert done.status_code == 303 and done.headers["location"].endswith("done=password_set")
        assert authenticate(settings, "beta@example.test", NEW) is not None
        assert authenticate(settings, "beta@example.test", PASSWORD) is None
        assert _sessions(settings, beta) == 0  # signed out everywhere
        assert person.get("/profile", follow_redirects=False).status_code == 303
        page = root.get("/admin/users?done=password_set&lang=uk").text
        assert "Новий пароль задано" in page and NEW not in page
        with connect(settings) as db:
            rows = db.execute("SELECT entity_id, details_json FROM audit_events WHERE action='user_password_set_by_admin'").fetchall()
        assert [row[0] for row in rows] == [beta]
        assert NEW not in json.dumps([dict(row) for row in rows])
