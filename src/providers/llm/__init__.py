"""LLM Gateway — multi-provider LLM abstraction layer.

See docs/architecture/04-llm-gateway.md.
"""

from src.providers.llm.anthropic_gateway import AnthropicGateway
from src.providers.llm.config import AnthropicGatewayConfig, OpenAICompatibleGatewayConfig
from src.providers.llm.openai_compat_gateway import OpenAICompatibleGateway
from src.providers.llm.pricing import DEFAULT_PRICING, ModelPricing, calculate_cost
from src.providers.llm.router import LLMRouter

__all__ = [
    "AnthropicGateway",
    "AnthropicGatewayConfig",
    "OpenAICompatibleGateway",
    "OpenAICompatibleGatewayConfig",
    "LLMRouter",
    "ModelPricing",
    "DEFAULT_PRICING",
    "calculate_cost",
]
