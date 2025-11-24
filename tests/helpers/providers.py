from __future__ import annotations

import pytest


@pytest.fixture
def mock_reasoning_env(monkeypatch: pytest.MonkeyPatch):
    """
    Force mock reasoning/LLM providers for deterministic runs.
    """
    monkeypatch.setenv("REASONING_PROVIDER", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    yield


@pytest.fixture
def mock_planner_env(monkeypatch: pytest.MonkeyPatch):
    """
    Force mock planner/LLM providers for deterministic runs.
    """
    monkeypatch.setenv("PLANNER_PROVIDER", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    yield
