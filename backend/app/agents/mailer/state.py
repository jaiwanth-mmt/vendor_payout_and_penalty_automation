"""LangGraph state for the vendor penalty mailer."""

from __future__ import annotations

import operator
from typing import Annotated, Any, NotRequired, TypedDict


class MailerState(TypedDict):
    job_id: str
    mode: str
    preview_token: str
    final_output_checksum: str
    recipients: list[str]
    booking_rows: list[dict[str, Any]]
    drafts: list[dict[str, Any]]
    results: list[dict[str, Any]]
    status: str
    error: NotRequired[str | None]
    trace: Annotated[list[dict[str, Any]], operator.add]


def empty_mailer_state(
    *,
    job_id: str,
    mode: str,
    preview_token: str,
    final_output_checksum: str,
    recipients: list[str],
    booking_rows: list[dict[str, Any]],
    drafts: list[dict[str, Any]] | None = None,
) -> MailerState:
    return {
        "job_id": job_id,
        "mode": mode,
        "preview_token": preview_token,
        "final_output_checksum": final_output_checksum,
        "recipients": list(recipients),
        "booking_rows": list(booking_rows),
        "drafts": list(drafts or []),
        "results": [],
        "status": "idle",
        "error": None,
        "trace": [],
    }
