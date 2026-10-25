"""Process-local addressability cache for emitted ContextBundles (#1592).

The registry lets runtime consumers resolve bundles that were already emitted
in this process. It is not persistence, memory, knowledge, or authority.

MVR-05B4c5: every entry is keyed by (emitting binding, emitting context
identity, bundle id). A scoped emission is retrieved under its request's
ActiveContextSet, so only a lookup with that same full context identity (same
binding, scope, principal, filter, selection, ...) can address it: two bindings
or two contexts emitting the same id stay independently addressable, and a
lookup never returns content retrieved under another context. A carrier-free
emission is not retrieved under a binding filter, so it registers unstamped
(``None``, ``None``) and only a carrier-free lookup can see it.
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import Protocol

from app.context_bundles.schema import ContextBundle

_MAX_EMITTED_BUNDLES = 128
_RegistryKey = tuple[str | None, str | None, str]
_EMITTED_BUNDLES: OrderedDict[_RegistryKey, ContextBundle] = OrderedDict()
# Sync route handlers run in worker threads: every registry operation holds this
# lock, so a concurrent registration never races a lookup or the size bound.
_REGISTRY_LOCK = threading.Lock()


class _ContextIdentity(Protocol):
    def context_identity_components(self) -> tuple[str, ...]: ...


def emitted_bundle_context_key(context: _ContextIdentity) -> str:
    """Non-reversible digest of a request context's full identity."""

    material = "\n".join(context.context_identity_components())
    return hashlib.sha256(f"emitted-context-bundle:{material}".encode()).hexdigest()


def _enforce_registry_bound() -> None:
    if _MAX_EMITTED_BUNDLES <= 0:
        _EMITTED_BUNDLES.clear()
        return
    while len(_EMITTED_BUNDLES) > _MAX_EMITTED_BUNDLES:
        _EMITTED_BUNDLES.popitem(last=False)


def _key(bundle_id: str, vault_binding_id: str | None, context_key: str | None) -> _RegistryKey:
    if (vault_binding_id is None) != (context_key is None):
        raise ValueError("a scoped registry key needs both a binding and a context key")
    return (vault_binding_id, context_key, bundle_id)


def register_emitted_bundle(
    bundle: ContextBundle,
    *,
    vault_binding_id: str | None = None,
    context_key: str | None = None,
) -> ContextBundle:
    """Record an emitted bundle under its emitting binding and context.

    A scoped emission passes its request binding and
    :func:`emitted_bundle_context_key` of its ActiveContextSet; a carrier-free
    emission passes neither and is registered unstamped. A deep copy is stored
    and returned so later caller mutation cannot silently rewrite the entry.
    """
    stored = bundle.model_copy(deep=True)
    key = _key(stored.id, vault_binding_id, context_key)
    with _REGISTRY_LOCK:
        _EMITTED_BUNDLES[key] = stored
        _EMITTED_BUNDLES.move_to_end(key)
        _enforce_registry_bound()
    return stored.model_copy(deep=True)


def get_emitted_bundle(
    bundle_id: str,
    *,
    vault_binding_id: str | None = None,
    context_key: str | None = None,
) -> ContextBundle | None:
    """Return a copy of the emitted bundle for ``bundle_id`` if visible.

    A scoped lookup sees only the entry its own binding and full context
    identity registered, so a foreign, other-context, unstamped or unknown id is
    indistinguishable. A carrier-free lookup sees only unstamped entries.
    """
    key = _key(bundle_id, vault_binding_id, context_key)
    with _REGISTRY_LOCK:
        bundle = _EMITTED_BUNDLES.get(key)
        if bundle is None:
            return None
        _EMITTED_BUNDLES.move_to_end(key)
        return bundle.model_copy(deep=True)


def clear_emitted_bundles() -> None:
    """Clear the process-local registry.

    This is intended for deterministic tests and process lifecycle hygiene.
    """
    with _REGISTRY_LOCK:
        _EMITTED_BUNDLES.clear()


__all__ = [
    "clear_emitted_bundles",
    "emitted_bundle_context_key",
    "get_emitted_bundle",
    "register_emitted_bundle",
]
