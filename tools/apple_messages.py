"""
Tool · Apple Messages (macOS)
=============================
Send iMessage / SMS through Messages.app via AppleScript.
"""

from __future__ import annotations

from tools._applescript import esc, run_applescript


def send_imessage(to: str, text: str) -> str:
    """Send an iMessage to a phone number or Apple ID email."""
    script = f'''
    tell application "Messages"
        set svc to 1st account whose service type = iMessage
        set buddyRef to participant "{esc(to)}" of svc
        send "{esc(text)}" to buddyRef
    end tell
    return "iMessage sent to {esc(to)}."
    '''
    return run_applescript(script)


TOOL_DESCRIPTORS = [
    {
        "name": "send_imessage",
        "description": "Send an iMessage via macOS Messages.app. Use find_contact first to resolve names.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Phone number (+39…) or Apple ID email"},
                "text": {"type": "string"},
            },
            "required": ["to", "text"],
        },
    },
]

TOOLS = {"send_imessage": send_imessage}
