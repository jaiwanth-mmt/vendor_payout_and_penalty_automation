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
from backend.app.agents.models import AgentDecision, AgentTraceStep, CaseReviewStatus, ClaimCase, clean_number, clean_text
from backend.app.domain.complaint_message import build_fallback_message, classify_cab_delay_window


CAB_DELAY_CATEGORY = "Cab Delay"
EXTRA_MONEY_TAKEN_CATEGORY = "Extra Money Taken"
FULFILLMENT_NOT_DONE_CATEGORY = "FULFILLMENT NOT DONE"
LOWER_CATEGORY_VEHICLE_CATEGORY = "Lower Category Vehicle"


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
    normalized_category = case.sub_category.strip().casefold()
    if normalized_category == CAB_DELAY_CATEGORY.casefold():
        decision, trace = cab_delay_agent(case)
    elif normalized_category == EXTRA_MONEY_TAKEN_CATEGORY.casefold():
        decision, trace = extra_money_agent(case)
    elif normalized_category == FULFILLMENT_NOT_DONE_CATEGORY.casefold():
        decision, trace = fulfillment_agent(case)
    elif normalized_category == LOWER_CATEGORY_VEHICLE_CATEGORY.casefold():
        decision, trace = lower_category_vehicle_agent(case)
    else:
        decision, trace = generic_complaint_agent(case)

    return decision, trace


def cab_delay_agent(case: ClaimCase) -> tuple[AgentDecision, list[AgentTraceStep]]:
    timing = evidence_fields(case, "timing")
    comments = evidence_fields(case, "comments").get("comments", "")
    delay_minutes = first_number(
        timing.get("boarded_after_pickup_minutes"),
        timing.get("driver_arrived_after_pickup_minutes"),
        timing.get("driver_started_after_pickup_minutes"),
    )
    has_tracking = evidence_status(case, "tracking") == "available"
    has_comments = bool(clean_text(comments))
    text_window = classify_cab_delay_window(" ".join([case.remarks, clean_text(comments)]))
    evidence_ids = available_ids(case, ["penalty", "timing", "comments"])

    if not has_tracking:
        confidence = 0.58 if has_comments else 0.35
        status: CaseReviewStatus = "missing_evidence"
        reason = "Tracking timing evidence is missing."
    elif delay_minutes is not None and delay_minutes > 15:
        confidence = 0.92 if has_comments else 0.86
        status = "auto_ready"
        reason = "Tracking supports delay beyond the operational threshold."
    elif text_window != "Cab Delay" and has_comments:
        confidence = 0.74
        status = "needs_review"
        reason = "Customer comment reports delay, but tracking delay threshold is not fully supported."
    else:
        confidence = 0.61 if has_comments else 0.52
        status = "needs_review"
        reason = "Cab delay evidence is partial."

    category = text_window if text_window else "Cab Delay"
    rationale = build_sentence(
        [
            f"Cab delay investigation selected {category}.",
            f"Observed delay was {delay_minutes:g} minutes." if delay_minutes is not None else "",
            "Customer comments are available." if has_comments else "Customer comments are unavailable.",
        ]
    )
    decision = make_decision(
        agent="Cab Delay Agent",
        decision="valid_penalty" if confidence >= 0.7 else "needs_review",
        categories=[category],
        confidence=confidence,
        amount=case.recoverable_amount,
        rationale=rationale,
        status=status,
        reason=reason,
        evidence_ids=evidence_ids,
    )
    trace = [
        AgentTraceStep(
            agent="Cab Delay Agent",
            action="compare_pickup_timeline",
            status="completed" if has_tracking else "warning",
            summary=rationale,
            evidence_ids=evidence_ids,
            metadata={"delay_minutes": delay_minutes, "text_window": category},
        )
    ]
    return decision, trace


def extra_money_agent(case: ClaimCase) -> tuple[AgentDecision, list[AgentTraceStep]]:
    comments = clean_text(evidence_fields(case, "comments").get("comments", ""))
    fare = evidence_fields(case, "fare")
    has_comment_signal = bool(re.search(r"\b(extra|cash|collect|charged|parking|toll|overcharg)", comments, re.I))
    charge_fields = [
        "cash_collected",
        "route_toll_charges",
        "toll_charges",
        "parking_charges",
        "airport_entry_fee",
        "extra_travelled_fare",
        "waiting_charges",
    ]
    populated_charge_fields = [field for field in charge_fields if clean_text(fare.get(field))]
    evidence_ids = available_ids(case, ["penalty", "comments", "fare"])

    if has_comment_signal and populated_charge_fields:
        confidence = 0.9
        status: CaseReviewStatus = "auto_ready"
        reason = "Customer comment and fare/payment evidence both support an extra-money claim."
    elif has_comment_signal:
        confidence = 0.72
        status = "needs_review"
        reason = "Customer comment supports extra-money claim, but fare/payment evidence is incomplete."
    elif populated_charge_fields:
        confidence = 0.62
        status = "needs_review"
        reason = "Fare/payment fields exist, but customer comment support is missing."
    else:
        confidence = 0.38
        status = "missing_evidence"
        reason = "No extra-money comment or fare/payment evidence was available."

    rationale = build_sentence(
        [
            "Extra Money Taken investigation reviewed customer comments and fare/payment fields.",
            f"Charge fields available: {', '.join(populated_charge_fields)}." if populated_charge_fields else "",
        ]
    )
    decision = make_decision(
        agent="Extra Money Taken Agent",
        decision="valid_penalty" if confidence >= 0.85 else "needs_review",
        categories=["Extra Money Taken"],
        confidence=confidence,
        amount=case.recoverable_amount,
        rationale=rationale,
        status=status,
        reason=reason,
        evidence_ids=evidence_ids,
    )
    trace = [
        AgentTraceStep(
            agent="Extra Money Taken Agent",
            action="compare_comments_with_fare_evidence",
            status="completed" if evidence_ids else "warning",
            summary=rationale,
            evidence_ids=evidence_ids,
            metadata={"charge_fields": populated_charge_fields},
        )
    ]
    return decision, trace


def fulfillment_agent(case: ClaimCase) -> tuple[AgentDecision, list[AgentTraceStep]]:
    status_fields = evidence_fields(case, "status")
    timing = evidence_fields(case, "timing")
    comments = clean_text(evidence_fields(case, "comments").get("comments", ""))
    status_text = " ".join(clean_text(value) for value in status_fields.values())
    comment_signal = bool(re.search(r"\b(no show|not arrive|did not arrive|not boarded|unfulfill)", comments, re.I))
    status_signal = bool(re.search(r"\b(not boarded|unfulfilled|no show|cancel)", status_text, re.I))
    has_timing = any(clean_text(timing.get(field)) for field in ["driver_started_ist", "driver_arrived_ist"])
    evidence_ids = available_ids(case, ["penalty", "status", "timing", "comments"])

    if status_signal and comment_signal:
        confidence = 0.91
        review_status: CaseReviewStatus = "auto_ready"
        reason = "Tracking status and customer comment both support fulfillment failure."
    elif status_signal or comment_signal:
        confidence = 0.73 if has_timing else 0.66
        review_status = "needs_review"
        reason = "Fulfillment failure evidence is present but not fully corroborated."
    else:
        confidence = 0.42
        review_status = "missing_evidence"
        reason = "No clear fulfillment failure signal was found."

    rationale = build_sentence(
        [
            "Fulfillment agent checked booking status, tracking status, driver movement, and comments.",
            f"Status evidence: {status_text}." if status_text else "",
        ]
    )
    decision = make_decision(
        agent="Fulfillment Not Done Agent",
        decision="valid_penalty" if confidence >= 0.85 else "needs_review",
        categories=["Vendor No Show"],
        confidence=confidence,
        amount=case.recoverable_amount,
        rationale=rationale,
        status=review_status,
        reason=reason,
        evidence_ids=evidence_ids,
    )
    trace = [
        AgentTraceStep(
            agent="Fulfillment Not Done Agent",
            action="verify_no_show_or_not_boarded_status",
            status="completed" if evidence_ids else "warning",
            summary=rationale,
            evidence_ids=evidence_ids,
            metadata={"status_signal": status_signal, "comment_signal": comment_signal},
        )
    ]
    return decision, trace


def lower_category_vehicle_agent(case: ClaimCase) -> tuple[AgentDecision, list[AgentTraceStep]]:
    vehicle = evidence_fields(case, "vehicle")
    comments = clean_text(evidence_fields(case, "comments").get("comments", ""))
    comment_signal = bool(re.search(r"\b(low|lower|downgrad|booked|received|instead|hatchback|sedan|suv|cng|electric)", comments, re.I))
    has_vehicle_tracking = bool(vehicle)
    evidence_ids = available_ids(case, ["penalty", "vehicle", "comments"])

    if comment_signal and has_vehicle_tracking:
        confidence = 0.88
        status: CaseReviewStatus = "auto_ready"
        reason = "Customer comment and tracking vehicle evidence support lower-category claim."
    elif comment_signal:
        confidence = 0.73
        status = "needs_review"
        reason = "Customer comment supports lower-category claim, but tracking vehicle evidence is incomplete."
    elif has_vehicle_tracking:
        confidence = 0.6
        status = "needs_review"
        reason = "Vehicle tracking fields exist, but customer comment support is missing."
    else:
        confidence = 0.4
        status = "missing_evidence"
        reason = "Vehicle category evidence is unavailable."

    rationale = build_sentence(
        [
            "Lower Category Vehicle agent compared customer complaint text with tracked vehicle category.",
            vehicle_summary(vehicle),
        ]
    )
    decision = make_decision(
        agent="Lower Category Vehicle Agent",
        decision="valid_penalty" if confidence >= 0.85 else "needs_review",
        categories=["Low Category Vehicle"],
        confidence=confidence,
        amount=case.recoverable_amount,
        rationale=rationale,
        status=status,
        reason=reason,
        evidence_ids=evidence_ids,
    )
    trace = [
        AgentTraceStep(
            agent="Lower Category Vehicle Agent",
            action="compare_booked_and_received_vehicle",
            status="completed" if evidence_ids else "warning",
            summary=rationale,
            evidence_ids=evidence_ids,
            metadata={"tracking_vehicle": vehicle},
        )
    ]
    return decision, trace


def generic_complaint_agent(case: ClaimCase) -> tuple[AgentDecision, list[AgentTraceStep]]:
    comments = clean_text(evidence_fields(case, "comments").get("comments", ""))
    category = build_fallback_message(sub_category=case.sub_category, remarks=case.remarks, comments=comments)
    has_comments = bool(comments)
    has_tracking = evidence_status(case, "tracking") == "available"
    confidence = 0.76 if has_comments and has_tracking else 0.62 if has_comments or has_tracking else 0.5
    status: CaseReviewStatus = "needs_review" if confidence < 0.85 else "auto_ready"
    if not has_comments and not has_tracking:
        status = "missing_evidence"
    reason = "Generic complaint agent found partial support; specialist logic is not yet available for this category."
    evidence_ids = available_ids(case, ["penalty", "tracking", "comments"])
    rationale = (
        f"Generic agent mapped {case.sub_category} to {category} using remarks, comments, and available tracking context."
    )
    decision = make_decision(
        agent="Generic Complaint Agent",
        decision="needs_review",
        categories=category.split(" + "),
        confidence=confidence,
        amount=case.recoverable_amount,
        rationale=rationale,
        status=status,
        reason=reason,
        evidence_ids=evidence_ids,
    )
    trace = [
        AgentTraceStep(
            agent="Generic Complaint Agent",
            action="classify_with_generic_policy",
            status="completed" if evidence_ids else "warning",
            summary=rationale,
            evidence_ids=evidence_ids,
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

    if specialist.confidence >= 0.85 and evidence_ids and not critical_missing(case):
        review_status = "auto_ready"
        reason = "Judge approved: specialist decision is supported by available evidence."
    elif critical_missing(case):
        review_status = "missing_evidence"
        confidence = min(confidence, 0.58)
        reason = "Judge routed to review because required evidence is missing."
    elif specialist.confidence < 0.6:
        review_status = "needs_review"
        reason = "Judge routed to review because confidence is below the auto-ready threshold."
    elif contradiction_detected(case):
        review_status = "contradiction"
        confidence = min(confidence, 0.7)
        reason = "Judge found a possible contradiction between comments and tracking evidence."

    decision = make_decision(
        agent="Judge Agent",
        decision=specialist.decision if review_status == "auto_ready" else "needs_review",
        categories=specialist.complaint_categories,
        confidence=confidence,
        amount=specialist.recommended_recovery_amount,
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
            metadata={"missing_evidence_count": len(missing_evidence), "confidence": confidence},
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
        return "Fetch missing evidence or review manually"
    if status == "contradiction":
        return "Manual review required due to conflicting evidence"
    if status == "failed":
        return "Manual review required because investigation failed"
    return "Review before operational action"


def evidence_fields(case: ClaimCase, suffix: str) -> dict[str, Any]:
    evidence = next((item for item in case.evidence if item.id.endswith(f":{suffix}")), None)
    return evidence.fields if evidence and evidence.status == "available" else {}


def evidence_status(case: ClaimCase, suffix: str) -> str:
    evidence = next((item for item in case.evidence if item.id.endswith(f":{suffix}")), None)
    return evidence.status if evidence else "missing"


def available_ids(case: ClaimCase, suffixes: list[str]) -> list[str]:
    selected: list[str] = []
    for suffix in suffixes:
        evidence = next((item for item in case.evidence if item.id.endswith(f":{suffix}")), None)
        if evidence and evidence.status == "available":
            selected.append(evidence.id)
    return selected


def first_number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        number = clean_number(value)
        if number or str(value).strip() in {"0", "0.0"}:
            return number
    return None


def build_sentence(parts: list[str]) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def vehicle_summary(vehicle: dict[str, Any]) -> str:
    if not vehicle:
        return "No tracked vehicle category was available."
    return "Tracked vehicle fields: " + ", ".join(f"{key}={value}" for key, value in vehicle.items()) + "."


def critical_missing(case: ClaimCase) -> bool:
    category = case.sub_category.casefold()
    if category == CAB_DELAY_CATEGORY.casefold():
        return evidence_status(case, "timing") != "available"
    if category == EXTRA_MONEY_TAKEN_CATEGORY.casefold():
        return evidence_status(case, "comments") != "available" and evidence_status(case, "fare") != "available"
    if category == FULFILLMENT_NOT_DONE_CATEGORY.casefold():
        return evidence_status(case, "status") != "available" and evidence_status(case, "comments") != "available"
    if category == LOWER_CATEGORY_VEHICLE_CATEGORY.casefold():
        return evidence_status(case, "vehicle") != "available" and evidence_status(case, "comments") != "available"
    return evidence_status(case, "comments") != "available" and evidence_status(case, "tracking") != "available"


def contradiction_detected(case: ClaimCase) -> bool:
    category = case.sub_category.casefold()
    comments = clean_text(evidence_fields(case, "comments").get("comments", ""))
    if not comments:
        return False

    if category == CAB_DELAY_CATEGORY.casefold():
        timing = evidence_fields(case, "timing")
        delay_minutes = first_number(
            timing.get("boarded_after_pickup_minutes"),
            timing.get("driver_arrived_after_pickup_minutes"),
            timing.get("driver_started_after_pickup_minutes"),
        )
        if delay_minutes is not None and delay_minutes <= 5 and re.search(r"\b(delay|late|wait)", comments, re.I):
            return True
    return False


def apply_judge_guardrails(case: ClaimCase, decision: AgentDecision) -> AgentDecision:
    if critical_missing(case):
        return apply_guardrail_status(
            decision,
            review_status="missing_evidence",
            confidence_cap=0.58,
            reason="Judge guardrail routed to review because required evidence is missing.",
        )
    if contradiction_detected(case):
        return apply_guardrail_status(
            decision,
            review_status="contradiction",
            confidence_cap=0.7,
            reason="Judge guardrail found a possible contradiction between comments and tracking evidence.",
        )
    if decision.review_status == "auto_ready" and decision.confidence < 0.85:
        return apply_guardrail_status(
            decision,
            review_status="needs_review",
            confidence_cap=0.84,
            reason="Judge guardrail routed to review because confidence is below the auto-ready threshold.",
        )
    if decision.review_status == "auto_ready" and not decision.evidence_ids:
        return apply_guardrail_status(
            decision,
            review_status="needs_review",
            confidence_cap=0.84,
            reason="Judge guardrail routed to review because no supporting evidence IDs were cited.",
        )
    return decision


def guardrail_payload(case: ClaimCase) -> dict[str, Any]:
    return {
        "critical_missing": critical_missing(case),
        "possible_contradiction": contradiction_detected(case),
        "available_evidence_ids": [item.id for item in case.evidence if item.status == "available"],
        "missing_evidence_ids": [item.id for item in case.evidence if item.status == "missing"],
        "error_evidence_ids": [item.id for item in case.evidence if item.status == "error"],
    }


def case_evidence_ids(case: ClaimCase) -> set[str]:
    return {item.id for item in case.evidence}


def llm_error_label(error: Exception) -> str:
    if isinstance(error, AgentLlmError):
        return str(error)
    message = clean_text(error)
    if not message:
        message = type(error).__name__
    return message[:180]
