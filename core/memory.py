"""
Core · Memory Manager
=====================
Short-term (in-RAM conversation window) and long-term
(SQLite-persisted) memory for the Desktop AI Pet Agent.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config.settings import get_settings

logger = logging.getLogger(__name__)


def _now() -> str:
    """Current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()

# How many recent turns to keep in the short-term window sent to the LLM
SHORT_TERM_LIMIT = 20


class MemoryManager:
    """Manage chat history with a rolling short-term window and SQLite persistence."""

    def __init__(self, db_path: str | None = None) -> None:
        """Open (or create) the SQLite database and prepare tables.

        Args:
            db_path: Override path; defaults to settings.database.path.
        """
        path = db_path or get_settings().database.path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

        # In-memory rolling window of the current conversation
        self._short_term: list[dict[str, Any]] = []
        self._load_recent_into_short_term()
        logger.info("MemoryManager ready — DB: %s", path)

    # ── Schema ───────────────────────────────────────────────────────

    def _create_tables(self) -> None:
        """Create the messages and facts tables if they do not exist."""
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
            """
        )
        # Migration: older DBs have no conversation_id on messages
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(messages)")}
        if "conversation_id" not in cols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN conversation_id INTEGER")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id)"
        )
        self._conn.commit()

    def _load_recent_into_short_term(self) -> None:
        """Populate the short-term window from the last N DB messages."""
        rows = self._conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id IS NULL "
            "ORDER BY id DESC LIMIT ?",
            (SHORT_TERM_LIMIT,),
        ).fetchall()
        # Reverse so oldest is first
        self._short_term = [
            {"role": r["role"], "content": r["content"]} for r in reversed(rows)
        ]

    # ── Short-term API ───────────────────────────────────────────────

    def add_message(
        self,
        role: str,
        content: str,
        source: str = "gui",
        conversation_id: int | None = None,
    ) -> None:
        """Append a message to memory and persist it.

        Args:
            role: ``user``, ``assistant``, ``system``, or ``tool``.
            content: Message text.
            source: Origin channel (``gui``, ``discord``, ``system``).
            conversation_id: Thread the message belongs to. Without one the
                message goes to the global rolling window (Discord path).
        """
        if conversation_id is None:
            self._short_term.append({"role": role, "content": content})
            if len(self._short_term) > SHORT_TERM_LIMIT:
                self._short_term = self._short_term[-SHORT_TERM_LIMIT:]

        now = _now()
        self._conn.execute(
            "INSERT INTO messages (role, content, source, created_at, conversation_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (role, content, source, now, conversation_id),
        )
        if conversation_id is not None:
            self._conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
            )
        self._conn.commit()

    def get_context(self, conversation_id: int | None = None) -> list[dict[str, Any]]:
        """Return the recent window for a conversation (or the global one)."""
        if conversation_id is None:
            return list(self._short_term)
        rows = self._conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (conversation_id, SHORT_TERM_LIMIT),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    # ── Conversations ────────────────────────────────────────────────

    def create_conversation(self, title: str = "New chat") -> dict[str, Any]:
        """Create a conversation thread and return it."""
        now = _now()
        cur = self._conn.execute(
            "INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)",
            (title[:80] or "New chat", now, now),
        )
        self._conn.commit()
        return self.get_conversation(cur.lastrowid)  # type: ignore[arg-type]

    def get_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        """Return one conversation row, or None."""
        row = self._conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_conversations(self, query: str = "", limit: int = 200) -> list[dict[str, Any]]:
        """List conversations (pinned first, newest first), optionally searched.

        Args:
            query: Matches titles and message content (case-insensitive).
            limit: Maximum rows.
        """
        sql = (
            "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id "
            "AND m.role IN ('user','assistant')) AS message_count FROM conversations c"
        )
        args: list[Any] = []
        if query:
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
        if title is not None:
            self._conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (title.strip()[:80] or "Untitled", conversation_id),
            )
        if pinned is not None:
            self._conn.execute(
                "UPDATE conversations SET pinned = ? WHERE id = ?", (int(pinned), conversation_id)
            )
        self._conn.commit()
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: int) -> None:
        """Delete a conversation and its messages."""
        self._conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        self._conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        self._conn.commit()

    def get_conversation_messages(self, conversation_id: int) -> list[dict[str, Any]]:
        """Return all user/assistant messages of a conversation, oldest first."""
        rows = self._conn.execute(
            "SELECT role, content, created_at FROM messages WHERE conversation_id = ? "
            "AND role IN ('user','assistant') ORDER BY id",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Usage ────────────────────────────────────────────────────────

    def record_usage(self, **fields: Any) -> None:
        """Persist one agent request's token/time stats (see ``usage`` table)."""
        fields.setdefault("created_at", _now())
        keys = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        self._conn.execute(f"INSERT INTO usage ({keys}) VALUES ({marks})", tuple(fields.values()))
        self._conn.commit()

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
                    f"SELECT model, {agg} FROM usage WHERE created_at >= ? "
                    "GROUP BY model ORDER BY requests DESC", (since,)
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
                    "LEFT JOIN conversations c ON c.id = u.conversation_id "
                    "ORDER BY u.id DESC LIMIT ?", (recent,)
                )
            ],
            "conversations": q("SELECT COUNT(*) FROM conversations").fetchone()[0],
        }

    def clear_short_term(self) -> None:
        """Wipe the in-memory conversation window (does not touch SQLite)."""
        self._short_term.clear()
        logger.info("Short-term memory cleared")

    # ── Long-term facts ──────────────────────────────────────────────

    def set_fact(self, key: str, value: str) -> None:
        """Store (or update) a named long-term fact about the user."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO facts (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                           updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        self._conn.commit()
        logger.info("Fact saved: %s = %s", key, value)

    def get_fact(self, key: str) -> str | None:
        """Retrieve a long-term fact by key, or None if missing."""
        row = self._conn.execute(
            "SELECT value FROM facts WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def get_all_facts(self) -> dict[str, str]:
        """Return every stored fact as a key→value mapping."""
        rows = self._conn.execute("SELECT key, value FROM facts").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def facts_as_system_prompt(self) -> str:
        """Format all facts into a system-prompt snippet for the LLM."""
        facts = self.get_all_facts()
        if not facts:
            return ""
        lines = [f"- {k}: {v}" for k, v in facts.items()]
        return "Known facts about the user:\n" + "\n".join(lines)

    # ── History queries ──────────────────────────────────────────────

    def get_history(
        self,
        limit: int = 50,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent messages from the database.

        Args:
            limit: Maximum number of messages.
            source: Optional filter by channel (``gui``, ``discord``).
        """
        if source:
            rows = self._conn.execute(
                "SELECT role, content, source, created_at FROM messages "
                "WHERE source = ? ORDER BY id DESC LIMIT ?",
                (source, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT role, content, source, created_at FROM messages "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def close(self) -> None:
        """Close the SQLite connection."""
        self._conn.close()
        logger.info("MemoryManager closed")
