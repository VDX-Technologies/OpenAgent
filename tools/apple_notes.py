"""
Tool · Apple Notes (macOS)
==========================
Create and search notes in Notes.app via AppleScript.
"""

from __future__ import annotations

from tools._applescript import esc, run_applescript


def create_note(title: str, body: str) -> str:
    """Create a note in the default Notes account."""
    script = f'''
    tell application "Notes"
        make new note with properties {{name:"{esc(title)}", body:"<h1>{esc(title)}</h1><p>{esc(body)}</p>"}}
    end tell
    return "Note created: {esc(title)}"
    '''
    return run_applescript(script)


def search_notes(query: str, limit: int = 5) -> str:
    """Return title + plaintext excerpt of notes whose name or body contains *query*."""
    limit = max(1, min(int(limit), 20))
    script = f'''
    tell application "Notes"
        set found to (every note whose name contains "{esc(query)}" or plaintext contains "{esc(query)}")
        set n to count of found
        if n > {limit} then set n to {limit}
        set output to ""
        repeat with i from 1 to n
            set nt to item i of found
            set txt to plaintext of nt
            if (length of txt) > 300 then set txt to (text 1 thru 300 of txt) & "…"
            set output to output & "## " & (name of nt) & linefeed & txt & linefeed & linefeed
        end repeat
    end tell
    return output
    '''
    return run_applescript(script, timeout=60) or f"No notes matching '{query}'."


TOOL_DESCRIPTORS = [
    {
        "name": "create_note",
        "description": "Create a new note in macOS Notes.app.",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
            "required": ["title", "body"],
        },
    },
    {
        "name": "search_notes",
        "description": "Search macOS Notes.app by keyword.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "description": "Max notes (default 5)"},
            },
            "required": ["query"],
        },
    },
]

TOOLS = {"create_note": create_note, "search_notes": search_notes}
