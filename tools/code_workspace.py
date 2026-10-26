"""
Tool · Code Workspace (coding agent)
====================================
Read, edit, commit and push code inside a local git repository.
All paths are confined to the active workspace (``CODE_WORKSPACE`` in
``.env``, switchable at runtime with ``set_workspace``).
"""

from __future__ import annotations

import base64
import logging
import subprocess
from pathlib import Path

from config.settings import get_settings, reload_settings, save_settings_to_env

logger = logging.getLogger(__name__)

MAX_READ = 60_000
_SKIP = {".git", "node_modules", ".next", "__pycache__", ".venv", "venv", "dist", "build"}


def _root() -> Path | None:
    p = get_settings().code.workspace
    return Path(p).expanduser().resolve() if p else None


def _safe(rel: str) -> Path:
    """Resolve *rel* inside the workspace, refusing escapes."""
    root = _root()
    if root is None:
        raise ValueError("No workspace set. Ask the user for a repo folder and call set_workspace.")
    path = (root / rel).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"Path '{rel}' is outside the workspace.")
    return path


def _git(*args: str, timeout: int = 60) -> str:
    """Run git in the workspace and return combined output."""
    root = _root()
    if root is None:
        return "Error: no workspace set."
    cfg = get_settings().github
    pre: list[str] = []
    if cfg.token:  # authenticate HTTPS pushes/pulls to github.com
        basic = base64.b64encode(f"x-access-token:{cfg.token}".encode()).decode()
        pre = ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}"]
    try:
        r = subprocess.run(["git", *pre, *args], cwd=root, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "Error: git timed out."
    except FileNotFoundError:
        return "Error: git is not installed."
    out = (r.stdout + r.stderr).strip()
    return out if r.returncode == 0 else f"Error (git {args[0]}): {out}"


def _guard(fn):
    """Turn ValueError/OSError into readable tool errors."""
    def wrap(*a, **kw):
        try:
            return fn(*a, **kw)
        except (ValueError, OSError) as exc:
            return f"Error: {exc}"
    wrap.__doc__ = fn.__doc__
    return wrap


# ── Public tools ─────────────────────────────────────────────────────

@_guard
def set_workspace(path: str) -> str:
    """Point the coding agent at a local folder containing a git repo."""
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        return f"Error: {p} is not a directory."
    if not (p / ".git").exists():
        return f"Error: {p} is not a git repository (run `git init` first)."
    save_settings_to_env({"CODE_WORKSPACE": str(p)})
    reload_settings()
    return f"Workspace set to {p}. Branch: {_git('branch', '--show-current')}"


@_guard
def list_files(path: str = ".", depth: int = 3) -> str:
    """List files under *path* (relative to the workspace), skipping build dirs."""
    base = _safe(path)
    root = _root()
    out: list[str] = []
    def walk(d: Path, lvl: int) -> None:
        for e in sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name)):
            if e.name in _SKIP or len(out) > 400:
                continue
            out.append(str(e.relative_to(root)) + ("/" if e.is_dir() else ""))
            if e.is_dir() and lvl < depth:
                walk(e, lvl + 1)
    walk(base, 1)
    return "\n".join(out) or "(empty)"


@_guard
def read_file(path: str, start_line: int = 1, end_line: int = 0) -> str:
    """Read a text file with line numbers (optionally a line range)."""
    lines = _safe(path).read_text(encoding="utf-8", errors="replace").splitlines()
    end = end_line or len(lines)
    body = "\n".join(f"{i:>5}  {l}" for i, l in enumerate(lines[start_line - 1:end], start_line))
    return body[:MAX_READ] + ("\n…(truncated)" if len(body) > MAX_READ else "")


@_guard
def write_file(path: str, content: str) -> str:
    """Create or overwrite a file with *content*."""
    p = _safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {path} ({len(content.splitlines())} lines)."


@_guard
def edit_file(path: str, old: str, new: str) -> str:
    """Replace one exact occurrence of *old* with *new* in a file."""
    p = _safe(path)
    text = p.read_text(encoding="utf-8")
    n = text.count(old)
    if n != 1:
        return f"Error: expected exactly 1 match of the old text, found {n}. Read the file and retry with a unique snippet."
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"Edited {path}."


@_guard
def search_code(query: str) -> str:
    """Search tracked files for a string (git grep)."""
    return _git("grep", "-n", "-I", "--", query)[:MAX_READ] or "No matches."


def git_status() -> str:
    """Show branch, changed files and short diff stats."""
    return _git("status", "-sb") + "\n\n" + _git("diff", "--stat")


def git_diff(path: str = "") -> str:
    """Show the unstaged + staged diff (optionally for one path)."""
    args = ["diff", "HEAD"] + (["--", path] if path else [])
    return _git(*args)[:MAX_READ] or "No changes."


def git_log(limit: int = 10) -> str:
    """Show recent commits."""
    return _git("log", f"-{int(limit)}", "--oneline", "--decorate")


def git_checkout(branch: str, create: bool = False) -> str:
    """Switch to (or create) a branch."""
    return _git("checkout", *(["-b"] if create else []), branch)


def git_commit(message: str) -> str:
    """Stage all changes and commit them with *message*."""
    add = _git("add", "-A")
    if add.startswith("Error"):
        return add
    return _git("commit", "-m", message)


def git_push(remote: str = "origin", branch: str = "") -> str:
    """Push the current (or given) branch to the remote, setting upstream."""
    branch = branch or _git("branch", "--show-current")
    return _git("push", "-u", remote, branch, timeout=120) or f"Pushed {branch} to {remote}."


def git_pull(remote: str = "origin") -> str:
    """Pull (rebase) from the remote."""
    return _git("pull", "--rebase", remote, timeout=120)


TOOLS = {
    "set_workspace": set_workspace, "list_files": list_files, "read_file": read_file,
    "write_file": write_file, "edit_file": edit_file, "search_code": search_code,
    "git_status": git_status, "git_diff": git_diff, "git_log": git_log,
    "git_checkout": git_checkout, "git_commit": git_commit, "git_push": git_push, "git_pull": git_pull,
}


def _d(name: str, desc: str, props: dict | None = None, req: list[str] | None = None) -> dict:
    return {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": req or []}}


_S = {"type": "string"}
TOOL_DESCRIPTORS = [
    _d("set_workspace", "Set the local git repo folder the coding agent works in.", {"path": _S}, ["path"]),
    _d("list_files", "List files in the workspace.", {"path": _S, "depth": {"type": "integer"}}),
    _d("read_file", "Read a workspace file with line numbers.",
       {"path": _S, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, ["path"]),
    _d("write_file", "Create or fully overwrite a workspace file.", {"path": _S, "content": _S}, ["path", "content"]),
    _d("edit_file", "Replace one exact, unique snippet in a file. Read the file first.",
       {"path": _S, "old": _S, "new": _S}, ["path", "old", "new"]),
    _d("search_code", "Search the repo for a string.", {"query": _S}, ["query"]),
    _d("git_status", "Show git status of the workspace."),
    _d("git_diff", "Show the current diff.", {"path": _S}),
    _d("git_log", "Show recent commits.", {"limit": {"type": "integer"}}),
    _d("git_checkout", "Switch to or create a branch.", {"branch": _S, "create": {"type": "boolean"}}, ["branch"]),
    _d("git_commit", "Stage all changes and commit. Only when the user asked to commit.", {"message": _S}, ["message"]),
    _d("git_push", "Push the branch to the remote. Only when the user asked to push.", {"remote": _S, "branch": _S}),
    _d("git_pull", "Pull latest changes (rebase).", {"remote": _S}),
]
