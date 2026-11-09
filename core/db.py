"""
Core · Thread-safe SQLite
=========================
The API, the scheduler, the Discord bot and telemetry threads all share one
SQLite connection. ``LockedConnection`` serialises every statement behind one
lock and fetches the rows while it holds it, so a statement from one thread can
never interleave with (or commit half of) another thread's work.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class Result:
    """Rows of a finished statement (cursor-like: fetchone / fetchall / iteration)."""

    def __init__(self, rows: list[Any], lastrowid: int | None, rowcount: int) -> None:
        self._rows, self.lastrowid, self.rowcount = rows, lastrowid, rowcount

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return list(self._rows)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._rows)


class LockedConnection:
    """A ``sqlite3.Connection`` whose calls are serialised by one re-entrant lock."""

    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()

    def execute(self, sql: str, params: Any = ()) -> Result:
        with self.lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
            return Result(rows, cur.lastrowid, cur.rowcount)

    def executescript(self, script: str) -> None:
        with self.lock:
            self._conn.executescript(script)

    def commit(self) -> None:
        with self.lock:
            self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[LockedConnection]:
        """Run several statements atomically (commit on success, rollback on error)."""
        with self.lock:
            try:
                yield self
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def close(self) -> None:
        with self.lock:
            self._conn.close()
