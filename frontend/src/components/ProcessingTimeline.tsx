import { AlertTriangle, CheckCircle2, ListChecks, LoaderCircle, Table2, XCircle } from "lucide-react";

import type {
  CategoryProgress,
  GraphEvent,
  InvestigationSummary,
  JobResponse,
  StepState,
  StepStatus,
  VisibleMetric,
} from "../types/jobs";
import MetricsGrid from "./MetricsGrid";
import WarningsList from "./WarningsList";

type ProcessingTimelineProps = {
  job: JobResponse | null;
  visibleMetrics: VisibleMetric[];
  graphEvents?: GraphEvent[];
  hasFailed: boolean;
};

const STAGE_LABELS: Record<string, string> = {
  intake: "Booking data intake",
  evidence_agent: "Tracking & trip check",
  specialist: "Policy & SOP evaluation",
  judge: "Quality & audit check",
  human_review: "Manual review",
  finalize: "Case finalization",
  portfolio_summary: "Recovery summary",
  vendor_penalty_analysis: "Vendor penalty analysis",
};

function ProcessingTimeline({
  job,
  visibleMetrics,
  hasFailed,
}: ProcessingTimelineProps) {
  const summary = job?.investigation_summary ?? null;

  return (
    <section className="processSurface">
      <div className="surfaceHeader processHeader">
        <div className="previewTitle">
          <ListChecks size={21} />
          <div>
            <h2>Processing timeline</h2>
            <p>{job ? job.original_filename : "Awaiting workbook"}</p>
          </div>
        </div>
      </div>

      {job?.status === "awaiting_edit" && (
        <div className="statusCallout" data-status="warning">
          <AlertTriangle size={18} />
          <span>
            {summary?.status_line ||
              "Automated checks complete — open Edit to review booking details before analysis."}
          </span>
        </div>
      )}

      {job?.status === "awaiting_review" && (
        <div className="statusCallout" data-status="warning">
          <AlertTriangle size={18} />
          <span>
            {summary?.status_line ||
              `Paused for manual review on ${job.pending_interrupts?.length ?? 0} booking(s).`}
          </span>
        </div>
      )}

      <div className="timeline">
        {(job?.steps ?? []).map((step) => (
          <div className="timelineStep" data-status={step.status} key={step.id}>
            <StepIcon status={step.status} />
            <div>
              <span>
                {step.label}
                {step.total_units > 0 && (
                  <strong className="stepCounter">
                    {step.completed_units}/{step.total_units}
                  </strong>
                )}
              </span>
              <p>{step.message || "Pending"}</p>
              <StepProgressBar step={step} />
            </div>
          </div>
        ))}
        {!job && (
          <div className="emptyState">
            <Table2 size={22} />
            <span>Processing stages will appear here</span>
          </div>
        )}
      </div>

      <InvestigationProgressPanel summary={summary} jobStatus={job?.status ?? null} />

      <CategoryProgressList categories={job?.category_progress ?? []} />
      <MetricsGrid metrics={visibleMetrics} />
      <WarningsList warnings={job?.warnings ?? []} />

      {hasFailed && (
        <div className="failureBlock">
          <XCircle size={18} />
          <span>{job?.error}</span>
        </div>
      )}
    </section>
  );
}

function InvestigationProgressPanel({
  summary,
  jobStatus,
}: {
  summary: InvestigationSummary | null;
  jobStatus: string | null;
}) {
  if (!summary || (!summary.total_cases && !summary.cases_seen && jobStatus === "queued")) {
    return null;
  }
  if (!summary.stages?.length && !summary.status_line) {
    return null;
  }

  const show =
    Boolean(summary.total_cases || summary.cases_seen || summary.status_line) &&
    (jobStatus === "running" ||
      jobStatus === "awaiting_edit" ||
      jobStatus === "awaiting_review" ||
      jobStatus === "succeeded" ||
      summary.cases_seen > 0);

  if (!show) return null;

  return (
    <div className="investigationProgressPanel">
      <div className="investigationProgressHeader">
        <div>
          <h3>Automated verification progress</h3>
          <p>{summary.status_line || "Checking booking details"}</p>
        </div>
        <strong>
          {summary.cases_finalized}/{summary.total_cases || summary.cases_seen || 0}
        </strong>
      </div>
      <div className="investigationStageList">
        {summary.stages.map((stage) => (
          <div className="investigationStage" data-status={stage.status} key={stage.id}>
            <div className="investigationStageTop">
              <span>{STAGE_LABELS[stage.id] || stage.label}</span>
              <em>
                {stage.total_units > 0
                  ? `${stage.completed_units}/${stage.total_units}`
                  : stage.status === "pending"
                    ? "—"
                    : "done"}
              </em>
            </div>
            <div className="investigationStageTrack" aria-hidden="true">
              <span
                style={{
                  width: `${
                    stage.total_units > 0
                      ? Math.min(100, Math.round((stage.completed_units / stage.total_units) * 100))
                      : stage.status === "completed"
                        ? 100
                        : 0
                  }%`,
                }}
              />
            </div>
          </div>
        ))}
      </div>
      {summary.pending_review > 0 && (
        <p className="investigationPendingNote">
          {summary.pending_review} booking{summary.pending_review === 1 ? "" : "s"} waiting for manual review
        </p>
      )}
    </div>
  );
}

function StepProgressBar({ step }: { step: StepState }) {
  if (!step.total_units) return null;
  const progress = Math.min(100, Math.round((step.completed_units / step.total_units) * 100));
  return (
    <div className="stepProgressTrack" aria-label={`${step.label} progress`}>
      <span style={{ width: `${progress}%` }} />
    </div>
  );
}

function CategoryProgressList({ categories }: { categories: CategoryProgress[] }) {
  if (!categories.length) return null;

  return (
    <div className="categoryProgressPanel">
      <div className="categoryProgressHeader">
        <span>Subcategory progress</span>
        <strong>
          {categories.filter((category) => category.status === "completed" || category.status === "failed").length}/
          {categories.length}
        </strong>
      </div>
      <div className="categoryProgressList">
        {categories.map((category) => (
          <div className="categoryProgressItem" data-status={category.status} key={category.slug}>
            <div>
              <span>{category.name}</span>
              <p>{category.message}</p>
            </div>
            <div className="categoryStatusBlock">
              <strong>{category.row_count}</strong>
              <em>{category.status}</em>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StepIcon({ status }: { status: StepStatus }) {
  if (status === "completed") return <CheckCircle2 size={18} />;
  if (status === "running") return <LoaderCircle className="spin" size={18} />;
  if (status === "warning") return <AlertTriangle size={18} />;
  if (status === "failed") return <XCircle size={18} />;
  return <span className="pendingDot" aria-hidden="true" />;
}

export default ProcessingTimeline;
