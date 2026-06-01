"""Workspace orientation MemoryCandidate intent seam tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
import app.api.routes.companion as companion_module
import app.panel.confirmation as confirm_module
from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.review_queue import MemoryCandidateReviewQueue
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
    monkeypatch.setenv(
        "MEMORY_INTENT_TRACE_PATH",
        str(tmp_path / "runtime" / "orientation-memory-intents.jsonl"),
    )
    monkeypatch.setattr(companion_module, "_configured_vault_name", lambda: "vault-test")
    clear_leave_point_trace()
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()
    yield
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _signals() -> OrientationSignals:
    now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    return OrientationSignals(
        events=EventCounters(
            watcher_runs_total=5,
            watcher_runs_24h=1,
            panel_runs_total=4,
            panel_runs_24h=1,
            promote_created_total=3,
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
            pending=0,
            processed_total=7,
            source_path="/tmp/raw-worker-path",
        ),
    )


def _review_queue_with_candidate() -> MemoryCandidateReviewQueue:
    queue = MemoryCandidateReviewQueue()
    queue.enqueue(
        MemoryCandidate(
            title="Private candidate title",
            memory_type=MemoryType.PREFERENCE_MEMORY,
            source_refs=["session:private-source"],
            derived_from="conversation:private",
            generated_by="companion_agent",
            content="Sensitive candidate content must stay out of orientation.",
            inferred=True,
        )
    )
    return queue


def _evaluation(*, qualifying: bool, related_only: bool = False) -> ResurfacingEvaluation:
    signals = [
        ResurfacingSignal(
            name="pending_promotions",
            value=2,
            source="/tmp/raw-events-path",
        )
    ]
    if qualifying:
        signals.append(
            ResurfacingSignal(
                name="promote_created_total" if related_only else "worker_queue_pending",
                value=3,
                source="/tmp/raw-events-path" if related_only else "/tmp/raw-worker-path",
            )
        )
    return ResurfacingEvaluation(
        generated_at="2026-05-31T12:00:00Z",
        status_summary="test",
        candidates=[
            ResurfacingCandidate(
                candidate_id="resurface-pending-promotions",
                label="Review a bounded runtime signal",
                why_now=ResurfacingWhyNow(
                    explanation="Multiple runtime signals indicate a review handoff may be useful.",
                    signals=signals,
                ),
            )
        ],
    )


def _orientation(client: TestClient):
    return client.get("/api/companion/orientation")


def test_pending_count_without_content(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _review_queue_with_candidate()
    monkeypatch.setattr(companion_module, "_orientation_memory_review_queue", lambda: queue)
    monkeypatch.setattr(companion_module, "get_orientation_signals", _signals)
    monkeypatch.setattr(
        companion_module,
        "evaluate_resurfacing_candidates",
        lambda signals=None: _evaluation(qualifying=False),
    )

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["memory"]["pending_candidate_count"] == 1
    payload = json.dumps(data)
    assert "Private candidate title" not in payload
    assert "Sensitive candidate content" not in payload
    assert "session:private-source" not in payload


def test_intent_emitted_no_write(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = MemoryCandidateReviewQueue()
    monkeypatch.setattr(companion_module, "_orientation_memory_review_queue", lambda: queue)
    monkeypatch.setattr(companion_module, "get_orientation_signals", _signals)
    monkeypatch.setattr(
        companion_module,
        "evaluate_resurfacing_candidates",
        lambda signals=None: _evaluation(qualifying=True),
    )

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["memory"]["pending_candidate_count"] == 0
    assert [entry.candidate_id for entry in queue.pending()] == []
    assert queue.recallable_for_working_context() == []
    assert getattr(confirm_module._idempotency_store, "_cache", {}) == {}
    assert len(data["mutation_intents"]) == 1
    intent = data["mutation_intents"][0]
    assert intent["kind"] == "MemoryCandidate"
    assert intent["target_queue"] == "agent_memory.review_queue"
    assert intent["handoff_hint"] == "panel_governance_review"
    assert intent["authority_role"] == "reference"
    assert intent["source_ref"]["ref"] == "status.events"
    assert len(intent["threshold_signals"]) == 2


def test_related_promotion_counters_do_not_emit_intent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = MemoryCandidateReviewQueue()
    monkeypatch.setattr(companion_module, "_orientation_memory_review_queue", lambda: queue)
    monkeypatch.setattr(companion_module, "get_orientation_signals", _signals)
    monkeypatch.setattr(
        companion_module,
        "evaluate_resurfacing_candidates",
        lambda signals=None: _evaluation(qualifying=True, related_only=True),
    )

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["mutation_intents"] == []


def test_intent_trace_recorded(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "runtime" / "orientation-memory-intents.jsonl"
    monkeypatch.setenv("MEMORY_INTENT_TRACE_PATH", str(trace_path))
    queue = MemoryCandidateReviewQueue()
    monkeypatch.setattr(companion_module, "_orientation_memory_review_queue", lambda: queue)
    monkeypatch.setattr(companion_module, "get_orientation_signals", _signals)
    monkeypatch.setattr(
        companion_module,
        "evaluate_resurfacing_candidates",
        lambda signals=None: _evaluation(qualifying=True),
    )

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    intent = data["mutation_intents"][0]
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    record = records[0]
    assert record["event_type"] == "orientation.memory_candidate_intent.emitted.v1"
    assert record["trace_id"] == data["meta"]["trace_id"]
    assert record["intent_id"] == intent["intent_id"]
    assert record["target_queue"] == "agent_memory.review_queue"
    assert record["source_ref"] == intent["source_ref"]
    assert record["threshold_signals"] == intent["threshold_signals"]
    assert record["emitted_at"]
    record_payload = json.dumps(record)
    assert "Sensitive candidate content" not in record_payload
    assert "note_body" not in record_payload
    assert "chat_transcript" not in record_payload
    assert getattr(confirm_module._idempotency_store, "_cache", {}) == {}


def test_no_hidden_accumulation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = MemoryCandidateReviewQueue()
    monkeypatch.setattr(companion_module, "_orientation_memory_review_queue", lambda: queue)
    monkeypatch.setattr(companion_module, "get_orientation_signals", _signals)
    monkeypatch.setattr(
        companion_module,
        "evaluate_resurfacing_candidates",
        lambda signals=None: _evaluation(qualifying=True),
    )

    first = _orientation(client)
    second = _orientation(client)

    assert first.status_code == 200
    assert second.status_code == 200
    first_data = first.json()
    second_data = second.json()
    assert first_data["memory"]["pending_candidate_count"] == 0
    assert second_data["memory"]["pending_candidate_count"] == 0
    assert len(first_data["mutation_intents"]) == 1
    assert len(second_data["mutation_intents"]) == 1
    assert first_data["mutation_intents"][0]["intent_id"] == second_data["mutation_intents"][0]["intent_id"]
    assert [entry.candidate_id for entry in queue.pending()] == []
    assert queue.decided() == []
    assert getattr(confirm_module._idempotency_store, "_cache", {}) == {}
