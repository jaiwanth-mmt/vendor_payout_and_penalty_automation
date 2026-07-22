"""Human edit stage helpers — snapshot, patch, apply outcomes before portfolio/package."""

from __future__ import annotations

from typing import Any, Literal

from backend.app.agents.models import clean_number, clean_text


EditOutcome = Literal["include", "needs_ops", "exclude"]
AiBucket = Literal["needs_check", "auto_approved"]

EDIT_OUTCOMES: frozenset[str] = frozenset({"include", "needs_ops", "exclude"})
AUTO_APPROVED_STATUSES: frozenset[str] = frozenset({"auto_ready"})
NEEDS_CHECK_STATUSES: frozenset[str] = frozenset(
    {"needs_review", "missing_evidence", "contradiction", "failed"}
)


def ai_bucket_for_status(review_status: str) -> AiBucket:
    status = clean_text(review_status) or "failed"
    if status in AUTO_APPROVED_STATUSES:
        return "auto_approved"
    return "needs_check"


def default_edit_outcome(ai_bucket: AiBucket) -> EditOutcome:
    return "include" if ai_bucket == "auto_approved" else "needs_ops"


def prepare_case_for_edit(case: dict[str, Any]) -> dict[str, Any]:
    """Attach immutable AI labels + editable snapshot fields for the edit workspace."""
    enriched = dict(case)
    review_status = clean_text(enriched.get("review_status")) or "failed"
    ai_bucket = ai_bucket_for_status(review_status)
    outcome = default_edit_outcome(ai_bucket)

    recoverable = round(clean_number(enriched.get("recoverable_amount")), 2)
    message = clean_text(enriched.get("message"))
    remarks = clean_text(enriched.get("remarks"))
    sub_category = clean_text(enriched.get("sub_category")) or "Uncategorized"

    enriched["ai_bucket"] = ai_bucket
    enriched["ai_review_status"] = review_status
    enriched["edit_outcome"] = outcome
    enriched["excluded"] = False
    enriched["original_recoverable_amount"] = recoverable
    enriched["original_message"] = message
    enriched["original_remarks"] = remarks
    enriched["original_sub_category"] = sub_category
    enriched["original_edit_outcome"] = outcome
    enriched["recoverable_amount"] = recoverable
    enriched["message"] = message
    enriched["remarks"] = remarks
    enriched["sub_category"] = sub_category
    enriched["was_edited"] = False
    enriched["edited_fields"] = []
    return enriched


def prepare_cases_for_edit(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [prepare_case_for_edit(case) for case in cases]


def compute_edited_fields(case: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    if round(clean_number(case.get("recoverable_amount")), 2) != round(
        clean_number(case.get("original_recoverable_amount")), 2
    ):
        changed.append("recoverable_amount")
    if clean_text(case.get("message")) != clean_text(case.get("original_message")):
        changed.append("message")
    if clean_text(case.get("remarks")) != clean_text(case.get("original_remarks")):
        changed.append("remarks")
    if clean_text(case.get("sub_category")) != clean_text(case.get("original_sub_category")):
        changed.append("sub_category")
    if clean_text(case.get("edit_outcome")) != clean_text(case.get("original_edit_outcome")):
        changed.append("edit_outcome")
    return changed


def refresh_edit_flags(case: dict[str, Any]) -> dict[str, Any]:
    updated = dict(case)
    edited_fields = compute_edited_fields(updated)
    updated["edited_fields"] = edited_fields
    updated["was_edited"] = bool(edited_fields)
    return updated


def patch_edit_case(case: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Apply editable field updates. booking_id in patch is ignored."""
    updated = dict(case)

    if "recoverable_amount" in patch:
        amount = clean_number(patch.get("recoverable_amount"))
        if amount < 0 or amount != amount:  # NaN check
            raise ValueError("recoverable_amount must be a finite number >= 0")
        updated["recoverable_amount"] = round(amount, 2)

    if "message" in patch:
        updated["message"] = clean_text(patch.get("message"))

    if "remarks" in patch:
        updated["remarks"] = clean_text(patch.get("remarks"))

    if "sub_category" in patch:
        sub_category = clean_text(patch.get("sub_category"))
        if not sub_category:
            raise ValueError("sub_category must be a non-empty string")
        updated["sub_category"] = sub_category

    if "edit_outcome" in patch:
        outcome = clean_text(patch.get("edit_outcome"))
        if outcome not in EDIT_OUTCOMES:
            raise ValueError("edit_outcome must be one of: include, needs_ops, exclude")
        updated["edit_outcome"] = outcome

    return refresh_edit_flags(updated)


def apply_edit_outcome_to_case(case: dict[str, Any]) -> dict[str, Any]:
    """Map edit outcome onto review_status / final_decision before portfolio."""
    applied = dict(case)
    outcome = clean_text(applied.get("edit_outcome")) or default_edit_outcome(
        ai_bucket_for_status(clean_text(applied.get("ai_review_status")) or "failed")
    )
    recoverable = round(clean_number(applied.get("recoverable_amount")), 2)
    message = clean_text(applied.get("message"))
    remarks = clean_text(applied.get("remarks"))
    sub_category = clean_text(applied.get("sub_category")) or "Uncategorized"

    applied["recoverable_amount"] = recoverable
    applied["message"] = message
    applied["remarks"] = remarks
    applied["sub_category"] = sub_category
    applied["edit_outcome"] = outcome

    judge = dict(applied.get("judge_decision") or {})
    final = dict(applied.get("final_decision") or judge)

    if outcome == "include":
        applied["excluded"] = False
        applied["review_status"] = "auto_ready"
        decision_fields = {
            "decision": "valid_penalty",
            "review_status": "auto_ready",
            "recommended_recovery_amount": recoverable,
            "recommended_action": "Ready for Cab Ops recovery package",
            "review_reason": clean_text(final.get("review_reason"))
            or "Included in recovery via human edit stage",
        }
    elif outcome == "needs_ops":
        applied["excluded"] = False
        applied["review_status"] = "needs_review"
        decision_fields = {
            "decision": "needs_review",
            "review_status": "needs_review",
            "recommended_recovery_amount": recoverable,
            "recommended_action": "Needs ops follow-up before recovery",
            "review_reason": clean_text(final.get("review_reason"))
            or "Flagged for ops follow-up via human edit stage",
        }
    else:
        ai_status = clean_text(applied.get("ai_review_status")) or "failed"
        applied["excluded"] = True
        applied["review_status"] = ai_status
        decision_fields = {
            "decision": clean_text(final.get("decision")) or "needs_review",
            "review_status": ai_status,
            "recommended_recovery_amount": 0,
            "recommended_action": "Excluded from recovery package",
            "review_reason": "Excluded via human edit stage",
        }

    for target in (judge, final):
        target.update(decision_fields)
    applied["judge_decision"] = judge
    applied["final_decision"] = final
    return refresh_edit_flags(applied)


def apply_edit_outcomes(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [apply_edit_outcome_to_case(case) for case in cases]


def edit_metrics(cases: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "edited_case_count": sum(1 for case in cases if case.get("was_edited")),
        "excluded_case_count": sum(1 for case in cases if case.get("excluded") or case.get("edit_outcome") == "exclude"),
        "needs_check_count": sum(1 for case in cases if case.get("ai_bucket") == "needs_check"),
        "auto_approved_count": sum(1 for case in cases if case.get("ai_bucket") == "auto_approved"),
    }


def cases_for_portfolio(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Zero recoverable for excluded rows so totals/rankings stay consistent."""
    portfolio_cases: list[dict[str, Any]] = []
    for case in cases:
        item = dict(case)
        if item.get("excluded") or clean_text(item.get("edit_outcome")) == "exclude":
            item = dict(item)
            item["recoverable_amount"] = 0
            item["_portfolio_omit"] = True
        portfolio_cases.append(item)
    return portfolio_cases


def edit_case_api_view(case: dict[str, Any]) -> dict[str, Any]:
    """Lean payload for the non-tech edit UI."""
    final = case.get("final_decision") or {}
    return {
        "booking_id": clean_text(case.get("booking_id")),
        "comments": clean_text(case.get("comments")),
        "recoverable_amount": round(clean_number(case.get("recoverable_amount")), 2),
        "message": clean_text(case.get("message")),
        "remarks": clean_text(case.get("remarks")),
        "sub_category": clean_text(case.get("sub_category")) or "Uncategorized",
        "vendor_name": clean_text(case.get("vendor_name")) or "Unknown vendor",
        "ai_bucket": case.get("ai_bucket") or ai_bucket_for_status(clean_text(case.get("review_status"))),
        "ai_review_status": clean_text(case.get("ai_review_status") or case.get("review_status")),
        "edit_outcome": clean_text(case.get("edit_outcome")) or "needs_ops",
        "was_edited": bool(case.get("was_edited")),
        "edited_fields": list(case.get("edited_fields") or []),
        "review_reason": clean_text(final.get("review_reason") or case.get("review_reason")),
        "excluded": bool(case.get("excluded")),
    }
