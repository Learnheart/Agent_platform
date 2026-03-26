# Thiết Kế Chi Tiết: LLM Gateway

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-25
> **Ngày cập nhật:** 2026-03-26
> **Parent:** [Architecture Overview](00-overview.md)
> **Status:** CONFIRMED — Direct Anthropic SDK

---

## 1. Scope

LLM Gateway là abstraction layer giữa Executor và LLM providers. Mọi LLM call đi qua component này.

- Phase 1: Anthropic (Claude) only — direct SDK
- Phase 2: Thêm OpenAI, Gemini adapters qua cùng `LLMGateway` protocol

### 1.1 Quyết Định Kiến Trúc

**ADR-014: Direct Anthropic SDK cho Phase 1**

| | Direct SDK | LiteLLM |
|---|---|---|
| Phase 1 cần | 1 provider | 1 provider |
| Dependencies | `anthropic` (1 lib) | `litellm` + proxy service |
| Streaming control | Full (SDK events) | Proxy layer thêm latency |
| Tool use parsing | SDK native | LiteLLM adapter (potential bugs) |
| Prompt caching | Anthropic API native | Phải qua LiteLLM mapping |
| Debug | Direct stack trace | Thêm proxy layer |
| Phase 2 effort | Viết adapter (~2-3 ngày/provider) | Config thêm provider |

**Quyết định:** Direct Anthropic SDK. Lý do:
1. Phase 1 chỉ cần 1 provider → LiteLLM là overhead không cần thiết
2. Full control over streaming, tool use, prompt caching
3. `LLMGateway` protocol đã abstract sẵn → Phase 2 thêm adapter dễ dàng
4. Ít dependency = ít risk

---

## 2. Interface

### 2.1 LLMGateway Protocol

```python
class LLMGateway(Protocol):
    async def chat(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        """Non-streaming LLM call. Blocks until complete response."""

    async def chat_stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        config: LLMConfig | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Streaming LLM call. Yields events as they arrive."""

    async def count_tokens(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
    ) -> int:
        """Pre-call token count estimation."""
```

### 2.2 Data Models

> Canonical definitions trong [`data-models.md`](data-models.md) Section 5. Summary:

```python
@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] | None
    usage: TokenUsage
    model: str
    provider: str
    latency_ms: float
    stop_reason: str      # "end_turn" | "tool_use" | "max_tokens" | "stop_sequence"

@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int | None = None
    cost_usd: float | None = None

@dataclass
class LLMConfig:
    temperature: float = 1.0
    max_tokens: int = 4096
    timeout_seconds: float = 120.0
    retry_policy: RetryPolicy | None = None

@dataclass
class RetryPolicy:
    max_retries: int = 3
    backoff_base_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    backoff_max_seconds: float = 30.0
    retryable_status_codes: list[int] = field(
        default_factory=lambda: [429, 500, 502, 503, 529]
    )
```

### 2.3 LLMStreamEvent

```python
@dataclass
class LLMStreamEvent:
    type: Literal[
        "text_delta",        # partial text
        "tool_call_start",   # tool call begins: id + name
        "tool_call_delta",   # partial tool arguments (JSON string chunk)
        "tool_call_end",     # tool call complete: full ToolCall
        "usage",             # token usage (arrives near end)
        "done",              # stream finished
        "error",             # stream error
    ]

    # text_delta
    content: str | None = None

    # tool_call_start
    tool_call_id: str | None = None
    tool_name: str | None = None

    # tool_call_delta
    arguments_delta: str | None = None

    # tool_call_end
    tool_call: ToolCall | None = None

    # usage / done
    usage: TokenUsage | None = None
    stop_reason: str | None = None

    # error
    error_message: str | None = None
    error_category: str | None = None
```

**Mapping từ Anthropic SDK events:**

| Anthropic SDK Event | → LLMStreamEvent |
|---|---|
| `content_block_start` (type=text) | — (no-op, wait for deltas) |
| `content_block_delta` (type=text_delta) | `text_delta(content=delta.text)` |
| `content_block_start` (type=tool_use) | `tool_call_start(tool_call_id=block.id, tool_name=block.name)` |
| `content_block_delta` (type=input_json_delta) | `tool_call_delta(tool_call_id=..., arguments_delta=delta.partial_json)` |
| `content_block_stop` (after tool_use) | `tool_call_end(tool_call=assembled_ToolCall)` |
| `message_delta` (usage) | `usage(usage=TokenUsage(...))` |
| `message_stop` | `done(stop_reason=..., usage=...)` |
| Exception | `error(error_message=..., error_category=...)` |

---

## 3. Implementation: AnthropicGateway

### 3.1 Class Structure

```python
class AnthropicGateway:
    """LLMGateway implementation using Anthropic Python SDK."""

    def __init__(self, config: AnthropicGatewayConfig):
        self._client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            max_retries=0,              # we handle retries ourselves
            timeout=httpx.Timeout(
                connect=10.0,
                read=config.default_timeout,
                write=10.0,
                pool=10.0,
            ),
            http_client=httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=config.max_connections,
                    max_keepalive_connections=config.max_keepalive,
                ),
            ),
        )
        self._pricing = config.pricing
        self._default_config = config.default_llm_config

    async def chat(self, model, messages, tools=None, config=None) -> LLMResponse: ...
    async def chat_stream(self, model, messages, tools=None, config=None) -> AsyncIterator[LLMStreamEvent]: ...
    async def count_tokens(self, model, messages, tools=None) -> int: ...
```

### 3.2 Configuration

```python
@dataclass
class AnthropicGatewayConfig:
    api_key: str
    default_timeout: float = 120.0
    max_connections: int = 100        # httpx connection pool max
    max_keepalive: int = 20           # persistent connections
    default_llm_config: LLMConfig = field(default_factory=LLMConfig)
    pricing: ModelPricing = field(default_factory=lambda: DEFAULT_PRICING)
```

### 3.3 chat() — Non-Streaming

```python
async def chat(self, model, messages, tools=None, config=None) -> LLMResponse:
    cfg = config or self._default_config
    anthropic_messages = self._convert_messages(messages)
    anthropic_tools = self._convert_tools(tools) if tools else NOT_GIVEN

    start = time.monotonic()
    response = await self._call_with_retry(
        lambda: self._client.messages.create(
            model=model,
            messages=anthropic_messages,
            tools=anthropic_tools,
            system=self._extract_system(messages),
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
        ),
        retry_policy=cfg.retry_policy,
    )
    latency_ms = (time.monotonic() - start) * 1000

    return LLMResponse(
        content=self._extract_text(response),
        tool_calls=self._extract_tool_calls(response),
        usage=self._build_usage(response.usage, model),
        model=response.model,
        provider="anthropic",
        latency_ms=latency_ms,
        stop_reason=response.stop_reason,
    )
```

### 3.4 chat_stream() — Streaming

```python
async def chat_stream(self, model, messages, tools=None, config=None):
    cfg = config or self._default_config
    anthropic_messages = self._convert_messages(messages)
    anthropic_tools = self._convert_tools(tools) if tools else NOT_GIVEN

    async with self._client.messages.stream(
        model=model,
        messages=anthropic_messages,
        tools=anthropic_tools,
        system=self._extract_system(messages),
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    ) as stream:
        current_tool_id: str | None = None
        current_tool_name: str | None = None
        accumulated_args: str = ""

        async for event in stream:
            match event.type:
                # Text streaming
                case "content_block_delta" if hasattr(event.delta, "text"):
                    yield LLMStreamEvent(
                        type="text_delta",
                        content=event.delta.text,
                    )

                # Tool call start
                case "content_block_start" if event.content_block.type == "tool_use":
                    current_tool_id = event.content_block.id
                    current_tool_name = event.content_block.name
                    accumulated_args = ""
                    yield LLMStreamEvent(
                        type="tool_call_start",
                        tool_call_id=current_tool_id,
                        tool_name=current_tool_name,
                    )

                # Tool call argument delta
                case "content_block_delta" if hasattr(event.delta, "partial_json"):
                    accumulated_args += event.delta.partial_json
                    yield LLMStreamEvent(
                        type="tool_call_delta",
                        tool_call_id=current_tool_id,
                        arguments_delta=event.delta.partial_json,
                    )

                # Tool call end
                case "content_block_stop" if current_tool_id:
                    yield LLMStreamEvent(
                        type="tool_call_end",
                        tool_call=ToolCall(
                            id=current_tool_id,
                            name=current_tool_name,
                            arguments=json.loads(accumulated_args) if accumulated_args else {},
                        ),
                    )
                    current_tool_id = None
                    current_tool_name = None

                # Message complete
                case "message_stop":
                    final = await stream.get_final_message()
                    yield LLMStreamEvent(
                        type="done",
                        usage=self._build_usage(final.usage, model),
                        stop_reason=final.stop_reason,
                    )
```

### 3.5 count_tokens() — Token Estimation

```python
async def count_tokens(self, model, messages, tools=None) -> int:
    """Sử dụng Anthropic SDK count_tokens API.

    Dùng để:
    - Context window budget check trước khi gọi LLM
    - Summarization trigger (khi > threshold)
    - Cost estimation
    """
    anthropic_messages = self._convert_messages(messages)
    anthropic_tools = self._convert_tools(tools) if tools else NOT_GIVEN

    result = await self._client.messages.count_tokens(
        model=model,
        messages=anthropic_messages,
        tools=anthropic_tools,
        system=self._extract_system(messages),
    )
    return result.input_tokens
```

> **Tại sao Anthropic SDK count_tokens thay vì tiktoken?**
> - Anthropic SDK sử dụng cùng tokenizer với model → chính xác 100%
> - tiktoken là tokenizer của OpenAI → sai số khi dùng cho Claude
> - count_tokens API miễn phí, latency < 50ms

### 3.6 Retry Logic

```python
async def _call_with_retry(self, call_fn, retry_policy: RetryPolicy | None = None):
    """Retry LLM calls with exponential backoff.

    Tự handle retry thay vì dùng SDK retry vì:
    - Cần emit events cho mỗi retry (audit, cost tracking)
    - Cần respect budget limits giữa retries
    - Cần custom logic per error category
    """
    policy = retry_policy or RetryPolicy()
    last_error = None

    for attempt in range(1 + policy.max_retries):
        try:
            return await call_fn()
        except anthropic.RateLimitError as e:
            last_error = e
            retry_after = _parse_retry_after(e)
            wait = retry_after or _backoff(attempt, policy)
            await asyncio.sleep(wait)
        except anthropic.InternalServerError as e:
            last_error = e
            wait = _backoff(attempt, policy)
            await asyncio.sleep(wait)
        except anthropic.APITimeoutError as e:
            last_error = e
            if attempt >= policy.max_retries:
                break
            await asyncio.sleep(_backoff(attempt, policy))
        except anthropic.BadRequestError:
            raise  # no retry — malformed request
        except anthropic.AuthenticationError:
            raise  # no retry — invalid API key

    raise last_error

def _backoff(attempt: int, policy: RetryPolicy) -> float:
    wait = policy.backoff_base_seconds * (policy.backoff_multiplier ** attempt)
    return min(wait, policy.backoff_max_seconds)

def _parse_retry_after(error) -> float | None:
    header = getattr(error, "response", None)
    if header and hasattr(header, "headers"):
        val = header.headers.get("retry-after")
        if val:
            return float(val)
    return None
```

---

## 4. Error Taxonomy

| Error | Anthropic Exception | ErrorCategory | Retry | Strategy |
|---|---|---|---|---|
| Rate limit (429) | `RateLimitError` | `LLM_RATE_LIMIT` | Yes | Backoff, respect `Retry-After` header |
| Overloaded (529) | `OverloadedError` | `LLM_SERVER_ERROR` | Yes | Backoff 1s → 2s → 4s |
| Server error (500/502/503) | `InternalServerError` | `LLM_SERVER_ERROR` | Yes | Up to 3x, backoff 1s → 2s → 4s |
| Content refusal | `BadRequestError` (content filtered) | `LLM_CONTENT_REFUSAL` | No | Return refusal to executor |
| Malformed response | JSON parse error | `LLM_MALFORMED_RESPONSE` | Yes | 1x retry same prompt |
| Timeout | `APITimeoutError` | `LLM_TIMEOUT` | Yes | 2x retry, tăng timeout mỗi lần |
| Auth error (401/403) | `AuthenticationError` | — | No | Fail immediately, alert |

### 4.1 Error Wrapping

```python
class LLMError(Exception):
    """Base error for LLM Gateway."""
    def __init__(self, message: str, category: ErrorCategory, retryable: bool, cause: Exception | None = None):
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.cause = cause
```

Executor nhận `LLMError` → xử lý theo `ErrorCategory` (xem [`data-models.md`](data-models.md) Section 9.2).

---

## 5. Cost Calculation

### 5.1 Pricing Table

> Hardcode trong config. Lý do: pricing ít thay đổi, cập nhật khi deploy. Tránh runtime dependency.

```python
@dataclass
class ModelPricing:
    input_per_million: float     # USD per 1M input tokens
    output_per_million: float    # USD per 1M output tokens
    cached_input_per_million: float | None = None  # prompt caching discount

DEFAULT_PRICING: dict[str, ModelPricing] = {
    "claude-sonnet-4-5-20250514": ModelPricing(
        input_per_million=3.0,
        output_per_million=15.0,
        cached_input_per_million=0.3,
    ),
    "claude-haiku-4-5-20251001": ModelPricing(
        input_per_million=0.80,
        output_per_million=4.0,
        cached_input_per_million=0.08,
    ),
}
```

### 5.2 Cost Calculation Logic

```python
def calculate_cost(usage: TokenUsage, model: str) -> float:
    pricing = DEFAULT_PRICING.get(model)
    if not pricing:
        return 0.0  # unknown model → log warning, return 0

    input_cost = (usage.prompt_tokens / 1_000_000) * pricing.input_per_million
    output_cost = (usage.completion_tokens / 1_000_000) * pricing.output_per_million

    # Subtract cached tokens discount
    if usage.cached_tokens and pricing.cached_input_per_million is not None:
        cached_saving = (usage.cached_tokens / 1_000_000) * (
            pricing.input_per_million - pricing.cached_input_per_million
        )
        input_cost -= cached_saving

    return round(input_cost + output_cost, 6)
```

---

## 6. Connection & Timeout

### 6.1 Connection Pooling

```python
# httpx connection pool config
httpx.Limits(
    max_connections=100,       # total connections across all hosts
    max_keepalive_connections=20,  # persistent keep-alive connections
)
```

- Phase 1 target: 1000 concurrent sessions → ~100 simultaneous LLM calls (execution is sequential per session)
- `max_connections=100` đủ cho Phase 1
- Phase 2: tune based on load test results

### 6.2 Timeout Strategy

```python
httpx.Timeout(
    connect=10.0,    # TCP connection timeout
    read=120.0,      # read timeout — matches LLMConfig.timeout_seconds
    write=10.0,      # write timeout (sending request)
    pool=10.0,       # waiting for available connection from pool
)
```

**Streaming timeout:**
- `read=120.0` áp dụng cho inter-chunk timeout (thời gian giữa 2 chunks)
- Anthropic SDK tự handle: nếu > 120s không nhận chunk mới → `APITimeoutError`
- Không cần custom timer — httpx + SDK đã handle

**Override per-call:**
- `LLMConfig.timeout_seconds` override `read` timeout per call
- Executor có thể tăng timeout cho complex queries

---

## 7. Prompt Caching

> Anthropic prompt caching giảm cost cho repeated system prompts + tool schemas.

### 7.1 Strategy

```python
async def _build_system_with_cache(self, system_prompt: str, tools: list | None) -> list[dict]:
    """Mark system prompt và tool schemas với cache_control.

    System prompt + tool schemas thường giống nhau giữa các calls
    trong cùng session → cache hit cao.
    """
    system_blocks = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    return system_blocks
```

- `cache_control: {"type": "ephemeral"}` → Anthropic cache system prompt 5 phút
- Tool schemas cũng tự động cached bởi SDK khi truyền vào `tools` param
- Cost saving: cached input tokens tính giá `cached_input_per_million` (90% discount)

### 7.2 Cache Hit Monitoring

Track `cached_tokens` trong `TokenUsage` → emit metrics:
- `llm.cache_hit_ratio` = `cached_tokens / prompt_tokens`
- Alert nếu cache hit ratio < 50% khi expected cao (same agent, same session)

---

## 8. Message Conversion

### 8.1 Platform → Anthropic Format

```python
def _convert_messages(self, messages: list[Message]) -> list[dict]:
    """Convert platform Message format to Anthropic API format.

    Platform dùng OpenAI-style message format (role + content).
    Anthropic API có format riêng cho tool use.
    """
    result = []
    for msg in messages:
        if msg.role == "system":
            continue  # system messages go in 'system' param, not 'messages'

        if msg.role == "tool":
            # Tool result → Anthropic tool_result content block
            result.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": msg.content,
                }],
            })
        elif msg.tool_calls:
            # Assistant with tool calls
            content = []
            if msg.content:
                content.append({"type": "text", "text": msg.content})
            for tc in msg.tool_calls:
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            result.append({"role": "assistant", "content": content})
        else:
            result.append({"role": msg.role, "content": msg.content})

    return result
```

### 8.2 Anthropic → Platform Format

```python
def _extract_text(self, response) -> str | None:
    for block in response.content:
        if block.type == "text":
            return block.text
    return None

def _extract_tool_calls(self, response) -> list[ToolCall] | None:
    calls = []
    for block in response.content:
        if block.type == "tool_use":
            calls.append(ToolCall(
                id=block.id,
                name=block.name,
                arguments=block.input,
            ))
    return calls or None
```

---

## 9. Observability

### 9.1 Metrics

| Metric | Type | Labels |
|--------|------|--------|
| `llm_request_duration_seconds` | Histogram | `model`, `provider`, `status` |
| `llm_request_total` | Counter | `model`, `provider`, `status` |
| `llm_tokens_total` | Counter | `model`, `direction` (input/output/cached) |
| `llm_cost_usd_total` | Counter | `model`, `provider` |
| `llm_retry_total` | Counter | `model`, `error_category` |
| `llm_cache_hit_ratio` | Gauge | `model` |

### 9.2 Tracing

Mỗi LLM call → 1 OpenTelemetry span:
```python
with tracer.start_as_current_span("llm.chat") as span:
    span.set_attribute("llm.model", model)
    span.set_attribute("llm.provider", "anthropic")
    span.set_attribute("llm.prompt_tokens", usage.prompt_tokens)
    span.set_attribute("llm.completion_tokens", usage.completion_tokens)
    span.set_attribute("llm.cost_usd", usage.cost_usd)
    span.set_attribute("llm.stop_reason", response.stop_reason)
    span.set_attribute("llm.cached_tokens", usage.cached_tokens or 0)
```

---

## 10. Resolved Questions

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Streaming parsing | Anthropic SDK handles it | SDK emits typed events (`content_block_delta`, etc.), không cần custom parser |
| 2 | Token counting | Anthropic SDK `count_tokens` API | Chính xác 100%, miễn phí, < 50ms. tiktoken là tokenizer OpenAI → sai số với Claude |
| 3 | Connection pooling | httpx pool: 100 max, 20 keepalive | Phase 1 target 1000 sessions, ~100 concurrent LLM calls |
| 4 | Streaming timeout | httpx read timeout (120s inter-chunk) | SDK + httpx tự handle. Không cần custom timer |
| 5 | Cost calculation | Hardcode pricing table | Pricing ít thay đổi. Cập nhật khi deploy. Tránh runtime dependency |
| 6 | Build vs Buy | Direct Anthropic SDK | Phase 1 chỉ cần 1 provider. LiteLLM là overhead. Adapter pattern cho Phase 2 |

---

## 11. Phase 2 Extensibility

```python
# Phase 2: thêm provider mới bằng cách implement LLMGateway protocol
class OpenAIGateway:
    """LLMGateway implementation for OpenAI models."""
    async def chat(self, model, messages, tools=None, config=None) -> LLMResponse: ...
    async def chat_stream(self, model, messages, tools=None, config=None) -> AsyncIterator[LLMStreamEvent]: ...
    async def count_tokens(self, model, messages, tools=None) -> int: ...

# Router chọn gateway dựa vào model config
class LLMRouter:
    def __init__(self, gateways: dict[str, LLMGateway]):
        self._gateways = gateways  # {"anthropic": AnthropicGateway, "openai": OpenAIGateway}

    def get_gateway(self, provider: str) -> LLMGateway:
        return self._gateways[provider]
```

Phase 2 scope:
- `OpenAIGateway` adapter
- `GeminiGateway` adapter
- `LLMRouter` với fallback logic
- Response caching (Redis)
- Model routing rules (per-agent config)

---

## 12. Tech Stack

| Component | Technology | Phase |
|-----------|-----------|-------|
| Anthropic client | `anthropic` Python SDK | 1 |
| HTTP client | `httpx` (async, bundled with anthropic SDK) | 1 |
| Token counting | Anthropic `count_tokens` API | 1 |
| Prompt caching | Anthropic `cache_control` API | 1 |
| Cost calculation | Hardcoded pricing table | 1 |
| Multi-provider adapters | Custom (OpenAIGateway, GeminiGateway) | 2 |
| Response caching | Redis | 2 |
| Model routing | LLMRouter + agent config | 2 |

---

## 13. Performance Targets

| Operation | Target | Mô tả |
|-----------|--------|--------|
| Token counting | < 50ms | Anthropic API call |
| Message conversion | < 1ms | In-memory format transform |
| Cost calculation | < 0.1ms | Arithmetic from pricing table |
| Connection pool acquisition | < 10ms | httpx pool wait |
| Retry backoff (rate limit) | Respect Retry-After | Dynamic based on header |
| Overhead per LLM call (excl. LLM latency) | < 5ms | Gateway processing overhead |
