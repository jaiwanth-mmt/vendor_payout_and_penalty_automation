/**
 * JobOutputsPage — final XLSX + category Excel previews/downloads.
 */
import { Package } from "lucide-react";
import { Link } from "react-router-dom";

import CategoryPreview from "../components/CategoryPreview";
import FinalOutputPreview from "../components/FinalOutputPreview";
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
          <strong>Outputs unlock when the job succeeds</strong>
          <p>
            Finish human review if needed. Packaging runs after investigation completes.
          </p>
        </div>
        <Link className="ghostButton" to={`/jobs/${jobId}`}>
          Back to progress
        </Link>
      </div>
    );
  }

  return (
    <div className="outputsPage">
      <FinalOutputPreview job={job} isComplete={isComplete} onDownload={downloadFinalOutput} />
      <CategoryPreview job={job} isComplete={isComplete} onDownload={downloadCategoryOutputs} />
    </div>
  );
}
