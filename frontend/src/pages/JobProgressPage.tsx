/**
 * JobProgressPage — pipeline timeline, metrics, SSE log + soft CTAs to Review/Outputs.
 */
import { ArrowRight, ClipboardList, Package } from "lucide-react";
import { Link } from "react-router-dom";

import ProcessingTimeline from "../components/ProcessingTimeline";
import { useJob } from "../context/JobProvider";

export default function JobProgressPage() {
  const {
    jobId,
    job,
    visibleMetrics,
    graphEvents,
    hasFailed,
    isAwaitingReview,
    isComplete,
    showAgentWorkspace,
  } = useJob();

  const pendingCount = job?.pending_interrupts?.length ?? 0;
  const needsReviewCount = Number(job?.case_counts?.needs_review ?? pendingCount);

  return (
    <div className="progressPage">
      {isAwaitingReview && showAgentWorkspace && (
        <div className="stageCta" data-tone="warning">
          <div>
            <strong>Human review needed</strong>
            <p>
              {needsReviewCount > 0
                ? `${needsReviewCount} case${needsReviewCount === 1 ? "" : "s"} awaiting Approve / Keep review.`
                : "Investigation paused for human review."}
            </p>
          </div>
          <Link className="primaryButton" to={`/jobs/${jobId}/review`}>
            <ClipboardList size={17} />
            <span>Open review</span>
            <ArrowRight size={16} />
          </Link>
        </div>
      )}

      {isComplete && (
        <div className="stageCta" data-tone="success">
          <div>
            <strong>Investigation complete</strong>
            <p>Final XLSX and category Excels are ready to preview and download.</p>
          </div>
          <Link className="primaryButton" to={`/jobs/${jobId}/outputs`}>
            <Package size={17} />
            <span>Open outputs</span>
            <ArrowRight size={16} />
          </Link>
        </div>
      )}

      <ProcessingTimeline
        job={job}
        visibleMetrics={visibleMetrics}
        graphEvents={graphEvents}
        hasFailed={hasFailed}
      />
    </div>
  );
}
