# Thiet Ke Chi Tiet: Planning & Execution Engine

> **Phien ban:** 2.0
> **Ngay tao:** 2026-03-25
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

```python
class AgentExecutor:
    """
    Main orchestrator. Stateless — loads state at start, persists at end.
    Runs as async worker consuming from task queue.
    """

    def __init__(
        self,
        llm_gateway: LLMGateway,
        tool_runtime: ToolRuntime,
        memory_manager: MemoryManager,
        checkpoint_manager: CheckpointManager,
        budget_controller: BudgetController,
        event_emitter: EventEmitter,
        guardrails: GuardrailsEngine,
    ): ...

    async def execute(self, task: ExecutionTask) -> ExecutionResult:
        """
        1. Load session state from checkpoint
        2. Select engine based on agent_config.pattern
        3. Run engine.step() in a loop until:
           a. Engine returns final_answer
           b. Budget exhausted (graceful stop)
           c. Error (retry or fail)
           d. HITL gate triggered (pause, re-enqueue later)
        4. Persist state after each step
        5. Emit events for tracing + streaming
        """
```

**Task Lifecycle:**

```python
async def execute(self, task: ExecutionTask) -> ExecutionResult:
    # 1. Load state
    session = await self.checkpoint_manager.restore(task.session_id)
    if session is None:
        session = Session.create(task)

    engine = self._select_engine(session.agent_config.execution_pattern)

    # 2. Execution loop
    while True:
        # Pre-step checks
        budget_result = await self.budget_controller.check(session)
        if budget_result.exhausted:
            return await self._graceful_stop(session, budget_result)

        # Build context
        context = await self.memory_manager.build_context(
            session_id=session.id,
            agent_config=session.agent_config,
        )

        # Inject budget warning if approaching limit
        if budget_result.warning:
            context.inject_system_message(budget_result.warning_message)

        # Execute one step
        step_result = await engine.step(session, context)

        # Post-step processing
        await self.memory_manager.update(session.id, step_result.messages)
        await self.checkpoint_manager.save_delta(session, step_result)
        await self.event_emitter.emit(step_result.events)

        # Check result type
        match step_result.type:
            case StepType.FINAL_ANSWER:
                session.state = SessionState.COMPLETED
                break
            case StepType.TOOL_CALL:
                continue
            case StepType.WAITING_INPUT:
                session.state = SessionState.WAITING_INPUT
                break
            case StepType.ERROR:
                if step_result.retryable and session.retry_count < max_retries:
                    session.retry_count += 1
                    continue
                else:
                    session.state = SessionState.FAILED
                    break

    await self.checkpoint_manager.save_snapshot(session)
    return ExecutionResult(session=session)
```

---

### 2.2 Internal Engine Abstraction

```python
class ExecutionEngine(Protocol):
    """Internal interface separating orchestration from reasoning.
    NOT a public API — internal boundary for clean architecture."""

    async def step(self, session: Session, context: ContextPayload) -> StepResult:
        """Execute one reasoning step. Platform handles orchestration
        (checkpoint, budget, events). Engine handles reasoning logic."""
        ...
```

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

```python
class ReActEngine:
    async def step(self, session: Session, context: ContextPayload) -> StepResult:
        """
        1. Call LLM with current context (messages + tools)
        2. Parse response:
           - If text only -> final_answer
           - If tool_use -> validate via guardrails -> execute -> return observation
           - If error -> return retryable error
        3. Append assistant message + tool result to session history
        """

        # 1. LLM call
        llm_response = await self.llm_gateway.chat(
            provider=session.agent_config.model_config.provider,
            model=session.agent_config.model_config.model,
            messages=context.messages,
            tools=context.tool_schemas,
            config=session.agent_config.model_config,
        )

        # 2. Parse & execute
        if llm_response.tool_calls:
            results = []
            for tool_call in llm_response.tool_calls:
                # Guardrail check
                permission = await self.guardrails.check_tool_call(tool_call, session)
                if permission.denied:
                    results.append(ToolResult(error=permission.reason))
                    continue
                if permission.requires_approval:
                    return StepResult(type=StepType.WAITING_INPUT, ...)

                # Execute tool
                result = await self.tool_runtime.invoke(tool_call)
                results.append(result)

            return StepResult(
                type=StepType.TOOL_CALL,
                messages=[llm_response.message, *tool_result_messages(results)],
                events=[...],
            )
        else:
            return StepResult(
                type=StepType.FINAL_ANSWER,
                messages=[llm_response.message],
                answer=llm_response.content,
                events=[...],
            )
```

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

```python
@dataclass
class Plan:
    id: str
    session_id: str
    version: int
    goal: str
    steps: list[PlanStep]
    status: Literal["planning", "executing", "replanning", "completed", "failed"]
    created_at: datetime
    updated_at: datetime

@dataclass
class PlanStep:
    id: int
    task: str
    dependencies: list[int]
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    result: str | None
    error: str | None
    retries: int = 0
    max_retries: int = 2
    started_at: datetime | None = None
    completed_at: datetime | None = None
```

**Interface:**

```python
class PlanExecuteEngine:
    async def step(self, session: Session, context: ContextPayload) -> StepResult:
        plan = await self.working_memory.get_plan(session.id)

        if plan is None:
            return await self._create_plan(session, context)

        if plan.status == "replanning":
            return await self._replan(session, context, plan)

        next_step = self._get_next_executable_step(plan)

        if next_step is None:
            if self._all_steps_completed(plan):
                return await self._synthesize(session, context, plan)
            else:
                return await self._handle_blocked(session, plan)

        return await self._execute_step(session, context, plan, next_step)

    async def _create_plan(self, session, context) -> StepResult: ...
    async def _execute_step(self, session, context, plan, step) -> StepResult: ...
    async def _should_replan(self, plan, step_result) -> bool: ...
    async def _replan(self, session, context, plan) -> StepResult: ...
    async def _synthesize(self, session, context, plan) -> StepResult: ...
```

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

```python
class ReflexionEngine:
    async def step(self, session: Session, context: ContextPayload) -> StepResult:
        attempt = session.metadata.get("reflexion_attempt", 0)
        max_attempts = session.agent_config.execution_config.get("max_reflexion_attempts", 3)

        if attempt >= max_attempts:
            return StepResult(type=StepType.FINAL_ANSWER, answer="Best attempt result...")

        result = await self.react_engine.step(session, context)
        evaluation = await self._evaluate(result, session.agent_config.evaluation_config)

        if evaluation.passed:
            return result

        reflection = await self._reflect(result, evaluation, context)

        session.metadata["reflexion_attempt"] = attempt + 1
        context.inject_system_message(f"Previous attempt evaluation: {evaluation.feedback}\n"
                                       f"Reflection: {reflection}")

        return StepResult(type=StepType.TOOL_CALL, ...)
```

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
               │  OR at session end                 │   hoac khi session ket thuc
               └─────────────────┬─────────────────┘
                                 │
                          Next step or done
```

```python
@dataclass
class CheckpointDelta:
    session_id: str
    step_index: int
    new_messages: list[Message]
    tool_results: list[ToolResult]
    metadata_updates: dict
    token_usage_delta: TokenUsage
    timestamp: datetime

@dataclass
class CheckpointSnapshot:
    session_id: str
    step_index: int
    state: bytes                        # Full serialized session
    conversation_hash: str
    token_usage: TokenUsage
    timestamp: datetime

class CheckpointManager:
    """
    Delta-based checkpoint. Luu delta sau moi step,
    full snapshot moi N steps hoac khi session ket thuc.
    """

    def __init__(self, redis, pg, snapshot_interval: int = 10):
        self.snapshot_interval = snapshot_interval

    async def save_delta(self, session: Session, step_result: StepResult) -> None:
        """
        1. Serialize chi new messages + tool results tu step vua xong
        2. Append delta vao Redis list
        3. Async append vao PostgreSQL
        4. Neu step_index % snapshot_interval == 0 -> save_snapshot()
        """
        delta = CheckpointDelta(
            session_id=session.id,
            step_index=session.step_index,
            new_messages=step_result.messages,
            tool_results=step_result.tool_results,
            metadata_updates=step_result.metadata_updates,
            token_usage_delta=step_result.token_usage,
            timestamp=utcnow(),
        )

        # Append delta
        await self.redis.rpush(
            f"checkpoint:deltas:{session.id}",
            delta.serialize(),
        )
        await self.pg.append_delta(delta)

        # Periodic full snapshot
        if session.step_index % self.snapshot_interval == 0:
            await self.save_snapshot(session)

    async def save_snapshot(self, session: Session) -> None:
        """Full session state serialize."""
        snapshot = CheckpointSnapshot(
            session_id=session.id,
            step_index=session.step_index,
            state=session.serialize(),
            conversation_hash=hash(session.conversation),
            token_usage=session.token_usage,
            timestamp=utcnow(),
        )

        await self.redis.set(
            f"checkpoint:snapshot:{session.id}",
            snapshot.serialize(),
            ex=session.ttl_seconds,
        )
        await self.pg.upsert_snapshot(snapshot)

        # Clear applied deltas
        await self.redis.delete(f"checkpoint:deltas:{session.id}")

    async def restore(self, session_id: str) -> Session | None:
        """
        1. Load last snapshot (Redis -> fallback PG)
        2. Load deltas sau snapshot
        3. Replay deltas len snapshot -> session hien tai
        """
        # Load snapshot
        snapshot_data = await self.redis.get(f"checkpoint:snapshot:{session_id}")
        if not snapshot_data:
            snapshot = await self.pg.get_latest_snapshot(session_id)
            if snapshot:
                snapshot_data = snapshot.state
            else:
                return None

        session = Session.deserialize(snapshot_data)

        # Load & replay deltas
        delta_list = await self.redis.lrange(f"checkpoint:deltas:{session_id}", 0, -1)
        if not delta_list:
            delta_list = await self.pg.get_deltas_after(session_id, session.step_index)

        for delta_data in delta_list:
            delta = CheckpointDelta.deserialize(delta_data)
            session.apply_delta(delta)

        # Warm up Redis
        await self.redis.set(
            f"checkpoint:snapshot:{session_id}",
            session.serialize(),
            ex=session.ttl_seconds,
        )

        return session

    async def cleanup(self, session_id: str) -> None:
        await self.redis.delete(f"checkpoint:snapshot:{session_id}")
        await self.redis.delete(f"checkpoint:deltas:{session_id}")
```

---

### 2.7 Budget Controller

```python
class BudgetController:
    async def check(self, session: Session) -> BudgetCheckResult:
        config = session.agent_config.execution_config
        usage = session.usage

        checks = []

        # Token budget
        if config.max_tokens_budget:
            ratio = usage.total_tokens / config.max_tokens_budget
            checks.append(BudgetCheck("tokens", ratio, config.max_tokens_budget))

        # Cost budget
        if config.max_cost_usd:
            ratio = usage.total_cost / config.max_cost_usd
            checks.append(BudgetCheck("cost", ratio, config.max_cost_usd))

        # Step budget
        if config.max_steps:
            ratio = session.step_index / config.max_steps
            checks.append(BudgetCheck("steps", ratio, config.max_steps))

        # Time budget
        if config.max_duration_seconds:
            elapsed = (utcnow() - session.created_at).total_seconds()
            ratio = elapsed / config.max_duration_seconds
            checks.append(BudgetCheck("time", ratio, config.max_duration_seconds))

        max_ratio = max(c.ratio for c in checks) if checks else 0

        return BudgetCheckResult(
            exhausted=(max_ratio >= 1.0),
            warning=(max_ratio >= 0.8),
            critical=(max_ratio >= 0.95),
            warning_message=self._build_warning(checks, max_ratio),
            checks=checks,
        )
```

---

### 2.8 Context Assembler

```python
class ContextAssembler:
    async def build(
        self,
        session: Session,
        agent_config: AgentConfig,
        memory_manager: MemoryManager,
    ) -> ContextPayload:
        """
        Assembly order (top = first in message list):

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

        Total tokens capped at agent_config.max_context_tokens.
        If over budget: trim from middle sections (3-6), never from 1 or 8.
        """
```

---

### 2.9 Event Emitter

```python
class EventEmitter:
    async def emit(self, events: list[AgentEvent]) -> None:
        """
        Dual-path emission:
        1. OpenTelemetry span -> Trace Store
        2. Redis pub/sub -> WebSocket handler -> Client
        """

    # Event types:
    # - step_start:      {step_index, pattern}
    # - llm_call_start:  {model, prompt_tokens_estimate}
    # - llm_call_end:    {model, prompt_tokens, completion_tokens, cost, latency}
    # - thought:         {content}
    # - tool_call:       {tool_name, input}
    # - tool_result:     {tool_name, output, duration, success}
    # - checkpoint:      {step_index, state_size}
    # - budget_warning:  {type, usage_ratio}
    # - final_answer:    {content, total_steps, total_cost}
    # - error:           {message, retryable}
```

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

```python
class ErrorCategory(str, Enum):
    LLM_RATE_LIMIT = "llm_rate_limit"
    LLM_SERVER_ERROR = "llm_server_error"
    LLM_CONTENT_REFUSAL = "llm_content_refusal"
    LLM_MALFORMED_RESPONSE = "llm_malformed"
    LLM_TIMEOUT = "llm_timeout"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_AUTH_FAILURE = "tool_auth_failure"
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    CHECKPOINT_WRITE_FAIL = "checkpoint_write"
    BUDGET_EXCEEDED = "budget_exceeded"
    EXECUTOR_CRASH = "executor_crash"

class RetryPolicy:
    category: ErrorCategory
    max_retries: int
    backoff_base_seconds: float
    backoff_multiplier: float
    backoff_max_seconds: float
```

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

`EXECUTOR_CRASH`: auto-recovery via queue re-delivery, khong dung RetryPolicy.

---

## 5. Configuration Model

### Phase 1

```python
@dataclass
class ExecutionConfig:
    pattern: Literal["react"] = "react"

    # Budget limits
    max_steps: int = 30
    max_tokens_budget: int = 50_000
    max_cost_usd: float = 5.0
    max_duration_seconds: int = 600

    # Budget behavior
    budget_warning_threshold: float = 0.8
    budget_critical_threshold: float = 0.95

    # Checkpoint
    checkpoint_enabled: bool = True
    checkpoint_interval: int = 1
    checkpoint_snapshot_interval: int = 10

    # ReAct specific
    react_max_consecutive_tool_calls: int = 10

    # Error handling
    max_retries_per_step: int = 2
    retry_backoff_seconds: float = 1.0

    # Context management
    max_context_tokens: int = 8000
    context_strategy: Literal["sliding_window", "summarize_recent", "selective", "token_trim"] = "summarize_recent"
```

### Phase 2

```python
@dataclass
class ExecutionConfigPhase2(ExecutionConfig):
    pattern: Literal["react", "plan_execute", "reflexion"] = "react"

    # Plan-Execute specific
    plan_max_steps: int = 10
    plan_max_replans: int = 3
    plan_step_max_substeps: int = 5
    plan_parallel_steps: bool = False

    # Reflexion specific
    reflexion_max_attempts: int = 3
    reflexion_evaluator: Literal["llm_judge", "custom_function"] = "llm_judge"
```

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
