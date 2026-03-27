"""LLMRouter — provider-based gateway dispatch.

See docs/architecture/04-llm-gateway.md Section 11.
"""

from __future__ import annotations

from src.core.enums import ErrorCategory
from src.core.errors import LLMError
from src.core.protocols import LLMGateway


class LLMRouter:
    """Route LLM requests to the correct gateway based on provider name.

    Example:
        router = LLMRouter({
            "anthropic": AnthropicGateway(...),
            "groq": OpenAICompatibleGateway(...),
            "lmstudio": OpenAICompatibleGateway(...),
        })
        gw = router.get_gateway("anthropic")
    """

    def __init__(self, gateways: dict[str, LLMGateway]) -> None:
        self._gateways = gateways

    def get_gateway(self, provider: str) -> LLMGateway:
        """Return the gateway for the given provider name.

        Raises LLMError with PROVIDER_NOT_FOUND category if unknown.
        """
        gw = self._gateways.get(provider)
        if gw is None:
            available = ", ".join(sorted(self._gateways.keys())) or "(none)"
            raise LLMError(
                f"Provider '{provider}' not found. Available: {available}",
                category=ErrorCategory.LLM_SERVER_ERROR,
                retryable=False,
            )
        return gw

    @property
    def providers(self) -> list[str]:
        """List of registered provider names."""
        return list(self._gateways.keys())
