"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  getConversation,
  getStatus,
  notifyConversations,
  sendChat,
  type AgentStatus,
  type ChatMessage,
  type Usage,
} from "@/lib/api";
import { MessageBubble } from "@/components/MessageBubble";
import { StatusPill } from "@/components/StatusPill";
import { ConnectorsMenu, ModelPicker, storedModel } from "@/components/ComposerControls";

export function ChatView() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [lastUsage, setLastUsage] = useState<Usage | null>(null);
  const [title, setTitle] = useState("");
  const router = useRouter();
  const params = useSearchParams();
  const convId = Number(params.get("c")) || null;
  // Id we just created ourselves — skip reloading it from the API.
  const createdRef = useRef<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await getStatus();
      setStatus(s);
      setError(null);
    } catch {
      setStatus(null);
    } finally {
      setStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    setModel(storedModel());
    // Prompt handed over from the first-boot intro.
    try {
      const draft = sessionStorage.getItem("vdx.draft");
      if (draft) {
        sessionStorage.removeItem("vdx.draft");
        setInput(draft);
        textareaRef.current?.focus();
      }
    } catch {}
    void refreshStatus();
    const id = setInterval(refreshStatus, 15_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [refreshStatus]);

  // Load the selected conversation (or reset for a new chat).
  useEffect(() => {
    if (convId !== null && convId === createdRef.current) return;
    createdRef.current = null;
    let alive = true;
    setLastUsage(null);
    setError(null);
    if (convId === null) {
      setMessages([]);
      setTitle("");
      return;
    }
    getConversation(convId)
      .then((c) => {
        if (!alive) return;
        setMessages(c.messages);
        setTitle(c.title);
      })
      .catch((err) => alive && setError(err instanceof Error ? err.message : "Could not load chat"));
    return () => {
      alive = false;
    };
  }, [convId]);

  // ⌘⇧O → new chat
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "o") {
        e.preventDefault();
        router.push("/");
        textareaRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  async function onSubmit(e?: React.FormEvent, override?: string) {
    e?.preventDefault();
    const text = (override ?? input).trim();
    if (!text || busy) return;

    if (override === undefined) setInput("");
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { role: "user", content: text, created_at: new Date().toISOString() }]);

    try {
      const res = await sendChat(text, model, convId);
      setMessages((m) => [...m, { role: "assistant", content: res.reply, created_at: new Date().toISOString() }]);
      setLastUsage(res.usage);
      if (res.conversation_id && res.conversation_id !== convId) {
        createdRef.current = res.conversation_id;
        setTitle(text.slice(0, 60));
        router.replace(`/?c=${res.conversation_id}`);
      }
      notifyConversations();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Request failed";
      setError(msg);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: `⚠️ ${msg}` },
      ]);
    } finally {
      setBusy(false);
      textareaRef.current?.focus();
    }
  }

  /** Re-send the last user prompt, dropping the last exchange from the view. */
  function onRetry() {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    setMessages((m) => m.slice(0, m.lastIndexOf(lastUser)));
    void onSubmit(undefined, lastUser.content);
  }

  /** Download the current chat as a Markdown file. */
  function onExport() {
    const md = [`# ${title || "VDX chat"}`, ""]
      .concat(messages.map((m) => `**${m.role === "user" ? "You" : "VDX"}:**\n\n${m.content}\n`))
      .join("\n");
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(title || "vdx-chat").replace(/[^\w-]+/g, "-").slice(0, 50)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void onSubmit();
    }
  }

  return (
    <div className="relative z-10 flex h-full min-h-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-[var(--border)] px-6">
        <div>
          <h1 className="max-w-[40vw] truncate text-[15px] font-medium tracking-[-0.015em]">
            {title || "New chat"}
          </h1>
          <p className="text-[11px] text-[var(--text-dim)]">
            Local agent · tools on demand
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusPill status={status} loading={statusLoading} />
          {messages.length > 0 && (
            <button
              type="button"
              onClick={onExport}
              className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:text-[var(--text)]"
            >
              Export .md
            </button>
          )}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        {messages.length === 0 && !busy ? (
          <EmptyState onPick={(t) => setInput(t)} />
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-6">
            {messages.map((m, i) => (
              <MessageBubble
                key={`${m.role}-${i}`}
                role={m.role}
                content={m.content}
                createdAt={m.created_at}
                model={m.role === "assistant" ? model || status?.model : undefined}
                onRetry={!busy && i === messages.length - 1 && m.role === "assistant" ? onRetry : undefined}
                onEdit={m.role === "user" ? () => { setInput(m.content); textareaRef.current?.focus(); } : undefined}
              />
            ))}
            {busy && (
              <div className="msg-in flex gap-3">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--bg-panel)] text-[9px] font-bold tracking-[0.06em] text-[var(--accent)]">
                  VDX
                </div>
                <div className="flex items-center gap-2 text-[13px] text-[var(--text-muted)]">
                  <span className="shimmer font-medium">Thinking…</span>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-[var(--border)] px-6 py-4">
        {error && (
          <p className="mb-2 text-[12px] text-[var(--danger)]">{error}</p>
        )}
        <form
          onSubmit={onSubmit}
          className="mx-auto flex max-w-3xl flex-col gap-1 rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-3 shadow-[0_0_0_1px_rgba(255,255,255,0.02)] focus-within:border-[color-mix(in_srgb,var(--accent)_45%,var(--border))]"
        >
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={busy}
            rows={1}
            placeholder="Message VDX Agent…  (Enter to send · Shift+Enter for newline)"
            className="max-h-40 min-h-[44px] w-full resize-none bg-transparent px-2 py-2 text-[14px] text-[var(--text)] outline-none placeholder:text-[var(--text-dim)] disabled:opacity-50"
          />
          <div className="flex items-center gap-1">
            <ModelPicker value={model} onChange={setModel} fallback={status?.model} />
            <ConnectorsMenu />
            <div className="flex-1" />
            {lastUsage && !busy && (
              <span
                className="mr-2 hidden text-[11px] text-[var(--text-dim)] sm:inline"
                title="Last reply: prompt / completion tokens · time · tool calls"
              >
                {lastUsage.prompt_tokens}↑ {lastUsage.completion_tokens}↓ ·{" "}
                {(lastUsage.duration_ms / 1000).toFixed(1)}s
                {lastUsage.tool_calls ? ` · ${lastUsage.tool_calls} tools` : ""}
              </span>
            )}
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="h-9 shrink-0 rounded-xl bg-white px-4 text-[13px] font-semibold text-[var(--bg)] transition hover:bg-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            Send
          </button>
          </div>
        </form>
      </div>

      <style jsx>{`
        .thinking-dots {
          letter-spacing: 1px;
          animation: pulse 1.2s ease-in-out infinite;
        }
        @keyframes pulse {
          0%,
          100% {
            opacity: 0.35;
          }
          50% {
            opacity: 1;
          }
        }
      `}</style>
    </div>
  );
}

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  const hints = [
    "What’s on my calendar today?",
    "Remind me to call Alex at 6pm",
    "Any unread emails?",
    "WhatsApp Marco: running 10 min late",
    "Summarise what I asked earlier",
  ];

  return (
    <div className="msg-in mx-auto flex h-full max-w-lg flex-col items-center justify-center px-4 text-center">
      <div className="wordmark mb-4 text-4xl">VDX</div>
      <p className="mb-8 text-[15px] leading-relaxed text-[var(--text-muted)]">
        Your local macOS agent. Connected to Gmail, Mail, Calendar,
        Reminders, WhatsApp, iMessage, Contacts and Notes — everything stays on this machine.
      </p>
      <div className="cascade grid w-full gap-2 text-left sm:grid-cols-2">
        {hints.map((hint) => (
          <button
            key={hint}
            type="button"
            onClick={() => onPick(hint)}
            className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)]/70 px-3.5 py-3 text-left text-[12.5px] text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:text-[var(--text)]"
          >
            {hint}
          </button>
        ))}
      </div>
    </div>
  );
}
