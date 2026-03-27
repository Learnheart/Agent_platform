"""Tests for LLMRouter.

Tests Section 11 of docs/architecture/04-llm-gateway.md.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.core.errors import LLMError
from src.providers.llm.router import LLMRouter


@pytest.fixture()
def mock_gateways():
    return {
        "anthropic": MagicMock(),
        "groq": MagicMock(),
        "lmstudio": MagicMock(),
    }


@pytest.fixture()
def router(mock_gateways):
    return LLMRouter(mock_gateways)


class TestLLMRouter:
    def test_get_existing_gateway(self, router, mock_gateways):
        gw = router.get_gateway("anthropic")
        assert gw is mock_gateways["anthropic"]

    def test_get_another_gateway(self, router, mock_gateways):
        gw = router.get_gateway("groq")
        assert gw is mock_gateways["groq"]

    def test_unknown_provider_raises(self, router):
        with pytest.raises(LLMError, match="Provider 'unknown' not found"):
            router.get_gateway("unknown")

    def test_unknown_provider_not_retryable(self, router):
        with pytest.raises(LLMError) as exc_info:
            router.get_gateway("unknown")
        assert exc_info.value.retryable is False

    def test_error_lists_available_providers(self, router):
        with pytest.raises(LLMError, match="anthropic"):
            router.get_gateway("nope")

    def test_providers_property(self, router):
        providers = router.providers
        assert sorted(providers) == ["anthropic", "groq", "lmstudio"]

    def test_empty_router(self):
        router = LLMRouter({})
        with pytest.raises(LLMError, match="\\(none\\)"):
            router.get_gateway("any")

    def test_empty_providers(self):
        router = LLMRouter({})
        assert router.providers == []
