"""MVR-06C production binding relocation engine.

Reached only through :meth:`app.instance.runtime.InstanceRegistryRuntime.relocate` (and
``recover_relocation`` / the ``binding-relocate`` and ``binding-lifecycle-recover`` CLI
commands). Sealed with ``capability_not_ready`` until the MVR-05 foreground and MVR-06B
background consumer floors are proven, i.e. until every foreground and background
consumer holds the shared per-binding effect lease in the ownership-fence order
(`docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md`, MVR-06C production protocol
proof, and `ESTABLISH_INSTANCE_VAULT_REGISTRY.md`).

Relocation moves one registration's content root to a new path that holds **the same**
vault: its durable vault marker must name the registration's logical ``vault_id`` and
local-clone ``local_instance_id``. A different initialized vault, a missing or ambiguous
marker, an uninitialized binding, or any other clone fails before any mutation. Relocation
by governed lineage to a different clone identity is not activated and fails the same way.

One recoverable journal (``binding-relocation.json``)::

    intent -> identity_validated -> reserved -> drained -> ownership_relocated
           -> committed -> consumers_reconciled -> complete

``reserved`` commits the durable ``relocating`` reservation: every new foreground and
background shared effect is refused (sealed) on either root. ``drained`` takes the
host-global ownership fence and then the binding's exclusive effect lease, waiting out
every already-authorized shared effect. ``ownership_relocated`` re-proves the target's
marker identity and moves the ledger lease's root locator under the global lock, so a
stale holder that captured the old root can never pass the fence again. ``committed`` is
the one registry generation that writes the new root, advances the binding revision (the
next request resolves a new ActiveContextSet generation, and context/cache identity keys on
that revision), clears the reservation, and records path-free ``bindingLineage``.
``consumers_reconciled`` proves the registry and ledger agree on one root and that a fresh
background resolution adopts it.

A typed refusal before the ownership move compensates: the reservation is withdrawn and the
source root stays authoritative. A process crash leaves the journal;
:meth:`BindingRelocationCoordinator.recover` resumes from its phase and never reopens access
before the commit. Once the ledger names the destination, the relocation only rolls forward.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.instance._storage_boundary import (
    _STORAGE_MUTATION_CAPABILITY,
    CapabilityNotReadyError,
    RegistryError,
)
from app.instance.background_supervisor import (
    LIFECYCLE_RELOCATING,
    LIFECYCLE_STATE_KEY,
    durable_background_state,
    stored_intent,
)
from app.instance.binding_removal import _content_epoch, _Journal
from app.instance.filesystem_identity import (
    FilesystemIdentityError,
    resolve_filesystem_root_identity,
    same_filesystem_root,
)
from app.instance.vault_registry import (
    RegistryDefaultConflict,
    RegistrySnapshot,
    VaultRegistration,
)

if TYPE_CHECKING:
    from app.instance.runtime import InstanceRegistryRuntime

logger = logging.getLogger(__name__)

RELOCATION_SCHEMA = "agentic-pkm.binding-relocation.v1"
RELOCATION_PHASES = (
    "intent",
    "identity_validated",
    "reserved",
    "drained",
    "ownership_relocated",
    "committed",
    "consumers_reconciled",
    "complete",
)
RELOCATION_ID_KEY = "relocationId"
_FLOOR_REFUSAL = "MVR-06C consumer effect-lease floor is required"
_RELOCATION_DRAIN_TIMEOUT_SECONDS = 30.0


class BindingRelocationRefused(RegistryError):
    """A relocation request is refused before it mutates any root, registry, or lease."""


class RelocationIdentityError(BindingRelocationRefused):
    """The target does not durably prove the binding's logical vault and local clone."""


def _fault_point(phase: str) -> None:
    """Process-failure injection seam for the non-journal durable boundaries."""

    from app.instance import binding_removal

    binding_removal._fault_point(phase)


def _require_consumer_floors(snapshot: RegistrySnapshot) -> None:
    """The MVR-05 foreground and MVR-06B background shared-effect floors."""

    if durable_background_state(snapshot) is None:
        raise CapabilityNotReadyError(_FLOOR_REFUSAL)


def _canonical(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def prove_relocation_identity(registration: VaultRegistration, destination: Path) -> None:
    """The target's durable vault marker names this binding's vault and local clone."""

    from app.instance.runtime import _read_vault_identity

    if registration.vault_id is None:
        raise RelocationIdentityError(
            "relocation requires an initialized binding with a durable logical vault identity"
        )
    if not (destination / "settings" / "vault.md").is_file() or not (
        destination / "settings" / "local.md"
    ).is_file():
        raise RelocationIdentityError("relocation target has no durable vault marker identity")
    try:
        vault_id, local_instance_id = _read_vault_identity(destination)
    except Exception as exc:  # malformed marker frontmatter is ambiguous, never a match
        raise RelocationIdentityError("relocation target vault marker identity is ambiguous") from exc
    if vault_id is None or local_instance_id is None:
        raise RelocationIdentityError("relocation target vault marker identity is incomplete")
    if vault_id != registration.vault_id:
        raise RelocationIdentityError("relocation target is a different initialized vault")
    if local_instance_id != registration.local_instance_id:
        raise RelocationIdentityError(
            "relocation target is a different local clone; governed lineage relocation is "
            "not activated"
        )


class BindingRelocationCoordinator:
    """The production relocation engine (crash-recoverable, compensating on refusal)."""

    def __init__(self, runtime: InstanceRegistryRuntime) -> None:
        self.runtime = runtime
        self.journal = _Journal(
            runtime.layout.root / "binding-relocation.json", RELOCATION_SCHEMA, RELOCATION_PHASES
        )

    # -- entrypoints --------------------------------------------------------------------

    def relocate(self, binding_id: str, destination: Path) -> VaultRegistration:
        snapshot = self.runtime.registry.load()
        _require_consumer_floors(snapshot)
        target = _canonical(destination)
        with self.journal.locked():
            existing = self.journal.load()
            if existing is not None and existing["phase"] != "complete":
                if (existing["binding_id"], existing["destination"]) != (binding_id, str(target)):
                    raise RegistryError("another binding relocation requires recovery first")
                return self._resume(existing)
            intent = self._plan(snapshot, binding_id, target)
            self.journal.save(intent, "intent")
            return self._resume(intent)

    def recover(self) -> VaultRegistration | None:
        with self.journal.locked():
            intent = self.journal.load()
            if intent is None or intent["phase"] == "complete":
                return None
            return self._resume(intent)

    # -- planning -----------------------------------------------------------------------

    def _plan(
        self, snapshot: RegistrySnapshot, binding_id: str, destination: Path
    ) -> dict[str, Any]:
        registration = snapshot.registrations.get(binding_id)
        if registration is None:
            raise RegistryError(f"unknown vault_binding_id: {binding_id}")
        if registration.extensions.get(LIFECYCLE_STATE_KEY) is not None:
            raise BindingRelocationRefused("binding already has a lifecycle reservation")
        floor = snapshot.extensions.get("scalarRollback")
        if isinstance(floor, dict) and floor.get("targetVaultBindingId") == binding_id:
            # The MVR-01C rollback floor records the target root; retargeting it belongs
            # to its owner, never to a relocation.
            raise RegistryDefaultConflict(
                "relocating the MVR-01C scalar rollback target requires an explicit "
                "authorized floor retarget"
            )
        self._validate_destination(snapshot, registration, destination)
        intent = stored_intent(snapshot)
        return {
            "schema": RELOCATION_SCHEMA,
            "relocation_id": f"relocation-{uuid4()}",
            "binding_id": binding_id,
            "channel_id": self.runtime.layout.channel_id,
            "source": asdict(registration),
            "destination": str(destination),
            "background_bound": bool(
                intent is not None and binding_id in intent.effective_binding_ids()
            ),
        }

    def _validate_destination(
        self,
        snapshot: RegistrySnapshot,
        registration: VaultRegistration,
        destination: Path,
    ) -> None:
        from app.instance.instance_state import (
            InstanceStatePreflightError,
            validate_registry_disjoint_from_content,
        )

        try:
            identity = resolve_filesystem_root_identity(destination)
        except FilesystemIdentityError as exc:
            raise BindingRelocationRefused("relocation target is not a usable directory") from exc
        if not identity.materialized:
            raise BindingRelocationRefused("relocation target does not exist")
        source = _canonical(registration.path)
        if source == destination:
            raise BindingRelocationRefused("relocation target is the binding's current root")
        for other_id, other in snapshot.registrations.items():
            if other_id == registration.vault_binding_id:
                continue
            other_root = _canonical(other.path)
            if same_filesystem_root(resolve_filesystem_root_identity(other_root), identity) or (
                destination.is_relative_to(other_root) or other_root.is_relative_to(destination)
            ):
                raise BindingRelocationRefused(
                    "relocation target overlaps another registered content root"
                )
        try:
            validate_registry_disjoint_from_content(
                self.runtime.layout.registry_path,
                [Path(item.path) for item in snapshot.registrations.values()] + [destination],
            )
        except InstanceStatePreflightError as exc:
            raise BindingRelocationRefused(str(exc)) from exc
        prove_relocation_identity(registration, destination)

    # -- resume -------------------------------------------------------------------------

    def _resume(self, intent: dict[str, Any]) -> VaultRegistration:
        from app.instance.binding_effect_lease import BindingEffectLeaseError
        from app.instance.ownership_ledger import LedgerError

        try:
            return self._run(intent)
        except (RegistryError, BindingEffectLeaseError, LedgerError):
            # A typed refusal before the ownership move leaves the source authoritative,
            # but only when the ledger *positively* still names the source: a move that
            # landed before a crash (journal still ``drained``) only rolls forward, and
            # an unreadable ledger keeps the journal. Any other exception is a process
            # failure: the journal is the authority.
            if self.journal.before(intent, "ownership_relocated") and (
                self._ledger_locator(intent) == _canonical(intent["source"]["path"])
            ):
                self._compensate(intent)
            raise

    def _run(self, intent: dict[str, Any]) -> VaultRegistration:
        runtime = self.runtime
        binding_id: str = intent["binding_id"]
        destination = Path(intent["destination"])
        before = self.journal.before
        if before(intent, "identity_validated"):
            snapshot = runtime.registry.load()
            current = snapshot.registrations.get(binding_id)
            if current is None or current.extensions.get(LIFECYCLE_STATE_KEY) is not None:
                raise BindingRelocationRefused("the relocating registration changed before validation")
            self._require_unchanged_source(intent, current)
            self._validate_destination(snapshot, current, destination)
            self.journal.save(intent, "identity_validated")
        if before(intent, "reserved"):
            self._reserve(intent)
            self.journal.save(intent, "reserved")
        if before(intent, "drained"):
            intent["drained_via"] = self._drain(intent)
            self.journal.save(intent, "drained")
        if before(intent, "ownership_relocated"):
            source = VaultRegistration(**intent["source"])
            locator = self._ledger_locator(intent)
            if locator == _canonical(source.path):
                # The target is proven again after the drain, immediately before the one
                # mutation that moves authority: it may have changed while holders drained.
                prove_relocation_identity(source, destination)
                runtime.ledger.relocate_active(
                    binding_id,
                    channel_id=runtime.layout.channel_id,
                    source_root=Path(source.path),
                    destination_root=destination,
                    _capability=_STORAGE_MUTATION_CAPABILITY,
                )
                _fault_point("binding-relocation:ledger_moved")
            elif locator != destination:
                # Neither root: never guess; the journal stays for recovery.
                raise RegistryError("the binding's ownership locator names neither relocation root")
            self.journal.save(intent, "ownership_relocated")
        if before(intent, "committed"):
            self._commit(intent)
            self.journal.save(intent, "committed")
        if before(intent, "consumers_reconciled"):
            intent["reconciliation"] = self._reconcile_consumers(intent)
            self.journal.save(intent, "consumers_reconciled")
        if before(intent, "complete"):
            self.journal.save(intent, "complete")
        registration = runtime.registry.load().registrations.get(binding_id)
        if registration is None:
            raise RegistryError("binding relocation completed without its registration")
        return registration

    # -- phases -------------------------------------------------------------------------

    @staticmethod
    def _require_unchanged_source(intent: dict[str, Any], current: VaultRegistration) -> None:
        source = VaultRegistration(**intent["source"])
        if (current.path, current.vault_id, current.local_instance_id) != (
            source.path,
            source.vault_id,
            source.local_instance_id,
        ):
            raise BindingRelocationRefused("the relocating registration changed before its reservation")

    def _reserve(self, intent: dict[str, Any]) -> None:
        relocation_id = intent["relocation_id"]

        def reserve(_snapshot: RegistrySnapshot, current: VaultRegistration) -> VaultRegistration | None:
            if current.extensions.get(RELOCATION_ID_KEY) == relocation_id:
                return None  # reserved before a crash
            if current.extensions.get(LIFECYCLE_STATE_KEY) is not None:
                raise BindingRelocationRefused("binding already has a lifecycle reservation")
            self._require_unchanged_source(intent, current)
            return replace(
                current,
                extensions={
                    **current.extensions,
                    LIFECYCLE_STATE_KEY: LIFECYCLE_RELOCATING,
                    RELOCATION_ID_KEY: relocation_id,
                },
            )

        self.runtime.registry.commit_binding_relocation_state(
            intent["binding_id"], reserve, _capability=_STORAGE_MUTATION_CAPABILITY
        )

    def _leases(self) -> Any:
        from app.instance.binding_effect_lease import BindingEffectLeaseManager

        return BindingEffectLeaseManager.for_runtime(
            registry_store=self.runtime.registry,
            ownership_root=self.runtime.ledger.root,
            state_root=self.runtime.layout.root / "binding-effect-leases",
        )

    def _drain(self, intent: dict[str, Any]) -> str:
        """Ownership fence -> exclusive binding lease: every prior shared effect finishes.

        The lease admits whichever root its physical fingerprint names: the source while
        the directory is still there, the destination once it was moved (renamed) there.
        """

        from app.instance.binding_effect_lease import OwnershipFenceUnavailable

        leases = self._leases()
        source = Path(intent["source"]["path"])
        destination = Path(intent["destination"])
        refusal: Exception | None = None
        for label, root in (("source", source), ("destination", destination)):
            try:
                with leases.exclusive_change(
                    intent["binding_id"],
                    channel_id=self.runtime.layout.channel_id,
                    root=root,
                    timeout=_RELOCATION_DRAIN_TIMEOUT_SECONDS,
                ):
                    return label
            except OwnershipFenceUnavailable as exc:
                refusal = exc
        raise BindingRelocationRefused(
            "the binding's ownership lease names neither the source nor the target root"
        ) from refusal

    def _ledger_locator(self, intent: dict[str, Any]) -> Path | None:
        """The active lease's recorded locator; ``None`` when unreadable or absent."""

        try:
            return self.runtime.ledger.active_lease_locator(
                intent["binding_id"], channel_id=self.runtime.layout.channel_id
            )
        except Exception:
            return None

    def _owned_by_destination(self, intent: dict[str, Any]) -> bool:
        try:
            return self.runtime.ledger.lease_locator_names(
                intent["binding_id"],
                channel_id=self.runtime.layout.channel_id,
                root=Path(intent["destination"]),
            )
        except Exception:
            return False

    def _commit(self, intent: dict[str, Any]) -> None:
        relocation_id = intent["relocation_id"]
        destination = intent["destination"]
        source = VaultRegistration(**intent["source"])

        def committed(snapshot: RegistrySnapshot) -> bool:
            from app.instance.binding_removal import _lineage

            return any(
                item.get("relocationId") == relocation_id and item.get("event") == "relocated"
                for item in _lineage(snapshot)
            )

        def commit(snapshot: RegistrySnapshot, current: VaultRegistration) -> VaultRegistration | None:
            if committed(snapshot):
                return None  # committed before a crash; roll forward
            if current.extensions.get(RELOCATION_ID_KEY) != relocation_id:
                raise RegistryError("the relocation reservation belongs to another lifecycle")
            extensions = {
                key: value
                for key, value in current.extensions.items()
                if key not in {LIFECYCLE_STATE_KEY, RELOCATION_ID_KEY}
            }
            extensions["bindingRevision"] = snapshot.revision + 1
            ref = current.ref
            if ref == f"path:{source.path}":
                ref = f"path:{destination}"
            return replace(current, path=destination, ref=ref, extensions=extensions)

        def lineage(snapshot: RegistrySnapshot) -> dict[str, Any]:
            current = snapshot.registrations[intent["binding_id"]]
            return {
                "bindingId": intent["binding_id"],
                "event": "relocated",
                "relocationId": relocation_id,
                "contentEpoch": _content_epoch(current),
                "registryRevision": snapshot.revision + 1,
                "bindingRevision": snapshot.revision + 1,
            }

        self.runtime.registry.commit_binding_relocation_state(
            intent["binding_id"],
            commit,
            lineage_entry=lineage,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )

    def _reconcile_consumers(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Prove one authorized root/revision for registry, ledger, and consumers."""

        from app.instance.background_supervisor import BackgroundLifecycleSupervisor
        from app.instance.scalar_binding_runtime import _binding_revision

        runtime = self.runtime
        binding_id = intent["binding_id"]
        destination = Path(intent["destination"])
        snapshot = runtime.registry.load()
        registration = snapshot.registrations.get(binding_id)
        if (
            registration is None
            or _canonical(registration.path) != destination
            or registration.extensions.get(LIFECYCLE_STATE_KEY) is not None
        ):
            raise RegistryError("the relocated registration did not converge on its target")
        if not self._owned_by_destination(intent):
            raise RegistryError("the relocated ownership lease did not converge on its target")
        receipt: dict[str, Any] = {
            "registry": "converged",
            "ownership": "converged",
            "binding_revision": _binding_revision(snapshot, binding_id),
            # Foreground request contexts and every context/cache identity key on the
            # binding revision this commit advanced.
            "context_caches": "rotated_by_binding_revision",
            "background": "not_background_bound",
        }
        if intent.get("background_bound"):
            supervisor = BackgroundLifecycleSupervisor.for_runtime(
                registry_path=runtime.layout.registry_path,
                ownership_root=runtime.ledger.root,
                channel_id=runtime.layout.channel_id,
                consumer="relocation-reconciler",
            )
            try:
                lifecycle = supervisor.start()
            except Exception as exc:  # truthful, bounded: recorded, never masked as running
                receipt["background"] = f"failed: {type(exc).__name__}"
            else:
                adopted = (
                    lifecycle.binding_id == binding_id
                    and lifecycle.root is not None
                    and _canonical(lifecycle.root) == destination
                )
                receipt["background"] = (
                    lifecycle.status if adopted or lifecycle.status != "running" else "not_adopted"
                )
                receipt["background_generation"] = lifecycle.generation
        return receipt

    def _compensate(self, intent: dict[str, Any]) -> None:
        """Withdraw a pre-ownership relocation: the source stays authoritative."""

        relocation_id = intent["relocation_id"]

        def withdraw(_snapshot: RegistrySnapshot, current: VaultRegistration) -> VaultRegistration | None:
            if current.extensions.get(RELOCATION_ID_KEY) != relocation_id:
                return None
            return replace(
                current,
                extensions={
                    key: value
                    for key, value in current.extensions.items()
                    if key not in {LIFECYCLE_STATE_KEY, RELOCATION_ID_KEY}
                },
            )

        if intent["binding_id"] in self.runtime.registry.load().registrations:
            self.runtime.registry.commit_binding_relocation_state(
                intent["binding_id"], withdraw, _capability=_STORAGE_MUTATION_CAPABILITY
            )
        self.journal.discard()


__all__ = [
    "RELOCATION_PHASES",
    "RELOCATION_SCHEMA",
    "BindingRelocationCoordinator",
    "BindingRelocationRefused",
    "RelocationIdentityError",
    "prove_relocation_identity",
]
