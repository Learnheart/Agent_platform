# Nghiên Cứu Mẫu Kiến Trúc: Agent Serving Platform

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect

---

## 1. Agent Execution Patterns

### 1.1 ReAct (Reasoning + Acting)

```
Thought → Action → Observation → Thought → Action → Observation → ... → Final Answer
```

- Mỗi iteration = 1 LLM call + 1 tool execution
- Dễ checkpoint giữa các bước
- Context window tăng tuyến tính theo số bước
- **Phù hợp:** Task 3-15 bước, baseline pattern
- **Hạn chế:** Dễ bị loop; không có planning horizon

### 1.2 Plan-then-Execute

```
[Planning Phase] → Full Task Decomposition → [Execution Phase] → Sequential/Parallel Sub-tasks
                                                  ↑
                                          Re-planning loop (optional)
```

- Tách biệt planning và execution thành 2 phase
- Plan là artifact first-class, có thể persist và version
- Cho phép parallelize sub-tasks độc lập
- **Phù hợp:** Task 10-50+ bước, workflow phức tạp
- **Platform design:** Expose `Plan` object với status tracking, cho phép user approve/modify trước execution

### 1.3 Tree of Thought (ToT)

- Explore nhiều nhánh reasoning song song, evaluate, prune
- Compute-intensive: depth 5, branch 3 = 243 leaf evaluations
- Cần evaluator riêng (LLM-as-judge hoặc specialized model)
- State management dạng cây, không phải chuỗi
- **Phù hợp:** Task cần correctness cao (code gen, math, complex reasoning)

### 1.4 Reflexion

```
Attempt → Evaluate → Reflect → Retry (with reflection) → ... → Pass
```

- Cần evaluation function (unit tests, LLM-as-judge)
- Context window tăng với mỗi retry cycle
- **Phù hợp:** Code generation (run tests, reflect, retry)

### 1.5 Multi-Agent Collaboration

| Pattern | Mô tả | Use case |
|---------|--------|----------|
| **Supervisor → Workers** | 1 agent điều phối, delegate cho specialist agents | Production orchestration |
| **Peer-to-Peer** | Agent giao tiếp trực tiếp, không có coordinator | Debate, adversarial testing |
| **Router** | Lightweight agent phân loại và route đến specialist | Request classification |
| **Sequential Pipeline** | Agent xử lý tuần tự theo chuỗi | Document processing |
| **Group Chat** | Nhiều agent thảo luận trong shared conversation | Brainstorming, review |

---

## 2. Infrastructure Patterns

### 2.1 Stateless Executor + Externalized State (Khuyến nghị)

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   API GW    │────→│   Task Queue │────→│  Executor   │
│   (Ingress) │     │  (SQS/Redis) │     │  (Stateless)│
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                 │
                                    ┌────────────┼────────────┐
                                    ▼            ▼            ▼
                              ┌──────────┐ ┌──────────┐ ┌──────────┐
                              │  State   │ │   LLM    │ │   Tool   │
                              │  Store   │ │ Provider │ │ Executor │
                              │(Redis/PG)│ │  (API)   │ │(Sandbox) │
                              └──────────┘ └──────────┘ └──────────┘
```

**Nguyên tắc:** Executor stateless, load state từ external store đầu mỗi step, persist cuối mỗi step.

**Lợi ích:**
- Horizontal scaling trivial (thêm executor instances)
- Fault tolerance (executor crash → step khác pick up từ checkpoint)
- Clean checkpoint/resume

### 2.2 Session Model

```typescript
Session {
  id: UUID
  agent_id: string                  // reference to agent definition
  tenant_id: string                 // for multi-tenant isolation
  state: CREATED | RUNNING | WAITING_INPUT | PAUSED | COMPLETED | FAILED | TIMED_OUT
  conversation_history: Message[]
  plan: Plan?                       // cho plan-then-execute patterns
  execution_trace: Step[]           // full audit trail
  memory_refs: MemoryStore[]        // references to long-term memory
  checkpoint: binary                // serialized execution state
  token_usage: { prompt: int, completion: int, total_cost: float }
  created_at, updated_at, ttl
  metadata: map<string, any>
}
```

### 2.3 Persistence Tiering

| Tier | Store | Dữ liệu | Retention |
|------|-------|----------|-----------|
| **Hot** | Redis/Memcached | Active sessions | TTL-based (hours) |
| **Warm** | PostgreSQL/DynamoDB | Recent sessions, query-able | Days-weeks |
| **Cold** | S3/Blob Storage | Archived traces, compliance | Months-years |

### 2.4 Dual Delivery Mode

**Streaming (Interactive):**
- WebSocket/SSE cho real-time feedback
- Events: `thought`, `action_start`, `action_result`, `token`, `final_answer`
- Cho interactive/conversational agents

**Queue-Based (Background):**
- Client submit task → nhận task ID → poll hoặc webhook khi hoàn thành
- Durable queue (SQS, Redis Streams, Kafka)
- Cho long-running agents (phút → giờ)

**Cùng một execution engine**, khác nhau ở output adapter.

### 2.5 Checkpoint & Resume

```
Step 1: [LLM Call] → [Tool Call] → [Observation] → ✅ CHECKPOINT
Step 2: [LLM Call] → [Tool Call] → ❌ CRASH
                                        ↓
                               RESUME from CHECKPOINT after Step 1
                                        ↓
Step 2: [LLM Call] → [Tool Call] → [Observation] → ✅ CHECKPOINT
```

- Checkpoint sau mỗi successful step
- Chứa: conversation history, plan state, step index, accumulated artifacts
- Resume: load checkpoint, skip completed steps, continue

### 2.6 Long-running Agent Lifecycle

| Policy | Mục đích |
|--------|----------|
| **Token budget** | Hard cap total tokens. Agent conclude khi gần limit |
| **Time budget** | Max wall-clock time per session |
| **Step budget** | Max reasoning steps |
| **Idle timeout** | Auto-pause nếu waiting user input quá lâu |
| **Context management** | Summarize older history, sliding window |
| **Graceful degradation** | Return partial results khi gần hết budget |

---

## 3. Memory Architecture

### 3.1 Memory Stack

```
┌─────────────────────────────────────────┐
│         Short-term Memory               │  ← Context window (messages, recent tools)
│         (per-session)                    │
├─────────────────────────────────────────┤
│         Working Memory                  │  ← Current plan, accumulated artifacts
│         (per-session)                    │
├─────────────────────────────────────────┤
│         Long-term Memory                │  ← Vector store, knowledge graph
│         (per-agent / per-tenant)         │
├─────────────────────────────────────────┤
│         Episodic Memory                 │  ← Past task summaries, lessons learned
│         (per-agent-type)                 │
├─────────────────────────────────────────┤
│         Shared Memory                   │  ← Multi-agent workspace
│         (per-multi-agent-session)        │
└─────────────────────────────────────────┘
```

### 3.2 Short-term Memory Strategies

| Strategy | Mô tả |
|----------|--------|
| Sliding window | Giữ N messages gần nhất |
| Summarization | Tóm tắt messages cũ, thay thế |
| Selective retention | Giữ system prompt + first message + recent + flagged important |
| Token-aware truncation | Cắt từ giữa (giữ system prompt + đầu + cuối) |

### 3.3 Long-term Memory Technologies

| Type | Technology | Use case |
|------|-----------|----------|
| Vector Store | Pinecone, Qdrant, pgvector, Chroma | RAG, semantic search |
| Knowledge Graph | Neo4j, Amazon Neptune | Multi-hop reasoning, entity relationships |
| Document Store | Elasticsearch, MongoDB | Full-text search, structured data |

### 3.4 Shared Memory cho Multi-Agent

- **Blackboard pattern:** Shared data structure, tất cả agent read/write. Cần concurrency control
- **Message-passing:** Message bus / topics. Decoupled nhưng khó shared understanding
- **Shared artifact store:** Workspace có version control cho outputs

---

## 4. Tool System Design

### 4.1 MCP-Native Architecture

```
┌─────────────────────────────────────────────────────┐
│                    AGENT EXECUTOR                     │
│                                                       │
│  ┌─────────┐   ┌──────────────┐   ┌──────────────┐ │
│  │   LLM   │──→│ Tool Router  │──→│ MCP Client   │ │
│  │ (decide) │   │ (permission  │   │ (discover &  │ │
│  │          │   │  check)      │   │  invoke)     │ │
│  └─────────┘   └──────────────┘   └──────┬───────┘ │
└───────────────────────────────────────────┼─────────┘
                                            │
                    ┌───────────────────────┼────────────────────┐
                    ▼                       ▼                    ▼
            ┌──────────────┐      ┌──────────────┐     ┌──────────────┐
            │  MCP Server  │      │  MCP Server  │     │  MCP Server  │
            │  (Database)  │      │  (GitHub)    │     │  (Custom)    │
            └──────────────┘      └──────────────┘     └──────────────┘
```

### 4.2 Tool Registry Model

```typescript
Tool {
  id: string
  name: string                        // unique within namespace
  namespace: string                   // "builtin", "mcp:<server>", "custom:<tenant>"
  description: string                 // LLM dùng để quyết định khi nào gọi
  input_schema: JSONSchema
  output_schema: JSONSchema?
  execution_mode: "sync" | "async"
  timeout_ms: int
  requires_approval: bool             // human-in-the-loop
  permission_scope: string[]          // ["read:files", "write:database"]
  rate_limit: RateLimit?
}
```

### 4.3 Tool Discovery

1. **Static configuration:** Agent definition liệt kê tools cụ thể
2. **MCP dynamic discovery:** Connect MCP servers, enumerate tools
3. **Capability-based search:** Agent mô tả cần gì → registry trả matching tools (semantic search)

### 4.4 Sandboxed Execution

| Tier | Isolation | Use case |
|------|-----------|----------|
| Process-level | seccomp, AppArmor | API calls, lightweight tools |
| Container-level | gVisor, Firecracker | Code execution, file processing |
| VM-level | Full VM | Untrusted code, maximum isolation |

---

## 5. Observability Stack

### 5.1 Tracing Hierarchy (OpenTelemetry)

```
Session Span (root)
└── Step Span (mỗi reasoning step)
    ├── LLM Call Span
    │   ├── attributes: model, temperature, token_usage, latency, cost
    │   └── events: prompt (opt), completion
    └── Tool Execution Span
        ├── attributes: tool_name, input_hash, duration, success/failure
        └── events: output (opt)
```

### 5.2 Cost Model

```
Total Cost = LLM Cost + Tool Cost + Infrastructure Cost

LLM Cost     = Σ (prompt_tokens × input_price + completion_tokens × output_price)
Tool Cost    = Σ (API call costs + sandbox compute time)
Infra Cost   = Σ (executor compute + storage + network)
```

### 5.3 Quality Metrics

| Category | Metrics |
|----------|---------|
| **Operational** | Task completion rate, avg steps, avg latency, error rate, retry rate |
| **Quality** | User satisfaction, LLM-as-judge scores, groundedness, tool call accuracy |
| **Cost** | Cost per session, per agent, per tenant, per step |

---

## 6. Security Architecture

### 6.1 Defense-in-Depth

```
┌──────────────────────────────────────────────────────┐
│ Layer 1: API Gateway                                  │
│   - Authentication (OAuth/OIDC)                       │
│   - Rate limiting                                     │
│   - Tenant identification                             │
├──────────────────────────────────────────────────────┤
│ Layer 2: Input Validation                             │
│   - Prompt injection detection (guardrail model)      │
│   - Schema validation                                 │
│   - Content filtering                                 │
├──────────────────────────────────────────────────────┤
│ Layer 3: Policy Enforcement                           │
│   - Tool permission check (RBAC)                      │
│   - Parameter constraint validation                   │
│   - Budget/rate limit enforcement                     │
├──────────────────────────────────────────────────────┤
│ Layer 4: Execution Isolation                          │
│   - Tenant data namespace isolation                   │
│   - Sandboxed tool execution                          │
│   - Network policy (allowlist)                        │
├──────────────────────────────────────────────────────┤
│ Layer 5: Output Validation                            │
│   - Response filtering                                │
│   - PII detection/masking                             │
│   - Canary token monitoring                           │
├──────────────────────────────────────────────────────┤
│ Layer 6: Audit & Monitoring                           │
│   - Immutable audit logs                              │
│   - Anomaly detection                                 │
│   - Compliance reporting                              │
└──────────────────────────────────────────────────────┘
```

### 6.2 Permission Model

```typescript
Capability {
  resource: string          // "database:prod", "api:stripe"
  actions: string[]         // ["read"], ["read", "write"]
  constraints: {
    rate_limit: "10/min"?
    max_cost_per_call: "$0.50"?
    requires_approval: bool?
    allowed_parameters: JSONSchema?
  }
}
```

**Nguyên tắc:** Deny by default. Tools phải được grant explicitly. Enforce ở tầng platform, không phải prompt.

### 6.3 Tenant Isolation

- Memory isolation: mỗi tenant vector store/knowledge graph riêng
- Session isolation: không cross-tenant access
- Tool isolation: custom tools invisible giữa tenants
- Compute isolation (optional): dedicated infra cho sensitive workloads
- Implementation: Namespace tất cả data stores bằng tenant_id, enforce ở API gateway

---

## 7. Khuyến Nghị Kiến Trúc Tổng Hợp

1. **Graph-based execution model** làm abstraction thống nhất (express ReAct, Plan-Execute, Tree, Multi-agent)
2. **Stateless executors + externalized state** cho scaling và fault tolerance
3. **Dual delivery** (streaming + queue-based) cùng engine
4. **MCP-native tool system** với governance layer
5. **Layered memory** (short-term → long-term → episodic → shared) như platform primitives
6. **Security as infrastructure** (không phải prompt-level)
7. **OpenTelemetry tracing** từ day 1
8. **Human-in-the-loop** là first-class primitive (Phase 1: session state machine hỗ trợ WAITING_INPUT; Phase 2: full tool approval workflow)
