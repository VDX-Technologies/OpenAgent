<script lang="ts">
  import { onMount } from "svelte";
  import { applyUpdate, getUpdate, type UpdateInfo } from "#lib/api";

  let info = $state<UpdateInfo | null>(null);
  let hidden = $state(false);

  async function refresh() {
    info = await getUpdate().catch(() => info);
  }

  // check at launch and every 6 hours; poll while an update installs
  onMount(() => {
    refresh();
    const id = setInterval(() => (info?.running ? refresh() : null), 2000);
    const slow = setInterval(refresh, 6 * 3600_000);
    return () => { clearInterval(id); clearInterval(slow); };
  });

  async function install() {
    info = await applyUpdate().catch((e) => (info ? { ...info, error: String(e) } : info));
  }
</script>

{#if info && !hidden && (info.available || info.done)}
  <div class="msg-in fixed right-5 bottom-5 z-40 w-[340px] rounded-xl border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-4 shadow-2xl" role="status">
    {#if info.done}
      <p class="text-[13px] font-medium">Update installed</p>
      <p class="mt-1.5 text-[12px] text-[var(--text-muted)]">Quit and reopen VDX OpenAgent to use v{info.latest}.</p>
    {:else}
      <p class="text-[13px] font-medium">VDX OpenAgent v{info.latest} is available</p>
      <p class="mt-1.5 text-[12px] text-[var(--text-muted)]">
        {#if info.running}Downloading and building… this takes a minute.
        {:else if info.error}<span class="text-[var(--danger)]">{info.error}</span>
        {:else}You have v{info.current}.{/if}
      </p>
    {/if}
    <div class="mt-3 flex justify-end gap-2">
      <button class="ghost-btn !text-[12px]" onclick={() => (hidden = true)}>{info.done ? "OK" : "Later"}</button>
      {#if !info.done}
        <button class="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-[12px] font-medium text-[var(--accent-text)] disabled:opacity-50" disabled={info.running} onclick={install}>
          {info.running ? "Updating…" : info.error ? "Retry" : "Update"}
        </button>
      {/if}
    </div>
  </div>
{/if}
