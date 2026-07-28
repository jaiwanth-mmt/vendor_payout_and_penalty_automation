from __future__ import annotations

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator


PURPOSE_LABELS: dict[str, str] = {
    "lower_category_vehicle": "Lower category vehicle",
    "source_alignment": "Source alignment",
    "specialist": "Specialist",
    "judge": "Judge",
    "portfolio": "Portfolio summary",
    "unknown": "Other",
}

PURPOSE_ORDER: tuple[str, ...] = (
    "specialist",
    "judge",
    "source_alignment",
    "lower_category_vehicle",
    "portfolio",
    "unknown",
)

DEFAULT_MODEL_NAME = "gpt-5"
DEFAULT_INPUT_USD_PER_1M = 1.25
DEFAULT_OUTPUT_USD_PER_1M = 10.0
DEFAULT_CACHED_INPUT_USD_PER_1M = 0.13

MAILER_NOTE = "Vendor mailer uses no LLM"


@dataclass(frozen=True)
class LlmPricingRates:
    input_usd_per_1m: float
    output_usd_per_1m: float
    cached_input_usd_per_1m: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_usd_per_1m": self.input_usd_per_1m,
            "output_usd_per_1m": self.output_usd_per_1m,
            "cached_input_usd_per_1m": self.cached_input_usd_per_1m,
            "currency": "USD",
        }


@dataclass(frozen=True)
class LlmTokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0

    @property
    def has_tokens(self) -> bool:
        return (
            self.prompt_tokens > 0
            or self.completion_tokens > 0
            or self.total_tokens > 0
            or self.cached_tokens > 0
        )

    def added(self, other: "LlmTokenUsage") -> "LlmTokenUsage":
        prompt = self.prompt_tokens + other.prompt_tokens
        completion = self.completion_tokens + other.completion_tokens
        cached = self.cached_tokens + other.cached_tokens
        total = self.total_tokens + other.total_tokens
        if total <= 0:
            total = prompt + completion
        return LlmTokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cached_tokens=cached,
        )


UsageRecorder = Callable[[str, LlmTokenUsage], None]

_current_llm_purpose: ContextVar[str] = ContextVar("current_llm_purpose", default="unknown")
_current_usage_recorder: ContextVar[UsageRecorder | None] = ContextVar(
    "current_usage_recorder",
    default=None,
)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        return default


def load_pricing_rates() -> LlmPricingRates:
    return LlmPricingRates(
        input_usd_per_1m=_env_float("LLM_INPUT_USD_PER_1M", DEFAULT_INPUT_USD_PER_1M),
        output_usd_per_1m=_env_float("LLM_OUTPUT_USD_PER_1M", DEFAULT_OUTPUT_USD_PER_1M),
        cached_input_usd_per_1m=_env_float(
            "LLM_CACHED_INPUT_USD_PER_1M",
            DEFAULT_CACHED_INPUT_USD_PER_1M,
        ),
    )


def parse_model_name_from_url(api_url: str | None) -> str | None:
    if not api_url:
        return None
    match = re.search(r"/deployments/([^/?]+)", str(api_url))
    if not match:
        return None
    name = match.group(1).strip()
    return name or None


def resolve_model_name() -> str:
    explicit = (os.getenv("LLM_MODEL_NAME") or "").strip()
    if explicit:
        return explicit
    from_url = parse_model_name_from_url(os.getenv("AZURE_OPENAI_CHAT_COMPLETIONS_URL"))
    return from_url or DEFAULT_MODEL_NAME


def extract_usage(response_payload: dict[str, Any] | None) -> LlmTokenUsage:
    if not isinstance(response_payload, dict):
        return LlmTokenUsage()
    usage = response_payload.get("usage")
    if not isinstance(usage, dict):
        return LlmTokenUsage()

    prompt = _nonneg_int(usage.get("prompt_tokens"))
    completion = _nonneg_int(usage.get("completion_tokens"))
    total = _nonneg_int(usage.get("total_tokens"))
    if total <= 0:
        total = prompt + completion

    cached = 0
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = _nonneg_int(details.get("cached_tokens"))
    return LlmTokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cached_tokens=cached,
    )


def estimate_cost_usd(usage: LlmTokenUsage, rates: LlmPricingRates | None = None) -> float:
    active = rates or load_pricing_rates()
    cached = min(max(0, usage.cached_tokens), max(0, usage.prompt_tokens))
    uncached = max(0, usage.prompt_tokens - cached)
    cost = (
        (uncached * active.input_usd_per_1m)
        + (cached * active.cached_input_usd_per_1m)
        + (usage.completion_tokens * active.output_usd_per_1m)
    ) / 1_000_000.0
    return round(cost, 6)


def purpose_label(purpose: str) -> str:
    key = (purpose or "unknown").strip() or "unknown"
    return PURPOSE_LABELS.get(key, PURPOSE_LABELS["unknown"])


def empty_llm_usage_summary(*, case_count: int = 0) -> dict[str, Any]:
    rates = load_pricing_rates()
    return {
        "model": resolve_model_name(),
        "pricing": rates.as_dict(),
        "totals": {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
        },
        "by_purpose": [],
        "case_count": max(0, int(case_count)),
        "notes": [MAILER_NOTE],
    }


def apply_usage_event(
    summary: dict[str, Any],
    *,
    purpose: str,
    usage: LlmTokenUsage,
    calls: int = 1,
) -> dict[str, Any]:
    """Mutate and return an llm_usage summary dict with one logical call applied."""
    rates = LlmPricingRates(
        input_usd_per_1m=float((summary.get("pricing") or {}).get("input_usd_per_1m") or DEFAULT_INPUT_USD_PER_1M),
        output_usd_per_1m=float((summary.get("pricing") or {}).get("output_usd_per_1m") or DEFAULT_OUTPUT_USD_PER_1M),
        cached_input_usd_per_1m=float(
            (summary.get("pricing") or {}).get("cached_input_usd_per_1m") or DEFAULT_CACHED_INPUT_USD_PER_1M
        ),
    )
    cost = estimate_cost_usd(usage, rates)
    purpose_key = (purpose or "unknown").strip() or "unknown"
    label = purpose_label(purpose_key)

    totals = summary.setdefault(
        "totals",
        {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
        },
    )
    totals["calls"] = int(totals.get("calls") or 0) + max(0, int(calls))
    totals["prompt_tokens"] = int(totals.get("prompt_tokens") or 0) + usage.prompt_tokens
    totals["completion_tokens"] = int(totals.get("completion_tokens") or 0) + usage.completion_tokens
    totals["cached_tokens"] = int(totals.get("cached_tokens") or 0) + usage.cached_tokens
    totals["total_tokens"] = int(totals.get("total_tokens") or 0) + (
        usage.total_tokens if usage.total_tokens else usage.prompt_tokens + usage.completion_tokens
    )
    totals["estimated_cost_usd"] = round(float(totals.get("estimated_cost_usd") or 0.0) + cost, 6)

    by_purpose: list[dict[str, Any]] = list(summary.get("by_purpose") or [])
    entry = next((item for item in by_purpose if item.get("purpose") == purpose_key), None)
    if entry is None:
        entry = {
            "purpose": purpose_key,
            "label": label,
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
        }
        by_purpose.append(entry)
    entry["calls"] = int(entry.get("calls") or 0) + max(0, int(calls))
    entry["prompt_tokens"] = int(entry.get("prompt_tokens") or 0) + usage.prompt_tokens
    entry["completion_tokens"] = int(entry.get("completion_tokens") or 0) + usage.completion_tokens
    entry["cached_tokens"] = int(entry.get("cached_tokens") or 0) + usage.cached_tokens
    entry["total_tokens"] = int(entry.get("total_tokens") or 0) + (
        usage.total_tokens if usage.total_tokens else usage.prompt_tokens + usage.completion_tokens
    )
    entry["estimated_cost_usd"] = round(float(entry.get("estimated_cost_usd") or 0.0) + cost, 6)
    entry["label"] = label

    order = {key: index for index, key in enumerate(PURPOSE_ORDER)}
    by_purpose.sort(key=lambda item: (order.get(str(item.get("purpose")), 99), str(item.get("label") or "")))
    summary["by_purpose"] = by_purpose
    if "notes" not in summary or not summary["notes"]:
        summary["notes"] = [MAILER_NOTE]
    if not summary.get("model"):
        summary["model"] = resolve_model_name()
    if not summary.get("pricing"):
        summary["pricing"] = rates.as_dict()
    return summary


def notify_recorded_usage(usage: LlmTokenUsage, *, calls: int = 1) -> None:
    if int(calls) <= 0 and not usage.has_tokens:
        return
    recorder = _current_usage_recorder.get()
    if recorder is None:
        return
    purpose = _current_llm_purpose.get() or "unknown"
    recorder(purpose, usage)


@contextmanager
def llm_purpose(purpose: str) -> Iterator[None]:
    token = _current_llm_purpose.set((purpose or "unknown").strip() or "unknown")
    try:
        yield
    finally:
        _current_llm_purpose.reset(token)


@contextmanager
def bind_usage_recorder(recorder: UsageRecorder | None) -> Iterator[None]:
    token = _current_usage_recorder.set(recorder)
    try:
        yield
    finally:
        _current_usage_recorder.reset(token)


def _nonneg_int(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, number)
