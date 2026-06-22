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
