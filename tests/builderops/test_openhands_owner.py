"""Native control-profile setup is model-free and reconciles before creating."""

import uuid

import pytest

from app.builderops import openhands_delivery as delivery
from app.builderops import openhands_owner as owner


def test_control_profile_is_created_once_selected_and_read_back(tmp_path, monkeypatch):
    entry = tmp_path / "bin/openhands"
    entry.parent.mkdir()
    entry.touch()
    monkeypatch.setattr(delivery, "_server_key", lambda *args: "private")
    profile = None
    selected = None
    calls = []
    ident = str(uuid.uuid4())

    def request(port, key, method, path, payload=None):
        nonlocal profile, selected
        calls.append((method, path))
        if path == "/agent-profiles/builder-control" and method == "GET":
            return (404, {}) if profile is None else (200, {"profile": profile})
        if path == "/agent-profiles/builder-control" and method == "POST":
            profile = {**payload, "id": ident}
            return 201, {}
        if path == "/settings":
            return 200, {"active_agent_profile_id": selected}
        if path == f"/agent-profiles/{ident}/activate":
            selected = ident
            return 200, {}
        pytest.fail(f"Unexpected profile request: {method} {path}")

    monkeypatch.setattr(delivery, "_http", request)
    owner.ensure_profile(tmp_path, tmp_path, {"port": 8123})
    owner.ensure_profile(tmp_path, tmp_path, {"port": 8123})
    assert calls.count(("POST", "/agent-profiles/builder-control")) == 1
    assert calls.count(("POST", f"/agent-profiles/{ident}/activate")) == 1
    assert profile["acp_server"] == "custom" and profile["acp_model"] is None
    assert profile["secret_refs"] == [] and profile["mcp_server_refs"] == []


def test_control_profile_refuses_an_existing_different_profile(tmp_path, monkeypatch):
    entry = tmp_path / "bin/openhands"
    entry.parent.mkdir()
    entry.touch()
    monkeypatch.setattr(delivery, "_server_key", lambda *args: "private")
    monkeypatch.setattr(delivery, "_http", lambda *args: (200, {"profile": {"agent_kind": "openhands"}}))
    with pytest.raises(delivery.DeliveryError, match="does not match"):
        owner.ensure_profile(tmp_path, tmp_path, {"port": 8123})
