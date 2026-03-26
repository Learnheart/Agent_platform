# Thiết Kế Chi Tiết: Data Governance Module

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect
> **Parent:** [Architecture Overview](00-overview.md)

---

## 1. Tổng Quan

### 1.1 Scope

1. **Audit**: Consolidate mọi audit events vào một pipeline duy nhất (immutable, queryable)
2. **Retention**: Enforce data lifecycle policies — giữ, xóa, archive
3. **Classification**: Gắn nhãn sensitivity cho data (PII, confidential, internal, public)
4. **Cost Accounting**: Aggregate cost data từ mọi session/agent/tenant
5. **Lineage** (Phase 2): Track data flow xuyên suốt execution chain

### 1.2 Deployment Model

```
Phase 1 (Module):
  Executor ──function call──→ GovernanceModule ──→ PostgreSQL

Phase 2 (Service, nếu cần):
  Executor ──event bus──→ GovernanceService ──→ Dedicated DB
```

---

## 2. High-Level Diagram

```
┌──────────────────────────── DATA GOVERNANCE MODULE ──────────────────────────┐
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                        GOVERNANCE PORT (Interface)                      │ │
│  │                                                                         │ │
│  │  record_audit()  │  check_retention()  │  classify()  │  track_cost()  │ │
│  │                                                                         │ │
│  └───────────┬───────────────┬──────────────────┬──────────────┬───────────┘ │
│              │               │                  │              │             │
│    ┌─────────▼─────────┐   ┌▼──────────────┐  ┌▼────────────┐ │             │
│    │   AUDIT SINK      │   │  RETENTION    │  │  DATA       │ │             │
│    │                   │   │  ENGINE       │  │  CLASSIFIER │ │             │
│    │ ┌───────────────┐ │   │               │  │             │ │             │
│    │ │ Event         │ │   │ ┌───────────┐ │  │ ┌─────────┐ │ │             │
│    │ │ Normalizer    │ │   │ │ Policy    │ │  │ │ Rules   │ │ │             │
│    │ ├───────────────┤ │   │ │ Evaluator │ │  │ │ Engine  │ │ │             │
│    │ │ Write-Behind  │ │   │ ├───────────┤ │  │ ├─────────┤ │ │             │
│    │ │ Buffer        │ │   │ │ Cleanup   │ │  │ │ Tag     │ │ │             │
│    │ ├───────────────┤ │   │ │ Scheduler │ │  │ │ Manager │ │ │             │
│    │ │ Batch Writer  │ │   │ └───────────┘ │  │ └─────────┘ │ │             │
│    │ └───────────────┘ │   │               │  │             │ │             │
│    │                   │   │  Scope:        │  │  Scope:     │ │             │
│    │  Scope: Per-event │   │  Background    │  │  Per-event  │ │             │
│    │  Store: PostgreSQL│   │  job (cron)    │  │  In-memory  │ │             │
│    │  (append-only)    │   │  Store: PG     │  │  rules      │ │             │
│    └───────────────────┘   └───────────────┘  └─────────────┘ │             │
│                                                                │             │
│    ┌───────────────────┐   ┌───────────────────────────────┐  │             │
│    │   COST            │   │   DATA LINEAGE                │  │             │
│    │   AGGREGATOR      │   │   (Phase 2)                   │  │             │
│    │                   │   │                               │  │             │
│    │ ┌───────────────┐ │   │ ┌───────────────────────────┐ │  │             │
│    │ │ Per-session   │ │   │ │ Lineage Graph Builder     │ │  │             │
│    │ │ accumulator   │ │   │ │ (from OTel trace spans)   │ │  │             │
│    │ ├───────────────┤ │   │ ├───────────────────────────┤ │  │             │
│    │ │ Per-agent     │ │   │ │ Lineage Query Engine      │ │  │             │
│    │ │ rollup        │ │   │ │ "What produced this?"     │ │  │             │
│    │ ├───────────────┤ │   │ └───────────────────────────┘ │  │             │
│    │ │ Per-tenant    │ │   │                               │  │             │
│    │ │ rollup        │ │   │  Scope: Cross-session         │  │             │
│    │ └───────────────┘ │   │  Store: PG (graph model)      │  │             │
│    │                   │   │  Build from: OTel traces       │  │             │
│    │  Scope: Per-event │   └───────────────────────────────┘  │             │
│    │  + background job │                                      │             │
│    │  Store: Redis     │                                      │             │
│    │  (counters) + PG  │                                      │             │
│    │  (aggregates)     │                                      │             │
│    └───────────────────┘                                      │             │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Governance Port (Interface)

**GovernancePort** là interface chính (Python Protocol) cho toàn bộ Data Governance module. Mọi component trong hệ thống đều tương tác với governance thông qua port này.

- **Phase 1**: LocalGovernance — in-process, truy cập DB trực tiếp.
- **Phase 2**: RemoteGovernance — HTTP/gRPC client tới Governance Service.

Các method của GovernancePort:

**Audit:**

- **record_audit(event: AuditEvent) -> None** — Ghi nhận một audit event. Non-blocking (write-behind buffer). Được gọi bởi: Executor, Guardrails, Session Manager, Tool Manager, Memory Manager.
- **query_audit(filters: AuditFilters, limit: int = 100, offset: int = 0) -> AuditQueryResult** — Truy vấn audit trail. Được gọi bởi: Admin API, compliance tools.

**Retention:**

- **check_retention(data_ref: DataRef) -> RetentionDecision** — Kiểm tra xem data item nên giữ, archive, hay xóa. Được gọi bởi: cleanup jobs, memory lifecycle.
- **enforce_retention(scope: RetentionScope) -> RetentionReport** — Chạy enforcement cho một scope (tenant/agent/global). Được gọi bởi: scheduled background job.

**Classification:**

- **classify(content: str, context: ClassificationContext) -> DataClassification** — Phân loại data sensitivity. Lightweight, in-process. Được gọi bởi: Audit Sink (tag events), Memory Manager (tag memories).

**Cost:**

- **track_cost(event: CostEvent) -> None** — Track một cost event. Non-blocking. Được gọi bởi: LLM Gateway (per-call), Tool Runtime (per-call).
- **get_cost_report(scope: CostScope, time_range: tuple[datetime, datetime]) -> CostReport** — Lấy aggregated cost report. Được gọi bởi: Admin API, Budget Controller.

**Lineage (Phase 2):**

- **record_lineage(edge: LineageEdge) -> None** — Ghi nhận một data lineage edge. Được gọi bởi: Event Bus consumer.
- **query_lineage(data_ref: DataRef, direction: Literal["upstream", "downstream"], depth: int = 3) -> LineageGraph** — Trace data lineage upstream (what produced this?) hoặc downstream (what did this produce?).

---

## 4. Component Descriptions

### 4.1 Audit Sink

#### 4.1.1 Audit Event Model

**AuditEvent** — Unified audit event model cho mọi platform action.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str (UUID) | Generated by module | Unique identifier |
| timestamp | datetime | — | Event time (UTC) |
| tenant_id | str | — | Tenant scope |
| agent_id | str or None | None | Agent scope |
| session_id | str or None | None | Session scope |
| step_index | int or None | None | Step trong session |
| category | AuditCategory (Enum) | — | Loại event (xem bảng bên dưới) |
| action | str | — | Hành động cụ thể trong category |
| actor | AuditActor | — | Ai/cái gì triggered event |
| resource_type | str or None | None | "agent", "session", "tool", "memory", v.v. |
| resource_id | str or None | None | ID của resource bị ảnh hưởng |
| details | dict | {} | Category-specific details |
| sensitivity | DataSensitivity | — | "public", "internal", "confidential", "restricted" |
| outcome | Literal | — | "success", "failure", "blocked", hoặc "warning" |

**AuditCategory** (Enum):

| Value | Description |
|-------|-------------|
| AGENT_MANAGEMENT ("agent_management") | Create, update, delete agent |
| SESSION_LIFECYCLE ("session_lifecycle") | Create, start, pause, resume, complete, fail |
| LLM_CALL ("llm_call") | Every LLM API call |
| TOOL_CALL ("tool_call") | Every tool invocation |
| GUARDRAIL_CHECK ("guardrail_check") | Inbound/outbound/policy checks |
| AUTH_EVENT ("auth_event") | Login, token refresh, permission denied |
| MEMORY_ACCESS ("memory_access") | Store, search, delete memory |
| DATA_EXPORT ("data_export") | Data exported from platform |
| CONFIG_CHANGE ("config_change") | Agent config, guardrail rules, retention policies |
| RETENTION_ACTION ("retention_action") | Data archived or deleted by retention policy |

**AuditActor** — Mô tả actor đã trigger event:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| type | Literal | — | "user", "agent", "system", hoặc "scheduler" |
| id | str | — | user_id, agent_id, "system", "retention_scheduler" |
| ip_address | str or None | None | Cho user actions |

#### 4.1.2 Write-Behind Buffer

**AuditSink** — Non-blocking audit event writer. Sử dụng write-behind buffer để tránh thêm latency vào execution path.

**Constructor parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| buffer_size | int | 1000 | Max events trước khi forced flush |
| flush_interval_ms | int | 500 | Auto-flush mỗi 500ms |
| classifier | DataClassifier or None | None | Optional classifier instance |

**Methods:**

- **record(event: AuditEvent) -> None** — Ghi audit event theo quy trình: (1) Classify event sensitivity (nếu classifier enabled), (2) Normalize event (đảm bảo required fields, sanitize details), (3) Thêm vào in-memory buffer, (4) Nếu buffer đầy hoặc flush interval đến hạn thì batch write. Guarantee: events được durably written trong khoảng flush_interval_ms. Nếu process crash trước flush thì events trong buffer bị mất. Với critical events (auth, guardrail_block), dùng sync_record() thay thế.

- **sync_record(event: AuditEvent) -> None** — Synchronous write cho critical events. Bypass buffer, ghi trực tiếp vào PostgreSQL. Dùng hạn chế — thêm ~5ms latency.

- **flush() -> int** — Flush buffer vào PostgreSQL. Trả về số events đã ghi.

- **_batch_write(events: list[AuditEvent]) -> None** — Batch INSERT vào bảng audit_events. Sử dụng COPY cho high-throughput (>1000 events/batch). Fallback sang INSERT ... VALUES cho batches nhỏ hơn.

#### 4.1.3 Audit Storage

Bảng **audit_events** — lưu trữ audit trail:

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| id | UUID | gen_random_uuid() | Primary key |
| timestamp | TIMESTAMPTZ | NOW() | Thời gian event |
| tenant_id | TEXT NOT NULL | — | Tenant scope |
| agent_id | TEXT | NULL | Agent scope |
| session_id | TEXT | NULL | Session scope |
| step_index | INT | NULL | Step index |
| category | TEXT NOT NULL | — | Loại event |
| action | TEXT NOT NULL | — | Hành động cụ thể |
| actor_type | TEXT NOT NULL | — | Loại actor |
| actor_id | TEXT NOT NULL | — | Actor ID |
| actor_ip | INET | NULL | IP address (cho user actions) |
| resource_type | TEXT | NULL | Loại resource bị ảnh hưởng |
| resource_id | TEXT | NULL | ID resource |
| details | JSONB NOT NULL | '{}' | Chi tiết event |
| sensitivity | TEXT NOT NULL | 'internal' | Data sensitivity level |
| outcome | TEXT NOT NULL | — | Kết quả event |
| created_date | DATE | GENERATED ALWAYS AS (DATE(timestamp)) STORED | Hỗ trợ partitioning |

**Indexes:**

- idx_audit_tenant_time: (tenant_id, timestamp DESC) — Query theo tenant và thời gian
- idx_audit_session: (session_id, timestamp) WHERE session_id IS NOT NULL — Query theo session
- idx_audit_category: (category, timestamp DESC) — Query theo category
- idx_audit_outcome: (outcome, timestamp DESC) WHERE outcome != 'success' — Query failures/blocks

**Append-only enforcement:** Một trigger function (prevent_audit_modification) ngăn chặn mọi UPDATE và DELETE trên bảng audit_events. Bất kỳ attempt nào sẽ raise exception: "audit_events table is append-only: UPDATE and DELETE are not permitted".

**Row-level security:** Bật RLS trên bảng audit_events. Policy tenant_isolation đảm bảo mỗi tenant chỉ thấy data của mình, sử dụng current_setting('app.current_tenant').

#### 4.1.4 Audit Log Partitioning

Bảng audit_events được partition theo tháng (PARTITION BY RANGE trên cột timestamp) để tối ưu query performance và data retention.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID NOT NULL | gen_random_uuid(), part of composite PK |
| timestamp | TIMESTAMPTZ NOT NULL | Thời gian event, partition key |
| tenant_id | TEXT NOT NULL | Tenant scope |
| agent_id | TEXT | Agent scope |
| session_id | TEXT | Session scope |
| step_index | INT | Step index |
| category | TEXT NOT NULL | Loại event |
| action | TEXT NOT NULL | Hành động |
| actor_type | TEXT NOT NULL | Loại actor |
| actor_id | TEXT NOT NULL | Actor ID |
| resource_type | TEXT | Loại resource |
| resource_id | TEXT | Resource ID |
| details | JSONB | Default '{}' |
| sensitivity | TEXT NOT NULL | Default 'internal' |
| outcome | TEXT NOT NULL | Kết quả |

- PRIMARY KEY là composite: (id, timestamp)
- Partitions tự động tạo theo tháng, ví dụ: audit_events_2026_03 cho VALUES FROM ('2026-03-01') TO ('2026-04-01')
- Retention engine quản lý việc drop partitions cũ hơn retention_period

#### 4.1.5 Audit Query

**AuditFilters** — Bộ lọc cho audit query:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| tenant_id | str | — (Required) | Tenant cần query |
| session_id | str or None | None | Lọc theo session |
| agent_id | str or None | None | Lọc theo agent |
| categories | list[AuditCategory] or None | None | Lọc theo categories |
| outcomes | list[str] or None | None | Ví dụ: ["failure", "blocked"] |
| time_range | tuple[datetime, datetime] or None | None | Khoảng thời gian |
| actor_id | str or None | None | Lọc theo actor |
| resource_type | str or None | None | Lọc theo resource type |
| sensitivity_min | DataSensitivity or None | None | Ngưỡng tối thiểu, ví dụ "confidential" = confidential + restricted |

**AuditQueryEngine** — Engine truy vấn audit trail:

- **query(filters: AuditFilters, limit: int = 100, offset: int = 0, order: Literal["asc", "desc"] = "desc") -> AuditQueryResult** — Truy vấn audit trail với filters. Trả về paginated results kèm total count. Các query phổ biến: "All failed guardrail checks for agent X in last 24h", "All tool calls in session Y", "All config changes by user Z", "All data export events with sensitivity >= confidential".

- **get_session_timeline(session_id: str) -> list[AuditEvent]** — Audit timeline đầy đủ cho một session — sắp xếp theo thứ tự thời gian. Bao gồm: lifecycle events, LLM calls, tool calls, guardrail checks.

---

### 4.2 Retention Engine

#### 4.2.1 Retention Policy Model

**RetentionPolicy** — Định nghĩa data được giữ bao lâu và xử lý sau khi hết hạn:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | Policy identifier |
| tenant_id | str | — | "platform" cho global policies |
| name | str | — | Tên policy |
| description | str | — | Mô tả |
| data_type | RetentionDataType (Enum) | — | Loại data áp dụng |
| scope | RetentionScope | — | tenant-wide, per-agent, per-sensitivity |
| retain_days | int | — | Giữ data N ngày |
| archive_before_delete | bool | True | Di chuyển sang cold storage trước khi xóa |
| archive_storage | str | "s3" | "s3", "gcs", hoặc "none" |
| applies_to_sensitivity | list[DataSensitivity] or None | None | Chỉ áp dụng cho certain classifications |
| enabled | bool | True | Trạng thái bật/tắt |
| last_run_at | datetime or None | None | Lần chạy gần nhất |
| next_run_at | datetime or None | None | Lần chạy tiếp theo |

**RetentionDataType** (Enum):

| Value | Description |
|-------|-------------|
| SESSION_DATA ("session_data") | Conversation history, checkpoints |
| AUDIT_EVENTS ("audit_events") | Audit trail records |
| TRACE_SPANS ("trace_spans") | OpenTelemetry traces |
| LONG_TERM_MEMORY ("long_term_memory") | Agent memories (pgvector) |
| COST_RECORDS ("cost_records") | Cost aggregation data |
| TOOL_LOGS ("tool_logs") | Tool invocation logs |

#### 4.2.2 Default Retention Policies (Platform)

| Data Type | Default Retention | Archive |
|---|---|---|
| Session data (hot, Redis) | Session + 1h | No (ephemeral) |
| Session data (warm, PG) | 90 days | Yes (S3) |
| Audit events | 365 days | Yes (S3) |
| Trace spans | 30 days | No |
| Long-term memories | Per-agent config | Yes (S3) |
| Cost records | Indefinite | No |
| Tool invocation logs | 30 days | No |

#### 4.2.3 Retention Scheduler

**RetentionScheduler** — Background job chạy retention policies theo schedule. Default: daily at 02:00 UTC.

**Methods:**

- **run() -> RetentionReport** — Quy trình: (1) Load tất cả enabled retention policies, (2) Với mỗi policy: (a) query data matching policy scope + age, (b) nếu archive_before_delete thì export sang cold storage, (c) delete expired data, (d) update policy.last_run_at, (3) Record audit event (RETENTION_ACTION), (4) Return report với counts.

- **run_for_tenant(tenant_id: str) -> RetentionReport** — Chạy retention cho một tenant cụ thể (admin-triggered).

- **dry_run(policy_id: str) -> RetentionReport** — Preview kết quả mà không thực sự xóa data.

**RetentionReport** — Kết quả chạy retention:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| policy_id | str | — | ID policy đã chạy |
| run_at | datetime | — | Thời điểm chạy |
| records_scanned | int | — | Số records đã quét |
| records_archived | int | — | Số records đã archive |
| records_deleted | int | — | Số records đã xóa |
| storage_freed_bytes | int | — | Dung lượng đã giải phóng |
| errors | list[str] | — | Danh sách lỗi (nếu có) |
| duration_seconds | float | — | Thời gian thực thi |

#### 4.2.4 Partition Drop Strategy

Retention engine sử dụng DROP PARTITION thay vì DELETE rows cho audit_events — hiệu quả O(1) so với row-by-row DELETE. Retention engine kiểm tra tuổi partition so với retention_period, rồi DROP TABLE partition cũ (ví dụ: DROP TABLE IF EXISTS audit_events_2025_01).

**PartitionRetentionStrategy** — Cho partitioned tables (audit_events), drop toàn bộ partition thay vì DELETE WHERE timestamp < cutoff.

**Methods:**

- **cleanup_expired_partitions(table: str, retention_days: int) -> list[str]** — Quy trình: (1) List tất cả partitions cho table, (2) Xác định partitions cũ hơn retention_days, (3) Nếu archive_before_delete thì pg_dump partition sang S3, (4) DROP TABLE partition_name, (5) Return list partition names đã drop.

- **ensure_future_partitions(table: str, months_ahead: int = 3) -> list[str]** — Pre-create partitions cho các tháng sắp tới. Chạy như một phần của retention scheduler.

---

### 4.3 Data Classifier

#### 4.3.1 Classification Model

**DataSensitivity** (Enum):

| Value | Description |
|-------|-------------|
| PUBLIC ("public") | Dữ liệu công khai |
| INTERNAL ("internal") | Dữ liệu nội bộ |
| CONFIDENTIAL ("confidential") | Dữ liệu bí mật |
| RESTRICTED ("restricted") | PII, credentials, regulated data |

**DataClassification** — Kết quả classification:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| sensitivity | DataSensitivity | — | Mức độ nhạy cảm |
| tags | list[str] | — | Ví dụ: ["pii", "credential", "financial", "health"] |
| confidence | float | — | 0.0 - 1.0 |
| classified_by | str | — | Ví dụ: "rule:email_pattern", "rule:api_key_pattern" |

**ClassificationContext** — Context cho classification:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| data_type | str | — | "user_message", "llm_response", "tool_result", "memory" |
| tenant_id | str | — | Tenant scope |
| agent_id | str or None | None | Agent scope |

#### 4.3.2 Classification Rules (Phase 1)

**DataClassifier** — Rule-based data classifier. Nhanh, deterministic, không phụ thuộc external service. Phase 2 sẽ thêm ML classifier cho nuanced content classification.

**Constructor:** Nhận danh sách ClassificationRule.

**Methods:**

- **classify(content: str, context: ClassificationContext) -> DataClassification** — Áp dụng rules theo thứ tự priority. Sensitivity cao nhất thắng. Default rules (built-in): (1) RESTRICTED nếu match: email, phone, SSN, credit card patterns, (2) RESTRICTED nếu match: API key patterns (sk-*, AKIA*, v.v.), (3) CONFIDENTIAL nếu match: financial amounts, account numbers, (4) CONFIDENTIAL nếu context.data_type == "tool_result" và tool là DB/API, (5) INTERNAL cho các trường hợp còn lại.

- **classify_batch(items: list[tuple[str, ClassificationContext]]) -> list[DataClassification]** — Batch classification cho hiệu quả.

**ClassificationRule** — Định nghĩa một rule phân loại:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | Rule identifier |
| name | str | — | Tên rule |
| priority | int | — | Lower = evaluated first |
| pattern | str or None | None | Regex pattern để match trong content |
| context_match | dict or None | None | Match trên context fields |
| sensitivity | DataSensitivity | — | Classification nếu rule match |
| tags | list[str] | — | Tags cần thêm |
| enabled | bool | True | Trạng thái bật/tắt |

---

### 4.4 Cost Aggregator

**CostAggregator** — Accumulates cost events và cung cấp aggregated reports. Real-time tracking qua Redis counters, durable storage trong PostgreSQL.

**Methods:**

- **track(event: CostEvent) -> None** — Quy trình: (1) Increment Redis counters (atomic, fast): session:{id}:cost (total session cost), agent:{id}:cost:{date} (daily agent cost), tenant:{id}:cost:{date} (daily tenant cost). (2) Append vào cost_events buffer (batch write sang PG).

- **get_session_cost(session_id: str) -> SessionCost** — Real-time session cost từ Redis.

- **get_report(scope: CostScope, time_range: tuple[datetime, datetime], group_by: Literal["day", "week", "month"] = "day") -> CostReport** — Aggregated cost report từ PostgreSQL. Supports breakdown by: model, tool, agent, tenant.

**CostEvent** — Mô tả một cost event:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| timestamp | datetime | — | Thời gian event |
| tenant_id | str | — | Tenant scope |
| agent_id | str | — | Agent scope |
| session_id | str | — | Session scope |
| step_index | int | — | Step trong session |
| event_type | Literal | — | "llm_call", "tool_call", hoặc "embedding" |
| provider | str or None | None | "anthropic", "openai" (LLM-specific) |
| model | str or None | None | Ví dụ: "claude-sonnet-4-5-20250514" (LLM-specific) |
| input_tokens | int or None | None | Số input tokens (LLM-specific) |
| output_tokens | int or None | None | Số output tokens (LLM-specific) |
| tool_name | str or None | None | Tên tool (Tool-specific) |
| cost_usd | float | — | Chi phí đã tính (USD) |

**CostReport** — Báo cáo chi phí aggregated:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| scope | CostScope | — | Phạm vi báo cáo |
| time_range | tuple[datetime, datetime] | — | Khoảng thời gian |
| total_cost_usd | float | — | Tổng chi phí USD |
| total_llm_calls | int | — | Tổng số LLM calls |
| total_tool_calls | int | — | Tổng số tool calls |
| total_tokens | int | — | Tổng tokens |
| breakdown | list[CostBreakdownItem] | — | Chi tiết theo model, tool, agent, v.v. |

**Cost Storage:**

Bảng **cost_events**:

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| id | UUID | gen_random_uuid() | Primary key |
| timestamp | TIMESTAMPTZ NOT NULL | NOW() | Thời gian event |
| tenant_id | TEXT NOT NULL | — | Tenant scope |
| agent_id | TEXT NOT NULL | — | Agent scope |
| session_id | TEXT NOT NULL | — | Session scope |
| step_index | INT NOT NULL | — | Step index |
| event_type | TEXT NOT NULL | — | Loại event |
| provider | TEXT | NULL | LLM provider |
| model | TEXT | NULL | Model name |
| input_tokens | INT | NULL | Input tokens |
| output_tokens | INT | NULL | Output tokens |
| tool_name | TEXT | NULL | Tool name |
| cost_usd | NUMERIC(10, 6) NOT NULL | — | Chi phí USD |

Bảng **cost_daily_aggregates** — Daily aggregation table (materialized by background job):

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| date | DATE NOT NULL | — | Ngày aggregate (part of composite PK) |
| tenant_id | TEXT NOT NULL | — | Tenant scope (part of composite PK) |
| agent_id | TEXT | NULL | Agent scope (part of composite PK) |
| provider | TEXT | NULL | LLM provider (part of composite PK) |
| model | TEXT | NULL | Model name (part of composite PK) |
| total_cost_usd | NUMERIC(12, 6) | — | Tổng chi phí ngày |
| total_llm_calls | INT | — | Tổng LLM calls |
| total_tool_calls | INT | — | Tổng tool calls |
| total_input_tokens | BIGINT | — | Tổng input tokens |
| total_output_tokens | BIGINT | — | Tổng output tokens |

- PRIMARY KEY: (date, tenant_id, agent_id, provider, model)

---

### 4.5 Data Lineage (Phase 2)

#### 4.5.1 Lineage Model

**LineageNode** — Một data artifact trong lineage graph:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | Node identifier |
| type | Literal | — | "user_input", "llm_output", "tool_input", "tool_output", "memory_entry", hoặc "agent_output" |
| session_id | str | — | Session scope |
| step_index | int | — | Step trong session |
| content_hash | str | — | Hash của content (không phải content gốc, vì privacy) |
| sensitivity | DataSensitivity | — | Mức nhạy cảm |
| timestamp | datetime | — | Thời điểm tạo |

**LineageEdge** — Một transformation hoặc dependency giữa data artifacts:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| source_id | str | — | LineageNode đã produce/influence |
| target_id | str | — | LineageNode bị produce/influence |
| relationship | Literal | — | "produced_by", "derived_from", "informed_by", "summarized_from", hoặc "approved_by" |
| session_id | str | — | Session scope |
| step_index | int | — | Step trong session |
| metadata | dict | — | Transformation details |

Các loại relationship: "produced_by" (LLM output produced by LLM call with this input), "derived_from" (Tool output derived from tool input), "informed_by" (LLM call informed by memory retrieval), "summarized_from" (Summary derived from conversation history), "approved_by" (Action approved by HITL).

**LineageGraph** — Subgraph kết quả query lineage:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| nodes | list[LineageNode] | — | Danh sách nodes |
| edges | list[LineageEdge] | — | Danh sách edges |
| root | str | — | Starting node ID |
| depth | int | — | Số hops từ root |

#### 4.5.2 Lineage Builder (Phase 2)

**LineageBuilder** — Builds lineage graph từ OTel traces và audit events. Chạy như background consumer của Event Bus.

**Methods:**

- **process_step_events(session_id: str, step_index: int, events: list[AgentEvent]) -> list[LineageEdge]** — Từ events của một completed step, extract lineage edges: (1) user_input -> (informed) -> llm_output, (2) memory_entry -> (informed_by) -> llm_output (nếu RAG was used), (3) llm_output -> (produced) -> tool_input (nếu tool_call), (4) tool_input -> (derived_from) -> tool_output, (5) tool_output -> (informed) -> next llm_output, (6) llm_output -> (produced) -> agent_output (nếu final_answer).

- **query_upstream(node_id: str, depth: int = 3) -> LineageGraph** — Data nào đã produce node này? Walk backwards qua graph.

- **query_downstream(node_id: str, depth: int = 3) -> LineageGraph** — Node này đã produce data nào? Walk forwards qua graph.

---

## 5. Integration Points

```
┌──────────────┐
│  Executor    │──record_audit(LLM_CALL)──────────┐
│              │──record_audit(TOOL_CALL)──────────┤
│              │──track_cost(llm/tool)─────────────┤
└──────────────┘                                    │
                                                    ▼
┌──────────────┐                           ┌───────────────┐
│  Guardrails  │──record_audit(GUARDRAIL)──│               │
│              │──classify(user_input)──────│  Governance   │
└──────────────┘                           │  Module       │
                                           │               │
┌──────────────┐                           │ ┌───────────┐ │
│  Session     │──record_audit(LIFECYCLE)──│ │ Audit Sink│ │
│  Manager     │                           │ │ Retention │ │
└──────────────┘                           │ │ Classifier│ │
                                           │ │ Cost Agg  │ │
┌──────────────┐                           │ └───────────┘ │
│  Memory      │──record_audit(MEMORY)─────│               │
│  Manager     │──classify(memory_content)─│               │
│              │──check_retention()────────│               │
└──────────────┘                           │               │
                                           │               │
┌──────────────┐                           │               │
│  Admin API   │──query_audit()────────────│               │
│              │──get_cost_report()────────│               │
│              │──enforce_retention()───────│               │
└──────────────┘                           └───────────────┘
```

### 5.1 Event Bus Integration

**Direct call** (real-time, trong execution path):

- governance.record_audit(event) — Non-blocking (write-behind)
- governance.track_cost(cost_event) — Non-blocking (Redis counter)
- governance.classify(content, ctx) — Sync, fast (<2ms)

**Event Bus consumer** (background, async):

**GovernanceEventConsumer** — Xử lý events từ Event Bus:

- Method **on_event(event: AgentEvent) -> None** xử lý theo event type:
  - Khi "session_completed": gọi lineage_builder.process_session(event.session_id) và cost_aggregator.rollup_session(event.session_id)
  - Khi "retention_schedule": gọi retention_scheduler.run()

---

## 6. Sequence Diagrams

### 6.1 Audit Recording During Execution Step

```
Executor         Guardrails       LLM GW          Governance          PostgreSQL
 │                  │                │                │                    │
 │──inbound check──→│                │                │                    │
 │                  │──record_audit──────────────────→│                    │
 │                  │  {GUARDRAIL,                    │──buffer──→         │
 │                  │   schema_valid,                 │  (in-memory)       │
 │                  │   outcome:pass}                 │                    │
 │◄──pass───────────│                │                │                    │
 │                  │                │                │                    │
 │──chat()─────────────────────────→│                │                    │
 │◄──response──────────────────────│                │                    │
 │                  │                │                │                    │
 │──record_audit───────────────────────────────────→│                    │
 │  {LLM_CALL, model:claude,                        │──buffer──→         │
 │   tokens:2400, cost:0.012}                        │                    │
 │                  │                │                │                    │
 │──track_cost─────────────────────────────────────→│                    │
 │  {llm_call, 0.012 USD}                           │──Redis INCR──→     │
 │                  │                │                │                    │
 │  ... (more execution) ...         │                │                    │
 │                  │                │                │                    │
 │                  │                │                │──flush timer──→    │
 │                  │                │                │  (every 500ms)     │
 │                  │                │                │──batch INSERT──────→│
 │                  │                │                │  (5 audit events)  │
 │                  │                │                │◄──ok───────────────│
```

### 6.2 Retention Enforcement (Background Job)

```
Scheduler       Governance         PostgreSQL          S3 (Archive)      Audit
 │                 │                   │                    │               │
 │──run()─────────→│                   │                    │               │
 │                 │                   │                    │               │
 │                 │──load policies───→│                    │               │
 │                 │◄──[3 policies]────│                    │               │
 │                 │                   │                    │               │
 │                 │ ┌─ Policy: session_data (90 days) ─┐   │               │
 │                 │ │                                   │   │               │
 │                 │ │──SELECT expired──→│               │   │               │
 │                 │ │◄──[42 sessions]──│               │   │               │
 │                 │ │                                   │   │               │
 │                 │ │──archive (export)────────────────→│   │               │
 │                 │ │◄──archived────────────────────────│   │               │
 │                 │ │                                   │   │               │
 │                 │ │──DELETE expired──→│               │   │               │
 │                 │ │◄──42 deleted─────│               │   │               │
 │                 │ │                                   │   │               │
 │                 │ └───────────────────────────────────┘   │               │
 │                 │                                         │               │
 │                 │ ┌─ Policy: audit_events (365 days) ─┐   │               │
 │                 │ │                                    │   │               │
 │                 │ │──DROP PARTITION expired────→│      │   │               │
 │                 │ │◄──dropped──────────────────│      │   │               │
 │                 │ │                                    │   │               │
 │                 │ └────────────────────────────────────┘   │               │
 │                 │                                         │               │
 │                 │ ┌─ Policy: trace_spans (30 days) ──┐   │               │
 │                 │ │  ... (similar flow, no archive) ..│   │               │
 │                 │ └───────────────────────────────────┘   │               │
 │                 │                                         │               │
 │                 │──record_audit(RETENTION_ACTION)─────────────────────────→│
 │                 │  {archived:42, deleted:108, freed:2.4GB}                │
 │                 │                                         │               │
 │◄──report────────│                                         │               │
 │  {scanned:500,  │                                         │               │
 │   archived:42,  │                                         │               │
 │   deleted:108}  │                                         │               │
```

### 6.3 Data Classification in Execution Flow

```
Executor         Memory Mgr       Governance        Audit Sink
 │                  │                │                  │
 │  [LLM returned final_answer]     │                  │
 │                  │                │                  │
 │──classify()─────────────────────→│                  │
 │  content: "Your account         │                  │
 │   #1234 balance is $5,430"      │                  │
 │  context: {data_type:           │                  │
 │   "llm_response"}               │                  │
 │                  │                │                  │
 │                  │              ┌─▼──────────────┐  │
 │                  │              │ Rule matching:  │  │
 │                  │              │ ✓ account #     │  │
 │                  │              │   → CONFIDENTIAL│  │
 │                  │              │   tag: financial│  │
 │                  │              │ ✓ dollar amount │  │
 │                  │              │   → CONFIDENTIAL│  │
 │                  │              │   tag: financial│  │
 │                  │              │                 │  │
 │                  │              │ Result:         │  │
 │                  │              │ CONFIDENTIAL    │  │
 │                  │              │ tags: [financial]│  │
 │                  │              └─┬──────────────┘  │
 │                  │                │                  │
 │◄──{CONFIDENTIAL,─────────────────│                  │
 │    [financial]}  │                │                  │
 │                  │                │                  │
 │──record_audit(LLM_CALL,          │                  │
 │   sensitivity:CONFIDENTIAL)──────────────────────→│
```

---

## 7. Configuration Model

### 7.1 Platform-Level Governance Config

**GovernanceConfig** — Platform-wide governance configuration, bao gồm 4 sub-config:

| Field | Type | Description |
|-------|------|-------------|
| audit | AuditConfig | Cấu hình audit |
| retention | RetentionConfig | Cấu hình retention |
| classification | ClassificationConfig | Cấu hình classification |
| cost | CostConfig | Cấu hình cost tracking |

**AuditConfig:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | True | Bật/tắt audit |
| buffer_size | int | 1000 | Số events trước khi forced flush |
| flush_interval_ms | int | 500 | Auto-flush interval (ms) |
| sync_categories | list[str] | ["auth_event", "config_change"] | Categories bypass buffer (ghi đồng bộ) |

**RetentionConfig:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | True | Bật/tắt retention |
| schedule_cron | str | "0 2 * * *" | Daily at 02:00 UTC |
| default_policies | list[RetentionPolicy] | [] | Danh sách policies mặc định |
| archive_storage | Literal["s3", "gcs", "none"] | "s3" | Nơi archive |
| archive_bucket | str | "" | Bucket name |
| dry_run | bool | False | Log only, không xóa |

**ClassificationConfig:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | True | Bật/tắt classification |
| default_sensitivity | DataSensitivity | INTERNAL | Mức nhạy cảm mặc định |
| custom_rules | list[ClassificationRule] | [] | Custom classification rules |
| classify_audit_events | bool | True | Tự động classify audit event details |
| classify_memory_entries | bool | True | Tự động classify stored memories |

**CostConfig:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | True | Bật/tắt cost tracking |
| aggregation_interval_minutes | int | 60 | Tần suất rollup (phút) |
| alert_thresholds | dict[str, float] | {"session_usd": 10.0, "tenant_daily_usd": 1000.0} | Ngưỡng cảnh báo: alert nếu single session > $10, alert nếu tenant daily spend > $1000 |

### 7.2 Tenant-Level Overrides

Tenant có thể override governance config ở cấp tenant. Cấu trúc override bao gồm:

- **tenant_id**: ID của tenant (ví dụ: "acme-corp")
- **governance.retention**: Override retention settings
  - session_data_days: Số ngày giữ session data (ví dụ: 180)
  - audit_events_days: Số ngày giữ audit events (ví dụ: 730)
  - archive_before_delete: Có archive trước khi xóa không (ví dụ: true)
- **governance.classification**: Override classification settings
  - custom_rules: Danh sách custom rules, mỗi rule bao gồm name (ví dụ: "acme_internal_ids"), pattern (regex, ví dụ: "ACME-\\d{6}"), sensitivity (ví dụ: "confidential"), và tags (ví dụ: ["internal_id"])
- **governance.cost**: Override cost settings
  - alert_thresholds: Override ngưỡng cảnh báo, ví dụ session_usd: 25.0, tenant_daily_usd: 5000.0

---

## 8. Tech Stack

| Component | Technology | Phase |
|-----------|-----------|-------|
| **Audit storage** | PostgreSQL (partitioned, append-only) | 1 |
| **Audit buffer** | In-memory buffer (asyncio.Queue) | 1 |
| **Cost counters (real-time)** | Redis (INCR, HSET) | 1 |
| **Cost aggregates** | PostgreSQL (materialized table) | 1 |
| **Classification engine** | Regex + custom rules (Python) | 1 |
| **Classification ML** | Fine-tuned classifier (Phase 2) | 2 |
| **Retention scheduler** | asyncio background task / APScheduler | 1 |
| **Archive storage** | S3 / GCS (via boto3/google-cloud-storage) | 1 |
| **Lineage storage** | PostgreSQL (adjacency list model) | 2 |
| **Lineage query** | Recursive CTE (PostgreSQL) | 2 |
| **Governance interface** | Python Protocol (ABC) | 1 |

---

## 9. Performance Targets

| Operation | Target Latency | Notes |
|-----------|---------------|-------|
| record_audit (buffered) | < 0.1ms | In-memory append, non-blocking |
| sync_record (critical) | < 5ms | Direct PostgreSQL INSERT |
| flush buffer (batch) | < 20ms | Batch INSERT (up to 1000 events) |
| classify (rule-based) | < 2ms | Regex matching, in-memory |
| track_cost | < 1ms | Redis INCR |
| query_audit (indexed) | < 50ms | PostgreSQL with proper indexes |
| get_session_timeline | < 30ms | Single session, indexed by session_id |
| get_cost_report (daily) | < 100ms | Pre-aggregated table |
| retention_run (per policy) | < 60s | Depends on data volume, batched |
| lineage query (depth 3) | < 200ms | Recursive CTE (Phase 2) |

Overhead constraint: Governance module < 1ms total latency on execution hot path (non-blocking buffer + async writes).

---

## 10. Error Handling

| Scenario | Behavior |
|----------|----------|
| Audit buffer flush fails (PG down) | Retry with backoff (3x). If persistent: log to local file as fallback. Never block execution. |
| Redis cost counter unavailable | Use in-memory counter (stale OK for ~1 min). Reconcile with PG aggregates on recovery. |
| Classification rule error | Skip rule, log warning, use default sensitivity. Never block on broken rule. |
| Retention job fails mid-run | Record partial progress. Next run picks up where it left off (idempotent). |
| Retention archive upload fails | Skip deletion for affected records. Retry archive on next run. |
| Audit query timeout | Return partial results with `is_truncated: true` flag. |

---

## 11. Phase Allocation

| Feature | Phase 1 | Phase 2 | Phase 3 |
|---------|---------|---------|---------|
| **Audit Sink** (buffer + batch write) | ✅ | | |
| **Audit Query** (filters, timeline) | ✅ | | |
| **Retention Engine** (policies + scheduler) | ✅ | | |
| **Data Classification** (rule-based) | ✅ | | |
| **Cost Aggregation** (real-time + reports) | ✅ | | |
| **Audit API** (/audit endpoints) | ✅ | | |
| **Governance Port** (interface, local impl) | ✅ | | |
| **Data Lineage** (graph builder + query) | | ✅ | |
| **ML Classification** (fine-tuned model) | | ✅ | |
| **Governance Service** (extract to service) | | ✅ (if needed) | |
| **Compliance Reporting** (GDPR, SOC2) | | ✅ | |
| **Cross-tenant Analytics** | | | ✅ |
| **Data Residency** (geo-aware storage) | | | ✅ |
