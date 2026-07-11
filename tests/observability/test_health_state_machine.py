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


def test_update_runs_under_the_instance_lock() -> None:
    """update()/reset() must run their mutation under the instance lock (#3461).

    Deterministic guard for the actual regression we care about — someone removing
    the lock now that /readyz and /status offload evaluate() to a threadpool and can
    run update() in parallel. A concurrency stress test cannot catch that: under
    CPython's GIL the individual ops are atomic and the invariants hold with or
    without the lock (this was a review finding on the first cut of this test). So
    instead swap in a lock proxy and assert the guard is on the code path: if the
    `with self._lock:` is dropped from update(), __enter__ is never called and this
    fails.
    """
    machine = HealthStateMachine()
    thresholds = HealthThresholds.defaults()
    real_lock = machine._lock
    events: list[str] = []

    class _TrackingLock:
        def __enter__(self):
            events.append("enter")
            return real_lock.__enter__()

        def __exit__(self, *exc):
            events.append("exit")
            return real_lock.__exit__(*exc)

    machine._lock = _TrackingLock()
    # Force a transition so the full mutation path (including _record_transition,
    # which must NOT re-acquire) runs under the lock.
    machine.update(
        30.0, thresholds=thresholds, now=datetime(2025, 1, 1, tzinfo=timezone.utc)  # noqa: UP017
    )
    assert events == ["enter", "exit"], (
        "update() did not run its mutation under self._lock"
    )

    events.clear()
    machine.reset()
    assert events == ["enter", "exit"], "reset() did not run under self._lock"


def test_health_state_machine_concurrent_update_smoke() -> None:
    """Load smoke: update() does not raise or corrupt state under concurrent callers.

    Not a strict race guard (see test_update_runs_under_the_instance_lock for that —
    the GIL makes this pass with or without the lock). This just exercises the real
    threadpool-parallel path once so a gross regression (an exception escaping,
    unbounded history growth) surfaces.
    """
    machine = HealthStateMachine()
    thresholds = HealthThresholds.defaults()
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)  # noqa: UP017
    valid_states = {"boot", "running", "catch_up", "degraded", "recovery"}

    def _hammer(i: int) -> None:
        age = 30.0 if i % 2 == 0 else 1.0
        machine.update(age, thresholds=thresholds, now=base + timedelta(seconds=i))

    with ThreadPoolExecutor(max_workers=16) as pool:
        # list() re-raises any worker exception.
        list(pool.map(_hammer, range(400)))

    assert machine.state in valid_states
    assert len(machine.transition_history) <= 20
