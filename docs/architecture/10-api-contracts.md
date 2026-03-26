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

**Success:**
```json
{
  "data": { ... },
  "meta": {
    "request_id": "req_abc123",
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "timestamp": "2026-03-26T10:30:00Z"
  }
}
```

**Error:**
```json
{
  "error": {
    "code": "AGENT_NOT_FOUND",
    "message": "Agent with ID 'xyz' not found",
    "details": {}
  },
  "meta": {
    "request_id": "req_abc123",
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "timestamp": "2026-03-26T10:30:00Z"
  }
}
```

### 1.3 Pagination

List endpoints sử dụng cursor-based pagination:

```
GET /api/v1/sessions?limit=20&cursor=eyJjcmVhdGVkX2F0IjoiMjAyNi0wMy0yNiJ9
```

**Response:**
```json
{
  "data": [ ... ],
  "pagination": {
    "limit": 20,
    "has_more": true,
    "next_cursor": "eyJjcmVhdGVkX2F0IjoiMjAyNi0wMy0yNSJ9"
  },
  "meta": { ... }
}
```

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

```python
class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authenticates every request and attaches identity to request.state.

    Execution order:
    1. Extract credentials from Authorization header
    2. Determine auth method: Bearer (Builder) or X-API-Key (End User)
    3. Validate credentials
    4. Attach AuthContext to request.state
    5. Pass to next middleware (TenantMiddleware)

    Skip: /health, /ready, /docs, /openapi.json
    """

    SKIP_PATHS = {"/health", "/ready", "/docs", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")

        try:
            if auth_header.startswith("Bearer "):
                # Builder: JWT (OAuth 2.0)
                token = auth_header[7:]
                auth_context = await self._validate_jwt(token)

            elif auth_header.startswith("X-API-Key "):
                # End User: scoped API key
                api_key = auth_header[10:]
                auth_context = await self._validate_api_key(api_key)

            else:
                raise AuthError("Missing or invalid Authorization header")

            request.state.auth = auth_context
            return await call_next(request)

        except AuthError as e:
            return JSONResponse(
                status_code=e.status_code,
                content={"error": {"code": e.code, "message": str(e)}},
            )

    async def _validate_jwt(self, token: str) -> AuthContext:
        """
        Validate JWT token (Builder authentication).

        1. Decode JWT using configured secret/JWKS
        2. Verify: expiry, issuer, audience
        3. Extract claims: sub (user_id), tenant_id, roles
        4. Return AuthContext

        Token payload:
        {
            "sub": "user_abc123",           # user ID
            "tenant_id": "tenant_xyz",      # tenant scope
            "roles": ["admin", "builder"],  # RBAC roles
            "iat": 1711440000,
            "exp": 1711443600,
            "iss": "agent-platform",
            "aud": "agent-platform"
        }
        """
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret,
                algorithms=[self._settings.jwt_algorithm],
                issuer=self._settings.jwt_issuer,
                audience=self._settings.jwt_audience,
            )
        except jwt.ExpiredSignatureError:
            raise AuthError("Token expired", status_code=401)
        except jwt.JWTError:
            raise AuthError("Invalid token", status_code=401)

        return AuthContext(
            user_id=payload["sub"],
            tenant_id=payload["tenant_id"],
            user_type="builder",
            roles=payload.get("roles", []),
        )

    async def _validate_api_key(self, api_key: str) -> AuthContext:
        """
        Validate API key (End User authentication).

        1. Hash the key: SHA-256(api_key) → key_hash
        2. Lookup key_hash in PostgreSQL api_keys table
        3. Verify: not expired, not revoked, status = active
        4. Extract: tenant_id, agent_ids (scoped access)
        5. Return AuthContext

        API key format: "sk_live_{random_32_chars}"
        Storage: only hash stored in DB (never plaintext)
        """
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        key_record = await self._api_key_repo.get_by_hash(key_hash)

        if not key_record:
            raise AuthError("Invalid API key", status_code=401)
        if key_record.status != "active":
            raise AuthError("API key revoked or expired", status_code=401)
        if key_record.expires_at and key_record.expires_at < utcnow():
            raise AuthError("API key expired", status_code=401)

        return AuthContext(
            user_id=key_record.id,
            tenant_id=key_record.tenant_id,
            user_type="end_user",
            roles=[],
            allowed_agent_ids=key_record.agent_ids,  # scoped to specific agents
        )
```

```python
@dataclass
class AuthContext:
    """Attached to request.state.auth after authentication."""
    user_id: str
    tenant_id: str
    user_type: Literal["builder", "end_user"]
    roles: list[str]                          # Builder RBAC roles
    allowed_agent_ids: list[str] | None = None  # End User: agents they can access (None = all for builder)
```

```python
class TenantMiddleware(BaseHTTPMiddleware):
    """
    Sets PostgreSQL session variable for Row-Level Security.
    Must run AFTER AuthMiddleware.

    For every DB query in this request, PostgreSQL RLS policies
    will automatically filter by tenant_id.
    """

    async def dispatch(self, request: Request, call_next):
        auth: AuthContext = getattr(request.state, "auth", None)
        if auth:
            # Set PostgreSQL session variable for RLS
            # This is done via the DB session factory
            request.state.tenant_id = auth.tenant_id
        return await call_next(request)
```

```python
# FastAPI Depends helpers for route-level auth checks

def get_current_tenant(request: Request) -> str:
    """Extract tenant_id from authenticated request."""
    return request.state.auth.tenant_id


def get_current_user(request: Request) -> AuthContext:
    """Get full auth context."""
    return request.state.auth


def require_builder(auth: AuthContext = Depends(get_current_user)) -> AuthContext:
    """Ensure caller is a Builder (not End User)."""
    if auth.user_type != "builder":
        raise HTTPException(403, detail="Builder access required")
    return auth


def require_agent_access(agent_id: str, auth: AuthContext = Depends(get_current_user)) -> AuthContext:
    """
    Ensure caller has access to this specific agent.
    Builder: always has access (within tenant).
    End User: only if agent_id is in their allowed_agent_ids.
    """
    if auth.user_type == "end_user":
        if auth.allowed_agent_ids and agent_id not in auth.allowed_agent_ids:
            raise HTTPException(403, detail="No access to this agent")
    return auth
```

**API Key Storage:**

```sql
CREATE TABLE api_keys (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    key_hash        TEXT NOT NULL UNIQUE,      -- SHA-256 hash of the API key
    name            TEXT NOT NULL,              -- human-readable label
    agent_ids       TEXT[] NOT NULL,            -- agents this key can access
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'revoked')),
    created_by      TEXT NOT NULL,              -- builder user_id who created it
    expires_at      TIMESTAMPTZ,
    last_used_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON api_keys
    USING (tenant_id = current_setting('app.current_tenant'));

CREATE INDEX idx_api_keys_hash ON api_keys (key_hash);
```

---

### 2.4 Auth Failure Responses

```json
// 401 — missing or invalid credentials
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Invalid or expired access token"
  }
}

// 403 — valid credentials, insufficient permissions
{
  "error": {
    "code": "FORBIDDEN",
    "message": "API key does not have access to this agent"
  }
}
```

---

## 3. Builder API

> Auth: Builder credentials (OAuth 2.0 Bearer token)

### 3.1 Agent Management

#### `POST /api/v1/agents` — Create Agent

**Request:**
```json
{
  "name": "Customer Support Agent",
  "description": "Handles customer inquiries via CRM tools",
  "system_prompt": "You are a helpful customer support agent...",
  "model_config": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-5-20250514",
    "temperature": 1.0,
    "max_tokens": 4096,
    "timeout_seconds": 120.0
  },
  "execution_config": {
    "pattern": "react",
    "max_steps": 30,
    "max_tokens_budget": 50000,
    "max_cost_usd": 5.0,
    "max_duration_seconds": 600,
    "context_strategy": "summarize_recent"
  },
  "memory_config": {
    "short_term": {
      "strategy": "summarize_recent",
      "max_context_tokens": 8000,
      "recent_messages_to_keep": 20,
      "summarization_threshold": 0.7
    },
    "working": {
      "scratchpad_enabled": true,
      "max_artifacts": 50
    }
  },
  "guardrails_config": {
    "input_validation": { "max_input_length": 10000 },
    "injection_detection": { "enabled": true, "block_threshold": 0.9 },
    "tool_permissions": [
      {
        "tool_pattern": "mcp:crm:*",
        "actions": ["invoke"],
        "constraints": {
          "max_calls_per_session": 50,
          "requires_approval": false
        }
      },
      {
        "tool_pattern": "mcp:email:send_*",
        "actions": ["invoke"],
        "constraints": {
          "requires_approval": true
        }
      }
    ],
    "budget": {
      "max_tokens_per_session": 50000,
      "max_cost_per_session_usd": 5.0,
      "max_steps_per_session": 50,
      "warning_threshold": 0.8
    }
  },
  "tools_config": {
    "mcp_server_ids": ["server_crm_01", "server_email_01"],
    "max_tools_per_prompt": 20
  }
}
```

**Response:** `201 Created`
```json
{
  "data": {
    "id": "agt_abc123",
    "tenant_id": "tenant_xyz",
    "name": "Customer Support Agent",
    "status": "draft",
    "created_at": "2026-03-26T10:30:00Z",
    "updated_at": "2026-03-26T10:30:00Z"
  },
  "meta": { ... }
}
```

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
```json
{
  "data": [
    {
      "id": "agt_abc123",
      "name": "Customer Support Agent",
      "description": "Handles customer inquiries via CRM tools",
      "status": "active",
      "model_config": { "provider": "anthropic", "model": "claude-sonnet-4-5-20250514" },
      "created_at": "2026-03-26T10:30:00Z",
      "updated_at": "2026-03-26T10:30:00Z"
    }
  ],
  "pagination": { "limit": 20, "has_more": false, "next_cursor": null },
  "meta": { ... }
}
```

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
```json
{
  "data": {
    "id": "ses_def456",
    "agent_id": "agt_abc123",
    "state": "completed",
    "step_index": 3,
    "usage": {
      "total_tokens": 12500,
      "prompt_tokens": 9800,
      "completion_tokens": 2700,
      "total_cost_usd": 0.42,
      "total_steps": 3,
      "total_tool_calls": 2,
      "total_llm_calls": 3,
      "duration_seconds": 15.3
    },
    "user_type": "builder",
    "created_at": "2026-03-26T10:31:00Z",
    "completed_at": "2026-03-26T10:31:15Z"
  },
  "meta": { ... }
}
```

---

#### `POST /api/v1/sessions/{session_id}/pause` — Pause Session

**Guard:** Session state phải là `RUNNING`.

**Response:** `200 OK`
```json
{
  "data": {
    "id": "ses_def456",
    "state": "paused",
    "step_index": 2
  },
  "meta": { ... }
}
```

**Errors:**
- `404 SESSION_NOT_FOUND`
- `400 INVALID_STATE_TRANSITION` — session không ở state `RUNNING`

---

#### `POST /api/v1/sessions/{session_id}/resume` — Resume Session

**Guard:** Session state phải là `PAUSED`.

**Response:** `200 OK`
```json
{
  "data": {
    "id": "ses_def456",
    "state": "running",
    "step_index": 2
  },
  "meta": { ... }
}
```

**Errors:**
- `400 INVALID_STATE_TRANSITION` — session không ở state `PAUSED`

---

#### `GET /api/v1/sessions/{session_id}/trace` — Execution Trace

> Trả về chi tiết từng step trong execution.

**Response:** `200 OK`
```json
{
  "data": {
    "session_id": "ses_def456",
    "total_steps": 3,
    "steps": [
      {
        "step_index": 1,
        "type": "tool_call",
        "thought": "I need to search the CRM for this customer...",
        "tool_calls": [
          { "id": "tc_001", "name": "mcp:crm:search_customer", "arguments": {"email": "user@example.com"} }
        ],
        "tool_results": [
          { "tool_call_id": "tc_001", "content": "{\"name\": \"John\", ...}", "is_error": false, "latency_ms": 120 }
        ],
        "usage": {
          "prompt_tokens": 3200,
          "completion_tokens": 450,
          "cost_usd": 0.12,
          "llm_latency_ms": 1200,
          "tool_latency_ms": 120
        },
        "guardrail_checks": [
          { "type": "injection_detection", "result": "pass", "latency_ms": 2 },
          { "type": "tool_permission", "result": "pass", "latency_ms": 1 }
        ],
        "timestamp": "2026-03-26T10:31:01Z"
      },
      {
        "step_index": 2,
        "type": "waiting_input",
        "thought": "I should send a follow-up email...",
        "tool_calls": [
          { "id": "tc_002", "name": "mcp:email:send_email", "arguments": {"to": "user@example.com", "subject": "Follow-up"} }
        ],
        "approval": {
          "approval_id": "apr_789",
          "status": "approved",
          "approved_by": "builder_user_01",
          "approved_at": "2026-03-26T10:31:08Z"
        },
        "timestamp": "2026-03-26T10:31:05Z"
      },
      {
        "step_index": 3,
        "type": "final_answer",
        "answer": "I've found the customer record and sent a follow-up email...",
        "usage": {
          "prompt_tokens": 4100,
          "completion_tokens": 350,
          "cost_usd": 0.15,
          "llm_latency_ms": 980
        },
        "timestamp": "2026-03-26T10:31:14Z"
      }
    ]
  },
  "meta": { ... }
}
```

---

#### `GET /api/v1/sessions/{session_id}/cost` — Cost Breakdown

**Response:** `200 OK`
```json
{
  "data": {
    "session_id": "ses_def456",
    "total_cost_usd": 0.42,
    "breakdown": {
      "llm_calls": [
        { "step_index": 1, "model": "claude-sonnet-4-5-20250514", "input_tokens": 3200, "output_tokens": 450, "cost_usd": 0.12 },
        { "step_index": 2, "model": "claude-sonnet-4-5-20250514", "input_tokens": 2500, "output_tokens": 200, "cost_usd": 0.09 },
        { "step_index": 3, "model": "claude-sonnet-4-5-20250514", "input_tokens": 4100, "output_tokens": 350, "cost_usd": 0.15 }
      ],
      "tool_calls": [
        { "step_index": 1, "tool_name": "mcp:crm:search_customer", "cost_usd": 0.0 },
        { "step_index": 2, "tool_name": "mcp:email:send_email", "cost_usd": 0.0 }
      ],
      "totals": {
        "llm_cost_usd": 0.36,
        "tool_cost_usd": 0.0,
        "total_input_tokens": 9800,
        "total_output_tokens": 1000
      }
    }
  },
  "meta": { ... }
}
```

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
```json
{
  "data": [
    {
      "id": "mcp:github:create_issue",
      "name": "create_issue",
      "server_id": "server_github_01",
      "namespace": "mcp:github",
      "description": "Create a new issue in a GitHub repository",
      "input_schema": {
        "type": "object",
        "properties": {
          "repo": { "type": "string" },
          "title": { "type": "string" },
          "body": { "type": "string" }
        },
        "required": ["repo", "title"]
      },
      "risk_level": "medium",
      "requires_approval": false,
      "status": "active"
    }
  ],
  "pagination": { ... },
  "meta": { ... }
}
```

---

### 3.4 MCP Servers (Builder)

#### `GET /api/v1/mcp-servers` — List MCP Servers

**Response:** `200 OK`
```json
{
  "data": [
    {
      "id": "server_github_01",
      "name": "GitHub MCP",
      "transport": "stdio",
      "status": "connected",
      "tools_count": 12,
      "last_connected_at": "2026-03-26T10:00:00Z"
    }
  ],
  "meta": { ... }
}
```

---

#### `POST /api/v1/mcp-servers` — Register MCP Server

**Request:**
```json
{
  "name": "GitHub MCP Server",
  "description": "GitHub integration via MCP",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": {
    "GITHUB_TOKEN": "ghp_..."
  },
  "auto_start": true,
  "health_check_interval_seconds": 60
}
```

**Response:** `201 Created`
```json
{
  "data": {
    "id": "server_github_01",
    "name": "GitHub MCP Server",
    "transport": "stdio",
    "status": "connecting",
    "tools_discovered": []
  },
  "meta": { ... }
}
```

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
```json
{
  "data": [
    {
      "id": "evt_001",
      "timestamp": "2026-03-26T10:31:01Z",
      "category": "guardrail_check",
      "action": "injection_detection",
      "actor": { "type": "system", "id": "guardrail_engine" },
      "outcome": "success",
      "details": {
        "check_type": "injection_detection",
        "result": "pass",
        "confidence": 0.05,
        "latency_ms": 2.1
      }
    }
  ],
  "pagination": { ... },
  "meta": { ... }
}
```

---

#### `GET /api/v1/audit/agents/{agent_id}` — Agent Audit Trail

Same schema as session audit, filtered by agent_id.

---

## 4. End User API

> Auth: Scoped API Key (`X-API-Key`). End User chỉ access được agent mà builder cho phép.

### 4.1 Session

#### `POST /api/v1/sessions` — Create Session

**Request:**
```json
{
  "agent_id": "agt_abc123"
}
```

**Response:** `201 Created`
```json
{
  "data": {
    "id": "ses_def456",
    "agent_id": "agt_abc123",
    "state": "created",
    "created_at": "2026-03-26T10:31:00Z"
  },
  "meta": { ... }
}
```

**Errors:**
- `404 AGENT_NOT_FOUND` — agent không tồn tại hoặc không active
- `403 FORBIDDEN` — API key không có quyền access agent này

---

### 4.2 Messages

#### `POST /api/v1/sessions/{session_id}/messages` — Send Message

> Gửi message và trigger execution. Response trả về ngay (202 Accepted). Client nhận kết quả qua SSE stream.

**Request:**
```json
{
  "content": "Find customer John Doe and check his recent orders"
}
```

**Response:** `202 Accepted`
```json
{
  "data": {
    "message_id": "msg_ghi789",
    "session_id": "ses_def456",
    "state": "running"
  },
  "meta": { ... }
}
```

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
```json
{
  "data": [
    {
      "id": "msg_001",
      "role": "user",
      "content": "Find customer John Doe",
      "created_at": "2026-03-26T10:31:00Z"
    },
    {
      "id": "msg_002",
      "role": "assistant",
      "content": "I found John Doe's record...",
      "tokens": 450,
      "created_at": "2026-03-26T10:31:14Z"
    }
  ],
  "meta": { ... }
}
```

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

```
event: heartbeat
id: evt_000
data: {}

event: step_start
id: evt_001
data: {"step_index": 1, "pattern": "react"}

event: thought
id: evt_002
data: {"content": "I need to search the CRM for this customer..."}

event: tool_call
id: evt_003
data: {"tool_name": "mcp:crm:search_customer", "arguments": {"email": "user@example.com"}}

event: tool_result
id: evt_004
data: {"tool_name": "mcp:crm:search_customer", "content_preview": "{\"name\": \"John\", ...}", "is_error": false, "latency_ms": 120}

event: text_delta
id: evt_005
data: {"content": "I found "}

event: text_delta
id: evt_006
data: {"content": "the customer record..."}

event: approval_requested
id: evt_007
data: {"approval_id": "apr_789", "tool_name": "mcp:email:send_email", "reason": "High-risk tool requires approval", "timeout_seconds": 3600}

event: budget_warning
id: evt_008
data: {"budget_type": "tokens", "usage_ratio": 0.85, "message": "85% of token budget used"}

event: guardrail_check
id: evt_009
data: {"check_type": "injection_detection", "result": "pass"}

event: error
id: evt_010
data: {"code": "TOOL_TIMEOUT", "message": "Tool mcp:crm:search timed out after 30s", "retryable": false}

event: final_answer
id: evt_011
data: {"content": "I've found John Doe's record and sent a follow-up email.", "usage": {"total_tokens": 12500, "total_cost_usd": 0.42, "total_steps": 3}}

event: done
id: evt_012
data: {"session_state": "completed"}
```

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

**Request:**
```json
{
  "approval_id": "apr_789",
  "decision": "approve"
}
```

**Response:** `200 OK`
```json
{
  "data": {
    "approval_id": "apr_789",
    "decision": "approve",
    "session_state": "running"
  },
  "meta": { ... }
}
```

#### `POST /api/v1/sessions/{session_id}/reject` — Reject Tool Call

**Request:**
```json
{
  "approval_id": "apr_789",
  "decision": "reject",
  "reason": "Do not send email to this address"
}
```

**Response:** `200 OK`

> Rejection reason sẽ được inject vào context cho LLM biết tại sao tool bị reject.

---

## 5. System API

### 5.1 Health Checks

#### `GET /health` — Liveness

```json
{ "status": "ok" }
```

#### `GET /ready` — Readiness

```json
{
  "status": "ready",
  "checks": {
    "postgresql": "ok",
    "redis": "ok",
    "llm_provider": "ok"
  }
}
```

Nếu bất kỳ check nào fail:
```json
{
  "status": "not_ready",
  "checks": {
    "postgresql": "ok",
    "redis": "error",
    "llm_provider": "ok"
  }
}
```
HTTP Status: `503 Service Unavailable`

---

## 6. Error Response Reference

### 6.1 Error Response Schema

```python
class ErrorResponse(BaseModel):
    error: ErrorDetail
    meta: ResponseMeta

class ErrorDetail(BaseModel):
    code: str                        # machine-readable (see data-models.md Section 9.3)
    message: str                     # human-readable
    details: dict = {}               # structured context
```

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

```
HTTP/1.1 429 Too Many Requests
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1711443600
Retry-After: 45

{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Rate limit exceeded. Retry after 45 seconds.",
    "details": {
      "limit": 60,
      "window_seconds": 60,
      "retry_after_seconds": 45
    }
  }
}
```

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
