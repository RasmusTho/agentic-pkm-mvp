import copy

from scripts.alpha_e2e import (
    _maybe_teardown,
    validate_runtime_progress,
    validate_status_invariants,
)


def _base_payloads():
    status = {
        "events_log": {"path": "/tmp/index-outbox.jsonl", "total_lines": 5},
        "worker_queue": {"mode": "file", "pending": 2, "processed_total": 3},
    }
    health = {"required_ok": True}
    return status, health


def test_invariants_require_required_ok() -> None:
    status, health = _base_payloads()
    health["required_ok"] = False
    errors = validate_status_invariants(status, health)
    assert errors
    assert "health.required_ok" in errors[0]


def test_invariants_db_mode_accepts_sqlalchemy_dsn() -> None:
    status, health = _base_payloads()
    status["worker_queue"] = {
        "mode": "db",
        "pending": 0,
        "processed_total": 0,
        "source_path": "postgresql+psycopg://app:app@db:5432/app",
    }
    errors = validate_status_invariants(status, health)
    assert not errors


def test_invariants_db_mode_does_not_require_events_log_math() -> None:
    status, health = _base_payloads()
    status["worker_queue"] = {"mode": "db", "pending": 0, "processed_total": 0, "source_path": "postgresql://app:app@db:5432/app"}
    status["events_log"]["total_lines"] = 42
    errors = validate_status_invariants(status, health)
    assert not errors


def test_invariants_db_mode_rejects_pending_from_events_log_sentinel() -> None:
    status, health = _base_payloads()
    status["worker_queue"] = {"mode": "db", "pending": 0, "processed_total": 0, "source_path": "postgresql://app:app@db:5432/app"}
    status["pending_from_events_log"] = True
    errors = validate_status_invariants(status, health)
    assert errors
    assert "pending_from_events_log" in errors[0]


def test_invariants_file_mode_pending_matches_events_log() -> None:
    status, health = _base_payloads()
    errors = validate_status_invariants(status, health)
    assert not errors


def test_invariants_file_mode_pending_mismatch_fails() -> None:
    status, health = _base_payloads()
    status = copy.deepcopy(status)
    status["worker_queue"]["pending"] = 4
    errors = validate_status_invariants(status, health)
    assert errors
    assert "worker_queue.pending" in errors[0]


def test_runtime_progress_requires_processed_increment() -> None:
    errors = validate_runtime_progress(
        baseline_processed=3,
        current_processed=3,
        processed_by_event={"promote.intent.created": 1},
        required_topic="promote.intent.created",
    )
    assert errors
    assert "processed_total" in errors[0]


def test_runtime_progress_requires_processing_topic() -> None:
    errors = validate_runtime_progress(
        baseline_processed=3,
        current_processed=4,
        processed_by_event={"other": 2},
        required_topic="promote.intent.created",
    )
    assert errors
    assert "did not process" in errors[-1]


def test_runtime_progress_accepts_processed_increment_and_topic() -> None:
    errors = validate_runtime_progress(
        baseline_processed=1,
        current_processed=2,
        processed_by_event={"promote.intent.created": 1},
        required_topic="promote.intent.created",
    )
    assert not errors


def test_maybe_teardown_runs_alpha_down_when_requested(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *, allow_fail: bool = False) -> None:
        calls.append(cmd)

    monkeypatch.setattr("scripts.alpha_e2e._run", fake_run)
    _maybe_teardown(True)
    assert calls == [["make", "alpha-down"]]


def test_maybe_teardown_is_noop_when_not_requested(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *, allow_fail: bool = False) -> None:
        calls.append(cmd)

    monkeypatch.setattr("scripts.alpha_e2e._run", fake_run)
    _maybe_teardown(False)
    assert calls == []
