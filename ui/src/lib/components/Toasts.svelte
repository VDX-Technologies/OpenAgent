<script lang="ts">
  import { onMount } from "svelte";
  import { X } from "@lucide/svelte";
  import { goto } from "$app/navigation";
  import { getNotifications, markNotificationsRead, type Note } from "#lib/api";
  import { onServerEvent } from "#lib/events";

  /** Automation results pop up here as they arrive (pushed over SSE, no polling). */
  let toasts = $state<Note[]>([]);

  function show(n: Note) {
    if (toasts.some((t) => t.id === n.id)) return;
    toasts = [...toasts, n].slice(-4);
    setTimeout(() => (toasts = toasts.filter((t) => t.id !== n.id)), 10_000);
  }
  function dismiss(n: Note) {
    toasts = toasts.filter((t) => t.id !== n.id);
    markNotificationsRead([n.id]).catch(() => {});
  }

  onMount(() => {
    // results that arrived while the window was closed (last day only)
    const since = Date.now() - 24 * 3600_000;
    getNotifications(0, true)
      .then(({ items }) => items.filter((n) => !n.created_at || Date.parse(n.created_at) > since).slice(-3).forEach(show))
      .catch(() => {});
    return onServerEvent((e) => { if (e.type === "notification") show(e.item); });
  });
</script>

<div class="pointer-events-none fixed right-4 bottom-4 z-50 flex w-[340px] flex-col gap-2" aria-live="polite">
  {#each toasts as n (n.id)}
    <div class="toast pointer-events-auto rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-3.5 shadow-lg">
      <div class="flex items-start gap-3">
        <span class="logo-tile mt-0.5 h-6 w-6"><img src="/brand/vdx-mark.png" alt="" /></span>
        <button class="min-w-0 flex-1 text-left" onclick={() => { if (n.conversation_id) goto(`/?c=${n.conversation_id}`); dismiss(n); }}>
          <p class="text-[13px] font-medium text-[var(--text)]">{n.title}</p>
          <p class="mt-0.5 line-clamp-3 text-[12.5px] text-[var(--text-muted)]">{n.text}</p>
        </button>
        <button class="text-[var(--text-dim)] hover:text-[var(--text)]" aria-label="Dismiss" onclick={() => dismiss(n)}><X size={14} strokeWidth={1.8} /></button>
      </div>
    </div>
  {/each}
</div>

<style>
  .toast { animation: vdx-pop var(--dur-slow) var(--ease) both; transform-origin: bottom right; }
</style>
