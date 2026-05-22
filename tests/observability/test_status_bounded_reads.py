"""Regression tests for #1206: /api/status must not perform unbounded file reads."""
from __future__ import annotations

import json
from pathlib import Path

from app.observability.status_service import (
    _STATUS_MAX_OUTBOX_LINES,
    _STATUS_TAIL_BYTES,
    _count_events,
    _count_outbox_events,
    _delivery_sla_status,
    _get_write_guard_status,
    _iter_tail_lines,
    _last_watcher_run_record,
    _read_last_json_record,
    _status_context_dimensions,
)


def _write_lines(path: Path, line: str, count: int) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for _ in range(count):
            fh.write(line + "\n")


def test_iter_tail_lines_caps_bytes(tmp_path: Path) -> None:
    path = tmp_path / "big.jsonl"
    payload = json.dumps({"event": "watcher.run", "timestamp": "2024-01-01T00:00:00Z"})
    # Write enough lines to exceed the 8 MB tail cap.
    line_count = (_STATUS_TAIL_BYTES // len(payload)) + 1000
    _write_lines(path, payload, line_count)
    assert path.stat().st_size > _STATUS_TAIL_BYTES

    lines = _iter_tail_lines(path)
    # The helper reads at most _STATUS_TAIL_BYTES; lines must fit within that.
    total = sum(len(line) + 1 for line in lines)
    assert total <= _STATUS_TAIL_BYTES + len(payload)


def test_iter_tail_lines_missing_file(tmp_path: Path) -> None:
    assert _iter_tail_lines(tmp_path / "missing.jsonl") == []


def test_count_outbox_events_capped(tmp_path: Path) -> None:
    path = tmp_path / "outbox.jsonl"
    _write_lines(path, "{}", _STATUS_MAX_OUTBOX_LINES + 500)
    count, truncated = _count_outbox_events(path)
    assert count == _STATUS_MAX_OUTBOX_LINES
    assert truncated is True


def test_count_outbox_events_under_cap(tmp_path: Path) -> None:
    path = tmp_path / "outbox.jsonl"
    _write_lines(path, "{}", 10)
    count, truncated = _count_outbox_events(path)
    assert count == 10
    assert truncated is False


def test_outbox_lag_hides_pending_when_truncated(tmp_path: Path, monkeypatch) -> None:
    """Regression for #1209 review: capped counts must not yield wrong pending=0."""
    import json as _json
    outbox = tmp_path / "outbox.jsonl"
    _write_lines(outbox, _json.dumps({"event": "x"}), _STATUS_MAX_OUTBOX_LINES + 100)
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(
        _json.dumps({"processed_total": _STATUS_MAX_OUTBOX_LINES + 5000, "outbox_path": str(outbox)}),
        encoding="utf-8",
    )

    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr(
        "app.observability.status_service.resolve_worker_heartbeat_path",
        lambda: heartbeat,
    )

    from app.observability.status_service import _get_outbox_lag

    lag = _get_outbox_lag()
    # processed_total >> capped count, so naive subtraction would yield 0.
    # The truncated signal must short-circuit that derivation.
    assert lag.pending_estimate is None
    assert lag.outbox_events is None


def test_count_events_does_not_read_entire_file(tmp_path: Path) -> None:
    path = tmp_path / "outbox.jsonl"
    payload = json.dumps({"event": "watcher.run", "timestamp": "2024-01-01T00:00:00Z"})
    line_count = (_STATUS_TAIL_BYTES // len(payload)) + 2000
    _write_lines(path, payload, line_count)

    counters = _count_events(path)
    # We tail-read at most ~8 MB worth of lines; the counter must reflect that bound.
    assert counters.watcher_runs_total < line_count


def test_delivery_sla_does_not_read_entire_file(tmp_path: Path) -> None:
    path = tmp_path / "outbox.jsonl"
    payload = json.dumps({"event": "orchestrator.step.error", "timestamp": "2024-01-01T00:00:00Z"})
    line_count = (_STATUS_TAIL_BYTES // len(payload)) + 1000
    _write_lines(path, payload, line_count)

    result = _delivery_sla_status(path)
    # Status is bounded; the field exists and counts were not loaded for every line.
    assert isinstance(result.outcomes_total, dict)


def test_read_last_json_record_uses_tail(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for i in range(10):
            fh.write(json.dumps({"i": i}) + "\n")
    record = _read_last_json_record(path)
    assert record == {"i": 9}


def test_last_watcher_run_record_uses_tail(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "watcher.run", "timestamp": "2024-01-01T00:00:00Z", "n": 1}) + "\n")
        fh.write(json.dumps({"event": "other"}) + "\n")
        fh.write(json.dumps({"event": "watcher.run.completed", "timestamp": "2024-01-02T00:00:00Z", "n": 2}) + "\n")
    record = _last_watcher_run_record(path)
    assert record is not None
    assert record.get("n") == 2


def test_status_context_dimensions_uses_tail(tmp_path: Path) -> None:
    path = tmp_path / "outbox.jsonl"
    payload = json.dumps(
        {"context_dimensions": {"scope": "team", "sphere_memberships": ["a"]}}
    )
    line_count = (_STATUS_TAIL_BYTES // len(payload)) + 200
    _write_lines(path, payload, line_count)

    result = _status_context_dimensions(path)
    assert result is not None
    assert result.scope == "team"


def test_write_guard_status_does_not_call_evaluate(monkeypatch) -> None:
    """The status request path must read cached state, never call evaluate()."""
    from app.health_contract import DEFAULT_CONTRACT

    def _boom():
        raise AssertionError("DEFAULT_CONTRACT.evaluate() must not run on status path")

    monkeypatch.setattr(DEFAULT_CONTRACT, "evaluate", _boom)
    # Should not raise — _get_write_guard_status reads state machine directly.
    status = _get_write_guard_status()
    assert status is not None


def test_diagnose_index_cached(monkeypatch) -> None:
    from app.index import doctor

    doctor.reset_diagnose_cache()
    call_count = {"n": 0}

    def fake_get_client(*args, **kwargs):
        call_count["n"] += 1

        class _Identity:
            provider = "fake"
            model = "fake"
            dim = 1
            normalize = False

        class _Client:
            identity = _Identity()

        return _Client()

    monkeypatch.setattr(doctor, "get_embeddings_client", fake_get_client)

    class _VectorIndex:
        def get_identity(self):
            return None

    monkeypatch.setattr(doctor, "get_vector_index", lambda: _VectorIndex())

    first = doctor.diagnose_index(use_cache=True)
    second = doctor.diagnose_index(use_cache=True)
    assert call_count["n"] == 1
    assert first is second

    doctor.reset_diagnose_cache()
    doctor.diagnose_index(use_cache=True)
    assert call_count["n"] == 2
