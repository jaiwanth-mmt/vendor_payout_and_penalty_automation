/** EvidenceCard — full evidence item with field pagination for AgentCockpit. */

import { useEffect, useState } from "react";

import type { EvidenceItem } from "../../types/jobs";
import PaginationControls from "../PaginationControls";
import { AGENT_PAGE_SIZE, pageCount, paginateLocal } from "./agentFormat";

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

export default EvidenceCard;
