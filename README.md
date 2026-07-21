# Agentic Loss Recovery Copilot

React + FastAPI workflow for converting a QlikSense loss recovery workbook into a Cab Ops recovery package. Jobs filter Excel by an **approval date range**, fetch **live** MySQL tracking + supplier vendor names (+ optional Redash comments) for those Booking IDs, enrich per subcategory, and agentically review each booking from `comments` → `Remarks` → `Sub Category`.

## Project Layout

```text
backend/app/
  agents/         claim cases, evidence, specialists, judge, portfolio
  core/           paths, env, shared tracking_utils
  domain/         workbook shaping, subcategory split, category registry/enrichers
  integrations/   llm_client, tracking/ (repository), MySQL helpers, Redash
  services/       pipeline, package builder, job store
  cli/            help entrypoint only
frontend/src/
  api/ components/ constants/ hooks/ types/
data/demo/        reference workbook + reference tracking JSON shape (not used by API for tracking)
```

See `AGENTS.md` and `docs/agent-playbook.md` for agent-oriented guidance.

## Setup

Copy `.env.example` to `.env`. **API jobs require MySQL credentials** (`MYSQL_PASSWORD` and related vars). Redash and Azure OpenAI are optional.

```bash
CATEGORY_PROCESSING_CONCURRENCY=4
LLM_CONCURRENCY=3
```

`uv sync` for Python; `cd frontend && npm install` if needed.

## Run Locally

```bash
uv run uvicorn backend.app.main:app --reload
cd frontend && npm run dev
```

Open `http://localhost:5173`, upload a QlikSense workbook, set **approval start/end** dates, and run.

## Tests

```bash
uv run pytest
cd frontend && npm run build
```

Tests inject an in-memory tracking repository; they do not call live MySQL.

## Output

Each job ZIP contains prepared/processed category workbooks, `manifest.json`, `final_output.xlsx`, `agent_audit.xlsx`, `review_queue.xlsx`, and `agent_summary.json`.

Agent decisions do not use tracking timing/fare/driver/vehicle/payment fields — those remain workbook enrichment only.

## Demo note

`data/demo/tracking_reports_by_booking.json` is **reference-only** (payload shape). Production tracking always comes from live DB for Booking IDs in the selected date range.
