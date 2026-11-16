"""Focused redaction and preservation coverage for source-RPC diagnostics."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.deploy import test_bws_source_rpc_assembly as rpc


def test_rpc_failure_diagnostics_are_redacted_and_cycle_safe() -> None:
    marker = 'PRIVATE_CANARY_RPC_DIAGNOSTIC'
    try:
        try:
            raise OSError(5, marker)
        except OSError as context:
            raise RuntimeError(marker) from context
    except RuntimeError as error:
        diagnostic = rpc._rpc_failure_diagnostic(error, [{
            'category': 'clean', 'return_code': 0, 'stderr_present': False, 'clean': True,
        }])
    assert marker not in repr(diagnostic)
    assert diagnostic['class'] == 'RuntimeError'
    assert diagnostic['context'][0]['class'] == 'OSError'
    assert diagnostic['context'][0]['errno'] == 5
    assert diagnostic['git_checks'][0]['clean'] is True

    cyclic = RuntimeError(marker)
    cyclic.__context__ = cyclic
    assert len(rpc._rpc_failure_diagnostic(cyclic, [])['context']) == 1

    try:
        try:
            raise OSError(6, marker)
        except OSError:
            raise RuntimeError(marker) from None
    except RuntimeError as error:
        suppressed = rpc._rpc_failure_diagnostic(error, [])
    assert suppressed['context'][0]['class'] == 'OSError'


def test_rpc_failure_diagnostics_preserve_original_failure(monkeypatch) -> None:
    original = RuntimeError('PRIVATE_CANARY_RPC_DIAGNOSTIC')
    state: dict[str, object] = {}
    monkeypatch.setattr(
        rpc, '_rpc_failure_diagnostic',
        lambda *_args: (_ for _ in ()).throw(AssertionError('diagnostic probe failed')),
    )
    with pytest.raises(RuntimeError) as raised:
        try:
            raise original
        except Exception as error:
            rpc._record_rpc_failure(state, error)
            raise
    assert raised.value is original
    assert 'rpc_failure' not in state


def test_rpc_failure_emission_is_redacted_bounded_and_repeated(capsys) -> None:
    marker = 'PRIVATE_CANARY_RPC_DIAGNOSTIC'
    state: dict[str, object] = {}
    result = SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
    for _ in range(rpc._RPC_GIT_CHECK_LIMIT + 3):
        rpc._record_rpc_git_check(state, 'clean', result)
    try:
        try:
            raise OSError(7, marker)
        except OSError as context:
            raise RuntimeError(marker) from context
    except RuntimeError as error:
        rpc._emit_rpc_failure_diagnostic(state, error)
        rpc._emit_rpc_failure_diagnostic(state, error)
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 2
    payload = json.loads(lines[0])
    assert payload['schema'] == 'rpc-failure-diagnostic.v1'
    assert marker not in '\n'.join(lines)
    assert payload['rpc_failure']['class'] == 'RuntimeError'
    assert payload['rpc_failure']['context'][0]['class'] == 'OSError'
    assert len(payload['rpc_git_checks']) == rpc._RPC_GIT_CHECK_LIMIT
    assert payload['rpc_git_checks_dropped'] == 3


def test_rpc_failure_emission_preserves_original_failure_when_stderr_fails(monkeypatch) -> None:
    class BrokenStderr:
        def write(self, _value):
            raise OSError('PRIVATE_CANARY stderr')

    original = RuntimeError('PRIVATE_CANARY_RPC_DIAGNOSTIC')
    monkeypatch.setattr(sys, 'stderr', BrokenStderr())
    with pytest.raises(RuntimeError) as raised:
        try:
            raise original
        except Exception as error:
            rpc._emit_rpc_failure_diagnostic({}, error)
            raise
    assert raised.value is original


def test_rpc_failure_emission_does_not_reuse_stale_failure_when_build_fails(
    monkeypatch, capsys,
) -> None:
    state: dict[str, object] = {}
    first = RuntimeError('PRIVATE_CANARY first')
    second = RuntimeError('PRIVATE_CANARY second')
    rpc._emit_rpc_failure_diagnostic(state, first)
    capsys.readouterr()
    monkeypatch.setattr(
        rpc, '_rpc_failure_diagnostic',
        lambda *_args: (_ for _ in ()).throw(AssertionError('diagnostic probe failed')),
    )
    with pytest.raises(RuntimeError) as raised:
        try:
            raise second
        except Exception as error:
            rpc._emit_rpc_failure_diagnostic(state, error)
            raise
    assert raised.value is second
    assert state.get('rpc_failure') is None
    assert capsys.readouterr().err == ''


def test_rpc_git_recording_is_bounded_and_preserves_success_on_probe_failure(monkeypatch) -> None:
    state: dict[str, object] = {}
    monkeypatch.setattr(
        rpc, '_rpc_git_record',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('probe failed')),
    )
    result = SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
    rpc._record_rpc_git_check(state, 'clean', result)
    native_result = object()
    observed = lambda argv: rpc._rpc_observed_git_run(
        state, lambda _argv: native_result, Path('/tmp/root'), 'revision', argv,
    )
    assert observed(['git', 'status', '--porcelain=v1']) is native_result
    assert state['rpc_git_checks'] == []

    monkeypatch.undo()
    bounded_state: dict[str, object] = {}
    for _ in range(rpc._RPC_GIT_CHECK_LIMIT + 4):
        rpc._record_rpc_git_check(bounded_state, 'clean', result)
    assert len(bounded_state['rpc_git_checks']) == rpc._RPC_GIT_CHECK_LIMIT
    assert bounded_state['rpc_git_checks_dropped'] == 4


@pytest.mark.parametrize('error', [OSError(5, 'PRIVATE_CANARY'), subprocess.TimeoutExpired('git', 20)])
def test_rpc_git_recording_preserves_observed_exception_on_probe_failure(monkeypatch, error) -> None:
    state: dict[str, object] = {}
    monkeypatch.setattr(
        rpc, '_rpc_git_record',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('probe failed')),
    )
    observed = lambda argv: rpc._rpc_observed_git_run(
        state, lambda _argv: (_ for _ in ()).throw(error), Path('/tmp/root'), 'revision', argv,
    )
    with pytest.raises(type(error)) as raised:
        observed(['git', 'rev-parse', 'HEAD'])
    assert raised.value is error
