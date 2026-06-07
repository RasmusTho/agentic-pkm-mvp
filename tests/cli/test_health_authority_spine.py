from __future__ import annotations

import pytest

from app.cli.health import _check_authority_spine
from app.health_contract import DEFAULT_CONTRACT, reset_state_machine
from app.write_guard import DEFAULT_WRITE_GUARD


def test_health_authority_spine_does_not_evaluate_write_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_state_machine()
    DEFAULT_CONTRACT.state_machine.state = "running"

    def fail_snapshot() -> dict[str, object]:
        raise AssertionError("health rendering must not evaluate WriteGuard")

    def fail_evaluate() -> dict[str, object]:
        raise AssertionError("health rendering must not evaluate HealthContract")

    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", fail_snapshot)
    monkeypatch.setattr(DEFAULT_CONTRACT, "evaluate", fail_evaluate)

    payload = _check_authority_spine()

    assert payload["write_guard"] == "active"
    assert payload["authority_non_upgrade"] == "enforced"
    assert payload["provenance_required_for_mutations"] == "yes"
    assert payload["read_projection_isolation"] == "active"
    reset_state_machine()


def test_health_authority_spine_reports_blocked_from_cached_state() -> None:
    reset_state_machine()
    DEFAULT_CONTRACT.state_machine.state = "safe_mode"

    payload = _check_authority_spine()

    assert payload["write_guard"] == "blocked"
    reset_state_machine()
