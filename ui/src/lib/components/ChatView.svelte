<script lang="ts">
  import { onMount, tick, untrack } from "svelte";
  import { goto, replaceState } from "$app/navigation";
  import { page } from "$app/state";
  import { getConversation, getStatus, type AgentStatus, type ChatMessage, type Usage } from "#lib/api";
  import { runs, startRun, type RunEnd } from "#lib/runs.svelte";
  import { storedModel } from "#lib/ui";
  import MessageBubble from "./MessageBubble.svelte";
  import StatusPill from "./StatusPill.svelte";
  import ModelPicker from "./ModelPicker.svelte";
  import ConnectorsMenu from "./ConnectorsMenu.svelte";

  const HINTS = [
    "What’s on my calendar today?", "Remind me to call Alex at 6pm", "Any unread emails?",
    "WhatsApp Marco: running 10 min late", "Summarise what I asked earlier",
  ];

  let messages = $state<ChatMessage[]>([]);
  let input = $state("");
  let status = $state<AgentStatus | null>(null);
  let offline = $state(false);
  let error = $state<string | null>(null);
  let model = $state("");
  let lastUsage = $state<Usage | null>(null);
  let title = $state("");
  let scroller: HTMLDivElement | undefined = $state();
  let textarea: HTMLTextAreaElement | undefined = $state();
  let created = $state<number | null>(null);
  let mounted = true;

  // shallow replaceState doesn't update page.url, so a just-created chat is tracked via `created`
  const convId = $derived(Number(page.url.searchParams.get("c")) || created);
  // the run lives in a shared store, so it keeps streaming while the user is on another page
  const run = $derived(runs[convId ?? 0]);
  const busy = $derived(!!run);
  const streamText = $derived(run?.stream ?? "");
  const toolName = $derived(run?.tool ?? null);
  // after navigating back mid-run the server copy may not hold the question yet
  const pendingQ = $derived(run && messages.at(-1)?.content !== run.text ? run.text : null);

  const refresh = () => getStatus().then((s) => { status = s; offline = false; }).catch(() => (offline = true));

  onMount(() => {
    model = storedModel();
    try {
      const d = sessionStorage.getItem("vdx.draft");
      if (d) { sessionStorage.removeItem("vdx.draft"); input = d; }
    } catch {}
    refresh();
    const id = setInterval(refresh, 15_000);
    textarea?.focus();
    window.addEventListener("vdx:run-end", onRunEnd);
    return () => { mounted = false; clearInterval(id); window.removeEventListener("vdx:run-end", onRunEnd); };
  });

  // Load the selected conversation (or reset for a new chat).
  $effect(() => {
    // re-runs on every navigation (page.url is a new object), e.g. "New chat" while on a fresh one
    const id = Number(page.url.searchParams.get("c")) || null;
    if (id !== null && id === untrack(() => created)) return;
    created = null;
    lastUsage = null; error = null;
    if (id === null) { messages = []; title = ""; return; }
    let alive = true;
    getConversation(id)
      .then((c) => { if (alive) { messages = c.messages; title = c.title; scrollDown(false); } })
      .catch((e) => alive && (error = e instanceof Error ? e.message : "Could not load chat"));
    return () => { alive = false; };
  });

  $effect(() => { if (streamText) scrollDown(); });

  function onRunEnd(ev: Event) {
    const e = (ev as CustomEvent<RunEnd>).detail;
    if (e.id !== convId) return;
    if (e.reply !== undefined) {
      lastUsage = e.usage ?? null;
      if (e.id === null) messages.push({ role: "assistant", content: e.reply, created_at: new Date().toISOString() });
      else getConversation(e.id).then((c) => { messages = c.messages; title = c.title; scrollDown(); }).catch(() => {});
    } else {
      if (e.partial) messages.push({ role: "assistant", content: e.partial });
      if (e.error) { error = e.error; messages.push({ role: "assistant", content: `⚠️ ${e.error}` }); }
    }
    textarea?.focus();
    scrollDown();
  }

  async function scrollDown(smooth = true) {
    await tick();
    if (!scroller) return;
    // Only follow the stream if the user is already near the bottom.
    if (smooth && scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight > 160) return;
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }

  async function send(override?: string) {
    const text = (override ?? input).trim();
    if (!text || busy) return;
    if (override === undefined) input = "";
    error = null;
    messages.push({ role: "user", content: text, created_at: new Date().toISOString() });
    scrollDown(false);
    await startRun(text, model, convId, (id) => {
      if (mounted && convId === null && page.url.pathname === "/") {
        created = id; title = text.slice(0, 60);
        replaceState(`/?c=${id}`, {});
      }
    });
  }

  function retry() {
    const i = messages.findLastIndex((m) => m.role === "user");
    if (i < 0) return;
    const text = messages[i].content;
    messages = messages.slice(0, i);
    send(text);
  }

  function exportMd() {
    const md = [`# ${title || "VDX chat"}`, ""]
      .concat(messages.map((m) => `**${m.role === "user" ? "You" : "VDX"}:**\n\n${m.content}\n`)).join("\n");
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    const a = Object.assign(document.createElement("a"), {
      href: url, download: `${(title || "vdx-chat").replace(/[^\w-]+/g, "-").slice(0, 50)}.md`,
    });
    a.click();
    URL.revokeObjectURL(url);
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
  }
  function onGlobalKey(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "o") {
      e.preventDefault(); goto("/"); textarea?.focus();
    }
  }
  function autosize(el: HTMLTextAreaElement) {
    $effect(() => { void input; el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 200)}px`; });
  }
</script>

<svelte:window onkeydown={onGlobalKey} />

{#snippet composer()}
  {#if error}<p class="mx-auto mb-2 w-full max-w-3xl text-[12px] text-[var(--danger)]">{error}</p>{/if}
    <form onsubmit={(e) => { e.preventDefault(); send(); }}
      class="mx-auto flex max-w-3xl flex-col gap-1 w-full rounded-3xl border border-[var(--border)] bg-[var(--bg-panel)] p-2.5 shadow-sm transition-colors focus-within:border-[var(--border-strong)]">
      <textarea bind:this={textarea} bind:value={input} use:autosize onkeydown={onKey} rows="1"
        placeholder="How can I help you today?"
        class="max-h-[200px] min-h-[40px] w-full resize-none bg-transparent px-2 py-2 text-[14px] outline-none placeholder:text-[var(--text-dim)]"></textarea>
      <div class="flex items-center gap-1.5">
        <ModelPicker bind:value={model} fallback={status?.model} />
        <ConnectorsMenu />
        <div class="flex-1"></div>
        {#if lastUsage && !busy}
          <span class="mr-2 hidden text-[11px] text-[var(--text-dim)] sm:inline" title="Last reply: prompt / completion tokens · time · tool calls">
            {lastUsage.prompt_tokens}↑ {lastUsage.completion_tokens}↓ · {(lastUsage.duration_ms / 1000).toFixed(1)}s{lastUsage.tool_calls ? ` · ${lastUsage.tool_calls} tools` : ""}
          </span>
        {/if}
        {#if busy}
          <button type="button" onclick={() => run?.ctrl.abort()} title="Stop" class="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--accent)] text-[var(--accent-text)]"><span class="h-2.5 w-2.5 rounded-[2px] bg-current"></span></button>
        {:else}
          <button type="submit" disabled={!input.trim()}
            title="Send" class="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--accent)] text-[var(--accent-text)] transition hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-30"><svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5m-6 6 6-6 6 6"/></svg></button>
        {/if}
      </div>
    </form>
{/snippet}

<div class="relative z-10 flex h-full min-h-0 flex-1 flex-col">
  <header class="flex h-14 shrink-0 items-center justify-between gap-4 px-5">
    <h1 class="max-w-[50vw] truncate text-[14px] font-medium text-[var(--text-muted)]">{messages.length ? title : ""}</h1>
    <div class="flex items-center gap-2">
      <StatusPill {status} error={offline} />
      {#if messages.length}<button class="ghost-btn !text-[12px]" onclick={exportMd}>Export</button>{/if}
    </div>
  </header>

  {#if messages.length === 0 && !busy}
    <div class="msg-in flex min-h-0 flex-1 flex-col items-center justify-center px-6 pb-[12vh]">
      <div class="mb-7 flex items-center gap-3">
        <span class="logo-tile h-9 w-9 !rounded-[10px]"><img src="/brand/vdx-mark.png" alt="" /></span>
        <span class="text-[26px] font-medium tracking-[-0.01em]">{model || status?.model || "VDX Agent"}</span>
      </div>
      <div class="w-full max-w-2xl">{@render composer()}</div>
      <div class="mt-6 w-full max-w-2xl px-3">
        <p class="mb-2 text-[12.5px] text-[var(--text-dim)]">Suggested</p>
        <div class="flex flex-col">
          {#each HINTS as h (h)}
            <button onclick={() => { input = h; textarea?.focus(); }}
              class="rounded-lg px-2 py-1.5 -mx-2 text-left text-[13.5px] text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text)]">{h}</button>
          {/each}
        </div>
      </div>
    </div>
  {:else}
    <div bind:this={scroller} class="min-h-0 flex-1 overflow-y-auto px-6 py-4">
      <div class="mx-auto flex max-w-3xl flex-col gap-6">
        {#each messages as m, i (i)}
          <MessageBubble role={m.role} content={m.content} time={m.created_at}
            model={m.role === "assistant" ? model || status?.model : undefined}
            onRetry={!busy && i === messages.length - 1 && m.role === "assistant" ? retry : undefined}
            onEdit={m.role === "user" ? () => { input = m.content; textarea?.focus(); } : undefined} />
        {/each}
        {#if pendingQ}<MessageBubble role="user" content={pendingQ} />{/if}
        {#if busy}
          {#if streamText}
            <MessageBubble role="assistant" content={streamText} model={model || status?.model} streaming />
          {:else}
            <div class="msg-in flex items-center gap-3">
              <span class="logo-tile h-6 w-6 !rounded-full"><img src="/brand/vdx-mark.png" alt="" /></span>
              <span class="shimmer text-[13px] font-medium">{toolName ? `Using ${toolName.replace(/_/g, " ")}…` : "Thinking…"}</span>
            </div>
          {/if}
        {/if}
      </div>
    </div>
    <div class="shrink-0 px-6 pb-5 pt-2">{@render composer()}</div>
  {/if}
</div>
