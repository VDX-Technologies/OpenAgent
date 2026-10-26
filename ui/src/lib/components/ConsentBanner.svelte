<script lang="ts">
  import { onMount } from "svelte";
  import { getTelemetryConsent, setTelemetryConsent } from "#lib/api";
  import { isOnboarded } from "#lib/ui";

  let show = $state(false);

  onMount(() => {
    // Ask only after the welcome guide is done, and only once.
    const id = setInterval(async () => {
      if (!isOnboarded()) return;
      clearInterval(id);
      const c = await getTelemetryConsent().catch(() => null);
      show = !!c && c.consent === null;
    }, 1500);
    return () => clearInterval(id);
  });

  async function choose(allow: boolean) {
    show = false;
    await setTelemetryConsent(allow).catch(() => {});
  }
</script>

{#if show}
  <div class="msg-in fixed right-5 bottom-5 z-40 w-[340px] rounded-xl border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-4 shadow-2xl" role="dialog" aria-label="Telemetry consent">
    <p class="text-[13px] font-medium">Help improve VDX OpenAgent?</p>
    <p class="mt-1.5 text-[12px] leading-relaxed text-[var(--text-muted)]">
      Share anonymous performance data: model, token counts, GPU/CPU time and your Mac model.
      Never your messages, files, accounts or IP address.
      <a href="/telemetry" class="underline">See exactly what is sent</a>.
    </p>
    <div class="mt-3 flex justify-end gap-2">
      <button class="ghost-btn !text-[12px]" onclick={() => choose(false)}>Don't share</button>
      <button class="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-[12px] font-medium text-[var(--accent-text)]" onclick={() => choose(true)}>Allow</button>
    </div>
  </div>
{/if}
