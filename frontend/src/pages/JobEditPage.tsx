/**
 * JobEditPage — human edit workspace before portfolio / Review.
 * Each section owns independent Booking ID search + Sub category filters.
 */
import { ArrowRight, CheckCircle2, ChevronDown, Clock3, LoaderCircle, PencilLine, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { approveEdits, bulkPatchEditCases, fetchEditCases, patchEditCase } from "../api/jobs";
import BookingSearchForm from "../components/BookingSearchForm";
import EditCaseCard from "../components/EditCaseCard";
import PaginationControls from "../components/PaginationControls";
import { useJob } from "../context/JobProvider";
import type { AiBucket, EditCaseItem, EditOutcome, PatchEditCaseRequest } from "../types/jobs";

const PAGE_SIZE_HINT = 5;

const BULK_LABELS: Record<EditOutcome, string> = {
  include: "Bulk include",
  exclude: "Bulk exclude",
  needs_ops: "Bulk needs ops",
};

type SectionFilters = {
  searchInput: string;
  activeSearch: string;
  subCategory: string;
};

const EMPTY_FILTERS: SectionFilters = {
  searchInput: "",
  activeSearch: "",
  subCategory: "",
};

type SectionState = {
  cases: EditCaseItem[];
  page: number;
  totalPages: number;
  filteredCount: number;
  subCategories: string[];
  filters: SectionFilters;
};

const EMPTY_SECTION: SectionState = {
  cases: [],
  page: 1,
  totalPages: 1,
  filteredCount: 0,
  subCategories: [],
  filters: EMPTY_FILTERS,
};

type BulkActionsProps = {
  matchCount: number;
  disabled: boolean;
  onBulk: (outcome: EditOutcome) => void;
};

function BulkActions({ matchCount, disabled, onBulk }: BulkActionsProps) {
  return (
    <div className="editBulkActions" role="group" aria-label="Bulk outcomes">
      {(["include", "exclude", "needs_ops"] as EditOutcome[]).map((outcome) => (
        <button
          key={outcome}
          type="button"
          className="ghostButton editBulkButton"
          disabled={disabled || matchCount === 0}
          onClick={() => onBulk(outcome)}
        >
          {BULK_LABELS[outcome]}
        </button>
      ))}
    </div>
  );
}

type SectionToolbarProps = {
  inputId: string;
  selectId: string;
  filters: SectionFilters;
  subCategories: string[];
  filteredCount: number;
  disabled: boolean;
  onSearchInputChange: (value: string) => void;
  onSearch: () => void;
  onClearSearch: () => void;
  onSubCategoryChange: (value: string) => void;
};

function SectionToolbar({
  inputId,
  selectId,
  filters,
  subCategories,
  filteredCount,
  disabled,
  onSearchInputChange,
  onSearch,
  onClearSearch,
  onSubCategoryChange,
}: SectionToolbarProps) {
  const hasActiveFilters = Boolean(filters.activeSearch || filters.subCategory);

  return (
    <div className="editSectionToolbar">
      <BookingSearchForm
        inputId={inputId}
        value={filters.searchInput}
        placeholder="Search booking ID"
        disabled={disabled}
        isActive={Boolean(filters.activeSearch)}
        onValueChange={onSearchInputChange}
        onSearch={onSearch}
        onClear={onClearSearch}
      />
      <div className="editSubcategoryFilter">
        <label htmlFor={selectId}>Sub category</label>
        <select
          id={selectId}
          value={filters.subCategory}
          disabled={disabled}
          onChange={(event) => onSubCategoryChange(event.target.value)}
        >
          <option value="">All sub categories</option>
          {subCategories.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>
      {hasActiveFilters && (
        <span className="previewCount">
          {filteredCount.toLocaleString()} {filteredCount === 1 ? "match" : "matches"}
        </span>
      )}
    </div>
  );
}

function sectionHasFilters(filters: SectionFilters): boolean {
  return Boolean(filters.activeSearch || filters.subCategory);
}

function emptyMessage(filters: SectionFilters, emptyLabel: string): string {
  return sectionHasFilters(filters) ? "No bookings match your search or filter." : emptyLabel;
}

export default function JobEditPage() {
  const { jobId, job, isAwaitingEdit, isComplete, showEditWorkspace, refreshJob } = useJob();
  const navigate = useNavigate();

  const [needsCheck, setNeedsCheck] = useState<SectionState>(EMPTY_SECTION);
  const [unhandled, setUnhandled] = useState<SectionState>(EMPTY_SECTION);
  const [auto, setAuto] = useState<SectionState>(EMPTY_SECTION);

  const [needsCheckCount, setNeedsCheckCount] = useState(0);
  const [autoCount, setAutoCount] = useState(0);
  const [unhandledCount, setUnhandledCount] = useState(0);
  const [editedCount, setEditedCount] = useState(0);
  const [excludedCount, setExcludedCount] = useState(0);

  const [autoExpanded, setAutoExpanded] = useState(false);
  const [pendingSaves, setPendingSaves] = useState(0);
  const [bulkSaving, setBulkSaving] = useState(false);
  const [sectionLoading, setSectionLoading] = useState({
    needs_check: false,
    unhandled: false,
    auto_approved: false,
  });
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const needsCheckRef = useRef(needsCheck);
  const unhandledRef = useRef(unhandled);
  const autoRef = useRef(auto);
  needsCheckRef.current = needsCheck;
  unhandledRef.current = unhandled;
  autoRef.current = auto;

  const canEdit = (isAwaitingEdit || isComplete) && !approving && !bulkSaving;
  const isReApprove = isComplete;
  const anySectionLoading =
    sectionLoading.needs_check || sectionLoading.unhandled || sectionLoading.auto_approved;
  const controlsDisabled = anySectionLoading || approving || bulkSaving;

  const applyMetrics = useCallback(
    (payload: {
      needs_check_count: number;
      auto_approved_count: number;
      unhandled_count: number;
      edited_case_count: number;
      excluded_case_count: number;
    }) => {
      setNeedsCheckCount(payload.needs_check_count);
      setAutoCount(payload.auto_approved_count);
      setUnhandledCount(payload.unhandled_count);
      setEditedCount(payload.edited_case_count);
      setExcludedCount(payload.excluded_case_count);
    },
    [],
  );

  const applySectionPayload = useCallback(
    (bucket: AiBucket, payload: Awaited<ReturnType<typeof fetchEditCases>>) => {
      const patch = (current: SectionState): SectionState => ({
        ...current,
        cases: payload.cases,
        page: payload.page,
        totalPages: payload.total_pages,
        filteredCount: payload.case_count,
        subCategories: payload.available_sub_categories ?? [],
      });
      if (bucket === "needs_check") setNeedsCheck(patch);
      else if (bucket === "unhandled") setUnhandled(patch);
      else setAuto(patch);
      applyMetrics(payload);
    },
    [applyMetrics],
  );

  const loadSection = useCallback(
    async (bucket: AiBucket, section: SectionState) => {
      if (!jobId) return;
      const payload = await fetchEditCases(jobId, section.page, bucket, {
        bookingId: section.filters.activeSearch,
        subCategory: section.filters.subCategory,
      });
      applySectionPayload(bucket, payload);
    },
    [applySectionPayload, jobId],
  );

  const refreshAllSections = useCallback(async () => {
    await Promise.all([
      loadSection("needs_check", needsCheckRef.current),
      loadSection("unhandled", unhandledRef.current),
      loadSection("auto_approved", autoRef.current),
    ]);
  }, [loadSection]);

  useEffect(() => {
    if (!jobId || !showEditWorkspace) return;
    let cancelled = false;
    setSectionLoading((current) => ({ ...current, needs_check: true }));
    setError(null);
    void (async () => {
      try {
        await loadSection("needs_check", needsCheckRef.current);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unable to load edit cases");
        }
      } finally {
        if (!cancelled) {
          setSectionLoading((current) => ({ ...current, needs_check: false }));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    jobId,
    loadSection,
    needsCheck.filters.activeSearch,
    needsCheck.filters.subCategory,
    needsCheck.page,
    showEditWorkspace,
  ]);

  useEffect(() => {
    if (!jobId || !showEditWorkspace) return;
    let cancelled = false;
    setSectionLoading((current) => ({ ...current, unhandled: true }));
    setError(null);
    void (async () => {
      try {
        await loadSection("unhandled", unhandledRef.current);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unable to load edit cases");
        }
      } finally {
        if (!cancelled) {
          setSectionLoading((current) => ({ ...current, unhandled: false }));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    jobId,
    loadSection,
    showEditWorkspace,
    unhandled.filters.activeSearch,
    unhandled.filters.subCategory,
    unhandled.page,
  ]);

  useEffect(() => {
    if (!jobId || !showEditWorkspace) return;
    let cancelled = false;
    setSectionLoading((current) => ({ ...current, auto_approved: true }));
    setError(null);
    void (async () => {
      try {
        await loadSection("auto_approved", autoRef.current);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unable to load edit cases");
        }
      } finally {
        if (!cancelled) {
          setSectionLoading((current) => ({ ...current, auto_approved: false }));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    auto.filters.activeSearch,
    auto.filters.subCategory,
    auto.page,
    jobId,
    loadSection,
    showEditWorkspace,
  ]);

  function updateSectionFilters(
    setter: typeof setNeedsCheck,
    updater: (filters: SectionFilters) => SectionFilters,
  ) {
    setter((current) => ({
      ...current,
      page: 1,
      filters: updater(current.filters),
    }));
  }

  function setSectionPage(setter: typeof setNeedsCheck, page: number) {
    setter((current) => ({ ...current, page }));
  }

  async function handleSave(bookingId: string, patch: PatchEditCaseRequest) {
    if (!jobId || !canEdit) return;
    setPendingSaves((count) => count + 1);
    try {
      await patchEditCase(jobId, bookingId, patch);
      await refreshAllSections();
      await refreshJob();
    } finally {
      setPendingSaves((count) => Math.max(0, count - 1));
    }
  }

  async function handleBulk(bucket: AiBucket, section: SectionState, sectionLabel: string, outcome: EditOutcome) {
    if (!jobId || !canEdit || section.filteredCount === 0) return;
    const filterHint = sectionHasFilters(section.filters) ? " matching this section’s filters" : "";
    const confirmed = window.confirm(
      `${BULK_LABELS[outcome]} for ${section.filteredCount.toLocaleString()} booking${
        section.filteredCount === 1 ? "" : "s"
      } in “${sectionLabel}”${filterHint}?`,
    );
    if (!confirmed) return;

    setBulkSaving(true);
    setError(null);
    try {
      const result = await bulkPatchEditCases(jobId, {
        bucket,
        edit_outcome: outcome,
        booking_id: section.filters.activeSearch || undefined,
        sub_category: section.filters.subCategory || undefined,
      });
      applyMetrics(result);
      await refreshAllSections();
      await refreshJob();
    } catch (bulkError) {
      setError(bulkError instanceof Error ? bulkError.message : "Bulk edit failed");
    } finally {
      setBulkSaving(false);
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
            reference only. Each section has its own search and filters. Approve to build or refresh the
            recovery analysis.
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

      {error && (
        <div className="inlineAlert" role="alert">
          {error}
        </div>
      )}

      {(anySectionLoading || bulkSaving) && (
        <div className="emptyState">
          <LoaderCircle className="spin" size={18} />
          <span>{bulkSaving ? "Applying bulk outcome…" : "Loading bookings…"}</span>
        </div>
      )}

      <section className="editBucketSection">
        <header className="editBucketHeader">
          <PencilLine size={18} />
          <div>
            <h2>Needs your check</h2>
            <p>AI flagged these bookings. Review them carefully — all sections are editable.</p>
          </div>
          <BulkActions
            matchCount={needsCheck.filteredCount}
            disabled={!canEdit || sectionLoading.needs_check}
            onBulk={(outcome) => void handleBulk("needs_check", needsCheck, "Needs your check", outcome)}
          />
        </header>
        <SectionToolbar
          inputId="edit-needs-check-booking-search"
          selectId="edit-needs-check-subcategory-filter"
          filters={needsCheck.filters}
          subCategories={needsCheck.subCategories}
          filteredCount={needsCheck.filteredCount}
          disabled={controlsDisabled}
          onSearchInputChange={(value) =>
            updateSectionFilters(setNeedsCheck, (filters) => ({ ...filters, searchInput: value }))
          }
          onSearch={() =>
            updateSectionFilters(setNeedsCheck, (filters) => ({
              ...filters,
              searchInput: filters.searchInput.trim(),
              activeSearch: filters.searchInput.trim(),
            }))
          }
          onClearSearch={() =>
            updateSectionFilters(setNeedsCheck, (filters) => ({
              ...filters,
              searchInput: "",
              activeSearch: "",
            }))
          }
          onSubCategoryChange={(value) =>
            updateSectionFilters(setNeedsCheck, (filters) => ({ ...filters, subCategory: value }))
          }
        />
        {needsCheck.cases.length === 0 ? (
          <div className="emptyState">{emptyMessage(needsCheck.filters, "No bookings in this section.")}</div>
        ) : (
          <div className="editCaseList">
            {needsCheck.cases.map((item) => (
              <EditCaseCard key={item.booking_id} caseItem={item} disabled={!canEdit} onSave={handleSave} />
            ))}
          </div>
        )}
        <PaginationControls
          label="Needs your check"
          page={needsCheck.page}
          totalPages={needsCheck.totalPages}
          itemCount={needsCheck.filteredCount}
          pageSize={PAGE_SIZE_HINT}
          noun="bookings"
          disabled={controlsDisabled}
          onPageChange={(page) => setSectionPage(setNeedsCheck, page)}
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
          <BulkActions
            matchCount={unhandled.filteredCount}
            disabled={!canEdit || sectionLoading.unhandled}
            onBulk={(outcome) => void handleBulk("unhandled", unhandled, "New / unique categories", outcome)}
          />
        </header>
        <SectionToolbar
          inputId="edit-unhandled-booking-search"
          selectId="edit-unhandled-subcategory-filter"
          filters={unhandled.filters}
          subCategories={unhandled.subCategories}
          filteredCount={unhandled.filteredCount}
          disabled={controlsDisabled}
          onSearchInputChange={(value) =>
            updateSectionFilters(setUnhandled, (filters) => ({ ...filters, searchInput: value }))
          }
          onSearch={() =>
            updateSectionFilters(setUnhandled, (filters) => ({
              ...filters,
              searchInput: filters.searchInput.trim(),
              activeSearch: filters.searchInput.trim(),
            }))
          }
          onClearSearch={() =>
            updateSectionFilters(setUnhandled, (filters) => ({
              ...filters,
              searchInput: "",
              activeSearch: "",
            }))
          }
          onSubCategoryChange={(value) =>
            updateSectionFilters(setUnhandled, (filters) => ({ ...filters, subCategory: value }))
          }
        />
        {unhandled.cases.length === 0 ? (
          <div className="emptyState">{emptyMessage(unhandled.filters, "No unique-category bookings.")}</div>
        ) : (
          <div className="editCaseList">
            {unhandled.cases.map((item) => (
              <EditCaseCard key={item.booking_id} caseItem={item} disabled={!canEdit} onSave={handleSave} />
            ))}
          </div>
        )}
        <PaginationControls
          label="New / unique categories"
          page={unhandled.page}
          totalPages={unhandled.totalPages}
          itemCount={unhandled.filteredCount}
          pageSize={PAGE_SIZE_HINT}
          noun="bookings"
          disabled={controlsDisabled}
          onPageChange={(page) => setSectionPage(setUnhandled, page)}
        />
      </section>

      <section className="editBucketSection" data-collapsed={!autoExpanded || undefined}>
        <div className="editBucketHeader editAutoHeader">
          <button
            type="button"
            className="editBucketToggle"
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
          <BulkActions
            matchCount={auto.filteredCount}
            disabled={!canEdit || sectionLoading.auto_approved}
            onBulk={(outcome) => void handleBulk("auto_approved", auto, "AI auto-approved", outcome)}
          />
        </div>
        {autoExpanded && (
          <>
            <SectionToolbar
              inputId="edit-auto-booking-search"
              selectId="edit-auto-subcategory-filter"
              filters={auto.filters}
              subCategories={auto.subCategories}
              filteredCount={auto.filteredCount}
              disabled={controlsDisabled}
              onSearchInputChange={(value) =>
                updateSectionFilters(setAuto, (filters) => ({ ...filters, searchInput: value }))
              }
              onSearch={() =>
                updateSectionFilters(setAuto, (filters) => ({
                  ...filters,
                  searchInput: filters.searchInput.trim(),
                  activeSearch: filters.searchInput.trim(),
                }))
              }
              onClearSearch={() =>
                updateSectionFilters(setAuto, (filters) => ({
                  ...filters,
                  searchInput: "",
                  activeSearch: "",
                }))
              }
              onSubCategoryChange={(value) =>
                updateSectionFilters(setAuto, (filters) => ({ ...filters, subCategory: value }))
              }
            />
            {auto.cases.length === 0 ? (
              <div className="emptyState">{emptyMessage(auto.filters, "No bookings in this section.")}</div>
            ) : (
              <div className="editCaseList">
                {auto.cases.map((item) => (
                  <EditCaseCard key={item.booking_id} caseItem={item} disabled={!canEdit} onSave={handleSave} />
                ))}
              </div>
            )}
            <PaginationControls
              label="AI auto-approved"
              page={auto.page}
              totalPages={auto.totalPages}
              itemCount={auto.filteredCount}
              pageSize={PAGE_SIZE_HINT}
              noun="bookings"
              disabled={controlsDisabled}
              onPageChange={(page) => setSectionPage(setAuto, page)}
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
            disabled={!canEdit || pendingSaves > 0 || approving || bulkSaving}
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
