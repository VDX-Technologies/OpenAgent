"""
Tool · Local files
==================
* Text extraction for files attached to a chat message (PDF, Word, text and code).
* A local knowledge index: folders the user adds are split into chunks and
  embedded with an Ollama embedding model, so VDX can search them by meaning
  (``search_files``). Without the embedding model it falls back to keyword search.
"""

from __future__ import annotations

import io
import logging
import os
import re
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TEXT_EXT = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".ini", ".xml", ".html",
    ".htm", ".py", ".js", ".ts", ".tsx", ".jsx", ".svelte", ".vue", ".java", ".kt", ".swift", ".go", ".rs", ".c",
    ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".sh", ".sql", ".css", ".scss", ".tex", ".log", ".env.example",
}
DOC_EXT = {".pdf", ".docx"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "Library", ".Trash"}
MAX_FILES = 3000
MAX_FILE_BYTES = 20_000_000
CHUNK, OVERLAP = 1200, 200

_llm: Any = None  # OllamaClient, set by the API on startup
_status: dict[str, Any] = {"running": False, "path": "", "done": 0, "total": 0, "error": ""}
_matrix: dict[str, Any] = {"ids": None, "vecs": None}
_lock = threading.Lock()


# ── Text extraction ──────────────────────────────────────────────────

def extract_text(name: str, data: bytes) -> str:
    """Readable text of a file (PDF, .docx, or anything that decodes as text)."""
    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return "(PDF support needs pypdf: .venv/bin/pip install pypdf)"
        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join((p.extract_text() or "") for p in reader.pages[:300]).strip()
        except Exception as exc:
            return f"(could not read this PDF: {exc})"
    if ext == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            return re.sub(r"<[^>]+>", "", xml).strip()
        except Exception as exc:
            return f"(could not read this document: {exc})"
    if b"\x00" in data[:4096]:
        return "(binary file — no readable text)"
    return data.decode("utf-8", errors="replace").strip()


# ── Knowledge index ──────────────────────────────────────────────────

def _conn() -> Any:
    from core import memory

    if memory._active is None:
        raise RuntimeError("memory not ready")
    c = memory._active._conn
    if _status.get("schema") is c:
        return c
    _status["schema"] = c
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_roots (path TEXT PRIMARY KEY, added_at TEXT, files INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT, root TEXT, path TEXT, mtime REAL, chunk INTEGER,
            text TEXT, vector BLOB);
        CREATE INDEX IF NOT EXISTS idx_knowledge_path ON knowledge(path);
        """
    )
    return c


def _chunks(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text)
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + CHUNK])
        i += CHUNK - OVERLAP
    return [c for c in out if c.strip()]


def _files(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for f in filenames:
            p = Path(dirpath) / f
            if p.suffix.lower() in TEXT_EXT | DOC_EXT:
                found.append(p)
                if len(found) >= MAX_FILES:
                    return found
    return found


def _embed(texts: list[str]) -> list[list[float]] | None:
    if _llm is None:
        return None
    try:
        return _llm.embed(texts)
    except Exception as exc:
        logger.info("Embedding unavailable, keyword search only: %s", exc)
        return None


def _index(root: Path) -> None:
    import numpy as np

    c = _conn()
    files = _files(root)
    _status.update(running=True, path=str(root), done=0, total=len(files), error="")
    embed_ok = True
    try:
        for p in files:
            try:
                st = p.stat()
                if st.st_size > MAX_FILE_BYTES:
                    continue
                row = c.execute("SELECT mtime FROM knowledge WHERE path = ? LIMIT 1", (str(p),)).fetchone()
                if row and abs(row[0] - st.st_mtime) < 1:
                    continue  # unchanged since last index
                pieces = _chunks(extract_text(p.name, p.read_bytes()))
                vecs = _embed([f"{p.name}\n{t}" for t in pieces]) if pieces and embed_ok else None
                if pieces and vecs is None:
                    embed_ok = False
                with c.transaction():
                    c.execute("DELETE FROM knowledge WHERE path = ?", (str(p),))
                    for i, t in enumerate(pieces):
                        blob = np.asarray(vecs[i], dtype=np.float32).tobytes() if vecs else None
                        c.execute("INSERT INTO knowledge (root, path, mtime, chunk, text, vector) VALUES (?,?,?,?,?,?)",
                                  (str(root), str(p), st.st_mtime, i, t, blob))
            except Exception:
                logger.debug("Could not index %s", p, exc_info=True)
            finally:
                _status["done"] += 1
        with c.transaction():
            c.execute("UPDATE knowledge_roots SET files = ? WHERE path = ?", (len(files), str(root)))
        if not embed_ok:
            _status["error"] = "Indexed for keyword search only — install the 'nomic-embed-text' model in Models for search by meaning."
    except Exception as exc:
        logger.exception("Indexing %s failed", root)
        _status["error"] = str(exc)
    finally:
        _status["running"] = False
        _matrix["ids"] = None


def add_folder(path: str) -> str:
    """Add a folder to the knowledge index (indexed in the background)."""
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        return f"Error: {root} is not a folder."
    if _status["running"]:
        return f"Error: still indexing {_status['path']} — try again when it finishes."
    c = _conn()
    with c.transaction():
        c.execute("INSERT OR IGNORE INTO knowledge_roots (path, added_at) VALUES (?, ?)", (str(root), time.strftime("%Y-%m-%d %H:%M")))
    threading.Thread(target=_index, args=(root,), name="vdx-index", daemon=True).start()
    return f"Indexing {root} in the background — search it with search_files in a minute."


def remove_folder(path: str) -> None:
    c = _conn()
    with c.transaction():
        c.execute("DELETE FROM knowledge WHERE root = ?", (path,))
        c.execute("DELETE FROM knowledge_roots WHERE path = ?", (path,))
    _matrix["ids"] = None


def folders() -> dict[str, Any]:
    c = _conn()
    roots = [dict(r) for r in c.execute(
        "SELECT r.path, r.added_at, r.files, (SELECT COUNT(*) FROM knowledge k WHERE k.root = r.path) AS chunks "
        "FROM knowledge_roots r ORDER BY r.added_at DESC")]
    return {"folders": roots, "status": {k: v for k, v in _status.items() if k != "schema"}}


def reindex_all() -> None:
    """Pick up changed files in every indexed folder (run on startup)."""
    def run() -> None:
        for r in _conn().execute("SELECT path FROM knowledge_roots").fetchall():
            if Path(r[0]).is_dir():
                _index(Path(r[0]))
    threading.Thread(target=run, name="vdx-reindex", daemon=True).start()


def search_files(query: str, limit: int = 5) -> str:
    """Passages of the user's indexed files that best match *query*."""
    import numpy as np

    c = _conn()
    if not c.execute("SELECT 1 FROM knowledge LIMIT 1").fetchone():
        return "No files indexed yet. The user can add folders in Memory → Files, or ask you to index one (index_folder)."
    limit = max(1, min(int(limit), 10))
    hits: list[tuple[float, str, str]] = []
    qv = _embed([query])
    if qv:
        with _lock:
            if _matrix["ids"] is None:
                rows = c.execute("SELECT id, vector FROM knowledge WHERE vector IS NOT NULL").fetchall()
                _matrix["ids"] = [r[0] for r in rows]
                vecs = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows]) if rows else np.zeros((0, 1))
                norms = np.linalg.norm(vecs, axis=1, keepdims=True) if len(rows) else 1
                _matrix["vecs"] = vecs / np.maximum(norms, 1e-9)
            ids, vecs = _matrix["ids"], _matrix["vecs"]
        if ids:
            q = np.asarray(qv[0], dtype=np.float32)
            if q.shape[0] == vecs.shape[1]:
                scores = vecs @ (q / max(float(np.linalg.norm(q)), 1e-9))
                for i in np.argsort(-scores)[:limit]:
                    row = c.execute("SELECT path, text FROM knowledge WHERE id = ?", (ids[int(i)],)).fetchone()
                    if row:
                        hits.append((float(scores[int(i)]), row[0], row[1]))
    if not hits:
        terms = [t for t in re.findall(r"\w{3,}", query.lower())][:6]
        if terms:
            score = " + ".join("(instr(lower(text), ?) > 0)" for _ in terms)
            rows = c.execute(f"SELECT path, text, ({score}) AS s FROM knowledge WHERE s > 0 ORDER BY s DESC LIMIT ?",
                             (*terms, limit)).fetchall()
            hits = [(float(r[2]), r[0], r[1]) for r in rows]
    if not hits:
        return f"Nothing in the indexed files matches '{query}'."
    return "\n\n".join(f"[{i + 1}] {p}\n{t.strip()[:1100]}" for i, (_, p, t) in enumerate(hits))


def index_folder(path: str) -> str:
    return add_folder(path)


def list_indexed_folders() -> str:
    roots = folders()["folders"]
    return "\n".join(f"{r['path']} ({r['files']} files)" for r in roots) or "No folders indexed."


TOOL_DESCRIPTORS = [
    {"name": "search_files", "description": "Search the user's indexed local files (documents, notes, code) and return matching passages with their paths.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}},
    {"name": "index_folder", "description": "Add a local folder to the searchable file index.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "list_indexed_folders", "description": "List folders in the file index.",
     "parameters": {"type": "object", "properties": {}}},
]

TOOLS = {"search_files": search_files, "index_folder": index_folder, "list_indexed_folders": list_indexed_folders}
