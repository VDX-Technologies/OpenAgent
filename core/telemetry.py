"""
Core · Telemetry
================
Per-request traces of the agent loop, to see *where the time goes*:

    model load → prompt prefill → token generation → tools → overhead

Each agent request is one row in ``traces`` with its spans stored as JSON.
``report()`` aggregates them into phase breakdowns, throughput percentiles,
per-tool latency and concrete tuning tips.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    return v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))]


class Trace:
    """Collects spans for one agent request (not thread-safe; one per request)."""

    def __init__(self, model: str, source: str, context_messages: int, context_chars: int, tools: int) -> None:
        """Start the wall clock for a request."""
        self.t0 = time.perf_counter()
        self.cpu0 = time.process_time()
        self.model, self.source = model, source
        self.context_messages, self.context_chars, self.tools = context_messages, context_chars, tools
        self.spans: list[dict[str, Any]] = []

    def _at(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)

    def llm(self, start_ms: int, usage: dict[str, Any]) -> None:
        """Record one Ollama call that started at *start_ms* (from :meth:`mark`)."""
        self.spans.append({
            "kind": "llm", "start": start_ms, "ms": self._at() - start_ms,
            **{k: int(usage.get(k) or 0) for k in
               ("load_ms", "prompt_ms", "eval_ms", "prompt_tokens", "completion_tokens", "duration_ms")},
        })

    def tool(self, name: str, start_ms: int, ok: bool) -> None:
        """Record one tool execution."""
        self.spans.append({"kind": "tool", "name": name, "start": start_ms, "ms": self._at() - start_ms, "ok": ok})

    def cpu_ms(self) -> int:
        """CPU time this process spent since the request started (all threads)."""
        return int((time.process_time() - self.cpu0) * 1000)

    def mark(self) -> int:
        """Milliseconds since the request started (use as a span start)."""
        return self._at()

    def summary(self) -> dict[str, Any]:
        """Flatten spans into the phase totals stored on the row."""
        llm = [s for s in self.spans if s["kind"] == "llm"]
        tools = [s for s in self.spans if s["kind"] == "tool"]
        total = self._at()
        out = {
            "total_ms": total,
            "load_ms": sum(s["load_ms"] for s in llm),
            "prompt_ms": sum(s["prompt_ms"] for s in llm),
            "eval_ms": sum(s["eval_ms"] for s in llm),
            "tool_ms": sum(s["ms"] for s in tools),
            "prompt_tokens": sum(s["prompt_tokens"] for s in llm),
            "completion_tokens": sum(s["completion_tokens"] for s in llm),
            "llm_calls": len(llm),
            "tool_calls": len(tools),
            "tool_errors": sum(1 for s in tools if not s["ok"]),
            # Time to the first generated token of the *final* answer is unknown
            # without streaming; first-call prefill end is the best proxy.
            "first_ms": (llm[0]["start"] + llm[0]["load_ms"] + llm[0]["prompt_ms"]) if llm else 0,
        }
        out["overhead_ms"] = max(0, total - out["load_ms"] - out["prompt_ms"] - out["eval_ms"] - out["tool_ms"])
        return out


class TelemetryStore:
    """SQLite persistence + aggregation for :class:`Trace` rows."""

    _COLS = ("total_ms", "load_ms", "prompt_ms", "eval_ms", "tool_ms", "overhead_ms", "first_ms",
             "prompt_tokens", "completion_tokens", "llm_calls", "tool_calls", "tool_errors")

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Create the ``traces`` table if needed (shares the MemoryManager connection)."""
        self._conn = conn
        self._lock = threading.Lock()
        cols = ", ".join(f"{c} INTEGER DEFAULT 0" for c in self._COLS)
        conn.execute(
            f"""CREATE TABLE IF NOT EXISTS traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER,
                model TEXT, source TEXT, ok INTEGER DEFAULT 1,
                context_messages INTEGER, context_chars INTEGER, tools INTEGER,
                {cols}, spans TEXT, created_at TEXT NOT NULL)"""
        )
        conn.commit()

    def save(self, trace: Trace, conversation_id: int | None, ok: bool = True) -> None:
        """Persist a finished trace."""
        row = {
            "conversation_id": conversation_id, "model": trace.model, "source": trace.source, "ok": int(ok),
            "context_messages": trace.context_messages, "context_chars": trace.context_chars, "tools": trace.tools,
            **trace.summary(), "spans": json.dumps(trace.spans), "created_at": _now(),
        }
        with self._lock:
            self._conn.execute(
                f"INSERT INTO traces ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values())
            )
            self._conn.commit()

    def clear(self) -> None:
        """Delete all traces."""
        with self._lock:
            self._conn.execute("DELETE FROM traces")
            self._conn.commit()

    def report(self, days: int = 7, recent: int = 40) -> dict[str, Any]:
        """Aggregate traces from the last *days* days (see module docstring)."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = [dict(r) for r in self._conn.execute(
            "SELECT * FROM traces WHERE created_at >= ? ORDER BY id DESC", (since,))]
        for r in rows:
            r["spans"] = json.loads(r["spans"] or "[]")

        def rate(tok: str, ms: str, rs: list[dict[str, Any]]) -> list[float]:
            return [r[tok] / (r[ms] / 1000) for r in rs if r[ms] > 0 and r[tok] > 0]

        def phases(rs: list[dict[str, Any]]) -> dict[str, int]:
            return {k: sum(r[k] for r in rs) for k in ("load_ms", "prompt_ms", "eval_ms", "tool_ms", "overhead_ms")}

        totals = [r["total_ms"] for r in rows]
        decode, prefill = rate("completion_tokens", "eval_ms", rows), rate("prompt_tokens", "prompt_ms", rows)

        by_model = []
        for m in sorted({r["model"] for r in rows}):
            rs = [r for r in rows if r["model"] == m]
            by_model.append({
                "model": m, "requests": len(rs),
                "p50_ms": _pct([r["total_ms"] for r in rs], 50), "p95_ms": _pct([r["total_ms"] for r in rs], 95),
                "decode_tps": _pct(rate("completion_tokens", "eval_ms", rs), 50),
                "prefill_tps": _pct(rate("prompt_tokens", "prompt_ms", rs), 50),
                "cold_loads": sum(1 for r in rs if r["load_ms"] > 1000),
                "avg_prompt_tokens": sum(r["prompt_tokens"] for r in rs) // max(1, len(rs)),
            })

        tools: dict[str, dict[str, Any]] = {}
        for r in rows:
            for s in r["spans"]:
                if s["kind"] == "tool":
                    t = tools.setdefault(s["name"], {"name": s["name"], "calls": 0, "errors": 0, "ms": []})
                    t["calls"] += 1
                    t["errors"] += 0 if s["ok"] else 1
                    t["ms"].append(s["ms"])
        tool_rows = sorted(
            ({"name": t["name"], "calls": t["calls"], "errors": t["errors"],
              "avg_ms": sum(t["ms"]) // len(t["ms"]), "p95_ms": _pct(t["ms"], 95)} for t in tools.values()),
            key=lambda t: -t["avg_ms"] * t["calls"],
        )

        summary = {
            "requests": len(rows),
            "errors": sum(1 for r in rows if not r["ok"]),
            "p50_ms": _pct(totals, 50), "p95_ms": _pct(totals, 95),
            "first_p50_ms": _pct([r["first_ms"] for r in rows if r["first_ms"]], 50),
            "decode_tps": _pct(decode, 50), "prefill_tps": _pct(prefill, 50),
            "avg_llm_calls": round(sum(r["llm_calls"] for r in rows) / max(1, len(rows)), 2),
            "avg_prompt_tokens": sum(r["prompt_tokens"] for r in rows) // max(1, len(rows)),
            "cold_loads": sum(1 for r in rows if r["load_ms"] > 1000),
        }
        return {
            "days": days, "summary": summary, "phases": phases(rows),
            "by_model": by_model, "tools": tool_rows,
            "recent": rows[:recent], "tips": _tips(summary, phases(rows), tool_rows, rows),
        }


def _tips(s: dict[str, Any], ph: dict[str, int], tools: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Turn the numbers into actionable advice."""
    if not rows:
        return []
    tips: list[dict[str, str]] = []
    total = max(1, sum(ph.values()))
    share = {k: v / total for k, v in ph.items()}

    if s["cold_loads"] and share["load_ms"] > 0.1:
        tips.append({"level": "high", "title": "Model reloads are slowing you down",
                     "body": f"{s['cold_loads']} request(s) waited for the model to load ({share['load_ms']:.0%} of all time). "
                             "Keep it in memory: set OLLAMA_KEEP_ALIVE=-1 (or 1h) and avoid switching models between chats."})
    if share["prompt_ms"] > 0.35 or s["avg_prompt_tokens"] > 4000:
        tips.append({"level": "high" if share["prompt_ms"] > 0.5 else "medium", "title": "Prompts are large",
                     "body": f"Prefill takes {share['prompt_ms']:.0%} of the time (avg {s['avg_prompt_tokens']:,} prompt tokens). "
                             "Disable connectors you don't use (each adds tool schemas), start new chats more often, "
                             "or shorten the history window."})
    if s["decode_tps"] and s["decode_tps"] < 15:
        tips.append({"level": "medium", "title": "Generation is slow",
                     "body": f"Median {s['decode_tps']:.1f} tok/s. A smaller or more quantised model (e.g. a 3B/4B, or q4_K_M) "
                             "will feel much snappier; see Models for picks that fit this Mac."})
    if s["avg_llm_calls"] > 2.5:
        tips.append({"level": "medium", "title": "Many model round-trips per request",
                     "body": f"On average {s['avg_llm_calls']} LLM calls per request. Each tool round re-sends the whole prompt; "
                             "models with stronger tool calling (qwen2.5/qwen3) usually need fewer rounds."})
    slow = [t for t in tools if t["avg_ms"] > 3000]
    if slow:
        tips.append({"level": "medium", "title": f"Slow tool: {slow[0]['name']}",
                     "body": f"Averages {slow[0]['avg_ms'] / 1000:.1f}s per call. AppleScript tools are slow when the app is "
                             "closed — keep Calendar/Mail running, or narrow the query (date range, max results)."})
    if s["requests"] and s["errors"] / s["requests"] > 0.1:
        tips.append({"level": "high", "title": "Frequent errors",
                     "body": f"{s['errors']} of {s['requests']} requests failed. Check data/vdx.log."})
    if share["overhead_ms"] > 0.15:
        tips.append({"level": "low", "title": "Overhead outside the model",
                     "body": f"{share['overhead_ms']:.0%} of the time is spent outside Ollama and tools (HTTP, memory, queueing)."})
    if not tips:
        tips.append({"level": "ok", "title": "Looks healthy", "body": "No obvious bottleneck in this range."})
    return tips
