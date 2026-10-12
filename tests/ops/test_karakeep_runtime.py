"""Native wiring fixtures; real-host KMA-06 acceptance remains on #3367."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from io import StringIO
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.ops import karakeep_runtime as kr
from app.ops.postgres_deploy_linux import DeploymentSupervisor, LinuxConfig
from app.ops.postgres_deploy import PostgresDeployError
from app.heimdal.observation_log import read_observations_from, reset_memory_observation_log
from app.heimdal.cursor_store import get_cursor, reset_memory_cursor_store
from app.instance.scalar_binding_runtime import resolve_scalar_binding_runtime
from app.write_guard import WriteGuard
from tests._mvr_default_vault_harness import new_runtime, activate
from tests._mvr03_principal_harness import run_principal_cutover, AuthPosture

pytestmark = pytest.mark.not_pg
ROOT = Path(__file__).resolve().parents[2]
REVISION = 'a' * 40
TOKEN = 'canary-issued-native-api-key-123456789'
ENDPOINT = 'http://172.23.0.5:3000'


@pytest.fixture(autouse=True)
def restore_child_process_logging():
    # Production child() exits its own process. Embedded probes share pytest's
    # process and must restore that child's deliberate logging containment.
    previous = logging.root.manager.disable
    try:
        yield
    finally:
        logging.disable(previous)


@pytest.fixture
def binding(tmp_path, monkeypatch):
    runtime = new_runtime(tmp_path, channel='test')
    root = tmp_path / 'vault'
    (root / 'settings').mkdir(parents=True)
    (root / 'settings/vault.md').write_text('---\nvaultId: native-test-vault\n---\n')
    (root / 'settings/local.md').write_text('---\nlocalInstanceId: native-test-instance\n---\n')
    first = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    activate(runtime, first, tmp_path)
    run_principal_cutover(runtime, channel_id='test', posture=AuthPosture(
        configured_credentials=0, credential=None, loopback_listener_proven=True,
        companion_proxy_configured=False))
    monkeypatch.setenv('PKM_ENVIRONMENT', 'test')
    monkeypatch.setenv('INSTANCE_VAULT_REGISTRY_PATH', str(runtime.registry.path))
    monkeypatch.setenv('INSTANCE_OWNERSHIP_ROOT', str(runtime.ledger.root))
    monkeypatch.setenv('VAULT_ROOT', str(root))
    monkeypatch.setenv('STORE_BACKEND', 'memory')
    reset_memory_observation_log()
    reset_memory_cursor_store()
    resolved = resolve_scalar_binding_runtime(vault_root=root)
    assert resolved is not None and resolved.channel_id == 'test'
    yield resolved
    reset_memory_observation_log()
    reset_memory_cursor_store()


@pytest.fixture
def admission(tmp_path, monkeypatch):
    (tmp_path / 'config/deploy').mkdir(parents=True)
    (tmp_path / 'config/deploy/test.env').write_text('APP_IMAGE_TAG=' + REVISION + '\n')
    config = LinuxConfig('test', tmp_path, tmp_path / 'db', 1000, 1000, str(uuid4()), str(uuid4()))
    environment = {'PKM_ENVIRONMENT': 'test', 'STORE_BACKEND': 'pg', 'VCS_REF': REVISION,
        'DATABASE_URL': 'postgresql://app@db:5432/app_test', 'DB_DSN': 'postgresql://app@db:5432/app_test',
        'DATABASE_PASSWORD_FILE': '/run/secrets/password', 'VAULT_ROOT': '/app/vault', 'VAULT_ROOT_TEST': '/app/vault',
        'INSTANCE_VAULT_REGISTRY_PATH': '/app/instance-state/agentic-pkm/vault-registry.md',
        'INSTANCE_OWNERSHIP_ROOT': '/app/instance-ownership'}
    def row(project, service, address):
        return {'Id': 'b' * 64, 'Image': 'sha256:' + 'c' * 64,
            'Config': {'Labels': {'com.docker.compose.project': project, 'com.docker.compose.service': service},
                       'Env': [key + '=' + value for key, value in environment.items()] if service == 'api' else []},
            'State': {'Running': True}, 'HostConfig': {'NetworkMode': 'bridge'},
            'Mounts': [], 'NetworkSettings': {'Networks': {'qualified-test': {'NetworkID': 'd' * 64, 'IPAddress': address}},
                'Ports': {'3000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '3000'}]} if service == 'karakeep' else {}}}
    rows = {('pkm-test', 'api'): row('pkm-test', 'api', '172.23.0.3'),
            ('pkm-test', 'db'): row('pkm-test', 'db', '172.23.0.4'),
            ('karakeep-test', 'karakeep'): row('karakeep-test', 'karakeep', '172.23.0.5')}
    api = rows['pkm-test', 'api']
    api['Mounts'] = [{'Destination': path, 'RW': True, 'Type': kind, 'Name': name, 'Source': '/private/' + name}
        for path, kind, name in (('/app/vault', 'bind', 'test-vault'), ('/app/instance-state', 'volume', 'pkm-test_instance-state'),
                                ('/app/tmp-test', 'volume', 'pkm-test_runtime-tmp'), ('/app/instance-ownership', 'bind', 'ownership'))]
    rows['pkm-test', 'db']['Mounts'] = [{'Destination': '/var/lib/postgresql/data', 'RW': True,
        'Type': 'volume', 'Name': 'pkm-test_pgdata'}]
    commands = []
    monkeypatch.setattr(kr, '_require_vm_host', lambda: None)
    monkeypatch.setattr(kr, '_container', lambda project, service: deepcopy(rows[project, service]))
    import app.ops.postgres_deploy_linux as linux
    monkeypatch.setattr(linux, '_private_json', lambda path: {'channel': 'test',
        'server_url': 'http://127.0.0.1:13000', 'qualified_at': datetime.now(timezone.utc).isoformat(),
        'qualification_ref': 'https://github.com/RasmusTho/agentic-pkm-mvp/issues/3367#issuecomment-1'})
    def command(argv):
        commands.append(argv)
        if 'rev-parse' in argv:
            return REVISION
        if 'status' in argv:
            return ''
        if 'image' in argv:
            return json.dumps([{'Config': {'Labels': {'org.opencontainers.image.revision': REVISION}}}])
        raise AssertionError(argv)
    monkeypatch.setattr(kr, '_command', command)
    return SimpleNamespace(config=config, rows=rows, environment=environment, commands=commands)


def source():
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path == '/':
            return httpx.Response(200)
        if request.url.path.endswith('/highlights'):
            return httpx.Response(200, json={'highlights': [], 'nextCursor': None})
        return httpx.Response(200, json={'bookmarks': [{'id': 'item-native', 'type': 'link', 'title': 'Reading',
            'note': 'Saved native note', 'content': {'url': 'https://example.com/reading'},
            'createdAt': '2026-07-10T08:15:00+02:00'}], 'nextCursor': None})
    return httpx.Client(transport=httpx.MockTransport(respond)), requests


def test_native_admission_checks_fixed_test_action_and_bindings_before_work(admission, monkeypatch):
    called = []
    monkeypatch.setattr(kr.subprocess, 'Popen', lambda *args, **kwargs: called.append(args))
    for channel in ('dev', 'prod', 'unknown', ''):
        with pytest.raises(kr.RuntimeRefused):
            kr.dispatch(admission.config, {'action': 'karakeep-acquire', 'channel': channel}, lambda: None)
        assert kr.main(['karakeep-acquire', channel]) == 78
    with pytest.raises(kr.RuntimeRefused):
        kr.dispatch(admission.config, {'action': 'sh', 'channel': 'test'}, lambda: None)
    for change in ('revision', 'mount', 'namespace'):
        previous = deepcopy(admission.rows)
        if change == 'revision':
            admission.rows['pkm-test', 'api']['Config']['Env'][2] = 'VCS_REF=unknown'
        elif change == 'mount':
            admission.rows['pkm-test', 'api']['Mounts'][1]['Name'] = 'pkm-prod_instance-state'
        else:
            admission.rows['karakeep-test', 'karakeep']['NetworkSettings']['Networks'] = {'foreign': {'NetworkID': 'x', 'IPAddress': '172.24.0.3'}}
        assert kr.dispatch(admission.config, {'action': 'karakeep-acquire', 'channel': 'test'}, lambda: None)['status'] == 'refused'
        admission.rows.clear()
        admission.rows.update(previous)
    assert called == []
    _, env, endpoint = kr.admitted_runtime(admission.config, 'karakeep-acquire')
    assert endpoint == ENDPOINT and endpoint != 'http://127.0.0.1:13000'
    assert env['KARAKEEP_RUNTIME_DB_ADDRESS'] == '172.23.0.4'
    # Missing actual PG/config or active authority refuses at the real child gate.
    with pytest.raises(kr.RuntimeRefused):
        kr.child_preflight({**env, 'STORE_BACKEND': 'memory'}, 'karakeep-acquire')
    with pytest.raises(kr.RuntimeRefused):
        kr.child_preflight({**env, 'DATABASE_URL': 'postgresql://app@db:5432/app'}, 'karakeep-project')


def test_native_producer_uses_scoped_key_and_published_handoff_only(binding, admission, monkeypatch):
    client, requests = source()
    # Reach the fixed supervisor dispatch, then the actual producer libraries;
    # process/driver fixtures isolate Docker and the secret provider only.
    class Input(StringIO):
        def close(self):
            self.saved = self.getvalue()
    pipe = Input()
    process = SimpleNamespace(stdin=pipe, stdout=StringIO(), wait=lambda timeout: 0, poll=lambda: 0)
    launches, reads = [], []
    monkeypatch.setattr(kr.subprocess, 'Popen', lambda argv, **kw: launches.append((argv, kw)) or process)
    class Reader:
        def lookup(self, project, identity):
            reads.append((project, identity))
            return TOKEN
    monkeypatch.setattr(LinuxConfig, 'reader', lambda self: Reader())
    def read(process, *, seconds):
        if seconds == 25:
            return {'ready': True}
        inputs = json.loads(pipe.getvalue().splitlines()[1])
        return kr.run_bound('karakeep-acquire', binding, inputs, http=client)
    monkeypatch.setattr(kr, '_read_line', read)
    supervisor = DeploymentSupervisor(admission.config)
    monkeypatch.setattr(supervisor, '_require_current_config', lambda: None)
    result = supervisor.request({'action': 'karakeep-acquire', 'channel': 'test'})
    assert result['status'] == 'complete' and result['published'] == 1
    assert reads == [('non-prod', 'test/karakeep.api-key')]
    assert TOKEN not in repr(launches) and ENDPOINT not in repr(launches)
    assert '/usr/bin/env' in launches[0][0] and '-i' in launches[0][0]
    assert launches[0][0][launches[0][0].index('--workdir') + 1] == '/app'
    assert '/usr/local/bin/python' in launches[0][0] and '-s' in launches[0][0]
    assert all(TOKEN == request.headers.get('authorization', '').removeprefix('Bearer ')
               for request in requests if request.url.path.startswith('/api/'))
    assert len(read_observations_from(0)) == 1 and not list(binding.root.rglob('*item-native*.md'))
    assert get_cursor('mimer.candidate_projector') == 0


def test_native_consumer_replays_without_source_and_preserves_guarded_cursor(binding, monkeypatch):
    client, _ = source()
    kr.run_bound('karakeep-acquire', binding, {'endpoint': ENDPOINT, 'token': TOKEN}, http=client)
    def forbidden(*args, **kwargs):
        raise AssertionError('consumer attempted source access')
    monkeypatch.setattr(httpx.Client, 'get', forbidden)
    monkeypatch.setattr(LinuxConfig, 'reader', forbidden)
    blocked = kr.run_bound('karakeep-project', binding, {}, write_guard=WriteGuard(lambda: {'state': 'safe_mode'}))
    assert blocked['status'] == 'blocked' and blocked['consumer_cursor'] == 0
    result = kr.run_bound('karakeep-project', binding, {}, write_guard=WriteGuard(lambda: {'state': 'healthy'}))
    assert result['status'] == 'complete' and result['written'] == 1 and result['consumer_cursor'] == 1
    note = next(binding.root.rglob('*item-native*.md')).read_text()
    assert 'requires_review: true' in note and TOKEN not in note and ENDPOINT not in note
    with pytest.raises(kr.RuntimeRefused):
        kr.run_bound('karakeep-project', binding, {'token': TOKEN})


def test_native_process_overlap_and_restart_keep_constituents_independent(tmp_path, binding):
    # Actual separate interpreter owns the OS flock. Killing it releases only
    # its constituent; no stale-state repair or TTL can authorize overlap.
    code = ('from pathlib import Path; from app.ops.karakeep_runtime import constituent_lock; '
            'import sys;\nwith constituent_lock(Path(sys.argv[1]), "karakeep-acquire"):\n'
            ' print("ready", flush=True); sys.stdin.read()\n')
    process = subprocess.Popen([sys.executable, '-c', code, str(tmp_path)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True, cwd=ROOT)
    try:
        assert process.stdout.readline().strip() == 'ready'
        with pytest.raises(BlockingIOError):
            with kr.constituent_lock(tmp_path, 'karakeep-acquire'):
                pytest.fail('overlap admitted')
        with kr.constituent_lock(tmp_path, 'karakeep-project'):
            pass
    finally:
        process.kill()
        process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
    with kr.constituent_lock(tmp_path, 'karakeep-acquire'):
        pass
    client, _ = source()
    first = kr.run_bound('karakeep-acquire', binding, {'endpoint': ENDPOINT, 'token': TOKEN}, http=client)
    # Every call constructs a fresh cursor; full-log lineage prevents duplicate
    # publication when recovery deliberately rescans page one.
    second = kr.run_bound('karakeep-acquire', binding, {'endpoint': ENDPOINT, 'token': TOKEN}, http=client)
    assert first['published'] == 1 and second['published'] == 0 and second['noops'] == 1
    written = kr.run_bound('karakeep-project', binding, {}, write_guard=WriteGuard(lambda: {'state': 'healthy'}))
    replay = kr.run_bound('karakeep-project', binding, {}, write_guard=WriteGuard(lambda: {'state': 'healthy'}))
    assert written['written'] == 1 and replay['consumed'] == 0 and replay['consumer_cursor'] == 1


def test_native_receipts_and_failures_are_bounded_and_value_free(binding, admission, monkeypatch, capsys):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503, text=TOKEN + ENDPOINT)))
    result = kr.run_bound('karakeep-acquire', binding, {'endpoint': ENDPOINT, 'token': TOKEN}, http=client)
    assert result['status'] == 'gated'
    assert TOKEN not in json.dumps(result) and ENDPOINT not in json.dumps(result)
    with pytest.raises(kr.RuntimeRefused):
        kr.validate_receipt({**result, 'error': TOKEN}, 'karakeep-acquire')
    assert kr.main(['karakeep-acquire', 'test', TOKEN]) == 78
    assert TOKEN not in capsys.readouterr().out
    class Input(StringIO):
        def close(self):
            pass
    process = SimpleNamespace(stdin=Input(), stdout=StringIO(), poll=lambda: 0)
    monkeypatch.setattr(kr.subprocess, 'Popen', lambda *args, **kwargs: process)
    monkeypatch.setattr(LinuxConfig, 'reader', lambda self: SimpleNamespace(lookup=lambda *args: TOKEN))
    count = 0
    def interrupted(process, *, seconds):
        nonlocal count
        count += 1
        if count == 1:
            return {'ready': True}
        raise OSError(TOKEN + ENDPOINT)
    monkeypatch.setattr(kr, '_read_line', interrupted)
    result = kr.dispatch(admission.config, {'action': 'karakeep-acquire', 'channel': 'test'}, lambda: None)
    assert result == {'status': 'pending', 'action': 'karakeep-acquire', 'channel': 'test'}


def test_supervisor_import_does_not_require_product_dependencies():
    code = '''
import sys
class DenyProduct:
 def find_spec(self, fullname, path=None, target=None):
  if fullname in {'httpx', 'pydantic', 'sqlalchemy'} or fullname.startswith(('app.heimdal', 'app.instance', 'app.vault')):
   raise ImportError(fullname)
sys.meta_path.insert(0, DenyProduct())
from app.ops.postgres_deploy_linux import DeploymentSupervisor
from app.ops.karakeep_runtime import require_action
require_action('karakeep-project', 'test')
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def child_runtime(binding, admission, monkeypatch, tmp_path):
    import psycopg
    from app.instance import scalar_binding_runtime as scalar
    from app.heimdal import publish

    environment = {**admission.environment, 'VAULT_ROOT': str(binding.root), 'VAULT_ROOT_TEST': str(binding.root),
                   'KARAKEEP_RUNTIME_DB_ADDRESS': '172.23.0.4'}
    password = tmp_path / 'db-password'
    password.write_text('fixture-only-db-password')
    environment['DATABASE_PASSWORD_FILE'] = str(password)
    queries, connections, log_reads = [], [], []
    actual = ['app_test', '172.23.0.4']
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, sql):
            queries.append(sql)
            return SimpleNamespace(fetchone=lambda: tuple(actual))
    monkeypatch.setattr(psycopg, 'connect', lambda url, **kw: connections.append((url, kw)) or Connection())
    # Map the fixture's volume directories at the existing resolver seam. The
    # resolver/GOV/ownership fence itself remains real, with no selector repair.
    def mounted_binding(*, vault_root):
        os.environ['INSTANCE_VAULT_REGISTRY_PATH'] = str(binding.registry_store.path)
        os.environ['INSTANCE_OWNERSHIP_ROOT'] = str(binding.ownership_ledger.root)
        return resolve_scalar_binding_runtime(vault_root=vault_root)
    monkeypatch.setattr(scalar, 'resolve_scalar_binding_runtime', mounted_binding)
    production_consumer_read = publish.read_observations_for_consumer
    monkeypatch.setattr(publish, 'read_observations_for_consumer', lambda consumer, **kw: log_reads.append((consumer, kw)) or [])
    for key in (*environment, 'STORE_SCHEMA_AUTOCREATE'):
        monkeypatch.setenv(key, os.environ.get(key, ''))
    return SimpleNamespace(environment=environment, queries=queries, connections=connections,
                           log_reads=log_reads, actual=actual, binding=binding,
                           production_consumer_read=production_consumer_read)


def test_child_preflight_checks_actual_pg_server_before_log_or_work(child_runtime):
    state = child_runtime
    selected = kr.child_preflight(state.environment, 'karakeep-project')
    assert selected.vault_binding_id == state.binding.vault_binding_id
    assert state.queries == ['SELECT current_database(), inet_server_addr()::text']
    assert state.connections[0][1] == {'connect_timeout': 5, 'autocommit': True}
    assert 'fixture-only-db-password' in state.connections[0][0]  # file-aware in-memory resolver
    assert state.log_reads == [('mimer.candidate_projector', {'limit': 1})]
    state.log_reads.clear()
    state.actual[1] = '172.24.0.4'
    with pytest.raises(PostgresDeployError):
        kr.child_preflight(state.environment, 'karakeep-acquire')
    assert not state.log_reads  # wrong server refuses before publication or candidate work


def test_producer_preflight_and_publication_survive_isolated_mimer_cursor_fault(child_runtime, monkeypatch, capsys):
    from app.heimdal import observation_log, publish
    from app.heimdal.cursor_store import ObservationCursorSchemaMissingError

    # Recover the production public consumer function masked by the fixture's
    # driver adapter, then inject the actual get_cursor seam it consults.
    monkeypatch.setattr(publish, 'read_observations_for_consumer', child_runtime.production_consumer_read)
    producer_reads, cursor_reads = [], []
    monkeypatch.setattr(observation_log, 'read_observations_from',
                        lambda sequence, **kw: producer_reads.append((sequence, kw)) or [])
    def unavailable_cursor(consumer):
        cursor_reads.append(consumer)
        raise ObservationCursorSchemaMissingError(TOKEN)
    monkeypatch.setattr(publish, 'get_cursor', unavailable_cursor)
    selected = kr.child_preflight(child_runtime.environment, 'karakeep-acquire')
    assert selected.vault_binding_id == child_runtime.binding.vault_binding_id
    assert producer_reads == [(0, {'limit': 1})] and not cursor_reads
    # Actual producer scheduling/adapter/publish path remains usable; the
    # fixture store does not substitute for the PG preflight above.
    monkeypatch.setenv('STORE_BACKEND', 'memory')
    client, _ = source()
    result = kr.run_bound('karakeep-acquire', selected, {'endpoint': ENDPOINT, 'token': TOKEN}, http=client)
    assert result['status'] == 'complete' and result['published'] == 1 and not cursor_reads
    # The consumer must report the isolated cursor fault honestly before ready.
    monkeypatch.setattr(kr.sys, 'stdin', StringIO(json.dumps(child_runtime.environment) + '\n'))
    assert kr.child('karakeep-project', 'test') == 0
    assert json.loads(capsys.readouterr().out) == {'status': 'refused', 'action': 'karakeep-project', 'channel': 'test'}
    assert cursor_reads == ['mimer.candidate_projector']


def test_publication_and_writeback_lost_ack_replay_existing_durable_boundaries(binding, monkeypatch):
    from app.heimdal import karakeep_ingest, candidate_projection
    client, _ = source()
    original = karakeep_ingest.KarakeepAdapter.acquire
    def interrupted_acquire(adapter):
        original(adapter)
        raise KeyboardInterrupt(TOKEN)
    with monkeypatch.context() as patch:
        patch.setattr(karakeep_ingest.KarakeepAdapter, 'acquire', interrupted_acquire)
        with pytest.raises(KeyboardInterrupt):
            kr.run_bound('karakeep-acquire', binding, {'endpoint': ENDPOINT, 'token': TOKEN}, http=client)
    assert len(read_observations_from(0)) == 1
    replay = kr.run_bound('karakeep-acquire', binding, {'endpoint': ENDPOINT, 'token': TOKEN}, http=client)
    assert replay['published'] == 0 and replay['noops'] == 1
    with monkeypatch.context() as patch:
        patch.setattr(candidate_projection, 'advance_cursor_for_consumer',
                      lambda *args: (_ for _ in ()).throw(RuntimeError(TOKEN)))
        failed = kr.run_bound('karakeep-project', binding, {}, write_guard=WriteGuard(lambda: {'state': 'healthy'}))
    assert failed['status'] == 'failed' and get_cursor('mimer.candidate_projector') == 0
    assert len(list(binding.root.rglob('*item-native*.md'))) == 1
    replay = kr.run_bound('karakeep-project', binding, {}, write_guard=WriteGuard(lambda: {'state': 'healthy'}))
    assert replay['already_exists'] == 1 and replay['consumer_cursor'] == 1


def test_container_discovery_reads_closed_selected_fields(admission, monkeypatch):
    calls = []
    def command(argv):
        calls.append(argv)
        return 'b' * 64 if 'ps' in argv else json.dumps(admission.rows['pkm-test', 'api'])
    monkeypatch.undo()  # exercise discovery, rather than the admission fixture's Docker adapter
    monkeypatch.setattr(kr, '_command', command)
    row = kr._container('pkm-test', 'api')
    assert row['Id'] == 'b' * 64 and len(calls) == 2
    assert calls[0][1:3] == ['--host', 'unix:///var/run/docker.sock']
    assert '--format' in calls[1]
    calls.clear()
    monkeypatch.setattr(kr, '_command', lambda argv: 'b' * 64 + '\n' + 'c' * 64)
    with pytest.raises(kr.RuntimeRefused):
        kr._container('pkm-test', 'api')


@pytest.mark.parametrize('fault', ['timeout', 'nonzero', 'malformed', 'oversized', 'invalid_receipt'])
def test_main_preserves_pending_after_started_ssh_loses_ack(fault, monkeypatch, capsys):
    # Production outer caller: the remote may have durably worked in every case.
    calls = []
    def invoke(argv, **kwargs):
        calls.append((argv, kwargs))
        if fault == 'timeout':
            raise subprocess.TimeoutExpired(argv, 180, output=TOKEN, stderr=ENDPOINT)
        if fault == 'nonzero':
            return SimpleNamespace(returncode=255, stdout='', stderr=TOKEN)
        if fault == 'malformed':
            return SimpleNamespace(returncode=0, stdout=TOKEN, stderr=ENDPOINT)
        if fault == 'oversized':
            return SimpleNamespace(returncode=0, stdout=TOKEN * 65536, stderr='')
        return SimpleNamespace(returncode=0, stdout=json.dumps({'status': 'complete', 'action': 'sh',
            'channel': 'test', 'error': TOKEN}), stderr='')
    monkeypatch.setattr(kr.subprocess, 'run', invoke)
    assert kr.main(['karakeep-acquire', 'test']) == 78
    assert json.loads(capsys.readouterr().out) == {'status': 'pending', 'action': 'karakeep-acquire', 'channel': 'test'}
    assert len(calls) == 1


@pytest.mark.parametrize('returncode', [0, 78])
def test_main_retains_received_refusal_and_rejects_before_ssh(returncode, monkeypatch, capsys):
    receipt = {'status': 'refused', 'action': 'karakeep-project', 'channel': 'test'}
    calls = []
    monkeypatch.setattr(kr.subprocess, 'run', lambda *args, **kwargs: calls.append(args)
        or SimpleNamespace(returncode=returncode, stdout=json.dumps(receipt), stderr=TOKEN))
    assert kr.main(['karakeep-project', 'prod']) == 78
    assert json.loads(capsys.readouterr().out) == {'status': 'refused', 'channel': 'test'}
    assert not calls
    assert kr.main(['karakeep-project', 'test']) == 78
    assert json.loads(capsys.readouterr().out) == receipt


@pytest.mark.parametrize('destination', [
    '/', '/app', '/app/app', '/app/app/ops/karakeep_runtime.py', '/app/mimer_runtime', '/app/schemas',
    '/app/config', '/app/import_shadow.py', '/usr', '/usr/local', '/usr/local/bin/python',
    '/usr/local/lib/python3.12/site-packages', '/usr/local/lib/python3.12/os.py',
    '/usr/bin/env', '/bin', '/lib/x86_64-linux-gnu', '/etc/ld.so.preload',
])
def test_admission_rejects_code_interpreter_and_dependency_overlays_before_launch(admission, destination, monkeypatch):
    admission.rows['pkm-test', 'api']['Mounts'].append(
        {'Destination': destination, 'Type': 'bind', 'Source': '/fixture-overlay', 'RW': False})
    effects = []
    monkeypatch.setattr(kr.subprocess, 'Popen', lambda *args, **kwargs: effects.append('launch'))
    monkeypatch.setattr(LinuxConfig, 'reader', lambda self: effects.append('reader'))
    result = kr.dispatch(admission.config, {'action': 'karakeep-acquire', 'channel': 'test'}, lambda: None)
    assert result['status'] == 'refused' and effects == []


def test_admission_preserves_existing_data_and_credential_mounts(admission):
    admission.rows['pkm-test', 'api']['Mounts'].extend([
        {'Destination': '/run/secrets/postgres', 'RW': False, 'Type': 'bind'},
        {'Destination': '/app/runtime/dispatcher', 'RW': True, 'Type': 'bind'},
        {'Destination': '/app/tmp', 'RW': True, 'Type': 'volume', 'Name': 'pkm-test_runtime-tmp'},
        {'Destination': '/data/tts', 'RW': True, 'Type': 'bind'},
    ])
    assert kr.admitted_runtime(admission.config, 'karakeep-project')[2] is None


def test_native_consumer_preserves_selected_sources_override(child_runtime, admission, monkeypatch):
    api = admission.rows['pkm-test', 'api']
    api['Config']['Env'].append('VAULT_SOURCES_DIR_REL=ConfiguredSources')
    forwarded = kr._environment(api)
    assert forwarded['VAULT_SOURCES_DIR_REL'] == 'ConfiguredSources'
    environment = {**child_runtime.environment, 'VAULT_SOURCES_DIR_REL': forwarded['VAULT_SOURCES_DIR_REL']}
    monkeypatch.setenv('VAULT_SOURCES_DIR_REL', forwarded['VAULT_SOURCES_DIR_REL'])
    selected = kr.child_preflight(environment, 'karakeep-project')
    monkeypatch.setenv('STORE_BACKEND', 'memory')
    client, _ = source()
    kr.run_bound('karakeep-acquire', selected, {'endpoint': ENDPOINT, 'token': TOKEN}, http=client)
    result = kr.run_bound('karakeep-project', selected, {}, write_guard=WriteGuard(lambda: {'state': 'healthy'}))
    assert result['status'] == 'complete' and result['written'] == 1 and result['consumer_cursor'] == 1
    assert len(list((selected.root / 'ConfiguredSources/Reading/Karakeep').glob('*item-native*.md'))) == 1
    assert not (selected.root / 'Sources').exists()


@pytest.mark.parametrize('unsafe', ['', '/outside', '../outside', 'Sources/../outside'])
def test_invalid_sources_override_refuses_consumer_before_ready_without_gating_producer(
    child_runtime, monkeypatch, capsys, unsafe
):
    from app.heimdal import observation_log
    monkeypatch.setenv('VAULT_SOURCES_DIR_REL', unsafe)
    environment = {**child_runtime.environment, 'VAULT_SOURCES_DIR_REL': unsafe}
    monkeypatch.setattr(kr.sys, 'stdin', StringIO(json.dumps(environment) + '\n'))
    assert kr.child('karakeep-project', 'test') == 0
    assert json.loads(capsys.readouterr().out) == {'status': 'refused', 'action': 'karakeep-project', 'channel': 'test'}
    monkeypatch.setenv('STORE_BACKEND', 'memory')
    assert not child_runtime.log_reads and get_cursor('mimer.candidate_projector') == 0
    monkeypatch.setattr(observation_log, 'read_observations_from', lambda *args, **kwargs: [])
    assert kr.child_preflight(environment, 'karakeep-acquire').vault_binding_id == child_runtime.binding.vault_binding_id
