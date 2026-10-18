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
from app.instance.vault_registry import VaultRegistryStore


def live_compatibility_binding_id() -> str:
    """The durable compatibility binding id, or the sentinel when none is bound.

    Read-only and lock-free: callers are already inside the compatibility seal.
    """

    raw_path = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    if not raw_path:
        return COMPATIBILITY_BINDING_ID
    try:
        registry = VaultRegistryStore(Path(raw_path).expanduser().resolve(strict=False))
        if not registry.path.exists():
            return COMPATIBILITY_BINDING_ID
        return SettingsRebindStore(registry).compatibility_binding_id()
    except Exception:
        return COMPATIBILITY_BINDING_ID


def legacy_view_bindings() -> tuple[str | None, ...]:
    """Stamps a carrier-free view addresses: live compat binding, sentinel, unstamped."""

    live = live_compatibility_binding_id()
    if live == COMPATIBILITY_BINDING_ID:
        return (COMPATIBILITY_BINDING_ID, None)
    return (live, COMPATIBILITY_BINDING_ID, None)
