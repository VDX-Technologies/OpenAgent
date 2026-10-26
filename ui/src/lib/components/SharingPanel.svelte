<script lang="ts">
  import { onMount } from "svelte";
  import { getTelemetryConsent, setTelemetryConsent, type TelemetryConsent } from "#lib/api";
  import Panel from "./Panel.svelte";

  let c = $state<TelemetryConsent | null>(null);

  onMount(() => { getTelemetryConsent().then((r) => (c = r)).catch(() => {}); });

  async function toggle() {
    if (c) c = { ...c, ...(await setTelemetryConsent(!c.consent)) };
  }
</script>

<Panel title="Anonymous sharing">
  {#snippet action()}
    {#if c}
      <button class="flex items-center gap-2 text-[12px]" onclick={toggle} aria-pressed={!!c.consent}>
        {c.consent ? "On" : "Off"}
        <span class="relative h-4 w-7 rounded-full transition-colors {c.consent ? 'bg-[var(--accent)]' : 'bg-[var(--border-strong)]'}">
          <span class="absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all {c.consent ? 'left-3.5' : 'left-0.5'}"></span>
        </span>
      </button>
    {/if}
  {/snippet}
  <p class="text-[12.5px] text-[var(--text-muted)]">
    When on, per-request numbers (model, size, quantization, tokens, load/prefill/GPU/CPU time, tool count) are sent with
    this install record. No prompts, replies, files, account names, hostnames or IP addresses.
  </p>
  {#if c}
    {#if !c.configured}
      <p class="mt-2 text-[12px] text-[var(--text-dim)]">No endpoint configured (VDX_TELEMETRY_URL), so nothing is sent.</p>
    {/if}
    <pre class="mt-3 overflow-x-auto rounded-lg bg-[var(--bg-hover)] p-3 text-[11.5px]">{JSON.stringify({ install_id: c.install_id, ...c.preview }, null, 2)}</pre>
  {/if}
</Panel>
