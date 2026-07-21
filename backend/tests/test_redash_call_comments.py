from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.integrations.redash_call_comments import build_call_comments_query, build_comments_by_booking
from backend.app.integrations.tracking_reports import (
    VENDOR_NAME_COLUMN,
    add_column_once,
    add_vendor_names_to_tracking_rows,
    build_booking_wise_output,
    collect_supplier_ids,
    prune_unhelpful_columns,
)


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
        source_workbook=Path("agentic_loss_recovery_output.xlsx"),
        comments_by_booking={"B1": "call transcript"},
        redash_comments_metadata={"enabled": True},
    )

    assert payload["metadata"]["source_workbook"] == "agentic_loss_recovery_output.xlsx"
    assert payload["metadata"]["commented_booking_count"] == 1
    assert payload["metadata"]["redash_comments"] == {"enabled": True}
    assert payload["bookings"]["B1"]["comments"] == "call transcript"
    assert "comments" not in payload["bookings"]["B2"]


def test_supplier_lookup_adds_vendor_name_to_tracking_rows() -> None:
    tracking_rows = [
        {"order_reference_number": "B1", "dispatch_id": "D1", "supplier_id": "S1"},
        {"order_reference_number": "B2", "dispatch_id": "D2", "supplier_id": "S2"},
        {
            "order_reference_number": "B3",
            "dispatch_id": "D3",
            "supplier_id": "",
            "original_supplier_id": "S3",
        },
    ]

    supplier_ids = collect_supplier_ids(tracking_rows)
    matched_count = add_vendor_names_to_tracking_rows(
        tracking_rows,
        vendor_names_by_supplier_id={"S1": "Acme Cabs", "S3": "Fallback Cabs"},
    )
    selected_columns = add_column_once(
        ["order_reference_number", "dispatch_id", "supplier_id"],
        VENDOR_NAME_COLUMN,
    )
    pruned_rows, kept_columns, dropped_columns = prune_unhelpful_columns(tracking_rows, selected_columns)

    assert supplier_ids == ["S1", "S2", "S3"]
    assert matched_count == 2
    assert tracking_rows[0][VENDOR_NAME_COLUMN] == "Acme Cabs"
    assert tracking_rows[2][VENDOR_NAME_COLUMN] == "Fallback Cabs"
    assert VENDOR_NAME_COLUMN in kept_columns
    assert VENDOR_NAME_COLUMN not in dropped_columns
    assert pruned_rows[0][VENDOR_NAME_COLUMN] == "Acme Cabs"
    assert pruned_rows[2][VENDOR_NAME_COLUMN] == "Fallback Cabs"


def test_build_booking_wise_output_includes_vendor_name_metadata() -> None:
    penalty_df = pd.DataFrame(
        [
            {"Booking ID": "B1", "Sub Category": "Cab Delay", "Remarks": "late cab"},
        ]
    )

    payload = build_booking_wise_output(
        penalty_df=penalty_df,
        tracking_rows=[
            {
                "order_reference_number": "B1",
                "dispatch_id": "D1",
                "supplier_id": "S1",
                VENDOR_NAME_COLUMN: "Acme Cabs",
            }
        ],
        selected_columns=[
            "order_reference_number",
            "dispatch_id",
            "supplier_id",
            VENDOR_NAME_COLUMN,
        ],
        dropped_columns=[],
        table_name="tracking_reports_raw",
        source_workbook=Path("agentic_loss_recovery_output.xlsx"),
        vendor_name_metadata={"source_table": "incabs_suppliers"},
    )

    assert payload["metadata"]["vendor_name"] == {"source_table": "incabs_suppliers"}
    assert payload["bookings"]["B1"]["tracking_reports_raw"][0][VENDOR_NAME_COLUMN] == "Acme Cabs"
