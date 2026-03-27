"""Tests for Redis stores using fakeredis."""

import pytest
import fakeredis.aioredis

from src.store.redis.session_store import SessionRedisStore
from src.store.redis.checkpoint_store import CheckpointRedisStore
from src.store.redis.budget_store import BudgetRedisStore
from src.store.redis.cost_store import CostRedisStore
from src.store.redis.queue import TaskQueue
from src.store.redis.pubsub import EventPublisher


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def redis_bytes():
    """Redis without decode_responses for binary data."""
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


class TestSessionRedisStore:
    async def test_append_and_get_messages(self, redis) -> None:
        store = SessionRedisStore(redis)
        msg1 = {"role": "user", "content": "Hello"}
        msg2 = {"role": "assistant", "content": "Hi!"}

        await store.append_message("s1", msg1)
        await store.append_message("s1", msg2)

        messages = await store.get_all_messages("s1")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    async def test_append_messages_batch(self, redis) -> None:
        store = SessionRedisStore(redis)
        msgs = [
            {"role": "user", "content": "1"},
            {"role": "assistant", "content": "2"},
            {"role": "user", "content": "3"},
        ]
        await store.append_messages("s1", msgs)
        assert await store.get_message_count("s1") == 3

    async def test_get_recent_messages(self, redis) -> None:
        store = SessionRedisStore(redis)
        for i in range(5):
            await store.append_message("s1", {"role": "user", "content": str(i)})

        recent = await store.get_recent_messages("s1", 2)
        assert len(recent) == 2
        assert recent[0]["content"] == "3"
        assert recent[1]["content"] == "4"

    async def test_summary(self, redis) -> None:
        store = SessionRedisStore(redis)
        assert await store.get_summary("s1") is None

        await store.set_summary("s1", "User asked about weather")
        assert await store.get_summary("s1") == "User asked about weather"

    async def test_working_memory(self, redis) -> None:
        store = SessionRedisStore(redis)
        await store.set_working_field("s1", "plan", {"steps": ["a", "b"]})
        await store.set_working_field("s1", "scratchpad", "notes here")

        wm = await store.get_working_memory("s1")
        assert wm["plan"] == {"steps": ["a", "b"]}
        assert wm["scratchpad"] == "notes here"

    async def test_delete_session(self, redis) -> None:
        store = SessionRedisStore(redis)
        await store.append_message("s1", {"role": "user", "content": "hi"})
        await store.set_summary("s1", "summary")
        await store.delete_session("s1")

        assert await store.get_all_messages("s1") == []
        assert await store.get_summary("s1") is None


class TestCheckpointRedisStore:
    async def test_delta_append_and_get(self, redis_bytes) -> None:
        store = CheckpointRedisStore(redis_bytes)
        delta1 = {"session_id": "s1", "step_index": 1, "data": "step1"}
        delta2 = {"session_id": "s1", "step_index": 2, "data": "step2"}

        await store.append_delta("s1", delta1)
        await store.append_delta("s1", delta2)

        deltas = await store.get_deltas("s1")
        assert len(deltas) == 2
        assert deltas[0]["step_index"] == 1

    async def test_deltas_after(self, redis_bytes) -> None:
        store = CheckpointRedisStore(redis_bytes)
        for i in range(5):
            await store.append_delta("s1", {"step_index": i, "data": f"step{i}"})

        after = await store.get_deltas_after("s1", 2)
        assert len(after) == 2
        assert after[0]["step_index"] == 3

    async def test_snapshot(self, redis_bytes) -> None:
        store = CheckpointRedisStore(redis_bytes)
        snapshot_data = b"serialized_session_state"

        await store.save_snapshot("s1", snapshot_data)
        result = await store.get_snapshot("s1")
        assert result == snapshot_data

    async def test_clear_deltas(self, redis_bytes) -> None:
        store = CheckpointRedisStore(redis_bytes)
        await store.append_delta("s1", {"step_index": 1})
        await store.clear_deltas("s1")
        assert await store.get_deltas("s1") == []

    async def test_delete_all(self, redis_bytes) -> None:
        store = CheckpointRedisStore(redis_bytes)
        await store.append_delta("s1", {"step_index": 1})
        await store.save_snapshot("s1", b"snap")
        await store.delete_all("s1")
        assert await store.get_deltas("s1") == []
        assert await store.get_snapshot("s1") is None


class TestBudgetRedisStore:
    async def test_initialize_and_get(self, redis) -> None:
        store = BudgetRedisStore(redis)
        await store.initialize("s1")
        budget = await store.get("s1")
        assert budget["tokens"] == 0
        assert budget["cost"] == 0.0
        assert budget["steps"] == 0
        assert budget["elapsed_seconds"] >= 0

    async def test_increment(self, redis) -> None:
        store = BudgetRedisStore(redis)
        await store.initialize("s1")
        updated = await store.increment("s1", tokens=100, cost=0.01, steps=1)
        assert updated["tokens"] == 100
        assert updated["steps"] == 1
        assert updated["cost"] == pytest.approx(0.01, abs=0.001)

    async def test_multiple_increments(self, redis) -> None:
        store = BudgetRedisStore(redis)
        await store.initialize("s1")
        await store.increment("s1", tokens=100, steps=1)
        await store.increment("s1", tokens=200, steps=1)
        budget = await store.get("s1")
        assert budget["tokens"] == 300
        assert budget["steps"] == 2

    async def test_get_nonexistent(self, redis) -> None:
        store = BudgetRedisStore(redis)
        budget = await store.get("nonexistent")
        assert budget["tokens"] == 0


class TestCostRedisStore:
    async def test_track_and_get(self, redis) -> None:
        store = CostRedisStore(redis)
        await store.track(
            tenant_id="t1",
            agent_id="a1",
            session_id="s1",
            cost_usd=0.05,
            input_tokens=1000,
            output_tokens=500,
        )
        cost = await store.get_session_cost("s1")
        assert cost["cost_usd"] == pytest.approx(0.05, abs=0.001)
        assert cost["input_tokens"] == 1000
        assert cost["call_count"] == 1

    async def test_multiple_tracks(self, redis) -> None:
        store = CostRedisStore(redis)
        await store.track(tenant_id="t1", agent_id="a1", session_id="s1", cost_usd=0.01)
        await store.track(tenant_id="t1", agent_id="a1", session_id="s1", cost_usd=0.02)
        cost = await store.get_session_cost("s1")
        assert cost["cost_usd"] == pytest.approx(0.03, abs=0.001)
        assert cost["call_count"] == 2

    async def test_tenant_daily(self, redis) -> None:
        store = CostRedisStore(redis)
        await store.track(tenant_id="t1", agent_id="a1", session_id="s1", cost_usd=0.10)
        daily = await store.get_tenant_daily_cost("t1")
        assert daily == pytest.approx(0.10, abs=0.001)


class TestTaskQueue:
    async def test_enqueue(self, redis) -> None:
        queue = TaskQueue(redis)
        task = {"session_id": "s1", "agent_id": "a1"}
        entry_id = await queue.enqueue("t1", task)
        assert entry_id  # non-empty stream ID


class TestEventPublisher:
    async def test_publish(self, redis) -> None:
        pub = EventPublisher(redis)
        # Just verify no error — no subscribers in test
        count = await pub.publish("events:s1", '{"type":"test"}')
        assert count == 0  # no subscribers

    async def test_publish_session_event(self, redis) -> None:
        pub = EventPublisher(redis)
        await pub.publish_session_event("s1", '{"type":"test"}')
        # No error means success
