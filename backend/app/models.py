from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


StepStatus = Literal["pending", "running", "completed", "warning", "failed"]
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


class CategoryPreviewResponse(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int
    page: int
    page_size: int
    total_pages: int


class ReviewQueueItem(BaseModel):
    booking_id: str
    sub_category: str
    recoverable_amount: float | int
    review_status: str
    decision: str
    confidence: float | int
    recommended_action: str
    review_reason: str


class ReviewQueuePageResponse(BaseModel):
    items: list[ReviewQueueItem] = Field(default_factory=list)
    item_count: int
    page: int
    page_size: int
    total_pages: int


class AgentProgressItem(BaseModel):
    agent: str
    status: StepStatus
    completed_units: int = 0
    total_units: int = 0
    message: str = ""


class AgentSummary(BaseModel):
    executive_summary: str = ""
    case_counts: dict[str, int] = Field(default_factory=dict)
    total_recoverable_amount: float = 0
    high_confidence_recoverable_amount: float = 0
    top_complaint_drivers: list[str] = Field(default_factory=list)
    category_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    missing_data_hotspots: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class AgentCasesPageResponse(BaseModel):
    cases: list[dict[str, Any]] = Field(default_factory=list)
    case_count: int
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
    agent_summary: AgentSummary | None = None
    case_counts: dict[str, int] = Field(default_factory=dict)
    agent_progress: list[AgentProgressItem] = Field(default_factory=list)
    download_ready: bool = False
    error: str | None = None


class CreateJobResponse(BaseModel):
    job_id: str
    status: JobStatus
