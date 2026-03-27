"""ReAct Engine — Think → Act → Observe reasoning loop.

Phase 1 execution pattern. Each call to step() performs one
Think→Act→Observe cycle and returns a StepResult.

See docs/architecture/03-planning.md Section 2.3.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.core.enums import AgentEventType, ErrorCategory, StepType
from src.core.errors import LLMError
from src.core.models import (
    AgentEvent,
    ContextPayload,
    LLMResponse,
    Message,
    Session,
    StepResult,
    StepUsage,
    ToolCall,
    ToolResult,
)
from src.core.protocols import LLMGateway, ToolRuntime

logger = logging.getLogger(__name__)


class _GuardrailResult:
    """Minimal guardrail check result for Phase 1.

    Will be replaced by the real GuardrailsEngine in M8.
    """

    def __init__(self, allowed: bool = True, requires_approval: bool = False, reason: str = ""):
        self.allowed = allowed
        self.requires_approval = requires_approval
        self.reason = reason


class ReActEngine:
    """ReAct (Reasoning + Acting) execution engine.

    Implements the ExecutionEngine protocol defined in core/protocols.py.
    Each step() call:
      1. Calls LLM with current context + tools
      2. If LLM returns tool_calls → execute tools → return TOOL_CALL step
      3. If LLM returns text only → return FINAL_ANSWER step
    """

    def __init__(
        self,
        llm_gateway: LLMGateway,
        tool_runtime: ToolRuntime | None = None,
        guardrails: Any | None = None,  # GuardrailsEngine (Phase 2)
    ) -> None:
        self._llm = llm_gateway
        self._tools = tool_runtime
        self._guardrails = guardrails

    async def step(
        self,
        session: Session,
        context: ContextPayload,
    ) -> StepResult:
        """Execute one Think → Act → Observe cycle."""
        events: list[AgentEvent] = []
        step_start = time.monotonic()

        event_base = {
            "session_id": session.id,
            "tenant_id": session.tenant_id,
            "agent_id": session.agent_id,
            "step_index": session.step_index,
        }

        # --- THINK: call LLM ---
        events.append(AgentEvent(
            type=AgentEventType.LLM_CALL_START,
            data={"model": session.model_config.get("model", "") if isinstance(session.metadata.get("model_config"), dict) else ""},
            **event_base,
        ))

        llm_start = time.monotonic()
        try:
            llm_response = await self._call_llm(session, context)
        except LLMError as exc:
            return self._error_result(exc, events, event_base, step_start)
        except Exception as exc:
            return self._error_result(exc, events, event_base, step_start)

        llm_latency = (time.monotonic() - llm_start) * 1000

        events.append(AgentEvent(
            type=AgentEventType.LLM_CALL_END,
            data={
                "model": llm_response.model,
                "prompt_tokens": llm_response.usage.prompt_tokens,
                "completion_tokens": llm_response.usage.completion_tokens,
                "cost": llm_response.usage.cost_usd or 0.0,
                "latency_ms": llm_latency,
            },
            **event_base,
        ))

        # --- Decide: tool calls or final answer? ---
        if llm_response.tool_calls:
            return await self._handle_tool_calls(
                session, llm_response, events, event_base, step_start, llm_latency,
            )

        # --- FINAL ANSWER (text only) ---
        return self._handle_final_answer(
            session, llm_response, events, event_base, step_start, llm_latency,
        )

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    async def _call_llm(self, session: Session, context: ContextPayload) -> LLMResponse:
        """Call LLM gateway with context."""
        model_cfg = session.metadata.get("model_config", {})
        model = model_cfg.get("model", "claude-sonnet-4-5-20250514") if isinstance(model_cfg, dict) else "claude-sonnet-4-5-20250514"
        provider = model_cfg.get("provider", "anthropic") if isinstance(model_cfg, dict) else "anthropic"

        # Prepend system prompt as first system message
        messages = [Message(role="system", content=context.system_prompt)] + list(context.messages)

        return await self._llm.chat(
            model=model,
            messages=messages,
            tools=context.tool_schemas or None,
        )

    # ------------------------------------------------------------------
    # Tool call handling
    # ------------------------------------------------------------------

    async def _handle_tool_calls(
        self,
        session: Session,
        llm_response: LLMResponse,
        events: list[AgentEvent],
        event_base: dict[str, Any],
        step_start: float,
        llm_latency: float,
    ) -> StepResult:
        """Process tool calls from the LLM response."""
        assert llm_response.tool_calls is not None

        # Build assistant message with tool calls
        assistant_msg = Message(
            role="assistant",
            content=llm_response.content or "",
            tool_calls=llm_response.tool_calls,
            session_id=session.id,
        )

        all_messages: list[Message] = [assistant_msg]
        all_tool_results: list[ToolResult] = []
        total_tool_latency = 0.0

        for tc in llm_response.tool_calls:
            # Emit tool_call event
            events.append(AgentEvent(
                type=AgentEventType.TOOL_CALL,
                data={"tool_name": tc.name, "input": tc.arguments},
                **event_base,
            ))

            # Guardrails check (Phase 1: allow all)
            guard_result = await self._check_guardrails(tc, session)

            if not guard_result.allowed:
                # Permission denied
                tool_result = ToolResult(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=f"Permission denied: {guard_result.reason}",
                    is_error=True,
                )
            elif guard_result.requires_approval:
                # HITL gate — pause session
                return StepResult(
                    type=StepType.WAITING_INPUT,
                    messages=all_messages,
                    tool_calls=llm_response.tool_calls,
                    events=events,
                    usage=self._build_usage(llm_response, llm_latency, 0),
                    approval_id=tc.id,
                )
            else:
                # Execute tool
                tool_result = await self._execute_tool(tc, session)

            total_tool_latency += tool_result.latency_ms
            all_tool_results.append(tool_result)

            # Tool result as message
            all_messages.append(Message(
                role="tool",
                content=tool_result.content,
                tool_call_id=tc.id,
                session_id=session.id,
            ))

            events.append(AgentEvent(
                type=AgentEventType.TOOL_RESULT,
                data={
                    "tool_name": tc.name,
                    "success": not tool_result.is_error,
                    "duration_ms": tool_result.latency_ms,
                },
                **event_base,
            ))

        return StepResult(
            type=StepType.TOOL_CALL,
            messages=all_messages,
            tool_calls=llm_response.tool_calls,
            tool_results=all_tool_results,
            events=events,
            usage=self._build_usage(llm_response, llm_latency, total_tool_latency),
        )

    # ------------------------------------------------------------------
    # Final answer handling
    # ------------------------------------------------------------------

    def _handle_final_answer(
        self,
        session: Session,
        llm_response: LLMResponse,
        events: list[AgentEvent],
        event_base: dict[str, Any],
        step_start: float,
        llm_latency: float,
    ) -> StepResult:
        """LLM returned text without tool calls → final answer."""
        answer = llm_response.content or ""

        events.append(AgentEvent(
            type=AgentEventType.FINAL_ANSWER,
            data={"content": answer[:500]},  # truncate for event payload
            **event_base,
        ))

        msg = Message(role="assistant", content=answer, session_id=session.id)

        return StepResult(
            type=StepType.FINAL_ANSWER,
            messages=[msg],
            answer=answer,
            events=events,
            usage=self._build_usage(llm_response, llm_latency, 0),
        )

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def _error_result(
        self,
        exc: Exception,
        events: list[AgentEvent],
        event_base: dict[str, Any],
        step_start: float,
    ) -> StepResult:
        """Build StepResult for an error."""
        is_llm_error = isinstance(exc, LLMError)
        category = exc.category.value if is_llm_error and exc.category else ErrorCategory.LLM_SERVER_ERROR.value
        retryable = exc.retryable if is_llm_error else False

        events.append(AgentEvent(
            type=AgentEventType.ERROR,
            data={"message": str(exc), "retryable": retryable},
            **event_base,
        ))

        return StepResult(
            type=StepType.ERROR,
            error_message=str(exc),
            error_category=category,
            retryable=retryable,
            events=events,
            usage=StepUsage(latency_ms=(time.monotonic() - step_start) * 1000),
        )

    # ------------------------------------------------------------------
    # Guardrails stub
    # ------------------------------------------------------------------

    async def _check_guardrails(self, tool_call: ToolCall, session: Session) -> _GuardrailResult:
        """Check guardrails for a tool call.

        Phase 1: always allow. Will be replaced by GuardrailsEngine in M8.
        """
        if self._guardrails is not None:
            try:
                return await self._guardrails.check_tool_call(tool_call, session)
            except Exception:
                logger.warning("Guardrail check failed, defaulting to allow", exc_info=True)
        return _GuardrailResult(allowed=True)

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _execute_tool(self, tool_call: ToolCall, session: Session) -> ToolResult:
        """Execute a single tool call via ToolRuntime."""
        if self._tools is None:
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content="Tool runtime not available",
                is_error=True,
            )
        tool_start = time.monotonic()
        try:
            result = await self._tools.invoke(session.tenant_id, session.id, tool_call)
            result.latency_ms = (time.monotonic() - tool_start) * 1000
            return result
        except Exception as exc:
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=f"Tool execution error: {exc}",
                is_error=True,
                latency_ms=(time.monotonic() - tool_start) * 1000,
            )

    # ------------------------------------------------------------------
    # Usage helpers
    # ------------------------------------------------------------------

    def _build_usage(
        self, llm_response: LLMResponse, llm_latency: float, tool_latency: float
    ) -> StepUsage:
        return StepUsage(
            prompt_tokens=llm_response.usage.prompt_tokens,
            completion_tokens=llm_response.usage.completion_tokens,
            cost_usd=llm_response.usage.cost_usd or 0.0,
            llm_latency_ms=llm_latency,
            tool_latency_ms=tool_latency,
            latency_ms=llm_latency + tool_latency,
        )
