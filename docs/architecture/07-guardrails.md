# Thiết Kế Chi Tiết: Guardrails Engine

> **Phiên bản:** 1.1
> **Ngày tạo:** 2026-03-25
> **Parent:** [Architecture Overview](00-overview.md)

---

## 1. High-Level Diagram

```
┌─────────────────────────────── GUARDRAILS ENGINE ──────────────────────────────────┐
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         INBOUND PIPELINE                                     │   │
│  │                                                                              │   │
│  │   User Input ──→ ┌────────────┐ ──→ ┌────────────┐ ──→ ┌──────────────┐    │   │
│  │                   │ Schema     │     │ Content    │     │ Injection    │    │   │
│  │                   │ Validator  │     │ Filter     │     │ Detector     │    │   │
│  │                   │ [Hard]     │     │ [Soft]     │     │ [Soft+CB]    │    │   │
│  │                   └────────────┘     └────────────┘     └──────┬───────┘    │   │
│  │                                                                 │            │   │
│  └─────────────────────────────────────────────────────────────────┼────────────┘   │
│                                                                     │                │
│  ┌──────────────────────────────────────────────────────────────────▼────────────┐  │
│  │                         POLICY ENGINE                                         │  │
│  │                                                                               │  │
│  │   ┌─────────────────┐   ┌─────────────────┐   ┌────────────────────────┐     │  │
│  │   │ Tool Permission  │   │ Budget           │   │ Rate Limit             │     │  │
│  │   │ Enforcer [Hard]  │   │ Enforcer [Hard]  │   │ Enforcer [Hard]        │     │  │
│  │   │                 │   │                   │   │                        │     │  │
│  │   │ - Agent-level   │   │ - Token budget    │   │ - Per-tenant           │     │  │
│  │   │ - Tenant-level  │   │ - Cost budget     │   │ - Per-agent            │     │  │
│  │   │ - Action-level  │   │ - Time budget     │   │ - Per-tool             │     │  │
│  │   └─────────────────┘   └─────────────────┘   └────────────────────────┘     │  │
│  │                                                                               │  │
│  │   ┌─────────────────┐   ┌─────────────────┐                                  │  │
│  │   │ HITL Gate        │   │ Custom Rule      │                                  │  │
│  │   │ [Configurable]   │   │ Engine [Soft]    │                                  │  │
│  │   │                  │   │ (Phase 2)        │                                  │  │
│  │   └─────────────────┘   └─────────────────┘                                  │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│                                                                     │                │
│  ┌──────────────────────────────────────────────────────────────────▼────────────┐  │
│  │                         OUTBOUND PIPELINE                                     │  │
│  │                                                                               │  │
│  │   LLM Output ──→ ┌────────────┐ ──→ ┌────────────┐ ──→ ┌──────────────┐     │  │
│  │                   │ Response   │     │ PII        │     │ Canary       │     │  │
│  │                   │ Filter     │     │ Detector   │     │ Monitor      │     │  │
│  │                   │ [Soft]     │     │ [Soft]     │     │ [Soft]       │     │  │
│  │                   └────────────┘     └────────────┘     └──────────────┘     │  │
│  │                                                                               │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                     │
│  ┌──────────────────────────────────────────────────────────────────────────────┐  │
│  │                         AUDIT TRAIL                                          │  │
│  │   Mọi check → result (pass/fail/warn) → immutable log                       │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Guardrail Classification

| Type | Behavior | Failure Mode | Components |
|------|----------|-------------|------------|
| **Hard** (fail-closed) | Phải pass, stateless, in-process | Service unavailable → reject request | Schema Validator, Tool Permission, Budget Enforcer |
| **Soft** (fail-open) | Best-effort, degrade gracefully | Service unavailable → allow + log warning | Content Filter, Injection Detector, PII Detector, Canary Monitor |

Hard guardrails: zero external dependency, sub-ms, không có lý do để fail.
Soft guardrails: có thể depend external service hoặc model inference, chấp nhận degrade.

### Circuit Breaker cho Soft Guardrails

**GuardrailCircuitBreaker** — Circuit breaker cho soft guardrails, quản lý ba trạng thái: CLOSED (hoạt động bình thường) → OPEN (bypass guardrail) → HALF_OPEN (thử nghiệm phục hồi).

**Thuộc tính cấu hình:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| failure_threshold | int | 5 | Số lần thất bại liên tiếp để chuyển sang OPEN |
| recovery_timeout_seconds | int | 60 | Thời gian ở trạng thái OPEN trước khi thử HALF_OPEN |
| half_open_max_calls | int | 3 | Số lần gọi thử nghiệm trong trạng thái HALF_OPEN |

**Phương thức:**

- **execute(check_fn: Callable, fallback: GuardrailResult) -> GuardrailResult** (async): Nếu CLOSED, chạy check_fn bình thường. Nếu OPEN, trả về fallback (cho phép + ghi log). Nếu HALF_OPEN, chạy check_fn và theo dõi thành công/thất bại.

---

## 2. Component Descriptions

### 2.1 Inbound Pipeline

#### 2.1.1 Schema Validator — Hard Guardrail (Phase 1)

| Kiểm tra | Chi tiết |
|----------|----------|
| Message format | Đúng cấu trúc `{role, content}`, role hợp lệ |
| Content length | Không vượt quá max allowed tokens cho agent |
| Character encoding | UTF-8 hợp lệ, không có control characters nguy hiểm |
| Attachment validation | File type, size trong allowlist |

**SchemaValidator** — Lớp thực hiện kiểm tra tính hợp lệ của input đầu vào.

- **validate(input: AgentInput, agent_config: AgentConfig) -> ValidationResult** (async): Trả về ValidationResult với trường passed (bool) và violations (list[Violation]). Nếu validation thất bại, trả về 400 Bad Request và không gọi LLM.

#### 2.1.2 Content Filter — Soft Guardrail (Phase 2)

| Mode | Hành vi |
|------|---------|
| **Block** | Reject input, trả error cho client |
| **Warn** | Cho qua nhưng log warning + emit event |
| **Redact** | Xóa/thay thế phần vi phạm, tiếp tục xử lý |

**ContentFilter** — Lớp lọc nội dung dựa trên chính sách.

- **check(content: str, policy: ContentPolicy) -> FilterResult** (async): Nhận nội dung và chính sách lọc. Chính sách bao gồm blocked_categories (danh sách như "hate_speech", "self_harm", "explicit") và mode ("block", "warn", hoặc "redact").

#### 2.1.3 Prompt Injection Detector — Soft Guardrail + Circuit Breaker

| Strategy | Precision | Recall | Phase |
|----------|-----------|--------|-------|
| **Heuristic rules** | Trung bình | Thấp | **1** |
| **Delimiter analysis** | Cao | Thấp | **1** |
| **Classifier model** | Cao | Cao | **2** |
| **Canary tokens** | Rất cao | N/A (detection) | **2** |

**InjectionDetector** — Lớp phát hiện prompt injection.

- **detect(user_input: str, system_prompt: str) -> DetectionResult** (async): Trả về DetectionResult bao gồm các trường: is_injection (bool), confidence (float, 0.0 - 1.0), strategy_triggered (str — cho biết detection layer nào đã phát hiện), và details (str).

**Ngưỡng xử lý Phase 1** (chỉ heuristic + delimiter): Match found thì BLOCK (reject ngay), No match thì PASS.

**Ngưỡng xử lý Phase 2** (thêm classifier + canary):

| Confidence | Hành động |
|------------|-----------|
| >= 0.9 | BLOCK — reject ngay lập tức |
| >= 0.7 | ESCALATE — log + đưa vào hàng đợi human review |
| >= 0.5 | WARN — log warning, tiếp tục xử lý với extra monitoring |
| < 0.5 | PASS |

---

### 2.2 Policy Engine

#### 2.2.1 Tool Permission Enforcer — Hard Guardrail (Phase 1)

```
┌─────────────────────────────────────────────┐
│ Tenant Policy                                │
│   └─ Agent Policy                            │
│       └─ Session Policy                      │
│           └─ Action Policy                   │
└─────────────────────────────────────────────┘
```

**ToolPermission** — Data model mô tả quyền truy cập tool.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| tool_pattern | str | (bắt buộc) | Pattern để match tool, ví dụ "mcp:database:*", "mcp:github:create_issue" |
| actions | list[str] | (bắt buộc) | Danh sách hành động được phép, ví dụ ["invoke"], ["invoke", "configure"] |
| constraints | PermissionConstraints | (bắt buộc) | Các ràng buộc chi tiết cho quyền |

**PermissionConstraints** — Data model mô tả các ràng buộc cho quyền tool.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| max_calls_per_session | int hoặc None | None | Số lần gọi tối đa mỗi session. None = không giới hạn |
| max_calls_per_minute | int hoặc None | None | Số lần gọi tối đa mỗi phút |
| max_cost_per_call | float hoặc None | None | Chi phí tối đa cho mỗi lần gọi (USD) |
| requires_approval | bool | (bắt buộc) | Có yêu cầu HITL gate hay không |
| allowed_parameters | dict hoặc None | None | JSONSchema subset mô tả các tham số được phép |
| denied_parameters | dict hoặc None | None | JSONSchema mô tả các tham số bị cấm rõ ràng |
| time_window | str hoặc None | None | Cửa sổ thời gian, ví dụ "business_hours_only" |

**ToolPermissionEnforcer** — Lớp kiểm tra quyền truy cập tool.

- **check(tool_call: ToolCall, agent_permissions: list[ToolPermission], session_context: SessionContext) -> PermissionResult** (async): Trả về ALLOW, DENY(reason), hoặc REQUIRE_APPROVAL(approver).

**Thứ tự đánh giá:**

1. Tool có nằm trong danh sách allowed tools của agent không? → DENY nếu không
2. Các tham số có nằm trong allowed constraints không? → DENY nếu không
3. Rate limit có bị vượt quá không? → DENY nếu có
4. Cost limit có bị vượt quá không? → DENY nếu có
5. Tool này có yêu cầu HITL approval không? → REQUIRE_APPROVAL nếu có
6. → ALLOW

#### 2.2.2 Budget Enforcer — Hard Guardrail (Phase 1)

| Budget Type | Scope | Kiểm tra |
|-------------|-------|----------|
| **Token budget** | Per-session | Total tokens consumed < max_tokens |
| **Cost budget** | Per-session, per-agent, per-tenant | Estimated USD cost < max_cost |
| **Step budget** | Per-session | Number of reasoning steps < max_steps |
| **Time budget** | Per-session | Wall-clock duration < max_duration |

**BudgetEnforcer** — Lớp kiểm soát ngân sách sử dụng.

- **check(session: Session, next_action: Action) -> BudgetResult** (async): Trước mỗi lần gọi LLM hoặc thực thi tool, thực hiện: (1) Tính toán mức sử dụng hiện tại (tokens, cost, steps, time); (2) Ước lượng chi phí hành động tiếp theo; (3) Nếu current + estimated > budget: inject "wrap up" instruction khi >= 90%, DENY và buộc kết thúc khi >= 100%.

- **estimate_cost(action: Action) -> CostEstimate** (async): Ước tính tokens cho lần gọi LLM tiếp theo dựa trên: context length hiện tại, độ dài completion trung bình cho agent này, và chi phí thực thi tool (nếu có).

```
Budget at 80%  → Log warning
Budget at 90%  → Inject instruction: "Bạn sắp hết budget. Hãy tóm tắt kết quả hiện tại."
Budget at 95%  → Inject instruction: "Đây là bước cuối cùng. Trả kết quả ngay."
Budget at 100% → Force stop, return partial result
```

#### 2.2.3 Rate Limit Enforcer — Hard Guardrail (Phase 1)

| Dimension | Default | Configurable |
|-----------|---------|-------------|
| LLM calls per minute per session | 30 | Yes |
| Tool calls per minute per session | 60 | Yes |
| LLM calls per minute per tenant | 300 | Yes |
| Concurrent sessions per tenant | 100 | Yes |

Token bucket algorithm trên Redis.

#### 2.2.4 Human-in-the-Loop (HITL) Gate — Configurable (Phase 1)

**HITLGate** — Lớp quản lý quy trình phê duyệt từ con người.

- **request_approval(session_id: str, action: ToolCall, reason: str, timeout_seconds: int = 3600) -> ApprovalResult** (async): Thực hiện các bước: (1) Set session state sang WAITING_INPUT; (2) Emit approval_requested event qua WebSocket + webhook; (3) Lưu pending approval vào DB; (4) Chờ human response (approve/reject/modify) hoặc timeout; (5) Trả về result để executor tiếp tục hoặc hủy.

**Approval payload:** Cấu trúc dữ liệu gửi đến người phê duyệt:

| Field | Type | Description |
|-------|------|-------------|
| approval_id | string (uuid) | ID duy nhất cho yêu cầu phê duyệt |
| session_id | string (uuid) | ID session liên quan |
| agent_name | string | Tên agent, ví dụ "customer-support-v2" |
| action.tool | string | Tên tool cần phê duyệt, ví dụ "mcp:database:execute_query" |
| action.parameters | object | Tham số của tool call, ví dụ { "query": "UPDATE users SET status='active' WHERE id=123" } |
| reason | string | Lý do cần phê duyệt, ví dụ "Tool 'execute_query' requires approval for write operations" |
| context_summary | string | Tóm tắt ngữ cảnh, ví dụ "Agent đang xử lý yêu cầu kích hoạt tài khoản user #123" |
| options | list[string] | Các lựa chọn: ["approve", "reject", "modify"] |
| expires_at | string (ISO 8601) | Thời điểm hết hạn, ví dụ "2026-03-25T15:30:00Z" |

#### 2.2.5 Custom Rule Engine — Soft Guardrail (Phase 2)

**GuardrailRule** — Data model mô tả một rule tùy chỉnh.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | (bắt buộc) | ID duy nhất của rule |
| name | str | (bắt buộc) | Tên rule |
| description | str | (bắt buộc) | Mô tả rule |
| trigger | str | (bắt buộc) | Thời điểm kích hoạt: "before_llm_call", "before_tool_call", hoặc "after_llm_call" |
| condition | str | (bắt buộc) | Biểu thức CEL (Common Expression Language) |
| action | str | (bắt buộc) | Hành động khi match: "block", "warn", "require_approval", hoặc "modify" |
| priority | int | (bắt buộc) | Độ ưu tiên, số thấp hơn được đánh giá trước |
| enabled | bool | (bắt buộc) | Rule có đang bật hay không |

**Ví dụ các rules:**

| Rule Name | Trigger | Condition (CEL) | Action |
|-----------|---------|-----------------|--------|
| no_delete_in_prod | before_tool_call | tool.name == "database:execute" AND input.query chứa "DELETE" AND env == "production" | block |
| large_data_approval | before_tool_call | tool.name == "database:execute" AND estimated_rows > 10000 | require_approval |
| notify_on_external_api | before_tool_call | tool.namespace bắt đầu bằng "mcp:external" | warn |

---

### 2.3 Outbound Pipeline

#### 2.3.1 Response Filter — Soft Guardrail (Phase 2)

| Kiểm tra | Hành vi |
|----------|---------|
| Toxic/harmful content trong response | Block + log |
| Off-topic response (agent deviation) | Warn + log |
| Hallucination indicators | Warn (khi confidence thấp) |
| Response length limit | Truncate + warn |

#### 2.3.2 PII Detector — Soft Guardrail (Phase 2)

| PII Type | Pattern | Mask |
|----------|---------|------|
| Email | regex | `***@***.com` |
| Phone | regex | `***-***-1234` |
| SSN | regex | `***-**-6789` |
| Credit card | regex + Luhn | `****-****-****-1234` |
| Name (optional) | NER model | `[PERSON]` |
| Address (optional) | NER model | `[ADDRESS]` |

**PIIDetector** — Lớp phát hiện và che giấu thông tin cá nhân (PII).

- **scan_and_mask(text: str, policy: PIIPolicy) -> PIIScanResult** (async): Nhận văn bản và chính sách PII. Chính sách bao gồm mode ("detect_only", "mask_in_response", "mask_in_logs", hoặc "mask_all") và types (danh sách loại PII cần phát hiện, ví dụ ["email", "phone", "ssn", "credit_card"]). Trả về PIIScanResult gồm: original_text (str), masked_text (str), và detections (list[PIIDetection] — mỗi detection gồm type, span, confidence).

#### 2.3.3 Canary Monitor — Soft Guardrail (Phase 2)

**CanaryMonitor** — Lớp giám sát canary tokens để phát hiện rò rỉ system prompt.

- **inject_canary(system_prompt: str, session_id: str) -> tuple[str, str]**: Tạo canary token duy nhất từ session_id, thêm marker dạng "[SYSTEM_INTEGRITY_TOKEN: {canary}]" vào cuối system prompt. Trả về tuple gồm (modified_prompt, canary_token).

- **check_output(output: str, canary_token: str) -> bool**: Kiểm tra output có chứa canary token không. Trả về True nếu canary bị rò rỉ trong output, khi đó cần phát ALERT.

---

### 2.4 Audit Trail

**GuardrailAuditEntry** — Data model cho mỗi bản ghi kiểm toán guardrail.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | (bắt buộc) | ID duy nhất của bản ghi |
| timestamp | datetime | (bắt buộc) | Thời điểm kiểm tra |
| session_id | str | (bắt buộc) | ID session liên quan |
| tenant_id | str | (bắt buộc) | ID tenant |
| agent_id | str | (bắt buộc) | ID agent |
| step_index | int | (bắt buộc) | Chỉ số bước trong session |
| check_type | str | (bắt buộc) | Loại kiểm tra, ví dụ "schema_validation", "injection_detection", "tool_permission", v.v. |
| check_name | str | (bắt buộc) | Tên cụ thể của bước kiểm tra |
| result | str | (bắt buộc) | Kết quả: "pass", "fail", "warn", hoặc "require_approval" |
| details | dict | (bắt buộc) | Chi tiết bổ sung |
| action_taken | str | (bắt buộc) | Hành động đã thực hiện: "allowed", "blocked", "masked", hoặc "escalated" |
| latency_ms | float | (bắt buộc) | Thời gian xử lý (mili-giây) |

PostgreSQL append-only table (no UPDATE/DELETE allowed).

---

## 3. Sequence Diagrams

### 3.1 Inbound Guardrails Flow (User Input → LLM)

```
User            API GW         Guardrails Engine                              LLM GW
 │                │                │                                            │
 │──message──────→│                │                                            │
 │                │──validate──→   │                                            │
 │                │              ┌─▼──────────────┐                            │
 │                │              │ Schema Validator │                            │
 │                │              │ [Hard] pass/fail │                            │
 │                │              └─┬──────────────┘                            │
 │                │              ┌─▼──────────────┐                            │
 │                │              │ Content Filter  │                            │
 │                │              │ [Soft] pass/warn │                            │
 │                │              └─┬──────────────┘                            │
 │                │              ┌─▼──────────────────┐                        │
 │                │              │ Injection Detector   │                        │
 │                │              │ [Soft+CB] pass/fail  │                        │
 │                │              └─┬──────────────────┘                        │
 │                │              ┌─▼──────────────┐                            │
 │                │              │ Budget Check    │                            │
 │                │              │ [Hard] pass/fail │                            │
 │                │              └─┬──────────────┘                            │
 │                │                │                                            │
 │                │                │──ALL PASSED──→ forward to executor ──────→│
 │                │                │                                            │
 │                │                │──audit log (entries)──→ Trace Store        │
 │                │                │                                            │
```

### 3.2 Tool Call Guardrails Flow (LLM → Tool)

```
Executor         Guardrails Engine                                    Tool Runtime
 │                    │                                                    │
 │──tool_call────────→│                                                    │
 │  {tool: "db:query" │                                                    │
 │   params: {...}}   │                                                    │
 │                  ┌─▼─────────────────┐                                 │
 │                  │ Tool Permission    │                                 │
 │                  │ [Hard] check       │                                 │
 │                  └─┬─────────────────┘                                 │
 │                  ┌─▼─────────────────┐                                 │
 │                  │ Rate Limit Check   │                                 │
 │                  │ [Hard] check       │                                 │
 │                  └─┬─────────────────┘                                 │
 │                  ┌─▼─────────────────┐                                 │
 │                  │ Custom Rules       │                                 │
 │                  │ [Soft] check       │                                 │
 │                  └─┬─────────────────┘                                 │
 │                  ┌─▼─────────────────┐                                 │
 │                  │ HITL Required?     │                                 │
 │                  │ [Configurable]     │                                 │
 │                  └─┬─────────────────┘                                 │
 │                    │                                                    │
 │                    │──ALLOW──→ forward ─────────────────────────────────→│
 │                    │                                                    │
 │                    │──audit log──→ Trace Store                          │
 │                    │                                                    │
```

### 3.3 HITL Approval Flow

```
Executor      Guardrails        Session Svc       Queue        Human         WebSocket
 │               │                  │                │            │              │
 │──tool_call───→│                  │                │            │              │
 │ {tool:"db:    │                  │                │            │              │
 │  delete"}     │                  │                │            │              │
 │             ┌─▼───────────┐     │                │            │              │
 │             │ Permission   │     │                │            │              │
 │             │ Check        │     │                │            │              │
 │             │ REQUIRE      │     │                │            │              │
 │             │   APPROVAL   │     │                │            │              │
 │             └─┬───────────┘     │                │            │              │
 │               │                  │                │            │              │
 │               │──set state──────→│                │            │              │
 │               │  WAITING_INPUT   │                │            │              │
 │               │                  │                │            │              │
 │               │──emit approval──→│────────────────│────────────│──notify─────→│
 │               │  _requested      │                │            │   (approval  │
 │               │                  │                │            │    request)  │
 │               │                  │                │            │              │
 │               │  ... executor paused, session state = WAITING_INPUT ...       │
 │               │                  │                │            │              │
 │               │                  │                │        ┌───▼────┐         │
 │               │                  │                │        │ Review │         │
 │               │                  │                │        │ action │         │
 │               │                  │                │        └───┬────┘         │
 │               │                  │                │            │              │
 │               │                  │◄──approve──────│◄───────────│              │
 │               │                  │                │            │              │
 │               │                  │──enqueue ─────→│            │              │
 │               │                  │  resume task   │            │              │
 │               │                  │                │            │              │
 │◄──────────────│◄─────────────────│◄───pull+resume─│            │              │
 │               │                  │                │            │              │
 │──execute tool─────────────────────────────────────────────────→ Tool Runtime  │
 │               │                  │                │            │              │
```

### 3.4 Outbound Guardrails Flow (LLM Response → Client)

```
LLM GW          Executor         Guardrails Engine                    Client
 │                │                    │                                 │
 │──response─────→│                    │                                 │
 │                │──check output─────→│                                 │
 │                │                  ┌─▼─────────────────┐              │
 │                │                  │ Response Filter    │              │
 │                │                  │ [Soft] check       │              │
 │                │                  └─┬─────────────────┘              │
 │                │                  ┌─▼─────────────────┐              │
 │                │                  │ PII Detector       │              │
 │                │                  │ [Soft] scan+mask   │              │
 │                │                  └─┬─────────────────┘              │
 │                │                  ┌─▼─────────────────┐              │
 │                │                  │ Canary Monitor     │              │
 │                │                  │ [Soft] check       │              │
 │                │                  └─┬─────────────────┘              │
 │                │                    │                                 │
 │                │◄──result───────────│                                 │
 │                │  (clean response)  │                                 │
 │                │                    │                                 │
 │                │──stream event──────│────────────────────────────────→│
 │                │                    │                                 │
 │                │                    │──audit log──→ Trace Store       │
```

---

## 4. Configuration Model

### 4.1 Agent-Level Guardrails Config

**GuardrailsConfig** — Cấu hình guardrails cấp agent, bao gồm ba nhóm:

**Inbound:**

| Field | Type | Description |
|-------|------|-------------|
| input_validation | InputValidationConfig | Cấu hình validation đầu vào |
| content_filtering | ContentFilterConfig | Cấu hình lọc nội dung |
| injection_detection | InjectionDetectionConfig | Cấu hình phát hiện injection |

**Policy:**

| Field | Type | Description |
|-------|------|-------------|
| tool_permissions | list[ToolPermission] | Danh sách quyền truy cập tool |
| budget | BudgetConfig | Cấu hình ngân sách |
| rate_limits | RateLimitConfig | Cấu hình giới hạn tốc độ |
| hitl_rules | list[HITLRule] | Danh sách rule HITL |
| custom_rules | list[GuardrailRule] | Danh sách rule tùy chỉnh |

**Outbound:**

| Field | Type | Description |
|-------|------|-------------|
| output_filtering | OutputFilterConfig | Cấu hình lọc output |
| pii_detection | PIIConfig | Cấu hình phát hiện PII |
| canary_enabled | bool | Bật/tắt canary monitoring |

**BudgetConfig** — Cấu hình ngân sách cho session.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| max_tokens_per_session | int | 50,000 | Số token tối đa mỗi session |
| max_cost_per_session_usd | float | 5.0 | Chi phí tối đa mỗi session (USD) |
| max_steps_per_session | int | 50 | Số bước tối đa mỗi session |
| max_duration_seconds | int | 600 | Thời lượng tối đa mỗi session (giây) |
| warning_threshold | float | 0.8 | Ngưỡng 80% để inject warning |
| critical_threshold | float | 0.95 | Ngưỡng 95% để buộc kết thúc |

**InjectionDetectionConfig** — Cấu hình phát hiện prompt injection.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | True | Bật/tắt phát hiện injection |
| strategies | list[str] | ["heuristic", "classifier"] | Các chiến lược phát hiện |
| block_threshold | float | 0.9 | Ngưỡng confidence để block |
| escalate_threshold | float | 0.7 | Ngưỡng confidence để escalate |
| warn_threshold | float | 0.5 | Ngưỡng confidence để warn |
| classifier_model | str | "guardrail-injection-v1" | ID model nội bộ dùng để classify |

### 4.2 Example Agent Definition with Guardrails

Ví dụ cấu hình guardrails cho agent "customer-support-v2":

**Thông tin chung:** agent_id = "customer-support-v2"

**Input validation:** max_message_length = 4000, allowed_content_types = ["text"]

**Content filtering:** mode = "block", categories = ["hate_speech", "self_harm"]

**Injection detection:** enabled = true, block_threshold = 0.85

**Tool permissions:**

| Tool Pattern | Actions | Constraints |
|-------------|---------|-------------|
| mcp:crm:read_* | ["invoke"] | (không có ràng buộc thêm) |
| mcp:crm:update_* | ["invoke"] | requires_approval = false |
| mcp:crm:delete_* | ["invoke"] | requires_approval = true |
| mcp:email:send | ["invoke"] | max_calls_per_session = 3 |

**Budget:** max_tokens_per_session = 30000, max_cost_per_session_usd = 2.0, max_steps = 20

**PII detection:** mode = "mask_in_logs", types = ["email", "phone", "ssn"]

**Canary:** canary_enabled = true

---

## 5. Tech Stack

| Component | Technology | Phase |
|-----------|-----------|-------|
| **Pipeline framework** | Python async middleware chain | 1 |
| **Schema validation** | Pydantic v2 | 1 |
| **Injection detection (heuristic)** | Regex + custom patterns | 1 |
| **Injection detection (classifier)** | Distil-BERT fine-tuned (ONNX) | 2 |
| **Content filtering** | OpenAI Moderation API / local model | 2 |
| **PII detection** | Presidio (Microsoft, OSS) | 2 |
| **Rate limiting** | Redis + token bucket algorithm | 1 |
| **Budget tracking** | Redis (counters) + PostgreSQL (aggregates) | 1 |
| **Custom rule engine** | CEL (Common Expression Language) | 2 |
| **HITL notifications** | WebSocket + Webhook | 1 |
| **Audit storage** | PostgreSQL (append-only table) | 1 |
| **Advanced classifier** | Fine-tuned guardrail model (self-hosted) | 2 |

---

## 6. Performance Targets

| Check | Target Latency | Phase |
|-------|---------------|-------|
| Schema validation | < 1ms | 1 |
| Content filter (regex) | < 2ms | 2 |
| Content filter (model) | < 20ms | 2 |
| Injection detection (heuristic) | < 2ms | 1 |
| Injection detection (classifier) | < 10ms | 2 |
| Tool permission check | < 1ms | 1 |
| Budget check | < 2ms (Redis) | 1 |
| Rate limit check | < 1ms (Redis) | 1 |
| PII detection (Presidio) | < 15ms | 2 |
| Canary check | < 1ms | 2 |
| **Total inbound pipeline** | **< 20ms** | 1 |
| **Total outbound pipeline** | **< 20ms** | 1 |

---

## 7. Error Handling

| Scenario | Classification | Behavior |
|----------|---------------|----------|
| Schema validation failure | Hard | Reject request (400) |
| Tool permission denied | Hard | Block tool call, return error to LLM |
| Budget exceeded | Hard | Graceful termination |
| Injection detector timeout | Soft | Allow + log warning + emit alert event |
| Injection detector unavailable | Soft | Allow + log warning + circuit breaker opens |
| Content filter unavailable | Soft | Allow + log warning |
| PII detector unavailable | Soft | Allow + log warning (no masking) |
| Rate limit Redis unavailable | Hard | Use local cache (~1min stale) + log |
| HITL approval timeout | Configurable | Default: auto-reject |
| Custom rule evaluation error | Soft | Skip rule + warn + log |
