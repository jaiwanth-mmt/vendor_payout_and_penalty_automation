/** AgentCockpit — read-only aggregate recovery analysis after edits are approved. */

import {
  AlertTriangle,
  Bot,
  ClipboardList,
  LoaderCircle,
  PencilLine,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useState } from "react";

import type { JobResponse } from "../../types/jobs";
import PaginationControls from "../PaginationControls";
import { AGENT_PAGE_SIZE, formatAmount, pageCount, paginateLocal } from "./agentFormat";
import KpiCard from "./KpiCard";
import VendorPenaltySummary from "./VendorPenaltySummary";

type AgentCockpitProps = {
  job: JobResponse | null;
  isWorkspaceReady: boolean;
};

function AgentCockpit({ job, isWorkspaceReady }: AgentCockpitProps) {
  const [actionPage, setActionPage] = useState(1);

  const summary = job?.agent_summary;
  const counts = job?.case_counts ?? {};
  const recommendedActions = summary?.recommended_actions ?? [];
  const pagedActions = paginateLocal(recommendedActions, actionPage);
  const editedCaseCount = summary?.edited_case_count ?? Number(job?.metrics?.edited_case_count ?? 0);
  const excludedCaseCount = summary?.excluded_case_count ?? Number(job?.metrics?.excluded_case_count ?? 0);

  return (
    <section className="agentSurface">
      <div className="surfaceHeader agentHeader">
        <div className="previewTitle">
          <Bot size={22} />
          <div>
            <h2>Recovery analysis</h2>
            <p>Numbers below reflect your approved edits.</p>
          </div>
        </div>
      </div>

      <VendorPenaltySummary summary={summary} isWorkspaceReady={isWorkspaceReady} />

      <div className="agentKpiGrid">
        <KpiCard icon={<ShieldCheck size={18} />} label="Included in recovery" value={counts.auto_ready ?? 0} />
        <KpiCard icon={<ClipboardList size={18} />} label="Needs ops follow-up" value={counts.needs_review ?? 0} />
        <KpiCard icon={<PencilLine size={18} />} label="Edited bookings" value={editedCaseCount} />
        <KpiCard icon={<AlertTriangle size={18} />} label="Excluded" value={excludedCaseCount} />
        <KpiCard
          icon={<Sparkles size={18} />}
          label="High-confidence recovery"
          value={formatAmount(summary?.high_confidence_recoverable_amount)}
        />
      </div>

      <div className="agentPanel agentPanelWide">
        <div className="agentPanelHeader">
          <span>Recommended actions</span>
          <strong>{recommendedActions.length}</strong>
        </div>
        <div className="actionList">
          {!isWorkspaceReady ? (
            <div className="agentEmpty">
              <LoaderCircle className="spin" size={24} />
              <span>Analysis appears after packaging</span>
            </div>
          ) : (
            <>
              {pagedActions.map((action) => (
                <p key={action}>{action}</p>
              ))}
              {!recommendedActions.length && (
                <div className="agentEmpty">
                  <Sparkles size={24} />
                  <span>Recommendations will appear here</span>
                </div>
              )}
            </>
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
    </section>
  );
}

export default AgentCockpit;
