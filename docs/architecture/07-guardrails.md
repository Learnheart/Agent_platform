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

```python
class GuardrailCircuitBreaker:
    """Circuit breaker for soft guardrails.
    States: CLOSED (normal) → OPEN (bypassing) → HALF_OPEN (testing)"""

    failure_threshold: int = 5          # consecutive failures to open
    recovery_timeout_seconds: int = 60  # time in OPEN before trying HALF_OPEN
    half_open_max_calls: int = 3        # calls to test in HALF_OPEN

    async def execute(self, check_fn: Callable, fallback: GuardrailResult) -> GuardrailResult:
        """If CLOSED: run check_fn normally.
        If OPEN: return fallback (allow + log).
        If HALF_OPEN: run check_fn, track success/failure."""
```

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

```python
class SchemaValidator:
    async def validate(self, input: AgentInput, agent_config: AgentConfig) -> ValidationResult:
        """
        Returns: ValidationResult(passed=bool, violations=list[Violation])
        Nếu failed → return 400 Bad Request, không gọi LLM
        """
```

#### 2.1.2 Content Filter — Soft Guardrail (Phase 2)

| Mode | Hành vi |
|------|---------|
| **Block** | Reject input, trả error cho client |
| **Warn** | Cho qua nhưng log warning + emit event |
| **Redact** | Xóa/thay thế phần vi phạm, tiếp tục xử lý |

```python
class ContentFilter:
    async def check(self, content: str, policy: ContentPolicy) -> FilterResult:
        """
        policy.blocked_categories: ["hate_speech", "self_harm", "explicit"]
        policy.mode: "block" | "warn" | "redact"
        """
```

#### 2.1.3 Prompt Injection Detector — Soft Guardrail + Circuit Breaker

| Strategy | Precision | Recall | Phase |
|----------|-----------|--------|-------|
| **Heuristic rules** | Trung bình | Thấp | **1** |
| **Delimiter analysis** | Cao | Thấp | **1** |
| **Classifier model** | Cao | Cao | **2** |
| **Canary tokens** | Rất cao | N/A (detection) | **2** |

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

#### 2.2.1 Tool Permission Enforcer — Hard Guardrail (Phase 1)

```
┌─────────────────────────────────────────────┐
│ Tenant Policy                                │
│   └─ Agent Policy                            │
│       └─ Session Policy                      │
│           └─ Action Policy                   │
└─────────────────────────────────────────────┘
```

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

#### 2.2.2 Budget Enforcer — Hard Guardrail (Phase 1)

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

**Approval payload:**

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

#### 2.2.5 Custom Rule Engine — Soft Guardrail (Phase 2)

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

#### 2.3.3 Canary Monitor — Soft Guardrail (Phase 2)

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
    check_name: str
    result: str              # "pass" | "fail" | "warn" | "require_approval"
    details: dict
    action_taken: str        # "allowed" | "blocked" | "masked" | "escalated"
    latency_ms: float
```

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
