from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


IST_OFFSET = timedelta(hours=5, minutes=30)
MISSING_TIME_VALUES = {"", "0", "none", "nan", "nat", "null"}


def raw_tracking_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_tracking_time(value: Any) -> datetime | None:
    text = raw_tracking_value(value)
    if not text or text.casefold() in MISSING_TIME_VALUES:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None


def normalize_start_time_utc(value: Any) -> datetime | None:
    return parse_tracking_time(value)


def format_dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_display_time(value: Any) -> str:
    parsed = parse_tracking_time(value)
    return format_dt(parsed) if parsed else raw_tracking_value(value)


_DISPLAY_FMT = "%d %b %Y %I:%M %p"
_DISPLAY_FMT_SECS = "%d %b %Y %I:%M:%S %p"


def _human_display(value: datetime) -> str:
    fmt = _DISPLAY_FMT_SECS if value.second else _DISPLAY_FMT
    return value.strftime(fmt).replace(" 0", " ", 1)


def format_ist_from_utc(value: Any) -> str:
    parsed = parse_tracking_time(value)
    if parsed is None:
        return ""
    return _human_display(parsed + IST_OFFSET)


def format_existing_ist_time(value: Any) -> str:
    parsed = parse_tracking_time(value)
    if parsed is None:
        return ""
    return _human_display(parsed)


def duration_minutes(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return int((end - start).total_seconds() // 60)


def format_duration(minutes: int | None) -> str:
    if minutes is None:
        return "unavailable"
    absolute_value = abs(minutes)
    sign = "-" if minutes < 0 else ""
    hours, remaining = divmod(absolute_value, 60)
    if hours:
        return f"{sign}{hours} hr {remaining} min"
    return f"{sign}{remaining} min"


def read_tracking_data(path: Path) -> dict[str, Any]:
    """Load bookings dict from a reference tracking JSON file (tests / demos only)."""
    return json.loads(path.read_text(encoding="utf-8")).get("bookings", {})


def booking_comments(bookings: dict[str, Any], booking_id: str) -> str:
    booking = bookings.get(booking_id, {})
    if not isinstance(booking, dict):
        return ""

    value = booking.get("comments")
    if value is None or str(value).strip() == "":
        value = booking.get("comment")
    return raw_tracking_value(value)


def first_tracking_row(bookings: dict[str, Any], booking_id: str) -> dict[str, Any]:
    booking = bookings.get(booking_id, {})
    if not isinstance(booking, dict):
        return {}
    rows = booking.get("tracking_reports_raw", [])
    if not rows:
        return {}
    return rows[0]
