"""Tests for EventEmitter — dual-path event emission."""

import json
from unittest.mock import AsyncMock

import pytest

from src.core.enums import AgentEventType
from src.core.models import AgentEvent
from src.engine.event_emitter import EventEmitter


def _event(**overrides) -> AgentEvent:
    defaults = dict(
        type=AgentEventType.STEP_START,
        session_id="s1",
        tenant_id="t1",
        agent_id="a1",
        step_index=0,
        data={"pattern": "react"},
    )
    defaults.update(overrides)
    return AgentEvent(**defaults)


class TestEmitRedis:
    @pytest.mark.asyncio
    async def test_publishes_to_correct_channel(self):
        pubsub = AsyncMock()
        pubsub.publish = AsyncMock(return_value=1)
        emitter = EventEmitter(pubsub=pubsub, channel_prefix="agent:events")

        event = _event(session_id="sess-123")
        await emitter.emit([event])

        pubsub.publish.assert_called_once()
        channel = pubsub.publish.call_args[0][0]
        assert channel == "agent:events:sess-123"

    @pytest.mark.asyncio
    async def test_serializes_event_as_json(self):
        pubsub = AsyncMock()
        pubsub.publish = AsyncMock(return_value=1)
        emitter = EventEmitter(pubsub=pubsub)

        event = _event(data={"cost": 0.05})
        await emitter.emit([event])

        payload = pubsub.publish.call_args[0][1]
        parsed = json.loads(payload)
        assert parsed["type"] == "step_start"
        assert parsed["session_id"] == "s1"
        assert parsed["data"]["cost"] == 0.05

    @pytest.mark.asyncio
    async def test_multiple_events_published_individually(self):
        pubsub = AsyncMock()
        pubsub.publish = AsyncMock(return_value=1)
        emitter = EventEmitter(pubsub=pubsub)

        events = [_event(step_index=0), _event(step_index=1)]
        await emitter.emit(events)
        assert pubsub.publish.call_count == 2

    @pytest.mark.asyncio
    async def test_redis_failure_does_not_raise(self):
        pubsub = AsyncMock()
        pubsub.publish = AsyncMock(side_effect=ConnectionError("Redis down"))
        emitter = EventEmitter(pubsub=pubsub)

        # Should not raise
        await emitter.emit([_event()])

    @pytest.mark.asyncio
    async def test_no_pubsub_skips_redis(self):
        emitter = EventEmitter(pubsub=None)
        # Should not raise
        await emitter.emit([_event()])


class TestEmitOne:
    @pytest.mark.asyncio
    async def test_emit_one_publishes(self):
        pubsub = AsyncMock()
        pubsub.publish = AsyncMock(return_value=1)
        emitter = EventEmitter(pubsub=pubsub)

        await emitter.emit_one(_event())
        pubsub.publish.assert_called_once()


class TestSerialization:
    @pytest.mark.asyncio
    async def test_all_fields_present(self):
        pubsub = AsyncMock()
        pubsub.publish = AsyncMock(return_value=1)
        emitter = EventEmitter(pubsub=pubsub)

        event = _event(step_index=5, data={"model": "claude"})
        await emitter.emit([event])

        payload = json.loads(pubsub.publish.call_args[0][1])
        assert "id" in payload
        assert payload["step_index"] == 5
        assert payload["agent_id"] == "a1"
        assert payload["tenant_id"] == "t1"
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_none_step_index_serialized(self):
        pubsub = AsyncMock()
        pubsub.publish = AsyncMock(return_value=1)
        emitter = EventEmitter(pubsub=pubsub)

        event = _event(step_index=None)
        await emitter.emit([event])
        payload = json.loads(pubsub.publish.call_args[0][1])
        assert payload["step_index"] is None
