<script lang="ts">
  import { ShieldCheck } from "@lucide/svelte";
  import { decideApproval, type Approval } from "#lib/api";

  /** Asks the user before the agent sends, deletes or publishes something. */
  let { approval, ondone }: { approval: Approval; ondone?: () => void } = $props();
  let busy = $state(false);
  let error = $state("");

  // the fields that matter most come first and get more room
  const MAIN = ["to", "recipient", "subject", "title", "name", "text", "body", "message", "content", "path", "branch"];
  const fields = $derived(
    Object.entries(approval.args ?? {}).sort(([a], [b]) => (MAIN.indexOf(a) + 1 || 99) - (MAIN.indexOf(b) + 1 || 99)),
  );
  const show = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v, null, 2));

  async function answer(allow: boolean, always = false) {
    busy = true; error = "";
    try { await decideApproval(approval.id, allow, always); ondone?.(); }
    catch (e) { error = e instanceof Error ? e.message : "Failed"; busy = false; }
  }
</script>

<div class="msg-in rounded-2xl border border-[var(--border-strong)] bg-[var(--bg-panel)] p-4 shadow-sm">
  <div class="mb-3 flex items-center gap-2 text-[13px] font-semibold">
    <ShieldCheck size={16} strokeWidth={1.8} class="text-[var(--warn)]" /> Allow VDX to: {approval.label}?
  </div>
  <dl class="flex max-h-72 flex-col gap-2 overflow-y-auto text-[12.5px]">
    {#each fields as [k, v] (k)}
      <div>
        <dt class="text-[11px] tracking-wide text-[var(--text-dim)] uppercase">{k.replace(/_/g, " ")}</dt>
        <dd class="mt-0.5 whitespace-pre-wrap break-words text-[var(--text)]">{show(v)}</dd>
      </div>
    {/each}
  </dl>
  {#if error}<p class="mt-2 text-[12px] text-[var(--danger)]">{error}</p>{/if}
  <div class="mt-4 flex flex-wrap items-center gap-2">
    <button disabled={busy} onclick={() => answer(true)}
      class="rounded-lg bg-[var(--accent)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--accent-text)] disabled:opacity-50">Allow</button>
    <button disabled={busy} onclick={() => answer(false)} class="ghost-btn !text-[12.5px]">Don't allow</button>
    <div class="flex-1"></div>
    <button disabled={busy} onclick={() => answer(true, true)} class="text-[12px] text-[var(--text-dim)] hover:text-[var(--text)]"
      title="Run this kind of action without asking (change it in Settings → Permissions)">Always allow</button>
  </div>
</div>
