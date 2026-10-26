<script lang="ts">
  import { onMount } from "svelte";
  import { getConnectors, setConnector, type Connector } from "#lib/api";

  let open = $state(false);
  let items = $state<Connector[]>([]);
  const on = $derived(items.filter((c) => c.enabled).length);

  onMount(() => { getConnectors().then((r) => (items = r.connectors)).catch(() => {}); });

  async function toggle(c: Connector) {
    c.enabled = !c.enabled;
    try { items = (await setConnector(c.id, c.enabled)).connectors; } catch { c.enabled = !c.enabled; }
  }
</script>

<svelte:window onclick={() => (open = false)} />

<div class="relative">
  <button type="button" onclick={(e) => { e.stopPropagation(); open = !open; }}
    class="flex items-center gap-1.5 rounded-full border border-[var(--border)] px-3 py-1 text-[12px] text-[var(--text-muted)] hover:text-[var(--text)]">
    ⌁ Apps <span class="text-[var(--text-dim)]">{on}</span>
  </button>
  {#if open}
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div onclick={(e) => e.stopPropagation()}
      class="vdx-popover absolute bottom-full left-0 z-30 mb-2 max-h-80 w-72 overflow-y-auto rounded-xl border border-[var(--border-strong)] bg-[var(--bg-panel)] p-1 shadow-2xl">
      {#each items as c (c.id)}
        <button type="button" onclick={() => toggle(c)} title={c.configured ? c.description : c.setup_hint}
          class="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left hover:bg-[var(--bg-hover)]">
          <span class="min-w-0">
            <span class="block text-[12.5px]">{c.name}</span>
            <span class="block truncate text-[11px] text-[var(--text-dim)]">{c.configured ? c.description : c.setup_hint}</span>
          </span>
          <span class="relative h-4 w-7 shrink-0 rounded-full transition-colors {c.enabled ? 'bg-[var(--accent)]' : 'bg-[var(--border-strong)]'}">
            <span class="absolute top-0.5 h-3 w-3 rounded-full bg-white transition-transform {c.enabled ? 'translate-x-3.5' : 'translate-x-0.5'}"></span>
          </span>
        </button>
      {/each}
    </div>
  {/if}
</div>
