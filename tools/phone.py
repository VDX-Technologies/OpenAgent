"""
Tool · Phone notifications (ntfy)
=================================
Push a message to the user's phone through ntfy (https://ntfy.sh): install the
ntfy app, subscribe to the topic set in Settings, and every message VDX sends
arrives as a notification. The topic name is the only secret, so it should be
long and random; a self-hosted ntfy server can be used instead of ntfy.sh.
"""

from __future__ import annotations

import logging
import secrets

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)


def new_topic() -> str:
    """A random, hard-to-guess topic name."""
    return f"vdx-{secrets.token_urlsafe(12)}"


def configured() -> bool:
    return bool(get_settings().phone.ntfy_topic)


_PRIORITY = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}


def send_to_phone(message: str, title: str = "VDX", priority: str = "default", url: str = "") -> str:
    """Send a push notification to the user's phone."""
    cfg = get_settings().phone
    if not cfg.ntfy_topic:
        return "Error: no phone topic set — add one in Settings → Phone."
    body = {"topic": cfg.ntfy_topic, "message": message, "title": title or "VDX", "tags": ["robot"],
            "priority": _PRIORITY.get(priority, 3)}
    if url:
        body["click"] = url
    try:  # JSON publishing keeps accents/emoji in the title intact (headers are latin-1 only)
        r = httpx.post(cfg.ntfy_server.rstrip("/"), json=body, timeout=10)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        logger.info("ntfy push failed: %s", exc)
        return f"Error sending to phone: {exc}"
    return "Sent to your phone."


TOOL_DESCRIPTORS = [
    {
        "name": "send_to_phone",
        "description": "Send a push notification to the user's own phone. Use it when the user asks to be "
                       "notified, reminded or sent something on their phone.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Notification text"},
                "title": {"type": "string", "description": "Short title"},
                "priority": {"type": "string", "enum": ["low", "default", "high", "urgent"]},
                "url": {"type": "string", "description": "Optional link to open when tapped"},
            },
            "required": ["message"],
        },
    },
]

TOOLS = {"send_to_phone": send_to_phone}
