<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { getNotifications, type Note } from "#lib/api";

  let toasts = $state<Note[]>([]);
  let last = -1;

  const dismiss = (id: number) => (toasts = toasts.filter((t) => t.id !== id));

  async function poll() {
    try {
      const { items } = await getNotifications(Math.max(0, last));
      if (items.length) {
        const prev = last;
        last = items[items.length - 1].id;
        if (prev < 0) return; // first poll: skip what fired before the window opened
        for (const n of items) {
          toasts = [...toasts, n].slice(-4);
          setTimeout(() => dismiss(n.id), 8000);
        }
      } else if (last < 0) last = 0;
    } catch { /* API not up yet */ }
  }

  onMount(() => {
    poll();
    const t = setInterval(poll, 4000);
    return () => clearInterval(t);
  });
</script>

<div class="pointer-events-none fixed right-4 bottom-4 z-50 flex w-[340px] flex-col gap-2" aria-live="polite">
  {#each toasts as n (n.id)}
    <div class="toast pointer-events-auto rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-3.5 shadow-lg">
      <div class="flex items-start gap-3">
        <span class="logo-tile mt-0.5 h-6 w-6"><img src="/brand/vdx-mark.png" alt="" /></span>
        <button class="min-w-0 flex-1 text-left" onclick={() => { if (n.conversation_id) goto(`/?c=${n.conversation_id}`); dismiss(n.id); }}>
          <p class="text-[13px] font-medium text-[var(--text)]">{n.title}</p>
          <p class="mt-0.5 line-clamp-3 text-[12.5px] text-[var(--text-muted)]">{n.text}</p>
        </button>
        <button class="text-[var(--text-dim)] hover:text-[var(--text)]" aria-label="Dismiss" onclick={() => dismiss(n.id)}>✕</button>
      </div>
    </div>
  {/each}
</div>

<style>
  .toast { animation: vdx-pop var(--dur-slow) var(--ease) both; transform-origin: bottom right; }
</style>
