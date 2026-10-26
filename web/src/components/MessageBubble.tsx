"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function useCopy() {
  const [copied, setCopied] = useState(false);
  return {
    copied,
    copy: (text: string) => {
      void navigator.clipboard?.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    },
  };
}

function ActionBtn({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className="rounded-md px-1.5 py-1 text-[12px] text-[var(--text-dim)] transition hover:bg-[var(--bg-hover)] hover:text-[var(--text)]"
    >
      {children}
    </button>
  );
}

/** Code block with language label + copy button. */
function CodeBlock({ children, className }: { children?: React.ReactNode; className?: string }) {
  const { copied, copy } = useCopy();
  const lang = /language-(\w+)/.exec(className || "")?.[1] || "text";
  const text = String(children ?? "").replace(/\n$/, "");
  return (
    <div className="my-3 overflow-hidden rounded-xl border border-[var(--border)] bg-[#0b0c0f]">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-1.5 font-mono text-[11px] text-[var(--text-dim)]">
        <span>{lang}</span>
        <button type="button" onClick={() => copy(text)} className="hover:text-[var(--text)]">
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-3 text-[12.5px] leading-relaxed">
        <code>{text}</code>
      </pre>
    </div>
  );
}

const time = (iso?: string) =>
  iso ? new Date(iso.replace(" ", "T")).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";

/** Open WebUI–style message: user as compact right bubble, assistant as full-width text with hover actions. */
export function MessageBubble({
  role,
  content,
  createdAt,
  model,
  onRetry,
  onEdit,
}: {
  role: "user" | "assistant";
  content: string;
  createdAt?: string;
  model?: string;
  onRetry?: () => void;
  onEdit?: () => void;
}) {
  const { copied, copy } = useCopy();

  if (role === "user") {
    return (
      <div className="msg-in group flex flex-col items-end gap-1">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-3xl rounded-br-lg bg-[var(--bg-hover)] px-4 py-2.5 text-[14.5px] leading-relaxed text-[var(--text)]">
          {content}
        </div>
        <div className="flex items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
          <span className="mr-1 text-[11px] text-[var(--text-dim)]">{time(createdAt)}</span>
          {onEdit && <ActionBtn label="Edit" onClick={onEdit}>✎</ActionBtn>}
          <ActionBtn label="Copy" onClick={() => copy(content)}>{copied ? "✓" : "⧉"}</ActionBtn>
        </div>
      </div>
    );
  }

  return (
    <div className="msg-in group flex gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--bg-panel)] text-[9px] font-bold tracking-[0.06em] text-[var(--accent)]">
        VDX
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-baseline gap-2">
          <span className="text-[13px] font-semibold text-[var(--text)]">VDX</span>
          {model && <span className="font-mono text-[11px] text-[var(--text-dim)]">{model}</span>}
          <span className="text-[11px] text-[var(--text-dim)] opacity-0 transition group-hover:opacity-100">{time(createdAt)}</span>
        </div>
        <div className="prose-vdx text-[14.5px]">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code({ className, children, ...rest }) {
                const block = /language-/.test(className || "") || String(children).includes("\n");
                return block ? (
                  <CodeBlock className={className}>{children}</CodeBlock>
                ) : (
                  <code className="rounded bg-[var(--bg-hover)] px-1.5 py-0.5 font-mono text-[0.88em]" {...rest}>
                    {children}
                  </code>
                );
              },
              pre: ({ children }) => <>{children}</>,
              a: ({ children, href }) => (
                <a href={href} target="_blank" rel="noreferrer" className="text-[var(--accent)] underline-offset-2 hover:underline">
                  {children}
                </a>
              ),
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
        <div className="mt-1 flex items-center gap-0.5 opacity-0 transition group-hover:opacity-100 focus-within:opacity-100">
          <ActionBtn label="Copy" onClick={() => copy(content)}>{copied ? "✓ Copied" : "⧉ Copy"}</ActionBtn>
          {onRetry && <ActionBtn label="Regenerate" onClick={onRetry}>↻ Regenerate</ActionBtn>}
        </div>
      </div>
    </div>
  );
}
