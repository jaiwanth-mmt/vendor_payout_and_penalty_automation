/** agentFormat — shared formatting and pagination helpers for AgentCockpit. */

export const AGENT_PAGE_SIZE = 5;

export function formatAmount(value: number | string | undefined): string {
  const numberValue = Number(value ?? 0);
  return `₹${numberValue.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export function statusLabel(value: string): string {
  return value.replace(/_/g, " ");
}

export function categoryText(value: string[] | string | null | undefined): string {
  if (Array.isArray(value)) {
    return value.filter(Boolean).join(" + ") || "No category";
  }
  return value?.trim() || "No category";
}

export function pageCount(itemCount: number): number {
  return Math.max(1, Math.ceil(itemCount / AGENT_PAGE_SIZE));
}

export function paginateLocal<T>(items: T[], page: number): T[] {
  const safePage = Math.min(page, pageCount(items.length));
  const startIndex = (safePage - 1) * AGENT_PAGE_SIZE;
  return items.slice(startIndex, startIndex + AGENT_PAGE_SIZE);
}
