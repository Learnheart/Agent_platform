"""Tests for API Layer — routes, middleware, responses."""

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.responses import error, success
from src.core.security import create_jwt_token


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def _auth_headers(tenant_id: str = "t1") -> dict:
    """Create auth headers with a valid JWT."""
    token = create_jwt_token(
        user_id="user1",
        tenant_id=tenant_id,
        roles=["admin"],
        secret="dev-secret",
    )
    return {"Authorization": f"Bearer {token}"}


def _api_key_headers(tenant_id: str = "t1") -> dict:
    return {"X-API-Key": f"apt_{tenant_id}_testkey123"}


# ============================================================
# Response helpers
# ============================================================


class TestResponses:
    def test_success_envelope(self):
        resp = success({"id": "123"})
        assert "data" in resp
        assert "meta" in resp
        assert resp["data"]["id"] == "123"
        assert "request_id" in resp["meta"]
        assert "timestamp" in resp["meta"]

    def test_error_envelope(self):
        resp = error("NOT_FOUND", "Resource not found")
        assert "error" in resp
        assert resp["error"]["code"] == "NOT_FOUND"
        assert "meta" in resp


# ============================================================
# Health endpoint
# ============================================================


class TestHealth:
    def test_health_check(self, client: TestClient):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ============================================================
# Auth middleware
# ============================================================


class TestAuth:
    def test_no_auth_returns_401(self, client: TestClient):
        resp = client.get("/api/v1/agents")
        assert resp.status_code == 401

    def test_api_key_auth(self, client: TestClient):
        resp = client.get("/api/v1/agents", headers=_api_key_headers())
        assert resp.status_code == 200

    def test_invalid_api_key(self, client: TestClient):
        resp = client.get("/api/v1/agents", headers={"X-API-Key": "bad"})
        assert resp.status_code == 401


# ============================================================
# Agent CRUD
# ============================================================


class TestAgentEndpoints:
    def test_list_agents(self, client: TestClient):
        resp = client.get("/api/v1/agents", headers=_api_key_headers())
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "agents" in data

    def test_get_agent(self, client: TestClient):
        resp = client.get("/api/v1/agents/a1", headers=_api_key_headers())
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == "a1"

    def test_create_agent_requires_builder(self, client: TestClient):
        # API key user = end_user, should fail builder check
        resp = client.post("/api/v1/agents", json={"name": "test"}, headers=_api_key_headers())
        assert resp.status_code == 403


# ============================================================
# Session endpoints
# ============================================================


class TestSessionEndpoints:
    def test_create_session(self, client: TestClient):
        resp = client.post(
            "/api/v1/sessions",
            json={"agent_id": "a1"},
            headers=_api_key_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["state"] == "created"

    def test_get_session(self, client: TestClient):
        resp = client.get("/api/v1/sessions/s1", headers=_api_key_headers())
        assert resp.status_code == 200

    def test_send_message(self, client: TestClient):
        resp = client.post(
            "/api/v1/sessions/s1/messages",
            json={"content": "hello"},
            headers=_api_key_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "enqueued"


# ============================================================
# SSE streaming
# ============================================================


class TestSSEHelper:
    def test_sse_format(self):
        from src.api.routes import _sse_format
        result = _sse_format("connected", {"session_id": "s1"})
        assert "event: connected" in result
        assert '"session_id"' in result
        assert result.endswith("\n\n")
