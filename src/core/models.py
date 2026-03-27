"""Core data models for the Agent Platform.

Canonical definitions from docs/architecture/01-data-models.md.
All models are Pydantic BaseModel with strict field definitions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.core.enums import (
    AgentEventType,
    DataSensitivity,
    ErrorCategory,
    SessionState,
    StepType,
)


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# Section 1: Core Entities
# ============================================================


class TenantConfig(BaseModel):
    """Per-tenant configuration limits."""

    max_agents: int = 50
    max_concurrent_sessions: int = 100
    max_mcp_servers: int = 20
    daily_budget_usd: float = 100.0
    default_model: str = "claude-sonnet-4-5-20250514"
    features: dict[str, bool] = Field(default_factory=dict)


class Tenant(BaseModel):
    """Tenant entity."""

    id: str = Field(default_factory=_uuid)
    name: str
    slug: str
    config: TenantConfig = Field(default_factory=TenantConfig)
    status: Literal["active", "suspended", "deleted"] = "active"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ModelConfig(BaseModel):
    """LLM model configuration for an agent."""

    provider: str = "anthropic"
    model: str = "claude-sonnet-4-5-20250514"
    temperature: float = 1.0
    max_tokens: int = 4096
    timeout_seconds: float = 120.0


class ExecutionConfig(BaseModel):
    """Execution engine configuration. See 03-planning Section 5."""

    pattern: Literal["react"] = "react"  # Phase 2: "plan_execute", "reflexion"
    max_steps: int = 30
    max_tokens_budget: int = 50000
    max_cost_usd: float = 5.0
    max_duration_seconds: int = 600
    budget_warning_threshold: float = 0.8
    budget_critical_threshold: float = 0.95
    checkpoint_enabled: bool = True
    checkpoint_interval: int = 1
    checkpoint_snapshot_interval: int = 10
    react_max_consecutive_tool_calls: int = 10
    max_retries_per_step: int = 2
    retry_backoff_seconds: float = 1.0
    max_context_tokens: int = 8000
    context_strategy: Literal["sliding_window", "summarize_recent", "selective", "token_trim"] = "summarize_recent"


class MemoryConfig(BaseModel):
    """Memory system configuration."""

    short_term_enabled: bool = True
    working_memory_enabled: bool = True
    long_term_enabled: bool = False  # Phase 2
    context_strategy: Literal["sliding_window", "summarize_recent", "selective", "token_trim"] = "summarize_recent"
    max_context_tokens: int = 8000
    summarize_threshold: float = 0.7


class GuardrailsConfig(BaseModel):
    """Guardrails configuration for an agent."""

    inbound_enabled: bool = True
    outbound_enabled: bool = True
    injection_detection_enabled: bool = True
    max_input_tokens: int = 4096
    tool_permissions: list[dict[str, Any]] = Field(default_factory=list)


class AgentToolsConfig(BaseModel):
    """Tool configuration for an agent."""

    mcp_server_ids: list[str] = Field(default_factory=list)
    tool_filters: list[str] | None = None
    max_tools_per_prompt: int = 20


class Agent(BaseModel):
    """Agent definition entity."""

    id: str = Field(default_factory=_uuid)
    tenant_id: str
    name: str
    description: str = ""
    system_prompt: str
    model_config_: ModelConfig = Field(default_factory=ModelConfig, alias="model_config")
    execution_config: ExecutionConfig = Field(default_factory=ExecutionConfig)
    memory_config: MemoryConfig = Field(default_factory=MemoryConfig)
    guardrails_config: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    tools_config: AgentToolsConfig = Field(default_factory=AgentToolsConfig)
    status: Literal["draft", "active", "archived"] = "draft"
    created_by: str = ""
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    model_config = {"populate_by_name": True}  # type: ignore[assignment]


class SessionUsage(BaseModel):
    """Cumulative usage statistics for a session."""

    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost_usd: float = 0.0
    total_steps: int = 0
    total_tool_calls: int = 0
    total_llm_calls: int = 0
    duration_seconds: float = 0.0


class Session(BaseModel):
    """Session entity — one conversation between a user and an agent."""

    id: str = Field(default_factory=_uuid)
    tenant_id: str
    agent_id: str
    state: SessionState = SessionState.CREATED
    step_index: int = 0
    usage: SessionUsage = Field(default_factory=SessionUsage)
    created_by: str = ""
    user_type: Literal["builder", "end_user"] = "builder"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None
    ttl_seconds: int = 3600


class Message(BaseModel):
    """A single message in a conversation."""

    id: str = Field(default_factory=_uuid)
    session_id: str = ""
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None
    tokens: int | None = None
    created_at: datetime = Field(default_factory=_now)


# ============================================================
# Section 2: Execution Models
# ============================================================


class ExecutionTrigger(BaseModel):
    """Describes why an execution task was created."""

    type: Literal["new_message", "resume", "approval_response", "retry"]
    message_id: str | None = None
    approval_id: str | None = None
    retry_step_index: int | None = None


class ExecutionTask(BaseModel):
    """Task enqueued to Redis Streams for executor workers."""

    id: str = Field(default_factory=_uuid)
    session_id: str
    agent_id: str
    tenant_id: str
    trigger: ExecutionTrigger
    created_at: datetime = Field(default_factory=_now)


class StepUsage(BaseModel):
    """Resource usage for a single execution step."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    llm_latency_ms: float = 0.0
    tool_latency_ms: float = 0.0


class StepResult(BaseModel):
    """Result returned after each step in the execution loop."""

    type: StepType
    messages: list[Message] = Field(default_factory=list)
    tool_calls: list[ToolCall] | None = None
    tool_results: list[ToolResult] | None = None
    metadata_updates: dict[str, Any] = Field(default_factory=dict)
    events: list[AgentEvent] = Field(default_factory=list)
    usage: StepUsage = Field(default_factory=StepUsage)
    answer: str | None = None
    error_message: str | None = None
    error_category: str | None = None
    retryable: bool = False
    approval_id: str | None = None


class ContextPayload(BaseModel):
    """Assembled context window for an LLM call."""

    system_prompt: str
    messages: list[Message]
    tool_schemas: list[dict[str, Any]] = Field(default_factory=list)
    total_tokens_estimate: int = 0
    has_summary: bool = False
    budget_warning: str | None = None


class BudgetCheck(BaseModel):
    """Single budget dimension check result."""

    type: Literal["tokens", "cost", "steps", "time"]
    current: float
    limit: float
    ratio: float


class BudgetCheckResult(BaseModel):
    """Aggregate budget check result."""

    exhausted: bool = False
    warning: bool = False
    critical: bool = False
    warning_message: str = ""
    checks: list[BudgetCheck] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    """Final result of executing an entire task."""

    session: Session


# ============================================================
# Section 3: Checkpoint Models
# ============================================================


class CheckpointDelta(BaseModel):
    """Incremental checkpoint after each step."""

    session_id: str
    step_index: int
    new_messages: list[Message] = Field(default_factory=list)
    tool_results: list[ToolResult] | None = None
    metadata_updates: dict[str, Any] = Field(default_factory=dict)
    token_usage_delta: StepUsage = Field(default_factory=StepUsage)
    timestamp: datetime = Field(default_factory=_now)


class CheckpointSnapshot(BaseModel):
    """Full session state snapshot."""

    session_id: str
    step_index: int
    state: bytes
    conversation_hash: str = ""
    usage: SessionUsage = Field(default_factory=SessionUsage)
    timestamp: datetime = Field(default_factory=_now)


# ============================================================
# Section 4: Tool Models
# ============================================================


class ToolCall(BaseModel):
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Result of a tool invocation."""

    tool_call_id: str
    tool_name: str
    content: str = ""
    is_error: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] | None = None
    cost_usd: float | None = None
    latency_ms: float = 0.0


# ============================================================
# Section 5: LLM Models
# ============================================================


class TokenUsage(BaseModel):
    """Token usage statistics from an LLM call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int | None = None
    cost_usd: float | None = None


class RetryPolicy(BaseModel):
    """Retry configuration for LLM/tool calls."""

    max_retries: int = 3
    backoff_base_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    backoff_max_seconds: float = 30.0
    retryable_status_codes: list[int] = Field(default_factory=lambda: [429, 500, 502, 503, 529])


class LLMConfig(BaseModel):
    """Per-call LLM configuration."""

    temperature: float = 1.0
    max_tokens: int = 4096
    timeout_seconds: float = 120.0
    retry_policy: RetryPolicy | None = None


class LLMResponse(BaseModel):
    """Response from an LLM call."""

    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model: str = ""
    provider: str = ""
    latency_ms: float = 0.0
    stop_reason: str = ""


class LLMStreamEvent(BaseModel):
    """A single event in a streaming LLM response."""

    type: Literal["text_delta", "tool_call_start", "tool_call_delta", "tool_call_end", "usage", "done", "error"]
    content: str | None = None
    tool_call: ToolCall | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments_delta: str | None = None
    usage: TokenUsage | None = None
    stop_reason: str | None = None
    error_message: str | None = None


# ============================================================
# Section 6: Event Model
# ============================================================


class AgentEvent(BaseModel):
    """Event emitted by the execution engine via Event Bus."""

    id: str = Field(default_factory=_uuid)
    type: AgentEventType
    session_id: str
    tenant_id: str
    agent_id: str
    step_index: int | None = None
    timestamp: datetime = Field(default_factory=_now)
    data: dict[str, Any] = Field(default_factory=dict)


# ============================================================
# Section 9: Governance Models
# ============================================================


class AuditActor(BaseModel):
    """Actor that triggered an audit event."""

    type: Literal["user", "agent", "system", "scheduler"]
    id: str
    ip_address: str | None = None


class AuditEvent(BaseModel):
    """Unified audit event model."""

    id: str = Field(default_factory=_uuid)
    timestamp: datetime = Field(default_factory=_now)
    tenant_id: str
    agent_id: str | None = None
    session_id: str | None = None
    step_index: int | None = None
    category: str  # AuditCategory value
    action: str
    actor: AuditActor
    resource_type: str | None = None
    resource_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    sensitivity: DataSensitivity = DataSensitivity.INTERNAL
    outcome: Literal["success", "failure", "blocked", "warning"] = "success"


class CostEvent(BaseModel):
    """Cost tracking event."""

    timestamp: datetime = Field(default_factory=_now)
    tenant_id: str
    agent_id: str
    session_id: str
    step_index: int = 0
    event_type: str = "llm_call"
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


# ============================================================
# Auth Models
# ============================================================


class AuthContext(BaseModel):
    """Authentication context attached to requests."""

    user_id: str
    tenant_id: str
    user_type: Literal["builder", "end_user"]
    roles: list[str] = Field(default_factory=list)
    allowed_agent_ids: list[str] | None = None


# Forward reference resolution
Message.model_rebuild()
StepResult.model_rebuild()
