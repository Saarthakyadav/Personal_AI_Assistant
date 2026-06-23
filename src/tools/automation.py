# src/tools/automation.py
"""
Automation tools for Nova — schedule background tasks (Phase 6).
"""

import json
from src.tools import Tool


def create_automation_tools(scheduler) -> list:
    """Create automation tools wired to the given TaskScheduler."""

    def _schedule_task(name: str, goal: str, trigger: str, trigger_args: dict) -> str:
        try:
            task_id = scheduler.schedule_task(
                name=name,
                goal=goal,
                trigger=trigger,
                trigger_args=trigger_args,
            )
            return json.dumps({
                "status": "scheduled",
                "task_id": task_id,
                "name": name,
                "trigger": trigger,
                "trigger_args": trigger_args,
                "note": "Task is now running in the background. View it in the Automations tab.",
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _list_tasks() -> str:
        try:
            tasks = scheduler.list_tasks()
            return json.dumps({"tasks": tasks, "count": len(tasks)}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _cancel_task(task_id: str) -> str:
        try:
            ok = scheduler.cancel_task(task_id)
            if ok:
                return json.dumps({"status": "cancelled", "task_id": task_id})
            return json.dumps({"error": f"Task '{task_id}' not found."})
        except Exception as e:
            return json.dumps({"error": str(e)})

    SCHEDULE_TASK = Tool(
        name="schedule_task",
        description=(
            "Schedule a recurring or one-time background task. "
            "The task will automatically run the specified goal through the agent. "
            "trigger can be: 'interval' (e.g. every 30 minutes), 'cron' (e.g. every day at 9am), "
            "or 'date' (run once at a specific time). "
            "Examples: "
            "  - Every 30 min: trigger='interval', trigger_args={'minutes': 30} "
            "  - Daily 9am: trigger='cron', trigger_args={'hour': 9, 'minute': 0} "
            "  - Once at specific time: trigger='date', trigger_args={'run_date': '2026-07-01T09:00:00'}"
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Human-readable task name."},
                "goal": {"type": "string", "description": "What the agent should do each time this task runs."},
                "trigger": {"type": "string", "enum": ["interval", "cron", "date"], "description": "How to trigger the task."},
                "trigger_args": {
                    "type": "object",
                    "description": "Trigger arguments. For interval: {'minutes': N} or {'hours': N}. For cron: {'hour': H, 'minute': M}. For date: {'run_date': 'ISO-8601'}.",
                },
            },
            "required": ["name", "goal", "trigger", "trigger_args"],
        },
        handler=_schedule_task,
        requires_confirmation=False,
    )

    LIST_TASKS = Tool(
        name="list_scheduled_tasks",
        description="List all active background scheduled tasks.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_list_tasks,
        requires_confirmation=False,
    )

    CANCEL_TASK = Tool(
        name="cancel_task",
        description="Cancel a scheduled background task by its task_id.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID shown in list_scheduled_tasks."},
            },
            "required": ["task_id"],
        },
        handler=_cancel_task,
        requires_confirmation=True,
    )

    return [SCHEDULE_TASK, LIST_TASKS, CANCEL_TASK]
