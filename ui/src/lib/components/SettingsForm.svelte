<script lang="ts">
  import { onMount } from "svelte";
  import { getModels, getSettings, saveSettings, testPhone, type SettingsPayload } from "#lib/api";
  import { resetOnboarding } from "#lib/ui";
  import PageHeader from "./PageHeader.svelte";
  import Panel from "./Panel.svelte";
  import SharingPanel from "./SharingPanel.svelte";

  type Field = { key: keyof SettingsPayload; label: string; type?: string; placeholder?: string; list?: boolean };

  const SECTIONS: { title: string; fields: Field[] }[] = [
    { title: "Ollama", fields: [
      { key: "ollama_base_url", label: "Base URL", placeholder: "http://localhost:11434" },
      { key: "ollama_model", label: "Model", list: true },
      { key: "ollama_temperature", label: "Temperature", type: "number" },
      { key: "ollama_timeout", label: "Timeout (s)", type: "number" },
    ] },
    { title: "Gmail", fields: [
      { key: "gmail_address", label: "Address", placeholder: "you@gmail.com" },
      { key: "gmail_app_password", label: "App password", type: "password" },
    ] },
    { title: "Discord", fields: [
      { key: "discord_bot_token", label: "Bot token", type: "password" },
      { key: "discord_prefix", label: "Prefix", placeholder: "!" },
      { key: "discord_allowed_users", label: "Allowed user IDs", placeholder: "comma separated" },
    ] },
    { title: "WhatsApp", fields: [
      { key: "whatsapp_token", label: "Access token", type: "password" },
      { key: "whatsapp_phone_id", label: "Phone number ID" },
    ] },
    { title: "Phone", fields: [
      { key: "ntfy_topic", label: "ntfy topic", placeholder: "click Generate" },
      { key: "ntfy_server", label: "ntfy server", placeholder: "https://ntfy.sh" },
    ] },
    { title: "GitHub & Code", fields: [
      { key: "github_token", label: "GitHub token", type: "password" },
      { key: "code_workspace", label: "Code workspace", placeholder: "~/projects" },
    ] },
  ];

  let form = $state<SettingsPayload>({
    ollama_base_url: "", ollama_model: "", ollama_temperature: 0.7, ollama_timeout: 120,
    gmail_address: "", gmail_app_password: "", discord_bot_token: "", discord_prefix: "!",
    discord_allowed_users: "", whatsapp_token: "", whatsapp_phone_id: "", github_token: "", code_workspace: "",
    ntfy_server: "https://ntfy.sh", ntfy_topic: "",
  });
  let phoneMsg = $state<{ ok: boolean; text: string } | null>(null);

  function newTopic() {
    const bytes = crypto.getRandomValues(new Uint8Array(12));
    form.ntfy_topic = "vdx-" + Array.from(bytes, (b) => b.toString(36).padStart(2, "0")).join("").slice(0, 20);
  }

  async function sendTest() {
    phoneMsg = null;
    try { await save(); phoneMsg = { ok: true, text: (await testPhone()).status }; }
    catch (e) { phoneMsg = { ok: false, text: e instanceof Error ? e.message : "Failed" }; }
  }
  let models = $state<string[]>([]);
  let saving = $state(false);
  let msg = $state<string | null>(null);
  let error = $state<string | null>(null);

  const refreshModels = () => getModels().then((r) => (models = r.models)).catch(() => {});

  onMount(() => {
    getSettings().then((s) => (form = { ...form, ...s })).catch((e) => (error = e.message));
    refreshModels();
  });

  async function save() {
    saving = true; msg = error = null;
    try {
      await saveSettings({ ...form, ollama_temperature: Number(form.ollama_temperature), ollama_timeout: Number(form.ollama_timeout) });
      msg = "Saved";
    } catch (e) { error = e instanceof Error ? e.message : "Save failed"; }
    saving = false;
  }
</script>

<div class="relative z-10 flex h-full min-h-0 flex-1 flex-col">
  <PageHeader title="Settings" subtitle="Persisted to project .env">
    <div class="flex items-center gap-3">
      {#if msg}<span class="text-[12px] text-[var(--ok)]">{msg}</span>{/if}
      {#if error}<span class="text-[12px] text-[var(--danger)]">{error}</span>{/if}
      <button class="ghost-btn !text-[12px]" onclick={resetOnboarding}>Show welcome guide</button>
      <button class="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-[12px] font-medium text-[var(--accent-text)] disabled:opacity-50"
        disabled={saving} onclick={save}>{saving ? "Saving…" : "Save changes"}</button>
    </div>
  </PageHeader>

  <div class="min-h-0 flex-1 overflow-y-auto px-6 py-6">
    <div class="cascade mx-auto flex max-w-3xl flex-col gap-5">
      {#each SECTIONS as s (s.title)}
        <Panel title={s.title}>
          {#snippet action()}
            {#if s.title === "Ollama"}<button class="ghost-btn !text-[12px]" onclick={refreshModels}>Refresh models</button>{/if}
            {#if s.title === "Phone"}
              <div class="flex gap-2">
                <button class="ghost-btn !text-[12px]" onclick={newTopic}>Generate</button>
                <button class="ghost-btn !text-[12px]" disabled={!form.ntfy_topic} onclick={sendTest}>Send test</button>
              </div>
            {/if}
          {/snippet}
          <div class="grid gap-4 md:grid-cols-2">
            {#each s.fields as f (f.key)}
              <label class="flex flex-col gap-1.5">
                <span class="label">{f.label}</span>
                <input class="field" type={f.type ?? "text"} step={f.type === "number" ? "any" : undefined}
                  placeholder={f.placeholder} list={f.list ? "vdx-models" : undefined}
                  bind:value={form[f.key] as string} />
              </label>
            {/each}
          </div>
          {#if s.title === "Phone"}
            <p class="mt-3 text-[12px] leading-relaxed text-[var(--text-muted)]">
              Install the free <a class="text-[var(--accent)] hover:underline" href="https://ntfy.sh" target="_blank" rel="noreferrer">ntfy</a> app
              on your phone and subscribe to this topic. VDX can then message you, and automation results arrive as notifications.
              Anyone who knows the topic name can read it, so keep it random.
            </p>
            {#if phoneMsg}<p class="mt-2 text-[12px] {phoneMsg.ok ? 'text-[var(--ok)]' : 'text-[var(--danger)]'}">{phoneMsg.text}</p>{/if}
          {/if}
        </Panel>
      {/each}
      <SharingPanel />
      <datalist id="vdx-models">{#each models as m (m)}<option value={m}></option>{/each}</datalist>
    </div>
  </div>
</div>
