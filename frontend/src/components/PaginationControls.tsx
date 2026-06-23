import { ChevronLeft, ChevronRight } from "lucide-react";

type PaginationControlsProps = {
  label: string;
  page: number;
  totalPages: number;
  itemCount: number;
  pageSize: number;
  disabled?: boolean;
  noun?: string;
  onPageChange: (page: number) => void;
};

function PaginationControls({
  label,
  page,
  totalPages,
  itemCount,
  pageSize,
  disabled = false,
  noun = "items",
  onPageChange
}: PaginationControlsProps) {
  const firstVisibleItem = itemCount ? (page - 1) * pageSize + 1 : 0;
  const lastVisibleItem = itemCount ? Math.min(page * pageSize, itemCount) : 0;
  const countText = itemCount
    ? `${firstVisibleItem.toLocaleString()}-${lastVisibleItem.toLocaleString()} of ${itemCount.toLocaleString()} ${noun}`
    : `0 ${noun}`;

  return (
    <div className="compactPagination" aria-label={label}>
      <span>{countText}</span>
      <div className="pagerButtons">
        <button
          aria-label={`Previous ${label}`}
          type="button"
          disabled={disabled || page <= 1}
          onClick={() => onPageChange(Math.max(1, page - 1))}
        >
          <ChevronLeft size={16} />
        </button>
        <strong>
          Page {page} of {totalPages}
        </strong>
        <button
          aria-label={`Next ${label}`}
          type="button"
          disabled={disabled || page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}

export default PaginationControls;
