import type { VisibleMetric } from "../types/jobs";

type MetricsGridProps = {
  metrics: VisibleMetric[];
};

function MetricsGrid({ metrics }: MetricsGridProps) {
  if (metrics.length === 0) return null;

  return (
    <div className="metricGrid">
      {metrics.map((metric) => (
        <div className="metricTile" key={metric.key}>
          <span>{metric.label}</span>
          <strong>{metric.value}</strong>
        </div>
      ))}
    </div>
  );
}

export default MetricsGrid;

