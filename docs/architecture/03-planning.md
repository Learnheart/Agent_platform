# Thiết Kế Chi Tiết: Planning & Execution Engine

> **Phiên bản:** 2.0
> **Ngày tạo:** 2026-03-25
> **Parent:** [Architecture Overview](00-overview.md)

---

## 1. High-Level Diagram

```
┌──────────────────────────── PLANNING & EXECUTION ENGINE ───────────────────────────┐
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                           AGENT EXECUTOR (Orchestrator)                      │   │
│  │                                                                              │   │
│  │   ┌───────────┐                                                             │   │
│  │   │ Task      │──→ Select execution pattern based on agent_config           │   │
│  │   │ Dispatcher │                                                             │   │
│  │   └─────┬─────┘                                                             │   │
│  │         │                                                                    │   │
│  │         ├─── pattern == "react" ──────→ ┌────────────────────────────┐       │   │
│  │         │           [Phase 1]           │     ReAct Engine           │       │   │
│  │         │                                │                            │       │   │
│  │         │                                │  ┌───────┐  ┌──────────┐ │       │   │
│  │         │                                │  │Think  │→ │Act       │ │       │   │
│  │         │                                │  │(LLM)  │  │(Tool/Ans)│ │       │   │
│  │         │                                │  └───────┘  └────┬─────┘ │       │   │
│  │         │                                │       ▲          │       │       │   │
│  │         │                                │       └──Observe─┘       │       │   │
│  │         │                                └────────────────────────────┘       │   │
│  │         │                                                                    │   │
│  │         ├─── pattern == "plan_execute" ─→ ┌────────────────────────────┐     │   │
│  │         │           [Phase 2]              │  Plan-then-Execute Engine  │     │   │
│  │         │                                  │                            │     │   │
│  │         │                                  │  ┌────────┐  ┌─────────┐ │     │   │
│  │         │                                  │  │Planner │→ │Step     │ │     │   │
│  │         │                                  │  │(LLM)   │  │Executor │ │     │   │
│  │         │                                  │  └────┬───┘  └────┬────┘ │     │   │
│  │         │                                  │       │           │      │     │   │
│  │         │                                  │       └──Replan◄──┘      │     │   │
│  │         │                                  └────────────────────────────┘     │   │
│  │         │                                                                    │   │
│  │         └─── pattern == "reflexion" ────→ ┌────────────────────────────┐     │   │
│  │                     [Phase 2]              │   Reflexion Engine         │     │   │
│  │                                            │                            │     │   │
│  │                                            │  ┌───────┐  ┌──────────┐ │     │   │
│  │                                            │  │Attempt│→ │Evaluate  │ │     │   │
│  │                                            │  │       │  │& Reflect │ │     │   │
│  │                                            │  └───┬───┘  └────┬─────┘ │     │   │
│  │                                            │      └───Retry◄──┘       │     │   │
│  │                                            └────────────────────────────┘     │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌──── Supporting Components ────────────────────────────────────────────────────┐  │
│  │                                                                                │  │
│  │  ┌────────────────┐  ┌────────────────┐  ┌──────────────┐  ┌──────────────┐  │  │
│  │  │ Checkpoint     │  │ Budget          │  │ Context      │  │ Event        │  │  │
│  │  │ Manager        │  │ Controller      │  │ Assembler    │  │ Emitter      │  │  │
│  │  │                │  │                 │  │              │  │              │  │  │
│  │  │ - Delta save   │  │ - Token budget  │  │ - Build LLM  │  │ - Trace spans│  │  │
│  │  │ - Snapshot     │  │ - Cost budget   │  │   prompt     │  │ - WS stream  │  │  │
│  │  │ - Restore      │  │ - Step budget   │  │ - Inject RAG │  │ - Webhook    │  │  │
│  │  │ - Cleanup      │  │ - Time budget   │  │ - Manage CTX │  │              │  │  │
│  │  └────────────────┘  └────────────────┘  └──────────────┘  └──────────────┘  │  │
│  │                                                                                │  │
│  └────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                     │
│  ┌──── External Dependencies ────────────────────────────────────────────────────┐  │
│  │                                                                                │  │
│  │  LLM Gateway  │  Tool Runtime (MCP)  │  Memory Manager  │  State Store (Redis) │  │
│  │                                                                                │  │
│  └────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Descriptions

### 2.1 Agent Executor (Orchestrator)

**Class: AgentExecutor** — Main orchestrator. Stateless: loads state at start, persists at end. Runs as async worker consuming from task queue.

**Dependencies (constructor):**

| Parameter | Type | Mô tả |
|-----------|------|--------|
| llm_gateway | LLMGateway | Gateway giao tiếp với các LLM provider |
| tool_runtime | ToolRuntime | Runtime thực thi tool qua MCP |
| memory_manager | MemoryManager | Quản lý memory (short-term, long-term, working) |
| checkpoint_manager | CheckpointManager | Quản lý checkpoint (delta + snapshot) |
| budget_controller | BudgetController | Kiểm tra budget (token, cost, step, time) |
| event_emitter | EventEmitter | Phát event cho tracing + streaming |
| guardrails | GuardrailsEngine | Engine kiểm tra guardrails |

**Method: execute(task: ExecutionTask) -> ExecutionResult**

Thực thi một task theo các bước:

1. Load session state from checkpoint
2. Select engine based on agent_config.pattern
3. Run engine.step() in a loop until:
   - a. Engine returns final_answer
   - b. Budget exhausted (graceful stop)
   - c. Error (retry or fail)
   - d. HITL gate triggered (pause, re-enqueue later)
4. Persist state after each step
5. Emit events for tracing + streaming

**Task Lifecycle:**

Chi tiết flow của method `execute`:

1. **Load state**: Gọi `checkpoint_manager.restore(task.session_id)`. Nếu trả về `None`, tạo session mới bằng `Session.create(task)`.
2. **Select engine**: Chọn engine phù hợp dựa trên `session.agent_config.execution_pattern`.
3. **Execution loop** — lặp liên tục:
   - **Pre-step checks**: Gọi `budget_controller.check(session)`. Nếu `budget_result.exhausted`, thực hiện graceful stop và trả về kết quả.
   - **Build context**: Gọi `memory_manager.build_context(session_id, agent_config)`.
   - **Inject budget warning**: Nếu `budget_result.warning`, inject system message cảnh báo vào context.
   - **Execute one step**: Gọi `engine.step(session, context)` để thực hiện một bước reasoning.
   - **Post-step processing**:
     - Gọi `memory_manager.update(session.id, step_result.messages)` để cập nhật memory.
     - Gọi `checkpoint_manager.save_delta(session, step_result)` để lưu checkpoint.
     - Gọi `event_emitter.emit(step_result.events)` để phát event.
   - **Check result type** (sử dụng pattern matching):
     - `StepType.FINAL_ANSWER`: Đặt `session.state = SessionState.COMPLETED`, break.
     - `StepType.TOOL_CALL`: Continue (tiếp tục loop).
     - `StepType.WAITING_INPUT`: Đặt `session.state = SessionState.WAITING_INPUT`, break.
     - `StepType.ERROR`: Nếu retryable và chưa hết max retries, tăng retry_count và continue. Ngược lại, đặt `session.state = SessionState.FAILED`, break.
4. **Finalize**: Gọi `checkpoint_manager.save_snapshot(session)`, trả về `ExecutionResult(session=session)`.

---

### 2.2 Internal Engine Abstraction

**Protocol: ExecutionEngine** — Internal interface separating orchestration from reasoning. NOT a public API — internal boundary for clean architecture.

**Method: step(session: Session, context: ContextPayload) -> StepResult**

Execute one reasoning step. Platform handles orchestration (checkpoint, budget, events). Engine handles reasoning logic.

---

### 2.3 ReAct Engine (Phase 1)

```
┌──────────────────── ReAct Loop ────────────────────┐
│                                                      │
│  ┌──────────┐    ┌──────────┐    ┌───────────────┐ │
│  │          │    │          │    │               │ │
│  │  THINK   │───→│   ACT    │───→│   OBSERVE     │ │
│  │  (LLM)   │    │(Tool/Ans)│    │ (Tool result) │ │
│  │          │    │          │    │               │ │
│  └──────────┘    └──────────┘    └───────┬───────┘ │
│       ▲                                   │         │
│       └───────────────────────────────────┘         │
│                                                      │
│  Termination: LLM returns final_answer OR budget hit │
└──────────────────────────────────────────────────────┘
```

**Class: ReActEngine**

**Method: step(session: Session, context: ContextPayload) -> StepResult**

Thực hiện một bước reasoning theo mô hình ReAct:

1. **LLM call**: Gọi `llm_gateway.chat()` với các tham số:
   - `provider`: từ `session.agent_config.model_config.provider`
   - `model`: từ `session.agent_config.model_config.model`
   - `messages`: từ `context.messages`
   - `tools`: từ `context.tool_schemas`
   - `config`: từ `session.agent_config.model_config`

2. **Parse & execute**: Kiểm tra response từ LLM:
   - **Nếu có tool_calls**: Duyệt qua từng tool call:
     - Gọi `guardrails.check_tool_call(tool_call, session)` để kiểm tra quyền.
     - Nếu `permission.denied`: trả về `ToolResult(error=permission.reason)`, skip tool call.
     - Nếu `permission.requires_approval`: trả về `StepResult(type=StepType.WAITING_INPUT, ...)`.
     - Nếu được phép: gọi `tool_runtime.invoke(tool_call)` để thực thi tool.
     - Trả về `StepResult(type=StepType.TOOL_CALL, messages=[llm_response.message, *tool_result_messages(results)], events=[...])`.
   - **Nếu chỉ có text (không có tool call)**: Trả về `StepResult(type=StepType.FINAL_ANSWER, messages=[llm_response.message], answer=llm_response.content, events=[...])`.

3. **Append**: Thêm assistant message + tool result vào session history.

---

### 2.4 Plan-then-Execute Engine (Phase 2)

```
┌──────────────────── Plan-then-Execute ─────────────────────────┐
│                                                                  │
│  PHASE 1: PLANNING                                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  User Goal ──→ Planner LLM ──→ Plan {                   │   │
│  │                                   steps: [               │   │
│  │                                     {id: 1, task: "...", │   │
│  │                                      deps: [],           │   │
│  │                                      status: "pending"}, │   │
│  │                                     ...                  │   │
│  │                                   ]                      │   │
│  │                                 }                        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                         │                                        │
│                         ▼                                        │
│  PHASE 2: EXECUTION (mini ReAct loop per step)                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  For each step (respecting deps):                        │   │
│  │    step.task ──→ LLM ──→ Tool calls ──→ Observe          │   │
│  │    Until step complete OR step fails                      │   │
│  │    On failure → Re-plan decision → REPLAN (back Phase 1)  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                         │                                        │
│                         ▼                                        │
│  PHASE 3: SYNTHESIS                                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  All step results ──→ Synthesizer LLM ──→ Final Answer   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Data Model:**

**Plan:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | — | ID duy nhất của plan |
| session_id | str | — | ID của session chứa plan |
| version | int | — | Phiên bản plan (tăng khi replan) |
| goal | str | — | Mục tiêu tổng thể của plan |
| steps | list[PlanStep] | — | Danh sách các bước cần thực hiện |
| status | Literal["planning", "executing", "replanning", "completed", "failed"] | — | Trạng thái hiện tại của plan |
| created_at | datetime | — | Thời điểm tạo plan |
| updated_at | datetime | — | Thời điểm cập nhật gần nhất |

**PlanStep:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | int | — | ID của step trong plan |
| task | str | — | Mô tả công việc cần thực hiện |
| dependencies | list[int] | — | Danh sách ID các step phải hoàn thành trước |
| status | Literal["pending", "running", "completed", "failed", "skipped"] | — | Trạng thái của step |
| result | str \| None | — | Kết quả khi step hoàn thành |
| error | str \| None | — | Thông tin lỗi nếu step thất bại |
| retries | int | 0 | Số lần đã retry |
| max_retries | int | 2 | Số lần retry tối đa |
| started_at | datetime \| None | None | Thời điểm bắt đầu |
| completed_at | datetime \| None | None | Thời điểm hoàn thành |

**Interface:**

**Class: PlanExecuteEngine**

**Method: step(session: Session, context: ContextPayload) -> StepResult**

Logic chính của method `step`:

1. Lấy plan hiện tại từ working memory qua `working_memory.get_plan(session.id)`.
2. **Nếu chưa có plan** (`plan is None`): Gọi `_create_plan(session, context)` để tạo plan mới.
3. **Nếu plan đang ở trạng thái "replanning"**: Gọi `_replan(session, context, plan)`.
4. **Tìm step tiếp theo có thể thực thi** qua `_get_next_executable_step(plan)`:
   - Nếu không tìm thấy step nào (`next_step is None`):
     - Nếu tất cả step đã completed: gọi `_synthesize(session, context, plan)` để tổng hợp kết quả.
     - Ngược lại: gọi `_handle_blocked(session, plan)` để xử lý trường hợp bị block.
   - Nếu có step: gọi `_execute_step(session, context, plan, next_step)`.

**Các private method:**

| Method | Parameters | Return | Mô tả |
|--------|-----------|--------|--------|
| _create_plan | session, context | StepResult | Tạo plan mới từ goal bằng LLM |
| _execute_step | session, context, plan, step | StepResult | Thực thi một step (mini ReAct loop) |
| _should_replan | plan, step_result | bool | Quyết định có cần replan không |
| _replan | session, context, plan | StepResult | Tạo phiên bản plan mới bằng LLM |
| _synthesize | session, context, plan | StepResult | Tổng hợp kết quả từ tất cả steps thành final answer |

---

### 2.5 Reflexion Engine (Phase 2)

```
┌──────────────── Reflexion Loop ─────────────────────┐
│                                                       │
│  ┌──────────┐    ┌──────────┐    ┌───────────────┐  │
│  │ ATTEMPT  │───→│ EVALUATE │───→│   REFLECT     │  │
│  │ (ReAct   │    │ (run test│    │ (LLM analyzes │  │
│  │  sub-loop│    │  /judge) │    │  failure)     │  │
│  │  )       │    │          │    │               │  │
│  └──────────┘    └─────┬────┘    └───────┬───────┘  │
│                        │                  │          │
│                   pass?│             ┌────▼────┐     │
│                  ┌─────▼──────┐     │  Retry  │     │
│                  │ YES: Done  │     │  with   │     │
│                  │ return     │     │ reflect │     │
│                  │ result     │     │ in ctx  │──┐  │
│                  └────────────┘     └─────────┘  │  │
│                                          ▲       │  │
│                                          └───────┘  │
│                                                       │
│  Max attempts: configurable (default 3)              │
└───────────────────────────────────────────────────────┘
```

**Class: ReflexionEngine**

**Method: step(session: Session, context: ContextPayload) -> StepResult**

Logic thực thi:

1. Lấy số lần attempt hiện tại từ `session.metadata.get("reflexion_attempt", 0)`.
2. Lấy giới hạn max attempts từ `session.agent_config.execution_config.get("max_reflexion_attempts", 3)`.
3. **Nếu đã đạt max attempts**: Trả về `StepResult(type=StepType.FINAL_ANSWER, answer="Best attempt result...")`.
4. **Thực hiện attempt**: Gọi `react_engine.step(session, context)` để chạy một ReAct loop.
5. **Đánh giá kết quả**: Gọi `_evaluate(result, session.agent_config.evaluation_config)`.
6. **Nếu evaluation passed**: Trả về result (thành công).
7. **Nếu evaluation failed**:
   - Gọi `_reflect(result, evaluation, context)` để LLM phân tích nguyên nhân thất bại.
   - Tăng `session.metadata["reflexion_attempt"]` lên 1.
   - Inject vào context message: "Previous attempt evaluation: {evaluation.feedback}\nReflection: {reflection}".
   - Trả về `StepResult(type=StepType.TOOL_CALL, ...)` để tiếp tục loop.

---

### 2.6 Checkpoint Manager (Delta-based)

```
                    ┌──────────────────────────┐
                    │ Restore: replay deltas   │
                    │ on top of last snapshot   │
                    └────────────┬─────────────┘
                                 │
               ┌─────────────────▼─────────────────┐
               │         EXECUTION STEP             │
               │  LLM call → Tool call → Observe    │
               └─────────────────┬─────────────────┘
                                 │
               ┌─────────────────▼─────────────────┐
               │  save_delta(): new messages +      │ ← After EVERY step
               │  tool results since last checkpoint│
               └─────────────────┬─────────────────┘
                                 │
               ┌─────────────────▼─────────────────┐
               │  save_snapshot(): full state       │ ← Every N steps (default 10)
               │  OR at session end                 │   hoặc khi session kết thúc
               └─────────────────┬─────────────────┘
                                 │
                          Next step or done
```

**Data Model: CheckpointDelta**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| session_id | str | — | ID của session |
| step_index | int | — | Thứ tự step hiện tại |
| new_messages | list[Message] | — | Các message mới từ step vừa thực hiện |
| tool_results | list[ToolResult] | — | Kết quả tool call từ step vừa thực hiện |
| metadata_updates | dict | — | Các thay đổi metadata |
| token_usage_delta | TokenUsage | — | Lượng token sử dụng trong step này |
| timestamp | datetime | — | Thời điểm tạo delta |

**Data Model: CheckpointSnapshot**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| session_id | str | — | ID của session |
| step_index | int | — | Thứ tự step tại thời điểm snapshot |
| state | bytes | — | Full serialized session |
| conversation_hash | str | — | Hash của conversation để detect changes |
| token_usage | TokenUsage | — | Tổng token usage tại thời điểm snapshot |
| timestamp | datetime | — | Thời điểm tạo snapshot |

**Class: CheckpointManager** — Delta-based checkpoint. Lưu delta sau mỗi step, full snapshot mỗi N steps hoặc khi session kết thúc.

**Constructor**: Nhận `redis`, `pg`, và `snapshot_interval: int = 10` (mặc định 10 steps giữa các snapshot).

**Method: save_delta(session: Session, step_result: StepResult) -> None**

1. Serialize chỉ new messages + tool results từ step vừa xong thành đối tượng `CheckpointDelta` (bao gồm session_id, step_index, new_messages, tool_results, metadata_updates, token_usage_delta, timestamp).
2. Append delta vào Redis list theo key `checkpoint:deltas:{session.id}`.
3. Async append vào PostgreSQL qua `pg.append_delta(delta)`.
4. Nếu `step_index % snapshot_interval == 0`, tự động gọi `save_snapshot()`.

**Method: save_snapshot(session: Session) -> None**

Full session state serialize:

1. Tạo `CheckpointSnapshot` với toàn bộ state của session (session_id, step_index, serialized state, conversation_hash, token_usage, timestamp).
2. Lưu vào Redis theo key `checkpoint:snapshot:{session.id}` với TTL bằng `session.ttl_seconds`.
3. Upsert vào PostgreSQL qua `pg.upsert_snapshot(snapshot)`.
4. Clear các deltas đã applied khỏi Redis (delete key `checkpoint:deltas:{session.id}`).

**Method: restore(session_id: str) -> Session | None**

1. Load last snapshot từ Redis (key `checkpoint:snapshot:{session_id}`). Nếu không có trong Redis, fallback lấy từ PostgreSQL qua `pg.get_latest_snapshot(session_id)`. Nếu không có snapshot nào, trả về `None`.
2. Deserialize snapshot thành `Session`.
3. Load deltas sau snapshot: lấy từ Redis list (`checkpoint:deltas:{session_id}`). Nếu không có trong Redis, fallback lấy từ PostgreSQL qua `pg.get_deltas_after(session_id, session.step_index)`.
4. Replay từng delta lên session bằng `session.apply_delta(delta)`.
5. Warm up Redis: lưu lại session đã restore vào Redis snapshot key với TTL tương ứng.
6. Trả về session đã restore.

**Method: cleanup(session_id: str) -> None**

Xóa cả snapshot và deltas khỏi Redis cho session đã cho (delete key `checkpoint:snapshot:{session_id}` và `checkpoint:deltas:{session_id}`).

---

### 2.7 Budget Controller

**Class: BudgetController**

**Method: check(session: Session) -> BudgetCheckResult**

Kiểm tra budget của session theo 4 chiều:

1. **Token budget**: Nếu `config.max_tokens_budget` được cấu hình, tính `ratio = usage.total_tokens / config.max_tokens_budget`.
2. **Cost budget**: Nếu `config.max_cost_usd` được cấu hình, tính `ratio = usage.total_cost / config.max_cost_usd`.
3. **Step budget**: Nếu `config.max_steps` được cấu hình, tính `ratio = session.step_index / config.max_steps`.
4. **Time budget**: Nếu `config.max_duration_seconds` được cấu hình, tính `elapsed = (utcnow() - session.created_at).total_seconds()` rồi `ratio = elapsed / config.max_duration_seconds`.

Lấy `max_ratio` là giá trị ratio lớn nhất trong tất cả các checks. Trả về `BudgetCheckResult` với:

| Field | Điều kiện | Mô tả |
|-------|-----------|--------|
| exhausted | max_ratio >= 1.0 | Budget đã hết, cần dừng |
| warning | max_ratio >= 0.8 | Cảnh báo sắp hết budget |
| critical | max_ratio >= 0.95 | Sắp hết budget (critical) |
| warning_message | — | Message cảnh báo được build từ các checks |
| checks | — | Danh sách tất cả BudgetCheck |

---

### 2.8 Context Assembler

**Class: ContextAssembler**

**Method: build(session: Session, agent_config: AgentConfig, memory_manager: MemoryManager) -> ContextPayload**

Assembly order (top = first in message list):

```
┌─────────────────────────────────────────────────┐
│ 1. System Prompt (from agent config)             │  Always present
├─────────────────────────────────────────────────┤
│ 2. Canary Token (if guardrails.canary_enabled)  │  Security
├─────────────────────────────────────────────────┤
│ 3. Long-term Memory Results (RAG)               │  If relevant memories found
├─────────────────────────────────────────────────┤
│ 4. Working Memory (plan, scratchpad)            │  If plan-execute pattern
├─────────────────────────────────────────────────┤
│ 5. Episodic Memory (past episodes)              │  Phase 3
├─────────────────────────────────────────────────┤
│ 6. Budget Warning (if approaching limit)        │  If budget > 80%
├─────────────────────────────────────────────────┤
│ 7. Conversation Summary (if summarized)         │  If short-term used summarize
├─────────────────────────────────────────────────┤
│ 8. Recent Messages (user + assistant + tool)    │  Last N messages
└─────────────────────────────────────────────────┘
```

Total tokens capped at `agent_config.max_context_tokens`. If over budget: trim from middle sections (3-6), never from 1 or 8.

---

### 2.9 Event Emitter

**Class: EventEmitter**

**Method: emit(events: list[AgentEvent]) -> None**

Dual-path emission:

1. **OpenTelemetry span** -> Trace Store
2. **Redis pub/sub** -> WebSocket handler -> Client

**Event types:**

| Event Type | Payload Fields |
|------------|---------------|
| step_start | step_index, pattern |
| llm_call_start | model, prompt_tokens_estimate |
| llm_call_end | model, prompt_tokens, completion_tokens, cost, latency |
| thought | content |
| tool_call | tool_name, input |
| tool_result | tool_name, output, duration, success |
| checkpoint | step_index, state_size |
| budget_warning | type, usage_ratio |
| final_answer | content, total_steps, total_cost |
| error | message, retryable |

---

## 3. Sequence Diagrams

### 3.1 ReAct Full Execution Flow

```
Client        Queue        Executor         LLM GW          Tool RT        Checkpoint    Event
 │              │              │               │               │               │            │
 │──submit─────→│              │               │               │               │            │
 │              │──pull───────→│               │               │               │            │
 │              │              │               │               │               │            │
 │              │              │──restore()────────────────────────────────────→│            │
 │              │              │◄──session state (or null)─────────────────────│            │
 │              │              │               │               │               │            │
 │              │              │ ┌─STEP 1──────────────────────────────────────────────────┐│
 │              │              │ │                                                         ││
 │              │              │ │ build_context() → Memory Manager                        ││
 │              │              │ │                                                         ││
 │◄─thought────────────────────│ │──chat(messages, tools)──→│                              ││
 │              │              │ │◄──{tool_call: search_db}──│                              ││
 │              │              │ │                           │                              ││
 │              │              │ │──guardrails.check()       │                              ││
 │              │              │ │  allowed                  │                              ││
 │              │              │ │                           │                              ││
 │◄─tool_call──────────────────│ │──invoke(search_db)───────────────────→│                 ││
 │              │              │ │◄──{results: [...]}────────────────────│                 ││
 │◄─observation────────────────│ │                                                         ││
 │              │              │ │──save_delta()───────────────────────→│                 ││
 │              │              │ │──emit()──────────────────────────────────────────────→  ││
 │              │              │ └─────────────────────────────────────────────────────────┘│
 │              │              │                                                            │
 │              │              │ ┌─STEP 2──────────────────────────────────────────────────┐│
 │              │              │ │ build_context() (updated with Step 1 results)           ││
 │              │              │ │                                                         ││
 │◄─thought────────────────────│ │──chat(messages, tools)──→│                              ││
 │              │              │ │◄──{content: "Based on..."}│  (no tool call = final)     ││
 │              │              │ │                                                         ││
 │◄─final_answer───────────────│ │──save_snapshot()──→ checkpoint                          ││
 │              │              │ │──emit()──→ events                                       ││
 │              │              │ └─────────────────────────────────────────────────────────┘│
 │              │              │               │               │               │            │
```

### 3.2 Crash Recovery via Checkpoint (Delta-based)

```
Executor A (crashes)     Queue         Executor B (picks up)     Checkpoint Store
 │                         │                │                        │
 │──pull task──────────────│                │                        │
 │──restore()──────────────────────────────────────────────────────→│
 │◄──snapshot (step 0)────────────────────────────────────────────│
 │                         │                │                        │
 │──step 1 (success)       │                │                        │
 │──save_delta()───────────────────────────────────────────────────→│ delta step=1
 │                         │                │                        │
 │──step 2 (LLM call)     │                │                        │
 │    CRASH                │                │                        │
 │                         │                │                        │
 │  [task not ACKed]       │                │                        │
 │                         │──timeout──────→│                        │
 │                         │  re-deliver    │                        │
 │                         │  task          │                        │
 │                         │                │──restore()─────────────→│
 │                         │                │◄──snapshot (step 0)     │
 │                         │                │   + replay delta (step 1)│
 │                         │                │   = session at step 1   │
 │                         │                │                        │
 │                         │                │──step 2 (retry)        │
 │                         │                │  (LLM call again)      │
 │                         │                │──step 2 (success)      │
 │                         │                │──save_delta()──────────→│ delta step=2
 │                         │                │                        │
```

---

## 4. Error Handling Strategy

| Error Type | Handling | Retry? |
|-----------|---------|--------|
| LLM API timeout | Retry with backoff | Yes (up to 2x, increased timeout) |
| LLM API rate limit | Retry with exponential backoff | Yes |
| LLM API 500 error | Retry with backoff | Yes (up to 3x) |
| LLM malformed response | Retry with clarification prompt | Yes (1x) |
| LLM content refusal | Return to client | No |
| Tool execution timeout | Return timeout error as observation | No |
| Tool auth failure | Return error as observation | No |
| Tool execution error | Return error as observation | No |
| Checkpoint write failure | Background retry, continue execution | Background |
| Budget exceeded | Graceful termination, return partial result | No |
| Executor crash | Task re-delivered from queue, resume from checkpoint | Automatic |
| Infinite loop detection | Force stop after N consecutive identical tool calls | No |

### 4.1 Error Taxonomy

**Enum: ErrorCategory**

| Value | Description |
|-------|-------------|
| LLM_RATE_LIMIT | "llm_rate_limit" — LLM provider trả về lỗi rate limit |
| LLM_SERVER_ERROR | "llm_server_error" — LLM provider trả về lỗi server (5xx) |
| LLM_CONTENT_REFUSAL | "llm_content_refusal" — LLM từ chối trả lời do content policy |
| LLM_MALFORMED_RESPONSE | "llm_malformed" — Response từ LLM không đúng format mong đợi |
| LLM_TIMEOUT | "llm_timeout" — LLM call bị timeout |
| TOOL_TIMEOUT | "tool_timeout" — Tool execution bị timeout |
| TOOL_AUTH_FAILURE | "tool_auth_failure" — Tool yêu cầu xác thực nhưng thất bại |
| TOOL_EXECUTION_ERROR | "tool_execution_error" — Tool chạy nhưng gặp lỗi |
| CHECKPOINT_WRITE_FAIL | "checkpoint_write" — Ghi checkpoint thất bại |
| BUDGET_EXCEEDED | "budget_exceeded" — Budget đã hết |
| EXECUTOR_CRASH | "executor_crash" — Executor process bị crash |

**Data Model: RetryPolicy**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| category | ErrorCategory | — | Loại lỗi áp dụng policy |
| max_retries | int | — | Số lần retry tối đa |
| backoff_base_seconds | float | — | Thời gian chờ cơ sở trước retry |
| backoff_multiplier | float | — | Hệ số nhân cho exponential backoff |
| backoff_max_seconds | float | — | Thời gian chờ tối đa giữa các retry |

**RetryPolicy Defaults:**

| ErrorCategory | max_retries | backoff_base_seconds | backoff_multiplier | backoff_max_seconds |
|---|---|---|---|---|
| `LLM_RATE_LIMIT` | 5 | 2.0 | 2.0 | 60.0 |
| `LLM_SERVER_ERROR` | 3 | 1.0 | 2.0 | 30.0 |
| `LLM_CONTENT_REFUSAL` | 0 | — | — | — |
| `LLM_MALFORMED_RESPONSE` | 1 | 0.5 | 1.0 | 1.0 |
| `LLM_TIMEOUT` | 2 | 1.0 | 1.5 | 10.0 |
| `TOOL_TIMEOUT` | 0 | — | — | — |
| `TOOL_AUTH_FAILURE` | 0 | — | — | — |
| `TOOL_EXECUTION_ERROR` | 0 | — | — | — |
| `CHECKPOINT_WRITE_FAIL` | 3 | 0.5 | 2.0 | 10.0 |
| `BUDGET_EXCEEDED` | 0 | — | — | — |
| `EXECUTOR_CRASH` | — | — | — | — |

`EXECUTOR_CRASH`: auto-recovery via queue re-delivery, không dùng RetryPolicy.

---

## 5. Configuration Model

### Phase 1

**Data Model: ExecutionConfig**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| pattern | Literal["react"] | "react" | Execution pattern sử dụng |
| max_steps | int | 30 | Số bước tối đa cho mỗi session |
| max_tokens_budget | int | 50,000 | Tổng token tối đa cho mỗi session |
| max_cost_usd | float | 5.0 | Chi phí tối đa (USD) cho mỗi session |
| max_duration_seconds | int | 600 | Thời gian tối đa (giây) cho mỗi session |
| budget_warning_threshold | float | 0.8 | Ngưỡng cảnh báo budget (80%) |
| budget_critical_threshold | float | 0.95 | Ngưỡng critical budget (95%) |
| checkpoint_enabled | bool | True | Bật/tắt checkpoint |
| checkpoint_interval | int | 1 | Lưu delta sau mỗi N steps |
| checkpoint_snapshot_interval | int | 10 | Lưu full snapshot sau mỗi N steps |
| react_max_consecutive_tool_calls | int | 10 | Số tool call liên tiếp tối đa (phát hiện loop) |
| max_retries_per_step | int | 2 | Số lần retry tối đa cho mỗi step bị lỗi |
| retry_backoff_seconds | float | 1.0 | Thời gian chờ cơ sở giữa các retry |
| max_context_tokens | int | 8,000 | Giới hạn token cho context window |
| context_strategy | Literal["sliding_window", "summarize_recent", "selective", "token_trim"] | "summarize_recent" | Chiến lược quản lý context khi vượt giới hạn |

### Phase 2

**Data Model: ExecutionConfigPhase2** (kế thừa từ ExecutionConfig)

Bao gồm tất cả field từ ExecutionConfig, cộng thêm:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| pattern | Literal["react", "plan_execute", "reflexion"] | "react" | Mở rộng thêm 2 pattern mới |
| plan_max_steps | int | 10 | Số bước tối đa trong một plan |
| plan_max_replans | int | 3 | Số lần replan tối đa |
| plan_step_max_substeps | int | 5 | Số sub-step tối đa cho mỗi plan step |
| plan_parallel_steps | bool | False | Cho phép thực thi song song các steps không phụ thuộc |
| reflexion_max_attempts | int | 3 | Số lần attempt tối đa cho Reflexion |
| reflexion_evaluator | Literal["llm_judge", "custom_function"] | "llm_judge" | Phương thức đánh giá kết quả |

---

## 6. Tech Stack

### Phase 1

| Component | Technology |
|-----------|-----------|
| **Executor runtime** | Python asyncio workers |
| **Task consumption** | Redis Streams consumer groups |
| **Checkpoint hot store** | Redis (string + list, TTL) |
| **Checkpoint durable store** | PostgreSQL (JSONB) |
| **Serialization** | msgpack (binary) / JSON (debug) |
| **LLM calls** | httpx async + provider SDKs |
| **Event emission (trace)** | OpenTelemetry SDK |
| **Event emission (stream)** | Redis Pub/Sub -> WebSocket |
| **Budget tracking** | Redis counters + PG aggregates |

### Phase 2

| Component | Technology |
|-----------|-----------|
| **Plan storage** | Redis Hash (working memory) |
| **Parallel step execution** | asyncio.gather |
| **Evaluator (reflexion)** | LLM-as-judge + custom hooks |

---

## 7. Performance Targets

| Operation | Target |
|-----------|--------|
| Checkpoint save delta (Redis) | < 2ms |
| Checkpoint save snapshot (Redis) | < 5ms |
| Checkpoint restore - snapshot (Redis) | < 3ms |
| Checkpoint restore - snapshot + deltas (Redis) | < 10ms |
| Checkpoint restore (PG fallback) | < 20ms |
| Context assembly | < 100ms |
| Step overhead (excl. LLM + tool) | < 50ms |
| Replan decision | < 5ms |
| Event emission | < 2ms |
| Budget check | < 2ms |
| Full step cycle (excl. LLM) | < 150ms |

---

## Phase 2: Sequence Diagrams

### Plan-then-Execute Full Flow

```
Client        Executor           LLM GW          Tool RT       Working Mem    Checkpoint
 │              │                   │               │               │             │
 │──submit─────→│                   │               │               │             │
 │              │                   │               │               │             │
 │              │ PLANNING: plan_prompt()──→ LLM ──→ plan JSON     │             │
 │◄─plan_created│  store_plan() ──────────────────────────────────→│             │
 │              │  save_delta() ──────────────────────────────────────────────────→│
 │              │                   │               │               │             │
 │              │ STEP N: mini ReAct loop per step                  │             │
 │◄─step_end───│  update_plan(stepN: completed) ──→│               │             │
 │              │  save_delta() ──────────────────────────────────────────────────→│
 │              │                   │               │               │             │
 │              │ SYNTHESIS: synthesize(all results) ──→ LLM        │             │
 │◄─final_answer│                   │               │               │             │
```

### Replan Flow

```
Executor              LLM GW          Working Mem
 │                      │                  │
 │  step N FAILED       │                  │
 │──should_replan()? → YES                 │
 │──replan_prompt()────→│                  │
 │◄──Plan v2 JSON───────│                  │
 │──store_plan(v2)─────────────────────────→│
 │  [Continue with Plan v2]                │
```
