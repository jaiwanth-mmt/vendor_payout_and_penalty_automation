/** CaseDrawer — case list + detail dossier for AgentCockpit. */

import { Eye, EyeOff, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import type { AgentCase } from "../../types/jobs";
import PaginationControls from "../PaginationControls";
import { AGENT_PAGE_SIZE, paginateLocal, statusLabel } from "./agentFormat";
import CaseListPanel from "./CaseListPanel";
import DecisionPair from "./DecisionPair";
import EvidenceCard from "./EvidenceCard";
import EvidenceTeaser from "./EvidenceTeaser";
import SourceComparison from "./SourceComparison";
import ToolCallCard from "./ToolCallCard";
import TraceCard from "./TraceCard";

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
  onSelect,
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
                data-edited={item.was_edited ? "true" : "false"}
                className={item.was_edited ? "caseSelectorEdited" : undefined}
                key={item.booking_id}
                onClick={() => onSelect(item)}
                type="button"
              >
                {item.booking_id}
                {item.was_edited ? " · edited" : ""}
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

export default CaseDrawer;
