# Kiến Trúc Tổng Quan: Agent Serving Platform

> **Phiên bản:** 1.1
> **Ngày cập nhật:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect

---

## 1. Tầm Nhìn Kiến Trúc

Agent Platform là một **serving infrastructure** cho AI agent — không phải framework hay library, mà là một nền tảng vận hành. Platform nhận agent definition, thực thi chúng trên hạ tầng có khả năng mở rộng, và cung cấp toàn bộ cross-cutting concerns (security, observability, cost tracking) mà mọi agent đều cần.

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

Các nguyên tắc thiết kế ở tầng chiến lược — hướng dẫn mọi quyết định kiến trúc và sản phẩm. Các quyết định kỹ thuật cụ thể (Stateless Executors, Event-Driven...) nằm trong [ADR](#10-architecture-decision-records-adr).

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
│  Guardrails Engine │ Tracing (OTel) │ Cost Calc │ Audit Log│
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
| **Tracing** | Span collection, metrics export | OpenTelemetry SDK |
| **Audit Logger** | Immutable action logging, compliance | PostgreSQL (append-only) |

---

## 5. Luồng Dữ Liệu Chính

### 5.1 Session Execution (1 Step)

```
Queue ──pull──→ Executor ──load──→ State Store
                    │
                    ├──build prompt──→ [system + history + tools]
                    │
                    ├──call──→ LLM Gateway ──→ LLM Provider
                    │              │
                    │         ◄──response──
                    │
                    ├── [if tool_call] ──→ Guardrails (validate)
                    │                          │
                    │                     ──→ Tool Runtime ──→ MCP Server
                    │                          │
                    │                     ◄──result──
                    │
                    ├──save──→ State Store (checkpoint)
                    ├──emit──→ Trace Store + WebSocket Stream
                    │
                    └── [if not final] ──enqueue──→ Queue (next step)
```

### 5.2 Session State Machine

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

---

## 6. Technology Stack (Phase 1)

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

## 7. API Surface (Phase 1)

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
```

---

## 8. Deployment Architecture

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

## 9. Security Overview

```
Layer 1: API Gateway ─── Auth (OAuth/API Key) + Rate Limit + TLS
Layer 2: Input ───────── Prompt injection detection + Schema validation
Layer 3: Policy ──────── Tool permission (RBAC) + Budget enforcement
Layer 4: Execution ───── Tenant isolation + Sandbox + Network policy
Layer 5: Output ──────── Response filtering + PII masking
Layer 6: Audit ───────── Immutable logs + Anomaly detection
```

---

## 10. Architecture Decision Records (ADR)

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

---

## 11. Detailed Design Documents

Các component phức tạp có thiết kế chi tiết riêng:

| Component | Tài liệu | Mô tả |
|-----------|----------|-------|
| **Guardrails** | [`guardrails/design.md`](guardrails/design.md) | Input/output validation, prompt injection, policy engine |
| **Memory** | [`memory/design.md`](memory/design.md) | Memory stack, vector store, context management, shared memory |
| **Planning** | [`planning/design.md`](planning/design.md) | ReAct, Plan-then-Execute, checkpoint, budget, orchestration |
| **MCP & Tools** | [`mcp-tools/design.md`](mcp-tools/design.md) | MCP client, tool registry, discovery, invocation, sandbox |

---

## 12. Directory Structure (Phase 1)

```
agent-platform/
├── src/
│   ├── api/                    # API layer (routes, middleware, websocket)
│   ├── services/               # Business logic (agent, session, tool, memory)
│   ├── engine/                 # Execution engine (executor, react, planner, checkpoint)
│   ├── providers/              # External (llm/, mcp/)
│   ├── store/                  # Data access (postgres/, redis/, memory/)
│   ├── core/                   # Shared (models, config, events, errors, security, tracing)
│   └── main.py
├── sdk/python/                 # Python SDK
├── tests/                      # unit/ integration/ e2e/
├── deploy/                     # docker/ k8s/
└── docs/                       # Documentation
```
