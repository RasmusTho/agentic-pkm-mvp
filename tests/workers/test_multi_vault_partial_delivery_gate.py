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
