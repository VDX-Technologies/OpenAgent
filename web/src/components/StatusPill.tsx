"use client";

import type { AgentStatus } from "@/lib/api";

export function StatusPill({
  status,
  loading,
}: {
  status: AgentStatus | null;
  loading?: boolean;
}) {
  if (loading && !status) {
    return (
      <span className="rounded-full border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-1 text-[12px] text-[var(--text-dim)]">
        Connecting…
      </span>
    );
  }

  if (!status) {
    return (
      <span className="rounded-full border border-[var(--danger)]/30 bg-[var(--danger)]/10 px-3 py-1 text-[12px] text-[var(--danger)]">
        API offline
      </span>
    );
  }

  const color = status.ollama_online ? "var(--ok)" : "var(--warn)";

  return (
    <span
      className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-1 text-[12px]"
      style={{ color }}
      title={status.base_url}
    >
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: color, boxShadow: `0 0 8px ${color}` }}
      />
      <span className="font-mono tracking-tight">
        {status.model}
      </span>
    </span>
  );
}
