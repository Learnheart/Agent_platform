"""Tests for CheckpointManager — delta + snapshot checkpoint management."""

from unittest.mock import AsyncMock, MagicMock

import msgpack
import pytest

from src.core.enums import StepType
from src.core.models import Message, Session, SessionUsage, StepResult, StepUsage
from src.engine.checkpoint import CheckpointManager


def _make_session(**overrides) -> Session:
    defaults = dict(tenant_id="t1", agent_id="a1", step_index=1, ttl_seconds=3600)
    defaults.update(overrides)
    return Session(**defaults)


def _step_result(**overrides) -> StepResult:
    defaults = dict(
        type=StepType.TOOL_CALL,
        messages=[Message(role="assistant", content="thinking...", session_id="s1")],
        usage=StepUsage(prompt_tokens=100, completion_tokens=50, cost_usd=0.01),
        metadata_updates={"last_tool": "search"},
    )
    defaults.update(overrides)
    return StepResult(**defaults)


def _mock_redis_store() -> AsyncMock:
    store = AsyncMock()
    store.append_delta = AsyncMock()
    store.save_snapshot = AsyncMock()
    store.clear_deltas = AsyncMock()
    store.delete_all = AsyncMock()
    store.get_snapshot = AsyncMock(return_value=None)
    store.get_deltas = AsyncMock(return_value=[])
    store.get_deltas_after = AsyncMock(return_value=[])
    return store


# --- save_delta ---


class TestSaveDelta:
    @pytest.mark.asyncio
    async def test_appends_delta_to_redis(self):
        redis = _mock_redis_store()
        mgr = CheckpointManager(redis_store=redis)
        session = _make_session()

        await mgr.save_delta(session, _step_result())

        redis.append_delta.assert_called_once()
        call_args = redis.append_delta.call_args
        assert call_args[0][0] == session.id
        assert isinstance(call_args[0][1], dict)

    @pytest.mark.asyncio
    async def test_delta_contains_step_index(self):
        redis = _mock_redis_store()
        mgr = CheckpointManager(redis_store=redis)
        session = _make_session(step_index=5)

        await mgr.save_delta(session, _step_result())

        delta_dict = redis.append_delta.call_args[0][1]
        assert delta_dict["step_index"] == 5

    @pytest.mark.asyncio
    async def test_pg_write_attempted_when_available(self):
        redis = _mock_redis_store()
        pg = AsyncMock()
        pg.append_delta = AsyncMock()
        mgr = CheckpointManager(redis_store=redis, pg_repo=pg)

        await mgr.save_delta(_make_session(), _step_result())

        pg.append_delta.assert_called_once()

    @pytest.mark.asyncio
    async def test_pg_failure_does_not_raise(self):
        redis = _mock_redis_store()
        pg = AsyncMock()
        pg.append_delta = AsyncMock(side_effect=Exception("PG down"))
        mgr = CheckpointManager(redis_store=redis, pg_repo=pg)

        await mgr.save_delta(_make_session(), _step_result())  # no raise


# --- auto snapshot ---


class TestAutoSnapshot:
    @pytest.mark.asyncio
    async def test_triggers_snapshot_at_interval(self):
        redis = _mock_redis_store()
        mgr = CheckpointManager(redis_store=redis, snapshot_interval=5)
        session = _make_session(step_index=10)

        await mgr.save_delta(session, _step_result())

        redis.save_snapshot.assert_called_once()
        redis.clear_deltas.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_snapshot_at_non_interval(self):
        redis = _mock_redis_store()
        mgr = CheckpointManager(redis_store=redis, snapshot_interval=5)
        session = _make_session(step_index=3)

        await mgr.save_delta(session, _step_result())

        redis.save_snapshot.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_snapshot_at_step_zero(self):
        redis = _mock_redis_store()
        mgr = CheckpointManager(redis_store=redis, snapshot_interval=5)
        session = _make_session(step_index=0)

        await mgr.save_delta(session, _step_result())

        redis.save_snapshot.assert_not_called()


# --- save_snapshot ---


class TestSaveSnapshot:
    @pytest.mark.asyncio
    async def test_saves_to_redis(self):
        redis = _mock_redis_store()
        mgr = CheckpointManager(redis_store=redis)
        session = _make_session()

        await mgr.save_snapshot(session)

        redis.save_snapshot.assert_called_once()
        redis.clear_deltas.assert_called_once()

    @pytest.mark.asyncio
    async def test_snapshot_bytes_deserializable(self):
        redis = _mock_redis_store()
        mgr = CheckpointManager(redis_store=redis)
        session = _make_session()

        await mgr.save_snapshot(session)

        state_bytes = redis.save_snapshot.call_args[0][1]
        data = msgpack.unpackb(state_bytes, raw=False)
        assert data["tenant_id"] == "t1"


# --- restore ---


class TestRestore:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_checkpoint(self):
        redis = _mock_redis_store()
        mgr = CheckpointManager(redis_store=redis)

        result = await mgr.restore("nonexistent", "t1")
        assert result is None

    @pytest.mark.asyncio
    async def test_restores_from_redis_snapshot(self):
        redis = _mock_redis_store()
        mgr = CheckpointManager(redis_store=redis)
        session = _make_session()
        snapshot_bytes = msgpack.packb(session.model_dump(mode="json"), default=str)
        redis.get_snapshot = AsyncMock(return_value=snapshot_bytes)

        restored = await mgr.restore(session.id, "t1")

        assert restored is not None
        assert restored.tenant_id == "t1"
        assert restored.agent_id == "a1"

    @pytest.mark.asyncio
    async def test_replays_deltas_on_top_of_snapshot(self):
        redis = _mock_redis_store()
        mgr = CheckpointManager(redis_store=redis)
        session = _make_session(step_index=5, usage=SessionUsage(total_tokens=100, prompt_tokens=60, completion_tokens=40))
        snapshot_bytes = msgpack.packb(session.model_dump(mode="json"), default=str)
        redis.get_snapshot = AsyncMock(return_value=snapshot_bytes)
        redis.get_deltas_after = AsyncMock(return_value=[
            {
                "step_index": 6,
                "new_messages": [],
                "metadata_updates": {"extra": "data"},
                "token_usage_delta": {"prompt_tokens": 50, "completion_tokens": 20, "cost_usd": 0.01},
            }
        ])

        restored = await mgr.restore(session.id, "t1")

        assert restored.step_index == 6
        assert restored.metadata.get("extra") == "data"
        assert restored.usage.prompt_tokens == 110  # 60 + 50
        assert restored.usage.total_steps == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_pg_snapshot(self):
        redis = _mock_redis_store()
        pg = AsyncMock()
        session = _make_session()
        snapshot_bytes = msgpack.packb(session.model_dump(mode="json"), default=str)
        pg.get_latest_snapshot = AsyncMock(return_value={"state": snapshot_bytes})
        pg.get_deltas_after = AsyncMock(return_value=[])
        mgr = CheckpointManager(redis_store=redis, pg_repo=pg)

        restored = await mgr.restore(session.id, "t1")

        assert restored is not None
        pg.get_latest_snapshot.assert_called_once()


# --- cleanup ---


class TestCleanup:
    @pytest.mark.asyncio
    async def test_deletes_all_from_redis(self):
        redis = _mock_redis_store()
        mgr = CheckpointManager(redis_store=redis)

        await mgr.cleanup("sess-1")

        redis.delete_all.assert_called_once_with("sess-1")
