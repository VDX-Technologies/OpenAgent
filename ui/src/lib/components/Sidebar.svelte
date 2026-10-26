<script lang="ts">
  import { confirmAction } from "#lib/confirm.svelte";
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { deleteConversation, listConversations, updateConversation, type Conversation } from "#lib/api";
  import { runs } from "#lib/runs.svelte";

  const I = {
    new: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z",
    search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm10 2-4.3-4.3",
    models: "M12 2 3 7l9 5 9-5-9-5Zm-9 10 9 5 9-5M3 17l9 5 9-5",
    auto: "M13 2 3 14h9l-1 8 10-12h-9l1-8Z",
    usage: "M3 3v18h18M7 15l4-4 3 3 5-6",
    settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14.5 3h-5l-.4 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z",
    panel: "M4 4h16v16H4zM9 4v16",
  };
  const NAV = [
    ["/automations", "Automations", I.auto], ["/models", "Models", I.models], ["/usage", "Usage", I.usage],
  ] as const;

  let collapsed = $state(false);
  let searching = $state(false);
  let q = $state("");
  let items = $state<Conversation[]>([]);
  let editing = $state<number | null>(null);
  let draft = $state("");
  const active = $derived(page.url.pathname === "/" ? Number(page.url.searchParams.get("c")) || null : null);

  const load = () => listConversations(q).then((r) => (items = r.conversations)).catch(() => {});

  onMount(() => {
    load();
    window.addEventListener("vdx:conversations", load);
    return () => window.removeEventListener("vdx:conversations", load);
  });

  let t: ReturnType<typeof setTimeout>;
  function search() { clearTimeout(t); t = setTimeout(load, 200); }

  async function rename(c: Conversation) {
    editing = null;
    if (draft.trim() && draft !== c.title) { await updateConversation(c.id, { title: draft.trim() }); load(); }
  }
  async function remove(c: Conversation) {
    if (!(await confirmAction(`Delete “${c.title}”?`))) return;
    await deleteConversation(c.id);
    if (active === c.id) goto("/");
    load();
  }
</script>

{#snippet icon(d: string)}
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path {d} /></svg>
{/snippet}

{#if collapsed}
  <aside class="flex w-14 shrink-0 flex-col items-center gap-2 bg-[var(--bg-elevated)] py-3">
    <button class="nav-item" title="Open sidebar" onclick={() => (collapsed = false)}>{@render icon(I.panel)}</button>
    <a href="/" class="nav-item" title="New chat">{@render icon(I.new)}</a>
  </aside>
{:else}
<aside class="flex w-[256px] shrink-0 flex-col bg-[var(--bg-elevated)]">
  <div class="flex h-14 items-center justify-between px-3">
    <a href="/" class="flex items-center gap-2.5 px-1">
      <span class="logo-tile h-6 w-6"><img src="/brand/vdx-mark.png" alt="" /></span>
      <span class="text-[15px] font-semibold">VDX OpenAgent</span>
    </a>
    <button class="nav-item !p-1.5" title="Close sidebar" onclick={() => (collapsed = true)}>{@render icon(I.panel)}</button>
  </div>

  <nav class="flex flex-col gap-0.5 px-2">
    <a href="/" data-sveltekit-noscroll class="nav-item">{@render icon(I.new)}New Chat</a>
    {#if searching}
      <!-- svelte-ignore a11y_autofocus -->
      <input bind:value={q} oninput={search} autofocus placeholder="Search chats"
        onblur={() => { if (!q) searching = false; }} class="field !rounded-lg !py-1.5 !text-[13px]" />
    {:else}
      <button class="nav-item text-left" onclick={() => (searching = true)}>{@render icon(I.search)}Search</button>
    {/if}
    {#each NAV as [href, label, d] (href)}
      <a {href} class="nav-item {page.url.pathname.startsWith(href) ? 'on' : ''}">{@render icon(d)}{label}</a>
    {/each}
  </nav>

  <p class="mt-5 px-4 pb-1 text-[12px] font-medium text-[var(--text-dim)]">Chats</p>
  <div class="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
    {#each items as c (c.id)}
      <div class="group relative flex items-center rounded-lg {active === c.id ? 'bg-[var(--bg-hover)]' : 'hover:bg-[var(--bg-hover)]'}">
        {#if editing === c.id}
          <!-- svelte-ignore a11y_autofocus -->
          <input bind:value={draft} autofocus onblur={() => rename(c)}
            onkeydown={(e) => { if (e.key === "Enter") rename(c); if (e.key === "Escape") editing = null; }}
            class="field m-0.5 !py-1 !text-[12.5px]" />
        {:else}
          <a href="/?c={c.id}" ondblclick={() => { editing = c.id; draft = c.title; }}
            class="min-w-0 flex-1 truncate px-2.5 py-1.5 text-[13px] {active === c.id ? 'text-[var(--text)]' : 'text-[var(--text-muted)]'}">
            {#if c.pinned}<span class="mr-1 text-[var(--text-dim)]">·</span>{/if}{#if runs[c.id]}<span class="run-dot" title="Generating…"></span>{/if}{c.title}
          </a>
          <div class="absolute right-1 hidden items-center gap-0.5 rounded-md bg-[var(--bg-hover)] pl-2 text-[11px] text-[var(--text-dim)] group-hover:flex">
            <button title={c.pinned ? "Unpin" : "Pin"} class="px-1 hover:text-[var(--text)]" onclick={async () => { await updateConversation(c.id, { pinned: !c.pinned }); load(); }}>{c.pinned ? "◉" : "○"}</button>
            <button title="Rename" class="px-1 hover:text-[var(--text)]" onclick={() => { editing = c.id; draft = c.title; }}>✎</button>
            <button title="Delete" class="px-1 hover:text-[var(--danger)]" onclick={() => remove(c)}>✕</button>
          </div>
        {/if}
      </div>
    {:else}
      <p class="px-3 py-2 text-[12px] text-[var(--text-dim)]">{q ? "No matches" : "No chats yet"}</p>
    {/each}
  </div>

  <div class="flex flex-col gap-0.5 p-2">
    <a href="/telemetry" class="nav-item !text-[13px] !text-[var(--text-muted)] {page.url.pathname.startsWith('/telemetry') ? 'on' : ''}">{@render icon(I.usage)}Telemetry</a>
    <a href="/settings" class="nav-item {page.url.pathname.startsWith('/settings') ? 'on' : ''}">{@render icon(I.settings)}Settings</a>
  </div>
</aside>
{/if}
