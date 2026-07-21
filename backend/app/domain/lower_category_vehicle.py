from __future__ import annotations

import json
from typing import Any

import pandas as pd

from backend.app.core.tracking_utils import booking_comments, first_tracking_row, raw_tracking_value
from backend.app.domain.cab_delay_enrichment import COMMENTS_COLUMN


VEHICLE_SUBCATEGORY_COLUMN = "vehicle_subcategory"
VEHICLE_TYPE_COLUMN = "vehicle_type"
CUSTOMER_BOOKED_VEHICLE_COLUMN = "customer booked vehicle"
CUSTOMER_RECEIVED_VEHICLE_COLUMN = "customer received vehicle"
LOWER_CATEGORY_VEHICLE_ENRICHMENT_COLUMNS = [
    VEHICLE_SUBCATEGORY_COLUMN,
    VEHICLE_TYPE_COLUMN,
    COMMENTS_COLUMN,
    CUSTOMER_BOOKED_VEHICLE_COLUMN,
    CUSTOMER_RECEIVED_VEHICLE_COLUMN,
]


def build_lower_category_vehicle_enrichment(bookings: dict[str, Any], booking_id: str) -> dict[str, str]:
    tracking_row = first_tracking_row(bookings, booking_id)
    return {
        VEHICLE_SUBCATEGORY_COLUMN: raw_tracking_value(tracking_row.get("vehicle_subcategory")),
        VEHICLE_TYPE_COLUMN: raw_tracking_value(tracking_row.get("vehicle_type")),
        COMMENTS_COLUMN: booking_comments(bookings, booking_id) or raw_tracking_value(
            tracking_row.get("comments")
        ),
    }


def ensure_lower_category_vehicle_columns(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    for column in LOWER_CATEGORY_VEHICLE_ENRICHMENT_COLUMNS:
        if column not in output.columns:
            output[column] = pd.Series([""] * len(output), index=output.index, dtype=object)
        else:
            output[column] = output[column].astype(object)
    return output


def build_lower_category_vehicle_prompt(*, booking_id: str, comments: str) -> str:
    return "\n".join(
        [
            (
                "Extract the vehicle category the customer says they booked and the vehicle category "
                "they say they received."
            ),
            "Return only a strict JSON object with these exact keys:",
            '{"customer_booked_vehicle": "", "customer_received_vehicle": ""}',
            "If either value is not clearly present in the comment, use an empty string for that value.",
            "Do not infer from tracking data, booking IDs, or outside knowledge.",
            "",
            f"Booking ID: {booking_id}",
            f"Customer comment: {comments}",
        ]
    )


def parse_lower_category_vehicle_response(value: str) -> dict[str, str]:
    parsed = json.loads(value.strip())
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object.")

    return {
        CUSTOMER_BOOKED_VEHICLE_COLUMN: raw_tracking_value(parsed.get("customer_booked_vehicle")),
        CUSTOMER_RECEIVED_VEHICLE_COLUMN: raw_tracking_value(parsed.get("customer_received_vehicle")),
    }
