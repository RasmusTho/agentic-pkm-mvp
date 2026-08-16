"""MVR-02: the explicit instance default vault and one fail-closed resolver.

``last_active_vault_ref`` is interaction history and ``VAULT_ROOT`` is a
deployment bootstrap. Neither is a truthful instance default, and conflating them
makes restarts nondeterministic and turns an invalid explicit selection into a
silent read/write against the wrong vault.

This module owns three things:

* :func:`resolve_vault_selection` — one production resolver applying
  ``request override > retained session > instance default > explicit legacy
  bootstrap > no-vault``, reporting which branch won. An explicit selection that
  does not resolve fails closed; it never falls through to last-active, another
  registration, the working directory, or ``./vault``.
* :func:`resolve_compatibility_default_vault_id` — the untrusted ``DEFAULT_VAULT_ID``
  logical-ID lookup, which resolves only when the logical vault ID maps to exactly
  one local binding.
* :class:`InstanceDefaultVaultService` — the single service behind the
  authenticated API and the headless CLI get/set/clear commands, so both
  producers converge on the same locked registry state, the same redacted
  receipt, and the same versioned mutation event.

MVR-05 owns the HTTP carriers (``X-Active-Context-Override`` and
``X-Active-Context-Session``); this slice only accepts their already-parsed
values as distinct resolver inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.events.types import INSTANCE_DEFAULT_VAULT_CHANGED
from app.instance.filesystem_identity import (
    FilesystemIdentityError,
    resolve_filesystem_root_identity,
    same_filesystem_root,
)
from app.instance.vault_registry import (
    DEFAULT_PROVENANCE_EXPLICIT,
    RegistryError,
    RegistrySnapshot,
    VaultRegistration,
    VaultRegistryStore,
)

SELECTION_REQUEST_OVERRIDE = "request_override"
SELECTION_SESSION = "session_selection"
SELECTION_INSTANCE_DEFAULT = "instance_default"
# A compatibility DEFAULT_VAULT_ID win is reported distinctly from a durable
# operator-set default: provenance is meant to be inspectable, and "an env var
# resolved this" is materially different from "the instance is configured this
# way" when someone is debugging which vault a background caller reached.
SELECTION_COMPATIBILITY_DEFAULT = "compatibility_default_vault_id"
SELECTION_LEGACY_BOOTSTRAP = "legacy_bootstrap"
SELECTION_NO_VAULT = "no_vault"

DEFAULT_VAULT_MUTATION_EVENT_VERSION = 1
_DEFAULT_MUTATION_FINGERPRINT = "instance-default-vault-changed-v1"


class VaultSelectionError(RegistryError):
    """An explicit selection is unknown, removed, or unauthorized.

    Raised instead of degrading to another binding: fail-closed is the whole
    point of the precedence chain.
    """


@dataclass(frozen=True)
class VaultSelection:
    """One resolved selection plus the branch that produced it."""

    vault_binding_id: str | None
    provenance: str
    registration: VaultRegistration | None = None

    @property
    def is_no_vault(self) -> bool:
        return self.vault_binding_id is None


def _require_registered(
    snapshot: RegistrySnapshot, vault_binding_id: str, *, branch: str
) -> VaultRegistration:
    registration = snapshot.registrations.get(vault_binding_id)
    if registration is None:
        raise VaultSelectionError(
            f"{branch} selection is not a current registration: {vault_binding_id}"
        )
    return registration


def resolve_compatibility_default_vault_id(snapshot: RegistrySnapshot, vault_id: str) -> str:
    """Resolve the untrusted ``DEFAULT_VAULT_ID`` logical ID to one binding.

    A logical vault ID may legitimately map to several local clones. That is
    ambiguous, not a tiebreak opportunity, so anything other than exactly one
    match fails closed.
    """

    normalized = (vault_id or "").strip()
    if not normalized:
        raise VaultSelectionError("compatibility DEFAULT_VAULT_ID is blank")
    matches = [
        registration.vault_binding_id
        for registration in snapshot.registrations.values()
        if registration.vault_id == normalized
    ]
    if len(matches) != 1:
        raise VaultSelectionError(
            "compatibility DEFAULT_VAULT_ID does not identify exactly one local binding"
        )
    return matches[0]


def resolve_legacy_bootstrap_binding(snapshot: RegistrySnapshot, vault_root: Path) -> str:
    """Resolve the explicit legacy bootstrap adapter to one stable binding.

    The adapter only ever *finds* the binding MVR-01B created or reconciled for
    this root. It never turns an env path into a new registration and never uses
    a path as identity: the path is matched through canonical filesystem-root
    identity, and anything other than exactly one match fails closed.
    """

    try:
        identity = resolve_filesystem_root_identity(vault_root)
    except FilesystemIdentityError as exc:
        raise VaultSelectionError(
            "legacy bootstrap root cannot be resolved to a filesystem identity"
        ) from exc
    matches = []
    for registration in snapshot.registrations.values():
        try:
            candidate = resolve_filesystem_root_identity(Path(registration.path))
        except FilesystemIdentityError:
            continue
        if same_filesystem_root(candidate, identity):
            matches.append(registration.vault_binding_id)
    if len(matches) != 1:
        raise VaultSelectionError(
            "legacy bootstrap env and registry truth do not identify exactly one binding"
        )
    return matches[0]


def resolve_vault_selection(
    snapshot: RegistrySnapshot,
    *,
    request_override: str | None = None,
    session_selection: str | None = None,
    legacy_bootstrap_vault_root: Path | None = None,
    compatibility_default_vault_id: str | None = None,
) -> VaultSelection:
    """Apply the MVR-02 precedence chain and report the winning branch.

    ``request_override`` is the one-request selection, ``session_selection`` the
    retained one. They are distinct inputs, and the override never persists into
    the session. Absence of every explicit input resolves to no-vault, which
    remains a valid result.
    """

    override = (request_override or "").strip() or None
    session = (session_selection or "").strip() or None
    if override is not None:
        registration = _require_registered(snapshot, override, branch="request override")
        return VaultSelection(override, SELECTION_REQUEST_OVERRIDE, registration)
    if session is not None:
        registration = _require_registered(snapshot, session, branch="session")
        return VaultSelection(session, SELECTION_SESSION, registration)
    default_binding_id = snapshot.default_vault_binding_id
    default_provenance = SELECTION_INSTANCE_DEFAULT
    if default_binding_id is None and compatibility_default_vault_id:
        default_binding_id = resolve_compatibility_default_vault_id(
            snapshot, compatibility_default_vault_id
        )
        default_provenance = SELECTION_COMPATIBILITY_DEFAULT
    if default_binding_id is not None:
        registration = _require_registered(snapshot, default_binding_id, branch="instance default")
        return VaultSelection(default_binding_id, default_provenance, registration)
    if legacy_bootstrap_vault_root is not None:
        binding_id = resolve_legacy_bootstrap_binding(snapshot, legacy_bootstrap_vault_root)
        registration = _require_registered(snapshot, binding_id, branch="legacy bootstrap")
        return VaultSelection(binding_id, SELECTION_LEGACY_BOOTSTRAP, registration)
    return VaultSelection(None, SELECTION_NO_VAULT, None)


@dataclass(frozen=True)
class DefaultVaultReceipt:
    """The redacted receipt both production producers return.

    Deliberately carries no content-root path, vault name, or other raw binding
    payload: a receipt travels into logs and GitHub comments, and the binding ID
    plus registry revision are enough to audit the mutation.
    """

    vault_binding_id: str | None
    provenance: str | None
    registry_revision: int
    previous_vault_binding_id: str | None = None
    changed: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "vault_binding_id": self.vault_binding_id,
            "provenance": self.provenance,
            "registry_revision": self.registry_revision,
            "previous_vault_binding_id": self.previous_vault_binding_id,
            "changed": self.changed,
        }


def _emit_default_mutation_event(receipt: DefaultVaultReceipt) -> str:
    """Publish exactly one versioned default-mutation event.

    MVR-06 consumes this contract for compatibility rebind, so the payload
    carries the new registry revision and binding identity only — never a raw
    binding payload — and is keyed on the revision so a crash-retry of the same
    logical mutation cannot produce a second row.
    """

    from app.events.models import new_event
    from app.instance.binding_ids import OUTBOX_GLOBAL_BINDING_ID
    from app.services.outbox import derive_idempotency_key, write_outbox_event

    payload = {
        "event_version": DEFAULT_VAULT_MUTATION_EVENT_VERSION,
        "registry_revision": receipt.registry_revision,
        "vault_binding_id": receipt.vault_binding_id,
        "previous_vault_binding_id": receipt.previous_vault_binding_id,
        "provenance": receipt.provenance,
    }
    idempotency_key = derive_idempotency_key(
        INSTANCE_DEFAULT_VAULT_CHANGED,
        str(receipt.registry_revision),
        _DEFAULT_MUTATION_FINGERPRINT,
    )
    event = new_event(
        event_type=INSTANCE_DEFAULT_VAULT_CHANGED,
        payload=payload,
        source="instance.default_vault",
    )
    # Durability classification (#4214 D5): `required_db=False` is deliberate.
    # The durable registry revision written just above is the authority — the
    # lane's own cross-task invariant is that background supervisors reconcile
    # durable registry revisions, never event delivery, and wake-up hints are
    # never the transition authority. So a skipped mirror on a runtime with no
    # configured Postgres is survivable: the committed revision still carries the
    # change, and requiring the DB here would make the headless CLI unusable on a
    # bare instance that has no outbox at all.
    return write_outbox_event(
        event,
        idempotency_key=idempotency_key,
        vault_binding_id=OUTBOX_GLOBAL_BINDING_ID,
        required_db=False,
    )


class InstanceDefaultVaultService:
    """One service behind the authenticated API and the headless CLI.

    Both producers validate registration, mutate through MVR-01's locked
    registry transaction, never touch ``last_active_vault_ref``, and return the
    same redacted receipt.

    This service **receives** its storage-mutation capability rather than holding
    it: the private capability stays sealed to its existing sanctioned importers
    (`app/instance/_storage_boundary.py`), and only
    :func:`app.instance.runtime.open_default_vault_service` — an already-allowed
    importer — hands it over. Constructing the service without one yields a
    read-only view whose mutators fail closed with ``CapabilityNotReadyError``.
    """

    def __init__(
        self,
        store: VaultRegistryStore,
        *,
        capability: Any = None,
        emit_event: Any = _emit_default_mutation_event,
    ) -> None:
        self._store = store
        self._capability = capability
        self._emit_event = emit_event

    @property
    def store(self) -> VaultRegistryStore:
        return self._store

    def get(self) -> DefaultVaultReceipt:
        snapshot = self._store.load()
        return DefaultVaultReceipt(
            vault_binding_id=snapshot.default_vault_binding_id,
            provenance=snapshot.default_vault_provenance,
            registry_revision=snapshot.revision,
            previous_vault_binding_id=snapshot.default_vault_binding_id,
            changed=False,
        )

    def set(self, vault_binding_id: str) -> DefaultVaultReceipt:
        target = (vault_binding_id or "").strip()
        if not target:
            raise VaultSelectionError("vault_binding_id is required")
        return self._mutate(target, provenance=DEFAULT_PROVENANCE_EXPLICIT)

    def clear(self) -> DefaultVaultReceipt:
        return self._mutate(None, provenance=DEFAULT_PROVENANCE_EXPLICIT)

    def remove_registration(
        self,
        vault_binding_id: str,
        *,
        clear_default: bool = False,
        replacement_default_binding_id: str | None = None,
    ) -> DefaultVaultReceipt:
        """Remove one registration through the reference-safe locked transaction."""

        before = self._store.load()
        updated = self._store.remove_registration(
            vault_binding_id,
            expected_revision=before.revision,
            clear_default=clear_default,
            replacement_default_binding_id=replacement_default_binding_id,
            _capability=self._capability,
        )
        receipt = DefaultVaultReceipt(
            vault_binding_id=updated.default_vault_binding_id,
            provenance=updated.default_vault_provenance,
            registry_revision=updated.revision,
            previous_vault_binding_id=before.default_vault_binding_id,
            changed=(before.default_vault_binding_id != updated.default_vault_binding_id),
        )
        if receipt.changed:
            self._emit_event(receipt)
        return receipt

    def _mutate(self, vault_binding_id: str | None, *, provenance: str) -> DefaultVaultReceipt:
        before = self._store.load()
        if vault_binding_id is not None and vault_binding_id not in before.registrations:
            # Fail closed before any write: an unknown or removed binding is never
            # silently substituted by another registration.
            raise VaultSelectionError(
                f"unknown or unauthorized vault_binding_id: {vault_binding_id}"
            )
        if (
            before.default_vault_binding_id == vault_binding_id
            and before.default_vault_provenance
            == (None if vault_binding_id is None else provenance)
        ):
            # A no-op is not a mutation: it must not burn a registry revision and
            # must not publish a rebind event MVR-06 would act on. Provenance is
            # part of "no-op" — an operator pinning a binding the first-vault
            # producer chose is a real change from an inferred default to an
            # explicit one, and must be recorded, not swallowed.
            return DefaultVaultReceipt(
                vault_binding_id=before.default_vault_binding_id,
                provenance=before.default_vault_provenance,
                registry_revision=before.revision,
                previous_vault_binding_id=before.default_vault_binding_id,
                changed=False,
            )
        updated = self._store.set_instance_default(
            vault_binding_id,
            provenance=provenance,
            expected_revision=before.revision,
            _capability=self._capability,
        )
        if updated.last_active_vault_ref != before.last_active_vault_ref:
            raise RegistryError("default mutation must not change last-active history")
        receipt = DefaultVaultReceipt(
            vault_binding_id=updated.default_vault_binding_id,
            provenance=updated.default_vault_provenance,
            registry_revision=updated.revision,
            previous_vault_binding_id=before.default_vault_binding_id,
            changed=True,
        )
        self._emit_event(receipt)
        return receipt


def redact_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the fields safe to publish outside the instance."""

    allowed = {
        "vault_binding_id",
        "previous_vault_binding_id",
        "provenance",
        "registry_revision",
        "changed",
    }
    return {key: value for key, value in receipt.items() if key in allowed}


__all__ = [
    "DEFAULT_VAULT_MUTATION_EVENT_VERSION",
    "SELECTION_INSTANCE_DEFAULT",
    "SELECTION_LEGACY_BOOTSTRAP",
    "SELECTION_NO_VAULT",
    "SELECTION_REQUEST_OVERRIDE",
    "SELECTION_SESSION",
    "DefaultVaultReceipt",
    "InstanceDefaultVaultService",
    "VaultSelection",
    "VaultSelectionError",
    "redact_receipt",
    "resolve_compatibility_default_vault_id",
    "resolve_legacy_bootstrap_binding",
    "resolve_vault_selection",
]
