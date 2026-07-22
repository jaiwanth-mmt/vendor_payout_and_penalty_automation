import {
  AlertTriangle,
  BarChart3,
  Bot,
  Building2,
  ClipboardList,
  Download,
  Eye,
  EyeOff,
  LoaderCircle,
  Network,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { fetchAgentCase, fetchAgentCases, fetchGraphTopology, fetchReviewQueue, resumeAgentCase } from "../api/jobs";
import type {
  AgentCase,
  AgentDecision,
  AgentSummary,
  AgentTraceStep,
  EvidenceItem,
  GraphTopology,
  JobResponse,
  PendingInterrupt,
  ReviewQueueItem,
  SourceAnalysis,
  ToolCallRecord,
  VendorSubcategorySummary,
} from "../types/jobs";
import BookingSearchForm from "./BookingSearchForm";
import MermaidDiagram from "./MermaidDiagram";
import PaginationControls from "./PaginationControls";

type AgentCockpitProps = {
  job: JobResponse | null;
  isComplete: boolean;
  isAwaitingReview?: boolean;
  onDownloadAgentAudit: () => void;
  onDownloadReviewQueue: () => void;
  onRefreshJob?: () => Promise<void> | void;
};

const AGENT_PAGE_SIZE = 5;

function formatAmount(value: number | string | undefined): string {
  const numberValue = Number(value ?? 0);
  return `₹${numberValue.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function statusLabel(value: string): string {
  return value.replace(/_/g, " ");
}

function categoryText(value: string[] | string | null | undefined): string {
  if (Array.isArray(value)) {
    return value.filter(Boolean).join(" + ") || "No category";
  }
  return value?.trim() || "No category";
}

function pageCount(itemCount: number): number {
  return Math.max(1, Math.ceil(itemCount / AGENT_PAGE_SIZE));
}

function paginateLocal<T>(items: T[], page: number): T[] {
  const safePage = Math.min(page, pageCount(items.length));
  const startIndex = (safePage - 1) * AGENT_PAGE_SIZE;
  return items.slice(startIndex, startIndex + AGENT_PAGE_SIZE);
}

function AgentCockpit({
  job,
  isComplete,
  isAwaitingReview = false,
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
    if (!isComplete || !job?.job_id) return;
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
  }, [isComplete, job?.job_id]);

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
    if (!isComplete || !job?.job_id) {
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
  }, [casePage, isComplete, job?.job_id]);

  useEffect(() => {
    if (!isComplete || !job?.job_id) {
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
  }, [isComplete, job?.job_id, reviewPage]);

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
            disabled={!isComplete}
            isActive={Boolean(activeSearch)}
            onValueChange={setSearchInput}
            onSearch={handleCaseSearch}
            onClear={handleClearSearch}
          />
          <button className="ghostButton" type="button" disabled={!isComplete} onClick={onDownloadReviewQueue}>
            <ClipboardList size={17} />
            <span>Review queue</span>
          </button>
          <button className="ghostButton" type="button" disabled={!isComplete} onClick={onDownloadAgentAudit}>
            <Download size={17} />
            <span>Agent audit</span>
          </button>
        </div>
      </div>

      <VendorPenaltySummary summary={summary} isComplete={isComplete} />

      {(isAwaitingReview || pendingInterrupts.length > 0) && (
        <div className="agentPanel hitlPanel">
          <div className="agentPanelHeader">
            <span>LangGraph human review</span>
            <strong>{pendingInterrupts.length}</strong>
          </div>
          <div className="reviewQueueList">
            {pendingInterrupts.map((item) => (
              <div className="hitlRow" key={item.booking_id}>
                <div>
                  <strong>{item.booking_id}</strong>
                  <p>{String((item.payload as { review_reason?: string }).review_reason || "Awaiting review")}</p>
                </div>
                <div className="hitlActions">
                  <button
                    className="ghostButton"
                    type="button"
                    disabled={resumeBusy === item.booking_id}
                    onClick={() => handleResume(item, true)}
                  >
                    Approve
                  </button>
                  <button
                    className="ghostButton"
                    type="button"
                    disabled={resumeBusy === item.booking_id}
                    onClick={() => handleResume(item, false)}
                  >
                    Keep review
                  </button>
                </div>
              </div>
            ))}
            {!pendingInterrupts.length && (
              <div className="agentEmpty">
                <ShieldCheck size={24} />
                <span>No pending interrupts</span>
              </div>
            )}
          </div>
        </div>
      )}

      {topology?.case?.mermaid && (
        <div className="agentPanel graphTopologyPanel">
          <div className="agentPanelHeader">
            <div className="graphTopologyTitle">
              <Network size={16} aria-hidden="true" />
              <span>Investigation graphs</span>
            </div>
            <button
              aria-expanded={showGraphs}
              className="ghostButton graphRevealButton"
              type="button"
              onClick={() => setShowGraphs((current) => !current)}
            >
              {showGraphs ? <EyeOff size={16} /> : <Eye size={16} />}
              <span>{showGraphs ? "Hide graphs" : "View graphs"}</span>
            </button>
          </div>
          {!showGraphs ? (
            <p className="graphTopologyHint">
              Case and portfolio LangGraph topology stay collapsed until you need them.
            </p>
          ) : (
            <div className="graphTopologyGrid">
              <div className="graphTopologyCard">
                <div className="agentPanelHeader">
                  <span>Case investigation graph</span>
                  <strong>{topology.case.nodes?.length ?? 0} nodes</strong>
                </div>
                <MermaidDiagram chart={topology.case.mermaid} className="mermaidDiagram" />
              </div>
              {topology.portfolio?.mermaid && (
                <div className="graphTopologyCard">
                  <div className="agentPanelHeader">
                    <span>Portfolio graph</span>
                    <strong>{topology.portfolio.nodes?.length ?? 0} nodes</strong>
                  </div>
                  <MermaidDiagram chart={topology.portfolio.mermaid} className="mermaidDiagram" />
                </div>
              )}
            </div>
          )}
        </div>
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
                <span>{isComplete ? "No review blockers" : "Review queue appears after processing"}</span>
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
            disabled={!isComplete || isReviewLoading}
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

function VendorPenaltySummary({ summary, isComplete }: { summary: AgentSummary | null | undefined; isComplete: boolean }) {
  const topVendors = summary?.top_vendors_by_penalty ?? [];
  const topByPenalty = summary?.top_subcategories_by_penalty ?? [];
  const topByCount = summary?.top_subcategories_by_count ?? [];
  const hasAnalysis = topVendors.length > 0 || topByPenalty.length > 0 || topByCount.length > 0;

  if (!hasAnalysis) {
    return (
      <div className="agentVendorSummary">
        <div className="agentVendorPanel agentVendorEmptyPanel">
          <div className="agentEmpty">
            <Building2 size={24} />
            <span>{isComplete ? "No vendor penalty data" : "Vendor analysis appears after processing"}</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="agentVendorSummary" aria-label="Vendor penalty analysis">
      <div className="agentVendorPanel">
        <div className="agentVendorPanelHeader">
          <span>Top vendor exposure</span>
          <Building2 size={16} />
        </div>
        <div className="vendorRankList">
          {topVendors.map((vendor, index) => (
            <div className="vendorRankRow" key={vendor.vendor_name}>
              <strong>{index + 1}</strong>
              <div>
                <span>{vendor.vendor_name}</span>
                <p>{vendor.case_count} cases</p>
              </div>
              <em>{formatAmount(vendor.total_recoverable)}</em>
            </div>
          ))}
        </div>
      </div>

      <div className="agentVendorPanel">
        <div className="agentVendorPanelHeader">
          <span>Top subcategories</span>
          <BarChart3 size={16} />
        </div>
        <div className="subcategorySummaryGrid">
          <SubcategorySummarySection title="By penalty" items={topByPenalty} />
          <SubcategorySummarySection title="By count" items={topByCount} />
        </div>
      </div>

      <div className="agentVendorPanel agentVendorPanelWide">
        <div className="agentVendorPanelHeader">
          <span>Vendor subcategory mix</span>
          <BarChart3 size={16} />
        </div>
        <div className="vendorMixList">
          {topVendors.slice(0, 3).map((vendor) => (
            <div className="vendorMixCard" key={vendor.vendor_name}>
              <div className="vendorMixCardHeader">
                <span>{vendor.vendor_name}</span>
                <strong>{formatAmount(vendor.total_recoverable)}</strong>
              </div>
              <div className="vendorMixRows">
                {vendor.top_subcategories.slice(0, 3).map((item, index) => (
                  <div className="vendorMixRow" key={item.subcategory}>
                    <span title={item.subcategory}>
                      {index + 1}. {item.subcategory}
                    </span>
                    <em>{item.case_count} cases</em>
                    <strong>{formatAmount(item.total_recoverable)}</strong>
                  </div>
                ))}
                {!vendor.top_subcategories.length && <p className="vendorMutedText">No subcategories</p>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SubcategorySummarySection({ title, items }: { title: string; items: VendorSubcategorySummary[] }) {
  return (
    <div className="subcategorySummarySection">
      <h3>{title}</h3>
      <SubcategorySummaryList items={items} />
    </div>
  );
}

function SubcategorySummaryList({ items }: { items: VendorSubcategorySummary[] }) {
  if (!items.length) {
    return <p className="vendorMutedText">No rows</p>;
  }

  return (
    <div className="subcategorySummaryList">
      {items.map((item) => (
        <div className="subcategorySummaryRow" key={item.subcategory}>
          <div>
            <span>{item.subcategory}</span>
            <em>{item.case_count} cases</em>
          </div>
          <strong>{formatAmount(item.total_recoverable)}</strong>
        </div>
      ))}
    </div>
  );
}

function KpiCard({ icon, label, value }: { icon: ReactNode; label: string; value: string | number }) {
  return (
    <div className="agentKpiCard">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ReviewQueueRow({
  item,
  isActive,
  onSelect
}: {
  item: ReviewQueueItem;
  isActive: boolean;
  onSelect: () => void;
}) {
  return (
    <button className="reviewQueueRow" data-active={isActive} type="button" onClick={onSelect}>
      <div>
        <span>{item.booking_id}</span>
        <p>{item.review_reason}</p>
        <small>
          {item.source_used || "Source"}: {categoryText(item.source_categories || item.message)} · Row:{" "}
          {categoryText(item.row_categories)}
        </small>
      </div>
      <em data-status={item.review_status}>{statusLabel(item.review_status)}</em>
    </button>
  );
}

function CaseDrawer({
  activeCase,
  activeBookingId,
  caseCount,
  casePage,
  cases,
  caseTotalPages,
  isCaseDetailLoading,
  isCasePageLoading,
  onPageChange,
  onSelect
}: {
  activeCase: AgentCase | null;
  activeBookingId: string | null;
  caseCount: number;
  casePage: number;
  cases: AgentCase[];
  caseTotalPages: number;
  isCaseDetailLoading: boolean;
  isCasePageLoading: boolean;
  onPageChange: (page: number) => void;
  onSelect: (agentCase: AgentCase) => void;
}) {
  const [evidencePage, setEvidencePage] = useState(1);
  const [tracePage, setTracePage] = useState(1);
  const [showFullEvidence, setShowFullEvidence] = useState(false);

  useEffect(() => {
    setEvidencePage(1);
    setTracePage(1);
    setShowFullEvidence(false);
  }, [activeCase?.booking_id]);

  if (!activeCase && !isCasePageLoading) return null;

  const decision = activeCase?.final_decision;
  const specialist = activeCase?.specialist_decision;
  const judge = activeCase?.judge_decision;
  const evidence = activeCase?.evidence ?? [];
  const trace = activeCase?.trace ?? [];
  const toolCalls = activeCase?.tool_calls ?? [];
  const pagedEvidence = paginateLocal(evidence, evidencePage);
  const pagedTrace = paginateLocal(trace, tracePage);

  return (
    <div className="caseDrawer">
      <div className="caseSelectorPanel">
        <div className="caseSelector">
          {isCasePageLoading ? (
            <div className="agentEmpty">
              <LoaderCircle className="spin" size={22} />
              <span>Loading cases</span>
            </div>
          ) : (
            cases.map((item) => (
              <button
                data-active={item.booking_id === activeBookingId}
                key={item.booking_id}
                onClick={() => onSelect(item)}
                type="button"
              >
                {item.booking_id}
              </button>
            ))
          )}
        </div>
        <PaginationControls
          label="Agent cases pagination"
          page={casePage}
          totalPages={caseTotalPages}
          itemCount={caseCount}
          pageSize={AGENT_PAGE_SIZE}
          noun="cases"
          disabled={isCasePageLoading}
          onPageChange={onPageChange}
        />
      </div>

      <div className="caseDetail">
        {isCaseDetailLoading || !activeCase ? (
          <div className="agentEmpty caseDetailLoading">
            <LoaderCircle className="spin" size={26} />
            <span>Loading case detail</span>
          </div>
        ) : (
          <>
            <div className="caseHero">
              <div>
                <span>{activeCase.sub_category}</span>
                <h3>{activeCase.booking_id}</h3>
                {decision && (
                  <div className="decisionSource" data-source={decision.decision_source}>
                    {decision.decision_source === "llm" ? "LLM decision" : "Fallback decision"}
                  </div>
                )}
                <p>{decision?.rationale}</p>
                <SourceComparison analysis={activeCase.source_analysis} />
                <DecisionPair specialist={specialist} judge={judge} />
                {toolCalls.length > 0 && (
                  <div className="toolCallList">
                    <span>LangGraph tools</span>
                    {toolCalls.map((call, index) => (
                      <ToolCallCard call={call} key={`${call.name}-${index}`} />
                    ))}
                  </div>
                )}
                {decision?.llm_error && <small>{decision.llm_error}</small>}
              </div>
              <div className="confidenceBadge" data-status={activeCase.review_status}>
                <strong>{Math.round((decision?.confidence ?? 0) * 100)}%</strong>
                <span>{statusLabel(activeCase.review_status)}</span>
              </div>
            </div>

            <div className="caseColumns" data-evidence-expanded={showFullEvidence}>
              <div className="evidenceColumn">
                <div className="evidenceColumnHeader">
                  <h4>Evidence</h4>
                  {evidence.length > 0 && (
                    <button
                      aria-expanded={showFullEvidence}
                      className="ghostButton evidenceRevealButton"
                      type="button"
                      onClick={() => setShowFullEvidence((current) => !current)}
                    >
                      {showFullEvidence ? <EyeOff size={15} /> : <Eye size={15} />}
                      <span>{showFullEvidence ? "Hide evidence" : "View full evidence"}</span>
                    </button>
                  )}
                </div>
                {evidence.length === 0 ? (
                  <div className="evidenceEmpty">No evidence items for this case.</div>
                ) : showFullEvidence ? (
                  <CaseListPanel
                    title=""
                    items={evidence}
                    page={evidencePage}
                    noun="evidence"
                    onPageChange={setEvidencePage}
                  >
                    {pagedEvidence.map((item) => (
                      <EvidenceCard item={item} key={item.id} />
                    ))}
                  </CaseListPanel>
                ) : (
                  <EvidenceTeaser evidence={evidence} />
                )}
              </div>
              <CaseListPanel
                title="Trace"
                items={trace}
                page={tracePage}
                noun="steps"
                onPageChange={setTracePage}
              >
                {pagedTrace.map((step, index) => (
                  <TraceCard step={step} key={`${step.agent}-${step.action}-${index}`} />
                ))}
              </CaseListPanel>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function DecisionPair({
  specialist,
  judge,
}: {
  specialist: AgentDecision | null | undefined;
  judge: AgentDecision | null | undefined;
}) {
  if (!specialist && !judge) return null;
  return (
    <div className="decisionPair">
      {specialist && (
        <div className="decisionCard">
          <span className="decisionRole">Specialist</span>
          <strong className="decisionAgent">{specialist.agent}</strong>
          <p className="decisionMeta">
            {statusLabel(specialist.review_status)} · {Math.round(specialist.confidence * 100)}%
          </p>
          <small className="decisionBody">{specialist.rationale}</small>
        </div>
      )}
      {judge && (
        <div className="decisionCard">
          <span className="decisionRole">Judge</span>
          <strong className="decisionAgent">{judge.agent}</strong>
          <p className="decisionMeta">
            {statusLabel(judge.review_status)} · {Math.round(judge.confidence * 100)}%
          </p>
          <small className="decisionBody">{judge.review_reason || judge.rationale}</small>
        </div>
      )}
    </div>
  );
}

function ToolCallCard({ call }: { call: ToolCallRecord }) {
  return (
    <article className="toolCallCard" data-status={call.status}>
      <div className="toolCallHeader">
        <strong>{call.name}</strong>
        <em>{call.status}</em>
      </div>
      <p>{call.summary}</p>
    </article>
  );
}

function SourceComparison({ analysis }: { analysis: SourceAnalysis | null | undefined }) {
  if (!analysis) return null;
  const sourceCategories = analysis.source_categories ?? [];
  const rowCategories = analysis.row_categories ?? [];

  return (
    <div className="sourceComparison" aria-label="Source alignment">
      <div>
        <span>Source</span>
        <strong>{analysis.source_label || "No source"}</strong>
        <p>{categoryText(sourceCategories.length ? sourceCategories : analysis.message)}</p>
      </div>
      <div>
        <span>Row</span>
        <strong>{rowCategories.length ? "Context" : "No row category"}</strong>
        <p>{categoryText(rowCategories)}</p>
      </div>
      <div>
        <span>Reason</span>
        <strong>{statusLabel(analysis.status || analysis.review_status)}</strong>
        <p>{analysis.reason || "No source-alignment reason available."}</p>
      </div>
    </div>
  );
}

function CaseListPanel<T>({
  title,
  items,
  page,
  noun,
  onPageChange,
  children
}: {
  title: string;
  items: T[];
  page: number;
  noun: string;
  onPageChange: (page: number) => void;
  children: ReactNode;
}) {
  return (
    <div>
      {title ? <h4>{title}</h4> : null}
      <div className={noun === "evidence" ? "evidenceList" : "traceList"}>{children}</div>
      {items.length > AGENT_PAGE_SIZE && (
        <PaginationControls
          label={`${title || noun} pagination`}
          page={page}
          totalPages={pageCount(items.length)}
          itemCount={items.length}
          pageSize={AGENT_PAGE_SIZE}
          noun={noun}
          onPageChange={onPageChange}
        />
      )}
    </div>
  );
}

function EvidenceTeaser({ evidence }: { evidence: EvidenceItem[] }) {
  const previewItems = evidence.slice(0, 4);
  const remaining = Math.max(0, evidence.length - previewItems.length);

  return (
    <div className="evidenceTeaser">
      <p>
        {evidence.length} evidence item{evidence.length === 1 ? "" : "s"} collected. Open the full
        dossier for field-level detail.
      </p>
      <ul className="evidenceTeaserList">
        {previewItems.map((item) => (
          <li key={item.id}>
            <strong>{item.title}</strong>
            <em>{item.source}</em>
          </li>
        ))}
        {remaining > 0 && <li className="evidenceTeaserMore">+{remaining} more</li>}
      </ul>
    </div>
  );
}

function EvidenceCard({ item }: { item: EvidenceItem }) {
  const [fieldPage, setFieldPage] = useState(1);
  const fieldEntries = Object.entries(item.fields ?? {});
  const pagedFieldEntries = paginateLocal(fieldEntries, fieldPage);

  useEffect(() => {
    setFieldPage(1);
  }, [item.id]);

  return (
    <div className="evidenceCard" data-status={item.status}>
      <div>
        <span>{item.title}</span>
        <em>{item.source}</em>
      </div>
      <p>{item.summary}</p>
      {fieldEntries.length > 0 && (
        <>
          <dl>
            {pagedFieldEntries.map(([key, value]) => (
              <div key={key}>
                <dt>{key.replace(/_/g, " ")}</dt>
                <dd>{Array.isArray(value) ? value.join(", ") : String(value)}</dd>
              </div>
            ))}
          </dl>
          {fieldEntries.length > AGENT_PAGE_SIZE && (
            <PaginationControls
              label={`${item.title} fields pagination`}
              page={fieldPage}
              totalPages={pageCount(fieldEntries.length)}
              itemCount={fieldEntries.length}
              pageSize={AGENT_PAGE_SIZE}
              noun="fields"
              onPageChange={setFieldPage}
            />
          )}
        </>
      )}
    </div>
  );
}

function TraceCard({ step }: { step: AgentTraceStep }) {
  return (
    <div className="traceItem" data-status={step.status}>
      <span>{step.agent}</span>
      <strong>{step.action.replace(/_/g, " ")}</strong>
      <p>{step.summary}</p>
    </div>
  );
}

export default AgentCockpit;
