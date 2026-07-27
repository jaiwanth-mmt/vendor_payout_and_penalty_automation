# LangGraph Investigation Guide

Coding agents: read this before editing the investigation layer.

## Boundary

LangGraph owns **agent investigation + portfolio only**.

Leave outside the graph (deterministic prep in `pipeline.py` / `domain/`):

- Excel date filter, CARBD / recoverable filters, dedupe
- Live MySQL tracking + Redash comments fetch
- Category column enrichers (`CATEGORY_ASYNC_ENRICHERS`) and deterministic complaint `message` (Remarks → Sub Category; no call-comments LLM)

## Topology

Per-case graph (`thread_id = "{job_id}:{booking_id}"`):

```text
intake → evidence_agent → specialist → judge → human_review → finalize
```

Job portfolio graph (`thread_id = "{job_id}:portfolio"`):

```text
portfolio_summary → vendor_penalty_analysis
```

Vendor penalty mailer graph (`thread_id = "{job_id}:mailer"`), triggered manually from Outputs after `succeeded`:

```text
assign → compose → validate → send → finalize
```

- Deterministic templates only (no LLM rewrite of title/message/fine/transcript/booking).
- SMTP lives in [`backend/app/integrations/smtp.py`](../backend/app/integrations/smtp.py); freeze/idempotency in [`backend/app/services/mailer.py`](../backend/app/services/mailer.py).
- Recipient list is editable via `MAILER_RECIPIENTS` in `.env`.
- Artifact: `{job_dir}/mailer_dispatch.json` stores frozen drafts + send results.

Source of truth:

- [`backend/app/agents/graphs.py`](../backend/app/agents/graphs.py) — `build_case_graph`, `build_portfolio_graph`
- [`backend/app/agents/mailer/`](../backend/app/agents/mailer/) — mailer state/nodes/graph/runner
- [`backend/app/agents/nodes/investigation.py`](../backend/app/agents/nodes/investigation.py) — node bodies
- [`backend/app/agents/runner.py`](../backend/app/agents/runner.py) — fan-out, streaming, resume
- [`backend/app/agents/tools.py`](../backend/app/agents/tools.py) — `@tool` evidence gatherers
- [`backend/app/agents/policy.py`](../backend/app/agents/policy.py) — deterministic guardrails
- [`backend/app/agents/state.py`](../backend/app/agents/state.py) — `InvestigationState` / `PortfolioState`

## Tools

Evidence agent invokes these tools (InjectedState):

| Tool | Purpose |
|---|---|
| `get_comments` | Customer call transcript |
| `get_remarks` | QlikSense Remarks |
| `get_sub_category` | Sub Category row context |
| `get_source_alignment` | Alignment analysis |
| `get_tracking_context` | Timing / fare / vehicle support |
| `get_vendor_context` | Vendor / supplier support |

**Policy:** category alignment primary is `Remarks` → Sub Category when mapped. Call comments remain available via `get_comments` for display/tools only and do not drive `message` or category primary. `message` is built deterministically from Remarks → Sub Category (`Fulfillment Not Done` → `Vendor No Show`). `Details Change` ≡ `Chauffeur/Vehicle Change`. Tracking/vendor/fare are supporting context and must not alone approve a penalty. Judge guardrails in `policy.py` still force review on unmapped Sub Category-only rows, invalid-penalty language, and Vendor No Show rows where SOP fine could not be computed (missing `amount` / `ttrip_type`) — not booking-ID mismatch. Edit-stage routing in `edit_cases.resolve_edit_bucket` additionally sends missing-Remarks mapped cases to Needs check and blank/`Uncategorized` Sub Category cases to New/unique, with explicit user-facing reasons. The Review UI no longer surfaces per-case LLM rationale or investigation graphs.

## Streaming + UI

- Nodes emit custom events via `get_stream_writer()` (`type`, `node`, `booking_id`, `tool`, `status`, `summary`).
- Job snapshot includes **`investigation_summary`** — executive stage progress (counts + status line). This is the primary UI surface.
- Raw `graph_events` are retained briefly for a **collapsed technical log** only (not the main feed).
- API: `GET /api/jobs/{id}/events` (SSE), `GET /api/jobs/{id}/graph` (mermaid), plus `agent_progress` / `pending_interrupts`.
- Frontend: ProcessingTimeline shows calm investigation stages; AgentCockpit keeps Mermaid topology behind **View graphs** (side-by-side when open) and case evidence behind **View full evidence**; technical SSE log is optional/collapsed.

## Human edit gate (production)

Production API jobs pass **`enable_hitl=False`**. After all cases finalize, the pipeline always pauses at **`awaiting_edit`** (no LangGraph interrupts).

1. Humans PATCH editable fields via `PATCH /api/jobs/{id}/edit-cases/{booking_id}`
2. `POST /api/jobs/{id}/approve-edits` applies outcomes, rewrites processed category XLSX, runs portfolio, builds ZIP
3. Review UI is analysis-only (no Approve / Keep review)

Editable fields: recoverable (fine), message, remarks, sub_category.  
Read-only: booking_id, call comments.  
Outcomes: `include` → `auto_ready`; `needs_ops` → `needs_review`; `exclude` → omitted from `final_output` + recoverable totals.

## LangGraph HITL (tests / optional)

When judge `review_status` ∈ `{needs_review, missing_evidence}` and `enable_hitl=True`:

1. `human_review` calls LangGraph `interrupt(payload)`
2. Job status becomes `awaiting_review` (package not finalized)
3. `POST /api/jobs/{id}/cases/{booking_id}/resume` resumes with `Command(resume=human_decision)`
4. When no pending interrupts remain, packaging can run (legacy path)

Checkpointer: in-memory per process by default (`InMemorySaver`), keyed by `job_id`. Optional sqlite under `backend/.runtime/langgraph/` via `use_sqlite=True`.

Production API jobs pass `enable_hitl=False`. Unit tests that exercise interrupts pass `enable_hitl=True`.

## Azure LLM

Use existing env only:

- `AZURE_OPENAI_CHAT_COMPLETIONS_URL`
- `AZURE_OPENAI_API_KEY`

LangChain chat model factory: [`backend/app/agents/langchain_model.py`](../backend/app/agents/langchain_model.py). Category enrichers still use [`backend/app/integrations/llm_client.py`](../backend/app/integrations/llm_client.py).

## Do not

- Put MySQL / Redash / Excel ETL / SMTP sockets inside LangGraph nodes (call integrations from mailer send via injected transport)
- Use deprecated `langgraph.prebuilt.create_react_agent` (use fixed `StateGraph` + tools here)
- Use `langgraph-supervisor` for this pipeline (subcategory is already known)
- Reintroduce “tracking forbidden in agent decisions” — that rule is obsolete; follow the policy section above
- Disable TLS certificate verification for SMTP

## Verification

```bash
uv run pytest
cd frontend && npm run build
graphify update .
```
