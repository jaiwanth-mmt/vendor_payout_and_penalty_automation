/**
 * useCreateJob — upload form state + POST /api/jobs, then navigate to Progress.
 * No poll/SSE here; JobProvider attaches the session on /jobs/:jobId.
 */
import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";

import { createJob } from "../api/jobs";
import { DEFAULT_END_DATE, DEFAULT_START_DATE } from "../constants/pipeline";

export function useCreateJob() {
  const navigate = useNavigate();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [startDate, setStartDate] = useState(DEFAULT_START_DATE);
  const [endDate, setEndDate] = useState(DEFAULT_END_DATE);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

    try {
      const payload = await createJob(selectedFile, startDate, endDate);
      navigate(`/jobs/${payload.job_id}`);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Upload failed");
      setIsSubmitting(false);
    }
  }, [endDate, navigate, selectedFile, startDate]);

  return {
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
  };
}
