"""
Core · Approvals
================
Actions that reach other people or can't be undone (sending email and
messages, pushing code, deleting things, running shortcuts…) are not run on
the model's say-so. The agent asks first: the chat shows an approval card
with the exact arguments, and the run waits for the user's answer.

"Always allow" for a tool is stored in ``APPROVAL_ALWAYS`` (.env). Runs nobody
is watching (automations, Discord without an answer) only run sensitive tools
that are always allowed.
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any

from config.settings import get_settings, reload_settings, save_settings_to_env

# Tool name → what the user sees on the card / in Settings → Permissions
SENSITIVE: dict[str, str] = {
    "send_email": "Send email (Gmail)",
    "gmail_create_draft": "Save Gmail drafts",
    "send_mail_app": "Send email (Apple Mail)",
    "send_imessage": "Send iMessages",
    "send_whatsapp": "Send WhatsApp messages",
    "delete_calendar_event": "Delete calendar events",
    "delete_reminder": "Delete reminders",
    "delete_automation": "Delete automations",
    "write_file": "Overwrite files in the code workspace",
    "git_commit": "Commit code",
    "git_push": "Push code",
    "github_create_issue": "Open GitHub issues",
    "github_create_pull_request": "Open GitHub pull requests",
    "run_shortcut": "Run Apple Shortcuts",
}

# MCP tools that don't declare themselves read-only are registered here at runtime
_dynamic: dict[str, str] = {}
_pending: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
WAIT_S = 600


def register(name: str, label: str) -> None:
    """Mark a tool (e.g. from an MCP server) as needing approval."""
    _dynamic[name] = label


def label(name: str) -> str:
    return SENSITIVE.get(name) or _dynamic.get(name) or name


def is_sensitive(name: str) -> bool:
    return name in SENSITIVE or name in _dynamic


def always(name: str) -> bool:
    return name in get_settings().always_allowed


def needs_approval(name: str) -> bool:
    return is_sensitive(name) and not always(name)


def set_always(name: str, on: bool) -> None:
    allowed = set(get_settings().always_allowed)
    (allowed.add if on else allowed.discard)(name)
    save_settings_to_env({"APPROVAL_ALWAYS": ",".join(sorted(allowed))})
    reload_settings()


def policy() -> list[dict[str, Any]]:
    """Every sensitive tool with its "always allow" state (Settings → Permissions)."""
    return [{"tool": t, "label": l, "always": always(t)} for t, l in {**SENSITIVE, **_dynamic}.items()]


def create(name: str, args: dict[str, Any], conversation_id: int | None) -> str:
    """Open a pending approval and return its id."""
    aid = secrets.token_urlsafe(8)
    with _lock:
        _pending[aid] = {"id": aid, "name": name, "args": args, "conversation_id": conversation_id,
                         "event": threading.Event(), "allow": False}
    return aid


def resolve(aid: str, allow: bool, remember: bool = False) -> bool:
    """Answer a pending approval (from the UI); False if it no longer exists."""
    with _lock:
        p = _pending.get(aid)
    if not p:
        return False
    if allow and remember:
        set_always(p["name"], True)
    p["allow"] = allow
    p["event"].set()
    return True


def wait(aid: str, cancel: threading.Event | None = None, timeout: float = WAIT_S) -> bool:
    """Block until the user answers (False on deny, timeout or cancel)."""
    p = _pending.get(aid)
    if not p:
        return False
    end = time.monotonic() + timeout
    try:
        while time.monotonic() < end:
            if p["event"].wait(0.25):
                return bool(p["allow"])
            if cancel is not None and cancel.is_set():
                return False
        return False
    finally:
        with _lock:
            _pending.pop(aid, None)


def pending(conversation_id: int | None = None) -> list[dict[str, Any]]:
    """Open approvals (to restore the card after the page reloads)."""
    with _lock:
        return [
            {k: p[k] for k in ("id", "name", "args", "conversation_id")} | {"label": label(p["name"])}
            for p in _pending.values()
            if conversation_id is None or p["conversation_id"] == conversation_id
        ]
