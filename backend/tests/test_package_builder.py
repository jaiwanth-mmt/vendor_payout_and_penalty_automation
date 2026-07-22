from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from backend.app.services.package_builder import (
    AGENT_AUDIT_COLUMNS,
    FINAL_EXPORT_COLUMNS,
    REVIEW_QUEUE_COLUMNS,
    build_agent_audit_dataframe,
    build_category_output_payload,
    build_final_output_dataframe,
    build_final_output_summary,
    build_manifest,
    build_review_queue_dataframe,
    write_category_outputs_zip,
    write_package_zip,
    write_workbook,
)


def test_build_final_output_dataframe_uses_contract_columns() -> None:
    processed_df = pd.DataFrame(
        [
            {
                "Booking ID": "B1",
                "Sub Category": "Cab Delay",
                "complaint_against": "dispatch_id",
                "complaint_against_id": "dispatch-b1",
                "title": "Service Issue",
                "message": "Cab Delay",
                "Recoverable": 150,
            }
        ]
    )

    final_df = build_final_output_dataframe([processed_df])

    assert final_df.columns.tolist() == FINAL_EXPORT_COLUMNS
    assert final_df.to_dict(orient="records") == [
        {
            "booking_id": "B1",
            "complaint_reasons": "Cab Delay",
            "complaint_against": "dispatch_id",
            "complaint_against_id": "dispatch-b1",
            "title": "Service Issue",
            "message": "Cab Delay",
            "fine": 150,
        }
    ]


def test_agent_audit_dataframe_keeps_headers_when_empty() -> None:
    audit_df = build_agent_audit_dataframe([])

    assert audit_df.columns.tolist() == AGENT_AUDIT_COLUMNS
    assert audit_df.empty


def test_review_queue_dataframe_keeps_headers_when_all_cases_auto_ready() -> None:
    review_queue_df = build_review_queue_dataframe(
        [
            {
                "booking_id": "B1",
                "sub_category": "Cab Delay",
                "recoverable_amount": 100,
                "review_status": "auto_ready",
                "final_decision": {
                    "decision": "valid_penalty",
                    "decision_source": "llm",
                    "confidence": 0.91,
                    "recommended_action": "Ready for Cab Ops recovery package",
                    "review_reason": "Evidence is sufficient.",
                    "rationale": "Supported by cited timing evidence.",
                    "evidence_ids": ["B1:timing"],
                },
            }
        ]
    )

    assert review_queue_df.columns.tolist() == REVIEW_QUEUE_COLUMNS
    assert review_queue_df.empty


def test_build_manifest_omits_preview_rows() -> None:
    final_output = {
        "filename": "final_output.xlsx",
        "row_count": 1,
        "columns": FINAL_EXPORT_COLUMNS,
        "download_ready": True,
    }
    categories = [
        {
            "name": "Cab Delay",
            "slug": "cab-delay",
            "row_count": 1,
            "output_columns": ["Booking ID", "message"],
            "prepared_filename": "category_files/prepared/cab-delay.xlsx",
            "processed_filename": "category_files/processed/cab-delay.xlsx",
            "status": "completed",
            "error": None,
        }
    ]

    manifest = build_manifest(
        start_date="2026-03-19",
        end_date="2026-03-19",
        raw_rows=5,
        prepared_rows=1,
        categories=categories,
        final_output=final_output,
    )

    assert manifest["start_date"] == "2026-03-19"
    assert manifest["end_date"] == "2026-03-19"
    assert manifest["raw_rows"] == 5
    assert manifest["prepared_rows"] == 1
    assert manifest["final_output"] == final_output
    assert manifest["categories"] == [
        {
            "name": "Cab Delay",
            "slug": "cab-delay",
            "row_count": 1,
            "output_columns": ["Booking ID", "message"],
            "prepared_filename": "category_files/prepared/cab-delay.xlsx",
            "processed_filename": "category_files/processed/cab-delay.xlsx",
            "status": "completed",
            "error": None,
        }
    ]


def test_write_package_zip_keeps_expected_archive_names(tmp_path: Path) -> None:
    prepared_path = tmp_path / "category_files" / "prepared" / "cab-delay.xlsx"
    processed_path = tmp_path / "category_files" / "processed" / "cab-delay.xlsx"
    manifest_path = tmp_path / "manifest.json"
    final_output_path = tmp_path / "final_output.xlsx"
    package_path = tmp_path / "agentic_loss_recovery_package.zip"
    write_workbook(pd.DataFrame([{"Booking ID": "B1"}]), prepared_path)
    write_workbook(pd.DataFrame([{"Booking ID": "B1", "message": "Cab Delay"}]), processed_path)
    write_workbook(pd.DataFrame([{"complaint_reasons": "Cab Delay"}]), final_output_path)
    manifest_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    write_package_zip(
        output_package_path=package_path,
        manifest_path=manifest_path,
        categories=[
            {
                "prepared_filename": "category_files/prepared/cab-delay.xlsx",
                "processed_filename": "category_files/processed/cab-delay.xlsx",
            }
        ],
        final_output_path=final_output_path,
        root_dir=tmp_path,
    )

    with zipfile.ZipFile(package_path) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "final_output.xlsx",
            "category_files/prepared/cab-delay.xlsx",
            "category_files/processed/cab-delay.xlsx",
        }


def test_write_category_outputs_zip_includes_prepared_and_processed(tmp_path: Path) -> None:
    prepared_path = tmp_path / "category_files" / "prepared" / "cab-delay.xlsx"
    processed_path = tmp_path / "category_files" / "processed" / "cab-delay.xlsx"
    zip_path = tmp_path / "category_outputs.zip"
    write_workbook(pd.DataFrame([{"Booking ID": "B1"}]), prepared_path)
    write_workbook(pd.DataFrame([{"Booking ID": "B1", "message": "Cab Delay"}]), processed_path)

    written = write_category_outputs_zip(
        output_zip_path=zip_path,
        categories=[
            {
                "prepared_filename": "category_files/prepared/cab-delay.xlsx",
                "processed_filename": "category_files/processed/cab-delay.xlsx",
            }
        ],
        root_dir=tmp_path,
    )

    assert written == 2
    with zipfile.ZipFile(zip_path) as archive:
        assert set(archive.namelist()) == {
            "category_files/prepared/cab-delay.xlsx",
            "category_files/processed/cab-delay.xlsx",
        }


def test_category_payload_and_final_summary_are_json_friendly(tmp_path: Path) -> None:
    processed_df = pd.DataFrame(
        [
            {
                "Booking ID": "B1",
                "Booking Date": pd.Timestamp("2026-03-19"),
                "updated_at": datetime(2026, 3, 19, 10, 15),
            }
        ]
    )
    prepared_path = tmp_path / "category_files" / "prepared" / "cab-delay.xlsx"
    processed_path = tmp_path / "category_files" / "processed" / "cab-delay.xlsx"
    write_workbook(processed_df, prepared_path)
    write_workbook(processed_df, processed_path)

    payload = build_category_output_payload(
        name="Cab Delay",
        slug="cab-delay",
        prepared_path=prepared_path,
        processed_path=processed_path,
        processed_df=processed_df,
        root_dir=tmp_path,
    )
    final_summary = build_final_output_summary(
        final_output_path=processed_path,
        final_output_df=processed_df,
        root_dir=tmp_path,
    )

    assert payload["prepared_filename"] == "category_files/prepared/cab-delay.xlsx"
    assert payload["processed_filename"] == "category_files/processed/cab-delay.xlsx"
    assert "preview_rows" not in payload
    assert final_summary["filename"] == "category_files/processed/cab-delay.xlsx"
    assert final_summary["download_ready"] is True
