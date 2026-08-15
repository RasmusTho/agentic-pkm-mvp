"""Production-loop no-vault idle + dispatch-table parity coverage for #2407.

PR #2399 (#2384 slice 05B) added the no-vault idle guard to
``outbox_worker.run_once(vault_root=None)``, but the production daemon
``run()`` still polled and dispatched directly. On a no-vault boot with queued
vault-bound work (e.g. ``ingest.vault.changed``) the handler raised
``NoVaultSelectedError``, which is non-transient, so the row was poison-counted
until dead-lettered instead of staying queued until a vault is selected.

These tests lock in two guarantees for #2407:

1. The production ``run()`` loop idles before polling/dispatching when no vault
   is selected; queued vault-bound rows are not dead-lettered solely due to the
   no-vault state.
2. ``run_once`` dispatches every supported topic through the real dispatch table
   rather than acking a supported-but-unhandled topic as if it were unsupported.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.events.types import INGEST_VAULT_CHANGED, PROMOTE_INTENT_CREATED
import app.workers.outbox_worker as outbox_worker

pytestmark = pytest.mark.not_pg


def test_run_idles_without_vault_before_dispatching_vault_bound_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The production daemon idles on no-vault instead of dead-lettering rows.

    With no vault selected the loop must not poll/dispatch a vault-bound row;
    it must not call ``poll_outbox_one``, ``handle_ingest_vault_changed``, or
    dead-letter anything. Queued rows stay queued until a vault is selected.
    """
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    # No /app/vault legacy mount and no selected vault: the loop must idle.
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)

    def _fail_poll() -> None:  # pragma: no cover - asserts it is never called
        raise AssertionError("poll_outbox_one must not run when no vault is selected")

    dead_letters: list[Any] = []

    def _fail_dispatch(*_a: Any, **_k: Any) -> None:  # pragma: no cover
        raise AssertionError("vault-bound handler must not run when no vault is selected")

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", _fail_poll)
    monkeypatch.setattr(outbox_worker, "handle_ingest_vault_changed", _fail_dispatch)
    monkeypatch.setattr(
        outbox_worker,
        "_dead_letter_outbox_message",
        lambda *a, **k: dead_letters.append((a, k)),
    )

    # The loop should complete its ticks by idling, never raising on the missing vault.
    outbox_worker.run(
        interval=0.0,
        heartbeat_interval=9999,
        log_heartbeat_interval=None,
        stop_after_ticks=3,
    )

    assert dead_letters == []
    assert not (tmp_path / "vault").exists()


def test_run_once_uses_real_dispatch_table_for_supported_topics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``run_once`` dispatches supported topics via the real dispatch table.

    A supported topic that ``run()`` handles (here ``promote.intent.created``)
    must not be silently acked as unsupported when delegated through
    ``run_once``; it must reach its real handler and then ack.
    """
    vault = tmp_path / "selected-vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)

    message = {
        "id": "row-1",
        "topic": PROMOTE_INTENT_CREATED,
        "payload": {"trace_id": "trace-promote", "event_id": "evt-1"},
    }
    monkeypatch.setattr(outbox_worker, "poll_outbox_one", lambda: message)

    consumed: list[dict[str, Any]] = []

    def _fake_consume(payload: Any, **kwargs: Any) -> None:
        consumed.append({"payload": dict(payload), "kwargs": kwargs})

    # The promotion consumer is imported lazily inside the dispatch path.
    import app.promotion.consumer as promotion_consumer

    monkeypatch.setattr(
        promotion_consumer, "consume_promotion_intent_payload", _fake_consume
    )

    acked: list[str] = []
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda mid: acked.append(mid))

    result = outbox_worker.run_once(vault_root=None)

    # The real handler ran for the supported topic (not acked as "unsupported").
    assert len(consumed) == 1
    assert consumed[0]["payload"]["trace_id"] == "trace-promote"
    assert acked == ["row-1"]
    assert result.state == "processed"
    assert result.processed == 1


def test_run_once_still_processes_vault_changed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression guard: existing supported topics keep their real handler."""
    vault = tmp_path / "selected-vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)

    message = {
        "id": "row-2",
        "topic": INGEST_VAULT_CHANGED,
        "payload": {"trace_id": "trace-ingest"},
    }
    monkeypatch.setattr(outbox_worker, "poll_outbox_one", lambda: message)

    handled: list[dict[str, Any]] = []
    monkeypatch.setattr(
        outbox_worker,
        "handle_ingest_vault_changed",
        lambda payload, **kwargs: handled.append({"payload": dict(payload), "kwargs": kwargs}),
    )
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda _mid: None)

    result = outbox_worker.run_once(vault_root=None)

    assert len(handled) == 1
    assert result.state == "processed"


def test_store_schema_missing_is_transient_never_dead_letters() -> None:
    """Schema-missing is boot-ordering, not poison (KERNEL-04, #2766).

    On a fresh stack the worker/watcher containers depend only on the db
    service while `alembic upgrade head` runs in the api/agent-service boot
    path, so the first dispatches can hit an unmigrated database. The
    production classification site (`_is_transient_dispatch_error`) must treat
    `StoreSchemaMissingError` — raised by the assert-only store preflight —
    as transient so the row stays pending for crash-retry under supervision
    instead of burning the poison budget and dead-lettering ingest events.
    """
    from app.db.errors import StoreSchemaMissingError

    exc = StoreSchemaMissingError(
        "Missing store table(s) ['store_objects'] in the configured Postgres. "
        "Store schema is migration-owned (KERNEL-04, #2766): run 'alembic upgrade head'."
    )
    assert outbox_worker._is_transient_dispatch_error(exc) is True

    # Also transient when wrapped mid-chain, as handlers re-raise with context.
    try:
        try:
            raise exc
        except StoreSchemaMissingError as inner:
            raise RuntimeError("handler wrapper") from inner
    except RuntimeError as wrapped:
        assert outbox_worker._is_transient_dispatch_error(wrapped) is True

    # Guard the boundary: a plain RuntimeError (poison payload class) must NOT
    # ride the schema-missing exemption.
    assert outbox_worker._is_transient_dispatch_error(RuntimeError("boom")) is False


def test_schema_violation_dead_letters_at_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """KERNEL-08 (#2770): an invalid registered-schema payload dead-letters immediately.

    Drives the production dispatch entrypoint (`_dispatch_topic` via the
    `run()` consume loop): a row tagged with a registered schema version whose
    payload violates that schema must dead-letter with reason
    `schema_violation` and must never reach the real topic handler (no partial
    processing), on the very first attempt (no poison-retry budget spent).
    """
    from app.events.models import new_event

    vault = tmp_path / "selected-vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)

    # index.embedding.requested.v1 requires payload.object_id; this payload lacks it.
    bad_payload = {"not_object_id": "x"}
    tagged_event = new_event(
        event_type="index.embedding.requested",
        payload=bad_payload,
        meta={"payload_schema": "index.embedding.requested.v1"},
    )
    message = {
        "id": "row-schema-violation",
        "topic": "index.embedding.requested",
        "payload": bad_payload,
        "event": tagged_event,
    }

    poll_calls = {"count": 0}

    def _poll_once():
        poll_calls["count"] += 1
        if poll_calls["count"] == 1:
            return message
        return None

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", _poll_once)
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)

    def _fail_handler(*_a: Any, **_k: Any) -> None:  # pragma: no cover - must never run
        raise AssertionError("real topic handler must not run on a schema violation")

    monkeypatch.setattr(outbox_worker, "process_indexer_event", _fail_handler)

    dead_letters: list[dict[str, Any]] = []

    def _capture_dead_letter(
        topic,
        payload,
        *,
        message_id,
        reason,
        attempts,
        trace_id,
        error,
        source_vault_binding_id,
    ):
        dead_letters.append(
            {
                "topic": topic,
                "payload": dict(payload),
                "message_id": message_id,
                "reason": reason,
                "attempts": attempts,
            }
        )

    monkeypatch.setattr(outbox_worker, "_dead_letter_outbox_message", _capture_dead_letter)

    acked: list[str] = []
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda mid: acked.append(mid))

    outbox_worker.run(interval=0.0, heartbeat_interval=9999, log_heartbeat_interval=None, stop_after_ticks=2)

    assert len(dead_letters) == 1
    assert dead_letters[0]["topic"] == "index.embedding.requested"
    assert dead_letters[0]["reason"] == "schema_violation"
    assert dead_letters[0]["message_id"] == "row-schema-violation"
    assert acked == ["row-schema-violation"]


def test_run_dead_letters_malformed_panel_note_uuid_without_worker_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A malformed stored panel UUID is poison for one row, not the worker.

    Exercise the production ``run()`` consume path rather than the UUID helper
    in isolation: the worker must keep running long enough to write a heartbeat
    after it has recorded and acknowledged the malformed event.
    """
    vault = tmp_path / "selected-vault"
    note = vault / "Inbox" / "malformed-panel.md"
    note.parent.mkdir(parents=True)
    source = "---\ntitle: Broken panel\nuuid: not-a-uuid\n---\n\n- [ ] Keep this source unchanged\n"
    note.write_text(source, encoding="utf-8")
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(audit_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    message = {
        "id": "row-panel-bad-uuid",
        "topic": outbox_worker.PANEL_SCAN_REQUESTED,
        "payload": {
            "vault_path": str(note),
            "relative_path": "Inbox/malformed-panel.md",
            "trace_id": "trace-panel-bad-uuid",
        },
    }
    polled = False

    def poll_once():
        nonlocal polled
        if polled:
            return None
        polled = True
        return message

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", poll_once)
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL", "0")

    acked: list[str] = []
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda mid: acked.append(str(mid)))
    heartbeats: list[dict[str, object]] = []
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **kwargs: heartbeats.append(kwargs))

    outbox_worker.run(interval=0.0, heartbeat_interval=0, log_heartbeat_interval=None, stop_after_ticks=2)

    assert acked == ["row-panel-bad-uuid"]
    receipt = json.loads(audit_path.read_text(encoding="utf-8"))
    assert receipt["event"] == outbox_worker.OUTBOX_EVENT_DEAD_LETTERED
    assert receipt["payload"] == {
        "original_topic": outbox_worker.PANEL_SCAN_REQUESTED,
        "original_event_id": "",
        "outbox_id": "row-panel-bad-uuid",
        "reason": "invalid_note_uuid",
        "attempts": 0,
        "error": "invalid panel note uuid: not-a-uuid",
    }
    assert heartbeats and heartbeats[-1]["processed_total"] == 1
    assert note.read_text(encoding="utf-8") == source


def test_schema_violation_on_grandfathered_row_is_log_only_never_dead_lettered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A pre-registry row (no payload_schema/schema_version tag) is grandfathered v0.

    Cross-task invariant #1 (docs/RUNTIME_CORRECTNESS_KERNEL/README.md): rows
    written before the registry existed must be validated log-only at
    dispatch, never dead-lettered retroactively, even if their payload would
    violate the current schema.
    """
    from app.events.models import new_event

    vault = tmp_path / "selected-vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)

    bad_payload = {"not_object_id": "x"}
    # No meta at all: this is what a genuinely pre-registry DB row looks like.
    untagged_event = new_event(event_type="index.embedding.requested", payload=bad_payload)
    message = {
        "id": "row-grandfathered",
        "topic": "index.embedding.requested",
        "payload": bad_payload,
        "event": untagged_event,
    }

    poll_calls = {"count": 0}

    def _poll_once():
        poll_calls["count"] += 1
        if poll_calls["count"] == 1:
            return message
        return None

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", _poll_once)
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)

    handled: list[Any] = []
    monkeypatch.setattr(
        outbox_worker,
        "process_indexer_event",
        lambda evt: handled.append(evt),
    )

    dead_letters: list[Any] = []
    monkeypatch.setattr(
        outbox_worker,
        "_dead_letter_outbox_message",
        lambda *a, **k: dead_letters.append((a, k)),
    )

    acked: list[str] = []
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda mid: acked.append(mid))

    outbox_worker.run(interval=0.0, heartbeat_interval=9999, log_heartbeat_interval=None, stop_after_ticks=2)

    assert dead_letters == []
    assert len(handled) == 1
    assert acked == ["row-grandfathered"]
