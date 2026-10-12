from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
import json
import fcntl
import os
from pathlib import Path
from types import SimpleNamespace
import threading
from uuid import uuid4

import pytest
import yaml

from app.ops import karakeep_deploy as kd
from app.ops.bws_secret_admin import BwsAdminConfig, BwsSecretAdmin, SecretAdminError, SecretCopy
from app.ops.bws_secret_reader import BwsItemAbsent, BwsLookupError, BwsReaderConfig, BwsSecretReader
from app.ops.host_secret_bootstrap import HostSecretBootstrapError, resolve_host_secret_values
from app.ops.host_secret_contract import KARAKEEP_GRANTS, load_host_secret_contract
from app.ops.host_secret_controller import HostSecretAdmissionError, HostSecretController
from app.ops.postgres_deploy import DeployJournal, DeployPlan, PostgresDeployError
from app.ops.postgres_deploy_linux import LinuxConfig, LinuxEffects, DeploymentSupervisor
from app.ops.secret_admin import SecretAdmin, main as secrets_main

pytestmark = pytest.mark.not_pg
ROOT = Path(__file__).resolve().parents[2]
REVISION = 'a' * 40
SESSION = 'canary_session_' + 's' * 40
SEARCH = 'canary_search_' + 'k' * 40
API = 'canary-issued-karakeep-api-key-123456789'


class Provider:
    def __init__(self, channel='dev'):
        self.values = {('non-prod', channel + '/karakeep.session-token'): SESSION,
                       ('non-prod', channel + '/karakeep.search-token'): SEARCH}
        self.calls = []

    def lookup(self, project, identity):
        self.calls.append(('read', project, identity))
        if (project, identity) not in self.values:
            raise BwsItemAbsent()
        return self.values[project, identity]

    def read(self, project, identity):
        self.calls.append(('read', project, identity))
        value = self.values.get((project, identity))
        return SecretCopy(str(uuid4()), value, '') if value is not None else None

    def put(self, project, identity, previous, value, note):
        self.calls.append(('put', project, identity))
        self.values[project, identity] = value
        return SecretCopy(previous.item_id if previous else str(uuid4()), value, note)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = tmp_path / 'checkout'
    root.mkdir()
    (root / 'config/deploy').mkdir(parents=True)
    manifest = (ROOT / 'docker-compose.karakeep.yml').read_text()
    (root / 'docker-compose.karakeep.yml').write_text(manifest)
    config = LinuxConfig('dev', root, tmp_path / 'data', 1000, 1000,
                         str(uuid4()), str(uuid4()))
    effects = kd.KarakeepEffects(config)
    effects.runtime = tmp_path / 'run/dev'
    effects.journal = DeployJournal(tmp_path / 'journal', 'dev')
    effects.unit_directory = tmp_path / 'units'
    effects.unit_directory.mkdir()
    provider = Provider()
    monkeypatch.setattr(LinuxConfig, 'reader', lambda self: provider)
    monkeypatch.setattr(kd.socket, 'gethostname', lambda: 'ygg-dev')
    settings = {'channel': 'dev', 'server_url': 'http://127.0.0.1:13000',
                'qualification_ref': 'https://github.com/RasmusTho/agentic-pkm-mvp/issues/3367#issuecomment-1',
                'qualified_at': datetime.now(timezone.utc).isoformat()}
    monkeypatch.setattr(kd, '_private_json', lambda path: settings if path.name == 'dev.json'
                        else json.loads(path.read_text()))
    state = SimpleNamespace(running=False, calls=[], fail=False, inspected=[], filesystem='tmpfs', restart='on-failure')

    def command(argv, *, env=None, timeout=30):
        state.calls.append((argv, env))
        if argv[0] == 'stat':
            return state.filesystem
        if argv[0] == 'git':
            return REVISION + '\n' if argv[-2:] == ['rev-parse', 'HEAD'] else manifest
        if 'info' in argv:
            return 'engine-id'
        if 'version' in argv:
            return '2.30.0'
        if 'ps' in argv:
            return 'web\nsearch\n' if state.running else ''
        if 'inspect' in argv:
            state.inspected.append(argv)
            return '\n'.join(json.dumps({
                'service': service, 'image': image,
                'restart': {'Name': state.restart, 'MaximumRetryCount': 0},
                'ports': {'3000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '3000'}]} if service == 'karakeep' else {},
                'mounts': [{'Type': 'volume', 'Name': effects.project + '_' + (
                    'karakeep-data' if service == 'karakeep' else 'karakeep-meilisearch-data')}],
                'state': {'Running': True, 'Health': {'Status': 'healthy'}},
            }) for service, image in kd.IMAGES.items())
        if 'up' in argv:
            # Reach the production Compose call with the real manifest and
            # actual consumer files; no combined config can deliver the token.
            shape = yaml.safe_load(manifest)
            web = Path(env['KARAKEEP_WEB_ENV_FILE']).read_text()
            search = Path(env['KARAKEEP_SEARCH_ENV_FILE']).read_text()
            assert API not in web + search
            assert SESSION in web and SESSION not in search and SEARCH in web + search
            assert shape['services']['karakeep']['ports'] == ['127.0.0.1:3000:3000']
            assert (root / 'config/deploy/dev.env.lock/bws-owner').exists()
            state.running = True
            if state.fail:
                raise RuntimeError(API)
        return ''

    monkeypatch.setattr(kd, '_command', command)
    supervisor = kd.KarakeepSupervisor(effects)
    admin = SecretAdmin(provider, controller=HostSecretController(tmp_path / 'controller'))

    class Remote(kd.SshKarakeepRemote):
        def request(self, action, operation_id, plan):
            state.calls.append(([action], None))
            return supervisor.request({'action': action, 'operation_id': operation_id, 'plan': plan.payload()})

    return SimpleNamespace(effects=effects, supervisor=supervisor, remote=Remote(), admin=admin,
                           provider=provider, state=state, settings=settings,
                           plan=kd.KarakeepPlan('dev', REVISION))


def deploy(runtime, **options):
    return kd.deploy_from_host(runtime.admin, runtime.remote, runtime.plan,
                               qualified=lambda: None, **options)


def test_declared_consumers_are_nonprod_and_service_does_not_require_api_token(runtime):
    contract = load_host_secret_contract()
    for channel in ('dev', 'test'):
        for consumer, secrets in KARAKEEP_GRANTS.items():
            assert {secret for ch, name, secret in contract.allowed if ch == channel and name == consumer} == secrets
    for channel, consumer, secret in [('prod', 'karakeep-service-web', 'karakeep.session-token'),
                                     ('dev', 'heimdal-api-ingress', 'karakeep.api-key'),
                                     ('dev', 'mimer-worker-main', 'karakeep.api-key')]:
        with pytest.raises(ValueError):
            contract.require_declared(channel=channel, consumer=consumer, secret=secret)
    assert deploy(runtime).terminal_result == 'committed'
    assert not any('api-key' in identity for _, _, identity in runtime.provider.calls)
    with pytest.raises(HostSecretBootstrapError):
        resolve_host_secret_values(channel='prod', consumer='heimdal-karakeep-fetch', provider='bws',
                                   bws_reader=runtime.provider, controller=runtime.admin.controller)
    with pytest.raises(HostSecretBootstrapError):
        resolve_host_secret_values(channel='dev', consumer='heimdal-karakeep-fetch', provider='keychain',
                                   keychain_lookup=lambda *args: API)
    runtime.provider.values['non-prod', 'dev/karakeep.api-key'] = API
    resolved = resolve_host_secret_values(channel='dev', consumer='heimdal-karakeep-fetch', provider='bws',
                                          bws_reader=runtime.provider, controller=runtime.admin.controller)
    assert resolved == {'karakeep.api-key': API}
    assert contract.binding_for('karakeep.api-key') == 'KARAKEEP_API_TOKEN'


def test_deploy_preflight_precedes_mutation_and_isolates_private_channels(runtime):
    runtime.provider.values.pop(('non-prod', 'dev/karakeep.search-token'))
    with pytest.raises(kd.KarakeepDeployError):
        deploy(runtime)
    assert not runtime.state.calls
    assert not runtime.effects.runtime.exists()
    runtime.provider.values['non-prod', 'dev/karakeep.search-token'] = SEARCH
    runtime.settings['server_url'] = 'http://0.0.0.0:3000'
    with pytest.raises(kd.KarakeepDeployError):
        deploy(runtime)
    assert not runtime.effects.runtime.exists()
    assert not runtime.effects.journal.directory.exists()
    runtime.settings['server_url'] = 'http://127.0.0.1:13000'
    assert deploy(runtime).terminal_result == 'committed'
    calls = [argv for argv, _ in runtime.state.calls]
    assert calls.index(['karakeep-preflight']) < calls.index(['karakeep-deploy'])
    compose = next(argv for argv in calls if 'up' in argv)
    assert compose[compose.index('--project-name') + 1] == 'karakeep-dev'
    cfg = runtime.effects.config
    other = kd.KarakeepEffects(LinuxConfig('test', cfg.root, cfg.data_directory, cfg.uid, cfg.gid,
                                          cfg.organization_id, cfg.project_id))
    assert other.project == 'karakeep-test' and other.runtime != runtime.effects.runtime
    assert all('Config.Env' not in str(argv) for argv in runtime.state.inspected)
    runtime.provider.calls.clear()
    runtime.state.calls.clear()
    with pytest.raises(kd.KarakeepDeployError):
        kd.deploy_from_host(runtime.admin, runtime.remote, kd.KarakeepPlan('prod', REVISION), qualified=lambda: None)
    assert not runtime.provider.calls and not runtime.state.calls


def test_account_setup_password_is_separate_nonprod_and_not_required_by_service(runtime):
    contract = load_host_secret_contract()
    assert contract.kind_for('karakeep.account-pass') == 'password'
    assert deploy(runtime).terminal_result == 'committed'
    assert not any('account-pass' in identity for _, _, identity in runtime.provider.calls)
    for channel in ('dev', 'test'):
        password = 'fixture account recovery password'
        runtime.admin.import_stdin(channel, 'karakeep.account-pass', StringIO(password))
        resolved = resolve_host_secret_values(channel=channel, consumer='karakeep-account-setup', provider='bws',
                                              bws_reader=runtime.provider, controller=runtime.admin.controller)
        assert resolved == {'karakeep.account-pass': password}
        assert contract.consumers_declared_for(channel=channel, secret='karakeep.account-pass') == {'karakeep-account-setup'}
        for secret in ('karakeep.api-key', 'karakeep.session-token', 'karakeep.search-token'):
            with pytest.raises(ValueError):
                contract.require_declared(channel=channel, consumer='karakeep-account-setup', secret=secret)
    runtime.provider.calls.clear()
    with pytest.raises(SecretAdminError):
        runtime.admin.import_stdin('prod', 'karakeep.account-pass', StringIO(password))
    with pytest.raises(HostSecretBootstrapError):
        resolve_host_secret_values(channel='prod', consumer='karakeep-account-setup', provider='bws',
                                   bws_reader=runtime.provider, controller=runtime.admin.controller)
    assert not runtime.provider.calls


def test_secret_delivery_is_scoped_ephemeral_and_rehydrated(runtime, monkeypatch):
    first = deploy(runtime)
    web, search = runtime.effects.runtime / 'web.env', runtime.effects.runtime / 'search.env'
    assert web.stat().st_mode & 0o777 == search.stat().st_mode & 0o777 == 0o600
    assert runtime.effects.runtime.stat().st_mode & 0o777 == 0o700
    assert 'NEXTAUTH_SECRET=' + SESSION in web.read_text()
    assert search.read_text() == 'MEILI_MASTER_KEY=' + SEARCH + '\n'
    assert 'KARAKEEP_API_TOKEN' not in web.read_text() + search.read_text()
    ordinary = ''.join(path.read_text() for path in runtime.effects.unit_directory.iterdir())
    ordinary += (runtime.effects.config.root / 'docker-compose.karakeep.yml').read_text()
    assert SESSION not in ordinary and SEARCH not in ordinary
    web.unlink()
    search.unlink()
    monkeypatch.setattr(kd, '_require_vm_root', lambda: None)
    monkeypatch.setattr(kd, '_installation_journal', lambda channel: runtime.effects.journal)
    monkeypatch.setattr(kd, 'rpc', lambda channel, request: runtime.supervisor.request(request))
    kd.boot('dev')  # actual unit call-site flow, not just a worker-method assertion
    assert SESSION in web.read_text() and search.read_text() == 'MEILI_MASTER_KEY=' + SEARCH + '\n'
    assert runtime.effects.journal.read() == first
    latest = runtime.effects.boot_journal.read()
    assert latest.terminal_result == 'committed' and latest.operation_id != first.operation_id
    assert not (runtime.effects.config.root / 'config/deploy/dev.env.lock').exists()


def test_rerun_preserves_data_and_unknown_outcome_blocks_duplicate(runtime):
    first = deploy(runtime)
    initial = dict(runtime.provider.values)
    assert deploy(runtime, operation_id=first.operation_id).operation_id == first.operation_id
    assert sum('up' in argv for argv, _ in runtime.state.calls) == 1
    assert deploy(runtime).terminal_result == 'committed'
    assert runtime.provider.values == initial
    assert not any('down' in argv or '-v' in argv for argv, _ in runtime.state.calls)
    runtime.state.fail = True
    with pytest.raises(kd.KarakeepDeployError, match='value-free') as error:
        deploy(runtime)
    assert API not in str(error.value)
    pending = runtime.effects.journal.read()
    assert pending.stage == 'activating' and pending.terminal_result is None
    assert (runtime.effects.config.root / 'config/deploy/dev.env.lock').exists()
    before = sum('up' in argv for argv, _ in runtime.state.calls)
    with pytest.raises(kd.KarakeepDeployError):
        deploy(runtime)
    assert before == sum('up' in argv for argv, _ in runtime.state.calls)
    # Supervisor restart cannot recreate a missing worker or bless healthy
    # containers after an unacknowledged activation.
    lost = kd.KarakeepSupervisor(runtime.effects)
    assert lost.request({'action': 'karakeep-status', 'operation_id': pending.operation_id,
                         'plan': runtime.plan.payload()}) == {'unknown': True}
    with pytest.raises(HostSecretAdmissionError):
        runtime.admin.controller.admit('check', 'dev').__enter__()


def test_boot_refuses_busy_channel_lock_without_compose_or_lock_retirement(runtime, monkeypatch):
    first = deploy(runtime)
    other = LinuxEffects(runtime.effects.config)
    monkeypatch.setattr(kd, '_require_vm_root', lambda: None)
    monkeypatch.setattr(kd, '_installation_journal', lambda channel: runtime.effects.journal)
    monkeypatch.setattr(kd, 'rpc', lambda channel, request: runtime.supervisor.request(request))
    # A live Mimer deploy/token refresh owns this same mkdir/flock admission.
    mimer = DeployJournal(runtime.effects.journal.directory / 'mimer-fixture', 'dev')
    other.operation_id = str(uuid4())
    with other.channel_lock(journal=mimer):
        before = sum('up' in argv for argv, _ in runtime.state.calls)
        with pytest.raises(kd.KarakeepDeployError):
            kd.boot('dev')
        assert before == sum('up' in argv for argv, _ in runtime.state.calls)
        assert (runtime.effects.config.root / 'config/deploy/dev.env.lock/bws-owner').exists()
        # Only the other owner's own terminal evidence retires its lock.
        for stage in ('prepared', 'preflighted', 'materialized', 'activating', 'committed'):
            mimer.write(other.operation_id, stage)
    assert not (runtime.effects.config.root / 'config/deploy/dev.env.lock').exists()
    assert runtime.effects.journal.read() == first
    assert runtime.effects.boot_journal.read() is None
    kd.boot('dev')  # contention cleared: approved installation is still bootable
    assert runtime.effects.journal.read() == first
    assert runtime.effects.boot_journal.read().terminal_result == 'committed'


def test_controller_prepares_only_absent_service_keys_and_never_invents_api_token(tmp_path, capsys):
    provider = Provider()
    provider.values.clear()
    admin = SecretAdmin(provider, controller=HostSecretController(tmp_path / 'controller'))
    assert secrets_main(['prepare-karakeep', 'dev'], admin=admin) == 0
    retained = dict(provider.values)
    assert set(retained) == {('non-prod', 'dev/karakeep.session-token'),
                             ('non-prod', 'dev/karakeep.search-token')}
    assert secrets_main(['prepare-karakeep', 'dev'], admin=admin) == 0
    assert retained == provider.values
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'karakeep.session-token', StringIO(SESSION))
    assert retained == provider.values
    provider.calls.clear()
    assert secrets_main(['prepare-karakeep', 'prod'], admin=admin) == 1
    assert not provider.calls
    assert all(value not in str(capsys.readouterr()) for value in retained.values())


def test_subprocess_boundary_scrubs_ambient_secrets_and_errors(monkeypatch):
    observed = []
    def runner(argv, **options):
        observed.append((argv, options))
        return SimpleNamespace(returncode=1, stdout=SESSION, stderr=API)
    monkeypatch.setenv('BWS_ACCESS_TOKEN', API)
    monkeypatch.setenv('KARAKEEP_API_TOKEN', API)
    monkeypatch.setattr(kd.subprocess, 'run', runner)
    with pytest.raises(kd.KarakeepDeployError) as error:
        kd._command(['docker', 'compose', 'up'])
    assert API not in str(error.value) and SESSION not in str(error.value)
    assert API not in str(observed) and SESSION not in str(observed)


def test_existing_supervisor_dispatches_only_matching_nonprod_channel(runtime, monkeypatch):
    owner = DeploymentSupervisor(runtime.effects.config)
    monkeypatch.setattr(owner, '_require_current_config', lambda: None)
    owner.karakeep = runtime.supervisor
    assert owner.request({'action': 'karakeep-preflight', 'operation_id': str(uuid4()),
                          'plan': runtime.plan.payload()}) == {'ready': True}
    with pytest.raises(kd.KarakeepDeployError):
        owner.request({'action': 'karakeep-deploy', 'operation_id': str(uuid4()),
                       'plan': kd.KarakeepPlan('test', REVISION).payload()})


def test_production_callers_bound_persistent_immediate_pending_without_replay(runtime, monkeypatch):
    clock = [0.0]
    sleeps = []
    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(kd.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(kd.time, 'sleep', sleep)
    monkeypatch.setattr(kd, '_OBSERVATION_SECONDS', 3)
    actions = []
    def request(action, operation_id, plan):
        actions.append((action, operation_id))
        return {'ready': True} if action == 'karakeep-preflight' else {'pending': True}
    monkeypatch.setattr(runtime.remote, 'request', request)
    with pytest.raises(kd.KarakeepOperationPending):
        deploy(runtime)
    assert [action for action, _ in actions] == ['karakeep-preflight', 'karakeep-deploy'] + ['karakeep-status'] * 3
    assert sleeps == [1, 1, 1]
    original = actions[-1][1]
    actions.clear()
    with pytest.raises(kd.KarakeepOperationPending):
        deploy(runtime)
    assert actions == [('karakeep-status', original)] * 4
    with pytest.raises(HostSecretAdmissionError):
        runtime.admin.controller.admit('check', 'dev').__enter__()
    # Test the actual boot caller separately from its worker: persistent
    # immediate pending never becomes old-receipt success or another boot RPC.
    other_id = str(uuid4())
    journal = runtime.effects.journal
    journal.bind_request(other_id, runtime.plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating', 'committed'):
        journal.write(other_id, stage)
    monkeypatch.setattr(kd, '_require_vm_root', lambda: None)
    monkeypatch.setattr(kd, '_installation_journal', lambda channel: journal)
    boot_requests = []
    def pending_rpc(channel, data):
        boot_requests.append(data)
        return {'pending': True}
    monkeypatch.setattr(kd, 'rpc', pending_rpc)
    with pytest.raises(kd.KarakeepOperationPending):
        kd.boot('dev')
    assert [request['action'] for request in boot_requests] == ['karakeep-boot'] + ['karakeep-boot-status'] * 3
    assert len({request['operation_id'] for request in boot_requests}) == 1


def test_lost_install_ack_remains_reconcilable_after_successful_boot(runtime, monkeypatch):
    request = runtime.remote.request
    def lose_ack(action, operation_id, plan):
        response = request(action, operation_id, plan)
        if action == 'karakeep-deploy':
            assert response['receipt']['terminal_result'] == 'committed'
            raise OSError(API)
        return response
    monkeypatch.setattr(runtime.remote, 'request', lose_ack)
    with pytest.raises(kd.KarakeepDeployError):
        deploy(runtime)
    installed = runtime.effects.journal.read()
    binding = (runtime.effects.journal.directory / 'dev.request.json').read_bytes()
    with pytest.raises(HostSecretAdmissionError):
        runtime.admin.controller.admit('check', 'dev').__enter__()
    monkeypatch.setattr(kd, '_require_vm_root', lambda: None)
    monkeypatch.setattr(kd, '_installation_journal', lambda channel: runtime.effects.journal)
    monkeypatch.setattr(kd, 'rpc', lambda channel, data: runtime.supervisor.request(data))
    for path in runtime.effects.runtime.iterdir():
        path.unlink()
    kd.boot('dev')
    assert runtime.effects.journal.read() == installed
    assert (runtime.effects.journal.directory / 'dev.request.json').read_bytes() == binding
    assert runtime.effects.boot_journal.read().terminal_result == 'committed'
    recovered = deploy(runtime, operation_id=installed.operation_id)
    assert recovered == installed
    assert runtime.admin.check('dev', kd.SERVICE_CONSUMERS) == [
        {'secret': 'karakeep.search-token', 'status': 'ok'},
        {'secret': 'karakeep.session-token', 'status': 'ok'},
    ]
    assert sum('up' in argv for argv, _ in runtime.state.calls) == 2


def test_unknown_boot_preserves_install_authority_and_blocks_all_replay(runtime, monkeypatch):
    installed = deploy(runtime)
    monkeypatch.setattr(kd, '_require_vm_root', lambda: None)
    monkeypatch.setattr(kd, '_installation_journal', lambda channel: runtime.effects.journal)
    monkeypatch.setattr(kd, 'rpc', lambda channel, data: runtime.supervisor.request(data))
    runtime.state.fail = True
    with pytest.raises(kd.KarakeepDeployError):
        kd.boot('dev')
    pending = runtime.effects.boot_journal.read()
    assert pending.stage == 'activating' and pending.terminal_result is None
    assert runtime.effects.journal.read() == installed
    before = sum('up' in argv for argv, _ in runtime.state.calls)
    with pytest.raises(kd.KarakeepDeployError):
        kd.boot('dev')
    with pytest.raises(kd.KarakeepDeployError):
        deploy(runtime)
    assert before == sum('up' in argv for argv, _ in runtime.state.calls)
    assert runtime.effects.journal.read() == installed
    assert (runtime.effects.config.root / 'config/deploy/dev.env.lock').exists()
    lost = kd.KarakeepSupervisor(runtime.effects)
    assert lost.request({'action': 'karakeep-boot-status', 'operation_id': pending.operation_id,
                         'plan': runtime.plan.payload()}) == {'unknown': True}


def test_non_tmpfs_preflight_refuses_before_lookup_or_runtime_write(runtime):
    runtime.state.filesystem = 'ext4'
    with pytest.raises(kd.KarakeepDeployError):
        runtime.effects.preflight(runtime.plan)
    assert not runtime.provider.calls
    assert not runtime.effects.runtime.exists()
    assert not runtime.effects.journal.directory.exists()


def test_bws_provider_boundaries_refuse_all_karakeep_prod_identities_before_auth(tmp_path, monkeypatch):
    from app.ops import bws_secret_reader
    auth = []
    monkeypatch.setattr(bws_secret_reader, '_read_token', lambda config: auth.append('token') or API)
    credentials = tmp_path / 'credentials'
    reader = BwsSecretReader(BwsReaderConfig('prod', str(uuid4()), str(uuid4()), credentials,
                                             credentials / 'bws-machine-account-token'),
                             client_factory=lambda: auth.append('reader-auth'))
    admin = BwsSecretAdmin(BwsAdminConfig(str(uuid4()), str(uuid4()), str(uuid4())),
                           token_reader=lambda: auth.append('admin-token') or API,
                           client_factory=lambda: auth.append('admin-auth'))
    for secret in ('karakeep.session-token', 'karakeep.search-token', 'karakeep.api-key', 'karakeep.account-pass'):
        with pytest.raises(BwsLookupError):
            reader.lookup('prod', 'prod/' + secret)
        with pytest.raises(SecretAdminError):
            admin.read('prod', 'prod/' + secret)
    assert auth == []


def _interrupt_boot_cleanup(runtime, monkeypatch):
    installed = deploy(runtime)
    retire = LinuxEffects.retire_reconciled_channel_lock
    def interrupted(handle, **options):
        raise OSError('fixture cleanup interruption')
    monkeypatch.setattr(LinuxEffects, 'retire_reconciled_channel_lock', staticmethod(interrupted))
    monkeypatch.setattr(kd, '_require_vm_root', lambda: None)
    monkeypatch.setattr(kd, '_installation_journal', lambda channel: runtime.effects.journal)
    monkeypatch.setattr(kd, 'rpc', lambda channel, request: runtime.supervisor.request(request))
    with pytest.raises(kd.KarakeepDeployError):
        kd.boot('dev')
    if runtime.supervisor.worker:
        runtime.supervisor.worker.join(1)
    receipt = runtime.effects.boot_journal.read()
    assert receipt.terminal_result == 'committed'
    marker = runtime.effects.config.root / 'config/deploy/dev.env.lock/bws-owner'
    assert json.loads(marker.read_text()) == runtime.effects.lock_owner(receipt.operation_id, boot=True)
    assert runtime.effects.journal.read() == installed
    runtime.supervisor = kd.KarakeepSupervisor(runtime.effects)  # actual supervisor loss/restart
    return installed, receipt, marker, retire


def test_terminal_boot_cleanup_crash_reconciles_prior_id_before_next_boot(runtime, monkeypatch):
    installed, prior, marker, retire = _interrupt_boot_cleanup(runtime, monkeypatch)
    request = {'action': 'karakeep-boot-status', 'operation_id': prior.operation_id,
               'plan': runtime.plan.payload()}
    # A continued retirement failure cannot become terminal success or erase
    # the prior proof by preparing another attempt.
    with pytest.raises(kd.KarakeepDeployError):
        runtime.supervisor.request(request)
    with pytest.raises(kd.KarakeepDeployError):
        kd.boot('dev')
    assert runtime.effects.boot_journal.read() == prior and marker.exists()
    monkeypatch.setattr(LinuxEffects, 'retire_reconciled_channel_lock', staticmethod(retire))
    assert runtime.supervisor.request(request) == {'receipt': prior.payload()}
    assert not marker.parent.exists()
    assert runtime.effects.boot_journal.read() == prior
    for path in runtime.effects.runtime.iterdir():
        path.unlink()
    kd.boot('dev')
    assert runtime.effects.journal.read() == installed
    assert runtime.effects.boot_journal.read().terminal_result == 'committed'
    assert runtime.effects.boot_journal.read().operation_id != prior.operation_id
    assert SESSION in (runtime.effects.runtime / 'web.env').read_text()
    assert not marker.parent.exists()


def test_terminal_install_cleanup_crash_reconciles_host_without_duplicate_deploy(runtime, monkeypatch):
    retire = LinuxEffects.retire_reconciled_channel_lock
    def interrupted(handle, **options):
        raise OSError('fixture cleanup interruption')
    monkeypatch.setattr(LinuxEffects, 'retire_reconciled_channel_lock', staticmethod(interrupted))
    with pytest.raises(kd.KarakeepDeployError):
        deploy(runtime)
    if runtime.supervisor.worker:
        runtime.supervisor.worker.join(1)
    installed = runtime.effects.journal.read()
    marker = runtime.effects.config.root / 'config/deploy/dev.env.lock/bws-owner'
    assert installed.terminal_result == 'committed' and marker.exists()
    monkeypatch.setattr(LinuxEffects, 'retire_reconciled_channel_lock', staticmethod(retire))
    restarted = kd.KarakeepSupervisor(runtime.effects)
    monkeypatch.setattr(runtime.remote, 'request', lambda action, operation_id, plan:
                        restarted.request({'action': action, 'operation_id': operation_id, 'plan': plan.payload()}))
    assert deploy(runtime, operation_id=installed.operation_id) == installed
    assert not marker.parent.exists()
    assert sum('up' in argv for argv, _ in runtime.state.calls) == 1
    assert runtime.admin.check('dev', kd.SERVICE_CONSUMERS)[0]['status'] == 'ok'


def test_detached_terminal_cleanup_loss_does_not_block_fresh_boot(runtime, monkeypatch):
    installed = deploy(runtime)
    monkeypatch.setattr(kd, '_require_vm_root', lambda: None)
    monkeypatch.setattr(kd, '_installation_journal', lambda channel: runtime.effects.journal)
    monkeypatch.setattr(kd, 'rpc', lambda channel, request: runtime.supervisor.request(request))
    lock = runtime.effects.config.root / 'config/deploy/dev.env.lock'
    unlink = os.unlink
    detached = []
    def lose_detached_cleanup(path, *args, **options):
        if path == 'bws-owner':
            assert not lock.exists()
            assert runtime.effects.boot_journal.read().terminal_result == 'committed'
            detached.append(True)
            raise OSError('fixture loss after canonical retirement')
        return unlink(path, *args, **options)
    monkeypatch.setattr(os, 'unlink', lose_detached_cleanup)
    kd.boot('dev')
    assert detached and not lock.exists()
    assert list(lock.parent.glob('dev.env.lock.reconciled-*'))
    monkeypatch.setattr(os, 'unlink', unlink)
    for path in runtime.effects.runtime.iterdir():
        path.unlink()
    kd.boot('dev')
    assert runtime.effects.journal.read() == installed
    assert runtime.effects.boot_journal.read().terminal_result == 'committed'
    assert SESSION in (runtime.effects.runtime / 'web.env').read_text()
    assert not lock.exists()


@pytest.mark.parametrize('obstruction', ['live', 'foreign-operation', 'token-push', 'malformed', 'hardlink'])
def test_terminal_status_refuses_live_foreign_or_malformed_lock_without_losing_proof(runtime, monkeypatch, obstruction):
    _installed, prior, marker, retire = _interrupt_boot_cleanup(runtime, monkeypatch)
    monkeypatch.setattr(LinuxEffects, 'retire_reconciled_channel_lock', staticmethod(retire))
    descriptor = None
    if obstruction == 'live':
        descriptor = os.open(marker, os.O_RDWR | os.O_NOFOLLOW)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    elif obstruction == 'foreign-operation':
        marker.write_text(json.dumps(runtime.effects.lock_owner(str(uuid4()), boot=True)) + '\n')
    elif obstruction == 'token-push':
        marker.write_text(json.dumps({'kind': 'token-push', 'operation_id': str(uuid4()), 'attempt_id': str(uuid4())}) + '\n')
    elif obstruction == 'malformed':
        marker.write_text(SESSION)
    else:
        (runtime.effects.runtime / 'fixture-marker-link').hardlink_to(marker)
    before = marker.read_bytes()
    try:
        with pytest.raises(kd.KarakeepDeployError) as error:
            runtime.supervisor.request({'action': 'karakeep-boot-status', 'operation_id': prior.operation_id,
                                        'plan': runtime.plan.payload()})
        assert SESSION not in str(error.value)
        assert marker.read_bytes() == before and runtime.effects.boot_journal.read() == prior
    finally:
        if descriptor is not None:
            os.close(descriptor)


@pytest.mark.parametrize('actor', ['postgres', 'karakeep-deploy', 'karakeep-boot', 'token-push'])
def test_postgres_failed_reconciliation_cannot_borrow_another_actor_lock(runtime, monkeypatch, actor):
    journal = DeployJournal(runtime.effects.journal.directory / 'postgres-fixture', 'dev')
    operation_id = str(uuid4())
    plan = DeployPlan('dev', REVISION, ('db',), ('postgres-db',))
    journal.bind_request(operation_id, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating', 'failed'):
        journal.write(operation_id, stage)
    path = runtime.effects.config.root / 'config/deploy/dev.env.lock'
    path.mkdir(mode=0o700)
    marker = path / 'bws-owner'
    value = '' if actor == 'postgres' else json.dumps({'kind': actor, 'channel': 'dev', 'operation_id': str(uuid4())}) + '\n'
    marker.write_text(value)
    marker.chmod(0o600)
    owner = DeploymentSupervisor(SimpleNamespace(channel='dev', root=runtime.effects.config.root, journal=journal))
    monkeypatch.setattr(owner, '_require_current_config', lambda: None)
    monkeypatch.setattr(LinuxEffects, 'quiescent', lambda self: True)
    request = {'action': 'reconcile-failed', 'operation_id': operation_id, 'plan': plan.payload(), 'bootstrap': False}
    if actor == 'postgres':
        assert owner.request(request)['receipt']['terminal_result'] == 'failed'
        assert not path.exists()
    else:
        with pytest.raises(PostgresDeployError):
            owner.request(request)
        assert marker.read_text() == value
        assert journal.read().operation_id == operation_id and journal.read().stage == 'failed'


@pytest.mark.parametrize('refusal', ['missing-key', 'reader-unavailable', 'pending-boot'])
def test_daemon_start_cannot_bypass_governed_boot_admission(runtime, monkeypatch, refusal):
    installed = deploy(runtime)
    shape = yaml.safe_load((runtime.effects.config.root / 'docker-compose.karakeep.yml').read_text())
    # Docker's documented on-failure policy supervises crashes, but does not
    # start retained containers when the daemon starts. The actual production
    # preflight below also checks the resolved container policy, not Config.Env.
    assert {service['restart'] for service in shape['services'].values()} == {'on-failure'}
    unit = next(runtime.effects.unit_directory.iterdir()).read_text()
    assert 'WantedBy=multi-user.target docker.service' in unit
    assert 'PartOf=docker.service' in unit
    runtime.state.running = False
    for path in runtime.effects.runtime.iterdir():
        path.unlink()
    if refusal == 'missing-key':
        runtime.provider.values.pop(('non-prod', 'dev/karakeep.search-token'))
    elif refusal == 'reader-unavailable':
        monkeypatch.setattr(LinuxConfig, 'reader', lambda self: (_ for _ in ()).throw(BwsLookupError()))
    else:
        operation_id = str(uuid4())
        journal = runtime.effects.boot_journal
        journal.bind_request(operation_id, runtime.plan, False, create=True)
        journal.write(operation_id, 'prepared')
    monkeypatch.setattr(kd, '_require_vm_root', lambda: None)
    monkeypatch.setattr(kd, '_installation_journal', lambda channel: runtime.effects.journal)
    monkeypatch.setattr(kd, 'rpc', lambda channel, request: runtime.supervisor.request(request))
    before = sum('up' in argv for argv, _ in runtime.state.calls)
    with pytest.raises((kd.KarakeepDeployError, BwsLookupError)):
        kd.boot('dev')
    assert before == sum('up' in argv for argv, _ in runtime.state.calls)
    assert runtime.effects.journal.read() == installed
    assert not list(runtime.effects.runtime.iterdir())


def test_retained_autostart_container_policy_refused_before_secret_lookup(runtime):
    deploy(runtime)
    runtime.state.restart = 'unless-stopped'
    runtime.provider.calls.clear()
    before = sum('up' in argv for argv, _ in runtime.state.calls)
    with pytest.raises(kd.KarakeepDeployError):
        runtime.effects.preflight(runtime.plan, boot=True)
    assert not runtime.provider.calls
    assert before == sum('up' in argv for argv, _ in runtime.state.calls)


@pytest.mark.parametrize('interruption', ['none', 'ack-lost', 'binding-only', 'prepared-only'])
def test_sent_deploy_refused_by_concurrent_boot_remains_reconcilable(runtime, monkeypatch, interruption):
    installed = deploy(runtime)
    binding = (runtime.effects.journal.directory / 'dev.request.json').read_bytes()
    entered, release = threading.Event(), threading.Event()
    failures, identifiers = [], []
    materialize = runtime.effects.materialize
    def pause_boot(values):
        entered.set()
        assert release.wait(5)
        materialize(values)
    monkeypatch.setattr(runtime.effects, 'materialize', pause_boot)
    monkeypatch.setattr(kd, '_require_vm_root', lambda: None)
    monkeypatch.setattr(kd, '_installation_journal', lambda channel: runtime.effects.journal)
    monkeypatch.setattr(kd, 'rpc', lambda channel, request: runtime.supervisor.request(request))
    def run_boot():
        try:
            kd.boot('dev')
        except Exception as error:
            failures.append(type(error).__name__)
    boot_worker = threading.Thread(target=run_boot)
    request = runtime.remote.request
    def race(action, operation_id, plan):
        response = request(action, operation_id, plan)
        if action == 'karakeep-preflight':
            boot_worker.start()
            assert entered.wait(2)
        elif action == 'karakeep-deploy':
            identifiers.append(operation_id)
            assert response['receipt']['terminal_result'] == 'aborted'
            if interruption == 'ack-lost':
                raise OSError('fixture acknowledgement loss')
        return response
    monkeypatch.setattr(runtime.remote, 'request', race)
    write = DeployJournal.write
    injected = []
    def interrupted_write(journal, operation_id, stage, *args, **options):
        if (journal.directory == runtime.effects.journal.directory / 'refused'
            and not injected and stage == {'binding-only': 'prepared', 'prepared-only': 'aborted'}.get(interruption)):
            injected.append(True)
            identifiers.append(operation_id)
            raise OSError('fixture receipt boundary interruption')
        return write(journal, operation_id, stage, *args, **options)
    monkeypatch.setattr(DeployJournal, 'write', interrupted_write)
    try:
        if interruption == 'none':
            refused = deploy(runtime)
        else:
            with pytest.raises(kd.KarakeepDeployError):
                deploy(runtime)
            # Same production host caller resumes status only; no duplicate RPC.
            restarted = kd.KarakeepSupervisor(runtime.effects)
            monkeypatch.setattr(runtime.remote, 'request', lambda action, operation_id, plan:
                                restarted.request({'action': action, 'operation_id': operation_id, 'plan': plan.payload()}))
            refused = deploy(runtime)
        assert refused.terminal_result == 'aborted' and refused.operation_id == identifiers[0]
        assert runtime.effects.journal.read() == installed
        assert (runtime.effects.journal.directory / 'dev.request.json').read_bytes() == binding
        pending = runtime.effects.boot_journal.read()
        assert pending.terminal_result is None
        marker = runtime.effects.config.root / 'config/deploy/dev.env.lock/bws-owner'
        assert json.loads(marker.read_text()) == runtime.effects.lock_owner(pending.operation_id, boot=True)
        # Replaying the rejected ID cannot acquire effects, even if admission
        # later becomes free. A changed binding cannot borrow its terminality.
        retry = {'action': 'karakeep-deploy', 'operation_id': refused.operation_id, 'plan': runtime.plan.payload()}
        assert runtime.supervisor.request(retry) == {'receipt': refused.payload()}
        with pytest.raises((kd.KarakeepDeployError, PostgresDeployError)):
            runtime.supervisor.request({**retry, 'plan': kd.KarakeepPlan('dev', 'b' * 40).payload()})
        assert sum('up' in argv for argv, _ in runtime.state.calls) == 1
        assert runtime.admin.check('dev', kd.SERVICE_CONSUMERS)[0]['status'] == 'ok'
    finally:
        release.set()
        if boot_worker.ident:
            boot_worker.join(3)
    assert not failures and not boot_worker.is_alive()
    assert runtime.effects.journal.read() == installed
    assert runtime.effects.boot_journal.read().terminal_result == 'committed'
    monkeypatch.setattr(runtime.effects, 'materialize', materialize)
    monkeypatch.setattr(runtime.remote, 'request', request)
    assert deploy(runtime).terminal_result == 'committed'
    assert sum('up' in argv for argv, _ in runtime.state.calls) == 3
    assert runtime.supervisor.request(retry) == {'receipt': refused.payload()}
    assert sum('up' in argv for argv, _ in runtime.state.calls) == 3


@pytest.mark.parametrize('race', ['credential-removed', 'qualification-stale', 'foreign-lock'])
def test_sent_deploy_rechecks_inputs_and_durably_refuses_before_effects(runtime, monkeypatch, race):
    installed = deploy(runtime)
    binding = (runtime.effects.journal.directory / 'dev.request.json').read_bytes()
    request = runtime.remote.request
    marker = runtime.effects.config.root / 'config/deploy/dev.env.lock/bws-owner'
    def change_after_preflight(action, operation_id, plan):
        response = request(action, operation_id, plan)
        if action == 'karakeep-preflight':
            if race == 'credential-removed':
                runtime.provider.values.pop(('non-prod', 'dev/karakeep.search-token'))
            elif race == 'qualification-stale':
                runtime.settings['qualified_at'] = '2000-01-01T00:00:00+00:00'
            else:
                marker.parent.mkdir(mode=0o700)
                marker.write_text(json.dumps({'kind': 'token-push', 'operation_id': str(uuid4()), 'attempt_id': str(uuid4())}) + '\n')
                marker.chmod(0o600)
        elif action == 'karakeep-deploy':
            assert response['receipt']['terminal_result'] == 'aborted'
            raise OSError('fixture acknowledgement loss')
        return response
    monkeypatch.setattr(runtime.remote, 'request', change_after_preflight)
    with pytest.raises(kd.KarakeepDeployError):
        deploy(runtime)
    before = marker.read_bytes() if marker.exists() else None
    restarted = kd.KarakeepSupervisor(runtime.effects)
    monkeypatch.setattr(runtime.remote, 'request', lambda action, operation_id, plan:
                        restarted.request({'action': action, 'operation_id': operation_id, 'plan': plan.payload()}))
    refused = deploy(runtime)
    assert refused.terminal_result == 'aborted'
    assert runtime.effects.journal.read() == installed
    assert (runtime.effects.journal.directory / 'dev.request.json').read_bytes() == binding
    assert (marker.read_bytes() if marker.exists() else None) == before
    assert sum('up' in argv for argv, _ in runtime.state.calls) == 1
    # Missing authority is never synthesized into an aborted/success receipt.
    with pytest.raises(kd.KarakeepDeployError):
        restarted.request({'action': 'karakeep-status', 'operation_id': str(uuid4()), 'plan': runtime.plan.payload()})
