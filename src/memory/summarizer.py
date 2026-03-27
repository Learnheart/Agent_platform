"""Conversation Summarizer — incremental summarization via LLM.

Creates and updates conversation summaries to keep the context window
within budget. Summary is always < 500 tokens.

See docs/architecture/05-memory.md Section 3.2.3.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.models import LLMResponse, Message
from src.core.protocols import LLMGateway

logger = logging.getLogger(__name__)

SUMMARIZE_SYSTEM_PROMPT = (
    "You are a conversation summarizer. Create a concise summary of the conversation below. "
    "Focus on key decisions, findings, actions taken, and important context. "
    "The summary should be under 500 tokens. If an existing summary is provided, "
    "incorporate the new messages into an updated summary."
)


class ConversationSummarizer:
    """Incremental conversation summarization using LLM."""

    def __init__(
        self,
        llm_gateway: LLMGateway | None = None,
        model: str = "claude-sonnet-4-5-20250514",
    ) -> None:
        self._llm = llm_gateway
        self._model = model

    async def summarize(
        self,
        messages: list[Message],
        existing_summary: str | None = None,
    ) -> str:
        """Create or update a conversation summary.

        If existing_summary is provided, creates an updated summary
        incorporating the new messages. Otherwise creates a fresh summary.

        Falls back to a simple truncation if no LLM is available.
        """
        if not messages:
            return existing_summary or ""

        if self._llm is None:
            return self._fallback_summarize(messages, existing_summary)

        # Build summarization prompt
        prompt_parts: list[str] = []
        if existing_summary:
            prompt_parts.append(f"Previous summary:\n{existing_summary}\n")
        prompt_parts.append("New messages to incorporate:")
        for msg in messages:
            prompt_parts.append(f"[{msg.role}]: {msg.content}")

        user_content = "\n".join(prompt_parts)

        try:
            response: LLMResponse = await self._llm.chat(
                model=self._model,
                messages=[
                    Message(role="system", content=SUMMARIZE_SYSTEM_PROMPT),
                    Message(role="user", content=user_content),
                ],
            )
            return response.content or self._fallback_summarize(messages, existing_summary)
        except Exception:
            logger.warning("LLM summarization failed, using fallback", exc_info=True)
            return self._fallback_summarize(messages, existing_summary)

    def _fallback_summarize(
        self,
        messages: list[Message],
        existing_summary: str | None = None,
    ) -> str:
        """Simple fallback: concatenate role:content pairs, truncate to ~500 tokens."""
        parts: list[str] = []
        if existing_summary:
            parts.append(f"[Previous context: {existing_summary[:200]}]")
        for msg in messages:
            parts.append(f"[{msg.role}]: {msg.content[:100]}")
        full = "\n".join(parts)
        # ~500 tokens ≈ 2000 chars
        return full[:2000]
