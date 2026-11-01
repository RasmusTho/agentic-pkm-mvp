"""Joined host/RPC/supervisor proofs; only external process/filesystem ports vary."""
from __future__ import annotations

from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import traceback
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
import yaml

from app.ops import native_source_identity_diagnostics as diagnostic
from app.ops import native_source_identity_persistence as persistence
from app.ops import postgres_deploy_host as host
from app.ops import postgres_deploy_linux as linux
from app.ops.host_secret_controller import HostSecretController
from app.ops.postgres_deploy import AuthorityCutover, DeployJournal, DeployPlan, PostgresDeployError
from tests._mvr_default_vault_harness import new_runtime, activate
from tests._mvr03_principal_harness import run_principal_cutover
from app.instance.local_operator_principal import AuthPosture
from tests.helpers.vault_settings import initialize_test_vault
from tests.ops.test_native_source_identity_diagnostics import FakeConnection
from tests.ops.test_native_source_identity_persistence import _map_fixed_container_mounts


REPO = Path(__file__).resolve().parents[2]
REVISION = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
DIGEST = 'sha256:' + 'b' * 64


@pytest.fixture(params=['dev', 'test'])
def composed(tmp_path, monkeypatch, request):
    channel = request.param
    root = tmp_path / 'installed-control'
    (root / 'config/deploy').mkdir(parents=True)
    for name in ('docker-compose.yaml', f'docker-compose.{channel}.yml', 'docker-compose.bws.yml',
                 'docker-compose.full-host-vault.yml', 'docker-compose.test-vault.yml'):
        shutil.copyfile(REPO / name, root / name)
    shutil.copyfile(REPO / 'config/runtime.defaults.env', root / 'config/runtime.defaults.env')
    (root / 'config/secrets').mkdir()
    shutil.copyfile(REPO / 'config/secrets/host_secret_contract.json',
                    root / 'config/secrets/host_secret_contract.json')
    runtime = new_runtime(tmp_path / 'authority', channel=channel)
    vault = tmp_path / 'selected'
    initialize_test_vault(vault)
    first = runtime.bootstrap_env_binding(vault_root=vault, watcher_vault_path=vault)
    activate(runtime, first, tmp_path / 'authority')
    run_principal_cutover(runtime, channel_id=channel,
                          posture=AuthPosture(configured_credentials=0, credential=None,
                                              loopback_listener_proven=True,
                                              companion_proxy_configured=False))
    from app.instance.settings_rebind import _install_dormant_settings_rebind
    from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
    _install_dormant_settings_rebind(runtime.registry, binding_id=first.vault_binding_id,
                                     _capability=STORAGE_MUTATION_CAPABILITY)
    note = vault / 'source.md'
    note.write_text('---\nuuid: invalid\n---\npublic synthetic body\n')
    registry_config = root / 'watchers.yaml'
    registry_config.write_text("watchers:\n  - name: notes\n    scope_glob: '*.md'\n    emit_event: ingest.vault.changed\n")
    monkeypatch.setattr('app.watcher.registry.DEFAULT_REGISTRY_CONFIG_PATH', registry_config)
    environment = {
        'PKM_ENVIRONMENT': channel, 'VAULT_ROOT': str(vault), 'VAULT_HOST_ROOT': str(vault),
        'WATCHER_VAULT_PATH': str(vault), 'WATCHER_ENABLE': '1', 'WATCHER_SCOPE_GLOB': '*.md',
        'LLM_PROVIDER': 'ollama', 'EMBED_PROVIDER': 'mock', 'EMBED_MODEL': 'synthetic-accepted',
        'STORE_BACKEND': 'pg', 'PKM_SETTINGS_PROFILE': 'lab',
        'DATABASE_URL': f'postgresql+psycopg:///?host=db&port=5432&dbname=app_{channel}&user=app',
        'INSTANCE_VAULT_REGISTRY_PATH': str(runtime.registry.path),
        'INSTANCE_OWNERSHIP_ROOT': str(runtime.ledger.root),
    }
    runtime_file = root / 'runtime.env'
    runtime_file.write_text(''.join(f'{key}={value}\n' for key, value in environment.items()))
    (root / 'config/deploy' / f'{channel}.env').write_text(f'VAULT_HOST_ROOT={vault}\n')
    journal = DeployJournal(tmp_path / 'native-journal', channel)
    with journal._directory():
        pass
    selected = AuthorityCutover(first.vault_binding_id, str(vault), str(runtime.ledger.root))
    old_id = str(uuid4())
    old_plan = DeployPlan(channel, REVISION, ('api',), ('postgres-api',))
    journal.bind_request(old_id, old_plan, False, create=True)
    journal.write(old_id, 'prepared')
    journal.write(old_id, 'aborted')
    config_file = tmp_path / 'config.json'
    linux._atomic_private_json(config_file, {
        'root': str(root), 'data_directory': str(tmp_path / 'data'), 'uid': os.getuid(), 'gid': os.getgid(),
        'organization_id': str(uuid4()), 'project_id': str(uuid4()), 'runtime_env_file': str(runtime_file),
    })
    read_json, kernel_fstat = linux._private_json, os.fstat
    def private_json(path):
        # The only adapted part of this real no-follow/schema reader is the
        # root-owned inode metadata unavailable to an unprivileged test runner.
        with monkeypatch.context() as kernel:
            def root_owned(descriptor):
                values = list(kernel_fstat(descriptor))
                values[4] = 0
                return os.stat_result(values)
            kernel.setattr(os, 'fstat', root_owned)
            return read_json(config_file if str(path).startswith('/etc/yggdrasil/bws-deploy/') else path)
    monkeypatch.setattr(linux, '_private_json', private_json)
    monkeypatch.setattr(linux.LinuxConfig, 'journal', property(lambda _cfg: journal))
    monkeypatch.setattr(linux.LinuxConfig, 'source_directory', property(lambda _cfg: tmp_path / 'secret-source'))
    cfg = linux.LinuxConfig.load(channel)
    cfg.source_directory.mkdir(mode=0o700)
    cfg.password_file.write_text('synthetic-witness-secret')
    cfg.password_file.chmod(0o440)
    environment['DATABASE_PASSWORD_FILE'] = str(cfg.password_file)
    source_read, path_stat = linux.PasswordSource._read_verified, Path.stat
    def source_read_with_kernel_metadata(source):
        with monkeypatch.context() as kernel:
            def root_owned(descriptor):
                values = list(kernel_fstat(descriptor))
                values[4] = 0
                return os.stat_result(values)
            def directory_stat(path, **kwargs):
                result = path_stat(path, **kwargs)
                if path == cfg.source_directory:
                    values = list(result)
                    values[4] = 0
                    return os.stat_result(values)
                return result
            kernel.setattr(os, 'fstat', root_owned)
            kernel.setattr(Path, 'stat', directory_stat)
            return source_read(source)
    monkeypatch.setattr(linux.PasswordSource, '_read_verified', source_read_with_kernel_metadata)
    controller = HostSecretController(tmp_path / 'host-journal')
    monkeypatch.setattr(host, 'HostSecretController', lambda: controller)
    services = yaml.safe_load((REPO / 'docker-compose.yaml').read_text())['services']
    services['api']['environment'] = dict(environment)
    compose = {'services': services}
    rows = []
    def mount(source, destination, kind='bind'):
        result = {'Type': kind, 'Source': str(source), 'Destination': destination,
                  'Mode': 'rw', 'RW': True, 'Propagation': 'rprivate'}
        if kind == 'volume':
            result.update(Name=f'pkm-{channel}_instance-state', Driver='local')
        return result
    for index, service in enumerate(('api', 'worker', 'watcher'), 1):
        running = service != 'watcher'
        rows.append({
            'Id': str(index) * 64, 'Image': 'sha256:' + 'c' * 64,
            'Config': {'Labels': {'com.docker.compose.project': f'pkm-{channel}',
                                  'com.docker.compose.service': service, 'com.docker.compose.oneoff': 'False'},
                       'Env': [f'{key}={value}' for key, value in environment.items()],
                       'Image': 'installed:accepted', 'User': f'{cfg.uid}:{cfg.gid}'},
            'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped'}},
            'Mounts': [mount(vault, str(vault)), mount(runtime.ledger.root, '/app/instance-ownership'),
                       mount(runtime.registry.path.parent.parent, '/app/instance-state', 'volume')],
            'State': {'Status': 'running' if running else 'exited', 'Running': running,
                      'Paused': False, 'Restarting': False, 'Pid': index if running else 0,
                      'StartedAt': 'public-start', 'FinishedAt': 'public-finish', 'ExitCode': 0},
        })
    state = SimpleNamespace(events=[], rows=rows, commands=[], workers=[], fail=None, rpc=[],
                            connection=FakeConnection(), after=None, producer_calls=0, errors=[],
                            credential_paths=[], metadata_calls=0, witness_fault=None,
                            retained_witness=None, removed_witnesses=[], connected_fields=[])
    def one_shot(name, service, labels, identifier, process_environment):
        row = copy.deepcopy(rows[0])
        row.update(Id=identifier * 64, Name='/' + name)
        row['Config'].update(Image='ghcr.io/rasmustho/pkm-app:' + process_environment['APP_IMAGE_TAG']
                            + process_environment['APP_IMAGE_DIGEST_SUFFIX'], Labels={
            'com.docker.compose.project': 'pkm-' + channel,
            'com.docker.compose.service': service, 'com.docker.compose.oneoff': 'True', **labels,
        })
        row['State'].update(Status='running', Running=True, Pid=20)
        row['HostConfig']['RestartPolicy']['Name'] = 'no'
        rows.append(row)
        return row
    from app.workers import outbox_worker
    metadata_producer = outbox_worker.persist_registry_source_identity
    def measured_producer(*args, **kwargs):
        state.metadata_calls += 1
        return metadata_producer(*args, **kwargs)
    monkeypatch.setattr(outbox_worker, 'persist_registry_source_identity', measured_producer)
    real_run = subprocess.run
    def process(argv, **kwargs):
        if argv[0] == 'ssh':
            payload = json.loads(kwargs['input'])
            state.rpc.append(payload)
            if state.fail == 'pre-dispatch':
                return subprocess.CompletedProcess(argv, 255, '', 'suppressed transport error')
            try:
                result = supervisor.request(payload)
                if state.fail == 'transport':
                    raise PostgresDeployError()
                return subprocess.CompletedProcess(argv, 0, json.dumps(result), '')
            except Exception:
                state.errors.append(traceback.format_exc())
                return subprocess.CompletedProcess(argv, 78, '', 'suppressed synthetic private error')
        if argv[0] == 'docker':
            return subprocess.CompletedProcess(argv, 0, command(argv, **kwargs), '')
        if argv[0] == 'git' and 'cat-file' in argv:
            return subprocess.CompletedProcess(argv, 0, b'', b'')
        if len(argv) > 2 and 'import os,sys; f=os.open' in argv[2]:
            assert os.pread(kwargs['pass_fds'][0], 65537, 0) == b'synthetic-witness-secret'
            return subprocess.CompletedProcess(argv, 0, b'', b'')
        if len(argv) > 2 and 'require_existing_authority_binding' in argv[2]:
            assert kwargs['cwd'] == root and kwargs['env']['PYTHONDONTWRITEBYTECODE'] == '1'
            assert argv[0] == sys.executable
            if os.geteuid() != 0:
                kwargs.pop('extra_groups')
        return real_run(argv, **kwargs)
    def command(argv, **kwargs):
        state.commands.append(argv)
        if argv[0] == 'git':
            return (REPO / 'app/config/database.py').read_text()
        if argv[:2] == ['docker', 'ps']:
            if any(item.startswith('name=') for item in argv):
                name = next(item.removeprefix('name=^/').removesuffix('$') for item in argv if item.startswith('name='))
                return '\n'.join(row['Id'] for row in rows if row.get('Name') == '/' + name)
            if state.after is not None:
                callback, state.after = state.after, None
                callback()
            matched = rows
            for item in argv:
                if item.startswith('label='):
                    key, separator, value = item.removeprefix('label=').partition('=')
                    matched = [row for row in matched if key in row['Config']['Labels']
                               and (not separator or row['Config']['Labels'][key] == value)]
            return '\n'.join(row['Id'] for row in matched)
        if argv[:3] == ['docker', 'inspect', '--type']:
            return json.dumps(rows)
        if argv[:3] == ['docker', 'inspect', '--format']:
            row = next(row for row in rows if row['Id'] == argv[-1])
            if argv[3] == '{{.Config.Image}}':
                return row['Config']['Image']
            labels = row['Config']['Labels']
            return ' '.join((row['Name'], labels['com.docker.compose.project'], labels['com.docker.compose.service'],
                             labels['com.docker.compose.oneoff'], labels['yggdrasil.native.operation'],
                             labels['yggdrasil.native.revision'], str(row['State']['Running']).lower()))
        if argv[:2] == ['docker', 'stop']:
            if state.fail == 'retain-producer':
                raise OSError('synthetic lost stop')
            row = next(row for row in rows if row['Id'] == argv[-1])
            row['State'].update(Status='exited', Running=False, Pid=0)
            state.events.append(('worker-stop', [row['Id']]))
            return ''
        if argv[:2] == ['docker', 'rm']:
            row = next(row for row in rows if row['Id'] == argv[-1])
            rows.remove(row)
            state.events.append(('worker-remove', [row['Id']]))
            return ''
        if argv[:3] == ['docker', 'volume', 'inspect']:
            return json.dumps([{'Mountpoint': str(runtime.registry.path.parent.parent)}])
        if argv[:5] == ['docker', '--host', 'unix:///var/run/docker.sock', 'image', 'inspect']:
            assert kwargs['env'] == {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
            return json.dumps([{'Config': {'Labels': {'org.opencontainers.image.revision': REVISION}},
                                'RepoDigests': ['ghcr.io/rasmustho/pkm-app@' + DIGEST]}])
        if argv[:3] == ['docker', 'image', 'inspect']:
            return json.dumps([{'Config': {'Labels': {'org.opencontainers.image.revision': REVISION}},
                                'RepoDigests': ['ghcr.io/rasmustho/pkm-app@' + DIGEST]}])
        if argv[:2] == ['docker', 'compose']:
            assert kwargs['cwd'] == root
            assert kwargs['env']['PYTHON'] == sys.executable
            assert str(root / 'docker-compose.full-host-vault.yml') in argv
            if channel == 'test':
                assert str(root / 'docker-compose.test-vault.yml') in argv
            action_index = argv.index('-p') + 2
            action, *args = argv[action_index:]
            if action == 'config':
                return json.dumps(compose)
            state.events.append((action, args))
            if action == 'pull':
                return ''
            if action in {'stop', 'start'}:
                assert args, 'bare service command must never occur'
                if state.fail == 'restore' and action == 'start':
                    raise PostgresDeployError()
                for row in rows:
                    if row['Config']['Labels']['com.docker.compose.service'] in args:
                        row['State'].update(Status='running' if action == 'start' else 'exited',
                                            Running=action == 'start', Pid=10 if action == 'start' else 0)
                return ''
            if action == 'run':
                state.producer_calls += 1
                labels = dict(args[index + 1].split('=', 1) for index, value in enumerate(args) if value == '--label')
                one_shot(args[args.index('--name') + 1], 'api', labels, 'e', kwargs['env'])
                if state.fail in {'producer', 'retain-producer'}:
                    raise PostgresDeployError()
                offset = args.index('app.ops.native_source_identity_persistence') + 1
                with monkeypatch.context() as context:
                    for key, value in environment.items():
                        context.setenv(key, value)
                    context.setenv('GIT_SHA', REVISION)
                    context.setenv('NATIVE_SOURCE_BOOTSTRAP', f'{channel}:{REVISION}')
                    _map_fixed_container_mounts(context, state_root=runtime.registry.path.parent.parent,
                                               ownership_root=runtime.ledger.root, selected_root=vault, legacy_root=False)
                    output = io.StringIO()
                    with redirect_stdout(output):
                        assert persistence.worker_main(args[offset:]) == 0
                    return output.getvalue()
        raise AssertionError(f'unexpected effect port: {argv[:3]}')
    monkeypatch.setattr(linux, '_command', command)
    monkeypatch.setattr(subprocess, 'run', process)
    supervisor = linux.DeploymentSupervisor(cfg)
    coordinator = diagnostic.run_production_diagnostic
    def traced_coordinator(**kwargs):
        try:
            return coordinator(**kwargs)
        except Exception:
            state.errors.append(traceback.format_exc())
            raise
    monkeypatch.setattr(diagnostic, 'run_production_diagnostic', traced_coordinator)
    capture = diagnostic._source_capture
    def traced_capture(*args, **kwargs):
        try:
            return capture(*args, **kwargs)
        except Exception:
            state.errors.append(traceback.format_exc())
            raise
    monkeypatch.setattr(diagnostic, '_source_capture', traced_capture)
    witness_tmpfs = tmp_path / 'witness-tmpfs'
    witness_tmpfs.mkdir(mode=0o1777)
    real_mkstemp, real_open, real_read_text = diagnostic.tempfile.mkstemp, os.open, Path.read_text
    real_unlink = os.unlink
    def connect(dsn, **kwargs):
        assert 'synthetic-witness-secret' in dsn
        credential = Path(os.environ['DATABASE_PASSWORD_FILE'])
        assert credential.read_text() == 'synthetic-witness-secret'
        if 'connect_timeout' in kwargs:
            class Ping:
                def __enter__(self):
                    return self
                def __exit__(self, *_args):
                    return None
                def cursor(self):
                    return self
                def execute(self, query):
                    assert query == 'SELECT 1'
                def fetchone(self):
                    return (1,)
            return Ping()
        assert credential.stat().st_mode & 0o777 == 0o600
        from psycopg.conninfo import conninfo_to_dict
        state.connected_fields.append({key: value for key, value in conninfo_to_dict(dsn).items() if key != 'password'})
        state.credential_paths.append(credential)
        return state.connection
    monkeypatch.setattr('psycopg.connect', connect)
    def bounded(argv, *, input_bytes, max_output_bytes, **kwargs):
        argv = tuple(argv)
        if argv[:3] == ('docker', 'image', 'inspect'):
            return 0, b'["PATH=/usr/bin"]' if argv[4] == '{{json .Config.Env}}' else DIGEST.encode()
        if 'config' in argv:
            return 0, json.dumps({'services': {diagnostic.DATABASE_WITNESS_SERVICE: {
                **compose['services'][diagnostic.DATABASE_WITNESS_SERVICE],
                'image': 'ghcr.io/rasmustho/pkm-app:' + kwargs['environment']['APP_IMAGE_TAG']
                + kwargs['environment']['APP_IMAGE_DIGEST_SUFFIX']}}}).encode()
        if argv[:3] == ('docker', 'container', 'inspect'):
            if state.fail == 'cleanup' or (state.fail == 'retain-witness' and state.retained_witness is not None):
                return 2, b''
            if state.retained_witness is not None and argv[-1] == state.retained_witness[0]:
                row = next(row for row in rows if row['Id'] == 'f' * 64)
                fields = [row['Id'], row['Config']['Labels'][diagnostic.OWNER_LABEL]]
                if '{{.Config.Image}}' in argv[4]:
                    fields.append(row['Config']['Image'])
                return 0, '\t'.join(fields).encode()
            return 1, b''
        if argv[:3] == ('docker', 'container', 'ls'):
            return 0, b''
        if argv[:3] == ('docker', 'container', 'rm'):
            assert argv == ('docker', 'container', 'rm', '--force', 'f' * 64)
            assert state.retained_witness is not None
            state.removed_witnesses.append(state.retained_witness)
            state.retained_witness = None
            rows.remove(next(row for row in rows if row['Id'] == 'f' * 64))
            for credential in witness_tmpfs.iterdir():
                real_unlink(credential)
            return 0, b''
        state.workers.append((argv, input_bytes, max_output_bytes))
        phase = 'prepare' if 'source-prepare' in argv else 'finalize' if 'source-finalize' in argv else 'witness'
        if state.fail in {'worker', phase}:
            raise diagnostic.SourceIdentityDiagnosticRefusal('database_witness_refused')
        if state.fail in {'malformed', 'private', 'oversized'} and phase == 'witness':
            return 0, {'malformed': b'not-json', 'private': b'{"private":"synthetic-witness-secret"}',
                       'oversized': b' ' * (max_output_bytes + 1)}[state.fail]
        if phase == 'witness':
            # Model the real service env-file precedence and only the actual
            # Compose run overrides. Do not inject the admitted API environment.
            child_environment = {}
            for source in (root / 'config/runtime.defaults.env', runtime_file):
                child_environment.update(line.split('=', 1) for line in source.read_text().splitlines()
                                         if line and not line.startswith('#') and '=' in line)
            child_environment.update(compose['services'][diagnostic.DATABASE_WITNESS_SERVICE]['environment'])
            for index, value in enumerate(argv):
                if value == '-e':
                    key, separator, selected_value = argv[index + 1].partition('=')
                    child_environment[key] = selected_value if separator else kwargs['environment'][key]
            name, token = argv[argv.index('--name') + 1], argv[argv.index('--label') + 1].split('=', 1)[1]
            one_shot(name, diagnostic.DATABASE_WITNESS_SERVICE, {diagnostic.OWNER_LABEL: token}, 'f', kwargs['environment'])
            if state.fail == 'retain-witness':
                state.retained_witness = (name, token)
                raise diagnostic.SourceIdentityDiagnosticRefusal('database_witness_refused')
        else:
            child_environment = dict(argv[index + 1].split('=', 1) for index, value in enumerate(argv) if value == '--env')
        if phase == 'witness' and state.witness_fault in {'extra', 'channel', 'digest', 'empty', 'oversized', 'duplicate'}:
            envelope = json.loads(input_bytes)
            if state.witness_fault == 'extra':
                envelope['private'] = 'synthetic-witness-secret'
            elif state.witness_fault == 'channel':
                envelope['channel'] = 'prod'
            elif state.witness_fault == 'digest':
                envelope['image_digest'] = 'sha256:' + 'e' * 64
            elif state.witness_fault == 'empty':
                envelope['password'] = ''
            input_bytes = json.dumps(envelope).encode()
            if state.witness_fault == 'oversized':
                input_bytes += b' ' * diagnostic.MAX_WITNESS_FRAME_BYTES
            elif state.witness_fault == 'duplicate':
                input_bytes = b'{"password":"different",' + input_bytes[1:]
        if phase == 'witness' and state.witness_fault == 'password-env':
            child_environment['PGPASSWORD'] = 'synthetic-witness-secret'
        if phase == 'witness' and state.witness_fault == 'target-drift':
            child_environment['DATABASE_URL'] = child_environment['DB_DSN'].replace('host=db', 'host=foreign-db')
        with monkeypatch.context() as context, patch.dict(os.environ, child_environment, clear=True):
            # Model only the isolated container's tmpfs/mount namespace. The
            # real CLI, private file lifecycle and canonical resolver remain.
            context.setattr(Path, 'read_text', lambda path, *a, **k:
                ('1 0 0:1 / /tmp rw - tmpfs tmpfs rw\n' if state.witness_fault != 'not-tmpfs' else '')
                if str(path) == '/proc/self/mountinfo'
                else real_read_text(path, *a, **k))
            context.setattr(os, 'open', lambda path, *a, **k:
                real_open(witness_tmpfs if path == '/tmp' else path, *a, **k))
            context.setattr(diagnostic.tempfile, 'mkstemp', lambda **k:
                real_mkstemp(**{**k, 'dir': witness_tmpfs}))
            if phase == 'witness' and state.witness_fault == 'unlink':
                state.retained_witness = (
                    argv[argv.index('--name') + 1],
                    argv[argv.index('--label') + 1].split('=', 1)[1],
                )
                def interrupted_unlink(path, *args, **kwargs):
                    if Path(path).parent == witness_tmpfs:
                        raise OSError('synthetic unlink interruption')
                    return real_unlink(path, *args, **kwargs)
                context.setattr(os, 'unlink', interrupted_unlink)
            context.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(input_bytes)))
            output = io.StringIO()
            worker_args = list(argv[argv.index('app.ops.native_source_identity_diagnostics') + 1:])
            with redirect_stdout(output):
                status = diagnostic.worker_main(worker_args)
            if status:
                state.errors.append((worker_args[0], output.getvalue()))
            if phase == 'witness' and state.retained_witness is None:
                rows.remove(next(row for row in rows if row['Id'] == 'f' * 64))
            return status, output.getvalue().encode()
    monkeypatch.setattr(diagnostic, '_run_bounded_status', bounded)
    def invoke(*, persist=False, operation_id=None, extra=()):
        args = [channel, REVISION, '--automatic', '--existing-secrets-only', '--current-state-source',
                '--persist-source-identity' if persist else '--diagnose-source-identity',
                '--operation-id', operation_id or str(uuid4()), '--image-digest', DIGEST,
                '--authority-cutover-binding', selected.binding_id, '--authority-cutover-root', selected.root,
                '--authority-cutover-ownership-root', selected.ownership_root, *extra]
        if persist:
            args += ['--source-producer-kind', 'registry']
        output = io.StringIO()
        with redirect_stdout(output):
            code = host.main(args)
        return code, output.getvalue()
    return SimpleNamespace(**state.__dict__, state=state, invoke=invoke, cfg=cfg, selected=selected,
                           supervisor=supervisor, runtime=runtime, note=note, controller=controller,
                           compose=compose, monkeypatch=monkeypatch)


@pytest.mark.parametrize('stopped', [False, True])
def test_composed_current_state_diagnostic_preserves_stopped_watcher(composed, stopped):
    if not stopped:
        composed.state.rows[-1]['State'].update(Status='running', Running=True, Pid=30)
    before = copy.deepcopy(composed.state.rows)
    code, output = composed.invoke()
    assert code == 0, (output, composed.state.errors)
    result = json.loads(output)
    assert result['contract'] == diagnostic.SOURCE_RECEIPT_CONTRACT
    assert result['registry_invalid_count'] == result['product_absent_count'] == 1
    assert composed.state.rows == before
    assert all(action == 'pull' for action, _ in composed.state.events)
    assert len(composed.state.workers) == 3
    assert len(composed.state.credential_paths) == 1
    assert all(not path.exists() for path in composed.state.credential_paths)
    assert linux.LinuxEffects(composed.cfg).channel_lock_owner() is None


@pytest.mark.parametrize("key,value", [
    ("DOCKER_HOST", "tcp://foreign.invalid:2375"),
    ("DOCKER_CONTEXT", "foreign"),
    ("APP_IMAGE_REPOSITORY", "foreign.invalid/image"),
])
def test_source_acquisition_rejects_installed_foreign_image_selectors(composed, key, value):
    selected = composed.selected
    channel = composed.cfg.channel
    plan = DeployPlan(channel, REVISION, ("api",), ("postgres-api",), image_digest=DIGEST,
                      authority_cutover=selected)
    snapshot = SimpleNamespace(
        child_environment=(("DATABASE_URL", f"postgresql+psycopg:///?host=db&port=5432&dbname=app_{channel}&user=app"),
                           (key, value)),
        unset_environment=(), container_root="/app/vault", vault_overlay="docker-compose.legacy-vault.yml",
        host_root=selected.root,
    )
    with pytest.raises(linux.PostgresDeployError):
        linux.LinuxEffects(composed.cfg).source_compose_invocation(cutover=selected, candidate=plan,
                                                                  source_snapshot=snapshot)


def test_source_acquisition_keeps_authenticated_image_after_installed_values(composed):
    selected = composed.selected
    channel = composed.cfg.channel
    plan = DeployPlan(channel, REVISION, ("api",), ("postgres-api",), image_digest=DIGEST,
                      authority_cutover=selected)
    snapshot = SimpleNamespace(
        child_environment=(("DATABASE_URL", f"postgresql+psycopg:///?host=db&port=5432&dbname=app_{channel}&user=app"),
                           ("APP_IMAGE_TAG", "foreign"), ("APP_IMAGE_DIGEST_SUFFIX", "@sha256:" + "c" * 64)),
        unset_environment=(), container_root="/app/vault", vault_overlay="docker-compose.legacy-vault.yml",
        host_root=selected.root,
    )
    argv, env = linux.LinuxEffects(composed.cfg).source_compose_invocation(
        cutover=selected, candidate=plan, source_snapshot=snapshot,
    )
    assert argv[:2] == ["docker", "compose"]
    assert env["APP_IMAGE_TAG"] == REVISION and env["APP_IMAGE_DIGEST_SUFFIX"] == "@" + DIGEST
    assert env["APP_IMAGE_REPOSITORY"] == "ghcr.io/rasmustho/pkm-app"
    assert env["DOCKER_HOST"] == "unix:///var/run/docker.sock"


@pytest.mark.parametrize('fault', ['registry', 'owner', 'pending-host', 'pending-native', 'channel',
                                  'rotation', 'transaction', 'key', 'private-lock', 'supervisor', 'transfer'])
def test_composed_admission_refuses_unproven_authority_without_mutation(composed, fault):
    if fault == 'registry':
        composed.runtime.registry.path.write_text('invalid')
    elif fault == 'owner':
        composed.selected = AuthorityCutover(composed.selected.binding_id, composed.selected.root, '/missing-owner')
        composed.runtime.ledger.root.rename(composed.runtime.ledger.root.with_name('retained-owner'))
    elif fault == 'pending-host':
        with composed.controller.source_persistence_operation(composed.cfg.channel, operation_id=str(uuid4())) as (operation, _):
            operation.prepare_mutation()
    elif fault == 'pending-native':
        composed.cfg.journal.write(str(uuid4()), 'prepared')
    elif fault == 'rotation':
        from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
        with pytest.raises(RuntimeError):
            composed.runtime.ledger.rotate_key(precondition=lambda *_: None, crash_after='key_commit',
                                               _capability=STORAGE_MUTATION_CAPABILITY)
    elif fault == 'transaction':
        composed.runtime.registry.transaction_path.write_text('{}')
    elif fault == 'transfer':
        from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
        composed.runtime.ledger.begin_transfer(source_binding_id=composed.selected.binding_id,
            destination_channel_id='test' if composed.cfg.channel == 'dev' else 'dev',
            destination_binding_id='binding-destination', _capability=STORAGE_MUTATION_CAPABILITY)
    elif fault in {'key', 'private-lock'}:
        path = composed.runtime.ledger.key_path if fault == 'key' else composed.runtime.ledger.lock_path
        path.unlink()
    elif fault == 'supervisor':
        composed.supervisor.operation = SimpleNamespace(finished=threading.Event())
    else:
        lock = composed.cfg.root / 'config/deploy' / f'{composed.cfg.channel}.env.lock'
        lock.mkdir(mode=0o700)
        (lock / 'unexpected').write_text('foreign')
    protected = {path: path.read_bytes() for directory in (
        composed.runtime.registry.path.parent, composed.runtime.ledger.root,
    ) if directory.exists() for path in directory.iterdir() if path.is_file()}
    code, _ = composed.invoke()
    assert code == 78
    assert all(path.read_bytes() == data for path, data in protected.items())
    assert not composed.state.workers and not composed.state.events


@pytest.mark.parametrize('fault', ['unknown', 'duplicate', 'created', 'paused', 'restarting', 'one-shot',
                                  'image', 'environment', 'mount', 'user', 'population', 'one-shot-restart'])
def test_composed_admission_refuses_census_and_boundary_drift(composed, fault):
    row = composed.state.rows[-1]
    if fault == 'unknown':
        row['Config']['Labels']['com.docker.compose.service'] = 'unknown-writer'
    elif fault == 'duplicate':
        duplicate = copy.deepcopy(row)
        duplicate['Id'] = 'd' * 64
        composed.state.rows.append(duplicate)
    elif fault == 'one-shot':
        row['Config']['Labels']['com.docker.compose.oneoff'] = 'True'
    elif fault == 'one-shot-restart':
        composed.compose['services']['migrate']['restart'] = 'always'
    elif fault in {'image', 'environment', 'mount', 'user', 'population'}:
        original = linux.LinuxEffects.require_source_identity_candidate
        def drift(effects, *args, **kwargs):
            original(effects, *args, **kwargs)
            if fault == 'image':
                row['Image'] = 'sha256:' + 'e' * 64
            elif fault == 'environment':
                row['Config']['Env'].append('NEW=value')
            elif fault == 'mount':
                row['Mounts'][0]['RW'] = False
            elif fault == 'user':
                row['Config']['User'] = '0:0'
            elif row in composed.state.rows:
                composed.state.rows.remove(row)
        composed.monkeypatch.setattr(linux.LinuxEffects, 'require_source_identity_candidate', drift)
    elif fault in {'paused', 'restarting'}:
        row['State'][fault.title()] = True
    else:
        row['State']['Status'] = 'created'
    code, _ = composed.invoke()
    assert code == 78
    assert not composed.state.workers


@pytest.mark.parametrize('fault', ['readonly', 'malformed', 'private', 'oversized', 'witness-volume', 'secret-missing'])
def test_composed_diagnostic_preserves_worker_isolation_and_redaction(composed, fault):
    if fault == 'readonly':
        composed.state.connection.read_only = 'off'
    elif fault == 'witness-volume':
        composed.compose['services'][diagnostic.DATABASE_WITNESS_SERVICE]['volumes'] = ['/source:/source']
    elif fault == 'secret-missing':
        composed.cfg.password_file.unlink()
    else:
        composed.state.fail = fault
    code, output = composed.invoke()
    assert code == 78
    assert 'public synthetic body' not in output and str(composed.note) not in output
    assert 'synthetic-witness-secret' not in output
    if fault == 'secret-missing':
        assert not composed.cfg.password_file.exists() and not composed.state.workers
        return
    assert json.loads(output)['reason'] == 'database_witness_refused'
    if fault == 'witness-volume':
        assert not composed.state.workers
        return
    source = composed.state.workers[0][0]
    assert source[source.index('--network') + 1] == 'none'
    assert '--read-only' in source
    assert not any('DATABASE_' in item or 'DB_DSN' in item for item in source)
    for argv, frame, _limit in composed.state.workers:
        if 'source-prepare' in argv or 'source-finalize' in argv:
            assert b'synthetic-witness-secret' not in frame
    if fault == 'readonly':
        assert composed.state.connection.queries[0][0] == 'SHOW default_transaction_read_only'


@pytest.mark.parametrize('fault', ['prepare', 'witness', 'finalize', 'transport', 'cleanup'])
def test_composed_diagnostic_failure_cleanup_and_no_replay(composed, fault):
    operation_id = str(uuid4())
    composed.state.fail = fault
    assert composed.invoke(operation_id=operation_id)[0] == 78
    count = len(composed.state.workers)
    composed.state.fail = None
    code, _ = composed.invoke(operation_id=operation_id)
    assert code == (0 if fault == 'transport' else 78)
    assert len(composed.state.workers) == count
    assert not any(action in {'start', 'stop'} for action, _ in composed.state.events)


@pytest.mark.parametrize('empty', [False, True])
def test_composed_current_state_registry_persistence_and_exact_cleanup(composed, empty):
    composed.note.write_text('public synthetic body\n')
    if empty:
        for row in composed.state.rows:
            row['State'].update(Status='exited', Running=False, Pid=0)
    watcher = copy.deepcopy(composed.state.rows[-1])
    code, output = composed.invoke(persist=True)
    assert code == 0, output
    result = json.loads(output)
    assert result['eligible'] is True
    assert composed.state.producer_calls == 1
    assert composed.state.metadata_calls == result['selected_count']
    assert [(action, args) for action, args in composed.state.events if action in {'start', 'stop'}] == (
        [] if empty else [('stop', ['api', 'worker']), ('start', ['api', 'worker'])])
    assert composed.state.rows[-1] == watcher
    assert linux.LinuxEffects(composed.cfg).channel_lock_owner() is None


@pytest.mark.parametrize('persist,artifact', [
    (False, 'request'), (False, 'attempt'), (False, 'terminal'),
    (True, 'request'), (True, 'attempt'), (True, 'producer'), (True, 'terminal'),
])
@pytest.mark.parametrize('entry', ['dangling-symlink', 'symlink', 'directory', 'fifo'])
def test_malformed_retained_source_entry_refuses_without_effects(composed, persist, artifact, entry):
    operation_id = str(uuid4())
    composed.note.write_text('writable public source without identity\n')
    directory = composed.cfg.journal.directory
    kind = 'source-identity' if persist else 'source-diagnostic'
    suffix = {'request': '.request.json', 'terminal': '.json', 'producer': '.producer.json',
              'attempt': '.producer.attempt.json' if persist else '.attempt.json'}[artifact]
    path = directory / f'{composed.cfg.channel}-{kind}-{operation_id}{suffix}'
    target = directory.parent / 'retained-source-target.json'
    if entry == 'symlink':
        linux._atomic_private_json(target, {'retained': 'public synthetic evidence'})
    if entry in {'dangling-symlink', 'symlink'}:
        path.symlink_to(target)
    elif entry == 'directory':
        path.mkdir(mode=0o700)
    else:
        os.mkfifo(path, 0o600)

    def retained_entries():
        return {item.name: (item.lstat().st_ino, item.lstat().st_mode,
                           item.readlink() if item.is_symlink() else
                           item.read_bytes() if item.is_file() else None)
                for item in directory.iterdir()}

    before = retained_entries()
    rows, source = copy.deepcopy(composed.state.rows), composed.note.read_bytes()
    target_before = target.read_bytes() if target.exists() else None
    # Fresh admission, same-ID cleanup and explicit absence retirement must all
    # preserve malformed evidence. None may reinterpret it as a missing entry.
    for extra in ((), (), ('--prove-source-operation-never-admitted',)):
        assert composed.invoke(persist=persist, operation_id=operation_id, extra=extra)[0] == 78
        assert retained_entries() == before
        assert composed.state.rows == rows and composed.note.read_bytes() == source
        assert not composed.state.events and not composed.state.workers
        assert composed.state.producer_calls == composed.state.metadata_calls == 0
        assert linux.LinuxEffects(composed.cfg).channel_lock_owner() is None
        assert (target.read_bytes() if target.exists() else None) == target_before


@pytest.mark.parametrize('fault', ['producer', 'restore', 'transport'])
def test_composed_registry_continuation_refuses_replay_and_reaches_normal_deploy_boundary(composed, fault):
    composed.note.write_text('public synthetic body\n')
    operation_id = str(uuid4())
    composed.state.fail = fault
    assert composed.invoke(persist=True, operation_id=operation_id)[0] == 78
    count = composed.state.producer_calls
    composed.state.fail = None
    composed.invoke(persist=True, operation_id=operation_id)
    assert composed.state.producer_calls == count == 1
    assert all(request['action'] == 'source-identity-persist' for request in composed.state.rpc)
    assert composed.state.rows[-1]['State']['Status'] == 'exited'
    assert composed.invoke(operation_id=operation_id)[0] == 78


def test_new_admission_cannot_authorize_other_operations(composed):
    assert composed.invoke(extra=('--ack-forward-only',))[0] == 78
    assert composed.invoke(extra=('--preflight-source-persistence-admission',))[0] == 78
    assert not composed.state.rpc
    with pytest.raises(PostgresDeployError):
        linux.SshDeployRemote('ygg-prod').diagnose_source_identity(str(uuid4()), REVISION, DIGEST, composed.selected)


@pytest.mark.parametrize('persist', [False, True])
@pytest.mark.parametrize('failure', ['pre-dispatch', 'authority', 'census'])
def test_never_admitted_source_operation_retires_only_by_bound_absence(composed, persist, failure):
    if persist:
        composed.note.write_text('source\n')
    operation_id = str(uuid4())
    rows = copy.deepcopy(composed.state.rows)
    authority = composed.runtime.registry.path.read_bytes()
    source = composed.note.read_bytes()
    if failure == 'authority':
        composed.runtime.registry.path.write_text('malformed synthetic authority\n')
    elif failure == 'census':
        composed.state.rows[-1]['State']['Status'] = 'created'
    else:
        composed.state.fail = failure
    assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    assert composed.controller.source_persistence_preflight(composed.cfg.channel)['ready'] is False
    composed.state.fail = None
    composed.runtime.registry.path.write_bytes(authority)
    composed.state.rows[:] = rows
    # A normal retry remains cleanup-only and must not turn absence into a
    # fresh attempt. Only the explicit existing absence-proof route retires it.
    assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    assert not composed.state.workers and composed.state.producer_calls == 0
    assert composed.invoke(persist=not persist, operation_id=operation_id,
                           extra=('--prove-source-operation-never-admitted',))[0] == 78
    legacy = [composed.cfg.channel, REVISION, '--automatic', '--existing-secrets-only',
              '--operation-id', operation_id, '--prove-source-persistence-never-admitted']
    if persist:
        legacy += ['--source-producer-kind', 'registry']
    with redirect_stdout(io.StringIO()):
        assert host.main(legacy) == 78  # current-state authority cannot become legacy authority
    if failure == 'pre-dispatch':
        composed.state.fail = 'transport'
        assert composed.invoke(persist=persist, operation_id=operation_id,
                               extra=('--prove-source-operation-never-admitted',))[0] == 78
        assert composed.controller.source_persistence_preflight(composed.cfg.channel)['ready'] is False
        composed.state.fail = None
    code, output = composed.invoke(persist=persist, operation_id=operation_id,
                                   extra=('--prove-source-operation-never-admitted',))
    assert code == 0, (output, composed.state.errors)
    proof = json.loads(output)
    assert proof['source_kind'] == ('source-persistence' if persist else 'source-diagnostic')
    assert proof['source_mode'] == 'current-state' and proof['host_operation_retired'] is True
    assert proof['native_attempt_retired'] is True
    assert 'request_fingerprint' not in proof and str(composed.note.parent) not in output
    native_original = copy.deepcopy(composed.state.rpc[0])
    attempt = composed.cfg.journal.directory / (
        f'{composed.cfg.channel}-source-identity-{operation_id}.producer.attempt.json' if persist
        else f'{composed.cfg.channel}-source-diagnostic-{operation_id}.attempt.json'
    )
    sealed = attempt.read_bytes()
    assert attempt.stat().st_mode & 0o777 == 0o600
    assert json.loads(sealed)['source_request']['source_mode'] == 'current-state'
    # The late original is not a host retry. Both the current daemon and a
    # restarted daemon must reject its original cleanup_only=false request.
    for supervisor in (composed.supervisor, linux.DeploymentSupervisor(composed.cfg)):
        with pytest.raises(PostgresDeployError):
            supervisor.request(native_original)
        swapped = {**native_original, 'action': 'source-identity-diagnose' if persist else 'source-identity-persist'}
        if persist:
            swapped.pop('producer_kind')
        else:
            swapped['producer_kind'] = 'registry'
        with pytest.raises(PostgresDeployError):
            supervisor.request(swapped)
    with pytest.raises(PostgresDeployError):
        linux.LinuxEffects(composed.cfg).persist_source_identity(
            operation_id, REVISION, DIGEST, composed.selected, 'registry',
        )
    assert composed.invoke(persist=persist, operation_id=operation_id,
                           extra=('--prove-source-operation-never-admitted',))[0] == 0
    assert attempt.read_bytes() == sealed
    assert composed.controller.source_persistence_preflight(composed.cfg.channel)['ready'] is True
    assert composed.state.rows == rows and composed.note.read_bytes() == source
    assert not composed.state.events and not composed.state.workers
    count = len(composed.state.rpc)
    assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    assert len(composed.state.rpc) == count  # the consumed ID never dispatches
    assert composed.invoke(persist=persist)[0] == 0


@pytest.mark.parametrize('persist', [False, True])
@pytest.mark.parametrize('conflict', ['request', 'attempt', 'producer', 'terminal', 'foreign-kind',
                                     'worker', 'diagnostic-worker', 'lock', 'supervisor', 'live-thread',
                                     'foreign-supervisor', 'malformed-lineage', 'pending-lineage'])
def test_never_admitted_proof_refuses_any_existing_native_authority(composed, persist, conflict):
    operation_id = str(uuid4())
    composed.state.fail = 'pre-dispatch'
    assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    composed.state.fail = None
    prefix = f'{composed.cfg.channel}-source-identity-{operation_id}'
    suffix = {'request': '.request.json', 'attempt': '.producer.attempt.json',
              'producer': '.producer.json', 'terminal': '.json'}.get(conflict)
    if suffix is not None:
        linux._atomic_private_json(composed.cfg.journal.directory / (prefix + suffix), {})
    elif conflict == 'foreign-kind':
        linux._atomic_private_json(composed.cfg.journal.directory /
            f'{composed.cfg.channel}-source-diagnostic-{operation_id}.attempt.json', {})
    elif conflict in {'worker', 'diagnostic-worker'}:
        label = 'yggdrasil.native.operation' if conflict == 'worker' else diagnostic.OWNER_LABEL
        composed.state.rows[-1]['Config']['Labels'][label] = operation_id if conflict == 'worker' else 'a' * 32
    elif conflict == 'lock':
        lock = composed.cfg.root / 'config/deploy' / f'{composed.cfg.channel}.env.lock'
        lock.mkdir(mode=0o700)
        (lock / 'foreign').write_text('foreign')
    elif conflict == 'malformed-lineage':
        linux._atomic_private_json(composed.cfg.journal.directory / (composed.cfg.channel + '.request.json'), {})
    elif conflict == 'pending-lineage':
        composed.cfg.journal.write(str(uuid4()), 'prepared')
    else:
        finished = threading.Event()
        if conflict in {'live-thread', 'foreign-supervisor'}:
            finished.set()
        composed.supervisor.operation = SimpleNamespace(
            finished=finished, thread=SimpleNamespace(is_alive=lambda: conflict != 'foreign-supervisor'),
            operation_id=str(uuid4()),
        )
    before = copy.deepcopy(composed.state.rows)
    assert composed.invoke(persist=persist, operation_id=operation_id,
                           extra=('--prove-source-operation-never-admitted',))[0] == 78
    assert composed.controller.source_persistence_preflight(composed.cfg.channel)['ready'] is False
    assert not composed.state.events and not composed.state.workers and composed.state.producer_calls == 0
    assert composed.state.rows == before


@pytest.mark.parametrize('persist', [False, True])
@pytest.mark.parametrize('field', ['operation_id', 'channel', 'source_kind', 'source_mode',
                                  'native_worker_absent', 'native_attempt_retired', 'request_fingerprint'])
def test_current_absence_proof_cannot_retire_a_different_host_binding(composed, persist, field):
    operation_id = str(uuid4())
    composed.state.fail = 'pre-dispatch'
    assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    composed.state.fail = None
    carrier = subprocess.run
    def altered(argv, **kwargs):
        result = carrier(argv, **kwargs)
        if argv[0] == 'ssh' and json.loads(kwargs['input'])['action'] == 'source-identity-prove-absence':
            response = json.loads(result.stdout)
            response['source_identity_absence'][field] = False if field.startswith('native_') else 'foreign'
            return subprocess.CompletedProcess(argv, 0, json.dumps(response), '')
        return result
    composed.monkeypatch.setattr(subprocess, 'run', altered)
    assert composed.invoke(persist=persist, operation_id=operation_id,
                           extra=('--prove-source-operation-never-admitted',))[0] == 78
    assert composed.controller.source_persistence_preflight(composed.cfg.channel)['ready'] is False
    assert not composed.state.events and not composed.state.workers


@pytest.mark.parametrize('persist', [False, True])
@pytest.mark.parametrize('interruption', ['before-write', 'after-write', 'mismatched-write'])
def test_absence_retirement_requires_durable_exact_readback(composed, persist, interruption):
    operation_id = str(uuid4())
    composed.state.fail = 'pre-dispatch'
    assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    composed.state.fail = None
    atomic = linux._atomic_private_json
    def interrupted(path, payload):
        if payload.get('contract') != 'native-source-identity-absence.v1':
            return atomic(path, payload)
        if interruption == 'before-write':
            raise OSError('synthetic write interruption')
        if interruption == 'mismatched-write':
            payload = {**payload, 'source_request': {**payload['source_request'], 'image_digest': 'sha256:' + 'a' * 64}}
        atomic(path, payload)
        if interruption == 'after-write':
            raise OSError('synthetic acknowledgement interruption')
    composed.monkeypatch.setattr(linux, '_atomic_private_json', interrupted)
    assert composed.invoke(persist=persist, operation_id=operation_id,
                           extra=('--prove-source-operation-never-admitted',))[0] == 78
    assert composed.controller.source_persistence_preflight(composed.cfg.channel)['ready'] is False
    assert not composed.state.events and not composed.state.workers
    composed.monkeypatch.setattr(linux, '_atomic_private_json', atomic)
    result = composed.invoke(persist=persist, operation_id=operation_id,
                             extra=('--prove-source-operation-never-admitted',))[0]
    assert result == (78 if interruption == 'mismatched-write' else 0)
    assert not composed.state.events and not composed.state.workers and composed.state.metadata_calls == 0


@pytest.mark.parametrize('persist', [False, True])
@pytest.mark.parametrize('proof', [False, True])
@pytest.mark.parametrize('option,value', [('--image-digest', 'sha256:' + 'a' * 64),
                                        ('--authority-cutover-binding', 'binding-foreign'),
                                        ('--authority-cutover-root', '/synthetic-other-root'),
                                        ('--authority-cutover-ownership-root', '/synthetic-other-owner')])
def test_host_current_request_is_bound_before_native_admission(composed, persist, proof, option, value):
    operation_id = str(uuid4())
    composed.state.fail = 'pre-dispatch'
    assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    composed.state.fail = None
    journal = composed.controller.directory / 'operations.jsonl'
    before = journal.read_bytes()
    count = len(composed.state.rpc)
    extra = (option, value, *(('--prove-source-operation-never-admitted',) if proof else ()))
    assert composed.invoke(persist=persist, operation_id=operation_id, extra=extra)[0] == 78
    assert journal.read_bytes() == before and len(composed.state.rpc) == count
    assert not composed.state.workers and not composed.state.events


@pytest.mark.parametrize('persist', [False, True])
@pytest.mark.parametrize('history', ['committed', 'aborted', 'pending', 'malformed'])
def test_current_admission_preserves_recorded_bootstrap_lineage(composed, persist, history):
    if persist:
        composed.note.write_text('source\n')
    journal = composed.cfg.journal
    old = journal.read()
    plan = journal.bound_plan(old.operation_id)
    operation_id = str(uuid4())
    journal.bind_request(operation_id, plan, True, create=True)
    journal.write(operation_id, 'prepared')
    if history == 'committed':
        for stage in ('preflighted', 'materialized', 'activating', 'committed'):
            journal.write(operation_id, stage)
    elif history != 'pending':
        journal.write(operation_id, 'aborted')
    request = journal.directory / (composed.cfg.channel + '.request.json')
    if history == 'malformed':
        payload = json.loads(request.read_text())
        payload['bootstrap'] = 'true'
        linux._atomic_private_json(request, payload)
    before = request.read_bytes()
    code, output = composed.invoke(persist=persist)
    assert code == (0 if history in {'committed', 'aborted'} else 78), (output, composed.state.errors)
    assert request.read_bytes() == before
    if history in {'pending', 'malformed'}:
        assert not composed.state.workers and not composed.state.events


@pytest.mark.parametrize('fault', ['extra', 'channel', 'digest', 'empty', 'oversized', 'duplicate',
                                  'password-env', 'not-tmpfs', 'target-drift'])
def test_real_witness_cli_refuses_credential_envelope_without_connect(composed, fault):
    composed.state.witness_fault = fault
    code, output = composed.invoke()
    assert code == 78
    assert not composed.state.credential_paths and not composed.state.connection.queries
    assert 'synthetic-witness-secret' not in output and str(composed.note) not in output
    assert json.loads(output)['terminal_state'] == 'refused'


def test_witness_uses_admitted_pin_target_not_runtime_env_file(composed):
    runtime_file = composed.cfg.root / 'runtime.env'
    runtime_file.write_text(runtime_file.read_text().replace('host=db', 'host=old-runtime-db'))
    pin = composed.cfg.root / 'config/deploy' / (composed.cfg.channel + '.env')
    target = f'postgresql+psycopg:///?host=db&port=5432&dbname=app_{composed.cfg.channel}&user=app'
    pin.write_text(pin.read_text() + f'DATABASE_URL={target}\n')
    code, output = composed.invoke()
    assert code == 0, output
    assert composed.state.connected_fields == [{
        'host': 'db', 'port': '5432', 'dbname': 'app_' + composed.cfg.channel, 'user': 'app',
    }]
    assert 'old-runtime-db' not in output


def test_witness_unlink_interruption_is_failed_and_token_cleanup_retires_tmpfs(composed):
    operation_id = str(uuid4())
    composed.state.witness_fault = 'unlink'
    code, output = composed.invoke(operation_id=operation_id)
    assert code == 78 and json.loads(output)['terminal_state'] == 'refused'
    assert composed.state.credential_paths and composed.state.removed_witnesses
    assert all(not path.exists() for path in composed.state.credential_paths)
    assert composed.state.retained_witness is None
    assert 'synthetic-witness-secret' not in output
    count = len(composed.state.workers)
    composed.state.witness_fault = None
    assert composed.invoke(operation_id=operation_id)[0] == 78
    assert len(composed.state.workers) == count


@pytest.mark.parametrize('persist', [False, True])
def test_retained_owned_one_shot_cleanup_precedes_complete_census(composed, persist):
    if persist:
        composed.note.write_text('source\n')
    before = copy.deepcopy(composed.state.rows)
    operation_id = str(uuid4())
    composed.state.fail = 'retain-producer' if persist else 'retain-witness'
    assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    assert len(composed.state.rows) == 4
    assert linux.LinuxEffects(composed.cfg).channel_lock_owner() is not None
    count = (composed.state.producer_calls, len(composed.state.workers))
    composed.state.fail = None
    assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    assert (composed.state.producer_calls, len(composed.state.workers)) == count
    assert len(composed.state.rows) == 3
    assert [row['State']['Running'] for row in composed.state.rows] == [row['State']['Running'] for row in before]
    assert composed.state.rows[-1] == before[-1]
    assert linux.LinuxEffects(composed.cfg).channel_lock_owner() is None


@pytest.mark.parametrize('persist', [False, True])
@pytest.mark.parametrize('fault', ['image', 'owner-label', 'candidate'])
def test_retained_one_shot_cleanup_cannot_borrow_foreign_binding(composed, persist, fault):
    if persist:
        composed.note.write_text('source\n')
    operation_id = str(uuid4())
    composed.state.fail = 'retain-producer' if persist else 'retain-witness'
    assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    owned = composed.state.rows[-1]
    composed.state.fail = None
    if fault == 'image':
        owned['Config']['Image'] = 'ghcr.io/rasmustho/pkm-app@sha256:' + 'a' * 64
    elif fault == 'owner-label':
        key = 'yggdrasil.native.operation' if persist else diagnostic.OWNER_LABEL
        owned['Config']['Labels'][key] = 'foreign'
    before = copy.deepcopy(composed.state.rows)
    events = len(composed.state.events)
    if fault == 'candidate':
        payload = {**composed.state.rpc[-1], 'cleanup_only': True, 'image_digest': 'sha256:' + 'a' * 64}
        with pytest.raises(PostgresDeployError):
            composed.supervisor.request(payload)
    else:
        assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    assert composed.state.rows == before and len(composed.state.events) == events
    assert linux.LinuxEffects(composed.cfg).channel_lock_owner() is not None


@pytest.mark.parametrize('persist', [False, True])
@pytest.mark.parametrize('drift', ['census', 'authority'])
def test_owned_one_shot_cleanup_does_not_bypass_failed_postproof(composed, persist, drift):
    if persist:
        composed.note.write_text('source\n')
    operation_id = str(uuid4())
    composed.state.fail = 'retain-producer' if persist else 'retain-witness'
    assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    if drift == 'census':
        composed.state.rows[2]['Config']['User'] = '0:0'
    else:
        composed.runtime.registry.path.write_text('malformed synthetic authority\n')
    composed.state.fail = None
    count = (composed.state.producer_calls, len(composed.state.workers))
    event_count = len(composed.state.events)
    assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    assert len(composed.state.rows) == 3
    assert (composed.state.producer_calls, len(composed.state.workers)) == count
    assert not any(action == 'start' for action, _ in composed.state.events[event_count:])
    assert linux.LinuxEffects(composed.cfg).channel_lock_owner() is not None


@pytest.mark.parametrize('spelling', ['uppercase', 'hex'])
def test_registry_noncanonical_late_uuid_refuses_before_earlier_writable_source(composed, spelling):
    identity = str(uuid4())
    declared = identity.upper() if spelling == 'uppercase' else identity.replace('-', '')
    later = composed.note.with_name('z.md')
    composed.note.rename(later)
    later.write_text(f'---\nuuid: "{declared}"\n---\nlater source\n')
    later.with_name('a.md').write_text('earlier writable source without UUID\n')
    before = {path: path.read_bytes() for path in later.parent.glob('*.md')}
    code, output = composed.invoke(persist=True)
    assert code == 78 and json.loads(output)['eligible'] is False
    assert composed.state.metadata_calls == 0
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize('evidence', ['malformed', 'legacy-malformed', 'symlink', 'directory', 'fifo',
                                     'duplicate', 'wrong-uuid', 'wrong-source', 'legacy-stale',
                                     'parent-alias', 'parent-file'])
def test_registry_companion_refusal_precedes_every_metadata_effect(composed, evidence):
    from app.services.companion_note import companion_path
    identity = str(uuid4())
    later = composed.note.with_name('z.md')
    composed.note.rename(later)
    later.write_text(f'---\nuuid: {identity}\n---\nlater source\n')
    later.with_name('a.md').write_text('earlier writable source without UUID\n')
    root = later.parent
    canonical = root / companion_path(identity, root)
    legacy = root / '_system' / 'companions' / f'{identity}.md'
    assert canonical != legacy
    canonical.parent.mkdir(parents=True, exist_ok=True)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    metadata = {'uuid': identity, 'source_ref': 'z.md',
                'content_hash': hashlib.sha256(b'later source\n').hexdigest()}
    if evidence == 'wrong-uuid':
        metadata['uuid'] = str(uuid4())
    if evidence == 'wrong-source':
        metadata['source_ref'] = 'different.md'
    if evidence == 'legacy-stale':
        metadata['content_hash'] = '0' * 64
    valid = '---\n' + yaml.safe_dump(metadata) + '---\n'
    if evidence == 'malformed':
        canonical.write_text('malformed companion\n')
    elif evidence.startswith('legacy-'):
        legacy.write_text('malformed companion\n' if evidence == 'legacy-malformed' else valid)
    elif evidence == 'symlink':
        canonical.symlink_to(later)
    elif evidence == 'directory':
        canonical.mkdir()
    elif evidence == 'fifo':
        os.mkfifo(canonical)
    elif evidence in {'parent-alias', 'parent-file'}:
        canonical.parent.rmdir()
        if evidence == 'parent-alias':
            canonical.parent.symlink_to(legacy.parent, target_is_directory=True)
        else:
            canonical.parent.write_text('not a directory\n')
    else:
        canonical.write_text(valid)
        if evidence == 'duplicate':
            legacy.write_text(valid)
    before = {path: path.read_bytes() for path in root.glob('*.md')}
    # Snapshot regular evidence only; never read the synthetic FIFO/alias.
    regular = {path: path.read_bytes() for path in (canonical, legacy)
               if path.is_file() and not path.is_symlink()}
    code, output = composed.invoke(persist=True)
    assert code == 78 and json.loads(output)['eligible'] is False
    assert composed.state.metadata_calls == 0
    assert {path: path.read_bytes() for path in before} == before
    assert all(path.read_bytes() == value for path, value in regular.items())


@pytest.mark.parametrize('location', ['canonical', 'legacy'])
def test_shared_strict_guard_preserves_valid_companion_without_rewrite(composed, location):
    from app.rebuildability import canonical_product_body_text
    from app.services.companion_note import companion_path
    identity = str(uuid4())
    composed.note.write_text(f'---\nuuid: {identity}\n---\nsource\n')
    root = composed.note.parent
    relative = companion_path(identity, root) if location == 'canonical' else Path('_system/companions') / f'{identity}.md'
    companion = root / relative
    companion.parent.mkdir(parents=True, exist_ok=True)
    metadata = {'uuid': identity, 'source_ref': composed.note.name,
                'content_hash': hashlib.sha256(canonical_product_body_text('source\n').encode()).hexdigest()}
    companion.write_text('---\n' + yaml.safe_dump(metadata) + '---\n')
    before = (composed.note.read_bytes(), companion.read_bytes())
    code, output = composed.invoke(persist=True)
    assert code == 0, (output, composed.state.errors)
    receipt = json.loads(output)
    assert receipt['eligible'] is True and composed.state.metadata_calls == receipt['selected_count']
    assert (composed.note.read_bytes(), companion.read_bytes()) == before


@pytest.mark.parametrize('presentation', ['whitespace', 'wikilink'])
def test_registry_preserves_strict_producer_supported_uuid_presentation(composed, presentation):
    identity = str(uuid4())
    declared = ' ' + identity + ' ' if presentation == 'whitespace' else '[[' + identity + ']]'
    composed.note.write_text(f'---\nuuid: "{declared}"\n---\nsource\n')
    before = composed.note.read_bytes()
    code, output = composed.invoke(persist=True)
    assert code == 0, output
    assert json.loads(output)['eligible'] is True and composed.note.read_bytes() == before


@pytest.mark.parametrize('fault', ['invalid', 'duplicate', 'conflicting-id', 'protected', 'policy-drift'])
def test_current_registry_selection_refuses_before_first_metadata_effect(composed, fault):
    if fault == 'duplicate':
        identity = str(uuid4())
        composed.note.write_text(f'---\nuuid: {identity}\n---\nsource\n')
        composed.note.with_name('second.md').write_bytes(composed.note.read_bytes())
    elif fault == 'conflicting-id':
        composed.note.write_text(f'---\nuuid: {uuid4()}\nid: {uuid4()}\n---\nsource\n')
    elif fault == 'protected':
        composed.note.write_text('---\nagent_maintained: true\nread_only: true\nauthority_role: derived\n---\nsource\n')
    elif fault == 'policy-drift':
        composed.note.write_text('source\n')
        original = persistence._registry_plan
        count = 0
        def changing(root):
            nonlocal count
            result = original(root)
            count += 1
            if count == 1:
                composed.note.with_name('new.md').write_text('new source\n')
            return result
        composed.monkeypatch.setattr(persistence, '_registry_plan', changing)
    before = composed.note.read_bytes()
    code, output = composed.invoke(persist=True)
    assert code == 78 and json.loads(output)['eligible'] is False
    assert composed.state.metadata_calls == 0 and composed.note.read_bytes() == before
    assert composed.state.rows[-1]['State']['Status'] == 'exited'


@pytest.mark.parametrize('fault', ['extra', 'kind', 'channel', 'owner'])
def test_real_registry_channel_lock_marker_is_closed(composed, fault):
    effects = linux.LinuxEffects(composed.cfg)
    effects.operation_id = str(uuid4())
    marker = {'kind': 'source-identity-persistence', 'channel': composed.cfg.channel,
              'operation_id': effects.operation_id, 'producer_kind': 'registry'}
    if fault == 'extra':
        marker['extra'] = 'no'
    elif fault == 'kind':
        marker['producer_kind'] = 'unknown'
    elif fault == 'channel':
        marker['channel'] = 'prod'
    else:
        marker['operation_id'] = str(uuid4())
    with pytest.raises(PostgresDeployError):
        with effects.channel_lock(journal=composed.cfg.journal, owner_marker=marker):
            pytest.fail('invalid marker acquired real lock')
    assert effects.channel_lock_owner() is None


@pytest.mark.parametrize('persist', [False, True])
def test_terminal_publication_interruption_reconciles_without_worker_replay(composed, persist):
    if persist:
        composed.note.write_text('source\n')
    operation_id = str(uuid4())
    original = linux._atomic_private_json
    fired = False
    def crash(path, payload):
        nonlocal fired
        original(path, payload)
        if not fired and path.name.endswith(operation_id + '.json'):
            fired = True
            raise PostgresDeployError()
    composed.monkeypatch.setattr(linux, '_atomic_private_json', crash)
    assert composed.invoke(persist=persist, operation_id=operation_id)[0] == 78
    count = composed.state.producer_calls if persist else len(composed.state.workers)
    composed.monkeypatch.setattr(linux, '_atomic_private_json', original)
    composed.invoke(persist=persist, operation_id=operation_id)
    assert (composed.state.producer_calls if persist else len(composed.state.workers)) == count
    assert linux.LinuxEffects(composed.cfg).channel_lock_owner() is None
