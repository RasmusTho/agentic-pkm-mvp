"""Real pytest output crosses the retained Verify and full-evidence boundaries."""

import json
import os
import subprocess
import sys

import pytest

from app.builderops import openhands_delivery as delivery
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.test_openhands_candidate_verify_v5 import verify_fixture
from tests.builderops.test_openhands_pr_cycle_p2_repair import HEAD, _verify_setup


@pytest.mark.parametrize(('mode', 'stream', 'accepted'), [
    ('skip', 'none', False), ('skip', 'stderr', False), ('skip', 'stdout', False),
    ('xfail', 'stderr', False), ('xpass', 'stdout', False),
    ('deselected', 'stderr', False), ('missing', 'stdout', False),
    ('failure', 'stderr', False), ('error', 'stderr', False), ('pass', 'none', True),
    ('pass', 'diagnostic', True), ('pass', 'stderr', False),
])
def test_real_results_and_full_validator(tmp_path, mode, stream, accepted):
    work = tmp_path / 'work'
    (work / 'tests').mkdir(parents=True)
    footer = {'none': '', 'stderr': '1 passed', 'stdout': '1 passed',
              'diagnostic': 'ordinary teardown diagnostic'}[stream]
    behavior = {'skip': 'pytest.skip("missing")', 'xfail': 'pytest.xfail("missing")',
                'xpass': 'pass', 'failure': 'assert False', 'deselected': 'pass',
                'missing': 'pass', 'error': 'pass', 'pass': 'pass'}[mode]
    marker = '@pytest.mark.xfail(reason="unexpected pass")\n' if mode == 'xpass' else ''
    source = ('import atexit,sys,pytest\n'
              + (f'atexit.register(lambda: print({footer!r}, file=sys.{"stdout" if stream == "stdout" else "stderr"}))\n' if footer else '')
              + ('@pytest.fixture(autouse=True)\ndef fixture():\n    yield\n    raise RuntimeError("teardown")\n' if mode == 'error' else '')
              + marker + '@pytest.mark.parametrize("n", [0, 1])\n'
              + f'def test_example(n):\n    if n: {behavior}\n    assert True\n')
    (work / 'tests/test_example.py').write_text(source)
    target = 'tests/test_example.py::' + ('test_absent' if mode == 'missing' else 'test_example')
    extra = ['-k', '0'] if mode == 'deselected' else []
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *extra, target],
                            cwd=work, capture_output=True, text=True,
                            env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
    output = result.stdout + '\n' + result.stderr
    (tmp_path / 'actual-output.json').write_text(json.dumps({'exit': result.returncode, 'stdout': result.stdout,
                                                              'stderr': result.stderr}, indent=2))
    assert bool(delivery._pytest_pass_count(output)) is accepted
    head, base = 'a' * 40, 'b' * 40
    review, evidence = tmp_path / 'review.txt', tmp_path / 'output.txt'
    review.write_text(f'independent review candidate {head} pass\n')
    evidence.write_text(output)
    body = f'## Acceptance Criteria\n- [ ] Required behavior.\n  - Verify: `{target}`\n'
    receipt = {'version': 1, 'repository': delivery.REPOSITORY, 'issue': 123, 'head_sha': head, 'base_sha': base,
        'risk_surfaces': [], 'review': {'verdict': 'pass', 'head_sha': head, 'reviewer': 'independent',
        'blocking_findings': [], 'evidence': {'path': str(review)}}, 'verification': [
        {'target': target, 'head_sha': head, 'result': 'pass', 'evidence': {'path': str(evidence)}}]}
    path = tmp_path / 'evidence.json'
    path.write_text(json.dumps(receipt))
    args = (path, {'worktree': str(work), 'issue': 123}, head, base, body)
    if accepted:
        assert result.returncode == 0
        delivery._full_evidence(*args)
    else:
        with pytest.raises(delivery.DeliveryError, match='Test source does not substantiate'):
            delivery._full_evidence(*args)


def test_summary_requires_one_complete_known_result():
    assert not delivery._pytest_pass_count('1 passed\n')
    assert not delivery._pytest_pass_count('1 passed, 1 rerun in 0.1s\n1 passed in 0.2s\n')
    assert delivery._pytest_pass_count('diagnostic: database ready\n1 passed in 61.2s (0:01:01)\n') == 1


@pytest.mark.parametrize(('stream', 'incomplete'), [('stderr', True), ('stdout', True), ('stderr', False)])
def test_candidate_bash_boundary_retains_ambiguous_result(tmp_path, capsys, monkeypatch, stream, incomplete):
    footer = '1 passed' if incomplete else 'ordinary teardown diagnostic'
    source = (f'import atexit,sys,pytest\natexit.register(lambda: print({footer!r}, file=sys.{stream}))\n'
              '@pytest.mark.parametrize("n", [0, 1])\ndef test_example(n):\n'
              + ('    if n: pytest.skip("missing")\n' if incomplete else '') + '    assert True\n')
    data, _, identity, _, _, _, advance, events, calls = verify_fixture(
        tmp_path, capsys, monkeypatch, test_source=source)
    result = advance()
    saved = cycle._find(data[0], 10, identity)
    verification = saved['candidate_verification']
    command = verification['commands'][0]
    assert command['exit_code'] == 0 and command['output_event_ids'] and command['output_events_sha256']
    assert verification['stop_verified'] and cycle._mapping(data[0], verification['worker'])['state'] == 'stopped_verified'
    assert len([c for c in calls if c[0] == 'POST']) == 1
    assert len([e for e in events if e['kind'] == 'BashCommand']) == 1
    if incomplete:
        assert '1 skipped' in command['stdout'] and '1 passed' in command[stream]
        assert result['action'] == 'candidate-verify-failed'
        assert 'incomplete or ambiguous' in verification['next_action']
        assert 'evidence_file' not in verification and 'repair_publication' not in saved
    else:
        assert verification['state'] == 'artifact_ready' and result['action'] == 'wait'
        assert 'ordinary teardown diagnostic' in command['stderr']
        assert cycle.Path(verification['evidence_file']).is_file()


@pytest.mark.parametrize('incomplete', [True, False])
def test_ordinary_sandbox_verify_interprets_real_output(tmp_path, monkeypatch, incomplete):
    source = tmp_path / 'test_real.py'
    source.write_text('import atexit,sys,pytest\n'
        + ('atexit.register(lambda: print("1 passed", file=sys.stderr))\n' if incomplete else '')
        + '@pytest.mark.parametrize("n", [0, 1])\ndef test_example(n):\n'
        + ('    if n: pytest.skip("missing")\n' if incomplete else '') + '    assert True\n')
    observed = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', str(source)],
        cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
    assert observed.returncode == 0
    layout, saved = _verify_setup(tmp_path, monkeypatch)
    def command(argv, *, timeout):
        if argv[1] == 'create':
            return subprocess.CompletedProcess(argv, 0, 'd' * 64, '')
        return subprocess.CompletedProcess(argv, observed.returncode, observed.stdout, observed.stderr)
    monkeypatch.setattr(cycle, '_command', command)
    monkeypatch.setattr(cycle.workspace, '_remove_owned', lambda *args, **kwargs: None)
    result = cycle.sandbox_verify(layout, 'reviewer', HEAD, ['tests/example.py'], '/approved/venv', saved)
    assert result['passed'] is not incomplete
    assert result['exit_code'] == 0 and len(result['output_sha256']) == 64
