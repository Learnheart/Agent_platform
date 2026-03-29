"""E2E: API endpoints via HTTP with real auth."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.e2e


class TestHealthEndpoint:
    """Health check should always work without auth."""

    async def test_health(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestAuthFlow:
    """Verify JWT and API key authentication."""

    async def test_no_auth_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/agents")
        assert resp.status_code == 401

    async def test_invalid_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/agents",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401

    async def test_jwt_auth_succeeds(
        self, client: AsyncClient, builder_headers: dict[str, str],
    ) -> None:
        resp = await client.get("/api/v1/agents", headers=builder_headers)
        assert resp.status_code == 200

    async def test_api_key_auth_succeeds(
        self, client: AsyncClient, api_key_headers: dict[str, str],
    ) -> None:
        resp = await client.get("/api/v1/agents", headers=api_key_headers)
        assert resp.status_code == 200

    async def test_api_key_user_cannot_create_agent(
        self, client: AsyncClient, api_key_headers: dict[str, str],
    ) -> None:
        """Agent creation requires builder role."""
        resp = await client.post(
            "/api/v1/agents",
            json={"name": "Should Fail"},
            headers=api_key_headers,
        )
        assert resp.status_code == 403


class TestAgentEndpoints:
    """Agent CRUD via HTTP."""

    async def test_create_agent(
        self, client: AsyncClient, builder_headers: dict[str, str],
    ) -> None:
        resp = await client.post(
            "/api/v1/agents",
            json={"name": "E2E Agent"},
            headers=builder_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["name"] == "E2E Agent"
        assert body["data"]["status"] == "draft"
        assert "meta" in body

    async def test_list_agents(
        self, client: AsyncClient, builder_headers: dict[str, str],
    ) -> None:
        resp = await client.get("/api/v1/agents", headers=builder_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "agents" in body["data"]

    async def test_get_agent(
        self, client: AsyncClient, builder_headers: dict[str, str],
    ) -> None:
        resp = await client.get("/api/v1/agents/test-id", headers=builder_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == "test-id"

    async def test_update_agent(
        self, client: AsyncClient, builder_headers: dict[str, str],
    ) -> None:
        resp = await client.put(
            "/api/v1/agents/test-id",
            json={"name": "Updated"},
            headers=builder_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["updated"] is True


class TestSessionEndpoints:
    """Session management via HTTP."""

    async def test_create_session(
        self, client: AsyncClient, builder_headers: dict[str, str],
    ) -> None:
        resp = await client.post(
            "/api/v1/sessions",
            json={"agent_id": "agent-1"},
            headers=builder_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["agent_id"] == "agent-1"
        assert body["data"]["state"] == "created"

    async def test_get_session(
        self, client: AsyncClient, builder_headers: dict[str, str],
    ) -> None:
        resp = await client.get("/api/v1/sessions/sess-1", headers=builder_headers)
        assert resp.status_code == 200

    async def test_send_message(
        self, client: AsyncClient, builder_headers: dict[str, str],
    ) -> None:
        resp = await client.post(
            "/api/v1/sessions/sess-1/messages",
            json={"content": "Hello!"},
            headers=builder_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] == "enqueued"


class TestResponseEnvelope:
    """Verify all responses follow the standard envelope format."""

    async def test_success_envelope(
        self, client: AsyncClient, builder_headers: dict[str, str],
    ) -> None:
        resp = await client.get("/api/v1/agents", headers=builder_headers)
        body = resp.json()
        assert "data" in body
        assert "meta" in body
        assert "request_id" in body["meta"]
        assert "timestamp" in body["meta"]
        assert body["meta"]["request_id"].startswith("req_")
