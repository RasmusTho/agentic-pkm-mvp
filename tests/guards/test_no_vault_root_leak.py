from __future__ import annotations

import os

from app.agents.panel_agent.wiring import get_default_action_wiring


def test_vault_root_is_not_set_in_tests() -> None:
    """
    Guardrail: tests must be hermetic. A user VAULT_ROOT (often iCloud) can cause
    filesystem calls to block and hang the suite.
    """
    assert os.getenv("VAULT_ROOT") in (None, ""), "VAULT_ROOT must not leak into tests"


def test_default_action_wiring_does_not_require_external_vault() -> None:
    """
    Guardrail: retrieving default action wiring should not require reading from an
    external vault path in tests. It must be resolvable from repo-bundled defaults.
    """
    wiring = get_default_action_wiring()
    assert isinstance(wiring, dict)
    assert wiring
