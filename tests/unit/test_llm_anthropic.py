"""Tests for AnthropicGateway.

Tests Sections 3-8 of docs/architecture/04-llm-gateway.md.
Uses mocked Anthropic SDK — no real API calls.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.enums import ErrorCategory
from src.core.errors import LLMError, LLMRateLimitError, LLMTimeoutError
from src.core.models import (
    LLMConfig,
    Message,
    RetryPolicy,
    ToolCall,
)
from src.providers.llm.anthropic_gateway import (
    AnthropicGateway,
    _build_system_with_cache,
    _build_usage,
    _calc_backoff,
    _convert_messages,
    _convert_tools,
    _extract_system,
    _extract_text,
    _extract_tool_calls,
    _parse_retry_after,
)
from src.providers.llm.config import AnthropicGatewayConfig
from src.providers.llm.pricing import DEFAULT_PRICING


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture()
def config():
    return AnthropicGatewayConfig(api_key="test-key")


@pytest.fixture()
def gateway(config):
    with patch("src.providers.llm.anthropic_gateway.anthropic.AsyncAnthropic"):
        gw = AnthropicGateway(config)
    return gw


def _make_response(
    content_text: str | None = "Hello",
    tool_uses: list[dict[str, Any]] | None = None,
    model: str = "claude-sonnet-4-5-20250514",
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> SimpleNamespace:
    """Build a fake Anthropic Message response."""
    blocks = []
    if content_text is not None:
        blocks.append(SimpleNamespace(type="text", text=content_text))
    if tool_uses:
        for tu in tool_uses:
            blocks.append(
                SimpleNamespace(type="tool_use", id=tu["id"], name=tu["name"], input=tu["input"])
            )
    return SimpleNamespace(
        content=blocks,
        model=model,
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    )


# ======================================================================
# Message Conversion Tests — Section 8
# ======================================================================


class TestConvertMessages:
    def test_user_message(self):
        msgs = [Message(role="user", content="hi")]
        result = _convert_messages(msgs)
        assert result == [{"role": "user", "content": "hi"}]

    def test_system_filtered(self):
        msgs = [
            Message(role="system", content="You are a helper"),
            Message(role="user", content="hi"),
        ]
        result = _convert_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_assistant_message(self):
        msgs = [Message(role="assistant", content="hello")]
        result = _convert_messages(msgs)
        assert result == [{"role": "assistant", "content": "hello"}]

    def test_tool_result(self):
        msgs = [Message(role="tool", content="result", tool_call_id="tc1")]
        result = _convert_messages(msgs)
        assert result[0]["role"] == "user"
        assert result[0]["content"][0]["type"] == "tool_result"
        assert result[0]["content"][0]["tool_use_id"] == "tc1"
        assert result[0]["content"][0]["content"] == "result"

    def test_assistant_with_tool_calls(self):
        msgs = [
            Message(
                role="assistant",
                content="Let me check",
                tool_calls=[ToolCall(id="tc1", name="search", arguments={"q": "test"})],
            )
        ]
        result = _convert_messages(msgs)
        assert result[0]["role"] == "assistant"
        blocks = result[0]["content"]
        assert blocks[0] == {"type": "text", "text": "Let me check"}
        assert blocks[1]["type"] == "tool_use"
        assert blocks[1]["id"] == "tc1"
        assert blocks[1]["name"] == "search"
        assert blocks[1]["input"] == {"q": "test"}

    def test_assistant_with_tool_calls_no_text(self):
        msgs = [
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="tc1", name="search", arguments={})],
            )
        ]
        result = _convert_messages(msgs)
        blocks = result[0]["content"]
        # No text block when content is empty
        assert len(blocks) == 1
        assert blocks[0]["type"] == "tool_use"


class TestExtractSystem:
    def test_has_system(self):
        msgs = [Message(role="system", content="Be helpful"), Message(role="user", content="hi")]
        assert _extract_system(msgs) == "Be helpful"

    def test_no_system(self):
        msgs = [Message(role="user", content="hi")]
        assert _extract_system(msgs) is None


class TestConvertTools:
    def test_basic_tool(self):
        tools = [{"name": "search", "description": "Search the web", "input_schema": {"type": "object"}}]
        result = _convert_tools(tools)
        assert result[0]["name"] == "search"
        assert result[0]["description"] == "Search the web"
        assert result[0]["input_schema"] == {"type": "object"}

    def test_tool_with_parameters_key(self):
        tools = [{"name": "calc", "parameters": {"type": "object", "properties": {}}}]
        result = _convert_tools(tools)
        assert result[0]["input_schema"] == {"type": "object", "properties": {}}


# ======================================================================
# Response Extraction Tests — Section 8.2
# ======================================================================


class TestExtractText:
    def test_text_content(self):
        resp = _make_response("Hello world")
        assert _extract_text(resp) == "Hello world"

    def test_no_text(self):
        resp = _make_response(content_text=None, tool_uses=[{"id": "1", "name": "t", "input": {}}])
        assert _extract_text(resp) is None


class TestExtractToolCalls:
    def test_no_tool_calls(self):
        resp = _make_response("Hello")
        assert _extract_tool_calls(resp) is None

    def test_with_tool_calls(self):
        resp = _make_response(
            "Hello",
            tool_uses=[{"id": "tc1", "name": "search", "input": {"query": "test"}}],
        )
        calls = _extract_tool_calls(resp)
        assert calls is not None
        assert len(calls) == 1
        assert calls[0].id == "tc1"
        assert calls[0].name == "search"
        assert calls[0].arguments == {"query": "test"}


# ======================================================================
# Prompt Caching Tests — Section 7
# ======================================================================


class TestBuildSystemWithCache:
    def test_cache_control_added(self):
        result = _build_system_with_cache("You are helpful")
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert result[0]["text"] == "You are helpful"
        assert result[0]["cache_control"] == {"type": "ephemeral"}


# ======================================================================
# Usage & Cost Tests — Section 5
# ======================================================================


class TestBuildUsage:
    def test_basic_usage(self):
        raw = SimpleNamespace(input_tokens=100, output_tokens=50)
        usage = _build_usage(raw, "claude-sonnet-4-5-20250514", DEFAULT_PRICING)
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150
        assert usage.cost_usd is not None
        assert usage.cost_usd > 0

    def test_with_cached_tokens(self):
        raw = SimpleNamespace(input_tokens=1000, output_tokens=100, cache_read_input_tokens=800)
        usage = _build_usage(raw, "claude-sonnet-4-5-20250514", DEFAULT_PRICING)
        assert usage.cached_tokens == 800


# ======================================================================
# Backoff & Retry Helpers — Section 3.6
# ======================================================================


class TestCalcBackoff:
    def test_attempt_0(self):
        policy = RetryPolicy()
        assert _calc_backoff(0, policy) == 1.0

    def test_attempt_1(self):
        policy = RetryPolicy()
        assert _calc_backoff(1, policy) == 2.0

    def test_attempt_2(self):
        policy = RetryPolicy()
        assert _calc_backoff(2, policy) == 4.0

    def test_capped_at_max(self):
        policy = RetryPolicy(backoff_max_seconds=5.0)
        assert _calc_backoff(10, policy) == 5.0


class TestParseRetryAfter:
    def test_no_response(self):
        exc = MagicMock(spec=[])
        assert _parse_retry_after(exc) is None

    def test_with_retry_after_header(self):
        exc = MagicMock()
        exc.response.headers = {"retry-after": "2.5"}
        assert _parse_retry_after(exc) == 2.5

    def test_no_header(self):
        exc = MagicMock()
        exc.response.headers = {}
        assert _parse_retry_after(exc) is None

    def test_invalid_header(self):
        exc = MagicMock()
        exc.response.headers = {"retry-after": "not-a-number"}
        assert _parse_retry_after(exc) is None


# ======================================================================
# Chat Tests — Section 3.3
# ======================================================================


class TestChat:
    @pytest.mark.asyncio
    async def test_chat_returns_response(self, gateway):
        resp = _make_response("Hello!")
        gateway._client.messages.create = AsyncMock(return_value=resp)

        result = await gateway.chat(
            model="claude-sonnet-4-5-20250514",
            messages=[Message(role="user", content="hi")],
        )

        assert result.content == "Hello!"
        assert result.provider == "anthropic"
        assert result.model == "claude-sonnet-4-5-20250514"
        assert result.latency_ms >= 0
        assert result.usage.prompt_tokens == 100
        assert result.usage.completion_tokens == 50

    @pytest.mark.asyncio
    async def test_chat_with_tools(self, gateway):
        resp = _make_response(
            "I'll search",
            tool_uses=[{"id": "tc1", "name": "search", "input": {"q": "test"}}],
            stop_reason="tool_use",
        )
        gateway._client.messages.create = AsyncMock(return_value=resp)

        tools = [{"name": "search", "description": "Search", "input_schema": {"type": "object"}}]
        result = await gateway.chat(
            model="claude-sonnet-4-5-20250514",
            messages=[Message(role="user", content="search for test")],
            tools=tools,
        )

        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "search"
        assert result.stop_reason == "tool_use"

    @pytest.mark.asyncio
    async def test_chat_with_custom_config(self, gateway):
        resp = _make_response("ok")
        gateway._client.messages.create = AsyncMock(return_value=resp)

        custom_config = LLMConfig(temperature=0.5, max_tokens=1000)
        await gateway.chat(
            model="claude-sonnet-4-5-20250514",
            messages=[Message(role="user", content="hi")],
            config=custom_config,
        )

        call_kwargs = gateway._client.messages.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 1000


# ======================================================================
# Retry Logic Tests — Section 3.6
# ======================================================================


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self, gateway):
        import anthropic as anth

        rate_limit_resp = MagicMock()
        rate_limit_resp.status_code = 429
        rate_limit_resp.headers = {}
        exc = anth.RateLimitError(
            message="rate limited",
            response=rate_limit_resp,
            body=None,
        )
        success_resp = _make_response("ok")
        gateway._client.messages.create = AsyncMock(side_effect=[exc, success_resp])

        with patch("src.providers.llm.anthropic_gateway.asyncio.sleep", new_callable=AsyncMock):
            result = await gateway.chat(
                model="claude-sonnet-4-5-20250514",
                messages=[Message(role="user", content="hi")],
                config=LLMConfig(retry_policy=RetryPolicy(max_retries=2)),
            )

        assert result.content == "ok"
        assert gateway._client.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_exhausted_retries_raises(self, gateway):
        import anthropic as anth

        rate_limit_resp = MagicMock()
        rate_limit_resp.status_code = 429
        rate_limit_resp.headers = {}
        exc = anth.RateLimitError(
            message="rate limited",
            response=rate_limit_resp,
            body=None,
        )
        gateway._client.messages.create = AsyncMock(side_effect=exc)

        with (
            patch("src.providers.llm.anthropic_gateway.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(LLMRateLimitError),
        ):
            await gateway.chat(
                model="claude-sonnet-4-5-20250514",
                messages=[Message(role="user", content="hi")],
                config=LLMConfig(retry_policy=RetryPolicy(max_retries=1)),
            )

    @pytest.mark.asyncio
    async def test_bad_request_no_retry(self, gateway):
        import anthropic as anth

        bad_resp = MagicMock()
        bad_resp.status_code = 400
        bad_resp.headers = {}
        exc = anth.BadRequestError(
            message="bad request",
            response=bad_resp,
            body=None,
        )
        gateway._client.messages.create = AsyncMock(side_effect=exc)

        with pytest.raises(LLMError) as exc_info:
            await gateway.chat(
                model="claude-sonnet-4-5-20250514",
                messages=[Message(role="user", content="hi")],
            )
        assert exc_info.value.category == ErrorCategory.LLM_CONTENT_REFUSAL

    @pytest.mark.asyncio
    async def test_auth_error_no_retry(self, gateway):
        import anthropic as anth

        auth_resp = MagicMock()
        auth_resp.status_code = 401
        auth_resp.headers = {}
        exc = anth.AuthenticationError(
            message="unauthorized",
            response=auth_resp,
            body=None,
        )
        gateway._client.messages.create = AsyncMock(side_effect=exc)

        with pytest.raises(LLMError):
            await gateway.chat(
                model="claude-sonnet-4-5-20250514",
                messages=[Message(role="user", content="hi")],
            )

    @pytest.mark.asyncio
    async def test_timeout_retry(self, gateway):
        import anthropic as anth

        exc = anth.APITimeoutError(request=MagicMock())
        success_resp = _make_response("ok")
        gateway._client.messages.create = AsyncMock(side_effect=[exc, success_resp])

        with patch("src.providers.llm.anthropic_gateway.asyncio.sleep", new_callable=AsyncMock):
            result = await gateway.chat(
                model="claude-sonnet-4-5-20250514",
                messages=[Message(role="user", content="hi")],
                config=LLMConfig(retry_policy=RetryPolicy(max_retries=2)),
            )
        assert result.content == "ok"

    @pytest.mark.asyncio
    async def test_timeout_exhausted_raises(self, gateway):
        import anthropic as anth

        exc = anth.APITimeoutError(request=MagicMock())
        gateway._client.messages.create = AsyncMock(side_effect=exc)

        with (
            patch("src.providers.llm.anthropic_gateway.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(LLMTimeoutError),
        ):
            await gateway.chat(
                model="claude-sonnet-4-5-20250514",
                messages=[Message(role="user", content="hi")],
                config=LLMConfig(retry_policy=RetryPolicy(max_retries=1)),
            )


# ======================================================================
# Count Tokens Tests — Section 3.5
# ======================================================================


class TestCountTokens:
    @pytest.mark.asyncio
    async def test_count_tokens(self, gateway):
        gateway._client.messages.count_tokens = AsyncMock(
            return_value=SimpleNamespace(input_tokens=42)
        )

        result = await gateway.count_tokens(
            model="claude-sonnet-4-5-20250514",
            messages=[Message(role="user", content="hello")],
        )
        assert result == 42
