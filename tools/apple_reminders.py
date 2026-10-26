"""
Tool · Apple Reminders (macOS)
===============================
Create, list, and complete reminders in the native Reminders.app
using AppleScript via the `osascript` subprocess.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────

def _run_applescript(script: str) -> str:
    """Execute an AppleScript snippet and return its stdout."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error("AppleScript error (Reminders): %s", result.stderr.strip())
            return f"Error: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.error("AppleScript timed out (Reminders)")
        return "Error: AppleScript execution timed out."
    except FileNotFoundError:
        logger.error("osascript not found — are you on macOS?")
        return "Error: osascript not found. This tool requires macOS."


# ── Public API ───────────────────────────────────────────────────────

def add_reminder(
    title: str,
    list_name: str = "Reminders",
    notes: str = "",
    due_date: datetime | None = None,
) -> str:
    """Create a new reminder in Apple Reminders.app."""
    due_clause = ""
    if due_date:
        due_str = due_date.strftime("%B %d, %Y at %I:%M:%S %p")
        due_clause = f', due date:date "{due_str}"'

    script = f'''
    tell application "Reminders"
        tell list "{list_name}"
            make new reminder with properties {{
                name:"{title}", ¬
                body:"{notes}"{due_clause}
            }}
        end tell
    end tell
    return "Reminder created: {title}"
    '''
    logger.info("Creating reminder: %s", title)
    return _run_applescript(script)


def list_reminders(list_name: str = "Reminders", show_completed: bool = False) -> str:
    """Return a newline-separated list of reminders."""
    completed_filter = "" if show_completed else "whose completed is false"
    script = f'''
    tell application "Reminders"
        tell list "{list_name}"
            set rems to (every reminder {completed_filter})
            set output to ""
            repeat with r in rems
                set output to output & "• " & (name of r) & linefeed
            end repeat
        end tell
    end tell
    return output
    '''
    logger.info("Listing reminders from list: %s", list_name)
    return _run_applescript(script) or "No reminders found."


def complete_reminder(title: str, list_name: str = "Reminders") -> str:
    """Mark the first reminder matching *title* as completed."""
    script = f'''
    tell application "Reminders"
        tell list "{list_name}"
            set matchingReminders to (every reminder whose name is "{title}")
            if (count of matchingReminders) > 0 then
                set completed of item 1 of matchingReminders to true
                return "Completed reminder: {title}"
            else
                return "No reminder found with title: {title}"
            end if
        end tell
    end tell
    '''
    logger.info("Completing reminder: %s", title)
    return _run_applescript(script)


def delete_reminder(title: str, list_name: str = "Reminders") -> str:
    """Delete the first reminder matching *title*."""
    script = f'''
    tell application "Reminders"
        tell list "{list_name}"
            set matchingReminders to (every reminder whose name is "{title}")
            if (count of matchingReminders) > 0 then
                delete item 1 of matchingReminders
                return "Deleted reminder: {title}"
            else
                return "No reminder found with title: {title}"
            end if
        end tell
    end tell
    '''
    logger.info("Deleting reminder: %s", title)
    return _run_applescript(script)


# ── Tool descriptor (used by the Agent for function-calling) ────────

TOOL_DESCRIPTORS = [
    {
        "name": "add_reminder",
        "description": (
            "Create a new reminder in Apple Reminders.app. "
            "Provide a title and optionally a list name, notes, and due date (ISO 8601)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Reminder title"},
                "list_name": {"type": "string", "default": "Reminders"},
                "notes": {"type": "string", "default": ""},
                "due_date": {"type": "string", "description": "Due date in ISO 8601 format"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List current (incomplete) reminders from Apple Reminders.app.",
        "parameters": {
            "type": "object",
            "properties": {
                "list_name": {"type": "string", "default": "Reminders"},
                "show_completed": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "complete_reminder",
        "description": "Mark a reminder as completed by its exact title.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "list_name": {"type": "string", "default": "Reminders"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "delete_reminder",
        "description": "Delete a reminder by its exact title.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "list_name": {"type": "string", "default": "Reminders"},
            },
            "required": ["title"],
        },
    },
]
