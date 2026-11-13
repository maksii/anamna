"""A medicine change refreshes the verdicts the web app memoises for that person.

Warfarin changes how an INR is judged, and the per-person memo is what the
overview and the results list read.  Saving or deleting a medicine must forget
that memo without anyone calling `invalidate_catalog` by hand.
"""

from __future__ import annotations

from pathlib import Path

from anamna.db import connect
from anamna.web import app as web

from test_audit_sample_facts import add_observation
from test_web_panels import build
from test_web_profile import csrf_for

VKA_BAND = "Vitamin K antagonist therapeutic range"
WARFARIN = {
    "kind": "medicine", "status": "current", "name": "Warfarin", "atc_code": "B01AA03",
    "started_on": "2026-03-01",
}


def memoised_inr(settings, user_id: str) -> tuple[object, object]:
    """The INR card as a page reads it: through the per-person memo."""
    token = web._request_cache.set({})
    try:
        with connect(settings) as connection:
            card = next(c for c in web._metric_catalog(connection, user_id) if c["id"] == "inr")
            verdict = card["verdict"] or {}
            return verdict.get("band_label"), verdict.get("authority")
    finally:
        web._request_cache.reset(token)


def sample_with_memo_warm(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_observation(settings, user_id, "inr", 2.5, "2026-04-10", "inr-on", raw_name="INR", unit="ratio")
    web.invalidate_catalog()
    assert memoised_inr(settings, user_id)[0] != VKA_BAND
    return settings, user_id, client


def save_warfarin(settings, client) -> None:
    response = client.post(
        "/medicines", data={"csrf_token": csrf_for(settings, client), **WARFARIN}, follow_redirects=False,
    )
    assert response.status_code == 303


def test_saving_a_medicine_refreshes_the_memoised_verdict(tmp_path: Path):
    settings, user_id, client = sample_with_memo_warm(tmp_path)
    save_warfarin(settings, client)
    assert memoised_inr(settings, user_id) == (VKA_BAND, "curated")


def test_deleting_the_medicine_refreshes_it_back(tmp_path: Path):
    settings, user_id, client = sample_with_memo_warm(tmp_path)
    save_warfarin(settings, client)
    assert memoised_inr(settings, user_id) == (VKA_BAND, "curated")
    with connect(settings) as connection:
        factor_id = connection.execute(
            "SELECT id FROM factors WHERE owner_user_id=?", (user_id,),
        ).fetchone()[0]
    response = client.post(
        f"/medicines/{factor_id}",
        data={"csrf_token": csrf_for(settings, client), "action": "remove"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert memoised_inr(settings, user_id)[0] != VKA_BAND
