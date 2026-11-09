"""
Tool · Apple Reminders (macOS)
==============================
Create, list, complete and delete reminders in Reminders.app. Reads go
through EventKit when VDX has access (instant), otherwise AppleScript.
"""

from __future__ import annotations

import logging
from datetime import datetime

from tools import _eventkit
from tools._applescript import esc, run_applescript
from tools.apple_calendar import _date_expr

logger = logging.getLogger(__name__)


def _list_ref(name: str) -> str:
    """AppleScript reference to the named list, or the default one."""
    return f'list "{esc(name)}"' if name and name.lower() != "reminders" else "default list"


def add_reminder(title: str, list_name: str = "", notes: str = "", due_date: datetime | None = None) -> str:
    """Create a new reminder (in the default list unless one is named)."""
    due = _date_expr("dueD", due_date) if due_date else ""
    props = f'name:"{esc(title)}", body:"{esc(notes)}"' + (", due date:dueD" if due_date else "")
    script = due + f'''
    tell application "Reminders"
        tell {_list_ref(list_name)}
            make new reminder with properties {{{props}}}
            set listName to name
        end tell
    end tell
    return "Reminder created: {esc(title)} in " & listName
    '''
    logger.info("Creating reminder: %s", title)
    return run_applescript(script, timeout=60)


def list_reminders(list_name: str = "", show_completed: bool = False) -> str:
    """Open (or completed) reminders, from every list unless one is named."""
    if _eventkit.ready("reminder"):
        try:
            items = _eventkit.reminders(list_name, show_completed)
            return "\n".join(
                f"• {r['title']} [{r['list']}]" + (f" — due {r['due']:%Y-%m-%d %H:%M}" if r["due"] else "")
                for r in items[:100]
            ) or "No reminders found."
        except ValueError as exc:
            return f"Error: {exc}"
        except Exception:
            logger.warning("EventKit read failed, using AppleScript", exc_info=True)
    filt = "" if show_completed else "whose completed is false"
    lists = f"{{{_list_ref(list_name)}}}" if list_name else "lists"
    script = f'''
    set output to ""
    tell application "Reminders"
        repeat with l in {lists}
            repeat with r in (every reminder of l {filt})
                set output to output & "• " & (name of r) & " [" & (name of l) & "]" & linefeed
            end repeat
        end repeat
    end tell
    return output
    '''
    return run_applescript(script, timeout=60) or "No reminders found."


def _first_match(action: str, done_text: str, title: str, list_name: str) -> str:
    lists = f"{{{_list_ref(list_name)}}}" if list_name else "lists"
    script = f'''
    tell application "Reminders"
        repeat with l in {lists}
            set found to (every reminder of l whose name is "{esc(title)}" and completed is false)
            if (count of found) > 0 then
                {action.format(item="item 1 of found")}
                return "{done_text}: {esc(title)}"
            end if
        end repeat
    end tell
    return "No open reminder found with title: {esc(title)}"
    '''
    return run_applescript(script, timeout=60)


def complete_reminder(title: str, list_name: str = "") -> str:
    """Mark the first open reminder matching *title* as completed."""
    return _first_match("set completed of {item} to true", "Completed reminder", title, list_name)


def delete_reminder(title: str, list_name: str = "") -> str:
    """Delete the first open reminder matching *title*."""
    return _first_match("delete {item}", "Deleted reminder", title, list_name)


TOOL_DESCRIPTORS = [
    {
        "name": "add_reminder",
        "description": "Create a reminder in Apple Reminders. Optional list name, notes and due date (ISO 8601).",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Reminder title"},
                "list_name": {"type": "string", "description": "Omit for the default list"},
                "notes": {"type": "string"},
                "due_date": {"type": "string", "description": "Due date in ISO 8601 format"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List open reminders from Apple Reminders (all lists unless one is named).",
        "parameters": {
            "type": "object",
            "properties": {"list_name": {"type": "string"}, "show_completed": {"type": "boolean"}},
        },
    },
    {
        "name": "complete_reminder",
        "description": "Mark a reminder as completed by its exact title.",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "list_name": {"type": "string"}},
                       "required": ["title"]},
    },
    {
        "name": "delete_reminder",
        "description": "Delete a reminder by its exact title.",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "list_name": {"type": "string"}},
                       "required": ["title"]},
    },
]
