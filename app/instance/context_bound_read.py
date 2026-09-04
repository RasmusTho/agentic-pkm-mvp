"""Canonical registry validation for immutable active-context filesystem reads.

The request snapshot deliberately carries stable binding provenance rather than
an ambient filesystem selection.  This seam turns those already-authorized
bindings into roots only after proving that the live registry still describes
the same binding revision.  A caller must use the returned roots for the whole
read operation; it cannot re-resolve a global vault midway through the request.
"""

from __future__ import annotations

import os
from contextlib import ExitStack, contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY
from app.instance.active_context_service import binding_revision_for
from app.instance.binding_effect_lease import BindingEffectLeaseError, BindingEffectLeaseManager
from app.instance.ownership_ledger import OwnershipLedger
from app.instance.vault_registry import VaultRegistryStore
from app.vault.active_context_v1 import ActiveContextSetV1, DegradedContextError


class ContextBoundReadError(RuntimeError):
    """A frozen request context cannot safely name a current read root."""


@dataclass(frozen=True)
class ContextBoundReadRoot:
    """One source root bound to an immutable request context generation."""

    vault_binding_id: str
    root: Path
    context_generation: int


def resolve_context_read_roots(
    context: ActiveContextSetV1,
    *,
    registry_store: VaultRegistryStore,
) -> tuple[ContextBoundReadRoot, ...]:
    """Resolve only roots whose current binding revision matches ``context``.

    Missing, moved, or revision-changed registrations fail the complete read
    before a caller opens a file.  This prevents a stale parent/snapshot from
    being silently rebound to a new root.
    """

    try:
        context.require_effect_capable()
    except DegradedContextError as exc:
        raise ContextBoundReadError("active context is degraded") from exc

    snapshot = registry_store.load()
    if snapshot.app_install_id != context.instance_identity:
        raise ContextBoundReadError("active context belongs to another instance")

    roots: list[ContextBoundReadRoot] = []
    for binding in context.source_bindings:
        registration = snapshot.registrations.get(binding.vault_binding_id)
        if registration is None:
            raise ContextBoundReadError("active context binding is no longer registered")
        if binding_revision_for(snapshot, binding.vault_binding_id) != binding.binding_revision:
            raise ContextBoundReadError("active context binding revision changed")
        root = Path(registration.path).expanduser().resolve(strict=False)
        if not root.is_dir():
            raise ContextBoundReadError("active context source is inaccessible")
        roots.append(
            ContextBoundReadRoot(
                vault_binding_id=binding.vault_binding_id,
                root=root,
                context_generation=context.generation,
            )
        )
    return tuple(roots)


@contextmanager
def context_bound_read_window(
    context: ActiveContextSetV1,
    *,
    registry_store: VaultRegistryStore,
) -> Iterator[tuple[ContextBoundReadRoot, ...]]:
    """Hold every selected binding's shared lease through filesystem I/O.

    The authoritative ownership fence is acquired by the existing lease
    manager before each binding lock.  Registry/revision validation runs again
    after all locks are held, so a revocation or relocation cannot cross the
    request's read-to-publication window.
    """

    ownership_root = os.getenv("INSTANCE_OWNERSHIP_ROOT", "").strip()
    if not ownership_root:
        raise ContextBoundReadError("instance ownership root is not bound")
    roots = resolve_context_read_roots(context, registry_store=registry_store)
    channel = os.getenv("PKM_ENVIRONMENT", "dev").strip() or "dev"
    leases = BindingEffectLeaseManager(
        registry_store=registry_store,
        ownership_ledger=OwnershipLedger(Path(ownership_root).expanduser().resolve(strict=False)),
        state_root=registry_store.path.parent / "binding-effect-leases",
        capability=_STORAGE_MUTATION_CAPABILITY,
    )
    try:
        with ExitStack() as stack:
            for source in roots:
                stack.enter_context(
                    leases.shared_effect(source.vault_binding_id, channel_id=channel, root=source.root)
                )
            # Do not hand an already-invalidated root to the caller after taking a
            # lease. This is the final revalidation immediately before I/O.
            refreshed = resolve_context_read_roots(context, registry_store=registry_store)
            yield refreshed
    except BindingEffectLeaseError as exc:
        raise ContextBoundReadError("active context effect lease is unavailable") from exc


@contextmanager
def context_bound_effect_window(
    context: ActiveContextSetV1,
    *,
    registry_store: VaultRegistryStore,
) -> Iterator[None]:
    """Fence a non-filesystem foreground read through response publication.

    Retrieval can publish cached or indexed material derived from a selected
    binding even where it does not itself open that binding's pathname. Reuse
    the same final-revalidation/shared-lease window for that effect.
    """

    with context_bound_read_window(context, registry_store=registry_store):
        yield


__all__ = [
    "ContextBoundReadError",
    "ContextBoundReadRoot",
    "context_bound_effect_window",
    "context_bound_read_window",
    "resolve_context_read_roots",
]
