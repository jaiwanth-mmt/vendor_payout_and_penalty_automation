/**
 * JobUsagePage — job-scoped LLM token and estimated cost summary (last stage).
 */
import {
  CircleDollarSign,
  Clock3,
  Coins,
  Gauge,
  MessageSquareText,
  Sparkles,
} from "lucide-react";
import { Link } from "react-router-dom";

import { useJob } from "../context/JobProvider";
import type { LlmUsageByPurpose, LlmUsageSummary } from "../types/jobs";

function formatInt(value: number): string {
  return Math.round(value || 0).toLocaleString("en-IN");
}

function formatUsd(value: number): string {
  if (!Number.isFinite(value) || value === 0) return "$0.00";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function formatRate(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (Number.isInteger(value)) return `$${value.toFixed(2)}`;
  return `$${value.toFixed(2)}`;
}

function sharePercent(part: number, total: number): string {
  if (!total || total <= 0) return "—";
  return `${((part / total) * 100).toFixed(1)}%`;
}

function emptyUsage(): LlmUsageSummary {
  return {
    model: "gpt-5",
    pricing: {
      input_usd_per_1m: 1.25,
      output_usd_per_1m: 10,
      cached_input_usd_per_1m: 0.13,
      currency: "USD",
    },
    totals: {
      calls: 0,
      prompt_tokens: 0,
      completion_tokens: 0,
      cached_tokens: 0,
      total_tokens: 0,
      estimated_cost_usd: 0,
    },
    by_purpose: [],
    case_count: 0,
    notes: ["Vendor mailer uses no LLM"],
  };
}

export default function JobUsagePage() {
  const { jobId, job, isComplete } = useJob();

  if (!isComplete) {
    return (
      <div className="pageEmptySurface emptyState" role="status">
        <Clock3 size={22} />
        <div>
          <strong>Usage unlocks after the job succeeds</strong>
          <p>Token counts and estimated cost appear once packaging finishes.</p>
        </div>
        <Link className="ghostButton" to={`/jobs/${jobId}`}>
          Back to progress
        </Link>
      </div>
    );
  }

  const usage = job?.llm_usage ?? emptyUsage();
  const totals = usage.totals;
  const pricing = usage.pricing;
  const byPurpose: LlmUsageByPurpose[] = usage.by_purpose ?? [];
  const caseCount = usage.case_count || 0;
  const avgTokensPerCall =
    totals.calls > 0 ? totals.total_tokens / totals.calls : 0;
  const costPerCase = caseCount > 0 ? totals.estimated_cost_usd / caseCount : 0;

  return (
    <div className="usagePage">
      <section className="agentSurface">
        <div className="surfaceHeader agentHeader">
          <div className="previewTitle">
            <Coins size={22} />
            <div>
              <h2>LLM usage</h2>
              <p>
                Tokens and estimated cost for this job · model{" "}
                <strong>{usage.model}</strong>
              </p>
            </div>
          </div>
        </div>

        <div className="agentKpiGrid usageKpiGrid">
          <div className="agentKpiCard">
            <MessageSquareText size={18} />
            <span>Calls</span>
            <strong>{formatInt(totals.calls)}</strong>
          </div>
          <div className="agentKpiCard">
            <Sparkles size={18} />
            <span>Input tokens</span>
            <strong>{formatInt(totals.prompt_tokens)}</strong>
          </div>
          <div className="agentKpiCard">
            <Sparkles size={18} />
            <span>Output tokens</span>
            <strong>{formatInt(totals.completion_tokens)}</strong>
          </div>
          <div className="agentKpiCard">
            <CircleDollarSign size={18} />
            <span>Estimated cost (USD)</span>
            <strong>{formatUsd(totals.estimated_cost_usd)}</strong>
          </div>
        </div>

        <div className="usageRateCard">
          <div>
            <span className="eyebrow">Rate card</span>
            <p>
              {usage.model} · {formatRate(pricing.input_usd_per_1m)} / 1M input ·{" "}
              {formatRate(pricing.output_usd_per_1m)} / 1M output ·{" "}
              {formatRate(pricing.cached_input_usd_per_1m)} / 1M cached input
            </p>
          </div>
          <p className="usageDisclaimer">
            Cost is an estimate from configured rates, not an Azure invoice.
          </p>
        </div>

        <div className="agentVendorPanel usageBreakdownPanel">
          <div className="agentVendorPanelHeader">
            <strong>By stage</strong>
            <span>{byPurpose.length} groups</span>
          </div>
          {byPurpose.length === 0 ? (
            <div className="agentEmpty">
              <p>No LLM calls were recorded for this job.</p>
            </div>
          ) : (
            <div className="usageTableWrap">
              <table className="usageTable">
                <thead>
                  <tr>
                    <th scope="col">Stage</th>
                    <th scope="col">Calls</th>
                    <th scope="col">Input</th>
                    <th scope="col">Output</th>
                    <th scope="col">Cost</th>
                    <th scope="col">Share</th>
                  </tr>
                </thead>
                <tbody>
                  {byPurpose.map((row) => (
                    <tr key={row.purpose}>
                      <td>{row.label}</td>
                      <td>{formatInt(row.calls)}</td>
                      <td>{formatInt(row.prompt_tokens)}</td>
                      <td>{formatInt(row.completion_tokens)}</td>
                      <td>{formatUsd(row.estimated_cost_usd)}</td>
                      <td>
                        {sharePercent(
                          row.estimated_cost_usd,
                          totals.estimated_cost_usd,
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="usageEfficiencyStrip">
          <div className="agentKpiCard">
            <Gauge size={18} />
            <span>Avg tokens / call</span>
            <strong>{formatInt(avgTokensPerCall)}</strong>
          </div>
          <div className="agentKpiCard">
            <CircleDollarSign size={18} />
            <span>Est. cost / case</span>
            <strong>
              {caseCount > 0 ? formatUsd(costPerCase) : "—"}
            </strong>
          </div>
          <div className="agentKpiCard">
            <Sparkles size={18} />
            <span>Total tokens</span>
            <strong>{formatInt(totals.total_tokens)}</strong>
          </div>
        </div>

        {(usage.notes?.length ?? 0) > 0 && (
          <ul className="usageNotes">
            {usage.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
            {totals.cached_tokens > 0 && (
              <li>
                Cached input tokens this job: {formatInt(totals.cached_tokens)}
              </li>
            )}
          </ul>
        )}
      </section>
    </div>
  );
}
