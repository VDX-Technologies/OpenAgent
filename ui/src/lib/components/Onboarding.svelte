<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { getConnectors, getPulls, getStatus, getSystem, pullModel, setConnector,
    type Connector, type PullState, type Recommendation } from "#lib/api";
  import { isOnboarded, markOnboarded, storeModel } from "#lib/ui";

  const STEPS = ["Welcome", "Engine", "Model", "Connectors", "Start"];
  const IDEAS = [
    { text: "What's on my calendar this week?", href: "/" },
    { text: "Remind me to call Marco tomorrow at 10am", href: "/" },
    { text: "Summarise my unread emails", href: "/" },
    { text: "Every morning at 8, brief me on my day", href: "/automations" },
  ];

  let open = $state(false);
  let leaving = $state(false);
  let step = $state(0);
  let online = $state<boolean | null>(null);
  let recs = $state<Recommendation[]>([]);
  let chosen = $state("");
  let pull = $state<PullState | null>(null);
  let connectors = $state<Connector[]>([]);

  onMount(() => { open = !isOnboarded(); });

  const check = () => { online = null; getStatus().then((s) => (online = s.ollama_online)).catch(() => (online = false)); };

  $effect(() => {
    if (!open) return;
    if (step === 1) check();
    if (step === 2 && !recs.length)
      getSystem().then((r) => {
        recs = r.recommendations.filter((m) => m.fit !== "too_big").slice(0, 4);
        chosen = (recs.find((m) => m.recommended) ?? recs[0])?.name ?? "";
      }).catch(() => {});
    if (step === 3 && !connectors.length) getConnectors().then((r) => (connectors = r.connectors)).catch(() => {});
  });

  $effect(() => {
    if (pull?.state !== "pulling") return;
    const id = setInterval(async () => {
      const r = await getPulls().catch(() => null);
      const p = r?.pulls.find((x) => x.name === pull?.name);
      if (p) pull = p;
    }, 800);
    return () => clearInterval(id);
  });

  function pick(name: string) { chosen = name; storeModel(name); }
  async function download() { storeModel(chosen); pull = await pullModel(chosen).catch(() => null); }
  async function toggle(c: Connector) { connectors = (await setConnector(c.id, !c.enabled)).connectors; }

  function finish(href?: string, draft?: string) {
    markOnboarded();
    if (draft) sessionStorage.setItem("vdx.draft", draft);
    leaving = true;
    setTimeout(() => { open = false; if (href) goto(href); }, 260);
  }
</script>

{#if open}
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6 backdrop-blur-sm {leaving ? 'onb-out' : 'onb-in'}">
    <div class="w-full max-w-lg overflow-hidden rounded-2xl border border-[var(--border-strong)] bg-[var(--bg-elevated)] shadow-2xl">
      <div class="h-0.5 bg-[var(--border)]">
        <div class="h-full bg-[var(--accent)] transition-all duration-500" style="width: {((step + 1) / STEPS.length) * 100}%"></div>
      </div>
      <div class="flex items-center justify-between px-6 pt-5">
        <span class="eyebrow">{step + 1} / {STEPS.length} · {STEPS[step]}</span>
        <button class="text-[12px] text-[var(--text-dim)] hover:text-[var(--text)]" onclick={() => finish()}>Skip</button>
      </div>

      {#key step}
        <div class="msg-in min-h-[280px] px-6 py-5">
          {#if step === 0}
            <span class="logo-tile mb-4 h-12 w-12 !rounded-xl"><img src="/brand/vdx-mark.png" alt="VDX" /></span>
            <h2 class="wordmark text-[24px]">Welcome to VDX OpenAgent</h2>
            <ul class="mt-4 flex flex-col gap-2 text-[13px] text-[var(--text-muted)]">
              <li>· Runs 100% locally on your Mac with Ollama.</li>
              <li>· Talks to Calendar, Reminders, Mail, GitHub and more.</li>
              <li>· Automates recurring tasks while you work.</li>
            </ul>
          {:else if step === 1}
            <h2 class="text-[18px] font-semibold">Local engine</h2>
            <p class="mt-2 text-[13px] text-[var(--text-muted)]">VDX uses Ollama to run models on this machine.</p>
            <div class="mt-5 flex items-center gap-3 text-[13px]">
              <span class="h-2 w-2 rounded-full {online ? 'bg-[var(--ok)]' : online === false ? 'bg-[var(--danger)]' : 'bg-[var(--text-dim)]'}"></span>
              {online === null ? "Checking…" : online ? "Ollama is running" : "Ollama is not reachable"}
              <button class="ghost-btn !text-[12px]" onclick={check}>Re-check</button>
            </div>
            {#if online === false}
              <p class="mt-4 text-[12px] text-[var(--text-dim)]">Install from ollama.com, or run <code>brew install ollama && ollama serve</code>.</p>
            {/if}
          {:else if step === 2}
            <h2 class="text-[18px] font-semibold">Pick a model</h2>
            <p class="mt-2 text-[13px] text-[var(--text-muted)]">Recommended for this machine.</p>
            <div class="mt-4 flex flex-col gap-2">
              {#each recs as m (m.name)}
                <button class="rounded-lg border px-3 py-2 text-left text-[12.5px] transition-colors {chosen === m.name ? 'border-[var(--accent)] bg-[var(--bg-hover)]' : 'border-[var(--border)] hover:bg-[var(--bg-hover)]'}"
                  onclick={() => pick(m.name)}>
                  <div class="flex justify-between"><code>{m.name}</code><span class="text-[var(--text-dim)]">{m.size_gb} GB{m.installed ? " · installed" : ""}</span></div>
                  <div class="mt-0.5 text-[11.5px] text-[var(--text-dim)]">{m.desc}</div>
                </button>
              {/each}
            </div>
            {@const sel = recs.find((m) => m.name === chosen)}
            {#if sel && !sel.installed}
              <div class="mt-4 flex items-center gap-3 text-[12px]">
                <button class="ghost-btn !text-[12px]" disabled={pull?.state === "pulling"} onclick={download}>Download</button>
                {#if pull}
                  <span class="text-[var(--text-dim)]">
                    {pull.state === "done" ? "Ready" : pull.state === "error" ? pull.status : `${pull.status} ${pull.total ? Math.round((pull.completed / pull.total) * 100) + "%" : ""}`}
                  </span>
                {/if}
              </div>
            {/if}
          {:else if step === 3}
            <h2 class="text-[18px] font-semibold">Connectors</h2>
            <p class="mt-2 text-[13px] text-[var(--text-muted)]">Turn on what the agent may use. Fewer = faster.</p>
            <div class="mt-4 flex max-h-56 flex-col gap-1 overflow-y-auto">
              {#each connectors as c (c.id)}
                <button class="flex items-center justify-between rounded-lg px-3 py-2 text-left text-[12.5px] hover:bg-[var(--bg-hover)]" onclick={() => toggle(c)}>
                  <span>{c.name}<span class="ml-2 text-[11px] text-[var(--text-dim)]">{c.configured ? "" : "needs setup"}</span></span>
                  <span class="relative h-4 w-7 rounded-full transition-colors {c.enabled ? 'bg-[var(--accent)]' : 'bg-[var(--border-strong)]'}">
                    <span class="absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all {c.enabled ? 'left-3.5' : 'left-0.5'}"></span>
                  </span>
                </button>
              {/each}
            </div>
          {:else}
            <h2 class="text-[18px] font-semibold">You're all set</h2>
            <p class="mt-2 text-[13px] text-[var(--text-muted)]">Try one of these:</p>
            <div class="mt-4 flex flex-col gap-2">
              {#each IDEAS as i (i.text)}
                <button class="rounded-lg border border-[var(--border)] px-3 py-2 text-left text-[12.5px] hover:bg-[var(--bg-hover)]"
                  onclick={() => finish(i.href, i.text)}>{i.text}</button>
              {/each}
            </div>
          {/if}
        </div>
      {/key}

      <div class="flex justify-between border-t border-[var(--border)] px-6 py-4">
        <button class="ghost-btn !text-[12px]" disabled={step === 0} onclick={() => step--}>Back</button>
        {#if step < STEPS.length - 1}
          <button class="rounded-lg bg-[var(--accent)] px-4 py-1.5 text-[12px] font-medium text-[var(--accent-text)]" onclick={() => step++}>Continue</button>
        {:else}
          <button class="rounded-lg bg-[var(--accent)] px-4 py-1.5 text-[12px] font-medium text-[var(--accent-text)]" onclick={() => finish("/")}>Open chat</button>
        {/if}
      </div>
    </div>
  </div>
{/if}
