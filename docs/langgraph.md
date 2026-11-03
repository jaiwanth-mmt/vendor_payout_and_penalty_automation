# LangGraph Investigation Guide

Coding agents and engineers: read this before modifying the LangGraph investigation and portfolio layers.

For complete architectural details, see the modular guides:
- [LangGraph Multi-Agent Investigation](langgraph-investigation.md)
- [Human Edit Workspace & Decision Stage](edit-stage-and-human-in-the-loop.md)
- [Vendor Penalty Mailer Engine](vendor-mailer.md)
- [LLM Token Usage & Cost Tracking](llm-usage-and-cost.md)

---

## 1. Architectural Boundary

LangGraph owns **agent investigation, portfolio synthesis, and vendor penalty mailing only**.

### Keep Outside the Graph (Deterministic Services in `pipeline.py` & `domain/`):
- Excel date filter (`Approval/Rejected DateTime`), CARBD / recoverable filters, dedupe.
- Exclusion filters (drop `User cancellation` / `Customer Delight` and paid-amount refunds).
- Live MySQL tracking + Redash comments fetch.
- Missing `supplier_id` discard rule.
- Category column enrichers (`CATEGORY_ASYNC_ENRICHERS`).
- Vendor No Show SOP fine formula (`ROUND_HALF_UP`).
- Deterministic complaint `message` synthesis (Remarks $\rightarrow$ Sub Category; no call-comments LLM).

---

## 2. Topologies

### Per-Case Investigation Graph (`thread_id = "{job_id}:{booking_id}"`):
```text
intake → evidence_agent → specialist → judge → human_review → finalize
```

### Job Portfolio Graph (`thread_id = "{job_id}:portfolio"`):
```text
portfolio_summary → vendor_penalty_analysis
```

### Vendor Penalty Mailer Graph (`thread_id = "{job_id}:mailer"`):
```text
assign → compose → validate → send → finalize
```

- **Deterministic Templates Only:** Zero LLM rewriting of title, message, fine, transcript, or booking ID. Consumes 0 LLM tokens.
- **SMTP Transport:** Located in [`backend/app/integrations/smtp.py`](../backend/app/integrations/smtp.py).
- **Idempotency & Freeze:** Managed by [`backend/app/services/mailer.py`](../backend/app/services/mailer.py) via SHA-256 `preview_token`.
- **Recipient Configuration:** Configured via `MAILER_RECIPIENTS` in `.env`.
- **Runtime Artifact:** `{job_dir}/mailer_dispatch.json` stores frozen drafts, preview token, and delivery results.

---

## 3. Evidence Tools

The `evidence_agent` invokes 6 specialized tools using `InjectedState`:

| Tool | Purpose | Primary Data Source |
| :--- | :--- | :--- |
| `get_comments` | Customer call transcript | Redash MyDesk notes |
| `get_remarks` | QlikSense Remarks | Uploaded workbook |
| `get_sub_category` | Sub Category row context | Uploaded workbook |
| `get_source_alignment` | Category alignment analysis | Text comparison engine |
| `get_tracking_context` | Timing / fare / vehicle support | Live MySQL `tracking_reports_raw` |
| `get_vendor_context` | Vendor / supplier identity | `incabs_suppliers` join |

### Evidence Policy Rules
- **Primary Category Source:** `Remarks` $\rightarrow$ `Sub Category` (when mapped).
- **Role of Call Comments:** Comments remain available via `get_comments` for display and agent context; they **never** drive `message` or primary category classification.
- **Deterministic Message:** Built deterministically from Remarks $\rightarrow$ Sub Category (`Fulfillment Not Done` $\rightarrow$ `Vendor No Show`). `Details Change` $\equiv$ `Chauffeur/Vehicle Change`.
- **Supporting Context:** Tracking, vendor, and fare context are supporting evidence only; they cannot alone approve a penalty.
- **Judge Guardrails:** Guardrails in `policy.py` force review on unmapped Sub Category-only rows, invalid-penalty language, and Vendor No Show rows where SOP fine could not be computed (missing `amount` or `ttrip_type`). Booking-ID mismatch is **not** a review trigger.

---

## 4. Human Edit Gate (Production)

Production API jobs pass **`enable_hitl=False`**. After all cases finalize, the pipeline always pauses at **`awaiting_edit`** (no LangGraph interrupts).

1. Humans inspect cases in 3 AI buckets: **Needs check**, **Auto-approved**, and **Unhandled (New/unique categories)**.
2. Humans patch editable fields via `PATCH /api/jobs/{id}/edit-cases/{booking_id}` or bulk update via `POST /api/jobs/{id}/edit-cases/bulk`.
3. `POST /api/jobs/{id}/approve-edits` applies outcomes, rewrites processed category XLSX, runs the portfolio graph, and builds the final ZIP package.
4. The Review UI is analysis-only (KPIs, vendor rankings, recommended actions).

- **Editable Fields:** `recoverable_amount` (fine after SOP), `message`, `remarks`, `sub_category`, `edit_outcome`.
- **Read-Only Fields:** `booking_id`, `comments`, `vendor_name`, `amount`, `ttrip_type`, `fine_before_sop`.
- **Outcomes:**
  - `include` $\rightarrow$ `auto_ready`; included in `final_output.xlsx`.
  - `needs_ops` $\rightarrow$ `needs_review`; included in `final_output.xlsx` and `review_queue.xlsx`.
  - `exclude` $\rightarrow$ omitted from `final_output.xlsx` and zeroed out in portfolio recoverable totals.

---

## 5. Streaming & Event Logging

- Nodes emit custom events via `get_stream_writer()` (`type`, `node`, `booking_id`, `tool`, `status`, `summary`).
- Real-time updates delivered via `GET /api/jobs/{id}/events` (SSE).
- Compact executive stage progress is maintained in `job.investigation_summary`.
- Collapsed technical event logs retain the latest 40 events.
- Interactive graph topologies accessible via `GET /api/jobs/{id}/graph` (Mermaid format).

---

## 6. Azure OpenAI & Token Accounting

- Chat completions configured via `AZURE_OPENAI_CHAT_COMPLETIONS_URL` and `AZURE_OPENAI_API_KEY`.
- LangChain chat model factory: [`backend/app/agents/langchain_model.py`](../backend/app/agents/langchain_model.py).
- Category enrichers use [`backend/app/integrations/llm_client.py`](../backend/app/integrations/llm_client.py).
- All requests tagged with `llm_purpose` (`specialist`, `judge`, `source_alignment`, `lower_category_vehicle`, `portfolio`).
- Real-time token usage and cost visible on `/jobs/{id}/usage`.

---

## 7. Development Invariants ("Do Not")

- **Do not** put MySQL, Redash, Excel ETL, or SMTP network sockets inside LangGraph nodes.
- **Do not** use deprecated `langgraph.prebuilt.create_react_agent` (use fixed `StateGraph` + tools).
- **Do not** use `langgraph-supervisor` (subcategory is already known).
- **Do not** allow call comments to overwrite Remarks or Sub Category when generating `message`.
- **Do not** disable TLS certificate verification for SMTP unless required by internal corporate CAs (`SMTP_TLS_VERIFY=false`).

---

## 8. Verification Commands

```bash
uv run pytest
cd frontend && npm run build
```
