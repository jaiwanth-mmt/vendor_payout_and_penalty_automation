import { AlertTriangle } from "lucide-react";

import type { WarningItem } from "../types/jobs";

type WarningsListProps = {
  warnings: WarningItem[];
};

function WarningsList({ warnings }: WarningsListProps) {
  if (warnings.length === 0) return null;

  return (
    <div className="warningStack">
      {warnings.map((warning) => (
        <div className="warningItem" key={`${warning.code}-${warning.booking_ids.join("-")}`}>
          <AlertTriangle size={17} />
          <div>
            <span>{warning.message}</span>
            {warning.booking_ids.length > 0 && <p>{warning.booking_ids.slice(0, 6).join(", ")}</p>}
          </div>
        </div>
      ))}
    </div>
  );
}

export default WarningsList;

