"""LLM pricing tables and cost calculation.

See docs/architecture/04-llm-gateway.md Section 5.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.core.models import TokenUsage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPricing:
    """Pricing per model (USD per 1M tokens)."""

    input_per_million: float
    output_per_million: float
    cached_input_per_million: float | None = None


# Hardcoded pricing table — update on deploy when prices change.
DEFAULT_PRICING: dict[str, ModelPricing] = {
    "claude-sonnet-4-5-20250514": ModelPricing(
        input_per_million=3.0,
        output_per_million=15.0,
        cached_input_per_million=0.3,
    ),
    "claude-haiku-4-5-20251001": ModelPricing(
        input_per_million=0.80,
        output_per_million=4.0,
        cached_input_per_million=0.08,
    ),
}


def calculate_cost(
    usage: TokenUsage,
    model: str,
    pricing: dict[str, ModelPricing] | None = None,
) -> float:
    """Calculate cost in USD from token usage and model pricing.

    Args:
        usage: Token usage from LLM response.
        model: Model name to look up pricing.
        pricing: Custom pricing table. Uses DEFAULT_PRICING if None.

    Returns:
        Cost in USD, rounded to 6 decimal places.
    """
    table = pricing or DEFAULT_PRICING
    model_pricing = table.get(model)
    if model_pricing is None:
        logger.warning("No pricing found for model '%s', returning 0.0", model)
        return 0.0

    input_cost = (usage.prompt_tokens / 1_000_000) * model_pricing.input_per_million
    output_cost = (usage.completion_tokens / 1_000_000) * model_pricing.output_per_million

    # Apply cache discount
    if usage.cached_tokens and model_pricing.cached_input_per_million is not None:
        cached_saving = (usage.cached_tokens / 1_000_000) * (
            model_pricing.input_per_million - model_pricing.cached_input_per_million
        )
        input_cost -= cached_saving

    return round(input_cost + output_cost, 6)
