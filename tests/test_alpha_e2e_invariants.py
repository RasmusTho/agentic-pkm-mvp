import copy

from scripts.alpha_e2e import validate_runtime_progress, validate_status_invariants


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


def test_runtime_progress_skips_pending_when_none() -> None:
    errors = validate_runtime_progress(
        baseline_pending=None,
        current_pending=None,
        baseline_processed=3,
        current_processed=4,
        processed_by_event={"ingest.vault.changed": 1},
        required_topic="ingest.vault.changed",
    )
    assert not errors


def test_runtime_progress_reports_missing_topic() -> None:
    errors = validate_runtime_progress(
        baseline_pending=1,
        current_pending=2,
        baseline_processed=3,
        current_processed=4,
        processed_by_event={"other": 1},
        required_topic="ingest.vault.changed",
    )
    assert errors
    assert "did not process" in errors[-1]
