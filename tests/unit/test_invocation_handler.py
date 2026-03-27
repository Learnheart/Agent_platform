"""Tests for InvocationHandler — tool execution with resilience."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.core.models import ToolCall
from src.providers.mcp.circuit_breaker import CircuitBreaker, CircuitState
from src.providers.mcp.invocation import InvocationHandler
from src.providers.mcp.models import ToolInfo
from src.providers.mcp.result_processor import ResultProcessor


def _tool_call(**overrides) -> ToolCall:
    defaults = dict(id="tc1", name="query", arguments={"sql": "SELECT 1"})
    defaults.update(overrides)
    return ToolCall(**defaults)


def _tool_info(**overrides) -> ToolInfo:
    defaults = dict(name="query", server_id="db-server", default_timeout_ms=5000)
    defaults.update(overrides)
    return ToolInfo(**defaults)


def _mcp_result(text: str = "result", is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _handler() -> InvocationHandler:
    return InvocationHandler(
        circuit_breaker=CircuitBreaker(failure_threshold=3),
        result_processor=ResultProcessor(),
    )


# --- Happy path ---


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_successful_invocation(self):
        client = AsyncMock()
        client.call_tool = AsyncMock(return_value=_mcp_result("42"))
        handler = _handler()

        result = await handler.invoke(client, _tool_call(), _tool_info())

        assert result.content == "42"
        assert result.is_error is False
        assert result.latency_ms >= 0
        client.call_tool.assert_called_once_with("query", {"sql": "SELECT 1"})

    @pytest.mark.asyncio
    async def test_error_result_preserved(self):
        client = AsyncMock()
        client.call_tool = AsyncMock(return_value=_mcp_result("SQL error", is_error=True))
        handler = _handler()

        result = await handler.invoke(client, _tool_call(), _tool_info())

        assert result.is_error is True
        assert "SQL error" in result.content


# --- Circuit breaker ---


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_rejects_when_open(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure("db-server")
        handler = InvocationHandler(cb, ResultProcessor())

        client = AsyncMock()
        result = await handler.invoke(client, _tool_call(), _tool_info())

        assert result.is_error is True
        assert "circuit breaker" in result.content.lower()
        client.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_records_success(self):
        cb = CircuitBreaker(failure_threshold=3)
        handler = InvocationHandler(cb, ResultProcessor())
        client = AsyncMock()
        client.call_tool = AsyncMock(return_value=_mcp_result("ok"))

        await handler.invoke(client, _tool_call(), _tool_info())

        assert cb.get_state("db-server") == CircuitState.CLOSED


# --- Timeout ---


class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        client = AsyncMock()

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(10)
            return _mcp_result("late")

        client.call_tool = slow_call
        handler = _handler()
        tool = _tool_info(default_timeout_ms=50)

        result = await handler.invoke(client, _tool_call(), tool, timeout_ms=50)

        assert result.is_error is True
        assert "timed out" in result.content

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        client = AsyncMock()
        client.call_tool = AsyncMock(return_value=_mcp_result("ok"))
        handler = _handler()

        result = await handler.invoke(client, _tool_call(), _tool_info(), timeout_ms=10000)

        assert result.is_error is False


# --- Execution errors ---


class TestErrors:
    @pytest.mark.asyncio
    async def test_exception_returns_error_result(self):
        client = AsyncMock()
        client.call_tool = AsyncMock(side_effect=ConnectionError("MCP server down"))
        handler = _handler()

        result = await handler.invoke(client, _tool_call(), _tool_info())

        assert result.is_error is True
        assert "MCP server down" in result.content

    @pytest.mark.asyncio
    async def test_exception_records_failure(self):
        cb = CircuitBreaker(failure_threshold=3)
        handler = InvocationHandler(cb, ResultProcessor())
        client = AsyncMock()
        client.call_tool = AsyncMock(side_effect=RuntimeError("crash"))

        await handler.invoke(client, _tool_call(), _tool_info())

        state = cb._states.get("db-server")
        assert state is not None
        assert state.failure_count == 1


# --- Retry for idempotent tools ---


class TestRetry:
    @pytest.mark.asyncio
    async def test_retries_idempotent_on_failure(self):
        client = AsyncMock()
        call_count = 0

        async def flaky_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("flaky")
            return _mcp_result("ok")

        client.call_tool = flaky_call
        handler = _handler()
        tool = _tool_info(idempotent=True, default_timeout_ms=5000)

        result = await handler.invoke(client, _tool_call(), tool)

        assert result.is_error is False
        assert call_count == 2
