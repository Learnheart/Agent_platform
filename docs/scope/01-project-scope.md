# Phạm Vi Dự Án: Agent Serving Platform

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect

---

## 1. Tổng Quan Dự Án

### 1.1 Tên dự án
**Agent Platform** — Nền tảng phục vụ AI Agent

### 1.2 Tầm nhìn (Vision)
Xây dựng một nền tảng toàn diện để tạo, triển khai, và vận hành AI agent ở quy mô production, với trọng tâm vào **reliability, observability, security, và developer experience**.

### 1.3 Mission Statement
> Giảm 80% công sức xây dựng hạ tầng cho AI agent, để developer tập trung vào business logic và agent behavior.

---

## 2. Phạm Vi Hệ Thống

### 2.1 Ranh Giới Hệ Thống (System Boundary)

```
┌─────────────────────── AGENT PLATFORM ───────────────────────┐
│                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ Agent       │  │ Execution    │  │ Tool System        │  │
│  │ Management  │  │ Engine       │  │ (MCP-Native)       │  │
│  │ API         │  │              │  │                    │  │
│  └─────────────┘  └──────────────┘  └────────────────────┘  │
│                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ Session &   │  │ Memory       │  │ Observability      │  │
│  │ State Mgmt  │  │ System       │  │ & Tracing          │  │
│  └─────────────┘  └──────────────┘  └────────────────────┘  │
│                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ Security &  │  │ API Gateway  │  │ SDK                │  │
│  │ Governance  │  │ & Auth       │  │ (Python P1, TS P2) │  │
│  └─────────────┘  └──────────────┘  └────────────────────┘  │
│                                                               │
└───────────────────────────────────────────────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
   LLM Providers      MCP Tool Servers      External Systems
   (Claude, GPT,      (DB, API, File,       (CRM, ITSM,
    Gemini, Local)      Custom...)            ERP...)
```

### 2.2 Trong phạm vi (In Scope)

| Component | Mô tả |
|-----------|--------|
| **Agent Management API** | CRUD agent definitions, versioning, configuration |
| **Execution Engine** | ReAct loop, Plan-then-Execute, checkpoint/resume |
| **Tool System** | MCP client, tool registry, permission enforcement |
| **Session Management** | Session lifecycle, state persistence, checkpoint |
| **Memory System** | Short-term (context), working (session-scoped); long-term (Phase 1-2) |
| **Observability** | Tracing (OTel), metrics, cost tracking, log aggregation |
| **Security** | Auth (OAuth/OIDC), RBAC, tenant isolation, audit trail |
| **API Gateway** | REST API, WebSocket streaming, rate limiting |
| **SDK** | Python SDK (primary), TypeScript SDK (secondary) |
| **Guardrails** | Schema validation, budget enforcement, tool permissions (slim Phase 1; advanced features Phase 2) |

### 2.3 Ngoài phạm vi (Out of Scope)

| Item | Lý do | Phase dự kiến |
|------|-------|---------------|
| Visual Agent Builder (low-code UI) | Cần core platform ổn định trước | Phase 2 |
| Agent Marketplace | Cần ecosystem trước | Phase 3 |
| Multi-agent orchestration nâng cao | Phức tạp, cần validate single-agent trước | Phase 2 |
| Edge deployment | Cần runtime riêng, market niche | Phase 3 |
| A2A protocol support | Protocol còn sớm | Phase 2-3 |
| Self-hosted LLM hosting | Khác bài toán, dùng provider có sẵn | Không |
| End-user facing UI/chatbot widget | Platform là backend, UI là responsibility của consumer | Không |
| Billing & subscription management | Dùng third-party (Stripe) | Phase 2 |

---

## 3. Phân Pha Phát Triển (Phased Delivery)

### Phase 1: Foundation (MVP)
**Mục tiêu:** Platform core chạy được single-agent với tool use, observable và reliable.

| Deliverable | Mô tả |
|-------------|--------|
| Agent Runtime | ReAct loop + Plan-then-Execute |
| MCP Tool Integration | Connect MCP servers, invoke tools |
| Session Management | Create/run/pause/resume sessions, checkpoint |
| State Store | Redis (hot) + PostgreSQL (warm) |
| Memory - Short-term | Context window management với summarization |
| Memory - Working | Plan state, artifacts, scratchpad (session-scoped) |
| REST API | Full CRUD cho agents, sessions, tools |
| WebSocket Streaming | Real-time event stream cho interactive sessions |
| Tracing | OpenTelemetry instrumentation, basic trace viewer |
| Auth | API key + OAuth 2.0 |
| Python SDK | Opinionated thin client — auth, session, streaming, tools (xem [DX spec](04-developer-experience.md)) |
| Cost Tracking | Per-session token usage và cost estimation |
| Documentation | API docs, getting started guide, architecture guide |

### Phase 2: Scale & Multi-tenant
**Mục tiêu:** Multi-tenant, multi-agent, enterprise features.

| Deliverable | Mô tả |
|-------------|--------|
| Multi-tenancy | Tenant isolation, per-tenant config |
| Multi-agent Orchestration | Supervisor, pipeline, router patterns |
| RBAC | Fine-grained role-based access control |
| Visual Trace Explorer | Full trace viewer UI |
| TypeScript SDK | Parity với Python SDK |
| Agent Versioning | Version management, rollback, A/B deploy |
| Evaluation Framework | Test suites, LLM-as-judge, regression testing |
| Budget Enforcement | Per-session, per-agent, per-tenant budgets |
| Billing Integration | Usage tracking, Stripe integration |
| On-premise Deployment | Helm charts, Kubernetes operator |
| Long-term Memory | Vector store (pgvector), RAG, knowledge base indexing |
| Advanced Guardrails | CEL rule engine, classifier-based injection detection, Presidio PII, canary tokens |
| LLM Providers | Gemini, OpenAI-compatible (Ollama, vLLM) |

### Phase 3: Ecosystem & Advanced
**Mục tiêu:** Marketplace, advanced patterns, edge.

| Deliverable | Mô tả |
|-------------|--------|
| Agent Marketplace | Publish, discover, share agent templates |
| Visual Agent Builder | Low-code drag-and-drop agent construction |
| A2A Protocol | Agent-to-agent interoperability |
| Advanced Memory | Episodic memory, knowledge graphs |
| Edge Runtime | Lightweight agent runtime cho edge devices |
| Advanced Evaluation | A/B testing, counterfactual analysis |
| Compliance Toolkit | SOC2, HIPAA, GDPR compliance packages |

---

## 4. Yêu Cầu Chất Lượng (Quality Attributes)

### 4.1 Performance

| Metric | Target Phase 1 | Target Phase 2 |
|--------|----------------|----------------|
| Platform overhead per step | < 100ms | < 50ms |
| Session create latency | < 200ms | < 100ms |
| Checkpoint write latency | < 50ms | < 20ms |
| Concurrent sessions | 1,000 | 50,000 |
| Streaming first token | < 500ms (excl. LLM) | < 200ms |

### 4.2 Reliability

| Metric | Target |
|--------|--------|
| Platform uptime | 99.9% (Phase 1) → 99.99% (Phase 2) |
| Checkpoint success rate | > 99.9% |
| Data durability | 99.999999999% (11 nines, via cloud storage) |
| RTO (Recovery Time Objective) | < 5 minutes |
| RPO (Recovery Point Objective) | 0 (last checkpoint) |

### 4.3 Security

| Requirement | Priority |
|-------------|----------|
| Authentication (OAuth 2.0 / OIDC) | P0 |
| API key management | P0 |
| TLS everywhere | P0 |
| Tenant data isolation | P0 |
| Tool permission enforcement | P0 |
| Audit logging | P0 |
| Prompt injection detection | P1 |
| PII detection/masking | P1 |
| SOC 2 compliance | P2 |

### 4.4 Scalability

- Horizontal scaling cho executor instances
- LLM provider load balancing và failover
- Queue-based backpressure handling
- Auto-scaling based on queue depth và active sessions

---

## 5. Constraints & Assumptions

### 5.1 Constraints (Ràng buộc)

| Constraint | Mô tả |
|------------|--------|
| **LLM Dependency** | Platform phụ thuộc vào external LLM APIs (Anthropic, OpenAI, Google...) |
| **MCP Protocol** | Tool integration theo chuẩn MCP; tool providers cần implement MCP server |
| **Cloud-first** | Phase 1 deploy trên cloud (AWS/GCP); on-premise ở Phase 2 |
| **Model Agnostic** | Không được hardcode cho một LLM provider cụ thể |

### 5.2 Assumptions (Giả định)

| Assumption | Risk nếu sai |
|------------|--------------|
| MCP tiếp tục được adopt rộng rãi | Phải support protocol khác, tăng complexity |
| LLM API cost giảm theo thời gian | Cost management quan trọng hơn |
| Enterprise muốn self-hosted option | On-premise scope có thể giảm |
| Developer muốn code-first trước, GUI sau | Có thể cần GUI sớm hơn |

---

## 6. Stakeholders

| Stakeholder | Vai trò | Quan tâm chính |
|-------------|---------|----------------|
| **Developer (API consumer)** | Xây agent trên platform | DX, API quality, SDK, docs |
| **Platform Operator** | Vận hành platform | Reliability, observability, scaling |
| **Enterprise Architect** | Quyết định adoption | Security, governance, compliance |
| **End User** | Tương tác với agent qua app | Response quality, latency |
| **Compliance Officer** | Đảm bảo compliance | Audit trail, data privacy, explainability |

---

## 7. Success Criteria

### Phase 1 Launch Criteria
- [ ] Agent runtime xử lý được ReAct và Plan-then-Execute patterns
- [ ] MCP tool integration hoạt động với ≥ 5 MCP servers phổ biến
- [ ] Checkpoint/resume success rate > 99%
- [ ] REST API + WebSocket streaming đầy đủ
- [ ] Python SDK published
- [ ] Tracing hiển thị được full execution trace
- [ ] Auth + tenant isolation hoạt động
- [ ] Documentation đủ để developer onboard trong < 1 ngày
- [ ] Load test: 1,000 concurrent sessions stable
- [ ] Security audit passed (basic level)
