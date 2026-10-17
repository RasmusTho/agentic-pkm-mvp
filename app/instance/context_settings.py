"""Fail-closed effective-settings resolution for an immutable read context."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

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
from app.vault.paths import resolve_vault_system_dir_rel
from app.vault.settings_service import RUNTIME_GATING_SETTINGS, SettingsService
from app.vault.active_context_v1 import ActiveContextSetV1


class IncompatibleBindingSettingsError(ContextBoundReadError):
    """A combined request would use inconsistent request-wide behavior."""


class UnclassifiedContextSettingError(ContextBoundReadError):
    """A setting reached a many-binding request without a registry classification."""


class BindingLocalPathEscapeError(ContextBoundReadError):
    """A binding-local path override would resolve outside its binding's root."""


SettingClassification = Literal["binding_local", "request_wide_must_match"]
BINDING_LOCAL: SettingClassification = "binding_local"
REQUEST_WIDE_MUST_MATCH: SettingClassification = "request_wide_must_match"

#: The process-wide vault path overrides (deferred from #6138 / PR #6159).
PROCESS_PATH_OVERRIDES: tuple[str, ...] = ("VAULT_SYSTEM_DIR_REL", "VAULT_LAYOUT_NOTE_REL")

#: Settings-registry classification for a many-binding request (MVR-05B4a,
#: ``docs/MULTI_VAULT_RUNTIME/ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md`` -- settings
#: keys are either ``binding_local`` or ``request_wide_must_match``). Every value a
#: combined request compares or isolates must be named here; an unnamed one fails
#: the request rather than defaulting to either class.
#:
#: ``VAULT_SYSTEM_DIR_REL`` / ``VAULT_LAYOUT_NOTE_REL`` are ``binding_local``: they
#: name a folder or note *inside a vault*, so even one process-wide value resolves
#: to a different, per-binding path under each binding's own root, and the vault's
#: own layout note may legitimately differ between bindings. They never shape the
#: combined result, so they are not compared; each must resolve inside its own
#: binding's root or the whole request fails before effect.
CONTEXT_SETTING_CLASSIFICATION: Mapping[str, SettingClassification] = MappingProxyType(
    {
        "providers": REQUEST_WIDE_MUST_MATCH,
        "llm_routing": REQUEST_WIDE_MUST_MATCH,
        "embedding_profiles": REQUEST_WIDE_MUST_MATCH,
        "retrieval_tuning": REQUEST_WIDE_MUST_MATCH,
        "ask": REQUEST_WIDE_MUST_MATCH,
        **{f"runtime:{key}": REQUEST_WIDE_MUST_MATCH for key in sorted(RUNTIME_GATING_SETTINGS)},
        "VAULT_SYSTEM_DIR_REL": BINDING_LOCAL,
        "VAULT_LAYOUT_NOTE_REL": BINDING_LOCAL,
    }
)


def setting_classification(key: str) -> SettingClassification:
    """The registry classification of ``key``; an unclassified key fails closed."""

    try:
        return CONTEXT_SETTING_CLASSIFICATION[key]
    except KeyError:
        raise UnclassifiedContextSettingError(
            f"setting {key!r} has no binding_local/request_wide_must_match classification"
        ) from None


@dataclass(frozen=True)
class ContextSettingsResolution:
    """Per-binding bundle provenance plus the compatible request-wide digest."""

    binding_bundle_digests: dict[str, str]
    request_wide_values: dict[str, object]
    ask_settings: AskSettings
    retrieval_tuning: RetrievalTuning
    llm_routing: LLMRoutingSettings
    #: Per binding, the resolved binding-local values (absolute, inside that root).
    binding_local_values: dict[str, dict[str, str | None]] = field(default_factory=dict)

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
    binding_local: dict[str, dict[str, str | None]] = {}
    have_initialized = 0
    first_bundle: SettingsBundle | None = None
    # Resolve every participating binding completely before comparing anything:
    # a conflict found at the last binding must not leave earlier work behind,
    # and no binding order may decide which value is reported.
    resolved: list[tuple[str, SettingsBundle, dict[str, object], dict[str, str | None]]] = []
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
        request_values = _request_wide_values(bundle, effective)
        local_values = _binding_local_values(Path(source.root))
        for key in (*request_values, *local_values):
            setting_classification(key)
        resolved.append((source.vault_binding_id, bundle, request_values, local_values))
    for binding_id, bundle, request_values, local_values in resolved:
        have_initialized += 1
        if first_bundle is None:
            first_bundle = bundle
        for key, value in request_values.items():
            if setting_classification(key) != REQUEST_WIDE_MUST_MATCH:
                raise UnclassifiedContextSettingError(f"setting {key!r} is not request-wide")
            if key in request_wide and request_wide[key] != value:
                raise IncompatibleBindingSettingsError("incompatible_binding_settings")
            request_wide[key] = value
        binding_local[binding_id] = local_values
        digests[binding_id] = _bundle_digest(bundle, request_values, local_values)
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
        binding_local_values=binding_local,
    )


def _confined(root: Path, relative: str, *, key: str) -> str:
    resolved_root = root.expanduser().resolve(strict=False)
    candidate = (resolved_root / relative).resolve(strict=False)
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise BindingLocalPathEscapeError(f"{key} resolves outside its binding's root")
    return str(candidate)


def _binding_local_values(root: Path) -> dict[str, str | None]:
    """Resolve the binding-local path overrides inside this binding's own root.

    The process-wide override (when set) applies to every binding, but always
    relative to and confined within each binding's root; an override that would
    escape a root fails the whole request before any read.
    """

    # Confine the raw overrides first: the system-folder resolution below may
    # itself follow the layout-note override.
    layout_rel = (os.getenv("VAULT_LAYOUT_NOTE_REL") or "").strip() or None
    layout_note = _confined(root, layout_rel, key="VAULT_LAYOUT_NOTE_REL") if layout_rel else None
    system_override = (os.getenv("VAULT_SYSTEM_DIR_REL") or "").strip() or None
    if system_override:
        _confined(root, system_override, key="VAULT_SYSTEM_DIR_REL")
    try:
        system_rel: str | None = resolve_vault_system_dir_rel(root).value
    except (ValueError, IndexError, OSError):
        # No resolvable system folder is a valid binding-local state, not a
        # request-wide one; the binding's own reads report it.
        system_rel = None
    return {
        "VAULT_SYSTEM_DIR_REL": (
            _confined(root, system_rel, key="VAULT_SYSTEM_DIR_REL") if system_rel else None
        ),
        "VAULT_LAYOUT_NOTE_REL": layout_note,
    }


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


def _bundle_digest(
    bundle: SettingsBundle,
    request_values: dict[str, object],
    local_values: dict[str, str | None] | None = None,
) -> str:
    material = {
        "bundle": bundle.model_dump(mode="json"),
        "request_wide": request_values,
        "binding_local": local_values or {},
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"context-settings.v2|{encoded}".encode()).hexdigest()


__all__ = [
    "BINDING_LOCAL",
    "BindingLocalPathEscapeError",
    "CONTEXT_SETTING_CLASSIFICATION",
    "ContextSettingsResolution",
    "IncompatibleBindingSettingsError",
    "PROCESS_PATH_OVERRIDES",
    "REQUEST_WIDE_MUST_MATCH",
    "UnclassifiedContextSettingError",
    "resolve_context_settings",
    "setting_classification",
]
