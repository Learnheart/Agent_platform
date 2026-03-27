"""Governance Service — implements GovernancePort protocol.

Orchestrates audit, cost tracking, and data classification.

See docs/architecture/09-governance.md.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.models import AuditEvent, CostEvent
from src.governance.audit_sink import AuditSink
from src.governance.cost_tracker import CostTracker
from src.governance.data_classifier import DataClassifier

logger = logging.getLogger(__name__)


class GovernanceService:
    """Implements the GovernancePort protocol.

    Provides:
    - Audit event recording (non-blocking, write-behind)
    - Cost tracking per session/agent/tenant
    - Data classification for PII/credentials
    """

    def __init__(
        self,
        audit_sink: AuditSink | None = None,
        cost_tracker: CostTracker | None = None,
        data_classifier: DataClassifier | None = None,
    ) -> None:
        self._audit = audit_sink or AuditSink()
        self._cost = cost_tracker or CostTracker()
        self._classifier = data_classifier or DataClassifier()

    # --- Audit ---

    async def record_audit(self, event: AuditEvent) -> None:
        """Record an audit event (non-blocking)."""
        await self._audit.record(event)

    async def query_audit(
        self,
        filters: dict[str, Any],
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Query audit trail (placeholder for PG query)."""
        return {"events": [], "total": 0, "limit": limit, "offset": offset}

    # --- Cost ---

    async def track_cost(self, event: CostEvent) -> None:
        """Track a cost event."""
        await self._cost.track(event)

    async def get_cost_report(
        self,
        scope: dict[str, str],
        time_range: tuple[str, str],
    ) -> dict[str, Any]:
        """Get cost report (placeholder)."""
        return {"scope": scope, "time_range": time_range, "total_cost_usd": 0.0}

    def get_session_cost(self, session_id: str) -> float:
        """Get current session cost."""
        return self._cost.get_session_cost(session_id)

    # --- Classification ---

    def classify(self, text: str) -> Any:
        """Classify text for sensitive data."""
        return self._classifier.classify(text)

    # --- Lifecycle ---

    async def start(self) -> None:
        """Start background tasks."""
        await self._audit.start()

    async def stop(self) -> None:
        """Stop and flush."""
        await self._audit.stop()
