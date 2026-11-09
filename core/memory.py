"""
Core · Memory Manager
=====================
Chat history, long-term facts about the user, usage stats and notifications,
all persisted in SQLite (one thread-safe connection shared by the app).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from config.settings import get_settings
from core.db import LockedConnection

logger = logging.getLogger(__name__)


def _now() -> str:
    """Current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


# History given to the model: up to SHORT_TERM_LIMIT user/assistant messages. The window
# moves in blocks of WINDOW_BLOCK messages instead of one per turn, so the start of the
# prompt stays identical across turns and Ollama can reuse its prompt cache.
SHORT_TERM_LIMIT = 20
WINDOW_BLOCK = 10
TOOL_CONTEXT_CHARS = 600  # old tool results are shortened in that history
NOTE_RE = re.compile(r"(\n\[(?:page|chat|images|file)\] .+)+$")

_active: MemoryManager | None = None


def _local_stamp(iso: str | None) -> str:
    """``[09/11 14:05]`` in local time — stable for a stored message, so the prompt prefix doesn't change."""
    try:
        return datetime.fromisoformat(iso or "").astimezone().strftime("[%d/%m %H:%M]")
    except ValueError:
        return ""


class MemoryManager:
    """Manage chat history, facts, usage and notifications in SQLite."""

    def __init__(self, db_path: str | None = None) -> None:
        """Open (or create) the SQLite database and prepare tables."""
        global _active
        path = db_path or get_settings().database.path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = LockedConnection(path)
        # WAL + NORMAL sync: commits (one per message) don't wait for a full disk flush
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._create_tables()
        self._global_floor = 0  # messages before this id are hidden from the global (Discord) window
        self.on_notify: list[Callable[[dict[str, Any]], None]] = []
        _active = self
        logger.info("MemoryManager ready — DB: %s", path)

    # ── Schema ───────────────────────────────────────────────────────

    def _create_tables(self) -> None:
        """Create tables, run migrations and set up full-text search."""
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                role      TEXT    NOT NULL,
                content   TEXT    NOT NULL,
                source    TEXT    DEFAULT 'gui',
                created_at TEXT   NOT NULL
            );
            CREATE TABLE IF NOT EXISTS facts (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                key       TEXT    UNIQUE NOT NULL,
                value     TEXT    NOT NULL,
                updated_at TEXT   NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT    NOT NULL,
                pinned     INTEGER DEFAULT 0,
                created_at TEXT    NOT NULL,
                updated_at TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id   INTEGER,
                model             TEXT    NOT NULL,
                source            TEXT,
                prompt_tokens     INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                duration_ms       INTEGER DEFAULT 0,
                tool_calls        INTEGER DEFAULT 0,
                llm_calls         INTEGER DEFAULT 0,
                created_at        TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT NOT NULL,
                text            TEXT NOT NULL,
                conversation_id INTEGER,
                read            INTEGER DEFAULT 0,
                created_at      TEXT NOT NULL
            );
            """
        )
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(messages)")}
        for col in ("conversation_id INTEGER", "model TEXT", "extra TEXT"):
            if col.split()[0] not in cols:
                self._conn.execute(f"ALTER TABLE messages ADD COLUMN {col}")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id)")
        self._fts = self._setup_fts()
        self._conn.commit()

    def _setup_fts(self) -> bool:
        """Full-text index over message content (falls back to LIKE without FTS5)."""
        exists = self._conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'messages_fts'").fetchone()
        try:
            self._conn.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content, content='messages', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
                CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
                END;
                CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE OF content ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
                    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
                END;
                """
            )
            if not exists:
                self._conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
            return True
        except Exception:
            logger.warning("SQLite FTS5 unavailable — chat search uses LIKE", exc_info=True)
            return False

    # ── Messages ─────────────────────────────────────────────────────

    def add_message(
        self,
        role: str,
        content: str,
        source: str = "gui",
        conversation_id: int | None = None,
        model: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> int:
        """Append a message and return its id.

        ``extra`` holds per-message data: attachments given to the model with a user
        turn (``context`` text, ``images``), a tool call's ``name``/``args``, or a
        reply's ``thinking`` / ``stopped`` flag.
        """
        now = _now()
        with self._conn.transaction() as c:
            mid = c.execute(
                "INSERT INTO messages (role, content, source, created_at, conversation_id, model, extra) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (role, content, source, now, conversation_id, model, json.dumps(extra) if extra else None),
            ).lastrowid
            if conversation_id is not None:
                c.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        return int(mid or 0)

    def get_message(self, message_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["extra"] = json.loads(d["extra"]) if d.get("extra") else {}
        return d

    def _conv_clause(self, conversation_id: int | None) -> tuple[str, tuple[Any, ...]]:
        if conversation_id is None:
            return "conversation_id IS NULL AND id >= ?", (self._global_floor,)
        return "conversation_id = ?", (conversation_id,)

    def _window_start(self, conversation_id: int | None) -> int:
        """Id of the first message in the model's history window (block-aligned, see SHORT_TERM_LIMIT)."""
        where, args = self._conv_clause(conversation_id)
        chat = f"{where} AND role IN ('user','assistant')"
        n = self._conn.execute(f"SELECT COUNT(*) FROM messages WHERE {chat}", args).fetchone()[0]
        if n <= SHORT_TERM_LIMIT:
            return 0
        drop = ((n - SHORT_TERM_LIMIT) // WINDOW_BLOCK + 1) * WINDOW_BLOCK
        row = self._conn.execute(
            f"SELECT id FROM messages WHERE {chat} ORDER BY id LIMIT 1 OFFSET ?", (*args, drop)
        ).fetchone()
        if not row:
            return 0
        # start on a user turn, never on a dangling reply
        user = self._conn.execute(
            f"SELECT id FROM messages WHERE {where} AND role = 'user' AND id >= ? ORDER BY id LIMIT 1", (*args, row[0])
        ).fetchone()
        return user[0] if user else row[0]

    def get_context(self, conversation_id: int | None = None) -> list[dict[str, Any]]:
        """Messages for the model: the recent window with timestamps, attachments and shortened tool results."""
        where, args = self._conv_clause(conversation_id)
        rows = self._conn.execute(
            f"SELECT role, content, created_at, extra FROM messages WHERE {where} AND id >= ? ORDER BY id",
            (*args, self._window_start(conversation_id)),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            content, extra = r["content"], json.loads(r["extra"]) if r["extra"] else {}
            msg: dict[str, Any] = {"role": r["role"]}
            if r["role"] == "tool" and len(content) > TOOL_CONTEXT_CHARS:
                content = content[:TOOL_CONTEXT_CHARS] + "…(shortened)"
            elif r["role"] == "user":
                content = f"{_local_stamp(r['created_at'])} {content}".lstrip()
                if extra.get("context"):
                    content = f"{extra['context']}\n\n---\n\n{content}"
                if extra.get("images"):
                    msg["images"] = extra["images"]
            msg["content"] = content
            out.append(msg)
        return out

    def last_user_message(self, conversation_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id FROM messages WHERE conversation_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        return self.get_message(row[0]) if row else None

    def delete_after(self, conversation_id: int, message_id: int) -> None:
        """Delete every message of a conversation that comes after *message_id* (for regenerate)."""
        with self._conn.transaction() as c:
            c.execute("DELETE FROM messages WHERE conversation_id = ? AND id > ?", (conversation_id, message_id))

    def delete_from(self, conversation_id: int, message_id: int) -> None:
        """Delete *message_id* and everything after it (for editing a message)."""
        with self._conn.transaction() as c:
            c.execute("DELETE FROM messages WHERE conversation_id = ? AND id >= ?", (conversation_id, message_id))

    # ── Conversations ────────────────────────────────────────────────

    def create_conversation(self, title: str = "New chat") -> dict[str, Any]:
        """Create a conversation thread and return it."""
        now = _now()
        with self._conn.transaction() as c:
            cid = c.execute(
                "INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)",
                (title[:80] or "New chat", now, now),
            ).lastrowid
        return self.get_conversation(cid)  # type: ignore[arg-type,return-value]

    def get_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        """Return one conversation row, or None."""
        row = self._conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        return dict(row) if row else None

    def list_conversations(self, query: str = "", limit: int = 200) -> list[dict[str, Any]]:
        """List conversations (pinned first, newest first), optionally searched by title and content."""
        sql = (
            "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id "
            "AND m.role IN ('user','assistant')) AS message_count FROM conversations c"
        )
        args: list[Any] = []
        query = query.strip()
        if query:
            terms = re.findall(r"\w+", query)
            if self._fts and terms:
                match = " ".join(f'"{t}"*' for t in terms)
                sql += (
                    " WHERE c.title LIKE ? OR c.id IN (SELECT m.conversation_id FROM messages_fts f "
                    "JOIN messages m ON m.id = f.rowid WHERE messages_fts MATCH ? AND m.role IN ('user','assistant'))"
                )
                args += [f"%{query}%", match]
            else:
                sql += (
                    " WHERE c.title LIKE ? OR EXISTS (SELECT 1 FROM messages m "
                    "WHERE m.conversation_id = c.id AND m.content LIKE ?)"
                )
                args += [f"%{query}%", f"%{query}%"]
        sql += " ORDER BY c.pinned DESC, c.updated_at DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def update_conversation(
        self, conversation_id: int, title: str | None = None, pinned: bool | None = None
    ) -> dict[str, Any] | None:
        """Rename and/or pin a conversation."""
        with self._conn.transaction() as c:
            if title is not None:
                c.execute("UPDATE conversations SET title = ? WHERE id = ?", (title.strip()[:80] or "Untitled", conversation_id))
            if pinned is not None:
                c.execute("UPDATE conversations SET pinned = ? WHERE id = ?", (int(pinned), conversation_id))
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: int) -> None:
        """Delete a conversation and its messages."""
        with self._conn.transaction() as c:
            c.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            c.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    def get_conversation_messages(self, conversation_id: int, include_tools: bool = False) -> list[dict[str, Any]]:
        """Messages of a conversation, oldest first (tool steps too with *include_tools*)."""
        roles = "('user','assistant','tool')" if include_tools else "('user','assistant')"
        rows = self._conn.execute(
            f"SELECT id, role, content, created_at, model, extra FROM messages WHERE conversation_id = ? "
            f"AND role IN {roles} ORDER BY id",
            (conversation_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            extra = json.loads(d.pop("extra") or "null") or {}
            if d["role"] == "tool":
                m = re.match(r"\[([\w.-]+)\] ?", d["content"])
                d["name"] = extra.get("name") or (m.group(1) if m else "tool")
                d["args"] = extra.get("args") or {}
                d["ok"] = extra.get("ok", not d["content"][m.end() if m else 0:].startswith("Error"))
                d["content"] = d["content"][m.end() if m else 0:][:1500]
            else:
                for k in ("thinking", "stopped"):
                    if extra.get(k):
                        d[k] = extra[k]
            out.append(d)
        return out

    # ── Usage ────────────────────────────────────────────────────────

    def record_usage(self, **fields: Any) -> None:
        """Persist one agent request's token/time stats (see ``usage`` table)."""
        fields.setdefault("created_at", _now())
        keys = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        with self._conn.transaction() as c:
            c.execute(f"INSERT INTO usage ({keys}) VALUES ({marks})", tuple(fields.values()))

    def usage_report(self, days: int = 30, recent: int = 50) -> dict[str, Any]:
        """Aggregate usage: totals, per-model, per-day, and the latest requests."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        agg = (
            "COUNT(*) AS requests, COALESCE(SUM(prompt_tokens),0) AS prompt_tokens, "
            "COALESCE(SUM(completion_tokens),0) AS completion_tokens, "
            "COALESCE(SUM(duration_ms),0) AS duration_ms, COALESCE(SUM(tool_calls),0) AS tool_calls"
        )
        q = self._conn.execute
        return {
            "days": days,
            "totals": dict(q(f"SELECT {agg} FROM usage WHERE created_at >= ?", (since,)).fetchone()),
            "by_model": [
                dict(r) for r in q(
                    f"SELECT model, {agg} FROM usage WHERE created_at >= ? GROUP BY model ORDER BY requests DESC", (since,)
                )
            ],
            "by_day": [
                dict(r) for r in q(
                    f"SELECT substr(created_at,1,10) AS day, {agg} FROM usage "
                    "WHERE created_at >= ? GROUP BY day ORDER BY day", (since,)
                )
            ],
            "recent": [
                dict(r) for r in q(
                    "SELECT u.*, c.title AS conversation_title FROM usage u "
                    "LEFT JOIN conversations c ON c.id = u.conversation_id ORDER BY u.id DESC LIMIT ?", (recent,)
                )
            ],
            "conversations": q("SELECT COUNT(*) FROM conversations").fetchone()[0],
        }

    def clear_short_term(self) -> None:
        """Start a fresh global (Discord) window; the stored history is kept."""
        row = self._conn.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()
        self._global_floor = row[0] + 1
        logger.info("Short-term memory cleared")

    # ── Long-term facts ──────────────────────────────────────────────

    def set_fact(self, key: str, value: str) -> None:
        """Store (or update) a named long-term fact about the user."""
        with self._conn.transaction() as c:
            c.execute(
                "INSERT INTO facts (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key.strip()[:80], value.strip()[:500], _now()),
            )
        logger.info("Fact saved: %s", key)

    def get_fact(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM facts WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def delete_fact(self, key: str) -> bool:
        with self._conn.transaction() as c:
            return c.execute("DELETE FROM facts WHERE key = ?", (key,)).rowcount > 0

    def get_all_facts(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self._conn.execute("SELECT key, value FROM facts ORDER BY key")}

    def list_facts(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute("SELECT key, value, updated_at FROM facts ORDER BY updated_at DESC")]

    def facts_as_system_prompt(self) -> str:
        """Format all facts into a system-prompt snippet for the LLM."""
        facts = self.get_all_facts()
        if not facts:
            return ""
        return "Known facts about the user (saved with remember):\n" + "\n".join(f"- {k}: {v}" for k, v in facts.items())

    # ── Notifications ────────────────────────────────────────────────

    def add_notification(self, title: str, text: str, conversation_id: int | None = None) -> dict[str, Any]:
        with self._conn.transaction() as c:
            nid = c.execute(
                "INSERT INTO notifications (title, text, conversation_id, created_at) VALUES (?, ?, ?, ?)",
                (title[:200], text[:2000], conversation_id, _now()),
            ).lastrowid
            # keep the inbox bounded
            c.execute("DELETE FROM notifications WHERE id <= ?", ((nid or 0) - 500,))
        note = dict(self._conn.execute("SELECT * FROM notifications WHERE id = ?", (nid,)).fetchone())
        for cb in list(self.on_notify):
            try:
                cb(note)
            except Exception:
                logger.exception("notification listener failed")
        return note

    def list_notifications(self, after: int = 0, unread: bool = False, limit: int = 50) -> list[dict[str, Any]]:
        sql = "SELECT * FROM notifications WHERE id > ?" + (" AND read = 0" if unread else "")
        rows = self._conn.execute(sql + " ORDER BY id DESC LIMIT ?", (after, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def mark_notifications_read(self, ids: list[int] | None = None) -> None:
        with self._conn.transaction() as c:
            if ids is None:
                c.execute("UPDATE notifications SET read = 1 WHERE read = 0")
            elif ids:
                c.execute(f"UPDATE notifications SET read = 1 WHERE id IN ({','.join('?' * len(ids))})", ids)

    # ── History queries ──────────────────────────────────────────────

    def get_history(self, limit: int = 50, source: str | None = None) -> list[dict[str, Any]]:
        """Return recent messages from the database, optionally for one channel."""
        if source:
            rows = self._conn.execute(
                "SELECT role, content, source, created_at FROM messages WHERE source = ? ORDER BY id DESC LIMIT ?",
                (source, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT role, content, source, created_at FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def close(self) -> None:
        self._conn.close()
        logger.info("MemoryManager closed")


# ── Agent tools: long-term memory ────────────────────────────────────

def _remember(key: str, value: str) -> str:
    if not _active:
        return "Error: memory is not available"
    if not key.strip() or not value.strip():
        return "Error: key and value are required"
    _active.set_fact(key, value)
    return f"Remembered: {key.strip()} = {value.strip()}"


def _forget(key: str) -> str:
    if not _active:
        return "Error: memory is not available"
    return f"Forgot {key}." if _active.delete_fact(key) else f"Nothing saved under '{key}'."


TOOLS: dict[str, Callable[..., str]] = {"remember": _remember, "forget": _forget}

TOOL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "remember",
        "description": (
            "Save a lasting fact or preference about the user (name, family, job, habits, favourite things, "
            "how they like answers). Call it whenever the user shares one, or says 'remember'. Reuse an existing "
            "key to update it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Short label, e.g. 'partner name' or 'coffee order'"},
                "value": {"type": "string", "description": "The fact itself"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "forget",
        "description": "Delete a saved fact about the user by its key.",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
    },
]
