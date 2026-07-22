/** ReviewQueueRow — single review-queue row for AgentCockpit. */

import type { ReviewQueueItem } from "../../types/jobs";
import { categoryText, statusLabel } from "./agentFormat";

function ReviewQueueRow({
  item,
  isActive,
  onSelect,
}: {
  item: ReviewQueueItem;
  isActive: boolean;
  onSelect: () => void;
}) {
  return (
    <button className="reviewQueueRow" data-active={isActive} type="button" onClick={onSelect}>
      <div>
        <span>{item.booking_id}</span>
        <p>{item.review_reason}</p>
        <small>
          {item.source_used || "Source"}: {categoryText(item.source_categories || item.message)} · Row:{" "}
          {categoryText(item.row_categories)}
        </small>
      </div>
      <em data-status={item.review_status}>{statusLabel(item.review_status)}</em>
    </button>
  );
}

export default ReviewQueueRow;
