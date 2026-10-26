"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  createAutomation,
  deleteAutomation,
  getAutomations,
  runAutomation,
  updateAutomation,
  type Automation,
  type AutomationInput,
  type AutomationKind,
} from "@/lib/api";
import { PageHeader, Panel } from "@/components/ui";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const TEMPLATES: AutomationInput[] = [
  { name: "Morning briefing", prompt: "Summarise today's calendar events, open reminders and unread emails in a short briefing.", kind: "daily", time: "08:00", weekdays: "0,1,2,3,4" },
  { name: "Inbox check", prompt: "Check unread emails and tell me only about the important ones.", kind: "interval", every_minutes: 60 },
  { name: "Weekly review", prompt: "List my calendar events for the coming week and the reminders still open.", kind: "daily", time: "18:00", weekdays: "6" },
];
const EMPTY: AutomationInput = { name: "", prompt: "", kind: "daily", time: "08:00", weekdays: "0,1,2,3,4,5,6", every_minutes: 60, run_at: "", notify: true };
const field = "rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] px-2.5 py-1.5 text-[13px] outline-none placeholder:text-[var(--text-dim)] focus:border-[var(--border-strong)]";

function schedule(a: Automation) {
  if (a.kind === "interval") return `Every ${a.every_minutes} min`;
  if (a.kind === "once") return `Once · ${a.run_at ? new Date(a.run_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "—"}`;
  const d = (a.weekdays ?? "").split(",").filter(Boolean);
  const days = d.length === 7 ? "Every day" : d.join() === "0,1,2,3,4" ? "Weekdays" : d.map((i) => DAYS[+i]).join(" ");
  return `${days} · ${a.time}`;
}

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "—");

export function AutomationsView() {
  const [items, setItems] = useState<Automation[]>([]);
  const [form, setForm] = useState<AutomationInput>(EMPTY);
  const [running, setRunning] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems((await getAutomations()).automations);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "API offline");
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(load, 15_000);
    return () => clearInterval(id);
  }, [load]);

  async function act(fn: () => Promise<unknown>) {
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    }
  }

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    const body = { ...form, run_at: form.kind === "once" && form.run_at ? form.run_at : undefined };
    await act(async () => {
      await createAutomation(body);
      setForm(EMPTY);
    });
  }

  async function onRun(id: number) {
    setRunning(id);
    await act(() => runAutomation(id));
    setRunning(null);
    setOpen(id);
  }

  const days = (form.weekdays ?? "").split(",").filter(Boolean);
  const toggleDay = (i: number) =>
    setForm((f) => ({
      ...f,
      weekdays: (days.includes(String(i)) ? days.filter((d) => d !== String(i)) : [...days, String(i)]).sort().join(","),
    }));

  return (
    <div className="relative z-10 flex h-full min-h-0 flex-1 flex-col">
      <PageHeader title="Automations" subtitle="Prompts VDX runs on a schedule — results land in their own chat and a macOS notification" />

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-5xl flex-col gap-5">
          {error && <p className="text-[13px] text-[var(--danger)]">{error}</p>}

          <Panel
            title="New automation"
            action={
              <div className="flex flex-wrap gap-1.5">
                {TEMPLATES.map((t) => (
                  <button key={t.name} type="button" onClick={() => setForm({ ...EMPTY, ...t })}
                    className="rounded-full border border-[var(--border)] px-2.5 py-0.5 text-[11.5px] text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text)]">
                    {t.name}
                  </button>
                ))}
              </div>
            }
          >
            <form onSubmit={onCreate} className="flex flex-col gap-3">
              <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Name" className={field} />
              <textarea required rows={3} value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })}
                placeholder="What should VDX do? e.g. Summarise my unread emails and remind me of today's meetings" className={`${field} resize-y`} />
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex rounded-lg border border-[var(--border)] p-0.5">
                  {(["daily", "interval", "once"] as AutomationKind[]).map((k) => (
                    <button key={k} type="button" onClick={() => setForm({ ...form, kind: k })}
                      className={`rounded-md px-2.5 py-1 text-[12px] capitalize ${form.kind === k ? "bg-[var(--bg-hover)] text-[var(--text)]" : "text-[var(--text-muted)]"}`}>
                      {k}
                    </button>
                  ))}
                </div>
                {form.kind === "daily" && (
                  <>
                    <input type="time" value={form.time ?? ""} onChange={(e) => setForm({ ...form, time: e.target.value })} className={field} />
                    <div className="flex gap-1">
                      {DAYS.map((d, i) => (
                        <button key={d} type="button" onClick={() => toggleDay(i)}
                          className={`h-7 w-9 rounded-md border text-[11px] ${days.includes(String(i)) ? "border-[var(--accent)] text-[var(--accent)]" : "border-[var(--border)] text-[var(--text-dim)]"}`}>
                          {d}
                        </button>
                      ))}
                    </div>
                  </>
                )}
                {form.kind === "interval" && (
                  <label className="flex items-center gap-2 text-[12.5px] text-[var(--text-muted)]">
                    Every
                    <input type="number" min={1} value={form.every_minutes ?? 60} onChange={(e) => setForm({ ...form, every_minutes: +e.target.value })} className={`${field} w-20`} />
                    minutes
                  </label>
                )}
                {form.kind === "once" && (
                  <input type="datetime-local" required value={form.run_at ?? ""} onChange={(e) => setForm({ ...form, run_at: e.target.value })} className={field} />
                )}
                <label className="flex items-center gap-1.5 text-[12.5px] text-[var(--text-muted)]">
                  <input type="checkbox" checked={!!form.notify} onChange={(e) => setForm({ ...form, notify: e.target.checked })} />
                  Notify
                </label>
                <div className="flex-1" />
                <button type="submit" className="h-8 rounded-lg bg-white px-4 text-[12.5px] font-semibold text-[var(--bg)] hover:bg-[var(--text-muted)]">
                  Create
                </button>
              </div>
              <p className="text-[11.5px] text-[var(--text-dim)]">Tip: you can also just ask in chat — “every weekday at 8 summarise my email”.</p>
            </form>
          </Panel>

          <Panel title={`Scheduled (${items.length})`}>
            {items.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-dim)]">No automations yet.</p>
            ) : (
              <div className="flex flex-col divide-y divide-[var(--border)]">
                {items.map((a) => (
                  <div key={a.id} className={`py-3 ${a.enabled ? "" : "opacity-55"}`}>
                    <div className="flex items-start justify-between gap-3">
                      <button type="button" onClick={() => setOpen(open === a.id ? null : a.id)} className="min-w-0 text-left">
                        <div className="flex items-center gap-2">
                          <span className="text-[13.5px] font-medium">{a.name}</span>
                          {a.last_status && (
                            <span className={`h-1.5 w-1.5 rounded-full ${a.last_status === "ok" ? "bg-[var(--ok)]" : "bg-[var(--danger)]"}`} title={`Last run: ${a.last_status}`} />
                          )}
                        </div>
                        <div className="mt-0.5 text-[11.5px] text-[var(--text-dim)]">
                          {schedule(a)} · next {when(a.next_run)} · {a.runs} runs
                        </div>
                        <p className="mt-1 line-clamp-1 text-[12px] text-[var(--text-muted)]">{a.prompt}</p>
                      </button>
                      <div className="flex shrink-0 items-center gap-3 text-[11.5px]">
                        <button type="button" disabled={running === a.id} onClick={() => onRun(a.id)} className="text-[var(--accent)] hover:underline disabled:opacity-50">
                          {running === a.id ? "Running…" : "Run now"}
                        </button>
                        <button type="button" onClick={() => act(() => updateAutomation(a.id, { enabled: !a.enabled }))} className="text-[var(--text-muted)] hover:text-[var(--text)]">
                          {a.enabled ? "Pause" : "Resume"}
                        </button>
                        <button type="button" onClick={() => confirm(`Delete “${a.name}”?`) && act(() => deleteAutomation(a.id))} className="text-[var(--text-dim)] hover:text-[var(--danger)]">
                          Delete
                        </button>
                      </div>
                    </div>
                    {open === a.id && (
                      <div className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] p-3 text-[12.5px]">
                        <div className="mb-1 flex justify-between text-[11px] text-[var(--text-dim)]">
                          <span>Last run {when(a.last_run)}</span>
                          {a.conversation_id && <Link href={`/?c=${a.conversation_id}`} className="text-[var(--accent)] hover:underline">Open chat →</Link>}
                        </div>
                        <p className="whitespace-pre-wrap text-[var(--text-muted)]">{a.last_result || "Not run yet."}</p>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
