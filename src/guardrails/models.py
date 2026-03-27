"""Data models for the Guardrails System.

See docs/architecture/07-guardrails.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# Check Results
# ============================================================


class Violation(BaseModel):
    """A single validation violation."""

    field: str = ""
    message: str = ""
    code: str = ""


class ValidationResult(BaseModel):
    """Result from SchemaValidator."""

    passed: bool = True
    violations: list[Violation] = Field(default_factory=list)
    latency_ms: float = 0.0


class DetectionResult(BaseModel):
    """Result from InjectionDetector."""

    is_injection: bool = False
    confidence: float = 0.0
    strategy_triggered: str = ""
    details: str = ""
    latency_ms: float = 0.0


class PermissionResult(BaseModel):
    """Result from ToolPermissionEnforcer."""

    status: Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"] = "ALLOW"
    reason: str = ""
    approver: str | None = None


class RateLimitResult(BaseModel):
    """Result from RateLimitEnforcer."""

    allowed: bool = True
    remaining_calls: int = 0
    reset_at: datetime | None = None


class GuardrailCheckResult(BaseModel):
    """Aggregate result from the full guardrails pipeline."""

    passed: bool = True
    blocked: bool = False
    requires_approval: bool = False
    reason: str = ""
    validation: ValidationResult | None = None
    injection: DetectionResult | None = None
    permission: PermissionResult | None = None
    rate_limit: RateLimitResult | None = None
    latency_ms: float = 0.0


# ============================================================
# Tool Permissions
# ============================================================


class PermissionConstraints(BaseModel):
    """Constraints on a tool permission."""

    max_calls_per_session: int | None = None
    max_calls_per_minute: int | None = None
    max_cost_per_call: float | None = None
    requires_approval: bool = False
    allowed_parameters: dict[str, Any] | None = None
    denied_parameters: dict[str, Any] | None = None


class ToolPermission(BaseModel):
    """Permission entry for a tool or tool pattern."""

    tool_pattern: str  # e.g., "mcp:database:*", "mcp:github:create_issue"
    actions: list[str] = Field(default_factory=lambda: ["invoke"])
    constraints: PermissionConstraints = Field(default_factory=PermissionConstraints)


# ============================================================
# Audit
# ============================================================


class GuardrailAuditEntry(BaseModel):
    """Audit trail entry for a guardrail check."""

    id: str = Field(default_factory=_uuid)
    timestamp: datetime = Field(default_factory=_now)
    session_id: str = ""
    tenant_id: str = ""
    agent_id: str = ""
    step_index: int = 0
    check_type: str = ""  # "schema_validation", "injection_detection", etc.
    check_name: str = ""
    result: str = ""  # "pass", "fail", "warn", "require_approval"
    details: dict[str, Any] = Field(default_factory=dict)
    action_taken: str = ""  # "allowed", "blocked", "escalated"
    latency_ms: float = 0.0
