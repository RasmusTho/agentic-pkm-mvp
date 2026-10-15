"""Linux effects for BWS-04. The supervised server owns worker lifetime, not SSH.

All command output is captured and discarded unless it is a validated identifier,
status, or finite advisory deploy failure stage. The root-owned configuration and
Unix socket are operator-installed;
there is no credential-valued environment, command argument, or status response.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import pwd
import re
import signal
import socket
import socketserver
import stat
import subprocess
import sys
import threading
from typing import Any, Iterator
from uuid import UUID, uuid4
from urllib.parse import urlencode, quote

from app.config.database import credential_free_database_fields, host_database_fields
from app.ops.bws_secret_reader import BwsReaderConfig, BwsSecretReader
from app.ops.host_secret_contract import DATABASE_CONSUMERS
from app.ops.native_web_acceptance import NativeWebRefusal, WEB_PROFILE
from app.ops.postgres_deploy import (
    AuthorityCutover, DeployJournal, DeployPlan, DeployReceipt, DeployWorker, PostgresDeployError,
    password_authenticate, vm_selected_values,
)

_ONE_SHOT_COMPOSE_SERVICES = frozenset({'instance-state-init', 'migrate'})
_CUTOVER_ENV = ('MVR01C_ROLLBACK_VAULT_BINDING_ID', 'MVR01C_ROLLBACK_VAULT_ROOT')
_DEPLOY_JOURNAL_SOCKET = '/run/systemd/journal/socket'
_DEPLOY_FAILURE_STAGES = frozenset({
    'preflight', 'runtime_identity', 'model_access', 'migration_inventory',
    'migration_ack', 'runtime_prepare', 'pin_write', 'image_pull',
    'scalar_retirement', 'instance_prepare', 'migration_apply', 'source_projection', 'service_recreate',
    'scalar_runtime', 'embedding_configuration', 'health', 'version',
    'fleet_fitness', 'ui_smoke', 'capture_watch', 'receipt',
})
_SOURCE_PROJECTION_FAILURE_REASONS = frozenset({
    'legacy_producer_policy_refused', 'legacy_source_refused', 'legacy_admission_refused',
    'legacy_identity_refused', 'legacy_race_refused', 'legacy_write_failed',
    'legacy_identity_persistence_refused', 'legacy_identity_mismatch_refused',
    'legacy_identity_ambiguous_refused', 'legacy_identity_producer_refused',
    'legacy_identity_canonical_refused',
    'legacy_candidate_refused', 'legacy_authority_refused', 'legacy_trust_refused',
    'legacy_origin_refused', 'legacy_payload_shape_refused', 'legacy_system_path_refused',
    'legacy_profile_refused', 'legacy_dependency_shape_refused',
    'legacy_retained_history_refused', 'legacy_relation_retention_refused',
    'vector_projection_failed', 'embedding_generation_failed', 'vector_index_write_failed',
    'source_preflight_failed', 'source_readiness_failed', 'source_command_failed',
    'source_summary_invalid', 'source_post_rebuild_failed', 'source_doctor_failed',
    'source_settings_failed', 'source_worker_failed', 'source_quiescence_failed',
    'source_writer_stop_failed', 'embedding_context_invalid',
    'embedding_identity_unavailable', 'embedding_identity_invalid',
    'embedding_service_unavailable', 'embedding_service_not_ready',
    'embedding_model_unavailable', 'embedding_model_not_ready', 'embedding_probe_failed',
    'source_worker_timeout', 'source_worker_terminated', 'source_worker_oom',
})
_GUARD_FAILURE_CHECKPOINTS = frozenset({
    'config_runtime_file_binding', 'inherited_owner_fd_inode_flock',
    'active_journal_operation', 'selector_shape_capture_raw_migration',
    'selected_image_file_protocol', 'database_target_binding',
    'password_source_read', 'credential_free_database_input',
    'selected_bws_consumer_scope', 'password_equality',
    'authority_request_binding',
})


def _deploy_failure_stage(stderr: str) -> str:
    prefix = 'YGGDRASIL_DEPLOY_FAILURE_STAGE='
    markers = [line.removeprefix(prefix) for line in stderr.splitlines() if prefix in line]
    # Ambiguous, malformed, or injected markers never produce free text.
    if len(markers) == 1 and markers[0] in _DEPLOY_FAILURE_STAGES:
        return markers[0]
    return 'unknown'


def _emit_native_diagnostic(payload: bytes) -> None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as journal:
            journal.setblocking(False)
            journal.sendto(payload, _DEPLOY_JOURNAL_SOCKET)
    except OSError:
        # Diagnostics are advisory; absence, refusal or queue pressure must not
        # delay recovery or replace the original deployment failure/authority.
        pass


def _deploy_failure_reason(stderr: str, stage: str) -> str:
    prefix = 'YGGDRASIL_DEPLOY_FAILURE_REASON='
    markers = [line.removeprefix(prefix) for line in stderr.splitlines() if prefix in line]
    if stage == 'source_projection' and len(markers) == 1 and markers[0] in _SOURCE_PROJECTION_FAILURE_REASONS:
        return markers[0]
    return 'command_failed'


def record_source_terminal(channel: str, name: str, status: int) -> int:
    """Retain exact operation evidence before destructive one-shot cleanup."""
    from app.ops.native_source_bootstrap import (
        SOURCE_PROJECTION_FAILURE_CODES, quiesce_owned_container, source_terminal_reason,
    )
    inherited_worker_guard(channel)
    cfg = LinuxConfig.load(channel)
    operation = os.environ['BWS_DEPLOY_OPERATION_ID']
    revision = os.environ['BWS_DEPLOY_TARGET_REVISION']
    if type(status) is not int or not 0 <= status <= 255:
        raise PostgresDeployError()
    observed = False
    reason = source_terminal_reason(status)

    def retain(exit_status: int, oom: bool) -> None:
        nonlocal reason, observed
        # The supervisor's timeout/signal is authoritative even when Docker's
        # child acknowledged TERM with zero. OOM is admitted only from Docker.
        effective = status if status in {124, 130, 143} else exit_status or status
        reason = source_terminal_reason(effective, oom_killed=oom)
        if reason is not None:
            cfg.journal.record_source_failure(operation, revision, reason)
        observed = True

    if not quiesce_owned_container(channel, name, operation, revision, observe_terminal=retain):
        raise PostgresDeployError()
    if not observed:
        # No container was created (or it is already absent). Retain only the
        # supervised fixed status; absence alone is not proof of success.
        if status == 0:
            raise PostgresDeployError()
        retain(status, False)
    return SOURCE_PROJECTION_FAILURE_CODES[reason] if reason else 0


def _emit_deploy_failure(stage: str, reason: str = 'command_failed') -> None:
    # The service deliberately nulls both raw streams. Only these fixed fields
    # reach the existing native journal; no captured text or caller metadata does.
    if stage not in _DEPLOY_FAILURE_STAGES:
        stage = 'unknown'
    if stage != 'source_projection' or reason not in _SOURCE_PROJECTION_FAILURE_REASONS:
        reason = 'command_failed'
    payload = (
        'PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n'
        f'MESSAGE=native deployment failure: stage={stage} class={reason}\n'
    ).encode('ascii')
    _emit_native_diagnostic(payload)


def _emit_pg_deadline() -> None:
    _emit_native_diagnostic(
        b'PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n'
        b'MESSAGE=native PG acceptance failure: reason=profile_deadline_exceeded\n'
    )


def _guard_failure_checkpoint(value: object) -> str:
    if isinstance(value, str) and value in _GUARD_FAILURE_CHECKPOINTS:
        return value
    return 'unknown'


def _emit_guard_failure(checkpoint: object) -> None:
    # Only fixed checkpoint names reach the existing native journal. The guard
    # exception, traceback, locals, and caller inputs never enter this payload.
    safe_checkpoint = _guard_failure_checkpoint(checkpoint)
    payload = (
        'PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n'
        f'MESSAGE=native deployment failure: checkpoint={safe_checkpoint} class=guard_refused\n'
    ).encode('ascii')
    _emit_native_diagnostic(payload)


@contextmanager
def _guard_failure_boundary() -> Iterator[dict[str, str]]:
    checkpoint = {'name': 'config_runtime_file_binding'}
    try:
        yield checkpoint
    except Exception:
        _emit_guard_failure(checkpoint.get('name'))
        raise


def _command(argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
             pass_fds: tuple[int, ...] = (), deploy_diagnostics: bool = False,
             timeout: int | None = None) -> str:
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, pass_fds=pass_fds, capture_output=True,
                                text=True, errors='replace' if deploy_diagnostics else 'strict',
                                check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PostgresDeployError() from None
    if result.returncode:
        if deploy_diagnostics:
            stage = _deploy_failure_stage(result.stderr)
            _emit_deploy_failure(stage, _deploy_failure_reason(result.stderr, stage))
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


def _runtime_env_file_path(value: Any) -> Path:
    """Validate the configured BWS runtime env as an absolute regular file."""
    try:
        raw_path = os.fspath(value)
    except TypeError:
        raise PostgresDeployError() from None
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
        raise PostgresDeployError()
    path = Path(raw_path)
    if not path.is_absolute():
        raise PostgresDeployError()
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise PostgresDeployError()
    except (OSError, ValueError):
        raise PostgresDeployError() from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return path


def database_input_files(cfg: LinuxConfig) -> list[Path]:
    from scripts.compose_env import compose_env_value
    pin = cfg.root / 'config/deploy' / (cfg.channel + '.env')
    configured_runtime = getattr(cfg, 'runtime_env_file', None)
    if configured_runtime is not None:
        return [pin, _runtime_env_file_path(configured_runtime)]
    runtime = './tmp-test/runtime.env' if cfg.channel == 'test' else './tmp/runtime.env'
    try:
        lines = pin.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        lines = []
    except (OSError, UnicodeError):
        raise PostgresDeployError() from None
    for line in lines:
        if line.startswith('WATCHER_RUNTIME_ENV_FILE='):
            selected_runtime = compose_env_value(line.split('=', 1)[1])
            if selected_runtime:
                runtime = selected_runtime
            # Match deploy_channel_compose.sh::_deploy_channel_env_value,
            # which deliberately resolves the first declaration and falls
            # back to the channel default when its value is empty.
            break
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
    with _guard_failure_boundary() as checkpoint:
        checkpoint['name'] = 'config_runtime_file_binding'
        cfg = LinuxConfig.load(channel)
        runtime_env_file = _runtime_env_file_path(cfg.runtime_env_file)
        if os.environ.get('BWS_DEPLOY_RUNTIME_ENV_FILE') != str(runtime_env_file):
            raise PostgresDeployError()
        checkpoint['name'] = 'inherited_owner_fd_inode_flock'
        descriptor = int(os.environ['BWS_DEPLOY_LOCK_FD'])
        expected = cfg.root / 'config/deploy' / (channel + '.env.lock') / 'bws-owner'
        info, held = expected.lstat(), os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or (held.st_dev, held.st_ino) != (info.st_dev, info.st_ino):
            raise PostgresDeployError()
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        checkpoint['name'] = 'active_journal_operation'
        receipt = cfg.journal.read()
        if receipt is None or receipt.stage != 'activating' or receipt.operation_id != os.environ.get('BWS_DEPLOY_OPERATION_ID'):
            raise PostgresDeployError()
        checkpoint['name'] = 'authority_request_binding'
        bound_plan = cfg.journal.bound_plan(receipt.operation_id)
        cutover = bound_plan.authority_cutover
        expected_cutover = (cutover.binding_id, cutover.root) if cutover else ('', '')
        if tuple(os.environ.get(key, '') for key in _CUTOVER_ENV) != expected_cutover:
            raise PostgresDeployError()
        if cutover and os.environ.get('INSTANCE_OWNERSHIP_HOST_STATE_DIR') != cutover.ownership_root:
            raise PostgresDeployError()
        if cutover:
            require_cutover_target_config(cfg, cutover)
        checkpoint['name'] = 'selector_shape_capture_raw_migration'
        expected_capture = os.environ.get('BWS_EXPECTED_CAPTURE_WATCH_CONFIGURED')
        expected_migration = os.environ.get('BWS_EXPECTED_RAW_MIGRATION_PENDING')
        target_revision = os.environ.get('BWS_DEPLOY_TARGET_REVISION', '')
        if (expected_capture not in {'0', '1'} or expected_migration not in {'0', '1'}
            or not re.fullmatch(r'[0-9a-f]{40}', target_revision)):
            raise PostgresDeployError()
        if cutover and target_revision != bound_plan.revision:
            raise PostgresDeployError()
        # The worker selected these consumers before any deployment mutation. Check
        # capture config again for every Compose call. Before the shell runs its
        # migration gate, independently derive HAR-02 from the current pin/marker;
        # afterward, require the shell's gate result to match the immutable choice.
        if _capture_watch_configured(cfg) != (expected_capture == '1'):
            raise PostgresDeployError()
        actual_capture = os.environ.get('DEPLOY_CAPTURE_WATCH_CONFIGURED')
        if actual_capture is not None and actual_capture != expected_capture:
            raise PostgresDeployError()
        actual_migration = os.environ.get('DEPLOY_HEIMDAL_RAW_MIGRATION_PENDING')
        if actual_migration is None:
            migration_pending = _raw_representation_migration_pending(cfg, target_revision)
        elif actual_migration in {'0', '1'}:
            migration_pending = actual_migration == '1'
        else:
            raise PostgresDeployError()
        if migration_pending != (expected_migration == '1'):
            raise PostgresDeployError()
        if compose_command in {'up', 'run', 'start', 'restart'}:
            checkpoint['name'] = 'selected_image_file_protocol'
            # Automatic rollback may restore an older pin. It cannot recreate clients
            # from a legacy image that bypasses the file-aware resolver.
            from scripts.compose_env import compose_env_value
            pin = cfg.root / 'config/deploy' / (channel + '.env')
            revisions = [compose_env_value(line.split('=', 1)[1]) for line in pin.read_text().splitlines()
                         if line.startswith('APP_IMAGE_TAG=')]
            if len(revisions) != 1:
                raise PostgresDeployError()
            require_file_protocol(cfg.root, revisions[0])
        checkpoint['name'] = 'database_target_binding'
        target = database_target(effective_database_fields(cfg, os.environ))
        if os.environ.get('BWS_DATABASE_TARGET') != target or (target == 'external' and os.environ.get('COMPOSE_PROFILES')):
            raise PostgresDeployError()
        checkpoint['name'] = 'password_source_read'
        PasswordSource(cfg).verify()
        checkpoint['name'] = 'credential_free_database_input'
        validate_database_inputs(os.environ, database_input_files(cfg))
        checkpoint['name'] = 'selected_bws_consumer_scope'
        # Recheck the same selected scope before every Compose call, including
        # calls made by the preserved migration/pin/rollback machinery.
        consumers = [*DATABASE_CONSUMERS, 'heimdal-api-ingress']
        if expected_capture == '1':
            consumers.append('heimdal-capture-watch')
        if expected_migration == '1':
            consumers.append('heimdal-raw-migrate')
        plan = DeployPlan(channel, target_revision, tuple(DATABASE_CONSUMERS.values()), tuple(consumers))
        values = vm_selected_values(plan, cfg.reader())
        checkpoint['name'] = 'password_equality'
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
    runtime_env_file: Path | None = None

    @classmethod
    def load(cls, channel: str, *, require_runtime_env: bool = True) -> LinuxConfig:
        if channel not in {'dev', 'test', 'prod'}:
            raise PostgresDeployError()
        data = _private_json(Path('/etc/yggdrasil/bws-deploy') / (channel + '.json'))
        base_keys = {'root', 'data_directory', 'uid', 'gid', 'organization_id', 'project_id'}
        runtime_env_key = 'runtime_env_file'
        data_keys = frozenset(data)
        if data_keys not in {frozenset(base_keys), frozenset((*base_keys, runtime_env_key))}:
            raise PostgresDeployError()
        if require_runtime_env and runtime_env_key not in data:
            raise PostgresDeployError()
        runtime_env_file = None
        if require_runtime_env:
            runtime_env_file = _runtime_env_file_path(data[runtime_env_key])
        cfg = cls(
            channel,
            Path(data['root']),
            Path(data['data_directory']),
            data['uid'],
            data['gid'],
            data['organization_id'],
            data['project_id'],
            runtime_env_file,
        )
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


def _runtime_user_ownership_state_dir(runtime_uid: int, xdg_state_home: str | None = None) -> Path:
    """Return the canonical host-global state default for the Compose user.

    The root BWS supervisor cannot use its own HOME for state owned by the
    non-root Compose identity, so it derives that path from the runtime UID.
    Non-root callers keep their own HOME default. An explicitly configured XDG
    state root takes precedence for either caller.
    """
    if xdg_state_home:
        return Path(xdg_state_home) / 'agentic-pkm' / 'instance-ownership'
    if type(runtime_uid) is not int or runtime_uid < 0:
        raise PostgresDeployError()
    if os.geteuid() == 0:
        try:
            home = Path(pwd.getpwuid(runtime_uid).pw_dir)
        except (KeyError, OSError):
            raise PostgresDeployError() from None
    else:
        home = Path(os.environ.get('HOME', ''))
    if not home.is_absolute() or home == Path('/'):
        raise PostgresDeployError()
    return home / '.local' / 'state' / 'agentic-pkm' / 'instance-ownership'


_BASE_DEPLOY_CONSUMERS = frozenset((*DATABASE_CONSUMERS, 'heimdal-api-ingress'))


def require_existing_authority_binding(data: dict[str, Any]) -> None:
    """Runtime-UID read-only proof; never restore, initialize or select a vault."""
    from app.instance.runtime import require_existing_authority_cutover_ready

    selected = AuthorityCutover(**data['selection'])
    selected.validate()
    require_existing_authority_cutover_ready(
        channel_id=data['channel'],
        registry_path=Path(data['registry_path']),
        host_global_root=Path(selected.ownership_root),
        vault_binding_id=selected.binding_id,
        vault_root=Path(selected.root),
    )


def require_cutover_target_config(config: LinuxConfig, selected: AuthorityCutover) -> None:
    """Match the shell's pin-before-runtime selected source, without selecting it."""
    from scripts.compose_env import compose_env_value

    sources = []
    for path in database_input_files(config):
        values: dict[str, str] = {}
        for line in path.read_text(encoding='utf-8').splitlines():
            key, separator, value = line.partition('=')
            if separator and key in {'VAULT_HOST_ROOT', 'VAULT_ROOT', 'VAULT_ROOT_' + config.channel.upper(),
                                     'WATCHER_VAULT_PATH', 'INSTANCE_OWNERSHIP_HOST_STATE_DIR'}:
                if key in values:
                    raise PostgresDeployError()
                values[key] = compose_env_value(value)
        sources.append(values)
    root = sources[0].get('VAULT_HOST_ROOT') or sources[1].get('VAULT_HOST_ROOT')
    if root != selected.root:
        raise PostgresDeployError()
    for values in sources:
        if any(value and value not in {selected.root, '/app/vault'} for key, value in values.items()
               if key in {'VAULT_ROOT', 'VAULT_ROOT_' + config.channel.upper(), 'WATCHER_VAULT_PATH'}):
            raise PostgresDeployError()
        owner = values.get('INSTANCE_OWNERSHIP_HOST_STATE_DIR')
        if owner and owner != selected.ownership_root:
            raise PostgresDeployError()


def _git_bytes(root: Path, *args: str) -> bytes:
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=False)
    if result.returncode:
        raise PostgresDeployError()
    return result.stdout


def _capture_watch_configured(config: LinuxConfig) -> bool:
    """Mirror deploy_channel.sh's fail-closed runtime-file selection."""
    from scripts.compose_env import compose_env_value

    runtime_path = database_input_files(config)[1]
    try:
        runtime_path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        raise PostgresDeployError() from None
    if not runtime_path.is_file() or not os.access(runtime_path, os.R_OK):
        raise PostgresDeployError()
    try:
        lines = runtime_path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        raise PostgresDeployError() from None
    values = [line[len('HEIMDAL_CAPTURE_WATCH_DIR='):]
              for line in lines if line.startswith('HEIMDAL_CAPTURE_WATCH_DIR=')]
    if len(values) > 1:
        raise PostgresDeployError()
    return bool(values and compose_env_value(values[0]).strip())


def _pin_value(config: LinuxConfig, key: str) -> str:
    pin = config.root / 'config/deploy' / (config.channel + '.env')
    try:
        lines = pin.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return ''
    except (OSError, UnicodeError):
        raise PostgresDeployError() from None
    values = [line[len(key) + 1:] for line in lines if line.startswith(key + '=')]
    if len(values) > 1:
        raise PostgresDeployError()
    return values[0] if values else ''


def _migration_baseline(config: LinuxConfig, target_revision: str, *, automatic: bool = False) -> str:
    """Use the deploy script's pending marker or current pin as migration base."""
    pending = config.root / 'config/deploy' / (config.channel + '.migration-pending.env')
    try:
        info = pending.lstat()
        if not stat.S_ISREG(info.st_mode) or pending.is_symlink():
            raise PostgresDeployError()
    except FileNotFoundError:
        current = _pin_value(config, 'APP_IMAGE_TAG')
        return current
    except OSError:
        raise PostgresDeployError() from None
    try:
        lines = pending.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        raise PostgresDeployError() from None
    fields: dict[str, str] = {}
    for line in lines:
        if '=' not in line:
            raise PostgresDeployError()
        key, value = line.split('=', 1)
        if key not in {'FROM_SHA', 'TARGET_SHA', 'ACK_FORWARD_ONLY'} or key in fields:
            raise PostgresDeployError()
        fields[key] = value
    if set(fields) != {'FROM_SHA', 'TARGET_SHA', 'ACK_FORWARD_ONLY'}:
        raise PostgresDeployError()
    if fields['TARGET_SHA'] != target_revision or fields['ACK_FORWARD_ONLY'] not in {'0', '1'}:
        raise PostgresDeployError()
    if automatic and fields['ACK_FORWARD_ONLY'] == '1':
        raise PostgresDeployError()
    if fields['FROM_SHA'] == '__NO_BASELINE__':
        return ''
    return fields['FROM_SHA']


def _raw_representation_migration_pending(config: LinuxConfig, target_revision: str,
                                         *, automatic: bool = False) -> bool:
    """Select the same changed migration set and HAR-02 predicate as deploy_channel.sh."""
    from app.release_channels.reversibility import (
        HEIMDAL_RAW_REPRESENTATION_MIGRATION,
        check_migration_snapshots,
        heimdal_raw_representation_migration_pending,
    )

    baseline = (_migration_baseline(config, target_revision, automatic=True)
                if automatic else _migration_baseline(config, target_revision))
    has_baseline = bool(baseline) and subprocess.run(
        ['git', '-C', str(config.root), 'rev-parse', '--verify', baseline + '^{commit}'],
        capture_output=True, check=False,
    ).returncode == 0
    if has_baseline:
        paths = _git_bytes(config.root, 'diff', '--diff-filter=AMCR', '--name-only',
                           baseline + '..' + target_revision, '--', 'app/alembic/versions')
    else:
        paths = _git_bytes(config.root, 'ls-tree', '-r', '--name-only', target_revision,
                           '--', 'app/alembic/versions')
    snapshots = []
    for raw_path in paths.decode('utf-8').splitlines():
        if not raw_path.endswith('.py'):
            continue
        name = Path(raw_path).name
        snapshots.append((name, _git_bytes(config.root, 'show', target_revision + ':' + raw_path)))
    receipt = check_migration_snapshots(snapshots)
    pending = heimdal_raw_representation_migration_pending(receipt)
    if pending and HEIMDAL_RAW_REPRESENTATION_MIGRATION not in {
        name for name, _content in snapshots
    }:
        raise PostgresDeployError()
    return pending


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


def ensure_candidate_object(config: LinuxConfig, revision: str) -> None:
    """Fetch only missing public candidate objects; never switch host tooling.

    The native channel lock is already held. Candidate SHA admission remains
    upstream; Git's content identity supplies the exact code/migration snapshots.
    No deployment or GitHub credential is inherited by this public fetch.
    """
    environment = {key: os.environ[key] for key in ('HOME', 'USER', 'LOGNAME', 'PATH') if key in os.environ}
    environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
    command = ['git', '-c', 'safe.directory=' + str(config.root), '-C', str(config.root),
               'cat-file', '-e', revision + '^{commit}']
    if subprocess.run(command, env=environment, capture_output=True, check=False).returncode == 0:
        return
    fetched = subprocess.run([
        'git', '-c', 'credential.helper=', '-c', 'safe.directory=' + str(config.root),
        '-C', str(config.root), 'fetch',
        '--no-tags', '--no-write-fetch-head', 'https://github.com/RasmusTho/agentic-pkm-mvp.git', revision,
    ], env=environment, capture_output=True, timeout=60, check=False)
    if fetched.returncode or subprocess.run(command, env=environment, capture_output=True, check=False).returncode:
        raise PostgresDeployError()


class LinuxEffects:
    def __init__(self, config: LinuxConfig) -> None:
        self.config = config
        self.source = PasswordSource(config)
        self.password: str | None = None
        self.consumer_values: dict[str, dict[str, str]] = {}
        self.lock_fd: int | None = None
        self.operation_id: str | None = None
        self.database_fields: dict[str, str] | None = None
        self.active_consumers: tuple[str, ...] | None = None
        self.active_revision: str | None = None
        self.capture_watch_configured: bool | None = None
        self.raw_migration_pending: bool | None = None

    def environment(self, cutover: AuthorityCutover | None = None) -> dict[str, str]:
        cfg = self.config
        runtime_env_file = database_input_files(cfg)[1]
        env = dict(os.environ)
        # Native authority is never inherited from the supervisor or shell.
        for key in _CUTOVER_ENV:
            env.pop(key, None)
        if cutover is not None:
            if env.get('DOCKER_HOST', 'unix:///var/run/docker.sock') != 'unix:///var/run/docker.sock' or env.get('DOCKER_CONTEXT'):
                raise PostgresDeployError()
            env['INSTANCE_OWNERSHIP_HOST_STATE_DIR'] = cutover.ownership_root
        # Refuse ambient password-bearing DSNs before invoking Compose.
        for key in ('DATABASE_URL', 'DB_DSN'):
            if env.get(key):
                credential_free_database_fields(env[key])
        if any(env.get(key) for key in ('POSTGRES_PASSWORD', 'PGPASSWORD', 'PGPASSFILE', 'PGSERVICE', 'PGSERVICEFILE')):
            raise PostgresDeployError()
        # The systemd supervisor has HOME=/root, but the host-global ledger is
        # owned and traversed by the configured non-root Compose identity. Keep
        # the same default path as a deploy run by that identity; an explicit
        # XDG root or host override remains authoritative and is validated by
        # the shell.
        if not env.get('INSTANCE_OWNERSHIP_HOST_STATE_DIR'):
            env['INSTANCE_OWNERSHIP_HOST_STATE_DIR'] = str(
                _runtime_user_ownership_state_dir(cfg.uid, env.get('XDG_STATE_HOME'))
            )
        # The installed supervisor runtime also owns the shell's Python helpers
        # and inherited guard; an ambient PYTHON cannot select a different host runtime.
        runtime_bin = Path(sys.executable).parent
        env.update(PYTHON=sys.executable,
                   PATH=os.pathsep.join((str(runtime_bin), env.get('PATH', os.defpath))),
                   PLAYWRIGHT_BROWSERS_PATH=str(runtime_bin.parent / 'browsers'),
                   HOST_SECRET_PROVIDER='bws', BWS_POSTGRES_PASSWORD_SOURCE=str(cfg.password_file),
                   BWS_DATABASE_NAME={'dev': 'app_dev', 'test': 'app_test', 'prod': 'app'}[cfg.channel],
                   LOCAL_UID=str(cfg.uid), LOCAL_GID=str(cfg.gid),
                   BWS_DATABASE_VOLUME={'dev': 'pkm-dev_pgdata-dev', 'test': 'pkm-test_pgdata', 'prod': 'pkm-prod_pgdata'}[cfg.channel],
                   BWS_DEPLOY_RUNTIME_ENV_FILE=str(runtime_env_file),
                   WATCHER_RUNTIME_ENV_FILE=str(runtime_env_file))
        # Reader credentials stay in the worker. Child programs get no token handle.
        env.pop('BWS_ACCESS_TOKEN', None)
        for key in ('DEPLOY_CAPTURE_WATCH_CONFIGURED', 'DEPLOY_HEIMDAL_RAW_MIGRATION_PENDING',
                    'BWS_EXPECTED_CAPTURE_WATCH_CONFIGURED', 'BWS_EXPECTED_RAW_MIGRATION_PENDING',
                    'BWS_DEPLOY_TARGET_REVISION'):
            env.pop(key, None)
        if self.active_consumers is not None:
            env.update(
                BWS_EXPECTED_CAPTURE_WATCH_CONFIGURED='1' if self.capture_watch_configured else '0',
                BWS_EXPECTED_RAW_MIGRATION_PENDING='1' if self.raw_migration_pending else '0',
                BWS_DEPLOY_TARGET_REVISION=self.active_revision or '',
            )
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
            or set(plan.consumers) != _BASE_DEPLOY_CONSUMERS):
            raise PostgresDeployError()
        validate_database_inputs(os.environ, database_input_files(self.config))
        if plan.automatic:
            if self.lock_fd is None:
                raise PostgresDeployError()
            ensure_candidate_object(self.config, plan.revision)
        require_file_protocol(self.config.root, plan.revision)
        self.qualify_authority_cutover(plan)

    def qualify_authority_cutover(self, plan: DeployPlan) -> None:
        if plan.authority_cutover is None:
            return
        cfg = self.config
        selected = plan.authority_cutover
        selected.validate()
        if plan.channel != cfg.channel:
            raise PostgresDeployError()
        require_cutover_target_config(cfg, selected)
        # Existing stopped/running writer bindings are the source of qualification.
        # Neither Compose creation nor a vault-discovery/default-selection path is used.
        ids = _command(['docker', 'ps', '--all', '--no-trunc', '--filter',
                        'label=com.docker.compose.project=pkm-' + cfg.channel,
                        '--format', '{{.ID}}']).splitlines()
        if not ids or len(set(ids)) != len(ids) or any(not re.fullmatch(r'[0-9a-f]{64}', item) for item in ids):
            raise PostgresDeployError()
        rows = json.loads(_command(['docker', 'inspect', '--type', 'container', *ids]))
        if not isinstance(rows, list) or {row.get('Id') for row in rows} != set(ids) or len(rows) != len(ids):
            raise PostgresDeployError()
        expected_services = {'api', 'worker', 'watcher'}
        if _capture_watch_configured(cfg):
            expected_services.add('heimdal-capture-watch')
        seen: set[str] = set()
        registry_roots: set[str] = set()
        env = self.environment(selected)
        for row in rows:
            labels = row.get('Config', {}).get('Labels', {})
            service = labels.get('com.docker.compose.service')
            if service not in {'api', 'worker', 'watcher', 'heimdal-capture-watch', 'migrate'}:
                continue
            if (service in seen or labels.get('com.docker.compose.project') != 'pkm-' + cfg.channel
                or labels.get('com.docker.compose.oneoff', 'False').lower() != 'false'):
                raise PostgresDeployError()
            seen.add(service)
            config = row['Config']
            entries = config.get('Env', [])
            if not isinstance(entries, list):
                raise PostgresDeployError()
            selectors: dict[str, str] = {}
            for entry in entries:
                if not isinstance(entry, str) or '\x00' in entry:
                    raise PostgresDeployError()
                key, separator, value = entry.partition('=')
                # Docker can retain an optional unset variable as a bare key.
                # Track its presence as empty so duplicates still refuse and it
                # cannot supply a required authority/channel/source selector.
                if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) or key in selectors:
                    raise PostgresDeployError()
                if not separator and (key in {'PKM_ENVIRONMENT', 'VAULT_HOST_ROOT', 'WATCHER_VAULT_PATH', *_CUTOVER_ENV}
                                      or key == 'VAULT_ROOT' or key.startswith('VAULT_ROOT_')):
                    raise PostgresDeployError()
                selectors[key] = value
            if selectors.get('PKM_ENVIRONMENT') != cfg.channel:
                raise PostgresDeployError()
            mounts = row.get('Mounts', [])
            if not isinstance(mounts, list) or any(not isinstance(mount, dict) for mount in mounts):
                raise PostgresDeployError()
            if service == 'migrate':
                # Canonical Alembic/SQL (including representation backfill) has
                # no filesystem content or registry access. Bind the exemption
                # to its producer ownership, entrypoint and actual access, never
                # its name, age or running state alone. Only the managed read-only
                # DB password file may be mounted; code/content overlays refuse.
                if (labels.get('com.agentic-pkm.mvr05.db-role') != 'migration-runner'
                    or config.get('Cmd') != ['/bin/bash', '/app/scripts/run_migrations.sh']
                    or config.get('Entrypoint') not in (None, [])
                    or config.get('WorkingDir') != '/app'
                    or len(mounts) > 1
                    or any(mount.get('Type') != 'bind'
                           or mount.get('Destination') != '/run/secrets/postgres_password'
                           or mount.get('Source') != str(cfg.password_file)
                           or mount.get('RW') is not False for mount in mounts)):
                    raise PostgresDeployError()
                continue
            for destinations, source in (({selected.root, '/app/vault'}, selected.root),
                                         ({'/app/instance-ownership'}, env['INSTANCE_OWNERSHIP_HOST_STATE_DIR'])):
                bound = [mount for mount in mounts if mount.get('Destination') in destinations]
                if len(bound) != 1 or bound[0].get('Type') != 'bind' or bound[0].get('Source') != source:
                    raise PostgresDeployError()
                if source == selected.root:
                    selected_destination = bound[0]['Destination']
            bound = [mount for mount in mounts if mount.get('Destination') == '/app/instance-state']
            if (len(bound) != 1 or bound[0].get('Type') != 'volume'
                or bound[0].get('Name') != 'pkm-' + cfg.channel + '_instance-state'):
                raise PostgresDeployError()
            registry_roots.add(bound[0]['Source'])
            container_roots = [selectors.get(key, '') for key in
                               ('VAULT_ROOT', 'VAULT_ROOT_' + cfg.channel.upper(), 'WATCHER_VAULT_PATH')]
            if (not any(container_roots) or any(value and value != selected_destination for value in container_roots)
                or selectors.get('VAULT_HOST_ROOT', selected.root) != selected.root):
                raise PostgresDeployError()
        if not expected_services <= seen or len(registry_roots) != 1:
            raise PostgresDeployError()
        registry_root = next(iter(registry_roots))
        volume = json.loads(_command(['docker', 'volume', 'inspect', 'pkm-' + cfg.channel + '_instance-state']))
        if (not isinstance(volume, list) or len(volume) != 1
            or volume[0].get('Mountpoint') != registry_root):
            raise PostgresDeployError()
        data = {'channel': cfg.channel, 'selection': {'binding_id': selected.binding_id, 'root': selected.root,
                                                   'ownership_root': selected.ownership_root},
                'registry_path': 'vault-registry.md'}
        # Registry/ledger are owned by the Compose runtime, not root. No protected
        # input is placed on argv or returned in the child/status diagnostics.
        # Docker's host volume ancestry is root-private even when the mounted
        # registry directory/files belong to the runtime UID. Open only this
        # already-qualified directory as supervisor, then let that UID read its
        # existing view through the inherited descriptor. No permissions/groups,
        # content mounts or storage-mutation capability are added.
        registry_directory = Path(registry_root) / 'agentic-pkm'
        if any(path.is_symlink() for path in (registry_directory, *registry_directory.parents)):
            raise PostgresDeployError()
        descriptor = os.open(registry_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if info.st_uid != cfg.uid or stat.S_IMODE(info.st_mode) != 0o700:
                raise PostgresDeployError()
            result = subprocess.run([sys.executable, '-c',
                'import json,os,sys; from app.ops.postgres_deploy_linux import require_existing_authority_binding; '
                'sys.path=[path for path in sys.path if path]; '
                'os.fchdir(int(sys.argv[1])); require_existing_authority_binding(json.load(sys.stdin))',
                str(descriptor)],
                input=json.dumps(data), text=True, cwd=cfg.root, pass_fds=(descriptor,),
                env={'PATH': os.defpath, 'PYTHONPATH': str(Path(__file__).resolve().parents[2]),
                     'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'},
                user=cfg.uid, group=cfg.gid, extra_groups=[], capture_output=True, check=False, timeout=30)
            current = registry_directory.stat()
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                raise PostgresDeployError()
        finally:
            os.close(descriptor)
        if result.returncode:
            raise PostgresDeployError()

    def select_active_plan(self, plan: DeployPlan) -> DeployPlan:
        self.validate_plan(plan)
        capture = _capture_watch_configured(self.config)
        migration = (_raw_representation_migration_pending(self.config, plan.revision, automatic=True)
                     if plan.automatic else _raw_representation_migration_pending(self.config, plan.revision))
        selected = list(plan.consumers)
        if capture:
            selected.append('heimdal-capture-watch')
        if migration:
            selected.append('heimdal-raw-migrate')
        candidate = tuple(selected)
        if self.active_consumers is not None and (
            self.active_consumers != candidate
            or self.capture_watch_configured != capture
            or self.raw_migration_pending != migration
            or self.active_revision != plan.revision
        ):
            raise PostgresDeployError()
        self.active_consumers = candidate
        self.active_revision = plan.revision
        self.capture_watch_configured = capture
        self.raw_migration_pending = migration
        return DeployPlan(plan.channel, plan.revision, plan.services, candidate, plan.ack_forward_only,
                          plan.image_digest, plan.automatic, plan.authority_cutover)

    def preflight(self, plan: DeployPlan) -> str:
        selected_plan = self.select_active_plan(plan)
        values = vm_selected_values(selected_plan, self.config.reader())
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

    def _reclaim_image_cache(self, plan: DeployPlan) -> None:
        """Optional cache recovery inside the existing automatic native lock."""
        if not plan.automatic or plan.channel not in {'dev', 'test'}:
            return
        from app.ops.pg_acceptance import IMAGE_REPOSITORY
        from scripts.compose_env import compose_env_value
        import fcntl

        reason = 'native_lock_unproven'
        image_pattern = r'sha256:[0-9a-f]{64}'
        container_pattern = r'[0-9a-f]{64}'

        def require_lock() -> None:
            if self.lock_fd is None or self.config.channel != plan.channel:
                raise PostgresDeployError()
            path = self.config.root / 'config/deploy' / (plan.channel + '.env.lock') / 'bws-owner'
            info, held = path.lstat(), os.fstat(self.lock_fd)
            if (not stat.S_ISREG(info.st_mode) or path.is_symlink()
                or (info.st_dev, info.st_ino) != (held.st_dev, held.st_ino)):
                raise PostgresDeployError()
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def inspect(ids: tuple[str, ...], kind: str) -> dict[str, dict[str, Any]]:
            if not ids:
                return {}
            if kind == 'container':
                fields = '{"id":{{json .Id}},"image_id":{{json .Image}},"ref":{{json .Config.Image}}}'
                keys = {'id', 'image_id', 'ref'}
                pattern = container_pattern
            else:
                fields = '{"id":{{json .Id}},"tags":{{json .RepoTags}},"digests":{{json .RepoDigests}},"created":{{json .Created}}}'
                keys = {'id', 'tags', 'digests', 'created'}
                pattern = image_pattern
            output = _command(['docker', kind, 'inspect', '--format', fields, *ids], timeout=15)
            rows: dict[str, dict[str, Any]] = {}
            for line in output.splitlines():
                row = json.loads(line)
                if (not isinstance(row, dict) or set(row) != keys
                    or not isinstance(row['id'], str) or not re.fullmatch(pattern, row['id'])
                    or row['id'] in rows):
                    raise PostgresDeployError()
                if kind == 'container':
                    if (not isinstance(row['image_id'], str)
                        or not re.fullmatch(image_pattern, row['image_id'])
                        or not isinstance(row['ref'], str) or not row['ref']):
                        raise PostgresDeployError()
                else:
                    for key in ('tags', 'digests'):
                        if row[key] is not None and (not isinstance(row[key], list)
                            or any(not isinstance(ref, str) for ref in row[key])):
                            raise PostgresDeployError()
                    if (not isinstance(row['created'], str)
                        or datetime.fromisoformat(row['created'].replace('Z', '+00:00')).tzinfo is None):
                        raise PostgresDeployError()
                rows[row['id']] = row
            if set(rows) != set(ids):
                raise PostgresDeployError()
            return rows

        def protection() -> tuple[object, set[str]]:
            digest = plan.image_digest
            if (not re.fullmatch(r'[0-9a-f]{40}', plan.revision) or not isinstance(digest, str)
                or not re.fullmatch(image_pattern, digest)):
                raise PostgresDeployError()
            protected = {IMAGE_REPOSITORY + ':' + plan.revision,
                         IMAGE_REPOSITORY + '@' + digest}
            pins: list[tuple[str, bytes | None]] = []
            for channel in ('dev', 'test', 'prod'):
                for suffix in ('.env', '.previous.env', '.migration-pending.env'):
                    path = self.config.root / 'config/deploy' / (channel + suffix)
                    try:
                        info = path.lstat()
                    except FileNotFoundError:
                        pins.append((path.name, None))
                        continue
                    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
                        raise PostgresDeployError()
                    content = path.read_bytes()
                    pins.append((path.name, content))
                    values: dict[str, str] = {}
                    for line in content.decode('utf-8').splitlines():
                        match = re.match(r'^(?:export\s+)?(APP_IMAGE_REPOSITORY|APP_IMAGE_TAG|APP_IMAGE_DIGEST_SUFFIX|FROM_SHA|TARGET_SHA)=(.*)$', line)
                        if match:
                            key, value = match.groups()
                            if key in values:
                                raise PostgresDeployError()
                            values[key] = compose_env_value(value)
                    if suffix == '.migration-pending.env':
                        for key in ('FROM_SHA', 'TARGET_SHA'):
                            value = values[key]
                            if key == 'FROM_SHA' and value == '__NO_BASELINE__':
                                continue
                            if not re.fullmatch(r'[0-9a-f]{40}', value):
                                raise PostgresDeployError()
                            protected.add(IMAGE_REPOSITORY + ':' + value)
                    else:
                        repository = values.get('APP_IMAGE_REPOSITORY') or IMAGE_REPOSITORY
                        tag = values['APP_IMAGE_TAG']
                        digest = values.get('APP_IMAGE_DIGEST_SUFFIX', '')
                        if (not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', tag)
                            or (digest and not re.fullmatch('@' + image_pattern, digest))):
                            raise PostgresDeployError()
                        protected.add(repository + ':' + tag)
                        if digest:
                            protected.add(repository + digest)
            ids = tuple(sorted(_command(['docker', 'ps', '--all', '--quiet', '--no-trunc'], timeout=15).splitlines()))
            if len(set(ids)) != len(ids) or any(not re.fullmatch(container_pattern, item) for item in ids):
                raise PostgresDeployError()
            containers = inspect(ids, 'container')
            for row in containers.values():
                protected.update((row['image_id'], row['ref']))
            # A Docker census may outlast a pin read. Refuse a mixed snapshot
            # before using it to prove that an image has no recovery owner.
            for name, before in pins:
                path = self.config.root / 'config/deploy' / name
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    after = None
                else:
                    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
                        raise PostgresDeployError()
                    after = path.read_bytes()
                if before != after:
                    raise PostgresDeployError()
            return (tuple(pins), containers), protected

        try:
            require_lock()
            reason = 'inventory_unproven'
            snapshot, protected = protection()
            ids = tuple(sorted(set(_command(['docker', 'image', 'ls', '--all', '--quiet', '--no-trunc'], timeout=15).splitlines())))
            if any(not re.fullmatch(image_pattern, item) for item in ids):
                raise PostgresDeployError()
            images = inspect(ids, 'image')
            candidates = []
            for image_id, row in images.items():
                refs = [*(row['tags'] or []), *(row['digests'] or [])]
                proved_digest = any(
                    re.fullmatch(re.escape(IMAGE_REPOSITORY) + '@' + image_pattern, ref)
                    for ref in (row['digests'] or [])
                )
                official = all(
                    re.fullmatch(re.escape(IMAGE_REPOSITORY) + r':[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', ref)
                    or re.fullmatch(re.escape(IMAGE_REPOSITORY) + '@' + image_pattern, ref)
                    for ref in refs
                )
                if proved_digest and official and image_id not in protected and not protected.intersection(refs):
                    candidates.append((datetime.fromisoformat(row['created'].replace('Z', '+00:00')), image_id))
            for _, image_id in sorted(candidates)[:8]:
                reason = 'native_lock_unproven'
                require_lock()
                reason = 'inventory_unproven'
                current, current_protected = protection()
                if current != snapshot or current_protected != protected:
                    reason = 'protection_changed'
                    raise PostgresDeployError()
                if inspect((image_id,), 'image')[image_id] != images[image_id]:
                    reason = 'image_changed'
                    raise PostgresDeployError()
                reason = 'removal_failed'
                _command(['docker', 'image', 'rm', '--no-prune', image_id], timeout=30)
        except Exception:
            # Optional recovery never replaces the ordinary pull/deploy gate.
            # Only a fixed phase reaches the journal, never Docker output.
            _emit_native_diagnostic((
                'PRIORITY=4\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n'
                f'MESSAGE=optional image cache recovery skipped: reason={reason}\n'
            ).encode('ascii'))

    def activate(self, plan: DeployPlan) -> None:
        if (self.lock_fd is None or set(plan.services) != set(DATABASE_CONSUMERS.values())
            or self.active_consumers is None):
            raise PostgresDeployError()
        self.source.verify()
        env = self.environment(plan.authority_cutover) if plan.authority_cutover else self.environment()
        # A supervisor environment variable is ambient to every operation. Only
        # the persisted request may authorize this one deployment's migration.
        env.pop('DEPLOY_ACK_FORWARD_ONLY', None)
        env['BWS_DEPLOY_LOCK_FD'] = str(self.lock_fd)
        receipt = self.config.journal.read()
        if (receipt is None or receipt.stage != 'activating'
            or plan.authority_cutover is not None and receipt.operation_id != self.operation_id):
            raise PostgresDeployError()
        if plan.authority_cutover is not None:
            self.config.journal.bind_request(receipt.operation_id, plan, False)
        self.qualify_authority_cutover(plan)
        if plan.authority_cutover is not None:
            env.update(zip(_CUTOVER_ENV, (plan.authority_cutover.binding_id, plan.authority_cutover.root)))
        env['BWS_DEPLOY_OPERATION_ID'] = receipt.operation_id
        self._reclaim_image_cache(plan)
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
                    if consumer in self.active_consumers:
                        raise PostgresDeployError()
                    values = {}
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
            argv = ['bash', str(self.config.root / 'scripts/deploy_channel.sh'),
                    'deploy', plan.channel, plan.revision]
            if plan.ack_forward_only:
                argv.append('--ack-forward-only')
            if plan.image_digest:
                argv += ['--image-digest', plan.image_digest]
            if plan.automatic:
                argv.append('--automatic')
            _command(argv, cwd=self.config.root, env=env, pass_fds=(self.lock_fd,),
                     deploy_diagnostics=True)
        finally:
            for path in paths:
                path.unlink()

    def _pg_runner(self, operation_id: str, plan: DeployPlan) -> Any:
        from app.ops.pg_acceptance_runner import PgAcceptanceRunner
        if (not plan.automatic or self.config.channel != plan.channel
            or plan.image_digest is None or self.operation_id not in {None, operation_id}):
            raise PostgresDeployError()
        return PgAcceptanceRunner(self.config.root, self.config.journal.directory,
                                  sha=plan.revision, digest=plan.image_digest,
                                  channel=plan.channel, operation_id=operation_id,
                                  deadline_signal=_emit_pg_deadline)

    def verify(self, operation_id: str, plan: DeployPlan) -> dict[str, Any]:
        receipt = self.config.journal.read()
        if (self.lock_fd is None or receipt is None or receipt.operation_id != operation_id
            or receipt.stage != 'verifying'):
            raise PostgresDeployError()
        return self._pg_runner(operation_id, plan).verify()

    def cleanup_verification(self, operation_id: str, plan: DeployPlan) -> None:
        self._pg_runner(operation_id, plan).cleanup()

    def qualify_web(self, operation_id: str) -> dict[str, Any]:
        """Fixed optional disposable proof for an already committed native image.

        No plan, command or profile is supplied by the caller. This readback
        does not rewrite PG, deployment, channel-health or parent acceptance.
        """
        from app.ops.native_web_acceptance_runner import NativeWebRunner
        if self.lock_fd is None or self.operation_id != operation_id:
            raise NativeWebRefusal('expected_committed_native_operation_required')
        proof = self._web_admission(operation_id)
        # Read only the two already-governed selectors. Never forward a channel
        # env file, its credentials or ambient caller TTS values to the image.
        runtime_path = _runtime_env_file_path(self.config.runtime_env_file)
        selectors: dict[str, str] = {}
        for line in runtime_path.read_text().splitlines():
            key, separator, value = line.partition('=')
            if separator and key in {'TTS_ENABLED', 'TTS_HOST_ROOT'}:
                if key in selectors:
                    raise NativeWebRefusal('selected_tts_configuration_ambiguous')
                selectors[key] = value
        root = Path(selectors.get('TTS_HOST_ROOT', ''))
        if selectors.get('TTS_ENABLED') != 'true' or not root.is_absolute() or not root.is_dir():
            raise NativeWebRefusal('selected_local_tts_unavailable')
        if root.is_relative_to(self.config.root.resolve()) or any(p.is_symlink() for p in (root, *root.parents)):
            raise NativeWebRefusal('selected_tts_source_unqualified')
        ensure_candidate_object(self.config, proof['source_sha'])
        result = NativeWebRunner(self.config.root, self.config.journal.directory,
                                 sha=proof['source_sha'], digest=proof['image_digest'],
                                 channel=self.config.channel, operation_id=operation_id, tts_root=root).verify()
        # Separate derived evidence, deliberately outside the deployment receipt.
        directory = self.config.journal.directory / 'native-web-results'
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or directory.is_symlink() or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
            raise NativeWebRefusal('web_evidence_directory_unqualified')
        path = directory / (self.config.channel + '-' + operation_id + '-' + result['resource_generation'] + '.json')
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(result, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return result

    def _web_admission(self, operation_id: str) -> dict[str, Any]:
        from app.ops.pg_acceptance import require_pass
        if self.config.channel not in {'dev', 'test'} or str(UUID(operation_id)) != operation_id:
            raise NativeWebRefusal('expected_committed_native_operation_required')
        receipt = self.config.journal.read()
        if (receipt is None or receipt.operation_id != operation_id or receipt.terminal_result != 'committed'
            or receipt.pg_acceptance is None):
            raise NativeWebRefusal('expected_committed_native_operation_required')
        proof = receipt.pg_acceptance
        require_pass(proof, proof['source_sha'], proof['image_digest'], self.config.channel, operation_id)
        request = _private_json(self.config.journal.directory / (self.config.channel + '.request.json'))
        raw = request.get('plan', {})
        plan = DeployPlan(self.config.channel, proof['source_sha'], tuple(raw.get('services', ())),
                          tuple(raw.get('consumers', ())), False, proof['image_digest'], True)
        if set(request) != {'operation_id', 'plan', 'bootstrap'} or request['bootstrap'] is not False:
            raise NativeWebRefusal('native_request_identity_mismatch')
        self.config.journal.bind_request(operation_id, plan, False)
        return proof

    def run_web_qualification(self, operation_id: str) -> dict[str, Any]:
        """Run/recover this fixed proof under the existing exact channel lock."""
        proof = self._web_admission(operation_id)  # Refuse foreign/prod before any lock/resource effect.
        self.operation_id = operation_id
        profile_owner = self._qualification_owner(WEB_PROFILE)
        path = self.config.root / 'config/deploy' / (self.config.channel + '.env.lock')
        result: dict[str, Any] | None = None
        fresh_identity = None
        if not path.exists():
            if not self._qualification_other_absent(WEB_PROFILE, proof):
                raise NativeWebRefusal('other_qualification_cleanup_unconfirmed')
            # The committed PG receipt predates this disposable attempt; it
            # cannot retire admission after unknown cleanup or no web result.
            with self.channel_lock(journal=self.config.journal, owner_marker=profile_owner, retire_terminal=False):
                if self.lock_fd is None:
                    raise PostgresDeployError()
                directory, owner = path.lstat(), os.fstat(self.lock_fd)
                fresh_identity = (directory.st_dev, directory.st_ino, owner.st_dev, owner.st_ino)
                result = self.qualify_web(operation_id)
                if not isinstance(result, dict) or result.get('cleanup') != 'confirmed':
                    raise PostgresDeployError()
        # An abrupt owner exit can retain native admission. Reuse its existing
        # inode/flock proof; never treat a name/PID or released lock as freeze.
        with self._qualification_reconciliation_lock(profile_owner, proof, allow_legacy=fresh_identity is None) as handle:
            self.lock_fd = handle[3]
            try:
                if fresh_identity is not None:
                    directory, owner = os.fstat(handle[2]), os.fstat(handle[3])
                    if fresh_identity != (directory.st_dev, directory.st_ino, owner.st_dev, owner.st_ino):
                        raise PostgresDeployError()
                receipt = self.config.journal.read()
                if (receipt is None or receipt.operation_id != operation_id
                    or receipt.terminal_result != 'committed' or not self.quiescent()):
                    raise PostgresDeployError()
                if result is None:
                    result = self.qualify_web(operation_id)
                if not isinstance(result, dict) or result.get('cleanup') != 'confirmed':
                    raise PostgresDeployError()
                self.retire_reconciled_channel_lock(handle, expected_owner=profile_owner)
                return result
            finally:
                self.lock_fd = None

    def qualify_journaling(self, operation_id: str) -> dict[str, Any]:
        """Separate fixed TEST extension; no selector, command or provider input."""
        from app.ops.native_journaling_acceptance import private_json
        from app.ops.native_journaling_acceptance_runner import NativeJournalingRunner
        if self.config.channel != 'test' or self.lock_fd is None or self.operation_id != operation_id:
            raise NativeWebRefusal('fixed_test_journaling_invocation_required')
        proof = self._web_admission(operation_id)
        ensure_candidate_object(self.config, proof['source_sha'])
        result = NativeJournalingRunner(self.config.root, self.config.journal.directory,
                                        sha=proof['source_sha'], digest=proof['image_digest'],
                                        channel='test', operation_id=operation_id).verify()
        directory = self.config.journal.directory / 'native-journaling-results'
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700
            or any(path.is_symlink() for path in (directory, *directory.parents))):
            raise NativeWebRefusal('journaling_evidence_directory_unqualified')
        private_json(directory / (operation_id + '-' + result['resource_generation'] + '.json'), result)
        return result

    def run_journaling_qualification(self, operation_id: str) -> dict[str, Any]:
        """Use the existing same-operation channel-lock recovery/retirement seam."""
        if self.config.channel != 'test':
            raise NativeWebRefusal('fixed_test_journaling_invocation_required')
        from app.ops.native_journaling_acceptance import PROFILE
        proof = self._web_admission(operation_id)
        self.operation_id = operation_id
        profile_owner = self._qualification_owner(PROFILE)
        path = self.config.root / 'config/deploy/test.env.lock'
        result: dict[str, Any] | None = None
        fresh_identity = None
        if not path.exists():
            if not self._qualification_other_absent(PROFILE, proof):
                raise NativeWebRefusal('other_qualification_cleanup_unconfirmed')
            with self.channel_lock(journal=self.config.journal, owner_marker=profile_owner, retire_terminal=False):
                if self.lock_fd is None:
                    raise PostgresDeployError()
                directory, owner = path.lstat(), os.fstat(self.lock_fd)
                fresh_identity = (directory.st_dev, directory.st_ino, owner.st_dev, owner.st_ino)
                result = self.qualify_journaling(operation_id)
                if result.get('cleanup') != 'confirmed':
                    raise PostgresDeployError()
        with self._qualification_reconciliation_lock(profile_owner, proof, allow_legacy=fresh_identity is None) as handle:
            self.lock_fd = handle[3]
            try:
                if fresh_identity is not None:
                    directory, owner = os.fstat(handle[2]), os.fstat(handle[3])
                    if fresh_identity != (directory.st_dev, directory.st_ino, owner.st_dev, owner.st_ino):
                        raise PostgresDeployError()
                receipt = self.config.journal.read()
                if (receipt is None or receipt.operation_id != operation_id
                    or receipt.terminal_result != 'committed' or not self.quiescent()):
                    raise PostgresDeployError()
                if result is None:
                    result = self.qualify_journaling(operation_id)
                if result.get('cleanup') != 'confirmed':
                    raise PostgresDeployError()
                self.retire_reconciled_channel_lock(handle, expected_owner=profile_owner)
                return result
            finally:
                self.lock_fd = None

    def _qualification_owner(self, profile: str) -> dict[str, str]:
        if self.operation_id is None:
            raise NativeWebRefusal('expected_committed_native_operation_required')
        return {'kind': 'native-qualification', 'channel': self.config.channel,
                'operation_id': self.operation_id, 'profile_version': profile}

    def _qualification_other_absent(self, profile: str, proof: dict[str, Any]) -> bool:
        """Read-only opposite-profile census; absence is never inferred from quiescence."""
        from app.ops.native_journaling_acceptance import PROFILE
        from app.ops.native_journaling_acceptance_runner import NativeJournalingRunner
        from app.ops.native_web_acceptance_runner import NativeWebRunner
        if profile == WEB_PROFILE and self.config.channel == 'dev':
            return True  # Journaling has no admitted DEV producer.
        if profile not in {WEB_PROFILE, PROFILE} or self.operation_id is None:
            raise NativeWebRefusal('qualification_owner_unqualified')
        runner_type = NativeJournalingRunner if profile == WEB_PROFILE else NativeWebRunner
        other = runner_type(self.config.root, self.config.journal.directory,
            sha=proof['source_sha'], digest=proof['image_digest'], channel=self.config.channel,
            operation_id=self.operation_id)
        if any(path.exists() or path.is_symlink() for path in (other.marker, other.preparing, other.directory)):
            return False
        return all(other._owned(suffix) is None for suffix in ('tests', 'db'))

    @contextmanager
    def _qualification_reconciliation_lock(self, owner: dict[str, str], proof: dict[str, Any], *, allow_legacy: bool
                                         ) -> Iterator[tuple[Path, int, int, int]]:
        # Acquisition fallback only. Never retry a yielded Product operation.
        with ExitStack() as stack:
            try:
                handle = stack.enter_context(self.failed_reconciliation_lock(expected_owner=owner))
            except PostgresDeployError:
                if not allow_legacy:
                    raise  # Never adopt a replacement of this invocation's fresh inode.
                try:
                    handle = stack.enter_context(self.failed_reconciliation_lock())
                except PostgresDeployError:
                    raise NativeWebRefusal('qualification_owner_unqualified') from None
                # Legacy empty owners are adopted only after opposite-profile
                # resource absence is proved under the held inode/flock.
                if not self._qualification_other_absent(owner['profile_version'], proof):
                    raise NativeWebRefusal('other_qualification_cleanup_unconfirmed')
                raw = (json.dumps(owner, sort_keys=True) + '\n').encode()
                if os.pread(handle[3], 4097, 0) or os.pwrite(handle[3], raw, 0) != len(raw):
                    raise PostgresDeployError()
                for descriptor in (handle[3], handle[2], handle[1]):
                    os.fsync(descriptor)
            yield handle

    def _running_one_shots(self) -> bool:
        # Running-only inventory misses a created container that Docker may
        # still start. This census grants no authority to stop any container.
        def inventory() -> tuple[str, ...]:
            output = _command([
                'docker', 'ps', '--all', '--no-trunc', '--filter',
                'label=com.docker.compose.project=pkm-' + self.config.channel,
                '--filter', 'label=com.docker.compose.oneoff=True', '--format', '{{.ID}}',
            ], cwd=self.config.root, timeout=15).strip()
            ids = tuple(output.splitlines()) if output else ()
            if len(set(ids)) != len(ids) or any(re.fullmatch(r'[0-9a-f]{64}', value) is None for value in ids):
                raise PostgresDeployError()
            return tuple(sorted(ids))

        ids = inventory()
        if not ids:
            return bool(inventory())

        def completed_snapshot() -> dict[str, tuple[str, ...]]:
            output = _command([
                'docker', 'inspect', '--type', 'container', '--format',
                '{{.Id}} {{.State.Status}} {{.State.Running}} {{.State.Paused}} '
                '{{.State.Restarting}} {{.State.Pid}}', *ids,
            ], cwd=self.config.root, timeout=15)
            records: dict[str, tuple[str, ...]] = {}
            for line in output.splitlines():
                fields = tuple(line.split())
                if (len(fields) != 6 or fields[0] not in ids or fields[0] in records
                    or fields[1] not in {'exited', 'dead'}
                    or fields[2:] != ('false', 'false', 'false', '0')):
                    raise PostgresDeployError()
                records[fields[0]] = fields[1:]
            if set(records) != set(ids):
                raise PostgresDeployError()
            return records

        # A transition, disappearance during inspection, or unavailable daemon
        # is unknown. Only stable completed state and membership are quiescent.
        first = completed_snapshot()
        return first != completed_snapshot() or inventory() != ids

    def quiescent(self) -> bool:
        # Called by the worker after each synchronous subprocess has been reaped.
        # Docker may still be starting after its CLI returns. Stable long-running
        # services are expected, but daemon-owned one-shot services can outlive
        # the Docker CLI and continue mutating state after their supervisor exits.
        try:
            # `compose ps` can omit `compose run` containers. API service labels
            # alone cannot distinguish a healthy server from the source writer.
            if self._running_one_shots():
                return False
            rows = self.compose('ps', '--all', '--format', 'json').strip()
            if not rows:
                return True
            records = json.loads(rows) if rows.startswith('[') else [json.loads(line) for line in rows.splitlines()]
            return isinstance(records, list) and all(
                isinstance(row, dict)
                and isinstance(row.get('Service'), str) and bool(row['Service'])
                and row.get('State') in {'running', 'exited', 'created'}
                and not (row['Service'] in _ONE_SHOT_COMPOSE_SERVICES and row['State'] == 'running')
                and row.get('Health') not in {'starting'}
                for row in records
            )
        except Exception:
            return False

    def recover_source_terminal(self, operation_id: str, plan: DeployPlan) -> None:
        """Observe a retained completed source one-shot, never replay it.

        Caller holds the same-ID reconciliation lock and has proved all
        one-shots quiescent. Absence creates no source-failure inference.
        """
        from app.ops.native_source_bootstrap import quiesce_owned_container, source_terminal_reason
        receipt = self.config.journal.read()
        if (receipt is None or receipt.operation_id != operation_id
            or receipt.stage not in {'activating', 'verifying', 'failed'}
            or self.config.journal.bound_plan(operation_id) != plan):
            raise PostgresDeployError()
        name = f'pkm-{plan.channel}-source-bootstrap-{operation_id}'

        def retain(status: int, oom: bool) -> None:
            reason = receipt.source_failure or source_terminal_reason(status, oom_killed=oom)
            if reason:
                self.config.journal.record_source_failure(operation_id, plan.revision, reason)

        if not quiesce_owned_container(plan.channel, name, operation_id, plan.revision,
                                       observe_terminal=retain, docker_command=_command):
            raise PostgresDeployError()

    @contextmanager
    def channel_lock(self, *, journal: DeployJournal | None = None,
                     owner_marker: dict[str, str] | None = None,
                     retire_terminal: bool = True) -> Iterator[None]:
        import fcntl
        path = self.config.root / 'config/deploy' / (self.config.channel + '.env.lock')
        if owner_marker is not None:
            from app.ops.native_journaling_acceptance import PROFILE
            qualification = (owner_marker.get('kind') == 'native-qualification'
                and set(owner_marker) == {'kind', 'channel', 'operation_id', 'profile_version'}
                and owner_marker.get('profile_version') in {WEB_PROFILE, PROFILE}
                and (owner_marker.get('profile_version') != PROFILE or self.config.channel == 'test')
                and journal is not None
                and journal.directory == self.config.journal.directory)
            karakeep = (set(owner_marker) == {'kind', 'channel', 'operation_id'}
                and owner_marker.get('kind') in {'karakeep-deploy', 'karakeep-boot'})
            if (journal is None or journal.channel != self.config.channel
                or self.config.channel not in {'dev', 'test'}
                or not (qualification or karakeep)
                or owner_marker['channel'] != self.config.channel
                or owner_marker['operation_id'] != self.operation_id
                or str(UUID(owner_marker['operation_id'])) != owner_marker['operation_id']):
                raise PostgresDeployError()
        # Preserve the existing mkdir admission, including old non-BWS callers.
        path.mkdir(mode=0o700)
        descriptor = None
        try:
            descriptor = os.open(path / 'bws-owner', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if owner_marker is not None:
                raw = (json.dumps(owner_marker, sort_keys=True) + '\n').encode()
                if os.write(descriptor, raw) != len(raw):
                    raise PostgresDeployError()
                os.fsync(descriptor)
                for directory in (path, path.parent):
                    opened = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        os.fsync(opened)
                    finally:
                        os.close(opened)
            self.lock_fd = descriptor
            yield
        finally:
            self.lock_fd = None
            if descriptor is not None:
                os.close(descriptor)
            receipt = (journal or self.config.journal).read()
            if retire_terminal and receipt and receipt.operation_id == self.operation_id and receipt.terminal_result:
                if owner_marker is not None:
                    with self.failed_reconciliation_lock(expected_owner=owner_marker) as handle:
                        self.retire_reconciled_channel_lock(handle, expected_owner=owner_marker)
                else:
                    (path / 'bws-owner').unlink()
                    path.rmdir()
            # Pending or unreadable state retains the mkdir lock as a durable
            # admission refusal. Never clear it merely because this thread ended.

    @contextmanager
    def failed_reconciliation_lock(self, *, expected_owner: dict[str, str] | None = None
                                   ) -> Iterator[tuple[Path, int, int, int]]:
        """Acquire the existing BWS channel lock without creating or changing it."""
        import fcntl

        path = self.config.root / 'config/deploy' / (self.config.channel + '.env.lock')
        parent_fd = directory_fd = lock_fd = None
        try:
            parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            directory_fd = os.open(
                path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
            )
            directory_info = os.fstat(directory_fd)
            names = set(os.listdir(directory_fd))
            if (directory_info.st_uid != os.geteuid() or stat.S_IMODE(directory_info.st_mode) != 0o700
                or names != {'bws-owner'}):
                raise PostgresDeployError()
            lock_fd = os.open(
                'bws-owner', os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
            )
            lock_info = os.fstat(lock_fd)
            if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.geteuid()
                or stat.S_IMODE(lock_info.st_mode) != 0o600 or lock_info.st_nlink != 1):
                raise PostgresDeployError()
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            raw_owner = os.pread(lock_fd, 4097, 0)
            if (expected_owner is None and raw_owner) or (
                expected_owner is not None and raw_owner != (json.dumps(expected_owner, sort_keys=True) + '\n').encode()
            ):
                raise PostgresDeployError()
            if set(os.listdir(directory_fd)) != {'bws-owner'}:
                raise PostgresDeployError()
            yield path, parent_fd, directory_fd, lock_fd
        except Exception:
            raise PostgresDeployError() from None
        finally:
            for descriptor in (lock_fd, directory_fd, parent_fd):
                if descriptor is not None:
                    os.close(descriptor)

    @staticmethod
    def retire_reconciled_channel_lock(
        handle: tuple[Path, int, int, int],
        *, expected_owner: dict[str, str] | None = None,
    ) -> None:
        """Atomically release admission, then remove the detached lock directory."""
        path, parent_fd, directory_fd, lock_fd = handle
        current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        opened = os.fstat(directory_fd)
        marker = os.stat('bws-owner', dir_fd=directory_fd, follow_symlinks=False)
        held = os.fstat(lock_fd)
        raw_owner = os.pread(lock_fd, 4097, 0)
        if (expected_owner is None and raw_owner) or (
            expected_owner is not None and raw_owner != (json.dumps(expected_owner, sort_keys=True) + '\n').encode()
        ):
            raise PostgresDeployError()
        if ((current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
            or (marker.st_dev, marker.st_ino) != (held.st_dev, held.st_ino)
            or set(os.listdir(directory_fd)) != {'bws-owner'}):
            raise PostgresDeployError()
        tombstone = path.name + '.reconciled-' + uuid4().hex
        os.rename(path.name, tombstone, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
        # A crash from here can leave only a uniquely named, detached directory;
        # it cannot block or be mistaken for the channel's admission lock.
        os.unlink('bws-owner', dir_fd=directory_fd)
        os.fsync(directory_fd)
        os.rmdir(tombstone, dir_fd=parent_fd)
        os.fsync(parent_fd)


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
        self.effects.config.journal.bind_request(self.operation_id, self.plan, self.bootstrap, create=True)
        worker = DeployWorker(self.effects.config.journal, self.effects)
        # Coordination only: no pins, writers, volumes or Docker mutation.
        worker.prepare(self.operation_id)
        try:
            self.effects.validate_plan(self.plan)
            selected_plan = self.effects.select_active_plan(self.plan)
        except Exception:
            # Selection is read-only. Persist a terminal refusal before releasing
            # the channel lock so a corrected selector can be retried safely.
            self.effects.config.journal.write(self.operation_id, 'aborted')
            raise
        if self.bootstrap:
            reader = self.effects.config.reader()
            from app.ops.host_secret_bootstrap import _resolve_bws_consumer_values
            from app.ops.host_secret_contract import load_host_secret_contract
            for consumer in selected_plan.consumers:
                if consumer not in DATABASE_CONSUMERS:
                    self.effects.consumer_values[consumer] = _resolve_bws_consumer_values(
                        self.plan.channel, consumer, load_host_secret_contract(), reader
                    )
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
        self.effects.config.journal.bind_request(self.operation_id, self.plan, self.bootstrap)
        receipt = self.effects.config.journal.read()
        if receipt and receipt.operation_id == self.operation_id and receipt.terminal_result:
            receipt.require_profile(self.plan)
            return {'receipt': receipt.payload()}
        if self.failed:
            if self.plan.authority_cutover is not None:
                return {'pending': True, 'empty': False, 'ready': False}
            raise PostgresDeployError()
        return {'pending': True, 'empty': self.empty, 'ready': self.ready.is_set()}


class DeploymentSupervisor:
    def __init__(self, config: LinuxConfig) -> None:
        self.config = config
        self.operation: SupervisedOperation | None = None
        self.mutex = threading.Lock()
        self.karakeep: Any = None

    def _require_current_config(self) -> None:
        current = LinuxConfig.load(self.config.channel)
        if current != self.config:
            raise PostgresDeployError()

    def _reconcile_failed(self, operation_id: str, plan: DeployPlan, bootstrap: bool) -> dict[str, Any]:
        self._require_current_config()
        previous = self.config.journal.read()
        if previous is None or previous.operation_id != operation_id:
            raise PostgresDeployError()
        self.config.journal.bind_request(operation_id, plan, bootstrap)
        previous.require_profile(plan)
        operation = self.operation
        if operation is not None and operation.operation_id != operation_id:
            raise PostgresDeployError()
        if previous.terminal_result is not None:
            if previous.terminal_result == 'failed':
                lock_path = self.config.root / 'config/deploy' / (self.config.channel + '.env.lock')
                try:
                    os.stat(lock_path, follow_symlinks=False)
                except FileNotFoundError:
                    return {'receipt': previous.payload()}
                effects = LinuxEffects(self.config)
                with effects.failed_reconciliation_lock() as lock:
                    if plan.automatic:
                        effects.cleanup_verification(operation_id, plan)
                    if not effects.quiescent():
                        raise PostgresDeployError()
                    effects.recover_source_terminal(operation_id, plan)
                    recovered = self.config.journal.read()
                    if (recovered is None or recovered.operation_id != operation_id
                        or recovered.terminal_result != 'failed'):
                        raise PostgresDeployError()
                    previous = recovered
                    effects.retire_reconciled_channel_lock(lock)
            return {'receipt': previous.payload()}
        if plan.authority_cutover is not None:
            # Quiescent services cannot establish the outcome of authority cutover.
            # Preserve the request, journal and admission lock for operator recovery.
            return {'pending': True, 'empty': False, 'ready': False}
        if previous.stage not in {'activating', 'verifying'}:
            raise PostgresDeployError()
        if operation is not None and (
            operation.plan != plan or operation.bootstrap != bootstrap
            or not operation.finished.is_set() or operation.thread.is_alive() or not operation.failed
        ):
            raise PostgresDeployError()
        effects = LinuxEffects(self.config)
        with effects.failed_reconciliation_lock() as lock:
            if plan.automatic:
                effects.cleanup_verification(operation_id, plan)
            if not effects.quiescent():
                raise PostgresDeployError()
            effects.recover_source_terminal(operation_id, plan)
            receipt = self.config.journal.write(operation_id, 'failed')
            effects.retire_reconciled_channel_lock(lock)
        return {'receipt': receipt.payload()}

    def request(self, data: dict[str, Any]) -> dict[str, Any]:
        if data.get('action') in {'karakeep-acquire', 'karakeep-project'}:
            from app.ops.karakeep_runtime import dispatch

            return dispatch(self.config, data, self._require_current_config)
        if isinstance(data.get('action'), str) and data['action'].startswith('karakeep-'):
            from app.ops.karakeep_deploy import KarakeepEffects, KarakeepSupervisor

            with self.mutex:
                if self.karakeep is None:
                    self.karakeep = KarakeepSupervisor(KarakeepEffects(self.config), self._require_current_config)
            # Karakeep retains this same guard at admission/effect boundaries,
            # inside durable refusal handling for new deploy IDs. Other
            # operations keep the existing fail-closed configuration gate.
            return self.karakeep.request(data)
        if set(data) != {'action', 'operation_id', 'plan', 'bootstrap'}:
            raise PostgresDeployError()
        operation_id = str(data['operation_id'])
        if str(UUID(operation_id)) != operation_id or type(data['bootstrap']) is not bool:
            raise PostgresDeployError()
        plan = DeployPlan.from_payload(data['plan'])
        if (plan.automatic or plan.authority_cutover is not None) and data['bootstrap']:
            raise PostgresDeployError()
        if plan.channel != self.config.channel or data['action'] not in {
            'prepare', 'activate', 'join', 'reconcile-failed'
        }:
            raise PostgresDeployError()
        with self.mutex:
            if data['action'] == 'reconcile-failed':
                return self._reconcile_failed(operation_id, plan, data['bootstrap'])
            previous = self.config.journal.read()
            if previous and previous.operation_id == operation_id:
                self.config.journal.bind_request(operation_id, plan, data['bootstrap'])
                if (plan.authority_cutover is not None and previous.terminal_result is None
                    and self.operation is None):
                    return {'pending': True, 'empty': False, 'ready': False}
            if previous and previous.operation_id == operation_id and previous.terminal_result:
                self.config.journal.bind_request(operation_id, plan, data['bootstrap'])
                previous.require_profile(plan)
                if previous.terminal_result == 'failed':
                    # Never expose failed terminal evidence until an interrupted
                    # lock retirement has been completed through the same proof.
                    return self._reconcile_failed(operation_id, plan, data['bootstrap'])
                return {'receipt': previous.payload()}
            if self.operation and self.operation.operation_id != operation_id:
                if not self.operation.finished.is_set():
                    raise PostgresDeployError()
                self.operation = None
            if self.operation is None:
                # A daemon loss without a receipt never authorizes another worker.
                # Only a new operation with no pending predecessor can be created.
                if data['action'] != 'prepare' or (previous and previous.terminal_result is None):
                    raise PostgresDeployError()
                # The service binds its root-owned channel config at startup.
                # Refuse stale config before admitting a request or starting a worker;
                # the operator can restart the idle service to apply the new config.
                self._require_current_config()
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
        connection.settimeout(170 if request.get('action') in {'karakeep-acquire', 'karakeep-project'} else 35)
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
        request = {'action': action, 'operation_id': operation_id, 'plan': plan.payload(), 'bootstrap': self.bootstrap}
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
            if plan.authority_cutover is not None and response.get('ready') is False:
                # A lost worker cannot make progress through another join RPC.
                # Return control with the existing host operation still pending.
                raise PostgresDeployError()
            response = self._request('join', operation_id, plan)
        receipt = DeployReceipt(**response['receipt'])
        receipt.validate()
        receipt.require_profile(plan)
        if receipt.operation_id != operation_id or receipt.channel != plan.channel:
            raise PostgresDeployError()
        return receipt

    def activate(self, operation_id: str, plan: DeployPlan) -> DeployReceipt:
        return self._terminal('activate', operation_id, plan)

    def join(self, operation_id: str, plan: DeployPlan) -> DeployReceipt:
        return self._terminal('join', operation_id, plan)

    def reconcile_failed(self, operation_id: str, plan: DeployPlan) -> DeployReceipt:
        self.bootstrap = False
        response = self._request('reconcile-failed', operation_id, plan)
        receipt = DeployReceipt(**response['receipt'])
        receipt.validate()
        receipt.require_profile(plan)
        if (receipt.operation_id != operation_id or receipt.channel != plan.channel
            or receipt.terminal_result not in {'committed', 'aborted', 'failed'}):
            raise PostgresDeployError()
        return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=(
        'serve', 'rpc', 'guard', 'cleanup', 'token-push', 'token-push-worker',
        'token-push-status', 'token-push-inspect', 'qualify-web', 'qualify-journaling', 'karakeep-boot',
        'karakeep-acquire', 'karakeep-project',
    ))
    parser.add_argument('channel', choices=('dev', 'test', 'prod'))
    parser.add_argument('operation_id', nargs='?')
    parser.add_argument('attempt_id', nargs='?')
    parser.add_argument('prior_generation', nargs='?')
    parser.add_argument('--compose-command')
    args = parser.parse_args(argv)
    journaling_started = False
    try:
        if args.action in {'karakeep-acquire', 'karakeep-project'}:
            if args.channel != 'test' or any((args.operation_id, args.attempt_id, args.prior_generation, args.compose_command)):
                raise PostgresDeployError()
            from app.ops.karakeep_runtime import remote

            return remote(args.action, args.channel)
        if args.action == 'karakeep-boot':
            from app.ops.karakeep_deploy import boot

            boot(args.channel)
            return 0
        if args.action.startswith('token-push'):
            from app.ops.bws_token_push import remote_main

            selected = [args.action, args.channel]
            selected.extend(
                value for value in (args.operation_id, args.attempt_id, args.prior_generation)
                if value is not None
            )
            return remote_main(
                selected,
                app_root=LinuxConfig.load(args.channel, require_runtime_env=False).root,
            )
        if args.action == 'qualify-journaling':
            if (args.channel != 'test' or args.operation_id is None
                or args.attempt_id is not None or args.prior_generation is not None or args.compose_command):
                raise NativeWebRefusal('fixed_test_journaling_invocation_required')
            effects = LinuxEffects(LinuxConfig.load(args.channel))
            effects._web_admission(args.operation_id)
            def journaling_interrupted(_signal: int, _frame: Any) -> None:
                raise KeyboardInterrupt()
            previous_handler = signal.signal(signal.SIGTERM, journaling_interrupted)
            try:
                journaling_started = True
                result = effects.run_journaling_qualification(args.operation_id)
            finally:
                signal.signal(signal.SIGTERM, previous_handler)
            print(json.dumps(result, sort_keys=True))
            return 0 if result['result'] == 'passed' else 78
        if args.action == 'qualify-web':
            if (args.channel not in {'dev', 'test'} or args.operation_id is None
                or args.attempt_id is not None or args.prior_generation is not None or args.compose_command):
                raise NativeWebRefusal('fixed_dev_test_invocation_required')
            effects = LinuxEffects(LinuxConfig.load(args.channel))
            def interrupted(_signal: int, _frame: Any) -> None:
                raise KeyboardInterrupt()
            previous_handler = signal.signal(signal.SIGTERM, interrupted)
            try:
                result = effects.run_web_qualification(args.operation_id)
            finally:
                signal.signal(signal.SIGTERM, previous_handler)
            print(json.dumps(result, sort_keys=True))
            return 0 if result['result'] == 'passed' else 78
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
    except NativeWebRefusal as exc:
        if args.action == 'qualify-journaling':
            from app.ops.native_journaling_acceptance import PROFILE
            print(json.dumps({'profile_version': PROFILE, 'result': 'unknown' if journaling_started else 'refused',
                              'reason': exc.reason, 'cleanup': 'unknown' if journaling_started else 'not_started'}, sort_keys=True))
            return 78
        print(json.dumps({'profile_version': WEB_PROFILE, 'result': 'refused', 'reason': exc.reason,
                          'cleanup': 'not_started'}, sort_keys=True))
        return 78
    except Exception:
        if args.action == 'qualify-journaling':
            from app.ops.native_journaling_acceptance import PROFILE
            print(json.dumps({'profile_version': PROFILE, 'result': 'unknown' if journaling_started else 'refused',
                              'reason': 'native_journaling_boundary_unavailable',
                              'cleanup': 'unknown' if journaling_started else 'not_started'}, sort_keys=True))
            return 78
        print('database deployment refused; operation remains pending', file=sys.stderr)
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
