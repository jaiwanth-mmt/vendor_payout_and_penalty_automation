/** HitlPanel — HITL interrupt list panel for AgentCockpit. */

import { ShieldCheck } from "lucide-react";

import type { PendingInterrupt } from "../../types/jobs";

function HitlPanel({
  pendingInterrupts,
  resumeBusy,
  onResume,
}: {
  pendingInterrupts: PendingInterrupt[];
  resumeBusy: string | null;
  onResume: (interrupt: PendingInterrupt, approve: boolean) => void;
}) {
  return (
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
                onClick={() => onResume(item, true)}
              >
                Approve
              </button>
              <button
                className="ghostButton"
                type="button"
                disabled={resumeBusy === item.booking_id}
                onClick={() => onResume(item, false)}
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
  );
}

export default HitlPanel;
