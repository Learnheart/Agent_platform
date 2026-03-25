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

```python
class MemoryManager:
    """
    Orchestrates all memory operations across layers.
    Each method enforces tenant isolation before delegating.
    """

    def __init__(
        self,
        short_term: ShortTermMemory,
        long_term: LongTermMemory | None,      # Phase 2
        working: WorkingMemory,
        episodic: EpisodicMemory | None,        # Phase 3
        shared: SharedMemory | None,            # Phase 2
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
        2. Working memory (plan state, artifacts)
        3. Short-term memory (recent conversation, managed by strategy)
        """

    # Called by executor after each step
    async def update(
        self,
        session_id: str,
        messages: list[Message],
        artifacts: dict | None,
    ) -> None:
        """Updates short-term buffer and working memory."""

    # Phase 2: explicit memory store/search (agent-initiated or API)
    async def store(self, tenant_id: str, agent_id: str, content: str, metadata: dict) -> str
    async def search(self, tenant_id: str, agent_id: str, query: str, top_k: int = 5) -> list[MemoryEntry]
    async def delete(self, tenant_id: str, memory_id: str) -> bool
```

---

### 3.2 Short-Term Memory (Phase 1)

**Scope:** Per-session.
**Store:** Redis.

#### 3.2.1 Context Window Manager

```python
class ContextWindowManager:
    async def build(
        self,
        full_history: list[Message],
        system_prompt: str,
        injected_context: str | None,       # working memory
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

| Strategy | Hoạt động | Trade-off |
|----------|-----------|-----------|
| **Sliding Window** | Giữ N messages gần nhất | Đơn giản, mất context cũ |
| **Summarize + Recent** (default) | Summarize messages cũ thành 1 message, giữ N messages gần nhất | Giữ context, tốn 1 LLM call |
| **Selective Retention** | Giữ system + first user msg + messages flagged "important" + recent | Tiết kiệm, cần logic flagging |
| **Token-Aware Trim** | Cắt messages từ giữa, ưu tiên giữ đầu + cuối | Tự động, có thể mất context quan trọng |

#### 3.2.2 Conversation Buffer

```python
class ConversationBuffer:
    """Full history stored in Redis, not affected by context trimming."""

    async def append(self, session_id: str, message: Message) -> None
    async def get_all(self, session_id: str) -> list[Message]
    async def get_recent(self, session_id: str, n: int) -> list[Message]
    async def get_token_count(self, session_id: str) -> int
```

**Storage:** Redis — key format: `session:{session_id}:messages` (list type)

#### 3.2.3 Summarizer

```python
class ConversationSummarizer:
    async def summarize(
        self,
        messages: list[Message],
        existing_summary: str | None,
        model_config: ModelConfig,
    ) -> str:
        """
        Incremental: if existing_summary provided, summarizes
        existing_summary + new_messages → updated_summary.

        Target: summary < 500 tokens regardless of input length.
        """
```

**Trigger logic:**
```
Token count of history > 70% of context_window_budget
    → Summarize oldest messages (keep last N)
    → Replace old messages with summary message
    → Continue execution
```

---

### 3.3 Working Memory (Phase 1)

**Scope:** Per-session.
**Store:** Redis Hash — key: `session:{session_id}:working`

```python
class WorkingMemory:
    """Session-scoped working state, stored in Redis for fast access."""

    async def get_plan(self, session_id: str) -> Plan | None
    async def update_plan(self, session_id: str, plan: Plan) -> None
    async def get_artifacts(self, session_id: str) -> dict
    async def store_artifact(self, session_id: str, key: str, value: Any) -> None
    async def get_scratchpad(self, session_id: str) -> str | None
    async def update_scratchpad(self, session_id: str, content: str) -> None
```

---

### 3.4 Long-Term Memory — Stub (Phase 2)

```python
class EmbeddingService:
    """Phase 2. Generates embeddings, abstracted from provider."""
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, query: str) -> list[float]: ...

class MemorySearchEngine:
    """Phase 2. Vector similarity search."""
    async def search(
        self,
        tenant_id: str,
        agent_id: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.7,
        filters: MemoryFilters | None = None,
        namespace: str = "default",
    ) -> list[MemorySearchResult]: ...

class KnowledgeBaseIndexer:
    """Phase 2. Ingest external documents into long-term memory."""
    async def ingest(
        self,
        tenant_id: str,
        agent_id: str,
        documents: list[Document],
        chunking_config: ChunkingConfig,
    ) -> IngestResult: ...
```

**Data Model (reference cho Phase 2):**

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
    embedding VECTOR(1536) NOT NULL,

    -- Metadata
    metadata JSONB DEFAULT '{}',
    source TEXT,
    tags TEXT[] DEFAULT '{}',

    -- Lifecycle
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
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

---

### 3.5 Episodic Memory — Stub (Phase 3)

```python
@dataclass
class Episode:
    id: str
    agent_id: str
    tenant_id: str
    task_summary: str
    approach: str
    outcome: str                   # "success" | "partial" | "failed"
    lessons_learned: str
    steps_taken: int
    total_cost: float
    duration_seconds: int
    tags: list[str]
    embedding: list[float]
    created_at: datetime

class EpisodicMemory:
    async def record_episode(self, session: CompletedSession) -> Episode: ...
    async def recall(self, task_description: str, top_k: int = 3) -> list[Episode]: ...
```

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

```python
@dataclass
class MemoryConfig:
    short_term: ShortTermConfig
    long_term: LongTermConfig
    working: WorkingConfig

@dataclass
class ShortTermConfig:
    strategy: Literal["sliding_window", "summarize_recent", "selective", "token_trim"]
    max_context_tokens: int = 8000
    recent_messages_to_keep: int = 20
    summarization_threshold: float = 0.7
    summarization_model: str = "claude-haiku-4-5-20251001"

@dataclass
class LongTermConfig:
    enabled: bool = False                       # Disabled in Phase 1
    auto_retrieve: bool = True
    top_k: int = 5
    score_threshold: float = 0.7
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    max_memories: int = 100_000
    chunking_strategy: str = "recursive"
    chunk_size: int = 512
    chunk_overlap: int = 50

@dataclass
class WorkingConfig:
    scratchpad_enabled: bool = True
    max_artifacts: int = 50
    max_artifact_size_bytes: int = 1_048_576    # 1MB
```

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

```python
class MemoryCleanupPolicy:
    max_memories_per_agent: int = 100_000
    eviction_strategy: str = "lru"          # "lru", "oldest", "lowest_score"
    min_access_count: int = 0
    max_age_days: int | None = None
    archive_before_delete: bool = True
```
