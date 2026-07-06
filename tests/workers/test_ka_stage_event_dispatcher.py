"""KA-07 (#3107): stage-event-dispatcher consumes the KA-06 stage.* outbox topics.

KA-06 (#2801) emits `knowledge_acquisition.stage.completed` and
`knowledge_acquisition.stage.dead_lettered` onto the existing DB outbox with
deterministic idempotency keys, but nothing consumed them -- a grep of
`app/orchestrator/` and `app/runtime/` showed zero handlers. This module drives
the real production dispatch entrypoint (`app.workers.outbox_worker._dispatch_topic`)
for both topics end-to-end, proving:

- AC1: the dispatcher has a route for both topics; a handled `completed` event
  at the `candidate` stage runs its bounded downstream action (a durable
  `knowledge_acquisition.candidate.ready_for_triage` observability signal).
- AC2: duplicate delivery does not duplicate the effect (the JSONL audit sink
  gains exactly one line, not two, across two dispatches of the identical
  event).
- AC3: a `dead_lettered` event is surfaced (a durable
  `knowledge_acquisition.stage.dead_letter_surfaced` signal), item-scoped
  (never raises), without blocking a sibling item's dispatch.
- AC4 (no regression to existing topics): covered by running the shared
  `tests/workers/test_handler_idempotency_harness.py` suite, which still
  passes with the two new topics added to its dynamically-enumerated
  `TOPIC_FIXTURES` table (see that module).

This module does NOT re-implement idempotency-key handling or a parallel
delivery path: it drives the real `_dispatch_topic` entrypoint and asserts on
the same JSONL audit sink (`INDEX_OUTBOX_PATH`) the existing dead-letter
handlers (`_dead_letter_outbox_message`) already use.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.events.models import new_event
from app.events.types import (
    KNOWLEDGE_ACQUISITION_STAGE_COMPLETED,
    KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED,
)
from app.workers import outbox_worker

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _memory_backend_and_dedup_reset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    outbox_path = tmp_path / "outbox_audit.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    outbox_worker._KA_CONSUMER_SIGNAL_DEDUP.clear()
    yield
    outbox_worker._KA_CONSUMER_SIGNAL_DEDUP.clear()


def _outbox_path() -> Path:
    return outbox_worker._outbox_audit_path()


def _read_signals(event_type: str) -> list[dict]:
    path = _outbox_path()
    if not path.exists():
        return []
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in records if r.get("event") == event_type]


def _dispatch(topic: str, payload: dict, *, row_id: str = "row-1", trace_id: str = "test-trace") -> None:
    envelope = new_event(event_type=topic, payload=dict(payload))
    message = {
        "id": row_id,
        "topic": topic,
        "payload": payload,
        "event": envelope,
        "timestamp": envelope.created_at,
    }
    outbox_worker._dispatch_topic(
        topic,
        payload,
        trace_id=trace_id,
        message=message,
        event_id=outbox_worker._event_id_from_message(message),
    )


# ---------------------------------------------------------------------------
# AC1: dispatch route exists; a `candidate`-stage completion runs its bounded
# downstream action.
# ---------------------------------------------------------------------------


def test_candidate_stage_completed_emits_ready_for_triage_signal() -> None:
    payload = {
        "stage": "candidate",
        "stage_version": 1,
        "content_identity": "sha256:test-candidate-identity",
        "artifact_path": "Sources/test-candidate.md",
    }
    _dispatch(KNOWLEDGE_ACQUISITION_STAGE_COMPLETED, payload)

    signals = _read_signals(outbox_worker.KA_CANDIDATE_READY_FOR_TRIAGE)
    assert len(signals) == 1, f"expected exactly one ready-for-triage signal, got {signals!r}"
    assert signals[0]["payload"]["content_identity"] == "sha256:test-candidate-identity"
    assert signals[0]["payload"]["artifact_path"] == "Sources/test-candidate.md"


@pytest.mark.parametrize("stage", ["normalize", "extracted"])
def test_non_terminal_stage_completed_is_traced_but_bounded_noop(stage: str) -> None:
    """Only the `candidate` stage has a concrete action. `normalize`/extractor
    stage completions dispatch cleanly (no exception) but emit no
    ready-for-triage signal -- there is no candidate yet to mark ready."""
    payload = {
        "stage": stage,
        "stage_version": 1,
        "content_identity": f"sha256:test-{stage}-identity",
    }
    if stage == "extracted":
        payload["extractor_id"] = "summary"

    _dispatch(KNOWLEDGE_ACQUISITION_STAGE_COMPLETED, payload)

    assert _read_signals(outbox_worker.KA_CANDIDATE_READY_FOR_TRIAGE) == []


def test_completed_event_missing_content_identity_is_a_safe_noop() -> None:
    """A malformed payload must not crash dispatch (worker never-crash posture)."""
    payload = {"stage": "candidate", "stage_version": 1}
    _dispatch(KNOWLEDGE_ACQUISITION_STAGE_COMPLETED, payload)
    assert _read_signals(outbox_worker.KA_CANDIDATE_READY_FOR_TRIAGE) == []


# ---------------------------------------------------------------------------
# AC2: duplicate delivery does not duplicate the effect.
# ---------------------------------------------------------------------------


def test_duplicate_delivery_of_completed_event_does_not_duplicate_signal() -> None:
    payload = {
        "stage": "candidate",
        "stage_version": 1,
        "content_identity": "sha256:test-dup-candidate",
        "artifact_path": "Sources/test-dup.md",
    }
    _dispatch(KNOWLEDGE_ACQUISITION_STAGE_COMPLETED, payload, row_id="row-1")
    _dispatch(KNOWLEDGE_ACQUISITION_STAGE_COMPLETED, payload, row_id="row-1")

    signals = _read_signals(outbox_worker.KA_CANDIDATE_READY_FOR_TRIAGE)
    assert len(signals) == 1, (
        f"redelivering the identical stage.completed event must dedup to a single "
        f"ready-for-triage signal, got {len(signals)}: {signals!r}"
    )


def test_duplicate_delivery_of_dead_letter_does_not_duplicate_signal() -> None:
    payload = {
        "stage": "extracted",
        "stage_version": 2,
        "content_identity": "sha256:test-dup-dead-letter",
        "extractor_id": "summary",
        "reason": "extraction_failed",
        "error": "boom",
    }
    _dispatch(KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED, payload, row_id="row-2")
    _dispatch(KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED, payload, row_id="row-2")

    signals = _read_signals(outbox_worker.KA_STAGE_DEAD_LETTER_SURFACED)
    assert len(signals) == 1, (
        f"redelivering the identical dead-lettered event must dedup to a single "
        f"surfaced signal, got {len(signals)}: {signals!r}"
    )


def test_stage_version_bump_is_a_distinct_signal_not_swallowed() -> None:
    """A stage-version bump derives a distinct idempotency key (per KERNEL-02's
    producer contract) -- a genuinely new lineage event must not be swallowed
    against an old row."""
    base_payload = {
        "stage": "candidate",
        "content_identity": "sha256:test-version-bump",
    }
    _dispatch(KNOWLEDGE_ACQUISITION_STAGE_COMPLETED, {**base_payload, "stage_version": 1}, row_id="row-3")
    _dispatch(KNOWLEDGE_ACQUISITION_STAGE_COMPLETED, {**base_payload, "stage_version": 2}, row_id="row-4")

    signals = _read_signals(outbox_worker.KA_CANDIDATE_READY_FOR_TRIAGE)
    assert len(signals) == 2, (
        f"a stage_version bump must emit a distinct signal, got {len(signals)}: {signals!r}"
    )


# ---------------------------------------------------------------------------
# AC3: dead-lettered events are surfaced, item-scoped, without blocking
# sibling items.
# ---------------------------------------------------------------------------


def test_dead_lettered_event_is_surfaced() -> None:
    payload = {
        "stage": "extracted",
        "stage_version": 3,
        "content_identity": "sha256:test-surfaced-identity",
        "extractor_id": "summary",
        "reason": "extraction_failed",
        "error": "model timeout",
    }
    _dispatch(KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED, payload)

    signals = _read_signals(outbox_worker.KA_STAGE_DEAD_LETTER_SURFACED)
    assert len(signals) == 1
    assert signals[0]["payload"]["content_identity"] == "sha256:test-surfaced-identity"
    assert signals[0]["payload"]["reason"] == "extraction_failed"
    assert signals[0]["payload"]["error"] == "model timeout"
    assert signals[0]["payload"]["extractor_id"] == "summary"


def test_dead_lettered_handler_never_raises_even_with_malformed_payload() -> None:
    """Item-scoped: a malformed dead-letter payload must not raise (which
    would otherwise propagate up through _dispatch_topic and could look like
    it blocks the poll loop for sibling items)."""
    payload = {"stage": "extracted", "reason": "extraction_failed", "error": "boom"}
    _dispatch(KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED, payload)  # must not raise


def test_dead_lettered_item_does_not_block_a_sibling_items_dispatch() -> None:
    """Dispatching a dead-lettered event for item A, followed by a completed
    event for a DIFFERENT item B, must process B normally -- item-scoped
    failure surfacing never blocks a sibling item."""
    dead_letter_payload = {
        "stage": "extracted",
        "stage_version": 1,
        "content_identity": "sha256:item-a-failed",
        "extractor_id": "summary",
        "reason": "extraction_failed",
        "error": "boom",
    }
    _dispatch(KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED, dead_letter_payload, row_id="row-a")

    sibling_payload = {
        "stage": "candidate",
        "stage_version": 1,
        "content_identity": "sha256:item-b-ok",
        "artifact_path": "Sources/item-b.md",
    }
    _dispatch(KNOWLEDGE_ACQUISITION_STAGE_COMPLETED, sibling_payload, row_id="row-b")

    dead_letter_signals = _read_signals(outbox_worker.KA_STAGE_DEAD_LETTER_SURFACED)
    ready_signals = _read_signals(outbox_worker.KA_CANDIDATE_READY_FOR_TRIAGE)
    assert len(dead_letter_signals) == 1
    assert len(ready_signals) == 1
    assert ready_signals[0]["payload"]["content_identity"] == "sha256:item-b-ok"
