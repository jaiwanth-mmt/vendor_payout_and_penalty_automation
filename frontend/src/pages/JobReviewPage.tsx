/**
 * JobReviewPage — AgentCockpit HITL / case workspace for /jobs/:jobId/review.
 */
import { ArrowRight, Clock3, Package } from "lucide-react";
import { Link } from "react-router-dom";

import AgentCockpit from "../components/agent";
import { useJob } from "../context/JobProvider";

export default function JobReviewPage() {
  const {
    jobId,
    job,
    showAgentWorkspace,
    isAwaitingReview,
    isComplete,
    downloadAgentAudit,
    downloadReviewQueue,
    refreshJob,
  } = useJob();

  if (!showAgentWorkspace) {
    return (
      <div className="pageEmptySurface emptyState" role="status">
        <Clock3 size={22} />
        <div>
          <strong>Review unlocks after investigation</strong>
          <p>Cases and HITL appear once the job reaches awaiting review or succeeds.</p>
        </div>
        <Link className="ghostButton" to={`/jobs/${jobId}`}>
          Back to progress
        </Link>
      </div>
    );
  }

  return (
    <div className="reviewPage">
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
      <AgentCockpit
        job={job}
        isWorkspaceReady={showAgentWorkspace}
        isAwaitingReview={isAwaitingReview}
        onDownloadAgentAudit={downloadAgentAudit}
        onDownloadReviewQueue={downloadReviewQueue}
        onRefreshJob={refreshJob}
        showDownloadActions={isComplete}
      />
    </div>
  );
}
