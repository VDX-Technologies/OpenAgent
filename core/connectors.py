"""
Core · Connectors
=================
Registry of app connectors (Gmail, Mail, Calendar, WhatsApp, …). Each
connector groups tool descriptors + callables and can be toggled on/off from
the UI (persisted as ``CONNECTORS_DISABLED`` in ``.env``).

Tool routing: every tool schema is sent with every model call, and ~40 of them
fill a good part of a small context window. :func:`route` keeps only the
connectors a conversation is about (keywords in the user's messages); the ones
without keywords (web, memory, MCP) are always included.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from config.settings import get_settings, reload_settings, save_settings_to_env
from core import automations, mcp, memory
from tools import apple_calendar, apple_contacts, apple_mail, apple_messages, apple_notes
from tools import apple_reminders, code_workspace, files, github_tool, gmail_tool, phone, shortcuts, web, whatsapp


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
    keywords: tuple[str, ...] = field(default_factory=tuple)


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


def _add_reminder(title, list_name="", notes="", due_date=None):
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
_DAYS = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica",
         "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MAIL = ("mail", "posta", "inbox", "unread", "non lett", "newsletter", "bozza", "draft", "rispondi", "reply", "briefing",
         "riepilog", "summar")

CONNECTORS: list[Connector] = [
    Connector("web", "Web", "Search the internet and read web pages.", web.TOOL_DESCRIPTORS, web.TOOLS),
    Connector("memory", "Memory", "Remember facts and preferences about the user.",
              memory.TOOL_DESCRIPTORS, memory.TOOLS),
    Connector(
        "phone", "Phone", "Send push notifications to your phone (ntfy).",
        phone.TOOL_DESCRIPTORS, phone.TOOLS, phone.configured,
        "Set a phone topic in Settings → Phone, then subscribe to it in the ntfy app.",
        ("phone", "telefono", "cellulare", "notific", "notify", "push", "mandami", "send me", "avvisami", "alert"),
    ),
    Connector(
        "code", "Code", "Read, edit, commit and push code in a local git repo.",
        code_workspace.TOOL_DESCRIPTORS, code_workspace.TOOLS,
        setup_hint="Set a repo folder in Settings, or ask VDX to use one.",
        keywords=("code", "codice", "repo", "git", "commit", "branch", "diff", "bug", "refactor", "funzion", "function",
                  "workspace", "progett", "project", "script", ".py", ".ts", ".js", "file"),
    ),
    Connector(
        "github", "GitHub", "Repos, issues, pull requests and cloning.",
        github_tool.TOOL_DESCRIPTORS, github_tool.TOOLS, lambda: bool(get_settings().github.token),
        "Add a GitHub personal access token (repo scope) in Settings.",
        ("github", "issue", "pull request", "repo", "clone", "clona"),
    ),
    Connector(
        "gmail", "Gmail", "Read inbox and messages, write drafts and send email.",
        gmail_tool.TOOL_DESCRIPTORS, gmail_tool.TOOLS, _gmail_ok,
        "Set Gmail address + App Password in Settings.", _MAIL,
    ),
    Connector(
        "mail", "Apple Mail", "Read and send with any account in Mail.app.",
        apple_mail.TOOL_DESCRIPTORS, apple_mail.TOOLS, lambda: _MAC, keywords=_MAIL,
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
        keywords=("calend", "event", "meeting", "riunion", "appuntament", "agenda", "impegn", "oggi", "domani", "today",
                  "tomorrow", "settiman", "week", "giornata", "schedule", "briefing", "riepilog", "summar", "libero",
                  "free", "busy", "occupat", *_DAYS),
    ),
    Connector(
        "reminders", "Reminders", "Manage Reminders.app tasks.",
        apple_reminders.TOOL_DESCRIPTORS,
        {
            "add_reminder": _add_reminder,
            "list_reminders": lambda list_name="", show_completed=False: apple_reminders.list_reminders(list_name, show_completed),
            "complete_reminder": lambda title, list_name="": apple_reminders.complete_reminder(title, list_name),
            "delete_reminder": lambda title, list_name="": apple_reminders.delete_reminder(title, list_name),
        },
        lambda: _MAC,
        keywords=("remind", "ricord", "promemoria", "todo", "to-do", "to do", "task", "compit", "da fare", "lista", "list",
                  "briefing", "riepilog", "summar", "oggi", "today"),
    ),
    Connector(
        "whatsapp", "WhatsApp", "Send messages (Cloud API or WhatsApp Desktop draft).",
        whatsapp.TOOL_DESCRIPTORS, whatsapp.TOOLS,
        setup_hint="Optional: WhatsApp Cloud API token + phone ID for fully automatic sending.",
        keywords=("whatsapp", "whats app", "wa "),
    ),
    Connector(
        "messages", "iMessage", "Send iMessages via Messages.app.",
        apple_messages.TOOL_DESCRIPTORS, apple_messages.TOOLS, lambda: _MAC,
        keywords=("imessage", "sms", "messag", "scrivi a", "scrivigli", "scrivile", "text ", "manda un", "send a"),
    ),
    Connector(
        "contacts", "Contacts", "Look up phone numbers and emails.",
        apple_contacts.TOOL_DESCRIPTORS, apple_contacts.TOOLS, lambda: _MAC,
        keywords=("contatt", "contact", "numero", "number", "chiama", "call ", "indirizzo", "address"),
    ),
    Connector(
        "notes", "Notes", "Create and search Notes.app notes.",
        apple_notes.TOOL_DESCRIPTORS, apple_notes.TOOLS, lambda: _MAC,
        keywords=("note", "nota", "appunt"),
    ),
    Connector(
        "files", "Files", "Search documents in folders you index (Memory → Files).",
        files.TOOL_DESCRIPTORS, files.TOOLS,
        keywords=("file", "document", "pdf", "cartell", "folder", "archivi", "indicizz", "index", "contratt", "fattur",
                  "invoice", "report", "relazion", "appunti"),
    ),
    Connector(
        "shortcuts", "Shortcuts", "Run your Apple Shortcuts.",
        shortcuts.TOOL_DESCRIPTORS, shortcuts.TOOLS, lambda: _MAC,
        keywords=("shortcut", "comandi rapidi", "comando rapido", "scorciatoi", "siri"),
    ),
    Connector(
        "automations", "Automations", "Schedule tasks VDX runs on its own.",
        automations.TOOL_DESCRIPTORS, automations.TOOLS,
        keywords=("ogni", "every", "automat", "programm", "schedul", "ricorrent", "recurring", "daily", "weekly",
                  "alle ", " at ", "tutti i giorni", "each", "mattina", "morning", "sera", "evening"),
    ),
]

# connectors that address people by name need the address book
_NEEDS_CONTACTS = {"messages", "whatsapp", "mail", "gmail"}


def _mcp_connectors() -> list[Connector]:
    out = []
    for s in mcp.servers():
        if not s.tools:
            continue
        descs, funcs = [], {}
        for t in s.tools:
            name = mcp.tool_name(s.name, t["name"])
            descs.append({"name": name, "description": (t.get("description") or t["name"])[:1000],
                          "parameters": t.get("inputSchema") or {"type": "object", "properties": {}}})
            funcs[name] = lambda _s=s, _t=t["name"], **kw: _s.call(_t, kw)
        out.append(Connector(f"mcp:{s.name}", s.name, f"MCP server ({len(descs)} tools).", descs, funcs))
    return out


def all_connectors() -> list[Connector]:
    return CONNECTORS + _mcp_connectors()


def is_enabled(cid: str) -> bool:
    """Return True unless the connector id is listed in CONNECTORS_DISABLED."""
    return cid not in get_settings().disabled_connectors


def active_connectors() -> list[Connector]:
    """Connectors that are both enabled and configured."""
    return [c for c in all_connectors() if is_enabled(c.id) and c.is_configured()]


def route(text: str) -> list[Connector]:
    """Active connectors relevant to *text* (all of them when routing is off)."""
    active = active_connectors()
    if not get_settings().ollama.tool_routing:
        return active
    t = f" {text.lower()} "
    chosen = {c.id for c in active if not c.keywords or any(k in t for k in c.keywords)}
    if chosen & _NEEDS_CONTACTS:
        chosen.add("contacts")
    return [c for c in active if c.id in chosen]


def set_enabled(cid: str, enabled: bool) -> None:
    """Persist a connector's enabled state to `.env`."""
    if cid not in {c.id for c in all_connectors()}:
        raise KeyError(cid)
    disabled = set(get_settings().disabled_connectors)
    (disabled.discard if enabled else disabled.add)(cid)
    save_settings_to_env({"CONNECTORS_DISABLED": ",".join(sorted(disabled))})
    reload_settings()


def describe() -> list[dict[str, Any]]:
    """Serialisable connector list for the API."""
    return [
        {
            "id": c.id, "name": c.name, "description": c.description, "enabled": is_enabled(c.id),
            "configured": c.is_configured(), "setup_hint": c.setup_hint, "tools": [d["name"] for d in c.descriptors],
        }
        for c in all_connectors()
    ]
