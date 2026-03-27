"""Tests for LLM pricing and cost calculation.

Tests Section 5 of docs/architecture/04-llm-gateway.md.
"""

import pytest

from src.core.models import TokenUsage
from src.providers.llm.pricing import DEFAULT_PRICING, ModelPricing, calculate_cost


class TestModelPricing:
    def test_default_pricing_has_sonnet(self):
        assert "claude-sonnet-4-5-20250514" in DEFAULT_PRICING

    def test_default_pricing_has_haiku(self):
        assert "claude-haiku-4-5-20251001" in DEFAULT_PRICING

    def test_pricing_values_sonnet(self):
        p = DEFAULT_PRICING["claude-sonnet-4-5-20250514"]
        assert p.input_per_million == 3.0
        assert p.output_per_million == 15.0
        assert p.cached_input_per_million == 0.3

    def test_pricing_values_haiku(self):
        p = DEFAULT_PRICING["claude-haiku-4-5-20251001"]
        assert p.input_per_million == 0.80
        assert p.output_per_million == 4.0
        assert p.cached_input_per_million == 0.08

    def test_model_pricing_frozen(self):
        p = ModelPricing(input_per_million=1.0, output_per_million=2.0)
        with pytest.raises(AttributeError):
            p.input_per_million = 5.0  # type: ignore[misc]


class TestCalculateCost:
    def test_basic_cost_sonnet(self):
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = calculate_cost(usage, "claude-sonnet-4-5-20250514")
        # input: 1000/1M * 3.0 = 0.003
        # output: 500/1M * 15.0 = 0.0075
        assert cost == pytest.approx(0.0105, abs=1e-6)

    def test_basic_cost_haiku(self):
        usage = TokenUsage(prompt_tokens=10000, completion_tokens=2000, total_tokens=12000)
        cost = calculate_cost(usage, "claude-haiku-4-5-20251001")
        # input: 10000/1M * 0.80 = 0.008
        # output: 2000/1M * 4.0 = 0.008
        assert cost == pytest.approx(0.016, abs=1e-6)

    def test_cost_with_cache(self):
        usage = TokenUsage(
            prompt_tokens=10000, completion_tokens=1000, total_tokens=11000, cached_tokens=8000
        )
        cost = calculate_cost(usage, "claude-sonnet-4-5-20250514")
        # input: 10000/1M * 3.0 = 0.03
        # output: 1000/1M * 15.0 = 0.015
        # cached saving: 8000/1M * (3.0 - 0.3) = 0.0216
        # total: 0.03 - 0.0216 + 0.015 = 0.0234
        assert cost == pytest.approx(0.0234, abs=1e-6)

    def test_unknown_model_returns_zero(self):
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = calculate_cost(usage, "unknown-model")
        assert cost == 0.0

    def test_zero_tokens(self):
        usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        cost = calculate_cost(usage, "claude-sonnet-4-5-20250514")
        assert cost == 0.0

    def test_custom_pricing_table(self):
        custom = {"my-model": ModelPricing(input_per_million=1.0, output_per_million=2.0)}
        usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000, total_tokens=2_000_000)
        cost = calculate_cost(usage, "my-model", pricing=custom)
        assert cost == pytest.approx(3.0, abs=1e-6)

    def test_no_cached_input_pricing(self):
        """Model without cached pricing — cached_tokens ignored."""
        custom = {"no-cache": ModelPricing(input_per_million=1.0, output_per_million=2.0)}
        usage = TokenUsage(
            prompt_tokens=1000, completion_tokens=500, total_tokens=1500, cached_tokens=800
        )
        cost = calculate_cost(usage, "no-cache", pricing=custom)
        # No cache discount applied
        # input: 1000/1M * 1.0 = 0.001
        # output: 500/1M * 2.0 = 0.001
        assert cost == pytest.approx(0.002, abs=1e-6)

    def test_cost_rounded_to_6_decimals(self):
        usage = TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        cost = calculate_cost(usage, "claude-sonnet-4-5-20250514")
        # Very small cost — verify rounding
        decimal_places = len(str(cost).split(".")[-1]) if "." in str(cost) else 0
        assert decimal_places <= 6
