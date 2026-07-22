/** CaseListPanel — paginated evidence/trace list panel for AgentCockpit. */

import type { ReactNode } from "react";

import PaginationControls from "../PaginationControls";
import { AGENT_PAGE_SIZE, pageCount } from "./agentFormat";

function CaseListPanel<T>({
  title,
  items,
  page,
  noun,
  onPageChange,
  children,
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

export default CaseListPanel;
