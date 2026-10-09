from __future__ import annotations

import pytest


@pytest.fixture
def mock_product_api_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the deterministic mock route in functional API tests that call Product models."""

    monkeypatch.setenv("LLM_FORCE_PROVIDER", "mock")
