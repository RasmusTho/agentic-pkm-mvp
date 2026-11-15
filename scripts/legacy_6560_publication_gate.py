"""Read-only proof immediately before an authorized #6560 PR effect.

This does not execute publication, lock Codex, or authorize raw Git commands.
The operator must hold the coordinated no-manual-starts/config-quiescence
conditions through proof and the subsequent effect.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
import sys
import time
from typing import Any

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.builderops import legacy_codex_6560_guard as guard
from app.builderops import legacy_git_config, legacy_owner_recovery as recovery
from app.builderops import openhands_pr_cycle as cycle
from scripts import agent_worktree


class PublicationProofError(ValueError):
    """The scoped current publication proof is absent, stale or ambiguous."""


def _read_prior_body(*, path: Path, digest: str, worktree: Path, reviewed_at: str) -> str:
    """Read the operator's existing reviewed body file, not a GitHub-derived copy."""
    from app.builderops.legacy_patch_backup import read_patch_backup
    if (not path.is_absolute() or path != path.resolve() or path == worktree or worktree in path.parents
            or not re.fullmatch(r'[0-9a-f]{64}', digest)):
        raise PublicationProofError('prior body intent file is unsupported')
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_size > 65536:
        raise PublicationProofError('prior body intent file is unsupported')
    raw = read_patch_backup(path, digest, max_bytes=65536)
    after = path.stat(follow_symlinks=False)
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or hashlib.sha256(raw).hexdigest() != digest
            or max(after.st_mtime, after.st_ctime) + 1 > recovery._timestamp(reviewed_at)):
        raise PublicationProofError('body file was not established before the authenticated intent comment')
    return raw.decode('utf-8')


def _json_no_duplicates(data: str) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate observation field')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def _body_intent(*, cwd: Path, worktree: Path, comment_id: int, body_file: Path,
                 branch: str, session: str, agent: str, lease: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read an existing account-authenticated, attempt-specific body intent.

    This proves what the account attested, not when a PATCH ran. The operator
    must independently establish that this comment preceded the exact attempt.
    """
    if type(comment_id) is not int or comment_id < 1:
        raise PublicationProofError('authenticated body intent is unavailable')
    comment = agent_worktree._read_github_transfer_comment(comment_id, cwd=cwd)
    allowed = {f'https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/{n}' for n in (6560, guard.PR)}
    if (comment.get('id') != comment_id or comment.get('issue_url') not in allowed
            or comment.get('author_association') not in {'OWNER', 'MEMBER', 'COLLABORATOR'}
            or not isinstance(comment.get('user'), dict) or comment['user'].get('login') != 'RasmusTho'
            or not isinstance(comment.get('created_at'), str) or comment.get('updated_at') != comment['created_at']
            or not isinstance(comment.get('body'), str) or len(comment['body'].encode()) > 65536):
        raise PublicationProofError('body intent comment is edited, foreign or unavailable')
    root = _json_no_duplicates(comment['body'])
    value = root.get('operator_publication_intent.v1') if isinstance(root, dict) else None
    fields = {'issue', 'pr', 'repository', 'branch', 'session', 'agent', 'lease_id', 'head',
              'before_body_sha256', 'body_sha256', 'body', 'attempt_id', 'reviewed'}
    if (not isinstance(root, dict) or set(root) != {'operator_publication_intent.v1'}
            or not isinstance(value, dict) or set(value) != fields or value.get('issue') != 6560
            or value.get('pr') != guard.PR or value.get('repository') != 'RasmusTho/agentic-pkm-mvp'
            or value.get('branch') != branch or value.get('session') != session or value.get('agent') != agent
            or value.get('lease_id') != lease or value.get('reviewed') is not True
            or not isinstance(value.get('head'), str) or not re.fullmatch(r'[0-9a-f]{40}', value['head'])
            or not isinstance(value.get('attempt_id'), str) or not re.fullmatch(r'[0-9a-f]{32}', value['attempt_id'])
            or not isinstance(value.get('body_sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', value['body_sha256'])
            or not isinstance(value.get('before_body_sha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', value['before_body_sha256'])
            or not isinstance(value.get('body'), str)
            or re.findall(r'<!--\s*operator-publication-attempt:.*?-->', value['body'], re.S)
                != [f"<!-- operator-publication-attempt:{value['attempt_id']} -->"]
            or recovery._timestamp(comment['created_at']) > time.time()):
        raise PublicationProofError('exact body intent comment is missing or mismatched')
    body = _read_prior_body(path=body_file, digest=value['body_sha256'], worktree=worktree,
                            reviewed_at=comment['created_at'])
    if body != value['body'] or hashlib.sha256(body.encode()).hexdigest() != value['body_sha256']:
        raise PublicationProofError('body intent bytes differ from the authenticated comment')
    # A duplicate attempt ID is ambiguous, even if its claimed body is equal.
    matches = []
    for item in recovery._operator_comments(cwd=cwd, issue=6560, pr=guard.PR):
        if not isinstance(item, dict) or not isinstance(item.get('body'), str):
            continue
        try:
            parsed = _json_no_duplicates(item['body'])
        except (ValueError, TypeError):
            continue
        candidate = parsed.get('operator_publication_intent.v1') if isinstance(parsed, dict) else None
        if isinstance(candidate, dict) and candidate.get('attempt_id') == value['attempt_id']:
            matches.append(item)
    if len(matches) != 1 or matches[0] != comment:
        raise PublicationProofError('body attempt comment is missing or ambiguous')
    return value, comment


def _pr_binding(*, cwd: Path) -> dict[str, Any]:
    try:
        raw = json.loads(recovery._github_read([f'repos/RasmusTho/agentic-pkm-mvp/pulls/{guard.PR}'], cwd=cwd))
        head, base = raw['head'], raw['base']
        value = {'number': raw['number'], 'state': raw['state'], 'draft': raw.get('draft'), 'body': raw['body'], 'updated_at': raw['updated_at'],
                 'head_sha': head['sha'], 'head_ref': head['ref'], 'head_repo': head['repo']['full_name'],
                 'base_sha': base['sha'], 'base_ref': base['ref'], 'base_repo': base['repo']['full_name']}
        if (value['number'] != guard.PR or value['state'] != 'open' or value['draft'] is not False
                or not all(isinstance(value[key], str) and value[key] for key in value if key not in {'number', 'draft'})
                or not re.fullmatch(r'[0-9a-f]{40,64}', value['base_sha'])):
            raise ValueError('invalid PR binding')
        return value
    except (KeyError, TypeError, ValueError, recovery.RecoveryEvidenceError) as exc:
        raise PublicationProofError('complete PR binding is unavailable') from exc


def check(*, cwd: Path, worktree: Path, session: str, agent: str, head: str,
          expected_remote_head: str, effect: str, just_pushed_from: str | None = None,
          prior_body_file: Path | None = None, prior_intent_comment_id: int | None = None,
          next_body_file: Path | None = None, next_intent_comment_id: int | None = None,
          first_commit_index: Path | None = None) -> dict[str, Any]:
    """Bind current candidate, operator pin, dispatcher claim and exact PR."""
    try:
        first_commit = effect in {'first-commit-stage', 'first-commit-commit'}
        if (effect not in {'push', 'patch', 'verify', 'first-commit-stage', 'first-commit-commit'}
                or str(worktree) != guard.WORKTREE
                or not session or session != os.environ.get("CODEX_SESSION_ID") or not agent
                or not re.fullmatch(r"[0-9a-f]{40}", head)
                or not re.fullmatch(r"[0-9a-f]{40}", expected_remote_head)
                or (effect == 'first-commit-commit' and not isinstance(first_commit_index, Path))
                or (effect != 'first-commit-commit' and first_commit_index is not None)
                or (first_commit and any(value is not None for value in
                    (just_pushed_from, prior_body_file, prior_intent_comment_id,
                     next_body_file, next_intent_comment_id)))):
            raise PublicationProofError('publication target or head is outside #6560 scope')
        legacy_git_config.check_host_config()
        legacy_git_config.check(cwd=cwd, worktree=worktree)
        recovery._verify_current_issue(cwd=cwd, issue=6560, worktree=worktree)
        dispatcher_identity = recovery._dispatcher_db_identity(recovery._operator_dispatcher_paths(cwd=cwd).db_path)
        actual, branch = agent_worktree._worktree_identity(cwd, worktree)
        if actual != worktree or recovery._git_read(worktree, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip() != head:
            raise PublicationProofError('local publication HEAD changed')
        registry = agent_worktree._default_registry_path(cwd)
        records = recovery._locked_raw_branch_snapshot(registry, branch=branch, worktree=worktree, allow_prepared=True)
        record = records.get(str(worktree))
        if (not isinstance(record, dict) or record.get('owner') != session or record.get('status') != 'active'
                or record.get('branch') != branch or record.get('generation') != guard.GENERATION
                or record.get('expires_at', 0) <= time.time()
                or agent_worktree._worktree_generation(cwd, worktree, create=False) != guard.GENERATION):
            raise PublicationProofError('current registration is stale or mismatched')
        agent_worktree.assert_operator_registration_pinned(record)
        proof = record['operator_registration']
        if proof.get('issue') != 6560:
            raise PublicationProofError('operator pin is not scoped to #6560')
        comments = [agent_worktree._read_github_transfer_comment(proof[key], cwd=cwd)
                    for key in ('pending_comment_id', 'ack_comment_id')]
        parsed = []
        for comment, key in zip(comments, ('pending_digest', 'ack_digest')):
            receipt, _, digest = agent_worktree._transfer_comment(comment, issue=6560, pr=guard.PR,
                                                                  receipt_key='operator_reconciliation.v1')
            if digest != proof[key]:
                raise PublicationProofError('operator comment changed')
            values = {name: receipt[name] for name in ('successor', 'predecessor', 'registration', 'candidate', 'writer', 'publication')}
            recovery.validate_operator_reconciliation(comment, issue=6560, pr=guard.PR, github_login='RasmusTho', **values)
            parsed.append(receipt)
        pending, acknowledged = parsed
        ack = acknowledged.get('successor_acknowledgment')
        candidate = proof['candidate_readback']
        expected_registration = {'path': str(worktree), 'branch': branch, 'owner': session,
                                 'generation': guard.GENERATION, 'epoch': proof['epoch'],
                                 'observed_at': proof['registration_read_at']}
        if (pending != {k: v for k, v in acknowledged.items() if k != 'successor_acknowledgment'}
                or not isinstance(ack, dict) or ack.get('successor_registration') != expected_registration
                or ack.get('candidate_readback') != candidate
                or ack.get('ack_attempt_id') != proof['ack_intent']['attempt_id']
                or pending.get('successor') != {'agent': agent, 'session': session}
                or proof.get('predecessor') != pending.get('predecessor_registration')
                or not agent_worktree._valid_dirty_material(candidate.get('dirty_material'))
                or candidate['dirty_material']['tree'] != pending['candidate']['tree']
                or any(candidate['dirty_material'][key] != pending['dirty_candidate'][key]
                       for key in ('index_blobs', 'file_sha256', 'patch_sha256', 'backup'))):
            raise PublicationProofError('pinned dirty material or ACK changed')
        predecessor = pending['predecessor']
        events = recovery._read_task_events(cwd=cwd, task_id=predecessor['task_id'], expected_identity=dispatcher_identity)
        claims = [event for event in events if event.get('event_type') == 'task.claimed'
                  and event.get('actor') == agent and isinstance(event.get('payload'), dict)
                  and event['payload'].get('session') == session
                  and isinstance(event['payload'].get('takeover'), dict)
                  and event['payload']['takeover'].get('previous_lease_id') == predecessor['lease_id']]
        if len(claims) != 1 or not isinstance(claims[0]['payload'].get('claim_id'), str):
            raise PublicationProofError('successor claim is ambiguous')
        lease = recovery._successor_claim_readback(cwd=cwd, task_id=predecessor['task_id'], issue=6560,
                    agent=agent, session=session, claim_id=claims[0]['payload']['claim_id'], predecessor=predecessor,
                    expected_identity=dispatcher_identity)
        guard.check(issue=6560, pr=guard.PR, worktree=worktree, session=session, receipt=pending)
        live = recovery.read_live_publication(cwd=cwd, pr=guard.PR, branch=branch)
        pr_binding = _pr_binding(cwd=cwd)
        if pr_binding['head_sha'] != live['head'] or pr_binding['head_ref'] != branch:
            raise PublicationProofError('PR identity changed during proof')
        if live['head'] != expected_remote_head:
            raise PublicationProofError('existing PR head changed')
        references = cycle.closure._closing_issue_references(
            cycle.SubprocessExecutor(timeout_seconds=30), cwd, 'RasmusTho/agentic-pkm-mvp', guard.PR)
        if references != [6560]:
            raise PublicationProofError('GitHub closing issue references changed')
        original_body = live['body_sha256'] == pending['publication']['body_sha256']
        intent_comments = []
        if first_commit and (not original_body or head != pending['candidate']['head']
                             or head != pending['publication']['head'] or live['head'] != head):
            raise PublicationProofError('first commit does not bind the original candidate and PR head')
        if effect == 'verify' and (original_body or head != live['head']):
            raise PublicationProofError('current successor body or head is not published')
        if original_body:
            if (live['head'] != pending['publication']['head']
                    and not (live['head'] == head and just_pushed_from == pending['publication']['head'])):
                raise PublicationProofError('prior push outcome is not reconciled')
            recovery._verify_pr_origin(cwd=cwd, issue=6560, pr=guard.PR, worktree=worktree,
                    candidate=pending['candidate'], predecessor=predecessor,
                    publication={**live, 'head': pending['publication']['head']})
        else:
            if not isinstance(prior_body_file, Path) or type(prior_intent_comment_id) is not int:
                raise PublicationProofError('previous body intent or attempted effect is unknown')
            prior, prior_comment = _body_intent(cwd=cwd, worktree=worktree, comment_id=prior_intent_comment_id,
                    body_file=prior_body_file, branch=branch, session=session, agent=agent, lease=lease)
            intent_comments.append((prior_intent_comment_id, prior_comment, prior_body_file))
            if prior['body_sha256'] != live['body_sha256'] or prior['body'] != pr_binding['body']:
                raise PublicationProofError('current body differs from the earlier reviewed intent')
            recovery._git_read(worktree, '--no-replace-objects', 'merge-base', '--is-ancestor',
                               prior['head'], live['head'])
            cycle._verify_dirty_first_patch(cwd=cwd, worktree=worktree, candidate=candidate, head=prior['head'])
            current_pr = json.loads(recovery._github_read([f'repos/RasmusTho/agentic-pkm-mvp/pulls/{guard.PR}'], cwd=cwd))
            body = current_pr.get('body') if isinstance(current_pr, dict) else None
            from scripts.pr_body_generator import resolve_native_issue_authority
            authority = resolve_native_issue_authority(body) if isinstance(body, str) else None
            if (body != prior['body'] or authority is None or authority.governing_issue != 6560 or list(authority.closing_issues) != [6560]
                    or hashlib.sha256(body.encode()).hexdigest() != live['body_sha256']):
                raise PublicationProofError('current successor PR body is unavailable or changed')
            origin, _ = cycle._pickup_origin(body, issue=6560, closing=[6560], branch=branch, comments=[])
            if (origin.get('mode') != 'dispatcher-backed' or origin.get('path') != str(worktree)
                    or origin.get('agent') != agent or origin.get('lease_id') != lease):
                raise PublicationProofError('current PR body is not bound to the successor')
        if effect == 'patch':
            if (head != live['head'] or not isinstance(next_body_file, Path)
                    or type(next_intent_comment_id) is not int):
                raise PublicationProofError('new PATCH body intent or current head is unavailable')
            intended, next_comment = _body_intent(cwd=cwd, worktree=worktree, comment_id=next_intent_comment_id,
                    body_file=next_body_file, branch=branch, session=session, agent=agent, lease=lease)
            intent_comments.append((next_intent_comment_id, next_comment, next_body_file))
            if (intended['head'] != live['head'] or intended['before_body_sha256'] != live['body_sha256']
                    or intended['body_sha256'] == live['body_sha256']):
                raise PublicationProofError('new PATCH intent does not bind the current PR state')
            from scripts.pr_body_generator import resolve_native_issue_authority
            intended_authority = resolve_native_issue_authority(intended['body'])
            if (intended_authority is None or intended_authority.governing_issue != 6560
                    or list(intended_authority.closing_issues) != [6560]):
                raise PublicationProofError('new PATCH body issue scope differs')
            origin, _ = cycle._pickup_origin(intended['body'], issue=6560, closing=[6560], branch=branch, comments=[])
            if (origin.get('mode') != 'dispatcher-backed' or origin.get('path') != str(worktree)
                    or origin.get('agent') != agent or origin.get('lease_id') != lease):
                raise PublicationProofError('new PATCH body is not bound to the successor')
        if not first_commit:
            recovery._git_read(worktree, '--no-replace-objects', 'merge-base', '--is-ancestor',
                               pending['publication']['head'], candidate['head'])
            recovery._git_read(worktree, '--no-replace-objects', 'merge-base', '--is-ancestor', live['head'], head)
            if live['head'] != pending['publication']['head']:
                cycle._verify_dirty_first_patch(cwd=cwd, worktree=worktree, candidate=candidate, head=live['head'])
            cycle._verify_dirty_first_patch(cwd=cwd, worktree=worktree, candidate=candidate, head=head)
        unique_ack = recovery._read_unique_operator_ack(cwd=cwd, issue=6560, pr=guard.PR,
                                                        pending=pending, expected_ack=ack)
        _, ack_at, ack_digest = agent_worktree._transfer_comment(
            unique_ack, issue=6560, pr=guard.PR, receipt_key='operator_reconciliation.v1')
        if (any(unique_ack.get(key) != comments[1].get(key) for key in ('id', 'body', 'created_at', 'updated_at'))
                or unique_ack.get('id') != proof['ack_comment_id'] or ack_at != proof['ack_at']
                or ack_digest != proof['ack_digest']):
            raise PublicationProofError('pinned acknowledgment changed or is ambiguous')
        for intent_id, earlier_comment, body_file in intent_comments:
            _, fresh_comment = _body_intent(cwd=cwd, worktree=worktree, comment_id=intent_id,
                    body_file=body_file, branch=branch, session=session, agent=agent, lease=lease)
            if (fresh_comment != earlier_comment
                    or recovery._timestamp(fresh_comment['created_at']) < ack_at):
                raise PublicationProofError('body intent changed or predates the pinned acknowledgment')
        if recovery._git_read(worktree, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip() != head:
            raise PublicationProofError('local publication HEAD changed during proof')
        recovery._verify_current_issue(cwd=cwd, issue=6560, worktree=worktree)
        if recovery.read_live_publication(cwd=cwd, pr=guard.PR, branch=branch) != live or _pr_binding(cwd=cwd) != pr_binding:
            raise PublicationProofError('PR state, base, head, ref or body changed during proof')
        if cycle.closure._closing_issue_references(
                cycle.SubprocessExecutor(timeout_seconds=30), cwd, 'RasmusTho/agentic-pkm-mvp', guard.PR) != references:
            raise PublicationProofError('GitHub closing issue references changed during proof')
        final_records = recovery._locked_raw_branch_snapshot(registry, branch=branch, worktree=worktree, allow_prepared=True)
        final_record = final_records.get(str(worktree))
        if (final_records != records or not isinstance(final_record, dict)
                or final_record.get('status') != 'active' or final_record.get('owner') != session
                or final_record.get('registration_epoch') != proof['epoch']
                or final_record.get('expires_at', 0) <= time.time()):
            raise PublicationProofError('registration changed or expired during proof')
        agent_worktree.assert_operator_registration_pinned(final_record)
        if recovery._dispatcher_db_identity(recovery._operator_dispatcher_paths(cwd=cwd).db_path) != dispatcher_identity:
            raise PublicationProofError('dispatcher identity changed during proof')
        final_lease = recovery._successor_claim_readback(cwd=cwd, task_id=predecessor['task_id'], issue=6560,
                      agent=agent, session=session, claim_id=claims[0]['payload']['claim_id'], predecessor=predecessor,
                      expected_identity=dispatcher_identity)
        if final_lease != lease:
            raise PublicationProofError('successor claim changed during proof')
        # Dispatcher reads can block; re-enter the inode-bound registry lock
        # afterwards rather than trusting the row captured before that read.
        post_claim_records = recovery._locked_raw_branch_snapshot(
            registry, branch=branch, worktree=worktree, allow_prepared=True)
        post_claim_record = post_claim_records.get(str(worktree))
        if (post_claim_records != records or not isinstance(post_claim_record, dict)
                or post_claim_record.get('status') != 'active' or post_claim_record.get('owner') != session
                or post_claim_record.get('registration_epoch') != proof['epoch']
                or post_claim_record.get('expires_at', 0) <= time.time()):
            raise PublicationProofError('registration changed or expired during final claim read')
        agent_worktree.assert_operator_registration_pinned(post_claim_record)
        index_digest = None
        if first_commit:
            from app.builderops.legacy_patch_tree import verify_first_patch_index
            from app.builderops.legacy_selected_files import read_selected

            guard.check(issue=6560, pr=guard.PR, worktree=worktree, session=session, receipt=pending)
            if recovery._read_operator_candidate(cwd=cwd, worktree=worktree, receipt=pending) != pending['candidate']:
                raise PublicationProofError('original candidate or dirty material changed before first commit')
            if first_commit_index is not None:
                material = candidate['dirty_material']
                selected = read_selected(worktree, material['file_sha256'])
                ordinary_index = Path(recovery._git_read(worktree, 'rev-parse', '--path-format=absolute',
                                                         '--git-path', 'index').decode().strip())
                index_digest = verify_first_patch_index(worktree=worktree, index=first_commit_index,
                    ordinary_index=ordinary_index, parent=head, selected=selected,
                    baseline_oids=material['index_blobs'])
            if (recovery._git_read(worktree, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip() != head
                    or recovery.read_live_publication(cwd=cwd, pr=guard.PR, branch=branch) != live
                    or _pr_binding(cwd=cwd) != pr_binding):
                raise PublicationProofError('candidate or PR changed before first commit')
            late_pending = agent_worktree._read_github_transfer_comment(proof['pending_comment_id'], cwd=cwd)
            late_receipt, _, late_pending_digest = agent_worktree._transfer_comment(
                late_pending, issue=6560, pr=guard.PR, receipt_key='operator_reconciliation.v1')
            if (late_receipt != pending or late_pending_digest != proof['pending_digest']
                    or any(late_pending.get(key) != comments[0].get(key)
                           for key in ('id', 'body', 'created_at', 'updated_at'))):
                raise PublicationProofError('pinned pending comment changed before first commit')
            late_ack = recovery._read_unique_operator_ack(cwd=cwd, issue=6560, pr=guard.PR,
                                                          pending=pending, expected_ack=ack)
            _, late_ack_at, late_ack_digest = agent_worktree._transfer_comment(
                late_ack, issue=6560, pr=guard.PR, receipt_key='operator_reconciliation.v1')
            if (late_ack_at != proof['ack_at'] or late_ack_digest != proof['ack_digest']
                    or any(late_ack.get(key) != comments[1].get(key)
                           for key in ('id', 'body', 'created_at', 'updated_at'))):
                raise PublicationProofError('pinned ACK changed before first commit')
            recovery._verify_current_issue(cwd=cwd, issue=6560, worktree=worktree)
            if recovery._successor_claim_readback(cwd=cwd, task_id=predecessor['task_id'], issue=6560,
                    agent=agent, session=session, claim_id=claims[0]['payload']['claim_id'],
                    predecessor=predecessor, expected_identity=dispatcher_identity) != lease:
                raise PublicationProofError('successor claim changed before first commit')
            final_rows = recovery._locked_raw_branch_snapshot(registry, branch=branch, worktree=worktree,
                                                                allow_prepared=True)
            if final_rows != records or final_rows[str(worktree)].get('expires_at', 0) <= time.time():
                raise PublicationProofError('registration changed before first commit')
        return {'issue': 6560, 'pr': guard.PR, 'branch': branch, 'head': head, 'effect': effect,
                'remote_head': expected_remote_head, 'epoch': proof['epoch'], 'lease_id': lease,
                'first_commit_index_sha256': index_digest,
                'attempt_source': 'operator must establish separately'}
    except PublicationProofError:
        raise
    except (guard.CodexGuardError, legacy_git_config.ConfigError, recovery.RecoveryEvidenceError,
            agent_worktree.WorktreeLifecycleError, cycle.CycleError, cycle.closure.ClosureError,
            KeyError, TypeError, OSError, ValueError) as exc:
        raise PublicationProofError('scoped publication proof unavailable or changed') from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worktree', type=Path, required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--agent', required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--expected-remote-head', required=True)
    parser.add_argument('--effect', choices=('push', 'patch', 'verify', 'first-commit-stage',
                                             'first-commit-commit'), required=True)
    parser.add_argument('--first-commit-index', type=Path, help='separately prepared #6560 index')
    parser.add_argument('--just-pushed-from', help='previous exact PR head after an immediately verified push')
    parser.add_argument('--prior-body-file', type=Path, help='existing reviewed body file from before the update')
    parser.add_argument('--prior-intent-comment-id', type=int, help='authenticated intent comment for the current successor body')
    parser.add_argument('--next-body-file', type=Path, help='new reviewed body bytes for the specific PATCH')
    parser.add_argument('--next-intent-comment-id', type=int, help='authenticated intent comment for the specific PATCH')
    args = parser.parse_args()
    try:
        proof = check(cwd=args.worktree, worktree=args.worktree, session=args.session, agent=args.agent,
                      head=args.head, expected_remote_head=args.expected_remote_head, effect=args.effect,
                      just_pushed_from=args.just_pushed_from, prior_body_file=args.prior_body_file,
                      prior_intent_comment_id=args.prior_intent_comment_id, next_body_file=args.next_body_file,
                      next_intent_comment_id=args.next_intent_comment_id, first_commit_index=args.first_commit_index)
    except PublicationProofError as exc:
        print(f'publication proof refused: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(proof, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
