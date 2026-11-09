"""The document pages show that they are waiting, in both locales."""

from pathlib import Path

from anamna.locales.messages import MESSAGES

WEB = Path(__file__).resolve().parents[2] / "src" / "anamna" / "web"


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_new_keys_exist_in_both_locales():
    for key in ("upload.progress_batch", "upload.saving", "upload.bar_label", "doc.rows_error", "doc.rows_loading"):
        assert MESSAGES[key]["en"].strip() and MESSAGES[key]["uk"].strip(), key


def test_detail_page_tracks_every_in_place_call():
    page = read("templates/document_detail.html")
    assert page.count("anamnaBusy.track(") == 4  # rows, value change, re-read, AI review
    assert "data-rows-error" in page and "data-rows-loading" in page


def test_search_tracks_and_does_not_bypass_the_busy_layer():
    page = read("templates/documents.html")
    assert "anamnaBusy.track(" in page and "anamnaBusy?.navigating(" in page


def test_upload_reports_bytes_and_failure():
    js, page = read("static/uploads.js"), read("templates/upload.html")
    assert "upload.onprogress" in js and "anamnaBusy?.navigating(" in js
    assert 'id="an-upload-bar"' in page and 'id="an-upload-js-error"' in page and 'role="alert"' in page
    assert "data-progress-batch" in page and "data-saving" in page
