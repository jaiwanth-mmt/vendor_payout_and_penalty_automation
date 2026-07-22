/** ToolCallCard — LangGraph tool call summary card for AgentCockpit. */

import type { ToolCallRecord } from "../../types/jobs";

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

export default ToolCallCard;
