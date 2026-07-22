/** DecisionPair — specialist/judge decision cards for AgentCockpit. */

import type { AgentDecision } from "../../types/jobs";
import { statusLabel } from "./agentFormat";

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

export default DecisionPair;
