"""OPS-34: every live session is listed on /profile and can be signed out one
at a time -- never the one making the request.  UX-21: the Connections tab
names each service once, in one vocabulary."""
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from anamna.db import connect, migrate
from anamna.security import create_user, list_sessions
from anamna.web.app import create_app

from test_web_profile import csrf_for, login
from test_web_security import PASSWORD, seed_patient, settings_for

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


def _sessions(settings, user_id):
    with connect(settings) as db:
        return [row[0] for row in db.execute("SELECT token_hash FROM sessions WHERE user_id=?", (user_id,))]


def test_sessions_are_listed_and_signed_out_one_by_one(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    seed_patient(settings, alpha, "Alpha Patient")
    app = create_app(settings)
    with TestClient(app, headers={"User-Agent": IPHONE}) as phone, TestClient(app, headers={"User-Agent": WINDOWS}) as laptop:
        login(phone, "alpha@example.test")
        login(laptop, "alpha@example.test")
        mine = hashlib.sha256(laptop.cookies["anamna_session"].encode()).hexdigest()
        for locale, heading, this, device, other in (
            ("en", "Where you are signed in", "This browser", "Safari on iPhone", "Chrome on Windows"),
            ("uk", "Активні сеанси", "Цей браузер", "Safari на iPhone", "Chrome на Windows"),
        ):
            page = laptop.get(f"/profile?tab=security&lang={locale}").text
            assert heading in page and this in page and device in page and other in page
            assert "profile.session" not in page
            assert mine not in page  # the stored hash never reaches the page
        rows = list_sessions(settings, alpha, laptop.cookies["anamna_session"])
        current = next(row for row in rows if row["current"])
        phone_row = next(row for row in rows if not row["current"])
        csrf = csrf_for(settings, laptop)
        # CSRF is required.
        assert laptop.post("/profile/sessions/revoke", data={"session": phone_row["id"], "csrf_token": "wrong"}).status_code == 403
        # The current session cannot be ended from the list, even by a forged post.
        refused = laptop.post("/profile/sessions/revoke", data={"session": current["id"], "csrf_token": csrf}, follow_redirects=False)
        assert refused.headers["location"].startswith("/profile?error=profile.error_session")
        assert len(_sessions(settings, alpha)) == 2
        done = laptop.post("/profile/sessions/revoke", data={"session": phone_row["id"], "csrf_token": csrf}, follow_redirects=False)
        assert done.status_code == 303 and "saved=session" in done.headers["location"]
        assert _sessions(settings, alpha) == [mine]
        assert phone.get("/profile", follow_redirects=False).status_code == 303  # the phone is out
        assert laptop.get("/profile").status_code == 200  # this browser is not
        assert "That session is signed out." in laptop.get("/profile?saved=session&lang=en").text


def test_sign_out_everywhere_else_keeps_this_browser(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    app = create_app(settings)
    with TestClient(app) as one, TestClient(app) as two, TestClient(app) as three, TestClient(app) as other:
        for client in (one, two, three):
            login(client, "alpha@example.test")
        login(other, "beta@example.test")
        response = one.post("/profile/sessions/revoke-others", data={"csrf_token": csrf_for(settings, one)}, follow_redirects=False)
        assert response.status_code == 303
        assert len(_sessions(settings, alpha)) == 1
        assert len(_sessions(settings, beta)) == 1  # nobody else's sessions
        assert one.get("/profile").status_code == 200


def test_connections_tab_lists_each_service_once_with_one_word_for_connected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANAMNA_TELEGRAM_BOT_TOKEN", "123456:abcdefghijklmnopqrstuvxyz")
    monkeypatch.setenv("ANAMNA_BACKGROUND_WORKERS", "0")  # no poller may reach Telegram
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    seed_patient(settings, alpha, "Alpha Patient")
    with connect(settings) as db:
        db.execute("UPDATE telegram_config SET enabled=1,bot_username='LedgerTestBot',last_success_at='2026-11-01T10:00:00+00:00'")
        db.execute("INSERT INTO telegram_links(owner_user_id,telegram_user_id,chat_id,locale,linked_at) VALUES(?,?,?,?,?)", (alpha, 7, 7, "uk", "2026-11-01T10:00:00+00:00"))
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        page = client.get("/profile?tab=connections&lang=uk").text
        assert 'class="an-conn-row"' not in page  # no second list of the same services
        assert page.count('id="conn-telegram"') == 1
        assert "підключено" in page
        for retired in ("Telegram підключено", "Підключено", "Пов'язано", "під’єднано"):
            assert retired not in page
        # A linked person is told when the bot itself is failing.
        with connect(settings) as db:
            db.execute("UPDATE telegram_config SET last_error='telegram.error_connection',last_error_at='2026-11-02T10:00:00+00:00'")
        page = client.get("/profile?tab=connections&lang=uk").text
        assert "виникла проблема" in page
