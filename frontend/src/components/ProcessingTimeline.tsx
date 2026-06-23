import { CheckCircle2, Download, LoaderCircle, Table2, XCircle } from "lucide-react";

import type { CabDelayProgress, CategoryProgress, JobResponse, StepState, StepStatus, VisibleMetric } from "../types/jobs";
import MetricsGrid from "./MetricsGrid";
import WarningsList from "./WarningsList";

type ProcessingTimelineProps = {
  job: JobResponse | null;
  visibleMetrics: VisibleMetric[];
  hasFailed: boolean;
  onDownload: () => void;
};

function ProcessingTimeline({ job, visibleMetrics, hasFailed, onDownload }: ProcessingTimelineProps) {
  return (
    <section className="processSurface">
      <div className="surfaceHeader processHeader">
        <div>
          <h2>Processing timeline</h2>
          <p>{job ? job.original_filename : "Awaiting workbook"}</p>
        </div>
        <button className="ghostButton" type="button" disabled={!job?.download_ready} onClick={onDownload}>
          <Download size={18} />
          <span>Download ZIP</span>
        </button>
      </div>

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
  if (status === "failed") return <XCircle size={18} />;
  return <span className="pendingDot" aria-hidden="true" />;
}

export default ProcessingTimeline;
