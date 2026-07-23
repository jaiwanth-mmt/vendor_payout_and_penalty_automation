export type StepStatus = "pending" | "running" | "completed" | "warning" | "failed";
export type JobStatus = "queued" | "running" | "awaiting_edit" | "awaiting_review" | "succeeded" | "failed";
export type EditOutcome = "include" | "needs_ops" | "exclude";
export type AiBucket = "needs_check" | "auto_approved" | "unhandled";

export type StepState = {
  id: string;
  label: string;
  status: StepStatus;
  message: string;
  completed_units: number;
  total_units: number;
  started_at: string | null;
  completed_at: string | null;
};

export type WarningItem = {
  code: string;
  message: string;
  booking_ids: string[];
};

export type PreviewRow = Record<string, string | number | null>;

export type CategoryOutput = {
  name: string;
  slug: string;
  row_count: number;
  output_columns: string[];
  prepared_filename: string;
  processed_filename: string;
  status: StepStatus;
  error: string | null;
};

export type FinalOutputSummary = {
  filename: string;
  row_count: number;
  columns: string[];
  download_ready: boolean;
};

export type ReviewQueueItem = {
  booking_id: string;
  sub_category: string;
  message: string;
  recoverable_amount: number;
  review_status: string;
  decision: string;
  confidence: number;
  recommended_action: string;
  review_reason: string;
  rationale: string;
  source_used: string;
  source_categories: string;
  row_categories: string;
  source_alignment_status: string;
  source_alignment_reason: string;
  evidence_ids: string;
};

export type AgentProgressItem = {
  agent: string;
  status: StepStatus;
  completed_units: number;
  total_units: number;
  message: string;
};

export type InvestigationStageProgress = {
  id: string;
  label: string;
  completed_units: number;
  total_units: number;
  status: StepStatus;
};

export type InvestigationSummary = {
  total_cases: number;
  cases_seen: number;
  cases_finalized: number;
  pending_review: number;
  status_line: string;
  stages: InvestigationStageProgress[];
};

export type GraphEvent = {
  type: string;
  node?: string;
  booking_id?: string;
  status?: string;
  summary?: string;
  tool?: string;
  thread_id?: string;
  job_id?: string;
  payload?: Record<string, unknown>;
};

export type PendingInterrupt = {
  booking_id: string;
  thread_id: string;
  payload: Record<string, unknown>;
};

export type GraphTopology = {
  case: { nodes: string[]; mermaid: string };
  portfolio: { nodes: string[]; mermaid: string };
};

export type ToolCallRecord = {
  name: string;
  status: string;
  summary: string;
  result?: Record<string, unknown>;
};

export type AgentSummary = {
  executive_summary: string;
  case_counts: Record<string, number>;
  total_recoverable_amount: number;
  high_confidence_case_count: number;
  high_confidence_recoverable_amount: number;
  top_complaint_drivers: string[];
  category_breakdown: Array<Record<string, string | number>>;
  top_vendors_by_penalty: Array<{
    vendor_name: string;
    case_count: number;
    total_recoverable: number;
    top_subcategories: VendorSubcategorySummary[];
  }>;
  top_subcategories_by_penalty: VendorSubcategorySummary[];
  top_subcategories_by_count: VendorSubcategorySummary[];
  missing_data_hotspots: string[];
  recommended_actions: string[];
  edited_case_count?: number;
  excluded_case_count?: number;
  needs_check_count?: number;
  auto_approved_count?: number;
  unhandled_count?: number;
};

export type VendorSubcategorySummary = {
  subcategory: string;
  case_count: number;
  total_recoverable: number;
};

export type EvidenceItem = {
  id: string;
  title: string;
  source: string;
  status: string;
  summary: string;
  fields: Record<string, string | number | boolean | null | string[]>;
  error: string | null;
};

export type AgentTraceStep = {
  agent: string;
  action: string;
  status: string;
  summary: string;
  evidence_ids: string[];
  metadata: Record<string, string | number | boolean | null | string[]>;
};

export type AgentDecision = {
  agent: string;
  decision: string;
  decision_source: "llm" | "fallback";
  complaint_categories: string[];
  confidence: number;
  recommended_recovery_amount: number;
  rationale: string;
  recommended_action: string;
  review_status: string;
  review_reason: string;
  evidence_ids: string[];
  llm_error: string | null;
};

export type SourceAnalysis = {
  primary_source: string;
  source_label: string;
  source_text: string;
  source_evidence_id: string;
  source_categories: string[];
  row_categories: string[];
  comments_categories: string[];
  remarks_categories: string[];
  sub_category_categories: string[];
  mentioned_booking_ids: string[];
  status: string;
  review_status: string;
  reason: string;
  message: string;
};

export type AgentCase = {
  booking_id: string;
  sub_category: string;
  remarks: string;
  comments: string;
  vendor_name: string;
  recoverable_amount: number;
  row_index: number;
  message: string;
  source_analysis: SourceAnalysis;
  review_status: string;
  evidence: EvidenceItem[];
  trace: AgentTraceStep[];
  tool_calls?: ToolCallRecord[];
  pending_interrupt?: boolean;
  specialist_decision: AgentDecision | null;
  judge_decision: AgentDecision | null;
  final_decision: AgentDecision | null;
  ai_bucket?: AiBucket;
  ai_review_status?: string;
  edit_outcome?: EditOutcome;
  was_edited?: boolean;
  edited_fields?: string[];
  excluded?: boolean;
};

export type AgentCasesResponse = {
  cases: AgentCase[];
  case_count: number;
  page: number;
  page_size: number;
  total_pages: number;
};

export type FinalOutputPreviewResponse = {
  columns: string[];
  rows: PreviewRow[];
  row_count: number;
  page: number;
  page_size: number;
  total_pages: number;
};

export type CategoryPreviewResponse = FinalOutputPreviewResponse;

export type ReviewQueuePageResponse = {
  items: ReviewQueueItem[];
  item_count: number;
  page: number;
  page_size: number;
  total_pages: number;
};

export type CategoryProgress = {
  name: string;
  slug: string;
  row_count: number;
  status: StepStatus;
  message: string;
  started_at: string | null;
  completed_at: string | null;
};

export type JobResponse = {
  job_id: string;
  status: JobStatus;
  current_step: string | null;
  original_filename: string;
  start_date: string;
  end_date: string;
  process_all: boolean;
  created_at: string;
  updated_at: string;
  steps: StepState[];
  metrics: Record<string, number | string>;
  warnings: WarningItem[];
  category_progress: CategoryProgress[];
  category_outputs: CategoryOutput[];
  final_output: FinalOutputSummary | null;
  agent_summary: AgentSummary | null;
  case_counts: Record<string, number>;
  agent_progress: AgentProgressItem[];
  investigation_summary: InvestigationSummary | null;
  graph_events: GraphEvent[];
  pending_interrupts: PendingInterrupt[];
  graph_topology: GraphTopology | null;
  download_ready: boolean;
  error: string | null;
};

export type CreateJobResponse = {
  job_id: string;
  status: JobStatus;
};

export type VisibleMetric = {
  key: string;
  label: string;
  value: number | string;
};

export type ResumeCaseRequest = {
  decision: string;
  review_status: string;
  recommended_recovery_amount?: number;
  review_reason?: string;
  rationale?: string;
  recommended_action?: string;
};

export type EditCaseItem = {
  booking_id: string;
  comments: string;
  recoverable_amount: number;
  message: string;
  remarks: string;
  sub_category: string;
  vendor_name: string;
  ai_bucket: AiBucket;
  ai_review_status: string;
  edit_outcome: EditOutcome;
  was_edited: boolean;
  edited_fields: string[];
  review_reason: string;
  excluded: boolean;
};

export type EditCasesPageResponse = {
  cases: EditCaseItem[];
  case_count: number;
  page: number;
  page_size: number;
  total_pages: number;
  needs_check_count: number;
  auto_approved_count: number;
  unhandled_count: number;
  edited_case_count: number;
  excluded_case_count: number;
  available_sub_categories: string[];
};

export type PatchEditCaseRequest = {
  recoverable_amount?: number;
  message?: string;
  remarks?: string;
  sub_category?: string;
  edit_outcome?: EditOutcome;
};
