"""Request and process caches that keep one page from re-reading the record.

Each test pins one of the contracts that makes a cache safe: a GET reads the
whole record once, a write path never sees a stale copy, and an owner's
laboratory edit leaves the device scan warm.
"""

from __future__ import annotations

from pathlib import Path

import anamna.devices.queries as queries
from anamna.db import connect
from anamna.web import app as web
from test_web_panels import build


def test_whole_record_rows_are_read_once_per_get_request(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        cache_token = web._request_cache.set({})
        memo_token = web._request_memo.set({})
        try:
            first = web._deduped_observation_rows(connection, user_id)
            second = web._deduped_observation_rows(connection, user_id)
            assert first
            assert first == second
            # The rows are shared; every caller gets dicts of its own.
            assert first is not second
            assert first[0] is not second[0]

            # A POST (no memo) reads the database again and still agrees.
            post_token = web._request_memo.set(None)
            try:
                third = web._deduped_observation_rows(connection, user_id)
                fourth = web._deduped_observation_rows(connection, user_id)
                assert third == fourth == first
            finally:
                web._request_memo.reset(post_token)
        finally:
            web._request_memo.reset(memo_token)
            web._request_cache.reset(cache_token)


def test_owner_invalidation_keeps_the_device_scan(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    scans: list[str] = []

    def scan(connection, owner_user_id, query="", limit=None):
        scans.append(owner_user_id)
        return []

    monkeypatch.setattr(web, "device_metric_catalog", scan)
    web.invalidate_catalog()
    with connect(settings) as connection:

        def read_in_new_request():
            token = web._request_cache.set({})
            try:
                return web._device_rows(connection, user_id)
            finally:
                web._request_cache.reset(token)

        read_in_new_request()
        assert len(scans) == 1

        # A laboratory edit forgets the owner's cards but not the device scan.
        web.invalidate_catalog(user_id)
        read_in_new_request()
        assert len(scans) == 1

        # Only a full invalidation forgets the scan.
        web.invalidate_catalog()
        read_in_new_request()
        assert len(scans) == 2


def test_the_device_overview_reuses_the_kept_scan(tmp_path: Path, monkeypatch):
    settings, owner_id, _ = build(tmp_path)
    scans: list[str] = []

    def scan(connection, owner_user_id, query="", limit=None):
        scans.append(owner_user_id)
        return []

    # Both names are patched: the overview must never reach the scan itself.
    monkeypatch.setattr(web, "device_metric_catalog", scan)
    monkeypatch.setattr(queries, "device_metric_catalog", scan)
    web.invalidate_catalog()
    with connect(settings) as connection:
        cache_token = web._request_cache.set({})
        try:
            web._device_rows(connection, owner_id)
            overview = web._device_overview(connection, owner_id)
        finally:
            web._request_cache.reset(cache_token)
        assert overview["core_metrics"] == []
        assert len(scans) == 1

        # A laboratory edit forgets the overview; the rebuild reuses the kept scan.
        web.invalidate_catalog(owner_id)
        cache_token = web._request_cache.set({})
        try:
            web._device_overview(connection, owner_id)
        finally:
            web._request_cache.reset(cache_token)
        assert len(scans) == 1


def test_a_laboratory_edit_keeps_every_device_only_read(tmp_path: Path, monkeypatch):
    settings, owner_id, _ = build(tmp_path)
    options: list[str] = []

    def device_options(connection, owner_user_id):
        options.append(owner_user_id)
        return []

    monkeypatch.setattr(web, "_correlation_device_options", device_options)
    web.invalidate_catalog()
    with connect(settings) as connection:

        def read_in_new_request():
            token = web._request_cache.set({})
            try:
                return web._correlation_device_half(connection, owner_id)
            finally:
                web._request_cache.reset(token)

        read_in_new_request()
        assert len(options) == 1

        # A laboratory edit forgets the owner's cards but not the device half of the correlation index.
        web.invalidate_catalog(owner_id)
        read_in_new_request()
        assert len(options) == 1

        # Only a full invalidation forgets it.
        web.invalidate_catalog()
        read_in_new_request()
        assert len(options) == 2


def test_a_reading_is_judged_once_until_the_record_changes(tmp_path: Path, monkeypatch):
    settings, owner_id, _ = build(tmp_path)
    judged: list[str] = []
    original = web._judge_reading

    def counting(*args, **kwargs):
        judged.append(str(args[1]))
        return original(*args, **kwargs)

    monkeypatch.setattr(web, "_judge_reading", counting)
    with connect(settings) as connection:
        cache_token = web._request_cache.set({})
        memo_token = web._request_memo.set({})
        try:
            row = next(
                found for found in web._deduped_observation_rows(connection, owner_id)
                if found["value_numeric"] is not None
            )
            concept_id = row["concept_id"]

            # A GET judges the reading once; the second page gets a copy.
            first = web._reading_verdict(connection, concept_id, row, 34, "male")
            second = web._reading_verdict(connection, concept_id, row, 34, "male")
            assert len(judged) == 1
            assert first == second
            assert first[1] is not second[1]
            assert first == original(connection, concept_id, row, 34, "male")

            # A laboratory edit forgets the remembered verdict.
            web.invalidate_catalog(owner_id)
            fresh = web._request_cache.set({})
            try:
                web._reading_verdict(connection, concept_id, row, 34, "male")
            finally:
                web._request_cache.reset(fresh)
            assert len(judged) == 2

            # A POST (no memo) judges afresh on every call.
            post_token = web._request_memo.set(None)
            try:
                web._reading_verdict(connection, concept_id, row, 34, "male")
                web._reading_verdict(connection, concept_id, row, 34, "male")
            finally:
                web._request_memo.reset(post_token)
            assert len(judged) == 4
        finally:
            web._request_memo.reset(memo_token)
            web._request_cache.reset(cache_token)


def test_a_reading_is_judged_afresh_without_a_request_cache(tmp_path: Path, monkeypatch):
    settings, owner_id, _ = build(tmp_path)
    judged: list[str] = []
    original = web._judge_reading

    def counting(*args, **kwargs):
        judged.append(str(args[1]))
        return original(*args, **kwargs)

    def no_memo(*args, **kwargs):
        raise AssertionError("the memo was consulted")

    with connect(settings) as connection:
        probe = web._request_cache.set({})
        try:
            row = next(
                found for found in web._deduped_observation_rows(connection, owner_id)
                if found["value_numeric"] is not None
            )
        finally:
            web._request_cache.reset(probe)

        monkeypatch.setattr(web, "_judge_reading", counting)
        monkeypatch.setattr(web, "_memoised", no_memo)
        # `_matrix_cards` switches the request cache off; a GET still has its memo dict.
        cache_token = web._request_cache.set(None)
        memo_token = web._request_memo.set({})
        try:
            concept_id = row["concept_id"]
            web._reading_verdict(connection, concept_id, row, 34, "male")
            web._reading_verdict(connection, concept_id, row, 34, "male")
            assert len(judged) == 2
        finally:
            web._request_memo.reset(memo_token)
            web._request_cache.reset(cache_token)


def test_pages_are_compressed(tmp_path: Path):
    _, _, client = build(tmp_path)
    response = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert "</html>" in response.text
