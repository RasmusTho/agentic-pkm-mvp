"""Trusted native resource owner for the single fixed journaling extension."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
from typing import Any
from uuid import UUID, uuid4
from xml.etree import ElementTree

from app.ops.native_journaling_acceptance import (
    DEADLINE, PROFILE, SELECTION_HASH, WRAPPER, identity, require_report, require_result,
)
from app.ops.native_journaling_transport import ProviderRelay, REFERENCE_KEYS, selected_references
from app.ops.native_web_acceptance import NativeWebRefusal, hash_json
from app.ops.native_web_acceptance_runner import NativeWebRunner
from app.ops.pg_acceptance import POSTGRES_IMAGE, PgAcceptanceError
from app.ops.pg_acceptance_runner import PgAcceptanceRunner, RESOURCE_PATHS


class NativeJournalingRunner(NativeWebRunner):
    def __init__(self, repository: Path, journal_directory: Path, *, sha: str, digest: str,
                 channel: str, operation_id: str) -> None:
        PgAcceptanceRunner.__init__(self, repository, journal_directory, sha=sha, digest=digest,
                                    channel=channel, operation_id=operation_id)
        self.identity = identity(sha, digest, channel, operation_id)
        self.name = 'ygg-jrnl-' + operation_id + '-' + SELECTION_HASH[:12]
        self.directory = journal_directory / 'native-journaling' / self.name
        self.marker = self.directory.with_name(self.name + '.owner.json')
        self.preparing = self.directory.with_name(self.name + '.owner.preparing')
        generation = str(uuid4())
        proof = self.marker if self.marker.exists() or self.marker.is_symlink() else self.preparing
        if proof.exists() or proof.is_symlink():
            self._require_parent()
            self._regular_marker(proof)
            try:
                owner = json.loads(proof.read_text())
            except (ValueError, UnicodeError):
                if proof != self.preparing or self.directory.exists():
                    raise NativeWebRefusal('foreign_resource_owner') from None
                owner = None  # Interrupted pre-owner bytes; no durable resource exists.
            if owner is not None and (not isinstance(owner, dict)
                or set(owner) != set(self.identity) | {'resource_generation'}
                or any(owner.get(key) != value for key, value in self.identity.items())
                or str(UUID(str(owner.get('resource_generation')))) != owner.get('resource_generation')):
                raise NativeWebRefusal('foreign_resource_owner')
            if owner is not None:
                generation = owner['resource_generation']
        self.identity['resource_generation'] = generation
        self.labels = {'io.yggdrasil.journaling.' + key: value for key, value in self.identity.items()}

    def resources(self, app_image_id: str) -> dict[str, Any]:
        # Reuse the exact-SHA native source producer, including baked config/schema
        # checks. No application tree from this snapshot becomes a candidate mount.
        manifest = NativeWebRunner.resources(self, app_image_id)
        if WRAPPER.split('::')[0] not in manifest['files']:
            raise NativeWebRefusal('journaling_wrapper_missing')
        (self.directory / 'source/native-journaling-manifest.json').write_text(json.dumps(manifest, sort_keys=True))
        return manifest

    def _provider_assets(self) -> dict[str, str]:
        references = selected_references()
        self.provider_references = references
        target = self.directory / 'provider'
        target.mkdir(mode=0o700)
        environment = {REFERENCE_KEYS[0]: references[REFERENCE_KEYS[0]]}
        self.provider_hashes: dict[str, str] = {}
        for key in REFERENCE_KEYS[1:]:
            source = Path(references[key])
            before = source.stat()
            data = source.read_bytes()
            after = source.stat()
            observed = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
                                      value.st_ctime_ns, value.st_uid, value.st_gid, value.st_mode)
            if observed(before) != observed(after):
                raise NativeWebRefusal('actual_product_provider_reference_drift')
            path = target / key
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self.provider_hashes[key] = hashlib.sha256(data).hexdigest()
            environment[key] = '/provider/' + key
        return environment

    def _check_provider_assets(self) -> None:
        if selected_references() != self.provider_references:
            raise NativeWebRefusal('actual_product_provider_reference_drift')
        for key, expected in self.provider_hashes.items():
            for path in (Path(self.provider_references[key]), self.directory / 'provider' / key):
                if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise NativeWebRefusal('actual_product_provider_reference_drift')

    def _retain(self, identifier: str, manifest: dict[str, Any]) -> dict[str, Any]:
        directory = self.directory.parent.parent / 'native-journaling-results'
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700
            or any(path.is_symlink() for path in (directory, *directory.parents))):
            raise NativeWebRefusal('journaling_evidence_directory_unqualified')
        final = directory / (self.identity['operation_id'] + '-' + self.identity['resource_generation'])
        pending = directory / (final.name + '.pending')
        pending.mkdir(mode=0o700)
        filenames = {'report.json': self.identity['resource_generation'] + '.json', 'junit.xml': 'junit.xml',
                     'journal-review-outbox.jsonl': 'journal-review-outbox.jsonl'}
        hashes = {}
        for target, source in filenames.items():
            self._docker('cp', identifier + ':/scratch/journaling-evidence/' + source, str(pending / target))
            path = pending / target
            metadata = path.lstat()
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or metadata.st_size > 4 * 1024 * 1024):
                raise NativeWebRefusal('journaling_artifact_unqualified')
            path.chmod(0o600)
            with path.open('rb') as stream:
                hashes[target] = hashlib.file_digest(stream, 'sha256').hexdigest()
                os.fsync(stream.fileno())
        report = json.loads((pending / 'report.json').read_text())
        require_report(report, manifest)
        receipt_rows = [json.loads(line) for line in (pending / 'journal-review-outbox.jsonl').read_text().splitlines()
                        if line.strip()]
        if (len(receipt_rows) != 1 or receipt_rows[0].get('event') != 'journal.entry.accepted'
            or receipt_rows[0].get('event_id') != report['artifacts']['acceptance_receipt_id']):
            raise NativeWebRefusal('guarded_journaling_receipt_incomplete')
        rows = ElementTree.parse(pending / 'junit.xml').getroot().findall('.//testcase')
        if (len(rows) != 1 or rows[0].get('name') != WRAPPER.split('::')[1]
            or rows[0].get('classname') != 'tests.journaling.test_conversational_journaling_live_acceptance'
            or any(rows[0].find(tag) is not None for tag in ('failure', 'error', 'skipped'))):
            raise NativeWebRefusal('journaling_junit_incomplete')
        descriptor = os.open(pending, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if final.exists() or final.is_symlink():
            raise NativeWebRefusal('foreign_journaling_evidence_preserved')
        os.rename(pending, final)
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.retained_artifacts = {'directory': str(final), 'files': hashes}
        return {'artifacts': self.retained_artifacts, 'report': report}

    def _execute(self) -> dict[str, Any]:
        image = self._image()
        manifest = self.resources(image['Id'])
        provider = self._provider_assets()  # Refuse missing actual provider before Product effects.
        self._check_provider_assets()
        self._docker('pull', POSTGRES_IMAGE, timeout=120)
        password = secrets.token_hex(24)
        database = self._create('db', [
            '--network', 'none', '--read-only', '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,nodev',
            '--tmpfs', '/var/run/postgresql:rw,nosuid,nodev', '--env', 'POSTGRES_USER=app',
            '--env', 'POSTGRES_PASSWORD=' + password, '--env', 'POSTGRES_DB=app_test',
            POSTGRES_IMAGE, '-c', 'listen_addresses=127.0.0.1',
        ])
        self._docker('start', database)
        for attempt in range(30):
            try:
                self._docker('exec', database, 'pg_isready', '-h', '127.0.0.1', '-U', 'app', '-d', 'app_test', timeout=5)
                break
            except PgAcceptanceError:
                if attempt == 29:
                    raise NativeWebRefusal('database_unavailable') from None
                time.sleep(2)
        self._docker('exec', database, 'psql', '--username', 'app', '--dbname', 'app_test',
                     '--set=ON_ERROR_STOP=1', '--command', 'CREATE EXTENSION IF NOT EXISTS vector')
        source = self.directory / 'source'
        mounts = {str(source / path): '/app/' + path for path in RESOURCE_PATHS}
        mounts[str(source / 'native-journaling-manifest.json')] = '/native-journaling-manifest.json'
        mounts[str(self.directory / 'provider')] = '/provider'
        environment = {
            'PATH': '/usr/local/bin:/usr/bin:/bin', 'PYTHONPATH': '/app', 'PYTHONDONTWRITEBYTECODE': '1',
            'PYTHONUNBUFFERED': '1', 'HOME': '/scratch/home', 'PKM_ENVIRONMENT': 'test', 'STORE_BACKEND': 'pg',
            'DATABASE_URL': f'postgresql://app:{password}@127.0.0.1:5432/app_test',
            'DB_DSN': f'postgresql://app:{password}@127.0.0.1:5432/app_test',
            'VAULT_ROOT': '/scratch/vault', 'VAULT_ROOT_TEST': '/scratch/vault', 'TEST_VAULT_ROOT': '/scratch/vault',
            'VCS_REF': self.identity['source_sha'], **provider,
        }
        self._candidate_command = ['-i', *(key + '=' + value for key, value in environment.items()),
                                   'python', '-m', 'app.ops.native_journaling_acceptance',
                                   '--manifest', '/native-journaling-manifest.json']
        mount_args = [arg for src, dst in mounts.items() for arg in ('--mount', f'type=bind,src={src},dst={dst},readonly')]
        identifier = self._create('tests', [
            '--network', 'container:' + database, '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--no-healthcheck', '--workdir', '/app',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=1g', '--tmpfs', '/scratch:rw,nosuid,nodev,size=512m',
            '--tmpfs', '/app/tmp:rw,nosuid,nodev', '--tmpfs', '/app/tmp-test:rw,nosuid,nodev',
            '--tmpfs', '/app/runtime:rw,nosuid,nodev', *mount_args,
            '--entrypoint', '/usr/bin/env', self.image, *self._candidate_command,
        ])
        self._check_container(identifier, database, image['Id'], mounts)
        self._check_provider_assets()
        db = self._owned('db')
        if (db is None or db['Id'] != database or type(db.get('State', {}).get('Pid')) is not int
            or db.get('State', {}).get('Running') is not True):
            raise NativeWebRefusal('database_identity_unknown')
        sandbox = db.get('NetworkSettings', {}).get('SandboxKey')
        if not isinstance(sandbox, str) or re.fullmatch(r'/(?:var/)?run/docker/netns/[a-z0-9_-]+', sandbox) is None:
            raise NativeWebRefusal('database_namespace_identity_unknown')
        namespace = os.open(sandbox, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(namespace)
            observed = os.stat('/proc/' + str(db['State']['Pid']) + '/ns/net')
            reread = self._owned('db')
            if ((opened.st_dev, opened.st_ino) != (observed.st_dev, observed.st_ino)
                or reread is None or reread['Id'] != database or reread.get('State') != db['State']
                or reread.get('NetworkSettings', {}).get('SandboxKey') != sandbox):
                raise NativeWebRefusal('database_namespace_identity_drift')
            with ProviderRelay(namespace, provider[REFERENCE_KEYS[0]]) as relay:
                try:
                    output = self._docker('start', '--attach', identifier, timeout=DEADLINE).decode()
                except PgAcceptanceError:
                    output = self._docker('logs', '--tail', '500', identifier).decode()
        finally:
            os.close(namespace)
        transport = relay.readback()
        self._check_provider_assets()
        self._check_container(identifier, database, image['Id'], mounts)
        if self._image()['Id'] != image['Id']:
            raise NativeWebRefusal('image_drift')
        row = self._inspect(identifier)
        lines = [line for line in output.splitlines() if line.startswith('YGGDRASIL_NATIVE_JOURNALING=')]
        if row.get('State', {}).get('Running') is not False or len(lines) != 1:
            raise NativeWebRefusal('journaling_wrapper_execution_incomplete')
        result = json.loads(lines[0].split('=', 1)[1])
        if any(result.get(key) != value for key, value in self.identity.items()):
            raise NativeWebRefusal('journaling_result_identity_mismatch')
        if row.get('State', {}).get('ExitCode') != 0 or result.get('result') != 'passed':
            reason = result.get('reason')
            if not isinstance(reason, str) or re.fullmatch(r'[a-z_]{1,80}', reason) is None:
                reason = 'journaling_wrapper_execution_incomplete'
            raise NativeWebRefusal(reason)
        retained = self._retain(identifier, manifest)
        require_result(result, manifest)
        if (result.get('wrapper') != WRAPPER or result.get('app_image_id') != image['Id']
            or result.get('resource_tree') != manifest['resource_tree'] or result.get('report') != retained['report']
            or result.get('report_hash') != hash_json(retained['report'])
            or result['guarded_receipt']['sha256'] != retained['artifacts']['files']['journal-review-outbox.jsonl']):
            raise NativeWebRefusal('journaling_evidence_drift')
        return {**result, 'transport': transport, 'artifacts': retained['artifacts'], 'profile_version': PROFILE}

    def verify(self) -> dict[str, Any]:
        result: dict[str, Any] = {**self.identity, 'result': 'refused', 'reason': 'unknown', 'cleanup': 'unknown'}
        try:
            self.cleanup()
            self.identity['resource_generation'] = str(uuid4())
            self.labels = {'io.yggdrasil.journaling.' + key: value for key, value in self.identity.items()}
            result.update(self.identity)
            result.update(self._execute())
        except NativeWebRefusal as exc:
            result.update(result='refused', reason=exc.reason)
            if exc.reason == 'native_provider_transport_cleanup_unknown':
                self.extra_cleanup_unknown = True
        except KeyboardInterrupt:
            result.update(result='refused', reason='interrupted_execution')
        except Exception:
            result.update(result='refused', reason='native_execution_unavailable')
        finally:
            try:
                self.cleanup()
                if getattr(self, 'extra_cleanup_unknown', False):
                    result.update(result='unknown', reason='native_provider_transport_cleanup_unknown', cleanup='unknown')
                else:
                    result['cleanup'] = 'confirmed'
            except Exception:
                result.update(result='unknown', reason='owned_cleanup_unknown', cleanup='unknown')
        if hasattr(self, 'retained_artifacts'):
            result['artifacts'] = self.retained_artifacts
        return result
