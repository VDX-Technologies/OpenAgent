"""
Core · Connectors
=================
Registry of app connectors (Gmail, Mail, Calendar, WhatsApp, …).
Each connector groups tool descriptors + callables and can be
toggled on/off from the UI (persisted as ``CONNECTORS_DISABLED`` in ``.env``).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from core import automations
from datetime import datetime
from typing import Any, Callable

from config.settings import get_settings, reload_settings, save_settings_to_env
from tools import apple_calendar, apple_contacts, apple_mail, apple_messages, apple_notes
from tools import apple_reminders, code_workspace, github_tool, gmail_tool, whatsapp


@dataclass
class Connector:
    """A group of related tools exposed to the agent."""

    id: str
    name: str
    description: str
    descriptors: list[dict[str, Any]]
    funcs: dict[str, Callable[..., str]]
    is_configured: Callable[[], bool] = lambda: True
    setup_hint: str = ""


def _add_calendar_event(title, start, end, calendar_name="", notes="", location=""):
    """Parse ISO dates then call the calendar tool."""
    try:
        ev = apple_calendar.CalendarEvent(
            title=title, start=datetime.fromisoformat(start), end=datetime.fromisoformat(end),
            calendar_name=calendar_name, notes=notes, location=location,
        )
    except ValueError as exc:
        return f"Error parsing dates: {exc}"
    return apple_calendar.add_event(ev)


def _add_reminder(title, list_name="Reminders", notes="", due_date=None):
    """Parse optional ISO due_date then call the reminders tool."""
    try:
        parsed = datetime.fromisoformat(due_date) if due_date else None
    except ValueError as exc:
        return f"Error parsing due_date: {exc}"
    return apple_reminders.add_reminder(title, list_name, notes, parsed)


def _gmail_ok() -> bool:
    g = get_settings().gmail
    return bool(g.address and g.app_password)


_MAC = sys.platform == "darwin"

CONNECTORS: list[Connector] = [
    Connector(
        "code", "Code", "Read, edit, commit and push code in a local git repo.",
        code_workspace.TOOL_DESCRIPTORS, code_workspace.TOOLS,
        setup_hint="Set a repo folder in Settings, or ask VDX to use one.",
    ),
    Connector(
        "github", "GitHub", "Repos, issues, pull requests and cloning.",
        github_tool.TOOL_DESCRIPTORS, github_tool.TOOLS, lambda: bool(get_settings().github.token),
        "Add a GitHub personal access token (repo scope) in Settings.",
    ),
    Connector(
        "gmail", "Gmail", "Read inbox (IMAP) and send email (SMTP).",
        gmail_tool.TOOL_DESCRIPTORS, gmail_tool.TOOLS, _gmail_ok,
        "Set Gmail address + App Password in Settings.",
    ),
    Connector(
        "mail", "Apple Mail", "Read and send with any account in Mail.app.",
        apple_mail.TOOL_DESCRIPTORS, apple_mail.TOOLS, lambda: _MAC,
    ),
    Connector(
        "calendar", "Calendar", "Create, list and delete Calendar.app events.",
        apple_calendar.TOOL_DESCRIPTORS,
        {
            "add_calendar_event": _add_calendar_event,
            "list_today_calendar_events": lambda calendar_name="": apple_calendar.list_today_events(calendar_name),
            "delete_calendar_event": lambda title, calendar_name="": apple_calendar.delete_event(title, calendar_name),
            "list_upcoming_events": apple_calendar.list_upcoming_events,
        },
        lambda: _MAC,
    ),
    Connector(
        "reminders", "Reminders", "Manage Reminders.app tasks.",
        apple_reminders.TOOL_DESCRIPTORS,
        {
            "add_reminder": _add_reminder,
            "list_reminders": lambda list_name="Reminders", show_completed=False: apple_reminders.list_reminders(list_name, show_completed),
            "complete_reminder": lambda title, list_name="Reminders": apple_reminders.complete_reminder(title, list_name),
            "delete_reminder": lambda title, list_name="Reminders": apple_reminders.delete_reminder(title, list_name),
        },
        lambda: _MAC,
    ),
    Connector(
        "whatsapp", "WhatsApp", "Send messages (Cloud API or WhatsApp Desktop draft).",
        whatsapp.TOOL_DESCRIPTORS, whatsapp.TOOLS,
        setup_hint="Optional: WhatsApp Cloud API token + phone ID for fully automatic sending.",
    ),
    Connector(
        "messages", "iMessage", "Send iMessages via Messages.app.",
        apple_messages.TOOL_DESCRIPTORS, apple_messages.TOOLS, lambda: _MAC,
    ),
    Connector(
        "contacts", "Contacts", "Look up phone numbers and emails.",
        apple_contacts.TOOL_DESCRIPTORS, apple_contacts.TOOLS, lambda: _MAC,
    ),
    Connector(
        "notes", "Notes", "Create and search Notes.app notes.",
        apple_notes.TOOL_DESCRIPTORS, apple_notes.TOOLS, lambda: _MAC,
    ),
    Connector(
        "automations", "Automations", "Schedule tasks VDX runs on its own.",
        automations.TOOL_DESCRIPTORS, automations.TOOLS,
    ),
]


def is_enabled(cid: str) -> bool:
    """Return True unless the connector id is listed in CONNECTORS_DISABLED."""
    return cid not in get_settings().disabled_connectors


def active_connectors() -> list[Connector]:
    """Connectors that are both enabled and configured."""
    return [c for c in CONNECTORS if is_enabled(c.id) and c.is_configured()]


def set_enabled(cid: str, enabled: bool) -> None:
    """Persist a connector's enabled state to `.env`."""
    if cid not in {c.id for c in CONNECTORS}:
        raise KeyError(cid)
    disabled = set(get_settings().disabled_connectors)
    (disabled.discard if enabled else disabled.add)(cid)
    save_settings_to_env({"CONNECTORS_DISABLED": ",".join(sorted(disabled))})
    reload_settings()


def describe() -> list[dict[str, Any]]:
    """Serialisable connector list for the API."""
    return [
        {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "enabled": is_enabled(c.id),
            "configured": c.is_configured(),
            "setup_hint": c.setup_hint,
            "tools": [d["name"] for d in c.descriptors],
        }
        for c in CONNECTORS
    ]
