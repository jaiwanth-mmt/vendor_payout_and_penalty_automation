import { AlertTriangle, CheckCircle2, ListChecks, LoaderCircle, Table2, XCircle } from "lucide-react";
import { useState } from "react";

import type {
  CabDelayProgress,
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

const NODE_LABELS: Record<string, string> = {
  intake: "Intake",
  evidence_agent: "Evidence",
  specialist: "Specialist",
  judge: "Judge",
  human_review: "Human review",
  finalize: "Finalize",
  portfolio_summary: "Portfolio",
  vendor_penalty_analysis: "Vendor analysis",
};

function ProcessingTimeline({
  job,
  visibleMetrics,
  graphEvents = [],
  hasFailed,
}: ProcessingTimelineProps) {
  const summary = job?.investigation_summary ?? null;
  const technicalEvents = graphEvents.length ? graphEvents : job?.graph_events ?? [];

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
              "Investigation complete — open Edit to check booking details before analysis."}
          </span>
        </div>
      )}

      {job?.status === "awaiting_review" && (
        <div className="statusCallout" data-status="warning">
          <AlertTriangle size={18} />
          <span>
            {summary?.status_line ||
              `Paused for human review on ${job.pending_interrupts?.length ?? 0} booking(s).`}
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

      {technicalEvents.length > 0 && <TechnicalEventDetails events={technicalEvents} />}

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
          <h3>Investigation progress</h3>
          <p>{summary.status_line || "Preparing investigation"}</p>
        </div>
        <strong>
          {summary.cases_finalized}/{summary.total_cases || summary.cases_seen || 0}
        </strong>
      </div>
      <div className="investigationStageList">
        {summary.stages.map((stage) => (
          <div className="investigationStage" data-status={stage.status} key={stage.id}>
            <div className="investigationStageTop">
              <span>{stage.label}</span>
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
          {summary.pending_review} booking{summary.pending_review === 1 ? "" : "s"} waiting for human review
        </p>
      )}
    </div>
  );
}

function TechnicalEventDetails({ events }: { events: GraphEvent[] }) {
  const [open, setOpen] = useState(false);
  const recent = events.slice(-20).reverse();

  return (
    <details
      className="technicalEventDetails"
      open={open}
      onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}
    >
      <summary>Technical event log</summary>
      <p className="technicalEventHint">Raw LangGraph telemetry for debugging. Hidden from the main progress view.</p>
      <ul>
        {recent.map((event, index) => (
          <li key={`${event.node ?? "event"}-${event.booking_id ?? ""}-${index}-${event.status ?? ""}`}>
            <strong>{humanEventTitle(event)}</strong>
            <p>{humanEventBody(event)}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}

function humanEventTitle(event: GraphEvent): string {
  const nodeLabel = NODE_LABELS[event.node ?? ""] || event.node || "Graph";
  if (event.type === "tool") {
    return `${nodeLabel} · ${event.tool || "tool"}`;
  }
  if (event.type === "interrupt") {
    return `${nodeLabel} · needs review`;
  }
  return nodeLabel;
}

function humanEventBody(event: GraphEvent): string {
  const parts = [
    event.summary || event.status || "",
    event.booking_id ? `Booking ${event.booking_id}` : "",
  ].filter(Boolean);
  return parts.join(" · ");
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
              {category.cab_delay && <CabDelayCounters counters={category.cab_delay} />}
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

function CabDelayCounters({ counters }: { counters: CabDelayProgress }) {
  const insightDone = counters.generated_insight_rows + counters.failed_insight_rows;
  const summaryDone = counters.generated_comment_summary_rows + counters.failed_comment_summary_rows;
  return (
    <div className="cabDelayCounters">
      <span>
        Insights {insightDone}/{counters.target_insight_rows}
      </span>
      <span>
        Summaries {summaryDone}/{counters.target_comment_summary_rows}
      </span>
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
