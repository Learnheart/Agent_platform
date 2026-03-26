# Thiết Kế Chi Tiết: Memory System

> **Phiên bản:** 2.0
> **Ngày tạo:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect
> **Parent:** [Architecture Overview](00-overview.md)

---

## 1. Phase Roadmap

| Phase | Memory Layers |
|-------|---------------|
| **Phase 1** | Short-term Memory, Working Memory |
| **Phase 2** | Long-term Memory (vector store, RAG, embedding, knowledge base), Shared Memory |
| **Phase 3** | Episodic Memory |

---

## 2. High-Level Diagram

```
┌──────────────────────────────── MEMORY SYSTEM ─────────────────────────────────────┐
│                                                                                     │
│                              ┌──────────────────┐                                  │
│                              │  Memory Manager  │                                  │
│                              │  (Orchestrator)  │                                  │
│                              └────────┬─────────┘                                  │
│                                       │                                             │
│  ┌─── PHASE 1 ────────────────────────┼──────────────────────────────────────────┐ │
│  │            ┌───────────────────────┼───────────────────────┐                  │ │
│  │            │                       │                       │                  │ │
│  │   ┌────────▼─────────┐   ┌────────▼─────────┐            │                  │ │
│  │   │  SHORT-TERM      │   │  WORKING         │            │                  │ │
│  │   │  MEMORY          │   │  MEMORY          │            │                  │ │
│  │   │                  │   │                  │            │                  │ │
│  │   │ ┌──────────────┐ │   │ ┌──────────────┐ │            │                  │ │
│  │   │ │ Context      │ │   │ │ Plan State   │ │            │                  │ │
│  │   │ │ Window Mgr   │ │   │ │              │ │            │                  │ │
│  │   │ ├──────────────┤ │   │ ├──────────────┤ │            │                  │ │
│  │   │ │ Conversation │ │   │ │ Accumulated  │ │            │                  │ │
│  │   │ │ Buffer       │ │   │ │ Artifacts    │ │            │                  │ │
│  │   │ ├──────────────┤ │   │ ├──────────────┤ │            │                  │ │
│  │   │ │ Summarizer   │ │   │ │ Scratchpad   │ │            │                  │ │
│  │   │ └──────────────┘ │   │ └──────────────┘ │            │                  │ │
│  │   │                  │   │                  │            │                  │ │
│  │   │  Scope: Session  │   │  Scope: Session  │            │                  │ │
│  │   │  Store: Redis    │   │  Store: Redis    │            │                  │ │
│  │   └──────────────────┘   └──────────────────┘            │                  │ │
│  └───────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                     │
│  ┌─── PHASE 2 (disabled) ───────────────────────────────────────────────────────┐  │
│  │   ┌──────────────────┐    ┌──────────────────┐                               │  │
│  │   │  LONG-TERM       │    │  SHARED          │                               │  │
│  │   │  MEMORY          │    │  MEMORY          │                               │  │
│  │   │                  │    │                  │                               │  │
│  │   │  Store: PG+      │    │  Store: Redis    │                               │  │
│  │   │  pgvector        │    │  Scope: Multi-   │                               │  │
│  │   │  Scope: Agent/   │    │  agent session   │                               │  │
│  │   │  Tenant          │    │                  │                               │  │
│  │   └──────────────────┘    └──────────────────┘                               │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                     │
│  ┌─── PHASE 3 (disabled) ───────────────────────────────────────────────────────┐  │
│  │   ┌──────────────────┐                                                       │  │
│  │   │  EPISODIC        │                                                       │  │
│  │   │  MEMORY          │                                                       │  │
│  │   │                  │                                                       │  │
│  │   │  Store: PG+      │                                                       │  │
│  │   │  pgvector        │                                                       │  │
│  │   │  Scope: Agent-   │                                                       │  │
│  │   │  type            │                                                       │  │
│  │   └──────────────────┘                                                       │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                     │
│     ┌──────────────────────────────────────────────────────────────────────────┐   │
│     │                      MEMORY ISOLATION LAYER                               │   │
│     │                                                                           │   │
│     │  Tenant A namespace ─────── Tenant B namespace ─────── Tenant C namespace │   │
│     │  (complete isolation)       (complete isolation)       (complete isolation)│   │
│     └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Descriptions

### 3.1 Memory Manager (Orchestrator)

**MemoryManager** orchestrates all memory operations across layers. Each method enforces tenant isolation before delegating to the appropriate memory layer.

**Constructor dependencies:**

| Dependency | Type | Phase |
|------------|------|-------|
| short_term | ShortTermMemory | Phase 1 |
| long_term | LongTermMemory hoặc None | Phase 2 |
| working | WorkingMemory | Phase 1 |
| episodic | EpisodicMemory hoặc None | Phase 3 |
| shared | SharedMemory hoặc None | Phase 2 |

**Methods:**

| Method | Parameters | Return Type | Description |
|--------|-----------|-------------|-------------|
| build_context | session_id: str, agent_config: AgentConfig | ContextPayload | Được Executor gọi trước mỗi LLM call. Assembles full context gồm: (1) System prompt từ agent config, (2) Working memory (plan state, artifacts), (3) Short-term memory (recent conversation, managed by strategy). |
| update | session_id: str, messages: list[Message], artifacts: dict hoặc None | None | Được Executor gọi sau mỗi step. Cập nhật short-term buffer và working memory. |
| store | tenant_id: str, agent_id: str, content: str, metadata: dict | str | Phase 2: Lưu nội dung vào long-term memory. Trả về memory ID. |
| search | tenant_id: str, agent_id: str, query: str, top_k: int (default 5) | list[MemoryEntry] | Phase 2: Tìm kiếm trong long-term memory. |
| delete | tenant_id: str, memory_id: str | bool | Phase 2: Xoá memory entry. |

---

### 3.2 Short-Term Memory (Phase 1)

**Scope:** Per-session.
**Store:** Redis.

#### 3.2.1 Context Window Manager

**ContextWindowManager** chịu trách nhiệm tối ưu danh sách messages sao cho vừa với token budget của model.

| Method | Parameters | Return Type | Description |
|--------|-----------|-------------|-------------|
| build | full_history: list[Message], system_prompt: str, injected_context: str hoặc None (working memory), tool_schemas: list[dict], strategy: ContextStrategy, max_tokens: int | list[Message] | Trả về danh sách messages đã tối ưu nằm trong giới hạn max_tokens. Luôn giữ system_prompt + tool_schemas, các messages còn lại được chọn theo strategy. |

**Strategies:**

| Strategy | Hoạt động | Trade-off |
|----------|-----------|-----------|
| **Sliding Window** | Giữ N messages gần nhất | Đơn giản, mất context cũ |
| **Summarize + Recent** (default) | Summarize messages cũ thành 1 message, giữ N messages gần nhất | Giữ context, tốn 1 LLM call |
| **Selective Retention** | Giữ system + first user msg + messages flagged "important" + recent | Tiết kiệm, cần logic flagging |
| **Token-Aware Trim** | Cắt messages từ giữa, ưu tiên giữ đầu + cuối | Tự động, có thể mất context quan trọng |

#### 3.2.2 Conversation Buffer

**ConversationBuffer** lưu trữ toàn bộ lịch sử hội thoại trong Redis, không bị ảnh hưởng bởi context trimming.

| Method | Parameters | Return Type | Description |
|--------|-----------|-------------|-------------|
| append | session_id: str, message: Message | None | Thêm message vào cuối buffer. |
| get_all | session_id: str | list[Message] | Lấy toàn bộ lịch sử hội thoại. |
| get_recent | session_id: str, n: int | list[Message] | Lấy N messages gần nhất. |
| get_token_count | session_id: str | int | Trả về tổng số tokens của toàn bộ lịch sử. |

**Storage:** Redis — key format: `session:{session_id}:messages` (list type)

#### 3.2.3 Summarizer

**ConversationSummarizer** tạo tóm tắt hội thoại theo phương thức incremental.

| Method | Parameters | Return Type | Description |
|--------|-----------|-------------|-------------|
| summarize | messages: list[Message], existing_summary: str hoặc None, model_config: ModelConfig | str | Nếu existing_summary được cung cấp, summarize existing_summary + new_messages thành updated_summary. Target: summary luôn < 500 tokens bất kể độ dài input. |

**Trigger logic:** Khi token count của lịch sử hội thoại vượt quá 70% của context_window_budget, hệ thống sẽ tự động summarize các messages cũ nhất (giữ lại N messages gần nhất), thay thế các messages cũ bằng 1 summary message, sau đó tiếp tục execution.

---

### 3.3 Working Memory (Phase 1)

**Scope:** Per-session.
**Store:** Redis Hash — key: `session:{session_id}:working`

**WorkingMemory** lưu trữ trạng thái làm việc trong phiên (session-scoped), sử dụng Redis để truy cập nhanh.

| Method | Parameters | Return Type | Description |
|--------|-----------|-------------|-------------|
| get_plan | session_id: str | Plan hoặc None | Lấy plan hiện tại của session. |
| update_plan | session_id: str, plan: Plan | None | Cập nhật plan cho session. |
| get_artifacts | session_id: str | dict | Lấy tất cả artifacts đã tích luỹ. |
| store_artifact | session_id: str, key: str, value: Any | None | Lưu artifact theo key. |
| get_scratchpad | session_id: str | str hoặc None | Lấy nội dung scratchpad. |
| update_scratchpad | session_id: str, content: str | None | Cập nhật nội dung scratchpad. |

---

### 3.4 Long-Term Memory — Stub (Phase 2)

**EmbeddingService** — Phase 2. Tạo embeddings, được trừu tượng hoá khỏi provider cụ thể.

| Method | Parameters | Return Type | Description |
|--------|-----------|-------------|-------------|
| embed | texts: list[str] | list[list[float]] | Tạo embedding vectors cho nhiều đoạn text. |
| embed_query | query: str | list[float] | Tạo embedding vector cho 1 câu query. |

**MemorySearchEngine** — Phase 2. Tìm kiếm vector similarity.

| Method | Parameters | Return Type | Description |
|--------|-----------|-------------|-------------|
| search | tenant_id: str, agent_id: str, query: str, top_k: int (default 5), score_threshold: float (default 0.7), filters: MemoryFilters hoặc None, namespace: str (default "default") | list[MemorySearchResult] | Tìm kiếm memories theo vector similarity. |

**KnowledgeBaseIndexer** — Phase 2. Ingest tài liệu bên ngoài vào long-term memory.

| Method | Parameters | Return Type | Description |
|--------|-----------|-------------|-------------|
| ingest | tenant_id: str, agent_id: str, documents: list[Document], chunking_config: ChunkingConfig | IngestResult | Xử lý và lưu trữ tài liệu vào long-term memory. |

**Data Model — bảng `memories` (reference cho Phase 2):**

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| id | UUID | gen_random_uuid() | Primary key |
| tenant_id | TEXT NOT NULL | — | ID tenant sở hữu |
| agent_id | TEXT NOT NULL | — | ID agent sở hữu |
| namespace | TEXT NOT NULL | 'default' | Namespace để phân vùng memories |
| content | TEXT NOT NULL | — | Nội dung memory |
| content_type | TEXT | 'text' | Loại nội dung: 'text', 'structured', 'code' |
| embedding | VECTOR(1536) NOT NULL | — | Vector embedding cho similarity search |
| metadata | JSONB | '{}' | Metadata tuỳ chỉnh |
| source | TEXT | — | Nguồn gốc nội dung |
| tags | TEXT[] | '{}' | Danh sách tags |
| created_at | TIMESTAMPTZ | NOW() | Thời điểm tạo |
| updated_at | TIMESTAMPTZ | NOW() | Thời điểm cập nhật lần cuối |
| expires_at | TIMESTAMPTZ | — | Thời điểm hết hạn (nullable) |
| access_count | INT | 0 | Số lần truy cập |
| last_accessed_at | TIMESTAMPTZ | — | Thời điểm truy cập lần cuối |

**Foreign key:** tenant_id tham chiếu đến tenants(id).

**Indexes:**

- **idx_memories_embedding:** HNSW index trên cột embedding sử dụng vector_cosine_ops (m = 16, ef_construction = 64) — phục vụ approximate nearest neighbor search nhanh.
- **idx_memories_scope:** Composite index trên (tenant_id, agent_id, namespace) — phục vụ truy vấn theo scope.

**Row-Level Security (RLS):**

- Bật RLS trên bảng memories.
- Policy `tenant_isolation`: chỉ cho phép truy cập rows có tenant_id khớp với current_setting('app.current_tenant').

---

### 3.5 Episodic Memory — Stub (Phase 3)

**Episode** — data model lưu trữ một trải nghiệm hoàn chỉnh của agent.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | Unique identifier |
| agent_id | str | — | ID agent sở hữu |
| tenant_id | str | — | ID tenant sở hữu |
| task_summary | str | — | Tóm tắt task đã thực hiện |
| approach | str | — | Cách tiếp cận đã sử dụng |
| outcome | str | — | Kết quả: "success", "partial", hoặc "failed" |
| lessons_learned | str | — | Bài học rút ra |
| steps_taken | int | — | Số bước đã thực hiện |
| total_cost | float | — | Tổng chi phí (USD) |
| duration_seconds | int | — | Thời gian thực thi (giây) |
| tags | list[str] | — | Danh sách tags |
| embedding | list[float] | — | Vector embedding cho similarity search |
| created_at | datetime | — | Thời điểm tạo |

**EpisodicMemory** — quản lý lưu trữ và truy xuất episodes.

| Method | Parameters | Return Type | Description |
|--------|-----------|-------------|-------------|
| record_episode | session: CompletedSession | Episode | Ghi lại episode từ một session đã hoàn thành. |
| recall | task_description: str, top_k: int (default 3) | list[Episode] | Tìm kiếm episodes tương tự với task mô tả. |

---

### 3.6 Shared Memory — Stub (Phase 2)

```
┌─────────────── SHARED MEMORY ──────────────────┐
│                                                  │
│  ┌──────────────┐  ┌───────────────────────┐   │
│  │ Blackboard   │  │ Artifact Store        │   │
│  │ (Key-Value)  │  │ (Documents, Files)    │   │
│  │              │  │                       │   │
│  │ Fast read/   │  │ Version-controlled    │   │
│  │ write for    │  │ outputs from agents   │   │
│  │ state sharing│  │                       │   │
│  └──────────────┘  └───────────────────────┘   │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │ Inter-Agent Message Bus                   │   │
│  │ (Redis pub/sub channels)                  │   │
│  │                                           │   │
│  │ Agent A ──publish──→ topic ──subscribe──→ │   │
│  │                      Agent B              │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │ Access Control                            │   │
│  │ Agent A: read+write blackboard, artifact  │   │
│  │ Agent B: read-only blackboard             │   │
│  │ Agent C: write-only artifact              │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
└──────────────────────────────────────────────────┘
```

---

## 4. Sequence Diagrams

### 4.1 Build Context for LLM Call (Phase 1)

```
Executor              Memory Manager           Short-Term                Working
 │                        │                       │                        │
 │──build_context()──────→│                       │                        │
 │                        │                       │                        │
 │                        │──get_recent(N)───────→│                        │
 │                        │◄──recent_messages─────│                        │
 │                        │                       │                        │
 │                        │──get_summary()───────→│                        │
 │                        │◄──summary (if exists)─│                        │
 │                        │                       │                        │
 │                        │    [Phase 2: long-term memory search ở đây]    │
 │                        │                       │                        │
 │                        │──get_plan()───────────────────────────────────→│
 │                        │◄──current_plan────────────────────────────────│
 │                        │                       │                        │
 │                        │──get_scratchpad()─────────────────────────────→│
 │                        │◄──scratchpad──────────────────────────────────│
 │                        │                       │                        │
 │                        │ ┌─ ASSEMBLE CONTEXT ─────────────────────────┐│
 │                        │ │ 1. System prompt                           ││
 │                        │ │ 2. [Summary of older conversation]         ││
 │                        │ │ 3. [Current plan + scratchpad]             ││
 │                        │ │ 4. Recent messages (last N)                ││
 │                        │ │ 5. Token budget check → trim if needed     ││
 │                        │ └───────────────────────────────────────────┘│
 │                        │                       │                        │
 │◄──ContextPayload───────│                       │                        │
 │   {messages, tools,    │                       │                        │
 │    token_count}        │                       │                        │
```

### 4.2 Auto-Summarization Flow (Phase 1)

```
Executor        Memory Manager      Short-Term Memory       LLM Gateway
 │                  │                     │                      │
 │──update()───────→│                     │                      │
 │  (new messages)  │                     │                      │
 │                  │──append()──────────→│                      │
 │                  │                     │                      │
 │                  │──get_token_count()─→│                      │
 │                  │◄──8,500 tokens──────│                      │
 │                  │                     │                      │
 │                  │  [8,500 > 70% of 10,000 budget]            │
 │                  │  → TRIGGER SUMMARIZATION                   │
 │                  │                     │                      │
 │                  │──get_oldest(N)─────→│                      │
 │                  │◄──old_messages──────│                      │
 │                  │                     │                      │
 │                  │──summarize(old_messages)───────────────────→│
 │                  │  {role: "system",                          │
 │                  │   content: "Summarize this conversation"}  │
 │                  │◄──summary_text─────────────────────────────│
 │                  │                     │                      │
 │                  │──replace_old_with_summary()──→│            │
 │                  │                     │         │            │
 │                  │                     │  [Remove old msgs,   │
 │                  │                     │   insert summary]    │
 │                  │                     │                      │
 │                  │──get_token_count()─→│                      │
 │                  │◄──4,200 tokens──────│  ← Reduced!          │
 │                  │                     │                      │
 │◄──done───────────│                     │                      │
```

### 4.3 Long-Term Memory Store & Search (Phase 2)

```
Agent (via Tool)      Memory Manager      Embedding Svc      Vector Store (PG)
 │                        │                    │                   │
 │──store("important      │                    │                   │
 │   finding: X")────────→│                    │                   │
 │                        │──embed(text)──────→│                   │
 │                        │◄──[0.12, -0.45,...]│                   │
 │                        │                    │                   │
 │                        │──INSERT────────────────────────────────→│
 │                        │◄──memory_id────────────────────────────│
 │                        │                    │                   │
 │◄──stored: mem_abc──────│                    │                   │
 │                        │                    │                   │
 │──search("findings      │                    │                   │
 │   about X")───────────→│                    │                   │
 │                        │──embed(query)─────→│                   │
 │                        │◄──query_vector─────│                   │
 │                        │                    │                   │
 │                        │──SELECT ... ORDER──────────────────────→│
 │                        │  BY embedding <=>  │                   │
 │                        │  query_vector      │                   │
 │                        │  LIMIT 5           │                   │
 │                        │◄──results──────────────────────────────│
 │                        │                    │                   │
 │◄──[MemoryEntry x 5]───│                    │                   │
```

### 4.4 Multi-Agent Shared Memory (Phase 2)

```
Agent A (Researcher)    Shared Memory       Agent B (Writer)
 │                          │                    │
 │──store_artifact()───────→│                    │
 │  key: "research_results" │                    │
 │  value: {findings: [...]}│                    │
 │◄──ok─────────────────────│                    │
 │                          │                    │
 │──publish("research_done")│                    │
 │──────────────────────────│──notify───────────→│
 │                          │                    │
 │                          │◄──get_artifact()───│
 │                          │   "research_results│
 │                          │──────data─────────→│
```

---

## 5. Configuration Model

**MemoryConfig** — cấu hình tổng thể cho Memory System, bao gồm 3 sub-config:

| Field | Type | Description |
|-------|------|-------------|
| short_term | ShortTermConfig | Cấu hình short-term memory |
| long_term | LongTermConfig | Cấu hình long-term memory |
| working | WorkingConfig | Cấu hình working memory |

**ShortTermConfig:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| strategy | Literal["sliding_window", "summarize_recent", "selective", "token_trim"] | — | Chiến lược quản lý context window |
| max_context_tokens | int | 8000 | Số token tối đa cho context window |
| recent_messages_to_keep | int | 20 | Số messages gần nhất luôn được giữ lại |
| summarization_threshold | float | 0.7 | Ngưỡng % token budget kích hoạt summarization |
| summarization_model | str | "claude-haiku-4-5-20251001" | Model sử dụng cho summarization |

**LongTermConfig:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | False | Disabled trong Phase 1 |
| auto_retrieve | bool | True | Tự động truy xuất long-term memory khi build context |
| top_k | int | 5 | Số kết quả trả về khi search |
| score_threshold | float | 0.7 | Ngưỡng similarity score tối thiểu |
| embedding_provider | str | "openai" | Provider cho embedding |
| embedding_model | str | "text-embedding-3-small" | Model embedding |
| embedding_dimensions | int | 1536 | Số chiều của embedding vector |
| max_memories | int | 100_000 | Số memories tối đa cho mỗi agent |
| chunking_strategy | str | "recursive" | Chiến lược chia nhỏ tài liệu |
| chunk_size | int | 512 | Kích thước mỗi chunk (tokens) |
| chunk_overlap | int | 50 | Số tokens overlap giữa các chunks |

**WorkingConfig:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| scratchpad_enabled | bool | True | Bật/tắt scratchpad |
| max_artifacts | int | 50 | Số artifacts tối đa mỗi session |
| max_artifact_size_bytes | int | 1_048_576 | Kích thước tối đa mỗi artifact (1MB) |

---

## 6. Tech Stack

| Component | Technology | Phase |
|-----------|-----------|-------|
| **Short-term storage** | Redis (List + Hash) | 1 |
| **Working memory** | Redis Hash | 1 |
| **Summarization** | Claude Haiku 4.5 / GPT-4o-mini | 1 |
| **Long-term vector store** | PostgreSQL + pgvector (HNSW) | 2 |
| **Embedding (cloud)** | OpenAI text-embedding-3-small | 2 |
| **Embedding (local)** | sentence-transformers (all-MiniLM) | 2 |
| **Document parsing** | Unstructured.io (OSS) | 2 |
| **Chunking** | LangChain text splitters / custom | 2 |
| **Shared memory bus** | Redis Pub/Sub | 2 |
| **Long-term scale-out** | Qdrant hoặc Pinecone | 3 |
| **Episodic memory store** | PostgreSQL + pgvector | 3 |

---

## 7. Performance Targets

### Phase 1

| Operation | Target Latency |
|-----------|---------------|
| Short-term: append message | < 1ms (Redis RPUSH) |
| Short-term: get recent N | < 2ms (Redis LRANGE) |
| Short-term: get token count | < 1ms (Redis cached counter) |
| Working: read plan/artifacts | < 2ms (Redis HGET) |
| Working: update | < 2ms (Redis HSET) |
| Context build (full assembly) | < 100ms (parallel retrieval) |
| Summarization | < 3s (LLM call) |

### Phase 2

| Operation | Target Latency |
|-----------|---------------|
| Long-term: embed text | < 50ms (API call, batched) |
| Long-term: vector search (top-5) | < 20ms (HNSW index, < 1M vectors) |
| Long-term: store memory | < 60ms (embed + INSERT) |

---

## 8. Memory Lifecycle & Cleanup

| Memory Type | TTL | Cleanup Strategy |
|-------------|-----|-----------------|
| **Short-term** | Session duration + 1h buffer | Auto-delete khi session archived |
| **Working** | Session duration | Auto-delete khi session complete/fail |
| **Long-term** (Phase 2) | Configurable per-agent (default: indefinite) | Policy-based (LRU, age, access count) |
| **Episodic** (Phase 3) | Indefinite | Capacity-based eviction (keep top-N episodes) |
| **Shared** (Phase 2) | Multi-agent session duration | Auto-delete khi session end |

**MemoryCleanupPolicy** — cấu hình chính sách dọn dẹp long-term memory:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| max_memories_per_agent | int | 100_000 | Số memories tối đa cho mỗi agent |
| eviction_strategy | str | "lru" | Chiến lược eviction: "lru", "oldest", "lowest_score" |
| min_access_count | int | 0 | Số lần truy cập tối thiểu để không bị evict |
| max_age_days | int hoặc None | None | Tuổi tối đa (ngày) — None nghĩa là không giới hạn |
| archive_before_delete | bool | True | Lưu trữ (archive) trước khi xoá |
