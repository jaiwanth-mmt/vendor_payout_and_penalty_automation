import { Activity } from "lucide-react";

import CategoryPreview from "./components/CategoryPreview";
import FinalOutputPreview from "./components/FinalOutputPreview";
import ProcessingTimeline from "./components/ProcessingTimeline";
import UploadPanel from "./components/UploadPanel";
import { usePenaltyJob } from "./hooks/usePenaltyJob";

function App() {
  const {
    selectedFile,
    setSelectedFile,
    approvalDate,
    setApprovalDate,
    job,
    isProcessing,
    isComplete,
    hasFailed,
    error,
    setError,
    visibleMetrics,
    submitJob,
    downloadPackage,
    downloadFinalOutput
  } = usePenaltyJob();

  function handleFileSelect(file: File | null) {
    setSelectedFile(file);
    setError(null);
  }

  return (
    <main className="appShell">
      <header className="topbar">
        <div className="brandLockup">
          <div className="brandMark" aria-hidden="true">
            <span />
            <span />
          </div>
          <div>
            <p className="eyebrow">MakeMyTrip cab ops</p>
            <h1>Penalty Automation</h1>
          </div>
        </div>
        <div className="statusPill" data-state={job?.status ?? "idle"}>
          <Activity size={16} />
          <span>{job?.status ?? "ready"}</span>
        </div>
      </header>

      <section className="workspace">
        <UploadPanel
          selectedFile={selectedFile}
          approvalDate={approvalDate}
          isProcessing={isProcessing}
          error={error}
          onFileSelect={handleFileSelect}
          onApprovalDateChange={setApprovalDate}
          onSubmit={submitJob}
        />
        <ProcessingTimeline
          job={job}
          visibleMetrics={visibleMetrics}
          hasFailed={hasFailed}
          onDownload={downloadPackage}
        />
      </section>

      <FinalOutputPreview job={job} isComplete={isComplete} onDownload={downloadFinalOutput} />
      <CategoryPreview job={job} isComplete={isComplete} />
    </main>
  );
}

export default App;
