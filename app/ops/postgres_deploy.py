"""BWS-04 ordered deployment, durable receipts, and the PostgreSQL file boundary.

Adapters perform effects; this module owns admission and ordering. Receipt/state
objects contain identifiers only. Provider and driver exceptions never escape.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import stat
import time
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID, uuid4

from app.config.database import resolve_database_url, normalize_database_url
from app.ops.bws_secret_admin import SecretCopy
from app.ops.bws_secret_reader import BwsItemAbsent
from app.ops.host_secret_bootstrap import _resolve_bws_consumer_values, validate_secret_value
from app.ops.host_secret_contract import CHANNEL_PROJECTS, DATABASE_CONSUMERS, load_host_secret_contract
from app.ops.host_secret_controller import HostSecretController, HostSecretOperation, TerminalEvidence
from app.ops.pg_acceptance import PROFILE_VERSION, SELECTION_HASH, require_pass
from app.ops.secret_admin import SecretAdmin, SecretHistory, _note

if TYPE_CHECKING:
    from app.ops.karakeep_deploy import KarakeepPlan


_IMAGE_PULL_FAILURE_CLASSES = frozenset({
    'registry_unauthorized', 'registry_denied', 'registry_manifest_unknown',
    'registry_rate_limited', 'unclassified',
})


class PostgresDeployError(RuntimeError):
    image_pull_failure: str | None = None

    def __init__(self, *, image_pull_failure: str | None = None) -> None:
        super().__init__('database deployment refused; matching terminal evidence required')
        if image_pull_failure is not None:
            self.image_pull_failure = (
                image_pull_failure
                if type(image_pull_failure) is str and image_pull_failure in _IMAGE_PULL_FAILURE_CLASSES
                else 'unclassified'
            )


@dataclass(frozen=True)
class AuthorityCutover:
    """Explicit existing selection; retained only in the private request."""
    binding_id: str
    root: str
    ownership_root: str

    def validate(self) -> None:
        if (not isinstance(self.binding_id, str)
            or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', self.binding_id) is None
            or any(not isinstance(value, str) or not value.startswith('/')
                   or value == '/' or any(c in value for c in ('\x00', '\n', '\r', ':'))
                   or str(Path(value)) != value or '..' in Path(value).parts
                   for value in (self.root, self.ownership_root))):
            raise PostgresDeployError()


@dataclass(frozen=True)
class DeployPlan:
    channel: str
    revision: str
    services: tuple[str, ...]
    consumers: tuple[str, ...]
    ack_forward_only: bool = False
    image_digest: str | None = None
    automatic: bool = False
    authority_cutover: AuthorityCutover | None = None
    promotion_plan: str | None = None
    principal_cutover: bool = False
    activation_scope: str = 'full'

    def payload(self) -> dict[str, Any]:
        """Keep retained manual request bindings compatible with older workers."""
        payload = asdict(self)
        if self.activation_scope == 'full':
            del payload['activation_scope']
        if not self.principal_cutover:
            del payload['principal_cutover']
        if self.authority_cutover is None:
            del payload['authority_cutover']
        if self.promotion_plan is None:
            del payload['promotion_plan']
        if self.image_digest is None and not self.automatic:
            del payload['image_digest']
            del payload['automatic']
        if self.automatic:
            payload['verification_profile'] = {'version': PROFILE_VERSION, 'selection_hash': SELECTION_HASH}
        return payload

    @classmethod
    def from_payload(cls, raw: Any) -> DeployPlan:
        legacy = {'channel', 'revision', 'services', 'consumers', 'ack_forward_only'}
        if not isinstance(raw, dict):
            raise PostgresDeployError()
        keys = set(raw) - {'authority_cutover', 'promotion_plan', 'principal_cutover', 'activation_scope'}
        if keys not in (legacy, legacy | {'image_digest', 'automatic'},
                        legacy | {'image_digest', 'automatic', 'verification_profile'}):
            raise PostgresDeployError()
        cutover = None
        if raw.get('authority_cutover') is not None:
            selected = raw['authority_cutover']
            if not isinstance(selected, dict) or set(selected) != {'binding_id', 'root', 'ownership_root'}:
                raise PostgresDeployError()
            cutover = AuthorityCutover(**selected)
        plan = cls(raw['channel'], raw['revision'], tuple(raw['services']), tuple(raw['consumers']),
                   raw['ack_forward_only'], raw.get('image_digest'), raw.get('automatic', False), cutover,
                   raw.get('promotion_plan'), raw.get('principal_cutover', False),
                   raw.get('activation_scope', 'full'))
        plan.validate()
        canonical_raw = dict(raw)
        if canonical_raw.get('principal_cutover') is False:
            del canonical_raw['principal_cutover']
        if canonical_raw.get('activation_scope') == 'full':
            del canonical_raw['activation_scope']
        if (plan.automatic and canonical_raw != json.loads(json.dumps(plan.payload()))
            or not plan.automatic and 'verification_profile' in raw):
            raise PostgresDeployError()
        return plan

    def validate(self) -> None:
        from app.config.activation_scope import validate_activation_scope
        try:
            validate_activation_scope(self.activation_scope, self.channel)
        except (ValueError, TypeError):
            raise PostgresDeployError() from None
        if self.activation_scope == 'text-capture' and (
            not self.automatic or self.authority_cutover is not None
            or self.principal_cutover or self.promotion_plan is not None
        ):
            raise PostgresDeployError()
        if type(self.principal_cutover) is not bool or (self.principal_cutover and (
            self.channel not in {'dev', 'test'} or self.image_digest is None
            or self.authority_cutover is not None or self.promotion_plan is not None
        )):
            raise PostgresDeployError()
        if self.promotion_plan is not None and (
            self.channel != 'prod' or self.automatic
            or not isinstance(self.promotion_plan, str)
            or not Path(self.promotion_plan).is_absolute()
            or len(self.promotion_plan) > 4096 or '\0' in self.promotion_plan
        ):
            raise PostgresDeployError()
        if self.authority_cutover is not None:
            if (not isinstance(self.authority_cutover, AuthorityCutover)
                or self.channel not in {'dev', 'test'} or self.automatic):
                raise PostgresDeployError()
            self.authority_cutover.validate()
        contract = load_host_secret_contract()
        if (type(self.ack_forward_only) is not bool or type(self.automatic) is not bool
            or self.channel not in CHANNEL_PROJECTS or len(self.revision) != 40
            or any(c not in '0123456789abcdef' for c in self.revision)
            or not self.services or len(set(self.services)) != len(self.services)
            or not self.consumers or len(set(self.consumers)) != len(self.consumers)):
            raise PostgresDeployError()
        if self.image_digest is not None and (
            not isinstance(self.image_digest, str)
            or re.fullmatch(r'sha256:[0-9a-f]{64}', self.image_digest) is None
        ):
            raise PostgresDeployError()
        if self.automatic and (
            self.channel not in {'dev', 'test'} or self.image_digest is None or self.ack_forward_only
        ):
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
class TestRecoveryRequest:
    """Authenticated TEST-only reset or reconstruction request.

    A reset request names the original failed authority-cutover operation.
    Reconstruction additionally names that operation in ``source_operation_id``
    and uses ``failed_operation_id`` for the terminal failed automatic
    successor.  Keeping both identities prevents a fresh candidate from being
    confused with either historical operation.
    """

    failed_operation_id: str
    plan: DeployPlan
    authority_cutover: AuthorityCutover
    source_operation_id: str | None = None
    source_plan: DeployPlan | None = None

    def validate(self) -> None:
        if (not isinstance(self.failed_operation_id, str)
            or not isinstance(self.plan, DeployPlan)
            or not isinstance(self.authority_cutover, AuthorityCutover)):
            raise PostgresDeployError()
        try:
            canonical_operation_id = str(UUID(self.failed_operation_id))
            canonical_source_operation_id = (
                str(UUID(self.source_operation_id))
                if self.source_operation_id is not None else None
            )
        except (ValueError, TypeError, AttributeError):
            raise PostgresDeployError() from None
        if (canonical_operation_id != self.failed_operation_id
            or canonical_source_operation_id != self.source_operation_id
            or self.source_operation_id == self.failed_operation_id
            or self.plan.channel != 'test'
            or not self.plan.automatic
            or self.plan.authority_cutover is not None
            or self.plan.principal_cutover
            or self.plan.image_digest is None
            or (self.source_operation_id is None) != (self.source_plan is None)):
            raise PostgresDeployError()
        self.plan.validate()
        self.authority_cutover.validate()
        if self.source_plan is not None:
            self.validate_source_plan(self.source_plan)

    def validate_failed_plan(self, failed_plan: DeployPlan) -> None:
        """Authenticate the journal-bound cutover independently of the successor.

        The request carries the fresh automatic candidate.  The failed plan is
        deliberately reconstructed from the VM's exact operation binding so a
        caller cannot replace it with a second, caller-supplied plan.  Only the
        candidate/runtime fields are shared; the failed operation remains a
        non-automatic authority cutover with the separately authenticated
        authority tuple.
        """
        self.validate()
        if not isinstance(failed_plan, DeployPlan):
            raise PostgresDeployError()
        failed_plan.validate()
        if self.source_operation_id is None:
            if (failed_plan.channel != 'test'
                or failed_plan.automatic
                or failed_plan.authority_cutover is None
                or failed_plan.authority_cutover != self.authority_cutover):
                raise PostgresDeployError()
            # The first automatic successor is bound to the retained cutover.
            for field in ('channel', 'revision', 'services', 'consumers'):
                if getattr(failed_plan, field) != getattr(self.plan, field):
                    raise PostgresDeployError()
            if (failed_plan.image_digest is not None
                and failed_plan.image_digest != self.plan.image_digest):
                raise PostgresDeployError()
            return
        # Reconstruction is authorized by a distinct terminal automatic
        # successor.  Its candidate bytes may differ from the new plan, while
        # its runtime surface must remain the same bounded TEST profile.
        if (failed_plan.channel != 'test'
            or not failed_plan.automatic
            or failed_plan.authority_cutover is not None
            or failed_plan.principal_cutover
            or failed_plan.image_digest is None):
            raise PostgresDeployError()
        for field in ('channel', 'services', 'consumers'):
            if getattr(failed_plan, field) != getattr(self.plan, field):
                raise PostgresDeployError()

    def validate_source_plan(self, source_plan: DeployPlan) -> None:
        """Validate the host-retained request for the completed reset."""
        if self.source_operation_id is None or not isinstance(source_plan, DeployPlan):
            raise PostgresDeployError()
        source_plan.validate()
        if (source_plan.channel != 'test'
            or not source_plan.automatic
            or source_plan.authority_cutover is not None
            or source_plan.principal_cutover
            or source_plan.image_digest is None):
            raise PostgresDeployError()
        for field in ('channel', 'services', 'consumers'):
            if getattr(source_plan, field) != getattr(self.plan, field):
                raise PostgresDeployError()

    def payload(self) -> dict[str, Any]:
        self.validate()
        payload = {
            'failed_operation_id': self.failed_operation_id,
            'plan': self.plan.payload(),
            'authority_cutover': asdict(self.authority_cutover),
        }
        if self.source_operation_id is not None:
            if self.source_plan is None:
                raise PostgresDeployError()
            payload['source_operation_id'] = self.source_operation_id
            payload['source_plan'] = self.source_plan.payload()
        return payload

    @classmethod
    def from_payload(cls, raw: Any) -> TestRecoveryRequest:
        if (not isinstance(raw, dict)
            or set(raw) not in (
                {'failed_operation_id', 'plan', 'authority_cutover'},
                {
                    'failed_operation_id', 'source_operation_id', 'source_plan',
                    'plan', 'authority_cutover',
                },
            )
            or not isinstance(raw['authority_cutover'], dict)
            or set(raw['authority_cutover']) != {'binding_id', 'root', 'ownership_root'}):
            raise PostgresDeployError()
        request = cls(
            raw['failed_operation_id'], DeployPlan.from_payload(raw['plan']),
            AuthorityCutover(**raw['authority_cutover']), raw.get('source_operation_id'),
            DeployPlan.from_payload(raw['source_plan']) if 'source_plan' in raw else None,
        )
        request.validate()
        return request


@dataclass(frozen=True)
class DeployReceipt:
    operation_id: str
    channel: str
    kind: str
    stage: str
    terminal_result: str | None
    pg_acceptance: dict[str, Any] | None = None
    source_failure: str | None = None
    activation_scope: str = 'full'

    def payload(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.activation_scope == 'full':
            del payload['activation_scope']
        if self.pg_acceptance is None:
            del payload['pg_acceptance']
        if self.source_failure is None:
            del payload['source_failure']
        return payload

    def require_profile(self, plan: DeployPlan) -> None:
        if self.activation_scope != plan.activation_scope:
            raise PostgresDeployError()
        if plan.automatic and self.terminal_result == 'committed':
            try:
                require_pass(self.pg_acceptance, plan.revision, plan.image_digest or '',
                             plan.channel, self.operation_id)
            except Exception:
                raise PostgresDeployError() from None

    def validate(self) -> None:
        from app.config.activation_scope import validate_activation_scope
        try:
            validate_activation_scope(self.activation_scope, self.channel)
        except (ValueError, TypeError):
            raise PostgresDeployError() from None
        from app.ops.native_source_bootstrap import SOURCE_PROJECTION_FAILURE_REASONS
        if self.source_failure is not None and (
            self.source_failure not in SOURCE_PROJECTION_FAILURE_REASONS
            or self.stage not in {'activating', 'failed'}
        ):
            raise PostgresDeployError()
        if (str(UUID(self.operation_id)) != self.operation_id or self.channel not in CHANNEL_PROJECTS
            or self.kind != 'deploy'
            or self.stage not in {'prepared', 'preflighted', 'materialized', 'authenticating', 'activating', 'verifying', 'committed', 'aborted', 'failed'}
            or self.terminal_result != (self.stage if self.stage in {'committed', 'aborted', 'failed'} else None)):
            raise PostgresDeployError()
        if self.pg_acceptance is not None:
            try:
                if self.stage != 'committed':
                    raise PostgresDeployError()
                require_pass(self.pg_acceptance, self.pg_acceptance['source_sha'],
                             self.pg_acceptance['image_digest'], self.channel, self.operation_id)
            except Exception:
                raise PostgresDeployError() from None

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

    def _read_json(self, name: str, *, limit: int) -> dict[str, Any] | None:
        if not self.directory.exists() and not self.directory.is_symlink():
            return None
        with self._directory() as directory:
            try:
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            except FileNotFoundError:
                return None
            with os.fdopen(descriptor, 'r') as source:
                info = os.fstat(source.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > limit or info.st_nlink != 1):
                    raise PostgresDeployError()
                try:
                    payload = json.load(source)
                    if not isinstance(payload, dict):
                        raise ValueError
                    return payload
                except Exception:
                    raise PostgresDeployError() from None

    def _write_json(self, name: str, payload: dict[str, Any]) -> None:
        with self._directory() as directory:
            temporary = name + '.' + str(uuid4()) + '.tmp'
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                dir_fd=directory,
            )
            try:
                with os.fdopen(descriptor, 'wb') as target:
                    target.write((json.dumps(payload, sort_keys=True) + '\n').encode())
                    target.flush()
                    os.fsync(target.fileno())
                os.rename(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass

    def _store_exact_json(self, name: str, payload: dict[str, Any], *, limit: int) -> None:
        prior = self._read_json(name, limit=limit)
        if prior is not None:
            if prior != payload:
                raise PostgresDeployError()
            return
        self._write_json(name, payload)

    @staticmethod
    def _operation_name(operation_id: str, suffix: str) -> str:
        try:
            valid = type(operation_id) is str and str(UUID(operation_id)) == operation_id
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise PostgresDeployError()
        return f'{operation_id}.{suffix}.json'

    @staticmethod
    def _request_plan(raw: Any) -> DeployPlan | KarakeepPlan:
        if isinstance(raw, dict) and set(raw) == {'channel', 'revision'}:
            from app.ops.karakeep_deploy import KarakeepPlan

            plan = KarakeepPlan(raw['channel'], raw['revision'])
            plan.validate()
            return plan
        return DeployPlan.from_payload(raw)

    def _validated_request(
        self, raw: Any, *, operation_id: str | None = None,
    ) -> tuple[dict[str, Any], DeployPlan | KarakeepPlan]:
        if (not isinstance(raw, dict) or set(raw) != {'operation_id', 'plan', 'bootstrap'}
            or type(raw.get('bootstrap')) is not bool):
            raise PostgresDeployError()
        try:
            selected_id = str(raw['operation_id'])
            if str(UUID(selected_id)) != selected_id or (
                operation_id is not None and selected_id != operation_id
            ):
                raise PostgresDeployError()
            plan = self._request_plan(raw['plan'])
        except Exception:
            raise PostgresDeployError() from None
        if plan.channel != self.channel:
            raise PostgresDeployError()
        canonical = json.loads(json.dumps({
            'operation_id': selected_id,
            'plan': plan.payload(),
            'bootstrap': raw['bootstrap'],
        }))
        if canonical != raw:
            raise PostgresDeployError()
        return canonical, plan

    def operation_request(
        self, operation_id: str,
    ) -> tuple[dict[str, Any], DeployPlan | KarakeepPlan] | None:
        """Read the exact historical request for one ID, if retained."""
        name = self._operation_name(operation_id, 'request')
        stored = self._read_json(name, limit=8192)
        if stored is not None:
            return self._validated_request(stored, operation_id=operation_id)
        current = self._read_json(self.channel + '.request.json', limit=8192)
        if current is None:
            return None
        validated = self._validated_request(current)
        return validated if validated[0]['operation_id'] == operation_id else None

    def current_request(self) -> tuple[dict[str, Any], DeployPlan | KarakeepPlan] | None:
        """Read and validate only the latest request slot, without historical fallback."""
        current = self._read_json(self.channel + '.request.json', limit=8192)
        return None if current is None else self._validated_request(current)

    def operation_receipt(self, operation_id: str) -> DeployReceipt | None:
        name = self._operation_name(operation_id, 'receipt')
        stored = self._read_json(name, limit=4096)
        receipt = None
        if stored is not None:
            try:
                receipt = DeployReceipt(**stored)
                receipt.validate()
            except Exception:
                raise PostgresDeployError() from None
            if (receipt.operation_id != operation_id or receipt.channel != self.channel
                or receipt.terminal_result not in {'committed', 'aborted', 'failed'}):
                raise PostgresDeployError()
        else:
            current = self.read()
            if current is not None and current.operation_id == operation_id and current.terminal_result is not None:
                receipt = current
        if receipt is not None:
            request = self.operation_request(operation_id)
            if request is not None and isinstance(request[1], DeployPlan):
                receipt.require_profile(request[1])
        return receipt

    @staticmethod
    def plan_fingerprint(plan: DeployPlan) -> str:
        canonical = json.dumps(plan.payload(), sort_keys=True, separators=(',', ':')).encode()
        return hashlib.sha256(canonical).hexdigest()

    def unknown_tombstone(self, operation_id: str) -> dict[str, Any] | None:
        name = self._operation_name(operation_id, 'unknown')
        raw = self._read_json(name, limit=16384)
        if raw is None:
            return None
        if not isinstance(raw, dict) or set(raw) != {
            'contract', 'operation_id', 'channel', 'plan', 'plan_sha256', 'bootstrap', 'outcome', 'proof',
        }:
            raise PostgresDeployError()
        try:
            plan = self._request_plan(raw['plan'])
        except Exception:
            raise PostgresDeployError() from None
        proof = raw.get('proof')
        identity = proof.get('channel_lock_identity') if isinstance(proof, dict) else None
        if (not isinstance(identity, dict) or set(identity) != {'device', 'inode', 'changed_ns'}
            or any(type(identity.get(key)) is not int or identity[key] < 0
                   for key in ('device', 'inode', 'changed_ns'))):
            raise PostgresDeployError()
        if not isinstance(plan, DeployPlan):
            raise PostgresDeployError()
        expected = {
            'contract': 'native-unknown-deploy-fence.v1',
            'operation_id': operation_id,
            'channel': self.channel,
            'plan': plan.payload(),
            'plan_sha256': self.plan_fingerprint(plan),
            'bootstrap': False,
            'outcome': 'unknown',
            'proof': {
                'channel_lock_acquired': True,
                'channel_lock_identity': identity,
                'worker_quiescent': True,
                'owned_one_offs_quiescent': True,
                'replay_fence_durable': True,
            },
        }
        if (plan.channel != self.channel or raw != json.loads(json.dumps(expected))
            or plan.authority_cutover is not None or plan.principal_cutover
            or plan.channel not in {'dev', 'test'}):
            raise PostgresDeployError()
        return raw

    def _has_unknown_fence_for_request(self, operation_id: str) -> bool:
        tombstone = self.unknown_tombstone(operation_id)
        if tombstone is None:
            return False
        request = self.operation_request(operation_id)
        if request is None:
            return True
        return (
            isinstance(request[1], DeployPlan)
            and request[0]['bootstrap'] is False
            and json.loads(json.dumps(request[1].payload())) == tombstone['plan']
        )

    def _has_retained_terminal(self, receipt: DeployReceipt) -> bool:
        request_name = self._operation_name(receipt.operation_id, 'request')
        receipt_name = self._operation_name(receipt.operation_id, 'receipt')
        raw_request = self._read_json(request_name, limit=8192)
        raw_receipt = self._read_json(receipt_name, limit=4096)
        if raw_request is None or raw_receipt is None:
            return False
        try:
            request, plan = self._validated_request(raw_request, operation_id=receipt.operation_id)
            retained = DeployReceipt(**raw_receipt)
            retained.validate()
        except Exception:
            return False
        if (plan.channel != self.channel or retained.payload() != receipt.payload()):
            return False
        if isinstance(plan, DeployPlan):
            try:
                retained.require_profile(plan)
            except Exception:
                return False
        self._store_exact_json(request_name, raw_request, limit=8192)
        self._store_exact_json(receipt_name, raw_receipt, limit=4096)
        return True

    def _unknown_fence_allows_request_supersession(
        self, request_id: str, receipt: DeployReceipt | None,
    ) -> bool:
        if not self._has_unknown_fence_for_request(request_id):
            return False
        if receipt is None:
            return True
        if receipt.operation_id == request_id:
            return receipt.terminal_result is None
        if receipt.terminal_result is None:
            return False
        return self._has_retained_terminal(receipt)

    def can_admit_request_after_current(self, operation_id: str, receipt: DeployReceipt | None) -> bool:
        """Check whether latest request/receipt state permits this exact new ID."""
        current = self._read_json(self.channel + '.request.json', limit=8192)
        current_id = None
        if current is not None:
            validated, _plan = self._validated_request(current)
            current_id = validated['operation_id']
        if current_id == operation_id:
            # This ID already occupies the current request slot. Treating a
            # missing or foreign receipt as admission evidence would replay a
            # retained operation after worker loss.
            return receipt is not None and receipt.operation_id == operation_id
        if current_id is None:
            if receipt is None:
                return True
            if receipt.terminal_result is None:
                return self._has_unknown_fence_for_request(receipt.operation_id)
            return self._has_retained_terminal(receipt)
        if receipt is not None and current_id == receipt.operation_id:
            if receipt.terminal_result is None:
                return self._has_unknown_fence_for_request(receipt.operation_id)
            return True
        if not self._has_unknown_fence_for_request(current_id):
            return False
        if receipt is None:
            return True
        if receipt.terminal_result is None:
            return False
        return self._has_retained_terminal(receipt)

    def fence_unknown(
        self, operation_id: str, plan: DeployPlan, *,
        channel_lock_identity: tuple[int, int, int],
    ) -> dict[str, Any]:
        plan.validate()
        if (not isinstance(channel_lock_identity, tuple) or len(channel_lock_identity) != 3
            or any(type(value) is not int or value < 0 for value in channel_lock_identity)):
            raise PostgresDeployError()
        if (plan.channel != self.channel or plan.channel not in {'dev', 'test'}
            or plan.authority_cutover is not None or plan.principal_cutover):
            raise PostgresDeployError()
        existing = self.unknown_tombstone(operation_id)
        if existing is not None:
            if existing['plan_sha256'] != self.plan_fingerprint(plan):
                raise PostgresDeployError()
            return existing
        if self.operation_receipt(operation_id) is not None:
            raise PostgresDeployError()
        request = self.operation_request(operation_id)
        if request is not None and (
            not isinstance(request[1], DeployPlan)
            or request[1] != plan or request[0]['bootstrap'] is not False
        ):
            raise PostgresDeployError()
        if request is not None:
            request_payload = json.loads(json.dumps({
                'operation_id': operation_id, 'plan': plan.payload(), 'bootstrap': False,
            }))
            self._store_exact_json(self._operation_name(operation_id, 'request'), request_payload, limit=8192)
        tombstone = {
            'contract': 'native-unknown-deploy-fence.v1',
            'operation_id': operation_id,
            'channel': self.channel,
            'plan': plan.payload(),
            'plan_sha256': self.plan_fingerprint(plan),
            'bootstrap': False,
            'outcome': 'unknown',
            'proof': {
                'channel_lock_acquired': True,
                'channel_lock_identity': {
                    'device': channel_lock_identity[0],
                    'inode': channel_lock_identity[1],
                    'changed_ns': channel_lock_identity[2],
                },
                'worker_quiescent': True,
                'owned_one_offs_quiescent': True,
                'replay_fence_durable': True,
            },
        }
        self._store_exact_json(self._operation_name(operation_id, 'unknown'),
                               json.loads(json.dumps(tombstone)), limit=16384)
        return tombstone

    def bind_request(self, operation_id: str, plan: DeployPlan | KarakeepPlan, bootstrap: bool, *, create: bool = False) -> None:
        """Bind the same-ID receipt to immutable, value-free request inputs.

        Persist before preparing the worker. A partial or missing binding can
        never turn an old terminal receipt into success for a different request.
        """
        plan.validate()
        if type(bootstrap) is not bool:
            raise PostgresDeployError()
        if isinstance(plan, DeployPlan) and (plan.authority_cutover is not None or plan.principal_cutover) and bootstrap:
            raise PostgresDeployError()
        DeployReceipt(operation_id, self.channel, 'deploy', 'prepared', None).validate()
        expected = {'operation_id': operation_id, 'plan': plan.payload(), 'bootstrap': bootstrap}
        # Normalize tuples to the on-disk JSON representation before comparison.
        expected = json.loads(json.dumps(expected))
        if self.unknown_tombstone(operation_id) is not None:
            raise PostgresDeployError()
        retained = self._read_json(self._operation_name(operation_id, 'request'), limit=8192)
        if retained is not None:
            prior_retained, retained_plan = self._validated_request(retained, operation_id=operation_id)
            if prior_retained != expected or retained_plan != plan:
                raise PostgresDeployError()
            if create:
                # A retained request is durable evidence that this ID was
                # already admitted. It may be read or reconciled, never used
                # to create another worker.
                raise PostgresDeployError()
            terminal = self.operation_receipt(operation_id)
            if terminal is not None:
                if isinstance(plan, DeployPlan):
                    terminal.require_profile(plan)
                return
            current = self._read_json(self.channel + '.request.json', limit=8192)
            if current is None or self._validated_request(current)[0] != expected:
                raise PostgresDeployError()
            current_receipt = self.read()
            if current_receipt is not None and current_receipt.operation_id != operation_id:
                raise PostgresDeployError()
            return
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
            if prior is not None:
                prior, prior_plan = self._validated_request(prior)
            if prior == expected:
                if create:
                    raise PostgresDeployError()
                self._store_exact_json(self._operation_name(operation_id, 'request'), expected, limit=8192)
                return
            if not create or (prior and prior.get('operation_id') == operation_id):
                raise PostgresDeployError()
            receipt = self.read()
            if prior is None and receipt is not None:
                raise PostgresDeployError()
            if prior is not None and receipt is None:
                if not self._unknown_fence_allows_request_supersession(prior['operation_id'], None):
                    raise PostgresDeployError()
            elif prior is not None and receipt is not None:
                if receipt.operation_id == prior['operation_id']:
                    if (receipt.terminal_result is None
                        and not self._unknown_fence_allows_request_supersession(
                            prior['operation_id'], receipt,
                        )):
                        raise PostgresDeployError()
                    if receipt.terminal_result is not None:
                        if isinstance(prior_plan, DeployPlan):
                            receipt.require_profile(prior_plan)
                        self._store_exact_json(
                            self._operation_name(receipt.operation_id, 'receipt'),
                            json.loads(json.dumps(receipt.payload())), limit=4096,
                        )
                elif not self._unknown_fence_allows_request_supersession(prior['operation_id'], receipt):
                    raise PostgresDeployError()
            if prior is not None:
                self._store_exact_json(self._operation_name(prior['operation_id'], 'request'), prior, limit=8192)
                if prior_plan.channel != self.channel:
                    raise PostgresDeployError()
            elif receipt is not None:
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
            self._store_exact_json(self._operation_name(operation_id, 'request'), expected, limit=8192)

    def _bound_request(self, operation_id: str | None) -> dict[str, Any]:
        with self._directory() as directory:
            descriptor = os.open(self.channel + '.request.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=directory)
            with os.fdopen(descriptor, 'r') as source:
                info = os.fstat(source.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 8192 or info.st_nlink != 1):
                    raise PostgresDeployError()
                request = json.load(source)
        if (not isinstance(request, dict) or set(request) != {'operation_id', 'plan', 'bootstrap'}
            or (operation_id is not None and request['operation_id'] != operation_id)):
            raise PostgresDeployError()
        return request

    def bound_plan(self, operation_id: str) -> DeployPlan:
        """Load and validate the exact current request used by authority checks."""
        request = self._bound_request(operation_id)
        canonical, selected = self._validated_request(request, operation_id=operation_id)
        if not isinstance(selected, DeployPlan):
            raise PostgresDeployError()
        if ((selected.authority_cutover is not None or selected.principal_cutover)
            and canonical['bootstrap']):
            raise PostgresDeployError()
        if self.unknown_tombstone(operation_id) is not None:
            raise PostgresDeployError()
        retained = self._read_json(self._operation_name(operation_id, 'request'), limit=8192)
        if retained is not None:
            retained_request, retained_plan = self._validated_request(
                retained, operation_id=operation_id,
            )
            if retained_request != canonical or retained_plan != selected:
                raise PostgresDeployError()
        return selected

    def write(self, operation_id: str, stage: str,
              pg_acceptance: dict[str, Any] | None = None) -> DeployReceipt:
        if self.unknown_tombstone(operation_id) is not None:
            raise PostgresDeployError()
        scope = 'full'
        current_request = self._read_json(self.channel + '.request.json', limit=8192)
        if current_request is not None:
            current_request, current_plan = self._validated_request(current_request)
            if current_request['operation_id'] == operation_id and isinstance(current_plan, DeployPlan):
                scope = current_plan.activation_scope
        receipt = DeployReceipt(operation_id, self.channel, 'deploy', stage,
                                stage if stage in {'committed', 'aborted', 'failed'} else None, pg_acceptance,
                                activation_scope=scope)
        previous = self.read()
        request_bound = self.operation_request(operation_id)
        if previous and previous.operation_id == operation_id and previous.source_failure is not None:
            receipt = DeployReceipt(operation_id, self.channel, 'deploy', stage,
                                    receipt.terminal_result, pg_acceptance, previous.source_failure, scope)
        receipt.validate()
        successors = {
            'prepared': {'preflighted', 'aborted'}, 'preflighted': {'materialized', 'aborted'},
            'materialized': {'authenticating', 'activating', 'aborted'},
            'authenticating': {'activating', 'aborted'}, 'activating': {'verifying', 'committed', 'aborted', 'failed'},
            'verifying': {'committed', 'failed'},
        }
        if previous and previous.terminal_result is None:
            advancing = (
                previous.operation_id == operation_id
                and stage in successors.get(previous.stage, set())
            )
            superseding_unknown = (
                previous.operation_id != operation_id
                and stage == 'prepared'
                and request_bound is not None
                and request_bound[0]['operation_id'] == operation_id
                and self._unknown_fence_allows_request_supersession(previous.operation_id, previous)
            )
            if not advancing and not superseding_unknown:
                raise PostgresDeployError()
        elif stage != 'prepared' or (previous and previous.operation_id == operation_id):
            raise PostgresDeployError()
        return self._persist(receipt)

    def record_source_failure(self, operation_id: str, revision: str, reason: str) -> None:
        previous = self.read()
        plan = self.bound_plan(operation_id)
        if (previous is None or previous.operation_id != operation_id or previous.stage not in {'activating', 'failed'}
            or plan.revision != revision or previous.source_failure not in {None, reason}):
            raise PostgresDeployError()
        if previous.source_failure == reason:
            if previous.terminal_result == 'failed':
                self._retain_source_failure_receipt(previous, previous)
            return
        receipt = DeployReceipt(operation_id, self.channel, 'deploy', previous.stage, previous.terminal_result,
                                source_failure=reason, activation_scope=plan.activation_scope)
        receipt.validate()
        if receipt.terminal_result == 'failed':
            self._retain_source_failure_receipt(previous, receipt)
        self._persist(receipt)

    def _retain_source_failure_receipt(
        self, previous: DeployReceipt, updated: DeployReceipt,
    ) -> None:
        """Allow only the supported late source diagnostic on a failed terminal."""
        if (previous.operation_id != updated.operation_id
            or previous.channel != self.channel or updated.channel != self.channel
            or previous.terminal_result != 'failed' or updated.terminal_result != 'failed'
            or previous.stage != 'failed' or updated.stage != 'failed'
            or previous.source_failure not in {None, updated.source_failure}
            or updated.source_failure is None):
            raise PostgresDeployError()
        previous.validate()
        updated.validate()
        name = self._operation_name(updated.operation_id, 'receipt')
        expected = json.loads(json.dumps(updated.payload()))
        stored = self._read_json(name, limit=4096)
        if stored is None:
            self._store_exact_json(name, expected, limit=4096)
            return
        try:
            retained = DeployReceipt(**stored)
            retained.validate()
        except Exception:
            raise PostgresDeployError() from None
        if retained.operation_id != updated.operation_id or retained.channel != self.channel:
            raise PostgresDeployError()
        if retained.payload() == expected:
            self._store_exact_json(name, expected, limit=4096)
            return
        baseline = DeployReceipt(
            updated.operation_id, updated.channel, updated.kind, updated.stage,
            updated.terminal_result, updated.pg_acceptance, activation_scope=updated.activation_scope,
        )
        if retained.payload() != json.loads(json.dumps(baseline.payload())):
            raise PostgresDeployError()
        self._write_json(name, expected)

    def _persist(self, receipt: DeployReceipt) -> DeployReceipt:
        with self._directory() as directory:
            temporary = self.channel + '.' + str(uuid4()) + '.tmp'
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(descriptor, 'wb') as target:
                    target.write((json.dumps(receipt.payload(), sort_keys=True) + '\n').encode())
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
    # Reuse one successful or absent lookup only within this preflight. The
    # worker calls this function again at each boundary to re-read BWS state.
    lookup_cache: dict[tuple[str, str], str | BwsItemAbsent] = {}
    try:
        values = {}
        for consumer in plan.consumers:
            values[consumer] = _resolve_bws_consumer_values(
                plan.channel, consumer, contract, reader, lookup_cache=lookup_cache
            )
        return values
    except Exception:
        raise PostgresDeployError() from None


def require_test_database_identity(conninfo: str, expected_address: str) -> None:
    """Bounded read-only native TEST identity probe, within the PG adapter."""
    import psycopg
    from app.db.dsn import resolve_dsn

    try:
        with psycopg.connect(resolve_dsn(conninfo), connect_timeout=5, autocommit=True) as connection:
            if connection.execute('SELECT current_database(), inet_server_addr()::text').fetchone() != (
                'app_test', expected_address
            ):
                raise PostgresDeployError()
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
    def verify(self, operation_id: str, plan: DeployPlan) -> dict[str, Any]: ...
    def cleanup_verification(self, operation_id: str, plan: DeployPlan) -> None: ...
    def quiescent(self) -> bool: ...


_POST_ACTIVATION_QUIESCENCE_POLL_SECONDS = 5.0
_POST_ACTIVATION_QUIESCENCE_TIMEOUT_SECONDS = 360.0


class DeployWorker:
    """Called only by the supervised same-ID worker while its VM lock is held."""
    def __init__(self, journal: DeployJournal, effects: VmEffects, *,
                 monotonic: Callable[[], float] | None = None,
                 sleep: Callable[[float], None] | None = None) -> None:
        self.journal = journal
        self.effects = effects
        self._prepared_id: str | None = None
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep

    def _wait_for_post_activation_quiescence(self) -> bool:
        deadline = self._monotonic() + _POST_ACTIVATION_QUIESCENCE_TIMEOUT_SECONDS
        while True:
            if self._monotonic() >= deadline:
                return False
            try:
                proven = self.effects.quiescent()
                if self._monotonic() >= deadline:
                    return False
                if proven:
                    return True
            except Exception:
                # An unavailable census is still an unproven predicate. Keep
                # the operation pending until the bounded observation period
                # expires rather than guessing a terminal outcome.
                pass
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return False
            self._sleep(min(_POST_ACTIVATION_QUIESCENCE_POLL_SECONDS, remaining))

    def prepare(self, operation_id: str) -> None:
        self.journal.write(operation_id, "prepared")
        self._prepared_id = operation_id

    def run(self, operation_id: str, plan: DeployPlan) -> DeployReceipt:
        plan.validate()
        if plan.authority_cutover is not None or plan.principal_cutover or plan.activation_scope != 'full':
            self.journal.bind_request(operation_id, plan, False)
        previous = self.journal.read()
        if previous and previous.operation_id == operation_id:
            if previous.terminal_result:
                previous.require_profile(plan)
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
            if not self._wait_for_post_activation_quiescence():
                raise PostgresDeployError()
            result = None
            if plan.automatic:
                self.journal.write(operation_id, 'verifying')
                try:
                    result = self.effects.verify(operation_id, plan)
                    require_pass(result, plan.revision, plan.image_digest or '', plan.channel, operation_id)
                except Exception:
                    # Activation has completed. Verification failure is local to
                    # this candidate once its owned scratch effects are removed.
                    self.effects.cleanup_verification(operation_id, plan)
                    if not self.effects.quiescent():
                        raise PostgresDeployError()
                    return self.journal.write(operation_id, 'failed')
            if result is None:
                return self.journal.write(operation_id, 'committed')
            return self.journal.write(operation_id, 'committed', result)
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
    def reconcile_failed(self, operation_id: str, plan: DeployPlan) -> DeployReceipt: ...
    def reconcile_unknown(self, operation_id: str, plan: DeployPlan) -> dict[str, Any]: ...
    def prove_absence(self, operation_id: str, plan: DeployPlan) -> dict[str, str | bool]: ...


def host_deploy_image_binding(plan: DeployPlan) -> str | None:
    """Retain only public image selectors and a fingerprint of the private plan."""
    if plan.channel not in {'dev', 'test'} or plan.image_digest is None:
        return None
    from app.ops.pg_acceptance import IMAGE_REPOSITORY
    return json.dumps({
        'schema': 'host-deploy-image-binding.v1', 'repository': IMAGE_REPOSITORY,
        'channel': plan.channel, 'revision': plan.revision, 'image_digest': plan.image_digest,
        'plan_fingerprint': DeployJournal.plan_fingerprint(plan),
    }, sort_keys=True, separators=(',', ':'))


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
                     *, qualified: Callable[[], None], allow_bootstrap: bool = True,
                     operation_id: str | None = None) -> DeployReceipt:
    """Hold the shared controller lock through matching remote terminal evidence."""
    if (type(allow_bootstrap) is not bool or (plan.automatic and allow_bootstrap)
        or (plan.authority_cutover is not None and allow_bootstrap)
        or (plan.principal_cutover and allow_bootstrap)
        or (operation_id is not None and not (plan.automatic or plan.authority_cutover is not None
                                             or plan.principal_cutover))):
        raise PostgresDeployError()
    plan.validate()
    if plan.channel in {'dev', 'test'} and plan.image_digest is None:
        raise PostgresDeployError()
    try:
        arguments: dict[str, Any] = {'allow_bootstrap': allow_bootstrap}
        binding = host_deploy_image_binding(plan)
        if binding is not None:
            arguments['deploy_image_binding'] = binding
            arguments['allow_legacy_terminal'] = operation_id is not None
        if operation_id is not None:
            arguments['operation_id'] = operation_id
        with admin.controller.deploy_operation(plan.channel, **arguments) as (operation, resumed):
            if operation_id is not None and resumed:
                try:
                    receipt = remote.reconcile_failed(operation.operation_id, plan)
                except Exception:
                    if operation.completed_result is not None:
                        # Never turn a completed operation into another send.
                        raise
                else:
                    receipt.require_profile(plan)
                    operation.finish(receipt.evidence())
                    return receipt
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
                    receipt.require_profile(plan)
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
                        receipt.require_profile(plan)
                        operation.finish(receipt.evidence())
                        return receipt
                    bootstrap_password(admin, operation, empty=True)
            if any(row['status'] not in {'ok', 'skipped'} for row in admin.check_selected(operation, plan.channel, plan.consumers)):
                raise PostgresDeployError()
            receipt = remote.activate(operation.operation_id, plan)
            receipt.require_profile(plan)
            operation.finish(receipt.evidence())
            return receipt
    except Exception:
        raise PostgresDeployError() from None
