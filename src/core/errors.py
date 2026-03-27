"""Error hierarchy for the Agent Platform.

Canonical definitions from docs/architecture/01-data-models.md Section 9.
"""

from src.core.enums import ErrorCategory


class PlatformError(Exception):
    """Base error for all platform errors."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 500,
        category: ErrorCategory | None = None,
        details: dict | None = None,
        retryable: bool = False,
        trace_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.category = category
        self.details = details or {}
        self.retryable = retryable
        self.trace_id = trace_id


# --- LLM Errors ---


class LLMError(PlatformError):
    """Error from LLM provider calls."""

    def __init__(
        self,
        message: str,
        *,
        category: ErrorCategory = ErrorCategory.LLM_SERVER_ERROR,
        provider: str = "",
        model: str = "",
        retryable: bool = True,
        **kwargs: object,
    ) -> None:
        super().__init__(
            code="LLM_PROVIDER_ERROR",
            message=message,
            status_code=502,
            category=category,
            details={"provider": provider, "model": model},
            retryable=retryable,
            **kwargs,  # type: ignore[arg-type]
        )


class LLMTimeoutError(LLMError):
    """LLM call timed out."""

    def __init__(self, message: str = "LLM call timed out", **kwargs: object) -> None:
        super().__init__(message, category=ErrorCategory.LLM_TIMEOUT, retryable=True, **kwargs)


class LLMRateLimitError(LLMError):
    """LLM rate limit exceeded."""

    def __init__(self, message: str = "LLM rate limit exceeded", **kwargs: object) -> None:
        super().__init__(message, category=ErrorCategory.LLM_RATE_LIMIT, retryable=True, **kwargs)


# --- Tool Errors ---


class ToolError(PlatformError):
    """Error from tool execution."""

    def __init__(
        self,
        message: str,
        *,
        category: ErrorCategory = ErrorCategory.TOOL_EXECUTION_ERROR,
        tool_name: str = "",
        retryable: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(
            code="TOOL_ERROR",
            message=message,
            status_code=500,
            category=category,
            details={"tool_name": tool_name},
            retryable=retryable,
            **kwargs,  # type: ignore[arg-type]
        )


class ToolTimeoutError(ToolError):
    """Tool call timed out."""

    def __init__(self, tool_name: str, timeout_ms: int, **kwargs: object) -> None:
        super().__init__(
            f"Tool '{tool_name}' timed out after {timeout_ms}ms",
            category=ErrorCategory.TOOL_TIMEOUT,
            tool_name=tool_name,
            **kwargs,
        )


# --- Guardrail Errors ---


class GuardrailError(PlatformError):
    """Error from guardrail checks."""

    def __init__(
        self,
        message: str,
        *,
        check_name: str = "",
        **kwargs: object,
    ) -> None:
        super().__init__(
            code="GUARDRAIL_BLOCKED",
            message=message,
            status_code=422,
            details={"check_name": check_name},
            **kwargs,  # type: ignore[arg-type]
        )


# --- Budget Errors ---


class BudgetExhaustedError(PlatformError):
    """Budget limit exceeded."""

    def __init__(
        self,
        budget_type: str,
        current: float,
        limit: float,
    ) -> None:
        super().__init__(
            code="BUDGET_EXCEEDED",
            message=f"Budget exhausted: {budget_type} ({current:.2f}/{limit:.2f})",
            status_code=429,
            category=ErrorCategory.BUDGET_EXCEEDED,
            details={"budget_type": budget_type, "current": current, "limit": limit},
        )


# --- Auth Errors ---


class AuthError(PlatformError):
    """Authentication/authorization error."""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(
            code="UNAUTHORIZED" if status_code == 401 else "FORBIDDEN",
            message=message,
            status_code=status_code,
        )


# --- State Errors ---


class InvalidStateTransitionError(PlatformError):
    """Invalid session state transition."""

    def __init__(self, from_state: str, to_state: str) -> None:
        super().__init__(
            code="INVALID_STATE_TRANSITION",
            message=f"Invalid state transition: {from_state} -> {to_state}",
            status_code=409,
            details={"from_state": from_state, "to_state": to_state},
        )


# --- Not Found Errors ---


class NotFoundError(PlatformError):
    """Resource not found."""

    def __init__(self, resource_type: str, resource_id: str) -> None:
        code = f"{resource_type.upper()}_NOT_FOUND"
        super().__init__(
            code=code,
            message=f"{resource_type.capitalize()} with ID '{resource_id}' not found",
            status_code=404,
        )
