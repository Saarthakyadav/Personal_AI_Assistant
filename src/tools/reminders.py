# src/tools/reminders.py
"""
Reminder tool and background service for Nova.

Reminders are persisted to a JSON file and a background thread checks every
15 seconds for due reminders.  When one fires it calls the speak_callback
(main.py's speak()) which handles mic mute/unmute properly.
"""

import json
import os
import threading
from datetime import datetime
from typing import Callable, List, Optional

from src.tools import Tool


class ReminderService:
    """Manages persistent reminders with a background checker thread."""

    def __init__(self, filepath: str, speak_callback: Callable[[str], None]):
        self._filepath = filepath
        self._speak = speak_callback          # main.py's speak() — handles mic
        self._lock = threading.Lock()
        self._reminders: List[dict] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._load()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self):
        """Start the background reminder-checker thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._check_loop, daemon=True)
        self._thread.start()
        pending = sum(1 for r in self._reminders if not r.get("done"))
        print(f"✅ Reminder service started ({pending} pending reminder(s))")

    def stop(self):
        """Stop the background thread."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    # ── Tool handler ──────────────────────────────────────────────────────

    def set_reminder(self, reminder_time: str, message: str) -> str:
        """
        Set a new reminder.

        Args:
            reminder_time: ISO-8601 datetime string (the LLM converts natural
                           language like "in 10 minutes" to ISO before calling).
            message: What to remind the user about.

        Returns:
            Confirmation string for the LLM.
        """
        try:
            dt = datetime.fromisoformat(reminder_time)
        except ValueError:
            return json.dumps({
                "error": f"Invalid time format: '{reminder_time}'. "
                         "Use ISO-8601 format like '2026-06-17T15:30:00'."
            })

        reminder = {
            "time": dt.isoformat(),
            "message": message,
            "created_at": datetime.now().isoformat(),
            "done": False,
        }

        with self._lock:
            self._reminders.append(reminder)
            self._save_unlocked()

        return (
            f"Reminder set for {dt.strftime('%I:%M %p on %A, %B %d')}: "
            f"'{message}'"
        )

    # ── Background loop ──────────────────────────────────────────────────

    def _check_loop(self):
        """Check for due reminders every 15 seconds."""
        while not self._stop.is_set():
            self._fire_due_reminders()
            self._stop.wait(15)  # sleep 15s, but wake immediately on stop()

    def _fire_due_reminders(self):
        """Find and fire any reminders whose time has passed."""
        now = datetime.now()
        to_fire = []

        with self._lock:
            for reminder in self._reminders:
                if reminder.get("done"):
                    continue
                try:
                    dt = datetime.fromisoformat(reminder["time"])
                except ValueError:
                    continue
                
                compare_now = now
                if dt.tzinfo is not None:
                    compare_now = datetime.now(dt.tzinfo)

                if dt <= compare_now:
                    to_fire.append(reminder)

        # FIX #7: Mark reminders done UNDER the lock BEFORE speaking, so a
        # second _fire_due_reminders() call can't re-collect them if speak()
        # takes longer than 15s (the check interval).
        if to_fire:
            with self._lock:
                for reminder in to_fire:
                    reminder["done"] = True
                self._save_unlocked()

        # Now speak outside the lock — reminders are already marked done
        for reminder in to_fire:
            print(f"\n⏰ Reminder firing: {reminder['message']}")
            try:
                self._speak(f"Reminder: {reminder['message']}")
            except Exception as e:
                print(f"   ⚠️ Reminder speak failed: {e}")

    # ── Persistence ──────────────────────────────────────────────────────

    def _load(self):
        if not os.path.exists(self._filepath):
            self._reminders = []
            return
        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._reminders = data.get("reminders", [])
        except Exception as e:
            print(f"   ⚠️ Could not load reminders: {e}")
            self._reminders = []

    def _save_unlocked(self):
        """Persist reminders to disk.  Caller must hold self._lock."""
        try:
            data = {
                "reminders": self._reminders,
                "updated_at": datetime.now().isoformat(),
            }
            with open(self._filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"   ⚠️ Could not save reminders: {e}")


def create_reminder_tool(service: ReminderService) -> Tool:
    """Create a Tool instance wired to the given ReminderService."""
    return Tool(
        name="set_reminder",
        description=(
            "Set a reminder for the user at a specific time. "
            "Convert the user's natural language time (e.g., 'in 10 minutes', "
            "'at 5pm tomorrow') to an ISO-8601 datetime string before calling. "
            "Use the get_current_datetime tool first if you need to know the "
            "current time to calculate the reminder time."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reminder_time": {
                    "type": "string",
                    "description": (
                        "The reminder time as an ISO-8601 datetime string, "
                        "e.g. '2026-06-17T15:30:00'."
                    ),
                },
                "message": {
                    "type": "string",
                    "description": "What to remind the user about.",
                },
            },
            "required": ["reminder_time", "message"],
        },
        handler=service.set_reminder,
        requires_confirmation=True,  # Ask user before setting
    )
