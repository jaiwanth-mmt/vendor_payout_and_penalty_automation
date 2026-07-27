/**
 * VendorMailerPanel — frozen mail drafts + send-to-vendor action on Outputs.
 */
import { LoaderCircle, Mail, Send } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { previewVendorMails, sendVendorMails } from "../api/jobs";
import type { MailerDispatchResponse, MailerDraft } from "../types/jobs";

type VendorMailerPanelProps = {
  jobId: string;
  isComplete: boolean;
};

function resultForRecipient(mailer: MailerDispatchResponse | null, recipient: string) {
  return mailer?.results.find((item) => item.recipient === recipient) ?? null;
}

export default function VendorMailerPanel({ jobId, isComplete }: VendorMailerPanelProps) {
  const [mailer, setMailer] = useState<MailerDispatchResponse | null>(null);
  const [activeRecipient, setActiveRecipient] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isComplete || !jobId) {
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    previewVendorMails(jobId)
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setMailer(payload);
        setActiveRecipient(payload.drafts[0]?.recipient ?? payload.recipients[0] ?? "");
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message || "Unable to load mailer preview");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, isComplete]);

  const activeDraft: MailerDraft | null = useMemo(() => {
    if (!mailer) {
      return null;
    }
    return mailer.drafts.find((draft) => draft.recipient === activeRecipient) ?? mailer.drafts[0] ?? null;
  }, [mailer, activeRecipient]);

  const canSend = Boolean(mailer?.can_send && mailer.preview_token && !isSending && !isLoading);
  const sendDisabledReason =
    mailer?.status === "sent"
      ? "Vendor mails already sent for this job"
      : mailer?.status === "sending"
        ? "Send already in progress"
        : null;

  async function handleSend() {
    if (!mailer?.preview_token || !canSend) {
      return;
    }
    const recipientCount = mailer.recipients.length;
    const confirmed = window.confirm(
      `Send ${recipientCount} penalty email${recipientCount === 1 ? "" : "s"} to the configured recipient list?`
    );
    if (!confirmed) {
      return;
    }
    setIsSending(true);
    setError(null);
    try {
      const payload = await sendVendorMails(jobId, { preview_token: mailer.preview_token });
      setMailer(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to send vendor mails");
    } finally {
      setIsSending(false);
    }
  }

  return (
    <section className="vendorMailerSurface previewSurface" aria-label="Vendor penalty mailer">
      <div className="surfaceHeader">
        <div>
          <p className="eyebrow">Vendor mailer</p>
          <h2>Send mail to vendor</h2>
          <p>
            One frozen draft per configured recipient. Assignments stay fixed after preview; send is allowed once.
          </p>
        </div>
        <div className="finalOutputActions">
          <span className="statusPill" data-state={mailer?.status ?? "idle"}>
            {mailer?.status ?? "idle"}
          </span>
        </div>
      </div>

      {error ? (
        <div className="inlineAlert" role="alert">
          {error}
        </div>
      ) : null}

      {mailer?.status === "sent" ? (
        <div className="stageCta" data-tone="success" role="status">
          <div>
            <strong>Vendor mails sent</strong>
            <p>
              Delivered to {mailer.results.filter((item) => item.status === "sent").length} recipient
              {mailer.results.length === 1 ? "" : "s"}
              {mailer.sent_at ? ` at ${mailer.sent_at}` : ""}.
            </p>
          </div>
        </div>
      ) : null}

      {mailer?.status === "partial" || mailer?.status === "failed" ? (
        <div className="stageCta" data-tone="warning" role="status">
          <div>
            <strong>{mailer.status === "partial" ? "Partial delivery" : "Send failed"}</strong>
            <p>{mailer.error || "One or more recipient deliveries failed. You can retry."}</p>
          </div>
        </div>
      ) : null}

      {isLoading ? (
        <div className="tableEmpty" role="status">
          <LoaderCircle className="spin" size={18} />
          <span>Preparing mail drafts…</span>
        </div>
      ) : null}

      {!isLoading && mailer ? (
        <>
          <div className="tableFrame vendorMailAssignments">
            <table className="previewTable">
              <thead>
                <tr>
                  <th>Recipient</th>
                  <th>Booking ID</th>
                  <th>Subject</th>
                  <th>Send status</th>
                </tr>
              </thead>
              <tbody>
                {mailer.assignments.map((assignment) => {
                  const result = resultForRecipient(mailer, assignment.recipient);
                  return (
                    <tr key={`${assignment.recipient}:${assignment.booking_id}`}>
                      <td>{assignment.recipient}</td>
                      <td>{assignment.booking_id}</td>
                      <td>{assignment.subject}</td>
                      <td>
                        {result?.status ?? (mailer.status === "sent" ? "sent" : "pending")}
                        {result?.error ? (
                          <div className="mailSendError" title={result.error}>
                            {result.error}
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="categoryTabs" role="tablist" aria-label="Mail draft templates">
            {mailer.drafts.map((draft, index) => (
              <button
                key={draft.recipient}
                type="button"
                className="categoryTab"
                role="tab"
                data-active={activeDraft?.recipient === draft.recipient}
                onClick={() => setActiveRecipient(draft.recipient)}
              >
                <span>Mail {index + 1}</span>
                <strong>{draft.booking_id}</strong>
              </button>
            ))}
          </div>

          {activeDraft ? (
            <div className="mailTemplateBody">
              <div className="mailTemplateMeta">
                <p>
                  <strong>To</strong> {activeDraft.recipient}
                </p>
                <p>
                  <strong>Subject</strong> {activeDraft.subject}
                </p>
              </div>
              <div className="tableFrame">
                <table className="previewTable mailKeyValueTable">
                  <tbody>
                    {activeDraft.fields.map((field) => (
                      <tr key={`${activeDraft.recipient}:${field.key}`}>
                        <th>{field.key}</th>
                        <td className="previewTextCell">{field.value || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <details className="mailRawPreview">
                <summary>Plain-text body</summary>
                <pre>{activeDraft.text_body}</pre>
              </details>
            </div>
          ) : null}

          <div className="editApproveBar vendorMailSendBar">
            <div>
              <strong>
                <Mail size={16} /> {mailer.recipients.length} recipient
                {mailer.recipients.length === 1 ? "" : "s"}
              </strong>
              <p>
                {sendDisabledReason ||
                  "Uses MAILER_RECIPIENTS from backend .env. Edit that list to change who receives mail."}
              </p>
            </div>
            <button
              type="button"
              className="primaryButton"
              disabled={!canSend}
              onClick={() => {
                void handleSend();
              }}
            >
              {isSending ? <LoaderCircle className="spin" size={16} /> : <Send size={16} />}
              <span>{isSending ? "Sending…" : mailer.status === "sent" ? "Already sent" : "Send mail to vendor"}</span>
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}
