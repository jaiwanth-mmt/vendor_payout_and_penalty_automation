export type StepStatus = "pending" | "running" | "completed" | "warning" | "failed";
export type JobStatus = "queued" | "running" | "succeeded" | "failed";

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

export type AgentSummary = {
  executive_summary: string;
  case_counts: Record<string, number>;
  total_recoverable_amount: number;
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
  specialist_decision: AgentDecision | null;
  judge_decision: AgentDecision | null;
  final_decision: AgentDecision | null;
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

export type CabDelayProgress = {
  target_insight_rows: number;
  generated_insight_rows: number;
  failed_insight_rows: number;
  target_comment_summary_rows: number;
  generated_comment_summary_rows: number;
  failed_comment_summary_rows: number;
};

export type CategoryProgress = {
  name: string;
  slug: string;
  row_count: number;
  status: StepStatus;
  message: string;
  started_at: string | null;
  completed_at: string | null;
  cab_delay: CabDelayProgress | null;
};

export type JobResponse = {
  job_id: string;
  status: JobStatus;
  current_step: string | null;
  original_filename: string;
  approval_date: string;
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
