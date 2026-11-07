"""MVR-06B: compatibility bridge handoff and the singleton/explicit-empty supervisor.

`docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md` (MVR-06B) owns four things here:

- **The bridge handoff.** :func:`run_compatibility_bridge_handoff` reads the live binding
  of the MVR-05/#3163 legacy picker bridge (``settings_rebind.v1``), drains the MVR-05
  scalar worker on it through the exclusive binding-effect lease, and in **one** registry
  generation materializes it as durable ``compatibility_binding_id`` and records the
  supervisor receipt (:class:`BackgroundSupervisorRecord`). Before that generation the
  bridge owns the watcher; after it the supervisor does. A refusal or crash before the
  write leaves the bridge authoritative and every intent mutation sealed.
- **Durable versioned binding state.** :func:`durable_background_state` is the only
  answer to "which binding does background work run on": the compatibility singleton or
  the explicit set (empty is durable idle). Request/session selection, registry
  membership, the instance default, and the env root never participate after handoff.
- **The supervisor.** :class:`BackgroundLifecycleSupervisor` derives one immutable full
  background :class:`ActiveContextSetV1` per running binding (typed ``no_workspace``,
  server-derived background principal, a domain-separated non-reversible capability
  digest that grants nothing), refuses a binding whose channel/root ownership lease is
  missing, pending, foreign, or changed, reconciles every unseen registry revision and
  auth epoch into a drained new generation, and runs every effect inside the host-global
  ownership fence then the shared per-binding effect lease, revalidating before I/O.
- **Governed singleton/empty intent producers** (:func:`apply_governed_intent_mutation`)
  and the MVR-06 transfer repair hook (:func:`repair_background_intent_for_transfer`).

The ``settings_rebind.v1`` record is retained as the shared two-phase phase journal
(mutation gate -> old-root pre-commit scan/buffer/quiescent ack -> commit -> old-root
post-commit scan/buffer drain -> resume); after the handoff its candidate is a projection
of durable intent, never the authority.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from app.instance._storage_boundary import (
    CapabilityNotReadyError,
    RegistryError,
    _require_storage_mutation_capability,
)
from app.instance.background_intent import (
    BACKGROUND_INTENT_KEY,
    BACKGROUND_SUPERVISOR_KEY,
    INTENT_MODE_COMPATIBILITY,
    INTENT_MODE_EXPLICIT,
    MVR06B_MAX_BACKGROUND_BINDINGS,
    PROVENANCE_BACKGROUND_INTENT,
    PROVENANCE_COMPATIBILITY_DEFAULT,
    PROVENANCE_COMPATIBILITY_HANDOFF,
    BackgroundBindingIntent,
    BackgroundSupervisorRecord,
)
from app.instance.vault_registry import RegistrySnapshot, VaultRegistryStore

if TYPE_CHECKING:
    from app.instance.background_authority import BackgroundRuntimeRoleStore
    from app.instance.binding_effect_lease import BindingEffectLeaseManager
    from app.instance.local_operator_principal import LocalOperatorPrincipalStore
    from app.vault.active_context_v1 import ActiveContextSetV1

logger = logging.getLogger(__name__)

#: Registration lifecycle reservations owned by the MVR-06B removal/reactivation engine.
LIFECYCLE_STATE_KEY: Final = "lifecycleState"
LIFECYCLE_DRAINING_REMOVAL: Final = "draining_removal"
LIFECYCLE_REACTIVATING: Final = "reactivating"
SEALED_LIFECYCLE_STATES = frozenset({LIFECYCLE_DRAINING_REMOVAL, LIFECYCLE_REACTIVATING})

BACKGROUND_CAPABILITY_DOMAIN = b"agentic-pkm.background-capability.v1"
BACKGROUND_CONTEXT_SCOPE = "background"
#: Provenance of a registration enrolled from a pre-registry single-vault install.
LEGACY_ENROLLMENT_PROVENANCES = frozenset(
    {"legacy_env_bootstrap", "authenticated_legacy_owner_inventory"}
)
#: The handoff holds the ingress fence exclusively while it drains; a holder that never
#: exits must fail the cutover (bridge stays authoritative), not wedge it.
HANDOFF_DRAIN_TIMEOUT_SECONDS = 60.0

LifecycleStatus = Literal["running", "idle", "failed"]


class BackgroundLifecycleError(RegistryError):
    """A background lifecycle cannot start, rebind, or effect (fail closed, loudly)."""


class BackgroundLifecycleStale(BackgroundLifecycleError):
    """The held generation no longer matches durable truth; reconcile before effecting."""


class BackgroundBindingIdle(CapabilityNotReadyError):
    """Durable intent runs no binding (explicit-empty or compatibility no-vault)."""


def _hint(message: str) -> None:
    logger.info("background supervisor: %s", message)


# -- durable versioned binding state -----------------------------------------------------


@dataclass(frozen=True)
class BackgroundBindingState:
    """The explicit versioned binding state every background consumer resolves."""

    intent_revision: int
    mode: str
    binding_ids: tuple[str, ...]
    intent_provenance: str
    registry_revision: int

    @property
    def selection_provenance(self) -> str:
        if self.mode == INTENT_MODE_COMPATIBILITY:
            return (
                PROVENANCE_COMPATIBILITY_DEFAULT
                if self.intent_provenance == PROVENANCE_COMPATIBILITY_DEFAULT
                else PROVENANCE_COMPATIBILITY_HANDOFF
            )
        return PROVENANCE_BACKGROUND_INTENT


def stored_intent(snapshot: RegistrySnapshot) -> BackgroundBindingIntent | None:
    raw = snapshot.extensions.get(BACKGROUND_INTENT_KEY)
    return None if raw is None else BackgroundBindingIntent.from_payload(raw)


def handoff_complete(snapshot: RegistrySnapshot) -> bool:
    intent = stored_intent(snapshot)
    return bool(intent and intent.handoff_complete)


def durable_background_state(snapshot: RegistrySnapshot) -> BackgroundBindingState | None:
    """``None`` before the handoff (the bridge still owns the watcher)."""

    intent = stored_intent(snapshot)
    if intent is None or not intent.handoff_complete:
        return None
    BackgroundSupervisorRecord.from_payload(snapshot.extensions.get(BACKGROUND_SUPERVISOR_KEY))
    return BackgroundBindingState(
        intent_revision=intent.revision,
        mode=intent.mode,
        binding_ids=intent.effective_binding_ids(),
        intent_provenance=intent.provenance,
        registry_revision=snapshot.revision,
    )


def background_capability_digest(
    *, instance_identity: str, intent_revision: int, binding_id: str | None, generation: int
) -> str:
    """Server-derived, domain-separated, non-reversible; never an authority grant."""

    material = b"\x00".join(
        (
            BACKGROUND_CAPABILITY_DOMAIN,
            instance_identity.encode(),
            str(intent_revision).encode(),
            (binding_id or "no-vault").encode(),
            str(generation).encode(),
        )
    )
    return hashlib.sha256(material).hexdigest()


# -- the bridge handoff -------------------------------------------------------------------


def _handoff_fault_point(stage: str) -> None:
    """Process-failure injection seam for the handoff; production is a no-op."""

    del stage


def _resolve_handoff_binding(
    snapshot: RegistrySnapshot, legacy_bootstrap_root: Path | None
) -> tuple[str | None, str, int]:
    """Live bridge binding > instance default > registered legacy bootstrap > no-vault."""

    from app.instance.settings_rebind import SettingsRebindRecord

    bridge_revision = 0
    bridge_cleared = False
    if snapshot.settings_rebind is not None:
        record = SettingsRebindRecord.from_payload(snapshot.settings_rebind)
        bridge_revision = record.desired_revision
        if record.phase == "prepared":
            raise CapabilityNotReadyError(
                "the legacy picker bridge has a prepared revision; let it commit or "
                "cancel before the supervisor handoff"
            )
        if record.reload_revision not in {None, record.desired_revision}:
            raise CapabilityNotReadyError(
                "the legacy picker bridge is awaiting its settings reload"
            )
        if record.candidate_binding_id is not None:
            if record.candidate_binding_id not in snapshot.registrations:
                raise RegistryError("the live bridge binding is not registered")
            return record.candidate_binding_id, PROVENANCE_COMPATIBILITY_HANDOFF, bridge_revision
        # A completed clear keeps the cleared binding as prior; ``candidate`` and ``prior``
        # both empty is never-bound (#5644), even when a first selection was cancelled.
        bridge_cleared = record.prior_binding_id is not None
    if snapshot.default_vault_binding_id is not None:
        return snapshot.default_vault_binding_id, PROVENANCE_COMPATIBILITY_DEFAULT, bridge_revision
    if legacy_bootstrap_root is not None:
        from app.instance.default_vault import (
            VaultSelectionError,
            resolve_legacy_bootstrap_binding,
        )

        try:
            binding = resolve_legacy_bootstrap_binding(snapshot, legacy_bootstrap_root)
        except VaultSelectionError as exc:
            # The MVR-01B legacy bootstrap must already be enrolled; MVR-06 never
            # creates a binding of its own.
            raise RegistryError(
                "the legacy bootstrap root is not one already-enrolled binding"
            ) from exc
        return binding, PROVENANCE_COMPATIBILITY_HANDOFF, bridge_revision
    if bridge_cleared or not snapshot.registrations:
        # The live bridge durably cleared its binding, or there is no vault at all.
        return None, PROVENANCE_COMPATIBILITY_HANDOFF, bridge_revision
    enrolled = list(snapshot.registrations.values())
    if len(enrolled) == 1 and enrolled[0].extensions.get("provenance") in LEGACY_ENROLLMENT_PROVENANCES:
        # A headless one-vault install: the single registration MVR-01B enrolled is durable
        # truth, readable where the vault itself is not mounted.
        return enrolled[0].vault_binding_id, PROVENANCE_COMPATIBILITY_HANDOFF, bridge_revision
    # Registered vaults with no bridge binding, no default, and no provable bootstrap: never
    # persist no-vault by omission, which would idle a running watcher.
    raise RegistryError(
        "the handoff cannot prove which binding the watcher runs on; set the instance "
        "default or pass --legacy-bootstrap-root"
    )


@dataclass(frozen=True)
class HandoffReceipt:
    snapshot: RegistrySnapshot
    handed_off: bool

    def as_dict(self) -> dict[str, Any]:
        state = durable_background_state(self.snapshot)
        assert state is not None
        return {
            "handed_off": self.handed_off,
            "intent_mode": state.mode,
            "intent_revision": state.intent_revision,
            "compatibility_binding_id": state.binding_ids[0] if state.binding_ids else None,
            "registry_revision": self.snapshot.revision,
            "retired_bridge": "settings_rebind.v1",
        }


def run_compatibility_bridge_handoff(
    registry: VaultRegistryStore,
    *,
    channel_id: str,
    ownership_root: Path | None,
    legacy_bootstrap_root: Path | None = None,
    stopped_window_proven: bool = False,
    _capability: Any = None,
) -> HandoffReceipt:
    """Retire the #3163 bridge and seat the supervisor in one fail-closed cutover.

    The MVR-05 scalar worker is drained first: the exclusive binding-effect lease on
    the live binding waits out every in-flight shared worker/watcher/settings effect and
    blocks new ones until the commit, so no effect straddles the authority change. Inside
    a proved stopped window every consumer is already stopped, so that proof is the drain.
    The commit itself is a single registry generation.
    """

    from app.instance.settings_rebind import (
        SettingsRebindRecord,
        compatibility_ingress_window,
    )

    _require_storage_mutation_capability(_capability)
    snapshot = registry.load()
    staged = stored_intent(snapshot)
    if staged is None:
        raise CapabilityNotReadyError(
            "the MVR-06A background-authority cutover must commit the staged intent first"
        )
    if staged.handoff_complete:
        return HandoffReceipt(snapshot=snapshot, handed_off=False)
    with compatibility_ingress_window(registry, transition=True):
        snapshot = registry.load()
        binding, provenance, bridge_revision = _resolve_handoff_binding(
            snapshot, legacy_bootstrap_root
        )
        intent = BackgroundBindingIntent(
            revision=staged.revision + 1,
            mode=INTENT_MODE_COMPATIBILITY,
            compatibility_handoff="complete",
            compatibility_binding_id=binding,
            background_vault_binding_ids=(),
            provenance=provenance,
        )
        supervisor = BackgroundSupervisorRecord(
            handoff_registry_revision=snapshot.revision + 1,
            handoff_intent_revision=intent.revision,
            retired_bridge_revision=bridge_revision,
        )
        journal: dict[str, Any] | None = None
        if snapshot.settings_rebind is not None:
            record = SettingsRebindRecord.from_payload(snapshot.settings_rebind)
            if record.candidate_binding_id != binding:
                if record.phase not in {"dormant", "no_lifecycle", "cancelled"} or (
                    record.candidate_binding_id is not None
                ):
                    raise RegistryError("the bridge journal disagrees with the handoff binding")
                # An unbound dormant journal (env-only one-vault install) adopts the
                # migrated legacy bootstrap so the watcher keeps running after restart.
                journal = replace(
                    record, prior_binding_id=binding, candidate_binding_id=binding
                ).as_payload()

        def commit() -> RegistrySnapshot:
            _handoff_fault_point("before_commit")
            committed = registry.complete_background_handoff(
                intent=intent,
                supervisor=supervisor,
                settings_rebind=journal,
                expected_revision=snapshot.revision,
                _capability=_capability,
            )
            _handoff_fault_point("after_commit")
            return committed

        # A proved stopped window is the drain: every consumer is stopped, and the init
        # container may see no vault or the image's own directory at the registered path.
        if binding is not None and ownership_root is not None and not stopped_window_proven:
            from app.instance.binding_effect_lease import BindingEffectLeaseManager

            registration = snapshot.registrations[binding]
            leases = BindingEffectLeaseManager.for_runtime(
                registry_store=registry,
                ownership_root=ownership_root,
                state_root=registry.path.parent / "binding-effect-leases",
            )
            _handoff_fault_point("drain")
            with leases.exclusive_change(
                binding,
                channel_id=channel_id,
                root=Path(registration.path),
                timeout=HANDOFF_DRAIN_TIMEOUT_SECONDS,
            ):
                committed = commit()
        else:
            committed = commit()
    emit_background_intent_event(committed, reason="compatibility_handoff")
    return HandoffReceipt(snapshot=committed, handed_off=True)


# -- wake-up hints ------------------------------------------------------------------------


def emit_background_intent_event(snapshot: RegistrySnapshot, *, reason: str) -> str | None:
    """Publish the idempotent wake-up hint for one durable intent revision.

    The committed registry revision is the authority; this row only accelerates
    reconciliation, so a lost or duplicated hint can neither split nor stall truth.
    """

    state = durable_background_state(snapshot)
    if state is None:
        return None
    from app.events.models import new_event
    from app.events.types import INSTANCE_BACKGROUND_INTENT_CHANGED
    from app.instance.binding_ids import OUTBOX_GLOBAL_BINDING_ID
    from app.services.outbox import derive_idempotency_key, write_outbox_event

    payload = {
        "event_version": 1,
        "intent_revision": state.intent_revision,
        "registry_revision": snapshot.revision,
        "mode": state.mode,
        "vault_binding_ids": list(state.binding_ids),
        "reason": reason,
    }
    try:
        return write_outbox_event(
            new_event(
                event_type=INSTANCE_BACKGROUND_INTENT_CHANGED,
                payload=payload,
                source="instance.background_supervisor",
            ),
            idempotency_key=derive_idempotency_key(
                INSTANCE_BACKGROUND_INTENT_CHANGED,
                str(state.intent_revision),
                "instance-background-intent-changed-v1",
            ),
            vault_binding_id=OUTBOX_GLOBAL_BINDING_ID,
            required_db=False,
            producer="shared.instance.background_supervisor",
        )
    except Exception as exc:  # the durable revision cursor closes this window
        _hint(f"wake-up hint for intent revision {state.intent_revision} not published: {exc}")
        return None


# -- governed singleton/empty producers ---------------------------------------------------


def _authorize_content(snapshot: RegistrySnapshot, binding_id: str, registry_path: Path) -> None:
    from app.governance.binding_authority import BindingAuthorizationError
    from app.instance.scalar_binding_runtime import _authorize_binding

    try:
        _authorize_binding(snapshot, binding_id, registry_path)
    except BindingAuthorizationError as exc:
        raise BackgroundLifecycleError(
            f"binding {binding_id} is not content-authorized for background work"
        ) from exc
    except RegistryError:
        raise


def apply_governed_intent_mutation(
    registry: VaultRegistryStore,
    *,
    command: Literal["add", "remove"],
    vault_binding_id: str,
    authorize: Callable[[RegistrySnapshot, str], None] | None = None,
) -> RegistrySnapshot:
    """The one MVR-06B add/remove producer behind the API router and the CLI.

    The first mutation in compatibility mode snapshots the effective singleton (or the
    truthful no-vault empty set) inside the same revision-checked transaction before it
    applies the command; a second binding is ``capability_not_ready`` without changing
    mode or stopping the compatibility lifecycle.
    """

    from app.instance.settings_rebind import SettingsRebindActivation

    target = (vault_binding_id or "").strip()
    if not target:
        raise RegistryError("vault_binding_id is required")
    snapshot = registry.load()
    intent = stored_intent(snapshot)
    if intent is None or not intent.handoff_complete:
        raise CapabilityNotReadyError(
            "capability_not_ready: background intent mutation is sealed until the MVR-06B "
            "supervisor handoff; the legacy watcher remains authoritative"
        )
    BackgroundSupervisorRecord.from_payload(snapshot.extensions.get(BACKGROUND_SUPERVISOR_KEY))
    base = intent.effective_binding_ids()
    if command == "add":
        registration = snapshot.registrations.get(target)
        if registration is None:
            raise RegistryError(f"unknown vault_binding_id: {target}")
        if registration.extensions.get(LIFECYCLE_STATE_KEY) in SEALED_LIFECYCLE_STATES:
            raise BackgroundLifecycleError(f"binding {target} is sealed by its lifecycle")
        (authorize or (lambda snap, item: _authorize_content(snap, item, registry.path)))(
            snapshot, target
        )
        if target in base:
            members = base
        elif len(base) >= MVR06B_MAX_BACKGROUND_BINDINGS:
            raise CapabilityNotReadyError(
                "capability_not_ready: a second background binding is gated until "
                "MVR-06C/06D; remove the current member before adding another"
            )
        else:
            members = (*base, target)
    else:
        # Instance-administrative removal: idempotent and independent of registry
        # membership or content authority, so failed stale intent can always be cleared.
        members = tuple(item for item in base if item != target)
    next_intent = BackgroundBindingIntent(
        revision=intent.revision + 1,
        mode=INTENT_MODE_EXPLICIT,
        compatibility_handoff="complete",
        compatibility_binding_id=None,
        background_vault_binding_ids=tuple(sorted(set(members))),
        provenance=PROVENANCE_BACKGROUND_INTENT,
    )
    if intent.mode == INTENT_MODE_EXPLICIT and next_intent.background_vault_binding_ids == (
        intent.background_vault_binding_ids
    ):
        return snapshot  # idempotent: no new revision, no new hint
    running_before = _running(snapshot, base)
    running_after = _running(snapshot, next_intent.background_vault_binding_ids)
    if running_before == running_after:
        from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY
        from app.instance.settings_rebind import compatibility_ingress_window

        with compatibility_ingress_window(registry, transition=True):
            current = registry.load()
            if stored_intent(current) != intent:
                raise RegistryError("background intent changed concurrently; retry")
            committed = registry.commit_background_intent(
                next_intent,
                expected_revision=current.revision,
                _capability=_STORAGE_MUTATION_CAPABILITY,
            )
    else:
        candidate = running_after[0] if running_after else None
        root = Path(snapshot.registrations[candidate].path) if candidate else None
        SettingsRebindActivation.from_environment(registry).activate_background(
            candidate_binding_id=candidate,
            candidate_root=root,
            intent=next_intent,
        )
        committed = registry.load()
    emit_background_intent_event(committed, reason=f"governed_{command}")
    return committed


def _running(snapshot: RegistrySnapshot, members: tuple[str, ...]) -> tuple[str, ...]:
    """Members a lifecycle can actually run (removed or sealed members stay failed intent)."""

    return tuple(
        item
        for item in members
        if item in snapshot.registrations
        and snapshot.registrations[item].extensions.get(LIFECYCLE_STATE_KEY) is None
    )


def repair_background_intent_for_transfer(
    registry: VaultRegistryStore, source_binding_id: str
) -> None:
    """The schema-versioned MVR-06 transfer hook (replaces the retired bridge hook).

    Compatibility mode preserves the enabled watcher as durable idle/no-vault (no
    implicit replacement is chosen); explicit mode removes only the transferred member.
    Neither enrols the destination. A revision race or failed commit raises, aborting
    the transfer with source ownership unchanged.
    """

    from app.instance.settings_rebind import SettingsRebindActivation

    snapshot = registry.load()
    intent = stored_intent(snapshot)
    if intent is None or not intent.handoff_complete:
        raise CapabilityNotReadyError("the MVR-06 transfer hook requires the completed handoff")
    if source_binding_id not in intent.effective_binding_ids():
        return
    if intent.mode == INTENT_MODE_COMPATIBILITY:
        next_intent = replace(
            intent,
            revision=intent.revision + 1,
            compatibility_binding_id=None,
            provenance=PROVENANCE_COMPATIBILITY_HANDOFF,
        )
    else:
        next_intent = replace(
            intent,
            revision=intent.revision + 1,
            background_vault_binding_ids=tuple(
                item for item in intent.background_vault_binding_ids if item != source_binding_id
            ),
            provenance=PROVENANCE_BACKGROUND_INTENT,
        )
    SettingsRebindActivation.from_environment(registry).activate_background(
        candidate_binding_id=None, candidate_root=None, intent=next_intent
    )
    emit_background_intent_event(registry.load(), reason="channel_transfer")


# -- the supervisor ----------------------------------------------------------------------


@dataclass(frozen=True)
class BackgroundLifecycle:
    """One immutable lifecycle generation; rotation produces a new object."""

    binding_id: str | None
    generation: int
    status: LifecycleStatus
    context: ActiveContextSetV1 | None
    root: Path | None
    intent_revision: int
    registry_revision: int
    binding_revision: int
    auth_epoch: int
    authorization_epoch: str
    failure: str | None = None

    def health(self) -> dict[str, Any]:
        """Bounded, redacted health projection (no host path, no binding payload)."""

        return {
            "binding_id": self.binding_id,
            "generation": self.generation,
            "status": self.status,
            "intent_revision": self.intent_revision,
            "registry_revision": self.registry_revision,
            "auth_epoch": self.auth_epoch,
            "context_id": None if self.context is None else self.context.context_id,
            "capability_digest": (
                None if self.context is None else self.context.selection_capability_digest
            ),
            "failure": self.failure,
        }


def _binding_revision(snapshot: RegistrySnapshot, binding_id: str) -> int:
    from app.instance.scalar_binding_runtime import _binding_revision as revision

    return revision(snapshot, binding_id)


class BackgroundLifecycleSupervisor:
    """Revision/auth-reconciling, ownership-checked, effect-leased singleton supervisor.

    One instance runs inside each background process (watcher, worker, settings). It
    never mints identity: the principal is the MVR-06A delegated background role.
    """

    def __init__(
        self,
        *,
        registry: VaultRegistryStore,
        ownership_ledger: Any,
        effect_leases: BindingEffectLeaseManager,
        role_store: BackgroundRuntimeRoleStore,
        principal_store: LocalOperatorPrincipalStore,
        channel_id: str,
        consumer: str,
        drain_timeout: float = 30.0,
    ) -> None:
        self.registry = registry
        self.ownership_ledger = ownership_ledger
        self.effect_leases = effect_leases
        self.role_store = role_store
        self.principal_store = principal_store
        self.channel_id = channel_id
        self.consumer = consumer
        self.drain_timeout = drain_timeout
        self._lifecycle: BackgroundLifecycle | None = None

    @classmethod
    def for_runtime(
        cls,
        *,
        registry_path: Path,
        ownership_root: Path,
        channel_id: str,
        consumer: str,
    ) -> BackgroundLifecycleSupervisor:
        from app.instance.binding_effect_lease import BindingEffectLeaseManager
        from app.instance.runtime import (
            open_background_role_store,
            open_local_operator_principal_store,
        )

        registry = VaultRegistryStore(Path(registry_path))
        leases = BindingEffectLeaseManager.for_runtime(
            registry_store=registry,
            ownership_root=ownership_root,
            state_root=registry.path.parent / "binding-effect-leases",
        )
        return cls(
            registry=registry,
            ownership_ledger=leases.ownership_ledger,
            effect_leases=leases,
            role_store=open_background_role_store(Path(registry_path)),
            principal_store=open_local_operator_principal_store(Path(registry_path)),
            channel_id=channel_id,
            consumer=consumer,
        )

    @property
    def lifecycle(self) -> BackgroundLifecycle | None:
        return self._lifecycle

    # -- resolution ---------------------------------------------------------------------

    def _role(self) -> Any:
        from app.instance.background_authority import validate_background_delegation

        delegator = self.principal_store.load()
        if delegator is None:
            raise BackgroundLifecycleError("the background delegation has no delegator")
        role = self.role_store.require()
        validate_background_delegation(role, delegator)
        return role

    def _resolve(self, generation: int) -> BackgroundLifecycle:
        snapshot = self.registry.load()
        state = durable_background_state(snapshot)
        if state is None:
            raise CapabilityNotReadyError(
                "the MVR-06B supervisor is not authoritative before the bridge handoff"
            )
        if len(state.binding_ids) > MVR06B_MAX_BACKGROUND_BINDINGS:
            raise CapabilityNotReadyError("many-binding supervision is sealed until MVR-06D")
        try:
            role = self._role()
        except Exception as exc:
            return self._failed(snapshot, state, generation, None, f"authorization: {exc}", 0)
        if not state.binding_ids:
            return BackgroundLifecycle(
                binding_id=None,
                generation=generation,
                status="idle",
                context=self._context(snapshot, state, None, generation, role, None),
                root=None,
                intent_revision=state.intent_revision,
                registry_revision=snapshot.revision,
                binding_revision=0,
                auth_epoch=role.auth_epoch,
                authorization_epoch=f"auth-epoch-{role.auth_epoch}",
            )
        binding = state.binding_ids[0]
        registration = snapshot.registrations.get(binding)
        if registration is None:
            return self._failed(
                snapshot, state, generation, binding, "binding is not registered", role.auth_epoch
            )
        lifecycle_state = registration.extensions.get(LIFECYCLE_STATE_KEY)
        if lifecycle_state in SEALED_LIFECYCLE_STATES:
            return self._failed(
                snapshot, state, generation, binding, f"binding is {lifecycle_state}", role.auth_epoch
            )
        root = Path(registration.path)
        try:
            self._require_ownership(binding, root)
            from app.instance.scalar_binding_runtime import _authorize_binding

            verdict = _authorize_binding(snapshot, binding, self.registry.path)
        except Exception as exc:
            return self._failed(snapshot, state, generation, binding, str(exc), role.auth_epoch)
        authorization_epoch = f"{verdict.epoch}|auth-epoch-{role.auth_epoch}"
        return BackgroundLifecycle(
            binding_id=binding,
            generation=generation,
            status="running",
            context=self._context(snapshot, state, binding, generation, role, authorization_epoch),
            root=root,
            intent_revision=state.intent_revision,
            registry_revision=snapshot.revision,
            binding_revision=_binding_revision(snapshot, binding),
            auth_epoch=role.auth_epoch,
            authorization_epoch=authorization_epoch,
        )

    def _require_ownership(self, binding: str, root: Path) -> None:
        """The exact channel/root lease must be active; runtime state never self-claims."""

        lease = self.ownership_ledger.load().leases.get(binding)
        if lease is None:
            raise BackgroundLifecycleError("binding has no ownership lease")
        if lease.state != "active":
            raise BackgroundLifecycleError(f"binding ownership lease is {lease.state}")
        if lease.channel_id != self.channel_id:
            raise BackgroundLifecycleError("binding root is leased to another release channel")
        try:
            with self.ownership_ledger.active_binding_fence(
                binding, channel_id=self.channel_id, root=root
            ):
                pass
        except Exception as exc:
            raise BackgroundLifecycleError("binding root does not match its ownership lease") from exc

    def _failed(
        self,
        snapshot: RegistrySnapshot,
        state: BackgroundBindingState,
        generation: int,
        binding: str | None,
        failure: str,
        auth_epoch: int,
    ) -> BackgroundLifecycle:
        logger.error(
            "background lifecycle failed consumer=%s binding=%s generation=%s: %s",
            self.consumer,
            binding,
            generation,
            failure,
        )
        return BackgroundLifecycle(
            binding_id=binding,
            generation=generation,
            status="failed",
            context=None,
            root=None,
            intent_revision=state.intent_revision,
            registry_revision=snapshot.revision,
            binding_revision=0 if binding is None else _binding_revision(snapshot, binding),
            auth_epoch=auth_epoch,
            authorization_epoch="",
            failure=failure,
        )

    def _context(
        self,
        snapshot: RegistrySnapshot,
        state: BackgroundBindingState,
        binding: str | None,
        generation: int,
        role: Any,
        authorization_epoch: str | None,
    ) -> ActiveContextSetV1:
        from app.vault.active_context_v1 import (
            ActiveContextBinding,
            ActiveContextSetV1,
            PrincipalContext,
            WorkspaceState,
        )

        registration = snapshot.registrations.get(binding) if binding else None
        bindings: tuple[ActiveContextBinding, ...] = ()
        if binding is not None and registration is not None:
            bindings = (
                ActiveContextBinding(
                    vault_binding_id=binding,
                    binding_revision=_binding_revision(snapshot, binding),
                    authorization_epoch=authorization_epoch or "",
                    vault_id=registration.vault_id,
                    local_instance_id=registration.local_instance_id,
                ),
            )
        digest = background_capability_digest(
            instance_identity=snapshot.app_install_id,
            intent_revision=state.intent_revision,
            binding_id=binding,
            generation=generation,
        )
        return ActiveContextSetV1(
            context_id=f"background:{self.consumer}:{state.intent_revision}:{generation}",
            generation=generation,
            workspace=WorkspaceState.none(),
            scope=BACKGROUND_CONTEXT_SCOPE,
            sphere_memberships=(),
            situated_identity=None,
            principal_context=PrincipalContext(
                principal_id=role.background_runtime_role_id,
                principal_kind="background_runtime_role",
                subject="instance_background_runtime",
                revision=role.revision,
            ),
            instance_identity=snapshot.app_install_id,
            source_bindings=bindings,
            registry_revision=snapshot.revision,
            authorization_epoch=authorization_epoch or f"auth-epoch-{role.auth_epoch}",
            selection_provenance=state.selection_provenance,
            selection_capability_digest=digest,
        )

    # -- lifecycle ----------------------------------------------------------------------

    def start(self) -> BackgroundLifecycle:
        self._lifecycle = self._resolve(1)
        return self._lifecycle

    def _cursor_changed(self, current: BackgroundLifecycle) -> bool:
        snapshot = self.registry.load()
        state = durable_background_state(snapshot)
        if state is None:
            return True
        role = self.role_store.load()
        if role is None or role.auth_epoch != current.auth_epoch:
            return True
        if state.intent_revision != current.intent_revision:
            return True
        binding = current.binding_id
        if binding is None:
            return bool(state.binding_ids)
        registration = snapshot.registrations.get(binding)
        if state.binding_ids != (binding,):
            return True
        if registration is None:
            return current.status != "failed"
        if registration.extensions.get(LIFECYCLE_STATE_KEY) in SEALED_LIFECYCLE_STATES:
            return current.status != "failed"
        return _binding_revision(snapshot, binding) != current.binding_revision

    def reconcile(self) -> BackgroundLifecycle:
        """Converge from durable registry revision + auth epoch (hints only accelerate).

        A failed lifecycle is retried on every call: ownership or authority repair has
        no registry revision of its own, so only a fresh resolution can observe it.
        """

        current = self._lifecycle
        if current is None:
            return self.start()
        if current.status != "failed" and not self._cursor_changed(current):
            return current
        if not self._drain(current):
            self._lifecycle = replace(
                current,
                status="failed",
                failure="the prior generation's in-flight effects have not drained",
            )
            return self._lifecycle
        resolved = self._resolve(current.generation + 1)
        if (
            current.status == "failed"
            and resolved.status == "failed"
            and (resolved.binding_id, resolved.failure) == (current.binding_id, current.failure)
            and resolved.intent_revision == current.intent_revision
        ):
            # An unchanged failure is the same generation, not a rotation.
            resolved = replace(resolved, generation=current.generation)
        self._lifecycle = resolved
        return self._lifecycle

    def _drain(self, lifecycle: BackgroundLifecycle) -> bool:
        """Wait out in-flight shared effects of the old generation before rotating."""

        from app.instance.binding_effect_lease import (
            BindingEffectLeaseError,
            OwnershipFenceUnavailable,
        )

        if lifecycle.binding_id is None or lifecycle.root is None:
            return True
        if self.ownership_ledger.active_owner(lifecycle.binding_id) is None:
            return True  # removal/transfer already drained and retired the lease
        try:
            with self.effect_leases.exclusive_change(
                lifecycle.binding_id,
                channel_id=self.channel_id,
                root=lifecycle.root,
                timeout=self.drain_timeout,
            ):
                return True
        except OwnershipFenceUnavailable:
            # The fence refuses every new holder; resolution below fails closed.
            return True
        except BindingEffectLeaseError as exc:
            if lifecycle.binding_id not in self.registry.load().registrations:
                return True  # the removal commit retired this binding's lease state
            logger.error(
                "background lifecycle drain not proven consumer=%s binding=%s: %s",
                self.consumer,
                lifecycle.binding_id,
                exc,
            )
            return False

    def require_current(self, lifecycle: BackgroundLifecycle) -> None:
        """Final validation inside the shared lease: durable truth and GOV are unchanged."""

        if self._cursor_changed(lifecycle) or lifecycle.binding_id is None:
            raise BackgroundLifecycleStale(
                "durable binding/auth truth changed before the effect; reconcile first"
            )
        from app.instance.scalar_binding_runtime import _authorize_binding

        verdict = _authorize_binding(self.registry.load(), lifecycle.binding_id, self.registry.path)
        role = self._role()
        if f"{verdict.epoch}|auth-epoch-{role.auth_epoch}" != lifecycle.authorization_epoch:
            raise BackgroundLifecycleStale("GOV authorization changed before the effect")

    @contextmanager
    def effect(self) -> Iterator[BackgroundLifecycle]:
        """Host-global fence -> shared effect lease -> revalidate; held through receipt."""

        lifecycle = self.reconcile()
        if lifecycle.status != "running" or lifecycle.binding_id is None or lifecycle.root is None:
            if lifecycle.status == "idle":
                raise BackgroundBindingIdle("durable background intent runs no binding")
            raise BackgroundLifecycleError(
                f"background lifecycle is {lifecycle.status}: {lifecycle.failure}"
            )
        with self.effect_leases.shared_effect(
            lifecycle.binding_id, channel_id=self.channel_id, root=lifecycle.root
        ):
            self.require_current(lifecycle)
            yield lifecycle

    def health(self) -> dict[str, Any]:
        lifecycle = self._lifecycle
        return {
            "consumer": self.consumer,
            "supervisor": "mvr06b-singleton",
            "lifecycles": [] if lifecycle is None else [lifecycle.health()],
        }


_PROCESS_SUPERVISORS: dict[tuple[str, str, str, str], BackgroundLifecycleSupervisor] = {}
_PROCESS_SUPERVISORS_LOCK = threading.Lock()


def process_background_supervisor(consumer: str) -> BackgroundLifecycleSupervisor | None:
    """The one supervisor of this watcher/worker process, or ``None`` before the handoff.

    Generations are per-process and in-memory: a restart reconstructs them from durable
    intent. The registry and ownership mounts come from the same env as every consumer.
    """

    registry_raw = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    if not registry_raw:
        return None
    registry_path = Path(registry_raw).expanduser().resolve(strict=False)
    if not registry_path.exists() or durable_background_state(
        VaultRegistryStore(registry_path).load()
    ) is None:
        return None
    ownership_raw = os.getenv("INSTANCE_OWNERSHIP_ROOT", "").strip()
    if not ownership_raw:
        raise BackgroundLifecycleError("background supervision requires the ownership root")
    channel = os.getenv("PKM_ENVIRONMENT", "dev").strip() or "dev"
    key = (str(registry_path), ownership_raw, channel, consumer)
    with _PROCESS_SUPERVISORS_LOCK:
        supervisor = _PROCESS_SUPERVISORS.get(key)
        if supervisor is None:
            supervisor = BackgroundLifecycleSupervisor.for_runtime(
                registry_path=registry_path,
                ownership_root=Path(ownership_raw).expanduser(),
                channel_id=channel,
                consumer=consumer,
            )
            _PROCESS_SUPERVISORS[key] = supervisor
    return supervisor


def durable_background_root() -> tuple[bool, Path | None]:
    """``(True, root-or-None)`` once durable intent owns the binding, else ``(False, None)``.

    An unreadable registry reports ``False``: the caller's resolver then fails closed on
    its own read, so this probe never turns a corrupt registry into a silent idle.
    """

    registry_raw = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    if not registry_raw:
        return False, None
    try:
        registry_path = Path(registry_raw).expanduser().resolve(strict=False)
        if not registry_path.exists():
            return False, None
        snapshot = VaultRegistryStore(registry_path).load()
        state = durable_background_state(snapshot)
    except Exception:
        return False, None
    if state is None:
        return False, None
    running = _running(snapshot, state.binding_ids)
    if not running:
        return True, None
    return True, Path(snapshot.registrations[running[0]].path).expanduser()


def revoke_background_role_fenced(
    *,
    registry: VaultRegistryStore,
    role_store: BackgroundRuntimeRoleStore,
    ownership_root: Path,
    channel_id: str,
    timeout: float | None = 30.0,
    _capability: Any = None,
) -> Any:
    """GOV revocation through the ownership fence -> exclusive binding lease order.

    A racing background effect either finishes (its shared lease is drained first) or
    is blocked before effect: the auth epoch advances while the exclusive lease is held.
    """

    from app.instance.binding_effect_lease import BindingEffectLeaseManager

    _require_storage_mutation_capability(_capability)
    snapshot = registry.load()
    state = durable_background_state(snapshot)
    # Sealed members included: a draining binding can still hold an in-flight effect, and
    # its exclusive lease stays available for exactly this kind of change.
    bindings = (
        ()
        if state is None
        else tuple(item for item in state.binding_ids if item in snapshot.registrations)
    )
    leases = BindingEffectLeaseManager.for_runtime(
        registry_store=registry,
        ownership_root=ownership_root,
        state_root=registry.path.parent / "binding-effect-leases",
    )

    def revoke(remaining: tuple[str, ...]) -> Any:
        if not remaining:
            return role_store.revoke(_capability=_capability)
        binding = remaining[0]
        registration = snapshot.registrations[binding]
        if leases.active_owner(binding) is None:
            return revoke(remaining[1:])
        with leases.exclusive_change(
            binding, channel_id=channel_id, root=Path(registration.path), timeout=timeout
        ):
            return revoke(remaining[1:])

    return revoke(bindings)


__all__ = [
    "BackgroundBindingIdle",
    "BackgroundBindingState",
    "BackgroundLifecycle",
    "BackgroundLifecycleError",
    "BackgroundLifecycleStale",
    "BackgroundLifecycleSupervisor",
    "HandoffReceipt",
    "LIFECYCLE_DRAINING_REMOVAL",
    "LIFECYCLE_REACTIVATING",
    "LIFECYCLE_STATE_KEY",
    "SEALED_LIFECYCLE_STATES",
    "apply_governed_intent_mutation",
    "background_capability_digest",
    "durable_background_state",
    "emit_background_intent_event",
    "durable_background_root",
    "handoff_complete",
    "process_background_supervisor",
    "repair_background_intent_for_transfer",
    "revoke_background_role_fenced",
    "run_compatibility_bridge_handoff",
    "stored_intent",
]
