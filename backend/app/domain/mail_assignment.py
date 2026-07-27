"""Deterministic recipient ↔ booking assignment for the vendor penalty mailer."""

from __future__ import annotations

import random
from typing import Any


def assign_bookings_to_recipients(
    recipients: list[str],
    booking_rows: list[dict[str, Any]],
    *,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """
    Assign one booking row per recipient.

    Unique bookings are preferred. When there are fewer rows than recipients,
    booking IDs are reused so every recipient still receives a mail.
    """
    cleaned_recipients = [str(item).strip() for item in recipients if str(item).strip()]
    if not cleaned_recipients:
        raise ValueError("At least one recipient is required")
    if not booking_rows:
        raise ValueError("At least one final-output booking row is required")

    chooser = rng or random.Random()
    rows = list(booking_rows)
    chooser.shuffle(rows)

    assignments: list[dict[str, Any]] = []
    if len(rows) >= len(cleaned_recipients):
        selected = rows[: len(cleaned_recipients)]
    else:
        selected = []
        for index in range(len(cleaned_recipients)):
            selected.append(rows[index % len(rows)])

    for recipient, row in zip(cleaned_recipients, selected, strict=True):
        booking_id = str(row.get("booking_id") or "").strip()
        if not booking_id:
            raise ValueError("Final-output rows must include booking_id")
        assignments.append(
            {
                "recipient": recipient,
                "booking_id": booking_id,
                "title": str(row.get("title") or "").strip(),
                "message": str(row.get("message") or "").strip(),
                "fine": row.get("fine"),
                "call_transcript": str(row.get("call_transcript") or "").strip(),
            }
        )
    return assignments
