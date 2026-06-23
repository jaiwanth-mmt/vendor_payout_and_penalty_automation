from __future__ import annotations

from typing import Any

import pandas as pd

from backend.app.domain.cab_delay_enrichment import (
    COMMENTS_COLUMN,
    booking_comments,
    first_tracking_row,
)
from backend.app.domain.tracking_common import tracking_cell_value


EXTRA_MONEY_TAKEN_TRACKING_FIELDS = [
    "type",
    "ttrip_type",
]
EXTRA_MONEY_TAKEN_ENRICHMENT_COLUMNS = [*EXTRA_MONEY_TAKEN_TRACKING_FIELDS, COMMENTS_COLUMN]


def build_extra_money_taken_enrichment(bookings: dict[str, Any], booking_id: str) -> dict[str, Any]:
    tracking_row = first_tracking_row(bookings, booking_id)
    enrichment = {
        field: tracking_cell_value(tracking_row.get(field))
        for field in EXTRA_MONEY_TAKEN_TRACKING_FIELDS
    }
    enrichment[COMMENTS_COLUMN] = booking_comments(bookings, booking_id) or tracking_cell_value(
        tracking_row.get("comments")
    )
    return enrichment


def enrich_extra_money_taken_rows(df: pd.DataFrame, *, tracking_bookings: dict[str, Any]) -> pd.DataFrame:
    output = df.copy()
    for column in EXTRA_MONEY_TAKEN_ENRICHMENT_COLUMNS:
        if column not in output.columns:
            output[column] = pd.Series([""] * len(output), index=output.index, dtype=object)
        else:
            output[column] = output[column].astype(object)

    for index in output.index.tolist():
        booking_id = str(output.at[index, "Booking ID"]).strip()
        if not booking_id:
            continue

        for column, value in build_extra_money_taken_enrichment(tracking_bookings, booking_id).items():
            output.at[index, column] = value

    return output
