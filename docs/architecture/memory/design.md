# Thiết Kế Chi Tiết: Memory System

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect
> **Parent:** [Architecture Overview](../00-overview.md)

---

## 1. High-Level Diagram

```
┌──────────────────────────────── MEMORY SYSTEM ─────────────────────────────────────┐
│                                                                                     │
│                              ┌──────────────────┐                                  │
│                              │  Memory Manager  │                                  │
│                              │  (Orchestrator)  │                                  │
│                              └────────┬─────────┘                                  │
│                                       │                                             │
│              ┌────────────────────────┼────────────────────────┐                   │
│              │                        │                        │                   │
│     ┌────────▼─────────┐    ┌────────▼─────────┐    ┌────────▼─────────┐          │
│     │  SHORT-TERM      │    │  LONG-TERM       │    │  WORKING         │          │
│     │  MEMORY          │    │  MEMORY          │    │  MEMORY          │          │
│     │                  │    │                  │    │                  │          │
│     │ ┌──────────────┐ │    │ ┌──────────────┐ │    │ ┌──────────────┐ │          │
│     │ │ Context      │ │    │ │ Vector Store │ │    │ │ Plan State   │ │          │
│     │ │ Window Mgr   │ │    │ │ (pgvector)   │ │    │ │              │ │          │
│     │ ├──────────────┤ │    │ ├──────────────┤ │    │ ├──────────────┤ │          │
│     │ │ Conversation │ │    │ │ Knowledge    │ │    │ │ Accumulated  │ │          │
│     │ │ Buffer       │ │    │ │ Base Index   │ │    │ │ Artifacts    │ │          │
│     │ ├──────────────┤ │    │ ├──────────────┤ │    │ ├──────────────┤ │          │
│     │ │ Summarizer   │ │    │ │ Embedding    │ │    │ │ Scratchpad   │ │          │
│     │ │              │ │    │ │ Service      │ │    │ │              │ │          │
│     │ └──────────────┘ │    │ └──────────────┘ │    │ └──────────────┘ │          │
│     │                  │    │                  │    │                  │          │
│     │  Scope: Session  │    │  Scope: Agent/   │    │  Scope: Session  │          │
│     │  Store: Redis    │    │  Tenant          │    │  Store: Redis    │          │
│     │                  │    │  Store: PG+      │    │                  │          │
│     │                  │    │  pgvector         │    │                  │          │
│     └──────────────────┘    └──────────────────┘    └──────────────────┘          │
│                                                                                     │
│     ┌──────────────────┐    ┌──────────────────┐                                  │
│     │  EPISODIC        │    │  SHARED          │                                  │
│     │  MEMORY          │    │  MEMORY          │                                  │
│     │                  │    │                  │                                  │
│     │ ┌──────────────┐ │    │ ┌──────────────┐ │                                  │
│     │ │ Experience   │ │    │ │ Blackboard   │ │                                  │
│     │ │ Store        │ │    │ │ (KV Store)   │ │                                  │
│     │ ├──────────────┤ │    │ ├──────────────┤ │                                  │
│     │ │ Episode      │ │    │ │ Artifact     │ │                                  │
│     │ │ Retriever    │ │    │ │ Store        │ │                                  │
│     │ └──────────────┘ │    │ ├──────────────┤ │                                  │
│     │                  │    │ │ Message Bus  │ │                                  │
│     │  Scope: Agent-   │    │ │ (inter-agent)│ │                                  │
│     │  type            │    │ └──────────────┘ │                                  │
│     │  Store: PG+      │    │                  │                                  │
│     │  pgvector         │    │  Scope: Multi-   │                                  │
│     │  Phase: 3        │    │  agent session   │                                  │
│     │                  │    │  Store: Redis    │                                  │
│     └──────────────────┘    │  Phase: 2        │                                  │
│                              └──────────────────┘                                  │
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

## 2. Component Descriptions

### 2.1 Memory Manager (Orchestrator)

Điểm entry duy nhất cho mọi memory operations. Routing requests đến đúng memory layer dựa trên context.

```python
class MemoryManager:
    """
    Orchestrates all memory operations across layers.
    Each method enforces tenant isolation before delegating.
    """

    def __init__(
        self,
        short_term: ShortTermMemory,
        long_term: LongTermMemory,
        working: WorkingMemory,
        episodic: EpisodicMemory | None,    # Phase 3
        shared: SharedMemory | None,        # Phase 2
    ): ...

    # Called by executor before each LLM call
    async def build_context(
        self,
        session_id: str,
        agent_config: AgentConfig,
    ) -> ContextPayload:
        """
        Assembles the full context for an LLM call:
        1. System prompt (from agent config)
        2. Relevant long-term memories (RAG retrieval)
        3. Working memory (plan state, artifacts)
        4. Short-term memory (recent conversation, managed by strategy)
        """

    # Called by executor after each step
    async def update(
        self,
        session_id: str,
        messages: list[Message],
        artifacts: dict | None,
    ) -> None:
        """Updates short-term buffer, working memory, and optionally long-term."""

    # Explicit memory store/search (agent-initiated or API)
    async def store(self, tenant_id: str, agent_id: str, content: str, metadata: dict) -> str
    async def search(self, tenant_id: str, agent_id: str, query: str, top_k: int = 5) -> list[MemoryEntry]
    async def delete(self, tenant_id: str, memory_id: str) -> bool
```

---

### 2.2 Short-Term Memory

**Scope:** Per-session. Chứa conversation history gần đây mà agent cần để hiểu context hiện tại.

**Vấn đề cốt lõi:** Context window của LLM có giới hạn. Agent chạy nhiều bước → history tăng → cần chiến lược quản lý.

#### 2.2.1 Context Window Manager

Quyết định **messages nào** đưa vào LLM call, dựa trên chiến lược được cấu hình.

```python
class ContextWindowManager:
    async def build(
        self,
        full_history: list[Message],
        system_prompt: str,
        injected_context: str | None,       # RAG results, working memory
        tool_schemas: list[dict],
        strategy: ContextStrategy,
        max_tokens: int,
    ) -> list[Message]:
        """
        Returns optimized message list that fits within max_tokens.
        Preserves: system_prompt (always) + tool_schemas + strategy-selected messages
        """
```

**Strategies:**

| Strategy | Cách hoạt động | Trade-off |
|----------|---------------|-----------|
| **Sliding Window** | Giữ N messages gần nhất | Đơn giản, mất context cũ |
| **Summarize + Recent** | Summarize messages cũ thành 1 message, giữ N messages gần nhất | Giữ context, tốn 1 LLM call |
| **Selective Retention** | Giữ system + first user msg + messages flagged "important" + recent | Tiết kiệm, cần logic flagging |
| **Token-Aware Trim** | Cắt messages từ giữa, ưu tiên giữ đầu + cuối | Tự động, có thể mất context quan trọng |

**Recommended default:** `Summarize + Recent` — tốt nhất cho hầu hết use cases.

#### 2.2.2 Conversation Buffer

Ring buffer lưu full conversation history trong Redis, không bị cắt bởi context strategy.

```python
class ConversationBuffer:
    """Full history stored in Redis, not affected by context trimming."""

    async def append(self, session_id: str, message: Message) -> None
    async def get_all(self, session_id: str) -> list[Message]
    async def get_recent(self, session_id: str, n: int) -> list[Message]
    async def get_token_count(self, session_id: str) -> int
```

**Storage:** Redis — key format: `session:{session_id}:messages` (list type)

**Tại sao cần buffer riêng?** Context strategy quyết định cái gì vào LLM call, nhưng full history cần lưu cho: audit trail, replay, debug, và summary generation.

#### 2.2.3 Summarizer

Tạo summary từ messages cũ khi buffer tiếp cận context limit.

```python
class ConversationSummarizer:
    async def summarize(
        self,
        messages: list[Message],
        existing_summary: str | None,
        model_config: ModelConfig,
    ) -> str:
        """
        Uses a lightweight LLM call to create/update a running summary.

        Incremental: if existing_summary provided, summarizes
        existing_summary + new_messages → updated_summary.

        Target: summary < 500 tokens regardless of input length.
        """
```

**Khi nào trigger summarization:**
```
Token count of history > 70% of context_window_budget
    → Summarize oldest messages (keep last N)
    → Replace old messages with summary message
    → Continue execution
```

---

### 2.3 Long-Term Memory (Phase 1-2)

> **Phase note:** Long-term memory được hạ từ P0 xuống P1 (Phase 1-2) sau review. Phase 1 MVP chỉ cần short-term + working memory — đủ cho hầu hết session-scoped use cases. Long-term memory (vector store, RAG) triển khai khi đã validate core runtime ổn định.

**Scope:** Per-agent hoặc per-tenant. Lưu trữ kiến thức persistent qua các sessions.

#### 2.3.1 Vector Store

```
┌─────────────────────────────────────────────────────────┐
│                   VECTOR STORE                           │
│                                                          │
│  ┌────────────┐    ┌──────────────┐    ┌─────────────┐ │
│  │ Embedding  │───→│  pgvector    │◄───│  Search     │ │
│  │ Service    │    │  Index       │    │  Engine     │ │
│  │            │    │              │    │             │ │
│  │ text →     │    │  HNSW /     │    │  query →    │ │
│  │ vector     │    │  IVFFlat    │    │  top-K      │ │
│  └────────────┘    └──────────────┘    └─────────────┘ │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Data Model:**

```sql
CREATE TABLE memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT 'default',

    -- Content
    content TEXT NOT NULL,
    content_type TEXT DEFAULT 'text',      -- 'text', 'structured', 'code'

    -- Embedding
    embedding VECTOR(1536) NOT NULL,        -- OpenAI ada-002 / Anthropic voyage

    -- Metadata
    metadata JSONB DEFAULT '{}',
    source TEXT,                             -- 'user_uploaded', 'agent_generated', 'session:{id}'
    tags TEXT[] DEFAULT '{}',

    -- Lifecycle
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,                 -- optional TTL
    access_count INT DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,

    -- Isolation
    CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

-- HNSW index for fast approximate nearest neighbor
CREATE INDEX idx_memories_embedding ON memories
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Composite index for tenant + agent scoping
CREATE INDEX idx_memories_scope ON memories (tenant_id, agent_id, namespace);

-- Row-level security
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON memories
    USING (tenant_id = current_setting('app.current_tenant'));
```

#### 2.3.2 Embedding Service

```python
class EmbeddingService:
    """Generates embeddings, abstracted from provider."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Providers (configurable):
        - OpenAI text-embedding-3-small (1536 dims, $0.02/1M tokens)
        - Voyage AI voyage-3 (1024 dims)
        - Local: sentence-transformers (384/768 dims, free)

        Includes:
        - Batching (max 2048 texts per call)
        - Caching (hash(text) → cached embedding)
        - Rate limiting
        """

    async def embed_query(self, query: str) -> list[float]:
        """Single text embedding optimized for search queries."""
```

#### 2.3.3 Search Engine

```python
class MemorySearchEngine:
    async def search(
        self,
        tenant_id: str,
        agent_id: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.7,
        filters: MemoryFilters | None = None,
        namespace: str = "default",
    ) -> list[MemorySearchResult]:
        """
        1. Embed query via EmbeddingService
        2. Vector similarity search in pgvector (cosine distance)
        3. Apply metadata filters (tags, date range, source)
        4. Apply score threshold
        5. Return top-K results with scores

        filters:
          - tags: ["faq", "product"]
          - date_range: (start, end)
          - source: "user_uploaded"
          - content_type: "text"
        """
```

**Search flow:**
```sql
-- Actual query generated by SearchEngine
SELECT id, content, metadata,
       1 - (embedding <=> $query_embedding) AS similarity
FROM memories
WHERE tenant_id = $tenant_id
  AND agent_id = $agent_id
  AND namespace = $namespace
  AND ($tag_filter IS NULL OR tags && $tag_filter)
ORDER BY embedding <=> $query_embedding
LIMIT $top_k;
```

#### 2.3.4 Knowledge Base Index

Cho phép ingest external documents (PDF, web pages, files) vào long-term memory.

```python
class KnowledgeBaseIndexer:
    async def ingest(
        self,
        tenant_id: str,
        agent_id: str,
        documents: list[Document],
        chunking_config: ChunkingConfig,
    ) -> IngestResult:
        """
        1. Parse documents (PDF → text, HTML → text, etc.)
        2. Chunk text using configured strategy
        3. Generate embeddings for each chunk
        4. Store in vector store with source metadata

        ChunkingConfig:
          - strategy: "fixed_size" | "recursive" | "semantic"
          - chunk_size: 512 tokens (default)
          - chunk_overlap: 50 tokens (default)
        """
```

---

### 2.4 Working Memory

**Scope:** Per-session. Lưu trạng thái công việc hiện tại — plan, intermediate results, scratchpad.

```python
class WorkingMemory:
    """Session-scoped working state, stored in Redis for fast access."""

    async def get_plan(self, session_id: str) -> Plan | None:
        """Get current execution plan (for plan-then-execute pattern)."""

    async def update_plan(self, session_id: str, plan: Plan) -> None:
        """Update plan status (step completed, re-planned, etc.)."""

    async def get_artifacts(self, session_id: str) -> dict:
        """Get accumulated artifacts (intermediate results, files, data)."""

    async def store_artifact(self, session_id: str, key: str, value: Any) -> None:
        """Store an artifact from a tool call or intermediate computation."""

    async def get_scratchpad(self, session_id: str) -> str | None:
        """Free-form scratchpad for agent notes (injected into prompt)."""

    async def update_scratchpad(self, session_id: str, content: str) -> None
```

**Storage:** Redis Hash — key: `session:{session_id}:working`

---

### 2.5 Episodic Memory (Phase 3)

**Scope:** Per-agent-type. Lưu kinh nghiệm từ các sessions trước — task nào, cách tiếp cận nào, kết quả ra sao.

```python
@dataclass
class Episode:
    id: str
    agent_id: str
    tenant_id: str
    task_summary: str              # Tóm tắt task đã thực hiện
    approach: str                  # Cách agent giải quyết
    outcome: str                   # "success" | "partial" | "failed"
    lessons_learned: str           # Rút ra bài học gì
    steps_taken: int
    total_cost: float
    duration_seconds: int
    tags: list[str]
    embedding: list[float]         # Embedding of task_summary for retrieval
    created_at: datetime

class EpisodicMemory:
    async def record_episode(self, session: CompletedSession) -> Episode:
        """Auto-generate episode summary from completed session using LLM."""

    async def recall(self, task_description: str, top_k: int = 3) -> list[Episode]:
        """Find similar past episodes to inform current planning."""
```

**Use case:** Khi agent nhận task mới, episodic memory được queried để tìm past episodes tương tự. Agent có thể học từ approaches đã thành công hoặc tránh approaches đã thất bại.

---

### 2.6 Shared Memory (Phase 2)

**Scope:** Per-multi-agent session. Cho phép nhiều agent chia sẻ thông tin trong cùng một phiên.

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

## 3. Sequence Diagrams

### 3.1 Build Context for LLM Call (mỗi step)

```
Executor              Memory Manager           Short-Term         Long-Term          Working
 │                        │                       │                  │                  │
 │──build_context()──────→│                       │                  │                  │
 │                        │                       │                  │                  │
 │                        │──get_recent(N)───────→│                  │                  │
 │                        │◄──recent_messages─────│                  │                  │
 │                        │                       │                  │                  │
 │                        │──get_summary()───────→│                  │                  │
 │                        │◄──summary (if exists)─│                  │                  │
 │                        │                       │                  │                  │
 │                        │──search(last_user_msg)─────────────────→│                  │
 │                        │◄──relevant_memories────────────────────│                  │
 │                        │                       │                  │                  │
 │                        │──get_plan()───────────────────────────────────────────────→│
 │                        │◄──current_plan─────────────────────────────────────────────│
 │                        │                       │                  │                  │
 │                        │──get_scratchpad()─────────────────────────────────────────→│
 │                        │◄──scratchpad───────────────────────────────────────────────│
 │                        │                       │                  │                  │
 │                        │                       │                  │                  │
 │                        │ ┌─ ASSEMBLE CONTEXT ─────────────────────────────────────┐ │
 │                        │ │ 1. System prompt                                       │ │
 │                        │ │ 2. [Summary of older conversation]                     │ │
 │                        │ │ 3. [Relevant long-term memories]                       │ │
 │                        │ │ 4. [Current plan + scratchpad]                         │ │
 │                        │ │ 5. Recent messages (last N)                            │ │
 │                        │ │ 6. Token budget check → trim if needed                 │ │
 │                        │ └────────────────────────────────────────────────────────┘ │
 │                        │                       │                  │                  │
 │◄──ContextPayload───────│                       │                  │                  │
 │   {messages, tools,    │                       │                  │                  │
 │    token_count}        │                       │                  │                  │
```

### 3.2 Auto-Summarization Flow (khi gần context limit)

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

### 3.3 Long-Term Memory Store & Search Flow

```
Agent (via Tool)      Memory Manager      Embedding Svc      Vector Store (PG)
 │                        │                    │                   │
 │──store("important      │                    │                   │
 │   finding: X")────────→│                    │                   │
 │                        │──embed(text)──────→│                   │
 │                        │◄──[0.12, -0.45,...]│                   │
 │                        │                    │                   │
 │                        │──INSERT────────────────────────────────→│
 │                        │  (tenant, agent,   │                   │
 │                        │   content, vector, │                   │
 │                        │   metadata)        │                   │
 │                        │◄──memory_id────────────────────────────│
 │                        │                    │                   │
 │◄──stored: mem_abc──────│                    │                   │
 │                        │                    │                   │
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
 │   with similarity      │                    │                   │
 │   scores               │                    │                   │
```

### 3.4 Multi-Agent Shared Memory Flow (Phase 2)

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
 │                          │  (subscribed to    │
 │                          │   research events) │
 │                          │                    │
 │                          │◄──get_artifact()───│
 │                          │   "research_results│
 │                          │──────data─────────→│
 │                          │                    │
 │                          │    [Agent B uses   │
 │                          │     research to    │
 │                          │     write article] │
```

---

## 4. Configuration Model

```python
@dataclass
class MemoryConfig:
    short_term: ShortTermConfig
    long_term: LongTermConfig
    working: WorkingConfig

@dataclass
class ShortTermConfig:
    strategy: Literal["sliding_window", "summarize_recent", "selective", "token_trim"]
    max_context_tokens: int = 8000          # tokens allocated for history
    recent_messages_to_keep: int = 20       # messages always kept (for summarize strategy)
    summarization_threshold: float = 0.7    # trigger at 70% of max_context_tokens
    summarization_model: str = "claude-haiku-4-5-20251001"  # cheap, fast model for summaries

@dataclass
class LongTermConfig:
    enabled: bool = True
    auto_retrieve: bool = True              # auto-RAG on each user message
    top_k: int = 5
    score_threshold: float = 0.7
    embedding_provider: str = "openai"      # "openai", "voyage", "local"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    max_memories: int = 100_000             # per agent, soft limit
    chunking_strategy: str = "recursive"
    chunk_size: int = 512
    chunk_overlap: int = 50

@dataclass
class WorkingConfig:
    scratchpad_enabled: bool = True
    max_artifacts: int = 50
    max_artifact_size_bytes: int = 1_048_576  # 1MB
```

---

## 5. Tech Stack

| Component | Technology | Phase | Lý do |
|-----------|-----------|-------|-------|
| **Short-term storage** | Redis (List + Hash) | 1 | Sub-ms access, TTL, atomic ops |
| **Long-term vector store** | PostgreSQL + pgvector (HNSW) | 1-2 | Single DB, mature, good perf to 1M vectors |
| **Long-term scale-out** | Qdrant hoặc Pinecone | 2-3 | Khi vượt 10M vectors hoặc cần advanced features |
| **Embedding (cloud)** | OpenAI text-embedding-3-small | 1-2 | Best cost/quality ratio |
| **Embedding (local)** | sentence-transformers (all-MiniLM) | 2 | Free, privacy, air-gapped |
| **Summarization** | Claude Haiku 4.5 / GPT-4o-mini | 1 | Cheap + fast cho summary tasks |
| **Document parsing** | Unstructured.io (OSS) | 1-2 | PDF, HTML, DOCX support |
| **Chunking** | LangChain text splitters / custom | 1-2 | Mature, well-tested strategies |
| **Working memory** | Redis Hash | 1 | Fast, structured, TTL |
| **Shared memory bus** | Redis Pub/Sub | 2 | Lightweight inter-agent messaging |
| **Episodic memory store** | PostgreSQL + pgvector | 3 | Reuse existing infra |

---

## 6. Performance Targets

| Operation | Target Latency | Notes |
|-----------|---------------|-------|
| Short-term: append message | < 1ms | Redis RPUSH |
| Short-term: get recent N | < 2ms | Redis LRANGE |
| Short-term: get token count | < 1ms | Redis cached counter |
| Long-term: embed text | < 50ms | API call (batched) |
| Long-term: vector search (top-5) | < 20ms | HNSW index, < 1M vectors |
| Long-term: store memory | < 60ms | embed + INSERT |
| Working: read plan/artifacts | < 2ms | Redis HGET |
| Working: update | < 2ms | Redis HSET |
| Context build (full assembly) | < 100ms | Parallel retrieval |
| Summarization | < 3s | LLM call (Haiku/mini) |

---

## 7. Memory Lifecycle & Cleanup

| Memory Type | TTL | Cleanup Strategy |
|-------------|-----|-----------------|
| **Short-term** | Session duration + 1h buffer | Auto-delete when session archived |
| **Working** | Session duration | Auto-delete on session complete/fail |
| **Long-term** | Configurable per-agent (default: indefinite) | Manual or policy-based (LRU, age, access count) |
| **Episodic** | Indefinite | Capacity-based eviction (keep top-N episodes) |
| **Shared** | Multi-agent session duration | Auto-delete on session end |

```python
class MemoryCleanupPolicy:
    max_memories_per_agent: int = 100_000
    eviction_strategy: str = "lru"          # "lru", "oldest", "lowest_score"
    min_access_count: int = 0               # Delete if accessed < N times
    max_age_days: int | None = None         # Delete if older than N days
    archive_before_delete: bool = True      # Move to cold storage before deletion
```
