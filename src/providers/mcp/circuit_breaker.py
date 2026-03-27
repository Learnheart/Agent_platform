"""Circuit Breaker — per-server resilience pattern.

Prevents cascading failures by tracking error rates per MCP server.

States: CLOSED → OPEN → HALF_OPEN → CLOSED (or back to OPEN).

See docs/architecture/06-mcp-tools.md Section 2.2.5.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import NamedTuple


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class _ServerState(NamedTuple):
    state: CircuitState
    failure_count: int
    last_failure_time: float
    opened_at: float


class CircuitBreaker:
    """Per-server circuit breaker.

    Args:
        failure_threshold: Failures within window to trip OPEN.
        window_seconds: Sliding window for counting failures.
        cooldown_seconds: Time in OPEN before transitioning to HALF_OPEN.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        window_seconds: float = 60.0,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._threshold = failure_threshold
        self._window = window_seconds
        self._cooldown = cooldown_seconds
        self._states: dict[str, _ServerState] = {}

    def allow_request(self, server_id: str) -> bool:
        """Check if a request to this server is allowed."""
        s = self._get(server_id)

        match s.state:
            case CircuitState.CLOSED:
                return True
            case CircuitState.OPEN:
                # Check if cooldown has elapsed → transition to HALF_OPEN
                if time.monotonic() - s.opened_at >= self._cooldown:
                    self._states[server_id] = s._replace(state=CircuitState.HALF_OPEN)
                    return True  # Allow one test request
                return False
            case CircuitState.HALF_OPEN:
                return True  # Allow test request

    def record_success(self, server_id: str) -> None:
        """Record a successful request."""
        s = self._get(server_id)

        match s.state:
            case CircuitState.HALF_OPEN:
                # Recovery confirmed → close circuit
                self._states[server_id] = _ServerState(
                    state=CircuitState.CLOSED,
                    failure_count=0,
                    last_failure_time=0.0,
                    opened_at=0.0,
                )
            case CircuitState.CLOSED:
                # Reset failure count on success (sliding window resets)
                if s.failure_count > 0:
                    self._states[server_id] = s._replace(failure_count=0)

    def record_failure(self, server_id: str) -> None:
        """Record a failed request."""
        now = time.monotonic()
        s = self._get(server_id)

        match s.state:
            case CircuitState.HALF_OPEN:
                # Test request failed → back to OPEN
                self._states[server_id] = _ServerState(
                    state=CircuitState.OPEN,
                    failure_count=s.failure_count + 1,
                    last_failure_time=now,
                    opened_at=now,
                )
            case CircuitState.CLOSED:
                # Check if failure is within window
                if now - s.last_failure_time > self._window:
                    new_count = 1  # Reset window
                else:
                    new_count = s.failure_count + 1

                if new_count >= self._threshold:
                    # Trip to OPEN
                    self._states[server_id] = _ServerState(
                        state=CircuitState.OPEN,
                        failure_count=new_count,
                        last_failure_time=now,
                        opened_at=now,
                    )
                else:
                    self._states[server_id] = _ServerState(
                        state=CircuitState.CLOSED,
                        failure_count=new_count,
                        last_failure_time=now,
                        opened_at=0.0,
                    )
            case CircuitState.OPEN:
                # Already open, just update timestamp
                self._states[server_id] = s._replace(
                    failure_count=s.failure_count + 1,
                    last_failure_time=now,
                )

    def get_state(self, server_id: str) -> CircuitState:
        """Get current circuit state for a server."""
        s = self._get(server_id)
        # Check for auto-transition OPEN→HALF_OPEN
        if s.state == CircuitState.OPEN and time.monotonic() - s.opened_at >= self._cooldown:
            self._states[server_id] = s._replace(state=CircuitState.HALF_OPEN)
            return CircuitState.HALF_OPEN
        return s.state

    def _get(self, server_id: str) -> _ServerState:
        if server_id not in self._states:
            self._states[server_id] = _ServerState(
                state=CircuitState.CLOSED,
                failure_count=0,
                last_failure_time=0.0,
                opened_at=0.0,
            )
        return self._states[server_id]
