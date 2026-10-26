"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import {
  deleteConversation,
  listConversations,
  updateConversation,
  type Conversation,
} from "@/lib/api";

const NAV = [
  { href: "/", label: "Chat" },
  { href: "/models", label: "Models" },
  { href: "/automations", label: "Automations" },
  { href: "/usage", label: "Usage" },
  { href: "/telemetry", label: "Telemetry" },
  { href: "/settings", label: "Settings" },
];

export function Sidebar() {
  return (
    <aside className="relative z-10 flex w-[260px] shrink-0 flex-col border-r border-[var(--border)] bg-[color-mix(in_srgb,var(--bg-panel)_88%,transparent)] backdrop-blur-md">
      <div className="px-5 pt-6 pb-4">
        <Link href="/" className="group block">
          <div className="wordmark flex items-center gap-2 text-[1.2rem] text-[var(--text)]">
            <img src="/brand/vdx-mark.png" alt="" className="h-6 w-6" />
            VDX
          </div>
          <div className="mt-0.5 text-[11px] uppercase tracking-[0.06em] text-[var(--text-dim)]">
            Agent
          </div>
        </Link>
      </div>
      <Suspense fallback={null}>
        <SidebarBody />
      </Suspense>
    </aside>
  );
}

function SidebarBody() {
  const pathname = usePathname();
  const router = useRouter();
  const params = useSearchParams();
  const activeId = pathname === "/" ? Number(params.get("c")) || null : null;
  const [items, setItems] = useState<Conversation[]>([]);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");

  const load = useCallback(async () => {
    try {
      setItems((await listConversations(query)).conversations);
    } catch {
      /* API offline */
    }
  }, [query]);

  useEffect(() => {
    const t = setTimeout(load, 200);
    window.addEventListener("vdx:conversations", load);
    return () => {
      clearTimeout(t);
      window.removeEventListener("vdx:conversations", load);
    };
  }, [load]);

  async function rename(id: number) {
    const title = draft.trim();
    setEditing(null);
    if (title) await updateConversation(id, { title }).catch(() => {});
    void load();
  }

  async function remove(c: Conversation) {
    if (!confirm(`Delete “${c.title}”?`)) return;
    await deleteConversation(c.id).catch(() => {});
    if (activeId === c.id) router.push("/");
    void load();
  }

  return (
    <>
      <nav className="grid grid-cols-2 gap-1 px-3">
        {NAV.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded-lg px-3 py-2 text-[12.5px] font-medium transition-colors ${
                active
                  ? "bg-[var(--bg-hover)] text-[var(--text)]"
                  : "text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text)]"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-4 flex flex-col gap-2 px-3">
        <button
          type="button"
          onClick={() => router.push("/")}
          title="New chat (⌘⇧O)"
          className="flex items-center justify-between rounded-lg border border-[var(--border)] px-3 py-2 text-[12.5px] text-[var(--text)] transition hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
        >
          <span>+ New chat</span>
          <kbd className="text-[10px] text-[var(--text-dim)]">⌘⇧O</kbd>
        </button>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search chats…"
          className="rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-1.5 text-[12px] text-[var(--text)] outline-none placeholder:text-[var(--text-dim)] focus:border-[var(--border-strong)]"
        />
      </div>

      <div className="mt-2 min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {items.length === 0 && (
          <p className="px-3 py-4 text-[11.5px] text-[var(--text-dim)]">
            {query ? "No matches." : "No chats yet."}
          </p>
        )}
        {items.map((c) => (
          <div
            key={c.id}
            className={`group flex items-center gap-1 rounded-lg px-2.5 py-1.5 transition-colors duration-150 ${
              activeId === c.id ? "bg-[var(--bg-hover)]" : "hover:bg-[var(--bg-hover)]"
            }`}
          >
            {editing === c.id ? (
              <input
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => rename(c.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void rename(c.id);
                  if (e.key === "Escape") setEditing(null);
                }}
                className="min-w-0 flex-1 rounded bg-[var(--bg-elevated)] px-1.5 py-0.5 text-[12.5px] outline-none"
              />
            ) : (
              <Link
                href={`/?c=${c.id}`}
                onDoubleClick={() => { setEditing(c.id); setDraft(c.title); }}
                className={`min-w-0 flex-1 truncate text-[12.5px] ${
                  activeId === c.id ? "text-[var(--text)]" : "text-[var(--text-muted)]"
                }`}
              >
                {c.pinned ? <span className="mr-1 text-[var(--accent)]">●</span> : null}
                {c.title}
              </Link>
            )}
            <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
              <IconBtn label={c.pinned ? "Unpin" : "Pin"} onClick={async () => { await updateConversation(c.id, { pinned: !c.pinned }).catch(() => {}); void load(); }}>
                {c.pinned ? "◉" : "○"}
              </IconBtn>
              <IconBtn label="Rename" onClick={() => { setEditing(c.id); setDraft(c.title); }}>✎</IconBtn>
              <IconBtn label="Delete" onClick={() => remove(c)} danger>✕</IconBtn>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

function IconBtn({ label, onClick, danger, children }: { label: string; onClick: () => void; danger?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className={`flex h-5 w-5 items-center justify-center rounded text-[10.5px] text-[var(--text-dim)] ${
        danger ? "hover:text-[var(--danger)]" : "hover:text-[var(--text)]"
      }`}
    >
      {children}
    </button>
  );
}
