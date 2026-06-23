from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.integrations.redash_call_comments import build_call_comments_query, build_comments_by_booking
from backend.app.integrations.tracking_reports import build_booking_wise_output


def test_build_call_comments_query_uses_workbook_booking_ids() -> None:
    query = build_call_comments_query(["B1", "B'2"])

    assert "td.entitykeyvirtual IN ('B1', 'B''2')" in query
    assert "a.summary AS comments" in query
    assert "WHERE rn = 1" in query


def test_build_comments_by_booking_dedupes_and_keeps_longest_first() -> None:
    comments = build_comments_by_booking(
        [
            {"booking_id": "B1", "comments": "short"},
            {"booking_id": "B1", "comments": "a much longer transcript"},
            {"booking_id": "B1", "comments": "short"},
            {"booking_id": "B2", "comments": None},
        ]
    )

    assert comments == {"B1": "a much longer transcript\n\nshort"}


def test_build_booking_wise_output_adds_comments_field() -> None:
    penalty_df = pd.DataFrame(
        [
            {"Booking ID": "B1", "Sub Category": "Cab Delay", "Remarks": "late cab"},
            {"Booking ID": "B2", "Sub Category": "Refund", "Remarks": "refund"},
        ]
    )

    payload = build_booking_wise_output(
        penalty_df=penalty_df,
        tracking_rows=[{"order_reference_number": "B1", "dispatch_id": "D1"}],
        selected_columns=["order_reference_number", "dispatch_id"],
        dropped_columns=[],
        table_name="tracking_reports_raw",
        source_workbook=Path("penalty_automation_output.xlsx"),
        comments_by_booking={"B1": "call transcript"},
        redash_comments_metadata={"enabled": True},
    )

    assert payload["metadata"]["source_workbook"] == "penalty_automation_output.xlsx"
    assert payload["metadata"]["commented_booking_count"] == 1
    assert payload["metadata"]["redash_comments"] == {"enabled": True}
    assert payload["bookings"]["B1"]["comments"] == "call transcript"
    assert "comments" not in payload["bookings"]["B2"]
