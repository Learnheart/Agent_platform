"""Event Emitter — dual-path event emission.

Path 1: OpenTelemetry spans → Trace Store
Path 2: Redis Pub/Sub → WebSocket handler → Client

See docs/architecture/03-planning.md Section 2.9.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

from src.core.models import AgentEvent

logger = logging.getLogger(__name__)


@runtime_checkable
class PubSubPublisher(Protocol):
    """Minimal interface for Redis pub/sub publishing."""

    async def publish(self, channel: str, message: str) -> int:
        ...


class EventEmitter:
    """Emits agent events via OpenTelemetry + Redis pub/sub.

    Both paths are best-effort: emission failures are logged but never
    block execution.
    """

    def __init__(
        self,
        pubsub: PubSubPublisher | None = None,
        channel_prefix: str = "agent:events",
    ) -> None:
        self._pubsub = pubsub
        self._channel_prefix = channel_prefix

    async def emit(self, events: list[AgentEvent]) -> None:
        """Emit a batch of events through both paths."""
        for event in events:
            await self._emit_one(event)

    async def emit_one(self, event: AgentEvent) -> None:
        """Emit a single event."""
        await self._emit_one(event)

    async def _emit_one(self, event: AgentEvent) -> None:
        # Path 1: OpenTelemetry span attributes
        self._record_otel_span(event)

        # Path 2: Redis pub/sub
        await self._publish_redis(event)

    def _record_otel_span(self, event: AgentEvent) -> None:
        """Record event as OTel span attributes (best-effort)."""
        try:
            from opentelemetry import trace  # noqa: F811

            tracer = trace.get_tracer("agent-platform.engine")
            with tracer.start_as_current_span(f"event.{event.type.value}") as span:
                span.set_attribute("event.type", event.type.value)
                span.set_attribute("event.session_id", event.session_id)
                span.set_attribute("event.agent_id", event.agent_id)
                span.set_attribute("event.tenant_id", event.tenant_id)
                if event.step_index is not None:
                    span.set_attribute("event.step_index", event.step_index)
                for k, v in event.data.items():
                    if isinstance(v, (str, int, float, bool)):
                        span.set_attribute(f"event.data.{k}", v)
        except Exception:
            logger.debug("OTel span recording skipped (library not available or error)")

    async def _publish_redis(self, event: AgentEvent) -> None:
        """Publish event to Redis pub/sub channel (best-effort)."""
        if self._pubsub is None:
            return
        try:
            channel = f"{self._channel_prefix}:{event.session_id}"
            payload = self._serialize(event)
            await self._pubsub.publish(channel, payload)
        except Exception:
            logger.warning("Failed to publish event to Redis", exc_info=True)

    def _serialize(self, event: AgentEvent) -> str:
        """Serialize event to JSON string."""
        data: dict[str, Any] = {
            "id": event.id,
            "type": event.type.value,
            "session_id": event.session_id,
            "tenant_id": event.tenant_id,
            "agent_id": event.agent_id,
            "step_index": event.step_index,
            "timestamp": event.timestamp.isoformat(),
            "data": event.data,
        }
        return json.dumps(data, default=str)
