from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from backend.app.core.tracking_utils import (
    IST_OFFSET,
    MISSING_TIME_VALUES,
    booking_comments,
    duration_minutes,
    first_tracking_row,
    format_display_time,
    format_dt,
    format_duration,
    format_existing_ist_time,
    format_ist_from_utc,
    parse_tracking_time,
    raw_tracking_value,
    read_tracking_data,
)
from backend.app.integrations.llm_client import (
    AZURE_MAX_COMPLETION_TOKENS_CAP,
    AZURE_SYSTEM_MESSAGE,
    DEFAULT_MAX_COMPLETION_TOKENS,
    DEFAULT_REASONING_EFFORT,
    AzureOpenAIEmptyMessageError,
    _post_azure_openai_async,
    _post_azure_openai_sync,
    azure_completion_token_budgets,
    azure_message_content,
    build_azure_openai_payload,
    should_retry_empty_message,
)


PREFERRED_START_TIME_IST_COLUMN = "Customer preferred pickup time (IST)"
DRIVER_STARTED_COLUMN = "Driver started towards pickup (IST)"
DRIVER_ARRIVED_COLUMN = "Driver arrived at pickup (IST)"
BOARDED_COLUMN = "Customer boarded cab (IST)"
INCABS_INSIGHT_COLUMN = "insights from incabs data"
COMMENTS_COLUMN = "comments"
INCABS_COMMENT_SUMMARY_COLUMN = "incabs and customer comment summary"
CAB_DELAY_ENRICHMENT_COLUMNS = [
    PREFERRED_START_TIME_IST_COLUMN,
    DRIVER_STARTED_COLUMN,
    DRIVER_ARRIVED_COLUMN,
    BOARDED_COLUMN,
    INCABS_INSIGHT_COLUMN,
    COMMENTS_COLUMN,
    INCABS_COMMENT_SUMMARY_COLUMN,
]
CAB_DELAY_PATTERN = re.compile(r"\bcab\s+(?:delay|delayed|dealy)\b", re.IGNORECASE)
NON_CAB_DELAY_REMARK_TOKEN_PATTERN = re.compile(
    r"\bcab\s+(?:delay|delayed|dealy)\b|[/,+&]|\band\b|\s+",
    re.IGNORECASE,
)
OUTPUT_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DISPLAY_DATETIME_FORMAT = "%d %b %Y %I:%M %p"
DISPLAY_DATETIME_WITH_SECONDS_FORMAT = "%d %b %Y %I:%M:%S %p"


def call_azure_openai(prompt: str, max_completion_tokens: int, reasoning_effort: str) -> str:
    """Call Azure OpenAI synchronously; defined here so monkeypatching _post_azure_openai_sync works."""
    import os
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


async def call_azure_openai_async(prompt: str, max_completion_tokens: int, reasoning_effort: str) -> str:
    """Call Azure OpenAI asynchronously; defined here so monkeypatching _post_azure_openai_async works."""
    import os
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


@dataclass(frozen=True)
class TimingContext:
    scheduled_pickup_ist: datetime | None
    driver_started: datetime | None
    driver_arrived: datetime | None
    boarded: datetime | None


@dataclass(frozen=True)
class TrackingEnrichment:
    preferred_start_time_ist: str
    driver_started: str
    driver_arrived: str
    boarded: str
    comments: str

    def to_columns(self) -> dict[str, str]:
        return {
            PREFERRED_START_TIME_IST_COLUMN: self.preferred_start_time_ist,
            DRIVER_STARTED_COLUMN: self.driver_started,
            DRIVER_ARRIVED_COLUMN: self.driver_arrived,
            BOARDED_COLUMN: self.boarded,
            COMMENTS_COLUMN: self.comments,
        }


def contains_cab_delay(value: object) -> bool:
    if pd.isna(value):
        return False
    return bool(CAB_DELAY_PATTERN.search(str(value)))


def is_pure_cab_delay_remark(value: object) -> bool:
    if pd.isna(value):
        return False

    raw_value = str(value).strip()
    if not raw_value or not contains_cab_delay(raw_value):
        return False

    leftover = NON_CAB_DELAY_REMARK_TOKEN_PATTERN.sub("", raw_value).strip()
    return leftover == ""


def build_tracking_enrichment(bookings: dict[str, Any], booking_id: str) -> TrackingEnrichment:
    tracking_row = first_tracking_row(bookings, booking_id)

    return TrackingEnrichment(
        preferred_start_time_ist=format_ist_from_utc(tracking_row.get("start_time")),
        driver_started=format_existing_ist_time(tracking_row.get("driver_started")),
        driver_arrived=format_existing_ist_time(tracking_row.get("driver_arrived")),
        boarded=format_existing_ist_time(tracking_row.get("boarded")),
        comments=booking_comments(bookings, booking_id),
    )


def build_timing_context(tracking_row: dict[str, Any]) -> TimingContext:
    start_time_utc = parse_tracking_time(tracking_row.get("start_time"))
    return TimingContext(
        scheduled_pickup_ist=start_time_utc + IST_OFFSET if start_time_utc else None,
        driver_started=parse_tracking_time(tracking_row.get("driver_started")),
        driver_arrived=parse_tracking_time(tracking_row.get("driver_arrived")),
        boarded=parse_tracking_time(tracking_row.get("boarded")),
    )


def build_incabs_insight_prompt(booking_id: str, timing: TimingContext) -> str:
    pickup_to_start = duration_minutes(timing.scheduled_pickup_ist, timing.driver_started)
    pickup_to_arrival = duration_minutes(timing.scheduled_pickup_ist, timing.driver_arrived)
    pickup_to_boarding = duration_minutes(timing.scheduled_pickup_ist, timing.boarded)
    start_to_arrival = duration_minutes(timing.driver_started, timing.driver_arrived)
    arrival_to_boarding = duration_minutes(timing.driver_arrived, timing.boarded)

    return "\n".join(
        [
            "Write one short, business-friendly Incabs insight explaining this cab delay.",
            "Do not mention UTC, JSON, APIs, fields, or technical system names.",
            "Use the calculated delays as facts. If a timestamp is unavailable, say the available evidence only.",
            "Keep it to one sentence, under 45 words.",
            "",
            f"Booking ID: {booking_id}",
            f"Scheduled pickup time: {format_dt(timing.scheduled_pickup_ist)}",
            f"Driver started time: {format_dt(timing.driver_started)}",
            f"Driver arrived time: {format_dt(timing.driver_arrived)}",
            f"Customer boarded time: {format_dt(timing.boarded)}",
            f"Driver started after scheduled pickup: {format_duration(pickup_to_start)}",
            f"Driver arrived after scheduled pickup: {format_duration(pickup_to_arrival)}",
            f"Customer boarded after scheduled pickup: {format_duration(pickup_to_boarding)}",
            f"Driver travel time from start to arrival: {format_duration(start_to_arrival)}",
            f"Customer wait after driver arrival: {format_duration(arrival_to_boarding)}",
        ]
    )


def build_comment_summary_prompt(
    *,
    booking_id: str,
    incabs_insight: str,
    comments: str,
    preferred_start_time_ist: str,
) -> str:
    return "\n".join(
        [
            "Write one brief business-friendly summary comparing Incabs tracking data with the customer call comment.",
            "Explain what Incabs says and what the customer reported, without choosing a side unless the facts clearly show it.",
            "Prefer IST timing for readability. Do not mention JSON, APIs, fields, prompts, or technical system names.",
            "Keep it to one sentence, under 55 words.",
            "",
            f"Booking ID: {booking_id}",
            f"Preferred pickup time (IST): {preferred_start_time_ist or 'unavailable'}",
            f"Incabs insight: {incabs_insight or 'unavailable'}",
            f"Customer call comment: {comments or 'unavailable'}",
        ]
    )


def find_target_rows(df: pd.DataFrame) -> pd.Series:
    if "Sub Category" not in df.columns or "Remarks" not in df.columns:
        raise KeyError("Input workbook must contain 'Sub Category' and 'Remarks' columns.")

    mentions_cab_delay = df["Sub Category"].apply(contains_cab_delay) | df["Remarks"].apply(contains_cab_delay)
    pure_cab_delay_remark = df["Remarks"].apply(is_pure_cab_delay_remark)
    return mentions_cab_delay & pure_cab_delay_remark


def ensure_enrichment_columns(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    for column in CAB_DELAY_ENRICHMENT_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    return output
