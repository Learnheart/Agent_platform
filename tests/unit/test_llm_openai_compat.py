"""Tests for OpenAICompatibleGateway.

Tests Section 11 of docs/architecture/04-llm-gateway.md.
Uses mocked OpenAI SDK — no real API calls.
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
from src.providers.llm.config import OpenAICompatibleGatewayConfig
from src.providers.llm.openai_compat_gateway import (
    OpenAICompatibleGateway,
    _calc_backoff,
    _convert_messages,
    _convert_tools,
    _extract_tool_calls,
)
from src.providers.llm.pricing import ModelPricing


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture()
def config():
    return OpenAICompatibleGatewayConfig(
        base_url="http://localhost:1234/v1",
        api_key="test-key",
        provider_name="lmstudio",
    )


@pytest.fixture()
def gateway(config):
    with patch("src.providers.llm.openai_compat_gateway.openai.AsyncOpenAI"):
        gw = OpenAICompatibleGateway(config)
    return gw


def _make_response(
    content: str | None = "Hello",
    tool_calls_data: list[dict[str, Any]] | None = None,
    model: str = "llama-3-8b",
    finish_reason: str = "stop",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> SimpleNamespace:
    """Build a fake OpenAI ChatCompletion response."""
    msg_tool_calls = None
    if tool_calls_data:
        msg_tool_calls = [
            SimpleNamespace(
                id=tc["id"],
                type="function",
                function=SimpleNamespace(
                    name=tc["name"],
                    arguments=json.dumps(tc["arguments"]),
                ),
            )
            for tc in tool_calls_data
        ]

    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=msg_tool_calls),
                finish_reason=finish_reason,
            )
        ],
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


# ======================================================================
# Message Conversion Tests
# ======================================================================


class TestConvertMessages:
    def test_user_message(self):
        msgs = [Message(role="user", content="hi")]
        result = _convert_messages(msgs)
        assert result == [{"role": "user", "content": "hi"}]

    def test_system_message_kept(self):
        """OpenAI format keeps system messages in the messages list."""
        msgs = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="hi"),
        ]
        result = _convert_messages(msgs)
        assert len(result) == 2
        assert result[0]["role"] == "system"

    def test_tool_result(self):
        msgs = [Message(role="tool", content="result data", tool_call_id="tc1")]
        result = _convert_messages(msgs)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "tc1"
        assert result[0]["content"] == "result data"

    def test_assistant_with_tool_calls(self):
        msgs = [
            Message(
                role="assistant",
                content="Let me search",
                tool_calls=[ToolCall(id="tc1", name="search", arguments={"q": "test"})],
            )
        ]
        result = _convert_messages(msgs)
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "Let me search"
        assert len(result[0]["tool_calls"]) == 1
        tc = result[0]["tool_calls"][0]
        assert tc["id"] == "tc1"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "search"
        assert json.loads(tc["function"]["arguments"]) == {"q": "test"}

    def test_assistant_with_tool_calls_no_content(self):
        msgs = [
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="tc1", name="fn", arguments={})],
            )
        ]
        result = _convert_messages(msgs)
        assert result[0]["content"] is None


class TestConvertTools:
    def test_basic_tool(self):
        tools = [{"name": "search", "description": "Search", "input_schema": {"type": "object"}}]
        result = _convert_tools(tools)
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "search"
        assert result[0]["function"]["parameters"] == {"type": "object"}


class TestExtractToolCalls:
    def test_no_tool_calls(self):
        msg = SimpleNamespace(tool_calls=None)
        assert _extract_tool_calls(msg) is None

    def test_with_tool_calls(self):
        msg = SimpleNamespace(
            tool_calls=[
                SimpleNamespace(
                    id="tc1",
                    function=SimpleNamespace(name="search", arguments='{"q": "hello"}'),
                )
            ]
        )
        calls = _extract_tool_calls(msg)
        assert calls is not None
        assert len(calls) == 1
        assert calls[0].name == "search"
        assert calls[0].arguments == {"q": "hello"}

    def test_invalid_json_arguments(self):
        msg = SimpleNamespace(
            tool_calls=[
                SimpleNamespace(
                    id="tc1",
                    function=SimpleNamespace(name="fn", arguments="not json"),
                )
            ]
        )
        calls = _extract_tool_calls(msg)
        assert calls is not None
        assert calls[0].arguments == {}


# ======================================================================
# Chat Tests
# ======================================================================


class TestChat:
    @pytest.mark.asyncio
    async def test_chat_returns_response(self, gateway):
        resp = _make_response("Hello!")
        gateway._client.chat.completions.create = AsyncMock(return_value=resp)

        result = await gateway.chat(
            model="llama-3-8b",
            messages=[Message(role="user", content="hi")],
        )

        assert result.content == "Hello!"
        assert result.provider == "lmstudio"
        assert result.model == "llama-3-8b"
        assert result.latency_ms >= 0
        assert result.usage.prompt_tokens == 100

    @pytest.mark.asyncio
    async def test_chat_with_tools(self, gateway):
        resp = _make_response(
            "I'll search",
            tool_calls_data=[{"id": "tc1", "name": "search", "arguments": {"q": "test"}}],
            finish_reason="tool_calls",
        )
        gateway._client.chat.completions.create = AsyncMock(return_value=resp)

        tools = [{"name": "search", "description": "Search", "input_schema": {"type": "object"}}]
        result = await gateway.chat(
            model="llama-3-8b",
            messages=[Message(role="user", content="search")],
            tools=tools,
        )

        assert result.tool_calls is not None
        assert result.tool_calls[0].name == "search"

    @pytest.mark.asyncio
    async def test_chat_with_custom_config(self, gateway):
        resp = _make_response("ok")
        gateway._client.chat.completions.create = AsyncMock(return_value=resp)

        custom_config = LLMConfig(temperature=0.2, max_tokens=512)
        await gateway.chat(
            model="llama-3-8b",
            messages=[Message(role="user", content="hi")],
            config=custom_config,
        )

        call_kwargs = gateway._client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.2
        assert call_kwargs["max_tokens"] == 512


# ======================================================================
# Retry Logic Tests
# ======================================================================


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self, gateway):
        import openai as oai

        rate_resp = MagicMock()
        rate_resp.status_code = 429
        rate_resp.headers = {}
        exc = oai.RateLimitError(
            message="rate limited",
            response=rate_resp,
            body=None,
        )
        success_resp = _make_response("ok")
        gateway._client.chat.completions.create = AsyncMock(side_effect=[exc, success_resp])

        with patch("src.providers.llm.openai_compat_gateway.asyncio.sleep", new_callable=AsyncMock):
            result = await gateway.chat(
                model="llama-3-8b",
                messages=[Message(role="user", content="hi")],
                config=LLMConfig(retry_policy=RetryPolicy(max_retries=2)),
            )
        assert result.content == "ok"

    @pytest.mark.asyncio
    async def test_bad_request_no_retry(self, gateway):
        import openai as oai

        bad_resp = MagicMock()
        bad_resp.status_code = 400
        bad_resp.headers = {}
        exc = oai.BadRequestError(
            message="bad",
            response=bad_resp,
            body=None,
        )
        gateway._client.chat.completions.create = AsyncMock(side_effect=exc)

        with pytest.raises(LLMError) as exc_info:
            await gateway.chat(
                model="llama-3-8b",
                messages=[Message(role="user", content="hi")],
            )
        assert exc_info.value.category == ErrorCategory.LLM_CONTENT_REFUSAL

    @pytest.mark.asyncio
    async def test_timeout_exhausted(self, gateway):
        import openai as oai

        exc = oai.APITimeoutError(request=MagicMock())
        gateway._client.chat.completions.create = AsyncMock(side_effect=exc)

        with (
            patch("src.providers.llm.openai_compat_gateway.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(LLMTimeoutError),
        ):
            await gateway.chat(
                model="llama-3-8b",
                messages=[Message(role="user", content="hi")],
                config=LLMConfig(retry_policy=RetryPolicy(max_retries=1)),
            )


# ======================================================================
# Count Tokens Tests
# ======================================================================


class TestCountTokens:
    @pytest.mark.asyncio
    async def test_count_tokens_with_tiktoken(self, gateway):
        """Should use tiktoken if available."""
        result = await gateway.count_tokens(
            model="gpt-4",
            messages=[Message(role="user", content="hello world")],
        )
        assert result > 0

    @pytest.mark.asyncio
    async def test_count_tokens_fallback(self, gateway):
        """Falls back to char estimation if tiktoken import fails."""
        with patch.dict("sys.modules", {"tiktoken": None}):
            # Force reimport to trigger ImportError path
            import importlib
            import src.providers.llm.openai_compat_gateway as mod

            # Directly test fallback: ~4 chars per token
            content = "a" * 100
            msgs = [Message(role="user", content=content)]
            result = await gateway.count_tokens(model="unknown-model", messages=msgs)
            assert result > 0


# ======================================================================
# Backoff Tests
# ======================================================================


class TestCalcBackoff:
    def test_attempt_0(self):
        policy = RetryPolicy()
        assert _calc_backoff(0, policy) == 1.0

    def test_capped(self):
        policy = RetryPolicy(backoff_max_seconds=3.0)
        assert _calc_backoff(10, policy) == 3.0
