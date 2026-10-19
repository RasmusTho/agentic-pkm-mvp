"""Isolated controller startup with a stdlib-only failure reporter."""
from __future__ import annotations

import argparse
import base64
import csv
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any

REPOSITORY = 'RasmusTho/agentic-pkm-mvp'
ROOT = Path(__file__).resolve().parents[1]


class CandidateRefused(RuntimeError):
    pass


@contextmanager
def checkpoint_lock(directory: Path, *, existing_only: bool = False):
    # A single launchd controller runs this driver; this local lock also prevents
    # duplicate manual invocations. Native locks remain deployment authority.
    info = directory.lstat()
    if (not directory.is_absolute() or directory.is_symlink() or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
        raise CandidateRefused('checkpoint_directory_refused')
    try:
        if existing_only:
            descriptor = os.open(directory / 'postmerge-dev-test.lock', os.O_RDWR | os.O_NOFOLLOW)
            fresh = False
        else:
            descriptor = os.open(directory / 'postmerge-dev-test.lock',
                                 os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            fresh = True
    except FileExistsError:
        descriptor = os.open(directory / 'postmerge-dev-test.lock', os.O_RDWR | os.O_NOFOLLOW)
        fresh = False
    try:
        lock_info = os.fstat(descriptor)
        if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.geteuid()
            or stat.S_IMODE(lock_info.st_mode) != 0o600 or lock_info.st_nlink != 1):
            raise CandidateRefused('checkpoint_lock_refused')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fresh
    finally:
        os.close(descriptor)


def _pause_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise CandidateRefused('pause_expiry_required')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except ValueError:
        raise CandidateRefused('pause_timestamp_refused') from None


def validate_observation(observation: Any) -> dict[str, Any]:
    if (not isinstance(observation, dict) or set(observation) != {'sequence', 'observed_at'}
        or type(observation['sequence']) is not int or not 0 < observation['sequence'] < 10**18
        or observation['observed_at'] != _pause_time(observation['observed_at']).isoformat()):
        raise CandidateRefused('heartbeat_observation_refused')
    return observation


def read_checkpoint_document(path: Path, *, allow_missing: bool = False) -> dict[str, Any] | None:
    checkpoint = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        if not allow_missing:
            raise CandidateRefused('checkpoint_missing_restore_authoritative_state') from None
    else:
        with os.fdopen(descriptor) as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 65536 or info.st_nlink != 1):
                raise CandidateRefused('checkpoint_refused')
            checkpoint = json.load(source)
            if not isinstance(checkpoint, dict):
                raise CandidateRefused('checkpoint_refused')
    return checkpoint


# These are the real poller, native child and lazy receipt-validation producers.
# Existing host operation closure, with versions owned by the existing BWS manifest.
DEPENDENCIES = ('bitwarden-sdk', 'python-dateutil', 'six')
DEPENDENCY_MODULES = {'bitwarden_sdk', 'bitwarden_py', 'dateutil', 'six'}

REQUIRED_MODULES = (
    'scripts.postmerge_dev_test', 'app.ops.postgres_deploy_host',
    'app.ops.postgres_deploy_linux', 'app.ops.heavy_acceptance',
    'app.ops.native_source_bootstrap',
)


def runtime_dependencies(requirements: Path) -> dict[str, str]:
    pins = dict(line.strip().split('==', 1) for line in requirements.read_text().splitlines()
                if '==' in line and not line.lstrip().startswith('#'))
    selected = {name: pins[name] for name in DEPENDENCIES}
    if any(re.fullmatch(r'[0-9]+(?:[.][0-9A-Za-z]+)*', version) is None for version in selected.values()):
        raise ValueError('tooling_dependency_pin_refused')
    return selected


def dependency_fingerprint(vendor: Path) -> str:
    files = {}
    if not vendor.is_dir() or vendor.is_symlink():
        raise ValueError('tooling_dependencies_refused')
    for path in sorted(vendor.rglob('*')):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError('tooling_dependencies_refused')
        if path.is_file():
            files[str(path.relative_to(vendor))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:
        raise ValueError('tooling_dependencies_refused')
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def copy_runtime_dependencies(vendor: Path) -> None:
    """Copy exact qualified installed distributions; never fetch packages or credentials."""
    vendor.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, version in runtime_dependencies(ROOT / 'requirements-bws-deploy.txt').items():
        distribution = metadata.distribution(name)
        record = distribution.read_text('RECORD')
        if distribution.version != version or not record:
            raise ValueError('tooling_dependency_version_refused')
        # Distribution.files may silently omit missing files. The wheel RECORD
        # is the producer's complete inventory, so absence is a refusal.
        for row in csv.reader(record.splitlines()):
            if len(row) != 3 or not row[0]:
                raise ValueError('tooling_dependency_file_refused')
            relative = Path(row[0])
            if relative.is_absolute() or '..' in relative.parts or relative.suffix == '.pth':
                raise ValueError('tooling_dependency_file_refused')
            if '__pycache__' in relative.parts or relative.suffix in {'.pyc', '.pyo'}:
                continue
            # Retain runtime/license/version evidence, not installer provenance
            # that may contain a credential-bearing direct URL or host detail.
            if (any(part.endswith('.dist-info') for part in relative.parts)
                and relative.name not in {'METADATA', 'WHEEL', 'RECORD', 'LICENSE', 'LICENSE.txt'}):
                continue
            source = Path(distribution.locate_file(relative))
            if source.is_symlink() or not source.is_file():
                raise ValueError('tooling_dependency_file_refused')
            data = source.read_bytes()
            if row[2] and len(data) != int(row[2]):
                raise ValueError('tooling_dependency_file_refused')
            if row[1]:
                algorithm, expected = row[1].split('=', 1)
                actual = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
                if algorithm != 'sha256' or actual != expected:
                    raise ValueError('tooling_dependency_hash_refused')
            elif relative.name != 'RECORD':
                raise ValueError('tooling_dependency_hash_refused')
            target = vendor / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != data:
                raise ValueError('tooling_dependency_collision_refused')
            target.write_bytes(data)


def self_check(sha: str) -> None:
    installation = ROOT.parent
    pin = json.loads((installation / 'pin.json').read_text())
    executable = installation / 'runtime/bin/python'
    vendor = installation / 'vendor'
    dependencies = runtime_dependencies(ROOT / 'requirements-bws-deploy.txt')
    if (re.fullmatch(r'[0-9a-f]{40}', sha) is None or installation.name != sha
        or ROOT.name != 'source' or pin != {
            'source_sha': sha, 'python_version': sys.version,
            'python_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'dependencies': dependencies, 'dependency_files_sha256': dependency_fingerprint(vendor),
        } or Path(sys.executable).absolute() != executable
        or not sys.flags.isolated or not sys.flags.no_site):
        raise ValueError('tooling_identity_refused')
    # -I -S removes cwd, PYTHONPATH, user site and .pth execution. Only the
    # independently installed reviewed snapshot is added to the import path.
    actual = {item.metadata['Name'].lower().replace('_', '-'): item.version
              for item in metadata.distributions(path=[str(vendor)])}
    if actual != dependencies:
        raise ValueError('tooling_dependency_version_refused')
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT), str(vendor)]
    os.chdir(ROOT)
    for name in REQUIRED_MODULES:
        importlib.import_module(name)
    # Existing-secrets deployment still reads BWS through this lazy factory.
    # Construction loads the real native SDK without login, Keychain or network.
    from app.ops.bws_secret_reader import _sdk_client
    _sdk_client()
    for name, module in tuple(sys.modules.items()):
        package = name.split('.')[0]
        if package not in {'app', 'scripts'} | DEPENDENCY_MODULES:
            continue
        origin = getattr(module, '__file__', None)
        expected = vendor if package in DEPENDENCY_MODULES else ROOT
        if origin is not None and not Path(origin).resolve().is_relative_to(expected):
            raise ValueError('tooling_import_refused')


def report_startup_failure(directory: Path) -> None:
    # This path must keep working even when app or the controller cannot import.
    # Snapshot only existing authority. The frontier is causal evidence, not
    # an allocated activity sequence; the time floor also preserves the status
    # pagination proof after clock correction and delayed writer admission.
    with checkpoint_lock(directory, existing_only=True):
        checkpoint = read_checkpoint_document(directory / 'postmerge-dev-test.json')
        observation = validate_observation(checkpoint['observation']) if 'observation' in checkpoint else None
        sequence = observation['sequence'] if observation else 0
        observed = datetime.now(timezone.utc)
        if observation is not None:
            observed = max(observed, _pause_time(observation['observed_at']))
    # Release the lock before transport; later actual activity can recover.
    # The host retains only its existing repo-only Actions-write permission.
    result = subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/git/ref/heads/main'],
                            capture_output=True, text=True, check=True, timeout=60)
    sha = json.loads(result.stdout)['object']['sha']
    if not isinstance(sha, str) or re.fullmatch(r'[0-9a-f]{40}', sha) is None:
        raise ValueError('liveness_identity_refused')
    payload = {'protocol': 'dev-delivery-liveness.v1', 'sha': sha,
               'observed_at': observed.isoformat(), 'startup': 'failed', 'after_sequence': sequence}
    subprocess.run(['gh', 'workflow', 'run', 'dev-delivery-liveness.yml',
                    '--repo', REPOSITORY, '--ref', 'main', '-f', 'kind=heartbeat',
                    '-f', 'payload=' + json.dumps(payload, sort_keys=True)],
                   capture_output=True, check=True, timeout=60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--tooling-sha')
    mode.add_argument('--prepare-dependencies', type=Path)
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--state-directory', type=Path)
    args, controller_args = parser.parse_known_args(argv)
    if args.prepare_dependencies is not None:
        if controller_args or args.self_check or args.state_directory is not None or not sys.flags.isolated:
            return 78
        try:
            copy_runtime_dependencies(args.prepare_dependencies)
            return 0
        except Exception:
            print('controller dependency preparation refused', file=sys.stderr)
            return 78
    try:
        self_check(args.tooling_sha)
    except Exception:
        signal = 'not_requested' if args.self_check else 'sent'
        if not args.self_check:
            try:
                if args.state_directory is None:
                    raise CandidateRefused('startup_requires_private_checkpoint')
                report_startup_failure(args.state_directory)
            except Exception:
                # Missing transport is observable through the existing watchdog.
                signal = 'failed'
        print(json.dumps({'result': 'startup_self_check_failed', 'liveness_signal': signal}, sort_keys=True))
        return 78
    if args.self_check:
        print(json.dumps({'result': 'startup_self_check_passed', 'tooling_sha': args.tooling_sha}, sort_keys=True))
        return 0
    from scripts.postmerge_dev_test import main as controller_main
    if args.state_directory is not None:
        controller_args += ['--state-directory', str(args.state_directory)]
    return controller_main(controller_args)


if __name__ == '__main__':
    raise SystemExit(main())
