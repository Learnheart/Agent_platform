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

```python
class EventBus:
    """
    Central event bus. Uses Redis Pub/Sub for fan-out delivery.

    Design decisions:
    - Pub/Sub (not Streams) for events: fire-and-forget, real-time, no persistence needed
    - Events are ephemeral — if a consumer is down, events are lost (acceptable for SSE/tracing)
    - Durable event delivery (audit) uses write-behind buffer in GovernanceModule, not event bus
    """

    def __init__(
        self,
        publisher: EventPublisher,
        consumers: list[EventConsumer],
    ):
        self._publisher = publisher
        self._consumers = consumers
        self._subscription_tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start all consumer subscription loops."""
        for consumer in self._consumers:
            task = asyncio.create_task(consumer.start())
            self._subscription_tasks.append(task)

    async def stop(self) -> None:
        """Cancel all consumer tasks, wait for graceful shutdown."""
        for task in self._subscription_tasks:
            task.cancel()
        await asyncio.gather(*self._subscription_tasks, return_exceptions=True)

    async def publish(self, event: AgentEvent) -> None:
        """
        Publish event to both session-specific and global channels.
        Non-blocking — fire and forget.
        """
        payload = event.model_dump_json()

        # Session-specific channel (SSE consumer listens here)
        await self._publisher.publish(
            channel=f"events:{event.session_id}",
            message=payload,
        )

        # Global channel (OTel, Governance, Webhook)
        await self._publisher.publish(
            channel="events:global",
            message=payload,
        )
```

### 2.3 EventPublisher (Redis Pub/Sub)

```python
class EventPublisher:
    """Low-level Redis Pub/Sub publisher."""

    def __init__(self, redis: Redis):
        self._redis = redis

    async def publish(self, channel: str, message: str) -> int:
        """
        Publish message to Redis Pub/Sub channel.
        Returns number of subscribers that received the message.
        """
        return await self._redis.publish(channel, message)
```

### 2.4 EventConsumer Protocol

```python
class EventConsumer(Protocol):
    """Interface for event bus consumers."""

    async def start(self) -> None:
        """Start consuming events. Runs until cancelled."""
        ...

    async def stop(self) -> None:
        """Graceful shutdown."""
        ...

    async def on_event(self, event: AgentEvent) -> None:
        """Handle a single event."""
        ...
```

### 2.5 Consumer Implementations

#### 2.5.1 SSE Consumer

```python
class SSEConsumer:
    """
    Subscribes to session-specific channels.
    Bridges Redis Pub/Sub → SSE streams for connected clients.

    Lifecycle:
    - Client connects to GET /sessions/{id}/stream
    - SSEManager creates subscription to events:{session_id}
    - Events flow: Redis Pub/Sub → SSEConsumer → SSEManager → HTTP SSE response
    - Client disconnects → unsubscribe from channel
    """

    def __init__(self, redis: Redis):
        self._redis = redis
        self._subscriptions: dict[str, redis.client.PubSub] = {}

    async def subscribe(self, session_id: str) -> AsyncIterator[AgentEvent]:
        """
        Subscribe to a session's events. Returns async iterator.
        Used by SSEManager to yield events to SSE response.
        """
        pubsub = self._redis.pubsub()
        channel = f"events:{session_id}"
        await pubsub.subscribe(channel)
        self._subscriptions[session_id] = pubsub

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    event = AgentEvent.model_validate_json(message["data"])
                    yield event
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            self._subscriptions.pop(session_id, None)

    async def unsubscribe(self, session_id: str) -> None:
        pubsub = self._subscriptions.pop(session_id, None)
        if pubsub:
            await pubsub.unsubscribe()
            await pubsub.aclose()
```

#### 2.5.2 OTel Trace Consumer

```python
class TraceConsumer:
    """
    Subscribes to global channel.
    Converts AgentEvents to OpenTelemetry spans.
    """

    def __init__(self, redis: Redis, tracer_provider):
        self._redis = redis
        self._tracer = tracer_provider.get_tracer("agent-platform")

    async def start(self) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe("events:global")

        async for message in pubsub.listen():
            if message["type"] == "message":
                event = AgentEvent.model_validate_json(message["data"])
                await self.on_event(event)

    async def on_event(self, event: AgentEvent) -> None:
        match event.type:
            case AgentEventType.LLM_CALL_END:
                with self._tracer.start_as_current_span("llm.chat") as span:
                    span.set_attribute("llm.model", event.data.get("model"))
                    span.set_attribute("llm.prompt_tokens", event.data.get("prompt_tokens"))
                    span.set_attribute("llm.completion_tokens", event.data.get("completion_tokens"))
                    span.set_attribute("llm.cost_usd", event.data.get("cost_usd"))
                    span.set_attribute("llm.latency_ms", event.data.get("latency_ms"))

            case AgentEventType.TOOL_RESULT:
                with self._tracer.start_as_current_span("tool.invoke") as span:
                    span.set_attribute("tool.name", event.data.get("tool_name"))
                    span.set_attribute("tool.is_error", event.data.get("is_error"))
                    span.set_attribute("tool.latency_ms", event.data.get("latency_ms"))

            # Other event types → additional spans as needed
```

#### 2.5.3 Governance Consumer

```python
class GovernanceConsumer:
    """
    Subscribes to global channel.
    Routes events to Governance module (audit + cost tracking).

    Note: This is a BACKUP path. Primary audit recording is done
    synchronously by Executor via governance.record_audit() (write-behind).
    This consumer catches any events that bypass the direct path.
    """

    def __init__(self, redis: Redis, governance: GovernancePort):
        self._redis = redis
        self._governance = governance

    async def start(self) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe("events:global")

        async for message in pubsub.listen():
            if message["type"] == "message":
                event = AgentEvent.model_validate_json(message["data"])
                await self.on_event(event)

    async def on_event(self, event: AgentEvent) -> None:
        # Cost tracking for LLM calls
        if event.type == AgentEventType.LLM_CALL_END:
            await self._governance.track_cost(CostEvent(
                timestamp=event.timestamp,
                tenant_id=event.tenant_id,
                agent_id=event.agent_id,
                session_id=event.session_id,
                step_index=event.step_index or 0,
                event_type="llm_call",
                provider=event.data.get("provider"),
                model=event.data.get("model"),
                input_tokens=event.data.get("prompt_tokens"),
                output_tokens=event.data.get("completion_tokens"),
                cost_usd=event.data.get("cost_usd", 0),
            ))

        # Session completion → trigger cost rollup
        if event.type == AgentEventType.SESSION_COMPLETED:
            await self._governance.rollup_session_cost(event.session_id)
```

#### 2.5.4 Webhook Consumer (Phase 1 — simple)

```python
class WebhookConsumer:
    """
    Subscribes to global channel.
    Sends webhook notifications to external systems for configured events.
    """

    def __init__(self, redis: Redis, http_client: httpx.AsyncClient):
        self._redis = redis
        self._http_client = http_client

    async def on_event(self, event: AgentEvent) -> None:
        # Only send webhooks for specific event types
        if event.type not in {
            AgentEventType.SESSION_COMPLETED,
            AgentEventType.APPROVAL_REQUESTED,
            AgentEventType.ERROR,
        }:
            return

        # Lookup webhook URL from agent/tenant config
        webhook_url = await self._get_webhook_url(event.tenant_id, event.agent_id)
        if not webhook_url:
            return

        payload = {
            "event_type": event.type.value,
            "session_id": event.session_id,
            "agent_id": event.agent_id,
            "timestamp": event.timestamp.isoformat(),
            "data": event.data,
        }

        try:
            await self._http_client.post(
                webhook_url,
                json=payload,
                timeout=10.0,
            )
        except httpx.HTTPError:
            # Log warning, don't retry (fire-and-forget for Phase 1)
            pass
```

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

```python
# src/api/routes/stream.py

from sse_starlette.sse import EventSourceResponse
from fastapi import APIRouter, Depends, Request

router = APIRouter()


@router.get("/sessions/{session_id}/stream")
async def stream_session_events(
    request: Request,
    session_id: str,
    tenant_id: str = Depends(get_current_tenant),
    state: AppState = Depends(get_app_state),
):
    """
    SSE endpoint for real-time session events.

    Event format (Server-Sent Events):
        event: {event_type}
        data: {JSON payload}
        id: {event_id}

    Event types:
        step_start, thought, tool_call, tool_result, final_answer,
        error, budget_warning, approval_requested, session_completed
    """
    # Verify session exists and belongs to tenant
    session = await state.session_service.get(tenant_id, session_id)
    if not session:
        raise HTTPException(404, detail="Session not found")

    return EventSourceResponse(
        _event_generator(request, session_id, state),
        media_type="text/event-stream",
    )


async def _event_generator(
    request: Request,
    session_id: str,
    state: AppState,
) -> AsyncIterator[dict]:
    """
    Async generator that yields SSE events.
    Runs until client disconnects or session completes.
    """
    sse_consumer = state.event_bus.sse_consumer

    async for event in sse_consumer.subscribe(session_id):
        # Check if client disconnected
        if await request.is_disconnected():
            break

        # Map AgentEvent → SSE event format
        yield {
            "event": event.type.value,
            "data": _serialize_event_data(event),
            "id": event.id,
        }

        # Stop streaming after terminal events
        if event.type in {
            AgentEventType.SESSION_COMPLETED,
            AgentEventType.FINAL_ANSWER,
            AgentEventType.ERROR,
        }:
            break


def _serialize_event_data(event: AgentEvent) -> str:
    """
    Serialize event data for SSE. Filter sensitive fields.
    Client receives only what they need.
    """
    match event.type:
        case AgentEventType.THOUGHT:
            return orjson.dumps({"content": event.data["content"]}).decode()

        case AgentEventType.TOOL_CALL:
            return orjson.dumps({
                "tool_name": event.data["tool_name"],
                "arguments": event.data["arguments"],
            }).decode()

        case AgentEventType.TOOL_RESULT:
            return orjson.dumps({
                "tool_name": event.data["tool_name"],
                "content_preview": event.data.get("content_preview", ""),
                "is_error": event.data.get("is_error", False),
            }).decode()

        case AgentEventType.FINAL_ANSWER:
            return orjson.dumps({
                "content": event.data["content"],
                "total_steps": event.data.get("total_steps"),
                "total_cost_usd": event.data.get("total_cost_usd"),
            }).decode()

        case AgentEventType.BUDGET_WARNING:
            return orjson.dumps({
                "budget_type": event.data["budget_type"],
                "usage_ratio": event.data["usage_ratio"],
            }).decode()

        case AgentEventType.APPROVAL_REQUESTED:
            return orjson.dumps({
                "approval_id": event.data["approval_id"],
                "tool_name": event.data["tool_name"],
                "reason": event.data["reason"],
            }).decode()

        case AgentEventType.ERROR:
            return orjson.dumps({
                "message": event.data["message"],
                "retryable": event.data.get("retryable", False),
            }).decode()

        case _:
            return orjson.dumps(event.data).decode()
```

### 3.3 SSE Event Format (Wire Protocol)

```
event: step_start
data: {"step_index": 1, "pattern": "react"}
id: evt_abc123

event: thought
data: {"content": "I need to search the database for..."}
id: evt_abc124

event: tool_call
data: {"tool_name": "mcp:database:query", "arguments": {"sql": "SELECT..."}}
id: evt_abc125

event: tool_result
data: {"tool_name": "mcp:database:query", "content_preview": "[3 rows]", "is_error": false}
id: evt_abc126

event: final_answer
data: {"content": "Based on the query results...", "total_steps": 2, "total_cost_usd": 0.024}
id: evt_abc127
```

### 3.4 Client Reconnection

SSE natively supports reconnection via `Last-Event-ID` header.

```python
@router.get("/sessions/{session_id}/stream")
async def stream_session_events(
    request: Request,
    session_id: str,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    ...
):
    """
    If client reconnects with Last-Event-ID:
    1. Check session state — if COMPLETED/FAILED, return final event only
    2. If RUNNING, subscribe and continue streaming from current state
    3. Events between disconnect and reconnect are LOST (acceptable for Phase 1)

    Phase 2: buffer recent events in Redis for replay on reconnect.
    """
```

### 3.5 Backpressure & Limits

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max concurrent SSE connections per tenant | 200 | Prevent resource exhaustion |
| SSE keep-alive interval | 15s | Prevent proxy/LB timeout (most default 60s) |
| Max event size | 64KB | Prevent memory issues with large tool results |
| Event truncation | Tool results > 4KB → `content_preview` only | Client can fetch full result via API |

```python
# SSE keep-alive: send comment every 15s to keep connection alive
async def _event_generator(...):
    last_event_time = time.monotonic()

    async for event in sse_consumer.subscribe(session_id):
        yield _format_event(event)
        last_event_time = time.monotonic()

    # Keep-alive is handled by sse-starlette's ping parameter:
    # EventSourceResponse(..., ping=15)
```

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

```python
class TaskQueue:
    """
    Redis Streams-based task queue for execution tasks.

    Design decisions:
    - Redis Streams (not Pub/Sub) for tasks: persistent, consumer groups, ACK semantics
    - Per-tenant streams for isolation and independent scaling
    - Consumer groups for load balancing across workers
    """

    def __init__(self, redis: Redis):
        self._redis = redis

    async def enqueue(self, task: ExecutionTask) -> str:
        """
        Add execution task to stream.
        Returns stream message ID.
        """
        stream_key = f"tasks:{task.tenant_id}"
        payload = task.model_dump_json()

        message_id = await self._redis.xadd(
            stream_key,
            {"payload": payload},
            maxlen=10000,          # cap stream length (oldest trimmed)
        )
        return message_id

    async def ensure_consumer_group(self, tenant_id: str) -> None:
        """Create consumer group if not exists."""
        stream_key = f"tasks:{tenant_id}"
        try:
            await self._redis.xgroup_create(
                stream_key,
                "executor_group",
                id="0",              # read from beginning
                mkstream=True,       # create stream if not exists
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise  # group already exists — OK

    async def dequeue(
        self,
        tenant_id: str,
        consumer_name: str,
        count: int = 1,
        block_ms: int = 5000,
    ) -> list[tuple[str, ExecutionTask]]:
        """
        Read next task(s) from stream via consumer group.
        Blocks up to block_ms if no messages available.
        Returns list of (message_id, task) tuples.
        """
        stream_key = f"tasks:{tenant_id}"

        messages = await self._redis.xreadgroup(
            groupname="executor_group",
            consumername=consumer_name,
            streams={stream_key: ">"},   # ">" = only new messages
            count=count,
            block=block_ms,
        )

        results = []
        for stream, stream_messages in messages:
            for msg_id, fields in stream_messages:
                task = ExecutionTask.model_validate_json(fields[b"payload"])
                results.append((msg_id, task))

        return results

    async def ack(self, tenant_id: str, message_id: str) -> None:
        """Acknowledge successful task processing."""
        stream_key = f"tasks:{tenant_id}"
        await self._redis.xack(stream_key, "executor_group", message_id)

    async def get_pending(
        self,
        tenant_id: str,
        min_idle_ms: int = 60000,
    ) -> list[dict]:
        """
        Get pending (unacked) messages older than min_idle_ms.
        Used for dead-letter detection and re-delivery.
        """
        stream_key = f"tasks:{tenant_id}"

        pending = await self._redis.xpending_range(
            stream_key,
            "executor_group",
            min="-",
            max="+",
            count=100,
        )

        return [
            p for p in pending
            if p["time_since_delivered"] > min_idle_ms
        ]

    async def reclaim(
        self,
        tenant_id: str,
        message_id: str,
        consumer_name: str,
        min_idle_ms: int = 60000,
    ) -> list:
        """
        Claim a pending message from a dead/slow consumer.
        Used by dead-letter processor to re-assign stuck tasks.
        """
        stream_key = f"tasks:{tenant_id}"

        return await self._redis.xclaim(
            stream_key,
            "executor_group",
            consumer_name,
            min_idle_time=min_idle_ms,
            message_ids=[message_id],
        )

    async def move_to_dlq(self, tenant_id: str, message_id: str, reason: str) -> None:
        """
        Move a permanently failed task to dead-letter queue.
        After max retries exceeded.
        """
        stream_key = f"tasks:{tenant_id}"
        dlq_key = f"dlq:{tenant_id}"

        # Read the original message
        messages = await self._redis.xrange(stream_key, min=message_id, max=message_id)
        if messages:
            _, fields = messages[0]
            # Add failure metadata
            fields[b"dlq_reason"] = reason.encode()
            fields[b"dlq_at"] = datetime.utcnow().isoformat().encode()
            fields[b"original_stream"] = stream_key.encode()

            await self._redis.xadd(dlq_key, fields, maxlen=1000)

        # ACK original to remove from pending
        await self._redis.xack(stream_key, "executor_group", message_id)
```

### 4.3 Task Worker Implementation

```python
class TaskWorker:
    """
    Executor worker process. Consumes tasks from Redis Streams.
    Runs as separate process(es), auto-scaled via K8s HPA on queue depth.
    """

    def __init__(
        self,
        task_queue: TaskQueue,
        executor: AgentExecutor,
        tenant_ids: list[str],
        consumer_name: str | None = None,
    ):
        self._queue = task_queue
        self._executor = executor
        self._tenant_ids = tenant_ids
        self._consumer_name = consumer_name or f"worker-{os.getpid()}-{uuid4().hex[:8]}"
        self._running = False

    async def run(self) -> None:
        """
        Main worker loop:
        1. Ensure consumer groups exist
        2. Start dead-letter monitor (background)
        3. Poll for tasks across tenant streams
        4. Execute tasks, ACK on completion
        """
        self._running = True

        # Ensure consumer groups
        for tenant_id in self._tenant_ids:
            await self._queue.ensure_consumer_group(tenant_id)

        # Start dead-letter monitor
        dlq_task = asyncio.create_task(self._dead_letter_monitor())

        try:
            while self._running:
                await self._poll_and_execute()
        finally:
            dlq_task.cancel()

    async def _poll_and_execute(self) -> None:
        """Poll all tenant streams, execute first available task."""
        for tenant_id in self._tenant_ids:
            tasks = await self._queue.dequeue(
                tenant_id=tenant_id,
                consumer_name=self._consumer_name,
                count=1,
                block_ms=1000,      # block 1s per tenant, then rotate
            )

            for message_id, task in tasks:
                try:
                    result = await self._executor.execute(task)
                    await self._queue.ack(tenant_id, message_id)
                except Exception as e:
                    # Don't ACK — message stays in pending list
                    # Dead-letter monitor will handle re-delivery or DLQ
                    structlog.get_logger().error(
                        "task_execution_failed",
                        task_id=task.id,
                        session_id=task.session_id,
                        error=str(e),
                    )

    async def _dead_letter_monitor(self) -> None:
        """
        Periodically check for stuck tasks (pending > threshold).
        Re-claim or move to DLQ based on retry count.
        """
        while self._running:
            await asyncio.sleep(30)  # check every 30s

            for tenant_id in self._tenant_ids:
                pending = await self._queue.get_pending(
                    tenant_id=tenant_id,
                    min_idle_ms=120_000,  # 2 minutes without ACK
                )

                for entry in pending:
                    delivery_count = entry.get("times_delivered", 0)

                    if delivery_count >= 3:
                        # Max retries exceeded → DLQ
                        await self._queue.move_to_dlq(
                            tenant_id=tenant_id,
                            message_id=entry["message_id"],
                            reason=f"Max retries exceeded ({delivery_count} deliveries)",
                        )
                    else:
                        # Re-claim for retry
                        await self._queue.reclaim(
                            tenant_id=tenant_id,
                            message_id=entry["message_id"],
                            consumer_name=self._consumer_name,
                            min_idle_ms=120_000,
                        )

    async def shutdown(self) -> None:
        """Graceful shutdown: finish current task, stop polling."""
        self._running = False
```

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

```yaml
# K8s HPA for executor workers
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
spec:
  scaleTargetRef:
    kind: Deployment
    name: executor-worker
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: External
      external:
        metric:
          name: redis_stream_pending_messages
        target:
          type: AverageValue
          averageValue: "10"    # 10 pending tasks per worker
```

---

## 5. EventEmitter (Executor-side)

```python
class EventEmitter:
    """
    Used by Executor to emit events during step execution.
    Wraps EventBus.publish with convenience methods.
    """

    def __init__(self, event_bus: EventBus):
        self._bus = event_bus

    async def emit(self, events: list[AgentEvent]) -> None:
        """Emit multiple events (typically from one step)."""
        for event in events:
            await self._bus.publish(event)

    async def emit_step_start(self, session_id: str, tenant_id: str, agent_id: str, step_index: int) -> None:
        await self._bus.publish(AgentEvent(
            id=str(uuid4()),
            type=AgentEventType.STEP_START,
            session_id=session_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            step_index=step_index,
            timestamp=datetime.utcnow(),
            data={"step_index": step_index, "pattern": "react"},
        ))

    async def emit_thought(self, session_id: str, tenant_id: str, agent_id: str, step_index: int, content: str) -> None:
        await self._bus.publish(AgentEvent(
            id=str(uuid4()),
            type=AgentEventType.THOUGHT,
            session_id=session_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            step_index=step_index,
            timestamp=datetime.utcnow(),
            data={"content": content},
        ))

    async def emit_tool_call(self, session_id: str, tenant_id: str, agent_id: str, step_index: int, tool_name: str, arguments: dict) -> None:
        await self._bus.publish(AgentEvent(
            id=str(uuid4()),
            type=AgentEventType.TOOL_CALL,
            session_id=session_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            step_index=step_index,
            timestamp=datetime.utcnow(),
            data={"tool_name": tool_name, "arguments": arguments},
        ))

    async def emit_final_answer(self, session_id: str, tenant_id: str, agent_id: str, step_index: int, content: str, total_steps: int, total_cost_usd: float) -> None:
        await self._bus.publish(AgentEvent(
            id=str(uuid4()),
            type=AgentEventType.FINAL_ANSWER,
            session_id=session_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            step_index=step_index,
            timestamp=datetime.utcnow(),
            data={"content": content, "total_steps": total_steps, "total_cost_usd": total_cost_usd},
        ))
```

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
| 7 | SSE vs WebSocket Phase 1? | SSE | Unidirectional (server → client) is sufficient for Phase 1. Simpler, HTTP-native |

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
| SSE event delivery (end-to-end) | < 5ms | Publish → client receives |
| Task enqueue (XADD) | < 1ms | Single Redis command |
| Task dequeue (XREADGROUP) | < 2ms (+ block time) | Block up to 5s if empty |
| Task ACK (XACK) | < 1ms | Single Redis command |
| Dead-letter check cycle | < 100ms | XPENDING scan |
| SSE keep-alive overhead | Negligible | 1 comment per 15s per connection |
| Max concurrent SSE connections | 10,000 per API pod | Limited by file descriptors and memory |
