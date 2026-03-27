"""SQLAlchemy table definitions for all core tables.

See docs/architecture/01-data-models.md Section 10.
Uses SQLAlchemy Core (Table) for performance-critical paths.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB

metadata = MetaData()

# ============================================================
# 10.1 tenants
# ============================================================

tenants = Table(
    "tenants",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("slug", Text, nullable=False, unique=True),
    Column("config", JSONB, nullable=False, server_default="{}"),
    Column("status", Text, nullable=False, server_default="active"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# ============================================================
# 10.2 agents
# ============================================================

agents = Table(
    "agents",
    metadata,
    Column("tenant_id", Text, sa.ForeignKey("tenants.id"), nullable=False),
    Column("id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text, server_default=""),
    Column("system_prompt", Text, nullable=False),
    Column("model_config", JSONB, nullable=False),
    Column("execution_config", JSONB, nullable=False),
    Column("memory_config", JSONB, nullable=False),
    Column("guardrails_config", JSONB, nullable=False),
    Column("tools_config", JSONB, nullable=False),
    Column("status", Text, nullable=False, server_default="draft"),
    Column("created_by", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    sa.PrimaryKeyConstraint("tenant_id", "id"),
)

sa.Index("idx_agents_tenant_status", agents.c.tenant_id, agents.c.status)

# ============================================================
# 10.3 sessions
# ============================================================

sessions = Table(
    "sessions",
    metadata,
    Column("tenant_id", Text, nullable=False),
    Column("id", Text, nullable=False),
    Column("agent_id", Text, nullable=False),
    Column("state", Text, nullable=False, server_default="created"),
    Column("step_index", Integer, nullable=False, server_default="0"),
    Column("usage", JSONB, nullable=False, server_default="{}"),
    Column("created_by", Text, nullable=False),
    Column("user_type", Text, nullable=False, server_default="builder"),
    Column("metadata_", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("ttl_seconds", Integer, nullable=False, server_default="3600"),
    sa.PrimaryKeyConstraint("tenant_id", "id"),
    sa.ForeignKeyConstraint(["tenant_id", "agent_id"], ["agents.tenant_id", "agents.id"]),
)

sa.Index("idx_sessions_agent", sessions.c.tenant_id, sessions.c.agent_id, sessions.c.state)
sa.Index("idx_sessions_state", sessions.c.tenant_id, sessions.c.state, sessions.c.created_at.desc())
sa.Index("idx_sessions_created", sessions.c.tenant_id, sessions.c.created_at.desc())

# ============================================================
# 10.4 messages
# ============================================================

messages = Table(
    "messages",
    metadata,
    Column("tenant_id", Text, nullable=False),
    Column("session_id", Text, nullable=False),
    Column("id", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("tool_call_id", Text, nullable=True),
    Column("tool_calls", JSONB, nullable=True),
    Column("tokens", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    sa.PrimaryKeyConstraint("tenant_id", "session_id", "id"),
    sa.ForeignKeyConstraint(
        ["tenant_id", "session_id"],
        ["sessions.tenant_id", "sessions.id"],
        ondelete="CASCADE",
    ),
)

sa.Index("idx_messages_session", messages.c.tenant_id, messages.c.session_id, messages.c.created_at)

# ============================================================
# 10.5 checkpoints_deltas
# ============================================================

checkpoints_deltas = Table(
    "checkpoints_deltas",
    metadata,
    Column("tenant_id", Text, nullable=False),
    Column("session_id", Text, nullable=False),
    Column("step_index", Integer, nullable=False),
    Column("new_messages", JSONB, nullable=False, server_default="[]"),
    Column("tool_results", JSONB, nullable=True),
    Column("metadata_updates", JSONB, nullable=False, server_default="{}"),
    Column("usage_delta", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    sa.PrimaryKeyConstraint("tenant_id", "session_id", "step_index"),
    sa.ForeignKeyConstraint(
        ["tenant_id", "session_id"],
        ["sessions.tenant_id", "sessions.id"],
        ondelete="CASCADE",
    ),
)

# ============================================================
# 10.6 checkpoints_snapshots
# ============================================================

checkpoints_snapshots = Table(
    "checkpoints_snapshots",
    metadata,
    Column("tenant_id", Text, nullable=False),
    Column("session_id", Text, nullable=False),
    Column("step_index", Integer, nullable=False),
    Column("state", LargeBinary, nullable=False),
    Column("conversation_hash", Text, nullable=False),
    Column("usage", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    sa.PrimaryKeyConstraint("tenant_id", "session_id", "step_index"),
    sa.ForeignKeyConstraint(
        ["tenant_id", "session_id"],
        ["sessions.tenant_id", "sessions.id"],
        ondelete="CASCADE",
    ),
)

# ============================================================
# 10.8 mcp_servers (must come before tools due to FK)
# ============================================================

mcp_servers = Table(
    "mcp_servers",
    metadata,
    Column("tenant_id", Text, sa.ForeignKey("tenants.id"), nullable=False),
    Column("id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=True),
    Column("transport", Text, nullable=False),
    Column("command", Text, nullable=True),
    Column("args", JSONB, nullable=True),
    Column("env_encrypted", LargeBinary, nullable=True),
    Column("url", Text, nullable=True),
    Column("headers_encrypted", LargeBinary, nullable=True),
    Column("connect_timeout_ms", Integer, server_default="10000"),
    Column("request_timeout_ms", Integer, server_default="30000"),
    Column("max_retries", Integer, server_default="3"),
    Column("auto_start", Boolean, server_default="true"),
    Column("health_check_interval_seconds", Integer, server_default="60"),
    Column("allowed_tools", ARRAY(Text), nullable=True),
    Column("blocked_tools", ARRAY(Text), nullable=True),
    Column("sandbox_level", Text, server_default="none"),
    Column("status", Text, server_default="disconnected"),
    Column("last_connected_at", DateTime(timezone=True), nullable=True),
    Column("last_error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    sa.PrimaryKeyConstraint("tenant_id", "id"),
)

# ============================================================
# 10.7 tools
# ============================================================

tools = Table(
    "tools",
    metadata,
    Column("tenant_id", Text, nullable=False),
    Column("id", Text, nullable=False),
    Column("server_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("namespace", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("input_schema", JSONB, nullable=False),
    Column("output_schema", JSONB, nullable=True),
    Column("execution_mode", Text, server_default="sync"),
    Column("default_timeout_ms", Integer, server_default="30000"),
    Column("estimated_latency_ms", Integer, nullable=True),
    Column("estimated_cost", Float, nullable=True),
    Column("idempotent", Boolean, server_default="false"),
    Column("permission_scope", ARRAY(Text), server_default="{}"),
    Column("risk_level", Text, server_default="low"),
    Column("requires_approval", Boolean, server_default="false"),
    Column("visibility", Text, server_default="tenant"),
    Column("discovered_at", DateTime(timezone=True), server_default=func.now()),
    Column("last_verified_at", DateTime(timezone=True), server_default=func.now()),
    Column("status", Text, server_default="active"),
    sa.PrimaryKeyConstraint("tenant_id", "id"),
    sa.ForeignKeyConstraint(
        ["tenant_id", "server_id"],
        ["mcp_servers.tenant_id", "mcp_servers.id"],
        ondelete="CASCADE",
    ),
)

sa.Index("idx_tools_namespace", tools.c.tenant_id, tools.c.namespace)

# ============================================================
# 10.9 audit_events (append-only, partition-ready)
# ============================================================

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", Text, primary_key=True, server_default=func.gen_random_uuid().cast(Text)),
    Column("timestamp", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("tenant_id", Text, nullable=False),
    Column("agent_id", Text, nullable=True),
    Column("session_id", Text, nullable=True),
    Column("step_index", Integer, nullable=True),
    Column("category", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("actor_type", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("actor_ip", INET, nullable=True),
    Column("resource_type", Text, nullable=True),
    Column("resource_id", Text, nullable=True),
    Column("details", JSONB, nullable=False, server_default="{}"),
    Column("sensitivity", Text, nullable=False, server_default="internal"),
    Column("outcome", Text, nullable=False),
)

sa.Index("idx_audit_tenant_time", audit_events.c.tenant_id, audit_events.c.timestamp.desc())
sa.Index("idx_audit_session", audit_events.c.session_id, audit_events.c.timestamp)
sa.Index("idx_audit_category", audit_events.c.category, audit_events.c.timestamp.desc())

# ============================================================
# 10.10 cost_events
# ============================================================

cost_events = Table(
    "cost_events",
    metadata,
    Column("id", Text, primary_key=True, server_default=func.gen_random_uuid().cast(Text)),
    Column("timestamp", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("tenant_id", Text, nullable=False),
    Column("agent_id", Text, nullable=False),
    Column("session_id", Text, nullable=False),
    Column("step_index", Integer, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("provider", Text, nullable=True),
    Column("model", Text, nullable=True),
    Column("input_tokens", Integer, nullable=True),
    Column("output_tokens", Integer, nullable=True),
    Column("tool_name", Text, nullable=True),
    Column("cost_usd", Numeric(10, 6), nullable=False),
)

sa.Index("idx_cost_session", cost_events.c.session_id, cost_events.c.timestamp)
sa.Index("idx_cost_tenant_time", cost_events.c.tenant_id, cost_events.c.timestamp.desc())

# ============================================================
# 10.11 cost_daily_aggregates
# ============================================================

cost_daily_aggregates = Table(
    "cost_daily_aggregates",
    metadata,
    Column("date", sa.Date, nullable=False),
    Column("tenant_id", Text, nullable=False),
    Column("agent_id", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("total_cost_usd", Numeric(12, 6)),
    Column("total_llm_calls", Integer),
    Column("total_tool_calls", Integer),
    Column("total_input_tokens", sa.BigInteger),
    Column("total_output_tokens", sa.BigInteger),
    sa.PrimaryKeyConstraint("date", "tenant_id", "agent_id", "provider", "model"),
)

# ============================================================
# api_keys (from 10-api-contracts Section 2.3)
# ============================================================

api_keys = Table(
    "api_keys",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, sa.ForeignKey("tenants.id"), nullable=False),
    Column("key_hash", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("agent_ids", ARRAY(Text), nullable=False),
    Column("status", Text, nullable=False, server_default="active"),
    Column("created_by", Text, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_used_at", DateTime(timezone=True), nullable=True),
)
