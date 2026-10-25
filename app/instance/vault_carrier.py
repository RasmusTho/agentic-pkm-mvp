"""Explicit vault carrier for the non-HTTP request carriers (MVR-05B4a, #6160).

The HTTP routes bind each request to one immutable ActiveContextSet. The agent,
MCP and CLI carriers have no request headers, so they receive the same decision
as a ``VaultCarrier``: exactly one resolution, made once at the carrier's entry
(a scoped context, an explicit operator selection, the instance default, a named
compatibility fallback, or no-vault), and then passed down explicitly. Nothing
below the entry point re-reads process selection or a vault environment key.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.instance.context_bound_read import ContextBoundReadError, resolve_context_read_roots
from app.instance.vault_registry import VaultRegistryStore
from app.vault.active_context_v1 import ActiveContextSetV1

CarrierSource = Literal[
    "active_context",
    "explicit_selection",
    "instance_default",
    "compatibility",
    "no_vault",
]


@dataclass(frozen=True)
class VaultCarrier:
    """One immutable vault resolution handed to a non-HTTP carrier."""

    source: CarrierSource
    root: Path | None
    vault_binding_id: str | None = None
    context_generation: int | None = None
    #: How the source was chosen (selection provenance, adapter name); for receipts.
    provenance: str = ""

    @property
    def is_no_vault(self) -> bool:
        return self.root is None

    @property
    def is_scoped(self) -> bool:
        """A carrier taken from a scoped session/override context (sealed for writes pre-05C)."""

        return self.source == "active_context"


def carrier_from_active_context(
    context: ActiveContextSetV1,
    *,
    registry_store: VaultRegistryStore,
) -> VaultCarrier:
    """Bind a single-vault carrier to a scoped context's one source binding.

    The root comes from live registry truth revalidated against the context's
    binding revision, never from a path, display name or process selection. A
    healthy zero-binding context is a scoped no-vault carrier; a many-binding
    context cannot be narrowed to one vault by the carrier and fails closed.
    """

    roots = resolve_context_read_roots(context, registry_store=registry_store)
    if not roots:
        return VaultCarrier(
            source="active_context",
            root=None,
            context_generation=context.generation,
            provenance=context.selection_provenance,
        )
    if len(roots) != 1:
        raise ContextBoundReadError("a single-vault carrier requires exactly one context binding")
    (bound,) = roots
    return VaultCarrier(
        source="active_context",
        root=bound.root,
        vault_binding_id=bound.vault_binding_id,
        context_generation=bound.context_generation,
        provenance=context.selection_provenance,
    )


__all__ = ["CarrierSource", "VaultCarrier", "carrier_from_active_context"]
