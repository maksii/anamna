"""OPS-31: the seeded agent key is labelled, flagged, and replaced -- never
duplicated -- when the operator changes ANAMNA_AGENT_TOKEN.  Keys a
person minted are never touched by that rotation."""
from pathlib import Path

from fastapi.testclient import TestClient

from anamna.db import connect, migrate
from anamna.security import access_token_user, create_access_token, create_user, ensure_seeded_token
from anamna.web.app import create_app

from test_web_security import PASSWORD, settings_for


def test_changed_seed_secret_retires_the_old_seeded_row_and_nothing_else(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    admin = create_user(settings, "root@example.test", "Root", PASSWORD)
    first = ensure_seeded_token(settings, "anamna_agent_first-secret")
    # A key the owner made by hand, even with the old seeded label, is theirs.
    minted, _ = create_access_token(settings, admin, "agent", "Seeded agent token", created_by_user_id=admin)
    second = ensure_seeded_token(settings, "anamna_agent_second-secret")
    assert second != first
    assert access_token_user(settings, "anamna_agent_first-secret") is None
    assert access_token_user(settings, "anamna_agent_second-secret")["id"] == admin
    with connect(settings) as db:
        rows = {row["id"]: dict(row) for row in db.execute("SELECT id, seeded, label FROM access_tokens")}
        audit = db.execute("SELECT entity_id, details_json FROM audit_events WHERE action='seeded_token_retired'").fetchall()
    assert set(rows) == {second, minted}
    assert rows[second]["seeded"] == 1 and rows[minted]["seeded"] == 0
    assert [row["entity_id"] for row in audit] == [first]
    # A restart with the same secret changes nothing.
    assert ensure_seeded_token(settings, "anamna_agent_second-secret") == second
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM access_tokens").fetchone()[0] == 2


def test_a_legacy_seeded_row_is_flagged_by_the_migration_and_then_rotated(tmp_path: Path):
    """The sandbox shape: a row the old seeder made (fixed label, no creator)
    beside the current one.  The migration flags it; the next start retires it."""
    settings = settings_for(tmp_path)
    migrate(settings)
    admin = create_user(settings, "root@example.test", "Root", PASSWORD)
    old, _ = create_access_token(settings, admin, "agent", "Seeded agent token", secret="anamna_agent_old-env-value")
    with connect(settings) as db:
        db.execute("UPDATE access_tokens SET seeded=0")
        # Replay the migration's own statement against the pre-migration shape.
        db.execute("""UPDATE access_tokens SET seeded = 1
            WHERE kind = 'agent' AND created_by_user_id IS NULL AND label = 'Seeded agent token'""")
        assert db.execute("SELECT seeded FROM access_tokens WHERE id=?", (old,)).fetchone()[0] == 1
    current = ensure_seeded_token(settings, "anamna_agent_new-env-value")
    with connect(settings) as db:
        assert [row[0] for row in db.execute("SELECT id FROM access_tokens")] == [current]


def test_the_seeded_key_says_where_it_comes_from_in_both_languages(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    secret = "anamna_agent_pinned-for-the-page"
    ensure_seeded_token(settings, secret)
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": f"Bearer {secret}"}
        for locale, name, pill in (("en", "Server agent key", "Set on the server"),
                                   ("uk", "Серверний ключ агента", "Задано на сервері")):
            client.cookies.set("anamna_lang", locale)
            for path in ("/profile?tab=tokens", "/admin/tokens"):
                page = client.get(path, headers=headers).text
                assert name in page and pill in page and "ANAMNA_AGENT_TOKEN" in page
                assert "token.seeded" not in page
