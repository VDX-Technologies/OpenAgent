<script lang="ts">
  let { ranges, value = $bindable() }: { ranges: number[]; value: number } = $props();
</script>

<div class="flex rounded-lg border border-[var(--border)] p-0.5">
  {#each ranges as r (r)}
    <button type="button" onclick={() => (value = r)}
      class="rounded-md px-2.5 py-1 text-[12px] transition-colors {value === r ? 'bg-[var(--bg-hover)] text-[var(--text)]' : 'text-[var(--text-muted)] hover:text-[var(--text)]'}">
      {r === 1 ? "24h" : `${r}d`}
    </button>
  {/each}
</div>
