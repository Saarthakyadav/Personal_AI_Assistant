# src/scheduler.py
"""
Background Task Scheduler for Nova — Phase 6.

Uses APScheduler with a local JSON job store for persistence.
Tasks are re-loaded on server restart.

Install: pip install apscheduler
"""

import json
import os
import uuid
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List


_TASKS_FILE = os.path.join(os.path.dirname(__file__), "..", "scheduled_tasks.json")


class TaskScheduler:
    """APScheduler-backed persistent task manager for background agent workflows."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: Dict[str, dict] = {}
        self._scheduler = None
        self._agent = None
        self._load_tasks()

    def start(self):
        """Start the APScheduler background scheduler."""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.jobstores.memory import MemoryJobStore
        except ImportError:
            raise ImportError("APScheduler not installed. Run: pip install apscheduler")

        self._scheduler = BackgroundScheduler(
            jobstores={"default": MemoryJobStore()},
            job_defaults={"coalesce": True, "max_instances": 1},
        )
        self._scheduler.start()
        print("✅ Task scheduler started")

        # Re-schedule any persisted tasks
        self._reschedule_persisted_tasks()

    def stop(self):
        """Stop the scheduler gracefully."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    # ── Public API ────────────────────────────────────────────────────────────

    def schedule_task(
        self,
        name: str,
        goal: str,
        trigger: str,
        trigger_args: dict,
        agent=None,
        conversation_history: Optional[list] = None,
    ) -> str:
        """
        Schedule a background agent task.

        Args:
            name:               Human-readable task name.
            goal:               The goal/prompt to run through the agent.
            trigger:            'interval', 'cron', or 'date'.
            trigger_args:       Trigger-specific args.
                                  interval: {"minutes": 30} or {"hours": 2}
                                  cron:     {"hour": 9, "minute": 0}
                                  date:     {"run_date": "2026-07-01T09:00:00"}
            agent:              AgentCore instance.
            conversation_history: Shared conversation history.

        Returns:
            task_id (str)
        """
        if agent:
            self._agent = agent

        task_id = str(uuid.uuid4())[:8]
        task = {
            "task_id": task_id,
            "name": name,
            "goal": goal,
            "trigger": trigger,
            "trigger_args": trigger_args,
            "created_at": datetime.now().isoformat(),
            "status": "scheduled",
            "last_run": None,
            "run_count": 0,
        }

        with self._lock:
            self._tasks[task_id] = task
            self._save_tasks_unlocked()

        self._add_to_scheduler(task)
        return task_id

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a scheduled task. Returns True if found and cancelled."""
        with self._lock:
            if task_id not in self._tasks:
                return False
            self._tasks[task_id]["status"] = "cancelled"
            self._save_tasks_unlocked()

        if self._scheduler:
            try:
                self._scheduler.remove_job(task_id)
            except Exception:
                pass
        return True

    def list_tasks(self) -> List[dict]:
        """Return all tasks (excluding cancelled)."""
        with self._lock:
            return [
                {k: v for k, v in t.items() if k != "goal"}  # omit long goal text
                for t in self._tasks.values()
                if t.get("status") != "cancelled"
            ]

    # ── Private helpers ───────────────────────────────────────────────────────

    def _add_to_scheduler(self, task: dict):
        """Add a task to APScheduler."""
        if not self._scheduler:
            return

        trigger = task["trigger"]
        args = task["trigger_args"].copy()
        task_id = task["task_id"]

        try:
            if trigger == "interval":
                self._scheduler.add_job(
                    self._run_task,
                    "interval",
                    id=task_id,
                    kwargs={"task_id": task_id},
                    replace_existing=True,
                    **args,
                )
            elif trigger == "cron":
                self._scheduler.add_job(
                    self._run_task,
                    "cron",
                    id=task_id,
                    kwargs={"task_id": task_id},
                    replace_existing=True,
                    **args,
                )
            elif trigger == "date":
                self._scheduler.add_job(
                    self._run_task,
                    "date",
                    id=task_id,
                    kwargs={"task_id": task_id},
                    replace_existing=True,
                    **args,
                )
            print(f"   ✅ Scheduled task '{task['name']}' ({trigger}: {args})")
        except Exception as e:
            print(f"   ⚠️ Failed to schedule task '{task['name']}': {e}")
            with self._lock:
                self._tasks[task["task_id"]]["status"] = "error"
                self._save_tasks_unlocked()

    def _run_task(self, task_id: str):
        """Execute a scheduled task through the agent."""
        with self._lock:
            task = self._tasks.get(task_id)
        if not task or task.get("status") == "cancelled":
            return

        goal = task["goal"]
        print(f"\n⏰ Running scheduled task '{task['name']}': {goal[:60]}")

        if self._agent:
            try:
                result = self._agent.run(
                    user_message=goal,
                    conversation_history=[],
                    confirm_callback=lambda n, d: True,  # auto-approve in background
                    mode="chat",
                )
                print(f"   ✅ Task result: {result[:200]}")
            except Exception as e:
                result = f"Error: {str(e)}"
                print(f"   ❌ Task failed: {e}")
        else:
            result = "No agent available to run this task."

        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["last_run"] = datetime.now().isoformat()
                self._tasks[task_id]["run_count"] = self._tasks[task_id].get("run_count", 0) + 1
                self._tasks[task_id]["last_result"] = result[:500]
                if task["trigger"] == "date":
                    self._tasks[task_id]["status"] = "completed"
                self._save_tasks_unlocked()

    def _reschedule_persisted_tasks(self):
        """Re-add active tasks to the scheduler after a restart."""
        with self._lock:
            tasks = list(self._tasks.values())
        for task in tasks:
            if task.get("status") == "scheduled":
                self._add_to_scheduler(task)

    def _load_tasks(self):
        if not os.path.exists(_TASKS_FILE):
            return
        try:
            with open(_TASKS_FILE, "r", encoding="utf-8") as f:
                self._tasks = json.load(f).get("tasks", {})
        except Exception:
            self._tasks = {}

    def _save_tasks_unlocked(self):
        """Caller must hold self._lock."""
        try:
            data = {"tasks": self._tasks, "updated_at": datetime.now().isoformat()}
            os.makedirs(os.path.dirname(_TASKS_FILE), exist_ok=True)
            with open(_TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"   ⚠️ Could not save tasks: {e}")
