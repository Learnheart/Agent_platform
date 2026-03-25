# Thiết Kế Chi Tiết: Planning & Execution Engine

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect
> **Parent:** [Architecture Overview](../00-overview.md)

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
│  │         │                                │     ReAct Engine           │       │   │
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
│  │         │                                  │  Plan-then-Execute Engine  │     │   │
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
│  │                                            │   Reflexion Engine         │     │   │
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
│  │  │ - Save state   │  │ - Token budget  │  │ - Build LLM  │  │ - Trace spans│  │  │
│  │  │ - Restore      │  │ - Cost budget   │  │   prompt     │  │ - WS stream  │  │  │
│  │  │ - Cleanup      │  │ - Step budget   │  │ - Inject RAG │  │ - Webhook    │  │  │
│  │  │                │  │ - Time budget   │  │ - Manage CTX │  │              │  │  │
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

Điểm entry cho mọi execution. Nhận task từ queue, dispatch sang đúng engine, quản lý lifecycle.

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
        Main execution loop:
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
        await self.checkpoint_manager.save(session)
        await self.event_emitter.emit(step_result.events)

        # Check result type
        match step_result.type:
            case StepType.FINAL_ANSWER:
                session.state = SessionState.COMPLETED
                break
            case StepType.TOOL_CALL:
                continue  # next iteration will process observation
            case StepType.WAITING_INPUT:
                session.state = SessionState.WAITING_INPUT
                break  # will be resumed via re-enqueue
            case StepType.ERROR:
                if step_result.retryable and session.retry_count < max_retries:
                    session.retry_count += 1
                    continue
                else:
                    session.state = SessionState.FAILED
                    break

    await self.checkpoint_manager.save(session)
    return ExecutionResult(session=session)
```

---

### 2.2 ReAct Engine

Pattern cơ bản nhất: **Think → Act → Observe → Repeat**.

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
        One ReAct iteration:

        1. Call LLM with current context (messages + tools)
        2. Parse response:
           - If text only → final_answer
           - If tool_use → validate via guardrails → execute → return observation
           - If error → return retryable error
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

### 2.3 Plan-then-Execute Engine

Tách **planning** và **execution** thành 2 phase riêng biệt. Phù hợp cho tasks phức tạp, multi-step.

```
┌──────────────────── Plan-then-Execute ─────────────────────────┐
│                                                                  │
│  PHASE 1: PLANNING                                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                                                          │   │
│  │  User Goal ──→ Planner LLM ──→ Plan {                   │   │
│  │                                   steps: [               │   │
│  │                                     {id: 1, task: "...", │   │
│  │                                      deps: [],           │   │
│  │                                      status: "pending"}, │   │
│  │                                     {id: 2, task: "...", │   │
│  │                                      deps: [1],          │   │
│  │                                      status: "pending"}, │   │
│  │                                     ...                  │   │
│  │                                   ]                      │   │
│  │                                 }                        │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                         │                                        │
│                         ▼                                        │
│  PHASE 2: EXECUTION                                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                                                          │   │
│  │  For each step (respecting deps):                        │   │
│  │    ┌─────────────────────────────────────────────────┐   │   │
│  │    │ Step Executor (mini ReAct loop)                  │   │   │
│  │    │                                                  │   │   │
│  │    │ step.task ──→ LLM ──→ Tool calls ──→ Observe    │   │   │
│  │    │                  ↑                      │        │   │   │
│  │    │                  └──────────────────────┘        │   │   │
│  │    │ Until step complete OR step fails                │   │   │
│  │    └─────────────────────────────────────────────────┘   │   │
│  │                         │                                │   │
│  │                    Step result                            │   │
│  │                         │                                │   │
│  │              ┌──────────▼──────────┐                     │   │
│  │              │ Re-plan decision?    │                     │   │
│  │              │                      │                     │   │
│  │              │ IF step failed OR    │                     │   │
│  │              │ new info changes     │──YES──→ REPLAN      │   │
│  │              │ the approach         │         (back to    │   │
│  │              │                      │          Phase 1)   │   │
│  │              │ ELSE                 │                     │   │
│  │              │ → Continue to next   │                     │   │
│  │              └──────────────────────┘                     │   │
│  │                                                          │   │
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
    version: int                        # Tăng khi replan
    goal: str                           # Original user goal
    steps: list[PlanStep]
    status: Literal["planning", "executing", "replanning", "completed", "failed"]
    created_at: datetime
    updated_at: datetime

@dataclass
class PlanStep:
    id: int
    task: str                           # What this step should accomplish
    dependencies: list[int]             # Step IDs that must complete first
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    result: str | None                  # Output of this step
    error: str | None
    retries: int = 0
    max_retries: int = 2
    started_at: datetime | None = None
    completed_at: datetime | None = None
```

```python
class PlanExecuteEngine:
    async def step(self, session: Session, context: ContextPayload) -> StepResult:
        plan = await self.working_memory.get_plan(session.id)

        if plan is None:
            # Phase 1: Generate plan
            return await self._create_plan(session, context)

        if plan.status == "replanning":
            return await self._replan(session, context, plan)

        # Phase 2: Execute next ready step
        next_step = self._get_next_executable_step(plan)

        if next_step is None:
            if self._all_steps_completed(plan):
                # Phase 3: Synthesize final answer
                return await self._synthesize(session, context, plan)
            else:
                # All remaining steps blocked or failed
                return await self._handle_blocked(session, plan)

        return await self._execute_step(session, context, plan, next_step)

    async def _create_plan(self, session, context) -> StepResult:
        """
        LLM call with planning prompt:
        "Given this goal, create a step-by-step plan.
         For each step, specify: task description, dependencies.
         Return as structured JSON."
        """

    async def _execute_step(self, session, context, plan, step) -> StepResult:
        """
        Run a mini ReAct loop scoped to this single step.
        step.task becomes the sub-goal.
        Max 5 sub-steps per plan step (configurable).
        """

    async def _should_replan(self, plan, step_result) -> bool:
        """
        Replan if:
        - Step failed after max retries
        - Step result reveals goal has changed
        - Step result makes remaining steps irrelevant
        """

    async def _replan(self, session, context, plan) -> StepResult:
        """
        LLM call with replanning prompt:
        "Original plan was: {...}
         Steps completed so far: {...}
         Step {N} failed/revealed new info: {...}
         Create an updated plan for the remaining work."
        """

    async def _synthesize(self, session, context, plan) -> StepResult:
        """
        LLM call to combine all step results into a coherent final answer.
        """
```

---

### 2.4 Reflexion Engine (Phase 2)

**Attempt → Evaluate → Reflect → Retry** cho tasks có verifiable output.

```
┌──────────────── Reflexion Loop ─────────────────────┐
│                                                       │
│  ┌──────────┐    ┌──────────┐    ┌───────────────┐  │
│  │          │    │          │    │               │  │
│  │ ATTEMPT  │───→│ EVALUATE │───→│   REFLECT     │  │
│  │ (ReAct   │    │ (run test│    │ (LLM analyzes │  │
│  │  sub-loop│    │  /judge) │    │  what went    │  │
│  │  )       │    │          │    │  wrong)       │  │
│  │          │    │          │    │               │  │
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

        # 1. Attempt (run ReAct sub-loop)
        result = await self.react_engine.step(session, context)

        # 2. Evaluate
        evaluation = await self._evaluate(result, session.agent_config.evaluation_config)

        if evaluation.passed:
            return result  # Success!

        # 3. Reflect
        reflection = await self._reflect(result, evaluation, context)

        # 4. Inject reflection into context for next attempt
        session.metadata["reflexion_attempt"] = attempt + 1
        context.inject_system_message(f"Previous attempt evaluation: {evaluation.feedback}\n"
                                       f"Reflection: {reflection}")

        return StepResult(type=StepType.TOOL_CALL, ...)  # Continue loop
```

---

### 2.5 Checkpoint Manager

**Mục đích:** Persist session state sau mỗi step, cho phép resume sau crash/pause.

```python
class CheckpointManager:
    """
    Saves and restores session state. Uses Redis for hot state,
    PostgreSQL for durable persistence.
    """

    async def save(self, session: Session) -> None:
        """
        1. Serialize session state (conversation, plan, step_index, metadata)
        2. Write to Redis (hot, fast access for active sessions)
        3. Async write to PostgreSQL (durable, for crash recovery)
        4. Emit checkpoint event for tracing
        """
        checkpoint = Checkpoint(
            session_id=session.id,
            step_index=session.step_index,
            state=session.serialize(),
            conversation_hash=hash(session.conversation),
            token_usage=session.token_usage,
            timestamp=utcnow(),
        )

        # Hot path (Redis)
        await self.redis.set(
            f"checkpoint:{session.id}",
            checkpoint.serialize(),
            ex=session.ttl_seconds,
        )

        # Durable path (PostgreSQL, async)
        await self.pg.upsert_checkpoint(checkpoint)

    async def restore(self, session_id: str) -> Session | None:
        """
        1. Try Redis first (fast)
        2. Fall back to PostgreSQL (durable)
        3. Return None if no checkpoint exists (new session)
        """
        # Hot path
        data = await self.redis.get(f"checkpoint:{session_id}")
        if data:
            return Session.deserialize(data)

        # Cold path
        checkpoint = await self.pg.get_checkpoint(session_id)
        if checkpoint:
            session = Session.deserialize(checkpoint.state)
            # Warm up Redis for subsequent steps
            await self.redis.set(f"checkpoint:{session.id}", checkpoint.state)
            return session

        return None

    async def cleanup(self, session_id: str) -> None:
        """Remove checkpoint data after session is archived."""
        await self.redis.delete(f"checkpoint:{session_id}")
```

**Checkpoint nằm ở đâu trong execution flow:**

```
                    ┌──────────────────────────┐
                    │ Load checkpoint (restore) │
                    └────────────┬─────────────┘
                                 │
               ┌─────────────────▼─────────────────┐
               │         EXECUTION STEP             │
               │  LLM call → Tool call → Observe    │
               └─────────────────┬─────────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │ Save checkpoint (save)    │ ← After EVERY successful step
                    └────────────┬─────────────┘
                                 │
                          Next step or done
```

---

### 2.6 Budget Controller

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

        # Determine overall status
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

### 2.7 Context Assembler

Builds the final message list sent to the LLM, incorporating all memory layers and injections.

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
        │    [system] "Relevant context from memory: ..."  │
        ├─────────────────────────────────────────────────┤
        │ 4. Working Memory (plan, scratchpad)            │  If plan-execute pattern
        │    [system] "Current plan: step 3/5..."          │
        ├─────────────────────────────────────────────────┤
        │ 5. Episodic Memory (past episodes)              │  Phase 3
        │    [system] "Similar past task: ..."             │
        ├─────────────────────────────────────────────────┤
        │ 6. Budget Warning (if approaching limit)        │  If budget > 80%
        │    [system] "Budget warning: 85% used..."        │
        ├─────────────────────────────────────────────────┤
        │ 7. Conversation Summary (if summarized)         │  If short-term used summarize
        │    [system] "Previous conversation summary:..."  │
        ├─────────────────────────────────────────────────┤
        │ 8. Recent Messages (user + assistant + tool)    │  Last N messages
        └─────────────────────────────────────────────────┘

        Total tokens capped at agent_config.max_context_tokens.
        If over budget: trim from middle sections (3-6), never from 1 or 8.
        """
```

---

### 2.8 Event Emitter

Emits structured events cho tracing (OpenTelemetry) và real-time streaming (WebSocket).

```python
class EventEmitter:
    async def emit(self, events: list[AgentEvent]) -> None:
        """
        Dual-path emission:
        1. OpenTelemetry span → Trace Store
        2. Redis pub/sub → WebSocket handler → Client
        """

    # Event types emitted during execution:
    # - step_start:      {step_index, pattern}
    # - llm_call_start:  {model, prompt_tokens_estimate}
    # - llm_call_end:    {model, prompt_tokens, completion_tokens, cost, latency}
    # - thought:         {content}  (LLM reasoning text)
    # - tool_call:       {tool_name, input}
    # - tool_result:     {tool_name, output, duration, success}
    # - checkpoint:      {step_index, state_size}
    # - budget_warning:  {type, usage_ratio}
    # - plan_created:    {plan_id, num_steps}
    # - plan_step_start: {step_id, task}
    # - plan_step_end:   {step_id, status, result_summary}
    # - replan:          {reason, new_plan_version}
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
 │              │              │ │  ✅ allowed               │                              ││
 │              │              │ │                           │                              ││
 │◄─tool_call──────────────────│ │──invoke(search_db)───────────────────→│                 ││
 │              │              │ │◄──{results: [...]}────────────────────│                 ││
 │◄─observation────────────────│ │                                                         ││
 │              │              │ │──save()──────────────────────────────→│                 ││
 │              │              │ │──emit()──────────────────────────────────────────────→  ││
 │              │              │ └─────────────────────────────────────────────────────────┘│
 │              │              │                                                            │
 │              │              │ ┌─STEP 2──────────────────────────────────────────────────┐│
 │              │              │ │ build_context() (updated with Step 1 results)           ││
 │              │              │ │                                                         ││
 │◄─thought────────────────────│ │──chat(messages, tools)──→│                              ││
 │              │              │ │◄──{content: "Based on..."}│  (no tool call = final)     ││
 │              │              │ │                                                         ││
 │◄─final_answer───────────────│ │──save()──→ checkpoint                                  ││
 │              │              │ │──emit()──→ events                                       ││
 │              │              │ └─────────────────────────────────────────────────────────┘│
 │              │              │               │               │               │            │
```

### 3.2 Plan-then-Execute Full Flow

```
Client        Executor           LLM GW          Tool RT       Working Mem    Checkpoint
 │              │                   │               │               │             │
 │──submit─────→│                   │               │               │             │
 │              │                   │               │               │             │
 │              │ ┌─PLANNING PHASE─────────────────────────────────────────────────┐
 │              │ │                  │               │               │             │
 │◄─thought─────│ │──plan_prompt()──→│              │               │             │
 │  "Planning.."│ │◄──plan JSON──────│              │               │             │
 │              │ │                  │               │               │             │
 │◄─plan_created│ │──store_plan()──────────────────────────────────→│             │
 │  {3 steps}   │ │                  │               │               │             │
 │              │ │──save()────────────────────────────────────────────────────────→│
 │              │ └─────────────────────────────────────────────────────────────────┘
 │              │                   │               │               │             │
 │              │ ┌─STEP 1: "Research competitors"─────────────────────────────────┐
 │◄─step_start──│ │                  │               │               │             │
 │              │ │  [mini ReAct loop for this sub-task]              │             │
 │◄─tool_call───│ │──web_search()────────────────────→│              │             │
 │◄─observation─│ │◄──results────────────────────────│              │             │
 │              │ │                  │               │               │             │
 │◄─step_end────│ │──update_plan(step1: completed)──────────────────→│             │
 │  "Step 1 done"│ │──save()───────────────────────────────────────────────────────→│
 │              │ └─────────────────────────────────────────────────────────────────┘
 │              │                   │               │               │             │
 │              │ ┌─STEP 2: "Analyze findings" (depends on step 1)─────────────────┐
 │◄─step_start──│ │                  │               │               │             │
 │              │ │  [mini ReAct with step 1 results in context]     │             │
 │◄─thought─────│ │──chat()─────────→│              │               │             │
 │◄─step_end────│ │◄──analysis───────│              │               │             │
 │              │ │──update_plan(step2: completed)──→│               │             │
 │              │ └─────────────────────────────────────────────────────────────────┘
 │              │                   │               │               │             │
 │              │ ┌─STEP 3: "Write report"─────────────────────────────────────────┐
 │◄─step_start──│ │  [mini ReAct with step 1+2 results]             │             │
 │◄─step_end────│ │                  │               │               │             │
 │              │ └─────────────────────────────────────────────────────────────────┘
 │              │                   │               │               │             │
 │              │ ┌─SYNTHESIS───────────────────────────────────────────────────────┐
 │              │ │──synthesize(all step results)───→│              │             │
 │◄─final_answer│ │◄──final report───│              │               │             │
 │              │ └─────────────────────────────────────────────────────────────────┘
```

### 3.3 Crash Recovery via Checkpoint

```
Executor A (crashes)     Queue         Executor B (picks up)     Checkpoint Store
 │                         │                │                        │
 │──pull task──────────────│                │                        │
 │──restore()──────────────────────────────────────────────────────→│
 │◄──session (step 0)─────────────────────────────────────────────│
 │                         │                │                        │
 │──step 1 (success)       │                │                        │
 │──save()─────────────────────────────────────────────────────────→│ checkpoint step=1
 │                         │                │                        │
 │──step 2 (LLM call)     │                │                        │
 │    ❌ CRASH             │                │                        │
 │                         │                │                        │
 │  [task not ACKed]       │                │                        │
 │                         │──timeout──────→│                        │
 │                         │  re-deliver    │                        │
 │                         │  task          │                        │
 │                         │                │──restore()─────────────→│
 │                         │                │◄──session (step 1)──────│
 │                         │                │   ← resumes from       │
 │                         │                │     last checkpoint     │
 │                         │                │                        │
 │                         │                │──step 2 (retry)        │
 │                         │                │  (LLM call again)      │
 │                         │                │──step 2 (success)      │
 │                         │                │──save()───────────────→│ checkpoint step=2
 │                         │                │                        │
```

### 3.4 Replan Flow (khi step fails)

```
Executor              LLM GW          Working Mem
 │                      │                  │
 │  [Executing Plan v1, step 3/5]          │
 │                      │                  │
 │──step 3 execution────→│                 │
 │◄──step 3 FAILED──────│                 │
 │  (API rate limited)   │                 │
 │                      │                  │
 │──should_replan()?    │                  │
 │  YES: step failed + retry exhausted     │
 │                      │                  │
 │──replan_prompt()────→│                  │
 │  "Plan v1: [...]     │                  │
 │   Completed: 1,2     │                  │
 │   Failed: 3 (reason) │                  │
 │   Remaining: 4,5     │                  │
 │   Create new plan"   │                  │
 │                      │                  │
 │◄──Plan v2 JSON───────│                  │
 │  [revised steps      │                  │
 │   accounting for     │                  │
 │   step 3 failure]    │                  │
 │                      │                  │
 │──store_plan(v2)─────────────────────────→│
 │                      │                  │
 │  [Continue execution with Plan v2]       │
 │                      │                  │
```

---

## 4. Configuration Model

```python
@dataclass
class ExecutionConfig:
    pattern: Literal["react", "plan_execute", "reflexion"] = "react"

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
    checkpoint_interval: int = 1              # Checkpoint every N steps

    # ReAct specific
    react_max_consecutive_tool_calls: int = 10  # Prevent infinite loops

    # Plan-Execute specific
    plan_max_steps: int = 10                  # Max steps in a plan
    plan_max_replans: int = 3                 # Max replan attempts
    plan_step_max_substeps: int = 5           # Max ReAct steps per plan step
    plan_parallel_steps: bool = False         # Phase 2: parallel independent steps

    # Reflexion specific
    reflexion_max_attempts: int = 3
    reflexion_evaluator: Literal["llm_judge", "custom_function"] = "llm_judge"

    # Error handling
    max_retries_per_step: int = 2
    retry_backoff_seconds: float = 1.0

    # Context management
    max_context_tokens: int = 8000            # Token budget for context window
    context_strategy: Literal["sliding_window", "summarize_recent", "selective", "token_trim"] = "summarize_recent"
```

---

## 5. Tech Stack

| Component | Technology | Phase | Lý do |
|-----------|-----------|-------|-------|
| **Executor runtime** | Python asyncio workers | 1 | Native async, cooperative multitasking |
| **Task consumption** | Redis Streams consumer groups | 1 | Reliable delivery, consumer groups, ACK |
| **Checkpoint hot store** | Redis (string, TTL) | 1 | Sub-ms save/restore for active sessions |
| **Checkpoint durable store** | PostgreSQL (JSONB) | 1 | Crash recovery, queryable |
| **Serialization** | msgpack (binary) / JSON (debug) | 1 | Fast serialize for checkpoints |
| **LLM calls** | httpx async + provider SDKs | 1 | Async, streaming, connection pooling |
| **Event emission (trace)** | OpenTelemetry SDK | 1 | Structured spans, industry standard |
| **Event emission (stream)** | Redis Pub/Sub → WebSocket | 1 | Low-latency fanout to connected clients |
| **Plan storage** | Redis Hash (working memory) | 1 | Fast read/write for active plans |
| **Budget tracking** | Redis counters + PG aggregates | 1 | Real-time + durable cost tracking |
| **Parallel step execution** | asyncio.gather | 2 | Independent plan steps run concurrently |
| **Evaluator (reflexion)** | LLM-as-judge + custom hooks | 2 | Pluggable evaluation |

---

## 6. Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| Checkpoint save (Redis) | < 5ms | Serialized session state |
| Checkpoint restore (Redis) | < 3ms | Cache hit |
| Checkpoint restore (PG) | < 20ms | Cache miss, fallback |
| Context assembly | < 100ms | Including RAG retrieval |
| Step overhead (excl. LLM + tool) | < 50ms | Checkpoint + event + context |
| Plan generation | 3-10s | One LLM call (depends on model) |
| Replan decision | < 5ms | Rule-based check |
| Event emission | < 2ms | Redis pub/sub |
| Budget check | < 2ms | Redis counter read |
| Full step cycle (excl. LLM) | < 150ms | All platform overhead |

---

## 7. Error Handling Strategy

| Error Type | Handling | Retry? |
|-----------|---------|--------|
| LLM API timeout | Retry with backoff | Yes (up to 3x) |
| LLM API rate limit | Queue + retry after delay | Yes (with exponential backoff) |
| LLM API 500 error | Retry; if persistent, failover to secondary provider | Yes |
| LLM malformed response | Retry with clarification prompt | Yes (1x) |
| Tool execution timeout | Return timeout error as observation to LLM | No (let LLM decide) |
| Tool execution error | Return error as observation to LLM | No (let LLM decide) |
| Checkpoint save failure | Log error, continue (risk of replay on crash) | Background retry |
| Budget exceeded | Graceful termination, return partial result | No |
| Executor crash | Task re-delivered from queue, resume from checkpoint | Automatic |
| Infinite loop detection | Force stop after N consecutive identical tool calls | No |
