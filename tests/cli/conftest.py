import pytest


@pytest.fixture(autouse=True)
def force_panel_rule_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep CLI-facing panel tests deterministic regardless of user shell env.
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.delenv("PANEL_AGENT_LLM_E2E", raising=False)
