from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any

from backend.app.agents.models import AgentDecision, CaseReviewStatus, ClaimCase, clean_number, clean_text, json_safe
from backend.app.domain.complaint_message import (
    ALLOWED_COMPLAINT_CATEGORIES,
    canonicalize_category,
    extract_json_text,
    format_message_categories,
)


AgentLlmGenerator = Callable[[str, int, str], str | Awaitable[str]]
ALLOWED_REVIEW_STATUSES: set[CaseReviewStatus] = {
    "auto_ready",
    "needs_review",
    "missing_evidence",
    "contradiction",
    "failed",
}
ALLOWED_DECISIONS = {"valid_penalty", "needs_review", "invalid_penalty", "partial", "failed"}
MAX_FIELD_VALUE_LENGTH = 420
SOURCE_HIERARCHY = ("comments", "remarks", "sub_category", "source_alignment")


class AgentLlmError(ValueError):
    """Raised when an agent LLM response cannot be safely used."""


async def maybe_call_agent_llm(
    llm_generator: AgentLlmGenerator,
    prompt: str,
    *,
    max_completion_tokens: int = 8192,
    reasoning_effort: str = "medium",
    semaphore: asyncio.Semaphore | None = None,
) -> str:
    if semaphore is None:
        return await _call_generator(llm_generator, prompt, max_completion_tokens, reasoning_effort)

    async with semaphore:
        return await _call_generator(llm_generator, prompt, max_completion_tokens, reasoning_effort)


async def _call_generator(
    llm_generator: AgentLlmGenerator,
    prompt: str,
    max_completion_tokens: int,
    reasoning_effort: str,
) -> str:
    if inspect.iscoroutinefunction(llm_generator):
        return str(await llm_generator(prompt, max_completion_tokens, reasoning_effort))

    result = await asyncio.to_thread(llm_generator, prompt, max_completion_tokens, reasoning_effort)
    if inspect.isawaitable(result):
        return str(await result)
    return str(result)


def parse_json_object(response: str) -> dict[str, Any]:
    try:
        parsed = json.loads(extract_json_text(response))
    except Exception as error:
        raise AgentLlmError("invalid_json") from error

    if not isinstance(parsed, dict):
        raise AgentLlmError("json_not_object")
    return parsed


def build_specialist_prompt(
    *,
    agent_name: str,
    case: ClaimCase,
    fallback_decision: AgentDecision,
    guardrails: dict[str, Any],
) -> str:
    payload = {
        "case": case_payload(case),
        "evidence": evidence_packet(case),
        "computed_facts_and_guardrails": json_safe(guardrails),
        "deterministic_fallback_decision": fallback_decision.to_dict(),
        "allowed_complaint_categories": ALLOWED_COMPLAINT_CATEGORIES,
        "allowed_review_statuses": sorted(ALLOWED_REVIEW_STATUSES),
        "allowed_decisions": sorted(ALLOWED_DECISIONS),
        "required_json_schema": decision_schema(),
    }
    return "\n".join(
        [
            "Agent specialist decision task.",
            f"You are the {agent_name} for MakeMyTrip Cab Ops loss recovery.",
            "Reason only over comments, Remarks, Sub Category, and source-alignment evidence provided in this payload.",
            "Use comments as primary evidence when present. If comments are absent, use Remarks.",
            "Treat Sub Category as supporting row context only; Sub Category alone is missing evidence.",
            "Auto-ready requires overlap between the primary evidence categories and row categories.",
            "Route booking-ID mismatches and category mismatches to needs_review.",
            "Do not use, infer from, request, or mention timing, fare, driver status, vehicle, tracking, or payment fields.",
            "Return only strict JSON matching required_json_schema. No markdown.",
            "Use complaint_categories only from allowed_complaint_categories.",
            "Use evidence_ids only from the provided source evidence IDs. Cite every key fact with those IDs.",
            "If comments and Remarks are both missing, route to missing_evidence rather than auto_ready.",
            "recommended_recovery_amount must be between 0 and the case recoverable_amount.",
            "",
            json.dumps(payload, ensure_ascii=False),
        ]
    )


def build_judge_prompt(
    *,
    case: ClaimCase,
    specialist_decision: AgentDecision,
    fallback_decision: AgentDecision,
    guardrails: dict[str, Any],
) -> str:
    payload = {
        "case": case_payload(case),
        "evidence": evidence_packet(case),
        "specialist_decision": specialist_decision.to_dict(),
        "deterministic_guardrail_decision": fallback_decision.to_dict(),
        "computed_facts_and_guardrails": json_safe(guardrails),
        "allowed_complaint_categories": ALLOWED_COMPLAINT_CATEGORIES,
        "allowed_review_statuses": sorted(ALLOWED_REVIEW_STATUSES),
        "allowed_decisions": sorted(ALLOWED_DECISIONS),
        "required_json_schema": decision_schema(),
    }
    return "\n".join(
        [
            "Judge Agent verification task.",
            "You are the final verifier for a Cab Ops recovery recommendation.",
            "Check whether the specialist decision follows the computed source-alignment evidence.",
            "Comments are primary when present. Remarks are primary only when comments are absent.",
            "Sub Category is supporting row context only; Sub Category alone is missing evidence.",
            "Approve as auto_ready only when primary evidence categories overlap row categories and no booking-ID mismatch exists.",
            "Route booking-ID mismatches and category mismatches to needs_review.",
            "Do not use, infer from, request, or mention timing, fare, driver status, vehicle, tracking, or payment fields.",
            "Return only strict JSON matching required_json_schema. No markdown.",
            "Do not route to review only because the primary evidence is brief, vague, or lacks operational corroboration.",
            "Reject or route to review when primary evidence is missing, mismatched, uncited, or explicitly says the penalty is wrong, false, resolved, denied, or invalid.",
            "Do not allow unsupported facts from the specialist rationale to become final facts.",
            "",
            json.dumps(payload, ensure_ascii=False),
        ]
    )


def build_portfolio_prompt(*, fallback_summary: dict[str, Any]) -> str:
    payload = {
        "portfolio_inputs": json_safe(fallback_summary),
        "required_json_schema": {
            "executive_summary": "string",
            "top_complaint_drivers": ["string"],
            "recommended_actions": ["string"],
            "missing_data_hotspots": ["string"],
            "category_breakdown": [{"category": "string", "cases": "number", "recoverable": "number"}],
        },
    }
    return "\n".join(
        [
            "Portfolio Summary Agent task.",
            "You summarize Cab Ops loss recovery investigation results for operational leaders.",
            "Use only the provided aggregate inputs. Do not invent suppliers, vendors, or source systems.",
            "Return only strict JSON matching required_json_schema. No markdown.",
            "Keep the executive summary concise and action-oriented.",
            "All recoverable amounts are INR; use the rupee symbol ₹ and never use dollar notation.",
            "",
            json.dumps(payload, ensure_ascii=False),
        ]
    )


def decision_schema() -> dict[str, Any]:
    return {
        "decision": "valid_penalty | needs_review | invalid_penalty | partial | failed",
        "complaint_categories": ["Allowed category string"],
        "confidence": "number 0..1",
        "recommended_recovery_amount": "number",
        "rationale": "short string grounded in cited evidence",
        "recommended_action": "short operational action",
        "review_status": "auto_ready | needs_review | missing_evidence | contradiction | failed",
        "review_reason": "short string",
        "evidence_ids": ["provided evidence ID"],
    }


def decision_from_payload(
    payload: dict[str, Any],
    *,
    fallback: AgentDecision,
    allowed_evidence_ids: set[str],
    default_agent: str,
    max_recovery_amount: float,
) -> AgentDecision:
    raw_decision = clean_text(payload.get("decision"))
    decision = raw_decision if raw_decision in ALLOWED_DECISIONS else fallback.decision

    categories = normalize_categories(payload.get("complaint_categories", payload.get("categories", [])))
    if not categories:
        categories = fallback.complaint_categories

    evidence_ids = normalize_evidence_ids(payload.get("evidence_ids", []), allowed_evidence_ids)
    if allowed_evidence_ids and not evidence_ids:
        raise AgentLlmError("no_valid_evidence_ids")

    review_status = normalize_review_status(payload.get("review_status"), fallback.review_status)
    confidence = clamp(clean_number(payload.get("confidence")), 0.0, 1.0)
    if payload.get("confidence") in (None, ""):
        confidence = fallback.confidence

    amount = clamp(clean_number(payload.get("recommended_recovery_amount")), 0.0, max(0.0, max_recovery_amount))
    if payload.get("recommended_recovery_amount") in (None, ""):
        amount = fallback.recommended_recovery_amount

    rationale = clean_text(payload.get("rationale")) or fallback.rationale
    review_reason = clean_text(payload.get("review_reason")) or fallback.review_reason
    recommended_action = clean_text(payload.get("recommended_action")) or fallback.recommended_action

    return AgentDecision(
        agent=default_agent,
        decision=decision,
        complaint_categories=categories,
        confidence=confidence,
        recommended_recovery_amount=amount,
        rationale=rationale,
        recommended_action=recommended_action,
        review_status=review_status,
        review_reason=review_reason,
        evidence_ids=evidence_ids,
        decision_source="llm",
    )


def mark_fallback(decision: AgentDecision, *, llm_error: str | None = None) -> AgentDecision:
    return AgentDecision(
        agent=decision.agent,
        decision=decision.decision,
        complaint_categories=decision.complaint_categories,
        confidence=decision.confidence,
        recommended_recovery_amount=decision.recommended_recovery_amount,
        rationale=decision.rationale,
        recommended_action=decision.recommended_action,
        review_status=decision.review_status,
        review_reason=decision.review_reason,
        evidence_ids=decision.evidence_ids,
        decision_source="fallback",
        llm_error=llm_error,
    )


def apply_guardrail_status(
    decision: AgentDecision,
    *,
    review_status: CaseReviewStatus,
    confidence_cap: float,
    reason: str,
) -> AgentDecision:
    confidence = min(decision.confidence, confidence_cap)
    return AgentDecision(
        agent=decision.agent,
        decision="needs_review" if review_status != "auto_ready" else decision.decision,
        complaint_categories=decision.complaint_categories,
        confidence=confidence,
        recommended_recovery_amount=decision.recommended_recovery_amount,
        rationale=decision.rationale,
        recommended_action=action_for_review_status(review_status),
        review_status=review_status,
        review_reason=reason,
        evidence_ids=decision.evidence_ids,
        decision_source=decision.decision_source,
        llm_error=decision.llm_error,
    )


def validate_portfolio_payload(payload: dict[str, Any], fallback_summary: dict[str, Any]) -> dict[str, Any]:
    output = dict(fallback_summary)
    for key in ["executive_summary"]:
        value = clean_text(payload.get(key))
        if value:
            output[key] = normalize_currency_text(value)

    for key in ["top_complaint_drivers", "recommended_actions", "missing_data_hotspots"]:
        values = string_list(payload.get(key))
        if values:
            output[key] = [normalize_currency_text(value) for value in values[:8]]

    breakdown = payload.get("category_breakdown")
    if isinstance(breakdown, list):
        normalized_breakdown: list[dict[str, Any]] = []
        for item in breakdown:
            if not isinstance(item, dict):
                continue
            category = clean_text(item.get("category"))
            if not category:
                continue
            normalized_breakdown.append(
                {
                    "category": category,
                    "cases": int(clean_number(item.get("cases"))),
                    "recoverable": round(clean_number(item.get("recoverable")), 2),
                }
            )
        if normalized_breakdown:
            output["category_breakdown"] = normalized_breakdown

    output["case_counts"] = fallback_summary.get("case_counts", {})
    output["total_recoverable_amount"] = fallback_summary.get("total_recoverable_amount", 0)
    output["high_confidence_case_count"] = fallback_summary.get("high_confidence_case_count", 0)
    output["high_confidence_recoverable_amount"] = fallback_summary.get("high_confidence_recoverable_amount", 0)
    return output


def normalize_currency_text(value: str) -> str:
    return clean_text(value).replace("$", "₹")


def case_payload(case: ClaimCase) -> dict[str, Any]:
    return {
        "booking_id": case.booking_id,
        "recoverable_amount": round(case.recoverable_amount, 2),
        "row_index": case.row_index,
    }


def evidence_packet(case: ClaimCase) -> list[dict[str, Any]]:
    selected_evidence = source_alignment_evidence(case)
    return [
        {
            "id": item.id,
            "title": item.title,
            "source": item.source,
            "status": item.status,
            "summary": truncate(item.summary),
            "fields": compact_fields(item.fields),
            "error": truncate(item.error or ""),
        }
        for item in selected_evidence
    ]


def source_alignment_evidence(case: ClaimCase) -> list[Any]:
    source_items: list[Any] = []
    for item in case.evidence:
        source_field = clean_text(item.fields.get("source_field"))
        if source_field not in SOURCE_HIERARCHY:
            source_field = source_from_evidence_id(item.id)
        if item.source != "source_alignment" and source_field not in SOURCE_HIERARCHY:
            continue
        source_items.append(item)
    return source_items


def source_from_evidence_id(evidence_id: str) -> str:
    for source_field in SOURCE_HIERARCHY:
        if evidence_id.endswith(f":{source_field}"):
            return source_field
    return ""


def compact_fields(fields: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in fields.items():
        if value in (None, ""):
            continue
        safe_value = json_safe(value)
        if isinstance(safe_value, str):
            safe_value = truncate(safe_value)
        elif isinstance(safe_value, list):
            safe_value = [truncate(item) if isinstance(item, str) else item for item in safe_value[:12]]
        elif isinstance(safe_value, dict):
            safe_value = {str(child_key): json_safe(child_value) for child_key, child_value in list(safe_value.items())[:20]}
        compact[str(key)] = safe_value
    return compact


def normalize_categories(raw_categories: Any) -> list[str]:
    if isinstance(raw_categories, str):
        raw_values = [part.strip() for part in raw_categories.replace(",", " + ").split("+")]
    elif isinstance(raw_categories, list):
        raw_values = raw_categories
    else:
        raw_values = []

    categories: list[str] = []
    for value in raw_values:
        category = canonicalize_category(value)
        if category and category not in categories:
            categories.append(category)
    return categories


def normalize_evidence_ids(raw_evidence_ids: Any, allowed_evidence_ids: set[str]) -> list[str]:
    if isinstance(raw_evidence_ids, str):
        raw_values = [part.strip() for part in raw_evidence_ids.replace(",", " ").split()]
    elif isinstance(raw_evidence_ids, list):
        raw_values = raw_evidence_ids
    else:
        raw_values = []

    evidence_ids: list[str] = []
    for value in raw_values:
        evidence_id = clean_text(value)
        if evidence_id in allowed_evidence_ids and evidence_id not in evidence_ids:
            evidence_ids.append(evidence_id)
    return evidence_ids


def normalize_review_status(value: Any, fallback_status: CaseReviewStatus) -> CaseReviewStatus:
    status = clean_text(value)
    if status in ALLOWED_REVIEW_STATUSES:
        return status  # type: ignore[return-value]
    return fallback_status


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := clean_text(item))]


def action_for_review_status(status: CaseReviewStatus) -> str:
    if status == "auto_ready":
        return "Ready for Cab Ops recovery package"
    if status == "missing_evidence":
        return "Review manually because source text is missing"
    if status == "contradiction":
        return "Manual review required due to conflicting evidence"
    if status == "failed":
        return "Manual review required because investigation failed"
    return "Review before operational action"


def categories_to_message(categories: list[str]) -> str:
    if not categories:
        return ""
    return format_message_categories(categories)


def truncate(value: Any, *, limit: int = MAX_FIELD_VALUE_LENGTH) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
