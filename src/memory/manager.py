"""Memory Manager — orchestrator for all memory layers.

Coordinates short-term (conversation buffer + summary), working memory,
and builds the context payload for LLM calls.

See docs/architecture/05-memory.md Section 3.1.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.models import Agent, ContextPayload, Message
from src.memory.conversation_buffer import ConversationBuffer
from src.memory.summarizer import ConversationSummarizer
from src.memory.working import WorkingMemory

logger = logging.getLogger(__name__)

# Default number of recent messages to keep when summarizing
DEFAULT_RECENT_MESSAGES = 10


class MemoryManager:
    """Orchestrates all memory operations across layers.

    Phase 1: Short-term memory + Working memory.
    Phase 2: Long-term memory (vector store) will be added.
    """

    def __init__(
        self,
        conversation_buffer: ConversationBuffer,
        working_memory: WorkingMemory,
        summarizer: ConversationSummarizer | None = None,
    ) -> None:
        self._buffer = conversation_buffer
        self._working = working_memory
        self._summarizer = summarizer

    # ------------------------------------------------------------------
    # build_context — called by Executor before each LLM call
    # ------------------------------------------------------------------

    async def build_context(
        self,
        session_id: str,
        agent: Agent,
        budget_warning: str | None = None,
    ) -> ContextPayload:
        """Assemble the full context for an LLM call.

        Assembly order:
        1. System prompt from agent config
        2. Working memory (plan, scratchpad, artifacts)
        3. Conversation summary (if exists)
        4. Budget warning (if approaching limit)
        5. Recent messages
        """
        max_tokens = agent.execution_config.max_context_tokens
        messages: list[Message] = []

        # 1. Working memory injection
        working_ctx = await self._working.build_context_string(session_id)
        if working_ctx:
            messages.append(Message(role="system", content=working_ctx))

        # 2. Conversation summary
        summary = await self._buffer.get_summary(session_id)
        has_summary = False
        if summary:
            messages.append(Message(role="system", content=f"[CONVERSATION SUMMARY]\n{summary}"))
            has_summary = True

        # 3. Budget warning
        if budget_warning:
            messages.append(Message(role="system", content=f"[BUDGET WARNING] {budget_warning}"))

        # 4. Recent messages
        recent = await self._buffer.get_all(session_id)
        messages.extend(recent)

        # 5. Token budget check — trim if needed
        total_estimate = self._estimate_tokens(agent.system_prompt) + sum(
            self._estimate_tokens(m.content) for m in messages
        )
        if total_estimate > max_tokens:
            messages = self._trim_to_budget(messages, max_tokens, agent.system_prompt)
            total_estimate = self._estimate_tokens(agent.system_prompt) + sum(
                self._estimate_tokens(m.content) for m in messages
            )

        return ContextPayload(
            system_prompt=agent.system_prompt,
            messages=messages,
            total_tokens_estimate=total_estimate,
            has_summary=has_summary,
            budget_warning=budget_warning,
        )

    # ------------------------------------------------------------------
    # update — called by Executor after each step
    # ------------------------------------------------------------------

    async def update(
        self,
        session_id: str,
        messages: list[Message],
        agent: Agent,
        artifacts: dict[str, Any] | None = None,
    ) -> None:
        """Update memory after an execution step.

        1. Append new messages to conversation buffer
        2. Store artifacts in working memory
        3. Check if summarization is needed
        """
        # 1. Append messages
        await self._buffer.append_many(session_id, messages)

        # 2. Store artifacts
        if artifacts:
            for key, value in artifacts.items():
                await self._working.store_artifact(session_id, key, value)

        # 3. Auto-summarization check
        await self._maybe_summarize(session_id, agent)

    # ------------------------------------------------------------------
    # Auto-summarization
    # ------------------------------------------------------------------

    async def _maybe_summarize(self, session_id: str, agent: Agent) -> None:
        """Trigger summarization if conversation exceeds threshold."""
        if self._summarizer is None:
            return

        threshold = agent.memory_config.summarize_threshold
        max_tokens = agent.memory_config.max_context_tokens
        token_count = await self._buffer.get_token_count(session_id)

        if token_count <= max_tokens * threshold:
            return

        logger.info(
            "Auto-summarizing session %s (tokens: %d, threshold: %d)",
            session_id, token_count, int(max_tokens * threshold),
        )

        # Get all messages, summarize older ones, keep recent
        all_msgs = await self._buffer.get_all(session_id)
        if len(all_msgs) <= DEFAULT_RECENT_MESSAGES:
            return

        old_msgs = all_msgs[:-DEFAULT_RECENT_MESSAGES]
        existing_summary = await self._buffer.get_summary(session_id)

        summary = await self._summarizer.summarize(old_msgs, existing_summary)
        await self._buffer.set_summary(session_id, summary)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def _trim_to_budget(
        self,
        messages: list[Message],
        max_tokens: int,
        system_prompt: str,
    ) -> list[Message]:
        """Trim messages to fit token budget, keeping recent messages."""
        overhead = self._estimate_tokens(system_prompt)
        remaining = max_tokens - overhead

        # Keep messages from the end
        result: list[Message] = []
        budget = remaining
        for msg in reversed(messages):
            cost = self._estimate_tokens(msg.content)
            if cost <= budget:
                result.append(msg)
                budget -= cost
            else:
                break
        result.reverse()
        return result
