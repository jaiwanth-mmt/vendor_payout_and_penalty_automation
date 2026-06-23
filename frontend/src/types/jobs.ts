export type StepStatus = "pending" | "running" | "completed" | "failed";
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
  preview_rows: PreviewRow[];
  status: StepStatus;
  error: string | null;
};

export type FinalOutputSummary = {
  filename: string;
  row_count: number;
  columns: string[];
  download_ready: boolean;
};

export type FinalOutputPreviewResponse = {
  columns: string[];
  rows: PreviewRow[];
  row_count: number;
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
