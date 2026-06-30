# src/orchestrator.py
"""
Multi-Agent Orchestrator for Nova.

Breaks complex goals into sub-tasks and delegates them to specialist agents:
  - ResearchAgent : web_search + search_documents
  - BrowserAgent  : browser_navigate + browser_extract_text + browser_search_and_book
  - EmailAgent    : draft_email + send_email
  - CalendarAgent : create_calendar_event + list_calendar_events
  - NovaAgent     : fallback general agent (uses all tools)

The orchestrator uses the LLM to plan which agents to call and in what order,
then aggregates results into a final response.
"""

import json
import time
from typing import List, Optional, Dict, Any
from src.tools import ToolRegistry
from src.memory import UserMemory


# ── Sub-agent tool sets ───────────────────────────────────────────────────────

AGENT_TOOL_MAP = {
    "research": ["web_search", "browser_search_web", "search_documents", "get_current_datetime"],
    "browser":  ["browser_navigate", "browser_extract_text", "browser_search_web", "browser_search_and_book"],
    "email":    ["draft_email", "send_email", "get_drafts", "list_emails"],
    "calendar": ["create_calendar_event", "list_calendar_events", "delete_calendar_event", "get_current_datetime"],
    "general":  ["execute_python", "http_fetch", "read_file"],
    "nova":     None,  # None means all tools
}

AGENT_DESCRIPTIONS = {
    "research":  "Research Agent — searches the web and documents for information",
    "browser":   "Browser Agent — automates web browsers for booking and extraction",
    "email":     "Email Agent — drafts, sends, and lists emails",
    "calendar":  "Calendar Agent — manages calendar events and scheduling",
    "general":   "General Agent — runs python code, reads files, and fetches web/API URLs",
    "nova":      "Nova (General) — handles anything that doesn't fit a specialist",
}


class Orchestrator:
    """Coordinates multiple specialist sub-agents to complete complex goals."""

    def __init__(self, groq_client, tool_registry: ToolRegistry, memory: UserMemory):
        self._client = groq_client
        self._full_registry = tool_registry
        self._memory = memory
        self._model = "llama-3.1-8b-instant"

    # ── Public API ────────────────────────────────────────────────────────────

    def run_workflow(
        self,
        goal: str,
        agents: Optional[List[str]] = None,
        confirm_callback: Optional[Any] = None,
        step_callback=None,
    ) -> dict:
        """
        Plan and execute a multi-agent workflow.

        Args:
            goal:           High-level user goal.
            agents:         Optional list of agent names to use (auto-selected if None).
            confirm_callback: Optional confirmation callback for guardrails.
            step_callback:  Optional (event_type, detail) → None callback for live UI.

        Returns:
            dict with keys: result, steps, agents_used, tools_used
        """
        if step_callback:
            step_callback("plan", f"Planning workflow for: {goal[:80]}")

        # Step 1: Use LLM to plan which agents to use
        plan = self._plan_workflow(goal, agents)
        if step_callback:
            step_callback("plan", f"Plan: {json.dumps(plan.get('steps', []))}")

        # Step 2: Execute each step
        results = []
        all_tools_used = []
        agents_used = []

        for step_plan in plan.get("steps", [{"agent": "nova", "task": goal}]):
            agent_name = step_plan.get("agent", "nova")
            task = step_plan.get("task", goal)
            depends_on = step_plan.get("depends_on", [])

            if step_callback:
                step_callback("agent", f"{agent_name}: {task[:60]}")

            # Inject previous results as context if there are dependencies
            context = ""
            for dep_idx in depends_on:
                if dep_idx < len(results):
                    context += f"\nPrevious result:\n{results[dep_idx]['result']}\n"

            full_task = task + context

            # Execute via specialist sub-agent
            sub_result = self._run_sub_agent(
                agent_name=agent_name,
                task=full_task,
                confirm_callback=confirm_callback,
                step_callback=step_callback,
            )

            results.append({
                "agent": agent_name,
                "task": task,
                "result": sub_result["result"],
                "tools_used": sub_result["tools_used"],
            })
            all_tools_used.extend(sub_result["tools_used"])
            if agent_name not in agents_used:
                agents_used.append(agent_name)

        # Step 3: Synthesize all results into a final response
        if step_callback:
            step_callback("synthesize", "Synthesizing results")

        if len(results) == 1:
            final_result = results[0]["result"]
        else:
            final_result = self._synthesize_results(goal, results)

        return {
            "result": final_result,
            "steps": results,
            "agents_used": agents_used,
            "tools_used": list(dict.fromkeys(all_tools_used)),  # deduplicated
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _plan_workflow(self, goal: str, requested_agents: Optional[List[str]] = None) -> dict:
        """Use the LLM to break a goal into ordered sub-tasks for agents."""
        available = list(AGENT_TOOL_MAP.keys())
        if requested_agents:
            available = [a for a in requested_agents if a in AGENT_TOOL_MAP]

        prompt = f"""You are a workflow planner. Break this goal into sub-tasks for specialist agents.

Goal: {goal}

Available agents:
{json.dumps(AGENT_DESCRIPTIONS, indent=2)}

Return a JSON object with a "steps" array. Each step has:
  - "agent": one of {available}
  - "task": specific instruction for that agent
  - "depends_on": list of step indices (0-based) whose results this step needs

Keep steps minimal — only split if genuinely different agents are needed.
Return ONLY valid JSON, no commentary.

Example:
{{"steps": [{{"agent": "research", "task": "Find flight prices from Delhi to Mumbai for July 1", "depends_on": []}}, {{"agent": "email", "task": "Draft an email summarizing the flight options found", "depends_on": [0]}}]}}"""

        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0.1,
            )
            raw = resp.choices[0].message.content.strip()
            # Strip markdown fences
            if raw.startswith("```"):
                raw = "\n".join(l for l in raw.split("\n") if not l.strip().startswith("```")).strip()
            plan = json.loads(raw)
            if "steps" not in plan:
                raise ValueError("No steps key")
            return plan
        except Exception as e:
            print(f"   ⚠️ Workflow planning failed ({e}), falling back to single nova agent")
            return {"steps": [{"agent": "nova", "task": goal, "depends_on": []}]}

    def _run_sub_agent(
        self,
        agent_name: str,
        task: str,
        confirm_callback: Optional[Any] = None,
        step_callback=None,
    ) -> dict:
        """Run a specialist sub-agent with a filtered tool set."""
        import types
        from src.agent import AgentCore

        # Build a filtered tool registry for this agent
        allowed_tools = AGENT_TOOL_MAP.get(agent_name)  # None = all tools
        if allowed_tools is not None:
            sub_registry = ToolRegistry()
            for tool_name in allowed_tools:
                tool = self._full_registry.get(tool_name)
                if tool:
                    sub_registry.register(tool)
        else:
            sub_registry = self._full_registry

        sub_agent = AgentCore(
            groq_client=self._client,
            memory=self._memory,
            tool_registry=sub_registry,
            max_steps=5,
            model=self._model,
        )

        tools_used = []

        # FIX #1: Track tools by wrapping sub_registry.execute with a
        # per-instance override that records every tool call.
        original_execute = sub_registry.__class__.execute

        def patched_execute(self_reg, tool_name: str, arguments: dict) -> str:
            tools_used.append(tool_name)
            return original_execute(self_reg, tool_name, arguments)

        sub_registry.execute = types.MethodType(patched_execute, sub_registry)

        # Set of irreversible tools to block in background/orchestrator default confirm
        BLOCKED_TOOLS = {"send_email", "browser_search_and_book", "delete_calendar_event", "cancel_task"}

        def default_confirm(tool_name: str, description: str) -> Any:
            if tool_name in BLOCKED_TOOLS:
                print(f"   ⚠️  Blocked irreversible tool in sub-agent background execution: {tool_name}")
                return json.dumps({
                    "status": "blocked",
                    "reason": "Background tasks cannot execute irreversible actions"
                })
            print(f"   🛡️ Sub-agent auto-approved: {tool_name}")
            return True

        actual_confirm = confirm_callback if confirm_callback is not None else default_confirm

        try:
            result = sub_agent.run(
                user_message=task,
                conversation_history=[],
                confirm_callback=actual_confirm,
                mode="chat",
                step_callback=step_callback,
            )
        except Exception as e:
            result = f"Sub-agent '{agent_name}' failed: {str(e)}"
        finally:
            # Restore: remove the instance override so the class method is used again
            try:
                del sub_registry.execute
            except AttributeError:
                pass

        return {"result": result, "tools_used": tools_used}

    def _synthesize_results(self, goal: str, results: List[dict]) -> str:
        """Synthesize multiple sub-agent results into a coherent final answer."""
        context = "\n\n".join(
            f"[{r['agent'].upper()} AGENT]: {r['result']}"
            for r in results
        )
        prompt = (
            f"The user's goal was: {goal}\n\n"
            f"Multiple agents completed sub-tasks:\n{context}\n\n"
            f"Synthesize a clear, helpful final response that addresses the user's original goal. "
            f"Be concise and practical."
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.2,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            # Fallback: concatenate results
            return "\n\n".join(f"**{r['agent']}**: {r['result']}" for r in results)
