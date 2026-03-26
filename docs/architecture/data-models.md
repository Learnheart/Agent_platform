# Data Models & Database Schema

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-26
> **Mục đích:** Định nghĩa canonical cho toàn bộ data models, enums, state machines, error taxonomy, và database schema của platform.

---

## 1. Core Entities

### 1.1 Tenant

```python
class Tenant(BaseModel):
    id: str                          # UUID
    name: str
    slug: str                        # URL-friendly identifier
    config: TenantConfig
    status: Literal["active", "suspended", "deleted"] = "active"
    created_at: datetime
    updated_at: datetime
```

```python
class TenantConfig(BaseModel):
    max_agents: int = 50
    max_concurrent_sessions: int = 100
    max_mcp_servers: int = 20
    daily_budget_usd: float = 100.0
    default_model: str = "claude-sonnet-4-5-20250514"
    features: dict[str, bool] = {}    # feature flags per tenant
```

### 1.2 Agent

```python
class Agent(BaseModel):
    id: str                          # UUID
    tenant_id: str
    name: str
    description: str = ""
    system_prompt: str
    model_config: ModelConfig
    execution_config: ExecutionConfig
    memory_config: MemoryConfig
    guardrails_config: GuardrailsConfig
    tools_config: AgentToolsConfig
    status: Literal["draft", "active", "archived"] = "draft"
    created_by: str                  # user_id
    created_at: datetime
    updated_at: datetime
```

```python
class ModelConfig(BaseModel):
    provider: str = "anthropic"      # Phase 1: "anthropic" only
    model: str = "claude-sonnet-4-5-20250514"
    temperature: float = 1.0
    max_tokens: int = 4096           # max tokens per LLM call
    timeout_seconds: float = 120.0
```

```python
class AgentToolsConfig(BaseModel):
    mcp_server_ids: list[str] = []   # IDs of connected MCP servers
    tool_filters: list[str] | None = None  # whitelist tool patterns, None = all
    max_tools_per_prompt: int = 20   # max tools sent to LLM per call
```

> **ExecutionConfig:** Xem Section 2.2
> **MemoryConfig:** Đã định nghĩa chi tiết trong [`memory.md`](memory.md) Section 5
> **GuardrailsConfig:** Đã định nghĩa chi tiết trong [`guardrails.md`](guardrails.md) Section 4.1

### 1.3 Session

```python
class Session(BaseModel):
    id: str                          # UUID
    tenant_id: str
    agent_id: str
    state: SessionState
    step_index: int = 0
    usage: SessionUsage
    created_by: str                  # user_id hoặc api_key_id
    user_type: Literal["builder", "end_user"]
    metadata: dict = {}
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    ttl_seconds: int = 3600          # session timeout
```

```python
class SessionUsage(BaseModel):
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost_usd: float = 0.0
    total_steps: int = 0
    total_tool_calls: int = 0
    total_llm_calls: int = 0
    duration_seconds: float = 0.0
```

### 1.4 Message

```python
class Message(BaseModel):
    id: str                          # UUID
    session_id: str
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_call_id: str | None = None  # for role="tool" — links to ToolCall.id
    tool_calls: list[ToolCall] | None = None  # for role="assistant" with tool use
    tokens: int | None = None
    created_at: datetime
```

---

## 2. Execution Models

### 2.1 ExecutionTask

> Task được enqueue vào Redis Streams, executor pull và xử lý.

```python
class ExecutionTask(BaseModel):
    id: str                          # UUID — task_id in queue
    session_id: str
    agent_id: str
    tenant_id: str
    trigger: ExecutionTrigger
    created_at: datetime
```

```python
class ExecutionTrigger(BaseModel):
    """Lý do tạo task — xác định executor sẽ làm gì."""
    type: Literal["new_message", "resume", "approval_response", "retry"]
    message_id: str | None = None    # for new_message
    approval_id: str | None = None   # for approval_response
    retry_step_index: int | None = None  # for retry
```

### 2.2 ExecutionConfig

> Đã định nghĩa trong [`planning.md`](planning.md) Section 5. Canonical definition:

```python
class ExecutionConfig(BaseModel):
    # Pattern
    pattern: Literal["react"] = "react"   # Phase 2: "plan_execute", "reflexion"

    # Budget
    max_steps: int = 30
    max_tokens_budget: int = 50_000
    max_cost_usd: float = 5.0
    max_duration_seconds: int = 600
    budget_warning_threshold: float = 0.8
    budget_critical_threshold: float = 0.95

    # Checkpoint
    checkpoint_enabled: bool = True
    checkpoint_interval: int = 1          # save delta every N steps
    checkpoint_snapshot_interval: int = 10 # full snapshot every N steps

    # ReAct
    react_max_consecutive_tool_calls: int = 10

    # Retry
    max_retries_per_step: int = 2
    retry_backoff_seconds: float = 1.0

    # Context window
    max_context_tokens: int = 8000
    context_strategy: Literal[
        "sliding_window",
        "summarize_recent",
        "selective",
        "token_trim"
    ] = "summarize_recent"
```

### 2.3 StepResult

> Kết quả trả về sau mỗi step trong execution loop.

```python
class StepResult(BaseModel):
    type: StepType
    messages: list[Message]          # messages generated in this step
    tool_calls: list[ToolCall] | None = None
    tool_results: list[ToolResult] | None = None
    metadata_updates: dict = {}      # working memory updates
    events: list[AgentEvent] = []
    usage: StepUsage

    # Type-specific fields
    answer: str | None = None        # FINAL_ANSWER: nội dung trả lời
    error_message: str | None = None # ERROR: mô tả lỗi
    error_category: str | None = None # ERROR: ErrorCategory value
    retryable: bool = False          # ERROR: có thể retry?
    approval_id: str | None = None   # WAITING_INPUT: ID để approve/reject
```

```python
class StepUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0          # total step latency (excl. LLM wait)
    llm_latency_ms: float = 0.0      # LLM call latency
    tool_latency_ms: float = 0.0     # tool call latency (if any)
```

### 2.4 ContextPayload

> Payload được build bởi MemoryManager, truyền vào ExecutionEngine.

```python
class ContextPayload(BaseModel):
    """Context window assembled for LLM call.

    Layer order (top → bottom, as injected into messages):
    1. System prompt (from agent config)
    2. Canary token (security marker)
    3. Long-term memory results (Phase 2 — RAG)
    4. Working memory (plan, scratchpad)
    5. Episodic memory (Phase 3 — past episodes)
    6. Budget warning (if approaching limit)
    7. Conversation summary (if strategy = summarize_recent)
    8. Recent messages (last N messages)
    """
    system_prompt: str               # Layer 1 — rendered system prompt
    messages: list[Message]          # Layers 2-8 assembled as message list
    tool_schemas: list[dict]         # tool definitions for LLM (provider-specific format)
    total_tokens_estimate: int       # estimated token count
    has_summary: bool = False        # whether conversation was summarized
    budget_warning: str | None = None # injected budget warning (Layer 6)
```

### 2.5 BudgetCheckResult

> Đã định nghĩa trong [`planning.md`](planning.md) Section 2.7.

```python
class BudgetCheckResult(BaseModel):
    exhausted: bool                  # budget completely used → force stop
    warning: bool                    # approaching limit (> warning_threshold)
    critical: bool                   # near limit (> critical_threshold)
    warning_message: str = ""        # message to inject into context
    checks: list[BudgetCheck] = []

class BudgetCheck(BaseModel):
    type: Literal["tokens", "cost", "steps", "time"]
    current: float                   # current usage
    limit: float                     # configured limit
    ratio: float                     # current / limit (0.0 - 1.0)
```

---

## 3. Checkpoint Models

> Strategy: delta-based — save incremental changes per step, full snapshot every N steps hoặc session end. Xem [`planning.md`](planning.md) Section 2.6.

### 3.1 CheckpointDelta

```python
class CheckpointDelta(BaseModel):
    session_id: str
    step_index: int
    new_messages: list[Message]
    tool_results: list[ToolResult] | None = None
    metadata_updates: dict = {}
    token_usage_delta: StepUsage
    timestamp: datetime
```

### 3.2 CheckpointSnapshot

```python
class CheckpointSnapshot(BaseModel):
    session_id: str
    step_index: int
    state: bytes                     # serialized full Session state
    conversation_hash: str           # integrity check
    usage: SessionUsage              # cumulative usage at this point
    timestamp: datetime
```

---

## 4. Tool Models

### 4.1 ToolCall

```python
class ToolCall(BaseModel):
    id: str                          # tool_use block ID from LLM
    name: str                        # tool name (e.g., "mcp:github:create_issue")
    arguments: dict                  # tool input arguments
```

> **ToolInfo, MCPServerConfig:** Đã định nghĩa chi tiết trong [`mcp-tools.md`](mcp-tools.md) Section 2.1-2.2
> **ToolResult:** Đã định nghĩa chi tiết trong [`mcp-tools.md`](mcp-tools.md) Section 2.2.6

### 4.2 ToolResult (Canonical)

```python
class ToolResult(BaseModel):
    tool_call_id: str                # matches ToolCall.id
    tool_name: str
    content: str                     # normalized text content
    is_error: bool = False
    metadata: dict = {}              # latency_ms, server_id, truncated, etc.
    artifacts: list[str] | None = None  # refs to large stored artifacts
    cost_usd: float | None = None
    latency_ms: float = 0.0
```

---

## 5. LLM Models

> Đã định nghĩa trong [`llm-gateway.md`](llm-gateway.md) Section 2. Canonical definitions:

### 5.1 LLMResponse

```python
class LLMResponse(BaseModel):
    content: str | None              # text response (None if only tool_calls)
    tool_calls: list[ToolCall] | None
    usage: TokenUsage
    model: str
    provider: str
    latency_ms: float
    stop_reason: str                 # "end_turn", "tool_use", "max_tokens", "stop_sequence"
```

### 5.2 TokenUsage

```python
class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int | None = None
    cost_usd: float | None = None
```

### 5.3 LLMStreamEvent

> Events emitted during SSE streaming from LLM Gateway.

```python
class LLMStreamEvent(BaseModel):
    type: Literal[
        "text_delta",       # partial text content
        "tool_call_start",  # tool call begins (name + partial args)
        "tool_call_delta",  # partial tool call arguments
        "tool_call_end",    # tool call complete
        "usage",            # token usage summary
        "done",             # stream complete
        "error",            # stream error
    ]
    # Type-specific fields
    content: str | None = None       # text_delta: partial text
    tool_call: ToolCall | None = None  # tool_call_end: completed call
    tool_call_id: str | None = None  # tool_call_start/delta
    tool_name: str | None = None     # tool_call_start
    arguments_delta: str | None = None  # tool_call_delta: partial JSON
    usage: TokenUsage | None = None  # usage/done
    stop_reason: str | None = None   # done
    error_message: str | None = None # error
```

---

## 6. Event Model

### 6.1 AgentEvent

> Events emitted bởi Executor qua Event Bus. Consumers: SSE Streamer, OTel Exporter, Governance Module, Webhook Notifier. Xem [`00-overview.md`](00-overview.md) Section 5.6.

```python
class AgentEvent(BaseModel):
    id: str                          # UUID
    type: AgentEventType
    session_id: str
    tenant_id: str
    agent_id: str
    step_index: int | None = None
    timestamp: datetime
    data: dict                       # type-specific payload (see below)
```

```python
class AgentEventType(str, Enum):
    # Session lifecycle
    SESSION_CREATED = "session_created"
    SESSION_COMPLETED = "session_completed"

    # Step lifecycle
    STEP_START = "step_start"

    # LLM
    LLM_CALL_START = "llm_call_start"
    LLM_CALL_END = "llm_call_end"
    THOUGHT = "thought"

    # Tool
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Guardrail
    GUARDRAIL_CHECK = "guardrail_check"
    APPROVAL_REQUESTED = "approval_requested"

    # System
    CHECKPOINT = "checkpoint"
    BUDGET_WARNING = "budget_warning"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"

    # Phase 2
    PLAN_CREATED = "plan_created"
    PLAN_STEP_END = "plan_step_end"
    REPLAN = "replan"
```

### 6.2 Event Data Payloads

| Event Type | `data` fields |
|------------|---------------|
| `session_created` | `{agent_id, user_type}` |
| `session_completed` | `{total_steps, total_cost_usd, total_tokens, duration_seconds}` |
| `step_start` | `{step_index, pattern}` |
| `llm_call_start` | `{model, prompt_tokens_estimate}` |
| `llm_call_end` | `{model, prompt_tokens, completion_tokens, cost_usd, latency_ms, stop_reason}` |
| `thought` | `{content}` |
| `tool_call` | `{tool_name, arguments}` |
| `tool_result` | `{tool_name, content_preview, is_error, latency_ms}` |
| `guardrail_check` | `{check_type, check_name, result, action_taken, latency_ms}` |
| `approval_requested` | `{tool_name, arguments, reason, approval_id, timeout_seconds}` |
| `checkpoint` | `{step_index, type: "delta"\|"snapshot", size_bytes}` |
| `budget_warning` | `{budget_type, usage_ratio, message}` |
| `final_answer` | `{content, total_steps, total_cost_usd}` |
| `error` | `{message, category, retryable}` |

---

## 7. Enums

### 7.1 SessionState

```python
class SessionState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
```

### 7.2 StepType

```python
class StepType(str, Enum):
    FINAL_ANSWER = "final_answer"    # LLM returned text-only response (no tool calls)
    TOOL_CALL = "tool_call"          # LLM requested tool use → continue loop
    WAITING_INPUT = "waiting_input"  # HITL approval required → pause session
    ERROR = "error"                  # step failed
```

> **ReAct Termination Logic:** LLM trả về response với `stop_reason="end_turn"` và KHÔNG có `tool_calls` → `StepType.FINAL_ANSWER`. Nếu response có `tool_calls` → `StepType.TOOL_CALL`.

### 7.3 ErrorCategory

> Đã định nghĩa trong [`planning.md`](planning.md) Section 4.1.

```python
class ErrorCategory(str, Enum):
    LLM_RATE_LIMIT = "llm_rate_limit"
    LLM_SERVER_ERROR = "llm_server_error"
    LLM_CONTENT_REFUSAL = "llm_content_refusal"
    LLM_MALFORMED_RESPONSE = "llm_malformed_response"
    LLM_TIMEOUT = "llm_timeout"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_AUTH_FAILURE = "tool_auth_failure"
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    CHECKPOINT_WRITE_FAIL = "checkpoint_write_fail"
    BUDGET_EXCEEDED = "budget_exceeded"
    EXECUTOR_CRASH = "executor_crash"
```

### 7.4 DataSensitivity

> Đã định nghĩa trong [`governance.md`](governance.md) Section 4.3.1.

```python
class DataSensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"        # PII, credentials, regulated data
```

### 7.5 RiskLevel

```python
class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
```

---

## 8. Session State Machine

### 8.1 States & Transitions

```
                  +───────────────────────────────────────────────+
                  │                                               │
                  │    CREATED ──start()──> RUNNING               │
                  │                          │  │  │              │
                  │               complete() │  │  │ wait_input() │
                  │                          v  │  v              │
                  │                    COMPLETED │  WAITING_INPUT  │
                  │                             │     │           │
                  │                    pause()  │     │ approve() │
                  │                          v  │     │ / reject()│
                  │                        PAUSED     │           │
                  │                          │  │     │           │
                  │               resume()   │  │     │           │
                  │                 +────────+  │     │           │
                  │                 │           │     │           │
                  │                 v           │     v           │
                  │               RUNNING <────+─────+           │
                  │                 │                             │
                  │    error() /    │                             │
                  │    timeout()    │                             │
                  │                 v                             │
                  │               FAILED                         │
                  +───────────────────────────────────────────────+
```

### 8.2 Transition Rules

| From | To | Trigger | Guard |
|------|----|---------|-------|
| `CREATED` | `RUNNING` | `start()` | Agent exists, budget available |
| `RUNNING` | `COMPLETED` | `complete()` | StepType == FINAL_ANSWER |
| `RUNNING` | `PAUSED` | `pause()` | Explicit pause request (Builder) |
| `RUNNING` | `WAITING_INPUT` | `wait_input()` | HITL approval required |
| `RUNNING` | `FAILED` | `error()` | Non-retryable error, hoặc retries exhausted |
| `RUNNING` | `FAILED` | `timeout()` | `max_duration_seconds` exceeded |
| `PAUSED` | `RUNNING` | `resume()` | Explicit resume request |
| `PAUSED` | `FAILED` | `timeout()` | Paused quá TTL |
| `WAITING_INPUT` | `RUNNING` | `approve()` | Human approved tool call |
| `WAITING_INPUT` | `RUNNING` | `reject()` | Human rejected → LLM nhận rejection message |
| `WAITING_INPUT` | `FAILED` | `timeout()` | Approval timeout (default 3600s) |

### 8.3 Invalid Transitions

Tất cả transitions không có trong bảng trên đều bị từ chối. Đặc biệt:
- `COMPLETED` → any: session đã kết thúc, không thể thay đổi state
- `FAILED` → any: session đã kết thúc, không thể thay đổi state
- `CREATED` → `COMPLETED`: không thể skip execution

---

## 9. Error Taxonomy

### 9.1 Error Response Model

```python
class PlatformError(BaseModel):
    code: str                        # machine-readable error code
    message: str                     # human-readable message
    category: ErrorCategory | None = None
    details: dict = {}               # structured error details
    retryable: bool = False
    trace_id: str | None = None      # OpenTelemetry trace ID
```

### 9.2 Retry Policy Defaults

> Từ [`planning.md`](planning.md) Section 4.1.

| Error Category | max_retries | backoff_base (s) | multiplier | max (s) |
|---|---|---|---|---|
| `LLM_RATE_LIMIT` | 5 | 2.0 | 2.0 | 60.0 |
| `LLM_SERVER_ERROR` | 3 | 1.0 | 2.0 | 30.0 |
| `LLM_CONTENT_REFUSAL` | 0 | — | — | — |
| `LLM_MALFORMED_RESPONSE` | 1 | 0.5 | 1.0 | 1.0 |
| `LLM_TIMEOUT` | 2 | 1.0 | 1.5 | 10.0 |
| `TOOL_TIMEOUT` | 0 | — | — | — |
| `TOOL_AUTH_FAILURE` | 0 | — | — | — |
| `TOOL_EXECUTION_ERROR` | 0 | — | — | — |
| `CHECKPOINT_WRITE_FAIL` | 3 | 0.5 | 2.0 | 10.0 |
| `BUDGET_EXCEEDED` | 0 | — | — | — |
| `EXECUTOR_CRASH` | — | — | — | — |

```python
class RetryPolicy(BaseModel):
    max_retries: int
    backoff_base_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    backoff_max_seconds: float = 30.0
```

### 9.3 API Error Codes

| HTTP Status | Error Code | Mô tả |
|---|---|---|
| 400 | `INVALID_REQUEST` | Request body không hợp lệ |
| 400 | `INVALID_AGENT_CONFIG` | Agent config validation failed |
| 400 | `INVALID_STATE_TRANSITION` | Session state transition không hợp lệ |
| 401 | `UNAUTHORIZED` | Missing or invalid credentials |
| 403 | `FORBIDDEN` | Không có quyền truy cập resource |
| 403 | `TENANT_MISMATCH` | Resource không thuộc tenant hiện tại |
| 404 | `AGENT_NOT_FOUND` | Agent không tồn tại |
| 404 | `SESSION_NOT_FOUND` | Session không tồn tại |
| 404 | `TOOL_NOT_FOUND` | Tool không tồn tại |
| 409 | `SESSION_ALREADY_RUNNING` | Session đang chạy, không thể start lại |
| 409 | `SESSION_COMPLETED` | Session đã kết thúc |
| 422 | `GUARDRAIL_BLOCKED` | Input bị block bởi guardrails |
| 429 | `RATE_LIMITED` | Quá số lượng request cho phép |
| 500 | `INTERNAL_ERROR` | Lỗi hệ thống |
| 502 | `LLM_PROVIDER_ERROR` | LLM provider trả về lỗi |
| 503 | `SERVICE_UNAVAILABLE` | Service tạm thời không khả dụng |
| 504 | `LLM_TIMEOUT` | LLM call timeout |

---

## 10. Database Schema (PostgreSQL)

> Tất cả tables sử dụng Row-Level Security (RLS) để tenant isolation. Xem [`00-overview.md`](00-overview.md) Section 10.

### 10.1 tenants

```sql
CREATE TABLE tenants (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    config      JSONB NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'suspended', 'deleted')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 10.2 agents

```sql
CREATE TABLE agents (
    id                TEXT NOT NULL,
    tenant_id         TEXT NOT NULL REFERENCES tenants(id),
    name              TEXT NOT NULL,
    description       TEXT DEFAULT '',
    system_prompt     TEXT NOT NULL,
    model_config      JSONB NOT NULL,      -- ModelConfig
    execution_config  JSONB NOT NULL,      -- ExecutionConfig
    memory_config     JSONB NOT NULL,      -- MemoryConfig
    guardrails_config JSONB NOT NULL,      -- GuardrailsConfig
    tools_config      JSONB NOT NULL,      -- AgentToolsConfig
    status            TEXT NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft', 'active', 'archived')),
    created_by        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (tenant_id, id)
);

ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON agents
    USING (tenant_id = current_setting('app.current_tenant'));

CREATE INDEX idx_agents_tenant_status ON agents (tenant_id, status);
```

### 10.3 sessions

```sql
CREATE TABLE sessions (
    id              TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'created'
                    CHECK (state IN (
                        'created', 'running', 'paused',
                        'waiting_input', 'completed', 'failed'
                    )),
    step_index      INT NOT NULL DEFAULT 0,
    usage           JSONB NOT NULL DEFAULT '{}',   -- SessionUsage
    created_by      TEXT NOT NULL,
    user_type       TEXT NOT NULL DEFAULT 'builder'
                    CHECK (user_type IN ('builder', 'end_user')),
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    ttl_seconds     INT NOT NULL DEFAULT 3600,

    PRIMARY KEY (tenant_id, id),
    CONSTRAINT fk_agent FOREIGN KEY (tenant_id, agent_id)
        REFERENCES agents(tenant_id, id)
);

ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON sessions
    USING (tenant_id = current_setting('app.current_tenant'));

CREATE INDEX idx_sessions_agent ON sessions (tenant_id, agent_id, state);
CREATE INDEX idx_sessions_state ON sessions (tenant_id, state, created_at DESC);
CREATE INDEX idx_sessions_created ON sessions (tenant_id, created_at DESC);
```

### 10.4 messages

> Conversation history durable storage. Hot copy cũng lưu trong Redis.

```sql
CREATE TABLE messages (
    id              TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    role            TEXT NOT NULL
                    CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content         TEXT NOT NULL,
    tool_call_id    TEXT,
    tool_calls      JSONB,             -- list[ToolCall] as JSON
    tokens          INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (tenant_id, session_id, id),
    CONSTRAINT fk_session FOREIGN KEY (tenant_id, session_id)
        REFERENCES sessions(tenant_id, id) ON DELETE CASCADE
);

ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON messages
    USING (tenant_id = current_setting('app.current_tenant'));

CREATE INDEX idx_messages_session ON messages (tenant_id, session_id, created_at);
```

### 10.5 checkpoints_deltas

```sql
CREATE TABLE checkpoints_deltas (
    session_id      TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    step_index      INT NOT NULL,
    new_messages    JSONB NOT NULL DEFAULT '[]',
    tool_results    JSONB,
    metadata_updates JSONB NOT NULL DEFAULT '{}',
    usage_delta     JSONB NOT NULL DEFAULT '{}',  -- StepUsage
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (tenant_id, session_id, step_index),
    CONSTRAINT fk_session FOREIGN KEY (tenant_id, session_id)
        REFERENCES sessions(tenant_id, id) ON DELETE CASCADE
);

ALTER TABLE checkpoints_deltas ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON checkpoints_deltas
    USING (tenant_id = current_setting('app.current_tenant'));
```

### 10.6 checkpoints_snapshots

```sql
CREATE TABLE checkpoints_snapshots (
    session_id          TEXT NOT NULL,
    tenant_id           TEXT NOT NULL,
    step_index          INT NOT NULL,
    state               BYTEA NOT NULL,       -- serialized Session
    conversation_hash   TEXT NOT NULL,
    usage               JSONB NOT NULL DEFAULT '{}',  -- SessionUsage
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (tenant_id, session_id, step_index),
    CONSTRAINT fk_session FOREIGN KEY (tenant_id, session_id)
        REFERENCES sessions(tenant_id, id) ON DELETE CASCADE
);

ALTER TABLE checkpoints_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON checkpoints_snapshots
    USING (tenant_id = current_setting('app.current_tenant'));
```

### 10.7 tools

> Đã định nghĩa trong [`mcp-tools.md`](mcp-tools.md) Section 2.1.1. Xem doc gốc cho full DDL.

```sql
CREATE TABLE tools (
    id                  TEXT NOT NULL,
    tenant_id           TEXT NOT NULL,
    server_id           TEXT NOT NULL,
    name                TEXT NOT NULL,
    namespace           TEXT NOT NULL,
    description         TEXT NOT NULL,
    input_schema        JSONB NOT NULL,
    output_schema       JSONB,
    execution_mode      TEXT DEFAULT 'sync',
    default_timeout_ms  INT DEFAULT 30000,
    estimated_latency_ms INT,
    estimated_cost      FLOAT,
    idempotent          BOOLEAN DEFAULT FALSE,
    permission_scope    TEXT[] DEFAULT '{}',
    risk_level          TEXT DEFAULT 'low',
    requires_approval   BOOLEAN DEFAULT FALSE,
    visibility          TEXT DEFAULT 'tenant',
    discovered_at       TIMESTAMPTZ DEFAULT NOW(),
    last_verified_at    TIMESTAMPTZ DEFAULT NOW(),
    status              TEXT DEFAULT 'active',

    PRIMARY KEY (tenant_id, id),
    CONSTRAINT fk_server FOREIGN KEY (tenant_id, server_id)
        REFERENCES mcp_servers(tenant_id, id)
);

ALTER TABLE tools ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tools
    USING (tenant_id = current_setting('app.current_tenant'));

CREATE INDEX idx_tools_namespace ON tools (tenant_id, namespace);
```

### 10.8 mcp_servers

> Đã định nghĩa trong [`mcp-tools.md`](mcp-tools.md) Section 2.2.2. Xem doc gốc cho full DDL.

```sql
CREATE TABLE mcp_servers (
    id                          TEXT NOT NULL,
    tenant_id                   TEXT NOT NULL REFERENCES tenants(id),
    name                        TEXT NOT NULL,
    description                 TEXT,
    transport                   TEXT NOT NULL
                                CHECK (transport IN ('stdio', 'sse', 'streamable_http')),
    command                     TEXT,
    args                        JSONB,
    env_encrypted               BYTEA,
    url                         TEXT,
    headers_encrypted           BYTEA,
    connect_timeout_ms          INT DEFAULT 10000,
    request_timeout_ms          INT DEFAULT 30000,
    max_retries                 INT DEFAULT 3,
    auto_start                  BOOLEAN DEFAULT TRUE,
    health_check_interval_seconds INT DEFAULT 60,
    allowed_tools               TEXT[],
    blocked_tools               TEXT[],
    sandbox_level               TEXT DEFAULT 'none',
    status                      TEXT DEFAULT 'disconnected',
    last_connected_at           TIMESTAMPTZ,
    last_error                  TEXT,
    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (tenant_id, id)
);

ALTER TABLE mcp_servers ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON mcp_servers
    USING (tenant_id = current_setting('app.current_tenant'));
```

### 10.9 audit_events

> Đã định nghĩa trong [`governance.md`](governance.md) Section 4.1.3. Partitioned by month, append-only.

```sql
CREATE TABLE audit_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tenant_id       TEXT NOT NULL,
    agent_id        TEXT,
    session_id      TEXT,
    step_index      INT,
    category        TEXT NOT NULL,
    action          TEXT NOT NULL,
    actor_type      TEXT NOT NULL,
    actor_id        TEXT NOT NULL,
    actor_ip        INET,
    resource_type   TEXT,
    resource_id     TEXT,
    details         JSONB NOT NULL DEFAULT '{}',
    sensitivity     TEXT NOT NULL DEFAULT 'internal',
    outcome         TEXT NOT NULL,
    created_date    DATE GENERATED ALWAYS AS (DATE(timestamp)) STORED
) PARTITION BY RANGE (created_date);

-- Append-only constraint
CREATE OR REPLACE FUNCTION prevent_audit_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: UPDATE and DELETE are not allowed';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_immutable
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();

ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON audit_events
    USING (tenant_id = current_setting('app.current_tenant'));

CREATE INDEX idx_audit_tenant_time ON audit_events (tenant_id, timestamp DESC);
CREATE INDEX idx_audit_session ON audit_events (session_id, timestamp);
CREATE INDEX idx_audit_category ON audit_events (category, timestamp DESC);
CREATE INDEX idx_audit_outcome ON audit_events (outcome, timestamp DESC)
    WHERE outcome != 'success';
```

### 10.10 cost_events

> Đã định nghĩa trong [`governance.md`](governance.md) Section 4.4.

```sql
CREATE TABLE cost_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tenant_id       TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    step_index      INT NOT NULL,
    event_type      TEXT NOT NULL
                    CHECK (event_type IN ('llm_call', 'tool_call', 'embedding')),
    provider        TEXT,
    model           TEXT,
    input_tokens    INT,
    output_tokens   INT,
    tool_name       TEXT,
    cost_usd        NUMERIC(10, 6) NOT NULL
);

ALTER TABLE cost_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON cost_events
    USING (tenant_id = current_setting('app.current_tenant'));

CREATE INDEX idx_cost_session ON cost_events (session_id, timestamp);
CREATE INDEX idx_cost_tenant_time ON cost_events (tenant_id, timestamp DESC);
```

### 10.11 cost_daily_aggregates

```sql
CREATE TABLE cost_daily_aggregates (
    date                DATE NOT NULL,
    tenant_id           TEXT NOT NULL,
    agent_id            TEXT,
    provider            TEXT,
    model               TEXT,
    total_cost_usd      NUMERIC(12, 6),
    total_llm_calls     INT,
    total_tool_calls    INT,
    total_input_tokens  BIGINT,
    total_output_tokens BIGINT,

    PRIMARY KEY (date, tenant_id, agent_id, provider, model)
);
```

### 10.12 memories

> Phase 2. Đã định nghĩa trong [`memory.md`](memory.md) Section 3.4.

```sql
CREATE TABLE memories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    namespace       TEXT NOT NULL DEFAULT 'default',
    content         TEXT NOT NULL,
    content_type    TEXT DEFAULT 'text'
                    CHECK (content_type IN ('text', 'structured', 'code')),
    embedding       VECTOR(1536) NOT NULL,
    metadata        JSONB DEFAULT '{}',
    source          TEXT,
    tags            TEXT[] DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    access_count    INT DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,

    CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON memories
    USING (tenant_id = current_setting('app.current_tenant'));

CREATE INDEX idx_memories_embedding ON memories
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_memories_scope ON memories (tenant_id, agent_id, namespace);
```

### 10.13 Entity Relationship Diagram

```
tenants
  │
  ├──1:N── agents
  │          │
  │          ├──1:N── sessions
  │          │          │
  │          │          ├──1:N── messages
  │          │          ├──1:N── checkpoints_deltas
  │          │          ├──1:N── checkpoints_snapshots
  │          │          └──1:N── cost_events
  │          │
  │          └──N:M── mcp_servers (via tools_config.mcp_server_ids)
  │
  ├──1:N── mcp_servers
  │          │
  │          └──1:N── tools
  │
  ├──1:N── audit_events
  ├──1:N── cost_daily_aggregates
  └──1:N── memories (Phase 2)
```

---

## 11. Redis Schema

### 11.1 Key Patterns

| Pattern | Type | TTL | Mô tả |
|---------|------|-----|--------|
| `session:{session_id}:messages` | List (RPUSH/LRANGE) | session + 1h | Conversation buffer (hot copy) |
| `session:{session_id}:working` | Hash (HSET/HGETALL) | session duration | Working memory: plan, scratchpad, artifacts |
| `session:{session_id}:state` | String (SET/GET) | session + 1h | Serialized Session object (hot cache) |
| `checkpoint:snapshot:{session_id}` | String | session + 1h | Latest full checkpoint snapshot |
| `checkpoint:deltas:{session_id}` | List | session + 1h | Ordered checkpoint deltas |
| `budget:{session_id}` | Hash | session duration | Real-time budget counters (tokens, cost, steps) |
| `rate_limit:{tenant_id}:{endpoint}` | String (INCR/EXPIRE) | Window duration | Rate limit counter per endpoint |
| `rate_limit:{tenant_id}:{user_id}` | String (INCR/EXPIRE) | Window duration | Rate limit counter per user |
| `cost:session:{session_id}` | Hash (HINCRBY) | session + 1h | Real-time cost accumulator |
| `cost:tenant:{tenant_id}:daily` | Hash (HINCRBY) | 25h | Daily tenant cost accumulator |
| `mcp:health:{server_id}` | Hash | indefinite | MCP server health status |

### 11.2 Redis Streams

| Stream | Consumer Group | Mô tả |
|--------|----------------|--------|
| `tasks:{tenant_id}` | `executor_group` | Execution task queue. Messages: ExecutionTask as JSON |
| `events:{session_id}` | `sse_group`, `governance_group` | AgentEvent fan-out to consumers |

---

## 12. Phase Scope Summary

| Model / Table | Phase 1 | Phase 2 | Phase 3 |
|---------------|:-------:|:-------:|:-------:|
| Tenant, Agent, Session, Message | ✅ | | |
| ExecutionTask, StepResult, ContextPayload | ✅ | | |
| ExecutionConfig (react) | ✅ | extend (plan_execute, reflexion) | |
| CheckpointDelta, CheckpointSnapshot | ✅ | | |
| ToolCall, ToolResult, ToolInfo | ✅ | | |
| MCPServerConfig | ✅ | | |
| LLMResponse, TokenUsage, LLMConfig | ✅ | | |
| LLMStreamEvent | ✅ | | |
| AgentEvent | ✅ | extend (plan events) | |
| ModelConfig (anthropic only) | ✅ | extend (openai, gemini) | |
| MemoryConfig (short-term + working) | ✅ | extend (long-term) | extend (episodic) |
| GuardrailsConfig (hard + soft/circuit breaker) | ✅ | extend (custom rules, PII) | |
| BudgetConfig, BudgetCheckResult | ✅ | | |
| AuditEvent, AuditFilters | ✅ | | |
| CostEvent, CostReport | ✅ | | |
| RetentionPolicy | ✅ | | |
| DataClassification | ✅ | | |
| Plan, PlanStep | | ✅ | |
| Episode | | | ✅ |
| memories table (pgvector) | | ✅ | |
| LineageNode, LineageEdge, LineageGraph | | ✅ | |
