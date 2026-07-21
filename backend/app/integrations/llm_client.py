from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable

import httpx


DEFAULT_MAX_COMPLETION_TOKENS = 2048
DEFAULT_REASONING_EFFORT = "minimal"
AZURE_MAX_COMPLETION_TOKENS_CAP = 16384
AZURE_SYSTEM_MESSAGE = "You write concise operational explanations for non-technical business users."

LlmGenerator = Callable[[str, int, str], str | Awaitable[str]]


class AzureOpenAIEmptyMessageError(RuntimeError):
    def __init__(self, *, finish_reason: object, attempts: int) -> None:
        reason = str(finish_reason or "unknown").strip() or "unknown"
        self.finish_reason = reason
        self.attempts = attempts
        super().__init__(f"azure_empty_message finish_reason={reason} attempts={attempts}")


def build_azure_openai_payload(prompt: str, max_completion_tokens: int, reasoning_effort: str) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": AZURE_SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        "max_completion_tokens": max_completion_tokens,
        "reasoning_effort": reasoning_effort,
    }


def azure_completion_token_budgets(max_completion_tokens: int) -> list[int]:
    budgets: list[int] = []
    current = max_completion_tokens
    while True:
        if current not in budgets:
            budgets.append(current)
        if current >= AZURE_MAX_COMPLETION_TOKENS_CAP:
            break
        current = min(current * 2 if current > 0 else AZURE_MAX_COMPLETION_TOKENS_CAP, AZURE_MAX_COMPLETION_TOKENS_CAP)
    return budgets


def azure_message_content(response_payload: dict[str, Any], *, attempts: int) -> str:
    choices = response_payload.get("choices", [])
    if not choices:
        raise RuntimeError("azure_no_choices")

    choice = choices[0]
    content = choice.get("message", {}).get("content")
    if content is None or not str(content).strip():
        raise AzureOpenAIEmptyMessageError(finish_reason=choice.get("finish_reason"), attempts=attempts)

    return " ".join(str(content).strip().split())


def should_retry_empty_message(error: AzureOpenAIEmptyMessageError, *, attempt: int, max_attempts: int) -> bool:
    return error.finish_reason == "length" and attempt < max_attempts


def _post_azure_openai_sync(api_url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Azure OpenAI request failed with HTTP {error.code}: {error_body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Azure OpenAI request failed: {error.reason}") from error


async def _post_azure_openai_async(api_url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                api_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "api-key": api_key,
                },
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as error:
        raise RuntimeError(
            f"Azure OpenAI request failed with HTTP {error.response.status_code}: {error.response.text}"
        ) from error
    except httpx.RequestError as error:
        raise RuntimeError(f"Azure OpenAI request failed: {error}") from error


def call_azure_openai(
    prompt: str,
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> str:
    api_url = os.getenv("AZURE_OPENAI_CHAT_COMPLETIONS_URL")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    if not api_url or not api_key:
        raise ValueError("AZURE_OPENAI_CHAT_COMPLETIONS_URL and AZURE_OPENAI_API_KEY are required in .env.")

    budgets = azure_completion_token_budgets(max_completion_tokens)
    for attempt, token_budget in enumerate(budgets, start=1):
        payload = build_azure_openai_payload(prompt, token_budget, reasoning_effort)
        response_payload = _post_azure_openai_sync(api_url, api_key, payload)
        try:
            return azure_message_content(response_payload, attempts=attempt)
        except AzureOpenAIEmptyMessageError as error:
            if should_retry_empty_message(error, attempt=attempt, max_attempts=len(budgets)):
                continue
            raise

    raise AzureOpenAIEmptyMessageError(finish_reason="length", attempts=len(budgets))


async def call_azure_openai_async(
    prompt: str,
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> str:
    api_url = os.getenv("AZURE_OPENAI_CHAT_COMPLETIONS_URL")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    if not api_url or not api_key:
        raise ValueError("AZURE_OPENAI_CHAT_COMPLETIONS_URL and AZURE_OPENAI_API_KEY are required in .env.")

    budgets = azure_completion_token_budgets(max_completion_tokens)
    for attempt, token_budget in enumerate(budgets, start=1):
        payload = build_azure_openai_payload(prompt, token_budget, reasoning_effort)
        response_payload = await _post_azure_openai_async(api_url, api_key, payload)
        try:
            return azure_message_content(response_payload, attempts=attempt)
        except AzureOpenAIEmptyMessageError as error:
            if should_retry_empty_message(error, attempt=attempt, max_attempts=len(budgets)):
                continue
            raise

    raise AzureOpenAIEmptyMessageError(finish_reason="length", attempts=len(budgets))


async def maybe_call_llm(
    llm_generator: LlmGenerator,
    prompt: str,
    max_completion_tokens: int,
    reasoning_effort: str,
) -> str:
    result = llm_generator(prompt, max_completion_tokens, reasoning_effort)
    if hasattr(result, "__await__"):
        return str(await result)  # type: ignore[misc]
    return str(result)


def call_llm_sync(
    llm_generator: LlmGenerator,
    prompt: str,
    max_completion_tokens: int,
    reasoning_effort: str,
) -> str:
    """Run an LLM generator synchronously without identity-checking the Azure client."""
    import asyncio
    import inspect

    result = llm_generator(prompt, max_completion_tokens, reasoning_effort)
    if inspect.isawaitable(result):
        return str(asyncio.run(result))
    return str(result)
