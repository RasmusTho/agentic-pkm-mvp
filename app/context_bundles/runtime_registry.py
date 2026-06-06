"""Process-local addressability cache for emitted ContextBundles (#1592).

The registry lets runtime consumers resolve bundles that were already emitted
in this process. It is not persistence, memory, knowledge, or authority.
"""
from __future__ import annotations

from collections import OrderedDict

from app.context_bundles.schema import ContextBundle

_MAX_EMITTED_BUNDLES = 128
_EMITTED_BUNDLES: OrderedDict[str, ContextBundle] = OrderedDict()


def _enforce_registry_bound() -> None:
    if _MAX_EMITTED_BUNDLES <= 0:
        _EMITTED_BUNDLES.clear()
        return
    while len(_EMITTED_BUNDLES) > _MAX_EMITTED_BUNDLES:
        _EMITTED_BUNDLES.popitem(last=False)


def register_emitted_bundle(bundle: ContextBundle) -> ContextBundle:
    """Record an emitted bundle for process-local lookup.

    A deep copy is stored and returned so later caller mutation cannot silently
    rewrite the registry entry.
    """
    stored = bundle.model_copy(deep=True)
    _EMITTED_BUNDLES[stored.id] = stored
    _EMITTED_BUNDLES.move_to_end(stored.id)
    _enforce_registry_bound()
    return stored.model_copy(deep=True)


def get_emitted_bundle(bundle_id: str) -> ContextBundle | None:
    """Return a copy of the emitted bundle for ``bundle_id`` if present."""
    bundle = _EMITTED_BUNDLES.get(bundle_id)
    if bundle is None:
        return None
    _EMITTED_BUNDLES.move_to_end(bundle_id)
    return bundle.model_copy(deep=True)


def clear_emitted_bundles() -> None:
    """Clear the process-local registry.

    This is intended for deterministic tests and process lifecycle hygiene.
    """
    _EMITTED_BUNDLES.clear()


__all__ = [
    "clear_emitted_bundles",
    "get_emitted_bundle",
    "register_emitted_bundle",
]
