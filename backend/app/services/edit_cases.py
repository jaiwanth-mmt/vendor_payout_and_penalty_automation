"""Human edit stage helpers — snapshot, patch, apply outcomes before portfolio/package."""

from __future__ import annotations

from typing import Any, Literal

from backend.app.agents.models import clean_number, clean_text
from backend.app.domain.complaint_message import map_complaint_labels
from backend.app.domain.fulfillment_not_done import is_vendor_no_show_category


EditOutcome = Literal["include", "needs_ops", "exclude"]
AiBucket = Literal["needs_check", "auto_approved", "unhandled"]

EDIT_OUTCOMES: frozenset[str] = frozenset({"include", "needs_ops", "exclude"})
AUTO_APPROVED_STATUSES: frozenset[str] = frozenset({"auto_ready"})
NEEDS_CHECK_STATUSES: frozenset[str] = frozenset(
    {"needs_review", "missing_evidence", "contradiction", "failed"}
)


def is_sub_category_absent(sub_category: object) -> bool:
    """True when Sub Category is blank or normalized placeholder Uncategorized."""
    text = clean_text(sub_category)
    return not text or text.casefold() == "uncategorized"


def is_unhandled_sub_category(sub_category: object) -> bool:
    """True when Sub Category does not map into ALLOWED_COMPLAINT_CATEGORIES (+ aliases)."""
    if is_sub_category_absent(sub_category):
        return True
    return not map_complaint_labels(sub_category)


def ai_bucket_for_status(review_status: str) -> AiBucket:
    """Map investigation review_status only (no Sub Category check). Prefer ai_bucket_for_case."""
    status = clean_text(review_status) or "failed"
    if status in AUTO_APPROVED_STATUSES:
        return "auto_approved"
    return "needs_check"


def default_edit_outcome(ai_bucket: AiBucket) -> EditOutcome:
    return "include" if ai_bucket == "auto_approved" else "needs_ops"


def _optional_amount(value: Any) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    amount = clean_number(value)
    if amount != amount:
        return None
    return round(amount, 2)


def vendor_no_show_sop_missing(case: dict[str, Any]) -> bool:
    """Force Needs check when Vendor No Show SOP inputs are missing."""
    if not is_vendor_no_show_category(case.get("sub_category")):
        return False
    if bool(case.get("sop_calculation_failed")):
        return True
    return case.get("fine_before_sop") is not None and _optional_amount(case.get("fine_after_sop")) is None


def resolve_edit_bucket(
    *,
    review_status: str,
    sub_category: str,
    remarks: str,
    case: dict[str, Any] | None = None,
) -> tuple[AiBucket, str]:
    """
    Deterministic edit-bucket routing with a product-facing reason.

    Precedence:
    1. Sub Category absent + Remarks absent → unhandled
    2. Sub Category absent + Remarks present → unhandled
    3. Present but unmapped Sub Category → unhandled
    4. Missing SOP inputs for Vendor No Show → needs_check
    5. Remarks absent + mapped Sub Category → needs_check
    6. Otherwise follow investigation review_status
    """
    remarks_text = clean_text(remarks)
    sub_text = clean_text(sub_category)
    remarks_absent = not remarks_text
    sub_absent = is_sub_category_absent(sub_text)

    if sub_absent and remarks_absent:
        return (
            "unhandled",
            "Remarks and Sub Category are absent.",
        )
    if sub_absent and not remarks_absent:
        return (
            "unhandled",
            "Remarks are present but Sub Category is absent, so this booking is categorized as Uncategorized.",
        )
    if not map_complaint_labels(sub_text):
        return (
            "unhandled",
            f"Sub Category '{sub_text}' is new/unique and is not in the allowed complaint list.",
        )

    if case is not None and vendor_no_show_sop_missing({**case, "sub_category": sub_text}):
        return (
            "needs_check",
            "Vendor No Show SOP fine could not be computed (missing amount or ttrip_type).",
        )

    if remarks_absent:
        return (
            "needs_check",
            "Remarks are absent; message was generated from Sub Category.",
        )

    status = clean_text(review_status) or "failed"
    if status in AUTO_APPROVED_STATUSES:
        return "auto_approved", ""
    return "needs_check", clean_text((case or {}).get("review_reason"))


def ai_bucket_for_case(
    *,
    review_status: str,
    sub_category: str,
    remarks: str = "",
    case: dict[str, Any] | None = None,
) -> AiBucket:
    """Assign edit-stage bucket from Remarks/Sub Category presence and review status."""
    bucket, _reason = resolve_edit_bucket(
        review_status=review_status,
        sub_category=sub_category,
        remarks=remarks,
        case=case,
    )
    return bucket


def prepare_case_for_edit(case: dict[str, Any]) -> dict[str, Any]:
    """Attach immutable AI labels + editable snapshot fields for the edit workspace."""
    enriched = dict(case)
    review_status = clean_text(enriched.get("review_status")) or "failed"
    recoverable = round(clean_number(enriched.get("recoverable_amount")), 2)
    message = clean_text(enriched.get("message"))
    remarks = clean_text(enriched.get("remarks"))
    # Preserve blank/Uncategorized so absence rules can still detect missing Sub Category.
    sub_category = clean_text(enriched.get("sub_category")) or "Uncategorized"
    amount = _optional_amount(enriched.get("amount"))
    ttrip_type = clean_text(enriched.get("ttrip_type"))
    fine_before_sop = _optional_amount(enriched.get("fine_before_sop"))
    fine_after_sop = _optional_amount(enriched.get("fine_after_sop"))
    sop_failed = bool(enriched.get("sop_calculation_failed"))
    enriched["sub_category"] = sub_category
    enriched["remarks"] = remarks
    enriched["fine_before_sop"] = fine_before_sop
    enriched["fine_after_sop"] = fine_after_sop
    enriched["sop_calculation_failed"] = sop_failed

    ai_bucket, bucket_reason = resolve_edit_bucket(
        review_status=review_status,
        sub_category=sub_category,
        remarks=remarks,
        case=enriched,
    )
    if ai_bucket == "needs_check" and bucket_reason:
        review_status = "needs_review"
    elif ai_bucket == "unhandled" and review_status in AUTO_APPROVED_STATUSES:
        # Keep investigation label but surface the unique-category reason in the UI.
        pass
    if bucket_reason:
        enriched["review_reason"] = bucket_reason
        enriched["edit_bucket_reason"] = bucket_reason
    else:
        enriched["edit_bucket_reason"] = ""
        enriched["review_reason"] = clean_text(enriched.get("review_reason"))

    outcome = default_edit_outcome(ai_bucket)

    enriched["ai_bucket"] = ai_bucket
    enriched["ai_review_status"] = review_status
    enriched["review_status"] = review_status
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
    enriched["amount"] = amount
    enriched["ttrip_type"] = ttrip_type
    enriched["fine_before_sop"] = fine_before_sop
    enriched["fine_after_sop"] = fine_after_sop
    enriched["sop_calculation_failed"] = sop_failed
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
    sub_category = clean_text(applied.get("sub_category")) or "Uncategorized"
    outcome = clean_text(applied.get("edit_outcome")) or default_edit_outcome(
        ai_bucket_for_case(
            review_status=clean_text(applied.get("ai_review_status")) or "failed",
            sub_category=sub_category,
            remarks=clean_text(applied.get("remarks")),
            case=applied,
        )
    )
    recoverable = round(clean_number(applied.get("recoverable_amount")), 2)
    message = clean_text(applied.get("message"))
    remarks = clean_text(applied.get("remarks"))

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
        "unhandled_count": sum(1 for case in cases if case.get("ai_bucket") == "unhandled"),
    }


def distinct_edit_sub_categories(cases: list[dict[str, Any]]) -> list[str]:
    """Sorted unique sub categories from edit cases (for filter dropdown)."""
    names = {
        clean_text(case.get("sub_category")) or "Uncategorized" for case in cases
    }
    return sorted(names)


def filter_edit_cases(
    cases: list[dict[str, Any]],
    *,
    bucket: str | None = None,
    booking_id: str | None = None,
    sub_category: str | None = None,
) -> list[dict[str, Any]]:
    """Filter edit cases by AI bucket, exact booking ID, and/or exact sub category."""
    booking_filter = clean_text(booking_id)
    sub_category_filter = clean_text(sub_category)

    filtered = cases
    if bucket:
        filtered = [case for case in filtered if case.get("ai_bucket") == bucket]
    if booking_filter:
        filtered = [
            case for case in filtered if clean_text(case.get("booking_id")) == booking_filter
        ]
    if sub_category_filter:
        filtered = [
            case
            for case in filtered
            if (clean_text(case.get("sub_category")) or "Uncategorized") == sub_category_filter
        ]
    return filtered


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


def bulk_patch_edit_outcomes(
    cases: list[dict[str, Any]],
    *,
    bucket: AiBucket,
    edit_outcome: EditOutcome,
    booking_id: str | None = None,
    sub_category: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """
    Apply one edit_outcome to every case in a bucket matching optional filters.

    Returns the full updated case list and the number of cases changed.
    """
    if edit_outcome not in EDIT_OUTCOMES:
        raise ValueError("edit_outcome must be one of: include, needs_ops, exclude")
    if bucket not in {"needs_check", "auto_approved", "unhandled"}:
        raise ValueError("bucket must be one of: needs_check, auto_approved, unhandled")

    targets = filter_edit_cases(
        cases,
        bucket=bucket,
        booking_id=booking_id,
        sub_category=sub_category,
    )
    target_ids = {clean_text(case.get("booking_id")) for case in targets if clean_text(case.get("booking_id"))}
    updated_cases: list[dict[str, Any]] = []
    updated_count = 0
    for case in cases:
        booking = clean_text(case.get("booking_id"))
        if booking in target_ids:
            patched = patch_edit_case(case, {"edit_outcome": edit_outcome})
            updated_cases.append(patched)
            updated_count += 1
        else:
            updated_cases.append(case)
    return updated_cases, updated_count


def edit_case_api_view(case: dict[str, Any]) -> dict[str, Any]:
    """Lean payload for the non-tech edit UI."""
    final = case.get("final_decision") or {}
    sub_category = clean_text(case.get("sub_category")) or "Uncategorized"
    remarks = clean_text(case.get("remarks"))
    review_status = clean_text(case.get("ai_review_status") or case.get("review_status"))
    ai_bucket = case.get("ai_bucket") or ai_bucket_for_case(
        review_status=review_status,
        sub_category=sub_category,
        remarks=remarks,
        case=case,
    )
    bucket_reason = clean_text(case.get("edit_bucket_reason") or case.get("review_reason"))
    if not bucket_reason:
        _bucket, bucket_reason = resolve_edit_bucket(
            review_status=review_status,
            sub_category=sub_category,
            remarks=remarks,
            case=case,
        )
    view = {
        "booking_id": clean_text(case.get("booking_id")),
        "comments": clean_text(case.get("comments")),
        "recoverable_amount": round(clean_number(case.get("recoverable_amount")), 2),
        "message": clean_text(case.get("message")),
        "remarks": remarks,
        "sub_category": sub_category,
        "vendor_name": clean_text(case.get("vendor_name")) or "Unknown vendor",
        "amount": _optional_amount(case.get("amount")),
        "ttrip_type": clean_text(case.get("ttrip_type")),
        "ai_bucket": ai_bucket,
        "ai_review_status": review_status,
        "edit_outcome": clean_text(case.get("edit_outcome")) or "needs_ops",
        "was_edited": bool(case.get("was_edited")),
        "edited_fields": list(case.get("edited_fields") or []),
        "review_reason": bucket_reason or clean_text(final.get("review_reason")),
        "excluded": bool(case.get("excluded")),
    }
    if is_vendor_no_show_category(sub_category) or case.get("fine_before_sop") is not None or case.get(
        "fine_after_sop"
    ) is not None:
        view["fine_before_sop"] = _optional_amount(case.get("fine_before_sop"))
        view["fine_after_sop"] = _optional_amount(case.get("fine_after_sop"))
    return view
