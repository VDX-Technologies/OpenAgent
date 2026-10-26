<script lang="ts">
  import type { Snippet } from "svelte";
  let { title, action, children }: { title: string; action?: Snippet; children: Snippet } = $props();
</script>

<section class="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-5">
  <div class="mb-4 flex items-center justify-between gap-3">
    <h2 class="text-[14px] font-semibold">{title}</h2>
    {@render action?.()}
  </div>
  {@render children()}
</section>
