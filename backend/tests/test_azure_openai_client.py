from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.app.domain import cab_delay_enrichment as cab_delay


def azure_payload(content: object, *, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": content},
            }
        ]
    }


def configure_azure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_CHAT_COMPLETIONS_URL", "https://example.test/openai")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")


def test_sync_azure_retries_length_empty_message_with_larger_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_azure_env(monkeypatch)
    responses = iter(
        [
            azure_payload("   ", finish_reason="length"),
            azure_payload("Generated insight.", finish_reason="stop"),
        ]
    )
    token_budgets: list[int] = []

    def fake_post(_api_url: str, _api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        token_budgets.append(payload["max_completion_tokens"])
        return next(responses)

    monkeypatch.setattr(cab_delay, "_post_azure_openai_sync", fake_post)

    result = cab_delay.call_azure_openai("prompt", 512, "minimal")

    assert result == "Generated insight."
    assert token_budgets == [512, 1024]


def test_sync_azure_exhausted_length_retries_raise_concise_error(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_azure_env(monkeypatch)
    token_budgets: list[int] = []

    def fake_post(_api_url: str, _api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        token_budgets.append(payload["max_completion_tokens"])
        return {
            "debug": "raw Azure payload should not be echoed",
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": ""},
                }
            ],
        }

    monkeypatch.setattr(cab_delay, "_post_azure_openai_sync", fake_post)

    with pytest.raises(cab_delay.AzureOpenAIEmptyMessageError) as error:
        cab_delay.call_azure_openai("prompt", 8192, "minimal")

    assert str(error.value) == "azure_empty_message finish_reason=length attempts=2"
    assert "raw Azure payload" not in str(error.value)
    assert token_budgets == [8192, 16384]


def test_sync_azure_non_length_empty_message_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_azure_env(monkeypatch)
    token_budgets: list[int] = []

    def fake_post(_api_url: str, _api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        token_budgets.append(payload["max_completion_tokens"])
        return azure_payload(None, finish_reason="stop")

    monkeypatch.setattr(cab_delay, "_post_azure_openai_sync", fake_post)

    with pytest.raises(cab_delay.AzureOpenAIEmptyMessageError) as error:
        cab_delay.call_azure_openai("prompt", 512, "minimal")

    assert str(error.value) == "azure_empty_message finish_reason=stop attempts=1"
    assert token_budgets == [512]


def test_async_azure_retries_length_empty_message_with_larger_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_azure_env(monkeypatch)
    responses = iter(
        [
            azure_payload("", finish_reason="length"),
            azure_payload("Async generated insight.", finish_reason="stop"),
        ]
    )
    token_budgets: list[int] = []

    async def fake_post(_api_url: str, _api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        token_budgets.append(payload["max_completion_tokens"])
        return next(responses)

    monkeypatch.setattr(cab_delay, "_post_azure_openai_async", fake_post)

    result = asyncio.run(cab_delay.call_azure_openai_async("prompt", 512, "minimal"))

    assert result == "Async generated insight."
    assert token_budgets == [512, 1024]


def test_async_azure_exhausted_length_retries_raise_concise_error(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_azure_env(monkeypatch)
    token_budgets: list[int] = []

    async def fake_post(_api_url: str, _api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        token_budgets.append(payload["max_completion_tokens"])
        return azure_payload("", finish_reason="length")

    monkeypatch.setattr(cab_delay, "_post_azure_openai_async", fake_post)

    with pytest.raises(cab_delay.AzureOpenAIEmptyMessageError) as error:
        asyncio.run(cab_delay.call_azure_openai_async("prompt", 8192, "minimal"))

    assert str(error.value) == "azure_empty_message finish_reason=length attempts=2"
    assert token_budgets == [8192, 16384]
