/**
 * NewJobPage — upload + date range, then navigate to /jobs/:id.
 * Two top-aligned surfaces in the same .workspace grid as Progress.
 */
import { ClipboardCheck, FileSpreadsheet, Package, Radar, Sparkles } from "lucide-react";

import UploadPanel from "../components/UploadPanel";
import { useCreateJob } from "../hooks/useCreateJob";

const NEXT_STEPS = [
  {
    icon: FileSpreadsheet,
    title: "Filter & prepare",
    body: "Approval date range, CARBD, recoverable amount, and Booking ID dedupe.",
  },
  {
    icon: Radar,
    title: "Live enrichment",
    body: "Tracking, vendor names, call comments, and subcategory processors.",
  },
  {
    icon: Sparkles,
    title: "LangGraph investigation",
    body: "Evidence tools, specialist, judge, and human review when needed.",
  },
  {
    icon: Package,
    title: "Outputs",
    body: "Final XLSX, category Excels, review queue, and agent audit package.",
  },
] as const;

export default function NewJobPage() {
  const {
    selectedFile,
    setSelectedFile,
    startDate,
    setStartDate,
    endDate,
    setEndDate,
    isSubmitting,
    error,
    setError,
    submitJob,
  } = useCreateJob();

  function handleFileSelect(file: File | null) {
    setSelectedFile(file);
    setError(null);
  }

  return (
    <div className="pageFrame">
      <header className="newJobPageHeader">
        <h2>Start a recovery run</h2>
        <p>Upload a QlikSense workbook and approval date range to begin.</p>
      </header>

      <div className="workspace newJobWorkspace">
        <UploadPanel
          selectedFile={selectedFile}
          startDate={startDate}
          endDate={endDate}
          isProcessing={isSubmitting}
          error={error}
          onFileSelect={handleFileSelect}
          onStartDateChange={setStartDate}
          onEndDateChange={setEndDate}
          onSubmit={submitJob}
        />

        <aside className="processSurface newJobGuide" aria-label="What happens next">
          <div className="surfaceHeader processHeader">
            <div className="previewTitle">
              <ClipboardCheck size={22} />
              <div>
                <h2>What happens next</h2>
                <p>Same path as Progress · Review · Outputs</p>
              </div>
            </div>
          </div>
          <ol className="newJobStepList">
            {NEXT_STEPS.map((step) => {
              const Icon = step.icon;
              return (
                <li className="newJobStep" key={step.title}>
                  <span className="newJobStepIcon" aria-hidden="true">
                    <Icon size={18} />
                  </span>
                  <div>
                    <strong>{step.title}</strong>
                    <p>{step.body}</p>
                  </div>
                </li>
              );
            })}
          </ol>
        </aside>
      </div>
    </div>
  );
}
