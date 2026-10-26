"""
Tool · WhatsApp
===============
Two delivery modes:

* **Cloud API** — if ``WHATSAPP_TOKEN`` and ``WHATSAPP_PHONE_ID`` are set,
  messages are sent directly through Meta's WhatsApp Business Cloud API.
* **Desktop** — otherwise the WhatsApp desktop app is opened with the chat
  and text pre-filled; the user presses Enter to send.
"""

from __future__ import annotations

import logging
import re
import subprocess
from urllib.parse import quote

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com/v21.0/{phone_id}/messages"


def _normalise(phone: str) -> str:
    """Strip everything but digits (international format, no '+')."""
    return re.sub(r"\D", "", phone)


def send_whatsapp(to: str, text: str) -> str:
    """Send a WhatsApp message to a phone number in international format."""
    number = _normalise(to)
    if len(number) < 8:
        return "Error: provide a full international phone number (e.g. +39 333 1234567). Use find_contact to look it up."

    cfg = get_settings().whatsapp
    if cfg.token and cfg.phone_id:
        try:
            resp = httpx.post(
                GRAPH_URL.format(phone_id=cfg.phone_id),
                headers={"Authorization": f"Bearer {cfg.token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": number,
                    "type": "text",
                    "text": {"body": text},
                },
                timeout=20,
            )
        except httpx.HTTPError as exc:
            return f"Error: WhatsApp API unreachable: {exc}"
        if resp.status_code >= 400:
            return f"Error: WhatsApp API {resp.status_code}: {resp.text[:300]}"
        return f"WhatsApp message sent to +{number}."

    url = f"whatsapp://send?phone={number}&text={quote(text)}"
    try:
        subprocess.run(["open", url], check=True, timeout=10)
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        return f"Error: could not open WhatsApp desktop: {exc}"
    return f"WhatsApp opened with a draft to +{number} — press Enter in WhatsApp to send."


TOOL_DESCRIPTORS = [
    {
        "name": "send_whatsapp",
        "description": (
            "Send a WhatsApp message. Needs an international phone number; "
            "use find_contact to resolve a name first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Phone number, e.g. +393331234567"},
                "text": {"type": "string"},
            },
            "required": ["to", "text"],
        },
    },
]

TOOLS = {"send_whatsapp": send_whatsapp}
