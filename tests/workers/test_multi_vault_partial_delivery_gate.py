from __future__ import annotations

from contextlib import contextmanager
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.events.models import new_event
from app.instance.binding_ids import OUTBOX_GLOBAL_BINDING_ID
from app.instance.binding_effect_lease import BindingEffectLeaseManager
from app.instance.ownership_ledger import OwnershipLedger
from app.instance.scalar_binding_runtime import resolve_scalar_binding_runtime
from app.instance.vault_registry import VaultRegistration, VaultRegistryStore
from app.services import outbox as outbox_service
from app.services.outbox_producers import OUTBOX_ENVELOPE_VERSION
from app.workers import outbox_worker
from app.workers import outbox_binding_gate
from app.workers.outbox_binding_gate import (
    OutboxBindingDeferred,
    worker_effect_window,
)
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


pytestmark = pytest.mark.not_pg


class _EffectLeases:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace

    @contextmanager
    def shared_effect(self, binding_id, *, channel_id, root):
        self.trace.append(f"lease-enter:{binding_id}:{channel_id}:{root}")
        try:
            yield
        finally:
            self.trace.append("lease-exit")


def _runtime(root: Path, trace: list[str]):
    return SimpleNamespace(
        vault_binding_id="binding-a",
        binding_revision=7,
        authority="allow",
        authorization_epoch="epoch-a",
        channel_id="dev",
        root=root,
        effect_leases=_EffectLeases(trace),
    )


def _message(binding_id: str, root: Path, *, revision: int = 7):
    # MVR-05D: the fixture row carries the same complete versioned envelope the
    # outbox choke point writes for a vault-bound producer.
    return {
        "id": "row-1",
        "topic": "unknown.test",
        "payload": {},
        "vault_binding_id": binding_id,
        "event": new_event(
            event_type="unknown.test",
            meta={
                "vault_binding_id": binding_id,
                "binding_authority": "allow",
                "binding_authorization_epoch": "epoch-a",
                "binding_revision": revision,
                "vault_root": str(root),
                "outbox_envelope": OUTBOX_ENVELOPE_VERSION,
                "routing_class": "vault_bound",
                "outbox_producer": "ingest.vault_sync",
                "producer_context": {
                    "kind": "binding_runtime",
                    "context_id": None,
                    "context_generation": None,
                },
                "idempotency": {"legacy_key": "legacy-1", "binding_scoped_key": "row-1"},
            },
        ),
    }


def test_mvr05a_scalar_worker_gates_migrated_rows_before_dispatch(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    trace: list[str] = []
    runtime = _runtime(root, trace)
    message = _message("binding-a", root)
    monkeypatch.setattr(outbox_worker, "resolve_scalar_binding_runtime", lambda **_: runtime)
    def _revalidate(value):
        trace.append("revalidate")
        return value

    monkeypatch.setattr(outbox_binding_gate, "validate_frozen_binding_runtime", _revalidate)
    monkeypatch.setattr(outbox_worker, "count_deferred_outbox_rows", lambda **_: 0)
    monkeypatch.setattr(
        outbox_worker,
        "poll_outbox_one",
        lambda **_: message,
    )
    def _dispatch(*_, **__):
        assert resolve_scalar_binding_runtime(requested_binding_id="binding-a") is runtime
        trace.append("dispatch")

    monkeypatch.setattr(outbox_worker, "_dispatch_topic", _dispatch)
    monkeypatch.setattr(
        outbox_worker,
        "ack_outbox",
        lambda *_: trace.append("ack"),
    )

    result = outbox_worker.run_once(vault_root=root)
    assert result.processed == 1
    assert trace == [
        f"lease-enter:binding-a:dev:{root}",
        "revalidate",
        "dispatch",
        "ack",
        "lease-exit",
    ]

    stale = _message("binding-a", root, revision=6)
    with pytest.raises(OutboxBindingDeferred):
        with worker_effect_window(stale, runtime=runtime):
            pytest.fail("stale work reached dispatch")

    global_row = _message(OUTBOX_GLOBAL_BINDING_ID, root)
    with worker_effect_window(global_row, runtime=runtime):
        trace.append("global-dispatch")
    assert trace[-1] == "global-dispatch"


def test_production_tick_skips_stale_head_and_dispatches_later_global(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    trace: list[str] = []
    runtime = _runtime(root, trace)
    global_row = _message(OUTBOX_GLOBAL_BINDING_ID, root)
    captured: dict[str, object] = {}

    monkeypatch.setattr(outbox_worker, "resolve_scalar_binding_runtime", lambda **_: runtime)

    def _poll(**kwargs):
        captured.update(kwargs)
        return global_row

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", _poll)
    monkeypatch.setattr(outbox_worker, "count_deferred_outbox_rows", lambda **_: 1)
    monkeypatch.setattr(outbox_worker, "_dispatch_topic", lambda *_, **__: trace.append("global"))
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda *_: trace.append("ack"))

    result = outbox_worker.run_once(vault_root=root)
    assert captured["required_binding_stamp"] == {
        "vault_binding_id": "binding-a",
        "binding_authority": "allow",
        "binding_authorization_epoch": "epoch-a",
        "binding_revision": 7,
        "vault_root": str(root),
    }
    assert result.state == "processed"
    assert trace == ["global", "ack"]


def test_worker_reports_blocked_pending_when_only_stale_rows_remain(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    runtime = _runtime(root, [])
    monkeypatch.setattr(outbox_worker, "resolve_scalar_binding_runtime", lambda **_: runtime)
    monkeypatch.setattr(outbox_worker, "poll_outbox_one", lambda **_: None)
    monkeypatch.setattr(outbox_worker, "count_deferred_outbox_rows", lambda **_: 2)

    result = outbox_worker.run_once(vault_root=root)
    assert result.state == "blocked_pending_mvr06"
    assert result.processed == 0


def test_mvr05a_revocation_cannot_cross_worker_dispatch_effect_window(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    registry = VaultRegistryStore(tmp_path / "instance" / "vault-registry.md")
    snapshot = registry.register(
        VaultRegistration("binding-a", f"path:{root}", str(root)),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    ledger = OwnershipLedger(tmp_path / "host-global")
    ledger.reserve(
        channel_id="dev",
        vault_binding_id="binding-a",
        root=root,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    ledger.activate("binding-a", _capability=STORAGE_MUTATION_CAPABILITY)
    manager = BindingEffectLeaseManager(
        registry_store=registry,
        ownership_ledger=ledger,
        state_root=tmp_path / "instance" / "binding-effect-leases",
        capability=STORAGE_MUTATION_CAPABILITY,
        poll_interval=0.005,
    )
    runtime = SimpleNamespace(
        vault_binding_id="binding-a",
        binding_revision=snapshot.revision,
        authority="allow",
        authorization_epoch="epoch-a",
        channel_id="dev",
        root=root,
        effect_leases=manager,
    )
    message = _message("binding-a", root, revision=snapshot.revision)
    message["event"] = message["event"].model_copy(
        update={
            "meta": {
                **dict(message["event"].meta or {}),
                "binding_authority": "allow",
                "binding_authorization_epoch": "epoch-a",
            }
        }
    )
    exclusive_entered = threading.Event()
    monkeypatch.setattr(
        outbox_binding_gate, "validate_frozen_binding_runtime", lambda value: value
    )

    def revoke() -> None:
        with manager.exclusive_change(
            "binding-a", channel_id="dev", root=root, timeout=2
        ):
            exclusive_entered.set()

    with worker_effect_window(message, runtime=runtime):
        thread = threading.Thread(target=revoke)
        thread.start()
        assert manager.wait_for_exclusive_pending("binding-a", timeout=1)
        assert not exclusive_entered.is_set()
    thread.join(2)
    assert exclusive_entered.is_set()


class _RecordingOutboxConn:
    """Captures the production choke-point INSERT without fixture row construction."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def execute(self, sql, params=()):
        rows = self.rows

        class _Cursor:
            def fetchone(self_inner):
                if not sql.lstrip().lower().startswith("insert into outbox"):
                    return None
                rows.append(
                    {
                        "id": params[0],
                        "topic": params[1],
                        "payload": params[2],
                        "legacy_key": params[5],
                        "vault_binding_id": params[6],
                    }
                )
                return (params[0],)

        return _Cursor()


def _polled(row: dict) -> dict:
    """Reconstruct the message exactly as ``poll_outbox_one`` hands it to the worker."""
    event = outbox_service._coerce_event_from_db(row["payload"], row["topic"])
    return {
        "id": str(row["id"]),
        "topic": event.event_type,
        "payload": dict(event.payload),
        "event": event,
        "vault_binding_id": str(row["vault_binding_id"]),
    }


def _with_meta(message: dict, **changes) -> dict:
    meta = {**dict(message["event"].meta or {}), **changes}
    for key, value in list(meta.items()):
        if value is _DROP:
            meta.pop(key)
    return {**message, "event": message["event"].model_copy(update={"meta": meta})}


_DROP = object()


def test_completed_worker_delivery_retains_mvr05a_fail_closed_gate(
    tmp_path, monkeypatch
) -> None:
    """MVR-05D: complete envelopes dispatch; legacy/corrupt/mismatched/ambiguous rows defer."""

    root = tmp_path / "vault"
    root.mkdir()
    trace: list[str] = []
    runtime = _runtime(root, trace)
    monkeypatch.setattr(outbox_service, "resolve_scalar_binding_runtime", lambda **_: runtime)
    monkeypatch.setattr(outbox_binding_gate, "validate_frozen_binding_runtime", lambda value: value)

    # 1. A real registered vault-bound producer writes through the production
    #    choke point; the worker consumes that row under the binding lease.
    conn = _RecordingOutboxConn()
    outbox_service.insert_object_and_outbox(
        {"uuid": "note-1", "relative_path": "n.md"},
        "mvr05d.vault_bound.test",
        "trace-1",
        conn=conn,
        producer="ingest.vault_sync",
    )
    (row,) = conn.rows
    assert row["vault_binding_id"] == "binding-a"
    complete = _polled(row)
    assert outbox_service.binding_envelope_is_dispatchable(complete)

    dispatched: list[str] = []
    monkeypatch.setattr(outbox_worker, "resolve_scalar_binding_runtime", lambda **_: runtime)
    monkeypatch.setattr(outbox_worker, "count_deferred_outbox_rows", lambda **_: 0)
    monkeypatch.setattr(outbox_worker, "poll_outbox_one", lambda **_: complete)
    monkeypatch.setattr(
        outbox_worker,
        "_dispatch_topic",
        lambda topic, *_a, message, **_k: dispatched.append(message["id"]),
    )
    acked: list[str] = []
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda row_id, *_: acked.append(row_id))
    result = outbox_worker.run_once(vault_root=root)
    assert result.state == "processed"
    assert dispatched == acked == [complete["id"]]
    assert trace[0].startswith("lease-enter:binding-a") and trace[-1] == "lease-exit"

    # 2. Every incomplete or inconsistent vault-bound row stays pending: the
    #    05A fail-closed treatment is retained for each failure class.
    legacy_05a_stamp = _with_meta(
        complete,
        outbox_envelope=_DROP,
        routing_class=_DROP,
        producer_context=_DROP,
        idempotency=_DROP,
        outbox_producer=_DROP,
    )
    refused = {
        "legacy-envelope": legacy_05a_stamp,
        "corrupt-version": _with_meta(complete, outbox_envelope="mvr05.outbox-envelope.v0"),
        "corrupt-idempotency": _with_meta(complete, idempotency="not-a-mapping"),
        "mismatched-row-id": {**complete, "id": "replayed-under-another-id"},
        "mismatched-routing": _with_meta(complete, routing_class="global"),
        "ambiguous-context": _with_meta(
            complete,
            producer_context={"kind": "no_binding_runtime", "context_id": None},
        ),
        "stale-revision": _with_meta(complete, binding_revision=6),
    }
    for case, message in refused.items():
        assert not (
            case != "stale-revision" and outbox_service.binding_envelope_is_dispatchable(message)
        ), case
        with pytest.raises(OutboxBindingDeferred):
            with worker_effect_window(message, runtime=runtime):
                pytest.fail(f"{case} row reached dispatch")
    foreign = {**complete, "vault_binding_id": "binding-b"}
    with pytest.raises(OutboxBindingDeferred):
        with worker_effect_window(foreign, runtime=runtime):
            pytest.fail("foreign-binding row reached dispatch")

    # 3. The durable poll predicate carries the same complete-envelope gate, so
    #    incomplete rows are skipped (not head-of-line) and counted as blocked.
    captured: list[tuple[str, tuple]] = []

    class _SqlConn:
        def execute(self, sql, params=()):
            captured.append((sql, tuple(params)))

            class _Cursor:
                def fetchone(self_inner):
                    return None if sql.lstrip().startswith("select id") else (3,)

            return _Cursor()

    stamp = outbox_worker.required_worker_binding_stamp(runtime)
    assert stamp is not None
    assert outbox_service.poll_outbox_one(
        _SqlConn(),
        eligible_binding_ids=outbox_worker.eligible_worker_bindings(runtime),
        required_binding_stamp=stamp,
    ) is None
    assert outbox_service.count_deferred_outbox_rows(
        conn=_SqlConn(), required_binding_stamp=stamp
    ) == 3
    for sql, params in captured:
        assert "{meta,outbox_envelope}" in sql and OUTBOX_ENVELOPE_VERSION in params
        assert "binding_scoped_key}' = id::text" in sql
        assert "legacy_key}' = legacy_key::text" in sql

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", lambda **_: None)
    monkeypatch.setattr(outbox_worker, "count_deferred_outbox_rows", lambda **_: 1)
    assert outbox_worker.run_once(vault_root=root).state == "blocked_pending_mvr06"

    # 4. Independently safe explicit-global work is never blocked by them.
    global_conn = _RecordingOutboxConn()
    outbox_service.write_outbox_event(
        new_event(event_type="mvr05d.global.test", payload={}),
        conn=global_conn,
        idempotency_key=outbox_service.derive_idempotency_key("t", "s", "f"),
        vault_binding_id=OUTBOX_GLOBAL_BINDING_ID,
        producer="shared.instance.default_vault",
    )
    global_message = _polled(global_conn.rows[0])
    assert global_message["event"].meta["routing_class"] == "global"
    with worker_effect_window(global_message, runtime=runtime):
        trace.append("global-dispatch")
    assert trace[-1] == "global-dispatch"
