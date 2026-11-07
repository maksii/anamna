"""First-run setup: an empty database leads to /setup, which asks for a
one-time code before anyone becomes administrator, and is gone afterwards."""

import html
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import cli
from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.locales.messages import MESSAGES
from anamna.security import (
    LOGIN_ATTEMPT_LIMIT,
    SETUP_CODE_GLOBAL_KEY,
    AlreadySetUp,
    clear_attempts,
    create_user,
    setup_code_matches,
)
from anamna.web import app as app_module
from anamna.web.app import create_app


PASSWORD = "a-long-local-password"


@pytest.fixture(autouse=True)
def fresh_meter():
    clear_attempts("setup-code:testclient")
    clear_attempts(SETUP_CODE_GLOBAL_KEY)
    yield
    clear_attempts("setup-code:testclient")
    clear_attempts(SETUP_CODE_GLOBAL_KEY)


def settings_for(tmp_path: Path, setup_code: str = "") -> Settings:
    sources = tmp_path / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    return Settings(
        database_path=tmp_path / "health.sqlite3", source_dir=sources,
        secret_key="test-secret", session_days=1, setup_code=setup_code,
    )


def form(code: str, **extra) -> dict:
    return {"setup_code": code, "display_name": "Owner Person", "email": "owner@example.test",
            "password": PASSWORD, "date_of_birth": "1990-05-04", "sex_at_birth": "female", **extra}


def users(settings: Settings) -> list[tuple]:
    with connect(settings) as connection:
        return [tuple(row) for row in connection.execute("SELECT email, role FROM users")]


def test_an_empty_database_leads_every_entrance_to_setup(tmp_path: Path):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        for path in ("/", "/login", "/register"):
            assert client.get(path).url.path == "/setup", path
        posted = client.post("/register", data={"email": "a@example.test", "display_name": "A",
                                                "password": PASSWORD}, follow_redirects=False)
        assert posted.headers["location"] == "/setup"
        page = client.get("/setup").text
        assert "becomes the administrator" in page and "sign-up stays closed" in page
        assert 'name="setup_code"' in page and "First-run setup code:" in page
        assert client.app.state.setup_code not in page
    assert users(settings) == []


def test_the_setup_page_is_fully_localized(tmp_path: Path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        client.cookies.set("anamna_lang", "uk")
        body = client.get("/setup").text
        for key in ("setup.heading", "setup.point_admin", "setup.code_label", "setup.submit"):
            assert html.escape(MESSAGES[key]["uk"], quote=False) in body, key
        assert "Set up this server" not in body and "Your account" not in body


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_a_wrong_or_missing_code_is_refused_in_both_languages(tmp_path: Path, locale: str):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        client.cookies.set("anamna_lang", locale)
        for code in ("", "0000-0000-0000-0000"):
            refused = client.post("/setup", data=form(code))
            assert refused.status_code == 400
            assert html.escape(MESSAGES["setup.error_code"][locale], quote=False) in refused.text
            # What was typed is kept, except the code and the password.
            assert 'value="owner@example.test"' in refused.text
            assert PASSWORD not in refused.text
    assert users(settings) == []


def test_the_right_code_creates_administrator_and_record_then_setup_is_gone(tmp_path: Path):
    settings = settings_for(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        created = client.post("/setup", data=form(app.state.setup_code), follow_redirects=False)
        assert created.headers["location"] == "/"
        assert "anamna_session" in created.cookies
        assert client.get("/admin/users").status_code == 200  # signed in, as administrator
    assert users(settings) == [("owner@example.test", "admin")]
    with connect(settings) as connection:
        patient = connection.execute(
            "SELECT p.display_name, p.date_of_birth, p.sex_at_birth FROM patients p"
            " JOIN users u ON u.id = p.owner_user_id"
        ).fetchall()
    assert [tuple(row) for row in patient] == [("Owner Person", "1990-05-04", "female")]

    with TestClient(create_app(settings)) as stranger:
        assert stranger.get("/setup", follow_redirects=False).headers["location"] == "/login"
        again = stranger.post("/setup", data=form(app.state.setup_code, email="second@example.test"),
                              follow_redirects=False)
        assert again.headers["location"] == "/login"
        # The normal pages are back: sign-in renders, sign-up is closed.
        assert stranger.get("/login").url.path == "/login"
        assert stranger.get("/register", follow_redirects=False).headers["location"] == "/login?error=closed"
    assert len(users(settings)) == 1


def test_setup_validates_like_registration(tmp_path: Path):
    settings = settings_for(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        code = app.state.setup_code
        assert "at least 10" in client.post("/setup", data=form(code, password="short")).text
        assert "valid past date" in client.post("/setup", data=form(code, date_of_birth="2999-01-01")).text
        assert client.post("/setup", data=form(code, sex_at_birth="other")).status_code == 400
        assert client.post("/setup", data=form(code, email="")).status_code == 400
        # Blank date of birth and sex are allowed, as on the profile page.
        assert client.post("/setup", data=form(code, date_of_birth="", sex_at_birth=""),
                           follow_redirects=False).headers["location"] == "/"


def test_wrong_codes_are_throttled(tmp_path: Path):
    settings = settings_for(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        for _ in range(LOGIN_ATTEMPT_LIMIT):
            assert client.post("/setup", data=form("wrong")).status_code == 400
        # Now even the right code waits: the meter does not tell guesses apart.
        assert client.post("/setup", data=form(app.state.setup_code)).status_code == 429
    assert users(settings) == []


def test_the_generated_code_is_printed_once_and_an_env_code_is_not(tmp_path: Path, capsys):
    app = create_app(settings_for(tmp_path / "a"))
    printed = capsys.readouterr().out
    assert f"First-run setup code: {app.state.setup_code}" in printed
    with TestClient(app) as client:
        client.get("/setup")
    assert "First-run setup code" not in capsys.readouterr().out  # once, not per visit

    chosen = "operator-chosen-code"
    env_app = create_app(settings_for(tmp_path / "b", setup_code=chosen))
    out = capsys.readouterr().out
    assert chosen not in out and "ANAMNA_SETUP_CODE" in out
    assert env_app.state.setup_code == chosen
    with TestClient(env_app) as client:
        page = client.get("/setup").text
        assert "ANAMNA_SETUP_CODE" in page and chosen not in page
        assert client.post("/setup", data=form(app.state.setup_code)).status_code == 400
        assert client.post("/setup", data=form(chosen), follow_redirects=False).headers["location"] == "/"


def test_two_simultaneous_submissions_make_one_administrator(tmp_path: Path):
    settings = settings_for(tmp_path)
    app = create_app(settings)
    barrier = threading.Barrier(2)
    locations: list[str] = []

    def submit(email: str) -> None:
        with TestClient(app) as client:
            barrier.wait()
            response = client.post("/setup", data=form(app.state.setup_code, email=email),
                                   follow_redirects=False)
            locations.append(response.headers["location"])

    threads = [threading.Thread(target=submit, args=(f"racer{n}@example.test",)) for n in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(locations)[0] == "/"
    assert sorted(locations)[1] in {"/login?error=setup_taken", "/login"}
    assert [role for _email, role in users(settings)] == ["admin"]


def test_the_loser_of_the_race_is_told_what_happened(tmp_path: Path, monkeypatch):
    """Both passed the page's own check; the transaction decides."""
    settings = settings_for(tmp_path)
    app = create_app(settings)
    migrate(settings)
    create_user(settings, "winner@example.test", "Winner", PASSWORD)
    monkeypatch.setattr(app_module, "has_users", lambda _settings: False)
    with TestClient(app) as client:
        lost = client.post("/setup", data=form(app.state.setup_code), follow_redirects=False)
        assert lost.headers["location"] == "/login?error=setup_taken"
        monkeypatch.undo()
        for locale in ("en", "uk"):
            client.cookies.set("anamna_lang", locale)
            message = html.escape(MESSAGES["setup.error_taken"][locale], quote=False)
            assert message in client.get("/login?error=setup_taken").text
    assert users(settings) == [("winner@example.test", "admin")]
    with pytest.raises(AlreadySetUp):
        create_user(settings, "late@example.test", "Late", PASSWORD, first_only=True)


def test_setup_code_comparison():
    assert setup_code_matches("abcd-1234", " abcd-1234 ")
    assert not setup_code_matches("abcd-1234", "abcd-1235")
    assert not setup_code_matches("", "")


def test_cli_init_creates_the_first_administrator_without_a_code(tmp_path: Path, monkeypatch):
    database = tmp_path / "cli.sqlite3"
    monkeypatch.setenv("ANAMNA_DB", str(database))
    monkeypatch.setenv("ANAMNA_SOURCES", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "anamna", "init", "--email", "cli@example.test", "--name", "Cli Owner",
        "--dob", "1985-01-02", "--sex", "male", "--password", PASSWORD,
    ])
    cli.main()
    settings = settings_for(tmp_path)
    settings = replace(settings, database_path=database)
    assert users(settings) == [("cli@example.test", "admin")]
    with connect(settings) as connection:
        row = connection.execute("SELECT date_of_birth, sex_at_birth FROM patients").fetchone()
    assert tuple(row) == ("1985-01-02", "male")
    with TestClient(create_app(settings)) as client:
        assert client.get("/setup", follow_redirects=False).headers["location"] == "/login"
