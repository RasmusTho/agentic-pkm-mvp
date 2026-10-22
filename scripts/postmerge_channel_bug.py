"""Route controller terminal evidence to one Actions-owned rolling Issue per channel.

Only the reviewed main workflow invokes writes. The controller retains its
Actions read/write client; native receipts cross as bounded public evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable
from urllib.parse import quote
from zipfile import ZipFile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.postmerge_dev_test import (
    Candidate, REPOSITORY, _github, load_candidate, validate_channel_evidence, validate_source_run,
)

WORKFLOW = 'postmerge-channel-bug.yml'
BOT = 'github-actions[bot]'
EVENT_MARKER = '<!-- postmerge-channel-verdict:v1 -->'
MAX_PAGES = 10
MAX_ATTEMPTS = 100


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


def _successful_channel_attempt(api: Callable[..., Any], run: dict[str, Any]) -> bool:
    # A rerun replaces the run's latest conclusion, not its accepted history.
    # Unknown/incomplete history is never permission to create a new red Issue.
    attempt = run.get('run_attempt')
    if (type(run.get('id')) is not int or run['id'] < 1
        or type(attempt) is not int or attempt < 1
        or re.fullmatch('[0-9a-f]{40}', str(run.get('head_sha'))) is None):
        raise AlertRefused('workflow_attempt_refused')
    failures = {'failure', 'cancelled', 'timed_out', 'action_required', 'neutral', 'skipped', 'stale', 'startup_failure'}
    if run.get('status') == 'completed':
        if run.get('conclusion') == 'success':
            return True
        if run.get('conclusion') not in failures:
            raise AlertRefused('workflow_attempt_refused')
    elif run.get('status') not in {'queued', 'in_progress', 'waiting', 'requested', 'pending'}:
        raise AlertRefused('workflow_attempt_refused')
    if attempt > MAX_ATTEMPTS:
        raise AlertRefused('workflow_history_incomplete')
    for previous in range(attempt - 1, 0, -1):
        prior = api('GET', f"repos/{REPOSITORY}/actions/runs/{run['id']}/attempts/{previous}")
        if (not isinstance(prior, dict) or type(prior.get('run_attempt')) is not int
            or prior['run_attempt'] != previous or prior.get('status') != 'completed'
            or any(prior.get(key) != run[key] for key in
                   ('id', 'display_title', 'head_sha', 'head_branch', 'event', 'path'))):
            raise AlertRefused('workflow_attempt_refused')
        if prior.get('conclusion') == 'success':
            return True
        if prior.get('conclusion') not in failures:
            raise AlertRefused('workflow_attempt_refused')
    return False


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
                           f'?branch=main&event=workflow_dispatch&created={created}&per_page=100&page={page}')
        if not isinstance(result, dict) or not isinstance(result.get('workflow_runs'), list):
            raise AlertRefused('workflow_listing_refused')
        rows = result['workflow_runs']
        for row in rows:
            match = pattern.fullmatch(row.get('display_title', ''))
            if (row.get('id') == run_id or row.get('head_branch') != 'main' or row.get('event') != 'workflow_dispatch'
                or row.get('path') != f'.github/workflows/{WORKFLOW}' or not match or match[1] != channel):
                continue
            other = Candidate(match[3], candidate.digest, int(match[4]), int(match[5]), candidate.artifact_id)
            same = (other.sha, other.run_id, other.run_attempt) == (candidate.sha, candidate.run_id, candidate.run_attempt)
            if not (same or _newer(api, other, candidate)) or not _successful_channel_attempt(api, row):
                continue
            if same:
                if match[6] != receipt_fingerprint:
                    raise AlertRefused('conflicting_terminal_verdict')
                continue
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
    # Candidate.run_attempt is the admitted successful workflow attempt.
    # The trusted loader already authenticated its image job and artifact, which
    # can come from an earlier attempt after a failed-jobs-only rerun.
    run = api('GET', f'repos/{REPOSITORY}/actions/runs/{candidate.run_id}/attempts/{candidate.run_attempt}')
    try:
        if (validate_source_run(run, candidate.run_id) != candidate.sha
            or type(run.get('id')) is not int or run['run_attempt'] != candidate.run_attempt):
            raise ValueError()
    except Exception:
        raise AlertRefused('candidate_build_refused') from None
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


HOLD_MARKER = '<!-- postmerge-dev-hold:v1 -->'


def _channel_ref(api: Callable[..., Any], channel: str) -> str | None:
    rows = api('GET', f'repos/{REPOSITORY}/git/matching-refs/heads/{channel}')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise AlertRefused('channel_ref_refused')
    matches = [row for row in rows if row.get('ref') == f'refs/heads/{channel}']
    if not matches:
        return None
    if (len(matches) != 1 or matches[0].get('object', {}).get('type') != 'commit'
        or re.fullmatch('[0-9a-f]{40}', str(matches[0]['object'].get('sha'))) is None):
        raise AlertRefused('channel_ref_refused')
    return matches[0]['object']['sha']


def _dev_hold(api: Callable[..., Any], current: str | None) -> int | None:
    # The existing Issue is the documented hold, not a parallel local ledger.
    # Only the repository owner can originate one. Listing/readback failure is
    # a refusal; it must never look like an absent hold.
    owner = REPOSITORY.split('/')[0]
    rows = _pages(api, f'repos/{REPOSITORY}/issues?state=open&creator={owner}')
    holds = []
    for row in rows:
        if 'pull_request' in row or HOLD_MARKER not in (row.get('body') or ''):
            continue
        number = row.get('number')
        if type(number) is not int or number < 1:
            raise AlertRefused('dev_hold_refused')
        issue = api('GET', f'repos/{REPOSITORY}/issues/{number}')
        if issue.get('state') == 'closed':
            continue
        try:
            match = re.match(re.escape(HOLD_MARKER) + r'\n```json\n([^`]+)\n```(?:\n|$)', issue['body'])
            hold = json.loads(match[1]) if match else None
            if (issue.get('number') != number or issue.get('state') != 'open' or 'pull_request' in issue
                or issue.get('user', {}).get('login') != owner or issue.get('user', {}).get('type') != 'User'
                or issue.get('author_association') != 'OWNER' or not isinstance(hold, dict)
                or set(hold) != {'sha'} or re.fullmatch('[0-9a-f]{40}', str(hold['sha'])) is None):
                raise ValueError()
            if current is None or hold['sha'] != current:
                raise AlertRefused('dev_hold_pin_mismatch')
        except AlertRefused:
            raise
        except Exception:
            raise AlertRefused('dev_hold_refused') from None
        holds.append(number)
    if len(holds) > 1:
        raise AlertRefused('dev_hold_ambiguous')
    return holds[0] if holds else None


def _green_receipt(api: Callable[..., Any], archive: Callable[[str], bytes], candidate: Candidate,
                   created_at: str, *, channel: str = 'dev', newer_than: str | None = None) -> bool:
    if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', created_at) is None:
        raise AlertRefused('source_run_time_refused')
    pattern = re.compile(r'channel-bug/' + channel + r'/passed/([0-9a-f]{40})/'
                         r'([1-9][0-9]*)/([1-9][0-9]*)/([0-9a-f]{64})')
    created = quote('>=' + created_at, safe='')
    for page in range(1, MAX_PAGES + 1):
        listing = api('GET', f'repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/runs'
                            f'?branch=main&event=workflow_dispatch&created={created}&per_page=100&page={page}')
        if not isinstance(listing, dict) or not isinstance(listing.get('workflow_runs'), list):
            raise AlertRefused('workflow_listing_refused')
        rows = listing['workflow_runs']
        for row in rows:
            match = pattern.fullmatch(row.get('display_title', ''))
            if (not match or row.get('event') != 'workflow_dispatch' or row.get('head_branch') != 'main'
                or row.get('path') != f'.github/workflows/{WORKFLOW}'):
                continue
            other = Candidate(match[1], candidate.digest, int(match[2]), int(match[3]), candidate.artifact_id)
            same = (other.sha, other.run_id, other.run_attempt) == (candidate.sha, candidate.run_id, candidate.run_attempt)
            if newer_than is None and not same:
                continue
            if newer_than is not None and ((same and match[4] == newer_than)
                                          or (not same and not _newer(api, other, candidate))):
                continue
            if not _successful_channel_attempt(api, row):
                continue
            fingerprint = match[4]
            name = f'postmerge-green-{channel}-{other.run_id}-{other.run_attempt}-attempt-'
            artifacts = api('GET', f"repos/{REPOSITORY}/actions/runs/{row['id']}/artifacts?per_page=100")
            if (not isinstance(artifacts, dict) or type(artifacts.get('total_count')) is not int
                or not 0 <= artifacts['total_count'] <= 100 or not isinstance(artifacts.get('artifacts'), list)
                or artifacts['total_count'] != len(artifacts['artifacts'])
                or any(not isinstance(item, dict) for item in artifacts['artifacts'])):
                raise AlertRefused('green_receipt_listing_refused')
            for artifact in artifacts['artifacts']:
                match = re.fullmatch(re.escape(name) + r'([1-9][0-9]*)', artifact.get('name', ''))
                if not match:
                    continue
                attempt = int(match[1])
                proof = api('GET', f"repos/{REPOSITORY}/actions/runs/{row['id']}/attempts/{attempt}")
                if (any(proof.get(key) != row.get(key) for key in
                        ('id', 'display_title', 'head_sha', 'head_branch', 'event', 'path'))
                    or proof.get('run_attempt') != attempt or proof.get('status') != 'completed'
                    or proof.get('conclusion') != 'success'
                    or proof.get('repository', {}).get('full_name') != REPOSITORY
                    or proof.get('head_repository', {}).get('full_name') != REPOSITORY
                    or proof.get('actor', {}).get('login') != REPOSITORY.split('/')[0]):
                    raise AlertRefused('green_receipt_attempt_refused')
                try:
                    if (artifact.get('expired') is not False or type(artifact.get('id')) is not int
                        or artifact['id'] < 1 or artifact.get('size_in_bytes', 32769) > 32768):
                        raise ValueError()
                    raw = archive(f"repos/{REPOSITORY}/actions/artifacts/{artifact['id']}/zip")
                    if len(raw) > 32768 or artifact.get('digest') != 'sha256:' + hashlib.sha256(raw).hexdigest():
                        raise ValueError()
                    with ZipFile(io.BytesIO(raw)) as zipped:
                        members = zipped.infolist()
                        if len(members) != 1 or members[0].filename != 'channel-verdict.json' or members[0].file_size > 16384:
                            raise ValueError()
                        evidence = json.loads(zipped.read(members[0]))
                    proven = validate_channel_evidence(evidence, channel)
                    if ((proven.sha, proven.run_id, proven.run_attempt) != (other.sha, other.run_id, other.run_attempt)
                        or (same and proven != candidate) or evidence['verdict'] != 'passed'
                        or evidence['receipt_fingerprint'] != fingerprint
                        or (channel == 'dev' and evidence['gate'] != 'heavy_acceptance')):
                        raise ValueError()
                except Exception:
                    raise AlertRefused('green_dev_receipt_refused') from None
                if newer_than is not None and same:
                    raise AlertRefused('conflicting_terminal_verdict')
                return True
        if len(rows) < 100:
            return False
    raise AlertRefused('workflow_listing_incomplete')


def advance_channel_ref(evidence: dict[str, Any], *, channel: str, event: str, ref: str,
                        repository: str, actor: str, run_id: int, run_attempt: int,
                        workflow_sha: str, api: Callable[..., Any] = _api,
                        archive: Callable[[str], bytes] = _github) -> dict[str, Any]:
    owner = REPOSITORY.split('/')[0]
    if (event != 'workflow_dispatch' or ref != 'refs/heads/main' or repository != REPOSITORY or actor != owner
        or type(run_id) is not int or run_id < 1 or type(run_attempt) is not int or run_attempt < 1
        or re.fullmatch('[0-9a-f]{40}', workflow_sha) is None):
        raise AlertRefused('workflow_authority_refused')
    own = api('GET', f'repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{run_attempt}')
    if (any(own.get(key) != value for key, value in {
        'id': run_id, 'run_attempt': run_attempt, 'head_sha': workflow_sha, 'head_branch': 'main',
        'event': 'workflow_dispatch', 'path': f'.github/workflows/{WORKFLOW}',
    }.items()) or own.get('repository', {}).get('full_name') != REPOSITORY
        or own.get('head_repository', {}).get('full_name') != REPOSITORY
        or own.get('actor', {}).get('login') != owner):
        raise AlertRefused('workflow_authority_refused')
    candidate = validate_evidence(evidence, channel)
    for base in (workflow_sha, candidate.sha):
        comparison = api('GET', f'repos/{REPOSITORY}/compare/{base}...main')
        if not isinstance(comparison, dict) or comparison.get('status') not in {'identical', 'ahead'}:
            raise AlertRefused('candidate_ancestry_refused')
    if evidence['verdict'] != 'passed':
        return {'channel_ref': 'red', 'channel': channel}
    # Legacy native-only greens remain valid for their existing consumers. New
    # ref authority requires the current complete DEV verdict, including heavy.
    if channel == 'dev' and evidence['gate'] != 'heavy_acceptance':
        raise AlertRefused('dev_heavy_receipt_missing')

    def read(path: str) -> bytes:
        return archive(path) if path.endswith('/zip') else json.dumps(api('GET', path)).encode()

    try:
        admitted = load_candidate(candidate.run_id, run_attempt=candidate.run_attempt, read=read)
        if admitted != candidate:
            raise ValueError()
    except Exception:
        raise AlertRefused('candidate_image_refused') from None
    run = api('GET', f'repos/{REPOSITORY}/actions/runs/{candidate.run_id}/attempts/{candidate.run_attempt}')
    if _green_receipt(api, archive, candidate, run.get('created_at', ''), channel=channel,
                      newer_than=evidence['receipt_fingerprint']):
        return {'channel_ref': 'stale', 'channel': channel}
    if channel == 'test' and not _green_receipt(api, archive, candidate, run.get('created_at', '')):
        raise AlertRefused('dev_green_receipt_missing')
    current = _channel_ref(api, channel)
    if channel == 'dev':
        hold = _dev_hold(api, current)
        if hold is not None:
            if _channel_ref(api, channel) != current:
                raise AlertRefused('channel_ref_readback_refused')
            return {'channel_ref': 'held', 'channel': channel, 'sha': current,
                    'hold_issue': f'https://github.com/{REPOSITORY}/issues/{hold}'}
    if current == candidate.sha:
        if _channel_ref(api, channel) != current:
            raise AlertRefused('channel_ref_readback_refused')
        return {'channel_ref': 'unchanged', 'channel': channel, 'sha': current}
    if current is not None:
        comparison = api('GET', f'repos/{REPOSITORY}/compare/{current}...{candidate.sha}')
        if not isinstance(comparison, dict) or comparison.get('status') != 'ahead':
            raise AlertRefused('channel_ref_not_fast_forward')
        api('PATCH', f'repos/{REPOSITORY}/git/refs/heads/{channel}', {'sha': candidate.sha, 'force': False})
    else:
        api('POST', f'repos/{REPOSITORY}/git/refs', {'ref': f'refs/heads/{channel}', 'sha': candidate.sha})
    if _channel_ref(api, channel) != candidate.sha:
        raise AlertRefused('channel_ref_readback_refused')
    return {'channel_ref': 'advanced', 'channel': channel, 'sha': candidate.sha}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--channel', required=True)
    parser.add_argument('--advance-ref', action='store_true')
    parser.add_argument('--receipt-file', type=Path)
    args = parser.parse_args()
    try:
        if len(args.evidence) > 16384:
            raise AlertRefused('channel_evidence_refused')
        evidence = json.loads(args.evidence)
        options = {'channel': args.channel, 'event': os.environ.get('GITHUB_EVENT_NAME', ''),
                   'ref': os.environ.get('GITHUB_REF', ''), 'repository': os.environ.get('GITHUB_REPOSITORY', ''),
                   'run_id': int(os.environ.get('GITHUB_RUN_ID', '0'))}
        if args.advance_ref:
            result = advance_channel_ref(evidence, **options, actor=os.environ.get('GITHUB_ACTOR', ''),
                                        run_attempt=int(os.environ.get('GITHUB_RUN_ATTEMPT', '0')),
                                        workflow_sha=os.environ.get('GITHUB_SHA', ''), api=_api, archive=_github)
            if args.receipt_file is not None and evidence['verdict'] == 'passed':
                args.receipt_file.write_text(json.dumps(evidence, sort_keys=True) + '\n')
        else:
            if args.receipt_file is not None:
                raise AlertRefused('receipt_requires_ref_consumer')
            result = {'channel_bug': reconcile(evidence, **options, api=_api)}
        print(json.dumps(result))
        return 0
    except Exception as error:
        # Never echo untrusted API bodies, inputs, credentials or child errors.
        key = 'channel_ref' if args.advance_ref else 'channel_bug'
        reason = str(error) if isinstance(error, AlertRefused) else 'consumer_failed'
        print(json.dumps({key: 'refused', 'reason': reason}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
