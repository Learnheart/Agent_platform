"""Data models for the MCP & Tool System.

Canonical definitions from docs/architecture/06-mcp-tools.md Section 2.1.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# Tool Info — tool registry entry
# ============================================================


class ToolInfo(BaseModel):
    """Full metadata for a registered tool."""

    id: str = ""
    name: str
    server_id: str = ""
    namespace: str = ""
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    output_schema: dict[str, Any] | None = None
    execution_mode: Literal["sync", "async"] = "sync"
    default_timeout_ms: int = 30000
    estimated_latency_ms: int | None = None
    estimated_cost: float | None = None
    idempotent: bool = False
    permission_scope: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    requires_approval: bool = False
    tenant_id: str = ""
    visibility: Literal["platform", "tenant", "agent"] = "tenant"
    discovered_at: datetime = Field(default_factory=_now)
    last_verified_at: datetime = Field(default_factory=_now)
    status: Literal["active", "degraded", "unavailable"] = "active"


# ============================================================
# MCP Server Configuration
# ============================================================


class MCPServerConfig(BaseModel):
    """Configuration for an MCP server connection."""

    id: str = Field(default_factory=_uuid)
    tenant_id: str = ""
    name: str = ""
    description: str = ""
    transport: Literal["stdio", "sse", "streamable_http"] = "stdio"
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    connect_timeout_ms: int = 10000
    request_timeout_ms: int = 30000
    max_retries: int = 3
    retry_backoff_ms: int = 1000
    auto_start: bool = True
    max_restarts: int = 5
    health_check_interval_seconds: int = 60
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None
    sandbox_level: Literal["none", "process", "container"] = "none"
    status: Literal["connected", "connecting", "disconnected", "error"] = "disconnected"
    last_connected_at: datetime | None = None
    last_error: str | None = None


# ============================================================
# Discovery Result
# ============================================================


class DiscoveryResult(BaseModel):
    """Result of discovering tools from an MCP server."""

    server_id: str
    tools_found: list[ToolInfo] = Field(default_factory=list)
    tools_added: int = 0
    tools_updated: int = 0
    tools_removed: int = 0
    errors: list[str] = Field(default_factory=list)


# ============================================================
# Health Status
# ============================================================


class HealthStatus(BaseModel):
    """Health check result for an MCP server."""

    status: Literal["healthy", "degraded", "unhealthy"] = "healthy"
    latency_ms: float = 0.0
    last_check: datetime = Field(default_factory=_now)
    consecutive_failures: int = 0
