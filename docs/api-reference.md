# REST & SSE API Reference

This document provides a comprehensive technical specification of all REST endpoints, query parameters, request/response models, and Server-Sent Events (SSE) contracts exposed by `backend/app/main.py`.

---

## 1. System Health & Job Lifecycle

### `GET /api/health`
Checks server availability.
- **Response `200 OK`:**
  ```json
  { "status": "ok" }
  ```

---

### `POST /api/jobs`
Creates a new background loss recovery processing job.
- **Content-Type:** `multipart/form-data`
- **Form Parameters:**
  - `file` (UploadFile, required): QlikSense Excel workbook (`.xlsx` or `.xls`).
  - `start_date` (string, optional): Range start date in ISO format (`YYYY-MM-DD`). Required unless `process_all=true`.
  - `end_date` (string, optional): Range end date in ISO format (`YYYY-MM-DD`). Required unless `process_all=true`.
  - `process_all` (boolean, optional, default `false`): When `true`, date filtering is bypassed and the entire workbook is processed.
- **Response `200 OK` (`CreateJobResponse`):**
  ```json
  {
    "job_id": "7f8b9c2a1e4d4e3f8a9b2c1d3e5f7a9b",
    "status": "queued"
  }
  ```
- **Error Codes:**
  - `400 Bad Request`: File is not a `.xlsx` or `.xls` workbook.
  - `422 Unprocessable Entity`: Missing `start_date`/`end_date` without `process_all=true`, invalid ISO format, or `start_date > end_date`.

---

### `GET /api/jobs/{job_id}`
Returns the comprehensive real-time snapshot of the job.
- **Response `200 OK` (`JobResponse`):**
  ```json
  {
    "job_id": "7f8b9c2a...",
    "status": "awaiting_edit",
    "current_step": "agent_investigation",
    "original_filename": "Qlik_Export.xlsx",
    "start_date": "2026-07-01",
    "end_date": "2026-07-15",
    "process_all": false,
    "created_at": "2026-11-04T00:00:00Z",
    "updated_at": "2026-11-04T00:02:15Z",
    "steps": [
      {
        "id": "workbook_parsed",
        "label": "Workbook parsed",
        "status": "completed",
        "message": "120 workbook rows read"
      }
    ],
    "metrics": {
      "raw_rows": 120,
      "prepared_rows": 45,
      "needs_check_count": 7,
      "auto_approved_count": 35,
      "unhandled_count": 3
    },
    "warnings": [],
    "category_progress": [],
    "category_outputs": [],
    "investigation_summary": {
      "total_cases": 45,
      "cases_seen": 45,
      "cases_finalized": 45,
      "pending_review": 0,
      "status_line": "All 45 cases finalized"
    },
    "llm_usage": { ... },
    "download_ready": false,
    "error": null
  }
  ```

---

## 2. Human Edit Workspace Endpoints

### `GET /api/jobs/{job_id}/edit-cases`
Returns a paginated list of cases within the human edit stage.
- **Query Parameters:**
  - `page` (integer, default `1`): 1-based page index.
  - `bucket` (string, optional): Filter by AI bucket (`needs_check`, `auto_approved`, `unhandled`).
  - `booking_id` (string, optional): Filter by exact booking ID.
  - `sub_category` (string, optional): Filter by exact subcategory.
- **Response `200 OK` (`EditCasesPageResponse`):**
  ```json
  {
    "cases": [
      {
        "booking_id": "MMT1001",
        "comments": "Customer reported cab did not arrive.",
        "recoverable_amount": 500.0,
        "message": "Vendor No Show",
        "remarks": "vendor no show",
        "sub_category": "FULFILLMENT NOT DONE",
        "vendor_name": "Reliable Cabs",
        "amount": 1200.0,
        "ttrip_type": "airport",
        "fine_before_sop": 1200.0,
        "fine_after_sop": 500.0,
        "ai_bucket": "auto_approved",
        "ai_review_status": "auto_ready",
        "edit_outcome": "include",
        "was_edited": false,
        "edited_fields": [],
        "review_reason": "",
        "excluded": false
      }
    ],
    "case_count": 1,
    "page": 1,
    "page_size": 5,
    "total_pages": 1,
    "needs_check_count": 7,
    "auto_approved_count": 35,
    "unhandled_count": 3,
    "edited_case_count": 0,
    "excluded_case_count": 0,
    "available_sub_categories": ["Cab Delay", "FULFILLMENT NOT DONE"]
  }
  ```

---

### `PATCH /api/jobs/{job_id}/edit-cases/{booking_id}`
Updates editable attributes for a specific case.
- **Request Body (`PatchEditCaseRequest`):**
  ```json
  {
    "recoverable_amount": 600.0,
    "message": "Vendor No Show",
    "remarks": "Vendor informed delay, missed flight",
    "sub_category": "FULFILLMENT NOT DONE",
    "edit_outcome": "include"
  }
  ```
- **Response `200 OK` (`EditCaseItem`):** The updated case view with `was_edited=true` and updated `edited_fields`.

---

### `POST /api/jobs/{job_id}/edit-cases/bulk`
Applies an `edit_outcome` to all cases matching the specified bucket and filters.
- **Request Body (`BulkPatchEditCasesRequest`):**
  ```json
  {
    "bucket": "needs_check",
    "edit_outcome": "include",
    "sub_category": "Cab Delay"
  }
  ```
- **Response `200 OK` (`BulkPatchEditCasesResponse`):**
  ```json
  {
    "updated_count": 4,
    "needs_check_count": 7,
    "auto_approved_count": 35,
    "unhandled_count": 3,
    "edited_case_count": 4,
    "excluded_case_count": 0
  }
  ```

---

### `POST /api/jobs/{job_id}/approve-edits`
Locks human edits, rewrites processed category workbooks, builds portfolio artifacts, and packages the final deliverables.
- **Response `200 OK` (`JobResponse`):** Updated job snapshot with `status="succeeded"`.

---

## 3. Vendor Penalty Mailer Endpoints

### `GET /api/jobs/{job_id}/mailer`
Returns current dispatch status and frozen drafts if previously generated.
- **Response `200 OK` (`MailerDispatchResponse`).**

---

### `POST /api/jobs/{job_id}/mailer/preview`
Generates frozen email drafts and computes the cryptographic `preview_token`.
- **Response `200 OK` (`MailerDispatchResponse`):**
  ```json
  {
    "status": "preview_ready",
    "preview_token": "9a8b7c6d5e...",
    "final_output_checksum": "1f2e3d4c...",
    "recipients": ["manager@go-mmt.com"],
    "drafts": [
      {
        "recipient": "manager@go-mmt.com",
        "booking_id": "MMT1001",
        "subject": "Penalty complaint details - MMT1001",
        "title": "Service Issue",
        "message": "Vendor No Show",
        "fine": "500",
        "call_transcript": "Customer reported cab did not arrive."
      }
    ],
    "can_send": true
  }
  ```

---

### `POST /api/jobs/{job_id}/mailer/send`
Dispatches frozen emails to recipients via SMTP.
- **Request Body (`SendVendorMailRequest`):**
  ```json
  {
    "preview_token": "9a8b7c6d5e..."
  }
  ```
- **Response `200 OK` (`MailerDispatchResponse`):** Returns dispatch status (`sent` or `partial`) and per-recipient message IDs.
- **Error Codes:**
  - `409 Conflict`: Mail already sent, or `preview_token` is stale because `final_output.xlsx` changed.
  - `503 Service Unavailable`: SMTP server unreachable.

---

## 4. Previews & Table Paginations

### `GET /api/jobs/{job_id}/final-output/preview`
Paginates through `final_output.xlsx`.
- **Query Parameters:** `page` (default `1`), `page_size` (default `25`, max `100`), `booking_id` (optional).
- **Response `200 OK` (`FinalOutputPreviewResponse`):** Returns `columns`, `rows`, `total_pages`, `row_count`.

---

### `GET /api/jobs/{job_id}/categories/{slug}/preview`
Paginates through a specific subcategory processed workbook (`category_files/processed/{slug}.xlsx`).
- **Query Parameters:** `page` (default `1`), `page_size` (default `5`, max `100`), `booking_id` (optional).
- **Response `200 OK` (`CategoryPreviewResponse`).**

---

## 5. Artifact Download Endpoints

| Endpoint | Content-Type | Artifact Returned |
| :--- | :--- | :--- |
| `GET /api/jobs/{id}/download` | `application/zip` | Full ZIP package (`agentic_loss_recovery_package.zip`). |
| `GET /api/jobs/{id}/final-output/download` | `application/vnd.openxmlformats-...` | `final_output.xlsx` |
| `GET /api/jobs/{id}/categories/download` | `application/zip` | ZIP of prepared and processed category workbooks. |
| `GET /api/jobs/{id}/agent-audit/download` | `application/vnd.openxmlformats-...` | `agent_audit.xlsx` |
| `GET /api/jobs/{id}/review-queue/download` | `application/vnd.openxmlformats-...` | `review_queue.xlsx` |

---

## 6. Server-Sent Events (SSE) & Real-Time Streaming

### `GET /api/jobs/{job_id}/events`
Opens a real-time event stream (`text/event-stream`) delivering investigation events and node updates.

#### Event Stream Protocol

1. **Heartbeat / Ping:**
   ```text
   event: ping
   data: {"time": "2026-11-04T00:00:00Z"}
   ```
2. **Graph Execution Event:**
   ```text
   event: graph_event
   data: {
     "type": "node",
     "node": "specialist",
     "booking_id": "MMT1001",
     "status": "completed",
     "summary": "Specialist verified Vendor No Show"
   }
   ```
3. **Stream Completion:**
   ```text
   event: done
   data: {"status": "succeeded"}
   ```

