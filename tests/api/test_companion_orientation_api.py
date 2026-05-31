"""Companion workspace orientation endpoint tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
import app.api.routes.companion as companion_module
import app.panel.confirmation as confirm_module
from app.api.app import app
from app.observability.status_model import EventCounters, IngestionStatus, WorkerQueueStatus
from app.observability.status_service import OrientationSignals
from app.orientation.leave_point_cursor import clear_leave_point_trace
from app.resurfacing.runtime import (
    ResurfacingCandidate,
    ResurfacingEvaluation,
    ResurfacingSignal,
    ResurfacingWhyNow,
)


@pytest.fixture(autouse=True)
def _clear_runtime_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_CHANNEL", "test")
    monkeypatch.setenv("LEAVE_POINT_TRACE_DB", str(tmp_path / "runtime" / "leave-point.sqlite3"))
    monkeypatch.setattr(companion_module, "_configured_vault_name", lambda: "vault-test")
    clear_leave_point_trace()
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()
    clear_leave_point_trace()
    yield
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _signals(*, pending: int = 2, pending_promotions: int = 3) -> OrientationSignals:
    now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    return OrientationSignals(
        events=EventCounters(
            watcher_runs_total=5,
            watcher_runs_24h=1,
            panel_runs_total=4,
            panel_runs_24h=1,
            promote_created_total=pending_promotions,
            promote_created_24h=1,
            promotion_executed_total=1,
            promotion_executed_24h=1,
            source_path="/tmp/raw-events-path",
        ),
        ingestion=IngestionStatus(
            last_run_at=now,
            last_run_ok=True,
            total_scanned=8,
            total_ingested=6,
        ),
        worker_queue=WorkerQueueStatus(
            mode="memory",
            pending=pending,
            processed_total=7,
            source_path="/tmp/raw-worker-path",
        ),
    )


def _fake_evaluation(count: int) -> ResurfacingEvaluation:
    candidates: list[ResurfacingCandidate] = []
    for index in range(count):
        candidates.append(
            ResurfacingCandidate(
                candidate_id=f"candidate-{index}",
                label=f"Candidate {index}",
                why_now=ResurfacingWhyNow(
                    explanation=f"why now {index}",
                    signals=[
                        ResurfacingSignal(
                            name="worker_queue_pending",
                            value=index,
                            source="/tmp/raw-worker-path",
                        )
                    ],
                ),
            )
        )
    return ResurfacingEvaluation(
        generated_at="2026-05-31T12:00:00Z",
        status_summary="test",
        candidates=candidates,
    )


def _orientation(client: TestClient):
    return client.get("/api/companion/orientation")


def test_orientation_snapshot_without_note(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "get_orientation_signals", lambda: _signals())

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["scope"]["kind"] == "workspace"
    assert data["scope"]["channel"] == "test"
    assert data["meta"]["contract_version"] == "workspace_orientation.v1"
    assert data["leave_point"]["status"] == "absent"
    assert data["leave_point"]["authority_role"] == "derived_runtime_projection"
    assert data["mutation_intents"] == []
    assert "artifact" not in data
    assert "body" not in data


def test_scope_freshness_and_bounded_candidates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "get_orientation_signals", lambda: _signals())
    monkeypatch.setattr(
        companion_module,
        "evaluate_resurfacing_candidates",
        lambda signals=None: _fake_evaluation(9),
    )

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    caps = data["meta"]["caps"]
    assert data["scope"]["kind"] == "workspace"
    assert data["meta"]["freshness"] == "fresh"
    assert data["meta"]["as_of"]
    assert data["meta"]["stale_after"]
    assert caps["resurface_candidates"] == 5
    assert len(data["resurface"]["candidates"]) == caps["resurface_candidates"]


def test_orientation_is_read_only(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "get_orientation_signals", lambda: _signals())
    write_note = MagicMock(side_effect=AssertionError("orientation must not write vault notes"))
    write_guard = MagicMock(side_effect=AssertionError("orientation must not evaluate WriteGuard"))
    monkeypatch.setattr(companion_module, "write_note_from_absolute", write_note)
    monkeypatch.setattr(companion_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", write_guard)

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["guards"]["read_only"] is True
    assert data["mutation_intents"] == []
    assert write_note.call_count == 0
    assert write_guard.call_count == 0
    assert canvas_module._sessions == {}
    assert getattr(confirm_module._idempotency_store, "_cache", {}) == {}


def test_items_carry_provenance(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "get_orientation_signals", lambda: _signals())

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["leave_point"]["authority_role"]
    assert "kind" in data["leave_point"]["source_ref"]
    assert "trace_id" in data["leave_point"]["source_ref"]
    items = [
        *data["open_loops"],
        *data["notable_changes"],
        *data["resurface"]["candidates"],
        data["governance"],
        data["guards"],
    ]
    assert items
    for item in items:
        assert item["authority_role"]
        assert item["source_ref"]["kind"]
        assert item["source_ref"]["ref"]
        assert not item["source_ref"]["ref"].startswith("/")


def test_degraded_when_source_unavailable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "get_orientation_signals", lambda: _signals())

    def _fail_resurfacing(signals=None):
        raise RuntimeError("resurfacing unavailable")

    monkeypatch.setattr(companion_module, "evaluate_resurfacing_candidates", _fail_resurfacing)

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["freshness"] == "partial"
    assert "resurfacing_source_unavailable" in data["meta"]["degraded_reasons"]
    assert data["guards"]["degraded"] is True
    assert "resurfacing_source_unavailable" in data["guards"]["reasons"]
    assert data["resurface"]["candidates"] == []


def test_runtime_unavailable_returns_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_signals():
        raise RuntimeError("status unavailable")

    monkeypatch.setattr(companion_module, "get_orientation_signals", _fail_signals)

    resp = _orientation(client)

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["error"] == "runtime_unavailable"
    assert detail["contract_version"] == "workspace_orientation.v1"
