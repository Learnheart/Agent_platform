"""Budget Controller — 4-dimension budget enforcement.

Checks token, cost, step, and time budgets per session.
See docs/architecture/03-planning.md Section 2.7.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.core.models import BudgetCheck, BudgetCheckResult, ExecutionConfig, Session


class BudgetController:
    """Checks session budget across four dimensions.

    Returns a BudgetCheckResult indicating whether the session should
    continue, show a warning, or be terminated.
    """

    def check(self, session: Session, config: ExecutionConfig) -> BudgetCheckResult:
        """Check all budget dimensions and return aggregate result."""
        checks: list[BudgetCheck] = []

        # 1. Token budget
        if config.max_tokens_budget > 0:
            ratio = session.usage.total_tokens / config.max_tokens_budget
            checks.append(BudgetCheck(type="tokens", current=session.usage.total_tokens, limit=config.max_tokens_budget, ratio=ratio))

        # 2. Cost budget
        if config.max_cost_usd > 0:
            ratio = session.usage.total_cost_usd / config.max_cost_usd
            checks.append(BudgetCheck(type="cost", current=session.usage.total_cost_usd, limit=config.max_cost_usd, ratio=ratio))

        # 3. Step budget
        if config.max_steps > 0:
            ratio = session.step_index / config.max_steps
            checks.append(BudgetCheck(type="steps", current=session.step_index, limit=config.max_steps, ratio=ratio))

        # 4. Time budget
        if config.max_duration_seconds > 0:
            elapsed = (datetime.now(timezone.utc) - session.created_at).total_seconds()
            ratio = elapsed / config.max_duration_seconds
            checks.append(BudgetCheck(type="time", current=elapsed, limit=config.max_duration_seconds, ratio=ratio))

        if not checks:
            return BudgetCheckResult(checks=checks)

        max_ratio = max(c.ratio for c in checks)
        warning_parts: list[str] = []
        for c in checks:
            if c.ratio >= config.budget_warning_threshold:
                warning_parts.append(f"{c.type}: {c.current:.1f}/{c.limit:.1f} ({c.ratio:.0%})")

        warning_message = ""
        if warning_parts:
            warning_message = "Budget warning — " + ", ".join(warning_parts)

        return BudgetCheckResult(
            exhausted=max_ratio >= 1.0,
            warning=max_ratio >= config.budget_warning_threshold,
            critical=max_ratio >= config.budget_critical_threshold,
            warning_message=warning_message,
            checks=checks,
        )
