"""MVR-06A: delegated background-runtime authority and the staged intent admin surface.

`docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md` (MVR-06A) makes this module the
owner of the *missing producer* for background identity, so the later lifecycle supervisor
never mints an identity of its own:

- one opaque, CSPRNG-minted ``background_runtime_role_id`` in a private, versioned,
  mode-``0600`` record beside the MVR-03 principal record,
- delegated from MVR-03's ``local_operator_role_id`` with schema, revision, and delegation
  provenance, and scoped to exactly the least-privilege background operations,
- independent of API-key rotation (the delegator's *role id* is pinned, not its credential
  revision), of human identity, and of ``appInstallId``,
- an ``auth_epoch`` that every GOV revocation advances; a revoked or stale delegation fails
  the startup preflight, so no background consumer can dispatch under it.

Ordering is the cutover's whole point (`run_background_authority_cutover`):

    MVR-05 fence present -> MVR-06 floor (schema v3) -> role/delegation -> staged intent

The floor commits first, in its own registry generation; the role write samples the floor
under the role lock; the intent is a later generation. A failure before the intent commits
compensates this attempt's role and floor, so the outcome is either the untouched
MVR-05/MVR-03 state or one complete MVR-06-compatible role and intent lineage.

The admin service is staged: list/inspect read durable intent without any write, and every
intent-changing command fails ``capability_not_ready`` until the MVR-06B supervisor handoff.
The legacy picker bridge stays the authoritative single-watcher owner meanwhile.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from app.instance._storage_boundary import (
    CapabilityNotReadyError,
    RegistryError,
    _require_storage_mutation_capability,
)
from app.instance.background_intent import (
    BACKGROUND_INTENT_KEY,
    HANDOFF_PENDING,
    INTENT_MODE_COMPATIBILITY,
    BackgroundBindingIntent,
    BackgroundIntentError,
)
from app.instance.local_operator_principal import (
    LocalOperatorPrincipalRecord,
    LocalOperatorPrincipalStore,
    PrincipalPreflightError,
)
from app.instance.settings_rebind import SettingsRebindRecord
from app.instance.vault_registry import (
    MINIMUM_RUNTIME_SCHEMA_KEY,
    MVR05_MINIMUM_RUNTIME_SCHEMA,
    MVR06_MINIMUM_RUNTIME_SCHEMA,
    RegistrySnapshot,
    VaultRegistryStore,
)

BACKGROUND_RUNTIME_ROLE_SCHEMA = "agentic-pkm.background-runtime-role.v1"
BACKGROUND_ROLE_RECORD_FILENAME = "background-runtime-role.json"

#: The complete least-privilege scope set: only the watcher, worker, settings, queue, and
#: receipt operations an authorized binding's background lifecycle needs.
BACKGROUND_RUNTIME_SCOPES: tuple[str, ...] = (
    "queue.claim_ack",
    "receipt.write",
    "settings.reload",
    "watcher.ingest",
    "worker.dispatch",
)

#: The local operator role's delegable authority. A background role may hold only a subset;
#: anything outside this set exceeds its delegator, and anything inside it but outside the
#: least-privilege set is over-broad.
LOCAL_OPERATOR_DELEGABLE_SCOPES: frozenset[str] = frozenset(
    BACKGROUND_RUNTIME_SCOPES
    + (
        "background_intent.manage",
        "content.governed_write",
        "instance.admin",
        "principal.manage",
    )
)

DELEGATOR_KIND = "delegated_operator_role"

STATUS_ACTIVE: Final = "active"
STATUS_REVOKED: Final = "revoked"

PROVENANCE_EXISTING_INSTALL = "existing_install_migration"
PROVENANCE_CHANNEL_BOOTSTRAP = "channel_bootstrap"
PROVENANCE_NATIVE_BOOTSTRAP = "native_bootstrap"
PROVENANCE_REDELEGATION = "governed_redelegation"
BOOTSTRAP_PROVENANCES: Mapping[str, str] = {
    "existing-install": PROVENANCE_EXISTING_INSTALL,
    "channel": PROVENANCE_CHANNEL_BOOTSTRAP,
    "native": PROVENANCE_NATIVE_BOOTSTRAP,
}
DELEGATION_PROVENANCES = frozenset(
    set(BOOTSTRAP_PROVENANCES.values()) | {PROVENANCE_REDELEGATION}
)

#: The background consumers whose startup preflight requires the delegated role once the
#: MVR-06 floor is recorded. The API is a foreground consumer and needs none.
BACKGROUND_CONSUMERS = frozenset({"watcher", "worker"})

_PROVISIONING_CUTOVER = (
    "run `python -m app.instance.runtime background-authority-cutover` inside the stopped "
    "deployment window"
)

RoleStatus = Literal["active", "revoked"]


class BackgroundAuthorityPreflightError(PrincipalPreflightError):
    """Missing, stale, ambiguous, over-broad, revoked, or partial background delegation."""


class BackgroundAuthorityFloorError(CapabilityNotReadyError):
    """A background role/delegation write was attempted before the MVR-06 floor."""


class BackgroundCutoverCompensationError(BackgroundAuthorityPreflightError):
    """The cutover failed and could not prove its own compensation completed."""


class BackgroundIntentNotReadyError(CapabilityNotReadyError):
    """Intent-changing commands stay sealed until the MVR-06B supervisor handoff."""

    error_code = "capability_not_ready"


@dataclass(frozen=True)
class BackgroundRuntimeRoleRecord:
    """The durable delegated background-runtime role."""

    revision: int
    background_runtime_role_id: str
    delegator_role_id: str
    scopes: tuple[str, ...]
    auth_epoch: int
    status: RoleStatus
    delegation_provenance: str
    created_at: float
    updated_at: float

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema": BACKGROUND_RUNTIME_ROLE_SCHEMA,
            "revision": self.revision,
            "background_runtime_role_id": self.background_runtime_role_id,
            "delegator_role_id": self.delegator_role_id,
            "delegator_kind": DELEGATOR_KIND,
            "scopes": list(self.scopes),
            "auth_epoch": self.auth_epoch,
            "status": self.status,
            "delegation_provenance": self.delegation_provenance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def receipt(self) -> dict[str, Any]:
        """Redaction-safe projection: opaque ids, scopes, epoch, provenance; no path."""

        return {
            "background_runtime_role_id": self.background_runtime_role_id,
            "delegator_role_id": self.delegator_role_id,
            "scopes": list(self.scopes),
            "auth_epoch": self.auth_epoch,
            "status": self.status,
            "role_revision": self.revision,
            "delegation_provenance": self.delegation_provenance,
        }


def _partial(message: str) -> BackgroundAuthorityPreflightError:
    return BackgroundAuthorityPreflightError(
        message,
        provisioning_action=(
            "restore the background role record from backup, or revoke and redelegate it"
        ),
    )


def _parse_role(payload: Mapping[str, Any]) -> BackgroundRuntimeRoleRecord:
    if payload.get("schema") != BACKGROUND_RUNTIME_ROLE_SCHEMA:
        raise BackgroundAuthorityPreflightError(
            "unknown background runtime role schema",
            provisioning_action="upgrade to an image that understands this role schema",
        )
    required = (
        "revision",
        "background_runtime_role_id",
        "delegator_role_id",
        "delegator_kind",
        "scopes",
        "auth_epoch",
        "status",
        "delegation_provenance",
        "created_at",
        "updated_at",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise _partial(f"partial background runtime role record; missing {missing}")
    revision = payload["revision"]
    epoch = payload["auth_epoch"]
    role_id = payload["background_runtime_role_id"]
    delegator = payload["delegator_role_id"]
    scopes = payload["scopes"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise _partial("background runtime role revision is invalid")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
        raise _partial("background runtime role auth epoch is invalid")
    if not isinstance(role_id, str) or not role_id.strip():
        raise _partial("background runtime role id is invalid")
    if not isinstance(delegator, str) or not delegator:
        raise _partial("background runtime role delegator is invalid")
    if payload["delegator_kind"] != DELEGATOR_KIND:
        raise _partial("background runtime role delegator kind is invalid")
    if not isinstance(scopes, list) or any(not isinstance(item, str) for item in scopes):
        raise _partial("background runtime role scopes are invalid")
    if scopes != sorted(set(scopes)):
        raise _partial("background runtime role scopes are not canonical")
    if payload["status"] not in {STATUS_ACTIVE, STATUS_REVOKED}:
        raise _partial("background runtime role status is invalid")
    if payload["delegation_provenance"] not in DELEGATION_PROVENANCES:
        raise _partial("background runtime role delegation provenance is invalid")
    return BackgroundRuntimeRoleRecord(
        revision=revision,
        background_runtime_role_id=role_id,
        delegator_role_id=delegator,
        scopes=tuple(scopes),
        auth_epoch=epoch,
        status=payload["status"],
        delegation_provenance=str(payload["delegation_provenance"]),
        created_at=float(payload["created_at"]),
        updated_at=float(payload["updated_at"]),
    )


def _mint_role_id() -> str:
    """CSPRNG-minted; derived from nothing (not the delegator, credential, or install id)."""

    return f"brr_{secrets.token_hex(16)}"


class BackgroundRuntimeRoleStore:
    """Private, versioned, lock-protected store for the delegated background role.

    It reuses the MVR-03 principal store's private-file mechanics (0700 directory, 0600
    file, ``O_NOFOLLOW`` + ``fstat`` read, fsync'd atomic replace) rather than a second
    implementation. Mutations require the sealed storage capability.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._io = LocalOperatorPrincipalStore(self.path)

    def load(self) -> BackgroundRuntimeRoleRecord | None:
        if not self.path.exists():
            return None
        try:
            payload = self._io._read_private_json(self.path)
        except BackgroundAuthorityPreflightError:
            raise
        except PrincipalPreflightError as error:
            # The shared private-file reader names the MVR-03 record; restate it for
            # this record so an unsafe role file is a background-authority refusal.
            raise BackgroundAuthorityPreflightError(
                f"background runtime role record is unsafe or unreadable ({error})",
                provisioning_action=error.provisioning_action,
            ) from error
        return _parse_role(payload)

    def require(self) -> BackgroundRuntimeRoleRecord:
        record = self.load()
        if record is None:
            raise BackgroundAuthorityPreflightError(
                "no delegated background runtime role is provisioned",
                provisioning_action=_PROVISIONING_CUTOVER,
            )
        return record

    def _write(self, record: BackgroundRuntimeRoleRecord) -> None:
        self._io._atomic_private_write(self.path, self._io._serialize(record.as_payload()))

    def bootstrap(
        self,
        *,
        delegator: LocalOperatorPrincipalRecord,
        delegation_provenance: str,
        floor_guard: Callable[[], bool],
        _capability: Any = None,
    ) -> tuple[BackgroundRuntimeRoleRecord, bool]:
        """Create the one delegated role, or return the identical existing one.

        Returns ``(record, created)``. Idempotent for the same delegator so a retried
        cutover never mints a second identity; a record delegated from another operator
        role is stale and needs governed redelegation, never a silent overwrite.
        """

        _require_storage_mutation_capability(_capability)
        if delegation_provenance not in BOOTSTRAP_PROVENANCES.values():
            raise BackgroundAuthorityPreflightError(
                f"unknown delegation provenance {delegation_provenance!r}",
                provisioning_action="use a declared MVR-06 bootstrap provenance",
            )
        with self._io._locked():
            # Sample the floor under the role lock: a caller-sampled bool could go stale
            # while compensation removes the floor and let a role commit without it.
            if not floor_guard():
                raise BackgroundAuthorityFloorError(
                    "the MVR-06 runtime floor must commit before the first background "
                    "role or delegation write"
                )
            existing = self.load()
            if existing is not None:
                validate_background_delegation(existing, delegator)
                return existing, False
            now = time.time()
            record = BackgroundRuntimeRoleRecord(
                revision=1,
                background_runtime_role_id=_mint_role_id(),
                delegator_role_id=delegator.local_operator_role_id,
                scopes=BACKGROUND_RUNTIME_SCOPES,
                auth_epoch=1,
                status=STATUS_ACTIVE,
                delegation_provenance=delegation_provenance,
                created_at=now,
                updated_at=now,
            )
            self._write(record)
            return record, True

    def discard_uncommitted(self, role_id: str, *, _capability: Any = None) -> None:
        """Compensation only: unlink a role this cutover attempt created and never used."""

        _require_storage_mutation_capability(_capability)
        with self._io._locked():
            current = self.load()
            if current is None:
                return
            if current.background_runtime_role_id != role_id or current.revision != 1:
                raise BackgroundCutoverCompensationError(
                    "the background role changed after this cutover created it",
                    provisioning_action="keep the deployment stopped and inspect role state",
                )
            self.path.unlink()
            directory = os.open(self.path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)  # the unlink must survive power loss
            finally:
                os.close(directory)

    def revoke(self, *, _capability: Any = None) -> BackgroundRuntimeRoleRecord:
        """GOV revocation: advance the auth epoch and make the delegation unusable."""

        _require_storage_mutation_capability(_capability)
        with self._io._locked():
            current = self.require()
            if current.status == STATUS_REVOKED:
                raise BackgroundAuthorityPreflightError(
                    "the background runtime role is already revoked",
                    provisioning_action="redelegate before revoking again",
                )
            record = BackgroundRuntimeRoleRecord(
                revision=current.revision + 1,
                background_runtime_role_id=current.background_runtime_role_id,
                delegator_role_id=current.delegator_role_id,
                scopes=current.scopes,
                auth_epoch=current.auth_epoch + 1,
                status=STATUS_REVOKED,
                delegation_provenance=current.delegation_provenance,
                created_at=current.created_at,
                updated_at=time.time(),
            )
            self._write(record)
            return record

    def redelegate(
        self,
        *,
        delegator: LocalOperatorPrincipalRecord,
        floor_guard: Callable[[], bool],
        _capability: Any = None,
    ) -> BackgroundRuntimeRoleRecord:
        """Governed recovery: a fresh role id under the current delegator, next epoch.

        Allowed only from a revoked or stale delegation; an active, valid delegation is
        never silently replaced.
        """

        _require_storage_mutation_capability(_capability)
        with self._io._locked():
            if not floor_guard():
                raise BackgroundAuthorityFloorError(
                    "the MVR-06 runtime floor must be recorded before redelegation"
                )
            current = self.require()
            if (
                current.status == STATUS_ACTIVE
                and current.delegator_role_id == delegator.local_operator_role_id
            ):
                raise BackgroundAuthorityPreflightError(
                    "an active background delegation cannot be replaced",
                    provisioning_action="revoke the background role before redelegating",
                )
            record = BackgroundRuntimeRoleRecord(
                revision=current.revision + 1,
                background_runtime_role_id=_mint_role_id(),
                delegator_role_id=delegator.local_operator_role_id,
                scopes=BACKGROUND_RUNTIME_SCOPES,
                auth_epoch=current.auth_epoch + 1,
                status=STATUS_ACTIVE,
                delegation_provenance=PROVENANCE_REDELEGATION,
                created_at=current.created_at,
                updated_at=time.time(),
            )
            self._write(record)
            return record


def background_role_path(registry_path: Path) -> Path:
    """The private role record, a sibling of the registry and the MVR-03 principal."""

    return Path(registry_path).parent / BACKGROUND_ROLE_RECORD_FILENAME


def validate_background_delegation(
    role: BackgroundRuntimeRoleRecord,
    delegator: LocalOperatorPrincipalRecord,
) -> None:
    """Fail closed on stale, ambiguous, revoked, partial, or over-broad delegation."""

    if role.status != STATUS_ACTIVE:
        raise BackgroundAuthorityPreflightError(
            f"the background runtime role is revoked at auth epoch {role.auth_epoch}",
            provisioning_action="run `background-role-redelegate` after GOV review",
        )
    if role.delegator_role_id != delegator.local_operator_role_id:
        raise BackgroundAuthorityPreflightError(
            "the background delegation is stale: its delegator is not the current local "
            "operator role",
            provisioning_action="run `background-role-redelegate` after GOV review",
        )
    principal_ids = {delegator.local_operator_role_id} | {
        item.role_id for item in delegator.additional_roles
    }
    if role.background_runtime_role_id in principal_ids:
        raise BackgroundAuthorityPreflightError(
            "the background role id is ambiguous with a foreground principal",
            provisioning_action="revoke and redelegate a distinct background role",
        )
    granted = set(role.scopes)
    if not granted <= LOCAL_OPERATOR_DELEGABLE_SCOPES:
        raise BackgroundAuthorityPreflightError(
            "the background delegation exceeds its delegator",
            provisioning_action="revoke and redelegate the least-privilege background role",
        )
    if granted - set(BACKGROUND_RUNTIME_SCOPES):
        raise BackgroundAuthorityPreflightError(
            "the background delegation is over-broad",
            provisioning_action="revoke and redelegate the least-privilege background role",
        )
    if granted != set(BACKGROUND_RUNTIME_SCOPES):
        raise _partial("the background delegation is partial: least-privilege scopes missing")


def mvr06_floor_recorded(snapshot: RegistrySnapshot) -> bool:
    floors = snapshot.extensions.get("runtimeFloors") or {}
    return (
        isinstance(floors, dict)
        and floors.get(MINIMUM_RUNTIME_SCHEMA_KEY) == MVR06_MINIMUM_RUNTIME_SCHEMA
    )


def staged_background_intent(snapshot: RegistrySnapshot) -> BackgroundBindingIntent | None:
    raw = snapshot.extensions.get(BACKGROUND_INTENT_KEY)
    return None if raw is None else BackgroundBindingIntent.from_payload(raw)


@dataclass(frozen=True)
class BackgroundRuntimeAuthority:
    """What a background consumer's preflight proved. Grants nothing by itself."""

    background_runtime_role_id: str
    auth_epoch: int
    intent_revision: int
    intent_mode: str


def require_background_runtime_authority(
    registry: VaultRegistryStore,
    *,
    principal_store: LocalOperatorPrincipalStore,
    role_store: BackgroundRuntimeRoleStore,
) -> BackgroundRuntimeAuthority | None:
    """Background-consumer startup preflight.

    Returns ``None`` before the MVR-06 floor: the pre-MVR-06 legacy path is unchanged.
    Once the floor is recorded, a complete role and intent lineage is mandatory.
    """

    snapshot = registry.read_existing()
    if not mvr06_floor_recorded(snapshot):
        return None
    try:
        intent = staged_background_intent(snapshot)
    except BackgroundIntentError as error:
        raise _partial("the durable background intent is malformed") from error
    if intent is None:
        raise BackgroundAuthorityPreflightError(
            "the MVR-06 cutover is incomplete: the floor has no background intent",
            provisioning_action=_PROVISIONING_CUTOVER,
        )
    delegator = principal_store.load()
    if delegator is None:
        raise BackgroundAuthorityPreflightError(
            "the background delegation has no local operator delegator",
            provisioning_action="complete the MVR-03 principal cutover first",
        )
    role = role_store.require()
    validate_background_delegation(role, delegator)
    return BackgroundRuntimeAuthority(
        background_runtime_role_id=role.background_runtime_role_id,
        auth_epoch=role.auth_epoch,
        intent_revision=intent.revision,
        intent_mode=intent.mode,
    )


@dataclass(frozen=True)
class BackgroundCutoverReceipt:
    role: BackgroundRuntimeRoleRecord
    snapshot: RegistrySnapshot
    floor_advanced: bool
    role_created: bool
    intent_installed: bool

    def as_dict(self) -> dict[str, Any]:
        intent = staged_background_intent(self.snapshot)
        return {
            **self.role.receipt(),
            "floor_recorded": True,
            "floor_advanced": self.floor_advanced,
            "role_created": self.role_created,
            "intent_installed": self.intent_installed,
            "intent_mode": intent.mode if intent else None,
            "intent_revision": intent.revision if intent else None,
            "registry_revision": self.snapshot.revision,
        }


def run_background_authority_cutover(
    registry: VaultRegistryStore,
    *,
    principal_store: LocalOperatorPrincipalStore,
    role_store: BackgroundRuntimeRoleStore,
    delegation_provenance: str,
    _capability: Any = None,
) -> BackgroundCutoverReceipt:
    """Floor -> role/delegation -> staged intent, with attempt-local compensation.

    Callers hold the proved stopped deployment window. Every precondition that can fail
    is checked before the irreversible floor; a later in-process failure removes only
    what this attempt wrote. A process kill instead leaves a floor-qualified partial
    lineage that every pre-MVR-06 image refuses at its schema gate, every MVR-06
    background consumer refuses at preflight, and a rerun of this cutover completes.
    """

    _require_storage_mutation_capability(_capability)
    if delegation_provenance not in BOOTSTRAP_PROVENANCES.values():
        raise BackgroundAuthorityPreflightError(
            f"unknown delegation provenance {delegation_provenance!r}",
            provisioning_action="use a declared MVR-06 bootstrap provenance",
        )
    delegator = principal_store.load()
    if delegator is None:
        raise BackgroundAuthorityPreflightError(
            "the background role is delegated from the local operator role, which is not "
            "provisioned",
            provisioning_action="complete the MVR-03 principal cutover first",
        )
    before = registry.load()
    floors = before.extensions.get("runtimeFloors") or {}
    minimum = floors.get(MINIMUM_RUNTIME_SCHEMA_KEY) if isinstance(floors, dict) else None
    if minimum not in {MVR05_MINIMUM_RUNTIME_SCHEMA, MVR06_MINIMUM_RUNTIME_SCHEMA}:
        raise BackgroundAuthorityFloorError(
            "the MVR-06 floor requires the recorded MVR-05 channel fence"
        )
    existing_role = role_store.load()
    if existing_role is not None:
        # A retry may reuse its own role, but never one delegated elsewhere.
        validate_background_delegation(existing_role, delegator)
    floor = registry.advance_mvr06_runtime_floor(_capability=_capability)
    floor_advanced = floor.revision != before.revision
    role: BackgroundRuntimeRoleRecord | None = None
    role_created = False
    try:
        role, role_created = role_store.bootstrap(
            delegator=delegator,
            delegation_provenance=delegation_provenance,
            floor_guard=lambda: mvr06_floor_recorded(registry.read_existing()),
            _capability=_capability,
        )
        intent_present = staged_background_intent(floor) is not None
        committed = registry.install_background_intent(
            BackgroundBindingIntent.staged_compatibility(),
            expected_revision=floor.revision,
            _capability=_capability,
        )
    except Exception as error:
        if floor_advanced:
            try:
                if role_created and role is not None:
                    role_store.discard_uncommitted(
                        role.background_runtime_role_id, _capability=_capability
                    )
                registry.compensate_mvr06_runtime_floor(
                    expected_revision=floor.revision, _capability=_capability
                )
            except Exception as compensation_error:
                raise BackgroundCutoverCompensationError(
                    "background cutover failed and its compensation is unproven",
                    provisioning_action=(
                        "keep the deployment stopped, inspect registry and role state, "
                        "then rerun the cutover"
                    ),
                ) from compensation_error
        raise error
    return BackgroundCutoverReceipt(
        role=role,
        snapshot=committed,
        floor_advanced=floor_advanced,
        role_created=role_created,
        intent_installed=not intent_present,
    )


# -- staged admin surface ---------------------------------------------------------------


def _bridge_view(snapshot: RegistrySnapshot) -> dict[str, Any]:
    """The still-authoritative legacy picker bridge, read without any write."""

    if snapshot.settings_rebind is None:
        return {"installed": False, "binding_id": None, "phase": None}
    record = SettingsRebindRecord.from_payload(snapshot.settings_rebind)
    return {
        "installed": True,
        "binding_id": record.candidate_binding_id,
        "phase": record.phase,
    }


class BackgroundIntentAdminService:
    """The one service behind the API router and the headless CLI.

    MVR-06A posture: list/inspect are read-only (they use the registry's no-repair,
    no-initialize read); add/remove raise ``capability_not_ready`` before touching any
    state, so durable intent cannot diverge from the still-authoritative legacy watcher.
    """

    def __init__(self, registry: VaultRegistryStore) -> None:
        self._registry = registry

    def _read(self) -> tuple[RegistrySnapshot, BackgroundBindingIntent | None]:
        snapshot = self._registry.read_existing()
        return snapshot, staged_background_intent(snapshot)

    def list(self) -> dict[str, Any]:
        snapshot, intent = self._read()
        return {
            "initialized": intent is not None,
            "mode": intent.mode if intent else None,
            "compatibility_handoff": intent.compatibility_handoff if intent else None,
            "compatibility_binding_id": (
                intent.compatibility_binding_id if intent else None
            ),
            "background_vault_binding_ids": (
                list(intent.background_vault_binding_ids) if intent else []
            ),
            "explicit_empty": bool(intent and intent.explicit_empty),
            "intent_revision": intent.revision if intent else None,
            "registry_revision": snapshot.revision,
            "legacy_bridge": _bridge_view(snapshot),
            "intent_mutations": BackgroundIntentNotReadyError.error_code,
        }

    def inspect(self, vault_binding_id: str) -> dict[str, Any]:
        snapshot, intent = self._read()
        bridge = _bridge_view(snapshot)
        if intent is None:
            status = "not_initialized"
        elif (
            intent.mode == INTENT_MODE_COMPATIBILITY
            and intent.compatibility_handoff == HANDOFF_PENDING
        ):
            status = (
                "legacy_bridge_binding"
                if bridge["binding_id"] == vault_binding_id
                else "not_enrolled"
            )
        elif intent.mode == INTENT_MODE_COMPATIBILITY:
            status = (
                "compatibility_binding"
                if intent.compatibility_binding_id == vault_binding_id
                else "not_enrolled"
            )
        else:
            status = (
                "explicit_member"
                if vault_binding_id in intent.background_vault_binding_ids
                else "not_enrolled"
            )
        return {
            "vault_binding_id": vault_binding_id,
            "registered": vault_binding_id in snapshot.registrations,
            "background_status": status,
            "intent_revision": intent.revision if intent else None,
            "registry_revision": snapshot.revision,
        }

    def _sealed(self, command: str) -> BackgroundIntentNotReadyError:
        return BackgroundIntentNotReadyError(
            f"capability_not_ready: background intent {command} is sealed until the "
            "MVR-06B supervisor handoff; the legacy watcher remains authoritative"
        )

    def add(self, vault_binding_id: str) -> dict[str, Any]:
        raise self._sealed("add")

    def remove(self, vault_binding_id: str) -> dict[str, Any]:
        raise self._sealed("remove")


__all__ = [
    "BACKGROUND_CONSUMERS",
    "BACKGROUND_ROLE_RECORD_FILENAME",
    "BACKGROUND_RUNTIME_ROLE_SCHEMA",
    "BACKGROUND_RUNTIME_SCOPES",
    "BOOTSTRAP_PROVENANCES",
    "LOCAL_OPERATOR_DELEGABLE_SCOPES",
    "BackgroundAuthorityFloorError",
    "BackgroundAuthorityPreflightError",
    "BackgroundCutoverCompensationError",
    "BackgroundCutoverReceipt",
    "BackgroundIntentAdminService",
    "BackgroundIntentNotReadyError",
    "BackgroundRuntimeAuthority",
    "BackgroundRuntimeRoleRecord",
    "BackgroundRuntimeRoleStore",
    "RegistryError",
    "background_role_path",
    "mvr06_floor_recorded",
    "require_background_runtime_authority",
    "run_background_authority_cutover",
    "staged_background_intent",
    "validate_background_delegation",
]
