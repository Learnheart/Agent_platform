"""Gateway configuration models.

See docs/architecture/04-llm-gateway.md Section 3.2 & 11.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.core.models import LLMConfig
from src.providers.llm.pricing import DEFAULT_PRICING, ModelPricing


class AnthropicGatewayConfig(BaseModel):
    """Configuration for AnthropicGateway."""

    api_key: str
    default_timeout: float = 120.0
    max_connections: int = 100
    max_keepalive: int = 20
    default_llm_config: LLMConfig = Field(default_factory=LLMConfig)
    pricing: dict[str, ModelPricing] = Field(default_factory=lambda: dict(DEFAULT_PRICING))


class OpenAICompatibleGatewayConfig(BaseModel):
    """Configuration for OpenAICompatibleGateway (Groq, LM Studio, etc.)."""

    base_url: str
    api_key: str = ""
    provider_name: str = "openai_compatible"
    default_timeout: float = 120.0
    max_connections: int = 100
    max_keepalive: int = 20
    default_llm_config: LLMConfig = Field(default_factory=LLMConfig)
    pricing: dict[str, ModelPricing] = Field(default_factory=dict)
