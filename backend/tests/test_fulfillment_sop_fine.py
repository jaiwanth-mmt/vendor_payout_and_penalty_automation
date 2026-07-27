from __future__ import annotations

import pandas as pd

from backend.app.domain.fulfillment_not_done import (
    FINE_AFTER_SOP_COLUMN,
    FINE_BEFORE_SOP_COLUMN,
    SOP_CALCULATION_FAILED_COLUMN,
    compute_vendor_no_show_sop_fine,
    enrich_fulfillment_not_done_rows,
    is_airport_trip_type,
)
from backend.app.services.edit_cases import prepare_case_for_edit, vendor_no_show_sop_missing


def test_is_airport_trip_type_accepts_airport_and_local() -> None:
    assert is_airport_trip_type("airport")
    assert is_airport_trip_type("LOCAL")
    assert not is_airport_trip_type("outstation")
    assert not is_airport_trip_type("")


def test_compute_vendor_no_show_sop_fine_airport_and_outstation() -> None:
    assert compute_vendor_no_show_sop_fine(amount=2828, ttrip_type="airport") == 500
    assert compute_vendor_no_show_sop_fine(amount=800, ttrip_type="local") == 400
    assert compute_vendor_no_show_sop_fine(amount=10000, ttrip_type="outstation") == 2000
    assert compute_vendor_no_show_sop_fine(amount=4000, ttrip_type="roundtrip") == 1000


def test_compute_vendor_no_show_sop_fine_half_up_rounding() -> None:
    # 653 airport: min(0.5*653, 500) = 326.5 → half-up → 327
    assert compute_vendor_no_show_sop_fine(amount=653, ttrip_type="airport") == 327
    # 651 airport: min(0.5*651, 500) = 325.5 → half-up → 326
    assert compute_vendor_no_show_sop_fine(amount=651, ttrip_type="airport") == 326
    # 649 airport: min(0.5*649, 500) = 324.5 → half-up → 325
    assert compute_vendor_no_show_sop_fine(amount=649, ttrip_type="airport") == 325
    # 646 airport: min(0.5*646, 500) = 323.0 → exact → 323
    assert compute_vendor_no_show_sop_fine(amount=646, ttrip_type="airport") == 323
    # Fractional < 0.5 via 0.25 rate: 1281 outstation → 320.25 → 320
    assert compute_vendor_no_show_sop_fine(amount=1281, ttrip_type="outstation") == 320
    # Fractional > 0.5 via 0.25 rate: 1283 outstation → 320.75 → 321
    assert compute_vendor_no_show_sop_fine(amount=1283, ttrip_type="outstation") == 321
    # Exact half via 0.25 rate: 1282 outstation → 320.5 → 321
    assert compute_vendor_no_show_sop_fine(amount=1282, ttrip_type="outstation") == 321


def test_compute_vendor_no_show_sop_fine_missing_inputs() -> None:
    assert compute_vendor_no_show_sop_fine(amount="", ttrip_type="airport") is None
    assert compute_vendor_no_show_sop_fine(amount=1200, ttrip_type="") is None
    assert compute_vendor_no_show_sop_fine(amount=0, ttrip_type="airport") is None
    assert compute_vendor_no_show_sop_fine(amount=None, ttrip_type="local") is None


def test_enrich_fulfillment_overwrites_recoverable_with_sop_fine() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B6",
                "Recoverable": 125,
                "amount": 2828,
                "ttrip_type": "airport",
            }
        ]
    )
    tracking = {"B6": {"tracking_reports_raw": [{}], "comments": ""}}

    output = enrich_fulfillment_not_done_rows(df, tracking_bookings=tracking)

    assert output.loc[0, FINE_BEFORE_SOP_COLUMN] == 125.0
    assert output.loc[0, FINE_AFTER_SOP_COLUMN] == 500.0
    assert output.loc[0, "Recoverable"] == 500.0
    assert output.loc[0, SOP_CALCULATION_FAILED_COLUMN] is False


def test_enrich_fulfillment_keeps_original_when_sop_inputs_missing() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B6",
                "Recoverable": 125,
                "amount": "",
                "ttrip_type": "",
            }
        ]
    )
    tracking = {"B6": {"tracking_reports_raw": [{}], "comments": ""}}

    output = enrich_fulfillment_not_done_rows(df, tracking_bookings=tracking)

    assert output.loc[0, FINE_BEFORE_SOP_COLUMN] == 125.0
    assert output.loc[0, FINE_AFTER_SOP_COLUMN] == ""
    assert output.loc[0, "Recoverable"] == 125
    assert output.loc[0, SOP_CALCULATION_FAILED_COLUMN] is True


def test_prepare_case_for_edit_forces_needs_check_when_sop_missing() -> None:
    case = prepare_case_for_edit(
        {
            "booking_id": "B6",
            "sub_category": "FULFILLMENT NOT DONE",
            "remarks": "Vendor No Show",
            "recoverable_amount": 125,
            "review_status": "auto_ready",
            "amount": None,
            "ttrip_type": "",
            "fine_before_sop": 125,
            "fine_after_sop": None,
            "sop_calculation_failed": True,
        }
    )

    assert vendor_no_show_sop_missing(case)
    assert case["ai_bucket"] == "needs_check"
    assert case["ai_review_status"] == "needs_review"
    assert "SOP fine could not be computed" in case["review_reason"]
