"""Runtime-declared reconnecting posture on Companion picker payloads (#3385)."""

from __future__ import annotations

from pathlib import Path

import app.api.routes.companion as companion_module
from app.config.paths import VaultRootMisconfiguredError


def test_runtime_reconnecting_flag_emission(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Only a configured vault plus health's unavailable state earns the flag."""
    configured = tmp_path / "Niflheim"
    monkeypatch.setattr(
        companion_module.DEFAULT_CONTRACT,
        "evaluate",
        lambda: {"state": "unhealthy"},
    )

    reconnecting = companion_module._no_vault_selection_required_response(
        configured_vault_root=configured
    )
    assert reconnecting.runtime_reconnecting is True

    unbound = companion_module._no_vault_selection_required_response()
    assert unbound.runtime_reconnecting is False

    misconfigured = companion_module._vault_selection_required_response(
        VaultRootMisconfiguredError("VAULT_ROOT", configured)
    )
    assert misconfigured.runtime_reconnecting is False

    uninitialized = companion_module._uninitialized_selection_required_response(
        selected_vault_path=configured
    )
    assert uninitialized.runtime_reconnecting is False

    monkeypatch.setattr(
        companion_module.DEFAULT_CONTRACT,
        "evaluate",
        lambda: {"state": "running"},
    )
    healthy = companion_module._no_vault_selection_required_response(
        configured_vault_root=configured
    )
    assert healthy.runtime_reconnecting is False
