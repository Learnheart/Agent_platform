"""API Routes — REST endpoints for the Agent Platform.

Phase 1: Agent CRUD + Session management + SSE streaming.
See docs/architecture/10-api-contracts.md.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.api.middleware import get_auth_context, require_builder
from src.api.responses import error, success
from src.core.models import AuthContext

router = APIRouter(prefix="/api/v1")


# ============================================================
# Health
# ============================================================


@router.get("/health")
async def health_check():
    return {"status": "ok"}


# ============================================================
# Agents CRUD
# ============================================================


@router.post("/agents")
async def create_agent(
    body: dict[str, Any],
    auth: AuthContext = Depends(require_builder),
):
    """Create a new agent definition."""
    # Phase 1: basic structure — will be wired to AgentRepository
    return success({
        "id": "placeholder",
        "tenant_id": auth.tenant_id,
        "name": body.get("name", ""),
        "status": "draft",
    })


@router.get("/agents")
async def list_agents(
    auth: AuthContext = Depends(get_auth_context),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List agents for the authenticated tenant."""
    return success({
        "agents": [],
        "total": 0,
        "page": page,
        "page_size": page_size,
    })


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """Get agent details."""
    return success({"id": agent_id, "tenant_id": auth.tenant_id})


@router.put("/agents/{agent_id}")
async def update_agent(
    agent_id: str,
    body: dict[str, Any],
    auth: AuthContext = Depends(require_builder),
):
    """Update an agent definition."""
    return success({"id": agent_id, "updated": True})


# ============================================================
# Sessions
# ============================================================


@router.post("/sessions")
async def create_session(
    body: dict[str, Any],
    auth: AuthContext = Depends(get_auth_context),
):
    """Create a new execution session."""
    return success({
        "id": "placeholder",
        "agent_id": body.get("agent_id", ""),
        "tenant_id": auth.tenant_id,
        "state": "created",
    })


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """Get session status and details."""
    return success({"id": session_id, "tenant_id": auth.tenant_id})


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    body: dict[str, Any],
    auth: AuthContext = Depends(get_auth_context),
):
    """Send a message to a session (triggers execution)."""
    return success({
        "session_id": session_id,
        "message_id": "placeholder",
        "status": "enqueued",
    })


# ============================================================
# SSE Streaming
# ============================================================


@router.get("/sessions/{session_id}/stream")
async def stream_session(
    session_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """Server-Sent Events stream for real-time session updates.

    Wire protocol:
    event: {type}
    data: {json}
    id: {event_id}
    """
    async def event_generator():
        # Phase 1: placeholder generator
        # Will be wired to SSEConsumer queue in production
        yield _sse_format("connected", {"session_id": session_id})
        # Keep connection alive with heartbeat
        try:
            while True:
                await asyncio.sleep(15)
                yield _sse_format("heartbeat", {})
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse_format(event_type: str, data: dict) -> str:
    """Format an SSE event string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
