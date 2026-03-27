"""Tool Manager — service layer for tool registry, invocation, and schema conversion.

Entry point for the Executor and API layer. Orchestrates ToolRegistry (PG),
SchemaConverter, InvocationHandler, and MCP clients.

See docs/architecture/06-mcp-tools.md Section 2.1.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.models import ToolCall, ToolResult
from src.providers.mcp.circuit_breaker import CircuitBreaker
from src.providers.mcp.invocation import InvocationHandler, MCPClient
from src.providers.mcp.models import ToolInfo
from src.providers.mcp.result_processor import ResultProcessor
from src.providers.mcp.schema_converter import SchemaConverter

logger = logging.getLogger(__name__)


class ToolManager:
    """Service layer for all tool operations.

    Manages:
    - Tool registry (in-memory cache backed by PG via ToolRepository)
    - Schema conversion for LLM providers
    - Tool invocation through MCP clients
    """

    def __init__(
        self,
        schema_converter: SchemaConverter | None = None,
        invocation_handler: InvocationHandler | None = None,
        tool_repo: Any | None = None,  # ToolRepository (PG)
    ) -> None:
        self._converter = schema_converter or SchemaConverter()
        self._invocation = invocation_handler or InvocationHandler(
            circuit_breaker=CircuitBreaker(),
            result_processor=ResultProcessor(),
        )
        self._repo = tool_repo
        # In-memory tool registry: {tenant_id: {tool_id: ToolInfo}}
        self._registry: dict[str, dict[str, ToolInfo]] = {}
        # MCP client connections: {(tenant_id, server_id): MCPClient}
        self._clients: dict[tuple[str, str], MCPClient] = {}

    # ------------------------------------------------------------------
    # Registry operations
    # ------------------------------------------------------------------

    def register(self, tool: ToolInfo) -> None:
        """Register or update a tool in the in-memory registry."""
        tenant = self._registry.setdefault(tool.tenant_id, {})
        tenant[tool.id] = tool

    def unregister(self, tenant_id: str, tool_id: str) -> None:
        """Remove a tool from the registry."""
        tenant = self._registry.get(tenant_id, {})
        tenant.pop(tool_id, None)

    def list_tools(self, tenant_id: str, agent_id: str | None = None) -> list[ToolInfo]:
        """List active tools for a tenant."""
        tenant = self._registry.get(tenant_id, {})
        tools = [t for t in tenant.values() if t.status == "active"]
        return tools

    def get_tool(self, tenant_id: str, tool_id: str) -> ToolInfo | None:
        """Get a single tool by ID."""
        return self._registry.get(tenant_id, {}).get(tool_id)

    # ------------------------------------------------------------------
    # Schema conversion for LLM
    # ------------------------------------------------------------------

    def get_tool_schemas_for_llm(
        self,
        tenant_id: str,
        agent_id: str,
        provider: str = "anthropic",
    ) -> list[dict[str, Any]]:
        """Get tool schemas formatted for a specific LLM provider."""
        tools = self.list_tools(tenant_id, agent_id)
        return self._converter.convert_batch(tools, provider)

    # ------------------------------------------------------------------
    # MCP client management
    # ------------------------------------------------------------------

    def register_client(self, tenant_id: str, server_id: str, client: MCPClient) -> None:
        """Register an MCP client connection."""
        self._clients[(tenant_id, server_id)] = client

    def unregister_client(self, tenant_id: str, server_id: str) -> None:
        """Remove an MCP client connection."""
        self._clients.pop((tenant_id, server_id), None)

    def get_client(self, tenant_id: str, server_id: str) -> MCPClient | None:
        """Get an MCP client for a server."""
        return self._clients.get((tenant_id, server_id))

    # ------------------------------------------------------------------
    # Tool invocation (implements ToolRuntime protocol)
    # ------------------------------------------------------------------

    async def invoke(
        self,
        tenant_id: str,
        session_id: str,
        tool_call: ToolCall,
    ) -> ToolResult:
        """Full tool invocation pipeline.

        1. Resolve tool from registry
        2. Get MCP client for the tool's server
        3. Invoke via InvocationHandler (timeout, retry, circuit breaker)
        4. Return processed result
        """
        # 1. Resolve tool
        tool_info = self._resolve_tool(tenant_id, tool_call.name)
        if tool_info is None:
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=f"Tool '{tool_call.name}' not found in registry",
                is_error=True,
            )

        # 2. Get client
        client = self.get_client(tenant_id, tool_info.server_id)
        if client is None:
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=f"No MCP client connected for server '{tool_info.server_id}'",
                is_error=True,
            )

        # 3. Invoke
        return await self._invocation.invoke(client, tool_call, tool_info)

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def register_tools_from_discovery(
        self,
        tenant_id: str,
        server_id: str,
        raw_tools: list[dict[str, Any]],
    ) -> list[ToolInfo]:
        """Register tools discovered from an MCP server.

        Converts raw MCP tools/list response into ToolInfo objects
        and adds them to the registry.
        """
        registered: list[ToolInfo] = []
        namespace = f"mcp:{server_id}"

        for raw in raw_tools:
            tool_id = f"{namespace}:{raw.get('name', 'unknown')}"
            tool = ToolInfo(
                id=tool_id,
                name=raw.get("name", "unknown"),
                server_id=server_id,
                namespace=namespace,
                description=raw.get("description", ""),
                input_schema=raw.get("inputSchema", {"type": "object", "properties": {}}),
                tenant_id=tenant_id,
            )
            self.register(tool)
            registered.append(tool)

        return registered

    def update_tool_status(self, tenant_id: str, tool_id: str, status: str) -> None:
        """Update a tool's status (active/degraded/unavailable)."""
        tool = self.get_tool(tenant_id, tool_id)
        if tool:
            tool.status = status  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_tool(self, tenant_id: str, tool_name: str) -> ToolInfo | None:
        """Find a tool by name (supports both raw name and sanitized name)."""
        tenant = self._registry.get(tenant_id, {})
        # Direct ID match
        if tool_name in tenant:
            return tenant[tool_name]
        # Match by name field
        for tool in tenant.values():
            if tool.name == tool_name:
                return tool
            # Match sanitized name (namespace__name format)
            sanitized = self._converter._sanitize_name(tool.name, tool.namespace)
            if sanitized == tool_name:
                return tool
        return None
