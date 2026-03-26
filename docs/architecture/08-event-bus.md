# Thiết Kế Chi Tiết: Event Bus, SSE Streaming & Task Queue

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-26
> **Parent:** [Architecture Overview](00-overview.md)

---

## 1. Scope

Tài liệu này định nghĩa ba subsystem liên quan chặt chẽ:

1. **Event Bus** — Publish/subscribe cho AgentEvents (Redis Pub/Sub)
2. **SSE Streaming** — Real-time event delivery tới client (Phase 1)
3. **Task Queue** — Execution task dispatch (Redis Streams)

```
┌──────────────────────── EVENT & TASK INFRASTRUCTURE ───────────────────────┐
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         EVENT BUS (Redis Pub/Sub)                    │  │
│  │                                                                      │  │
│  │  Publishers:                    Consumers:                           │  │
│  │  ┌──────────┐                  ┌─────────────┐                      │  │
│  │  │ Executor │──emit──→         │ SSE Consumer│──→ Client (SSE)      │  │
│  │  │ Services │         channel  │ OTel Export │──→ Trace Store       │  │
│  │  │ Guardrail│──emit──→         │ Gov Consumer│──→ Audit + Cost     │  │
│  │  └──────────┘                  │ Webhook     │──→ External systems  │  │
│  │                                └─────────────┘                      │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                       TASK QUEUE (Redis Streams)                     │  │
│  │                                                                      │  │
│  │  Session Service ──XADD──→ tasks:{tenant_id} ──XREADGROUP──→ Worker │  │
│  │                            (stream)              (consumer    Pool   │  │
│  │                                                   group)            │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                       SSE STREAMING (sse-starlette)                  │  │
│  │                                                                      │  │
│  │  Client ──GET /sessions/{id}/stream──→ SSEManager ←──subscribe──    │  │
│  │                                         │               Event Bus   │  │
│  │                                         └──yield events──→ Client   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Event Bus

### 2.1 Architecture

```
Publishers                  Redis Pub/Sub               Consumers
                            (channels)
┌──────────┐                                      ┌──────────────┐
│ Executor │──publish──→ events:{session_id} ──→  │ SSE Consumer │
│          │                                      │              │
│          │──publish──→ events:global ────────→  │ OTel Export  │
└──────────┘                                      │              │
                                                  │ Gov Consumer │
┌──────────┐                                      │              │
│ Session  │──publish──→ events:{session_id} ──→  │ Webhook      │
│ Service  │                                      └──────────────┘
└──────────┘
```

**Channel naming:**

| Channel Pattern | Scope | Subscribers |
|----------------|-------|-------------|
| `events:{session_id}` | Per-session events | SSE consumer (for that session's client) |
| `events:global` | All events (fan-out) | OTel exporter, Governance consumer, Webhook notifier |

### 2.2 EventBus Interface

**Class: EventBus** — Central event bus. Uses Redis Pub/Sub for fan-out delivery.

Design decisions:
- Pub/Sub (not Streams) for events: fire-and-forget, real-time, no persistence needed
- Events are ephemeral — if a consumer is down, events are lost (acceptable for SSE/tracing)
- Durable event delivery (audit) uses write-behind buffer in GovernanceModule, not event bus

**Constructor parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| publisher | EventPublisher | Low-level Redis Pub/Sub publisher |
| consumers | list[EventConsumer] | List of event consumers to manage |

Internal state: _subscription_tasks (list of asyncio.Task) tracks running consumer tasks.

**Methods:**

- **start() -> None** — Start all consumer subscription loops. Creates an asyncio task for each consumer's start() method and tracks them in _subscription_tasks.

- **stop() -> None** — Cancel all consumer tasks, wait for graceful shutdown. Cancels each task and gathers results with return_exceptions=True.

- **publish(event: AgentEvent) -> None** — Publish event to both session-specific and global channels. Non-blocking, fire and forget. Serializes the event to JSON via model_dump_json(), then publishes to two channels:
  1. Session-specific channel: `events:{event.session_id}` (SSE consumer listens here)
  2. Global channel: `events:global` (OTel, Governance, Webhook)

### 2.3 EventPublisher (Redis Pub/Sub)

**Class: EventPublisher** — Low-level Redis Pub/Sub publisher.

**Constructor parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| redis | Redis | Redis connection instance |

**Methods:**

- **publish(channel: str, message: str) -> int** — Publish message to Redis Pub/Sub channel. Returns number of subscribers that received the message. Delegates directly to redis.publish().

### 2.4 EventConsumer Protocol

**Protocol: EventConsumer** — Interface for event bus consumers. All consumers must implement the following methods:

| Method | Parameters | Return Type | Description |
|--------|------------|-------------|-------------|
| start() | (none) | None | Start consuming events. Runs until cancelled. |
| stop() | (none) | None | Graceful shutdown. |
| on_event(event) | event: AgentEvent | None | Handle a single event. |

### 2.5 Consumer Implementations

#### 2.5.1 SSE Consumer

**Class: SSEConsumer** — Subscribes to session-specific channels. Bridges Redis Pub/Sub to SSE streams for connected clients.

Lifecycle:
1. Client connects to GET /sessions/{id}/stream
2. SSEManager creates subscription to events:{session_id}
3. Events flow: Redis Pub/Sub -> SSEConsumer -> SSEManager -> HTTP SSE response
4. Client disconnects -> unsubscribe from channel

**Constructor parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| redis | Redis | Redis connection instance |

Internal state: _subscriptions (dict[str, redis.client.PubSub]) maps session_id to its PubSub instance.

**Methods:**

- **subscribe(session_id: str) -> AsyncIterator[AgentEvent]** — Subscribe to a session's events. Returns an async iterator. Used by SSEManager to yield events to the SSE response. Creates a PubSub instance, subscribes to channel `events:{session_id}`, stores the subscription, and yields AgentEvent objects parsed from incoming messages. On completion (or cancellation), unsubscribes from the channel, closes the PubSub, and removes the subscription from the internal dict.

- **unsubscribe(session_id: str) -> None** — Remove and close a session's PubSub subscription if it exists.

#### 2.5.2 OTel Trace Consumer

**Class: TraceConsumer** — Subscribes to global channel. Converts AgentEvents to OpenTelemetry spans.

**Constructor parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| redis | Redis | Redis connection instance |
| tracer_provider | TracerProvider | OpenTelemetry tracer provider; a tracer named "agent-platform" is obtained from it |

**Methods:**

- **start() -> None** — Creates a PubSub instance, subscribes to "events:global", and listens for messages in a loop. Each received message is deserialized to AgentEvent and passed to on_event().

- **on_event(event: AgentEvent) -> None** — Handles events based on type:
  - **LLM_CALL_END**: Creates an OpenTelemetry span "llm.chat" with attributes: llm.model, llm.prompt_tokens, llm.completion_tokens, llm.cost_usd, llm.latency_ms (all sourced from event.data).
  - **TOOL_RESULT**: Creates an OpenTelemetry span "tool.invoke" with attributes: tool.name, tool.is_error, tool.latency_ms (all sourced from event.data).
  - Other event types: Additional spans as needed.

#### 2.5.3 Governance Consumer

**Class: GovernanceConsumer** — Subscribes to global channel. Routes events to Governance module (audit + cost tracking).

Note: This is a BACKUP path. Primary audit recording is done synchronously by Executor via governance.record_audit() (write-behind). This consumer catches any events that bypass the direct path.

**Constructor parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| redis | Redis | Redis connection instance |
| governance | GovernancePort | Governance module port for cost tracking |

**Methods:**

- **start() -> None** — Creates a PubSub instance, subscribes to "events:global", and listens for messages in a loop. Each received message is deserialized to AgentEvent and passed to on_event().

- **on_event(event: AgentEvent) -> None** — Handles events based on type:
  - **LLM_CALL_END**: Calls governance.track_cost() with a CostEvent containing: timestamp, tenant_id, agent_id, session_id, step_index (default 0), event_type="llm_call", provider, model, input_tokens, output_tokens, cost_usd (default 0). All values sourced from the event.
  - **SESSION_COMPLETED**: Calls governance.rollup_session_cost(event.session_id) to trigger cost rollup for the completed session.

#### 2.5.4 Webhook Consumer (Phase 1 — simple)

**Class: WebhookConsumer** — Subscribes to global channel. Sends webhook notifications to external systems for configured events.

**Constructor parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| redis | Redis | Redis connection instance |
| http_client | httpx.AsyncClient | HTTP client for sending webhook requests |

**Methods:**

- **on_event(event: AgentEvent) -> None** — Handles webhook notifications. Only sends webhooks for specific event types: SESSION_COMPLETED, APPROVAL_REQUESTED, ERROR. For all other event types, returns immediately.

  Workflow:
  1. Check if event type is in the allowed set; if not, return.
  2. Look up webhook URL from agent/tenant config via _get_webhook_url(event.tenant_id, event.agent_id). If no URL configured, return.
  3. Build payload with fields: event_type (string value), session_id, agent_id, timestamp (ISO format), data.
  4. POST payload as JSON to the webhook URL with a 10-second timeout.
  5. On HTTP error: log warning, do not retry (fire-and-forget for Phase 1).

---

## 3. SSE Streaming

### 3.1 Architecture

```
Client (browser/SDK)          API Server                   Redis Pub/Sub
       │                          │                             │
       │──GET /sessions/{id}/     │                             │
       │     stream ─────────────→│                             │
       │                          │──subscribe ────────────────→│
       │                          │  channel: events:{id}       │
       │                          │                             │
       │                          │   [Executor publishes       │
       │                          │    events to channel]       │
       │                          │                             │
       │                          │◄──event message─────────────│
       │◄──SSE: event: thought────│                             │
       │     data: {"content":..} │                             │
       │                          │◄──event message─────────────│
       │◄──SSE: event: tool_call──│                             │
       │     data: {"tool":...}   │                             │
       │                          │◄──event message─────────────│
       │◄──SSE: event: final──────│                             │
       │     data: {"answer":...} │                             │
       │                          │                             │
       │  [connection closed]     │──unsubscribe ──────────────→│
```

### 3.2 SSE Endpoint

**Route:** GET /sessions/{session_id}/stream (defined in src/api/routes/stream.py)

Uses sse-starlette's EventSourceResponse.

**Endpoint: stream_session_events**

Parameters:

| Parameter | Type | Source | Description |
|-----------|------|--------|-------------|
| request | Request | FastAPI | The incoming HTTP request |
| session_id | str | Path | The session to stream events for |
| tenant_id | str | Depends(get_current_tenant) | Authenticated tenant ID |
| state | AppState | Depends(get_app_state) | Application state containing services |

SSE endpoint for real-time session events.

Event format (Server-Sent Events): each event contains an "event" field (the event type), a "data" field (JSON payload), and an "id" field (event ID).

Event types supported: step_start, thought, tool_call, tool_result, final_answer, error, budget_warning, approval_requested, session_completed.

Behavior:
1. Verify session exists and belongs to tenant. If not found, raise HTTP 404 "Session not found".
2. Return an EventSourceResponse wrapping the _event_generator async generator.

**Internal function: _event_generator(request, session_id, state) -> AsyncIterator[dict]**

Async generator that yields SSE events. Runs until client disconnects or session completes.

1. Obtains the SSE consumer from state.event_bus.sse_consumer.
2. Subscribes to the session's events via sse_consumer.subscribe(session_id).
3. For each event received, checks if client disconnected (request.is_disconnected()); if so, breaks.
4. Maps AgentEvent to SSE event format: yields a dict with keys "event" (event type value), "data" (serialized event data), "id" (event ID).
5. Stops streaming after terminal events: SESSION_COMPLETED, FINAL_ANSWER, ERROR.

**Internal function: _serialize_event_data(event: AgentEvent) -> str**

Serializes event data for SSE using orjson. Filters sensitive fields so the client receives only what they need. Serialization varies by event type:

| Event Type | Fields Included |
|------------|----------------|
| THOUGHT | content |
| TOOL_CALL | tool_name, arguments |
| TOOL_RESULT | tool_name, content_preview (default ""), is_error (default False) |
| FINAL_ANSWER | content, total_steps, total_cost_usd |
| BUDGET_WARNING | budget_type, usage_ratio |
| APPROVAL_REQUESTED | approval_id, tool_name, reason |
| ERROR | message, retryable (default False) |
| (all others) | Full event.data passed through |

### 3.3 SSE Event Format (Wire Protocol)

The SSE wire format uses standard Server-Sent Events structure. Each event contains three lines: event (the type), data (JSON payload), and id (unique event identifier), separated by blank lines. Example event sequence:

- **step_start** event: data includes step_index and pattern (e.g., step_index: 1, pattern: "react"), id: evt_abc123
- **thought** event: data includes content (e.g., "I need to search the database for..."), id: evt_abc124
- **tool_call** event: data includes tool_name and arguments (e.g., tool_name: "mcp:database:query", arguments with sql), id: evt_abc125
- **tool_result** event: data includes tool_name, content_preview, is_error (e.g., content_preview: "[3 rows]", is_error: false), id: evt_abc126
- **final_answer** event: data includes content, total_steps, total_cost_usd (e.g., content: "Based on the query results...", total_steps: 2, total_cost_usd: 0.024), id: evt_abc127

### 3.4 Client Reconnection

SSE natively supports reconnection via `Last-Event-ID` header.

**Endpoint behavior with Last-Event-ID:**

The stream_session_events endpoint accepts an optional last_event_id parameter (from the Last-Event-ID HTTP header).

Reconnection logic:
1. Check session state — if COMPLETED/FAILED, return final event only.
2. If RUNNING, subscribe and continue streaming from current state.
3. Events between disconnect and reconnect are LOST (acceptable for Phase 1).

Phase 2: buffer recent events in Redis for replay on reconnect.

### 3.5 Backpressure & Limits

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max concurrent SSE connections per tenant | 200 | Prevent resource exhaustion |
| SSE keep-alive interval | 15s | Prevent proxy/LB timeout (most default 60s) |
| Max event size | 64KB | Prevent memory issues with large tool results |
| Event truncation | Tool results > 4KB -> `content_preview` only | Client can fetch full result via API |

SSE keep-alive is handled by sse-starlette's ping parameter. The EventSourceResponse is constructed with ping=15, which sends an SSE comment every 15 seconds to keep the connection alive and prevent proxy/load-balancer timeouts.

---

## 4. Task Queue (Redis Streams)

### 4.1 Architecture

```
┌──────────────┐     XADD      ┌─────────────────────┐     XREADGROUP    ┌──────────────┐
│  Session     │──────────────→│  Redis Stream        │──────────────────→│  Worker Pool │
│  Service     │               │  tasks:{tenant_id}   │                   │              │
│              │               │                      │                   │  ┌────────┐  │
│  (enqueue    │               │  Consumer Group:     │                   │  │Worker 1│  │
│   execution  │               │  "executor_group"    │                   │  │Worker 2│  │
│   task)      │               │                      │                   │  │Worker N│  │
│              │               │  ┌───┐┌───┐┌───┐    │                   │  └────────┘  │
└──────────────┘               │  │T1 ││T2 ││T3 │    │                   │              │
                               │  └───┘└───┘└───┘    │                   │  (XACK after │
                               └─────────────────────┘                   │   completion) │
                                        │                                └──────────────┘
                                        │ (unacked, timed out)
                                        v
                               ┌─────────────────────┐
                               │  Dead-Letter Stream  │
                               │  dlq:{tenant_id}     │
                               └─────────────────────┘
```

### 4.2 Task Queue Interface

**Class: TaskQueue** — Redis Streams-based task queue for execution tasks.

Design decisions:
- Redis Streams (not Pub/Sub) for tasks: persistent, consumer groups, ACK semantics
- Per-tenant streams for isolation and independent scaling
- Consumer groups for load balancing across workers

**Constructor parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| redis | Redis | Redis connection instance |

**Methods:**

- **enqueue(task: ExecutionTask) -> str** — Add execution task to stream. Returns stream message ID. Serializes the task to JSON, then calls XADD on stream key `tasks:{task.tenant_id}` with field "payload" containing the JSON. Stream is capped at maxlen=10000 (oldest entries trimmed).

- **ensure_consumer_group(tenant_id: str) -> None** — Create consumer group if not exists. Calls XGROUP CREATE on stream `tasks:{tenant_id}` with group name "executor_group", reading from id "0" (beginning), with mkstream=True (creates stream if it does not exist). Silently ignores BUSYGROUP error (group already exists).

- **dequeue(tenant_id: str, consumer_name: str, count: int = 1, block_ms: int = 5000) -> list[tuple[str, ExecutionTask]]** — Read next task(s) from stream via consumer group. Blocks up to block_ms milliseconds if no messages available. Returns list of (message_id, task) tuples. Uses XREADGROUP with groupname "executor_group", the given consumer name, and ">" selector (only new messages). Deserializes payload field from each message into ExecutionTask.

- **ack(tenant_id: str, message_id: str) -> None** — Acknowledge successful task processing. Calls XACK on stream `tasks:{tenant_id}` for group "executor_group" with the given message_id.

- **get_pending(tenant_id: str, min_idle_ms: int = 60000) -> list[dict]** — Get pending (unacked) messages older than min_idle_ms. Used for dead-letter detection and re-delivery. Calls XPENDING with range "-" to "+" and count 100, then filters results to only include entries where time_since_delivered exceeds min_idle_ms.

- **reclaim(tenant_id: str, message_id: str, consumer_name: str, min_idle_ms: int = 60000) -> list** — Claim a pending message from a dead/slow consumer. Used by dead-letter processor to re-assign stuck tasks. Calls XCLAIM on stream `tasks:{tenant_id}` for group "executor_group", transferring ownership to the specified consumer_name, with the given min_idle_time and message_id.

- **move_to_dlq(tenant_id: str, message_id: str, reason: str) -> None** — Move a permanently failed task to dead-letter queue (after max retries exceeded). Reads the original message from stream `tasks:{tenant_id}` using XRANGE, adds failure metadata fields (dlq_reason, dlq_at with UTC timestamp, original_stream), writes to dead-letter stream `dlq:{tenant_id}` via XADD (capped at maxlen=1000), then ACKs the original message to remove it from pending.

### 4.3 Task Worker Implementation

**Class: TaskWorker** — Executor worker process. Consumes tasks from Redis Streams. Runs as separate process(es), auto-scaled via K8s HPA on queue depth.

**Constructor parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| task_queue | TaskQueue | (required) | Task queue instance |
| executor | AgentExecutor | (required) | Agent executor for running tasks |
| tenant_ids | list[str] | (required) | List of tenant IDs to consume tasks for |
| consumer_name | str or None | None | Consumer name; defaults to "worker-{pid}-{random_hex8}" |

Internal state: _running (bool) controls the main loop.

**Methods:**

- **run() -> None** — Main worker loop:
  1. Ensure consumer groups exist for all tenant_ids.
  2. Start dead-letter monitor as a background asyncio task.
  3. Poll for tasks across tenant streams by calling _poll_and_execute() in a loop while _running is True.
  4. On exit, cancel the dead-letter monitor task.

- **_poll_and_execute() -> None** — Poll all tenant streams, execute first available task. Iterates through each tenant_id, calls dequeue with count=1 and block_ms=1000 (block 1 second per tenant, then rotate). For each dequeued task:
  - On success: calls executor.execute(task) then acks the message.
  - On exception: does NOT ack (message stays in pending list). Logs error with task_id, session_id, and error message via structlog. Dead-letter monitor will handle re-delivery or DLQ.

- **_dead_letter_monitor() -> None** — Periodically checks for stuck tasks (pending longer than threshold). Runs every 30 seconds. For each tenant_id, calls get_pending with min_idle_ms=120000 (2 minutes without ACK). For each stuck entry:
  - If delivery count >= 3 (max retries exceeded): moves to DLQ via move_to_dlq with reason "Max retries exceeded ({delivery_count} deliveries)".
  - Otherwise: reclaims the message for retry via reclaim with min_idle_ms=120000.

- **shutdown() -> None** — Graceful shutdown: sets _running to False to stop polling after the current iteration completes.

### 4.4 Task Lifecycle

```
Session Service                  Redis Stream                Worker              Executor
     │                               │                          │                    │
     │──XADD(ExecutionTask)─────────→│                          │                    │
     │                               │ [message in stream]      │                    │
     │                               │                          │                    │
     │                               │◄──XREADGROUP────────────│                    │
     │                               │──(message_id, task)─────→│                    │
     │                               │                          │                    │
     │                               │                          │──execute(task)────→│
     │                               │                          │                    │
     │                               │                          │  [execution runs...│
     │                               │                          │   emits events     │
     │                               │                          │   via Event Bus]   │
     │                               │                          │                    │
     │                               │                          │◄──result───────────│
     │                               │                          │                    │
     │                               │◄──XACK(message_id)──────│                    │
     │                               │  [message removed from   │                    │
     │                               │   pending entries list]   │                    │
```

**Failure scenario:**

```
Worker A                     Redis Stream               Worker B (reclaims)
  │                               │                          │
  │◄──XREADGROUP─────────────────│                          │
  │   (msg_id, task)              │                          │
  │                               │                          │
  │──execute(task)                │                          │
  │   CRASH ✗                     │                          │
  │                               │                          │
  │  [msg stays in PEL            │                          │
  │   (Pending Entries List)]     │                          │
  │                               │                          │
  │  [2 min timeout...]           │                          │
  │                               │                          │
  │                               │◄──XCLAIM(msg_id)─────────│
  │                               │──(reclaimed message)─────→│
  │                               │                          │
  │                               │                          │──execute(task) ──→
  │                               │                          │  [resume from
  │                               │                          │   checkpoint]
  │                               │◄──XACK(msg_id)──────────│
```

### 4.5 Worker Scaling

| Metric | Trigger | Action |
|--------|---------|--------|
| Stream length (`XLEN`) | > 100 pending tasks | Scale up workers |
| Stream length | < 10 pending tasks | Scale down workers |
| PEL size | > 20 unacked | Alert — workers may be stuck |
| DLQ size | > 0 | Alert — tasks permanently failing |

**K8s HPA Configuration for executor workers:**

| Field | Value |
|-------|-------|
| API version | autoscaling/v2 |
| Kind | HorizontalPodAutoscaler |
| Target resource kind | Deployment |
| Target resource name | executor-worker |
| Min replicas | 2 |
| Max replicas | 20 |
| Metric type | External |
| Metric name | redis_stream_pending_messages |
| Target type | AverageValue |
| Target average value | 10 (10 pending tasks per worker) |

---

## 5. EventEmitter (Executor-side)

**Class: EventEmitter** — Used by Executor to emit events during step execution. Wraps EventBus.publish with convenience methods.

**Constructor parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| event_bus | EventBus | The central event bus instance |

**Methods:**

- **emit(events: list[AgentEvent]) -> None** — Emit multiple events (typically from one step). Iterates through the list and publishes each event via the event bus.

- **emit_step_start(session_id: str, tenant_id: str, agent_id: str, step_index: int) -> None** — Publishes a STEP_START event. Creates an AgentEvent with a new UUID, type STEP_START, the given identifiers, current UTC timestamp, and data containing step_index and pattern ("react").

- **emit_thought(session_id: str, tenant_id: str, agent_id: str, step_index: int, content: str) -> None** — Publishes a THOUGHT event. Creates an AgentEvent with a new UUID, type THOUGHT, the given identifiers, current UTC timestamp, and data containing the thought content.

- **emit_tool_call(session_id: str, tenant_id: str, agent_id: str, step_index: int, tool_name: str, arguments: dict) -> None** — Publishes a TOOL_CALL event. Creates an AgentEvent with a new UUID, type TOOL_CALL, the given identifiers, current UTC timestamp, and data containing tool_name and arguments.

- **emit_final_answer(session_id: str, tenant_id: str, agent_id: str, step_index: int, content: str, total_steps: int, total_cost_usd: float) -> None** — Publishes a FINAL_ANSWER event. Creates an AgentEvent with a new UUID, type FINAL_ANSWER, the given identifiers, current UTC timestamp, and data containing content, total_steps, and total_cost_usd.

---

## 6. Resolved Questions

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Pub/Sub vs Streams for events? | Pub/Sub | Events are ephemeral, real-time. No need for persistence or replay. Simpler model |
| 2 | Pub/Sub vs Streams for tasks? | Streams | Tasks need persistence, ACK semantics, consumer groups, dead-letter handling |
| 3 | Event persistence for SSE reconnect? | Phase 1: no replay (events lost). Phase 2: buffer last N events in Redis | Simplicity. Most clients will not disconnect mid-session |
| 4 | Per-tenant vs global task stream? | Per-tenant streams | Isolation, independent scaling, no noisy-neighbor |
| 5 | Worker scaling metric? | Redis Stream pending count | Direct measure of queue pressure. Available via Redis metrics |
| 6 | DLQ handling? | Separate stream per tenant | Simple, queryable, independent management |
| 7 | SSE vs WebSocket Phase 1? | SSE | Unidirectional (server -> client) is sufficient for Phase 1. Simpler, HTTP-native |

---

## 7. Tech Stack

| Component | Technology | Phase |
|-----------|-----------|-------|
| **Event Bus** | Redis Pub/Sub | 1 |
| **SSE streaming** | `sse-starlette` + FastAPI | 1 |
| **Task Queue** | Redis Streams + Consumer Groups | 1 |
| **Dead-letter queue** | Redis Streams (separate) | 1 |
| **Event serialization** | `orjson` (JSON) | 1 |
| **WebSocket** | FastAPI WebSocket | 2 |
| **Event replay buffer** | Redis List (recent events) | 2 |

---

## 8. Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| Event publish (Redis Pub/Sub) | < 1ms | Single PUBLISH command |
| Event subscribe + receive | < 2ms | Redis Pub/Sub latency |
| SSE event delivery (end-to-end) | < 5ms | Publish -> client receives |
| Task enqueue (XADD) | < 1ms | Single Redis command |
| Task dequeue (XREADGROUP) | < 2ms (+ block time) | Block up to 5s if empty |
| Task ACK (XACK) | < 1ms | Single Redis command |
| Dead-letter check cycle | < 100ms | XPENDING scan |
| SSE keep-alive overhead | Negligible | 1 comment per 15s per connection |
| Max concurrent SSE connections | 10,000 per API pod | Limited by file descriptors and memory |
