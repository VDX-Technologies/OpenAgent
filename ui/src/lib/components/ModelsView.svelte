<script lang="ts">
  import { confirmAction } from "#lib/confirm.svelte";
  import { deleteModel, getModelsDetailed, getPulls, getSystem, pullModel,
    type InstalledModel, type PullState, type Recommendation, type SystemProfile } from "#lib/api";
  import { fmtBytes } from "#lib/ui";
  import PageHeader from "./PageHeader.svelte";
  import Panel from "./Panel.svelte";

  const FIT = {
    great: { label: "Runs great", cls: "text-[var(--ok)] border-[color-mix(in_srgb,var(--ok)_40%,transparent)]" },
    ok: { label: "Tight fit", cls: "text-[#e0b252] border-[#e0b25266]" },
    too_big: { label: "Too big", cls: "text-[var(--text-dim)] border-[var(--border)]" },
  };

  let profile = $state<SystemProfile | null>(null);
  let recs = $state<Recommendation[]>([]);
  let installed = $state<InstalledModel[]>([]);
  let running = $state<string[]>([]);
  let pulls = $state<Record<string, PullState>>({});
  let custom = $state("");
  let error = $state<string | null>(null);

  async function load() {
    try {
      const [sys, det] = await Promise.all([getSystem(), getModelsDetailed().catch(() => ({ models: [], running: [] }))]);
      profile = sys.profile; recs = sys.recommendations;
      installed = det.models; running = det.running.map((r) => r.name);
      error = null;
    } catch (e) { error = e instanceof Error ? e.message : "API offline"; }
  }

  async function tick() {
    try {
      const { pulls: list } = await getPulls();
      const finished = list.some((p) => p.state === "done" && pulls[p.name]?.state === "pulling");
      pulls = Object.fromEntries(list.map((p) => [p.name, p]));
      if (finished) load();
    } catch { /* ignore */ }
  }

  const active = $derived(Object.values(pulls).some((p) => p.state === "pulling"));
  $effect(() => { load(); tick(); });
  $effect(() => {
    if (!active) return;
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  });

  async function onPull(name: string) {
    if (!name.trim()) return;
    try { const p = await pullModel(name.trim()); pulls[p.name] = p; custom = ""; }
    catch (e) { error = e instanceof Error ? e.message : "Pull failed"; }
  }

  async function onDelete(name: string) {
    if (!(await confirmAction(`Delete ${name} from Ollama?`))) return;
    try { await deleteModel(name); await load(); }
    catch (e) { error = e instanceof Error ? e.message : "Delete failed"; }
  }

  const sorted = $derived([...recs].sort((a, b) => Number(b.recommended) - Number(a.recommended)));
  const pct = (p?: PullState) => (p?.total ? Math.round((p.completed / p.total) * 100) : 0);
</script>

{#snippet spec(label: string, value: string)}
  <div class="min-w-0">
    <div class="text-[11px] uppercase tracking-[0.06em] text-[var(--text-dim)]">{label}</div>
    <div class="mt-0.5 truncate text-[13px]" title={value}>{value}</div>
  </div>
{/snippet}

<div class="relative z-10 flex h-full min-h-0 flex-1 flex-col">
  <PageHeader title="Models" subtitle="Recommended for this machine · download and manage Ollama models" />
  <div class="min-h-0 flex-1 overflow-y-auto px-6 py-6">
    <div class="mx-auto flex max-w-5xl flex-col gap-5">
      {#if error}<p class="text-[13px] text-[var(--danger)]">{error}</p>{/if}

      {#if profile}
        <Panel title="This machine">
          <div class="grid grid-cols-2 gap-4 md:grid-cols-5">
            {@render spec("Chip", profile.chip)}
            {@render spec("Memory", `${profile.ram_gb} GB${profile.apple_silicon ? " unified" : ""}`)}
            {@render spec("CPU cores", profile.perf_cores ? `${profile.cpu_cores} (${profile.perf_cores}P + ${profile.efficiency_cores}E)` : String(profile.cpu_cores))}
            {@render spec("Free disk", `${profile.disk_free_gb} / ${profile.disk_total_gb} GB`)}
            {@render spec("System", `${profile.os}${profile.model ? ` · ${profile.model}` : ""}`)}
          </div>
          {#if !profile.apple_silicon}
            <p class="mt-3 text-[12px] text-[var(--text-dim)]">No Apple Silicon GPU detected — recommendations are more conservative (CPU inference).</p>
          {/if}
        </Panel>
      {/if}

      <Panel title="Recommended">
        <div class="cascade grid gap-3 md:grid-cols-2">
          {#each sorted as m (m.name)}
            {@const p = pulls[m.name]}
            <div class="rounded-xl border p-4 transition hover:-translate-y-0.5 hover:border-[var(--border-strong)] {m.recommended ? 'border-[color-mix(in_srgb,var(--accent)_45%,var(--border))]' : 'border-[var(--border)]'} {m.fit === 'too_big' ? 'opacity-55' : ''}">
              <div class="flex items-start justify-between gap-2">
                <div class="min-w-0">
                  <div class="flex flex-wrap items-center gap-1.5">
                    <code class="text-[13px] text-[var(--text)]">{m.name}</code>
                    {#if m.recommended}<span class="rounded-full bg-[var(--accent)] px-2 py-0.5 text-[10px] font-semibold text-[var(--bg)]">Best pick</span>{/if}
                  </div>
                  <p class="mt-1 text-[12px] text-[var(--text-muted)]">{m.desc}</p>
                </div>
                <span class="shrink-0 rounded-full border px-2 py-0.5 text-[10.5px] {FIT[m.fit].cls}">{FIT[m.fit].label}</span>
              </div>
              <div class="mt-3 flex items-center justify-between gap-2">
                <div class="flex flex-wrap gap-1 text-[10.5px] text-[var(--text-dim)]">
                  <span>{m.size_gb} GB</span><span>·</span><span>{m.min_ram} GB RAM</span>
                  {#each m.tags as t (t)}<span class="rounded bg-[var(--bg-elevated)] px-1.5">{t}</span>{/each}
                </div>
                {#if m.installed}
                  <span class="text-[11.5px] text-[var(--ok)]">✓ Installed</span>
                {:else if p?.state === "pulling"}
                  <span class="text-[11.5px] tabular-nums text-[var(--accent)]">{p.total ? `${pct(p)}%` : p.status}</span>
                {:else}
                  <button type="button" class="ghost-btn" disabled={m.fit === "too_big"} onclick={() => onPull(m.name)}>Download</button>
                {/if}
              </div>
              {#if p?.state === "pulling"}
                <div class="mt-2 h-1 overflow-hidden rounded bg-[var(--bg-elevated)]">
                  <div class="h-full bg-[var(--accent)] transition-all" style:width="{pct(p)}%"></div>
                </div>
              {/if}
              {#if p?.state === "error"}<p class="mt-2 text-[11.5px] text-[var(--danger)]">{p.status}</p>{/if}
            </div>
          {/each}
        </div>
      </Panel>

      <Panel title="Installed">
        {#snippet action()}
          <form class="flex gap-1.5" onsubmit={(e) => { e.preventDefault(); onPull(custom); }}>
            <input bind:value={custom} placeholder="Pull any model, e.g. phi4" class="field w-48 !py-1 !text-[12px]" />
            <button type="submit" class="ghost-btn">Pull</button>
          </form>
        {/snippet}
        {#each Object.values(pulls).filter((p) => p.state === "pulling" && !recs.some((r) => r.name === p.name)) as p (p.name)}
          <p class="mb-2 text-[12px] text-[var(--accent)]">Downloading {p.name}… {p.total ? `${pct(p)}%` : p.status}</p>
        {/each}
        {#if installed.length === 0}
          <p class="text-[12.5px] text-[var(--text-dim)]">No models installed (or Ollama is offline).</p>
        {:else}
          <div class="flex flex-col divide-y divide-[var(--border)]">
            {#each installed as m (m.name)}
              <div class="flex items-center justify-between gap-3 py-2.5">
                <div class="min-w-0">
                  <div class="flex items-center gap-2">
                    <code class="text-[13px]">{m.name}</code>
                    {#if running.includes(m.name)}<span class="rounded-full border border-[color-mix(in_srgb,var(--ok)_40%,transparent)] px-1.5 text-[10px] text-[var(--ok)]">loaded</span>{/if}
                  </div>
                  <div class="text-[11px] text-[var(--text-dim)]">{[m.parameter_size, m.quantization, m.family, fmtBytes(m.size)].filter(Boolean).join(" · ")}</div>
                </div>
                <button type="button" onclick={() => onDelete(m.name)} class="text-[11.5px] text-[var(--text-dim)] hover:text-[var(--danger)]">Delete</button>
              </div>
            {/each}
          </div>
        {/if}
      </Panel>
    </div>
  </div>
</div>
