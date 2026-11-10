"""
VDX OpenAgent · FastAPI Server
==============================
HTTP API consumed by the SvelteKit frontend (ui/). Exposes chat, memory,
automations, models, voice and settings endpoints, plus a Server-Sent Events
stream for live notifications. Optionally starts the Discord bot.

Only this Mac can talk to it: requests must target localhost (no DNS
rebinding) and come from the app itself, not from a web page that happens to
be open in the browser.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import re
import queue
import threading
from collections import deque
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api import __version__, updater
from config.settings import get_settings, reload_settings, save_settings_to_env
from core import approvals, automations, connectors, hardware, mcp, voice
from core.agent import Agent
from core.llm import LLMError, OllamaClient
from core.memory import NOTE_RE, MemoryManager
from core.telemetry_share import TelemetryShare
from tools import files, phone, web

logger = logging.getLogger(__name__)

llm: OllamaClient | None = None
memory: MemoryManager | None = None
agent: Agent | None = None
scheduler: automations.Scheduler | None = None
share: TelemetryShare | None = None

# ── Live events (SSE) ────────────────────────────────────────────────

_events: deque[tuple[int, dict[str, Any]]] = deque(maxlen=200)
_events_lock = threading.Lock()
_event_seq = 0


def publish(kind: str, **data: Any) -> None:
    """Send an event to every open UI (``/api/events``)."""
    global _event_seq
    with _events_lock:
        _event_seq += 1
        _events.append((_event_seq, {"type": kind, **data}))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot core services, background workers and the optional Discord bot."""
    global llm, memory, agent, scheduler, share

    logging.basicConfig(level=logging.INFO, format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
                        datefmt="%H:%M:%S")

    llm = OllamaClient()
    memory = MemoryManager()
    agent = Agent(llm=llm, memory=memory)
    share = agent.share = TelemetryShare()
    files._llm = llm
    memory.on_notify.append(lambda n: publish("notification", item=n))

    if llm.is_available():
        logger.info("Ollama online — model: %s", llm.model)
        llm.warm()  # load the model now, not on the first message
    else:
        logger.warning("Ollama offline at %s", llm.base_url)

    mcp.start_all()
    files.reindex_all()
    # keep ~/Applications/VDX OpenAgent.app in step with this code (also covers updates applied by
    # an older updater that had no post-update step); a no-op when it is already current
    from api import bundle

    threading.Thread(target=bundle.refresh, name="vdx-bundle", daemon=True).start()

    settings = get_settings()
    if settings.discord.token:
        from interface.discord_bot import run_discord_bot

        threading.Thread(target=run_discord_bot, args=(agent,), name="discord-bot", daemon=True).start()
        logger.info("Discord bot thread started")

    scheduler = automations.Scheduler(automations.AutomationStore(memory._conn), agent)
    scheduler.on_change = lambda: publish("automations")
    scheduler.start()

    yield

    if scheduler:
        scheduler.stop()
    mcp.stop_all()
    voice.stop_recording(discard=True)
    voice.stop_speaking()
    if share:
        share.stop()
    if memory:
        memory.close()
    logger.info("VDX OpenAgent API shut down")


app = FastAPI(title="VDX OpenAgent API", version=__version__, lifespan=lifespan)

_DEV_ORIGINS = [f"http://{h}:{p}" for h in ("localhost", "127.0.0.1") for p in (3000, 5173)]
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"} | {
    h.strip() for h in os.getenv("VDX_ALLOWED_HOSTS", "").split(",") if h.strip()
}


@app.middleware("http")
async def local_only(request: Request, call_next):
    """Refuse requests a web page could forge: other Host names, or another site's Origin.

    CORS only stops a page from *reading* answers; a cross-site POST without a body still
    reaches the server (start the microphone, run an automation, restart the app…).
    """
    host_header = request.headers.get("host", "")
    host = re.sub(r":\d+$", "", host_header)
    if host and host not in _LOCAL_HOSTS:
        return JSONResponse({"detail": "Forbidden host"}, status_code=403)
    origin = request.headers.get("origin")
    if origin is not None and origin != f"http://{host_header}" and origin not in _DEV_ORIGINS:
        return JSONResponse({"detail": "Forbidden origin"}, status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("sec-fetch-site") == "cross-site":
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    return await call_next(request)


app.add_middleware(CORSMiddleware, allow_origins=_DEV_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ── Request / response models ────────────────────────────────────────

class FilePayload(BaseModel):
    """A file attached to a message (base64 content)."""

    name: str = Field(..., max_length=300)
    data: str = Field(..., max_length=28_000_000)


class ChatRequest(BaseModel):
    """Incoming chat message from the web UI."""

    message: str = Field("", max_length=32_000)
    source: str = "web"
    model: str | None = None
    conversation_id: int | None = None
    images: list[str] = Field(default_factory=list, max_length=4)  # base64 or data: URLs
    urls: list[str] = Field(default_factory=list, max_length=5)  # pages to read with this message
    ref_conversations: list[int] = Field(default_factory=list, max_length=5)  # chats to use as context
    files: list[FilePayload] = Field(default_factory=list, max_length=5)  # documents (PDF, text, code…)
    think: bool | None = None  # reasoning on/off for models that support it (None = setting)
    regenerate: bool = False  # answer the last user message again
    edit_of: int | None = None  # replace this user message (and everything after it) with *message*


class ChatResponse(BaseModel):
    reply: str
    conversation_id: int | None = None
    usage: dict[str, Any] = {}


class ConversationPatch(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class PullRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class StatusResponse(BaseModel):
    ollama_online: bool
    model: str
    base_url: str
    temperature: float
    short_term_messages: int
    facts: int
    gmail_configured: bool
    discord_configured: bool


class SettingsPayload(BaseModel):
    """Editable settings mirrored to `.env` (None = not sent by this client: keep the stored value)."""

    ollama_base_url: str
    ollama_model: str
    ollama_temperature: float = 0.7
    ollama_timeout: int = 120
    gmail_address: str = ""
    gmail_app_password: str = ""
    discord_bot_token: str = ""
    discord_prefix: str = "!"
    discord_allowed_users: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    github_token: str = ""
    code_workspace: str = ""
    ntfy_server: str | None = None
    ntfy_topic: str | None = None
    ollama_think: str | None = None
    tool_routing: bool | None = None
    whisper_model: str | None = None
    whisper_language: str | None = None


class ConnectorToggle(BaseModel):
    enabled: bool


class Decision(BaseModel):
    allow: bool
    always: bool = False


class FactPayload(BaseModel):
    key: str = Field(..., min_length=1, max_length=80)
    value: str = Field(..., min_length=1, max_length=500)


class SpeakPayload(BaseModel):
    text: str = Field(..., max_length=20_000)
    language: str = ""


# ── Helpers ──────────────────────────────────────────────────────────

def _require_agent() -> Agent:
    if agent is None:
        raise HTTPException(503, "Agent not ready")
    return agent


def _attachments(body: ChatRequest, a: Agent) -> tuple[str, list[str], str]:
    """Turn a request's attachments into (model context, images, note for the stored message).

    The note is one ``[chat|page|file|images] value`` line per attachment; the UI shows them as chips.
    """
    parts: list[str] = []
    note: list[str] = []
    for cid in body.ref_conversations:
        conv = a.memory.get_conversation(cid)
        if not conv:
            continue
        lines = [f"{m['role']}: {m['content']}" for m in a.memory.get_conversation_messages(cid)]
        parts.append(f"[Referenced chat \"{conv['title']}\"]\n" + "\n".join(lines)[-8000:])
        note.append(f"[chat] {conv['title']}")
    for url in body.urls:
        parts.append(f"[Attached web page]\n{web.fetch_url(url, max_chars=8000)}")
        note.append(f"[page] {url}")
    for f in body.files:
        raw = f.data.split(",", 1)[1] if f.data.startswith("data:") else f.data
        try:
            data = base64.b64decode(raw, validate=False)
        except (binascii.Error, ValueError):
            continue
        text = files.extract_text(f.name, data)
        parts.append(f"[Attached file \"{f.name}\"]\n{text[:24000]}" + ("\n…(truncated)" if len(text) > 24000 else ""))
        note.append(f"[file] {f.name}")
    images = [i.split(",", 1)[1] if i.startswith("data:") else i for i in body.images]
    if images:
        note.append(f"[images] {len(images)}")
    return "\n\n".join(parts), images, "\n".join(note)


def _busy_label(a: Agent) -> str:
    cur = a.current or {}
    return {"automation": "an automation", "discord": "a Discord request"}.get(cur.get("source", ""), "another chat")


# ── Routes ───────────────────────────────────────────────────────────

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "vdx-agent", "version": __version__}


@app.get("/api/update")
def update_status() -> dict:
    return updater.check()


@app.post("/api/update")
def update_apply() -> dict:
    return updater.apply()


@app.post("/api/update/restart")
def update_restart() -> dict:
    return updater.restart()


@app.get("/api/status", response_model=StatusResponse)
def status() -> StatusResponse:
    a = _require_agent()
    s = get_settings()
    return StatusResponse(
        ollama_online=a.llm.is_available(), model=a.llm.model, base_url=a.llm.base_url,
        temperature=a.llm.temperature, short_term_messages=len(a.memory.get_context()),
        facts=len(a.memory.get_all_facts()), gmail_configured=bool(s.gmail.address and s.gmail.app_password),
        discord_configured=bool(s.discord.token),
    )


@app.get("/api/models")
def list_models() -> dict[str, Any]:
    a = _require_agent()
    names = a.llm.list_models()
    return {"models": names, "thinking": [m for m in names if "thinking" in a.llm.capabilities(m)]}


@app.post("/api/models/warm")
def warm_model(body: PullRequest) -> dict[str, str]:
    """Load a model into memory now (the user just picked it)."""
    _require_agent().llm.warm(body.name)
    return {"status": "loading"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    """Process a user message through the agent (tools + memory), without streaming."""
    a = _require_agent()
    if not body.message.strip():
        raise HTTPException(422, "Empty message")
    context, images, note = _attachments(body, a)
    text = body.message.strip() + (f"\n\n{note}" if note else "")
    cid = body.conversation_id
    if cid is not None and not a.memory.get_conversation(cid):
        raise HTTPException(404, "Conversation not found")
    if cid is None and body.source == "web":
        cid = a.memory.create_conversation(" ".join(body.message.split())[:60] or "New chat")["id"]
    try:
        with a.lock:
            reply = a.process(text, source=body.source, model=body.model or None, conversation_id=cid,
                              context=context, images=images, think=body.think)
            usage = dict(a.last_usage)
    except LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        logger.exception("Chat failed")
        raise HTTPException(500, f"Agent error: {exc}") from exc
    return ChatResponse(reply=reply, conversation_id=cid, usage=usage)


@app.post("/api/chat/stream")
def chat_stream(body: ChatRequest) -> StreamingResponse:
    """Stream a turn as Server-Sent Events (see :meth:`Agent.run` for the event types).

    Also handles ``regenerate`` (answer the last question again) and ``edit_of``
    (replace a user message and everything after it), keeping their attachments.
    """
    a = _require_agent()
    cid = body.conversation_id
    if cid is not None and not a.memory.get_conversation(cid):
        raise HTTPException(404, "Conversation not found")
    reuse, old_extra, old_note = False, {}, ""
    if body.regenerate:
        last = a.memory.last_user_message(cid) if cid is not None else None
        if not last:
            raise HTTPException(400, "Nothing to regenerate")
        text = last["content"]
    else:
        if not body.message.strip():
            raise HTTPException(422, "Empty message")
        if body.edit_of is not None:
            old = a.memory.get_message(body.edit_of)
            if not old or old["conversation_id"] != cid or old["role"] != "user":
                raise HTTPException(404, "Message not found")
            old_extra = old["extra"]
            m = NOTE_RE.search(old["content"])
            old_note = m.group(0).strip() if m else ""
        text = body.message.strip()
    if cid is None and body.source == "web":
        cid = a.memory.create_conversation(" ".join(body.message.split())[:60] or "New chat")["id"]

    def events() -> Iterator[str]:
        nonlocal text
        send = lambda ev: f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"  # noqa: E731
        yield send({"type": "start", "conversation_id": cid})
        shown: set[str] = set()  # approvals of the run ahead shown on this stream
        if not a.lock.acquire(blocking=False):
            yield send({"type": "status", "text": f"Waiting for {_busy_label(a)} to finish…"})
            with _queue_lock:
                _waiting[cid] = _waiting.get(cid, 0) + 1
            try:
                # The run ahead may be blocked on an approval whose card isn't on screen
                # (page reloaded, other chat, quick window closed): show it here too, so
                # the user can answer it instead of watching this one spin.
                while not a.lock.acquire(timeout=0.5):
                    with _queue_lock:
                        stopped = cid in _cancelled
                        _cancelled.discard(cid)
                    if stopped:  # stopped while queued: give up without running
                        for aid in shown:
                            yield send({"type": "approval_done", "id": aid, "allow": False})
                        yield send({"type": "done", "reply": "", "usage": {}, "stopped": True, "conversation_id": cid})
                        return
                    open_ = {p["id"]: p for p in approvals.pending()}
                    for aid in shown - open_.keys():
                        yield send({"type": "approval_done", "id": aid, "allow": False})
                        yield send({"type": "status", "text": f"Waiting for {_busy_label(a)} to finish…"})
                    for aid, p in open_.items():
                        if aid not in shown:
                            yield send({"type": "status", "text": "Another chat is waiting for your approval…"})
                            yield send({"type": "approval", "id": aid, "name": p["name"], "label": p["label"], "args": p["args"]})
                    shown = set(open_)
            finally:
                with _queue_lock:
                    _waiting[cid] -= 1
                    if not _waiting[cid]:
                        del _waiting[cid]
            with _queue_lock:
                cancelled = cid in _cancelled
                _cancelled.discard(cid)
            if cancelled:  # stopped while it was queued: don't run it at all
                a.lock.release()
                yield send({"type": "done", "reply": "", "usage": {}, "stopped": True, "conversation_id": cid})
                return
        for aid in shown:  # the run ahead is done: drop its cards from this stream
            yield send({"type": "approval_done", "id": aid, "allow": False})

        # The turn runs in its own thread and this stream only relays its events: if the
        # page goes away (reload, other chat, quick window closed) the turn still finishes
        # and frees the agent, instead of staying parked on an unsent event forever.
        out: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def work() -> None:
            nonlocal text
            try:
                context, images = "", []
                if body.regenerate:
                    a.memory.delete_after(cid, last["id"])
                else:
                    if body.urls or body.files or body.ref_conversations:
                        out.put({"type": "status", "text": "Reading attachments…"})
                    context, images, note = _attachments(body, a)
                    context = "\n\n".join(p for p in (old_extra.get("context", ""), context) if p)
                    images = (old_extra.get("images") or []) + images
                    note = "\n".join(p for p in (old_note, note) if p)
                    text = text + (f"\n\n{note}" if note else "")
                    if body.edit_of is not None:
                        a.memory.delete_from(cid, body.edit_of)
                for ev in a.run(text, source=body.source, model=body.model or None, conversation_id=cid,
                                context=context, images=images[:8], think=body.think, reuse_last=body.regenerate,
                                approve=lambda aid, _n, _a: approvals.wait(aid, a._cancel)):
                    if ev["type"] == "done":
                        ev["conversation_id"] = cid
                    out.put(ev)
            except LLMError as exc:
                out.put({"type": "error", "detail": str(exc)})
            except Exception as exc:
                logger.exception("Stream failed")
                out.put({"type": "error", "detail": f"Agent error: {exc}"})
            finally:
                a.lock.release()
                out.put(None)

        threading.Thread(target=work, name=f"chat-{cid}", daemon=True).start()
        while (ev := out.get()) is not None:
            yield send(ev)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


class StopPayload(BaseModel):
    conversation_id: int | None = None


_queue_lock = threading.Lock()
_waiting: dict[int | None, int] = {}  # conversations with a run queued behind another one
_cancelled: set[int | None] = set()


@app.post("/api/chat/stop")
def chat_stop(body: StopPayload) -> dict[str, bool]:
    """Stop the answer being generated (what was written so far is kept), or a queued one."""
    with _queue_lock:
        if body.conversation_id in _waiting:
            _cancelled.add(body.conversation_id)
            return {"stopped": True}
    return {"stopped": _require_agent().stop(body.conversation_id)}


@app.get("/api/chat/active")
def chat_active() -> dict[str, Any]:
    """The run in progress, if any (conversation and source)."""
    return {"active": _require_agent().current}


# ── Approvals & permissions ──────────────────────────────────────────

@app.get("/api/approvals")
def list_approvals(conversation_id: int | None = None) -> dict[str, Any]:
    return {"approvals": approvals.pending(conversation_id)}


@app.post("/api/approvals/{aid}")
def decide(aid: str, body: Decision) -> dict[str, bool]:
    """Allow or deny a pending action (``always`` = don't ask again for this tool)."""
    if not approvals.resolve(aid, body.allow, body.always):
        raise HTTPException(404, "This request already expired")
    return {"ok": True}


@app.get("/api/permissions")
def permissions() -> dict[str, Any]:
    return {"permissions": approvals.policy()}


@app.put("/api/permissions/{tool}")
def set_permission(tool: str, body: ConnectorToggle) -> dict[str, Any]:
    if not approvals.is_sensitive(tool):
        raise HTTPException(404, "Unknown action")
    approvals.set_always(tool, body.enabled)
    return {"permissions": approvals.policy()}


# ── Conversations ────────────────────────────────────────────────────

@app.get("/api/conversations")
def list_conversations(q: str | None = None, limit: int = 300) -> dict[str, Any]:
    """List chats (pinned first), optionally filtered by title/content."""
    return {"conversations": _require_agent().memory.list_conversations(query=q or "", limit=max(1, min(limit, 5000)))}


@app.post("/api/conversations")
def create_conversation() -> dict[str, Any]:
    return _require_agent().memory.create_conversation("New chat")


@app.get("/api/conversations/{cid}")
def get_conversation(cid: int, steps: bool = False) -> dict[str, Any]:
    """A chat with its messages (and tool steps with ``steps=1``)."""
    m = _require_agent().memory
    conv = m.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return {**conv, "messages": m.get_conversation_messages(cid, include_tools=steps)}


@app.patch("/api/conversations/{cid}")
def patch_conversation(cid: int, body: ConversationPatch) -> dict[str, Any]:
    m = _require_agent().memory
    if not m.get_conversation(cid):
        raise HTTPException(404, "Conversation not found")
    m.update_conversation(cid, title=body.title, pinned=body.pinned)
    return m.get_conversation(cid)  # type: ignore[return-value]


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: int) -> dict[str, str]:
    _require_agent().memory.delete_conversation(cid)
    return {"status": "deleted"}


# ── Memory (facts) & local files ─────────────────────────────────────

@app.get("/api/memory")
def list_memory() -> dict[str, Any]:
    return {"facts": _require_agent().memory.list_facts()}


@app.put("/api/memory")
def put_memory(body: FactPayload) -> dict[str, Any]:
    m = _require_agent().memory
    m.set_fact(body.key, body.value)
    return {"facts": m.list_facts()}


@app.delete("/api/memory/{key:path}")
def delete_memory(key: str) -> dict[str, Any]:
    m = _require_agent().memory
    m.delete_fact(key)
    return {"facts": m.list_facts()}


class FolderPayload(BaseModel):
    path: str = Field(..., min_length=1, max_length=1000)


@app.get("/api/knowledge")
def knowledge() -> dict[str, Any]:
    return files.folders()


@app.post("/api/knowledge")
def knowledge_add(body: FolderPayload) -> dict[str, Any]:
    msg = files.add_folder(body.path)
    if msg.startswith("Error"):
        raise HTTPException(400, msg[7:])
    return files.folders()


@app.delete("/api/knowledge")
def knowledge_remove(path: str) -> dict[str, Any]:
    files.remove_folder(path)
    return files.folders()


# ── MCP servers ──────────────────────────────────────────────────────

class MCPPayload(BaseModel):
    config: str = Field(..., max_length=100_000)


@app.get("/api/mcp")
def mcp_get() -> dict[str, Any]:
    return {"config": mcp.read_config(), "servers": mcp.status()}


@app.put("/api/mcp")
def mcp_put(body: MCPPayload) -> dict[str, Any]:
    try:
        mcp.write_config(body.config)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid JSON: {exc}") from exc
    mcp.start_all()
    return {"config": mcp.read_config(), "servers": mcp.status()}


# ── Usage, notifications & system ────────────────────────────────────

@app.get("/api/telemetry")
def telemetry(days: int = 7) -> dict[str, Any]:
    a = _require_agent()
    report = a.telemetry.report(days=max(1, min(days, 365)))
    report["loaded"] = a.llm.running_models()
    report["default_model"] = a.llm.model
    return report


class ConsentPayload(BaseModel):
    allow: bool


def _require_share() -> TelemetryShare:
    if share is None:
        raise HTTPException(503, "Telemetry not ready")
    return share


@app.get("/api/telemetry/consent")
def telemetry_consent() -> dict[str, Any]:
    s = _require_share()
    return {**s.status(), "preview": s.install()}


@app.put("/api/telemetry/consent")
def telemetry_consent_set(body: ConsentPayload) -> dict[str, Any]:
    return _require_share().set_consent(body.allow)


@app.delete("/api/telemetry")
def telemetry_clear() -> dict[str, bool]:
    _require_agent().telemetry.clear()
    return {"ok": True}


@app.get("/api/usage")
def usage(days: int = 30) -> dict[str, Any]:
    return _require_agent().memory.usage_report(days=max(1, min(days, 365)))


@app.get("/api/notifications")
def notifications(after: int = 0, unread: bool = False) -> dict[str, Any]:
    """Notifications (automation results) newer than *after*, or the unread ones."""
    return {"items": _require_agent().memory.list_notifications(after=after, unread=unread)}


class ReadPayload(BaseModel):
    ids: list[int] | None = None


@app.post("/api/notifications/read")
def notifications_read(body: ReadPayload) -> dict[str, bool]:
    _require_agent().memory.mark_notifications_read(body.ids)
    publish("notifications_read")
    return {"ok": True}


@app.get("/api/events")
async def live_events(request: Request) -> StreamingResponse:
    """Server-Sent Events: notifications and automation changes as they happen (replaces polling)."""

    async def gen():
        with _events_lock:
            last = _event_seq
        yield "retry: 3000\n\n"
        idle = 0.0
        while not await request.is_disconnected():
            with _events_lock:
                fresh = [(s, e) for s, e in _events if s > last]
            for s, e in fresh:
                last = s
                yield f"data: {json.dumps(e, ensure_ascii=False, default=str)}\n\n"
            idle = 0.0 if fresh else idle + 0.5
            if idle >= 15:
                idle = 0.0
                yield ": ping\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/system")
def system_info() -> dict[str, Any]:
    a = _require_agent()
    profile = hardware.system_profile()
    try:
        installed = a.llm.list_models()
    except Exception:
        installed = []
    return {"profile": profile, "recommendations": hardware.recommend(profile, installed)}


# ── Model management ─────────────────────────────────────────────────

_pulls: dict[str, dict[str, Any]] = {}


@app.get("/api/models/detailed")
def models_detailed() -> dict[str, Any]:
    a = _require_agent()
    try:
        return {"models": a.llm.list_models_detailed(), "running": a.llm.running_models()}
    except Exception as exc:
        raise HTTPException(502, f"Ollama unreachable: {exc}") from exc


@app.post("/api/models/pull")
def pull_model(body: PullRequest) -> dict[str, Any]:
    """Start downloading a model in the background; poll /api/models/pulls."""
    a = _require_agent()
    name = body.name.strip()
    if _pulls.get(name, {}).get("state") == "pulling":
        return _pulls[name]
    _pulls[name] = {"name": name, "state": "pulling", "status": "starting", "completed": 0, "total": 0}

    def progress(status: str, completed: int, total: int) -> None:
        _pulls[name].update(status=status, completed=completed or 0, total=total or 0)

    def run() -> None:
        try:
            a.llm.pull_model(name, on_progress=progress)
            _pulls[name].update(state="done", status="success")
        except Exception as exc:
            _pulls[name].update(state="error", status=str(exc))

    threading.Thread(target=run, name=f"pull-{name}", daemon=True).start()
    return _pulls[name]


@app.get("/api/models/pulls")
def pull_status() -> dict[str, Any]:
    return {"pulls": list(_pulls.values())}


@app.delete("/api/models/{name:path}")
def delete_model(name: str) -> dict[str, str]:
    try:
        _require_agent().llm.delete_model(name)
    except Exception as exc:
        raise HTTPException(502, f"Delete failed: {exc}") from exc
    _pulls.pop(name, None)
    return {"status": "deleted"}


@app.get("/api/connectors")
def list_connectors() -> dict[str, Any]:
    return {"connectors": connectors.describe()}


@app.put("/api/connectors/{cid}")
def toggle_connector(cid: str, body: ConnectorToggle) -> dict[str, Any]:
    try:
        connectors.set_enabled(cid, body.enabled)
    except KeyError:
        raise HTTPException(404, f"Unknown connector '{cid}'") from None
    return {"connectors": connectors.describe()}


@app.get("/api/history")
def history(limit: int = 50, source: str | None = "web") -> dict[str, Any]:
    msgs = _require_agent().memory.get_history(limit=limit, source=source)
    return {"messages": [{"role": m["role"], "content": m["content"], "created_at": m.get("created_at")}
                         for m in msgs if m["role"] in ("user", "assistant")]}


@app.post("/api/chat/clear")
def clear_chat() -> dict[str, str]:
    _require_agent().memory.clear_short_term()
    return {"status": "cleared"}


@app.get("/api/settings")
def get_settings_api() -> SettingsPayload:
    """Current settings (secrets included — local-only app)."""
    s = get_settings()
    return SettingsPayload(
        ollama_base_url=s.ollama.base_url, ollama_model=s.ollama.model, ollama_temperature=s.ollama.temperature,
        ollama_timeout=s.ollama.timeout, gmail_address=s.gmail.address, gmail_app_password=s.gmail.app_password,
        discord_bot_token=s.discord.token, discord_prefix=s.discord.command_prefix,
        discord_allowed_users=",".join(str(u) for u in s.discord.allowed_user_ids),
        whatsapp_token=s.whatsapp.token, whatsapp_phone_id=s.whatsapp.phone_id, github_token=s.github.token,
        code_workspace=s.code.workspace, ntfy_server=s.phone.ntfy_server, ntfy_topic=s.phone.ntfy_topic,
        ollama_think=s.ollama.think, tool_routing=s.ollama.tool_routing, whisper_model=s.voice.whisper_model,
        whisper_language=s.voice.language,
    )


@app.put("/api/settings")
def put_settings(body: SettingsPayload) -> dict[str, str]:
    """Persist settings to `.env` and hot-reload the Ollama client."""
    a = _require_agent()
    old_model = a.llm.model
    updates = {
        "OLLAMA_BASE_URL": body.ollama_base_url.strip(), "OLLAMA_MODEL": body.ollama_model.strip(),
        "OLLAMA_TEMPERATURE": str(body.ollama_temperature), "OLLAMA_TIMEOUT": str(body.ollama_timeout),
        "GMAIL_ADDRESS": body.gmail_address.strip(), "GMAIL_APP_PASSWORD": body.gmail_app_password.strip(),
        "DISCORD_BOT_TOKEN": body.discord_bot_token.strip(), "DISCORD_PREFIX": body.discord_prefix.strip() or "!",
        "DISCORD_ALLOWED_USERS": body.discord_allowed_users.strip(), "WHATSAPP_TOKEN": body.whatsapp_token.strip(),
        "WHATSAPP_PHONE_ID": body.whatsapp_phone_id.strip(), "GITHUB_TOKEN": body.github_token.strip(),
        "CODE_WORKSPACE": body.code_workspace.strip(),
    }
    optional = {
        "NTFY_SERVER": (body.ntfy_server, lambda v: v.strip() or "https://ntfy.sh"),
        "NTFY_TOPIC": (body.ntfy_topic, str.strip),
        "OLLAMA_THINK": (body.ollama_think, lambda v: v if v in ("on", "off") else "off"),
        "TOOL_ROUTING": (body.tool_routing, lambda v: "1" if v else "0"),
        "WHISPER_MODEL": (body.whisper_model, lambda v: v.strip() or "small"),
        "WHISPER_LANGUAGE": (body.whisper_language, lambda v: v.strip().lower()[:5]),
    }
    for key, (value, norm) in optional.items():
        if value is not None:
            updates[key] = norm(value)  # type: ignore[operator]
    if not updates["OLLAMA_BASE_URL"] or not updates["OLLAMA_MODEL"]:
        raise HTTPException(400, "Ollama URL and model are required")
    try:
        path = save_settings_to_env(updates)
        settings = reload_settings()
        a.llm.apply_config(base_url=settings.ollama.base_url, model=settings.ollama.model,
                           temperature=settings.ollama.temperature, timeout=settings.ollama.timeout)
    except OSError as exc:
        raise HTTPException(500, f"Could not write .env: {exc}") from exc
    if settings.ollama.model != old_model:
        a.llm.warm()
    return {"status": "saved", "path": str(path)}


# ── Phone & voice ────────────────────────────────────────────────────

@app.post("/api/phone/test")
def phone_test() -> dict[str, str]:
    result = phone.send_to_phone("VDX OpenAgent can reach your phone.", "VDX connected")
    if result.startswith("Error"):
        raise HTTPException(400, result)
    return {"status": result}


@app.get("/api/voice")
def voice_status() -> dict[str, bool]:
    """Local speech-to-text installed? Can the app record the mic itself? Can it speak?"""
    ok = voice.available()
    return {"available": ok, "native": ok and voice.can_record(), "tts": bool(__import__("shutil").which("say"))}


@app.post("/api/voice/record/start")
def voice_record_start() -> dict[str, str]:
    if not voice.can_record():
        raise HTTPException(501, "Recording needs sounddevice: .venv/bin/pip install sounddevice")
    voice.stop_speaking()  # don't record our own voice
    try:
        voice.start_recording()
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc
    return {"status": "recording"}


@app.get("/api/voice/record/status")
def voice_record_status() -> dict[str, Any]:
    """Live transcription so far, and whether the speaker has paused (hands-free mode)."""
    return voice.recording_status()


@app.post("/api/voice/record/stop")
def voice_record_stop(discard: bool = False) -> dict[str, str]:
    """Stop recording and return the transcription (or just stop, with ``discard``)."""
    if discard:
        voice.stop_recording(discard=True)
        return {"text": "", "language": ""}
    try:
        return voice.transcribe_recording()
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except voice.VoiceUnavailable as exc:
        raise HTTPException(501, str(exc)) from exc
    except Exception as exc:
        logger.exception("Transcription failed")
        raise HTTPException(500, f"Transcription failed: {exc}") from exc


@app.post("/api/voice/transcribe")
async def voice_transcribe(request: Request, language: str = "") -> dict[str, str]:
    """Transcribe a recorded clip (raw audio in the request body) on this Mac."""
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "No audio received")
    if len(audio) > 25_000_000:
        raise HTTPException(413, "Recording too long")
    try:
        return await run_in_threadpool(voice.transcribe, audio, language or None)
    except voice.VoiceUnavailable as exc:
        raise HTTPException(501, str(exc)) from exc
    except Exception as exc:
        logger.exception("Transcription failed")
        raise HTTPException(500, f"Transcription failed: {exc}") from exc


@app.post("/api/voice/speak")
def voice_speak(body: SpeakPayload) -> dict[str, bool]:
    """Read text aloud with a local macOS voice."""
    return {"speaking": voice.speak(body.text, body.language)}


@app.get("/api/voice/speak")
def voice_speaking() -> dict[str, bool]:
    return {"speaking": voice.speaking()}


@app.delete("/api/voice/speak")
def voice_speak_stop() -> dict[str, bool]:
    voice.stop_speaking()
    return {"speaking": False}


# ── Automations ──────────────────────────────────────────────────────

class AutomationPayload(BaseModel):
    name: str | None = None
    prompt: str | None = None
    kind: str | None = None
    every_minutes: int | None = None
    time: str | None = None
    weekdays: str | None = None
    run_at: str | None = None
    model: str | None = None
    notify: bool | None = None
    enabled: bool | None = None


def _require_scheduler() -> automations.Scheduler:
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not ready")
    return scheduler


@app.get("/api/automations")
def list_automations() -> dict[str, Any]:
    return {"automations": _require_scheduler().store.list()}


@app.post("/api/automations")
def create_automation(body: AutomationPayload) -> dict[str, Any]:
    try:
        a = _require_scheduler().store.create(**body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    publish("automations")
    return a


@app.patch("/api/automations/{aid}")
def update_automation(aid: int, body: AutomationPayload) -> dict[str, Any]:
    try:
        a = _require_scheduler().store.update(aid, **body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not a:
        raise HTTPException(status_code=404, detail="Automation not found")
    publish("automations")
    return a


@app.delete("/api/automations/{aid}")
def delete_automation(aid: int) -> dict[str, str]:
    _require_scheduler().store.delete(aid)
    publish("automations")
    return {"status": "deleted"}


@app.post("/api/automations/{aid}/run")
def run_automation(aid: int) -> dict[str, Any]:
    """Run an automation immediately (blocks until the agent replies)."""
    a = _require_scheduler().run(aid)
    if not a:
        raise HTTPException(status_code=404, detail="Automation not found")
    return a


# ── Web UI (all-in-one mode) ─────────────────────────────────────────
# When `ui/build` exists (``pnpm build``), the API also serves the UI on
# the same port — mounted last so every /api route above wins.

_ROOT = Path(__file__).resolve().parent.parent
_UI = next((p for p in (_ROOT / "ui" / "build", _ROOT / "web" / "out") if p.is_dir()), None)
if _UI is not None:
    if (_UI / "_app").is_dir():
        app.mount("/_app", StaticFiles(directory=_UI / "_app"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """Serve built UI files, falling back to index.html for client-side routes."""
        f = (_UI / path).resolve()
        if path and f.is_file() and f.is_relative_to(_UI):
            return FileResponse(f)
        # never cache the shell, so a rebuilt UI shows up on the next launch
        return FileResponse(_UI / "index.html", headers={"Cache-Control": "no-store"})
