from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pandas as pd

from backend.app.core.tracking_utils import (
    booking_comments,
    first_tracking_row,
    format_existing_ist_time,
    format_ist_from_utc,
    raw_tracking_value,
)
from backend.app.domain.cab_delay_enrichment import COMMENTS_COLUMN
from backend.app.domain.tracking_common import TTRIP_TYPE_COLUMN, tracking_cell_value


BOOKING_STATUS_COLUMN = "booking status"
TRACKING_STATUS_COLUMN = "tracking status"
FULFILLMENT_PREFERRED_START_TIME_COLUMN = "preferred start time of customer (IST)"
FULFILLMENT_DRIVER_STARTED_COLUMN = "driver_started"
FULFILLMENT_DRIVER_ARRIVED_COLUMN = "driver_arrived"
FINE_BEFORE_SOP_COLUMN = "fine_before_sop"
FINE_AFTER_SOP_COLUMN = "fine_after_sop"
SOP_CALCULATION_FAILED_COLUMN = "sop_calculation_failed"
AIRPORT_TRIP_TYPES = frozenset({"airport", "local"})
FULFILLMENT_NOT_DONE_ENRICHMENT_COLUMNS = [
    BOOKING_STATUS_COLUMN,
    TRACKING_STATUS_COLUMN,
    COMMENTS_COLUMN,
    FULFILLMENT_PREFERRED_START_TIME_COLUMN,
    FULFILLMENT_DRIVER_STARTED_COLUMN,
    FULFILLMENT_DRIVER_ARRIVED_COLUMN,
    FINE_BEFORE_SOP_COLUMN,
    FINE_AFTER_SOP_COLUMN,
]


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _parse_positive_amount(value: object) -> float | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        amount = float(text)
    except (TypeError, ValueError):
        return None
    if amount != amount or amount <= 0:
        return None
    return amount


def is_airport_trip_type(ttrip_type: object) -> bool:
    return _clean_text(ttrip_type).casefold() in AIRPORT_TRIP_TYPES


def _round_half_up_to_int(value: Decimal) -> float:
    """Round to nearest integer with half-up (>= 0.5 rounds away from zero)."""
    return float(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_vendor_no_show_sop_fine(*, amount: object, ttrip_type: object) -> float | None:
    """Return SOP fine for Vendor No Show, or None when inputs are missing/invalid."""
    trip = _clean_text(ttrip_type)
    if not trip:
        return None
    booking_amount = _parse_positive_amount(amount)
    if booking_amount is None:
        return None
    amount_dec = Decimal(str(booking_amount))
    if is_airport_trip_type(trip):
        fine = min(amount_dec * Decimal("0.5"), Decimal("500"))
    else:
        fine = min(amount_dec * Decimal("0.25"), Decimal("2000"))
    return _round_half_up_to_int(fine)


def is_vendor_no_show_category(sub_category: object) -> bool:
    key = _clean_text(sub_category).casefold()
    return "fulfillment not done" in key or "vendor no show" in key


def build_fulfillment_not_done_enrichment(bookings: dict[str, Any], booking_id: str) -> dict[str, str]:
    tracking_row = first_tracking_row(bookings, booking_id)
    return {
        BOOKING_STATUS_COLUMN: raw_tracking_value(tracking_row.get("booking_status")),
        TRACKING_STATUS_COLUMN: raw_tracking_value(tracking_row.get("tracking_status")),
        COMMENTS_COLUMN: booking_comments(bookings, booking_id) or raw_tracking_value(
            tracking_row.get("comments")
        ),
        FULFILLMENT_PREFERRED_START_TIME_COLUMN: format_ist_from_utc(tracking_row.get("start_time")),
        FULFILLMENT_DRIVER_STARTED_COLUMN: format_existing_ist_time(tracking_row.get("driver_started")),
        FULFILLMENT_DRIVER_ARRIVED_COLUMN: format_existing_ist_time(tracking_row.get("driver_arrived")),
    }


def enrich_fulfillment_not_done_rows(
    df: pd.DataFrame,
    *,
    tracking_bookings: dict[str, Any],
) -> pd.DataFrame:
    output = df.copy()
    for column in [*FULFILLMENT_NOT_DONE_ENRICHMENT_COLUMNS, SOP_CALCULATION_FAILED_COLUMN]:
        if column not in output.columns:
            output[column] = pd.Series([""] * len(output), index=output.index, dtype=object)
        else:
            output[column] = output[column].astype(object)
    if "Recoverable" in output.columns:
        output["Recoverable"] = output["Recoverable"].astype(object)

    for index in output.index.tolist():
        booking_id = str(output.at[index, "Booking ID"]).strip()
        if not booking_id:
            continue

        for column, value in build_fulfillment_not_done_enrichment(tracking_bookings, booking_id).items():
            output.at[index, column] = value

        original_recoverable = 0.0
        if "Recoverable" in output.columns:
            try:
                original_recoverable = round(float(output.at[index, "Recoverable"] or 0), 2)
            except (TypeError, ValueError):
                original_recoverable = 0.0
        output.at[index, FINE_BEFORE_SOP_COLUMN] = original_recoverable

        tracking_row = first_tracking_row(tracking_bookings, booking_id)
        amount = (
            output.at[index, "amount"]
            if "amount" in output.columns and _clean_text(output.at[index, "amount"])
            else tracking_row.get("amount")
        )
        ttrip_type = (
            output.at[index, TTRIP_TYPE_COLUMN]
            if TTRIP_TYPE_COLUMN in output.columns and _clean_text(output.at[index, TTRIP_TYPE_COLUMN])
            else tracking_cell_value(tracking_row.get(TTRIP_TYPE_COLUMN))
        )
        sop_fine = compute_vendor_no_show_sop_fine(amount=amount, ttrip_type=ttrip_type)
        if sop_fine is None:
            output.at[index, FINE_AFTER_SOP_COLUMN] = ""
            output.at[index, SOP_CALCULATION_FAILED_COLUMN] = True
            continue

        output.at[index, FINE_AFTER_SOP_COLUMN] = sop_fine
        output.at[index, SOP_CALCULATION_FAILED_COLUMN] = False
        if "Recoverable" in output.columns:
            output.at[index, "Recoverable"] = sop_fine

    return output
