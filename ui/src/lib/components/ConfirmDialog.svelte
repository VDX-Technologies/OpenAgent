<script lang="ts">
  import { answer, dialog } from "#lib/confirm.svelte";

  let btn = $state<HTMLButtonElement>();
  $effect(() => { if (dialog.ask) btn?.focus(); });
</script>

<svelte:window onkeydown={(e) => { if (dialog.ask && e.key === "Escape") answer(false); }} />

{#if dialog.ask}
  <div class="onb-in fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-[2px]"
    role="presentation" onclick={(e) => { if (e.target === e.currentTarget) answer(false); }}>
    <div role="dialog" aria-modal="true" aria-labelledby="confirm-msg"
      class="w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--bg-panel)] p-5 shadow-2xl">
      <p id="confirm-msg" class="text-[14px] leading-relaxed text-[var(--text)]">{dialog.ask.message}</p>
      <p class="mt-1 text-[12.5px] text-[var(--text-dim)]">This can't be undone.</p>
      <div class="mt-5 flex justify-end gap-2">
        <button type="button" class="rounded-lg border border-[var(--border)] px-3.5 py-1.5 text-[13px] text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text)]"
          onclick={() => answer(false)}>Cancel</button>
        <button type="button" bind:this={btn} class="rounded-lg bg-[var(--danger)] px-3.5 py-1.5 text-[13px] font-medium text-white hover:opacity-90"
          onclick={() => answer(true)}>{dialog.ask.action}</button>
      </div>
    </div>
  </div>
{/if}
