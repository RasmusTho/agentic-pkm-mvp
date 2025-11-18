from __future__ import annotations

import pytest

from app.orchestrator.agents import AgentPermissionError, resolve_agent_config, validate_agent_permissions
from app.settings.agents import AgentConfig


def _config(**kwargs) -> AgentConfig:
    defaults = {
        "agent_id": "ingest-agent",
        "agent_type": "planner",
        "enabled": True,
        "flows": ["ingest"],
        "allowed_events": ["ingest.object.created"],
    }
    defaults.update(kwargs)
    return AgentConfig(**defaults)


def test_resolve_agent_config_handles_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config()
    monkeypatch.setattr("app.orchestrator.agents.load_agent_configs", lambda: {cfg.agent_id: cfg})
    resolved = resolve_agent_config("agent:ingest-agent", flow_id="ingest", event_type="ingest.object.created")
    assert resolved is cfg
    assert resolve_agent_config("agent:unknown") is None


def test_validate_agent_permissions_requires_enabled() -> None:
    cfg = _config(enabled=False)
    with pytest.raises(AgentPermissionError):
        validate_agent_permissions(cfg, flow_id="ingest", event_type="ingest.object.created")


def test_validate_agent_permissions_checks_flows_and_events() -> None:
    cfg = _config()
    # Matching flow/event passes
    validate_agent_permissions(cfg, flow_id="ingest", event_type="ingest.object.created")
    # Flow mismatch
    with pytest.raises(AgentPermissionError):
        validate_agent_permissions(cfg, flow_id="qa", event_type="ingest.object.created")
    # Event mismatch
    with pytest.raises(AgentPermissionError):
        validate_agent_permissions(cfg, flow_id="ingest", event_type="ask.query.received")


def test_validate_agent_permissions_allows_missing_filters() -> None:
    cfg = _config(flows=[], allowed_events=[])
    validate_agent_permissions(cfg, flow_id=None, event_type=None)
