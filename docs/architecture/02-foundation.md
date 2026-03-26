# Thiết Kế Chi Tiết: Project Foundation

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-26
> **Parent:** [Architecture Overview](00-overview.md)

---

## 1. Scope

Tài liệu này định nghĩa **project foundation** — những thành phần nền tảng cần có trước khi implement bất kỳ module nào:

1. **Project Structure** — package layout, module responsibilities
2. **Dependencies** — pyproject.toml, version constraints
3. **Configuration Management** — cách load config runtime
4. **Dependency Injection / Wiring** — cách các component được khởi tạo và kết nối
5. **Application Lifecycle** — startup / shutdown sequence
6. **Database Migration** — Alembic setup, migration strategy

---

## 2. Project Structure

> Mở rộng từ [`00-overview.md`](00-overview.md) Section 14. Chi tiết trách nhiệm từng module.

```
agent-platform/
├── src/
│   ├── __init__.py
│   ├── main.py                      # FastAPI app factory + lifespan
│   │
│   ├── api/                         # API Layer — HTTP interface
│   │   ├── __init__.py
│   │   ├── app.py                   # create_app(), middleware registration
│   │   ├── deps.py                  # FastAPI dependency providers (get_db, get_redis, get_services)
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py              # AuthMiddleware (JWT + API Key)
│   │   │   ├── tenant.py            # TenantMiddleware (extract + set tenant context)
│   │   │   ├── rate_limit.py        # RateLimitMiddleware
│   │   │   ├── request_id.py        # RequestIDMiddleware (X-Request-ID)
│   │   │   └── error_handler.py     # Global exception → PlatformError response
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── agents.py            # /api/v1/agents — Builder API
│   │   │   ├── sessions.py          # /api/v1/sessions — Builder + End User API
│   │   │   ├── messages.py          # /api/v1/sessions/{id}/messages
│   │   │   ├── tools.py             # /api/v1/tools — Builder API
│   │   │   ├── audit.py             # /api/v1/audit — Builder API
│   │   │   └── stream.py            # /api/v1/sessions/{id}/stream — SSE endpoint
│   │   └── schemas/
│   │       ├── __init__.py
│   │       ├── agents.py            # Request/Response schemas cho agent endpoints
│   │       ├── sessions.py
│   │       ├── messages.py
│   │       └── common.py            # ResponseEnvelope, PaginationParams, ErrorResponse
│   │
│   ├── services/                    # Business Logic Layer
│   │   ├── __init__.py
│   │   ├── agent_service.py         # AgentManager — CRUD agent definitions
│   │   ├── session_service.py       # SessionManager — session lifecycle, state machine
│   │   ├── tool_service.py          # ToolManager — tool registry, discovery, invocation
│   │   └── memory_service.py        # MemoryManager — orchestrate memory layers
│   │
│   ├── engine/                      # Execution Engine
│   │   ├── __init__.py
│   │   ├── executor.py              # AgentExecutor — main orchestrator
│   │   ├── react.py                 # ReActEngine — Think/Act/Observe loop
│   │   ├── checkpoint.py            # CheckpointManager — delta + snapshot
│   │   ├── budget.py                # BudgetController — token/cost/step/time limits
│   │   ├── context.py               # ContextAssembler — build LLM prompt
│   │   └── worker.py                # TaskWorker — Redis Streams consumer
│   │
│   ├── providers/                   # External Provider Integrations
│   │   ├── __init__.py
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── gateway.py           # LLMGateway protocol
│   │   │   └── anthropic.py         # AnthropicGateway implementation
│   │   └── mcp/
│   │       ├── __init__.py
│   │       ├── client_manager.py    # MCPClientManager — connection pool, lifecycle
│   │       ├── invoker.py           # InvocationHandler — execute tool calls
│   │       └── schema_converter.py  # MCP ↔ Anthropic tool schema conversion
│   │
│   ├── guardrails/                  # Guardrails Engine
│   │   ├── __init__.py
│   │   ├── engine.py                # GuardrailsEngine — pipeline orchestrator
│   │   ├── inbound/
│   │   │   ├── __init__.py
│   │   │   ├── schema_validator.py  # SchemaValidator (hard)
│   │   │   └── injection_detector.py # InjectionDetector (soft + circuit breaker)
│   │   ├── policy/
│   │   │   ├── __init__.py
│   │   │   ├── tool_permission.py   # ToolPermissionEnforcer (hard)
│   │   │   ├── budget_enforcer.py   # BudgetEnforcer (hard)
│   │   │   ├── rate_limiter.py      # RateLimitEnforcer (hard)
│   │   │   └── hitl_gate.py         # HITLGate (configurable)
│   │   └── circuit_breaker.py       # GuardrailCircuitBreaker
│   │
│   ├── governance/                  # Data Governance Module
│   │   ├── __init__.py
│   │   ├── port.py                  # GovernancePort protocol
│   │   ├── local.py                 # LocalGovernance implementation (Phase 1)
│   │   ├── audit_sink.py            # AuditSink — write-behind buffer
│   │   ├── retention.py             # RetentionScheduler + strategies
│   │   ├── classifier.py            # DataClassifier — rule-based
│   │   └── cost_aggregator.py       # CostAggregator — Redis + PG
│   │
│   ├── store/                       # Data Access Layer
│   │   ├── __init__.py
│   │   ├── postgres/
│   │   │   ├── __init__.py
│   │   │   ├── database.py          # AsyncEngine, async_session_factory
│   │   │   ├── models.py            # SQLAlchemy ORM models (optional, or raw SQL)
│   │   │   ├── agent_repo.py        # AgentRepository — CRUD queries
│   │   │   ├── session_repo.py      # SessionRepository
│   │   │   ├── message_repo.py      # MessageRepository
│   │   │   ├── checkpoint_repo.py   # CheckpointRepository
│   │   │   ├── tool_repo.py         # ToolRepository
│   │   │   ├── audit_repo.py        # AuditRepository (append-only)
│   │   │   └── cost_repo.py         # CostRepository
│   │   └── redis/
│   │       ├── __init__.py
│   │       ├── client.py            # Redis client wrapper (connection pool)
│   │       ├── session_store.py     # Session hot state (conversation buffer, working memory)
│   │       ├── checkpoint_store.py  # Checkpoint snapshots + deltas (Redis)
│   │       ├── budget_store.py      # Real-time budget counters
│   │       ├── rate_limit_store.py  # Token bucket counters
│   │       ├── cost_store.py        # Real-time cost accumulators
│   │       ├── queue.py             # TaskQueue — Redis Streams producer
│   │       └── pubsub.py            # EventPublisher — Redis Pub/Sub
│   │
│   ├── events/                      # Event Bus
│   │   ├── __init__.py
│   │   ├── bus.py                   # EventBus — publish + subscribe
│   │   ├── types.py                 # AgentEvent, AgentEventType (re-export from core)
│   │   ├── consumers/
│   │   │   ├── __init__.py
│   │   │   ├── sse_consumer.py      # SSE stream consumer
│   │   │   ├── trace_consumer.py    # OTel trace exporter consumer
│   │   │   └── governance_consumer.py # Governance audit/cost consumer
│   │   └── sse.py                   # SSEManager — per-session SSE streams
│   │
│   └── core/                        # Shared Kernel
│       ├── __init__.py
│       ├── config.py                # Settings (Pydantic Settings)
│       ├── models.py                # Core data models (Message, ToolCall, etc.)
│       ├── enums.py                 # SessionState, StepType, ErrorCategory, etc.
│       ├── errors.py                # PlatformError, LLMError, etc.
│       ├── events.py                # AgentEvent, AgentEventType
│       ├── protocols.py             # Shared Protocol definitions
│       ├── security.py              # Password hashing, token generation, encryption
│       └── tracing.py               # OpenTelemetry setup, tracer/meter providers
│
├── migrations/                      # Alembic
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
│
├── tests/
│   ├── conftest.py                  # Shared fixtures (db, redis, client)
│   ├── unit/
│   │   ├── test_llm_gateway.py
│   │   ├── test_react_engine.py
│   │   ├── test_checkpoint.py
│   │   ├── test_budget.py
│   │   ├── test_guardrails.py
│   │   ├── test_memory.py
│   │   └── test_governance.py
│   ├── integration/
│   │   ├── test_session_flow.py
│   │   ├── test_tool_invocation.py
│   │   └── test_event_bus.py
│   └── e2e/
│       └── test_full_execution.py
│
├── deploy/
│   ├── docker/
│   │   ├── Dockerfile
│   │   ├── Dockerfile.worker        # Executor worker image
│   │   └── docker-compose.yml       # Local dev: API + Worker + PG + Redis
│   └── k8s/
│       ├── api-deployment.yaml
│       ├── worker-deployment.yaml
│       └── configmap.yaml
│
├── docs/
│   └── architecture/                # (this folder)
│
├── pyproject.toml
├── CLAUDE.md
└── PROJECT.md
```

### 2.1 Layer Dependencies

```
api/ ──→ services/ ──→ engine/     ──→ providers/ (llm/, mcp/)
 │          │            │               │
 │          │            │               └──→ store/ (postgres/, redis/)
 │          │            │
 │          │            └──→ guardrails/
 │          │
 │          └──→ store/ (postgres/, redis/)
 │
 └──→ events/ (sse consumer)

governance/ ←── events/ (governance consumer)
                 │
core/ ←──── (imported by all layers)
```

**Rules:**
- `core/` has **zero** imports from other `src/` packages
- `store/` imports only from `core/`
- `providers/` imports from `core/` and `store/`
- `services/` imports from `core/`, `store/`, `providers/`
- `engine/` imports from `core/`, `services/`, `providers/`, `guardrails/`
- `api/` imports from `core/`, `services/`, `events/`
- **No circular imports** — enforce via layer discipline

---

## 3. Dependencies (pyproject.toml)

Project **agent-platform** version 0.1.0 yêu cầu Python >= 3.12. Build system sử dụng **hatchling**, với wheel target package là `src`.

**Core dependencies:**

| Category | Package | Version Constraint | Purpose |
|----------|---------|-------------------|---------|
| Web framework | fastapi | >=0.115, <1.0 | API framework |
| Web framework | uvicorn[standard] | >=0.32, <1.0 | ASGI server |
| Web framework | sse-starlette | >=2.0, <3.0 | SSE support for FastAPI |
| LLM providers | anthropic | >=0.42, <1.0 | Anthropic SDK (includes httpx) |
| MCP | mcp | >=1.0, <2.0 | MCP Python SDK |
| Database | asyncpg | >=0.30, <1.0 | Async PostgreSQL driver |
| Database | sqlalchemy | >=2.0, <3.0 | SQL toolkit (async) |
| Database | alembic | >=1.14, <2.0 | Database migrations |
| Redis | redis[hiredis] | >=5.2, <6.0 | Async Redis client |
| Configuration | pydantic | >=2.10, <3.0 | Data validation |
| Configuration | pydantic-settings | >=2.7, <3.0 | Settings from env vars |
| Observability | opentelemetry-api | >=1.29, <2.0 | OTel API |
| Observability | opentelemetry-sdk | >=1.29, <2.0 | OTel SDK |
| Observability | opentelemetry-exporter-otlp | >=1.29, <2.0 | OTLP exporter |
| Observability | opentelemetry-instrumentation-fastapi | >=0.50b, <1.0 | FastAPI auto-instrumentation |
| Observability | opentelemetry-instrumentation-httpx | >=0.50b, <1.0 | httpx auto-instrumentation |
| Observability | opentelemetry-instrumentation-redis | >=0.50b, <1.0 | Redis auto-instrumentation |
| Observability | opentelemetry-instrumentation-sqlalchemy | >=0.50b, <1.0 | SQLAlchemy auto-instrumentation |
| Serialization | msgpack | >=1.1, <2.0 | Binary serialization for checkpoints |
| Serialization | orjson | >=3.10, <4.0 | Fast JSON (optional, replace stdlib json) |
| Security | python-jose[cryptography] | >=3.3, <4.0 | JWT validation |
| Security | passlib[bcrypt] | >=1.7, <2.0 | Password hashing (API keys) |
| Security | cryptography | >=44, <45 | Encryption (MCP server env vars) |
| Utilities | structlog | >=24.4, <25.0 | Structured logging |
| Utilities | tenacity | >=9.0, <10.0 | Retry utility (used by stores, not LLM — LLM has custom retry) |

**Dev dependencies** (optional group `dev`):

| Package | Version Constraint | Purpose |
|---------|-------------------|---------|
| pytest | >=8.3, <9.0 | Test runner |
| pytest-asyncio | >=0.25, <1.0 | Async test support |
| pytest-cov | >=6.0, <7.0 | Coverage reporting |
| httpx | >=0.28, <1.0 | TestClient |
| fakeredis[lua] | >=2.26, <3.0 | In-memory Redis for tests |
| testcontainers[postgres] | >=4.0, <5.0 | PostgreSQL in Docker for integration tests |
| factory-boy | >=3.3, <4.0 | Test fixtures |
| ruff | >=0.8, <1.0 | Linter + formatter |
| mypy | >=1.14, <2.0 | Type checking |

**Tool configuration:**

| Tool | Setting | Value |
|------|---------|-------|
| pytest | testpaths | tests |
| pytest | asyncio_mode | auto |
| pytest | markers | `unit` (no external deps), `integration` (need PG + Redis), `e2e` (full system) |
| ruff | target-version | py312 |
| ruff | line-length | 120 |
| ruff.lint | select | E, F, W, I, UP, B, SIM, RUF |
| mypy | python_version | 3.12 |
| mypy | strict | true |
| mypy | plugins | pydantic.mypy |

### 3.1 Dependency Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| PostgreSQL driver | `asyncpg` | Best async performance, native COPY support for batch audit writes |
| SQL layer | SQLAlchemy 2.0 (async) | Mature, async support, migration (Alembic). Use Core (not ORM) for performance-critical paths |
| Redis client | `redis-py` with hiredis | Official, async support, hiredis for C-level speed |
| SSE | `sse-starlette` | Lightweight SSE adapter for Starlette/FastAPI |
| JWT | `python-jose` | Widely used, supports RS256/ES256 |
| Serialization | `msgpack` (checkpoints), `orjson` (JSON) | Binary efficiency for checkpoints; orjson 3-10x faster than stdlib json |
| Logging | `structlog` | Structured JSON logs, async-friendly, processor pipeline |
| MCP SDK | `mcp` (official) | Official Python SDK for MCP protocol |

---

## 4. Configuration Management

### 4.1 Strategy: Pydantic Settings

Tất cả configuration load từ **environment variables**, hỗ trợ `.env` file cho local dev.

Class **Settings** là root configuration, kế thừa từ Pydantic BaseSettings. Cấu hình model: prefix = `APP_`, nested delimiter = `__`, hỗ trợ file `.env` (UTF-8), case insensitive.

Ví dụ: biến môi trường `APP_DATABASE__HOST=localhost` sẽ map thành `settings.database.host`.

**Settings (root):**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| app_name | str | "agent-platform" | Tên ứng dụng |
| environment | str | "development" | Môi trường: development / staging / production |
| debug | bool | False | Bật debug mode |
| log_level | str | "INFO" | Mức log |
| server | ServerSettings | (default factory) | Cấu hình server |
| database | DatabaseSettings | (default factory) | Cấu hình database |
| redis | RedisSettings | (default factory) | Cấu hình Redis |
| llm | LLMSettings | (default factory) | Cấu hình LLM |
| auth | AuthSettings | (default factory) | Cấu hình authentication |
| tracing | TracingSettings | (default factory) | Cấu hình tracing |
| governance | GovernanceSettings | (default factory) | Cấu hình governance |

**ServerSettings:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| host | str | "0.0.0.0" | Bind address |
| port | int | 8000 | HTTP port |
| workers | int | 1 | Uvicorn workers (API process) |
| executor_workers | int | 4 | Executor worker processes |

**DatabaseSettings:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| host | str | "localhost" | PostgreSQL host |
| port | int | 5432 | PostgreSQL port |
| name | str | "agent_platform" | Database name |
| user | str | "postgres" | Database user |
| password | str | "" | Database password (REQUIRED in production) |
| pool_min_size | int | 5 | Connection pool minimum |
| pool_max_size | int | 20 | Connection pool maximum |
| echo | bool | False | SQLAlchemy echo (debug only) |

DatabaseSettings cũng cung cấp một property `dsn` trả về connection string dạng `postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}`.

**RedisSettings:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| url | str | "redis://localhost:6379/0" | Redis connection URL |
| max_connections | int | 50 | Maximum connections |
| decode_responses | bool | True | Decode bytes to str |
| socket_timeout | float | 5.0 | Socket timeout (seconds) |
| retry_on_timeout | bool | True | Auto-retry on timeout |

**LLMSettings:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| anthropic_api_key | str | "" | Anthropic API key (REQUIRED) |
| default_model | str | "claude-sonnet-4-5-20250514" | Default model |
| default_timeout | float | 120.0 | Request timeout (seconds) |
| max_connections | int | 100 | Max HTTP connections |
| max_keepalive | int | 20 | Max keepalive connections |

**AuthSettings:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| jwt_secret | str | "" | JWT secret (REQUIRED in production, or use JWKS) |
| jwt_algorithm | str | "HS256" | JWT signing algorithm |
| jwt_issuer | str | "agent-platform" | JWT issuer claim |
| jwt_audience | str | "agent-platform" | JWT audience claim |
| jwt_expiry_seconds | int | 3600 | JWT token expiry |
| api_key_hash_scheme | str | "bcrypt" | passlib scheme for API key hashing |

**TracingSettings:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | True | Enable tracing |
| exporter | str | "otlp" | Exporter type: otlp / console / none |
| otlp_endpoint | str | "http://localhost:4317" | OTLP collector endpoint |
| service_name | str | "agent-platform" | OTel service name |
| sample_rate | float | 1.0 | Sampling rate (1.0 = 100%) |

**GovernanceSettings:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| audit_enabled | bool | True | Enable audit logging |
| audit_buffer_size | int | 1000 | Audit write-behind buffer size |
| audit_flush_interval_ms | int | 500 | Audit flush interval (ms) |
| retention_enabled | bool | True | Enable data retention |
| retention_schedule_cron | str | "0 2 * * *" | Retention job cron (daily at 2 AM) |
| classification_enabled | bool | True | Enable data classification |
| cost_tracking_enabled | bool | True | Enable cost tracking |

### 4.2 Environment Variable Examples

Các biến môi trường cho local development (file `.env`):

- **Database:** `APP_DATABASE__HOST=localhost`, `APP_DATABASE__PORT=5432`, `APP_DATABASE__NAME=agent_platform`, `APP_DATABASE__USER=postgres`, `APP_DATABASE__PASSWORD=localdev`
- **Redis:** `APP_REDIS__URL=redis://localhost:6379/0`
- **LLM:** `APP_LLM__ANTHROPIC_API_KEY=sk-ant-api03-...`
- **Auth:** `APP_AUTH__JWT_SECRET=dev-secret-change-in-production`
- **Tracing:** `APP_TRACING__ENABLED=true`, `APP_TRACING__EXPORTER=console`

### 4.3 Config Access Pattern

Settings được load một lần tại startup dưới dạng singleton, sử dụng hàm `get_settings()` được cache bằng `@lru_cache` (từ `functools`). Hàm này trả về instance duy nhất của `Settings()` và được inject vào mọi component qua DI.

---

## 5. Dependency Injection / Wiring

### 5.1 Strategy: Manual DI via FastAPI Depends + Lifespan

**Không dùng DI framework** (e.g., `dependency-injector`). Lý do:
- FastAPI `Depends()` đã đủ cho request-scoped dependencies
- App-scoped singletons quản lý qua `lifespan` context
- Ít magic, dễ debug, dễ test

### 5.2 Application State (Singletons)

Class **AppState** là một dataclass chứa tất cả application-scoped singletons. Được tạo trong lifespan, gắn vào `app.state`, và inject vào request handlers qua FastAPI Depends.

| Field | Type | Description |
|-------|------|-------------|
| settings | Settings | Application configuration |
| db_engine | AsyncEngine | SQLAlchemy async engine |
| db_session_factory | async_sessionmaker | DB session factory |
| redis | Redis | Async Redis client |
| llm_gateway | AnthropicGateway | LLM provider |
| mcp_client_manager | MCPClientManager | MCP connection manager |
| agent_service | AgentService | Agent CRUD service |
| session_service | SessionService | Session lifecycle service |
| tool_service | ToolService | Tool registry & invocation |
| memory_service | MemoryService | Memory orchestration |
| guardrails_engine | GuardrailsEngine | Guardrails pipeline |
| event_bus | EventBus | Event publish/subscribe |
| governance | GovernancePort | Governance (audit, retention, cost) |

### 5.3 Lifespan — Startup / Shutdown

Hàm **lifespan** là một async context manager gắn vào FastAPI app, chịu trách nhiệm tạo và dọn dẹp tất cả resources. Quy trình khởi tạo theo 6 phase:

**Phase 1 — Infrastructure:** Tạo async database engine (SQLAlchemy) với pool size từ settings, tạo session factory (`expire_on_commit=False`), tạo Redis client từ URL. Verify connections bằng `SELECT 1` (database) và `PING` (Redis).

**Phase 2 — Tracing:** Khởi tạo OpenTelemetry tracer provider từ tracing settings.

**Phase 3 — Providers:** Tạo `AnthropicGateway` với config gồm api_key, default_timeout, max_connections, max_keepalive. Tạo `MCPClientManager` với Redis instance.

**Phase 4 — Stores:** Tạo tất cả PostgreSQL repositories (AgentRepository, SessionRepository, MessageRepository, CheckpointRepository, ToolRepository, AuditRepository, CostRepository) — mỗi repository nhận `db_session_factory`. Tạo tất cả Redis stores (SessionRedisStore, CheckpointRedisStore, BudgetRedisStore, RateLimitRedisStore, CostRedisStore, TaskQueue, EventPublisher) — mỗi store nhận Redis client.

**Phase 5 — Cross-cutting:** Tạo `LocalGovernance` với AuditSink (audit_repo + buffer_size từ settings), RetentionScheduler (db_session_factory), DataClassifier, CostAggregator (cost_store + cost_repo). Tạo `EventBus` với EventPublisher và 3 consumers: SSEConsumer, TraceConsumer (tracer_provider), GovernanceConsumer (governance). Tạo `GuardrailsEngine` với SchemaValidator, InjectionDetector, ToolPermissionEnforcer, BudgetEnforcer (budget_store), RateLimitEnforcer (rate_limit_store), HITLGate (session_store + event_bus).

**Phase 6 — Services:** Tạo `MemoryService` với ShortTermMemory (session_store), WorkingMemory (session_store), llm_gateway. Tạo `ToolService` với ToolRegistry (tool_repo), ToolDiscoveryService (mcp_client_manager), SchemaConverter, ToolRuntime (mcp_client_manager). Tạo `AgentService` (agent_repo, tool_service) và `SessionService` (session_repo, session_store, task_queue, event_bus).

Sau đó compose tất cả thành **AppState**, gắn vào `app.state.app`. Start background tasks: `event_bus.start()` và `governance.start()` (audit flush timer, retention scheduler).

Khi yield xong (app shutdown), dọn dẹp theo thứ tự ngược: governance.stop() → event_bus.stop() → mcp_client_manager.close_all() → redis.aclose() → db_engine.dispose().

### 5.4 FastAPI Dependency Providers

File `src/api/deps.py` định nghĩa các dependency provider functions cho FastAPI:

- **get_app_state(request)** → Lấy AppState từ `request.app.state.app`.
- **get_db_session(state)** → Async generator, tạo AsyncSession từ `state.db_session_factory()` và yield session (auto cleanup khi request kết thúc). Depends vào get_app_state.
- **get_agent_service(state)** → Trả về `state.agent_service`. Depends vào get_app_state.
- **get_session_service(state)** → Trả về `state.session_service`. Depends vào get_app_state.
- **get_tool_service(state)** → Trả về `state.tool_service`. Depends vào get_app_state.

Cách sử dụng trong routes: các route handler khai báo dependency qua `Depends(get_agent_service)`, ví dụ endpoint `POST /agents` nhận `agent_service: AgentService = Depends(get_agent_service)` và `tenant_id: str = Depends(get_current_tenant)`, sau đó gọi `agent_service.create(tenant_id, body)`.

### 5.5 Executor Worker — Separate Process

Class **TaskWorker** chạy như process(es) riêng biệt, consume ExecutionTask từ Redis Streams. Worker có AppState riêng (DB pool, Redis, providers) — KHÔNG shared với API process.

TaskWorker nhận AppState qua constructor và tạo `AgentExecutor` với các dependencies: llm_gateway, tool_runtime (từ tool_service.runtime), memory_manager (memory_service), CheckpointManager (CheckpointRedisStore + CheckpointRepository), BudgetController (BudgetRedisStore), EventEmitter (event_bus), guardrails (guardrails_engine).

Method `run()` là main consumer loop — xem chi tiết tại [event-bus.md](08-event-bus.md) cho Redis Streams details.

### 5.6 Testing — Dependency Override

File `tests/conftest.py` định nghĩa shared fixtures:

- **mock_redis** — Fixture trả về `FakeRedis()` (từ `fakeredis.aioredis`) để test mà không cần Redis server thật.
- **mock_llm_gateway** — Fixture trả về mock object ghi lại các calls và trả về canned responses.
- **app_state(mock_redis, mock_llm_gateway, test_db_session_factory)** — Fixture tạo AppState với `Settings(environment="test")`, mock_redis, mock_llm_gateway, test_db_session_factory, và các mock khác.

---

## 6. Database Migration (Alembic)

### 6.1 Setup

```
migrations/
├── alembic.ini          # Alembic config (points to env.py)
├── env.py               # Migration environment (async engine)
└── versions/
    ├── 001_initial_schema.py
    ├── 002_add_audit_partitions.py
    └── ...
```

### 6.2 Alembic Configuration

File **alembic.ini** cấu hình Alembic với `script_location = migrations`. Thuộc tính `sqlalchemy.url` được set placeholder (sẽ bị override bởi env.py lúc runtime).

File **migrations/env.py** chịu trách nhiệm chạy migrations với async engine. Nó import `get_settings()` để lấy database DSN, tạo async engine bằng `create_async_engine(settings.database.dsn)`, rồi thực thi migrations trong async context (sử dụng `asyncio.run()`). Connections được mở qua `connectable.connect()` và migrations chạy qua `connection.run_sync()`.

### 6.3 Migration Strategy

| Rule | Detail |
|------|--------|
| **Naming** | `NNN_description.py` — sequential numbering, snake_case description |
| **One concern per migration** | Không mix schema changes với data migrations |
| **Backwards compatible** | Add column → nullable hoặc with default. Drop column → 2-step (deprecate → remove) |
| **Idempotent** | Use `IF NOT EXISTS`, `IF EXISTS` where applicable |
| **RLS always on** | Mọi table mới phải có RLS policy |
| **Partition management** | Audit partitions created by RetentionScheduler, not Alembic |

### 6.4 Initial Migration Scope

File `migrations/versions/001_initial_schema.py` tạo initial schema bao gồm: tenants, agents, sessions, messages, checkpoints (deltas + snapshots), mcp_servers, tools, audit_events (partitioned), cost_events, cost_daily_aggregates. DDL definitions tham chiếu tại [data-models.md](01-data-models.md) Section 10.

### 6.5 Commands

Các lệnh Alembic thường dùng:

- **Tạo migration mới:** Chạy `alembic revision --autogenerate -m "add_xyz_table"` để tự động generate migration từ model changes.
- **Chạy migrations:** Chạy `alembic upgrade head` để apply tất cả pending migrations.
- **Rollback một bước:** Chạy `alembic downgrade -1` để rollback migration gần nhất.
- **Xem version hiện tại:** Chạy `alembic current` để hiển thị migration version đang active.

---

## 7. Application Entry Points

### 7.1 API Server

File `src/main.py` là entry point chính cho API server. Nó import `create_app()` từ `src.api.app` để tạo FastAPI app instance. Khi chạy trực tiếp (dưới dạng script), sử dụng `uvicorn.run()` với tham số: module path `"src.main:app"`, host `"0.0.0.0"`, port `8000`, workers `1` (single worker per container, scale via K8s replicas), log_level `"info"`.

File `src/api/app.py` định nghĩa hàm `create_app()` trả về FastAPI instance với title "Agent Platform API", version "0.1.0", và lifespan function. Middleware được đăng ký theo thứ tự thực thi bottom-to-top: RequestIDMiddleware, TenantMiddleware, AuthMiddleware (nhận settings.auth), và error_handler_middleware (exception handler). Routes được mount với prefix `/api/v1`: agents_router, sessions_router, messages_router, tools_router, audit_router, stream_router. Một health check endpoint `GET /health` trả về `{"status": "ok"}`.

### 7.2 Executor Worker

Executor worker chạy như separate process bằng lệnh `python -m src.engine.worker`.

File `src/engine/worker.py` (phần entry point) định nghĩa hàm async `main()` — worker entry point. Hàm này tạo AppState riêng cho worker (cùng infrastructure nhưng không có HTTP server) bằng `build_worker_state(settings)`, sau đó tạo `TaskWorker(state)` và gọi `worker.run()`. Khi file được chạy trực tiếp, nó sử dụng `asyncio.run(main())`.

---

## 8. Docker (Local Development)

### 8.1 docker-compose.yml

File `deploy/docker/docker-compose.yml` (version 3.9) định nghĩa các services cho local development:

| Service | Image / Build | Ports | Dependencies | Notes |
|---------|---------------|-------|-------------|-------|
| api | Build từ `deploy/docker/Dockerfile` | 8000:8000 | postgres (healthy), redis (healthy) | Load env từ `.env` |
| worker | Build từ `deploy/docker/Dockerfile.worker` | (none) | postgres (healthy), redis (healthy) | Load env từ `.env`, replicas: 2 |
| postgres | postgres:16-alpine | 5432:5432 | (none) | DB: agent_platform, user: postgres, password: localdev. Volume: pgdata. Healthcheck: pg_isready mỗi 5s |
| redis | redis:7-alpine | 6379:6379 | (none) | Healthcheck: redis-cli ping mỗi 5s |

Volume `pgdata` được khai báo để persist PostgreSQL data.

### 8.2 Dockerfile

**Dockerfile (API server)** tại `deploy/docker/Dockerfile`: Base image `python:3.12-slim`. Working directory `/app`. Copy `pyproject.toml` rồi chạy `pip install --no-cache-dir .` để cài dependencies. Copy `src/` và `migrations/` vào image. Expose port 8000. Command mặc định: `uvicorn src.main:app --host 0.0.0.0 --port 8000`.

**Dockerfile (Worker)** tại `deploy/docker/Dockerfile.worker`: Base image `python:3.12-slim`. Working directory `/app`. Copy `pyproject.toml` rồi chạy `pip install --no-cache-dir .` để cài dependencies. Copy `src/` vào image (không cần migrations). Command mặc định: `python -m src.engine.worker`.

---

## 9. Resolved Questions

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | DI framework? | No — manual DI via FastAPI Depends + lifespan | Less magic, easier to debug and test. FastAPI Depends is sufficient |
| 2 | ORM or raw SQL? | SQLAlchemy Core (not ORM) for hot path; ORM optional for CRUD | Performance for checkpoint/audit writes. ORM OK for agent/session CRUD |
| 3 | Config source? | Env vars only (Pydantic Settings) | 12-factor app. No config files to manage. `.env` for local dev |
| 4 | Monorepo or separate packages? | Single package (`src/`) | Phase 1 simplicity. Extract packages when team grows |
| 5 | API + Worker same image? | Separate Dockerfiles, same codebase | Different entry points, different scaling needs |
| 6 | Migration tool? | Alembic (async) | De facto standard for SQLAlchemy. Async support via asyncpg |
| 7 | Logging? | structlog (JSON) | Structured, async-friendly, integrates with OTel |
