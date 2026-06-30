# src/tools/calendar_tool.py
import json
from datetime import datetime, timedelta
from typing import Optional
from googleapiclient.discovery import build

from src.tools import Tool
from src.tools.google_auth import get_google_credentials

# ── 1. create_calendar_event ──────────────────────────────────────────────────

def _create_calendar_event(
    title: str,
    start: str,
    end: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
) -> str:
    """Create a Google Calendar event."""
    try:
        creds = get_google_credentials()
        service = build('calendar', 'v3', credentials=creds)
    except Exception as e:
        return json.dumps({"error": f"Failed to authenticate with Google: {e}"})

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

    event_body = {
        'summary': title,
        'location': location or '',
        'description': description or '',
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': 'UTC',
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': 'UTC',
        },
    }

    try:
        event = service.events().insert(calendarId='primary', body=event_body).execute()
        return json.dumps({
            "status": "created",
            "event": {
                "id": event.get('id'),
                "title": event.get('summary'),
                "start": event.get('start', {}).get('dateTime'),
                "link": event.get('htmlLink')
            }
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to create Google Calendar event: {e}"})

CREATE_CALENDAR_EVENT = Tool(
    name="create_calendar_event",
    description=(
        "Create a calendar event directly in Google Calendar. "
        "Use ISO-8601 format for start/end times, e.g. '2026-07-01T14:00:00'. "
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
    """List upcoming Google Calendar events."""
    try:
        creds = get_google_credentials()
        service = build('calendar', 'v3', credentials=creds)
    except Exception as e:
        return json.dumps({"error": f"Failed to authenticate with Google: {e}"})

    now = datetime.utcnow()
    time_min = now.isoformat() + 'Z'  # 'Z' indicates UTC time
    time_max = (now + timedelta(days=days_ahead)).isoformat() + 'Z'

    try:
        events_result = service.events().list(
            calendarId='primary', 
            timeMin=time_min,
            timeMax=time_max,
            maxResults=20, 
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        
        upcoming = []
        for e in events:
            start = e['start'].get('dateTime', e['start'].get('date'))
            upcoming.append({
                "id": e['id'],
                "title": e.get('summary', 'Untitled Event'),
                "start": start,
                "location": e.get('location', ''),
                "description": e.get('description', '')
            })

        return json.dumps({
            "events": upcoming,
            "count": len(upcoming),
            "range": f"Next {days_ahead} days",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch Google Calendar events: {e}"})

LIST_CALENDAR_EVENTS = Tool(
    name="list_calendar_events",
    description="List upcoming Google Calendar events for the next N days (default 7).",
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
    """Delete a Google Calendar event by its ID."""
    try:
        creds = get_google_credentials()
        service = build('calendar', 'v3', credentials=creds)
    except Exception as e:
        return json.dumps({"error": f"Failed to authenticate with Google: {e}"})

    try:
        service.events().delete(calendarId='primary', eventId=event_id).execute()
        return json.dumps({"status": "deleted", "event_id": event_id})
    except Exception as e:
        return json.dumps({"error": f"Failed to delete event '{event_id}'. Error: {e}"})

DELETE_CALENDAR_EVENT = Tool(
    name="delete_calendar_event",
    description="Delete a Google Calendar event by its ID. Use list_calendar_events to find the ID.",
    parameters={
        "type": "object",
        "properties": {
            "event_id": {"type": "string", "description": "The event ID."},
        },
        "required": ["event_id"],
    },
    handler=_delete_calendar_event,
    requires_confirmation=True,
)

# ── Exported list ─────────────────────────────────────────────────────────────
CALENDAR_TOOLS = [CREATE_CALENDAR_EVENT, LIST_CALENDAR_EVENTS, DELETE_CALENDAR_EVENT]
