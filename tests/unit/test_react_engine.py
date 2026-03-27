"""Tests for ReActEngine — Think → Act → Observe loop."""

from unittest.mock import AsyncMock

import pytest

from src.core.enums import AgentEventType, StepType
from src.core.models import (
    ContextPayload,
    LLMResponse,
    Message,
    Session,
    TokenUsage,
    ToolCall,
    ToolResult,
)
from src.engine.react import ReActEngine


def _session(**overrides) -> Session:
    defaults = dict(
        tenant_id="t1",
        agent_id="a1",
        step_index=0,
        metadata={"model_config": {"provider": "anthropic", "model": "claude-sonnet-4-5-20250514"}},
    )
    defaults.update(overrides)
    return Session(**defaults)


def _context(**overrides) -> ContextPayload:
    defaults = dict(
        system_prompt="You are a helpful assistant.",
        messages=[Message(role="user", content="What is 2+2?", session_id="s1")],
        tool_schemas=[{"name": "calculator", "description": "math tool"}],
    )
    defaults.update(overrides)
    return ContextPayload(**defaults)


def _llm_text_response(content: str = "The answer is 4.") -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=None,
        usage=TokenUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70, cost_usd=0.001),
        model="claude-sonnet-4-5-20250514",
        provider="anthropic",
        latency_ms=150,
    )


def _llm_tool_response(tool_name: str = "calculator", args: dict | None = None) -> LLMResponse:
    return LLMResponse(
        content="Let me calculate that.",
        tool_calls=[ToolCall(id="tc1", name=tool_name, arguments=args or {"expr": "2+2"})],
        usage=TokenUsage(prompt_tokens=50, completion_tokens=30, total_tokens=80, cost_usd=0.002),
        model="claude-sonnet-4-5-20250514",
        provider="anthropic",
    )


# --- Final answer ---


class TestFinalAnswer:
    @pytest.mark.asyncio
    async def test_text_response_returns_final_answer(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_text_response("42"))
        engine = ReActEngine(llm_gateway=llm)

        result = await engine.step(_session(), _context())

        assert result.type == StepType.FINAL_ANSWER
        assert result.answer == "42"
        assert len(result.messages) == 1
        assert result.messages[0].role == "assistant"

    @pytest.mark.asyncio
    async def test_final_answer_has_events(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_text_response())
        engine = ReActEngine(llm_gateway=llm)

        result = await engine.step(_session(), _context())

        event_types = {e.type for e in result.events}
        assert AgentEventType.LLM_CALL_START in event_types
        assert AgentEventType.LLM_CALL_END in event_types
        assert AgentEventType.FINAL_ANSWER in event_types

    @pytest.mark.asyncio
    async def test_usage_populated(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_text_response())
        engine = ReActEngine(llm_gateway=llm)

        result = await engine.step(_session(), _context())

        assert result.usage.prompt_tokens == 50
        assert result.usage.completion_tokens == 20
        assert result.usage.cost_usd > 0


# --- Tool calls ---


class TestToolCalls:
    @pytest.mark.asyncio
    async def test_tool_call_step_type(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_tool_response())
        tool_rt = AsyncMock()
        tool_rt.invoke = AsyncMock(return_value=ToolResult(
            tool_call_id="tc1", tool_name="calculator", content="4",
        ))
        engine = ReActEngine(llm_gateway=llm, tool_runtime=tool_rt)

        result = await engine.step(_session(), _context())

        assert result.type == StepType.TOOL_CALL
        assert result.tool_calls is not None
        assert result.tool_results is not None
        assert len(result.tool_results) == 1
        assert result.tool_results[0].content == "4"

    @pytest.mark.asyncio
    async def test_tool_messages_in_result(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_tool_response())
        tool_rt = AsyncMock()
        tool_rt.invoke = AsyncMock(return_value=ToolResult(
            tool_call_id="tc1", tool_name="calculator", content="4",
        ))
        engine = ReActEngine(llm_gateway=llm, tool_runtime=tool_rt)

        result = await engine.step(_session(), _context())

        roles = [m.role for m in result.messages]
        assert "assistant" in roles
        assert "tool" in roles

    @pytest.mark.asyncio
    async def test_tool_events_emitted(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_tool_response())
        tool_rt = AsyncMock()
        tool_rt.invoke = AsyncMock(return_value=ToolResult(
            tool_call_id="tc1", tool_name="calculator", content="4",
        ))
        engine = ReActEngine(llm_gateway=llm, tool_runtime=tool_rt)

        result = await engine.step(_session(), _context())

        event_types = {e.type for e in result.events}
        assert AgentEventType.TOOL_CALL in event_types
        assert AgentEventType.TOOL_RESULT in event_types

    @pytest.mark.asyncio
    async def test_no_tool_runtime_returns_error(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_tool_response())
        engine = ReActEngine(llm_gateway=llm, tool_runtime=None)

        result = await engine.step(_session(), _context())

        assert result.type == StepType.TOOL_CALL
        assert result.tool_results[0].is_error is True
        assert "not available" in result.tool_results[0].content

    @pytest.mark.asyncio
    async def test_tool_execution_error_captured(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_tool_response())
        tool_rt = AsyncMock()
        tool_rt.invoke = AsyncMock(side_effect=RuntimeError("tool crashed"))
        engine = ReActEngine(llm_gateway=llm, tool_runtime=tool_rt)

        result = await engine.step(_session(), _context())

        assert result.type == StepType.TOOL_CALL
        assert result.tool_results[0].is_error is True
        assert "tool crashed" in result.tool_results[0].content


# --- LLM errors ---


class TestLLMErrors:
    @pytest.mark.asyncio
    async def test_llm_error_returns_error_step(self):
        from src.core.errors import LLMError

        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=LLMError("rate limited", retryable=True))
        engine = ReActEngine(llm_gateway=llm)

        result = await engine.step(_session(), _context())

        assert result.type == StepType.ERROR
        assert result.retryable is True
        assert "rate limited" in result.error_message

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_error_step(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=ValueError("unexpected"))
        engine = ReActEngine(llm_gateway=llm)

        result = await engine.step(_session(), _context())

        assert result.type == StepType.ERROR
        assert result.retryable is False
        assert "unexpected" in result.error_message

    @pytest.mark.asyncio
    async def test_error_events_emitted(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=RuntimeError("boom"))
        engine = ReActEngine(llm_gateway=llm)

        result = await engine.step(_session(), _context())

        event_types = {e.type for e in result.events}
        assert AgentEventType.ERROR in event_types
