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
    body: "Filter approved bookings, drop cancellations and customer refunds, and remove duplicates.",
  },
  {
    icon: Radar,
    title: "Live data check",
    body: "Fetch live cab tracking, vendor details, and trip information.",
  },
  {
    icon: Sparkles,
    title: "Review & edit",
    body: "Automated checks verify each booking, then you can review and adjust fines before approval.",
  },
  {
    icon: Package,
    title: "Analysis & exports",
    body: "Review vendor penalty breakdown, download Excel reports, and email vendors.",
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

        <aside className="processSurface newJobGuide" aria-label="Workflow overview">
          <div className="surfaceHeader processHeader">
            <div className="previewTitle">
              <ClipboardCheck size={22} />
              <div>
                <h2>Workflow overview</h2>
                <p>Progress → Edit → Review → Outputs</p>
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
