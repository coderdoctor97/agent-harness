"""Model Context Protocol (MCP) adapter and integration layer.

Provides a clean interface for registering, querying, and delegating to MCP
servers and tools in the agent harness environment.

When an MCP server is configured (via environment or config), tools and resources
provided by the server are registered and surfaced in the agent runtime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("agent_harness.web.mcp")


@dataclass
class MCPServerConfig:
    """Configuration for an external MCP server."""

    name: str
    transport: str = "stdio"  # "stdio" or "sse"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPToolDescriptor:
    """Description of a tool exposed by an MCP server."""

    name: str
    server_name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)


class MCPClientAdapter:
    """Adapter bridging MCP servers with the AgentHarness tool registry."""

    def __init__(self, servers: list[MCPServerConfig] | None = None) -> None:
        self._servers: dict[str, MCPServerConfig] = {
            s.name: s for s in (servers or [])
        }
        self._tools: dict[str, MCPToolDescriptor] = {}
        self._connected: bool = False

    @property
    def is_connected(self) -> bool:
        """Whether at least one MCP server is active."""
        return self._connected and bool(self._servers)

    def register_server(self, server: MCPServerConfig) -> None:
        """Register a new MCP server configuration."""
        self._servers[server.name] = server

    def list_servers(self) -> list[dict[str, Any]]:
        """Return registered MCP servers and their statuses."""
        return [
            {
                "name": s.name,
                "transport": s.transport,
                "enabled": s.enabled,
                "url": s.url or None,
            }
            for s in self._servers.values()
        ]

    def list_tools(self) -> list[dict[str, Any]]:
        """List all tools discovered from connected MCP servers."""
        return [
            {
                "name": t.name,
                "server": t.server_name,
                "description": t.description,
                "capabilities": t.capabilities,
            }
            for t in self._tools.values()
        ]

    def status(self) -> dict[str, Any]:
        """Return MCP integration status."""
        return {
            "available": True,
            "connected": self.is_connected,
            "servers_count": len(self._servers),
            "tools_count": len(self._tools),
            "servers": self.list_servers(),
        }
