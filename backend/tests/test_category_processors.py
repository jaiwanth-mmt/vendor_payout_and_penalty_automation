from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd

from backend.app.domain.cab_delay_enrichment import (
    BOARDED_COLUMN,
    COMMENTS_COLUMN,
    DRIVER_ARRIVED_COLUMN,
    DRIVER_STARTED_COLUMN,
    INCABS_INSIGHT_COLUMN,
    PREFERRED_START_TIME_IST_COLUMN,
    build_tracking_enrichment,
)
from backend.app.domain.category_processors import (
    COMMON_PROCESSED_OUTPUT_COLUMNS,
    EXTRA_MONEY_TAKEN_OUTPUT_COLUMNS,
    FULFILLMENT_NOT_DONE_OUTPUT_COLUMNS,
    LOWER_CATEGORY_VEHICLE_OUTPUT_COLUMNS,
    enrich_cab_delay_insights_async,
    enrich_message_column_async,
    process_category_batch,
)
from backend.app.domain.complaint_message import MESSAGE_COLUMN
from backend.app.domain.fulfillment_not_done import (
    BOOKING_STATUS_COLUMN,
    FULFILLMENT_DRIVER_ARRIVED_COLUMN,
    FULFILLMENT_DRIVER_STARTED_COLUMN,
    FULFILLMENT_PREFERRED_START_TIME_COLUMN,
    TRACKING_STATUS_COLUMN,
)
from backend.app.domain.lower_category_vehicle import (
    CUSTOMER_BOOKED_VEHICLE_COLUMN,
    CUSTOMER_RECEIVED_VEHICLE_COLUMN,
    VEHICLE_SUBCATEGORY_COLUMN,
    VEHICLE_TYPE_COLUMN,
)
from backend.app.domain.subcategories import CategoryBatch
from backend.app.services.pipeline import process_uploaded_workbook
from backend.tests.factories import (
    assert_complaint_metadata,
    mock_llm,
    write_fulfillment_workbook,
    write_lower_category_workbook,
    write_tracking_json_with_extra_money,
    write_tracking_json_with_fulfillment,
    write_tracking_json_with_lower_category,
    write_two_category_workbook,
)


def test_async_cab_delay_llm_generation_respects_concurrency_limit() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": f"B{index}",
                "Booking Date": "2026-03-19",
                "Booking Month": "Mar 2026",
                "Loss Dept": "CARBD",
                "Sub Category": "Cab Delay",
                "Loss Amount": 100,
                "Recoverable": 100,
                "Remarks": "Cab Delay",
            }
            for index in range(1, 5)
        ]
    )
    tracking_bookings = {
        f"B{index}": {
            "tracking_reports_raw": [
                {
                    "order_reference_number": f"B{index}",
                    "start_time": "2026-03-19 04:30:00",
                    "driver_started": "2026-03-19 10:20:00",
                    "driver_arrived": "2026-03-19 10:40:00",
                    "boarded": "2026-03-19 10:45:00",
                }
            ],
            "comments": "",
        }
        for index in range(1, 5)
    }
    current_calls = 0
    max_seen = 0
    progress_updates: list[dict[str, int]] = []

    async def async_llm(_prompt: str, _tokens: int, _effort: str) -> str:
        nonlocal current_calls, max_seen
        current_calls += 1
        max_seen = max(max_seen, current_calls)
        await asyncio.sleep(0.01)
        current_calls -= 1
        return "Async insight."

    async def run() -> None:
        _output, summary = await enrich_cab_delay_insights_async(
            df,
            tracking_bookings=tracking_bookings,
            llm_generator=async_llm,
            llm_concurrency=2,
            on_progress=lambda counters, _message: progress_updates.append(counters.copy()),
        )
        assert summary.generated_insight_rows == 4

    asyncio.run(run())

    assert max_seen == 2
    assert progress_updates[-1]["generated_insight_rows"] == 4


def test_async_message_classification_respects_concurrency_limit() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": f"B{index}",
                "Sub Category": "Extra Money Taken",
                "Remarks": "driver collected extra",
                COMMENTS_COLUMN: "Customer said driver collected extra cash.",
            }
            for index in range(1, 5)
        ]
    )
    current_calls = 0
    max_seen = 0

    async def async_llm(_prompt: str, _tokens: int, _effort: str) -> str:
        nonlocal current_calls, max_seen
        current_calls += 1
        max_seen = max(max_seen, current_calls)
        await asyncio.sleep(0.01)
        current_calls -= 1
        return '{"categories": ["Extra Money Taken"]}'

    async def run() -> pd.DataFrame:
        return await enrich_message_column_async(
            df,
            llm_generator=async_llm,
            llm_concurrency=2,
        )

    output = asyncio.run(run())

    assert max_seen == 2
    assert output[MESSAGE_COLUMN].tolist() == ["Extra Money Taken"] * 4


def test_extra_money_taken_package_includes_tracking_columns(tmp_path: Path) -> None:
    workbook_path = tmp_path / "qliksense.xlsx"
    tracking_path = tmp_path / "tracking.json"
    package_path = tmp_path / "penalty_automation_package.zip"
    write_two_category_workbook(workbook_path)
    write_tracking_json_with_extra_money(tracking_path)

    warnings: list[dict[str, object]] = []
    result = process_uploaded_workbook(
        input_path=workbook_path,
        tracking_json_path=tracking_path,
        output_package_path=package_path,
        approval_date="2026-03-19",
        on_step_start=lambda _step_id, _message: None,
        on_step_complete=lambda _step_id, _message: None,
        on_warning=warnings.append,
        reason_generator=mock_llm,
    )

    extra_money_output = tmp_path / "category_files" / "processed" / "extra-money-taken.xlsx"
    output_df = pd.read_excel(extra_money_output, keep_default_na=False)
    extra_money_category = next(
        category for category in result.category_outputs if category["slug"] == "extra-money-taken"
    )

    assert warnings == []
    assert output_df.columns.tolist() == EXTRA_MONEY_TAKEN_OUTPUT_COLUMNS
    assert output_df.loc[0, "Booking ID"] == "B5"
    assert_complaint_metadata(output_df.loc[0], "dispatch-b5")
    assert output_df.loc[0, "type"] == "ONE_WAY"
    assert output_df.loc[0, "ttrip_type"] == "airport"
    assert output_df.loc[0, "amount"] == 1234
    assert output_df.loc[0, "cash_collected"] == 1000
    assert output_df.loc[0, "extra_travelled_fare"] == 90
    assert output_df.loc[0, "airport_entry_fee"] == 200
    assert output_df.loc[0, "comments"] == "Customer said driver collected extra cash for toll and parking."
    assert output_df.loc[0, MESSAGE_COLUMN] == "Extra Money Taken"
    assert extra_money_category["output_columns"] == EXTRA_MONEY_TAKEN_OUTPUT_COLUMNS
    assert extra_money_category["preview_rows"][0]["total_driver_charge"] == 150
    assert extra_money_category["preview_rows"][0]["comments"] == (
        "Customer said driver collected extra cash for toll and parking."
    )
    assert extra_money_category["preview_rows"][0][MESSAGE_COLUMN] == "Extra Money Taken"


def test_fulfillment_not_done_package_includes_tracking_status_and_times(tmp_path: Path) -> None:
    workbook_path = tmp_path / "qliksense.xlsx"
    tracking_path = tmp_path / "tracking.json"
    package_path = tmp_path / "penalty_automation_package.zip"
    write_fulfillment_workbook(workbook_path)
    write_tracking_json_with_fulfillment(tracking_path)

    warnings: list[dict[str, object]] = []
    result = process_uploaded_workbook(
        input_path=workbook_path,
        tracking_json_path=tracking_path,
        output_package_path=package_path,
        approval_date="2026-03-19",
        on_step_start=lambda _step_id, _message: None,
        on_step_complete=lambda _step_id, _message: None,
        on_warning=warnings.append,
        reason_generator=mock_llm,
    )

    fulfillment_output = tmp_path / "category_files" / "processed" / "fulfillment-not-done.xlsx"
    output_df = pd.read_excel(fulfillment_output, keep_default_na=False)
    fulfillment_category = result.category_outputs[0]

    assert warnings == []
    assert output_df.columns.tolist() == FULFILLMENT_NOT_DONE_OUTPUT_COLUMNS
    assert output_df.loc[0, "Booking ID"] == "B6"
    assert_complaint_metadata(output_df.loc[0], "dispatch-b6")
    assert output_df.loc[0, BOOKING_STATUS_COLUMN] == "CONFIRMED"
    assert output_df.loc[0, TRACKING_STATUS_COLUMN] == "NOT BOARDED"
    assert output_df.loc[0, "amount"] == 2828
    assert output_df.loc[0, "base_amount"] == 2413
    assert output_df.loc[0, "amount_paid"] == 566
    assert output_df.loc[0, "route_toll_charges"] == 80
    assert output_df.loc[0, "airport_entry_fee"] == 200
    assert output_df.loc[0, COMMENTS_COLUMN] == "Customer said the assigned cab did not arrive for the airport pickup."
    assert output_df.loc[0, FULFILLMENT_PREFERRED_START_TIME_COLUMN] == "19 Mar 2026 3:15 AM"
    assert output_df.loc[0, FULFILLMENT_DRIVER_STARTED_COLUMN] == "19 Mar 2026 3:21:38 AM"
    assert output_df.loc[0, FULFILLMENT_DRIVER_ARRIVED_COLUMN] == "19 Mar 2026 3:21:44 AM"
    assert output_df.loc[0, MESSAGE_COLUMN] == "Vendor No Show"
    assert fulfillment_category["output_columns"] == FULFILLMENT_NOT_DONE_OUTPUT_COLUMNS
    assert fulfillment_category["preview_rows"][0][FULFILLMENT_PREFERRED_START_TIME_COLUMN] == (
        "19 Mar 2026 3:15 AM"
    )
    assert fulfillment_category["preview_rows"][0][MESSAGE_COLUMN] == "Vendor No Show"


def test_lower_category_vehicle_package_includes_tracking_and_llm_columns(tmp_path: Path) -> None:
    workbook_path = tmp_path / "qliksense.xlsx"
    tracking_path = tmp_path / "tracking.json"
    package_path = tmp_path / "penalty_automation_package.zip"
    write_lower_category_workbook(workbook_path)
    write_tracking_json_with_lower_category(tracking_path)

    warnings: list[dict[str, object]] = []
    result = process_uploaded_workbook(
        input_path=workbook_path,
        tracking_json_path=tracking_path,
        output_package_path=package_path,
        approval_date="2026-03-19",
        on_step_start=lambda _step_id, _message: None,
        on_step_complete=lambda _step_id, _message: None,
        on_warning=warnings.append,
        reason_generator=mock_llm,
    )

    lower_category_output = tmp_path / "category_files" / "processed" / "lower-category-vehicle.xlsx"
    output_df = pd.read_excel(lower_category_output, keep_default_na=False)
    lower_category = result.category_outputs[0]

    assert warnings == []
    assert output_df.columns.tolist() == LOWER_CATEGORY_VEHICLE_OUTPUT_COLUMNS
    assert output_df.loc[0, "Booking ID"] == "B7"
    assert_complaint_metadata(output_df.loc[0], "dispatch-b7")
    assert output_df.loc[0, "amount"] == 6177
    assert output_df.loc[0, "cash_collected"] == 4736
    assert output_df.loc[0, "per_km_rate"] == 40.1
    assert output_df.loc[0, "total_distance"] == 294
    assert output_df.loc[0, "driver_charge_per_day"] == 170
    assert output_df.loc[0, VEHICLE_SUBCATEGORY_COLUMN] == "basic-electric"
    assert output_df.loc[0, VEHICLE_TYPE_COLUMN] == "sedan"
    assert output_df.loc[0, COMMENTS_COLUMN] == (
        "Customer booked an electric sedan but received a CNG hatchback instead."
    )
    assert output_df.loc[0, CUSTOMER_BOOKED_VEHICLE_COLUMN] == "electric sedan"
    assert output_df.loc[0, CUSTOMER_RECEIVED_VEHICLE_COLUMN] == "CNG hatchback"
    assert output_df.loc[0, MESSAGE_COLUMN] == "Low Category Vehicle"
    assert lower_category["output_columns"] == LOWER_CATEGORY_VEHICLE_OUTPUT_COLUMNS
    assert lower_category["preview_rows"][0][CUSTOMER_BOOKED_VEHICLE_COLUMN] == "electric sedan"
    assert lower_category["preview_rows"][0][CUSTOMER_RECEIVED_VEHICLE_COLUMN] == "CNG hatchback"
    assert lower_category["preview_rows"][0][MESSAGE_COLUMN] == "Low Category Vehicle"


def test_lower_category_vehicle_llm_failure_warns_and_leaves_values_blank(tmp_path: Path) -> None:
    workbook_path = tmp_path / "qliksense.xlsx"
    tracking_path = tmp_path / "tracking.json"
    package_path = tmp_path / "penalty_automation_package.zip"
    write_lower_category_workbook(workbook_path)
    write_tracking_json_with_lower_category(tracking_path)

    warnings: list[dict[str, object]] = []
    result = process_uploaded_workbook(
        input_path=workbook_path,
        tracking_json_path=tracking_path,
        output_package_path=package_path,
        approval_date="2026-03-19",
        on_step_start=lambda _step_id, _message: None,
        on_step_complete=lambda _step_id, _message: None,
        on_warning=warnings.append,
        reason_generator=lambda _prompt, _tokens, _effort: "not json",
    )

    output_df = pd.read_excel(
        tmp_path / "category_files" / "processed" / "lower-category-vehicle.xlsx",
        keep_default_na=False,
    )

    assert result.category_outputs[0]["status"] == "completed"
    assert output_df.loc[0, CUSTOMER_BOOKED_VEHICLE_COLUMN] == ""
    assert output_df.loc[0, CUSTOMER_RECEIVED_VEHICLE_COLUMN] == ""
    assert output_df.loc[0, MESSAGE_COLUMN] == "Low Category Vehicle"
    assert warnings == [
        {
            "code": "lower_category_vehicle_extraction_failed",
            "message": (
                "1 Lower Category Vehicle rows could not have booked/received vehicle values extracted "
                "from comments. Processed category files were still produced."
            ),
            "booking_ids": ["B7"],
        }
    ]


def test_tracking_enrichment_formats_pickup_utc_as_ist_with_date_rollover() -> None:
    bookings = {
        "B5": {
            "tracking_reports_raw": [
                {
                    "start_time": "2026-03-19 21:45:00",
                    "driver_started": "2026-03-20 03:20:05.500000",
                    "driver_arrived": "0",
                    "boarded": None,
                }
            ],
            "comments": "Driver was delayed.",
        }
    }

    columns = build_tracking_enrichment(bookings, "B5").to_columns()

    assert columns[PREFERRED_START_TIME_IST_COLUMN] == "20 Mar 2026 3:15 AM"
    assert columns[DRIVER_STARTED_COLUMN] == "20 Mar 2026 3:20:05 AM"
    assert columns[DRIVER_ARRIVED_COLUMN] == ""
    assert columns[BOARDED_COLUMN] == ""


def test_extra_money_processor_adds_tracking_fields_without_cab_columns() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B2",
                "Booking Date": "2026-03-19",
                "Booking Month": "Mar 2026",
                "Loss Dept": "CARBD",
                "Sub Category": "Extra Money Taken",
                "Loss Amount": 80,
                "Recoverable": 80,
                "Remarks": "driver collected extra",
            }
        ]
    )
    tracking_bookings = {
        "B2": {
            "tracking_reports_raw": [
                {
                    "type": "LOCAL_RENTAL",
                    "ttrip_type": "local",
                    "amount": 840,
                    "base_amount": 800,
                    "amount_paid": 200,
                    "cash_collected": 640,
                    "per_km_rate": 28,
                    "total_distance": 30,
                    "extra_travelled": 8.11,
                    "extra_travelled_fare": 0,
                    "route_toll_charges": 0,
                    "toll_charges": 0,
                    "toll_paid": 0,
                    "parking_charges": 0,
                    "state_tax": 0,
                    "airport_entry_fee": 0,
                    "night_charges": 0,
                    "waiting_charges": "0",
                    "driver_charge_per_day": 0,
                    "total_driver_charge": 0,
                }
            ],
            "comments": "Customer disputed extra cash collection.",
        }
    }

    outcome = process_category_batch(
        CategoryBatch(name="Extra Money Taken", slug="extra-money-taken", df=df),
        tracking_bookings=tracking_bookings,
        llm_generator=mock_llm,
    )

    assert outcome.df.columns.tolist() == EXTRA_MONEY_TAKEN_OUTPUT_COLUMNS
    assert outcome.df.loc[0, "type"] == "LOCAL_RENTAL"
    assert outcome.df.loc[0, "extra_travelled"] == 8.11
    assert outcome.df.loc[0, "comments"] == "Customer disputed extra cash collection."
    assert INCABS_INSIGHT_COLUMN not in outcome.df.columns
    assert outcome.insight_summary is None


def test_fulfillment_not_done_processor_adds_tracking_fields_without_cab_insights() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B6",
                "Booking Date": "2026-03-19",
                "Booking Month": "Mar 2026",
                "Loss Dept": "CARBD",
                "Sub Category": "FULFILLMENT NOT DONE",
                "Loss Amount": 125,
                "Recoverable": 125,
                "Remarks": "paid amount refund",
            }
        ]
    )
    tracking_bookings = {
        "B6": {
            "tracking_reports_raw": [
                {
                    "dispatch_id": "dispatch-b6",
                    "booking_status": "CONFIRMED",
                    "tracking_status": "NOT BOARDED",
                    "start_time": "2026-03-18 21:45:00",
                    "driver_started": "2026-03-19 03:21:38.764000",
                    "driver_arrived": "2026-03-19 03:21:44.001000",
                }
            ],
            "comments": "Customer said the cab did not arrive.",
        }
    }

    outcome = process_category_batch(
        CategoryBatch(name="FULFILLMENT NOT DONE", slug="fulfillment-not-done", df=df),
        tracking_bookings=tracking_bookings,
        llm_generator=mock_llm,
    )

    assert outcome.df.columns.tolist() == FULFILLMENT_NOT_DONE_OUTPUT_COLUMNS
    assert_complaint_metadata(outcome.df.loc[0], "dispatch-b6")
    assert outcome.df.loc[0, BOOKING_STATUS_COLUMN] == "CONFIRMED"
    assert outcome.df.loc[0, TRACKING_STATUS_COLUMN] == "NOT BOARDED"
    assert outcome.df.loc[0, COMMENTS_COLUMN] == "Customer said the cab did not arrive."
    assert outcome.df.loc[0, FULFILLMENT_PREFERRED_START_TIME_COLUMN] == "19 Mar 2026 3:15 AM"
    assert outcome.df.loc[0, FULFILLMENT_DRIVER_STARTED_COLUMN] == "19 Mar 2026 3:21:38 AM"
    assert outcome.df.loc[0, FULFILLMENT_DRIVER_ARRIVED_COLUMN] == "19 Mar 2026 3:21:44 AM"
    assert outcome.df.loc[0, MESSAGE_COLUMN] == "Vendor No Show"
    assert INCABS_INSIGHT_COLUMN not in outcome.df.columns
    assert outcome.insight_summary is None


def test_lower_category_vehicle_processor_adds_tracking_and_llm_fields_without_cab_insights() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B7",
                "Booking Date": "2026-03-19",
                "Booking Month": "Mar 2026",
                "Loss Dept": "CARBD",
                "Sub Category": "Lower Category Vehicle",
                "Loss Amount": 200,
                "Recoverable": 200,
                "Remarks": "low category vehicle",
            }
        ]
    )
    tracking_bookings = {
        "B7": {
            "tracking_reports_raw": [
                {
                    "dispatch_id": "dispatch-b7",
                    "vehicle_subcategory": "basic-electric",
                    "vehicle_type": "sedan",
                }
            ],
            "comments": "Customer booked an electric sedan but received a CNG hatchback instead.",
        }
    }

    outcome = process_category_batch(
        CategoryBatch(name="Lower Category Vehicle", slug="lower-category-vehicle", df=df),
        tracking_bookings=tracking_bookings,
        llm_generator=mock_llm,
    )

    assert outcome.df.columns.tolist() == LOWER_CATEGORY_VEHICLE_OUTPUT_COLUMNS
    assert_complaint_metadata(outcome.df.loc[0], "dispatch-b7")
    assert outcome.df.loc[0, VEHICLE_SUBCATEGORY_COLUMN] == "basic-electric"
    assert outcome.df.loc[0, VEHICLE_TYPE_COLUMN] == "sedan"
    assert outcome.df.loc[0, COMMENTS_COLUMN] == (
        "Customer booked an electric sedan but received a CNG hatchback instead."
    )
    assert outcome.df.loc[0, CUSTOMER_BOOKED_VEHICLE_COLUMN] == "electric sedan"
    assert outcome.df.loc[0, CUSTOMER_RECEIVED_VEHICLE_COLUMN] == "CNG hatchback"
    assert outcome.df.loc[0, MESSAGE_COLUMN] == "Low Category Vehicle"
    assert INCABS_INSIGHT_COLUMN not in outcome.df.columns
    assert outcome.insight_summary is None
    assert outcome.warnings == []


def test_other_category_processors_add_common_tracking_amount_fields() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B3",
                "Booking Date": "2026-03-19",
                "Booking Month": "Mar 2026",
                "Loss Dept": "CARBD",
                "Sub Category": "Driver Behavior",
                "Loss Amount": 80,
                "Recoverable": 80,
                "Remarks": "driver rude",
            }
        ]
    )
    tracking_bookings = {
        "B3": {
            "comments": "Customer reported the driver behaved rudely.",
            "tracking_reports_raw": [
                {
                    "dispatch_id": "dispatch-b3",
                    "amount": 980,
                    "base_amount": 900,
                    "amount_paid": 100,
                    "cash_collected": 880,
                    "per_km_rate": 22,
                    "total_distance": 40,
                    "extra_travelled": 3,
                    "extra_travelled_fare": 66,
                    "route_toll_charges": 50,
                    "toll_charges": 50,
                    "toll_paid": 1,
                    "parking_charges": 10,
                    "state_tax": 5,
                    "airport_entry_fee": 0,
                    "night_charges": 20,
                    "waiting_charges": "0",
                    "driver_charge_per_day": 30,
                    "total_driver_charge": 30,
                }
            ],
        }
    }

    outcome = process_category_batch(
        CategoryBatch(name="Driver Behavior", slug="driver-behavior", df=df),
        tracking_bookings=tracking_bookings,
        llm_generator=mock_llm,
    )

    assert outcome.df.columns.tolist() == COMMON_PROCESSED_OUTPUT_COLUMNS
    assert_complaint_metadata(outcome.df.loc[0], "dispatch-b3")
    assert outcome.df.loc[0, "amount"] == 980
    assert outcome.df.loc[0, "cash_collected"] == 880
    assert outcome.df.loc[0, "extra_travelled_fare"] == 66
    assert outcome.df.loc[0, "total_driver_charge"] == 30
    assert outcome.df.loc[0, COMMENTS_COLUMN] == "Customer reported the driver behaved rudely."
    assert outcome.df.loc[0, MESSAGE_COLUMN] == "Bad Driver Behaviour/Skill"
    assert INCABS_INSIGHT_COLUMN not in outcome.df.columns
    assert outcome.insight_summary is None
