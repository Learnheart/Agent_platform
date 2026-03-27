"""Guardrails Engine — orchestrates all guardrail checks.

Main entry point for the Executor to run guardrail checks.

See docs/architecture/07-guardrails.md.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.core.models import Message, Session, ToolCall
from src.guardrails.inbound.injection_detector import InjectionDetector
from src.guardrails.inbound.schema_validator import SchemaValidator
from src.guardrails.models import (
    GuardrailCheckResult,
    PermissionResult,
    ToolPermission,
)
from src.guardrails.policy.tool_permission import ToolPermissionEnforcer

logger = logging.getLogger(__name__)


class GuardrailsEngine:
    """Orchestrates inbound and policy guardrail checks."""

    def __init__(
        self,
        schema_validator: SchemaValidator | None = None,
        injection_detector: InjectionDetector | None = None,
        tool_permission_enforcer: ToolPermissionEnforcer | None = None,
    ) -> None:
        self._validator = schema_validator or SchemaValidator()
        self._injector = injection_detector or InjectionDetector()
        self._permissions = tool_permission_enforcer or ToolPermissionEnforcer()

    # ------------------------------------------------------------------
    # Inbound check — user input → LLM
    # ------------------------------------------------------------------

    def check_inbound(
        self,
        messages: list[Message],
        system_prompt: str = "",
    ) -> GuardrailCheckResult:
        """Run inbound guardrail pipeline on user messages.

        1. Schema validation (hard)
        2. Injection detection (soft)
        """
        start = time.monotonic()

        # 1. Schema validation (hard — fail-closed)
        validation = self._validator.validate(messages)
        if not validation.passed:
            return GuardrailCheckResult(
                passed=False,
                blocked=True,
                reason="; ".join(v.message for v in validation.violations),
                validation=validation,
                latency_ms=(time.monotonic() - start) * 1000,
            )

        # 2. Injection detection (soft — best-effort)
        injection = None
        user_messages = [m for m in messages if m.role == "user"]
        for msg in user_messages:
            result = self._injector.detect(msg.content, system_prompt)
            if result.is_injection:
                injection = result
                break

        if injection and injection.is_injection:
            return GuardrailCheckResult(
                passed=False,
                blocked=True,
                reason=f"Injection detected: {injection.strategy_triggered}",
                validation=validation,
                injection=injection,
                latency_ms=(time.monotonic() - start) * 1000,
            )

        return GuardrailCheckResult(
            passed=True,
            validation=validation,
            injection=injection,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    # ------------------------------------------------------------------
    # Tool call check — LLM → Tool
    # ------------------------------------------------------------------

    def check_tool_call(
        self,
        tool_call: ToolCall,
        session: Session,
        permissions: list[ToolPermission] | None = None,
    ) -> GuardrailCheckResult:
        """Run guardrail checks on a tool call.

        1. Tool permission check (hard)
        """
        start = time.monotonic()

        perm_result = self._permissions.check(
            tool_call,
            permissions or [],
        )

        match perm_result.status:
            case "DENY":
                return GuardrailCheckResult(
                    passed=False,
                    blocked=True,
                    reason=perm_result.reason,
                    permission=perm_result,
                    latency_ms=(time.monotonic() - start) * 1000,
                )
            case "REQUIRE_APPROVAL":
                return GuardrailCheckResult(
                    passed=False,
                    requires_approval=True,
                    reason=perm_result.reason,
                    permission=perm_result,
                    latency_ms=(time.monotonic() - start) * 1000,
                )
            case "ALLOW":
                return GuardrailCheckResult(
                    passed=True,
                    permission=perm_result,
                    latency_ms=(time.monotonic() - start) * 1000,
                )

        return GuardrailCheckResult(
            passed=True,
            latency_ms=(time.monotonic() - start) * 1000,
        )
