/**
 * JobEditPage — human edit workspace before portfolio / Review.
 * Editable while awaiting_edit and after success (re-edit + re-approve updates numbers).
 */
import { ArrowRight, CheckCircle2, ChevronDown, Clock3, LoaderCircle, PencilLine, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { approveEdits, fetchEditCases, patchEditCase } from "../api/jobs";
import BookingSearchForm from "../components/BookingSearchForm";
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
  const [unhandledPage, setUnhandledPage] = useState(1);
  const [needsCheckCases, setNeedsCheckCases] = useState<EditCaseItem[]>([]);
  const [autoCases, setAutoCases] = useState<EditCaseItem[]>([]);
  const [unhandledCases, setUnhandledCases] = useState<EditCaseItem[]>([]);
  const [needsCheckTotalPages, setNeedsCheckTotalPages] = useState(1);
  const [autoTotalPages, setAutoTotalPages] = useState(1);
  const [unhandledTotalPages, setUnhandledTotalPages] = useState(1);
  const [needsCheckFilteredCount, setNeedsCheckFilteredCount] = useState(0);
  const [autoFilteredCount, setAutoFilteredCount] = useState(0);
  const [unhandledFilteredCount, setUnhandledFilteredCount] = useState(0);
  const [needsCheckCount, setNeedsCheckCount] = useState(0);
  const [autoCount, setAutoCount] = useState(0);
  const [unhandledCount, setUnhandledCount] = useState(0);
  const [editedCount, setEditedCount] = useState(0);
  const [excludedCount, setExcludedCount] = useState(0);
  const [availableSubCategories, setAvailableSubCategories] = useState<string[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [subCategoryFilter, setSubCategoryFilter] = useState("");
  const [autoExpanded, setAutoExpanded] = useState(false);
  const [pendingSaves, setPendingSaves] = useState(0);
  const [loading, setLoading] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canEdit = (isAwaitingEdit || isComplete) && !approving;
  const isReApprove = isComplete;
  const hasActiveFilters = Boolean(activeSearch || subCategoryFilter);
  const filteredMatchCount = needsCheckFilteredCount + autoFilteredCount + unhandledFilteredCount;

  const loadBucket = useCallback(
    async (bucket: AiBucket, page: number) => {
      if (!jobId) return;
      const payload = await fetchEditCases(jobId, page, bucket, {
        bookingId: activeSearch,
        subCategory: subCategoryFilter,
      });
      if (bucket === "needs_check") {
        setNeedsCheckCases(payload.cases);
        setNeedsCheckTotalPages(payload.total_pages);
        setNeedsCheckFilteredCount(payload.case_count);
        setNeedsCheckCount(payload.needs_check_count);
      } else if (bucket === "auto_approved") {
        setAutoCases(payload.cases);
        setAutoTotalPages(payload.total_pages);
        setAutoFilteredCount(payload.case_count);
        setAutoCount(payload.auto_approved_count);
      } else {
        setUnhandledCases(payload.cases);
        setUnhandledTotalPages(payload.total_pages);
        setUnhandledFilteredCount(payload.case_count);
        setUnhandledCount(payload.unhandled_count);
      }
      setEditedCount(payload.edited_case_count);
      setExcludedCount(payload.excluded_case_count);
      setAvailableSubCategories(payload.available_sub_categories ?? []);
      setNeedsCheckCount(payload.needs_check_count);
      setAutoCount(payload.auto_approved_count);
      setUnhandledCount(payload.unhandled_count);
    },
    [activeSearch, jobId, subCategoryFilter],
  );

  const reloadAll = useCallback(async () => {
    if (!jobId || !showEditWorkspace) return;
    setLoading(true);
    setError(null);
    try {
      await Promise.all([
        loadBucket("needs_check", needsCheckPage),
        loadBucket("auto_approved", autoPage),
        loadBucket("unhandled", unhandledPage),
      ]);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load edit cases");
    } finally {
      setLoading(false);
    }
  }, [autoPage, jobId, loadBucket, needsCheckPage, showEditWorkspace, unhandledPage]);

  useEffect(() => {
    void reloadAll();
  }, [reloadAll]);

  function handleSearch() {
    const trimmedSearch = searchInput.trim();
    setSearchInput(trimmedSearch);
    setActiveSearch(trimmedSearch);
    setNeedsCheckPage(1);
    setAutoPage(1);
    setUnhandledPage(1);
  }

  function handleClearSearch() {
    setSearchInput("");
    setActiveSearch("");
    setNeedsCheckPage(1);
    setAutoPage(1);
    setUnhandledPage(1);
  }

  function handleSubCategoryChange(nextValue: string) {
    setSubCategoryFilter(nextValue);
    setNeedsCheckPage(1);
    setAutoPage(1);
    setUnhandledPage(1);
  }

  async function handleSave(bookingId: string, patch: PatchEditCaseRequest) {
    if (!jobId || !canEdit) return;
    setPendingSaves((count) => count + 1);
    try {
      await patchEditCase(jobId, bookingId, patch);
      await Promise.all([
        loadBucket("needs_check", needsCheckPage),
        loadBucket("auto_approved", autoPage),
        loadBucket("unhandled", unhandledPage),
      ]);
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
          <span>{unhandledCount} unique categories</span>
          <span>{autoCount} AI auto-approved</span>
          <span>{editedCount} edited</span>
          <span>{excludedCount} excluded</span>
        </div>
      </header>

      <div className="editToolbar">
        <BookingSearchForm
          inputId="edit-booking-search"
          value={searchInput}
          placeholder="Search booking ID"
          disabled={loading || approving}
          isActive={Boolean(activeSearch)}
          onValueChange={setSearchInput}
          onSearch={handleSearch}
          onClear={handleClearSearch}
        />
        <div className="editSubcategoryFilter">
          <label htmlFor="edit-subcategory-filter">Sub category</label>
          <select
            id="edit-subcategory-filter"
            value={subCategoryFilter}
            disabled={loading || approving}
            onChange={(event) => handleSubCategoryChange(event.target.value)}
          >
            <option value="">All sub categories</option>
            {availableSubCategories.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        {hasActiveFilters && (
          <span className="previewCount">
            {filteredMatchCount.toLocaleString()} {filteredMatchCount === 1 ? "match" : "matches"}
          </span>
        )}
      </div>

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
            <p>AI flagged these bookings. Review them carefully — all sections are editable.</p>
          </div>
        </header>
        {needsCheckCases.length === 0 ? (
          <div className="emptyState">
            {hasActiveFilters ? "No bookings match your search or filter." : "No bookings in this section."}
          </div>
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
          itemCount={needsCheckFilteredCount}
          pageSize={PAGE_SIZE_HINT}
          noun="bookings"
          disabled={loading}
          onPageChange={setNeedsCheckPage}
        />
      </section>

      <section className="editBucketSection">
        <header className="editBucketHeader">
          <Sparkles size={18} />
          <div>
            <h2>New / unique categories</h2>
            <p>
              Sub categories not in the allowed complaint list. Decide Include / Needs ops / Exclude before
              approval — they still appear in category previews and the package when included.
            </p>
          </div>
        </header>
        {unhandledCases.length === 0 ? (
          <div className="emptyState">
            {hasActiveFilters ? "No bookings match your search or filter." : "No unique-category bookings."}
          </div>
        ) : (
          <div className="editCaseList">
            {unhandledCases.map((item) => (
              <EditCaseCard key={item.booking_id} caseItem={item} disabled={!canEdit} onSave={handleSave} />
            ))}
          </div>
        )}
        <PaginationControls
          label="New / unique categories"
          page={unhandledPage}
          totalPages={unhandledTotalPages}
          itemCount={unhandledFilteredCount}
          pageSize={PAGE_SIZE_HINT}
          noun="bookings"
          disabled={loading}
          onPageChange={setUnhandledPage}
        />
      </section>

      <section className="editBucketSection" data-collapsed={!autoExpanded || undefined}>
        <button
          type="button"
          className="editBucketHeader editBucketToggle"
          aria-expanded={autoExpanded}
          onClick={() => setAutoExpanded((open) => !open)}
        >
          <CheckCircle2 size={18} />
          <div>
            <h2>AI auto-approved</h2>
            <p>
              {autoCount.toLocaleString()} booking{autoCount === 1 ? "" : "s"} look ready to AI. Click to{" "}
              {autoExpanded ? "collapse" : "expand"}.
            </p>
          </div>
          <ChevronDown size={18} className="editBucketChevron" data-open={autoExpanded || undefined} />
        </button>
        {autoExpanded && (
          <>
            {autoCases.length === 0 ? (
              <div className="emptyState">
                {hasActiveFilters ? "No bookings match your search or filter." : "No bookings in this section."}
              </div>
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
              itemCount={autoFilteredCount}
              pageSize={PAGE_SIZE_HINT}
              noun="bookings"
              disabled={loading}
              onPageChange={setAutoPage}
            />
          </>
        )}
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
