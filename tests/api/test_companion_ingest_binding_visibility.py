"""#3119 regression — `_ingest_binding_state`'s own docstring commits to
degrading a heartbeat-check failure to a *visible* ``"unbound"`` state
("Never raises — a heartbeat read failure degrades to \"unbound\" rather than
breaking the workspace/capture response"). The except-block previously
returned ``state="unknown"`` instead, which `serve_dev_page.py`'s banner logic
(`ingest_unbound = state in ("unbound", "diverged")`) treats identically to
"no vault selected yet" — i.e. silently, with no banner. That silently
defeated the fix's own purpose in exactly the scenario it exists to cover:
the binding check itself failing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.api.routes.companion as companion_module


def test_ingest_binding_state_degrades_to_unbound_not_unknown_on_check_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*, selected_vault_path: str | None) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(companion_module, "ingest_binding_status", _raise)

    result = companion_module._ingest_binding_state(Path("/tmp/does-not-matter"))

    assert result.state == "unbound", (
        "a heartbeat-check failure must surface as the visible 'unbound' "
        "state (matching the function's own docstring), not the silent "
        "'unknown' state that the workspace banner treats identically to "
        "'no vault selected yet'"
    )
    assert result.bound is False
