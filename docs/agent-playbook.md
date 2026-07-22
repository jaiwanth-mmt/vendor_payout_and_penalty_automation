# Agent Playbook

Keep public API routes, frontend response types, final XLSX columns, and ZIP compatibility stable unless the user explicitly asks for a contract change.

## Common Change Recipes

- **Add a subcategory processor:** add output columns to `CATEGORY_PROCESSORS` and an async enricher to `CATEGORY_ASYNC_ENRICHERS` in `backend/app/domain/category_processors.py`. Put parsing/enrichment helpers in their own `backend/app/domain/` module. LangGraph investigation runs automatically after enrichment.
- **Add or change LangGraph behavior:** edit `backend/app/agents/` (`graphs.py`, `nodes/`, `tools.py`, `policy.py`, `runner.py`). See `docs/langgraph.md`. Do not put Excel/MySQL/Redash ETL into graph nodes.
- **Add an evidence tool:** define `@tool` in `tools.py`, add to `INVESTIGATION_TOOLS`, and ensure evidence_agent invokes it. Update UI tool timeline expectations if needed.
- **Change HITL routing:** edit `HITL_REVIEW_STATUSES` / `human_review_node` in `policy.py` + `nodes/investigation.py`, and the resume endpoint in `main.py`.
- **Change prepared workbook shaping:** edit `backend/app/domain/penalty_dataset.py` (including `filter_by_input_date_range`). Edit `subcategories.py` only for naming/slugging/split.
- **Change package contents:** edit `backend/app/services/package_builder.py`.
- **Change API progress/response fields:** update `backend/app/models.py`, `job_store.py`, and `frontend/src/types/jobs.ts` together.
- **Change live tracking:** edit `backend/app/integrations/tracking/` and/or `tracking_reports.py` / `redash_call_comments.py`. Pipeline accepts any `TrackingRepository`.

## Output Contracts

- Create job form: `file`, `start_date`, `end_date` (inclusive `Approval/Rejected DateTime` range).
- JobResponse includes `start_date`, `end_date` (not `approval_date`).
- Job statuses: `queued` | `running` | `awaiting_review` | `succeeded` | `failed`.
- LangGraph visibility: `investigation_summary` (primary), `agent_progress`, `pending_interrupts`, `graph_topology`; `graph_events` for collapsed technical detail only.
- Endpoints: `GET /api/jobs/{id}/events` (SSE), `GET /api/jobs/{id}/graph`, `GET /api/jobs/{id}/interrupts`, `POST /api/jobs/{id}/cases/{booking_id}/resume`, `GET /api/jobs/{id}/categories/download` (ZIP of all category prepared/processed XLSX).
- Every processed workbook includes shared tracking fields, `message`, and agent metadata columns.
- Cab Delay adds timing + comments + Incabs insights/summaries when available.
- Evidence tools may include tracking/vendor context; source-text alignment remains primary for auto-ready (`comments` → `Remarks` → mapped Sub Category). Booking-ID mismatch does not force HITL.
- ZIP: `manifest.json`, `final_output.xlsx`, `agent_audit.xlsx`, `review_queue.xlsx`, `agent_summary.json`, `category_files/prepared/*.xlsx`, `category_files/processed/*.xlsx`.
- UI routes: `/` (upload) → `/jobs/:jobId` (progress) → `/jobs/:jobId/review` (HITL) → `/jobs/:jobId/outputs` (previews). Job session state lives in `JobProvider`; do not add a second poller on pages. Processing timeline has no package ZIP button; category preview downloads category Excels; case evidence and investigation graphs stay collapsed until revealed.
- `data/demo/tracking_reports_by_booking.json` is reference-only; production uses live MySQL/Redash.

## Test Map

- `test_pipeline.py`: orchestration + package; inject `InMemoryTrackingRepository`.
- `test_api.py`: HTTP job lifecycle; monkeypatch `live_tracking_repository_from_env`.
- `test_category_processors.py`: registry enrichers + LLM concurrency.
- `test_package_builder.py`: manifest/ZIP schemas (`start_date`/`end_date`).
- `test_agent_llm.py`: prompts/decisions/portfolio (compat wrappers over LangGraph nodes).
- `test_langgraph_graph.py`: graph compile, tools, HITL interrupt/resume.
- `factories.py`: shared workbook/tracking fixtures.

## Verification

```bash
uv run pytest
cd frontend && npm run build
graphify update .
```
