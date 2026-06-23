# Penalty Automation Demo

React + FastAPI workflow for converting a QlikSense loss recovery workbook into a ZIP package of per-subcategory XLSX outputs.

## Project Layout

```text
backend/app/
  core/          repo paths and env loading
  domain/        workbook shaping, subcategory splitting, and category processors
  integrations/  MySQL tracking and Redash comment clients
  services/      API-facing orchestration, package building, and job state
  cli/           package entry points for root wrapper scripts
frontend/src/
  api/ components/ constants/ hooks/ types/
data/demo/
  qliksense_dump.xlsx
  tracking_reports_by_booking.json
  expected_penalty_automation_output.xlsx
```

See `AGENTS.md` for the full code map and safe-edit guidance for AI coding agents.
See `docs/agent-playbook.md` for common change recipes and output-contract notes.

## Setup

Copy `.env.example` to `.env` and fill only the services you need. The app can run the bundled demo without MySQL or Redash access.

Optional processing controls:

```bash
CATEGORY_PROCESSING_CONCURRENCY=4
LLM_CONCURRENCY=3
```

These tune how many subcategories and LLM calls run in parallel during API processing.
`CAB_DELAY_LLM_CONCURRENCY` is still accepted as a deprecated fallback for older `.env` files.

Install Python dependencies with `uv sync` if needed. Install frontend dependencies from `frontend/` with `npm install` if `node_modules` is missing.

## Run Locally

Backend:

```bash
uv run uvicorn backend.app.main:app --reload
```

Frontend:

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173`, upload `data/demo/qliksense_dump.xlsx`, keep the default approval date `2026-03-19`, and run the automation.

## Tests

```bash
uv run pytest
cd frontend
npm run build
```

## CLI Utilities

The root scripts are thin compatibility wrappers around package modules:

```bash
uv run python build_penalty_dataset.py
uv run python enrich_cab_delay_reasons.py
uv run python extract_tracking_reports.py
uv run python add_redash_comments_to_tracking_json.py
```

Keep new implementation code under `backend/app/`; only add or change root scripts when a backwards-compatible command needs to be exposed.

Generated API artifacts are written under `backend/.runtime/`. Demo fixtures live under `data/demo/`.

## Output

The backend creates an in-memory job, writes temporary artifacts under `backend/.runtime/`, splits prepared rows by cleaned subcategory, and returns a downloadable ZIP package. Each package contains prepared category workbooks, processed category workbooks, and `manifest.json`.

All processed subcategory workbooks include fare, distance, toll, charge, driver-charge, comment fields from tracking reports, and a generated `message` complaint-category column.
Cab Delay currently adds Incabs timing evidence, call comments, generated Incabs insights, and Incabs/comment summaries when Azure OpenAI is configured.
Extra Money Taken adds trip type and comment fields from tracking reports.
Fulfillment Not Done adds booking/tracking status, call comments, and formatted Incabs timing evidence.
Lower Category Vehicle adds vehicle category fields from tracking reports plus customer booked/received vehicle values
extracted from comments.
Other subcategories add only the shared tracking amount/comment fields until their custom processors are added.
The frontend shows subcategory progress while processing runs, including Cab Delay insight and summary counters.

The expected demo path for the bundled workbook produces 71 prepared rows across 9 subcategories.
