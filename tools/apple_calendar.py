"""
Tool · Apple Calendar (macOS)
==============================
Create, list and delete events in the native Calendar.app
using AppleScript via the `osascript` subprocess.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from tools._applescript import esc, run_applescript

logger = logging.getLogger(__name__)


# ── Data classes ─────────────────────────────────────────────────────

@dataclass
class CalendarEvent:
    """Represents a calendar event to create."""
    title: str
    start: datetime
    end: datetime
    calendar_name: str = ""  # empty = first writable calendar
    notes: str = ""
    location: str = ""


# ── Helpers ──────────────────────────────────────────────────────────

def _date_expr(var: str, dt: datetime) -> str:
    """AppleScript lines building *dt* in *var* without locale-dependent date strings."""
    return (f"set {var} to current date\nset day of {var} to 1\n"
            f"set year of {var} to {dt.year}\nset month of {var} to {dt.month}\nset day of {var} to {dt.day}\n"
            f"set time of {var} to {dt.hour * 3600 + dt.minute * 60 + dt.second}\n")


def _cal_ref(name: str) -> str:
    """AppleScript reference to the named calendar, or the first writable one."""
    if name and name.lower() != "calendar":
        return f'calendar "{esc(name)}"'
    return "(first calendar whose writable is true)"


# Readable timestamp independent of the system locale: 2026-10-26 14:30
_FMT = (' & (year of d as integer) & "-" & text -2 thru -1 of ("0" & ((month of d) as integer)) & "-" & '
        'text -2 thru -1 of ("0" & (day of d)) & " " & text -2 thru -1 of ("0" & (hours of d)) & ":" & '
        'text -2 thru -1 of ("0" & (minutes of d))')


def _list_between(start: datetime, end: datetime, calendar_name: str = "") -> str:
    """Events starting in [start, end) across all calendars (or just *calendar_name*)."""
    cals = f"{{{_cal_ref(calendar_name)}}}" if calendar_name and calendar_name.lower() != "calendar" else "calendars"
    script = _date_expr("startD", start) + _date_expr("endD", end) + f'''
    set output to ""
    tell application "Calendar"
        repeat with cal in {cals}
            set evs to (every event of cal whose start date ≥ startD and start date < endD)
            repeat with ev in evs
                set d to start date of ev
                set output to output & ""{_FMT} & " — " & (summary of ev) & " [" & (name of cal) & "]" & linefeed
            end repeat
        end repeat
    end tell
    return output
    '''
    out = run_applescript(script, timeout=90)
    if out.startswith("Error"):
        return out
    return "\n".join(sorted({line for line in out.splitlines() if line.strip()}))


# ── Public API (tool functions) ─────────────────────────────────────

def add_event(event: CalendarEvent) -> str:
    """Add a new event to Apple Calendar (first writable calendar unless one is named)."""
    script = _date_expr("startD", event.start) + _date_expr("endD", event.end) + f'''
    tell application "Calendar"
        tell {_cal_ref(event.calendar_name)}
            make new event with properties {{summary:"{esc(event.title)}", start date:startD, end date:endD, description:"{esc(event.notes)}", location:"{esc(event.location)}"}}
            set calName to name
        end tell
    end tell
    return "Event created: {esc(event.title)} in " & calName
    '''
    logger.info("Creating calendar event: %s", event.title)
    return run_applescript(script, timeout=60)


def list_today_events(calendar_name: str = "") -> str:
    """List today's events across all calendars (or just *calendar_name*)."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return _list_between(today, today + timedelta(days=1), calendar_name) or "No events found for today."


def delete_event(title: str, calendar_name: str = "") -> str:
    """Delete the first upcoming event matching *title* (any calendar unless one is named)."""
    cals = f"{{{_cal_ref(calendar_name)}}}" if calendar_name and calendar_name.lower() != "calendar" else "calendars"
    script = f'''
    tell application "Calendar"
        repeat with cal in {cals}
            set matches to (every event of cal whose summary is "{esc(title)}")
            if (count of matches) > 0 then
                delete item 1 of matches
                return "Deleted event: {esc(title)} from " & (name of cal)
            end if
        end repeat
    end tell
    return "No event found with title: {esc(title)}"
    '''
    logger.info("Deleting calendar event: %s", title)
    return run_applescript(script, timeout=90)


def list_upcoming_events(days: int = 7) -> str:
    """List events across all calendars for the next *days* days."""
    days = max(1, min(int(days), 60))
    now = datetime.now()
    return _list_between(now, now + timedelta(days=days)) or f"No events in the next {days} days."



# ── Tool descriptor (used by the Agent for function-calling) ────────

TOOL_DESCRIPTORS = [
    {
        "name": "add_calendar_event",
        "description": (
            "Add a new event to the user's Apple Calendar on macOS. "
            "Provide title, start/end datetimes (ISO 8601), and optionally "
            "calendar_name, notes, and location."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start datetime in ISO 8601"},
                "end": {"type": "string", "description": "End datetime in ISO 8601"},
                "calendar_name": {"type": "string", "description": "Calendar name (omit for the default calendar)"},
                "notes": {"type": "string", "description": "Event notes/body", "default": ""},
                "location": {"type": "string", "description": "Event location", "default": ""},
            },
            "required": ["title", "start", "end"],
        },
    },
    {
        "name": "list_today_calendar_events",
        "description": "List all of today's events from Apple Calendar.",
        "parameters": {
            "type": "object",
            "properties": {
                "calendar_name": {"type": "string", "description": "Optional; omit to search all calendars"},
            },
        },
    },
    {
        "name": "delete_calendar_event",
        "description": "Delete a calendar event by its exact title.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "calendar_name": {"type": "string", "description": "Optional; omit to search all calendars"},
            },
            "required": ["title"],
        },
    },
]

TOOL_DESCRIPTORS.append(
    {
        "name": "list_upcoming_events",
        "description": "List upcoming events across ALL calendars for the next N days.",
        "parameters": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Days ahead (default 7)"}},
        },
    }
)
