"""AI assist — free-model hints that must never change how the app behaves
without them.

The contract under test: configuration lives in ``app_settings`` and decides
everything; every outbound call is budgeted below the free-tier caps and
recorded whether it worked or not; hint rounds are retained per document and locale;
and with AI off the pages render exactly as they always did.  The provider is
stubbed at the registry seam — the same place a second real provider would
plug in — so the tests also prove the abstraction actually abstracts.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from anamna import ai

_REAL_FETCH_MODELS = ai._fetch_models  # captured before the autouse stub
from anamna.db import connect, migrate, utc_now

from test_web_panels import build, settings_for
from test_web_issue_reports import csrf_for


@pytest.fixture(autouse=True)
def _no_live_model_lists(monkeypatch):
    """The admin page asks a provider for its model list whenever a key is
    stored; no test may let that leave the machine."""
    monkeypatch.setattr(ai, "_fetch_models", lambda provider, key: [])
    monkeypatch.setattr(ai, "_MODEL_CACHE", {})


HINTS_REPLY = json.dumps(
    {
        "summary": "A laboratory panel of lipids and blood counts.",
        "summary_evidence": [],
        "suggested_title": "Lipid panel — Test Lab, 13 Feb 2025",
        "suggested_metadata": {
            "clinical_type": "laboratory", "vendor": "Test Lab",
            "report_date": "2025-02-13", "page": None, "quote": "",
        },
    },
    ensure_ascii=False,
)


def stub_provider(reply: str = HINTS_REPLY, calls: list | None = None):
    def provider(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        if calls is not None:
            calls.append({
                "api_key": api_key,
                "model": model,
                "messages": messages,
                "response_format": response_format,
            })
        return ai.AIResult(content=reply, model=model, prompt_tokens=100, completion_tokens=50)

    return provider


def configure(settings, key: str = "sk-or-test") -> None:
    ai.save_ai_settings(settings, {"ai_api_key": key})


# --- module: configuration ---------------------------------------------------


def test_defaults_are_enabled_but_inactive_without_a_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = settings_for(tmp_path)
    migrate(settings)
    config = ai.ai_settings(settings)
    assert config["enabled"] == "1"
    assert config["model"] == ai.DEFAULT_MODEL
    assert config["provider"] == "openrouter"
    assert not ai.ai_active(settings)
    configure(settings)
    assert ai.ai_active(settings)
    ai.save_ai_settings(settings, {"ai_enabled": "0"})
    assert not ai.ai_active(settings)


def test_environment_key_is_a_fallback_not_an_override(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-from-env")
    assert ai.ai_settings(settings)["api_key"] == "sk-from-env"
    configure(settings, "sk-from-db")
    assert ai.ai_settings(settings)["api_key"] == "sk-from-db"


def test_lowercase_openrouter_environment_key_is_supported(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("openrouter", "sk-from-lowercase-env")
    settings = settings_for(tmp_path)
    migrate(settings)
    assert ai.ai_settings(settings)["api_key"] == "sk-from-lowercase-env"


# --- module: budget and accounting -------------------------------------------


def test_complete_records_success_and_failure(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    configure(settings)
    monkeypatch.setitem(ai.PROVIDERS, "openrouter", stub_provider("hello"))
    result = ai.complete(settings, "unit_test", [{"role": "user", "content": "hi"}])
    assert result.content == "hello"

    def failing(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        raise ai.AIUnavailable("provider_error", "HTTP 429: rate limited")

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", failing)
    with pytest.raises(ai.AIUnavailable) as failure:
        ai.complete(settings, "unit_test", [{"role": "user", "content": "hi"}])
    assert failure.value.reason == "provider_error"

    with connect(settings) as connection:
        rows = connection.execute("SELECT ok, prompt_tokens, error FROM ai_usage ORDER BY id").fetchall()
    assert [row["ok"] for row in rows] == [1, 0]
    assert rows[0]["prompt_tokens"] == 100
    assert "429" in rows[1]["error"]


def test_the_budget_slot_is_claimed_before_the_call_not_after(tmp_path: Path, monkeypatch):
    """A request in flight has to be visible to the next one.

    Recording on completion measured finishes, not starts: with a 90 s timeout
    and a 40-thread pool, every reader pressing Generate in the same minute
    would read the same empty window and all forty requests would leave the
    machine, against a documented cap of 20/min.
    """
    settings = settings_for(tmp_path)
    migrate(settings)
    configure(settings)
    seen: list[int] = []

    def provider(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        # What a concurrent request would see while this one is still waiting.
        with connect(settings) as connection:
            seen.append(connection.execute("SELECT COUNT(*) FROM ai_usage").fetchone()[0])
        return ai.AIResult(content="hello", model=model, prompt_tokens=1, completion_tokens=1)

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", provider)
    ai.complete(settings, "unit_test", [{"role": "user", "content": "hi"}])
    assert seen == [1], "the in-flight request was invisible to the budget"

    with connect(settings) as connection:
        (row,) = connection.execute("SELECT ok, error FROM ai_usage").fetchall()
    assert row["ok"] == 1 and row["error"] is None  # settled, not left as the reservation


def test_a_provider_that_breaks_in_any_other_way_still_degrades(tmp_path: Path, monkeypatch):
    """A congested free pool answers 200 with an HTML interstitial or a
    truncated body often enough that JSONDecodeError is a normal Tuesday.

    Every caller treats AIUnavailable as "no hint today"; anything else
    escaping turns that into a 500 on a page that would have rendered fine
    without the hint, and the attempt never reaches the admin page.
    """
    settings = settings_for(tmp_path)
    migrate(settings)
    configure(settings)

    def broken(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        raise json.JSONDecodeError("Expecting value", "<html>502 Bad Gateway</html>", 0)

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", broken)
    with pytest.raises(ai.AIUnavailable) as failure:
        ai.complete(settings, "unit_test", [{"role": "user", "content": "hi"}])
    assert failure.value.reason == "provider_error"

    # The failure is recorded, not swallowed — otherwise the admin page shows
    # nothing and the budget undercounts a request that really was spent.
    with connect(settings) as connection:
        (row,) = connection.execute("SELECT ok, error FROM ai_usage").fetchall()
    assert row["ok"] == 0
    assert "JSONDecodeError" in row["error"]


def test_truncated_generation_is_failure_with_usage_preserved(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    configure(settings)

    def truncated(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        return ai.AIResult(
            content='{"summary":"cut off', model="routed/free-model",
            prompt_tokens=73, completion_tokens=29, finish_reason="length",
        )

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", truncated)
    with pytest.raises(ai.AIUnavailable, match="finish_reason=length"):
        ai.complete(settings, "unit_test", [{"role": "user", "content": "hi"}])
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT ok, model, prompt_tokens, completion_tokens, error FROM ai_usage"
        ).fetchone()
    assert dict(row) == {
        "ok": 0,
        "model": "routed/free-model",
        "prompt_tokens": 73,
        "completion_tokens": 29,
        "error": "generation stopped with finish_reason=length (output limit 32000 tokens)",
    }


def test_hints_never_touch_the_record(tmp_path: Path, monkeypatch):
    """The headline rule: a model's output is advisory text a person reads.

    Nothing it says may mark a value verified, change a value, or resolve a
    review task — extraction stays provisional until a person says otherwise.
    """
    settings, user_id, client = build(tmp_path)
    configure(settings)
    monkeypatch.setitem(ai.PROVIDERS, "openrouter", stub_provider())

    def snapshot():
        with connect(settings) as connection:
            return (
                [dict(row) for row in connection.execute(
                    """SELECT id, title, title_set_by, clinical_type, vendor_id, report_date,
                              classified_by, classification_confidence
                         FROM documents ORDER BY id"""
                )],
                [dict(row) for row in connection.execute(
                    "SELECT id, value_numeric, value_text, verification_status FROM observations ORDER BY id"
                )],
                [dict(row) for row in connection.execute(
                    "SELECT id, title, clinical_type, vendor_id, report_date, status FROM reports ORDER BY id"
                )],
                [dict(row) for row in connection.execute(
                    """SELECT id, occurrence_date, vaccine_code, product_name, manufacturer,
                              dose_number, lot_number, verification_status
                         FROM immunizations ORDER BY id"""
                )],
                [dict(row) for row in connection.execute(
                    "SELECT id, state FROM review_tasks ORDER BY id"
                )],
            )

    before = snapshot()
    response = client.post(
        "/documents/doc-1/ai-hints",
        data={"csrf_token": csrf_for(settings, user_id)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ai_document_hints").fetchone()[0] == 1
    assert snapshot() == before


def test_daily_budget_refuses_before_calling_the_provider(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    configure(settings)
    with connect(settings) as connection:
        connection.executemany(
            "INSERT INTO ai_usage(created_at, feature, provider, model, ok) VALUES (?, 'x', 'openrouter', 'm', 1)",
            [(utc_now(),)] * ai.DAILY_BUDGET,
        )
    calls: list = []
    monkeypatch.setitem(ai.PROVIDERS, "openrouter", stub_provider(calls=calls))
    with pytest.raises(ai.AIUnavailable) as failure:
        ai.complete(settings, "unit_test", [{"role": "user", "content": "hi"}])
    assert failure.value.reason == "budget"
    assert calls == []  # refused locally, no request left the machine


def test_minute_budget_spaces_out_bursts(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    configure(settings)
    with connect(settings) as connection:
        connection.executemany(
            "INSERT INTO ai_usage(created_at, feature, provider, model, ok) VALUES (?, 'x', 'openrouter', 'm', 1)",
            [(utc_now(),)] * ai.MINUTE_BUDGET,
        )
    monkeypatch.setitem(ai.PROVIDERS, "openrouter", stub_provider())
    with pytest.raises(ai.AIUnavailable) as failure:
        ai.complete(settings, "unit_test", [{"role": "user", "content": "hi"}])
    assert failure.value.reason == "budget"


def test_disabled_never_reaches_the_provider(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = settings_for(tmp_path)
    migrate(settings)
    calls: list = []
    monkeypatch.setitem(ai.PROVIDERS, "openrouter", stub_provider(calls=calls))
    with pytest.raises(ai.AIUnavailable) as failure:
        ai.complete(settings, "unit_test", [{"role": "user", "content": "hi"}])
    assert failure.value.reason == "disabled"
    assert calls == []


def test_document_hints_attaches_page_images_for_textless_documents(tmp_path: Path, monkeypatch):
    """A fully scanned page carries no text the parser can read; the request
    must carry the page image instead, as a data URL the provider format
    understands."""
    settings = settings_for(tmp_path)
    migrate(settings)
    configure(settings)
    calls: list = []
    monkeypatch.setitem(ai.PROVIDERS, "openrouter", stub_provider(calls=calls))
    ai.document_hints(
        settings,
        document={"title": "scan", "original_filename": "scan.pdf", "clinical_type": "laboratory"},
        pages=[{"page_number": 1, "native_text": "", "ocr_text": ""}],
        observations=[],
        images=[b"\x89PNG-fake-bytes"],
        locale="en",
    )
    user_content = calls[0]["messages"][1]["content"]
    assert isinstance(user_content, list)
    image_parts = [part for part in user_content if part.get("type") == "image_url"]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_document_review_runs_focused_checks_concurrently_and_validates_ids(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    configure(settings)
    barrier = threading.Barrier(3, timeout=3)
    tasks: list[str] = []

    def provider(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        payload = json.loads(messages[1]["content"])
        task = payload["task"]
        tasks.append(task)
        barrier.wait()
        if task == "grounded_overview":
            reply = {
                "summary": "The report lists an LDL result.",
                "summary_evidence": [{"page": 1, "quote": "LDL 4.42 mmol/L"}],
                "suggested_title": "Laboratory report — 13 Feb 2025",
                "suggested_metadata": {
                    "clinical_type": "laboratory", "vendor": "Test Lab",
                    "report_date": "2025-02-13", "page": 1, "quote": "Test Lab",
                },
            }
        elif task == "find_missing_measurements":
            reply = {"missed_values": [{
                "name": "ESR", "value": "12", "unit": "mm/h", "reference": "2-15",
                "observed_at": "2025-02-13", "page": 1, "evidence": "ESR 12 mm/h (2-15)",
            }]}
        else:
            reply = {
                "suspicious": [
                    {"observation_id": "obs-ldl", "issue_type": "source_mismatch",
                     "reason": "Unit needs review", "evidence": "LDL 4.42 mmol/L",
                     "suggested_name": "", "suggested_value": "", "suggested_unit": "mmol/L",
                     "suggested_reference": ""},
                    {"observation_id": "invented", "issue_type": "source_mismatch",
                     "reason": "Must be discarded", "evidence": "LDL 4.42 mmol/L",
                     "suggested_name": "", "suggested_value": "", "suggested_unit": "",
                     "suggested_reference": ""},
                ],
                "immunization_issues": [], "missed_immunizations": [],
            }
        return ai.AIResult(content=json.dumps(reply), model="routed/free", prompt_tokens=10, completion_tokens=10)

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", provider)
    result = ai.document_hints(
        settings,
        document={"title": "report.pdf", "clinical_type": "laboratory", "vendor": "Test Lab"},
        pages=[{"page_number": 1, "native_text": "Test Lab\nLDL 4.42 mmol/L\nESR 12 mm/h (2-15)", "ocr_text": ""}],
        observations=[{
            "id": "obs-ldl", "raw_name": "LDL", "value": "4.42", "unit": "mmol/L",
            "vendor_reference_text": "0-3", "page_number": 1,
        }],
        immunizations=[{
            "id": "vax-1", "occurrence_date": "2025-02-13", "vaccine_code": "DTaP",
            "product_name": "", "manufacturer": "", "dose_number": 1,
            "doses_in_series": 3, "lot_number": "ABC", "page_number": 1,
        }],
        locale="en",
    )
    assert set(tasks) == {"grounded_overview", "find_missing_measurements", "audit_structured_extraction"}
    assert result["missed_values"][0]["reference"] == "2-15"
    assert result["missed_values"][0]["evidence"] == "ESR 12 mm/h (2-15)"
    assert [item["observation_id"] for item in result["suspicious"]] == ["obs-ldl"]
    assert set(result["models"]) == {"overview", "measurements", "audit"}


def test_duplicate_document_review_is_collapsed_while_first_is_running(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    configure(settings)
    entered = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def provider(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return ai.AIResult(content=HINTS_REPLY, model=model, prompt_tokens=1, completion_tokens=1)

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", provider)
    kwargs = {
        "document": {"id": "same-document", "clinical_type": "pathology"},
        "pages": [], "observations": [], "locale": "en",
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ai.document_hints, settings, **kwargs)
        assert entered.wait(2)
        with pytest.raises(ai.AIUnavailable) as duplicate:
            ai.document_hints(settings, **kwargs)
        assert duplicate.value.reason == "in_progress"
        release.set()
        assert first.result()["summary"]
    assert len(calls) == 1


def test_microbiology_never_treats_disk_potencies_as_missing_health_metrics(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    configure(settings)
    tasks: list[str] = []

    def provider(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        task = json.loads(messages[1]["content"])["task"]
        tasks.append(task)
        reply = json.loads(HINTS_REPLY) if task == "grounded_overview" else {
            "suspicious": [
                {
                    "observation_id": "organism", "issue_type": "source_mismatch",
                    "reason": "Formatting differs", "evidence": "Staphylococcus aureus 1.0 x 10^2 КУО/г",
                    "suggested_name": "Staphylococcus aureus", "suggested_value": "1.0 x 10^2",
                    "suggested_unit": "КУО/г", "suggested_reference": "",
                },
                {
                    "observation_id": "antibiotic", "issue_type": "not_measurement",
                    "reason": "Susceptibility row", "evidence": "Амікацин 30 мкг Чутливий",
                    "suggested_name": "Амікацин", "suggested_value": "Чутливий",
                    "suggested_unit": "мкг", "suggested_reference": "",
                },
            ],
            "immunization_issues": [], "missed_immunizations": [],
        }
        return ai.AIResult(content=json.dumps(reply), model=model, prompt_tokens=1, completion_tokens=1)

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", provider)
    result = ai.document_hints(
        settings,
        document={"id": "culture", "clinical_type": "microbiology"},
        pages=[{
            "page_number": 1,
            "native_text": "Staphylococcus aureus 1.0 x 10^2 КУО/г\nАмікацин 30 мкг Чутливий",
            "ocr_text": "",
        }],
        observations=[
            {"id": "organism", "raw_name": "Staphylococcus aureus", "value": "100.0",
             "unit": "КУО/г", "page_number": 1},
            {"id": "antibiotic", "raw_name": "Амікацин", "value": "Чутливий",
             "unit": "", "page_number": 1},
        ],
        locale="uk",
    )
    assert set(tasks) == {"grounded_overview", "audit_structured_extraction"}
    assert result["missed_values"] == []
    assert [item["observation_id"] for item in result["suspicious"]] == ["antibiotic"]
    assert result["suspicious"][0]["suggested_value"] == ""


def test_openrouter_request_carries_free_fallbacks():
    request = ai._openrouter_request("google/gemma-4-31b-it:free", [], 100)
    assert request["models"][0] == "google/gemma-4-31b-it:free"
    assert set(ai.FALLBACK_MODELS) <= set(request["models"])
    # A paid model the admin chose deliberately is never silently substituted.
    assert "models" not in ai._openrouter_request("anthropic/claude-sonnet-5", [], 100)


def test_openrouter_free_request_requires_and_heals_structured_output():
    request = ai._openrouter_request(
        "openrouter/free", [], 3000, ai.DOCUMENT_HINTS_RESPONSE_FORMAT
    )
    assert request["model"] == "openrouter/free"
    assert "models" not in request
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["provider"] == {"require_parameters": True}
    assert request["plugins"] == [{"id": "response-healing"}]


# --- module: reply parsing ---------------------------------------------------


def test_parse_json_reply_tolerates_decoration():
    assert ai.parse_json_reply('{"a": 1}') == {"a": 1}
    assert ai.parse_json_reply('```json\n{"a": 1}\n```') == {"a": 1}
    assert ai.parse_json_reply('Here is the answer:\n{"a": 1}') == {"a": 1}
    assert ai.parse_json_reply('note {not JSON}\n{"a": 1}\ntrailing') == {"a": 1}
    with pytest.raises(ai.AIUnavailable):
        ai.parse_json_reply("no json here")
    with pytest.raises(ai.AIUnavailable):
        ai.parse_json_reply("[1, 2]")


def test_parse_errors_do_not_copy_medical_reply_into_telemetry():
    sensitive = 'User Safety: safe — patient marker 123'
    with pytest.raises(ai.AIUnavailable) as failure:
        ai.parse_json_reply(sensitive)
    assert "patient marker" not in failure.value.detail
    assert failure.value.detail == f"no JSON object in reply ({len(sensitive)} chars)"


def test_document_text_redacts_labelled_patient_identifiers():
    text = (
        "ПІБ пацієнта: Example Person Стать: Чоловіча\n"
        "Дата народження: 14.03.1990 Вік: 36 років\n"
        "№ медичної картки пацієнта 12345\n"
        "Висновок: stated clinical finding"
    )
    redacted = ai.redact_document_text(text)
    assert "Example Person" not in redacted
    assert "14.03.1990" not in redacted
    assert "12345" not in redacted
    assert "Висновок: stated clinical finding" in redacted


def test_imaging_prompt_uses_explicit_conclusion_not_detailed_body():
    text = (
        "[page 1]\nClinic\nДата візиту: 08.08.2026\nУЗД органів черевної порожнини\n"
        "Жовчевий міхур: detailed body that must not be summarized\n"
        "[page 2]\nВисновок: stated liver and pancreas findings\n"
        "РЕКОМЕНДОВАНО:\nConsult specialist\nЛікар: Example"
    )
    excerpt = ai.imaging_review_excerpt(text, "clinical_report")
    assert excerpt is not None
    assert "УЗД органів черевної порожнини" in excerpt
    assert "detailed body" not in excerpt
    assert "Висновок: stated liver and pancreas findings" in excerpt
    assert "Consult specialist" in excerpt
    assert "Лікар: Example" not in excerpt


def test_imaging_summary_drops_model_appended_advice():
    summary = (
        "The report states finding one. The report states finding two. "
        "The source recommends consultation. This will improve treatment."
    )
    assert ai._limit_sentences(summary, 3) == (
        "The report states finding one. The report states finding two. "
        "The source recommends consultation."
    )


def test_lab_summary_drops_model_authored_reference_interpretation():
    summary = (
        "The report lists vitamin D 31.7 ng/mL and glucose 5.95 mmol/L. "
        "All values are within the reference range except cholesterol, which indicates high risk."
    )
    assert ai._safe_lab_summary(summary, "en", 83) == (
        "The report lists vitamin D 31.7 ng/mL and glucose 5.95 mmol/L."
    )
    ukrainian = (
        "Документ містить результати лабораторних досліджень. "
        "Вітамін D виходить за межі норми, а глюкоза в межах норми."
    )
    assert ai._safe_lab_summary(ukrainian, "uk", 83) == (
        "Документ містить результати лабораторних досліджень."
    )


def test_scientific_notation_and_decimal_are_the_same_numeric_value():
    assert ai._numeric_equivalent("100.0", "1.0 x 10^2")
    assert ai._numeric_equivalent("1000000", "1,0 × 10^6")
    assert not ai._numeric_equivalent("100", "1.0 x 10^3")


# --- web: document hints -----------------------------------------------------


def test_document_page_carries_no_ai_panel_when_unconfigured(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    _, _, client = build(tmp_path)
    page = client.get("/documents/doc-1")
    assert page.status_code == 200
    assert "side-panel-ai" not in page.text


def test_generate_caches_renders_and_reuses(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    calls: list = []
    monkeypatch.setitem(ai.PROVIDERS, "openrouter", stub_provider(calls=calls))
    csrf = csrf_for(settings, user_id)

    response = client.post(
        "/documents/doc-1/ai-hints", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("#side-panel-ai")
    assert len(calls) == 1
    # The model was shown the page text and the already-extracted rows.
    sent = json.dumps(calls[0]["messages"], ensure_ascii=False)
    assert "LDL cholesterol" in sent
    assert "untrusted source data" in sent
    assert "evidence-bound review component" in sent
    assert "short exact quote" in sent
    assert "do not interpret medical imagery" in sent
    assert calls[0]["response_format"] == ai.OVERVIEW_RESPONSE_FORMAT

    page = client.get("/documents/doc-1")
    assert "A laboratory panel of lipids and blood counts." in page.text
    assert "Lipid panel — Test Lab, 13 Feb 2025" in page.text
    assert 'name="title" maxlength="240" value="Lipid panel — Test Lab, 13 Feb 2025"' in page.text
    assert 'name="apply_clinical_type" value="1"' in page.text
    assert '<option value="laboratory" selected>' in page.text

    # A second press serves the latest round; explicit regeneration appends a new one.
    client.post("/documents/doc-1/ai-hints", data={"csrf_token": csrf}, follow_redirects=False)
    assert len(calls) == 1
    client.post(
        "/documents/doc-1/ai-hints", data={"csrf_token": csrf, "refresh": "1"}, follow_redirects=False
    )
    assert len(calls) == 2
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM ai_document_hints WHERE document_id='doc-1' AND locale='en'"
        ).fetchone()[0] == 2
    page = client.get("/documents/doc-1").text
    assert "History" in page and "Latest" in page


def test_generate_supports_the_fetch_promise_contract(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    monkeypatch.setitem(ai.PROVIDERS, "openrouter", stub_provider())
    response = client.post(
        "/documents/doc-1/ai-hints",
        data={"csrf_token": csrf_for(settings, user_id)},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "ok": True, "location": "/documents/doc-1#side-panel-ai"
    }
    cached = client.post(
        "/documents/doc-1/ai-hints",
        data={"csrf_token": csrf_for(settings, user_id)},
        headers={"Accept": "application/json"},
    )
    assert cached.json()["cached"] is True
    page = client.get("/documents/doc-1").text
    assert 'id="ai-review-form"' in page
    assert "await fetch(aiForm.action" in page
    assert 'role="status" aria-live="polite"' in page


def test_cached_review_renders_evidence_and_editable_apply_controls(tmp_path: Path):
    settings, _, client = build(tmp_path)
    hints = {
        "summary": "The source lists a laboratory result.",
        "summary_evidence": [{"page": 2, "quote": "ESR 12 mm/h"}],
        "suggested_title": "Laboratory results",
        "suggested_metadata": {
            "clinical_type": "laboratory", "vendor": "Test Lab",
            "report_date": "2025-02-13", "page": 1, "quote": "Test Lab",
        },
        "missed_values": [{
            "name": "ESR", "value": "12", "unit": "mm/h", "reference": "2-15",
            "observed_at": "2025-02-13", "page": 2, "evidence": "ESR 12 mm/h",
        }],
        "suspicious": [{
            "observation_id": "obs-0", "name": "LDL cholesterol", "value": "4.42",
            "unit": "mmol/L", "page": 1, "reason": "Compare this row with the source.",
            "issue_type": "source_mismatch", "evidence": "LDL cholesterol 4.42 mmol/L",
            "suggested_name": "", "suggested_value": "", "suggested_unit": "",
            "suggested_reference": "",
        }],
        "immunization_issues": [], "missed_immunizations": [],
        "models": {"overview": "free/model", "measurements": "free/model", "audit": "free/model"},
        "model": "free/model", "review_sections": ["overview", "measurements", "audit"],
        "section_errors": [],
    }
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO ai_document_hints(document_id, locale, provider, model, content_json, created_at)
               VALUES ('doc-1', 'en', 'openrouter', 'free/model', ?, ?)""",
            (json.dumps(hints), utc_now()),
        )
    page = client.get("/documents/doc-1").text
    assert 'href="#page-2"' in page and "ESR 12 mm/h" in page
    assert 'name="vendor_reference_text" value="2-15"' in page
    assert 'name="observed_at" type="date" value="2025-02-13"' in page
    assert 'name="evidence_text" rows="2">ESR 12 mm/h' in page
    assert 'href="#observation-obs-0"' in page
    assert 'action="/documents/doc-1/ai-metadata"' in page
    assert 'name="apply_clinical_type" value="1"' in page
    assert '<option value="laboratory" selected>' in page


def test_review_round_history_keeps_and_opens_older_answers(tmp_path: Path):
    settings, _, client = build(tmp_path)
    older = {"summary": "First review", "section_errors": []}
    latest = {"summary": "Second review", "section_errors": []}
    with connect(settings) as connection:
        first_id = connection.execute(
            """INSERT INTO ai_document_hints(document_id, locale, provider, model, content_json, created_at)
               VALUES ('doc-1', 'en', 'openrouter', 'model/first', ?, '2026-08-08T09:00:00+00:00')""",
            (json.dumps(older),),
        ).lastrowid
        connection.execute(
            """INSERT INTO ai_document_hints(document_id, locale, provider, model, content_json, created_at)
               VALUES ('doc-1', 'en', 'openrouter', 'model/latest', ?, '2026-08-09T10:00:00+00:00')""",
            (json.dumps(latest),),
        )
        query_plan = " ".join(
            str(row["detail"])
            for row in connection.execute(
                """EXPLAIN QUERY PLAN
                   SELECT id FROM ai_document_hints
                    WHERE document_id='doc-1' AND locale='en'
                    ORDER BY created_at DESC, id DESC LIMIT 1"""
            )
        )
    assert "idx_ai_document_hints_document_locale_created" in query_plan

    page = client.get("/documents/doc-1").text
    assert "Second review" in page
    assert "First review" not in page
    assert "model/first" in page and "model/latest" in page
    assert 'id="ai-history-dialog"' in page

    older_page = client.get(f"/documents/doc-1?hint={first_id}").text
    assert "First review" in older_page
    assert "Previous round" in older_page
    assert 'href="/documents/doc-1#side-panel-ai">Latest</a>' in older_page


def test_ai_document_details_apply_only_selected_fields(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    with connect(settings) as connection:
        before = connection.execute(
            "SELECT clinical_type, vendor_id, report_date FROM documents WHERE id='doc-1'"
        ).fetchone()

    response = client.post(
        "/documents/doc-1/ai-metadata",
        data={
            "csrf_token": csrf,
            "clinical_type": "pathology",
            "vendor": "AI Suggested Clinic",
            "report_date": "2026-08-09",
            "apply_vendor": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with connect(settings) as connection:
        after = connection.execute(
            """SELECT d.clinical_type, d.vendor_id, d.report_date, v.canonical_name vendor
                 FROM documents d LEFT JOIN vendors v ON v.id=d.vendor_id WHERE d.id='doc-1'"""
        ).fetchone()
        audit = connection.execute(
            "SELECT details_json FROM audit_events WHERE action='ai_document_details_applied'"
        ).fetchone()
    assert after["clinical_type"] == before["clinical_type"]
    assert after["report_date"] == before["report_date"]
    assert after["vendor_id"] != before["vendor_id"]
    assert after["vendor"] == "AI Suggested Clinic"
    assert json.loads(audit["details_json"]) == {"vendor": "AI Suggested Clinic"}

    refused = client.post(
        "/documents/doc-1/ai-metadata",
        data={"csrf_token": csrf, "clinical_type": "pathology"},
    )
    assert refused.status_code == 400


def test_hints_are_cached_per_locale(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    monkeypatch.setitem(ai.PROVIDERS, "openrouter", stub_provider())
    csrf = csrf_for(settings, user_id)
    client.post("/documents/doc-1/ai-hints", data={"csrf_token": csrf}, follow_redirects=False)
    client.cookies.set("anamna_lang", "uk")
    client.post("/documents/doc-1/ai-hints", data={"csrf_token": csrf}, follow_redirects=False)
    with connect(settings) as connection:
        locales = {
            row["locale"]
            for row in connection.execute("SELECT locale FROM ai_document_hints WHERE document_id='doc-1'")
        }
    assert locales == {"en", "uk"}


def test_provider_failure_degrades_to_an_explained_error(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)

    def failing(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        raise ai.AIUnavailable("provider_error", "HTTP 500")

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", failing)
    csrf = csrf_for(settings, user_id)
    response = client.post(
        "/documents/doc-1/ai-hints", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "ai_error=provider_error" in response.headers["location"]
    page = client.get("/documents/doc-1?ai_error=provider_error")
    assert "The model did not answer" in page.text
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ai_document_hints").fetchone()[0] == 0


def test_apply_title_marks_it_human_so_rescan_keeps_it(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    response = client.post(
        "/documents/doc-1/ai-title",
        data={"title": "Lipid panel — Test Lab", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with connect(settings) as connection:
        row = connection.execute("SELECT title, title_set_by FROM documents WHERE id='doc-1'").fetchone()
    assert row["title"] == "Lipid panel — Test Lab"
    assert row["title_set_by"] == "human"


# --- web: admin page ---------------------------------------------------------


def admin_form(csrf: str, **overrides) -> dict:
    """A complete /admin/ai submission: every task routed to OpenRouter."""
    data = {"enabled": "1", "csrf_token": csrf}
    for task in ai.TASKS:
        data.update({
            f"task_{task}_enabled": "1",
            f"task_{task}_provider": "openrouter",
            f"task_{task}_model": "",
            f"task_{task}_effort": "",
            f"task_{task}_max_tokens": "",
        })
    data.update(overrides)
    return data


def test_admin_page_shows_state_and_saves_settings(tmp_path: Path, monkeypatch):
    for name in ("OPENROUTER_API_KEY", "openrouter", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)

    page = client.get("/admin/ai")
    assert page.status_code == 200
    assert "No API key" in page.text

    response = client.post(
        "/admin/ai",
        data=admin_form(csrf, key_openrouter="sk-or-abcdef123456",
                        task_default_model="openai/gpt-oss-20b:free"),
        follow_redirects=False,
    )
    assert response.status_code == 303
    config = ai.ai_settings(settings)
    assert config["api_key"] == "sk-or-abcdef123456"
    assert config["model"] == "openai/gpt-oss-20b:free"

    page = client.get("/admin/ai")
    assert "Active" in page.text
    assert "...123456" in page.text  # recognisable, never the whole secret
    assert "sk-or-abcdef123456" not in page.text

    # A blank key field keeps the stored key; the explicit checkbox clears it.
    client.post("/admin/ai", data=admin_form(csrf), follow_redirects=False)
    assert ai.ai_settings(settings)["api_key"] == "sk-or-abcdef123456"
    client.post("/admin/ai", data=admin_form(csrf, clear_key_openrouter="1"), follow_redirects=False)
    assert ai.ai_settings(settings)["api_key"] == ""
    with connect(settings) as connection:
        details = [row[0] for row in connection.execute(
            "SELECT details_json FROM audit_events WHERE action='admin_ai_changed'"
        )]
    assert details and not any("abcdef123456" in item for item in details)


def test_admin_page_reports_usage(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    monkeypatch.setitem(ai.PROVIDERS, "openrouter", stub_provider())
    csrf = csrf_for(settings, user_id)
    client.post("/documents/doc-1/ai-hints", data={"csrf_token": csrf}, follow_redirects=False)
    page = client.get("/admin/ai")
    assert "Document hints" in page.text
    assert "answered" in page.text
    summary = ai.usage_summary(settings)
    assert summary["today"] == 1
    assert summary["month"]["prompt_tokens"] == 100


def test_admin_test_button_round_trips(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    monkeypatch.setitem(ai.PROVIDERS, "openrouter", stub_provider("OK"))
    csrf = csrf_for(settings, user_id)
    response = client.post("/admin/ai/test", data={"csrf_token": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert "done=test" in response.headers["location"]
    assert ai.usage_summary(settings)["by_feature"][0]["feature"] == "admin_test"


def test_admin_page_refuses_non_admins(tmp_path: Path):
    from fastapi.testclient import TestClient

    from anamna.security import create_session, create_user
    from anamna.web.app import create_app

    settings, _, _ = build(tmp_path)
    other_id = create_user(settings, "second@example.test", "Second", "another-long-password")
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, other_id)
    client.cookies.set("anamna_session", token)
    assert client.get("/admin/ai").status_code == 403


# --- providers: request translation ------------------------------------------


IMAGE_MESSAGES = [
    {"role": "system", "content": "You audit documents."},
    {"role": "user", "content": [
        {"type": "text", "text": "{\"task\": \"audit\"}"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ]},
]


def test_anthropic_request_moves_system_converts_images_and_sets_effort():
    request = ai._anthropic_request(
        "claude-opus-5-5", IMAGE_MESSAGES, 16000, ai.AUDIT_RESPONSE_FORMAT, "medium"
    )
    assert request["system"] == "You audit documents."
    assert all(message["role"] != "system" for message in request["messages"])
    blocks = request["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "{\"task\": \"audit\"}"}
    assert blocks[1] == {"type": "image", "source": {
        "type": "base64", "media_type": "image/png", "data": "QUJD",
    }}
    assert request["output_config"]["effort"] == "medium"
    schema = request["output_config"]["format"]
    assert schema["type"] == "json_schema"
    text = json.dumps(schema)
    # Constraints Anthropic's compiler rejects are gone; type lists are anyOf.
    assert "maxLength" not in text and "maxItems" not in text
    assert '"type": ["integer", "null"]' not in text and "anyOf" in text
    # Rejected or meaningless on current models.
    assert "temperature" not in request and "thinking" not in request
    assert request["max_tokens"] == 16000


def test_openai_request_uses_responses_api_shapes():
    request = ai._openai_request("gpt-5-mini", IMAGE_MESSAGES, 4000, ai.AUDIT_RESPONSE_FORMAT, "low")
    assert request["instructions"] == "You audit documents."
    assert request["store"] is False
    assert request["max_output_tokens"] == 4000
    assert request["reasoning"] == {"effort": "low"}
    content = request["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "{\"task\": \"audit\"}"}
    assert content[1] == {"type": "input_image", "image_url": "data:image/png;base64,QUJD", "detail": "auto"}
    text_format = request["text"]["format"]
    assert text_format["type"] == "json_schema" and text_format["strict"] is True
    assert text_format["name"] == "extraction_audit"
    assert "maxLength" not in json.dumps(text_format["schema"])
    # A model default leaves `reasoning` out: non-reasoning models reject it.
    assert "reasoning" not in ai._openai_request("gpt-4.1", [{"role": "user", "content": "hi"}], 100)


class _Obj:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def _fake_anthropic(response, seen: list):
    class Messages:
        def create(self, **kwargs):
            seen.append(kwargs)
            return response

    return lambda api_key, timeout: _Obj(messages=Messages())


def route_everything(settings, provider: str, model: str, effort: str = "", max_tokens: int = 2000):
    for task in ai.TASKS:
        ai.save_task_route(settings, task, {
            "provider": provider, "model": model, "effort": effort,
            "max_tokens": max_tokens, "enabled": True,
        })


def test_anthropic_refusal_and_cutoff_are_failures_with_usage_kept(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    ai.save_ai_settings(settings, {"ai_key_anthropic": "sk-ant-test"})
    route_everything(settings, "anthropic", "claude-opus-5-5", "medium")
    seen: list = []
    usage = _Obj(input_tokens=900, output_tokens=40, cache_creation_input_tokens=0, cache_read_input_tokens=100)
    refusal = _Obj(
        content=[], stop_reason="refusal", stop_details=_Obj(category="bio"),
        usage=usage, model="claude-opus-5-5",
    )
    monkeypatch.setattr(ai, "_anthropic_client", _fake_anthropic(refusal, seen))
    with pytest.raises(ai.AIUnavailable) as failure:
        ai.complete(settings, "admin_test", [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}])
    assert failure.value.reason == "provider_error"
    assert "refusal" in failure.value.detail and "bio" in failure.value.detail
    assert seen[0]["system"] == "s" and seen[0]["output_config"] == {"effort": "medium"}

    cut = _Obj(
        content=[_Obj(type="text", text='{"a":')], stop_reason="max_tokens",
        stop_details=None, usage=usage, model="claude-opus-5-5",
    )
    monkeypatch.setattr(ai, "_anthropic_client", _fake_anthropic(cut, seen))
    with pytest.raises(ai.AIUnavailable) as failure:
        ai.complete(settings, "admin_test", [{"role": "user", "content": "hi"}])
    assert failure.value.reason == "truncated"

    ok = _Obj(
        content=[_Obj(type="thinking", thinking=""), _Obj(type="text", text="OK")],
        stop_reason="end_turn", stop_details=None, usage=usage, model="claude-opus-5-5",
    )
    monkeypatch.setattr(ai, "_anthropic_client", _fake_anthropic(ok, seen))
    assert ai.complete(settings, "admin_test", [{"role": "user", "content": "hi"}]).content == "OK"
    with connect(settings) as connection:
        rows = [dict(row) for row in connection.execute(
            "SELECT provider, ok, prompt_tokens, completion_tokens, error FROM ai_usage ORDER BY id"
        )]
    assert [row["ok"] for row in rows] == [0, 0, 1]
    assert {row["provider"] for row in rows} == {"anthropic"}
    # Cache reads are input tokens too; every row keeps what was billed.
    assert all(row["prompt_tokens"] == 1000 and row["completion_tokens"] == 40 for row in rows)
    assert "finish_reason=length" in rows[1]["error"]


def test_anthropic_sdk_errors_degrade_with_status(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    ai.save_ai_settings(settings, {"ai_key_anthropic": "sk-ant-test"})
    route_everything(settings, "anthropic", "claude-opus-5-5")

    class Failing:
        def create(self, **kwargs):
            error = RuntimeError("bad effort")
            error.status_code = 400
            error.message = "output_config.effort: invalid"
            raise error

    monkeypatch.setattr(ai, "_anthropic_client", lambda api_key, timeout: _Obj(messages=Failing()))
    with pytest.raises(ai.AIUnavailable) as failure:
        ai.complete(settings, "admin_test", [{"role": "user", "content": "hi"}])
    assert failure.value.reason == "provider_error"
    assert failure.value.detail == "HTTP 400: output_config.effort: invalid"


def test_openai_incomplete_reply_is_truncated_and_text_comes_back(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    ai.save_ai_settings(settings, {"ai_key_openai": "sk-openai-test"})
    route_everything(settings, "openai", "gpt-5-mini", "low")
    seen: list = []

    def client_for(response):
        class Responses:
            def create(self, **kwargs):
                seen.append(kwargs)
                return response

        return lambda api_key, timeout: _Obj(responses=Responses())

    usage = _Obj(input_tokens=500, output_tokens=60)
    incomplete = _Obj(
        error=None, status="incomplete", incomplete_details=_Obj(reason="max_output_tokens"),
        output=[], output_text="", usage=usage, model="gpt-5-mini-2026",
    )
    monkeypatch.setattr(ai, "_openai_client", client_for(incomplete))
    with pytest.raises(ai.AIUnavailable) as failure:
        ai.complete(settings, "changes_summary", [{"role": "user", "content": "hi"}])
    assert failure.value.reason == "truncated"
    assert seen[0]["reasoning"] == {"effort": "low"} and seen[0]["max_output_tokens"] == 2000

    refused = _Obj(
        error=None, status="completed", incomplete_details=None,
        output=[_Obj(content=[_Obj(type="refusal", refusal="no")])],
        output_text="", usage=usage, model="gpt-5-mini-2026",
    )
    monkeypatch.setattr(ai, "_openai_client", client_for(refused))
    with pytest.raises(ai.AIUnavailable, match="finish_reason=refusal"):
        ai.complete(settings, "changes_summary", [{"role": "user", "content": "hi"}])

    done = _Obj(
        error=None, status="completed", incomplete_details=None,
        output=[_Obj(content=[_Obj(type="output_text", text="Stable.")])],
        output_text="Stable.", usage=usage, model="gpt-5-mini-2026",
    )
    monkeypatch.setattr(ai, "_openai_client", client_for(done))
    result = ai.complete(settings, "changes_summary", [{"role": "user", "content": "hi"}])
    assert result.content == "Stable." and result.model == "gpt-5-mini-2026"
    assert result.prompt_tokens == 500 and result.completion_tokens == 60


# --- routing, keys, legacy settings, budgets ---------------------------------


def test_features_route_to_their_task(tmp_path: Path, monkeypatch):
    for name in ("OPENROUTER_API_KEY", "openrouter"):
        monkeypatch.delenv(name, raising=False)
    settings = settings_for(tmp_path)
    migrate(settings)
    assert ai.task_for("document_hints_audit") == "document_review"
    assert ai.task_for("changes_summary") == "summary"
    assert ai.task_for("admin_test") == "default"
    ai.save_ai_settings(settings, {
        "ai_api_key": "sk-or", "ai_key_anthropic": "sk-ant", "ai_key_openai": "sk-oa",
    })
    ai.save_task_route(settings, "document_review", {
        "provider": "anthropic", "model": "claude-opus-5-5", "effort": "medium",
        "max_tokens": 16000, "enabled": True,
    })
    ai.save_task_route(settings, "summary", {
        "provider": "openai", "model": "gpt-5-nano", "effort": "minimal",
        "max_tokens": 1500, "enabled": True,
    })
    calls: dict[str, dict] = {}

    def recorder(name):
        def provider(api_key, model, messages, max_tokens, timeout, response_format=None, *, effort=""):
            calls[name] = {"key": api_key, "model": model, "max_tokens": max_tokens, "effort": effort}
            return ai.AIResult(content="ok", model=model, prompt_tokens=1, completion_tokens=1)
        return provider

    for name in ai.PROVIDER_NAMES:
        monkeypatch.setitem(ai.PROVIDERS, name, recorder(name))
    hi = [{"role": "user", "content": "hi"}]
    ai.complete(settings, "document_hints_overview", hi, max_tokens=3000)
    ai.complete(settings, "changes_summary", hi, max_tokens=900)
    ai.complete(settings, "admin_test", hi)
    assert calls["anthropic"] == {"key": "sk-ant", "model": "claude-opus-5-5", "max_tokens": 16000, "effort": "medium"}
    # The admin's output limit wins over the caller's guess.
    assert calls["openai"] == {"key": "sk-oa", "model": "gpt-5-nano", "max_tokens": 1500, "effort": "minimal"}
    assert calls["openrouter"]["model"] == ai.DEFAULT_MODEL and calls["openrouter"]["effort"] == ""
    assert ai.provider_host(settings) == "openrouter.ai"
    assert ai.provider_host(settings, "document_review") == "api.anthropic.com"
    assert ai.provider_host(settings, task="summary") == "api.openai.com"
    with connect(settings) as connection:
        assert dict(connection.execute("SELECT feature, provider FROM ai_usage").fetchall()) == {
            "document_hints_overview": "anthropic", "changes_summary": "openai", "admin_test": "openrouter",
        }

    # A task switched off is off, while the others keep answering.
    ai.save_task_route(settings, "summary", {"provider": "openai", "model": "gpt-5-nano", "enabled": False})
    assert not ai.ai_active(settings, task="summary")
    assert ai.ai_active(settings, task="document_review") and ai.ai_active(settings)
    with pytest.raises(ai.AIUnavailable) as failure:
        ai.complete(settings, "changes_summary", hi)
    assert failure.value.reason == "disabled"


def test_provider_keys_fall_back_to_environment_until_saved(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-env")
    config = ai.ai_settings(settings)
    assert config["keys"]["anthropic"] == "sk-ant-env"
    assert config["key_sources"]["openai"] == "environment"
    ai.save_ai_settings(settings, {"ai_key_anthropic": "sk-ant-db"})
    assert ai.ai_settings(settings)["keys"]["anthropic"] == "sk-ant-db"
    # Forgetting a saved key means no key, not "the environment's again".
    ai.save_ai_settings(settings, {"ai_key_anthropic": ""})
    config = ai.ai_settings(settings)
    assert config["keys"]["anthropic"] == "" and config["key_sources"]["anthropic"] == ""
    assert config["keys"]["openai"] == "sk-oa-env"


def test_legacy_single_provider_settings_route_every_task(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    ai.save_ai_settings(settings, {
        "ai_api_key": "sk-or-legacy", "ai_provider": "openrouter", "ai_model": "google/gemma:free",
    })
    config = ai.ai_settings(settings)
    for task in ai.TASKS:
        route = config["tasks"][task]
        assert (route["provider"], route["model"], route["enabled"]) == ("openrouter", "google/gemma:free", True)
        assert route["max_tokens"] == ai.TASK_DEFAULT_MAX_TOKENS[task]
    assert ai.TASK_DEFAULT_MAX_TOKENS["document_review"] >= 16000
    assert ai.ai_active(settings, "document_review")
    # Moving one task to another provider does not drag the legacy model along.
    ai.save_task_route(settings, "summary", {"provider": "openai", "model": "", "enabled": True})
    assert ai.ai_settings(settings)["tasks"]["summary"]["model"] == ai.DEFAULT_MODELS["openai"]
    assert ai.ai_settings(settings)["tasks"]["document_review"]["model"] == "google/gemma:free"


def test_paid_provider_daily_cap_is_per_provider(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    ai.save_ai_settings(settings, {
        "ai_api_key": "sk-or", "ai_key_anthropic": "sk-ant", "ai_daily_cap_anthropic": "3",
    })
    ai.save_task_route(settings, "document_review", {"provider": "anthropic", "model": "claude-haiku-5-5", "enabled": True})
    with connect(settings) as connection:
        # A full OpenRouter minute must not block Anthropic, nor the reverse.
        connection.executemany(
            "INSERT INTO ai_usage(created_at, feature, provider, model, ok) VALUES (?, 'x', 'openrouter', 'm', 1)",
            [(utc_now(),)] * ai.MINUTE_BUDGET,
        )
        connection.executemany(
            "INSERT INTO ai_usage(created_at, feature, provider, model, ok) VALUES (?, 'x', 'anthropic', 'm', 1)",
            [(utc_now(),)] * 2,
        )
    calls: list = []
    monkeypatch.setitem(ai.PROVIDERS, "anthropic", stub_provider("ok", calls=calls))
    ai.complete(settings, "document_hints_overview", [{"role": "user", "content": "hi"}])
    with pytest.raises(ai.AIUnavailable) as failure:
        ai.complete(settings, "document_hints_overview", [{"role": "user", "content": "hi"}])
    assert failure.value.reason == "budget"
    assert len(calls) == 1
    summary = ai.usage_summary(settings)
    anthropic = next(item for item in summary["budgets"] if item["provider"] == "anthropic")
    assert anthropic == {"provider": "anthropic", "today": 3, "cap": 3}
    by_task = {item["name"]: item["requests"] for item in summary["by_task"]}
    assert by_task["document_review"] == 1


def test_live_model_list_is_cached_and_failure_tolerant(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert ai.list_models(settings, "openai") == []  # no key, no outbound call
    ai.save_ai_settings(settings, {"ai_key_openai": "sk-oa-list1"})
    fetched: list = []
    monkeypatch.setattr(ai, "_fetch_models", lambda provider, key: fetched.append(provider) or ["gpt-x"])
    monkeypatch.setattr(ai, "_MODEL_CACHE", {})
    assert ai.list_models(settings, "openai") == ["gpt-x"]
    assert ai.list_models(settings, "openai") == ["gpt-x"]
    assert fetched == ["openai"]

    def broken(provider, key):
        raise RuntimeError("network down")

    monkeypatch.setattr(ai, "_fetch_models", broken)
    monkeypatch.setattr(ai, "_MODEL_CACHE", {})
    assert ai.list_models(settings, "openai") == []


# --- web: admin routing form -------------------------------------------------


def test_admin_form_saves_routes_and_validates(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    monkeypatch.setattr(ai, "_fetch_models", lambda provider, key: ["claude-opus-5-5", "claude-haiku-5-5"])
    monkeypatch.setattr(ai, "_MODEL_CACHE", {})
    response = client.post("/admin/ai", data=admin_form(
        csrf,
        key_anthropic="sk-ant-secret-aaaaaa", key_openai="sk-oa-secret-bbbbbb", cap_openai="50",
        task_document_review_provider="anthropic", task_document_review_model="claude-opus-5-5",
        task_document_review_effort="medium", task_document_review_max_tokens="20000",
        task_summary_provider="openai", task_summary_model="gpt-5-nano",
        task_summary_effort="max",  # OpenAI offers no "max": dropped, not saved
        task_default_enabled="",
    ), follow_redirects=False)
    assert response.status_code == 303 and "done=saved" in response.headers["location"]
    config = ai.ai_settings(settings)
    review = config["tasks"]["document_review"]
    assert (review["provider"], review["model"], review["effort"], review["max_tokens"]) == (
        "anthropic", "claude-opus-5-5", "medium", 20000,
    )
    assert config["tasks"]["summary"]["effort"] == ""
    assert config["tasks"]["default"]["enabled"] is False
    assert config["caps"]["openai"] == 50

    page = client.get("/admin/ai").text
    assert "sk-ant-secret" not in page and "...aaaaaa" in page and "...bbbbbb" in page
    # The page never waits for a provider: an unfetched list is asked for after it loads.
    assert 'data-ai-models-fetch="anthropic"' in page
    listed = client.get("/admin/ai/models?provider=anthropic").json()
    assert listed == {"provider": "anthropic", "models": ["claude-opus-5-5", "claude-haiku-5-5"]}
    # Once fetched, the next render carries it inline.
    page = client.get("/admin/ai").text
    assert '<option value="claude-haiku-5-5">' in page and 'data-ai-models-fetch="anthropic"' not in page
    assert "api.anthropic.com" in page

    for bad, key in (
        ({"task_summary_provider": "gemini"}, "aiassist.error_provider"),
        ({"task_summary_max_tokens": "10"}, "aiassist.error_max_tokens"),
        ({"cap_anthropic": "-1"}, "aiassist.error_cap"),
    ):
        refused = client.post("/admin/ai", data=admin_form(csrf, **bad), follow_redirects=False)
        assert refused.headers["location"].endswith(f"error={key}")
    assert ai.ai_settings(settings)["tasks"]["document_review"]["provider"] == "anthropic"

    forged = client.post("/admin/ai", data=admin_form("not-the-token"), follow_redirects=False)
    assert forged.status_code in (400, 403)
    assert ai.ai_settings(settings)["tasks"]["document_review"]["provider"] == "anthropic"


def test_admin_test_runs_the_chosen_task_and_names_the_model(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    ai.save_ai_settings(settings, {"ai_api_key": "sk-or", "ai_key_anthropic": "sk-ant"})
    ai.save_task_route(settings, "document_review", {"provider": "anthropic", "model": "claude-opus-5-5", "enabled": True})

    def answer(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        return ai.AIResult(content="OK", model=model + "-answered", prompt_tokens=1, completion_tokens=1)

    monkeypatch.setitem(ai.PROVIDERS, "anthropic", answer)
    csrf = csrf_for(settings, user_id)
    response = client.post("/admin/ai/test", data={"csrf_token": csrf, "task": "document_review"}, follow_redirects=False)
    location = response.headers["location"]
    assert "done=test" in location and "task=document_review" in location
    page = client.get(location.split("#")[0]).text
    assert "Document review: answered by claude-opus-5-5-answered." in page
    with connect(settings) as connection:
        assert tuple(connection.execute("SELECT feature, provider FROM ai_usage").fetchone()) == (
            "admin_test_document_review", "anthropic",
        )
    refused = client.post("/admin/ai/test", data={"csrf_token": csrf, "task": "nope"}, follow_redirects=False)
    assert "error=aiassist.error_test_task" in refused.headers["location"]


# --- web: truncated specialists and one-click corrections --------------------


def add_page(settings, text: str) -> None:
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO document_pages(document_id, page_number, native_text, extraction_method, review_status)
               VALUES ('doc-1', 1, ?, 'native', 'not_reviewed')""",
            (text,),
        )


def test_a_cut_off_specialist_keeps_the_others_and_says_why(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure(settings)
    add_page(settings, "LDL cholesterol 4.42 mmol/L\nESR 12 mm/h")

    def provider(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        task = json.loads(messages[1]["content"])["task"]
        if task == "grounded_overview":
            return ai.AIResult(content=HINTS_REPLY, model="free/a", prompt_tokens=5, completion_tokens=5)
        return ai.AIResult(content='{"missed', model="free/b", prompt_tokens=9000,
                           completion_tokens=max_tokens, finish_reason="length")

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", provider)
    csrf = csrf_for(settings, user_id)
    response = client.post("/documents/doc-1/ai-hints", data={"csrf_token": csrf},
                           headers={"Accept": "application/json"})
    assert response.status_code == 200 and response.json()["ok"] is True
    with connect(settings) as connection:
        saved = json.loads(connection.execute("SELECT content_json FROM ai_document_hints").fetchone()[0])
    assert saved["summary"]
    assert saved["section_failures"]["measurements"] == "truncated"
    page = client.get("/documents/doc-1").text
    assert "missing-value check" in page
    assert "cut off at the output limit" in page

    # Every specialist cut off: nothing saved, and the reader is told it was
    # the output limit rather than a generic failure.
    def all_cut(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        return ai.AIResult(content="{", model="free/b", prompt_tokens=1, completion_tokens=1, finish_reason="length")

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", all_cut)
    failed = client.post("/documents/doc-1/ai-hints", data={"csrf_token": csrf, "refresh": "1"},
                         headers={"Accept": "application/json"})
    assert failed.status_code == 503 and failed.json()["reason"] == "truncated"
    page = client.get("/documents/doc-1?ai_error=truncated").text
    assert "cut off before it finished" in page
    assert 'data-error-truncated="' in page
    client.cookies.set("anamna_lang", "uk")
    assert "обірвалася" in client.get("/documents/doc-1?ai_error=truncated").text


def seed_suspicious_round(settings) -> None:
    hints = {
        "summary": "A lab report.", "summary_evidence": [], "suggested_title": "",
        "suggested_metadata": {}, "missed_values": [],
        "suspicious": [
            {"observation_id": "obs-0", "name": "LDL cholesterol", "value": "4.42", "unit": "mmol/L",
             "reference": "0 - 3.0", "page": 1, "reason": "The page prints 4.24.",
             "issue_type": "source_mismatch", "evidence": "LDL cholesterol 4.24 mmol/L",
             "suggested_name": "", "suggested_value": "4.24", "suggested_unit": "",
             "suggested_reference": ""},
            {"observation_id": "obs-2", "name": "Creatinine", "value": "88.0", "unit": "µmol/L",
             "reference": "", "page": 3, "reason": "A dose, not a result.",
             "issue_type": "not_measurement", "evidence": "Creatinine 88",
             "suggested_name": "", "suggested_value": "", "suggested_unit": "",
             "suggested_reference": ""},
        ],
        "immunization_issues": [], "missed_immunizations": [], "models": {}, "model": "m",
        "review_sections": ["overview", "audit"], "section_errors": [],
    }
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO ai_document_hints(document_id, locale, provider, model, content_json, created_at)
               VALUES ('doc-1', 'en', 'anthropic', 'claude-opus-5-5', ?, ?)""",
            (json.dumps(hints), utc_now()),
        )


def _ai_panel(page: str) -> str:
    return page.split('id="side-panel-ai"')[1].split("</section>")[0]


def test_suspicious_rows_render_a_prefilled_correction_that_stays_unverified(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    seed_suspicious_round(settings)
    panel = _ai_panel(client.get("/documents/doc-1").text)
    assert 'action="/observations/obs-0"' in panel
    assert 'name="ai_suggested" value="1"' in panel
    assert 'name="value_numeric" inputmode="decimal" value="4.24"' in panel
    # Fields the model left empty carry the row's current values, not blanks.
    assert 'name="unit_raw" value="mmol/L"' in panel
    assert 'name="vendor_reference_text" value="0 - 3.0"' in panel
    assert 'name="canonical_name" list="an-concept-list" value="LDL cholesterol"' in panel
    # A non-result gets a set-aside button instead of a correction.
    assert 'action="/observations/obs-2/state"' in panel
    assert "Differs from the source" in panel and "Not a measurement" in panel

    csrf = csrf_for(settings, user_id)
    response = client.post("/observations/obs-0", data={
        "csrf_token": csrf, "ai_suggested": "1", "next": "/documents/doc-1",
        "raw_name": "LDL cholesterol", "canonical_name": "LDL cholesterol",
        "value_numeric": "4.24", "value_text": "", "unit_raw": "mmol/L",
        "vendor_reference_text": "0 - 3.0",
    }, follow_redirects=False)
    assert response.status_code == 303
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT value_numeric, verification_status, extraction_method, confidence FROM observations WHERE id='obs-0'"
        ).fetchone()
        audit = connection.execute(
            "SELECT action, details_json FROM audit_events WHERE entity_id='obs-0'"
        ).fetchone()
    assert row["value_numeric"] == 4.24
    # Applied by a person, verified by nobody yet: the queue still asks.
    assert row["verification_status"] == "extracted"
    assert row["extraction_method"] == "ai_suggested_correction"
    assert row["confidence"] == pytest.approx(0.9)
    assert audit["action"] == "observation_ai_correction_applied"
    assert json.loads(audit["details_json"])["previous_value_numeric"] == 4.42

    # An ordinary correction is still a human correction.
    client.post("/observations/obs-1", data={
        "csrf_token": csrf, "raw_name": "HDL cholesterol", "value_numeric": "1.43", "unit_raw": "mmol/L",
    }, follow_redirects=False)
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT verification_status FROM observations WHERE id='obs-1'"
        ).fetchone()[0] == "corrected"

    # A row the person has since set aside offers no action any more.
    client.post("/observations/obs-2/state", data={"csrf_token": csrf, "action": "reject"}, follow_redirects=False)
    panel = _ai_panel(client.get("/documents/doc-1").text)
    assert 'action="/observations/obs-2/state"' not in panel
    assert "You have already set this row aside." in panel


def test_document_page_offers_review_only_while_the_route_is_enabled(tmp_path: Path):
    settings, _, client = build(tmp_path)
    ai.save_ai_settings(settings, {"ai_api_key": "sk-or", "ai_key_anthropic": "sk-ant"})
    ai.save_task_route(settings, "document_review", {"provider": "anthropic", "model": "claude-opus-5-5", "enabled": True})
    page = client.get("/documents/doc-1").text
    assert 'id="ai-review-form"' in page
    # The button is the whole control: no privacy paragraph above it.
    assert "page images to api.anthropic.com" not in page
    ai.save_task_route(settings, "document_review", {"provider": "anthropic", "model": "claude-opus-5-5", "enabled": False})
    assert 'id="ai-review-form"' not in client.get("/documents/doc-1").text


def test_paid_review_sends_whole_document_with_images_and_strict_format(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    ai.save_ai_settings(settings, {"ai_key_anthropic": "sk-ant"})
    ai.save_task_route(settings, "document_review", {"provider": "anthropic", "model": "claude-opus-5-5", "effort": "medium", "enabled": True})
    calls: list = []
    monkeypatch.setitem(ai.PROVIDERS, "anthropic", stub_provider(calls=calls))
    long_text = "LDL 4.42 mmol/L " * 700  # ~11k chars: beyond the free cap of 4000
    ai.document_hints(
        settings,
        document={"id": "d", "title": "report", "clinical_type": "laboratory"},
        pages=[{"page_number": n, "native_text": long_text, "ocr_text": ""} for n in range(1, 31)],
        observations=[{"id": "o1", "raw_name": "LDL", "value": "4.42", "unit": "mmol/L", "page_number": 1}],
        images=[b"png-1", b"png-2"],
        locale="en",
    )
    by_task = {}
    for call in calls:
        content = call["messages"][1]["content"]
        payload = json.loads(content[0]["text"] if isinstance(content, list) else content)
        by_task[payload["task"]] = (call, content, payload)
    assert set(by_task) == {"grounded_overview", "transcribe_printed_results", "audit_structured_extraction"}
    # The transcriber is never shown the parser's rows, or it copies them.
    assert "extracted_values" not in by_task["transcribe_printed_results"][2]["document_data"]
    assert by_task["transcribe_printed_results"][0]["response_format"] == ai.PRINTED_RESULTS_RESPONSE_FORMAT
    call, content, payload = by_task["audit_structured_extraction"]
    pages = payload["document_data"]["source_pages"]
    assert len(pages) == 30 and len(pages[0]["text"]) > 4000
    assert sum(1 for part in content if part.get("type") == "image_url") == 2
    assert call["response_format"] == ai.AUDIT_RESPONSE_FORMAT  # strict even with images
    system = call["messages"][0]["content"]
    assert "EVERY row in extracted_values" in system
    assert "the analyte name, the value, the unit, the reference interval and the page number" in system


def test_transcription_is_diffed_in_code_not_by_the_model():
    """Asked for omissions, Haiku and Sonnet both returned [] for a deleted
    haemoglobin.  A transcription diffed here finds it, flags a value the page
    contradicts, and stays silent where the parse agrees."""
    page = (
        "Гемоглобін (HGB) 151 г/л 130-170\n"
        "Холестерин загальний 7.22 ммоль/л <5.2\n"
        "Тригліцериди 1,23 ммоль/л"
    )
    source = {1: ai._match_key(page)}
    extracted = [
        {"id": "chol", "name": "Холестерин загальний", "value": "72.2", "unit": "ммоль/л", "page": 1},
        {"id": "tg", "name": "Тригліцериди", "value": "1.23", "unit": "ммоль/л", "page": 1},
    ]
    printed = [
        {"name": "Гемоглобін (HGB)", "value": "151", "unit": "г/л", "page": 1, "evidence": "Гемоглобін (HGB) 151 г/л"},
        {"name": "Холестерин загальний", "value": "7.22", "unit": "ммоль/л", "page": 1, "evidence": "Холестерин загальний 7.22"},
        {"name": "Тригліцериди", "value": "1,23", "unit": "ммоль/л", "page": 1, "evidence": "Тригліцериди 1,23"},
        # A slip the page does not support is never turned into a correction.
        {"name": "Тригліцериди", "value": "9.99", "unit": "ммоль/л", "page": 1, "evidence": ""},
    ]
    missed, mismatches = ai._compare_transcription(printed, extracted, source, {1})
    assert [row["name"] for row in missed] == ["Гемоглобін (HGB)"]
    assert [(m["observation_id"], m["suggested_value"]) for m in mismatches] == [("chol", "7.22")]


def test_openai_models_are_offered_newest_first(monkeypatch):
    """Alphabetical order put gpt-4o first and the newest families last."""
    from types import SimpleNamespace

    listing = [
        SimpleNamespace(id="gpt-4o", created=1715000000),
        SimpleNamespace(id="gpt-6-luna", created=1790000000),
        SimpleNamespace(id="text-embedding-3-large", created=1795000000),
        SimpleNamespace(id="gpt-5-mini", created=1754000000),
    ]
    client = SimpleNamespace(models=SimpleNamespace(list=lambda: listing))
    monkeypatch.setattr(ai, "_openai_client", lambda key, timeout: client)
    assert _REAL_FETCH_MODELS("openai", "sk-test") == ["gpt-6-luna", "gpt-5-mini", "gpt-4o"]
