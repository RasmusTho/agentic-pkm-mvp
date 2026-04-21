from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.events.types import PROMOTE_DONE, PROMOTE_ERROR, PROMOTE_INTENT_CREATED
from app.observability import status_service
from app.promotion.consumer import consume_promotion_intents, reset_promotion_dedup_store
from app.store import object_store as object_store_module
from app.store.object_store import DomainObject, ObjectStore

pytestmark = pytest.mark.not_pg


def _write_note(path: Path, uuid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nuuid: {uuid}\nreview_state: draft\n---\nContent\n",
        encoding="utf-8",
    )


def _make_promotion_intent(
    *,
    event_id: str,
    trace_id: str,
    note_uuid: str,
    note_path: Path,
) -> dict:
    return {
        "event": PROMOTE_INTENT_CREATED,
        "event_id": event_id,
        "trace_id": trace_id,
        "source": "panel_agent",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": {
            "note": {"uuid": note_uuid, "path": str(note_path)},
            "transition": {"family": "promotion", "target_maturity": "evergreen"},
        },
    }


def _read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    object_store_module._MEMORY_STORE.clear()
    reset_promotion_dedup_store()
    yield
    object_store_module._MEMORY_STORE.clear()
    reset_promotion_dedup_store()


def test_consumer_failure_paths_are_observable_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")

    vault_root = tmp_path / "vault"
    applied_uuid = "00000000-0000-0000-0000-000000000001"
    missing_uuid = "00000000-0000-0000-0000-000000000002"
    applied_path = vault_root / "Notes" / "applied.md"
    missing_path = vault_root / "Notes" / "missing.md"
    _write_note(applied_path, applied_uuid)

    ObjectStore().save_object(
        DomainObject(
            uuid=applied_uuid,
            kind="note",
            payload={"raw_text": applied_path.read_text(encoding="utf-8"), "origin": "vault"},
            source_ref=str(applied_path),
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
        trace_id="trace-seed",
    )

    trace_id = "trace-outbox-consumer"
    event_1 = _make_promotion_intent(
        event_id="evt-1",
        trace_id=trace_id,
        note_uuid=applied_uuid,
        note_path=applied_path,
    )
    event_2 = _make_promotion_intent(
        event_id="evt-1",
        trace_id=trace_id,
        note_uuid=applied_uuid,
        note_path=applied_path,
    )
    event_3 = _make_promotion_intent(
        event_id="evt-2",
        trace_id=trace_id,
        note_uuid=missing_uuid,
        note_path=missing_path,
    )

    outbox_path = tmp_path / "index-outbox.jsonl"
    outbox_path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in (event_1, event_2, event_3)) + "\n",
        encoding="utf-8",
    )

    summary = consume_promotion_intents(outbox_path=outbox_path)
    assert summary["intents_seen"] == 3
    assert summary["applied"] == 1
    assert summary["errors"] == 1
    assert summary["skipped_duplicates"] == 1
    assert summary["emitted"] == 2

    summary_again = consume_promotion_intents(outbox_path=outbox_path)
    assert summary_again == {"intents_seen": 0, "applied": 0, "errors": 0, "emitted": 0, "skipped_duplicates": 0}

    records = _read_records(outbox_path)
    done_events = [record for record in records if record.get("event") == PROMOTE_DONE]
    error_events = [record for record in records if record.get("event") == PROMOTE_ERROR]

    assert len(done_events) == 1
    assert len(error_events) == 1

    done = done_events[0]
    assert done["trace_id"] == trace_id
    assert done["payload"]["source_event"] == "evt-1"
    assert done["payload"]["note_uuid"] == applied_uuid

    error = error_events[0]
    assert error["trace_id"] == trace_id
    assert error["payload"]["reason"] == "path_not_found"
    assert error["payload"]["source_event"] == "evt-2"
    assert error["payload"]["note_uuid"] == missing_uuid

    updated_note = applied_path.read_text(encoding="utf-8")
    assert "review_state: reviewed" in updated_note
    assert "maturity: evergreen" in updated_note


def test_jsonl_audit_is_not_treated_as_worker_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox_path = tmp_path / "index-outbox.jsonl"
    outbox_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "event": PROMOTE_INTENT_CREATED,
                    "event_id": "evt-audit-1",
                    "trace_id": "trace-audit",
                    "source": "panel_agent",
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "payload": {
                        "note": {
                            "uuid": "00000000-0000-0000-0000-000000000003",
                            "path": str(tmp_path / "vault" / "Notes" / "audit.md"),
                        },
                        "transition": {"family": "promotion", "target_maturity": "evergreen"},
                    },
                },
                ensure_ascii=False,
            )
            for _ in range(2)
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("DATABASE_URL", "postgresql://app:app@db:5432/app")
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("WORKER_ENABLE", "1")
    monkeypatch.setattr(status_service, "INDEX_OUTBOX_PATH", outbox_path, raising=False)
    monkeypatch.setattr(status_service, "_count_outbox_pending_db", lambda: 7)

    worker_queue = status_service._get_worker_queue_status()
    events_log = status_service._events_log_status()

    assert worker_queue.mode == "db"
    assert worker_queue.source_path == "postgresql://app:app@db:5432/app"
    assert worker_queue.pending == 7
    assert events_log.path == str(outbox_path)
    assert events_log.total_lines == 2
