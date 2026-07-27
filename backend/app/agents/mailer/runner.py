"""Runner for the vendor penalty mailer LangGraph."""

from __future__ import annotations

from typing import Any

from backend.app.agents.mailer.graphs import build_mailer_graph
from backend.app.agents.mailer.state import empty_mailer_state
from backend.app.integrations.smtp import MailTransport


def mailer_thread_id(job_id: str) -> str:
    return f"{job_id}:mailer"


async def run_mailer_graph(
    *,
    job_id: str,
    mode: str,
    preview_token: str,
    final_output_checksum: str,
    recipients: list[str],
    booking_rows: list[dict[str, Any]],
    drafts: list[dict[str, Any]] | None = None,
    transport: MailTransport | None = None,
) -> dict[str, Any]:
    graph = build_mailer_graph(transport=transport)
    initial = empty_mailer_state(
        job_id=job_id,
        mode=mode,
        preview_token=preview_token,
        final_output_checksum=final_output_checksum,
        recipients=recipients,
        booking_rows=booking_rows,
        drafts=drafts,
    )
    result = await graph.ainvoke(
        initial,
        config={"configurable": {"thread_id": mailer_thread_id(job_id)}},
    )
    return {
        "status": result.get("status") or "idle",
        "preview_token": result.get("preview_token") or preview_token,
        "final_output_checksum": result.get("final_output_checksum") or final_output_checksum,
        "recipients": list(result.get("recipients") or recipients),
        "drafts": list(result.get("drafts") or []),
        "results": list(result.get("results") or []),
        "error": result.get("error"),
        "trace": list(result.get("trace") or []),
    }
