"""AnthropicGateway — LLMGateway implementation using Anthropic Python SDK.

See docs/architecture/04-llm-gateway.md Sections 3-8.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import anthropic
import httpx

from src.core.enums import ErrorCategory
from src.core.errors import LLMError, LLMRateLimitError, LLMTimeoutError
from src.core.models import (
    LLMConfig,
    LLMResponse,
    LLMStreamEvent,
    Message,
    RetryPolicy,
    TokenUsage,
    ToolCall,
)
from src.providers.llm.config import AnthropicGatewayConfig
from src.providers.llm.pricing import calculate_cost

logger = logging.getLogger(__name__)


class AnthropicGateway:
    """LLMGateway implementation for Anthropic models.

    Uses the Anthropic Python SDK with custom retry logic,
    prompt caching, and message conversion.
    """

    def __init__(self, config: AnthropicGatewayConfig) -> None:
        self._config = config
        self._default_llm_config = config.default_llm_config
        self._pricing = config.pricing

        http_client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=config.max_connections,
                max_keepalive_connections=config.max_keepalive,
            ),
        )
        self._client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            max_retries=0,  # We handle retries ourselves
            timeout=httpx.Timeout(
                connect=10.0,
                read=config.default_timeout,
                write=10.0,
                pool=10.0,
            ),
            http_client=http_client,
        )

    # ------------------------------------------------------------------
    # Public API — implements LLMGateway protocol
    # ------------------------------------------------------------------

    async def chat(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        """Non-streaming LLM call."""
        cfg = config or self._default_llm_config
        anthropic_messages = _convert_messages(messages)
        system_prompt = _extract_system(messages)
        anthropic_tools = _convert_tools(tools) if tools else anthropic.NOT_GIVEN

        start = time.monotonic()

        async def _call() -> anthropic.types.Message:
            return await self._client.messages.create(
                model=model,
                messages=anthropic_messages,
                tools=anthropic_tools,
                system=_build_system_with_cache(system_prompt) if system_prompt else anthropic.NOT_GIVEN,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )

        response = await self._call_with_retry(_call, cfg.retry_policy)
        latency_ms = (time.monotonic() - start) * 1000

        usage = _build_usage(response.usage, model, self._pricing)

        return LLMResponse(
            content=_extract_text(response),
            tool_calls=_extract_tool_calls(response),
            usage=usage,
            model=response.model,
            provider="anthropic",
            latency_ms=latency_ms,
            stop_reason=response.stop_reason or "",
        )

    async def chat_stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        config: LLMConfig | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Streaming LLM call. Yields LLMStreamEvent as they arrive."""
        cfg = config or self._default_llm_config
        anthropic_messages = _convert_messages(messages)
        system_prompt = _extract_system(messages)
        anthropic_tools = _convert_tools(tools) if tools else anthropic.NOT_GIVEN

        current_tool_id: str | None = None
        current_tool_name: str | None = None
        accumulated_args = ""

        try:
            async with self._client.messages.stream(
                model=model,
                messages=anthropic_messages,
                tools=anthropic_tools,
                system=_build_system_with_cache(system_prompt) if system_prompt else anthropic.NOT_GIVEN,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            ) as stream:
                async for event in stream:
                    # Text delta
                    if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                        yield LLMStreamEvent(type="text_delta", content=event.delta.text)

                    # Tool call start
                    elif event.type == "content_block_start" and getattr(event.content_block, "type", None) == "tool_use":
                        current_tool_id = event.content_block.id
                        current_tool_name = event.content_block.name
                        accumulated_args = ""
                        yield LLMStreamEvent(
                            type="tool_call_start",
                            tool_call_id=current_tool_id,
                            tool_name=current_tool_name,
                        )

                    # Tool call argument delta
                    elif event.type == "content_block_delta" and hasattr(event.delta, "partial_json"):
                        accumulated_args += event.delta.partial_json
                        yield LLMStreamEvent(
                            type="tool_call_delta",
                            tool_call_id=current_tool_id,
                            arguments_delta=event.delta.partial_json,
                        )

                    # Tool call end
                    elif event.type == "content_block_stop" and current_tool_id is not None:
                        try:
                            parsed_args = json.loads(accumulated_args) if accumulated_args else {}
                        except json.JSONDecodeError:
                            parsed_args = {}
                        yield LLMStreamEvent(
                            type="tool_call_end",
                            tool_call=ToolCall(
                                id=current_tool_id,
                                name=current_tool_name or "",
                                arguments=parsed_args,
                            ),
                        )
                        current_tool_id = None
                        current_tool_name = None

                    # Message complete
                    elif event.type == "message_stop":
                        final_message = stream.get_final_message()
                        usage = _build_usage(final_message.usage, model, self._pricing)
                        yield LLMStreamEvent(
                            type="done",
                            usage=usage,
                            stop_reason=final_message.stop_reason or "",
                        )

        except anthropic.APITimeoutError as exc:
            yield LLMStreamEvent(type="error", error_message=str(exc))
        except anthropic.APIError as exc:
            yield LLMStreamEvent(type="error", error_message=str(exc))

    async def count_tokens(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        """Token count estimation using Anthropic SDK count_tokens API."""
        anthropic_messages = _convert_messages(messages)
        system_prompt = _extract_system(messages)
        anthropic_tools = _convert_tools(tools) if tools else anthropic.NOT_GIVEN

        result = await self._client.messages.count_tokens(
            model=model,
            messages=anthropic_messages,
            tools=anthropic_tools,
            system=_build_system_with_cache(system_prompt) if system_prompt else anthropic.NOT_GIVEN,
        )
        return result.input_tokens

    # ------------------------------------------------------------------
    # Retry logic — Section 3.6
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        call_fn: Any,
        retry_policy: RetryPolicy | None,
    ) -> anthropic.types.Message:
        """Execute an LLM call with exponential backoff retry."""
        policy = retry_policy or RetryPolicy()
        last_error: Exception | None = None

        for attempt in range(1 + policy.max_retries):
            try:
                return await call_fn()

            except anthropic.RateLimitError as exc:
                last_error = exc
                if attempt >= policy.max_retries:
                    break
                wait = _parse_retry_after(exc) or _calc_backoff(attempt, policy)
                logger.warning("Rate limited (attempt %d/%d), waiting %.1fs", attempt + 1, policy.max_retries, wait)
                await asyncio.sleep(wait)

            except anthropic.InternalServerError as exc:
                last_error = exc
                if attempt >= policy.max_retries:
                    break
                wait = _calc_backoff(attempt, policy)
                logger.warning("Server error (attempt %d/%d), waiting %.1fs", attempt + 1, policy.max_retries, wait)
                await asyncio.sleep(wait)

            except anthropic.APITimeoutError as exc:
                last_error = exc
                if attempt >= policy.max_retries:
                    break
                wait = _calc_backoff(attempt, policy)
                logger.warning("Timeout (attempt %d/%d), waiting %.1fs", attempt + 1, policy.max_retries, wait)
                await asyncio.sleep(wait)

            except anthropic.BadRequestError as exc:
                raise LLMError(
                    str(exc),
                    category=ErrorCategory.LLM_CONTENT_REFUSAL,
                    retryable=False,
                ) from exc

            except anthropic.AuthenticationError as exc:
                raise LLMError(
                    str(exc),
                    category=ErrorCategory.LLM_SERVER_ERROR,
                    retryable=False,
                ) from exc

        # Exhausted retries — raise appropriate error
        if isinstance(last_error, anthropic.RateLimitError):
            raise LLMRateLimitError(str(last_error)) from last_error
        if isinstance(last_error, anthropic.APITimeoutError):
            raise LLMTimeoutError(str(last_error)) from last_error
        raise LLMError(str(last_error)) from last_error


# ======================================================================
# Helper functions (module-private)
# ======================================================================


def _convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert platform Messages to Anthropic API format.

    See Section 8.1.
    """
    result: list[dict[str, Any]] = []
    for msg in messages:
        # System messages are handled separately
        if msg.role == "system":
            continue

        # Tool result → user message with tool_result content block
        if msg.role == "tool":
            result.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                ],
            })

        # Assistant with tool_calls → content blocks
        elif msg.role == "assistant" and msg.tool_calls:
            blocks: list[dict[str, Any]] = []
            if msg.content:
                blocks.append({"type": "text", "text": msg.content})
            for tc in msg.tool_calls:
                blocks.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            result.append({"role": "assistant", "content": blocks})

        # Normal message
        else:
            result.append({"role": msg.role, "content": msg.content})

    return result


def _extract_system(messages: list[Message]) -> str | None:
    """Extract the first system message content."""
    for msg in messages:
        if msg.role == "system":
            return msg.content
    return None


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert platform tool schemas to Anthropic format."""
    anthropic_tools: list[dict[str, Any]] = []
    for tool in tools:
        anthropic_tools.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            "input_schema": tool.get("input_schema", tool.get("parameters", {})),
        })
    return anthropic_tools


def _build_system_with_cache(system_prompt: str) -> list[dict[str, Any]]:
    """Build system message with prompt caching. See Section 7."""
    return [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _extract_text(response: anthropic.types.Message) -> str | None:
    """Extract text content from Anthropic response. See Section 8.2."""
    for block in response.content:
        if block.type == "text":
            return block.text
    return None


def _extract_tool_calls(response: anthropic.types.Message) -> list[ToolCall] | None:
    """Extract tool calls from Anthropic response. See Section 8.2."""
    calls: list[ToolCall] = []
    for block in response.content:
        if block.type == "tool_use":
            calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))
    return calls if calls else None


def _build_usage(
    raw_usage: Any,
    model: str,
    pricing: dict[str, Any],
) -> TokenUsage:
    """Build TokenUsage from Anthropic response usage."""
    prompt_tokens = getattr(raw_usage, "input_tokens", 0)
    completion_tokens = getattr(raw_usage, "output_tokens", 0)
    cached_tokens = getattr(raw_usage, "cache_read_input_tokens", None)

    usage = TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        cached_tokens=cached_tokens,
    )
    usage.cost_usd = calculate_cost(usage, model, pricing)
    return usage


def _calc_backoff(attempt: int, policy: RetryPolicy) -> float:
    """Calculate exponential backoff wait time."""
    wait = policy.backoff_base_seconds * (policy.backoff_multiplier ** attempt)
    return min(wait, policy.backoff_max_seconds)


def _parse_retry_after(exc: anthropic.RateLimitError) -> float | None:
    """Parse Retry-After header from rate limit error response."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    retry_after = response.headers.get("retry-after")
    if retry_after is None:
        return None
    try:
        return float(retry_after)
    except (ValueError, TypeError):
        return None
