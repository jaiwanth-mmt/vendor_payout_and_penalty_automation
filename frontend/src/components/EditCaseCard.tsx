/** EditCaseCard — compact horizontal editable row for one booking. */

import { useEffect, useState } from "react";

import type { EditCaseItem, EditOutcome, PatchEditCaseRequest } from "../types/jobs";

const OUTCOME_OPTIONS: { value: EditOutcome; label: string; help: string }[] = [
  { value: "include", label: "Include", help: "Add to the recovery package." },
  { value: "needs_ops", label: "Needs ops", help: "Keep in the ops follow-up list." },
  { value: "exclude", label: "Exclude", help: "Leave out of the recovery package." },
];

type EditCaseCardProps = {
  caseItem: EditCaseItem;
  disabled?: boolean;
  onSave: (bookingId: string, patch: PatchEditCaseRequest) => Promise<void>;
};

function EditCaseCard({ caseItem, disabled = false, onSave }: EditCaseCardProps) {
  const [recoverable, setRecoverable] = useState(String(caseItem.recoverable_amount ?? 0));
  const [message, setMessage] = useState(caseItem.message ?? "");
  const [remarks, setRemarks] = useState(caseItem.remarks ?? "");
  const [subCategory, setSubCategory] = useState(caseItem.sub_category ?? "");
  const [outcome, setOutcome] = useState<EditOutcome>(caseItem.edit_outcome);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    setRecoverable(String(caseItem.recoverable_amount ?? 0));
    setMessage(caseItem.message ?? "");
    setRemarks(caseItem.remarks ?? "");
    setSubCategory(caseItem.sub_category ?? "");
    setOutcome(caseItem.edit_outcome);
    setLocalError(null);
  }, [
    caseItem.booking_id,
    caseItem.recoverable_amount,
    caseItem.message,
    caseItem.remarks,
    caseItem.sub_category,
    caseItem.edit_outcome,
    caseItem.was_edited,
  ]);

  async function persist(patch: PatchEditCaseRequest) {
    setSaving(true);
    setLocalError(null);
    try {
      await onSave(caseItem.booking_id, patch);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  async function saveRecoverable() {
    const amount = Number(recoverable);
    if (!Number.isFinite(amount) || amount < 0) {
      setLocalError("Fine amount must be a number 0 or higher");
      return;
    }
    if (amount === caseItem.recoverable_amount) return;
    await persist({ recoverable_amount: amount });
  }

  async function saveMessage() {
    if (message === caseItem.message) return;
    await persist({ message });
  }

  async function saveRemarks() {
    if (remarks === caseItem.remarks) return;
    await persist({ remarks });
  }

  async function saveSubCategory() {
    const trimmed = subCategory.trim();
    if (!trimmed) {
      setLocalError("Sub category cannot be empty");
      return;
    }
    if (trimmed === caseItem.sub_category) return;
    await persist({ sub_category: trimmed });
  }

  async function saveOutcome(next: EditOutcome) {
    setOutcome(next);
    if (next === caseItem.edit_outcome) return;
    await persist({ edit_outcome: next });
  }

  return (
    <article className="editCaseCard" data-edited={caseItem.was_edited ? "true" : "false"}>
      <header className="editCaseHeader">
        <div className="editCaseIdentity">
          <span className={`bookingIdChip${caseItem.was_edited ? " bookingIdChipEdited" : ""}`}>
            {caseItem.booking_id}
          </span>
          <span className="editCaseVendor">{caseItem.vendor_name || "Unknown vendor"}</span>
          {caseItem.was_edited && <em className="editedBadge">Edited</em>}
          {saving && <small className="editSavingHint">Saving…</small>}
        </div>
        <button
          type="button"
          className="ghostButton editCommentsToggle"
          onClick={() => setCommentsOpen((open) => !open)}
        >
          {commentsOpen ? "Hide comments" : "Call comments"}
        </button>
      </header>

      {caseItem.ai_bucket === "needs_check" && caseItem.review_reason && (
        <p className="editAiReason" title={caseItem.review_reason}>
          Why AI flagged this: {caseItem.review_reason}
        </p>
      )}

      <div className="editFieldGrid">
        <label className="editField editFieldFine">
          <span>Fine (₹)</span>
          <input
            type="number"
            min={0}
            step="0.01"
            value={recoverable}
            disabled={disabled || saving}
            onChange={(event) => setRecoverable(event.target.value)}
            onBlur={() => void saveRecoverable()}
          />
        </label>
        <label className="editField editFieldSub">
          <span>Sub category</span>
          <input
            type="text"
            value={subCategory}
            disabled={disabled || saving}
            onChange={(event) => setSubCategory(event.target.value)}
            onBlur={() => void saveSubCategory()}
          />
        </label>
        <fieldset className="editOutcomeGroup editFieldOutcome" disabled={disabled || saving}>
          <legend>Outcome</legend>
          <div className="editOutcomeRow">
            {OUTCOME_OPTIONS.map((option) => (
              <label key={option.value} className="editOutcomeOption" title={option.help}>
                <input
                  type="radio"
                  name={`outcome-${caseItem.booking_id}`}
                  checked={outcome === option.value}
                  onChange={() => void saveOutcome(option.value)}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <label className="editField editFieldMessage">
          <span>Message</span>
          <textarea
            rows={1}
            value={message}
            disabled={disabled || saving}
            onChange={(event) => setMessage(event.target.value)}
            onBlur={() => void saveMessage()}
          />
        </label>
        <label className="editField editFieldRemarks">
          <span>Remarks</span>
          <textarea
            rows={1}
            value={remarks}
            disabled={disabled || saving}
            onChange={(event) => setRemarks(event.target.value)}
            onBlur={() => void saveRemarks()}
          />
        </label>
      </div>

      {commentsOpen && (
        <pre className="editCommentsBody">
          {caseItem.comments?.trim() || "No call comments for this booking."}
        </pre>
      )}

      {localError && (
        <p className="inlineAlert" role="alert">
          {localError}
        </p>
      )}
    </article>
  );
}

export default EditCaseCard;
