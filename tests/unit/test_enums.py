"""Tests for core enums and session state machine."""

import pytest

from src.core.enums import (
    AgentEventType,
    DataSensitivity,
    ErrorCategory,
    RiskLevel,
    SessionState,
    StepType,
    validate_session_transition,
)


class TestSessionState:
    def test_all_states_exist(self) -> None:
        assert SessionState.CREATED == "created"
        assert SessionState.RUNNING == "running"
        assert SessionState.PAUSED == "paused"
        assert SessionState.WAITING_INPUT == "waiting_input"
        assert SessionState.COMPLETED == "completed"
        assert SessionState.FAILED == "failed"

    def test_valid_transitions(self) -> None:
        valid = [
            (SessionState.CREATED, SessionState.RUNNING),
            (SessionState.RUNNING, SessionState.COMPLETED),
            (SessionState.RUNNING, SessionState.PAUSED),
            (SessionState.RUNNING, SessionState.WAITING_INPUT),
            (SessionState.RUNNING, SessionState.FAILED),
            (SessionState.PAUSED, SessionState.RUNNING),
            (SessionState.PAUSED, SessionState.FAILED),
            (SessionState.WAITING_INPUT, SessionState.RUNNING),
            (SessionState.WAITING_INPUT, SessionState.FAILED),
        ]
        for from_state, to_state in valid:
            assert validate_session_transition(from_state, to_state), (
                f"{from_state} -> {to_state} should be valid"
            )

    def test_invalid_transitions(self) -> None:
        invalid = [
            (SessionState.CREATED, SessionState.COMPLETED),
            (SessionState.CREATED, SessionState.FAILED),
            (SessionState.CREATED, SessionState.PAUSED),
            (SessionState.COMPLETED, SessionState.RUNNING),
            (SessionState.COMPLETED, SessionState.FAILED),
            (SessionState.FAILED, SessionState.RUNNING),
            (SessionState.FAILED, SessionState.COMPLETED),
            (SessionState.PAUSED, SessionState.COMPLETED),
            (SessionState.WAITING_INPUT, SessionState.COMPLETED),
        ]
        for from_state, to_state in invalid:
            assert not validate_session_transition(from_state, to_state), (
                f"{from_state} -> {to_state} should be invalid"
            )

    def test_terminal_states_have_no_transitions(self) -> None:
        for to_state in SessionState:
            assert not validate_session_transition(SessionState.COMPLETED, to_state)
            assert not validate_session_transition(SessionState.FAILED, to_state)


class TestStepType:
    def test_values(self) -> None:
        assert StepType.FINAL_ANSWER == "final_answer"
        assert StepType.TOOL_CALL == "tool_call"
        assert StepType.WAITING_INPUT == "waiting_input"
        assert StepType.ERROR == "error"


class TestErrorCategory:
    def test_llm_errors(self) -> None:
        llm_errors = [e for e in ErrorCategory if e.value.startswith("llm_")]
        assert len(llm_errors) == 5

    def test_tool_errors(self) -> None:
        tool_errors = [e for e in ErrorCategory if e.value.startswith("tool_")]
        assert len(tool_errors) == 3


class TestOtherEnums:
    def test_data_sensitivity_ordering(self) -> None:
        levels = [DataSensitivity.PUBLIC, DataSensitivity.INTERNAL, DataSensitivity.CONFIDENTIAL, DataSensitivity.RESTRICTED]
        assert len(levels) == 4

    def test_risk_level(self) -> None:
        assert RiskLevel.LOW == "low"
        assert RiskLevel.CRITICAL == "critical"

    def test_agent_event_type_count(self) -> None:
        # Phase 1 events + Phase 2 placeholders
        assert len(AgentEventType) >= 14
