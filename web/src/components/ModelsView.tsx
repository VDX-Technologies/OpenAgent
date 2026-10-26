"use client";

import { useCallback, useEffect, useState } from "react";
import {
  deleteModel,
  getModelsDetailed,
  getPulls,
  getSystem,
  pullModel,
  type InstalledModel,
  type PullState,
  type Recommendation,
  type SystemProfile,
} from "@/lib/api";
import { PageHeader, Panel, fmtBytes } from "@/components/ui";

const FIT = {
  great: { label: "Runs great", cls: "text-[var(--ok)] border-[color-mix(in_srgb,var(--ok)_40%,transparent)]" },
  ok: { label: "Tight fit", cls: "text-[#e0b252] border-[#e0b25266]" },
  too_big: { label: "Too big", cls: "text-[var(--text-dim)] border-[var(--border)]" },
};

export function ModelsView() {
  const [profile, setProfile] = useState<SystemProfile | null>(null);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [installed, setInstalled] = useState<InstalledModel[]>([]);
  const [running, setRunning] = useState<string[]>([]);
  const [pulls, setPulls] = useState<Record<string, PullState>>({});
  const [custom, setCustom] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [sys, det] = await Promise.all([getSystem(), getModelsDetailed().catch(() => ({ models: [], running: [] }))]);
      setProfile(sys.profile);
      setRecs(sys.recommendations);
      setInstalled(det.models);
      setRunning(det.running.map((r) => r.name));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "API offline");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const active = Object.values(pulls).some((p) => p.state === "pulling");

  // Poll pull progress while something downloads.
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const { pulls: list } = await getPulls();
        if (!alive) return;
        const next = Object.fromEntries(list.map((p) => [p.name, p]));
        setPulls(next);
        if (list.some((p) => p.state === "done" && pulls[p.name]?.state === "pulling")) void load();
      } catch {
        /* ignore */
      }
    };
    void tick();
    if (!active) return () => { alive = false; };
    const id = setInterval(tick, 1000);
    return () => {
      alive = false;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, load]);

  async function onPull(name: string) {
    if (!name.trim()) return;
    try {
      const p = await pullModel(name.trim());
      setPulls((s) => ({ ...s, [p.name]: p }));
      setCustom("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pull failed");
    }
  }

  async function onDelete(name: string) {
    if (!confirm(`Delete ${name} from Ollama?`)) return;
    try {
      await deleteModel(name);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  const sorted = [...recs].sort((a, b) => Number(b.recommended) - Number(a.recommended));

  return (
    <div className="relative z-10 flex h-full min-h-0 flex-1 flex-col">
      <PageHeader title="Models" subtitle="Recommended for this machine · download and manage Ollama models" />

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-5xl flex-col gap-5">
          {error && <p className="text-[13px] text-[var(--danger)]">{error}</p>}

          {profile && (
            <Panel title="This machine">
              <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
                <Spec label="Chip" value={profile.chip} />
                <Spec label="Memory" value={`${profile.ram_gb} GB${profile.apple_silicon ? " unified" : ""}`} />
                <Spec
                  label="CPU cores"
                  value={profile.perf_cores ? `${profile.cpu_cores} (${profile.perf_cores}P + ${profile.efficiency_cores}E)` : String(profile.cpu_cores)}
                />
                <Spec label="Free disk" value={`${profile.disk_free_gb} / ${profile.disk_total_gb} GB`} />
                <Spec label="System" value={`${profile.os}${profile.model ? ` · ${profile.model}` : ""}`} />
              </div>
              {!profile.apple_silicon && (
                <p className="mt-3 text-[12px] text-[var(--text-dim)]">
                  No Apple Silicon GPU detected — recommendations are more conservative (CPU inference).
                </p>
              )}
            </Panel>
          )}

          <Panel title="Recommended">
            <div className="cascade grid gap-3 md:grid-cols-2">
              {sorted.map((m) => {
                const p = pulls[m.name];
                const pct = p?.total ? Math.round((p.completed / p.total) * 100) : 0;
                return (
                  <div
                    key={m.name}
                    className={`rounded-xl border p-4 transition hover:-translate-y-0.5 hover:border-[var(--border-strong)] ${
                      m.recommended ? "border-[color-mix(in_srgb,var(--accent)_45%,var(--border))]" : "border-[var(--border)]"
                    } ${m.fit === "too_big" ? "opacity-55" : ""}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <code className="text-[13px] text-[var(--text)]">{m.name}</code>
                          {m.recommended && (
                            <span className="rounded-full bg-[var(--accent)] px-2 py-0.5 text-[10px] font-semibold text-[var(--bg)]">
                              Best pick
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-[12px] text-[var(--text-muted)]">{m.desc}</p>
                      </div>
                      <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10.5px] ${FIT[m.fit].cls}`}>
                        {FIT[m.fit].label}
                      </span>
                    </div>
                    <div className="mt-3 flex items-center justify-between gap-2">
                      <div className="flex flex-wrap gap-1 text-[10.5px] text-[var(--text-dim)]">
                        <span>{m.size_gb} GB</span>
                        <span>·</span>
                        <span>{m.min_ram} GB RAM</span>
                        {m.tags.map((t) => (
                          <span key={t} className="rounded bg-[var(--bg-elevated)] px-1.5">{t}</span>
                        ))}
                      </div>
                      {m.installed ? (
                        <span className="text-[11.5px] text-[var(--ok)]">✓ Installed</span>
                      ) : p?.state === "pulling" ? (
                        <span className="text-[11.5px] tabular-nums text-[var(--accent)]">{p.total ? `${pct}%` : p.status}</span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => onPull(m.name)}
                          disabled={m.fit === "too_big"}
                          className="rounded-lg border border-[var(--border)] px-2.5 py-1 text-[11.5px] text-[var(--text)] hover:border-[var(--border-strong)] disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          Download
                        </button>
                      )}
                    </div>
                    {p?.state === "pulling" && (
                      <div className="mt-2 h-1 overflow-hidden rounded bg-[var(--bg-elevated)]">
                        <div className="h-full bg-[var(--accent)] transition-all" style={{ width: `${pct}%` }} />
                      </div>
                    )}
                    {p?.state === "error" && <p className="mt-2 text-[11.5px] text-[var(--danger)]">{p.status}</p>}
                  </div>
                );
              })}
            </div>
          </Panel>

          <Panel
            title="Installed"
            action={
              <form
                onSubmit={(e) => { e.preventDefault(); void onPull(custom); }}
                className="flex gap-1.5"
              >
                <input
                  value={custom}
                  onChange={(e) => setCustom(e.target.value)}
                  placeholder="Pull any model, e.g. phi4"
                  className="w-48 rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] px-2.5 py-1 text-[12px] outline-none placeholder:text-[var(--text-dim)]"
                />
                <button type="submit" className="rounded-lg border border-[var(--border)] px-2.5 py-1 text-[12px] hover:border-[var(--border-strong)]">
                  Pull
                </button>
              </form>
            }
          >
            {Object.values(pulls)
              .filter((p) => p.state === "pulling" && !recs.some((r) => r.name === p.name))
              .map((p) => (
                <p key={p.name} className="mb-2 text-[12px] text-[var(--accent)]">
                  Downloading {p.name}… {p.total ? `${Math.round((p.completed / p.total) * 100)}%` : p.status}
                </p>
              ))}
            {installed.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-dim)]">No models installed (or Ollama is offline).</p>
            ) : (
              <div className="flex flex-col divide-y divide-[var(--border)]">
                {installed.map((m) => (
                  <div key={m.name} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <code className="text-[13px]">{m.name}</code>
                        {running.includes(m.name) && (
                          <span className="rounded-full border border-[color-mix(in_srgb,var(--ok)_40%,transparent)] px-1.5 text-[10px] text-[var(--ok)]">
                            loaded
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-[var(--text-dim)]">
                        {[m.parameter_size, m.quantization, m.family, fmtBytes(m.size)].filter(Boolean).join(" · ")}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => onDelete(m.name)}
                      className="text-[11.5px] text-[var(--text-dim)] hover:text-[var(--danger)]"
                    >
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Spec({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] uppercase tracking-[0.06em] text-[var(--text-dim)]">{label}</div>
      <div className="mt-0.5 truncate text-[13px]" title={value}>{value}</div>
    </div>
  );
}
