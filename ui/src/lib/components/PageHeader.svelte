<script lang="ts">
  import type { Snippet } from "svelte";
  let { title, subtitle, children }: { title: string; subtitle?: string; children?: Snippet } = $props();
</script>

<header class="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-[var(--border)] px-6">
  <div class="min-w-0">
    <h1 class="truncate text-[15px] font-semibold tracking-[-0.01em]">{title}</h1>
    {#if subtitle}<p class="truncate text-[11px] text-[var(--text-dim)]">{subtitle}</p>{/if}
  </div>
  {@render children?.()}
</header>
