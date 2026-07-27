"""Mailer graph nodes: assign → compose → validate → send → finalize."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from backend.app.agents.mailer.state import MailerState
from backend.app.domain.mail_assignment import assign_bookings_to_recipients
from backend.app.domain.mail_templates import build_mail_draft
from backend.app.integrations.smtp import MailTransport, OutboundMail, SmtpError, send_mail_async


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trace(node: str, summary: str, **payload: Any) -> dict[str, Any]:
    return {
        "node": node,
        "summary": summary,
        "at": _utc_now(),
        "payload": payload,
    }


def assign_node(state: MailerState) -> dict[str, Any]:
    if state.get("drafts"):
        return {
            "status": "assigned",
            "trace": [_trace("assign", "Reused frozen mailer drafts", draft_count=len(state["drafts"]))],
        }

    seed_material = f"{state['job_id']}:{state['final_output_checksum']}:{','.join(state['recipients'])}"
    rng = random.Random(seed_material)
    assignments = assign_bookings_to_recipients(state["recipients"], state["booking_rows"], rng=rng)
    return {
        "drafts": [
            {
                "recipient": item["recipient"],
                "booking_id": item["booking_id"],
                "title": item["title"],
                "message": item["message"],
                "fine": item["fine"],
                "call_transcript": item["call_transcript"],
            }
            for item in assignments
        ],
        "status": "assigned",
        "trace": [_trace("assign", "Assigned bookings to recipients", assignment_count=len(assignments))],
    }


def compose_node(state: MailerState) -> dict[str, Any]:
    composed: list[dict[str, Any]] = []
    for draft in state.get("drafts") or []:
        if draft.get("subject") and draft.get("html_body") and draft.get("text_body"):
            composed.append(draft)
            continue
        composed.append(
            build_mail_draft(
                recipient=str(draft.get("recipient") or ""),
                title=str(draft.get("title") or ""),
                message=str(draft.get("message") or ""),
                fine=draft.get("fine"),
                booking_id=str(draft.get("booking_id") or ""),
                call_transcript=str(draft.get("call_transcript") or ""),
            )
        )
    return {
        "drafts": composed,
        "status": "composed",
        "trace": [_trace("compose", "Rendered deterministic mail drafts", draft_count=len(composed))],
    }


def validate_node(state: MailerState) -> dict[str, Any]:
    drafts = state.get("drafts") or []
    if not drafts:
        raise ValueError("Mailer drafts are empty")
    if len(drafts) != len(state.get("recipients") or []):
        raise ValueError("Mailer draft count does not match recipient count")

    for draft in drafts:
        recipient = str(draft.get("recipient") or "").strip()
        booking_id = str(draft.get("booking_id") or "").strip()
        subject = str(draft.get("subject") or "").strip()
        if not recipient or not booking_id or not subject:
            raise ValueError("Each mail draft requires recipient, booking_id, and subject")
        if not str(draft.get("text_body") or "").strip() or not str(draft.get("html_body") or "").strip():
            raise ValueError("Each mail draft requires text_body and html_body")
        if "<strong>" not in str(draft.get("html_body") or ""):
            raise ValueError("HTML mail body must include bold keys")

    return {
        "status": "validated",
        "trace": [_trace("validate", "Validated mail drafts", draft_count=len(drafts))],
    }


async def send_node(state: MailerState, *, transport: MailTransport | None = None) -> dict[str, Any]:
    mode = str(state.get("mode") or "preview").strip().casefold()
    if mode != "send":
        return {
            "results": [],
            "status": "preview_ready",
            "trace": [_trace("send", "Skipped SMTP send in preview mode")],
        }
    if transport is None:
        raise SmtpError("Mail transport is required for send mode")

    results: list[dict[str, Any]] = []
    for draft in state.get("drafts") or []:
        recipient = str(draft.get("recipient") or "").strip()
        booking_id = str(draft.get("booking_id") or "").strip()
        try:
            send_result = await send_mail_async(
                transport,
                OutboundMail(
                    to=recipient,
                    subject=str(draft.get("subject") or ""),
                    text_body=str(draft.get("text_body") or ""),
                    html_body=str(draft.get("html_body") or ""),
                ),
            )
            results.append(
                {
                    "recipient": recipient,
                    "booking_id": booking_id,
                    "status": "sent",
                    "message_id": send_result.message_id,
                    "smtp_response": send_result.smtp_response,
                    "error": None,
                    "sent_at": _utc_now(),
                }
            )
        except Exception as error:  # noqa: BLE001 - per-recipient isolation
            results.append(
                {
                    "recipient": recipient,
                    "booking_id": booking_id,
                    "status": "failed",
                    "message_id": None,
                    "smtp_response": "",
                    "error": str(error),
                    "sent_at": None,
                }
            )

    failed = sum(1 for item in results if item["status"] == "failed")
    status = "sent" if failed == 0 else ("partial" if failed < len(results) else "failed")
    return {
        "results": results,
        "status": status,
        "trace": [_trace("send", "Completed SMTP send attempts", result_count=len(results), failed=failed)],
    }


def finalize_node(state: MailerState) -> dict[str, Any]:
    status = str(state.get("status") or "preview_ready")
    return {
        "status": status,
        "trace": [_trace("finalize", f"Mailer finished with status={status}")],
    }
