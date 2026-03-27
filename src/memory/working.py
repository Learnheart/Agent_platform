"""Working Memory — session-scoped state for plans, artifacts, scratchpad.

Stores working state in Redis Hash for fast access during execution.

See docs/architecture/05-memory.md Section 3.3.
"""

from __future__ import annotations

from typing import Any


class WorkingMemory:
    """Session-scoped working memory backed by Redis.

    Stores:
    - Plan state (for plan-execute pattern, Phase 2)
    - Accumulated artifacts from tool calls
    - Scratchpad for agent notes
    """

    def __init__(self, session_store: Any) -> None:
        """Args:
            session_store: SessionRedisStore instance.
        """
        self._store = session_store

    # --- Plan ---

    async def get_plan(self, session_id: str) -> dict[str, Any] | None:
        """Get current plan for the session (Phase 2)."""
        return await self._store.get_working_field(session_id, "plan")

    async def update_plan(self, session_id: str, plan: dict[str, Any]) -> None:
        """Update the plan for the session."""
        await self._store.set_working_field(session_id, "plan", plan)

    # --- Artifacts ---

    async def get_artifacts(self, session_id: str) -> dict[str, Any]:
        """Get all accumulated artifacts."""
        result = await self._store.get_working_field(session_id, "artifacts")
        return result if isinstance(result, dict) else {}

    async def store_artifact(self, session_id: str, key: str, value: Any) -> None:
        """Store an artifact by key."""
        artifacts = await self.get_artifacts(session_id)
        artifacts[key] = value
        await self._store.set_working_field(session_id, "artifacts", artifacts)

    # --- Scratchpad ---

    async def get_scratchpad(self, session_id: str) -> str | None:
        """Get scratchpad content."""
        result = await self._store.get_working_field(session_id, "scratchpad")
        return str(result) if result is not None else None

    async def update_scratchpad(self, session_id: str, content: str) -> None:
        """Update scratchpad content."""
        await self._store.set_working_field(session_id, "scratchpad", content)

    # --- Build context string ---

    async def build_context_string(self, session_id: str) -> str | None:
        """Build a context string from working memory for injection into LLM context.

        Returns None if working memory is empty.
        """
        parts: list[str] = []

        plan = await self.get_plan(session_id)
        if plan:
            parts.append(f"[Current Plan]\n{_format_plan(plan)}")

        scratchpad = await self.get_scratchpad(session_id)
        if scratchpad:
            parts.append(f"[Scratchpad]\n{scratchpad}")

        artifacts = await self.get_artifacts(session_id)
        if artifacts:
            artifact_lines = [f"  - {k}: {_truncate(str(v), 200)}" for k, v in artifacts.items()]
            parts.append("[Artifacts]\n" + "\n".join(artifact_lines))

        return "\n\n".join(parts) if parts else None


def _format_plan(plan: dict[str, Any]) -> str:
    """Format a plan dict as readable text."""
    lines = [f"Goal: {plan.get('goal', 'N/A')}"]
    for step in plan.get("steps", []):
        status = step.get("status", "pending")
        task = step.get("task", "")
        lines.append(f"  [{status}] {task}")
    return "\n".join(lines)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
