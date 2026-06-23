# Agent Playbook

This project is optimized for small, safe edits. Keep public API routes, frontend response types, root CLI commands, ZIP layout, and workbook column contracts stable unless the user explicitly asks for a contract change.

## Common Change Recipes

- Add a subcategory processor: update `backend/app/domain/category_processors.py` with the category name, output columns, and dispatch branch. Put reusable category-specific parsing/enrichment helpers in their own `backend/app/domain/` module.
- Change prepared workbook shaping: edit `backend/app/domain/penalty_dataset.py` for filtering, duplicate consolidation, and output columns. Edit `backend/app/domain/subcategories.py` only for subcategory cleanup, slugging, or split behavior.
- Change package contents: edit `backend/app/services/package_builder.py` for final output rows, manifest fields, ZIP members, workbook writes, and preview serialization.
- Change API progress or response fields: update `backend/app/models.py`, `backend/app/services/job_store.py`, and the matching frontend types in `frontend/src/types/jobs.ts`.
- Change external data fetching: keep MySQL and Redash behavior inside `backend/app/integrations/`; call those modules from CLI or services.

## Output Contracts

- Root scripts are compatibility wrappers; implementation belongs under `backend/app/`.
- `backend.app.services.pipeline` remains the public pipeline facade. Existing imports from this module should keep working.
- Every processed workbook includes shared tracking fields and the `message` column.
- Cab Delay adds timing evidence, comments, Incabs insights, and comment summaries when available.
- The ZIP contains `manifest.json`, `final_output.xlsx`, `category_files/prepared/*.xlsx`, and `category_files/processed/*.xlsx`.
- `frontend/src/types/jobs.ts` must stay aligned with `backend/app/models.py`.

## Test Map

- `backend/tests/test_pipeline.py`: end-to-end orchestration, job package behavior, and pipeline-level failure handling.
- `backend/tests/test_subcategories.py`: subcategory cleanup, slugging, splitting, and prepared-output shape.
- `backend/tests/test_category_processors.py`: category processor dispatch, enrichment columns, LLM fallback/concurrency, and category-specific outputs.
- `backend/tests/test_package_builder.py`: final output, manifest, ZIP names, and preview serialization.
- `backend/tests/factories.py`: shared workbook/tracking fixtures for backend tests.

## Verification

```bash
uv run pytest
cd frontend && npm run build
```
