"""Protocol interfaces (contracts) between layers.

These define the boundaries between components. Each protocol is implemented
by a concrete class in a different layer. See architecture docs 03-10.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.core.models import (
        AgentEvent,
        AuditEvent,
        BudgetCheckResult,
        ContextPayload,
        CostEvent,
        LLMConfig,
        LLMResponse,
        LLMStreamEvent,
        Message,
        Session,
        StepResult,
        TokenUsage,
        ToolCall,
        ToolResult,
    )


# ============================================================
# LLM Gateway — docs/architecture/04-llm-gateway.md Section 2.1
# ============================================================


@runtime_checkable
class LLMGateway(Protocol):
    """Abstraction layer for LLM providers."""

    async def chat(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        """Non-streaming LLM call."""
        ...

    async def chat_stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        config: LLMConfig | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Streaming LLM call. Yields events as they arrive."""
        ...

    async def count_tokens(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        """Estimate token count before calling LLM."""
        ...


# ============================================================
# Execution Engine — docs/architecture/03-planning.md Section 2.2
# ============================================================


@runtime_checkable
class ExecutionEngine(Protocol):
    """Internal engine abstraction (ReAct, Plan-Execute, etc.)."""

    async def step(
        self,
        session: Session,
        context: ContextPayload,
    ) -> StepResult:
        """Execute one reasoning step."""
        ...


# ============================================================
# Tool Runtime — docs/architecture/06-mcp-tools.md
# ============================================================


@runtime_checkable
class ToolRuntime(Protocol):
    """Runtime for executing tool calls via MCP."""

    async def invoke(
        self,
        tenant_id: str,
        session_id: str,
        tool_call: ToolCall,
    ) -> ToolResult:
        """Execute a single tool call."""
        ...


# ============================================================
# Event Consumer — docs/architecture/08-event-bus.md Section 2.4
# ============================================================


@runtime_checkable
class EventConsumer(Protocol):
    """Interface for event bus consumers."""

    async def start(self) -> None:
        """Start consuming events."""
        ...

    async def stop(self) -> None:
        """Graceful shutdown."""
        ...

    async def on_event(self, event: AgentEvent) -> None:
        """Handle a single event."""
        ...


# ============================================================
# Governance Port — docs/architecture/09-governance.md Section 3
# ============================================================


@runtime_checkable
class GovernancePort(Protocol):
    """Interface for data governance module."""

    # Audit
    async def record_audit(self, event: AuditEvent) -> None:
        """Record an audit event (non-blocking, write-behind)."""
        ...

    async def query_audit(
        self,
        filters: dict[str, Any],
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Query audit trail."""
        ...

    # Cost
    async def track_cost(self, event: CostEvent) -> None:
        """Track a cost event (non-blocking)."""
        ...

    async def get_cost_report(
        self,
        scope: dict[str, str],
        time_range: tuple[str, str],
    ) -> dict[str, Any]:
        """Get aggregated cost report."""
        ...

    # Lifecycle
    async def start(self) -> None:
        """Start background tasks (flush timer, retention scheduler)."""
        ...

    async def stop(self) -> None:
        """Stop background tasks and flush remaining data."""
        ...
