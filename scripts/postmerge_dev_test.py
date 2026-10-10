"""Admit a published main image and use the existing native dev/test boundary.

Only public build identities and fixed terminal fields enter the output. No test
or deployment child receives the GitHub read token; remote/native recovery owns
unknown outcomes. This driver never retries or reconciles a deployment itself.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import asdict
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable
from zipfile import ZipFile

REPOSITORY = 'RasmusTho/agentic-pkm-mvp'
IMAGE_REPOSITORY = 'ghcr.io/rasmustho/pkm-app'
BUILD_WORKFLOW = '.github/workflows/app-image-build.yml'


class CandidateRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class Candidate:
    sha: str
    digest: str
    run_id: int
    run_attempt: int
    artifact_id: int


def _digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', value) is not None


def validate_source_run(run: dict[str, Any], run_id: int) -> str:
    if (run.get('id') != run_id or type(run.get('run_attempt')) is not int
        or run['run_attempt'] < 1 or run.get('event') != 'push'
        or run.get('status') != 'completed' or run.get('conclusion') != 'success'
        or run.get('head_branch') != 'main' or run.get('path') != BUILD_WORKFLOW
        or run.get('repository', {}).get('full_name') != REPOSITORY
        or run.get('head_repository', {}).get('full_name') != REPOSITORY
        or not isinstance(run.get('head_sha'), str)
        or re.fullmatch(r'[0-9a-f]{40}', run['head_sha']) is None):
        raise CandidateRefused('source_build_refused')
    return str(run['head_sha'])


def validate_artifact(run: dict[str, Any], artifact: dict[str, Any], archive: bytes) -> Candidate:
    sha = validate_source_run(run, run['id'])
    if (artifact.get('name') != 'app-image-tts-engine-proof-' + sha
        or artifact.get('expired') is not False or type(artifact.get('id')) is not int
        or not _digest(artifact.get('digest'))
        or len(archive) > 1048576
        or 'sha256:' + hashlib.sha256(archive).hexdigest() != artifact['digest']):
        raise CandidateRefused('artifact_identity_refused')
    try:
        with ZipFile(io.BytesIO(archive)) as zipped:
            members = zipped.infolist()
            if (len(members) != 1 or members[0].filename != 'app-image-tts-engine-proof.json'
                or members[0].file_size > 65536):
                raise CandidateRefused('artifact_shape_refused')
            proof = json.loads(zipped.read(members[0]))
        digest = proof['image_index_digest']
        platforms = proof['platforms']
        if (proof['contract'] != 'app-image-tts-engine-proof.v1' or proof['candidate_sha'] != sha
            or proof['image'] != IMAGE_REPOSITORY + ':' + sha or not _digest(digest)
            or proof['image_ref'] != IMAGE_REPOSITORY + '@' + digest
            or proof['probe_scope'] != 'package_presence_cli_load_import_app_health'
            or not isinstance(platforms, list) or len(platforms) != 2
            or {p['platform'] for p in platforms} != {'linux/amd64', 'linux/arm64'}
            or any(p['probe_result'] != 'pass' or not _digest(p['platform_digest']) for p in platforms)):
            raise CandidateRefused('image_proof_refused')
    except CandidateRefused:
        raise
    except Exception:
        raise CandidateRefused('image_proof_refused') from None
    return Candidate(sha, digest, run['id'], run['run_attempt'], artifact['id'])


def _github(path: str) -> bytes:
    result = subprocess.run(['gh', 'api', path], capture_output=True, timeout=60, check=False)
    if result.returncode or len(result.stdout) > 1048576:
        raise CandidateRefused('github_read_failed')
    return result.stdout


def load_candidate(run_id: int) -> Candidate:
    run = json.loads(_github(f'repos/{REPOSITORY}/actions/runs/{run_id}'))
    sha = validate_source_run(run, run_id)
    artifacts = json.loads(_github(f'repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100'))
    if artifacts['total_count'] > 100:
        raise CandidateRefused('artifact_listing_incomplete')
    matches = [a for a in artifacts['artifacts'] if a['name'] == 'app-image-tts-engine-proof-' + sha]
    if len(matches) != 1 or matches[0].get('size_in_bytes', 1048577) > 1048576:
        raise CandidateRefused('artifact_missing_or_ambiguous')
    artifact = matches[0]
    archive = _github(f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip')
    return validate_artifact(run, artifact, archive)


def _current_main() -> str:
    return str(json.loads(_github(f'repos/{REPOSITORY}/commits/main'))['sha'])


def latest_build() -> int:
    runs = json.loads(_github(
        f'repos/{REPOSITORY}/actions/workflows/app-image-build.yml/runs?branch=main&event=push&per_page=1'))
    entries = runs['workflow_runs']
    if not entries or entries[0].get('status') != 'completed' or entries[0].get('conclusion') != 'success':
        raise CandidateRefused('latest_build_not_ready')
    return int(entries[0]['id'])


def _atomic_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w') as target:
            json.dump(checkpoint, target, sort_keys=True)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def checkpoint_lock(directory: Path):
    # A single launchd controller runs this driver; this local lock also prevents
    # duplicate manual invocations. Native locks remain deployment authority.
    info = directory.lstat()
    if (not directory.is_absolute() or directory.is_symlink() or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
        raise CandidateRefused('checkpoint_directory_refused')
    descriptor = os.open(directory / 'postmerge-dev-test.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        lock_info = os.fstat(descriptor)
        if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.geteuid()
            or stat.S_IMODE(lock_info.st_mode) != 0o600 or lock_info.st_nlink != 1):
            raise CandidateRefused('checkpoint_lock_refused')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def poll(directory: Path, *, build: Callable[[], int] = latest_build,
         load: Callable[[int], Candidate] = load_candidate,
         deploy: Callable[[str, Candidate], dict[str, Any]] | None = None,
         reconcile: Callable[[str, Candidate], dict[str, Any]] | None = None,
         current_main: Callable[[], str] = _current_main) -> int:
    # No CI job runs this path. It is supervised on the existing private agent
    # host, which already owns credentials, SSH dispatch and terminal recovery.
    with checkpoint_lock(directory):
        path = directory / 'postmerge-dev-test.json'
        checkpoint = None
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            pass
        else:
            with os.fdopen(descriptor) as source:
                info = os.fstat(source.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 65536 or info.st_nlink != 1):
                    raise CandidateRefused('checkpoint_refused')
                checkpoint = json.load(source)
                _validate_checkpoint(checkpoint)
        if checkpoint and checkpoint['phase'] == 'started':
            # Read the exact pending native request under its existing lock. No
            # new activation, retry or adoption of a different request is allowed.
            candidate = Candidate(**checkpoint['candidate'])
            receipt = (reconcile or native_reconcile)(checkpoint['channel'], candidate)
            result = 'passed' if receipt['terminal_result'] == 'committed' else 'failed_or_pending'
            outcome = {**checkpoint['outcome'], 'result': result, 'operation_id': receipt['operation_id']}
            _save_outcome(path, candidate, outcome)
            checkpoint.update(phase=result, outcome=outcome)
            if result != 'passed':
                return 78
        if checkpoint and checkpoint['phase'] == 'passed' and checkpoint['channel'] == 'dev':
            candidate = Candidate(**checkpoint['candidate'])
            return deliver(candidate, deploy=deploy or native_deploy, current_main=lambda: candidate.sha,
                           emit=lambda outcome: _save_outcome(path, candidate, outcome), channels=('test',))
        run_id = build()
        candidate = load(run_id)
        if checkpoint and (checkpoint['candidate']['run_id'], checkpoint['candidate']['run_attempt']) == (
            candidate.run_id, candidate.run_attempt
        ):
            return 0
        return deliver(candidate, deploy=deploy or native_deploy, current_main=current_main,
                       emit=lambda outcome: _save_outcome(path, candidate, outcome))


def _save_outcome(path: Path, candidate: Candidate, outcome: dict[str, Any]) -> None:
    _atomic_checkpoint(path, {'candidate': asdict(candidate), 'phase': outcome['result'],
                              'channel': outcome.get('channel'), 'outcome': outcome})
    print(json.dumps(outcome, sort_keys=True))


def _validate_checkpoint(checkpoint: dict[str, Any]) -> None:
    try:
        candidate = Candidate(**checkpoint['candidate'])
        if (set(checkpoint) != {'candidate', 'phase', 'channel', 'outcome'}
            or re.fullmatch(r'[0-9a-f]{40}', candidate.sha) is None or not _digest(candidate.digest)
            or any(type(value) is not int or value < 1
                   for value in (candidate.run_id, candidate.run_attempt, candidate.artifact_id))
            or checkpoint['phase'] not in {'started', 'passed', 'failed_or_pending', 'superseded_before_deployment'}
            or checkpoint['channel'] not in {'dev', 'test', None}
            or (checkpoint['channel'] is None) != (checkpoint['phase'] == 'superseded_before_deployment')
            or any(checkpoint['outcome'].get(key) != value for key, value in {
                'source_sha': candidate.sha, 'image_digest': candidate.digest, 'source_run_id': candidate.run_id,
                'source_run_attempt': candidate.run_attempt, 'artifact_id': candidate.artifact_id,
                'result': checkpoint['phase'], 'channel': checkpoint['channel'],
            }.items())):
            raise ValueError()
    except Exception:
        raise CandidateRefused('checkpoint_refused') from None


def _native(channel: str, candidate: Candidate, *, reconcile: bool = False) -> dict[str, Any]:
    # Existing host code sanitizes SSH's environment and retains the VM worker
    # through terminal evidence. Capture all streams; never print child errors.
    environment = {k: v for k, v in os.environ.items() if k not in {'GH_TOKEN', 'GITHUB_TOKEN'}}
    command = [
        sys.executable, '-m', 'app.ops.postgres_deploy_host', channel, candidate.sha,
        '--existing-secrets-only', '--automatic', '--image-digest', candidate.digest,
    ]
    if reconcile:
        command.append('--reconcile-pending')
    result = subprocess.run(command, env=environment, capture_output=True, text=True, check=False)
    if result.returncode:
        raise CandidateRefused('native_stage_failed_or_pending')
    try:
        receipt = json.loads(result.stdout)
        if (set(receipt) != {'operation_id', 'channel', 'kind', 'stage', 'terminal_result'}
            or receipt['channel'] != channel or receipt['kind'] != 'deploy'
            or receipt['stage'] != receipt['terminal_result']
            or receipt['terminal_result'] not in ({'committed', 'failed', 'aborted'} if reconcile else {'committed'})):
            raise ValueError()
        from uuid import UUID
        if str(UUID(receipt['operation_id'])) != receipt['operation_id']:
            raise ValueError()
        return receipt
    except Exception:
        raise CandidateRefused('native_terminal_evidence_refused') from None


def native_deploy(channel: str, candidate: Candidate) -> dict[str, Any]:
    return _native(channel, candidate)


def native_reconcile(channel: str, candidate: Candidate) -> dict[str, Any]:
    return _native(channel, candidate, reconcile=True)


def deliver(candidate: Candidate, *, deploy: Callable[[str, Candidate], dict[str, Any]] = native_deploy,
            current_main: Callable[[], str] = _current_main,
            emit: Callable[[dict[str, Any]], None] = lambda result: print(json.dumps(result, sort_keys=True)),
            channels: tuple[str, ...] = ('dev', 'test')) -> int:
    if channels not in {('dev', 'test'), ('test',)}:
        raise CandidateRefused('invalid_stage_sequence')
    identity = {'source_sha': candidate.sha, 'image_digest': candidate.digest,
                'source_run_id': candidate.run_id, 'source_run_attempt': candidate.run_attempt,
                'artifact_id': candidate.artifact_id}
    # Supersede only before any mutation; never abandon a started dev/test chain.
    if current_main() != candidate.sha:
        emit({**identity, 'result': 'superseded_before_deployment'})
        return 0
    for channel in channels:
        emit({**identity, 'channel': channel, 'result': 'started'})
        try:
            receipt = deploy(channel, candidate)
            if receipt.get('terminal_result') != 'committed' or receipt.get('channel') != channel:
                raise CandidateRefused('native_terminal_evidence_refused')
        except Exception:
            emit({**identity, 'channel': channel, 'result': 'failed_or_pending',
                  'failure_reference': f'https://github.com/{REPOSITORY}/actions/runs/{candidate.run_id}'})
            return 78
        emit({**identity, 'channel': channel, 'result': 'passed', 'operation_id': receipt['operation_id']})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--source-run', type=int)
    selection.add_argument('--latest', action='store_true')
    parser.add_argument('--admit-only', action='store_true')
    parser.add_argument('--state-directory', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.latest:
            if args.state_directory is None or args.admit_only:
                raise CandidateRefused('poll_requires_private_checkpoint')
            return poll(args.state_directory)
        if args.source_run < 1:
            raise CandidateRefused('invalid_source_run')
        candidate = load_candidate(args.source_run)
        if args.admit_only:
            print(json.dumps(asdict(candidate), sort_keys=True))
            return 0
        return deliver(candidate)
    except Exception as error:
        if args.latest and isinstance(error, CandidateRefused) and str(error) == 'latest_build_not_ready':
            return 0
        reason = str(error) if isinstance(error, CandidateRefused) else 'controller_failed'
        print(json.dumps({'result': 'admission_failed', 'source_run_id': args.source_run, 'reason': reason}))
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
