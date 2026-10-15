from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.instance import legacy_owner_recovery as recovery
from app.instance import runtime as rt
from app.instance.instance_state import InstanceStateLayout, InstanceStatePreflightError
from app.instance.ownership_ledger import OwnershipLedger
from app.instance.vault_registry import VaultRegistration
from scripts import instance_state_writer_inventory as inventory
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

pytestmark = pytest.mark.not_pg


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value))
    path.chmod(0o600)


def fixture(tmp_path: Path, controller_pid: int | None = None):
    base = tmp_path.resolve()
    state, host, content = (base / name for name in ('state', 'host', 'content'))
    for root in (state, host, content):
        root.mkdir(mode=0o700)
    (content / 'source.md').write_text('retained source bytes\n')
    runtime = rt.InstanceRegistryRuntime(InstanceStateLayout.for_channel(state, 'test'), OwnershipLedger(host))
    runtime.layout.ensure()
    runtime.registry.register(VaultRegistration('retained', f'path:{content}', str(content),
        vault_id='vault-retained', local_instance_id='instance-retained'),
        _capability=STORAGE_MUTATION_CAPABILITY)
    controller_pid = controller_pid or os.getpid()
    controller = {'pid': controller_pid, 'start_token': inventory.controller_token(controller_pid)}
    rt._begin_instance_state_deployment(channel='test', instance_state_root=state,
        host_global_root=host, legacy_path=base / 'absent.md', controller_pid=controller['pid'],
        controller_start_token=controller['start_token'])
    domains = {domain: [] for domain in ('dev', 'native', 'prod', 'test')}
    empty = rt._canonical_json_digest(domains)
    namespace = inventory.controller_namespace_digest(os.getpid())
    write(host / 'deployment-quiescence-inventory.json', {
        'schema': rt._QUIESCENCE_INVENTORY_SCHEMA, 'inventory_complete': True,
        'all_consumers_stopped': True, 'probe_count': 2, 'controller': controller,
        'controller_namespace_digest': namespace, 'domains': domains,
        'snapshot_digests': [empty, empty],
    })
    rt._prove_instance_state_quiescence(channel='test', host_global_root=host,
        inventory_path=host / 'deployment-quiescence-inventory.json')
    identity, ancestors, physical = inventory._owner_identity_material(content, domain='test', source='fixture')
    owners = [{'channel_id': 'test', 'root': str(content)}]
    sources = {'docker': ['docker:empty'], 'config': ['a' * 64], 'owners': owners,
        'owner_identities': [{'channel_id': 'test', 'root': str(content), 'identity': identity,
            'ancestor_identities': sorted(ancestors), 'legacy_ancestor_identities': list(physical)}]}
    receipt = host / 'legacy-owner-inventory.json'
    write(receipt, {'schema': rt._LEGACY_INVENTORY_SCHEMA, 'inventory_complete': True,
        'writers_drained': True, 'source_probe_count': 2, 'validated_after_quiescence': True,
        'source_evidence': sources, 'owners': owners, 'source_digest': rt._canonical_json_digest(sources)})
    rt._bind_test_owner_proof(channel='test', instance_state_root=state, host_global_root=host,
        owner_receipt_path=receipt, expected_owner_receipt_sha256=sha(receipt),
        quiescence_proof_path=host / 'deployment-quiescence-proof.json')
    args = dict(channel='test', instance_state_root=state, host_global_root=host,
        vault_binding_id='retained', expected_registry_sha256=sha(runtime.registry.path),
        owner_receipt_path=receipt, expected_owner_receipt_sha256=sha(receipt),
        quiescence_proof_path=host / 'deployment-quiescence-proof.json',
        backup_root=base / 'backup', acknowledge_new_ownership_epoch=True)
    return runtime, args, content


def initialize(args):
    return recovery.initialize_dormant_ownership(**args)


def test_exact_admission_preserves_source_and_registry_and_produces_one_authenticated_lease(tmp_path):
    runtime, args, content = fixture(tmp_path)
    before = runtime.registry.path.read_bytes(), (content / 'source.md').read_bytes()
    result = initialize(args)
    assert result['prepared'] is True
    assert result['activation'] == 'inactive_fenced'
    assert initialize(args) == result
    current = runtime.ledger.require_existing()
    assert set(current.leases) == {'retained'}
    assert current.leases['retained'].channel_id == 'test'
    assert (runtime.registry.path.read_bytes(), (content / 'source.md').read_bytes()) == before
    assert rt._deployment_fence_path(runtime.ledger.root, 'test').exists()


@pytest.mark.parametrize('change', ['ack', 'channel', 'binding', 'registry', 'receipt',
    'partial_key', 'partial_ledger', 'transaction', 'rotation', 'missing_source',
    'unsafe_host', 'foreign_owner', 'ancestor', 'tombstone'])
def test_refusal_matrix_is_before_effects(tmp_path, change):
    runtime, args, _ = fixture(tmp_path)
    key = {'ack': 'acknowledge_new_ownership_epoch', 'channel': 'channel',
        'binding': 'vault_binding_id', 'registry': 'expected_registry_sha256',
        'receipt': 'expected_owner_receipt_sha256'}.get(change)
    if key:
        args[key] = False if change == 'ack' else ('prod' if change == 'channel' else 'wrong')
    elif change in {'partial_key', 'partial_ledger', 'transaction', 'rotation'}:
        path = {'partial_key': runtime.ledger.key_path, 'partial_ledger': runtime.ledger.path,
            'transaction': runtime.registry.transaction_path, 'rotation': runtime.ledger.rotation_path}[change]
        write(path, {})
    elif change == 'unsafe_host':
        runtime.ledger.root.chmod(0o755)
    elif change == 'missing_source':
        (Path(runtime.registry.load().registrations['retained'].path) / 'source.md').unlink()
        Path(runtime.registry.load().registrations['retained'].path).rmdir()
    elif change == 'tombstone':
        from dataclasses import replace
        from app.instance.vault_registry import RemovalTombstone
        with runtime.registry._locked(recover_transactions=False):
            current = runtime.registry._read_current_locked(recover=False)
            retired = RemovalTombstone('retired', 'path:retired', str(tmp_path / 'retired'),
                'old-vault', 'old-instance', 1)
            runtime.registry._write_locked(replace(current, removal_tombstones={'retired': retired}))
        args['expected_registry_sha256'] = sha(runtime.registry.path)
    else:
        receipt = args['owner_receipt_path']
        value = json.loads(receipt.read_bytes())
        if change == 'foreign_owner':
            value['owners'][0]['channel_id'] = 'prod'
        else:
            value['source_evidence']['owner_identities'][0]['legacy_ancestor_identities'] = []
        write(receipt, value)
        args['expected_owner_receipt_sha256'] = sha(receipt)
    before = runtime.registry.path.read_bytes()
    with pytest.raises(InstanceStatePreflightError):
        initialize(args)
    assert runtime.ledger.key_path.exists() == (change == 'partial_key')
    assert runtime.ledger.path.exists() == (change == 'partial_ledger')
    assert not args['backup_root'].exists()
    assert runtime.registry.path.read_bytes() == before


def test_concurrency_and_stale_proof_recheck_all_locks(tmp_path):
    runtime, args, _ = fixture(tmp_path)
    proof = args['quiescence_proof_path']
    value = json.loads(proof.read_bytes())
    write(proof, value | {'nonce': 'stale'})
    with pytest.raises(InstanceStatePreflightError):
        initialize(args)
    assert not runtime.ledger.key_path.exists()
    write(proof, value)
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            result = initialize(args)
            os.write(write_fd, json.dumps(result).encode())
        finally:
            os._exit(0)
    os.close(write_fd)
    parent_result = initialize(args)
    child_result = json.loads(os.read(read_fd, 8192))
    os.close(read_fd)
    assert os.waitpid(pid, 0)[1] == 0
    assert parent_result == child_result
    assert len(list(args['backup_root'].parent.glob('backup'))) == 1


@pytest.mark.parametrize('target', ['state', 'host', 'state_child', 'host_child'])
def test_content_and_authority_roots_refuse_overlap_before_effects(tmp_path, target):
    from dataclasses import replace
    runtime, args, _ = fixture(tmp_path)
    root = args['instance_state_root'] if target.startswith('state') else runtime.ledger.root
    if target.endswith('child'):
        root = root / 'nested'
        root.mkdir()
    with runtime.registry._locked(recover_transactions=False):
        current = runtime.registry._read_current_locked(recover=False)
        reg = replace(current.registrations['retained'], path=str(root))
        runtime.registry._write_locked(replace(current, registrations={'retained': reg}))
    args['expected_registry_sha256'] = sha(runtime.registry.path)
    with pytest.raises(InstanceStatePreflightError):
        initialize(args)
    assert not runtime.ledger.key_path.exists() and not args['backup_root'].exists()


@pytest.mark.parametrize('target', ['content', 'state', 'host'])
def test_backup_physical_aliases_refuse_before_staging(tmp_path, target):
    runtime, args, content = fixture(tmp_path)
    root = {'content': content, 'state': args['instance_state_root'], 'host': runtime.ledger.root}[target]
    alias = args['backup_root'].parent / 'alias'
    alias.symlink_to(root, target_is_directory=True)
    args['backup_root'] = alias / 'backup'
    with pytest.raises(InstanceStatePreflightError):
        initialize(args)
    assert not runtime.ledger.key_path.exists() and not (root / 'backup').exists()


def test_physical_ancestor_changes_refuse_before_effects(tmp_path, monkeypatch):
    runtime, args, _ = fixture(tmp_path)
    original = recovery.require_test_controller
    observed = 0
    def race(proof, roots):
        nonlocal observed
        original(proof, roots)
        observed += 1
        if observed == 2:
            args['instance_state_root'].chmod(0o750)
    monkeypatch.setattr(recovery, 'require_test_controller', race)
    with pytest.raises(InstanceStatePreflightError):
        initialize(args)
    assert not runtime.ledger.key_path.exists()


@pytest.mark.parametrize('cause', ['dead', 'namespace'])
def test_dead_controller_and_unqualified_namespace_refuse_before_effects(tmp_path, monkeypatch, cause):
    runtime, args, _ = fixture(tmp_path)
    if cause == 'namespace':
        monkeypatch.setattr(inventory, 'controller_namespace_digest', lambda *a: '0' * 64)
    else:
        def unavailable(*a):
            raise inventory.InventoryError('controller unavailable')
        monkeypatch.setattr(inventory, 'controller_token', unavailable)
    with pytest.raises(InstanceStatePreflightError):
        initialize(args)
    assert not runtime.ledger.key_path.exists() and not args['backup_root'].exists()


def crash_before_key(runtime, monkeypatch):
    original = recovery._atomic_private_write
    def crash(path, payload):
        if path == runtime.ledger.key_path:
            raise OSError('injected before key')
        original(path, payload)
    monkeypatch.setattr(recovery, '_atomic_private_write', crash)
    return original


def test_prepared_package_reservation_cannot_escape_to_alternate_destination(tmp_path, monkeypatch):
    runtime, args, _ = fixture(tmp_path)
    crash_before_key(runtime, monkeypatch)
    with pytest.raises(OSError):
        initialize(args)
    epoch = json.loads((args['backup_root'] / 'manifest.json').read_bytes())['dormant_ownership']['epoch_id']
    args['backup_root'] = args['backup_root'].parent / 'different'
    with pytest.raises(InstanceStatePreflightError):
        initialize(args)
    assert not args['backup_root'].exists() and not runtime.ledger.key_path.exists()
    assert recovery.read_preparation_reservation(runtime.ledger.root)['epoch_id'] == epoch


def test_proof_republication_cannot_erase_a_partial_preparation_reservation(tmp_path, monkeypatch):
    runtime, args, _ = fixture(tmp_path)
    original = rt._replace_private_json
    def fail(path, value):
        original(path, value)
        if recovery._PREPARATION in value:
            raise OSError('after first reservation')
    monkeypatch.setattr(rt, '_replace_private_json', fail)
    with pytest.raises(OSError):
        initialize(args)
    reserved = recovery.read_preparation_reservation(runtime.ledger.root)
    monkeypatch.setattr(rt, '_replace_private_json', original)
    with pytest.raises(InstanceStatePreflightError):
        rt._prove_instance_state_quiescence(channel='test', host_global_root=runtime.ledger.root,
            inventory_path=runtime.ledger.root / 'deployment-quiescence-inventory.json')
    assert recovery.read_preparation_reservation(runtime.ledger.root) == reserved
    assert initialize(args)['epoch_id'] == reserved['epoch_id']


def test_partial_canonical_reservation_resumes_exact_durable_sibling_package(tmp_path, monkeypatch):
    test_proof_republication_cannot_erase_a_partial_preparation_reservation(tmp_path, monkeypatch)


def test_reserved_missing_package_stays_indeterminate_without_reminting(tmp_path, monkeypatch):
    runtime, args, _ = fixture(tmp_path)
    crash_before_key(runtime, monkeypatch)
    with pytest.raises(OSError):
        initialize(args)
    reserved = recovery.read_preparation_reservation(runtime.ledger.root)
    args['backup_root'].rename(args['backup_root'].with_name('retained-away'))
    with pytest.raises(InstanceStatePreflightError):
        initialize(args)
    assert recovery.read_preparation_reservation(runtime.ledger.root) == reserved
    assert not runtime.ledger.key_path.exists()


@pytest.mark.parametrize('operation', ['begin', 'release', 'cleanup', 'finish'])
def test_pending_preparation_fence_survives_begin_release_and_finalization(tmp_path, monkeypatch, operation):
    runtime, args, _ = fixture(tmp_path)
    crash_before_key(runtime, monkeypatch)
    with pytest.raises(OSError):
        initialize(args)
    reserved = recovery.read_preparation_reservation(runtime.ledger.root)
    proof = rt._load_deployment_quiescence_proof(args['quiescence_proof_path'])
    with pytest.raises(InstanceStatePreflightError):
        if operation == 'begin':
            rt._begin_instance_state_deployment(channel='test', instance_state_root=args['instance_state_root'],
                host_global_root=runtime.ledger.root, legacy_path=tmp_path / 'absent',
                controller_pid=proof.controller_pid, controller_start_token=proof.controller_start_token)
        elif operation == 'release':
            rt._release_instance_state_deployment_lease(channel='test', host_global_root=runtime.ledger.root,
                controller_pid=proof.controller_pid, controller_start_token=proof.controller_start_token)
        elif operation == 'cleanup':
            rt._complete_instance_state_deployment_cleanup(runtime.ledger.root)
        else:
            rt._finish_instance_state_deployment(channel='test', instance_state_root=args['instance_state_root'],
                host_global_root=runtime.ledger.root, legacy_path=tmp_path / 'absent',
                inventory_path=args['owner_receipt_path'], backup_root=tmp_path / 'ordinary',
                restore_root=None, quiescence_proof=proof)
    assert recovery.read_preparation_reservation(runtime.ledger.root) == reserved
    assert rt._deployment_fence_path(runtime.ledger.root, 'test').exists()


def test_published_package_retry_completes_directory_durability_before_authority(tmp_path, monkeypatch):
    runtime, args, _ = fixture(tmp_path)
    original = recovery._fsync_directory
    blocked = True
    parent_attempts = 0
    def barrier(path):
        nonlocal parent_attempts
        if path == args['backup_root'].parent and args['backup_root'].exists():
            parent_attempts += 1
            if blocked:
                raise OSError('package parent barrier unavailable')
        original(path)
    monkeypatch.setattr(recovery, '_fsync_directory', barrier)
    for _ in range(2):
        with pytest.raises(OSError):
            initialize(args)
        assert not runtime.ledger.key_path.exists()
    assert parent_attempts == 2
    blocked = False
    assert initialize(args)['prepared']


@pytest.mark.parametrize('point', ['reservation', 'key', 'ledger'])
def test_all_reservation_and_canonical_directory_barriers_repeat_on_retry(tmp_path, monkeypatch, point):
    runtime, args, _ = fixture(tmp_path)
    original = recovery._fsync_directory
    failed = False
    calls = []
    def barrier(path):
        nonlocal failed
        calls.append(path)
        eligible = ((point == 'reservation' and path == runtime.ledger.root / 'deployment-public')
            or (point == 'key' and path == runtime.ledger.root and runtime.ledger.key_path.exists() and not runtime.ledger.path.exists())
            or (point == 'ledger' and path == runtime.ledger.root and runtime.ledger.path.exists()))
        if eligible and not failed:
            failed = True
            raise OSError('directory barrier unavailable')
        original(path)
    monkeypatch.setattr(recovery, '_fsync_directory', barrier)
    with pytest.raises(OSError):
        initialize(args)
    reserved = recovery.read_preparation_reservation(runtime.ledger.root)
    calls.clear()
    assert initialize(args)['epoch_id'] == reserved['epoch_id']
    assert runtime.ledger.root in calls and runtime.ledger.root / 'deployment-public' in calls


def test_completed_pair_requires_durability_before_safety_cleanup(tmp_path, monkeypatch):
    runtime, args, _ = fixture(tmp_path)
    initialize(args)
    original = recovery._fsync_directory
    def fail(path):
        if path == runtime.ledger.root:
            raise OSError('canonical barrier unavailable')
        original(path)
    monkeypatch.setattr(recovery, '_fsync_directory', fail)
    proof = rt._load_deployment_quiescence_proof(args['quiescence_proof_path'])
    with pytest.raises(InstanceStatePreflightError):
        rt._release_instance_state_deployment_lease(channel='test', host_global_root=runtime.ledger.root,
            controller_pid=proof.controller_pid, controller_start_token=proof.controller_start_token)
    assert rt._deployment_fence_path(runtime.ledger.root, 'test').exists()
    monkeypatch.setattr(recovery, '_fsync_directory', original)
    assert rt._release_instance_state_deployment_lease(channel='test', host_global_root=runtime.ledger.root,
        controller_pid=proof.controller_pid, controller_start_token=proof.controller_start_token)['released']


def test_crash_fence_resumes_only_same_prepared_epoch(tmp_path, monkeypatch):
    runtime, args, _ = fixture(tmp_path)
    original = recovery._atomic_private_write
    def crash(path, payload):
        original(path, payload)
        if path == runtime.ledger.key_path:
            raise OSError('injected after key publication')
    monkeypatch.setattr(recovery, '_atomic_private_write', crash)
    with pytest.raises(OSError):
        initialize(args)
    manifest = (args['backup_root'] / 'manifest.json').read_bytes()
    monkeypatch.setattr(recovery, '_atomic_private_write', original)
    result = initialize(args)
    assert (args['backup_root'] / 'manifest.json').read_bytes() == manifest
    assert result['epoch_id'] == json.loads(manifest)['dormant_ownership']['epoch_id']


def test_initializer_output_and_effect_scope_are_bounded(tmp_path, capsys):
    runtime, args, content = fixture(tmp_path)
    result = initialize(args)
    output = json.dumps(result)
    key = json.loads(runtime.ledger.key_path.read_bytes())
    assert str(tmp_path) not in output and key['secret'] not in output
    assert sha(runtime.ledger.key_path) not in output
    assert 'retained source bytes' not in output
    assert result['activation'] == 'inactive_fenced'
    assert runtime.registry.load().authority == 'dormant'
    assert (content / 'source.md').read_text() == 'retained source bytes\n'
    cli = ['deployment-initialize-dormant-ownership']
    for name, value in args.items():
        cli.append('--' + name.replace('_', '-'))
        if not isinstance(value, bool):
            cli.append(str(value))
    assert rt.main(cli) == 0
    assert json.loads(capsys.readouterr().out) == result
    cli[cli.index('--channel') + 1] = 'prod'
    assert rt.main(cli) == 1
    refusal = capsys.readouterr().out
    assert json.loads(refusal)['outcome'] == 'refused'
    assert str(tmp_path) not in refusal and key['secret'] not in refusal


def test_prospective_destination_change_refuses_before_staging(tmp_path, monkeypatch):
    runtime, args, content = fixture(tmp_path)
    original = recovery.require_test_controller
    observations = 0
    def race(proof, roots):
        nonlocal observations
        original(proof, roots)
        observations += 1
        if observations == 2:
            args['backup_root'].symlink_to(content, target_is_directory=True)
    monkeypatch.setattr(recovery, 'require_test_controller', race)
    with pytest.raises(InstanceStatePreflightError):
        initialize(args)
    assert not list(args['backup_root'].parent.glob('.backup-prepared-*'))
    assert not runtime.ledger.key_path.exists() and not runtime.ledger.path.exists()


def test_geometry_safe_sibling_and_symmetric_aliases(tmp_path):
    root = tmp_path.resolve()
    left, right = root / 'left', root / 'right'
    left.mkdir()
    right.mkdir()
    child = left / 'child'
    child.mkdir()
    a, b, c = (recovery._capture_geometry(p) for p in (left, right, child))
    assert not recovery._overlaps(a, b)
    assert recovery._overlaps(a, c) and recovery._overlaps(c, a)
    assert recovery._overlaps(a, a)
    alias = root / 'alias'
    alias.symlink_to(left, target_is_directory=True)
    with pytest.raises(InstanceStatePreflightError):
        recovery._capture_geometry(alias)


def test_exited_unreaped_controller_refuses_before_effects(tmp_path):
    import time
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(write_fd)
        os.read(read_fd, 1)
        os._exit(0)
    os.close(read_fd)
    try:
        runtime, args, _ = fixture(tmp_path, controller_pid=pid)
        os.write(write_fd, b'x')
        os.close(write_fd)
        # Do not reap until after observing the native zombie state.
        deadline = time.monotonic() + 3
        while True:
            try:
                inventory.controller_namespace_digest(pid)
            except (inventory.InventoryError, ProcessLookupError):
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        with pytest.raises(InstanceStatePreflightError):
            initialize(args)
        assert not runtime.ledger.key_path.exists() and not args['backup_root'].exists()
    finally:
        try:
            os.close(write_fd)
        except OSError:
            pass
        os.waitpid(pid, 0)


def test_operation_specific_evidence_is_not_an_ordinary_rotation_journal(tmp_path):
    from app.instance.ownership_ledger import LedgerKeyError, ROTATION_SCHEMA
    ledger = OwnershipLedger(tmp_path.resolve() / 'host')
    ledger.load()
    key_before, ledger_before = ledger.key_path.read_bytes(), ledger.path.read_bytes()
    write(ledger.rotation_path, {'schema': ROTATION_SCHEMA,
        'key': json.loads(key_before), 'ledger': json.loads(ledger_before),
        'dormant_ownership': {'decision': 'explicit-new-ownership-epoch'}})
    with pytest.raises(LedgerKeyError):
        ledger.load()
    assert ledger.key_path.read_bytes() == key_before
    assert ledger.path.read_bytes() == ledger_before
    assert ledger.rotation_path.exists()


def test_operation_specific_evidence_is_not_a_generic_restore(tmp_path):
    from app.instance.instance_state import InstanceStateBackup
    from tests.helpers.mvr01c_authority import establish_authority_window
    root = tmp_path.resolve()
    state = root / 'state'
    state.mkdir(mode=0o700)
    content = root / 'content'
    content.mkdir()
    runtime = rt.InstanceRegistryRuntime(InstanceStateLayout.for_channel(state, 'test'),
        OwnershipLedger(root / 'host'))
    runtime.layout.ensure()
    runtime.registry.register(VaultRegistration('binding', f'path:{content}', str(content)),
        _capability=STORAGE_MUTATION_CAPABILITY)
    from app.instance.ownership_ledger import LegacyOwner
    runtime.ledger.bootstrap_legacy_owners([LegacyOwner('test', 'binding', content)],
        inventory_complete=True, writers_drained=True, _capability=STORAGE_MUTATION_CAPABILITY)
    proof, owners = establish_authority_window(runtime, root)
    backup = InstanceStateBackup(runtime.layout, runtime.ledger)
    destination = root / 'backup'
    backup.create(destination, quiescence_proof=proof, owner_receipt_path=owners)
    manifest = destination / 'manifest.json'
    write(manifest, json.loads(manifest.read_bytes()) | {'dormant_ownership': {}})
    before = runtime.registry.path.read_bytes(), runtime.ledger.path.read_bytes(), runtime.ledger.key_path.read_bytes()
    with pytest.raises(InstanceStatePreflightError):
        backup.restore(destination, quiescence_proof=proof, owner_receipt_path=owners)
    assert (runtime.registry.path.read_bytes(), runtime.ledger.path.read_bytes(), runtime.ledger.key_path.read_bytes()) == before


@pytest.mark.parametrize('scenario', ['exact', 'foreign_owner', 'dirty_source', 'runtime_uid'])
def test_test_preparation_producer_holds_window_until_explicit_initializer(tmp_path, scenario):
    """Real shell -> native qualify/begin/prove/bind/initialize/release.

    Only external host/config discovery, stopped-service transport and PostgreSQL
    readback are fixtures. Canonical two-pass producers, actual OS controller
    identity/namespace, runtime authority and filesystem writes are real.
    """
    root = tmp_path.resolve()
    source = Path(__file__).resolve().parents[2]
    candidate = root / 'candidate'
    candidate.mkdir()
    for name in ('app', 'scripts', 'docs/settings'):
        shutil.copytree(source / name, candidate / name,
            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('.gitignore', 'docker-compose.yaml', 'pyproject.toml'):
        shutil.copyfile(source / name, candidate / name)
    git_env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    git_env |= {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
    for arguments in (['init', '-q'], ['add', '.'], ['-c', 'user.name=Fixture', '-c',
        'user.email=fixture@example.invalid', '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'isolated candidate']):
        subprocess.run(['git', *arguments], cwd=candidate, env=git_env, check=True, capture_output=True)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=candidate, env=git_env, text=True).strip()
    if scenario == 'dirty_source':
        (candidate / 'unreviewed.py').write_text('unreviewed = True\n')
    state, host, content = (root / item for item in ('state', 'host', 'content'))
    for item in (state, host, content):
        item.mkdir(mode=0o700)
    (content / 'source.md').write_text('untouched synthetic source\n')
    runtime = rt.InstanceRegistryRuntime(InstanceStateLayout.for_channel(state, 'test'), OwnershipLedger(host))
    runtime.layout.ensure()
    runtime.registry.register(VaultRegistration('retained', f'path:{content}', str(content),
        vault_id='retained-vault', local_instance_id='retained-instance'), _capability=STORAGE_MUTATION_CAPABILITY)
    registry_before = runtime.registry.path.read_bytes()
    interpreter = root / 'fixture-python'
    interpreter.write_text(f'#!{sys.executable}\n' + r'''
import hashlib, json, os, sys
from pathlib import Path
sys.path.insert(0, os.environ['FIXTURE_CODE'])
with open(os.environ['EVENTS'], 'a') as output:
    output.write(json.dumps(sys.argv[1:]) + '\n')
from scripts import instance_state_writer_inventory as inventory
if len(sys.argv) > 1 and sys.argv[1].endswith('instance_state_writer_inventory.py'):
    content = Path(os.environ['FIXTURE_CONTENT'])
    channel = 'prod' if os.environ['SCENARIO'] == 'foreign_owner' else 'test'
    owners = [{'channel_id': channel, 'root': str(content)}]
    identity, ancestors, physical = inventory._owner_identity_material(content, domain=channel, source='fixture')
    evidence = {'docker': ['docker:empty'], 'config': ['a' * 64], 'owners': owners,
        'owner_identities': [{'channel_id': channel, 'root': str(content), 'identity': identity,
            'ancestor_identities': sorted(ancestors), 'legacy_ancestor_identities': list(physical)}],
        'retired_owner_identities': []}
    snapshot = {'owners': owners, 'source_evidence': evidence,
        'source_digest': hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
    inventory._legacy_owner_snapshot = lambda *args, **kwargs: snapshot
    inventory._snapshot = lambda **kwargs: {key: [] for key in ('dev', 'native', 'prod', 'test')}
    raise SystemExit(inventory.main(sys.argv[2:]))
if sys.argv[1:3] == ['-m', 'app.instance.runtime']:
    from app.instance import runtime
    raise SystemExit(runtime.main(sys.argv[3:]))
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
''')
    interpreter.chmod(0o700)
    environment = git_env | {'FIXTURE_CODE': str(candidate), 'FIXTURE_CONTENT': str(content),
        'SCENARIO': scenario, 'EVENTS': str(root / 'events'), 'TEST_PY': str(interpreter),
        'STATE': str(state), 'HOST': str(host), 'REVISION': revision,
        'REGISTRY_SHA': sha(runtime.registry.path), 'BACKUP': str(root / 'backup'),
        'INSTANCE_OWNERSHIP_HOST_STATE_DIR': str(host), 'LOCAL_UID': str(os.geteuid()),
        'LOCAL_GID': str(os.getegid()), 'MVR03_PRINCIPAL_CUTOVER': '0',
        'INSTANCE_STATE_RESTORE_PATH': '', 'INSTANCE_LEGACY_OWNER_INVENTORY_PATH': '/app/instance-ownership/legacy-owner-inventory.json'}
    if scenario == 'runtime_uid':
        environment['LOCAL_UID'] = str(os.geteuid() + 1)
    script = r'''
set -eu
source "$FIXTURE_CODE/scripts/lib/instance_state_deployment.sh"
fake_compose() {
  printf 'compose:%s\n' "$*" >> "$EVENTS"
  case "$1" in
    config) cat "$FIXTURE_CODE/docker-compose.yaml" ;;
    stop|exec) return 0 ;;
    *) return 89 ;;
  esac
}
prepare_test_dormant_ownership_window fake_compose "$FIXTURE_CODE/.env.test" "$TEST_PY" "$REVISION" "$STATE" "$HOST/absent-legacy.md"
"$TEST_PY" -c 'import os; from pathlib import Path; h=Path(os.environ["HOST"]); assert (h/"deployment-test-restart-fence.json").exists(); assert not (h/"ownership-key.json").exists(); assert not (h/"ownership-ledger.json").exists()'
receipt_sha="$("$TEST_PY" -c 'import hashlib,os; from pathlib import Path; print(hashlib.sha256((Path(os.environ["HOST"])/"legacy-owner-inventory.json").read_bytes()).hexdigest())')"
"$TEST_PY" -m app.instance.runtime deployment-initialize-dormant-ownership --channel test \
  --instance-state-root "$STATE" --host-global-root "$HOST" --vault-binding-id retained \
  --expected-registry-sha256 "$REGISTRY_SHA" --owner-receipt-path "$HOST/legacy-owner-inventory.json" \
  --expected-owner-receipt-sha256 "$receipt_sha" --quiescence-proof-path "$HOST/deployment-quiescence-proof.json" \
  --backup-root "$BACKUP" --acknowledge-new-ownership-epoch
controller_token="$("$TEST_PY" "$FIXTURE_CODE/scripts/instance_state_writer_inventory.py" controller-token --pid "$$")"
"$TEST_PY" -m app.instance.runtime deployment-release --channel test --host-global-root "$HOST" --controller-pid "$$" --controller-start-token "$controller_token"
'''
    result = subprocess.run(['bash', '-c', script], cwd=candidate, env=environment,
        capture_output=True, text=True, timeout=60)
    events = (root / 'events').read_text()
    assert runtime.registry.path.read_bytes() == registry_before
    assert (content / 'source.md').read_text() == 'untouched synthetic source\n'
    if scenario != 'exact':
        assert result.returncode != 0
        assert 'compose:stop' not in events and 'deployment-begin' not in events
        assert not runtime.ledger.key_path.exists()
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'compose:stop' in events and 'pg_stat_activity' in events
    assert 'mvr05-record-floor' not in events and 'deployment-finish' not in events
    assert 'principal-cutover' not in events and 'authority-cutover' not in events
    assert not rt._deployment_fence_path(host, 'test').exists()
    assert set(runtime.ledger.require_existing().leases) == {'retained'}
    assert str(root) not in result.stdout
