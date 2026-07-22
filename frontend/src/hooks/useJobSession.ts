/**
 * useJobSession — poll + SSE + downloads for one existing jobId.
 * Used by JobProvider so Progress/Edit/Review/Outputs share one session.
 * Does not own the upload form (see useCreateJob).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiUrl, fetchJob, openJobEventStream } from "../api/jobs";
import { METRIC_LABELS } from "../constants/pipeline";
import type { GraphEvent, JobResponse, VisibleMetric } from "../types/jobs";

function formatMetricValue(key: string, value: number | string): number | string {
  const numberValue = Number(value);
  if (key === "agent_total_recoverable_amount") {
    const amount = Number.isFinite(numberValue)
      ? numberValue.toLocaleString("en-IN", { maximumFractionDigits: 0 })
      : "0";
    return `₹${amount}`;
  }
  if (key === "agent_high_confidence_percentage") {
    return `${Number.isFinite(numberValue) ? numberValue.toFixed(1) : "0.0"}%`;
  }
  return typeof value === "number" ? value.toLocaleString("en-IN") : value;
}

function shouldStreamEvents(job: JobResponse | null): boolean {
  if (!job) return true;
  return (
    job.status === "queued" ||
    job.status === "running" ||
    job.status === "awaiting_edit" ||
    job.status === "awaiting_review"
  );
}

export function useJobSession(jobId: string | undefined) {
  const [job, setJob] = useState<JobResponse | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(jobId));
  const [error, setError] = useState<string | null>(null);
  const [graphEvents, setGraphEvents] = useState<GraphEvent[]>([]);
  const [editGatePassed, setEditGatePassed] = useState(false);
  const pendingEventsRef = useRef<GraphEvent[]>([]);
  const flushTimerRef = useRef<number | null>(null);

  const isProcessing = job?.status === "queued" || job?.status === "running";
  const isAwaitingEdit = job?.status === "awaiting_edit";
  const isAwaitingReview = job?.status === "awaiting_review";
  const isComplete = job?.status === "succeeded";
  const hasFailed = job?.status === "failed";
  // Keep Edit available while approve/re-approve flips status to running for packaging.
  const showEditWorkspace = isAwaitingEdit || isComplete || (job?.status === "running" && editGatePassed);
  const showAgentWorkspace = isComplete;

  useEffect(() => {
    if (isAwaitingEdit || isComplete) {
      setEditGatePassed(true);
    }
  }, [isAwaitingEdit, isComplete]);

  const fetchJobStatus = useCallback(async (id: string) => {
    const payload = await fetchJob(id);
    setJob(payload);
    // Prefer polled investigation_summary; only seed technical log from snapshot when empty.
    if (payload.graph_events?.length) {
      setGraphEvents((current) => (current.length ? current : payload.graph_events));
    }
    return payload;
  }, []);

  // Reset + attach when the URL jobId changes (deep link / navigation).
  useEffect(() => {
    if (!jobId) {
      setJob(null);
      setGraphEvents([]);
      setError(null);
      setIsLoading(false);
      return;
    }

    let isCancelled = false;
    setJob(null);
    setGraphEvents([]);
    pendingEventsRef.current = [];
    setEditGatePassed(false);
    setError(null);
    setIsLoading(true);

    fetchJobStatus(jobId)
      .then(() => {
        if (!isCancelled) setIsLoading(false);
      })
      .catch((loadError) => {
        if (!isCancelled) {
          setJob(null);
          setError(loadError instanceof Error ? loadError.message : "Unable to load job");
          setIsLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [fetchJobStatus, jobId]);

  useEffect(() => {
    if (!jobId || isLoading) return;
    // Keep polling through awaiting_edit so saves / approve update the timeline.
    if (job?.status === "succeeded" || job?.status === "failed") return;
    if (error && !job?.job_id) return;

    let isCancelled = false;
    const poll = async () => {
      try {
        await fetchJobStatus(jobId);
        if (!isCancelled) setError(null);
      } catch (pollError) {
        if (!isCancelled) {
          setError(pollError instanceof Error ? pollError.message : "Status polling failed");
        }
      }
    };

    // Initial attach already fetched; interval continues while non-terminal.
    const timer = window.setInterval(poll, 900);
    return () => {
      isCancelled = true;
      window.clearInterval(timer);
    };
  }, [error, fetchJobStatus, isLoading, job?.job_id, job?.status, jobId]);

  useEffect(() => {
    if (!jobId || !shouldStreamEvents(job)) return;

    const source = openJobEventStream(jobId);
    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as GraphEvent;
        // Buffer SSE ticks and flush at most ~1/sec so the technical log stays readable.
        pendingEventsRef.current = [...pendingEventsRef.current.slice(-39), event];
        if (flushTimerRef.current != null) return;
        flushTimerRef.current = window.setTimeout(() => {
          const batch = pendingEventsRef.current;
          pendingEventsRef.current = [];
          flushTimerRef.current = null;
          if (!batch.length) return;
          setGraphEvents((current) => [...current, ...batch].slice(-40));
        }, 1000);
      } catch {
        // ignore malformed SSE payloads
      }
    };
    source.onerror = () => {
      source.close();
    };
    return () => {
      source.close();
      if (flushTimerRef.current != null) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
    };
  }, [job, jobId]);

  const visibleMetrics = useMemo<VisibleMetric[]>(() => {
    if (!job?.metrics) return [];
    const totalCases = Number(job.metrics.agent_total_cases ?? job.case_counts.total_cases ?? 0);
    const highConfidenceCases = Number(
      job.metrics.agent_high_confidence_cases ?? job.agent_summary?.high_confidence_case_count ?? 0,
    );
    const highConfidencePercentage = totalCases > 0 ? (highConfidenceCases / totalCases) * 100 : 0;
    const metricValues: Record<string, number | string> = {
      ...job.metrics,
      agent_high_confidence_percentage: highConfidencePercentage,
    };
    return Object.entries(METRIC_LABELS)
      .filter(([key]) => metricValues[key] !== undefined)
      .map(([key, label]) => ({ key, label, value: formatMetricValue(key, metricValues[key]) }));
  }, [job]);

  const downloadFinalOutput = useCallback(() => {
    if (!job?.final_output?.download_ready) return;
    window.location.href = apiUrl(`/api/jobs/${job.job_id}/final-output/download`);
  }, [job]);

  const downloadAgentAudit = useCallback(() => {
    if (job?.status !== "succeeded") return;
    window.location.href = apiUrl(`/api/jobs/${job.job_id}/agent-audit/download`);
  }, [job]);

  const downloadReviewQueue = useCallback(() => {
    if (job?.status !== "succeeded") return;
    window.location.href = apiUrl(`/api/jobs/${job.job_id}/review-queue/download`);
  }, [job]);

  const downloadCategoryOutputs = useCallback(() => {
    if (job?.status !== "succeeded" || !(job.category_outputs?.length > 0)) return;
    window.location.href = apiUrl(`/api/jobs/${job.job_id}/categories/download`);
  }, [job]);

  const refreshJob = useCallback(async () => {
    if (!jobId) return;
    await fetchJobStatus(jobId);
  }, [fetchJobStatus, jobId]);

  return {
    jobId: jobId ?? null,
    job,
    isLoading,
    isProcessing,
    isAwaitingEdit,
    isAwaitingReview,
    isComplete,
    showEditWorkspace,
    showAgentWorkspace,
    hasFailed,
    error,
    setError,
    visibleMetrics,
    graphEvents,
    downloadFinalOutput,
    downloadAgentAudit,
    downloadReviewQueue,
    downloadCategoryOutputs,
    refreshJob,
  };
}

export type JobSessionValue = ReturnType<typeof useJobSession>;
