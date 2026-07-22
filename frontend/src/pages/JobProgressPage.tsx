/**
 * JobProgressPage — pipeline timeline, metrics, SSE log + soft CTAs to Edit/Outputs.
 */
import { ArrowRight, Package, PencilLine } from "lucide-react";
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
    isAwaitingEdit,
    isComplete,
    showEditWorkspace,
  } = useJob();

  const needsCheckCount = Number(job?.metrics?.needs_check_count ?? 0);
  const totalCases = Number(job?.case_counts?.total_cases ?? job?.metrics?.agent_total_cases ?? 0);

  return (
    <div className="progressPage">
      {isAwaitingEdit && showEditWorkspace && (
        <div className="stageCta" data-tone="warning">
          <div>
            <strong>Ready for edits</strong>
            <p>
              {totalCases > 0
                ? `${totalCases} booking${totalCases === 1 ? "" : "s"} ready to check${
                    needsCheckCount > 0 ? ` (${needsCheckCount} need your check)` : ""
                  }.`
                : "Investigation finished — open Edit to review booking details."}
            </p>
          </div>
          <Link className="primaryButton" to={`/jobs/${jobId}/edit`}>
            <PencilLine size={17} />
            <span>Open edit</span>
            <ArrowRight size={16} />
          </Link>
        </div>
      )}

      {isComplete && (
        <div className="stageCta" data-tone="success">
          <div>
            <strong>Package ready</strong>
            <p>Final analysis and downloads are available.</p>
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
