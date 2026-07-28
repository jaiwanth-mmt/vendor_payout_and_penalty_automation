from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


StepStatus = Literal["pending", "running", "completed", "warning", "failed"]
JobStatus = Literal["queued", "running", "awaiting_edit", "awaiting_review", "succeeded", "failed"]
EditOutcome = Literal["include", "needs_ops", "exclude"]
AiBucket = Literal["needs_check", "auto_approved", "unhandled"]


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
    message: str = ""
    recoverable_amount: float | int
    review_status: str
    decision: str
    confidence: float | int
    recommended_action: str
    review_reason: str
    rationale: str = ""
    source_used: str = ""
    source_categories: str = ""
    row_categories: str = ""
    source_alignment_status: str = ""
    source_alignment_reason: str = ""
    evidence_ids: str = ""


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


class InvestigationStageProgress(BaseModel):
    id: str
    label: str
    completed_units: int = 0
    total_units: int = 0
    status: StepStatus = "pending"


class InvestigationSummary(BaseModel):
    total_cases: int = 0
    cases_seen: int = 0
    cases_finalized: int = 0
    pending_review: int = 0
    status_line: str = ""
    stages: list[InvestigationStageProgress] = Field(default_factory=list)


class GraphEvent(BaseModel):
    type: str = ""
    node: str = ""
    booking_id: str = ""
    status: str = ""
    summary: str = ""
    tool: str | None = None
    thread_id: str | None = None
    job_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class PendingInterrupt(BaseModel):
    booking_id: str
    thread_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class GraphTopologyResponse(BaseModel):
    case: dict[str, Any] = Field(default_factory=dict)
    portfolio: dict[str, Any] = Field(default_factory=dict)
    mailer: dict[str, Any] = Field(default_factory=dict)


class ResumeCaseRequest(BaseModel):
    decision: str = "needs_review"
    review_status: str = "needs_review"
    recommended_recovery_amount: float | None = None
    review_reason: str = ""
    rationale: str = ""
    recommended_action: str = ""


class PatchEditCaseRequest(BaseModel):
    recoverable_amount: float | None = None
    message: str | None = None
    remarks: str | None = None
    sub_category: str | None = None
    edit_outcome: EditOutcome | None = None


class BulkPatchEditCasesRequest(BaseModel):
    bucket: AiBucket
    edit_outcome: EditOutcome
    booking_id: str | None = None
    sub_category: str | None = None


class EditCaseItem(BaseModel):
    booking_id: str
    comments: str = ""
    recoverable_amount: float = 0
    message: str = ""
    remarks: str = ""
    sub_category: str = ""
    vendor_name: str = ""
    amount: float | None = None
    ttrip_type: str = ""
    fine_before_sop: float | None = None
    fine_after_sop: float | None = None
    ai_bucket: AiBucket = "needs_check"
    ai_review_status: str = ""
    edit_outcome: EditOutcome = "needs_ops"
    was_edited: bool = False
    edited_fields: list[str] = Field(default_factory=list)
    review_reason: str = ""
    excluded: bool = False


class EditCasesPageResponse(BaseModel):
    cases: list[EditCaseItem] = Field(default_factory=list)
    case_count: int
    page: int
    page_size: int
    total_pages: int
    needs_check_count: int = 0
    auto_approved_count: int = 0
    unhandled_count: int = 0
    edited_case_count: int = 0
    excluded_case_count: int = 0
    available_sub_categories: list[str] = Field(default_factory=list)


class BulkPatchEditCasesResponse(BaseModel):
    updated_count: int
    needs_check_count: int = 0
    auto_approved_count: int = 0
    unhandled_count: int = 0
    edited_case_count: int = 0
    excluded_case_count: int = 0


class AgentSummary(BaseModel):
    executive_summary: str = ""
    case_counts: dict[str, int] = Field(default_factory=dict)
    total_recoverable_amount: float = 0
    high_confidence_case_count: int = 0
    high_confidence_recoverable_amount: float = 0
    top_complaint_drivers: list[str] = Field(default_factory=list)
    category_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    top_vendors_by_penalty: list[dict[str, Any]] = Field(default_factory=list)
    top_subcategories_by_penalty: list[dict[str, Any]] = Field(default_factory=list)
    top_subcategories_by_count: list[dict[str, Any]] = Field(default_factory=list)
    missing_data_hotspots: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    edited_case_count: int = 0
    excluded_case_count: int = 0
    needs_check_count: int = 0
    auto_approved_count: int = 0
    unhandled_count: int = 0


class AgentCasesPageResponse(BaseModel):
    cases: list[dict[str, Any]] = Field(default_factory=list)
    case_count: int
    page: int
    page_size: int
    total_pages: int


class CategoryProgress(BaseModel):
    name: str
    slug: str
    row_count: int
    status: StepStatus = "pending"
    message: str = "Pending"
    started_at: str | None = None
    completed_at: str | None = None


class LlmUsagePricing(BaseModel):
    input_usd_per_1m: float = 1.25
    output_usd_per_1m: float = 10.0
    cached_input_usd_per_1m: float = 0.13
    currency: str = "USD"


class LlmUsageTotals(BaseModel):
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class LlmUsageByPurpose(BaseModel):
    purpose: str
    label: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class LlmUsageSummary(BaseModel):
    model: str = "gpt-5"
    pricing: LlmUsagePricing = Field(default_factory=LlmUsagePricing)
    totals: LlmUsageTotals = Field(default_factory=LlmUsageTotals)
    by_purpose: list[LlmUsageByPurpose] = Field(default_factory=list)
    case_count: int = 0
    notes: list[str] = Field(default_factory=list)


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    current_step: str | None = None
    original_filename: str
    start_date: str
    end_date: str
    process_all: bool = False
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
    investigation_summary: InvestigationSummary | None = None
    graph_events: list[dict[str, Any]] = Field(default_factory=list)
    pending_interrupts: list[PendingInterrupt] = Field(default_factory=list)
    graph_topology: dict[str, Any] | None = None
    llm_usage: LlmUsageSummary | None = None
    download_ready: bool = False
    error: str | None = None


class CreateJobResponse(BaseModel):
    job_id: str
    status: JobStatus


MailerStatus = Literal["idle", "preview_ready", "sending", "sent", "partial", "failed"]


class MailerAssignment(BaseModel):
    recipient: str
    booking_id: str
    subject: str = ""


class MailerDraftField(BaseModel):
    key: str
    value: str = ""


class MailerDraft(BaseModel):
    recipient: str
    booking_id: str
    subject: str
    text_body: str = ""
    html_body: str = ""
    fields: list[MailerDraftField] = Field(default_factory=list)
    title: str = ""
    message: str = ""
    fine: str = ""
    call_transcript: str = ""


class MailerSendResult(BaseModel):
    recipient: str
    booking_id: str
    status: Literal["sent", "failed"]
    message_id: str | None = None
    smtp_response: str = ""
    error: str | None = None
    sent_at: str | None = None


class MailerDispatchResponse(BaseModel):
    status: MailerStatus = "idle"
    preview_token: str | None = None
    final_output_checksum: str | None = None
    recipients: list[str] = Field(default_factory=list)
    assignments: list[MailerAssignment] = Field(default_factory=list)
    drafts: list[MailerDraft] = Field(default_factory=list)
    results: list[MailerSendResult] = Field(default_factory=list)
    sent_at: str | None = None
    error: str | None = None
    can_send: bool = False


class SendVendorMailRequest(BaseModel):
    preview_token: str
