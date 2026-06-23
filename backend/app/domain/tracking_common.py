from __future__ import annotations

from typing import Any

import pandas as pd

from backend.app.domain.cab_delay_enrichment import (
    COMMENTS_COLUMN,
    booking_comments,
    first_tracking_row,
)

COMPLAINT_AGAINST_COLUMN = "complaint_against"
COMPLAINT_AGAINST_ID_COLUMN = "complaint_against_id"
TITLE_COLUMN = "title"
COMPLAINT_AGAINST_VALUE = "dispatch_id"
TITLE_VALUE = "Service Issue"
COMPLAINT_METADATA_COLUMNS = [
    COMPLAINT_AGAINST_COLUMN,
    COMPLAINT_AGAINST_ID_COLUMN,
    TITLE_COLUMN,
]

TRACKING_AMOUNT_COLUMNS = [
    "amount",
    "base_amount",
    "amount_paid",
    "cash_collected",
    "per_km_rate",
    "total_distance",
    "extra_travelled",
    "extra_travelled_fare",
    "route_toll_charges",
    "toll_charges",
    "toll_paid",
    "parking_charges",
    "state_tax",
    "airport_entry_fee",
    "night_charges",
    "waiting_charges",
    "driver_charge_per_day",
    "total_driver_charge",
]
COMMON_TRACKING_COLUMNS = [*COMPLAINT_METADATA_COLUMNS, *TRACKING_AMOUNT_COLUMNS, COMMENTS_COLUMN]


def tracking_cell_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value


def build_common_tracking_enrichment(bookings: dict[str, Any], booking_id: str) -> dict[str, Any]:
    tracking_row = first_tracking_row(bookings, booking_id)
    enrichment = {
        COMPLAINT_AGAINST_COLUMN: COMPLAINT_AGAINST_VALUE,
        COMPLAINT_AGAINST_ID_COLUMN: tracking_cell_value(tracking_row.get(COMPLAINT_AGAINST_VALUE)),
        TITLE_COLUMN: TITLE_VALUE,
    }
    enrichment.update({
        column: tracking_cell_value(tracking_row.get(column))
        for column in TRACKING_AMOUNT_COLUMNS
    })
    enrichment[COMMENTS_COLUMN] = booking_comments(bookings, booking_id) or tracking_cell_value(
        tracking_row.get("comments")
    )
    return enrichment


def enrich_common_tracking_fields(df: pd.DataFrame, *, tracking_bookings: dict[str, Any]) -> pd.DataFrame:
    output = df.copy()
    for column in COMMON_TRACKING_COLUMNS:
        if column not in output.columns:
            output[column] = pd.Series([""] * len(output), index=output.index, dtype=object)
        else:
            output[column] = output[column].astype(object)

    output[COMPLAINT_AGAINST_COLUMN] = COMPLAINT_AGAINST_VALUE
    output[TITLE_COLUMN] = TITLE_VALUE

    for index in output.index.tolist():
        booking_id = str(output.at[index, "Booking ID"]).strip()
        if not booking_id:
            continue

        for column, value in build_common_tracking_enrichment(tracking_bookings, booking_id).items():
            output.at[index, column] = value

    return output
