from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import pytest

from app.instance.vault_registry import RegistryRevisionConflict, VaultRegistration, VaultRegistryStore


def _registration(index: int) -> VaultRegistration:
    return VaultRegistration(
        vault_binding_id=f"binding-{index}",
        ref=f"path:/vault/{index}",
        path=f"/vault/{index}",
        vault_id=f"vault-{index}",
        local_instance_id=f"clone-{index}",
    )


def _process_register(path: str, index: int) -> None:
    VaultRegistryStore(Path(path)).register(_registration(index))


def test_production_mutations_are_locked_atomic_and_revision_checked(tmp_path) -> None:
    path = tmp_path / "vault-registry.md"
    store = VaultRegistryStore(path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: VaultRegistryStore(path).register(_registration(index)), range(8)))

    loaded = store.load()
    assert loaded.revision == 8
    assert len(loaded.registrations) == 8

    with pytest.raises(RegistryRevisionConflict, match="expected revision 0"):
        store.register(_registration(99), expected_revision=0)
    assert store.load().revision == 8

    process_path = tmp_path / "process-registry.md"
    context = get_context("spawn")
    processes = [context.Process(target=_process_register, args=(str(process_path), index)) for index in range(4)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    assert VaultRegistryStore(process_path).load().revision == 4
    assert len(VaultRegistryStore(process_path).load().registrations) == 4
