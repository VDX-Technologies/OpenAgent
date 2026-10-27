<script lang="ts">
  import { onMount } from "svelte";
  import { Globe } from "@lucide/svelte";
  import { getConnectors, notifyConnectors, setConnector } from "#lib/api";

  /** Quick switch for the Web connector: lets the model search the internet and open links. */
  let on = $state<boolean | null>(null);

  const load = () => getConnectors().then((r) => (on = r.connectors.find((c) => c.id === "web")?.enabled ?? null)).catch(() => {});

  onMount(() => {
    load();
    window.addEventListener("vdx:connectors", load);
    return () => window.removeEventListener("vdx:connectors", load);
  });

  async function toggle() {
    if (on === null) return;
    on = !on;
    try { await setConnector("web", on); notifyConnectors(); } catch { on = !on; }
  }
</script>

{#if on !== null}
  <button type="button" role="switch" aria-checked={on} onclick={toggle}
    title={on ? "Internet access on: the model can search the web and open links" : "Internet access off"}
    class="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] transition-colors {on ? 'border-[var(--border-strong)] text-[var(--text)]' : 'border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)]'}">
    <Globe size={13} strokeWidth={1.8} /> Web
    <span class="relative ml-0.5 h-3.5 w-6 shrink-0 rounded-full transition-colors {on ? 'bg-[var(--accent)]' : 'bg-[var(--border-strong)]'}">
      <span class="absolute top-0.5 h-2.5 w-2.5 rounded-full bg-white transition-transform {on ? 'translate-x-3' : 'translate-x-0.5'}"></span>
    </span>
  </button>
{/if}
