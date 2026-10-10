"""Disposable PG effects inside the existing locked native deployment operation.

The candidate has a network-none namespace, readonly public Git resources, and
scratch storage only. Docker and source-object access stay in the trusted worker.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import time
from typing import Any

from app.ops.pg_acceptance import (
    IMAGE_REPOSITORY, POSTGRES_IMAGE, SELECTORS, SELECTION_HASH,
    PgAcceptanceError, identity, require_pass,
)

RESOURCE_PATHS = (
    'tests', 'docs', 'golden', 'pytest.ini', 'Dockerfile.builderops',
    'Dockerfile.builderops.dockerignore', 'requirements-builderops.txt',
    'docker-compose.devui-sources.yml', 'docker-compose.devui.yml', '.github', '.codex', 'AGENTS.md',
)
BAKED_PACKAGES = ('app', 'mimer_runtime', 'llm_contract', 'companion-ui/companion-app')
PROFILE_DEADLINE = 1800


def _command(argv: list[str], *, timeout: int = 60) -> bytes:
    # No HOME, credential helper, Docker context/socket override, private env,
    # caller Python path, or Git overlay is inherited by tooling subprocesses.
    environment = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
                   'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                   'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_REPLACE_OBJECTS': '1'}
    try:
        result = subprocess.run(argv, env=environment, capture_output=True, check=False, timeout=timeout)
        if result.returncode or len(result.stdout) > 128 * 1024 * 1024:
            raise PgAcceptanceError()
        return result.stdout
    except Exception:
        raise PgAcceptanceError() from None


class PgAcceptanceRunner:
    def __init__(self, repository: Path, journal_directory: Path, *, sha: str, digest: str,
                 channel: str, operation_id: str) -> None:
        self.identity = identity(sha, digest, channel, operation_id)
        self.repository = repository
        self.name = 'ygg-pg-' + channel + '-' + operation_id + '-' + SELECTION_HASH[:12]
        self.directory = journal_directory / 'pg-acceptance' / self.name
        self.marker = self.directory.with_name(self.name + '.owner.json')
        self.preparing = self.directory.with_name(self.name + '.owner.preparing')
        self.image = IMAGE_REPOSITORY + ':' + sha + '@' + digest
        self.labels = {'io.yggdrasil.pg.' + key: value for key, value in self.identity.items()}

    def _docker(self, *arguments: str, timeout: int = 60) -> bytes:
        return _command(['docker', *arguments], timeout=timeout)

    def _git(self, *arguments: str) -> bytes:
        return _command(['git', '-c', 'safe.directory=' + str(self.repository),
                         '-C', str(self.repository), *arguments])

    def _inspect(self, identifier: str) -> dict[str, Any]:
        rows = json.loads(self._docker('inspect', '--type', 'container', identifier))
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise PgAcceptanceError()
        return rows[0]

    def _owned(self, suffix: str) -> dict[str, Any] | None:
        name = self.name + '-' + suffix
        observed = self._docker('container', 'ls', '--all', '--no-trunc', '--filter',
                                'name=^/' + name + '$', '--format', '{{.ID}}').decode().strip()
        if not observed:
            return None
        if re.fullmatch(r'[0-9a-f]{64}', observed) is None:
            raise PgAcceptanceError()
        row = self._inspect(observed)
        labels = row.get('Config', {}).get('Labels', {})
        if (row.get('Id') != observed or row.get('Name') != '/' + name
            or not isinstance(labels, dict) or any(labels.get(k) != v for k, v in self.labels.items())):
            raise PgAcceptanceError()
        return row

    def cleanup(self) -> None:
        # Inspect exact IDs and all identity labels before each removal; never
        # use a project-wide prune, a name prefix, or another channel's receipt.
        for suffix in ('tests', 'db'):
            row = self._owned(suffix)
            if row is not None:
                self._docker('rm', '--force', row['Id'])
                if self._owned(suffix) is not None:
                    raise PgAcceptanceError()
        if not self.directory.parent.exists():
            return
        self._require_parent()
        owner = self._owner()
        if self.directory.exists() or self.directory.is_symlink():
            self._require_directory()
            if owner != self.identity:
                raise PgAcceptanceError()
            shutil.rmtree(self.directory)
        # A preparing file can be incomplete only before directory/container
        # creation. Its exact operation namespace and private parent are owned
        # by the existing locked request; no durable resource relies on it.
        if self.preparing.exists() or self.preparing.is_symlink():
            self._regular_marker(self.preparing)
            try:
                prepared = json.loads(self.preparing.read_text())
            except (ValueError, UnicodeError):
                prepared = None
            if prepared is not None and prepared != self.identity:
                raise PgAcceptanceError()
            self.preparing.unlink()
        if owner is not None:
            # Persist resource-directory absence before retiring its proof,
            # including recovery that observes an already removed directory.
            self._sync_parent()
            self.marker.unlink()
        self._sync_parent()

    def _regular_marker(self, path: Path) -> None:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 8192):
            raise PgAcceptanceError()

    def _owner(self) -> dict[str, str] | None:
        try:
            self.marker.lstat()
        except FileNotFoundError:
            return None
        self._regular_marker(self.marker)
        owner = json.loads(self.marker.read_text())
        if owner != self.identity:
            raise PgAcceptanceError()
        return owner

    def _sync_parent(self) -> None:
        descriptor = os.open(self.directory.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _require_parent(self) -> None:
        info = self.directory.parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700
            or any(path.is_symlink() for path in self.directory.parents)):
            raise PgAcceptanceError()

    def _require_directory(self) -> None:
        self._require_parent()
        info = self.directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
            raise PgAcceptanceError()

    def resources(self, app_image_id: str) -> dict[str, Any]:
        # Recovery first removes only this operation's owned remnants. A fresh
        # snapshot is always made from immutable objects, never working files.
        self.directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._require_parent()
        if self._owner() is not None or self.directory.exists():
            raise PgAcceptanceError()
        descriptor = os.open(self.preparing, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as owner_stream:
            json.dump(self.identity, owner_stream, sort_keys=True)
            owner_stream.flush()
            os.fsync(owner_stream.fileno())
        os.rename(self.preparing, self.marker)
        self._sync_parent()
        # The complete owner proof is outside the removable tree, durable
        # before its first directory, and removed only after the tree is gone.
        self.directory.mkdir(mode=0o700)
        self._require_directory()
        revision = self.identity['source_sha']
        if self._git('rev-parse', revision + '^{commit}').decode().strip() != revision:
            raise PgAcceptanceError()
        tree = self._git('rev-parse', revision + '^{tree}').decode().strip()
        if re.fullmatch(r'[0-9a-f]{40}', tree) is None:
            raise PgAcceptanceError()
        paths = (*RESOURCE_PATHS, *BAKED_PACKAGES)
        objects: dict[str, tuple[str, str]] = {}
        for record in self._git('ls-tree', '-rz', revision, '--', *paths).split(b'\0'):
            if not record:
                continue
            header, raw_name = record.split(b'\t', 1)
            mode, kind, oid = header.decode().split()
            if mode not in {'100644', '100755'} or kind != 'blob':
                raise PgAcceptanceError()
            objects[raw_name.decode()] = (mode, oid)
        manifest: dict[str, Any] = {**self.identity, 'resource_tree': tree,
                                    'app_image_id': app_image_id, 'files': {}}
        source = self.directory / 'source'
        source.mkdir()
        archive = self._git('archive', '--format=tar', revision, '--', *paths)
        seen: set[str] = set()
        with tarfile.open(fileobj=io.BytesIO(archive)) as archived:
            for member in archived:
                name = member.name.rstrip('/')
                if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
                    raise PgAcceptanceError()
                if member.isdir():
                    continue
                if not member.isfile() or name not in objects or name in seen:
                    raise PgAcceptanceError()
                stream = archived.extractfile(member)
                if stream is None:
                    raise PgAcceptanceError()
                content = stream.read()
                mode, oid = objects[name]
                if hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest() != oid:
                    raise PgAcceptanceError()
                seen.add(name)
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                target.chmod(0o755 if mode == '100755' else 0o644)
                if any(name == path or name.startswith(path + '/') for path in RESOURCE_PATHS) or name.endswith('.py'):
                    manifest['files'][name] = hashlib.sha256(content).hexdigest()
        if seen != set(objects) or any(not (source / path).exists() for path in RESOURCE_PATHS):
            raise PgAcceptanceError()
        if any(selector.split('::')[0] not in manifest['files'] for selector in SELECTORS):
            raise PgAcceptanceError()
        # Baked package trees are checked in-container but never bind-mounted.
        (source / 'pg-acceptance-manifest.json').write_text(json.dumps(manifest, sort_keys=True))
        return manifest

    def _create(self, suffix: str, arguments: list[str]) -> str:
        labels = [argument for key, value in self.labels.items() for argument in ('--label', key + '=' + value)]
        identifier = self._docker('create', '--name', self.name + '-' + suffix,
                                  *labels, *arguments).decode().strip()
        row = self._owned(suffix)
        if row is None or row['Id'] != identifier:
            raise PgAcceptanceError()
        return identifier

    def verify(self) -> dict[str, Any]:
        self.cleanup()
        try:
            images = json.loads(self._docker('image', 'inspect', self.image))
            if not isinstance(images, list) or len(images) != 1:
                raise PgAcceptanceError()
            image = images[0]
            if (image.get('Config', {}).get('Labels', {}).get('org.opencontainers.image.revision') != self.identity['source_sha']
                or IMAGE_REPOSITORY + '@' + self.identity['image_digest'] not in image.get('RepoDigests', [])
                or image.get('Config', {}).get('Volumes')
                or re.fullmatch(r'sha256:[0-9a-f]{64}', str(image.get('Id'))) is None):
                raise PgAcceptanceError()
            manifest = self.resources(image['Id'])
            self._docker('pull', POSTGRES_IMAGE, timeout=120)
            database = self._create('db', [
                '--network', 'none', '--read-only', '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,nodev',
                '--tmpfs', '/var/run/postgresql:rw,nosuid,nodev',
                '--env', 'POSTGRES_USER=app', '--env', 'POSTGRES_PASSWORD=app', '--env', 'POSTGRES_DB=app_test',
                POSTGRES_IMAGE, '-c', 'listen_addresses=127.0.0.1',
            ])
            row = self._inspect(database)
            if (row.get('HostConfig', {}).get('NetworkMode') != 'none'
                or row.get('HostConfig', {}).get('PortBindings') or row.get('HostConfig', {}).get('Binds')):
                raise PgAcceptanceError()
            self._docker('start', database)
            for attempt in range(30):
                try:
                    self._docker('exec', database, 'pg_isready', '-h', '127.0.0.1', '-p', '5432',
                                 '-U', 'app', '-d', 'app_test', timeout=5)
                    break
                except PgAcceptanceError:
                    if attempt == 29:
                        raise
                    time.sleep(2)
            # Provision the isolated acceptance dependency at the trusted
            # native effect boundary, matching CI's existing service setup.
            self._docker('exec', database, 'psql', '--username', 'app', '--dbname', 'app_test',
                         '--command', 'CREATE EXTENSION IF NOT EXISTS vector')
            source = self.directory / 'source'
            mounts = [argument for path in RESOURCE_PATHS for argument in (
                '--mount', f'type=bind,src={source / path},dst=/app/{path},readonly',
            )]
            mounts += ['--mount', f'type=bind,src={source / "pg-acceptance-manifest.json"},dst=/pg-manifest.json,readonly']
            environment = {
                'PATH': '/usr/local/bin:/usr/bin:/bin', 'PYTHONPATH': '/app:/app/companion-ui/companion-app',
                'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1', 'HOME': '/tmp',
                'DATABASE_URL': 'postgresql://app:app@127.0.0.1:5432/app_test',
                'DB_DSN': 'postgresql://app:app@127.0.0.1:5432/app_test',
                'STORE_BACKEND': 'pg', 'LLM_PROVIDER': 'mock', 'PKM_ENVIRONMENT': 'test',
                'VAULT_ROOT': '/scratch/vault', 'VAULT_ROOT_TEST': '/scratch/vault', 'TEST_VAULT_ROOT': '/scratch/vault',
            }
            container = self._create('tests', [
                '--network', 'container:' + database, '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--no-healthcheck', '--workdir', '/app',
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=1g', '--tmpfs', '/scratch:rw,nosuid,nodev,size=256m',
                '--tmpfs', '/app/tmp:rw,nosuid,nodev', '--tmpfs', '/app/tmp-test:rw,nosuid,nodev',
                '--tmpfs', '/app/runtime:rw,nosuid,nodev', *mounts,
                '--entrypoint', '/usr/bin/env', self.image, '-i',
                *(key + '=' + value for key, value in environment.items()),
                'python', '-m', 'app.ops.pg_acceptance', '--manifest', '/pg-manifest.json',
            ])
            row = self._inspect(container)
            config = row.get('HostConfig', {})
            observed_mounts = row.get('Mounts', [])
            expected_mounts = {str(source / path): '/app/' + path for path in RESOURCE_PATHS}
            expected_mounts[str(source / 'pg-acceptance-manifest.json')] = '/pg-manifest.json'
            if (row.get('Image') != image['Id'] or config.get('NetworkMode') != 'container:' + database
                or config.get('Binds') or config.get('PortBindings') or config.get('Privileged')
                or config.get('ReadonlyRootfs') is not True or config.get('CapDrop') != ['ALL']
                or {mount.get('Source'): mount.get('Destination') for mount in observed_mounts if mount.get('Type') == 'bind'} != expected_mounts
                or any(mount.get('RW') is not False for mount in observed_mounts if mount.get('Type') == 'bind')
                or any(mount.get('Type') not in {'bind', 'tmpfs'} for mount in observed_mounts)):
                raise PgAcceptanceError()
            output = self._docker('start', '--attach', container, timeout=PROFILE_DEADLINE).decode()
            rows = [line for line in output.splitlines() if line.startswith('YGGDRASIL_PG_ACCEPTANCE=')]
            if len(rows) != 1:
                raise PgAcceptanceError()
            result = json.loads(rows[0].split('=', 1)[1])
            require_pass(result, self.identity['source_sha'], self.identity['image_digest'],
                         self.identity['channel'], self.identity['operation_id'])
            if result['resource_tree'] != manifest['resource_tree'] or result['app_image_id'] != image['Id']:
                raise PgAcceptanceError()
            return result
        finally:
            self.cleanup()
