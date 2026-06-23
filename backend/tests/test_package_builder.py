from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from backend.app.services.package_builder import (
    FINAL_EXPORT_COLUMNS,
    build_category_output_payload,
    build_final_output_dataframe,
    build_final_output_summary,
    build_manifest,
    dataframe_preview,
    write_package_zip,
    write_workbook,
)


def test_build_final_output_dataframe_uses_contract_columns() -> None:
    processed_df = pd.DataFrame(
        [
            {
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
            "complaint_reasons": "Cab Delay",
            "complaint_against": "dispatch_id",
            "complaint_against_id": "dispatch-b1",
            "title": "Service Issue",
            "message": "Cab Delay",
            "fine": 150,
        }
    ]


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
            "preview_rows": [{"Booking ID": "B1"}],
            "status": "completed",
            "error": None,
        }
    ]

    manifest = build_manifest(
        approval_date="2026-03-19",
        raw_rows=5,
        prepared_rows=1,
        categories=categories,
        final_output=final_output,
    )

    assert manifest["approval_date"] == "2026-03-19"
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
    package_path = tmp_path / "penalty_automation_package.zip"
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


def test_payload_and_preview_values_are_json_friendly(tmp_path: Path) -> None:
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
        preview_limit=1,
    )
    final_summary = build_final_output_summary(
        final_output_path=processed_path,
        final_output_df=processed_df,
        root_dir=tmp_path,
    )

    assert payload["prepared_filename"] == "category_files/prepared/cab-delay.xlsx"
    assert payload["processed_filename"] == "category_files/processed/cab-delay.xlsx"
    assert payload["preview_rows"] == [
        {"Booking ID": "B1", "Booking Date": "2026-03-19", "updated_at": "2026-03-19"}
    ]
    assert dataframe_preview(processed_df, limit=1) == payload["preview_rows"]
    assert final_summary["filename"] == "category_files/processed/cab-delay.xlsx"
    assert final_summary["download_ready"] is True
