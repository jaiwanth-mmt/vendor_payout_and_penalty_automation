from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openpyxl import load_workbook

from backend.app.core.env import load_env_file
from backend.app.core.paths import DEFAULT_APPROVAL_DATE, DEMO_TRACKING_JSON_PATH, JOB_RUNTIME_ROOT, REPO_ROOT
from backend.app.models import CreateJobResponse, FinalOutputPreviewResponse, JobResponse
from backend.app.services.job_store import JobStore
from backend.app.services.pipeline import process_uploaded_workbook_async


RUNTIME_DIR = JOB_RUNTIME_ROOT
TRACKING_JSON_PATH = DEMO_TRACKING_JSON_PATH

load_env_file(REPO_ROOT / ".env")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Penalty Automation API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

job_store = JobStore()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/jobs", response_model=CreateJobResponse)
async def create_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    approval_date: str = Form(DEFAULT_APPROVAL_DATE),
) -> CreateJobResponse:
    validate_approval_date(approval_date)
    validate_upload(file)

    job_id = uuid4().hex
    job_dir = RUNTIME_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    upload_path = job_dir / f"input{Path(file.filename or '').suffix or '.xlsx'}"
    upload_path.write_bytes(await file.read())

    job_store.create_job(
        job_id=job_id,
        original_filename=file.filename or "uploaded-workbook.xlsx",
        approval_date=approval_date,
        job_dir=job_dir,
        upload_path=upload_path,
    )
    job_store.mark_step_running(job_id, "upload_received", "Workbook uploaded")
    job_store.mark_step_completed(job_id, "upload_received", "Upload stored securely")

    background_tasks.add_task(run_processing_job, job_id, upload_path, approval_date, job_dir)
    return CreateJobResponse(job_id=job_id, status="queued")


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    try:
        return job_store.snapshot(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Job not found") from error


@app.get("/api/jobs/{job_id}/download")
def download_job(job_id: str) -> FileResponse:
    try:
        snapshot = job_store.snapshot(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Job not found") from error

    package_path = job_store.get_package_path(job_id)
    if snapshot.status != "succeeded" or package_path is None or not package_path.exists():
        raise HTTPException(status_code=409, detail="ZIP package is not ready yet")

    filename = f"penalty_automation_{snapshot.approval_date}.zip"
    return FileResponse(package_path, media_type="application/zip", filename=filename)


@app.get("/api/jobs/{job_id}/final-output/download")
def download_final_output(job_id: str) -> FileResponse:
    try:
        snapshot = job_store.snapshot(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Job not found") from error

    final_output_path = job_store.get_final_output_path(job_id)
    if snapshot.status != "succeeded" or final_output_path is None or not final_output_path.exists():
        raise HTTPException(status_code=409, detail="Final output is not ready yet")

    return FileResponse(
        final_output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=snapshot.final_output.filename if snapshot.final_output else "final_output.xlsx",
    )


@app.get("/api/jobs/{job_id}/final-output/preview", response_model=FinalOutputPreviewResponse)
def preview_final_output(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> FinalOutputPreviewResponse:
    try:
        snapshot = job_store.snapshot(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Job not found") from error

    final_output_path = job_store.get_final_output_path(job_id)
    if snapshot.status != "succeeded" or final_output_path is None or not final_output_path.exists():
        raise HTTPException(status_code=409, detail="Final output is not ready yet")

    return read_final_output_preview(final_output_path, page=page, page_size=page_size)


async def run_processing_job(job_id: str, upload_path: Path, approval_date: str, job_dir: Path) -> None:
    try:
        result = await process_uploaded_workbook_async(
            input_path=upload_path,
            tracking_json_path=TRACKING_JSON_PATH,
            output_package_path=job_dir / "penalty_automation_package.zip",
            approval_date=approval_date,
            on_step_start=lambda step_id, message: job_store.mark_step_running(job_id, step_id, message),
            on_step_complete=lambda step_id, message: job_store.mark_step_completed(job_id, step_id, message),
            on_warning=lambda warning: job_store.add_warning(job_id, warning),
            on_step_progress=lambda step_id, completed_units, total_units, message: job_store.update_step_units(
                job_id,
                step_id,
                completed_units=completed_units,
                total_units=total_units,
                message=message,
            ),
            on_category_progress_initialized=lambda categories: job_store.initialize_category_progress(
                job_id,
                categories,
            ),
            on_category_progress=lambda slug, update: job_store.update_category_progress(job_id, slug, **update),
        )
        job_store.complete_job(
            job_id,
            metrics=result.metrics,
            category_outputs=result.category_outputs,
            package_path=result.package_path,
            final_output_path=result.final_output_path,
            final_output=result.final_output,
        )
    except Exception as error:
        job_store.fail_job(job_id, str(error))


def validate_approval_date(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise HTTPException(status_code=422, detail="approval_date must be in YYYY-MM-DD format") from error


def validate_upload(file: UploadFile) -> None:
    filename = file.filename or ""
    if Path(filename).suffix.lower() not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Upload a QlikSense Excel workbook (.xlsx or .xls)")


def read_final_output_preview(path: Path, *, page: int, page_size: int) -> FinalOutputPreviewResponse:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        row_count = max((worksheet.max_row or 1) - 1, 0)
        total_pages = max(1, ceil(row_count / page_size))
        safe_page = min(page, total_pages)
        start_index = (safe_page - 1) * page_size
        end_index = start_index + page_size

        worksheet_rows = worksheet.iter_rows(values_only=True)
        columns = [str(column or "") for column in next(worksheet_rows, ())]
        rows: list[dict[str, Any]] = []

        for row_index, values in enumerate(worksheet_rows):
            if row_index < start_index:
                continue
            if row_index >= end_index:
                break
            rows.append(
                {
                    column: serialize_preview_cell(values[column_index] if column_index < len(values) else None)
                    for column_index, column in enumerate(columns)
                }
            )

        return FinalOutputPreviewResponse(
            columns=columns,
            rows=rows,
            row_count=row_count,
            page=safe_page,
            page_size=page_size,
            total_pages=total_pages,
        )
    finally:
        workbook.close()


def serialize_preview_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return value
