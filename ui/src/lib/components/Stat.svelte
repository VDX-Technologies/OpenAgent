<script lang="ts">
  let { label, value }: { label: string; value: string | number } = $props();
</script>

<div class="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] px-4 py-3">
  <div class="text-[11px] uppercase tracking-[0.06em] text-[var(--text-dim)]">{label}</div>
  <div class="mt-1 text-[20px] font-semibold tabular-nums tracking-[-0.02em]">{value}</div>
</div>
