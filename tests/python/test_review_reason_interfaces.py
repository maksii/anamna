"""Review-task reasons written by different modules render through one helper."""

import json

from anamna.ingest.pipeline import review_reason_text


def task(reason, key=None, params=None):
    return {"reason": reason, "reason_key": key,
            "reason_params_json": json.dumps(params, ensure_ascii=False) if params is not None else None}


def test_flat_params_with_a_key_render_from_the_catalogue():
    # labsync's missing-rows task keeps flat params (it looks up `order`/`names`).
    row = task("The Synevo record of order 1 has 2 result(s) …", "labsync.review_missing",
               {"count": 2, "lab": "Synevo", "order": "94621560", "names": "Лейкоцити; Слиз"})
    uk = review_reason_text(row, "uk")
    en = review_reason_text(row, "en")
    assert "94621560" in uk and "94621560" in en
    assert "(s)" not in en and uk != en


def test_parts_payload_still_renders_and_counts_pluralise():
    row = task("Check 3 vaccination(s) …", None,
               {"parts": [{"key": "review.vaccinations_n", "params": {"count": 3}}]})
    assert "3" in review_reason_text(row, "uk") and "(s)" not in review_reason_text(row, "en")


def test_a_row_without_params_falls_back_to_its_sentence():
    assert review_reason_text(task("Something old."), "en") == "Something old."
