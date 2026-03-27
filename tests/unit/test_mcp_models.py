"""Tests for MCP data models."""

import pytest

from src.providers.mcp.models import (
    DiscoveryResult,
    HealthStatus,
    MCPServerConfig,
    ToolInfo,
)


class TestToolInfo:
    def test_defaults(self):
        t = ToolInfo(name="search")
        assert t.name == "search"
        assert t.status == "active"
        assert t.risk_level == "low"
        assert t.input_schema == {"type": "object", "properties": {}}

    def test_full_construction(self):
        t = ToolInfo(
            id="mcp:github:create_issue",
            name="create_issue",
            server_id="github-server",
            namespace="mcp:github",
            description="Create a new issue",
            input_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            risk_level="medium",
            requires_approval=True,
            tenant_id="t1",
        )
        assert t.id == "mcp:github:create_issue"
        assert t.requires_approval is True


class TestMCPServerConfig:
    def test_stdio_config(self):
        cfg = MCPServerConfig(
            name="postgres",
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-postgres"],
        )
        assert cfg.transport == "stdio"
        assert cfg.command == "npx"
        assert cfg.status == "disconnected"

    def test_sse_config(self):
        cfg = MCPServerConfig(
            name="remote",
            transport="sse",
            url="https://mcp.example.com/v1",
            headers={"Authorization": "Bearer token"},
        )
        assert cfg.url is not None
        assert cfg.connect_timeout_ms == 10000

    def test_defaults(self):
        cfg = MCPServerConfig()
        assert cfg.max_retries == 3
        assert cfg.sandbox_level == "none"
        assert cfg.auto_start is True


class TestDiscoveryResult:
    def test_empty(self):
        r = DiscoveryResult(server_id="s1")
        assert r.tools_found == []
        assert r.tools_added == 0

    def test_with_tools(self):
        tools = [ToolInfo(name="a"), ToolInfo(name="b")]
        r = DiscoveryResult(server_id="s1", tools_found=tools, tools_added=2)
        assert len(r.tools_found) == 2


class TestHealthStatus:
    def test_defaults(self):
        h = HealthStatus()
        assert h.status == "healthy"
        assert h.consecutive_failures == 0

    def test_unhealthy(self):
        h = HealthStatus(status="unhealthy", consecutive_failures=5, latency_ms=5000)
        assert h.consecutive_failures == 5
