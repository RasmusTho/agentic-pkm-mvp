"""Resolve the one active scalar-era vault to current MVR binding authority."""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.instance.binding_effect_lease import BindingEffectLeaseManager
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.instance.filesystem_identity import (
    resolve_filesystem_root_identity,
    same_filesystem_root,
)
from app.instance.ownership_ledger import OwnershipLedger
from app.instance.vault_registry import (
    REGISTRY_AUTHORITY_DORMANT,
    REGISTRY_AUTHORITY_ACTIVE,
    RegistryError,
    RegistrySnapshot,
    VaultRegistryStore,
)


@dataclass(frozen=True)
class ScalarBindingRuntime:
    vault_binding_id: str
    binding_revision: int
    authority: str
    authorization_epoch: str
    channel_id: str
    root: Path
    registry_store: VaultRegistryStore
    ownership_ledger: OwnershipLedger
    effect_leases: BindingEffectLeaseManager
    #: MVR-06B: the durable background-intent revision this worker runtime was resolved
    #: from (``None`` for the pre-handoff scalar/env-root resolution and foreground use).
    intent_revision: int | None = None
    #: MVR-06B: the full background ActiveContextSet capability digest (identity only).
    background_context_digest: str | None = None
    #: MVR-06B: ``True`` for a background-worker runtime (explicit versioned binding).
    background_worker: bool = False


_FROZEN_EFFECT_RUNTIME: ContextVar[ScalarBindingRuntime | None] = ContextVar(
    "mvr05_frozen_effect_runtime", default=None
)


def _binding_revision(snapshot: RegistrySnapshot, binding_id: str) -> int:
    registration = snapshot.registrations.get(binding_id)
    if registration is None:
        return 0
    recorded = (registration.extensions or {}).get("bindingRevision")
    return recorded if isinstance(recorded, int) and recorded > 0 else snapshot.revision


def _configured_root(explicit_root: Path | None) -> Path:
    if explicit_root is not None:
        return explicit_root.expanduser().resolve(strict=True)
    raw = (os.getenv("WATCHER_VAULT_PATH") or os.getenv("VAULT_ROOT") or "").strip()
    if not raw:
        raise RegistryError("the scalar binding translator requires a configured vault root")
    return Path(raw).expanduser().resolve(strict=True)


def _authorize_binding(
    snapshot: RegistrySnapshot, binding_id: str, registry_path: Path
) -> Any:
    """Resolve the delegated principal and obtain a real GOV verdict."""

    # Lazy imports keep the outbox module graph acyclic during process startup.
    from app.governance.binding_authority import (
        BindingAuthorizationError,
        BindingAuthorizationRequest,
        RegistryBindingAuthorizer,
    )
    from app.instance.local_operator_principal import (
        LocalOperatorPrincipalStore,
        PRINCIPAL_RECORD_FILENAME,
    )

    principal_record = LocalOperatorPrincipalStore(
        registry_path.parent / PRINCIPAL_RECORD_FILENAME
    ).load()
    if principal_record is None or not principal_record.subjects:
        raise RegistryError("binding runtime requires a governed local operator subject")
    principal = principal_record.principal_for(sorted(principal_record.subjects)[0])
    authorizer = RegistryBindingAuthorizer(
        {
            known_id: _binding_revision(snapshot, known_id)
            for known_id in snapshot.registrations
        }
    )
    verdict = authorizer.authorize(
        BindingAuthorizationRequest(
            principal=principal,
            vault_binding_id=binding_id,
            action="outbox.binding_effect",
            write_class="durable_effect",
            required_permission="vault.write",
        )
    )
    if not verdict.allowed:
        raise BindingAuthorizationError(verdict)
    return verdict


def validate_frozen_binding_runtime(runtime: ScalarBindingRuntime) -> ScalarBindingRuntime:
    """Re-resolve registry, root, ownership and GOV after the shared lease lands."""

    snapshot = runtime.registry_store.load()
    if snapshot.authority != REGISTRY_AUTHORITY_ACTIVE:
        raise RegistryError("binding runtime requires active registry authority")
    registration = snapshot.registrations.get(runtime.vault_binding_id)
    if registration is None:
        raise RegistryError("the leased binding is no longer registered")
    if _binding_revision(snapshot, runtime.vault_binding_id) != runtime.binding_revision:
        raise RegistryError("the leased binding revision changed before dispatch")
    if not same_filesystem_root(
        resolve_filesystem_root_identity(registration.path),
        resolve_filesystem_root_identity(runtime.root),
    ):
        raise RegistryError("the leased binding root changed before dispatch")
    verdict = _authorize_binding(
        snapshot, runtime.vault_binding_id, runtime.registry_store.path
    )
    if verdict.epoch != runtime.authorization_epoch:
        raise RegistryError("the leased binding GOV authorization epoch changed before dispatch")
    if runtime.background_worker:
        from app.instance.background_supervisor import durable_background_state

        state = durable_background_state(snapshot)
        if state is None or state.intent_revision != runtime.intent_revision:
            raise RegistryError(
                "the background worker binding revision changed before dispatch"
            )
        if state.binding_ids != (runtime.vault_binding_id,):
            raise RegistryError("the background worker binding is no longer durable intent")
    return runtime


@contextmanager
def frozen_binding_effect(runtime: ScalarBindingRuntime) -> Iterator[None]:
    """Reuse one revalidated shared-lease context for nested receipt writes."""

    token = _FROZEN_EFFECT_RUNTIME.set(runtime)
    try:
        yield
    finally:
        _FROZEN_EFFECT_RUNTIME.reset(token)


def current_binding_effect_runtime() -> ScalarBindingRuntime | None:
    """The already-admitted worker/write effect, never a new authority grant."""
    return _FROZEN_EFFECT_RUNTIME.get()


def resolve_scalar_binding_runtime(
    *,
    requested_binding_id: str | None = None,
    vault_root: Path | None = None,
) -> ScalarBindingRuntime | None:
    """Return ``None`` only for non-runtime/unit compatibility environments."""

    frozen = _FROZEN_EFFECT_RUNTIME.get()
    if frozen is not None:
        requested = (requested_binding_id or "").strip()
        if requested and requested not in {
            COMPATIBILITY_BINDING_ID,
            frozen.vault_binding_id,
        }:
            raise RegistryError("outbox binding does not match the frozen effect window")
        if vault_root is not None and not same_filesystem_root(
            resolve_filesystem_root_identity(vault_root),
            resolve_filesystem_root_identity(frozen.root),
        ):
            raise RegistryError("outbox root does not match the frozen effect window")
        return frozen

    registry_raw = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    ownership_raw = os.getenv("INSTANCE_OWNERSHIP_ROOT", "").strip()
    if not registry_raw and not ownership_raw:
        return None
    if not registry_raw or not ownership_raw:
        raise RegistryError("binding runtime requires both registry and ownership roots")

    registry = VaultRegistryStore(Path(registry_raw).expanduser().resolve(strict=True))
    snapshot = registry.load()
    requested = (requested_binding_id or "").strip()
    if snapshot.authority == REGISTRY_AUTHORITY_DORMANT:
        # MVR-01B deliberately keeps the registry non-authoritative.  The
        # legacy scalar app-local store remains the runtime source of truth
        # until the explicit MVR-01C cutover installs the rollback floor and
        # activates binding-keyed producers.  Returning the compatibility
        # posture here is distinct from an invalid active registry, which must
        # still fail closed below.
        if requested and requested != COMPATIBILITY_BINDING_ID:
            raise RegistryError("native binding requires active registry authority")
        return None
    if snapshot.authority != REGISTRY_AUTHORITY_ACTIVE:
        raise RegistryError("binding runtime requires active registry authority")
    root = _configured_root(vault_root)
    root_identity = resolve_filesystem_root_identity(root)
    matches = [
        registration
        for registration in snapshot.registrations.values()
        if same_filesystem_root(
            resolve_filesystem_root_identity(registration.path), root_identity
        )
    ]
    if len(matches) != 1:
        raise RegistryError("configured scalar root must resolve to exactly one active binding")
    registration = matches[0]
    if requested and requested not in {
        COMPATIBILITY_BINDING_ID,
        registration.vault_binding_id,
    }:
        raise RegistryError("outbox binding does not match the configured scalar root")

    channel = os.getenv("PKM_ENVIRONMENT", "dev").strip() or "dev"
    ledger = OwnershipLedger(Path(ownership_raw).expanduser().resolve(strict=True))
    with ledger.active_binding_fence(
        registration.vault_binding_id,
        channel_id=channel,
        root=root,
    ):
        pass
    verdict = _authorize_binding(snapshot, registration.vault_binding_id, registry.path)
    from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY
    return ScalarBindingRuntime(
        vault_binding_id=registration.vault_binding_id,
        binding_revision=_binding_revision(snapshot, registration.vault_binding_id),
        authority=verdict.status,
        authorization_epoch=verdict.epoch,
        channel_id=channel,
        root=root,
        registry_store=registry,
        ownership_ledger=ledger,
        effect_leases=BindingEffectLeaseManager(
            registry_store=registry,
            ownership_ledger=ledger,
            state_root=registry.path.parent / "binding-effect-leases",
            capability=_STORAGE_MUTATION_CAPABILITY,
        ),
    )


def resolve_background_worker_runtime(
    *, vault_root: Path | None = None
) -> ScalarBindingRuntime | None:
    """The worker's binding resolution: scalar env root before MVR-06B, durable after.

    Before the bridge handoff this is exactly :func:`resolve_scalar_binding_runtime`.
    After it the worker consumes explicit versioned binding state: the durable
    singleton intent resolved to its registration, ownership lease, GOV verdict, and
    full background ActiveContextSet identity. An env/selected root that is not the
    durable binding is refused, so no worker ever runs on the prior binding, and
    explicit-empty/no-vault intent idles the worker.
    """

    registry_raw = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    ownership_raw = os.getenv("INSTANCE_OWNERSHIP_ROOT", "").strip()
    if not registry_raw or not ownership_raw:
        return resolve_scalar_binding_runtime(vault_root=vault_root)
    registry = VaultRegistryStore(Path(registry_raw).expanduser().resolve(strict=True))
    snapshot = registry.load()
    from app.instance.background_supervisor import (
        BackgroundBindingIdle,
        background_capability_digest,
        durable_background_state,
    )

    state = durable_background_state(snapshot)
    if state is None:
        return resolve_scalar_binding_runtime(vault_root=vault_root)
    if snapshot.authority != REGISTRY_AUTHORITY_ACTIVE:
        raise RegistryError("background worker requires active registry authority")
    if not state.binding_ids:
        raise BackgroundBindingIdle("durable background intent runs no binding")
    if len(state.binding_ids) != 1:
        raise RegistryError("many-binding worker dispatch is sealed until MVR-06D")
    binding_id = state.binding_ids[0]
    registration = snapshot.registrations.get(binding_id)
    if registration is None:
        raise RegistryError("the durable background binding is not registered")
    root = Path(registration.path).expanduser().resolve(strict=True)
    if vault_root is not None and not same_filesystem_root(
        resolve_filesystem_root_identity(vault_root),
        resolve_filesystem_root_identity(root),
    ):
        raise RegistryError("the worker root is not the durable background binding")
    channel = os.getenv("PKM_ENVIRONMENT", "dev").strip() or "dev"
    ledger = OwnershipLedger(Path(ownership_raw).expanduser().resolve(strict=True))
    with ledger.active_binding_fence(binding_id, channel_id=channel, root=root):
        pass
    verdict = _authorize_binding(snapshot, binding_id, registry.path)
    from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

    return ScalarBindingRuntime(
        vault_binding_id=binding_id,
        binding_revision=_binding_revision(snapshot, binding_id),
        authority=verdict.status,
        authorization_epoch=verdict.epoch,
        channel_id=channel,
        root=root,
        registry_store=registry,
        ownership_ledger=ledger,
        effect_leases=BindingEffectLeaseManager(
            registry_store=registry,
            ownership_ledger=ledger,
            state_root=registry.path.parent / "binding-effect-leases",
            capability=_STORAGE_MUTATION_CAPABILITY,
        ),
        intent_revision=state.intent_revision,
        background_context_digest=background_capability_digest(
            instance_identity=snapshot.app_install_id,
            intent_revision=state.intent_revision,
            binding_id=binding_id,
            generation=1,
        ),
        background_worker=True,
    )


__all__ = [
    "ScalarBindingRuntime",
    "resolve_background_worker_runtime",
    "frozen_binding_effect",
    "resolve_scalar_binding_runtime",
    "validate_frozen_binding_runtime",
]
