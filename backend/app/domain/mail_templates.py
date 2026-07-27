"""Deterministic vendor penalty email templates (text + HTML)."""

from __future__ import annotations

import html
from typing import Any


def format_fine(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")
    text = str(value).strip()
    return text


def build_mail_subject(booking_id: str) -> str:
    cleaned = str(booking_id or "").strip()
    if not cleaned:
        raise ValueError("booking_id is required for mail subject")
    return f"Penalty complaint details - {cleaned}"


def build_mail_fields(
    *,
    title: str,
    message: str,
    fine: Any,
    booking_id: str,
    call_transcript: str = "",
) -> list[tuple[str, str]]:
    cleaned_booking = str(booking_id or "").strip()
    if not cleaned_booking:
        raise ValueError("booking_id is required for mail body")

    fields: list[tuple[str, str]] = [
        ("title", str(title or "").strip()),
        ("message", str(message or "").strip()),
        ("Fine", format_fine(fine)),
    ]
    transcript = str(call_transcript or "").strip()
    if transcript:
        fields.append(("call transcript", transcript))
    fields.append(("complaint against booking", cleaned_booking))
    return fields


def build_text_body(
    *,
    title: str,
    message: str,
    fine: Any,
    booking_id: str,
    call_transcript: str = "",
) -> str:
    fields = build_mail_fields(
        title=title,
        message=message,
        fine=fine,
        booking_id=booking_id,
        call_transcript=call_transcript,
    )
    lines = [
        "hi ,",
        "here is the details of the complaint below",
        "",
    ]
    for key, value in fields:
        lines.append(f"{key} : {value}")
    lines.extend(["", "Thanks ,", "cabs team"])
    return "\n".join(lines)


def build_html_body(
    *,
    title: str,
    message: str,
    fine: Any,
    booking_id: str,
    call_transcript: str = "",
) -> str:
    fields = build_mail_fields(
        title=title,
        message=message,
        fine=fine,
        booking_id=booking_id,
        call_transcript=call_transcript,
    )
    rows = []
    for key, value in fields:
        rows.append(
            "<tr>"
            f"<td style=\"padding:6px 12px;border:1px solid #d0d7de;vertical-align:top;\">"
            f"<strong>{html.escape(key)}</strong></td>"
            f"<td style=\"padding:6px 12px;border:1px solid #d0d7de;vertical-align:top;\">"
            f"{html.escape(value)}</td>"
            "</tr>"
        )
    table = (
        '<table style="border-collapse:collapse;width:100%;max-width:640px;'
        'font-family:Arial,sans-serif;font-size:14px;line-height:1.4;">'
        f"{''.join(rows)}</table>"
    )
    return (
        '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5;color:#111;">'
        "<p>hi ,</p>"
        "<p>here is the details of the complaint below</p>"
        f"{table}"
        "<p>Thanks ,<br/>cabs team</p>"
        "</div>"
    )


def build_mail_draft(
    *,
    recipient: str,
    title: str,
    message: str,
    fine: Any,
    booking_id: str,
    call_transcript: str = "",
) -> dict[str, Any]:
    subject = build_mail_subject(booking_id)
    text_body = build_text_body(
        title=title,
        message=message,
        fine=fine,
        booking_id=booking_id,
        call_transcript=call_transcript,
    )
    html_body = build_html_body(
        title=title,
        message=message,
        fine=fine,
        booking_id=booking_id,
        call_transcript=call_transcript,
    )
    fields = [
        {"key": key, "value": value}
        for key, value in build_mail_fields(
            title=title,
            message=message,
            fine=fine,
            booking_id=booking_id,
            call_transcript=call_transcript,
        )
    ]
    return {
        "recipient": recipient,
        "booking_id": booking_id,
        "subject": subject,
        "text_body": text_body,
        "html_body": html_body,
        "fields": fields,
        "title": str(title or "").strip(),
        "message": str(message or "").strip(),
        "fine": format_fine(fine),
        "call_transcript": str(call_transcript or "").strip(),
    }
