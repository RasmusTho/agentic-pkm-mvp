"""The live producing binding of carrier-free (compatibility) panel effects.

MVR-05B4c2: ``COMPATIBILITY_BINDING_ID`` is only the transitional namespace for rows
inherited from the single-vault runtime. When an instance registry is bound, the
vault a carrier-free request writes to is a registered binding with a real id, and a
scoped request selecting that same vault presents that id. Producers therefore stamp
the durable compatibility binding, and a carrier-free view spans it, the sentinel and
unstamped legacy entries.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.instance.settings_rebind import SettingsRebindStore
from app.instance.filesystem_identity import (
    resolve_filesystem_root_identity,
    same_filesystem_root,
)
from app.instance.vault_registry import VaultRegistryStore


class CompatibilityBindingUnavailableError(RuntimeError):
    """A configured registry cannot prove the compatibility binding (fail closed)."""


def live_compatibility_binding_id() -> str:
    """The durable compatibility binding id.

    The legacy sentinel is reserved for the explicit no-registry journeys: the
    registry env is unset, the configured registry is not provisioned yet, or the
    pre-floor journey where no settings rebind is installed (the process selection
    is the only binding). A configured but unreadable registry, or an unresolved
    rebind record, raises ``CompatibilityBindingUnavailableError`` so the emitting
    or staging operation fails closed instead of misattributing its stamp.

    Read-only and lock-free: callers are already inside the compatibility seal.
    """

    raw_path = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    if not raw_path:
        return COMPATIBILITY_BINDING_ID
    registry = VaultRegistryStore(Path(raw_path).expanduser().resolve(strict=False))
    if not registry.path.exists():
        return COMPATIBILITY_BINDING_ID
    try:
        snapshot = registry.load()
        if snapshot.settings_rebind is None:
            return COMPATIBILITY_BINDING_ID
        return SettingsRebindStore(registry).compatibility_binding_id()
    except Exception as exc:
        raise CompatibilityBindingUnavailableError(
            "compatibility binding is not provable"
        ) from exc


def compatibility_binding_for_root(root: Path) -> str:
    """The live compatibility binding, proven to be the vault at ``root``.

    For producers that write a vault root they were handed (rather than the
    sealed selection): once a registry binding is live, ``root`` must be that
    binding's registered root, or the producer fails closed before any write
    instead of stamping another vault's binding. The no-registry journeys return
    the legacy sentinel unchanged.
    """

    live = live_compatibility_binding_id()
    if live == COMPATIBILITY_BINDING_ID:
        return live
    raw_path = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    try:
        registry = VaultRegistryStore(Path(raw_path).expanduser().resolve(strict=False))
        registration = registry.load().registrations.get(live)
        if registration is None:
            raise CompatibilityBindingUnavailableError("compatibility binding is not registered")
        if same_filesystem_root(
            resolve_filesystem_root_identity(Path(root)),
            resolve_filesystem_root_identity(Path(registration.path)),
        ):
            return live
    except CompatibilityBindingUnavailableError:
        raise
    except Exception as exc:
        raise CompatibilityBindingUnavailableError("compatibility binding is not provable") from exc
    raise CompatibilityBindingUnavailableError(
        "vault root is not the live compatibility binding's registered root"
    )


def legacy_view_bindings() -> tuple[str | None, ...]:
    """Stamps a carrier-free view addresses: live compat binding, sentinel, unstamped.

    A read never stamps anything, so an unprovable compatibility binding narrows the
    view to the sentinel and unstamped entries instead of failing the read.
    """

    try:
        live = live_compatibility_binding_id()
    except CompatibilityBindingUnavailableError:
        return (COMPATIBILITY_BINDING_ID, None)
    if live == COMPATIBILITY_BINDING_ID:
        return (COMPATIBILITY_BINDING_ID, None)
    return (live, COMPATIBILITY_BINDING_ID, None)
