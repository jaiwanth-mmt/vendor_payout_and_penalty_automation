import type {
  AgentCase,
  AgentCasesResponse,
  CategoryPreviewResponse,
  CreateJobResponse,
  FinalOutputPreviewResponse,
  JobResponse,
  ReviewQueuePageResponse
} from "../types/jobs";

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
  pageSize: number,
  bookingId = ""
): Promise<FinalOutputPreviewResponse> {
  const searchParams = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize)
  });
  const trimmedBookingId = bookingId.trim();
  if (trimmedBookingId) {
    searchParams.set("booking_id", trimmedBookingId);
  }
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/final-output/preview?${searchParams.toString()}`));
  if (!response.ok) {
    throw new Error("Unable to fetch final output preview");
  }
  return (await response.json()) as FinalOutputPreviewResponse;
}

export async function fetchCategoryPreview(
  jobId: string,
  slug: string,
  page: number,
  bookingId = ""
): Promise<CategoryPreviewResponse> {
  const searchParams = new URLSearchParams({
    page: String(page)
  });
  const trimmedBookingId = bookingId.trim();
  if (trimmedBookingId) {
    searchParams.set("booking_id", trimmedBookingId);
  }
  const response = await fetch(
    apiUrl(`/api/jobs/${jobId}/categories/${encodeURIComponent(slug)}/preview?${searchParams.toString()}`)
  );
  if (!response.ok) {
    throw new Error("Unable to fetch category preview");
  }
  return (await response.json()) as CategoryPreviewResponse;
}

export async function fetchReviewQueue(jobId: string, page: number): Promise<ReviewQueuePageResponse> {
  const searchParams = new URLSearchParams({
    page: String(page)
  });
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/review-queue?${searchParams.toString()}`));
  if (!response.ok) {
    throw new Error("Unable to fetch review queue");
  }
  return (await response.json()) as ReviewQueuePageResponse;
}

export async function fetchAgentCases(jobId: string, page: number): Promise<AgentCasesResponse> {
  const searchParams = new URLSearchParams({
    page: String(page)
  });
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/cases?${searchParams.toString()}`));
  if (!response.ok) {
    throw new Error("Unable to fetch agent cases");
  }
  return (await response.json()) as AgentCasesResponse;
}

export async function fetchAgentCase(jobId: string, bookingId: string): Promise<AgentCase> {
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/cases/${encodeURIComponent(bookingId)}`));
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? "Unable to fetch agent case");
  }
  return (await response.json()) as AgentCase;
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
