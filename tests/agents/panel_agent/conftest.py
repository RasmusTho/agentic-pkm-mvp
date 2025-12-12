import pytest


@pytest.fixture(autouse=True)
def force_panel_rule_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure unit/graph/runtime panel tests stay deterministic even if user env sets llm mode.
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.delenv("PANEL_AGENT_LLM_E2E", raising=False)
