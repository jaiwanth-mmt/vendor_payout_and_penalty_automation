from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.domain.cab_delay_enrichment import INCABS_COMMENT_SUMMARY_COLUMN, INCABS_INSIGHT_COLUMN
from backend.app.domain.complaint_message import MESSAGE_COLUMN
from backend.app.domain.tracking_common import (
    COMPLAINT_AGAINST_COLUMN,
    COMPLAINT_AGAINST_ID_COLUMN,
    COMPLAINT_AGAINST_VALUE,
    TITLE_COLUMN,
    TITLE_VALUE,
)
from backend.app.services.pipeline import FINAL_EXPORT_COLUMNS


def write_sample_workbook(path: Path) -> None:
    pd.DataFrame(
        [
            {
                "Booking ID": "B1",
                "Booking Date": "2026-03-19",
                "Booking Month": "Mar 2026",
                "Loss Dept": "CARBD",
                "Sub Category": "Cab Delay",
                "Loss Amount": 100,
                "Loss Amount (INR)": 100,
                "Recoverable": 100,
                "Recoverable (INR)": 100,
                "Remarks": "Cab Delay",
                "Approval/Rejected DateTime": "2026-03-19 10:15:00",
            }
        ]
    ).to_excel(path, index=False)


def write_tracking_json(path: Path) -> None:
    payload = {
        "bookings": {
            "B1": {
                "tracking_reports_raw": [
                    {
                        "dispatch_id": "dispatch-b1",
                        "order_reference_number": "B1",
                        "start_time": "2026-03-19 04:30:00",
                        "driver_started": "2026-03-19 10:20:00",
                        "driver_arrived": "2026-03-19 10:40:00",
                        "boarded": "2026-03-19 10:45:00",
                    }
                ],
                "comments": "Customer said the cab was delayed and the driver needed more time.",
            }
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_create_job_poll_and_download_package(tmp_path: Path, monkeypatch) -> None:
    workbook_path = tmp_path / "qliksense.xlsx"
    tracking_path = tmp_path / "tracking.json"
    runtime_dir = tmp_path / "jobs"
    write_sample_workbook(workbook_path)
    write_tracking_json(tracking_path)

    monkeypatch.setattr(main, "TRACKING_JSON_PATH", tracking_path)
    monkeypatch.setattr(main, "RUNTIME_DIR", runtime_dir)

    async def mock_azure(prompt: str, _tokens: int, _effort: str) -> str:
        if "Complaint category classification task." in prompt:
            return '{"categories": ["Cab Delay"]}'
        if "Customer call comment:" in prompt:
            return "API mock combined summary."
        return "API mock Incabs insight."

    monkeypatch.setattr("backend.app.services.pipeline.call_azure_openai_async", mock_azure)

    with TestClient(main.app) as client:
        with workbook_path.open("rb") as file_handle:
            response = client.post(
                "/api/jobs",
                data={"approval_date": "2026-03-19"},
                files={
                    "file": (
                        "qliksense.xlsx",
                        file_handle,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        assert response.status_code == 200
        job_id = response.json()["job_id"]

        status_response = client.get(f"/api/jobs/{job_id}")
        assert status_response.status_code == 200
        payload = status_response.json()
        assert payload["status"] == "succeeded"
        assert payload["metrics"]["prepared_rows"] == 1
        assert payload["metrics"]["category_count"] == 1
        assert payload["metrics"]["final_output_rows"] == 1
        assert payload["final_output"] == {
            "filename": "final_output.xlsx",
            "row_count": 1,
            "columns": FINAL_EXPORT_COLUMNS,
            "download_ready": True,
        }
        category_step = next(step for step in payload["steps"] if step["id"] == "categories_processed")
        assert category_step["completed_units"] == 1
        assert category_step["total_units"] == 1
        assert payload["category_progress"][0]["name"] == "Cab Delay"
        assert payload["category_progress"][0]["status"] == "completed"
        assert payload["category_progress"][0]["cab_delay"]["generated_insight_rows"] == 1
        assert payload["category_progress"][0]["cab_delay"]["generated_comment_summary_rows"] == 1
        assert payload["category_outputs"][0]["name"] == "Cab Delay"
        assert payload["category_outputs"][0]["preview_rows"][0][COMPLAINT_AGAINST_COLUMN] == COMPLAINT_AGAINST_VALUE
        assert payload["category_outputs"][0]["preview_rows"][0][COMPLAINT_AGAINST_ID_COLUMN] == "dispatch-b1"
        assert payload["category_outputs"][0]["preview_rows"][0][TITLE_COLUMN] == TITLE_VALUE
        assert payload["category_outputs"][0]["preview_rows"][0][INCABS_INSIGHT_COLUMN] == "API mock Incabs insight."
        assert (
            payload["category_outputs"][0]["preview_rows"][0][INCABS_COMMENT_SUMMARY_COLUMN]
            == "API mock combined summary."
        )
        assert payload["category_outputs"][0]["preview_rows"][0][MESSAGE_COLUMN] == "Cab Delay"

        preview_response = client.get(f"/api/jobs/{job_id}/final-output/preview", params={"page": 1, "page_size": 1})
        assert preview_response.status_code == 200
        preview_payload = preview_response.json()
        assert preview_payload["columns"] == FINAL_EXPORT_COLUMNS
        assert preview_payload["row_count"] == 1
        assert preview_payload["page"] == 1
        assert preview_payload["page_size"] == 1
        assert preview_payload["total_pages"] == 1
        assert preview_payload["rows"] == [
            {
                "complaint_reasons": "Cab Delay",
                "complaint_against": COMPLAINT_AGAINST_VALUE,
                "complaint_against_id": "dispatch-b1",
                "title": TITLE_VALUE,
                "message": "Cab Delay",
                "fine": 100,
            }
        ]

        final_download_response = client.get(f"/api/jobs/{job_id}/final-output/download")
        assert final_download_response.status_code == 200
        assert final_download_response.headers["content-type"] == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        final_output_df = pd.read_excel(io.BytesIO(final_download_response.content), keep_default_na=False)
        assert final_output_df.columns.tolist() == FINAL_EXPORT_COLUMNS
        assert final_output_df.loc[0, "fine"] == 100

        download_response = client.get(f"/api/jobs/{job_id}/download")
        assert download_response.status_code == 200
        assert download_response.headers["content-type"] == "application/zip"

        with zipfile.ZipFile(io.BytesIO(download_response.content)) as archive:
            assert set(archive.namelist()) == {
                "manifest.json",
                "final_output.xlsx",
                "category_files/prepared/cab-delay.xlsx",
                "category_files/processed/cab-delay.xlsx",
            }
