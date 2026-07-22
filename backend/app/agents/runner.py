"""LangGraph investigation runner — replaces the hand-rolled orchestrator loop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pandas as pd
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from backend.app.agents.graphs import (
    build_case_graph,
    build_portfolio_graph,
    case_graph_mermaid,
    graph_topology_payload,
    maybe_await_callback,
)
from backend.app.agents.llm import AgentLlmGenerator
from backend.app.agents.models import AGENT_OUTPUT_COLUMNS, ClaimCase, clean_number, clean_text
from backend.app.agents.portfolio import (
    UNKNOWN_VENDOR_NAME,
    VENDOR_NAME_COLUMN,
    build_case_counts,
    build_portfolio_summary_async,
)
from backend.app.agents.state import empty_investigation_state
from backend.app.agents.tools import build_tracking_context
from backend.app.core.paths import LANGGRAPH_RUNTIME_ROOT
from backend.app.domain.complaint_message import MESSAGE_COLUMN

COMMENTS_COLUMN = "comments"

# Process-local registries for resume / SSE (job_id scoped).
_JOB_CHECKPOINTS: dict[str, Any] = {}
_JOB_PENDING_INTERRUPTS: dict[str, dict[str, dict[str, Any]]] = {}
_JOB_EVENTS: dict[str, list[dict[str, Any]]] = {}
_JOB_CASES: dict[str, dict[str, dict[str, Any]]] = {}
_JOB_GRAPHS: dict[str, Any] = {}
_JOB_META: dict[str, dict[str, Any]] = {}
_EVENT_LIMIT = 500


def case_thread_id(job_id: str, booking_id: str) -> str:
    return f"{job_id}:{booking_id or 'unknown'}"


def portfolio_thread_id(job_id: str) -> str:
    return f"{job_id}:portfolio"


def build_claim_case(row: pd.Series, *, row_index: int) -> ClaimCase:
    vendor_name = clean_text(row.get(VENDOR_NAME_COLUMN)) or UNKNOWN_VENDOR_NAME
    return ClaimCase(
        booking_id=clean_text(row.get("Booking ID")),
        sub_category=clean_text(row.get("Sub Category")) or "Uncategorized",
        remarks=clean_text(row.get("Remarks")),
        recoverable_amount=clean_number(row.get("Recoverable")),
        row_index=row_index,
        comments=clean_text(row.get(COMMENTS_COLUMN)),
        message=clean_text(row.get(MESSAGE_COLUMN)),
        vendor_name=vendor_name,
    )


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


def apply_case_result_to_output(output: pd.DataFrame, index: Any, case: ClaimCase | dict[str, Any]) -> None:
    if isinstance(case, ClaimCase):
        columns = case.to_agent_columns()
        message = clean_text(case.message or case.source_analysis.get("message"))
    else:
        columns = claim_dict_to_agent_columns(case)
        message = clean_text(case.get("message") or (case.get("source_analysis") or {}).get("message"))
    for column, value in columns.items():
        output.at[index, column] = value
    if MESSAGE_COLUMN in output.columns and message:
        output.at[index, MESSAGE_COLUMN] = message


def claim_dict_to_agent_columns(case: dict[str, Any]) -> dict[str, Any]:
    reconstructed = ClaimCase(
        booking_id=clean_text(case.get("booking_id")),
        sub_category=clean_text(case.get("sub_category")) or "Uncategorized",
        remarks=clean_text(case.get("remarks")),
        recoverable_amount=clean_number(case.get("recoverable_amount")),
        row_index=int(case.get("row_index") or 0),
        comments=clean_text(case.get("comments")),
        message=clean_text(case.get("message")),
        vendor_name=clean_text(case.get("vendor_name")) or UNKNOWN_VENDOR_NAME,
        source_analysis=dict(case.get("source_analysis") or {}),
    )
    from backend.app.agents.policy import decision_from_dict

    reconstructed.specialist_decision = decision_from_dict(case.get("specialist_decision"))
    reconstructed.judge_decision = decision_from_dict(case.get("judge_decision"))
    return reconstructed.to_agent_columns()


def get_or_create_checkpointer(job_id: str, *, use_sqlite: bool = False):
    if job_id in _JOB_CHECKPOINTS:
        return _JOB_CHECKPOINTS[job_id]
    if use_sqlite:
        LANGGRAPH_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        # Lazy import — AsyncSqliteSaver needs an open connection context in production paths.
        from langgraph.checkpoint.sqlite import SqliteSaver

        db_path = LANGGRAPH_RUNTIME_ROOT / f"{job_id}.sqlite"
        checkpointer = SqliteSaver.from_conn_string(str(db_path))
        # SqliteSaver.from_conn_string returns a context manager in some versions.
        if hasattr(checkpointer, "__enter__"):
            checkpointer = checkpointer.__enter__()
        _JOB_CHECKPOINTS[job_id] = checkpointer
        return checkpointer
    checkpointer = InMemorySaver()
    _JOB_CHECKPOINTS[job_id] = checkpointer
    return checkpointer


def append_job_event(job_id: str, event: dict[str, Any]) -> None:
    bucket = _JOB_EVENTS.setdefault(job_id, [])
    payload = {**event, "job_id": job_id}
    bucket.append(payload)
    if len(bucket) > _EVENT_LIMIT:
        del bucket[: len(bucket) - _EVENT_LIMIT]


def get_job_events(job_id: str, *, after_index: int = 0) -> list[dict[str, Any]]:
    events = _JOB_EVENTS.get(job_id, [])
    if after_index <= 0:
        return list(events)
    return list(events[after_index:])


def get_pending_interrupts(job_id: str) -> list[dict[str, Any]]:
    return list((_JOB_PENDING_INTERRUPTS.get(job_id) or {}).values())


def get_job_cases_map(job_id: str) -> dict[str, dict[str, Any]]:
    return dict(_JOB_CASES.get(job_id) or {})


def review_queue_row(case: dict[str, Any]) -> dict[str, Any]:
    decision = case.get("final_decision") or {}
    source_analysis = case.get("source_analysis") or {}
    return {
        "booking_id": case.get("booking_id", ""),
        "sub_category": case.get("sub_category", ""),
        "message": case.get("message", ""),
        "recoverable_amount": case.get("recoverable_amount", 0),
        "review_status": case.get("review_status", "failed"),
        "decision": decision.get("decision", ""),
        "confidence": decision.get("confidence", 0),
        "recommended_action": decision.get("recommended_action", ""),
        "review_reason": decision.get("review_reason", ""),
        "rationale": decision.get("rationale", ""),
        "source_used": source_analysis.get("source_label", ""),
        "source_categories": join_categories(source_analysis.get("source_categories", [])),
        "row_categories": join_categories(source_analysis.get("row_categories", [])),
        "source_alignment_status": source_analysis.get("status", ""),
        "source_alignment_reason": source_analysis.get("reason", ""),
        "evidence_ids": ", ".join(decision.get("evidence_ids", [])),
    }


def build_agent_progress(
    cases: list[dict[str, Any]],
    *,
    agent_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    total = len(cases)
    intake_missing_booking_ids = count_cases(cases, lambda case: not clean_text(case.get("booking_id")))
    evidence_error_cases = count_cases(cases, lambda case: any_evidence_status(case, "error"))
    evidence_missing_cases = count_cases(cases, lambda case: case.get("review_status") == "missing_evidence")
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
    pending = count_cases(cases, lambda case: bool(case.get("pending_interrupt")))

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
                f"LangGraph tools found {evidence_error_cases} error cases and {evidence_missing_cases} missing-source cases"
                if evidence_error_cases
                else f"LangGraph tools found {evidence_missing_cases} missing-source cases"
                if evidence_missing_cases
                else f"Evidence tools completed for {total} cases"
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
            "Human Review",
            total=total,
            completed=total - pending,
            status="warning" if pending else "completed",
            message=(
                f"{pending} cases awaiting human review via LangGraph interrupt"
                if pending
                else f"Human review cleared for {total} cases"
            ),
        ),
        progress_item(
            "Portfolio Summary Agent",
            total=total,
            completed=0 if pending else total,
            status="warning" if pending or portfolio_error else "completed",
            message=(
                "Portfolio summary waiting for human review to finish"
                if pending
                else f"Portfolio summary used fallback: {portfolio_error}"
                if portfolio_error
                else f"Portfolio summary completed for {total} cases"
            ),
        ),
        progress_item(
            "Vendor Penalty Analysis Agent",
            total=total,
            completed=0 if pending else total,
            status="warning" if pending else "completed",
            message=(
                "Vendor analysis waiting for human review to finish"
                if pending
                else f"Vendor penalty analysis completed for {total} cases"
            ),
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


def join_categories(value: Any) -> str:
    if isinstance(value, list):
        return " + ".join(clean_text(item) for item in value if clean_text(item))
    return clean_text(value)


def case_payload_from_graph_state(values: dict[str, Any], *, pending_interrupt: bool = False) -> dict[str, Any]:
    if values.get("case_payload"):
        payload = dict(values["case_payload"])
        payload["pending_interrupt"] = pending_interrupt
        return payload

    case = ClaimCase(
        booking_id=clean_text(values.get("booking_id")),
        sub_category=clean_text(values.get("sub_category")) or "Uncategorized",
        remarks=clean_text(values.get("remarks")),
        recoverable_amount=clean_number(values.get("recoverable_amount")),
        row_index=int(values.get("row_index") or 0),
        comments=clean_text(values.get("comments")),
        message=clean_text(values.get("message")),
        vendor_name=clean_text(values.get("vendor_name")) or UNKNOWN_VENDOR_NAME,
        source_analysis=dict(values.get("source_analysis") or {}),
    )
    from backend.app.agents.models import AgentTraceStep, EvidenceItem
    from backend.app.agents.policy import decision_from_dict

    for item in values.get("evidence") or []:
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
    for step in values.get("trace") or []:
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
    case.specialist_decision = decision_from_dict(values.get("specialist_decision"))
    case.judge_decision = decision_from_dict(values.get("judge_decision"))
    payload = case.to_dict()
    payload["tool_calls"] = list(values.get("tool_calls") or [])
    payload["pending_interrupt"] = pending_interrupt
    return payload


async def _run_one_case(
    *,
    graph,
    job_id: str,
    index: Any,
    position: int,
    row: pd.Series,
    tracking_bookings: dict[str, Any],
    on_event=None,
) -> tuple[int, Any, dict[str, Any], bool]:
    case = build_claim_case(row, row_index=position)
    booking_id = case.booking_id or f"row-{position}"
    thread_id = case_thread_id(job_id, booking_id)
    initial = empty_investigation_state(
        job_id=job_id,
        booking_id=booking_id,
        row_index=position,
        sub_category=case.sub_category,
        remarks=case.remarks,
        comments=case.comments,
        message=case.message,
        vendor_name=case.vendor_name,
        recoverable_amount=case.recoverable_amount,
        tracking_context=build_tracking_context(tracking_bookings, booking_id),
    )
    config = {"configurable": {"thread_id": thread_id}}
    interrupted = False
    final_values: dict[str, Any] = dict(initial)

    async for mode, chunk in graph.astream(
        initial,
        config=config,
        stream_mode=["updates", "custom"],
    ):
        if mode == "custom" and isinstance(chunk, dict):
            event = {**chunk, "thread_id": thread_id}
            append_job_event(job_id, event)
            await maybe_await_callback(on_event, event)
        elif mode == "updates" and isinstance(chunk, dict):
            for node_name, update in chunk.items():
                if node_name == "__interrupt__":
                    interrupted = True
                    interrupt_payload = update
                    if isinstance(interrupt_payload, tuple):
                        interrupt_payload = interrupt_payload[0] if interrupt_payload else {}
                    if hasattr(interrupt_payload, "value"):
                        interrupt_payload = interrupt_payload.value
                    if not isinstance(interrupt_payload, dict):
                        interrupt_payload = {"raw": interrupt_payload}
                    pending = {
                        "booking_id": booking_id,
                        "thread_id": thread_id,
                        "df_index": index if not hasattr(index, "item") else index,
                        "payload": interrupt_payload,
                    }
                    _JOB_PENDING_INTERRUPTS.setdefault(job_id, {})[booking_id] = pending
                    event = {
                        "type": "interrupt",
                        "node": "human_review",
                        "booking_id": booking_id,
                        "status": "awaiting_review",
                        "summary": interrupt_payload.get("review_reason") or "Human review required",
                        "payload": interrupt_payload,
                        "thread_id": thread_id,
                    }
                    append_job_event(job_id, event)
                    await maybe_await_callback(on_event, event)
                elif isinstance(update, dict):
                    final_values.update({k: v for k, v in update.items() if k != "messages"})
                    event = {
                        "type": "update",
                        "node": node_name,
                        "booking_id": booking_id,
                        "status": "updated",
                        "summary": f"{node_name} updated state",
                        "thread_id": thread_id,
                    }
                    append_job_event(job_id, event)
                    await maybe_await_callback(on_event, event)

    # Prefer checkpoint values after stream.
    try:
        snapshot = await graph.aget_state(config)
        if snapshot and snapshot.values:
            final_values = dict(snapshot.values)
            if snapshot.tasks:
                for task in snapshot.tasks:
                    if getattr(task, "interrupts", None):
                        interrupted = True
                        for item in task.interrupts:
                            value = getattr(item, "value", item)
                            if not isinstance(value, dict):
                                value = {"raw": value}
                            _JOB_PENDING_INTERRUPTS.setdefault(job_id, {})[booking_id] = {
                                "booking_id": booking_id,
                                "thread_id": thread_id,
                                "df_index": index,
                                "payload": value,
                            }
    except Exception:
        pass

    payload = case_payload_from_graph_state(final_values, pending_interrupt=interrupted)
    _JOB_CASES.setdefault(job_id, {})[booking_id] = payload
    return position, index, payload, interrupted


async def investigate_category_frame_async(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: AgentLlmGenerator | None,
    llm_concurrency: int,
    job_id: str | None = None,
    enable_hitl: bool = False,
    use_sqlite: bool = False,
    on_event=None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """
    Run LangGraph investigation for each row.

    Pending HITL interrupts are stored in the job registry (see get_pending_interrupts).
    """
    resolved_job_id = job_id or f"local-{id(df)}"
    output = ensure_agent_columns(df)
    semaphore = asyncio.Semaphore(max(1, llm_concurrency))
    checkpointer = get_or_create_checkpointer(resolved_job_id, use_sqlite=use_sqlite)
    graph = build_case_graph(
        llm_generator=llm_generator,
        semaphore=semaphore,
        checkpointer=checkpointer,
        enable_hitl=enable_hitl,
    )
    _JOB_GRAPHS[resolved_job_id] = graph
    _JOB_META[resolved_job_id] = {
        "llm_generator": llm_generator,
        "llm_concurrency": llm_concurrency,
        "enable_hitl": enable_hitl,
        "topology": graph_topology_payload(),
        "case_mermaid": case_graph_mermaid(graph),
    }
    _JOB_EVENTS.setdefault(resolved_job_id, [])
    _JOB_PENDING_INTERRUPTS.setdefault(resolved_job_id, {})
    _JOB_CASES.setdefault(resolved_job_id, {})

    indexes = output.index.tolist()
    cases: list[dict[str, Any] | None] = [None] * len(indexes)
    gate = asyncio.Semaphore(max(1, llm_concurrency))

    async def investigate_one(position: int, index: Any) -> tuple[int, Any, dict[str, Any], bool]:
        async with gate:
            return await _run_one_case(
                graph=graph,
                job_id=resolved_job_id,
                index=index,
                position=position,
                row=output.loc[index],
                tracking_bookings=tracking_bookings,
                on_event=on_event,
            )

    tasks = [asyncio.create_task(investigate_one(position, index)) for position, index in enumerate(indexes)]
    for task in asyncio.as_completed(tasks):
        position, index, payload, _interrupted = await task
        cases[position] = payload
        reconstructed = ClaimCase(
            booking_id=clean_text(payload.get("booking_id")),
            sub_category=clean_text(payload.get("sub_category")) or "Uncategorized",
            remarks=clean_text(payload.get("remarks")),
            recoverable_amount=clean_number(payload.get("recoverable_amount")),
            row_index=position,
            comments=clean_text(payload.get("comments")),
            message=clean_text(payload.get("message")),
            vendor_name=clean_text(payload.get("vendor_name")) or UNKNOWN_VENDOR_NAME,
            source_analysis=dict(payload.get("source_analysis") or {}),
        )
        from backend.app.agents.policy import decision_from_dict

        reconstructed.specialist_decision = decision_from_dict(payload.get("specialist_decision"))
        reconstructed.judge_decision = decision_from_dict(payload.get("judge_decision"))
        apply_case_result_to_output(output, index, reconstructed)

    ordered = [case for case in cases if case is not None]
    return output, ordered


def investigate_category_frame(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
    llm_generator: AgentLlmGenerator | None = None,
    llm_concurrency: int = 1,
    job_id: str | None = None,
    enable_hitl: bool = False,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    return asyncio.run(
        investigate_category_frame_async(
            df,
            tracking_bookings=tracking_bookings,
            llm_generator=llm_generator,
            llm_concurrency=llm_concurrency,
            job_id=job_id,
            enable_hitl=enable_hitl,
        )
    )


async def resume_case(
    *,
    job_id: str,
    booking_id: str,
    human_decision: dict[str, Any],
    on_event=None,
) -> dict[str, Any]:
    graph = _JOB_GRAPHS.get(job_id)
    if graph is None:
        raise KeyError(f"No compiled graph for job {job_id}")
    pending = (_JOB_PENDING_INTERRUPTS.get(job_id) or {}).get(booking_id)
    if pending is None:
        raise KeyError(f"No pending interrupt for booking {booking_id}")

    thread_id = pending.get("thread_id") or case_thread_id(job_id, booking_id)
    config = {"configurable": {"thread_id": thread_id}}
    final_values: dict[str, Any] = {}

    async for mode, chunk in graph.astream(
        Command(resume=human_decision),
        config=config,
        stream_mode=["updates", "custom"],
    ):
        if mode == "custom" and isinstance(chunk, dict):
            event = {**chunk, "thread_id": thread_id}
            append_job_event(job_id, event)
            await maybe_await_callback(on_event, event)
        elif mode == "updates" and isinstance(chunk, dict):
            for node_name, update in chunk.items():
                if isinstance(update, dict):
                    final_values.update({k: v for k, v in update.items() if k != "messages"})
                    event = {
                        "type": "update",
                        "node": node_name,
                        "booking_id": booking_id,
                        "status": "updated",
                        "summary": f"{node_name} updated state after resume",
                        "thread_id": thread_id,
                    }
                    append_job_event(job_id, event)
                    await maybe_await_callback(on_event, event)

    try:
        snapshot = await graph.aget_state(config)
        if snapshot and snapshot.values:
            final_values = dict(snapshot.values)
    except Exception:
        pass

    payload = case_payload_from_graph_state(final_values, pending_interrupt=False)
    _JOB_CASES.setdefault(job_id, {})[booking_id] = payload
    (_JOB_PENDING_INTERRUPTS.get(job_id) or {}).pop(booking_id, None)
    return payload


async def run_portfolio_for_job(
    *,
    job_id: str,
    cases: list[dict[str, Any]],
    llm_generator: AgentLlmGenerator | None,
    llm_concurrency: int,
    on_event=None,
) -> dict[str, Any]:
    checkpointer = get_or_create_checkpointer(job_id, use_sqlite=False)
    graph = build_portfolio_graph(
        llm_generator=llm_generator,
        llm_concurrency=llm_concurrency,
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": portfolio_thread_id(job_id)}}
    result = await graph.ainvoke(
        {"job_id": job_id, "cases": cases, "messages": [], "trace": []},
        config=config,
    )
    summary = dict(result.get("agent_summary") or {})
    if not summary:
        summary = await build_portfolio_summary_async(
            cases,
            llm_generator=llm_generator,
            llm_concurrency=llm_concurrency,
        )
    event = {
        "type": "node",
        "node": "portfolio_summary",
        "booking_id": "",
        "status": "completed",
        "summary": summary.get("executive_summary") or "Portfolio completed",
        "thread_id": portfolio_thread_id(job_id),
    }
    append_job_event(job_id, event)
    await maybe_await_callback(on_event, event)
    return summary


def get_graph_topology(job_id: str | None = None) -> dict[str, Any]:
    if job_id and job_id in _JOB_META:
        return _JOB_META[job_id].get("topology") or graph_topology_payload()
    return graph_topology_payload()


# Re-export portfolio helpers used by pipeline
__all__ = [
    "apply_case_result_to_output",
    "build_agent_progress",
    "build_case_counts",
    "build_claim_case",
    "build_portfolio_summary_async",
    "case_graph_mermaid",
    "ensure_agent_columns",
    "get_graph_topology",
    "get_job_events",
    "get_pending_interrupts",
    "graph_topology_payload",
    "investigate_category_frame",
    "investigate_category_frame_async",
    "resume_case",
    "review_queue_row",
    "run_portfolio_for_job",
]
