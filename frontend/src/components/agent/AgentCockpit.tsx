/** AgentCockpit — orchestrator for agent review workspace. */

import {
  AlertTriangle,
  Bot,
  ClipboardList,
  Download,
  LoaderCircle,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  fetchAgentCase,
  fetchAgentCases,
  fetchGraphTopology,
  fetchReviewQueue,
  resumeAgentCase,
} from "../../api/jobs";
import type {
  AgentCase,
  GraphTopology,
  JobResponse,
  PendingInterrupt,
  ReviewQueueItem,
} from "../../types/jobs";
import BookingSearchForm from "../BookingSearchForm";
import PaginationControls from "../PaginationControls";
import { AGENT_PAGE_SIZE, formatAmount, pageCount, paginateLocal } from "./agentFormat";
import CaseDrawer from "./CaseDrawer";
import GraphTopologyPanel from "./GraphTopologyPanel";
import HitlPanel from "./HitlPanel";
import KpiCard from "./KpiCard";
import ReviewQueueRow from "./ReviewQueueRow";
import VendorPenaltySummary from "./VendorPenaltySummary";

type AgentCockpitProps = {
  job: JobResponse | null;
  isWorkspaceReady: boolean;
  isAwaitingReview?: boolean;
  showDownloadActions?: boolean;
  onDownloadAgentAudit: () => void;
  onDownloadReviewQueue: () => void;
  onRefreshJob?: () => Promise<void> | void;
};

function AgentCockpit({
  job,
  isWorkspaceReady,
  isAwaitingReview = false,
  showDownloadActions = false,
  onDownloadAgentAudit,
  onDownloadReviewQueue,
  onRefreshJob,
}: AgentCockpitProps) {
  const [casePage, setCasePage] = useState(1);
  const [casePageItems, setCasePageItems] = useState<AgentCase[]>([]);
  const [caseCount, setCaseCount] = useState(0);
  const [caseTotalPages, setCaseTotalPages] = useState(1);
  const [reviewPage, setReviewPage] = useState(1);
  const [reviewItems, setReviewItems] = useState<ReviewQueueItem[]>([]);
  const [reviewItemCount, setReviewItemCount] = useState(0);
  const [reviewTotalPages, setReviewTotalPages] = useState(1);
  const [activeCase, setActiveCase] = useState<AgentCase | null>(null);
  const [activeBookingId, setActiveBookingId] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [actionPage, setActionPage] = useState(1);
  const [isCasePageLoading, setIsCasePageLoading] = useState(false);
  const [isReviewLoading, setIsReviewLoading] = useState(false);
  const [isCaseDetailLoading, setIsCaseDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [topology, setTopology] = useState<GraphTopology | null>(null);
  const [resumeBusy, setResumeBusy] = useState<string | null>(null);
  const [showGraphs, setShowGraphs] = useState(false);

  const pendingInterrupts = job?.pending_interrupts ?? [];

  useEffect(() => {
    setCasePage(1);
    setCasePageItems([]);
    setCaseCount(0);
    setCaseTotalPages(1);
    setReviewPage(1);
    setReviewItems([]);
    setReviewItemCount(0);
    setReviewTotalPages(1);
    setActiveCase(null);
    setActiveBookingId(null);
    setSearchInput("");
    setActiveSearch("");
    setActionPage(1);
    setError(null);
    setTopology(null);
    setShowGraphs(false);
  }, [job?.job_id]);

  useEffect(() => {
    if (!isWorkspaceReady || !job?.job_id) return;
    let cancelled = false;
    fetchGraphTopology(job.job_id)
      .then((payload) => {
        if (!cancelled) setTopology(payload);
      })
      .catch(() => {
        if (!cancelled && job.graph_topology) setTopology(job.graph_topology as GraphTopology);
      });
    return () => {
      cancelled = true;
    };
  }, [isWorkspaceReady, job?.job_id]);

  async function handleResume(interrupt: PendingInterrupt, approve: boolean) {
    if (!job?.job_id) return;
    setResumeBusy(interrupt.booking_id);
    setError(null);
    try {
      const amount = Number(
        (interrupt.payload as { recoverable_amount?: number }).recoverable_amount ??
          (interrupt.payload as { judge_decision?: { recommended_recovery_amount?: number } }).judge_decision
            ?.recommended_recovery_amount ??
          0
      );
      await resumeAgentCase(job.job_id, interrupt.booking_id, {
        decision: approve ? "valid_penalty" : "needs_review",
        review_status: approve ? "auto_ready" : "needs_review",
        recommended_recovery_amount: approve ? amount : 0,
        review_reason: approve ? "Approved via LangGraph human review" : "Kept in review via LangGraph HITL",
        recommended_action: approve ? "Ready for Cab Ops recovery package" : "Review before operational action",
      });
      await onRefreshJob?.();
      // Reload review queue / cases after each resume so counts stay current during HITL.
      if (job.job_id) {
        try {
          const reviewPayload = await fetchReviewQueue(job.job_id, reviewPage);
          setReviewItems(reviewPayload.items);
          setReviewItemCount(reviewPayload.item_count);
          setReviewTotalPages(reviewPayload.total_pages);
        } catch {
          // refreshJob already updated snapshot; ignore secondary reload errors
        }
      }
    } catch (resumeError) {
      setError(resumeError instanceof Error ? resumeError.message : "Resume failed");
    } finally {
      setResumeBusy(null);
    }
  }

  useEffect(() => {
    if (!isWorkspaceReady || !job?.job_id) {
      setCasePageItems([]);
      setIsCasePageLoading(false);
      return;
    }

    let isCancelled = false;
    setIsCasePageLoading(true);
    setError(null);

    fetchAgentCases(job.job_id, casePage)
      .then((payload) => {
        if (isCancelled) return;
        setCasePageItems(payload.cases);
        setCaseCount(payload.case_count);
        setCaseTotalPages(payload.total_pages);
        if (payload.page !== casePage) {
          setCasePage(payload.page);
        }
        if (activeSearch) {
          return;
        }
        if (payload.cases.length > 0) {
          setActiveBookingId(payload.cases[0].booking_id);
          setActiveCase(payload.cases[0]);
        } else {
          setActiveBookingId(null);
          setActiveCase(null);
        }
      })
      .catch((caseError) => {
        if (!isCancelled) {
          setCasePageItems([]);
          setError(caseError instanceof Error ? caseError.message : "Unable to load agent cases");
        }
      })
      .finally(() => {
        if (!isCancelled) {
          setIsCasePageLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [casePage, isWorkspaceReady, job?.job_id]);

  useEffect(() => {
    if (!isWorkspaceReady || !job?.job_id) {
      setReviewItems([]);
      setIsReviewLoading(false);
      return;
    }

    let isCancelled = false;
    setIsReviewLoading(true);
    setError(null);

    fetchReviewQueue(job.job_id, reviewPage)
      .then((payload) => {
        if (isCancelled) return;
        setReviewItems(payload.items);
        setReviewItemCount(payload.item_count);
        setReviewTotalPages(payload.total_pages);
        if (payload.page !== reviewPage) {
          setReviewPage(payload.page);
        }
      })
      .catch((reviewError) => {
        if (!isCancelled) {
          setReviewItems([]);
          setError(reviewError instanceof Error ? reviewError.message : "Unable to load review queue");
        }
      })
      .finally(() => {
        if (!isCancelled) {
          setIsReviewLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [isWorkspaceReady, job?.job_id, reviewPage]);

  const summary = job?.agent_summary;
  const counts = job?.case_counts ?? {};
  const recommendedActions = summary?.recommended_actions ?? [];
  const pagedActions = paginateLocal(recommendedActions, actionPage);

  async function handleReviewSelect(bookingId: string) {
    if (!job?.job_id) return;
    setSearchInput("");
    setActiveSearch("");
    setActiveBookingId(bookingId);
    setIsCaseDetailLoading(true);
    setError(null);

    try {
      const payload = await fetchAgentCase(job.job_id, bookingId);
      setActiveCase(payload);
    } catch (caseError) {
      setError(caseError instanceof Error ? caseError.message : "Unable to load agent case");
    } finally {
      setIsCaseDetailLoading(false);
    }
  }

  function handleCaseSelect(item: AgentCase) {
    setSearchInput("");
    setActiveSearch("");
    setActiveBookingId(item.booking_id);
    setActiveCase(item);
  }

  function handleCasePageChange(nextPage: number) {
    setSearchInput("");
    setActiveSearch("");
    setActiveBookingId(null);
    setActiveCase(null);
    setCasePage(nextPage);
  }

  async function handleCaseSearch() {
    if (!job?.job_id) return;
    const trimmedSearch = searchInput.trim();
    if (!trimmedSearch) return;

    setSearchInput(trimmedSearch);
    setActiveSearch(trimmedSearch);
    setActiveBookingId(trimmedSearch);
    setActiveCase(null);
    setCasePage(1);
    setIsCaseDetailLoading(true);
    setError(null);

    try {
      const payload = await fetchAgentCase(job.job_id, trimmedSearch);
      setActiveCase(payload);
      setActiveBookingId(payload.booking_id);
    } catch (caseError) {
      setActiveBookingId(null);
      setError(caseError instanceof Error ? caseError.message : "Unable to load agent case");
    } finally {
      setIsCaseDetailLoading(false);
    }
  }

  function handleClearSearch() {
    setSearchInput("");
    setActiveSearch("");
    setCasePage(1);
    setError(null);

    const firstCase = casePageItems[0];
    if (firstCase) {
      setActiveBookingId(firstCase.booking_id);
      setActiveCase(firstCase);
    } else {
      setActiveBookingId(null);
      setActiveCase(null);
    }
  }

  return (
    <section className="agentSurface">
      <div className="surfaceHeader agentHeader">
        <div className="previewTitle">
          <Bot size={22} />
          <div>
            <h2>Agentic Loss Recovery Copilot</h2>
          </div>
        </div>
        <div className="agentActions">
          <BookingSearchForm
            inputId="agent-booking-search"
            value={searchInput}
            placeholder="Search booking ID"
            disabled={!isWorkspaceReady}
            isActive={Boolean(activeSearch)}
            onValueChange={setSearchInput}
            onSearch={handleCaseSearch}
            onClear={handleClearSearch}
          />
          <button
            className="ghostButton"
            type="button"
            disabled={!showDownloadActions}
            onClick={onDownloadReviewQueue}
          >
            <ClipboardList size={17} />
            <span>Review queue</span>
          </button>
          <button
            className="ghostButton"
            type="button"
            disabled={!showDownloadActions}
            onClick={onDownloadAgentAudit}
          >
            <Download size={17} />
            <span>Agent audit</span>
          </button>
        </div>
      </div>

      <VendorPenaltySummary summary={summary} isWorkspaceReady={isWorkspaceReady} />

      {(isAwaitingReview || pendingInterrupts.length > 0) && (
        <HitlPanel
          pendingInterrupts={pendingInterrupts}
          resumeBusy={resumeBusy}
          onResume={handleResume}
        />
      )}

      {topology?.case?.mermaid && (
        <GraphTopologyPanel
          topology={topology}
          showGraphs={showGraphs}
          onToggleShowGraphs={() => setShowGraphs((current) => !current)}
        />
      )}

      <div className="agentKpiGrid">
        <KpiCard icon={<ShieldCheck size={18} />} label="Auto-ready" value={counts.auto_ready ?? 0} />
        <KpiCard icon={<ClipboardList size={18} />} label="Needs review" value={counts.needs_review ?? 0} />
        <KpiCard icon={<AlertTriangle size={18} />} label="Missing source" value={counts.missing_evidence ?? 0} />
        <KpiCard
          icon={<Sparkles size={18} />}
          label="High-confidence recovery"
          value={formatAmount(summary?.high_confidence_recoverable_amount)}
        />
      </div>

      <div className="agentGrid">
        <div className="agentPanel">
          <div className="agentPanelHeader">
            <span>Review queue</span>
            <strong>{reviewItemCount}</strong>
          </div>
          <div className="reviewQueueList">
            {isReviewLoading ? (
              <div className="agentEmpty">
                <LoaderCircle className="spin" size={24} />
                <span>Loading review queue</span>
              </div>
            ) : (
              reviewItems.map((item) => (
                <ReviewQueueRow
                  item={item}
                  key={item.booking_id}
                  isActive={activeBookingId === item.booking_id}
                  onSelect={() => handleReviewSelect(item.booking_id)}
                />
              ))
            )}
            {!isReviewLoading && !reviewItems.length && (
              <div className="agentEmpty">
                <ShieldCheck size={24} />
                <span>
                  {isWorkspaceReady ? "No review blockers" : "Review queue appears after processing"}
                </span>
              </div>
            )}
          </div>
          <PaginationControls
            label="Review queue pagination"
            page={reviewPage}
            totalPages={reviewTotalPages}
            itemCount={reviewItemCount}
            pageSize={AGENT_PAGE_SIZE}
            noun="items"
            disabled={!isWorkspaceReady || isReviewLoading}
            onPageChange={setReviewPage}
          />
        </div>

        <div className="agentPanel">
          <div className="agentPanelHeader">
            <span>Portfolio actions</span>
            <strong>{recommendedActions.length}</strong>
          </div>
          <div className="actionList">
            {pagedActions.map((action) => (
              <p key={action}>{action}</p>
            ))}
            {!recommendedActions.length && (
              <div className="agentEmpty">
                <Sparkles size={24} />
                <span>Recommendations will appear here</span>
              </div>
            )}
          </div>
          {recommendedActions.length > AGENT_PAGE_SIZE && (
            <PaginationControls
              label="Portfolio actions pagination"
              page={actionPage}
              totalPages={pageCount(recommendedActions.length)}
              itemCount={recommendedActions.length}
              pageSize={AGENT_PAGE_SIZE}
              noun="actions"
              onPageChange={setActionPage}
            />
          )}
        </div>
      </div>

      {error && (
        <div className="inlineAlert agentError" role="alert">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      <CaseDrawer
        activeCase={activeCase}
        activeBookingId={activeBookingId}
        caseCount={caseCount}
        casePage={casePage}
        cases={casePageItems}
        caseTotalPages={caseTotalPages}
        isCaseDetailLoading={isCaseDetailLoading}
        isCasePageLoading={isCasePageLoading}
        onPageChange={handleCasePageChange}
        onSelect={handleCaseSelect}
      />
    </section>
  );
}

export default AgentCockpit;
