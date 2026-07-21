"""LangGraph state schemas for per-case investigation and job portfolio graphs."""

from __future__ import annotations

import operator
from typing import Annotated, Any, NotRequired, TypedDict

from langgraph.graph.message import add_messages


def merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(left or {})
    merged.update(right or {})
    return merged


class InvestigationState(TypedDict):
    """Per-booking investigation state (thread_id = job_id:booking_id)."""

    messages: Annotated[list, add_messages]
    job_id: str
    booking_id: str
    row_index: int
    sub_category: str
    remarks: str
    comments: str
    message: str
    vendor_name: str
    recoverable_amount: float
    tracking_context: dict[str, Any]
    source_analysis: dict[str, Any]
    evidence: Annotated[list[dict[str, Any]], operator.add]
    tool_calls: Annotated[list[dict[str, Any]], operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]
    specialist_decision: NotRequired[dict[str, Any] | None]
    judge_decision: NotRequired[dict[str, Any] | None]
    human_decision: NotRequired[dict[str, Any] | None]
    final_decision: NotRequired[dict[str, Any] | None]
    case_payload: NotRequired[dict[str, Any] | None]
    pending_interrupt: NotRequired[bool]
    error: NotRequired[str | None]


class PortfolioState(TypedDict):
    """Job-level portfolio aggregation (thread_id = job_id:portfolio)."""

    job_id: str
    cases: list[dict[str, Any]]
    agent_summary: NotRequired[dict[str, Any]]
    vendor_analysis: NotRequired[dict[str, Any]]
    messages: Annotated[list, add_messages]
    trace: Annotated[list[dict[str, Any]], operator.add]


def empty_investigation_state(
    *,
    job_id: str,
    booking_id: str,
    row_index: int,
    sub_category: str,
    remarks: str,
    comments: str,
    message: str,
    vendor_name: str,
    recoverable_amount: float,
    tracking_context: dict[str, Any] | None = None,
) -> InvestigationState:
    return {
        "messages": [],
        "job_id": job_id,
        "booking_id": booking_id,
        "row_index": row_index,
        "sub_category": sub_category,
        "remarks": remarks,
        "comments": comments,
        "message": message,
        "vendor_name": vendor_name,
        "recoverable_amount": recoverable_amount,
        "tracking_context": tracking_context or {},
        "source_analysis": {},
        "evidence": [],
        "tool_calls": [],
        "trace": [],
        "specialist_decision": None,
        "judge_decision": None,
        "human_decision": None,
        "final_decision": None,
        "case_payload": None,
        "pending_interrupt": False,
        "error": None,
    }
