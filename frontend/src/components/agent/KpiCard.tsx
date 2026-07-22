/** KpiCard — KPI tile for AgentCockpit summary metrics. */

import type { ReactNode } from "react";

function KpiCard({ icon, label, value }: { icon: ReactNode; label: string; value: string | number }) {
  return (
    <div className="agentKpiCard">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export default KpiCard;
