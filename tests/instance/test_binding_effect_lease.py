from __future__ import annotations

import multiprocessing
import threading
import time
from pathlib import Path

import pytest

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
    with manager.shared_effect(
        "binding-a", channel_id="dev", root=vault, timeout=5
    ):
        acquired.set()
        release.wait(5)


def test_exclusive_acquirer_waits_for_an_in_flight_shared_holder(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    shared_entered = threading.Event()
    shared_release = threading.Event()
    exclusive_entered = threading.Event()

    def hold_shared() -> None:
        with manager.shared_effect(
            "binding-a", channel_id="dev", root=vault, timeout=2
        ):
            shared_entered.set()
            shared_release.wait(2)

    def acquire_exclusive() -> None:
        with manager.exclusive_change(
            "binding-a", channel_id="dev", root=vault, timeout=2
        ):
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
        with manager.shared_effect(
            "binding-a", channel_id="dev", root=vault, timeout=2
        ):
            first_entered.set()
            first_release.wait(2)

    def exclusive() -> None:
        with manager.exclusive_change(
            "binding-a", channel_id="dev", root=vault, timeout=2
        ):
            exclusive_entered.set()

    shared_thread = threading.Thread(target=first_shared)
    exclusive_thread = threading.Thread(target=exclusive)
    shared_thread.start()
    assert first_entered.wait(1)
    exclusive_thread.start()
    assert manager.wait_for_exclusive_pending("binding-a", timeout=1)

    with pytest.raises(BindingEffectLeaseTimeout):
        with manager.shared_effect(
            "binding-a", channel_id="dev", root=vault, timeout=0.05
        ):
            pytest.fail("a new shared holder barged ahead of a pending exclusive")

    first_release.set()
    shared_thread.join(2)
    exclusive_thread.join(2)
    assert exclusive_entered.is_set()


def test_leases_for_distinct_bindings_do_not_serialise(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a", "binding-b")
    vault_a = tmp_path / "vaults" / "binding-a"
    vault_b = tmp_path / "vaults" / "binding-b"

    with manager.shared_effect(
        "binding-a", channel_id="dev", root=vault_a, timeout=1
    ):
        with manager.exclusive_change(
            "binding-b", channel_id="dev", root=vault_b, timeout=0.2
        ):
            assert manager.observe("binding-a").shared_count == 1
            assert manager.observe("binding-b").exclusive_held


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
        with manager.exclusive_change(
            "binding-a", channel_id="dev", root=vault, timeout=0.1
        ):
            pytest.fail("cross-process exclusive overlapped a shared holder")

    release.set()
    process.join(5)
    assert process.exitcode == 0
    with manager.exclusive_change(
        "binding-a", channel_id="dev", root=vault, timeout=1
    ):
        assert manager.observe("binding-a").exclusive_held
