from __future__ import annotations

import multiprocessing
import os
import queue
import threading
import time
from pathlib import Path

import pytest

from app.instance.active_context_service import binding_revision_for
from app.instance.binding_effect_lease import (
    BindingEffectLeaseManager,
    BindingEffectLeaseTimeout,
)
from app.instance.ownership_ledger import OwnershipLedger
from app.instance.vault_registry import VaultRegistration, VaultRegistryStore
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def _build_manager(root: Path, *binding_ids: str) -> BindingEffectLeaseManager:
    registry = VaultRegistryStore(root / "instance" / "vault-registry.md")
    ledger = OwnershipLedger(root / "host-global")
    for binding_id in binding_ids:
        vault = root / "vaults" / binding_id
        vault.mkdir(parents=True, exist_ok=True)
        registry.register(
            VaultRegistration(binding_id, f"path:{vault}", str(vault)),
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        ledger.reserve(
            channel_id="dev",
            vault_binding_id=binding_id,
            root=vault,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        ledger.activate(binding_id, _capability=STORAGE_MUTATION_CAPABILITY)
    return BindingEffectLeaseManager(
        registry_store=registry,
        ownership_ledger=ledger,
        state_root=root / "instance" / "binding-effect-leases",
        capability=STORAGE_MUTATION_CAPABILITY,
        poll_interval=0.005,
    )


def _manager_for_existing(root: str) -> BindingEffectLeaseManager:
    path = Path(root)
    return BindingEffectLeaseManager(
        registry_store=VaultRegistryStore(path / "instance" / "vault-registry.md"),
        ownership_ledger=OwnershipLedger(path / "host-global"),
        state_root=path / "instance" / "binding-effect-leases",
        capability=STORAGE_MUTATION_CAPABILITY,
        poll_interval=0.005,
    )


def _hold_shared(root: str, acquired, release) -> None:
    manager = _manager_for_existing(root)
    vault = Path(root) / "vaults" / "binding-a"
    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=5):
        acquired.set()
        release.wait(5)


def _record_exclusive(root: str, name: str, entered) -> None:
    manager = _manager_for_existing(root)
    vault = Path(root) / "vaults" / "binding-a"
    with manager.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=5):
        entered.put(name)
        time.sleep(0.03)


def test_exclusive_acquirer_waits_for_an_in_flight_shared_holder(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    shared_entered = threading.Event()
    shared_release = threading.Event()
    exclusive_entered = threading.Event()

    def hold_shared() -> None:
        with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=2):
            shared_entered.set()
            shared_release.wait(2)

    def acquire_exclusive() -> None:
        with manager.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=2):
            exclusive_entered.set()

    shared = threading.Thread(target=hold_shared)
    exclusive = threading.Thread(target=acquire_exclusive)
    shared.start()
    assert shared_entered.wait(1)
    exclusive.start()
    time.sleep(0.05)
    assert not exclusive_entered.is_set()
    shared_release.set()
    shared.join(2)
    exclusive.join(2)
    assert exclusive_entered.is_set()


def test_pending_exclusive_blocks_new_shared_acquisition(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    first_entered = threading.Event()
    first_release = threading.Event()
    exclusive_entered = threading.Event()

    def first_shared() -> None:
        with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=2):
            first_entered.set()
            first_release.wait(2)

    def exclusive() -> None:
        with manager.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=2):
            exclusive_entered.set()

    shared_thread = threading.Thread(target=first_shared)
    exclusive_thread = threading.Thread(target=exclusive)
    shared_thread.start()
    assert first_entered.wait(1)
    exclusive_thread.start()
    assert manager.wait_for_exclusive_pending("binding-a", timeout=1)

    with pytest.raises(BindingEffectLeaseTimeout):
        with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=0.05):
            pytest.fail("a new shared holder barged ahead of a pending exclusive")

    first_release.set()
    shared_thread.join(2)
    exclusive_thread.join(2)
    assert exclusive_entered.is_set()


def test_foreign_pid_namespace_preserves_live_shared_and_pending_authority(
    tmp_path, monkeypatch
) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    foreign_observer = _manager_for_existing(str(tmp_path))
    vault = tmp_path / "vaults" / "binding-a"
    exclusive_entered = threading.Event()

    def exclusive() -> None:
        with manager.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=2):
            exclusive_entered.set()

    def reject_observer_local_pid_identity(holder) -> bool:
        raise AssertionError("observer-local PID identity is not lease authority")

    monkeypatch.setattr(
        foreign_observer,
        "_holder_alive",
        reject_observer_local_pid_identity,
    )
    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
        exclusive_thread = threading.Thread(target=exclusive)
        exclusive_thread.start()
        assert manager.wait_for_exclusive_pending("binding-a", timeout=1)

        observation = foreign_observer.observe("binding-a")
        assert observation.shared_count == 1
        assert observation.exclusive_pending_count == 1
        with pytest.raises(BindingEffectLeaseTimeout):
            with foreign_observer.shared_effect(
                "binding-a", channel_id="dev", root=vault, timeout=0.05
            ):
                pytest.fail("a foreign observer cannot erase a live pending waiter")

    exclusive_thread.join(2)
    assert exclusive_entered.is_set()


def test_leases_for_distinct_bindings_do_not_serialise(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a", "binding-b")
    vault_a = tmp_path / "vaults" / "binding-a"
    vault_b = tmp_path / "vaults" / "binding-b"

    with manager.shared_effect("binding-a", channel_id="dev", root=vault_a, timeout=1):
        with manager.exclusive_change("binding-b", channel_id="dev", root=vault_b, timeout=0.2):
            assert manager.observe("binding-a").shared_count == 1
            assert manager.observe("binding-b").exclusive_held


def test_lease_bookkeeping_does_not_rotate_binding_revision(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    before = manager.registry_store.load()
    binding_revision = binding_revision_for(before, "binding-a")

    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
        inside = manager.registry_store.load()
        assert inside.revision == before.revision
        assert binding_revision_for(inside, "binding-a") == binding_revision
        assert manager.persisted_state("binding-a")["generation"] == 1

    after = manager.registry_store.load()
    assert after.revision == before.revision
    assert binding_revision_for(after, "binding-a") == binding_revision
    assert manager.persisted_state("binding-a")["generation"] == 2


@pytest.mark.parametrize("binding_id", [" binding-a ", "vault-å"])
def test_opaque_binding_id_round_trips_through_acquire_and_release(tmp_path, binding_id) -> None:
    manager = _build_manager(tmp_path, binding_id)
    vault = tmp_path / "vaults" / binding_id

    with manager.shared_effect(binding_id, channel_id="dev", root=vault, timeout=1):
        persisted = manager.persisted_state(binding_id)
        assert persisted["vaultBindingId"] == binding_id
        assert binding_id in manager.registry_store.load().extensions["bindingEffectLeases"]

    assert manager.persisted_state(binding_id)["vaultBindingId"] == binding_id


def test_exclusion_holds_across_separate_processes(tmp_path) -> None:
    _build_manager(tmp_path, "binding-a")
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    release = context.Event()
    process = context.Process(target=_hold_shared, args=(str(tmp_path), acquired, release))
    process.start()
    assert acquired.wait(3)

    manager = _manager_for_existing(str(tmp_path))
    vault = tmp_path / "vaults" / "binding-a"
    with pytest.raises(BindingEffectLeaseTimeout):
        with manager.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=0.1):
            pytest.fail("cross-process exclusive overlapped a shared holder")

    release.set()
    process.join(5)
    assert process.exitcode == 0
    with manager.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=1):
        assert manager.observe("binding-a").exclusive_held


def test_unreaped_dead_exclusive_waiter_does_not_occupy_fifo_head(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"

    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
        pid = os.fork()
        if pid == 0:
            child = _manager_for_existing(str(tmp_path))
            try:
                with child.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=10):
                    os._exit(0)
            except BaseException:
                os._exit(2)
        assert manager.wait_for_exclusive_pending("binding-a", timeout=3)
        os.kill(pid, 9)
        time.sleep(0.05)

    try:
        with manager.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=2):
            assert manager.observe("binding-a").exclusive_held
    finally:
        os.waitpid(pid, 0)


def test_cross_process_exclusive_waiters_preserve_fifo_order(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    context = multiprocessing.get_context("spawn")
    entered = context.Queue()

    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
        first = context.Process(target=_record_exclusive, args=(str(tmp_path), "first", entered))
        first.start()
        assert manager.wait_for_exclusive_pending("binding-a", timeout=3)
        second = context.Process(target=_record_exclusive, args=(str(tmp_path), "second", entered))
        second.start()
        deadline = time.monotonic() + 3
        while (
            manager.observe("binding-a").exclusive_pending_count < 2 and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert manager.observe("binding-a").exclusive_pending_count == 2

    assert entered.get(timeout=3) == "first"
    assert entered.get(timeout=3) == "second"
    with pytest.raises(queue.Empty):
        entered.get_nowait()
    first.join(5)
    second.join(5)
    assert first.exitcode == second.exitcode == 0
