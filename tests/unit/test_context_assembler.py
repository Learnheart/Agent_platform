"""Tests for ContextAssembler — context window building."""

import pytest

from src.core.models import Agent, ExecutionConfig, MemoryConfig, Message, ModelConfig
from src.engine.context import ContextAssembler


def _make_agent(**overrides) -> Agent:
    defaults = dict(
        tenant_id="t1",
        name="test-agent",
        system_prompt="You are a helpful assistant.",
        model_config=ModelConfig(),
        execution_config=ExecutionConfig(max_context_tokens=8000),
        memory_config=MemoryConfig(),
    )
    defaults.update(overrides)
    return Agent(**defaults)


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content, session_id="s1")


@pytest.fixture
def assembler() -> ContextAssembler:
    return ContextAssembler()


@pytest.fixture
def agent() -> Agent:
    return _make_agent()


# --- Basic assembly ---


class TestBasicAssembly:
    def test_system_prompt_preserved(self, assembler: ContextAssembler, agent: Agent):
        msgs = [_msg("user", "hello")]
        ctx = assembler.build(agent, msgs)
        assert ctx.system_prompt == agent.system_prompt

    def test_messages_included(self, assembler: ContextAssembler, agent: Agent):
        msgs = [_msg("user", "hello"), _msg("assistant", "hi")]
        ctx = assembler.build(agent, msgs)
        assert len(ctx.messages) == 2
        assert ctx.messages[0].role == "user"

    def test_tool_schemas_passed_through(self, assembler: ContextAssembler, agent: Agent):
        schemas = [{"name": "search", "description": "search tool"}]
        ctx = assembler.build(agent, [_msg("user", "hi")], tool_schemas=schemas)
        assert ctx.tool_schemas == schemas

    def test_token_estimate_positive(self, assembler: ContextAssembler, agent: Agent):
        ctx = assembler.build(agent, [_msg("user", "hello world")])
        assert ctx.total_tokens_estimate > 0


# --- Budget warning injection ---


class TestBudgetWarning:
    def test_budget_warning_injected(self, assembler: ContextAssembler, agent: Agent):
        ctx = assembler.build(agent, [_msg("user", "hi")], budget_warning="Token budget at 85%")
        system_msgs = [m for m in ctx.messages if "[BUDGET WARNING]" in m.content]
        assert len(system_msgs) == 1
        assert ctx.budget_warning == "Token budget at 85%"

    def test_no_budget_warning_when_none(self, assembler: ContextAssembler, agent: Agent):
        ctx = assembler.build(agent, [_msg("user", "hi")])
        assert ctx.budget_warning is None


# --- Summary injection ---


class TestSummaryInjection:
    def test_summary_injected(self, assembler: ContextAssembler, agent: Agent):
        ctx = assembler.build(agent, [_msg("user", "hi")], summary="Previous discussion about X.")
        summary_msgs = [m for m in ctx.messages if "[CONVERSATION SUMMARY]" in m.content]
        assert len(summary_msgs) == 1
        assert ctx.has_summary is True

    def test_no_summary_flag_when_absent(self, assembler: ContextAssembler, agent: Agent):
        ctx = assembler.build(agent, [_msg("user", "hi")])
        assert ctx.has_summary is False


# --- Trimming behavior ---


class TestTrimming:
    def test_recent_messages_kept_over_middle(self, assembler: ContextAssembler):
        """Recent messages should survive trimming before middle sections."""
        agent = _make_agent(
            execution_config=ExecutionConfig(max_context_tokens=200),
            system_prompt="sys",
        )
        msgs = [_msg("user", "short")]
        ctx = assembler.build(agent, msgs, budget_warning="w" * 500, summary="s" * 500)
        # Recent messages must be in final output
        user_msgs = [m for m in ctx.messages if m.role == "user"]
        assert len(user_msgs) >= 1

    def test_oldest_messages_dropped_when_over_budget(self, assembler: ContextAssembler):
        """When too many recent messages, oldest are dropped."""
        agent = _make_agent(
            execution_config=ExecutionConfig(max_context_tokens=100),
            system_prompt="s",
        )
        msgs = [_msg("user", "a" * 200), _msg("user", "b" * 50)]
        ctx = assembler.build(agent, msgs)
        # The second (newer) message should be kept
        assert any("b" in m.content for m in ctx.messages)


# --- Empty inputs ---


class TestEdgeCases:
    def test_empty_messages(self, assembler: ContextAssembler, agent: Agent):
        ctx = assembler.build(agent, [])
        assert ctx.messages == []
        assert ctx.system_prompt == agent.system_prompt

    def test_empty_tool_schemas(self, assembler: ContextAssembler, agent: Agent):
        ctx = assembler.build(agent, [_msg("user", "hi")], tool_schemas=[])
        assert ctx.tool_schemas == []
