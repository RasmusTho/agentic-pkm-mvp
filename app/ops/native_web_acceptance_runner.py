"""Trusted operation-owned envelope for the two fixed Product web pilots."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import time
from typing import Any
from uuid import UUID, uuid4

from app.ops.native_web_acceptance import (
    NativeWebRefusal, WEB_DEADLINE, WEB_SELECTION_HASH, WRAPPERS,
    require_result, web_identity,
)
from app.ops.pg_acceptance import IMAGE_REPOSITORY, POSTGRES_IMAGE, PgAcceptanceDeadlineExceeded, PgAcceptanceError
from app.ops.pg_acceptance_runner import BAKED_PACKAGES, RESOURCE_PATHS, PgAcceptanceRunner, _command

# Image-owned dependencies and assets are checked, never overlaid on /app.
WEB_BAKED_PATHS = (*BAKED_PACKAGES, 'schemas', 'config', 'configs', 'vault', 'scripts', 'alembic.ini')
BROWSER_RUNTIME = Path('/opt/yggdrasil/bws-deploy-runtime')
TTS_FILES = (
    'piper/sv_SE-lisa-medium/sv_SE-lisa-medium.onnx',
    'piper/sv_SE-lisa-medium/sv_SE-lisa-medium.onnx.json',
    'kokoro/kokoro-v1.0.int8.onnx', 'kokoro/voices-v1.0.bin',
)


class NativeWebRunner(PgAcceptanceRunner):
    def __init__(self, repository: Path, journal_directory: Path, *, sha: str, digest: str,
                 channel: str, operation_id: str, tts_root: Path | None = None) -> None:
        super().__init__(repository, journal_directory, sha=sha, digest=digest,
                         channel=channel, operation_id=operation_id)
        self.identity = web_identity(sha, digest, channel, operation_id)
        self.tts_root = tts_root
        self.name = 'ygg-web-' + channel + '-' + operation_id + '-' + WEB_SELECTION_HASH[:12]
        self.directory = journal_directory / 'native-web' / self.name
        self.marker = self.directory.with_name(self.name + '.owner.json')
        self.preparing = self.directory.with_name(self.name + '.owner.preparing')
        generation = str(uuid4())
        if self.marker.exists() or self.marker.is_symlink():
            self._require_parent()
            self._regular_marker(self.marker)
            owner = json.loads(self.marker.read_text())
            if (not isinstance(owner, dict) or set(owner) != set(self.identity) | {'resource_generation'}
                or any(owner.get(k) != v for k, v in self.identity.items())
                or str(UUID(str(owner.get('resource_generation')))) != owner.get('resource_generation')):
                raise NativeWebRefusal('foreign_resource_owner')
            generation = owner['resource_generation']
        self.identity['resource_generation'] = generation
        self.labels = {'io.yggdrasil.web.' + key: value for key, value in self.identity.items()}
        self._asset_sources: dict[str, tuple[Path, tuple[int, int, int, int, int, int, int]]] = {}
        self._asset_bytes = 0

    def resources(self, app_image_id: str) -> dict[str, Any]:
        manifest = super().resources(app_image_id)
        revision = self.identity['source_sha']
        # Every baked web asset/config/source file is verified against Git.
        # scripts/ in the image is intentionally a runtime subset: check only
        # the Dockerfile's actual COPY inventory, not host-only builder tools.
        for record in self._git('ls-tree', '-rz', revision, '--', *WEB_BAKED_PATHS).split(b'\0'):
            if not record:
                continue
            header, raw_name = record.split(b'\t', 1)
            mode, kind, oid = header.decode().split()
            name = raw_name.decode()
            if name.startswith('scripts/') and name not in {
                'scripts/start_api.sh', 'scripts/run_migrations.sh', 'scripts/__init__.py',
                'scripts/prepare_instance_state_permissions.sh', 'scripts/yaml_roundtrip.py',
                'scripts/compose_env.py', 'scripts/validate_issue_readiness.py',
                'scripts/validate_source_anchors.py',
            }:
                continue
            if mode not in {'100644', '100755'} or kind != 'blob':
                raise NativeWebRefusal('unsupported_source_resource')
            content = self._git('cat-file', 'blob', oid)
            manifest['files'][name] = hashlib.sha256(content).hexdigest()
        # A missing pilot is an independently testable refusal; no DB, browser
        # or Product service is started merely to discover that omission.
        if any(selector.split('::')[0] not in manifest['files'] for selector in WRAPPERS):
            raise NativeWebRefusal('required_wrapper_missing')
        (self.directory / 'source' / 'native-web-manifest.json').write_text(json.dumps(manifest, sort_keys=True))
        return manifest

    def _snapshot_file(self, source: Path, target: Path) -> str:
        # Fixed asset inventory only; links, special files, replacement during
        # copying or over-budget resources cannot enter candidate mounts.
        if any(path.is_symlink() for path in (source, *source.parents)):
            raise NativeWebRefusal('prerequisite_source_unqualified')
        before = source.stat()
        self._asset_bytes += before.st_size
        if (not stat.S_ISREG(before.st_mode) or before.st_size > 1024 * 1024 * 1024
            or self._asset_bytes > 2 * 1024 * 1024 * 1024 or before.st_mode & 0o022):
            raise NativeWebRefusal('prerequisite_source_unqualified')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target, follow_symlinks=False)
        after = source.stat()
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns):
            raise NativeWebRefusal('prerequisite_source_drift')
        target.chmod(0o755 if before.st_mode & 0o111 else 0o644)
        with target.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        self._asset_sources[target.relative_to(self.directory / 'assets').as_posix()] = (source, (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_uid, before.st_gid, before.st_mode,
        ))
        return digest

    def _snapshot_prerequisites(self, manifest: dict[str, Any]) -> None:
        if self.tts_root is None:
            raise NativeWebRefusal('selected_local_tts_unavailable')
        assets = self.directory / 'assets'
        assets.mkdir()
        files: dict[str, str] = {}
        native = json.loads(_command([str(BROWSER_RUNTIME / 'bin/python'), '-I', '-c',
            "import json,sys,sysconfig,platform,importlib.metadata as m;print(json.dumps({"
            "'platform':sys.platform,'machine':platform.machine(),'python_abi':sysconfig.get_config_var('SOABI'),"
            "'python_minor':list(sys.version_info[:2]),'prefix':sys.prefix,'playwright':m.version('playwright')}))"]))
        expected_machine = {'amd64': 'x86_64', 'arm64': 'aarch64'}[manifest['app_image_platform']]
        if (native.get('platform') != 'linux' or native.get('machine') != expected_machine
            or native.get('python_minor') != [3, 12] or native.get('prefix') != str(BROWSER_RUNTIME)
            or native.get('playwright') != '1.63.0' or not str(native.get('python_abi')).startswith('cpython-312-')):
            raise NativeWebRefusal('native_browser_abi_or_platform_mismatch')
        site_packages = BROWSER_RUNTIME / 'lib/python3.12/site-packages'
        # These narrow packages are the existing pinned native browser runtime,
        # not a host application overlay or a mounted supervisor/credential store.
        packages = {'playwright': '1.63.0', 'pyee': '13.0.1', 'greenlet': '3.5.6'}
        for package, version in packages.items():
            metadata = site_packages / f'{package}-{version}.dist-info/METADATA'
            if not metadata.is_file() or f'Version: {version}\n' not in metadata.read_text():
                raise NativeWebRefusal('native_browser_runtime_unavailable')
            package_root = site_packages / package
            if not package_root.is_dir():
                raise NativeWebRefusal('native_browser_runtime_unavailable')
            for source in sorted(package_root.rglob('*')):
                if source.is_dir() and not source.is_symlink():
                    continue
                if '__pycache__' in source.parts:
                    continue
                name = 'python/' + source.relative_to(site_packages).as_posix()
                files[name] = self._snapshot_file(source, assets / name)
                if len(files) > 10000:
                    raise NativeWebRefusal('prerequisite_budget_exceeded')
        browser = BROWSER_RUNTIME / 'browsers/chromium_headless_shell-1243'
        if not browser.is_dir():
            raise NativeWebRefusal('native_browser_payload_unavailable')
        for source in sorted(browser.rglob('*')):
            if source.is_dir() and not source.is_symlink():
                continue
            name = 'browsers/' + source.relative_to(browser.parent).as_posix()
            files[name] = self._snapshot_file(source, assets / name)
            if len(files) > 10000:
                raise NativeWebRefusal('prerequisite_budget_exceeded')
        for name in TTS_FILES:
            files['tts/' + name] = self._snapshot_file(self.tts_root / 'models' / name, assets / 'tts' / name)
        manifest['prerequisites'] = {'files': files, 'playwright': packages['playwright'], 'chromium_revision': '1243',
                                     'sv_voice': 'sv_SE-lisa-medium', 'en_us_voice': 'bf_isabella',
                                     'native_runtime': native,
                                     'source_roots': {'browser_runtime': str(BROWSER_RUNTIME), 'tts': str(self.tts_root)},
                                     'source_ownership': {name: list(observed) for name, (_, observed) in self._asset_sources.items()}}
        (self.directory / 'source/native-web-manifest.json').write_text(json.dumps(manifest, sort_keys=True))

    def _check_prerequisites(self, manifest: dict[str, Any]) -> None:
        for name, expected in manifest['prerequisites']['files'].items():
            source, observed = self._asset_sources[name]
            metadata = source.stat()
            if (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns,
                metadata.st_uid, metadata.st_gid, metadata.st_mode) != observed:
                raise NativeWebRefusal('prerequisite_source_drift')
            for path in (source, self.directory / 'assets' / name):
                if path.is_symlink():
                    raise NativeWebRefusal('prerequisite_source_drift')
                with path.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                        raise NativeWebRefusal('prerequisite_source_drift')

    def _image(self) -> dict[str, Any]:
        rows = json.loads(self._docker('image', 'inspect', self.image))
        if not isinstance(rows, list) or len(rows) != 1:
            raise NativeWebRefusal('image_identity_unknown')
        image = rows[0]
        revisions = [value for value in image.get('Config', {}).get('Env', []) if value.startswith('VCS_REF=')]
        if (image.get('Config', {}).get('Labels', {}).get('org.opencontainers.image.revision') != self.identity['source_sha']
            or revisions != ['VCS_REF=' + self.identity['source_sha']]
            or IMAGE_REPOSITORY + '@' + self.identity['image_digest'] not in image.get('RepoDigests', [])
            or image.get('Config', {}).get('Volumes')
            or image.get('Os') != 'linux' or image.get('Architecture') not in {'amd64', 'arm64'}
            or re.fullmatch(r'sha256:[0-9a-f]{64}', str(image.get('Id'))) is None):
            raise NativeWebRefusal('image_identity_mismatch')
        return image

    def _check_container(self, identifier: str, database: str, image_id: str,
                         expected_mounts: dict[str, str]) -> None:
        row = self._owned('tests')
        if row is None or row['Id'] != identifier:
            raise NativeWebRefusal('service_identity_unknown')
        config = row.get('HostConfig', {})
        mounts = row.get('Mounts', [])
        if (row.get('Image') != image_id or config.get('NetworkMode') != 'container:' + database
            or config.get('Binds') or config.get('PortBindings') or config.get('Privileged')
            or config.get('ReadonlyRootfs') is not True or config.get('CapDrop') != ['ALL']
            or config.get('SecurityOpt') not in (['no-new-privileges'], ['no-new-privileges:true'])
            or row.get('Config', {}).get('Entrypoint') != ['/usr/bin/env']
            or row.get('Config', {}).get('Cmd') != self._candidate_command
            or {m.get('Source'): m.get('Destination') for m in mounts if m.get('Type') == 'bind'} != expected_mounts
            or any(m.get('RW') is not False for m in mounts if m.get('Type') == 'bind')
            or any(m.get('Type') not in {'bind', 'tmpfs'} for m in mounts)):
            raise NativeWebRefusal('service_containment_mismatch')
        db = self._owned('db')
        if (db is None or db['Id'] != database or db.get('HostConfig', {}).get('NetworkMode') != 'none'
            or db.get('HostConfig', {}).get('PortBindings') or db.get('HostConfig', {}).get('Binds')):
            raise NativeWebRefusal('database_containment_mismatch')

    def _retain_artifacts(self, identifier: str) -> dict[str, Any]:
        directory = self.directory.parent.parent / 'native-web-results'
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700 or any(p.is_symlink() for p in (directory, *directory.parents))):
            raise NativeWebRefusal('web_evidence_directory_unqualified')
        retained = directory / (self.identity['channel'] + '-' + self.identity['operation_id'] + '-' + self.identity['resource_generation'])
        retained.mkdir(mode=0o700)
        artifacts: dict[str, Any] = {}
        for pilot in ('deep-review', 'daily-briefing'):
            target = retained / pilot
            target.mkdir(mode=0o700)
            hashes: dict[str, str] = {}
            for filename in ('report.json', 'trace.zip', 'junit.xml'):
                try:
                    self._docker('cp', identifier + ':/scratch/native-web-reports/' + pilot + '/' + filename, str(target / filename))
                except PgAcceptanceError:
                    continue
                path = target / filename
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > 128 * 1024 * 1024:
                    raise NativeWebRefusal('pilot_artifact_unqualified')
                path.chmod(0o600)
                with path.open('rb') as stream:
                    hashes[filename] = hashlib.file_digest(stream, 'sha256').hexdigest()
                    os.fsync(stream.fileno())
            artifacts[pilot] = {'directory': str(target), 'files': hashes}
            descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        self.retained_artifacts = artifacts
        return artifacts

    def _execute(self) -> dict[str, Any]:
        image = self._image()
        manifest = self.resources(image['Id'])
        manifest['app_image_platform'] = image['Architecture']
        self._snapshot_prerequisites(manifest)
        self._check_prerequisites(manifest)
        self._docker('pull', POSTGRES_IMAGE, timeout=120)
        scratch_password = secrets.token_hex(24)
        database = self._create('db', [
            '--network', 'none', '--read-only', '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,nodev',
            '--tmpfs', '/var/run/postgresql:rw,nosuid,nodev', '--env', 'POSTGRES_USER=app',
            '--env', 'POSTGRES_PASSWORD=' + scratch_password, '--env', 'POSTGRES_DB=app_test',
            POSTGRES_IMAGE, '-c', 'listen_addresses=127.0.0.1',
        ])
        db = self._owned('db')
        if (db is None or db['Id'] != database or db.get('HostConfig', {}).get('NetworkMode') != 'none'
            or db.get('HostConfig', {}).get('PortBindings') or db.get('HostConfig', {}).get('Binds')):
            raise NativeWebRefusal('database_containment_mismatch')
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
        expected_mounts = {str(source / path): '/app/' + path for path in RESOURCE_PATHS}
        expected_mounts[str(source / 'native-web-manifest.json')] = '/native-web-manifest.json'
        expected_mounts[str(self.directory / 'assets')] = '/web-assets'
        mounts = [arg for src, dst in expected_mounts.items() for arg in (
            '--mount', f'type=bind,src={src},dst={dst},readonly',
        )]
        environment = {
            'PATH': '/usr/local/bin:/usr/bin:/bin', 'PYTHONPATH': '/app:/app/companion-ui/companion-app:/web-assets/python',
            'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1', 'HOME': '/scratch/home',
            'DATABASE_URL': f'postgresql://app:{scratch_password}@127.0.0.1:5432/app_test',
            'DB_DSN': f'postgresql://app:{scratch_password}@127.0.0.1:5432/app_test',
            'STORE_BACKEND': 'pg', 'PKM_ENVIRONMENT': 'test',
            'VAULT_ROOT': '/scratch/vault', 'VAULT_ROOT_TEST': '/scratch/vault', 'TEST_VAULT_ROOT': '/scratch/vault',
            'NATIVE_WEB_CONTEXT': '/scratch/native-web-context.json',
            'TTS_ENABLED': 'true', 'TTS_LOCAL_ONLY': 'true', 'TTS_MODEL_DIR': '/web-assets/tts',
            'TTS_CACHE_DIR': '/scratch/tts/cache', 'TTS_LOG_DIR': '/scratch/tts/logs',
            'TTS_ALLOW_BROWSER_FALLBACK': 'false', 'TTS_ALLOW_CLOUD_FALLBACK': 'false',
            'TTS_SV_VOICE': 'sv_SE-lisa-medium', 'TTS_EN_US_VOICE': 'bf_isabella', 'TTS_EN_GB_VOICE': 'bf_isabella',
            'PLAYWRIGHT_BROWSERS_PATH': '/web-assets/browsers',
            'VCS_REF': self.identity['source_sha'],
        }
        self._candidate_command = ['-i', *(key + '=' + value for key, value in environment.items()),
                                   'python', '-m', 'app.ops.native_web_acceptance', '--manifest', '/native-web-manifest.json']
        identifier = self._create('tests', [
            '--network', 'container:' + database, '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--no-healthcheck', '--workdir', '/app',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=1g', '--tmpfs', '/scratch:rw,nosuid,nodev,size=512m',
            '--tmpfs', '/app/tmp:rw,nosuid,nodev', '--tmpfs', '/app/tmp-test:rw,nosuid,nodev',
            '--tmpfs', '/app/runtime:rw,nosuid,nodev', *mounts,
            '--entrypoint', '/usr/bin/env', self.image, *self._candidate_command,
        ])
        self._check_container(identifier, database, image['Id'], expected_mounts)
        try:
            output = self._docker('start', '--attach', identifier, timeout=WEB_DEADLINE).decode()
        except PgAcceptanceDeadlineExceeded:
            self._retain_artifacts(identifier)
            raise NativeWebRefusal('web_deadline_exceeded') from None
        except PgAcceptanceError:
            # A finite child refusal is recovered only from this exact owned
            # container's single structured line; raw logs are never retained.
            output = self._docker('logs', '--tail', '500', identifier).decode()
        self._check_container(identifier, database, image['Id'], expected_mounts)
        self._check_prerequisites(manifest)
        if self._image()['Id'] != image['Id']:
            raise NativeWebRefusal('image_drift')
        row = self._inspect(identifier)
        if row.get('State', {}).get('Running') is not False:
            raise NativeWebRefusal('wrapper_execution_incomplete')
        artifacts = self._retain_artifacts(identifier)
        lines = [line for line in output.splitlines() if line.startswith('YGGDRASIL_NATIVE_WEB=')]
        if len(lines) != 1:
            raise NativeWebRefusal('wrapper_execution_incomplete')
        result = json.loads(lines[0].split('=', 1)[1])
        if (row.get('State', {}).get('ExitCode') != 0 or result.get('result') != 'passed'):
            if (any(result.get(k) != v for k, v in self.identity.items())
                or not isinstance(result.get('reason'), str) or re.fullmatch(r'[a-z_]{1,80}', result['reason']) is None):
                raise NativeWebRefusal('wrapper_execution_incomplete')
            raise NativeWebRefusal(result['reason'])
        # Cleanup is still unknown here. This local check deliberately supplies
        # no host-cleanup authority to the candidate.
        require_result({**result, 'cleanup': 'confirmed'}, self.identity, manifest)
        if any(set(row['files']) != {'report.json', 'trace.zip', 'junit.xml'} for row in artifacts.values()):
            raise NativeWebRefusal('pilot_artifacts_incomplete')
        for pilot, row in artifacts.items():
            if json.loads((Path(row['directory']) / 'report.json').read_text()) != result['pilots'][pilot]:
                raise NativeWebRefusal('pilot_report_drift')
            from app.ops.native_web_reports import require_artifacts
            require_artifacts(pilot, Path(row['directory']))
        return {**result, 'artifacts': artifacts}

    def verify(self) -> dict[str, Any]:
        result: dict[str, Any] = {**self.identity, 'result': 'refused', 'reason': 'unknown', 'cleanup': 'unknown'}
        try:
            self.cleanup()
            # A retry owns a fresh resource generation after exact old cleanup.
            self.identity['resource_generation'] = str(uuid4())
            self.labels = {'io.yggdrasil.web.' + k: v for k, v in self.identity.items()}
            result.update(self.identity)
            result = {**result, **self._execute()}
        except NativeWebRefusal as exc:
            result.update(result='refused', reason=exc.reason)
        except KeyboardInterrupt:
            result.update(result='refused', reason='interrupted_execution')
        except Exception:
            result.update(result='refused', reason='native_execution_unavailable')
        finally:
            try:
                self.cleanup()
                result['cleanup'] = 'confirmed'
            except Exception:
                result.update(result='unknown', reason='owned_cleanup_unknown', cleanup='unknown')
        if hasattr(self, 'retained_artifacts'):
            result['artifacts'] = self.retained_artifacts
        return result
