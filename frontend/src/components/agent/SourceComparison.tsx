/** SourceComparison — source alignment comparison for AgentCockpit. */

import type { SourceAnalysis } from "../../types/jobs";
import { categoryText, statusLabel } from "./agentFormat";

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

export default SourceComparison;
