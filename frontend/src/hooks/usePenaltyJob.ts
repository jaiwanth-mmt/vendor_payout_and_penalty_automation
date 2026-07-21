import { useCallback, useEffect, useMemo, useState } from "react";

import { apiUrl, createJob, fetchJob } from "../api/jobs";
import { DEFAULT_END_DATE, DEFAULT_START_DATE, METRIC_LABELS } from "../constants/pipeline";
import type { JobResponse, VisibleMetric } from "../types/jobs";

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

export function usePenaltyJob() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [startDate, setStartDate] = useState(DEFAULT_START_DATE);
  const [endDate, setEndDate] = useState(DEFAULT_END_DATE);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isProcessing = job?.status === "queued" || job?.status === "running" || isSubmitting;
  const isComplete = job?.status === "succeeded";
  const hasFailed = job?.status === "failed";

  const fetchJobStatus = useCallback(async (id: string) => {
    const payload = await fetchJob(id);
    setJob(payload);
    return payload;
  }, []);

  useEffect(() => {
    if (!jobId) return;
    if (job?.status === "succeeded" || job?.status === "failed") return;

    let isCancelled = false;
    const poll = async () => {
      try {
        const payload = await fetchJobStatus(jobId);
        if (!isCancelled && isTerminalJob(payload)) {
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

    try {
      const payload = await createJob(selectedFile, startDate, endDate);
      setJobId(payload.job_id);
      const initialJob = await fetchJobStatus(payload.job_id);
      if (isTerminalJob(initialJob)) {
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

  return {
    selectedFile,
    setSelectedFile,
    startDate,
    setStartDate,
    endDate,
    setEndDate,
    job,
    isProcessing,
    isComplete,
    hasFailed,
    error,
    setError,
    visibleMetrics,
    submitJob,
    downloadPackage,
    downloadFinalOutput,
    downloadAgentAudit,
    downloadReviewQueue
  };
}
