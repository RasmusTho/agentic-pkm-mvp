"""Process-local addressability cache for emitted ContextBundles (#1592).

The registry lets runtime consumers resolve bundles that were already emitted
in this process. It is not persistence, memory, knowledge, or authority.

MVR-05B4c5: every entry is keyed by (emitting binding, bundle id), so two
bindings emitting the same id stay independently addressable and a lookup never
returns another binding's bundle. A carrier-free emission is not retrieved under
a binding filter, so it registers unstamped (``None``): only the carrier-free
legacy view can see it, never a scoped lookup.
"""
from __future__ import annotations

from collections import OrderedDict

from app.context_bundles.schema import ContextBundle

_MAX_EMITTED_BUNDLES = 128
_RegistryKey = tuple[str | None, str]
_EMITTED_BUNDLES: OrderedDict[_RegistryKey, ContextBundle] = OrderedDict()


def _enforce_registry_bound() -> None:
    if _MAX_EMITTED_BUNDLES <= 0:
        _EMITTED_BUNDLES.clear()
        return
    while len(_EMITTED_BUNDLES) > _MAX_EMITTED_BUNDLES:
        _EMITTED_BUNDLES.popitem(last=False)


def _legacy_view() -> tuple[str | None, ...]:
    from app.instance.compatibility_binding import legacy_view_bindings

    return legacy_view_bindings()


def register_emitted_bundle(
    bundle: ContextBundle, *, vault_binding_id: str | None = None
) -> ContextBundle:
    """Record an emitted bundle under its emitting binding for process-local lookup.

    ``vault_binding_id`` is the scoped request's binding, whose retrieval was
    filtered to the request's bindings. A carrier-free caller omits it and the
    bundle is registered unstamped. A deep copy is
    stored and returned so later caller mutation cannot silently rewrite the
    registry entry.
    """
    stored = bundle.model_copy(deep=True)
    key = (vault_binding_id, stored.id)
    _EMITTED_BUNDLES[key] = stored
    _EMITTED_BUNDLES.move_to_end(key)
    _enforce_registry_bound()
    return stored.model_copy(deep=True)


def get_emitted_bundle(
    bundle_id: str, *, vault_binding_id: str | None = None
) -> ContextBundle | None:
    """Return a copy of the emitted bundle for ``bundle_id`` if visible.

    A scoped read (``vault_binding_id``) sees only that binding's own entry, so a
    foreign or unstamped bundle is indistinguishable from an unknown id. A
    carrier-free read sees the legacy view: the live compatibility binding, the
    no-registry sentinel and unstamped entries.
    """
    bindings = (vault_binding_id,) if vault_binding_id is not None else _legacy_view()
    for binding in bindings:
        key = (binding, bundle_id)
        bundle = _EMITTED_BUNDLES.get(key)
        if bundle is not None:
            _EMITTED_BUNDLES.move_to_end(key)
            return bundle.model_copy(deep=True)
    return None


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
