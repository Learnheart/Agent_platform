"""Tests for CircuitBreaker — per-server resilience."""

import time
from unittest.mock import patch

import pytest

from src.providers.mcp.circuit_breaker import CircuitBreaker, CircuitState


@pytest.fixture
def cb() -> CircuitBreaker:
    return CircuitBreaker(failure_threshold=3, window_seconds=60.0, cooldown_seconds=5.0)


class TestClosedState:
    def test_new_server_allows_requests(self, cb: CircuitBreaker):
        assert cb.allow_request("s1") is True

    def test_state_starts_closed(self, cb: CircuitBreaker):
        assert cb.get_state("s1") == CircuitState.CLOSED

    def test_failures_below_threshold_stay_closed(self, cb: CircuitBreaker):
        cb.record_failure("s1")
        cb.record_failure("s1")
        assert cb.get_state("s1") == CircuitState.CLOSED
        assert cb.allow_request("s1") is True

    def test_success_resets_failure_count(self, cb: CircuitBreaker):
        cb.record_failure("s1")
        cb.record_failure("s1")
        cb.record_success("s1")
        cb.record_failure("s1")
        cb.record_failure("s1")
        # Should still be closed because success reset the count
        assert cb.get_state("s1") == CircuitState.CLOSED


class TestOpenState:
    def test_trips_at_threshold(self, cb: CircuitBreaker):
        for _ in range(3):
            cb.record_failure("s1")
        assert cb.get_state("s1") == CircuitState.OPEN

    def test_rejects_requests_when_open(self, cb: CircuitBreaker):
        for _ in range(3):
            cb.record_failure("s1")
        assert cb.allow_request("s1") is False


class TestHalfOpenState:
    def test_transitions_to_half_open_after_cooldown(self, cb: CircuitBreaker):
        for _ in range(3):
            cb.record_failure("s1")
        assert cb.get_state("s1") == CircuitState.OPEN

        # Simulate cooldown elapsed
        state = cb._states["s1"]
        cb._states["s1"] = state._replace(opened_at=time.monotonic() - 10)

        assert cb.get_state("s1") == CircuitState.HALF_OPEN
        assert cb.allow_request("s1") is True

    def test_success_in_half_open_closes(self, cb: CircuitBreaker):
        for _ in range(3):
            cb.record_failure("s1")
        # Force HALF_OPEN
        state = cb._states["s1"]
        cb._states["s1"] = state._replace(opened_at=time.monotonic() - 10)
        cb.allow_request("s1")  # triggers transition

        cb.record_success("s1")
        assert cb.get_state("s1") == CircuitState.CLOSED

    def test_failure_in_half_open_reopens(self, cb: CircuitBreaker):
        for _ in range(3):
            cb.record_failure("s1")
        state = cb._states["s1"]
        cb._states["s1"] = state._replace(opened_at=time.monotonic() - 10)
        cb.allow_request("s1")  # triggers HALF_OPEN

        cb.record_failure("s1")
        assert cb.get_state("s1") == CircuitState.OPEN


class TestWindowReset:
    def test_failures_outside_window_reset(self):
        cb = CircuitBreaker(failure_threshold=3, window_seconds=1.0, cooldown_seconds=5.0)
        cb.record_failure("s1")
        cb.record_failure("s1")
        # Simulate window elapsed by adjusting last_failure_time
        state = cb._states["s1"]
        cb._states["s1"] = state._replace(last_failure_time=time.monotonic() - 2)
        cb.record_failure("s1")
        # Count should have reset (only 1 failure in new window)
        assert cb.get_state("s1") == CircuitState.CLOSED


class TestMultipleServers:
    def test_independent_tracking(self, cb: CircuitBreaker):
        for _ in range(3):
            cb.record_failure("s1")
        assert cb.get_state("s1") == CircuitState.OPEN
        assert cb.get_state("s2") == CircuitState.CLOSED
        assert cb.allow_request("s2") is True
