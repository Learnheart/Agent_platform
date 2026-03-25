# Yêu Cầu Hệ Thống: Agent Serving Platform

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect

---

## 1. Use Cases Ưu Tiên

### Priority Matrix

| Priority | Use Case | Phase |
|----------|----------|-------|
| **P0** | Customer Support Automation | 1-2 |
| **P0** | Custom Agent Building (Developer) | 1 |
| **P1** | IT Helpdesk Agents | 2 |
| **P1** | Document Processing | 2 |
| **P2** | Data Analysis Agents | 2-3 |
| **P2** | Code Generation / DevOps | 2-3 |
| **P2** | Sales/Marketing Automation | 2-3 |
| **P3** | Compliance/Audit Agents | 3 |
| **P3** | Agent Marketplace | 3 |

---

## 2. Functional Requirements

### 2.1 Agent Management (FR-AM)

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| FR-AM-01 | Tạo agent definition với system prompt, model config, tool list | P0 | 1 |
| FR-AM-02 | Cập nhật agent definition (prompt, tools, config) | P0 | 1 |
| FR-AM-03 | Xóa agent definition | P0 | 1 |
| FR-AM-04 | List/search agent definitions | P0 | 1 |
| FR-AM-05 | Version management cho agent definitions | P1 | 2 |
| FR-AM-06 | Clone/fork agent definition | P2 | 2 |
| FR-AM-07 | Agent template library | P2 | 2-3 |
| FR-AM-08 | A/B deploy giữa agent versions | P2 | 3 |

### 2.2 Execution Engine (FR-EE)

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| FR-EE-01 | ReAct execution loop (Thought → Action → Observation) | P0 | 1 |
| FR-EE-02 | Plan-then-Execute pattern (plan → sub-tasks → execute) | P1 | 2 |
| FR-EE-03 | Checkpoint sau mỗi step thành công | P0 | 1 |
| FR-EE-04 | Resume từ checkpoint sau failure | P0 | 1 |
| FR-EE-05 | Streaming output (SSE Phase 1, WebSocket Phase 2) | P0 | 1 |
| FR-EE-06 | Queue-based async execution | P0 | 1 |
| FR-EE-07 | Token budget enforcement (max tokens per session) | P0 | 1 |
| FR-EE-08 | Time budget enforcement (max duration per session) | P0 | 1 |
| FR-EE-09 | Step budget enforcement (max steps per session) | P1 | 1 |
| FR-EE-10 | Multi-agent: Supervisor → Workers pattern | P1 | 2 |
| FR-EE-11 | Multi-agent: Sequential pipeline | P1 | 2 |
| FR-EE-12 | Multi-agent: Router pattern | P1 | 2 |
| FR-EE-13 | Tree of Thought execution | P2 | 3 |
| FR-EE-14 | Reflexion pattern (evaluate → reflect → retry) | P2 | 2 |
| FR-EE-15 | Context window management (summarize, truncate) | P0 | 1 |

### 2.3 Tool System (FR-TS)

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| FR-TS-01 | MCP client: connect to MCP servers (stdio + HTTP) | P0 | 1 |
| FR-TS-02 | MCP tool discovery: enumerate tools from connected servers | P0 | 1 |
| FR-TS-03 | Tool invocation với schema validation | P0 | 1 |
| FR-TS-04 | Tool permission enforcement (per-agent allowlist) | P0 | 1 |
| FR-TS-05 | Tool timeout handling | P0 | 1 |
| FR-TS-06 | Tool retry với configurable policy | P1 | 1 |
| FR-TS-07 | Custom tool registration (non-MCP) | P1 | 1-2 |
| FR-TS-08 | Tool rate limiting | P1 | 2 |
| FR-TS-09 | Human-in-the-loop approval cho high-risk tools | P1 | 2 |
| FR-TS-10 | Sandboxed code execution environment | P1 | 2 |
| FR-TS-11 | Tool capability-based search (semantic) | P2 | 3 |

### 2.4 Session Management (FR-SM)

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| FR-SM-01 | Create session (agent + initial input) | P0 | 1 |
| FR-SM-02 | Session state machine (CREATED → RUNNING → COMPLETED/FAILED) | P0 | 1 |
| FR-SM-03 | Pause/resume session | P0 | 1 |
| FR-SM-04 | WAITING_INPUT state (human-in-the-loop) | P1 | 1-2 |
| FR-SM-05 | Session timeout (idle + max duration) | P0 | 1 |
| FR-SM-06 | List/query sessions với filters | P0 | 1 |
| FR-SM-07 | Session metadata (tags, billing info) | P1 | 1 |
| FR-SM-08 | Session history retrieval (full execution trace) | P0 | 1 |
| FR-SM-09 | Batch session creation | P2 | 2 |
| FR-SM-10 | Session TTL và auto-cleanup | P1 | 1 |

### 2.5 Memory System (FR-MS)

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| FR-MS-01 | Short-term: conversation history management | P0 | 1 |
| FR-MS-02 | Short-term: automatic summarization khi gần limit | P0 | 1 |
| FR-MS-03 | Long-term: vector store cho per-agent knowledge | P1 | 2 |
| FR-MS-04 | Long-term: store/retrieve memories as agent actions | P1 | 2 |
| FR-MS-05 | Memory namespace isolation per tenant | P0 | 1 |
| FR-MS-06 | Episodic memory (cross-session learning) | P2 | 3 |
| FR-MS-07 | Knowledge graph integration | P2 | 3 |
| FR-MS-08 | Shared memory cho multi-agent sessions | P1 | 2 |

### 2.6 LLM Integration (FR-LLM)

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| FR-LLM-01 | LLM Provider abstraction interface (model-agnostic contract) | P0 | 1 |
| FR-LLM-02 | Anthropic Claude API integration (first provider) | P0 | 1 |
| FR-LLM-03 | OpenAI API integration (second provider) | P1 | 2 |
| FR-LLM-03b | Google Gemini API integration | P1 | 2 |
| FR-LLM-04 | OpenAI-compatible API support (cho local models) | P1 | 2 |
| FR-LLM-05 | Model fallback (primary → secondary khi fail) | P1 | 2 |
| FR-LLM-06 | Model routing (task complexity → appropriate model) | P2 | 2 |
| FR-LLM-07 | Response caching (same prompt → cached result, temp=0) | P2 | 2 |
| FR-LLM-08 | Token usage tracking per call | P0 | 1 |

### 2.8 Web UI (FR-UI)

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| FR-UI-01 | Dashboard tổng quan (số agent, sessions, chi phí) | P0 | 1 |
| FR-UI-02 | Tạo agent bằng form cấu hình (system prompt, model, tools, guardrails) | P0 | 1 |
| FR-UI-03 | Chỉnh sửa agent config | P0 | 1 |
| FR-UI-04 | Danh sách và quản lý agent (list, search, delete) | P0 | 1 |
| FR-UI-05 | Chat interface với agent (gửi message, xem streaming response) | P0 | 1 |
| FR-UI-06 | Xem session list với filter (agent, trạng thái, thời gian) | P0 | 1 |
| FR-UI-07 | Execution trace view (timeline các steps, tool calls, chi phí) | P0 | 1 |
| FR-UI-08 | Tool registry view (danh sách MCP servers và tools) | P1 | 1 |
| FR-UI-09 | Settings page (API keys, LLM provider config) | P1 | 1 |
| FR-UI-10 | Visual workflow builder (kéo thả) | P1 | 2 |
| FR-UI-11 | Agent template library trên UI | P2 | 2 |
| FR-UI-12 | Real-time notification (session complete, error, HITL request) | P1 | 2 |

---

## 3. Non-Functional Requirements

### 3.1 Performance (NFR-P)

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-P-01 | Platform overhead per execution step | < 100ms |
| NFR-P-02 | Session creation latency | < 200ms |
| NFR-P-03 | Checkpoint write latency | < 50ms |
| NFR-P-04 | Streaming first token delivery (excl. LLM) | < 500ms |
| NFR-P-05 | API response time (non-streaming) | p99 < 500ms |
| NFR-P-06 | Concurrent sessions supported | ≥ 1,000 (Phase 1) |

### 3.2 Reliability (NFR-R)

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-R-01 | Platform uptime | 99.9% |
| NFR-R-02 | Checkpoint success rate | > 99.9% |
| NFR-R-03 | Zero data loss on executor crash | Via checkpoint |
| NFR-R-04 | Recovery time (RTO) | < 5 minutes |
| NFR-R-05 | Graceful degradation khi LLM provider down | Retry same provider (Phase 1), fallback Phase 2 |

### 3.3 Security (NFR-S)

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-S-01 | TLS 1.3 cho mọi communication | P0 |
| NFR-S-02 | OAuth 2.0 / OIDC authentication | P0 |
| NFR-S-03 | API key authentication | P0 |
| NFR-S-04 | Tenant data isolation (namespace-based) | P0 |
| NFR-S-05 | Tool permission enforcement at platform level | P0 |
| NFR-S-06 | Immutable audit log cho mọi action | P0 |
| NFR-S-07 | Encryption at rest (AES-256) | P0 |
| NFR-S-08 | Prompt injection detection middleware | P1 |
| NFR-S-09 | PII detection và masking trong logs | P1 |
| NFR-S-10 | RBAC với fine-grained permissions | P1 (Phase 2) |

### 3.4 Scalability (NFR-SC)

| ID | Requirement | Detail |
|----|-------------|--------|
| NFR-SC-01 | Horizontal scaling executor instances | Auto-scale on queue depth |
| NFR-SC-02 | LLM provider load balancing | Round-robin + health check |
| NFR-SC-03 | Database connection pooling | Per-tenant limits |
| NFR-SC-04 | Queue-based backpressure | Reject khi queue full |
| NFR-SC-05 | Stateless executor design | Mọi state externalized |

### 3.5 Observability (NFR-O)

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-O-01 | OpenTelemetry tracing cho mọi session/step/LLM call/tool call | P0 |
| NFR-O-02 | Cost tracking per session, per agent, per tenant | P0 |
| NFR-O-03 | Structured logging (JSON) | P0 |
| NFR-O-04 | Health check endpoint | P0 |
| NFR-O-05 | Metrics export (Prometheus compatible) | P1 |
| NFR-O-06 | Dashboard cho operational metrics | P1 |
| NFR-O-07 | Alert rules cho anomaly detection | P2 |

---

## 4. Integration Requirements

### 4.1 LLM Providers (Phase 1)

| Provider | Priority | Protocol | Phase |
|----------|----------|----------|-------|
| Anthropic (Claude) | P0 | Anthropic API | 1 |
| OpenAI (GPT-4o, o3) | P1 | OpenAI API | 2 |
| Google (Gemini) | P1 | Gemini API | 2 |
| OpenAI-compatible (Ollama, vLLM) | P1 | OpenAI-compatible API | 2 |

Phase 1: Claude only. LLM abstraction interface từ đầu, OpenAI adapter Phase 2.

### 4.2 MCP Tool Servers (Phase 1 test targets)

| MCP Server | Purpose |
|------------|---------|
| Filesystem | File read/write operations |
| PostgreSQL/SQLite | Database queries |
| GitHub | Repository operations |
| Slack | Messaging |
| Web Search (Brave/Google) | Information retrieval |

### 4.3 Enterprise Systems (Phase 2+)

| Category | Systems |
|----------|---------|
| CRM | Salesforce, HubSpot |
| ITSM | ServiceNow, Jira |
| Communication | Slack, Teams, Email |
| Identity | SAML 2.0, OIDC, LDAP |
| Storage | S3, Azure Blob, GCS |

---

## 5. Deployment Requirements

### Phase 1: Cloud Deployment

| Requirement | Detail |
|-------------|--------|
| Container runtime | Docker / Kubernetes |
| Cloud provider | AWS (primary), GCP (secondary) |
| Database | PostgreSQL (primary), Redis (cache/queue) |
| Vector store | pgvector (embedded in PostgreSQL) |
| Object storage | S3 / GCS |
| CI/CD | GitHub Actions |

### Phase 2: On-premise Support

| Requirement | Detail |
|-------------|--------|
| Deployment artifact | Helm chart + Kubernetes operator |
| Air-gapped install | Offline container registry support |
| Identity integration | Corporate SAML/OIDC/LDAP |
| Data residency | All data trong customer perimeter |

---

## 6. Compliance Requirements (Progressive)

| Standard | Phase | Scope |
|----------|-------|-------|
| SOC 2 Type I | Phase 2 | Platform security controls |
| SOC 2 Type II | Phase 3 | Continuous compliance |
| GDPR | Phase 2 | EU data handling |
| HIPAA | Phase 3 | Healthcare use cases |
| ISO 27001 | Phase 3 | Enterprise deployments |

---

## 7. Latency Expectations by Use Case

| Use Case | First Token | Full Response | Notes |
|----------|-------------|---------------|-------|
| Customer Support (Tier 1) | < 500ms | < 3s | Real-time, user-facing |
| Customer Support (Tier 2/3) | < 1s | < 10s | Complex reasoning acceptable |
| IT Helpdesk | < 1s | < 5s (action) | Action execution matters |
| Data Analysis | < 2s | < 30s | Progressive loading helps |
| Document Processing | < 1s | < 60s/doc | Batch-oriented, throughput > latency |
| Code Generation | < 1s | < 30s | Streaming output critical |

---

## 8. Throughput Targets (Phase 2)

| Use Case | Concurrent Sessions |
|----------|---------------------|
| Customer Support | 10,000+ |
| IT Helpdesk | 5,000 |
| Document Processing | 10,000 docs/hour |
| Data Analysis | 500 concurrent queries |
| Code Generation | 2,000 concurrent |
