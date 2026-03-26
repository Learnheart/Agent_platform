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

`LLMGateway` là một Protocol class định nghĩa interface chung cho mọi LLM provider. Các method:

| Method | Parameters | Return Type | Description |
|--------|-----------|-------------|-------------|
| `chat` | `model: str`, `messages: list[Message]`, `tools: list[ToolSchema] \| None = None`, `config: LLMConfig \| None = None` | `LLMResponse` | Non-streaming LLM call. Blocks until complete response. |
| `chat_stream` | `model: str`, `messages: list[Message]`, `tools: list[ToolSchema] \| None = None`, `config: LLMConfig \| None = None` | `AsyncIterator[LLMStreamEvent]` | Streaming LLM call. Yields events as they arrive. |
| `count_tokens` | `model: str`, `messages: list[Message]`, `tools: list[ToolSchema] \| None = None` | `int` | Pre-call token count estimation. |

Tất cả method đều là `async`.

### 2.2 Data Models

> Canonical definitions trong [`01-data-models.md`](01-data-models.md) Section 5. Summary:

**LLMResponse**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `content` | `str \| None` | — | Nội dung text response từ LLM |
| `tool_calls` | `list[ToolCall] \| None` | — | Danh sách tool calls nếu LLM yêu cầu gọi tool |
| `usage` | `TokenUsage` | — | Thông tin token usage |
| `model` | `str` | — | Tên model thực tế trả về |
| `provider` | `str` | — | Tên provider (e.g., "anthropic") |
| `latency_ms` | `float` | — | Thời gian xử lý call (ms) |
| `stop_reason` | `str` | — | Lý do dừng: "end_turn", "tool_use", "max_tokens", hoặc "stop_sequence" |

**TokenUsage**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prompt_tokens` | `int` | — | Số token trong prompt (input) |
| `completion_tokens` | `int` | — | Số token trong completion (output) |
| `total_tokens` | `int` | — | Tổng số token (input + output) |
| `cached_tokens` | `int \| None` | `None` | Số token được cache hit (prompt caching) |
| `cost_usd` | `float \| None` | `None` | Chi phí ước tính (USD) |

**LLMConfig**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `temperature` | `float` | `1.0` | Temperature cho sampling |
| `max_tokens` | `int` | `4096` | Số token tối đa cho response |
| `timeout_seconds` | `float` | `120.0` | Timeout cho call |
| `retry_policy` | `RetryPolicy \| None` | `None` | Retry policy, dùng default nếu None |

**RetryPolicy**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_retries` | `int` | `3` | Số lần retry tối đa |
| `backoff_base_seconds` | `float` | `1.0` | Base time cho exponential backoff |
| `backoff_multiplier` | `float` | `2.0` | Multiplier cho backoff |
| `backoff_max_seconds` | `float` | `30.0` | Thời gian backoff tối đa |
| `retryable_status_codes` | `list[int]` | `[429, 500, 502, 503, 529]` | Các HTTP status codes cho phép retry |

### 2.3 LLMStreamEvent

**LLMStreamEvent** là dataclass đại diện cho một sự kiện trong streaming response. Trường `type` xác định loại event, các trường còn lại chỉ có giá trị tương ứng với type đó.

**Các giá trị `type` hợp lệ:**

| Type | Mô tả | Trường liên quan |
|------|--------|-----------------|
| `"text_delta"` | Partial text content | `content: str` |
| `"tool_call_start"` | Tool call bắt đầu: id + name | `tool_call_id: str`, `tool_name: str` |
| `"tool_call_delta"` | Partial tool arguments (JSON string chunk) | `tool_call_id: str`, `arguments_delta: str` |
| `"tool_call_end"` | Tool call hoàn tất: full ToolCall | `tool_call: ToolCall` |
| `"usage"` | Token usage (arrives near end) | `usage: TokenUsage` |
| `"done"` | Stream finished | `usage: TokenUsage`, `stop_reason: str` |
| `"error"` | Stream error | `error_message: str`, `error_category: str` |

Tất cả trường (trừ `type`) đều optional, default `None`.

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

`AnthropicGateway` là implementation class của `LLMGateway` protocol, sử dụng Anthropic Python SDK.

**Constructor** nhận `AnthropicGatewayConfig` và khởi tạo:
- Một `anthropic.AsyncAnthropic` client với `max_retries=0` (tự handle retry), timeout tùy chỉnh qua `httpx.Timeout` (connect=10s, read=config.default_timeout, write=10s, pool=10s), và HTTP client với connection pool limits (`max_connections`, `max_keepalive` từ config).
- Lưu `pricing` và `default_llm_config` từ config.

**Methods:** `chat`, `chat_stream`, `count_tokens` — implement đúng `LLMGateway` protocol (xem chi tiết bên dưới).

### 3.2 Configuration

**AnthropicGatewayConfig**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `api_key` | `str` | — | Anthropic API key |
| `default_timeout` | `float` | `120.0` | Default read timeout (seconds) |
| `max_connections` | `int` | `100` | httpx connection pool max connections |
| `max_keepalive` | `int` | `20` | Persistent keep-alive connections |
| `default_llm_config` | `LLMConfig` | `LLMConfig()` | Default LLM config dùng khi caller không truyền |
| `pricing` | `ModelPricing` | `DEFAULT_PRICING` | Bảng giá theo model |

### 3.3 chat() — Non-Streaming

**Mô tả logic từng bước:**

1. Lấy config: sử dụng `config` nếu caller truyền, nếu không dùng `self._default_config`.
2. Convert messages từ platform format sang Anthropic format bằng `_convert_messages`.
3. Convert tool schemas sang Anthropic format bằng `_convert_tools` (nếu có tools), nếu không truyền `NOT_GIVEN`.
4. Ghi nhận thời điểm bắt đầu (`time.monotonic()`).
5. Gọi `self._call_with_retry` với lambda thực hiện `self._client.messages.create(...)`, truyền: `model`, `messages` (đã convert), `tools` (đã convert), `system` (trích từ messages), `temperature`, `max_tokens` từ config. Retry policy lấy từ config.
6. Tính `latency_ms` = (thời gian hiện tại - thời điểm bắt đầu) * 1000.
7. Trả về `LLMResponse` với:
   - `content`: trích text từ response bằng `_extract_text`
   - `tool_calls`: trích tool calls bằng `_extract_tool_calls`
   - `usage`: build `TokenUsage` từ `response.usage` + model (để tính cost)
   - `model`: `response.model`
   - `provider`: `"anthropic"`
   - `latency_ms`: đã tính ở bước 6
   - `stop_reason`: `response.stop_reason`

### 3.4 chat_stream() — Streaming

**Mô tả logic từng bước:**

1. Lấy config và convert messages/tools giống `chat()`.
2. Mở streaming context bằng `self._client.messages.stream(...)` với các tham số tương tự `chat()`.
3. Khởi tạo state theo dõi tool call đang xử lý: `current_tool_id`, `current_tool_name` (cả hai ban đầu `None`), và `accumulated_args` (chuỗi rỗng).
4. Iterate qua từng event trong stream, xử lý theo `event.type`:
   - **Text delta** (`content_block_delta` với `event.delta` có thuộc tính `text`): yield `LLMStreamEvent(type="text_delta", content=event.delta.text)`.
   - **Tool call start** (`content_block_start` với `event.content_block.type == "tool_use"`): lưu `current_tool_id` và `current_tool_name` từ content block, reset `accumulated_args` thành rỗng, yield `LLMStreamEvent(type="tool_call_start", ...)`.
   - **Tool call argument delta** (`content_block_delta` với `event.delta` có thuộc tính `partial_json`): nối `event.delta.partial_json` vào `accumulated_args`, yield `LLMStreamEvent(type="tool_call_delta", ...)`.
   - **Tool call end** (`content_block_stop` khi `current_tool_id` có giá trị): yield `LLMStreamEvent(type="tool_call_end", tool_call=ToolCall(...))` với arguments parse từ `accumulated_args` (JSON), reset `current_tool_id` và `current_tool_name` về `None`.
   - **Message complete** (`message_stop`): lấy final message từ stream, yield `LLMStreamEvent(type="done", usage=..., stop_reason=...)`.

### 3.5 count_tokens() — Token Estimation

Sử dụng Anthropic SDK `count_tokens` API để ước tính số token.

**Mục đích sử dụng:**
- Context window budget check trước khi gọi LLM
- Summarization trigger (khi vượt threshold)
- Cost estimation

**Logic:**
1. Convert messages và tools sang Anthropic format.
2. Gọi `self._client.messages.count_tokens(...)` với `model`, `messages`, `tools`, `system` (trích từ messages).
3. Trả về `result.input_tokens`.

> **Tại sao Anthropic SDK count_tokens thay vì tiktoken?**
> - Anthropic SDK sử dụng cùng tokenizer với model → chính xác 100%
> - tiktoken là tokenizer của OpenAI → sai số khi dùng cho Claude
> - count_tokens API miễn phí, latency < 50ms

### 3.6 Retry Logic

Method `_call_with_retry(call_fn, retry_policy)` thực hiện retry LLM calls với exponential backoff.

**Lý do tự handle retry thay vì dùng SDK retry:**
- Cần emit events cho mỗi retry (audit, cost tracking)
- Cần respect budget limits giữa retries
- Cần custom logic per error category

**Logic:**

1. Lấy retry policy (dùng default `RetryPolicy()` nếu không truyền).
2. Loop từ attempt 0 đến `1 + max_retries`:
   - Gọi `call_fn()`. Nếu thành công, trả kết quả ngay.
   - Nếu `RateLimitError`: parse header `Retry-After` nếu có, nếu không tính backoff. Sleep rồi retry.
   - Nếu `InternalServerError`: tính backoff, sleep rồi retry.
   - Nếu `APITimeoutError`: nếu đã hết số lần retry thì break, nếu chưa thì sleep backoff rồi retry.
   - Nếu `BadRequestError`: raise ngay (malformed request, không retry).
   - Nếu `AuthenticationError`: raise ngay (invalid API key, không retry).
3. Nếu hết retries, raise error cuối cùng.

**Hàm tính backoff:** `wait = backoff_base_seconds * (backoff_multiplier ^ attempt)`, giới hạn bởi `backoff_max_seconds`.

**Hàm parse Retry-After:** Lấy giá trị header `retry-after` từ response của error. Trả về float nếu có, `None` nếu không.

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

`LLMError` là base exception class cho LLM Gateway.

| Field | Type | Description |
|-------|------|-------------|
| `message` | `str` | Mô tả lỗi |
| `category` | `ErrorCategory` | Phân loại lỗi (enum) |
| `retryable` | `bool` | Có thể retry hay không |
| `cause` | `Exception \| None` | Exception gốc gây ra lỗi |

Executor nhận `LLMError` → xử lý theo `ErrorCategory` (xem [`01-data-models.md`](01-data-models.md) Section 9.2).

---

## 5. Cost Calculation

### 5.1 Pricing Table

> Hardcode trong config. Lý do: pricing ít thay đổi, cập nhật khi deploy. Tránh runtime dependency.

**ModelPricing** — cấu trúc lưu giá theo model:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `input_per_million` | `float` | — | USD per 1M input tokens |
| `output_per_million` | `float` | — | USD per 1M output tokens |
| `cached_input_per_million` | `float \| None` | `None` | Giá input tokens khi cache hit (prompt caching discount) |

**DEFAULT_PRICING** — bảng giá mặc định:

| Model | Input (USD/1M tokens) | Output (USD/1M tokens) | Cached Input (USD/1M tokens) |
|-------|----------------------|----------------------|------------------------------|
| `claude-sonnet-4-5-20250514` | 3.0 | 15.0 | 0.3 |
| `claude-haiku-4-5-20251001` | 0.80 | 4.0 | 0.08 |

### 5.2 Cost Calculation Logic

Hàm `calculate_cost(usage: TokenUsage, model: str) -> float` tính chi phí như sau:

1. Tra bảng `DEFAULT_PRICING` theo `model`. Nếu model không có trong bảng → log warning, trả về `0.0`.
2. Tính `input_cost` = (`prompt_tokens` / 1,000,000) * `input_per_million`.
3. Tính `output_cost` = (`completion_tokens` / 1,000,000) * `output_per_million`.
4. Nếu có `cached_tokens` và model hỗ trợ `cached_input_per_million`: tính `cached_saving` = (`cached_tokens` / 1,000,000) * (`input_per_million` - `cached_input_per_million`). Trừ `cached_saving` khỏi `input_cost`.
5. Trả về `round(input_cost + output_cost, 6)`.

---

## 6. Connection & Timeout

### 6.1 Connection Pooling

Cấu hình httpx connection pool:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `max_connections` | `100` | Total connections across all hosts |
| `max_keepalive_connections` | `20` | Persistent keep-alive connections |

- Phase 1 target: 1000 concurrent sessions → ~100 simultaneous LLM calls (execution is sequential per session)
- `max_connections=100` đủ cho Phase 1
- Phase 2: tune based on load test results

### 6.2 Timeout Strategy

Cấu hình httpx Timeout:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `connect` | `10.0s` | TCP connection timeout |
| `read` | `120.0s` | Read timeout — matches `LLMConfig.timeout_seconds` |
| `write` | `10.0s` | Write timeout (sending request) |
| `pool` | `10.0s` | Waiting for available connection from pool |

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

Method `_build_system_with_cache(system_prompt, tools)` xây dựng system message với cache control.

**Logic:**
- Tạo một list chứa system text block với `cache_control: {"type": "ephemeral"}`.
- System prompt và tool schemas thường giống nhau giữa các calls trong cùng session → cache hit cao.

**Chi tiết:**
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

Method `_convert_messages(messages: list[Message]) -> list[dict]` chuyển đổi platform Message format sang Anthropic API format.

Platform dùng OpenAI-style message format (role + content). Anthropic API có format riêng cho tool use.

**Quy tắc chuyển đổi:**

| Platform Message | Anthropic Format |
|-----------------|-----------------|
| `role="system"` | Bỏ qua — system messages truyền riêng qua tham số `system`, không đưa vào `messages` |
| `role="tool"` (tool result) | Chuyển thành `role="user"` với content block `type="tool_result"`, bao gồm `tool_use_id` và `content` |
| `role="assistant"` có `tool_calls` | Chuyển thành `role="assistant"` với content là danh sách blocks: text block (nếu có content) + các tool_use blocks (mỗi block chứa `id`, `name`, `input` từ ToolCall) |
| Các role khác (user, assistant không có tool_calls) | Giữ nguyên `role` và `content` |

### 8.2 Anthropic → Platform Format

**`_extract_text(response) -> str | None`:** Duyệt qua `response.content`, tìm block có `type == "text"`, trả về `block.text`. Nếu không tìm thấy, trả về `None`.

**`_extract_tool_calls(response) -> list[ToolCall] | None`:** Duyệt qua `response.content`, tìm tất cả blocks có `type == "tool_use"`, tạo `ToolCall(id=block.id, name=block.name, arguments=block.input)` cho mỗi block. Trả về list nếu có ít nhất 1 tool call, `None` nếu không có.

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

Mỗi LLM call tạo 1 OpenTelemetry span với tên `"llm.chat"`. Các attributes được ghi nhận trên span:

| Attribute | Value | Description |
|-----------|-------|-------------|
| `llm.model` | model name | Tên model được sử dụng |
| `llm.provider` | `"anthropic"` | Tên provider |
| `llm.prompt_tokens` | `usage.prompt_tokens` | Số input tokens |
| `llm.completion_tokens` | `usage.completion_tokens` | Số output tokens |
| `llm.cost_usd` | `usage.cost_usd` | Chi phí ước tính (USD) |
| `llm.stop_reason` | `response.stop_reason` | Lý do dừng |
| `llm.cached_tokens` | `usage.cached_tokens` hoặc `0` | Số tokens được cache |

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

Phase 2 mở rộng multi-provider bằng cách thêm các class implement `LLMGateway` protocol:

**OpenAIGateway** — implement `LLMGateway` cho OpenAI models, cung cấp cùng 3 methods: `chat`, `chat_stream`, `count_tokens`.

**LLMRouter** — router chọn gateway dựa vào provider name:
- Constructor nhận `gateways: dict[str, LLMGateway]` — mapping từ provider name đến gateway instance (ví dụ: `{"anthropic": AnthropicGateway(...), "openai": OpenAIGateway(...)}`).
- Method `get_gateway(provider: str) -> LLMGateway` trả về gateway tương ứng.

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
