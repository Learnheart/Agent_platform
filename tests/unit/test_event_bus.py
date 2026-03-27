"""Tests for Event Bus — publishing, consumers, SSE."""

import asyncio

import pytest

from src.core.enums import AgentEventType
from src.core.models import AgentEvent
from src.events.bus import EventBus, EventConsumer, LogConsumer, SSEConsumer


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


class CollectorConsumer(EventConsumer):
    def __init__(self):
        self.events: list[AgentEvent] = []
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def on_event(self, event):
        self.events.append(event)


class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_to_consumer(self):
        bus = EventBus()
        consumer = CollectorConsumer()
        bus.register(consumer)
        await bus.publish(_event())
        assert len(consumer.events) == 1

    @pytest.mark.asyncio
    async def test_publish_many(self):
        bus = EventBus()
        consumer = CollectorConsumer()
        bus.register(consumer)
        await bus.publish_many([_event(step_index=0), _event(step_index=1)])
        assert len(consumer.events) == 2

    @pytest.mark.asyncio
    async def test_multiple_consumers(self):
        bus = EventBus()
        c1, c2 = CollectorConsumer(), CollectorConsumer()
        bus.register(c1)
        bus.register(c2)
        await bus.publish(_event())
        assert len(c1.events) == 1
        assert len(c2.events) == 1

    @pytest.mark.asyncio
    async def test_start_stop(self):
        bus = EventBus()
        consumer = CollectorConsumer()
        bus.register(consumer)
        await bus.start()
        assert consumer.started is True
        await bus.stop()
        assert consumer.stopped is True

    @pytest.mark.asyncio
    async def test_consumer_error_does_not_block(self):
        bus = EventBus()

        class FailingConsumer(EventConsumer):
            async def on_event(self, event):
                raise RuntimeError("boom")

        good = CollectorConsumer()
        bus.register(FailingConsumer())
        bus.register(good)
        await bus.publish(_event())
        assert len(good.events) == 1


class TestSSEConsumer:
    @pytest.mark.asyncio
    async def test_subscribe_and_receive(self):
        sse = SSEConsumer()
        queue = sse.subscribe("s1")
        await sse.on_event(_event(session_id="s1"))
        assert not queue.empty()
        event = await queue.get()
        assert event.session_id == "s1"

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        sse = SSEConsumer()
        sse.subscribe("s1")
        sse.unsubscribe("s1")
        await sse.on_event(_event(session_id="s1"))
        # No error, event just dropped

    @pytest.mark.asyncio
    async def test_different_sessions_isolated(self):
        sse = SSEConsumer()
        q1 = sse.subscribe("s1")
        q2 = sse.subscribe("s2")
        await sse.on_event(_event(session_id="s1"))
        assert not q1.empty()
        assert q2.empty()


class TestLogConsumer:
    @pytest.mark.asyncio
    async def test_no_error(self):
        consumer = LogConsumer()
        await consumer.on_event(_event())
