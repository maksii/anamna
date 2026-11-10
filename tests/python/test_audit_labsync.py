"""Audit fixes for the laboratory sync: one refused order, transient errors,
forgetting an account, vendor-scoped matching, Synevo's one-person shortcut,
the card's credential marker, truncated downloads, docx size, and what the
Doctor Eleks log says about a server reply.

Every fake is the one in ``test_labsync.py``: HTTP is stubbed at
``common._http`` and intake at ``labsync.intake.enqueue``.  No laboratory is
ever called.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import uuid
import zipfile
from pathlib import Path

import pytest

from anamna import labsync
from anamna.db import connect, utc_now
from anamna.labsync import LabSyncError, common, doctoreleks, expert, synevo, visit_pdf
from anamna.security import create_user
from test_labsync import (
    connect_esculab,
    es_row,
    esculab_routes,
    make,
    order,
    router,
    seed_doc,
    sign_in_esculab,
    stub_intake,
)

RECORD_RESULT = "Гемоглобін (HGB)"


def _intake_for(orders: tuple[str, ...]) -> dict[str, dict]:
    """A finished document for each downloaded order named."""
    return {
        f"esculab-{number}.pdf": {"vendor": "Esculab", "order": number, "day": "2026-01-10",
                                  "values": [(RECORD_RESULT, 151.0, "г/л", None)]}
        for number in orders
    }


def _three_orders_routes():
    numbers = ("9001", "9002", "9003")
    orders = [order(int(number), ready=1, total=1, dt=f"2026-01-1{index + 1} 08:00")
              for index, number in enumerate(numbers)]
    rows = {number: [es_row(RECORD_RESULT, "151", "г/л")] for number in numbers}
    return esculab_routes(orders, rows)


# --- defect 1: one refused order is that order's failure ----------------------------


def test_one_refused_order_is_recorded_and_the_others_still_import(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    routes = _three_orders_routes()
    routes[("GET", "/api/results/getResults/111/9002")] = lambda body, headers: 403  # the lab refuses this PDF
    connect_esculab(settings, user_id, monkeypatch, routes)
    calls = stub_intake(monkeypatch, settings, user_id, _intake_for(("9001", "9003")))

    summary = labsync.sync(settings, user_id, "esculab", inline=True)

    assert (summary["imported"], summary["failed"]) == (2, 1)
    assert calls == ["esculab-9001.pdf", "esculab-9003.pdf"]
    with connect(settings) as connection:
        tracked = {row["order_id"]: dict(row) for row in connection.execute("SELECT * FROM lab_orders")}
    assert tracked["9001"]["state"] == tracked["9003"]["state"] == "imported"
    assert tracked["9002"]["state"] == "failed"
    assert tracked["9002"]["error_key"] == "labsync.error_order_forbidden"
    assert labsync.account(settings, user_id, "esculab")["sync_state"] == "done"


def test_two_refused_orders_in_a_row_are_a_refused_credential(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    routes = _three_orders_routes()
    routes[("GET", "/api/results/getResults/111/9001")] = lambda body, headers: 403
    routes[("GET", "/api/results/getResults/111/9002")] = lambda body, headers: 403
    connect_esculab(settings, user_id, monkeypatch, routes)

    with pytest.raises(common.LabSyncError) as caught:
        labsync.sync(settings, user_id, "esculab", inline=True)

    assert caught.value.key == "labsync.error_auth"
    assert labsync.account(settings, user_id, "esculab")["sync_detail_key"] == "labsync.error_auth"


def test_a_failed_list_for_one_linked_person_does_not_stop_the_next(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    monkeypatch.setattr(common, "_http", router(esculab_routes([], {})))
    sign_in_esculab(settings, user_id)
    labsync.check_account(settings, user_id, "esculab")
    labsync.link_person(settings, user_id, "esculab", "111", "self", confirmed=False)
    labsync.link_person(settings, user_id, "esculab", "222", "self", confirmed=True)
    seen: list[str] = []

    def listing(*args, **kwargs):
        person = args[5]
        seen.append(str(person["id"]))
        if str(person["id"]) == "111":
            raise common.LabSyncError("labsync.error_reply")
        return None

    monkeypatch.setattr(labsync, "_sync_link", listing)

    summary = labsync.sync(settings, user_id, "esculab", inline=True)

    assert sorted(seen) == ["111", "222"]
    assert summary["failed"] == 1


def test_an_auth_error_from_the_list_call_still_stops_the_run(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    monkeypatch.setattr(common, "_http", router(esculab_routes([], {})))
    sign_in_esculab(settings, user_id)
    labsync.check_account(settings, user_id, "esculab")
    labsync.link_person(settings, user_id, "esculab", "111", "self", confirmed=False)
    labsync.link_person(settings, user_id, "esculab", "222", "self", confirmed=True)

    def refused(*args, **kwargs):
        raise common.LabSyncError("labsync.error_auth", 401)

    monkeypatch.setattr(labsync, "_sync_link", refused)

    with pytest.raises(common.LabSyncError) as caught:
        labsync.sync(settings, user_id, "esculab", inline=True)
    assert caught.value.key == "labsync.error_auth"


# --- defect 2: a transient error keeps an imported order imported ---------------------


def test_an_imported_order_that_hits_a_transient_error_keeps_its_state(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    routes = esculab_routes([order(9001, ready=1, total=1)], {"9001": [es_row(RECORD_RESULT, "151", "г/л")]})
    connect_esculab(settings, user_id, monkeypatch, routes)
    stub_intake(monkeypatch, settings, user_id, _intake_for(("9001",)))
    assert labsync.sync(settings, user_id, "esculab", inline=True)["imported"] == 1

    def unreachable(body, headers):
        raise common.LabSyncError("labsync.error_unreachable")

    routes[("GET", "/api/customers/getOrdersResult/9001/111")] = unreachable
    summary = labsync.sync(settings, user_id, "esculab", inline=True)

    assert summary["failed"] == 1
    with connect(settings) as connection:
        tracked = dict(connection.execute(
            "SELECT state, error_key, document_id FROM lab_orders WHERE order_id='9001'").fetchone())
    assert tracked["state"] == "imported"
    assert tracked["error_key"] == "labsync.error_unreachable"
    assert tracked["document_id"]


# --- defect 3: forgetting keeps the device id, never the trusted-device token ----------


def test_forgetting_a_lab_keeps_the_device_id_and_drops_the_trusted_token(tmp_path: Path):
    settings, user_id, _ = make(tmp_path)
    device = str(uuid.uuid4())
    with connect(settings) as connection:
        connection.execute("INSERT OR IGNORE INTO lab_accounts(user_id, provider, updated_at) VALUES (?, ?, '2026-01-01')",
                           (user_id, "esculab"))
        connection.execute(
            "UPDATE lab_accounts SET secret='secret-value', refresh_secret=? WHERE user_id=? AND provider='esculab'",
            (json.dumps({"device_id": device, "trusted": "trusted-token-do-not-keep"}), user_id))

    labsync.forget(settings, user_id, "esculab")

    row = labsync.account(settings, user_id, "esculab")
    assert row["secret"] == ""
    assert json.loads(row["refresh_secret"]) == {"device_id": device}
    assert "trusted-token-do-not-keep" not in row["refresh_secret"]


# --- defect 4: a by-number match only counts this lab's documents --------------------


def test_a_number_only_matches_a_document_of_the_same_lab(tmp_path: Path):
    settings, user_id, _ = make(tmp_path)
    other_lab = seed_doc(settings, user_id, vendor="Synevo", order="9001", day="2026-01-10", values=[])
    same_lab = seed_doc(settings, user_id, vendor="Esculab", order="9001", day="2026-01-10", values=[])
    no_vendor = seed_doc(settings, user_id, vendor="Esculab", order="9001", day="2026-01-10", values=[])
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET vendor_id=NULL WHERE id=?", (no_vendor,))

    with connect(settings) as connection:
        found = labsync.documents_for_order(connection, user_id, ["9001"], "esculab")

    assert other_lab not in found
    assert same_lab in found and no_vendor in found


# --- defect 5: a one-person account accepts an order under another Synevo handle -----


def test_synevo_one_person_account_accepts_an_item_under_another_handle():
    client = synevo.Client("https://www.synevo.ua", "x" * 64)
    one_person = {"match_ids": ["p1"], "account_size": 1}
    two_people = {"match_ids": ["p1"], "account_size": 2}
    other_handle = {"Person": {"_id": "other-9"}}
    # One person on the account: the order's handle may differ from the linked ids.
    assert client._mine(other_handle, one_person) is True
    # Two or more people: a handle we do not hold is not provably ours.
    assert client._mine(other_handle, two_people) is False
    # An item under a linked id is ours regardless of the account size.
    assert client._mine({"Person": {"_id": "p1"}}, one_person) is True
    assert client._mine({"Person": {"_id": "p1"}}, two_people) is True


# --- defect 6: the card carries a marker, never a part of the credential --------------


def test_secret_tail_is_a_hash_marker_not_the_credential_tail():
    marker = labsync.secret_tail("abcdef123456")
    assert len(marker) == 6
    assert "123456" not in marker
    assert marker == hashlib.sha256(b"abcdef123456").hexdigest()[:6]
    assert labsync.secret_tail("") == ""


# --- defect 7: truncated downloads are unreachable, never stored ----------------------


class _Cut:
    """A response whose body ends early."""

    status = 200
    headers = http.client.HTTPMessage()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, _limit=-1):
        raise http.client.IncompleteRead(b"")


class _CutOpener:
    def open(self, request, timeout=0):
        return _Cut()


def test_a_body_cut_short_mid_transfer_is_unreachable(monkeypatch):
    monkeypatch.setattr(common, "_opener", _CutOpener())
    with pytest.raises(common.LabSyncError) as caught:
        common._http("GET", "http://127.0.0.1:9/report", headers={})
    assert caught.value.key == "labsync.error_unreachable"


def test_a_pdf_without_its_end_marker_is_refused_as_unreachable(monkeypatch):
    truncated = b"%PDF-1.4 the first page and then nothing more"
    monkeypatch.setattr(common, "_http", lambda *args, **kwargs: (200, [], truncated))
    with pytest.raises(common.LabSyncError) as caught:
        common.call("GET", "http://127.0.0.1:9/report.pdf", headers={}, want="pdf")
    assert caught.value.key == "labsync.error_unreachable"

    whole = b"%PDF-1.4 the whole report\n%%EOF\n"
    monkeypatch.setattr(common, "_http", lambda *args, **kwargs: (200, [], whole))
    assert common.call("GET", "http://127.0.0.1:9/report.pdf", headers={}, want="pdf")[0] == whole


# --- defect 8: an oversized docx member is refused -------------------------------------


def test_a_docx_member_over_the_size_limit_is_refused(monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>",
        )
    data = buffer.getvalue()
    assert visit_pdf.docx_pdf(data, "consult").startswith(b"%PDF")

    monkeypatch.setattr(visit_pdf, "MAX_MEMBER_BYTES", 10)
    with pytest.raises(common.LabSyncError) as caught:
        visit_pdf.docx_pdf(data, "consult")
    assert caught.value.key == "labsync.error_pdf"


# --- defect 9: a server's sentence is logged by length and field names only ----------


def test_a_server_sentence_is_logged_by_length_never_as_text(caplog):
    reply = "@Foo is not a parameter for procedure spiUserPatientDetails."
    with caplog.at_level("WARNING"):
        error = doctoreleks._unreadable("spiUserPatientDetails", reply, "a sentence instead of data")
    assert error.key == "labsync.error_reply"
    assert f"replied {len(reply)} characters" in caplog.text
    assert "Foo" not in caplog.text and "parameter" not in caplog.text


# --- defect 10: a truncated expert PDF is unreachable, never returned -----------------


def test_a_truncated_expert_pdf_is_unreachable_and_never_returned(monkeypatch):
    order = {"order_id": "r7", "packet": "УЗД", "dates": ["2025-01-01"], "has_file": True,
             "files": [{"file_id": 7, "name": "UZD.pdf", "mime_type": "application/pdf"}]}
    person = {"id": "p41", "family_member_id": None}
    client = expert.Client("http://127.0.0.1:9", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.YWNjZXNzLXNpZ25hdHVyZQ", "", "")

    monkeypatch.setattr(common, "_http", router({
        ("GET", "/api/v1/medical/research/7/file"): b"%PDF-1.4 the first page and then nothing"}))
    with pytest.raises(LabSyncError) as caught:
        client.pdfs(order, person)
    assert caught.value.key == "labsync.error_unreachable"

    whole = b"%PDF-1.4 the whole report\n%%EOF\n"
    monkeypatch.setattr(common, "_http", router({("GET", "/api/v1/medical/research/7/file"): whole}))
    assert client.pdfs(order, person) == [whole]


# --- defect 11: a lab amendment to an order in the record is asked about once -----------


def _rows_changed_tasks(settings) -> list[dict]:
    with connect(settings) as connection:
        return [dict(row) for row in connection.execute(
            "SELECT owner_user_id, entity_id, state FROM review_tasks WHERE reason_key='review.lab_rows_changed'")]


def _imported_esculab_order(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    routes = esculab_routes([order(9001, ready=1, total=1)], {"9001": [es_row(RECORD_RESULT, "151", "г/л")]})
    connect_esculab(settings, user_id, monkeypatch, routes)
    stub_intake(monkeypatch, settings, user_id, _intake_for(("9001",)))
    assert labsync.sync(settings, user_id, "esculab", inline=True)["imported"] == 1

    def amend(value: str) -> None:
        routes[("GET", "/api/customers/getOrdersResult/9001/111")] = (
            lambda body, headers: [es_row(RECORD_RESULT, value, "г/л")])

    return settings, user_id, amend


def test_a_lab_amendment_opens_one_review_task_on_the_document(tmp_path: Path, monkeypatch):
    settings, user_id, amend = _imported_esculab_order(tmp_path, monkeypatch)
    assert _rows_changed_tasks(settings) == []

    amend("160")
    labsync.sync(settings, user_id, "esculab", inline=True)
    with connect(settings) as connection:
        tracked = dict(connection.execute(
            "SELECT document_id, rows_changed_at FROM lab_orders WHERE order_id='9001'").fetchone())
    assert tracked["rows_changed_at"]
    [task] = _rows_changed_tasks(settings)
    assert (task["owner_user_id"], task["entity_id"], task["state"]) == (user_id, tracked["document_id"], "open")

    labsync.sync(settings, user_id, "esculab", inline=True)  # the same amendment, read again
    amend("170")  # a further amendment while that task is still open
    labsync.sync(settings, user_id, "esculab", inline=True)
    assert len(_rows_changed_tasks(settings)) == 1


def test_an_amended_order_without_a_document_opens_no_task(tmp_path: Path, monkeypatch):
    settings, user_id, amend = _imported_esculab_order(tmp_path, monkeypatch)
    with connect(settings) as connection:
        connection.execute("UPDATE lab_orders SET document_id=NULL WHERE order_id='9001'")

    amend("160")
    labsync.sync(settings, user_id, "esculab", inline=True)
    assert _rows_changed_tasks(settings) == []


# --- defect 12: removing a share removes the lab links between the two accounts -------


def test_drop_links_between_removes_both_directions_and_nothing_else(tmp_path: Path):
    settings, user_a, _ = make(tmp_path)
    user_b = create_user(settings, "b@example.test", "B", "synthetic-pass-1234")
    user_c = create_user(settings, "c@example.test", "C", "synthetic-pass-1234")
    links = [
        (user_a, user_b, "p1"),  # a's lab person feeds b's record
        (user_b, user_a, "p2"),  # b's lab person feeds a's record
        (user_a, user_a, "p3"),  # a's own record
        (user_a, user_c, "p4"),  # a's lab person feeds a third user
        (user_c, user_b, "p5"),  # a third user's lab person feeds b
    ]
    with connect(settings) as connection:
        for account, target, remote in links:
            connection.execute(
                """INSERT INTO lab_person_links(account_user_id, provider, remote_person_id, remote_person_json,
                       target_user_id, consent, created_at, updated_at)
                   VALUES (?, 'esculab', ?, '{}', ?, 'owner', ?, ?)""",
                (account, remote, target, utc_now(), utc_now()))
        # Held for b, fetched by a's account, never accepted: what the removal drops.
        connection.execute(
            """INSERT INTO lab_orders(owner_user_id, account_user_id, provider, remote_person_id, order_id, state,
                   first_seen_at, last_synced_at)
               VALUES (?, ?, 'esculab', 'p1', '555', 'awaiting', ?, ?)""", (user_b, user_a, utc_now(), utc_now()))

    assert labsync.drop_links_between(settings, user_a, user_b) == 2

    with connect(settings) as connection:
        remaining = {(row["account_user_id"], row["remote_person_id"]) for row in connection.execute(
            "SELECT account_user_id, remote_person_id FROM lab_person_links")}
        held = connection.execute("SELECT COUNT(*) FROM lab_orders WHERE order_id='555'").fetchone()[0]
    assert remaining == {(user_a, "p3"), (user_a, "p4"), (user_c, "p5")}
    assert held == 0
    assert labsync.drop_links_between(settings, user_a, user_b) == 0
