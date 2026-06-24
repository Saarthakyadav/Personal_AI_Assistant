# src/agent.py
"""
Agent Core — The Brain.

Implements the agentic reasoning loop:
  1. Assemble context  (system prompt + memory + tools + history + user msg)
  2. Call LLM with tool definitions
  3. If text response → done
  4. If tool call → check guardrails → execute → feed result back → loop
  5. Safety brake: max N steps

Phase 1 fixes:
  - System prompt no longer duplicates "You are Nova..." in voice mode
  - _parse_failed_tool_call uses a balanced-brace JSON extractor instead of
    a greedy regex that breaks on nested objects
  - step_callback parameter for live UI updates (Phase 3+)
"""

import json
import re
from typing import Callable, List, Optional

from src.memory import UserMemory
from src.tools import ToolRegistry


# Type aliases
ConfirmCallback = Optional[Callable[[str, str], bool]]
StepCallback = Optional[Callable[[str, str], None]]   # (event_type, detail) → None


class AgentCore:
    """The agentic reasoning loop that can call tools iteratively."""

    def __init__(
        self,
        groq_client,
        memory: UserMemory,
        tool_registry: ToolRegistry,
        max_steps: int = 10,
        model: str = "llama-3.3-70b-versatile",
    ):
        self._client = groq_client
        self._memory = memory
        self._registry = tool_registry
        self._max_steps = max_steps
        self._model = model

    # ── Public API ────────────────────────────────────────────────────────

    def run(
        self,
        user_message: str,
        conversation_history: list,
        confirm_callback: ConfirmCallback = None,
        mode: str = "chat",
        step_callback: StepCallback = None,
    ) -> str:
        """
        Run the full reasoning loop for a single user query.

        Args:
            user_message:          The transcribed user command.
            conversation_history:  Rolling conversation history (list of dicts).
            confirm_callback:      Called when a tool requires voice confirmation.
                                   Signature: (tool_name, description) -> bool.
            mode:                  The interaction mode ("chat" or "voice").
            step_callback:         Optional hook called on each step for live UI.
                                   Signature: (event_type, detail) -> None.

        Returns:
            The final text response to speak back to the user.
        """
        messages = self._build_initial_messages(user_message, conversation_history, mode)
        tool_defs = self._registry.get_tool_definitions()

        if step_callback:
            step_callback("start", f"Processing: {user_message[:80]}")

        for step in range(self._max_steps):
            print(f"   🔄 Agent step {step + 1}/{self._max_steps}")
            if step_callback:
                step_callback("step", f"Reasoning step {step + 1}")

            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=tool_defs if tool_defs else None,
                    tool_choice="auto" if tool_defs else None,
                    parallel_tool_calls=False if tool_defs else None,
                    max_tokens=1500 if mode == "chat" else 400,
                    temperature=0.2,
                )
            except Exception as e:
                # ── Handle Groq's tool_use_failed error ───────────────
                parsed = self._parse_failed_tool_call(e)
                if parsed:
                    tool_name, arguments = parsed
                    print(f"   🔧 Tool call (recovered): {tool_name}({arguments})")
                    if step_callback:
                        step_callback("tool", f"Using tool: {tool_name}")

                    tool = self._registry.get(tool_name)
                    if tool and tool.requires_confirmation and confirm_callback:
                        description = self._describe_tool_call(tool_name, arguments)
                        confirmed = confirm_callback(tool_name, description)
                        if not confirmed:
                            result = json.dumps({"status": "cancelled", "reason": "User declined."})
                            print(f"   🚫 User declined {tool_name}")
                        else:
                            result = self._registry.execute(tool_name, arguments)
                            print(f"   ✅ Tool result: {result[:200]}")
                    else:
                        result = self._registry.execute(tool_name, arguments)
                        print(f"   ✅ Tool result: {result[:200]}")

                    synth_id = f"call_recovered_{step}"
                    messages.append({
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": synth_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments),
                            },
                        }],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": synth_id,
                        "content": result,
                    })
                    continue

                print(f"   ❌ LLM call failed: {e}")
                return "Something went wrong while I was thinking. Please try again."

            choice = response.choices[0]
            assistant_msg = choice.message

            # ── Case 1: LLM returned a text response (done) ──────────
            if not assistant_msg.tool_calls:
                final_text = assistant_msg.content or ""
                print(f"   ✅ Agent done (text response)")
                if step_callback:
                    step_callback("done", "Response ready")
                return final_text.strip()

            # ── Case 2: LLM wants to call tool(s) ────────────────────
            messages.append(self._serialize_assistant_message(assistant_msg))

            for tool_call in assistant_msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                if not isinstance(arguments, dict):
                    arguments = {}

                print(f"   🔧 Tool call: {tool_name}({arguments})")
                if step_callback:
                    step_callback("tool", f"Using tool: {tool_name}")

                # ── Guardrails: check if tool requires confirmation ───
                tool = self._registry.get(tool_name)
                if tool and tool.requires_confirmation and confirm_callback:
                    description = self._describe_tool_call(tool_name, arguments)
                    confirmed = confirm_callback(tool_name, description)
                    if not confirmed:
                        result = json.dumps({
                            "status": "cancelled",
                            "reason": "User declined confirmation."
                        })
                        print(f"   🚫 User declined {tool_name}")
                    else:
                        result = self._registry.execute(tool_name, arguments)
                        print(f"   ✅ Tool result: {result[:200]}")
                else:
                    result = self._registry.execute(tool_name, arguments)
                    print(f"   ✅ Tool result: {result[:200]}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        # ── Safety brake: max steps exceeded ──────────────────────────
        print(f"   ⚠️ Agent hit max steps ({self._max_steps})")
        if step_callback:
            step_callback("error", "Max steps exceeded")
        return (
            "I've been working on this for a while but couldn't finish. "
            "Could you try rephrasing your request?"
        )

    # ── Private helpers ───────────────────────────────────────────────────

    def _build_initial_messages(
        self, user_message: str, conversation_history: list, mode: str = "chat"
    ) -> list:
        """Assemble the full message list for the first LLM call."""
        facts_block = self._memory.get_facts_prompt()

        # BUG FIX #5: voice mode no longer re-declares "You are Nova..." — it
        # is already in the shared system header below.
        if mode == "voice":
            length_hint = "Be concise — keep replies to 1-3 sentences since responses are spoken aloud."
        else:
            length_hint = (
                "For anything covered by your training — general knowledge, explanations, "
                "coding, math, creative writing — answer fully and directly WITHOUT calling tools. "
                "Tools are optional helpers for live data (web, weather, reminders, PDFs, browser)."
            )

        system_content = (
            "You are Nova, a helpful AI assistant with access to powerful tools. "
            f"{length_hint}\n\n"
            "TOOL USAGE RULES:\n"
            "- ONLY call a tool when the user EXPLICITLY asks for something that requires it.\n"
            "- Use get_current_datetime ONLY when the user asks for the time/date.\n"
            "- Use web_search ONLY when the user asks to search or asks about current events/news.\n"
            "- Use get_weather ONLY when the user asks about weather.\n"
            "- Use set_reminder ONLY when the user asks to set a reminder or alarm.\n"
            "- Use search_documents when the user asks about an uploaded PDF document.\n"
            "- Use browser_navigate / browser_search_and_book for web automation tasks.\n"
            "- Use draft_email / send_email for email tasks.\n"
            "- Use list_emails when the user asks to check, read, or view their emails.\n"
            "- Use create_calendar_event for scheduling.\n"
            "- For greetings, personal statements, general knowledge, respond DIRECTLY without tools.\n"
            "- When setting reminders, call get_current_datetime FIRST, THEN set_reminder.\n"
            "- NEVER call tools speculatively or 'just in case'.\n"
            "- For irreversible actions (book, send, delete), ALWAYS explain what you will do "
            "before calling the tool — the guardrail system will ask the user to confirm.\n"
        )
        if facts_block:
            system_content += "\n" + facts_block

        messages = [{"role": "system", "content": system_content}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})
        return messages

    @staticmethod
    def _serialize_assistant_message(msg) -> dict:
        """Convert a Groq assistant message object to a serializable dict."""
        serialized = {
            "role": "assistant",
            "content": msg.content or "",
        }
        if msg.tool_calls:
            serialized["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        return serialized

    @staticmethod
    def _describe_tool_call(tool_name: str, arguments: dict) -> str:
        """Build a human-readable description for the confirmation prompt."""
        if tool_name == "set_reminder":
            msg = arguments.get("message", "something")
            time_str = arguments.get("reminder_time", "an unknown time")
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(time_str)
                time_str = dt.strftime("%I:%M %p")
            except (ValueError, ImportError):
                pass
            return f"set a reminder at {time_str} to '{msg}'"

        if tool_name == "send_email":
            to = arguments.get("to", "?")
            subject = arguments.get("subject", "?")
            return f"send an email to {to} with subject '{subject}'"

        if tool_name == "browser_search_and_book":
            site = arguments.get("site", "the website")
            task = arguments.get("task_type", "book")
            return f"{task} on {site}"

        if tool_name == "create_calendar_event":
            title = arguments.get("title", "an event")
            start = arguments.get("start", "?")
            return f"create a calendar event '{title}' at {start}"

        if tool_name == "delete_calendar_event":
            return f"delete calendar event {arguments.get('event_id', '?')}"

        # Generic fallback
        args_str = ", ".join(f"{k}={v}" for k, v in arguments.items())
        return f"use {tool_name}({args_str})" if args_str else f"use {tool_name}"

    @staticmethod
    def _parse_failed_tool_call(error) -> tuple:
        """
        Extract tool name and args from Groq's tool_use_failed error.

        BUG FIX #7: Use a balanced-brace JSON extractor instead of .*? which
        fails on nested objects like {"details": {"from": "DEL", "to": "BOM"}}.
        """
        try:
            error_str = str(error)
            if "tool_use_failed" not in error_str:
                return None

            # 1. Extract tool name
            name_match = re.search(r'<function=(\w+)', error_str)
            if not name_match:
                return None
            tool_name = name_match.group(1)

            # 2. Find first '{' after the tool name and walk forward counting braces
            start_idx = error_str.find('{', name_match.end())
            if start_idx == -1:
                return None

            depth = 0
            for i, ch in enumerate(error_str[start_idx:], start_idx):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        json_str = error_str[start_idx:i + 1]
                        arguments = json.loads(json_str)
                        if not isinstance(arguments, dict):
                            arguments = {}
                        return tool_name, arguments

        except Exception:
            pass
        return None
