<script lang="ts">
  import type { AgentStatus } from "#lib/api";
  let { status, error }: { status: AgentStatus | null; error: boolean } = $props();
</script>

<div class="flex items-center gap-2 rounded-full border border-[var(--border)] px-3 py-1 text-[11.5px] text-[var(--text-muted)]">
  {#if error}
    <span class="h-1.5 w-1.5 rounded-full bg-[var(--danger)]"></span>API offline
  {:else if !status}
    <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--text-dim)]"></span>Connecting…
  {:else}
    <span class="h-1.5 w-1.5 rounded-full {status.ollama_online ? 'bg-[var(--ok)]' : 'bg-[var(--warn)]'}"></span>
    <span class="max-w-40 truncate">{status.ollama_online ? status.model : "Ollama offline"}</span>
  {/if}
</div>
