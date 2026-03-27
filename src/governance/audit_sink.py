"""Audit Sink — non-blocking write-behind buffer for audit events.

Buffers audit events in memory and flushes them to PostgreSQL
in batches for performance.

See docs/architecture/09-governance.md.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.core.models import AuditEvent

logger = logging.getLogger(__name__)


class AuditSink:
    """Write-behind buffer for audit events.

    Events are buffered in memory and flushed to the audit repository
    periodically or when the buffer reaches max size.
    """

    def __init__(
        self,
        audit_repo: Any | None = None,  # AuditRepository
        buffer_size: int = 1000,
        flush_interval_seconds: float = 0.5,
    ) -> None:
        self._repo = audit_repo
        self._buffer: list[AuditEvent] = []
        self._buffer_size = buffer_size
        self._flush_interval = flush_interval_seconds
        self._flush_task: asyncio.Task | None = None
        self._running = False

    async def record(self, event: AuditEvent) -> None:
        """Record an audit event (non-blocking)."""
        self._buffer.append(event)
        if len(self._buffer) >= self._buffer_size:
            await self._flush()

    async def start(self) -> None:
        """Start the periodic flush timer."""
        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def stop(self) -> None:
        """Stop the flush timer and flush remaining events."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush()

    async def _periodic_flush(self) -> None:
        """Periodically flush buffered events."""
        while self._running:
            await asyncio.sleep(self._flush_interval)
            if self._buffer:
                await self._flush()

    async def _flush(self) -> None:
        """Flush all buffered events to storage."""
        if not self._buffer:
            return

        events = list(self._buffer)
        self._buffer.clear()

        if self._repo is None:
            logger.debug("No audit repo configured, dropping %d events", len(events))
            return

        try:
            dicts = [e.model_dump(mode="json") for e in events]
            await self._repo.batch_insert(dicts)
        except Exception:
            logger.error("Failed to flush %d audit events", len(events), exc_info=True)
            # Re-add events to buffer for retry (up to limit)
            self._buffer.extend(events[:self._buffer_size])

    @property
    def pending_count(self) -> int:
        """Number of events waiting to be flushed."""
        return len(self._buffer)
