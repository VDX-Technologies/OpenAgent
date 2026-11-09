<script lang="ts">
  import { Brain, Check, ChevronRight, Copy, FileText, Image, Link, MessageSquare, Pencil, RotateCcw, Square, Volume2 } from "@lucide/svelte";
  import { renderMarkdown } from "#lib/markdown";
  import { isSpeaking, speak, stopSpeaking } from "#lib/api";

  /** Attachment note lines the server appends to a user message: "[page] url", "[chat] title", "[file] name", "[images] n". */
  const NOTE = /^\[(page|chat|images|file)\] (.+)$/;
  const ICONS = { page: Link, chat: MessageSquare, images: Image, file: FileText } as const;

  let { role, content, time, model, streaming = false, thinking = "", stopped = false, highlight = false,
    onRetry, onEdit, canSpeak = false }: {
    role: "user" | "assistant"; content: string; time?: string; model?: string | null; streaming?: boolean;
    thinking?: string; stopped?: boolean; highlight?: boolean; onRetry?: () => void; onEdit?: () => void; canSpeak?: boolean;
  } = $props();

  const parts = $derived.by(() => {
    if (role !== "user") return { text: content, notes: [] as { kind: keyof typeof ICONS; label: string }[] };
    const lines = content.split("\n");
    const notes: { kind: keyof typeof ICONS; label: string }[] = [];
    while (lines.length && NOTE.test(lines[lines.length - 1])) {
      const [, kind, value] = lines.pop()!.match(NOTE)!;
      notes.unshift({ kind: kind as keyof typeof ICONS, label: kind === "images" ? `${value} image${value === "1" ? "" : "s"}` : value });
    }
    return { text: lines.join("\n").trimEnd(), notes };
  });
  const html = $derived(role === "assistant" ? renderMarkdown(content, streaming) : "");
  let copied = $state(false);
  let speaking = $state(false);
  let showThinking = $state(false);
  const fmt = (t?: string) => (t ? new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "");

  function copy() { navigator.clipboard.writeText(parts.text); copied = true; setTimeout(() => (copied = false), 1200); }
  function onClick(e: MouseEvent) {
    const b = (e.target as HTMLElement).closest("[data-copy]") as HTMLButtonElement | null;
    if (!b) return;
    navigator.clipboard.writeText(b.closest(".code-block")?.querySelector("code")?.textContent ?? "");
    b.textContent = "Copied"; setTimeout(() => (b.textContent = "Copy"), 1200);
  }
  async function toggleSpeak() {
    if (speaking) { speaking = false; await stopSpeaking(); return; }
    speaking = true;
    await speak(content).catch(() => (speaking = false));
    // the voice runs on the Mac: check when it's done to reset the button
    const id = setInterval(async () => {
      const s = await isSpeaking().catch(() => ({ speaking: false }));
      if (!s.speaking) { speaking = false; clearInterval(id); }
    }, 800);
  }
</script>

{#if role === "user"}
  <div class="msg-in group flex flex-col items-end {highlight ? 'search-hit' : ''}">
    {#if parts.notes.length}
      <div class="mb-1.5 flex max-w-[80%] flex-wrap justify-end gap-1.5">
        {#each parts.notes as n, i (i)}
          {@const Icon = ICONS[n.kind]}
          <span class="flex max-w-[240px] items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] px-2 py-1 text-[12px] text-[var(--text-muted)]">
            <Icon size={13} strokeWidth={1.8} class="shrink-0" /><span class="truncate">{n.label}</span>
          </span>
        {/each}
      </div>
    {/if}
    {#if parts.text}<div class="max-w-[80%] whitespace-pre-wrap rounded-3xl rounded-br-lg bg-[var(--bg-hover)] px-4 py-2.5 text-[14px] leading-relaxed">{parts.text}</div>{/if}
    <div class="mt-1 flex items-center gap-2 text-[11px] text-[var(--text-dim)] opacity-0 group-hover:opacity-100">
      <span>{fmt(time)}</span>
      {#if onEdit}<button onclick={onEdit} class="hover:text-[var(--text)]" title="Edit and resend"><Pencil size={12} strokeWidth={1.8} /></button>{/if}
      <button onclick={copy} class="hover:text-[var(--text)]" title="Copy">{#if copied}<Check size={12} strokeWidth={1.8} />{:else}<Copy size={12} strokeWidth={1.8} />{/if}</button>
    </div>
  </div>
{:else}
  <div class="msg-in group flex gap-3 {highlight ? 'search-hit' : ''}">
    <span class="logo-tile mt-0.5 h-6 w-6 !rounded-full"><img src="/brand/vdx-mark.png" alt="" /></span>
    <div class="min-w-0 flex-1">
      <div class="mb-1 flex items-baseline gap-2 text-[12px]">
        <span class="font-semibold">VDX</span>
        {#if model}<span class="text-[var(--text-dim)]">{model}</span>{/if}
        <span class="text-[11px] text-[var(--text-dim)]">{fmt(time)}</span>
      </div>
      {#if thinking}
        <button class="mb-1.5 flex items-center gap-1.5 text-[12px] text-[var(--text-dim)] hover:text-[var(--text-muted)]" onclick={() => (showThinking = !showThinking)}>
          <Brain size={13} strokeWidth={1.8} /> {streaming && !content ? "Reasoning…" : "Reasoning"}
          <ChevronRight size={12} strokeWidth={2} class="transition-transform {showThinking || (streaming && !content) ? 'rotate-90' : ''}" />
        </button>
        {#if showThinking || (streaming && !content)}
          <div class="mb-2 max-h-64 overflow-y-auto whitespace-pre-wrap border-l-2 border-[var(--border-strong)] pl-3 text-[12.5px] leading-relaxed text-[var(--text-dim)]">{thinking}</div>
        {/if}
      {/if}
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
      <div class="prose-vdx text-[14px] {streaming ? 'caret' : ''}" onclick={onClick}>{@html html}</div>
      {#if stopped}<p class="mt-1 text-[11.5px] text-[var(--text-dim)]">Stopped</p>{/if}
      {#if !streaming}
        <div class="mt-1.5 flex gap-3 text-[11.5px] text-[var(--text-dim)] opacity-0 group-hover:opacity-100">
          <button onclick={copy} class="hover:text-[var(--text)]">{copied ? "Copied" : "Copy"}</button>
          {#if canSpeak}
            <button onclick={toggleSpeak} class="flex items-center gap-1 hover:text-[var(--text)]">
              {#if speaking}<Square size={11} strokeWidth={2} /> Stop{:else}<Volume2 size={12} strokeWidth={1.8} /> Read aloud{/if}
            </button>
          {/if}
          {#if onRetry}<button onclick={onRetry} class="flex items-center gap-1 hover:text-[var(--text)]"><RotateCcw size={12} strokeWidth={1.8} /> Regenerate</button>{/if}
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  :global(.code-block) { margin: 0.75rem 0; overflow: hidden; border-radius: 10px; border: 1px solid var(--border); background: var(--code-bg); }
  :global(.code-block pre) { margin: 0 !important; border: 0 !important; border-radius: 0 !important; }
  :global(.code-head) { display: flex; justify-content: space-between; padding: 0.35rem 0.8rem; font-size: 11px; color: var(--text-dim); border-bottom: 1px solid var(--border); }
  :global(.code-head button:hover) { color: var(--text); }
  :global(.caret > :last-child::after) { content: "▍"; margin-left: 2px; color: var(--accent); animation: vdx-blink 1s steps(2) infinite; }
  :global(.search-hit) { outline: 2px solid var(--warn); outline-offset: 6px; border-radius: 12px; }
  @keyframes -global-vdx-blink { 50% { opacity: 0; } }
  /* syntax colours (highlight.js), readable in both themes */
  :global(.hljs-keyword), :global(.hljs-selector-tag), :global(.hljs-built_in) { color: #c3489c; }
  :global(.hljs-string), :global(.hljs-attr), :global(.hljs-template-tag) { color: #3f8f3a; }
  :global(.hljs-number), :global(.hljs-literal), :global(.hljs-symbol) { color: #c06a1b; }
  :global(.hljs-comment), :global(.hljs-quote) { color: var(--text-dim); font-style: italic; }
  :global(.hljs-title), :global(.hljs-function .hljs-title), :global(.hljs-section) { color: #3a73c9; }
  :global(.hljs-type), :global(.hljs-class .hljs-title), :global(.hljs-tag), :global(.hljs-name) { color: #8a5cd1; }
  :global(.hljs-variable), :global(.hljs-params), :global(.hljs-meta) { color: #b5862b; }
  @media (prefers-color-scheme: dark) {
    :global(.hljs-keyword), :global(.hljs-selector-tag), :global(.hljs-built_in) { color: #f07ac8; }
    :global(.hljs-string), :global(.hljs-attr), :global(.hljs-template-tag) { color: #8fd18a; }
    :global(.hljs-number), :global(.hljs-literal), :global(.hljs-symbol) { color: #f0a35e; }
    :global(.hljs-title), :global(.hljs-function .hljs-title), :global(.hljs-section) { color: #7fb0ff; }
    :global(.hljs-type), :global(.hljs-class .hljs-title), :global(.hljs-tag), :global(.hljs-name) { color: #c4a3ff; }
    :global(.hljs-variable), :global(.hljs-params), :global(.hljs-meta) { color: #e6c07b; }
  }
</style>
