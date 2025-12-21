from datetime import datetime, timedelta, timezone

from app.health_contract import HealthStateMachine


def test_health_state_machine_hysteresis() -> None:
    machine = HealthStateMachine()
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)  # noqa: UP017
    for i in range(3):
        state, reason, since = machine.update(16.0, now=base + timedelta(seconds=i))
    assert state == "degraded"
    assert "lag" in reason
    for i in range(9):
        state, reason, since = machine.update(3.0, now=base + timedelta(seconds=10 + i))
        if i < 9:
            assert state in {"recovery", "degraded"}
    state, reason, since = machine.update(3.0, now=base + timedelta(seconds=20))
    assert state == "running"
    assert "recovered" in reason
