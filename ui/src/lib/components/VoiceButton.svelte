<script lang="ts">
  import { onMount } from "svelte";
  import { LoaderCircle, Mic, Square } from "@lucide/svelte";
  import { getVoice, transcribe } from "#lib/api";

  /** Mic button: records, transcribes, and hands the text to `ontext`. */
  let { ontext, onerror }: { ontext: (text: string) => void; onerror?: (msg: string) => void } = $props();

  type SR = { lang: string; interimResults: boolean; continuous: boolean; start(): void; stop(): void;
    onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
    onerror: ((e: { error: string }) => void) | null; onend: (() => void) | null };

  // "local" = record and transcribe on the Mac (Whisper); "browser" = the browser's own recognizer
  let mode = $state<"local" | "browser" | null>(null);
  let phase = $state<"idle" | "recording" | "working">("idle");
  let seconds = $state(0);
  let recorder: MediaRecorder | null = null;
  let recognizer: SR | null = null;
  let timer: ReturnType<typeof setInterval>;

  const browserSR = () => (window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR })
    .SpeechRecognition ?? (window as unknown as { webkitSpeechRecognition?: new () => SR }).webkitSpeechRecognition;

  onMount(() => {
    const canRecord = !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";
    getVoice()
      .then((v) => (mode = v.available && canRecord ? "local" : browserSR() ? "browser" : null))
      .catch(() => (mode = browserSR() ? "browser" : null));
    return () => { stopTracks(); clearInterval(timer); };
  });

  function fail(msg: string) { phase = "idle"; clearInterval(timer); onerror?.(msg); }

  function stopTracks() { recorder?.stream.getTracks().forEach((t) => t.stop()); }

  async function startLocal() {
    let stream: MediaStream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch { return fail("Microphone access was denied — allow it in System Settings → Privacy → Microphone."); }
    const type = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg"].find((t) => MediaRecorder.isTypeSupported(t));
    const chunks: Blob[] = [];
    recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = async () => {
      stopTracks();
      phase = "working";
      try {
        const { text } = await transcribe(new Blob(chunks, { type: recorder?.mimeType || type || "audio/webm" }));
        if (text) ontext(text);
        phase = "idle";
      } catch (e) { fail(e instanceof Error ? e.message : "Transcription failed"); }
    };
    recorder.start();
  }

  function startBrowser() {
    const Ctor = browserSR();
    if (!Ctor) return fail("Voice input isn't available here");
    let text = "";
    recognizer = new Ctor();
    recognizer.lang = navigator.language || "en-US";
    recognizer.interimResults = false;
    recognizer.continuous = true;
    recognizer.onresult = (e) => { text = Array.from(e.results, (r) => r[0].transcript).join(" "); };
    recognizer.onerror = (e) => fail(e.error === "not-allowed" ? "Microphone access was denied" : `Voice input error: ${e.error}`);
    recognizer.onend = () => { if (text.trim()) ontext(text.trim()); phase = "idle"; clearInterval(timer); };
    recognizer.start();
  }

  async function toggle() {
    if (phase === "working") return;
    if (phase === "recording") {
      clearInterval(timer);
      if (mode === "local") recorder?.stop(); else recognizer?.stop();
      if (mode === "local") phase = "working";
      return;
    }
    phase = "recording"; seconds = 0;
    timer = setInterval(() => (seconds += 1), 1000);
    if (mode === "local") await startLocal(); else startBrowser();
  }
</script>

{#if mode}
  <button type="button" onclick={toggle} disabled={phase === "working"}
    title={phase === "recording" ? "Stop and transcribe" : phase === "working" ? "Transcribing…" : "Speak instead of typing"}
    class="flex h-8 items-center justify-center gap-1.5 rounded-full px-2 text-[12px] transition-colors
      {phase === 'recording' ? 'bg-[var(--danger)] text-white' : 'text-[var(--text-muted)] hover:text-[var(--text)]'}">
    {#if phase === "recording"}
      <Square size={12} strokeWidth={2.4} class="fill-current" />
      <span class="tabular-nums">{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}</span>
    {:else if phase === "working"}
      <LoaderCircle size={16} strokeWidth={1.8} class="animate-spin" />
    {:else}
      <Mic size={16} strokeWidth={1.8} />
    {/if}
  </button>
{/if}
