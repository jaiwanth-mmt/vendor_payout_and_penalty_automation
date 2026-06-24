from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from typing import Any

import pandas as pd

from backend.app.agents.evidence import EvidenceToolset
from backend.app.agents.llm import (
    AgentLlmGenerator,
    build_portfolio_prompt,
    categories_to_message,
    maybe_call_agent_llm,
    parse_json_object,
    validate_portfolio_payload,
)
from backend.app.agents.models import AGENT_OUTPUT_COLUMNS, AgentTraceStep, ClaimCase, clean_number, clean_text
from backend.app.agents.specialists import (
    llm_error_label,
    run_judge_agent,
    run_judge_agent_async,
    run_specialist_agent,
    run_specialist_agent_async,
)
from backend.app.domain.complaint_message import MESSAGE_COLUMN


COMMENTS_COLUMN = "comments"
UNKNOWN_VENDOR_NAME = "Unknown vendor"
VENDOR_NAME_COLUMN = "vendor_name"


def build_claim_case(row: pd.Series, *, row_index: int) -> ClaimCase:
    vendor_name = clean_text(row.get(VENDOR_NAME_COLUMN)) or UNKNOWN_VENDOR_NAME
    return ClaimCase(
        booking_id=clean_text(row.get("Booking ID")),
        sub_category=clean_text(row.get("Sub Category")) or "Uncategorized",
        remarks=clean_text(row.get("Remarks")),
        recoverable_amount=clean_number(row.get("Recoverable")),
        row_index=row_index,
        comments=clean_text(row.get(COMMENTS_COLUMN)),
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

    output = ensure_agent_columns(df)
    evidence_tools = EvidenceToolset(tracking_bookings)
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
    output = ensure_agent_columns(df)
    evidence_tools = EvidenceToolset(tracking_bookings)
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

    decision = case.final_decision
    if decision is None:
        return

    message = categories_to_message(decision.complaint_categories)
    if message:
        output.at[index, MESSAGE_COLUMN] = message


def build_case_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(case.get("review_status", "failed") for case in cases)
    return {
        "total_cases": len(cases),
        "auto_ready": counts.get("auto_ready", 0),
        "needs_review": counts.get("needs_review", 0),
        "missing_evidence": counts.get("missing_evidence", 0),
        "contradiction": counts.get("contradiction", 0),
        "failed": counts.get("failed", 0),
    }


def review_queue_row(case: dict[str, Any]) -> dict[str, Any]:
    decision = case.get("final_decision") or {}
    return {
        "booking_id": case.get("booking_id", ""),
        "sub_category": case.get("sub_category", ""),
        "recoverable_amount": case.get("recoverable_amount", 0),
        "review_status": case.get("review_status", "failed"),
        "decision": decision.get("decision", ""),
        "confidence": decision.get("confidence", 0),
        "recommended_action": decision.get("recommended_action", ""),
        "review_reason": decision.get("review_reason", ""),
    }


def build_agent_progress(
    cases: list[dict[str, Any]],
    *,
    agent_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    total = len(cases)
    intake_missing_booking_ids = count_cases(cases, lambda case: not clean_text(case.get("booking_id")))
    evidence_error_cases = count_cases(cases, lambda case: any_evidence_status(case, "error"))
    evidence_missing_cases = count_cases(cases, lambda case: any_evidence_status(case, "missing"))
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


def build_portfolio_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    case_counts = build_case_counts(cases)
    total_recoverable = sum(float(case.get("recoverable_amount") or 0) for case in cases)
    high_confidence_recoverable = sum(
        float(case.get("recoverable_amount") or 0)
        for case in cases
        if (case.get("final_decision") or {}).get("confidence", 0) >= 0.85
    )
    category_totals: dict[str, dict[str, Any]] = defaultdict(lambda: {"category": "", "cases": 0, "recoverable": 0.0})
    missing_sources: Counter[str] = Counter()

    for case in cases:
        category = str(case.get("sub_category") or "Uncategorized")
        category_totals[category]["category"] = category
        category_totals[category]["cases"] += 1
        category_totals[category]["recoverable"] += float(case.get("recoverable_amount") or 0)
        for evidence in case.get("evidence", []):
            if evidence.get("status") == "missing":
                missing_sources[evidence.get("title", "Evidence")] += 1

    top_categories = sorted(
        category_totals.values(),
        key=lambda item: (item["recoverable"], item["cases"]),
        reverse=True,
    )
    top_complaint_drivers = [
        f"{item['category']}: {item['cases']} cases, recoverable {item['recoverable']:.0f}"
        for item in top_categories[:5]
    ]
    missing_data_hotspots = [
        f"{title}: missing for {count} cases"
        for title, count in missing_sources.most_common(5)
    ]
    recommended_actions = build_recommended_actions(case_counts, top_categories, missing_data_hotspots)
    vendor_analysis = build_vendor_penalty_analysis(cases)

    return {
        "executive_summary": (
            f"Agents investigated {len(cases)} bookings and marked "
            f"{case_counts['auto_ready']} as ready for recovery, with "
            f"{case_counts['needs_review'] + case_counts['missing_evidence'] + case_counts['contradiction']} "
            "requiring review before action."
        ),
        "case_counts": case_counts,
        "total_recoverable_amount": round(total_recoverable, 2),
        "high_confidence_recoverable_amount": round(high_confidence_recoverable, 2),
        "top_complaint_drivers": top_complaint_drivers,
        "category_breakdown": [
            {
                "category": item["category"],
                "cases": item["cases"],
                "recoverable": round(item["recoverable"], 2),
            }
            for item in top_categories
        ],
        **vendor_analysis,
        "missing_data_hotspots": missing_data_hotspots,
        "recommended_actions": recommended_actions,
    }


def build_vendor_penalty_analysis(cases: list[dict[str, Any]]) -> dict[str, Any]:
    vendor_totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "vendor_name": "",
            "case_count": 0,
            "total_recoverable": 0.0,
            "subcategory_totals": defaultdict(lambda: {"subcategory": "", "case_count": 0, "total_recoverable": 0.0}),
        }
    )
    category_totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"subcategory": "", "case_count": 0, "total_recoverable": 0.0}
    )

    for case in cases:
        vendor_name = clean_text(case.get("vendor_name")) or UNKNOWN_VENDOR_NAME
        subcategory = clean_text(case.get("sub_category")) or "Uncategorized"
        recoverable = clean_number(case.get("recoverable_amount"))

        vendor_total = vendor_totals[vendor_name]
        vendor_total["vendor_name"] = vendor_name
        vendor_total["case_count"] += 1
        vendor_total["total_recoverable"] += recoverable

        vendor_subcategory = vendor_total["subcategory_totals"][subcategory]
        vendor_subcategory["subcategory"] = subcategory
        vendor_subcategory["case_count"] += 1
        vendor_subcategory["total_recoverable"] += recoverable

        category_total = category_totals[subcategory]
        category_total["subcategory"] = subcategory
        category_total["case_count"] += 1
        category_total["total_recoverable"] += recoverable

    top_vendors = sorted(
        vendor_totals.values(),
        key=lambda item: (-item["total_recoverable"], -item["case_count"], item["vendor_name"].casefold()),
    )[:3]
    top_categories_by_penalty = sorted(
        category_totals.values(),
        key=lambda item: (-item["total_recoverable"], -item["case_count"], item["subcategory"].casefold()),
    )[:3]
    top_categories_by_count = sorted(
        category_totals.values(),
        key=lambda item: (-item["case_count"], -item["total_recoverable"], item["subcategory"].casefold()),
    )[:3]

    return {
        "top_vendors_by_penalty": [
            {
                "vendor_name": item["vendor_name"],
                "case_count": item["case_count"],
                "total_recoverable": round(item["total_recoverable"], 2),
                "top_subcategories": normalize_ranked_category_items(
                    sorted(
                        item["subcategory_totals"].values(),
                        key=lambda subcategory_item: (
                            -subcategory_item["total_recoverable"],
                            -subcategory_item["case_count"],
                            subcategory_item["subcategory"].casefold(),
                        ),
                    )[:3]
                ),
            }
            for item in top_vendors
        ],
        "top_subcategories_by_penalty": normalize_ranked_category_items(top_categories_by_penalty),
        "top_subcategories_by_count": normalize_ranked_category_items(top_categories_by_count),
    }


def normalize_ranked_category_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "subcategory": item["subcategory"],
            "case_count": item["case_count"],
            "total_recoverable": round(item["total_recoverable"], 2),
        }
        for item in items
    ]


async def build_portfolio_summary_async(
    cases: list[dict[str, Any]],
    *,
    llm_generator: AgentLlmGenerator | None,
    llm_concurrency: int,
) -> dict[str, Any]:
    fallback_summary = build_portfolio_summary(cases)
    if llm_generator is None or not cases:
        return fallback_summary

    try:
        semaphore = asyncio.Semaphore(max(1, llm_concurrency))
        response = await maybe_call_agent_llm(
            llm_generator,
            build_portfolio_prompt(fallback_summary=fallback_summary),
            max_completion_tokens=4096,
            reasoning_effort="medium",
            semaphore=semaphore,
        )
        payload = parse_json_object(response)
        return validate_portfolio_payload(payload, fallback_summary)
    except Exception as error:
        fallback_summary["portfolio_summary_source"] = "fallback"
        fallback_summary["portfolio_llm_error"] = llm_error_label(error)
        return fallback_summary


def build_recommended_actions(
    case_counts: dict[str, int],
    top_categories: list[dict[str, Any]],
    missing_data_hotspots: list[str],
) -> list[str]:
    actions: list[str] = []
    if top_categories:
        actions.append(f"Prioritize recovery review for {top_categories[0]['category']} because it has the highest recoverable exposure.")
    if case_counts["missing_evidence"]:
        actions.append("Review cases where comments, Remarks, and Sub Category are missing before operational recovery.")
    if case_counts["contradiction"]:
        actions.append("Route contradiction cases to a Cab Ops reviewer before any supplier action.")
    if not actions:
        actions.append("Proceed with the high-confidence recovery package and monitor category trends.")
    if missing_data_hotspots:
        actions.append("Improve source coverage: " + "; ".join(missing_data_hotspots[:2]) + ".")
    return actions
