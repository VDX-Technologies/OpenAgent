<script lang="ts">
  import { getUsage, type UsageReport } from "#lib/api";
  import { fmtNum } from "#lib/ui";
  import PageHeader from "./PageHeader.svelte";
  import Panel from "./Panel.svelte";
  import Stat from "./Stat.svelte";
  import Table from "./Table.svelte";
  import RangeTabs from "./RangeTabs.svelte";
  import Heatmap from "./Heatmap.svelte";

  let days = $state(30);
  let data = $state<UsageReport | null>(null);
  let error = $state<string | null>(null);

  $effect(() => {
    getUsage(days).then((d) => { data = d; error = null; })
      .catch((e) => (error = e instanceof Error ? e.message : "Failed to load usage"));
  });

  // the heatmap always shows the full year, independent of the range tabs
  let year = $state<UsageReport | null>(null);
  $effect(() => { getUsage(365).then((d) => (year = d)).catch(() => {}); });

  const t = $derived(data?.totals);
</script>

{#snippet empty()}<p class="text-[12.5px] text-[var(--text-dim)]">No requests in this range yet.</p>{/snippet}

<div class="relative z-10 flex h-full min-h-0 flex-1 flex-col">
  <PageHeader title="Usage" subtitle="Tokens and latency of every agent request — all local, all free">
    <RangeTabs ranges={[1, 7, 30, 90]} bind:value={days} />
  </PageHeader>

  <div class="min-h-0 flex-1 overflow-y-auto px-6 py-6">
    <div class="mx-auto flex max-w-5xl flex-col gap-5">
      {#if error}<p class="text-[13px] text-[var(--danger)]">{error}</p>{/if}

      <div class="cascade grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Requests" value={fmtNum(t?.requests)} />
        <Stat label="Prompt tokens" value={fmtNum(t?.prompt_tokens)} />
        <Stat label="Output tokens" value={fmtNum(t?.completion_tokens)} />
        <Stat label="Avg latency" value={t?.requests ? `${(t.duration_ms / t.requests / 1000).toFixed(1)}s` : "—"} />
        <Stat label="Tool calls" value={fmtNum(t?.tool_calls)} />
      </div>

      <Panel title="Activity · last 12 months">
        <Heatmap days={year?.by_day ?? []} />
      </Panel>

      <Panel title="By model">
        {#if data?.by_model.length}
          <Table head={["Model", "Requests", "Prompt", "Output", "Avg latency", "Tok/s", "Tools"]}>
            {#each data.by_model as m (m.model)}
              <tr>
                <td><code class="text-[var(--text)]">{m.model}</code></td>
                <td>{fmtNum(m.requests)}</td><td>{fmtNum(m.prompt_tokens)}</td><td>{fmtNum(m.completion_tokens)}</td>
                <td>{(m.duration_ms / Math.max(1, m.requests) / 1000).toFixed(1)}s</td>
                <td>{m.duration_ms ? (m.completion_tokens / (m.duration_ms / 1000)).toFixed(1) : "—"}</td>
                <td>{fmtNum(m.tool_calls)}</td>
              </tr>
            {/each}
          </Table>
        {:else}{@render empty()}{/if}
      </Panel>

      <Panel title="Recent requests">
        {#if data?.recent.length}
          <Table head={["When", "Chat", "Model", "Source", "Prompt", "Output", "Time", "Tools"]}>
            {#each data.recent as r (r.id)}
              <tr>
                <td>{new Date(r.created_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}</td>
                <td><span class="block max-w-[200px] truncate">{r.conversation_title || "—"}</span></td>
                <td><code>{r.model}</code></td><td>{r.source}</td>
                <td>{fmtNum(r.prompt_tokens)}</td><td>{fmtNum(r.completion_tokens)}</td>
                <td>{(r.duration_ms / 1000).toFixed(1)}s</td><td>{r.tool_calls}</td>
              </tr>
            {/each}
          </Table>
        {:else}{@render empty()}{/if}
      </Panel>
    </div>
  </div>
</div>
