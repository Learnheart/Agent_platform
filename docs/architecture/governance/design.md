# Thiết Kế Chi Tiết: Data Governance Module

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect
> **Parent:** [Architecture Overview](../00-overview.md)

---

## 1. Tổng Quan

### 1.1 Vấn Đề Cần Giải Quyết

Agent Platform tạo ra nhiều loại dữ liệu xuyên suốt lifecycle: conversation logs, tool call records, LLM responses, cost metrics, guardrail decisions, memory entries. Dữ liệu này hiện nằm rải rác ở nhiều components (Guardrails audit, Event Emitter traces, Memory lifecycle). Cần một module thống nhất để:

1. **Audit**: Consolidate mọi audit events vào một pipeline duy nhất, đảm bảo immutability và queryability
2. **Retention**: Enforce data lifecycle policies — khi nào giữ, khi nào xóa, khi nào archive
3. **Classification**: Gắn nhãn sensitivity cho data flowing through platform (PII, confidential, internal, public)
4. **Cost Accounting**: Aggregate cost data từ mọi session/agent/tenant thành reports
5. **Lineage** (Phase 2): Track data flow xuyên suốt execution chain — input nào dẫn đến output nào

### 1.2 Thiết Kế: Module, Không Phải Service

Governance được thiết kế như **internal module** trong Phase 1, với interface rõ ràng để tách thành service trong Phase 2 nếu cần.

**Lý do:**
- Phase 1 chưa có production data patterns → premature service extraction
- Module = zero network overhead, zero deployment complexity
- Interface-first design → swap implementation từ in-process sang network call khi cần

```
Phase 1 (Module):
  Executor ──function call──→ GovernanceModule ──→ PostgreSQL

Phase 2 (Service, nếu cần):
  Executor ──event bus──→ GovernanceService ──→ Dedicated DB
```

---

## 2. High-Level Diagram

```
┌──────────────────────────── DATA GOVERNANCE MODULE ──────────────────────────┐
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                        GOVERNANCE PORT (Interface)                      │ │
│  │                                                                         │ │
│  │  record_audit()  │  check_retention()  │  classify()  │  track_cost()  │ │
│  │                                                                         │ │
│  └───────────┬───────────────┬──────────────────┬──────────────┬───────────┘ │
│              │               │                  │              │             │
│    ┌─────────▼─────────┐   ┌▼──────────────┐  ┌▼────────────┐ │             │
│    │   AUDIT SINK      │   │  RETENTION    │  │  DATA       │ │             │
│    │                   │   │  ENGINE       │  │  CLASSIFIER │ │             │
│    │ ┌───────────────┐ │   │               │  │             │ │             │
│    │ │ Event         │ │   │ ┌───────────┐ │  │ ┌─────────┐ │ │             │
│    │ │ Normalizer    │ │   │ │ Policy    │ │  │ │ Rules   │ │ │             │
│    │ ├───────────────┤ │   │ │ Evaluator │ │  │ │ Engine  │ │ │             │
│    │ │ Write-Behind  │ │   │ ├───────────┤ │  │ ├─────────┤ │ │             │
│    │ │ Buffer        │ │   │ │ Cleanup   │ │  │ │ Tag     │ │ │             │
│    │ ├───────────────┤ │   │ │ Scheduler │ │  │ │ Manager │ │ │             │
│    │ │ Batch Writer  │ │   │ └───────────┘ │  │ └─────────┘ │ │             │
│    │ └───────────────┘ │   │               │  │             │ │             │
│    │                   │   │  Scope:        │  │  Scope:     │ │             │
│    │  Scope: Per-event │   │  Background    │  │  Per-event  │ │             │
│    │  Store: PostgreSQL│   │  job (cron)    │  │  In-memory  │ │             │
│    │  (append-only)    │   │  Store: PG     │  │  rules      │ │             │
│    └───────────────────┘   └───────────────┘  └─────────────┘ │             │
│                                                                │             │
│    ┌───────────────────┐   ┌───────────────────────────────┐  │             │
│    │   COST            │   │   DATA LINEAGE                │  │             │
│    │   AGGREGATOR      │   │   (Phase 2)                   │  │             │
│    │                   │   │                               │  │             │
│    │ ┌───────────────┐ │   │ ┌───────────────────────────┐ │  │             │
│    │ │ Per-session   │ │   │ │ Lineage Graph Builder     │ │  │             │
│    │ │ accumulator   │ │   │ │ (from OTel trace spans)   │ │  │             │
│    │ ├───────────────┤ │   │ ├───────────────────────────┤ │  │             │
│    │ │ Per-agent     │ │   │ │ Lineage Query Engine      │ │  │             │
│    │ │ rollup        │ │   │ │ "What produced this?"     │ │  │             │
│    │ ├───────────────┤ │   │ └───────────────────────────┘ │  │             │
│    │ │ Per-tenant    │ │   │                               │  │             │
│    │ │ rollup        │ │   │  Scope: Cross-session         │  │             │
│    │ └───────────────┘ │   │  Store: PG (graph model)      │  │             │
│    │                   │   │  Build from: OTel traces       │  │             │
│    │  Scope: Per-event │   └───────────────────────────────┘  │             │
│    │  + background job │                                      │             │
│    │  Store: Redis     │                                      │             │
│    │  (counters) + PG  │                                      │             │
│    │  (aggregates)     │                                      │             │
│    └───────────────────┘                                      │             │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Governance Port (Interface)

Interface duy nhất mà các component khác sử dụng để tương tác với Governance module. Thiết kế theo Dependency Inversion — consumer phụ thuộc vào interface, không phải implementation.

```python
class GovernancePort(Protocol):
    """
    Primary interface for the Data Governance module.
    All components interact with governance through this port.

    Phase 1: LocalGovernance (in-process, direct DB access)
    Phase 2: RemoteGovernance (HTTP/gRPC client to Governance Service)
    """

    # ── Audit ──
    async def record_audit(self, event: AuditEvent) -> None:
        """
        Record an audit event. Non-blocking (write-behind buffer).
        Called by: Executor, Guardrails, Session Manager, Tool Manager, Memory Manager.
        """

    async def query_audit(
        self,
        filters: AuditFilters,
        limit: int = 100,
        offset: int = 0,
    ) -> AuditQueryResult:
        """Query audit trail. Called by: Admin API, compliance tools."""

    # ── Retention ──
    async def check_retention(self, data_ref: DataRef) -> RetentionDecision:
        """
        Check if a data item should be kept, archived, or deleted.
        Called by: cleanup jobs, memory lifecycle.
        """

    async def enforce_retention(self, scope: RetentionScope) -> RetentionReport:
        """
        Run retention enforcement for a scope (tenant/agent/global).
        Called by: scheduled background job.
        """

    # ── Classification ──
    async def classify(self, content: str, context: ClassificationContext) -> DataClassification:
        """
        Classify data sensitivity. Lightweight, in-process.
        Called by: Audit Sink (tag events), Memory Manager (tag memories).
        """

    # ── Cost ──
    async def track_cost(self, event: CostEvent) -> None:
        """
        Track a cost event. Non-blocking.
        Called by: LLM Gateway (per-call), Tool Runtime (per-call).
        """

    async def get_cost_report(
        self,
        scope: CostScope,
        time_range: tuple[datetime, datetime],
    ) -> CostReport:
        """Get aggregated cost report. Called by: Admin API, Budget Controller."""

    # ── Lineage (Phase 2) ──
    async def record_lineage(self, edge: LineageEdge) -> None:
        """Record a data lineage edge. Called by: Event Bus consumer."""

    async def query_lineage(
        self,
        data_ref: DataRef,
        direction: Literal["upstream", "downstream"],
        depth: int = 3,
    ) -> LineageGraph:
        """
        Trace data lineage upstream (what produced this?) or
        downstream (what did this produce?).
        """
```

---

## 4. Component Descriptions

### 4.1 Audit Sink

Consolidate mọi audit events từ toàn bộ platform vào một pipeline duy nhất.

**Vấn đề hiện tại:** Guardrails có `GuardrailAuditEntry`, Event Emitter có trace events, Session Manager có lifecycle events — 3 nguồn audit riêng biệt. Governance module thống nhất chúng.

#### 4.1.1 Audit Event Model

```python
@dataclass
class AuditEvent:
    """Unified audit event model for all platform actions."""

    # Identity
    id: str                              # UUID, generated by module
    timestamp: datetime                  # Event time (UTC)

    # Scope
    tenant_id: str
    agent_id: str | None
    session_id: str | None
    step_index: int | None

    # Event
    category: AuditCategory              # Enum: see below
    action: str                          # Specific action within category
    actor: AuditActor                    # Who/what triggered this

    # Details
    resource_type: str | None            # "agent", "session", "tool", "memory", etc.
    resource_id: str | None              # ID of affected resource
    details: dict                        # Category-specific details

    # Classification
    sensitivity: DataSensitivity         # "public", "internal", "confidential", "restricted"

    # Result
    outcome: Literal["success", "failure", "blocked", "warning"]

class AuditCategory(str, Enum):
    # Agent lifecycle
    AGENT_MANAGEMENT = "agent_management"         # create, update, delete agent

    # Session lifecycle
    SESSION_LIFECYCLE = "session_lifecycle"        # create, start, pause, resume, complete, fail

    # Execution
    LLM_CALL = "llm_call"                         # every LLM API call
    TOOL_CALL = "tool_call"                        # every tool invocation

    # Security
    GUARDRAIL_CHECK = "guardrail_check"           # inbound/outbound/policy checks
    AUTH_EVENT = "auth_event"                      # login, token refresh, permission denied

    # Data
    MEMORY_ACCESS = "memory_access"               # store, search, delete memory
    DATA_EXPORT = "data_export"                    # data exported from platform

    # Administration
    CONFIG_CHANGE = "config_change"               # agent config, guardrail rules, retention policies
    RETENTION_ACTION = "retention_action"          # data archived or deleted by retention policy

class AuditActor:
    type: Literal["user", "agent", "system", "scheduler"]
    id: str                               # user_id, agent_id, "system", "retention_scheduler"
    ip_address: str | None                # For user actions
```

#### 4.1.2 Write-Behind Buffer

Audit writes không block execution path. Events được buffered rồi batch-write.

```python
class AuditSink:
    """
    Non-blocking audit event writer.
    Uses write-behind buffer to avoid adding latency to execution path.
    """

    def __init__(
        self,
        buffer_size: int = 1000,           # Max events before forced flush
        flush_interval_ms: int = 500,      # Auto-flush every 500ms
        classifier: DataClassifier | None = None,
    ): ...

    async def record(self, event: AuditEvent) -> None:
        """
        1. Classify event sensitivity (if classifier enabled)
        2. Normalize event (ensure required fields, sanitize details)
        3. Add to in-memory buffer
        4. If buffer full or flush interval reached → batch write

        Guarantee: events are durably written within flush_interval_ms.
        If process crashes before flush → events in buffer are lost.
        For critical events (auth, guardrail_block), use sync_record() instead.
        """

    async def sync_record(self, event: AuditEvent) -> None:
        """
        Synchronous write for critical events.
        Bypasses buffer, writes directly to PostgreSQL.
        Use sparingly — adds ~5ms latency.
        """

    async def flush(self) -> int:
        """Flush buffer to PostgreSQL. Returns number of events written."""

    async def _batch_write(self, events: list[AuditEvent]) -> None:
        """
        Batch INSERT into audit_events table.
        Uses COPY for high-throughput (>1000 events/batch).
        Fallback to INSERT ... VALUES for smaller batches.
        """
```

#### 4.1.3 Audit Storage

```sql
CREATE TABLE audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Scope
    tenant_id TEXT NOT NULL,
    agent_id TEXT,
    session_id TEXT,
    step_index INT,

    -- Event
    category TEXT NOT NULL,
    action TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_ip INET,

    -- Resource
    resource_type TEXT,
    resource_id TEXT,
    details JSONB NOT NULL DEFAULT '{}',

    -- Classification
    sensitivity TEXT NOT NULL DEFAULT 'internal',

    -- Result
    outcome TEXT NOT NULL,

    -- Partitioning support
    created_date DATE GENERATED ALWAYS AS (DATE(timestamp)) STORED
);

-- Partition by month for efficient retention and queries
-- (actual partitioning setup in migration scripts)

-- Indexes for common query patterns
CREATE INDEX idx_audit_tenant_time ON audit_events (tenant_id, timestamp DESC);
CREATE INDEX idx_audit_session ON audit_events (session_id, timestamp) WHERE session_id IS NOT NULL;
CREATE INDEX idx_audit_category ON audit_events (category, timestamp DESC);
CREATE INDEX idx_audit_outcome ON audit_events (outcome, timestamp DESC) WHERE outcome != 'success';

-- Prevent modification (append-only enforcement)
CREATE OR REPLACE FUNCTION prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_events table is append-only: UPDATE and DELETE are not permitted';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_immutable
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();

-- Row-level security
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON audit_events
    USING (tenant_id = current_setting('app.current_tenant'));
```

#### 4.1.4 Audit Query

```python
@dataclass
class AuditFilters:
    tenant_id: str                        # Required
    session_id: str | None = None
    agent_id: str | None = None
    categories: list[AuditCategory] | None = None
    outcomes: list[str] | None = None     # ["failure", "blocked"]
    time_range: tuple[datetime, datetime] | None = None
    actor_id: str | None = None
    resource_type: str | None = None
    sensitivity_min: DataSensitivity | None = None  # "confidential" = confidential + restricted

class AuditQueryEngine:
    async def query(
        self,
        filters: AuditFilters,
        limit: int = 100,
        offset: int = 0,
        order: Literal["asc", "desc"] = "desc",
    ) -> AuditQueryResult:
        """
        Query audit trail with filters.
        Returns paginated results with total count.

        Common queries:
        - "All failed guardrail checks for agent X in last 24h"
        - "All tool calls in session Y"
        - "All config changes by user Z"
        - "All data export events with sensitivity >= confidential"
        """

    async def get_session_timeline(self, session_id: str) -> list[AuditEvent]:
        """
        Complete audit timeline for a session — ordered chronologically.
        Includes: lifecycle events, LLM calls, tool calls, guardrail checks.
        Used for debugging and compliance review.
        """
```

---

### 4.2 Retention Engine

Enforce data lifecycle policies — tự động archive hoặc delete data theo rules.

#### 4.2.1 Retention Policy Model

```python
@dataclass
class RetentionPolicy:
    """Defines how long data should be kept and what happens after."""

    id: str
    tenant_id: str                        # "platform" for global policies
    name: str
    description: str

    # Scope
    data_type: RetentionDataType          # What type of data this applies to
    scope: RetentionScope                 # tenant-wide, per-agent, per-sensitivity

    # Rules
    retain_days: int                      # Keep for N days
    archive_before_delete: bool = True    # Move to cold storage before deletion
    archive_storage: str = "s3"           # "s3", "gcs", "none"

    # Conditions
    applies_to_sensitivity: list[DataSensitivity] | None = None  # Only apply to certain classifications

    # Status
    enabled: bool = True
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None

class RetentionDataType(str, Enum):
    SESSION_DATA = "session_data"          # Conversation history, checkpoints
    AUDIT_EVENTS = "audit_events"          # Audit trail records
    TRACE_SPANS = "trace_spans"            # OpenTelemetry traces
    LONG_TERM_MEMORY = "long_term_memory"  # Agent memories (pgvector)
    COST_RECORDS = "cost_records"          # Cost aggregation data
    TOOL_LOGS = "tool_logs"               # Tool invocation logs
```

#### 4.2.2 Default Retention Policies (Platform)

| Data Type | Default Retention | Archive | Rationale |
|---|---|---|---|
| Session data (hot, Redis) | Session + 1h | No (ephemeral) | Cleanup after session ends |
| Session data (warm, PG) | 90 days | Yes (S3) | Replay, debug, compliance |
| Audit events | 365 days | Yes (S3) | Compliance requirement |
| Trace spans | 30 days | No | Debugging, recent only |
| Long-term memories | Per-agent config | Yes (S3) | Agent-managed lifecycle |
| Cost records | Indefinite | No | Billing, analytics |
| Tool invocation logs | 30 days | No | Debugging |

#### 4.2.3 Retention Scheduler

```python
class RetentionScheduler:
    """
    Background job that runs retention policies on a schedule.
    Default: daily at 02:00 UTC.
    """

    async def run(self) -> RetentionReport:
        """
        1. Load all enabled retention policies
        2. For each policy:
           a. Query data matching policy scope + age
           b. If archive_before_delete: export to cold storage
           c. Delete expired data
           d. Update policy.last_run_at
        3. Record audit event (RETENTION_ACTION)
        4. Return report with counts
        """

    async def run_for_tenant(self, tenant_id: str) -> RetentionReport:
        """Run retention for a specific tenant (admin-triggered)."""

    async def dry_run(self, policy_id: str) -> RetentionReport:
        """Preview what would be affected without actually deleting."""
```

**Retention report:**

```python
@dataclass
class RetentionReport:
    policy_id: str
    run_at: datetime
    records_scanned: int
    records_archived: int
    records_deleted: int
    storage_freed_bytes: int
    errors: list[str]
    duration_seconds: float
```

---

### 4.3 Data Classifier

Gắn nhãn sensitivity cho data flowing through platform. Rule-based trong Phase 1, ML-based trong Phase 2.

#### 4.3.1 Classification Model

```python
class DataSensitivity(str, Enum):
    PUBLIC = "public"                # Có thể expose ra ngoài
    INTERNAL = "internal"            # Chỉ nội bộ platform
    CONFIDENTIAL = "confidential"    # Chứa business-sensitive data
    RESTRICTED = "restricted"        # Chứa PII, credentials, hoặc regulated data

@dataclass
class DataClassification:
    sensitivity: DataSensitivity
    tags: list[str]                  # ["pii", "credential", "financial", "health"]
    confidence: float                # 0.0 - 1.0
    classified_by: str               # "rule:email_pattern", "rule:api_key_pattern"

@dataclass
class ClassificationContext:
    data_type: str                   # "user_message", "llm_response", "tool_result", "memory"
    tenant_id: str
    agent_id: str | None
```

#### 4.3.2 Classification Rules (Phase 1)

```python
class DataClassifier:
    """
    Rule-based data classifier. Fast, deterministic, no external dependencies.
    Phase 2: add ML classifier for nuanced content classification.
    """

    def __init__(self, rules: list[ClassificationRule]):
        self.rules = rules

    async def classify(
        self,
        content: str,
        context: ClassificationContext,
    ) -> DataClassification:
        """
        Apply rules in priority order. Highest sensitivity wins.

        Default rules (built-in):
        1. RESTRICTED if matches: email, phone, SSN, credit card patterns
        2. RESTRICTED if matches: API key patterns (sk-*, AKIA*, etc.)
        3. CONFIDENTIAL if matches: financial amounts, account numbers
        4. CONFIDENTIAL if context.data_type == "tool_result" and tool is DB/API
        5. INTERNAL otherwise

        Tenant can add custom rules via config.
        """

    async def classify_batch(
        self,
        items: list[tuple[str, ClassificationContext]],
    ) -> list[DataClassification]:
        """Batch classification for efficiency."""
```

**Rule definition:**

```python
@dataclass
class ClassificationRule:
    id: str
    name: str
    priority: int                         # Lower = evaluated first
    pattern: str | None                   # Regex pattern to match in content
    context_match: dict | None            # Match on context fields
    sensitivity: DataSensitivity          # Classification if rule matches
    tags: list[str]                       # Tags to add
    enabled: bool = True
```

---

### 4.4 Cost Aggregator

Track và aggregate costs từ LLM calls và tool executions.

```python
class CostAggregator:
    """
    Accumulates cost events and provides aggregated reports.
    Real-time tracking via Redis counters, durable storage in PostgreSQL.
    """

    async def track(self, event: CostEvent) -> None:
        """
        1. Increment Redis counters (atomic, fast):
           - session:{id}:cost (total session cost)
           - agent:{id}:cost:{date} (daily agent cost)
           - tenant:{id}:cost:{date} (daily tenant cost)
        2. Append to cost_events buffer (batch write to PG)
        """

    async def get_session_cost(self, session_id: str) -> SessionCost:
        """Real-time session cost from Redis."""

    async def get_report(
        self,
        scope: CostScope,
        time_range: tuple[datetime, datetime],
        group_by: Literal["day", "week", "month"] = "day",
    ) -> CostReport:
        """
        Aggregated cost report from PostgreSQL.
        Supports breakdown by: model, tool, agent, tenant.
        """

@dataclass
class CostEvent:
    timestamp: datetime
    tenant_id: str
    agent_id: str
    session_id: str
    step_index: int

    event_type: Literal["llm_call", "tool_call", "embedding"]

    # LLM-specific
    provider: str | None              # "anthropic", "openai"
    model: str | None                 # "claude-sonnet-4-5-20250514"
    input_tokens: int | None
    output_tokens: int | None

    # Tool-specific
    tool_name: str | None

    # Cost
    cost_usd: float                   # Calculated cost

@dataclass
class CostReport:
    scope: CostScope
    time_range: tuple[datetime, datetime]
    total_cost_usd: float
    total_llm_calls: int
    total_tool_calls: int
    total_tokens: int
    breakdown: list[CostBreakdownItem]   # By model, tool, agent, etc.
```

**Cost storage:**

```sql
CREATE TABLE cost_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tenant_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    step_index INT NOT NULL,

    event_type TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    input_tokens INT,
    output_tokens INT,
    tool_name TEXT,

    cost_usd NUMERIC(10, 6) NOT NULL
);

-- Daily aggregation table (materialized by background job)
CREATE TABLE cost_daily_aggregates (
    date DATE NOT NULL,
    tenant_id TEXT NOT NULL,
    agent_id TEXT,
    provider TEXT,
    model TEXT,

    total_cost_usd NUMERIC(12, 6),
    total_llm_calls INT,
    total_tool_calls INT,
    total_input_tokens BIGINT,
    total_output_tokens BIGINT,

    PRIMARY KEY (date, tenant_id, agent_id, provider, model)
);
```

---

### 4.5 Data Lineage (Phase 2)

Track data flow xuyên suốt execution — input nào dẫn đến output nào.

> **Phase note:** Data lineage cho Agent systems chưa có industry-standard patterns. Phase 1 thu thập đủ raw data (OTel traces, audit events) để build lineage graph trong Phase 2 khi đã hiểu rõ production patterns.

#### 4.5.1 Lineage Model

```python
@dataclass
class LineageNode:
    """A data artifact in the lineage graph."""
    id: str
    type: Literal[
        "user_input",       # User message
        "llm_output",       # LLM response
        "tool_input",       # Parameters sent to tool
        "tool_output",      # Result from tool
        "memory_entry",     # Stored/retrieved memory
        "agent_output",     # Final answer to user
    ]
    session_id: str
    step_index: int
    content_hash: str        # Hash of content (not content itself, for privacy)
    sensitivity: DataSensitivity
    timestamp: datetime

@dataclass
class LineageEdge:
    """A transformation or dependency between data artifacts."""
    source_id: str           # LineageNode that produced/influenced
    target_id: str           # LineageNode that was produced/influenced
    relationship: Literal[
        "produced_by",       # LLM output produced by LLM call with this input
        "derived_from",      # Tool output derived from tool input
        "informed_by",       # LLM call informed by memory retrieval
        "summarized_from",   # Summary derived from conversation history
        "approved_by",       # Action approved by HITL
    ]
    session_id: str
    step_index: int
    metadata: dict           # Transformation details

@dataclass
class LineageGraph:
    """Subgraph of lineage for a query result."""
    nodes: list[LineageNode]
    edges: list[LineageEdge]
    root: str                # Starting node ID
    depth: int               # How many hops from root
```

#### 4.5.2 Lineage Builder (Phase 2)

```python
class LineageBuilder:
    """
    Builds lineage graph from OTel traces and audit events.
    Runs as background consumer of Event Bus.
    """

    async def process_step_events(
        self,
        session_id: str,
        step_index: int,
        events: list[AgentEvent],
    ) -> list[LineageEdge]:
        """
        From a completed step's events, extract lineage edges:

        1. user_input → (informed) → llm_output
        2. memory_entry → (informed_by) → llm_output (if RAG was used)
        3. llm_output → (produced) → tool_input (if tool_call)
        4. tool_input → (derived_from) → tool_output
        5. tool_output → (informed) → next llm_output
        6. llm_output → (produced) → agent_output (if final_answer)
        """

    async def query_upstream(
        self,
        node_id: str,
        depth: int = 3,
    ) -> LineageGraph:
        """What data produced this node? Walk backwards through graph."""

    async def query_downstream(
        self,
        node_id: str,
        depth: int = 3,
    ) -> LineageGraph:
        """What was produced from this node? Walk forwards through graph."""
```

---

## 5. Integration: How Governance Connects to Other Components

### 5.1 Integration Points

```
┌──────────────┐
│  Executor    │──record_audit(LLM_CALL)──────────┐
│              │──record_audit(TOOL_CALL)──────────┤
│              │──track_cost(llm/tool)─────────────┤
└──────────────┘                                    │
                                                    ▼
┌──────────────┐                           ┌───────────────┐
│  Guardrails  │──record_audit(GUARDRAIL)──│               │
│              │──classify(user_input)──────│  Governance   │
└──────────────┘                           │  Module       │
                                           │               │
┌──────────────┐                           │ ┌───────────┐ │
│  Session     │──record_audit(LIFECYCLE)──│ │ Audit Sink│ │
│  Manager     │                           │ │ Retention │ │
└──────────────┘                           │ │ Classifier│ │
                                           │ │ Cost Agg  │ │
┌──────────────┐                           │ └───────────┘ │
│  Memory      │──record_audit(MEMORY)─────│               │
│  Manager     │──classify(memory_content)─│               │
│              │──check_retention()────────│               │
└──────────────┘                           │               │
                                           │               │
┌──────────────┐                           │               │
│  Admin API   │──query_audit()────────────│               │
│              │──get_cost_report()────────│               │
│              │──enforce_retention()───────│               │
└──────────────┘                           └───────────────┘
```

### 5.2 Event Bus Integration

Governance module vừa được gọi trực tiếp (cho real-time operations) vừa consume events từ bus (cho background processing).

```python
# Direct call (real-time, in execution path)
# Used for: audit recording, cost tracking, classification
await governance.record_audit(event)    # Non-blocking (write-behind)
await governance.track_cost(cost_event) # Non-blocking (Redis counter)
result = await governance.classify(content, ctx)  # Sync, fast (<2ms)

# Event Bus consumer (background, async)
# Used for: lineage building, cost aggregation rollups, retention scheduling
class GovernanceEventConsumer:
    async def on_event(self, event: AgentEvent) -> None:
        match event.type:
            case "session_completed":
                await self.lineage_builder.process_session(event.session_id)
                await self.cost_aggregator.rollup_session(event.session_id)
            case "retention_schedule":
                await self.retention_scheduler.run()
```

---

## 6. Sequence Diagrams

### 6.1 Audit Recording During Execution Step

```
Executor         Guardrails       LLM GW          Governance          PostgreSQL
 │                  │                │                │                    │
 │──inbound check──→│                │                │                    │
 │                  │──record_audit──────────────────→│                    │
 │                  │  {GUARDRAIL,                    │──buffer──→         │
 │                  │   schema_valid,                 │  (in-memory)       │
 │                  │   outcome:pass}                 │                    │
 │◄──pass───────────│                │                │                    │
 │                  │                │                │                    │
 │──chat()─────────────────────────→│                │                    │
 │◄──response──────────────────────│                │                    │
 │                  │                │                │                    │
 │──record_audit───────────────────────────────────→│                    │
 │  {LLM_CALL, model:claude,                        │──buffer──→         │
 │   tokens:2400, cost:0.012}                        │                    │
 │                  │                │                │                    │
 │──track_cost─────────────────────────────────────→│                    │
 │  {llm_call, 0.012 USD}                           │──Redis INCR──→     │
 │                  │                │                │                    │
 │  ... (more execution) ...         │                │                    │
 │                  │                │                │                    │
 │                  │                │                │──flush timer──→    │
 │                  │                │                │  (every 500ms)     │
 │                  │                │                │──batch INSERT──────→│
 │                  │                │                │  (5 audit events)  │
 │                  │                │                │◄──ok───────────────│
```

### 6.2 Retention Enforcement (Background Job)

```
Scheduler       Governance         PostgreSQL          S3 (Archive)      Audit
 │                 │                   │                    │               │
 │──run()─────────→│                   │                    │               │
 │                 │                   │                    │               │
 │                 │──load policies───→│                    │               │
 │                 │◄──[3 policies]────│                    │               │
 │                 │                   │                    │               │
 │                 │ ┌─ Policy: session_data (90 days) ─┐   │               │
 │                 │ │                                   │   │               │
 │                 │ │──SELECT expired──→│               │   │               │
 │                 │ │◄──[42 sessions]──│               │   │               │
 │                 │ │                                   │   │               │
 │                 │ │──archive (export)────────────────→│   │               │
 │                 │ │◄──archived────────────────────────│   │               │
 │                 │ │                                   │   │               │
 │                 │ │──DELETE expired──→│               │   │               │
 │                 │ │◄──42 deleted─────│               │   │               │
 │                 │ │                                   │   │               │
 │                 │ └───────────────────────────────────┘   │               │
 │                 │                                         │               │
 │                 │ ┌─ Policy: trace_spans (30 days) ──┐   │               │
 │                 │ │  ... (similar flow, no archive) ..│   │               │
 │                 │ └───────────────────────────────────┘   │               │
 │                 │                                         │               │
 │                 │──record_audit(RETENTION_ACTION)─────────────────────────→│
 │                 │  {archived:42, deleted:108, freed:2.4GB}                │
 │                 │                                         │               │
 │◄──report────────│                                         │               │
 │  {scanned:500,  │                                         │               │
 │   archived:42,  │                                         │               │
 │   deleted:108}  │                                         │               │
```

### 6.3 Data Classification in Execution Flow

```
Executor         Memory Mgr       Governance        Audit Sink
 │                  │                │                  │
 │  [LLM returned final_answer]     │                  │
 │                  │                │                  │
 │──classify()─────────────────────→│                  │
 │  content: "Your account         │                  │
 │   #1234 balance is $5,430"      │                  │
 │  context: {data_type:           │                  │
 │   "llm_response"}               │                  │
 │                  │                │                  │
 │                  │              ┌─▼──────────────┐  │
 │                  │              │ Rule matching:  │  │
 │                  │              │ ✓ account #     │  │
 │                  │              │   → CONFIDENTIAL│  │
 │                  │              │   tag: financial│  │
 │                  │              │ ✓ dollar amount │  │
 │                  │              │   → CONFIDENTIAL│  │
 │                  │              │   tag: financial│  │
 │                  │              │                 │  │
 │                  │              │ Result:         │  │
 │                  │              │ CONFIDENTIAL    │  │
 │                  │              │ tags: [financial]│  │
 │                  │              └─┬──────────────┘  │
 │                  │                │                  │
 │◄──{CONFIDENTIAL,─────────────────│                  │
 │    [financial]}  │                │                  │
 │                  │                │                  │
 │──record_audit(LLM_CALL,          │                  │
 │   sensitivity:CONFIDENTIAL)──────────────────────→│
 │                  │                │                  │
 │  [Classification informs:                           │
 │   - Audit event tagging                             │
 │   - PII masking in logs                             │
 │   - Retention policy matching]                      │
```

---

## 7. Configuration Model

### 7.1 Platform-Level Governance Config

```python
@dataclass
class GovernanceConfig:
    """Platform-wide governance configuration."""

    # Audit
    audit: AuditConfig

    # Retention
    retention: RetentionConfig

    # Classification
    classification: ClassificationConfig

    # Cost
    cost: CostConfig

@dataclass
class AuditConfig:
    enabled: bool = True
    buffer_size: int = 1000               # Events before forced flush
    flush_interval_ms: int = 500          # Auto-flush interval
    sync_categories: list[str] = field(   # Categories that bypass buffer
        default_factory=lambda: ["auth_event", "config_change"]
    )

@dataclass
class RetentionConfig:
    enabled: bool = True
    schedule_cron: str = "0 2 * * *"      # Daily at 02:00 UTC
    default_policies: list[RetentionPolicy] = field(default_factory=list)
    archive_storage: Literal["s3", "gcs", "none"] = "s3"
    archive_bucket: str = ""
    dry_run: bool = False                 # Log only, don't delete

@dataclass
class ClassificationConfig:
    enabled: bool = True
    default_sensitivity: DataSensitivity = DataSensitivity.INTERNAL
    custom_rules: list[ClassificationRule] = field(default_factory=list)
    classify_audit_events: bool = True    # Auto-classify audit event details
    classify_memory_entries: bool = True  # Auto-classify stored memories

@dataclass
class CostConfig:
    enabled: bool = True
    aggregation_interval_minutes: int = 60  # Rollup frequency
    alert_thresholds: dict[str, float] = field(
        default_factory=lambda: {
            "session_usd": 10.0,          # Alert if single session > $10
            "tenant_daily_usd": 1000.0,   # Alert if tenant daily spend > $1000
        }
    )
```

### 7.2 Tenant-Level Overrides

Tenants có thể override một số governance settings:

```json
{
  "tenant_id": "acme-corp",
  "governance": {
    "retention": {
      "session_data_days": 180,
      "audit_events_days": 730,
      "archive_before_delete": true
    },
    "classification": {
      "custom_rules": [
        {
          "name": "acme_internal_ids",
          "pattern": "ACME-\\d{6}",
          "sensitivity": "confidential",
          "tags": ["internal_id"]
        }
      ]
    },
    "cost": {
      "alert_thresholds": {
        "session_usd": 25.0,
        "tenant_daily_usd": 5000.0
      }
    }
  }
}
```

---

## 8. Tech Stack

| Component | Technology | Phase | Lý do |
|-----------|-----------|-------|-------|
| **Audit storage** | PostgreSQL (partitioned, append-only) | 1 | Queryable, immutable with triggers, partition by month |
| **Audit buffer** | In-memory buffer (asyncio.Queue) | 1 | Zero dependency, fast, sufficient for single-process |
| **Cost counters (real-time)** | Redis (INCR, HSET) | 1 | Atomic counters, sub-ms |
| **Cost aggregates** | PostgreSQL (materialized table) | 1 | Durable, queryable reports |
| **Classification engine** | Regex + custom rules (Python) | 1 | Zero dependency, < 2ms, deterministic |
| **Classification ML** | Fine-tuned classifier (Phase 2) | 2 | Higher accuracy for nuanced content |
| **Retention scheduler** | asyncio background task / APScheduler | 1 | Lightweight, sufficient for Phase 1 |
| **Archive storage** | S3 / GCS (via boto3/google-cloud-storage) | 1 | Cold storage for archived data |
| **Lineage storage** | PostgreSQL (adjacency list model) | 2 | Reuse existing infra |
| **Lineage query** | Recursive CTE (PostgreSQL) | 2 | Graph traversal in SQL |
| **Governance interface** | Python Protocol (ABC) | 1 | Dependency inversion, swappable implementation |

---

## 9. Performance Targets

| Operation | Target Latency | Notes |
|-----------|---------------|-------|
| record_audit (buffered) | < 0.1ms | In-memory append, non-blocking |
| sync_record (critical) | < 5ms | Direct PostgreSQL INSERT |
| flush buffer (batch) | < 20ms | Batch INSERT (up to 1000 events) |
| classify (rule-based) | < 2ms | Regex matching, in-memory |
| track_cost | < 1ms | Redis INCR |
| query_audit (indexed) | < 50ms | PostgreSQL with proper indexes |
| get_session_timeline | < 30ms | Single session, indexed by session_id |
| get_cost_report (daily) | < 100ms | Pre-aggregated table |
| retention_run (per policy) | < 60s | Depends on data volume, batched |
| lineage query (depth 3) | < 200ms | Recursive CTE (Phase 2) |

**Overhead constraint:** Governance module must add **< 1ms total latency** to the execution hot path (via non-blocking buffer + async writes).

---

## 10. Error Handling

| Scenario | Behavior |
|----------|----------|
| Audit buffer flush fails (PG down) | Retry with backoff (3x). If persistent: log to local file as fallback. Never block execution. |
| Redis cost counter unavailable | Use in-memory counter (stale OK for ~1 min). Reconcile with PG aggregates on recovery. |
| Classification rule error | Skip rule, log warning, use default sensitivity. Never block on broken rule. |
| Retention job fails mid-run | Record partial progress. Next run picks up where it left off (idempotent). |
| Retention archive upload fails | Skip deletion for affected records. Retry archive on next run. |
| Audit query timeout | Return partial results with `is_truncated: true` flag. |

---

## 11. Phase Allocation

| Feature | Phase 1 | Phase 2 | Phase 3 |
|---------|---------|---------|---------|
| **Audit Sink** (buffer + batch write) | ✅ | | |
| **Audit Query** (filters, timeline) | ✅ | | |
| **Retention Engine** (policies + scheduler) | ✅ | | |
| **Data Classification** (rule-based) | ✅ | | |
| **Cost Aggregation** (real-time + reports) | ✅ | | |
| **Audit API** (/audit endpoints) | ✅ | | |
| **Governance Port** (interface, local impl) | ✅ | | |
| **Data Lineage** (graph builder + query) | | ✅ | |
| **ML Classification** (fine-tuned model) | | ✅ | |
| **Governance Service** (extract to service) | | ✅ (if needed) | |
| **Compliance Reporting** (GDPR, SOC2) | | ✅ | |
| **Cross-tenant Analytics** | | | ✅ |
| **Data Residency** (geo-aware storage) | | | ✅ |
