<script lang="ts">
  import { onMount } from "svelte";
  import { FolderOpen, Trash2 } from "@lucide/svelte";
  import { addKnowledge, deleteFact, getFacts, getKnowledge, getModelsDetailed, getPulls, pullModel, removeKnowledge, saveFact,
    type Fact, type Knowledge } from "#lib/api";
  import { confirmAction } from "#lib/confirm.svelte";
  import PageHeader from "./PageHeader.svelte";
  import Panel from "./Panel.svelte";

  const EMBED = "nomic-embed-text";
  let facts = $state<Fact[]>([]);
  let know = $state<Knowledge | null>(null);
  let key = $state("");
  let value = $state("");
  let folder = $state("");
  let error = $state<string | null>(null);
  let embedInstalled = $state<boolean | null>(null);
  let pulling = $state("");
  let editing = $state<string | null>(null);

  const loadFacts = () => getFacts().then((r) => (facts = r.facts)).catch((e) => (error = e.message));
  const loadKnow = () => getKnowledge().then((r) => (know = r)).catch(() => {});

  onMount(() => {
    loadFacts(); loadKnow();
    getModelsDetailed().then((r) => (embedInstalled = r.models.some((m) => m.name.startsWith(EMBED)))).catch(() => (embedInstalled = null));
  });

  // follow indexing progress
  $effect(() => {
    if (!know?.status.running) return;
    const id = setInterval(loadKnow, 1000);
    return () => clearInterval(id);
  });

  async function add(e: SubmitEvent) {
    e.preventDefault();
    if (!key.trim() || !value.trim()) return;
    try { facts = (await saveFact(key.trim(), value.trim())).facts; key = value = ""; editing = null; error = null; }
    catch (err) { error = err instanceof Error ? err.message : "Could not save"; }
  }
  async function remove(f: Fact) {
    if (!(await confirmAction(`Forget “${f.key}”?`))) return;
    facts = (await deleteFact(f.key)).facts;
  }
  async function addFolder(e: SubmitEvent) {
    e.preventDefault();
    if (!folder.trim()) return;
    try { know = await addKnowledge(folder.trim()); folder = ""; error = null; }
    catch (err) { error = err instanceof Error ? err.message : "Could not add folder"; }
  }
  async function removeFolder(path: string) {
    if (!(await confirmAction(`Remove ${path} from the index?`))) return;
    know = await removeKnowledge(path);
  }
  async function installEmbed() {
    pulling = "starting";
    await pullModel(EMBED).catch(() => {});
    const id = setInterval(async () => {
      const p = (await getPulls().catch(() => null))?.pulls.find((x) => x.name === EMBED);
      if (!p) return;
      pulling = p.state === "pulling" ? `${p.total ? Math.round((p.completed / p.total) * 100) : 0}%` : p.state === "error" ? p.status : "";
      if (p.state !== "pulling") { clearInterval(id); embedInstalled = p.state === "done"; }
    }, 800);
  }
</script>

<div class="relative z-10 flex h-full min-h-0 flex-1 flex-col">
  <PageHeader title="Memory" subtitle="What VDX knows about you, and the files it can search — all stored on this Mac" />
  <div class="min-h-0 flex-1 overflow-y-auto px-6 py-6">
    <div class="cascade mx-auto flex max-w-3xl flex-col gap-5">
      {#if error}<p class="text-[13px] text-[var(--danger)]">{error}</p>{/if}

      <Panel title="What VDX knows about you">
        <p class="-mt-2 mb-4 text-[12.5px] text-[var(--text-muted)]">
          Tell VDX things like “remember that my partner is Giulia” in any chat, or add them here. They're used in every conversation.
        </p>
        <div class="flex flex-col divide-y divide-[var(--border)]">
          {#each facts as f (f.key)}
            <div class="group flex items-start gap-3 py-2.5">
              <span class="w-40 shrink-0 text-[12.5px] font-medium">{f.key}</span>
              <span class="min-w-0 flex-1 text-[12.5px] text-[var(--text-muted)]">{f.value}</span>
              <button class="text-[11.5px] text-[var(--text-dim)] opacity-0 group-hover:opacity-100 hover:text-[var(--text)]"
                onclick={() => { editing = f.key; key = f.key; value = f.value; }}>Edit</button>
              <button class="text-[var(--text-dim)] opacity-0 group-hover:opacity-100 hover:text-[var(--danger)]" title="Forget" onclick={() => remove(f)}><Trash2 size={13} strokeWidth={1.8} /></button>
            </div>
          {:else}
            <p class="py-3 text-[12.5px] text-[var(--text-dim)]">Nothing yet.</p>
          {/each}
        </div>
        <form class="mt-4 flex gap-2" onsubmit={add}>
          <input class="field !w-44 shrink-0" placeholder="e.g. coffee order" bind:value={key} readonly={editing !== null} />
          <input class="field !w-auto min-w-0 flex-1" placeholder="e.g. flat white, no sugar" bind:value={value} />
          <button class="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-[12px] font-medium text-[var(--accent-text)]">{editing ? "Save" : "Add"}</button>
          {#if editing}<button type="button" class="ghost-btn !text-[12px]" onclick={() => { editing = null; key = value = ""; }}>Cancel</button>{/if}
        </form>
      </Panel>

      <Panel title="Files VDX can search">
        <p class="-mt-2 mb-4 text-[12.5px] text-[var(--text-muted)]">
          Add folders (documents, notes, projects). VDX indexes PDFs, Word and text files locally and finds passages by meaning —
          ask “what does the lease say about pets?”.
        </p>
        {#if embedInstalled === false}
          <div class="mb-4 flex items-center gap-3 rounded-lg border border-[var(--border)] p-3 text-[12.5px]">
            <span class="min-w-0 flex-1 text-[var(--text-muted)]">Search by meaning needs the small <code>{EMBED}</code> model (274 MB). Without it, search matches keywords only.</span>
            <button class="ghost-btn !text-[12px]" disabled={!!pulling} onclick={installEmbed}>{pulling ? `Installing ${pulling}` : "Install"}</button>
          </div>
        {/if}
        <div class="flex flex-col divide-y divide-[var(--border)]">
          {#each know?.folders ?? [] as f (f.path)}
            <div class="flex items-center gap-3 py-2.5 text-[12.5px]">
              <FolderOpen size={15} strokeWidth={1.7} class="shrink-0 text-[var(--text-muted)]" />
              <span class="min-w-0 flex-1 truncate" title={f.path}>{f.path}</span>
              <span class="text-[var(--text-dim)]">{f.files} files · {f.chunks} passages</span>
              <button class="text-[var(--text-dim)] hover:text-[var(--danger)]" title="Remove" onclick={() => removeFolder(f.path)}><Trash2 size={13} strokeWidth={1.8} /></button>
            </div>
          {:else}
            <p class="py-3 text-[12.5px] text-[var(--text-dim)]">No folders yet.</p>
          {/each}
        </div>
        {#if know?.status.running}
          <p class="mt-3 text-[12px] text-[var(--text-muted)]">Indexing {know.status.path}… {know.status.done}/{know.status.total}</p>
        {:else if know?.status.error}
          <p class="mt-3 text-[12px] text-[var(--warn)]">{know.status.error}</p>
        {/if}
        <form class="mt-4 flex gap-2" onsubmit={addFolder}>
          <input class="field !w-auto min-w-0 flex-1" placeholder="~/Documents/Work" bind:value={folder} />
          <button class="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-[12px] font-medium text-[var(--accent-text)]" disabled={know?.status.running}>Add folder</button>
        </form>
      </Panel>
    </div>
  </div>
</div>
