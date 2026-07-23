/**
 * NewJobPage — upload + approval date range (or entire workbook), then navigate to /jobs/:id.
 * Two top-aligned surfaces in the same .workspace grid as Progress.
 */
import { ClipboardCheck, FileSpreadsheet, Package, Radar, Sparkles } from "lucide-react";

import UploadPanel from "../components/UploadPanel";
import { useCreateJob } from "../hooks/useCreateJob";

const NEXT_STEPS = [
  {
    icon: FileSpreadsheet,
    title: "Filter & prepare",
    body: "Approval date range (or whole sheet), CARBD, recoverable amount, and Booking ID dedupe.",
  },
  {
    icon: Radar,
    title: "Live enrichment",
    body: "Tracking, vendor names, call comments, and subcategory processors.",
  },
  {
    icon: Sparkles,
    title: "Investigate & edit",
    body: "Agents investigate each booking, then you check and fix details before analysis.",
  },
  {
    icon: Package,
    title: "Review & outputs",
    body: "Top vendors and totals, then Final XLSX, category Excels, and audit package.",
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
    processAll,
    setProcessAll,
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
        <p>Upload a QlikSense workbook, then filter by approval date or process the whole sheet.</p>
      </header>

      <div className="workspace newJobWorkspace">
        <UploadPanel
          selectedFile={selectedFile}
          startDate={startDate}
          endDate={endDate}
          processAll={processAll}
          isProcessing={isSubmitting}
          error={error}
          onFileSelect={handleFileSelect}
          onStartDateChange={setStartDate}
          onEndDateChange={setEndDate}
          onProcessAllChange={setProcessAll}
          onSubmit={submitJob}
        />

        <aside className="processSurface newJobGuide" aria-label="What happens next">
          <div className="surfaceHeader processHeader">
            <div className="previewTitle">
              <ClipboardCheck size={22} />
              <div>
                <h2>What happens next</h2>
                <p>Same path as Progress · Edit · Review · Outputs</p>
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
