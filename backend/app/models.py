from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


StepStatus = Literal["pending", "running", "completed", "failed"]
JobStatus = Literal["queued", "running", "succeeded", "failed"]


class StepState(BaseModel):
    id: str
    label: str
    status: StepStatus = "pending"
    message: str = ""
    completed_units: int = 0
    total_units: int = 0
    started_at: str | None = None
    completed_at: str | None = None


class WarningItem(BaseModel):
    code: str
    message: str
    booking_ids: list[str] = Field(default_factory=list)


class CategoryOutput(BaseModel):
    name: str
    slug: str
    row_count: int
    output_columns: list[str] = Field(default_factory=list)
    prepared_filename: str
    processed_filename: str
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)
    status: StepStatus = "completed"
    error: str | None = None


class FinalOutputSummary(BaseModel):
    filename: str
    row_count: int
    columns: list[str] = Field(default_factory=list)
    download_ready: bool = False


class FinalOutputPreviewResponse(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int
    page: int
    page_size: int
    total_pages: int


class CabDelayProgress(BaseModel):
    target_insight_rows: int = 0
    generated_insight_rows: int = 0
    failed_insight_rows: int = 0
    target_comment_summary_rows: int = 0
    generated_comment_summary_rows: int = 0
    failed_comment_summary_rows: int = 0


class CategoryProgress(BaseModel):
    name: str
    slug: str
    row_count: int
    status: StepStatus = "pending"
    message: str = "Pending"
    started_at: str | None = None
    completed_at: str | None = None
    cab_delay: CabDelayProgress | None = None


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    current_step: str | None = None
    original_filename: str
    approval_date: str
    created_at: str
    updated_at: str
    steps: list[StepState]
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[WarningItem] = Field(default_factory=list)
    category_progress: list[CategoryProgress] = Field(default_factory=list)
    category_outputs: list[CategoryOutput] = Field(default_factory=list)
    final_output: FinalOutputSummary | None = None
    download_ready: bool = False
    error: str | None = None


class CreateJobResponse(BaseModel):
    job_id: str
    status: JobStatus
