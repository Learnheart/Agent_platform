"""Shared test fixtures."""

import pytest


@pytest.fixture
def tenant_id() -> str:
    return "tenant_test_001"


@pytest.fixture
def agent_id() -> str:
    return "agent_test_001"


@pytest.fixture
def session_id() -> str:
    return "session_test_001"
