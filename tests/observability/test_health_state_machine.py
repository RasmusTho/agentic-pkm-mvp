from concurrent.futures import ThreadPoolExecutor
from datetime import timezone, datetime, timedelta

from app.health_contract import HealthStateMachine
from app.settings.health_settings import HealthThresholds


def test_health_state_machine_hysteresis() -> None:
    machine = HealthStateMachine()
    thresholds = HealthThresholds.defaults()
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)  # noqa: UP017
    for i in range(3):
        state, reason, since = machine.update(
            16.0,
            thresholds=thresholds,
            now=base + timedelta(seconds=i),
        )
    assert state == "degraded"
    assert "idle" in reason
    for i in range(9):
        state, reason, since = machine.update(
            3.0,
            thresholds=thresholds,
            now=base + timedelta(seconds=10 + i),
        )
        if i < 9:
            assert state in {"recovery", "degraded"}
    state, reason, since = machine.update(
        3.0,
        thresholds=thresholds,
        now=base + timedelta(seconds=20),
    )
    assert state == "running"
    assert "recovered" in reason


def test_health_state_machine_concurrent_update_is_consistent() -> None:
    """update() is safe under concurrent callers (#3461 review finding).

    The /readyz and /status handlers now offload evaluate() to a threadpool, so
    two evaluate() calls can run state_machine.update() truly in parallel. update()
    does non-atomic read-modify-write on the counters and mutates transition_history
    (insert + slice); without the internal lock this races. Hammer it from many
    threads with alternating idle/active ages that force transitions, and assert no
    exception escapes and the machine's invariants hold.
    """
    machine = HealthStateMachine()
    thresholds = HealthThresholds.defaults()
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)  # noqa: UP017
    valid_states = {"boot", "running", "catch_up", "degraded", "recovery"}

    def _hammer(i: int) -> None:
        # Alternate well above degrade / well below recover to churn counters
        # and provoke transitions on every worker.
        age = 30.0 if i % 2 == 0 else 1.0
        machine.update(age, thresholds=thresholds, now=base + timedelta(seconds=i))

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(_hammer, range(400)))

    assert machine.state in valid_states
    assert machine.bad_counter >= 0
    assert machine.good_counter >= 0
    # insert(0)+slice under a race can corrupt or overgrow the bounded history.
    assert len(machine.transition_history) <= 20
    assert all(isinstance(entry, dict) for entry in machine.transition_history)
