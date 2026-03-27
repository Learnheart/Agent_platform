"""Event Bus — central hub for event publishing and consumption.

Manages publishers and consumer lifecycle. Events are published via
Redis Pub/Sub and consumed by registered consumers.

See docs/architecture/08-event-bus.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

from src.core.enums import AgentEventType
from src.core.models import AgentEvent

logger = logging.getLogger(__name__)


class EventBus:
    """Central event bus managing publishing and consumption.

    Events flow:
    1. Publisher emits AgentEvent
    2. Bus serializes and dispatches to all registered consumers
    3. Consumers process events independently (errors don't propagate)
    """

    def __init__(self) -> None:
        self._consumers: list[EventConsumer] = []
        self._running = False

    def register(self, consumer: EventConsumer) -> None:
        """Register an event consumer."""
        self._consumers.append(consumer)

    async def start(self) -> None:
        """Start all registered consumers."""
        self._running = True
        for consumer in self._consumers:
            try:
                await consumer.start()
            except Exception:
                logger.error("Failed to start consumer %s", type(consumer).__name__, exc_info=True)

    async def stop(self) -> None:
        """Stop all consumers gracefully."""
        self._running = False
        for consumer in self._consumers:
            try:
                await consumer.stop()
            except Exception:
                logger.error("Failed to stop consumer %s", type(consumer).__name__, exc_info=True)

    async def publish(self, event: AgentEvent) -> None:
        """Publish an event to all consumers (best-effort)."""
        for consumer in self._consumers:
            try:
                await consumer.on_event(event)
            except Exception:
                logger.warning(
                    "Consumer %s failed to process event %s",
                    type(consumer).__name__, event.type.value,
                    exc_info=True,
                )

    async def publish_many(self, events: list[AgentEvent]) -> None:
        """Publish multiple events."""
        for event in events:
            await self.publish(event)


class EventConsumer:
    """Base class for event consumers."""

    async def start(self) -> None:
        """Start the consumer."""

    async def stop(self) -> None:
        """Stop the consumer."""

    async def on_event(self, event: AgentEvent) -> None:
        """Process a single event."""


class SSEConsumer(EventConsumer):
    """Collects events for Server-Sent Events streaming.

    Events are buffered per-session for pickup by SSE endpoints.
    """

    def __init__(self, max_buffer_size: int = 1000) -> None:
        self._buffers: dict[str, asyncio.Queue[AgentEvent]] = {}
        self._max_buffer = max_buffer_size

    async def on_event(self, event: AgentEvent) -> None:
        queue = self._buffers.get(event.session_id)
        if queue is not None and not queue.full():
            await queue.put(event)

    def subscribe(self, session_id: str) -> asyncio.Queue[AgentEvent]:
        """Create a subscription queue for a session."""
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=self._max_buffer)
        self._buffers[session_id] = queue
        return queue

    def unsubscribe(self, session_id: str) -> None:
        """Remove a session subscription."""
        self._buffers.pop(session_id, None)


class TraceConsumer(EventConsumer):
    """Converts AgentEvents to OpenTelemetry spans (best-effort)."""

    async def on_event(self, event: AgentEvent) -> None:
        try:
            from opentelemetry import trace
            tracer = trace.get_tracer("agent-platform.events")
            with tracer.start_as_current_span(f"event.{event.type.value}") as span:
                span.set_attribute("event.session_id", event.session_id)
                span.set_attribute("event.type", event.type.value)
                for k, v in event.data.items():
                    if isinstance(v, (str, int, float, bool)):
                        span.set_attribute(f"event.{k}", v)
        except Exception:
            pass  # OTel not available


class LogConsumer(EventConsumer):
    """Logs all events for debugging/development."""

    async def on_event(self, event: AgentEvent) -> None:
        logger.info(
            "Event: type=%s session=%s step=%s",
            event.type.value, event.session_id, event.step_index,
        )
