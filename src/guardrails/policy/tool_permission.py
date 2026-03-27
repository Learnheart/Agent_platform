"""Tool Permission Enforcer — permission checks for tool calls (Hard Guardrail).

Evaluates tool calls against agent permission rules.

See docs/architecture/07-guardrails.md Section Policy.
"""

from __future__ import annotations

import fnmatch
from typing import Any

from src.core.models import ToolCall
from src.guardrails.models import PermissionResult, ToolPermission


class ToolPermissionEnforcer:
    """Enforces tool call permissions based on agent configuration.

    Evaluation order:
    1. Is tool in agent's allowed list? → DENY if no
    2. Does it require approval? → REQUIRE_APPROVAL if yes
    3. → ALLOW
    """

    def check(
        self,
        tool_call: ToolCall,
        permissions: list[ToolPermission],
        session_context: dict[str, Any] | None = None,
    ) -> PermissionResult:
        """Check if a tool call is permitted."""
        if not permissions:
            # No permissions configured → allow all (open by default in Phase 1)
            return PermissionResult(status="ALLOW")

        # Find matching permission
        matched = self._find_matching_permission(tool_call.name, permissions)

        if matched is None:
            return PermissionResult(
                status="DENY",
                reason=f"Tool '{tool_call.name}' is not in the allowed tool list",
            )

        # Check constraints
        constraints = matched.constraints

        # Check denied parameters
        if constraints.denied_parameters:
            for param_name in constraints.denied_parameters:
                if param_name in tool_call.arguments:
                    return PermissionResult(
                        status="DENY",
                        reason=f"Parameter '{param_name}' is not allowed for tool '{tool_call.name}'",
                    )

        # Check if HITL approval is required
        if constraints.requires_approval:
            return PermissionResult(
                status="REQUIRE_APPROVAL",
                reason=f"Tool '{tool_call.name}' requires human approval",
            )

        return PermissionResult(status="ALLOW")

    def _find_matching_permission(
        self, tool_name: str, permissions: list[ToolPermission]
    ) -> ToolPermission | None:
        """Find the first matching permission for a tool name.

        Supports glob patterns (e.g., "mcp:database:*").
        """
        for perm in permissions:
            if fnmatch.fnmatch(tool_name, perm.tool_pattern):
                return perm
            # Also check without namespace prefix
            if ":" in tool_name:
                short_name = tool_name.split(":")[-1]
                if fnmatch.fnmatch(short_name, perm.tool_pattern):
                    return perm
        return None
