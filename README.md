# Agentic Loss Recovery Copilot

React + FastAPI app that turns a QlikSense loss-recovery workbook into a Cab Ops ZIP package.

For each job it:

1. Filters Excel rows by an **approval date range** (`Approval/Rejected DateTime`)
2. Keeps CARBD rows with non-zero Recoverable, consolidates duplicate Booking IDs
3. Fetches **live** tracking for those Booking IDs (`order_reference_number` in MySQL)
4. Looks up **vendor names** from `incabs_suppliers`
5. Optionally fetches **call comments** from Redash (MyDesk source)
6. Enriches each subcategory, classifies a complaint `message`, and runs agent review (`comments` → `Remarks` → `Sub Category`)

## Project layout

```text
backend/app/
  main.py           FastAPI API
  models.py         response contracts (keep aligned with frontend types)
  agents/           claim cases, evidence, specialists, judge, portfolio
  core/             paths, env loading, shared tracking_utils
  domain/           Excel shaping, subcategory split, category registry/enrichers
  integrations/     Azure LLM, MySQL tracking helpers, Redash, TrackingRepository
  services/         pipeline orchestration, package builder, job store
  cli/              help entrypoint only
frontend/src/       upload UI (date range), timeline, AgentCockpit, previews
data/demo/          sample workbook + reference tracking JSON (API does not read JSON for tracking)
docs/agent-playbook.md
AGENTS.md           edit guidance for AI coding agents
```

Runtime job artifacts are written under `backend/.runtime/` (gitignored).

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
cd frontend
npm run dev
```

Open `http://localhost:5173`:

1. Upload a QlikSense `.xlsx` (e.g. `data/demo/qliksense_dump.xlsx`)
2. Set **approval start** and **approval end** dates
3. Run automation
4. Download the ZIP / final output / agent audit / review queue when complete

## Data flow (short)

```text
Excel upload + start_date/end_date
  → filter Approval/Rejected DateTime (inclusive)
  → CARBD + recoverable + dedupe
  → split by Sub Category
  → live MySQL tracking + suppliers (+ Redash comments)
  → category enrichers + message + agents
  → ZIP under backend/.runtime/jobs/
```

Booking ID in Excel = `order_reference_number` in MySQL.

## Output package

Each successful job ZIP includes:

- `manifest.json` (`start_date`, `end_date`, category list)
- `final_output.xlsx`
- `agent_audit.xlsx`
- `review_queue.xlsx`
- `agent_summary.json`
- `category_files/prepared/*.xlsx`
- `category_files/processed/*.xlsx`

Processed workbooks include shared tracking fields (amounts, vendor, comments), a `message` column, and agent metadata. Cab Delay also adds Incabs timing / insight columns when Azure is configured.

**Agent decisions** use only `comments`, `Remarks`, and `Sub Category`. Timing, fare, driver, vehicle, and payment fields are workbook enrichment only.

## Tests

```bash
uv run pytest
cd frontend && npm run build
```

Tests use an in-memory tracking repository — they do **not** need live MySQL or Redash.

## Demo / reference data

Under `data/demo/`:

- `qliksense_dump.xlsx` — sample input workbook
- `tracking_reports_by_booking.json` — **reference only** (payload shape). The API always fetches tracking live.
- `expected_agentic_loss_recovery_output.xlsx` — historical expected shape

See `data/demo/README.md`.

## Docs for contributors / agents

- `AGENTS.md` — code map and safe-edit rules
- `docs/agent-playbook.md` — common change recipes and contracts
