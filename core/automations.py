"""
Core · Automations
==================
Scheduled prompts the agent runs on its own ("every morning at 8
summarise my unread email"). Stored in SQLite next to the chat history;
a background thread checks every 20 s and runs whatever is due, each
automation writing into its own conversation.

Schedules:
    interval  — every ``every_minutes`` minutes
    daily     — at ``time`` (HH:MM) on ``weekdays`` (0=Mon … 6=Sun)
    once      — a single run at ``run_at`` (ISO datetime), then disabled
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any, Callable


logger = logging.getLogger(__name__)

KINDS = ("interval", "daily", "once")
_FIELDS = ("name", "prompt", "kind", "every_minutes", "time", "weekdays", "run_at", "model", "notify", "enabled")

_store: "AutomationStore | None" = None


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def next_run(a: dict[str, Any], after: datetime | None = None) -> str | None:
    """Compute the next local ISO run time for automation *a*, or None if it never runs again."""
    after = after or _now()
    if not a.get("enabled"):
        return None
    kind = a["kind"]
    if kind == "interval":
        last = datetime.fromisoformat(a["last_run"]) if a.get("last_run") else None
        step = timedelta(minutes=max(1, int(a.get("every_minutes") or 60)))
        return max((last or after) + step, after).isoformat()
    if kind == "once":
        if a.get("last_run") or not a.get("run_at"):
            return None
        return a["run_at"]
    # daily
    hh, mm = (int(x) for x in (a.get("time") or "08:00").split(":")[:2])
    days = {int(d) for d in str(a.get("weekdays") or "0,1,2,3,4,5,6").split(",") if d.strip() != ""}
    for offset in range(8):
        cand = (after + timedelta(days=offset)).replace(hour=hh, minute=mm, second=0)
        if cand > after and cand.weekday() in days:
            return cand.isoformat()
    return None


def _parse_when(value: str) -> datetime:
    """Local naive datetime from an ISO string ("2026-11-10T09:00", "2026-11-10 09:00", with or without a zone)."""
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(f"run_at must be a date and time like 2026-11-10T09:00, got '{value}'") from None
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def _validate(data: dict[str, Any]) -> dict[str, Any]:
    """Check and normalise schedule fields (raises ValueError with a readable message)."""
    if data.get("time") is not None:
        m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", str(data["time"]).strip())
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise ValueError(f"time must be HH:MM, got '{data['time']}'")
        data["time"] = f"{int(m.group(1)):02d}:{m.group(2)}"
    if data.get("weekdays") is not None:
        try:
            days = sorted({int(d) for d in str(data["weekdays"]).split(",") if d.strip()})
        except ValueError:
            raise ValueError("weekdays must be a comma list of 0 (Mon) … 6 (Sun)") from None
        if not days or any(d < 0 or d > 6 for d in days):
            raise ValueError("weekdays must be a comma list of 0 (Mon) … 6 (Sun)")
        data["weekdays"] = ",".join(map(str, days))
    if data.get("every_minutes") is not None:
        n = int(data["every_minutes"])
        if not 1 <= n <= 10080:
            raise ValueError("every_minutes must be between 1 and 10080")
        data["every_minutes"] = n
    if data.get("run_at"):
        data["run_at"] = _parse_when(data["run_at"]).replace(microsecond=0).isoformat()
    return data


class AutomationStore:
    """CRUD for the ``automations`` table (shares the MemoryManager connection)."""

    def __init__(self, conn: Any) -> None:
        """Create the table if needed."""
        self._conn = conn
        self._lock = threading.Lock()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS automations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT    NOT NULL,
                prompt          TEXT    NOT NULL,
                kind            TEXT    NOT NULL DEFAULT 'daily',
                every_minutes   INTEGER DEFAULT 60,
                time            TEXT    DEFAULT '08:00',
                weekdays        TEXT    DEFAULT '0,1,2,3,4,5,6',
                run_at          TEXT,
                model           TEXT,
                notify          INTEGER DEFAULT 1,
                enabled         INTEGER DEFAULT 1,
                conversation_id INTEGER,
                last_run        TEXT,
                last_status     TEXT,
                last_result     TEXT,
                next_run        TEXT,
                runs            INTEGER DEFAULT 0,
                created_at      TEXT    NOT NULL
            )
            """
        )
        # automation chats used to be titled "⏱ name"
        conn.execute("UPDATE conversations SET title = ltrim(substr(title, 2)) WHERE title LIKE '⏱%'")
        conn.commit()

    def _row(self, r: sqlite3.Row | None) -> dict[str, Any] | None:
        if r is None:
            return None
        d = dict(r)
        d["enabled"], d["notify"] = bool(d["enabled"]), bool(d["notify"])
        return d

    def list(self) -> list[dict[str, Any]]:
        """All automations, enabled first then by next run."""
        rows = self._conn.execute(
            "SELECT * FROM automations ORDER BY enabled DESC, next_run IS NULL, next_run, id"
        ).fetchall()
        return [self._row(r) for r in rows]  # type: ignore[misc]

    def get(self, aid: int) -> dict[str, Any] | None:
        """One automation by id."""
        return self._row(self._conn.execute("SELECT * FROM automations WHERE id = ?", (aid,)).fetchone())

    def create(self, **fields: Any) -> dict[str, Any]:
        """Insert an automation; validates the schedule and computes ``next_run``."""
        data = _validate({k: v for k, v in fields.items() if k in _FIELDS and v is not None})
        data.setdefault("kind", "daily")
        if data["kind"] not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if not data.get("name") or not data.get("prompt"):
            raise ValueError("name and prompt are required")
        if data["kind"] == "once" and not data.get("run_at"):
            raise ValueError("a one-off automation needs run_at (date and time)")
        data["next_run"] = next_run({"enabled": True, **data})
        data["created_at"] = _now().isoformat()
        with self._lock:
            cur = self._conn.execute(
                f"INSERT INTO automations ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
                tuple(int(v) if isinstance(v, bool) else v for v in data.values()),
            )
            self._conn.commit()
        return self.get(cur.lastrowid)  # type: ignore[return-value]

    def update(self, aid: int, **fields: Any) -> dict[str, Any] | None:
        """Patch editable fields (or run bookkeeping) and recompute ``next_run``."""
        cur = self.get(aid)
        if not cur:
            return None
        allowed = set(_FIELDS) | {"conversation_id", "last_run", "last_status", "last_result", "runs"}
        data = _validate({k: v for k, v in fields.items() if k in allowed})
        if data.get("kind", cur["kind"]) not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        merged = {**cur, **data}
        if merged["kind"] == "once" and "run_at" in data:
            merged["last_run"] = data["last_run"] = data.get("last_run")  # re-arm a one-shot
        if merged["kind"] == "once" and merged.get("last_run"):
            merged["enabled"] = data["enabled"] = False
        data["next_run"] = next_run(merged)
        with self._lock:
            self._conn.execute(
                f"UPDATE automations SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                (*(int(v) if isinstance(v, bool) else v for v in data.values()), aid),
            )
            self._conn.commit()
        return self.get(aid)

    def delete(self, aid: int) -> None:
        """Remove an automation (its conversation is kept)."""
        with self._lock:
            self._conn.execute("DELETE FROM automations WHERE id = ?", (aid,))
            self._conn.commit()

    def due(self) -> list[dict[str, Any]]:
        """Enabled automations whose ``next_run`` has passed."""
        now = _now().isoformat()
        rows = self._conn.execute(
            "SELECT * FROM automations WHERE enabled = 1 AND next_run IS NOT NULL AND next_run <= ?", (now,)
        ).fetchall()
        return [self._row(r) for r in rows]  # type: ignore[misc]


def notify(title: str, text: str, conversation_id: int | None = None) -> None:
    """Store a notification (in-app inbox + toast), show a macOS banner, and push it to the phone if set up."""
    from core import memory
    from tools._applescript import notify_mac

    if memory._active is not None:
        memory._active.add_notification(title, text, conversation_id)
    notify_mac(title, text)
    if _phone_push_on():
        from tools import phone

        threading.Thread(target=phone.send_to_phone, args=(text[:2000], title), daemon=True).start()


def _phone_push_on() -> bool:
    """Whether notifications also go to the phone (Phone connector set up and enabled)."""
    from core import connectors  # late import: connectors imports this module
    from tools import phone

    return phone.configured() and connectors.is_enabled("phone")


class Scheduler:
    """Background thread that runs due automations through the agent."""

    def __init__(self, store: AutomationStore, agent: Any) -> None:
        """Wire the store to an Agent (whose lock serialises it with the chat API)."""
        global _store
        _store = store
        self.store, self.agent = store, agent
        self._stop = threading.Event()
        self._running: set[int] = set()
        self.on_change: Callable[[], None] | None = None

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                logger.debug("automation listener failed", exc_info=True)

    def start(self) -> None:
        """Start polling in a daemon thread."""
        threading.Thread(target=self._loop, name="automations", daemon=True).start()
        logger.info("Automation scheduler started")

    def stop(self) -> None:
        """Stop the polling loop."""
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(20):
            try:
                for a in self.store.due():
                    self.run(a["id"])
            except Exception:
                logger.exception("Automation tick failed")

    def run(self, aid: int) -> dict[str, Any] | None:
        """Run automation *aid* now (blocking) and record the result."""
        a = self.store.get(aid)
        if not a or aid in self._running:
            return a
        self._running.add(aid)
        try:
            mem = self.agent.memory
            cid = a.get("conversation_id")
            if not cid or not mem.get_conversation(cid):
                cid = mem.create_conversation(a["name"])["id"]
            # Framing goes in the model-only context: put in the message itself, small models read
            # "Automation …" as a request to create one and answer with questions instead of doing the task.
            pushed = a.get("notify") and _phone_push_on()
            context = (
                "This is a scheduled task running now with nobody watching. Do the task below "
                "right away: call the tools you need, then reply with the result. Do not ask questions, do not "
                "ask for confirmation and do not create or change automations."
                + (" Your reply is sent to the user's phone automatically, so don't call send_to_phone." if pushed else "")
            )
            started = _now().isoformat()
            self.store.update(aid, last_status="running")
            self._changed()
            try:
                with self.agent.lock:
                    reply = self.agent.process(a["prompt"], source="automation", model=a.get("model") or None,
                                               conversation_id=cid, context=context)
                status = "ok"
            except Exception as exc:
                logger.exception("Automation %s failed", aid)
                reply, status = f"Error: {exc}", "error"
            self.store.update(
                aid, conversation_id=cid, last_run=started, last_status=status,
                last_result=reply[:2000], runs=(a.get("runs") or 0) + 1,
            )
            if a.get("notify") or status == "error":
                notify(a["name"] + (" failed" if status == "error" else ""), reply, cid)
            self._changed()
            return self.store.get(aid)
        finally:
            self._running.discard(aid)


# ── Agent tools ──────────────────────────────────────────────────────

def _tool_create(name: str, prompt: str, kind: str = "daily", time: str = "08:00",
                 weekdays: str = "0,1,2,3,4,5,6", every_minutes: int = 60, run_at: str = "") -> str:
    if not _store:
        return "Error: automations are not running"
    try:
        a = _store.create(name=name, prompt=prompt, kind=kind, time=time, weekdays=weekdays,
                          every_minutes=every_minutes, run_at=run_at or None)
    except ValueError as exc:
        return f"Error: {exc}"
    return f"Automation #{a['id']} “{a['name']}” created — next run {a['next_run']}."


def _tool_list() -> str:
    if not _store:
        return "Error: automations are not running"
    items = _store.list()
    if not items:
        return "No automations."
    return "\n".join(
        f"#{a['id']} {a['name']} [{a['kind']}, {'on' if a['enabled'] else 'off'}] next: {a['next_run'] or '—'} · {a['prompt'][:80]}"
        for a in items
    )


def _tool_delete(automation_id: int) -> str:
    if not _store:
        return "Error: automations are not running"
    if not _store.get(int(automation_id)):
        return f"No automation #{automation_id}"
    _store.delete(int(automation_id))
    return f"Automation #{automation_id} deleted."


TOOLS: dict[str, Callable[..., str]] = {
    "create_automation": _tool_create,
    "list_automations": _tool_list,
    "delete_automation": _tool_delete,
}

TOOL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "create_automation",
        "description": (
            "Schedule a recurring or one-off task that VDX runs by itself later "
            "(e.g. 'every weekday at 8:00 summarise unread email'). The prompt is what VDX will do at run time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short name"},
                "prompt": {"type": "string", "description": "Instruction VDX executes on each run"},
                "kind": {"type": "string", "enum": list(KINDS)},
                "time": {"type": "string", "description": "HH:MM for daily"},
                "weekdays": {"type": "string", "description": "Comma list 0=Mon..6=Sun for daily"},
                "every_minutes": {"type": "integer", "description": "For interval"},
                "run_at": {"type": "string", "description": "ISO datetime for once"},
            },
            "required": ["name", "prompt", "kind"],
        },
    },
    {
        "name": "list_automations",
        "description": "List scheduled automations.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_automation",
        "description": "Delete a scheduled automation by id.",
        "parameters": {
            "type": "object",
            "properties": {"automation_id": {"type": "integer"}},
            "required": ["automation_id"],
        },
    },
]
