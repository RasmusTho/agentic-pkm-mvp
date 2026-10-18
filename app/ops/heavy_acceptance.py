"""Post-merge heavy-test profile run on the ygg `test` VM (#6158).

`scripts/select_pr_tests.py :: HEAVY_PR_DEFERRED_TARGETS` defers heavy targets
from the required PR check. After a candidate's native `test` deployment
commits, the host controller runs this fixed profile on the VM and dispatches
its bounded verdict to `.github/workflows/post-merge-heavy-tests.yml`.

The profile runs inside the admitted image against the exact candidate tree
at `/work`, with the selector's own heavy targets, the PR marker expression and
the 120-second thread watchdog, matching the GitHub-hosted run it replaces.
It does not gate channel advancement or rewrite `postmerge-pg.v1`.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any
from uuid import UUID

PROFILE_VERSION = 'postmerge-heavy.v1'
TEST_TIMEOUT = 120
PROFILE_DEADLINE = 3600
RESULT_PREFIX = 'YGGDRASIL_HEAVY_ACCEPTANCE='
# A docker-gated test that skips on the VM would be silent coverage loss
# against the GitHub-hosted run, which always has the docker CLI.
DOCKER_SKIP_REASON = 'docker executable not found'
MAX_FAILURES = 20
MAX_NODEID = 200
VERDICTS = ('passed', 'failed', 'refused')
COUNT_KEYS = ('selected', 'passed', 'failed', 'skipped', 'docker_skipped')


class HeavyAcceptanceError(RuntimeError):
    def __init__(self, reason: str = 'heavy_acceptance_refused') -> None:
        super().__init__(reason)
        self.reason = reason


def identity(sha: str, digest: str, channel: str, operation_id: str) -> dict[str, str]:
    if (re.fullmatch(r'[0-9a-f]{40}', sha) is None
        or re.fullmatch(r'sha256:[0-9a-f]{64}', digest) is None
        or channel not in {'dev', 'test'} or str(UUID(operation_id)) != operation_id):
        raise HeavyAcceptanceError('heavy_identity_refused')
    return {'profile_version': PROFILE_VERSION, 'source_sha': sha, 'image_digest': digest,
            'channel': channel, 'operation_id': operation_id}


def _bounded_failures(value: Any) -> list[str]:
    if (not isinstance(value, list) or len(value) > MAX_FAILURES
        or any(not isinstance(item, str) or not item or len(item) > MAX_NODEID
               or re.search(r'[\x00-\x1f]', item) for item in value)):
        raise HeavyAcceptanceError('heavy_evidence_refused')
    return list(value)


def classify(summary: Any, expected: dict[str, str]) -> dict[str, Any]:
    """Turn an in-container summary into a bounded verdict; never a vacuous pass."""
    if (not isinstance(summary, dict)
        or set(summary) != set(expected) | {'targets', 'exit_status', 'failures', 'report_hash', *COUNT_KEYS}
        or any(summary.get(key) != value for key, value in expected.items())
        or not isinstance(summary['targets'], list) or not summary['targets']
        or any(not isinstance(t, str) or re.fullmatch(r'tests/[A-Za-z0-9_./-]+', t) is None
               for t in summary['targets'])
        or type(summary['exit_status']) is not int
        or any(type(summary[key]) is not int or summary[key] < 0 for key in COUNT_KEYS)
        or re.fullmatch(r'[0-9a-f]{64}', str(summary['report_hash'])) is None):
        raise HeavyAcceptanceError('heavy_evidence_refused')
    failures = _bounded_failures(summary['failures'])
    passed = (summary['exit_status'] == 0 and summary['failed'] == 0 and summary['docker_skipped'] == 0
              and summary['selected'] > 0 and summary['passed'] > 0 and not failures)
    return {**expected, 'result': 'passed' if passed else 'failed', 'targets': summary['targets'],
            'failures': failures, 'report_hash': summary['report_hash'],
            **{key: summary[key] for key in COUNT_KEYS}}


def refusal(reason: str) -> dict[str, Any]:
    if re.fullmatch(r'[a-z0-9_]{1,64}', reason) is None:
        reason = 'heavy_acceptance_refused'
    return {'profile_version': PROFILE_VERSION, 'result': 'refused', 'reason': reason}


def _load_selector(root: Path) -> Any:
    spec = importlib.util.spec_from_file_location('heavy_select_pr_tests', root / 'scripts/select_pr_tests.py')
    if spec is None or spec.loader is None:
        raise HeavyAcceptanceError('heavy_selector_unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pytest_arguments(marker: str, targets: list[str]) -> list[str]:
    return ['-q', '-m', marker, *targets, '--tb=short', '-p', 'timeout',
            '--timeout=' + str(TEST_TIMEOUT), '--timeout-method=thread',
            '-o', 'cache_dir=/tmp/heavy-acceptance-cache']


class HeavyResults:
    """Count outcomes; a failure, error or docker-gated skip cannot pass."""
    def __init__(self) -> None:
        self.nodes: set[str] = set()
        self.passed: set[str] = set()
        self.failed: list[str] = []
        self.skipped = 0
        self.docker_skipped = 0
        self.watchdog = False

    def pytest_collection_finish(self, session: Any) -> None:
        self.nodes = {item.nodeid for item in session.items}
        self.watchdog = (session.config.getoption('timeout') == TEST_TIMEOUT
                         and session.config.getoption('timeout_method') == 'thread')

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.failed:
            if report.nodeid not in self.failed:
                self.failed.append(report.nodeid)
        elif report.skipped and not hasattr(report, 'wasxfail'):
            self.skipped += 1
            if DOCKER_SKIP_REASON in str(report.longrepr):
                self.docker_skipped += 1
        elif report.when == 'call' and report.passed:
            self.passed.add(report.nodeid)

    def pytest_collectreport(self, report: Any) -> None:
        if report.failed:
            self.failed.append(report.nodeid or 'collection')

    def summary(self, exit_status: int) -> dict[str, Any]:
        if not self.watchdog:
            raise HeavyAcceptanceError('heavy_watchdog_missing')
        report_hash = hashlib.sha256(json.dumps(
            [sorted(self.passed), self.failed], separators=(',', ':')).encode()).hexdigest()
        return {'exit_status': exit_status, 'selected': len(self.nodes), 'passed': len(self.passed),
                'failed': len(self.failed), 'skipped': self.skipped, 'docker_skipped': self.docker_skipped,
                'failures': [node[:MAX_NODEID] for node in self.failed[:MAX_FAILURES]],
                'report_hash': report_hash}


def run(manifest: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    import pytest
    root = Path.cwd() if root is None else root  # The container's workdir is the exact tree.
    expected = identity(manifest['source_sha'], manifest['image_digest'],
                        manifest['channel'], manifest['operation_id'])
    selector = _load_selector(root)
    targets = list(selector.HEAVY_PR_DEFERRED_TARGETS)
    if not targets:
        raise HeavyAcceptanceError('heavy_selection_empty')
    plugin = HeavyResults()
    exit_status = int(pytest.main(pytest_arguments(selector.PR_MARKER_EXPRESSION, targets), plugins=[plugin]))
    return {**expected, 'targets': targets, **plugin.summary(exit_status)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = run(json.loads(args.manifest.read_text()))
        print(RESULT_PREFIX + json.dumps(summary, sort_keys=True))
        return 0
    except Exception as exc:
        print('heavy acceptance refused: ' + type(exc).__name__, file=sys.stderr)
        print(RESULT_PREFIX + 'refused')
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
