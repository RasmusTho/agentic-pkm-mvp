from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def isolate_non_pg_memory_backend(request: pytest.FixtureRequest) -> Iterator[None]:
    """Keep a prior case's memory corpus and embedding identity out of API requests."""

    if request.node.get_closest_marker("pg") is not None:
        yield
        return

    from app.stores import reset_memory_store_backend

    reset_memory_store_backend()
    try:
        yield
    finally:
        reset_memory_store_backend()


@pytest.fixture
def mock_product_api_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the deterministic mock route in functional API tests that call Product models."""

    monkeypatch.setenv("LLM_FORCE_PROVIDER", "mock")
