# Thiết Kế Chi Tiết: MCP & Tool System

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect
> **Parent:** [Architecture Overview](00-overview.md)

---

## 1. High-Level Diagram

```
┌───────────────────────────── MCP & TOOL SYSTEM ────────────────────────────────────┐
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         TOOL MANAGER (Service Layer)                        │   │
│  │                                                                              │   │
│  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                    │   │
│  │  │ Tool         │   │ Tool         │   │ Schema       │                    │   │
│  │  │ Registry     │   │ Discovery    │   │ Converter    │                    │   │
│  │  │              │   │ Service      │   │              │                    │   │
│  │  │ - CRUD       │   │ - MCP enum   │   │ - MCP →      │                    │   │
│  │  │ - Search     │   │ - Static cfg │   │   OpenAI fmt │                    │   │
│  │  │ - Namespace  │   │ - Capability │   │ - MCP →      │                    │   │
│  │  │   isolation  │   │   search     │   │   Anthropic  │                    │   │
│  │  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘                    │   │
│  └─────────┼──────────────────┼──────────────────┼────────────────────────────┘   │
│            │                  │                   │                                │
│  ┌─────────▼──────────────────▼──────────────────▼────────────────────────────┐   │
│  │                         TOOL RUNTIME (Execution Layer)                      │   │
│  │                                                                              │   │
│  │  ┌──────────────────────────────────────────────────────────────────────┐   │   │
│  │  │                   MCP CLIENT MANAGER                                  │   │   │
│  │  │                                                                       │   │   │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐                 │   │   │
│  │  │  │ Connection  │  │ Transport   │  │ Health       │                 │   │   │
│  │  │  │ Pool        │  │ Manager     │  │ Monitor      │                 │   │   │
│  │  │  │             │  │             │  │              │                 │   │   │
│  │  │  │ - Per-server│  │ - stdio     │  │ - Heartbeat  │                 │   │   │
│  │  │  │   conn mgmt │  │ - HTTP+SSE  │  │ - Auto-      │                 │   │   │
│  │  │  │ - Lifecycle │  │ - Streamable│  │   reconnect  │                 │   │   │
│  │  │  │ - Cleanup   │  │   HTTP      │  │ - Failover   │                 │   │   │
│  │  │  └─────────────┘  └─────────────┘  └──────────────┘                 │   │   │
│  │  └──────────────────────────────────────────────────────────────────────┘   │   │
│  │                                                                              │   │
│  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────────┐   │   │
│  │  │ Invocation   │   │ Result       │   │ Sandbox Manager              │   │   │
│  │  │ Handler      │   │ Processor    │   │                              │   │   │
│  │  │              │   │              │   │ ┌──────────┐ ┌────────────┐ │   │   │
│  │  │ - Route call │   │ - Normalize  │   │ │Container │ │ Process    │ │   │   │
│  │  │ - Timeout    │   │ - Truncate   │   │ │Sandbox   │ │ Sandbox    │ │   │   │
│  │  │ - Retry      │   │ - Error map  │   │ │(gVisor)  │ │(seccomp)  │ │   │   │
│  │  │ - Circuit    │   │ - Cost track │   │ └──────────┘ └────────────┘ │   │   │
│  │  │   breaker    │   │              │   │                              │   │   │
│  │  └──────────────┘   └──────────────┘   └──────────────────────────────┘   │   │
│  │                                                                              │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                          │                                                          │
│  ════════════════════════╪══════════════════════════════════════════════════════    │
│           MCP Protocol   │  (JSON-RPC 2.0)                                         │
│  ════════════════════════╪══════════════════════════════════════════════════════    │
│                          │                                                          │
│  ┌───────────────────────▼──────────────────────────────────────────────────────┐  │
│  │                         MCP SERVERS (External)                                │  │
│  │                                                                               │  │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌───────────┐ │  │
│  │  │ Database   │ │ GitHub     │ │ Filesystem │ │ Slack      │ │ Custom    │ │  │
│  │  │ (postgres, │ │ (repos,    │ │ (read,     │ │ (channels, │ │ (tenant-  │ │  │
│  │  │  sqlite,   │ │  issues,   │ │  write,    │ │  messages, │ │  provided │ │  │
│  │  │  mysql)    │ │  PRs)      │ │  search)   │ │  users)    │ │  servers) │ │  │
│  │  └────────────┘ └────────────┘ └────────────┘ └────────────┘ └───────────┘ │  │
│  │                                                                               │  │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐               │  │
│  │  │ Web Search │ │ Email      │ │ Jira /     │ │ Cloud APIs │               │  │
│  │  │ (Brave,    │ │ (SMTP,     │ │ ServiceNow │ │ (AWS, GCP, │               │  │
│  │  │  Google)   │ │  IMAP)     │ │            │ │  Azure)    │               │  │
│  │  └────────────┘ └────────────┘ └────────────┘ └────────────┘               │  │
│  │                                                                               │  │
│  └───────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Descriptions

### 2.1 Tool Manager (Service Layer)

Lớp service xử lý business logic: registry, discovery, schema conversion. Là interface chính mà các service khác (Executor, API) sử dụng.

```python
class ToolManager:
    """
    Service layer for all tool operations.
    Entry point for executor and API layer.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        discovery: ToolDiscoveryService,
        schema_converter: SchemaConverter,
        runtime: ToolRuntime,
    ): ...

    # --- Registry ---
    async def list_tools(self, tenant_id: str, agent_id: str | None = None) -> list[ToolInfo]:
        """List tools available to a tenant/agent, combining static + discovered."""

    async def get_tool(self, tenant_id: str, tool_id: str) -> ToolInfo:
        """Get full tool details including schema."""

    # --- Discovery ---
    async def discover_from_server(self, tenant_id: str, server_config: MCPServerConfig) -> list[ToolInfo]:
        """Connect to an MCP server, enumerate tools, register them."""

    async def refresh_tools(self, tenant_id: str, server_id: str) -> list[ToolInfo]:
        """Re-discover tools from an existing server (schema may have changed)."""

    # --- Execution ---
    async def invoke(
        self,
        tenant_id: str,
        session_id: str,
        tool_call: ToolCall,
    ) -> ToolResult:
        """
        Full invocation pipeline:
        1. Resolve tool from registry
        2. (Permission check is done by Guardrails before this call)
        3. Route to correct MCP server via runtime
        4. Handle timeout, retry, circuit breaker
        5. Process and normalize result
        6. Track cost and emit trace event
        """

    # --- Schema for LLM ---
    async def get_tool_schemas_for_llm(
        self,
        tenant_id: str,
        agent_id: str,
        llm_provider: str,
    ) -> list[dict]:
        """
        Get tool schemas formatted for a specific LLM provider.
        MCP tool schema → OpenAI function calling format / Anthropic tool_use format.
        """
```

---

#### 2.1.1 Tool Registry

Lưu trữ metadata của tất cả tools available trong platform, phân vùng theo tenant.

```python
@dataclass
class ToolInfo:
    id: str                                     # "mcp:github:create_issue"
    name: str                                   # "create_issue"
    server_id: str                              # ID of the MCP server this tool belongs to
    namespace: str                              # "mcp:github"
    description: str                            # "Create a new issue in a GitHub repository"
    input_schema: dict                          # JSONSchema for input parameters
    output_schema: dict | None                  # JSONSchema for output (optional)

    # Operational metadata
    execution_mode: Literal["sync", "async"]    # "sync" = wait for result, "async" = fire-and-forget
    default_timeout_ms: int                     # Per-tool timeout
    estimated_latency_ms: int | None            # Historical average latency
    estimated_cost: float | None                # Estimated cost per call (USD), if applicable
    idempotent: bool                            # Safe to retry?

    # Access control metadata
    permission_scope: list[str]                 # ["github:write", "issues:create"]
    risk_level: Literal["low", "medium", "high", "critical"]
    requires_approval: bool                     # Default HITL setting

    # Tenant scoping
    tenant_id: str
    visibility: Literal["platform", "tenant", "agent"]

    # Lifecycle
    discovered_at: datetime
    last_verified_at: datetime
    status: Literal["active", "degraded", "unavailable"]
```

**Storage:**

```sql
CREATE TABLE tools (
    id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    server_id TEXT NOT NULL,
    name TEXT NOT NULL,
    namespace TEXT NOT NULL,
    description TEXT NOT NULL,
    input_schema JSONB NOT NULL,
    output_schema JSONB,

    execution_mode TEXT DEFAULT 'sync',
    default_timeout_ms INT DEFAULT 30000,
    estimated_latency_ms INT,
    estimated_cost FLOAT,
    idempotent BOOLEAN DEFAULT FALSE,

    permission_scope TEXT[] DEFAULT '{}',
    risk_level TEXT DEFAULT 'low',
    requires_approval BOOLEAN DEFAULT FALSE,
    visibility TEXT DEFAULT 'tenant',

    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    last_verified_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT DEFAULT 'active',

    PRIMARY KEY (tenant_id, id),
    CONSTRAINT fk_server FOREIGN KEY (tenant_id, server_id)
        REFERENCES mcp_servers(tenant_id, id) ON DELETE CASCADE
);

-- Row-level security
ALTER TABLE tools ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tools
    USING (tenant_id = current_setting('app.current_tenant'));

-- Fast lookup by namespace
CREATE INDEX idx_tools_namespace ON tools (tenant_id, namespace);
```

```python
class ToolRegistry:
    async def register(self, tool: ToolInfo) -> None:
        """Register or update a tool in the registry."""

    async def unregister(self, tenant_id: str, tool_id: str) -> None:
        """Remove a tool from the registry."""

    async def list_by_agent(self, tenant_id: str, agent_id: str) -> list[ToolInfo]:
        """
        Get tools for a specific agent:
        1. Load agent definition → agent.tools (allowlist of tool patterns)
        2. Match against registry using glob patterns
        3. Return matched tools with status = 'active'
        """

    async def search(self, tenant_id: str, query: str, top_k: int = 10) -> list[ToolInfo]:
        """Semantic search across tool descriptions (Phase 2, capability-based discovery)."""

    async def update_status(self, tenant_id: str, tool_id: str, status: str) -> None:
        """Mark tool as active/degraded/unavailable based on health checks."""
```

---

#### 2.1.2 Tool Discovery Service

Kết nối đến MCP server, liệt kê tools, và đồng bộ vào registry.

```python
class ToolDiscoveryService:
    async def discover(
        self,
        tenant_id: str,
        server_config: MCPServerConfig,
    ) -> DiscoveryResult:
        """
        1. Connect to MCP server via configured transport
        2. Call tools/list (MCP protocol method)
        3. For each tool: parse schema, assign namespace, compute risk level
        4. Register in ToolRegistry
        5. Return summary of discovered tools

        Also discovers:
        - Resources (via resources/list) → registered as read-only tools
        - Prompts (via prompts/list) → registered as prompt templates
        """

    async def refresh(self, tenant_id: str, server_id: str) -> DiscoveryResult:
        """
        Re-run discovery for an existing server.
        Detects: new tools, removed tools, schema changes.
        Updates registry accordingly.
        """

    async def verify_tool(self, tenant_id: str, tool_id: str) -> VerificationResult:
        """
        Verify a specific tool is still available and schema matches registry.
        Called periodically by health monitor.
        """
```

---

#### 2.1.3 Schema Converter

Chuyển đổi MCP tool schema sang format mà từng LLM provider yêu cầu.

```python
class SchemaConverter:
    """
    MCP tool schema (JSONSchema-based) → LLM-specific format.
    Each LLM provider has slightly different tool/function calling format.
    """

    def to_anthropic(self, tool: ToolInfo) -> dict:
        """
        MCP tool → Anthropic tool_use format.
        Anthropic expects JSONSchema in input_schema field directly.
        MCP tool schema IS JSONSchema → minimal transformation needed.
        """
        # MCP tool.inputSchema is already JSONSchema — Anthropic accepts it directly
        schema = tool.input_schema.copy()

        # Ensure required top-level fields
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})

        return {
            "name": self._sanitize_name(tool.name, tool.namespace),
            "description": self._build_description(tool),
            "input_schema": schema,
        }

    def to_openai(self, tool: ToolInfo) -> dict:
        """MCP tool → OpenAI function calling format (Phase 2)."""
        schema = tool.input_schema.copy()
        schema.setdefault("type", "object")

        return {
            "type": "function",
            "function": {
                "name": self._sanitize_name(tool.name, tool.namespace),
                "description": self._build_description(tool),
                "parameters": schema,
            },
        }

    def to_google(self, tool: ToolInfo) -> dict:
        """MCP tool → Gemini function declaration format (Phase 2)."""
        schema = tool.input_schema.copy()
        schema.setdefault("type", "object")

        return {
            "name": self._sanitize_name(tool.name, tool.namespace),
            "description": self._build_description(tool),
            "parameters": schema,
        }

    def convert(self, tool: ToolInfo, provider: str) -> dict:
        """Dispatch to the correct converter based on LLM provider."""
        converters = {
            "anthropic": self.to_anthropic,
            "openai": self.to_openai,
            "google": self.to_google,
        }
        converter = converters.get(provider)
        if not converter:
            raise ValueError(f"Unknown LLM provider: {provider}")
        return converter(tool)

    def convert_batch(self, tools: list[ToolInfo], provider: str) -> list[dict]:
        """Convert multiple tools for a single LLM call."""
        return [self.convert(tool, provider) for tool in tools]

    def from_llm_tool_call(self, raw_call: dict, provider: str) -> ToolCall:
        """
        Parse LLM tool_call response back into normalized ToolCall model.
        Each provider returns tool calls in a different format.
        """
        match provider:
            case "anthropic":
                # Anthropic: content_block with type="tool_use"
                # Already parsed by LLM Gateway into ToolCall format
                return ToolCall(
                    id=raw_call["id"],
                    name=raw_call["name"],
                    arguments=raw_call.get("input", {}),
                )
            case "openai":
                # OpenAI: {"id", "function": {"name", "arguments": JSON string}}
                return ToolCall(
                    id=raw_call["id"],
                    name=raw_call["function"]["name"],
                    arguments=json.loads(raw_call["function"]["arguments"]),
                )
            case _:
                raise ValueError(f"Unknown provider: {provider}")

    def _sanitize_name(self, name: str, namespace: str) -> str:
        """
        Build tool name for LLM. Must be unique and valid identifier.

        Strategy:
        - Use namespace prefix to avoid collisions: "github__create_issue"
        - Replace invalid chars: ':', '-', '.' → '_'
        - Anthropic allows: [a-zA-Z0-9_-], max 64 chars

        Example: namespace="mcp:github", name="create_issue" → "github__create_issue"
        """
        # Extract short namespace: "mcp:github" → "github"
        short_ns = namespace.split(":")[-1] if ":" in namespace else namespace
        full_name = f"{short_ns}__{name}"
        # Sanitize: only allow alphanumeric, underscore, hyphen
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", full_name)
        return sanitized[:64]

    def _build_description(self, tool: ToolInfo) -> str:
        """
        Build description string for LLM.
        Include namespace context so LLM understands which service this tool belongs to.
        """
        prefix = f"[{tool.namespace}] " if tool.namespace else ""
        return f"{prefix}{tool.description}"
```

**Tại sao cần converter?**
- MCP tool schema = JSONSchema (chuẩn)
- Anthropic `tool_use` = JSONSchema nhưng wrapper khác OpenAI
- OpenAI `function calling` = `{"type":"function","function":{"name","parameters"}}`
- Google `function_declarations` = lại format khác
- Platform phải chạy trên bất kỳ LLM → converter là cầu nối

---

### 2.2 Tool Runtime (Execution Layer)

Lớp thực thi: quản lý kết nối MCP, gọi tools, xử lý kết quả.

#### 2.2.1 MCP Client Manager

Quản lý vòng đời kết nối đến tất cả MCP servers.

```python
class MCPClientManager:
    """
    Manages connections to all MCP servers for a platform instance.
    Each MCP server has exactly one managed connection (pooled per tenant if needed).
    """

    def __init__(
        self,
        transport_manager: TransportManager,
        health_monitor: HealthMonitor,
        connection_pool: ConnectionPool,
    ): ...

    async def get_client(self, tenant_id: str, server_id: str) -> MCPClient:
        """
        Get or create an MCP client connection.
        1. Check pool for existing connection
        2. If exists and healthy → return
        3. If not exists → create via transport manager
        4. If unhealthy → reconnect
        """
        key = (tenant_id, server_id)
        client = await self._pool.get(tenant_id, server_id)

        if client is not None:
            health = await self._health_monitor.get_cached_status(server_id)
            if health and health.status != "unhealthy":
                return client
            # Unhealthy → close and reconnect
            await self._pool.remove(tenant_id, server_id)
            await client.close()

        # Create new connection
        server_config = await self._load_server_config(tenant_id, server_id)
        client = await self.connect_server(server_config)
        return client

    async def connect_server(self, server_config: MCPServerConfig) -> MCPClient:
        """
        Establish new connection to an MCP server.
        1. Select transport (stdio / HTTP+SSE / Streamable HTTP)
        2. Perform MCP initialize handshake
        3. Negotiate capabilities
        4. Add to connection pool
        5. Start health monitoring
        """
        # 1. Create transport
        transport = await self._transport_manager.create_transport(server_config)

        # 2. Create MCP client with transport
        client = MCPClient(transport)

        # 3. Initialize handshake
        init_result = await client.initialize(
            client_info={"name": "agent-platform", "version": "1.0"},
            capabilities={"tools": True, "resources": True},
        )
        server_capabilities = init_result.capabilities

        # 4. Send initialized notification
        await client.initialized()

        # 5. Add to pool
        await self._pool.put(
            server_config.tenant_id,
            server_config.id,
            client,
        )

        # 6. Update server status
        server_config.status = "connected"
        server_config.last_connected_at = datetime.utcnow()

        # 7. Start health monitoring for this server
        await self._health_monitor.register(
            server_config.tenant_id,
            server_config.id,
            interval_seconds=server_config.health_check_interval_seconds,
        )

        return client

    async def disconnect_server(self, tenant_id: str, server_id: str) -> None:
        """Gracefully close connection and remove from pool."""
        await self._health_monitor.unregister(server_id)
        client = await self._pool.get(tenant_id, server_id)
        if client:
            await client.close()
            await self._pool.remove(tenant_id, server_id)

    async def disconnect_all(self, tenant_id: str) -> None:
        """Disconnect all servers for a tenant (cleanup on tenant deactivation)."""
        stats = await self._pool.get_stats()
        for server_id in stats.get(tenant_id, {}).keys():
            await self.disconnect_server(tenant_id, server_id)

    async def close_all(self) -> None:
        """Shutdown: disconnect every server across all tenants."""
        all_stats = await self._pool.get_stats()
        for tenant_id, servers in all_stats.items():
            for server_id in servers:
                await self.disconnect_server(tenant_id, server_id)
```

#### 2.2.2 Transport Manager

Xử lý các transport protocol mà MCP hỗ trợ.

```python
class TransportManager:
    """
    Creates the appropriate transport for connecting to an MCP server.
    MCP supports multiple transport mechanisms.
    """

    async def create_transport(self, config: MCPServerConfig) -> MCPTransport:
        match config.transport:
            case "stdio":
                return await self._create_stdio_transport(config)
            case "sse":
                return await self._create_sse_transport(config)
            case "streamable_http":
                return await self._create_streamable_http_transport(config)

    async def _create_stdio_transport(self, config: MCPServerConfig) -> StdioTransport:
        """
        Launch MCP server as subprocess, communicate via stdin/stdout.

        Lifecycle:
        1. Spawn process: config.command + config.args + config.env
        2. Wrap stdin/stdout as JSON-RPC transport
        3. Monitor process health (exit code, stderr)
        4. Auto-restart on crash (configurable max restarts)

        Security:
        - Process runs under restricted user (not root)
        - Resource limits: max memory, max CPU, max open files
        - Filesystem access restricted to config.allowed_paths
        """

    async def _create_sse_transport(self, config: MCPServerConfig) -> SSETransport:
        """
        Connect to remote MCP server via HTTP + Server-Sent Events.

        Lifecycle:
        1. HTTP POST to config.url for requests
        2. SSE stream from config.url/events for responses
        3. Auth via config.headers (Bearer token, API key)
        4. Reconnect on disconnect with exponential backoff

        Security:
        - TLS required (reject plain HTTP)
        - Auth token rotation support
        - Response size limits
        """

    async def _create_streamable_http_transport(self, config: MCPServerConfig) -> StreamableHTTPTransport:
        """
        Newer MCP transport: single HTTP endpoint, bidirectional streaming.
        Preferred for remote servers (simpler than SSE).
        """
```

**MCP Server Configuration Model:**

```python
@dataclass
class MCPServerConfig:
    id: str
    tenant_id: str
    name: str                               # Human-readable name
    description: str

    # Transport
    transport: Literal["stdio", "sse", "streamable_http"]

    # stdio-specific
    command: str | None                     # e.g., "npx", "python", "docker"
    args: list[str] | None                  # e.g., ["-y", "@modelcontextprotocol/server-postgres"]
    env: dict[str, str] | None             # Environment variables (may contain secrets)
    cwd: str | None                         # Working directory

    # HTTP-specific (sse / streamable_http)
    url: str | None                         # e.g., "https://mcp.example.com/v1"
    headers: dict[str, str] | None          # Auth headers

    # Connection settings
    connect_timeout_ms: int = 10_000
    request_timeout_ms: int = 30_000
    max_retries: int = 3
    retry_backoff_ms: int = 1_000

    # Lifecycle
    auto_start: bool = True                 # Start on platform boot?
    max_restarts: int = 5                   # For stdio: max auto-restarts
    health_check_interval_seconds: int = 60

    # Security
    allowed_tools: list[str] | None         # Whitelist (None = all)
    blocked_tools: list[str] | None         # Blacklist
    sandbox_level: Literal["none", "process", "container"] = "none"

    # Status
    status: Literal["connected", "connecting", "disconnected", "error"] = "disconnected"
    last_connected_at: datetime | None = None
    last_error: str | None = None
```

**Storage:**

```sql
CREATE TABLE mcp_servers (
    id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,

    transport TEXT NOT NULL,
    command TEXT,
    args JSONB,
    env_encrypted BYTEA,                    -- Encrypted environment variables
    url TEXT,
    headers_encrypted BYTEA,                -- Encrypted auth headers

    connect_timeout_ms INT DEFAULT 10000,
    request_timeout_ms INT DEFAULT 30000,
    max_retries INT DEFAULT 3,
    auto_start BOOLEAN DEFAULT TRUE,
    health_check_interval_seconds INT DEFAULT 60,

    allowed_tools TEXT[],
    blocked_tools TEXT[],
    sandbox_level TEXT DEFAULT 'none',

    status TEXT DEFAULT 'disconnected',
    last_connected_at TIMESTAMPTZ,
    last_error TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (tenant_id, id)
);

ALTER TABLE mcp_servers ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON mcp_servers
    USING (tenant_id = current_setting('app.current_tenant'));
```

#### 2.2.3 Connection Pool

```python
class ConnectionPool:
    """
    Manages active MCP client connections.
    Key: (tenant_id, server_id) → MCPClient

    Behaviors:
    - Lazy connection: connect on first use
    - Max connections per tenant: configurable (default 20)
    - Idle timeout: close connections unused for > 10 minutes
    - Graceful shutdown: close all on platform stop
    """

    async def get(self, tenant_id: str, server_id: str) -> MCPClient | None
    async def put(self, tenant_id: str, server_id: str, client: MCPClient) -> None
    async def remove(self, tenant_id: str, server_id: str) -> None
    async def get_stats(self) -> PoolStats    # active, idle, total per tenant
```

#### 2.2.4 Health Monitor

```python
class HealthMonitor:
    """
    Monitors MCP server health and manages auto-recovery.
    Runs as background task.
    """

    async def start(self) -> None:
        """Start monitoring loop."""

    async def check_server(self, tenant_id: str, server_id: str) -> HealthStatus:
        """
        Health check for a single server:
        1. Send MCP ping (or tools/list as lightweight check)
        2. Measure response latency
        3. Compare with historical baseline

        Returns: HealthStatus(
            status: "healthy" | "degraded" | "unhealthy",
            latency_ms: float,
            last_check: datetime,
            consecutive_failures: int,
        )
        """

    async def _on_unhealthy(self, tenant_id: str, server_id: str, status: HealthStatus) -> None:
        """
        Recovery actions:
        - stdio server: kill and restart process
        - HTTP server: reconnect with backoff
        - After max_restarts: mark as unavailable, alert
        - Update tool status in registry → executor won't try to call unavailable tools
        """
```

#### 2.2.5 Invocation Handler

Core logic cho việc gọi tool qua MCP.

```python
class InvocationHandler:
    """
    Handles the actual invocation of a tool on an MCP server.
    Includes timeout, retry, circuit breaker, and cost tracking.
    """

    def __init__(
        self,
        circuit_breaker: CircuitBreaker,
        result_processor: ResultProcessor,
        tracer,
    ):
        self._cb = circuit_breaker
        self._processor = result_processor
        self._tracer = tracer

    async def invoke(
        self,
        client: MCPClient,
        tool_call: ToolCall,
        tool_info: ToolInfo,
        timeout_ms: int | None = None,
    ) -> ToolResult:
        """
        Full invocation pipeline with timeout, circuit breaker, retry, and metrics.
        """
        effective_timeout = timeout_ms or tool_info.default_timeout_ms
        server_id = tool_info.server_id
        start = time.monotonic()

        # 1. Check circuit breaker
        if not await self._cb.allow_request(server_id):
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=f"Tool server temporarily unavailable (circuit breaker open for {server_id})",
                is_error=True,
                metadata={"circuit_breaker": "open"},
                latency_ms=0,
            )

        # 2. Execute with retry (if idempotent)
        try:
            with self._tracer.start_as_current_span("tool.invoke") as span:
                span.set_attribute("tool.name", tool_call.name)
                span.set_attribute("tool.server_id", server_id)

                if tool_info.idempotent and tool_info.max_retries > 0:
                    raw_result = await self._invoke_with_retry(
                        client, tool_call, tool_info, effective_timeout,
                    )
                else:
                    raw_result = await self._invoke_with_timeout(
                        client, tool_call.name, tool_call.arguments, effective_timeout,
                    )

                latency_ms = (time.monotonic() - start) * 1000
                span.set_attribute("tool.latency_ms", latency_ms)

                # 3. Record success
                await self._cb.record_success(server_id)

                # 4. Process result
                result = await self._processor.process(raw_result, tool_info)
                result.tool_call_id = tool_call.id
                result.latency_ms = latency_ms
                return result

        except ToolTimeoutError:
            latency_ms = (time.monotonic() - start) * 1000
            await self._cb.record_failure(server_id)
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=f"Tool '{tool_call.name}' timed out after {effective_timeout}ms",
                is_error=True,
                metadata={"error_category": "tool_timeout"},
                latency_ms=latency_ms,
            )

        except MCPConnectionError as e:
            latency_ms = (time.monotonic() - start) * 1000
            await self._cb.record_failure(server_id)
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=f"Connection error calling '{tool_call.name}': {e}",
                is_error=True,
                metadata={"error_category": "tool_connection_error"},
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            await self._cb.record_failure(server_id)
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=f"Error calling '{tool_call.name}': {e}",
                is_error=True,
                metadata={"error_category": "tool_execution_error"},
                latency_ms=latency_ms,
            )

    async def _invoke_with_timeout(self, client, name, arguments, timeout_ms) -> dict:
        """MCP tools/call with configurable timeout."""
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                return await client.call_tool(name, arguments)
        except asyncio.TimeoutError:
            raise ToolTimeoutError(f"Tool {name} timed out after {timeout_ms}ms")

    async def _invoke_with_retry(self, client, tool_call, tool_info, timeout_ms) -> dict:
        """
        Retry logic for idempotent tools:
        - Exponential backoff: 1s, 2s, 4s
        - Max retries from server config
        - Timeout → retry
        - Server error (MCP error code) → retry
        - Client error (invalid params) → do NOT retry
        - Connection error → raise (let caller handle reconnect)
        """
        max_retries = tool_info.max_retries or 2
        backoff_base = 1.0
        last_error = None

        for attempt in range(1 + max_retries):
            try:
                return await self._invoke_with_timeout(
                    client, tool_call.name, tool_call.arguments, timeout_ms,
                )
            except ToolTimeoutError as e:
                last_error = e
                if attempt < max_retries:
                    wait = backoff_base * (2 ** attempt)
                    await asyncio.sleep(wait)
                    continue
            except MCPServerError as e:
                # MCP server returned error — retry if not client fault
                if e.code and e.code >= -32600:  # client errors in JSON-RPC
                    raise  # don't retry client errors
                last_error = e
                if attempt < max_retries:
                    wait = backoff_base * (2 ** attempt)
                    await asyncio.sleep(wait)
                    continue

        raise last_error
```

**Circuit Breaker:**

```python
class CircuitBreaker:
    """
    Per-server circuit breaker to prevent cascading failures.

    States:
    - CLOSED: normal operation, requests flow through
    - OPEN: server is failing, reject requests immediately
    - HALF_OPEN: allow one test request to check recovery

    Transitions:
    CLOSED → OPEN: when failure_count >= threshold (default 5) within window (default 60s)
    OPEN → HALF_OPEN: after cooldown period (default 30s)
    HALF_OPEN → CLOSED: if test request succeeds
    HALF_OPEN → OPEN: if test request fails
    """

    async def allow_request(self, server_id: str) -> bool
    async def record_success(self, server_id: str) -> None
    async def record_failure(self, server_id: str) -> None
    async def get_state(self, server_id: str) -> CircuitState
```

#### 2.2.6 Result Processor

```python
class ResultProcessor:
    """
    Normalizes and processes raw MCP tool results before returning to the executor.
    """

    async def process(self, raw_result: dict, tool_info: ToolInfo) -> ToolResult:
        """
        1. Extract content from MCP result format
           MCP returns: { content: [{ type: "text", text: "..." }], isError: bool }

        2. Normalize to platform format:
           ToolResult(content: str, is_error: bool, metadata: dict)

        3. Truncate if too large (protect context window):
           - If content > max_result_tokens: truncate with "[...truncated, full result stored]"
           - Store full result in artifact store, reference in metadata

        4. Redact sensitive data if PII policy requires

        5. Calculate cost (if tool has cost model)
        """

    def _truncate(self, content: str, max_tokens: int = 4000) -> tuple[str, bool]:
        """Truncate content to fit in context window, preserving start and end."""
        # Keep first 60% + last 40% of budget, insert truncation marker
```

**ToolResult model:**

```python
@dataclass
class ToolResult:
    tool_call_id: str               # Matches the LLM's tool_call ID
    tool_name: str
    content: str                    # Normalized text content
    is_error: bool
    metadata: dict                  # latency_ms, server_id, truncated, etc.
    artifacts: list[str] | None     # References to large stored artifacts
    cost_usd: float | None         # Cost of this invocation (if tracked)
    latency_ms: float
```

#### 2.2.7 Sandbox Manager (Phase 2)

Cho các tool cần chạy code hoặc truy cập filesystem.

```python
class SandboxManager:
    """
    Provides isolated execution environments for tools that need them.
    Used primarily for code execution tools and filesystem tools.
    """

    async def execute_in_sandbox(
        self,
        sandbox_level: Literal["process", "container"],
        command: str,
        args: list[str],
        env: dict[str, str],
        timeout_seconds: int = 30,
        constraints: SandboxConstraints | None = None,
    ) -> SandboxResult:
        """
        Process sandbox: seccomp + AppArmor profile
        Container sandbox: ephemeral container (gVisor runtime)

        Constraints:
        - max_memory_mb: 512 (default)
        - max_cpu_seconds: 30
        - network_access: False (default)
        - allowed_network_hosts: [] (whitelist if network_access=True)
        - writable_paths: ["/tmp/workspace"]
        - readonly_paths: ["/data/input"]
        """
```

---

## 3. Sequence Diagrams

### 3.1 MCP Server Connection & Tool Discovery

```
Admin API       Tool Manager      Discovery Svc       Transport Mgr      MCP Server
 │                  │                  │                   │                  │
 │──POST            │                  │                   │                  │
 │  /tools/discover │                  │                   │                  │
 │  {server_config} │                  │                   │                  │
 │─────────────────→│                  │                   │                  │
 │                  │──discover()─────→│                   │                  │
 │                  │                  │                   │                  │
 │                  │                  │──create_transport()→│                │
 │                  │                  │                   │──spawn process──→│
 │                  │                  │                   │  (stdio) or      │
 │                  │                  │                   │  HTTP connect     │
 │                  │                  │                   │◄──ready──────────│
 │                  │                  │◄──transport────────│                  │
 │                  │                  │                   │                  │
 │                  │                  │═══ MCP HANDSHAKE ═════════════════════│
 │                  │                  │                                       │
 │                  │                  │──initialize()───────────────────────→│
 │                  │                  │  {protocolVersion: "2025-03-26",     │
 │                  │                  │   capabilities: {tools: true},       │
 │                  │                  │   clientInfo: {name: "agent-platform"│
 │                  │                  │                version: "1.0"}}      │
 │                  │                  │◄──{serverInfo, capabilities}─────────│
 │                  │                  │                                       │
 │                  │                  │──initialized()──────────────────────→│
 │                  │                  │  (notification, no response)         │
 │                  │                  │                                       │
 │                  │                  │═══ TOOL DISCOVERY ════════════════════│
 │                  │                  │                                       │
 │                  │                  │──tools/list()───────────────────────→│
 │                  │                  │◄──{tools: [                          │
 │                  │                  │     {name: "query",                  │
 │                  │                  │      description: "Run SQL query",   │
 │                  │                  │      inputSchema: {...}},            │
 │                  │                  │     {name: "list_tables",            │
 │                  │                  │      description: "List tables",     │
 │                  │                  │      inputSchema: {...}}             │
 │                  │                  │   ]}                                  │
 │                  │                  │                                       │
 │                  │                  │ ┌─ FOR EACH TOOL ────────────────┐   │
 │                  │                  │ │ 1. Parse schema                │   │
 │                  │                  │ │ 2. Assign namespace "mcp:db"   │   │
 │                  │                  │ │ 3. Compute risk level          │   │
 │                  │                  │ │ 4. Register in ToolRegistry    │   │
 │                  │                  │ └────────────────────────────────┘   │
 │                  │                  │                   │                  │
 │                  │◄──DiscoveryResult│                   │                  │
 │                  │   {2 tools found}│                   │                  │
 │◄──200 OK─────────│                  │                   │                  │
 │  {tools: [...]}  │                  │                   │                  │
```

### 3.2 Tool Invocation Flow (Happy Path)

```
Executor        Guardrails      Tool Manager      Invocation Hdlr     MCP Client    MCP Server
 │                 │                │                  │                  │              │
 │ LLM returned:   │                │                  │                  │              │
 │ tool_call:      │                │                  │                  │              │
 │ {name:"query",  │                │                  │                  │              │
 │  args:{sql:..}} │                │                  │                  │              │
 │                 │                │                  │                  │              │
 │──check()───────→│                │                  │                  │              │
 │                 │──permission OK │                  │                  │              │
 │◄──ALLOW─────────│                │                  │                  │              │
 │                 │                │                  │                  │              │
 │──invoke()──────────────────────→│                  │                  │              │
 │                 │                │                  │                  │              │
 │                 │                │──resolve tool     │                  │              │
 │                 │                │  from registry    │                  │              │
 │                 │                │                  │                  │              │
 │                 │                │──invoke()────────→│                  │              │
 │                 │                │                  │                  │              │
 │                 │                │                  │──validate input   │              │
 │                 │                │                  │  vs schema        │              │
 │                 │                │                  │                  │              │
 │                 │                │                  │──check circuit    │              │
 │                 │                │                  │  breaker: CLOSED  │              │
 │                 │                │                  │                  │              │
 │                 │                │                  │──start OTel span  │              │
 │                 │                │                  │                  │              │
 │                 │                │                  │──call_tool()─────→│              │
 │                 │                │                  │                  │──tools/call──→│
 │                 │                │                  │                  │  {name:"query"│
 │                 │                │                  │                  │   arguments:  │
 │                 │                │                  │                  │   {sql:"..."}}│
 │                 │                │                  │                  │              │
 │                 │                │                  │                  │◄──result─────│
 │                 │                │                  │                  │  {content:[  │
 │                 │                │                  │                  │   {type:"text"│
 │                 │                │                  │                  │    text:"..."}│
 │                 │                │                  │◄──raw_result──────│   ]}         │
 │                 │                │                  │                  │              │
 │                 │                │                  │──record_success() │              │
 │                 │                │                  │  (circuit breaker)│              │
 │                 │                │                  │                  │              │
 │                 │                │                  │──end OTel span    │              │
 │                 │                │                  │  {latency: 45ms}  │              │
 │                 │                │                  │                  │              │
 │                 │                │◄──process result──│                  │              │
 │                 │                │   (normalize,     │                  │              │
 │                 │                │    truncate,      │                  │              │
 │                 │                │    calc cost)     │                  │              │
 │                 │                │                  │                  │              │
 │◄──ToolResult────────────────────│                  │                  │              │
 │   {content,     │                │                  │                  │              │
 │    latency:48ms,│                │                  │                  │              │
 │    is_error:    │                │                  │                  │              │
 │    false}       │                │                  │                  │              │
```

### 3.3 Tool Invocation — Error & Recovery Flows

```
Executor        Invocation Hdlr     Circuit Breaker     MCP Client     MCP Server
 │                  │                    │                  │              │
 │──invoke()───────→│                    │                  │              │
 │                  │──allow_request()──→│                  │              │
 │                  │◄──ALLOWED──────────│                  │              │
 │                  │                    │                  │              │
 │                  │──call_tool()───────────────────────→│──────────────→│
 │                  │                                      │              │
 │                  │                    ❌ TIMEOUT (30s)   │              │
 │                  │                                      │              │
 │                  │──record_failure()─→│                  │              │
 │                  │                    │ failures: 1/5    │              │
 │                  │                    │                  │              │
 │                  │  [tool is idempotent → RETRY]         │              │
 │                  │                    │                  │              │
 │                  │──call_tool() ──────────────────────→│──────────────→│
 │                  │◄──result───────────────────────────│◄──────────────│
 │                  │                    │                  │              │
 │                  │──record_success()─→│                  │              │
 │                  │                    │ failures: 0      │              │
 │◄──ToolResult─────│                    │                  │              │
 │                  │                    │                  │              │
 │                  │                    │                  │              │
 │══ LATER: Server keeps failing ════════════════════════════════════════│
 │                  │                    │                  │              │
 │──invoke()───────→│                    │                  │              │
 │                  │──allow_request()──→│                  │              │
 │                  │◄──DENIED───────────│                  │              │
 │                  │  (circuit OPEN,    │                  │              │
 │                  │   5 failures in    │                  │              │
 │                  │   60s window)      │                  │              │
 │                  │                    │                  │              │
 │◄──ToolResult─────│                    │                  │              │
 │  {is_error: true │                    │                  │              │
 │   content:       │                    │                  │              │
 │   "Tool server   │                    │                  │              │
 │    temporarily   │                    │                  │              │
 │    unavailable"} │                    │                  │              │
 │                  │                    │                  │              │
 │ [Executor feeds  │                    │                  │              │
 │  error back to   │   ══ 30s cooldown ══                 │              │
 │  LLM → LLM      │                    │                  │              │
 │  decides next    │                    │                  │              │
 │  action]         │  ══ HALF_OPEN ══   │                  │              │
 │                  │                    │                  │              │
 │──invoke()───────→│──allow_request()──→│ allow 1 test     │              │
 │                  │◄──ALLOWED──────────│                  │              │
 │                  │──call_tool()───────────────────────→│──────────────→│
 │                  │◄──result (OK)─────────────────────│◄──────────────│
 │                  │──record_success()─→│ → CLOSED        │              │
 │◄──ToolResult─────│  (circuit recovered)                 │              │
```

### 3.4 stdio MCP Server Lifecycle (Start → Crash → Auto-Restart)

```
Platform Boot      Transport Mgr        OS Process          Health Monitor
 │                     │                    │                     │
 │──start_servers()───→│                    │                     │
 │                     │                    │                     │
 │                     │──spawn("npx",      │                     │
 │                     │  ["-y",            │                     │
 │                     │   "@mcp/server-    │                     │
 │                     │    postgres"])      │                     │
 │                     │───────────────────→│                     │
 │                     │                    │ [process running,   │
 │                     │                    │  PID: 12345]        │
 │                     │◄──stdio pipes──────│                     │
 │                     │                    │                     │
 │                     │──MCP initialize()──→│                    │
 │                     │◄──OK───────────────│                     │
 │                     │                    │                     │
 │                     │──register in pool   │                     │
 │                     │                    │                     │
 │                     │──start monitoring──────────────────────→│
 │                     │                    │                     │──ping every 60s──→
 │                     │                    │                     │◄──pong
 │                     │                    │                     │
 │                     │                    │                     │
 │                     │                    │ ❌ CRASH             │
 │                     │                    │ (exit code 1)       │
 │                     │                    │                     │
 │                     │◄──SIGCHLD──────────│                     │
 │                     │                    │                     │
 │                     │──detect crash       │                     │
 │                     │  restarts: 1/5     │                     │
 │                     │                    │                     │
 │                     │──spawn (restart)───→│                    │
 │                     │                    │ [new PID: 12350]    │
 │                     │◄──stdio pipes──────│                     │
 │                     │                    │                     │
 │                     │──MCP initialize()──→│                    │
 │                     │◄──OK───────────────│                     │
 │                     │                    │                     │
 │                     │──re-register,       │                     │
 │                     │  re-discover tools  │                     │
 │                     │                    │                     │
 │                     │──notify health ────────────────────────→│
 │                     │  monitor (recovered)│                     │
```

### 3.5 Tool Schema → LLM Call → Tool Result (End-to-End)

```
Context Assembler    Schema Converter    LLM Gateway        Executor       Tool Manager
 │                      │                   │                  │                │
 │──get_tool_schemas()─→│                   │                  │                │
 │  (provider:anthropic)│                   │                  │                │
 │                      │                   │                  │                │
 │                      │──load tools from registry            │                │
 │                      │  [query, list_tables, create_issue]  │                │
 │                      │                   │                  │                │
 │                      │──convert each to  │                  │                │
 │                      │  Anthropic format: │                  │                │
 │                      │  [{name:"query",  │                  │                │
 │                      │    description:...,│                 │                │
 │                      │    input_schema:   │                  │                │
 │                      │    {type:"object", │                  │                │
 │                      │     properties:{   │                  │                │
 │                      │      sql:{type:    │                  │                │
 │                      │       "string"}    │                  │                │
 │                      │     }}}]           │                  │                │
 │                      │                   │                  │                │
 │◄──tool_schemas───────│                   │                  │                │
 │                      │                   │                  │                │
 │──build messages[]    │                   │                  │                │
 │  + tool_schemas      │                   │                  │                │
 │  → ContextPayload    │                   │                  │                │
 │                      │                   │                  │                │
 │────────────────────context──────────────→│                  │                │
 │                      │                   │──chat(messages,  │                │
 │                      │                   │   tools=schemas) │                │
 │                      │                   │──→ Anthropic API │                │
 │                      │                   │                  │                │
 │                      │                   │◄── response:     │                │
 │                      │                   │  tool_use:       │                │
 │                      │                   │  {id:"toolu_01", │                │
 │                      │                   │   name:"query",  │                │
 │                      │                   │   input:{sql:    │                │
 │                      │                   │    "SELECT..."}} │                │
 │                      │                   │                  │                │
 │                      │  from_llm_tool_call()                │                │
 │                      │◄─── parse Anthropic format──────────│                │
 │                      │──→ ToolCall(name, args, call_id)    │                │
 │                      │                   │                  │                │
 │                      │                   │                  │──invoke()─────→│
 │                      │                   │                  │◄──ToolResult───│
 │                      │                   │                  │                │
 │                      │                   │                  │ Format result  │
 │                      │                   │                  │ as Anthropic   │
 │                      │                   │                  │ tool_result msg│
 │                      │                   │                  │                │
 │                      │                   │◄──messages (incl.│                │
 │                      │                   │   tool_result)   │                │
 │                      │                   │                  │                │
 │                      │                   │──next LLM call   │                │
 │                      │                   │  (with result)   │                │
```

---

## 4. MCP Protocol Details

### 4.1 Protocol Version & Capabilities

Platform hỗ trợ MCP protocol version **2024-11-05** (stable) và sẵn sàng cho **2025-03-26** (latest).

**Capabilities negotiated during `initialize`:**

| Capability | Platform hỗ trợ (as client) | Mô tả |
|------------|----------------------------|--------|
| `tools` | Yes | Call tools on server |
| `resources` | Yes | Read resources (files, data) |
| `prompts` | Yes (Phase 2) | Use server-provided prompt templates |
| `logging` | Yes | Receive log messages from server |
| `roots` | No | File system roots (not applicable for platform) |
| `sampling` | No (Phase 3) | Server requesting LLM completions via client |

### 4.2 MCP Message Flow

```
Platform (Client)                    MCP Server
     │                                    │
     │────── initialize ────────────────→│  (request)
     │◄───── initialize result ──────────│  (response)
     │────── initialized ───────────────→│  (notification)
     │                                    │
     │────── tools/list ────────────────→│  (request)
     │◄───── tools list ────────────────│  (response)
     │                                    │
     │────── tools/call ────────────────→│  (request)
     │◄───── tool result ───────────────│  (response)
     │                                    │
     │◄───── notifications/tools/list_  ──│  (notification: tools changed)
     │       changed                      │
     │────── tools/list ────────────────→│  (re-discover)
     │◄───── updated tools list ─────────│
     │                                    │
     │────── resources/list ────────────→│  (request)
     │◄───── resources list ─────────────│  (response)
     │                                    │
     │────── resources/read ────────────→│  (request)
     │◄───── resource contents ──────────│  (response)
```

### 4.3 Handling `notifications/tools/list_changed`

Khi MCP server thông báo tool list thay đổi:

```python
async def _on_tools_changed(self, server_id: str) -> None:
    """
    Server notified that its tool list has changed.
    1. Re-enumerate tools via tools/list
    2. Diff with current registry
    3. Register new tools
    4. Mark removed tools as unavailable
    5. Update changed schemas
    6. Log changes for audit
    """
```

---

## 5. Agent Tool Configuration

### 5.1 Agent Definition — Tool Section

```json
{
  "agent_id": "customer-support-v2",
  "tools": {
    "mcp_servers": [
      {
        "server_id": "crm-server",
        "allowed_tools": ["read_customer", "update_customer", "search_customers"],
        "blocked_tools": ["delete_customer"]
      },
      {
        "server_id": "email-server",
        "allowed_tools": ["send_email"],
        "overrides": {
          "send_email": {
            "requires_approval": true,
            "max_calls_per_session": 3,
            "timeout_ms": 10000
          }
        }
      }
    ],
    "builtin_tools": ["memory_store", "memory_search"],
    "max_tools_in_prompt": 20
  }
}
```

### 5.2 Tool Selection for Prompt

Khi agent có nhiều tools (>20), không nên đưa tất cả vào prompt (ảnh hưởng LLM performance). Platform hỗ trợ **tool selection**:

```python
class ToolSelector:
    async def select_for_prompt(
        self,
        all_tools: list[ToolInfo],
        context: ContextPayload,
        max_tools: int = 20,
    ) -> list[ToolInfo]:
        """
        Strategy:
        Phase 1 (simple): Return all tools if <= max_tools, else return
                          most recently used + always-include list.

        Phase 2 (smart):  Embed tool descriptions + current user message,
                          return top-K most relevant tools by cosine similarity.
        """
```

---

## 6. Security Considerations

### 6.1 MCP Server Trust Levels

| Trust Level | Description | Examples | Controls |
|-------------|------------|----------|----------|
| **Platform-managed** | Servers run by platform operator | Built-in DB, filesystem servers | Full trust, direct access |
| **Tenant-provided (verified)** | Server provided by tenant, reviewed | Enterprise custom servers | Schema validation, sandbox |
| **Tenant-provided (unverified)** | Server provided by tenant, not reviewed | Third-party MCP servers | Strict sandbox, limited resources |
| **Community** | Open-source / marketplace servers | npm MCP packages | Maximum isolation, approval required |

### 6.2 Secret Management

MCP servers often need credentials (DB passwords, API keys). Platform handles this securely:

```python
@dataclass
class MCPServerSecrets:
    server_id: str
    tenant_id: str
    env_vars: dict[str, str]        # Encrypted at rest
    auth_headers: dict[str, str]    # Encrypted at rest

# Storage: encrypted in PostgreSQL using tenant-specific encryption key
# Never logged, never included in traces
# Injected into server process env at spawn time only
# Rotatable via API without server restart
```

### 6.3 Network Isolation

```
┌─── Platform Network ──────────────────────────────┐
│                                                     │
│  Executor ──→ MCP Client ──→ MCP Server (stdio)   │ ← Same host, no network
│                                                     │
│  Executor ──→ MCP Client ──→ ┌──────────────┐     │
│                               │ Network Policy│     │
│                               │ (allowlist)   │     │ ← HTTP servers: TLS required,
│                               └──────┬───────┘     │   host allowlist enforced
│                                      │              │
└──────────────────────────────────────┼──────────────┘
                                       │
                              External MCP Servers
```

---

## 7. Tech Stack

| Component | Technology | Phase | Lý do |
|-----------|-----------|-------|-------|
| **MCP Client SDK** | `mcp` (official Python SDK) | 1 | Standard implementation, maintained by Anthropic |
| **Transport: stdio** | `asyncio.subprocess` | 1 | Built-in Python, async process management |
| **Transport: HTTP/SSE** | `httpx` + `httpx-sse` | 1 | Async HTTP client, SSE support |
| **Schema validation** | `jsonschema` / Pydantic | 1 | Validate tool inputs against JSONSchema |
| **Schema conversion** | Custom Python module | 1 | MCP → OpenAI/Anthropic/Google format |
| **Connection pool** | Custom (dict + asyncio.Lock) | 1 | Lightweight, sufficient for Phase 1 |
| **Circuit breaker** | Custom (Redis-backed state) | 1 | Distributed state across executors |
| **Health monitoring** | `asyncio` background tasks | 1 | Lightweight periodic checks |
| **Tool registry DB** | PostgreSQL | 1 | Queryable, tenant-isolated |
| **Secret encryption** | `cryptography` (Fernet) | 1 | Tenant-scoped encryption keys |
| **Process sandbox** | `seccomp` + `AppArmor` profiles | 2 | Linux kernel-level isolation |
| **Container sandbox** | `gVisor` (runsc) via Docker | 2 | Strong isolation for untrusted code |
| **Tool embedding** | pgvector (reuse Memory infra) | 2 | Semantic tool search |

---

## 8. Performance Targets

| Operation | Target Latency | Notes |
|-----------|---------------|-------|
| Tool resolution from registry | < 2ms | PostgreSQL indexed lookup |
| Schema conversion (1 tool) | < 0.1ms | In-memory transformation |
| Schema conversion (20 tools) | < 1ms | Batched |
| MCP initialize handshake | < 2s | One-time per server connection |
| Tool discovery (tools/list) | < 1s | Depends on server, cached after |
| Tool invocation overhead (platform) | < 10ms | Excluding actual tool execution |
| Tool invocation (typical API tool) | 50-500ms | Depends on external service |
| Tool invocation (DB query) | 10-200ms | Depends on query complexity |
| Circuit breaker check | < 1ms | Redis GET |
| Health check (ping) | < 5ms | Simple round-trip |
| Input schema validation | < 2ms | jsonschema validate |
| Result processing + truncation | < 5ms | String operations |
| **Total platform overhead per tool call** | **< 20ms** | All platform logic, excl. server |

---

## 9. Error Handling

| Error | Source | Platform Response |
|-------|--------|-------------------|
| MCP server not connected | Connection pool | Connect on-demand; if fails → return error to LLM |
| MCP server crash (stdio) | Process monitor | Auto-restart (up to max_restarts); update tool status |
| MCP initialize fails | Handshake | Retry 3x with backoff; log error; mark server as error |
| Tool not found | Registry | Return clear error to LLM: "Tool X not available" |
| Input validation fails | Schema validator | Return validation error to LLM (not a platform error) |
| Tool execution timeout | Invocation handler | Return timeout error to LLM; record in circuit breaker |
| Tool returns isError=true | MCP server | Pass error content to LLM as tool result (LLM decides next) |
| Tool result too large | Result processor | Truncate + store full in artifacts; return truncated + ref |
| Circuit breaker open | Circuit breaker | Return "server unavailable" to LLM; don't call server |
| Auth token expired (HTTP) | Transport | Refresh token if possible; else reconnect with new token |
| `tools/list_changed` notification | MCP server | Auto re-discover; update registry; no executor impact |
| Network error to HTTP server | Transport | Retry with backoff; if persistent → circuit breaker |
