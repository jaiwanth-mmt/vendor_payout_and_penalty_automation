/**
 * JobProvider — owns one job session for /jobs/:jobId/*
 * Attach: read jobId from route → fetchJob → poll 900ms + SSE while non-terminal.
 * Consumers: useJob() from pages under JobLayout.
 */
import { createContext, useContext, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import { useJobSession, type JobSessionValue } from "../hooks/useJobSession";

const JobContext = createContext<JobSessionValue | null>(null);

export function JobProvider({ children }: { children: ReactNode }) {
  const { jobId } = useParams<{ jobId: string }>();
  const session = useJobSession(jobId);

  return <JobContext.Provider value={session}>{children}</JobContext.Provider>;
}

export function useJob(): JobSessionValue {
  const value = useContext(JobContext);
  if (!value) {
    throw new Error("useJob must be used inside JobProvider (/jobs/:jobId routes)");
  }
  return value;
}
