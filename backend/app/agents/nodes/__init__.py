"""Shared helpers for LangGraph investigation nodes."""

from __future__ import annotations

from typing import Any

from backend.app.agents.models import clean_text


def emit_custom(event: dict[str, Any]) -> None:
    """Emit a custom stream event when running under LangGraph streaming."""
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        writer(event)
    except Exception:
        pass


def trace_step(
    *,
    agent: str,
    action: str,
    status: str,
    summary: str,
    evidence_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "agent": agent,
        "action": action,
        "status": status,
        "summary": summary,
        "evidence_ids": evidence_ids or [],
        "metadata": metadata or {},
    }


def tool_call_record(*, name: str, status: str, summary: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "summary": summary,
        "result": result or {},
    }


def booking_label(state: dict[str, Any]) -> str:
    return clean_text(state.get("booking_id")) or "unknown"
