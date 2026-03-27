"""Schema Validator — input validation (Hard Guardrail).

Validates message format, content length, and encoding.
Sub-millisecond, stateless, fail-closed.

See docs/architecture/07-guardrails.md Section Inbound.
"""

from __future__ import annotations

import time

from src.core.models import Message
from src.guardrails.models import ValidationResult, Violation

# Control characters that are considered dangerous
_DANGEROUS_CHARS = set(range(0, 8)) | set(range(14, 32)) - {10, 13}  # Allow \n, \r

VALID_ROLES = {"user", "assistant", "system", "tool"}


class SchemaValidator:
    """Validates inbound messages against format and size constraints."""

    def __init__(self, max_input_tokens: int = 4096) -> None:
        self._max_input_tokens = max_input_tokens

    def validate(self, messages: list[Message]) -> ValidationResult:
        """Validate a list of messages."""
        start = time.monotonic()
        violations: list[Violation] = []

        for i, msg in enumerate(messages):
            self._check_role(msg, i, violations)
            self._check_content(msg, i, violations)
            self._check_encoding(msg, i, violations)

        latency = (time.monotonic() - start) * 1000
        return ValidationResult(
            passed=len(violations) == 0,
            violations=violations,
            latency_ms=latency,
        )

    def _check_role(self, msg: Message, idx: int, violations: list[Violation]) -> None:
        if msg.role not in VALID_ROLES:
            violations.append(Violation(
                field=f"messages[{idx}].role",
                message=f"Invalid role '{msg.role}'. Must be one of: {VALID_ROLES}",
                code="invalid_role",
            ))

    def _check_content(self, msg: Message, idx: int, violations: list[Violation]) -> None:
        if not msg.content and msg.role == "user":
            violations.append(Violation(
                field=f"messages[{idx}].content",
                message="User message content cannot be empty",
                code="empty_content",
            ))
            return

        # Rough token estimate: 1 token ≈ 4 chars
        estimated_tokens = len(msg.content) // 4
        if estimated_tokens > self._max_input_tokens:
            violations.append(Violation(
                field=f"messages[{idx}].content",
                message=f"Content exceeds max tokens ({estimated_tokens} > {self._max_input_tokens})",
                code="content_too_long",
            ))

    def _check_encoding(self, msg: Message, idx: int, violations: list[Violation]) -> None:
        for char in msg.content:
            if ord(char) in _DANGEROUS_CHARS:
                violations.append(Violation(
                    field=f"messages[{idx}].content",
                    message=f"Content contains dangerous control character (U+{ord(char):04X})",
                    code="dangerous_character",
                ))
                break
