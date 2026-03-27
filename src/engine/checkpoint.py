"""Checkpoint Manager — delta-based checkpoint with snapshot compaction.

Saves a delta after every step and a full snapshot every N steps.
On restore, loads the last snapshot + replays deltas on top.

See docs/architecture/03-planning.md Section 2.6.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import msgpack

from src.core.models import (
    CheckpointDelta,
    CheckpointSnapshot,
    Message,
    Session,
    SessionUsage,
    StepResult,
)

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Delta-based checkpoint manager backed by Redis (hot) + PostgreSQL (durable).

    Constructor accepts the Redis and PG store objects directly so that
    the manager stays decoupled from connection details.
    """

    def __init__(
        self,
        redis_store: Any,  # CheckpointRedisStore
        pg_repo: Any | None = None,  # CheckpointRepository (optional for unit tests)
        snapshot_interval: int = 10,
    ) -> None:
        self._redis = redis_store
        self._pg = pg_repo
        self._snapshot_interval = snapshot_interval

    # ------------------------------------------------------------------
    # save_delta
    # ------------------------------------------------------------------

    async def save_delta(
        self,
        session: Session,
        step_result: StepResult,
    ) -> None:
        """Persist an incremental delta after a single execution step."""
        delta = CheckpointDelta(
            session_id=session.id,
            step_index=session.step_index,
            new_messages=step_result.messages,
            tool_results=step_result.tool_results,
            metadata_updates=step_result.metadata_updates,
            token_usage_delta=step_result.usage,
        )
        delta_dict = self._delta_to_dict(delta)

        # Redis (hot)
        await self._redis.append_delta(session.id, delta_dict, ttl=session.ttl_seconds)

        # PostgreSQL (durable, async best-effort)
        if self._pg is not None:
            try:
                await self._pg.append_delta(session.tenant_id, delta_dict)
            except Exception:
                logger.warning("PG delta write failed (non-blocking)", exc_info=True)

        # Auto-snapshot every N steps
        if self._snapshot_interval > 0 and session.step_index % self._snapshot_interval == 0 and session.step_index > 0:
            await self.save_snapshot(session)

    # ------------------------------------------------------------------
    # save_snapshot
    # ------------------------------------------------------------------

    async def save_snapshot(self, session: Session) -> None:
        """Persist a full session state snapshot."""
        state_bytes = msgpack.packb(session.model_dump(mode="json"), default=str)
        conv_hash = hashlib.sha256(state_bytes).hexdigest()[:16]

        snapshot = CheckpointSnapshot(
            session_id=session.id,
            step_index=session.step_index,
            state=state_bytes,
            conversation_hash=conv_hash,
            usage=session.usage,
        )

        # Redis
        await self._redis.save_snapshot(session.id, snapshot.state, ttl=session.ttl_seconds)
        # Clear applied deltas from Redis
        await self._redis.clear_deltas(session.id)

        # PostgreSQL
        if self._pg is not None:
            try:
                snap_dict = {
                    "session_id": snapshot.session_id,
                    "step_index": snapshot.step_index,
                    "state": snapshot.state,
                    "conversation_hash": snapshot.conversation_hash,
                    "usage": snapshot.usage.model_dump(mode="json"),
                }
                await self._pg.upsert_snapshot(session.tenant_id, snap_dict)
                await self._pg.delete_deltas(session.tenant_id, session.id, session.step_index)
            except Exception:
                logger.warning("PG snapshot write failed (non-blocking)", exc_info=True)

    # ------------------------------------------------------------------
    # restore
    # ------------------------------------------------------------------

    async def restore(self, session_id: str, tenant_id: str) -> Session | None:
        """Restore session from last snapshot + replay deltas.

        Returns None if no checkpoint exists (new session).
        """
        # 1. Load snapshot from Redis, fallback PG
        snapshot_bytes = await self._redis.get_snapshot(session_id)

        if snapshot_bytes is None and self._pg is not None:
            pg_snap = await self._pg.get_latest_snapshot(tenant_id, session_id)
            if pg_snap is not None:
                snapshot_bytes = pg_snap.get("state")

        if snapshot_bytes is None:
            return None

        # 2. Deserialize snapshot → Session
        state_dict = msgpack.unpackb(snapshot_bytes, raw=False)
        session = Session.model_validate(state_dict)

        # 3. Load deltas after snapshot
        deltas = await self._redis.get_deltas_after(session_id, session.step_index)

        if not deltas and self._pg is not None:
            try:
                deltas = await self._pg.get_deltas_after(tenant_id, session_id, session.step_index)
            except Exception:
                logger.warning("PG delta read failed during restore", exc_info=True)
                deltas = []

        # 4. Replay deltas
        for delta_dict in deltas:
            self._apply_delta(session, delta_dict)

        # 5. Warm up Redis with restored session
        state_bytes = msgpack.packb(session.model_dump(mode="json"), default=str)
        await self._redis.save_snapshot(session_id, state_bytes, ttl=session.ttl_seconds)

        return session

    # ------------------------------------------------------------------
    # cleanup
    # ------------------------------------------------------------------

    async def cleanup(self, session_id: str) -> None:
        """Remove all checkpoint data from Redis for a session."""
        await self._redis.delete_all(session_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _delta_to_dict(self, delta: CheckpointDelta) -> dict[str, Any]:
        return delta.model_dump(mode="json")

    def _apply_delta(self, session: Session, delta_dict: dict[str, Any]) -> None:
        """Replay a single delta on top of a session."""
        # Advance step index
        step_idx = delta_dict.get("step_index", session.step_index)
        if step_idx > session.step_index:
            session.step_index = step_idx

        # Append new messages
        new_msgs = delta_dict.get("new_messages", [])
        # Messages are stored but session model doesn't hold them inline;
        # we track step_index + usage instead. If the session later needs
        # message history, it will be loaded from the message store.

        # Merge metadata updates
        meta = delta_dict.get("metadata_updates", {})
        if meta:
            session.metadata.update(meta)

        # Accumulate token usage
        usage_delta = delta_dict.get("token_usage_delta", {})
        if usage_delta:
            session.usage.prompt_tokens += usage_delta.get("prompt_tokens", 0)
            session.usage.completion_tokens += usage_delta.get("completion_tokens", 0)
            session.usage.total_tokens += usage_delta.get("prompt_tokens", 0) + usage_delta.get("completion_tokens", 0)
            session.usage.total_cost_usd += usage_delta.get("cost_usd", 0.0)
            session.usage.total_steps += 1
