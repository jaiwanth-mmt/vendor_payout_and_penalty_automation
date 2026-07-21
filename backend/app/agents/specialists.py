"""Compatibility re-exports — policy lives in policy.py; async agents live in LangGraph nodes."""

from backend.app.agents.policy import (
    AGENT_BY_CATEGORY,
    CAB_DELAY_CATEGORY,
    SOURCE_CONFIDENCE,
    SOURCE_HIERARCHY,
    SOURCE_LABELS,
    action_for_status,
    agent_name_for_categories,
    apply_judge_guardrails,
    apply_source_categories,
    build_judge_decision,
    build_specialist_decision,
    critical_missing,
    ensure_source_analysis,
    guardrail_payload,
    llm_error_label,
    make_decision,
    primary_source,
    promote_to_auto_ready,
    source_alignment_needs_review,
)

EXTRA_MONEY_TAKEN_CATEGORY = "Extra Money Taken"
FULFILLMENT_NOT_DONE_CATEGORY = "FULFILLMENT NOT DONE"
LOWER_CATEGORY_VEHICLE_CATEGORY = "Lower Category Vehicle"


def run_specialist_agent(case):
    decision, trace = build_specialist_decision(case)
    from backend.app.agents.models import AgentTraceStep

    case.specialist_decision = decision
    case.trace.extend(
        [
            AgentTraceStep(
                agent=step["agent"],
                action=step["action"],
                status=step["status"],
                summary=step["summary"],
                evidence_ids=step.get("evidence_ids") or [],
                metadata=step.get("metadata") or {},
            )
            for step in trace
        ]
    )


def run_judge_agent(case):
    decision, trace = build_judge_decision(case)
    from backend.app.agents.models import AgentTraceStep

    case.judge_decision = decision
    case.trace.extend(
        [
            AgentTraceStep(
                agent=step["agent"],
                action=step["action"],
                status=step["status"],
                summary=step["summary"],
                evidence_ids=step.get("evidence_ids") or [],
                metadata=step.get("metadata") or {},
            )
            for step in trace
        ]
    )


async def run_specialist_agent_async(case, *, llm_generator, semaphore):
    from backend.app.agents.nodes.investigation import specialist_node

    state = {
        "booking_id": case.booking_id,
        "sub_category": case.sub_category,
        "remarks": case.remarks,
        "comments": case.comments,
        "message": case.message,
        "vendor_name": case.vendor_name,
        "recoverable_amount": case.recoverable_amount,
        "row_index": case.row_index,
        "source_analysis": case.source_analysis,
        "evidence": [item.to_dict() for item in case.evidence],
        "trace": [],
        "tool_calls": [],
        "job_id": "",
        "tracking_context": {},
        "messages": [],
    }
    update = await specialist_node(state, llm_generator=llm_generator, semaphore=semaphore)
    from backend.app.agents.policy import decision_from_dict
    from backend.app.agents.models import AgentTraceStep

    if update.get("source_analysis"):
        case.source_analysis = update["source_analysis"]
    case.specialist_decision = decision_from_dict(update.get("specialist_decision"))
    for step in update.get("trace") or []:
        case.trace.append(
            AgentTraceStep(
                agent=step["agent"],
                action=step["action"],
                status=step["status"],
                summary=step["summary"],
                evidence_ids=step.get("evidence_ids") or [],
                metadata=step.get("metadata") or {},
            )
        )


async def run_judge_agent_async(case, *, llm_generator, semaphore):
    from backend.app.agents.nodes.investigation import judge_node
    from backend.app.agents.policy import decision_from_dict
    from backend.app.agents.models import AgentTraceStep

    state = {
        "booking_id": case.booking_id,
        "sub_category": case.sub_category,
        "remarks": case.remarks,
        "comments": case.comments,
        "message": case.message,
        "vendor_name": case.vendor_name,
        "recoverable_amount": case.recoverable_amount,
        "row_index": case.row_index,
        "source_analysis": case.source_analysis,
        "evidence": [item.to_dict() for item in case.evidence],
        "specialist_decision": case.specialist_decision.to_dict() if case.specialist_decision else None,
        "trace": [],
        "tool_calls": [],
        "job_id": "",
        "tracking_context": {},
        "messages": [],
    }
    update = await judge_node(state, llm_generator=llm_generator, semaphore=semaphore)
    if update.get("source_analysis"):
        case.source_analysis = update["source_analysis"]
    case.judge_decision = decision_from_dict(update.get("judge_decision"))
    for step in update.get("trace") or []:
        case.trace.append(
            AgentTraceStep(
                agent=step["agent"],
                action=step["action"],
                status=step["status"],
                summary=step["summary"],
                evidence_ids=step.get("evidence_ids") or [],
                metadata=step.get("metadata") or {},
            )
        )


def contradiction_detected(case) -> bool:
    analysis = ensure_source_analysis(case)
    from backend.app.agents.models import clean_text

    return clean_text(analysis.get("status")) == "invalid_signal"


def source_from_evidence_id(evidence_id: str) -> str:
    for source_field in ("comments", "remarks", "sub_category"):
        if evidence_id.endswith(f":{source_field}"):
            return source_field
    return ""


def case_evidence_ids(case) -> set[str]:
    return set(source_evidence_ids(case))


def source_evidence_ids(case) -> list[str]:
    evidence_ids: list[str] = []
    for item in case.evidence:
        from backend.app.agents.models import clean_text

        source_field = clean_text(item.fields.get("source_field")) or source_from_evidence_id(item.id)
        if item.source in {"source_alignment", "tracking"} or source_field in {
            "comments",
            "remarks",
            "sub_category",
            "source_alignment",
            "tracking",
        }:
            if item.id not in evidence_ids:
                evidence_ids.append(item.id)
    if not evidence_ids:
        source = primary_source(case)
        if source:
            evidence_ids.append(source[3])
    return evidence_ids


__all__ = [
    "AGENT_BY_CATEGORY",
    "CAB_DELAY_CATEGORY",
    "EXTRA_MONEY_TAKEN_CATEGORY",
    "FULFILLMENT_NOT_DONE_CATEGORY",
    "LOWER_CATEGORY_VEHICLE_CATEGORY",
    "SOURCE_CONFIDENCE",
    "SOURCE_HIERARCHY",
    "SOURCE_LABELS",
    "action_for_status",
    "agent_name_for_categories",
    "apply_judge_guardrails",
    "apply_source_categories",
    "build_judge_decision",
    "build_specialist_decision",
    "case_evidence_ids",
    "contradiction_detected",
    "critical_missing",
    "ensure_source_analysis",
    "guardrail_payload",
    "llm_error_label",
    "make_decision",
    "primary_source",
    "promote_to_auto_ready",
    "run_judge_agent",
    "run_judge_agent_async",
    "run_specialist_agent",
    "run_specialist_agent_async",
    "source_alignment_needs_review",
    "source_evidence_ids",
    "source_from_evidence_id",
]
