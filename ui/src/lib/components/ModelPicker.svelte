<script lang="ts">
  import { onMount } from "svelte";
  import { getModels } from "#lib/api";
  import { storeModel } from "#lib/ui";

  let { value = $bindable(""), fallback = "" }: { value?: string; fallback?: string } = $props();
  let open = $state(false);
  let models = $state<string[]>([]);

  onMount(() => { getModels().then((r) => (models = r.models)).catch(() => {}); });

  function pick(m: string) { value = m; storeModel(m); open = false; }
</script>

<svelte:window onclick={() => (open = false)} />

<div class="relative">
  <button type="button" onclick={(e) => { e.stopPropagation(); open = !open; }}
    class="flex items-center gap-1.5 rounded-full border border-[var(--border)] px-3 py-1 text-[12px] text-[var(--text-muted)] hover:text-[var(--text)]">
    <span class="max-w-36 truncate">{value || fallback || "Model"}</span><span class="text-[9px]">▾</span>
  </button>
  {#if open}
    <div class="vdx-popover absolute bottom-full left-0 z-30 mb-2 max-h-72 w-64 overflow-y-auto rounded-xl border border-[var(--border-strong)] bg-[var(--bg-panel)] p-1 shadow-2xl">
      {#each models as m (m)}
        <button type="button" onclick={() => pick(m)}
          class="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-[12.5px] hover:bg-[var(--bg-hover)]">
          <span class="truncate">{m}</span>{#if (value || fallback) === m}<span class="text-[var(--accent)]">✓</span>{/if}
        </button>
      {:else}
        <p class="px-3 py-2 text-[12px] text-[var(--text-dim)]">No models installed — see Models.</p>
      {/each}
    </div>
  {/if}
</div>
