<script lang="ts">
  import { onMount, tick } from "svelte";
  import { ArrowUpRight, Plus } from "@lucide/svelte";
  import { renderMarkdown } from "#lib/markdown";
  import { runs, startRun, stopRun } from "#lib/runs.svelte";
  import { storedModel } from "#lib/ui";
  import ApprovalCard from "#lib/components/ApprovalCard.svelte";
  import VoiceButton from "#lib/components/VoiceButton.svelte";

  /** ⌥Space panel: ask without opening the main window. Follow-ups stay in the same chat until "New". */
  type Api = { hide_quick?: () => void; open_main?: (cid: number | null) => void };
  const api = (): Api => (window as unknown as { pywebview?: { api?: Api } }).pywebview?.api ?? {};

  let input = $state("");
  let partial = $state("");
  let reply = $state("");
  let error = $state("");
  let convId = $state<number | null>(null);
  let box: HTMLTextAreaElement | undefined = $state();
  const run = $derived(runs[convId ?? 0]);

  onMount(() => {
    box?.focus();
    // the window is reused: focus the input every time it is shown again
    const onFocus = () => box?.focus();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  });

  async function ask() {
    const text = input.trim();
    if (!text || run) return;
    input = ""; reply = ""; error = "";
    const end = await startRun(text, storedModel(), convId, (id) => (convId = id));
    convId = end.id ?? convId;
    reply = end.reply ?? end.partial;
    if (end.error) error = end.error;
    await tick();
    box?.focus();
  }
  function reset() { convId = null; reply = ""; error = ""; input = ""; box?.focus(); }
  function onKey(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(); }
    if (e.key === "Escape") { e.preventDefault(); if (run) stopRun(convId); else api().hide_quick?.(); }
  }
  const shown = $derived(run ? run.stream : reply);
</script>

<div class="flex h-screen flex-col overflow-hidden bg-[var(--bg-panel)] text-[var(--text)]">
  <div class="pywebview-drag-region flex items-center gap-2 border-b border-[var(--border)] px-4 py-3">
    <span class="logo-tile h-6 w-6 shrink-0"><img src="/brand/vdx-mark.png" alt="" /></span>
    <textarea bind:this={box} bind:value={input} onkeydown={onKey} rows="1" placeholder={partial || "Ask VDX…"}
      class="min-w-0 flex-1 resize-none bg-transparent py-1 text-[16px] outline-none placeholder:text-[var(--text-dim)]"></textarea>
    <VoiceButton ontext={(t) => { input = input ? `${input} ${t}` : t; ask(); }} onpartial={(t) => (partial = t)} onerror={(m) => (error = m)} />
    {#if convId !== null}
      <button class="text-[var(--text-dim)] hover:text-[var(--text)]" title="New question" onclick={reset}><Plus size={16} /></button>
      <button class="text-[var(--text-dim)] hover:text-[var(--text)]" title="Open in VDX" onclick={() => api().open_main?.(convId)}><ArrowUpRight size={16} /></button>
    {/if}
  </div>
  <div class="min-h-0 flex-1 overflow-y-auto px-5 py-4">
    {#if error}<p class="mb-2 text-[12.5px] text-[var(--danger)]">{error}</p>{/if}
    {#if run?.approval}<ApprovalCard approval={run.approval} />{/if}
    {#if shown}
      <div class="prose-vdx text-[14px]">{@html renderMarkdown(shown, !!run)}</div>
    {:else if run}
      <p class="shimmer text-[13px]">{run.status || (run.tool ? `Using ${run.tool.replace(/_/g, " ")}…` : "Thinking…")}</p>
    {:else}
      <p class="text-[12.5px] text-[var(--text-dim)]">Enter to ask · Esc to close · answers are saved in your chats</p>
    {/if}
  </div>
</div>
