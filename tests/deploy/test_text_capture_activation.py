"""Request, real supervisor/worker and shell/bootstrap integration; external ports are fixtures."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import patch
from uuid import uuid4

import pytest
import yaml

from app.ops import postgres_deploy_host as host
from app.ops import postgres_deploy_linux as linux
from app.ops.postgres_deploy import DeployPlan, PostgresDeployError
from tests.deploy import test_postgres_deploy_principal_cutover as native_contract
from tests.deploy.test_deploy_channel import _deploy_events, _run_deploy
from tests.deploy.test_deploy_channel_script import _native_source_harness

SHA = 'a' * 40
DIGEST = 'sha256:' + 'b' * 64
native = native_contract.native


def _pg_ports(native, tmp_path, monkeypatch):
    from app.ops.pg_acceptance_runner import PgAcceptanceRunner
    from tests.deploy.test_postmerge_pg_acceptance import DockerBoundary, _repository
    with patch.object(subprocess, 'run', native.real_run):
        objects, native.sha = _repository(tmp_path)
    (native.cfg.root / 'config/deploy' / (native.cfg.channel + '.env')).write_text('APP_IMAGE_TAG=' + native.sha + '\n')
    boundaries = {}

    def git_port(_runner, *arguments):
        return native.real_run(['git', '-C', str(objects), *arguments], capture_output=True, check=True).stdout

    def docker_port(runner, *arguments, **kwargs):
        return boundaries.setdefault(runner.name, DockerBoundary(runner)).command(*arguments, **kwargs)

    monkeypatch.setattr(PgAcceptanceRunner, '_git', git_port)
    monkeypatch.setattr(PgAcceptanceRunner, '_docker', docker_port)
    return boundaries


def test_request_scope_roundtrip_and_rejection(native, tmp_path, monkeypatch):
    _pg_ports(native, tmp_path, monkeypatch)
    operation_id = str(uuid4())
    args = [native.cfg.channel, native.sha, '--image-digest', DIGEST,
            '--automatic', '--existing-secrets-only', '--activation-scope', 'text-capture',
            '--operation-id', operation_id]
    assert host.main(args) == 0
    plan = native.cfg.journal.bound_plan(operation_id)
    assert plan.activation_scope == 'text-capture'
    assert DeployPlan.from_payload(json.loads(json.dumps(plan.payload()))) == plan
    assert all(request['plan']['activation_scope'] == 'text-capture' for request in native.requests)
    terminal = native.cfg.journal.read()
    terminal.require_profile(plan)
    with pytest.raises(PostgresDeployError):
        terminal.require_profile(replace(plan, activation_scope='full'))
    with pytest.raises(PostgresDeployError):
        native.supervisor.request({**native.requests[0], 'plan': json.loads(json.dumps(
            replace(plan, activation_scope='full').payload()))})
    assert native.supervisor.request({**native.requests[0], 'action': 'join'}) == {'receipt': terminal.payload()}
    assert len(native.activations) == 1
    for raw in ({**plan.payload(), 'activation_scope': 'unknown'},
                {**plan.payload(), 'channel': 'prod'},
                {**plan.payload(), 'activation_scope': None}):
        with pytest.raises(PostgresDeployError):
            DeployPlan.from_payload(raw)
    legacy = replace(plan, activation_scope='full')
    assert 'activation_scope' not in legacy.payload()
    assert DeployPlan.from_payload(json.loads(json.dumps(legacy.payload()))) == legacy
    # Refusal precedes controller construction, SSH and secret-provider access.
    monkeypatch.setattr(host, 'HostSecretController', lambda: pytest.fail('invalid scope reached host admission'))
    assert host.main(['prod', *args[1:]]) == 78
    assert host.main([value for value in args if value != '--existing-secrets-only']) == 78
    with pytest.raises(SystemExit):
        host.main([*args[:-4], '--activation-scope', 'unknown'])


def test_worker_configuration_and_receipt_bind_scope(native, tmp_path, monkeypatch):
    boundaries = _pg_ports(native, tmp_path, monkeypatch)
    refused = []

    def inspect_worker(_argv, **kwargs):
        environment = {**kwargs['env'], 'DEPLOY_ACTIVATION_SCOPE': 'text-capture'}
        assert environment['BWS_DEPLOY_ACTIVATION_SCOPE'] == 'text-capture'
        for changed in ({**environment, 'BWS_DEPLOY_ACTIVATION_SCOPE': 'full'},
                        {**environment, 'DEPLOY_ACTIVATION_SCOPE': 'full'},
                        {**environment, 'BWS_DEPLOY_TARGET_REVISION': 'e' * 40},
                        {**environment, 'BWS_DEPLOY_OPERATION_ID': str(uuid4())}):
            with patch.dict(os.environ, changed, clear=True), pytest.raises(PostgresDeployError):
                linux.inherited_worker_guard(native.cfg.channel, 'run')
            refused.append(changed)
        return subprocess.CompletedProcess(_argv, 0, '', '')

    native.wrapper = inspect_worker
    monkeypatch.setenv('PKM_ACTIVATION_SCOPE', 'text-capture')
    monkeypatch.setenv('DEPLOY_ACTIVATION_SCOPE', 'text-capture')
    monkeypatch.setenv('BWS_DEPLOY_ACTIVATION_SCOPE', 'text-capture')
    operation_id = str(uuid4())
    args = [native.cfg.channel, native.sha, '--image-digest', DIGEST,
            '--automatic', '--existing-secrets-only', '--activation-scope', 'text-capture',
            '--operation-id', operation_id]
    assert host.main(args) == 0
    assert len(refused) == 4
    assert native.cfg.journal.read().payload()['activation_scope'] == 'text-capture'
    assert all(not boundary.containers for boundary in boundaries.values())
    # A fresh full worker strips every ambient scope input.
    fresh = linux.LinuxEffects(native.cfg)
    environment = fresh.environment()
    assert all(key not in environment for key in ('PKM_ACTIVATION_SCOPE', 'DEPLOY_ACTIVATION_SCOPE',
                                                  'BWS_DEPLOY_ACTIVATION_SCOPE'))


@pytest.mark.parametrize('channel', ['dev', 'test'])
@pytest.mark.parametrize('scope', ['full', 'text-capture'])
def test_native_text_activation_preserves_foundational_guards(tmp_path, channel, scope):
    root, env, sha = _native_source_harness(tmp_path, channel=channel, ready=False)
    # A scope-only transition at the same SHA/digest still needs a previous pin.
    prior_scope = 'text-capture' if scope == 'full' else 'full'
    prior_pin = f'APP_IMAGE_TAG={sha}\nAPP_IMAGE_DIGEST_SUFFIX=@{DIGEST}\n'
    if prior_scope != 'full':
        prior_pin += 'DEPLOY_ACTIVATION_SCOPE=text-capture\n'
    (root / 'config/deploy' / (channel + '.env')).write_text(prior_pin)
    extra = []
    if scope == 'text-capture':
        env['BWS_DEPLOY_ACTIVATION_SCOPE'] = scope
        extra = ['--activation-scope', scope, '--automatic', '--image-digest', DIGEST]
        # Poison the real shell's semantic gate ports; any accidental call refuses.
        env.update(FAKE_EMBEDDING_IDENTITY_RC='78', FAKE_SOURCE_RC='78', FAKE_SOURCE_INDEX_RC='78')
        curl = tmp_path / 'bin/curl'
        curl.write_text(curl.read_text().replace(
            'case "$*" in',
            'if [[ "$*" == *"/api/health"* ]]; then\n'
            '  printf \'{"ok":false,"required_ok":false,"activation_scope":"text-capture",'
            '"full_channel_qualified":false,"version":{"git_sha":"%s"}}\\n\' "$FAKE_SHA"\n'
            '  exit 0\nfi\ncase "$*" in', 1))
    result = _run_deploy(root, env, sha, *extra, channel=channel)
    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    assert any('instance-state-init' in event for event in events)
    assert 'api-migrations' in events
    assert any('api-cli settings validate --json' == event for event in events)
    source = next(i for i, event in enumerate(events) if event.startswith('source-probe '))
    recreation = next(i for i, event in enumerate(events) if 'up -d --force-recreate' in event and 'instance-state' not in event)
    assert source < recreation
    receipt = json.loads((root / 'ops/deployments' / (channel + '-latest.json')).read_text())
    pin = (root / 'config/deploy' / (channel + '.env')).read_text()
    previous = (root / 'config/deploy' / (channel + '.previous.env')).read_text()
    assert ('DEPLOY_ACTIVATION_SCOPE=text-capture' in previous) == (prior_scope == 'text-capture')
    if scope == 'text-capture':
        assert 'DEPLOY_ACTIVATION_SCOPE=text-capture' in pin
        assert receipt['activation_scope'] == scope and receipt['full_channel_qualified'] is False
        assert not any(event.startswith(('embedding-identity-read', 'embedding-probe', 'source-rebuild', 'ollama-')) for event in events)
        assert not any(event.startswith('api-cli index') for event in events)
        assert any(f'NATIVE_SOURCE_BOOTSTRAP={channel}:{sha}:text-capture' in event for event in events)
        assert any('up -d --force-recreate --no-deps api' in event for event in events)
        assert not any('up -d --force-recreate api worker watcher' in event for event in events)
    else:
        assert 'activation_scope' not in receipt and 'DEPLOY_ACTIVATION_SCOPE' not in pin
        assert any(event.startswith('embedding-probe ') for event in events)
        assert 'source-rebuild' in events
        assert 'api-cli index doctor --json --strict' in events


@pytest.mark.parametrize('channel', ['dev', 'test'])
def test_legacy_selected_image_refuses_text_before_bootstrap_or_runtime(tmp_path, channel):
    root, env, sha = _native_source_harness(tmp_path, channel=channel, ready=False)
    repository = Path(__file__).resolve().parents[2]
    legacy_revision = 'd4004fbb3bab42ac9068d65494a22edf05c5c96e'
    # Use the actual pre-scope image source, rather than teaching a stub to
    # return an invented compatibility verdict. Its strict preflight must win.
    for relative in ('app/ops/native_source_bootstrap.py', 'app/api/app.py', 'scripts/start_api.sh'):
        legacy = subprocess.check_output(['git', '-C', str(repository), 'show', legacy_revision + ':' + relative])
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(legacy)
    env['BWS_DEPLOY_ACTIVATION_SCOPE'] = 'text-capture'
    result = _run_deploy(root, env, sha, '--activation-scope', 'text-capture',
                         '--automatic', '--image-digest', DIGEST, channel=channel)
    assert result.returncode != 0
    events = _deploy_events(env)
    assert any(f'NATIVE_SOURCE_BOOTSTRAP={channel}:{sha}:text-capture' in event for event in events)
    assert 'api-migrations' not in events
    assert not any(event.startswith(('api-cli ', 'source-rebuild', 'embedding-probe ')) for event in events)
    assert not any('up -d --force-recreate --no-deps api' in event for event in events)
    assert not (root / 'ops/deployments' / (channel + '-latest.json')).exists()


@pytest.mark.parametrize('scope,selector_suffix', [('text-capture', ''), ('full', ':text-capture')])
def test_bootstrap_scope_requires_explicit_selector_agreement(monkeypatch, scope, selector_suffix):
    from app.ops import native_source_bootstrap as bootstrap
    selector = 'dev:' + SHA + selector_suffix
    monkeypatch.setenv('PKM_ENVIRONMENT', 'dev')
    monkeypatch.setenv('PKM_ACTIVATION_SCOPE', scope)
    monkeypatch.setenv('NATIVE_SOURCE_BOOTSTRAP', selector)
    monkeypatch.setattr(bootstrap, '_instance_preflight', lambda *_args: pytest.fail('scope mismatch passed preflight'))
    with pytest.raises(ValueError, match='source context invalid'):
        bootstrap.preflight(selector)


@pytest.mark.parametrize('channel', ['dev', 'test'])
@pytest.mark.parametrize('failure', ['backend', 'context', 'unbound', 'settings'])
def test_text_activation_foundation_refusal_never_recreates(tmp_path, channel, failure):
    root, env, sha = _native_source_harness(tmp_path, channel=channel, ready=False)
    env['BWS_DEPLOY_ACTIVATION_SCOPE'] = 'text-capture'
    env[{'backend': 'FAKE_API_BACKEND', 'context': 'FAKE_API_CONTEXT_RC',
         'unbound': 'FAKE_API_UNBOUND', 'settings': 'FAKE_SOURCE_SETTINGS_RC'}[failure]] = (
             'memory' if failure == 'backend' else '1')
    result = _run_deploy(root, env, sha, '--activation-scope', 'text-capture',
                         '--automatic', '--image-digest', DIGEST, channel=channel)
    assert result.returncode != 0
    events = _deploy_events(env)
    assert not any('up -d --force-recreate --no-deps api' in event for event in events)
    assert not any(event.startswith(('embedding-probe ', 'source-rebuild')) for event in events)
    assert not (root / 'ops/deployments' / (channel + '-latest.json')).exists()


@pytest.mark.parametrize('arguments,marker', [([], 'text-capture'), (['--activation-scope', 'text-capture'], 'full'),
                                            (['--activation-scope', 'unknown'], 'unknown')])
def test_shell_scope_mismatch_refuses_before_effects(tmp_path, arguments, marker):
    root, env, sha = _native_source_harness(tmp_path, channel='dev')
    env['BWS_DEPLOY_ACTIVATION_SCOPE'] = marker
    result = _run_deploy(root, env, sha, *arguments)
    assert result.returncode == 78
    assert not Path(env['FAKE_DEPLOY_EVENT_LOG']).exists()


@pytest.mark.parametrize('channel,content,accepted', [
    ('dev', '', 'full'), ('test', 'DEPLOY_ACTIVATION_SCOPE=text-capture\n', 'text-capture'),
    ('prod', 'DEPLOY_ACTIVATION_SCOPE=text-capture\n', None),
    ('dev', 'DEPLOY_ACTIVATION_SCOPE=\n', None),
    ('test', 'DEPLOY_ACTIVATION_SCOPE=unknown\n', None),
    ('dev', 'DEPLOY_ACTIVATION_SCOPE=full\nDEPLOY_ACTIVATION_SCOPE=text-capture\n', None),
])
def test_active_pin_scope_is_finite_and_overrides_ambient(tmp_path, channel, content, accepted):
    pin = tmp_path / 'channel.env'
    pin.write_text(content)
    library = Path(__file__).resolve().parents[2] / 'scripts/lib/deploy_channel_compose.sh'
    command = '''set -e
source "$1"
scope="$(_deploy_channel_pin_activation_scope "$2" "$3")"
_deploy_channel_signboard_override_document "${scope}"
'''
    result = subprocess.run(['bash', '-c', command, '--', str(library), str(pin), channel],
                            env={**os.environ, 'PKM_ACTIVATION_SCOPE': 'unknown',
                                 'DEPLOY_ACTIVATION_SCOPE': 'text-capture'},
                            text=True, capture_output=True, check=False)
    assert pin.read_text() == content
    if accepted is None:
        assert result.returncode == 78 and not result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert yaml.safe_load(result.stdout)['services']['api']['environment']['PKM_ACTIVATION_SCOPE'] == accepted


def test_scoped_rollback_requires_gateway_and_stopped_semantic_producers(tmp_path):
    repository = Path(__file__).resolve().parents[2]
    script = (repository / 'scripts/deploy_channel.sh').read_text()

    def function(name):
        return name + '() {' + script.split(name + '() {', 1)[1].split('\n}\n', 1)[0] + '\n}\n'

    pin = tmp_path / 'channel.env'
    pin.write_text('DEPLOY_ACTIVATION_SCOPE=text-capture\n')
    # Keep production pin/rollback/HTTP predicates; inject only Compose and HTTP
    # output ports. API's ordinary semantic /readyz health may remain red.
    command = '''set -e
source "$1"
pin_file="$2"
channel=dev
PYTHON="$3"
api_port=1
ui_port=2
compose() { printf '%s\\n' "$FIXTURE_ROWS"; }
wait_json_ok() { return 0; }
curl() { printf '%s\\n' '{"activation_scope":"text-capture","full_channel_qualified":false}'; }
''' + function('text_activation_gate') + function('rollback_runtime_complete_gate') + 'rollback_runtime_complete_gate\n'
    healthy = [{'Service': 'api', 'State': 'running', 'Health': 'unhealthy'},
               {'Service': 'companion-ui', 'State': 'running', 'Health': 'healthy'},
               {'Service': 'worker', 'State': 'exited', 'Health': ''}]
    for rows, accepted in [(healthy, True), (healthy[:1], False),
                           ([*healthy[:2], {'Service': 'worker', 'State': 'running'}], False)]:
        result = subprocess.run(['bash', '-c', command, '--',
                                 str(repository / 'scripts/lib/deploy_channel_compose.sh'), str(pin),
                                 os.sys.executable],
                                env={**os.environ, 'FIXTURE_ROWS': json.dumps(rows)},
                                text=True, capture_output=True, check=False)
        assert (result.returncode == 0) == accepted, result.stderr
