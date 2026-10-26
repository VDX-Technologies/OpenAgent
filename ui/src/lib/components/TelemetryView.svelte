<script lang="ts">
  import { confirmAction } from "#lib/confirm.svelte";
  import { clearTelemetry, getTelemetry, type Phases, type TelemetryReport } from "#lib/api";
  import { fmtBytes, fmtNum } from "#lib/ui";
  import PageHeader from "./PageHeader.svelte";
  import Panel from "./Panel.svelte";
  import SharingPanel from "./SharingPanel.svelte";
  import Stat from "./Stat.svelte";
  import Table from "./Table.svelte";
  import RangeTabs from "./RangeTabs.svelte";

  const PHASES: { key: keyof Phases; label: string; color: string; hint: string }[] = [
    { key: "load_ms", label: "Model load", color: "#e0b252", hint: "Loading weights into memory (cold start)" },
    { key: "prompt_ms", label: "Prefill", color: "#6aa6ff", hint: "Reading the prompt: system, history, tool schemas" },
    { key: "eval_ms", label: "Generation", color: "var(--accent)", hint: "Producing output tokens" },
    { key: "tool_ms", label: "Tools", color: "#b48cff", hint: "Running connectors (AppleScript, Gmail, git…)" },
    { key: "overhead_ms", label: "Overhead", color: "var(--text-dim)", hint: "HTTP, memory, everything else" },
  ];
  const LLM_PARTS = [["load_ms", "#e0b252"], ["prompt_ms", "#6aa6ff"], ["eval_ms", "var(--accent)"]] as const;
  const TIP = {
    high: "border-[color-mix(in_srgb,var(--danger)_45%,var(--border))]",
    medium: "border-[#e0b25266]",
    low: "border-[var(--border)]",
    ok: "border-[color-mix(in_srgb,var(--ok)_40%,var(--border))]",
  };

  const sec = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s` : `${Math.round(ms)}ms`);
  const tps = (n: number) => (n ? `${n.toFixed(n >= 100 ? 0 : 1)} tok/s` : "—");
  const hm = (t: string) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

  let days = $state(7);
  let data = $state<TelemetryReport | null>(null);
  let open = $state<number | null>(null);
  let error = $state<string | null>(null);

  const load = () => getTelemetry(days).then((d) => { data = d; error = null; })
    .catch((e) => (error = e instanceof Error ? e.message : "Failed to load telemetry"));

  $effect(() => {
    void days;
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  });

  const s = $derived(data?.summary);
  const total = $derived(data ? Math.max(1, PHASES.reduce((a, p) => a + data!.phases[p.key], 0)) : 1);
</script>

<div class="relative z-10 flex h-full min-h-0 flex-1 flex-col">
  <PageHeader title="Telemetry" subtitle="Where the time goes — model load, prefill, generation and tools">
    <div class="flex items-center gap-2">
      <button class="text-[12px] text-[var(--text-dim)] hover:text-[var(--danger)]"
        onclick={async () => { if (await confirmAction("Delete all traces?", "Reset")) { await clearTelemetry(); load(); } }}>Reset</button>
      <RangeTabs ranges={[1, 7, 30]} bind:value={days} />
    </div>
  </PageHeader>

  <div class="min-h-0 flex-1 overflow-y-auto px-6 py-6">
    <div class="mx-auto flex max-w-5xl flex-col gap-5">
      {#if error}<p class="text-[13px] text-[var(--danger)]">{error}</p>{/if}
      <SharingPanel />

      <div class="cascade grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Latency p50" value={s?.requests ? sec(s.p50_ms) : "—"} />
        <Stat label="Latency p95" value={s?.requests ? sec(s.p95_ms) : "—"} />
        <Stat label="First token ≈" value={s?.first_p50_ms ? sec(s.first_p50_ms) : "—"} />
        <Stat label="Generation" value={tps(s?.decode_tps ?? 0)} />
        <Stat label="Prefill" value={tps(s?.prefill_tps ?? 0)} />
      </div>

      {#if data?.tips.length}
        <Panel title="How to make it faster">
          <div class="cascade grid gap-3 md:grid-cols-2">
            {#each data.tips as t (t.title)}
              <div class="rounded-xl border p-4 {TIP[t.level]}">
                <div class="text-[13px] font-medium">{t.title}</div>
                <p class="mt-1 text-[12px] leading-relaxed text-[var(--text-muted)]">{t.body}</p>
              </div>
            {/each}
          </div>
        </Panel>
      {/if}

      <Panel title="Time breakdown">
        {#if data && s?.requests}
          <div class="flex h-3 overflow-hidden rounded-full bg-[var(--bg-elevated)]">
            {#each PHASES as p (p.key)}
              <div title="{p.label}: {sec(data.phases[p.key])}" class="h-full transition-all duration-500"
                style:width="{(data.phases[p.key] / total) * 100}%" style:background={p.color}></div>
            {/each}
          </div>
          <div class="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5">
            {#each PHASES as p (p.key)}
              <div title={p.hint}>
                <div class="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.06em] text-[var(--text-dim)]">
                  <span class="h-2 w-2 rounded-full" style:background={p.color}></span>{p.label}
                </div>
                <div class="mt-0.5 text-[14px] tabular-nums">
                  {Math.round((data.phases[p.key] / total) * 100)}%
                  <span class="ml-1.5 text-[11.5px] text-[var(--text-dim)]">{sec(data.phases[p.key] / s.requests)}/req</span>
                </div>
              </div>
            {/each}
          </div>
          <p class="mt-4 text-[11.5px] text-[var(--text-dim)]">
            {s.requests} requests · {s.avg_llm_calls} model calls/request · {fmtNum(s.avg_prompt_tokens)} prompt tokens/request · {plural(s.cold_loads, "cold load")}
          </p>
        {:else}
          <p class="text-[12.5px] text-[var(--text-dim)]">Send a few messages in Chat — traces show up here.</p>
        {/if}
      </Panel>

      <div class="grid gap-5 md:grid-cols-2">
        <Panel title="In memory now">
          {#if data?.loaded.length}
            <div class="flex flex-col gap-2">
              {#each data.loaded as m (m.name)}
                <div class="flex items-center justify-between text-[12.5px]">
                  <code>{m.name}</code>
                  <span class="text-[var(--text-dim)]">{fmtBytes(m.size_vram)} · unloads {m.expires_at ? hm(m.expires_at) : "—"}</span>
                </div>
              {/each}
            </div>
          {:else}
            <p class="text-[12.5px] text-[var(--text-dim)]">No model loaded — the next message will pay the load time for <code>{data?.default_model}</code>.</p>
          {/if}
        </Panel>

        <Panel title="Tools">
          {#if data?.tools.length}
            <Table head={["Tool", "Calls", "Avg", "p95", "Errors"]}>
              {#each data.tools as t (t.name)}
                <tr>
                  <td><code class="text-[var(--text)]">{t.name}</code></td><td>{t.calls}</td>
                  <td>{sec(t.avg_ms)}</td><td>{sec(t.p95_ms)}</td>
                  <td class={t.errors ? "text-[var(--danger)]" : ""}>{t.errors}</td>
                </tr>
              {/each}
            </Table>
          {:else}
            <p class="text-[12.5px] text-[var(--text-dim)]">No tool calls in this range.</p>
          {/if}
        </Panel>
      </div>

      {#if data?.by_model.length}
        <Panel title="By model">
          <Table head={["Model", "Requests", "p50", "p95", "Generation", "Prefill", "Avg prompt", "Cold loads"]}>
            {#each data.by_model as m (m.model)}
              <tr>
                <td><code class="text-[var(--text)]">{m.model}</code></td><td>{m.requests}</td>
                <td>{sec(m.p50_ms)}</td><td>{sec(m.p95_ms)}</td><td>{tps(m.decode_tps)}</td><td>{tps(m.prefill_tps)}</td>
                <td>{fmtNum(m.avg_prompt_tokens)}</td><td>{m.cold_loads}</td>
              </tr>
            {/each}
          </Table>
        </Panel>
      {/if}

      {#if data?.recent.length}
        <Panel title="Recent requests">
          <div class="flex flex-col divide-y divide-[var(--border)]">
            {#each data.recent as r (r.id)}
              {@const T = Math.max(1, r.total_ms)}
              <div class="py-2">
                <button type="button" onclick={() => (open = open === r.id ? null : r.id)} class="flex w-full items-center gap-3 text-left text-[12.5px]">
                  <span class="w-16 shrink-0 text-[var(--text-dim)]">{hm(r.created_at)}</span>
                  <code class="w-32 shrink-0 truncate">{r.model}</code>
                  <div class="flex h-2 flex-1 overflow-hidden rounded-full bg-[var(--bg-elevated)]">
                    {#each PHASES as p (p.key)}<div style:width="{(r[p.key] / T) * 100}%" style:background={p.color}></div>{/each}
                  </div>
                  <span class="w-14 shrink-0 text-right tabular-nums">{sec(r.total_ms)}</span>
                  <span class="w-24 shrink-0 text-right text-[11.5px] text-[var(--text-dim)]">{plural(r.llm_calls, "call")} · {plural(r.tool_calls, "tool")}</span>
                </button>
                {#if open === r.id}
                  <div class="msg-in mt-3 flex flex-col gap-1.5 rounded-lg bg-[var(--bg-elevated)] p-3">
                    <p class="mb-1 text-[11px] text-[var(--text-dim)]">
                      {r.context_messages} messages in context · {r.tools} tool schemas · {fmtNum(r.prompt_tokens)} prompt / {fmtNum(r.completion_tokens)} output tokens
                    </p>
                    {#each r.spans as sp, i (i)}
                      <div class="flex items-center gap-3 text-[11.5px]">
                        <span class="w-40 shrink-0 truncate text-[var(--text-muted)]">
                          {sp.kind === "llm" ? `model · ${sp.prompt_tokens}→${sp.completion_tokens} tok` : `${sp.ok ? "" : "✕ "}${sp.name}`}
                        </span>
                        <div class="relative h-2.5 flex-1">
                          <div class="absolute flex h-full overflow-hidden rounded-sm"
                            style:left="{(sp.start / T) * 100}%" style:width="{Math.max(0.5, (sp.ms / T) * 100)}%">
                            {#if sp.kind === "llm"}
                              {#each LLM_PARTS as [k, c] (k)}<div style:flex={Math.max(0, sp[k])} style:background={c}></div>{/each}
                            {:else}
                              <div class="flex-1" style:background={sp.ok ? "#b48cff" : "var(--danger)"}></div>
                            {/if}
                          </div>
                        </div>
                        <span class="w-12 shrink-0 text-right tabular-nums text-[var(--text-dim)]">{sec(sp.ms)}</span>
                      </div>
                    {/each}
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        </Panel>
      {/if}
    </div>
  </div>
</div>
