/** TraceCard — agent trace step card for AgentCockpit. */

import type { AgentTraceStep } from "../../types/jobs";

function TraceCard({ step }: { step: AgentTraceStep }) {
  return (
    <div className="traceItem" data-status={step.status}>
      <span>{step.agent}</span>
      <strong>{step.action.replace(/_/g, " ")}</strong>
      <p>{step.summary}</p>
    </div>
  );
}

export default TraceCard;
