<script lang="ts">
  import { onDestroy } from "svelte";
  import { Headphones, X } from "@lucide/svelte";
  import { getRecording, isSpeaking, speak, startRecording, stopRecording, stopSpeaking } from "#lib/api";
  import type { RunEnd } from "#lib/runs.svelte";

  /**
   * Hands-free conversation: listen → (the user pauses) → send → read the answer aloud → listen again.
   * Say "stop" (or "basta") or press the button to end it.
   */
  let { onsend, onerror }: { onsend: (text: string) => Promise<RunEnd | undefined>; onerror?: (msg: string) => void } = $props();

  let active = $state(false);
  let phase = $state<"listening" | "thinking" | "speaking">("listening");
  let partial = $state("");
  let level = $state(0);
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
  const EXIT = /^(stop|basta|fine|esci|exit|quit|ferma(ti)?)[.!]?$/i;

  async function loop() {
    while (active) {
      phase = "listening"; partial = "";
      try { await startRecording(); } catch (e) { onerror?.(e instanceof Error ? e.message : "Microphone unavailable"); break; }
      while (active) {
        await sleep(300);
        const s = await getRecording().catch(() => null);
        if (!s) continue;
        partial = s.text; level = s.level;
        if (s.ended || s.seconds > 120) break;
      }
      if (!active) { await stopRecording(true).catch(() => {}); break; }
      let heard = { text: "", language: "" };
      try { heard = await stopRecording(); } catch (e) { onerror?.(e instanceof Error ? e.message : "Transcription failed"); break; }
      const text = heard.text.trim();
      partial = text;
      if (!text) continue;
      if (EXIT.test(text)) break;
      phase = "thinking";
      const end = await onsend(text);
      if (!active || !end || end.error) break;
      if (end.reply) {
        phase = "speaking";
        await speak(end.reply, heard.language).catch(() => {});
        await sleep(300);
        while (active && (await isSpeaking().catch(() => ({ speaking: false }))).speaking) await sleep(350);
      }
    }
    active = false; level = 0; partial = "";
  }

  function toggle() {
    if (active) { stop(); return; }
    active = true;
    loop();
  }
  function stop() {
    active = false;
    stopRecording(true).catch(() => {});
    stopSpeaking();
  }
  onDestroy(() => { if (active) stop(); });
</script>

<button type="button" onclick={toggle} title={active ? "End conversation mode" : "Conversation mode: talk, and VDX answers out loud"}
  class="flex h-8 items-center justify-center rounded-full px-2 transition-colors {active ? 'bg-[var(--accent)] text-[var(--accent-text)]' : 'text-[var(--text-muted)] hover:text-[var(--text)]'}">
  <Headphones size={16} strokeWidth={1.8} />
</button>

{#if active}
  <div class="msg-in fixed bottom-28 left-1/2 z-40 flex w-[min(560px,90vw)] -translate-x-1/2 items-center gap-3 rounded-2xl border border-[var(--border-strong)] bg-[var(--bg-panel)] px-4 py-3 shadow-2xl">
    <span class="relative flex h-3 w-3 shrink-0">
      <span class="absolute inline-flex h-full w-full rounded-full {phase === 'listening' ? 'bg-[var(--danger)]' : phase === 'speaking' ? 'bg-[var(--ok)]' : 'bg-[var(--text-dim)]'} opacity-60"
        style:transform="scale({1 + level * 2})"></span>
      <span class="relative inline-flex h-3 w-3 rounded-full {phase === 'listening' ? 'bg-[var(--danger)]' : phase === 'speaking' ? 'bg-[var(--ok)]' : 'bg-[var(--text-dim)]'}"></span>
    </span>
    <div class="min-w-0 flex-1">
      <p class="text-[12px] font-medium text-[var(--text-muted)]">
        {phase === "listening" ? "Listening… pause when you're done" : phase === "thinking" ? "Thinking…" : "Speaking…"}
      </p>
      {#if partial}<p class="truncate text-[13px]">{partial}</p>{/if}
    </div>
    <button class="text-[var(--text-dim)] hover:text-[var(--text)]" title="End conversation mode" onclick={stop}><X size={16} strokeWidth={1.8} /></button>
  </div>
{/if}
