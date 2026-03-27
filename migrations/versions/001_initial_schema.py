"""001 initial schema

Create all Phase 1 tables with RLS policies and indexes.
See docs/architecture/01-data-models.md Section 10.

Revision ID: 001
Create Date: 2026-03-27
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- tenants ---
    op.execute("""
        CREATE TABLE tenants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            config JSONB NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'suspended', 'deleted')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # --- agents ---
    op.execute("""
        CREATE TABLE agents (
            tenant_id TEXT NOT NULL REFERENCES tenants(id),
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            system_prompt TEXT NOT NULL,
            model_config JSONB NOT NULL,
            execution_config JSONB NOT NULL,
            memory_config JSONB NOT NULL,
            guardrails_config JSONB NOT NULL,
            tools_config JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'active', 'archived')),
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, id)
        )
    """)
    op.execute("CREATE INDEX idx_agents_tenant_status ON agents (tenant_id, status)")

    # --- sessions ---
    op.execute("""
        CREATE TABLE sessions (
            tenant_id TEXT NOT NULL,
            id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'created'
                CHECK (state IN ('created', 'running', 'paused', 'waiting_input', 'completed', 'failed')),
            step_index INT NOT NULL DEFAULT 0,
            usage JSONB NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL,
            user_type TEXT NOT NULL DEFAULT 'builder'
                CHECK (user_type IN ('builder', 'end_user')),
            metadata_ JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            ttl_seconds INT NOT NULL DEFAULT 3600,
            PRIMARY KEY (tenant_id, id),
            FOREIGN KEY (tenant_id, agent_id) REFERENCES agents(tenant_id, id)
        )
    """)
    op.execute("CREATE INDEX idx_sessions_agent ON sessions (tenant_id, agent_id, state)")
    op.execute("CREATE INDEX idx_sessions_state ON sessions (tenant_id, state, created_at DESC)")
    op.execute("CREATE INDEX idx_sessions_created ON sessions (tenant_id, created_at DESC)")

    # --- messages ---
    op.execute("""
        CREATE TABLE messages (
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
            content TEXT NOT NULL,
            tool_call_id TEXT,
            tool_calls JSONB,
            tokens INT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, session_id, id),
            FOREIGN KEY (tenant_id, session_id) REFERENCES sessions(tenant_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX idx_messages_session ON messages (tenant_id, session_id, created_at)")

    # --- checkpoints_deltas ---
    op.execute("""
        CREATE TABLE checkpoints_deltas (
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            step_index INT NOT NULL,
            new_messages JSONB NOT NULL DEFAULT '[]',
            tool_results JSONB,
            metadata_updates JSONB NOT NULL DEFAULT '{}',
            usage_delta JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, session_id, step_index),
            FOREIGN KEY (tenant_id, session_id) REFERENCES sessions(tenant_id, id) ON DELETE CASCADE
        )
    """)

    # --- checkpoints_snapshots ---
    op.execute("""
        CREATE TABLE checkpoints_snapshots (
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            step_index INT NOT NULL,
            state BYTEA NOT NULL,
            conversation_hash TEXT NOT NULL,
            usage JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, session_id, step_index),
            FOREIGN KEY (tenant_id, session_id) REFERENCES sessions(tenant_id, id) ON DELETE CASCADE
        )
    """)

    # --- mcp_servers ---
    op.execute("""
        CREATE TABLE mcp_servers (
            tenant_id TEXT NOT NULL REFERENCES tenants(id),
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            transport TEXT NOT NULL CHECK (transport IN ('stdio', 'sse', 'streamable_http')),
            command TEXT,
            args JSONB,
            env_encrypted BYTEA,
            url TEXT,
            headers_encrypted BYTEA,
            connect_timeout_ms INT DEFAULT 10000,
            request_timeout_ms INT DEFAULT 30000,
            max_retries INT DEFAULT 3,
            auto_start BOOLEAN DEFAULT TRUE,
            health_check_interval_seconds INT DEFAULT 60,
            allowed_tools TEXT[],
            blocked_tools TEXT[],
            sandbox_level TEXT DEFAULT 'none',
            status TEXT DEFAULT 'disconnected',
            last_connected_at TIMESTAMPTZ,
            last_error TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (tenant_id, id)
        )
    """)

    # --- tools ---
    op.execute("""
        CREATE TABLE tools (
            tenant_id TEXT NOT NULL,
            id TEXT NOT NULL,
            server_id TEXT NOT NULL,
            name TEXT NOT NULL,
            namespace TEXT NOT NULL,
            description TEXT NOT NULL,
            input_schema JSONB NOT NULL,
            output_schema JSONB,
            execution_mode TEXT DEFAULT 'sync',
            default_timeout_ms INT DEFAULT 30000,
            estimated_latency_ms INT,
            estimated_cost FLOAT,
            idempotent BOOLEAN DEFAULT FALSE,
            permission_scope TEXT[] DEFAULT '{}',
            risk_level TEXT DEFAULT 'low',
            requires_approval BOOLEAN DEFAULT FALSE,
            visibility TEXT DEFAULT 'tenant',
            discovered_at TIMESTAMPTZ DEFAULT NOW(),
            last_verified_at TIMESTAMPTZ DEFAULT NOW(),
            status TEXT DEFAULT 'active',
            PRIMARY KEY (tenant_id, id),
            FOREIGN KEY (tenant_id, server_id) REFERENCES mcp_servers(tenant_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX idx_tools_namespace ON tools (tenant_id, namespace)")

    # --- audit_events ---
    op.execute("""
        CREATE TABLE audit_events (
            id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            tenant_id TEXT NOT NULL,
            agent_id TEXT,
            session_id TEXT,
            step_index INT,
            category TEXT NOT NULL,
            action TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            actor_ip INET,
            resource_type TEXT,
            resource_id TEXT,
            details JSONB NOT NULL DEFAULT '{}',
            sensitivity TEXT NOT NULL DEFAULT 'internal',
            outcome TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX idx_audit_tenant_time ON audit_events (tenant_id, timestamp DESC)")
    op.execute("CREATE INDEX idx_audit_session ON audit_events (session_id, timestamp)")
    op.execute("CREATE INDEX idx_audit_category ON audit_events (category, timestamp DESC)")

    # --- cost_events ---
    op.execute("""
        CREATE TABLE cost_events (
            id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            tenant_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            step_index INT NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN ('llm_call', 'tool_call', 'embedding')),
            provider TEXT,
            model TEXT,
            input_tokens INT,
            output_tokens INT,
            tool_name TEXT,
            cost_usd NUMERIC(10, 6) NOT NULL
        )
    """)
    op.execute("CREATE INDEX idx_cost_session ON cost_events (session_id, timestamp)")
    op.execute("CREATE INDEX idx_cost_tenant_time ON cost_events (tenant_id, timestamp DESC)")

    # --- cost_daily_aggregates ---
    op.execute("""
        CREATE TABLE cost_daily_aggregates (
            date DATE NOT NULL,
            tenant_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            total_cost_usd NUMERIC(12, 6),
            total_llm_calls INT,
            total_tool_calls INT,
            total_input_tokens BIGINT,
            total_output_tokens BIGINT,
            PRIMARY KEY (date, tenant_id, agent_id, provider, model)
        )
    """)

    # --- api_keys ---
    op.execute("""
        CREATE TABLE api_keys (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(id),
            key_hash TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            agent_ids TEXT[] NOT NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
            created_by TEXT NOT NULL,
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_used_at TIMESTAMPTZ
        )
    """)

    # --- RLS policies for tenant isolation ---
    for table in ["agents", "sessions", "messages", "checkpoints_deltas",
                   "checkpoints_snapshots", "mcp_servers", "tools",
                   "audit_events", "cost_events", "api_keys"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.current_tenant', true))
        """)


def downgrade() -> None:
    tables = [
        "cost_daily_aggregates", "cost_events", "audit_events", "api_keys",
        "tools", "mcp_servers", "checkpoints_snapshots", "checkpoints_deltas",
        "messages", "sessions", "agents", "tenants",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
