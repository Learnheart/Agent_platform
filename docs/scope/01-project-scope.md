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
> Giảm 80% công sức xây dựng hạ tầng cho AI agent, để builder tập trung vào business logic và agent behavior.

### 1.4 Mô Hình Người Dùng (User Model)

Platform phục vụ **hai đối tượng** với vai trò khác nhau:

```
┌─────────────────────────────────────────────────────────────────┐
│                     AGENT PLATFORM                               │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  BUILDER (đối tượng chính)                               │    │
│  │  Sử dụng Management UI + API để:                         │    │
│  │  - Tạo, cấu hình, quản lý agent                         │    │
│  │  - Kết nối MCP tools                                      │    │
│  │  - Thiết lập guardrails                                   │    │
│  │  - Monitor, debug, tối ưu agent                           │    │
│  │  - Test agent qua chat interface                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  END USER (đối tượng phụ)                                │    │
│  │  Tương tác với agent đã được builder tạo sẵn:            │    │
│  │  - Chat với agent qua Session API / Embed widget          │    │
│  │  - Không truy cập management UI                           │    │
│  │  - Không biết/cần biết platform bên dưới                  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

| | **Builder** | **End User** |
|---|---|---|
| **Quan hệ với platform** | Trực tiếp — dùng Management UI/API | Gián tiếp — dùng agent qua Session API |
| **Truy cập** | Management UI, toàn bộ API | Chỉ Session API (send message, nhận response) |
| **Mục tiêu** | Tạo agent giải quyết bài toán nghiệp vụ | Được phục vụ bởi agent |
| **Phase 1 scope** | Full management + test chat | Session API để tương tác với agent |
| **Ai chịu trách nhiệm UX?** | Platform cung cấp Management UI | Builder chịu trách nhiệm trải nghiệm end user (platform cung cấp Session API + SSE) |

> **Nguyên tắc:** Platform tập trung xây dựng trải nghiệm tốt nhất cho Builder. Với End User, platform cung cấp **runtime + API** để builder tự xây dựng trải nghiệm phù hợp với use case.

---

## 2. Phạm Vi Hệ Thống

### 2.1 Ranh Giới Hệ Thống (System Boundary)

```
                 Builder                              End User
                   │                                     │
                   │ Management UI + API                 │ Session API (chat)
                   ▼                                     ▼
┌─────────────────────── AGENT PLATFORM ───────────────────────┐
│                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ Agent       │  │ Execution    │  │ Tool System        │  │
│  │ Management  │  │ Engine       │  │ (MCP-Native)       │  │
│  │ (Builder)   │  │              │  │                    │  │
│  └─────────────┘  └──────────────┘  └────────────────────┘  │
│                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ Session &   │  │ Memory       │  │ Observability      │  │
│  │ State Mgmt  │  │ System       │  │ & Tracing          │  │
│  │ (Both)      │  │              │  │ (Builder)          │  │
│  └─────────────┘  └──────────────┘  └────────────────────┘  │
│                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ Security &  │  │ API Gateway  │  │ Management UI      │  │
│  │ Governance  │  │ & Auth       │  │ (Builder only)     │  │
│  └─────────────┘  └──────────────┘  └────────────────────┘  │
│                                                               │
└───────────────────────────────────────────────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
   LLM Providers      MCP Tool Servers      External Systems
   (Anthropic, Groq,  (DB, API, File,       (CRM, ITSM,
    LM Studio, ...)    Custom...)            ERP...)
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
| **Management UI** | Phase 1: config-based (form tạo agent, quản lý session, xem kết quả) — chỉ cho Builder. Phase 2: visual builder |
| **Session API** | REST + SSE cho End User tương tác với agent (send message, nhận streaming response) |
| **SDK** | Optional Phase 2+ (Python, TypeScript) |
| **Guardrails** | Schema validation, budget enforcement, tool permissions (slim Phase 1; advanced features Phase 2) |

### 2.3 Ngoài phạm vi (Out of Scope)

| Item | Lý do | Phase dự kiến |
|------|-------|---------------|
| Visual Workflow Builder (kéo thả) | Nằm trong Phase 2, không phải Phase 1 | Phase 2 |
| Agent Marketplace | Cần ecosystem trước | Phase 3 |
| Multi-agent orchestration nâng cao | Phức tạp, cần validate single-agent trước | Phase 2 |
| Edge deployment | Cần runtime riêng, market niche | Phase 3 |
| A2A protocol support | Protocol còn sớm | Phase 2-3 |
| Self-hosted LLM hosting | Platform kết nối tới self-hosted models (LM Studio) nhưng không tự host model | Không |
| End-user UI (chatbot widget, embed) | Platform cung cấp Session API, builder tự xây UI cho end user hoặc dùng embed widget (Phase 2) | Phase 2 (embed widget) |
| Billing & subscription management | Dùng third-party (Stripe) | Phase 2 |

---

## 3. Phân Pha Phát Triển (Phased Delivery)

### Phase 1: Foundation (MVP)
**Mục tiêu:** Platform core chạy được single-agent với tool use, observable và reliable.

| Deliverable | Mô tả |
|-------------|--------|
| Agent Runtime | ReAct loop (Plan-then-Execute → Phase 2) |
| MCP Tool Integration | Connect MCP servers, invoke tools |
| Session Management | Create/run/pause/resume sessions, checkpoint |
| State Store | Redis (hot) + PostgreSQL (warm) |
| Memory - Short-term | Context window management với summarization |
| Memory - Working | Plan state, artifacts, scratchpad (session-scoped) |
| REST API | Full CRUD cho agents, sessions, tools |
| SSE Streaming | Real-time event stream cho interactive sessions (SSE Phase 1, WebSocket Phase 2) |
| Tracing | OpenTelemetry instrumentation, basic trace viewer |
| Auth | API key + OAuth 2.0 |
| Management UI | Form tạo agent, quản lý session, xem kết quả (config-based) — cho Builder |
| LLM Gateway | Multi-provider: Anthropic (Claude), Groq, LM Studio (self-hosted) via `LLMGateway` protocol |
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
| Visual Workflow Builder | Kéo thả (drag-and-drop) agent construction |
| SDK (Python, TypeScript) | Optional — cho developer muốn code-first integration |
| Agent Versioning | Version management, rollback, A/B deploy |
| Evaluation Framework | Test suites, LLM-as-judge, regression testing |
| Budget Enforcement | Per-session, per-agent, per-tenant budgets |
| Billing Integration | Usage tracking, Stripe integration |
| On-premise Deployment | Helm charts, Kubernetes operator |
| Long-term Memory | Vector store (pgvector), RAG, knowledge base indexing |
| Advanced Guardrails | CEL rule engine, classifier-based injection detection, Presidio PII, canary tokens |
| LLM Advanced Routing | Fallback logic, load balancing, per-agent model config |

### Phase 3: Ecosystem & Advanced
**Mục tiêu:** Marketplace, advanced patterns, edge.

| Deliverable | Mô tả |
|-------------|--------|
| Agent Marketplace | Publish, discover, share agent templates |
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
| Builder muốn low/no-code UI để tạo agent | Nếu sai, cần SDK sớm hơn (hiện tại: UI-first, SDK Phase 2) |

---

## 6. Stakeholders

| Stakeholder | Vai trò | Quan hệ với Platform | Quan tâm chính |
|-------------|---------|---------------------|----------------|
| **Builder** (đối tượng chính) | Tạo, cấu hình, quản lý agent | Trực tiếp — dùng Management UI + API | UX, tốc độ tạo agent, observability, cost visibility |
| **End User** (đối tượng phụ) | Tương tác với agent đã tạo sẵn | Gián tiếp — dùng agent qua Session API | Response quality, latency, reliability |
| **Platform Operator** | Vận hành platform | Trực tiếp — infrastructure | Reliability, observability, scaling |
| **Enterprise Architect** | Quyết định adoption | Stakeholder | Security, governance, compliance |
| **Compliance Officer** | Đảm bảo compliance | Stakeholder | Audit trail, data privacy, explainability |

---

## 7. Success Criteria

### Phase 1 Launch Criteria
- [ ] Agent runtime xử lý được ReAct và Plan-then-Execute patterns
- [ ] MCP tool integration hoạt động với ≥ 5 MCP servers phổ biến
- [ ] Checkpoint/resume success rate > 99%
- [ ] REST API + SSE streaming đầy đủ
- [ ] Management UI cho phép Builder tạo agent trong <5 phút
- [ ] Tracing hiển thị được full execution trace
- [ ] Auth + tenant isolation hoạt động
- [ ] Builder tạo agent đầu tiên < 15 phút
- [ ] End User gửi message và nhận response qua Session API thành công
- [ ] Load test: 1,000 concurrent sessions stable
- [ ] Security audit passed (basic level)
