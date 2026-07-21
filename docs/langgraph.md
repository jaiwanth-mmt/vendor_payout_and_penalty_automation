# LangGraph Investigation Guide

Coding agents: read this before editing the investigation layer.

## Boundary

LangGraph owns **agent investigation + portfolio only**.

Leave outside the graph (deterministic prep in `pipeline.py` / `domain/`):

- Excel date filter, CARBD / recoverable filters, dedupe
- Live MySQL tracking + Redash comments fetch
- Category column enrichers (`CATEGORY_ASYNC_ENRICHERS`) and complaint `message` classification loops

## Topology

Per-case graph (`thread_id = "{job_id}:{booking_id}"`):

```text
intake → evidence_agent → specialist → judge → human_review → finalize
```

Job portfolio graph (`thread_id = "{job_id}:portfolio"`):

```text
portfolio_summary → vendor_penalty_analysis
```

Source of truth:

- [`backend/app/agents/graphs.py`](../backend/app/agents/graphs.py) — `build_case_graph`, `build_portfolio_graph`
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

**Policy:** source text remains primary (`comments` → `Remarks`; Sub Category alone = missing evidence). Tracking/vendor/fare are supporting context and must not alone approve a penalty. Judge guardrails in `policy.py` still force review on missing text evidence, booking-id mismatch, and invalid-penalty language.

## Streaming + UI

- Nodes emit custom events via `get_stream_writer()` (`type`, `node`, `booking_id`, `tool`, `status`, `summary`).
- Job snapshot includes **`investigation_summary`** — executive stage progress (counts + status line). This is the primary UI surface.
- Raw `graph_events` are retained briefly for a **collapsed technical log** only (not the main feed).
- API: `GET /api/jobs/{id}/events` (SSE), `GET /api/jobs/{id}/graph` (mermaid), plus `agent_progress` / `pending_interrupts`.
- Frontend: ProcessingTimeline shows calm investigation stages; AgentCockpit renders Mermaid topology (sanitized LangGraph HTML labels); technical SSE log is optional/collapsed.

## Human-in-the-loop

When judge `review_status` ∈ `{needs_review, missing_evidence}` and `enable_hitl=True`:

1. `human_review` calls LangGraph `interrupt(payload)`
2. Job status becomes `awaiting_review` (package not finalized)
3. UI / `POST /api/jobs/{id}/cases/{booking_id}/resume` resumes with `Command(resume=human_decision)`
4. When no pending interrupts remain, portfolio + package completion runs

Checkpointer: in-memory per process by default (`InMemorySaver`), keyed by `job_id`. Optional sqlite under `backend/.runtime/langgraph/` via `use_sqlite=True`.

Production API jobs pass `enable_hitl=True`. Unit tests that need immediate completion pass `enable_hitl=False`.

## Azure LLM

Use existing env only:

- `AZURE_OPENAI_CHAT_COMPLETIONS_URL`
- `AZURE_OPENAI_API_KEY`

LangChain chat model factory: [`backend/app/agents/langchain_model.py`](../backend/app/agents/langchain_model.py). Category enrichers still use [`backend/app/integrations/llm_client.py`](../backend/app/integrations/llm_client.py).

## Do not

- Put MySQL / Redash / Excel ETL inside LangGraph nodes
- Use deprecated `langgraph.prebuilt.create_react_agent` (use fixed `StateGraph` + tools here)
- Use `langgraph-supervisor` for this pipeline (subcategory is already known)
- Reintroduce “tracking forbidden in agent decisions” — that rule is obsolete; follow the policy section above

## Verification

```bash
uv run pytest
cd frontend && npm run build
graphify update .
```
