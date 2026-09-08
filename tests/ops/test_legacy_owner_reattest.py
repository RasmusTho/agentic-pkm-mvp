from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from app.instance import legacy_owner_recovery as recovery
from app.instance import runtime as runtime_module
from app.instance.instance_state import InstanceStateLayout
from app.instance.ownership_ledger import LegacyOwner, LedgerError, OwnershipLedger
from app.instance.runtime import InstanceRegistryRuntime
from app.instance.vault_registry import VaultRegistration
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.helpers.mvr01c_authority import establish_authority_window, finish_authority_window

pytestmark = pytest.mark.not_pg


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path):
    tmp_path = tmp_path.resolve()
    state = tmp_path / 'instance-state'
    state.mkdir(mode=0o700)
    root = tmp_path / 'vault'
    root.mkdir()
    runtime = InstanceRegistryRuntime(
        InstanceStateLayout.for_channel(state, 'dev'), OwnershipLedger(tmp_path / 'ownership'),
    )
    runtime.registry.register(
        VaultRegistration('binding-a', f'path:{root}', str(root)),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    runtime.ledger.bootstrap_legacy_owners(
        (LegacyOwner('dev', 'binding-a', root),), inventory_complete=True, writers_drained=True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    proof, inventory = establish_authority_window(runtime, tmp_path)
    original = json.loads(runtime.ledger.path.read_bytes())
    original['schema'] = 'agentic-pkm.host-ownership-ledger.v1'
    original['leases']['binding-a']['ancestor_fingerprints'] = ['f' * 64] * len(root.parents)
    runtime.ledger.path.write_text(json.dumps(original))
    proof_path = tmp_path / 'proof.json'
    proof_path.write_text(json.dumps({
        'channel_id': proof.channel_id, 'nonce': proof.nonce,
        'inventory_digest': proof.inventory_digest, 'lease_path': str(proof.lease_path),
        'controller': {'pid': proof.controller_pid, 'start_token': proof.controller_start_token},
        'owner_receipt_digest': proof.owner_receipt_digest,
    }))
    args = ['deployment-reattest-legacy-owner', '--channel', 'dev',
            '--instance-state-root', str(state), '--host-global-root', str(runtime.ledger.root),
            '--backup-root', str(tmp_path / 'backup'), '--quiescence-proof-path', str(proof_path),
            '--owner-receipt-path', str(inventory), '--vault-binding-id', 'binding-a',
            '--expected-ledger-sha256', _sha(runtime.ledger.path),
            '--expected-registry-sha256', _sha(runtime.registry.path),
            '--acknowledge-new-ownership-epoch']
    return runtime, args, proof, inventory


def _set(args, option, value):
    args[args.index(option) + 1] = str(value)


def _protected(runtime):
    return {p: p.read_bytes() for p in (runtime.ledger.path, runtime.ledger.key_path, runtime.registry.path)}


def test_cli_reattests_retained_dev_owner(tmp_path, capsys):
    runtime, args, proof, inventory = _fixture(tmp_path)
    before = _protected(runtime)
    assert runtime_module.main(args) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['activation'] == 'inactive_fenced'
    assert receipt['prior_effects'] == 'not_inferred'
    assert receipt['backup_verified']
    assert str(tmp_path) not in json.dumps(receipt)
    assert runtime.ledger.key_path.read_bytes() == before[runtime.ledger.key_path]
    assert runtime.registry.path.read_bytes() == before[runtime.registry.path]
    current = runtime.ledger.require_existing()
    lease = current.leases['binding-a']
    old_lease = json.loads(before[runtime.ledger.path])['leases']['binding-a']
    assert lease.root_fingerprint == old_lease['root_fingerprint']
    assert lease.sealed_root == old_lease['sealed_root']
    assert lease.owner_receipt_digest == proof.owner_receipt_digest
    assert runtime_module._deployment_fence_path(runtime.ledger.root, 'dev').exists()
    manifest = json.loads((tmp_path / 'backup' / 'manifest.json').read_bytes())
    assert manifest['epoch_id'] == receipt['epoch_id']
    for name, digest in manifest['checksums'].items():
        assert _sha(tmp_path / 'backup' / name) == digest
    finish_authority_window(runtime, tmp_path, proof, inventory)
    assert not runtime_module._deployment_fence_path(runtime.ledger.root, 'dev').exists()


@pytest.mark.parametrize('case', [
    'no_ack', 'stale_ledger', 'stale_registry', 'foreign_channel', 'wrong_binding',
    'stale_proof', 'changed_inventory', 'extra_owner', 'wrong_root', 'wrong_key',
    'active_registry', 'tombstone', 'transfer', 'rotation', 'backup_symlink',
    'backup_overlap', 'backup_public', 'backup_conflict', 'backup_artifact_symlink',
    'backup_lexical_vault',
])
def test_cli_refuses_unproved_or_changed_authority(tmp_path, capsys, case):
    runtime, args, proof, inventory = _fixture(tmp_path)
    if case == 'no_ack':
        args.remove('--acknowledge-new-ownership-epoch')
    elif case in {'stale_ledger', 'stale_registry'}:
        _set(args, '--expected-' + case.split('_')[1] + '-sha256', '0' * 64)
    elif case == 'foreign_channel':
        _set(args, '--channel', 'prod')
    elif case == 'wrong_binding':
        _set(args, '--vault-binding-id', 'foreign')
    elif case == 'stale_proof':
        proof_path = Path(args[args.index('--quiescence-proof-path') + 1])
        payload = json.loads(proof_path.read_bytes())
        payload['nonce'] = 'stale'
        proof_path.write_text(json.dumps(payload))
    elif case == 'changed_inventory':
        inventory.write_text('{}')
    elif case == 'active_registry':
        with runtime.registry._locked():
            snapshot = runtime.registry._read_current_locked(recover=False)
            extensions = dict(snapshot.extensions)
            extensions['scalarRollback'] = {
                'schema': 'agentic-pkm.scalar-rollback-floor.v1',
                'targetVaultBindingId': 'binding-a',
                'forkRegistryRevision': snapshot.revision,
                'gatewayPreflight': 'authenticated-mutation-filter',
                'nativeGuardPreflight': 'deny-by-default',
                'rollForwardLineage': 'agentic-pkm.scalar-roll-forward-lineage.v1',
                'composePolicySha256': 'a' * 64, 'gatewayPolicySha256': 'b' * 64,
                'nativeLauncherSha256': 'c' * 64,
            }
            runtime.registry._write_locked(replace(snapshot, authority='active', extensions=extensions))
        _set(args, '--expected-registry-sha256', _sha(runtime.registry.path))
    elif case == 'rotation':
        runtime.ledger.rotation_path.write_text('{}')
        runtime.ledger.rotation_path.chmod(0o600)
    elif case.startswith('backup_'):
        backup = tmp_path / 'backup'
        if case == 'backup_symlink':
            backup.symlink_to(runtime.ledger.root, target_is_directory=True)
        elif case == 'backup_overlap':
            _set(args, '--backup-root', runtime.ledger.root / 'backup')
        elif case == 'backup_artifact_symlink':
            backup.mkdir(mode=0o700)
            (backup / 'ownership-key.json').symlink_to(runtime.ledger.key_path)
        elif case == 'backup_lexical_vault':
            root = tmp_path / 'vault'
            (tmp_path / 'alias-parent').mkdir()
            lexical = tmp_path / 'alias-parent' / '..' / 'vault'
            _set(args, '--backup-root', root / 'backup')
            # Registry spellings cannot widen the protected physical-root boundary.
            with runtime.registry._locked():
                snapshot = runtime.registry._read_current_locked(recover=False)
                reg = snapshot.registrations['binding-a']
                runtime.registry._write_locked(replace(snapshot, registrations={
                    'binding-a': replace(reg, path=str(lexical)),
                }))
            _set(args, '--expected-registry-sha256', _sha(runtime.registry.path))
        elif case == 'backup_public':
            backup.mkdir(mode=0o755)
        else:
            backup.mkdir(mode=0o700)
            (backup / 'unknown').write_text('unrelated')
    elif case == 'wrong_key':
        payload = json.loads(runtime.ledger.key_path.read_bytes())
        payload['secret'] = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='
        runtime.ledger.key_path.write_text(json.dumps(payload))
    else:
        payload = json.loads(runtime.ledger.path.read_bytes())
        lease = payload['leases']['binding-a']
        if case == 'extra_owner':
            payload['leases']['foreign'] = lease | {'vault_binding_id': 'foreign', 'channel_id': 'prod'}
        elif case == 'wrong_root':
            lease['root_fingerprint'] = '0' * 64
        elif case == 'tombstone':
            payload['tombstones']['retired'] = lease | {'vault_binding_id': 'retired', 'state': 'retired'}
        elif case == 'transfer':
            payload['transfer'] = {'invalid': True}
        runtime.ledger.path.write_text(json.dumps(payload))
        _set(args, '--expected-ledger-sha256', _sha(runtime.ledger.path))
    before = _protected(runtime)
    assert runtime_module.main(args) == 1
    assert 'refused' in capsys.readouterr().out
    assert _protected(runtime) == before
    assert runtime_module._deployment_fence_path(runtime.ledger.root, 'dev').exists()


@pytest.mark.parametrize('point', ['backup', 'before_ledger', 'after_ledger'])
def test_interrupted_reattest_replays_exact_transition(tmp_path, monkeypatch, capsys, point):
    runtime, args, proof, inventory = _fixture(tmp_path)
    before = _protected(runtime)
    original_write = OwnershipLedger._write_ledger_locked
    original_backup = recovery._atomic_private_write
    triggered = False

    def crash_write(self, candidate, key):
        if point == 'after_ledger':
            original_write(self, candidate, key)
        raise OSError('simulated interruption')

    def crash_backup(path, payload):
        nonlocal triggered
        original_backup(path, payload)
        if not triggered:
            triggered = True
            raise OSError('simulated backup interruption')

    if point == 'backup':
        monkeypatch.setattr(recovery, '_atomic_private_write', crash_backup)
    else:
        monkeypatch.setattr(OwnershipLedger, '_write_ledger_locked', crash_write)
    assert runtime_module.main(args) == 1
    if point != 'after_ledger':
        assert _protected(runtime) == before
    else:
        assert (tmp_path / 'backup' / 'manifest.json').is_file()
    monkeypatch.setattr(OwnershipLedger, '_write_ledger_locked', original_write)
    monkeypatch.setattr(recovery, '_atomic_private_write', original_backup)
    capsys.readouterr()
    assert runtime_module.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert runtime_module.main(args) == 0
    assert json.loads(capsys.readouterr().out) == first
    # A valid-looking changed registry is still not the receipt-bound transition.
    stale = args.copy()
    _set(stale, '--expected-registry-sha256', 'f' * 64)
    assert runtime_module.main(stale) == 1
    assert runtime.ledger.key_path.read_bytes() == before[runtime.ledger.key_path]
    assert (tmp_path / 'backup' / 'ownership-ledger.json').read_bytes() == before[runtime.ledger.path]
    assert runtime_module._deployment_fence_path(runtime.ledger.root, 'dev').exists()


def test_normal_authentication_stays_fail_closed(tmp_path):
    runtime, args, proof, inventory = _fixture(tmp_path)
    before = _protected(runtime)
    with pytest.raises(LedgerError):
        runtime.ledger.require_existing()
    owners = runtime_module._load_legacy_owner_inventory(
        inventory, registry=runtime.registry.load(), channel='dev', quiescence_proof=proof,
    )
    with pytest.raises(LedgerError, match='not registry-authenticated'):
        runtime.ledger.require_registry_consistency(
            channel_id='dev', registrations={'binding-a': None}, tombstones={},
            transfer_lineage=(), global_live_owners=owners, require_materialized_roots=False,
        )
    assert _protected(runtime) == before
    assert runtime_module.main(args) == 0
    finish_authority_window(runtime, tmp_path, proof, inventory)
    assert runtime.ledger.require_existing().schema == 'agentic-pkm.host-ownership-ledger.v2'


@pytest.mark.parametrize('change', ['registry', 'epoch', 'manifest', 'backup'])
def test_receipt_rejects_changed_replay_authority(tmp_path, monkeypatch, change):
    runtime, args, proof, inventory = _fixture(tmp_path)
    original_write = OwnershipLedger._write_ledger_locked

    def crash(self, candidate, key):
        if change == 'epoch':
            original_write(self, candidate, key)
        raise OSError('interrupted after convergence receipt')

    monkeypatch.setattr(OwnershipLedger, '_write_ledger_locked', crash)
    assert runtime_module.main(args) == 1
    monkeypatch.setattr(OwnershipLedger, '_write_ledger_locked', original_write)
    if change == 'registry':
        with runtime.registry._locked():
            snapshot = runtime.registry._read_current_locked(recover=False)
            runtime.registry._write_locked(replace(snapshot, revision=snapshot.revision + 1))
        _set(args, '--expected-registry-sha256', _sha(runtime.registry.path))
    elif change == 'epoch':
        runtime_module._release_instance_state_deployment_lease(
            channel='dev', host_global_root=runtime.ledger.root,
            controller_pid=proof.controller_pid, controller_start_token=proof.controller_start_token,
        )
        # Same owner and root, genuinely new canonical lease and inventory receipt.
        fresh, inventory = establish_authority_window(runtime, tmp_path)
        assert fresh.nonce != proof.nonce
        proof_path = Path(args[args.index('--quiescence-proof-path') + 1])
        payload = json.loads(proof_path.read_bytes())
        payload.update(nonce=fresh.nonce, owner_receipt_digest=fresh.owner_receipt_digest,
                       inventory_digest=fresh.inventory_digest)
        proof_path.write_text(json.dumps(payload))
    elif change == 'manifest':
        path = tmp_path / 'backup' / 'manifest.json'
        payload = json.loads(path.read_bytes())
        payload['epoch_id'] = 'forged'
        path.write_text(json.dumps(payload))
    else:
        (tmp_path / 'backup' / 'ownership-key.json').write_text('{}')
    before = _protected(runtime)
    assert runtime_module.main(args) == 1
    assert _protected(runtime) == before
    assert runtime_module._deployment_fence_path(runtime.ledger.root, 'dev').exists()


def test_backup_overlap_uses_canonical_protected_roots(tmp_path):
    (tmp_path / 'vault').mkdir()
    (tmp_path / 'alias-parent').mkdir()
    lexical = tmp_path / 'alias-parent' / '..' / 'vault'
    with pytest.raises(runtime_module.InstanceStatePreflightError):
        recovery._backup_destination(tmp_path / 'vault' / 'backup', (lexical,))
    assert not (tmp_path / 'vault' / 'backup').exists()


@pytest.mark.parametrize('journal', ['rotation', 'registry_transaction'])
def test_cli_refuses_journal_created_while_waiting_for_lock(tmp_path, monkeypatch, journal):
    runtime, args, proof, inventory = _fixture(tmp_path)
    before = _protected(runtime)
    lock = OwnershipLedger._locked
    journal_path = runtime.ledger.rotation_path if journal == 'rotation' else runtime.registry.transaction_path

    @contextmanager
    def concurrent_journal(self, **kwargs):
        # Another writer crashes just before this call wins the ledger lock.
        journal_path.write_text('{}')
        journal_path.chmod(0o600)
        with lock(self, **kwargs):
            yield

    monkeypatch.setattr(OwnershipLedger, '_locked', concurrent_journal)
    assert runtime_module.main(args) == 1
    assert _protected(runtime) == before
    assert journal_path.read_text() == '{}'
    assert not (tmp_path / 'backup').exists()


@pytest.mark.parametrize("artifact", ["rollback_export_path", "snapshot_path", "snapshot_checksum_path"])
@pytest.mark.parametrize("damage", ["missing", "stale"])
@pytest.mark.parametrize("stale_expected_digest", [False, True])
def test_cli_refuses_damaged_registry_artifacts_without_healing(
    tmp_path, artifact, damage, stale_expected_digest,
):
    runtime, args, _, _ = _fixture(tmp_path)
    path = getattr(runtime.registry, artifact)
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"retained damaged evidence\n")
    if stale_expected_digest:
        _set(args, "--expected-registry-sha256", "0" * 64)
    protected = [runtime.ledger.path, runtime.ledger.key_path, runtime.registry.path,
                 runtime.registry.rollback_export_path, runtime.registry.snapshot_path,
                 runtime.registry.snapshot_checksum_path]
    before = {p: p.read_bytes() if p.exists() else None for p in protected}
    assert runtime_module.main(args) == 1
    assert {p: p.read_bytes() if p.exists() else None for p in protected} == before
    assert not (tmp_path / "backup").exists()
    assert runtime_module._deployment_fence_path(runtime.ledger.root, "dev").exists()
