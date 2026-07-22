# Agent Guide

## What This Project Does
Agentic Loss Recovery Copilot converts a QlikSense loss-recovery workbook into a ZIP of per-subcategory workbooks plus agent investigation artifacts. The API filters Excel rows by an **approval date range**, consolidates duplicates, splits by subcategory, fetches **live** tracking/vendor/comment data for those Booking IDs, runs category enrichers + complaint `message` classification, then runs a **LangGraph** investigation (intake → evidence tools → specialist → judge → HITL → finalize → portfolio).

## Project Map
- `backend/app/main.py`: FastAPI routes, SSE/graph/HITL resume, job lifecycle wiring.
- `backend/app/models.py`: API response models — keep aligned with `frontend/src/types/jobs.ts`.
- `backend/app/services/pipeline.py`: orchestration facade (date range → live tracking → category registry → LangGraph investigation → package).
- `backend/app/services/package_builder.py`: XLSX, manifest, ZIP, preview payloads.
- `backend/app/services/job_store.py`: in-memory job lifecycle/progress (`awaiting_review`, `investigation_summary`, short graph-event retention).
- `backend/app/domain/penalty_dataset.py`: workbook filter (date range), CARBD/recoverable filters, dedupe, shape.
- `backend/app/domain/subcategories.py`: cleaned subcategory names, slugs, split.
- `backend/app/domain/category_processors.py`: **processor registry** (`CATEGORY_ASYNC_ENRICHERS`) + message/Cab Delay LLM loops; calls LangGraph runner after enrichers.
- `backend/app/domain/`: category enrichers (`cab_delay_enrichment`, `extra_money_taken`, `fulfillment_not_done`, `lower_category_vehicle`, `tracking_common`, `complaint_message`).
- `backend/app/core/tracking_utils.py`: shared tracking dict access + time formatting (do **not** put these in Cab Delay).
- `backend/app/core/paths.py` / `env.py`: repo paths and `.env` loading (`LANGGRAPH_RUNTIME_ROOT`).
- `backend/app/integrations/llm_client.py`: Azure OpenAI sync/async client for enrichers/message.
- `backend/app/integrations/tracking/`: `TrackingRepository` (live MySQL + suppliers + Redash; in-memory for tests).
- `backend/app/integrations/tracking_reports.py`: MySQL fetch/prune/vendor join helpers (library only).
- `backend/app/integrations/redash_call_comments.py`: Redash comment fetch (library only).
- `backend/app/agents/`: **LangGraph investigation** — `graphs.py`, `runner.py`, `tools.py`, `nodes/`, `policy.py`, `state.py`, `langchain_model.py`, plus source alignment / portfolio helpers.
- `frontend/src/`: React multi-page UI — `/` upload (`useCreateJob`), `/jobs/:jobId` progress, `/jobs/:jobId/review` HITL, `/jobs/:jobId/outputs` downloads. `JobProvider`/`useJobSession` own poll+SSE across job routes. Agent cockpit under `components/agent/`.
- `data/demo/`: reference workbook + reference tracking JSON shape (**API does not read tracking JSON**).
- `docs/langgraph.md`: LangGraph topology, tools, HITL, streaming contracts for coding agents.
- `docs/agent-playbook.md`: common AI-agent edit recipes.

## Run Commands
- Backend API: `uv run uvicorn backend.app.main:app --reload`
- Frontend: `cd frontend && npm run dev`
- Backend tests: `uv run pytest`
- Frontend build: `cd frontend && npm run build`

## Data Flow
1. `POST /api/jobs` with `file`, `start_date`, `end_date` (YYYY-MM-DD, inclusive).
2. Filter `Approval/Rejected DateTime` to that range → CARBD → non-zero Recoverable → dedupe → prepared columns.
3. Split prepared rows by cleaned `Sub Category`.
4. Live tracking for prepared Booking IDs (`order_reference_number`):
   - MySQL `tracking_reports_raw`
   - Vendor names via `incabs_suppliers` (`oid` ← supplier ids on tracking rows → `on_final` as `vendor_name`)
   - Redash call comments when `REDASH_API_KEY` is set
5. Registry-dispatched category enrichers + `message` column.
6. LangGraph per-case investigation (tools + specialist + judge + optional HITL interrupt).
7. If interrupts remain → job status `awaiting_review`. Else portfolio graph → ZIP under `backend/.runtime/jobs/`.

## Live Tracking Config (`.env`)
Required for API jobs: `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`, `MYSQL_TABLE_NAME` (default `tracking_reports_raw`).
Optional: `MYSQL_SUPPLIERS_TABLE_NAME` (default `incabs_suppliers`), `REDASH_*`, `AZURE_OPENAI_*`, `CATEGORY_PROCESSING_CONCURRENCY`, `LLM_CONCURRENCY`.

## Safe Edit Guidance
- Keep ZIP layout stable unless the user asks to change contracts.
- **LangGraph changes:** edit `backend/app/agents/graphs.py`, `nodes/`, `tools.py`, `policy.py`, `runner.py`. Read `docs/langgraph.md` first.
- **Add/remove a subcategory enricher:** register one entry in `CATEGORY_ASYNC_ENRICHERS` + output columns in `CATEGORY_PROCESSORS`; put helpers in a focused `domain/` module. Do **not** move enrichers into LangGraph.
- **Do not** put MySQL/Redash/Azure HTTP in React or route handlers — use `integrations/`.
- **Evidence policy:** tools may return tracking/vendor/fare context; **source-text alignment (comments → Remarks → Sub Category when mapped) remains primary**. `Details Change` ≡ `Chauffeur/Vehicle Change`. Cab Delay family ↔ Vendor No Show / Fulfillment Not Done uses Remarks → Sub Category as primary. Judge guardrails still force review on unmapped Sub Category-only rows and invalid-penalty language — **not** on booking-ID mismatch.
- Tests inject `InMemoryTrackingRepository`; never require live DB for `pytest`. Graph tests use `InMemorySaver` / `enable_hitl` flags.
- After structural code moves: `graphify update .`
- Run `uv run pytest` and `cd frontend && npm run build` before handoff.
