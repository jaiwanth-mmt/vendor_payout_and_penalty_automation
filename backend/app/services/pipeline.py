from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.agents.orchestrator import (
    build_agent_progress,
    build_case_counts,
    build_portfolio_summary,
    build_portfolio_summary_async,
    investigate_category_frame_async,
)
from backend.app.domain.cab_delay_enrichment import call_azure_openai_async, first_tracking_row, read_tracking_data
from backend.app.domain.category_processors import (
    CAB_DELAY_CATEGORY,
    CAB_DELAY_OUTPUT_COLUMNS,
    CATEGORY_PROCESSORS,
    COMMON_PROCESSED_BASE_COLUMNS,
    COMMON_PROCESSED_OUTPUT_COLUMNS,
    EXTRA_MONEY_TAKEN_CATEGORY,
    EXTRA_MONEY_TAKEN_OUTPUT_COLUMNS,
    FULFILLMENT_NOT_DONE_CATEGORY,
    FULFILLMENT_NOT_DONE_OUTPUT_COLUMNS,
    LOWER_CATEGORY_VEHICLE_CATEGORY,
    LOWER_CATEGORY_VEHICLE_OUTPUT_COLUMNS,
    CategoryProcessingOutcome,
    CategoryProcessorSpec,
    InsightSummary,
    LlmGenerator,
    add_cab_delay_warnings,
    append_unique_columns,
    cab_delay_progress_payload,
    call_azure_or_custom_sync,
    clear_lower_category_vehicle_llm_columns,
    enrich_cab_delay_insights,
    enrich_cab_delay_insights_async,
    enrich_lower_category_vehicle,
    enrich_lower_category_vehicle_async,
    enrich_message_column,
    enrich_message_column_async,
    format_cab_delay_progress,
    maybe_call_llm,
    output_columns_for_category,
    process_category_batch,
    process_category_batch_async,
    row_text,
)
from backend.app.domain.penalty_dataset import (
    DEFAULT_DATE_COLUMN,
    FINAL_OUTPUT_COLUMNS,
    clean_output_text_columns,
    consolidate_duplicate_bookings,
    filter_by_input_date,
    keep_only_carbd_loss_dept,
    normalize_numeric_columns,
    read_input_file,
    remove_zero_recoverable_rows,
    shape_loss_recovery_output,
)
from backend.app.domain.subcategories import (
    CategoryBatch,
    build_unique_slug_map,
    normalize_subcategory_name,
    slugify,
    split_by_subcategory,
)
from backend.app.domain.tracking_common import enrich_common_tracking_fields
from backend.app.services.package_builder import (
    AGENT_AUDIT_FILENAME,
    AGENT_SUMMARY_FILENAME,
    FINAL_EXPORT_COLUMNS,
    FINAL_EXPORT_COLUMN_MAP,
    FINAL_OUTPUT_FILENAME,
    MANIFEST_FILENAME,
    PACKAGE_FILENAME,
    PREPARED_CATEGORY_ROOT,
    PROCESSED_CATEGORY_ROOT,
    REVIEW_QUEUE_FILENAME,
    build_agent_audit_dataframe,
    build_category_output_payload,
    build_final_output_dataframe,
    build_final_output_summary,
    build_manifest,
    build_review_queue_dataframe,
    write_package_zip,
    write_workbook,
)


DEFAULT_CATEGORY_PROCESSING_CONCURRENCY = 4
DEFAULT_LLM_CONCURRENCY = 3
REQUIRED_INPUT_COLUMNS = {
    "Booking ID",
    "Booking Date",
    "Booking Month",
    "Loss Dept",
    "Sub Category",
    "Loss Amount",
    "Recoverable",
    "Remarks",
    DEFAULT_DATE_COLUMN,
}

ProgressCallback = Callable[[str, str], None]
StepUnitsCallback = Callable[[str, int, int, str], None]
WarningCallback = Callable[[dict[str, Any]], None]
CategoryProgressInitCallback = Callable[[list[dict[str, Any]]], None]
CategoryProgressCallback = Callable[[str, dict[str, Any]], None]


@dataclass
class PipelineResult:
    metrics: dict[str, Any]
    warnings: list[dict[str, Any]]
    category_outputs: list[dict[str, Any]]
    package_path: Path
    manifest_path: Path
    final_output_path: Path
    final_output: dict[str, Any]
    agent_audit_path: Path
    review_queue_path: Path
    agent_summary_path: Path
    agent_summary: dict[str, Any]
    case_counts: dict[str, int]
    agent_progress: list[dict[str, Any]]
    agent_cases: list[dict[str, Any]]


def noop_step_units(_step_id: str, _completed_units: int, _total_units: int, _message: str) -> None:
    return None


def noop_category_progress_init(_categories: list[dict[str, Any]]) -> None:
    return None


def noop_category_progress(_slug: str, _update: dict[str, Any]) -> None:
    return None


def process_uploaded_workbook(
    *,
    input_path: Path,
    tracking_json_path: Path,
    output_package_path: Path,
    approval_date: str,
    on_step_start: ProgressCallback,
    on_step_complete: ProgressCallback,
    on_warning: WarningCallback,
    on_step_progress: StepUnitsCallback | None = None,
    on_category_progress_initialized: CategoryProgressInitCallback | None = None,
    on_category_progress: CategoryProgressCallback | None = None,
    reason_generator: LlmGenerator | None = None,
    category_processing_concurrency: int | None = None,
    llm_concurrency: int | None = None,
    cab_delay_llm_concurrency: int | None = None,
) -> PipelineResult:
    return asyncio.run(
        process_uploaded_workbook_async(
            input_path=input_path,
            tracking_json_path=tracking_json_path,
            output_package_path=output_package_path,
            approval_date=approval_date,
            on_step_start=on_step_start,
            on_step_complete=on_step_complete,
            on_warning=on_warning,
            on_step_progress=on_step_progress,
            on_category_progress_initialized=on_category_progress_initialized,
            on_category_progress=on_category_progress,
            reason_generator=reason_generator,
            category_processing_concurrency=category_processing_concurrency,
            llm_concurrency=llm_concurrency,
            cab_delay_llm_concurrency=cab_delay_llm_concurrency,
        )
    )


async def process_uploaded_workbook_async(
    *,
    input_path: Path,
    tracking_json_path: Path,
    output_package_path: Path,
    approval_date: str,
    on_step_start: ProgressCallback,
    on_step_complete: ProgressCallback,
    on_warning: WarningCallback,
    on_step_progress: StepUnitsCallback | None = None,
    on_category_progress_initialized: CategoryProgressInitCallback | None = None,
    on_category_progress: CategoryProgressCallback | None = None,
    reason_generator: LlmGenerator | None = None,
    category_processing_concurrency: int | None = None,
    llm_concurrency: int | None = None,
    cab_delay_llm_concurrency: int | None = None,
) -> PipelineResult:
    warnings: list[dict[str, Any]] = []
    step_progress = on_step_progress or noop_step_units
    init_category_progress = on_category_progress_initialized or noop_category_progress_init
    update_category_progress = on_category_progress or noop_category_progress
    active_llm_generator: LlmGenerator = reason_generator or call_azure_openai_async
    category_concurrency = positive_int(
        category_processing_concurrency,
        env_name="CATEGORY_PROCESSING_CONCURRENCY",
        default=DEFAULT_CATEGORY_PROCESSING_CONCURRENCY,
    )
    llm_concurrency_limit = positive_int_from_env(
        llm_concurrency if llm_concurrency is not None else cab_delay_llm_concurrency,
        env_names=("LLM_CONCURRENCY", "CAB_DELAY_LLM_CONCURRENCY"),
        default=DEFAULT_LLM_CONCURRENCY,
    )
    job_dir = output_package_path.parent
    prepared_dir = job_dir / PREPARED_CATEGORY_ROOT
    processed_dir = job_dir / PROCESSED_CATEGORY_ROOT
    manifest_path = job_dir / MANIFEST_FILENAME

    def emit_warning(warning: dict[str, Any]) -> None:
        warnings.append(warning)
        on_warning(warning)

    on_step_start("workbook_parsed", "Reading uploaded QlikSense workbook")
    raw_df = await asyncio.to_thread(read_input_file, input_path, 0)
    validate_input_columns(raw_df)
    on_step_complete("workbook_parsed", f"{len(raw_df):,} workbook rows read")

    on_step_start("date_filtered", f"Filtering {DEFAULT_DATE_COLUMN} for {approval_date}")
    date_filtered_df = filter_by_input_date(raw_df, DEFAULT_DATE_COLUMN, approval_date)
    on_step_complete("date_filtered", f"{len(date_filtered_df):,} rows match the selected date")

    on_step_start("filters_applied", "Keeping CARBD rows with non-zero recoverable amount")
    carbd_df = keep_only_carbd_loss_dept(date_filtered_df)
    normalized_df = normalize_numeric_columns(
        carbd_df,
        ["Loss Amount", "Loss Amount (INR)", "Recoverable", "Recoverable (INR)"],
    )
    recoverable_df = remove_zero_recoverable_rows(normalized_df)
    on_step_complete(
        "filters_applied",
        f"{len(recoverable_df):,} rows remain after CARBD and recoverable filters",
    )

    on_step_start("duplicates_consolidated", "Merging repeated Booking IDs")
    consolidated_df = consolidate_duplicate_bookings(recoverable_df)
    prepared_df = shape_prepared_output(consolidated_df)
    on_step_complete("duplicates_consolidated", f"{len(prepared_df):,} unique bookings prepared")

    on_step_start("categories_split", "Splitting prepared rows by subcategory")
    category_batches = split_by_subcategory(prepared_df)
    prepared_dir.mkdir(parents=True, exist_ok=True)
    await asyncio.gather(
        *[
            asyncio.to_thread(write_workbook, batch.df, prepared_dir / f"{batch.slug}.xlsx")
            for batch in category_batches
        ]
    )
    init_category_progress(build_initial_category_progress(category_batches))
    on_step_complete(
        "categories_split",
        f"{len(category_batches):,} subcategory files prepared",
    )

    on_step_start("tracking_matched", "Matching bookings with bundled tracking data")
    if not tracking_json_path.exists():
        raise FileNotFoundError(f"Tracking JSON not found: {tracking_json_path}")

    tracking_bookings = await asyncio.to_thread(read_tracking_data, tracking_json_path)
    booking_ids = prepared_df["Booking ID"].fillna("").astype(str).str.strip().tolist()
    matched_booking_ids = [
        booking_id
        for booking_id in booking_ids
        if first_tracking_row(tracking_bookings, booking_id)
    ]
    matched_booking_id_set = set(matched_booking_ids)
    unmatched_booking_ids = [
        booking_id
        for booking_id in booking_ids
        if booking_id and booking_id not in matched_booking_id_set
    ]
    if unmatched_booking_ids:
        emit_warning(
            {
                "code": "tracking_not_found",
                "message": f"{len(unmatched_booking_ids)} bookings were not found in tracking JSON.",
                "booking_ids": unmatched_booking_ids,
            }
        )
    on_step_complete("tracking_matched", f"{len(matched_booking_ids):,} bookings matched tracking data")

    on_step_start("categories_processed", "Processing each subcategory file independently")
    processed_dir.mkdir(parents=True, exist_ok=True)
    step_progress(
        "categories_processed",
        0,
        len(category_batches),
        f"0 of {len(category_batches)} categories processed",
    )

    category_outputs: list[dict[str, Any] | None] = [None] * len(category_batches)
    processed_category_frames: list[pd.DataFrame | None] = [None] * len(category_batches)
    agent_cases_by_category: list[list[dict[str, Any]] | None] = [None] * len(category_batches)
    cab_delay_summary = InsightSummary()
    completed_categories = 0

    semaphore = asyncio.Semaphore(category_concurrency)
    tasks = [
        asyncio.create_task(
            process_category_for_package(
                index=index,
                batch=batch,
                semaphore=semaphore,
                tracking_bookings=tracking_bookings,
                llm_generator=active_llm_generator,
                llm_concurrency=llm_concurrency_limit,
                prepared_dir=prepared_dir,
                processed_dir=processed_dir,
                root_dir=job_dir,
                on_category_progress=update_category_progress,
            )
        )
        for index, batch in enumerate(category_batches)
    ]

    for completed_task in asyncio.as_completed(tasks):
        index, _batch, outcome, category_output, category_warnings = await completed_task
        category_outputs[index] = category_output
        processed_category_frames[index] = outcome.df
        agent_cases_by_category[index] = outcome.agent_cases
        if outcome.insight_summary:
            cab_delay_summary = outcome.insight_summary
        for warning in category_warnings:
            emit_warning(warning)

        completed_categories += 1
        step_progress(
            "categories_processed",
            completed_categories,
            len(category_batches),
            f"{completed_categories} of {len(category_batches)} categories processed",
        )

    finalized_category_outputs = [category for category in category_outputs if category is not None]
    on_step_complete(
        "categories_processed",
        f"{sum(category['row_count'] for category in finalized_category_outputs):,} rows processed across categories",
    )

    on_step_start("package_prepared", "Packaging subcategory workbooks")
    final_output_path = job_dir / FINAL_OUTPUT_FILENAME
    agent_audit_path = job_dir / AGENT_AUDIT_FILENAME
    review_queue_path = job_dir / REVIEW_QUEUE_FILENAME
    agent_summary_path = job_dir / AGENT_SUMMARY_FILENAME
    agent_cases = [
        case
        for category_cases in agent_cases_by_category
        if category_cases is not None
        for case in category_cases
    ]
    agent_summary = await build_portfolio_summary_async(
        agent_cases,
        llm_generator=active_llm_generator,
        llm_concurrency=llm_concurrency_limit,
    )
    case_counts = build_case_counts(agent_cases)
    agent_progress = build_agent_progress(agent_cases, agent_summary=agent_summary)
    final_output_df = build_final_output_dataframe(
        [frame for frame in processed_category_frames if frame is not None]
    )
    await asyncio.to_thread(write_workbook, final_output_df, final_output_path)
    await asyncio.to_thread(write_workbook, build_agent_audit_dataframe(agent_cases), agent_audit_path)
    await asyncio.to_thread(write_workbook, build_review_queue_dataframe(agent_cases), review_queue_path)
    await asyncio.to_thread(
        agent_summary_path.write_text,
        json.dumps(agent_summary, indent=2, ensure_ascii=False),
        "utf-8",
    )
    final_output = build_final_output_summary(
        final_output_path=final_output_path,
        final_output_df=final_output_df,
        root_dir=job_dir,
    )
    agent_artifacts = {
        "agent_audit": agent_audit_path.relative_to(job_dir).as_posix(),
        "review_queue": review_queue_path.relative_to(job_dir).as_posix(),
        "agent_summary": agent_summary_path.relative_to(job_dir).as_posix(),
    }
    manifest = build_manifest(
        approval_date=approval_date,
        raw_rows=len(raw_df),
        prepared_rows=len(prepared_df),
        categories=finalized_category_outputs,
        final_output=final_output,
        agent_summary=agent_summary,
        agent_artifacts=agent_artifacts,
    )
    await asyncio.to_thread(manifest_path.write_text, json.dumps(manifest, indent=2), "utf-8")
    await asyncio.to_thread(
        write_package_zip,
        output_package_path=output_package_path,
        manifest_path=manifest_path,
        categories=finalized_category_outputs,
        final_output_path=final_output_path,
        root_dir=job_dir,
        agent_artifact_paths=[agent_audit_path, review_queue_path, agent_summary_path],
    )
    on_step_complete(
        "package_prepared",
        f"ZIP package ready with {len(finalized_category_outputs):,} categories and final XLSX",
    )

    metrics = {
        "raw_rows": len(raw_df),
        "date_filtered_rows": len(date_filtered_df),
        "carbd_rows": len(carbd_df),
        "recoverable_rows": len(recoverable_df),
        "prepared_rows": len(prepared_df),
        "category_count": len(finalized_category_outputs),
        "final_output_rows": len(final_output_df),
        "tracking_matched_bookings": len(matched_booking_ids),
        "tracking_unmatched_bookings": len(unmatched_booking_ids),
        "target_insight_rows": cab_delay_summary.target_insight_rows,
        "existing_insight_rows": cab_delay_summary.existing_insight_rows,
        "generated_insight_rows": cab_delay_summary.generated_insight_rows,
        "failed_insight_rows": cab_delay_summary.failed_insight_rows,
        "target_comment_summary_rows": cab_delay_summary.target_comment_summary_rows,
        "existing_comment_summary_rows": cab_delay_summary.existing_comment_summary_rows,
        "generated_comment_summary_rows": cab_delay_summary.generated_comment_summary_rows,
        "failed_comment_summary_rows": cab_delay_summary.failed_comment_summary_rows,
        "agent_total_cases": case_counts["total_cases"],
        "agent_auto_ready_cases": case_counts["auto_ready"],
        "agent_needs_review_cases": case_counts["needs_review"],
        "agent_missing_evidence_cases": case_counts["missing_evidence"],
        "agent_contradiction_cases": case_counts["contradiction"],
        "agent_failed_cases": case_counts["failed"],
        "agent_total_recoverable_amount": agent_summary["total_recoverable_amount"],
        "agent_high_confidence_recoverable_amount": agent_summary["high_confidence_recoverable_amount"],
    }
    return PipelineResult(
        metrics=metrics,
        warnings=warnings,
        category_outputs=finalized_category_outputs,
        package_path=output_package_path,
        manifest_path=manifest_path,
        final_output_path=final_output_path,
        final_output=final_output,
        agent_audit_path=agent_audit_path,
        review_queue_path=review_queue_path,
        agent_summary_path=agent_summary_path,
        agent_summary=agent_summary,
        case_counts=case_counts,
        agent_progress=agent_progress,
        agent_cases=agent_cases,
    )


def positive_int(explicit_value: int | None, *, env_name: str, default: int) -> int:
    return positive_int_from_env(explicit_value, env_names=(env_name,), default=default)


def positive_int_from_env(explicit_value: int | None, *, env_names: tuple[str, ...], default: int) -> int:
    if explicit_value is not None:
        return max(1, explicit_value)

    raw_value = ""
    for env_name in env_names:
        raw_value = os.getenv(env_name, "").strip()
        if raw_value:
            break
    if not raw_value:
        return default

    try:
        return max(1, int(raw_value))
    except ValueError:
        return default


def validate_input_columns(df: pd.DataFrame) -> None:
    missing_columns = sorted(REQUIRED_INPUT_COLUMNS.difference(df.columns))
    if missing_columns:
        raise ValueError(f"Uploaded workbook is missing required columns: {', '.join(missing_columns)}")


def shape_prepared_output(df: pd.DataFrame) -> pd.DataFrame:
    cleaned_df = clean_output_text_columns(df)
    shaped_df = shape_loss_recovery_output(cleaned_df)
    return shaped_df.loc[:, FINAL_OUTPUT_COLUMNS].copy()


def shape_final_output(df: pd.DataFrame) -> pd.DataFrame:
    return shape_prepared_output(df)


def build_initial_category_progress(category_batches: list[CategoryBatch]) -> list[dict[str, Any]]:
    return [
        {
            "name": batch.name,
            "slug": batch.slug,
            "row_count": len(batch.df),
            "cab_delay": cab_delay_progress_payload() if batch.name == CAB_DELAY_CATEGORY else None,
        }
        for batch in category_batches
    ]


async def process_category_for_package(
    *,
    index: int,
    batch: CategoryBatch,
    semaphore: asyncio.Semaphore,
    tracking_bookings: dict[str, Any],
    llm_generator: LlmGenerator,
    llm_concurrency: int,
    prepared_dir: Path,
    processed_dir: Path,
    root_dir: Path,
    on_category_progress: CategoryProgressCallback,
) -> tuple[int, CategoryBatch, CategoryProcessingOutcome, dict[str, Any], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []

    async with semaphore:
        on_category_progress(
            batch.slug,
            {"status": "running", "message": f"Processing {len(batch.df):,} rows"},
        )
        try:
            outcome = await process_category_batch_async(
                batch,
                tracking_bookings=tracking_bookings,
                llm_generator=llm_generator,
                llm_concurrency=llm_concurrency,
                on_cab_delay_progress=lambda counters, message: on_category_progress(
                    batch.slug,
                    {"message": message, "cab_delay": counters},
                ),
            )
        except Exception as error:
            fallback_df = enrich_common_tracking_fields(batch.df, tracking_bookings=tracking_bookings)
            fallback_df = await enrich_message_column_async(
                fallback_df,
                llm_generator=llm_generator,
                llm_concurrency=llm_concurrency,
            )
            fallback_df, agent_cases = await investigate_category_frame_async(
                fallback_df,
                tracking_bookings=tracking_bookings,
                llm_generator=llm_generator,
                llm_concurrency=llm_concurrency,
            )
            outcome = CategoryProcessingOutcome(
                df=fallback_df.loc[:, COMMON_PROCESSED_OUTPUT_COLUMNS].copy(),
                failed=True,
                error=str(error),
                agent_cases=agent_cases,
            )
            warnings.append(
                {
                    "code": "category_processing_failed",
                    "message": (
                        f"{batch.name} processing failed; a pass-through processed workbook was still produced."
                    ),
                    "booking_ids": batch.df["Booking ID"].fillna("").astype(str).str.strip().tolist(),
                }
            )

        prepared_path = prepared_dir / f"{batch.slug}.xlsx"
        processed_path = processed_dir / f"{batch.slug}.xlsx"
        await asyncio.to_thread(write_workbook, outcome.df, processed_path)
        category_output = build_category_output_payload(
            name=batch.name,
            slug=batch.slug,
            prepared_path=prepared_path,
            processed_path=processed_path,
            processed_df=outcome.df,
            root_dir=root_dir,
            failed=outcome.failed,
            error=outcome.error,
        )

        if outcome.insight_summary:
            warnings.extend(outcome.insight_summary.warnings)
        warnings.extend(outcome.warnings)

        status = "failed" if outcome.failed else "completed"
        message = outcome.error if outcome.failed else f"Processed {len(outcome.df):,} rows"
        on_category_progress(batch.slug, {"status": status, "message": message})
        return index, batch, outcome, category_output, warnings
