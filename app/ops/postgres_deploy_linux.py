"""Linux effects for BWS-04. The supervised server owns worker lifetime, not SSH.

All command output is captured and discarded unless it is a validated identifier
or status. The root-owned configuration and Unix socket are operator-installed;
there is no credential-valued environment, command argument, or status response.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import socket
import socketserver
import stat
import subprocess
import sys
import threading
from typing import Any, Iterator
from uuid import UUID
from urllib.parse import urlencode, quote

from app.config.database import credential_free_database_fields, host_database_fields
from app.ops.bws_secret_reader import BwsReaderConfig, BwsSecretReader
from app.ops.host_secret_contract import DATABASE_CONSUMERS
from app.ops.postgres_deploy import (
    DeployJournal, DeployPlan, DeployReceipt, DeployWorker, PostgresDeployError,
    password_authenticate, vm_selected_values,
)


def _command(argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
             pass_fds: tuple[int, ...] = ()) -> str:
    result = subprocess.run(argv, cwd=cwd, env=env, pass_fds=pass_fds, capture_output=True, text=True, check=False)
    if result.returncode:
        raise PostgresDeployError()
    return result.stdout


def validate_database_inputs(environment: Any, paths: list[Path]) -> None:
    from scripts.compose_env import compose_env_value
    sources = [dict(environment)]
    for path in paths:
        if not path.exists():
            continue
        values = {}
        for line in path.read_text().splitlines():
            match = re.match(r'^(?:export\s+)?(DATABASE_URL|DB_DSN|POSTGRES_PASSWORD|PGPASSWORD|PGPASSFILE|PGSERVICE|PGSERVICEFILE)\s*=(.*)$', line.strip())
            if match:
                key, raw = match.groups()
                if key in values:
                    raise PostgresDeployError()
                values[key] = compose_env_value(raw)
        sources.append(values)
    for source in sources:
        for key in ('POSTGRES_PASSWORD', 'PGPASSWORD', 'PGPASSFILE', 'PGSERVICE', 'PGSERVICEFILE'):
            if source.get(key):
                raise PostgresDeployError()
        for key in ('DATABASE_URL', 'DB_DSN'):
            if source.get(key):
                credential_free_database_fields(source[key])


def database_input_files(cfg: LinuxConfig) -> list[Path]:
    from scripts.compose_env import compose_env_value
    pin = cfg.root / 'config/deploy' / (cfg.channel + '.env')
    runtime = './tmp-test/runtime.env' if cfg.channel == 'test' else './tmp/runtime.env'
    for line in pin.read_text().splitlines():
        if line.startswith('WATCHER_RUNTIME_ENV_FILE='):
            runtime = compose_env_value(line.split('=', 1)[1])
    path = Path(runtime)
    return [pin, path if path.is_absolute() else cfg.root / path]


def effective_database_fields(config: LinuxConfig, environment: Any) -> dict[str, str]:
    """One alias/producer precedence for validation, authentication and Compose.

    Explicit process overrides precede the pin and generated runtime file; within
    each source DATABASE_URL precedes DB_DSN. Both aliases are validated first.
    """
    from scripts.compose_env import compose_env_value
    paths = database_input_files(config)
    validate_database_inputs(environment, paths)
    sources = [dict(environment)]
    for path in paths:
        source = {}
        if path.exists():
            for line in path.read_text().splitlines():
                match = re.match(r'^(?:export\s+)?(DATABASE_URL|DB_DSN)\s*=(.*)$', line.strip())
                if match:
                    source[match[1]] = compose_env_value(match[2])
        sources.append(source)
    explicit = next((source.get('DATABASE_URL') or source.get('DB_DSN')
                     for source in sources if source.get('DATABASE_URL') or source.get('DB_DSN')), None)
    fields = credential_free_database_fields(explicit) if explicit else {}
    fields.setdefault('user', 'app')
    # Only the no-override path owns the managed-db default. Explicit libpq
    # DSNs without a host must reach the host-probe refusal, never gain proof
    # for a silently substituted target. Empty hosts are preserved likewise.
    if explicit is None:
        fields.setdefault('host', 'db')
    fields.setdefault('port', '5432')
    fields.setdefault('dbname', {'dev': 'app_dev', 'test': 'app_test', 'prod': 'app'}[config.channel])
    return fields


def database_target(fields: dict[str, str]) -> str:
    return 'local' if fields.get('host') == 'db' and fields.get('port') == '5432' and not fields.get('hostaddr') else 'external'


def _database_url(fields: dict[str, str]) -> str:
    return 'postgresql+psycopg:///?' + urlencode(fields, quote_via=quote)


def require_file_protocol(root: Path, revision: str) -> None:
    import ast
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise PostgresDeployError()
    tree = ast.parse(_command(['git', '-C', str(root), 'show', revision + ':app/config/database.py']))
    if not any(isinstance(node, ast.Assign) and len(node.targets) == 1
               and isinstance(node.targets[0], ast.Name)
               and node.targets[0].id == 'DATABASE_FILE_CREDENTIAL_PROTOCOL'
               and isinstance(node.value, ast.Constant) and node.value.value == 1 for node in tree.body):
        raise PostgresDeployError()


def inherited_worker_guard(channel: str, compose_command: str | None = None) -> None:
    import fcntl
    cfg = LinuxConfig.load(channel)
    descriptor = int(os.environ['BWS_DEPLOY_LOCK_FD'])
    expected = cfg.root / 'config/deploy' / (channel + '.env.lock') / 'bws-owner'
    info, held = expected.lstat(), os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or (held.st_dev, held.st_ino) != (info.st_dev, info.st_ino):
        raise PostgresDeployError()
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    receipt = cfg.journal.read()
    if receipt is None or receipt.stage != 'activating' or receipt.operation_id != os.environ.get('BWS_DEPLOY_OPERATION_ID'):
        raise PostgresDeployError()
    if compose_command in {'up', 'run', 'start', 'restart'}:
        # Automatic rollback may restore an older pin. It cannot recreate clients
        # from a legacy image that bypasses the file-aware resolver.
        from scripts.compose_env import compose_env_value
        pin = cfg.root / 'config/deploy' / (channel + '.env')
        revisions = [compose_env_value(line.split('=', 1)[1]) for line in pin.read_text().splitlines()
                     if line.startswith('APP_IMAGE_TAG=')]
        if len(revisions) != 1:
            raise PostgresDeployError()
        require_file_protocol(cfg.root, revisions[0])
    target = database_target(effective_database_fields(cfg, os.environ))
    if os.environ.get('BWS_DATABASE_TARGET') != target or (target == 'external' and os.environ.get('COMPOSE_PROFILES')):
        raise PostgresDeployError()
    PasswordSource(cfg).verify()
    validate_database_inputs(os.environ, database_input_files(cfg))
    # Recheck the same selected scope before every Compose call, including
    # calls made by the preserved migration/pin/rollback machinery.
    plan = DeployPlan(channel, '0' * 40, tuple(DATABASE_CONSUMERS.values()),
                      (*DATABASE_CONSUMERS, 'heimdal-api-ingress', 'heimdal-capture-watch', 'heimdal-raw-migrate'))
    values = vm_selected_values(plan, cfg.reader())
    if values['postgres-db']['postgres.password'].encode() != cfg.password_file.read_bytes():
        raise PostgresDeployError()


def _private_json(path: Path) -> dict[str, Any]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'r') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 65536):
            raise PostgresDeployError()
        result = json.load(stream)
        if not isinstance(result, dict):
            raise PostgresDeployError()
        return result


def _root_directory(path: Path) -> None:
    if not path.is_absolute():
        raise PostgresDeployError()
    for parent in reversed((path, *path.parents)):
        if parent.is_symlink():
            raise PostgresDeployError()
        if not parent.exists():
            parent.mkdir(mode=0o700)
        if parent.stat().st_uid != 0:
            raise PostgresDeployError()
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise PostgresDeployError()


@dataclass(frozen=True)
class LinuxConfig:
    channel: str
    root: Path
    data_directory: Path
    uid: int
    gid: int
    organization_id: str
    project_id: str

    @classmethod
    def load(cls, channel: str) -> LinuxConfig:
        if channel not in {'dev', 'test', 'prod'}:
            raise PostgresDeployError()
        data = _private_json(Path('/etc/yggdrasil/bws-deploy') / (channel + '.json'))
        if set(data) != {'root', 'data_directory', 'uid', 'gid', 'organization_id', 'project_id'}:
            raise PostgresDeployError()
        cfg = cls(channel, Path(data['root']), Path(data['data_directory']), data['uid'], data['gid'], data['organization_id'], data['project_id'])
        if (not cfg.root.is_absolute() or not cfg.data_directory.is_absolute()
            or cfg.root.is_symlink() or cfg.data_directory.is_symlink()
            or type(cfg.uid) is not int or type(cfg.gid) is not int or min(cfg.uid, cfg.gid) < 1
            or str(UUID(cfg.organization_id)) != cfg.organization_id or str(UUID(cfg.project_id)) != cfg.project_id):
            raise PostgresDeployError()
        return cfg

    @property
    def source_directory(self) -> Path:
        return Path('/run/yggdrasil/postgres') / self.channel

    @property
    def password_file(self) -> Path:
        return self.source_directory / 'password'

    @property
    def socket_path(self) -> Path:
        return Path('/run/yggdrasil/bws-deploy') / (self.channel + '.sock')

    @property
    def journal(self) -> DeployJournal:
        return DeployJournal(Path('/var/lib/yggdrasil/bws-deploy'), self.channel)

    def reader(self) -> BwsSecretReader:
        return BwsSecretReader(BwsReaderConfig.from_environment({
            **os.environ, 'BWS_READER_PROJECT': 'prod' if self.channel == 'prod' else 'non-prod',
            'BWS_ORGANIZATION_ID': self.organization_id, 'BWS_PROJECT_ID': self.project_id,
        }))


class PasswordSource:
    def __init__(self, config: LinuxConfig) -> None:
        self.config = config

    def materialize(self, value: str) -> None:
        cfg = self.config
        if os.geteuid() != 0:
            raise PostgresDeployError()
        # /run must really be tmpfs; never substitute a persistent temporary dir.
        _root_directory(cfg.source_directory)
        if _command(['stat', '-f', '-c', '%T', str(cfg.source_directory)]).strip() != 'tmpfs':
            raise PostgresDeployError()
        path = cfg.password_file
        if path.exists():
            self.verify()
            if path.read_bytes() != value.encode():
                # Replacing a bind mount's inode would strand running consumers
                # on a prior value. Rotation is deliberately not this operation.
                raise PostgresDeployError()
            return
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o440)
        try:
            os.fchown(fd, 0, cfg.gid)
            os.fchmod(fd, 0o440)
            raw = value.encode()
            if os.write(fd, raw) != len(raw):
                raise PostgresDeployError()
            os.fsync(fd)
        finally:
            os.close(fd)
        self.verify()

    def verify(self) -> None:
        cfg = self.config
        descriptor = os.open(cfg.password_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            directory = cfg.source_directory.stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != cfg.gid
                or stat.S_IMODE(info.st_mode) != 0o440 or info.st_nlink != 1
                or directory.st_uid != 0 or stat.S_IMODE(directory.st_mode) != 0o700):
                raise PostgresDeployError()
            # The inode is opened by root just as Docker opens the bind source.
            # Test read access using the actual service IDs on that inherited fd.
            result = subprocess.run([sys.executable, '-c',
                'import os,sys; f=os.open("/proc/self/fd/"+sys.argv[1],os.O_RDONLY); '
                'b=os.read(f,65537); sys.exit(0 if b and len(b)<=65536 else 1)', str(descriptor)],
                pass_fds=(descriptor,), user=cfg.uid, group=cfg.gid, extra_groups=[], capture_output=True, check=False)
            if result.returncode:
                raise PostgresDeployError()
        finally:
            os.close(descriptor)

    def cleanup(self, *, all_consumers_stopped: bool) -> None:
        if not all_consumers_stopped:
            raise PostgresDeployError()
        self.verify()
        self.config.password_file.unlink()


class LinuxEffects:
    def __init__(self, config: LinuxConfig) -> None:
        self.config = config
        self.source = PasswordSource(config)
        self.password: str | None = None
        self.consumer_values: dict[str, dict[str, str]] = {}
        self.lock_fd: int | None = None
        self.operation_id: str | None = None
        self.database_fields: dict[str, str] | None = None

    def environment(self) -> dict[str, str]:
        cfg = self.config
        env = dict(os.environ)
        # Refuse ambient password-bearing DSNs before invoking Compose.
        for key in ('DATABASE_URL', 'DB_DSN'):
            if env.get(key):
                credential_free_database_fields(env[key])
        if any(env.get(key) for key in ('POSTGRES_PASSWORD', 'PGPASSWORD', 'PGPASSFILE', 'PGSERVICE', 'PGSERVICEFILE')):
            raise PostgresDeployError()
        env.update(HOST_SECRET_PROVIDER='bws', BWS_POSTGRES_PASSWORD_SOURCE=str(cfg.password_file),
                   BWS_DATABASE_NAME={'dev': 'app_dev', 'test': 'app_test', 'prod': 'app'}[cfg.channel],
                   LOCAL_UID=str(cfg.uid), LOCAL_GID=str(cfg.gid),
                   BWS_DATABASE_VOLUME={'dev': 'pkm-dev_pgdata-dev', 'test': 'pkm-test_pgdata', 'prod': 'pkm-prod_pgdata'}[cfg.channel])
        # Reader credentials stay in the worker. Child programs get no token handle.
        env.pop('BWS_ACCESS_TOKEN', None)
        fields = effective_database_fields(cfg, env)
        if self.database_fields is not None and fields != self.database_fields:
            raise PostgresDeployError()
        self.database_fields = fields
        # Pass the same immutable, value-free target through every Compose call;
        # generated runtime values cannot override this environment snapshot.
        env['DATABASE_URL'] = env['DB_DSN'] = _database_url(fields)
        env['BWS_DATABASE_TARGET'] = database_target(fields)
        if env['BWS_DATABASE_TARGET'] == 'external':
            # No ambient profile can reintroduce the unrelated local DB/volume.
            env['COMPOSE_PROFILES'] = ''
        return env

    def compose(self, *args: str) -> str:
        cfg = self.config
        env = self.environment()
        overlays = ['-f', str(cfg.root / 'docker-compose.bws.yml')]
        if env['BWS_DATABASE_TARGET'] == 'external':
            overlays += ['-f', str(cfg.root / 'docker-compose.bws-external.yml')]
        return _command(['docker', 'compose', '--env-file', str(cfg.root / 'config/deploy' / (cfg.channel + '.env')),
            '-f', str(cfg.root / 'docker-compose.yaml'), '-f', str(cfg.root / ('docker-compose.' + cfg.channel + '.yml')),
            *overlays, '-p', 'pkm-' + cfg.channel, *args], cwd=cfg.root, env=env)

    def validate_plan(self, plan: DeployPlan) -> None:
        plan.validate()
        if (set(plan.services) != set(DATABASE_CONSUMERS.values())
            or set(plan.consumers) != {*DATABASE_CONSUMERS, 'heimdal-api-ingress', 'heimdal-capture-watch', 'heimdal-raw-migrate'}):
            raise PostgresDeployError()
        validate_database_inputs(os.environ, database_input_files(self.config))
        require_file_protocol(self.config.root, plan.revision)

    def preflight(self, plan: DeployPlan) -> str:
        self.validate_plan(plan)
        values = vm_selected_values(plan, self.config.reader())
        passwords = {value['postgres.password'] for consumer, value in values.items() if consumer in DATABASE_CONSUMERS}
        if len(passwords) != 1:
            raise PostgresDeployError()
        candidate = next(iter(passwords))
        if self.password is not None and candidate != self.password:
            raise PostgresDeployError()
        self.password = candidate
        self.consumer_values = values
        self.environment()
        return candidate

    def local_database(self) -> bool:
        self.environment()
        fields = self.database_fields or {}
        return database_target(fields) == 'local'

    def initialized(self) -> bool:
        cfg = self.config
        if not self.local_database():
            # Local PGDATA cannot prove an external target empty. Require actual
            # auth, forbid bootstrap, and never start/stop the unrelated local DB.
            return True
        # Inspect the actual existing named-volume source without creating one.
        volume = {'dev': 'pkm-dev_pgdata-dev', 'test': 'pkm-test_pgdata', 'prod': 'pkm-prod_pgdata'}[cfg.channel]
        observed = _command(['docker', 'volume', 'inspect', '--format', '{{.Mountpoint}}', volume]).strip()
        if Path(observed) != cfg.data_directory or not cfg.data_directory.is_dir():
            raise PostgresDeployError()
        existing = self.compose('ps', '--all', '-q', 'db').strip()
        if existing:
            if not re.fullmatch(r'[0-9a-f]{12,64}', existing):
                raise PostgresDeployError()
            mounts = json.loads(_command(['docker', 'inspect', '--format', '{{json .Mounts}}', existing]))
            selected = [mount for mount in mounts if mount.get('Destination') == '/var/lib/postgresql/data']
            if len(selected) != 1 or selected[0].get('Name') != volume or Path(selected[0].get('Source', '')) != cfg.data_directory:
                # Never redirect existing anonymous/test or foreign channel data.
                raise PostgresDeployError()
        entries = list(cfg.data_directory.iterdir())
        if not entries:
            # The image initializes only this exact role/database. A different
            # user, database, or connection option needs proof even on empty data.
            expected = {'host': 'db', 'port': '5432', 'user': 'app',
                        'dbname': {'dev': 'app_dev', 'test': 'app_test', 'prod': 'app'}[cfg.channel]}
            return self.database_fields != expected
        if not (cfg.data_directory / 'PG_VERSION').is_file():
            raise PostgresDeployError()
        return True

    def materialize(self, password: str) -> None:
        self.source.materialize(password)

    def database_running(self) -> bool:
        output = self.compose('ps', '--status', 'running', '-q', 'db').strip()
        if output and not re.fullmatch(r'[0-9a-f]{12,64}', output):
            raise PostgresDeployError()
        return bool(output)

    def start_database_only(self) -> None:
        self.source.verify()
        self.compose('up', '-d', '--wait', '--wait-timeout', '60', '--no-deps', 'db')

    def authenticate(self) -> None:
        cfg = self.config
        # Resolve through the same producer/alias boundary used by Compose, then
        # translate only the known Compose-db endpoint to its host-published port.
        # hostaddr preserves the original host for TLS identity verification.
        self.environment()
        fields = host_database_fields(self.database_fields or {},
                                      published_port={'dev': 15433, 'test': 15434, 'prod': 15432}[cfg.channel])
        password_authenticate({'DATABASE_PASSWORD_FILE': str(cfg.password_file),
                               'DATABASE_URL': _database_url(fields)})

    def stop_database(self) -> None:
        self.compose('stop', 'db')
        if self.database_running():
            raise PostgresDeployError()

    def activate(self, plan: DeployPlan) -> None:
        if self.lock_fd is None or set(plan.services) != set(DATABASE_CONSUMERS.values()):
            raise PostgresDeployError()
        self.source.verify()
        env = self.environment()
        env['BWS_DEPLOY_LOCK_FD'] = str(self.lock_fd)
        receipt = self.config.journal.read()
        if receipt is None or receipt.stage != 'activating':
            raise PostgresDeployError()
        env['BWS_DEPLOY_OPERATION_ID'] = receipt.operation_id
        # Only declared consumer bindings are handed to Compose, as private
        # tmpfs env-file handles. No value is copied to this process environment.
        from app.ops.host_secret_contract import load_host_secret_contract
        contract = load_host_secret_contract()
        paths = []
        handles = {'heimdal-api-ingress': 'HOST_SECRET_RUNTIME_ENV_FILE_API',
                   'heimdal-capture-watch': 'HOST_SECRET_RUNTIME_ENV_FILE',
                   'heimdal-raw-migrate': 'BWS_MIGRATE_SECRET_ENV_FILE'}
        try:
            for consumer, handle in handles.items():
                values = self.consumer_values.get(consumer)
                if values is None:
                    raise PostgresDeployError()
                path = self.config.source_directory / (consumer + '.env')
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                paths.append(path)
                with os.fdopen(descriptor, 'w') as stream:
                    for secret, value in values.items():
                        stream.write(contract.binding_for(secret) + '=' + value + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                env[handle] = str(path)
            # Existing deployment owns image, pin, migration and writer semantics.
            _command(['bash', str(self.config.root / 'scripts/deploy_channel.sh'), 'deploy', plan.channel, plan.revision],
                     cwd=self.config.root, env=env, pass_fds=(self.lock_fd,))
        finally:
            for path in paths:
                path.unlink()

    def quiescent(self) -> bool:
        # Called by the worker after each synchronous subprocess has been reaped.
        # Docker may still be restarting/starting after its CLI returns.
        try:
            rows = self.compose('ps', '--all', '--format', 'json').strip()
            if not rows:
                return True
            records = json.loads(rows) if rows.startswith('[') else [json.loads(line) for line in rows.splitlines()]
            return all(row.get('State') in {'running', 'exited', 'created'}
                       and row.get('Health') not in {'starting'} for row in records)
        except Exception:
            return False

    @contextmanager
    def channel_lock(self) -> Iterator[None]:
        import fcntl
        path = self.config.root / 'config/deploy' / (self.config.channel + '.env.lock')
        # Preserve the existing mkdir admission, including old non-BWS callers.
        path.mkdir(mode=0o700)
        descriptor = None
        try:
            descriptor = os.open(path / 'bws-owner', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lock_fd = descriptor
            yield
        finally:
            self.lock_fd = None
            if descriptor is not None:
                os.close(descriptor)
            receipt = self.config.journal.read()
            if receipt and receipt.operation_id == self.operation_id and receipt.terminal_result:
                (path / 'bws-owner').unlink()
                path.rmdir()
            # Pending or unreadable state retains the mkdir lock as a durable
            # admission refusal. Never clear it merely because this thread ended.


class SupervisedOperation:
    """One thread per same-ID request; SSH disconnects cannot cancel its effects."""
    def __init__(self, effects: LinuxEffects, operation_id: str, plan: DeployPlan, bootstrap: bool) -> None:
        self.effects, self.operation_id, self.plan, self.bootstrap = effects, operation_id, plan, bootstrap
        self.effects.operation_id = operation_id
        self.ready = threading.Event()
        self.activation = threading.Event()
        self.finished = threading.Event()
        self.empty = False
        self.failed = False
        self.thread = threading.Thread(target=self._run, daemon=False)

    def _run_locked(self) -> None:
        previous = self.effects.config.journal.read()
        if previous and previous.terminal_result is None:
            raise PostgresDeployError()
        self.effects.validate_plan(self.plan)
        self.effects.config.journal.bind_request(self.operation_id, self.plan, self.bootstrap, create=True)
        worker = DeployWorker(self.effects.config.journal, self.effects)
        # Coordination only: no pins, writers, volumes or Docker mutation.
        worker.prepare(self.operation_id)
        if self.bootstrap:
            reader = self.effects.config.reader()
            from app.ops.host_secret_bootstrap import _resolve_bws_consumer_values
            from app.ops.host_secret_contract import load_host_secret_contract
            for consumer in self.plan.consumers:
                if consumer not in DATABASE_CONSUMERS:
                    _resolve_bws_consumer_values(self.plan.channel, consumer, load_host_secret_contract(), reader)
            if self.effects.initialized():
                raise PostgresDeployError()
            self.empty = True
        else:
            self.effects.preflight(self.plan)
        self.ready.set()
        self.activation.wait()
        worker.run(self.operation_id, self.plan)

    def _run(self) -> None:
        try:
            with self.effects.channel_lock():
                try:
                    self._run_locked()
                except Exception:
                    self.failed = True
                    receipt = self.effects.config.journal.read()
                    if (receipt and receipt.operation_id == self.operation_id
                        and receipt.stage == 'prepared' and self.effects.quiescent()):
                        self.effects.config.journal.write(self.operation_id, 'aborted')
                    # Terminal write remains under the lock, before its cleanup.
        except Exception:
            self.failed = True
        finally:
            self.ready.set()
            self.finished.set()

    def result(self) -> dict[str, Any]:
        receipt = self.effects.config.journal.read()
        if receipt and receipt.operation_id == self.operation_id and receipt.terminal_result:
            return {'receipt': asdict(receipt)}
        if self.failed:
            raise PostgresDeployError()
        return {'pending': True, 'empty': self.empty, 'ready': self.ready.is_set()}


class DeploymentSupervisor:
    def __init__(self, config: LinuxConfig) -> None:
        self.config = config
        self.operation: SupervisedOperation | None = None
        self.mutex = threading.Lock()

    def request(self, data: dict[str, Any]) -> dict[str, Any]:
        if set(data) != {'action', 'operation_id', 'plan', 'bootstrap'}:
            raise PostgresDeployError()
        operation_id = str(data['operation_id'])
        if str(UUID(operation_id)) != operation_id or type(data['bootstrap']) is not bool:
            raise PostgresDeployError()
        raw = data['plan']
        plan = DeployPlan(raw['channel'], raw['revision'], tuple(raw['services']), tuple(raw['consumers']))
        plan.validate()
        if plan.channel != self.config.channel or data['action'] not in {'prepare', 'activate', 'join'}:
            raise PostgresDeployError()
        with self.mutex:
            previous = self.config.journal.read()
            if previous and previous.operation_id == operation_id and previous.terminal_result:
                self.config.journal.bind_request(operation_id, plan, data['bootstrap'])
                return {'receipt': asdict(previous)}
            if self.operation and self.operation.operation_id != operation_id:
                if not self.operation.finished.is_set():
                    raise PostgresDeployError()
                self.operation = None
            if self.operation is None:
                # A daemon loss without a receipt never authorizes another worker.
                # Only a new operation with no pending predecessor can be created.
                if data['action'] != 'prepare' or (previous and previous.terminal_result is None):
                    raise PostgresDeployError()
                self.operation = SupervisedOperation(LinuxEffects(self.config), operation_id, plan, data['bootstrap'])
                self.operation.thread.start()
            operation = self.operation
            if operation.plan != plan or operation.bootstrap != data['bootstrap']:
                raise PostgresDeployError()
            if data['action'] == 'activate':
                if not operation.ready.is_set() or operation.failed:
                    raise PostgresDeployError()
                operation.activation.set()
        if data['action'] == 'prepare':
            operation.ready.wait(25)
        else:
            operation.finished.wait(25)
        return operation.result()


def serve(config: LinuxConfig) -> None:
    if os.geteuid() != 0 or sys.platform != 'linux':
        raise PostgresDeployError()
    _root_directory(config.socket_path.parent)
    import fcntl
    singleton = os.open(config.socket_path.with_suffix('.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(singleton, fcntl.LOCK_EX | fcntl.LOCK_NB)
    supervisor = DeploymentSupervisor(config)

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            try:
                raw = self.rfile.readline(65537)
                if not raw.endswith(b'\n') or len(raw) > 65536:
                    raise PostgresDeployError()
                result = supervisor.request(json.loads(raw))
            except Exception:
                result = {'refused': True}
            self.wfile.write((json.dumps(result, sort_keys=True) + '\n').encode())

    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True

    # systemd is the singleton owner. A leftover socket may be removed only once
    # that unit's old process/cgroup has ended; systemd guarantees this on restart.
    if config.socket_path.exists():
        config.socket_path.unlink()
    previous_umask = os.umask(0o077)
    try:
        with Server(str(config.socket_path), Handler) as server:
            os.chmod(config.socket_path, 0o600)
            server.serve_forever()
    finally:
        os.umask(previous_umask)
        os.close(singleton)


def rpc(channel: str, request: dict[str, Any]) -> dict[str, Any]:
    if channel not in {'dev', 'test', 'prod'} or os.geteuid() != 0:
        raise PostgresDeployError()
    path = Path('/run/yggdrasil/bws-deploy') / (channel + '.sock')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(35)
        connection.connect(str(path))
        with connection.makefile('rwb') as stream:
            stream.write((json.dumps(request) + '\n').encode())
            stream.flush()
            raw = stream.readline(65537)
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get('refused'):
        raise PostgresDeployError()
    return result


class SshDeployRemote:
    def __init__(self, host: str) -> None:
        # Host alias only: no options, shell syntax, or user-supplied command.
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}', host):
            raise PostgresDeployError()
        self.host = host
        self.bootstrap = False

    def _request(self, action: str, operation_id: str, plan: DeployPlan) -> dict[str, Any]:
        request = {'action': action, 'operation_id': operation_id, 'plan': asdict(plan), 'bootstrap': self.bootstrap}
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '--', self.host,
            'sudo', '-n', '/usr/local/libexec/yggdrasil-bws-deploy', 'rpc', plan.channel],
            input=json.dumps(request) + '\n', text=True, capture_output=True, check=False)
        if result.returncode:
            raise PostgresDeployError()
        response = json.loads(result.stdout)
        if not isinstance(response, dict) or response.get('refused'):
            raise PostgresDeployError()
        return response

    def prepare(self, operation_id: str, plan: DeployPlan, *, bootstrap: bool) -> bool:
        self.bootstrap = bootstrap
        response = self._request('prepare', operation_id, plan)
        if 'receipt' in response:
            return False
        if not response.get('ready'):
            raise PostgresDeployError()
        return response.get('empty') is True

    def _terminal(self, action: str, operation_id: str, plan: DeployPlan) -> DeployReceipt:
        # Each RPC waits inside the supervised VM operation. No process/SHA polling
        # or host-side timeout turns a pending operation into a terminal result.
        response = self._request(action, operation_id, plan)
        while response.get('pending'):
            response = self._request('join', operation_id, plan)
        receipt = DeployReceipt(**response['receipt'])
        receipt.validate()
        if receipt.operation_id != operation_id or receipt.channel != plan.channel:
            raise PostgresDeployError()
        return receipt

    def activate(self, operation_id: str, plan: DeployPlan) -> DeployReceipt:
        return self._terminal('activate', operation_id, plan)

    def join(self, operation_id: str, plan: DeployPlan) -> DeployReceipt:
        return self._terminal('join', operation_id, plan)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('serve', 'rpc', 'guard', 'cleanup'))
    parser.add_argument('channel', choices=('dev', 'test', 'prod'))
    parser.add_argument('--compose-command')
    args = parser.parse_args(argv)
    try:
        if args.action == 'serve':
            serve(LinuxConfig.load(args.channel))
        elif args.action == 'guard':
            inherited_worker_guard(args.channel, args.compose_command)
        elif args.action == 'cleanup':
            effects = LinuxEffects(LinuxConfig.load(args.channel))
            running = effects.compose('ps', '--status', 'running', '-q', *DATABASE_CONSUMERS.values()).strip()
            if not running and effects.quiescent() and effects.config.password_file.exists():
                effects.source.cleanup(all_consumers_stopped=True)
        else:
            request = json.load(sys.stdin)
            result = rpc(args.channel, request)
            print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print('database deployment refused; operation remains pending', file=sys.stderr)
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
