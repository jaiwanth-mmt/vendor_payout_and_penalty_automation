# Agent Guide

## What This Project Does
Penalty Automation converts a QlikSense loss recovery workbook into a ZIP package of per-subcategory workbooks for cab-ops review. The backend filters and consolidates workbook rows, splits the prepared data by cleaned subcategory, runs category-specific processors, adds a generated complaint-category `message`, and packages prepared/processed XLSX files with a manifest. Cab Delay currently adds Incabs timing evidence, call comments, and optional Azure OpenAI explanations; other subcategories receive shared tracking fields plus the message classifier until their processors are added.

## Project Map
- `backend/app/main.py`: FastAPI routes and job lifecycle wiring.
- `backend/app/models.py`: API response models shared by backend tests and frontend expectations.
- `backend/app/services/pipeline.py`: public pipeline facade and high-level orchestration.
- `backend/app/services/package_builder.py`: final XLSX, manifest, ZIP, and preview payload creation.
- `backend/app/services/job_store.py`: in-memory job lifecycle/progress state.
- `backend/app/domain/penalty_dataset.py`: loss-recovery workbook filtering, duplicate consolidation, and prepared output shaping.
- `backend/app/domain/subcategories.py`: cleaned subcategory names, slug generation, and prepared row splitting.
- `backend/app/domain/category_processors.py`: subcategory processor registry, output-column contracts, message enrichment, and processor dispatch.
- `backend/app/domain/cab_delay_enrichment.py`: Cab Delay timing evidence, comments, and Azure OpenAI prompt/client helpers.
- `backend/app/domain/`: other category-specific enrichment helpers.
- `backend/app/integrations/`: MySQL tracking extraction and Redash comment clients.
- `backend/app/core/`: repo paths and environment loading.
- `backend/app/cli/`: package entry points used by root compatibility scripts.
- `frontend/src/api/`: HTTP calls to the backend.
- `frontend/src/hooks/`: React state and polling workflows.
- `frontend/src/components/`: presentational UI pieces.
- `frontend/src/constants/` and `frontend/src/types/`: shared frontend schema and display constants.
- `data/demo/`: bundled demo workbook, tracking JSON, and expected output workbook.
- `docs/agent-playbook.md`: common AI-agent edit recipes and output contracts.

## Run Commands
- Backend API: `uv run uvicorn backend.app.main:app --reload`
- Frontend dev server: `cd frontend && npm run dev`
- Backend tests: `uv run pytest`
- Frontend build/typecheck: `cd frontend && npm run build`
- Build workbook output manually: `uv run python build_penalty_dataset.py`
- Enrich workbook manually: `uv run python enrich_cab_delay_reasons.py`
- Refresh tracking JSON manually: `uv run python extract_tracking_reports.py`

## Data Flow
1. Upload workbook through `POST /api/jobs`.
2. `backend.app.services.pipeline.process_uploaded_workbook` reads the workbook and calls domain logic.
3. Penalty rows are filtered by approval date, CARBD loss department, and non-zero recoverable amount.
4. Duplicate bookings are consolidated and shaped into prepared columns.
5. Prepared rows are split into exact cleaned `Sub Category` XLSX files.
6. Demo tracking data from `data/demo/tracking_reports_by_booking.json` is matched by Booking ID.
7. Each subcategory processor writes its own processed XLSX; every processed workbook gets a `message` complaint-category column, and Cab Delay adds timing/comment/summary columns.
8. The API stores runtime output under `backend/.runtime/jobs/` and exposes a ZIP package download.

## Runtime Progress
- API jobs expose per-step unit counters and per-subcategory progress in `JobResponse`.
- Subcategory processing runs concurrently; tune with `CATEGORY_PROCESSING_CONCURRENCY` in `.env`.
- LLM calls run concurrently with `LLM_CONCURRENCY`; `CAB_DELAY_LLM_CONCURRENCY` remains a deprecated fallback.

## Safe Edit Guidance
- Keep API endpoints, response fields, and per-subcategory output contracts stable unless the user explicitly asks for a contract change.
- Add or change subcategory processors in `backend/app/domain/category_processors.py`; keep category-specific helper logic in focused `backend/app/domain/` modules.
- Add workbook filtering/shaping rules in `backend/app/domain/penalty_dataset.py`; add subcategory naming/splitting rules in `backend/app/domain/subcategories.py`.
- Keep high-level orchestration in `backend/app/services/pipeline.py`; do not put category business rules there.
- Put final-output, manifest, ZIP, and preview-payload changes in `backend/app/services/package_builder.py`.
- Keep external service details in `backend/app/integrations/`; do not mix network calls into React components or API route handlers.
- Use `backend/app/core/paths.py` for repo-relative paths instead of hardcoded local machine paths.
- Root scripts are compatibility wrappers. Add new implementation code under `backend/app/` first, then expose it through a wrapper only if needed.
- When changing frontend behavior, keep server types in `frontend/src/types/jobs.ts` aligned with `backend/app/models.py`.
- Run both `uv run pytest` and `cd frontend && npm run build` before handing off structural changes.
