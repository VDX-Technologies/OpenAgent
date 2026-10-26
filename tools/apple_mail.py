"""
Tool · Apple Mail (macOS)
=========================
Read the unified inbox and send messages through Mail.app via AppleScript.
Works with every account configured in Mail (iCloud, Outlook, Exchange, …).
"""

from __future__ import annotations

from tools._applescript import esc, run_applescript


def list_mail_inbox(limit: int = 10, unread_only: bool = True) -> str:
    """Return the most recent messages from Mail.app's inbox."""
    limit = max(1, min(int(limit), 50))
    filt = "whose read status is false" if unread_only else ""
    script = f'''
    tell application "Mail"
        set msgs to (messages of inbox {filt})
        set n to count of msgs
        if n > {limit} then set n to {limit}
        set output to ""
        repeat with i from 1 to n
            set m to item i of msgs
            set output to output & "• " & (sender of m) & " — " & (subject of m) & " (" & (date received of m as string) & ")" & linefeed
        end repeat
    end tell
    return output
    '''
    return run_applescript(script, timeout=60) or "No messages found."


def send_mail_app(to: str, subject: str, body: str) -> str:
    """Send an email using the default account in Mail.app."""
    script = f'''
    tell application "Mail"
        set msg to make new outgoing message with properties {{subject:"{esc(subject)}", content:"{esc(body)}", visible:false}}
        tell msg to make new to recipient at end of to recipients with properties {{address:"{esc(to)}"}}
        send msg
    end tell
    return "Mail sent to {esc(to)}."
    '''
    return run_applescript(script)


TOOL_DESCRIPTORS = [
    {
        "name": "list_mail_inbox",
        "description": "List recent emails from the macOS Mail.app inbox (all accounts).",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max messages (default 10)"},
                "unread_only": {"type": "boolean", "description": "Only unread (default true)"},
            },
        },
    },
    {
        "name": "send_mail_app",
        "description": "Send an email via macOS Mail.app using its default account.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
]

TOOLS = {"list_mail_inbox": list_mail_inbox, "send_mail_app": send_mail_app}
