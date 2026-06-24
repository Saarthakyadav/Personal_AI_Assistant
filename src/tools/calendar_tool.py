# src/tools/calendar_tool.py
"""
Calendar tools for Nova — local ICS file + optional Google Calendar API.

Uses a local JSON store for events (works without any API key).
Events are saved to calendar_events.json in the project root.

Tools:
  - create_calendar_event : Create an event (REQUIRES CONFIRMATION)
  - list_calendar_events  : List upcoming events (safe)
  - delete_calendar_event : Delete an event (REQUIRES CONFIRMATION)
"""

import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional

from src.tools import Tool


_CALENDAR_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "calendar_events.json"))
_cal_lock = threading.Lock()


def _load_events() -> list:
    if not os.path.exists(_CALENDAR_FILE):
        return []
    try:
        with open(_CALENDAR_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("events", [])
    except Exception:
        return []


def _save_events(events: list):
    data = {"events": events, "updated_at": datetime.now().isoformat()}
    parent = os.path.dirname(_CALENDAR_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(_CALENDAR_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── 1. create_calendar_event ──────────────────────────────────────────────────

def _create_calendar_event(
    title: str,
    start: str,
    end: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
) -> str:
    """Create a local calendar event."""
    try:
        start_dt = datetime.fromisoformat(start)
    except ValueError:
        return json.dumps({"error": f"Invalid start time format: '{start}'. Use ISO-8601 like '2026-07-01T14:00:00'."})

    if end:
        try:
            end_dt = datetime.fromisoformat(end)
        except ValueError:
            end_dt = start_dt + timedelta(hours=1)
    else:
        end_dt = start_dt + timedelta(hours=1)

    event = {
        "id": str(uuid.uuid4())[:8],
        "title": title,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "description": description or "",
        "location": location or "",
        "created_at": datetime.now().isoformat(),
    }

    with _cal_lock:
        events = _load_events()
        events.append(event)
        _save_events(events)

    return json.dumps({
        "status": "created",
        "event": {
            "id": event["id"],
            "title": event["title"],
            "start": start_dt.strftime("%I:%M %p on %A, %B %d, %Y"),
            "end": end_dt.strftime("%I:%M %p"),
            "location": event["location"] or "(none)",
        }
    }, indent=2)


CREATE_CALENDAR_EVENT = Tool(
    name="create_calendar_event",
    description=(
        "Create a calendar event and store it locally. "
        "Use ISO-8601 format for start/end times, e.g. '2026-07-01T14:00:00'. "
        "Call get_current_datetime first if you need to calculate a relative time."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Event title / name."},
            "start": {"type": "string", "description": "Start time in ISO-8601 format."},
            "end": {"type": "string", "description": "End time in ISO-8601 format. Defaults to 1 hour after start."},
            "description": {"type": "string", "description": "Optional event description or notes."},
            "location": {"type": "string", "description": "Optional event location."},
        },
        "required": ["title", "start"],
    },
    handler=_create_calendar_event,
    requires_confirmation=True,
)


# ── 2. list_calendar_events ───────────────────────────────────────────────────

def _list_calendar_events(days_ahead: int = 7) -> str:
    """List upcoming calendar events."""
    with _cal_lock:
        events = _load_events()

    now = datetime.now()
    cutoff = now + timedelta(days=days_ahead)

    upcoming = []
    for e in events:
        try:
            start_dt = datetime.fromisoformat(e["start"])
            if now <= start_dt <= cutoff:
                upcoming.append({
                    "id": e["id"],
                    "title": e["title"],
                    "start": start_dt.strftime("%I:%M %p on %A, %B %d"),
                    "_sort_key": start_dt.isoformat(),  # FIX #13: sort by raw datetime
                    "location": e.get("location", ""),
                    "description": e.get("description", ""),
                })
        except Exception:
            continue

    # FIX #13: sort by ISO datetime string, not formatted display string
    upcoming.sort(key=lambda x: x["_sort_key"])
    # Remove the sort key before returning
    for item in upcoming:
        item.pop("_sort_key", None)

    return json.dumps({
        "events": upcoming,
        "count": len(upcoming),
        "range": f"Next {days_ahead} days",
    }, indent=2)


LIST_CALENDAR_EVENTS = Tool(
    name="list_calendar_events",
    description="List upcoming calendar events for the next N days (default 7).",
    parameters={
        "type": "object",
        "properties": {
            "days_ahead": {"type": "integer", "description": "How many days ahead to look. Default is 7."},
        },
        "required": [],
    },
    handler=_list_calendar_events,
    requires_confirmation=False,
)


# ── 3. delete_calendar_event ──────────────────────────────────────────────────

def _delete_calendar_event(event_id: str) -> str:
    """Delete a calendar event by its ID."""
    with _cal_lock:
        events = _load_events()
        original_count = len(events)
        events = [e for e in events if e.get("id") != event_id]
        if len(events) == original_count:
            return json.dumps({"error": f"Event '{event_id}' not found. Use list_calendar_events to find valid IDs."})
        _save_events(events)

    return json.dumps({"status": "deleted", "event_id": event_id})


DELETE_CALENDAR_EVENT = Tool(
    name="delete_calendar_event",
    description="Delete a calendar event by its ID. Use list_calendar_events to find the ID.",
    parameters={
        "type": "object",
        "properties": {
            "event_id": {"type": "string", "description": "The event ID (8-character string shown in list_calendar_events)."},
        },
        "required": ["event_id"],
    },
    handler=_delete_calendar_event,
    requires_confirmation=True,
)


# ── Exported list ─────────────────────────────────────────────────────────────

CALENDAR_TOOLS = [CREATE_CALENDAR_EVENT, LIST_CALENDAR_EVENTS, DELETE_CALENDAR_EVENT]
