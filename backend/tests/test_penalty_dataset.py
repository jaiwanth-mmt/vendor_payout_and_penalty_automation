from __future__ import annotations

import pandas as pd
import pytest

from backend.app.domain.penalty_dataset import (
    drop_excluded_remarks,
    drop_excluded_subcategories,
    filter_by_input_date_range,
    is_excluded_remark,
    is_excluded_subcategory,
    parse_approval_datetimes,
)


def test_filter_by_input_date_range_is_inclusive() -> None:
    df = pd.DataFrame(
        {
            "Approval/Rejected DateTime": [
                "2026-03-18 23:00:00",
                "2026-03-19 10:00:00",
                "2026-03-20 01:00:00",
                "2026-03-21 12:00:00",
            ],
            "Booking ID": ["A", "B", "C", "D"],
        }
    )

    filtered = filter_by_input_date_range(
        df,
        "Approval/Rejected DateTime",
        "2026-03-19",
        "2026-03-20",
    )

    assert filtered["Booking ID"].tolist() == ["B", "C"]


def test_filter_by_input_date_range_rejects_inverted_bounds() -> None:
    df = pd.DataFrame(
        {
            "Approval/Rejected DateTime": ["2026-03-19"],
            "Booking ID": ["A"],
        }
    )
    with pytest.raises(ValueError, match="start_date"):
        filter_by_input_date_range(df, "Approval/Rejected DateTime", "2026-03-21", "2026-03-19")


def test_parse_approval_datetimes_strips_qliksense_day_first_text() -> None:
    series = pd.Series(
        [
            "20/07/2026  4:29:37 PM",
            "07/04/2026  1:00:00 PM",
            "19/07/2026 3:34:45 PM",
        ]
    )
    parsed = parse_approval_datetimes(series)
    assert parsed.dt.normalize().tolist() == [
        pd.Timestamp("2026-07-20"),
        pd.Timestamp("2026-04-07"),
        pd.Timestamp("2026-07-19"),
    ]


def test_filter_by_approval_datetime_day_first_text_inclusive() -> None:
    df = pd.DataFrame(
        {
            "Approval/Rejected DateTime": [
                "19/07/2026  11:00:00 PM",
                "20/07/2026  4:29:37 PM",
                "21/07/2026  1:00:00 AM",
            ],
            "Booking ID": ["A", "B", "C"],
        }
    )
    filtered = filter_by_input_date_range(
        df,
        "Approval/Rejected DateTime",
        "2026-07-20",
        "2026-07-20",
    )
    assert filtered["Booking ID"].tolist() == ["B"]


def test_is_excluded_subcategory_user_cancellation_and_customer_delight() -> None:
    assert is_excluded_subcategory("User cancellation")
    assert is_excluded_subcategory("USER CANCELLATION")
    assert is_excluded_subcategory("CARBD - User cancellation")
    assert is_excluded_subcategory("IER-Customer Delight")
    assert is_excluded_subcategory("Customer Delight")
    assert not is_excluded_subcategory("Cab Delay")
    assert not is_excluded_subcategory("Accidental Case")


def test_drop_excluded_subcategories_removes_penalty_ineligible_rows() -> None:
    df = pd.DataFrame(
        {
            "Booking ID": ["A", "B", "C", "D"],
            "Sub Category": [
                "Cab Delay",
                "User cancellation",
                "IER-Customer Delight",
                "CARBD - customer delight",
            ],
        }
    )
    kept = drop_excluded_subcategories(df)
    assert kept["Booking ID"].tolist() == ["A"]


def test_is_excluded_remark_paid_amount_refund_variants() -> None:
    assert is_excluded_remark("paid amount refund - AutoClaim raised")
    assert is_excluded_remark("refund of the paid amount - AutoClaim raised")
    assert is_excluded_remark("refund of paid amount.")
    assert is_excluded_remark("VENDOR  NO SHOW (PAID  AMOUNT  REFUND)")
    assert is_excluded_remark("vendor no show (paid  amount refund ) - AutoClaim raised")
    assert is_excluded_remark("Refund of the paid amount")
    assert not is_excluded_remark("Cab Delay")
    assert not is_excluded_remark("Vendor No Show")
    assert not is_excluded_remark("extra money refund - AutoClaim raised")
    assert not is_excluded_remark("EXTRA AMOUNT REFUND")
    assert not is_excluded_remark("")


def test_drop_excluded_remarks_removes_paid_amount_refund_rows() -> None:
    df = pd.DataFrame(
        {
            "Booking ID": ["A", "B", "C", "D"],
            "Remarks": [
                "Cab Delay",
                "paid amount refund - AutoClaim raised",
                "VENDOR NO SHOW (PAID AMOUNT REFUND)",
                "extra money refund - AutoClaim raised",
            ],
        }
    )
    kept = drop_excluded_remarks(df)
    assert kept["Booking ID"].tolist() == ["A", "D"]
