<script lang="ts">
  import { onMount } from "svelte";
  import { Bell } from "@lucide/svelte";
  import { goto } from "$app/navigation";
  import { getNotifications, markNotificationsRead, type Note } from "#lib/api";
  import { onServerEvent } from "#lib/events";

  /** Everything automations reported, kept until read — also what happened while the app was closed. */
  let items = $state<Note[]>([]);
  let open = $state(false);
  const unread = $derived(items.filter((n) => !n.read).length);

  const load = () => getNotifications(0).then((r) => (items = r.items.reverse())).catch(() => {});
  const when = (t?: string) => (t ? new Date(t).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "");

  onMount(() => {
    load();
    return onServerEvent((e) => { if (e.type === "notification" || e.type === "notifications_read") load(); });
  });

  async function readAll() { await markNotificationsRead().catch(() => {}); load(); }
  function openNote(n: Note) {
    markNotificationsRead([n.id]).catch(() => {});
    n.read = 1;
    open = false;
    if (n.conversation_id) goto(`/?c=${n.conversation_id}`);
  }
</script>

<svelte:window onclick={() => (open = false)} />

<div class="relative">
  <button class="nav-item w-full text-left" onclick={(e) => { e.stopPropagation(); open = !open; }}>
    <Bell strokeWidth={1.7} />Inbox
    {#if unread}<span class="ml-auto rounded-full bg-[var(--accent)] px-1.5 text-[10.5px] font-semibold text-[var(--accent-text)]">{unread}</span>{/if}
  </button>
  {#if open}
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div onclick={(e) => e.stopPropagation()}
      class="vdx-popover absolute bottom-full left-0 z-40 mb-2 flex max-h-[60vh] w-80 flex-col rounded-xl border border-[var(--border-strong)] bg-[var(--bg-panel)] shadow-2xl">
      <div class="flex items-center justify-between border-b border-[var(--border)] px-4 pt-3 pb-2">
        <span class="text-[11px] font-medium tracking-wide text-[var(--text-dim)] uppercase">Inbox</span>
        {#if unread}<button class="text-[11.5px] text-[var(--text-muted)] hover:text-[var(--text)]" onclick={readAll}>Mark all read</button>{/if}
      </div>
      <div class="min-h-0 overflow-y-auto p-1.5">
        {#each items as n (n.id)}
          <button class="flex w-full gap-2 rounded-lg px-2.5 py-2 text-left hover:bg-[var(--bg-hover)]" onclick={() => openNote(n)}>
            <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full {n.read ? 'bg-transparent' : 'bg-[var(--accent)]'}"></span>
            <span class="min-w-0">
              <span class="block text-[12.5px] font-medium">{n.title}</span>
              <span class="mt-0.5 line-clamp-2 block text-[12px] text-[var(--text-muted)]">{n.text}</span>
              <span class="mt-0.5 block text-[11px] text-[var(--text-dim)]">{when(n.created_at)}</span>
            </span>
          </button>
        {:else}
          <p class="px-3 py-4 text-center text-[12px] text-[var(--text-dim)]">Automation results show up here.</p>
        {/each}
      </div>
    </div>
  {/if}
</div>
