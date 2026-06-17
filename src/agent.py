# src/agent.py
"""
Agent Core — The Brain.

Implements the agentic reasoning loop:
  1. Assemble context  (system prompt + memory + tools + history + user msg)
  2. Call LLM with tool definitions
  3. If text response → done
  4. If tool call → check guardrails → execute → feed result back → loop
  5. Safety brake: max N steps
"""

import json
import re
from typing import Callable, List, Optional

from src.memory import UserMemory
from src.tools import ToolRegistry


# Type alias for the confirmation callback supplied by main.py.
# Signature: confirm_callback(tool_name, description) -> bool
ConfirmCallback = Optional[Callable[[str, str], bool]]


class AgentCore:
    """The agentic reasoning loop that can call tools iteratively."""

    def __init__(
        self,
        groq_client,
        memory: UserMemory,
        tool_registry: ToolRegistry,
        max_steps: int = 5,
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
    ) -> str:
        """
        Run the full reasoning loop for a single user query.

        Args:
            user_message:          The transcribed user command.
            conversation_history:  Rolling conversation history (list of dicts).
            confirm_callback:      Called when a tool requires voice confirmation.
                                   Signature: (tool_name, description) -> bool.

        Returns:
            The final text response to speak back to the user.
        """
        messages = self._build_initial_messages(user_message, conversation_history)
        tool_defs = self._registry.get_tool_definitions()

        for step in range(self._max_steps):
            print(f"   🔄 Agent step {step + 1}/{self._max_steps}")

            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=tool_defs if tool_defs else None,
                    tool_choice="auto" if tool_defs else None,
                    max_tokens=400,
                    temperature=0.5,  # Lower temp for reliable tool use
                )
            except Exception as e:
                # ── Handle Groq's tool_use_failed error ───────────────
                # Groq sometimes can't parse its own model's raw function
                # call format: <function=tool_name{"arg": "val"}</function>
                # We parse it ourselves and execute the tool directly.
                parsed = self._parse_failed_tool_call(e)
                if parsed:
                    tool_name, arguments = parsed
                    print(f"   🔧 Tool call (recovered): {tool_name}({arguments})")

                    # Guardrails check
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

                    # Synthesize proper message history so the LLM can see the result
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
                    continue  # next iteration — LLM will see the tool result

                print(f"   ❌ LLM call failed: {e}")
                return "Something went wrong while I was thinking. Please try again."

            choice = response.choices[0]
            assistant_msg = choice.message

            # ── Case 1: LLM returned a text response (done) ──────────
            if not assistant_msg.tool_calls:
                final_text = assistant_msg.content or ""
                print(f"   ✅ Agent done (text response)")
                return final_text.strip()

            # ── Case 2: LLM wants to call tool(s) ────────────────────
            # Add the assistant's message (with tool_calls) to history
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

                # ── Guardrails: check if tool requires confirmation ───
                tool = self._registry.get(tool_name)
                if tool and tool.requires_confirmation and confirm_callback:
                    # Build a human-readable description of what we're about to do
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
                    # No confirmation needed — execute directly
                    result = self._registry.execute(tool_name, arguments)
                    print(f"   ✅ Tool result: {result[:200]}")

                # Feed tool result back to the LLM
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        # ── Safety brake: max steps exceeded ──────────────────────────
        print(f"   ⚠️ Agent hit max steps ({self._max_steps})")
        return (
            "I've been working on this for a while but couldn't finish. "
            "Could you try rephrasing your request?"
        )

    # ── Private helpers ───────────────────────────────────────────────────

    def _build_initial_messages(
        self, user_message: str, conversation_history: list
    ) -> list:
        """Assemble the full message list for the first LLM call."""
        # System prompt with memory facts
        facts_block = self._memory.get_facts_prompt()
        system_content = (
            "You are Nova, a helpful voice assistant with access to tools. "
            "Be concise — keep replies to 1-3 sentences since responses are spoken aloud.\n\n"
            "TOOL USAGE RULES:\n"
            "- ONLY call a tool when the user EXPLICITLY asks for something that requires it.\n"
            "- Use get_current_datetime ONLY when the user asks for the time/date.\n"
            "- Use web_search ONLY when the user asks to search or asks about current events/news.\n"
            "- Use get_weather ONLY when the user asks about weather.\n"
            "- Use set_reminder ONLY when the user asks to set a reminder or alarm.\n"
            "- For greetings, personal statements, general knowledge, or conversation, "
            "respond DIRECTLY without calling any tools.\n"
            "- When setting reminders, call get_current_datetime first to know the current time, "
            "then calculate the correct ISO-8601 timestamp for set_reminder.\n"
            "- NEVER call tools speculatively or 'just in case'.\n"
        )
        if facts_block:
            system_content += "\n" + facts_block

        messages = [{"role": "system", "content": system_content}]

        # Add conversation history
        messages.extend(conversation_history)

        # Add the current user message
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
            return f"set a reminder at {time_str} to {msg}"

        # Generic fallback
        args_str = ", ".join(f"{k}={v}" for k, v in arguments.items())
        return f"use the {tool_name} tool with {args_str}" if args_str else f"use the {tool_name} tool"

    @staticmethod
    def _parse_failed_tool_call(error) -> tuple:
        """
        Extract tool name and args from Groq's tool_use_failed error.

        Groq sometimes returns:
          <function=web_search{"query": "..."}</function>
        We parse that into ("web_search", {"query": "..."}).

        Returns (tool_name, arguments) or None.
        """
        try:
            error_str = str(error)
            if "tool_use_failed" not in error_str:
                return None

            # Extract the failed_generation content
            # Handles all formats:
            #   <function=web_search{"query": "..."}</function>
            #   <function=web_search[]{"query": "..."}</function>
            #   <function=web_search={"query": "..."}</function>
            match = re.search(
                r'<function=(\w+)[^\{]*(\{.*?\})\s*</function>',
                error_str,
            )
            if match:
                tool_name = match.group(1)
                arguments = json.loads(match.group(2))
                if not isinstance(arguments, dict):
                    arguments = {}
                return tool_name, arguments
        except Exception:
            pass
        return None

