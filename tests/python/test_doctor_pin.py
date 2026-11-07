"""Doctor access by six-digit code.

A code is a short, single-use way to the same read-only guest session a
/t/<secret> link opens.  Every boundary is tested from the side that must be
refused, beside the case that works.
"""

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import security
from anamna.db import connect, migrate
from anamna.security import create_doctor_pin, create_user
from anamna.web.app import create_app

from test_web_profile import csrf_for, login
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for


@pytest.fixture(autouse=True)
def fresh_meters():
    """The throttle is an in-process dict; no test may inherit another's knocks."""
    def clear():
        for key in [k for k in security._attempts if k.startswith("doctor-pin:")]:
            del security._attempts[key]
    clear()
    yield
    clear()


@pytest.fixture
def world(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    owner = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, owner, "Alpha Patient")
    seed_document(settings, owner, patient, "Alpha private result", "alpha.txt")
    return settings, owner, create_app(settings)


def shift_clock(monkeypatch, delta: timedelta) -> None:
    """Move security.py's clock; the app's own stays put."""
    class Shifted(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + delta
    monkeypatch.setattr(security, "datetime", Shifted)


def mint_from_profile(app, settings) -> str:
    with TestClient(app) as owner:
        login(owner, "alpha@example.test")
        page = owner.post("/profile/doctor-pin", data={"csrf_token": csrf_for(settings, owner)})
    assert page.status_code == 200
    spaced = re.search(r'aria-label="Access code: ([0-9 ]{11})"', page.text).group(1)
    assert "/doctor" in page.text
    return spaced.replace(" ", "")


def alert(response) -> str:
    return re.search(r'role="alert"[^>]*>([^<]+)<', response.text).group(1)


def test_owner_mints_a_code_and_the_doctor_reads_without_writing(world):
    settings, owner, app = world
    pin = mint_from_profile(app, settings)
    assert len(pin) == 6 and pin.isdigit()

    with TestClient(app) as doctor:
        assert doctor.get("/doctor").status_code == 200
        opened = doctor.post("/doctor", data={"pin": pin[:3] + " " + pin[3:]}, follow_redirects=False)
        assert opened.status_code == 303 and opened.headers["location"] == "/"
        home = doctor.get("/")
        assert home.status_code == 200 and "read-only" in home.text
        assert "Alpha private result" in doctor.get("/documents").text
        # Read-only exactly like a guest link: tools refused, not hidden.
        for path in ("/upload", "/review", "/profile", "/admin/users", "/admin/tokens"):
            assert doctor.get(path).status_code == 403, path
        assert doctor.post("/profile/doctor-pin", data={}).status_code == 403
        assert doctor.post("/tokens", data={"kind": "agent"}).status_code == 403
        # The code page stays open to the guest for the next patient's code.
        assert doctor.get("/doctor").status_code == 200

    with connect(settings) as connection:
        row = connection.execute(
            "SELECT * FROM access_tokens WHERE pin_hash IS NOT NULL"
        ).fetchone()
        assert row["kind"] == "guest" and row["owner_user_id"] == owner
        assert row["pin_redeemed_at"] is not None
        # Session and credential both end 24 h after the code was created.
        created = datetime.fromisoformat(row["created_at"])
        assert datetime.fromisoformat(row["expires_at"]) - created == timedelta(hours=24)
        assert datetime.fromisoformat(row["pin_redeem_by"]) - created == timedelta(minutes=15)
        session = connection.execute(
            "SELECT expires_at FROM sessions WHERE token_id = ?", (row["id"],)
        ).fetchone()
        assert datetime.fromisoformat(session["expires_at"]) <= datetime.fromisoformat(row["expires_at"]) + timedelta(seconds=1)
        actions = [r[0] for r in connection.execute(
            "SELECT action FROM audit_events WHERE entity_id = ? ORDER BY id", (row["id"],)
        )]
        assert actions == ["doctor_pin_created", "doctor_pin_redeemed"]


def test_only_a_keyed_hash_of_the_code_is_stored(world):
    settings, owner, _ = world
    token_id, pin, _, _ = create_doctor_pin(settings, owner)
    with connect(settings) as connection:
        row = dict(connection.execute("SELECT * FROM access_tokens WHERE id = ?", (token_id,)).fetchone())
        dump = "\n".join(map(str, connection.iterdump()))
    assert row["pin_hash"] == security.doctor_pin_digest(settings, pin)
    # Not a plain SHA-256, which a leaked database gives up in 10^6 tries.
    assert row["pin_hash"] != hashlib.sha256(pin.encode()).hexdigest()
    assert pin not in row.values()
    assert re.search(rf"(?<!\d){pin}(?!\d)", dump) is None


def test_a_code_works_once(world):
    settings, _, app = world
    pin = mint_from_profile(app, settings)
    with TestClient(app) as first:
        assert first.post("/doctor", data={"pin": pin}, follow_redirects=False).status_code == 303
    with TestClient(app) as second:
        again = second.post("/doctor", data={"pin": pin}, follow_redirects=False)
        assert again.status_code == 400
        assert second.get("/documents", follow_redirects=False).status_code == 303


def test_a_code_is_only_accepted_inside_its_window(world, monkeypatch):
    settings, owner, app = world
    _, pin, _, _ = create_doctor_pin(settings, owner)
    shift_clock(monkeypatch, timedelta(minutes=16))
    with TestClient(app) as late:
        assert late.post("/doctor", data={"pin": pin}, follow_redirects=False).status_code == 400
    monkeypatch.undo()
    # Still inside the window: accepted.
    _, fresh, _, _ = create_doctor_pin(settings, owner)
    shift_clock(monkeypatch, timedelta(minutes=14))
    with TestClient(app) as prompt:
        assert prompt.post("/doctor", data={"pin": fresh}, follow_redirects=False).status_code == 303


def test_the_session_ends_24_hours_after_the_code_was_created(world, monkeypatch):
    settings, owner, app = world
    _, pin, _, _ = create_doctor_pin(settings, owner)
    with TestClient(app) as doctor:
        doctor.post("/doctor", data={"pin": pin})
        shift_clock(monkeypatch, timedelta(hours=23, minutes=58))
        assert doctor.get("/documents", follow_redirects=False).status_code == 200
        shift_clock(monkeypatch, timedelta(hours=24, minutes=1))
        gone = doctor.get("/documents", follow_redirects=False)
        assert gone.status_code == 303 and gone.headers["location"].startswith("/login")


def test_wrong_expired_used_and_malformed_codes_read_the_same(world, monkeypatch):
    settings, owner, app = world
    _, used, _, _ = create_doctor_pin(settings, owner)
    _, stale, _, _ = create_doctor_pin(settings, owner)
    wrong = next(f"{n:06d}" for n in range(10**6) if f"{n:06d}" not in (used, stale))
    with TestClient(app) as client:
        client.post("/doctor", data={"pin": used})
        messages = {
            alert(client.post("/doctor", data={"pin": wrong})),
            alert(client.post("/doctor", data={"pin": used})),
            alert(client.post("/doctor", data={"pin": "12ab"})),
        }
        shift_clock(monkeypatch, timedelta(minutes=20))
        messages.add(alert(client.post("/doctor", data={"pin": stale})))
    assert len(messages) == 1
    assert "6 digits" in messages.pop()


def test_failed_codes_are_throttled_per_client_and_globally(world):
    settings, owner, app = world
    _, pin, _, _ = create_doctor_pin(settings, owner)
    wrong = "000000" if pin != "000000" else "111111"
    with TestClient(app) as client:
        knock = {"CF-Connecting-IP": "203.0.113.7"}
        for _ in range(security.DOCTOR_PIN_CLIENT_LIMIT):
            assert client.post("/doctor", data={"pin": wrong}, headers=knock).status_code == 400
        # Locked out: even the right code is refused, and is not spent.
        locked = client.post("/doctor", data={"pin": pin}, headers=knock, follow_redirects=False)
        assert locked.status_code == 429 and "Too many" in locked.text
        with connect(settings) as connection:
            assert connection.execute(
                "SELECT pin_redeemed_at FROM access_tokens WHERE pin_hash IS NOT NULL"
            ).fetchone()[0] is None
        # Another clinic is unaffected by that one...
        other = {"CF-Connecting-IP": "198.51.100.1"}
        assert client.post("/doctor", data={"pin": wrong}, headers=other).status_code == 400
        # ...until the server-wide budget is spent, from however many addresses.
        spent = security.DOCTOR_PIN_CLIENT_LIMIT + 1
        for n in range(security.DOCTOR_PIN_GLOBAL_LIMIT - spent):
            client.post("/doctor", data={"pin": wrong}, headers={"CF-Connecting-IP": f"192.0.2.{n}"})
        fresh = {"CF-Connecting-IP": "192.0.2.250"}
        assert client.post("/doctor", data={"pin": pin}, headers=fresh).status_code == 429


def test_revoking_ends_the_doctors_session(world):
    settings, _, app = world
    pin = mint_from_profile(app, settings)
    with TestClient(app) as doctor:
        doctor.post("/doctor", data={"pin": pin})
        assert doctor.get("/documents").status_code == 200
        with TestClient(app) as owner:
            login(owner, "alpha@example.test")
            listing = owner.get("/profile?tab=sharing").text
            token_id = re.search(r'/profile/doctor-pin/([0-9a-f-]+)/revoke', listing).group(1)
            assert "Doctor&#39;s access open" in listing or "Doctor's access open" in listing
            done = owner.post(
                f"/profile/doctor-pin/{token_id}/revoke",
                data={"csrf_token": csrf_for(settings, owner)}, follow_redirects=False,
            )
            assert done.headers["location"] == "/profile?saved=doctor_revoked"
            assert "No doctor can open your record" in owner.get("/profile?saved=doctor_revoked").text
        assert doctor.get("/documents", follow_redirects=False).status_code == 303
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions WHERE token_id IS NOT NULL").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action = 'doctor_pin_revoked' AND entity_id = ?", (token_id,)
        ).fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_another_owner_cannot_revoke_or_mint_against_someone_else(world):
    settings, owner, app = world
    token_id, _, _, _ = create_doctor_pin(settings, owner)
    create_user(settings, "mallory@example.test", "Mallory", PASSWORD)
    with TestClient(app) as mallory:
        login(mallory, "mallory@example.test")
        refused = mallory.post(
            f"/profile/doctor-pin/{token_id}/revoke",
            data={"csrf_token": csrf_for(settings, mallory)}, follow_redirects=False,
        )
        assert refused.headers["location"] == "/profile?error=doctor.error_unknown"
        # Minting needs the CSRF token of the signed-in owner.
        assert mallory.post("/profile/doctor-pin", data={"csrf_token": "nope"}).status_code == 403
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM access_tokens WHERE id = ?", (token_id,)).fetchone()[0] == 1


def test_codes_never_collide_with_a_live_code(world, monkeypatch):
    settings, owner, _ = world
    draws = iter([123456, 123456, 654321])
    monkeypatch.setattr(security.secrets, "randbelow", lambda _: next(draws))
    assert create_doctor_pin(settings, owner)[1] == "123456"
    assert create_doctor_pin(settings, owner)[1] == "654321"


@pytest.mark.parametrize(
    ("locale", "heading", "foreign"),
    [("en", "Open a patient&#39;s record", "Відкрити картку"), ("uk", "Відкрити картку пацієнта", "Open the record")],
)
def test_doctor_page_renders_in_both_locales(world, locale, heading, foreign):
    _, _, app = world
    with TestClient(app) as client:
        client.cookies.set("anamna_lang", locale)
        page = client.get("/doctor").text
        assert heading in page or heading.replace("&#39;", "'") in page
        assert foreign not in page
        assert 'inputmode="numeric"' in page and 'autocomplete="one-time-code"' in page
        assert '<label for="doctor-pin">' in page
        wrong = client.post("/doctor", data={"pin": "000000"}).text
        assert ("6 digits" if locale == "en" else "6 цифр") in wrong
        # Reachable from the sign-in page.
        assert 'href="/doctor"' in client.get("/login").text


def test_the_doctor_address_keeps_the_https_the_visitor_used(tmp_path):
    """Behind the Cloudflare tunnel the app sees http; the address printed for
    the doctor must still be the https one the patient's browser is on."""
    from test_web_panels import build

    settings, _user_id, client = build(tmp_path)
    # The address is printed on the code card, which exists only once a code is minted.
    page = client.post("/profile/doctor-pin", data={"csrf_token": csrf_for(settings, client)},
                       headers={"X-Forwarded-Proto": "https"}).text
    assert "https://testserver/doctor" in page
    assert "http://testserver/doctor" not in page
