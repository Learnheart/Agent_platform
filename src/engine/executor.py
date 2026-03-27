"""Agent Executor — main orchestrator for task execution.

Stateless orchestrator: loads session state at start, persists at end.
Runs the execution loop by delegating to an ExecutionEngine (ReAct in Phase 1).

See docs/architecture/03-planning.md Section 2.1.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.core.enums import AgentEventType, SessionState, StepType
from src.core.models import (
    Agent,
    AgentEvent,
    ContextPayload,
    ExecutionResult,
    ExecutionTask,
    Message,
    Session,
    StepResult,
)
from src.engine.budget import BudgetController
from src.engine.checkpoint import CheckpointManager
from src.engine.context import ContextAssembler
from src.engine.event_emitter import EventEmitter
from src.engine.react import ReActEngine

logger = logging.getLogger(__name__)


class AgentExecutor:
    """Main orchestrator that drives the execution loop.

    Dependencies are injected via constructor (see 03-planning Section 2.1).
    """

    def __init__(
        self,
        engine: ReActEngine,
        checkpoint_manager: CheckpointManager,
        budget_controller: BudgetController,
        context_assembler: ContextAssembler,
        event_emitter: EventEmitter,
        agent_store: Any | None = None,  # AgentRepository — for loading agent config
        message_store: Any | None = None,  # MessageRepository — for loading history
    ) -> None:
        self._engine = engine
        self._checkpoint = checkpoint_manager
        self._budget = budget_controller
        self._context = context_assembler
        self._events = event_emitter
        self._agent_store = agent_store
        self._message_store = message_store

    async def execute(
        self,
        task: ExecutionTask,
        agent: Agent,
        messages: list[Message] | None = None,
    ) -> ExecutionResult:
        """Execute a task through the full lifecycle.

        Steps:
        1. Load/create session from checkpoint
        2. Run engine.step() in a loop until terminal condition
        3. Persist state after each step
        4. Emit events for tracing + streaming

        Args:
            task: The execution task from the queue.
            agent: Agent definition (loaded by caller).
            messages: Initial messages (for new sessions). If None, loaded from store.

        Returns:
            ExecutionResult with the final session state.
        """
        # 1. Load or create session
        session = await self._checkpoint.restore(task.session_id, task.tenant_id)

        if session is None:
            session = Session(
                id=task.session_id,
                tenant_id=task.tenant_id,
                agent_id=task.agent_id,
                state=SessionState.RUNNING,
                metadata={
                    "model_config": agent.model_config_.model_dump(mode="json"),
                },
            )
        else:
            session.state = SessionState.RUNNING

        # Emit session start
        await self._events.emit_one(AgentEvent(
            type=AgentEventType.SESSION_CREATED,
            session_id=session.id,
            tenant_id=session.tenant_id,
            agent_id=session.agent_id,
            data={"trigger": task.trigger.type},
        ))

        conversation: list[Message] = list(messages or [])

        # 2. Execution loop
        consecutive_tool_calls = 0
        max_consecutive = agent.execution_config.react_max_consecutive_tool_calls

        while True:
            # Pre-step: budget check
            budget_result = self._budget.check(session, agent.execution_config)

            if budget_result.exhausted:
                session.state = SessionState.COMPLETED
                await self._events.emit_one(AgentEvent(
                    type=AgentEventType.BUDGET_WARNING,
                    session_id=session.id,
                    tenant_id=session.tenant_id,
                    agent_id=session.agent_id,
                    step_index=session.step_index,
                    data={"exhausted": True, "message": budget_result.warning_message},
                ))
                break

            # Build context
            budget_warning = budget_result.warning_message if budget_result.warning else None
            ctx = self._context.build(
                agent=agent,
                messages=conversation,
                tool_schemas=self._get_tool_schemas(agent),
                budget_warning=budget_warning,
            )

            # Step start event
            await self._events.emit_one(AgentEvent(
                type=AgentEventType.STEP_START,
                session_id=session.id,
                tenant_id=session.tenant_id,
                agent_id=session.agent_id,
                step_index=session.step_index,
                data={"pattern": agent.execution_config.pattern},
            ))

            # Execute one step
            step_result = await self._engine.step(session, ctx)

            # Post-step: update session
            session.step_index += 1
            session.usage.total_steps += 1
            session.usage.prompt_tokens += step_result.usage.prompt_tokens
            session.usage.completion_tokens += step_result.usage.completion_tokens
            session.usage.total_tokens += step_result.usage.prompt_tokens + step_result.usage.completion_tokens
            session.usage.total_cost_usd += step_result.usage.cost_usd
            session.usage.total_llm_calls += 1
            if step_result.tool_calls:
                session.usage.total_tool_calls += len(step_result.tool_calls)

            # Append messages to conversation
            conversation.extend(step_result.messages)

            # Merge metadata updates
            if step_result.metadata_updates:
                session.metadata.update(step_result.metadata_updates)

            # Persist checkpoint
            if agent.execution_config.checkpoint_enabled:
                await self._checkpoint.save_delta(session, step_result)

            # Emit step events
            await self._events.emit(step_result.events)

            # Check result type
            match step_result.type:
                case StepType.FINAL_ANSWER:
                    session.state = SessionState.COMPLETED
                    break

                case StepType.WAITING_INPUT:
                    session.state = SessionState.WAITING_INPUT
                    break

                case StepType.TOOL_CALL:
                    consecutive_tool_calls += 1
                    # Infinite loop detection
                    if consecutive_tool_calls >= max_consecutive:
                        logger.warning(
                            "Max consecutive tool calls reached (%d), forcing stop",
                            max_consecutive,
                        )
                        session.state = SessionState.COMPLETED
                        break
                    continue

                case StepType.ERROR:
                    if step_result.retryable and self._can_retry(session, agent):
                        retry_count = session.metadata.get("retry_count", 0) + 1
                        session.metadata["retry_count"] = retry_count
                        await asyncio.sleep(
                            agent.execution_config.retry_backoff_seconds * retry_count
                        )
                        continue
                    else:
                        session.state = SessionState.FAILED
                        break

        # 3. Finalize
        if agent.execution_config.checkpoint_enabled:
            await self._checkpoint.save_snapshot(session)

        await self._events.emit_one(AgentEvent(
            type=AgentEventType.SESSION_COMPLETED,
            session_id=session.id,
            tenant_id=session.tenant_id,
            agent_id=session.agent_id,
            data={
                "state": session.state.value,
                "total_steps": session.usage.total_steps,
                "total_cost": session.usage.total_cost_usd,
            },
        ))

        return ExecutionResult(session=session)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _can_retry(self, session: Session, agent: Agent) -> bool:
        """Check if the current step can be retried."""
        retry_count = session.metadata.get("retry_count", 0)
        return retry_count < agent.execution_config.max_retries_per_step

    def _get_tool_schemas(self, agent: Agent) -> list[dict]:
        """Get tool schemas for the agent. Phase 1: empty (tools from MCP not yet wired)."""
        return []
