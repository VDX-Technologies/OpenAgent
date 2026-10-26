<script lang="ts">
  import { confirmAction } from "#lib/confirm.svelte";
  import { createAutomation, deleteAutomation, getAutomations, runAutomation, updateAutomation,
    type Automation, type AutomationInput, type AutomationKind } from "#lib/api";
  import PageHeader from "./PageHeader.svelte";
  import Panel from "./Panel.svelte";

  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const KINDS: AutomationKind[] = ["daily", "interval", "once"];
  const TEMPLATES: AutomationInput[] = [
    { name: "Morning briefing", prompt: "Summarise today's calendar events, open reminders and unread emails in a short briefing.", kind: "daily", time: "08:00", weekdays: "0,1,2,3,4" },
    { name: "Inbox check", prompt: "Check unread emails and tell me only about the important ones.", kind: "interval", every_minutes: 60 },
    { name: "Weekly review", prompt: "List my calendar events for the coming week and the reminders still open.", kind: "daily", time: "18:00", weekdays: "6" },
  ];
  const EMPTY: AutomationInput = { name: "", prompt: "", kind: "daily", time: "08:00", weekdays: "0,1,2,3,4,5,6", every_minutes: 60, run_at: "", notify: true };

  const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "—");
  function schedule(a: Automation) {
    if (a.kind === "interval") return `Every ${a.every_minutes} min`;
    if (a.kind === "once") return `Once · ${when(a.run_at)}`;
    const d = (a.weekdays ?? "").split(",").filter(Boolean);
    const days = d.length === 7 ? "Every day" : d.join() === "0,1,2,3,4" ? "Weekdays" : d.map((i) => DAYS[+i]).join(" ");
    return `${days} · ${a.time}`;
  }

  let items = $state<Automation[]>([]);
  let form = $state<AutomationInput>({ ...EMPTY });
  let running = $state<number | null>(null);
  let open = $state<number | null>(null);
  let error = $state<string | null>(null);

  async function load() {
    try { items = (await getAutomations()).automations; error = null; }
    catch (e) { error = e instanceof Error ? e.message : "API offline"; }
  }
  $effect(() => { load(); const id = setInterval(load, 15_000); return () => clearInterval(id); });

  async function act(fn: () => Promise<unknown>) {
    try { await fn(); await load(); }
    catch (e) { error = e instanceof Error ? e.message : "Request failed"; }
  }

  function onCreate(e: SubmitEvent) {
    e.preventDefault();
    const body = { ...form, run_at: form.kind === "once" && form.run_at ? form.run_at : undefined };
    act(async () => { await createAutomation(body); form = { ...EMPTY }; });
  }

  async function onRun(id: number) {
    running = id;
    await act(() => runAutomation(id));
    running = null; open = id;
  }

  const days = $derived((form.weekdays ?? "").split(",").filter(Boolean));
  const toggleDay = (i: number) => {
    const s = String(i);
    form.weekdays = (days.includes(s) ? days.filter((d) => d !== s) : [...days, s]).sort().join(",");
  };
</script>

<div class="relative z-10 flex h-full min-h-0 flex-1 flex-col">
  <PageHeader title="Automations" subtitle="Prompts VDX runs on a schedule — results land in their own chat and a macOS notification" />
  <div class="min-h-0 flex-1 overflow-y-auto px-6 py-6">
    <div class="mx-auto flex max-w-5xl flex-col gap-5">
      {#if error}<p class="text-[13px] text-[var(--danger)]">{error}</p>{/if}

      <Panel title="New automation">
        {#snippet action()}
          <div class="flex flex-wrap gap-1.5">
            {#each TEMPLATES as t (t.name)}
              <button type="button" onclick={() => (form = { ...EMPTY, ...t })}
                class="rounded-full border border-[var(--border)] px-2.5 py-0.5 text-[11.5px] text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text)]">{t.name}</button>
            {/each}
          </div>
        {/snippet}
        <form onsubmit={onCreate} class="flex flex-col gap-3">
          <input required bind:value={form.name} placeholder="Name" class="field" />
          <textarea required rows="3" bind:value={form.prompt} class="field resize-y"
            placeholder="What should VDX do? e.g. Summarise my unread emails and remind me of today's meetings"></textarea>
          <div class="flex flex-wrap items-center gap-2">
            <div class="flex rounded-lg border border-[var(--border)] p-0.5">
              {#each KINDS as k (k)}
                <button type="button" onclick={() => (form.kind = k)}
                  class="rounded-md px-2.5 py-1 text-[12px] capitalize {form.kind === k ? 'bg-[var(--bg-hover)] text-[var(--text)]' : 'text-[var(--text-muted)]'}">{k}</button>
              {/each}
            </div>
            {#if form.kind === "daily"}
              <input type="time" bind:value={form.time} class="field" />
              <div class="flex gap-1">
                {#each DAYS as d, i (d)}
                  <button type="button" onclick={() => toggleDay(i)}
                    class="h-7 w-9 rounded-md border text-[11px] {days.includes(String(i)) ? 'border-[var(--accent)] text-[var(--accent)]' : 'border-[var(--border)] text-[var(--text-dim)]'}">{d}</button>
                {/each}
              </div>
            {:else if form.kind === "interval"}
              <label class="flex items-center gap-2 text-[12.5px] text-[var(--text-muted)]">
                Every <input type="number" min="1" bind:value={form.every_minutes} class="field w-20" /> minutes
              </label>
            {:else}
              <input type="datetime-local" required bind:value={form.run_at} class="field" />
            {/if}
            <label class="flex items-center gap-1.5 text-[12.5px] text-[var(--text-muted)]">
              <input type="checkbox" bind:checked={form.notify} /> Notify
            </label>
            <div class="flex-1"></div>
            <button type="submit" class="h-8 rounded-lg bg-[var(--accent)] px-4 text-[12.5px] font-semibold text-[var(--accent-text)] hover:opacity-85">Create</button>
          </div>
          <p class="text-[11.5px] text-[var(--text-dim)]">Tip: you can also just ask in chat — “every weekday at 8 summarise my email”.</p>
        </form>
      </Panel>

      <Panel title="Scheduled ({items.length})">
        {#if items.length === 0}
          <p class="text-[12.5px] text-[var(--text-dim)]">No automations yet.</p>
        {:else}
          <div class="flex flex-col divide-y divide-[var(--border)]">
            {#each items as a (a.id)}
              <div class="py-3 {a.enabled ? '' : 'opacity-55'}">
                <div class="flex items-start justify-between gap-3">
                  <button type="button" onclick={() => (open = open === a.id ? null : a.id)} class="min-w-0 text-left">
                    <div class="flex items-center gap-2">
                      <span class="text-[13.5px] font-medium">{a.name}</span>
                      {#if a.last_status}<span title="Last run: {a.last_status}" class="h-1.5 w-1.5 rounded-full {a.last_status === 'ok' ? 'bg-[var(--ok)]' : 'bg-[var(--danger)]'}"></span>{/if}
                    </div>
                    <div class="mt-0.5 text-[11.5px] text-[var(--text-dim)]">{schedule(a)} · next {when(a.next_run)} · {a.runs} runs</div>
                    <p class="mt-1 line-clamp-1 text-[12px] text-[var(--text-muted)]">{a.prompt}</p>
                  </button>
                  <div class="flex shrink-0 items-center gap-3 text-[11.5px]">
                    <button type="button" disabled={running === a.id} onclick={() => onRun(a.id)} class="text-[var(--accent)] hover:underline disabled:opacity-50">{running === a.id ? "Running…" : "Run now"}</button>
                    <button type="button" onclick={() => act(() => updateAutomation(a.id, { enabled: !a.enabled }))} class="text-[var(--text-muted)] hover:text-[var(--text)]">{a.enabled ? "Pause" : "Resume"}</button>
                    <button type="button" onclick={async () => (await confirmAction(`Delete “${a.name}”?`)) && act(() => deleteAutomation(a.id))} class="text-[var(--text-dim)] hover:text-[var(--danger)]">Delete</button>
                  </div>
                </div>
                {#if open === a.id}
                  <div class="msg-in mt-2 rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] p-3 text-[12.5px]">
                    <div class="mb-1 flex justify-between text-[11px] text-[var(--text-dim)]">
                      <span>Last run {when(a.last_run)}</span>
                      {#if a.conversation_id}<a href="/?c={a.conversation_id}" class="text-[var(--accent)] hover:underline">Open chat →</a>{/if}
                    </div>
                    <p class="whitespace-pre-wrap text-[var(--text-muted)]">{a.last_result || "Not run yet."}</p>
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      </Panel>
    </div>
  </div>
</div>
