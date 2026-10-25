import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ops import postgres_deploy_linux as linux
from app.ops.host_secret_controller import (
    HostSecretAdmissionError,
    HostSecretController,
    TerminalEvidence,
)
from app.ops.postgres_deploy import DeployJournal, DeployPlan, PostgresDeployError


SHA = 'a' * 40
DIGEST = 'sha256:' + 'b' * 64


def _terminal_foreign(tmp_path):
    journal = DeployJournal(tmp_path / 'journal', 'dev')
    foreign = str(uuid4())
    plan = DeployPlan('dev', 'f' * 40, ('db',), ('postgres-db',),
                      image_digest='sha256:' + 'e' * 64, automatic=True)
    journal.bind_request(foreign, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating', 'failed'):
        journal.write(foreign, stage)
    root = tmp_path / 'checkout'
    (root / 'config/deploy').mkdir(parents=True)
    config = SimpleNamespace(channel='dev', journal=journal, root=root)
    supervisor = linux.DeploymentSupervisor(config)
    supervisor._require_current_config = lambda: None
    return supervisor, journal


def test_operation_absence_probe_returns_fixed_content_free_fields(tmp_path):
    supervisor, _journal = _terminal_foreign(tmp_path)
    operation_id = str(uuid4())
    plan = DeployPlan('dev', SHA, ('db',), ('postgres-db',),
                      image_digest=DIGEST, automatic=True)
    result = supervisor.request({
        'action': 'prove-absence', 'operation_id': operation_id,
        'plan': json.loads(json.dumps(plan.payload())), 'bootstrap': False,
    })
    assert result == {
        'contract': 'native-deploy-operation-absence.v1',
        'operation_id': operation_id,
        'channel': 'dev',
        'candidate_sha': SHA,
        'image_digest': DIGEST,
        'native_operation_absent': True,
        'native_worker_absent': True,
        'native_lock_absent': True,
        'native_request_absent': True,
    }
    assert 'plan' not in result and 'source' not in json.dumps(result)


def test_host_absence_proof_holds_admission_lock_and_rejects_recorded_id(tmp_path):
    controller = HostSecretController(tmp_path / 'host')
    operation_id = str(uuid4())
    remote = {
        'contract': 'native-deploy-operation-absence.v1',
        'operation_id': operation_id,
        'channel': 'dev',
        'candidate_sha': SHA,
        'image_digest': DIGEST,
        'native_operation_absent': True,
        'native_worker_absent': True,
        'native_lock_absent': True,
        'native_request_absent': True,
    }

    def readback():
        with pytest.raises(HostSecretAdmissionError):
            with controller.admit('check', 'shared'):
                pytest.fail('host admission raced absence proof')
        return remote

    proof = controller.prove_deploy_absence(operation_id, 'dev', readback)
    assert proof == {
        **remote, 'host_operation_absent': True, 'host_operation_retired': True,
    }

    # The durable fence closes the proof-to-checkpoint gap. It is resumable,
    # but the exact ID can never enter host admission after proof succeeds.
    assert controller.prove_deploy_absence(operation_id, 'dev', lambda: remote) == proof
    with pytest.raises(HostSecretAdmissionError):
        with controller.deploy_operation(
            'dev', allow_bootstrap=False, operation_id=operation_id
        ):
            pytest.fail('retired ID re-entered host admission')

    admitted_id = str(uuid4())
    with controller.deploy_operation(
        'dev', allow_bootstrap=False, operation_id=admitted_id
    ) as (operation, resumed):
        assert not resumed
        operation.prepare_mutation()
        operation.finish(TerminalEvidence(
            admitted_id, 'deploy', 'dev', 'failed', 'remote-terminal'
        ))
    with pytest.raises(HostSecretAdmissionError):
        controller.prove_deploy_absence(
            admitted_id, 'dev', lambda: pytest.fail('recorded ID reached remote probe')
        )


def test_absence_retirement_is_sideband_to_unrelated_host_pending_operation(tmp_path):
    controller = HostSecretController(tmp_path / 'host')
    with controller.admit('check', 'shared') as unrelated:
        unrelated_id = unrelated.operation_id
    operation_id = str(uuid4())
    remote = {
        'contract': 'native-deploy-operation-absence.v1',
        'operation_id': operation_id,
        'channel': 'dev',
        'candidate_sha': SHA,
        'image_digest': DIGEST,
        'native_operation_absent': True,
        'native_worker_absent': True,
        'native_lock_absent': True,
        'native_request_absent': True,
    }

    assert controller.prove_deploy_absence(operation_id, 'dev', lambda: remote)[
        'host_operation_retired'
    ] is True
    observed = []

    def readback(selected_id, kind, target):
        observed.append((selected_id, kind, target))
        return TerminalEvidence(selected_id, kind, target, 'committed', 'read-complete')

    controller.reconcile(readback)
    assert observed == [(unrelated_id, 'check', 'shared')]
    with controller._locked_journal() as descriptor:
        assert controller._pending(descriptor) is None
    with pytest.raises(HostSecretAdmissionError):
        with controller.deploy_operation(
            'dev', allow_bootstrap=False, operation_id=operation_id
        ):
            pytest.fail('sideband retirement fence was lost')


@pytest.mark.parametrize('footprint', ['operation', 'request', 'lock', 'worker'])
def test_foreign_terminal_requires_no_worker_lock_or_request_mutation(tmp_path, footprint):
    supervisor, journal = _terminal_foreign(tmp_path)
    operation_id = str(uuid4())
    plan = DeployPlan('dev', SHA, ('db',), ('postgres-db',),
                      image_digest=DIGEST, automatic=True)
    if footprint == 'operation':
        journal = DeployJournal(tmp_path / 'matching', 'dev')
        journal.bind_request(operation_id, plan, False, create=True)
        for stage in ('prepared', 'preflighted', 'materialized', 'activating', 'failed'):
            journal.write(operation_id, stage)
        supervisor.config.journal = journal
    elif footprint == 'request':
        request_path = journal.directory / 'dev.request.json'
        request = json.loads(request_path.read_text())
        request['operation_id'] = operation_id
        request_path.write_text(json.dumps(request))
    elif footprint == 'lock':
        lock = supervisor.config.root / 'config/deploy/dev.env.lock'
        lock.mkdir()
    else:
        supervisor.operation = SimpleNamespace(
            operation_id=operation_id,
            finished=SimpleNamespace(is_set=lambda: False),
            thread=SimpleNamespace(is_alive=lambda: True),
        )
    with pytest.raises(PostgresDeployError):
        supervisor.request({
            'action': 'prove-absence', 'operation_id': operation_id,
            'plan': json.loads(json.dumps(plan.payload())), 'bootstrap': False,
        })
