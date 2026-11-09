<script lang="ts">
  import { onMount } from "svelte";
  import { getMCP, notifyConnectors, saveMCP, type MCPState } from "#lib/api";
  import Panel from "./Panel.svelte";

  /** MCP servers: plug any Model Context Protocol server in, its tools become VDX tools. */
  let mcp = $state<MCPState | null>(null);
  let text = $state("");
  let msg = $state<{ ok: boolean; text: string } | null>(null);
  const EXAMPLE = `{
  "mcpServers": {
    "files": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "~/Documents"]
    }
  }
}`;

  const load = () => getMCP().then((s) => { mcp = s; text = s.config; }).catch(() => {});
  onMount(() => {
    load();
    // servers start in the background: refresh their status for a little while
    const id = setInterval(() => getMCP().then((s) => (mcp = s)).catch(() => {}), 3000);
    setTimeout(() => clearInterval(id), 30_000);
    return () => clearInterval(id);
  });

  async function save() {
    msg = null;
    try { mcp = await saveMCP(text); msg = { ok: true, text: "Saved — servers are starting" }; notifyConnectors(); }
    catch (e) { msg = { ok: false, text: e instanceof Error ? e.message : "Save failed" }; }
  }
</script>

<Panel title="MCP servers">
  {#snippet action()}
    <div class="flex gap-2">
      {#if !text.includes('"command"')}<button class="ghost-btn !text-[12px]" onclick={() => (text = EXAMPLE)}>Example</button>{/if}
      <button class="ghost-btn !text-[12px]" onclick={save}>Save & restart</button>
    </div>
  {/snippet}
  <p class="-mt-2 mb-3 text-[12.5px] text-[var(--text-muted)]">
    Add any <a class="text-[var(--accent)] hover:underline" href="https://modelcontextprotocol.io/examples" target="_blank" rel="noreferrer">MCP server</a>
    (same format as Claude Desktop). Its tools appear under Apps; tools that change things ask for approval.
  </p>
  <textarea bind:value={text} spellcheck="false" rows="8"
    class="field w-full resize-y font-mono !text-[12px] leading-relaxed"></textarea>
  {#if msg}<p class="mt-2 text-[12px] {msg.ok ? 'text-[var(--ok)]' : 'text-[var(--danger)]'}">{msg.text}</p>{/if}
  {#if mcp?.servers.length}
    <div class="mt-3 flex flex-col gap-1.5 text-[12.5px]">
      {#each mcp.servers as s (s.name)}
        <div class="flex items-center gap-2">
          <span class="h-2 w-2 rounded-full {s.running ? 'bg-[var(--ok)]' : s.error ? 'bg-[var(--danger)]' : 'bg-[var(--text-dim)]'}"></span>
          <span class="font-medium">{s.name}</span>
          <span class="truncate text-[var(--text-dim)]">{s.running ? `${s.tools.length} tools` : s.error || "starting…"}</span>
        </div>
      {/each}
    </div>
  {/if}
</Panel>
