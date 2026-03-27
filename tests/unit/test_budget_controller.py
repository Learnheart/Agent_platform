"""Tests for BudgetController — 4-dimension budget enforcement."""

from datetime import datetime, timedelta, timezone

import pytest

from src.core.models import ExecutionConfig, Session, SessionUsage
from src.engine.budget import BudgetController


def _make_session(**overrides) -> Session:
    defaults = dict(
        tenant_id="t1",
        agent_id="a1",
        step_index=0,
        usage=SessionUsage(),
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Session(**defaults)


@pytest.fixture
def ctrl() -> BudgetController:
    return BudgetController()


@pytest.fixture
def config() -> ExecutionConfig:
    return ExecutionConfig(
        max_steps=30,
        max_tokens_budget=50000,
        max_cost_usd=5.0,
        max_duration_seconds=600,
    )


# --- Basic checks ---


class TestBudgetControllerBasic:
    def test_fresh_session_no_warning(self, ctrl: BudgetController, config: ExecutionConfig):
        session = _make_session()
        result = ctrl.check(session, config)
        assert not result.exhausted
        assert not result.warning
        assert not result.critical
        assert len(result.checks) == 4

    def test_returns_four_dimensions(self, ctrl: BudgetController, config: ExecutionConfig):
        session = _make_session()
        result = ctrl.check(session, config)
        types = {c.type for c in result.checks}
        assert types == {"tokens", "cost", "steps", "time"}


# --- Token budget ---


class TestTokenBudget:
    def test_token_warning(self, ctrl: BudgetController, config: ExecutionConfig):
        session = _make_session(usage=SessionUsage(total_tokens=42000))
        result = ctrl.check(session, config)
        assert result.warning
        assert not result.exhausted

    def test_token_exhausted(self, ctrl: BudgetController, config: ExecutionConfig):
        session = _make_session(usage=SessionUsage(total_tokens=50000))
        result = ctrl.check(session, config)
        assert result.exhausted

    def test_token_critical(self, ctrl: BudgetController, config: ExecutionConfig):
        session = _make_session(usage=SessionUsage(total_tokens=48000))
        result = ctrl.check(session, config)
        assert result.critical


# --- Cost budget ---


class TestCostBudget:
    def test_cost_warning(self, ctrl: BudgetController, config: ExecutionConfig):
        session = _make_session(usage=SessionUsage(total_cost_usd=4.2))
        result = ctrl.check(session, config)
        assert result.warning

    def test_cost_exhausted(self, ctrl: BudgetController, config: ExecutionConfig):
        session = _make_session(usage=SessionUsage(total_cost_usd=5.0))
        result = ctrl.check(session, config)
        assert result.exhausted


# --- Step budget ---


class TestStepBudget:
    def test_step_warning(self, ctrl: BudgetController, config: ExecutionConfig):
        session = _make_session(step_index=25)
        result = ctrl.check(session, config)
        assert result.warning

    def test_step_exhausted(self, ctrl: BudgetController, config: ExecutionConfig):
        session = _make_session(step_index=30)
        result = ctrl.check(session, config)
        assert result.exhausted


# --- Time budget ---


class TestTimeBudget:
    def test_time_warning(self, ctrl: BudgetController, config: ExecutionConfig):
        created = datetime.now(timezone.utc) - timedelta(seconds=500)
        session = _make_session(created_at=created)
        result = ctrl.check(session, config)
        assert result.warning

    def test_time_exhausted(self, ctrl: BudgetController, config: ExecutionConfig):
        created = datetime.now(timezone.utc) - timedelta(seconds=601)
        session = _make_session(created_at=created)
        result = ctrl.check(session, config)
        assert result.exhausted


# --- Warning message ---


class TestWarningMessage:
    def test_warning_message_contains_type(self, ctrl: BudgetController, config: ExecutionConfig):
        session = _make_session(usage=SessionUsage(total_tokens=42000))
        result = ctrl.check(session, config)
        assert "tokens" in result.warning_message

    def test_no_warning_message_when_safe(self, ctrl: BudgetController, config: ExecutionConfig):
        session = _make_session()
        result = ctrl.check(session, config)
        assert result.warning_message == ""


# --- Edge: disabled dimensions ---


class TestDisabledDimensions:
    def test_zero_budget_skips_dimension(self, ctrl: BudgetController):
        config = ExecutionConfig(max_steps=0, max_tokens_budget=0, max_cost_usd=0, max_duration_seconds=0)
        session = _make_session()
        result = ctrl.check(session, config)
        assert len(result.checks) == 0
        assert not result.exhausted
