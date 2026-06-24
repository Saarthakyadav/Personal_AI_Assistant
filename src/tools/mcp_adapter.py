# src/tools/mcp_adapter.py
"""
MCP-Style Plugin Adapter for Nova.

Provides a lightweight Model Context Protocol-inspired plugin layer that groups
tools into named "servers" (e.g. 'calendar', 'email').  This matches the
Architecture v3 flowchart box: "MCP servers (plug-in) — calendar · email".

Not a full network-protocol MCP implementation, but provides the architectural
abstraction: tool grouping, server discovery, and unified routing.
"""

import json
from typing import Dict, List, Optional
from src.tools import Tool, ToolRegistry


class MCPServer:
    """A named group of tools that acts as a plugin server."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._tools: Dict[str, Tool] = {}

    def add_tool(self, tool: Tool):
        """Register a tool with this server."""
        self._tools[tool.name] = tool

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


class MCPPluginAdapter:
    """
    Manages multiple MCP-style plugin servers and registers their tools
    into the main ToolRegistry.
    """

    def __init__(self):
        self._servers: Dict[str, MCPServer] = {}

    def create_server(self, name: str, description: str) -> MCPServer:
        """Create and register a new plugin server."""
        server = MCPServer(name=name, description=description)
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
                    registry.register(tool)
                    count += 1
        return count

    def list_servers(self) -> List[dict]:
        """Return metadata for all registered servers."""
        return [server.to_dict() for server in self._servers.values()]

    def get_server(self, name: str) -> Optional[MCPServer]:
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
            return json.dumps({"error": f"MCP server '{server_name}' not found."})

        tool = server.get_tool(tool_name)
        if not tool:
            return json.dumps({
                "error": f"Tool '{tool_name}' not found on server '{server_name}'.",
                "available_tools": server.list_tools(),
            })

        try:
            result = tool.handler(**arguments)
            if not isinstance(result, str):
                result = json.dumps(result)
            return result
        except Exception as e:
            return json.dumps({"error": f"MCP tool '{tool_name}' failed: {str(e)}"})

    def __repr__(self):
        servers = ", ".join(
            f"{s.name}({s.tool_count})" for s in self._servers.values()
        )
        return f"MCPPluginAdapter(servers=[{servers}])"
