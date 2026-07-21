from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from backend.app.agents.evidence import EvidenceToolset
from backend.app.agents.models import AGENT_OUTPUT_COLUMNS, AgentTraceStep, ClaimCase, clean_number, clean_text
from backend.app.agents.portfolio import (
    UNKNOWN_VENDOR_NAME,
    VENDOR_NAME_COLUMN,
    build_case_counts,
    build_portfolio_summary,
    build_portfolio_summary_async,
    build_vendor_penalty_analysis,
    count_cases,
)
from backend.app.agents.source_alignment import build_source_alignment_async
from backend.app.agents.specialists import (
    llm_error_label,
    run_judge_agent,
    run_judge_agent_async,
    run_specialist_agent,
    run_specialist_agent_async,
)
from backend.app.agents.llm import AgentLlmGenerator
from backend.app.domain.complaint_message import MESSAGE_COLUMN


COMMENTS_COLUMN = "comments"


def build_claim_case(row: pd.Series, *, row_index: int) -> ClaimCase:
    vendor_name = clean_text(row.get(VENDOR_NAME_COLUMN)) or UNKNOWN_VENDOR_NAME
    return ClaimCase(
        booking_id=clean_text(row.get("Booking ID")),
        sub_category=clean_text(row.get("Sub Category")) or "Uncategorized",
        remarks=clean_text(row.get("Remarks")),
        recoverable_amount=clean_number(row.get("Recoverable")),
        row_index=row_index,
        comments=clean_text(row.get(COMMENTS_COLUMN)),
        message=clean_text(row.get(MESSAGE_COLUMN)),
        vendor_name=vendor_name,
    )


def investigate_category_frame(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: AgentLlmGenerator | None = None,
    llm_concurrency: int = 1,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    if llm_generator is not None:
        return asyncio.run(
            investigate_category_frame_async(
                df,
                tracking_bookings=tracking_bookings,
                llm_generator=llm_generator,
                llm_concurrency=llm_concurrency,
            )
        )

    _ = tracking_bookings
    output = ensure_agent_columns(df)
    evidence_tools = EvidenceToolset()
    cases: list[ClaimCase] = []

    for position, index in enumerate(output.index.tolist()):
        case = build_claim_case(output.loc[index], row_index=position)
        case.trace.append(
            AgentTraceStep(
                agent="Intake Agent",
                action="normalize_claim_case",
                status="completed",
                summary=f"Created claim case for booking {case.booking_id or 'unknown'} in {case.sub_category}.",
            )
        )
        evidence, trace = evidence_tools.gather_for_case(case)
        case.evidence.extend(evidence)
        case.trace.extend(trace)
        run_specialist_agent(case)
        run_judge_agent(case)
        cases.append(case)

        apply_case_result_to_output(output, index, case)

    return output, [case.to_dict() for case in cases]


async def investigate_category_frame_async(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: AgentLlmGenerator | None,
    llm_concurrency: int,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    _ = tracking_bookings
    output = ensure_agent_columns(df)
    evidence_tools = EvidenceToolset()
    semaphore = asyncio.Semaphore(max(1, llm_concurrency))
    indexes = output.index.tolist()
    cases: list[ClaimCase | None] = [None] * len(indexes)

    async def investigate_one(position: int, index: Any) -> tuple[int, Any, ClaimCase]:
        case = build_claim_case(output.loc[index], row_index=position)
        case.trace.append(
            AgentTraceStep(
                agent="Intake Agent",
                action="normalize_claim_case",
                status="completed",
                summary=f"Created claim case for booking {case.booking_id or 'unknown'} in {case.sub_category}.",
            )
        )
        if llm_generator is not None:
            case.source_analysis = (
                await build_source_alignment_async(case, llm_generator=llm_generator, semaphore=semaphore)
            ).to_dict()
        evidence, trace = evidence_tools.gather_for_case(case)
        case.evidence.extend(evidence)
        case.trace.extend(trace)
        await run_specialist_agent_async(case, llm_generator=llm_generator, semaphore=semaphore)
        await run_judge_agent_async(case, llm_generator=llm_generator, semaphore=semaphore)
        return position, index, case

    tasks = [asyncio.create_task(investigate_one(position, index)) for position, index in enumerate(indexes)]
    for task in asyncio.as_completed(tasks):
        position, index, case = await task
        cases[position] = case
        apply_case_result_to_output(output, index, case)

    ordered_cases = [case for case in cases if case is not None]
    return output, [case.to_dict() for case in ordered_cases]


def ensure_agent_columns(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    if MESSAGE_COLUMN not in output.columns:
        output[MESSAGE_COLUMN] = pd.Series([""] * len(output), index=output.index, dtype=object)
    for column in AGENT_OUTPUT_COLUMNS:
        if column not in output.columns:
            output[column] = pd.Series([""] * len(output), index=output.index, dtype=object)
        else:
            output[column] = output[column].astype(object)
    return output


def apply_case_result_to_output(output: pd.DataFrame, index: Any, case: ClaimCase) -> None:
    for column, value in case.to_agent_columns().items():
        output.at[index, column] = value



def review_queue_row(case: dict[str, Any]) -> dict[str, Any]:
    decision = case.get("final_decision") or {}
    source_analysis = case.get("source_analysis") or {}
    return {
        "booking_id": case.get("booking_id", ""),
        "sub_category": case.get("sub_category", ""),
        "message": case.get("message", ""),
        "recoverable_amount": case.get("recoverable_amount", 0),
        "review_status": case.get("review_status", "failed"),
        "decision": decision.get("decision", ""),
        "confidence": decision.get("confidence", 0),
        "recommended_action": decision.get("recommended_action", ""),
        "review_reason": decision.get("review_reason", ""),
        "rationale": decision.get("rationale", ""),
        "source_used": source_analysis.get("source_label", ""),
        "source_categories": join_categories(source_analysis.get("source_categories", [])),
        "row_categories": join_categories(source_analysis.get("row_categories", [])),
        "source_alignment_status": source_analysis.get("status", ""),
        "source_alignment_reason": source_analysis.get("reason", ""),
        "evidence_ids": ", ".join(decision.get("evidence_ids", [])),
    }


def build_agent_progress(
    cases: list[dict[str, Any]],
    *,
    agent_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    total = len(cases)
    intake_missing_booking_ids = count_cases(cases, lambda case: not clean_text(case.get("booking_id")))
    evidence_error_cases = count_cases(cases, lambda case: any_evidence_status(case, "error"))
    evidence_missing_cases = count_cases(cases, lambda case: case.get("review_status") == "missing_evidence")
    missing_specialist_cases = count_cases(cases, lambda case: not case.get("specialist_decision"))
    specialist_error_cases = count_cases(
        cases,
        lambda case: bool((case.get("specialist_decision") or {}).get("llm_error")),
    )
    specialist_review_cases = count_cases(
        cases,
        lambda case: (case.get("specialist_decision") or {}).get("review_status") != "auto_ready",
    )
    missing_judge_cases = count_cases(cases, lambda case: not case.get("judge_decision"))
    judge_failed_cases = count_cases(cases, lambda case: case.get("review_status") == "failed")
    judge_review_cases = count_cases(
        cases,
        lambda case: case.get("review_status") in {"needs_review", "missing_evidence", "contradiction"},
    )
    portfolio_error = clean_text((agent_summary or {}).get("portfolio_llm_error"))

    return [
        progress_item(
            "Intake Agent",
            total=total,
            completed=total,
            status="warning" if intake_missing_booking_ids else "completed",
            message=(
                f"Intake completed for {total} cases; {intake_missing_booking_ids} missing booking IDs"
                if intake_missing_booking_ids
                else f"Intake completed for {total} cases"
            ),
        ),
        progress_item(
            "Evidence Retrieval Agent",
            total=total,
            completed=total,
            status="failed" if evidence_error_cases else "warning" if evidence_missing_cases else "completed",
            message=(
                f"Source selection found {evidence_error_cases} error cases and {evidence_missing_cases} missing-source cases"
                if evidence_error_cases
                else f"Source selection found {evidence_missing_cases} missing-source cases"
                if evidence_missing_cases
                else f"Source selection completed for {total} cases"
            ),
        ),
        progress_item(
            "Category Specialist Agents",
            total=total,
            completed=total - missing_specialist_cases,
            status=(
                "failed"
                if missing_specialist_cases
                else "warning"
                if specialist_error_cases or specialist_review_cases
                else "completed"
            ),
            message=(
                f"Specialists failed for {missing_specialist_cases} cases"
                if missing_specialist_cases
                else f"Specialists routed {specialist_review_cases} cases to review; {specialist_error_cases} used LLM fallback"
                if specialist_error_cases or specialist_review_cases
                else f"Specialists completed for {total} cases"
            ),
        ),
        progress_item(
            "Judge Agent",
            total=total,
            completed=total - missing_judge_cases,
            status=(
                "failed"
                if missing_judge_cases or judge_failed_cases
                else "warning"
                if judge_review_cases
                else "completed"
            ),
            message=(
                f"Judge failed for {missing_judge_cases + judge_failed_cases} cases"
                if missing_judge_cases or judge_failed_cases
                else f"Judge routed {judge_review_cases} cases to review"
                if judge_review_cases
                else f"Judge approved {total} cases"
            ),
        ),
        progress_item(
            "Portfolio Summary Agent",
            total=total,
            completed=total,
            status="warning" if portfolio_error else "completed",
            message=(
                f"Portfolio summary used fallback: {portfolio_error}"
                if portfolio_error
                else f"Portfolio summary completed for {total} cases"
            ),
        ),
        progress_item(
            "Vendor Penalty Analysis Agent",
            total=total,
            completed=total,
            status="completed",
            message=f"Vendor penalty analysis completed for {total} cases",
        ),
    ]


def progress_item(agent: str, *, total: int, completed: int, status: str, message: str) -> dict[str, Any]:
    return {
        "agent": agent,
        "status": status,
        "completed_units": max(0, completed),
        "total_units": total,
        "message": message,
    }


def count_cases(cases: list[dict[str, Any]], predicate) -> int:
    return sum(1 for case in cases if predicate(case))


def any_evidence_status(case: dict[str, Any], status: str) -> bool:
    return any(evidence.get("status") == status for evidence in case.get("evidence", []))


def join_categories(value: Any) -> str:
    if isinstance(value, list):
        return " + ".join(clean_text(item) for item in value if clean_text(item))
    return clean_text(value)
