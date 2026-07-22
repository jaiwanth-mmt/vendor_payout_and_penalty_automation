/**
 * JobLayout — stage stepper (Progress · Review · Outputs) + status + child page outlet.
 * Locked stages use aria-disabled; soft unlock from job status flags via useJob().
 */
import { Activity, ArrowLeft } from "lucide-react";
import { Link, NavLink, Outlet } from "react-router-dom";

import { useJob } from "../context/JobProvider";

type StageKey = "progress" | "review" | "outputs";

function stageDisabledReason(
  key: StageKey,
  flags: { showAgentWorkspace: boolean; isComplete: boolean; hasFailed: boolean },
): string | null {
  if (key === "progress") return null;
  if (flags.hasFailed) return "Job failed — start a new job";
  if (key === "review" && !flags.showAgentWorkspace) {
    return "Available after investigation reaches review or completion";
  }
  if (key === "outputs" && !flags.isComplete) {
    return "Available after the job succeeds";
  }
  return null;
}

export default function JobLayout() {
  const {
    jobId,
    job,
    isLoading,
    error,
    isComplete,
    showAgentWorkspace,
    hasFailed,
  } = useJob();

  if (!jobId) {
    return (
      <div className="pageFrame">
        <div className="emptyState pageEmpty">
          <span>Missing job id</span>
          <Link className="ghostButton" to="/">
            New job
          </Link>
        </div>
      </div>
    );
  }

  if (isLoading && !job) {
    return (
      <div className="pageFrame">
        <div className="emptyState pageEmpty">
          <span>Loading job…</span>
        </div>
      </div>
    );
  }

  if (error && !job) {
    return (
      <div className="pageFrame">
        <div className="emptyState pageEmpty" role="alert">
          <span>{error}</span>
          <Link className="ghostButton" to="/">
            <ArrowLeft size={16} />
            <span>New job</span>
          </Link>
        </div>
      </div>
    );
  }

  const flags = { showAgentWorkspace, isComplete, hasFailed };
  const stages: { key: StageKey; label: string; to: string }[] = [
    { key: "progress", label: "Progress", to: `/jobs/${jobId}` },
    { key: "review", label: "Review", to: `/jobs/${jobId}/review` },
    { key: "outputs", label: "Outputs", to: `/jobs/${jobId}/outputs` },
  ];

  return (
    <div className="jobShell">
      <div className="jobStageBar">
        <nav className="jobStageNav" aria-label="Job stages">
          {stages.map((stage) => {
            const reason = stageDisabledReason(stage.key, flags);
            const locked = Boolean(reason);
            if (locked) {
              return (
                <span
                  key={stage.key}
                  className="jobStageLink"
                  data-locked="true"
                  aria-disabled="true"
                  title={reason ?? undefined}
                >
                  {stage.label}
                </span>
              );
            }
            return (
              <NavLink
                key={stage.key}
                className={({ isActive }) =>
                  `jobStageLink${isActive ? " jobStageLinkActive" : ""}`
                }
                end={stage.key === "progress"}
                to={stage.to}
              >
                {stage.label}
              </NavLink>
            );
          })}
        </nav>
        <div className="jobStageMeta">
          <div className="statusPill" data-state={job?.status ?? "idle"}>
            <Activity size={16} />
            <span>{job?.status ?? "ready"}</span>
          </div>
          <Link className="ghostButton jobNewLink" to="/">
            New job
          </Link>
        </div>
      </div>
      <div className="pageFrame">
        <Outlet />
      </div>
    </div>
  );
}
