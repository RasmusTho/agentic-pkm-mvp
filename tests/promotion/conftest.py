import pytest


@pytest.fixture(autouse=True)
def force_panel_rule_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # Promotion payload tests rely on deterministic panel runtime behaviour.
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.delenv("PANEL_AGENT_LLM_E2E", raising=False)
