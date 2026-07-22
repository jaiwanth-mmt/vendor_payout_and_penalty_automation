/** VendorPenaltySummary — vendor/subcategory penalty analysis for AgentCockpit. */

import { BarChart3, Building2 } from "lucide-react";

import type { AgentSummary, VendorSubcategorySummary } from "../../types/jobs";
import { formatAmount } from "./agentFormat";

function VendorPenaltySummary({
  summary,
  isWorkspaceReady,
}: {
  summary: AgentSummary | null | undefined;
  isWorkspaceReady: boolean;
}) {
  const topVendors = summary?.top_vendors_by_penalty ?? [];
  const topByPenalty = summary?.top_subcategories_by_penalty ?? [];
  const topByCount = summary?.top_subcategories_by_count ?? [];
  const hasAnalysis = topVendors.length > 0 || topByPenalty.length > 0 || topByCount.length > 0;

  if (!hasAnalysis) {
    return (
      <div className="agentVendorSummary">
        <div className="agentVendorPanel agentVendorEmptyPanel">
          <div className="agentEmpty">
            <Building2 size={24} />
            <span>{isWorkspaceReady ? "No vendor penalty data" : "Vendor analysis appears after processing"}</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="agentVendorSummary" aria-label="Vendor penalty analysis">
      <div className="agentVendorPanel">
        <div className="agentVendorPanelHeader">
          <span>Top vendor exposure</span>
          <Building2 size={16} />
        </div>
        <div className="vendorRankList">
          {topVendors.map((vendor, index) => (
            <div className="vendorRankRow" key={vendor.vendor_name}>
              <strong>{index + 1}</strong>
              <div>
                <span>{vendor.vendor_name}</span>
                <p>{vendor.case_count} cases</p>
              </div>
              <em>{formatAmount(vendor.total_recoverable)}</em>
            </div>
          ))}
        </div>
      </div>

      <div className="agentVendorPanel">
        <div className="agentVendorPanelHeader">
          <span>Top subcategories</span>
          <BarChart3 size={16} />
        </div>
        <div className="subcategorySummaryGrid">
          <SubcategorySummarySection title="By penalty" items={topByPenalty} />
          <SubcategorySummarySection title="By count" items={topByCount} />
        </div>
      </div>

      <div className="agentVendorPanel agentVendorPanelWide">
        <div className="agentVendorPanelHeader">
          <span>Vendor subcategory mix</span>
          <BarChart3 size={16} />
        </div>
        <div className="vendorMixList">
          {topVendors.slice(0, 3).map((vendor) => (
            <div className="vendorMixCard" key={vendor.vendor_name}>
              <div className="vendorMixCardHeader">
                <span>{vendor.vendor_name}</span>
                <strong>{formatAmount(vendor.total_recoverable)}</strong>
              </div>
              <div className="vendorMixRows">
                {vendor.top_subcategories.slice(0, 3).map((item, index) => (
                  <div className="vendorMixRow" key={item.subcategory}>
                    <span title={item.subcategory}>
                      {index + 1}. {item.subcategory}
                    </span>
                    <em>{item.case_count} cases</em>
                    <strong>{formatAmount(item.total_recoverable)}</strong>
                  </div>
                ))}
                {!vendor.top_subcategories.length && <p className="vendorMutedText">No subcategories</p>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SubcategorySummarySection({ title, items }: { title: string; items: VendorSubcategorySummary[] }) {
  return (
    <div className="subcategorySummarySection">
      <h3>{title}</h3>
      <SubcategorySummaryList items={items} />
    </div>
  );
}

function SubcategorySummaryList({ items }: { items: VendorSubcategorySummary[] }) {
  if (!items.length) {
    return <p className="vendorMutedText">No rows</p>;
  }

  return (
    <div className="subcategorySummaryList">
      {items.map((item) => (
        <div className="subcategorySummaryRow" key={item.subcategory}>
          <div>
            <span>{item.subcategory}</span>
            <em>{item.case_count} cases</em>
          </div>
          <strong>{formatAmount(item.total_recoverable)}</strong>
        </div>
      ))}
    </div>
  );
}

export default VendorPenaltySummary;
export { SubcategorySummarySection, SubcategorySummaryList };
