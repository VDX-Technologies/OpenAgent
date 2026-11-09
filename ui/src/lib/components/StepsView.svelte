<script lang="ts">
  import { Check, ChevronRight, LoaderCircle, MessageSquareText, X } from "@lucide/svelte";
  import type { Step } from "#lib/runs.svelte";

  /** What the agent did before answering: each tool call with its arguments and result. */
  let { steps, live = false }: { steps: Step[]; live?: boolean } = $props();
  let open = $state(false);
  let expanded = $state<number | null>(null);

  const tools = $derived(steps.filter((s) => s.name));
  const failed = $derived(tools.filter((s) => s.ok === false).length);
  const human = (n?: string) => (n ?? "").replace(/__/g, " · ").replace(/_/g, " ");
  function summary(args?: Record<string, unknown>) {
    const v = Object.values(args ?? {}).find((x) => typeof x === "string" || typeof x === "number");
    const s = v === undefined ? "" : String(v);
    return s.length > 70 ? s.slice(0, 70) + "…" : s;
  }
</script>

{#if steps.length}
  <div class="mb-2 text-[12.5px]">
    <button class="flex items-center gap-1.5 text-[var(--text-dim)] hover:text-[var(--text-muted)]" onclick={() => (open = !open)}>
      <ChevronRight size={12} strokeWidth={2} class="transition-transform {open || live ? 'rotate-90' : ''}" />
      {live ? "Working" : "Used"} {tools.length} tool{tools.length === 1 ? "" : "s"}{failed ? ` · ${failed} failed` : ""}
    </button>
    {#if open || live}
      <ol class="mt-1.5 flex flex-col gap-1 border-l border-[var(--border-strong)] pl-3">
        {#each steps as s, i (i)}
          {#if s.note}
            <li class="flex gap-2 text-[var(--text-dim)]"><MessageSquareText size={13} strokeWidth={1.8} class="mt-0.5 shrink-0" /><span class="line-clamp-2">{s.note}</span></li>
          {:else}
            <li>
              <button class="flex w-full items-start gap-2 text-left" onclick={() => (expanded = expanded === i ? null : i)}>
                <span class="mt-0.5 shrink-0">
                  {#if s.ok === undefined}<LoaderCircle size={13} strokeWidth={2} class="animate-spin text-[var(--text-dim)]" />
                  {:else if s.ok}<Check size={13} strokeWidth={2} class="text-[var(--ok)]" />
                  {:else}<X size={13} strokeWidth={2} class="text-[var(--danger)]" />{/if}
                </span>
                <span class="min-w-0">
                  <span class="font-medium text-[var(--text-muted)]">{human(s.name)}</span>
                  {#if summary(s.args)}<span class="ml-1.5 text-[var(--text-dim)]">{summary(s.args)}</span>{/if}
                </span>
              </button>
              {#if expanded === i}
                <div class="mt-1 ml-5 rounded-lg bg-[var(--bg-elevated)] p-2 font-mono text-[11.5px] text-[var(--text-muted)]">
                  {#if s.args && Object.keys(s.args).length}<pre class="whitespace-pre-wrap break-words">{JSON.stringify(s.args, null, 2)}</pre>{/if}
                  {#if s.preview}<pre class="mt-1.5 max-h-48 overflow-y-auto whitespace-pre-wrap break-words border-t border-[var(--border)] pt-1.5">{s.preview}</pre>{/if}
                </div>
              {/if}
            </li>
          {/if}
        {/each}
      </ol>
    {/if}
  </div>
{/if}
