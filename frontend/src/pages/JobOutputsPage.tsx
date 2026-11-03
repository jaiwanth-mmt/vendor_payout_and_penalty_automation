/**
 * JobOutputsPage — vendor mailer + final XLSX + category Excel previews/downloads.
 */
import { Package } from "lucide-react";
import { Link } from "react-router-dom";

import CategoryPreview from "../components/CategoryPreview";
import FinalOutputPreview from "../components/FinalOutputPreview";
import VendorMailerPanel from "../components/VendorMailerPanel";
import { useJob } from "../context/JobProvider";

export default function JobOutputsPage() {
  const {
    jobId,
    job,
    isComplete,
    downloadFinalOutput,
    downloadCategoryOutputs,
  } = useJob();

  if (!isComplete) {
    return (
      <div className="pageEmptySurface emptyState" role="status">
        <Package size={22} />
        <div>
          <strong>Outputs unlock after approving edits</strong>
          <p>
            Complete your review in Edit and approve to generate the final Excel files and vendor emails.
          </p>
        </div>
        <Link className="ghostButton" to={`/jobs/${jobId}/edit`}>
          Back to edit
        </Link>
      </div>
    );
  }

  return (
    <div className="outputsPage">
      {jobId ? <VendorMailerPanel jobId={jobId} isComplete={isComplete} /> : null}
      <FinalOutputPreview job={job} isComplete={isComplete} onDownload={downloadFinalOutput} />
      <CategoryPreview job={job} isComplete={isComplete} onDownload={downloadCategoryOutputs} />
    </div>
  );
}
