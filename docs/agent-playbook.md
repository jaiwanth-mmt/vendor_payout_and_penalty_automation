# Agent Playbook

Keep public API routes, frontend response types, final XLSX columns, and ZIP compatibility stable unless the user explicitly asks for a contract change.

## Common Change Recipes

- **Add a subcategory processor:** add output columns to `CATEGORY_PROCESSORS` and an async enricher to `CATEGORY_ASYNC_ENRICHERS` in `backend/app/domain/category_processors.py`. Put parsing/enrichment helpers in their own `backend/app/domain/` module. Agent investigation runs automatically after enrichment.
- **Add or change agent behavior:** edit `backend/app/agents/` (evidence, source_alignment, specialists, portfolio). Specialists select exactly one source in order: `comments` → `Remarks` → `Sub Category`. Judge applies guardrails. Do not feed tracking timing/fare/vehicle into agent decisions.
- **Change prepared workbook shaping:** edit `backend/app/domain/penalty_dataset.py` (including `filter_by_input_date_range`). Edit `subcategories.py` only for naming/slugging/split.
- **Change package contents:** edit `backend/app/services/package_builder.py`.
- **Change API progress/response fields:** update `backend/app/models.py`, `job_store.py`, and `frontend/src/types/jobs.ts` together.
- **Change live tracking:** edit `backend/app/integrations/tracking/` and/or `tracking_reports.py` / `redash_call_comments.py`. Pipeline accepts any `TrackingRepository`.

## Output Contracts

- Create job form: `file`, `start_date`, `end_date` (inclusive `Approval/Rejected DateTime` range).
- JobResponse includes `start_date`, `end_date` (not `approval_date`).
- Every processed workbook includes shared tracking fields, `message`, and agent metadata columns.
- Cab Delay adds timing + comments + Incabs insights/summaries when available.
- Agent decisions ignore tracking-derived timing/fare/driver/vehicle/payment fields.
- ZIP: `manifest.json`, `final_output.xlsx`, `agent_audit.xlsx`, `review_queue.xlsx`, `agent_summary.json`, `category_files/prepared/*.xlsx`, `category_files/processed/*.xlsx`.
- `data/demo/tracking_reports_by_booking.json` is reference-only; production uses live MySQL/Redash.

## Test Map

- `test_pipeline.py`: orchestration + package; inject `InMemoryTrackingRepository`.
- `test_api.py`: HTTP job lifecycle; monkeypatch `live_tracking_repository_from_env`.
- `test_category_processors.py`: registry enrichers + LLM concurrency.
- `test_package_builder.py`: manifest/ZIP schemas (`start_date`/`end_date`).
- `test_agent_llm.py`: agent prompts/decisions/portfolio.
- `factories.py`: shared workbook/tracking fixtures.

## Verification

```bash
uv run pytest
cd frontend && npm run build
```
