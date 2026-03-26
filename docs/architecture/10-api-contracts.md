# API Contracts

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-26
> **Mục đích:** Định nghĩa canonical cho toàn bộ REST API endpoints, request/response schemas, SSE streaming, authentication, và error handling.

---

## 1. API Conventions

### 1.1 Base URL & Versioning

```
https://{host}/api/v1/{resource}
```

- Versioning trong URL path (`/api/v1/`)
- Breaking changes → bump version (`/api/v2/`)
- Non-breaking additions (new fields, new endpoints) → giữ nguyên version

### 1.2 Response Envelope

Tất cả responses (trừ SSE stream) sử dụng envelope chuẩn:

**Success Response:**

| Field | Type | Mô tả |
|-------|------|--------|
| `data` | object | Dữ liệu trả về |
| `meta.request_id` | string | ID request, ví dụ `req_abc123` |
| `meta.trace_id` | string | OpenTelemetry trace ID |
| `meta.timestamp` | string (ISO 8601) | Thời điểm response |

**Error Response:**

| Field | Type | Mô tả |
|-------|------|--------|
| `error.code` | string | Machine-readable error code, ví dụ `AGENT_NOT_FOUND` |
| `error.message` | string | Human-readable message, ví dụ `Agent with ID 'xyz' not found` |
| `error.details` | object | Structured context bổ sung (optional) |
| `meta.request_id` | string | ID request |
| `meta.trace_id` | string | OpenTelemetry trace ID |
| `meta.timestamp` | string (ISO 8601) | Thời điểm response |

### 1.3 Pagination

List endpoints sử dụng cursor-based pagination:

```
GET /api/v1/sessions?limit=20&cursor=eyJjcmVhdGVkX2F0IjoiMjAyNi0wMy0yNiJ9
```

**Response bao gồm pagination object:**

| Field | Type | Mô tả |
|-------|------|--------|
| `data` | array | Danh sách items |
| `pagination.limit` | int | Số items trả về (ví dụ 20) |
| `pagination.has_more` | boolean | Còn data tiếp theo hay không |
| `pagination.next_cursor` | string / null | Cursor cho page tiếp theo |
| `meta` | object | Request metadata |

### 1.4 Filtering & Sorting

```
GET /api/v1/sessions?agent_id=abc&state=running&sort=-created_at
```

- Filter bằng query params
- Sort: prefix `-` = descending, không prefix = ascending
- Default sort: `-created_at` (newest first)

### 1.5 Common Headers

| Header | Mô tả | Required |
|--------|--------|----------|
| `Authorization` | `Bearer {token}` hoặc `X-API-Key {key}` | Yes |
| `X-Tenant-ID` | Tenant identifier (extracted from token nếu OAuth) | Conditional |
| `X-Request-ID` | Client-generated request ID (UUID) | No |
| `Content-Type` | `application/json` | Yes (POST/PUT/PATCH) |
| `Accept` | `application/json` hoặc `text/event-stream` | No |

### 1.6 Response Headers

| Header | Mô tả |
|--------|--------|
| `X-Request-ID` | Echo back client request ID, or server-generated |
| `X-Trace-ID` | OpenTelemetry trace ID |
| `X-RateLimit-Limit` | Requests allowed per window |
| `X-RateLimit-Remaining` | Requests remaining in current window |
| `X-RateLimit-Reset` | Unix timestamp when window resets |
| `Retry-After` | Seconds to wait (on 429 responses) |

---

## 2. Authentication

### 2.1 Builder Authentication

- **Method:** OAuth 2.0 / OIDC (Bearer token)
- **Header:** `Authorization: Bearer {access_token}`
- **Scope:** Full access to Builder API + read access to End User API
- **Tenant:** Extracted from token claims (`tenant_id`)

### 2.2 End User Authentication

- **Method:** API Key (scoped to specific agent)
- **Header:** `Authorization: X-API-Key {api_key}`
- **Scope:** End User API only — create sessions, send messages, stream
- **Tenant + Agent:** Resolved from API key mapping

### 2.3 Auth Middleware Implementation

**AuthMiddleware** (kế thừa BaseHTTPMiddleware) xác thực mọi request và gắn identity vào `request.state`.

**Execution order:**

1. Extract credentials từ `Authorization` header
2. Xác định auth method: `Bearer` (Builder) hoặc `X-API-Key` (End User)
3. Validate credentials
4. Gắn `AuthContext` vào `request.state`
5. Pass request cho middleware tiếp theo (`TenantMiddleware`)

**Skip paths:** `/health`, `/ready`, `/docs`, `/openapi.json` — các path này không yêu cầu authentication.

**Logic xử lý:**

- Nếu header bắt đầu bằng `Bearer `: xử lý như Builder JWT authentication — gọi `_validate_jwt(token)`.
- Nếu header bắt đầu bằng `X-API-Key `: xử lý như End User API key authentication — gọi `_validate_api_key(api_key)`.
- Nếu không khớp: trả về `AuthError("Missing or invalid Authorization header")`.
- Khi xảy ra `AuthError`: trả về `JSONResponse` với `status_code` và error body chứa `code` + `message`.

**JWT Validation (Builder authentication) — `_validate_jwt`:**

1. Decode JWT sử dụng configured secret/JWKS
2. Verify: expiry, issuer, audience
3. Extract claims: `sub` (user_id), `tenant_id`, `roles`
4. Return `AuthContext`

JWT token payload chứa các claims:

| Claim | Mô tả | Ví dụ |
|-------|--------|-------|
| `sub` | User ID | `user_abc123` |
| `tenant_id` | Tenant scope | `tenant_xyz` |
| `roles` | RBAC roles | `["admin", "builder"]` |
| `iat` | Issued at (Unix timestamp) | `1711440000` |
| `exp` | Expiry (Unix timestamp) | `1711443600` |
| `iss` | Issuer | `agent-platform` |
| `aud` | Audience | `agent-platform` |

Decode sử dụng `jwt.decode()` với `jwt_secret`, `jwt_algorithm`, `jwt_issuer`, `jwt_audience` từ settings. Nếu `ExpiredSignatureError` → raise `AuthError("Token expired", 401)`. Nếu `JWTError` → raise `AuthError("Invalid token", 401)`.

Kết quả: trả về `AuthContext` với `user_id=payload["sub"]`, `tenant_id=payload["tenant_id"]`, `user_type="builder"`, `roles=payload.get("roles", [])`.

**API Key Validation (End User authentication) — `_validate_api_key`:**

1. Hash API key: `SHA-256(api_key)` → `key_hash`
2. Lookup `key_hash` trong PostgreSQL `api_keys` table
3. Verify: not expired, not revoked, status = `active`
4. Extract: `tenant_id`, `agent_ids` (scoped access)
5. Return `AuthContext`

API key format: `sk_live_{random_32_chars}`. Chỉ hash được lưu trong DB, không bao giờ lưu plaintext.

Kết quả: trả về `AuthContext` với `user_id=key_record.id`, `tenant_id=key_record.tenant_id`, `user_type="end_user"`, `roles=[]`, `allowed_agent_ids=key_record.agent_ids`.

**AuthContext** — Data class được gắn vào `request.state.auth` sau khi authentication thành công:

| Field | Type | Mô tả |
|-------|------|--------|
| `user_id` | str | ID của user |
| `tenant_id` | str | ID của tenant |
| `user_type` | Literal["builder", "end_user"] | Loại user |
| `roles` | list[str] | Builder RBAC roles |
| `allowed_agent_ids` | list[str] / None | End User: agents họ có thể access. None = all (cho builder) |

**TenantMiddleware** (kế thừa BaseHTTPMiddleware) — Chạy SAU AuthMiddleware. Set PostgreSQL session variable cho Row-Level Security. Với mọi DB query trong request, PostgreSQL RLS policies sẽ tự động filter theo `tenant_id`. Logic: lấy `auth` từ `request.state`, nếu có thì set `request.state.tenant_id = auth.tenant_id`.

**FastAPI Depends helpers cho route-level auth checks:**

- `get_current_tenant(request)` → Extract `tenant_id` từ authenticated request (trả về `request.state.auth.tenant_id`).
- `get_current_user(request)` → Get full `AuthContext` (trả về `request.state.auth`).
- `require_builder(auth)` → Đảm bảo caller là Builder (không phải End User). Nếu `auth.user_type != "builder"` → raise `HTTPException(403, "Builder access required")`.
- `require_agent_access(agent_id, auth)` → Đảm bảo caller có quyền access agent cụ thể. Builder: luôn có access (within tenant). End User: chỉ khi `agent_id` nằm trong `allowed_agent_ids`.

**API Key Storage:**

Table `api_keys`:

| Column | Type | Constraints | Mô tả |
|--------|------|-------------|--------|
| `id` | TEXT | PRIMARY KEY | Unique identifier |
| `tenant_id` | TEXT | NOT NULL, FK → tenants(id) | Tenant sở hữu key |
| `key_hash` | TEXT | NOT NULL, UNIQUE | SHA-256 hash of the API key |
| `name` | TEXT | NOT NULL | Human-readable label |
| `agent_ids` | TEXT[] | NOT NULL | Agents key này có thể access |
| `status` | TEXT | NOT NULL, DEFAULT 'active', CHECK IN ('active', 'revoked') | Trạng thái key |
| `created_by` | TEXT | NOT NULL | Builder user_id đã tạo key |
| `expires_at` | TIMESTAMPTZ | | Thời điểm hết hạn |
| `last_used_at` | TIMESTAMPTZ | | Lần sử dụng gần nhất |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | Thời điểm tạo |

Row Level Security được bật với policy `tenant_isolation` sử dụng `tenant_id = current_setting('app.current_tenant')`.

Index: `idx_api_keys_hash` trên column `key_hash`.

---

### 2.4 Auth Failure Responses

**401 — Missing or invalid credentials:**

| Field | Value |
|-------|-------|
| `error.code` | `UNAUTHORIZED` |
| `error.message` | `Invalid or expired access token` |

**403 — Valid credentials, insufficient permissions:**

| Field | Value |
|-------|-------|
| `error.code` | `FORBIDDEN` |
| `error.message` | `API key does not have access to this agent` |

---

## 3. Builder API

> Auth: Builder credentials (OAuth 2.0 Bearer token)

### 3.1 Agent Management

#### `POST /api/v1/agents` — Create Agent

**Request Body:**

| Field | Type | Required | Mô tả |
|-------|------|----------|--------|
| `name` | string | Yes | Tên agent, ví dụ `Customer Support Agent` |
| `description` | string | No | Mô tả agent |
| `system_prompt` | string | Yes | System prompt cho agent |
| `model_config` | object | Yes | Cấu hình LLM model |
| `model_config.provider` | string | Yes | Provider, ví dụ `anthropic` |
| `model_config.model` | string | Yes | Model name, ví dụ `claude-sonnet-4-5-20250514` |
| `model_config.temperature` | float | No | Temperature, ví dụ `1.0` |
| `model_config.max_tokens` | int | No | Max tokens per response, ví dụ `4096` |
| `model_config.timeout_seconds` | float | No | Timeout cho LLM call, ví dụ `120.0` |
| `execution_config` | object | Yes | Cấu hình execution |
| `execution_config.pattern` | string | Yes | Execution pattern, ví dụ `react` |
| `execution_config.max_steps` | int | No | Số step tối đa, ví dụ `30` |
| `execution_config.max_tokens_budget` | int | No | Token budget, ví dụ `50000` |
| `execution_config.max_cost_usd` | float | No | Cost limit, ví dụ `5.0` |
| `execution_config.max_duration_seconds` | int | No | Duration limit, ví dụ `600` |
| `execution_config.context_strategy` | string | No | Context strategy, ví dụ `summarize_recent` |
| `memory_config` | object | No | Cấu hình memory |
| `memory_config.short_term.strategy` | string | No | Strategy, ví dụ `summarize_recent` |
| `memory_config.short_term.max_context_tokens` | int | No | Max context tokens, ví dụ `8000` |
| `memory_config.short_term.recent_messages_to_keep` | int | No | Số messages giữ lại, ví dụ `20` |
| `memory_config.short_term.summarization_threshold` | float | No | Threshold, ví dụ `0.7` |
| `memory_config.working.scratchpad_enabled` | boolean | No | Bật scratchpad |
| `memory_config.working.max_artifacts` | int | No | Max artifacts, ví dụ `50` |
| `guardrails_config` | object | No | Cấu hình guardrails |
| `guardrails_config.input_validation.max_input_length` | int | No | Max input length, ví dụ `10000` |
| `guardrails_config.injection_detection.enabled` | boolean | No | Bật injection detection |
| `guardrails_config.injection_detection.block_threshold` | float | No | Threshold để block, ví dụ `0.9` |
| `guardrails_config.tool_permissions` | array | No | Danh sách tool permissions |
| `guardrails_config.tool_permissions[].tool_pattern` | string | Yes | Pattern tool, ví dụ `mcp:crm:*` |
| `guardrails_config.tool_permissions[].actions` | array | Yes | Allowed actions, ví dụ `["invoke"]` |
| `guardrails_config.tool_permissions[].constraints.max_calls_per_session` | int | No | Max calls, ví dụ `50` |
| `guardrails_config.tool_permissions[].constraints.requires_approval` | boolean | No | Yêu cầu approval |
| `guardrails_config.budget` | object | No | Budget guardrail |
| `guardrails_config.budget.max_tokens_per_session` | int | No | Max tokens, ví dụ `50000` |
| `guardrails_config.budget.max_cost_per_session_usd` | float | No | Max cost, ví dụ `5.0` |
| `guardrails_config.budget.max_steps_per_session` | int | No | Max steps, ví dụ `50` |
| `guardrails_config.budget.warning_threshold` | float | No | Warning ratio, ví dụ `0.8` |
| `tools_config` | object | No | Cấu hình tools |
| `tools_config.mcp_server_ids` | array | No | Danh sách MCP server IDs |
| `tools_config.max_tools_per_prompt` | int | No | Max tools per prompt, ví dụ `20` |

**Response:** `201 Created`

| Field | Type | Mô tả |
|-------|------|--------|
| `data.id` | string | Agent ID, ví dụ `agt_abc123` |
| `data.tenant_id` | string | Tenant ID |
| `data.name` | string | Tên agent |
| `data.status` | string | Trạng thái, luôn là `draft` khi mới tạo |
| `data.created_at` | string (ISO 8601) | Thời điểm tạo |
| `data.updated_at` | string (ISO 8601) | Thời điểm cập nhật |
| `meta` | object | Request metadata |

**Errors:**
- `400 INVALID_AGENT_CONFIG` — config validation failed
- `404 TOOL_NOT_FOUND` — mcp_server_id does not exist

---

#### `GET /api/v1/agents` — List Agents

**Query Params:**
| Param | Type | Default | Mô tả |
|-------|------|---------|--------|
| `status` | string | — | Filter by status: `draft`, `active`, `archived` |
| `search` | string | — | Search by name (partial match) |
| `sort` | string | `-created_at` | Sort field |
| `limit` | int | 20 | Page size (max 100) |
| `cursor` | string | — | Pagination cursor |

**Response:** `200 OK`

Trả về danh sách agents dạng paginated. Mỗi agent summary bao gồm:

| Field | Type | Mô tả |
|-------|------|--------|
| `id` | string | Agent ID |
| `name` | string | Tên agent |
| `description` | string | Mô tả agent |
| `status` | string | Trạng thái: `draft`, `active`, `archived` |
| `model_config.provider` | string | Provider name |
| `model_config.model` | string | Model name |
| `created_at` | string (ISO 8601) | Thời điểm tạo |
| `updated_at` | string (ISO 8601) | Thời điểm cập nhật |

Kèm theo `pagination` object (xem Section 1.3) và `meta`.

---

#### `GET /api/v1/agents/{agent_id}` — Get Agent

**Response:** `200 OK` — Full Agent object (including all configs)

**Errors:**
- `404 AGENT_NOT_FOUND`

---

#### `PUT /api/v1/agents/{agent_id}` — Update Agent

**Request:** Same schema as Create (full replace). Chỉ `status != "archived"` mới cho phép update.

**Response:** `200 OK`

**Errors:**
- `400 INVALID_AGENT_CONFIG`
- `404 AGENT_NOT_FOUND`
- `409 SESSION_ALREADY_RUNNING` — nếu có active sessions đang dùng agent này (warning, không block)

---

#### `DELETE /api/v1/agents/{agent_id}` — Delete Agent

Soft delete — set `status = "archived"`. Không xoá data.

**Guard:** Reject nếu có sessions đang `RUNNING` hoặc `WAITING_INPUT`.

**Response:** `204 No Content`

**Errors:**
- `404 AGENT_NOT_FOUND`
- `409 SESSION_ALREADY_RUNNING` — có active sessions

---

### 3.2 Session Management (Builder)

#### `GET /api/v1/sessions` — List Sessions

**Query Params:**
| Param | Type | Default | Mô tả |
|-------|------|---------|--------|
| `agent_id` | string | — | Filter by agent |
| `state` | string | — | Filter by state: `running`, `completed`, `failed`, ... |
| `user_type` | string | — | Filter: `builder`, `end_user` |
| `sort` | string | `-created_at` | Sort field |
| `limit` | int | 20 | Page size (max 100) |
| `cursor` | string | — | Pagination cursor |

**Response:** `200 OK` — Paginated list of Session summaries

---

#### `GET /api/v1/sessions/{session_id}` — Get Session

**Response:** `200 OK`

| Field | Type | Mô tả |
|-------|------|--------|
| `data.id` | string | Session ID, ví dụ `ses_def456` |
| `data.agent_id` | string | Agent ID |
| `data.state` | string | Trạng thái session, ví dụ `completed` |
| `data.step_index` | int | Số step đã thực hiện |
| `data.usage.total_tokens` | int | Tổng tokens đã dùng |
| `data.usage.prompt_tokens` | int | Tokens cho prompt |
| `data.usage.completion_tokens` | int | Tokens cho completion |
| `data.usage.total_cost_usd` | float | Tổng chi phí |
| `data.usage.total_steps` | int | Tổng số steps |
| `data.usage.total_tool_calls` | int | Tổng số tool calls |
| `data.usage.total_llm_calls` | int | Tổng số LLM calls |
| `data.usage.duration_seconds` | float | Thời gian execution |
| `data.user_type` | string | Loại user: `builder` hoặc `end_user` |
| `data.created_at` | string (ISO 8601) | Thời điểm tạo |
| `data.completed_at` | string (ISO 8601) | Thời điểm hoàn thành |
| `meta` | object | Request metadata |

---

#### `POST /api/v1/sessions/{session_id}/pause` — Pause Session

**Guard:** Session state phải là `RUNNING`.

**Response:** `200 OK`

| Field | Type | Mô tả |
|-------|------|--------|
| `data.id` | string | Session ID |
| `data.state` | string | Chuyển sang `paused` |
| `data.step_index` | int | Step index hiện tại |
| `meta` | object | Request metadata |

**Errors:**
- `404 SESSION_NOT_FOUND`
- `400 INVALID_STATE_TRANSITION` — session không ở state `RUNNING`

---

#### `POST /api/v1/sessions/{session_id}/resume` — Resume Session

**Guard:** Session state phải là `PAUSED`.

**Response:** `200 OK`

| Field | Type | Mô tả |
|-------|------|--------|
| `data.id` | string | Session ID |
| `data.state` | string | Chuyển sang `running` |
| `data.step_index` | int | Step index hiện tại |
| `meta` | object | Request metadata |

**Errors:**
- `400 INVALID_STATE_TRANSITION` — session không ở state `PAUSED`

---

#### `GET /api/v1/sessions/{session_id}/trace` — Execution Trace

> Trả về chi tiết từng step trong execution.

**Response:** `200 OK`

| Field | Type | Mô tả |
|-------|------|--------|
| `data.session_id` | string | Session ID |
| `data.total_steps` | int | Tổng số steps |
| `data.steps` | array | Danh sách steps |

Mỗi step trong `data.steps` bao gồm:

| Field | Type | Mô tả |
|-------|------|--------|
| `step_index` | int | Số thứ tự step |
| `type` | string | Loại step: `tool_call`, `waiting_input`, `final_answer` |
| `thought` | string | LLM reasoning (nếu có) |
| `tool_calls` | array | Danh sách tool calls (nếu type = `tool_call` hoặc `waiting_input`) |
| `tool_calls[].id` | string | Tool call ID, ví dụ `tc_001` |
| `tool_calls[].name` | string | Tên tool, ví dụ `mcp:crm:search_customer` |
| `tool_calls[].arguments` | object | Arguments truyền vào tool |
| `tool_results` | array | Kết quả tool (nếu có) |
| `tool_results[].tool_call_id` | string | ID tương ứng với tool_call |
| `tool_results[].content` | string | Nội dung kết quả |
| `tool_results[].is_error` | boolean | Có lỗi hay không |
| `tool_results[].latency_ms` | float | Latency tool execution |
| `usage.prompt_tokens` | int | Tokens cho prompt |
| `usage.completion_tokens` | int | Tokens cho completion |
| `usage.cost_usd` | float | Chi phí step |
| `usage.llm_latency_ms` | float | LLM latency |
| `usage.tool_latency_ms` | float | Tool latency (nếu có) |
| `guardrail_checks` | array | Kết quả guardrail checks (nếu có) |
| `guardrail_checks[].type` | string | Loại check, ví dụ `injection_detection` |
| `guardrail_checks[].result` | string | Kết quả: `pass` hoặc `blocked` |
| `guardrail_checks[].latency_ms` | float | Latency check |
| `approval` | object | Thông tin approval (nếu type = `waiting_input`) |
| `approval.approval_id` | string | Approval ID |
| `approval.status` | string | `approved` hoặc `rejected` |
| `approval.approved_by` | string | User đã approve |
| `approval.approved_at` | string (ISO 8601) | Thời điểm approve |
| `answer` | string | Final answer (nếu type = `final_answer`) |
| `timestamp` | string (ISO 8601) | Thời điểm step |

---

#### `GET /api/v1/sessions/{session_id}/cost` — Cost Breakdown

**Response:** `200 OK`

| Field | Type | Mô tả |
|-------|------|--------|
| `data.session_id` | string | Session ID |
| `data.total_cost_usd` | float | Tổng chi phí session |
| `data.breakdown.llm_calls` | array | Chi tiết từng LLM call |
| `data.breakdown.llm_calls[].step_index` | int | Step number |
| `data.breakdown.llm_calls[].model` | string | Model đã dùng |
| `data.breakdown.llm_calls[].input_tokens` | int | Input tokens |
| `data.breakdown.llm_calls[].output_tokens` | int | Output tokens |
| `data.breakdown.llm_calls[].cost_usd` | float | Chi phí LLM call |
| `data.breakdown.tool_calls` | array | Chi tiết từng tool call |
| `data.breakdown.tool_calls[].step_index` | int | Step number |
| `data.breakdown.tool_calls[].tool_name` | string | Tên tool |
| `data.breakdown.tool_calls[].cost_usd` | float | Chi phí tool call |
| `data.breakdown.totals.llm_cost_usd` | float | Tổng chi phí LLM |
| `data.breakdown.totals.tool_cost_usd` | float | Tổng chi phí tools |
| `data.breakdown.totals.total_input_tokens` | int | Tổng input tokens |
| `data.breakdown.totals.total_output_tokens` | int | Tổng output tokens |
| `meta` | object | Request metadata |

---

### 3.3 Tools (Builder)

#### `GET /api/v1/tools` — List Available Tools

**Query Params:**
| Param | Type | Default | Mô tả |
|-------|------|---------|--------|
| `server_id` | string | — | Filter by MCP server |
| `namespace` | string | — | Filter by namespace (e.g., `mcp:github`) |
| `risk_level` | string | — | Filter: `low`, `medium`, `high`, `critical` |
| `status` | string | `active` | Filter: `active`, `degraded`, `unavailable` |
| `search` | string | — | Search by name or description |
| `limit` | int | 50 | Page size (max 200) |
| `cursor` | string | — | Pagination cursor |

**Response:** `200 OK`

Trả về danh sách tools dạng paginated. Mỗi tool bao gồm:

| Field | Type | Mô tả |
|-------|------|--------|
| `id` | string | Tool ID, ví dụ `mcp:github:create_issue` |
| `name` | string | Tên tool |
| `server_id` | string | MCP server ID |
| `namespace` | string | Tool namespace |
| `description` | string | Mô tả tool |
| `input_schema` | object | JSON Schema mô tả input của tool (type, properties, required) |
| `risk_level` | string | Mức rủi ro: `low`, `medium`, `high`, `critical` |
| `requires_approval` | boolean | Có yêu cầu approval không |
| `status` | string | Trạng thái: `active`, `degraded`, `unavailable` |

Kèm theo `pagination` và `meta`.

---

### 3.4 MCP Servers (Builder)

#### `GET /api/v1/mcp-servers` — List MCP Servers

**Response:** `200 OK`

Trả về danh sách MCP servers. Mỗi server bao gồm:

| Field | Type | Mô tả |
|-------|------|--------|
| `id` | string | Server ID, ví dụ `server_github_01` |
| `name` | string | Tên server |
| `transport` | string | Transport type, ví dụ `stdio` |
| `status` | string | Trạng thái: `connected`, `connecting`, `disconnected` |
| `tools_count` | int | Số tools đã discover |
| `last_connected_at` | string (ISO 8601) | Thời điểm connect gần nhất |

Kèm theo `meta`.

---

#### `POST /api/v1/mcp-servers` — Register MCP Server

**Request Body:**

| Field | Type | Required | Mô tả |
|-------|------|----------|--------|
| `name` | string | Yes | Tên server, ví dụ `GitHub MCP Server` |
| `description` | string | No | Mô tả server |
| `transport` | string | Yes | Transport type: `stdio` |
| `command` | string | Yes | Command để start server, ví dụ `npx` |
| `args` | array | No | Arguments cho command, ví dụ `["-y", "@modelcontextprotocol/server-github"]` |
| `env` | object | No | Environment variables, ví dụ `{"GITHUB_TOKEN": "ghp_..."}` |
| `auto_start` | boolean | No | Tự động start khi register |
| `health_check_interval_seconds` | int | No | Interval health check, ví dụ `60` |

**Response:** `201 Created`

| Field | Type | Mô tả |
|-------|------|--------|
| `data.id` | string | Server ID |
| `data.name` | string | Tên server |
| `data.transport` | string | Transport type |
| `data.status` | string | Trạng thái ban đầu: `connecting` |
| `data.tools_discovered` | array | Danh sách tools (ban đầu trống) |
| `meta` | object | Request metadata |

> Server sẽ tự connect + discover tools trong background. Client poll `GET /api/v1/mcp-servers/{id}` để check status.

---

#### `DELETE /api/v1/mcp-servers/{server_id}` — Remove MCP Server

**Guard:** Không cho xoá nếu server đang được active agents sử dụng.

**Response:** `204 No Content`

---

### 3.5 Governance (Builder)

#### `GET /api/v1/audit/sessions/{session_id}` — Session Audit Trail

**Query Params:**
| Param | Type | Default | Mô tả |
|-------|------|---------|--------|
| `categories` | string | — | Comma-separated: `llm_call,tool_call,guardrail_check` |
| `outcomes` | string | — | Comma-separated: `failure,blocked` |
| `limit` | int | 100 | Page size |
| `cursor` | string | — | Pagination cursor |

**Response:** `200 OK`

Trả về danh sách audit events dạng paginated. Mỗi event bao gồm:

| Field | Type | Mô tả |
|-------|------|--------|
| `id` | string | Event ID, ví dụ `evt_001` |
| `timestamp` | string (ISO 8601) | Thời điểm event |
| `category` | string | Loại: `guardrail_check`, `llm_call`, `tool_call` |
| `action` | string | Hành động cụ thể, ví dụ `injection_detection` |
| `actor.type` | string | Loại actor: `system`, `user` |
| `actor.id` | string | ID actor |
| `outcome` | string | Kết quả: `success`, `failure`, `blocked` |
| `details` | object | Thông tin chi tiết (tuỳ category) |

Ví dụ `details` cho `guardrail_check`: chứa `check_type`, `result`, `confidence`, `latency_ms`.

Kèm theo `pagination` và `meta`.

---

#### `GET /api/v1/audit/agents/{agent_id}` — Agent Audit Trail

Same schema as session audit, filtered by agent_id.

---

## 4. End User API

> Auth: Scoped API Key (`X-API-Key`). End User chỉ access được agent mà builder cho phép.

### 4.1 Session

#### `POST /api/v1/sessions` — Create Session

**Request Body:**

| Field | Type | Required | Mô tả |
|-------|------|----------|--------|
| `agent_id` | string | Yes | ID của agent cần tạo session |

**Response:** `201 Created`

| Field | Type | Mô tả |
|-------|------|--------|
| `data.id` | string | Session ID, ví dụ `ses_def456` |
| `data.agent_id` | string | Agent ID |
| `data.state` | string | Trạng thái ban đầu: `created` |
| `data.created_at` | string (ISO 8601) | Thời điểm tạo |
| `meta` | object | Request metadata |

**Errors:**
- `404 AGENT_NOT_FOUND` — agent không tồn tại hoặc không active
- `403 FORBIDDEN` — API key không có quyền access agent này

---

### 4.2 Messages

#### `POST /api/v1/sessions/{session_id}/messages` — Send Message

> Gửi message và trigger execution. Response trả về ngay (202 Accepted). Client nhận kết quả qua SSE stream.

**Request Body:**

| Field | Type | Required | Mô tả |
|-------|------|----------|--------|
| `content` | string | Yes | Nội dung message, ví dụ `Find customer John Doe and check his recent orders` |

**Response:** `202 Accepted`

| Field | Type | Mô tả |
|-------|------|--------|
| `data.message_id` | string | Message ID, ví dụ `msg_ghi789` |
| `data.session_id` | string | Session ID |
| `data.state` | string | Trạng thái: `running` |
| `meta` | object | Request metadata |

**Errors:**
- `404 SESSION_NOT_FOUND`
- `400 INVALID_STATE_TRANSITION` — session đã `COMPLETED` hoặc `FAILED`
- `422 GUARDRAIL_BLOCKED` — input bị block bởi inbound guardrails

**Flow:**
1. API nhận message → validate → store message → enqueue ExecutionTask
2. Return `202 Accepted` ngay lập tức
3. Client connect SSE stream để nhận real-time events
4. Executor pull task → execute steps → emit events qua SSE

---

#### `GET /api/v1/sessions/{session_id}/messages` — Get Conversation History

**Response:** `200 OK`

Trả về danh sách messages. Mỗi message bao gồm:

| Field | Type | Mô tả |
|-------|------|--------|
| `id` | string | Message ID |
| `role` | string | `user` hoặc `assistant` |
| `content` | string | Nội dung message |
| `tokens` | int | Số tokens (chỉ có ở assistant messages) |
| `created_at` | string (ISO 8601) | Thời điểm tạo |

Kèm theo `meta`.

> Chỉ trả về messages với `role` = `user` hoặc `assistant`. System messages và tool messages không expose cho end user.

---

### 4.3 SSE Streaming

#### `GET /api/v1/sessions/{session_id}/stream` — Real-Time Event Stream

> Server-Sent Events (SSE). Client giữ connection mở để nhận events real-time.

**Headers:**

```
Accept: text/event-stream
Authorization: X-API-Key {api_key}
```

**Connection Behavior:**
- Client connect bất kỳ lúc nào — nhận events từ thời điểm connect
- Server gửi `heartbeat` mỗi 15s nếu không có events (keep-alive)
- Client reconnect: gửi `Last-Event-ID` header → server resume từ event đó
- Connection tự đóng khi session `COMPLETED` hoặc `FAILED`

### 4.4 SSE Event Types

Mỗi SSE event có format: `event: {type}`, `id: {event_id}`, `data: {json_payload}`.

Danh sách event types và data payload:

| Event | Data Fields | Mô tả |
|-------|-------------|--------|
| `heartbeat` | (trống) | Keep-alive |
| `step_start` | `step_index`, `pattern` | Bắt đầu step mới, ví dụ step_index=1, pattern=react |
| `thought` | `content` | LLM reasoning, ví dụ "I need to search the CRM..." |
| `tool_call` | `tool_name`, `arguments` | Tool invocation bắt đầu |
| `tool_result` | `tool_name`, `content_preview`, `is_error`, `latency_ms` | Kết quả tool (truncated) |
| `text_delta` | `content` | Partial text response (streaming) |
| `approval_requested` | `approval_id`, `tool_name`, `reason`, `timeout_seconds` | Yêu cầu human approval |
| `budget_warning` | `budget_type`, `usage_ratio`, `message` | Budget warning, ví dụ "85% of token budget used" |
| `guardrail_check` | `check_type`, `result` | Guardrail status |
| `error` | `code`, `message`, `retryable` | Error notification |
| `final_answer` | `content`, `usage` (chứa `total_tokens`, `total_cost_usd`, `total_steps`) | Final response kèm usage stats |
| `done` | `session_state` | Stream kết thúc, ví dụ session_state=completed |

### 4.5 SSE Event Reference

| Event | Timing | Data Fields | Mô tả |
|-------|--------|-------------|--------|
| `heartbeat` | Mỗi 15s | `{}` | Keep-alive |
| `step_start` | Đầu mỗi step | `step_index`, `pattern` | Bắt đầu step mới |
| `thought` | Sau LLM response (nếu có) | `content` | LLM reasoning/thinking |
| `tool_call` | Khi LLM gọi tool | `tool_name`, `arguments` | Tool invocation bắt đầu |
| `tool_result` | Sau tool execution | `tool_name`, `content_preview`, `is_error`, `latency_ms` | Kết quả tool (truncated) |
| `text_delta` | Streaming LLM text | `content` | Partial text response |
| `approval_requested` | Khi HITL cần approval | `approval_id`, `tool_name`, `reason`, `timeout_seconds` | Yêu cầu human approval |
| `budget_warning` | Budget > warning threshold | `budget_type`, `usage_ratio`, `message` | Budget warning |
| `guardrail_check` | Sau mỗi guardrail check | `check_type`, `result` | Guardrail status |
| `error` | Khi có lỗi | `code`, `message`, `retryable` | Error notification |
| `final_answer` | Khi execution xong | `content`, `usage` | Final response |
| `done` | Cuối stream | `session_state` | Stream kết thúc |

### 4.6 HITL Approval API

#### `POST /api/v1/sessions/{session_id}/approve` — Approve Tool Call

**Request Body:**

| Field | Type | Required | Mô tả |
|-------|------|----------|--------|
| `approval_id` | string | Yes | ID approval cần approve |
| `decision` | string | Yes | Giá trị: `approve` |

**Response:** `200 OK`

| Field | Type | Mô tả |
|-------|------|--------|
| `data.approval_id` | string | Approval ID |
| `data.decision` | string | `approve` |
| `data.session_state` | string | Trạng thái session sau approve: `running` |
| `meta` | object | Request metadata |

#### `POST /api/v1/sessions/{session_id}/reject` — Reject Tool Call

**Request Body:**

| Field | Type | Required | Mô tả |
|-------|------|----------|--------|
| `approval_id` | string | Yes | ID approval cần reject |
| `decision` | string | Yes | Giá trị: `reject` |
| `reason` | string | No | Lý do reject, ví dụ `Do not send email to this address` |

**Response:** `200 OK`

> Rejection reason sẽ được inject vào context cho LLM biết tại sao tool bị reject.

---

## 5. System API

### 5.1 Health Checks

#### `GET /health` — Liveness

Trả về trạng thái liveness. Response chứa field `status` với giá trị `ok`.

#### `GET /ready` — Readiness

Trả về trạng thái readiness, kiểm tra tất cả dependencies.

**Response khi healthy:**

| Field | Type | Mô tả |
|-------|------|--------|
| `status` | string | `ready` |
| `checks.postgresql` | string | `ok` |
| `checks.redis` | string | `ok` |
| `checks.llm_provider` | string | `ok` |

**Response khi unhealthy (HTTP Status: `503 Service Unavailable`):**

| Field | Type | Mô tả |
|-------|------|--------|
| `status` | string | `not_ready` |
| `checks.postgresql` | string | `ok` hoặc `error` |
| `checks.redis` | string | `ok` hoặc `error` |
| `checks.llm_provider` | string | `ok` hoặc `error` |

---

## 6. Error Response Reference

### 6.1 Error Response Schema

**ErrorResponse** gồm 2 fields chính:

| Field | Type | Mô tả |
|-------|------|--------|
| `error` | ErrorDetail | Chi tiết lỗi |
| `meta` | ResponseMeta | Request metadata |

**ErrorDetail:**

| Field | Type | Mô tả |
|-------|------|--------|
| `code` | str | Machine-readable error code (xem `01-data-models.md` Section 9.3) |
| `message` | str | Human-readable error message |
| `details` | dict | Structured context bổ sung (default: trống) |

### 6.2 Error Codes Table

> Xem [`01-data-models.md`](01-data-models.md) Section 9.3 cho full list.

| HTTP | Code | When |
|------|------|------|
| 400 | `INVALID_REQUEST` | Malformed JSON, missing required fields |
| 400 | `INVALID_AGENT_CONFIG` | Agent config validation failure |
| 400 | `INVALID_STATE_TRANSITION` | Session state machine violation |
| 401 | `UNAUTHORIZED` | Missing or invalid credentials |
| 403 | `FORBIDDEN` | Valid auth, no access |
| 403 | `TENANT_MISMATCH` | Cross-tenant access attempt |
| 404 | `AGENT_NOT_FOUND` | Agent does not exist |
| 404 | `SESSION_NOT_FOUND` | Session does not exist |
| 404 | `TOOL_NOT_FOUND` | Tool does not exist |
| 409 | `SESSION_ALREADY_RUNNING` | Conflict with active session |
| 409 | `SESSION_COMPLETED` | Session already finished |
| 422 | `GUARDRAIL_BLOCKED` | Input blocked by guardrails |
| 429 | `RATE_LIMITED` | Too many requests |
| 500 | `INTERNAL_ERROR` | Unexpected server error |
| 502 | `LLM_PROVIDER_ERROR` | LLM API returned error |
| 503 | `SERVICE_UNAVAILABLE` | Temporary unavailability |
| 504 | `LLM_TIMEOUT` | LLM call timed out |

---

## 7. Rate Limiting

### 7.1 Default Limits

| Scope | Limit | Window |
|-------|-------|--------|
| Builder API (per tenant) | 1000 req | 1 minute |
| End User API (per API key) | 60 req | 1 minute |
| Message send (per session) | 10 req | 1 minute |
| Session create (per API key) | 20 req | 1 minute |

### 7.2 Rate Limit Response

Khi bị rate limit, server trả về HTTP `429 Too Many Requests` với các headers:

| Header | Ví dụ | Mô tả |
|--------|-------|--------|
| `X-RateLimit-Limit` | `60` | Requests allowed per window |
| `X-RateLimit-Remaining` | `0` | Requests remaining |
| `X-RateLimit-Reset` | `1711443600` | Unix timestamp khi window reset |
| `Retry-After` | `45` | Seconds to wait |

Error body:

| Field | Value | Mô tả |
|-------|-------|--------|
| `error.code` | `RATE_LIMITED` | Error code |
| `error.message` | `Rate limit exceeded. Retry after 45 seconds.` | Human-readable message |
| `error.details.limit` | `60` | Request limit per window |
| `error.details.window_seconds` | `60` | Window duration |
| `error.details.retry_after_seconds` | `45` | Seconds to wait |

---

## 8. Phase Scope

| Endpoint Group | Phase 1 | Phase 2 |
|---|:---:|:---:|
| Agent CRUD (`/agents`) | ✅ | extend (versioning, clone) |
| Session Management (`/sessions`) | ✅ | extend (WebSocket) |
| Messages (`/sessions/{id}/messages`) | ✅ | |
| SSE Stream (`/sessions/{id}/stream`) | ✅ | |
| WebSocket (`/sessions/{id}/ws`) | | ✅ |
| Tools List (`/tools`) | ✅ | extend (custom tool registration) |
| MCP Servers (`/mcp-servers`) | ✅ | |
| Audit Trail (`/audit`) | ✅ | |
| Cost Breakdown (`/sessions/{id}/cost`) | ✅ | |
| Execution Trace (`/sessions/{id}/trace`) | ✅ | |
| HITL Approval (`/approve`, `/reject`) | ✅ | |
| Memory API (`/memory`) | | ✅ |
| Health/Ready (`/health`, `/ready`) | ✅ | |
| Agent Versioning (`/agents/{id}/versions`) | | ✅ |
| SDK endpoints | | ✅ |
