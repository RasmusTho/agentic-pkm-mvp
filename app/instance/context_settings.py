"""Fail-closed effective-settings resolution for an immutable read context."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.instance.context_bound_read import ContextBoundReadError, resolve_context_read_roots
from app.settings.compiler import compile_all
from app.settings.models import (
    AskSettings,
    LLMRoutingSettings,
    RetrievalTuning,
    SettingsBundle,
)
from app.retrieval.tuning import resolve_retrieval_tuning
from app.instance.vault_registry import VaultRegistryStore
from app.vault.manager import VaultManager, is_vault_root
from app.vault.settings_service import RUNTIME_GATING_SETTINGS, SettingsService
from app.vault.active_context_v1 import ActiveContextSetV1


class IncompatibleBindingSettingsError(ContextBoundReadError):
    """A combined request would use inconsistent request-wide behavior."""


@dataclass(frozen=True)
class ContextSettingsResolution:
    """Per-binding bundle provenance plus the compatible request-wide digest."""

    binding_bundle_digests: dict[str, str]
    request_wide_values: dict[str, object]
    ask_settings: AskSettings
    retrieval_tuning: RetrievalTuning
    llm_routing: LLMRoutingSettings

    @property
    def cache_bundle_digest(self) -> str:
        """Digest complete per-binding settings provenance without values."""

        material = "|".join(
            f"{binding_id}={digest}"
            for binding_id, digest in sorted(self.binding_bundle_digests.items())
        )
        return hashlib.sha256(f"active-context-settings.v1|{material}".encode()).hexdigest()


def resolve_context_settings(
    context: ActiveContextSetV1,
    *,
    registry_store: VaultRegistryStore,
) -> ContextSettingsResolution:
    """Resolve every initialized source before a many-binding effect.

    Resolve the complete effective bundle for every initialized binding before
    any read, cache, retrieval, or model work.  Values that shape a combined
    request (provider/model routing, retrieval policy, ASK limits/prompt, and
    runtime gates) must agree exactly; a first binding never wins by accident.
    A provisional root has no settings bundle yet and is deliberately left
    out: it is readable but not eligible for an initialized combined settings
    operation.
    """

    roots = resolve_context_read_roots(context, registry_store=registry_store)
    service = SettingsService()
    digests: dict[str, str] = {}
    request_wide: dict[str, object] = {}
    have_initialized = 0
    first_bundle: SettingsBundle | None = None
    for source in roots:
        if not is_vault_root(Path(source.root)):
            continue
        try:
            vault_context = VaultManager().validate_vault(source.root)
            effective = service.resolve(vault_context).settings
            bundle = (
                compile_all(auto_heal=False, vault_root=Path(source.root), publish=False)
                if Path(source.root).is_dir()
                else SettingsBundle()
            )
        except Exception as exc:
            raise ContextBoundReadError("active context settings are unavailable") from exc
        have_initialized += 1
        if first_bundle is None:
            first_bundle = bundle
        request_values = _request_wide_values(bundle, effective)
        for key, value in request_values.items():
            if key in request_wide and request_wide[key] != value:
                raise IncompatibleBindingSettingsError("incompatible_binding_settings")
            request_wide[key] = value
        digests[source.vault_binding_id] = _bundle_digest(bundle, request_values)
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
    selected = first_bundle or SettingsBundle()
    return ContextSettingsResolution(
        digests,
        request_wide,
        ask_settings=_ask_settings(selected),
        retrieval_tuning=resolve_retrieval_tuning(selected.retrieval_tuning),
        llm_routing=selected.llm_routing,
    )


def _ask_settings(bundle: SettingsBundle) -> AskSettings:
    value = bundle.agents.get("ask")
    return value if isinstance(value, AskSettings) else AskSettings()


def _request_wide_values(bundle: SettingsBundle, effective: Any) -> dict[str, object]:
    """Return only typed values that can change a combined read/model result."""

    values: dict[str, object] = {
        "providers": bundle.providers.model_dump(mode="json"),
        "llm_routing": bundle.llm_routing.model_dump(mode="json"),
        "embedding_profiles": bundle.embedding_profiles.model_dump(mode="json"),
        "retrieval_tuning": bundle.retrieval_tuning.model_dump(mode="json"),
        "ask": _ask_settings(bundle).model_dump(mode="json"),
    }
    for key in RUNTIME_GATING_SETTINGS:
        values[f"runtime:{key}"] = getattr(effective[key], "value")
    return values


def _bundle_digest(bundle: SettingsBundle, request_values: dict[str, object]) -> str:
    material = {
        "bundle": bundle.model_dump(mode="json"),
        "request_wide": request_values,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"context-settings.v2|{encoded}".encode()).hexdigest()


__all__ = [
    "ContextSettingsResolution",
    "IncompatibleBindingSettingsError",
    "resolve_context_settings",
]
