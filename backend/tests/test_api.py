from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from uuid import uuid4

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
    VENDOR_NAME_COLUMN,
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
                        "vendor_name": "savaari",
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

    monkeypatch.setattr(main, "RUNTIME_DIR", runtime_dir)

    from backend.app.integrations.tracking import InMemoryTrackingRepository

    monkeypatch.setattr(
        "backend.app.main.live_tracking_repository_from_env",
        lambda: InMemoryTrackingRepository(json_path=tracking_path),
    )

    async def mock_azure(prompt: str, _tokens: int, _effort: str) -> str:
        if "Agent specialist decision task." in prompt or "Judge Agent verification task." in prompt:
            evidence_ids = list(dict.fromkeys(re.findall(r'"id":\s*"([^"]+)"', prompt)))[:3]
            amount_match = re.search(r'"recoverable_amount":\s*([0-9.]+)', prompt)
            amount = float(amount_match.group(1)) if amount_match else 100
            return json.dumps(
                {
                    "decision": "valid_penalty",
                    "complaint_categories": ["Cab Delay"],
                    "confidence": 0.91,
                    "recommended_recovery_amount": amount,
                    "rationale": "API mock LLM approved Cab Delay based on selected source text.",
                    "recommended_action": "Ready for Cab Ops recovery package",
                    "review_status": "auto_ready",
                    "review_reason": "API mock LLM judge approved the selected source.",
                    "evidence_ids": evidence_ids,
                }
            )
        if "Portfolio Summary Agent task." in prompt:
            return json.dumps(
                {
                    "executive_summary": "API mock portfolio summary.",
                    "top_complaint_drivers": ["Cab Delay: 1 case"],
                    "recommended_actions": ["Proceed with reviewed recovery package."],
                    "missing_data_hotspots": [],
                    "category_breakdown": [],
                }
            )
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
                data={"start_date": "2026-03-19", "end_date": "2026-03-19"},
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
        assert payload["case_counts"]["total_cases"] == 1
        assert payload["agent_summary"]["case_counts"]["total_cases"] == 1
        assert payload["agent_summary"]["high_confidence_case_count"] == 1
        assert payload["metrics"]["agent_high_confidence_cases"] == 1
        assert payload["agent_summary"]["top_vendors_by_penalty"] == [
            {
                "vendor_name": "savaari",
                "case_count": 1,
                "total_recoverable": 100.0,
                "top_subcategories": [
                    {"subcategory": "Cab Delay", "case_count": 1, "total_recoverable": 100.0},
                ],
            }
        ]
        assert payload["agent_summary"]["top_subcategories_by_penalty"] == [
            {"subcategory": "Cab Delay", "case_count": 1, "total_recoverable": 100.0},
        ]
        assert payload["agent_summary"]["top_subcategories_by_count"] == [
            {"subcategory": "Cab Delay", "case_count": 1, "total_recoverable": 100.0},
        ]
        assert payload["agent_progress"][-1]["agent"] == "Vendor Penalty Analysis Agent"
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
        assert "preview_rows" not in payload["category_outputs"][0]

        category_preview_response = client.get(f"/api/jobs/{job_id}/categories/cab-delay/preview")
        assert category_preview_response.status_code == 200
        category_preview_payload = category_preview_response.json()
        assert category_preview_payload["row_count"] == 1
        assert category_preview_payload["page"] == 1
        assert category_preview_payload["page_size"] == 5
        assert category_preview_payload["total_pages"] == 1
        assert category_preview_payload["rows"][0][COMPLAINT_AGAINST_COLUMN] == COMPLAINT_AGAINST_VALUE
        assert category_preview_payload["rows"][0][COMPLAINT_AGAINST_ID_COLUMN] == "dispatch-b1"
        assert category_preview_payload["rows"][0][TITLE_COLUMN] == TITLE_VALUE
        assert category_preview_payload["rows"][0][VENDOR_NAME_COLUMN] == "savaari"
        assert category_preview_payload["rows"][0][INCABS_INSIGHT_COLUMN] == "API mock Incabs insight."
        assert category_preview_payload["rows"][0][INCABS_COMMENT_SUMMARY_COLUMN] == "API mock combined summary."
        assert category_preview_payload["rows"][0][MESSAGE_COLUMN] == "Cab Delay"

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
                "booking_id": "B1",
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
        assert final_output_df.loc[0, "booking_id"] == "B1"
        assert final_output_df.loc[0, "fine"] == 100

        cases_response = client.get(f"/api/jobs/{job_id}/cases")
        assert cases_response.status_code == 200
        cases_payload = cases_response.json()
        assert cases_payload["case_count"] == 1
        assert cases_payload["page"] == 1
        assert cases_payload["page_size"] == 5
        assert cases_payload["total_pages"] == 1
        assert cases_payload["cases"][0]["booking_id"] == "B1"
        assert cases_payload["cases"][0]["final_decision"]["agent"] == "Judge Agent"

        review_queue_page_response = client.get(f"/api/jobs/{job_id}/review-queue")
        assert review_queue_page_response.status_code == 200
        review_queue_page_payload = review_queue_page_response.json()
        assert review_queue_page_payload == {
            "items": [],
            "item_count": 0,
            "page": 1,
            "page_size": 5,
            "total_pages": 1,
        }

        case_response = client.get(f"/api/jobs/{job_id}/cases/B1")
        assert case_response.status_code == 200
        assert case_response.json()["booking_id"] == "B1"

        agent_audit_response = client.get(f"/api/jobs/{job_id}/agent-audit/download")
        assert agent_audit_response.status_code == 200
        audit_df = pd.read_excel(io.BytesIO(agent_audit_response.content), keep_default_na=False)
        assert audit_df.loc[0, "booking_id"] == "B1"

        review_queue_response = client.get(f"/api/jobs/{job_id}/review-queue/download")
        assert review_queue_response.status_code == 200

        category_download_response = client.get(f"/api/jobs/{job_id}/categories/download")
        assert category_download_response.status_code == 200
        assert category_download_response.headers["content-type"] == "application/zip"
        assert (
            'filename="category_outputs_2026-03-19_to_2026-03-19.zip"'
            in category_download_response.headers["content-disposition"]
        )
        with zipfile.ZipFile(io.BytesIO(category_download_response.content)) as archive:
            assert set(archive.namelist()) == {
                "category_files/prepared/cab-delay.xlsx",
                "category_files/processed/cab-delay.xlsx",
            }

        download_response = client.get(f"/api/jobs/{job_id}/download")
        assert download_response.status_code == 200
        assert download_response.headers["content-type"] == "application/zip"
        assert 'filename="agentic_loss_recovery_2026-03-19_to_2026-03-19.zip"' in download_response.headers["content-disposition"]

        with zipfile.ZipFile(io.BytesIO(download_response.content)) as archive:
            assert set(archive.namelist()) == {
                "manifest.json",
                "final_output.xlsx",
                "agent_audit.xlsx",
                "review_queue.xlsx",
                "agent_summary.json",
                "category_files/prepared/cab-delay.xlsx",
                "category_files/processed/cab-delay.xlsx",
            }


def test_paged_category_cases_and_review_queue_endpoints(tmp_path: Path) -> None:
    job_id = uuid4().hex
    job_dir = tmp_path / job_id
    processed_path = job_dir / "category_files" / "processed" / "cab-delay.xlsx"
    prepared_path = job_dir / "category_files" / "prepared" / "cab-delay.xlsx"
    upload_path = job_dir / "input.xlsx"
    package_path = job_dir / "agentic_loss_recovery_package.zip"
    final_output_path = job_dir / "final_output.xlsx"
    agent_audit_path = job_dir / "agent_audit.xlsx"
    review_queue_path = job_dir / "review_queue.xlsx"
    agent_summary_path = job_dir / "agent_summary.json"
    rows = [
        {
            "Booking ID": f"B{index}",
            "Sub Category": "Cab Delay",
            "Recoverable": index * 10,
            MESSAGE_COLUMN: "Cab Delay",
        }
        for index in range(1, 13)
    ]
    cases = [
        {
            "booking_id": f"B{index}",
            "sub_category": "Cab Delay",
            "recoverable_amount": index * 10,
            "review_status": "needs_review",
            "final_decision": {
                "agent": "Judge Agent",
                "decision": "needs_review",
                "confidence": 0.5,
                "recommended_action": "Review manually",
                "review_reason": f"Needs review {index}",
            },
        }
        for index in range(1, 13)
    ]

    processed_path.parent.mkdir(parents=True)
    prepared_path.parent.mkdir(parents=True)
    pd.DataFrame(rows).to_excel(processed_path, index=False)
    pd.DataFrame(rows).to_excel(prepared_path, index=False)
    final_output_rows = [
        {
            "booking_id": row["Booking ID"],
            "complaint_reasons": row["Sub Category"],
            "complaint_against": "dispatch_id",
            "complaint_against_id": f"dispatch-{row['Booking ID'].lower()}",
            "title": "Service Issue",
            "message": row[MESSAGE_COLUMN],
            "fine": row["Recoverable"],
        }
        for row in rows
    ]
    pd.DataFrame(final_output_rows, columns=FINAL_EXPORT_COLUMNS).to_excel(final_output_path, index=False)
    pd.DataFrame(cases).to_excel(agent_audit_path, index=False)
    pd.DataFrame(cases).to_excel(review_queue_path, index=False)
    upload_path.write_bytes(b"input")
    package_path.write_bytes(b"zip")
    agent_summary_path.write_text("{}", encoding="utf-8")

    main.job_store.create_job(
        job_id=job_id,
        original_filename="input.xlsx",
        start_date="2026-03-19",
        end_date="2026-03-19",
        job_dir=job_dir,
        upload_path=upload_path,
    )
    main.job_store.complete_job(
        job_id,
        metrics={},
        category_outputs=[
            {
                "name": "Cab Delay",
                "slug": "cab-delay",
                "row_count": len(rows),
                "output_columns": list(rows[0].keys()),
                "prepared_filename": "category_files/prepared/cab-delay.xlsx",
                "processed_filename": "category_files/processed/cab-delay.xlsx",
                "status": "completed",
                "error": None,
            }
        ],
        package_path=package_path,
        final_output_path=final_output_path,
        final_output={
            "filename": "final_output.xlsx",
            "row_count": len(rows),
            "columns": FINAL_EXPORT_COLUMNS,
            "download_ready": True,
        },
        agent_audit_path=agent_audit_path,
        review_queue_path=review_queue_path,
        agent_summary_path=agent_summary_path,
        agent_summary={},
        case_counts={"total_cases": len(cases)},
        agent_progress=[],
        agent_cases=cases,
    )

    not_ready_job_id = uuid4().hex
    not_ready_dir = tmp_path / not_ready_job_id
    not_ready_dir.mkdir()
    not_ready_upload_path = not_ready_dir / "input.xlsx"
    not_ready_upload_path.write_bytes(b"input")
    main.job_store.create_job(
        job_id=not_ready_job_id,
        original_filename="input.xlsx",
        start_date="2026-03-19",
        end_date="2026-03-19",
        job_dir=not_ready_dir,
        upload_path=not_ready_upload_path,
    )

    with TestClient(main.app) as client:
        category_page = client.get(f"/api/jobs/{job_id}/categories/cab-delay/preview", params={"page": 2})
        assert category_page.status_code == 200
        category_payload = category_page.json()
        assert category_payload["row_count"] == 12
        assert category_payload["page"] == 2
        assert category_payload["page_size"] == 5
        assert category_payload["total_pages"] == 3
        assert [row["Booking ID"] for row in category_payload["rows"]] == ["B6", "B7", "B8", "B9", "B10"]

        category_search = client.get(
            f"/api/jobs/{job_id}/categories/cab-delay/preview",
            params={"booking_id": " B10 ", "page": 2},
        )
        assert category_search.status_code == 200
        category_search_payload = category_search.json()
        assert category_search_payload["row_count"] == 1
        assert category_search_payload["page"] == 1
        assert category_search_payload["total_pages"] == 1
        assert [row["Booking ID"] for row in category_search_payload["rows"]] == ["B10"]

        category_search_missing = client.get(
            f"/api/jobs/{job_id}/categories/cab-delay/preview",
            params={"booking_id": "missing"},
        )
        assert category_search_missing.status_code == 200
        assert category_search_missing.json()["row_count"] == 0
        assert category_search_missing.json()["page"] == 1
        assert category_search_missing.json()["total_pages"] == 1
        assert category_search_missing.json()["rows"] == []

        category_last_page = client.get(f"/api/jobs/{job_id}/categories/cab-delay/preview", params={"page": 99})
        assert category_last_page.status_code == 200
        assert category_last_page.json()["page"] == 3
        assert [row["Booking ID"] for row in category_last_page.json()["rows"]] == ["B11", "B12"]

        final_output_search = client.get(
            f"/api/jobs/{job_id}/final-output/preview",
            params={"booking_id": "B10", "page": 2, "page_size": 5},
        )
        assert final_output_search.status_code == 200
        final_output_search_payload = final_output_search.json()
        assert final_output_search_payload["columns"] == FINAL_EXPORT_COLUMNS
        assert final_output_search_payload["row_count"] == 1
        assert final_output_search_payload["page"] == 1
        assert final_output_search_payload["total_pages"] == 1
        assert [row["booking_id"] for row in final_output_search_payload["rows"]] == ["B10"]

        final_output_search_missing = client.get(
            f"/api/jobs/{job_id}/final-output/preview",
            params={"booking_id": "missing"},
        )
        assert final_output_search_missing.status_code == 200
        assert final_output_search_missing.json()["row_count"] == 0
        assert final_output_search_missing.json()["page"] == 1
        assert final_output_search_missing.json()["total_pages"] == 1
        assert final_output_search_missing.json()["rows"] == []

        invalid_category = client.get(f"/api/jobs/{job_id}/categories/missing/preview")
        assert invalid_category.status_code == 404

        not_ready_category = client.get(f"/api/jobs/{not_ready_job_id}/categories/cab-delay/preview")
        assert not_ready_category.status_code == 409

        cases_page = client.get(f"/api/jobs/{job_id}/cases", params={"page": 2})
        assert cases_page.status_code == 200
        cases_payload = cases_page.json()
        assert cases_payload["case_count"] == 12
        assert cases_payload["page"] == 2
        assert cases_payload["page_size"] == 5
        assert cases_payload["total_pages"] == 3
        assert [case["booking_id"] for case in cases_payload["cases"]] == ["B6", "B7", "B8", "B9", "B10"]

        review_queue_page = client.get(f"/api/jobs/{job_id}/review-queue", params={"page": 2})
        assert review_queue_page.status_code == 200
        review_payload = review_queue_page.json()
        assert review_payload["item_count"] == 12
        assert review_payload["page"] == 2
        assert review_payload["page_size"] == 5
        assert review_payload["total_pages"] == 3
        assert [item["booking_id"] for item in review_payload["items"]] == ["B6", "B7", "B8", "B9", "B10"]
