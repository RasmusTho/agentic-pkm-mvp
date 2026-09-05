"""Fail-closed effective-settings resolution for an immutable read context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.instance.context_bound_read import ContextBoundReadError, resolve_context_read_roots
from app.instance.vault_registry import VaultRegistryStore
from app.vault.manager import VaultManager, is_vault_root
from app.vault.settings_bundle import settings_bundle_digest
from app.vault.settings_service import RUNTIME_GATING_SETTINGS, SettingsService
from app.vault.active_context_v1 import ActiveContextSetV1


class IncompatibleBindingSettingsError(ContextBoundReadError):
    """A combined request would use inconsistent request-wide behavior."""


@dataclass(frozen=True)
class ContextSettingsResolution:
    """Per-binding bundle provenance plus the compatible request-wide digest."""

    binding_bundle_digests: dict[str, str]
    request_wide_values: dict[str, object]

    @property
    def context_settings_digest(self) -> str:
        """Stable provenance for the complete selected-binding settings set."""

        import hashlib
        import json

        return hashlib.sha256(
            json.dumps(self.binding_bundle_digests, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def resolve_context_settings(
    context: ActiveContextSetV1,
    *,
    registry_store: VaultRegistryStore,
) -> ContextSettingsResolution:
    """Resolve every initialized source before a many-binding effect.

    The canonical settings registry already classifies runtime-gating keys.
    Those are the current request-wide behavior keys; all other Settings
    Spine values remain local to their binding.  A provisional root has no
    settings bundle yet and is deliberately left out: it is readable but not
    eligible for an initialized combined settings operation.
    """

    roots = resolve_context_read_roots(context, registry_store=registry_store)
    service = SettingsService()
    digests: dict[str, str] = {}
    request_wide: dict[str, object] = {}
    have_initialized = 0
    for source in roots:
        if not is_vault_root(Path(source.root)):
            continue
        try:
            effective = service.resolve(VaultManager().validate_vault(source.root)).settings
        except Exception as exc:
            raise ContextBoundReadError("active context settings are unavailable") from exc
        have_initialized += 1
        # EffectiveSetting structurally supplies the digest protocol; mypy
        # cannot infer that from its dataclass field declaration.
        digests[source.vault_binding_id] = settings_bundle_digest(effective)  # type: ignore[arg-type]
        for key in RUNTIME_GATING_SETTINGS:
            value = effective[key].value
            if key in request_wide and request_wide[key] != value:
                raise IncompatibleBindingSettingsError("incompatible_binding_settings")
            request_wide[key] = value
    # A one-binding or provisional read needs no synthetic agreement.  The
    # iteration still occurred for every initialized selected binding, so a
    # future registry classification cannot accidentally become first-wins.
    if len(roots) > 1 and have_initialized == 0:
        raise ContextBoundReadError("active context settings are unavailable")
    return ContextSettingsResolution(digests, request_wide)


__all__ = [
    "ContextSettingsResolution",
    "IncompatibleBindingSettingsError",
    "resolve_context_settings",
]
