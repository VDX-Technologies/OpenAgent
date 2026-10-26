"use client";

import { useEffect, useState } from "react";
import { resetOnboarding } from "@/components/Onboarding";
import {
  getModels,
  getSettings,
  saveSettings,
  type SettingsPayload,
} from "@/lib/api";

const EMPTY: SettingsPayload = {
  ollama_base_url: "http://localhost:11434",
  ollama_model: "qwen2.5:7b",
  ollama_temperature: 0.7,
  ollama_timeout: 120,
  gmail_address: "",
  gmail_app_password: "",
  discord_bot_token: "",
  discord_prefix: "!",
  discord_allowed_users: "",
  whatsapp_token: "",
  whatsapp_phone_id: "",
  github_token: "",
  code_workspace: "",
};

export function SettingsForm() {
  const [form, setForm] = useState<SettingsPayload>(EMPTY);
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [s, m] = await Promise.all([getSettings(), getModels().catch(() => ({ models: [] }))]);
        setForm(s);
        setModels(m.models);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load settings");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  function set<K extends keyof SettingsPayload>(key: K, value: SettingsPayload[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function onRefreshModels() {
    try {
      const m = await getModels();
      setModels(m.models);
      setMessage(`Found ${m.models.length} model(s)`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not list models");
    }
  }

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      await saveSettings(form);
      setMessage("Saved. Discord token changes need an API restart.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="p-8 text-[13px] text-[var(--text-muted)]">Loading settings…</div>
    );
  }

  return (
    <div className="relative z-10 flex h-full min-h-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center border-b border-[var(--border)] px-6">
        <div>
          <h1 className="text-[15px] font-medium tracking-[-0.015em]">
            Settings
          </h1>
          <p className="text-[11px] text-[var(--text-dim)]">
            Persisted to project <code className="text-[var(--accent)]">.env</code>
          </p>
        </div>
      </header>

      <form onSubmit={onSave} className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-5">
          <Section title="Ollama" subtitle="Local model endpoint">
            <Field label="Base URL">
              <input
                className="field"
                value={form.ollama_base_url}
                onChange={(e) => set("ollama_base_url", e.target.value)}
              />
            </Field>
            <Field
              label="Model"
              action={
                <button type="button" onClick={onRefreshModels} className="ghost-btn">
                  Refresh
                </button>
              }
            >
              <input
                className="field"
                list="ollama-models"
                value={form.ollama_model}
                onChange={(e) => set("ollama_model", e.target.value)}
              />
              <datalist id="ollama-models">
                {models.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Temperature">
                <input
                  className="field"
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={form.ollama_temperature}
                  onChange={(e) => set("ollama_temperature", Number(e.target.value))}
                />
              </Field>
              <Field label="Timeout (s)">
                <input
                  className="field"
                  type="number"
                  min={10}
                  max={600}
                  value={form.ollama_timeout}
                  onChange={(e) => set("ollama_timeout", Number(e.target.value))}
                />
              </Field>
            </div>
          </Section>

          <Section title="Gmail" subtitle="SMTP via App Password">
            <Field label="Address">
              <input
                className="field"
                type="email"
                value={form.gmail_address}
                onChange={(e) => set("gmail_address", e.target.value)}
                placeholder="you@gmail.com"
              />
            </Field>
            <Field label="App Password">
              <input
                className="field"
                type="password"
                value={form.gmail_app_password}
                onChange={(e) => set("gmail_app_password", e.target.value)}
                placeholder="16-character app password"
              />
            </Field>
          </Section>

          <Section title="Discord" subtitle="Remote control — restart API after token change">
            <Field label="Bot Token">
              <input
                className="field"
                type="password"
                value={form.discord_bot_token}
                onChange={(e) => set("discord_bot_token", e.target.value)}
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Prefix">
                <input
                  className="field"
                  value={form.discord_prefix}
                  onChange={(e) => set("discord_prefix", e.target.value)}
                />
              </Field>
              <Field label="Allowed user IDs">
                <input
                  className="field"
                  value={form.discord_allowed_users}
                  onChange={(e) => set("discord_allowed_users", e.target.value)}
                  placeholder="comma-separated"
                />
              </Field>
            </div>
          </Section>

          <Section title="WhatsApp" subtitle="Optional Cloud API — without it, VDX opens WhatsApp Desktop with a pre-filled draft">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Access token">
                <input
                  className="field"
                  type="password"
                  value={form.whatsapp_token}
                  onChange={(e) => set("whatsapp_token", e.target.value)}
                />
              </Field>
              <Field label="Phone number ID">
                <input
                  className="field"
                  value={form.whatsapp_phone_id}
                  onChange={(e) => set("whatsapp_phone_id", e.target.value)}
                />
              </Field>
            </div>
          </Section>

          <Section title="GitHub & Code" subtitle="Coding agent: reads, edits, commits and pushes in a local git repo">
            <Field label="GitHub token (repo scope)">
              <input
                className="field"
                type="password"
                value={form.github_token}
                onChange={(e) => set("github_token", e.target.value)}
                placeholder="ghp_… or github_pat_…"
              />
            </Field>
            <Field label="Repo folder">
              <input
                className="field"
                value={form.code_workspace}
                onChange={(e) => set("code_workspace", e.target.value)}
                placeholder="/Users/you/Developer/my-repo"
              />
            </Field>
          </Section>

          {(message || error) && (
            <p className={`text-[13px] ${error ? "text-[var(--danger)]" : "text-[var(--ok)]"}`}>
              {error || message}
            </p>
          )}

          <div className="flex justify-between pb-8">
            <button
              type="button"
              onClick={resetOnboarding}
              className="rounded-xl border border-[var(--border)] px-4 py-2.5 text-[13px] text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text)]"
            >
              Show welcome guide
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-xl bg-white px-5 py-2.5 text-[13px] font-semibold text-[var(--bg)] transition hover:bg-[var(--text-muted)] disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </div>
      </form>

      <style jsx>{`
        .field {
          width: 100%;
          border-radius: 10px;
          border: 1px solid var(--border);
          background: var(--bg-elevated);
          color: var(--text);
          padding: 0.65rem 0.85rem;
          font-size: 13.5px;
          outline: none;
        }
        .field:focus {
          border-color: color-mix(in srgb, var(--accent) 50%, var(--border));
        }
        .ghost-btn {
          border: 1px solid var(--border);
          border-radius: 8px;
          padding: 0.3rem 0.65rem;
          font-size: 11px;
          color: var(--text-muted);
          background: transparent;
        }
        .ghost-btn:hover {
          color: var(--text);
          border-color: var(--border-strong);
        }
      `}</style>
    </div>
  );
}

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-5">
      <div className="mb-4">
        <h2 className="text-[14px] font-semibold">{title}</h2>
        <p className="text-[12px] text-[var(--text-dim)]">{subtitle}</p>
      </div>
      <div className="flex flex-col gap-3.5">{children}</div>
    </section>
  );
}

function Field({
  label,
  children,
  action,
}: {
  label: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <label className="block">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-[var(--text-dim)]">
          {label}
        </span>
        {action}
      </div>
      {children}
    </label>
  );
}
