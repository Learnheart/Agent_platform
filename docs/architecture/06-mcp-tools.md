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

**ToolManager** là service layer cho tất cả các thao tác liên quan đến tool. Đây là entry point cho executor và API layer.

**Constructor** nhận 4 dependency: ToolRegistry, ToolDiscoveryService, SchemaConverter, ToolRuntime.

**Các method:**

| Method | Parameters | Return Type | Mô tả |
|--------|-----------|-------------|--------|
| `list_tools` | tenant_id: str, agent_id: str \| None = None | list[ToolInfo] | Liệt kê tools available cho một tenant/agent, kết hợp static + discovered |
| `get_tool` | tenant_id: str, tool_id: str | ToolInfo | Lấy full tool details bao gồm schema |
| `discover_from_server` | tenant_id: str, server_config: MCPServerConfig | list[ToolInfo] | Kết nối đến MCP server, enumerate tools, đăng ký chúng |
| `refresh_tools` | tenant_id: str, server_id: str | list[ToolInfo] | Re-discover tools từ server hiện có (schema có thể đã thay đổi) |
| `invoke` | tenant_id: str, session_id: str, tool_call: ToolCall | ToolResult | Full invocation pipeline (xem chi tiết bên dưới) |
| `get_tool_schemas_for_llm` | tenant_id: str, agent_id: str, llm_provider: str | list[dict] | Lấy tool schemas đã format cho LLM provider cụ thể (MCP → OpenAI/Anthropic/Google) |

**Chi tiết invoke pipeline:**
1. Resolve tool từ registry
2. Permission check được Guardrails thực hiện trước khi gọi method này
3. Route đến đúng MCP server qua runtime
4. Xử lý timeout, retry, circuit breaker
5. Process và normalize result
6. Track cost và emit trace event

---

#### 2.1.1 Tool Registry

Lưu trữ metadata của tất cả tools available trong platform, phân vùng theo tenant.

**Data model ToolInfo:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | Định danh tool, ví dụ "mcp:github:create_issue" |
| name | str | — | Tên tool, ví dụ "create_issue" |
| server_id | str | — | ID của MCP server mà tool này thuộc về |
| namespace | str | — | Namespace phân vùng, ví dụ "mcp:github" |
| description | str | — | Mô tả tool, ví dụ "Create a new issue in a GitHub repository" |
| input_schema | dict | — | JSONSchema cho input parameters |
| output_schema | dict \| None | — | JSONSchema cho output (optional) |
| execution_mode | Literal["sync", "async"] | — | "sync" = chờ kết quả, "async" = fire-and-forget |
| default_timeout_ms | int | — | Timeout riêng cho tool |
| estimated_latency_ms | int \| None | — | Trung bình latency từ dữ liệu lịch sử |
| estimated_cost | float \| None | — | Chi phí ước tính mỗi lần gọi (USD), nếu có |
| idempotent | bool | — | Có an toàn để retry không? |
| permission_scope | list[str] | — | Ví dụ ["github:write", "issues:create"] |
| risk_level | Literal["low", "medium", "high", "critical"] | — | Mức rủi ro |
| requires_approval | bool | — | Cài đặt HITL mặc định |
| tenant_id | str | — | Tenant sở hữu |
| visibility | Literal["platform", "tenant", "agent"] | — | Phạm vi hiển thị |
| discovered_at | datetime | — | Thời điểm phát hiện |
| last_verified_at | datetime | — | Lần xác minh cuối |
| status | Literal["active", "degraded", "unavailable"] | — | Trạng thái hiện tại |

**Storage — Bảng `tools`:**

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| id | TEXT NOT NULL | — | Tool ID |
| tenant_id | TEXT NOT NULL | — | Tenant ID |
| server_id | TEXT NOT NULL | — | MCP server ID |
| name | TEXT NOT NULL | — | Tên tool |
| namespace | TEXT NOT NULL | — | Namespace |
| description | TEXT NOT NULL | — | Mô tả |
| input_schema | JSONB NOT NULL | — | JSONSchema cho input |
| output_schema | JSONB | — | JSONSchema cho output (nullable) |
| execution_mode | TEXT | 'sync' | Chế độ thực thi |
| default_timeout_ms | INT | 30000 | Timeout mặc định |
| estimated_latency_ms | INT | — | Latency ước tính |
| estimated_cost | FLOAT | — | Chi phí ước tính |
| idempotent | BOOLEAN | FALSE | Có idempotent không |
| permission_scope | TEXT[] | '{}' | Danh sách permission scope |
| risk_level | TEXT | 'low' | Mức rủi ro |
| requires_approval | BOOLEAN | FALSE | Cần phê duyệt không |
| visibility | TEXT | 'tenant' | Phạm vi hiển thị |
| discovered_at | TIMESTAMPTZ | NOW() | Thời điểm phát hiện |
| last_verified_at | TIMESTAMPTZ | NOW() | Lần xác minh cuối |
| status | TEXT | 'active' | Trạng thái |

- **Primary Key:** (tenant_id, id)
- **Foreign Key:** (tenant_id, server_id) tham chiếu đến mcp_servers(tenant_id, id) ON DELETE CASCADE
- **Row-Level Security:** Bật RLS với policy tenant_isolation, lọc theo current_setting('app.current_tenant')
- **Index:** idx_tools_namespace trên (tenant_id, namespace) cho fast lookup by namespace

**ToolRegistry — Các method:**

| Method | Parameters | Return Type | Mô tả |
|--------|-----------|-------------|--------|
| `register` | tool: ToolInfo | None | Đăng ký hoặc cập nhật tool trong registry |
| `unregister` | tenant_id: str, tool_id: str | None | Xoá tool khỏi registry |
| `list_by_agent` | tenant_id: str, agent_id: str | list[ToolInfo] | Lấy tools cho agent cụ thể: (1) load agent definition lấy allowlist tool patterns, (2) match với registry bằng glob patterns, (3) trả về matched tools có status = 'active' |
| `search` | tenant_id: str, query: str, top_k: int = 10 | list[ToolInfo] | Semantic search trên tool descriptions (Phase 2, capability-based discovery) |
| `update_status` | tenant_id: str, tool_id: str, status: str | None | Đánh dấu tool là active/degraded/unavailable dựa trên health checks |

---

#### 2.1.2 Tool Discovery Service

Kết nối đến MCP server, liệt kê tools, và đồng bộ vào registry.

**ToolDiscoveryService — Các method:**

| Method | Parameters | Return Type | Mô tả |
|--------|-----------|-------------|--------|
| `discover` | tenant_id: str, server_config: MCPServerConfig | DiscoveryResult | Kết nối MCP server, gọi tools/list, parse schema, assign namespace, compute risk level, đăng ký vào ToolRegistry. Cũng discover Resources (via resources/list, đăng ký như read-only tools) và Prompts (via prompts/list, đăng ký như prompt templates) |
| `refresh` | tenant_id: str, server_id: str | DiscoveryResult | Re-run discovery cho server hiện có. Detect: new tools, removed tools, schema changes. Cập nhật registry tương ứng |
| `verify_tool` | tenant_id: str, tool_id: str | VerificationResult | Xác minh tool cụ thể vẫn available và schema khớp registry. Được health monitor gọi định kỳ |

---

#### 2.1.3 Schema Converter

Chuyển đổi MCP tool schema sang format mà từng LLM provider yêu cầu.

**SchemaConverter** chuyển đổi MCP tool schema (JSONSchema-based) sang format riêng của từng LLM provider. Mỗi provider có format tool/function calling hơi khác nhau.

**Các method chính:**

| Method | Parameters | Return Type | Mô tả |
|--------|-----------|-------------|--------|
| `to_anthropic` | tool: ToolInfo | dict | Chuyển MCP tool sang Anthropic tool_use format |
| `to_openai` | tool: ToolInfo | dict | Chuyển MCP tool sang OpenAI function calling format (Phase 2) |
| `to_google` | tool: ToolInfo | dict | Chuyển MCP tool sang Gemini function declaration format (Phase 2) |
| `convert` | tool: ToolInfo, provider: str | dict | Dispatch sang converter phù hợp dựa trên LLM provider. Raise ValueError nếu provider không hỗ trợ |
| `convert_batch` | tools: list[ToolInfo], provider: str | list[dict] | Chuyển đổi nhiều tools cùng lúc cho một lần gọi LLM |
| `from_llm_tool_call` | raw_call: dict, provider: str | ToolCall | Parse LLM tool_call response ngược lại thành ToolCall model chuẩn hoá |
| `_sanitize_name` | name: str, namespace: str | str | Tạo tên tool cho LLM, phải unique và là valid identifier |
| `_build_description` | tool: ToolInfo | str | Tạo description string cho LLM, bao gồm namespace context |

**Quy tắc chuyển đổi cho từng provider:**

- **Anthropic (to_anthropic):** MCP tool.inputSchema đã là JSONSchema — Anthropic chấp nhận trực tiếp. Đảm bảo có type="object" và properties={}. Output structure: name (sanitized), description (có prefix namespace), input_schema (JSONSchema).

- **OpenAI (to_openai):** Bọc trong structure: type="function", bên trong có function object chứa name (sanitized), description, và parameters (JSONSchema).

- **Google (to_google):** Structure tương tự OpenAI: name (sanitized), description, parameters (JSONSchema).

**Quy tắc parse ngược (from_llm_tool_call):**

- **Anthropic:** Content block type="tool_use" — đã được LLM Gateway parse sẵn. Lấy id, name, và input (arguments) trực tiếp.
- **OpenAI:** Format {"id", "function": {"name", "arguments": JSON string}} — cần json.loads cho arguments vì OpenAI trả về dạng JSON string.

**Quy tắc sanitize name (_sanitize_name):** Dùng namespace prefix để tránh collision. Trích xuất short namespace (ví dụ "mcp:github" thành "github"), ghép thành "github__create_issue". Thay ký tự không hợp lệ bằng underscore. Anthropic cho phép [a-zA-Z0-9_-], tối đa 64 ký tự. Cắt xuống 64 ký tự nếu vượt quá.

**Quy tắc build description (_build_description):** Thêm prefix namespace trong ngoặc vuông trước description, ví dụ "[mcp:github] Create a new issue in a GitHub repository", để LLM hiểu tool thuộc service nào.

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

**MCPClientManager** quản lý connections đến tất cả MCP servers cho một platform instance. Mỗi MCP server có đúng một managed connection (pooled per tenant nếu cần).

**Constructor** nhận 3 dependency: TransportManager, HealthMonitor, ConnectionPool.

**Các method:**

| Method | Parameters | Return Type | Mô tả |
|--------|-----------|-------------|--------|
| `get_client` | tenant_id: str, server_id: str | MCPClient | Lấy hoặc tạo MCP client connection. Kiểm tra pool → nếu tồn tại và healthy thì trả về → nếu không tồn tại thì tạo mới qua transport manager → nếu unhealthy thì đóng và reconnect |
| `connect_server` | server_config: MCPServerConfig | MCPClient | Thiết lập kết nối mới: (1) tạo transport, (2) tạo MCP client, (3) initialize handshake, (4) negotiate capabilities, (5) thêm vào connection pool, (6) cập nhật server status và last_connected_at, (7) bắt đầu health monitoring |
| `disconnect_server` | tenant_id: str, server_id: str | None | Đóng kết nối gracefully và xoá khỏi pool. Unregister khỏi health monitor trước |
| `disconnect_all` | tenant_id: str | None | Ngắt kết nối tất cả servers của một tenant (cleanup khi tenant bị deactivate) |
| `close_all` | — | None | Shutdown: ngắt mọi server trên tất cả tenants |

**Chi tiết connect_server:** Khi initialize handshake, gửi client_info (name: "agent-platform", version: "1.0") và capabilities (tools: True, resources: True). Sau khi nhận server capabilities, gửi notification initialized() để hoàn tất handshake.

#### 2.2.2 Transport Manager

Xử lý các transport protocol mà MCP hỗ trợ.

**TransportManager** tạo transport phù hợp cho mỗi MCP server connection. MCP hỗ trợ nhiều cơ chế transport.

**Các method:**

| Method | Parameters | Return Type | Mô tả |
|--------|-----------|-------------|--------|
| `create_transport` | config: MCPServerConfig | MCPTransport | Dispatch tạo transport dựa trên config.transport: "stdio", "sse", hoặc "streamable_http" |
| `_create_stdio_transport` | config: MCPServerConfig | StdioTransport | Khởi chạy MCP server dạng subprocess, giao tiếp qua stdin/stdout |
| `_create_sse_transport` | config: MCPServerConfig | SSETransport | Kết nối đến remote MCP server qua HTTP + Server-Sent Events |
| `_create_streamable_http_transport` | config: MCPServerConfig | StreamableHTTPTransport | MCP transport mới hơn: single HTTP endpoint, bidirectional streaming. Ưu tiên cho remote servers (đơn giản hơn SSE) |

**Chi tiết stdio transport lifecycle:**
1. Spawn process: config.command + config.args + config.env
2. Wrap stdin/stdout thành JSON-RPC transport
3. Monitor process health (exit code, stderr)
4. Auto-restart khi crash (configurable max restarts)

**Security cho stdio:** Process chạy dưới restricted user (không phải root). Resource limits: max memory, max CPU, max open files. Filesystem access giới hạn theo config.allowed_paths.

**Chi tiết SSE transport lifecycle:**
1. HTTP POST đến config.url cho requests
2. SSE stream từ config.url/events cho responses
3. Auth qua config.headers (Bearer token, API key)
4. Reconnect khi disconnect với exponential backoff

**Security cho SSE:** Bắt buộc TLS (reject plain HTTP). Hỗ trợ auth token rotation. Response size limits.

**MCP Server Configuration Model — MCPServerConfig:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | Server ID |
| tenant_id | str | — | Tenant ID |
| name | str | — | Tên hiển thị (human-readable) |
| description | str | — | Mô tả server |
| transport | Literal["stdio", "sse", "streamable_http"] | — | Loại transport |
| command | str \| None | — | Lệnh stdio, ví dụ "npx", "python", "docker" |
| args | list[str] \| None | — | Arguments, ví dụ ["-y", "@modelcontextprotocol/server-postgres"] |
| env | dict[str, str] \| None | — | Biến môi trường (có thể chứa secrets) |
| cwd | str \| None | — | Working directory |
| url | str \| None | — | URL cho HTTP transport, ví dụ "https://mcp.example.com/v1" |
| headers | dict[str, str] \| None | — | Auth headers |
| connect_timeout_ms | int | 10000 | Timeout kết nối |
| request_timeout_ms | int | 30000 | Timeout request |
| max_retries | int | 3 | Số lần retry tối đa |
| retry_backoff_ms | int | 1000 | Backoff giữa các retry |
| auto_start | bool | True | Khởi động cùng platform? |
| max_restarts | int | 5 | Số lần auto-restart tối đa (cho stdio) |
| health_check_interval_seconds | int | 60 | Tần suất health check |
| allowed_tools | list[str] \| None | — | Whitelist tools (None = tất cả) |
| blocked_tools | list[str] \| None | — | Blacklist tools |
| sandbox_level | Literal["none", "process", "container"] | "none" | Mức sandbox |
| status | Literal["connected", "connecting", "disconnected", "error"] | "disconnected" | Trạng thái hiện tại |
| last_connected_at | datetime \| None | None | Lần kết nối cuối |
| last_error | str \| None | None | Lỗi cuối cùng |

**Storage — Bảng `mcp_servers`:**

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| id | TEXT NOT NULL | — | Server ID |
| tenant_id | TEXT NOT NULL | — | Tenant ID |
| name | TEXT NOT NULL | — | Tên server |
| description | TEXT | — | Mô tả |
| transport | TEXT NOT NULL | — | Loại transport |
| command | TEXT | — | Lệnh stdio |
| args | JSONB | — | Arguments |
| env_encrypted | BYTEA | — | Biến môi trường (encrypted) |
| url | TEXT | — | URL cho HTTP transport |
| headers_encrypted | BYTEA | — | Auth headers (encrypted) |
| connect_timeout_ms | INT | 10000 | Timeout kết nối |
| request_timeout_ms | INT | 30000 | Timeout request |
| max_retries | INT | 3 | Số lần retry |
| auto_start | BOOLEAN | TRUE | Tự khởi động |
| health_check_interval_seconds | INT | 60 | Tần suất health check |
| allowed_tools | TEXT[] | — | Whitelist tools |
| blocked_tools | TEXT[] | — | Blacklist tools |
| sandbox_level | TEXT | 'none' | Mức sandbox |
| status | TEXT | 'disconnected' | Trạng thái |
| last_connected_at | TIMESTAMPTZ | — | Lần kết nối cuối |
| last_error | TEXT | — | Lỗi cuối |
| created_at | TIMESTAMPTZ | NOW() | Thời điểm tạo |
| updated_at | TIMESTAMPTZ | NOW() | Thời điểm cập nhật |

- **Primary Key:** (tenant_id, id)
- **Row-Level Security:** Bật RLS với policy tenant_isolation, lọc theo current_setting('app.current_tenant')

#### 2.2.3 Connection Pool

**ConnectionPool** quản lý các active MCP client connections. Key là cặp (tenant_id, server_id), value là MCPClient.

**Behaviors:**
- Lazy connection: chỉ kết nối khi sử dụng lần đầu
- Max connections per tenant: configurable (mặc định 20)
- Idle timeout: đóng connection không dùng quá 10 phút
- Graceful shutdown: đóng tất cả khi platform dừng

**Các method:**

| Method | Parameters | Return Type | Mô tả |
|--------|-----------|-------------|--------|
| `get` | tenant_id: str, server_id: str | MCPClient \| None | Lấy client từ pool |
| `put` | tenant_id: str, server_id: str, client: MCPClient | None | Thêm client vào pool |
| `remove` | tenant_id: str, server_id: str | None | Xoá client khỏi pool |
| `get_stats` | — | PoolStats | Thống kê active, idle, total theo tenant |

#### 2.2.4 Health Monitor

**HealthMonitor** giám sát sức khoẻ MCP server và quản lý auto-recovery. Chạy dạng background task.

**Các method:**

| Method | Parameters | Return Type | Mô tả |
|--------|-----------|-------------|--------|
| `start` | — | None | Bắt đầu monitoring loop |
| `check_server` | tenant_id: str, server_id: str | HealthStatus | Health check cho một server: (1) gửi MCP ping hoặc tools/list, (2) đo response latency, (3) so sánh với baseline lịch sử |
| `_on_unhealthy` | tenant_id: str, server_id: str, status: HealthStatus | None | Recovery actions khi server unhealthy |

**HealthStatus** bao gồm: status ("healthy" / "degraded" / "unhealthy"), latency_ms (float), last_check (datetime), consecutive_failures (int).

**Recovery actions (_on_unhealthy):**
- stdio server: kill và restart process
- HTTP server: reconnect với backoff
- Sau max_restarts: đánh dấu unavailable, gửi alert
- Cập nhật tool status trong registry → executor sẽ không gọi tools unavailable

#### 2.2.5 Invocation Handler

Core logic cho việc gọi tool qua MCP.

**InvocationHandler** xử lý việc gọi tool thực tế trên MCP server. Bao gồm timeout, retry, circuit breaker, và cost tracking.

**Constructor** nhận 3 dependency: CircuitBreaker, ResultProcessor, tracer (OpenTelemetry).

**Method chính — invoke:**

| Parameter | Type | Mô tả |
|-----------|------|--------|
| client | MCPClient | MCP client connection |
| tool_call | ToolCall | Tool call cần thực thi |
| tool_info | ToolInfo | Metadata của tool |
| timeout_ms | int \| None | Timeout tùy chỉnh (mặc định dùng tool_info.default_timeout_ms) |
| **Return** | ToolResult | Kết quả thực thi |

**Invoke pipeline chi tiết:**

1. **Circuit breaker check:** Nếu circuit breaker OPEN cho server_id, trả về ToolResult lỗi ngay lập tức ("Tool server temporarily unavailable").

2. **Execute with retry:** Nếu tool là idempotent và max_retries > 0, gọi qua _invoke_with_retry. Ngược lại gọi _invoke_with_timeout trực tiếp. Ghi OTel span với attributes tool.name và tool.server_id.

3. **Record success:** Gọi circuit_breaker.record_success() để reset failure count.

4. **Process result:** Gọi ResultProcessor.process() để normalize kết quả. Gán tool_call_id và latency_ms.

**Xử lý lỗi:**
- **ToolTimeoutError:** Record failure trong circuit breaker, trả về ToolResult lỗi với error_category "tool_timeout"
- **MCPConnectionError:** Record failure, trả về ToolResult lỗi với error_category "tool_connection_error"
- **Exception khác:** Record failure, trả về ToolResult lỗi với error_category "tool_execution_error"

Trong mọi trường hợp lỗi, latency_ms vẫn được tính và ghi nhận.

**_invoke_with_timeout:** Gọi MCP client.call_tool() với asyncio.timeout (timeout_ms / 1000). Raise ToolTimeoutError nếu hết thời gian.

**_invoke_with_retry — Retry logic cho idempotent tools:**
- Exponential backoff: 1s, 2s, 4s
- Max retries lấy từ tool_info.max_retries hoặc mặc định 2
- Timeout → retry
- Server error (MCP error code) → retry
- Client error (invalid params, JSON-RPC error code >= -32600) → KHÔNG retry, raise ngay
- Connection error → raise, để caller xử lý reconnect

**Circuit Breaker:**

**CircuitBreaker** ngăn cascading failures, hoạt động per-server.

**Các trạng thái:**
- **CLOSED:** Hoạt động bình thường, requests đi qua
- **OPEN:** Server đang lỗi, reject requests ngay lập tức
- **HALF_OPEN:** Cho phép 1 test request để kiểm tra recovery

**Chuyển trạng thái:**
- CLOSED → OPEN: khi failure_count >= threshold (mặc định 5) trong window (mặc định 60s)
- OPEN → HALF_OPEN: sau cooldown period (mặc định 30s)
- HALF_OPEN → CLOSED: nếu test request thành công
- HALF_OPEN → OPEN: nếu test request thất bại

**Các method:**

| Method | Parameters | Return Type | Mô tả |
|--------|-----------|-------------|--------|
| `allow_request` | server_id: str | bool | Kiểm tra có cho phép request không |
| `record_success` | server_id: str | None | Ghi nhận thành công |
| `record_failure` | server_id: str | None | Ghi nhận thất bại |
| `get_state` | server_id: str | CircuitState | Lấy trạng thái hiện tại |

#### 2.2.6 Result Processor

**ResultProcessor** chuẩn hoá và xử lý raw MCP tool results trước khi trả về executor.

**Method process** (raw_result: dict, tool_info: ToolInfo) → ToolResult, thực hiện:

1. **Extract content:** Từ MCP result format (content: [{type: "text", text: "..."}], isError: bool)
2. **Normalize:** Sang platform format ToolResult(content: str, is_error: bool, metadata: dict)
3. **Truncate nếu quá lớn:** Nếu content vượt max_result_tokens, cắt với marker "[...truncated, full result stored]". Lưu full result vào artifact store, tham chiếu trong metadata. Khi truncate, giữ 60% đầu + 40% cuối của budget, chèn truncation marker ở giữa.
4. **Redact sensitive data** nếu PII policy yêu cầu
5. **Calculate cost** nếu tool có cost model

**Data model ToolResult:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| tool_call_id | str | — | Khớp với tool_call ID của LLM |
| tool_name | str | — | Tên tool |
| content | str | — | Nội dung text đã normalize |
| is_error | bool | — | Có phải lỗi không |
| metadata | dict | — | Bao gồm latency_ms, server_id, truncated, v.v. |
| artifacts | list[str] \| None | — | Tham chiếu đến large stored artifacts |
| cost_usd | float \| None | — | Chi phí invocation (nếu tracked) |
| latency_ms | float | — | Thời gian thực thi |

#### 2.2.7 Sandbox Manager (Phase 2)

Cho các tool cần chạy code hoặc truy cập filesystem.

**SandboxManager** cung cấp môi trường thực thi isolated cho tools cần thiết. Sử dụng chủ yếu cho code execution tools và filesystem tools.

**Method execute_in_sandbox:**

| Parameter | Type | Default | Mô tả |
|-----------|------|---------|--------|
| sandbox_level | Literal["process", "container"] | — | Mức sandbox |
| command | str | — | Lệnh thực thi |
| args | list[str] | — | Arguments |
| env | dict[str, str] | — | Biến môi trường |
| timeout_seconds | int | 30 | Timeout |
| constraints | SandboxConstraints \| None | None | Ràng buộc tài nguyên |
| **Return** | SandboxResult | — | Kết quả thực thi |

**Sandbox levels:**
- **Process sandbox:** seccomp + AppArmor profile
- **Container sandbox:** ephemeral container (gVisor runtime)

**SandboxConstraints mặc định:**
- max_memory_mb: 512
- max_cpu_seconds: 30
- network_access: False
- allowed_network_hosts: [] (whitelist nếu network_access=True)
- writable_paths: ["/tmp/workspace"]
- readonly_paths: ["/data/input"]

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

Khi MCP server thông báo tool list thay đổi, platform thực hiện hàm **_on_tools_changed**(server_id: str):

1. Re-enumerate tools via tools/list
2. Diff với current registry
3. Register new tools
4. Mark removed tools as unavailable
5. Update changed schemas
6. Log changes cho audit

---

## 5. Agent Tool Configuration

### 5.1 Agent Definition — Tool Section

Mỗi agent definition chứa một section "tools" cấu hình MCP servers và tools mà agent được phép sử dụng. Cấu trúc bao gồm:

**Top-level fields:**
- **agent_id:** Định danh agent, ví dụ "customer-support-v2"
- **tools:** Object chứa cấu hình tools

**Trong "tools":**
- **mcp_servers:** Mảng các server config, mỗi item gồm:
  - **server_id:** ID server cần kết nối, ví dụ "crm-server"
  - **allowed_tools:** Danh sách tools cho phép, ví dụ ["read_customer", "update_customer", "search_customers"]
  - **blocked_tools:** Danh sách tools bị chặn, ví dụ ["delete_customer"]
  - **overrides:** (optional) Object ghi đè config cho từng tool cụ thể, mỗi key là tên tool, value chứa các override như requires_approval (bool), max_calls_per_session (int), timeout_ms (int)
- **builtin_tools:** Danh sách built-in tools, ví dụ ["memory_store", "memory_search"]
- **max_tools_in_prompt:** Số lượng tools tối đa đưa vào prompt, ví dụ 20

### 5.2 Tool Selection for Prompt

Khi agent có nhiều tools (>20), không nên đưa tất cả vào prompt (ảnh hưởng LLM performance). Platform hỗ trợ **tool selection**:

**ToolSelector** có method **select_for_prompt**(all_tools: list[ToolInfo], context: ContextPayload, max_tools: int = 20) → list[ToolInfo]:

- **Phase 1 (simple):** Trả về tất cả tools nếu <= max_tools, ngược lại trả về most recently used + always-include list.
- **Phase 2 (smart):** Embed tool descriptions + current user message, trả về top-K most relevant tools theo cosine similarity.

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

**MCPServerSecrets** data model:

| Field | Type | Description |
|-------|------|-------------|
| server_id | str | Server ID |
| tenant_id | str | Tenant ID |
| env_vars | dict[str, str] | Biến môi trường (encrypted at rest) |
| auth_headers | dict[str, str] | Auth headers (encrypted at rest) |

**Quy tắc bảo mật:**
- Storage: encrypted trong PostgreSQL sử dụng tenant-specific encryption key
- Never logged, never included in traces
- Inject vào server process env chỉ tại thời điểm spawn
- Rotatable qua API mà không cần restart server

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
