"""Context Assembler — builds the LLM context window.

Assembly order (top = first in message list):
1. System prompt (always)
2. Long-term memory results (Phase 2 — placeholder)
3. Working memory / plan (Phase 2 — placeholder)
4. Budget warning (if approaching limit)
5. Conversation summary (if summarised)
6. Recent messages (user + assistant + tool)

Total tokens capped at agent max_context_tokens.
If over budget: trim from middle sections, never from system prompt or recent messages.

See docs/architecture/03-planning.md Section 2.8.
"""

from __future__ import annotations

from src.core.models import Agent, ContextPayload, Message


class ContextAssembler:
    """Builds the context payload for an LLM call."""

    # Rough average chars-per-token for estimation (conservative).
    CHARS_PER_TOKEN = 4

    def build(
        self,
        agent: Agent,
        messages: list[Message],
        tool_schemas: list[dict] | None = None,
        budget_warning: str | None = None,
        summary: str | None = None,
    ) -> ContextPayload:
        """Assemble context window respecting token limits.

        Args:
            agent: Agent definition (contains system prompt, config).
            messages: Full conversation history for the session.
            tool_schemas: Available tool JSON schemas.
            budget_warning: Warning message to inject if budget is running low.
            summary: Conversation summary to prepend (if history was summarised).

        Returns:
            ContextPayload ready to be sent to LLM.
        """
        max_tokens = agent.execution_config.max_context_tokens
        tool_schemas = tool_schemas or []

        # --- 1. System prompt (always present) ---
        system_prompt = agent.system_prompt

        # --- Build context messages in priority order ---
        context_messages: list[Message] = []

        # --- 2-3. Long-term / working memory (Phase 2 placeholder) ---
        # Will be injected here when Memory module is implemented.

        # --- 4. Budget warning ---
        if budget_warning:
            context_messages.append(
                Message(role="system", content=f"[BUDGET WARNING] {budget_warning}")
            )

        # --- 5. Conversation summary ---
        has_summary = False
        if summary:
            context_messages.append(
                Message(role="system", content=f"[CONVERSATION SUMMARY]\n{summary}")
            )
            has_summary = True

        # --- 6. Recent messages (never trimmed) ---
        recent = list(messages)

        # --- Token budget estimation ---
        system_tokens = self._estimate_tokens(system_prompt)
        tool_tokens = self._estimate_tokens(str(tool_schemas)) if tool_schemas else 0
        overhead = system_tokens + tool_tokens

        # Tokens available for context_messages + recent
        remaining = max_tokens - overhead

        # Recent messages get priority — calculate their cost
        recent_tokens = sum(self._estimate_tokens(m.content) for m in recent)

        # If recent alone exceeds budget, trim oldest messages
        if recent_tokens > remaining:
            recent = self._trim_messages(recent, remaining)
            recent_tokens = sum(self._estimate_tokens(m.content) for m in recent)
            # No room for middle sections
            context_messages = []
        else:
            # Trim middle sections (budget warning, summary) if needed
            middle_tokens = sum(self._estimate_tokens(m.content) for m in context_messages)
            if middle_tokens + recent_tokens > remaining:
                available_for_middle = remaining - recent_tokens
                context_messages = self._trim_messages(context_messages, available_for_middle)

        # Final assembly: middle sections + recent
        final_messages = context_messages + recent
        total_estimate = overhead + sum(self._estimate_tokens(m.content) for m in final_messages)

        return ContextPayload(
            system_prompt=system_prompt,
            messages=final_messages,
            tool_schemas=tool_schemas,
            total_tokens_estimate=total_estimate,
            has_summary=has_summary and any(
                "[CONVERSATION SUMMARY]" in m.content for m in final_messages
            ),
            budget_warning=budget_warning if any(
                "[BUDGET WARNING]" in m.content for m in final_messages
            ) else None,
        )

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate based on character count."""
        if not text:
            return 0
        return max(1, len(text) // self.CHARS_PER_TOKEN)

    def _trim_messages(self, messages: list[Message], max_tokens: int) -> list[Message]:
        """Keep messages from the end, dropping oldest first."""
        if not messages:
            return []
        result: list[Message] = []
        budget = max_tokens
        for msg in reversed(messages):
            cost = self._estimate_tokens(msg.content)
            if cost <= budget:
                result.append(msg)
                budget -= cost
            else:
                break
        result.reverse()
        return result
