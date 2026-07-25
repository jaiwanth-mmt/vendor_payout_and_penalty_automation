"""Tests for the human edit stage helpers and approve-edits packaging."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd

from backend.app.integrations.tracking import InMemoryTrackingRepository
from backend.app.services.edit_cases import (
    apply_edit_outcomes,
    bulk_patch_edit_outcomes,
    distinct_edit_sub_categories,
    edit_case_api_view,
    filter_edit_cases,
    patch_edit_case,
    prepare_case_for_edit,
    prepare_cases_for_edit,
)
from backend.app.services.pipeline import apply_edits_and_package, process_uploaded_workbook
from backend.tests.factories import mock_llm, write_sample_workbook, write_tracking_json


def test_prepare_and_patch_edit_case_marks_was_edited() -> None:
    cases = prepare_cases_for_edit(
        [
            {
                "booking_id": "B1",
                "sub_category": "Cab Delay",
                "remarks": "late",
                "message": "Cab Delayed",
                "comments": "call note",
                "recoverable_amount": 150,
                "review_status": "needs_review",
                "final_decision": {"review_reason": "Needs check", "confidence": 0.5},
            }
        ]
    )
    case = cases[0]
    assert case["ai_bucket"] == "needs_check"
    assert case["edit_outcome"] == "needs_ops"
    assert case["was_edited"] is False

    patched = patch_edit_case(
        case,
        {
            "booking_id": "SHOULD_IGNORE",
            "recoverable_amount": 200,
            "edit_outcome": "include",
            "sub_category": "Cab Delay",
        },
    )
    assert patched["booking_id"] == "B1"
    assert patched["recoverable_amount"] == 200
    assert patched["was_edited"] is True
    assert "recoverable_amount" in patched["edited_fields"]
    assert "edit_outcome" in patched["edited_fields"]


def test_apply_edit_outcomes_exclude_and_include() -> None:
    cases = prepare_cases_for_edit(
        [
            {
                "booking_id": "B1",
                "sub_category": "Cab Delay",
                "remarks": "Cab Delay",
                "message": "Cab Delay",
                "recoverable_amount": 100,
                "review_status": "auto_ready",
                "final_decision": {"decision": "valid_penalty", "confidence": 0.9, "review_status": "auto_ready"},
            },
            {
                "booking_id": "B2",
                "sub_category": "Cab Delay",
                "remarks": "late cab",
                "message": "Cab Delay",
                "recoverable_amount": 50,
                "review_status": "needs_review",
                "final_decision": {"decision": "needs_review", "confidence": 0.4, "review_status": "needs_review"},
            },
        ]
    )
    cases[1] = patch_edit_case(cases[1], {"edit_outcome": "exclude"})
    applied = apply_edit_outcomes(cases)
    assert applied[0]["review_status"] == "auto_ready"
    assert applied[0]["excluded"] is False
    assert applied[1]["excluded"] is True
    assert applied[1]["final_decision"]["recommended_recovery_amount"] == 0


def test_filter_edit_cases_by_booking_bucket_and_sub_category() -> None:
    cases = prepare_cases_for_edit(
        [
            {
                "booking_id": "B1",
                "sub_category": "Cab Delay",
                "remarks": "late cab",
                "message": "Cab Delay",
                "recoverable_amount": 100,
                "review_status": "auto_ready",
            },
            {
                "booking_id": "B2",
                "sub_category": "Extra Money Taken",
                "remarks": "extra cash",
                "message": "Extra Money Taken",
                "recoverable_amount": 50,
                "review_status": "needs_review",
            },
            {
                "booking_id": "B3",
                "sub_category": "Cab Delay",
                "remarks": "driver late",
                "message": "Cab Delay",
                "recoverable_amount": 75,
                "review_status": "needs_review",
            },
            {
                "booking_id": "B4",
                "sub_category": "Brand New Penalty Type",
                "remarks": "odd case",
                "message": "",
                "recoverable_amount": 40,
                "review_status": "auto_ready",
            },
            {
                "booking_id": "B5",
                "sub_category": "Cab Delay",
                "remarks": "",
                "message": "Cab Delay",
                "recoverable_amount": 60,
                "review_status": "auto_ready",
            },
        ]
    )

    assert cases[0]["ai_bucket"] == "auto_approved"
    assert cases[1]["ai_bucket"] == "needs_check"
    assert cases[3]["ai_bucket"] == "unhandled"
    assert cases[3]["edit_outcome"] == "needs_ops"
    assert cases[4]["ai_bucket"] == "needs_check"
    assert "Remarks are absent" in cases[4]["review_reason"]

    assert [case["booking_id"] for case in filter_edit_cases(cases, booking_id=" B2 ")] == ["B2"]
    assert filter_edit_cases(cases, booking_id="missing") == []
    assert [case["booking_id"] for case in filter_edit_cases(cases, sub_category="Cab Delay")] == [
        "B1",
        "B3",
        "B5",
    ]
    assert [
        case["booking_id"]
        for case in filter_edit_cases(
            cases,
            bucket="needs_check",
            sub_category="Cab Delay",
        )
    ] == ["B3", "B5"]
    assert [case["booking_id"] for case in filter_edit_cases(cases, bucket="unhandled")] == ["B4"]
    assert distinct_edit_sub_categories(cases) == [
        "Brand New Penalty Type",
        "Cab Delay",
        "Extra Money Taken",
    ]


def test_edit_bucket_routing_for_absent_remarks_and_sub_category() -> None:
    both_absent = prepare_case_for_edit(
        {
            "booking_id": "U1",
            "sub_category": "",
            "remarks": "",
            "recoverable_amount": 10,
            "review_status": "auto_ready",
        }
    )
    assert both_absent["ai_bucket"] == "unhandled"
    assert both_absent["sub_category"] == "Uncategorized"
    assert "Remarks and Sub Category are absent" in both_absent["review_reason"]

    sub_absent = prepare_case_for_edit(
        {
            "booking_id": "U2",
            "sub_category": "Uncategorized",
            "remarks": "driver was rude",
            "recoverable_amount": 20,
            "review_status": "auto_ready",
        }
    )
    assert sub_absent["ai_bucket"] == "unhandled"
    assert "Sub Category is absent" in sub_absent["review_reason"]
    assert "Uncategorized" in sub_absent["review_reason"]

    remarks_absent = prepare_case_for_edit(
        {
            "booking_id": "U3",
            "sub_category": "Cab Delay",
            "remarks": "",
            "message": "Cab Delay",
            "recoverable_amount": 30,
            "review_status": "auto_ready",
        }
    )
    assert remarks_absent["ai_bucket"] == "needs_check"
    assert "Remarks are absent" in remarks_absent["review_reason"]
    assert "message was generated from Sub Category" in remarks_absent["review_reason"]

    fulfillment_missing_remarks = prepare_case_for_edit(
        {
            "booking_id": "U4",
            "sub_category": "FULFILLMENT NOT DONE",
            "remarks": "",
            "message": "Vendor No Show",
            "recoverable_amount": 500,
            "review_status": "auto_ready",
            "amount": 2828,
            "ttrip_type": "airport",
            "fine_before_sop": 125,
            "fine_after_sop": 500,
            "sop_calculation_failed": False,
        }
    )
    assert fulfillment_missing_remarks["ai_bucket"] == "needs_check"
    assert "Remarks are absent" in fulfillment_missing_remarks["review_reason"]
    view = edit_case_api_view(fulfillment_missing_remarks)
    assert "Remarks are absent" in view["review_reason"]


def test_bulk_patch_edit_outcomes_respects_bucket_and_filters() -> None:
    cases = prepare_cases_for_edit(
        [
            {
                "booking_id": "B1",
                "sub_category": "Cab Delay",
                "remarks": "late",
                "recoverable_amount": 100,
                "review_status": "needs_review",
            },
            {
                "booking_id": "B2",
                "sub_category": "Extra Money Taken",
                "remarks": "extra",
                "recoverable_amount": 50,
                "review_status": "needs_review",
            },
            {
                "booking_id": "B3",
                "sub_category": "Cab Delay",
                "remarks": "delay",
                "recoverable_amount": 75,
                "review_status": "auto_ready",
            },
        ]
    )

    updated, count = bulk_patch_edit_outcomes(
        cases,
        bucket="needs_check",
        edit_outcome="include",
        sub_category="Cab Delay",
    )
    assert count == 1
    by_id = {case["booking_id"]: case for case in updated}
    assert by_id["B1"]["edit_outcome"] == "include"
    assert by_id["B1"]["was_edited"] is True
    assert by_id["B2"]["edit_outcome"] == "needs_ops"
    assert by_id["B3"]["edit_outcome"] == "include"
    assert by_id["B3"]["was_edited"] is False


def test_process_pauses_for_edit_then_approve_packages(tmp_path: Path) -> None:
    workbook_path = tmp_path / "qliksense.xlsx"
    tracking_path = tmp_path / "tracking.json"
    package_path = tmp_path / "agentic_loss_recovery_package.zip"
    write_sample_workbook(workbook_path)
    write_tracking_json(tracking_path)

    result = process_uploaded_workbook(
        input_path=workbook_path,
        tracking_repository=InMemoryTrackingRepository(json_path=tracking_path),
        output_package_path=package_path,
        start_date="2026-03-19",
        end_date="2026-03-19",
        on_step_start=lambda _step_id, _message: None,
        on_step_complete=lambda _step_id, _message: None,
        on_warning=lambda _warning: None,
        reason_generator=mock_llm,
        job_id="edit-test-job",
    )

    assert result.awaiting_edit is True
    assert not package_path.exists()
    assert result.agent_cases[0]["ai_bucket"] in {"needs_check", "auto_approved", "unhandled"}
    assert "edit_outcome" in result.agent_cases[0]

    edited = patch_edit_case(result.agent_cases[0], {"recoverable_amount": 175, "edit_outcome": "include"})
    packaged = asyncio.run(
        apply_edits_and_package(
            job_dir=tmp_path,
            output_package_path=package_path,
            start_date="2026-03-19",
            end_date="2026-03-19",
            category_outputs=result.category_outputs,
            agent_cases=[edited],
            metrics=result.metrics,
            job_id="edit-test-job",
        )
    )

    assert package_path.exists()
    assert packaged["metrics"]["agent_total_recoverable_amount"] == 175
    assert packaged["agent_summary"]["total_recoverable_amount"] == 175
    assert packaged["metrics"]["edited_case_count"] == 1
    final_df = pd.read_excel(packaged["final_output_path"], keep_default_na=False)
    assert float(final_df.loc[0, "fine"]) == 175
    processed = pd.read_excel(tmp_path / "category_files" / "processed" / "cab-delay.xlsx", keep_default_na=False)
    assert float(processed.loc[0, "Recoverable"]) == 175


def test_exclude_omits_from_final_output_and_totals(tmp_path: Path) -> None:
    workbook_path = tmp_path / "qliksense.xlsx"
    tracking_path = tmp_path / "tracking.json"
    package_path = tmp_path / "agentic_loss_recovery_package.zip"
    write_sample_workbook(workbook_path)
    write_tracking_json(tracking_path)

    result = process_uploaded_workbook(
        input_path=workbook_path,
        tracking_repository=InMemoryTrackingRepository(json_path=tracking_path),
        output_package_path=package_path,
        start_date="2026-03-19",
        end_date="2026-03-19",
        on_step_start=lambda _step_id, _message: None,
        on_step_complete=lambda _step_id, _message: None,
        on_warning=lambda _warning: None,
        reason_generator=mock_llm,
        job_id="exclude-test-job",
    )
    excluded = patch_edit_case(result.agent_cases[0], {"edit_outcome": "exclude"})
    packaged = asyncio.run(
        apply_edits_and_package(
            job_dir=tmp_path,
            output_package_path=package_path,
            start_date="2026-03-19",
            end_date="2026-03-19",
            category_outputs=result.category_outputs,
            agent_cases=[excluded],
            metrics=result.metrics,
            job_id="exclude-test-job",
        )
    )
    assert packaged["metrics"]["final_output_rows"] == 0
    assert packaged["agent_summary"]["total_recoverable_amount"] == 0
    assert packaged["metrics"]["excluded_case_count"] == 1
    final_df = pd.read_excel(packaged["final_output_path"], keep_default_na=False)
    assert len(final_df) == 0
