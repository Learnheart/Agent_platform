# Kiến Trúc Tổng Quan: Agent Serving Platform

> **Phiên bản:** 3.0
> **Ngày cập nhật:** 2026-03-25

---

## 1. Phạm Vi Hệ Thống

**Platform chịu trách nhiệm:** runtime execution, state management, security, observability, cost control, data governance.
**Developer chịu trách nhiệm:** agent logic (system prompt, tool selection, model config).

```
                    +---------------------------------------------------------+
                    |               AGENT PLATFORM (our system)               |
                    |                                                         |
  Developers ------>|  SDK / API / CLI                                        |
                    |       |                                                 |
                    |       v                                                 |
                    |  Agent Management --- Session --- Execution Engine      |
                    |       |                  |              |               |
                    |       |           +------+------+      |               |
                    |       |           | Cross-Cutting|      |               |
                    |       |           | Guardrails   |      |               |
                    |       |           | Governance   |      |               |
                    |       |           | Tracing      |      |               |
                    |       |           +--------------+      |               |
                    |       |                                 |               |
                    |       v                                 v               |
                    |  PostgreSQL / Redis            LLM GW / Tool RT        |
                    |                                   |         |           |
                    +-----------------------------------+---------+-----------+
                                                        |         |
                                                        v         v
                                                  LLM Providers  MCP Servers
                                                  (Anthropic     (DB, GitHub,
                                                   Phase 1)       Slack, ...)
```

### Phase Scope

| Khu vực | Phase 1 | Phase 2 |
|---------|---------|---------|
| Execution Engine | ReAct | Plan-then-Execute, Reflexion |
| LLM Provider | Claude (Anthropic) | OpenAI adapter, Gemini |
| Real-time Streaming | SSE (Server-Sent Events) | WebSocket |
| Memory | Short-term + Working | Long-term (vector store, RAG) |
| Multi-tenant | Single-tenant | Multi-tenant, RBAC |
| SDK | Python | TypeScript |

---

## 2. High-Level Architecture

```
+----------------------------------------------------------------------+
|                            CLIENT LAYER                                |
|  SDK (Python) | REST API | SSE | Webhook Consumer                     |
|  [WebSocket -> Phase 2]                                                |
+-------------------------------+--------------------------------------+
                                |
+-------------------------------v--------------------------------------+
|                           API GATEWAY                                  |
|              Auth  |  Rate Limit  |  Tenant Routing  |  TLS            |
+-------------------------------+--------------------------------------+
                                |
        +-----------------------+---------------------------+
        v                       v                           v
+---------------+    +------------------+    +------------------+
|    Agent      |    |    Session       |    |    Admin          |
|    Management |    |    Service       |    |    Service        |
|    Service    |    |                  |    |                  |
+-------+-------+    +--------+---------+    +------------------+
        |                     |
        |              +------v-------+
        |              |  Task Queue  |
        |              | (Redis Strm) |
        |              +------+-------+
        |                     |
        |           +---------v----------+
        |           |   EXECUTOR POOL    |
        |           | +----++----++----+ |
        |           | | E1 || E2 || EN | |    <- Stateless, auto-scaled
        |           | +--+-++--+-++--+-+ |
        |           +----+-----+-----+---+
        |                |     |     |
+-------+----------------+-----+-----+----------------------------+
|       |          INFRASTRUCTURE LAYER                             |
|       v                v     v     v                             |
|  +---------+   +---------------+   +---------------+            |
|  |  State  |   |  LLM Gateway  |   | Tool Runtime  |            |
|  |  Store  |   |               |   | (MCP Client)  |            |
|  |(Redis+PG|   | Anthropic     |   |               |            |
|  |)        |   | (Phase 1)     |   | +---++---+    |            |
|  +---------+   +---------------+   | |MCP||MCP|    |            |
|  +---------+                       | |Svr||Svr|    |            |
|  | Memory  |   +---------------+   | +---++---+    |            |
|  | Store   |   | Trace Store   |   +---------------+            |
|  |(pgvector|   | (OTel -> PG)  |                                 |
|  |) Ph2    |   +---------------+                                 |
|  +---------+                                                     |
+------------------------------------------------------------------+
```

---

## 3. Design Principles

| # | Nguyên tắc | Ý nghĩa |
|---|-----------|---------|
| 1 | **Platform, not Framework** | Cung cấp hạ tầng serving. Platform lo cross-cutting concerns, developer lo agent logic |
| 2 | **API-First** | Mọi tính năng accessible qua API trước |
| 3 | **Model-Agnostic** | Abstraction layer cho LLM providers |
| 4 | **MCP-Native** | MCP làm chuẩn tích hợp tool chính |
| 5 | **Secure by Default** | Permission, isolation, audit ở tầng platform |
| 6 | **Observable from Day 1** | Tracing, metrics, cost tracking built-in |
| 7 | **Progressive Complexity** | Đơn giản cho use case cơ bản, mạnh mẽ cho use case phức tạp |

---

## 4. Core Components

### 4.1 Component Map

```
+---- API Layer --------------------------------------------------------+
|  REST Controller | SSE Handler | Auth Middleware                       |
|  [WebSocket Handler -> Phase 2]                                        |
+-----------------------------+------------------------------------------+
                              |
+---- Core Services ----------v------------------------------------------+
|  Agent Manager | Session Manager | Tool Manager | Memory Mgr           |
+-----------------------------+------------------------------------------+
                              |
+---- Execution Engine -------v------------------------------------------+
|  +-------------------------------------------------------------+      |
|  |                Agent Executor                                 |      |
|  |  ReAct Engine (Phase 1) | Plan-Execute (Phase 2)             |      |
|  |  Context Manager | Checkpoint Mgr | Budget Enforcer          |      |
|  |  Event Emitter                                                |      |
|  +-------------------------------------------------------------+      |
|  +-------------------------------------------------------------+      |
|  |                LLM Gateway                                    |      |
|  |  Abstraction Interface (model-agnostic contract)              |      |
|  |  Anthropic (Phase 1) | OpenAI (Phase 2) | More (Phase 2+)    |      |
|  |  Token Tracker | Rate Limiter | Failover | Cache             |      |
|  +-------------------------------------------------------------+      |
+------------------------------------------------------------------------+

+---- Cross-Cutting ---------------------------------------------------+
|  Guardrails Engine | Governance Module | Tracing (OTel)               |
|  Cost Calculator   | Audit Logger      | Event Bus                    |
+----------------------------------------------------------------------+

+---- Infrastructure --------------------------------------------------+
|  PostgreSQL (+pgvector) | Redis (State + Queue) | S3/GCS             |
+----------------------------------------------------------------------+
```

### 4.2 Component Summary

| Component | Trách nhiệm | Technology |
|-----------|-------------|------------|
| **API Gateway** | Auth, rate limit, routing, TLS | FastAPI + middleware |
| **Agent Manager** | CRUD agent definitions, versioning, config | FastAPI + PostgreSQL |
| **Session Manager** | Session lifecycle, state machine, query | FastAPI + Redis + PG |
| **Tool Manager** | Tool registry, MCP connection, permission check | MCP SDK + PG |
| **Memory Manager** | Short-term context (Phase 1), long-term vector search (Phase 2) | Redis (Phase 1), pgvector (Phase 2) |
| **Executor** | Reasoning loop, checkpoint, budget enforcement | Python async workers |
| **Planning Engine** | ReAct (Phase 1), Plan-then-Execute (Phase 2) | Built-in (Python) |
| **LLM Gateway** | Provider abstraction, token tracking, failover, cache | httpx + provider SDKs |
| **Guardrails Engine** | Input/output validation, prompt injection detection | Middleware pipeline |
| **Governance Module** | Audit consolidation, retention policies, data classification | Internal module (Phase 1), service-ready interface |
| **Tracing** | Span collection, metrics export | OpenTelemetry SDK |
| **Event Bus** | Event emission cho tracing, streaming, audit, webhook | Redis Pub/Sub + OTel |

### 4.3 Component Interaction Matrix

```
                  Agent   Session  Tool    Memory  Executor  LLM GW  Guard   Govern  Event
                  Mgr     Mgr      Mgr     Mgr               rails   ance    Bus
  -----------------------------------------------------------------------------------------
  API Layer       v       v        v       v                                  v
  Agent Mgr                                                           v       v
  Session Mgr                                      v(enqueue)                 v
  Executor                         v       v                v  v     v       v
  LLM Gateway                                                                 v
  Tool Runtime                                                                v
  Guardrails                                                          v       v
  Governance                                                                  v(consume)
```

---

## 5. Luồng Xử Lý Hệ Thống (End-to-End Flows)

### 5.1 Luồng Tổng Quan: Từ API Request đến Response

```
+------+     +---------+     +---------+     +----------+     +----------+
|Client|---->|API Layer|---->|Session  |---->|Task Queue|---->|Executor  |
|      |     |         |     |Manager  |     |(Redis)   |     |Pool      |
+------+     +---------+     +---------+     +----------+     +----+-----+
   ^              |                                                 |
   |              |            +------------------------------------+
   |              |            |
   |              |            v
   |              |    +--------------- EXECUTION LOOP ------------------+
   |              |    |                                                  |
   |              |    |  +----------+   +-----------+   +-------------+ |
   |              |    |  |Checkpoint|-->|  Context   |-->| Guardrails  | |
   |              |    |  | Restore  |   | Assembly   |   | (Inbound)   | |
   |              |    |  +----------+   +-----------+   +------+------+ |
   |              |    |                                         |       |
   |              |    |                                  +------v------+ |
   |              |    |                                  | LLM Gateway | |
   |              |    |                                  | (LLM Call)  | |
   |              |    |                                  +------+------+ |
   |              |    |                                         |       |
   |              |    |                                  +------v------+ |
   |              |    |                                  | Guardrails  | |
   |              |    |                                  | (Outbound)  | |
   |              |    |                                  +------+------+ |
   |              |    |                                         |       |
   |              |    |                         +---------------+       |
   |              |    |                         |               |       |
   |              |    |              +----------v--+   +--------v-----+ |
   |              |    |              | Tool Call?   |   | Final Answer?| |
   |              |    |              | YES          |   | YES          | |
   |              |    |              +------+-------+   +-------+-----+ |
   |              |    |                     |                   |       |
   |              |    |              +------v-------+           |       |
   |              |    |              | Guardrails   |           |       |
   |              |    |              | (Permission) |           |       |
   |              |    |              +------+-------+           |       |
   |              |    |                     |                   |       |
   |              |    |              +------v-------+           |       |
   |              |    |              | Tool Runtime |           |       |
   |              |    |              | (MCP Call)   |           |       |
   |              |    |              +------+-------+           |       |
   |              |    |                     |                   |       |
   |              |    |              +------v-------+           |       |
   |              |    |              | Memory       |           |       |
   |              |    |              | Update       |           |       |
   |              |    |              +------+-------+           |       |
   |              |    |                     |                   |       |
   |              |    |              +------v-------+           |       |
   |              |    |              | Checkpoint   |           |       |
   |              |    |              | Save         |           |       |
   |              |    |              +------+-------+           |       |
   |              |    |                     |                   |       |
   |              |    |                     v                   |       |
   |              |    |              LOOP (next step)           |       |
   |              |    |                                         |       |
   |              |    +-----------------------------------------+       |
   |              |                                              |
   |<-------------+-------- SSE Stream (events) ----------------+
   |              |
   |              |    +-------------------------------------------+
   |              |    |        CROSS-CUTTING (mỗi step)            |
   |              |    |                                            |
   |              |    |  Event Bus --> OTel Trace Store            |
   |              |    |           --> Governance (audit sink)      |
   |              |    |           --> SSE (client stream, Phase 1) |
   |              |    |           --> WebSocket (Phase 2)          |
   |              |    |           --> Webhook (external notify)    |
   |              |    |           --> Cost Calculator              |
   |              |    +-------------------------------------------+
```

### 5.2 Luồng Chi Tiết: Một Step Thực Thi (Sequence Diagram)

```
Client     API GW    Session   Queue    Executor   Memory    Guardrails  LLM GW    Tool RT   Checkpoint  Event Bus  Governance
 |           |         |         |         |          |          |          |          |          |           |          |
 |--POST --->|         |         |         |          |          |          |          |          |           |          |
 | /sessions |         |         |          |          |          |          |          |          |           |          |
 | /{id}/msg |         |         |         |          |          |          |          |          |           |          |
 |           |--auth-->|         |         |          |          |          |          |          |           |          |
 |           |  + rate |         |         |          |          |          |          |          |           |          |
 |           |  limit  |         |         |          |          |          |          |          |           |          |
 |           |         |         |         |          |          |          |          |          |           |          |
 |           |         |--store  |         |          |          |          |          |          |           |          |
 |           |         |  msg    |         |          |          |          |          |          |           |          |
 |           |         |--enqueue------>   |          |          |          |          |          |           |          |
 |           |         |         |         |          |          |          |          |          |           |          |
 |<--202-----|         |         |         |          |          |          |          |          |           |          |
 | Accepted  |         |         |         |          |          |          |          |          |           |          |
 |           |         |         |         |          |          |          |          |          |           |          |
 | === SSE ============================================ (client connects SSE for streaming) ==============================|
 |           |         |         |         |          |          |          |          |          |           |          |
 |           |         |         |--pull-->|          |          |          |          |          |           |          |
 |           |         |         |         |          |          |          |          |          |           |          |
 |           |         |         |         |--restore------------------------------------------->|           |          |
 |           |         |         |         |<--state---------------------------------------------.|           |          |
 |           |         |         |         |          |          |          |          |          |           |          |
 |           |         |         |         |--build-->|         |          |          |          |           |          |
 |           |         |         |         |  context  |         |          |          |          |           |          |
 |           |         |         |         |<-payload--|         |          |          |          |           |          |
 |           |         |         |         |          |          |          |          |          |           |          |
 |           |         |         |         |--inbound---------->|          |          |          |           |          |
 |           |         |         |         |  check    |        |          |          |          |           |          |
 |           |         |         |         |<-pass--------------|          |          |          |           |          |
 |           |         |         |         |          |          |          |          |          |           |          |
 |           |         |         |         |--chat(messages, tools)------->|          |          |           |          |
 |<== thought (SSE stream) ====|         |<--response (tool_call)--------|          |          |           |          |
 |           |         |         |         |          |          |          |          |          |           |          |
 |           |         |         |         |--permission check-->|         |          |          |           |          |
 |           |         |         |         |<--ALLOW------------|         |          |          |           |          |
 |           |         |         |         |          |          |          |          |          |           |          |
 |<== tool_call (SSE) ========|         |--invoke------------------------------------>|          |           |          |
 |           |         |         |         |<--result-------------------------------------|          |           |          |
 |<== observation (SSE) ======|         |          |          |          |          |          |           |          |
 |           |         |         |         |--outbound check--->|          |          |          |           |          |
 |           |         |         |         |<--pass------------|          |          |          |           |          |
 |           |         |         |         |          |          |          |          |          |           |          |
 |           |         |         |         |--update-->|         |          |          |          |           |          |
 |           |         |         |         |  memory   |         |          |          |          |           |          |
 |           |         |         |         |          |          |          |          |          |           |          |
 |           |         |         |         |--save-------------------------------------------->|           |          |
 |           |         |         |         |  checkpoint          |          |          |          |           |          |
 |           |         |         |         |          |          |          |          |          |           |          |
 |           |         |         |         |--emit events-------------------------------------------------------->|          |
 |           |         |         |         |          |          |          |          |          |           |--audit-->|
 |           |         |         |         |          |          |          |          |          |           |--trace-->|(OTel)
 |           |         |         |         |          |          |          |          |          |           |--cost--->|(calc)
 |           |         |         |         |          |          |          |          |          |           |          |
 |           |         |         |         | [if not final: enqueue next step]        |          |           |          |
 |           |         |         |         | [if final: return answer]                |          |           |          |
 |           |         |         |         |          |          |          |          |          |           |          |
 |<== final_answer (SSE) =====|         |          |          |          |          |          |           |          |
```

### 5.3 Luồng Multi-Step Execution (Macro View)

```
Client sends message
        |
        v
+-- Queue <--------------------------------------------------------+
|       |                                                           |
|       v                                                           |
|   Executor pulls task                                             |
|       |                                                           |
|       v                                                           |
|   +- STEP 1 ---------------------------------------------------+ |
|   | Restore checkpoint (empty -- new session)                    | |
|   | Build context: [system_prompt + user_message]               | |
|   | Guardrails inbound: PASS                                    | |
|   | LLM call -> response: tool_call(search_database)            | |
|   | Guardrails permission: PASS                                 | |
|   | Tool call -> result: [{rows...}]                            | |
|   | Guardrails outbound: PASS                                   | |
|   | Memory update: append messages                               | |
|   | Checkpoint save: step=1                                      | |
|   | Events: thought, tool_call, observation                      | |
|   | Result: TOOL_CALL -> continue                                | |
|   +-------------------------------------------------------------+ |
|       |                                                           |
|       | enqueue next step ----------------------------------------+
|       v
|   +- STEP 2 ---------------------------------------------------+
|   | Restore checkpoint (step=1)                                  |
|   | Build context: [system + history + tool_result]              |
|   | Guardrails inbound: PASS                                    |
|   | LLM call -> response: tool_call(send_email)                 |
|   | Guardrails permission: REQUIRES_APPROVAL                    |
|   | HITL gate -> session state: WAITING_INPUT                   |
|   | Checkpoint save: step=2, paused                              |
|   | Events: tool_call, approval_requested                        |
|   | Result: WAITING_INPUT -> pause                                |
|   +-------------------------------------------------------------+
|
|   ... human approves via API/webhook ...
|
|   +- STEP 3 (resumed) -----------------------------------------+
|   | Restore checkpoint (step=2)                                  |
|   | Execute approved tool call: send_email                       |
|   | LLM call with all context -> final_answer                    |
|   | Guardrails outbound: PASS                                   |
|   | Memory update: append final answer                           |
|   | Checkpoint save: step=3, completed                           |
|   | Events: tool_result, final_answer                            |
|   | Result: FINAL_ANSWER -> done                                 |
|   +-------------------------------------------------------------+
|
v
Session state: COMPLETED
Total: 3 steps, 3 LLM calls, 2 tool calls, 1 HITL approval
Cost: tracked per step, aggregated to session/agent/tenant
```

### 5.4 Session State Machine

```
    CREATED --start()--> RUNNING --complete()--> COMPLETED
                           |  ^
                  pause()  |  | resume()
                           v  |
                         PAUSED
                           |
                  timeout  |
                           v
                         FAILED
                           ^
                           | error/timeout
                         RUNNING --wait_input()--> WAITING_INPUT
```

### 5.5 Luồng Agent Creation & Configuration

```
Developer        SDK/API         Agent Manager      Tool Manager      PostgreSQL
 |                  |                 |                   |                |
 |--create_agent()-->|                 |                   |                |
 |  {name,          |                 |                   |                |
 |   system_prompt, |                 |                   |                |
 |   model_config,  |                 |                   |                |
 |   tools: [...],  |                 |                   |                |
 |   guardrails,    |                 |                   |                |
 |   memory_config} |                 |                   |                |
 |                  |--POST /agents-->|                   |                |
 |                  |                 |                   |                |
 |                  |                 |--validate config   |                |
 |                  |                 |  (schema, model,   |                |
 |                  |                 |   budget limits)   |                |
 |                  |                 |                   |                |
 |                  |                 |--verify tools----->|                |
 |                  |                 |<--verified---------|                |
 |                  |                 |                   |                |
 |                  |                 |--INSERT agent----------------------------->|
 |                  |                 |<--agent_id--------------------------------|
 |                  |                 |                   |                |
 |                  |<--agent_id------|                   |                |
 |<--agent created--|                 |                   |                |
```

### 5.6 Luồng Cross-Cutting: Events Flow Through System

```
    Executor / Services
         |
         | emit(AgentEvent)
         v
   +----------------------- EVENT BUS ---------------------------+
   |                                                              |
   |  event types:                                                |
   |  step_start, llm_call_start, llm_call_end, thought,         |
   |  tool_call, tool_result, checkpoint, budget_warning,         |
   |  plan_created, plan_step_end, replan, final_answer,          |
   |  error, session_created, session_completed                   |
   |                                                              |
   +--+----------+------------------+-----------------+-----------+
      |          |                  |                 |
      v          v                  v                 v
 +---------+ +----------+ +-----------+ +------------+
 |  OTel   | |   SSE    | | Governance| |  Webhook   |
 | Exporter| | Streamer | |  Module   | |  Notifier  |
 |         | | (Ph1)    | |           | |            |
 | -> Trace| | -> Client| | -> Audit  | | -> External|
 |   Store | |   (live) | | -> Cost   | |   systems  |
 | (PG)    | |          | | -> Retain | |            |
 +---------+ +----------+ +-----------+ +------------+
```

### 5.7 Luồng Error & Recovery

| Failure Scenario | Recovery |
|-----------------|----------|
| Executor crash (mid-step) | Task not ACKed -> re-delivered from queue. New executor restores from checkpoint. Resumes from last saved step |
| Task timeout in queue | Re-deliver hoặc move to dead-letter queue |
| LLM API error | Retry with exponential backoff (3x). If persistent -> session FAILED |
| LLM rate limit | Queue + delay + retry |
| LLM content refusal | No retry, return refusal message to client |
| LLM provider outage | Retry same provider (no cross-provider failover Phase 1) |
| Tool execution timeout | Return error as observation to LLM. LLM decides: retry, use different tool, or answer without tool result |
| MCP server crash (stdio) | Auto-restart (up to max_restarts). Re-discover tools, update registry |
| Budget exceeded | Inject "wrap up" at 90%. Force stop at 100%, return partial result |
| Guardrail blocked | Return error to client (inbound). Or block response + log (outbound) |
| Checkpoint write failure (Redis) | Fallback to PG; log warning |
| Checkpoint write failure (PG) | Log error, continue (risk of replay) |
| Redis unavailable | Checkpoint: fallback to PG (slower). Rate limit: use local cache (~1min stale). Memory: degrade gracefully (no STM) |
| PostgreSQL unavailable | Platform enters read-only mode. Active sessions continue (Redis state). New sessions blocked until recovery |

---

## 6. Data Model Overview

### 6.1 Entity Relationships

```
+----------+       +--------------+       +--------------+
|  Tenant  |--1:N--|    Agent     |--1:N--|   Session    |
|          |       |              |       |              |
| id       |       | id           |       | id           |
| name     |       | tenant_id    |       | agent_id     |
| config   |       | name         |       | state        |
|          |       | system_prompt|       | step_index   |
|          |       | model_config |       | usage        |
|          |       | tools_config |       | created_at   |
|          |       | guardrails   |       |              |
|          |       | memory_config|       |              |
+----------+       +------+-------+       +------+-------+
                          |                       |
                   +------+-------+        +------+-------+
                   |  MCP Server  |        |  Checkpoint  |
                   |              |        |              |
                   | id           |        | session_id   |
                   | tenant_id    |        | step_index   |
                   | transport    |        | state (JSON) |
                   | config       |        | timestamp    |
                   +------+-------+        +--------------+
                          |
                   +------+-------+        +--------------+
                   |    Tool      |        |   Memory     |
                   |              |        |  (pgvector)  |
                   | id           |        |              |
                   | server_id    |        | id           |
                   | namespace    |        | agent_id     |
                   | input_schema |        | content      |
                   | risk_level   |        | embedding    |
                   +------+-------+        | metadata     |
                                           +--------------+

          +--------------+       +--------------+
          |  Audit Log   |       | Trace Span   |
          | (append-only)|       |              |
          |              |       | trace_id     |
          | id           |       | span_id      |
          | session_id   |       | session_id   |
          | event_type   |       | operation    |
          | details      |       | duration     |
          | timestamp    |       | attributes   |
          +--------------+       +--------------+
```

### 6.2 Data Storage Strategy

| Data | Storage | Scope | Lifecycle | Access Pattern |
|------|---------|-------|-----------|----------------|
| Agent definitions | PostgreSQL | Per-tenant | Indefinite | CRUD, low frequency |
| Session state (hot) | Redis | Per-session | Session + 1h | Read/write every step |
| Session state (durable) | PostgreSQL | Per-session | Configurable retention | Checkpoint, crash recovery |
| Conversation history | Redis (buffer) | Per-session | Session + 1h | Append per step |
| Working memory | Redis Hash | Per-session | Session duration | Read/write per step |
| Long-term memory (Phase 2) | PG + pgvector | Per-agent | Configurable TTL | RAG search per LLM call |
| Tool registry | PostgreSQL | Per-tenant | Indefinite | Lookup per tool call |
| MCP server config | PostgreSQL | Per-tenant | Indefinite | Connection management |
| Trace spans | PostgreSQL | Per-session | 30 days default | Query for debugging |
| Audit logs | PostgreSQL (append-only) | Per-action | Indefinite | Compliance, forensics |
| Cost aggregates | PostgreSQL | Per-session/agent/tenant | Indefinite | Reporting, budget enforcement |

---

## 7. Technology Stack (Phase 1)

| Layer | Technology |
|-------|-----------|
| **Language** | Python 3.12+ |
| **Web Framework** | FastAPI |
| **Task Queue** | Redis Streams |
| **Primary DB** | PostgreSQL 16 |
| **Cache/State** | Redis 7 |
| **Vector Store** | pgvector (Phase 2) |
| **Tracing** | OpenTelemetry SDK |
| **Container** | Docker / K8s |
| **MCP Client** | Official MCP SDK |
| **CI/CD** | GitHub Actions |

---

## 8. API Surface (Phase 1)

```
# Agent Management
POST   /api/v1/agents                    Create agent
GET    /api/v1/agents                    List agents
GET    /api/v1/agents/{id}               Get agent
PUT    /api/v1/agents/{id}               Update agent
DELETE /api/v1/agents/{id}               Delete agent

# Session
POST   /api/v1/sessions                  Create + start session
GET    /api/v1/sessions/{id}             Get session state
POST   /api/v1/sessions/{id}/messages    Send message
POST   /api/v1/sessions/{id}/pause       Pause
POST   /api/v1/sessions/{id}/resume      Resume
GET    /api/v1/sessions/{id}/trace       Execution trace
GET    /api/v1/sessions/{id}/cost        Cost breakdown

# Streaming (Phase 1: SSE)
GET    /api/v1/sessions/{id}/stream      Real-time events (SSE)
# Note: WebSocket streaming -> Phase 2

# Tools
GET    /api/v1/tools                     List tools

# Memory (Phase 2)
POST   /api/v1/memory/{agent_id}         Store memory
GET    /api/v1/memory/{agent_id}/search  Semantic search

# Governance (Phase 1)
GET    /api/v1/audit/sessions/{id}       Audit trail for session
GET    /api/v1/audit/agents/{id}         Audit trail for agent
```

---

## 9. Deployment Architecture

```
+------------------- Kubernetes Cluster --------------------+
|                                                             |
|  +------------+  +------------+  +----------------------+  |
|  | API Gateway |  | Agent Mgmt |  | Session Service      |  |
|  | (2+ pods)   |  | (2+ pods)   |  | (2+ pods)            |  |
|  +------+------+  +------+-----+  +------+---------------+  |
|         +----------------+---------------+                   |
|                          v                                    |
|  +------------------------------------------------------+   |
|  | Executor Pool (3-N pods, HPA on queue depth)          |   |
|  +------------------------------------------------------+   |
|                          |                                    |
|  +------------+  +------v-----+  +----------------------+  |
|  | Redis (HA) |  | PostgreSQL |  | S3 / GCS             |  |
|  |            |  | (Primary + |  | (artifacts, archive)  |  |
|  |            |  |  Replica)  |  |                       |  |
|  +------------+  +------------+  +----------------------+  |
+-------------------------------------------------------------+
         | External
         v
LLM Providers (Anthropic Phase 1)  |  MCP Servers
```

---

## 10. Security Overview

```
Layer 1: API Gateway --- Auth (OAuth/API Key) + Rate Limit + TLS
Layer 2: Input --------- Prompt injection detection + Schema validation
Layer 3: Policy -------- Tool permission (RBAC) + Budget enforcement
Layer 4: Execution ----- Tenant isolation + Sandbox + Network policy
Layer 5: Output -------- Response filtering + PII masking
Layer 6: Governance ---- Immutable audit logs + Data classification + Retention enforcement
```

---

## 11. Cross-Cutting Concerns

| Concern | Implementation | Phase |
|---------|---------------|-------|
| **Authentication & Authorization** | API Gateway middleware (OAuth2/API Key), tenant routing | 1 |
| **Input/Output Safety** | Guardrails Engine (inbound + outbound pipeline) | 1 |
| **Observability** | OpenTelemetry SDK — spans cho mọi LLM call, tool call, step | 1 |
| **Cost Tracking** | Budget Controller + Event Bus -> Cost Calculator -> PG aggregates | 1 |
| **Audit Trail** | Governance Module — mọi action logged immutable | 1 |
| **Data Retention** | Governance Module — policy-based cleanup (session data, logs, memories) | 1 |
| **Data Classification** | Governance Module — sensitivity tagging cho data in transit | 1 |
| **Tenant Isolation** | Row-Level Security (PostgreSQL) + Redis key namespacing | 1 |
| **Error Resilience** | Circuit breaker (tools), retry with backoff (LLM), checkpoint (state) | 1 |
| **Real-time Streaming** | Event Bus -> Redis Pub/Sub -> SSE Handler (Phase 1), WebSocket (Phase 2) | 1 |

---

## 12. Architecture Decision Records (ADR)

| # | Quyết định | Trade-off |
|---|-----------|-----------|
| ADR-001 | Python làm ngôn ngữ chính | Không tối ưu perf như Go/Rust |
| ADR-002 | Stateless executor + externalized state | Thêm latency state load/save |
| ADR-003 | Redis Streams cho task queue. Dead-letter queue logic Phase 1 | Có thể cần Kafka ở scale lớn |
| ADR-004 | PostgreSQL + pgvector all-in-one | Cần specialized stores sau |
| ADR-005 | MCP làm chuẩn tool integration | Providers phải implement MCP |
| ADR-006 | FastAPI | N/A |
| ADR-007 | OpenTelemetry tracing | Setup complexity |
| ADR-008 | Row-level security cho tenant isolation | Dedicated DB cho high-sec |
| ADR-009 | Event-driven execution (mỗi step emit events) | Event ordering complexity, eventual consistency |
| ADR-010 | Governance as module (Phase 1), service-ready interface | Cross-cutting logic nằm trong cùng process |
| ADR-011 | SSE cho real-time streaming Phase 1 (unidirectional) | WebSocket Phase 2 cho bidirectional |
| ADR-012 | TaskQueue abstraction interface — decouple queue implementation từ consumer logic. Cho phép swap Redis Streams -> Kafka không cần rewrite consumers | Interface overhead |
| ADR-013 | Delta-based checkpoint — lưu incremental changes (messages mới, tool results) thay vì full session state mỗi step. Full snapshot định kỳ hoặc cuối session | Replay complexity khi restore |

---

## 13. Detailed Design Documents

| Component | Tài liệu | Mô tả |
|-----------|----------|-------|
| **Guardrails** | [`guardrails.md`](guardrails.md) | Input/output validation, prompt injection, policy engine |
| **Memory** | [`memory.md`](memory.md) | Memory stack, vector store, context management, shared memory |
| **Planning** | [`planning.md`](planning.md) | ReAct, Plan-then-Execute, checkpoint, budget, orchestration |
| **MCP & Tools** | [`mcp-tools.md`](mcp-tools.md) | MCP client, tool registry, discovery, invocation, sandbox |
| **Governance** | [`governance.md`](governance.md) | Audit consolidation, retention policies, data classification, lineage |
| **LLM Gateway** | [`llm-gateway.md`](llm-gateway.md) | Provider abstraction, token tracking, failover, error taxonomy (PENDING — validate via spike) |

---

## 14. Directory Structure (Phase 1)

```
agent-platform/
├── src/
│   ├── api/                    # API layer (routes, middleware, SSE)
│   ├── services/               # Business logic (agent, session, tool, memory)
│   ├── engine/                 # Execution engine (executor, react, planner, checkpoint)
│   ├── providers/              # External (llm/, mcp/)
│   ├── governance/             # Data governance (audit, retention, classification)
│   ├── store/                  # Data access (postgres/, redis/, memory/)
│   ├── core/                   # Shared (models, config, events, errors, security, tracing)
│   └── main.py
├── sdk/python/                 # Python SDK
├── tests/                      # unit/ integration/ e2e/
├── deploy/                     # docker/ k8s/
└── docs/                       # Documentation
```
