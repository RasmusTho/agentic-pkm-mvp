"""BWS-04 ordered deployment, durable receipts, and the PostgreSQL file boundary.

Adapters perform effects; this module owns admission and ordering. Receipt/state
objects contain identifiers only. Provider and driver exceptions never escape.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.config.database import resolve_database_url, normalize_database_url
from app.ops.bws_secret_admin import SecretCopy
from app.ops.host_secret_bootstrap import _resolve_bws_consumer_values, validate_secret_value
from app.ops.host_secret_contract import CHANNEL_PROJECTS, DATABASE_CONSUMERS, load_host_secret_contract
from app.ops.host_secret_controller import HostSecretController, HostSecretOperation, TerminalEvidence
from app.ops.secret_admin import SecretAdmin, SecretHistory, _note


class PostgresDeployError(RuntimeError):
    def __init__(self) -> None:
        super().__init__('database deployment refused; matching terminal evidence required')


@dataclass(frozen=True)
class DeployPlan:
    channel: str
    revision: str
    services: tuple[str, ...]
    consumers: tuple[str, ...]
    ack_forward_only: bool = False

    def validate(self) -> None:
        contract = load_host_secret_contract()
        if (type(self.ack_forward_only) is not bool
            or self.channel not in CHANNEL_PROJECTS or len(self.revision) != 40
            or any(c not in '0123456789abcdef' for c in self.revision)
            or not self.services or len(set(self.services)) != len(self.services)
            or not self.consumers or len(set(self.consumers)) != len(self.consumers)):
            raise PostgresDeployError()
        selected = {consumer for consumer, service in DATABASE_CONSUMERS.items() if service in self.services}
        if not selected or not selected <= set(self.consumers):
            raise PostgresDeployError()
        for consumer in self.consumers:
            if consumer in DATABASE_CONSUMERS:
                if consumer not in selected:
                    raise PostgresDeployError()
                contract.file_binding(channel=self.channel, consumer=consumer, secret='postgres.password')
            elif not any(ch == self.channel and name == consumer for ch, name, _ in contract.allowed):
                raise PostgresDeployError()


@dataclass(frozen=True)
class DeployReceipt:
    operation_id: str
    channel: str
    kind: str
    stage: str
    terminal_result: str | None

    def validate(self) -> None:
        if (str(UUID(self.operation_id)) != self.operation_id or self.channel not in CHANNEL_PROJECTS
            or self.kind != 'deploy'
            or self.stage not in {'prepared', 'preflighted', 'materialized', 'authenticating', 'activating', 'committed', 'aborted', 'failed'}
            or self.terminal_result != (self.stage if self.stage in {'committed', 'aborted', 'failed'} else None)):
            raise PostgresDeployError()

    def evidence(self) -> TerminalEvidence:
        self.validate()
        if self.terminal_result is None:
            raise PostgresDeployError()
        return TerminalEvidence(self.operation_id, self.kind, self.channel, self.terminal_result, 'remote-terminal')


class DeployJournal:
    """One owner-only atomic, fsynced channel journal outside Git and tmpfs."""
    def __init__(self, directory: Path, channel: str) -> None:
        if channel not in CHANNEL_PROJECTS:
            raise PostgresDeployError()
        self.directory = directory
        self.channel = channel

    @contextmanager
    def _directory(self) -> Iterator[int]:
        descriptor = None
        try:
            if not self.directory.is_absolute() or any(
                p.is_symlink() or (p / '.git').exists() for p in (self.directory, *self.directory.parents)
            ):
                raise PostgresDeployError()
            descriptor = HostSecretController._durable_directory(self.directory)
            info = os.fstat(descriptor)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise PostgresDeployError()
            yield descriptor
        except Exception:
            raise PostgresDeployError() from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def read(self) -> DeployReceipt | None:
        if not self.directory.exists():
            return None
        with self._directory() as directory:
            try:
                descriptor = os.open(self.channel + '.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            except FileNotFoundError:
                return None
            with os.fdopen(descriptor, 'r') as source:
                info = os.fstat(source.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096 or info.st_nlink != 1):
                    raise PostgresDeployError()
                receipt = DeployReceipt(**json.load(source))
                receipt.validate()
                if receipt.channel != self.channel:
                    raise PostgresDeployError()
                return receipt

    def bind_request(self, operation_id: str, plan: DeployPlan, bootstrap: bool, *, create: bool = False) -> None:
        """Bind the same-ID receipt to immutable, value-free request inputs.

        Persist before preparing the worker. A partial or missing binding can
        never turn an old terminal receipt into success for a different request.
        """
        plan.validate()
        DeployReceipt(operation_id, self.channel, 'deploy', 'prepared', None).validate()
        expected = {'operation_id': operation_id, 'plan': asdict(plan), 'bootstrap': bootstrap}
        # Normalize tuples to the on-disk JSON representation before comparison.
        expected = json.loads(json.dumps(expected))
        with self._directory() as directory:
            name = self.channel + '.request.json'
            try:
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            except FileNotFoundError:
                prior = None
            else:
                with os.fdopen(descriptor, 'r') as source:
                    info = os.fstat(source.fileno())
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                        or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 8192 or info.st_nlink != 1):
                        raise PostgresDeployError()
                    prior = json.load(source)
            if prior == expected:
                return
            if not create or (prior and prior.get('operation_id') == operation_id):
                raise PostgresDeployError()
            receipt = self.read()
            if receipt and (receipt.terminal_result is None or receipt.operation_id == operation_id):
                raise PostgresDeployError()
            temporary = name + '.' + str(uuid4()) + '.tmp'
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(descriptor, 'w') as target:
                    json.dump(expected, target, sort_keys=True)
                    target.flush()
                    os.fsync(target.fileno())
                os.rename(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass

    def write(self, operation_id: str, stage: str) -> DeployReceipt:
        receipt = DeployReceipt(operation_id, self.channel, 'deploy', stage,
                                stage if stage in {'committed', 'aborted', 'failed'} else None)
        receipt.validate()
        previous = self.read()
        successors = {
            'prepared': {'preflighted', 'aborted'}, 'preflighted': {'materialized', 'aborted'},
            'materialized': {'authenticating', 'activating', 'aborted'},
            'authenticating': {'activating', 'aborted'}, 'activating': {'committed', 'aborted', 'failed'},
        }
        if previous and previous.terminal_result is None:
            if previous.operation_id != operation_id or stage not in successors.get(previous.stage, set()):
                raise PostgresDeployError()
        elif stage != 'prepared' or (previous and previous.operation_id == operation_id):
            raise PostgresDeployError()
        with self._directory() as directory:
            temporary = self.channel + '.' + str(uuid4()) + '.tmp'
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(descriptor, 'wb') as target:
                    target.write((json.dumps(receipt.__dict__, sort_keys=True) + '\n').encode())
                    target.flush()
                    os.fsync(target.fileno())
                os.rename(temporary, self.channel + '.json', src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
        return receipt


def vm_selected_values(plan: DeployPlan, reader: Any) -> dict[str, dict[str, str]]:
    plan.validate()
    contract = load_host_secret_contract()
    try:
        return {consumer: _resolve_bws_consumer_values(plan.channel, consumer, contract, reader)
                for consumer in plan.consumers}
    except Exception:
        raise PostgresDeployError() from None


def password_authenticate(environment: Mapping[str, str], *, connect: Callable[..., Any] | None = None) -> None:
    """Require successful libpq password authentication, never trust/peer/readiness.

    PostgreSQL libpq PQconnectionUsedPassword is exposed by psycopg.pgconn.
    No SQL/password/environment mutation and no diagnostic from the driver escapes.
    """
    import psycopg
    try:
        if 'DATABASE_PASSWORD_FILE' not in environment:
            raise PostgresDeployError()
        url = normalize_database_url(resolve_database_url(environment), sqlalchemy=False)
        with (connect or psycopg.connect)(url, connect_timeout=5) as connection:
            if not connection.pgconn.used_password:
                raise PostgresDeployError()
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                if cursor.fetchone() != (1,):
                    raise PostgresDeployError()
    except Exception:
        raise PostgresDeployError() from None


class VmEffects(Protocol):
    def preflight(self, plan: DeployPlan) -> str: ...
    def initialized(self) -> bool: ...
    def materialize(self, password: str) -> None: ...
    def local_database(self) -> bool: ...
    def database_running(self) -> bool: ...
    def start_database_only(self) -> None: ...
    def authenticate(self) -> None: ...
    def stop_database(self) -> None: ...
    def activate(self, plan: DeployPlan) -> None: ...
    def quiescent(self) -> bool: ...


class DeployWorker:
    """Called only by the supervised same-ID worker while its VM lock is held."""
    def __init__(self, journal: DeployJournal, effects: VmEffects) -> None:
        self.journal = journal
        self.effects = effects
        self._prepared_id: str | None = None

    def prepare(self, operation_id: str) -> None:
        self.journal.write(operation_id, "prepared")
        self._prepared_id = operation_id

    def run(self, operation_id: str, plan: DeployPlan) -> DeployReceipt:
        plan.validate()
        previous = self.journal.read()
        if previous and previous.operation_id == operation_id:
            if previous.terminal_result:
                return previous
            # Process/worker loss does not authorize replay. Live reconnects join
            # the supervisor's existing invocation instead of calling run again.
            if previous.stage != 'prepared' or self._prepared_id != operation_id:
                raise PostgresDeployError()
        if previous and previous.terminal_result is None and self._prepared_id != operation_id:
            raise PostgresDeployError()
        password = self.effects.preflight(plan)
        if not validate_secret_value('password', password):
            raise PostgresDeployError()
        if self._prepared_id != operation_id:
            self.prepare(operation_id)
        self.journal.write(operation_id, 'preflighted')
        started = False
        activation_started = False
        try:
            initialized = self.effects.initialized()
            self.effects.materialize(password)
            del password
            self.journal.write(operation_id, 'materialized')
            # Re-read the same project and consumer set before any Compose.
            self.effects.preflight(plan)
            if initialized:
                self.journal.write(operation_id, 'authenticating')
                if self.effects.local_database() and not self.effects.database_running():
                    # Mark before sending; an ambiguous start must be stopped and
                    # proven quiescent, not mistaken for no effect.
                    started = True
                    self.effects.start_database_only()
                self.effects.authenticate()
            self.effects.preflight(plan)
            self.journal.write(operation_id, 'activating')
            activation_started = True
            self.effects.activate(plan)
            if not self.effects.quiescent():
                raise PostgresDeployError()
            return self.journal.write(operation_id, 'committed')
        except Exception:
            if not activation_started:
                try:
                    if started:
                        self.effects.stop_database()
                    if self.effects.quiescent():
                        return self.journal.write(operation_id, 'aborted')
                except Exception:
                    pass
            # Activation may include migrations/pins/writers. No generic rollback
            # or guessed terminal result is allowed after that boundary.
            raise PostgresDeployError() from None


class DeployRemote(Protocol):
    def prepare(self, operation_id: str, plan: DeployPlan, *, bootstrap: bool) -> bool: ...
    def activate(self, operation_id: str, plan: DeployPlan) -> DeployReceipt: ...
    def join(self, operation_id: str, plan: DeployPlan) -> DeployReceipt: ...


def bootstrap_password(admin: SecretAdmin, operation: HostSecretOperation, *, empty: bool) -> None:
    """Only locked empty-data bootstrap; never generic rotation or a retry-create."""
    operation.require_active(operation.target)
    if operation.kind != 'deploy' or not empty:
        raise PostgresDeployError()
    identity = operation.target + '/postgres.password'
    project = CHANNEL_PROJECTS[operation.target]
    with SecretHistory.open(admin.controller.directory) as history:
        records = history.records(operation.operation_id)
        current = admin.provider.read(project, identity)
        marker = _note('', operation.operation_id)
        if records:
            # Matching success is reusable; absent/ambiguous reads never mean a
            # sent create was rejected. No second create on this operation ID.
            if current is None or marker not in current.note.splitlines():
                raise PostgresDeployError()
            if not validate_secret_value('password', current.value):
                raise PostgresDeployError()
            sends = [record for record in records if record['event'] == 'sent']
            if len(sends) != 1:
                raise PostgresDeployError()
            sent = sends[0]
            outcomes = {record.get('request_id') for record in records if record['event'] in {'committed', 'rejected'}}
            if sent['request_id'] not in outcomes:
                history.append(operation_id=operation.operation_id, attempt_id=sent['attempt_id'],
                               identity=identity, event='committed', project=project, request_id=sent['request_id'])
                history.append(operation_id=operation.operation_id, attempt_id=sent['attempt_id'],
                               identity=identity, event='terminal', result='committed', previous_attempt=None)
            return
        if current is not None:
            raise PostgresDeployError()
        common = dict(operation_id=operation.operation_id, attempt_id=str(uuid4()), identity=identity)
        history.append(**common, event='snapshot', project=project, previous_state='absent')
        history.append(**common, event='prepared', previous_attempt=None)
        value = secrets.token_urlsafe(48)
        result: SecretCopy = admin._send_put(history, operation, common, project, identity, None, value, marker)
        current = admin.provider.read(project, identity)
        if current is None or current.item_id != result.item_id or current.value != value or marker not in current.note.splitlines():
            raise PostgresDeployError()
        history.append(**common, event='terminal', result='committed', previous_attempt=None)


def deploy_from_host(admin: SecretAdmin, remote: DeployRemote, plan: DeployPlan,
                     *, qualified: Callable[[], None], allow_bootstrap: bool = True) -> DeployReceipt:
    """Hold the shared controller lock through matching remote terminal evidence."""
    if type(allow_bootstrap) is not bool:
        raise PostgresDeployError()
    plan.validate()
    try:
        with admin.controller.deploy_operation(
            plan.channel, allow_bootstrap=allow_bootstrap
        ) as (operation, resumed):
            with SecretHistory.open(admin.controller.directory) as history:
                bootstrap_history = bool(history.records(operation.operation_id)) if resumed else False
            if bootstrap_history:
                if not allow_bootstrap:
                    raise PostgresDeployError()
                # A resumed bootstrap may still send a BWS create; retain the
                # owner qualification before its first remote recovery call.
                qualified()
                empty = remote.prepare(operation.operation_id, plan, bootstrap=True)
                if empty:
                    bootstrap_password(admin, operation, empty=True)
                else:
                    receipt = remote.join(operation.operation_id, plan)
                    operation.finish(receipt.evidence())
                    return receipt
            else:
                statuses = admin.check_selected(operation, plan.channel, plan.consumers)
                missing_password = any(row == {'secret': 'postgres.password', 'status': 'missing'} for row in statuses)
                if any(row['status'] not in {'ok', 'skipped'} and row != {'secret': 'postgres.password', 'status': 'missing'} for row in statuses):
                    raise PostgresDeployError()
                if missing_password and not allow_bootstrap:
                    # Read-only Product rollouts must stop before persisting a
                    # host mutation or asking the VM to inspect/bootstrap data.
                    raise PostgresDeployError()
                if missing_password:
                    # A missing password can proceed only on the explicitly
                    # allowed first-init path, qualified before any RPC.
                    qualified()
                operation.prepare_mutation()
                empty = remote.prepare(operation.operation_id, plan, bootstrap=missing_password)
                if missing_password:
                    if not empty:
                        receipt = remote.join(operation.operation_id, plan)
                        operation.finish(receipt.evidence())
                        return receipt
                    bootstrap_password(admin, operation, empty=True)
            if any(row['status'] not in {'ok', 'skipped'} for row in admin.check_selected(operation, plan.channel, plan.consumers)):
                raise PostgresDeployError()
            receipt = remote.activate(operation.operation_id, plan)
            operation.finish(receipt.evidence())
            return receipt
    except Exception:
        raise PostgresDeployError() from None
