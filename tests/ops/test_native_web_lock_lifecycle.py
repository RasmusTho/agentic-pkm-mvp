"""Actual admission/inode/flock paths; no native service or scenario substitute."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ops import postgres_deploy_linux as linux
from app.ops.native_web_acceptance import NativeWebRefusal
from app.ops.postgres_deploy import DeployJournal, DeployPlan, PostgresDeployError
from tests.deploy.test_postmerge_pg_acceptance import DIGEST, _result


@pytest.fixture
def admitted(tmp_path, monkeypatch):
    root = tmp_path / 'checkout'
    (root / 'config/deploy').mkdir(parents=True)
    journal = DeployJournal(tmp_path / 'journal', 'test')
    operation = str(uuid4())
    plan = DeployPlan('test', 'a' * 40, ('db', 'api'), ('postgres-db', 'postgres-api'),
                      image_digest=DIGEST, automatic=True)
    journal.bind_request(operation, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'authenticating', 'activating', 'verifying'):
        journal.write(operation, stage)
    journal.write(operation, 'committed', _result(plan.revision, 'test', operation))
    effects = linux.LinuxEffects(SimpleNamespace(root=root, journal=journal, channel='test'))
    # Only native host ownership and Docker quiescence are unavailable locally.
    # Admission, journal, mkdir, descriptors/flock and retirement are real.
    monkeypatch.setattr(linux, '_private_json', lambda path: json.loads(path.read_text()))
    monkeypatch.setattr(effects, 'quiescent', lambda: True)
    monkeypatch.setattr(effects, '_qualification_other_absent', lambda _profile, _proof: True)
    return effects, operation, root / 'config/deploy/test.env.lock'


def confirmed(effects, monkeypatch):
    calls = []
    def qualify(operation):
        assert effects.lock_fd is not None
        calls.append(operation)
        # A refused feature result can have confirmed worker cleanup. This is
        # solely a local lock boundary assertion, never fabricated native PASS.
        return {'result': 'refused', 'cleanup': 'confirmed'}
    monkeypatch.setattr(effects, 'qualify_web', qualify)
    return calls


@pytest.mark.parametrize('reply', [{'result': 'unknown', 'cleanup': 'unknown'}, {'result': 'refused'}])
def test_fresh_unknown_cleanup_retains_real_admission_until_exact_retry(admitted, monkeypatch, reply):
    effects, operation, lock = admitted
    before = effects.config.journal.read().payload()
    monkeypatch.setattr(effects, 'qualify_web', lambda _operation: reply)
    with pytest.raises(PostgresDeployError):
        effects.run_web_qualification(operation)
    assert lock.is_dir() and (lock / 'bws-owner').is_file() and effects.lock_fd is None
    identity = (lock.stat().st_ino, (lock / 'bws-owner').stat().st_ino)
    with pytest.raises(FileExistsError):
        with effects.channel_lock():
            pytest.fail('unconfirmed native resources must retain admission')
    with pytest.raises(NativeWebRefusal):
        effects.run_web_qualification(str(uuid4()))
    assert identity == (lock.stat().st_ino, (lock / 'bws-owner').stat().st_ino)
    assert effects.config.journal.read().payload() == before
    calls = confirmed(effects, monkeypatch)
    assert effects.run_web_qualification(operation)['result'] == 'refused'
    assert calls == [operation] and not lock.exists()


def test_fresh_no_result_retains_real_admission(admitted, monkeypatch):
    effects, operation, lock = admitted
    def crash(_operation):
        assert effects.lock_fd is not None
        raise NativeWebRefusal('interrupted_native_boundary')
    monkeypatch.setattr(effects, 'qualify_web', crash)
    with pytest.raises(NativeWebRefusal, match='interrupted_native_boundary'):
        effects.run_web_qualification(operation)
    assert lock.is_dir() and effects.lock_fd is None
    confirmed(effects, monkeypatch)
    assert effects.run_web_qualification(operation)['cleanup'] == 'confirmed'
    assert not lock.exists()


def test_fresh_confirmed_cleanup_retires_without_a_second_qualifier(admitted, monkeypatch):
    effects, operation, lock = admitted
    calls = confirmed(effects, monkeypatch)
    before = effects.config.journal.read().payload()
    assert effects.run_web_qualification(operation) == {'result': 'refused', 'cleanup': 'confirmed'}
    assert calls == [operation] and not lock.exists() and effects.lock_fd is None
    assert effects.config.journal.read().payload() == before


def test_fresh_foreign_inode_replacement_is_preserved(admitted, monkeypatch):
    effects, operation, lock = admitted
    original = lock.with_name('detached-original')
    foreign = []
    def replace(_operation):
        lock.rename(original)
        lock.mkdir(mode=0o700)
        descriptor = os.open(lock / 'bws-owner', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        foreign.append((lock.stat().st_ino, (lock / 'bws-owner').stat().st_ino))
        return {'result': 'refused', 'cleanup': 'confirmed'}
    monkeypatch.setattr(effects, 'qualify_web', replace)
    with pytest.raises(PostgresDeployError):
        effects.run_web_qualification(operation)
    assert foreign == [(lock.stat().st_ino, (lock / 'bws-owner').stat().st_ino)]
    assert (lock / 'bws-owner').read_bytes() == b''
    assert (original / 'bws-owner').is_file() and effects.lock_fd is None


def test_retirement_interruption_preserves_admission_for_exact_recovery(admitted, monkeypatch):
    effects, operation, lock = admitted
    confirmed(effects, monkeypatch)
    retire = effects.retire_reconciled_channel_lock
    def interrupted(_handle, **_kwargs):
        raise PostgresDeployError()
    monkeypatch.setattr(effects, 'retire_reconciled_channel_lock', interrupted)
    with pytest.raises(PostgresDeployError):
        effects.run_web_qualification(operation)
    assert lock.is_dir() and effects.lock_fd is None
    monkeypatch.setattr(effects, 'retire_reconciled_channel_lock', retire)
    assert effects.run_web_qualification(operation)['cleanup'] == 'confirmed'
    assert not lock.exists()


def test_quiescence_unknown_keeps_retained_admission(admitted, monkeypatch):
    effects, operation, lock = admitted
    confirmed(effects, monkeypatch)
    monkeypatch.setattr(effects, 'quiescent', lambda: False)
    with pytest.raises(PostgresDeployError):
        effects.run_web_qualification(operation)
    assert lock.is_dir() and effects.lock_fd is None
    monkeypatch.setattr(effects, 'quiescent', lambda: True)
    assert effects.run_web_qualification(operation)['cleanup'] == 'confirmed'
    assert not lock.exists()
