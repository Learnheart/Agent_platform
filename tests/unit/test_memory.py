"""Tests for Memory System — ConversationBuffer, WorkingMemory, Summarizer, MemoryManager."""

from unittest.mock import AsyncMock

import pytest

from src.core.models import Agent, ExecutionConfig, LLMResponse, MemoryConfig, Message, ModelConfig, TokenUsage
from src.memory.conversation_buffer import ConversationBuffer
from src.memory.manager import MemoryManager
from src.memory.summarizer import ConversationSummarizer
from src.memory.working import WorkingMemory


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content, session_id="s1")


def _agent(**overrides) -> Agent:
    defaults = dict(
        tenant_id="t1",
        name="test",
        system_prompt="You are helpful.",
        model_config=ModelConfig(),
        execution_config=ExecutionConfig(max_context_tokens=8000),
        memory_config=MemoryConfig(max_context_tokens=8000, summarize_threshold=0.7),
    )
    defaults.update(overrides)
    return Agent(**defaults)


def _mock_session_store() -> AsyncMock:
    """Mock SessionRedisStore."""
    store = AsyncMock()
    store._messages: list = []
    store._summary: str | None = None
    store._working: dict = {}

    async def append_message(sid, msg):
        store._messages.append(msg)

    async def append_messages(sid, msgs):
        store._messages.extend(msgs)

    async def get_all_messages(sid):
        return list(store._messages)

    async def get_recent_messages(sid, n):
        return list(store._messages[-n:])

    async def get_message_count(sid):
        return len(store._messages)

    async def get_summary(sid):
        return store._summary

    async def set_summary(sid, s):
        store._summary = s

    async def get_working_field(sid, field):
        return store._working.get(field)

    async def set_working_field(sid, field, value):
        store._working[field] = value

    store.append_message = append_message
    store.append_messages = append_messages
    store.get_all_messages = get_all_messages
    store.get_recent_messages = get_recent_messages
    store.get_message_count = get_message_count
    store.get_summary = get_summary
    store.set_summary = set_summary
    store.get_working_field = get_working_field
    store.set_working_field = set_working_field
    return store


# ============================================================
# ConversationBuffer
# ============================================================


class TestConversationBuffer:
    @pytest.mark.asyncio
    async def test_append_and_get_all(self):
        store = _mock_session_store()
        buf = ConversationBuffer(store)
        await buf.append("s1", _msg("user", "hello"))
        msgs = await buf.get_all("s1")
        assert len(msgs) == 1
        assert msgs[0].content == "hello"

    @pytest.mark.asyncio
    async def test_append_many(self):
        store = _mock_session_store()
        buf = ConversationBuffer(store)
        await buf.append_many("s1", [_msg("user", "a"), _msg("assistant", "b")])
        msgs = await buf.get_all("s1")
        assert len(msgs) == 2

    @pytest.mark.asyncio
    async def test_get_recent(self):
        store = _mock_session_store()
        buf = ConversationBuffer(store)
        await buf.append_many("s1", [_msg("user", "a"), _msg("assistant", "b"), _msg("user", "c")])
        recent = await buf.get_recent("s1", 2)
        assert len(recent) == 2
        assert recent[0].content == "b"

    @pytest.mark.asyncio
    async def test_token_count(self):
        store = _mock_session_store()
        buf = ConversationBuffer(store)
        await buf.append("s1", _msg("user", "hello world"))
        count = await buf.get_token_count("s1")
        assert count > 0

    @pytest.mark.asyncio
    async def test_summary_roundtrip(self):
        store = _mock_session_store()
        buf = ConversationBuffer(store)
        await buf.set_summary("s1", "discussion about X")
        s = await buf.get_summary("s1")
        assert s == "discussion about X"


# ============================================================
# WorkingMemory
# ============================================================


class TestWorkingMemory:
    @pytest.mark.asyncio
    async def test_plan_roundtrip(self):
        store = _mock_session_store()
        wm = WorkingMemory(store)
        await wm.update_plan("s1", {"goal": "test", "steps": []})
        plan = await wm.get_plan("s1")
        assert plan["goal"] == "test"

    @pytest.mark.asyncio
    async def test_plan_none_initially(self):
        store = _mock_session_store()
        wm = WorkingMemory(store)
        assert await wm.get_plan("s1") is None

    @pytest.mark.asyncio
    async def test_artifact_store_and_get(self):
        store = _mock_session_store()
        wm = WorkingMemory(store)
        await wm.store_artifact("s1", "search_result", {"data": [1, 2, 3]})
        artifacts = await wm.get_artifacts("s1")
        assert artifacts["search_result"] == {"data": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_scratchpad_roundtrip(self):
        store = _mock_session_store()
        wm = WorkingMemory(store)
        await wm.update_scratchpad("s1", "thinking about X")
        s = await wm.get_scratchpad("s1")
        assert s == "thinking about X"

    @pytest.mark.asyncio
    async def test_build_context_string_empty(self):
        store = _mock_session_store()
        wm = WorkingMemory(store)
        ctx = await wm.build_context_string("s1")
        assert ctx is None

    @pytest.mark.asyncio
    async def test_build_context_string_with_data(self):
        store = _mock_session_store()
        wm = WorkingMemory(store)
        await wm.update_plan("s1", {"goal": "research", "steps": [{"status": "running", "task": "step 1"}]})
        await wm.update_scratchpad("s1", "note: important finding")
        ctx = await wm.build_context_string("s1")
        assert ctx is not None
        assert "research" in ctx
        assert "important finding" in ctx


# ============================================================
# ConversationSummarizer
# ============================================================


class TestSummarizer:
    @pytest.mark.asyncio
    async def test_fallback_when_no_llm(self):
        summarizer = ConversationSummarizer(llm_gateway=None)
        msgs = [_msg("user", "hello"), _msg("assistant", "hi there")]
        result = await summarizer.summarize(msgs)
        assert "[user]" in result
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_fallback_with_existing_summary(self):
        summarizer = ConversationSummarizer(llm_gateway=None)
        result = await summarizer.summarize([_msg("user", "new message")], existing_summary="old context")
        assert "old context" in result

    @pytest.mark.asyncio
    async def test_empty_messages(self):
        summarizer = ConversationSummarizer(llm_gateway=None)
        result = await summarizer.summarize([])
        assert result == ""

    @pytest.mark.asyncio
    async def test_llm_summarization(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=LLMResponse(
            content="Summary: user asked about X, assistant explained Y.",
            usage=TokenUsage(),
        ))
        summarizer = ConversationSummarizer(llm_gateway=llm)
        result = await summarizer.summarize([_msg("user", "tell me about X")])
        assert "Summary" in result
        llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_failure_uses_fallback(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
        summarizer = ConversationSummarizer(llm_gateway=llm)
        result = await summarizer.summarize([_msg("user", "hello")])
        assert "hello" in result  # fallback used


# ============================================================
# MemoryManager
# ============================================================


class TestMemoryManager:
    def _make_manager(self):
        store = _mock_session_store()
        buf = ConversationBuffer(store)
        wm = WorkingMemory(store)
        summarizer = ConversationSummarizer(llm_gateway=None)
        return MemoryManager(buf, wm, summarizer), store

    @pytest.mark.asyncio
    async def test_build_context_basic(self):
        mgr, store = self._make_manager()
        store._messages = [_msg("user", "hello").model_dump(mode="json")]
        ctx = await mgr.build_context("s1", _agent())
        assert ctx.system_prompt == "You are helpful."
        assert len(ctx.messages) >= 1

    @pytest.mark.asyncio
    async def test_build_context_includes_summary(self):
        mgr, store = self._make_manager()
        store._summary = "Previous discussion about X."
        store._messages = [_msg("user", "continue").model_dump(mode="json")]
        ctx = await mgr.build_context("s1", _agent())
        assert ctx.has_summary is True
        summary_msgs = [m for m in ctx.messages if "CONVERSATION SUMMARY" in m.content]
        assert len(summary_msgs) == 1

    @pytest.mark.asyncio
    async def test_build_context_includes_budget_warning(self):
        mgr, store = self._make_manager()
        store._messages = [_msg("user", "hi").model_dump(mode="json")]
        ctx = await mgr.build_context("s1", _agent(), budget_warning="Token budget at 85%")
        assert ctx.budget_warning is not None
        warn_msgs = [m for m in ctx.messages if "BUDGET WARNING" in m.content]
        assert len(warn_msgs) == 1

    @pytest.mark.asyncio
    async def test_build_context_includes_working_memory(self):
        mgr, store = self._make_manager()
        store._working["plan"] = {"goal": "find bugs", "steps": []}
        store._messages = [_msg("user", "start").model_dump(mode="json")]
        ctx = await mgr.build_context("s1", _agent())
        plan_msgs = [m for m in ctx.messages if "find bugs" in m.content]
        assert len(plan_msgs) == 1

    @pytest.mark.asyncio
    async def test_update_appends_messages(self):
        mgr, store = self._make_manager()
        await mgr.update("s1", [_msg("user", "new msg")], _agent())
        assert len(store._messages) == 1

    @pytest.mark.asyncio
    async def test_update_stores_artifacts(self):
        mgr, store = self._make_manager()
        await mgr.update("s1", [], _agent(), artifacts={"result": "data"})
        artifacts = store._working.get("artifacts")
        assert artifacts is not None
        assert artifacts["result"] == "data"

    @pytest.mark.asyncio
    async def test_token_estimate_positive(self):
        mgr, store = self._make_manager()
        store._messages = [_msg("user", "hello world").model_dump(mode="json")]
        ctx = await mgr.build_context("s1", _agent())
        assert ctx.total_tokens_estimate > 0
