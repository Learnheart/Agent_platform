# Thiết Kế Chi Tiết: LLM Gateway

> **Phiên bản:** 0.1 (Stub — pending spike validation)
> **Ngày tạo:** 2026-03-25
> **Parent:** [Architecture Overview](00-overview.md)
> **Status:** PENDING — full design after vertical spike (tuần 2-3)

---

## 1. Scope

LLM Gateway là abstraction layer giữa Executor và LLM providers. Mọi LLM call đi qua component này.

Phase 1: Anthropic (Claude) only.
Phase 2: OpenAI, Gemini, local models.

---

## 2. Interface (Confirmed)

```python
class LLMGateway(Protocol):
    async def chat(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        """Synchronous (non-streaming) LLM call."""

    async def chat_stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        config: LLMConfig | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Streaming LLM call. Yields events: text_delta, tool_call_delta, done."""

@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] | None
    usage: TokenUsage
    model: str
    provider: str
    latency_ms: float
    stop_reason: str

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
```

---

## 3. Open Questions (Validate via Spike)

| # | Question | Spike Validation |
|---|----------|-----------------|
| 1 | Streaming parsing: partial tool calls, thinking blocks — cần custom parser hay SDK đủ? | Implement streaming với Anthropic SDK, đo complexity |
| 2 | Token counting: pre-call estimation accuracy? Cần tiktoken hay dùng SDK estimate? | So sánh estimate vs actual trên 100 calls |
| 3 | Connection pooling: httpx pool size tối ưu cho concurrent sessions? | Load test với 50 concurrent sessions |
| 4 | Timeout strategy: khi stream đang chảy nhưng chậm, timeout thế nào? | Measure inter-chunk latency distribution |
| 5 | Cost calculation: pricing data source? Hardcode hay fetch runtime? | Evaluate LiteLLM pricing data vs manual config |
| 6 | Build vs Buy: LiteLLM proxy có đủ cho Phase 1? Trade-off control vs effort? | Spike both paths, compare 1 tuần effort |

---

## 4. Error Taxonomy (Confirmed)

| Error | Retry | Strategy |
|-------|-------|----------|
| Rate limit (429) | Yes | Exponential backoff, respect Retry-After header |
| Server error (500/502/503) | Yes | Up to 3x, backoff 1s → 2s → 4s |
| Content refusal | No | Return refusal to client |
| Malformed response | Yes | 1x retry with same prompt |
| Timeout | Yes | 2x retry with increased timeout |
| Auth error (401/403) | No | Fail immediately, alert |
| Provider outage | No | No cross-provider failover Phase 1. Log + alert. Phase 2: configurable failover. |

---

## 5. Phase 1 Implementation Decision

Pending spike results. Two options:

**Option A: Direct Anthropic SDK**
- Dùng anthropic Python SDK trực tiếp
- Wrap trong LLMGateway interface
- Minimal abstraction, maximum control
- Risk: phải tự build mọi thứ khi thêm provider

**Option B: LiteLLM proxy**
- Deploy LiteLLM as internal service
- LLMGateway gọi vào LiteLLM
- Multi-provider ready from day 1
- Risk: thêm dependency, less control over provider-specific features

Decision: sau spike tuần 1-2.

---

## 6. Tech Stack

| Component | Technology | Phase |
|-----------|-----------|-------|
| Anthropic client | anthropic Python SDK | 1 |
| HTTP client | httpx (async) | 1 |
| Token estimation | anthropic SDK / tiktoken | 1 |
| Multi-provider | LiteLLM hoặc custom | 2 |
| Response caching | Redis | 2 |
| Prompt caching | Anthropic prompt caching API | 1 |
