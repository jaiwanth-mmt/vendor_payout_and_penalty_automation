from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.app.core.tracking_utils import (
    booking_comments,
    first_tracking_row,
    format_existing_ist_time,
    format_ist_from_utc,
)
from backend.app.integrations.llm_client import (
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
COMMENTS_COLUMN = "comments"
CAB_DELAY_ENRICHMENT_COLUMNS = [
    PREFERRED_START_TIME_IST_COLUMN,
    DRIVER_STARTED_COLUMN,
    DRIVER_ARRIVED_COLUMN,
    BOARDED_COLUMN,
    COMMENTS_COLUMN,
]


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


def build_tracking_enrichment(bookings: dict[str, Any], booking_id: str) -> TrackingEnrichment:
    tracking_row = first_tracking_row(bookings, booking_id)

    return TrackingEnrichment(
        preferred_start_time_ist=format_ist_from_utc(tracking_row.get("start_time")),
        driver_started=format_existing_ist_time(tracking_row.get("driver_started")),
        driver_arrived=format_existing_ist_time(tracking_row.get("driver_arrived")),
        boarded=format_existing_ist_time(tracking_row.get("boarded")),
        comments=booking_comments(bookings, booking_id),
    )


def ensure_enrichment_columns(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    for column in CAB_DELAY_ENRICHMENT_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    return output


def enrich_cab_delay_rows(df: pd.DataFrame, *, tracking_bookings: dict[str, Any]) -> pd.DataFrame:
    """Attach Cab Delay timing + comments columns from live tracking (no LLM)."""
    output = ensure_enrichment_columns(df)
    for index in output.index.tolist():
        booking_id = str(output.at[index, "Booking ID"]).strip()
        if not booking_id:
            continue
        enrichment = build_tracking_enrichment(tracking_bookings, booking_id)
        for column, value in enrichment.to_columns().items():
            output.at[index, column] = value
    return output
