# Data Models & Database Schema

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-26
> **Mục đích:** Định nghĩa canonical cho toàn bộ data models, enums, state machines, error taxonomy, và database schema của platform.

---

## 1. Core Entities

### 1.1 Tenant

**Tenant** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | UUID |
| name | str | — | Tên tenant |
| slug | str | — | URL-friendly identifier |
| config | TenantConfig | — | Cấu hình tenant |
| status | Literal["active", "suspended", "deleted"] | "active" | Trạng thái tenant |
| created_at | datetime | — | Thời điểm tạo |
| updated_at | datetime | — | Thời điểm cập nhật |

**TenantConfig** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| max_agents | int | 50 | Số agent tối đa |
| max_concurrent_sessions | int | 100 | Số session đồng thời tối đa |
| max_mcp_servers | int | 20 | Số MCP server tối đa |
| daily_budget_usd | float | 100.0 | Budget hàng ngày (USD) |
| default_model | str | "claude-sonnet-4-5-20250514" | Model mặc định |
| features | dict[str, bool] | {} | Feature flags per tenant |

### 1.2 Agent

**Agent** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | UUID |
| tenant_id | str | — | ID của tenant sở hữu |
| name | str | — | Tên agent |
| description | str | "" | Mô tả agent |
| system_prompt | str | — | System prompt |
| model_config | ModelConfig | — | Cấu hình model |
| execution_config | ExecutionConfig | — | Cấu hình execution |
| memory_config | MemoryConfig | — | Cấu hình memory |
| guardrails_config | GuardrailsConfig | — | Cấu hình guardrails |
| tools_config | AgentToolsConfig | — | Cấu hình tools |
| status | Literal["draft", "active", "archived"] | "draft" | Trạng thái agent |
| created_by | str | — | user_id của người tạo |
| created_at | datetime | — | Thời điểm tạo |
| updated_at | datetime | — | Thời điểm cập nhật |

**ModelConfig** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| provider | str | "anthropic" | Phase 1: "anthropic" only |
| model | str | "claude-sonnet-4-5-20250514" | Tên model |
| temperature | float | 1.0 | Temperature cho LLM |
| max_tokens | int | 4096 | Max tokens per LLM call |
| timeout_seconds | float | 120.0 | Timeout cho LLM call |

**AgentToolsConfig** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| mcp_server_ids | list[str] | [] | IDs of connected MCP servers |
| tool_filters | list[str] \| None | None | Whitelist tool patterns, None = all |
| max_tools_per_prompt | int | 20 | Max tools sent to LLM per call |

> **ExecutionConfig:** Xem Section 2.2
> **MemoryConfig:** Đã định nghĩa chi tiết trong [`05-memory.md`](05-memory.md) Section 5
> **GuardrailsConfig:** Đã định nghĩa chi tiết trong [`07-guardrails.md`](07-guardrails.md) Section 4.1

### 1.3 Session

**Session** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | UUID |
| tenant_id | str | — | ID của tenant |
| agent_id | str | — | ID của agent |
| state | SessionState | — | Trạng thái session |
| step_index | int | 0 | Bước hiện tại |
| usage | SessionUsage | — | Thông tin sử dụng |
| created_by | str | — | user_id hoặc api_key_id |
| user_type | Literal["builder", "end_user"] | — | Loại user |
| metadata | dict | {} | Metadata bổ sung |
| created_at | datetime | — | Thời điểm tạo |
| updated_at | datetime | — | Thời điểm cập nhật |
| completed_at | datetime \| None | None | Thời điểm kết thúc |
| ttl_seconds | int | 3600 | Session timeout |

**SessionUsage** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| total_tokens | int | 0 | Tổng tokens đã dùng |
| prompt_tokens | int | 0 | Tokens cho prompt |
| completion_tokens | int | 0 | Tokens cho completion |
| total_cost_usd | float | 0.0 | Tổng chi phí (USD) |
| total_steps | int | 0 | Tổng số steps |
| total_tool_calls | int | 0 | Tổng số tool calls |
| total_llm_calls | int | 0 | Tổng số LLM calls |
| duration_seconds | float | 0.0 | Tổng thời gian (giây) |

### 1.4 Message

**Message** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | UUID |
| session_id | str | — | ID của session |
| role | Literal["user", "assistant", "system", "tool"] | — | Vai trò của message |
| content | str | — | Nội dung message |
| tool_call_id | str \| None | None | Cho role="tool" — links to ToolCall.id |
| tool_calls | list[ToolCall] \| None | None | Cho role="assistant" with tool use |
| tokens | int \| None | None | Số tokens |
| created_at | datetime | — | Thời điểm tạo |

---

## 2. Execution Models

### 2.1 ExecutionTask

> Task được enqueue vào Redis Streams, executor pull và xử lý.

**ExecutionTask** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | UUID — task_id in queue |
| session_id | str | — | ID của session |
| agent_id | str | — | ID của agent |
| tenant_id | str | — | ID của tenant |
| trigger | ExecutionTrigger | — | Lý do tạo task |
| created_at | datetime | — | Thời điểm tạo |

**ExecutionTrigger** (BaseModel) — Lý do tạo task — xác định executor sẽ làm gì.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| type | Literal["new_message", "resume", "approval_response", "retry"] | — | Loại trigger |
| message_id | str \| None | None | Cho new_message |
| approval_id | str \| None | None | Cho approval_response |
| retry_step_index | int \| None | None | Cho retry |

### 2.2 ExecutionConfig

> Đã định nghĩa trong [`03-planning.md`](03-planning.md) Section 5. Canonical definition:

**ExecutionConfig** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| pattern | Literal["react"] | "react" | Phase 2: "plan_execute", "reflexion" |
| max_steps | int | 30 | Budget: số step tối đa |
| max_tokens_budget | int | 50000 | Budget: tổng tokens tối đa |
| max_cost_usd | float | 5.0 | Budget: chi phí tối đa (USD) |
| max_duration_seconds | int | 600 | Budget: thời gian tối đa (giây) |
| budget_warning_threshold | float | 0.8 | Ngưỡng cảnh báo budget |
| budget_critical_threshold | float | 0.95 | Ngưỡng critical budget |
| checkpoint_enabled | bool | True | Bật/tắt checkpoint |
| checkpoint_interval | int | 1 | Save delta every N steps |
| checkpoint_snapshot_interval | int | 10 | Full snapshot every N steps |
| react_max_consecutive_tool_calls | int | 10 | ReAct: max tool calls liên tiếp |
| max_retries_per_step | int | 2 | Retry: số lần retry tối đa per step |
| retry_backoff_seconds | float | 1.0 | Retry: backoff base (giây) |
| max_context_tokens | int | 8000 | Context window: max tokens |
| context_strategy | Literal["sliding_window", "summarize_recent", "selective", "token_trim"] | "summarize_recent" | Context window: chiến lược quản lý context |

### 2.3 StepResult

> Kết quả trả về sau mỗi step trong execution loop.

**StepResult** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| type | StepType | — | Loại step |
| messages | list[Message] | — | Messages generated in this step |
| tool_calls | list[ToolCall] \| None | None | Tool calls (nếu có) |
| tool_results | list[ToolResult] \| None | None | Tool results (nếu có) |
| metadata_updates | dict | {} | Working memory updates |
| events | list[AgentEvent] | [] | Events emitted |
| usage | StepUsage | — | Usage cho step này |
| answer | str \| None | None | FINAL_ANSWER: nội dung trả lời |
| error_message | str \| None | None | ERROR: mô tả lỗi |
| error_category | str \| None | None | ERROR: ErrorCategory value |
| retryable | bool | False | ERROR: có thể retry? |
| approval_id | str \| None | None | WAITING_INPUT: ID để approve/reject |

**StepUsage** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| prompt_tokens | int | 0 | Tokens cho prompt |
| completion_tokens | int | 0 | Tokens cho completion |
| cost_usd | float | 0.0 | Chi phí (USD) |
| latency_ms | float | 0.0 | Total step latency (excl. LLM wait) |
| llm_latency_ms | float | 0.0 | LLM call latency |
| tool_latency_ms | float | 0.0 | Tool call latency (if any) |

### 2.4 ContextPayload

> Payload được build bởi MemoryManager, truyền vào ExecutionEngine.

**ContextPayload** (BaseModel) — Context window assembled for LLM call.

Layer order (top -> bottom, as injected into messages):
1. System prompt (from agent config)
2. Canary token (security marker)
3. Long-term memory results (Phase 2 — RAG)
4. Working memory (plan, scratchpad)
5. Episodic memory (Phase 3 — past episodes)
6. Budget warning (if approaching limit)
7. Conversation summary (if strategy = summarize_recent)
8. Recent messages (last N messages)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| system_prompt | str | — | Layer 1 — rendered system prompt |
| messages | list[Message] | — | Layers 2-8 assembled as message list |
| tool_schemas | list[dict] | — | Tool definitions for LLM (provider-specific format) |
| total_tokens_estimate | int | — | Estimated token count |
| has_summary | bool | False | Whether conversation was summarized |
| budget_warning | str \| None | None | Injected budget warning (Layer 6) |

### 2.5 BudgetCheckResult

> Đã định nghĩa trong [`03-planning.md`](03-planning.md) Section 2.7.

**BudgetCheckResult** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| exhausted | bool | — | Budget completely used — force stop |
| warning | bool | — | Approaching limit (> warning_threshold) |
| critical | bool | — | Near limit (> critical_threshold) |
| warning_message | str | "" | Message to inject into context |
| checks | list[BudgetCheck] | [] | Danh sách budget checks |

**BudgetCheck** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| type | Literal["tokens", "cost", "steps", "time"] | — | Loại budget check |
| current | float | — | Current usage |
| limit | float | — | Configured limit |
| ratio | float | — | current / limit (0.0 - 1.0) |

---

## 3. Checkpoint Models

> Strategy: delta-based — save incremental changes per step, full snapshot every N steps hoặc session end. Xem [`03-planning.md`](03-planning.md) Section 2.6.

### 3.1 CheckpointDelta

**CheckpointDelta** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| session_id | str | — | ID của session |
| step_index | int | — | Index của step |
| new_messages | list[Message] | — | Messages mới trong step |
| tool_results | list[ToolResult] \| None | None | Tool results (nếu có) |
| metadata_updates | dict | {} | Metadata updates |
| token_usage_delta | StepUsage | — | Token usage cho step này |
| timestamp | datetime | — | Thời điểm tạo |

### 3.2 CheckpointSnapshot

**CheckpointSnapshot** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| session_id | str | — | ID của session |
| step_index | int | — | Index của step |
| state | bytes | — | Serialized full Session state |
| conversation_hash | str | — | Integrity check |
| usage | SessionUsage | — | Cumulative usage at this point |
| timestamp | datetime | — | Thời điểm tạo |

---

## 4. Tool Models

### 4.1 ToolCall

**ToolCall** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | tool_use block ID from LLM |
| name | str | — | Tool name (e.g., "mcp:github:create_issue") |
| arguments | dict | — | Tool input arguments |

> **ToolInfo, MCPServerConfig:** Đã định nghĩa chi tiết trong [`06-mcp-tools.md`](06-mcp-tools.md) Section 2.1-2.2
> **ToolResult:** Đã định nghĩa chi tiết trong [`06-mcp-tools.md`](06-mcp-tools.md) Section 2.2.6

### 4.2 ToolResult (Canonical)

**ToolResult** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| tool_call_id | str | — | Matches ToolCall.id |
| tool_name | str | — | Tên tool |
| content | str | — | Normalized text content |
| is_error | bool | False | Có phải lỗi không |
| metadata | dict | {} | latency_ms, server_id, truncated, etc. |
| artifacts | list[str] \| None | None | Refs to large stored artifacts |
| cost_usd | float \| None | None | Chi phí (USD) |
| latency_ms | float | 0.0 | Thời gian thực thi (ms) |

---

## 5. LLM Models

> Đã định nghĩa trong [`04-llm-gateway.md`](04-llm-gateway.md) Section 2. Canonical definitions:

### 5.1 LLMResponse

**LLMResponse** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| content | str \| None | — | Text response (None if only tool_calls) |
| tool_calls | list[ToolCall] \| None | — | Tool calls (nếu có) |
| usage | TokenUsage | — | Token usage |
| model | str | — | Tên model |
| provider | str | — | Tên provider |
| latency_ms | float | — | Thời gian phản hồi (ms) |
| stop_reason | str | — | "end_turn", "tool_use", "max_tokens", "stop_sequence" |

### 5.2 TokenUsage

**TokenUsage** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| prompt_tokens | int | — | Tokens cho prompt |
| completion_tokens | int | — | Tokens cho completion |
| total_tokens | int | — | Tổng tokens |
| cached_tokens | int \| None | None | Cached tokens (nếu có) |
| cost_usd | float \| None | None | Chi phí (USD) |

### 5.3 LLMStreamEvent

> Events emitted during SSE streaming from LLM Gateway.

**LLMStreamEvent** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| type | Literal["text_delta", "tool_call_start", "tool_call_delta", "tool_call_end", "usage", "done", "error"] | — | Loại event (xem bảng chi tiết bên dưới) |
| content | str \| None | None | text_delta: partial text |
| tool_call | ToolCall \| None | None | tool_call_end: completed call |
| tool_call_id | str \| None | None | tool_call_start/delta |
| tool_name | str \| None | None | tool_call_start |
| arguments_delta | str \| None | None | tool_call_delta: partial JSON |
| usage | TokenUsage \| None | None | usage/done |
| stop_reason | str \| None | None | done |
| error_message | str \| None | None | error |

**LLMStreamEvent type values:**

| Value | Description |
|-------|-------------|
| text_delta | Partial text content |
| tool_call_start | Tool call begins (name + partial args) |
| tool_call_delta | Partial tool call arguments |
| tool_call_end | Tool call complete |
| usage | Token usage summary |
| done | Stream complete |
| error | Stream error |

---

## 6. Event Model

### 6.1 AgentEvent

> Events emitted bởi Executor qua Event Bus. Consumers: SSE Streamer, OTel Exporter, Governance Module, Webhook Notifier. Xem [`00-overview.md`](00-overview.md) Section 5.6.

**AgentEvent** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | UUID |
| type | AgentEventType | — | Loại event |
| session_id | str | — | ID của session |
| tenant_id | str | — | ID của tenant |
| agent_id | str | — | ID của agent |
| step_index | int \| None | None | Index của step (nếu có) |
| timestamp | datetime | — | Thời điểm phát event |
| data | dict | — | Type-specific payload (xem Section 6.2) |

**AgentEventType** (str, Enum)

| Value | Description |
|-------|-------------|
| session_created | Session lifecycle: session đã được tạo |
| session_completed | Session lifecycle: session đã kết thúc |
| step_start | Step lifecycle: bắt đầu step |
| llm_call_start | LLM: bắt đầu gọi LLM |
| llm_call_end | LLM: kết thúc gọi LLM |
| thought | LLM: reasoning/thinking content |
| tool_call | Tool: gọi tool |
| tool_result | Tool: kết quả tool |
| guardrail_check | Guardrail: kiểm tra guardrail |
| approval_requested | Guardrail: yêu cầu approval (HITL) |
| checkpoint | System: checkpoint đã lưu |
| budget_warning | System: cảnh báo budget |
| final_answer | System: câu trả lời cuối cùng |
| error | System: lỗi |
| plan_created | Phase 2: plan đã được tạo |
| plan_step_end | Phase 2: kết thúc plan step |
| replan | Phase 2: replan |

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

**SessionState** (str, Enum)

| Value | Description |
|-------|-------------|
| created | Session đã tạo, chưa chạy |
| running | Session đang chạy |
| paused | Session tạm dừng |
| waiting_input | Đang chờ input từ user (HITL) |
| completed | Session đã hoàn thành |
| failed | Session thất bại |

### 7.2 StepType

**StepType** (str, Enum)

| Value | Description |
|-------|-------------|
| final_answer | LLM returned text-only response (no tool calls) |
| tool_call | LLM requested tool use — continue loop |
| waiting_input | HITL approval required — pause session |
| error | Step failed |

> **ReAct Termination Logic:** LLM trả về response với `stop_reason="end_turn"` và KHÔNG có `tool_calls` → `StepType.FINAL_ANSWER`. Nếu response có `tool_calls` → `StepType.TOOL_CALL`.

### 7.3 ErrorCategory

> Đã định nghĩa trong [`03-planning.md`](03-planning.md) Section 4.1.

**ErrorCategory** (str, Enum)

| Value | Description |
|-------|-------------|
| llm_rate_limit | LLM rate limit exceeded |
| llm_server_error | LLM server error |
| llm_content_refusal | LLM từ chối nội dung |
| llm_malformed_response | LLM response không hợp lệ |
| llm_timeout | LLM call timeout |
| tool_timeout | Tool call timeout |
| tool_auth_failure | Tool authentication failure |
| tool_execution_error | Tool execution error |
| checkpoint_write_fail | Checkpoint write failure |
| budget_exceeded | Budget đã vượt giới hạn |
| executor_crash | Executor crash |

### 7.4 DataSensitivity

> Đã định nghĩa trong [`09-governance.md`](09-governance.md) Section 4.3.1.

**DataSensitivity** (str, Enum)

| Value | Description |
|-------|-------------|
| public | Dữ liệu công khai |
| internal | Dữ liệu nội bộ |
| confidential | Dữ liệu bảo mật |
| restricted | PII, credentials, regulated data |

### 7.5 RiskLevel

**RiskLevel** (str, Enum)

| Value | Description |
|-------|-------------|
| low | Rủi ro thấp |
| medium | Rủi ro trung bình |
| high | Rủi ro cao |
| critical | Rủi ro nghiêm trọng |

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

**PlatformError** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| code | str | — | Machine-readable error code |
| message | str | — | Human-readable message |
| category | ErrorCategory \| None | None | Error category |
| details | dict | {} | Structured error details |
| retryable | bool | False | Có thể retry không |
| trace_id | str \| None | None | OpenTelemetry trace ID |

### 9.2 Retry Policy Defaults

> Từ [`03-planning.md`](03-planning.md) Section 4.1.

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

**RetryPolicy** (BaseModel)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| max_retries | int | — | Số lần retry tối đa |
| backoff_base_seconds | float | 1.0 | Backoff base (giây) |
| backoff_multiplier | float | 2.0 | Backoff multiplier |
| backoff_max_seconds | float | 30.0 | Backoff max (giây) |

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

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | TEXT | PRIMARY KEY | UUID của tenant |
| name | TEXT | NOT NULL | Tên tenant |
| slug | TEXT | NOT NULL, UNIQUE | URL-friendly identifier |
| config | JSONB | NOT NULL, DEFAULT '{}' | Cấu hình tenant (TenantConfig) |
| status | TEXT | NOT NULL, DEFAULT 'active', CHECK IN ('active', 'suspended', 'deleted') | Trạng thái tenant |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Thời điểm tạo |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Thời điểm cập nhật |

### 10.2 agents

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | TEXT | NOT NULL (part of composite PK) | UUID của agent |
| tenant_id | TEXT | NOT NULL, FK -> tenants(id) (part of composite PK) | ID của tenant |
| name | TEXT | NOT NULL | Tên agent |
| description | TEXT | DEFAULT '' | Mô tả agent |
| system_prompt | TEXT | NOT NULL | System prompt |
| model_config | JSONB | NOT NULL | ModelConfig |
| execution_config | JSONB | NOT NULL | ExecutionConfig |
| memory_config | JSONB | NOT NULL | MemoryConfig |
| guardrails_config | JSONB | NOT NULL | GuardrailsConfig |
| tools_config | JSONB | NOT NULL | AgentToolsConfig |
| status | TEXT | NOT NULL, DEFAULT 'draft', CHECK IN ('draft', 'active', 'archived') | Trạng thái agent |
| created_by | TEXT | NOT NULL | user_id của người tạo |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Thời điểm tạo |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Thời điểm cập nhật |

- **Primary Key:** (tenant_id, id)
- **RLS:** Enabled, policy `tenant_isolation` — `USING (tenant_id = current_setting('app.current_tenant'))`
- **Index:** `idx_agents_tenant_status` ON (tenant_id, status)

### 10.3 sessions

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | TEXT | NOT NULL (part of composite PK) | UUID của session |
| tenant_id | TEXT | NOT NULL (part of composite PK) | ID của tenant |
| agent_id | TEXT | NOT NULL | ID của agent |
| state | TEXT | NOT NULL, DEFAULT 'created', CHECK IN ('created', 'running', 'paused', 'waiting_input', 'completed', 'failed') | Trạng thái session |
| step_index | INT | NOT NULL, DEFAULT 0 | Bước hiện tại |
| usage | JSONB | NOT NULL, DEFAULT '{}' | SessionUsage |
| created_by | TEXT | NOT NULL | user_id hoặc api_key_id |
| user_type | TEXT | NOT NULL, DEFAULT 'builder', CHECK IN ('builder', 'end_user') | Loại user |
| metadata | JSONB | NOT NULL, DEFAULT '{}' | Metadata bổ sung |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Thời điểm tạo |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Thời điểm cập nhật |
| completed_at | TIMESTAMPTZ | (nullable) | Thời điểm kết thúc |
| ttl_seconds | INT | NOT NULL, DEFAULT 3600 | Session timeout |

- **Primary Key:** (tenant_id, id)
- **Foreign Key:** `fk_agent` — (tenant_id, agent_id) REFERENCES agents(tenant_id, id)
- **RLS:** Enabled, policy `tenant_isolation` — `USING (tenant_id = current_setting('app.current_tenant'))`
- **Indexes:**
  - `idx_sessions_agent` ON (tenant_id, agent_id, state)
  - `idx_sessions_state` ON (tenant_id, state, created_at DESC)
  - `idx_sessions_created` ON (tenant_id, created_at DESC)

### 10.4 messages

> Conversation history durable storage. Hot copy cũng lưu trong Redis.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | TEXT | NOT NULL (part of composite PK) | UUID của message |
| tenant_id | TEXT | NOT NULL (part of composite PK) | ID của tenant |
| session_id | TEXT | NOT NULL (part of composite PK) | ID của session |
| role | TEXT | NOT NULL, CHECK IN ('user', 'assistant', 'system', 'tool') | Vai trò của message |
| content | TEXT | NOT NULL | Nội dung message |
| tool_call_id | TEXT | (nullable) | ID liên kết với ToolCall |
| tool_calls | JSONB | (nullable) | list[ToolCall] as JSON |
| tokens | INT | (nullable) | Số tokens |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Thời điểm tạo |

- **Primary Key:** (tenant_id, session_id, id)
- **Foreign Key:** `fk_session` — (tenant_id, session_id) REFERENCES sessions(tenant_id, id) ON DELETE CASCADE
- **RLS:** Enabled, policy `tenant_isolation` — `USING (tenant_id = current_setting('app.current_tenant'))`
- **Index:** `idx_messages_session` ON (tenant_id, session_id, created_at)

### 10.5 checkpoints_deltas

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| session_id | TEXT | NOT NULL (part of composite PK) | ID của session |
| tenant_id | TEXT | NOT NULL (part of composite PK) | ID của tenant |
| step_index | INT | NOT NULL (part of composite PK) | Index của step |
| new_messages | JSONB | NOT NULL, DEFAULT '[]' | Messages mới trong step |
| tool_results | JSONB | (nullable) | Tool results |
| metadata_updates | JSONB | NOT NULL, DEFAULT '{}' | Metadata updates |
| usage_delta | JSONB | NOT NULL, DEFAULT '{}' | StepUsage |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Thời điểm tạo |

- **Primary Key:** (tenant_id, session_id, step_index)
- **Foreign Key:** `fk_session` — (tenant_id, session_id) REFERENCES sessions(tenant_id, id) ON DELETE CASCADE
- **RLS:** Enabled, policy `tenant_isolation` — `USING (tenant_id = current_setting('app.current_tenant'))`

### 10.6 checkpoints_snapshots

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| session_id | TEXT | NOT NULL (part of composite PK) | ID của session |
| tenant_id | TEXT | NOT NULL (part of composite PK) | ID của tenant |
| step_index | INT | NOT NULL (part of composite PK) | Index của step |
| state | BYTEA | NOT NULL | Serialized Session |
| conversation_hash | TEXT | NOT NULL | Integrity check |
| usage | JSONB | NOT NULL, DEFAULT '{}' | SessionUsage |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Thời điểm tạo |

- **Primary Key:** (tenant_id, session_id, step_index)
- **Foreign Key:** `fk_session` — (tenant_id, session_id) REFERENCES sessions(tenant_id, id) ON DELETE CASCADE
- **RLS:** Enabled, policy `tenant_isolation` — `USING (tenant_id = current_setting('app.current_tenant'))`

### 10.7 tools

> Đã định nghĩa trong [`06-mcp-tools.md`](06-mcp-tools.md) Section 2.1.1. Xem doc gốc cho full DDL.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | TEXT | NOT NULL (part of composite PK) | UUID của tool |
| tenant_id | TEXT | NOT NULL (part of composite PK) | ID của tenant |
| server_id | TEXT | NOT NULL | ID của MCP server |
| name | TEXT | NOT NULL | Tên tool |
| namespace | TEXT | NOT NULL | Namespace |
| description | TEXT | NOT NULL | Mô tả tool |
| input_schema | JSONB | NOT NULL | JSON Schema cho input |
| output_schema | JSONB | (nullable) | JSON Schema cho output |
| execution_mode | TEXT | DEFAULT 'sync' | Chế độ thực thi |
| default_timeout_ms | INT | DEFAULT 30000 | Timeout mặc định (ms) |
| estimated_latency_ms | INT | (nullable) | Latency ước tính (ms) |
| estimated_cost | FLOAT | (nullable) | Chi phí ước tính |
| idempotent | BOOLEAN | DEFAULT FALSE | Tool có idempotent không |
| permission_scope | TEXT[] | DEFAULT '{}' | Permission scopes |
| risk_level | TEXT | DEFAULT 'low' | Mức rủi ro |
| requires_approval | BOOLEAN | DEFAULT FALSE | Cần approval không |
| visibility | TEXT | DEFAULT 'tenant' | Phạm vi hiển thị |
| discovered_at | TIMESTAMPTZ | DEFAULT NOW() | Thời điểm phát hiện |
| last_verified_at | TIMESTAMPTZ | DEFAULT NOW() | Thời điểm verify cuối |
| status | TEXT | DEFAULT 'active' | Trạng thái tool |

- **Primary Key:** (tenant_id, id)
- **Foreign Key:** `fk_server` — (tenant_id, server_id) REFERENCES mcp_servers(tenant_id, id)
- **RLS:** Enabled, policy `tenant_isolation` — `USING (tenant_id = current_setting('app.current_tenant'))`
- **Index:** `idx_tools_namespace` ON (tenant_id, namespace)

### 10.8 mcp_servers

> Đã định nghĩa trong [`06-mcp-tools.md`](06-mcp-tools.md) Section 2.2.2. Xem doc gốc cho full DDL.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | TEXT | NOT NULL (part of composite PK) | UUID của MCP server |
| tenant_id | TEXT | NOT NULL, FK -> tenants(id) (part of composite PK) | ID của tenant |
| name | TEXT | NOT NULL | Tên server |
| description | TEXT | (nullable) | Mô tả server |
| transport | TEXT | NOT NULL, CHECK IN ('stdio', 'sse', 'streamable_http') | Loại transport |
| command | TEXT | (nullable) | Command (cho stdio) |
| args | JSONB | (nullable) | Arguments (cho stdio) |
| env_encrypted | BYTEA | (nullable) | Environment variables (encrypted) |
| url | TEXT | (nullable) | URL (cho sse/streamable_http) |
| headers_encrypted | BYTEA | (nullable) | Headers (encrypted) |
| connect_timeout_ms | INT | DEFAULT 10000 | Connection timeout (ms) |
| request_timeout_ms | INT | DEFAULT 30000 | Request timeout (ms) |
| max_retries | INT | DEFAULT 3 | Số lần retry tối đa |
| auto_start | BOOLEAN | DEFAULT TRUE | Tự động start |
| health_check_interval_seconds | INT | DEFAULT 60 | Khoảng cách health check (giây) |
| allowed_tools | TEXT[] | (nullable) | Whitelist tools |
| blocked_tools | TEXT[] | (nullable) | Blacklist tools |
| sandbox_level | TEXT | DEFAULT 'none' | Mức sandbox |
| status | TEXT | DEFAULT 'disconnected' | Trạng thái kết nối |
| last_connected_at | TIMESTAMPTZ | (nullable) | Thời điểm kết nối cuối |
| last_error | TEXT | (nullable) | Lỗi cuối cùng |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Thời điểm tạo |
| updated_at | TIMESTAMPTZ | DEFAULT NOW() | Thời điểm cập nhật |

- **Primary Key:** (tenant_id, id)
- **RLS:** Enabled, policy `tenant_isolation` — `USING (tenant_id = current_setting('app.current_tenant'))`

### 10.9 audit_events

> Đã định nghĩa trong [`09-governance.md`](09-governance.md) Section 4.1.3. Partitioned by month, append-only.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY, DEFAULT gen_random_uuid() | UUID của event |
| timestamp | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Thời điểm event |
| tenant_id | TEXT | NOT NULL | ID của tenant |
| agent_id | TEXT | (nullable) | ID của agent |
| session_id | TEXT | (nullable) | ID của session |
| step_index | INT | (nullable) | Index của step |
| category | TEXT | NOT NULL | Category of audit event |
| action | TEXT | NOT NULL | Action performed |
| actor_type | TEXT | NOT NULL | Loại actor |
| actor_id | TEXT | NOT NULL | ID của actor |
| actor_ip | INET | (nullable) | IP address của actor |
| resource_type | TEXT | (nullable) | Loại resource |
| resource_id | TEXT | (nullable) | ID của resource |
| details | JSONB | NOT NULL, DEFAULT '{}' | Chi tiết event |
| sensitivity | TEXT | NOT NULL, DEFAULT 'internal' | Mức độ nhạy cảm |
| outcome | TEXT | NOT NULL | Kết quả |
| created_date | DATE | GENERATED ALWAYS AS (DATE(timestamp)) STORED | Ngày tạo (partition key) |

- **Partitioning:** PARTITION BY RANGE (created_date)
- **Append-only constraint:** Trigger `audit_immutable` chạy function `prevent_audit_mutation()` BEFORE UPDATE OR DELETE, raise exception "audit_events is append-only: UPDATE and DELETE are not allowed"
- **RLS:** Enabled, policy `tenant_isolation` — `USING (tenant_id = current_setting('app.current_tenant'))`
- **Indexes:**
  - `idx_audit_tenant_time` ON (tenant_id, timestamp DESC)
  - `idx_audit_session` ON (session_id, timestamp)
  - `idx_audit_category` ON (category, timestamp DESC)
  - `idx_audit_outcome` ON (outcome, timestamp DESC) WHERE outcome != 'success'

### 10.10 cost_events

> Đã định nghĩa trong [`09-governance.md`](09-governance.md) Section 4.4.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY, DEFAULT gen_random_uuid() | UUID của event |
| timestamp | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Thời điểm event |
| tenant_id | TEXT | NOT NULL | ID của tenant |
| agent_id | TEXT | NOT NULL | ID của agent |
| session_id | TEXT | NOT NULL | ID của session |
| step_index | INT | NOT NULL | Index của step |
| event_type | TEXT | NOT NULL, CHECK IN ('llm_call', 'tool_call', 'embedding') | Loại cost event |
| provider | TEXT | (nullable) | Provider name |
| model | TEXT | (nullable) | Model name |
| input_tokens | INT | (nullable) | Số input tokens |
| output_tokens | INT | (nullable) | Số output tokens |
| tool_name | TEXT | (nullable) | Tên tool |
| cost_usd | NUMERIC(10, 6) | NOT NULL | Chi phí (USD) |

- **RLS:** Enabled, policy `tenant_isolation` — `USING (tenant_id = current_setting('app.current_tenant'))`
- **Indexes:**
  - `idx_cost_session` ON (session_id, timestamp)
  - `idx_cost_tenant_time` ON (tenant_id, timestamp DESC)

### 10.11 cost_daily_aggregates

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| date | DATE | NOT NULL (part of composite PK) | Ngày |
| tenant_id | TEXT | NOT NULL (part of composite PK) | ID của tenant |
| agent_id | TEXT | (part of composite PK) | ID của agent |
| provider | TEXT | (part of composite PK) | Provider name |
| model | TEXT | (part of composite PK) | Model name |
| total_cost_usd | NUMERIC(12, 6) | (nullable) | Tổng chi phí (USD) |
| total_llm_calls | INT | (nullable) | Tổng số LLM calls |
| total_tool_calls | INT | (nullable) | Tổng số tool calls |
| total_input_tokens | BIGINT | (nullable) | Tổng input tokens |
| total_output_tokens | BIGINT | (nullable) | Tổng output tokens |

- **Primary Key:** (date, tenant_id, agent_id, provider, model)

### 10.12 memories

> Phase 2. Đã định nghĩa trong [`05-memory.md`](05-memory.md) Section 3.4.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY, DEFAULT gen_random_uuid() | UUID của memory |
| tenant_id | TEXT | NOT NULL, FK -> tenants(id) | ID của tenant |
| agent_id | TEXT | NOT NULL | ID của agent |
| namespace | TEXT | NOT NULL, DEFAULT 'default' | Namespace |
| content | TEXT | NOT NULL | Nội dung memory |
| content_type | TEXT | DEFAULT 'text', CHECK IN ('text', 'structured', 'code') | Loại content |
| embedding | VECTOR(1536) | NOT NULL | Vector embedding |
| metadata | JSONB | DEFAULT '{}' | Metadata bổ sung |
| source | TEXT | (nullable) | Nguồn gốc |
| tags | TEXT[] | DEFAULT '{}' | Tags |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Thời điểm tạo |
| updated_at | TIMESTAMPTZ | DEFAULT NOW() | Thời điểm cập nhật |
| expires_at | TIMESTAMPTZ | (nullable) | Thời điểm hết hạn |
| access_count | INT | DEFAULT 0 | Số lần truy cập |
| last_accessed_at | TIMESTAMPTZ | (nullable) | Thời điểm truy cập cuối |

- **RLS:** Enabled, policy `tenant_isolation` — `USING (tenant_id = current_setting('app.current_tenant'))`
- **Indexes:**
  - `idx_memories_embedding` ON embedding USING hnsw (vector_cosine_ops) WITH (m = 16, ef_construction = 64)
  - `idx_memories_scope` ON (tenant_id, agent_id, namespace)

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
