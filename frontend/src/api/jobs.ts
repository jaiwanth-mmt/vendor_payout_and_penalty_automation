import type { CreateJobResponse, FinalOutputPreviewResponse, JobResponse } from "../types/jobs";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export async function fetchJob(jobId: string): Promise<JobResponse> {
  const response = await fetch(apiUrl(`/api/jobs/${jobId}`));
  if (!response.ok) {
    throw new Error("Unable to fetch job status");
  }
  return (await response.json()) as JobResponse;
}

export async function fetchFinalOutputPreview(
  jobId: string,
  page: number,
  pageSize: number
): Promise<FinalOutputPreviewResponse> {
  const searchParams = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize)
  });
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/final-output/preview?${searchParams.toString()}`));
  if (!response.ok) {
    throw new Error("Unable to fetch final output preview");
  }
  return (await response.json()) as FinalOutputPreviewResponse;
}

export async function createJob(file: File, approvalDate: string): Promise<CreateJobResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("approval_date", approvalDate);

  const response = await fetch(apiUrl("/api/jobs"), {
    method: "POST",
    body: formData
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? "Upload failed");
  }
  return (await response.json()) as CreateJobResponse;
}
