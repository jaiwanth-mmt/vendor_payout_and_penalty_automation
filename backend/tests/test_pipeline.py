from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from backend.app.core.paths import DEMO_TRACKING_JSON_PATH, DEMO_WORKBOOK_PATH
from backend.app.domain.cab_delay_enrichment import (
    BOARDED_COLUMN,
    COMMENTS_COLUMN,
    DRIVER_ARRIVED_COLUMN,
    DRIVER_STARTED_COLUMN,
    INCABS_COMMENT_SUMMARY_COLUMN,
    INCABS_INSIGHT_COLUMN,
    PREFERRED_START_TIME_IST_COLUMN,
)
from backend.app.domain.complaint_message import MESSAGE_COLUMN
from backend.app.domain.tracking_common import (
    COMPLAINT_AGAINST_VALUE,
    TITLE_VALUE,
    VENDOR_NAME_COLUMN,
)
from backend.app.services import pipeline
from backend.app.services.pipeline import CAB_DELAY_OUTPUT_COLUMNS, process_uploaded_workbook
from backend.tests.factories import (
    assert_complaint_metadata,
    mock_llm,
    write_sample_workbook,
    write_tracking_json,
    write_two_category_workbook,
)


def test_process_uploaded_workbook_generates_category_package(tmp_path: Path) -> None:
    workbook_path = tmp_path / "qliksense.xlsx"
    tracking_path = tmp_path / "tracking.json"
    package_path = tmp_path / "agentic_loss_recovery_package.zip"
    write_sample_workbook(workbook_path)
    write_tracking_json(tracking_path)

    started_steps: list[str] = []
    completed_steps: list[str] = []
    warnings: list[dict[str, object]] = []

    result = process_uploaded_workbook(
        input_path=workbook_path,
        tracking_json_path=tracking_path,
        output_package_path=package_path,
        approval_date="2026-03-19",
        on_step_start=lambda step_id, _message: started_steps.append(step_id),
        on_step_complete=lambda step_id, _message: completed_steps.append(step_id),
        on_warning=warnings.append,
        reason_generator=mock_llm,
    )

    cab_delay_output = tmp_path / "category_files" / "processed" / "cab-delay.xlsx"
    output_df = pd.read_excel(cab_delay_output, keep_default_na=False)
    assert result.metrics["raw_rows"] == 5
    assert result.metrics["date_filtered_rows"] == 4
    assert result.metrics["prepared_rows"] == 1
    assert result.metrics["category_count"] == 1
    assert result.metrics["generated_insight_rows"] == 1
    assert result.metrics["generated_comment_summary_rows"] == 1
    assert result.package_path == package_path
    assert result.manifest_path == tmp_path / "manifest.json"
    assert result.final_output_path == tmp_path / "final_output.xlsx"
    assert result.agent_audit_path == tmp_path / "agent_audit.xlsx"
    assert result.review_queue_path == tmp_path / "review_queue.xlsx"
    assert result.agent_summary_path == tmp_path / "agent_summary.json"
    assert package_path.exists()
    assert result.case_counts["total_cases"] == 1
    assert result.agent_summary["case_counts"]["total_cases"] == 1
    assert result.agent_summary["top_vendors_by_penalty"] == [
        {
            "vendor_name": "savaari",
            "case_count": 1,
            "total_recoverable": 150,
            "top_subcategories": [
                {"subcategory": "Cab Delay", "case_count": 1, "total_recoverable": 150},
            ],
        }
    ]
    assert result.agent_summary["top_subcategories_by_penalty"] == [
        {"subcategory": "Cab Delay", "case_count": 1, "total_recoverable": 150},
    ]
    assert result.agent_summary["top_subcategories_by_count"] == [
        {"subcategory": "Cab Delay", "case_count": 1, "total_recoverable": 150},
    ]
    assert result.agent_cases[0]["booking_id"] == "B1"
    assert result.agent_cases[0]["vendor_name"] == "savaari"
    assert result.agent_cases[0]["final_decision"]["agent"] == "Judge Agent"
    assert result.final_output == {
        "filename": "final_output.xlsx",
        "row_count": 1,
        "columns": pipeline.FINAL_EXPORT_COLUMNS,
        "download_ready": True,
    }
    assert not (tmp_path / "agentic_loss_recovery_output.csv").exists()
    final_output_df = pd.read_excel(result.final_output_path, keep_default_na=False)
    assert final_output_df.columns.tolist() == pipeline.FINAL_EXPORT_COLUMNS
    assert final_output_df.loc[0, "booking_id"] == "B1"
    assert final_output_df.loc[0, "complaint_reasons"] == "Cab Delay"
    assert final_output_df.loc[0, "complaint_against"] == COMPLAINT_AGAINST_VALUE
    assert final_output_df.loc[0, "complaint_against_id"] == "dispatch-b1"
    assert final_output_df.loc[0, "title"] == TITLE_VALUE
    assert final_output_df.loc[0, "message"] == "Cab Delayed > 15 Minutes"
    assert final_output_df.loc[0, "fine"] == 150
    assert output_df.columns.tolist() == CAB_DELAY_OUTPUT_COLUMNS
    assert output_df.loc[0, "Booking ID"] == "B1"
    assert_complaint_metadata(output_df.loc[0], "dispatch-b1")
    assert output_df.loc[0, "Loss Amount"] == 150
    assert output_df.loc[0, "Recoverable"] == 150
    assert output_df.loc[0, "Sub Category"] == "Cab Delay"
    assert output_df.loc[0, "amount"] == 1200
    assert output_df.loc[0, "base_amount"] == 1000
    assert output_df.loc[0, "amount_paid"] == 200
    assert output_df.loc[0, "cash_collected"] == 1000
    assert output_df.loc[0, "extra_travelled_fare"] == 40
    assert output_df.loc[0, "total_driver_charge"] == 150
    assert output_df.loc[0, VENDOR_NAME_COLUMN] == "savaari"
    assert "preferred start time of customer (UTC)" not in output_df.columns
    assert output_df.loc[0, PREFERRED_START_TIME_IST_COLUMN] == "19 Mar 2026 10:00 AM"
    assert output_df.loc[0, DRIVER_STARTED_COLUMN] == "19 Mar 2026 10:20 AM"
    assert output_df.loc[0, DRIVER_ARRIVED_COLUMN] == "19 Mar 2026 10:40 AM"
    assert output_df.loc[0, BOARDED_COLUMN] == "19 Mar 2026 10:45 AM"
    assert output_df.loc[0, INCABS_INSIGHT_COLUMN] == "Mock Incabs insight."
    assert output_df.loc[0, COMMENTS_COLUMN] == (
        "Customer reported that the cab had not arrived and the driver said they needed 20 minutes."
    )
    assert output_df.loc[0, INCABS_COMMENT_SUMMARY_COLUMN] == "Mock combined summary."
    assert output_df.loc[0, MESSAGE_COLUMN] == "Cab Delayed > 15 Minutes"
    assert result.category_outputs[0]["name"] == "Cab Delay"
    assert result.category_outputs[0]["row_count"] == 1
    assert "preview_rows" not in result.category_outputs[0]
    assert "package_prepared" in completed_steps
    assert warnings == []
    assert started_steps[0] == "workbook_parsed"

    with zipfile.ZipFile(package_path) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "final_output.xlsx",
            "agent_audit.xlsx",
            "review_queue.xlsx",
            "agent_summary.json",
            "category_files/prepared/cab-delay.xlsx",
            "category_files/processed/cab-delay.xlsx",
        }


def test_process_uploaded_workbook_reports_category_progress(tmp_path: Path) -> None:
    workbook_path = tmp_path / "qliksense.xlsx"
    tracking_path = tmp_path / "tracking.json"
    package_path = tmp_path / "agentic_loss_recovery_package.zip"
    write_two_category_workbook(workbook_path)
    write_tracking_json(tracking_path)

    initialized_categories: list[list[dict[str, object]]] = []
    category_updates: list[tuple[str, dict[str, object]]] = []
    step_updates: list[tuple[str, int, int, str]] = []

    result = process_uploaded_workbook(
        input_path=workbook_path,
        tracking_json_path=tracking_path,
        output_package_path=package_path,
        approval_date="2026-03-19",
        on_step_start=lambda _step_id, _message: None,
        on_step_complete=lambda _step_id, _message: None,
        on_warning=lambda _warning: None,
        on_step_progress=lambda step_id, completed, total, message: step_updates.append(
            (step_id, completed, total, message)
        ),
        on_category_progress_initialized=lambda categories: initialized_categories.append(categories),
        on_category_progress=lambda slug, update: category_updates.append((slug, update)),
        reason_generator=mock_llm,
    )

    assert result.metrics["category_count"] == 2
    assert [category["slug"] for category in initialized_categories[0]] == ["cab-delay", "extra-money-taken"]
    assert step_updates[-1] == ("categories_processed", 2, 2, "2 of 2 categories processed")
    assert ("cab-delay", {"status": "completed", "message": "Processed 1 rows"}) in category_updates
    assert any(slug == "cab-delay" and "cab_delay" in update for slug, update in category_updates)


def test_category_processor_failure_writes_fallback_file_and_package(tmp_path: Path, monkeypatch) -> None:
    workbook_path = tmp_path / "qliksense.xlsx"
    tracking_path = tmp_path / "tracking.json"
    package_path = tmp_path / "agentic_loss_recovery_package.zip"
    write_two_category_workbook(workbook_path)
    write_tracking_json(tracking_path)
    original_processor = pipeline.process_category_batch_async

    async def failing_extra_money_processor(*args, **kwargs):
        batch = args[0]
        if batch.name == "Extra Money Taken":
            raise RuntimeError("processor boom")
        return await original_processor(*args, **kwargs)

    monkeypatch.setattr(pipeline, "process_category_batch_async", failing_extra_money_processor)
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
    assert package_path.exists()
    assert extra_money_output.exists()
    assert_complaint_metadata(output_df.loc[0], "")
    failed_category = next(category for category in result.category_outputs if category["slug"] == "extra-money-taken")
    assert failed_category["status"] == "failed"
    assert failed_category["error"] == "processor boom"
    assert warnings[0]["code"] == "tracking_not_found"
    assert any(warning["code"] == "category_processing_failed" for warning in warnings)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["final_output"]["filename"] == "final_output.xlsx"
    assert manifest["final_output"]["row_count"] == 2
    final_output_df = pd.read_excel(result.final_output_path, keep_default_na=False)
    assert final_output_df.columns.tolist() == pipeline.FINAL_EXPORT_COLUMNS
    assert final_output_df["booking_id"].tolist() == ["B1", "B5"]
    assert final_output_df["complaint_reasons"].tolist() == ["Cab Delay", "Extra Money Taken"]
    manifest_category = next(category for category in manifest["categories"] if category["slug"] == "extra-money-taken")
    assert manifest_category["status"] == "failed"
    assert manifest_category["error"] == "processor boom"


def test_demo_workbook_creates_one_processed_xlsx_per_subcategory(tmp_path: Path) -> None:
    package_path = tmp_path / "agentic_loss_recovery_package.zip"

    result = process_uploaded_workbook(
        input_path=DEMO_WORKBOOK_PATH,
        tracking_json_path=DEMO_TRACKING_JSON_PATH,
        output_package_path=package_path,
        approval_date="2026-03-19",
        on_step_start=lambda _step_id, _message: None,
        on_step_complete=lambda _step_id, _message: None,
        on_warning=lambda _warning: None,
        reason_generator=mock_llm,
    )

    category_names = {category["name"] for category in result.category_outputs}
    assert category_names == {
        "AC not working",
        "Cab Delay",
        "Details Change",
        "Driver Behavior",
        "Extra Money Taken",
        "FULFILLMENT NOT DONE",
        "Lower Category Vehicle",
        "Poor Vehicle Condition",
        "Vehicle Breakdown",
    }
    assert result.metrics["prepared_rows"] == 71
    assert result.metrics["category_count"] == 9
    assert result.metrics["final_output_rows"] == 71
    assert result.final_output["row_count"] == 71
    assert all(VENDOR_NAME_COLUMN in category["output_columns"] for category in result.category_outputs)
    assert package_path.exists()
    final_output_df = pd.read_excel(result.final_output_path, keep_default_na=False)
    assert final_output_df.columns.tolist() == pipeline.FINAL_EXPORT_COLUMNS
    assert len(final_output_df) == 71

    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "final_output.xlsx" in names
        assert sum(name.startswith("category_files/prepared/") for name in names) == 9
        assert sum(name.startswith("category_files/processed/") for name in names) == 9


def test_process_uploaded_workbook_keeps_package_when_comment_summary_fails(tmp_path: Path) -> None:
    workbook_path = tmp_path / "qliksense.xlsx"
    tracking_path = tmp_path / "tracking.json"
    package_path = tmp_path / "agentic_loss_recovery_package.zip"
    write_sample_workbook(workbook_path)
    write_tracking_json(tracking_path)

    warnings: list[dict[str, object]] = []

    def failing_summary_llm(prompt: str, _tokens: int, _effort: str) -> str:
        if "Customer call comment:" in prompt:
            raise RuntimeError("summary failed")
        return "Mock Incabs insight."

    result = process_uploaded_workbook(
        input_path=workbook_path,
        tracking_json_path=tracking_path,
        output_package_path=package_path,
        approval_date="2026-03-19",
        on_step_start=lambda _step_id, _message: None,
        on_step_complete=lambda _step_id, _message: None,
        on_warning=warnings.append,
        reason_generator=failing_summary_llm,
    )

    output_df = pd.read_excel(tmp_path / "category_files" / "processed" / "cab-delay.xlsx", keep_default_na=False)
    assert package_path.exists()
    assert result.metrics["generated_insight_rows"] == 1
    assert result.metrics["failed_comment_summary_rows"] == 1
    assert output_df.loc[0, INCABS_INSIGHT_COLUMN] == "Mock Incabs insight."
    assert output_df.loc[0, INCABS_COMMENT_SUMMARY_COLUMN] == ""
    assert warnings == [
        {
            "code": "azure_comment_summary_failed",
            "message": "1 Incabs/comment summaries could not be generated. Processed category files were still produced.",
            "booking_ids": ["B1"],
        }
    ]


def test_process_uploaded_workbook_reports_missing_columns(tmp_path: Path) -> None:
    workbook_path = tmp_path / "bad.xlsx"
    tracking_path = tmp_path / "tracking.json"
    pd.DataFrame([{"Booking ID": "B1"}]).to_excel(workbook_path, index=False)
    write_tracking_json(tracking_path)

    with pytest.raises(ValueError, match="missing required columns"):
        process_uploaded_workbook(
            input_path=workbook_path,
            tracking_json_path=tracking_path,
            output_package_path=tmp_path / "agentic_loss_recovery_package.zip",
            approval_date="2026-03-19",
            on_step_start=lambda _step_id, _message: None,
            on_step_complete=lambda _step_id, _message: None,
            on_warning=lambda _warning: None,
            reason_generator=lambda _prompt, _tokens, _effort: "unused",
        )
