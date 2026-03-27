"""Core enumerations for the Agent Platform.

Canonical definitions from docs/architecture/01-data-models.md Section 7.
"""

from enum import Enum


class SessionState(str, Enum):
    """Session lifecycle states. See 01-data-models Section 8 for state machine."""

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"


# Valid state transitions: {from_state: {to_states}}
SESSION_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.CREATED: {SessionState.RUNNING},
    SessionState.RUNNING: {
        SessionState.COMPLETED,
        SessionState.PAUSED,
        SessionState.WAITING_INPUT,
        SessionState.FAILED,
    },
    SessionState.PAUSED: {SessionState.RUNNING, SessionState.FAILED},
    SessionState.WAITING_INPUT: {SessionState.RUNNING, SessionState.FAILED},
    SessionState.COMPLETED: set(),  # terminal
    SessionState.FAILED: set(),  # terminal
}


def validate_session_transition(from_state: SessionState, to_state: SessionState) -> bool:
    """Check if a session state transition is valid."""
    return to_state in SESSION_TRANSITIONS.get(from_state, set())


class StepType(str, Enum):
    """Result type of a single execution step."""

    FINAL_ANSWER = "final_answer"
    TOOL_CALL = "tool_call"
    WAITING_INPUT = "waiting_input"
    ERROR = "error"


class ErrorCategory(str, Enum):
    """Error classification for retry logic and observability."""

    LLM_RATE_LIMIT = "llm_rate_limit"
    LLM_SERVER_ERROR = "llm_server_error"
    LLM_CONTENT_REFUSAL = "llm_content_refusal"
    LLM_MALFORMED_RESPONSE = "llm_malformed_response"
    LLM_TIMEOUT = "llm_timeout"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_AUTH_FAILURE = "tool_auth_failure"
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    CHECKPOINT_WRITE_FAIL = "checkpoint_write_fail"
    BUDGET_EXCEEDED = "budget_exceeded"
    EXECUTOR_CRASH = "executor_crash"


class DataSensitivity(str, Enum):
    """Data classification levels for governance."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class RiskLevel(str, Enum):
    """Tool risk assessment levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AgentEventType(str, Enum):
    """Event types emitted by the execution engine."""

    SESSION_CREATED = "session_created"
    SESSION_COMPLETED = "session_completed"
    STEP_START = "step_start"
    LLM_CALL_START = "llm_call_start"
    LLM_CALL_END = "llm_call_end"
    THOUGHT = "thought"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    GUARDRAIL_CHECK = "guardrail_check"
    APPROVAL_REQUESTED = "approval_requested"
    CHECKPOINT = "checkpoint"
    BUDGET_WARNING = "budget_warning"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"
    # Phase 2
    PLAN_CREATED = "plan_created"
    PLAN_STEP_END = "plan_step_end"
    REPLAN = "replan"


class AuditCategory(str, Enum):
    """Audit event categories for governance."""

    AGENT_MANAGEMENT = "agent_management"
    SESSION_LIFECYCLE = "session_lifecycle"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    GUARDRAIL_CHECK = "guardrail_check"
    AUTH_EVENT = "auth_event"
    MEMORY_ACCESS = "memory_access"
    DATA_EXPORT = "data_export"
    CONFIG_CHANGE = "config_change"
    RETENTION_ACTION = "retention_action"
