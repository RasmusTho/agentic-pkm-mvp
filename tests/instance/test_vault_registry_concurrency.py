from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import pytest

import app.instance.vault_registry as registry_module
from app.instance.vault_registry import RegistryError, RegistryRevisionConflict, VaultRegistration, VaultRegistryStore


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


@pytest.mark.parametrize("interruption_artifact", ["snapshot", "checksum", "main"])
def test_restart_recovers_every_precommit_interruption(tmp_path, monkeypatch, interruption_artifact) -> None:
    path = tmp_path / f"interrupted-{interruption_artifact}.md"
    store = VaultRegistryStore(path)
    store.register(_registration(1))
    previous = {
        store.path: store.path.read_bytes(),
        store.snapshot_path: store.snapshot_path.read_bytes(),
        store.snapshot_checksum_path: store.snapshot_checksum_path.read_bytes(),
    }
    target = {
        "snapshot": store.snapshot_path,
        "checksum": store.snapshot_checksum_path,
        "main": store.path,
    }[interruption_artifact]
    real_write = registry_module._atomic_private_write

    def interrupt_after_write(candidate, payload):
        real_write(candidate, payload)
        if candidate == target:
            raise KeyboardInterrupt(f"crash after {interruption_artifact}")

    monkeypatch.setattr(registry_module, "_atomic_private_write", interrupt_after_write)
    with pytest.raises(KeyboardInterrupt, match=f"crash after {interruption_artifact}"):
        store.register(_registration(2), expected_revision=1)
    assert store.transaction_path.exists()
    assert store.transaction_path.stat().st_mode & 0o777 == 0o600

    monkeypatch.setattr(registry_module, "_atomic_private_write", real_write)
    recovered = VaultRegistryStore(path).load()
    assert recovered.revision == 1
    assert set(recovered.registrations) == {"binding-1"}
    assert not store.transaction_path.exists()
    for artifact, payload in previous.items():
        assert artifact.read_bytes() == payload


def test_restart_rolls_forward_after_committed_marker(tmp_path, monkeypatch) -> None:
    path = tmp_path / "committed-interruption.md"
    store = VaultRegistryStore(path)
    store.register(_registration(1))
    real_write = registry_module._atomic_private_write

    def interrupt_after_commit_marker(candidate, payload):
        real_write(candidate, payload)
        if candidate == store.transaction_path and b'"phase":"committed"' in payload:
            raise KeyboardInterrupt("crash after committed marker")

    monkeypatch.setattr(registry_module, "_atomic_private_write", interrupt_after_commit_marker)
    with pytest.raises(KeyboardInterrupt, match="crash after committed marker"):
        store.register(_registration(2), expected_revision=1)
    monkeypatch.setattr(registry_module, "_atomic_private_write", real_write)

    recovered = VaultRegistryStore(path).load()
    assert recovered.revision == 2
    assert set(recovered.registrations) == {"binding-1", "binding-2"}
    assert store.path.read_bytes() == store.snapshot_path.read_bytes()
    assert store.snapshot_checksum_path.read_text().strip() == registry_module.hashlib.sha256(
        store.path.read_bytes()
    ).hexdigest()
    assert not store.transaction_path.exists()


def test_corrupt_transaction_journal_fails_closed(tmp_path, monkeypatch) -> None:
    path = tmp_path / "corrupt-transaction.md"
    store = VaultRegistryStore(path)
    store.register(_registration(1))
    original = path.read_bytes()
    store.transaction_path.write_text('{"schema":')
    store.transaction_path.chmod(0o600)

    with pytest.raises(RegistryError, match="transaction journal is corrupt"):
        store.load()
    assert path.read_bytes() == original

    digest_path = tmp_path / "digest-transaction.md"
    digest_store = VaultRegistryStore(digest_path)
    digest_store.register(_registration(1))
    digest_original = digest_path.read_bytes()
    real_write = registry_module._atomic_private_write

    def interrupt_after_snapshot(candidate, payload):
        real_write(candidate, payload)
        if candidate == digest_store.snapshot_path:
            raise KeyboardInterrupt("leave prepared journal")

    with monkeypatch.context() as patch:
        patch.setattr(registry_module, "_atomic_private_write", interrupt_after_snapshot)
        with pytest.raises(KeyboardInterrupt, match="leave prepared journal"):
            digest_store.register(_registration(2), expected_revision=1)
    journal = json.loads(digest_store.transaction_path.read_text())
    journal["previous"]["main"]["sha256"] = "0" * 64
    digest_store.transaction_path.write_text(json.dumps(journal))
    digest_store.transaction_path.chmod(0o600)

    with pytest.raises(RegistryError, match="artifact digest is invalid"):
        digest_store.load()
    assert digest_path.read_bytes() == digest_original
