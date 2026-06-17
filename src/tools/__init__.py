# src/tools/__init__.py
"""
Tool registration framework for the Nova agent.

Provides the `Tool` dataclass and `ToolRegistry` class that converts
our tool definitions to the OpenAI-compatible format expected by Groq's
function-calling API.
"""

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class Tool:
    """A single tool that the agent can invoke."""

    name: str
    description: str
    parameters: dict                  # JSON Schema for the tool's arguments
    handler: Callable                 # The actual Python function to run
    requires_confirmation: bool = False  # If True, ask user before executing


class ToolRegistry:
    """Registry that holds all available tools and provides them to the LLM."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    # ── Registration ──────────────────────────────────────────────────────

    def register(self, tool: Tool):
        """Register a tool.  Overwrites if the name already exists."""
        self._tools[tool.name] = tool

    # ── Lookup ────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())

    @property
    def count(self) -> int:
        return len(self._tools)

    # ── Groq / OpenAI format ──────────────────────────────────────────────

    def get_tool_definitions(self) -> List[dict]:
        """Return tool definitions in the OpenAI-compatible format for Groq."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    # ── Execution ─────────────────────────────────────────────────────────

    def execute(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool by name.  Returns a JSON string (result or error)."""
        tool = self._tools.get(tool_name)
        if tool is None:
            return json.dumps({
                "error": f"Unknown tool '{tool_name}'. Available tools: "
                         f"{', '.join(self._tools.keys())}"
            })
        if not isinstance(arguments, dict):
            arguments = {}
        try:
            result = tool.handler(**arguments)
            # Ensure we always return a string
            if not isinstance(result, str):
                result = json.dumps(result)
            return result
        except Exception as e:
            return json.dumps({"error": f"Tool '{tool_name}' failed: {str(e)}"})
