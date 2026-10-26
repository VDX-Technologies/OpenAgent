<script lang="ts">
  import type { Snippet } from "svelte";
  let { head, children }: { head: string[]; children: Snippet } = $props();
</script>

<div class="overflow-x-auto">
  <table class="vdx-table w-full text-left text-[12.5px] tabular-nums">
    <thead>
      <tr class="text-[11px] uppercase tracking-[0.06em] text-[var(--text-dim)]">
        {#each head as h, i (h)}<th class="pb-2 font-normal {i ? 'text-right' : ''}">{h}</th>{/each}
      </tr>
    </thead>
    <tbody class="text-[var(--text-muted)]">{@render children()}</tbody>
  </table>
</div>

<style>
  :global(.vdx-table td) { padding: 0.45rem 0; border-top: 1px solid var(--border); }
  :global(.vdx-table td:not(:first-child)) { text-align: right; padding-left: 1rem; }
</style>
