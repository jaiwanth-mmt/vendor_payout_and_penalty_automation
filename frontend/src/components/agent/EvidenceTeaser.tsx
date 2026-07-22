/** EvidenceTeaser — collapsed evidence preview for AgentCockpit. */

import type { EvidenceItem } from "../../types/jobs";

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

export default EvidenceTeaser;
