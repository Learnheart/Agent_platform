"""Tests for ToolManager — service layer for tool operations."""

from unittest.mock import AsyncMock

import pytest

from src.core.models import ToolCall
from src.providers.mcp.circuit_breaker import CircuitBreaker
from src.providers.mcp.invocation import InvocationHandler
from src.providers.mcp.models import ToolInfo
from src.providers.mcp.result_processor import ResultProcessor
from src.providers.mcp.schema_converter import SchemaConverter
from src.providers.mcp.tool_manager import ToolManager


def _tool(**overrides) -> ToolInfo:
    defaults = dict(
        id="mcp:github:create_issue",
        name="create_issue",
        server_id="github-server",
        namespace="mcp:github",
        description="Create a new issue",
        input_schema={"type": "object", "properties": {"title": {"type": "string"}}},
        tenant_id="t1",
        status="active",
    )
    defaults.update(overrides)
    return ToolInfo(**defaults)


@pytest.fixture
def manager() -> ToolManager:
    return ToolManager()


# --- Registry ---


class TestRegistry:
    def test_register_and_get(self, manager: ToolManager):
        tool = _tool()
        manager.register(tool)
        result = manager.get_tool("t1", "mcp:github:create_issue")
        assert result is not None
        assert result.name == "create_issue"

    def test_list_tools(self, manager: ToolManager):
        manager.register(_tool(id="t1", name="a"))
        manager.register(_tool(id="t2", name="b"))
        tools = manager.list_tools("t1")
        assert len(tools) == 2

    def test_list_excludes_unavailable(self, manager: ToolManager):
        manager.register(_tool(id="t1", status="active"))
        manager.register(_tool(id="t2", status="unavailable"))
        tools = manager.list_tools("t1")
        assert len(tools) == 1

    def test_unregister(self, manager: ToolManager):
        manager.register(_tool())
        manager.unregister("t1", "mcp:github:create_issue")
        assert manager.get_tool("t1", "mcp:github:create_issue") is None

    def test_get_nonexistent(self, manager: ToolManager):
        assert manager.get_tool("t1", "nonexistent") is None


# --- Schema conversion ---


class TestSchemaConversion:
    def test_get_schemas_anthropic(self, manager: ToolManager):
        manager.register(_tool())
        schemas = manager.get_tool_schemas_for_llm("t1", "a1", provider="anthropic")
        assert len(schemas) == 1
        assert "input_schema" in schemas[0]

    def test_get_schemas_openai(self, manager: ToolManager):
        manager.register(_tool())
        schemas = manager.get_tool_schemas_for_llm("t1", "a1", provider="openai")
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"

    def test_empty_registry_returns_empty(self, manager: ToolManager):
        schemas = manager.get_tool_schemas_for_llm("t1", "a1")
        assert schemas == []


# --- Client management ---


class TestClientManagement:
    def test_register_and_get_client(self, manager: ToolManager):
        client = AsyncMock()
        manager.register_client("t1", "s1", client)
        assert manager.get_client("t1", "s1") is client

    def test_unregister_client(self, manager: ToolManager):
        client = AsyncMock()
        manager.register_client("t1", "s1", client)
        manager.unregister_client("t1", "s1")
        assert manager.get_client("t1", "s1") is None


# --- Tool invocation ---


class TestInvocation:
    @pytest.mark.asyncio
    async def test_invoke_success(self, manager: ToolManager):
        tool = _tool()
        manager.register(tool)
        client = AsyncMock()
        client.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "Issue created"}],
            "isError": False,
        })
        manager.register_client("t1", "github-server", client)

        result = await manager.invoke("t1", "s1", ToolCall(id="tc1", name="create_issue", arguments={"title": "Bug"}))

        assert result.content == "Issue created"
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_invoke_tool_not_found(self, manager: ToolManager):
        result = await manager.invoke("t1", "s1", ToolCall(id="tc1", name="unknown", arguments={}))
        assert result.is_error is True
        assert "not found" in result.content

    @pytest.mark.asyncio
    async def test_invoke_no_client(self, manager: ToolManager):
        manager.register(_tool())
        result = await manager.invoke("t1", "s1", ToolCall(id="tc1", name="create_issue", arguments={}))
        assert result.is_error is True
        assert "No MCP client" in result.content

    @pytest.mark.asyncio
    async def test_invoke_resolves_by_sanitized_name(self, manager: ToolManager):
        tool = _tool()
        manager.register(tool)
        client = AsyncMock()
        client.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
        })
        manager.register_client("t1", "github-server", client)

        # Use sanitized name (github__create_issue)
        result = await manager.invoke("t1", "s1", ToolCall(id="tc1", name="github__create_issue", arguments={}))
        assert result.is_error is False


# --- Discovery registration ---


class TestDiscoveryRegistration:
    def test_register_from_discovery(self, manager: ToolManager):
        raw_tools = [
            {"name": "query", "description": "Run SQL query", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "list_tables", "description": "List tables", "inputSchema": {"type": "object", "properties": {}}},
        ]
        registered = manager.register_tools_from_discovery("t1", "db-server", raw_tools)

        assert len(registered) == 2
        assert manager.get_tool("t1", "mcp:db-server:query") is not None
        assert manager.get_tool("t1", "mcp:db-server:list_tables") is not None

    def test_discovery_sets_namespace(self, manager: ToolManager):
        raw_tools = [{"name": "search", "description": "Search"}]
        registered = manager.register_tools_from_discovery("t1", "brave", raw_tools)
        assert registered[0].namespace == "mcp:brave"


# --- Tool status ---


class TestToolStatus:
    def test_update_status(self, manager: ToolManager):
        manager.register(_tool())
        manager.update_tool_status("t1", "mcp:github:create_issue", "degraded")
        tool = manager.get_tool("t1", "mcp:github:create_issue")
        assert tool.status == "degraded"
