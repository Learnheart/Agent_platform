"""OpenAICompatibleGateway — LLMGateway for OpenAI-compatible providers.

Supports Groq, LM Studio, and any provider exposing an OpenAI-compatible API.
See docs/architecture/04-llm-gateway.md Section 11.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import openai

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
from src.providers.llm.config import OpenAICompatibleGatewayConfig
from src.providers.llm.pricing import calculate_cost

logger = logging.getLogger(__name__)


class OpenAICompatibleGateway:
    """LLMGateway implementation for OpenAI-compatible providers.

    Uses the OpenAI Python SDK with a custom base_url to connect to
    Groq, LM Studio, or any OpenAI-compatible endpoint.
    """

    def __init__(self, config: OpenAICompatibleGatewayConfig) -> None:
        self._config = config
        self._provider_name = config.provider_name
        self._default_llm_config = config.default_llm_config
        self._pricing = config.pricing

        http_client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=config.max_connections,
                max_keepalive_connections=config.max_keepalive,
            ),
        )
        self._client = openai.AsyncOpenAI(
            api_key=config.api_key or "not-needed",
            base_url=config.base_url,
            max_retries=0,
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
        openai_messages = _convert_messages(messages)
        openai_tools = _convert_tools(tools) if tools else openai.NOT_GIVEN

        start = time.monotonic()

        async def _call() -> Any:
            return await self._client.chat.completions.create(
                model=model,
                messages=openai_messages,
                tools=openai_tools,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )

        response = await self._call_with_retry(_call, cfg.retry_policy)
        latency_ms = (time.monotonic() - start) * 1000

        choice = response.choices[0]
        raw_usage = response.usage

        usage = TokenUsage(
            prompt_tokens=raw_usage.prompt_tokens if raw_usage else 0,
            completion_tokens=raw_usage.completion_tokens if raw_usage else 0,
            total_tokens=raw_usage.total_tokens if raw_usage else 0,
        )
        usage.cost_usd = calculate_cost(usage, model, self._pricing)

        return LLMResponse(
            content=choice.message.content,
            tool_calls=_extract_tool_calls(choice.message),
            usage=usage,
            model=response.model,
            provider=self._provider_name,
            latency_ms=latency_ms,
            stop_reason=choice.finish_reason or "",
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
        openai_messages = _convert_messages(messages)
        openai_tools = _convert_tools(tools) if tools else openai.NOT_GIVEN

        current_tool_calls: dict[int, dict[str, Any]] = {}
        accumulated_usage = TokenUsage()

        try:
            stream = await self._client.chat.completions.create(
                model=model,
                messages=openai_messages,
                tools=openai_tools,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )

            async for chunk in stream:
                # Usage chunk (arrives near end)
                if chunk.usage is not None:
                    accumulated_usage = TokenUsage(
                        prompt_tokens=chunk.usage.prompt_tokens,
                        completion_tokens=chunk.usage.completion_tokens,
                        total_tokens=chunk.usage.total_tokens,
                    )
                    accumulated_usage.cost_usd = calculate_cost(
                        accumulated_usage, model, self._pricing
                    )
                    yield LLMStreamEvent(type="usage", usage=accumulated_usage)

                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                # Text delta
                if delta.content:
                    yield LLMStreamEvent(type="text_delta", content=delta.content)

                # Tool call deltas
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in current_tool_calls:
                            current_tool_calls[idx] = {
                                "id": tc_delta.id or "",
                                "name": getattr(tc_delta.function, "name", "") or "",
                                "arguments": "",
                            }
                            yield LLMStreamEvent(
                                type="tool_call_start",
                                tool_call_id=current_tool_calls[idx]["id"],
                                tool_name=current_tool_calls[idx]["name"],
                            )
                        if tc_delta.function and tc_delta.function.arguments:
                            current_tool_calls[idx]["arguments"] += tc_delta.function.arguments
                            yield LLMStreamEvent(
                                type="tool_call_delta",
                                tool_call_id=current_tool_calls[idx]["id"],
                                arguments_delta=tc_delta.function.arguments,
                            )

                # Stream end
                if finish_reason is not None:
                    # Emit tool_call_end for all accumulated tool calls
                    for tc_data in current_tool_calls.values():
                        try:
                            parsed_args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                        except json.JSONDecodeError:
                            parsed_args = {}
                        yield LLMStreamEvent(
                            type="tool_call_end",
                            tool_call=ToolCall(
                                id=tc_data["id"],
                                name=tc_data["name"],
                                arguments=parsed_args,
                            ),
                        )
                    yield LLMStreamEvent(
                        type="done",
                        usage=accumulated_usage,
                        stop_reason=finish_reason,
                    )

        except openai.APITimeoutError as exc:
            yield LLMStreamEvent(type="error", error_message=str(exc))
        except openai.APIError as exc:
            yield LLMStreamEvent(type="error", error_message=str(exc))

    async def count_tokens(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        """Estimate token count using tiktoken (OpenAI-compatible providers).

        Falls back to character-based estimation if tiktoken doesn't
        have a mapping for the model.
        """
        try:
            import tiktoken

            try:
                enc = tiktoken.encoding_for_model(model)
            except KeyError:
                enc = tiktoken.get_encoding("cl100k_base")

            total = 0
            for msg in messages:
                total += 4  # message overhead
                total += len(enc.encode(msg.content))
                if msg.role:
                    total += len(enc.encode(msg.role))
            if tools:
                total += len(enc.encode(json.dumps(tools)))
            total += 2  # reply priming
            return total

        except ImportError:
            # Fallback: ~4 chars per token
            total_chars = sum(len(msg.content) for msg in messages)
            if tools:
                total_chars += len(json.dumps(tools))
            return total_chars // 4

    # ------------------------------------------------------------------
    # Retry logic (same pattern as AnthropicGateway)
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        call_fn: Any,
        retry_policy: RetryPolicy | None,
    ) -> Any:
        """Execute an LLM call with exponential backoff retry."""
        policy = retry_policy or RetryPolicy()
        last_error: Exception | None = None

        for attempt in range(1 + policy.max_retries):
            try:
                return await call_fn()

            except openai.RateLimitError as exc:
                last_error = exc
                if attempt >= policy.max_retries:
                    break
                wait = _calc_backoff(attempt, policy)
                logger.warning("Rate limited (attempt %d/%d), waiting %.1fs", attempt + 1, policy.max_retries, wait)
                await asyncio.sleep(wait)

            except openai.InternalServerError as exc:
                last_error = exc
                if attempt >= policy.max_retries:
                    break
                wait = _calc_backoff(attempt, policy)
                logger.warning("Server error (attempt %d/%d), waiting %.1fs", attempt + 1, policy.max_retries, wait)
                await asyncio.sleep(wait)

            except openai.APITimeoutError as exc:
                last_error = exc
                if attempt >= policy.max_retries:
                    break
                wait = _calc_backoff(attempt, policy)
                logger.warning("Timeout (attempt %d/%d), waiting %.1fs", attempt + 1, policy.max_retries, wait)
                await asyncio.sleep(wait)

            except openai.BadRequestError as exc:
                raise LLMError(
                    str(exc),
                    category=ErrorCategory.LLM_CONTENT_REFUSAL,
                    retryable=False,
                ) from exc

            except openai.AuthenticationError as exc:
                raise LLMError(
                    str(exc),
                    category=ErrorCategory.LLM_SERVER_ERROR,
                    retryable=False,
                ) from exc

        if isinstance(last_error, openai.RateLimitError):
            raise LLMRateLimitError(str(last_error)) from last_error
        if isinstance(last_error, openai.APITimeoutError):
            raise LLMTimeoutError(str(last_error)) from last_error
        raise LLMError(str(last_error)) from last_error


# ======================================================================
# Helper functions (module-private)
# ======================================================================


def _convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert platform Messages to OpenAI chat format."""
    result: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "tool":
            result.append({
                "role": "tool",
                "tool_call_id": msg.tool_call_id,
                "content": msg.content,
            })
        elif msg.role == "assistant" and msg.tool_calls:
            openai_msg: dict[str, Any] = {"role": "assistant"}
            if msg.content:
                openai_msg["content"] = msg.content
            else:
                openai_msg["content"] = None
            openai_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]
            result.append(openai_msg)
        else:
            result.append({"role": msg.role, "content": msg.content})
    return result


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert platform tool schemas to OpenAI function calling format."""
    openai_tools: list[dict[str, Any]] = []
    for tool in tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", tool.get("parameters", {})),
            },
        })
    return openai_tools


def _extract_tool_calls(message: Any) -> list[ToolCall] | None:
    """Extract tool calls from OpenAI response message."""
    if not message.tool_calls:
        return None
    calls: list[ToolCall] = []
    for tc in message.tool_calls:
        try:
            args = json.loads(tc.function.arguments) if tc.function.arguments else {}
        except json.JSONDecodeError:
            args = {}
        calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
    return calls if calls else None


def _calc_backoff(attempt: int, policy: RetryPolicy) -> float:
    """Calculate exponential backoff wait time."""
    wait = policy.backoff_base_seconds * (policy.backoff_multiplier ** attempt)
    return min(wait, policy.backoff_max_seconds)
