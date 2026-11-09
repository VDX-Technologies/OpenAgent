"""
Core · Agent Orchestrator
=========================
Ties together the LLM, memory, and tool modules. One loop (:meth:`Agent.run`)
streams the model's answer, runs the tools it asks for (asking the user first
for sensitive ones), feeds results back and repeats until a final answer.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Callable

from core import approvals, connectors
from core.llm import LLMError, OllamaClient
from core.memory import MemoryManager
from core.telemetry import TelemetryStore, Trace
from core.telemetry_share import TelemetryShare

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 15  # coding tasks chain read → edit → commit → push
REPLY_TOKENS = 1024  # context kept free for the model's answer
CHARS_PER_TOKEN = 3.5  # conservative estimate, so the prompt is never cut by Ollama
IMAGE_CHARS = 2000  # rough prompt cost of one image, for fitting the context
SUMMARY_PROMPT = "Summarise what you did and the result."

# approve(approval_id, tool_name, args) -> allowed?
Approver = Callable[[str, str, dict[str, Any]], bool]

SYSTEM_PROMPT = """\
You are VDX OpenAgent — a sharp, capable local assistant for macOS \
(think Jarvis: precise, proactive, no fluff). You run entirely \
on the user's machine via Ollama.

Connected apps right now:
{connectors}

Guidelines:
- Be concise and helpful. Reply in the same language the user writes in.
- When the user asks for an action, CALL the tool yourself right away. \
Never explain to the user how to call a tool or show tool calls as code — you execute them.
- Actions that send, delete or publish something are shown to the user for approval automatically: \
just call the tool. If the user declines, don't retry it.
- Confirm actions clearly after tools succeed. If a tool fails, say what the user can check.
- Never invent calendar/reminder/email data — always call the tool.
- To message someone by name, call find_contact first to get their number/email.
- When the user shares a lasting fact or preference about themselves, save it with remember.
- Coding: list_files/read_file before editing; prefer edit_file for small changes; check git_diff before committing.
- Today is {today}. Each user message starts with the time it was sent, like [09/11 14:05] (day/month).
{facts}
"""


class Agent:
    """Orchestrate LLM ↔ tools ↔ memory for conversation turns."""

    def __init__(self, llm: OllamaClient | None = None, memory: MemoryManager | None = None) -> None:
        self.llm = llm or OllamaClient()
        self.memory = memory or MemoryManager()
        self._tools_now: dict[str, Callable[..., str]] = {}
        self.last_usage: dict[str, Any] = {}
        self.telemetry = TelemetryStore(self.memory._conn)
        self._trace: Trace | None = None
        self.share: TelemetryShare | None = None
        # one run at a time: chat, automations and Discord all take this lock. A plain Lock, not an
        # RLock: a streamed run may be released from another worker thread than the one that took it.
        self.lock = threading.Lock()
        self._cancel = threading.Event()
        self.current: dict[str, Any] | None = None  # {"conversation_id", "source"} of the run in progress
        self.on_state_change: Callable[[str], None] | None = None

    # ── Tools ────────────────────────────────────────────────────────

    def _active_tools(self, exclude: frozenset[str], text: str) -> tuple[dict[str, Callable[..., str]], list[dict[str, Any]]]:
        """Callables + Ollama schemas of the enabled connectors this turn needs."""
        funcs: dict[str, Callable[..., str]] = {}
        schemas: list[dict[str, Any]] = []
        for c in connectors.route(text):
            if c.id in exclude:
                continue
            funcs.update(c.funcs)
            schemas += [
                {"type": "function", "function": {"name": d["name"], "description": d["description"], "parameters": d["parameters"]}}
                for d in c.descriptors
            ]
        return funcs, schemas

    def _set_state(self, state: str) -> None:
        if self.on_state_change:
            try:
                self.on_state_change(state)
            except Exception:
                logger.exception("on_state_change callback failed")

    def _system_message(self) -> dict[str, str]:
        """System prompt: every active app (stable across turns, so Ollama's prompt cache holds) and known facts."""
        active = connectors.active_connectors()
        return {"role": "system", "content": SYSTEM_PROMPT.format(
            connectors="\n".join(f"- {c.name}: {c.description}" for c in active) or "- none",
            today=datetime.now().strftime("%A %Y-%m-%d"),
            facts=self.memory.facts_as_system_prompt(),
        )}

    # ── Text tool-call fallback ──────────────────────────────────────

    @staticmethod
    def _loads(obj: str) -> Any:
        """Parse JSON-ish arguments written by small models (bare keys, single quotes)."""
        fixed = re.sub(r'([{,]\s*)([A-Za-z_]\w*)\s*:', r'\1"\2":', obj)
        candidates = [obj, fixed] + ([fixed.replace("'", '"')] if '"' not in obj else [])
        for cand in candidates:
            try:
                return json.loads(cand)
            except json.JSONDecodeError:
                continue
        return None

    def _extract_text_calls(self, content: str) -> list[dict[str, Any]]:
        """Recover tool calls that weaker models write as text instead of real calls.

        Only when the reply *is* the call: a reply that mentions or proposes a call in a
        sentence ("I could run send_email(...) — shall I?") is left alone.
        """
        if not content or not self._tools_now:
            return []
        text = content.strip()
        if (m := re.fullmatch(r"```[\w-]*\s*(.*?)\s*```", text, re.S)):
            text = m.group(1).strip()
        text = text.strip("`").strip()
        names = "|".join(map(re.escape, sorted(self._tools_now, key=len, reverse=True)))
        call_re = rf"\b({names})\s*\(((?:[^()]|\([^()]*\))*)\)"
        calls: list[dict[str, Any]] = []
        if re.match(call_re, text):
            if re.sub(r"[\s`;,.]", "", re.sub(call_re, "", text)):
                return []  # prose around the call
            for m in re.finditer(call_re, text):
                inner = m.group(2).strip()
                if inner.startswith("{"):
                    args = self._loads(inner)
                else:
                    args = {
                        k: next(v for v in vals if v)
                        for k, *vals in re.findall(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^,\s)]+))', inner)
                    }
                if isinstance(args, dict):
                    calls.append({"function": {"name": m.group(1), "arguments": args}})
        elif text[:1] in "{[":
            obj = self._loads(text)
            for o in obj if isinstance(obj, list) else [obj]:
                if isinstance(o, dict) and o.get("name") in self._tools_now:
                    args = o.get("arguments") or o.get("parameters") or {}
                    calls.append({"function": {"name": o["name"], "arguments": args if isinstance(args, dict) else {}}})
        return calls

    def _resolve_calls(self, reply: dict[str, Any]) -> bool:
        """Ensure *reply* carries tool_calls, salvaging text ones; return True if any."""
        if reply.get("tool_calls"):
            return True
        calls = self._extract_text_calls(reply.get("content") or "")
        if calls:
            logger.info("Recovered %d tool call(s) from text reply", len(calls))
            reply["tool_calls"] = calls
            reply["content"] = ""
        return bool(calls)

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> str:
        fn = self._tools_now.get(name)
        if fn is None:
            return f"Error: unknown tool '{name}'"
        try:
            logger.info("Executing tool %s(%s)", name, arguments)
            result = fn(**arguments)
            result = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
            logger.info("Tool %s result: %s", name, result[:200])
            return result
        except TypeError as exc:
            return f"Error: bad arguments for {name}: {exc}"
        except Exception as exc:
            logger.exception("Tool %s raised", name)
            return f"Error executing {name}: {exc}"

    # ── Context budget ───────────────────────────────────────────────

    def _budget(self, schemas: list[dict[str, Any]] | None) -> int:
        """Characters of messages that fit the model's context next to the tools and the answer."""
        num_ctx = getattr(self.llm, "num_ctx", 8192)
        return int((num_ctx - REPLY_TOKENS) * CHARS_PER_TOKEN) - (len(json.dumps(schemas)) if schemas else 0)

    @staticmethod
    def _size(m: dict[str, Any]) -> int:
        return len(m.get("content") or "") + IMAGE_CHARS * len(m.get("images") or [])

    def _fit(self, messages: list[dict[str, Any]], schemas: list[dict[str, Any]] | None) -> None:
        """Trim *messages* in place to fit the context window (checked before every model call).

        Ollama silently drops the start of a prompt that is too long, which loses the system
        prompt. Instead: old history goes first (down to 75% of the budget, so the trimmed
        prompt stays the same for the next turns and keeps hitting the cache), then the
        biggest tool results of this turn are shortened, then the attached content.
        """
        budget = self._budget(schemas)
        total = sum(map(self._size, messages))
        if total <= budget:
            return
        turn = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=len(messages) - 1)
        while total > budget * 0.75 and turn > 1:
            total -= self._size(messages.pop(1))
            turn -= 1
        while turn > 1 and (messages[1].get("role") == "tool" or messages[1].get("tool_calls")):
            total -= self._size(messages.pop(1))  # no orphaned tool results
            turn -= 1
        for m in sorted((m for m in messages[turn + 1:] if m.get("role") == "tool"), key=self._size, reverse=True):
            if total <= budget:
                break
            size = self._size(m)
            keep = max(800, size - (total - budget))
            if keep < size:
                m["content"] = m["content"][:keep] + "\n…(cut to fit the model's context)"
                total -= size - self._size(m)
        if total > budget:
            last = messages[turn]
            keep = max(budget - (total - self._size(last)), 2000)
            last["content"] = "…(start of the attached content cut to fit the model's context)\n" + last["content"][-keep:]

    # ── Running ──────────────────────────────────────────────────────

    def stop(self, conversation_id: int | None = None) -> bool:
        """Stop the run in progress (only if it belongs to *conversation_id*, when given)."""
        cur = self.current
        if not cur or (conversation_id is not None and cur.get("conversation_id") != conversation_id):
            return False
        self._cancel.set()
        return True

    def _run_tools(self, reply: dict[str, Any], messages: list[dict[str, Any]], source: str,
                   conversation_id: int | None, approve: Approver | None) -> Iterator[dict[str, Any]]:
        """Run each tool call in *reply* (asking approval for sensitive ones), yielding UI events."""
        calls = reply.get("tool_calls") or []
        messages.append({"role": "assistant", "content": reply.get("content") or "", "tool_calls": calls})
        cap = max(2000, self._budget(None) // 3)
        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            raw = fn.get("arguments", {})
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    raw = {}
            args: dict[str, Any] = raw if isinstance(raw, dict) else {}
            yield {"type": "tool", "name": name, "args": args}

            result: str | None = None
            if name in self._tools_now and approvals.needs_approval(name):
                if approve is None:
                    result = (f"Not run: '{approvals.label(name)}' needs the user's approval and nobody can approve it "
                              "right now. Tell the user they can allow it in Settings → Permissions to run it unattended.")
                else:
                    aid = approvals.create(name, args, conversation_id)
                    yield {"type": "approval", "id": aid, "name": name, "label": approvals.label(name), "args": args}
                    allowed = approve(aid, name, args)
                    yield {"type": "approval_done", "id": aid, "allow": allowed}
                    if not allowed:
                        result = "The user declined this action. Don't retry it; ask what they want instead."
            if result is None:
                t0 = self._trace.mark() if self._trace else 0
                result = self._execute_tool(name, args)
                if self._trace:
                    self._trace.tool(name, t0, not result.startswith("Error"))
            ok = not result.startswith(("Error", "Not run", "The user declined"))
            yield {"type": "tool_result", "name": name, "ok": ok, "preview": result[:400]}
            fed = result if len(result) <= cap else result[:cap] + "\n…(truncated — ask for a smaller range if you need more)"
            messages.append({"role": "tool", "content": fed, "tool_name": name})
            self.memory.add_message("tool", f"[{name}] {result[:6000]}", source=source, conversation_id=conversation_id,
                                    extra={"name": name, "args": args, "ok": ok})

    def run(
        self,
        user_message: str,
        source: str = "web",
        model: str | None = None,
        conversation_id: int | None = None,
        context: str = "",
        images: list[str] | None = None,
        think: bool | None = None,
        approve: Approver | None = None,
        reuse_last: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Process one user turn, yielding UI events.

        Events: ``thinking``/``token`` text chunks, ``tool`` (name, args) before a tool runs,
        ``approval`` / ``approval_done`` around a sensitive one, ``tool_result``, and finally
        ``done`` (reply, usage, stopped). Raises :class:`LLMError` when the model fails — the
        error is not stored as a reply. *context* and *images* are stored with the user turn
        and stay available to the model on later turns. With *reuse_last* the user message is
        already stored (regenerate). The caller holds :attr:`lock`.
        """
        self._cancel.clear()
        self.current = {"conversation_id": conversation_id, "source": source}
        self._set_state("thinking")
        if not reuse_last:
            extra = {k: v for k, v in (("context", context), ("images", images)) if v}
            self.memory.add_message("user", user_message, source=source, conversation_id=conversation_id, extra=extra or None)
        history = self.memory.get_context(conversation_id)
        said = " ".join(m["content"].rsplit("\n\n---\n\n", 1)[-1] for m in history if m["role"] == "user")
        exclude = frozenset({"automations"}) if source == "automation" else frozenset()  # a run mustn't schedule more
        self._tools_now, schemas = self._active_tools(exclude, said[-4000:])
        messages = [self._system_message(), *history]
        self._trace = Trace(model or self.llm.model, source, len(messages), sum(map(self._size, messages)), len(schemas))
        stats = self._new_stats()
        partial, thinking, finished = "", "", False
        try:
            for rnd in range(MAX_TOOL_ROUNDS + 1):
                last = rnd == MAX_TOOL_ROUNDS
                self._fit(messages, None if last else schemas)
                msgs = messages + [{"role": "user", "content": SUMMARY_PROMPT}] if last else messages
                reply: dict[str, Any] = {}
                partial = ""
                events = self.llm.chat_events(msgs, tools=None if last else schemas, model=model, think=think)
                try:
                    for kind, val in events:
                        if self._cancel.is_set():
                            break
                        if kind == "token":
                            partial += val
                            yield {"type": "token", "text": val}
                        elif kind == "thinking":
                            thinking += val
                            yield {"type": "thinking", "text": val}
                        else:
                            reply = val
                finally:
                    events.close()  # closes the HTTP stream: Ollama stops generating
                if self._cancel.is_set():
                    finished = True
                    yield self._finish(partial, stats, source, conversation_id, model, thinking, stopped=True)
                    return
                self._add_usage(stats, reply)
                if last or not self._resolve_calls(reply):
                    finished = True
                    yield self._finish(reply.get("content") or "", stats, source, conversation_id, model, thinking)
                    return
                yield {"type": "tool_round", "text": partial}
                partial = ""
                stats["tool_calls"] += len(reply["tool_calls"])
                for ev in self._run_tools(reply, messages, source, conversation_id, approve):
                    yield ev
                if self._cancel.is_set():
                    finished = True
                    yield self._finish("", stats, source, conversation_id, model, thinking, stopped=True)
                    return
        except GeneratorExit:
            # the client went away mid-answer: keep what was written so far
            if not finished and (partial or thinking):
                self._finish(partial, stats, source, conversation_id, model, thinking, stopped=True)
            raise
        except Exception:
            if self._trace:
                self._trace.model = model or self.llm.model
                try:
                    self.telemetry.save(self._trace, conversation_id, ok=False)
                except Exception:
                    logger.exception("Could not record telemetry")
                self._trace = None
            self._set_state("idle")
            raise
        finally:
            self.current = None

    def _finish(self, content: str, stats: dict[str, Any], source: str, conversation_id: int | None,
                model: str | None, thinking: str = "", stopped: bool = False) -> dict[str, Any]:
        """Persist the final reply and usage; return the ``done`` event."""
        name = model or self.llm.model
        if not content.strip() and not stopped:
            content = "Done."
        extra = {k: v for k, v in (("thinking", thinking[-20000:]), ("stopped", stopped)) if v}
        if content or stopped:
            self.memory.add_message("assistant", content, source=source, conversation_id=conversation_id,
                                    model=name, extra=extra or None)
        try:
            self.memory.record_usage(conversation_id=conversation_id, model=name, source=source, **stats)
        except Exception:
            logger.exception("Could not record usage")
        self.last_usage = {**stats, "model": name}
        if self._trace:
            self._trace.model = name
            try:
                self.telemetry.save(self._trace, conversation_id)
            except Exception:
                logger.exception("Could not record telemetry")
            self._share(self._trace)
            self._trace = None
        self._set_state("talking")
        return {"type": "done", "reply": content, "usage": self.last_usage, "stopped": stopped}

    def _share(self, trace: Trace) -> None:
        """Queue anonymous numbers for this request when the user opted in."""
        if not (self.share and self.share.enabled):
            return
        summary, cpu, model = trace.summary(), trace.cpu_ms(), trace.model
        ok = summary["tool_errors"] == 0

        def run() -> None:
            try:
                self.share.record(summary, model, ok, cpu, self.llm.list_models_detailed(), self.llm.running_models())
            except Exception:
                logger.debug("Telemetry share failed", exc_info=True)

        threading.Thread(target=run, daemon=True).start()

    def _add_usage(self, stats: dict[str, Any], reply: dict[str, Any]) -> None:
        """Pop Ollama stats off *reply* and add them to the running totals (and the trace)."""
        u = reply.pop("_usage", None) or {}
        reply.pop("thinking", None)
        if self._trace:
            self._trace.llm(max(0, self._trace.mark() - int(u.get("duration_ms") or 0)), u)
        stats["llm_calls"] += 1
        for k in ("prompt_tokens", "completion_tokens", "duration_ms"):
            stats[k] += int(u.get(k) or 0)

    @staticmethod
    def _new_stats() -> dict[str, Any]:
        return {"prompt_tokens": 0, "completion_tokens": 0, "duration_ms": 0, "tool_calls": 0, "llm_calls": 0}

    def process(self, user_message: str, source: str = "gui", model: str | None = None,
                conversation_id: int | None = None, context: str = "", images: list[str] | None = None,
                approve: Approver | None = None, think: bool | None = None) -> str:
        """Run a turn to completion and return the reply (automations, Discord). Caller holds :attr:`lock`."""
        reply = ""
        for ev in self.run(user_message, source=source, model=model, conversation_id=conversation_id,
                           context=context, images=images, think=think, approve=approve):
            if ev["type"] == "done":
                reply = ev["reply"]
        return reply

    process_stream = run


__all__ = ["Agent", "LLMError"]
