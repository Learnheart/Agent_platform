# Thiết Kế Chi Tiết: Guardrails Engine

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect
> **Parent:** [Architecture Overview](../00-overview.md)

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
│  │                   └────────────┘     └────────────┘     └──────┬───────┘    │   │
│  │                                                                 │            │   │
│  └─────────────────────────────────────────────────────────────────┼────────────┘   │
│                                                                     │                │
│  ┌──────────────────────────────────────────────────────────────────▼────────────┐  │
│  │                         POLICY ENGINE                                         │  │
│  │                                                                               │  │
│  │   ┌─────────────────┐   ┌─────────────────┐   ┌────────────────────────┐     │  │
│  │   │ Tool Permission  │   │ Budget           │   │ Rate Limit             │     │  │
│  │   │ Enforcer        │   │ Enforcer         │   │ Enforcer               │     │  │
│  │   │                 │   │                   │   │                        │     │  │
│  │   │ - Agent-level   │   │ - Token budget    │   │ - Per-tenant           │     │  │
│  │   │ - Tenant-level  │   │ - Cost budget     │   │ - Per-agent            │     │  │
│  │   │ - Action-level  │   │ - Time budget     │   │ - Per-tool             │     │  │
│  │   └─────────────────┘   └─────────────────┘   └────────────────────────┘     │  │
│  │                                                                               │  │
│  │   ┌─────────────────┐   ┌─────────────────┐                                  │  │
│  │   │ HITL Gate        │   │ Custom Rule      │                                  │  │
│  │   │ (Human-in-the-  │   │ Engine           │                                  │  │
│  │   │  Loop)           │   │ (User-defined)   │                                  │  │
│  │   └─────────────────┘   └─────────────────┘                                  │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│                                                                     │                │
│  ┌──────────────────────────────────────────────────────────────────▼────────────┐  │
│  │                         OUTBOUND PIPELINE                                     │  │
│  │                                                                               │  │
│  │   LLM Output ──→ ┌────────────┐ ──→ ┌────────────┐ ──→ ┌──────────────┐     │  │
│  │                   │ Response   │     │ PII        │     │ Canary       │     │  │
│  │                   │ Filter     │     │ Detector   │     │ Monitor      │     │  │
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

## 2. Component Descriptions

### 2.1 Inbound Pipeline

Chạy **trước** khi input được gửi đến LLM. Mỗi check là một middleware trong pipeline, xử lý tuần tự. Nếu bất kỳ check nào fail → request bị reject ngay, không gọi LLM.

#### 2.1.1 Schema Validator

**Mục đích:** Đảm bảo input tuân thủ format mong đợi trước khi đi sâu hơn.

| Kiểm tra | Chi tiết |
|----------|----------|
| Message format | Đúng cấu trúc `{role, content}`, role hợp lệ |
| Content length | Không vượt quá max allowed tokens cho agent |
| Character encoding | UTF-8 hợp lệ, không có control characters nguy hiểm |
| Attachment validation | File type, size trong allowlist |

```python
class SchemaValidator:
    async def validate(self, input: AgentInput, agent_config: AgentConfig) -> ValidationResult:
        """
        Returns: ValidationResult(passed=bool, violations=list[Violation])
        Nếu failed → return 400 Bad Request, không gọi LLM
        """
```

#### 2.1.2 Content Filter (Phase 2)

> **Phase note:** Đẩy sang Phase 2 sau review. Phase 1 personas (Marcus, Elena) cần budget limits + tool permissions, không cần content classification. Regex-based keyword blocking đủ cho Phase 1 nếu cần — nằm trong Schema Validator.

**Mục đích:** Lọc nội dung vi phạm policy (toxic, NSFW, off-topic) trước khi đến LLM.

| Mode | Hành vi |
|------|---------|
| **Block** | Reject input, trả error cho client |
| **Warn** | Cho qua nhưng log warning + emit event |
| **Redact** | Xóa/thay thế phần vi phạm, tiếp tục xử lý |

**Implementation:** Sử dụng lightweight classifier model (distilbert-based hoặc regex patterns cho Phase 1, specialized model cho Phase 2).

```python
class ContentFilter:
    async def check(self, content: str, policy: ContentPolicy) -> FilterResult:
        """
        policy.blocked_categories: ["hate_speech", "self_harm", "explicit"]
        policy.mode: "block" | "warn" | "redact"
        """
```

#### 2.1.3 Prompt Injection Detector

**Mục đích:** Phát hiện các nỗ lực prompt injection — input cố gắng override system instructions hoặc điều khiển agent thực hiện hành động trái phép.

**Detection strategies (layered):**

| Strategy | Mô tả | Precision | Recall | Phase |
|----------|--------|-----------|--------|-------|
| **Heuristic rules** | Regex patterns cho common injection phrases ("ignore previous instructions", "you are now...") | Trung bình | Thấp | **1** |
| **Delimiter analysis** | Phát hiện attempts to break prompt structure (closing XML tags, markdown headers) | Cao | Thấp | **1** |
| **Classifier model** | Fine-tuned model phân loại input là benign vs injection | Cao | Cao | **2** |
| **Canary tokens** | Embed unique tokens trong system prompt; nếu xuất hiện trong output → leaked | Rất cao | N/A (detection) | **2** |

> **Phase note:** Phase 1 chỉ implement heuristic rules + delimiter analysis (zero dependency, < 5ms). Classifier model và canary tokens đẩy sang Phase 2 — giảm complexity và dependency (không cần ONNX runtime, fine-tuned model trong Phase 1).

```python
class InjectionDetector:
    async def detect(self, user_input: str, system_prompt: str) -> DetectionResult:
        """
        Returns: DetectionResult(
            is_injection: bool,
            confidence: float,        # 0.0 - 1.0
            strategy_triggered: str,  # which detection layer caught it
            details: str
        )

        Phase 1 (heuristic + delimiter only):
          Match found → BLOCK (reject immediately)
          No match → PASS

        Phase 2 (+ classifier + canary):
          >= 0.9 → BLOCK (reject immediately)
          >= 0.7 → ESCALATE (log + human review queue)
          >= 0.5 → WARN (log warning, proceed with extra monitoring)
          <  0.5 → PASS
        """
```

---

### 2.2 Policy Engine

Chạy **trong quá trình** execution, kiểm tra mỗi action trước khi thực thi.

#### 2.2.1 Tool Permission Enforcer

**Mục đích:** Kiểm soát agent được phép gọi tool nào, với tham số nào.

**Permission layers (evaluated top-down):**

```
┌─────────────────────────────────────────────┐
│ Tenant Policy                                │  "Tenant X chỉ dùng read-only tools"
│   └─ Agent Policy                            │  "Agent A được dùng DB + GitHub"
│       └─ Session Policy                      │  "Session này là readonly"
│           └─ Action Policy                   │  "Tool write:database cần approval"
└─────────────────────────────────────────────┘
```

**Data Model:**

```python
@dataclass
class ToolPermission:
    tool_pattern: str          # "mcp:database:*", "mcp:github:create_issue"
    actions: list[str]         # ["invoke"], ["invoke", "configure"]
    constraints: PermissionConstraints

@dataclass
class PermissionConstraints:
    max_calls_per_session: int | None     # None = unlimited
    max_calls_per_minute: int | None
    max_cost_per_call: float | None       # USD
    requires_approval: bool               # HITL gate
    allowed_parameters: dict | None       # JSONSchema subset of allowed params
    denied_parameters: dict | None        # JSONSchema of explicitly denied params
    time_window: str | None               # "business_hours_only"
```

**Evaluation:**

```python
class ToolPermissionEnforcer:
    async def check(
        self,
        tool_call: ToolCall,
        agent_permissions: list[ToolPermission],
        session_context: SessionContext,
    ) -> PermissionResult:
        """
        Returns: ALLOW | DENY(reason) | REQUIRE_APPROVAL(approver)

        Evaluation order:
        1. Is tool in agent's allowed tool list? → DENY if not
        2. Are parameters within allowed constraints? → DENY if not
        3. Is rate limit exceeded? → DENY if yes
        4. Is cost limit exceeded? → DENY if yes
        5. Does this tool require HITL approval? → REQUIRE_APPROVAL if yes
        6. → ALLOW
        """
```

#### 2.2.2 Budget Enforcer

**Mục đích:** Ngăn chặn chi phí vượt kiểm soát từ agentic loops.

| Budget Type | Scope | Kiểm tra |
|-------------|-------|----------|
| **Token budget** | Per-session | Total tokens consumed < max_tokens |
| **Cost budget** | Per-session, per-agent, per-tenant | Estimated USD cost < max_cost |
| **Step budget** | Per-session | Number of reasoning steps < max_steps |
| **Time budget** | Per-session | Wall-clock duration < max_duration |

```python
class BudgetEnforcer:
    async def check(self, session: Session, next_action: Action) -> BudgetResult:
        """
        Before each LLM call or tool execution:
        1. Calculate current usage (tokens, cost, steps, time)
        2. Estimate next action cost
        3. If current + estimated > budget:
           - If >= 90% budget: inject "wrap up" instruction to LLM
           - If >= 100% budget: DENY, force graceful termination
        """

    async def estimate_cost(self, action: Action) -> CostEstimate:
        """
        Estimate tokens for next LLM call based on:
        - Current context length
        - Average completion length for this agent
        - Tool execution cost (if applicable)
        """
```

**Graceful degradation flow:**

```
Budget at 80% → Log warning
Budget at 90% → Inject instruction: "Bạn sắp hết budget. Hãy tóm tắt kết quả hiện tại."
Budget at 95% → Inject instruction: "Đây là bước cuối cùng. Trả kết quả ngay."
Budget at 100% → Force stop, return partial result
```

#### 2.2.3 Rate Limit Enforcer

| Dimension | Default | Configurable |
|-----------|---------|-------------|
| LLM calls per minute per session | 30 | Yes |
| Tool calls per minute per session | 60 | Yes |
| LLM calls per minute per tenant | 300 | Yes |
| Concurrent sessions per tenant | 100 | Yes |

**Implementation:** Token bucket algorithm trên Redis.

#### 2.2.4 Human-in-the-Loop (HITL) Gate

**Mục đích:** Tạm dừng execution, chờ human approval cho actions nhạy cảm.

```python
class HITLGate:
    async def request_approval(
        self,
        session_id: str,
        action: ToolCall,
        reason: str,
        timeout_seconds: int = 3600,
    ) -> ApprovalResult:
        """
        1. Set session state → WAITING_INPUT
        2. Emit approval_requested event (via WebSocket + webhook)
        3. Store pending approval in DB
        4. Wait for human response (approve/reject/modify) or timeout
        5. Return result → executor continues or aborts
        """
```

**Approval payload gửi cho human:**

```json
{
  "approval_id": "uuid",
  "session_id": "uuid",
  "agent_name": "customer-support-v2",
  "action": {
    "tool": "mcp:database:execute_query",
    "parameters": { "query": "UPDATE users SET status='active' WHERE id=123" }
  },
  "reason": "Tool 'execute_query' requires approval for write operations",
  "context_summary": "Agent đang xử lý yêu cầu kích hoạt tài khoản user #123",
  "options": ["approve", "reject", "modify"],
  "expires_at": "2026-03-25T15:30:00Z"
}
```

#### 2.2.5 Custom Rule Engine (Phase 2)

> **Phase note:** CEL rule engine đẩy sang Phase 2 sau review. Phase 1 personas không cần dynamic rule definition — static config (tool_permissions + budget) đủ dùng. CEL thêm dependency nặng (cel-python) và complexity mà chưa có user nào cần trong MVP.

**Mục đích:** Cho phép tenant/admin define rules tùy chỉnh mà không cần code.

```python
@dataclass
class GuardrailRule:
    id: str
    name: str
    description: str
    trigger: str              # "before_llm_call" | "before_tool_call" | "after_llm_call"
    condition: str            # CEL expression (Common Expression Language)
    action: str               # "block" | "warn" | "require_approval" | "modify"
    priority: int             # Lower = evaluated first
    enabled: bool

# Example rules:
rules = [
    GuardrailRule(
        name="no_delete_in_prod",
        trigger="before_tool_call",
        condition='tool.name == "database:execute" && input.query.contains("DELETE") && env == "production"',
        action="block",
    ),
    GuardrailRule(
        name="large_data_approval",
        trigger="before_tool_call",
        condition='tool.name == "database:execute" && estimated_rows > 10000',
        action="require_approval",
    ),
    GuardrailRule(
        name="notify_on_external_api",
        trigger="before_tool_call",
        condition='tool.namespace.startsWith("mcp:external")',
        action="warn",
    ),
]
```

---

### 2.3 Outbound Pipeline

Chạy **sau** khi LLM trả response, trước khi gửi về client.

#### 2.3.1 Response Filter

| Kiểm tra | Hành vi |
|----------|---------|
| Toxic/harmful content trong response | Block + log |
| Off-topic response (agent deviation) | Warn + log |
| Hallucination indicators | Warn (khi confidence thấp) |
| Response length limit | Truncate + warn |

#### 2.3.2 PII Detector (Phase 2)

> **Phase note:** Presidio-based PII detection đẩy sang Phase 2. Phase 1 chỉ cần regex-based masking cho patterns rõ ràng (email, phone, credit card) trong log output — nằm trong structured logging layer, không cần Presidio dependency.

**Mục đích:** Phát hiện và mask PII trong output trước khi trả về client hoặc ghi vào logs.

| PII Type | Pattern | Mask |
|----------|---------|------|
| Email | regex | `***@***.com` |
| Phone | regex | `***-***-1234` |
| SSN | regex | `***-**-6789` |
| Credit card | regex + Luhn | `****-****-****-1234` |
| Name (optional) | NER model | `[PERSON]` |
| Address (optional) | NER model | `[ADDRESS]` |

```python
class PIIDetector:
    async def scan_and_mask(
        self,
        text: str,
        policy: PIIPolicy,
    ) -> PIIScanResult:
        """
        policy.mode: "detect_only" | "mask_in_response" | "mask_in_logs" | "mask_all"
        policy.types: ["email", "phone", "ssn", "credit_card"]

        Returns: PIIScanResult(
            original_text: str,
            masked_text: str,
            detections: list[PIIDetection(type, span, confidence)]
        )
        """
```

#### 2.3.3 Canary Monitor (Phase 2)

> **Phase note:** Canary tokens đẩy sang Phase 2 cùng với classifier-based injection detection.

**Mục đích:** Phát hiện system prompt leakage.

**Mechanism:**
1. Khi tạo session, embed một unique canary token vào system prompt
2. Monitor mọi output cho sự xuất hiện của canary token
3. Nếu phát hiện → system prompt đã bị leak (có thể do prompt injection)
4. Action: Block response + alert + log incident

```python
class CanaryMonitor:
    def inject_canary(self, system_prompt: str, session_id: str) -> tuple[str, str]:
        """Returns (modified_prompt, canary_token)"""
        canary = generate_unique_token(session_id)
        marker = f"[SYSTEM_INTEGRITY_TOKEN: {canary}]"
        return system_prompt + f"\n{marker}", canary

    def check_output(self, output: str, canary_token: str) -> bool:
        """Returns True if canary is leaked in output → ALERT"""
        return canary_token in output
```

---

### 2.4 Audit Trail

**Mọi guardrail check** đều được log bất kể kết quả.

```python
@dataclass
class GuardrailAuditEntry:
    id: str
    timestamp: datetime
    session_id: str
    tenant_id: str
    agent_id: str
    step_index: int
    check_type: str          # "schema_validation", "injection_detection", "tool_permission", etc.
    check_name: str          # Specific check name
    result: str              # "pass" | "fail" | "warn" | "require_approval"
    details: dict            # Check-specific details
    action_taken: str        # "allowed" | "blocked" | "masked" | "escalated"
    latency_ms: float        # How long the check took
```

**Storage:** PostgreSQL append-only table (no UPDATE/DELETE allowed).

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
 │                │              │ ✅ format OK     │                            │
 │                │              └─┬──────────────┘                            │
 │                │              ┌─▼──────────────┐                            │
 │                │              │ Content Filter  │                            │
 │                │              │ ✅ content clean │                            │
 │                │              └─┬──────────────┘                            │
 │                │              ┌─▼──────────────────┐                        │
 │                │              │ Injection Detector   │                        │
 │                │              │ Heuristic: ✅ pass   │                        │
 │                │              │ Classifier: ✅ 0.12  │                        │
 │                │              └─┬──────────────────┘                        │
 │                │              ┌─▼──────────────┐                            │
 │                │              │ Budget Check    │                            │
 │                │              │ ✅ 2,400/10,000 │                            │
 │                │              │    tokens used  │                            │
 │                │              └─┬──────────────┘                            │
 │                │                │                                            │
 │                │                │──ALL PASSED──→ forward to executor ──────→│
 │                │                │                                            │
 │                │                │──audit log (5 entries)──→ Trace Store      │
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
 │                  │ Check              │                                 │
 │                  │ ✅ Agent allowed   │                                 │
 │                  │ ✅ Params valid    │                                 │
 │                  └─┬─────────────────┘                                 │
 │                  ┌─▼─────────────────┐                                 │
 │                  │ Rate Limit Check   │                                 │
 │                  │ ✅ 5/30 calls used │                                 │
 │                  └─┬─────────────────┘                                 │
 │                  ┌─▼─────────────────┐                                 │
 │                  │ Custom Rules       │                                 │
 │                  │ ✅ No rules match  │                                 │
 │                  └─┬─────────────────┘                                 │
 │                  ┌─▼─────────────────┐                                 │
 │                  │ HITL Required?     │                                 │
 │                  │ ❌ No (read-only)  │                                 │
 │                  └─┬─────────────────┘                                 │
 │                    │                                                    │
 │                    │──ALLOW──→ forward ─────────────────────────────────→│
 │                    │                                                    │
 │                    │──audit log──→ Trace Store                          │
 │                    │                                                    │
```

### 3.3 HITL Approval Flow (High-Risk Action)

```
Executor      Guardrails        Session Svc       Queue        Human         WebSocket
 │               │                  │                │            │              │
 │──tool_call───→│                  │                │            │              │
 │ {tool:"db:    │                  │                │            │              │
 │  delete"}     │                  │                │            │              │
 │             ┌─▼───────────┐     │                │            │              │
 │             │ Permission   │     │                │            │              │
 │             │ Check        │     │                │            │              │
 │             │ ⚠ REQUIRE    │     │                │            │              │
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
 │                │                  │ ✅ Content safe    │              │
 │                │                  └─┬─────────────────┘              │
 │                │                  ┌─▼─────────────────┐              │
 │                │                  │ PII Detector       │              │
 │                │                  │ ⚠ Email found      │              │
 │                │                  │ → masked in logs   │              │
 │                │                  └─┬─────────────────┘              │
 │                │                  ┌─▼─────────────────┐              │
 │                │                  │ Canary Monitor     │              │
 │                │                  │ ✅ No leakage      │              │
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

```python
@dataclass
class GuardrailsConfig:
    # Inbound
    input_validation: InputValidationConfig
    content_filtering: ContentFilterConfig
    injection_detection: InjectionDetectionConfig

    # Policy
    tool_permissions: list[ToolPermission]
    budget: BudgetConfig
    rate_limits: RateLimitConfig
    hitl_rules: list[HITLRule]
    custom_rules: list[GuardrailRule]

    # Outbound
    output_filtering: OutputFilterConfig
    pii_detection: PIIConfig
    canary_enabled: bool

@dataclass
class BudgetConfig:
    max_tokens_per_session: int = 50_000
    max_cost_per_session_usd: float = 5.0
    max_steps_per_session: int = 50
    max_duration_seconds: int = 600
    warning_threshold: float = 0.8      # 80% → inject warning
    critical_threshold: float = 0.95    # 95% → force wrap-up

@dataclass
class InjectionDetectionConfig:
    enabled: bool = True
    strategies: list[str] = ["heuristic", "classifier"]
    block_threshold: float = 0.9
    escalate_threshold: float = 0.7
    warn_threshold: float = 0.5
    classifier_model: str = "guardrail-injection-v1"  # internal model ID
```

### 4.2 Example Agent Definition with Guardrails

```json
{
  "agent_id": "customer-support-v2",
  "guardrails": {
    "input_validation": { "max_message_length": 4000, "allowed_content_types": ["text"] },
    "content_filtering": { "mode": "block", "categories": ["hate_speech", "self_harm"] },
    "injection_detection": { "enabled": true, "block_threshold": 0.85 },
    "tool_permissions": [
      { "tool_pattern": "mcp:crm:read_*", "actions": ["invoke"] },
      { "tool_pattern": "mcp:crm:update_*", "actions": ["invoke"], "constraints": { "requires_approval": false } },
      { "tool_pattern": "mcp:crm:delete_*", "actions": ["invoke"], "constraints": { "requires_approval": true } },
      { "tool_pattern": "mcp:email:send", "actions": ["invoke"], "constraints": { "max_calls_per_session": 3 } }
    ],
    "budget": { "max_tokens_per_session": 30000, "max_cost_per_session_usd": 2.0, "max_steps": 20 },
    "pii_detection": { "mode": "mask_in_logs", "types": ["email", "phone", "ssn"] },
    "canary_enabled": true
  }
}
```

---

## 5. Tech Stack

| Component | Technology | Phase | Lý do |
|-----------|-----------|-------|-------|
| **Pipeline framework** | Python async middleware chain | 1 | Simple, fast, extensible |
| **Schema validation** | Pydantic v2 | 1 | Native to FastAPI, fast |
| **Injection detection (heuristic)** | Regex + custom patterns | 1 | Zero dependency, fast |
| **Injection detection (classifier)** | Distil-BERT fine-tuned (ONNX) | 2 | Local inference, <10ms |
| **Content filtering** | OpenAI Moderation API / local model | 2 | Classifier-based filtering |
| **PII detection** | Presidio (Microsoft, OSS) | 2 | Mature, extensible, multi-language |
| **Rate limiting** | Redis + token bucket algorithm | 1 | Distributed, fast |
| **Budget tracking** | Redis (counters) + PostgreSQL (aggregates) | 1 | Real-time + durable |
| **Custom rule engine** | CEL (Common Expression Language) | 2 | Google-backed, sandboxed, fast (was Phase 1) |
| **HITL notifications** | WebSocket + Webhook | 1 | Real-time + async delivery |
| **Audit storage** | PostgreSQL (append-only table) | 1 | Queryable, immutable with triggers |
| **Advanced classifier** | Fine-tuned guardrail model (self-hosted) | 2 | Higher accuracy, custom categories |

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

| Scenario | Hành vi |
|----------|---------|
| Guardrail service unavailable | **Fail-closed** — reject request, log error |
| Injection detector timeout | Proceed with warning + extra monitoring |
| Budget check Redis unavailable | Use local cache (stale-ok for ~1 min) + log |
| HITL approval timeout | Configurable: auto-reject (default) or auto-approve |
| Custom rule evaluation error | Skip rule + warn + log (never block on broken rule) |
