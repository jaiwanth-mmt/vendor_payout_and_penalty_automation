import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";

import type { WarningItem } from "../types/jobs";
import PaginationControls from "./PaginationControls";

type WarningsListProps = {
  warnings: WarningItem[];
};

const WARNING_PAGE_SIZE = 5;

function WarningsList({ warnings }: WarningsListProps) {
  if (warnings.length === 0) return null;

  return (
    <div className="warningStack">
      {warnings.map((warning) => (
        <WarningCard key={`${warning.code}-${warning.booking_ids.join("-")}`} warning={warning} />
      ))}
    </div>
  );
}

function WarningCard({ warning }: { warning: WarningItem }) {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(warning.booking_ids.length / WARNING_PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const startIndex = (safePage - 1) * WARNING_PAGE_SIZE;
  const visibleBookingIds = warning.booking_ids.slice(startIndex, startIndex + WARNING_PAGE_SIZE);

  useEffect(() => {
    setPage(1);
  }, [warning.code, warning.message]);

  return (
    <div className="warningItem">
      <AlertTriangle size={17} />
      <div>
        <span>{warning.message}</span>
        {warning.booking_ids.length > 0 && (
          <>
            <p>{visibleBookingIds.join(", ")}</p>
            <PaginationControls
              label={`${warning.code} warning booking IDs pagination`}
              page={safePage}
              totalPages={totalPages}
              itemCount={warning.booking_ids.length}
              pageSize={WARNING_PAGE_SIZE}
              noun="bookings"
              onPageChange={setPage}
            />
          </>
        )}
      </div>
    </div>
  );
}

export default WarningsList;
