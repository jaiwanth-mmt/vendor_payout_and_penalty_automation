/**
 * JobEditPage — human edit workspace before portfolio / Review.
 * Editable while awaiting_edit and after success (re-edit + re-approve updates numbers).
 */
import { ArrowRight, CheckCircle2, Clock3, LoaderCircle, PencilLine } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { approveEdits, fetchEditCases, patchEditCase } from "../api/jobs";
import EditCaseCard from "../components/EditCaseCard";
import PaginationControls from "../components/PaginationControls";
import { useJob } from "../context/JobProvider";
import type { AiBucket, EditCaseItem, PatchEditCaseRequest } from "../types/jobs";

const PAGE_SIZE_HINT = 5;

export default function JobEditPage() {
  const { jobId, job, isAwaitingEdit, isComplete, showEditWorkspace, refreshJob } = useJob();
  const navigate = useNavigate();
  const [needsCheckPage, setNeedsCheckPage] = useState(1);
  const [autoPage, setAutoPage] = useState(1);
  const [needsCheckCases, setNeedsCheckCases] = useState<EditCaseItem[]>([]);
  const [autoCases, setAutoCases] = useState<EditCaseItem[]>([]);
  const [needsCheckTotalPages, setNeedsCheckTotalPages] = useState(1);
  const [autoTotalPages, setAutoTotalPages] = useState(1);
  const [needsCheckCount, setNeedsCheckCount] = useState(0);
  const [autoCount, setAutoCount] = useState(0);
  const [editedCount, setEditedCount] = useState(0);
  const [excludedCount, setExcludedCount] = useState(0);
  const [pendingSaves, setPendingSaves] = useState(0);
  const [loading, setLoading] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canEdit = (isAwaitingEdit || isComplete) && !approving;
  const isReApprove = isComplete;

  const loadBucket = useCallback(
    async (bucket: AiBucket, page: number) => {
      if (!jobId) return;
      const payload = await fetchEditCases(jobId, page, bucket);
      if (bucket === "needs_check") {
        setNeedsCheckCases(payload.cases);
        setNeedsCheckTotalPages(payload.total_pages);
        setNeedsCheckCount(payload.needs_check_count);
      } else {
        setAutoCases(payload.cases);
        setAutoTotalPages(payload.total_pages);
        setAutoCount(payload.auto_approved_count);
      }
      setEditedCount(payload.edited_case_count);
      setExcludedCount(payload.excluded_case_count);
    },
    [jobId],
  );

  const reloadAll = useCallback(async () => {
    if (!jobId || !showEditWorkspace) return;
    setLoading(true);
    setError(null);
    try {
      await Promise.all([loadBucket("needs_check", needsCheckPage), loadBucket("auto_approved", autoPage)]);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load edit cases");
    } finally {
      setLoading(false);
    }
  }, [autoPage, jobId, loadBucket, needsCheckPage, showEditWorkspace]);

  useEffect(() => {
    void reloadAll();
  }, [reloadAll]);

  async function handleSave(bookingId: string, patch: PatchEditCaseRequest) {
    if (!jobId || !canEdit) return;
    setPendingSaves((count) => count + 1);
    try {
      await patchEditCase(jobId, bookingId, patch);
      await Promise.all([loadBucket("needs_check", needsCheckPage), loadBucket("auto_approved", autoPage)]);
      await refreshJob();
    } finally {
      setPendingSaves((count) => Math.max(0, count - 1));
    }
  }

  async function handleApprove() {
    if (!jobId || !canEdit || pendingSaves > 0) return;
    const confirmed = window.confirm(
      isReApprove
        ? "Re-approve edits and rebuild the recovery analysis?\n\nReview and Outputs numbers will update."
        : "Approve all edits and build the recovery analysis?\n\nYou can still come back to Edit and re-approve later.",
    );
    if (!confirmed) return;
    setApproving(true);
    setError(null);
    try {
      await approveEdits(jobId);
      await refreshJob();
      navigate(`/jobs/${jobId}/review`);
    } catch (approveError) {
      setError(approveError instanceof Error ? approveError.message : "Approve failed");
      setApproving(false);
    }
  }

  if (!showEditWorkspace) {
    return (
      <div className="pageEmptySurface emptyState" role="status">
        <Clock3 size={22} />
        <div>
          <strong>Edit unlocks after investigation</strong>
          <p>Once agents finish, you can check and fix booking details here.</p>
        </div>
        <Link className="ghostButton" to={`/jobs/${jobId}`}>
          Back to progress
        </Link>
      </div>
    );
  }

  return (
    <div className="editPage">
      <header className="editPageHeader">
        <div>
          <p className="eyebrow">Edit bookings</p>
          <h2>Check and fix the booking details</h2>
          <p>
            Update fine amount, message, remarks, or sub category if needed. Call comments are shown for
            reference only. Approve to build or refresh the recovery analysis.
          </p>
        </div>
        <div className="editSummaryChips">
          <span>{needsCheckCount} need your check</span>
          <span>{autoCount} AI auto-approved</span>
          <span>{editedCount} edited</span>
          <span>{excludedCount} excluded</span>
        </div>
      </header>

      {error && (
        <div className="inlineAlert" role="alert">
          {error}
        </div>
      )}

      {loading && (
        <div className="emptyState">
          <LoaderCircle className="spin" size={18} />
          <span>Loading bookings…</span>
        </div>
      )}

      <section className="editBucketSection">
        <header className="editBucketHeader">
          <PencilLine size={18} />
          <div>
            <h2>Needs your check</h2>
            <p>AI flagged these bookings. Review them carefully — both sections are editable.</p>
          </div>
        </header>
        {needsCheckCases.length === 0 ? (
          <div className="emptyState">No bookings in this section.</div>
        ) : (
          <div className="editCaseList">
            {needsCheckCases.map((item) => (
              <EditCaseCard key={item.booking_id} caseItem={item} disabled={!canEdit} onSave={handleSave} />
            ))}
          </div>
        )}
        <PaginationControls
          label="Needs your check"
          page={needsCheckPage}
          totalPages={needsCheckTotalPages}
          itemCount={needsCheckCount}
          pageSize={PAGE_SIZE_HINT}
          noun="bookings"
          disabled={loading}
          onPageChange={setNeedsCheckPage}
        />
      </section>

      <section className="editBucketSection">
        <header className="editBucketHeader">
          <CheckCircle2 size={18} />
          <div>
            <h2>AI auto-approved</h2>
            <p>These look ready to AI. You can still change any field or outcome.</p>
          </div>
        </header>
        {autoCases.length === 0 ? (
          <div className="emptyState">No bookings in this section.</div>
        ) : (
          <div className="editCaseList">
            {autoCases.map((item) => (
              <EditCaseCard key={item.booking_id} caseItem={item} disabled={!canEdit} onSave={handleSave} />
            ))}
          </div>
        )}
        <PaginationControls
          label="AI auto-approved"
          page={autoPage}
          totalPages={autoTotalPages}
          itemCount={autoCount}
          pageSize={PAGE_SIZE_HINT}
          noun="bookings"
          disabled={loading}
          onPageChange={setAutoPage}
        />
      </section>

      {canEdit && (
        <footer className="editApproveBar">
          <div>
            <strong>
              {editedCount} edited · {excludedCount} excluded
            </strong>
            <p>
              {pendingSaves > 0
                ? "Saving your latest changes…"
                : isReApprove
                  ? "Re-approve to refresh Review and Outputs with your latest edits."
                  : "Approve when you are happy with all edits."}
            </p>
          </div>
          <button
            type="button"
            className="primaryButton"
            disabled={!canEdit || pendingSaves > 0 || approving}
            onClick={() => void handleApprove()}
          >
            {approving ? <LoaderCircle className="spin" size={17} /> : <CheckCircle2 size={17} />}
            <span>
              {approving
                ? "Building package…"
                : isReApprove
                  ? "Re-approve & update"
                  : "Approve edits & continue"}
            </span>
            {!approving && <ArrowRight size={16} />}
          </button>
        </footer>
      )}

      {job?.status === "running" && approving && (
        <div className="inlineAlert" role="status">
          Building recovery analysis from your edits…
        </div>
      )}
    </div>
  );
}
