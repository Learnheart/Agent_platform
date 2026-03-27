"""Tests for Governance System — AuditSink, CostTracker, DataClassifier, GovernanceService."""

from unittest.mock import AsyncMock

import pytest

from src.core.enums import DataSensitivity
from src.core.models import AuditActor, AuditEvent, CostEvent
from src.governance.audit_sink import AuditSink
from src.governance.cost_tracker import CostTracker
from src.governance.data_classifier import DataClassifier
from src.governance.service import GovernanceService


# ============================================================
# AuditSink
# ============================================================


class TestAuditSink:
    @pytest.mark.asyncio
    async def test_record_buffers_event(self):
        sink = AuditSink()
        event = AuditEvent(
            tenant_id="t1",
            category="session_lifecycle",
            action="session_created",
            actor=AuditActor(type="user", id="u1"),
        )
        await sink.record(event)
        assert sink.pending_count == 1

    @pytest.mark.asyncio
    async def test_flush_clears_buffer(self):
        sink = AuditSink()
        await sink.record(AuditEvent(
            tenant_id="t1", category="test", action="test",
            actor=AuditActor(type="system", id="sys"),
        ))
        await sink._flush()
        assert sink.pending_count == 0

    @pytest.mark.asyncio
    async def test_flush_calls_repo(self):
        repo = AsyncMock()
        repo.batch_insert = AsyncMock()
        sink = AuditSink(audit_repo=repo)
        await sink.record(AuditEvent(
            tenant_id="t1", category="test", action="test",
            actor=AuditActor(type="system", id="sys"),
        ))
        await sink._flush()
        repo.batch_insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_flush_at_buffer_limit(self):
        repo = AsyncMock()
        repo.batch_insert = AsyncMock()
        sink = AuditSink(audit_repo=repo, buffer_size=2)
        for _ in range(2):
            await sink.record(AuditEvent(
                tenant_id="t1", category="test", action="test",
                actor=AuditActor(type="system", id="sys"),
            ))
        repo.batch_insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_repo_failure_does_not_raise(self):
        repo = AsyncMock()
        repo.batch_insert = AsyncMock(side_effect=Exception("DB down"))
        sink = AuditSink(audit_repo=repo)
        await sink.record(AuditEvent(
            tenant_id="t1", category="test", action="test",
            actor=AuditActor(type="system", id="sys"),
        ))
        await sink._flush()  # no raise


# ============================================================
# CostTracker
# ============================================================


class TestCostTracker:
    @pytest.mark.asyncio
    async def test_track_accumulates(self):
        tracker = CostTracker()
        await tracker.track(CostEvent(
            tenant_id="t1", agent_id="a1", session_id="s1",
            cost_usd=0.05, input_tokens=100, output_tokens=50,
        ))
        await tracker.track(CostEvent(
            tenant_id="t1", agent_id="a1", session_id="s1",
            cost_usd=0.03, input_tokens=80, output_tokens=30,
        ))
        assert tracker.get_session_cost("s1") == pytest.approx(0.08)

    @pytest.mark.asyncio
    async def test_separate_sessions(self):
        tracker = CostTracker()
        await tracker.track(CostEvent(
            tenant_id="t1", agent_id="a1", session_id="s1", cost_usd=0.1,
        ))
        await tracker.track(CostEvent(
            tenant_id="t1", agent_id="a1", session_id="s2", cost_usd=0.2,
        ))
        assert tracker.get_session_cost("s1") == pytest.approx(0.1)
        assert tracker.get_session_cost("s2") == pytest.approx(0.2)

    def test_unknown_session_returns_zero(self):
        tracker = CostTracker()
        assert tracker.get_session_cost("nonexistent") == 0.0

    @pytest.mark.asyncio
    async def test_redis_failure_does_not_raise(self):
        redis = AsyncMock()
        redis.track = AsyncMock(side_effect=ConnectionError("Redis down"))
        tracker = CostTracker(redis_cost_store=redis)
        await tracker.track(CostEvent(
            tenant_id="t1", agent_id="a1", session_id="s1", cost_usd=0.05,
        ))
        assert tracker.get_session_cost("s1") == pytest.approx(0.05)


# ============================================================
# DataClassifier
# ============================================================


class TestDataClassifier:
    def test_clean_text(self):
        c = DataClassifier()
        result = c.classify("Hello world, nice weather today.")
        assert not result.has_sensitive_data
        assert result.sensitivity == DataSensitivity.PUBLIC

    def test_detects_email(self):
        c = DataClassifier()
        result = c.classify("Contact me at user@example.com")
        assert result.has_sensitive_data
        assert "email" in result.tags

    def test_detects_api_key(self):
        c = DataClassifier()
        result = c.classify("Use key sk-1234567890abcdefghijklmn")
        assert result.has_sensitive_data
        assert "api_key" in result.tags
        assert result.sensitivity == DataSensitivity.RESTRICTED

    def test_detects_credit_card(self):
        c = DataClassifier()
        result = c.classify("Card: 4111-1111-1111-1111")
        assert result.has_sensitive_data
        assert "credit_card" in result.tags

    def test_detects_ssn(self):
        c = DataClassifier()
        result = c.classify("SSN: 123-45-6789")
        assert "ssn" in result.tags

    def test_detects_aws_key(self):
        c = DataClassifier()
        result = c.classify("AKIAIOSFODNN7EXAMPLE")
        assert "aws_key" in result.tags

    def test_detects_password(self):
        c = DataClassifier()
        result = c.classify("password: MySecret123!")
        assert "password_field" in result.tags

    def test_multiple_types(self):
        c = DataClassifier()
        result = c.classify("Email: user@test.com, key: sk-abcdefghijklmnopqrstuv")
        assert len(result.tags) >= 2

    def test_empty_text(self):
        c = DataClassifier()
        result = c.classify("")
        assert not result.has_sensitive_data


# ============================================================
# GovernanceService
# ============================================================


class TestGovernanceService:
    @pytest.mark.asyncio
    async def test_record_audit(self):
        sink = AuditSink()
        svc = GovernanceService(audit_sink=sink)
        await svc.record_audit(AuditEvent(
            tenant_id="t1", category="test", action="test",
            actor=AuditActor(type="system", id="sys"),
        ))
        assert sink.pending_count == 1

    @pytest.mark.asyncio
    async def test_track_cost(self):
        tracker = CostTracker()
        svc = GovernanceService(cost_tracker=tracker)
        await svc.track_cost(CostEvent(
            tenant_id="t1", agent_id="a1", session_id="s1", cost_usd=0.1,
        ))
        assert svc.get_session_cost("s1") == pytest.approx(0.1)

    def test_classify(self):
        svc = GovernanceService()
        result = svc.classify("user@example.com")
        assert result.has_sensitive_data
