from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.app.agents import AGENT_OUTPUT_COLUMNS, investigate_category_frame, investigate_category_frame_async
from backend.app.domain.cab_delay_enrichment import (
    CAB_DELAY_ENRICHMENT_COLUMNS,
    COMMENTS_COLUMN,
    INCABS_COMMENT_SUMMARY_COLUMN,
    INCABS_INSIGHT_COLUMN,
    PREFERRED_START_TIME_IST_COLUMN,
    build_comment_summary_prompt,
    build_incabs_insight_prompt,
    build_timing_context,
    build_tracking_enrichment,
    call_azure_openai,
    call_azure_openai_async,
    ensure_enrichment_columns,
    find_target_rows,
    first_tracking_row,
)
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
class InsightSummary:
    target_insight_rows: int = 0
    existing_insight_rows: int = 0
    generated_insight_rows: int = 0
    failed_insight_rows: int = 0
    unmatched_insight_rows: int = 0
    target_comment_summary_rows: int = 0
    existing_comment_summary_rows: int = 0
    generated_comment_summary_rows: int = 0
    failed_comment_summary_rows: int = 0
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CategoryProcessingOutcome:
    df: pd.DataFrame
    insight_summary: InsightSummary | None = None
    failed: bool = False
    error: str | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    agent_cases: list[dict[str, Any]] = field(default_factory=list)


def output_columns_for_category(category_name: str) -> list[str]:
    return CATEGORY_PROCESSORS.get(category_name, COMMON_PROCESSOR_SPEC).output_columns


def process_category_batch(
    batch: CategoryBatch,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
) -> CategoryProcessingOutcome:
    base_df = enrich_common_tracking_fields(batch.df, tracking_bookings=tracking_bookings)

    if batch.name == CAB_DELAY_CATEGORY:
        enriched_df, insight_summary = enrich_cab_delay_insights(
            base_df,
            tracking_bookings=tracking_bookings,
            llm_generator=llm_generator,
        )
        enriched_df = enrich_message_column(enriched_df, llm_generator=llm_generator)
        enriched_df, agent_cases = investigate_category_frame(
            enriched_df,
            tracking_bookings=tracking_bookings,
            llm_generator=llm_generator,
        )
        return CategoryProcessingOutcome(
            enriched_df.loc[:, output_columns_for_category(batch.name)].copy(),
            insight_summary,
            agent_cases=agent_cases,
        )

    if batch.name == EXTRA_MONEY_TAKEN_CATEGORY:
        enriched_df = enrich_extra_money_taken_rows(base_df, tracking_bookings=tracking_bookings)
        enriched_df = enrich_message_column(enriched_df, llm_generator=llm_generator)
        enriched_df, agent_cases = investigate_category_frame(
            enriched_df,
            tracking_bookings=tracking_bookings,
            llm_generator=llm_generator,
        )
        return CategoryProcessingOutcome(
            enriched_df.loc[:, output_columns_for_category(batch.name)].copy(),
            agent_cases=agent_cases,
        )

    if batch.name == FULFILLMENT_NOT_DONE_CATEGORY:
        enriched_df = enrich_fulfillment_not_done_rows(base_df, tracking_bookings=tracking_bookings)
        enriched_df = enrich_message_column(enriched_df, llm_generator=llm_generator)
        enriched_df, agent_cases = investigate_category_frame(
            enriched_df,
            tracking_bookings=tracking_bookings,
            llm_generator=llm_generator,
        )
        return CategoryProcessingOutcome(
            enriched_df.loc[:, output_columns_for_category(batch.name)].copy(),
            agent_cases=agent_cases,
        )

    if batch.name == LOWER_CATEGORY_VEHICLE_CATEGORY:
        enriched_df, warnings = enrich_lower_category_vehicle(
            base_df,
            tracking_bookings=tracking_bookings,
            llm_generator=llm_generator,
        )
        enriched_df = enrich_message_column(enriched_df, llm_generator=llm_generator)
        enriched_df, agent_cases = investigate_category_frame(
            enriched_df,
            tracking_bookings=tracking_bookings,
            llm_generator=llm_generator,
        )
        return CategoryProcessingOutcome(
            enriched_df.loc[:, output_columns_for_category(batch.name)].copy(),
            warnings=warnings,
            agent_cases=agent_cases,
        )

    enriched_df = enrich_message_column(base_df, llm_generator=llm_generator)
    enriched_df, agent_cases = investigate_category_frame(
        enriched_df,
        tracking_bookings=tracking_bookings,
        llm_generator=llm_generator,
    )
    return CategoryProcessingOutcome(
        enriched_df.loc[:, COMMON_PROCESSED_OUTPUT_COLUMNS].copy(),
        agent_cases=agent_cases,
    )


async def process_category_batch_async(
    batch: CategoryBatch,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
    llm_concurrency: int,
    on_cab_delay_progress: Callable[[dict[str, int], str], None],
) -> CategoryProcessingOutcome:
    base_df = enrich_common_tracking_fields(batch.df, tracking_bookings=tracking_bookings)

    if batch.name == CAB_DELAY_CATEGORY:
        enriched_df, insight_summary = await enrich_cab_delay_insights_async(
            base_df,
            tracking_bookings=tracking_bookings,
            llm_generator=llm_generator,
            llm_concurrency=llm_concurrency,
            on_progress=on_cab_delay_progress,
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
        )
        return CategoryProcessingOutcome(
            enriched_df.loc[:, output_columns_for_category(batch.name)].copy(),
            insight_summary,
            agent_cases=agent_cases,
        )

    if batch.name == EXTRA_MONEY_TAKEN_CATEGORY:
        enriched_df = await asyncio.to_thread(
            enrich_extra_money_taken_rows,
            base_df,
            tracking_bookings=tracking_bookings,
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
        )
        return CategoryProcessingOutcome(
            enriched_df.loc[:, output_columns_for_category(batch.name)].copy(),
            agent_cases=agent_cases,
        )

    if batch.name == FULFILLMENT_NOT_DONE_CATEGORY:
        enriched_df = await asyncio.to_thread(
            enrich_fulfillment_not_done_rows,
            base_df,
            tracking_bookings=tracking_bookings,
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
        )
        return CategoryProcessingOutcome(
            enriched_df.loc[:, output_columns_for_category(batch.name)].copy(),
            agent_cases=agent_cases,
        )

    if batch.name == LOWER_CATEGORY_VEHICLE_CATEGORY:
        enriched_df, warnings = await enrich_lower_category_vehicle_async(
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
        )
        return CategoryProcessingOutcome(
            enriched_df.loc[:, output_columns_for_category(batch.name)].copy(),
            warnings=warnings,
            agent_cases=agent_cases,
        )

    enriched_df = await enrich_message_column_async(
        base_df,
        llm_generator=llm_generator,
        llm_concurrency=llm_concurrency,
    )
    enriched_df, agent_cases = await investigate_category_frame_async(
        enriched_df,
        tracking_bookings=tracking_bookings,
        llm_generator=llm_generator,
        llm_concurrency=llm_concurrency,
    )
    return CategoryProcessingOutcome(
        enriched_df.loc[:, COMMON_PROCESSED_OUTPUT_COLUMNS].copy(),
        agent_cases=agent_cases,
    )


async def maybe_call_llm(
    llm_generator: LlmGenerator,
    prompt: str,
    max_completion_tokens: int,
    reasoning_effort: str,
) -> str:
    if inspect.iscoroutinefunction(llm_generator):
        return await llm_generator(prompt, max_completion_tokens, reasoning_effort)

    result = await asyncio.to_thread(llm_generator, prompt, max_completion_tokens, reasoning_effort)
    if inspect.isawaitable(result):
        return await result
    return str(result)


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


def enrich_cab_delay_insights(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
    max_completion_tokens: int = 2048,
    reasoning_effort: str = "minimal",
) -> tuple[pd.DataFrame, InsightSummary]:
    output = ensure_enrichment_columns(df)

    for index in output.index.tolist():
        booking_id = str(output.at[index, "Booking ID"]).strip()
        if not booking_id:
            continue
        enrichment = build_tracking_enrichment(tracking_bookings, booking_id)
        for column, value in enrichment.to_columns().items():
            output.at[index, column] = value

    target_mask = find_target_rows(output)
    existing_insight_mask = output[INCABS_INSIGHT_COLUMN].fillna("").astype(str).str.strip().ne("")
    pending_insight_mask = target_mask & ~existing_insight_mask
    summary = InsightSummary(
        target_insight_rows=int(target_mask.sum()),
        existing_insight_rows=int((target_mask & existing_insight_mask).sum()),
    )

    failed_insight_booking_ids: list[str] = []
    failed_summary_booking_ids: list[str] = []
    unmatched_booking_ids: list[str] = []

    for index in output.index[pending_insight_mask].tolist():
        booking_id = str(output.at[index, "Booking ID"]).strip()
        tracking_row = first_tracking_row(tracking_bookings, booking_id)
        if not tracking_row:
            unmatched_booking_ids.append(booking_id)
            continue

        prompt = build_incabs_insight_prompt(booking_id, build_timing_context(tracking_row))
        try:
            output.at[index, INCABS_INSIGHT_COLUMN] = call_azure_or_custom_sync(
                llm_generator,
                prompt,
                max_completion_tokens,
                reasoning_effort,
            )
            summary.generated_insight_rows += 1
        except Exception:
            failed_insight_booking_ids.append(booking_id)

    summary_mask = (
        target_mask
        & output[INCABS_INSIGHT_COLUMN].fillna("").astype(str).str.strip().ne("")
        & output[COMMENTS_COLUMN].fillna("").astype(str).str.strip().ne("")
    )
    existing_summary_mask = output[INCABS_COMMENT_SUMMARY_COLUMN].fillna("").astype(str).str.strip().ne("")
    pending_summary_mask = summary_mask & ~existing_summary_mask
    summary.target_comment_summary_rows = int(summary_mask.sum())
    summary.existing_comment_summary_rows = int((summary_mask & existing_summary_mask).sum())

    for index in output.index[pending_summary_mask].tolist():
        booking_id = str(output.at[index, "Booking ID"]).strip()
        prompt = build_comment_summary_prompt(
            booking_id=booking_id,
            incabs_insight=str(output.at[index, INCABS_INSIGHT_COLUMN]).strip(),
            comments=str(output.at[index, COMMENTS_COLUMN]).strip(),
            preferred_start_time_ist=str(output.at[index, PREFERRED_START_TIME_IST_COLUMN]).strip(),
        )
        try:
            output.at[index, INCABS_COMMENT_SUMMARY_COLUMN] = call_azure_or_custom_sync(
                llm_generator,
                prompt,
                max_completion_tokens,
                reasoning_effort,
            )
            summary.generated_comment_summary_rows += 1
        except Exception:
            failed_summary_booking_ids.append(booking_id)

    add_cab_delay_warnings(summary, unmatched_booking_ids, failed_insight_booking_ids, failed_summary_booking_ids)
    return output, summary


def call_azure_or_custom_sync(
    llm_generator: LlmGenerator,
    prompt: str,
    max_completion_tokens: int,
    reasoning_effort: str,
) -> str:
    if llm_generator is call_azure_openai_async:
        return call_azure_openai(prompt, max_completion_tokens, reasoning_effort)

    result = llm_generator(prompt, max_completion_tokens, reasoning_effort)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return str(result)


async def enrich_cab_delay_insights_async(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
    llm_concurrency: int,
    on_progress: Callable[[dict[str, int], str], None],
    max_completion_tokens: int = 2048,
    reasoning_effort: str = "minimal",
) -> tuple[pd.DataFrame, InsightSummary]:
    output = ensure_enrichment_columns(df)

    for index in output.index.tolist():
        booking_id = str(output.at[index, "Booking ID"]).strip()
        if not booking_id:
            continue
        enrichment = build_tracking_enrichment(tracking_bookings, booking_id)
        for column, value in enrichment.to_columns().items():
            output.at[index, column] = value

    target_mask = find_target_rows(output)
    existing_insight_mask = output[INCABS_INSIGHT_COLUMN].fillna("").astype(str).str.strip().ne("")
    pending_insight_mask = target_mask & ~existing_insight_mask
    summary = InsightSummary(
        target_insight_rows=int(target_mask.sum()),
        existing_insight_rows=int((target_mask & existing_insight_mask).sum()),
    )
    counters = cab_delay_progress_payload(summary)
    on_progress(counters, format_cab_delay_progress(counters))

    failed_insight_booking_ids: list[str] = []
    failed_summary_booking_ids: list[str] = []
    unmatched_booking_ids: list[str] = []
    insight_updates: list[tuple[int, str]] = []
    semaphore = asyncio.Semaphore(llm_concurrency)

    async def generate_insight(index: int) -> tuple[str, int, str, str | None]:
        booking_id = str(output.at[index, "Booking ID"]).strip()
        tracking_row = first_tracking_row(tracking_bookings, booking_id)
        if not tracking_row:
            return "unmatched", index, booking_id, None

        prompt = build_incabs_insight_prompt(booking_id, build_timing_context(tracking_row))
        try:
            async with semaphore:
                value = await maybe_call_llm(llm_generator, prompt, max_completion_tokens, reasoning_effort)
            return "generated", index, booking_id, value
        except Exception:
            return "failed", index, booking_id, None

    insight_tasks = [
        asyncio.create_task(generate_insight(index))
        for index in output.index[pending_insight_mask].tolist()
    ]
    for task in asyncio.as_completed(insight_tasks):
        status, index, booking_id, value = await task
        if status == "generated" and value is not None:
            insight_updates.append((index, value))
            summary.generated_insight_rows += 1
        elif status == "unmatched":
            unmatched_booking_ids.append(booking_id)
        else:
            failed_insight_booking_ids.append(booking_id)
            summary.failed_insight_rows = len(failed_insight_booking_ids)

        counters = cab_delay_progress_payload(summary)
        on_progress(counters, format_cab_delay_progress(counters))

    for index, value in insight_updates:
        output.at[index, INCABS_INSIGHT_COLUMN] = value

    summary_mask = (
        target_mask
        & output[INCABS_INSIGHT_COLUMN].fillna("").astype(str).str.strip().ne("")
        & output[COMMENTS_COLUMN].fillna("").astype(str).str.strip().ne("")
    )
    existing_summary_mask = output[INCABS_COMMENT_SUMMARY_COLUMN].fillna("").astype(str).str.strip().ne("")
    pending_summary_mask = summary_mask & ~existing_summary_mask
    summary.target_comment_summary_rows = int(summary_mask.sum())
    summary.existing_comment_summary_rows = int((summary_mask & existing_summary_mask).sum())
    counters = cab_delay_progress_payload(summary)
    on_progress(counters, format_cab_delay_progress(counters))

    async def generate_summary(index: int) -> tuple[str, int, str, str | None]:
        booking_id = str(output.at[index, "Booking ID"]).strip()
        prompt = build_comment_summary_prompt(
            booking_id=booking_id,
            incabs_insight=str(output.at[index, INCABS_INSIGHT_COLUMN]).strip(),
            comments=str(output.at[index, COMMENTS_COLUMN]).strip(),
            preferred_start_time_ist=str(output.at[index, PREFERRED_START_TIME_IST_COLUMN]).strip(),
        )
        try:
            async with semaphore:
                value = await maybe_call_llm(llm_generator, prompt, max_completion_tokens, reasoning_effort)
            return "generated", index, booking_id, value
        except Exception:
            return "failed", index, booking_id, None

    summary_updates: list[tuple[int, str]] = []
    summary_tasks = [
        asyncio.create_task(generate_summary(index))
        for index in output.index[pending_summary_mask].tolist()
    ]
    for task in asyncio.as_completed(summary_tasks):
        status, index, booking_id, value = await task
        if status == "generated" and value is not None:
            summary_updates.append((index, value))
            summary.generated_comment_summary_rows += 1
        else:
            failed_summary_booking_ids.append(booking_id)
            summary.failed_comment_summary_rows = len(failed_summary_booking_ids)

        counters = cab_delay_progress_payload(summary)
        on_progress(counters, format_cab_delay_progress(counters))

    for index, value in summary_updates:
        output.at[index, INCABS_COMMENT_SUMMARY_COLUMN] = value

    summary.failed_insight_rows = len(failed_insight_booking_ids)
    summary.failed_comment_summary_rows = len(failed_summary_booking_ids)
    add_cab_delay_warnings(summary, unmatched_booking_ids, failed_insight_booking_ids, failed_summary_booking_ids)
    counters = cab_delay_progress_payload(summary)
    on_progress(counters, format_cab_delay_progress(counters))
    return output, summary


def cab_delay_progress_payload(summary: InsightSummary | None = None) -> dict[str, int]:
    summary = summary or InsightSummary()
    return {
        "target_insight_rows": summary.target_insight_rows,
        "generated_insight_rows": summary.generated_insight_rows,
        "failed_insight_rows": summary.failed_insight_rows,
        "target_comment_summary_rows": summary.target_comment_summary_rows,
        "generated_comment_summary_rows": summary.generated_comment_summary_rows,
        "failed_comment_summary_rows": summary.failed_comment_summary_rows,
    }


def format_cab_delay_progress(counters: dict[str, int]) -> str:
    insight_done = counters["generated_insight_rows"] + counters["failed_insight_rows"]
    summary_done = counters["generated_comment_summary_rows"] + counters["failed_comment_summary_rows"]
    return (
        f"Insights {insight_done}/{counters['target_insight_rows']} | "
        f"Summaries {summary_done}/{counters['target_comment_summary_rows']}"
    )


def add_cab_delay_warnings(
    summary: InsightSummary,
    unmatched_booking_ids: list[str],
    failed_insight_booking_ids: list[str],
    failed_summary_booking_ids: list[str],
) -> None:
    if unmatched_booking_ids:
        summary.unmatched_insight_rows = len(unmatched_booking_ids)
        summary.warnings.append(
            {
                "code": "insight_tracking_missing",
                "message": (
                    f"{len(unmatched_booking_ids)} cab-delay rows could not be enriched "
                    "because tracking evidence was unavailable."
                ),
                "booking_ids": unmatched_booking_ids,
            }
        )

    if failed_insight_booking_ids:
        summary.failed_insight_rows = len(failed_insight_booking_ids)
        summary.warnings.append(
            {
                "code": "azure_insight_failed",
                "message": (
                    f"{len(failed_insight_booking_ids)} cab-delay insights could not be generated. "
                    "Processed category files were still produced."
                ),
                "booking_ids": failed_insight_booking_ids,
            }
        )

    if failed_summary_booking_ids:
        summary.failed_comment_summary_rows = len(failed_summary_booking_ids)
        summary.warnings.append(
            {
                "code": "azure_comment_summary_failed",
                "message": (
                    f"{len(failed_summary_booking_ids)} Incabs/comment summaries could not be generated. "
                    "Processed category files were still produced."
                ),
                "booking_ids": failed_summary_booking_ids,
            }
        )
