"""The OpenWearables integration as the browser meets it.

Two layers of consent, so two halves: the operator names the server and holds
its key at ``/admin/openwearables``, and each person picks their own account on
that server from the profile's Connections tab.  What is asserted here is the
web contract around :mod:`anamna.openwearables` — the gates, the secret
that is never echoed back, the account list a hand-written POST cannot bypass,
and the promise that a server which is down costs a notice rather than a page.

HTTP is stubbed at ``openwearables._request``, the one door every real call
goes through, and the background threads are neutralised: what the sync itself
writes is test_openwearables.py's subject.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import openwearables
from anamna.db import connect, utc_now
from anamna.security import create_session, create_user
from anamna.web.app import create_app

from test_web_issue_reports import csrf_for
from test_web_panels import PASSWORD, build


URL = "https://ow.example.test"
KEY = "ow-key-abcdef"

REMOTE = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "created_at": "2024-01-01T00:00:00Z",
        "first_name": "Panels",
        "last_name": "Tester",
        # Deliberately not the same case as the account here: the preselection
        # matches addresses, and an address is case-insensitive.
        "email": "Panels@Example.Test",
        "external_user_id": "ext-1",
        "last_synced_at": "2026-08-06T10:00:00Z",
        "last_synced_provider": "apple_health",
        "has_active_connection": True,
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "created_at": "2024-01-01T00:00:00Z",
        "first_name": "Someone",
        "last_name": "Else",
        "email": "else@example.test",
        "external_user_id": "ext-2",
        "last_synced_at": None,
        "last_synced_provider": None,
        "has_active_connection": False,
    },
]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """No ambient server, no in-flight sync left by an earlier test."""
    monkeypatch.delenv("ANAMNA_OPENWEARABLES_URL", raising=False)
    monkeypatch.delenv("ANAMNA_OPENWEARABLES_API_KEY", raising=False)
    openwearables.reset_module_state()


def configure(settings, *, url: str = URL, key: str = KEY, enabled: str = "1") -> None:
    openwearables.save_settings(
        settings,
        {
            "openwearables_enabled": enabled,
            "openwearables_url": url,
            "openwearables_api_key": key,
        },
    )


def serve_users(monkeypatch, items: list[dict] | None = None, calls: list | None = None):
    """``_request`` answering the user list, the only endpoint the web layer
    reaches on its own."""

    def request(url, **kwargs):
        if calls is not None:
            calls.append({"url": url, **kwargs})
        assert "/api/v1/users" in url, url
        return {"items": REMOTE if items is None else items, "total": 2, "page": 1,
                "limit": 100, "pages": 1, "has_next": False, "has_prev": False}

    monkeypatch.setattr(openwearables, "_request", request)


def refuse(monkeypatch, status: int | None = None):
    def request(url, **kwargs):
        raise openwearables.OpenWearablesError("nope", status=status)

    monkeypatch.setattr(openwearables, "_request", request)


def no_threads(monkeypatch) -> dict[str, list[str]]:
    """The two background entry points, recorded instead of run."""
    spawned: dict[str, list[str]] = {"backfill": [], "sync": []}
    monkeypatch.setattr(
        openwearables, "start_backfill", lambda _s, user_id: spawned["backfill"].append(user_id)
    )
    monkeypatch.setattr(
        openwearables, "start_recent_sync", lambda _s, user_id: spawned["sync"].append(user_id)
    )
    return spawned


def stored(settings) -> dict[str, str]:
    return openwearables.ow_settings(settings)


def connections(settings) -> list:
    with connect(settings) as db:
        return db.execute(
            "SELECT * FROM provider_connections WHERE provider=?", (openwearables.PROVIDER,)
        ).fetchall()


def seed_days(settings, user_id: str, days: tuple[str, ...]) -> None:
    """Synced rows, without running a sync: what unlinking must not delete."""
    import_id = openwearables.ensure_envelope(settings, user_id)
    with connect(settings) as db:
        patient_id = db.execute(
            "SELECT id FROM patients WHERE owner_user_id=?", (user_id,)
        ).fetchone()["id"]
        for day in days:
            db.execute(
                """INSERT INTO device_metric_days(
                       id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                       metric_key, metric_name, category, day, aggregation, unit, value,
                       sample_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'steps', 'Daily steps', 'device_activity', ?,
                           'sum', 'steps', 8000, 1, ?)""",
                (f"day-{day}", user_id, patient_id, import_id, openwearables.SOURCE_NAME,
                 openwearables.SOURCE_NAME, day, utc_now()),
            )


def second_person(settings, tmp_path: Path) -> TestClient:
    """A signed-in member.  The account `build` makes is the first in the
    database and therefore the administrator."""
    user_id = create_user(settings, "member@example.test", "Member", PASSWORD)
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    client.cookies.set("anamna_lang", "en")
    return client


# --- the administrator's half ------------------------------------------------


def test_admin_page_is_for_administrators_only(tmp_path: Path):
    settings, _, client = build(tmp_path)
    # A stranger is 401 inside, which the handler turns into a trip to sign in;
    # a signed-in member is 403, because signing in again would not help.
    stranger = TestClient(create_app(settings)).get(
        "/admin/openwearables", follow_redirects=False
    )
    assert stranger.status_code == 303 and stranger.headers["location"].startswith("/login")
    assert second_person(settings, tmp_path).get("/admin/openwearables").status_code == 403
    page = client.get("/admin/openwearables")
    assert page.status_code == 200
    assert "OpenWearables" in page.text


def test_saving_keeps_the_stored_key_until_it_is_cleared(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    saved = client.post(
        "/admin/openwearables",
        data={"csrf_token": csrf, "enabled": "1", "url": f"{URL}/", "api_key": KEY},
        follow_redirects=False,
    )
    assert saved.headers["location"] == "/admin/openwearables?done=saved"
    assert stored(settings) == {"enabled": "1", "url": URL, "api_key": KEY}
    assert openwearables.configured(settings)

    # An untouched form submits a blank secret; that means "keep it".
    client.post(
        "/admin/openwearables",
        data={"csrf_token": csrf, "enabled": "1", "url": URL, "api_key": ""},
        follow_redirects=False,
    )
    assert stored(settings)["api_key"] == KEY

    # The page shows the tail, never the key — nor in the value of any field.
    page = client.get("/admin/openwearables").text
    assert KEY not in page
    assert KEY[-6:] in page

    client.post(
        "/admin/openwearables",
        data={"csrf_token": csrf, "enabled": "1", "url": URL, "api_key": "", "clear_key": "1"},
        follow_redirects=False,
    )
    assert stored(settings)["api_key"] == ""
    assert not openwearables.configured(settings)


def test_saving_a_different_server_unlinks_and_says_so(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    openwearables.link_account(settings, user_id, REMOTE[0]["id"], REMOTE[0]["email"])
    seed_days(settings, user_id, ("2026-08-01",))
    moved = client.post(
        "/admin/openwearables",
        data={
            "csrf_token": csrf_for(settings, user_id),
            "enabled": "1",
            "url": "https://other.example.test",
            "api_key": "",
        },
        follow_redirects=False,
    )
    assert moved.headers["location"] == "/admin/openwearables?done=saved_relink"
    assert connections(settings) == []
    # The measurements are the person's own and survive the operator's edit.
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_metric_days").fetchone()[0] == 1


def test_a_junk_address_is_refused_before_it_is_stored(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    bad = client.post(
        "/admin/openwearables",
        data={"csrf_token": csrf_for(settings, user_id), "enabled": "1", "url": "ow.example.test"},
        follow_redirects=False,
    )
    assert bad.headers["location"] == "/admin/openwearables?error=openwearables.error_url"
    assert stored(settings)["url"] == ""


def test_the_test_button_makes_one_real_authenticated_request(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    # Nothing configured: no request is attempted at all.
    refuse(monkeypatch)
    empty = client.post(
        "/admin/openwearables/test", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert empty.headers["location"] == "/admin/openwearables?error=openwearables.error_url"

    configure(settings)
    calls: list = []
    serve_users(monkeypatch, calls=calls)
    good = client.post(
        "/admin/openwearables/test", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert good.headers["location"] == "/admin/openwearables?done=test_ok&users=2"
    assert calls[0]["headers"]["X-Open-Wearables-API-Key"] == KEY
    assert "2 accounts" in client.get("/admin/openwearables?done=test_ok&users=2").text

    refuse(monkeypatch, status=401)
    denied = client.post(
        "/admin/openwearables/test", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert denied.headers["location"] == "/admin/openwearables?error=openwearables.error_unauthorized"

    refuse(monkeypatch)
    down = client.post(
        "/admin/openwearables/test", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert down.headers["location"] == "/admin/openwearables?error=openwearables.error_unreachable"


# --- the person's half -------------------------------------------------------


def test_with_no_server_configured_there_is_nothing_to_find(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    page = client.get("/profile").text
    # The administration page stays in the nav — that is where it gets turned
    # on — but the person's card and its routes are simply not there.
    assert "/profile/openwearables/" not in page
    assert "profile-panel-connections" not in page  # no tab, no panel
    csrf = csrf_for(settings, user_id)
    for path in ("link", "unlink", "sync"):
        response = client.post(
            f"/profile/openwearables/{path}",
            data={"csrf_token": csrf, "remote_user_id": REMOTE[0]["id"]},
            follow_redirects=False,
        )
        assert response.status_code == 404, path
    # The devices page offers no vendor card for a server nobody configured —
    # only the administration link in the account menu names it.
    assert "<h3>OpenWearables</h3>" not in client.get("/devices").text


def test_the_vendor_card_outlives_a_switched_off_feature(tmp_path: Path, monkeypatch):
    """Rows a since-disabled link wrote must keep saying where they came from —
    unexplained measurements are worse than no measurements."""
    settings, user_id, client = build(tmp_path)
    monkeypatch.setattr(openwearables, "maybe_refresh", lambda *args: None)
    configure(settings)
    assert "<h3>OpenWearables</h3>" in client.get("/devices").text
    seed_days(settings, user_id, ("2026-08-01",))
    configure(settings, enabled="0")
    assert not openwearables.configured(settings)
    assert "<h3>OpenWearables</h3>" in client.get("/devices").text


def test_the_card_offers_the_accounts_and_preselects_your_own(tmp_path: Path, monkeypatch):
    settings, _, client = build(tmp_path)
    configure(settings)
    serve_users(monkeypatch)
    page = client.get("/profile?tab=connections").text
    assert 'action="/profile/openwearables/link"' in page
    assert f'<option value="{REMOTE[0]["id"]}" selected>' in page
    assert f'<option value="{REMOTE[1]["id"]}" >' in page
    assert "else@example.test" in page


def test_a_server_that_will_not_answer_costs_a_notice_not_the_page(tmp_path: Path, monkeypatch):
    settings, _, client = build(tmp_path)
    configure(settings)
    refuse(monkeypatch)
    page = client.get("/profile?tab=connections")
    assert page.status_code == 200
    assert "not answering right now" in page.text
    assert 'action="/profile/openwearables/link"' not in page.text


def test_linking_stores_the_choice_and_starts_the_backfill(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    serve_users(monkeypatch)
    spawned = no_threads(monkeypatch)
    linked = client.post(
        "/profile/openwearables/link",
        data={"csrf_token": csrf_for(settings, user_id), "remote_user_id": REMOTE[0]["id"]},
        follow_redirects=False,
    )
    assert linked.headers["location"] == "/profile?saved=openwearables_linked"
    (row,) = connections(settings)
    assert row["user_id"] == user_id and row["external_user_id"] == REMOTE[0]["id"]
    assert spawned["backfill"] == [user_id]
    # The address is remembered as the server spells it, for the card to show.
    assert openwearables.sync_state(settings, user_id)["remote_email"] == REMOTE[0]["email"]

    page = client.get("/profile?saved=openwearables_linked").text
    assert "Account linked" in page
    assert 'action="/profile/openwearables/sync"' in page
    assert 'action="/profile/openwearables/unlink"' in page
    assert REMOTE[0]["email"] in page


def test_link_refuses_an_account_the_server_never_offered(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    serve_users(monkeypatch)
    spawned = no_threads(monkeypatch)
    forged = client.post(
        "/profile/openwearables/link",
        data={"csrf_token": csrf_for(settings, user_id), "remote_user_id": "not-on-the-list"},
        follow_redirects=False,
    )
    assert forged.headers["location"] == "/profile?error=openwearables.error_user"
    assert connections(settings) == []
    assert spawned["backfill"] == []


def test_link_survives_a_server_that_dies_between_page_and_press(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    refuse(monkeypatch)
    no_threads(monkeypatch)
    response = client.post(
        "/profile/openwearables/link",
        data={"csrf_token": csrf_for(settings, user_id), "remote_user_id": REMOTE[0]["id"]},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/profile?error=openwearables.error_unreachable"
    assert connections(settings) == []


def test_linking_a_different_account_says_the_earlier_data_was_replaced(
    tmp_path: Path, monkeypatch
):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    serve_users(monkeypatch)
    no_threads(monkeypatch)
    csrf = csrf_for(settings, user_id)
    client.post(
        "/profile/openwearables/link",
        data={"csrf_token": csrf, "remote_user_id": REMOTE[0]["id"]},
        follow_redirects=False,
    )
    seed_days(settings, user_id, ("2026-08-01", "2026-08-02"))
    swapped = client.post(
        "/profile/openwearables/link",
        data={"csrf_token": csrf, "remote_user_id": REMOTE[1]["id"]},
        follow_redirects=False,
    )
    assert swapped.headers["location"] == "/profile?saved=openwearables_replaced"
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_metric_days").fetchone()[0] == 0
    assert "everything the previous link had synced was deleted" in client.get(
        "/profile?saved=openwearables_replaced"
    ).text


def test_unlinking_stops_the_sync_and_keeps_every_measurement(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    serve_users(monkeypatch)
    no_threads(monkeypatch)
    openwearables.link_account(settings, user_id, REMOTE[0]["id"], REMOTE[0]["email"])
    seed_days(settings, user_id, ("2026-08-01", "2026-08-02"))
    gone = client.post(
        "/profile/openwearables/unlink",
        data={"csrf_token": csrf_for(settings, user_id)},
        follow_redirects=False,
    )
    assert gone.headers["location"] == "/profile?saved=openwearables_unlinked"
    assert connections(settings) == []
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM device_metric_days").fetchone()[0] == 2
    assert "stays in your record" in client.get("/profile?saved=openwearables_unlinked").text


def test_sync_now_asks_for_the_recent_window(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    spawned = no_threads(monkeypatch)
    csrf = csrf_for(settings, user_id)
    # Nothing linked: there is no account to sync.
    assert client.post(
        "/profile/openwearables/sync", data={"csrf_token": csrf}, follow_redirects=False
    ).status_code == 404

    openwearables.link_account(settings, user_id, REMOTE[0]["id"], REMOTE[0]["email"])
    started = client.post(
        "/profile/openwearables/sync", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert started.headers["location"] == "/profile?saved=openwearables_sync"
    assert spawned["sync"] == [user_id]


def test_a_failed_dataset_is_named_on_both_pages(tmp_path: Path, monkeypatch):
    """A dataset that stopped arriving must not read as a quiet week."""
    settings, user_id, client = build(tmp_path)
    configure(settings)
    monkeypatch.setattr(openwearables, "maybe_refresh", lambda *args: None)
    openwearables.link_account(settings, user_id, REMOTE[0]["id"], REMOTE[0]["email"])
    openwearables._update_state(
        settings, user_id, failed_datatypes={"sleep": "HTTP 500: boom"}, last_sync_at=utc_now()
    )
    profile = client.get("/profile?tab=connections").text
    assert "Deep sleep" in profile  # named by its measurements, not by "sleep"
    devices = client.get("/devices").text
    assert "Some OpenWearables data is not arriving" in devices
    assert "HTTP 500: boom" in devices  # the server's own words, verbatim


def test_opening_the_devices_page_tops_the_sync_up(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    spawned = no_threads(monkeypatch)
    openwearables.link_account(settings, user_id, REMOTE[0]["id"], REMOTE[0]["email"])
    assert client.get("/devices").status_code == 200
    assert spawned["sync"] == [user_id]  # never synced: due immediately
    openwearables._update_state(settings, user_id, last_sync_at=utc_now())
    client.get("/devices")
    assert spawned["sync"] == [user_id]  # fresh enough: not asked again


def test_the_card_is_ukrainian_in_the_ukrainian_locale(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    serve_users(monkeypatch)
    no_threads(monkeypatch)
    client.cookies.set("anamna_lang", "uk")
    # Assertions avoid the apostrophe in «Пов'язати»: Jinja escapes it to
    # &#39;, so the literal would never match however right the page is.
    unlinked = client.get("/profile?tab=connections").text
    assert "Сервер OpenWearables" in unlinked
    assert "Ваш обліковий запис на цьому сервері" in unlinked
    assert "Link this account" not in unlinked
    assert "Your account on that server" not in unlinked

    openwearables.link_account(settings, user_id, REMOTE[0]["id"], REMOTE[0]["email"])
    linked = client.get("/profile?tab=connections").text
    assert "Синхронізувати зараз" in linked
    assert "Остання перевірка" in linked
    assert "Sync now" not in linked
    assert "Unlink" not in linked

    admin = client.get("/admin/openwearables").text
    assert "Сервер OpenWearables" in admin
    assert "Зберегти налаштування" in admin
    assert "Save settings" not in admin
