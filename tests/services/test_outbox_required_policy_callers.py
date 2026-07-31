"""Production-caller coverage for strict self-owned outbox policy (#4064)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.panel_agent import execution as panel_execution
from app.episodes import closure
from app.episodes.closure import EpisodeCloseCandidate
from app.episodes.notes import episode_note_rel_path
from app.episodes.store import write_episode_note
from app.events.schema import make_outbox_event
from app.objects import DomainObject, ObjectStore
from app.outbox import events as outbox_events
from app.promotion.consumer import (
    consume_promotion_intent_payload,
    reset_promotion_dedup_store,
)
from app.services import outbox as outbox_service
from app.workers import outbox_worker
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg


@pytest.fixture()
def required_db_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select memory domain storage while making a configured DB outbox unavailable."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")

    def _raise() -> None:
        raise RuntimeError("required outbox unavailable")

    monkeypatch.setattr(outbox_service, "_open_conn", _raise)


def _allow_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy", "reason": None})


def test_episode_closure_does_not_advance_projection_after_memory_skip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    required_db_unavailable: None,
) -> None:
    """The load-bearing outbox-before-projection boundary must fail before projection sync."""
    episode_id = "ep-40640000-2222-4333-8444-555555555555"
    end = datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc)
    write_episode_note(
        title="Strict outbox episode",
        scope="work",
        start=(end - timedelta(hours=1)).isoformat(),
        end=end.isoformat(),
        closed=False,
        segmentation="proposed",
        episode_id=episode_id,
        vault_root=tmp_path,
        write_guard=_allow_guard(),
    )
    monkeypatch.setattr(closure, "_count_active_bound_artifacts", lambda _episode_id: 0)
    projection_syncs: list[str] = []
    monkeypatch.setattr(closure, "_sync_projection_closed", projection_syncs.append)

    candidate = EpisodeCloseCandidate(
        episode_id=episode_id,
        scope="work",
        note_path=episode_note_rel_path(episode_id),
        time_end=end,
    )

    with pytest.raises(RuntimeError, match="required outbox unavailable"):
        closure.close_episode(candidate, vault_root=tmp_path, write_guard=_allow_guard())

    assert projection_syncs == []


def test_promotion_does_not_return_applied_after_memory_skip(
    tmp_path: Path,
    required_db_unavailable: None,
) -> None:
    """Promotion must fail before returning an applied/emitted acknowledgement."""
    reset_promotion_dedup_store()
    note_uuid = "00000000-0000-0000-0000-000000004064"
    note_path = tmp_path / "vault" / "promotion.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        f"---\nuuid: {note_uuid}\nreview_state: draft\n---\nBody\n",
        encoding="utf-8",
    )
    payload = {
        "note": {"uuid": note_uuid, "path": str(note_path)},
        "transition": {"family": "promotion", "target_maturity": "evergreen"},
    }

    with pytest.raises(RuntimeError, match="required outbox unavailable"):
        consume_promotion_intent_payload(
            payload,
            trace_id="trace-promote-4064",
            event_id="event-promote-4064",
        )


def test_embedding_request_does_not_append_diagnostic_after_memory_skip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    required_db_unavailable: None,
) -> None:
    """The DB-first embedding request must fail before its diagnostic JSONL append."""
    audit_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(outbox_events, "INDEX_OUTBOX_PATH", audit_path)

    with pytest.raises(RuntimeError, match="required outbox unavailable"):
        outbox_events.emit_index_embedding_requested(
            {
                "object_id": uuid4(),
                "trace_id": "trace-embedding-4064",
                "source": "test",
            }
        )

    assert not audit_path.exists()


def test_panel_db_persistence_does_not_execute_after_memory_skip(
    monkeypatch: pytest.MonkeyPatch,
    required_db_unavailable: None,
) -> None:
    """An explicit persist-created-to-DB request must fail before intent execution."""
    intent = make_outbox_event(
        "panel.intent.created",
        source="test",
        payload={
            "note": {"uuid": "note-4064"},
            "panel": {"panel_id": "panel-4064"},
        },
    )
    monkeypatch.setattr(
        panel_execution,
        "run_panel_intent_for_note",
        lambda *args, **kwargs: [intent],
    )
    executed: list[object] = []

    def _execute(event: object, **kwargs: object) -> object:
        executed.append(event)
        return SimpleNamespace(emitted_events=[])

    monkeypatch.setattr(panel_execution, "execute_panel_intent", _execute)

    with pytest.raises(RuntimeError, match="required outbox unavailable"):
        panel_execution.run_panel_note_execution(
            "note-4064",
            persist_created_to_db=True,
        )

    assert executed == []


def test_durable_object_save_does_not_ack_after_memory_skip(
    monkeypatch: pytest.MonkeyPatch,
    required_db_unavailable: None,
) -> None:
    """A durable object put must propagate a missing canonical outbox event."""
    puts: list[tuple[object, dict[str, object]]] = []

    class _Store:
        def put(self, object_id: object, **kwargs: object) -> None:
            puts.append((object_id, kwargs))

    monkeypatch.setattr(
        "app.objects.resolve_object_store_port",
        lambda: SimpleNamespace(backend="pg", store=_Store()),
    )
    obj = DomainObject(
        uuid="11111111-1111-4111-8111-111111114064",
        kind="note",
        payload={"content": "strict"},
        source_ref="strict.md",
        created_at=datetime.now(timezone.utc),
    )

    with pytest.raises(RuntimeError, match="required outbox unavailable"):
        ObjectStore().save_object(obj)

    assert len(puts) == 1


def test_worker_retry_does_not_report_queued_after_memory_skip(
    tmp_path: Path,
    required_db_unavailable: None,
) -> None:
    """A skipped DB retry must not let the worker report that retry as queued."""
    queued = outbox_worker._queue_transient_retry(
        "test.worker.retry",
        {
            "event_id": "event-worker-4064",
            "trace_id": "trace-worker-4064",
            "_worker_retry_count": 0,
        },
        note_path=tmp_path / "note.md",
        reason="transient",
        original_event_id="event-worker-4064",
    )

    assert queued is False
