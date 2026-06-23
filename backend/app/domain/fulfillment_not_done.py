from __future__ import annotations

from typing import Any

import pandas as pd

from backend.app.domain.cab_delay_enrichment import (
    COMMENTS_COLUMN,
    booking_comments,
    first_tracking_row,
    format_existing_ist_time,
    format_ist_from_utc,
    raw_tracking_value,
)


BOOKING_STATUS_COLUMN = "booking status"
TRACKING_STATUS_COLUMN = "tracking status"
FULFILLMENT_PREFERRED_START_TIME_COLUMN = "preferred start time of customer (IST)"
FULFILLMENT_DRIVER_STARTED_COLUMN = "driver_started"
FULFILLMENT_DRIVER_ARRIVED_COLUMN = "driver_arrived"
FULFILLMENT_NOT_DONE_ENRICHMENT_COLUMNS = [
    BOOKING_STATUS_COLUMN,
    TRACKING_STATUS_COLUMN,
    COMMENTS_COLUMN,
    FULFILLMENT_PREFERRED_START_TIME_COLUMN,
    FULFILLMENT_DRIVER_STARTED_COLUMN,
    FULFILLMENT_DRIVER_ARRIVED_COLUMN,
]


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
    for column in FULFILLMENT_NOT_DONE_ENRICHMENT_COLUMNS:
        if column not in output.columns:
            output[column] = pd.Series([""] * len(output), index=output.index, dtype=object)
        else:
            output[column] = output[column].astype(object)

    for index in output.index.tolist():
        booking_id = str(output.at[index, "Booking ID"]).strip()
        if not booking_id:
            continue

        for column, value in build_fulfillment_not_done_enrichment(tracking_bookings, booking_id).items():
            output.at[index, column] = value

    return output
