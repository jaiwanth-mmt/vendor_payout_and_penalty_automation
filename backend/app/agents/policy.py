"""Deterministic specialist/judge policy and guardrails used by LangGraph nodes."""

from __future__ import annotations

from typing import Any

from backend.app.agents.llm import AgentLlmError, apply_guardrail_status
from backend.app.agents.models import AgentDecision, CaseReviewStatus, ClaimCase, clean_text
from backend.app.agents.source_alignment import build_source_alignment, format_categories


CAB_DELAY_CATEGORY = "Cab Delay"
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
HITL_REVIEW_STATUSES = frozenset({"needs_review", "missing_evidence"})


def claim_case_from_state(state: dict[str, Any], *, evidence: list[dict[str, Any]] | None = None) -> ClaimCase:
    case = ClaimCase(
        booking_id=clean_text(state.get("booking_id")),
        sub_category=clean_text(state.get("sub_category")) or "Uncategorized",
        remarks=clean_text(state.get("remarks")),
        recoverable_amount=float(state.get("recoverable_amount") or 0),
        row_index=int(state.get("row_index") or 0),
        comments=clean_text(state.get("comments")),
        message=clean_text(state.get("message")),
        vendor_name=clean_text(state.get("vendor_name")) or "Unknown vendor",
        source_analysis=dict(state.get("source_analysis") or {}),
    )
    if evidence:
        from backend.app.agents.models import EvidenceItem

        for item in evidence:
            case.evidence.append(
                EvidenceItem(
                    id=str(item.get("id", "")),
                    title=str(item.get("title", "")),
                    source=str(item.get("source", "")),
                    status=item.get("status") or "missing",
                    summary=str(item.get("summary", "")),
                    fields=dict(item.get("fields") or {}),
                    error=item.get("error"),
                )
            )
    return case


def ensure_source_analysis(case: ClaimCase) -> dict[str, Any]:
    if not case.source_analysis:
        case.source_analysis = build_source_alignment(case).to_dict()
    return case.source_analysis


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


def agent_name_for_categories(categories: list[str]) -> str:
    if not categories:
        return "Source Alignment Agent"
    return AGENT_BY_CATEGORY.get(categories[0], "Source Alignment Agent")


def primary_source(case: ClaimCase) -> tuple[str, str, str, str] | None:
    analysis = ensure_source_analysis(case)
    source_field = clean_text(analysis.get("primary_source"))
    if source_field not in SOURCE_HIERARCHY:
        return None
    source_text = clean_text(analysis.get("source_text"))
    evidence_id = clean_text(analysis.get("source_evidence_id")) or f"{case.booking_id}:{source_field}"
    if not source_text:
        return None
    return source_field, SOURCE_LABELS[source_field], source_text, evidence_id


def build_specialist_decision(case: ClaimCase) -> tuple[AgentDecision, list[dict[str, Any]]]:
    analysis = ensure_source_analysis(case)
    source = primary_source(case)
    if source is None:
        decision = make_decision(
            agent="Source Alignment Agent",
            decision="needs_review",
            categories=[],
            confidence=0.35,
            amount=0,
            rationale=clean_text(analysis.get("reason")) or "Agent review could not find a usable source text.",
            status="missing_evidence",
            reason=clean_text(analysis.get("reason")) or "No comments, Remarks, or mappable Sub Category were available.",
            evidence_ids=[],
        )
        return decision, [
            {
                "agent": "Source Alignment Agent",
                "action": "apply_source_alignment",
                "status": "warning",
                "summary": decision.review_reason,
                "evidence_ids": [],
                "metadata": {"source_priority": list(SOURCE_HIERARCHY), "source_alignment_status": "missing_evidence"},
            }
        ]

    source_field, source_label, _source_text, evidence_id = source
    categories = list(analysis.get("source_categories") or [])
    agent_name = agent_name_for_categories(categories)
    alignment_status = clean_text(analysis.get("status"))
    if clean_text(analysis.get("review_status")) != "auto_ready":
        confidence = 0.55
        status: CaseReviewStatus = "needs_review"
        decision_value = "needs_review"
        reason = clean_text(analysis.get("reason")) or f"{source_label} did not align with row context."
    else:
        confidence = SOURCE_CONFIDENCE[source_field]
        status = "auto_ready"
        decision_value = "valid_penalty"
        reason = clean_text(analysis.get("reason")) or f"{source_label} aligns with row context."

    rationale = (
        f"Agent compared {source_label} categories ({format_categories(categories)}) "
        f"with row categories ({format_categories(list(analysis.get('row_categories') or []))})."
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
    return decision, [
        {
            "agent": agent_name,
            "action": "apply_source_alignment",
            "status": "completed" if status == "auto_ready" else "warning",
            "summary": reason,
            "evidence_ids": [evidence_id],
            "metadata": {
                "primary_source": source_field,
                "source_alignment_status": alignment_status,
                "source_priority": list(SOURCE_HIERARCHY),
            },
        }
    ]


def critical_missing(case: ClaimCase) -> bool:
    return clean_text(ensure_source_analysis(case).get("review_status")) == "missing_evidence"


def source_alignment_needs_review(case: ClaimCase) -> bool:
    return clean_text(ensure_source_analysis(case).get("review_status")) == "needs_review"


def build_judge_decision(case: ClaimCase) -> tuple[AgentDecision, list[dict[str, Any]]]:
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

    analysis = ensure_source_analysis(case)
    evidence_ids = specialist.evidence_ids
    review_status: CaseReviewStatus = specialist.review_status
    confidence = specialist.confidence
    reason = specialist.review_reason
    amount = specialist.recommended_recovery_amount

    if critical_missing(case):
        review_status = "missing_evidence"
        confidence = min(confidence, 0.58)
        reason = clean_text(analysis.get("reason")) or "Judge routed to review because comments and Remarks are unavailable."
    elif source_alignment_needs_review(case):
        review_status = "needs_review"
        confidence = min(confidence, 0.75)
        reason = clean_text(analysis.get("reason")) or "Judge routed to review because source categories do not align."
    elif evidence_ids:
        review_status = "auto_ready"
        confidence = max(confidence, 0.86)
        amount = case.recoverable_amount
        reason = clean_text(analysis.get("reason")) or "Judge approved: primary source aligns with row context."
    else:
        review_status = "needs_review"
        reason = "Judge routed to review because no source evidence ID was cited."

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
    return decision, [
        {
            "agent": "Judge Agent",
            "action": "verify_specialist_decision",
            "status": "completed" if review_status == "auto_ready" else "warning",
            "summary": reason,
            "evidence_ids": evidence_ids,
            "metadata": {
                "source_alignment_status": clean_text(analysis.get("status")),
                "confidence": confidence,
            },
        }
    ]


def apply_judge_guardrails(case: ClaimCase, decision: AgentDecision) -> AgentDecision:
    if critical_missing(case):
        return apply_guardrail_status(
            decision,
            review_status="missing_evidence",
            confidence_cap=0.58,
            reason=clean_text(ensure_source_analysis(case).get("reason"))
            or "Judge guardrail routed to review because comments and Remarks are unavailable.",
        )
    if source_alignment_needs_review(case):
        return apply_guardrail_status(
            decision,
            review_status="needs_review",
            confidence_cap=0.75,
            reason=clean_text(ensure_source_analysis(case).get("reason"))
            or "Judge guardrail routed to review because source categories do not align.",
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
        review_reason=clean_text(ensure_source_analysis(case).get("reason"))
        or "Judge approved: primary source aligns with row context.",
        evidence_ids=decision.evidence_ids,
        decision_source=decision.decision_source,
        llm_error=decision.llm_error,
    )


def apply_source_categories(case: ClaimCase, decision: AgentDecision) -> AgentDecision:
    categories = list(ensure_source_analysis(case).get("source_categories") or [])
    if not categories:
        return decision
    return AgentDecision(
        agent=decision.agent,
        decision=decision.decision,
        complaint_categories=categories,
        confidence=decision.confidence,
        recommended_recovery_amount=decision.recommended_recovery_amount,
        rationale=decision.rationale,
        recommended_action=decision.recommended_action,
        review_status=decision.review_status,
        review_reason=decision.review_reason,
        evidence_ids=decision.evidence_ids,
        decision_source=decision.decision_source,
        llm_error=decision.llm_error,
    )


def guardrail_payload(case: ClaimCase) -> dict[str, Any]:
    source = primary_source(case)
    analysis = ensure_source_analysis(case)
    return {
        "critical_missing": critical_missing(case),
        "requires_review": source_alignment_needs_review(case),
        "source_priority": list(SOURCE_HIERARCHY),
        "selected_source": source[0] if source else "",
        "source_alignment": analysis,
        "available_evidence_ids": [item.id for item in case.evidence if item.status == "available"],
        "missing_evidence_ids": [item.id for item in case.evidence if item.status == "missing"],
        "error_evidence_ids": [item.id for item in case.evidence if item.status == "error"],
        "tracking_tools_available": True,
    }


def llm_error_label(error: Exception) -> str:
    if isinstance(error, AgentLlmError):
        return str(error)
    message = clean_text(error)
    if not message:
        message = type(error).__name__
    return message[:180]


def decision_from_dict(payload: dict[str, Any] | None) -> AgentDecision | None:
    if not payload:
        return None
    return AgentDecision(
        agent=str(payload.get("agent") or "Agent"),
        decision=str(payload.get("decision") or "needs_review"),
        complaint_categories=list(payload.get("complaint_categories") or []),
        confidence=float(payload.get("confidence") or 0),
        recommended_recovery_amount=float(payload.get("recommended_recovery_amount") or 0),
        rationale=str(payload.get("rationale") or ""),
        recommended_action=str(payload.get("recommended_action") or ""),
        review_status=payload.get("review_status") or "needs_review",
        review_reason=str(payload.get("review_reason") or ""),
        evidence_ids=list(payload.get("evidence_ids") or []),
        decision_source=payload.get("decision_source") or "fallback",
        llm_error=payload.get("llm_error"),
    )


def merge_human_decision(judge: dict[str, Any], human: dict[str, Any]) -> dict[str, Any]:
    merged = dict(judge)
    if human.get("decision"):
        merged["decision"] = human["decision"]
    if human.get("review_status"):
        merged["review_status"] = human["review_status"]
    if "recommended_recovery_amount" in human:
        merged["recommended_recovery_amount"] = human["recommended_recovery_amount"]
    if human.get("review_reason"):
        merged["review_reason"] = human["review_reason"]
    if human.get("rationale"):
        merged["rationale"] = human["rationale"]
    if human.get("recommended_action"):
        merged["recommended_action"] = human["recommended_action"]
    merged["decision_source"] = "llm" if judge.get("decision_source") == "llm" else "fallback"
    merged["agent"] = "Human Review"
    merged["human_resolved"] = True
    return merged
