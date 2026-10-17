from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.instance.ownership_ledger import LegacyOwner, OwnershipLedger
from app.instance.vault_registry import VaultRegistration, VaultRegistryStore
from app.ops import postgres_deploy_linux as linux
from app.ops.host_secret_contract import DATABASE_CONSUMERS
from app.ops.postgres_deploy import AuthorityCutover, DeployJournal, DeployPlan, DeployWorker, PostgresDeployError
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.helpers.runtime_identity import runtime_reachable_test_root


REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def target(tmp_path, monkeypatch, request):
    tmp_path = runtime_reachable_test_root(tmp_path, request).resolve()
    root = tmp_path / 'checkout'
    (root / 'config/deploy').mkdir(parents=True)
    runtime = root / 'runtime.env'
    runtime.write_text('VAULT_ROOT=/app/vault\nWATCHER_VAULT_PATH=/app/vault\n')
    vault = tmp_path / 'selected'
    settings = vault / 'settings'
    settings.mkdir(parents=True)
    vault_id, local_id = str(uuid4()), str(uuid4())
    for name in ('paths.md', 'workflow.md', 'design-handoff.md', 'companion-ui.md'):
        (settings / name).write_text('---\n---\n')
    (settings / 'vault.md').write_text('---\nvaultId: ' + vault_id + '\n---\n')
    (settings / 'local.md').write_text('---\nlocalInstanceId: ' + local_id + '\n---\n')
    (root / 'config/deploy/test.env').write_text('VAULT_HOST_ROOT=' + str(vault) + '\n')
    state = tmp_path / 'volume' / 'agentic-pkm'
    state.mkdir(parents=True, mode=0o700)
    registry = VaultRegistryStore(state / 'vault-registry.md')
    registry.register(VaultRegistration('binding-selected', 'path:' + str(vault), str(vault), vault_id, local_id),
                      _capability=STORAGE_MUTATION_CAPABILITY)
    owner = tmp_path / 'ownership'
    ledger = OwnershipLedger(owner)
    ledger.bootstrap_legacy_owners([LegacyOwner('test', 'binding-selected', vault)],
                                  inventory_complete=True, writers_drained=True,
                                  _capability=STORAGE_MUTATION_CAPABILITY)
    journal = DeployJournal(tmp_path / 'journal', 'test')
    cfg = SimpleNamespace(channel='test', root=root, journal=journal, runtime_env_file=runtime,
                          uid=os.getuid(), gid=os.getgid(), password_file=tmp_path / 'password',
                          source_directory=tmp_path / 'sources')
    cfg.source_directory.mkdir()
    selected = AuthorityCutover('binding-selected', str(vault), str(owner))
    plan = DeployPlan('test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
                      (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), authority_cutover=selected)
    rows = []
    for i, service in enumerate(('api', 'worker', 'watcher'), 1):
        rows.append({'Id': str(i) * 64, 'Config': {'Labels': {
            'com.docker.compose.project': 'pkm-test', 'com.docker.compose.service': service,
            'com.docker.compose.oneoff': 'False'}, 'Env': ['PKM_ENVIRONMENT=test', 'VAULT_ROOT=/app/vault', 'WATCHER_VAULT_PATH=/app/vault']},
            'Mounts': [{'Destination': '/app/vault', 'Source': str(vault), 'Type': 'bind'},
                       {'Destination': '/app/instance-ownership', 'Source': str(owner), 'Type': 'bind'},
                       {'Destination': '/app/instance-state', 'Source': str(state.parent), 'Type': 'volume',
                        'Name': 'pkm-test_instance-state'}]})
    calls = []

    def command(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ['docker', 'ps']:
            return '\n'.join(row['Id'] for row in rows)
        if argv[:2] == ['docker', 'inspect']:
            return json.dumps(rows)
        if argv[:3] == ['docker', 'volume', 'inspect']:
            return json.dumps([{'Mountpoint': str(state.parent)}])
        pytest.fail('unexpected mutation: ' + argv[0])

    real_run = subprocess.run

    def run(argv, **kwargs):
        if len(argv) > 2 and 'require_existing_authority_binding' in argv[2]:
            assert kwargs['user'] == cfg.uid and kwargs['group'] == cfg.gid
            assert kwargs['pass_fds'] == (int(argv[3]),)
            # The production supervisor is root. A local non-root test already
            # has this exact UID/GID and cannot perform setgroups(2), so retain
            # its identity while exercising the real separate proof process.
            if os.geteuid() != 0:
                kwargs.pop('extra_groups')
            return real_run(argv, **kwargs)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(linux, '_command', command)
    monkeypatch.setattr(linux.subprocess, 'run', run)
    monkeypatch.setattr(linux, 'require_file_protocol', lambda *_: None)
    monkeypatch.setattr(linux, '_raw_representation_migration_pending', lambda *_: False)
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _: cfg)
    return SimpleNamespace(cfg=cfg, selected=selected, plan=plan, rows=rows, calls=calls,
                           registry=registry, ledger=ledger, vault=vault, runtime=runtime, command=command,
                           real_run=real_run)


def _mount_mode(target, mode):
    destination = target.selected.root if mode == 'same-path' else '/app/vault'
    target.runtime.write_text('VAULT_ROOT=' + destination + '\nWATCHER_VAULT_PATH=' + destination + '\n')
    for row in target.rows:
        row['Mounts'][0]['Destination'] = destination
        row['Config']['Env'] = ['PKM_ENVIRONMENT=test', 'VAULT_ROOT=' + destination, 'WATCHER_VAULT_PATH=' + destination]


def request(plan, operation_id, action='prepare'):
    return {'action': action, 'operation_id': operation_id, 'plan': plan.payload(), 'bootstrap': False}


@pytest.mark.parametrize('mount_mode', ['alias', 'same-path'])
def test_native_cutover_admission_freezes_exact_inputs_and_refuses_changed_request(target, monkeypatch, mount_mode):
    _mount_mode(target, mount_mode)
    cfg, plan = target.cfg, target.plan
    effects = linux.LinuxEffects(cfg)
    monkeypatch.setattr(linux, 'LinuxEffects', lambda _: effects)
    effects.preflight = lambda selected: (effects.select_active_plan(selected), 'fake-password')[1]
    effects.initialized = lambda: True
    effects.materialize = lambda _: None
    effects.local_database = lambda: False
    effects.authenticate = lambda: None
    effects.quiescent = lambda: True
    effects.activate = lambda _: None
    supervisor = linux.DeploymentSupervisor(cfg)
    identifier = str(uuid4())
    assert supervisor.request(request(plan, identifier))['ready']
    private = cfg.journal.directory / 'test.request.json'
    assert json.loads(private.read_text())['plan']['authority_cutover'] == {
        'binding_id': target.selected.binding_id, 'root': str(target.vault),
        'ownership_root': str(target.ledger.root)}
    assert private.stat().st_mode & 0o777 == 0o600
    try:
        for changed in (replace(plan, revision='b' * 40),
                        replace(plan, authority_cutover=replace(target.selected, binding_id='other')),
                        replace(plan, authority_cutover=replace(target.selected, root='/other')),
                        replace(plan, authority_cutover=replace(target.selected, ownership_root='/other')),
                        replace(plan, authority_cutover=None)):
            for action in ('prepare', 'activate', 'join', 'reconcile-failed'):
                with pytest.raises(PostgresDeployError):
                    supervisor.request(request(changed, identifier, action))
        for forbidden in (replace(plan, channel='prod'), replace(plan, automatic=True, image_digest='sha256:' + 'c' * 64)):
            with pytest.raises(PostgresDeployError):
                supervisor.request(request(forbidden, str(uuid4())))
        incomplete = request(plan, str(uuid4()))
        del incomplete['plan']['authority_cutover']['root']
        with pytest.raises(PostgresDeployError):
            supervisor.request(incomplete)
        with pytest.raises(PostgresDeployError):
            supervisor.request({**request(plan, identifier), 'bootstrap': True})
    finally:
        assert supervisor.request(request(plan, identifier, 'activate'))['receipt']['stage'] == 'committed'


def _stopped_window(target, env):
    """Execute the public shell producer; external Compose/inventory return fixed proof."""
    root = target.cfg.root
    event_log = root / 'events'
    fake_bin = root / 'bin'
    fake_bin.mkdir()
    python = fake_bin / 'python3'
    python.write_text('''#!/usr/bin/env bash
if [ "${1:-}" = - ]; then exec "$REAL_PYTHON" "$@"; fi
printf 'inventory:%s\\n' "$*" >> "$EVENT_LOG"
case " $* " in
  *' controller-token '*) printf 'linux:%064d\\n' 0; exit 0 ;;
  *' compose-fence-plan '*)
    while [ "$#" -gt 0 ]; do
      if [ "$1" = --receipt-output ]; then printf '{"schema":"fixture"}\\n' > "$2"; chmod 0600 "$2"; break; fi
      shift
    done
    printf 'api worker watcher heimdal-capture-watch\\n'; exit 0 ;;
esac
while [ "$#" -gt 0 ]; do
  if [ "$1" = --output ]; then printf '{"writers_drained":true}\\n' > "$2"; exit 0; fi
  shift
done
exit 0
''')
    python.chmod(0o755)
    script = '''set -u
source "$PRODUCER"
fake_compose() {
  printf 'compose:%s\\n' "$*" >> "$EVENT_LOG"
  if [ "${1:-}" = config ]; then cat "$COMPOSE_BASE"; fi
  return 0
}
prepare_instance_state_deployment fake_compose test
'''
    result = target.real_run(['bash', '-c', script], env={**env,
        'PATH': str(fake_bin) + ':' + env['PATH'], 'REAL_PYTHON': sys.executable,
        'PYTHON': str(python),
        'PRODUCER': str(REPO / 'scripts/lib/instance_state_deployment.sh'),
        'COMPOSE_BASE': str(REPO / 'docker-compose.yaml'), 'EVENT_LOG': str(event_log)},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return event_log.read_text().splitlines()


@pytest.mark.parametrize('mount_mode', ['alias', 'same-path'])
def test_native_worker_uses_frozen_cutover_only_in_stopped_window(target, monkeypatch, mount_mode):
    _mount_mode(target, mount_mode)
    cfg, plan = target.cfg, target.plan
    identifier = str(uuid4())
    cfg.journal.bind_request(identifier, plan, False, create=True)
    effects = linux.LinuxEffects(cfg)
    effects.operation_id = identifier
    effects.preflight = lambda _: 'fake-password'
    effects.initialized = lambda: True
    effects.materialize = lambda _: None
    effects.local_database = lambda: False
    effects.authenticate = lambda: None
    effects.quiescent = lambda: True
    effects.active_consumers = plan.consumers
    effects.consumer_values = {'heimdal-api-ingress': {}}
    effects.active_revision = plan.revision
    effects.capture_watch_configured = effects.raw_migration_pending = False
    effects.source.verify = lambda: None
    monkeypatch.setenv('MVR01C_ROLLBACK_VAULT_ROOT', '/ambient-wrong')
    monkeypatch.setenv('MVR01C_ROLLBACK_VAULT_BINDING_ID', 'ambient-wrong')
    monkeypatch.setenv('INSTANCE_OWNERSHIP_HOST_STATE_DIR', '/ambient-wrong')
    observed = []

    def command(argv, **kwargs):
        if argv[0] != 'bash':
            return target.command(argv, **kwargs)
        assert cfg.journal.read().stage == 'activating'
        env = kwargs['env']
        assert env['MVR01C_ROLLBACK_VAULT_ROOT'] == target.selected.root
        assert env['MVR01C_ROLLBACK_VAULT_BINDING_ID'] == target.selected.binding_id
        assert env['INSTANCE_OWNERSHIP_HOST_STATE_DIR'] == target.selected.ownership_root
        assert kwargs['pass_fds'] == (effects.lock_fd,)
        observed.extend(_stopped_window(target, env))
        return ''

    monkeypatch.setattr(linux, '_command', command)
    with effects.channel_lock():
        worker = DeployWorker(cfg.journal, effects)
        worker.prepare(identifier)
        assert worker.run(identifier, plan).stage == 'committed'
    cutover = next(i for i, event in enumerate(observed) if 'authority-cutover' in event)
    assert any('prove-quiescent' in event for event in observed[:cutover])
    assert any('validate-legacy-owners' in event for event in observed[:cutover])
    assert any(event.startswith('compose:stop ') for event in observed[:cutover])
    assert any('deployment-finish' in event for event in observed[cutover + 1:])
    assert '--volume ' + target.selected.root + ':/app/selected-vault:ro' in observed[cutover]
    assert 'python -m app.instance.runtime authority-cutover' in observed[cutover]
    assert '--inventory-path ' in observed[cutover] and '--quiescence-proof-path ' in observed[cutover]


def test_native_cutover_requires_existing_qualified_binding_before_effects(target):
    effects = linux.LinuxEffects(target.cfg)
    effects.validate_plan(target.plan)
    snapshots = {path: path.read_bytes() for directory in (target.registry.path.parent, target.ledger.root)
                 for path in directory.iterdir() if path.is_file()}
    for broken in (replace(target.selected, binding_id='unknown'),
                   replace(target.selected, root=str(target.vault.parent / 'missing')),
                   replace(target.selected, ownership_root=str(target.ledger.root.parent / 'missing'))):
        with pytest.raises(PostgresDeployError):
            effects.validate_plan(replace(target.plan, authority_cutover=broken))
    original = target.rows[1]['Mounts'][0]['Source']
    target.rows[1]['Mounts'][0]['Source'] = '/conflicting-source'
    with pytest.raises(PostgresDeployError):
        effects.validate_plan(target.plan)
    target.rows[1]['Mounts'][0]['Source'] = original
    original_destination = target.rows[1]['Mounts'][0]['Destination']
    target.rows[1]['Mounts'][0]['Destination'] = str(target.vault)
    with pytest.raises(PostgresDeployError):
        effects.validate_plan(target.plan)  # Selector and actual destination disagree.
    target.rows[1]['Mounts'][0]['Destination'] = original_destination
    local = target.vault / 'settings/local.md'
    before = local.read_bytes()
    local.write_text('---\nlocalInstanceId: conflicting\n---\n')
    with pytest.raises(PostgresDeployError):
        effects.validate_plan(target.plan)
    local.write_bytes(before)
    # An initialized but different physical root cannot borrow the selected lease.
    selected = target.vault.rename(target.vault.with_name('old-selected'))
    target.vault.mkdir()
    import shutil
    shutil.copytree(selected / 'settings', target.vault / 'settings')
    with pytest.raises(PostgresDeployError):
        effects.validate_plan(target.plan)
    assert all(path.read_bytes() == payload for path, payload in snapshots.items())
    assert all(argv[0] == 'docker' and argv[1] in {'ps', 'inspect', 'volume'} for argv in target.calls)


def test_cutover_admission_refuses_pending_ownership_rotation_without_recovery(target):
    effects = linux.LinuxEffects(target.cfg)
    effects.validate_plan(target.plan)
    with pytest.raises(RuntimeError, match='key_commit'):
        target.ledger.rotate_key(precondition=lambda *_: None, crash_after='key_commit',
                                 _capability=STORAGE_MUTATION_CAPABILITY)
    snapshots = {path: path.read_bytes() for directory in (target.registry.path.parent, target.ledger.root)
                 for path in directory.iterdir() if path.is_file()}
    assert target.ledger.rotation_path in snapshots
    with pytest.raises(PostgresDeployError):
        effects.validate_plan(target.plan)
    assert all(path.read_bytes() == payload for path, payload in snapshots.items())
    assert target.ledger.rotation_path.exists()
    # The ordinary public proof retains its prior recovery behavior.
    target.ledger.require_scalar_rollback_ready(channel_id='test', registrations={target.selected.binding_id: target.vault})
    assert not target.ledger.rotation_path.exists()
    effects.validate_plan(target.plan)
    target.ledger.lock_path.unlink()
    with pytest.raises(PostgresDeployError):
        effects.validate_plan(target.plan)
    assert not target.ledger.lock_path.exists()


def test_runtime_uid_reads_existing_registry_view_without_host_ancestry_access(target, monkeypatch):
    """Run the real proof child against inaccessible ancestry, without chmod repair."""
    engine = target.cfg.root.parent / 'protected-engine'
    engine.mkdir(mode=0o700)
    volume = target.registry.path.parent.parent.rename(engine / 'volume')
    target.registry = VaultRegistryStore(volume / 'agentic-pkm/vault-registry.md')
    for row in target.rows:
        row['Mounts'][2]['Source'] = str(volume)
    original_command = target.command

    def command(argv, **kwargs):
        if argv[:3] == ['docker', 'volume', 'inspect']:
            return json.dumps([{'Mountpoint': str(volume)}])
        return original_command(argv, **kwargs)

    monkeypatch.setattr(linux, '_command', command)
    if os.geteuid() == 0:
        target.cfg.uid = target.cfg.gid = 65534
        for directory in (target.vault, target.ledger.root, volume / 'agentic-pkm'):
            for path in (directory, *directory.rglob('*')):
                os.chown(path, target.cfg.uid, target.cfg.gid)
    snapshots = {path: path.read_bytes() for directory in (target.registry.path.parent, target.ledger.root)
                 for path in directory.iterdir() if path.is_file()}
    observed = []

    def run(argv, **kwargs):
        if len(argv) > 2 and 'require_existing_authority_binding' in argv[2]:
            assert kwargs['user'] == target.cfg.uid and kwargs['pass_fds'] == (int(argv[3]),)
            # Local non-root tests cannot open an already-inaccessible engine
            # path as the root supervisor does. Close ancestry only after the
            # real production callsite opens the qualified directory descriptor.
            if os.geteuid() != 0:
                engine.chmod(0o000)
                kwargs.pop('extra_groups')
            try:
                probe = target.real_run([sys.executable, '-c',
                    'import os,sys\ntry: os.stat(sys.argv[1])\n'
                    'except PermissionError: sys.exit(0)\nelse: sys.exit(1)', str(target.registry.path)],
                    **{key: value for key, value in kwargs.items() if key != 'input'})
                assert probe.returncode == 0
                readonly = '''import errno,os
_open = os.open
def read_open(path, flags, *args, **kwargs):
    if flags & (os.O_CREAT | os.O_RDWR | os.O_WRONLY | os.O_TRUNC):
        raise OSError(errno.EROFS, "proof view is read-only")
    return _open(path, flags, *args, **kwargs)
def refuse_write(*args, **kwargs):
    raise OSError(errno.EROFS, "proof view is read-only")
os.open = read_open
os.fchmod = os.chmod = os.mkdir = refuse_write
'''
                guarded = [*argv]
                guarded[2] = 'exec(' + repr(readonly) + '); ' + argv[2]
                result = target.real_run(guarded, **kwargs)
                assert result.returncode == 0, result.stderr
                observed.append(result.returncode)
                return result
            finally:
                if os.geteuid() != 0:
                    engine.chmod(0o700)
        return target.real_run(argv, **kwargs)

    monkeypatch.setattr(linux.subprocess, 'run', run)
    linux.LinuxEffects(target.cfg).validate_plan(target.plan)
    assert observed == [0]
    assert engine.stat().st_mode & 0o777 == 0o700
    assert all(path.read_bytes() == payload for path, payload in snapshots.items())


def test_read_only_authority_proof_never_changes_permissions_or_creates_locks(target, monkeypatch):
    before = {path: (path.read_bytes(), path.stat().st_mode, path.stat().st_uid, path.stat().st_gid)
              for directory in (target.registry.path.parent, target.ledger.root)
              for path in directory.iterdir() if path.is_file()}
    real_open = os.open
    calls = []

    def read_open(path, flags, *args, **kwargs):
        assert not flags & (os.O_CREAT | os.O_RDWR | os.O_WRONLY | os.O_TRUNC)
        calls.append((path, flags))
        return real_open(path, flags, *args, **kwargs)

    def refuse_write(*_args, **_kwargs):
        pytest.fail('read-only proof attempted a filesystem write or permission change')

    monkeypatch.setattr(os, 'open', read_open)
    for name in ('fchmod', 'chmod', 'mkdir'):
        monkeypatch.setattr(os, name, refuse_write)
    linux.require_existing_authority_binding({'channel': 'test', 'selection': {
        'binding_id': target.selected.binding_id, 'root': target.selected.root,
        'ownership_root': target.selected.ownership_root}, 'registry_path': str(target.registry.path)})
    assert len(calls) >= 2
    assert all((path.read_bytes(), path.stat().st_mode, path.stat().st_uid, path.stat().st_gid) == state
               for path, state in before.items())


@pytest.mark.parametrize('mount_mode', ['alias', 'same-path'])
def test_cutover_mismatch_refuses_native_prepare_and_worker_before_authority(target, monkeypatch, mount_mode):
    _mount_mode(target, mount_mode)
    cfg, plan = target.cfg, target.plan
    effects = linux.LinuxEffects(cfg)
    monkeypatch.setattr(linux, 'LinuxEffects', lambda _: effects)
    effects.quiescent = lambda: True
    supervisor = linux.DeploymentSupervisor(cfg)
    identifier = str(uuid4())
    previous_runtime = target.runtime.read_text()
    target.runtime.write_text('VAULT_ROOT=/foreign\n')
    result = supervisor.request(request(plan, identifier))
    assert result['receipt']['stage'] == 'aborted'
    assert target.calls == []  # Refused before Docker or state effects.
    target.runtime.write_text(previous_runtime)
    identifier = str(uuid4())
    cfg.journal.bind_request(identifier, plan, False, create=True)
    effects.operation_id = identifier
    effects.preflight = lambda _: 'fake-password'
    effects.initialized = lambda: True
    effects.materialize = lambda _: None
    effects.local_database = lambda: False
    effects.authenticate = lambda: None
    effects.active_consumers = plan.consumers
    effects.source.verify = lambda: None
    target.rows[1]['Config']['Env'] = ['VAULT_ROOT=/foreign']
    with effects.channel_lock():
        worker = DeployWorker(cfg.journal, effects)
        worker.prepare(identifier)
        with pytest.raises(PostgresDeployError):
            worker.run(identifier, plan)
        assert cfg.journal.read().stage == 'activating'  # No guessed terminal cleanup.
    assert all(argv[0] == 'docker' for argv in target.calls)


def test_native_cutover_recovery_preserves_pending_and_exact_input_binding(target, monkeypatch):
    cfg, plan = target.cfg, target.plan
    identifier = str(uuid4())
    cfg.journal.bind_request(identifier, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating'):
        cfg.journal.write(identifier, stage)
    lock = cfg.root / 'config/deploy/test.env.lock'
    lock.mkdir(mode=0o700)
    (lock / 'bws-owner').touch(mode=0o600)
    monkeypatch.setattr(linux.LinuxEffects, 'activate', lambda *_: pytest.fail('must not replay'))
    monkeypatch.setattr(linux.LinuxEffects, 'quiescent', lambda *_: pytest.fail('health cannot prove outcome'))
    for _ in range(2):
        supervisor = linux.DeploymentSupervisor(cfg)
        for action in ('prepare', 'activate', 'join', 'reconcile-failed'):
            assert supervisor.request(request(plan, identifier, action))['pending']
            with pytest.raises(PostgresDeployError):
                supervisor.request(request(replace(plan, authority_cutover=None), identifier, action))
        assert cfg.journal.read().stage == 'activating' and lock.is_dir()
    remote = linux.SshDeployRemote('ygg-test')
    sent = []
    remote._request = lambda *args: (sent.append(args), {'pending': True, 'ready': False})[1]
    with pytest.raises(PostgresDeployError):
        remote.join(identifier, plan)
    assert len(sent) == 1  # An unknown restart does not busy-retry join.
    private = cfg.journal.directory / 'test.request.json'
    payload = private.read_bytes()
    private.unlink()
    with pytest.raises(PostgresDeployError):
        supervisor.request(request(plan, identifier, 'join'))
    private.write_bytes(payload)
    private.chmod(0o600)
    cfg.journal.write(identifier, 'committed')
    terminal = supervisor.request(request(plan, identifier, 'join'))
    assert terminal['receipt']['stage'] == 'committed'
    with pytest.raises(PostgresDeployError):
        supervisor.request(request(replace(plan, revision='b' * 40), identifier, 'join'))
    assert target.selected.root not in json.dumps(terminal)
    assert target.selected.ownership_root not in json.dumps(terminal)


def test_host_cli_produces_explicit_cutover_without_inferred_ack(target, monkeypatch):
    from app.ops import postgres_deploy_host as host
    from app.ops.postgres_deploy import DeployReceipt

    captured = []
    monkeypatch.setattr(host, 'HostSecretController', lambda: object())
    monkeypatch.setattr(host, '_configured_host_admin', lambda: object())
    monkeypatch.setattr(host, 'SecretAdmin', lambda *_args, **_kwargs: object())
    monkeypatch.setattr(host, 'SshDeployRemote', lambda _: object())
    identifier = str(uuid4())

    def deploy(_admin, _remote, plan, **kwargs):
        captured.append((plan, kwargs))
        return DeployReceipt(identifier, 'test', 'deploy', 'committed', 'committed')

    monkeypatch.setattr(host, 'deploy_from_host', deploy)
    args = ['test', target.plan.revision, '--existing-secrets-only', '--operation-id', identifier,
            '--authority-cutover-binding', target.selected.binding_id,
            '--authority-cutover-root', target.selected.root,
            '--authority-cutover-ownership-root', target.selected.ownership_root]
    assert host.main(args) == 0
    selected, kwargs = captured.pop()
    assert selected == target.plan and not selected.ack_forward_only
    assert kwargs['allow_bootstrap'] is False and kwargs['operation_id'] == identifier
    assert host.main([*args, '--automatic']) == 78
    assert host.main([value for value in args if value != '--existing-secrets-only']) == 78
    assert captured == []


@pytest.mark.parametrize('mount_mode', ['alias', 'same-path'])
def test_inherited_compose_guard_refuses_changed_or_missing_authority_request(target, monkeypatch, mount_mode):
    _mount_mode(target, mount_mode)
    cfg, plan = target.cfg, target.plan
    identifier = str(uuid4())
    cfg.journal.bind_request(identifier, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating'):
        cfg.journal.write(identifier, stage)
    lock = cfg.root / 'config/deploy/test.env.lock'
    lock.mkdir()
    cfg.password_file.write_text('fake-password')
    cfg.reader = lambda: object()
    monkeypatch.setattr(linux.PasswordSource, 'verify', lambda _: None)
    monkeypatch.setattr(linux, 'vm_selected_values', lambda *_: {'postgres-db': {'postgres.password': 'fake-password'}})
    with (lock / 'bws-owner').open('w+') as fd:
        env = {'BWS_DEPLOY_RUNTIME_ENV_FILE': str(cfg.runtime_env_file), 'BWS_DEPLOY_LOCK_FD': str(fd.fileno()),
               'BWS_DEPLOY_OPERATION_ID': identifier, 'BWS_DEPLOY_TARGET_REVISION': plan.revision,
               'BWS_EXPECTED_CAPTURE_WATCH_CONFIGURED': '0', 'BWS_EXPECTED_RAW_MIGRATION_PENDING': '0',
               'DEPLOY_HEIMDAL_RAW_MIGRATION_PENDING': '0', 'BWS_DATABASE_TARGET': 'local',
               'MVR01C_ROLLBACK_VAULT_BINDING_ID': target.selected.binding_id,
               'MVR01C_ROLLBACK_VAULT_ROOT': target.selected.root,
               'INSTANCE_OWNERSHIP_HOST_STATE_DIR': target.selected.ownership_root}
        monkeypatch.setattr(os, 'environ', env)
        linux.inherited_worker_guard('test')
        for key in ('MVR01C_ROLLBACK_VAULT_BINDING_ID', 'MVR01C_ROLLBACK_VAULT_ROOT',
                    'INSTANCE_OWNERSHIP_HOST_STATE_DIR', 'BWS_DEPLOY_TARGET_REVISION'):
            prior = env[key]
            env[key] = '/changed'
            with pytest.raises(PostgresDeployError):
                linux.inherited_worker_guard('test')
            env[key] = prior
        pin = cfg.root / 'config/deploy/test.env'
        pin.write_text('VAULT_HOST_ROOT=/changed\n')
        with pytest.raises(PostgresDeployError):
            linux.inherited_worker_guard('test')
        pin.write_text('VAULT_HOST_ROOT=' + target.selected.root + '\n')
        target.runtime.write_text('VAULT_ROOT=/foreign\n')
        with pytest.raises(PostgresDeployError):
            linux.inherited_worker_guard('test')
        _mount_mode(target, mount_mode)
        (cfg.journal.directory / 'test.request.json').unlink()
        with pytest.raises(PostgresDeployError):
            linux.inherited_worker_guard('test')


def test_ordinary_deployments_remain_compatible_and_cutover_is_value_free(target, monkeypatch):
    ordinary = replace(target.plan, authority_cutover=None)
    assert 'authority_cutover' not in ordinary.payload()
    assert DeployPlan.from_payload(ordinary.payload()) == ordinary
    automatic = replace(ordinary, automatic=True, image_digest='sha256:' + 'b' * 64)
    assert DeployPlan.from_payload(json.loads(json.dumps(automatic.payload()))) == automatic
    monkeypatch.setenv('MVR01C_ROLLBACK_VAULT_BINDING_ID', 'ambient')
    monkeypatch.setenv('MVR01C_ROLLBACK_VAULT_ROOT', '/ambient')
    effects = linux.LinuxEffects(target.cfg)
    env = effects.environment()
    assert all(key not in env for key in linux._CUTOVER_ENV)
    identifier = str(uuid4())
    target.cfg.journal.bind_request(identifier, ordinary, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating', 'committed'):
        target.cfg.journal.write(identifier, stage)
    receipt = linux.DeploymentSupervisor(target.cfg).request(request(ordinary, identifier, 'join'))
    assert receipt['receipt']['terminal_result'] == 'committed'
    assert all(path not in json.dumps(receipt) for path in (target.selected.root, target.selected.ownership_root))
