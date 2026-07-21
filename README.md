# Agentic Loss Recovery Copilot

React + FastAPI app that turns a QlikSense loss-recovery workbook into a Cab Ops ZIP package, with a **LangGraph** investigation layer (tools, streaming, human-in-the-loop).

For each job it:

1. Filters Excel rows by an **approval date range** (`Approval/Rejected DateTime`)
2. Keeps CARBD rows with non-zero Recoverable, consolidates duplicate Booking IDs
3. Fetches **live** tracking for those Booking IDs (`order_reference_number` in MySQL)
4. Looks up **vendor names** from `incabs_suppliers`
5. Optionally fetches **call comments** from Redash (MyDesk source)
6. Enriches each subcategory and classifies a complaint `message`
7. Runs LangGraph investigation: intake → evidence tools → specialist → judge → HITL (when needed) → portfolio → ZIP

## Project layout

```text
backend/app/
  main.py           FastAPI API (SSE, graph topology, HITL resume)
  models.py         response contracts (keep aligned with frontend types)
  agents/           LangGraph graphs, tools, nodes, runner, policy, portfolio
  core/             paths, env loading, shared tracking_utils
  domain/           Excel shaping, subcategory split, category registry/enrichers
  integrations/     Azure LLM, MySQL tracking helpers, Redash, TrackingRepository
  services/         pipeline orchestration, package builder, job store
  cli/              help entrypoint only
frontend/src/       upload UI, investigation stage progress, AgentCockpit (HITL + Mermaid)
data/demo/          sample workbook + reference tracking JSON (API does not read JSON for tracking)
docs/langgraph.md   LangGraph contracts for coding agents
docs/agent-playbook.md
AGENTS.md           edit guidance for AI coding agents
```

Runtime job artifacts are written under `backend/.runtime/` (gitignored). LangGraph checkpoints may use `backend/.runtime/langgraph/`.

## Setup

```bash
cp .env.example .env
uv sync
cd frontend && npm install
```

### Required for real jobs

| Variable | Purpose |
|---|---|
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | Live tracking |
| `MYSQL_TABLE_NAME` | Default `tracking_reports_raw` |

### Recommended for call comments

| Variable | Purpose |
|---|---|
| `REDASH_API_KEY` | Auth for Redash |
| `REDASH_HOST` | Default `http://common-redash.mmt.com` |
| `REDASH_SOURCE_IDS` | Default **`10`** (MyDesk / vortex call tables) |

Without `REDASH_API_KEY`, jobs still run but the `comments` column stays empty.

### Optional

| Variable | Purpose |
|---|---|
| `AZURE_OPENAI_CHAT_COMPLETIONS_URL` / `AZURE_OPENAI_API_KEY` | Insights, `message`, agent decisions |
| `MYSQL_SUPPLIERS_TABLE_NAME` | Default `incabs_suppliers` |
| `CATEGORY_PROCESSING_CONCURRENCY` | How many subcategories run in parallel (default `4`) |
| `LLM_CONCURRENCY` | Parallel Azure calls per category worker (default `3`) |

For large date ranges, raise concurrency carefully (e.g. `LLM_CONCURRENCY=10`, `CATEGORY_PROCESSING_CONCURRENCY=6`) and watch for Azure rate limits. Restart uvicorn after changing `.env`.

## Run locally

Backend:

```bash
uv run uvicorn backend.app.main:app --reload
```

Frontend:

```bash
cd frontend && npm run dev
```

## Job statuses

`queued` → `running` → (`awaiting_review` if LangGraph HITL interrupts) → `succeeded` | `failed`

When the job is `awaiting_review`:

1. Open **Agentic Loss Recovery Copilot** (Agent cockpit)
2. Approve or keep cases in **LangGraph human review**
3. After the last interrupt clears, packaging runs and the final XLSX / ZIP become available

The processing timeline shows calm **investigation stage progress**. Raw LangGraph SSE events stay in a collapsed technical log.

## LangGraph visibility APIs

| Endpoint | Purpose |
|---|---|
| `GET /api/jobs/{id}` | Job snapshot including `investigation_summary`, `pending_interrupts`, short `graph_events` |
| `GET /api/jobs/{id}/events` | SSE stream of node/tool/interrupt events |
| `GET /api/jobs/{id}/graph` | Mermaid topology for case + portfolio graphs |
| `GET /api/jobs/{id}/interrupts` | Pending HITL payloads |
| `POST /api/jobs/{id}/cases/{booking_id}/resume` | Resume an interrupted case |

See [docs/langgraph.md](docs/langgraph.md) for topology, tools, and policy.

## Evidence policy

Source-text alignment remains primary (`comments` → `Remarks`; Sub Category alone is missing evidence). LangGraph tools may also return tracking/vendor/fare context as **supporting** evidence. Judge guardrails still force review on missing text evidence, booking-id mismatch, and invalid-penalty language.

## Tests

```bash
uv run pytest
cd frontend && npm run build
```
