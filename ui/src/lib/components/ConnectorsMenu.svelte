<script lang="ts">
  import { onMount } from "svelte";
  import { Blocks } from "@lucide/svelte";
  import { getConnectors, notifyConnectors, setConnector, type Connector } from "#lib/api";
  import Switch from "./Switch.svelte";

  let open = $state(false);
  let maxH = $state(384);
  let btn: HTMLButtonElement;
  let items = $state<Connector[]>([]);
  const on = $derived(items.filter((c) => c.enabled && c.configured).length);

  // Web has its own switch in the composer (WebToggle)
  const load = () => getConnectors().then((r) => (items = r.connectors.filter((c) => c.id !== "web"))).catch(() => {});

  onMount(() => {
    load();
    window.addEventListener("vdx:connectors", load);
    return () => window.removeEventListener("vdx:connectors", load);
  });

  async function toggle(c: Connector) {
    c.enabled = !c.enabled;
    try { await setConnector(c.id, c.enabled); notifyConnectors(); } catch { c.enabled = !c.enabled; }
  }
</script>

<svelte:window onclick={() => (open = false)} />

<div class="relative">
  <button type="button" bind:this={btn}
    onclick={(e) => {
      e.stopPropagation();
      maxH = Math.min(384, btn.getBoundingClientRect().top - 16); // the menu opens upwards: never past the top
      open = !open;
    }}
    class="flex items-center gap-1.5 rounded-full border border-[var(--border)] px-3 py-1 text-[12px] text-[var(--text-muted)] hover:text-[var(--text)]">
    <Blocks size={13} strokeWidth={1.8} /> Apps <span class="text-[var(--text-dim)]">{on}</span>
  </button>
  {#if open}
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div onclick={(e) => e.stopPropagation()} style:max-height="{maxH}px"
      class="vdx-popover absolute bottom-full left-0 z-30 mb-2 flex w-80 flex-col rounded-xl border border-[var(--border-strong)] bg-[var(--bg-panel)] shadow-2xl">
      <p class="border-b border-[var(--border)] px-4 pt-3 pb-2 text-[11px] font-medium tracking-wide text-[var(--text-dim)] uppercase">Apps the model can use</p>
      <div class="flex min-h-0 flex-col gap-0.5 overflow-y-auto p-1.5">
        {#each items as c (c.id)}
          <button type="button" role="switch" aria-checked={c.enabled} onclick={() => toggle(c)}
            class="flex w-full items-center gap-4 rounded-lg px-2.5 py-2.5 text-left hover:bg-[var(--bg-hover)]">
            <span class="min-w-0 flex-1">
              <span class="block text-[13px] leading-tight">{c.name}</span>
              <span class="mt-1 line-clamp-2 block text-[11.5px] leading-snug {c.configured ? 'text-[var(--text-dim)]' : 'text-[var(--warn,var(--text-muted))]'}">{c.configured ? c.description : c.setup_hint || "Not available on this computer"}</span>
            </span>
            <span class={c.configured ? "" : "opacity-40"}><Switch on={c.enabled} /></span>
          </button>
        {/each}
      </div>
    </div>
  {/if}
</div>
