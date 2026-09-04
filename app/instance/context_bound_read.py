"""Canonical registry validation for immutable active-context filesystem reads.

The request snapshot deliberately carries stable binding provenance rather than
an ambient filesystem selection.  This seam turns those already-authorized
bindings into roots only after proving that the live registry still describes
the same binding revision.  A caller must use the returned roots for the whole
read operation; it cannot re-resolve a global vault midway through the request.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.instance.active_context_service import binding_revision_for
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


__all__ = ["ContextBoundReadError", "ContextBoundReadRoot", "resolve_context_read_roots"]
