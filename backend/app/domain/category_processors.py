from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.app.agents import AGENT_OUTPUT_COLUMNS, investigate_category_frame_async
from backend.app.domain.cab_delay_enrichment import (
    CAB_DELAY_ENRICHMENT_COLUMNS,
    COMMENTS_COLUMN,
    enrich_cab_delay_rows,
)
from backend.app.integrations.llm_client import call_llm_sync, maybe_call_llm
from backend.app.domain.complaint_message import (
    MESSAGE_COLUMN,
    build_message_classification_prompt,
    build_message_from_response,
    build_message_repair_prompt,
)
from backend.app.domain.extra_money_taken import (
    EXTRA_MONEY_TAKEN_ENRICHMENT_COLUMNS,
    enrich_extra_money_taken_rows,
)
from backend.app.domain.fulfillment_not_done import (
    FULFILLMENT_NOT_DONE_ENRICHMENT_COLUMNS,
    enrich_fulfillment_not_done_rows,
)
from backend.app.domain.lower_category_vehicle import (
    CUSTOMER_BOOKED_VEHICLE_COLUMN,
    CUSTOMER_RECEIVED_VEHICLE_COLUMN,
    LOWER_CATEGORY_VEHICLE_ENRICHMENT_COLUMNS,
    build_lower_category_vehicle_enrichment,
    build_lower_category_vehicle_prompt,
    ensure_lower_category_vehicle_columns,
    parse_lower_category_vehicle_response,
)
from backend.app.domain.penalty_dataset import FINAL_OUTPUT_COLUMNS
from backend.app.domain.subcategories import CategoryBatch
from backend.app.domain.tracking_common import COMMON_TRACKING_COLUMNS, enrich_common_tracking_fields


LlmGenerator = Callable[[str, int, str], str | Awaitable[str]]


def append_unique_columns(base_columns: list[str], extra_columns: list[str]) -> list[str]:
    output = list(base_columns)
    for column in extra_columns:
        if column not in output:
            output.append(column)
    return output


CAB_DELAY_CATEGORY = "Cab Delay"
EXTRA_MONEY_TAKEN_CATEGORY = "Extra Money Taken"
FULFILLMENT_NOT_DONE_CATEGORY = "FULFILLMENT NOT DONE"
LOWER_CATEGORY_VEHICLE_CATEGORY = "Lower Category Vehicle"

COMMON_PROCESSED_BASE_COLUMNS = [*FINAL_OUTPUT_COLUMNS, *COMMON_TRACKING_COLUMNS]
COMMON_PROCESSED_OUTPUT_COLUMNS = append_unique_columns(
    append_unique_columns(COMMON_PROCESSED_BASE_COLUMNS, [MESSAGE_COLUMN]),
    AGENT_OUTPUT_COLUMNS,
)
CAB_DELAY_OUTPUT_COLUMNS = append_unique_columns(
    append_unique_columns(COMMON_PROCESSED_BASE_COLUMNS, CAB_DELAY_ENRICHMENT_COLUMNS),
    [MESSAGE_COLUMN, *AGENT_OUTPUT_COLUMNS],
)
EXTRA_MONEY_TAKEN_OUTPUT_COLUMNS = append_unique_columns(
    append_unique_columns(COMMON_PROCESSED_BASE_COLUMNS, EXTRA_MONEY_TAKEN_ENRICHMENT_COLUMNS),
    [MESSAGE_COLUMN, *AGENT_OUTPUT_COLUMNS],
)
FULFILLMENT_NOT_DONE_OUTPUT_COLUMNS = append_unique_columns(
    append_unique_columns(COMMON_PROCESSED_BASE_COLUMNS, FULFILLMENT_NOT_DONE_ENRICHMENT_COLUMNS),
    [MESSAGE_COLUMN, *AGENT_OUTPUT_COLUMNS],
)
LOWER_CATEGORY_VEHICLE_OUTPUT_COLUMNS = append_unique_columns(
    append_unique_columns(COMMON_PROCESSED_BASE_COLUMNS, LOWER_CATEGORY_VEHICLE_ENRICHMENT_COLUMNS),
    [MESSAGE_COLUMN, *AGENT_OUTPUT_COLUMNS],
)


@dataclass(frozen=True)
class CategoryProcessorSpec:
    category_name: str
    output_columns: list[str]


COMMON_PROCESSOR_SPEC = CategoryProcessorSpec("default", COMMON_PROCESSED_OUTPUT_COLUMNS)
CATEGORY_PROCESSORS: dict[str, CategoryProcessorSpec] = {
    CAB_DELAY_CATEGORY: CategoryProcessorSpec(CAB_DELAY_CATEGORY, CAB_DELAY_OUTPUT_COLUMNS),
    EXTRA_MONEY_TAKEN_CATEGORY: CategoryProcessorSpec(
        EXTRA_MONEY_TAKEN_CATEGORY,
        EXTRA_MONEY_TAKEN_OUTPUT_COLUMNS,
    ),
    FULFILLMENT_NOT_DONE_CATEGORY: CategoryProcessorSpec(
        FULFILLMENT_NOT_DONE_CATEGORY,
        FULFILLMENT_NOT_DONE_OUTPUT_COLUMNS,
    ),
    LOWER_CATEGORY_VEHICLE_CATEGORY: CategoryProcessorSpec(
        LOWER_CATEGORY_VEHICLE_CATEGORY,
        LOWER_CATEGORY_VEHICLE_OUTPUT_COLUMNS,
    ),
}


@dataclass
class CategoryProcessingOutcome:
    df: pd.DataFrame
    failed: bool = False
    error: str | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    agent_cases: list[dict[str, Any]] = field(default_factory=list)


CategoryEnrichmentResult = tuple[pd.DataFrame, list[dict[str, Any]]]
CategoryAsyncEnricher = Callable[..., Awaitable[CategoryEnrichmentResult]]


def output_columns_for_category(category_name: str) -> list[str]:
    return CATEGORY_PROCESSORS.get(category_name, COMMON_PROCESSOR_SPEC).output_columns


async def _enrich_cab_delay_async(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
    llm_concurrency: int,
) -> CategoryEnrichmentResult:
    del llm_generator, llm_concurrency
    enriched_df = await asyncio.to_thread(
        enrich_cab_delay_rows,
        df,
        tracking_bookings=tracking_bookings,
    )
    return enriched_df, []


async def _enrich_extra_money_taken_async(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
    llm_concurrency: int,
) -> CategoryEnrichmentResult:
    del llm_generator, llm_concurrency
    enriched_df = await asyncio.to_thread(
        enrich_extra_money_taken_rows,
        df,
        tracking_bookings=tracking_bookings,
    )
    return enriched_df, []


async def _enrich_fulfillment_not_done_async(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
    llm_concurrency: int,
) -> CategoryEnrichmentResult:
    del llm_generator, llm_concurrency
    enriched_df = await asyncio.to_thread(
        enrich_fulfillment_not_done_rows,
        df,
        tracking_bookings=tracking_bookings,
    )
    return enriched_df, []


async def _enrich_lower_category_vehicle_async(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
    llm_concurrency: int,
) -> CategoryEnrichmentResult:
    enriched_df, warnings = await enrich_lower_category_vehicle_async(
        df,
        tracking_bookings=tracking_bookings,
        llm_generator=llm_generator,
        llm_concurrency=llm_concurrency,
    )
    return enriched_df, warnings


async def _enrich_default_async(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
    llm_concurrency: int,
) -> CategoryEnrichmentResult:
    del tracking_bookings, llm_generator, llm_concurrency
    return df, []


CATEGORY_ASYNC_ENRICHERS: dict[str, CategoryAsyncEnricher] = {
    CAB_DELAY_CATEGORY: _enrich_cab_delay_async,
    EXTRA_MONEY_TAKEN_CATEGORY: _enrich_extra_money_taken_async,
    FULFILLMENT_NOT_DONE_CATEGORY: _enrich_fulfillment_not_done_async,
    LOWER_CATEGORY_VEHICLE_CATEGORY: _enrich_lower_category_vehicle_async,
}


def process_category_batch(
    batch: CategoryBatch,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
) -> CategoryProcessingOutcome:
    return asyncio.run(
        process_category_batch_async(
            batch,
            tracking_bookings=tracking_bookings,
            llm_generator=llm_generator,
            llm_concurrency=1,
        )
    )


async def process_category_batch_async(
    batch: CategoryBatch,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
    llm_concurrency: int,
    job_id: str | None = None,
    enable_hitl: bool = False,
    on_agent_event=None,
) -> CategoryProcessingOutcome:
    base_df = enrich_common_tracking_fields(batch.df, tracking_bookings=tracking_bookings)
    enricher = CATEGORY_ASYNC_ENRICHERS.get(batch.name, _enrich_default_async)
    enriched_df, warnings = await enricher(
        base_df,
        tracking_bookings=tracking_bookings,
        llm_generator=llm_generator,
        llm_concurrency=llm_concurrency,
    )
    enriched_df = await enrich_message_column_async(
        enriched_df,
        llm_generator=llm_generator,
        llm_concurrency=llm_concurrency,
    )
    enriched_df, agent_cases = await investigate_category_frame_async(
        enriched_df,
        tracking_bookings=tracking_bookings,
        llm_generator=llm_generator,
        llm_concurrency=llm_concurrency,
        job_id=job_id,
        enable_hitl=enable_hitl,
        on_event=on_agent_event,
    )
    return CategoryProcessingOutcome(
        enriched_df.loc[:, output_columns_for_category(batch.name)].copy(),
        warnings=warnings,
        agent_cases=agent_cases,
    )


def ensure_message_column(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    output[MESSAGE_COLUMN] = pd.Series([""] * len(output), index=output.index, dtype=object)
    return output


def row_text(df: pd.DataFrame, index: int, column: str) -> str:
    if column not in df.columns:
        return ""
    value = df.at[index, column]
    if pd.isna(value):
        return ""
    return str(value).strip()


def build_message_with_repair_sync(
    *,
    sub_category: str,
    remarks: str,
    comments: str,
    llm_generator: LlmGenerator,
    max_completion_tokens: int,
    reasoning_effort: str,
) -> str:
    prompt = build_message_classification_prompt(
        sub_category=sub_category,
        remarks=remarks,
        comments=comments,
    )
    response = ""
    failure_reason = "empty_or_unmapped_categories"
    try:
        response = call_azure_or_custom_sync(
            llm_generator,
            prompt,
            max_completion_tokens,
            reasoning_effort,
        )
        message = build_message_from_response(
            response,
            sub_category=sub_category,
            remarks=remarks,
            comments=comments,
        )
        if message:
            return message
    except Exception as exc:
        failure_reason = f"initial_classification_failed: {type(exc).__name__}"

    repair_prompt = build_message_repair_prompt(
        sub_category=sub_category,
        remarks=remarks,
        comments=comments,
        previous_response=response,
        failure_reason=failure_reason,
    )
    try:
        repair_response = call_azure_or_custom_sync(
            llm_generator,
            repair_prompt,
            max_completion_tokens,
            reasoning_effort,
        )
        return build_message_from_response(
            repair_response,
            sub_category=sub_category,
            remarks=remarks,
            comments=comments,
        )
    except Exception:
        return ""


async def build_message_with_repair_async(
    *,
    sub_category: str,
    remarks: str,
    comments: str,
    llm_generator: LlmGenerator,
    semaphore: asyncio.Semaphore,
    max_completion_tokens: int,
    reasoning_effort: str,
) -> str:
    prompt = build_message_classification_prompt(
        sub_category=sub_category,
        remarks=remarks,
        comments=comments,
    )
    response = ""
    failure_reason = "empty_or_unmapped_categories"
    try:
        async with semaphore:
            response = await maybe_call_llm(llm_generator, prompt, max_completion_tokens, reasoning_effort)
        message = build_message_from_response(
            response,
            sub_category=sub_category,
            remarks=remarks,
            comments=comments,
        )
        if message:
            return message
    except Exception as exc:
        failure_reason = f"initial_classification_failed: {type(exc).__name__}"

    repair_prompt = build_message_repair_prompt(
        sub_category=sub_category,
        remarks=remarks,
        comments=comments,
        previous_response=response,
        failure_reason=failure_reason,
    )
    try:
        async with semaphore:
            repair_response = await maybe_call_llm(
                llm_generator,
                repair_prompt,
                max_completion_tokens,
                reasoning_effort,
            )
        return build_message_from_response(
            repair_response,
            sub_category=sub_category,
            remarks=remarks,
            comments=comments,
        )
    except Exception:
        return ""


def enrich_message_column(
    df: pd.DataFrame,
    *,
    llm_generator: LlmGenerator,
    max_completion_tokens: int = 2048,
    reasoning_effort: str = "minimal",
) -> pd.DataFrame:
    output = ensure_message_column(df)

    for index in output.index.tolist():
        sub_category = row_text(output, index, "Sub Category")
        remarks = row_text(output, index, "Remarks")
        comments = row_text(output, index, COMMENTS_COLUMN)
        if not (comments or remarks):
            output.at[index, MESSAGE_COLUMN] = ""
            continue
        output.at[index, MESSAGE_COLUMN] = build_message_with_repair_sync(
            sub_category=sub_category,
            remarks=remarks,
            comments=comments,
            llm_generator=llm_generator,
            max_completion_tokens=max_completion_tokens,
            reasoning_effort=reasoning_effort,
        )

    return output


async def enrich_message_column_async(
    df: pd.DataFrame,
    *,
    llm_generator: LlmGenerator,
    llm_concurrency: int,
    max_completion_tokens: int = 2048,
    reasoning_effort: str = "minimal",
) -> pd.DataFrame:
    output = ensure_message_column(df)
    rows = [
        (
            index,
            row_text(output, index, "Sub Category"),
            row_text(output, index, "Remarks"),
            row_text(output, index, COMMENTS_COLUMN),
        )
        for index in output.index.tolist()
    ]
    semaphore = asyncio.Semaphore(llm_concurrency)

    async def classify_row(index: int, sub_category: str, remarks: str, comments: str) -> tuple[int, str]:
        if not (comments or remarks):
            return index, ""
        message = await build_message_with_repair_async(
            sub_category=sub_category,
            remarks=remarks,
            comments=comments,
            llm_generator=llm_generator,
            semaphore=semaphore,
            max_completion_tokens=max_completion_tokens,
            reasoning_effort=reasoning_effort,
        )
        return index, message

    tasks = [asyncio.create_task(classify_row(*row)) for row in rows]
    for task in asyncio.as_completed(tasks):
        index, message = await task
        output.at[index, MESSAGE_COLUMN] = message

    return output


def enrich_lower_category_vehicle(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
    max_completion_tokens: int = 2048,
    reasoning_effort: str = "minimal",
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    output = ensure_lower_category_vehicle_columns(df)
    clear_lower_category_vehicle_llm_columns(output)
    failed_booking_ids: list[str] = []

    for index in output.index.tolist():
        booking_id = str(output.at[index, "Booking ID"]).strip()
        if not booking_id:
            continue

        for column, value in build_lower_category_vehicle_enrichment(tracking_bookings, booking_id).items():
            output.at[index, column] = value

        comments = str(output.at[index, COMMENTS_COLUMN]).strip()
        if not comments:
            continue

        prompt = build_lower_category_vehicle_prompt(booking_id=booking_id, comments=comments)
        try:
            response = call_azure_or_custom_sync(
                llm_generator,
                prompt,
                max_completion_tokens,
                reasoning_effort,
            )
            extracted = parse_lower_category_vehicle_response(response)
        except Exception:
            failed_booking_ids.append(booking_id)
            continue

        for column, value in extracted.items():
            output.at[index, column] = value

    return output, build_lower_category_vehicle_warnings(failed_booking_ids)


async def enrich_lower_category_vehicle_async(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
    llm_concurrency: int,
    max_completion_tokens: int = 2048,
    reasoning_effort: str = "minimal",
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    output = ensure_lower_category_vehicle_columns(df)
    clear_lower_category_vehicle_llm_columns(output)
    extraction_targets: list[tuple[int, str, str]] = []

    for index in output.index.tolist():
        booking_id = str(output.at[index, "Booking ID"]).strip()
        if not booking_id:
            continue

        for column, value in build_lower_category_vehicle_enrichment(tracking_bookings, booking_id).items():
            output.at[index, column] = value

        comments = str(output.at[index, COMMENTS_COLUMN]).strip()
        if comments:
            extraction_targets.append((index, booking_id, comments))

    semaphore = asyncio.Semaphore(llm_concurrency)

    async def extract_values(
        index: int,
        booking_id: str,
        comments: str,
    ) -> tuple[str, int, str, dict[str, str] | None]:
        prompt = build_lower_category_vehicle_prompt(booking_id=booking_id, comments=comments)
        try:
            async with semaphore:
                response = await maybe_call_llm(llm_generator, prompt, max_completion_tokens, reasoning_effort)
            return "extracted", index, booking_id, parse_lower_category_vehicle_response(response)
        except Exception:
            return "failed", index, booking_id, None

    tasks = [
        asyncio.create_task(extract_values(index, booking_id, comments))
        for index, booking_id, comments in extraction_targets
    ]
    failed_booking_ids: list[str] = []

    for task in asyncio.as_completed(tasks):
        status, index, booking_id, extracted = await task
        if status == "extracted" and extracted is not None:
            for column, value in extracted.items():
                output.at[index, column] = value
        else:
            failed_booking_ids.append(booking_id)

    return output, build_lower_category_vehicle_warnings(failed_booking_ids)


def clear_lower_category_vehicle_llm_columns(output: pd.DataFrame) -> None:
    output[CUSTOMER_BOOKED_VEHICLE_COLUMN] = ""
    output[CUSTOMER_RECEIVED_VEHICLE_COLUMN] = ""


def build_lower_category_vehicle_warnings(failed_booking_ids: list[str]) -> list[dict[str, Any]]:
    if not failed_booking_ids:
        return []

    return [
        {
            "code": "lower_category_vehicle_extraction_failed",
            "message": (
                f"{len(failed_booking_ids)} Lower Category Vehicle rows could not have booked/received "
                "vehicle values extracted from comments. Processed category files were still produced."
            ),
            "booking_ids": failed_booking_ids,
        }
    ]



def call_azure_or_custom_sync(
    llm_generator: LlmGenerator,
    prompt: str,
    max_completion_tokens: int,
    reasoning_effort: str,
) -> str:
    return call_llm_sync(llm_generator, prompt, max_completion_tokens, reasoning_effort)
