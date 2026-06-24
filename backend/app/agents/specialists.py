from __future__ import annotations

import re
from typing import Any

from backend.app.agents.llm import (
    AgentLlmError,
    AgentLlmGenerator,
    apply_guardrail_status,
    build_judge_prompt,
    build_specialist_prompt,
    decision_from_payload,
    mark_fallback,
    maybe_call_agent_llm,
    parse_json_object,
)
from backend.app.agents.models import AgentDecision, AgentTraceStep, CaseReviewStatus, ClaimCase, clean_text
from backend.app.domain.complaint_message import build_fallback_message


CAB_DELAY_CATEGORY = "Cab Delay"
EXTRA_MONEY_TAKEN_CATEGORY = "Extra Money Taken"
FULFILLMENT_NOT_DONE_CATEGORY = "FULFILLMENT NOT DONE"
LOWER_CATEGORY_VEHICLE_CATEGORY = "Lower Category Vehicle"
SOURCE_HIERARCHY = ("comments", "remarks", "sub_category")
SOURCE_LABELS = {
    "comments": "comments",
    "remarks": "Remarks",
    "sub_category": "Sub Category",
}
SOURCE_CONFIDENCE = {
    "comments": 0.93,
    "remarks": 0.89,
    "sub_category": 0.86,
}
AGENT_BY_CATEGORY = {
    "Cab Delay": "Cab Delay Agent",
    "Cab Delayed > 15 Minutes": "Cab Delay Agent",
    "Cab Delayed by 30-60 Minutes": "Cab Delay Agent",
    "Cab Delayed > 1 Hour": "Cab Delay Agent",
    "Extra Money Taken": "Extra Money Taken Agent",
    "Vendor No Show": "Fulfillment Not Done Agent",
    "Low Category Vehicle": "Lower Category Vehicle Agent",
    "AC Not Working": "AC Not Working Agent",
    "Accident on the Way": "Accident Review Agent",
    "Bad Driver Behaviour/Skill": "Driver Behavior Agent",
    "Cab Breakdown": "Cab Breakdown Agent",
    "Chauffeur/Vehicle Change": "Details Change Agent",
    "Drunk Driver": "Driver Behavior Agent",
    "Poor Vehicle Condition": "Vehicle Condition Agent",
    "White Number Plate": "White Number Plate Agent",
}


def run_specialist_agent(case: ClaimCase) -> None:
    decision, trace = build_specialist_decision(case)
    case.specialist_decision = decision
    case.trace.extend(trace)


async def run_specialist_agent_async(
    case: ClaimCase,
    *,
    llm_generator: AgentLlmGenerator | None,
    semaphore,
) -> None:
    fallback_decision, fallback_trace = build_specialist_decision(case)
    if llm_generator is None:
        case.specialist_decision = fallback_decision
        case.trace.extend(fallback_trace)
        return

    try:
        prompt = build_specialist_prompt(
            agent_name=fallback_decision.agent,
            case=case,
            fallback_decision=fallback_decision,
            guardrails=guardrail_payload(case),
        )
        response = await maybe_call_agent_llm(
            llm_generator,
            prompt,
            max_completion_tokens=8192,
            reasoning_effort="medium",
            semaphore=semaphore,
        )
        payload = parse_json_object(response)
        decision = decision_from_payload(
            payload,
            fallback=fallback_decision,
            allowed_evidence_ids=case_evidence_ids(case),
            default_agent=fallback_decision.agent,
            max_recovery_amount=case.recoverable_amount,
        )
        case.specialist_decision = decision
        case.trace.append(
            AgentTraceStep(
                agent=fallback_decision.agent,
                action="llm_reason_over_evidence",
                status="completed" if decision.review_status == "auto_ready" else "warning",
                summary=decision.rationale,
                evidence_ids=decision.evidence_ids,
                metadata={
                    "decision_source": decision.decision_source,
                    "confidence": decision.confidence,
                    "review_status": decision.review_status,
                },
            )
        )
    except Exception as error:
        fallback_with_error = mark_fallback(fallback_decision, llm_error=llm_error_label(error))
        case.specialist_decision = fallback_with_error
        case.trace.extend(fallback_trace)
        case.trace.append(
            AgentTraceStep(
                agent=fallback_decision.agent,
                action="llm_decision_fallback",
                status="warning",
                summary="Specialist LLM output was unavailable or invalid; deterministic fallback decision was used.",
                evidence_ids=fallback_decision.evidence_ids,
                metadata={"llm_error": fallback_with_error.llm_error or "unknown"},
            )
        )


def build_specialist_decision(case: ClaimCase) -> tuple[AgentDecision, list[AgentTraceStep]]:
    return source_hierarchy_agent(case)


def source_hierarchy_agent(case: ClaimCase) -> tuple[AgentDecision, list[AgentTraceStep]]:
    source = primary_source(case)
    if source is None:
        decision = make_decision(
            agent="Source Hierarchy Agent",
            decision="needs_review",
            categories=[],
            confidence=0.35,
            amount=0,
            rationale="Agent review could not find comments, Remarks, or Sub Category text.",
            status="missing_evidence",
            reason="No comments, Remarks, or Sub Category text was available for agent review.",
            evidence_ids=[],
        )
        return decision, [
            AgentTraceStep(
                agent="Source Hierarchy Agent",
                action="apply_source_hierarchy",
                status="warning",
                summary=decision.review_reason,
                evidence_ids=[],
                metadata={"source_priority": list(SOURCE_HIERARCHY)},
            )
        ]

    source_field, source_label, source_text, evidence_id = source
    categories = categories_from_source(source_field, source_text)
    agent_name = agent_name_for_categories(categories)
    if contradiction_detected(case):
        confidence = 0.55
        status: CaseReviewStatus = "needs_review"
        decision_value = "needs_review"
        reason = f"{source_label} contains a possible contradiction or invalid-penalty signal."
    else:
        confidence = SOURCE_CONFIDENCE[source_field]
        status = "auto_ready"
        decision_value = "valid_penalty"
        reason = f"{source_label} was selected by the comments -> Remarks -> Sub Category hierarchy."

    rationale = (
        f"Agent used only {source_label} for this decision under the configured source hierarchy."
    )
    decision = make_decision(
        agent=agent_name,
        decision=decision_value,
        categories=categories,
        confidence=confidence,
        amount=case.recoverable_amount,
        rationale=rationale,
        status=status,
        reason=reason,
        evidence_ids=[evidence_id],
    )
    trace = [
        AgentTraceStep(
            agent=agent_name,
            action="apply_source_hierarchy",
            status="completed" if status == "auto_ready" else "warning",
            summary=rationale,
            evidence_ids=[evidence_id],
            metadata={"selected_source": source_field, "source_priority": list(SOURCE_HIERARCHY)},
        )
    ]
    return decision, trace


def run_judge_agent(case: ClaimCase) -> None:
    decision, trace = build_judge_decision(case)
    case.judge_decision = decision
    case.trace.extend(trace)


async def run_judge_agent_async(
    case: ClaimCase,
    *,
    llm_generator: AgentLlmGenerator | None,
    semaphore,
) -> None:
    fallback_decision, fallback_trace = build_judge_decision(case)
    specialist = case.specialist_decision
    if llm_generator is None or specialist is None:
        case.judge_decision = fallback_decision
        case.trace.extend(fallback_trace)
        return

    try:
        prompt = build_judge_prompt(
            case=case,
            specialist_decision=specialist,
            fallback_decision=fallback_decision,
            guardrails=guardrail_payload(case),
        )
        response = await maybe_call_agent_llm(
            llm_generator,
            prompt,
            max_completion_tokens=8192,
            reasoning_effort="high",
            semaphore=semaphore,
        )
        payload = parse_json_object(response)
        decision = decision_from_payload(
            payload,
            fallback=fallback_decision,
            allowed_evidence_ids=case_evidence_ids(case),
            default_agent="Judge Agent",
            max_recovery_amount=case.recoverable_amount,
        )
        decision = apply_judge_guardrails(case, decision)
        case.judge_decision = decision
        case.trace.append(
            AgentTraceStep(
                agent="Judge Agent",
                action="llm_verify_specialist_decision",
                status="completed" if decision.review_status == "auto_ready" else "warning",
                summary=decision.review_reason,
                evidence_ids=decision.evidence_ids,
                metadata={
                    "decision_source": decision.decision_source,
                    "confidence": decision.confidence,
                    "review_status": decision.review_status,
                },
            )
        )
    except Exception as error:
        fallback_with_error = mark_fallback(fallback_decision, llm_error=llm_error_label(error))
        case.judge_decision = fallback_with_error
        case.trace.extend(fallback_trace)
        case.trace.append(
            AgentTraceStep(
                agent="Judge Agent",
                action="llm_judge_fallback",
                status="warning",
                summary="Judge LLM output was unavailable or invalid; deterministic guardrail decision was used.",
                evidence_ids=fallback_decision.evidence_ids,
                metadata={"llm_error": fallback_with_error.llm_error or "unknown"},
            )
        )


def build_judge_decision(case: ClaimCase) -> tuple[AgentDecision, list[AgentTraceStep]]:
    specialist = case.specialist_decision
    if specialist is None:
        decision = make_decision(
            agent="Judge Agent",
            decision="failed",
            categories=[],
            confidence=0,
            amount=0,
            rationale="No specialist decision was available for verification.",
            status="failed",
            reason="Specialist agent failed.",
            evidence_ids=[],
        )
        return decision, []

    missing_evidence = [item for item in case.evidence if item.status == "missing"]
    evidence_ids = specialist.evidence_ids
    review_status: CaseReviewStatus = specialist.review_status
    confidence = specialist.confidence
    reason = specialist.review_reason

    amount = specialist.recommended_recovery_amount
    if critical_missing(case):
        review_status = "missing_evidence"
        confidence = min(confidence, 0.58)
        reason = "Judge routed to review because comments, Remarks, and Sub Category are unavailable."
    elif contradiction_detected(case):
        review_status = "contradiction"
        confidence = min(confidence, 0.7)
        reason = "Judge found a possible contradiction in the selected source text."
    elif evidence_ids:
        review_status = "auto_ready"
        confidence = max(confidence, 0.86)
        amount = case.recoverable_amount
        reason = "Judge approved: specialist decision is supported by the selected source text."
    else:
        review_status = "needs_review"
        reason = "Judge routed to review because no selected source evidence ID was cited."

    decision = make_decision(
        agent="Judge Agent",
        decision="valid_penalty" if review_status == "auto_ready" else "needs_review",
        categories=specialist.complaint_categories,
        confidence=confidence,
        amount=amount,
        rationale=f"Judge verified {specialist.agent}: {specialist.rationale}",
        status=review_status,
        reason=reason,
        evidence_ids=evidence_ids,
    )
    trace = [
        AgentTraceStep(
            agent="Judge Agent",
            action="verify_specialist_decision",
            status="completed" if review_status == "auto_ready" else "warning",
            summary=reason,
            evidence_ids=evidence_ids,
            metadata={"missing_source_count": len(missing_evidence), "confidence": confidence},
        )
    ]
    return decision, trace


def make_decision(
    *,
    agent: str,
    decision: str,
    categories: list[str],
    confidence: float,
    amount: float,
    rationale: str,
    status: CaseReviewStatus,
    reason: str,
    evidence_ids: list[str],
    decision_source: str = "fallback",
    llm_error: str | None = None,
) -> AgentDecision:
    return AgentDecision(
        agent=agent,
        decision=decision,
        complaint_categories=[category for category in categories if category],
        confidence=max(0.0, min(1.0, confidence)),
        recommended_recovery_amount=amount if confidence >= 0.6 else 0,
        rationale=rationale,
        recommended_action=action_for_status(status),
        review_status=status,
        review_reason=reason,
        evidence_ids=evidence_ids,
        decision_source="llm" if decision_source == "llm" else "fallback",
        llm_error=llm_error,
    )


def action_for_status(status: CaseReviewStatus) -> str:
    if status == "auto_ready":
        return "Ready for Cab Ops recovery package"
    if status == "missing_evidence":
        return "Review manually because source text is missing"
    if status == "contradiction":
        return "Manual review required due to conflicting evidence"
    if status == "failed":
        return "Manual review required because investigation failed"
    return "Review before operational action"


def primary_source(case: ClaimCase) -> tuple[str, str, str, str] | None:
    evidence_by_source: dict[str, tuple[str, str]] = {}
    for item in case.evidence:
        if item.status != "available":
            continue
        source_field = clean_text(item.fields.get("source_field"))
        if source_field not in SOURCE_HIERARCHY:
            source_field = source_from_evidence_id(item.id)
        if source_field not in SOURCE_HIERARCHY:
            continue
        source_text = clean_text(item.fields.get("text") or item.fields.get(source_field))
        if not source_text and source_field == "comments":
            source_text = clean_text(item.fields.get("comments"))
        if not source_text and source_field == "remarks":
            source_text = clean_text(item.fields.get("Remarks") or item.fields.get("remarks"))
        if not source_text and source_field == "sub_category":
            source_text = clean_text(item.fields.get("Sub Category") or item.fields.get("sub_category"))
        if source_text:
            evidence_by_source[source_field] = (source_text, item.id)

    case_values = {
        "comments": case.comments,
        "remarks": case.remarks,
        "sub_category": case.sub_category,
    }
    for source_field in SOURCE_HIERARCHY:
        if source_field in evidence_by_source:
            source_text, evidence_id = evidence_by_source[source_field]
            return source_field, SOURCE_LABELS[source_field], source_text, evidence_id
        source_text = clean_text(case_values[source_field])
        if source_text:
            return source_field, SOURCE_LABELS[source_field], source_text, f"{case.booking_id}:{source_field}"
    return None


def source_from_evidence_id(evidence_id: str) -> str:
    for source_field in SOURCE_HIERARCHY:
        if evidence_id.endswith(f":{source_field}"):
            return source_field
    return ""


def categories_from_source(source_field: str, source_text: str) -> list[str]:
    message = build_fallback_message(
        sub_category=source_text if source_field == "sub_category" else "",
        remarks=source_text if source_field == "remarks" else "",
        comments=source_text if source_field == "comments" else "",
    )
    return [category.strip() for category in message.split(" + ") if category.strip()]


def agent_name_for_categories(categories: list[str]) -> str:
    if not categories:
        return "Source Hierarchy Agent"
    return AGENT_BY_CATEGORY.get(categories[0], "Source Hierarchy Agent")


def critical_missing(case: ClaimCase) -> bool:
    return primary_source(case) is None


def contradiction_detected(case: ClaimCase) -> bool:
    source = primary_source(case)
    if source is None:
        return False
    _source_field, _source_label, source_text, _evidence_id = source
    return bool(
        re.search(
            (
                r"\b(no complaint|no issue|issue resolved|complaint resolved|wrong penalty|"
                r"incorrect penalty|false claim|invalid penalty|penalty not valid|not genuine|"
                r"customer denied|denied complaint)\b"
            ),
            source_text,
            re.I,
        )
    )


def apply_judge_guardrails(case: ClaimCase, decision: AgentDecision) -> AgentDecision:
    if critical_missing(case):
        return apply_guardrail_status(
            decision,
            review_status="missing_evidence",
            confidence_cap=0.58,
            reason="Judge guardrail routed to review because comments, Remarks, and Sub Category are unavailable.",
        )
    if contradiction_detected(case):
        return apply_guardrail_status(
            decision,
            review_status="contradiction",
            confidence_cap=0.7,
            reason="Judge guardrail found a possible contradiction in the selected source text.",
        )
    if not decision.evidence_ids:
        return apply_guardrail_status(
            decision,
            review_status="needs_review",
            confidence_cap=0.84,
            reason="Judge guardrail routed to review because no supporting evidence IDs were cited.",
        )
    return promote_to_auto_ready(decision, case)


def promote_to_auto_ready(decision: AgentDecision, case: ClaimCase) -> AgentDecision:
    return AgentDecision(
        agent=decision.agent,
        decision="valid_penalty",
        complaint_categories=decision.complaint_categories,
        confidence=max(decision.confidence, 0.86),
        recommended_recovery_amount=case.recoverable_amount,
        rationale=decision.rationale,
        recommended_action=action_for_status("auto_ready"),
        review_status="auto_ready",
        review_reason="Judge approved: selected source text is present and has no explicit invalid-penalty signal.",
        evidence_ids=decision.evidence_ids,
        decision_source=decision.decision_source,
        llm_error=decision.llm_error,
    )


def guardrail_payload(case: ClaimCase) -> dict[str, Any]:
    source = primary_source(case)
    return {
        "critical_missing": critical_missing(case),
        "possible_contradiction": contradiction_detected(case),
        "source_priority": list(SOURCE_HIERARCHY),
        "selected_source": source[0] if source else "",
        "available_evidence_ids": source_evidence_ids(case),
        "missing_evidence_ids": [item.id for item in case.evidence if item.status == "missing"],
        "error_evidence_ids": [item.id for item in case.evidence if item.status == "error"],
    }


def case_evidence_ids(case: ClaimCase) -> set[str]:
    return set(source_evidence_ids(case))


def source_evidence_ids(case: ClaimCase) -> list[str]:
    source = primary_source(case)
    return [source[3]] if source else []


def llm_error_label(error: Exception) -> str:
    if isinstance(error, AgentLlmError):
        return str(error)
    message = clean_text(error)
    if not message:
        message = type(error).__name__
    return message[:180]
