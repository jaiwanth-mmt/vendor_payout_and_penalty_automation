from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from typing import Any

from backend.app.agents.llm import (
    AgentLlmGenerator,
    build_portfolio_prompt,
    maybe_call_agent_llm,
    parse_json_object,
    validate_portfolio_payload,
)
from backend.app.agents.models import clean_number, clean_text
from backend.app.agents.specialists import llm_error_label


UNKNOWN_VENDOR_NAME = "Unknown vendor"
VENDOR_NAME_COLUMN = "vendor_name"


def count_cases(cases: list[dict[str, Any]], predicate) -> int:
    return sum(1 for case in cases if predicate(case))


def is_portfolio_omitted(case: dict[str, Any]) -> bool:
    if case.get("_portfolio_omit") or case.get("excluded"):
        return True
    return clean_text(case.get("edit_outcome")) == "exclude"


def build_portfolio_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    case_counts = build_case_counts(cases)
    ranked_cases = [case for case in cases if not is_portfolio_omitted(case)]
    total_recoverable = sum(float(case.get("recoverable_amount") or 0) for case in ranked_cases)
    high_confidence_case_count = count_cases(
        ranked_cases,
        lambda case: (case.get("final_decision") or {}).get("confidence", 0) >= 0.85,
    )
    high_confidence_recoverable = sum(
        float(case.get("recoverable_amount") or 0)
        for case in ranked_cases
        if (case.get("final_decision") or {}).get("confidence", 0) >= 0.85
    )
    category_totals: dict[str, dict[str, Any]] = defaultdict(lambda: {"category": "", "cases": 0, "recoverable": 0.0})
    missing_sources: Counter[str] = Counter()

    for case in ranked_cases:
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
    vendor_analysis = build_vendor_penalty_analysis(ranked_cases)
    edited_case_count = sum(1 for case in cases if case.get("was_edited"))
    excluded_case_count = sum(1 for case in cases if is_portfolio_omitted(case))
    needs_check_count = sum(1 for case in cases if case.get("ai_bucket") == "needs_check")
    auto_approved_count = sum(1 for case in cases if case.get("ai_bucket") == "auto_approved")
    unhandled_count = sum(1 for case in cases if case.get("ai_bucket") == "unhandled")

    return {
        "executive_summary": (
            f"Agents investigated {len(cases)} bookings and marked "
            f"{case_counts['auto_ready']} as ready for recovery, with "
            f"{case_counts['needs_review'] + case_counts['missing_evidence'] + case_counts['contradiction']} "
            "requiring review before action."
        ),
        "case_counts": case_counts,
        "total_recoverable_amount": round(total_recoverable, 2),
        "high_confidence_case_count": high_confidence_case_count,
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
        "edited_case_count": edited_case_count,
        "excluded_case_count": excluded_case_count,
        "needs_check_count": needs_check_count,
        "auto_approved_count": auto_approved_count,
        "unhandled_count": unhandled_count,
    }


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
        if is_portfolio_omitted(case):
            continue
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
