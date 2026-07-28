from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.integrations import llm_client
from backend.app.integrations.llm_usage import (
    LlmTokenUsage,
    apply_usage_event,
    bind_usage_recorder,
    empty_llm_usage_summary,
    estimate_cost_usd,
    extract_usage,
    llm_purpose,
    load_pricing_rates,
    parse_model_name_from_url,
    resolve_model_name,
)
from backend.app.services.job_store import JobStore


def test_extract_usage_reads_prompt_completion_and_cached() -> None:
    usage = extract_usage(
        {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "total_tokens": 140,
                "prompt_tokens_details": {"cached_tokens": 20},
            }
        }
    )
    assert usage == LlmTokenUsage(
        prompt_tokens=100,
        completion_tokens=40,
        total_tokens=140,
        cached_tokens=20,
    )


def test_extract_usage_missing_payload_is_zero() -> None:
    assert extract_usage(None) == LlmTokenUsage()
    assert extract_usage({}) == LlmTokenUsage()


def test_estimate_cost_usd_splits_cached_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_INPUT_USD_PER_1M", "1.25")
    monkeypatch.setenv("LLM_OUTPUT_USD_PER_1M", "10")
    monkeypatch.setenv("LLM_CACHED_INPUT_USD_PER_1M", "0.13")
    rates = load_pricing_rates()
    usage = LlmTokenUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000, total_tokens=2_000_000, cached_tokens=200_000)
    # uncached 800k * 1.25 + cached 200k * 0.13 + output 1M * 10
    expected = (800_000 * 1.25 + 200_000 * 0.13 + 1_000_000 * 10) / 1_000_000
    assert estimate_cost_usd(usage, rates) == round(expected, 6)


def test_parse_model_name_from_deployment_url() -> None:
    assert (
        parse_model_name_from_url(
            "https://example.openai.azure.com/openai/deployments/gpt-5/chat/completions?api-version=2025-01-01-preview"
        )
        == "gpt-5"
    )


def test_resolve_model_name_prefers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL_NAME", "gpt-5-custom")
    assert resolve_model_name() == "gpt-5-custom"


def test_apply_usage_event_aggregates_by_purpose() -> None:
    summary = empty_llm_usage_summary()
    apply_usage_event(
        summary,
        purpose="specialist",
        usage=LlmTokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
    )
    apply_usage_event(
        summary,
        purpose="specialist",
        usage=LlmTokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
    )
    apply_usage_event(
        summary,
        purpose="judge",
        usage=LlmTokenUsage(prompt_tokens=40, completion_tokens=5, total_tokens=45),
    )
    assert summary["totals"]["calls"] == 3
    assert summary["totals"]["prompt_tokens"] == 160
    assert summary["totals"]["completion_tokens"] == 65
    by_purpose = {item["purpose"]: item for item in summary["by_purpose"]}
    assert by_purpose["specialist"]["calls"] == 2
    assert by_purpose["specialist"]["prompt_tokens"] == 120
    assert by_purpose["judge"]["calls"] == 1
    assert by_purpose["specialist"]["label"] == "Specialist"


def test_azure_client_sums_retry_usage_and_notifies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_CHAT_COMPLETIONS_URL", "https://example.test/openai")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    responses = iter(
        [
            {
                "choices": [{"finish_reason": "length", "message": {"content": "   "}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
            {
                "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            },
        ]
    )
    recorded: list[tuple[str, LlmTokenUsage]] = []

    def fake_post(_api_url: str, _api_key: str, _payload: dict) -> dict:
        return next(responses)

    monkeypatch.setattr(llm_client, "_post_azure_openai_sync", fake_post)

    with bind_usage_recorder(lambda purpose, usage: recorded.append((purpose, usage))):
        with llm_purpose("specialist"):
            result = llm_client.call_azure_openai("prompt", 512, "minimal")

    assert result == "ok"
    assert len(recorded) == 1
    assert recorded[0][0] == "specialist"
    assert recorded[0][1].prompt_tokens == 22
    assert recorded[0][1].completion_tokens == 13
    assert recorded[0][1].total_tokens == 35


def test_job_store_records_llm_usage_in_snapshot(tmp_path: Path) -> None:
    store = JobStore()
    job_id = "job-usage-1"
    store.create_job(
        job_id=job_id,
        original_filename="demo.xlsx",
        start_date="2026-01-01",
        end_date="2026-01-31",
        job_dir=tmp_path,
        upload_path=tmp_path / "demo.xlsx",
    )
    store.record_llm_usage(
        job_id,
        "judge",
        LlmTokenUsage(prompt_tokens=1000, completion_tokens=200, total_tokens=1200, cached_tokens=100),
    )
    store.set_llm_usage_case_count(job_id, 4)
    snapshot = store.snapshot(job_id)
    assert snapshot.llm_usage is not None
    assert snapshot.llm_usage.totals.calls == 1
    assert snapshot.llm_usage.totals.prompt_tokens == 1000
    assert snapshot.llm_usage.totals.completion_tokens == 200
    assert snapshot.llm_usage.case_count == 4
    assert snapshot.llm_usage.by_purpose[0].purpose == "judge"
    assert snapshot.llm_usage.by_purpose[0].label == "Judge"
    assert snapshot.llm_usage.notes == ["Vendor mailer uses no LLM"]
