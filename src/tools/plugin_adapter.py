# src/tools/plugin_adapter.py
"""
Plugin Adapter for Nova.

Provides a lightweight plugin layer that groups
tools into named "servers" (e.g. 'calendar', 'email').  This matches the
Architecture v3 flowchart box: "Plugin servers (plug-in) — calendar · email".

Provides the architectural abstraction: tool grouping, server discovery, and unified routing.
"""

import json
from typing import Dict, List, Optional, Callable
from src.tools import Tool, ToolRegistry


class PluginServer:
    """A named group of tools that acts as a plugin server."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._tools: Dict[str, Tool] = {}
        self._original_handlers: Dict[str, Callable] = {}

    def add_tool(self, tool: Tool):
        """Register a tool with this server."""
        self._tools[tool.name] = tool
        self._original_handlers[tool.name] = tool.handler

    def list_tools(self) -> List[str]:
        """Return the names of all tools on this server."""
        return list(self._tools.keys())

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    def to_dict(self) -> dict:
        return {
            "server": self.name,
            "description": self.description,
            "tools": self.list_tools(),
            "tool_count": self.tool_count,
        }


class PluginAdapter:
    """
    Manages multiple plugin servers and registers their tools
    into the main ToolRegistry.
    """

    def __init__(self):
        self._servers: Dict[str, PluginServer] = {}

    def create_server(self, name: str, description: str) -> PluginServer:
        """Create and register a new plugin server."""
        server = PluginServer(name=name, description=description)
        self._servers[name] = server
        return server

    def register_tools(self, server_name: str, tools: List[Tool]):
        """Add tools to a named server. Creates the server if it doesn't exist."""
        if server_name not in self._servers:
            self.create_server(server_name, f"{server_name} plugin server")
        server = self._servers[server_name]
        for tool in tools:
            server.add_tool(tool)

    def install_into_registry(self, registry: ToolRegistry):
        """Register all tools from all servers into the main ToolRegistry."""
        count = 0
        for server in self._servers.values():
            for tool_name in server.list_tools():
                tool = server.get_tool(tool_name)
                if tool:
                    # Wrap handler to route via Plugin execute
                    def make_plugin_handler(s_name=server.name, t_name=tool_name):
                        def plugin_handler(*args, **kwargs):
                            print(f"🔌 [Plugin Route] server: '{s_name}' -> tool: '{t_name}'")
                            return self.execute(s_name, t_name, kwargs)
                        return plugin_handler

                    tool.handler = make_plugin_handler()
                    registry.register(tool)
                    count += 1
        return count

    def list_servers(self) -> List[dict]:
        """Return metadata for all registered servers."""
        return [server.to_dict() for server in self._servers.values()]

    def get_server(self, name: str) -> Optional[PluginServer]:
        return self._servers.get(name)

    def get_server_for_tool(self, tool_name: str) -> Optional[str]:
        """Find which server owns a given tool name."""
        for server in self._servers.values():
            if tool_name in server.list_tools():
                return server.name
        return None

    def execute(self, server_name: str, tool_name: str, arguments: dict) -> str:
        """Execute a tool via its server. Returns JSON result or error."""
        server = self._servers.get(server_name)
        if not server:
            return json.dumps({"error": f"Plugin server '{server_name}' not found."})

        tool = server.get_tool(tool_name)
        if not tool:
            return json.dumps({
                "error": f"Tool '{tool_name}' not found on server '{server_name}'.",
                "available_tools": server.list_tools(),
            })

        original_handler = server._original_handlers.get(tool_name)
        if not original_handler:
            return json.dumps({"error": f"Original handler not found for '{tool_name}' on server '{server_name}'."})

        try:
            result = original_handler(**arguments)
            if not isinstance(result, str):
                result = json.dumps(result)
            return result
        except Exception as e:
            return json.dumps({"error": f"Plugin tool '{tool_name}' failed: {str(e)}"})

    def __repr__(self):
        servers = ", ".join(
            f"{s.name}({s.tool_count})" for s in self._servers.values()
        )
        return f"PluginAdapter(servers=[{servers}])"
