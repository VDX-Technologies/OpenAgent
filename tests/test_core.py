"""Unit tests for the agent loop, memory, automations, settings and the API guard (no Ollama needed)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "")


# ── settings ─────────────────────────────────────────────────────────

def test_env_values_with_backslashes_are_stored_verbatim():
    from config.settings import _upsert_env_key

    for value in (r"pa\1ss", r"ab\gcd", r"tok\\n", "plain"):
        out = _upsert_env_key("A=1\nGMAIL_APP_PASSWORD=old\n", "GMAIL_APP_PASSWORD", value)
        assert f"GMAIL_APP_PASSWORD={value}\n" in out
        assert out.startswith("A=1\n")


# ── memory ───────────────────────────────────────────────────────────

@pytest.fixture()
def mem(tmp_path: Path):
    from core.memory import MemoryManager

    m = MemoryManager(str(tmp_path / "t.db"))
    yield m
    m.close()


def test_history_window_moves_in_blocks_so_the_prompt_prefix_is_stable(mem):
    from core.memory import SHORT_TERM_LIMIT

    cid = mem.create_conversation("x")["id"]
    firsts = []
    for i in range(30):
        mem.add_message("user", f"q{i}", conversation_id=cid)
        mem.add_message("assistant", f"a{i}", conversation_id=cid)
        ctx = mem.get_context(cid)
        assert len([m for m in ctx if m["role"] in ("user", "assistant")]) <= SHORT_TERM_LIMIT
        assert ctx[0]["role"] == "user"
        firsts.append(ctx[0]["content"].split("] ", 1)[1])
    # the start moves once every WINDOW_BLOCK messages (every 5 turns), not on every turn
    # (a sliding window would give 21 different starts over these 30 turns)
    assert len(set(firsts)) <= 6


def test_user_turns_keep_attachments_and_stable_timestamps(mem):
    cid = mem.create_conversation("x")["id"]
    mem.add_message("user", "what is this?", conversation_id=cid, extra={"context": "[Attached web page]\nhello", "images": ["abc"]})
    a, b = mem.get_context(cid), mem.get_context(cid)
    assert a == b
    assert a[0]["content"].startswith("[Attached web page]") and a[0]["content"].rstrip().endswith("what is this?")
    assert a[0]["images"] == ["abc"]


def test_regenerate_and_edit_remove_the_old_turn(mem):
    cid = mem.create_conversation("x")["id"]
    q = mem.add_message("user", "q1", conversation_id=cid)
    mem.add_message("tool", "[web_search] r", conversation_id=cid)
    mem.add_message("assistant", "a1", conversation_id=cid, model="m1")
    mem.delete_after(cid, mem.last_user_message(cid)["id"])
    assert [m["role"] for m in mem.get_conversation_messages(cid, include_tools=True)] == ["user"]
    mem.delete_from(cid, q)
    assert mem.get_conversation_messages(cid) == []


def test_messages_remember_their_model_and_search_uses_content(mem):
    cid = mem.create_conversation("Shopping")["id"]
    mem.add_message("user", "buy oat milk", conversation_id=cid)
    mem.add_message("assistant", "ok", conversation_id=cid, model="qwen2.5:7b")
    assert mem.get_conversation_messages(cid)[1]["model"] == "qwen2.5:7b"
    assert [c["id"] for c in mem.list_conversations("oat")] == [cid]
    assert mem.list_conversations("nothing-like-this") == []


def test_facts_tools(mem):
    from core import memory

    assert memory._remember("partner", "Giulia").startswith("Remembered")
    assert "partner: Giulia" in mem.facts_as_system_prompt()
    assert memory._forget("partner") == "Forgot partner."
    assert mem.facts_as_system_prompt() == ""


def test_notifications_are_persisted_and_marked_read(mem):
    n = mem.add_notification("Briefing", "3 events today", None)
    assert [x["id"] for x in mem.list_notifications(unread=True)] == [n["id"]]
    mem.mark_notifications_read([n["id"]])
    assert mem.list_notifications(unread=True) == []


# ── automations ──────────────────────────────────────────────────────

def test_automation_schedules_are_validated(mem):
    from core.automations import AutomationStore

    store = AutomationStore(mem._conn)
    with pytest.raises(ValueError):
        store.create(name="x", prompt="y", kind="once", run_at="tomorrow at 9")
    with pytest.raises(ValueError):
        store.create(name="x", prompt="y", kind="once")
    with pytest.raises(ValueError):
        store.create(name="x", prompt="y", kind="daily", time="25:00")
    a = store.create(name="x", prompt="y", kind="once", run_at="2030-01-01 09:00")
    assert a["next_run"] == "2030-01-01T09:00:00"
    b = store.create(name="x", prompt="y", kind="daily", time="7.30", weekdays="4,0,0")
    assert (b["time"], b["weekdays"]) == ("07:30", "0,4")


# ── agent ────────────────────────────────────────────────────────────

class FakeLLM:
    """Replays scripted replies; records the messages it was sent."""

    model, num_ctx = "fake", 8192

    def __init__(self, replies: list[dict[str, Any]]):
        self.replies, self.seen = list(replies), []

    def chat_events(self, messages, tools=None, model=None, think=None, temperature=None):
        self.seen.append([dict(m) for m in messages])
        reply = dict(self.replies.pop(0))
        if reply.get("content"):
            yield "token", reply["content"]
        yield "message", {**reply, "_usage": {"prompt_tokens": 1, "completion_tokens": 1}}


def _agent(mem, replies):
    from core.agent import Agent

    return Agent(llm=FakeLLM(replies), memory=mem)  # type: ignore[arg-type]


def test_prose_that_mentions_a_tool_is_not_executed(mem):
    a = _agent(mem, [])
    a._tools_now = {"send_email": lambda **k: "sent", "remember": lambda **k: "ok"}
    assert a._extract_text_calls('I can email him: send_email(to="b@x.com", subject="Hi", body="...") — shall I?') == []
    assert a._extract_text_calls("Next I would call remember({key: 'a'}) if you want.") == []
    ok = a._extract_text_calls('send_email({"to": "a@b.c", "subject": "It\'s done", "body": "don\'t worry"})')
    assert ok and ok[0]["function"]["arguments"]["subject"] == "It's done"
    assert a._extract_text_calls('```json\n{"name": "remember", "arguments": {"key": "k", "value": "v"}}\n```')


def test_sensitive_tools_need_approval_and_unattended_runs_refuse_them(mem, monkeypatch):
    from core import approvals, connectors

    sent: list[Any] = []
    conn = connectors.Connector("t", "T", "test", [{"name": "send_email", "description": "", "parameters": {}}],
                                {"send_email": lambda **k: sent.append(k) or "Email sent"})
    monkeypatch.setattr(connectors, "route", lambda text: [conn])
    monkeypatch.setattr(connectors, "active_connectors", lambda: [conn])
    monkeypatch.setattr(approvals, "always", lambda name: False)
    call = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "send_email", "arguments": {"to": "x"}}}]}

    a = _agent(mem, [call, {"role": "assistant", "content": "I couldn't send it."}])
    assert a.process("email x") == "I couldn't send it."
    assert sent == []  # nobody to approve it

    a = _agent(mem, [call, {"role": "assistant", "content": "Sent!"}])
    events = list(a.run("email x", approve=lambda aid, n, args: True))
    assert [e["type"] for e in events if e["type"].startswith("approval")] == ["approval", "approval_done"]
    assert sent == [{"to": "x"}]


def test_errors_from_the_model_are_raised_not_saved_as_replies(mem):
    from core.llm import LLMError

    class Broken(FakeLLM):
        def chat_events(self, *a, **k):
            raise LLMError("model 'x' not found")
            yield  # pragma: no cover

    from core.agent import Agent

    a = Agent(llm=Broken([]), memory=mem)  # type: ignore[arg-type]
    cid = mem.create_conversation("x")["id"]
    with pytest.raises(LLMError):
        a.process("hi", conversation_id=cid)
    assert [m["role"] for m in mem.get_conversation_messages(cid)] == ["user"]


def test_context_is_fitted_before_every_call_and_keeps_the_system_prompt(mem, monkeypatch):
    from core import connectors

    conn = connectors.Connector("t", "T", "t", [{"name": "read_file", "description": "", "parameters": {}}],
                                {"read_file": lambda **k: "x" * 200_000})
    monkeypatch.setattr(connectors, "route", lambda text: [conn])
    call = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": {}}}]}
    a = _agent(mem, [call, {"role": "assistant", "content": "done"}])
    assert a.process("read it") == "done"
    second = a.llm.seen[1]
    assert second[0]["role"] == "system"
    assert sum(len(m.get("content") or "") for m in second) < a._budget(None)


def test_stop_keeps_the_partial_answer(mem):
    a = _agent(mem, [{"role": "assistant", "content": "partial answer"}])
    cid = mem.create_conversation("x")["id"]
    events = a.run("hi", conversation_id=cid)
    for e in events:
        if e["type"] == "token":
            a.stop(cid)
    msgs = mem.get_conversation_messages(cid)
    assert msgs[-1]["role"] == "assistant" and msgs[-1].get("stopped")


# ── connectors ───────────────────────────────────────────────────────

def test_tool_routing_picks_connectors_by_topic(monkeypatch):
    from config.settings import get_settings
    from core import connectors

    monkeypatch.setattr(get_settings().ollama, "tool_routing", True)
    monkeypatch.setattr(connectors, "active_connectors", lambda: connectors.CONNECTORS)
    ids = {c.id for c in connectors.route("cosa ho in calendario domani?")}
    assert {"calendar", "web", "memory"} <= ids and "github" not in ids
    assert "contacts" in {c.id for c in connectors.route("manda un whatsapp a Marco")}


# ── tools ────────────────────────────────────────────────────────────

def test_search_code_without_matches_is_not_an_error(tmp_path, monkeypatch):
    from config.settings import get_settings
    from tools import code_workspace

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.py").write_text("print('hi')\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    monkeypatch.setattr(get_settings().code, "workspace", str(tmp_path))
    assert code_workspace.search_code("zzz_not_here").startswith("No matches")
    assert "a.py:1" in code_workspace.search_code("print")


def test_text_extraction_and_tts_helpers():
    from core import voice
    from tools.files import extract_text

    assert extract_text("a.md", "# Title\nbody".encode()) == "# Title\nbody"
    assert "binary" in extract_text("x.bin", b"\x00\x01\x02")
    assert voice._guess_language("Ciao, questo è il mio calendario per la settimana che non ho visto") == "it"
    assert voice._plain("**Hi** [link](https://x.y) `code`") == "Hi link code"


# ── API guard ────────────────────────────────────────────────────────

def test_api_refuses_other_sites_and_hosts():
    from fastapi.testclient import TestClient

    from api.server import app

    c = TestClient(app, base_url="http://127.0.0.1:8741")  # no lifespan: no Ollama needed
    assert c.get("/api/health").status_code == 200
    assert c.post("/api/voice/record/start", headers={"origin": "https://evil.example"}).status_code == 403
    assert c.get("/api/health", headers={"host": "evil.example"}).status_code == 403
    assert c.post("/api/update/restart", headers={"sec-fetch-site": "cross-site"}).status_code == 403


# ── app bundle (macOS only) ──────────────────────────────────────────

@pytest.mark.skipif(__import__("sys").platform != "darwin", reason="macOS app bundle")
def test_bundle_is_built_once_then_kept_current(tmp_path, monkeypatch):
    from api import bundle

    monkeypatch.setattr(bundle, "APP", tmp_path / "VDX OpenAgent.app")
    assert bundle.refresh().startswith("skipped")  # nothing installed: never creates one by itself
    assert bundle.refresh(force=True).startswith("updated")
    assert "NSCalendarsFullAccessUsageDescription" in (bundle.APP / "Contents" / "Info.plist").read_text()
    assert bundle.refresh() == "up to date"  # every later start is a no-op
    marker = bundle.APP / "Contents" / "Resources" / bundle.MARKER
    marker.write_text(marker.read_text().replace(str(bundle.ROOT), "/some/other/clone"))
    assert bundle.refresh().startswith("skipped")  # another clone's app is left alone
