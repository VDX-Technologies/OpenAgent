"""
Tool · EventKit (fast Calendar / Reminders reads)
=================================================
Reading events and reminders through AppleScript means Calendar/Reminders
must launch and answer ``whose`` queries, which takes seconds (minutes with
many calendars). EventKit answers in milliseconds.

It is used only when macOS already granted VDX access. The access prompt is
only requested from the app bundle, whose Info.plist explains why (macOS kills
a process that asks without that explanation). Otherwise the AppleScript path
is used, exactly as before.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

FULL_ACCESS = 3  # EKAuthorizationStatusFullAccess (== Authorized before macOS 14)
_requested: set[str] = set()
_store: Any = None
_lock = threading.Lock()


def _ek() -> Any:
    try:
        import EventKit

        return EventKit
    except ImportError:
        return None


def _entity(kind: str) -> Any:
    ek = _ek()
    return ek.EKEntityTypeEvent if kind == "event" else ek.EKEntityTypeReminder


def _can_prompt(kind: str) -> bool:
    try:
        from Foundation import NSBundle

        info = NSBundle.mainBundle().infoDictionary() or {}
        key = "NSCalendarsFullAccessUsageDescription" if kind == "event" else "NSRemindersFullAccessUsageDescription"
        return bool(info.get(key))
    except Exception:
        return False


def store() -> Any:
    global _store
    with _lock:
        if _store is None:
            _store = _ek().EKEventStore.alloc().init()
        return _store


def ready(kind: str) -> bool:
    """True when EventKit can read *kind* ("event" / "reminder") right now; may start the access prompt."""
    ek = _ek()
    if ek is None:
        return False
    try:
        status = ek.EKEventStore.authorizationStatusForEntityType_(_entity(kind))
    except Exception:
        return False
    if status == FULL_ACCESS:
        return True
    if status == 0 and kind not in _requested and _can_prompt(kind):
        _requested.add(kind)
        s = store()
        done = lambda granted, error: logger.info("EventKit %s access: %s", kind, bool(granted))  # noqa: E731
        try:
            if kind == "event" and hasattr(s, "requestFullAccessToEventsWithCompletion_"):
                s.requestFullAccessToEventsWithCompletion_(done)
            elif kind == "reminder" and hasattr(s, "requestFullAccessToRemindersWithCompletion_"):
                s.requestFullAccessToRemindersWithCompletion_(done)
            else:
                s.requestAccessToEntityType_completion_(_entity(kind), done)
        except Exception:
            logger.debug("EventKit access request failed", exc_info=True)
    return False


def _nsdate(dt: datetime) -> Any:
    from Foundation import NSDate

    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _py(nsdate: Any) -> datetime:
    return datetime.fromtimestamp(nsdate.timeIntervalSince1970())


def events_between(start: datetime, end: datetime, calendar_name: str = "") -> list[dict[str, Any]]:
    s = store()
    cals = None
    if calendar_name and calendar_name.lower() != "calendar":
        cals = [c for c in s.calendarsForEntityType_(_entity("event")) if c.title().lower() == calendar_name.lower()]
        if not cals:
            raise ValueError(f"no calendar named '{calendar_name}'")
    pred = s.predicateForEventsWithStartDate_endDate_calendars_(_nsdate(start), _nsdate(end), cals)
    out = []
    for ev in s.eventsMatchingPredicate_(pred) or []:
        st = _py(ev.startDate())
        if st < start and not ev.isAllDay():
            continue  # started earlier and still running: list it only on its own day
        out.append({"start": st, "end": _py(ev.endDate()), "title": str(ev.title() or ""), "all_day": bool(ev.isAllDay()),
                    "calendar": str(ev.calendar().title()), "location": str(ev.location() or "")})
    return sorted(out, key=lambda e: e["start"])


def reminders(list_name: str = "", completed: bool = False) -> list[dict[str, Any]]:
    s = store()
    cals = list(s.calendarsForEntityType_(_entity("reminder")))
    if list_name:
        cals = [c for c in cals if c.title().lower() == list_name.lower()]
        if not cals:
            raise ValueError(f"no reminders list named '{list_name}'")
    pred = (s.predicateForCompletedRemindersWithCompletionDateStarting_ending_calendars_(None, None, cals) if completed
            else s.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(None, None, cals))
    result: dict[str, Any] = {}
    done = threading.Event()

    def cb(items: Any) -> None:
        result["items"] = list(items or [])
        done.set()

    s.fetchRemindersMatchingPredicate_completion_(pred, cb)
    if not done.wait(20):
        raise TimeoutError("Reminders did not answer")
    out = []
    for r in result["items"]:
        comps = r.dueDateComponents()
        due = None
        if comps is not None and comps.date() is not None:
            due = _py(comps.date())
        out.append({"title": str(r.title() or ""), "list": str(r.calendar().title()), "due": due,
                    "notes": str(r.notes() or "")[:200]})
    return sorted(out, key=lambda r: (r["due"] is None, r["due"] or datetime.max))
