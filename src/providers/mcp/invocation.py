"""Invocation Handler — core tool execution with timeout, retry, circuit breaker.

Routes tool calls through the MCP client with resilience patterns.

See docs/architecture/06-mcp-tools.md Section 2.2.5.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Protocol, runtime_checkable

from src.core.errors import ToolError, ToolTimeoutError
from src.core.models import ToolCall, ToolResult
from src.providers.mcp.circuit_breaker import CircuitBreaker
from src.providers.mcp.models import ToolInfo
from src.providers.mcp.result_processor import ResultProcessor

logger = logging.getLogger(__name__)


@runtime_checkable
class MCPClient(Protocol):
    """Minimal interface for an MCP client connection."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server. Returns raw MCP result dict."""
        ...


class InvocationHandler:
    """Handles tool invocation with timeout, retry, and circuit breaker.

    Implements the ToolRuntime protocol from core/protocols.py when
    combined with ToolManager routing.
    """

    def __init__(
        self,
        circuit_breaker: CircuitBreaker,
        result_processor: ResultProcessor,
    ) -> None:
        self._cb = circuit_breaker
        self._rp = result_processor

    async def invoke(
        self,
        client: MCPClient,
        tool_call: ToolCall,
        tool_info: ToolInfo,
        timeout_ms: int | None = None,
    ) -> ToolResult:
        """Execute a tool call through the full invocation pipeline.

        1. Circuit breaker check
        2. Execute with retry (if idempotent) or timeout
        3. Record success/failure in circuit breaker
        4. Process and normalize result
        """
        server_id = tool_info.server_id
        effective_timeout = timeout_ms or tool_info.default_timeout_ms
        start = time.monotonic()

        # 1. Circuit breaker check
        if not self._cb.allow_request(server_id):
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content="Tool server temporarily unavailable (circuit breaker open)",
                is_error=True,
                latency_ms=0.0,
            )

        # 2. Execute
        try:
            if tool_info.idempotent and tool_info.default_timeout_ms > 0:
                raw = await self._invoke_with_retry(
                    client, tool_call, tool_info, effective_timeout,
                )
            else:
                raw = await self._invoke_with_timeout(
                    client, tool_call, effective_timeout,
                )
        except ToolTimeoutError:
            self._cb.record_failure(server_id)
            latency = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=f"Tool '{tool_call.name}' timed out after {effective_timeout}ms",
                is_error=True,
                latency_ms=latency,
            )
        except Exception as exc:
            self._cb.record_failure(server_id)
            latency = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=f"Tool execution error: {exc}",
                is_error=True,
                latency_ms=latency,
            )

        # 3. Record success
        self._cb.record_success(server_id)
        latency = (time.monotonic() - start) * 1000

        # 4. Process result
        result = self._rp.process(raw, tool_call.id, tool_info)
        result.latency_ms = latency
        return result

    async def _invoke_with_timeout(
        self,
        client: MCPClient,
        tool_call: ToolCall,
        timeout_ms: int,
    ) -> dict[str, Any]:
        """Call tool with asyncio timeout."""
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                return await client.call_tool(tool_call.name, tool_call.arguments)
        except asyncio.TimeoutError:
            raise ToolTimeoutError(tool_call.name, timeout_ms)

    async def _invoke_with_retry(
        self,
        client: MCPClient,
        tool_call: ToolCall,
        tool_info: ToolInfo,
        timeout_ms: int,
    ) -> dict[str, Any]:
        """Call tool with retries for idempotent tools.

        Retry on timeout and server errors. Do NOT retry on client errors.
        """
        max_retries = min(tool_info.default_timeout_ms // 1000, 3) if tool_info.default_timeout_ms else 2
        max_retries = max(1, max_retries)
        backoff = 1.0
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                return await self._invoke_with_timeout(client, tool_call, timeout_ms)
            except ToolTimeoutError as exc:
                last_exc = exc
                if attempt < max_retries:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                    continue
                raise
            except ToolError as exc:
                # Don't retry non-retryable tool errors
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                    continue
                raise

        raise last_exc  # type: ignore[misc]
