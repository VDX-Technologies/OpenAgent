<script lang="ts">
  import { onMount, tick, untrack } from "svelte";
  import { goto, replaceState } from "$app/navigation";
  import { page } from "$app/state";
  import { getActiveRun, getApprovals, getConversation, getModels, getStatus, getUpdate, getVoice,
    type AgentStatus, type Approval, type ChatMessage, type Usage } from "#lib/api";
  import { runs, startRun, stopRun, type RunEnd, type Step } from "#lib/runs.svelte";
  import { storedModel } from "#lib/ui";
  import MessageBubble from "./MessageBubble.svelte";
  import StepsView from "./StepsView.svelte";
  import ApprovalCard from "./ApprovalCard.svelte";
  import StatusPill from "./StatusPill.svelte";
  import AttachMenu, { filesToAttachments, type Attached } from "./AttachMenu.svelte";
  import { Brain, ChevronDown, ChevronUp, FileText, Link, MessageSquare, Pencil, RotateCcw, Search, X } from "@lucide/svelte";
  import ModelPicker from "./ModelPicker.svelte";
  import ConnectorsMenu from "./ConnectorsMenu.svelte";
  import WebToggle from "./WebToggle.svelte";
  import VoiceButton from "./VoiceButton.svelte";
  import HandsFree from "./HandsFree.svelte";

  const HINTS = [
    "What’s on my calendar today?", "Remind me to call Alex at 6pm", "Summarise my unread emails",
    "Remember that I prefer short answers", "Search my documents for the latest invoice",
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
  let thinkModels = $state<string[]>([]);
  let think = $state(false);
  let voiceMode = $state<"native" | "local" | "browser" | null>(null);
  let tts = $state(false);
  let partial = $state("");
  let editing = $state<{ id: number; index: number } | null>(null);
  let dragging = $state(false);
  let serverApprovals = $state<Approval[]>([]);
  let serverBusy = $state(false);

  // shallow replaceState doesn't update page.url, so a just-created chat is tracked via `created`
  const convId = $derived(Number(page.url.searchParams.get("c")) || created);
  // the run lives in a shared store, so it keeps streaming while the user is on another page
  const run = $derived(runs[convId ?? 0]);
  const busy = $derived(!!run);
  const currentModel = $derived(model || status?.model || "");
  const canThink = $derived(thinkModels.includes(currentModel));
  // after navigating back mid-run the server copy may not hold the question yet
  const pendingQ = $derived(run && run.text && messages.findLast((m) => m.role === "user")?.content !== run.text ? run.text : null);

  /** Messages grouped for display: tool steps are shown above the answer they led to. */
  type Item = { m: ChatMessage | null; index: number; steps: Step[] };
  const items = $derived.by(() => {
    const out: Item[] = [];
    let pending: Step[] = [];
    messages.forEach((m, index) => {
      if (m.role === "tool") { pending.push({ name: m.name, args: m.args, ok: m.ok, preview: m.content }); return; }
      out.push({ m, index, steps: m.role === "assistant" ? pending : [] });
      if (m.role === "assistant") pending = [];
    });
    if (pending.length) out.push({ m: null, index: messages.length, steps: pending });
    return out;
  });
  const lastItem = $derived(items.at(-1));

  const refresh = () => getStatus().then((s) => { status = s; offline = false; }).catch(() => (offline = true));

  onMount(() => {
    model = storedModel();
    try {
      const d = sessionStorage.getItem("vdx.draft");
      if (d) { sessionStorage.removeItem("vdx.draft"); input = d; }
      think = localStorage.getItem("vdx.think") === "1";
    } catch {}
    refresh();
    getModels().then((r) => (thinkModels = r.thinking ?? [])).catch(() => {});
    getVoice().then((v) => (tts = v.tts)).catch(() => {});
    const id = setInterval(refresh, 30_000);
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
    lastUsage = null; error = null; editing = null; serverApprovals = []; closeSearch();
    if (id === null) { messages = []; title = ""; return; }
    let alive = true;
    load(id, false, () => alive);
    // a run started before the page reloaded keeps going on the server: follow it
    if (!untrack(() => runs[id])) {
      getApprovals(id).then((r) => alive && (serverApprovals = r.approvals)).catch(() => {});
      getActiveRun().then((r) => { if (alive && r.active?.conversation_id === id) follow(id, () => alive); }).catch(() => {});
    }
    return () => { alive = false; };
  });

  function load(id: number, smooth = true, alive: () => boolean = () => true) {
    return getConversation(id)
      .then((c) => { if (alive()) { messages = c.messages; title = c.title; scrollDown(smooth); } })
      .catch((e) => alive() && (error = e instanceof Error ? e.message : "Could not load chat"));
  }

  async function follow(id: number, alive: () => boolean) {
    serverBusy = true;
    while (alive()) {
      await new Promise((r) => setTimeout(r, 1500));
      const [a, p] = await Promise.all([getActiveRun().catch(() => null), getApprovals(id).catch(() => null)]);
      if (p) serverApprovals = p.approvals;
      if (a?.active?.conversation_id !== id) break;
    }
    serverBusy = false;
    if (alive()) load(id);
  }

  $effect(() => { if (run?.stream || run?.steps.length || run?.approval) scrollDown(); });

  function onRunEnd(ev: Event) {
    const e = (ev as CustomEvent<RunEnd>).detail;
    if (e.id !== convId) return;
    if (e.reply !== undefined) {
      lastUsage = e.usage ?? null;
      if (e.id === null) messages.push({ role: "assistant", content: e.reply, created_at: new Date().toISOString() });
      else load(e.id);
    } else {
      if (e.id !== null) load(e.id);
      else if (e.partial) messages.push({ role: "assistant", content: e.partial, stopped: true });
      if (e.error) error = e.error;
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

  let attached = $state<Attached[]>([]);
  let version = $state("");
  getUpdate().then((u) => (version = u.current)).catch(() => {});

  async function send(override?: string): Promise<RunEnd | undefined> {
    const text = (override ?? input).trim();
    if (!text || busy) return;
    if (override === undefined) input = "";
    const att = {
      images: attached.filter((a) => a.kind === "image").map((a) => a.value),
      urls: attached.filter((a) => a.kind === "url").map((a) => a.value),
      ref_conversations: attached.filter((a) => a.kind === "chat").map((a) => Number(a.value)),
      files: attached.filter((a) => a.kind === "file").map((a) => ({ name: a.label, data: a.value })),
    };
    attached = [];
    error = null;
    const edit = editing;
    editing = null;
    if (edit) messages = messages.slice(0, edit.index);
    messages.push({ role: "user", content: text, created_at: new Date().toISOString() });
    scrollDown(false);
    return startRun(text, model, convId, (id) => {
      if (mounted && convId === null && page.url.pathname === "/") {
        created = id; title = text.slice(0, 60);
        replaceState(`/?c=${id}`, {});
      }
    }, att, { think: canThink ? think : null, edit_of: edit?.id ?? null });
  }

  /** Answer the last question again — the old answer is replaced, not duplicated. */
  function retry() {
    const i = messages.findLastIndex((m) => m.role === "user");
    if (i < 0 || busy || convId === null) return;
    messages = messages.slice(0, i + 1);
    error = null;
    startRun(messages[i].content, model, convId, undefined, undefined, { regenerate: true, think: canThink ? think : null });
  }

  function startEdit(m: ChatMessage, index: number) {
    if (!m.id || busy) return;
    editing = { id: m.id, index };
    input = m.content.replace(/(\n\[(page|chat|images|file)\] .+)+$/, "").trimEnd();
    textarea?.focus();
  }

  function exportMd() {
    const md = [`# ${title || "VDX chat"}`, ""]
      .concat(messages.filter((m) => m.role !== "tool").map((m) => `**${m.role === "user" ? "You" : "VDX"}:**\n\n${m.content}\n`)).join("\n");
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    const a = Object.assign(document.createElement("a"), {
      href: url, download: `${(title || "vdx-chat").replace(/[^\w-]+/g, "-").slice(0, 50)}.md`,
    });
    a.click();
    URL.revokeObjectURL(url);
  }

  // ── search in this chat ──
  let searchOpen = $state(false);
  let q = $state("");
  let hit = $state(0);
  let searchInput: HTMLInputElement | undefined = $state();
  const hits = $derived(q.trim().length < 2 ? [] : items.filter((it) => it.m && it.m.content.toLowerCase().includes(q.trim().toLowerCase())).map((it) => it.index));
  function openSearch() { searchOpen = true; tick().then(() => searchInput?.focus()); }
  function closeSearch() { searchOpen = false; q = ""; hit = 0; }
  function jump(d: number) {
    if (!hits.length) return;
    hit = (hit + d + hits.length) % hits.length;
    document.getElementById(`msg-${hits[hit]}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  $effect(() => { void hits; hit = 0; if (hits.length) tick().then(() => document.getElementById(`msg-${hits[0]}`)?.scrollIntoView({ block: "center" })); });

  function onKey(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
    if (e.key === "Escape" && editing) { editing = null; input = ""; }
  }
  function onGlobalKey(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "o") {
      e.preventDefault(); goto("/"); textarea?.focus();
    }
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === "f" && messages.length) { e.preventDefault(); openSearch(); }
  }
  function autosize(el: HTMLTextAreaElement) {
    $effect(() => { void input; el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 200)}px`; });
  }

  async function addDropped(files: FileList | File[] | null | undefined) {
    if (!files || !files.length) return;
    attached.push(...(await filesToAttachments(Array.from(files), attached)));
    textarea?.focus();
  }
  function onPaste(e: ClipboardEvent) {
    if (e.clipboardData?.files.length) { e.preventDefault(); addDropped(e.clipboardData.files); }
  }
  function toggleThink() {
    think = !think;
    try { localStorage.setItem("vdx.think", think ? "1" : "0"); } catch {}
  }
</script>

<svelte:window onkeydown={onGlobalKey} />

{#snippet composer()}
  {#if error}
    <div class="mx-auto mb-2 flex w-full max-w-3xl items-center gap-3 text-[12px] text-[var(--danger)]">
      <span class="min-w-0 flex-1">{error}</span>
      {#if convId !== null && messages.at(-1)?.role === "user" && !busy}
        <button class="flex items-center gap-1 text-[var(--text-muted)] hover:text-[var(--text)]" onclick={retry}><RotateCcw size={12} strokeWidth={1.8} /> Retry</button>
      {/if}
    </div>
  {/if}
  {#if editing}
    <div class="mx-auto mb-1.5 flex w-full max-w-3xl items-center gap-2 px-3 text-[12px] text-[var(--text-muted)]">
      <Pencil size={12} strokeWidth={1.8} /> Editing a message — sending replaces it and everything after it.
      <button class="ml-auto hover:text-[var(--text)]" onclick={() => { editing = null; input = ""; }}>Cancel</button>
    </div>
  {/if}
    <form onsubmit={(e) => { e.preventDefault(); send(); }}
      class="mx-auto flex max-w-3xl flex-col gap-1 w-full rounded-3xl border border-[var(--border)] bg-[var(--bg-panel)] p-2.5 shadow-sm transition-colors focus-within:border-[var(--border-strong)]">
      {#if attached.length}
        <div class="flex flex-wrap gap-1.5 px-1 pt-1">
          {#each attached as a, i (a.value.slice(0, 64) + i)}
            <span class="flex max-w-[240px] items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] py-1 pl-1 pr-2 text-[12px]">
              {#if a.kind === "image"}<img src={a.value} alt="" class="h-7 w-7 rounded object-cover" />{:else}<span class="pl-1 text-[var(--text-muted)]">{#if a.kind === "url"}<Link size={13} strokeWidth={1.8} />{:else if a.kind === "file"}<FileText size={13} strokeWidth={1.8} />{:else}<MessageSquare size={13} strokeWidth={1.8} />{/if}</span>{/if}
              <span class="truncate">{a.label}</span>
              <button type="button" class="text-[var(--text-dim)] hover:text-[var(--text)]" title="Remove" onclick={() => attached.splice(i, 1)}><X size={13} strokeWidth={1.8} /></button>
            </span>
          {/each}
        </div>
      {/if}
      <textarea bind:this={textarea} bind:value={input} use:autosize onkeydown={onKey} onpaste={onPaste} rows="1"
        placeholder={partial ? partial : "How can I help you today?"}
        class="max-h-[200px] min-h-[40px] w-full resize-none bg-transparent px-2 py-2 text-[14px] outline-none {partial ? 'placeholder:text-[var(--text)]' : 'placeholder:text-[var(--text-dim)]'}"></textarea>
      <div class="flex items-center gap-1.5">
        <AttachMenu bind:items={attached} />
        <ModelPicker bind:value={model} fallback={status?.model} />
        <ConnectorsMenu />
        <WebToggle />
        {#if canThink}
          <button type="button" onclick={toggleThink} title={think ? "Reasoning on: slower, better at hard problems" : "Reasoning off: faster answers"}
            class="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] transition-colors {think ? 'border-[var(--border-strong)] text-[var(--text)]' : 'border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)]'}">
            <Brain size={13} strokeWidth={1.8} /> Think
          </button>
        {/if}
        <div class="flex-1"></div>
        {#if lastUsage && !busy}
          <span class="mr-2 hidden text-[11px] text-[var(--text-dim)] sm:inline" title="Last reply: prompt / completion tokens · time · tool calls">
            {lastUsage.prompt_tokens}↑ {lastUsage.completion_tokens}↓ · {(lastUsage.duration_ms / 1000).toFixed(1)}s{lastUsage.tool_calls ? ` · ${lastUsage.tool_calls} tools` : ""}
          </span>
        {/if}
        {#if voiceMode === "native" && tts}
          <HandsFree onsend={(t) => send(t)} onerror={(m) => (error = m)} />
        {/if}
        <VoiceButton ontext={(t) => { input = input.trim() ? `${input.trimEnd()} ${t}` : t; textarea?.focus(); }}
          onpartial={(t) => (partial = t)} onmode={(m) => (voiceMode = m)} onerror={(m) => (error = m)} />
        {#if busy}
          <button type="button" onclick={() => stopRun(convId)} title="Stop" disabled={run?.stopping}
            class="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--accent)] text-[var(--accent-text)] disabled:opacity-50"><span class="h-2.5 w-2.5 rounded-[2px] bg-current"></span></button>
        {:else}
          <button type="submit" disabled={!input.trim()}
            title="Send" class="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--accent)] text-[var(--accent-text)] transition hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-30"><svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5m-6 6 6-6 6 6"/></svg></button>
        {/if}
      </div>
    </form>
{/snippet}

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="relative z-10 flex h-full min-h-0 flex-1 flex-col"
  ondragover={(e) => { if (e.dataTransfer?.types.includes("Files")) { e.preventDefault(); dragging = true; } }}
  ondragleave={(e) => { if (e.currentTarget === e.target) dragging = false; }}
  ondrop={(e) => { e.preventDefault(); dragging = false; addDropped(e.dataTransfer?.files); }}>
  {#if dragging}
    <div class="pointer-events-none absolute inset-3 z-40 flex items-center justify-center rounded-3xl border-2 border-dashed border-[var(--border-strong)] bg-[var(--bg)]/80 text-[14px] text-[var(--text-muted)]">
      Drop images or documents to attach them
    </div>
  {/if}
  <header class="flex h-14 shrink-0 items-center justify-between gap-4 px-5">
    <h1 class="max-w-[40vw] truncate text-[14px] font-medium text-[var(--text-muted)]">{messages.length ? title : ""}</h1>
    <div class="flex items-center gap-2">
      {#if searchOpen}
        <div class="flex items-center gap-1 rounded-full border border-[var(--border-strong)] px-2.5 py-1">
          <Search size={13} strokeWidth={1.8} class="text-[var(--text-dim)]" />
          <input bind:this={searchInput} bind:value={q} placeholder="Find in chat" class="w-36 bg-transparent text-[12px] outline-none"
            onkeydown={(e) => { if (e.key === "Enter") jump(e.shiftKey ? -1 : 1); if (e.key === "Escape") closeSearch(); }} />
          <span class="text-[11px] tabular-nums text-[var(--text-dim)]">{hits.length ? `${hit + 1}/${hits.length}` : q.trim().length > 1 ? "0" : ""}</span>
          <button class="text-[var(--text-dim)] hover:text-[var(--text)]" title="Previous" onclick={() => jump(-1)}><ChevronUp size={14} /></button>
          <button class="text-[var(--text-dim)] hover:text-[var(--text)]" title="Next" onclick={() => jump(1)}><ChevronDown size={14} /></button>
          <button class="text-[var(--text-dim)] hover:text-[var(--text)]" title="Close" onclick={closeSearch}><X size={14} /></button>
        </div>
      {:else if messages.length}
        <button class="ghost-btn !px-2" title="Find in chat (⌘F)" onclick={openSearch}><Search size={14} strokeWidth={1.8} /></button>
      {/if}
      <StatusPill {status} error={offline} />
      {#if version}<span class="rounded-full border border-[var(--border)] px-2.5 py-1 font-mono text-[11px] text-[var(--text-muted)]" title="VDX OpenAgent version">v{version}</span>{/if}
      {#if messages.length}<button class="ghost-btn !text-[12px]" onclick={exportMd}>Export</button>{/if}
    </div>
  </header>

  {#if messages.length === 0 && !busy}
    <div class="msg-in flex min-h-0 flex-1 flex-col items-center justify-center px-6 pb-[12vh]">
      <div class="mb-7 flex items-center gap-3">
        <span class="logo-tile h-9 w-9 !rounded-[10px]"><img src="/brand/vdx-mark.png" alt="" /></span>
        <span class="text-[26px] font-medium tracking-[-0.01em]">{currentModel || "VDX OpenAgent"}</span>
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
        {#each items as it (it.index)}
          <div id="msg-{it.index}">
            {#if it.m && (it.m.role === "user" || it.m.role === "assistant")}
              {@const m = it.m}
              {#if m.role === "assistant"}<div class="pl-9"><StepsView steps={it.steps} /></div>{/if}
              <MessageBubble role={m.role as "user" | "assistant"} content={m.content} time={m.created_at} thinking={m.thinking} stopped={m.stopped}
                highlight={searchOpen && hits[hit] === it.index}
                model={m.role === "assistant" ? m.model || currentModel : undefined} canSpeak={tts}
                onRetry={!busy && it === lastItem && m.role === "assistant" && convId !== null ? retry : undefined}
                onEdit={m.role === "user" && m.id && !busy ? () => startEdit(m, it.index) : undefined} />
            {:else}
              <div class="pl-9"><StepsView steps={it.steps} /></div>
            {/if}
          </div>
        {/each}
        {#if pendingQ}<MessageBubble role="user" content={pendingQ} />{/if}
        {#each serverApprovals as a (a.id)}
          <div class="pl-9"><ApprovalCard approval={a} ondone={() => (serverApprovals = serverApprovals.filter((x) => x.id !== a.id))} /></div>
        {/each}
        {#if serverBusy && !busy}
          <div class="msg-in flex items-center gap-3">
            <span class="logo-tile h-6 w-6 !rounded-full"><img src="/brand/vdx-mark.png" alt="" /></span>
            <span class="shimmer text-[13px] font-medium">VDX is still working on this…</span>
          </div>
        {/if}
        {#if busy && run}
          <div class="flex flex-col gap-2">
            {#if run.steps.length}<div class="pl-9"><StepsView steps={run.steps} live /></div>{/if}
            {#if run.approval}<div class="pl-9"><ApprovalCard approval={run.approval} /></div>{/if}
            {#if run.stream || run.thinking}
              <MessageBubble role="assistant" content={run.stream} thinking={run.thinking} model={currentModel} streaming />
            {:else if !run.approval}
              <div class="msg-in flex items-center gap-3">
                <span class="logo-tile h-6 w-6 !rounded-full"><img src="/brand/vdx-mark.png" alt="" /></span>
                <span class="shimmer text-[13px] font-medium">
                  {run.stopping ? "Stopping…" : run.status || (run.tool ? `Using ${run.tool.replace(/__/g, " · ").replace(/_/g, " ")}…` : "Thinking…")}
                </span>
              </div>
            {/if}
          </div>
        {/if}
      </div>
    </div>
    <div class="shrink-0 px-6 pb-5 pt-2">{@render composer()}</div>
  {/if}
</div>
