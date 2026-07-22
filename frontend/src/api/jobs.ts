import type {
  AgentCase,
  AgentCasesResponse,
  CategoryPreviewResponse,
  CreateJobResponse,
  EditCaseItem,
  EditCasesPageResponse,
  FinalOutputPreviewResponse,
  GraphTopology,
  JobResponse,
  PatchEditCaseRequest,
  PendingInterrupt,
  ResumeCaseRequest,
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

export async function fetchEditCases(
  jobId: string,
  page: number,
  bucket?: "needs_check" | "auto_approved"
): Promise<EditCasesPageResponse> {
  const searchParams = new URLSearchParams({
    page: String(page)
  });
  if (bucket) {
    searchParams.set("bucket", bucket);
  }
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/edit-cases?${searchParams.toString()}`));
  if (!response.ok) {
    throw new Error("Unable to fetch edit cases");
  }
  return (await response.json()) as EditCasesPageResponse;
}

export async function patchEditCase(
  jobId: string,
  bookingId: string,
  body: PatchEditCaseRequest
): Promise<EditCaseItem> {
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/edit-cases/${encodeURIComponent(bookingId)}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? "Unable to save edit");
  }
  return (await response.json()) as EditCaseItem;
}

export async function approveEdits(jobId: string): Promise<JobResponse> {
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/approve-edits`), {
    method: "POST"
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? "Unable to approve edits");
  }
  return (await response.json()) as JobResponse;
}

export async function fetchGraphTopology(jobId: string): Promise<GraphTopology> {
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/graph`));
  if (!response.ok) {
    throw new Error("Unable to fetch LangGraph topology");
  }
  return (await response.json()) as GraphTopology;
}

export async function fetchPendingInterrupts(jobId: string): Promise<PendingInterrupt[]> {
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/interrupts`));
  if (!response.ok) {
    throw new Error("Unable to fetch pending interrupts");
  }
  return (await response.json()) as PendingInterrupt[];
}

export async function resumeAgentCase(
  jobId: string,
  bookingId: string,
  body: ResumeCaseRequest
): Promise<AgentCase> {
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/cases/${encodeURIComponent(bookingId)}/resume`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? "Unable to resume case");
  }
  return (await response.json()) as AgentCase;
}

export function openJobEventStream(jobId: string): EventSource {
  return new EventSource(apiUrl(`/api/jobs/${jobId}/events`));
}

export async function createJob(
  file: File,
  startDate: string,
  endDate: string,
): Promise<CreateJobResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("start_date", startDate);
  formData.append("end_date", endDate);

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
