"""Conversation Buffer — full conversation history management.

Stores the complete message history in Redis. Provides access to
recent messages and token counting for context management.

See docs/architecture/05-memory.md Section 3.2.2.
"""

from __future__ import annotations

from typing import Any

from src.core.models import Message

# Rough chars-per-token for estimation
CHARS_PER_TOKEN = 4


class ConversationBuffer:
    """Manages the full conversation history for a session.

    Wraps SessionRedisStore for message operations and adds
    token estimation.
    """

    def __init__(self, session_store: Any) -> None:
        """Args:
            session_store: SessionRedisStore instance.
        """
        self._store = session_store

    async def append(self, session_id: str, message: Message) -> None:
        """Append a message to the buffer."""
        await self._store.append_message(session_id, message.model_dump(mode="json"))

    async def append_many(self, session_id: str, messages: list[Message]) -> None:
        """Append multiple messages at once."""
        if not messages:
            return
        dicts = [m.model_dump(mode="json") for m in messages]
        await self._store.append_messages(session_id, dicts)

    async def get_all(self, session_id: str) -> list[Message]:
        """Get full conversation history."""
        raw = await self._store.get_all_messages(session_id)
        return [Message.model_validate(r) for r in raw]

    async def get_recent(self, session_id: str, n: int) -> list[Message]:
        """Get the N most recent messages."""
        raw = await self._store.get_recent_messages(session_id, n)
        return [Message.model_validate(r) for r in raw]

    async def get_token_count(self, session_id: str) -> int:
        """Estimate total token count of the conversation."""
        messages = await self.get_all(session_id)
        return sum(self._estimate_tokens(m.content) for m in messages)

    async def get_summary(self, session_id: str) -> str | None:
        """Get the current conversation summary."""
        return await self._store.get_summary(session_id)

    async def set_summary(self, session_id: str, summary: str) -> None:
        """Store a conversation summary."""
        await self._store.set_summary(session_id, summary)

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // CHARS_PER_TOKEN)
