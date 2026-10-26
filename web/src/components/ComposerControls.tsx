"use client";

import { useEffect, useRef, useState } from "react";
import { getConnectors, getModels, setConnector, type Connector } from "@/lib/api";

const MODEL_KEY = "vdx.model";

/** Close a popover when clicking outside of it. */
function useOutside(ref: React.RefObject<HTMLElement | null>, onOut: () => void) {
  useEffect(() => {
    function h(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onOut();
    }
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [ref, onOut]);
}

const menu =
  "vdx-popover absolute bottom-full left-0 z-20 mb-2 w-72 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-1 shadow-2xl";
const chip =
  "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[12px] text-[var(--text-muted)] transition hover:bg-[var(--bg-hover)] hover:text-[var(--text)]";

/** ChatGPT-style model switcher. Persists the choice in localStorage. */
export function ModelPicker({
  value,
  onChange,
  fallback,
}: {
  value: string;
  onChange: (m: string) => void;
  fallback?: string;
}) {
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  useOutside(ref, () => setOpen(false));

  useEffect(() => {
    getModels().then((r) => setModels(r.models)).catch(() => setModels([]));
  }, [open]);

  const current = value || fallback || "model";

  return (
    <div ref={ref} className="relative">
      <button type="button" className={chip} onClick={() => setOpen((o) => !o)}>
        <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />
        <span className="font-mono">{current}</span>
        <span aria-hidden>▾</span>
      </button>
      {open && (
        <div className={menu}>
          <p className="eyebrow px-3 pb-1 pt-2">Model</p>
          {models.length === 0 && (
            <p className="px-3 py-2 text-[12px] text-[var(--text-dim)]">
              No models found. Run <code>ollama pull qwen2.5:7b</code>.
            </p>
          )}
          {models.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => {
                onChange(m);
                try {
                  localStorage.setItem(MODEL_KEY, m);
                } catch {}
                setOpen(false);
              }}
              className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left font-mono text-[12.5px] text-[var(--text)] hover:bg-[var(--bg-hover)]"
            >
              {m}
              {m === current && <span className="text-[var(--accent)]">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Read the persisted model choice (client only). */
export function storedModel(): string {
  try {
    return localStorage.getItem(MODEL_KEY) || "";
  } catch {
    return "";
  }
}

/** Popover listing app connectors with on/off toggles. */
export function ConnectorsMenu() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Connector[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  useOutside(ref, () => setOpen(false));

  useEffect(() => {
    getConnectors().then((r) => setItems(r.connectors)).catch(() => {});
  }, [open]);

  const active = items.filter((c) => c.enabled && c.configured).length;

  async function toggle(c: Connector) {
    try {
      const r = await setConnector(c.id, !c.enabled);
      setItems(r.connectors);
    } catch {}
  }

  return (
    <div ref={ref} className="relative">
      <button type="button" className={chip} onClick={() => setOpen((o) => !o)}>
        <span aria-hidden>⌁</span>
        Apps{items.length > 0 && <span className="text-[var(--text-dim)]">{active}</span>}
      </button>
      {open && (
        <div className={`${menu} w-80`}>
          <p className="eyebrow px-3 pb-1 pt-2">Connectors</p>
          {items.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => toggle(c)}
              title={c.configured ? c.tools.join(", ") : c.setup_hint}
              className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left hover:bg-[var(--bg-hover)]"
            >
              <span className="min-w-0">
                <span className="block text-[13px] text-[var(--text)]">{c.name}</span>
                <span className="block truncate text-[11px] text-[var(--text-dim)]">
                  {c.configured ? c.description : c.setup_hint || "Not available"}
                </span>
              </span>
              <span
                className={`relative h-4 w-7 shrink-0 rounded-full transition ${
                  c.enabled && c.configured ? "bg-[var(--accent)]" : "bg-[var(--border)]"
                }`}
              >
                <span
                  className={`absolute top-0.5 h-3 w-3 rounded-full bg-[var(--bg)] transition-all ${
                    c.enabled ? "left-3.5" : "left-0.5"
                  }`}
                />
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
