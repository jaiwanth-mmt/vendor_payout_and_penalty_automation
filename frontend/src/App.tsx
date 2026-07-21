import { Activity } from "lucide-react";

import AgentCockpit from "./components/AgentCockpit";
import CategoryPreview from "./components/CategoryPreview";
import FinalOutputPreview from "./components/FinalOutputPreview";
import ProcessingTimeline from "./components/ProcessingTimeline";
import UploadPanel from "./components/UploadPanel";
import { usePenaltyJob } from "./hooks/usePenaltyJob";

function App() {
  const {
    selectedFile,
    setSelectedFile,
    startDate,
    setStartDate,
    endDate,
    setEndDate,
    job,
    isProcessing,
    isComplete,
    isAwaitingReview,
    showAgentWorkspace,
    hasFailed,
    error,
    setError,
    visibleMetrics,
    graphEvents,
    submitJob,
    downloadPackage,
    downloadFinalOutput,
    downloadAgentAudit,
    downloadReviewQueue,
    refreshJob
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
            <h1>Agentic Loss Recovery Copilot</h1>
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
          startDate={startDate}
          endDate={endDate}
          isProcessing={isProcessing}
          error={error}
          onFileSelect={handleFileSelect}
          onStartDateChange={setStartDate}
          onEndDateChange={setEndDate}
          onSubmit={submitJob}
        />
        <ProcessingTimeline
          job={job}
          visibleMetrics={visibleMetrics}
          graphEvents={graphEvents}
          hasFailed={hasFailed}
          onDownload={downloadPackage}
        />
      </section>

      <AgentCockpit
        job={job}
        isComplete={showAgentWorkspace}
        isAwaitingReview={isAwaitingReview}
        onDownloadAgentAudit={downloadAgentAudit}
        onDownloadReviewQueue={downloadReviewQueue}
        onRefreshJob={refreshJob}
      />
      <FinalOutputPreview job={job} isComplete={isComplete} onDownload={downloadFinalOutput} />
      <CategoryPreview job={job} isComplete={isComplete} />
    </main>
  );
}

export default App;
