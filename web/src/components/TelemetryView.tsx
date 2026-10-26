"use client";

import { useCallback, useEffect, useState } from "react";
import { clearTelemetry, getTelemetry, type Phases, type TelemetryReport, type TraceRow } from "@/lib/api";
import { PageHeader, Panel, fmtBytes, fmtNum } from "@/components/ui";
import { Stat, Table } from "@/components/UsageView";

const RANGES = [1, 7, 30];

const PHASES: { key: keyof Phases; label: string; color: string; hint: string }[] = [
  { key: "load_ms", label: "Model load", color: "#e0b252", hint: "Loading weights into memory (cold start)" },
  { key: "prompt_ms", label: "Prefill", color: "#6aa6ff", hint: "Reading the prompt: system, history, tool schemas" },
  { key: "eval_ms", label: "Generation", color: "var(--accent)", hint: "Producing output tokens" },
  { key: "tool_ms", label: "Tools", color: "#b48cff", hint: "Running connectors (AppleScript, Gmail, git…)" },
  { key: "overhead_ms", label: "Overhead", color: "var(--text-dim)", hint: "HTTP, memory, everything else" },
];

const TIP = {
  high: "border-[color-mix(in_srgb,var(--danger)_45%,var(--border))]",
  medium: "border-[#e0b25266]",
  low: "border-[var(--border)]",
  ok: "border-[color-mix(in_srgb,var(--ok)_40%,var(--border))]",
};

const sec = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s` : `${Math.round(ms)}ms`);
const tps = (n: number) => (n ? `${n.toFixed(n >= 100 ? 0 : 1)} tok/s` : "—");

export function TelemetryView() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<TelemetryReport | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    getTelemetry(days)
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load telemetry"));
  }, [days]);

  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);

  const s = data?.summary;
  const total = data ? Math.max(1, PHASES.reduce((a, p) => a + data.phases[p.key], 0)) : 1;

  return (
    <div className="relative z-10 flex h-full min-h-0 flex-1 flex-col">
      <PageHeader title="Telemetry" subtitle="Where the time goes — model load, prefill, generation and tools">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={async () => { if (confirm("Delete all traces?")) { await clearTelemetry(); load(); } }}
            className="text-[12px] text-[var(--text-dim)] hover:text-[var(--danger)]"
          >
            Reset
          </button>
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
        </div>
      </PageHeader>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-5xl flex-col gap-5">
          {error && <p className="text-[13px] text-[var(--danger)]">{error}</p>}

          <div className="cascade grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label="Latency p50" value={s?.requests ? sec(s.p50_ms) : "—"} />
            <Stat label="Latency p95" value={s?.requests ? sec(s.p95_ms) : "—"} />
            <Stat label="First token ≈" value={s?.first_p50_ms ? sec(s.first_p50_ms) : "—"} />
            <Stat label="Generation" value={tps(s?.decode_tps ?? 0)} />
            <Stat label="Prefill" value={tps(s?.prefill_tps ?? 0)} />
          </div>

          {data && data.tips.length > 0 && (
            <Panel title="How to make it faster">
              <div className="cascade grid gap-3 md:grid-cols-2">
                {data.tips.map((t) => (
                  <div key={t.title} className={`rounded-xl border p-4 ${TIP[t.level]}`}>
                    <div className="text-[13px] font-medium">{t.title}</div>
                    <p className="mt-1 text-[12px] leading-relaxed text-[var(--text-muted)]">{t.body}</p>
                  </div>
                ))}
              </div>
            </Panel>
          )}

          <Panel title="Time breakdown">
            {s?.requests ? (
              <>
                <div className="flex h-3 overflow-hidden rounded-full bg-[var(--bg-elevated)]">
                  {PHASES.map((p) => (
                    <div
                      key={p.key}
                      title={`${p.label}: ${sec(data!.phases[p.key])}`}
                      style={{ width: `${(data!.phases[p.key] / total) * 100}%`, background: p.color }}
                      className="h-full transition-all duration-500"
                    />
                  ))}
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5">
                  {PHASES.map((p) => (
                    <div key={p.key} title={p.hint}>
                      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.06em] text-[var(--text-dim)]">
                        <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
                        {p.label}
                      </div>
                      <div className="mt-0.5 text-[14px] tabular-nums">
                        {Math.round((data!.phases[p.key] / total) * 100)}%
                        <span className="ml-1.5 text-[11.5px] text-[var(--text-dim)]">{sec(data!.phases[p.key] / s.requests)}/req</span>
                      </div>
                    </div>
                  ))}
                </div>
                <p className="mt-4 text-[11.5px] text-[var(--text-dim)]">
                  {s.requests} requests · {s.avg_llm_calls} model calls/request · {fmtNum(s.avg_prompt_tokens)} prompt tokens/request ·{" "}
                  {s.cold_loads} cold load{s.cold_loads === 1 ? "" : "s"}
                </p>
              </>
            ) : (
              <p className="text-[12.5px] text-[var(--text-dim)]">Send a few messages in Chat — traces show up here.</p>
            )}
          </Panel>

          <div className="grid gap-5 md:grid-cols-2">
            <Panel title="In memory now">
              {data?.loaded.length ? (
                <div className="flex flex-col gap-2">
                  {data.loaded.map((m) => (
                    <div key={m.name} className="flex items-center justify-between text-[12.5px]">
                      <code>{m.name}</code>
                      <span className="text-[var(--text-dim)]">
                        {fmtBytes(m.size_vram)} · unloads {m.expires_at ? new Date(m.expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[12.5px] text-[var(--text-dim)]">
                  No model loaded — the next message will pay the load time for <code>{data?.default_model}</code>.
                </p>
              )}
            </Panel>

            <Panel title="Tools">
              {data?.tools.length ? (
                <Table
                  head={["Tool", "Calls", "Avg", "p95", "Errors"]}
                  rows={data.tools.map((t) => [
                    <code key="n" className="text-[var(--text)]">{t.name}</code>,
                    t.calls,
                    sec(t.avg_ms),
                    sec(t.p95_ms),
                    t.errors ? <span key="e" className="text-[var(--danger)]">{t.errors}</span> : "0",
                  ])}
                />
              ) : (
                <p className="text-[12.5px] text-[var(--text-dim)]">No tool calls in this range.</p>
              )}
            </Panel>
          </div>

          {data && data.by_model.length > 0 && (
            <Panel title="By model">
              <Table
                head={["Model", "Requests", "p50", "p95", "Generation", "Prefill", "Avg prompt", "Cold loads"]}
                rows={data.by_model.map((m) => [
                  <code key="m" className="text-[var(--text)]">{m.model}</code>,
                  m.requests, sec(m.p50_ms), sec(m.p95_ms), tps(m.decode_tps), tps(m.prefill_tps),
                  fmtNum(m.avg_prompt_tokens), m.cold_loads,
                ])}
              />
            </Panel>
          )}

          {data && data.recent.length > 0 && (
            <Panel title="Recent requests">
              <div className="flex flex-col divide-y divide-[var(--border)]">
                {data.recent.map((r) => (
                  <TraceItem key={r.id} r={r} open={open === r.id} onToggle={() => setOpen(open === r.id ? null : r.id)} />
                ))}
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

/** One request: summary row + expandable waterfall of its spans. */
function TraceItem({ r, open, onToggle }: { r: TraceRow; open: boolean; onToggle: () => void }) {
  const T = Math.max(1, r.total_ms);
  return (
    <div className="py-2">
      <button type="button" onClick={onToggle} className="flex w-full items-center gap-3 text-left text-[12.5px]">
        <span className="w-16 shrink-0 text-[var(--text-dim)]">
          {new Date(r.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
        <code className="w-32 shrink-0 truncate">{r.model}</code>
        <div className="flex h-2 flex-1 overflow-hidden rounded-full bg-[var(--bg-elevated)]">
          {PHASES.map((p) => (
            <div key={p.key} style={{ width: `${(r[p.key] / T) * 100}%`, background: p.color }} />
          ))}
        </div>
        <span className="w-14 shrink-0 text-right tabular-nums">{sec(r.total_ms)}</span>
        <span className="w-24 shrink-0 text-right text-[11.5px] text-[var(--text-dim)]">
          {r.llm_calls} call{r.llm_calls === 1 ? "" : "s"} · {r.tool_calls} tool{r.tool_calls === 1 ? "" : "s"}
        </span>
      </button>
      {open && (
        <div className="msg-in mt-3 flex flex-col gap-1.5 rounded-lg bg-[var(--bg-elevated)] p-3">
          <p className="mb-1 text-[11px] text-[var(--text-dim)]">
            {r.context_messages} messages in context · {r.tools} tool schemas · {fmtNum(r.prompt_tokens)} prompt / {fmtNum(r.completion_tokens)} output tokens
          </p>
          {r.spans.map((sp, i) => (
            <div key={i} className="flex items-center gap-3 text-[11.5px]">
              <span className="w-40 shrink-0 truncate text-[var(--text-muted)]">
                {sp.kind === "llm" ? `model · ${sp.prompt_tokens}→${sp.completion_tokens} tok` : `${sp.ok ? "" : "✕ "}${sp.name}`}
              </span>
              <div className="relative h-2.5 flex-1">
                <div
                  className="absolute flex h-full overflow-hidden rounded-sm"
                  style={{ left: `${(sp.start / T) * 100}%`, width: `${Math.max(0.5, (sp.ms / T) * 100)}%` }}
                >
                  {sp.kind === "llm" ? (
                    [["load_ms", "#e0b252"], ["prompt_ms", "#6aa6ff"], ["eval_ms", "var(--accent)"]].map(([k, c]) => (
                      <div key={k} style={{ flex: Math.max(0, sp[k as "load_ms"]), background: c }} />
                    ))
                  ) : (
                    <div className="flex-1" style={{ background: sp.ok ? "#b48cff" : "var(--danger)" }} />
                  )}
                </div>
              </div>
              <span className="w-12 shrink-0 text-right tabular-nums text-[var(--text-dim)]">{sec(sp.ms)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
