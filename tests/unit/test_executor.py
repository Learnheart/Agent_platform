"""Tests for AgentExecutor — main orchestrator."""

from unittest.mock import AsyncMock, patch

import pytest

from src.core.enums import SessionState, StepType
from src.core.models import (
    Agent,
    AgentEvent,
    ExecutionConfig,
    ExecutionTask,
    ExecutionTrigger,
    LLMResponse,
    Message,
    ModelConfig,
    Session,
    StepResult,
    StepUsage,
    TokenUsage,
    ToolCall,
    ToolResult,
)
from src.engine.budget import BudgetController
from src.engine.checkpoint import CheckpointManager
from src.engine.context import ContextAssembler
from src.engine.event_emitter import EventEmitter
from src.engine.executor import AgentExecutor
from src.engine.react import ReActEngine


def _agent(**overrides) -> Agent:
    defaults = dict(
        tenant_id="t1",
        name="test-agent",
        system_prompt="You are helpful.",
        model_config=ModelConfig(),
        execution_config=ExecutionConfig(max_steps=10, max_retries_per_step=2),
    )
    defaults.update(overrides)
    return Agent(**defaults)


def _task(**overrides) -> ExecutionTask:
    defaults = dict(
        session_id="s1",
        agent_id="a1",
        tenant_id="t1",
        trigger=ExecutionTrigger(type="new_message"),
    )
    defaults.update(overrides)
    return ExecutionTask(**defaults)


def _final_answer_step(answer: str = "Done.") -> StepResult:
    return StepResult(
        type=StepType.FINAL_ANSWER,
        messages=[Message(role="assistant", content=answer, session_id="s1")],
        answer=answer,
        usage=StepUsage(prompt_tokens=50, completion_tokens=20, cost_usd=0.001),
    )


def _tool_call_step() -> StepResult:
    return StepResult(
        type=StepType.TOOL_CALL,
        messages=[
            Message(role="assistant", content="calling tool", session_id="s1"),
            Message(role="tool", content="result", tool_call_id="tc1", session_id="s1"),
        ],
        tool_calls=[ToolCall(id="tc1", name="search", arguments={})],
        tool_results=[ToolResult(tool_call_id="tc1", tool_name="search", content="result")],
        usage=StepUsage(prompt_tokens=30, completion_tokens=20, cost_usd=0.001),
    )


def _error_step(retryable: bool = False) -> StepResult:
    return StepResult(
        type=StepType.ERROR,
        error_message="something went wrong",
        retryable=retryable,
        usage=StepUsage(),
    )


def _waiting_step() -> StepResult:
    return StepResult(
        type=StepType.WAITING_INPUT,
        messages=[Message(role="assistant", content="need approval", session_id="s1")],
        usage=StepUsage(),
        approval_id="tc1",
    )


def _build_executor(engine_steps: list[StepResult]) -> AgentExecutor:
    """Build executor with mocked dependencies."""
    engine = AsyncMock(spec=ReActEngine)
    engine.step = AsyncMock(side_effect=engine_steps)

    redis_store = AsyncMock()
    redis_store.append_delta = AsyncMock()
    redis_store.save_snapshot = AsyncMock()
    redis_store.clear_deltas = AsyncMock()
    redis_store.get_snapshot = AsyncMock(return_value=None)
    redis_store.get_deltas_after = AsyncMock(return_value=[])
    redis_store.delete_all = AsyncMock()

    checkpoint = CheckpointManager(redis_store=redis_store)
    budget = BudgetController()
    context = ContextAssembler()
    events = EventEmitter(pubsub=None)

    return AgentExecutor(
        engine=engine,
        checkpoint_manager=checkpoint,
        budget_controller=budget,
        context_assembler=context,
        event_emitter=events,
    )


# --- Happy path ---


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_single_step_final_answer(self):
        executor = _build_executor([_final_answer_step("The answer is 42.")])
        result = await executor.execute(_task(), _agent(), messages=[Message(role="user", content="hi", session_id="s1")])

        assert result.session.state == SessionState.COMPLETED
        assert result.session.usage.total_steps == 1

    @pytest.mark.asyncio
    async def test_tool_call_then_final_answer(self):
        executor = _build_executor([_tool_call_step(), _final_answer_step()])
        result = await executor.execute(_task(), _agent(), messages=[Message(role="user", content="search something", session_id="s1")])

        assert result.session.state == SessionState.COMPLETED
        assert result.session.usage.total_steps == 2
        assert result.session.usage.total_tool_calls == 1

    @pytest.mark.asyncio
    async def test_usage_accumulated(self):
        executor = _build_executor([_tool_call_step(), _final_answer_step()])
        result = await executor.execute(_task(), _agent(), messages=[])

        assert result.session.usage.prompt_tokens == 80  # 30 + 50
        assert result.session.usage.total_cost_usd > 0


# --- Budget exhaustion ---


class TestBudgetExhaustion:
    @pytest.mark.asyncio
    async def test_stops_when_budget_exhausted(self):
        agent = _agent(execution_config=ExecutionConfig(max_steps=2))
        # 2 tool calls will reach step budget
        executor = _build_executor([_tool_call_step(), _tool_call_step(), _final_answer_step()])
        result = await executor.execute(_task(), agent, messages=[])

        assert result.session.state == SessionState.COMPLETED
        assert result.session.usage.total_steps == 2


# --- Error handling ---


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_non_retryable_error_fails_session(self):
        executor = _build_executor([_error_step(retryable=False)])
        result = await executor.execute(_task(), _agent(), messages=[])

        assert result.session.state == SessionState.FAILED

    @pytest.mark.asyncio
    async def test_retryable_error_retries_then_succeeds(self):
        executor = _build_executor([
            _error_step(retryable=True),
            _final_answer_step(),
        ])
        result = await executor.execute(_task(), _agent(), messages=[])

        assert result.session.state == SessionState.COMPLETED
        assert result.session.usage.total_steps == 2

    @pytest.mark.asyncio
    async def test_retryable_error_exhausts_retries(self):
        agent = _agent(execution_config=ExecutionConfig(max_retries_per_step=1, retry_backoff_seconds=0.01))
        executor = _build_executor([
            _error_step(retryable=True),
            _error_step(retryable=True),
        ])
        result = await executor.execute(_task(), agent, messages=[])

        assert result.session.state == SessionState.FAILED


# --- HITL gate ---


class TestWaitingInput:
    @pytest.mark.asyncio
    async def test_waiting_input_pauses_session(self):
        executor = _build_executor([_waiting_step()])
        result = await executor.execute(_task(), _agent(), messages=[])

        assert result.session.state == SessionState.WAITING_INPUT


# --- Infinite loop protection ---


class TestInfiniteLoopProtection:
    @pytest.mark.asyncio
    async def test_max_consecutive_tool_calls_stops(self):
        agent = _agent(execution_config=ExecutionConfig(
            react_max_consecutive_tool_calls=3,
            max_steps=100,
        ))
        steps = [_tool_call_step() for _ in range(5)]
        executor = _build_executor(steps)
        result = await executor.execute(_task(), agent, messages=[])

        assert result.session.state == SessionState.COMPLETED
        assert result.session.usage.total_steps == 3


# --- Checkpoint ---


class TestCheckpointing:
    @pytest.mark.asyncio
    async def test_checkpoint_disabled_skips_save(self):
        agent = _agent(execution_config=ExecutionConfig(checkpoint_enabled=False))
        executor = _build_executor([_final_answer_step()])

        # Spy on checkpoint
        executor._checkpoint.save_delta = AsyncMock()
        executor._checkpoint.save_snapshot = AsyncMock()

        await executor.execute(_task(), agent, messages=[])

        executor._checkpoint.save_delta.assert_not_called()
        executor._checkpoint.save_snapshot.assert_not_called()
