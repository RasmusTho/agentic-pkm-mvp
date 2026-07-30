import json
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest
from anyio import to_thread
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import health_contract as health_contract_route
from app.health_contract import HealthContract, HealthStateMachine
from app.settings.health_settings import HealthThresholds


def _mock_snapshot(state: str, reason: str) -> dict[str, object]:
    return {
        "state": state,
        "reason": reason,
        "since_ts": "2025-01-01T00:00:00+00:00",
        "outbox_count": 1,
        "outbox_recent_age_s": 0.1,
        "store_object_count": 1,
        "bootstrap_state": "active",
        "bootstrap_reason": "objects or outbox events detected",
        "embedding_identity": {
            "backend": "mock",
            "expected_identity": None,
            "stored_identity": None,
        },
        "index_doctor_status": "pass",
        "events_doctor_status": "pass",
        "errors_last_10m": 0,
        "settings_status": "ok",
        "settings_source": {
            "path": "/fake/vault/System/Settings/health.md",
            "mtime": "2025-01-01T00:00:00+00:00",
            "sha256": "deadbeef",
        },
        "settings_errors": [],
        "thresholds": {
            "outbox_degrade_oldest_age_s": 15.0,
            "outbox_recover_oldest_age_s": 5.0,
            "degrade_samples": 3,
            "recover_samples": 10,
        },
        "writes_allowed": True,
        "write_guard_reason": None,
    }


def test_health_endpoints_ready(monkeypatch) -> None:
    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.routes.health_contract.DEFAULT_CONTRACT.evaluate",
        lambda: _mock_snapshot("running", "ok"),
    )
    resp_live = client.get("/healthz")
    assert resp_live.status_code == 200
    assert resp_live.json() == {"ok": True}

    resp_ready = client.get("/readyz")
    assert resp_ready.status_code == 200
    assert resp_ready.json()["state"] == "running"
    assert resp_ready.json()["class"] == "active"

    resp_status = client.get("/status")
    assert resp_status.status_code == 200
    payload = resp_status.json()
    assert payload["state"] == "running"
    assert payload["settings_status"] == "ok"
    assert payload["writes_allowed"] is True


def test_readyz_unhealthy(monkeypatch) -> None:
    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.routes.health_contract.DEFAULT_CONTRACT.evaluate",
        lambda: _mock_snapshot("boot", "starting"),
    )
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["detail"]["state"] == "boot"
    assert resp.json()["detail"]["class"] == "active"


def test_readyz_status_do_not_block_event_loop(monkeypatch) -> None:
    def slow_evaluate() -> dict[str, object]:
        time.sleep(0.2)
        return _mock_snapshot("running", "ok")

    monkeypatch.setattr(health_contract_route.DEFAULT_CONTRACT, "evaluate", slow_evaluate)

    async def assert_nonblocking(endpoint) -> None:
        request_task = asyncio.create_task(endpoint())
        await asyncio.sleep(0.01)
        assert not request_task.done()
        await request_task

    asyncio.run(assert_nonblocking(health_contract_route.readyz))
    asyncio.run(assert_nonblocking(health_contract_route.health_status))


def test_shared_health_contract_evaluation_is_serialized(monkeypatch) -> None:
    machine = HealthStateMachine()
    thresholds = HealthThresholds.defaults()
    first_update_started = threading.Event()
    release_first_update = threading.Event()
    second_lock_attempted = threading.Event()
    counter_lock = threading.Lock()
    active_updates = 0
    maximum_active_updates = 0
    lock_attempts = 0

    class RecordingLock:
        def __init__(self) -> None:
            self._lock = threading.Lock()

        def __enter__(self) -> None:
            nonlocal lock_attempts
            with counter_lock:
                lock_attempts += 1
                if lock_attempts == 2:
                    second_lock_attempted.set()
            self._lock.acquire()

        def __exit__(self, *exc_info) -> None:
            self._lock.release()

    original_update = machine._update_unlocked

    def synchronized_update(age, thresholds, *, now=None):
        nonlocal active_updates, maximum_active_updates
        with counter_lock:
            active_updates += 1
            maximum_active_updates = max(maximum_active_updates, active_updates)
        try:
            if not first_update_started.is_set():
                first_update_started.set()
                assert release_first_update.wait(timeout=1)
            return original_update(age, thresholds, now=now)
        finally:
            with counter_lock:
                active_updates -= 1

    monkeypatch.setattr(machine, "_lock", RecordingLock())
    monkeypatch.setattr(machine, "_update_unlocked", synchronized_update)
    monkeypatch.setattr(health_contract_route.DEFAULT_CONTRACT, "state_machine", machine)

    def evaluate_state_machine() -> dict[str, object]:
        state, reason, _ = machine.update(0, thresholds)
        return _mock_snapshot(state, reason)

    monkeypatch.setattr(
        health_contract_route.DEFAULT_CONTRACT,
        "_evaluate",
        evaluate_state_machine,
    )

    async def evaluate_both_routes() -> None:
        readyz_task = asyncio.create_task(health_contract_route.readyz())
        while not first_update_started.is_set():
            await asyncio.sleep(0)
        status_task = asyncio.create_task(health_contract_route.health_status())
        while not second_lock_attempted.is_set():
            await asyncio.sleep(0)

        assert maximum_active_updates == 1
        release_first_update.set()
        await asyncio.gather(readyz_task, status_task)

    asyncio.run(asyncio.wait_for(evaluate_both_routes(), timeout=1))

    assert lock_attempts == 2
    assert maximum_active_updates == 1


def test_blocked_health_diagnostic_does_not_queue_direct_consumers_on_transition_lock(
    monkeypatch,
) -> None:
    first_evaluation_started = threading.Event()
    release_first_evaluation = threading.Event()
    call_lock = threading.Lock()
    evaluation_count = 0
    expected_evaluation_count = 0

    def first_call_blocks() -> dict[str, object]:
        nonlocal evaluation_count
        with call_lock:
            evaluation_count += 1
            current_call = evaluation_count
        if current_call == 1:
            first_evaluation_started.set()
            assert release_first_evaluation.wait(timeout=1)
        return _mock_snapshot("running", "ok")

    monkeypatch.setattr(
        health_contract_route.DEFAULT_CONTRACT,
        "_evaluate",
        first_call_blocks,
    )

    async def assert_shared_pool_remains_available() -> None:
        nonlocal expected_evaluation_count
        limiter = to_thread.current_default_thread_limiter()
        expected_evaluation_count = limiter.total_tokens
        active_route = asyncio.create_task(health_contract_route.health_status())
        while not first_evaluation_started.is_set():
            await asyncio.sleep(0)

        direct_consumers = [
            asyncio.create_task(
                to_thread.run_sync(health_contract_route.DEFAULT_CONTRACT.evaluate)
            )
            for _ in range(limiter.total_tokens - 1)
        ]
        await asyncio.sleep(0)

        assert await asyncio.wait_for(
            to_thread.run_sync(lambda: "unrelated"),
            timeout=0.5,
        ) == "unrelated"
        release_first_evaluation.set()
        await active_route
        await asyncio.gather(*direct_consumers)

    asyncio.run(asyncio.wait_for(assert_shared_pool_remains_available(), timeout=1))

    assert evaluation_count == expected_evaluation_count


def test_stale_health_evaluation_cannot_overwrite_newer_transition(
    monkeypatch,
) -> None:
    machine = HealthStateMachine()
    first_diagnostic_started = threading.Event()
    release_first_diagnostic = threading.Event()
    call_lock = threading.Lock()
    age_calls = 0
    now_values = iter(
        [
            datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        ]
    )
    contract = HealthContract(
        state_machine=machine,
        now_fn=lambda: next(now_values),
        vault_root_fn=lambda: None,
    )

    def overtaking_age(*_args) -> float:
        nonlocal age_calls
        with call_lock:
            age_calls += 1
            current_call = age_calls
        if current_call == 1:
            first_diagnostic_started.set()
            assert release_first_diagnostic.wait(timeout=1)
            return 30.0
        return 0.0

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr(contract, "_compute_age", overtaking_age)
    monkeypatch.setattr(
        "app.health_contract.diagnose_index",
        lambda: {
            "backend": "memory",
            "expected_identity": None,
            "stored_identity": None,
            "issues": [],
            "warnings": [],
        },
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        older_evaluation = executor.submit(contract.evaluate)
        assert first_diagnostic_started.wait(timeout=1)
        newer_evaluation = executor.submit(contract.evaluate)
        newer_snapshot = newer_evaluation.result(timeout=1)
        release_first_diagnostic.set()
        older_snapshot = older_evaluation.result(timeout=1)

    assert newer_snapshot["state"] == "running"
    assert older_snapshot["state"] == "running"
    state, _, since_ts, transition_history = machine.snapshot()
    assert state == "running"
    assert since_ts == "2025-01-01T00:00:01+00:00"
    assert [entry["state"] for entry in transition_history] == ["running"]
    assert transition_history[0]["since_ts"] == since_ts


def test_stale_healthy_evaluation_preserves_newer_dependency_failure(
    monkeypatch,
) -> None:
    first_diagnostic_started = threading.Event()
    release_first_diagnostic = threading.Event()
    call_lock = threading.Lock()
    dependency_checks = 0
    contract = HealthContract(vault_root_fn=lambda: None)

    def dependency_reason(*_args) -> str | None:
        nonlocal dependency_checks
        with call_lock:
            dependency_checks += 1
            current_call = dependency_checks
        if current_call == 1:
            return None
        return "postgres unavailable"

    def blocked_object_count() -> tuple[int, str | None]:
        first_diagnostic_started.set()
        assert release_first_diagnostic.wait(timeout=1)
        return 0, None

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr(contract, "_db_dependency_down_reason", dependency_reason)
    monkeypatch.setattr(contract, "_count_objects", blocked_object_count)
    monkeypatch.setattr(
        "app.health_contract.diagnose_index",
        lambda: {
            "backend": "memory",
            "expected_identity": None,
            "stored_identity": None,
            "issues": [],
            "warnings": [],
        },
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        older_healthy_evaluation = executor.submit(contract.evaluate)
        assert first_diagnostic_started.wait(timeout=1)
        newer_db_down_evaluation = executor.submit(contract.evaluate)
        newer_snapshot = newer_db_down_evaluation.result(timeout=1)
        release_first_diagnostic.set()
        older_snapshot = older_healthy_evaluation.result(timeout=1)

    assert newer_snapshot["state"] == "unhealthy"
    assert newer_snapshot["writes_allowed"] is False
    assert older_snapshot["state"] == "unhealthy"
    assert older_snapshot["reason"] == newer_snapshot["reason"]
    assert older_snapshot["writes_allowed"] is False


def test_health_state_machine_lock_releases_after_exception(monkeypatch) -> None:
    machine = HealthStateMachine()
    thresholds = HealthThresholds.defaults()
    original_update = machine._update_unlocked
    call_count = 0

    def fail_then_succeed(age, thresholds, *, now=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("health transition failed")
        return original_update(age, thresholds, now=now)

    monkeypatch.setattr(machine, "_update_unlocked", fail_then_succeed)

    with pytest.raises(RuntimeError, match="health transition failed"):
        machine.update(0, thresholds)
    assert machine.update(0, thresholds)[0] == "running"


def test_health_state_machine_instances_do_not_share_transition_lock(monkeypatch) -> None:
    first_machine = HealthStateMachine()
    second_machine = HealthStateMachine()
    thresholds = HealthThresholds.defaults()
    update_barrier = threading.Barrier(2, timeout=1)
    counter_lock = threading.Lock()
    active_updates = 0
    maximum_active_updates = 0

    def wrap_update(machine):
        original_update = machine._update_unlocked

        def synchronized_update(age, thresholds, *, now=None):
            nonlocal active_updates, maximum_active_updates
            with counter_lock:
                active_updates += 1
                maximum_active_updates = max(maximum_active_updates, active_updates)
            try:
                update_barrier.wait()
                return original_update(age, thresholds, now=now)
            finally:
                with counter_lock:
                    active_updates -= 1

        return synchronized_update

    monkeypatch.setattr(first_machine, "_update_unlocked", wrap_update(first_machine))
    monkeypatch.setattr(second_machine, "_update_unlocked", wrap_update(second_machine))

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_update = executor.submit(first_machine.update, 0, thresholds)
        second_update = executor.submit(second_machine.update, 0, thresholds)

        assert first_update.result(timeout=1)[0] == "running"
        assert second_update.result(timeout=1)[0] == "running"

    assert maximum_active_updates == 2


def test_health_contract_degrades_on_stale_outbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outbox_path = tmp_path / "index-outbox.jsonl"
    old_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    record = {
        "event": "watcher.run",
        "timestamp": old_ts.isoformat().replace("+00:00", "Z"),
        "trace_id": "trace-health",
        "source": "test",
        "payload": {},
    }
    outbox_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.outbox.events.INDEX_OUTBOX_PATH", outbox_path, raising=False)
    monkeypatch.setattr("app.events.outbox.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    now = datetime(2025, 1, 1, 0, 0, 30, tzinfo=timezone.utc)
    contract = HealthContract(
        state_machine=HealthStateMachine(),
        now_fn=lambda: now,
        vault_root_fn=lambda: tmp_path,
    )
    snapshot = None
    for _ in range(3):
        snapshot = contract.evaluate()

    assert snapshot is not None
    assert snapshot["state"] == "degraded"
    assert "outbox idle" in snapshot["reason"]
    assert any("events-doctor" in action for action in snapshot["suggested_actions"])
