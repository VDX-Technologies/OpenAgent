"""
Tool · Apple Contacts (macOS)
=============================
Look up phone numbers and emails in Contacts.app so other connectors
(Messages, WhatsApp, Mail) can address people by name.
"""

from __future__ import annotations

from tools._applescript import esc, run_applescript


def find_contact(name: str) -> str:
    """Return phones and emails of contacts whose name contains *name*."""
    script = f'''
    tell application "Contacts"
        set found to (every person whose name contains "{esc(name)}")
        set output to ""
        repeat with p in found
            set output to output & (name of p) & ": "
            repeat with ph in phones of p
                set output to output & (value of ph) & " "
            end repeat
            repeat with em in emails of p
                set output to output & (value of em) & " "
            end repeat
            set output to output & linefeed
        end repeat
    end tell
    return output
    '''
    return run_applescript(script) or f"No contact matching '{name}'."


TOOL_DESCRIPTORS = [
    {
        "name": "find_contact",
        "description": "Search macOS Contacts by name; returns phone numbers and emails.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Full or partial name"}},
            "required": ["name"],
        },
    },
]

TOOLS = {"find_contact": find_contact}
