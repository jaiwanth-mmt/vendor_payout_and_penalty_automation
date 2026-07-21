"""Investigation graph node functions."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.types import Command, interrupt

from backend.app.agents.llm import (
    AgentLlmGenerator,
    build_judge_prompt,
    build_specialist_prompt,
    decision_from_payload,
    mark_fallback,
    maybe_call_agent_llm,
    parse_json_object,
)
from backend.app.agents.models import clean_text
from backend.app.agents.nodes import booking_label, emit_custom, tool_call_record, trace_step
from backend.app.agents.policy import (
    HITL_REVIEW_STATUSES,
    apply_judge_guardrails,
    apply_source_categories,
    build_judge_decision,
    build_specialist_decision,
    claim_case_from_state,
    decision_from_dict,
    ensure_source_analysis,
    guardrail_payload,
    llm_error_label,
    merge_human_decision,
)
from backend.app.agents.source_alignment import build_source_alignment_async
from backend.app.agents.tools import INVESTIGATION_TOOLS


async def intake_node(state: dict[str, Any]) -> dict[str, Any]:
    booking_id = booking_label(state)
    emit_custom(
        {
            "type": "node",
            "node": "intake",
            "booking_id": booking_id,
            "status": "running",
            "summary": f"Normalizing claim case for {booking_id}",
        }
    )
    step = trace_step(
        agent="Intake Agent",
        action="normalize_claim_case",
        status="completed",
        summary=f"Created claim case for booking {booking_id} in {clean_text(state.get('sub_category')) or 'Uncategorized'}.",
    )
    emit_custom(
        {
            "type": "node",
            "node": "intake",
            "booking_id": booking_id,
            "status": "completed",
            "summary": step["summary"],
        }
    )
    return {"trace": [step], "pending_interrupt": False}


async def evidence_agent_node(
    state: dict[str, Any],
    *,
    llm_generator: AgentLlmGenerator | None = None,
    semaphore=None,
) -> dict[str, Any]:
    """Gather evidence by invoking investigation tools; optionally refresh source alignment via LLM."""
    booking_id = booking_label(state)
    emit_custom(
        {
            "type": "node",
            "node": "evidence_agent",
            "booking_id": booking_id,
            "status": "running",
            "summary": "Gathering evidence via LangGraph tools",
        }
    )

    case = claim_case_from_state(state)
    source_analysis = dict(state.get("source_analysis") or {})
    if llm_generator is not None:
        try:
            source_analysis = (
                await build_source_alignment_async(case, llm_generator=llm_generator, semaphore=semaphore)
            ).to_dict()
            case.source_analysis = source_analysis
        except Exception:
            source_analysis = ensure_source_analysis(case)
    else:
        source_analysis = ensure_source_analysis(case)

    # Inject analysis into tool-visible state before tool calls.
    tool_state = {**state, "source_analysis": source_analysis}
    evidence: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for tool in INVESTIGATION_TOOLS:
        try:
            raw = tool.invoke({"state": tool_state})
            if not isinstance(raw, dict):
                raise TypeError("tool returned non-dict")
            item = raw.get("evidence") or {}
            evidence_id = str(item.get("id") or "")
            if evidence_id and evidence_id not in seen_ids:
                evidence.append(item)
                seen_ids.add(evidence_id)
            if raw.get("tool") == "get_source_alignment" and isinstance(raw.get("analysis"), dict):
                source_analysis = raw["analysis"]
                tool_state["source_analysis"] = source_analysis
            record = tool_call_record(
                name=str(raw.get("tool") or tool.name),
                status="completed",
                summary=str((item or {}).get("summary") or f"{tool.name} completed"),
                result={"evidence_id": evidence_id, "status": item.get("status")},
            )
            tool_calls.append(record)
            emit_custom(
                {
                    "type": "tool",
                    "node": "evidence_agent",
                    "booking_id": booking_id,
                    "tool": record["name"],
                    "status": record["status"],
                    "summary": record["summary"],
                }
            )
        except Exception as error:
            record = tool_call_record(
                name=tool.name,
                status="failed",
                summary=f"{tool.name} failed: {llm_error_label(error)}",
            )
            tool_calls.append(record)
            emit_custom(
                {
                    "type": "tool",
                    "node": "evidence_agent",
                    "booking_id": booking_id,
                    "tool": tool.name,
                    "status": "failed",
                    "summary": record["summary"],
                }
            )

    alignment_status = clean_text(source_analysis.get("review_status"))
    step = trace_step(
        agent="Evidence Retrieval Agent",
        action="compare_sources",
        status="completed" if alignment_status == "auto_ready" else "warning",
        summary=clean_text(source_analysis.get("reason")) or "Evidence tools completed.",
        evidence_ids=[item["id"] for item in evidence if item.get("status") == "available"],
        metadata={
            "source_priority": ["comments", "remarks"],
            "primary_source": clean_text(source_analysis.get("primary_source")),
            "source_alignment_status": clean_text(source_analysis.get("status")),
            "tools": [call["name"] for call in tool_calls],
        },
    )
    emit_custom(
        {
            "type": "node",
            "node": "evidence_agent",
            "booking_id": booking_id,
            "status": "completed",
            "summary": step["summary"],
        }
    )
    return {
        "source_analysis": source_analysis,
        "evidence": evidence,
        "tool_calls": tool_calls,
        "trace": [step],
    }


async def specialist_node(
    state: dict[str, Any],
    *,
    llm_generator: AgentLlmGenerator | None = None,
    semaphore=None,
) -> dict[str, Any]:
    booking_id = booking_label(state)
    emit_custom(
        {
            "type": "node",
            "node": "specialist",
            "booking_id": booking_id,
            "status": "running",
            "summary": "Running category specialist",
        }
    )
    case = claim_case_from_state(state, evidence=list(state.get("evidence") or []))
    source_analysis_update: dict[str, Any] = {}
    if llm_generator is not None and not case.source_analysis:
        case.source_analysis = (
            await build_source_alignment_async(case, llm_generator=llm_generator, semaphore=semaphore)
        ).to_dict()
        source_analysis_update = {"source_analysis": case.source_analysis}
    fallback_decision, fallback_trace = build_specialist_decision(case)
    if llm_generator is None:
        case.specialist_decision = fallback_decision
        emit_custom(
            {
                "type": "node",
                "node": "specialist",
                "booking_id": booking_id,
                "status": "completed",
                "summary": fallback_decision.rationale,
            }
        )
        return {
            **source_analysis_update,
            "specialist_decision": fallback_decision.to_dict(),
            "trace": fallback_trace,
        }

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
            allowed_evidence_ids={item.get("id", "") for item in (state.get("evidence") or [])},
            default_agent=fallback_decision.agent,
            max_recovery_amount=case.recoverable_amount,
        )
        decision = apply_source_categories(case, decision)
        step = trace_step(
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
        emit_custom(
            {
                "type": "node",
                "node": "specialist",
                "booking_id": booking_id,
                "status": "completed",
                "summary": decision.rationale,
            }
        )
        return {**source_analysis_update, "specialist_decision": decision.to_dict(), "trace": [step]}
    except Exception as error:
        fallback_with_error = mark_fallback(fallback_decision, llm_error=llm_error_label(error))
        step = trace_step(
            agent=fallback_decision.agent,
            action="llm_decision_fallback",
            status="warning",
            summary="Specialist LLM output was unavailable or invalid; deterministic fallback decision was used.",
            evidence_ids=fallback_decision.evidence_ids,
            metadata={"llm_error": fallback_with_error.llm_error or "unknown"},
        )
        emit_custom(
            {
                "type": "node",
                "node": "specialist",
                "booking_id": booking_id,
                "status": "warning",
                "summary": step["summary"],
            }
        )
        return {
            **source_analysis_update,
            "specialist_decision": fallback_with_error.to_dict(),
            "trace": [*fallback_trace, step],
        }


async def judge_node(
    state: dict[str, Any],
    *,
    llm_generator: AgentLlmGenerator | None = None,
    semaphore=None,
) -> dict[str, Any]:
    booking_id = booking_label(state)
    emit_custom(
        {
            "type": "node",
            "node": "judge",
            "booking_id": booking_id,
            "status": "running",
            "summary": "Running judge verification",
        }
    )
    case = claim_case_from_state(state, evidence=list(state.get("evidence") or []))
    source_analysis_update: dict[str, Any] = {}
    if llm_generator is not None and not case.source_analysis:
        case.source_analysis = (
            await build_source_alignment_async(case, llm_generator=llm_generator, semaphore=semaphore)
        ).to_dict()
        source_analysis_update = {"source_analysis": case.source_analysis}
    case.specialist_decision = decision_from_dict(state.get("specialist_decision"))
    fallback_decision, fallback_trace = build_judge_decision(case)
    specialist = case.specialist_decision

    if llm_generator is None or specialist is None:
        emit_custom(
            {
                "type": "node",
                "node": "judge",
                "booking_id": booking_id,
                "status": "completed",
                "summary": fallback_decision.review_reason,
            }
        )
        return {
            **source_analysis_update,
            "judge_decision": fallback_decision.to_dict(),
            "trace": fallback_trace,
        }

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
            allowed_evidence_ids={item.get("id", "") for item in (state.get("evidence") or [])},
            default_agent="Judge Agent",
            max_recovery_amount=case.recoverable_amount,
        )
        decision = apply_source_categories(case, decision)
        decision = apply_judge_guardrails(case, decision)
        step = trace_step(
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
        emit_custom(
            {
                "type": "node",
                "node": "judge",
                "booking_id": booking_id,
                "status": "completed",
                "summary": decision.review_reason,
            }
        )
        return {**source_analysis_update, "judge_decision": decision.to_dict(), "trace": [step]}
    except Exception as error:
        fallback_with_error = mark_fallback(fallback_decision, llm_error=llm_error_label(error))
        step = trace_step(
            agent="Judge Agent",
            action="llm_judge_fallback",
            status="warning",
            summary="Judge LLM output was unavailable or invalid; deterministic guardrail decision was used.",
            evidence_ids=fallback_decision.evidence_ids,
            metadata={"llm_error": fallback_with_error.llm_error or "unknown"},
        )
        emit_custom(
            {
                "type": "node",
                "node": "judge",
                "booking_id": booking_id,
                "status": "warning",
                "summary": step["summary"],
            }
        )
        return {
            **source_analysis_update,
            "judge_decision": fallback_with_error.to_dict(),
            "trace": [*fallback_trace, step],
        }


def human_review_node(state: dict[str, Any]) -> Command[Literal["finalize"]]:
    booking_id = booking_label(state)
    judge = dict(state.get("judge_decision") or {})
    review_status = clean_text(judge.get("review_status"))
    if review_status not in HITL_REVIEW_STATUSES:
        emit_custom(
            {
                "type": "node",
                "node": "human_review",
                "booking_id": booking_id,
                "status": "skipped",
                "summary": "No human review required",
            }
        )
        return Command(goto="finalize", update={"pending_interrupt": False})

    emit_custom(
        {
            "type": "interrupt",
            "node": "human_review",
            "booking_id": booking_id,
            "status": "awaiting_review",
            "summary": judge.get("review_reason") or "Human review required",
            "payload": {
                "booking_id": booking_id,
                "sub_category": state.get("sub_category"),
                "review_status": review_status,
                "judge_decision": judge,
                "specialist_decision": state.get("specialist_decision"),
                "recoverable_amount": state.get("recoverable_amount"),
            },
        }
    )
    human = interrupt(
        {
            "booking_id": booking_id,
            "job_id": state.get("job_id"),
            "sub_category": state.get("sub_category"),
            "review_status": review_status,
            "judge_decision": judge,
            "specialist_decision": state.get("specialist_decision"),
            "recoverable_amount": state.get("recoverable_amount"),
            "review_reason": judge.get("review_reason"),
            "rationale": judge.get("rationale"),
        }
    )
    if not isinstance(human, dict):
        human = {"review_status": review_status, "decision": judge.get("decision")}
    merged = merge_human_decision(judge, human)
    return Command(
        goto="finalize",
        update={
            "human_decision": human,
            "judge_decision": merged,
            "pending_interrupt": False,
            "trace": [
                trace_step(
                    agent="Human Review",
                    action="resume_interrupt",
                    status="completed",
                    summary=clean_text(human.get("review_reason")) or "Human review applied.",
                    metadata={"review_status": merged.get("review_status")},
                )
            ],
        },
    )


def finalize_node(state: dict[str, Any]) -> dict[str, Any]:
    booking_id = booking_label(state)
    specialist = state.get("specialist_decision")
    judge = state.get("judge_decision")
    final_decision = judge or specialist
    case = claim_case_from_state(state, evidence=list(state.get("evidence") or []))
    case.source_analysis = dict(state.get("source_analysis") or {})
    case.specialist_decision = decision_from_dict(specialist)
    case.judge_decision = decision_from_dict(judge)
    case.trace = []
    for step in state.get("trace") or []:
        from backend.app.agents.models import AgentTraceStep

        case.trace.append(
            AgentTraceStep(
                agent=str(step.get("agent") or ""),
                action=str(step.get("action") or ""),
                status=step.get("status") or "completed",
                summary=str(step.get("summary") or ""),
                evidence_ids=list(step.get("evidence_ids") or []),
                metadata=dict(step.get("metadata") or {}),
            )
        )
    payload = case.to_dict()
    payload["tool_calls"] = list(state.get("tool_calls") or [])
    payload["pending_interrupt"] = bool(state.get("pending_interrupt"))
    emit_custom(
        {
            "type": "node",
            "node": "finalize",
            "booking_id": booking_id,
            "status": "completed",
            "summary": f"Finalized investigation for {booking_id}",
            "review_status": (final_decision or {}).get("review_status") if isinstance(final_decision, dict) else None,
        }
    )
    return {
        "final_decision": final_decision,
        "case_payload": payload,
        "pending_interrupt": False,
    }


async def portfolio_summary_node(
    state: dict[str, Any],
    *,
    llm_generator: AgentLlmGenerator | None = None,
    llm_concurrency: int = 1,
) -> dict[str, Any]:
    from backend.app.agents.portfolio import build_portfolio_summary_async

    emit_custom(
        {
            "type": "node",
            "node": "portfolio_summary",
            "booking_id": "",
            "status": "running",
            "summary": "Building portfolio summary",
        }
    )
    summary = await build_portfolio_summary_async(
        list(state.get("cases") or []),
        llm_generator=llm_generator,
        llm_concurrency=llm_concurrency,
    )
    emit_custom(
        {
            "type": "node",
            "node": "portfolio_summary",
            "booking_id": "",
            "status": "completed",
            "summary": summary.get("executive_summary") or "Portfolio summary completed",
        }
    )
    return {
        "agent_summary": summary,
        "trace": [
            trace_step(
                agent="Portfolio Summary Agent",
                action="aggregate_cases",
                status="completed",
                summary=summary.get("executive_summary") or "Portfolio summary completed",
            )
        ],
    }


async def vendor_penalty_analysis_node(state: dict[str, Any]) -> dict[str, Any]:
    from backend.app.agents.portfolio import build_vendor_penalty_analysis

    emit_custom(
        {
            "type": "node",
            "node": "vendor_penalty_analysis",
            "booking_id": "",
            "status": "running",
            "summary": "Building vendor penalty analysis",
        }
    )
    analysis = build_vendor_penalty_analysis(list(state.get("cases") or []))
    summary = dict(state.get("agent_summary") or {})
    summary.update(analysis)
    emit_custom(
        {
            "type": "node",
            "node": "vendor_penalty_analysis",
            "booking_id": "",
            "status": "completed",
            "summary": "Vendor penalty analysis completed",
        }
    )
    return {
        "agent_summary": summary,
        "vendor_analysis": analysis,
        "trace": [
            trace_step(
                agent="Vendor Penalty Analysis Agent",
                action="rank_vendors",
                status="completed",
                summary="Vendor penalty analysis completed",
            )
        ],
    }
