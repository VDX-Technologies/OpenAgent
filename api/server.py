"""
VDX OpenAgent · FastAPI Server
==========================
HTTP API consumed by the SvelteKit frontend (ui/). Exposes chat,
status, history, and settings endpoints. Optionally starts
the Discord bot in a background thread.
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config.settings import get_settings, reload_settings, save_settings_to_env
from core import automations, connectors, hardware
from core.agent import Agent
from core.llm import OllamaClient
from core.memory import MemoryManager
from core.telemetry_share import TelemetryShare

logger = logging.getLogger(__name__)

# Shared singletons — initialised in lifespan
llm: OllamaClient | None = None
memory: MemoryManager | None = None
agent: Agent | None = None
scheduler: automations.Scheduler | None = None
share: TelemetryShare | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot core services and optionally the Discord bot."""
    global llm, memory, agent, scheduler, share

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
        datefmt="%H:%M:%S",
    )

    llm = OllamaClient()
    memory = MemoryManager()
    agent = Agent(llm=llm, memory=memory)
    share = agent.share = TelemetryShare()

    if llm.is_available():
        logger.info("Ollama online — model: %s", llm.model)
    else:
        logger.warning("Ollama offline at %s", llm.base_url)

    settings = get_settings()
    if settings.discord.token:
        from interface.discord_bot import run_discord_bot

        threading.Thread(
            target=run_discord_bot,
            args=(agent,),
            name="discord-bot",
            daemon=True,
        ).start()
        logger.info("Discord bot thread started")

    scheduler = automations.Scheduler(automations.AutomationStore(memory._conn), agent, _agent_lock)
    scheduler.start()

    yield

    if scheduler:
        scheduler.stop()
    if share:
        share.stop()
    if memory:
        memory.close()
    logger.info("VDX OpenAgent API shut down")


app = FastAPI(
    title="VDX OpenAgent API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / response models ────────────────────────────────────────

class ChatRequest(BaseModel):
    """Incoming chat message from the web UI."""

    message: str = Field(..., min_length=1, max_length=32_000)
    source: str = "web"
    model: str | None = None
    conversation_id: int | None = None


class ChatResponse(BaseModel):
    """Final assistant reply plus the conversation it belongs to."""

    reply: str
    conversation_id: int | None = None
    usage: dict[str, Any] = {}


class ConversationPatch(BaseModel):
    """Rename / pin a conversation."""

    title: str | None = None
    pinned: bool | None = None


class PullRequest(BaseModel):
    """Model to download from the Ollama registry."""

    name: str = Field(..., min_length=1, max_length=200)


class StatusResponse(BaseModel):
    """Health + runtime snapshot."""

    ollama_online: bool
    model: str
    base_url: str
    temperature: float
    short_term_messages: int
    facts: int
    gmail_configured: bool
    discord_configured: bool


class SettingsPayload(BaseModel):
    """Editable settings mirrored to `.env`."""

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


class ConnectorToggle(BaseModel):
    """Enable/disable a connector."""

    enabled: bool


# ── Helpers ──────────────────────────────────────────────────────────

def _require_agent() -> Agent:
    if agent is None:
        raise HTTPException(503, "Agent not ready")
    return agent


# ── Routes ───────────────────────────────────────────────────────────

@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "service": "vdx-agent"}


@app.get("/api/status", response_model=StatusResponse)
def status() -> StatusResponse:
    """Return Ollama / integrations status for the UI header."""
    a = _require_agent()
    s = get_settings()
    return StatusResponse(
        ollama_online=a.llm.is_available(),
        model=a.llm.model,
        base_url=a.llm.base_url,
        temperature=a.llm.temperature,
        short_term_messages=len(a.memory.get_context()),
        facts=len(a.memory.get_all_facts()),
        gmail_configured=bool(s.gmail.address and s.gmail.app_password),
        discord_configured=bool(s.discord.token),
    )


@app.get("/api/models")
def list_models() -> dict[str, list[str]]:
    """List models installed on the local Ollama server."""
    a = _require_agent()
    return {"models": a.llm.list_models()}


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    """Process a user message through the agent (tools + memory)."""
    a = _require_agent()
    text = body.message.strip()
    cid = body.conversation_id
    if cid is not None and not a.memory.get_conversation(cid):
        raise HTTPException(404, "Conversation not found")
    if cid is None and body.source == "web":
        title = " ".join(text.split())[:60] or "New chat"
        cid = a.memory.create_conversation(title)["id"]
    try:
        with _agent_lock:
            reply = a.process(text, source=body.source, model=body.model or None, conversation_id=cid)
            usage = dict(a.last_usage)
    except Exception as exc:
        logger.exception("Chat failed")
        raise HTTPException(500, f"Agent error: {exc}") from exc
    return ChatResponse(reply=reply, conversation_id=cid, usage=usage)


@app.post("/api/chat/stream")
def chat_stream(body: ChatRequest) -> StreamingResponse:
    """Same as ``/api/chat`` but streams Server-Sent Events (token / tool / done)."""
    a = _require_agent()
    text = body.message.strip()
    cid = body.conversation_id
    if cid is not None and not a.memory.get_conversation(cid):
        raise HTTPException(404, "Conversation not found")
    if cid is None and body.source == "web":
        cid = a.memory.create_conversation(" ".join(text.split())[:60] or "New chat")["id"]

    def events() -> Iterator[str]:
        with _agent_lock:
            try:
                # tell the client its conversation id up front, so it can follow the run anywhere
                yield f"data: {json.dumps({'type': 'start', 'conversation_id': cid})}\n\n"
                for ev in a.process_stream(text, source=body.source, model=body.model or None, conversation_id=cid):
                    if ev["type"] == "done":
                        ev["conversation_id"] = cid
                    yield f"data: {json.dumps(ev)}\n\n"
            except Exception as exc:
                logger.exception("Stream failed")
                yield f"data: {json.dumps({'type': 'error', 'detail': f'Agent error: {exc}'})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ── Conversations ────────────────────────────────────────────────────

@app.get("/api/conversations")
def list_conversations(q: str | None = None, limit: int = 100) -> dict[str, Any]:
    """List chats (pinned first), optionally filtered by title/content."""
    return {"conversations": _require_agent().memory.list_conversations(query=q or "", limit=limit)}


@app.post("/api/conversations")
def create_conversation() -> dict[str, Any]:
    """Create an empty chat."""
    return _require_agent().memory.create_conversation("New chat")


@app.get("/api/conversations/{cid}")
def get_conversation(cid: int) -> dict[str, Any]:
    """Return a chat with its user/assistant messages."""
    m = _require_agent().memory
    conv = m.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return {**conv, "messages": m.get_conversation_messages(cid)}


@app.patch("/api/conversations/{cid}")
def patch_conversation(cid: int, body: ConversationPatch) -> dict[str, Any]:
    """Rename or pin/unpin a chat."""
    m = _require_agent().memory
    if not m.get_conversation(cid):
        raise HTTPException(404, "Conversation not found")
    m.update_conversation(cid, title=body.title, pinned=body.pinned)
    return m.get_conversation(cid)


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: int) -> dict[str, str]:
    """Delete a chat and its messages."""
    _require_agent().memory.delete_conversation(cid)
    return {"status": "deleted"}


# ── Usage & system ───────────────────────────────────────────────────

@app.get("/api/telemetry")
def telemetry(days: int = 7) -> dict[str, Any]:
    """Latency/throughput breakdown of recent requests, loaded models and tuning tips."""
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
    """Sharing consent state plus an exact preview of the anonymous install record."""
    s = _require_share()
    return {**s.status(), "preview": s.install()}


@app.put("/api/telemetry/consent")
def telemetry_consent_set(body: ConsentPayload) -> dict[str, Any]:
    """Allow or deny anonymous telemetry sharing."""
    return _require_share().set_consent(body.allow)


@app.delete("/api/telemetry")
def telemetry_clear() -> dict[str, bool]:
    """Delete all recorded traces."""
    _require_agent().telemetry.clear()
    return {"ok": True}


@app.get("/api/usage")
def usage(days: int = 30) -> dict[str, Any]:
    """Token / latency report for the last *days* days."""
    return _require_agent().memory.usage_report(days=max(1, min(days, 365)))


@app.get("/api/notifications")
def notifications(after: int = 0) -> dict[str, Any]:
    """In-app notifications (automation results) newer than *after*."""
    from core.automations import notifications_since
    return {"items": notifications_since(after)}


@app.get("/api/system")
def system_info() -> dict[str, Any]:
    """Hardware profile + model recommendations for this machine."""
    a = _require_agent()
    profile = hardware.system_profile()
    try:
        installed = a.llm.list_models()
    except Exception:
        installed = []
    return {"profile": profile, "recommendations": hardware.recommend(profile, installed)}


# ── Model management ─────────────────────────────────────────────────

_agent_lock = threading.Lock()
_pulls: dict[str, dict[str, Any]] = {}


@app.get("/api/models/detailed")
def models_detailed() -> dict[str, Any]:
    """Installed models with size/family/quantization + currently loaded ones."""
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
    """Progress of every pull started since the API booted."""
    return {"pulls": list(_pulls.values())}


@app.delete("/api/models/{name:path}")
def delete_model(name: str) -> dict[str, str]:
    """Remove an installed model from Ollama."""
    try:
        _require_agent().llm.delete_model(name)
    except Exception as exc:
        raise HTTPException(502, f"Delete failed: {exc}") from exc
    _pulls.pop(name, None)
    return {"status": "deleted"}


@app.get("/api/connectors")
def list_connectors() -> dict[str, Any]:
    """List app connectors with enabled/configured state."""
    return {"connectors": connectors.describe()}


@app.put("/api/connectors/{cid}")
def toggle_connector(cid: str, body: ConnectorToggle) -> dict[str, Any]:
    """Enable or disable a connector."""
    try:
        connectors.set_enabled(cid, body.enabled)
    except KeyError:
        raise HTTPException(404, f"Unknown connector '{cid}'") from None
    return {"connectors": connectors.describe()}


@app.get("/api/history")
def history(limit: int = 50, source: str | None = "web") -> dict[str, Any]:
    """Return recent messages for hydrating the chat UI."""
    a = _require_agent()
    msgs = a.memory.get_history(limit=limit, source=source)
    # Only user/assistant for the feed
    clean = [
        {"role": m["role"], "content": m["content"], "created_at": m.get("created_at")}
        for m in msgs
        if m["role"] in ("user", "assistant")
    ]
    return {"messages": clean}


@app.post("/api/chat/clear")
def clear_chat() -> dict[str, str]:
    """Clear the short-term conversation window."""
    a = _require_agent()
    a.memory.clear_short_term()
    return {"status": "cleared"}


@app.get("/api/settings")
def get_settings_api() -> SettingsPayload:
    """Return current settings (secrets included — local-only app)."""
    s = get_settings()
    return SettingsPayload(
        ollama_base_url=s.ollama.base_url,
        ollama_model=s.ollama.model,
        ollama_temperature=s.ollama.temperature,
        ollama_timeout=s.ollama.timeout,
        gmail_address=s.gmail.address,
        gmail_app_password=s.gmail.app_password,
        discord_bot_token=s.discord.token,
        discord_prefix=s.discord.command_prefix,
        discord_allowed_users=",".join(str(u) for u in s.discord.allowed_user_ids),
        whatsapp_token=s.whatsapp.token,
        whatsapp_phone_id=s.whatsapp.phone_id,
        github_token=s.github.token,
        code_workspace=s.code.workspace,
    )


@app.put("/api/settings")
def put_settings(body: SettingsPayload) -> dict[str, str]:
    """Persist settings to `.env` and hot-reload Ollama client config."""
    a = _require_agent()
    updates = {
        "OLLAMA_BASE_URL": body.ollama_base_url.strip(),
        "OLLAMA_MODEL": body.ollama_model.strip(),
        "OLLAMA_TEMPERATURE": str(body.ollama_temperature),
        "OLLAMA_TIMEOUT": str(body.ollama_timeout),
        "GMAIL_ADDRESS": body.gmail_address.strip(),
        "GMAIL_APP_PASSWORD": body.gmail_app_password.strip(),
        "DISCORD_BOT_TOKEN": body.discord_bot_token.strip(),
        "DISCORD_PREFIX": body.discord_prefix.strip() or "!",
        "DISCORD_ALLOWED_USERS": body.discord_allowed_users.strip(),
        "WHATSAPP_TOKEN": body.whatsapp_token.strip(),
        "WHATSAPP_PHONE_ID": body.whatsapp_phone_id.strip(),
        "GITHUB_TOKEN": body.github_token.strip(),
        "CODE_WORKSPACE": body.code_workspace.strip(),
    }
    if not updates["OLLAMA_BASE_URL"] or not updates["OLLAMA_MODEL"]:
        raise HTTPException(400, "Ollama URL and model are required")

    try:
        path = save_settings_to_env(updates)
        settings = reload_settings()
        a.llm.apply_config(
            base_url=settings.ollama.base_url,
            model=settings.ollama.model,
            temperature=settings.ollama.temperature,
            timeout=settings.ollama.timeout,
        )
    except OSError as exc:
        raise HTTPException(500, f"Could not write .env: {exc}") from exc

    return {"status": "saved", "path": str(path)}


# ── Automations ──────────────────────────────────────────────────────


class AutomationPayload(BaseModel):
    """Create / patch an automation (all optional on PATCH)."""

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
    """All automations."""
    return {"automations": _require_scheduler().store.list()}


@app.post("/api/automations")
def create_automation(body: AutomationPayload) -> dict[str, Any]:
    """Create an automation."""
    try:
        return _require_scheduler().store.create(**body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/automations/{aid}")
def update_automation(aid: int, body: AutomationPayload) -> dict[str, Any]:
    """Edit / enable / disable an automation."""
    try:
        a = _require_scheduler().store.update(aid, **body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not a:
        raise HTTPException(status_code=404, detail="Automation not found")
    return a


@app.delete("/api/automations/{aid}")
def delete_automation(aid: int) -> dict[str, str]:
    """Delete an automation."""
    _require_scheduler().store.delete(aid)
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
        return FileResponse(_UI / "index.html")
