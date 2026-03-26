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

```toml
[project]
name = "agent-platform"
version = "0.1.0"
requires-python = ">=3.12"
description = "Agent Serving Platform"

dependencies = [
    # Web framework
    "fastapi>=0.115,<1.0",
    "uvicorn[standard]>=0.32,<1.0",
    "sse-starlette>=2.0,<3.0",       # SSE support for FastAPI

    # LLM providers
    "anthropic>=0.42,<1.0",           # Anthropic SDK (includes httpx)

    # MCP
    "mcp>=1.0,<2.0",                  # MCP Python SDK

    # Database
    "asyncpg>=0.30,<1.0",            # Async PostgreSQL driver
    "sqlalchemy>=2.0,<3.0",          # SQL toolkit (async)
    "alembic>=1.14,<2.0",            # Database migrations

    # Redis
    "redis[hiredis]>=5.2,<6.0",     # Async Redis client

    # Configuration
    "pydantic>=2.10,<3.0",           # Data validation
    "pydantic-settings>=2.7,<3.0",   # Settings from env vars

    # Observability
    "opentelemetry-api>=1.29,<2.0",
    "opentelemetry-sdk>=1.29,<2.0",
    "opentelemetry-exporter-otlp>=1.29,<2.0",
    "opentelemetry-instrumentation-fastapi>=0.50b,<1.0",
    "opentelemetry-instrumentation-httpx>=0.50b,<1.0",
    "opentelemetry-instrumentation-redis>=0.50b,<1.0",
    "opentelemetry-instrumentation-sqlalchemy>=0.50b,<1.0",

    # Serialization
    "msgpack>=1.1,<2.0",             # Binary serialization for checkpoints
    "orjson>=3.10,<4.0",             # Fast JSON (optional, replace stdlib json)

    # Security
    "python-jose[cryptography]>=3.3,<4.0",  # JWT validation
    "passlib[bcrypt]>=1.7,<2.0",     # Password hashing (API keys)
    "cryptography>=44,<45",          # Encryption (MCP server env vars)

    # Utilities
    "structlog>=24.4,<25.0",         # Structured logging
    "tenacity>=9.0,<10.0",           # Retry utility (used by stores, not LLM — LLM has custom retry)
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3,<9.0",
    "pytest-asyncio>=0.25,<1.0",
    "pytest-cov>=6.0,<7.0",
    "httpx>=0.28,<1.0",              # TestClient
    "fakeredis[lua]>=2.26,<3.0",     # In-memory Redis for tests
    "testcontainers[postgres]>=4.0,<5.0",  # PostgreSQL in Docker for integration tests
    "factory-boy>=3.3,<4.0",         # Test fixtures
    "ruff>=0.8,<1.0",                # Linter + formatter
    "mypy>=1.14,<2.0",               # Type checking
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "unit: Unit tests (no external deps)",
    "integration: Integration tests (need PG + Redis)",
    "e2e: End-to-end tests (full system)",
]

[tool.ruff]
target-version = "py312"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
```

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

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """
    Root configuration. Load từ env vars, prefix = APP_.
    Ví dụ: APP_DATABASE__HOST=localhost → settings.database.host
    """
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ──
    app_name: str = "agent-platform"
    environment: str = "development"           # development | staging | production
    debug: bool = False
    log_level: str = "INFO"

    # ── Server ──
    server: "ServerSettings" = Field(default_factory=lambda: ServerSettings())

    # ── Database ──
    database: "DatabaseSettings" = Field(default_factory=lambda: DatabaseSettings())

    # ── Redis ──
    redis: "RedisSettings" = Field(default_factory=lambda: RedisSettings())

    # ── LLM ──
    llm: "LLMSettings" = Field(default_factory=lambda: LLMSettings())

    # ── Auth ──
    auth: "AuthSettings" = Field(default_factory=lambda: AuthSettings())

    # ── Tracing ──
    tracing: "TracingSettings" = Field(default_factory=lambda: TracingSettings())

    # ── Governance ──
    governance: "GovernanceSettings" = Field(default_factory=lambda: GovernanceSettings())


class ServerSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1                           # uvicorn workers (API process)
    executor_workers: int = 4                  # executor worker processes


class DatabaseSettings(BaseSettings):
    host: str = "localhost"
    port: int = 5432
    name: str = "agent_platform"
    user: str = "postgres"
    password: str = ""                         # REQUIRED in production
    pool_min_size: int = 5
    pool_max_size: int = 20
    echo: bool = False                         # SQLAlchemy echo (debug only)

    @property
    def dsn(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class RedisSettings(BaseSettings):
    url: str = "redis://localhost:6379/0"
    max_connections: int = 50
    decode_responses: bool = True
    socket_timeout: float = 5.0
    retry_on_timeout: bool = True


class LLMSettings(BaseSettings):
    anthropic_api_key: str = ""                # REQUIRED
    default_model: str = "claude-sonnet-4-5-20250514"
    default_timeout: float = 120.0
    max_connections: int = 100
    max_keepalive: int = 20


class AuthSettings(BaseSettings):
    jwt_secret: str = ""                       # REQUIRED in production (or use JWKS)
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "agent-platform"
    jwt_audience: str = "agent-platform"
    jwt_expiry_seconds: int = 3600
    api_key_hash_scheme: str = "bcrypt"        # passlib scheme


class TracingSettings(BaseSettings):
    enabled: bool = True
    exporter: str = "otlp"                     # otlp | console | none
    otlp_endpoint: str = "http://localhost:4317"
    service_name: str = "agent-platform"
    sample_rate: float = 1.0                   # 1.0 = 100% sampling


class GovernanceSettings(BaseSettings):
    audit_enabled: bool = True
    audit_buffer_size: int = 1000
    audit_flush_interval_ms: int = 500
    retention_enabled: bool = True
    retention_schedule_cron: str = "0 2 * * *"
    classification_enabled: bool = True
    cost_tracking_enabled: bool = True
```

### 4.2 Environment Variable Examples

```bash
# .env (local development)

# Database
APP_DATABASE__HOST=localhost
APP_DATABASE__PORT=5432
APP_DATABASE__NAME=agent_platform
APP_DATABASE__USER=postgres
APP_DATABASE__PASSWORD=localdev

# Redis
APP_REDIS__URL=redis://localhost:6379/0

# LLM
APP_LLM__ANTHROPIC_API_KEY=sk-ant-api03-...

# Auth
APP_AUTH__JWT_SECRET=dev-secret-change-in-production

# Tracing
APP_TRACING__ENABLED=true
APP_TRACING__EXPORTER=console
```

### 4.3 Config Access Pattern

```python
# Singleton — loaded once at startup, injected everywhere via DI
from functools import lru_cache

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

---

## 5. Dependency Injection / Wiring

### 5.1 Strategy: Manual DI via FastAPI Depends + Lifespan

**Không dùng DI framework** (e.g., `dependency-injector`). Lý do:
- FastAPI `Depends()` đã đủ cho request-scoped dependencies
- App-scoped singletons quản lý qua `lifespan` context
- Ít magic, dễ debug, dễ test

### 5.2 Application State (Singletons)

```python
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from redis.asyncio import Redis


@dataclass
class AppState:
    """
    Application-scoped singletons. Created in lifespan, attached to app.state.
    Injected into request handlers via FastAPI Depends.
    """
    settings: Settings
    db_engine: AsyncEngine
    db_session_factory: async_sessionmaker
    redis: Redis

    # Providers
    llm_gateway: "AnthropicGateway"
    mcp_client_manager: "MCPClientManager"

    # Services
    agent_service: "AgentService"
    session_service: "SessionService"
    tool_service: "ToolService"
    memory_service: "MemoryService"

    # Engine
    guardrails_engine: "GuardrailsEngine"
    event_bus: "EventBus"

    # Governance
    governance: "GovernancePort"
```

### 5.3 Lifespan — Startup / Shutdown

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: create → yield (serve) → cleanup."""

    settings = get_settings()

    # ── Phase 1: Infrastructure ──
    db_engine = create_async_engine(settings.database.dsn, pool_size=settings.database.pool_max_size)
    db_session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    redis = Redis.from_url(settings.redis.url, max_connections=settings.redis.max_connections)

    # Verify connections
    async with db_engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    await redis.ping()

    # ── Phase 2: Tracing ──
    tracer_provider = setup_tracing(settings.tracing)

    # ── Phase 3: Providers ──
    llm_gateway = AnthropicGateway(
        config=AnthropicGatewayConfig(
            api_key=settings.llm.anthropic_api_key,
            default_timeout=settings.llm.default_timeout,
            max_connections=settings.llm.max_connections,
            max_keepalive=settings.llm.max_keepalive,
        )
    )

    mcp_client_manager = MCPClientManager(redis=redis)

    # ── Phase 4: Stores ──
    agent_repo = AgentRepository(db_session_factory)
    session_repo = SessionRepository(db_session_factory)
    message_repo = MessageRepository(db_session_factory)
    checkpoint_repo = CheckpointRepository(db_session_factory)
    tool_repo = ToolRepository(db_session_factory)
    audit_repo = AuditRepository(db_session_factory)
    cost_repo = CostRepository(db_session_factory)

    session_store = SessionRedisStore(redis)
    checkpoint_store = CheckpointRedisStore(redis)
    budget_store = BudgetRedisStore(redis)
    rate_limit_store = RateLimitRedisStore(redis)
    cost_store = CostRedisStore(redis)
    task_queue = TaskQueue(redis)
    event_publisher = EventPublisher(redis)

    # ── Phase 5: Cross-cutting ──
    governance = LocalGovernance(
        audit_sink=AuditSink(audit_repo, buffer_size=settings.governance.audit_buffer_size),
        retention=RetentionScheduler(db_session_factory),
        classifier=DataClassifier(),
        cost_aggregator=CostAggregator(cost_store, cost_repo),
    )

    event_bus = EventBus(
        publisher=event_publisher,
        consumers=[
            SSEConsumer(),
            TraceConsumer(tracer_provider),
            GovernanceConsumer(governance),
        ],
    )

    guardrails_engine = GuardrailsEngine(
        schema_validator=SchemaValidator(),
        injection_detector=InjectionDetector(),
        tool_permission=ToolPermissionEnforcer(),
        budget_enforcer=BudgetEnforcer(budget_store),
        rate_limiter=RateLimitEnforcer(rate_limit_store),
        hitl_gate=HITLGate(session_store, event_bus),
    )

    # ── Phase 6: Services ──
    memory_service = MemoryService(
        short_term=ShortTermMemory(session_store),
        working=WorkingMemory(session_store),
        llm_gateway=llm_gateway,
    )

    tool_service = ToolService(
        registry=ToolRegistry(tool_repo),
        discovery=ToolDiscoveryService(mcp_client_manager),
        schema_converter=SchemaConverter(),
        runtime=ToolRuntime(mcp_client_manager),
    )

    agent_service = AgentService(agent_repo, tool_service)
    session_service = SessionService(session_repo, session_store, task_queue, event_bus)

    # ── Compose AppState ──
    state = AppState(
        settings=settings,
        db_engine=db_engine,
        db_session_factory=db_session_factory,
        redis=redis,
        llm_gateway=llm_gateway,
        mcp_client_manager=mcp_client_manager,
        agent_service=agent_service,
        session_service=session_service,
        tool_service=tool_service,
        memory_service=memory_service,
        guardrails_engine=guardrails_engine,
        event_bus=event_bus,
        governance=governance,
    )

    app.state.app = state

    # ── Start background tasks ──
    await event_bus.start()
    await governance.start()                   # audit flush timer, retention scheduler

    yield

    # ── Shutdown (reverse order) ──
    await governance.stop()
    await event_bus.stop()
    await mcp_client_manager.close_all()
    await redis.aclose()
    await db_engine.dispose()
```

### 5.4 FastAPI Dependency Providers

```python
# src/api/deps.py

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession


def get_app_state(request: Request) -> AppState:
    return request.app.state.app


async def get_db_session(state: AppState = Depends(get_app_state)) -> AsyncSession:
    async with state.db_session_factory() as session:
        yield session


def get_agent_service(state: AppState = Depends(get_app_state)) -> AgentService:
    return state.agent_service


def get_session_service(state: AppState = Depends(get_app_state)) -> SessionService:
    return state.session_service


def get_tool_service(state: AppState = Depends(get_app_state)) -> ToolService:
    return state.tool_service


# Usage in routes:
@router.post("/agents")
async def create_agent(
    body: CreateAgentRequest,
    agent_service: AgentService = Depends(get_agent_service),
    tenant_id: str = Depends(get_current_tenant),
):
    return await agent_service.create(tenant_id, body)
```

### 5.5 Executor Worker — Separate Process

```python
# src/engine/worker.py

class TaskWorker:
    """
    Runs as separate process(es). Consumes ExecutionTask from Redis Streams.
    Has its own AppState (DB pool, Redis, providers) — NOT shared with API process.
    """

    def __init__(self, state: AppState):
        self.state = state
        self.executor = AgentExecutor(
            llm_gateway=state.llm_gateway,
            tool_runtime=state.tool_service.runtime,
            memory_manager=state.memory_service,
            checkpoint_manager=CheckpointManager(
                redis_store=CheckpointRedisStore(state.redis),
                pg_repo=CheckpointRepository(state.db_session_factory),
            ),
            budget_controller=BudgetController(BudgetRedisStore(state.redis)),
            event_emitter=EventEmitter(state.event_bus),
            guardrails=state.guardrails_engine,
        )

    async def run(self):
        """Main consumer loop. See event-bus.md for Redis Streams details."""
        ...
```

### 5.6 Testing — Dependency Override

```python
# tests/conftest.py

import pytest
from fakeredis.aioredis import FakeRedis


@pytest.fixture
def mock_redis():
    return FakeRedis()


@pytest.fixture
def mock_llm_gateway():
    """Returns a mock that records calls and returns canned responses."""
    ...


@pytest.fixture
def app_state(mock_redis, mock_llm_gateway, test_db_session_factory):
    return AppState(
        settings=Settings(environment="test"),
        redis=mock_redis,
        llm_gateway=mock_llm_gateway,
        db_session_factory=test_db_session_factory,
        ...
    )
```

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

```ini
# alembic.ini
[alembic]
script_location = migrations
sqlalchemy.url = driver://user:pass@localhost/dbname  # overridden by env.py
```

```python
# migrations/env.py
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from src.core.config import get_settings

settings = get_settings()

def run_migrations_online():
    """Run migrations with async engine."""
    connectable = create_async_engine(settings.database.dsn)

    async def do_run():
        async with connectable.connect() as connection:
            await connection.run_sync(do_migrations, connection)

    import asyncio
    asyncio.run(do_run())
```

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

```python
# migrations/versions/001_initial_schema.py

"""
Initial schema: tenants, agents, sessions, messages,
checkpoints (deltas + snapshots), mcp_servers, tools,
audit_events (partitioned), cost_events, cost_daily_aggregates.

DDL definitions: see data-models.md Section 10.
"""
```

### 6.5 Commands

```bash
# Create new migration
alembic revision --autogenerate -m "add_xyz_table"

# Run migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1

# Show current version
alembic current
```

---

## 7. Application Entry Points

### 7.1 API Server

```python
# src/main.py

import uvicorn
from src.api.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        workers=1,           # single worker per container, scale via K8s replicas
        log_level="info",
    )
```

```python
# src/api/app.py

from fastapi import FastAPI
from src.api.middleware.auth import AuthMiddleware
from src.api.middleware.tenant import TenantMiddleware
from src.api.middleware.request_id import RequestIDMiddleware
from src.api.middleware.error_handler import error_handler_middleware


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Agent Platform API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware (execution order: bottom → top)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TenantMiddleware)
    app.add_middleware(AuthMiddleware, settings=settings.auth)
    app.add_exception_handler(Exception, error_handler_middleware)

    # Routes
    app.include_router(agents_router, prefix="/api/v1")
    app.include_router(sessions_router, prefix="/api/v1")
    app.include_router(messages_router, prefix="/api/v1")
    app.include_router(tools_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    app.include_router(stream_router, prefix="/api/v1")

    # Health check
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
```

### 7.2 Executor Worker

```bash
# Run as separate process
python -m src.engine.worker
```

```python
# src/engine/worker.py (entry point section)

async def main():
    """Worker entry point. Creates its own AppState, starts consuming tasks."""
    settings = get_settings()

    # Build worker-specific AppState (same infra, no HTTP server)
    state = await build_worker_state(settings)

    worker = TaskWorker(state)
    await worker.run()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

## 8. Docker (Local Development)

### 8.1 docker-compose.yml

```yaml
version: "3.9"

services:
  api:
    build:
      context: .
      dockerfile: deploy/docker/Dockerfile
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  worker:
    build:
      context: .
      dockerfile: deploy/docker/Dockerfile.worker
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      replicas: 2

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: agent_platform
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: localdev
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
```

### 8.2 Dockerfile

```dockerfile
# deploy/docker/Dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY src/ src/
COPY migrations/ migrations/

EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```dockerfile
# deploy/docker/Dockerfile.worker
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY src/ src/

CMD ["python", "-m", "src.engine.worker"]
```

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
