"""Route controller terminal evidence to one Actions-owned rolling Issue per channel.

Only the reviewed main workflow invokes writes. The controller retains its
Actions read/write client; native receipts cross as bounded public evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable
from urllib.parse import quote

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.postmerge_dev_test import (
    BUILD_JOB, BUILD_WORKFLOW, Candidate, REPOSITORY, validate_channel_evidence,
)

WORKFLOW = 'postmerge-channel-bug.yml'
BOT = 'github-actions[bot]'
EVENT_MARKER = '<!-- postmerge-channel-verdict:v1 -->'
MAX_PAGES = 10


class AlertRefused(ValueError):
    pass


def _api(method: str, path: str, data: dict[str, Any] | None = None) -> Any:
    command = ['gh', 'api', '--method', method, path]
    if data is not None:
        command += ['--input', '-']
    result = subprocess.run(command, input=json.dumps(data) if data is not None else None,
                            capture_output=True, text=True, timeout=60, check=False)
    if result.returncode or len(result.stdout) > 2 * 1048576:
        raise AlertRefused('github_request_failed')
    try:
        return json.loads(result.stdout) if result.stdout else None
    except ValueError:
        raise AlertRefused('github_response_refused') from None


def validate_evidence(evidence: Any, channel: str) -> Candidate:
    try:
        return validate_channel_evidence(evidence, channel)
    except Exception:
        raise AlertRefused('channel_evidence_refused') from None


def _owned(row: dict[str, Any]) -> bool:
    return row.get('user', {}).get('login') == BOT and row.get('user', {}).get('type') == 'Bot'


def _pages(api: Callable[..., Any], path: str) -> list[dict[str, Any]]:
    rows = []
    for page in range(1, MAX_PAGES + 1):
        batch = api('GET', f'{path}&per_page=100&page={page}')
        if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
            raise AlertRefused('github_listing_refused')
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise AlertRefused('github_listing_incomplete')


def _event(body: str, channel: str) -> dict[str, Any] | None:
    if EVENT_MARKER not in body:
        return None
    try:
        match = re.search(re.escape(EVENT_MARKER) + r'\n```json\n([^`]+)\n```', body)
        evidence = json.loads(match[1]) if match else None
        validate_evidence(evidence, channel)
        return evidence
    except Exception:
        raise AlertRefused('owned_issue_evidence_refused') from None


def _newer(api: Callable[..., Any], left: Candidate, right: Candidate) -> bool:
    """Whether left is strictly after right on main, including build reruns."""
    if left.sha == right.sha:
        return (left.run_id, left.run_attempt) > (right.run_id, right.run_attempt)
    compare = api('GET', f'repos/{REPOSITORY}/compare/{right.sha}...{left.sha}')
    status = compare.get('status') if isinstance(compare, dict) else None
    if status not in {'ahead', 'behind'}:
        raise AlertRefused('candidate_order_refused')
    return status == 'ahead'


def _newer_completed_verdict(api: Callable[..., Any], candidate: Candidate, channel: str, run_id: int,
                             created_at: str, receipt_fingerprint: str) -> bool:
    # A green verdict with no open bug still has a durable workflow receipt.
    # Consult it so an older delayed red cannot open an already-recovered bug.
    if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', created_at) is None:
        raise AlertRefused('source_run_time_refused')
    created = quote('>=' + created_at, safe='')
    pattern = re.compile(r'channel-bug/(dev|test)/(passed|failed)/([0-9a-f]{40})/'
                         r'([1-9][0-9]*)/([1-9][0-9]*)/([0-9a-f]{64})')
    for page in range(1, MAX_PAGES + 1):
        result = api('GET', f'repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/runs'
                           f'?branch=main&event=workflow_dispatch&status=success&created={created}&per_page=100&page={page}')
        if not isinstance(result, dict) or not isinstance(result.get('workflow_runs'), list):
            raise AlertRefused('workflow_listing_refused')
        rows = result['workflow_runs']
        for row in rows:
            match = pattern.fullmatch(row.get('display_title', ''))
            if (row.get('id') == run_id or row.get('conclusion') != 'success'
                or row.get('head_branch') != 'main' or row.get('event') != 'workflow_dispatch'
                or row.get('path') != f'.github/workflows/{WORKFLOW}' or not match or match[1] != channel):
                continue
            other = Candidate(match[3], candidate.digest, int(match[4]), int(match[5]), candidate.artifact_id)
            if (other.sha, other.run_id, other.run_attempt) == (candidate.sha, candidate.run_id, candidate.run_attempt):
                if match[6] != receipt_fingerprint:
                    raise AlertRefused('conflicting_terminal_verdict')
                continue
            if _newer(api, other, candidate):
                return True
        if len(rows) < 100:
            return False
    raise AlertRefused('workflow_listing_incomplete')


def _evidence_body(evidence: dict[str, Any], run_url: str) -> str:
    candidate = Candidate(**evidence['candidate'])
    previous = evidence['last_good_sha']
    commit_range = f'{previous}...{candidate.sha}' if previous else f'unknown...{candidate.sha} (no prior green recorded)'
    return (f"Channel `{evidence['channel']}` is **{evidence['verdict']}** at `{candidate.sha}`.\n\n"
            f'Commit range since last green: `{commit_range}`.\n\n'
            f"Gate: `{evidence['gate']}`. Native receipt: `{candidate.operation_id(evidence['channel'])}`.\n\n"
            f'Controller verdict receipt: {run_url}\n\n{EVENT_MARKER}\n```json\n'
            + json.dumps(evidence, sort_keys=True, indent=2) + '\n```\n')


def _issue_body(evidence: dict[str, Any], run_url: str) -> str:
    return f"""<!-- postmerge-channel-bug:v1:{evidence['channel']} -->
## Context

{_evidence_body(evidence, run_url)}
Later red candidates comment here; a later green candidate closes this rolling channel bug.

## Scope

Diagnose and repair the failing native gate from its exact candidate receipt. Classify the affected subsystem and add a reproducing test before implementation.

## Source Anchors

- `scripts/postmerge_dev_test.py`
- `docs/adr/ADR-0068-continuous-dev-delivery-flow.md :: Decision`

## SBS Impact

Builder System / CES boundary for failure routing; the repair's subsystem depends on the native failure receipt.

## Constraints

- Do not pause or revert main merges or roll back dev/test. Repair rolls forward through a later candidate.
- Host changes retain their existing explicit operator authority.

## Acceptance Criteria

- [ ] The channel has a later green native verdict containing the repair. Verify: runtime receipt: postmerge-channel-verdict.v1

## Out of Scope

- Changing merge gates, production promotion or controller credential scopes.

## Suggested Validation

- Reproduce the exact failing gate and verify a later green candidate on this channel.

## Source Docs

- `docs/adr/ADR-0068-continuous-dev-delivery-flow.md`

## Applies learning (optional)

"""


def reconcile(evidence: dict[str, Any], *, channel: str, event: str, ref: str, repository: str,
              run_id: int, api: Callable[..., Any] = _api) -> str:
    if event != 'workflow_dispatch' or ref != 'refs/heads/main' or repository != REPOSITORY or run_id < 1:
        raise AlertRefused('workflow_authority_refused')
    candidate = validate_evidence(evidence, channel)
    # Source run metadata changes on rerun. Authenticate the recorded image
    # job's exact attempt; unrelated failed jobs may have been rerun later.
    attempt_path = f'repos/{REPOSITORY}/actions/runs/{candidate.run_id}/attempts/{candidate.run_attempt}'
    run = api('GET', attempt_path)
    if (not isinstance(run, dict) or type(run.get('id')) is not int or run['id'] != candidate.run_id
        or type(run.get('run_attempt')) is not int or run['run_attempt'] != candidate.run_attempt
        or run.get('event') != 'push' or run.get('status') != 'completed'
        or run.get('head_branch') != 'main' or run.get('path') != BUILD_WORKFLOW
        or run.get('repository', {}).get('full_name') != REPOSITORY
        or run.get('head_repository', {}).get('full_name') != REPOSITORY
        or run.get('head_sha') != candidate.sha):
        raise AlertRefused('candidate_build_refused')
    jobs = api('GET', attempt_path + '/jobs?per_page=100')
    if (not isinstance(jobs, dict) or not isinstance(jobs.get('jobs'), list)
        or type(jobs.get('total_count')) is not int or not 0 <= jobs['total_count'] <= 100
        or jobs['total_count'] != len(jobs['jobs']) or any(not isinstance(job, dict) for job in jobs['jobs'])):
        raise AlertRefused('candidate_build_refused')
    image_jobs = [job for job in jobs['jobs'] if job.get('name') == BUILD_JOB]
    if (len(image_jobs) != 1
        or any(type(image_jobs[0].get(key)) is not int for key in ('run_id', 'run_attempt'))
        or any(image_jobs[0].get(key) != value for key, value in {
        'run_id': candidate.run_id, 'run_attempt': candidate.run_attempt, 'head_sha': candidate.sha,
        'status': 'completed', 'conclusion': 'success',
    }.items())):
        raise AlertRefused('candidate_build_refused')
    for base, head in ((candidate.sha, 'main'), (evidence['last_good_sha'], candidate.sha)):
        if base is not None:
            comparison = api('GET', f'repos/{REPOSITORY}/compare/{base}...{head}')
            if not isinstance(comparison, dict) or comparison.get('status') not in {'identical', 'ahead'}:
                raise AlertRefused('candidate_ancestry_refused')
    # A later main-push build cannot predate this build's original creation.
    # Filter by that immutable time so normal polling does not scan all history.
    if _newer_completed_verdict(api, candidate, channel, run_id, run.get('created_at', ''),
                                 evidence['receipt_fingerprint']):
        return 'stale'
    marker = f'<!-- postmerge-channel-bug:v1:{channel} -->'
    issues = _pages(api, f'repos/{REPOSITORY}/issues?state=all&creator=github-actions%5Bbot%5D&labels=type%3Abug')
    owned = [row for row in issues if _owned(row) and 'pull_request' not in row
             and row.get('body', '').startswith(marker + '\n')]
    if len(owned) > 1:
        raise AlertRefused('channel_issue_ambiguous')
    run_url = f'https://github.com/{REPOSITORY}/actions/runs/{run_id}'
    if not owned:
        if evidence['verdict'] == 'passed':
            return 'green_without_bug'
        api('POST', f'repos/{REPOSITORY}/issues', {
            'title': f'bug: {channel} candidate is red', 'body': _issue_body(evidence, run_url),
            # This is failure intake; the exact repair must be made bounded
            # before readiness/claim, rather than guessing its owning subsystem.
            'labels': ['type:bug', 'prio:high'],
        })
        return 'opened'
    issue = owned[0]
    number = issue['number']
    if type(number) is not int or number < 1 or issue.get('state') not in {'open', 'closed'}:
        raise AlertRefused('channel_issue_refused')
    latest = _event(issue['body'], channel)
    if latest is None:
        raise AlertRefused('owned_issue_evidence_refused')
    for comment in _pages(api, f'repos/{REPOSITORY}/issues/{number}/comments?'):
        if _owned(comment):
            receipt = _event(comment.get('body', ''), channel)
            if receipt is not None:
                latest = receipt
    previous = Candidate(**latest['candidate'])
    if _newer(api, previous, candidate):
        return 'stale'
    same = asdict(previous) == asdict(candidate)
    if ((previous.sha, previous.run_id, previous.run_attempt) ==
        (candidate.sha, candidate.run_id, candidate.run_attempt) and not same):
        raise AlertRefused('conflicting_candidate_identity')
    if same and (latest['verdict'] != evidence['verdict'] or latest['receipt'] != evidence['receipt']):
        raise AlertRefused('conflicting_terminal_verdict')
    if not same:
        api('POST', f'repos/{REPOSITORY}/issues/{number}/comments', {'body': _evidence_body(evidence, run_url)})
    state = 'closed' if evidence['verdict'] == 'passed' else 'open'
    if state != issue['state']:
        data: dict[str, Any] = {'state': state, 'state_reason': 'completed' if state == 'closed' else 'reopened'}
        if state == 'closed':
            data['labels'] = [row['name'] for row in issue.get('labels', [])
                              if not row['name'].startswith(('agent:', 'action:'))]
        api('PATCH', f'repos/{REPOSITORY}/issues/{number}', data)
    return 'closed' if state == 'closed' else 'updated'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--channel', required=True)
    args = parser.parse_args()
    try:
        if len(args.evidence) > 16384:
            raise AlertRefused('channel_evidence_refused')
        result = reconcile(json.loads(args.evidence), channel=args.channel,
                           event=os.environ.get('GITHUB_EVENT_NAME', ''), ref=os.environ.get('GITHUB_REF', ''),
                           repository=os.environ.get('GITHUB_REPOSITORY', ''),
                           run_id=int(os.environ.get('GITHUB_RUN_ID', '0')))
        print(json.dumps({'channel_bug': result}))
        return 0
    except Exception:
        # Never echo untrusted API bodies, inputs, credentials or child errors.
        print(json.dumps({'channel_bug': 'refused'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
