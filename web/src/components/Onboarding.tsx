"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  getConnectors,
  getPulls,
  getStatus,
  getSystem,
  pullModel,
  setConnector,
  type AgentStatus,
  type Connector,
  type PullState,
  type Recommendation,
  type SystemProfile,
} from "@/lib/api";

const COOKIE = "vdx_onboarded";
const MODEL_KEY = "vdx.model";
const STEPS = ["Welcome", "Engine", "Model", "Connectors", "Start"] as const;

/** True once the user finished (or skipped) the first-boot intro. */
export function isOnboarded(): boolean {
  return typeof document !== "undefined" && document.cookie.split("; ").some((c) => c === `${COOKIE}=1`);
}

function markOnboarded() {
  document.cookie = `${COOKIE}=1; path=/; max-age=${60 * 60 * 24 * 365 * 5}; SameSite=Lax`;
}

/** Re-open the intro (e.g. from Settings). */
export function resetOnboarding() {
  document.cookie = `${COOKIE}=; path=/; max-age=0`;
  location.reload();
}

/** First-boot setup: checks Ollama, picks/downloads a model, enables connectors, suggests a first task. */
export function Onboarding() {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [closing, setClosing] = useState(false);

  useEffect(() => {
    if (!isOnboarded()) setOpen(true);
  }, []);

  const finish = useCallback(() => {
    markOnboarded();
    setClosing(true);
    setTimeout(() => setOpen(false), 260);
  }, []);

  if (!open) return null;
  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  const back = () => setStep((s) => Math.max(s - 1, 0));

  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-md ${
        closing ? "onb-out" : "onb-in"
      }`}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Welcome to VDX"
        className="relative flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--bg-panel)] shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8)]"
      >
        <div className="flex items-center gap-1.5 px-6 pt-5">
          {STEPS.map((s, i) => (
            <div key={s} className="h-1 flex-1 overflow-hidden rounded-full bg-[var(--bg-hover)]">
              <div
                className="h-full rounded-full bg-[var(--accent)] transition-[width] duration-500"
                style={{ width: i <= step ? "100%" : "0%" }}
              />
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between px-6 pt-3">
          <span className="eyebrow">
            Step {step + 1} of {STEPS.length} · {STEPS[step]}
          </span>
          <button type="button" onClick={finish} className="text-[12px] text-[var(--text-dim)] hover:text-[var(--text)]">
            Skip setup
          </button>
        </div>

        <div key={step} className="msg-in min-h-0 flex-1 overflow-y-auto px-6 pb-2 pt-5">
          {step === 0 && <Welcome />}
          {step === 1 && <Engine />}
          {step === 2 && <ModelStep />}
          {step === 3 && <ConnectorsStep />}
          {step === 4 && <StartStep onDone={finish} />}
        </div>

        <div className="flex items-center justify-between border-t border-[var(--border)] px-6 py-4">
          <button
            type="button"
            onClick={back}
            disabled={step === 0}
            className="rounded-lg px-3 py-2 text-[13px] text-[var(--text-muted)] hover:text-[var(--text)] disabled:invisible"
          >
            ← Back
          </button>
          {step < STEPS.length - 1 ? (
            <button
              type="button"
              onClick={next}
              className="rounded-xl bg-white px-5 py-2 text-[13px] font-semibold text-[var(--bg)] hover:bg-[var(--accent)]"
            >
              {step === 0 ? "Let’s set it up" : "Continue"}
            </button>
          ) : (
            <button
              type="button"
              onClick={finish}
              className="rounded-xl bg-white px-5 py-2 text-[13px] font-semibold text-[var(--bg)] hover:bg-[var(--accent)]"
            >
              Open VDX
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Title({ children, sub }: { children: React.ReactNode; sub: string }) {
  return (
    <>
      <h2 className="text-[22px] font-medium tracking-[-0.02em]">{children}</h2>
      <p className="mt-1.5 text-[13.5px] leading-relaxed text-[var(--text-muted)]">{sub}</p>
    </>
  );
}

function Welcome() {
  const points = [
    ["Private by design", "Runs on your Mac with Ollama — your data never leaves this machine."],
    ["Connected", "Mail, Calendar, Reminders, Messages, Notes, GitHub and more."],
    ["Works for you", "Schedule automations that run on their own, every day."],
  ];
  return (
    <div className="flex flex-col items-center text-center">
      <img src="/brand/vdx-mark.png" alt="" className="mb-4 h-12 w-12" />
      <div className="wordmark text-3xl">VDX</div>
      <p className="mt-2 max-w-sm text-[14px] text-[var(--text-muted)]">
        Your local AI agent. Two minutes of setup and it’s ready to work.
      </p>
      <div className="cascade mt-6 grid w-full gap-2 text-left">
        {points.map(([t, d]) => (
          <div key={t} className="rounded-xl border border-[var(--border)] bg-[var(--bg-elevated)] px-4 py-3">
            <div className="text-[13px] font-medium">{t}</div>
            <div className="text-[12px] text-[var(--text-muted)]">{d}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Engine() {
  const [status, setStatus] = useState<AgentStatus | null | "offline">(null);

  const check = useCallback(() => {
    setStatus(null);
    getStatus().then(setStatus).catch(() => setStatus("offline"));
  }, []);

  useEffect(check, [check]);

  const ok = status && status !== "offline" && status.ollama_online;
  return (
    <>
      <Title sub="VDX uses Ollama to run language models locally.">Check the engine</Title>
      <div className="mt-5 flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-elevated)] px-4 py-3.5">
        <span
          className={`h-2.5 w-2.5 rounded-full ${
            status === null ? "animate-pulse bg-[var(--text-dim)]" : ok ? "bg-[var(--ok)] shadow-[0_0_10px_var(--ok)]" : "bg-[var(--danger)]"
          }`}
        />
        <div className="flex-1 text-[13px]">
          {status === null
            ? "Checking…"
            : status === "offline"
              ? "VDX API is not reachable"
              : ok
                ? "Ollama is running"
                : "Ollama is not running"}
        </div>
        <button type="button" onClick={check} className="text-[12px] text-[var(--text-muted)] hover:text-[var(--text)]">
          Re-check
        </button>
      </div>
      {status !== null && !ok && (
        <div className="mt-3 rounded-xl border border-[var(--border)] px-4 py-3 text-[12.5px] leading-relaxed text-[var(--text-muted)]">
          Install Ollama from{" "}
          <a href="https://ollama.com/download" target="_blank" rel="noreferrer" className="text-[var(--accent)] underline-offset-2 hover:underline">
            ollama.com/download
          </a>
          , open it, then press <b>Re-check</b>. You can also continue and do this later.
        </div>
      )}
    </>
  );
}

function ModelStep() {
  const [profile, setProfile] = useState<SystemProfile | null>(null);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [chosen, setChosen] = useState("");
  const [pull, setPull] = useState<PullState | null>(null);

  useEffect(() => {
    getSystem()
      .then((s) => {
        setProfile(s.profile);
        const list = s.recommendations.filter((r) => r.fit !== "too_big").slice(0, 4);
        setRecs(list);
        const best = list.find((r) => r.recommended) ?? list[0];
        if (best) setChosen(best.name);
      })
      .catch(() => {});
  }, []);

  // Poll the download while it runs.
  useEffect(() => {
    if (pull?.state !== "pulling") return;
    const id = setInterval(async () => {
      try {
        const { pulls } = await getPulls();
        const p = pulls.find((x) => x.name === pull.name);
        if (p) setPull(p);
      } catch {}
    }, 800);
    return () => clearInterval(id);
  }, [pull?.state, pull?.name]);

  function pick(name: string) {
    setChosen(name);
    try {
      localStorage.setItem(MODEL_KEY, name);
    } catch {}
  }

  async function download() {
    pick(chosen);
    try {
      setPull(await pullModel(chosen));
    } catch (e) {
      setPull({ name: chosen, state: "error", status: e instanceof Error ? e.message : "Failed", completed: 0, total: 0 });
    }
  }

  const sel = recs.find((r) => r.name === chosen);
  const pct = pull?.total ? Math.round((pull.completed / pull.total) * 100) : 0;
  return (
    <>
      <Title
        sub={
          profile
            ? `Picked for your ${profile.chip} with ${profile.ram_gb} GB of memory.`
            : "Picking the best model for this machine…"
        }
      >
        Choose a brain
      </Title>
      <div className="cascade mt-5 grid gap-2">
        {recs.map((r) => (
          <button
            key={r.name}
            type="button"
            onClick={() => pick(r.name)}
            className={`flex items-center gap-3 rounded-xl border px-4 py-3 text-left ${
              chosen === r.name
                ? "border-[var(--accent)] bg-[var(--accent-dim)]"
                : "border-[var(--border)] bg-[var(--bg-elevated)] hover:border-[var(--border-strong)]"
            }`}
          >
            <span
              className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                chosen === r.name ? "border-[var(--accent)]" : "border-[var(--border-strong)]"
              }`}
            >
              {chosen === r.name && <span className="h-2 w-2 rounded-full bg-[var(--accent)]" />}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <code className="text-[13px]">{r.name}</code>
                {r.recommended && (
                  <span className="rounded-full bg-[var(--accent)] px-2 py-0.5 text-[10px] font-semibold text-[var(--bg)]">Best pick</span>
                )}
              </div>
              <div className="truncate text-[12px] text-[var(--text-muted)]">{r.desc}</div>
            </div>
            <span className="shrink-0 text-[11px] text-[var(--text-dim)]">
              {r.installed ? "✓ Installed" : `${r.size_gb} GB`}
            </span>
          </button>
        ))}
        {!recs.length && <div className="h-32 animate-pulse rounded-xl bg-[var(--bg-elevated)]" />}
      </div>
      {sel && !sel.installed && (
        <div className="mt-4">
          {pull?.state === "pulling" ? (
            <>
              <div className="mb-1.5 flex justify-between text-[12px] text-[var(--text-muted)]">
                <span>Downloading {pull.name}…</span>
                <span className="tabular-nums">{pull.total ? `${pct}%` : pull.status}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-[var(--bg-hover)]">
                <div className="h-full bg-[var(--accent)] transition-[width] duration-700" style={{ width: `${pct}%` }} />
              </div>
              <p className="mt-2 text-[11.5px] text-[var(--text-dim)]">You can continue — it keeps downloading in the background.</p>
            </>
          ) : pull?.state === "done" ? (
            <p className="text-[12.5px] text-[var(--ok)]">✓ {pull.name} is ready</p>
          ) : (
            <button
              type="button"
              onClick={download}
              className="w-full rounded-xl border border-[var(--border-strong)] py-2.5 text-[13px] hover:border-[var(--accent)] hover:text-[var(--accent)]"
            >
              Download {sel.name} ({sel.size_gb} GB)
            </button>
          )}
          {pull?.state === "error" && <p className="mt-2 text-[12px] text-[var(--danger)]">{pull.status}</p>}
        </div>
      )}
    </>
  );
}

function ConnectorsStep() {
  const [list, setList] = useState<Connector[]>([]);

  useEffect(() => {
    getConnectors().then((r) => setList(r.connectors)).catch(() => {});
  }, []);

  async function toggle(c: Connector) {
    setList((l) => l.map((x) => (x.id === c.id ? { ...x, enabled: !x.enabled } : x)));
    try {
      setList((await setConnector(c.id, !c.enabled)).connectors);
    } catch {}
  }

  return (
    <>
      <Title sub="Turn on what VDX may use. macOS will ask for permission the first time each app is used.">
        Connect your apps
      </Title>
      <div className="cascade mt-5 grid gap-2 sm:grid-cols-2">
        {list.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => toggle(c)}
            title={c.configured ? c.description : c.setup_hint}
            className={`flex items-center justify-between gap-2 rounded-xl border px-3.5 py-2.5 text-left ${
              c.enabled ? "border-[color-mix(in_srgb,var(--accent)_50%,var(--border))]" : "border-[var(--border)] opacity-70 hover:opacity-100"
            }`}
          >
            <div className="min-w-0">
              <div className="text-[13px] font-medium">{c.name}</div>
              <div className="truncate text-[11px] text-[var(--text-dim)]">
                {c.configured ? c.description : `Needs setup · ${c.setup_hint}`}
              </div>
            </div>
            <span className={`relative h-4 w-7 shrink-0 rounded-full transition-colors ${c.enabled ? "bg-[var(--accent)]" : "bg-[var(--bg-hover)]"}`}>
              <span
                className={`absolute top-0.5 h-3 w-3 rounded-full bg-[var(--bg)] transition-all ${c.enabled ? "left-3.5" : "left-0.5"}`}
              />
            </span>
          </button>
        ))}
        {!list.length && <div className="h-24 animate-pulse rounded-xl bg-[var(--bg-elevated)] sm:col-span-2" />}
      </div>
    </>
  );
}

function StartStep({ onDone }: { onDone: () => void }) {
  const router = useRouter();
  const ideas = [
    ["💬", "What’s on my calendar today?", "/"],
    ["⏰", "Remind me to stretch at 4pm", "/"],
    ["📬", "Every weekday at 8, summarise my unread email", "/"],
    ["⚙️", "Set up an automation", "/automations/"],
  ];

  function go(text: string, href: string) {
    if (href === "/") {
      try {
        sessionStorage.setItem("vdx.draft", text);
      } catch {}
    }
    onDone();
    router.push(href);
  }

  return (
    <>
      <Title sub="Try one of these, or just type what you need. You can reopen this guide from Settings.">You’re all set</Title>
      <div className="cascade mt-5 grid gap-2">
        {ideas.map(([icon, text, href]) => (
          <button
            key={text}
            type="button"
            onClick={() => go(text, href)}
            className="group flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-elevated)] px-4 py-3 text-left text-[13px] hover:border-[var(--border-strong)]"
          >
            <span className="text-[16px]">{icon}</span>
            <span className="flex-1">{text}</span>
            <span className="text-[var(--text-dim)] transition-transform group-hover:translate-x-0.5 group-hover:text-[var(--text)]">→</span>
          </button>
        ))}
      </div>
    </>
  );
}
