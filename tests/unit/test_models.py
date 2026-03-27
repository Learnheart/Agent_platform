"""Tests for core data models — serialization, defaults, round-trip."""

import json

from src.core.enums import AgentEventType, SessionState, StepType
from src.core.models import (
    Agent,
    AgentEvent,
    AuthContext,
    BudgetCheck,
    BudgetCheckResult,
    CheckpointDelta,
    CheckpointSnapshot,
    ContextPayload,
    ExecutionConfig,
    ExecutionResult,
    ExecutionTask,
    ExecutionTrigger,
    LLMConfig,
    LLMResponse,
    LLMStreamEvent,
    Message,
    ModelConfig,
    RetryPolicy,
    Session,
    SessionUsage,
    StepResult,
    StepUsage,
    Tenant,
    TenantConfig,
    TokenUsage,
    ToolCall,
    ToolResult,
)


class TestTenant:
    def test_defaults(self) -> None:
        t = Tenant(name="Test", slug="test")
        assert t.status == "active"
        assert t.config.max_agents == 50
        assert t.id  # UUID generated

    def test_json_round_trip(self) -> None:
        t = Tenant(name="Acme", slug="acme")
        data = t.model_dump()
        t2 = Tenant.model_validate(data)
        assert t2.name == "Acme"
        assert t2.slug == "acme"


class TestAgent:
    def test_defaults(self) -> None:
        a = Agent(tenant_id="t1", name="Bot", system_prompt="You are a bot.")
        assert a.status == "draft"
        assert a.description == ""
        assert a.execution_config.pattern == "react"
        assert a.execution_config.max_steps == 30

    def test_model_config_alias(self) -> None:
        data = {
            "tenant_id": "t1",
            "name": "Bot",
            "system_prompt": "test",
            "model_config": {"provider": "groq", "model": "llama-3.3-70b"},
        }
        a = Agent.model_validate(data)
        assert a.model_config_.provider == "groq"

    def test_json_round_trip(self) -> None:
        a = Agent(tenant_id="t1", name="Bot", system_prompt="Hello")
        json_str = a.model_dump_json(by_alias=True)
        data = json.loads(json_str)
        a2 = Agent.model_validate(data)
        assert a2.name == "Bot"


class TestSession:
    def test_defaults(self) -> None:
        s = Session(tenant_id="t1", agent_id="a1")
        assert s.state == SessionState.CREATED
        assert s.step_index == 0
        assert s.usage.total_tokens == 0
        assert s.ttl_seconds == 3600
        assert s.completed_at is None

    def test_json_round_trip(self) -> None:
        s = Session(tenant_id="t1", agent_id="a1", user_type="end_user")
        data = s.model_dump()
        s2 = Session.model_validate(data)
        assert s2.user_type == "end_user"


class TestMessage:
    def test_user_message(self) -> None:
        m = Message(role="user", content="Hello")
        assert m.role == "user"
        assert m.tool_calls is None
        assert m.id  # UUID generated

    def test_assistant_with_tool_calls(self) -> None:
        tc = ToolCall(id="tc1", name="search", arguments={"query": "test"})
        m = Message(role="assistant", content="", tool_calls=[tc])
        assert len(m.tool_calls) == 1
        assert m.tool_calls[0].name == "search"

    def test_tool_message(self) -> None:
        m = Message(role="tool", content="result", tool_call_id="tc1")
        assert m.tool_call_id == "tc1"


class TestToolModels:
    def test_tool_call(self) -> None:
        tc = ToolCall(id="tc1", name="mcp:github:create_issue", arguments={"title": "Bug"})
        assert tc.arguments["title"] == "Bug"

    def test_tool_result_success(self) -> None:
        tr = ToolResult(tool_call_id="tc1", tool_name="search", content="Found 3 results")
        assert not tr.is_error
        assert tr.latency_ms == 0.0

    def test_tool_result_error(self) -> None:
        tr = ToolResult(tool_call_id="tc1", tool_name="search", content="Timeout", is_error=True)
        assert tr.is_error


class TestLLMModels:
    def test_token_usage(self) -> None:
        u = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert u.total_tokens == 150
        assert u.cached_tokens is None

    def test_llm_response_text(self) -> None:
        r = LLMResponse(
            content="Hello!",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="claude-sonnet-4-5-20250514",
            provider="anthropic",
            latency_ms=250.0,
            stop_reason="end_turn",
        )
        assert r.tool_calls is None

    def test_llm_response_tool_call(self) -> None:
        tc = ToolCall(id="tc1", name="search", arguments={})
        r = LLMResponse(
            tool_calls=[tc],
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="test",
            provider="anthropic",
            latency_ms=100.0,
            stop_reason="tool_use",
        )
        assert r.content is None
        assert len(r.tool_calls) == 1

    def test_llm_stream_event_text_delta(self) -> None:
        e = LLMStreamEvent(type="text_delta", content="Hello")
        assert e.content == "Hello"

    def test_llm_stream_event_tool_call_start(self) -> None:
        e = LLMStreamEvent(type="tool_call_start", tool_call_id="tc1", tool_name="search")
        assert e.tool_name == "search"

    def test_llm_config_defaults(self) -> None:
        c = LLMConfig()
        assert c.temperature == 1.0
        assert c.max_tokens == 4096

    def test_retry_policy(self) -> None:
        p = RetryPolicy(max_retries=5, backoff_base_seconds=2.0)
        assert p.backoff_multiplier == 2.0
        assert 429 in p.retryable_status_codes


class TestExecutionModels:
    def test_execution_task(self) -> None:
        t = ExecutionTask(
            session_id="s1",
            agent_id="a1",
            tenant_id="t1",
            trigger=ExecutionTrigger(type="new_message", message_id="m1"),
        )
        assert t.trigger.type == "new_message"

    def test_step_result_final_answer(self) -> None:
        sr = StepResult(type=StepType.FINAL_ANSWER, answer="Done!")
        assert sr.answer == "Done!"
        assert sr.tool_calls is None

    def test_step_result_tool_call(self) -> None:
        sr = StepResult(
            type=StepType.TOOL_CALL,
            tool_calls=[ToolCall(id="tc1", name="search", arguments={})],
        )
        assert len(sr.tool_calls) == 1

    def test_step_usage(self) -> None:
        u = StepUsage(prompt_tokens=100, completion_tokens=50, cost_usd=0.01)
        assert u.latency_ms == 0.0

    def test_context_payload(self) -> None:
        cp = ContextPayload(
            system_prompt="You are a bot",
            messages=[Message(role="user", content="Hi")],
            tool_schemas=[{"name": "search"}],
            total_tokens_estimate=100,
        )
        assert len(cp.messages) == 1
        assert cp.budget_warning is None

    def test_budget_check_result(self) -> None:
        bcr = BudgetCheckResult(
            exhausted=False,
            warning=True,
            critical=False,
            warning_message="Token budget at 85%",
            checks=[BudgetCheck(type="tokens", current=42500, limit=50000, ratio=0.85)],
        )
        assert bcr.warning
        assert bcr.checks[0].ratio == 0.85


class TestCheckpointModels:
    def test_checkpoint_delta(self) -> None:
        cd = CheckpointDelta(
            session_id="s1",
            step_index=3,
            new_messages=[Message(role="assistant", content="Hello")],
        )
        assert cd.step_index == 3
        assert len(cd.new_messages) == 1

    def test_checkpoint_snapshot(self) -> None:
        cs = CheckpointSnapshot(
            session_id="s1",
            step_index=10,
            state=b"binary_state_data",
            conversation_hash="abc123",
        )
        assert cs.state == b"binary_state_data"


class TestEventModel:
    def test_agent_event(self) -> None:
        e = AgentEvent(
            type=AgentEventType.LLM_CALL_END,
            session_id="s1",
            tenant_id="t1",
            agent_id="a1",
            step_index=2,
            data={"model": "claude-sonnet-4-5-20250514", "cost_usd": 0.01},
        )
        assert e.type == AgentEventType.LLM_CALL_END
        assert e.data["cost_usd"] == 0.01

    def test_agent_event_json_round_trip(self) -> None:
        e = AgentEvent(
            type=AgentEventType.FINAL_ANSWER,
            session_id="s1",
            tenant_id="t1",
            agent_id="a1",
            data={"content": "Done"},
        )
        json_str = e.model_dump_json()
        e2 = AgentEvent.model_validate_json(json_str)
        assert e2.type == AgentEventType.FINAL_ANSWER


class TestAuthContext:
    def test_builder(self) -> None:
        ac = AuthContext(user_id="u1", tenant_id="t1", user_type="builder", roles=["admin"])
        assert ac.allowed_agent_ids is None

    def test_end_user(self) -> None:
        ac = AuthContext(user_id="u2", tenant_id="t1", user_type="end_user", allowed_agent_ids=["a1", "a2"])
        assert len(ac.allowed_agent_ids) == 2


class TestExecutionConfig:
    def test_defaults(self) -> None:
        ec = ExecutionConfig()
        assert ec.pattern == "react"
        assert ec.max_steps == 30
        assert ec.max_tokens_budget == 50000
        assert ec.budget_warning_threshold == 0.8
        assert ec.context_strategy == "summarize_recent"
