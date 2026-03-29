"""E2E: Repository CRUD against real PostgreSQL."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.store.postgres.agent_repo import AgentRepository
from src.store.postgres.message_repo import MessageRepository
from src.store.postgres.session_repo import SessionRepository

pytestmark = pytest.mark.e2e


def _agent_data(agent_id: str | None = None) -> dict:
    return {
        "id": agent_id or f"agent_{uuid.uuid4().hex[:8]}",
        "name": "E2E Test Agent",
        "description": "Created by e2e test",
        "system_prompt": "You are a helpful assistant.",
        "model_config": {"model": "claude-sonnet-4-5-20250514", "max_tokens": 1024},
        "execution_config": {"max_steps": 10},
        "memory_config": {"type": "buffer"},
        "guardrails_config": {},
        "tools_config": {},
        "status": "draft",
        "created_by": "e2e_builder",
    }


class TestAgentRepository:
    """Full CRUD lifecycle for agents on real DB."""

    async def test_create_and_get(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        test_tenant_id: str,
    ) -> None:
        repo = AgentRepository(db_session_factory)
        data = _agent_data()
        agent_id = data["id"]

        created = await repo.create(test_tenant_id, data)
        assert created["id"] == agent_id
        assert created["tenant_id"] == test_tenant_id

        fetched = await repo.get(test_tenant_id, agent_id)
        assert fetched is not None
        assert fetched["name"] == "E2E Test Agent"
        assert fetched["system_prompt"] == "You are a helpful assistant."

    async def test_update(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        test_tenant_id: str,
    ) -> None:
        repo = AgentRepository(db_session_factory)
        data = _agent_data()
        agent_id = data["id"]
        await repo.create(test_tenant_id, data)

        updated = await repo.update(test_tenant_id, agent_id, {"name": "Updated Agent"})
        assert updated is not None
        assert updated["name"] == "Updated Agent"

    async def test_soft_delete(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        test_tenant_id: str,
    ) -> None:
        repo = AgentRepository(db_session_factory)
        data = _agent_data()
        agent_id = data["id"]
        await repo.create(test_tenant_id, data)

        deleted = await repo.delete(test_tenant_id, agent_id)
        assert deleted is True

        fetched = await repo.get(test_tenant_id, agent_id)
        assert fetched is not None
        assert fetched["status"] == "archived"

    async def test_list_with_pagination(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        test_tenant_id: str,
    ) -> None:
        repo = AgentRepository(db_session_factory)
        # Create 3 agents
        for _ in range(3):
            await repo.create(test_tenant_id, _agent_data())

        result = await repo.list(test_tenant_id, limit=2)
        assert len(result["items"]) == 2
        assert result["has_more"] is True
        assert result["next_cursor"] is not None

        # Fetch next page
        result2 = await repo.list(test_tenant_id, limit=2, cursor=result["next_cursor"])
        assert len(result2["items"]) >= 1


class TestSessionRepository:
    """Session CRUD + state transitions on real DB."""

    async def test_create_and_state_update(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        test_tenant_id: str,
    ) -> None:
        agent_repo = AgentRepository(db_session_factory)
        session_repo = SessionRepository(db_session_factory)

        # Must create agent first (FK constraint)
        agent_data = _agent_data()
        await agent_repo.create(test_tenant_id, agent_data)

        session_id = f"sess_{uuid.uuid4().hex[:8]}"
        await session_repo.create(test_tenant_id, {
            "id": session_id,
            "agent_id": agent_data["id"],
            "state": "created",
            "created_by": "e2e_builder",
        })

        fetched = await session_repo.get(test_tenant_id, session_id)
        assert fetched is not None
        assert fetched["state"] == "created"

        # Transition to running
        ok = await session_repo.update_state(test_tenant_id, session_id, "running", step_index=1)
        assert ok is True

        fetched = await session_repo.get(test_tenant_id, session_id)
        assert fetched["state"] == "running"
        assert fetched["step_index"] == 1


class TestMessageRepository:
    """Message persistence on real DB."""

    async def test_create_and_list(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        test_tenant_id: str,
    ) -> None:
        agent_repo = AgentRepository(db_session_factory)
        session_repo = SessionRepository(db_session_factory)
        msg_repo = MessageRepository(db_session_factory)

        # Setup: agent → session
        agent_data = _agent_data()
        await agent_repo.create(test_tenant_id, agent_data)

        session_id = f"sess_{uuid.uuid4().hex[:8]}"
        await session_repo.create(test_tenant_id, {
            "id": session_id,
            "agent_id": agent_data["id"],
            "state": "created",
            "created_by": "e2e_builder",
        })

        # Create messages
        await msg_repo.create(test_tenant_id, {
            "session_id": session_id,
            "id": f"msg_{uuid.uuid4().hex[:8]}",
            "role": "user",
            "content": "Hello from e2e test",
        })
        await msg_repo.create(test_tenant_id, {
            "session_id": session_id,
            "id": f"msg_{uuid.uuid4().hex[:8]}",
            "role": "assistant",
            "content": "Hello! I'm the e2e test assistant.",
        })

        msgs = await msg_repo.list_by_session(test_tenant_id, session_id)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

        count = await msg_repo.count_by_session(test_tenant_id, session_id)
        assert count == 2

    async def test_batch_create(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        test_tenant_id: str,
    ) -> None:
        agent_repo = AgentRepository(db_session_factory)
        session_repo = SessionRepository(db_session_factory)
        msg_repo = MessageRepository(db_session_factory)

        agent_data = _agent_data()
        await agent_repo.create(test_tenant_id, agent_data)

        session_id = f"sess_{uuid.uuid4().hex[:8]}"
        await session_repo.create(test_tenant_id, {
            "id": session_id,
            "agent_id": agent_data["id"],
            "state": "created",
            "created_by": "e2e_builder",
        })

        items = [
            {"session_id": session_id, "id": f"msg_{i}", "role": "user", "content": f"Msg {i}"}
            for i in range(5)
        ]
        count = await msg_repo.create_batch(test_tenant_id, items)
        assert count == 5
