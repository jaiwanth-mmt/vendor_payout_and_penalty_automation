/**
 * JobReviewPage — analysis cockpit after edits are approved (no HITL Approve/Keep).
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
          <strong>Review unlocks after you approve edits</strong>
          <p>Top vendors, totals, and case details appear once the recovery package is built.</p>
        </div>
        <Link className="ghostButton" to={`/jobs/${jobId}/edit`}>
          Back to edit
        </Link>
      </div>
    );
  }

  return (
    <div className="reviewPage">
      {isComplete && (
        <div className="stageCta" data-tone="success">
          <div>
            <strong>Analysis complete</strong>
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
        onDownloadAgentAudit={downloadAgentAudit}
        onDownloadReviewQueue={downloadReviewQueue}
        onRefreshJob={refreshJob}
        showDownloadActions={isComplete}
      />
    </div>
  );
}
