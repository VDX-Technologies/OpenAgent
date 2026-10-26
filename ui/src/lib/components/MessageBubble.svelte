<script lang="ts">
  import { marked, type Tokens } from "marked";

  let { role, content, time, model, streaming = false, onRetry, onEdit }: {
    role: "user" | "assistant"; content: string; time?: string; model?: string; streaming?: boolean;
    onRetry?: () => void; onEdit?: () => void;
  } = $props();

  const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
  const renderer = new marked.Renderer();
  renderer.code = ({ text, lang }: Tokens.Code) =>
    `<div class="code-block"><div class="code-head"><span>${esc(lang || "code")}</span><button type="button" data-copy>Copy</button></div><pre><code>${esc(text)}</code></pre></div>`;
  renderer.link = ({ href, text }: Tokens.Link) => `<a href="${esc(href)}" target="_blank" rel="noreferrer">${text}</a>`;
  renderer.html = ({ text }: Tokens.HTML | Tokens.Tag) => esc(text);

  const html = $derived(role === "assistant" ? (marked.parse(content, { renderer, async: false }) as string) : "");
  let copied = $state(false);
  const fmt = (t?: string) => (t ? new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "");

  function copy() { navigator.clipboard.writeText(content); copied = true; setTimeout(() => (copied = false), 1200); }
  function onClick(e: MouseEvent) {
    const b = (e.target as HTMLElement).closest("[data-copy]") as HTMLButtonElement | null;
    if (!b) return;
    navigator.clipboard.writeText(b.closest(".code-block")?.querySelector("code")?.textContent ?? "");
    b.textContent = "Copied"; setTimeout(() => (b.textContent = "Copy"), 1200);
  }
</script>

{#if role === "user"}
  <div class="msg-in group flex flex-col items-end">
    <div class="max-w-[80%] whitespace-pre-wrap rounded-3xl rounded-br-lg bg-[var(--bg-hover)] px-4 py-2.5 text-[14px] leading-relaxed">{content}</div>
    <div class="mt-1 flex gap-2 text-[11px] text-[var(--text-dim)] opacity-0 group-hover:opacity-100">
      <span>{fmt(time)}</span>
      {#if onEdit}<button onclick={onEdit} class="hover:text-[var(--text)]" title="Edit">✎</button>{/if}
      <button onclick={copy} class="hover:text-[var(--text)]" title="Copy">{copied ? "✓" : "⧉"}</button>
    </div>
  </div>
{:else}
  <div class="msg-in group flex gap-3">
    <span class="logo-tile mt-0.5 h-6 w-6 !rounded-full"><img src="/brand/vdx-mark.png" alt="" /></span>
    <div class="min-w-0 flex-1">
      <div class="mb-1 flex items-baseline gap-2 text-[12px]">
        <span class="font-semibold">VDX</span>
        {#if model}<span class="text-[var(--text-dim)]">{model}</span>{/if}
        <span class="text-[11px] text-[var(--text-dim)]">{fmt(time)}</span>
      </div>
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
      <div class="prose-vdx text-[14px] {streaming ? 'caret' : ''}" onclick={onClick}>{@html html}</div>
      {#if !streaming}
        <div class="mt-1.5 flex gap-3 text-[11.5px] text-[var(--text-dim)] opacity-0 group-hover:opacity-100">
          <button onclick={copy} class="hover:text-[var(--text)]">{copied ? "Copied" : "Copy"}</button>
          {#if onRetry}<button onclick={onRetry} class="hover:text-[var(--text)]">↻ Regenerate</button>{/if}
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  :global(.code-block) { margin: 0.75rem 0; overflow: hidden; border-radius: 10px; border: 1px solid var(--border); background: #0b0c0f; }
  :global(.code-block pre) { margin: 0 !important; border: 0 !important; border-radius: 0 !important; }
  :global(.code-head) { display: flex; justify-content: space-between; padding: 0.35rem 0.8rem; font-size: 11px; color: var(--text-dim); border-bottom: 1px solid var(--border); }
  :global(.code-head button:hover) { color: var(--text); }
  :global(.caret > :last-child::after) { content: "▍"; margin-left: 2px; color: var(--accent); animation: vdx-blink 1s steps(2) infinite; }
  @keyframes -global-vdx-blink { 50% { opacity: 0; } }
</style>
