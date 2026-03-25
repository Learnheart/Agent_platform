# Kiến Trúc Tổng Quan: Agent Serving Platform

> **Phiên bản:** 2.0
> **Ngày cập nhật:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect

---

## 1. Tầm Nhìn Kiến Trúc

Agent Platform là một **serving infrastructure** cho AI agent — không phải framework hay library, mà là một nền tảng vận hành. Platform nhận agent definition, thực thi chúng trên hạ tầng có khả năng mở rộng, và cung cấp toàn bộ cross-cutting concerns (security, observability, cost tracking, data governance) mà mọi agent đều cần.

**Ranh giới hệ thống:**

```
                    ┌─────────────────────────────────────────────────────────┐
                    │               AGENT PLATFORM (our system)               │
                    │                                                         │
  Developers ──────▶│  SDK / API / CLI                                        │
                    │       │                                                 │
                    │       ▼                                                 │
                    │  Agent Management ─── Session ─── Execution Engine      │
                    │       │                  │              │               │
                    │       │           ┌──────┴──────┐      │               │
                    │       │           │ Cross-Cutting│      │               │
                    │       │           │ Guardrails   │      │               │
                    │       │           │ Governance   │      │               │
                    │       │           │ Tracing      │      │               │
                    │       │           └──────────────┘      │               │
                    │       │                                 │               │
                    │       ▼                                 ▼               │
                    │  PostgreSQL / Redis            LLM GW / Tool RT        │
                    │                                   │         │           │
                    └───────────────────────────────────┼─────────┼───────────┘
                                                        │         │
                                                        ▼         ▼
                                                  LLM Providers  MCP Servers
                                                  (Anthropic,    (DB, GitHub,
                                                   OpenAI, ...)   Slack, ...)
```

**Platform chịu trách nhiệm:** runtime execution, state management, security, observability, cost control, data governance.
**Developer chịu trách nhiệm:** agent logic (system prompt, tool selection, model config).

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            CLIENT LAYER                                  │
│    SDK (Python/TS)  │  REST API  │  WebSocket  │  Webhook Consumer       │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────────┐
│                           API GATEWAY                                    │
│              Auth  │  Rate Limit  │  Tenant Routing  │  TLS              │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐    ┌──────────────────┐    ┌──────────────────┐
│    Agent      │    │    Session       │    │    Admin          │
│    Management │    │    Service       │    │    Service        │
│    Service    │    │                  │    │                  │
└───────┬───────┘    └────────┬─────────┘    └──────────────────┘
        │                     │
        │              ┌──────▼───────┐
        │              │  Task Queue  │
        │              │ (Redis Strm) │
        │              └──────┬───────┘
        │                     │
        │           ┌─────────▼──────────┐
        │           │   EXECUTOR POOL    │
        │           │ ┌────┐┌────┐┌────┐ │
        │           │ │ E1 ││ E2 ││ EN │ │    ← Stateless, auto-scaled
        │           │ └──┬─┘└──┬─┘└──┬─┘ │
        │           └────┼─────┼─────┼───┘
        │                │     │     │
┌───────┼────────────────┼─────┼─────┼───────────────────────────────────┐
│       │          INFRASTRUCTURE LAYER                                   │
│       ▼                ▼     ▼     ▼                                   │
│  ┌─────────┐   ┌───────────────┐   ┌───────────────┐                  │
│  │  State  │   │  LLM Gateway  │   │ Tool Runtime  │                  │
│  │  Store  │   │               │   │ (MCP Client)  │                  │
│  │(Redis+PG│   │ Claude│GPT│   │   │               │                  │
│  │)        │   │ Gemini│Custom│ │   │ ┌───┐┌───┐   │                  │
│  └─────────┘   └───────────────┘   │ │MCP││MCP│   │                  │
│  ┌─────────┐                       │ │Svr││Svr│   │                  │
│  │ Memory  │   ┌───────────────┐   │ └───┘└───┘   │                  │
│  │ Store   │   │ Trace Store   │   └───────────────┘                  │
│  │(pgvector│   │ (OTel → PG)  │                                       │
│  │)        │   └───────────────┘                                       │
│  └─────────┘                                                           │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Design Principles

Các nguyên tắc thiết kế ở tầng chiến lược — hướng dẫn mọi quyết định kiến trúc và sản phẩm. Các quyết định kỹ thuật cụ thể (Stateless Executors, Event-Driven...) nằm trong [ADR](#12-architecture-decision-records-adr).

| # | Nguyên tắc | Ý nghĩa |
|---|-----------|---------|
| 1 | **Platform, not Framework** | Cung cấp hạ tầng serving, không chỉ là SDK/library. Platform lo cross-cutting concerns, developer lo agent logic |
| 2 | **API-First** | Mọi tính năng accessible qua API trước, UI là lớp bọc. Documentation-first |
| 3 | **Model-Agnostic** | Abstraction layer cho LLM providers, không lock-in vào một provider |
| 4 | **MCP-Native** | Adopt MCP làm chuẩn tích hợp tool chính. De facto standard |
| 5 | **Secure by Default** | Permission, isolation, audit ở tầng platform, không phải prompt |
| 6 | **Observable from Day 1** | Tracing, metrics, cost tracking built-in từ đầu |
| 7 | **Progressive Complexity** | Đơn giản cho use case cơ bản, mạnh mẽ cho use case phức tạp |

---

## 4. Core Components

### 4.1 Component Map

```
┌──── API Layer ─────────────────────────────────────────────┐
│  REST Controller │ WebSocket Handler │ Auth Middleware      │
└─────────────────────────────┬──────────────────────────────┘
                              │
┌──── Core Services ──────────▼──────────────────────────────┐
│  Agent Manager │ Session Manager │ Tool Manager │ Memory Mgr│
└─────────────────────────────┬──────────────────────────────┘
                              │
┌──── Execution Engine ───────▼──────────────────────────────┐
│  ┌─────────────────────────────────────────────────────┐   │
│  │                Agent Executor                        │   │
│  │  Planning Engine │ ReAct Engine │ Context Manager   │   │
│  │  Checkpoint Mgr  │ Budget Enforcer │ Event Emitter  │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                LLM Gateway                           │   │
│  │  Abstraction Interface (model-agnostic contract)     │   │
│  │  Anthropic (P0) │ OpenAI (P1) │ More (Phase 2)      │   │
│  │  Token Tracker │ Rate Limiter │ Failover │ Cache    │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────┘

┌──── Cross-Cutting ─────────────────────────────────────────┐
│  Guardrails Engine │ Governance Module │ Tracing (OTel)     │
│  Cost Calculator   │ Audit Logger      │ Event Bus          │
└────────────────────────────────────────────────────────────┘

┌──── Infrastructure ────────────────────────────────────────┐
│  PostgreSQL (+pgvector) │ Redis (State + Queue) │ S3/GCS   │
└────────────────────────────────────────────────────────────┘
```

### 4.2 Component Summary

| Component | Trách nhiệm | Technology |
|-----------|-------------|------------|
| **API Gateway** | Auth, rate limit, routing, TLS | FastAPI + middleware |
| **Agent Manager** | CRUD agent definitions, versioning, config | FastAPI + PostgreSQL |
| **Session Manager** | Session lifecycle, state machine, query | FastAPI + Redis + PG |
| **Tool Manager** | Tool registry, MCP connection, permission check | MCP SDK + PG |
| **Memory Manager** | Short-term context, long-term vector search | pgvector + Redis |
| **Executor** | Reasoning loop, checkpoint, budget enforcement | Python async workers |
| **Planning Engine** | Plan-then-Execute, ReAct, re-planning | Built-in (Python) |
| **LLM Gateway** | Multi-provider, token tracking, failover, cache | httpx + provider SDKs |
| **Guardrails Engine** | Input/output validation, prompt injection detection | Middleware pipeline |
| **Governance Module** | Audit consolidation, retention policies, data classification | Internal module (Phase 1), service-ready interface |
| **Tracing** | Span collection, metrics export | OpenTelemetry SDK |
| **Event Bus** | Event emission cho tracing, streaming, audit, webhook | Redis Pub/Sub + OTel |

### 4.3 Component Interaction Matrix

Mỗi ô cho biết component ở cột **gọi đến** component ở hàng.

```
                  Agent   Session  Tool    Memory  Executor  LLM GW  Guard   Govern  Event
                  Mgr     Mgr      Mgr     Mgr               rails   ance    Bus
  ────────────────────────────────────────────────────────────────────────────────────────
  API Layer       ✓       ✓        ✓       ✓                                  ✓
  Agent Mgr                                                           ✓       ✓
  Session Mgr                                      ✓(enqueue)                 ✓
  Executor                         ✓       ✓                ✓  ✓     ✓       ✓
  LLM Gateway                                                                 ✓
  Tool Runtime                                                                ✓
  Guardrails                                                          ✓       ✓
  Governance                                                                  ✓(consume)
```

**Luồng phụ thuộc chính:**
- **Executor** là hub trung tâm — gọi đến hầu hết components
- **Event Bus** là backbone — mọi component emit events, Governance và Tracing consume
- **Guardrails** là gateway — chặn trước mọi LLM call và tool call

---

## 5. Luồng Xử Lý Hệ Thống (End-to-End Flows)

### 5.1 Luồng Tổng Quan: Từ API Request đến Response

Đây là luồng **đầy đủ** khi client gửi message đến agent, bao gồm tất cả cross-cutting concerns.

```
┌──────┐     ┌─────────┐     ┌─────────┐     ┌──────────┐     ┌──────────┐
│Client│────→│API Layer│────→│Session  │────→│Task Queue│────→│Executor  │
│      │     │         │     │Manager  │     │(Redis)   │     │Pool      │
└──────┘     └─────────┘     └─────────┘     └──────────┘     └────┬─────┘
   ▲              │                                                 │
   │              │            ┌────────────────────────────────────┘
   │              │            │
   │              │            ▼
   │              │    ┌───────────────── EXECUTION LOOP ──────────────────┐
   │              │    │                                                    │
   │              │    │  ┌──────────┐   ┌───────────┐   ┌─────────────┐  │
   │              │    │  │Checkpoint│──→│  Context   │──→│ Guardrails  │  │
   │              │    │  │ Restore  │   │ Assembly   │   │ (Inbound)   │  │
   │              │    │  └──────────┘   └───────────┘   └──────┬──────┘  │
   │              │    │                                         │         │
   │              │    │                                  ┌──────▼──────┐  │
   │              │    │                                  │ LLM Gateway │  │
   │              │    │                                  │ (LLM Call)  │  │
   │              │    │                                  └──────┬──────┘  │
   │              │    │                                         │         │
   │              │    │                                  ┌──────▼──────┐  │
   │              │    │                                  │ Guardrails  │  │
   │              │    │                                  │ (Outbound)  │  │
   │              │    │                                  └──────┬──────┘  │
   │              │    │                                         │         │
   │              │    │                         ┌───────────────┤         │
   │              │    │                         │               │         │
   │              │    │              ┌──────────▼──┐   ┌───────▼───────┐ │
   │              │    │              │ Tool Call?   │   │ Final Answer? │ │
   │              │    │              │ YES          │   │ YES           │ │
   │              │    │              └──────┬───────┘   └───────┬───────┘ │
   │              │    │                     │                   │         │
   │              │    │              ┌──────▼───────┐           │         │
   │              │    │              │ Guardrails   │           │         │
   │              │    │              │ (Permission) │           │         │
   │              │    │              └──────┬───────┘           │         │
   │              │    │                     │                   │         │
   │              │    │              ┌──────▼───────┐           │         │
   │              │    │              │ Tool Runtime │           │         │
   │              │    │              │ (MCP Call)   │           │         │
   │              │    │              └──────┬───────┘           │         │
   │              │    │                     │                   │         │
   │              │    │              ┌──────▼───────┐           │         │
   │              │    │              │ Memory       │           │         │
   │              │    │              │ Update       │           │         │
   │              │    │              └──────┬───────┘           │         │
   │              │    │                     │                   │         │
   │              │    │              ┌──────▼───────┐           │         │
   │              │    │              │ Checkpoint   │           │         │
   │              │    │              │ Save         │           │         │
   │              │    │              └──────┬───────┘           │         │
   │              │    │                     │                   │         │
   │              │    │                     ▼                   │         │
   │              │    │              LOOP (next step)           │         │
   │              │    │                                         │         │
   │              │    └─────────────────────────────────────────┘         │
   │              │                                              │
   │◄─────────────┼──────── WebSocket Stream (events) ──────────┘
   │              │
   │              │    ┌─────────────────────────────────────────┐
   │              │    │        CROSS-CUTTING (mọi step)         │
   │              │    │                                         │
   │              │    │  Event Bus ──→ OTel Trace Store         │
   │              │    │           ──→ Governance (audit sink)   │
   │              │    │           ──→ WebSocket (client stream) │
   │              │    │           ──→ Webhook (external notify) │
   │              │    │           ──→ Cost Calculator           │
   │              │    └─────────────────────────────────────────┘
```

### 5.2 Luồng Chi Tiết: Một Step Thực Thi (Sequence Diagram)

```
Client     API GW    Session   Queue    Executor   Memory    Guardrails  LLM GW    Tool RT   Checkpoint  Event Bus  Governance
 │           │         │         │         │          │          │          │          │          │           │          │
 │──POST ───→│         │         │         │          │          │          │          │          │           │          │
 │ /sessions │         │         │          │          │          │          │          │          │           │          │
 │ /{id}/msg │         │         │         │          │          │          │          │          │           │          │
 │           │──auth──→│         │         │          │          │          │          │          │           │          │
 │           │  + rate │         │         │          │          │          │          │          │           │          │
 │           │  limit  │         │         │          │          │          │          │          │           │          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │           │         │──store  │         │          │          │          │          │          │           │          │
 │           │         │  msg    │         │          │          │          │          │          │           │          │
 │           │         │──enqueue──────→   │          │          │          │          │          │           │          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │◄──202─────│         │         │         │          │          │          │          │          │           │          │
 │ Accepted  │         │         │         │          │          │          │          │          │           │          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │ ═══ WS ══════════════════════════════════ (client connects WebSocket for streaming) ═══════════════════════          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │           │         │         │──pull──→│          │          │          │          │          │           │          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │           │         │         │         │──restore─────────────────────────────────────────→│           │          │
 │           │         │         │         │◄──state──────────────────────────────────────────│           │          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │           │         │         │         │──build───→│         │          │          │          │           │          │
 │           │         │         │         │  context  │         │          │          │          │           │          │
 │           │         │         │         │◄─payload──│         │          │          │          │           │          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │           │         │         │         │──inbound─────────→│          │          │          │           │          │
 │           │         │         │         │  check    │        │          │          │          │           │          │
 │           │         │         │         │◄─pass─────────────│          │          │          │           │          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │           │         │         │         │──chat(messages, tools)──────→│          │          │           │          │
 │◄══ thought (WS stream) ══════│         │◄──response (tool_call)───────│          │          │           │          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │           │         │         │         │──permission check──→│         │          │          │           │          │
 │           │         │         │         │◄──ALLOW────────────│         │          │          │           │          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │◄══ tool_call (WS) ══════════│         │──invoke──────────────────────────────→│          │           │          │
 │           │         │         │         │◄──result──────────────────────────────│          │           │          │
 │◄══ observation (WS) ════════│         │          │          │          │          │          │           │          │
 │           │         │         │         │──outbound check───→│          │          │          │           │          │
 │           │         │         │         │◄──pass─────────────│          │          │          │           │          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │           │         │         │         │──update──→│         │          │          │          │           │          │
 │           │         │         │         │  memory   │         │          │          │          │           │          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │           │         │         │         │──save────────────────────────────────────────────→│           │          │
 │           │         │         │         │  checkpoint          │          │          │          │           │          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │           │         │         │         │──emit events──────────────────────────────────────────────────→│          │
 │           │         │         │         │          │          │          │          │          │           │──audit──→│
 │           │         │         │         │          │          │          │          │          │           │──trace──→│(OTel)
 │           │         │         │         │          │          │          │          │          │           │──cost───→│(calc)
 │           │         │         │         │          │          │          │          │          │           │          │
 │           │         │         │         │ [if not final: enqueue next step]        │          │           │          │
 │           │         │         │         │ [if final: return answer]                │          │           │          │
 │           │         │         │         │          │          │          │          │          │           │          │
 │◄══ final_answer (WS) ═══════│         │          │          │          │          │          │           │          │
```

### 5.3 Luồng Multi-Step Execution (Macro View)

Một session thường chạy **nhiều step**. Đây là cách chúng chain lại:

```
Client sends message
        │
        ▼
┌── Queue ◄──────────────────────────────────────────────────────┐
│       │                                                         │
│       ▼                                                         │
│   Executor pulls task                                           │
│       │                                                         │
│       ▼                                                         │
│   ┌─ STEP 1 ───────────────────────────────────────────────┐   │
│   │ Restore checkpoint (empty — new session)                │   │
│   │ Build context: [system_prompt + user_message]           │   │
│   │ Guardrails inbound: ✅                                  │   │
│   │ LLM call → response: tool_call(search_database)        │   │
│   │ Guardrails permission: ✅                               │   │
│   │ Tool call → result: [{rows...}]                        │   │
│   │ Guardrails outbound: ✅                                 │   │
│   │ Memory update: append messages                          │   │
│   │ Checkpoint save: step=1                                 │   │
│   │ Events: thought, tool_call, observation                 │   │
│   │ Result: TOOL_CALL → continue                            │   │
│   └─────────────────────────────────────────────────────────┘   │
│       │                                                         │
│       │ enqueue next step ──────────────────────────────────────┘
│       ▼
│   ┌─ STEP 2 ───────────────────────────────────────────────┐
│   │ Restore checkpoint (step=1)                             │
│   │ Build context: [system + history + tool_result]         │
│   │ Guardrails inbound: ✅                                  │
│   │ LLM call → response: tool_call(send_email)             │
│   │ Guardrails permission: ⚠️ REQUIRES_APPROVAL            │
│   │ HITL gate → session state: WAITING_INPUT                │
│   │ Checkpoint save: step=2, paused                         │
│   │ Events: tool_call, approval_requested                   │
│   │ Result: WAITING_INPUT → pause                           │
│   └─────────────────────────────────────────────────────────┘
│
│   ... human approves via WebSocket/webhook ...
│
│   ┌─ STEP 3 (resumed) ─────────────────────────────────────┐
│   │ Restore checkpoint (step=2)                             │
│   │ Execute approved tool call: send_email                  │
│   │ LLM call with all context → final_answer                │
│   │ Guardrails outbound: ✅                                 │
│   │ Memory update: append final answer                      │
│   │ Checkpoint save: step=3, completed                      │
│   │ Events: tool_result, final_answer                       │
│   │ Result: FINAL_ANSWER → done                             │
│   └─────────────────────────────────────────────────────────┘
│
▼
Session state: COMPLETED
Total: 3 steps, 3 LLM calls, 2 tool calls, 1 HITL approval
Cost: tracked per step, aggregated to session/agent/tenant
```

### 5.4 Session State Machine

```
    CREATED ──start()──→ RUNNING ──complete()──→ COMPLETED
                           │  ▲
                  pause()  │  │ resume()
                           ▼  │
                         PAUSED
                           │
                  timeout  │
                           ▼
                         FAILED
                           ▲
                           │ error/timeout
                         RUNNING ──wait_input()──→ WAITING_INPUT
```

### 5.5 Luồng Agent Creation & Configuration

```
Developer        SDK/API         Agent Manager      Tool Manager      PostgreSQL
 │                  │                 │                   │                │
 │──create_agent()─→│                 │                   │                │
 │  {name,          │                 │                   │                │
 │   system_prompt, │                 │                   │                │
 │   model_config,  │                 │                   │                │
 │   tools: [...],  │                 │                   │                │
 │   guardrails,    │                 │                   │                │
 │   memory_config} │                 │                   │                │
 │                  │──POST /agents──→│                   │                │
 │                  │                 │                   │                │
 │                  │                 │──validate config   │                │
 │                  │                 │  (schema, model,   │                │
 │                  │                 │   budget limits)   │                │
 │                  │                 │                   │                │
 │                  │                 │──verify tools─────→│                │
 │                  │                 │  "do these tools   │                │
 │                  │                 │   exist & active?"  │                │
 │                  │                 │◄──verified──────────│                │
 │                  │                 │                   │                │
 │                  │                 │──INSERT agent──────────────────────→│
 │                  │                 │◄──agent_id─────────────────────────│
 │                  │                 │                   │                │
 │                  │◄──agent_id──────│                   │                │
 │◄──agent created──│                 │                   │                │
 │                  │                 │                   │                │
 │  (agent is now ready to receive sessions)              │                │
```

### 5.6 Luồng Cross-Cutting: Events Flow Through System

Mọi action trong hệ thống emit events. Các hệ thống downstream consume events theo nhu cầu.

```
    Executor / Services
         │
         │ emit(AgentEvent)
         ▼
   ┌───────────────────── EVENT BUS ─────────────────────────┐
   │                                                          │
   │  event types:                                            │
   │  step_start, llm_call_start, llm_call_end, thought,     │
   │  tool_call, tool_result, checkpoint, budget_warning,     │
   │  plan_created, plan_step_end, replan, final_answer,      │
   │  error, session_created, session_completed               │
   │                                                          │
   └──┬──────────┬──────────────┬──────────────┬──────────────┘
      │          │              │              │
      ▼          ▼              ▼              ▼
 ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌────────────┐
 │  OTel   │ │ WebSocket│ │Governance│ │  Webhook   │
 │ Exporter│ │ Streamer │ │ Module   │ │  Notifier  │
 │         │ │          │ │          │ │            │
 │ → Trace │ │ → Client │ │ → Audit  │ │ → External │
 │   Store │ │   (live) │ │ → Cost   │ │   systems  │
 │ (PG)    │ │          │ │ → Retain │ │            │
 └─────────┘ └──────────┘ └─────────┘ └────────────┘
```

### 5.7 Luồng Error & Recovery

```
┌──── Failure Scenario ──────────────────────── Recovery ─────────────────────┐
│                                                                              │
│  Executor crash (mid-step)         Task not ACKed → re-delivered from queue  │
│       │                            New executor restores from checkpoint     │
│       ▼                            Resumes from last saved step              │
│  Task timeout in queue                                                       │
│                                                                              │
│  LLM API error                     Retry with exponential backoff (3x)      │
│       │                            If persistent → failover to secondary    │
│       ▼                            provider (if configured)                  │
│  LLM rate limit                    Queue + delay + retry                     │
│                                                                              │
│  Tool execution timeout            Return error as observation to LLM       │
│       │                            LLM decides: retry, use different tool,  │
│       ▼                            or answer without tool result             │
│  MCP server crash (stdio)          Auto-restart (up to max_restarts)        │
│                                    Re-discover tools, update registry       │
│                                                                              │
│  Budget exceeded                   Inject "wrap up" at 90%                  │
│       │                            Force stop at 100%, return partial result │
│       ▼                                                                      │
│  Guardrail blocked                 Return error to client (inbound)         │
│                                    Or block response + log (outbound)        │
│                                                                              │
│  Redis unavailable                 Checkpoint: fallback to PG (slower)      │
│                                    Rate limit: use local cache (~1min stale) │
│                                    Memory: degrade gracefully (no STM)       │
│                                                                              │
│  PostgreSQL unavailable            Platform enters read-only mode            │
│                                    Active sessions continue (Redis state)    │
│                                    New sessions blocked until recovery       │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Data Model Overview

### 6.1 Entity Relationships

```
┌──────────┐       ┌──────────────┐       ┌──────────────┐
│  Tenant  │──1:N──│    Agent     │──1:N──│   Session    │
│          │       │              │       │              │
│ id       │       │ id           │       │ id           │
│ name     │       │ tenant_id    │       │ agent_id     │
│ config   │       │ name         │       │ state        │
│          │       │ system_prompt│       │ step_index   │
│          │       │ model_config │       │ usage        │
│          │       │ tools_config │       │ created_at   │
│          │       │ guardrails   │       │              │
│          │       │ memory_config│       │              │
└──────────┘       └──────┬───────┘       └──────┬───────┘
                          │                       │
                   ┌──────┴───────┐        ┌──────┴───────┐
                   │  MCP Server  │        │  Checkpoint  │
                   │              │        │              │
                   │ id           │        │ session_id   │
                   │ tenant_id    │        │ step_index   │
                   │ transport    │        │ state (JSON) │
                   │ config       │        │ timestamp    │
                   └──────┬───────┘        └──────────────┘
                          │
                   ┌──────┴───────┐        ┌──────────────┐
                   │    Tool      │        │   Memory     │
                   │              │        │  (pgvector)  │
                   │ id           │        │              │
                   │ server_id    │        │ id           │
                   │ namespace    │        │ agent_id     │
                   │ input_schema │        │ content      │
                   │ risk_level   │        │ embedding    │
                   └──────────────┘        │ metadata     │
                                           └──────────────┘

          ┌──────────────┐       ┌──────────────┐
          │  Audit Log   │       │ Trace Span   │
          │ (append-only)│       │              │
          │              │       │ trace_id     │
          │ id           │       │ span_id      │
          │ session_id   │       │ session_id   │
          │ event_type   │       │ operation    │
          │ details      │       │ duration     │
          │ timestamp    │       │ attributes   │
          └──────────────┘       └──────────────┘
```

### 6.2 Data Storage Strategy

| Data | Storage | Scope | Lifecycle | Access Pattern |
|------|---------|-------|-----------|----------------|
| Agent definitions | PostgreSQL | Per-tenant | Indefinite | CRUD, low frequency |
| Session state (hot) | Redis | Per-session | Session + 1h | Read/write every step |
| Session state (durable) | PostgreSQL | Per-session | Configurable retention | Checkpoint, crash recovery |
| Conversation history | Redis (buffer) | Per-session | Session + 1h | Append per step |
| Working memory | Redis Hash | Per-session | Session duration | Read/write per step |
| Long-term memory | PG + pgvector | Per-agent | Configurable TTL | RAG search per LLM call |
| Tool registry | PostgreSQL | Per-tenant | Indefinite | Lookup per tool call |
| MCP server config | PostgreSQL | Per-tenant | Indefinite | Connection management |
| Trace spans | PostgreSQL | Per-session | 30 days default | Query for debugging |
| Audit logs | PostgreSQL (append-only) | Per-action | Indefinite | Compliance, forensics |
| Cost aggregates | PostgreSQL | Per-session/agent/tenant | Indefinite | Reporting, budget enforcement |

---

## 7. Technology Stack (Phase 1)

| Layer | Technology | Lý do |
|-------|-----------|-------|
| **Language** | Python 3.12+ | AI/ML ecosystem, MCP SDK, FastAPI |
| **Web Framework** | FastAPI | Async-native, OpenAPI, WebSocket |
| **Task Queue** | Redis Streams | Lightweight, fast, built-in Redis |
| **Primary DB** | PostgreSQL 16 | Reliable, pgvector, JSONB |
| **Cache/State** | Redis 7 | Sub-ms, Streams, pub/sub |
| **Vector Store** | pgvector | Minimize infra (embedded in PG) |
| **Tracing** | OpenTelemetry SDK | Industry standard |
| **Container** | Docker / K8s | Standard orchestration |
| **MCP Client** | Official MCP SDK | Standard implementation |
| **CI/CD** | GitHub Actions | Integrated |

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

# WebSocket
WS     /api/v1/sessions/{id}/stream      Real-time events

# Tools
GET    /api/v1/tools                     List tools

# Memory (Phase 1-2, khi long-term memory enabled)
POST   /api/v1/memory/{agent_id}         Store memory
GET    /api/v1/memory/{agent_id}/search  Semantic search

# Governance (Phase 1)
GET    /api/v1/audit/sessions/{id}       Audit trail for session
GET    /api/v1/audit/agents/{id}         Audit trail for agent
```

---

## 9. Deployment Architecture

```
┌──────────────────── Kubernetes Cluster ────────────────────┐
│                                                             │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────────┐ │
│  │ API Gateway │  │ Agent Mgmt │  │ Session Service      │ │
│  │ (2+ pods)   │  │ (2+ pods)   │  │ (2+ pods)            │ │
│  └──────┬──────┘  └──────┬─────┘  └──────┬───────────────┘ │
│         └────────────────┼───────────────┘                  │
│                          ▼                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Executor Pool (3-N pods, HPA on queue depth)         │   │
│  └──────────────────────────────────────────────────────┘   │
│                          │                                   │
│  ┌────────────┐  ┌──────▼─────┐  ┌──────────────────────┐ │
│  │ Redis (HA) │  │ PostgreSQL │  │ S3 / GCS             │ │
│  │            │  │ (Primary + │  │ (artifacts, archive)  │ │
│  │            │  │  Replica)  │  │                       │ │
│  └────────────┘  └────────────┘  └──────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
         │ External
         ▼
LLM Providers (Anthropic, OpenAI, Google)  │  MCP Servers
```

---

## 10. Security Overview

```
Layer 1: API Gateway ─── Auth (OAuth/API Key) + Rate Limit + TLS
Layer 2: Input ───────── Prompt injection detection + Schema validation
Layer 3: Policy ──────── Tool permission (RBAC) + Budget enforcement
Layer 4: Execution ───── Tenant isolation + Sandbox + Network policy
Layer 5: Output ──────── Response filtering + PII masking
Layer 6: Governance ──── Immutable audit logs + Data classification + Retention enforcement
```

---

## 11. Cross-Cutting Concerns

Những concerns xuyên suốt mọi component, được xử lý ở tầng platform:

| Concern | Implementation | Phase |
|---------|---------------|-------|
| **Authentication & Authorization** | API Gateway middleware (OAuth2/API Key), tenant routing | 1 |
| **Input/Output Safety** | Guardrails Engine (inbound + outbound pipeline) | 1 |
| **Observability** | OpenTelemetry SDK — spans cho mọi LLM call, tool call, step | 1 |
| **Cost Tracking** | Budget Controller + Event Bus → Cost Calculator → PG aggregates | 1 |
| **Audit Trail** | Governance Module — mọi action logged immutable | 1 |
| **Data Retention** | Governance Module — policy-based cleanup (session data, logs, memories) | 1 |
| **Data Classification** | Governance Module — sensitivity tagging cho data in transit | 1 |
| **Tenant Isolation** | Row-Level Security (PostgreSQL) + Redis key namespacing | 1 |
| **Error Resilience** | Circuit breaker (tools), retry with backoff (LLM), checkpoint (state) | 1 |
| **Real-time Streaming** | Event Bus → Redis Pub/Sub → WebSocket Handler | 1 |

---

## 12. Architecture Decision Records (ADR)

| # | Quyết định | Lý do | Trade-off |
|---|-----------|-------|-----------|
| ADR-001 | Python làm ngôn ngữ chính | AI/ML ecosystem, MCP SDK | Không tối ưu perf như Go/Rust |
| ADR-002 | Stateless executor + externalized state | Scaling, fault tolerance | Thêm latency state load/save |
| ADR-003 | Redis Streams cho task queue | Lightweight, đủ Phase 1 | Có thể cần Kafka ở scale lớn |
| ADR-004 | PostgreSQL + pgvector all-in-one | Giảm infra complexity | Cần specialized stores sau |
| ADR-005 | MCP làm chuẩn tool integration | De facto standard | Providers phải implement MCP |
| ADR-006 | FastAPI | Async, OpenAPI, WebSocket | N/A (clear winner) |
| ADR-007 | OpenTelemetry tracing | Industry standard, neutral | Setup complexity |
| ADR-008 | Row-level security cho tenant isolation | Đơn giản cho Phase 1 | Dedicated DB cho high-sec |
| ADR-009 | Event-driven execution (mọi step emit events) | Enables tracing, streaming, audit, webhook từ cùng một cơ chế | Event ordering complexity, eventual consistency |
| ADR-010 | Governance as module (Phase 1), service-ready interface | Avoid premature microservice, nhưng sẵn sàng tách khi cần | Cross-cutting logic nằm trong cùng process |

---

## 13. Detailed Design Documents

Các component phức tạp có thiết kế chi tiết riêng:

| Component | Tài liệu | Mô tả |
|-----------|----------|-------|
| **Guardrails** | [`guardrails/design.md`](guardrails/design.md) | Input/output validation, prompt injection, policy engine |
| **Memory** | [`memory/design.md`](memory/design.md) | Memory stack, vector store, context management, shared memory |
| **Planning** | [`planning/design.md`](planning/design.md) | ReAct, Plan-then-Execute, checkpoint, budget, orchestration |
| **MCP & Tools** | [`mcp-tools/design.md`](mcp-tools/design.md) | MCP client, tool registry, discovery, invocation, sandbox |
| **Governance** | [`governance/design.md`](governance/design.md) | Audit consolidation, retention policies, data classification, lineage |

---

## 14. Directory Structure (Phase 1)

```
agent-platform/
├── src/
│   ├── api/                    # API layer (routes, middleware, websocket)
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
