"use client";

import { useEffect, useState } from "react";
import { getUsage, type UsageReport } from "@/lib/api";
import { PageHeader, Panel, fmtNum } from "@/components/ui";

const RANGES = [1, 7, 30, 90];

export function UsageView() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<UsageReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getUsage(days)
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load usage"));
  }, [days]);

  const t = data?.totals;
  const maxDay = Math.max(1, ...(data?.by_day.map((d) => d.prompt_tokens + d.completion_tokens) ?? [1]));

  return (
    <div className="relative z-10 flex h-full min-h-0 flex-1 flex-col">
      <PageHeader title="Usage" subtitle="Tokens and latency of every agent request — all local, all free">
        <div className="flex rounded-lg border border-[var(--border)] p-0.5">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setDays(r)}
              className={`rounded-md px-2.5 py-1 text-[12px] ${
                days === r ? "bg-[var(--bg-hover)] text-[var(--text)]" : "text-[var(--text-muted)] hover:text-[var(--text)]"
              }`}
            >
              {r === 1 ? "24h" : `${r}d`}
            </button>
          ))}
        </div>
      </PageHeader>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-5xl flex-col gap-5">
          {error && <p className="text-[13px] text-[var(--danger)]">{error}</p>}

          <div className="cascade grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label="Requests" value={fmtNum(t?.requests)} />
            <Stat label="Prompt tokens" value={fmtNum(t?.prompt_tokens)} />
            <Stat label="Output tokens" value={fmtNum(t?.completion_tokens)} />
            <Stat
              label="Avg latency"
              value={t?.requests ? `${(t.duration_ms / t.requests / 1000).toFixed(1)}s` : "—"}
            />
            <Stat label="Tool calls" value={fmtNum(t?.tool_calls)} />
          </div>

          <Panel title="Tokens per day">
            {data?.by_day.length ? (
              <div className="flex h-32 items-end gap-1">
                {data.by_day.map((d) => {
                  const total = d.prompt_tokens + d.completion_tokens;
                  return (
                    <div
                      key={d.day}
                      className="group relative flex-1 origin-bottom rounded-t transition-[height] duration-500 bg-[color-mix(in_srgb,var(--accent)_55%,transparent)] hover:bg-[var(--accent)]"
                      style={{ height: `${Math.max(3, (total / maxDay) * 100)}%` }}
                      title={`${d.day}: ${fmtNum(total)} tokens · ${d.requests} requests`}
                    />
                  );
                })}
              </div>
            ) : (
              <Empty />
            )}
          </Panel>

          <Panel title="By model">
            {data?.by_model.length ? (
              <Table
                head={["Model", "Requests", "Prompt", "Output", "Avg latency", "Tok/s", "Tools"]}
                rows={data.by_model.map((m) => [
                  <code key="m" className="text-[var(--text)]">{m.model}</code>,
                  fmtNum(m.requests),
                  fmtNum(m.prompt_tokens),
                  fmtNum(m.completion_tokens),
                  `${(m.duration_ms / Math.max(1, m.requests) / 1000).toFixed(1)}s`,
                  m.duration_ms ? (m.completion_tokens / (m.duration_ms / 1000)).toFixed(1) : "—",
                  fmtNum(m.tool_calls),
                ])}
              />
            ) : (
              <Empty />
            )}
          </Panel>

          <Panel title="Recent requests">
            {data?.recent.length ? (
              <Table
                head={["When", "Chat", "Model", "Source", "Prompt", "Output", "Time", "Tools"]}
                rows={data.recent.map((r) => [
                  new Date(r.created_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" }),
                  <span key="c" className="block max-w-[200px] truncate">{r.conversation_title || "—"}</span>,
                  <code key="m">{r.model}</code>,
                  r.source,
                  fmtNum(r.prompt_tokens),
                  fmtNum(r.completion_tokens),
                  `${(r.duration_ms / 1000).toFixed(1)}s`,
                  r.tool_calls,
                ])}
              />
            ) : (
              <Empty />
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] px-4 py-3.5">
      <div className="text-[11px] uppercase tracking-[0.06em] text-[var(--text-dim)]">{label}</div>
      <div className="mt-1 text-[22px] font-medium tracking-[-0.02em]">{value}</div>
    </div>
  );
}

function Empty() {
  return <p className="text-[12.5px] text-[var(--text-dim)]">No requests in this range yet.</p>;
}

export function Table({ head, rows }: { head: string[]; rows: React.ReactNode[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[12.5px]">
        <thead>
          <tr className="border-b border-[var(--border)] text-[11px] uppercase tracking-[0.05em] text-[var(--text-dim)]">
            {head.map((h, i) => (
              <th key={h} className={`py-2 pr-4 font-medium ${i > 0 ? "whitespace-nowrap" : ""}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-[var(--border)] last:border-0 text-[var(--text-muted)] hover:bg-[var(--bg-hover)]">
              {row.map((cell, j) => (
                <td key={j} className="py-2 pr-4 whitespace-nowrap tabular-nums">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
