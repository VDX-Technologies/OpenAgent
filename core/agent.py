"""
Core · Agent Orchestrator
=========================
Ties together the LLM, memory, and tool modules.
Handles function-calling loops: the model requests a tool,
the agent executes it, feeds the result back, and repeats
until a final natural-language answer is produced.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from collections.abc import Iterator
from typing import Any, Callable

from core.llm import OllamaClient
from core.memory import MemoryManager
from core import connectors
from core.telemetry import TelemetryStore, Trace
from core.telemetry_share import TelemetryShare

logger = logging.getLogger(__name__)

# Maximum tool-call rounds before forcing a text reply
MAX_TOOL_ROUNDS = 15  # coding tasks chain read → edit → commit → push
REPLY_TOKENS = 1024  # context kept free for the model's answer
CHARS_PER_TOKEN = 3.5  # conservative estimate, so the prompt is never cut by Ollama

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
- Confirm actions clearly after tools succeed.
- If a tool fails, apologise and suggest what the user can check.
- Never invent calendar/reminder/email data — always call the tool.
- To message someone by name, call find_contact first to get their number/email.
- Before sending messages or emails on the user's behalf, make sure recipient and text are clear.
- Coding: list_files/read_file before editing; prefer edit_file for small changes; check git_diff before committing; commit and push only when the user asks.
- Today is {today}. The current time is given at the start of the user's latest message.
{facts}
"""


class Agent:
    """Orchestrate LLM ↔ tools ↔ memory for a single conversation turn."""

    def __init__(
        self,
        llm: OllamaClient | None = None,
        memory: MemoryManager | None = None,
    ) -> None:
        """Create the agent with optional injected dependencies."""
        self.llm = llm or OllamaClient()
        self.memory = memory or MemoryManager()
        self._tools_now: dict[str, Callable[..., str]] = {}
        self.last_usage: dict[str, Any] = {}
        self.telemetry = TelemetryStore(self.memory._conn)
        self._trace: Trace | None = None
        self.share: TelemetryShare | None = None

        # Optional callback for UI status (thinking / talking / idle)
        self.on_state_change: Callable[[str], None] | None = None

    # ── Tool registry ────────────────────────────────────────────────

    def _active_tools(self) -> tuple[dict[str, Callable[..., str]], list[dict[str, Any]]]:
        """Return callables + Ollama schemas for currently enabled connectors."""
        funcs: dict[str, Callable[..., str]] = {}
        schemas: list[dict[str, Any]] = []
        for c in connectors.active_connectors():
            funcs.update(c.funcs)
            schemas += [
                {"type": "function", "function": {
                    "name": d["name"], "description": d["description"], "parameters": d["parameters"],
                }}
                for d in c.descriptors
            ]
        return funcs, schemas

    # ── State helper ─────────────────────────────────────────────────

    def _set_state(self, state: str) -> None:
        """Notify listeners (e.g. the GUI) of an animation state change."""
        if self.on_state_change:
            try:
                self.on_state_change(state)
            except Exception:
                logger.exception("on_state_change callback failed")

    # ── System prompt ────────────────────────────────────────────────

    def _system_message(self) -> dict[str, str]:
        """Build the system prompt with current time and known facts."""
        facts = self.memory.facts_as_system_prompt()
        active = connectors.active_connectors()
        content = SYSTEM_PROMPT.format(
            connectors="\n".join(f"- {c.name}: {c.description}" for c in active) or "- none",
            # date only: a prompt that changes every minute defeats Ollama's prompt cache
            today=datetime.now().strftime("%A %Y-%m-%d"),
            facts=facts,
        )
        return {"role": "system", "content": content}

    # ── Text tool-call fallback ──────────────────────────────────────

    def _extract_text_calls(self, content: str) -> list[dict[str, Any]]:
        """Recover tool calls that weaker models write as text instead of real calls.

        Handles ``name({...})``, ``name(key="v", ...)`` and
        ``{"name": ..., "arguments": {...}}`` forms for known tool names.
        """
        if not content or not self._tools_now:
            return []
        calls: list[dict[str, Any]] = []
        decoder = json.JSONDecoder()

        def loads(obj: str) -> dict[str, Any] | None:
            # Quote bare JS-style keys: {title: "x"} → {"title": "x"}
            fixed = re.sub(r'([{,]\s*)([A-Za-z_]\w*)\s*:', r'\1"\2":', obj).replace("'", '"')
            try:
                val, _ = decoder.raw_decode(fixed)
                return val if isinstance(val, dict) else None
            except json.JSONDecodeError:
                return None

        names = "|".join(map(re.escape, sorted(self._tools_now, key=len, reverse=True)))
        for m in re.finditer(rf"\b({names})\s*\(", content):
            rest = content[m.end():].lstrip()
            if rest.startswith("{"):
                args = loads(rest)
            else:
                body = rest.split(")", 1)[0]
                args = {k: v1 or v2 for k, v1, v2 in re.findall(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', body)}
            if args is not None:
                calls.append({"function": {"name": m.group(1), "arguments": args}})
        if not calls:
            for m in re.finditer(r'\{\s*"name"\s*:', content):
                obj = loads(content[m.start():])
                if obj and obj.get("name") in self._tools_now:
                    args = obj.get("arguments") or obj.get("parameters") or {}
                    calls.append({"function": {"name": obj["name"], "arguments": args}})
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

    # ── Tool execution ───────────────────────────────────────────────

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Look up and run a registered tool, returning its result string."""
        fn = self._tools_now.get(name)
        if fn is None:
            return f"Error: unknown tool '{name}'"
        try:
            logger.info("Executing tool %s(%s)", name, arguments)
            result = fn(**arguments)
            logger.info("Tool %s result: %s", name, result[:200])
            return result
        except TypeError as exc:
            return f"Error: bad arguments for {name}: {exc}"
        except Exception as exc:
            logger.exception("Tool %s raised", name)
            return f"Error executing {name}: {exc}"

    # ── Main entry points ────────────────────────────────────────────

    def _begin(
        self, user_message: str, source: str, conversation_id: int | None,
        context: str = "", images: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Persist the user turn and build the initial message list + tool schemas.

        *context* (attached pages / chats) and *images* (base64) are given to the
        model with this turn only; the stored message keeps just the user's text.
        """
        self._set_state("thinking")
        self.memory.add_message("user", user_message, source=source, conversation_id=conversation_id)
        self._tools_now, schemas = self._active_tools()
        messages = [self._system_message(), *self.memory.get_context(conversation_id)]
        if messages[-1].get("role") == "user":
            turn = {**messages[-1], "content": f"[{datetime.now():%H:%M}] {messages[-1]['content']}"}
            if context:
                turn["content"] = f"{context}\n\n---\n\n{turn['content']}"
            if images:
                turn["images"] = images
            messages[-1] = turn
        self._fit(messages, schemas)
        self._trace = Trace(self.llm.model, source, len(messages), sum(len(m.get("content") or "") for m in messages), len(schemas))
        return messages, schemas

    def _fit(self, messages: list[dict[str, Any]], schemas: list[dict[str, Any]]) -> None:
        """Trim *messages* in place to fit the model's context window.

        Ollama silently drops the start of a prompt that is too long, which loses the
        system prompt. Instead the oldest history goes first, then the start of the
        current turn (its attached pages/chats) is shortened.
        """
        num_ctx = getattr(self.llm, "num_ctx", 8192)
        budget = int((num_ctx - REPLY_TOKENS) * CHARS_PER_TOKEN) - len(json.dumps(schemas))
        size = lambda m: len(m.get("content") or "")  # noqa: E731
        total = sum(map(size, messages))
        while total > budget and len(messages) > 2:
            total -= size(messages.pop(1))
        while len(messages) > 2 and messages[1].get("role") == "tool":  # no orphaned tool results
            total -= size(messages.pop(1))
        if total > budget:
            last = messages[-1]
            keep = max(budget - (total - size(last)), 2000)
            last["content"] = "…(start of the attached content cut to fit the model's context)\n" + last["content"][-keep:]

    def _handle_tools(self, reply: dict[str, Any], messages: list[dict[str, Any]], source: str, conversation_id: int | None) -> int:
        """Run every tool call in *reply*, appending results; return how many ran."""
        messages.append(reply)
        calls = reply.get("tool_calls") or []
        for call in calls:
            fn_info = call.get("function", {})
            name = fn_info.get("name", "")
            raw_args = fn_info.get("arguments", {})
            # Ollama may return arguments as a JSON string or a dict
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    args = {}
            else:
                args = raw_args or {}

            t0 = self._trace.mark() if self._trace else 0
            result = self._execute_tool(name, args)
            if self._trace:
                self._trace.tool(name, t0, not result.startswith("Error"))
            messages.append({"role": "tool", "content": result})
            # Also persist tool results lightly in memory
            self.memory.add_message("tool", f"[{name}] {result}", source=source, conversation_id=conversation_id)
        return len(calls)

    def _finish(self, content: str, stats: dict[str, Any], source: str, conversation_id: int | None, model: str | None) -> str:
        """Persist the final reply and the request's usage stats."""
        self.memory.add_message("assistant", content, source=source, conversation_id=conversation_id)
        try:
            self.memory.record_usage(
                conversation_id=conversation_id,
                model=model or self.llm.model,
                source=source,
                **stats,
            )
        except Exception:
            logger.exception("Could not record usage")
        self.last_usage = {**stats, "model": model or self.llm.model}
        if self._trace:
            self._trace.model = model or self.llm.model
            try:
                self.telemetry.save(self._trace, conversation_id)
            except Exception:
                logger.exception("Could not record telemetry")
            self._share(self._trace)
            self._trace = None
        self._set_state("talking")
        return content

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
        if self._trace:
            self._trace.llm(max(0, self._trace.mark() - int(u.get("duration_ms") or 0)), u)
        stats["llm_calls"] += 1
        for k in ("prompt_tokens", "completion_tokens", "duration_ms"):
            stats[k] += int(u.get(k) or 0)

    @staticmethod
    def _new_stats() -> dict[str, Any]:
        return {"prompt_tokens": 0, "completion_tokens": 0, "duration_ms": 0, "tool_calls": 0, "llm_calls": 0}

    def process(
        self,
        user_message: str,
        source: str = "gui",
        model: str | None = None,
        conversation_id: int | None = None,
        context: str = "",
        images: list[str] | None = None,
    ) -> str:
        """Process a user message synchronously (web/GUI path).

        Runs the tool-calling loop and returns the final assistant reply.
        Token usage of the whole request is stored in ``self.last_usage``.
        """
        messages, schemas = self._begin(user_message, source, conversation_id, context, images)
        stats = self._new_stats()

        for _round in range(MAX_TOOL_ROUNDS):
            reply = self.llm.chat(messages, tools=schemas, model=model)
            self._add_usage(stats, reply)
            if not self._resolve_calls(reply):
                return self._finish(reply.get("content") or "", stats, source, conversation_id, model)
            stats["tool_calls"] += self._handle_tools(reply, messages, source, conversation_id)

        # Safety: too many rounds — ask for a plain text wrap-up
        final = self.llm.chat(
            messages + [{"role": "user", "content": "Please summarise the result."}],
            model=model,
        )
        self._add_usage(stats, final)
        return self._finish(final.get("content") or "Done.", stats, source, conversation_id, model)

    async def aprocess(
        self,
        user_message: str,
        source: str = "discord",
        model: str | None = None,
        conversation_id: int | None = None,
    ) -> str:
        """Async variant of :meth:`process` for the Discord bot path."""
        messages, schemas = self._begin(user_message, source, conversation_id)
        stats = self._new_stats()

        for _round in range(MAX_TOOL_ROUNDS):
            reply = await self.llm.achat(messages, tools=schemas, model=model)
            self._add_usage(stats, reply)
            if not self._resolve_calls(reply):
                return self._finish(reply.get("content") or "", stats, source, conversation_id, model)
            stats["tool_calls"] += self._handle_tools(reply, messages, source, conversation_id)

        final = await self.llm.achat(
            messages + [{"role": "user", "content": "Please summarise the result."}],
            model=model,
        )
        self._add_usage(stats, final)
        return self._finish(final.get("content") or "Done.", stats, source, conversation_id, model)

    def process_stream(
        self,
        user_message: str,
        source: str = "web",
        model: str | None = None,
        conversation_id: int | None = None,
        context: str = "",
        images: list[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Like :meth:`process`, but yields UI events as they happen.

        Events: ``{"type": "token", "text"}`` while the model writes,
        ``{"type": "tool", "name"}`` before each tool round (any streamed
        text so far is discarded by the UI), and finally
        ``{"type": "done", "reply", "usage"}``.
        """
        messages, schemas = self._begin(user_message, source, conversation_id, context, images)
        stats = self._new_stats()
        for _round in range(MAX_TOOL_ROUNDS + 1):
            last = _round == MAX_TOOL_ROUNDS
            msgs = messages + [{"role": "user", "content": "Please summarise the result."}] if last else messages
            reply: dict[str, Any] = {}
            for kind, val in self.llm.chat_events(msgs, tools=None if last else schemas, model=model):
                if kind == "token":
                    yield {"type": "token", "text": val}
                else:
                    reply = val
            self._add_usage(stats, reply)
            if last or not self._resolve_calls(reply):
                content = self._finish(reply.get("content") or "Done.", stats, source, conversation_id, model)
                yield {"type": "done", "reply": content, "usage": self.last_usage}
                return
            for call in reply["tool_calls"]:
                yield {"type": "tool", "name": call.get("function", {}).get("name", "")}
            stats["tool_calls"] += self._handle_tools(reply, messages, source, conversation_id)
