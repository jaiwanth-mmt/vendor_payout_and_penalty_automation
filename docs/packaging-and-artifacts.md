# Packaging, File Schemas & Output Artifacts

This document defines the file specifications, column layouts, JSON schemas, and compression layout for all artifacts produced by `backend/app/services/package_builder.py`.

---

## 1. Output Package Layout

When a job reaches `succeeded`, all deliverables are assembled inside `backend/.runtime/{job_id}/` and compressed into `agentic_loss_recovery_package.zip`:

```text
agentic_loss_recovery_package.zip
├── manifest.json
├── final_output.xlsx
├── agent_audit.xlsx
├── review_queue.xlsx
├── agent_summary.json
└── category_files/
    ├── prepared/
    │   ├── cab-delay.xlsx
    │   ├── extra-money-taken.xlsx
    │   └── fulfillment-not-done.xlsx
    └── processed/
        ├── cab-delay.xlsx
        ├── extra-money-taken.xlsx
        └── fulfillment-not-done.xlsx
```

---

## 2. Deliverable Schemas & Column Contracts

### A. Final Output Workbook (`final_output.xlsx`)

The core deliverable consumed by the Cab Ops recovery teams. It contains exactly 7 standardized columns:

| Column Position | Column Name | Source Field in Processed Frame | Description |
| :---: | :--- | :--- | :--- |
| **1** | `booking_id` | `Booking ID` | Unique MMT booking reference number. |
| **2** | `complaint_reasons` | `Sub Category` | Categorized complaint subcategory. |
| **3** | `complaint_against` | `complaint_against` | Constant identifier: `"dispatch_id"`. |
| **4** | `complaint_against_id`| `complaint_against_id` | Dispatch ID value extracted from live tracking. |
| **5** | `title` | `title` | Constant title: `"Service Issue"`. |
| **6** | `message` | `message` | Normalized canonical complaint category string (`A + B`). |
| **7** | `fine` | `Recoverable` | Post-SOP (or human-edited) penalty amount. |

#### Critical Invariants
- **Exclusion Guarantee:** Rows marked with `edit_outcome = "exclude"` are **completely omitted** from `final_output.xlsx`.
- **Clean Schema:** Internal calculation columns (such as `fine_before_sop`, `fine_after_sop`, `amount`, and `ttrip_type`) are deliberately excluded from this file.

---

### B. Agent Audit Workbook (`agent_audit.xlsx`)

Provides a comprehensive 33-column audit trail documenting all decisions, confidence levels, and human modifications:

```python
AGENT_AUDIT_COLUMNS = [
    "booking_id",
    "sub_category",
    "message",
    "recoverable_amount",
    "review_status",
    "decision",
    "decision_source",
    "llm_error",
    "complaint_categories",
    "confidence",
    "recommended_recovery_amount",
    "recommended_action",
    "review_reason",
    "rationale",
    "source_used",
    "source_categories",
    "row_categories",
    "source_alignment_status",
    "source_alignment_reason",
    "mentioned_booking_ids",
    "specialist_agent",
    "specialist_decision_source",
    "specialist_llm_error",
    "specialist_confidence",
    "judge_decision_source",
    "judge_llm_error",
    "judge_confidence",
    "evidence_ids",
    "evidence_count",
    "trace_count",
    "edit_outcome",
    "was_edited",
    "excluded",
]
```

---

### C. Review Queue Workbook (`review_queue.xlsx`)

Filters cases flagged with `review_status` $\in \{\text{"needs_review"}, \text{"missing_evidence"}, \text{"contradiction"}\}$ to assist operations teams in manual follow-ups:

```python
REVIEW_QUEUE_COLUMNS = [
    "booking_id",
    "sub_category",
    "message",
    "recoverable_amount",
    "review_status",
    "decision",
    "decision_source",
    "llm_error",
    "confidence",
    "recommended_action",
    "review_reason",
    "rationale",
    "source_used",
    "source_categories",
    "row_categories",
    "source_alignment_status",
    "source_alignment_reason",
    "evidence_ids",
]
```

---

### D. Executive Summary JSON (`agent_summary.json`)

Synthesized portfolio metrics and vendor penalty rankings produced by the LangGraph portfolio graph:

```json
{
  "executive_summary": "Processed 45 claims totaling ₹56,200 in recoverable penalties across 3 subcategories.",
  "case_counts": {
    "total_cases": 45,
    "auto_ready": 38,
    "needs_review": 5,
    "missing_evidence": 2,
    "contradiction": 0,
    "failed": 0
  },
  "total_recoverable_amount": 56200.0,
  "high_confidence_case_count": 38,
  "high_confidence_recoverable_amount": 49800.0,
  "top_complaint_drivers": [
    "Vendor No Show",
    "Cab Delayed > 15 Minutes"
  ],
  "category_breakdown": [
    {
      "category": "FULFILLMENT NOT DONE",
      "case_count": 25,
      "total_recoverable_amount": 32000.0
    }
  ],
  "top_vendors_by_penalty": [
    {
      "vendor_name": "Reliable Cabs Pvt Ltd",
      "case_count": 12,
      "total_recoverable_amount": 16000.0
    }
  ],
  "edited_case_count": 4,
  "excluded_case_count": 2,
  "needs_check_count": 7,
  "auto_approved_count": 35,
  "unhandled_count": 3
}
```

---

### E. Manifest Specification (`manifest.json`)

Machine-readable manifest tracking processing metadata, row counts, and relative file paths:

```json
{
  "generated_at": "2026-11-04T00:00:00+00:00",
  "start_date": "2026-07-01",
  "end_date": "2026-07-20",
  "process_all": false,
  "raw_rows": 120,
  "prepared_rows": 45,
  "final_output_rows": 43,
  "categories": [
    {
      "name": "Cab Delay",
      "slug": "cab-delay",
      "row_count": 18,
      "prepared_file": "category_files/prepared/cab-delay.xlsx",
      "processed_file": "category_files/processed/cab-delay.xlsx",
      "status": "completed",
      "error": null
    }
  ],
  "final_output": {
    "filename": "final_output.xlsx",
    "row_count": 43,
    "columns": [
      "booking_id",
      "complaint_reasons",
      "complaint_against",
      "complaint_against_id",
      "title",
      "message",
      "fine"
    ],
    "download_ready": true
  },
  "agent_artifacts": {
    "agent_audit": "agent_audit.xlsx",
    "review_queue": "review_queue.xlsx",
    "agent_summary": "agent_summary.json"
  }
}
```

---

## 3. Dedicated Artifact Download Endpoints

| Endpoint | Content-Type | Download Filename |
| :--- | :--- | :--- |
| `GET /api/jobs/{id}/download` | `application/zip` | `agentic_loss_recovery_{start}_to_{end}.zip` |
| `GET /api/jobs/{id}/final-output/download` | `application/vnd.openxmlformats-...` | `final_output.xlsx` |
| `GET /api/jobs/{id}/categories/download` | `application/zip` | `category_outputs.zip` |
| `GET /api/jobs/{id}/agent-audit/download` | `application/vnd.openxmlformats-...` | `agent_audit.xlsx` |
| `GET /api/jobs/{id}/review-queue/download` | `application/vnd.openxmlformats-...` | `review_queue.xlsx` |

