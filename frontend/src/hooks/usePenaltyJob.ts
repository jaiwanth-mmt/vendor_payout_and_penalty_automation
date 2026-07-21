import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiUrl, createJob, fetchJob, openJobEventStream } from "../api/jobs";
import { DEFAULT_END_DATE, DEFAULT_START_DATE, METRIC_LABELS } from "../constants/pipeline";
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

function isTerminalJob(job: JobResponse): boolean {
  return job.status === "succeeded" || job.status === "failed";
}

function shouldStreamEvents(job: JobResponse | null): boolean {
  if (!job) return true;
  return job.status === "queued" || job.status === "running" || job.status === "awaiting_review";
}

export function usePenaltyJob() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [startDate, setStartDate] = useState(DEFAULT_START_DATE);
  const [endDate, setEndDate] = useState(DEFAULT_END_DATE);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [graphEvents, setGraphEvents] = useState<GraphEvent[]>([]);
  const pendingEventsRef = useRef<GraphEvent[]>([]);
  const flushTimerRef = useRef<number | null>(null);

  const isProcessing = job?.status === "queued" || job?.status === "running" || isSubmitting;
  const isAwaitingReview = job?.status === "awaiting_review";
  const isComplete = job?.status === "succeeded";
  const hasFailed = job?.status === "failed";
  const showAgentWorkspace = isComplete || isAwaitingReview;

  const fetchJobStatus = useCallback(async (id: string) => {
    const payload = await fetchJob(id);
    setJob(payload);
    // Prefer polled investigation_summary; only seed technical log from snapshot when empty.
    if (payload.graph_events?.length) {
      setGraphEvents((current) => (current.length ? current : payload.graph_events));
    }
    return payload;
  }, []);

  useEffect(() => {
    if (!jobId) return;
    // Keep polling through awaiting_review so Approve / Keep review updates the timeline.
    if (job && isTerminalJob(job)) return;

    let isCancelled = false;
    const poll = async () => {
      try {
        const payload = await fetchJobStatus(jobId);
        if (!isCancelled && isTerminalJob(payload)) {
          setIsSubmitting(false);
        }
        if (!isCancelled && payload.status === "awaiting_review") {
          setIsSubmitting(false);
        }
      } catch (pollError) {
        if (!isCancelled) {
          setError(pollError instanceof Error ? pollError.message : "Status polling failed");
          setIsSubmitting(false);
        }
      }
    };

    poll();
    const timer = window.setInterval(poll, 900);
    return () => {
      isCancelled = true;
      window.clearInterval(timer);
    };
  }, [fetchJobStatus, job?.status, jobId]);

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
      agent_high_confidence_percentage: highConfidencePercentage
    };
    return Object.entries(METRIC_LABELS)
      .filter(([key]) => metricValues[key] !== undefined)
      .map(([key, label]) => ({ key, label, value: formatMetricValue(key, metricValues[key]) }));
  }, [job]);

  const submitJob = useCallback(async () => {
    if (!selectedFile) {
      setError("Select a QlikSense Excel workbook first.");
      return;
    }
    if (startDate > endDate) {
      setError("Start date must be on or before end date.");
      return;
    }

    setIsSubmitting(true);
    setError(null);
    setJob(null);
    setJobId(null);
    setGraphEvents([]);
    pendingEventsRef.current = [];

    try {
      const payload = await createJob(selectedFile, startDate, endDate);
      setJobId(payload.job_id);
      const initialJob = await fetchJobStatus(payload.job_id);
      if (isTerminalJob(initialJob) || initialJob.status === "awaiting_review") {
        setIsSubmitting(false);
      }
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Upload failed");
      setIsSubmitting(false);
    }
  }, [endDate, fetchJobStatus, selectedFile, startDate]);

  const downloadPackage = useCallback(() => {
    if (!job?.download_ready) return;
    window.location.href = apiUrl(`/api/jobs/${job.job_id}/download`);
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

  const refreshJob = useCallback(async () => {
    if (!jobId) return;
    await fetchJobStatus(jobId);
  }, [fetchJobStatus, jobId]);

  return {
    selectedFile,
    setSelectedFile,
    startDate,
    setStartDate,
    endDate,
    setEndDate,
    job,
    isProcessing,
    isAwaitingReview,
    isComplete,
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
  };
}
