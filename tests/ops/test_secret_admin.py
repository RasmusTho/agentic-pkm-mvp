from __future__ import annotations

from io import StringIO
import json
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from app.ops.bws_secret_admin import (
    BwsAdminConfig, BwsSecretAdmin, PrecommitRejection, SecretAdminError, SecretCopy,
)
from app.ops.host_secret_controller import HostSecretAdmissionError, HostSecretController, TerminalEvidence
from app.ops.secret_admin import SecretAdmin, SecretHistory, main

CANARY = 'canary-issued-provider-value-123456789'
PRIOR = 'prior-issued-provider-value-987654321'
IDENTITY = 'shared/openai.api-key'


class FakeProvider:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], SecretCopy] = {}
        self.calls: list[tuple[str, str, str]] = []
        self.fail: dict[tuple[str, str], BaseException] = {}
        self.on_put = lambda: None

    def seed(self, identity=IDENTITY, value=PRIOR, projects=('non-prod', 'prod')):
        for project in projects:
            self.values[project, identity] = SecretCopy(str(uuid4()), value, 'owner text')

    def read(self, project, identity):
        self.calls.append(('read', project, identity))
        if error := self.fail.get(('read', project)):
            raise error
        return self.values.get((project, identity))

    def put(self, project, identity, previous, value, note):
        self.calls.append(('put', project, identity))
        self.on_put()
        if error := self.fail.get(('put', project)):
            raise error
        result = SecretCopy(previous.item_id if previous else str(uuid4()), value, note)
        self.values[project, identity] = result
        return result

    def delete(self, project, identity, current):
        self.calls.append(('delete', project, identity))
        if error := self.fail.get(('delete', project)):
            raise error
        del self.values[project, identity]


@pytest.fixture
def setup(tmp_path):
    provider = FakeProvider()
    controller = HostSecretController(tmp_path / 'controller')
    return SecretAdmin(provider, controller=controller), provider, controller


def history(controller):
    return [json.loads(line) for line in (controller.directory / 'secret-history.jsonl').read_text().splitlines()]


def test_check_scopes_required_set_to_selected_consumers(setup, capsys):
    admin, provider, _ = setup
    provider.seed()
    assert main(['check', 'dev', '--consumer', 'builderops-model-inquiry'], admin=admin) == 0
    assert {identity for _, _, identity in provider.calls} == {IDENTITY}
    assert PRIOR not in capsys.readouterr().out


def test_inactive_optional_provider_credentials_do_not_block_check(setup):
    admin, provider, _ = setup
    provider.seed('dev/heimdal.raw-store-key', 'a' * 64, ('non-prod',))
    statuses = admin.check('dev', ['heimdal-api-ingress'])
    assert statuses == [{'secret': 'github.token', 'status': 'skipped'},
                        {'secret': 'heimdal.raw-store-key', 'status': 'ok'}]
    assert not any('openai' in identity for _, _, identity in provider.calls)


def test_malformed_optional_provider_credential_blocks_check(setup):
    admin, provider, _ = setup
    provider.seed('dev/heimdal.raw-store-key', 'a' * 64, ('non-prod',))
    provider.seed('shared/github.token', 'bad')
    assert admin.check('dev', ['heimdal-api-ingress'])[0]['status'] == 'invalid'


def test_external_identity_imports_from_stdin_without_value_disclosure(setup, capsys):
    admin, provider, _ = setup
    assert main(['import', 'dev', 'openai.api-key', '--stdin'], admin=admin, stdin=StringIO(CANARY)) == 0
    assert all(copy.value == CANARY for copy in provider.values.values())
    output = capsys.readouterr()
    assert json.loads(output.out) == {'status': 'imported'}
    assert CANARY not in output.out + output.err
    assert main(['import', 'dev', 'openai.api-key', CANARY], admin=admin) == 1
    assert CANARY not in str(capsys.readouterr())


@pytest.mark.parametrize('secret', ['openai.api-key', 'anthropic.api-key', 'github.token',
    'discord.webhook', 'heimdal.raw-store-key', 'heimdal.archive-pass', 'postgres.password'])
def test_generation_and_rotation_reject_external_and_protected_identities(setup, secret):
    admin, provider, _ = setup
    for channel in ('dev', 'test', 'prod'):
        for method in (admin.generate, admin.rotate):
            with pytest.raises(SecretAdminError):
                method(channel, secret)
    assert provider.calls == []


def test_initialized_postgres_password_cannot_be_rotated(setup):
    admin, provider, _ = setup
    provider.seed('dev/postgres.password', 'existing password', ('non-prod',))
    with pytest.raises(SecretAdminError):
        admin.rotate('dev', 'postgres.password')
    admin.import_stdin('dev', 'postgres.password', StringIO('existing password'))
    assert provider.values['non-prod', 'dev/postgres.password'].value == 'existing password'


def test_rotation_archives_prior_value_before_update(setup):
    admin, provider, controller = setup
    provider.seed()
    def check_history():
        records = history(controller)
        assert len([r for r in records if r['event'] == 'snapshot' and r['value'] == PRIOR]) == 2
        assert any(r['event'] == 'prepared' for r in records)
    provider.on_put = check_history
    admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
    assert (controller.directory / 'secret-history.jsonl').stat().st_mode & 0o777 == 0o600
    assert CANARY not in (controller.directory / 'operations.jsonl').read_text()


def test_rotation_history_failure_does_not_change_active_value(setup, monkeypatch):
    admin, provider, _ = setup
    provider.seed()
    monkeypatch.setattr(SecretHistory, 'append', lambda *a, **k: (_ for _ in ()).throw(OSError(CANARY)))
    with pytest.raises(SecretAdminError) as error:
        admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
    assert CANARY not in str(error.value)
    assert all(c.value == PRIOR for c in provider.values.values())
    assert not any(c[0] == 'put' for c in provider.calls)


def test_admin_shared_check_detects_missing_and_divergent_copies(setup):
    admin, provider, _ = setup
    provider.seed(projects=('non-prod',))
    assert admin.check('dev', ['builderops-model-inquiry'])[0]['status'] == 'missing'
    provider.seed(value=CANARY, projects=('prod',))
    assert admin.check('dev', ['builderops-model-inquiry'])[0]['status'] == 'divergent'


def test_shared_import_updates_both_project_copies_without_output(setup, capsys):
    admin, provider, _ = setup
    provider.seed()
    assert main(['import', 'prod', 'openai.api-key', '--stdin'], admin=admin, stdin=StringIO(CANARY)) == 0
    assert {c.value for c in provider.values.values()} == {CANARY}
    assert all(c.note.startswith('owner text\n[yggdrasil-secret-operation:') for c in provider.values.values())
    assert CANARY not in str(capsys.readouterr())


def test_typesafe_import_targets_non_prod_and_rejects_other_channels(setup, capsys):
    admin, provider, controller = setup
    assert main(['import', 'dev', 'typesafe.api-key', '--stdin'], admin=admin,
                stdin=StringIO(CANARY)) == 0
    assert set(provider.values) == {('non-prod', 'dev/typesafe.api-key')}
    assert provider.values['non-prod', 'dev/typesafe.api-key'].value == CANARY
    records = history(controller)
    assert {(record.get('project'), record.get('identity')) for record in records
            if record['event'] == 'snapshot'} == {('non-prod', 'dev/typesafe.api-key')}
    assert CANARY not in str(capsys.readouterr())
    provider.calls.clear()
    assert main(['import', 'test', 'typesafe.api-key', '--stdin'], admin=admin,
                stdin=StringIO(CANARY)) == 1
    assert provider.calls == []


def test_marr_import_records_genesis_before_one_send_and_blocks_ambiguous_recovery(setup):
    admin, provider, controller = setup
    observed: list[dict[str, object]] = []

    def fail_after_history():
        observed.extend(history(controller))
        raise RuntimeError(CANARY)

    provider.on_put = fail_after_history
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'typesafe.api-key', StringIO(CANARY))
    assert [(record['event'], record.get('project')) for record in observed[:3]] == [
        ('snapshot', 'non-prod'),
        ('prepared', None),
        ('sent', 'non-prod'),
    ]
    assert observed[0]['previous_state'] == 'absent'
    assert 'value' not in observed[0]
    assert provider.calls == [
        ('read', 'non-prod', 'dev/typesafe.api-key'),
        ('put', 'non-prod', 'dev/typesafe.api-key'),
    ]

    calls = list(provider.calls)
    provider.on_put = lambda: None
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'typesafe.api-key', StringIO(PRIOR))
    with pytest.raises(HostSecretAdmissionError):
        with controller.admit('check', 'dev'):
            pytest.fail('ambiguous MARR write must keep the controller locked')
    assert provider.calls == calls
    assert not any(
        record['event'] in {'committed', 'rejected', 'terminal'}
        for record in history(controller)
    )


def test_typesafe_admin_check_uses_only_marr_project_and_exact_consumer_grant(setup):
    admin, provider, _ = setup
    provider.seed('dev/typesafe.api-key', CANARY, ('non-prod',))
    assert admin.check('dev', ['marr-server-dev']) == [
        {'secret': 'typesafe.api-key', 'status': 'ok'}
    ]
    assert provider.calls == [('read', 'non-prod', 'dev/typesafe.api-key')]
    with pytest.raises(SecretAdminError):
        admin.check('test', ['marr-server-dev'])
    provider.calls.clear()
    admin.check('dev', ['builderops-ckm-semantic'])
    assert set(provider.calls) == {
        ('read', 'non-prod', 'shared/openai.api-key'),
        ('read', 'prod', 'shared/openai.api-key'),
    }


def test_typesafe_import_rejects_non_dev_scope_before_provider_access(setup):
    admin, provider, _ = setup
    with pytest.raises(SecretAdminError):
        admin.import_stdin('test', 'typesafe.api-key', StringIO(CANARY))
    assert provider.calls == []
    assert provider.values == {}


def test_admin_project_inventory_has_only_existing_channel_projects():
    org, nonprod, prod = [str(uuid4()) for _ in range(3)]
    current = BwsSecretAdmin(BwsAdminConfig(org, nonprod, prod), token_reader=lambda: CANARY)
    assert current.config.projects() == {'non-prod': nonprod, 'prod': prod}
    with pytest.raises(SecretAdminError):
        current._scope('marr-dev', 'dev/typesafe.api-key')
    assert current._scope('non-prod', 'dev/typesafe.api-key') == nonprod
    for project, identity in (
        ('prod', 'dev/typesafe.api-key'),
        ('marr-dev', 'shared/openai.api-key'),
    ):
        with pytest.raises(SecretAdminError):
            current._scope(project, identity)


def test_admin_session_requires_the_exact_configured_project_inventory():
    org, nonprod, prod = [str(uuid4()) for _ in range(3)]

    def client_for(projects):
        auth = NS(login_access_token=lambda *_: NS(
            success=True, data=NS(authenticated=True)
        ))
        project_api = NS(list=lambda _organization: NS(
            success=True,
            data=NS(data=[NS(name=name, id=project_id, organization_id=org)
                          for name, project_id in projects]),
        ))
        return NS(auth=lambda: auth, projects=lambda: project_api)

    two_projects = client_for([('non-prod', nonprod), ('prod', prod)])
    admin = BwsSecretAdmin(BwsAdminConfig(org, nonprod, prod),
                           client_factory=lambda: two_projects, token_reader=lambda: CANARY)
    assert admin._session() is two_projects

    unexpected_marr_project = client_for(
        [('non-prod', nonprod), ('prod', prod), ('unexpected', str(uuid4()))]
    )
    admin_without_marr = BwsSecretAdmin(
        BwsAdminConfig(org, nonprod, prod),
        client_factory=lambda: unexpected_marr_project,
        token_reader=lambda: CANARY,
    )
    with pytest.raises(SecretAdminError):
        admin_without_marr._session()


def test_shared_import_history_records_genesis_tombstone_before_first_provision(setup):
    admin, provider, controller = setup
    def check_history():
        snapshots = [r for r in history(controller) if r['event'] == 'snapshot']
        assert {r['project'] for r in snapshots} == {'non-prod', 'prod'}
        assert all(r['previous_state'] == 'absent' and 'value' not in r for r in snapshots)
    provider.on_put = check_history
    admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))


def test_shared_import_missing_copy_tombstone_precedes_both_writes(setup):
    admin, provider, controller = setup
    provider.seed(projects=('non-prod',))
    def check_history():
        snapshots = [r for r in history(controller) if r['event'] == 'snapshot']
        assert [(r['project'], r['previous_state']) for r in snapshots] == [('non-prod', 'present'), ('prod', 'absent')]
    provider.on_put = check_history
    admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))


def test_shared_import_history_failure_leaves_both_copies_unchanged(setup, monkeypatch):
    admin, provider, _ = setup
    provider.seed()
    append = SecretHistory.append
    def fail_second(self, **record):
        if record['event'] == 'snapshot' and record['project'] == 'prod':
            raise OSError(CANARY)
        append(self, **record)
    monkeypatch.setattr(SecretHistory, 'append', fail_second)
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
    assert all(c.value == PRIOR for c in provider.values.values())
    assert not any(c[0] == 'put' for c in provider.calls)


def test_shared_secret_partial_update_is_compensated_or_reported_divergent(setup):
    admin, provider, controller = setup
    provider.seed()
    provider.fail['put', 'prod'] = PrecommitRejection()
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
    assert all(c.value == PRIOR for c in provider.values.values())
    assert history(controller)[-1]['result'] == 'aborted'
    operation_id = history(controller)[-1]['operation_id']
    assert provider.values['non-prod', IDENTITY].note == (
        f'owner text\n[yggdrasil-secret-operation:{operation_id}]'
    )
    assert provider.values['prod', IDENTITY].note == 'owner text'
    assert admin.check('dev', ['builderops-model-inquiry'])[0]['status'] == 'ok'


@pytest.mark.parametrize('compensation_fails', [False, True])
def test_shared_import_partial_failure_restores_absent_copy_or_reports_divergent(setup, compensation_fails):
    admin, provider, controller = setup
    provider.fail['put', 'prod'] = PrecommitRejection()
    if compensation_fails:
        provider.fail['delete', 'non-prod'] = PrecommitRejection()
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
    assert bool(provider.values) == compensation_fails
    if compensation_fails:
        with pytest.raises(SecretAdminError):
            admin.check('dev', ['builderops-model-inquiry'])
        with pytest.raises(HostSecretAdmissionError):
            with controller.admit('deploy', 'dev'):
                pytest.fail('divergence admitted deploy')
    else:
        assert history(controller)[-1]['result'] == 'aborted'


def test_deferred_protected_key_rotation_is_refused_without_value_disclosure(setup, capsys):
    admin, provider, _ = setup
    for secret in ['heimdal.raw-store-key', 'heimdal.archive-pass']:
        for command in ['generate', 'rotate', 'import']:
            args = [command, 'prod', secret] + (['--stdin'] if command == 'import' else [])
            assert main(args, admin=admin, stdin=StringIO(CANARY)) == 1
    assert provider.calls == []
    assert CANARY not in str(capsys.readouterr())


def test_shared_import_unknown_write_outcome_stays_pending_and_blocks_recovery(setup):
    admin, provider, controller = setup
    provider.seed()
    provider.fail['put', 'prod'] = RuntimeError(CANARY)
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
    calls = list(provider.calls)
    provider.fail.clear()
    # Even matching or absent item-note readback cannot establish terminality.
    for action in [lambda: admin.import_stdin('dev', 'openai.api-key', StringIO(PRIOR)),
                   lambda: admin.check('dev', ['builderops-model-inquiry'])]:
        with pytest.raises(SecretAdminError):
            action()
    assert provider.calls == calls
    with pytest.raises(HostSecretAdmissionError):
        with controller.admit('deploy', 'dev'):
            pytest.fail('unknown write admitted deploy')


def test_delayed_shared_write_cannot_land_after_recovery_import(setup):
    admin, provider, _ = setup
    provider.fail['put', 'prod'] = TimeoutError()
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
    provider.fail.clear()
    calls = list(provider.calls)
    # Model the still-running provider request landing after the timeout.
    provider.seed(value=CANARY, projects=('prod',))
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'openai.api-key', StringIO(PRIOR))
    assert provider.calls == calls
    assert all(c.value == CANARY for c in provider.values.values())


def test_shared_import_interruption_blocks_until_reimport_reconciles(setup, monkeypatch):
    admin, provider, controller = setup
    append = SecretHistory.append
    def crash_terminal(self, **record):
        if record['event'] == 'terminal':
            raise KeyboardInterrupt()
        append(self, **record)
    monkeypatch.setattr(SecretHistory, 'append', crash_terminal)
    with pytest.raises(KeyboardInterrupt):
        admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
    with pytest.raises(SecretAdminError):
        admin.check('dev', ['builderops-model-inquiry'])
    monkeypatch.setattr(SecretHistory, 'append', append)
    admin.import_stdin('dev', 'openai.api-key', StringIO(PRIOR))
    records = history(controller)
    assert records[-1]['previous_attempt'] is not None
    assert len([r for r in records if r['event'] == 'snapshot']) == 4
    assert all(c.value == PRIOR for c in provider.values.values())


def test_shared_import_cannot_interleave_with_deploy_check_to_compose(setup):
    admin, provider, controller = setup
    provider.seed()
    with controller.admit('deploy', 'dev') as operation:
        assert admin.check_selected(operation, 'dev', ['builderops-model-inquiry'])[0]['status'] == 'ok'
        with pytest.raises(SecretAdminError):
            admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
        assert all(c.value == PRIOR for c in provider.values.values())
        operation.finish(TerminalEvidence(operation.operation_id, 'deploy', 'dev', 'committed', 'remote-terminal'))


def test_admin_write_value_never_enters_argv_or_output(setup, monkeypatch, capsys):
    admin, provider, _ = setup
    import subprocess
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('subprocess called'))
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('subprocess called'))
    provider.fail['put', 'prod'] = RuntimeError(CANARY)
    assert main(['import', 'dev', 'openai.api-key', '--stdin'], admin=admin, stdin=StringIO(CANARY)) == 1
    assert CANARY not in str(capsys.readouterr())


def test_sdk_adapter_authenticates_without_cache_and_uses_request_body(monkeypatch):
    from bitwarden_sdk import BitwardenClient
    org, nonprod, prod, item = [str(uuid4()) for _ in range(4)]
    config = BwsAdminConfig(org, nonprod, prod)
    commands = []
    class Inner:
        def run_command(self, raw):
            command = json.loads(raw)
            commands.append(command)
            response = {'success': True}
            if 'loginAccessToken' in command:
                response['data'] = {'authenticated': True, 'resetMasterPassword': False, 'forcePasswordReset': False}
            elif 'projects' in command:
                response['data'] = {'data': [{'id': pid, 'name': name, 'organizationId': org,
                    'creationDate': '2026-01-01T00:00:00Z', 'revisionDate': '2026-01-01T00:00:00Z'}
                    for name, pid in [('non-prod', nonprod), ('prod', prod)]]}
            else:
                request = command['secrets']['create']
                response['data'] = {'id': item, 'key': request['key'], 'value': request['value'],
                    'note': request['note'], 'organizationId': org,
                    'projectId': request['projectIds'][0],
                    'creationDate': '2026-01-01T00:00:00Z', 'revisionDate': '2026-01-01T00:00:00Z'}
            return json.dumps(response)
    # Exercise the real SDK serialization boundary without constructing its native client.
    client = object.__new__(BitwardenClient)
    client.inner = Inner()
    adapter = BwsSecretAdmin(config, client_factory=lambda: client, token_reader=lambda: CANARY)
    result = adapter.put('non-prod', IDENTITY, None, PRIOR, 'owner\nmarker')
    assert result.value == PRIOR
    assert len(commands) == 3
    assert 'stateFile' not in json.dumps(commands[0])
    assert commands[-1]['secrets']['create']['value'] == PRIOR
    assert commands[-1]['secrets']['create']['projectIds'] == [nonprod]
    marr_copy = adapter.put('non-prod', 'dev/typesafe.api-key', None, CANARY, 'marr owner note')
    assert marr_copy.value == CANARY
    assert commands[-1]['secrets']['create']['key'] == 'dev/typesafe.api-key'
    assert commands[-1]['secrets']['create']['projectIds'] == [nonprod]


def test_sdk_exception_is_unknown_not_typed_rejection():
    org, nonprod, prod = [str(uuid4()) for _ in range(3)]
    client = NS(auth=lambda: NS(login_access_token=lambda *a: (_ for _ in ()).throw(RuntimeError(CANARY))))
    adapter = BwsSecretAdmin(BwsAdminConfig(org, nonprod, prod),
                             client_factory=lambda: client, token_reader=lambda: CANARY)
    with pytest.raises(SecretAdminError) as error:
        adapter.put('non-prod', IDENTITY, None, PRIOR, 'note')
    assert not isinstance(error.value, PrecommitRejection)
    assert CANARY not in str(error.value)


def test_partial_history_record_fails_closed(setup):
    admin, provider, controller = setup
    admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
    with (controller.directory / 'secret-history.jsonl').open('a') as sink:
        sink.write('{')
    calls = list(provider.calls)
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'openai.api-key', StringIO(PRIOR))
    assert provider.calls == calls


def test_history_fsync_failure_never_sends(setup, monkeypatch):
    admin, provider, controller = setup
    provider.seed()
    import os
    real = os.fsync
    def fail_history(fd):
        # Discover only fixture file identities, never inspect credential files.
        candidate = controller.directory / 'secret-history.jsonl'
        if candidate.exists() and os.fstat(fd).st_ino == candidate.stat().st_ino:
            raise OSError(CANARY)
        real(fd)
    monkeypatch.setattr(os, 'fsync', fail_history)
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
    assert not any(call[0] == 'put' for call in provider.calls)
    assert all(copy.value == PRIOR for copy in provider.values.values())


def test_postsend_interruption_has_no_terminal_record_and_cannot_recover(setup):
    admin, provider, _ = setup
    provider.on_put = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
    calls = list(provider.calls)
    provider.on_put = lambda: None
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'openai.api-key', StringIO(PRIOR))
    assert provider.calls == calls


def test_unknown_compensation_remains_pending(setup):
    admin, provider, _ = setup
    provider.fail['put', 'prod'] = PrecommitRejection()
    provider.fail['delete', 'non-prod'] = RuntimeError(CANARY)
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
    calls = list(provider.calls)
    provider.fail.clear()
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'openai.api-key', StringIO(PRIOR))
    assert provider.calls == calls


def test_history_symlink_is_refused_before_provider_write(setup, tmp_path):
    admin, provider, controller = setup
    controller.directory.mkdir(mode=0o700)
    target = tmp_path / 'other'
    target.write_text('untouched')
    (controller.directory / 'secret-history.jsonl').symlink_to(target)
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY))
    assert target.read_text() == 'untouched'
    assert provider.calls == []


def test_invalid_import_is_exact_not_stripped_and_never_reads_provider(setup):
    admin, provider, _ = setup
    with pytest.raises(SecretAdminError):
        admin.import_stdin('dev', 'openai.api-key', StringIO(CANARY + '\n'))
    assert provider.calls == []
